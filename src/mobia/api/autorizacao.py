"""Quem esta chamando, e se pode. TEC-202, RNF-12.

Este modulo tem tres coisas: a identidade da requisicao (`IdentidadeDaRequisicao`),
a guarda que as rotas penduram na assinatura (`Exige`) e a lista das rotas que
nao tem guarda nenhuma (`ROTAS_PUBLICAS`), cada uma com a razao escrita.

**A guarda e dependencia por rota, e nao middleware** (D3 do desenho). O
precedente do repo seria o contrario -- o `RateLimitPorIP` da TEC-205 e
middleware justamente para nao depender de alguem lembrar de incluir a rota
nova --, e a razao de divergir e mecanica: o Starlette resolve QUAL rota atende
a requisicao dentro do router, depois de toda a pilha de middleware. Um
middleware que quisesse saber qual permissao a rota exige teria de reimplementar
a correspondencia de caminho (inclusive `/{corretor_id}` e `/{handoff_id}`) em
paralelo ao FastAPI, e duas implementacoes de roteamento divergem em silencio.

Quem cobre o "esqueci a rota nova" e `test_toda_rota_declara_autorizacao`, que
varre `app.routes` e exige de cada uma ou um `Exige`, ou presenca na
`ROTAS_PUBLICAS`. E protecao de CI e nao de runtime, e a diferenca fica dita:
o que ela garante e que nenhuma rota chega a `main` sem alguem ter decidido,
por escrito, quem pode chama-la.
"""

import secrets
import uuid
from dataclasses import dataclass

import structlog
from fastapi import Header, HTTPException, Request, status

from mobia.app.config import get_settings
from mobia.domain.usuarios.permissoes import Permissao, permissoes_de
from mobia.domain.usuarios.tokens import TokenInvalido, validar

log = structlog.get_logger(__name__)

# As rotas sem guarda, e por que cada uma.
#
# Ela e lida por `test_toda_rota_declara_autorizacao`, e nao pelo runtime --
# nada neste modulo consulta esta lista para deixar alguem passar. Uma rota so
# fica publica por NAO declarar `Exige`; esta lista e onde essa ausencia deixa
# de ser esquecimento e vira decisao.
ROTAS_PUBLICAS: dict[str, str] = {
    "/health": "probe de liveness; um 403 aqui derrubaria o processo",
    "/webhooks/whatsapp": "quem chama e a Meta, autenticada por assinatura HMAC (RNF-15)",
    "/widget/chat": "o chat do site; quem o abre e visitante anonima (TEC-124)",
    "/api/v1/auth/login": "produz a credencial que esta guarda valida",
    "/api/v1/auth/mfa": "idem -- troca o desafio pelo par de tokens",
    "/api/v1/auth/refresh": "autentica-se pelo proprio refresh apresentado",
    "/api/v1/auth/logout": "idem; e responde 200 ate para refresh que nao existe",
    # **Nao porque alguem decidiu que devem ser publicas** (L6 do desenho).
    # Sao rotas que o FastAPI registra sozinho e que descrevem a API inteira a
    # quem pedir. Desliga-las e decisao de outra card -- escondidas aqui, elas
    # sairiam da vista de quem for decidir.
    "/openapi.json": "esquema publico; desligar e decisao de outra card (L6)",
    "/docs": "idem",
    "/docs/oauth2-redirect": "idem",
    "/redoc": "idem",
}

# O que o ramo do token compartilhado produz no lugar de um usuario.
#
# Nao e um UUID de verdade porque nao ha usuario nenhum por tras dele: quem
# usa o token compartilhado nao tem identidade, e esta constante existe para
# que o log diga isso em vez de inventar um id.
SEM_USUARIO = "token-compartilhado"


@dataclass(frozen=True)
class IdentidadeDaRequisicao:
    """Quem chamou, ja resolvido -- por JWT ou pelo token compartilhado.

    **O token compartilhado resolve para um ADMIN sem usuario** (D2 do
    desenho). Nao e concessao preguicosa: e o que a Emenda E-01 da RN-19.5 ja
    escreveu em 12/09/2026 -- "enquanto a TEC-201 nao existir, o papel ADMIN e
    o header X-Admin-Token". A TEC-201 chegou e nao o apagou, por sequenciamento;
    quem o apaga e a TEC-309, que faz o BFF mandar sessao de verdade.

    **A consequencia, dita:** quem tem o token compartilhado passa em TODA
    permissao da matriz, inclusive nas que so o ADMIN tem. A autorizacao por
    papel so vale de verdade para quem entra por JWT.
    """

    papel: str
    usuario_id: uuid.UUID | None
    corretor_id: uuid.UUID | None

    @property
    def e_corretor(self) -> bool:
        """Se as regras de dono se aplicam a quem chamou.

        So o papel CORRETOR e limitado ao proprio: para ADMIN e GERENTE, agir
        em nome de terceiro e a funcao (Emenda E-05 a RN-16.4).
        """
        return self.papel == "CORRETOR"

    def pode(self, permissao: Permissao) -> bool:
        return permissao in permissoes_de(self.papel)

    def para_log(self) -> str:
        """O identificador que vai para o log. Nunca o token."""
        return str(self.usuario_id) if self.usuario_id is not None else SEM_USUARIO


