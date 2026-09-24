"""O job que redige o resumo do handoff e encadeia o que vem depois dele.

TEC-175, TEC-177, TEC-180. Sao DOIS enfileiramentos desde a TEC-180, e nao so
o da notificacao: o aviso ao corretor (RN-16.2) e a exportacao para o CRM
(RN-16.5). Os dois saem daqui pela mesma razao -- e neste ponto que o resumo
existe -- e os dois tem a mesma guarda contra falha de Redis.
"""

import uuid
from typing import Any

import structlog

from mobia.domain.handoff.geracao import gerar_resumo as _gerar
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.exportar_crm import EXPORTAR_CRM_JOB
from mobia.workers.jobs.notificar import NOTIFICAR_JOB

log = structlog.get_logger(__name__)


async def gerar_resumo(ctx: dict[str, Any], handoff_id: str) -> str:
    """Gera o resumo, enfileira a notificacao do corretor e a exportacao para o CRM.

    O redator vem do `ctx` e nao e construido aqui, pelo mesmo motivo que o
    `classificador` e o `resumidor` do `process_message` vem de la: e o
    `startup` do worker que decide qual implementacao roda, e o teste troca a
    decisao sem tocar no job.

    **Os DOIS enfileiramentos sao INDEPENDENTES de `gravou`.** A D2 do desenho
    de TEC-177 manda avisar o corretor mesmo quando o resumo nao pode ser
    gerado -- e o handoff sem resumo e justamente o que mais precisa do
    aviso, nao um caso a pular. A D10 da TEC-180 estende o mesmo argumento a
    exportacao. `notificar_corretor` (Task 4) monta um corpo proprio para o
    caso sem resumo e o payload do CRM leva `resumo: null`; este job so decide
    SE enfileira, nunca o conteudo.
    """
    gravou = await _gerar(
        get_sessionmaker(), redator=ctx["redator"], handoff_id=uuid.UUID(handoff_id)
    )

    # Nao propaga: o resumo (ou a ausencia dele) ja esta gravado neste ponto,
    # e uma falha do Redis aqui perderia so a notificacao, nunca o trabalho
    # que `_gerar` ja fez. Mesmo molde do `_agendar_resumo` em
    # `domain/agente/turno.py`. O `_job_id` fixo por handoff so evita duplicar
    # a notificacao enquanto o job `notificar:<id>` estiver VIVO -- o
    # `enqueue_job` do ARQ recusa quando a chave do job OU a de resultado
    # existe, e este job entra com `keep_result=0` (`workers/main.py`), entao
    # a chave de resultado some ao terminar. Uma retentativa que chegue DEPOIS
    # do `notificar_corretor` original ja ter concluido nao encontra nenhuma
    # das duas chaves e duplica a notificacao mesmo assim -- e a L3 do
    # desenho, declarada e nao corrigida aqui.
    try:
        await ctx["redis"].enqueue_job(NOTIFICAR_JOB, handoff_id, _job_id=f"notificar:{handoff_id}")
    except Exception as falha:
        # `motivo` alem do traceback, que desde a TEC-293 nao leva mensagem: o
        # texto de uma falha de `enqueue_job` e de conexao com o Redis, e e ele
        # que se le as tres da manha. Seguro aqui porque esta chamada so passa
        # `handoff_id` e o `_job_id` derivado dele -- UUID gerado por este
        # projeto. Mesmo argumento da D3 da TEC-292.
        log.warning(
            "notificacao.nao_agendada",
            handoff_id=handoff_id,
            motivo=str(falha),
            exc_info=True,
        )

    # TEC-180, D10. Mesmo molde e mesmo `try/except` da notificacao acima, pela
    # mesma razao: o resumo ja esta gravado neste ponto, e uma falha do Redis
    # nao pode desfazer isso. A diferenca e que aqui a perda TEM rede --
    # `sweep_crm_pendentes` recolhe o handoff que ficou com `crm_tentativas =
    # 0` depois da janela.
    #
    # **Independe de `gravou`**, pelo mesmo argumento que a D2 da TEC-177 usa
    # para a notificacao: o handoff sem resumo e o que mais precisa chegar a
    # uma pessoa, nao um caso a pular. O payload leva `resumo: null` e o CRM
    # decide o que fazer com isso.
    try:
        await ctx["redis"].enqueue_job(EXPORTAR_CRM_JOB, handoff_id, _job_id=f"crm:{handoff_id}")
    except Exception as falha:
        log.warning(
            "crm.exportacao_nao_agendada",
            handoff_id=handoff_id,
            motivo=str(falha),
            exc_info=True,
        )

    return "gravado" if gravou else "sem_resumo"
