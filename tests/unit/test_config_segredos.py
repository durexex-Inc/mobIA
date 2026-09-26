"""TEC-203, D5: em producao o `.env` nao e lido, e segredo vem de env ou arquivo montado."""

import pytest

from mobia.app.config import ConfiguracaoInsegura, get_settings


@pytest.fixture
def em_diretorio_com_env(tmp_path, monkeypatch):
    """`get_settings` e `@lru_cache`: sem limpar, o `app = create_app()` de
    `main.py` (importado por `tests/conftest.py`) ja preencheu o cache com a
    `Settings` do `.env` real do repo antes do primeiro teste rodar, e nenhum
    `monkeypatch` deste arquivo teria efeito nenhum sobre o valor lido.
    """
    monkeypatch.chdir(tmp_path)
    for nome in ("ENVIRONMENT", "JWT_SEGREDO", "MOBIA_SECRETS_DIR"):
        monkeypatch.delenv(nome, raising=False)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_fora_de_producao_o_env_continua_valendo(em_diretorio_com_env):
    (em_diretorio_com_env / ".env").write_text("WHATSAPP_VERIFY_TOKEN=do-arquivo\n")
    assert get_settings().whatsapp_verify_token == "do-arquivo"


def test_em_producao_o_env_nao_e_lido(em_diretorio_com_env, monkeypatch, segredos_de_producao):
    (em_diretorio_com_env / ".env").write_text("WHATSAPP_VERIFY_TOKEN=do-arquivo\n")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert get_settings().whatsapp_verify_token != "do-arquivo"


def test_ambiente_de_producao_vindo_do_arquivo_reprova(em_diretorio_com_env):
    (em_diretorio_com_env / ".env").write_text("ENVIRONMENT=production\n")
    with pytest.raises(ConfiguracaoInsegura, match="ENVIRONMENT"):
        get_settings()


def test_segredo_de_arquivo_montado(em_diretorio_com_env, monkeypatch):
    montados = em_diretorio_com_env / "segredos"
    montados.mkdir()
    (montados / "whatsapp_verify_token").write_text("montado")
    monkeypatch.setenv("MOBIA_SECRETS_DIR", str(montados))
    assert get_settings().whatsapp_verify_token == "montado"
