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
from mobia.domain.context.models import ConversationSummary, LeadQualification, aad_do_resumo
from mobia.infra.crypto import decrypt, encrypt

log = structlog.get_logger(__name__)

# Sai de `Extracao` e nao de uma lista escrita a mao: e a mesma fonte de onde
# `SCHEMA_DA_EXTRACAO` deriva, entao a proxima card que acrescentar campo nao
# precisa lembrar deste lugar.
_CAMPOS_DA_EXTRACAO = frozenset(campo.name for campo in fields(Extracao))

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
    - `intencao` sempre entra quando ha gravacao. Ela vem de fora, do
      classificador, e nunca da extracao -- a tabela `conversation_intent` e
      esta coluna guardam o mesmo fato, e duas fontes para ele divergiriam, o
      que apareceria como bug de score na TEC-150.
    """
    if intencao is Intencao.FORA_DE_ESCOPO:
        return {}
    return {"intencao": intencao.value, **extracao.preenchidos()}


def campos_a_marcar(perguntou: Iterable[str], preenchidos: Iterable[str]) -> set[str]:
    """Os campos que o agente perguntou neste turno e o lead nao respondeu.

    A regra unica de marcacao da TEC-257, compartilhada entre `gravar_estado`
    (producao) e o runner do eval, pela mesma razao que `campos_a_gravar`:
    duas copias divergiriam, e a divergencia so apareceria na borda.

    `perguntou` vem do modelo, que declara sobre o que perguntou. **Nome que
    nao e campo de extracao e descartado**, nao corrigido nem adivinhado: com
    a marca permanente, marcar de mais mata o campo pela vida da conversa e
    sem rastro, enquanto marcar de menos custa uma pergunta a mais. O
    descarte e logado para a deriva de vocabulario do modelo ser visivel --
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
    for nome in perguntou:
        if nome in _CAMPOS_DA_EXTRACAO:
            conhecidos.add(nome)
        else:
            ignorados.append(nome)

    if ignorados:
        plausiveis = sorted({n for n in ignorados if _NOME_PLAUSIVEL.fullmatch(n)})
        log.warning(
            "estado.campo_perguntado_desconhecido",
            nomes=plausiveis,
            descartados=len(ignorados) - len(plausiveis),
        )

    return conhecidos - set(preenchidos)


async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
    perguntou: Iterable[str] = (),
) -> None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia.

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
        # de menos e o erro mais seguro dos dois.
        return

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
    await session.execute(
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
    )


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

    Um `UPDATE` que nao casa nenhuma linha e um no-op correto, nao um erro: e
    o que acontece quando a chamada pre-entrega nao criou linha nenhuma
    (FORA_DE_ESCOPO) e nenhum turno anterior desta conversa criou uma antes.
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