def _negar() -> HTTPException:
    """Sempre 403, e sempre com este detalhe.

    **Um texto so para "nao autenticado" e "autenticado sem permissao".** A
    distincao interessa ao log, que a registra; na resposta, ela contaria a
    quem sonda se o token que ele tem vale alguma coisa. Mesma regra do
    `_CREDENCIAL_INVALIDA` de `routes/auth.py`.

    403 e nao 401 tambem por compatibilidade deliberada: e o que `exigir_admin`
    respondia desde a TEC-156, e o painel de hoje ja o trata.
    """
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _do_jwt(authorization: str) -> IdentidadeDaRequisicao | None:
    """A identidade que o header `Authorization` carrega, ou None.

    Devolve None -- e nao levanta -- para tudo que nao for um JWT valido:
    formato errado, assinatura invalida, expirado. Quem decide o desfecho e
    `Exige`, que ainda tem o caminho do token compartilhado para tentar depois
    (D2 da TEC-201, que esta funcao herda de `_jwt_de_admin`).
    """
    prefixo = "Bearer "
    if not authorization.startswith(prefixo):
        return None
    try:
        identidade = validar(authorization[len(prefixo) :], get_settings())
    except TokenInvalido as falha:
        log.warning("auth.jwt_recusado", motivo=str(falha))
        return None
    return IdentidadeDaRequisicao(
        papel=identidade.papel,
        usuario_id=identidade.usuario_id,
        corretor_id=identidade.corretor_id,
    )


def _do_token_compartilhado(x_admin_token: str) -> IdentidadeDaRequisicao | None:
    """O ADMIN sintetico do `X-Admin-Token`, ou None. TEC-201, D2.

    O texto abaixo e da TEC-156 e continua valendo:

    `compare_digest` e nao `==`: comparacao de string curto-circuita no
    primeiro byte diferente, e o tempo da resposta revela o prefixo correto.

    Comparado em bytes, nao nas strings recebidas: `compare_digest` exige que
    os dois lados sejam ASCII quando sao `str`, e recusa com `TypeError`
    quando nao sao -- um cliente mandando `X-Admin-Token` com acento ou emoji
    viraria 500 (erro do servidor) em vez de 403 (token errado). Codificar
    para UTF-8 antes de comparar tira essa exigencia do caminho.

    `not esperado` curto-circuita antes do `compare_digest` quando o token nao
    esta configurado: sem esta clausula, um token vazio comparado contra um
    vazio passaria como "correto". Desde a TEC-201 isso nao e hipotetico --
    `main.py` registra os routers administrativos INCONDICIONALMENTE, entao a
    aplicacao sobe de fato sem `CATALOGO_ADMIN_TOKEN` configurado.
    """
    esperado = get_settings().catalogo_admin_token
    if not esperado or not secrets.compare_digest(
        x_admin_token.encode("utf-8"), esperado.encode("utf-8")
    ):
        return None

    # O `warning` e por USO, nao por requisicao recusada: ele e o instrumento
    # que permite apagar o token antigo com EVIDENCIA, medindo quando ele
    # parou de ser usado em vez de apagar por fe (D2 da TEC-201). Depois da
    # TEC-202 ele importa MAIS, nao menos -- agora este caminho nao contorna
    # so a autenticacao, contorna a matriz inteira.
    log.warning("auth.token_compartilhado_usado")
    return IdentidadeDaRequisicao(papel="ADMIN", usuario_id=None, corretor_id=None)


def identidade_da_requisicao(
    x_admin_token: str = "", authorization: str = ""
) -> IdentidadeDaRequisicao | None:
    """Quem chamou, pelos dois caminhos aceitos hoje, nesta ordem.

    O JWT vem primeiro para que uma requisicao que traga os dois seja atribuida
    a PESSOA, e nao ao token anonimo -- caso real enquanto o painel migra
    (TEC-309) e o unico em que a ordem muda alguma coisa: o que ela decide e o
    que sai no log.
    """
    return _do_jwt(authorization) or _do_token_compartilhado(x_admin_token)


class Exige:
    """A guarda de uma rota: `_: Identificado = Depends(Exige(Permissao.X))`.

    **Classe e nao closure**, por duas razoes. A varredura da D3 precisa
    reconhecer a dependencia e LER qual permissao ela exige -- `isinstance`
    mais um atributo faz isso, e uma funcao interna nao faria sem truque. E
    devolver a identidade permite que o handler continue a conta de autorizacao
    onde ela nao cabe numa permissao: a regra de dono da D5.
    """

    def __init__(self, permissao: Permissao) -> None:
        self.permissao = permissao

    async def __call__(
        self,
        request: Request,
        x_admin_token: str = Header(default=""),
        authorization: str = Header(default=""),
    ) -> IdentidadeDaRequisicao:
        identidade = identidade_da_requisicao(x_admin_token, authorization)

        if identidade is None:
            # Sem identidade nenhuma nao ha papel a registrar, e o evento sai
            # com `papel=None` em vez de com um papel inventado: "ninguem
            # provou quem e" e um fato diferente de "provou e nao pode".
            registrar_negativa(request, self.permissao, identidade=None)
            raise _negar()

        if not identidade.pode(self.permissao):
            registrar_negativa(request, self.permissao, identidade=identidade)
            raise _negar()

        return identidade


