"""TEC-203, D1: chave com mais de 90 dias gera aviso, e nunca derruba a subida."""

import base64
import logging
import os
from datetime import date

import pytest

from mobia.app.config import Settings
from mobia.infra.rotacao import avisar_rotacao_vencida, chaves_vencidas


def _keyring(ativa: str) -> dict[str, object]:
    return {
        "content_encryption_keys": {ativa: base64.b64encode(os.urandom(32)).decode()},
        "content_encryption_key_ativa": ativa,
    }


def test_chaves_novas_nao_vencem():
    settings = Settings(**_keyring("20260901"), lead_indice_chave_id="20260901")
    assert chaves_vencidas(settings, date(2026, 11, 30)) == []


def test_chave_de_conteudo_com_91_dias_vence():
    settings = Settings(**_keyring("20260601"), lead_indice_chave_id="20260926")
    assert chaves_vencidas(settings, date(2026, 8, 31)) == ["CONTENT_ENCRYPTION_KEY_ATIVA"]


def test_chave_de_indice_vence_pelo_proprio_id():
    settings = Settings(lead_indice_chave_id="20260101")
    assert chaves_vencidas(settings, date(2026, 9, 26)) == ["LEAD_INDICE_CHAVE_ID"]


def test_keyring_vazio_nao_tem_idade_para_vencer():
    assert "CONTENT_ENCRYPTION_KEY_ATIVA" not in chaves_vencidas(Settings(), date(2030, 1, 1))


def test_avisa_em_producao_com_chave_de_indice_vencida(
    segredos_de_producao: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LEAD_INDICE_CHAVE_ID", "20260101")
    settings = Settings()
    with caplog.at_level(logging.WARNING):
        avisar_rotacao_vencida(settings, date(2026, 9, 26))
    assert "seguranca.rotacao_vencida" in caplog.text


def test_fica_silencioso_fora_de_producao(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(lead_indice_chave_id="20260101")
    with caplog.at_level(logging.WARNING):
        avisar_rotacao_vencida(settings, date(2026, 9, 26))
    assert "seguranca.rotacao_vencida" not in caplog.text
