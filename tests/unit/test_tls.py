"""TEC-203, D6: TLS 1.3 com verificacao de certificado em producao; nada muda fora dela."""

import ssl

import pytest

from mobia.app.config import ConfiguracaoInsegura, Settings, get_settings
from mobia.infra.queue import redis_settings
from mobia.infra.tls import argumentos_de_conexao_do_banco, contexto_tls, exigir_redis_com_tls


def test_contexto_exige_tls_13_e_verifica_certificado():
    contexto = contexto_tls()
    assert contexto.minimum_version == ssl.TLSVersion.TLSv1_3
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True


def test_fora_de_producao_o_banco_conecta_sem_tls():
    assert argumentos_de_conexao_do_banco(Settings()) == {}


def test_em_producao_o_banco_recebe_o_contexto(monkeypatch, segredos_de_producao):
    monkeypatch.setenv("ENVIRONMENT", "production")
    argumentos = argumentos_de_conexao_do_banco(Settings())
    assert isinstance(argumentos["ssl"], ssl.SSLContext)


def test_redis_sem_tls_reprova():
    with pytest.raises(ConfiguracaoInsegura, match="rediss://"):
        exigir_redis_com_tls("redis://cache:6379/0")


def test_redis_com_tls_passa():
    exigir_redis_com_tls("rediss://cache:6379/0")


def test_em_producao_redis_settings_exige_rediss_e_verifica_certificado(
    monkeypatch, segredos_de_producao
):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REDIS_URL", "rediss://cache:6380/0")
    get_settings.cache_clear()
    try:
        settings = redis_settings()
    finally:
        get_settings.cache_clear()

    assert settings.ssl is True
    assert settings.ssl_cert_reqs == "required"
    assert settings.ssl_check_hostname is True


def test_em_producao_redis_settings_reprova_sem_rediss(monkeypatch, segredos_de_producao):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6380/0")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfiguracaoInsegura, match="rediss://"):
            redis_settings()
    finally:
        get_settings.cache_clear()
