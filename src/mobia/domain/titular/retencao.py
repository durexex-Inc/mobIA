"""A retencao do lead: transcricao de 12 meses, lead parado ha 24. TEC-207, D5.

**As duas regras de idade (12 e 24 meses) nao decidem sozinhas o que pode ser
apagado** -- pedem as linhas com o corte certo sobre `clock_timestamp()` do
banco, e nao `datetime.now()` do worker, pela mesma razao de
`auditoria/retencao.py`. `cumprir_eliminacoes_vencidas` e diferente: o prazo
que ela cumpre (`prazo_em`) ja foi calculado em `registrar_solicitacao`
(RNF-21, 15 dias) a partir de `datetime.now(UTC)`, e comparar contra o mesmo
relogio aqui e consistente com aquele calculo -- nao ha um segundo corte para
divergir do banco.

Tres operacoes. `esvaziar_transcricoes_vencidas` e `anonimizar_leads_vencidos`
varrem o banco em lotes, com commit por lote (ou por lead, na anonimizacao),
para nao segurar lock longo sobre uma tabela que pode ter milhoes de linhas.
`cumprir_eliminacoes_vencidas` e diferente: `repositorio.vencidas` ja devolve
a lista inteira das solicitacoes vencidas num SELECT so (normalmente pequena
-- e gente que pediu, nao mensagem), e esta funcao apenas poda essa lista a
`lote` itens por passagem, sem reconsultar o banco a cada fatia.

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

**Um lead que falha nao trava os outros, nem se repete para sempre.** As
duas funcoes que iteram lead a lead (`anonimizar_leads_vencidos` e
`cumprir_eliminacoes_vencidas`) capturam excecao por item: um lead com dado
inconsistente, ou uma falha transitoria de banco, loga
`titular.anonimizacao_por_retencao_falhou` ou `titular.eliminacao_vencida_falhou`
(com `lead_ref`/`solicitacao_id`, nunca telefone) e segue para o proximo. Sem
isso, a selecao em lote e ordenada (`ORDER BY max(created_at)` e
`ORDER BY prazo_em`), entao o MESMO lead problematico apareceria primeiro em
toda passagem futura, bloqueando quem vem depois dele para sempre.

**As duas funcoes de lote tambem tem um teto de lotes por passagem
(`max_lotes`).** Existe por causa do `job_timeout` do worker (D5 em
`workers/main.py`): sem teto, o primeiro dia com um backlog grande (ou uma
recuperacao apos um periodo sem o cron rodar) varreria tudo de uma vez,
arriscando estourar o timeout no meio de um `DELETE`/`UPDATE` e deixando
tanto o commit quanto o log de conclusao pendentes. Com o teto, um backlog
grande drena em varias passagens diarias em vez de numa so -- nunca se perde
trabalho (cada lote comita e fica pronto), so demora mais dias para zerar.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.auditoria.referencia import lead_ref as calcular_lead_ref
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
LOTE_PADRAO_DE_ELIMINACOES = 100

# Ate 10 mil mensagens por passagem (20 x 500) -- cada lote e dois statements
# em massa (um DELETE, um UPDATE), baratos mesmo em milhares de linhas.
MAXIMO_DE_LOTES_DE_TRANSCRICOES = 20

# Ate 200 leads por passagem (2 x 100) -- bem mais caro por unidade que a
# transcricao: cada lead paga um `eliminacao.anonimizar` inteiro, com
# DISABLE/ENABLE TRIGGER (ACCESS EXCLUSIVE, ainda que breve) e cerca de dez
# DELETE/UPDATE em tabelas diferentes.
MAXIMO_DE_LOTES_DE_LEADS = 2

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
# mais urgentes primeiro. E so um SNAPSHOT: `_lead_ainda_vencido` reconfere
# cada par antes de anonimizar de verdade (ver a docstring dela).
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

# A mesma condicao da consulta acima, so que para UM par, calculada dentro da
# transacao que vai anonimizar -- ver `_lead_ainda_vencido`. `COALESCE` com
# `clock_timestamp()` e so defensivo: um par sem mensagem nenhuma nunca
# deveria aparecer aqui (ele so existe por ter passado pela consulta em lote,
# que exige `messages`), mas se acontecer, o COALESCE faz a condicao falhar
# em vez de comparar `NULL < ...` e propagar `NULL` para o booleano.
_LEAD_AINDA_VENCIDO = text(
    f"""
    SELECT
        NOT EXISTS (
            SELECT 1 FROM handoffs h
            WHERE h.channel = :c AND h.conversation_key = :k
              AND h.status IN ('ACEITO', 'CONCLUIDO')
        )
        AND COALESCE(
            (SELECT max(created_at) FROM messages WHERE channel = :c AND conversation_key = :k),
            clock_timestamp()
        ) < clock_timestamp() - interval '{RETENCAO_DO_LEAD_MESES} months'
    """
)


async def _lead_ainda_vencido(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> bool:
    """Reconfere handoff e idade agora, dentro da transacao que vai anonimizar.

    `anonimizar_leads_vencidos` monta o lote com um SELECT separado, e o
    par pode ter deixado de valer a condicao no intervalo ate ser processado
    -- uma mensagem nova chegou (o lead voltou a falar) ou um handoff virou
    ACEITO. As duas coisas tornam o snapshot do lote obsoleto, e anonimizar
    mesmo assim apagaria uma conversa que ja nao esta parada.
    """
    resultado = await session.scalar(_LEAD_AINDA_VENCIDO, {"c": channel, "k": conversation_key})
    return bool(resultado)


async def esvaziar_transcricoes_vencidas(
    session_factory: async_sessionmaker[AsyncSession],
    armazem: ArmazemDeMidia,
    *,
    lote: int = LOTE_PADRAO_DE_TRANSCRICOES,
    max_lotes: int = MAXIMO_DE_LOTES_DE_TRANSCRICOES,
) -> int:
    """Esvazia conteudo de mensagem com mais de 12 meses; devolve quantas linhas.

    Por lote: le os ids vencidos com conteudo ainda presente, apaga a LINHA
    de midia e zera as tres colunas de conteudo -- os dois antes do commit.
    O BLOB em si so cai depois do commit (fora da transacao, num armazem que
    nao participa dela), mesma ordem de `eliminacao.anonimizar` e pela mesma
    razao: um rollback nao pode deixar linha apontando para blob que ja
    sumiu. O laco para no primeiro lote incompleto, ou ao atingir
    `max_lotes` (ver a docstring do modulo) -- o que vier primeiro.

    **Um `CancelledError` no meio do laco de blobs nao vaza em silencio.** O
    laco de apagar esta dentro de um `try/except BaseException`: se o worker
    cancelar a corrotina ali (job_timeout, SIGTERM), o log
    `titular.midia_apagamento_cancelado` sai com as chaves que ainda nao
    foram confirmadas apagadas, e a excecao e repropagada -- o cancelamento
    continua cancelamento, so que agora com rastro de quais blobs podem ter
    ficado orfaos.

    Termina apagando `conversation_summaries` dos pares cuja ultima mensagem
    tambem passou do corte -- um resumo e derivado da transcricao, e nao ha
    por que sobreviver a ela.
    """
    if lote < 1:
        raise ValueError(f"lote tem de ser positivo: {lote}")
    total = 0
    lotes_processados = 0
    while True:
        if lotes_processados >= max_lotes:
            break
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

        restantes = list(chaves_de_midia)
        try:
            while restantes:
                chave = restantes[0]
                try:
                    await armazem.apagar(chave)
                except Exception:
                    log.warning("titular.midia_nao_apagada", chave=chave, exc_info=True)
                restantes.pop(0)
        except BaseException:
            log.warning("titular.midia_apagamento_cancelado", chaves_restantes=restantes)
            raise

        total += len(ids)
        lotes_processados += 1
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
    max_lotes: int = MAXIMO_DE_LOTES_DE_LEADS,
) -> int:
    """Anonimiza todo lead sem conversao parado ha mais de 24 meses.

    Por lead, e nao por lote unico: cada par recebe sua propria solicitacao
    (commitada sozinha) e sua propria chamada a `eliminacao.anonimizar`, que
    abre e fecha a transacao dela. **Um lead por transacao** (D5) -- um erro
    no meio do sweep nao derruba os que ja foram cumpridos.

    Antes de cada anonimizacao, `_lead_ainda_vencido` reconfere o par na
    hora: o SELECT em lote e um snapshot, e o lead pode ter escrito de novo
    ou ganho um handoff ACEITO enquanto esperava a vez dele no lote.

    **Um lead que falha nao para os outros.** A chamada inteira (recheck,
    `registrar_solicitacao`, `eliminacao.anonimizar`) esta num
    `try/except Exception` por lead: uma falha loga
    `titular.anonimizacao_por_retencao_falhou` com `lead_ref` (e
    `solicitacao_id`, se ja existir) e segue para o proximo par -- sem isso,
    o MESMO lead problematico venceria primeiro em toda passagem futura
    (`ORDER BY max(created_at)`) e travaria quem vem depois dele para
    sempre. `total` conta só quem foi anonimizado com sucesso.
    """
    total = 0
    lotes_processados = 0
    while True:
        if lotes_processados >= max_lotes:
            break
        async with session_factory() as session:
            pares = list(
                (await session.execute(_SELECIONAR_LOTE_DE_LEADS_VENCIDOS, {"lote": lote})).all()
            )
        for channel, conversation_key in pares:
            lead_ref_do_par = calcular_lead_ref(
                channel, conversation_key, chave=get_settings().auditoria_chave_do_lead
            )
            solicitacao_id: uuid.UUID | None = None
            try:
                async with session_factory() as session:
                    if not await _lead_ainda_vencido(
                        session, channel=channel, conversation_key=conversation_key
                    ):
                        log.info("titular.retencao_lead_nao_mais_vencido", lead_ref=lead_ref_do_par)
                        continue
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
            except Exception:
                log.warning(
                    "titular.anonimizacao_por_retencao_falhou",
                    lead_ref=lead_ref_do_par,
                    solicitacao_id=str(solicitacao_id) if solicitacao_id is not None else None,
                    exc_info=True,
                )
        lotes_processados += 1
        if len(pares) < lote:
            break

    log.info("titular.leads_anonimizados_por_retencao", contagem=total)
    return total


async def cumprir_eliminacoes_vencidas(
    session_factory: async_sessionmaker[AsyncSession],
    armazem: ArmazemDeMidia,
    *,
    lote: int = LOTE_PADRAO_DE_ELIMINACOES,
) -> int:
    """Cumpre solicitacao ELIMINACAO ABERTA cujo prazo de 15 dias passou.

    `repositorio.vencidas` devolve a lista inteira num SELECT so -- ela e
    ordenada por `prazo_em` (quem venceu ha mais tempo primeiro), e esta
    funcao poda essa lista a `lote` itens por passagem, a mesma razao de
    `max_lotes` nas outras duas funcoes (D5, `workers/main.py`): sem o teto,
    um backlog grande arriscaria estourar o `job_timeout` do worker numa so
    passagem. Um backlog maior que `lote` drena em varias passagens diarias.

    **Uma solicitacao que falha nao para as outras**, pela mesma razao de
    `anonimizar_leads_vencidos`: cada `eliminacao.anonimizar` esta num
    `try/except Exception` por item, e uma falha loga
    `titular.eliminacao_vencida_falhou` com `solicitacao_id` e `lead_ref` (a
    coluna sobrevive a anonimizacao, ver `models.py`) e segue. `total` conta
    so quem foi cumprida com sucesso.
    """
    async with session_factory() as session:
        pendentes = await vencidas(
            session, agora=datetime.now(UTC), tipo=TipoDeSolicitacao.ELIMINACAO
        )
    total = 0
    for solicitacao in pendentes[:lote]:
        try:
            await eliminacao.anonimizar(session_factory, armazem, solicitacao_id=solicitacao.id)
            total += 1
        except Exception:
            log.warning(
                "titular.eliminacao_vencida_falhou",
                solicitacao_id=str(solicitacao.id),
                lead_ref=solicitacao.lead_ref,
                exc_info=True,
            )
    log.info("titular.eliminacoes_vencidas_cumpridas", contagem=total)
    return total
