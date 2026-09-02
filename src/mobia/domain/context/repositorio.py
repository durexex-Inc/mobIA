import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.auditoria import causas_do_recalculo
from mobia.domain.context.models import (
    ConversationSummary,
    LeadQualification,
    LeadScoreAudit,
    aad_do_resumo,
)
from mobia.domain.context.score import Score, calcular_score
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.infra.crypto import decrypt, encrypt

log = structlog.get_logger(__name__)

# Sai de `Extracao` e nao de uma lista escrita a mao: e a mesma fonte de onde
# `SCHEMA_DA_EXTRACAO` deriva, entao a proxima card que acrescentar campo nao
# precisa lembrar deste lugar.
_CAMPOS_DA_EXTRACAO = frozenset(campo.name for campo in fields(Extracao))

# O orcamento e o unico campo cujo nome NAO e o mesmo nos tres lugares, e a
# TEC-146 criou essa divergencia sem querer:
#
#   o modelo diz     `faixa_preco_expressao`  (unica chave de preco do
#                                              SCHEMA_DA_EXTRACAO)
#   o banco guarda   `faixa_preco_min_centavos` / `faixa_preco_max_centavos`
#   o prompt exibe   `faixa_preco_min` / `faixa_preco_max`  (ruling R6:
#                                              reais, sob as chaves antigas)
#
# A marca de "(perguntado, sem resposta)" viaja da primeira coluna para a
# terceira, e depois do rename ela nao chegava em ponto nenhum: o nome que o
# modelo pode dizer nao e campo de `Extracao` (era descartado como vocabulario
# desconhecido, com `estado.campo_perguntado_desconhecido` no log), e mesmo
# escrito na forma do banco nunca casaria a chave que `_texto_do_estado`
# renderiza. Resultado: o agente podia reperguntar o orcamento a cada turno,
# para sempre, sem nenhum teste ficando vermelho -- o mesmo modo de falha
# silencioso que a TEC-257 documentou ao criar esta maquinaria.
#
# A traducao mora aqui porque aqui e onde os tres vocabularios se encontram.
# O alvo e `faixa_preco_max`, que e o nome que a marca tinha antes desta
# branch, quando os tres coincidiam -- entao o texto do prompt volta a ser
# byte-identico ao de antes tambem neste caminho. `faixa_preco_min` de
# proposito nao recebe marca: orcamento e UM assunto, e duas linhas de marca
# para uma pergunta so gastariam prompt dizendo a mesma coisa.
_MARCA_DO_ORCAMENTO = "faixa_preco_max"
_NOME_DA_MARCA = {
    "faixa_preco_expressao": _MARCA_DO_ORCAMENTO,
    "faixa_preco_min_centavos": _MARCA_DO_ORCAMENTO,
    "faixa_preco_max_centavos": _MARCA_DO_ORCAMENTO,
}


def _marca_de(nome: str) -> str | None:
    """O nome sob o qual a marca deste campo e gravada, ou `None` se o nome
    nao pertence a vocabulario nenhum que este modulo conheca."""
    if nome in _NOME_DA_MARCA:
        return _NOME_DA_MARCA[nome]
    return nome if nome in _CAMPOS_DA_EXTRACAO else None


# Um nome de campo e minusculas e underscore. O que nao casa nao vai para o
# log: o modelo pode devolver o texto da pergunta em vez do nome, e texto de
# pergunta carrega o que o lead disse.
#
# Risco residual, aceito e nao eliminado: o regex barra frase -- tem espaco,
# maiuscula, acento, pontuacao -- mas nao barra um token isolado, minusculo,
# sem acento e sem digito. Um valor do lead nessa forma ("pinheiros", "sim")
# passa no fullmatch e vai literal para `nomes=[...]` do log.warning abaixo.
# Nao existe filtro estrutural que separe esse token de um nome de campo
# legitimo que o modelo inventou (ex.: "bairro") -- os dois sao a mesma forma
# sintatica, e distinguir os dois e exatamente o que este log existe para
# mostrar. Trocar o nome por so uma contagem fecharia esse buraco, mas
# destruiria o diagnostico que fez `perguntou` ser lista de string em vez de
# enum: pagaria o preco da forma cara sem comprar o beneficio dela. E a
# exposicao so acontece quando o modelo poe um valor onde deveria por um nome
# de campo -- caso em que queremos ver, porque significa que a declaracao do
# modelo quebrou.
_NOME_PLAUSIVEL = re.compile(r"[a-z_]{1,32}")


