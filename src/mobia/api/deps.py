import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from mobia.app.config import get_settings
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker


def get_ingestion_service(request: Request) -> IngestionService:
    return IngestionService(get_sessionmaker(), getattr(request.app.state, "redis_pool", None))


def exigir_admin(x_admin_token: Annotated[str, Header()] = "") -> None:
    """A autenticacao provisoria do endpoint administrativo (TEC-156, D1).

    `compare_digest` e nao `==`: comparacao de string curto-circuita no
    primeiro byte diferente, e o tempo da resposta revela o prefixo correto.

    Comparado em bytes, nao nas strings recebidas: `compare_digest` exige que
    os dois lados sejam ASCII quando sao `str`, e recusa com `TypeError`
    quando nao sao -- um cliente mandando `X-Admin-Token` com acento ou emoji
    viraria 500 (erro do servidor) em vez de 403 (token errado). Codificar
    para UTF-8 antes de comparar tira essa exigencia do caminho: bytes aceita
    qualquer conteudo.

    Quando a TEC-201 chegar, o corpo desta funcao vira validacao de JWT mais
    papel ADMIN e nenhum handler muda -- e esse o ponto de ter uma funcao aqui
    em vez de um `if` dentro da rota.
    """
    esperado = get_settings().catalogo_admin_token
    if not esperado or not secrets.compare_digest(
        x_admin_token.encode("utf-8"), esperado.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
