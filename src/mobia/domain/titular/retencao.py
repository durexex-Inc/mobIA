"""A retencao do lead: transcricao de 12 meses, lead parado ha 24. TEC-207, D5.

**As duas regras de idade (12 e 24 meses) nao decidem sozinhas o que pode ser
apagado** -- pedem as linhas com o corte certo sobre `clock_timestamp()` do
banco, e nao `datetime.now()` do worker, pela mesma razao de
`auditoria/retencao.py`. `cumprir_eliminacoes_vencidas` e diferente: o prazo
que ela cumpre (`prazo_em`) ja foi calculado em `registrar_solicitacao`
(RNF-21, 15 dias) a partir de `datetime.now(UTC)`, e comparar contra o mesmo
relogio aqui e consistente com aquele calculo -- nao ha um segundo corte para
divergir do banco.

Tres operacoes, cada uma varrendo em lotes com commit por lote (ou por lead,
na anonimizacao) para nao segurar lock longo sobre uma tabela que pode ter
milhoes de linhas:

- `esvaziar_transcricoes_vencidas`: conteudo de mensagem com mais de 12 meses
  vira nulo, a midia correspondente e apagada, e a linha fica -- ela e quem
  ancora a coorte do funil (`metricas/repositorio.py::_nascimento`). Tambem
  apaga `conversation_summaries` de pares cuja ultima mensagem passou do
  mesmo corte.
- `anonimizar_leads_vencidos`: lead sem handoff ACEITO/CONCLUIDO, parado ha
  mais de 24 meses (`max(messages.created_at)`, a mesma base de
  `leads/repositorio.py::_ultima_interacao`), vira uma solicitacao ELIMINACAO
  de origem RETENCAO, cumprida na hora por `eliminacao.anonimizar`.
- `cumprir_eliminacoes_vencidas`: toda solicitacao ELIMINACAO ABERTA cujo
  prazo de 15 dias (RNF-21) ja passou -- o titular pediu, o ADMIN nao decidiu
  a tempo, e o prazo legal nao pode depender de inacao.

**Par ja anonimizado nao entra de novo em `anonimizar_leads_vencidos`.** A
anonimizacao apaga a linha de `identidades_de_lead` do par (ver
`anonimizacao.py`), e o pseudonimo que sobra nunca fala de novo -- a ultima
mensagem dele continua no passado para sempre. Sem a exclusao por
`identidades_de_lead`, cada passagem do sweep voltaria a "anonimizar" o mesmo
pseudonimo, criando uma solicitacao RETENCAO nova a cada dia.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.midia.armazem import ArmazemDeMidia
from mobia.domain.midia.politica import chave_do_objeto
from mobia.domain.titular import eliminacao
from mobia.domain.titular.repositorio import registrar_solicitacao, vencidas
from mobia.domain.titular.vocabulario import (
    RETENCAO_DA_TRANSCRICAO_MESES,
    RETENCAO_DO_LEAD_MESES,
    OrigemDaSolicitacao,
    TipoDeSolicitacao,
)

log = structlog.get_logger(__name__)

LOTE_PADRAO_DE_TRANSCRICOES = 500
LOTE_PADRAO_DE_LEADS = 100

_SELECIONAR_LOTE_DE_MENSAGENS_VENCIDAS = text(
    f"""
    SELECT id FROM messages
    WHERE created_at < clock_timestamp() - interval '{RETENCAO_DA_TRANSCRICAO_MESES} months'
      AND (text_body IS NOT NULL OR raw_payload IS NOT NULL OR envelope_context IS NOT NULL)
    ORDER BY created_at
    LIMIT :lote
    FOR UPDATE
    """
)

_MIDIAS_DO_LOTE = text(
    "SELECT message_id, chave_no_armazem FROM midias_recebidas WHERE message_id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_APAGAR_MIDIAS_DO_LOTE = text("DELETE FROM midias_recebidas WHERE message_id IN :ids").bindparams(
    bindparam("ids", expanding=True)
)

_ESVAZIAR_MENSAGENS_DO_LOTE = text(
    "UPDATE messages SET text_body = NULL, raw_payload = NULL, envelope_context = NULL"
    " WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_APAGAR_RESUMOS_VENCIDOS = text(
    f"""
    DELETE FROM conversation_summaries cs
    WHERE (
        SELECT max(m.created_at) FROM messages m
        WHERE m.channel = cs.channel AND m.conversation_key = cs.conversation_key
    ) < clock_timestamp() - interval '{RETENCAO_DA_TRANSCRICAO_MESES} months'
    """
)

# Pares sem handoff ACEITO/CONCLUIDO, com identidade (ver a docstring do
# modulo) e parados ha mais que o corte -- na ordem de quem esta parado ha
# mais tempo, para que uma interrupcao no meio do sweep tenha cumprido os
# mais urgentes primeiro.
_SELECIONAR_LOTE_DE_LEADS_VENCIDOS = text(
    f"""
    SELECT m.channel, m.conversation_key
    FROM messages m
    WHERE EXISTS (
        SELECT 1 FROM identidades_de_lead i
        WHERE i.channel = m.channel AND i.conversation_key = m.conversation_key
    )
    AND NOT EXISTS (
        SELECT 1 FROM handoffs h
        WHERE h.channel = m.channel AND h.conversation_key = m.conversation_key
          AND h.status IN ('ACEITO', 'CONCLUIDO')
    )
    GROUP BY m.channel, m.conversation_key
    HAVING max(m.created_at) < clock_timestamp() - interval '{RETENCAO_DO_LEAD_MESES} months'
    ORDER BY max(m.created_at)
    LIMIT :lote
    """
)


async def esvaziar_transcricoes_vencidas(
    session_factory: async_sessionmaker[AsyncSession],
    armazem: ArmazemDeMidia,
    *,
    lote: int = LOTE_PADRAO_DE_TRANSCRICOES,
) -> int:
    """Esvazia conteudo de mensagem com mais de 12 meses; devolve quantas linhas.

    Por lote: le os ids vencidos com conteudo ainda presente, apaga a midia
    (linha e blob) e zera as tres colunas de conteudo, tudo antes do commit --
    o blob em si so cai DEPOIS, mesma ordem de `eliminacao.anonimizar` e pela
    mesma razao (um rollback nao pode deixar linha apontando para blob que ja
    sumiu). O laco para no primeiro lote incompleto.

    Termina apagando `conversation_summaries` dos pares cuja ultima mensagem
    tambem passou do corte -- um resumo e derivado da transcricao, e nao ha
    por que sobreviver a ela.
    """
    if lote < 1:
        raise ValueError(f"lote tem de ser positivo: {lote}")
    total = 0
    while True:
        async with session_factory() as session:
            ids: list[uuid.UUID] = list(
                (
                    await session.execute(_SELECIONAR_LOTE_DE_MENSAGENS_VENCIDAS, {"lote": lote})
                ).scalars()
            )
            chaves_de_midia: list[str] = []
            if ids:
                midias = (await session.execute(_MIDIAS_DO_LOTE, {"ids": ids})).all()
                chaves_de_midia = sorted(
                    {
                        chave if chave is not None else chave_do_objeto(message_id)
                        for message_id, chave in midias
                    }
                )
                await session.execute(_APAGAR_MIDIAS_DO_LOTE, {"ids": ids})
                await session.execute(_ESVAZIAR_MENSAGENS_DO_LOTE, {"ids": ids})
            await session.commit()

        for chave in chaves_de_midia:
            try:
                await armazem.apagar(chave)
            except Exception:
                log.warning("titular.midia_nao_apagada", chave=chave, exc_info=True)

        total += len(ids)
        if len(ids) < lote:
            break

    async with session_factory() as session:
        await session.execute(_APAGAR_RESUMOS_VENCIDOS)
        await session.commit()

    log.info("titular.transcricoes_esvaziadas", contagem=total)
    return total


async def anonimizar_leads_vencidos(
    session_factory: async_sessionmaker[AsyncSession],
    armazem: ArmazemDeMidia,
    *,
    lote: int = LOTE_PADRAO_DE_LEADS,
) -> int:
    """Anonimiza todo lead sem conversao parado ha mais de 24 meses.

    Por lead, e nao por lote unico: cada par recebe sua propria solicitacao
    (commitada sozinha) e sua propria chamada a `eliminacao.anonimizar`, que
    abre e fecha a transacao dela. **Um lead por transacao** (D5) -- um erro
    no meio do sweep nao derruba os que ja foram cumpridos, e a proxima
    passagem retoma do que sobrou, porque quem ja foi anonimizado sai da
    consulta (ver a docstring do modulo).
    """
    total = 0
    while True:
        async with session_factory() as session:
            pares = list(
                (await session.execute(_SELECIONAR_LOTE_DE_LEADS_VENCIDOS, {"lote": lote})).all()
            )
        for channel, conversation_key in pares:
            async with session_factory() as session:
                solicitacao_id = await registrar_solicitacao(
                    session,
                    channel=channel,
                    conversation_key=conversation_key,
                    tipo=TipoDeSolicitacao.ELIMINACAO,
                    origem=OrigemDaSolicitacao.RETENCAO,
                    ator=ATOR_SISTEMA,
                )
                await session.commit()
            await eliminacao.anonimizar(session_factory, armazem, solicitacao_id=solicitacao_id)
            total += 1
        if len(pares) < lote:
            break

    log.info("titular.leads_anonimizados_por_retencao", contagem=total)
    return total


async def cumprir_eliminacoes_vencidas(
    session_factory: async_sessionmaker[AsyncSession], armazem: ArmazemDeMidia
) -> int:
    """Cumpre toda solicitacao ELIMINACAO ABERTA cujo prazo de 15 dias passou.

    So le a lista uma vez -- ao contrario das outras duas funcoes deste
    modulo, aqui nao ha por que reconsultar: `eliminacao.anonimizar` fecha
    cada solicitacao como ATENDIDA, e uma que passou pelo prazo nunca volta a
    ser ABERTA.
    """
    async with session_factory() as session:
        pendentes = await vencidas(
            session, agora=datetime.now(UTC), tipo=TipoDeSolicitacao.ELIMINACAO
        )
    for solicitacao in pendentes:
        await eliminacao.anonimizar(session_factory, armazem, solicitacao_id=solicitacao.id)
    log.info("titular.eliminacoes_vencidas_cumpridas", contagem=len(pendentes))
    return len(pendentes)
