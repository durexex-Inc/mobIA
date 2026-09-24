"""A varredura que reabre a exportacao para CRM parada. TEC-180, RN-16.5.

E ela que faz o terceiro cenario do Gherkin passar -- "dado um payload na fila
de reprocessamento, quando o webhook volta a responder, entao o envio e
concluido". Sem ela, tres falhas deixariam o handoff parado para sempre e
"fila de reprocessamento" seria so um nome para "desistimos".

**Sem teto de rodadas, de proposito.** Um CRM fora do ar por uma semana produz
uma rodada por ciclo de cron, para sempre, e cada rodada termina num `error`.
O alerta repetido e o sintoma de que alguem precisa olhar; parar de tentar
seria a perda silenciosa com outro nome. Ver a D8 e a lacuna L5 do desenho.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings
from mobia.domain.crm.port import MAX_TENTATIVAS
from mobia.workers.jobs.exportar_crm import EXPORTAR_CRM_JOB

log = structlog.get_logger(__name__)

SWEEP_CRM_JOB = "sweep_crm_pendentes"

# **Um statement, e nao as duas fases da `sweep_stalled`.** Mesmo argumento de
# `sweep_importacoes_travadas`: ali o SELECT e commitado antes do enqueue
# porque ha I/O de rede no meio. Aqui tambem ha -- o enqueue no Redis --, mas a
# escrita e a mesma linha que o SELECT trava, e o `RETURNING` ja entrega os ids
# para enfileirar DEPOIS do commit, fora do lock.
#
# `FOR UPDATE SKIP LOCKED` pela razao de sempre: duas varreduras concorrentes
# nao pegam a mesma linha.
#
# Os dois ramos do `WHERE` sao a D8, e ambos precisam existir:
#
# - `crm_tentativas >= :max_tentativas` -- a rodada anterior esgotou. Zerar o
#   contador E o que abre a rodada nova; o job so olha o numero.
# - `crm_tentativas = 0 AND criado_em < now() - janela` -- o enqueue nunca
#   aconteceu. E o caso do Redis fora do ar no instante em que `gerar_resumo`
#   tentou agendar, que o `try/except` de la engole de proposito para nao
#   perder o resumo ja gravado. Sem este ramo, esse handoff nunca seria
#   exportado e nada diria isso.
#
# O que fica de FORA dos dois: `0 < crm_tentativas < :max_tentativas`, que e
# uma rodada EM VOO, com um `Retry` pendente na fila do ARQ. Recolhe-la
# dispararia uma segunda rodada em paralelo com a primeira.
_REABRIR_PENDENTES = text(
    """
    UPDATE handoffs
       SET crm_tentativas = 0,
           atualizado_em = now()
     WHERE id IN (
             SELECT id
               FROM handoffs
              WHERE crm_sincronizado_em IS NULL
                AND (
                      crm_tentativas >= :max_tentativas
                      OR (
                           crm_tentativas = 0
                           AND criado_em < now() - make_interval(secs => :sem_tentativa_after)
                         )
                    )
              ORDER BY criado_em
              LIMIT :limite
                FOR UPDATE SKIP LOCKED
           )
    RETURNING id
    """
)


async def sweep_crm_pendentes(ctx: dict[str, Any], limite: int = 100) -> int:
    """Reabre a exportacao dos handoffs parados. Devolve quantos.

    **Sai antes de tocar o banco quando nao ha porta.** Sem `CRM_WEBHOOK_URL`,
    TODO handoff que ja existe se encaixa no segundo ramo do `WHERE` -- nenhum
    tem tentativa nenhuma --, e a varredura reenfileiraria a tabela inteira a
    cada ciclo de cron para que cada job saisse com "desligado". Ruido caro por
    uma feature que esta desligada.
    """
    if ctx.get("crm") is None:
        return 0

    settings: Settings = ctx.get("settings") or get_settings()
    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        resultado = await session.execute(
            _REABRIR_PENDENTES,
            {
                "max_tentativas": MAX_TENTATIVAS,
                "sem_tentativa_after": settings.sweep_crm_sem_tentativa_after_seconds,
                "limite": limite,
            },
        )
        ids: list[uuid.UUID] = [linha[0] for linha in resultado.fetchall()]
        await session.commit()

    for handoff_id in ids:
        # `try/except` por id, e nao em volta do laco: um Redis que recusa um
        # enqueue nao deve custar os outros da mesma passagem. O que ficar de
        # fora volta na proxima -- a linha ja esta com o contador zerado, e o
        # segundo ramo do `WHERE` a recolhe de novo.
        try:
            await ctx["redis"].enqueue_job(
                EXPORTAR_CRM_JOB, str(handoff_id), _job_id=f"crm:{handoff_id}"
            )
        except Exception as falha:
            log.warning(
                "crm.reenfileiramento_falhou",
                handoff_id=str(handoff_id),
                motivo=str(falha),
                exc_info=True,
            )

    if ids:
        log.info("crm.pendentes_reabertos", count=len(ids))
    return len(ids)
