import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import String, cast, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.dinheiro import mudou_de_banda, ticket_de
from mobia.domain.agente.investidor import (
    CAMPOS_DO_INVESTIDOR,
    ExtracaoDoInvestidor,
    Horizonte,
    RetornoEsperadoTipo,
)
from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.auditoria import causas_do_recalculo
from mobia.domain.context.models import (
    ConversationIntentAudit,
    ConversationSummary,
    LeadQualification,
    LeadScoreAudit,
    aad_do_resumo,
)
from mobia.domain.context.qualificacao import esta_qualificado, perfil_de
from mobia.domain.context.score import Score, calcular_score
from mobia.domain.context.temperatura import Temperatura, temperatura_de
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
# byte-identico ao de antes tambem neste caminho. Nenhum nome sai como
# `faixa_preco_min`: orcamento e UM assunto, e duas linhas de marca para uma
# pergunta so gastariam prompt dizendo a mesma coisa.
#
# TEC-148: as duas chaves do PROMPT entram tambem. Nada diz ao modelo qual
# dos vocabularios `perguntou`/`recusou` aceitam, e o que ele le a cada turno
# e `faixa_preco_min`/`faixa_preco_max` -- entao e por esses nomes que ele
# tende a relatar. Sem as duas linhas abaixo, uma recusa do orcamento (o
# cenario titular da card) era descartada como vocabulario desconhecido.
# `faixa_preco_max` mapeia para si mesmo. A linha parece redundante e nao e:
# sem ela o nome cai no `in _CAMPOS_DA_EXTRACAO` de `_marca_de`, e nem
# `faixa_preco_max` nem `faixa_preco_min` sao campos de `Extracao` -- os dois
# voltariam a ser descartados. Nao apague.
_MARCA_DO_ORCAMENTO = "faixa_preco_max"
_NOME_DA_MARCA = {
    "faixa_preco_expressao": _MARCA_DO_ORCAMENTO,
    "faixa_preco_min_centavos": _MARCA_DO_ORCAMENTO,
    "faixa_preco_max_centavos": _MARCA_DO_ORCAMENTO,
    "faixa_preco_min": _MARCA_DO_ORCAMENTO,
    "faixa_preco_max": _MARCA_DO_ORCAMENTO,
}


def _marca_de(nome: str) -> str | None:
    """O nome sob o qual a MARCA deste campo e gravada, ou `None` se o nome
    nao pertence ao vocabulario que este modulo sabe marcar.

    **So a trilha padrao, e os nomes do investidor ficam de fora de
    proposito** -- quem os conhece e `_nome_contavel`, logo abaixo. Marcar e
    contar sao vocabularios diferentes desde a TEC-153; o porque esta la.
    """
    if nome in _NOME_DA_MARCA:
        return _NOME_DA_MARCA[nome]
    return nome if nome in _CAMPOS_DA_EXTRACAO else None


def _nome_contavel(nome: str) -> str | None:
    """O nome sob o qual esta pergunta CONTA para o teto da RN-05.5, ou
    `None` se o nome nao pertence a vocabulario nenhum. TEC-153.

    Superconjunto de `_marca_de`: tudo que se marca tambem se conta, e os
    nomes do investidor se contam **sem** se marcar. A trilha do investidor
    tem schema proprio (o schema compilado e parcela do orcamento de prompt),
    entao os nomes dela nao estao em `_CAMPOS_DA_EXTRACAO`; sem esta funcao
    toda pergunta do investidor sairia de graca do teto da RN-05.5, e um
    investidor seria interrogado sem fim enquanto um comprador e cortado na
    oitava.

    **Os dois vocabularios sao separados porque marcar campo de investidor
    esta errado, e do jeito caro.** `campos_a_marcar` e `campos_a_recusar`
    subtraem os campos que o turno gravou, e esses campos saem de
    `Extracao.preenchidos()` -- que nunca carrega campo de investidor, porque
    eles moram em `ExtracaoDoInvestidor` e sao gravados por
    `gravar_investidor`, noutra chamada e noutra transacao. Um vocabulario
    unico faria toda pergunta do subagente virar marca PERMANENTE de
    "perguntado, sem resposta" mesmo quando o lead respondeu no mesmo turno:
    exatamente o "marcar de mais" que os docstrings de la chamam de erro
    caro. Do lado da recusa o dano e irmao: registrar-se-ia uma recusa que
    nada honra.

    Contar de mais nao tem essa assimetria -- o teto e sobre perguntas
    FEITAS, e a pergunta do investidor foi feita.
    """
    marca = _marca_de(nome)
    if marca is not None:
        return marca
    return nome if nome in CAMPOS_DO_INVESTIDOR else None


def perguntas_contaveis(perguntou: Iterable[str]) -> frozenset[str]:
    """Os nomes de `perguntou` que contam para o teto da RN-05.5. TEC-149, D3.

    Conjunto e nao lista: os dois extremos do orcamento chegam como nomes
    distintos e sao UMA pergunta -- `_nome_contavel` ja os colapsa no mesmo
    nome logico (por `_marca_de`), e o conjunto termina o servico. Nome que
    nao pertence a vocabulario nenhum sai fora: o modelo as vezes devolve o
    texto da pergunta em lugar do nome do campo, e contar isso gastaria o
    orcamento do lead com um defeito nosso.

    Passa por `_marca_de` de proposito, em vez de uma segunda lista de nomes
    da trilha padrao: duas fontes para o mesmo vocabulario divergiriam em
    silencio, que e o defeito que a TEC-146 gastou uma card inteira
    consertando.
    """
    marcas = (_nome_contavel(nome) for nome in perguntou)
    return frozenset(marca for marca in marcas if marca is not None)


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


