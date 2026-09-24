"""O vocabulario de `messages.channel` (TEC-124)."""

import inspect

from mobia.domain.messages.canais import (
    CANAIS_COM_REENGAJAMENTO,
    CANAL_WEB,
    CANAL_WHATSAPP,
)
from mobia.domain.messages.service import IngestionService


def test_os_dois_canais_sao_minusculos() -> None:
    # A coluna esta povoada com `whatsapp` desde a TEC-122. Um valor
    # maiusculo ao lado faria consulta por canal depender de caixa.
    assert CANAL_WHATSAPP == "whatsapp"
    assert CANAL_WEB == "web"


def test_o_reengajamento_e_allowlist_e_nao_alcanca_o_web() -> None:
    # Allowlist e nao `!= CANAL_WEB`: canal novo nasce de fora.
    assert CANAIS_COM_REENGAJAMENTO == (CANAL_WHATSAPP,)
    assert CANAL_WEB not in CANAIS_COM_REENGAJAMENTO


def test_o_default_da_ingestao_e_a_constante_e_nao_um_literal_solto() -> None:
    assinatura = inspect.signature(IngestionService.ingest)
    assert assinatura.parameters["channel"].default == CANAL_WHATSAPP