@dataclass(frozen=True)
class ResumoDaConversa:
    """O resumo ja decifrado, com a marca do que ele cobre."""

    texto: str
    watermark_created_at: datetime
    watermark_message_id: uuid.UUID
    mensagens_cobertas: int
    modelo: str


async def ler_resumo(
    session: AsyncSession, channel: str, conversation_key: str
) -> ResumoDaConversa | None:
    linha = await session.get(ConversationSummary, (channel, conversation_key))
    if linha is None:
        return None
    texto = decrypt(bytes(linha.resumo), aad_do_resumo(channel, conversation_key))
    if texto is None:
        # `assert` some sob `python -O` e o dataclass sairia com `texto=None`
        # contra a propria anotacao, para o prompt e para a contagem. A coluna
        # e NOT NULL, entao chegar aqui e garantia quebrada -- falhar alto.
        raise ValueError("resumo decifrou como nulo, mas a coluna e NOT NULL")
    return ResumoDaConversa(
        texto=texto,
        watermark_created_at=linha.watermark_created_at,
        watermark_message_id=linha.watermark_message_id,
        mensagens_cobertas=linha.mensagens_cobertas,
        modelo=linha.modelo,
    )


async def gravar_resumo(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    texto: str,
    watermark_created_at: datetime,
    watermark_message_id: uuid.UUID,
    mensagens_cobertas: int,
    modelo: str,
) -> None:
    """Upsert: uma conversa tem um resumo, nao um historico deles.

    Nao commita -- a sessao e emprestada, como em `ler_resumo` e `ler_estado`,
    e quem chama e dono da fronteira da transacao. Isso importa a partir da
    TEC-145: gravar o resumo junto com outro estado na mesma transacao exige
    que nada aqui a feche antes da hora.
    """
    cifrado = encrypt(texto, aad_do_resumo(channel, conversation_key))
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "resumo": cifrado,
        "watermark_created_at": watermark_created_at,
        "watermark_message_id": watermark_message_id,
        "mensagens_cobertas": mensagens_cobertas,
        "modelo": modelo,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationSummary).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in (
                    "resumo",
                    "watermark_created_at",
                    "watermark_message_id",
                    "mensagens_cobertas",
                    "modelo",
                    "updated_at",
                )
            },
            # Guarda de monotonia: a marca so anda para frente. Dois turnos
            # concorrentes da mesma conversa leem o mesmo estado, dobram e
            # gravam; sem esta condicao o mais lento sobrescreve o mais rapido,
            # a marca recua e as mensagens entre as duas marcas sao dobradas
            # duas vezes -- conteudo duplicado no resumo, para sempre. `<=` e
            # nao `<` porque a compressao regrava a mesma marca de proposito:
            # ela so encurta o texto, nao cobre mensagem nova.
            where=ConversationSummary.watermark_created_at
            <= statement.excluded.watermark_created_at,
        )
    )


async def ler_estado(
    session: AsyncSession, channel: str, conversation_key: str
) -> LeadQualification | None:
    resultado = await session.execute(
        select(LeadQualification).where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
    )
    return resultado.scalar_one_or_none()