def intencao_e_gravavel(intencao: Intencao) -> bool:
    """Esta intencao chega a ser gravada em `lead_qualification.intencao`?

    Extraida de `campos_a_gravar` na TEC-136 para ter UM dono. A pergunta
    passou a ter um segundo interessado (`aplicar_mudanca_de_intencao`, que so
    descarta quando a intencao de fato muda a coluna), e duas copias da regra
    divergiriam no dia em que uma oitava intencao entrasse no enum.
    """
    return intencao not in (Intencao.FORA_DE_ESCOPO, Intencao.INDEFINIDA)


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
    - **`INDEFINIDA` nao sobrescreve `intencao`** (TEC-147). Quem responde
      "esta intencao chega a ser gravada?" e `intencao_e_gravavel`, a funcao
      imediatamente anterior, desde que a TEC-136 lhe deu um segundo
      interessado. Era a unica coluna desta tabela que violava o "None nao
      apaga" logo acima:
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
    if not intencao_e_gravavel(intencao):
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

    **Campo do investidor nunca e marcado, e a exclusao e deliberada**
    (TEC-153). Ele nao passa por `_marca_de` e nao entra no log de
    desconhecidos: a subtracao abaixo usa `Extracao.preenchidos()`, que nunca
    carrega campo de investidor, entao marcar aqui seria marcar de mais --
    permanente -- ate quando o lead responde no mesmo turno. O teto da
    RN-05.5 continua contando essa pergunta, por `_nome_contavel`.

    `preenchidos` sao os campos que este turno gravou. A subtracao e o que
    separa esta marca do proxy irmao: campo que o estado JA SABE e
    reperguntado e assunto de `_reperguntou`, nao daqui.

    A subtracao usa os campos **deste** turno, e nao o estado acumulado, para
    nao pagar uma consulta a mais. Uma marca sobre campo que ja estava
    preenchido de um turno anterior e possivel por esse caminho, e fica inerte
    enquanto o valor existir: `_texto_do_estado` mostra o valor quando ele ha,
    e a marca so aparece onde nao ha valor. Valor vence marca.

    **Inerte nao e permanente, desde a TEC-136.** Ate ela, era: nenhum caminho
    de gravacao apagava coluna, entao um valor gravado nunca sumia e a marca
    escondida atras dele nunca voltava a aparecer. `aplicar_mudanca_de_intencao`
    (neste arquivo) abriu a excecao de proposito e anula as duas colunas do
    orcamento quando a intencao troca de banda -- e por isso ela remove a marca
    do orcamento das duas colunas de marca no mesmo UPDATE. Sem essa remocao,
    a marca que dormia atras do valor acordaria no instante em que o valor
    sumisse, e o agente trataria como ja perguntado um orcamento que ele nunca
    perguntou naquela banda. Qualquer descarte futuro de coluna tem de fazer o
    mesmo pela marca dela.
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
        if marca is not None:
            conhecidos.add(marca)
        elif _nome_contavel(nome) is None:
            # TEC-153: nome do investidor nao e "desconhecido" -- ele pertence
            # ao vocabulario contavel e nao ao marcavel, de proposito (ver
            # `_nome_contavel`). Ele cai fora da marca do mesmo jeito, mas sem
            # entrar neste log: registra-lo como deriva de vocabulario faria o
            # unico instrumento que temos para a deriva disparar em todo turno
            # do investidor, dizendo "desconhecido" sobre um nome que este
            # modulo conhece.
            ignorados.append(nome)

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


def campos_a_recusar(recusou: Iterable[str], preenchidos: Iterable[str]) -> set[str]:
    """Os campos que o lead se negou a informar neste turno.

    Mesma forma de `campos_a_marcar` e pelos mesmos motivos: e regra unica
    para producao, e os nomes passam por `_marca_de` antes de qualquer coisa
    porque o orcamento tem varios nomes neste repo e o unico que o modelo
    pode dizer nao e coluna. O runner do eval NAO chama esta funcao -- o
    corpus anotado da TEC-145 nao marca recusa em turno nenhum (lacuna
    declarada no desenho), entao nao ha o que a regra faria ali. Uma card
    futura que anote recusa no corpus tem de ligar o runner nesta funcao, e
    nao escrever uma segunda copia dela.

    **Nome fora do vocabulario e descartado, nao adivinhado.** Aqui isso pesa
    mais que na marca: recusa inventada faz o agente parar de perguntar um
    campo obrigatorio e `esta_qualificado` devolver False para sempre, sem o
    lead perceber. Descartar custa uma pergunta a mais.

    **Campo do investidor nao entra aqui** (TEC-153), como nao entra na marca
    irma: a recusa so alcanca o modelo pela marca que `_texto_do_estado`
    renderiza, e la o campo do investidor sai como VALOR, nunca como marca.
    Registra-la produziria uma coluna com um nome que nada honra -- promessa
    de RN-05.7 que o prompt nao cumpre. Descartar custa uma pergunta a mais,
    que e o preco que o resto deste docstring ja aceita.

    **A recusa aceita tambem e logada**, e nao so a descartada. Uma recusa
    sobre campo que ainda nao tinha valor nao move o score nem gera linha na
    trilha da TEC-152 -- sem esta linha de log ela nao existiria em lugar
    nenhum alem da coluna. Ver o comentario no corpo.

    **`preenchidos` subtrai, e e o cenario 2 da card:** se o lead informou o
    campo neste turno, ele nao esta recusando o campo. Vale para os dois
    extremos do orcamento -- "a partir de 300 mil" preenche so o minimo e
    responde a pergunta sobre orcamento.

    A subtracao aqui cobre o turno corrente. Desfazer uma recusa ANTERIOR
    quando o valor chega e feito no SQL de `gravar_estado`, que e o unico
    lugar que ve o array acumulado.
    """
    conhecidos: set[str] = set()
    ignorados: list[str] = []
    # dict.fromkeys em vez de iterar `recusou` direto: sem dedupe, um nome
    # repetido (["bairro", "bairro"]) entraria duas vezes em `ignorados`, e o
    # `len(ignorados) - len(plausiveis)` abaixo contaria a segunda ocorrencia
    # como se o filtro de PII tivesse suprimido alguem -- um `descartados=1`
    # mentindo sobre uma supressao que nunca aconteceu. Mesmo raciocinio de
    # `campos_a_marcar`, ver o comentario la.
    for nome in dict.fromkeys(recusou):
        marca = _marca_de(nome)
        if marca is not None:
            conhecidos.add(marca)
        elif _nome_contavel(nome) is None:
            # Mesma excecao de `campos_a_marcar`, pela mesma razao: o nome do
            # investidor nao e deriva de vocabulario, e este log so serve se
            # disser a verdade sobre o que o modelo inventou. Ver
            # `_nome_contavel`.
            ignorados.append(nome)

    if ignorados:
        plausiveis = sorted({n for n in ignorados if _NOME_PLAUSIVEL.fullmatch(n)})
        log.warning(
            "estado.campo_recusado_desconhecido",
            nomes=plausiveis,
            descartados=len(ignorados) - len(plausiveis),
        )

    aceitos = conhecidos - {_marca_de(nome) or nome for nome in preenchidos}
    if aceitos:
        # O unico instrumento do erro CARO desta card. Recusa de falso
        # positivo e silenciosa por construcao: quando o campo nao tinha
        # valor, o score nao muda (a completude ja nao o contava), a trilha
        # da TEC-152 nao ganha linha, e o lead vira permanentemente
        # inqualificavel sem rastro em lugar nenhum alem da coluna. Uma linha
        # de log e a coisa barata que torna isso audivel enquanto o corpus de
        # eval nao anota recusa (lacuna declarada no desenho).
        #
        # Os nomes saem INTEIROS, sem passar por `_NOME_PLAUSIVEL`. Nao e
        # esquecimento: aqui eles ja passaram por `_marca_de`, entao sao
        # vocabulario fixo -- chave de `_NOME_DA_MARCA` ou campo de
        # `Extracao` --, e nao ha caminho por onde texto do lead chegue.
        # Filtrar seria custo sem risco a comprar. Os DESCARTADOS acima sao
        # o caso oposto, e por isso so eles precisam do filtro.
        log.info("estado.campo_recusado", nomes=sorted(aceitos))
    return aceitos


