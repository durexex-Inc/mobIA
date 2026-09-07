"""A guarda da chave ausente, e o lote vazio.

Nenhuma chamada de rede: os testes que exercitam o cliente de verdade nao
existem, de proposito. Uma suite de 22 minutos nao pode passar a depender de
provedor externo -- seria flake por rede, nao sinal.
"""

import pytest

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.infra import embeddings


def test_sem_chave_o_cliente_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    # `setenv` com string vazia, e nao `delenv`: variavel de ambiente vence o
    # `.env` no pydantic-settings, e string vazia e falsy. Com `delenv`, uma
    # chave presente no `.env` de quem executa faria o teste falhar por
    # ambiente.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    embeddings.get_client.cache_clear()

    with pytest.raises(ConfiguracaoInsegura) as erro:
        embeddings.get_client()

    assert "OPENAI_API_KEY" in str(erro.value)


async def test_lote_vazio_nao_chama_o_provedor(monkeypatch: pytest.MonkeyPatch) -> None:
    # Se `embedar([])` chamasse o provedor, a guarda da chave levantaria --
    # entao passar sem chave configurada E a assercao.
    # `setenv` com string vazia, e nao `delenv`: variavel de ambiente vence o
    # `.env` no pydantic-settings, e string vazia e falsy. Com `delenv`, uma
    # chave presente no `.env` de quem executa faria o teste falhar por
    # ambiente.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    embeddings.get_client.cache_clear()

    assert await embeddings.embedar([]) == []


def test_o_timeout_do_cliente_cabe_no_job_timeout() -> None:
    # Mesmo raciocinio do comentario em `infra/anthropic.py`: o teto por
    # chamada tem de ser estritamente menor que o `job_timeout` do worker,
    # senao uma chamada lenta nao falha -- e cancelada pelo ARQ.
    pior_caso = embeddings.TIMEOUT_SEGUNDOS * (embeddings.MAX_TENTATIVAS + 1)
    lotes_por_passagem = 2

    assert pior_caso * lotes_por_passagem < 240