class ExigeSessao:
    """Exige um usuario de verdade, de qualquer papel. TEC-202, D7.

    **O token compartilhado NAO serve aqui**, e e a unica guarda deste sistema
    de que isso vale: ele resolve para um ADMIN sem usuario, e uma rota que
    responde "quem sou eu" nao tem o que responder a quem nao e ninguem.
    Inventar um corpo para esse caso seria ensinar o BFF a confiar numa
    identidade que nao existe.

    Guarda o `GET /auth/me`, e so ele. Permissao nenhuma e exigida de
    proposito: a rota nao da acesso a dado nenhum alem do que o proprio token
    de quem chama ja carrega.
    """

    async def __call__(
        self,
        request: Request,
        x_admin_token: str = Header(default=""),
        authorization: str = Header(default=""),
    ) -> IdentidadeDaRequisicao:
        identidade = identidade_da_requisicao(x_admin_token, authorization)
        if identidade is None or identidade.usuario_id is None:
            registrar_negativa(request, None, identidade=identidade, motivo="sem_sessao")
            raise _negar()
        return identidade


# Instancia unica, ao contrario do `Exige`, que e construido na assinatura da
# rota com a permissao dela. Aqui nao ha argumento nenhum que a assinatura
# precise mostrar, entao a constante nao afasta informacao de lugar nenhum --
# e dispensa mais uma entrada no `extend-immutable-calls` do `pyproject.toml`.
EXIGE_SESSAO = ExigeSessao()


def registrar_negativa(
    request: Request,
    permissao: Permissao | None,
    *,
    identidade: IdentidadeDaRequisicao | None,
    motivo: str = "sem_permissao",
) -> None:
    """A tentativa negada, registrada. TEC-202, D6.

    **Vai para o log e nao para uma tabela**, contra o precedente de
    `rate_limit_events` e `moderation_events` -- e pelo argumento que o proprio
    docstring de `RateLimitEvent` escreve: "escrever uma linha por requisicao
    transformaria o registro de abuso no proprio vetor de abuso". Vale aqui com
    menos defesa que la: negacao de autorizacao e o que um varredor de
    endpoints produz EM RAJADA, sem precisar de credencial nenhuma, e cada 403
    viraria uma escrita no Postgres do defensor.

    A trilha imutavel da RNF-18 e a TEC-206, que nao depende desta. Quando ela
    chegar, este evento ganha destino persistente sem mudar de forma.

    **Nunca o token e nunca o corpo** -- so quem, o que foi exigido e onde.

    `permissao` e nula quando o que faltou nao foi permissao, e sim sessao de
    usuario -- e o caso do `ExigeSessao`.
    """
    log.warning(
        "autorizacao.negada",
        motivo=motivo,
        permissao=permissao.value if permissao is not None else None,
        papel=identidade.papel if identidade else None,
        usuario_id=identidade.para_log() if identidade else None,
        metodo=request.method,
        rota=request.url.path,
    )


def exigir_dono(
    request: Request,
    identidade: IdentidadeDaRequisicao,
    *,
    permissao: Permissao,
    corretor_id: uuid.UUID | None,
) -> None:
    """Recusa o CORRETOR que age sobre o que nao e dele. TEC-202, D5.

    Roda DEPOIS de `Exige`, dentro do handler, porque a pergunta depende do
    recurso -- e quem sabe qual e o recurso e a rota, nao a dependencia.

    **So morde o papel CORRETOR.** Para ADMIN e GERENTE, agir em nome de
    terceiro e a funcao (Emenda E-05 a RN-16.4) -- e o token compartilhado,
    que resolve para ADMIN, passa junto.

    **403 e nao 404** (D8): o 404 esconderia a existencia do recurso, e ai a
    tentativa negada -- que a card manda registrar -- se perderia no ruido de
    identificador inexistente. Quem investiga precisa distinguir "sondou um id
    aleatorio" de "tentou o lead do colega". O que vaza e a existencia de um
    UUIDv4 que o atacante teria de adivinhar, e e aceito.

    **`corretor_id` do recurso nulo tambem nega**, e nao e caso de borda: um
    handoff sem destinatario (Emenda E-02 da RN-16.3) nao e de ninguem, e "nao
    e de ninguem" nao quer dizer "e de quem pedir".
    """
    if not identidade.e_corretor:
        return
    if corretor_id is not None and corretor_id == identidade.corretor_id:
        return
    registrar_negativa(request, permissao, identidade=identidade, motivo="corretor_nao_e_o_dono")
    raise _negar()
