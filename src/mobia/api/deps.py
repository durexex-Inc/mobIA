import secrets
from typing import Annotated

import structlog
from fastapi import Header, HTTPException, status
from starlette.requests import HTTPConnection

from mobia.app.config import get_settings
from mobia.domain.messages.service import IngestionService
from mobia.domain.usuarios.tokens import TokenInvalido, validar
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)


def get_ingestion_service(conexao: HTTPConnection) -> IngestionService:
    """O mesmo servico para o webhook e para o widget.

    `HTTPConnection` e nao `Request` desde a TEC-124: e a base comum de
    `Request` e `WebSocket`, e o FastAPI so injeta `Request` em escopo `http`.
    Com `Request` aqui, a rota do widget falhava na resolucao da dependencia,
    antes de aceitar a conexao.
    """
    return IngestionService(get_sessionmaker(), getattr(conexao.app.state, "redis_pool", None))


def _jwt_de_admin(authorization: str) -> bool:
    """Se o header `Authorization` traz um JWT valido de ADMIN. TEC-201.

    Devolve False -- e nao levanta -- para tudo que nao for isso: formato
    errado, assinatura invalida, expirado, ou papel diferente. Quem decide o
    desfecho e `exigir_admin`, que ainda tem o caminho do token compartilhado
    para tentar depois (D2 do desenho).
    """
    prefixo = "Bearer "
    if not authorization.startswith(prefixo):
        return False
    try:
        identidade = validar(authorization[len(prefixo) :], get_settings())
    except TokenInvalido as falha:
        log.warning("auth.jwt_recusado", motivo=str(falha))
        return False
    return identidade.papel == "ADMIN"


def exigir_admin(
    x_admin_token: Annotated[str, Header()] = "",
    authorization: Annotated[str, Header()] = "",
) -> None:
    """A guarda das rotas administrativas: JWT de ADMIN **ou** o token compartilhado.

    **Os dois convivem de proposito, e isso e sequenciamento (TEC-201, D2).**
    Trocar so pelo JWT quebraria o painel hoje: o BFF do frontend manda
    `X-Admin-Token` (`lib/servidor/api.ts`), e quem o faz mandar sessao de
    verdade e a TEC-309 -- que esta card destrava e que portanto ainda nao
    existe. A propria TEC-309 pressupoe a convivencia, ao exigir que nao chegue
    ao navegador "nenhum token de acesso, de renovacao ou o token
    administrativo provisorio".

    **O risco fica dito: enquanto os dois convivem, a seguranca do conjunto e a
    do elo mais fraco.** Quem tiver o token compartilhado entra sem usuario,
    sem papel e sem MFA. Esta card constroi o caminho para fechar isso; quem
    fecha e a TEC-309, apagando o ramo de baixo e esta funcao inteira com ele.

    O `warning` por uso do token antigo existe para que a remocao seja feita
    com EVIDENCIA -- da para medir quando ele parou de ser usado, em vez de
    apagar por fe.

    O texto abaixo e da TEC-156 e continua valendo para o ramo do token:

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
    if _jwt_de_admin(authorization):
        return

    esperado = get_settings().catalogo_admin_token
    # `not esperado` curto-circuita antes do compare_digest quando o token nao
    # esta configurado. Em producao isso nunca dispara sozinho -- main.py so
    # registra este router quando `catalogo_admin_token` e verdadeiro --, mas
    # a funcao roda isolada em teste, e sem esta clausula um token vazio
    # comparado contra um vazio recusado passaria como "correto".
    if not esperado or not secrets.compare_digest(
        x_admin_token.encode("utf-8"), esperado.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    # So chega aqui quem passou pelo token COMPARTILHADO -- o ramo do JWT
    # retornou la em cima. Ver a D2: este aviso e o instrumento que permite
    # apagar o token antigo com evidencia.
    log.warning("auth.token_compartilhado_usado")