def campos_a_gravar(intencao: Intencao, extracao: Extracao) -> dict[str, Any]:
    """A regra unica de acumulacao do estado de qualificacao.

    Compartilhada entre `gravar_estado` (producao) e o runner do eval
    (`_rodar_conversa` em `evals/test_acuracia_de_intencao.py`), porque o
    corpus anotado da TEC-145 media a extracao com uma copia divergente desta
    regra: nao honrava a guarda de `FORA_DE_ESCOPO` e nunca acumulava
    `intencao`, entao o `LeadQualification` sintetico do eval nunca carregava
    a linha `intencao: X` que o prompt de producao carrega a partir do
    segundo turno (`montagem._texto_do_estado`). Extrair a regra para uma
    funcao so fecha as duas frentes de uma vez: nao ha como o eval divergir de
    novo sem que os dois lados divirjam da mesma chamada.

    Devolve os campos **deste turno**, prontos para entrar num
    `dict.update` (runner) ou num `ON CONFLICT DO UPDATE` (aqui) por cima do
    estado anterior -- "mais novo vence" e responsabilidade de quem chama, nao
    desta funcao.

    - `FORA_DE_ESCOPO` nao grava nada: dict vazio. A guarda vive aqui, no
      unico lugar que os dois chamadores passam, para que nao haja como
      esquece-la num terceiro caminho futuro. Repare que ela tambem nao
      **apaga**: um dict vazio nao entra no `update`/`SET`, entao o lead que
      qualificou e depois mandou uma piada continua com o que disse.
    - `None` no campo nao apaga: so os campos que `Extracao.preenchidos()`
      devolveu (os que o lead de fato informou neste turno) entram.
    - `intencao` entra quando ha gravacao e quando ela diz alguma coisa. Ela
      vem de fora, do classificador, e nunca da extracao -- a tabela
      `conversation_intent` e esta coluna guardam o mesmo fato, e duas fontes
      para ele divergiriam, o que apareceria como bug de score na TEC-150.
    - **`INDEFINIDA` nao sobrescreve `intencao`** (TEC-147). Era a unica
      coluna desta tabela que violava o "None nao apaga" logo acima:
      `INDEFINIDA` e, no comentario do proprio enum, "ainda nao da para
      saber", e o classificador pode devolve-la em qualquer turno -- um
      "obrigado" no meio da conversa basta. Deixando-a sobrescrever, um lead
      que ja tinha dito COMPRA deixava de ser qualificado (`esta_qualificado`
      so ve a linha atual e nao tem como saber que houve intencao melhor
      antes) e disparava `lead.qualificado` DE NOVO ao voltar ao assunto --
      a taxa da RN-17.1 contando travessias em vez de leads. Os campos de
      extracao do turno continuam gravando normalmente: o lead que diz
      "zona sul" sem deixar claro se compra ou aluga informou a regiao.

      Consequencia aceita, e ela e o "marcar de menos" que `campos_a_marcar`
      ja declara como o erro seguro: um turno `INDEFINIDA` sem extracao
      nenhuma agora devolve dict vazio, entao nao grava linha e nao grava
      marca de "perguntado, sem resposta". O primeiro turno de uma conversa
      que so diz "oi" deixa de criar linha com `intencao: INDEFINIDA` --
      linha que nao dizia nada e que o prompt renderizava assim mesmo.
    """
    if intencao is Intencao.FORA_DE_ESCOPO:
        return {}
    if intencao is Intencao.INDEFINIDA:
        return extracao.preenchidos()
    return {"intencao": intencao.value, **extracao.preenchidos()}


def campos_a_marcar(perguntou: Iterable[str], preenchidos: Iterable[str]) -> set[str]:
    """Os campos que o agente perguntou neste turno e o lead nao respondeu.

    A regra unica de marcacao da TEC-257, compartilhada entre `gravar_estado`
    (producao) e o runner do eval, pela mesma razao que `campos_a_gravar`:
    duas copias divergiriam, e a divergencia so apareceria na borda.

    `perguntou` vem do modelo, que declara sobre o que perguntou. Os nomes
    passam por `_NOME_DA_MARCA` antes de qualquer coisa -- o orcamento tem tres
    nomes desde a TEC-146, e o unico que o modelo pode dizer nao e campo de
    `Extracao`. Ver o comentario daquela tabela.

    **Nome que nao pertence a vocabulario nenhum e descartado**, nao corrigido
    nem adivinhado: com a marca permanente, marcar de mais mata o campo pela
    vida da conversa e sem rastro, enquanto marcar de menos custa uma pergunta
    a mais. O descarte e logado para a deriva de vocabulario do modelo ser
    visivel --
    era a critica que a card fazia ao proxy de palavra-chave.

    `preenchidos` sao os campos que este turno gravou. A subtracao e o que
    separa esta marca do proxy irmao: campo que o estado JA SABE e
    reperguntado e assunto de `_reperguntou`, nao daqui.

    A subtracao usa os campos **deste** turno, e nao o estado acumulado, para
    nao pagar uma consulta a mais. Uma marca sobre campo que ja estava
    preenchido de um turno anterior e possivel por esse caminho, e e inerte:
    `_texto_do_estado` mostra o valor quando ele existe, e a marca so aparece
    onde nao ha valor. Valor vence marca -- e um valor, uma vez gravado,
    nunca e apagado (`None` nao apaga).
    """
    conhecidos: set[str] = set()
    ignorados: list[str] = []
    # dict.fromkeys em vez de iterar `perguntou` direto: sem dedupe, um nome
    # repetido (["bairro", "bairro"]) entraria duas vezes em `ignorados`, e o
    # `len(ignorados) - len(plausiveis)` abaixo contaria a segunda ocorrencia
    # como se o filtro de PII tivesse suprimido alguem -- um `descartados=1`
    # mentindo sobre uma supressao que nunca aconteceu, no unico instrumento
    # que esta card tem para essa deriva.
    for nome in dict.fromkeys(perguntou):
        marca = _marca_de(nome)
        if marca is None:
            ignorados.append(nome)
        else:
            conhecidos.add(marca)

    if ignorados:
        plausiveis = sorted({n for n in ignorados if _NOME_PLAUSIVEL.fullmatch(n)})
        log.warning(
            "estado.campo_perguntado_desconhecido",
            nomes=plausiveis,
            descartados=len(ignorados) - len(plausiveis),
        )

    # `preenchidos` passa pela mesma traducao: um turno que gravou QUALQUER
    # extremo do orcamento respondeu a pergunta sobre orcamento. Sem isto,
    # "a partir de 300 mil" (que so preenche o minimo) deixaria a marca de
    # `faixa_preco_max` de pe sobre um campo que o lead acabou de responder --
    # marcar de MAIS, que e o erro caro, porque a marca e permanente.
    return conhecidos - {_marca_de(nome) or nome for nome in preenchidos}