def _sem_os_respondidos(expressao: Any, respondidos: list[str]) -> Any:
    """Encadeia `array_remove` para tirar do array cada campo respondido.

    Existe como funcao para o laco nao poluir o dicionario do `set_`, que ja
    e o trecho mais denso de `gravar_estado`. Postgres nao tem operador de
    subtracao de array; `array_remove` e o built-in, e remove todas as
    ocorrencias do elemento.
    """
    for nome in respondidos:
        expressao = func.array_remove(expressao, nome)
    return expressao


async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
    perguntou: Iterable[str] = (),
    recusou: Iterable[str] = (),
) -> LeadQualification | None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia
    -- a unica excecao mora em `aplicar_mudanca_de_intencao`, e so la (RN-03.3,
    TEC-136): aquele caminho descarta o orcamento por um UPDATE proprio,
    ANTES desta funcao na mesma transacao, quando a intencao troca de banda.

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

    `recusou` tem default de proposito, como `perguntou`: nenhum chamador
    antigo precisa saber da TEC-148 para continuar funcionando, e nao
    registrar recusa e o comportamento seguro.

    Quando o turno nao tem campo nenhum a gravar (`campos_a_gravar` devolveu
    {}), esta funcao ainda pode gravar -- so a recusa, so por UPDATE, e so
    numa linha que ja existe. Ver o comentario dentro do `if not campos:`
    abaixo para o motivo de isso nao seguir a mesma guarda de `perguntou`.
    """
    campos = campos_a_gravar(intencao, extracao)
    if not campos:
        # A guarda de FORA_DE_ESCOPO vale para a marca de `perguntou` tambem,
        # e o buraco esta declarado no spec: um agente que pergunte num turno
        # fora de escopo nao marca e pode perguntar de novo. Com a marca
        # permanente, marcar de menos e o erro mais seguro dos dois -- por
        # isso `perguntou` simplesmente cai no chao aqui, sem UPDATE nenhum.
        #
        # `recusou` NAO pode cair no mesmo chao. Um turno sem campo nenhum e
        # exatamente a forma provavel do cenario central desta card: um lead
        # que so diz "prefiro nao falar disso" classifica INDEFINIDA ou
        # FORA_DE_ESCOPO e nao extrai nada, `campos_a_gravar` devolve {} e
        # cairia aqui -- e para a recusa marcar de menos e o erro CARO, nao o
        # seguro: o agente continua perguntando o campo que o lead ja disse
        # que nao quer informar, o que e o proprio motivo da card existir.
        #
        # A saida e um UPDATE que toca so `campos_recusados`, no molde de
        # `marcar_perguntados` (mesmo arquivo): nao reabre o upsert de
        # `intencao`/`extracao`, e devolve a linha atualizada em vez de nada.
        #
        # Deliberadamente NAO cria linha. Um lead sem `lead_qualification`
        # nenhuma que so recusa continua sem linha -- criar moveria o score
        # dele de 0 para o piso documentado de 6 pontos e geraria registro na
        # trilha da TEC-152 so por uma recusa isolada, uma consequencia que
        # esta card nunca decidiu. A recusa sobrevive para quem ja tem
        # estado; de quem nao tem nenhum, ela continua se perdendo, do mesmo
        # jeito que antes desta correcao.
        recusados_isolados = sorted(campos_a_recusar(recusou, ()))
        if not recusados_isolados:
            return None

        resultado_da_recusa = await session.execute(
            update(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .values(
                campos_recusados=func.coalesce(
                    LeadQualification.campos_recusados,
                    literal_column("'{}'::varchar[]"),
                ).op("||")(recusados_isolados),
                updated_at=datetime.now(UTC),
            )
            .returning(LeadQualification)
            .execution_options(populate_existing=True)
        )
        return resultado_da_recusa.scalar_one_or_none()

    marcados = sorted(campos_a_marcar(perguntou, campos))
    recusados = sorted(campos_a_recusar(recusou, campos))
    # Os nomes que este turno preencheu, na forma canonica da marca -- e o que
    # sai do array acumulado no SQL abaixo.
    respondidos = sorted({_marca_de(nome) or nome for nome in campos})

    valores: dict[str, Any] = {
        "channel": channel,
        "conversation_key": conversation_key,
        "updated_at": datetime.now(UTC),
        # Sempre presente, mesmo vazio: `NULL` esta reservado para "linha
        # anterior a TEC-257, ninguem marcava", e um insert que omitisse a
        # coluna criaria uma linha nova com a semantica de linha antiga.
        "perguntados_sem_resposta": marcados,
        # Sempre presente, mesmo vazio, pela mesma razao da coluna vizinha:
        # `NULL` esta reservado para "linha anterior a esta card".
        "campos_recusados": recusados,
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
                # Uniao em SQL pela razao da coluna vizinha: dois turnos
                # concorrentes da mesma conversa leriam o mesmo array, cada um
                # uniria o seu, e o mais lento sobrescreveria em silencio.
                #
                # `array_remove` encadeado tira o que este turno respondeu --
                # o cenario 2 da card, atravessando turnos. Ele remove TODAS
                # as ocorrencias do nome respondido; um nome recusado em DOIS
                # turnos diferentes sem nunca ser respondido acumula
                # ['regiao', 'regiao'] e fica assim -- duplicata e possivel
                # por este caminho, mesma razao da coluna irma logo acima:
                # quem le testa pertinencia, nao conta.
                "campos_recusados": _sem_os_respondidos(
                    func.coalesce(
                        LeadQualification.campos_recusados,
                        literal_column("'{}'::varchar[]"),
                    ).op("||")(statement.excluded.campos_recusados),
                    respondidos,
                ),
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


@dataclass(frozen=True)
class MudancaDeIntencao:
    """O que a troca de intencao deste turno mudou. TEC-136."""

    de: str | None
    para: str
    faixa_descartada: bool


async def aplicar_mudanca_de_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
) -> MudancaDeIntencao | None:
    """Descarta o que a intencao nova invalida e registra a troca. RN-03.3.

    Devolve `None` quando nao houve mudanca a aplicar: intencao que nao se
    grava, conversa sem estado ainda, ou intencao igual a que ja estava.

    **A excecao ao "None no campo nao apaga" mora aqui, e so aqui.** A regra de
    `campos_a_gravar` e de `gravar_estado` segue intacta: nada que venha da
    extracao apaga coluna nenhuma. Esta funcao e um caminho SEPARADO, que nao
    apaga por ausencia de valor e sim porque a banda de plausibilidade mudou --
    e por isso ela toca UMA coisa, o orcamento, e nenhum outro campo.

    **Roda ANTES de `gravar_estado`, e a ordem e o desenho.** O descarte e um
    UPDATE que anula a faixa; o upsert de `gravar_estado` vem depois e escreve
    por cima o valor novo quando o lead o disse no mesmo turno ("na verdade
    quero comprar, ate 800 mil"). Invertendo a ordem, o descarte apagaria o
    numero que o lead acabou de dar.

    **Nao cria linha.** Primeiro turno da conversa nao tem estado a invalidar,
    e criar linha aqui moveria o score do lead pelo mesmo argumento que o
    `if not campos:` de `gravar_estado` registra por extenso.

    **Nao escreve `updated_at`, e isso depende da ordem acima.** Quem descarta
    tem intencao gravavel por construcao (a guarda e a primeira linha), entao
    `gravar_estado` sempre vem atras na mesma transacao e carimba a coluna.
    Quem mudar a ordem, ou passar a chamar esta funcao sem `gravar_estado`
    depois, deixa a linha com valor apagado e `updated_at` velho.

    **O lock nao e decorativo.** Turnos da mesma conversa nao sao
    serializados -- a deduplicacao do ARQ e por mensagem, nao por conversa --,
    e sem ele dois turnos concorrentes leem a mesma intencao anterior e ambos
    gravam linha de historico para a mesma troca. E a corrida que
    `registrar_recalculo` fechou com este mesmo cadeado. Ele ja e tomado nesta
    transacao, mais adiante, por aquela funcao: tomar aqui antes preserva a
    ordem de aquisicao e nao cria deadlock novo.
    """
    if not intencao_e_gravavel(intencao):
        return None

    estado = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
            # `populate_existing` aqui NAO e o mesmo caso do `RETURNING` de
            # `gravar_estado`, que protege o valor devolvido a quem chama: aqui
            # ele protege o LOCK. Quem chama esta funcao no turno ja leu o
            # estado nesta sessao para montar o prompt, entao a linha esta no
            # identity map; sem isto o ORM devolveria a instancia velha e
            # jogaria fora justamente as colunas que o `FOR UPDATE` acabou de
            # reler depois de esperar o concorrente. A decisao sairia do
            # snapshot de ANTES do cadeado, que e a corrida que o cadeado
            # existe para fechar. Tirar esta linha nao quebra nenhum teste que
            # so use uma sessao, entao ela tem um teste proprio:
            # `test_a_decisao_sai_da_linha_sob_o_cadeado_e_nao_do_cache_da_sessao`.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if estado is None:
        return None

    # Sem guarda de valor fora do enum de proposito: `lead_qualification.intencao`
    # so e escrita por `campos_a_gravar`, sempre a partir de `Intencao.value`, e
    # defender de um caso que nenhum caminho produz esconderia a corrupcao real
    # no dia em que um caminho novo a produzisse.
    antiga = Intencao(estado.intencao) if estado.intencao is not None else None
    if antiga is intencao:
        return None

    # A origem sai da instancia ANTES do UPDATE abaixo. Ele e um UPDATE ORM, e
    # a sincronizacao de sessao expira os atributos da linha que ele casou:
    # ler `estado.intencao` depois dispararia recarga, e o historico passaria a
    # depender do que a recarga devolvesse em vez do que o cadeado leu.
    de = estado.intencao

    descartar = mudou_de_banda(antiga, intencao)
    if descartar:
        await session.execute(
            update(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .values(
                faixa_preco_min_centavos=None,
                faixa_preco_max_centavos=None,
                # A marca sai junto com o valor, senao o descarte se fecha
                # sozinho: o agente trataria o orcamento como ja perguntado e
                # nunca reperguntaria o da banda nova.
                #
                # **As DUAS colunas de marca, e nao so a primeira.**
                # `_texto_do_estado` monta os marcados como a uniao delas
                # (`montagem.py`), e as duas guardam o orcamento sob o mesmo
                # nome canonico. Limpar so uma deixa a outra emitindo
                # `faixa_preco_max: (perguntado, sem resposta)` sobre um valor
                # que acabou de ser apagado -- o pior dos dois mundos: o lead
                # perde o numero E nao e reperguntado.
                #
                # Sim, isto apaga uma recusa, e a TEC-148 promete nao
                # reperguntar o que o lead recusou. A promessa continua de pe
                # porque o sujeito dela mudou: recusar dizer o orcamento de
                # ALUGUEL nao e recusar dizer o de COMPRA, pelo mesmo
                # argumento que faz o NUMERO cair -- um valor de uma banda nao
                # significa nada na outra, e uma recusa tampouco. Nao limpar
                # tambem nao seria neutro: `esta_qualificado` e
                # `calcular_score` leem `campos_recusados`, entao a recusa da
                # era de aluguel seguiria descontando do score um orcamento
                # que nem existe mais.
                #
                # `array_remove` e o mesmo built-in que `_sem_os_respondidos`
                # usa, e pela mesma razao: Postgres nao tem subtracao de array.
                # O nome vem de `_MARCA_DO_ORCAMENTO` porque a marca tem tres
                # grafias no repo e escrever qualquer uma a mao reintroduziria
                # a divergencia que aquela constante fechou.
                perguntados_sem_resposta=func.array_remove(
                    LeadQualification.perguntados_sem_resposta, _MARCA_DO_ORCAMENTO
                ),
                campos_recusados=func.array_remove(
                    LeadQualification.campos_recusados, _MARCA_DO_ORCAMENTO
                ),
            )
        )

    session.add(
        ConversationIntentAudit(
            id=uuid.uuid4(),
            channel=channel,
            conversation_key=conversation_key,
            de=de,
            para=intencao.value,
            faixa_descartada=descartar,
        )
    )
    # Flush e nao commit: a sessao e emprestada, como em `gravar_estado`, e a
    # linha tem de estar visivel a uma leitura posterior na mesma transacao.
    await session.flush()
    return MudancaDeIntencao(de=de, para=intencao.value, faixa_descartada=descartar)


def _do_vocabulario[V: StrEnum](vocabulario: type[V], bruto: str | None) -> V | None:
    """Rele uma coluna de vocabulario com tolerancia: valor fora do enum vira
    `None`, e nao `ValueError`. TEC-153.

    Mesmo formato de `_membro` (`agente/classificador.py`), que faz isto para
    o que o MODELO devolve; nao e um import dele porque `domain/context` nao
    depende de `domain/agente/classificador` em lugar nenhum e aquela funcao e
    privada de la. Nao ha vocabulario duplicado por causa disto -- as duas
    leem o mesmo enum, que segue sendo a fonte unica.

    **Hoje nada pode chegar aqui fora do enum**: so `gravar_investidor`
    escreve estas colunas, e sempre a partir do enum. A guarda existe para o
    dia em que uma card encolher um vocabulario e esquecer a migracao de
    dados: com o construtor cru, o `ValueError` estouraria DENTRO da transacao
    pre-entrega e derrubaria o turno inteiro -- a mensagem volta para a fila e
    o lead nao recebe resposta nenhuma. Com a tolerancia, o custo e um perfil
    que fica como esta ate o lead responder de novo.

    O valor sai no log inteiro, e nao so o nome do enum: descobrir QUAL valor
    sumiu do vocabulario e o ponto do alerta, e aqui nao ha risco de PII --
    esta coluna nunca carregou texto do lead, so membro de enum escrito por
    este modulo.
    """
    if bruto is None:
        return None
    try:
        return vocabulario(bruto)
    except ValueError:
        log.warning(
            "estado.vocabulario_fora_do_enum", vocabulario=vocabulario.__name__, valor=bruto
        )
        return None


async def gravar_investidor(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    investidor: ExtracaoDoInvestidor,
) -> None:
    """Grava os campos da RN-05.2 e o perfil derivado da RN-07.2. TEC-153.

    **So grava campo que veio.** A qualificacao e progressiva: `None` num
    campo significa "o lead ainda nao disse", e sobrescrever um valor antigo
    com `None` apagaria o que ele ja tinha dito num turno anterior -- o mesmo
    cuidado que `campos_a_gravar` toma para a trilha padrao.

    O perfil e DERIVADO e gravado junto, e nao calculado na leitura: quem le
    o lead precisa dele sem reexecutar a regra, e a TEC-154 le a coluna
    direto. Ele e recalculado a partir do estado JA MESCLADO -- horizonte
    pode ter vindo num turno e o tipo de retorno noutro, e classificar so com
    o que chegou neste turno daria `None` para um lead que ja respondeu os
    dois.

    Nao commita, como as irmas deste arquivo: a sessao e emprestada e quem
    chama e dono da fronteira da transacao.

    **Consequencia declarada: sem linha, nada e gravado.** O unico criador de
    `lead_qualification` e o upsert de `gravar_estado`, que retorna cedo --
    "Deliberadamente NAO cria linha" -- quando `campos_a_gravar` devolve
    vazio. Um turno INDEFINIDA ou FORA_DE_ESCOPO sem extracao nenhuma no
    primeiro contato deixa o lead sem linha, e o que ele disser sobre ticket
    ou horizonte nesse mesmo turno se perde. E a mesma lacuna L4 que
    `contar_perguntas` ja declara, pela mesma causa e com a mesma razao para
    nao criar linha aqui: criar moveria o score de 0 para o piso documentado
    e gravaria na trilha da TEC-152 por um lead que ainda nao se qualificou.
    Fica contido do mesmo jeito -- assim que QUALQUER linha existir, todo
    turno seguinte grava.
    """
    # `populate_existing`: esta leitura nao serve so para saber se a linha
    # existe -- o perfil e derivado das colunas que ela carrega. Numa sessao
    # que ja tivesse carregado a linha, o identity map devolveria a instancia
    # velha e a mescla usaria o horizonte de antes, gravando um perfil errado
    # em silencio. E o mesmo cuidado, e pelo mesmo mecanismo, que `gravar_estado`
    # documenta no `RETURNING` dela.
    linha = await session.scalar(
        select(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .execution_options(populate_existing=True)
    )
    if linha is None:
        return

    valores: dict[str, Any] = {}
    if investidor.ticket_expressao is not None:
        # `ticket_de` devolvendo `None` e "o lead falou algo que nao e
        # dinheiro", ou recusou -- e ai nao ha o que gravar. Escrever `None`
        # aqui apagaria o ticket de um turno anterior por causa de uma frase
        # que nao dizia valor nenhum.
        centavos = ticket_de(investidor.ticket_expressao)
        if centavos is not None:
            valores["ticket_investimento_centavos"] = centavos
    if investidor.retorno_esperado_pct is not None:
        valores["retorno_esperado_pct"] = investidor.retorno_esperado_pct
    if investidor.retorno_esperado_tipo is not None:
        valores["retorno_esperado_tipo"] = investidor.retorno_esperado_tipo.value
    if investidor.horizonte is not None:
        valores["horizonte"] = investidor.horizonte.value
    if investidor.tolerancia_reforma is not None:
        valores["tolerancia_reforma"] = investidor.tolerancia_reforma.value
    if investidor.ja_investe_em_imoveis is not None:
        valores["ja_investe_em_imoveis"] = investidor.ja_investe_em_imoveis

    # O estado MESCLADO, e nao os campos deste turno: o que este turno trouxe
    # vence, e o que ele nao trouxe continua sendo o que a coluna ja tinha.
    # As colunas sao `str` (`String(16)`), os enums e que sao o vocabulario --
    # a conversao acontece aqui, na borda, e nao no modelo. Ela e TOLERANTE de
    # proposito: `_do_vocabulario` explica o que o construtor cru custaria.
    horizonte_mesclado = investidor.horizonte or _do_vocabulario(Horizonte, linha.horizonte)
    tipo_mesclado = investidor.retorno_esperado_tipo or _do_vocabulario(
        RetornoEsperadoTipo, linha.retorno_esperado_tipo
    )
    perfil = perfil_de(horizonte_mesclado, tipo_mesclado)
    if perfil is not None:
        # `None` nao entra pela mesma regra dos campos acima: falta um dos dois
        # e "ainda nao da para saber", nao "o perfil sumiu". E `perfil_de` e
        # total sobre os nove pares possiveis, entao um perfil ja gravado so
        # pode ser reescrito por outro perfil, nunca apagado.
        valores["perfil_investidor"] = perfil.value

    if not valores:
        # Turno do investidor em que o lead nao disse nada novo: um `SET` so
        # com `updated_at` seria escrita morta.
        return

    await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .values(**valores, updated_at=datetime.now(UTC))
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


async def contar_perguntas(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    perguntou: Iterable[str],
) -> None:
    """Soma ao contador do teto da RN-05.5 as perguntas deste turno. TEC-149.

    **Funcao irma de `marcar_perguntados`, e nao um trecho dentro dela.** As
    duas rodam no mesmo commit pos-entrega e pela mesma razao -- a pergunta
    so conta depois de o lead te-la recebido --, mas as guardas sao
    diferentes e incompativeis. `marcar_perguntados` sai cedo quando o turno
    nao extraiu campo nenhum, e o comentario de la declara que "marcar de
    menos e o erro seguro". Aqui o mesmo atalho inverte o sinal: o turno em
    que o lead escreve "oi" e o agente pergunta o orcamento nao extrai nada,
    sairia naquele `return`, e a pergunta FEITA E ENTREGUE nao contaria --
    dando ao lead mais perguntas do que as oito que a regra promete.

    **Incremento em SQL, nunca lendo em Python para regravar.** E a mesma
    razao pela qual a uniao da marca foi para o SQL: dois turnos concorrentes
    da mesma conversa, em que o commit pos-entrega mais lento sobrescreve o
    valor mais novo pelo mais velho, em silencio. `coluna = coluna + :n` nao
    tem esse problema, e um contador errado nao tem sintoma nenhum ate o
    lead ser cortado cedo ou tarde demais.

    Sem nada contavel, nenhum UPDATE: um turno que so respondeu duvida nao
    gasta orcamento, e um `SET` que soma zero so produziria escrita morta.

    **Consequencia declarada: o `UPDATE` e no-op enquanto o lead nao tem
    linha.** O unico gravador de `lead_qualification` e o upsert dentro de
    `gravar_estado`, e ele retorna cedo -- "Deliberadamente NAO cria linha"
    -- quando `campos_a_gravar` devolve vazio, o que vale sempre para
    FORA_DE_ESCOPO e para INDEFINIDA sem extracao. No primeiro turno em que
    o lead so diz "oi", nada e extraido, o agente pode perguntar mesmo
    assim, e este UPDATE nao casa linha nenhuma: a pergunta foi FEITA E
    ENTREGUE e nao e contada. Criar a linha aqui foi cogitado e rejeitado --
    moveria o score do lead de 0 para o piso documentado e gravaria uma
    entrada na trilha de score por causa de um lead que nao disse nada, um
    efeito colateral maior que a subcontagem. O erro fica contido: assim que
    QUALQUER linha existir para o lead, toda pergunta seguinte conta.
    """
    quantas = len(perguntas_contaveis(perguntou))
    if not quantas:
        return

    await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .values(
            perguntas_feitas=LeadQualification.perguntas_feitas + quantas,
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


@dataclass(frozen=True)
class Recalculo:
    """O que o passo de recalculo do turno produziu.

    Existe porque o turno precisa de mais de uma resposta do mesmo passo, e
    todas saem da mesma linha travada. Devolver so a trilha obrigaria uma
    segunda leitura -- e nao confiar em leitura de fora e exatamente o motivo
    pelo qual esta funcao rele sob lock.

    `trilha is None` significa "o resultado nao mudou, e nada foi gravado".
    **Nao confunda com o `None` que a funcao devolve**, que significa "nao
    havia sujeito": sem linha de qualificacao nao ha lead a pontuar, e
    `score.py` ja distingue a ausencia de sujeito de uma nota igual a zero.

    `anterior is None` e a coluna `temperatura` nula -- lead nunca
    recalculado, ou linha anterior a TEC-151. **Nao e sinonimo de FRIO**: a
    borda da RN-06.5 dispara quando `anterior` nao era QUENTE e agora e, e um
    lead cujo primeiro recalculo cai em QUENTE de fato esquentou.

    `gatilhos` sao os desta fala, e nao os acumulados na coluna: e o que o
    evento do log precisa dizer sobre POR QUE esquentou agora. Vazio quando a
    temperatura veio da faixa.

    `total` acompanha para o log poder distinguir um QUENTE de faixa (70+) de
    um QUENTE forcado sobre score baixo, que sao fatos operacionais bem
    diferentes para quem le.
    """

    trilha: LeadScoreAudit | None
    temperatura: Temperatura
    anterior: Temperatura | None
    gatilhos: tuple[str, ...]
    total: int


async def registrar_recalculo(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    gatilhos: tuple[str, ...] = (),
    causas_externas: tuple[str, ...] = (),
) -> Recalculo | None:
    """Recalcula o score do lead e grava a trilha se ele mudou.

    Devolve `None` quando **nao havia estado a pontuar**, e um `Recalculo`
    com `trilha is None` quando havia estado, o resultado foi identico ao
    ultimo registrado **e o chamador nao informou `causas_externas`** -- com
    causa externa a linha nasce mesmo com o resultado identico, que e o ponto
    do parametro (ver abaixo). Os dois casos eram o mesmo `None` ate a
    TEC-151, e ela
    os separou porque a temperatura pode mudar num turno em que nenhum dos
    cinco fatores se move -- um gatilho da RN-06.3 e exatamente isso.

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

    **Desde a TEC-136 o upsert nao e mais o primeiro a tomar este cadeado.**
    `aplicar_mudanca_de_intencao` roda antes dos dois e, quando a intencao do
    turno e gravavel, faz `SELECT ... FOR UPDATE` sobre a mesma linha ate nos
    turnos em que devolve `None` -- e sao a maioria, porque a intencao
    acumulada raramente muda. Nesses turnos o lock daqui e redundante mesmo sem
    campo nenhum, que era o caso que o paragrafo acima dizia nao ter upsert. Nos
    outros -- INDEFINIDA e FORA_DE_ESCOPO, que aquela funcao recusa antes de
    tocar o banco -- nada muda. A ordem de aquisicao e a mesma linha nos dois
    casos, entao nao ha deadlock novo; a docstring daquela funcao argumenta isso
    do outro lado, e esta nota existe para a referencia cruzada valer nos dois
    sentidos.

    **A temperatura e resolvida ANTES da trilha, e a ordem e o ponto
    (TEC-151).** Ate esta card a funcao retornava cedo quando `causas` estava
    vazio; nao pode mais, porque um gatilho da RN-06.3 dispara em turno em que
    nenhum dos cinco fatores se move -- o lead pede visita, e o `return None`
    antecipado engoliria o forcamento. Ha teste de guarda para isso:
    `test_o_turno_sem_mudanca_de_score_ainda_resolve_a_temperatura`.

    **`causas_externas` entra na tupla ANTES da guarda `if not causas`, e e ai
    que esta o ponto (TEC-136).** A tupla vazia continua sendo o sinal de "nao
    grave" -- nenhum `if` novo decide gravar --, mas ela deixou de sair toda de
    `causas_do_recalculo`, que so enxerga os cinco fatores. Uma causa informada
    pelo chamador e um fato sobre a ORIGEM do gatilho, e nao sobre o que se
    moveu: e razao suficiente para a linha existir mesmo com os cinco fatores
    identicos. O caso concreto e a troca de intencao do lead, que pode nao
    mexer em fator nenhum e que a card pede registrada com o motivo. Unindo
    DEPOIS da guarda, essa troca sumiria da trilha -- que e exatamente o
    defeito que o parametro existe para fechar.

    **Nao confundir com `gatilhos`.** Aquele alimenta o forcamento de
    temperatura da RN-06.3 e nao decide nada sobre a trilha; este decide a
    trilha e nao toca na temperatura. Sao dois assuntos e por isso dois
    parametros.
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

    # `or ()` porque `NULL` (linha anterior a TEC-148) e `{}` (registrou, sem
    # recusa) sao estados diferentes na coluna, e esta leitura trata os dois
    # iguais -- mesmo raciocinio de `_recusados_de` em turno.py. Calculada uma
    # vez e passada para `calcular_score` e `esta_qualificado` abaixo: as duas
    # chamadas precisam do mesmo fato sobre a mesma linha, e duas copias do
    # `frozenset(...)` seriam duas copias deste comentario para manter certas.
    recusados = frozenset(estado.campos_recusados or ())

    novo = calcular_score(
        estado,
        mensagens_do_lead=await contar_mensagens_do_lead(
            session, channel=channel, conversation_key=conversation_key
        ),
        # Explicito, e nao pelo default: a busca de imoveis (TEC-158) nao
        # existe, e a TEC-150 prescreve que ate la o fator contribua zero.
        # Quando ela existir, este e o unico ponto que muda.
        imoveis_compativeis=0,
        # TEC-148: a recusa sai da mesma linha que o lock acabou de reler,
        # entao nao ha consulta extra e nao ha risco de ler estado velho.
        recusados=recusados,
    )

    # A temperatura sai da MESMA linha travada que o score, e o `qualificado`
    # tambem. Nao vem do `antes` de `turno.py`: aquele foi lido por
    # `montar_contexto` numa OUTRA sessao, antes do bloco transacional, e um
    # turno concorrente da mesma conversa pode ter commitado no intervalo --
    # o teto seria aplicado sobre qualificacao velha. Mesma razao pela qual o
    # estado vem do `FOR UPDATE` daqui, e nao de `depois_do_estado`.
    qualificado = esta_qualificado(estado, recusados)

    # As duas metades do forcamento, e a persistida e a que o cenario 3 da
    # card exige. O segundo termo forca AGORA (o pedido de visita chegando
    # neste turno); o primeiro MANTEM forcado depois -- e e o unico que
    # responde ao cenario 3, porque o turno que rebaixaria e justamente um
    # turno SEM gatilho: o lead pediu visita ha tres turnos, agora so
    # respondeu "ok", e `gatilhos` esta vazio. Sem o termo persistido,
    # `temperatura_de` voltaria a olhar o score e devolveria FRIO.
    forcada = estado.temperatura_forcada_em is not None or bool(gatilhos)

    anterior = Temperatura(estado.temperatura) if estado.temperatura else None
    temperatura = temperatura_de(novo, qualificado=qualificado, forcada=forcada)

    # So os motivos que a coluna AINDA nao tem -- e nao `gatilhos` bruto --
    # decidem se ha algo NOVO a escrever. Um lead ja forcado que repete a
    # mesma fala ("quero agendar visita" de novo) devolve `gatilhos` nao
    # vazio todo turno, mas nao ha motivo novo nenhum: usar `gatilhos` ali
    # fazia o UPDATE disparar a cada turno e a coluna crescer
    # (['VISITA', 'VISITA', ...]) para sempre, o que nem a duplicata
    # tolerada das colunas irmas justifica -- aquelas duplicam quando o LEAD
    # diz duas coisas diferentes que colidem no mesmo nome, esta duplicava
    # quando ele repetia a MESMA fala.
    novos = tuple(g for g in gatilhos if g not in (estado.temperatura_forcada_motivos or ()))

    # `or novos` no teste, e nao so a mudanca de temperatura: um lead que JA
    # era QUENTE forcado e menciona proposta pela primeira vez nao muda de
    # temperatura, mas o motivo novo tem de entrar na coluna. Duplicata
    # continua possivel dentro de UM turno so (`gatilhos_de` pode repetir a
    # tupla se o texto casar o mesmo motivo duas vezes) e nao incomoda, mesma
    # aceitacao das duas colunas de array vizinhas -- o que este calculo
    # fecha e so a duplicata ENTRE turnos.
    if temperatura is not anterior or novos:
        valores: dict[str, Any] = {
            "temperatura": temperatura.value,
            "updated_at": datetime.now(UTC),
        }
        if novos:
            valores["temperatura_forcada_em"] = func.coalesce(
                LeadQualification.temperatura_forcada_em, func.clock_timestamp()
            )
            # A uniao mora no SQL, no molde da coluna irma `campos_recusados`
            # em `gravar_estado` -- mesma forma, por consistencia, e nao pela
            # mesma razao: aquele UPDATE nao tem lock, e este roda sob o `FOR
            # UPDATE` que `estado` ja tomou, entao a corrida entre dois
            # turnos que aquele comentario descreve nao existe aqui.
            #
            # `coalesce` porque `NULL || {'VISITA'}` e NULL em Postgres, e
            # toda linha anterior a esta card tem NULL aqui. `novos` e nao
            # `gatilhos` no `cast`: e o mesmo calculo que decidiu entrar
            # neste `if`, e gravar `gatilhos` aqui reabriria o crescimento
            # sem fim que `novos` existe para fechar.
            valores["temperatura_forcada_motivos"] = func.coalesce(
                LeadQualification.temperatura_forcada_motivos,
                literal_column("'{}'::varchar[]"),
            ).op("||")(cast(list(novos), ARRAY(String(16))))
        await session.execute(
            update(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .values(**valores)
        )
        # Sem `populate_existing`, e nao por descuido: este e um Core
        # `update()` contra uma entidade ORM, executado por `Session.execute`
        # com `synchronize_session="auto"` (o default), que sincroniza cada
        # coluna do `SET` de um jeito diferente conforme o valor.
        #
        # `temperatura` e `updated_at` sao literais Python (`str`, `datetime`)
        # -- o avaliador consegue calcula-los e os atribui direto na
        # instancia que a sessao ja tem (`estado`, mesma linha, pelo identity
        # map), sem expirar nada.
        #
        # `temperatura_forcada_em` e `temperatura_forcada_motivos` -- gravadas
        # so quando `novos` nao e vazio -- sao expressao SQL
        # (`func.coalesce`, `.op("||")`), que o avaliador nao sabe calcular em
        # Python. Para essas duas, e so essas duas, ele EXPIRA os atributos
        # correspondentes em vez de sincroniza-los; a proxima leitura --
        # inclusive um `session.get` depois do commit, como os testes fazem --
        # dispara SELECT e volta com o valor gravado. Mesma familia de
        # comportamento implicito que o comentario de `populate_existing` em
        # `gravar_estado` documenta, so que aqui e a ausencia da opcao que e o
        # ponto.

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

    # As externas primeiro, e nao por estilo: quem le a trilha quer saber o que
    # DISPAROU o registro antes de ler o que se moveu, e a ordem das derivadas
    # ja e a de `Score` (a docstring de `causas_do_recalculo` conta com isso
    # para o teste comparar por igualdade). Prefixar preserva as duas ordens.
    causas = causas_externas + causas_do_recalculo(_score_do_registro(ultimo), novo)
    if not causas:
        return Recalculo(
            trilha=None,
            temperatura=temperatura,
            anterior=anterior,
            gatilhos=gatilhos,
            total=novo.total,
        )

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
    # Flush e nao commit: a sessao e emprestada e o commit e de quem chamou,
    # mas a linha tem de estar visivel a uma leitura posterior na mesma
    # transacao -- inclusive a que a proxima chamada faz para achar o "ultimo
    # registro".
    await session.flush()
    return Recalculo(
        trilha=linha,
        temperatura=temperatura,
        anterior=anterior,
        gatilhos=gatilhos,
        total=novo.total,
    )
