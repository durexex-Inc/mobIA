"""O aviso de chave vencida. TEC-203, D1, RNF-14 (rotacao a cada 90 dias).

**Aviso, e nunca recusa.** Derrubar a producao porque uma data passou e pior
que o risco que a regra mitiga, e quem agenda a rotacao e o runbook, nao a
subida do processo. O log existe para o alarme do provedor pegar.
"""

from datetime import UTC, date, datetime, timedelta

import structlog

from mobia.app.config import Settings, data_do_id

log = structlog.get_logger(__name__)

VALIDADE = timedelta(days=90)


def chaves_vencidas(settings: Settings, hoje: date) -> list[str]:
    vencidas = []
    ativa = settings.content_encryption_key_ativa
    if ativa and hoje - data_do_id(ativa) > VALIDADE:
        vencidas.append("CONTENT_ENCRYPTION_KEY_ATIVA")
    if hoje - data_do_id(settings.lead_indice_chave_id) > VALIDADE:
        vencidas.append("LEAD_INDICE_CHAVE_ID")
    return vencidas


def avisar_rotacao_vencida(settings: Settings, hoje: date | None = None) -> None:
    """So em producao: em desenvolvimento a chave default nunca roda, e o aviso seria ruido."""
    if not settings.em_producao:
        return
    for nome in chaves_vencidas(settings, hoje or datetime.now(UTC).date()):
        log.warning("seguranca.rotacao_vencida", chave=nome, validade_dias=VALIDADE.days)
