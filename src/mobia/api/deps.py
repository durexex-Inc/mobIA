from starlette.requests import HTTPConnection

from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker


def get_ingestion_service(conexao: HTTPConnection) -> IngestionService:
    """O mesmo servico para o webhook e para o widget.

    `HTTPConnection` e nao `Request` desde a TEC-124: e a base comum de
    `Request` e `WebSocket`, e o FastAPI so injeta `Request` em escopo `http`.
    Com `Request` aqui, a rota do widget falhava na resolucao da dependencia,
    antes de aceitar a conexao.
    """
    return IngestionService(get_sessionmaker(), getattr(conexao.app.state, "redis_pool", None))


# **`exigir_admin` saiu daqui na TEC-202.** Ela perguntava uma coisa so -- "e
# ADMIN, ou tem o token compartilhado?" -- e guardava as onze rotas nao
# publicas com a mesma resposta. Agora cada rota declara a PERMISSAO que
# exerce, e quem sabe que papeis a tem e a matriz de
# `domain/usuarios/permissoes.py`.
#
# O ramo do token compartilhado nao morreu: virou
# `_do_token_compartilhado` em `api/autorizacao.py`, com os comentarios da
# TEC-156 e da TEC-201 que ainda valem. O painel parou de manda-lo na TEC-309;
# quem o apaga do FastAPI e a TEC-382.