async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
    perguntou: Iterable[str] = (),
) -> LeadQualification | None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia.

    Devolve a linha que o `RETURNING` trouxe -- o que o banco de fato gravou,
    ja acumulado com o que a linha tinha antes deste turno, e nao so os
    campos que este turno passou. A alternativa seria recompor a acumulacao
    em Python (estado anterior + `campos_a_gravar`), o que criaria uma
    terceira copia da regra: `campos_a_gravar` existe precisamente para que
    producao e o runner do eval nao divirjam cada um com a sua copia, e uma
    copia a mais so para uma linha de log repetiria o mesmo erro. `RETURNING`
    devolve o valor sem consulta extra e sem essa copia -- a TEC-147 usa isso
    para o turno comparar o estado antes e depois da escrita.

    Nao commita -- a sessao e emprestada, como em `ler_resumo`, `ler_estado` e
    `gravar_resumo`, e quem chama e dono da fronteira da transacao.

    A regra dos campos mora em `campos_a_gravar` e a da marca em
    `campos_a_marcar`, e nao aqui, porque o runner do eval precisa das duas
    para acumular o estado sintetico entre turnos. Ver os docstrings de la.

    `perguntou` tem default de proposito: nenhum chamador antigo precisa saber
    da TEC-257 para continuar funcionando, e nao marcar e o comportamento
    seguro.
    """
    campos = campos_a_gravar(intencao, extracao)
    if not campos:
        # A guarda de FORA_DE_ESCOPO vale para a marca tambem, e o buraco esta
        # declarado no spec: um agente que pergunte num turno fora de escopo
        # nao marca e pode perguntar de novo. Com a marca permanente, marcar
        # de menos e o erro mais seguro dos dois. Nao ha linha gravada, entao
        # nao ha linha a devolver.
        return None

    marcados = sorted(campos_a_marcar(perguntou, campos))

    valores: dict[str, Any] = {
        "channel": channel,
        "conversation_key": conversation_key,
        "updated_at": datetime.now(UTC),
        # Sempre presente, mesmo vazio: `NULL` esta reservado para "linha
        # anterior a TEC-257, ninguem marcava", e um insert que omitisse a
        # coluna criaria uma linha nova com a semantica de linha antiga.
        "perguntados_sem_resposta": marcados,
        **campos,
    }
    statement = pg_insert(LeadQualification).values(valores)
    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                **{chave: statement.excluded[chave] for chave in (*campos, "updated_at")},
                # A uniao mora no SQL, e nao numa leitura previa em Python.
                #
                # Ler o array antigo, unir em memoria e gravar abriria a
                # janela que a guarda de monotonia de `gravar_resumo` ja
                # fechou para o resumo: dois turnos concorrentes da mesma
                # conversa leem o mesmo valor, cada um une o seu, e o mais
                # lento sobrescreve a marca do mais rapido -- perda
                # silenciosa, e a marca e o que impede reperguntar.
                #
                # `coalesce` porque `NULL || {'regiao'}` e NULL em Postgres, e
                # toda linha anterior a esta card tem NULL aqui.
                #
                # Duplicata e possivel por este caminho e nao incomoda: quem
                # le testa pertinencia, nao conta.
                "perguntados_sem_resposta": func.coalesce(
                    LeadQualification.perguntados_sem_resposta,
                    literal_column("'{}'::varchar[]"),
                ).op("||")(statement.excluded.perguntados_sem_resposta),
            },
        )
        .returning(LeadQualification)
        # Sem isto o `RETURNING` mente quando a sessao ja carregou esta linha:
        # o identity map do SQLAlchemy devolve a instancia que a sessao ja tem
        # e NAO a atualiza com a linha que o banco acabou de devolver. Uma
        # sessao que le com `ler_estado` e grava logo depois receberia aqui o
        # estado ANTERIOR a gravacao -- e a docstring acima estaria mentindo.
        #
        # `turno.py` hoje escapa por acidente (le numa sessao, grava noutra),
        # e por isso nenhum teste pegava. A TEC-150 quer ler e gravar na mesma
        # sessao para recalcular o score, e ali `lead.qualificado` pararia de
        # disparar em silencio.
        .execution_options(populate_existing=True)
    )
    return resultado.scalar_one()


async def marcar_perguntados(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
    perguntou: Iterable[str],
) -> None:
    """Grava so a marca de `perguntou`, num UPDATE que nao toca mais nada.

    Existe para o commit pos-entrega de `turno.py` (a marca so pode ser
    gravada depois da entrega confirmada -- ver o comentario la) nao reabrir
    a corrida que a uniao em SQL de `gravar_estado` fechou para a marca, so
    que agora do lado das colunas de valor.

    Reusar `gravar_estado` inteiro nesse ponto -- regravando `intencao` e
    `extracao` de novo, com os mesmos valores de `gerada` -- e idempotente so
    contra si mesmo. Contra a concorrencia real entre dois turnos da mesma
    conversa (a razao pela qual a uniao da marca foi para o SQL) ele inverte
    "mais novo vence" em silencio: turno A grava extracao_A em t1, turno B
    grava extracao_B em t2 > t1, e o commit pos-entrega de A -- se regravasse
    extracao -- aconteceria em t3 > t2 e sobrescreveria extracao_B com
    extracao_A, que e mais velha. Esta funcao evita o problema tocando so a
    coluna da marca: nao ha coluna de valor no `SET` para inverter.

    `preenchidos` vem de `campos_a_gravar`, calculada aqui so para a
    subtracao de `campos_a_marcar` -- nada dela e gravado. A mesma guarda de
    `gravar_estado` vale: sem campos deste turno (inclui FORA_DE_ESCOPO), nao
    ha marca (D8 do spec) -- marcar de menos e o erro seguro.

    A linha existe garantidamente sempre que ha algo a marcar: o guard acima
    (`if not preenchidos: return`) so deixa passar quando `campos_a_gravar`
    devolveu campos deste turno, e e exatamente esse retorno cedo -- nao este
    `UPDATE` -- que cobre FORA_DE_ESCOPO. Quando ha campos deste turno, a
    chamada pre-entrega de `gravar_estado` (o bloco de cima em `turno.py`) ja
    commitou, numa transacao anterior e ja fechada, a linha que este UPDATE
    vai encontrar. Um `UPDATE` que nao casasse nenhuma linha ficaria um no-op
    inofensivo mesmo assim -- e uma propriedade defensiva desta funcao, nao um
    caminho que se espera exercitar.
    """
    preenchidos = campos_a_gravar(intencao, extracao)
    if not preenchidos:
        return

    marcados = sorted(campos_a_marcar(perguntou, preenchidos))
    if not marcados:
        return

    await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .values(
            perguntados_sem_resposta=func.coalesce(
                LeadQualification.perguntados_sem_resposta,
                literal_column("'{}'::varchar[]"),
            ).op("||")(marcados),
            updated_at=datetime.now(UTC),
        )
    )


async def contar_mensagens_do_lead(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> int:
    """As falas de ENTRADA do lead que a moderacao nao bloqueou.

    **Esta e a unica implementacao do contrato, e existe para que a TEC-151
    nao escreva a segunda.** A docstring de `calcular_score` fixa a definicao
    palavra por palavra e nomeia o risco: tres leituras eram defensaveis, e
    duas fontes para o mesmo fato divergiriam em silencio -- que e o defeito
    que a TEC-146 gastou uma card inteira consertando. Quem precisar da
    contagem chama daqui.

    `status` nao entra: RECEIVED, QUEUED e PROCESSED descrevem o pipeline de
    ingestao, nao se o lead falou, e filtrar por eles faria a contagem oscilar
    com retentativa.

    Inclui a mensagem do turno corrente -- a ingestao a persiste antes de o job
    rodar.
    """
    total = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.channel == channel,
            Message.conversation_key == conversation_key,
            Message.direction == MessageDirection.INBOUND,
            Message.bloqueada_em.is_(None),
        )
    )
    return total or 0


def _score_do_registro(registro: LeadScoreAudit | None) -> Score | None:
    """Reconstroi o `Score` de um registro da trilha.

    Existe porque a comparacao da RN-06.4 emendada e sobre os cinco fatores, e
    nao sobre o total: um registro guarda os cinco em colunas, e compara-los
    exige remonta-los no tipo que `causas_do_recalculo` recebe.
    """
    if registro is None:
        return None
    return Score(
        completude=registro.completude,
        urgencia=registro.urgencia,
        catalogo=registro.catalogo,
        engajamento=registro.engajamento,
        capacidade=registro.capacidade,
    )


async def registrar_recalculo(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> LeadScoreAudit | None:
    """Recalcula o score do lead e grava a trilha se ele mudou.

    Devolve a linha gravada, ou `None` quando nao havia estado a pontuar ou
    quando o resultado foi identico ao ultimo registrado.

    Nao commita -- a sessao e emprestada, como em `gravar_estado`, e quem chama
    e dono da fronteira da transacao. A trilha tem de entrar no MESMO commit
    que o estado: uma trilha que registrasse um score calculado sobre um estado
    que o rollback desfez seria pior que trilha nenhuma, porque e lida
    justamente por quem ja desconfia do numero.

    **O estado vem do `SELECT ... FOR UPDATE` daqui, e nao de fora.** Reusar o
    retorno de `gravar_estado` ou o `contexto.estado` do turno pareceria mais
    barato -- os dois ja estao em maos -- e seria errado no caminho sem campos:
    `contexto.estado` foi lido por `montar_contexto` numa OUTRA sessao, antes
    deste bloco, e um turno concorrente da mesma conversa pode ter commitado
    uma alteracao no intervalo. Como o lock precisa do statement de qualquer
    jeito, deixa-lo devolver a linha custa zero e apaga a questao.

    **O lock nao e decorativo: turnos da mesma conversa NAO sao
    serializados.** A deduplicacao do ARQ e por mensagem (`_job_id =
    msg:<id>`), nao por conversa, e a protecao contra paralelismo e uma
    invariante de tempo (`job_timeout` < `sweep_inflight_after_seconds`), nao
    um lock. Sem ele, dois recalculos concorrentes leem o mesmo ultimo
    registro, ambos veem mudanca e ambos gravam -- dois registros com o mesmo
    `total_anterior`, e a cadeia deixa de reconstruir a evolucao. No turno COM
    campos o lock ja foi tomado pelo `ON CONFLICT DO UPDATE` de
    `gravar_estado` e este e redundante; no turno SEM campos nao ha upsert, e e
    exatamente o caminho em que a unica mudanca vem da contagem de mensagens.
    """
    estado = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
            # Mesma razao do `populate_existing` de `gravar_estado`: no turno
            # com campos a sessao ACABOU de carregar esta linha pelo RETURNING
            # do upsert, e sem a opcao o identity map devolve a instancia que a
            # sessao ja tem em vez da linha que o banco mandou. A releitura que
            # existe justamente para nao usar estado velho devolveria estado
            # velho, com o lock tomado e tudo parecendo certo.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if estado is None:
        return None

    novo = calcular_score(
        estado,
        mensagens_do_lead=await contar_mensagens_do_lead(
            session, channel=channel, conversation_key=conversation_key
        ),
        # Explicito, e nao pelo default: a busca de imoveis (TEC-158) nao
        # existe, e a TEC-150 prescreve que ate la o fator contribua zero.
        # Quando ela existir, este e o unico ponto que muda.
        imoveis_compativeis=0,
    )

    ultimo = (
        await session.scalars(
            select(LeadScoreAudit)
            .where(
                LeadScoreAudit.channel == channel,
                LeadScoreAudit.conversation_key == conversation_key,
            )
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).first()

    causas = causas_do_recalculo(_score_do_registro(ultimo), novo)
    if not causas:
        return None

    linha = LeadScoreAudit(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        total_anterior=ultimo.total_novo if ultimo is not None else None,
        total_novo=novo.total,
        completude=novo.completude,
        urgencia=novo.urgencia,
        catalogo=novo.catalogo,
        engajamento=novo.engajamento,
        capacidade=novo.capacidade,
        causas=list(causas),
    )
    session.add(linha)
    # Flush e nao commit: a linha precisa existir no banco para o proximo
    # `registrar_recalculo` da mesma transacao a enxergar como "ultimo", e o
    # commit e de quem chamou.
    await session.flush()
    return linha
