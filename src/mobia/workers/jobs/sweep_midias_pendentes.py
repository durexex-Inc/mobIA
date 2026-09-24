"""Recupera o download de midia cujo enfileiramento se perdeu. TEC-132, D3.

Cron proprio, e nao um passo da `sweep_stalled`: aquela varre `messages` a
cada 30 segundos com um contrato documentado sobre `attempts` e status da
mensagem, e misturar outra tabela nela obrigaria a reescrever esse contrato.
"""

from datetime import timedelta
from typing import Any

import structlog

from mobia.domain.midia.repositorio import expirar_pendentes, pendentes_para_reenfileirar
from mobia.infra.queue import enqueue_baixar_midia

log = structlog.get_logger(__name__)

# Bem acima da duracao de um job normal, retentativas incluidas: os `Retry` de
# `baixar_midia` somam 30+60+90+120 = 300s de espera, e o job em voo nao e
# enfileiramento perdido. Mais curto, a varredura so bateria no `_job_id` de
# um job que ainda existe -- inofensivo, mas ruido.
REENFILEIRAR_APOS = timedelta(minutes=10)

# Abaixo da retencao da midia na Meta: passado isto, a URL provavelmente ja
# nao resolve, e a linha fecha como FALHOU/EXPIRADA em vez de ser tentada.
EXPIRAR_APOS = timedelta(days=7)


async def sweep_midias_pendentes(ctx: dict[str, Any], limite: int = 100) -> int:
    """Expira as velhas demais e re-enfileira as da janela. Devolve quantas
    re-enfileirou.

    Expirar vem antes de listar para que uma linha nunca seja as duas coisas
    na mesma passagem -- as fronteiras sao a mesma constante.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    expiradas = await expirar_pendentes(session_factory, mais_velhas_que=EXPIRAR_APOS)
    if expiradas:
        log.info("midia.expiradas", count=expiradas)

    ids = await pendentes_para_reenfileirar(
        session_factory,
        mais_velhas_que=REENFILEIRAR_APOS,
        mais_novas_que=EXPIRAR_APOS,
        limite=limite,
    )
    enfileiradas = 0
    for message_id in ids:
        try:
            novo = await enqueue_baixar_midia(redis, message_id)
        except Exception as exc:
            # Mesma forma da `sweep_stalled`: uma linha que falha nao aborta as
            # outras, e a proxima passagem tenta de novo. `detail` fica pelo
            # mesmo motivo de la -- o unico argumento e um UUID nosso.
            log.warning(
                "midia.enqueue_failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            continue
        if novo:
            enfileiradas += 1
    if enfileiradas:
        log.info("midia.reenfileiradas", count=enfileiradas)
    return enfileiradas
