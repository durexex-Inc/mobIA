"""Recupera o download de midia cujo enfileiramento se perdeu. TEC-132, D3.

Cron proprio, e nao um passo da `sweep_stalled`: aquela varre `messages` a
cada 30 segundos com um contrato documentado sobre `attempts` e status da
mensagem, e misturar outra tabela nela obrigaria a reescrever esse contrato.
"""

from datetime import timedelta
from typing import Any

import structlog

from mobia.domain.midia.repositorio import (
    esgotar_pendentes,
    expirar_pendentes,
    pendentes_para_reenfileirar,
)
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

# Quantas vezes esta varredura re-enfileira a mesma linha antes de fecha-la
# como FALHOU/TENTATIVAS_ESGOTADAS. O que chega aqui nao e a Graph API fora do
# ar -- essa passa pelo `Retry` de `baixar_midia` e fecha sozinha depois de
# `MAXIMO_DE_TENTATIVAS` --, e a falha que escapa do `Retry`: o `job_timeout`
# de um arquivo grande ou lento, um erro de banco no `marcar`, uma excecao
# inesperada. Essas se repetem para o mesmo arquivo, e sem teto a linha
# voltava a fila a cada 5 minutos por 7 dias, ~2000 jobs no mesmo token das
# mensagens de saida. Seis passadas sao ~30 minutos alem dos 10 da janela:
# folga para um banco ou um Redis que caiu voltar, e um teto de 6 x
# `MAXIMO_DE_TENTATIVAS` jobs por arquivo em vez de ~2000.
TETO_DE_REENFILEIRAMENTOS = 6


async def sweep_midias_pendentes(ctx: dict[str, Any], limite: int = 100) -> int:
    """Expira as velhas demais, fecha as que chegaram no teto e re-enfileira
    as da janela. Devolve quantas re-enfileirou.

    Expirar e esgotar vem antes de reivindicar para que uma linha nunca seja
    fechada e re-enfileirada na mesma passagem -- as fronteiras sao as mesmas
    constantes. Com o teto em 6, a linha re-enfileirada seis vezes fecha na
    setima passagem.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    expiradas = await expirar_pendentes(session_factory, mais_velhas_que=EXPIRAR_APOS)
    # As duas em WARNING, como os desfechos FALHOU de `baixar_midia`: as duas
    # fecham a linha como FALHOU, midia que o sistema desistiu de guardar, e e
    # esse o nivel que pode alimentar alerta.
    if expiradas:
        log.warning("midia.expiradas", count=expiradas)

    esgotadas = await esgotar_pendentes(session_factory, teto=TETO_DE_REENFILEIRAMENTOS)
    if esgotadas:
        log.warning("midia.tentativas_esgotadas", count=esgotadas)

    ids = await pendentes_para_reenfileirar(
        session_factory,
        mais_velhas_que=REENFILEIRAR_APOS,
        mais_novas_que=EXPIRAR_APOS,
        teto=TETO_DE_REENFILEIRAMENTOS,
        limite=limite,
    )
    enfileiradas = 0
    for message_id in ids:
        try:
            novo = await enqueue_baixar_midia(redis, message_id)
        except Exception as exc:
            # Mesma forma da `sweep_stalled`: uma linha que falha nao aborta as
            # outras, e a proxima passagem tenta de novo -- ja com esta
            # passagem contada em `tentativas`, que sobe ao reivindicar. `detail` fica pelo
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
