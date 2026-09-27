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

import uuid
from dataclasses import dataclass

import structlog
from fastapi import Header, HTTPException, Request, status

from mobia.api.middleware import origem_da_requisicao
from mobia.app.config import get_settings
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import (
    Acao,
    Ator,
    AtorTipo,
    Entidade,
    detalhes_da_negativa,
)
from mobia.domain.usuarios.permissoes import Permissao, permissoes_de
from mobia.domain.usuarios.tokens import TokenInvalido, validar
from mobia.infra.db import get_sessionmaker

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
    "/widget/aparencia/{slug}": (
        "cor, lado e nome do botao do chat do site; quem pede e o loader, antes "
        "de qualquer visitante se identificar (TEC-344)"
    ),
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

# O texto que `para_log`/`como_ator` devolvem quando `usuario_id` e nulo.
#
# Nenhum construtor produz mais essa identidade: so o JWT resolve identidade
# desde que a TEC-382 apagou `_do_token_compartilhado`, e o `sub` dele e claim
# obrigatoria (`domain/usuarios/tokens.py`) -- o ramo de `usuario_id` nulo fica
# vestigial em `para_log`/`como_ator`, e a razao de ele continuar la e a mesma
# que `ExigeSessao.__call__` explica: o campo segue tipado `uuid.UUID | None`.
#
# Nao e um UUID de verdade porque nao havia usuario nenhum por tras do token
# compartilhado que produzia este valor: a constante existia para que o log
# dissesse isso em vez de inventar um id. Os EVENTOS GRAVADOS ENTAO continuam
# com este texto exato em `ator_id`, e uma consulta por ele e possivel (`ator`
# em `domain/auditoria/consulta.py` e texto exato, nao UUID) -- mas nada neste
# modulo dispara essa consulta; ela e responsabilidade de quem le a trilha.
SEM_USUARIO = "token-compartilhado"


@dataclass(frozen=True)
class IdentidadeDaRequisicao:
    """Quem chamou, resolvido por JWT -- o unico caminho aceito desde a TEC-382.

    **Ate aqui havia um segundo caminho**, o header `X-Admin-Token`, que a
    Emenda E-01 da RN-19.5 introduziu em 12/09/2026 -- "enquanto a TEC-201 nao
    existir, o papel ADMIN e o header X-Admin-Token". A TEC-201 chegou e nao o
    apagou, por sequenciamento (Emenda E-02 a RNF-11): ele resolvia para um
    ADMIN sem usuario e passava em TODA permissao da matriz. A TEC-309 tirou o
    painel desse caminho sem apaga-lo do FastAPI (Emenda E-03 a RNF-11); a
    TEC-382 apaga o ramo em si (Emenda E-04 a RNF-11).

    `usuario_id` continua nulavel no tipo, mas nao ha mais construtor nenhum
    que passe `None` -- `para_log` e `como_ator` tratam esse ramo como
    vestigial, e nao como caminho vivo.
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
        """O identificador que vai para o log. Nunca o token.

        So devolve `SEM_USUARIO` para uma identidade com `usuario_id` nulo --
        o que o JWT nunca produz (`sub` e claim obrigatoria em
        `domain/usuarios/tokens.py`). Ninguem mais constroi essa identidade
        desde a TEC-382; o ramo fica porque `usuario_id` continua tipado
        nulavel.
        """
        return str(self.usuario_id) if self.usuario_id is not None else SEM_USUARIO

    def como_ator(self) -> Ator:
        """Quem chamou, como ator da trilha de auditoria (TEC-206).

        Sempre USUARIO, com o mesmo identificador do log: o `usuario_id`, ou
        `SEM_USUARIO` se ele for nulo -- ramo vestigial, pela mesma razao de
        `para_log`.
        """
        return Ator(AtorTipo.USUARIO, self.para_log())


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
    `Exige`, que ate a TEC-382 ainda tinha o caminho do token compartilhado
    para tentar depois (D2 da TEC-201, que esta funcao herda de
    `_jwt_de_admin`); agora um `None` daqui e identidade nenhuma, ponto final.
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


def identidade_da_requisicao(authorization: str = "") -> IdentidadeDaRequisicao | None:
    """Quem chamou -- so pelo JWT, desde a TEC-382.

    Ate aqui havia um segundo argumento, `x_admin_token`, resolvido por
    `_do_token_compartilhado` (TEC-156, TEC-201). O painel ja tinha parado de
    manda-lo na TEC-309; esta funcao para de aceita-lo (Emenda E-04 a RNF-11).
    """
    return _do_jwt(authorization)


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
        authorization: str = Header(default=""),
    ) -> IdentidadeDaRequisicao:
        identidade = identidade_da_requisicao(authorization)

        if identidade is None:
            # Sem identidade nenhuma nao ha papel a registrar, e o evento sai
            # com `papel=None` em vez de com um papel inventado: "ninguem
            # provou quem e" e um fato diferente de "provou e nao pode". E nao
            # vai para a trilha (TEC-206, D7): ver `registrar_negativa`.
            await registrar_negativa(request, self.permissao, identidade=None)
            raise _negar()

        if not identidade.pode(self.permissao):
            await registrar_negativa(request, self.permissao, identidade=identidade)
            raise _negar()

        return identidade


class ExigeSessao:
    """Exige um usuario de verdade, de qualquer papel. TEC-202, D7.

    **A checagem de `identidade.usuario_id is None` abaixo ficou vestigial
    com a TEC-382.** Ate ela, era o que recusava o token compartilhado aqui --
    e so aqui, a unica guarda deste sistema de que isso valia: ele resolvia
    para um ADMIN sem usuario, e uma rota que responde "quem sou eu" nao tem o
    que responder a quem nao e ninguem. Sem `_do_token_compartilhado`, so o
    JWT chega a este ponto, e o `sub` dele e claim obrigatoria
    (`domain/usuarios/tokens.py`) -- `usuario_id` nunca mais e `None` na
    pratica. A linha fica porque `IdentidadeDaRequisicao.usuario_id` continua
    tipado como nulavel.

    Guarda o `GET /auth/me`, e so ele. Permissao nenhuma e exigida de
    proposito: a rota nao da acesso a dado nenhum alem do que o proprio token
    de quem chama ja carrega.
    """

    async def __call__(
        self,
        request: Request,
        authorization: str = Header(default=""),
    ) -> IdentidadeDaRequisicao:
        identidade = identidade_da_requisicao(authorization)
        if identidade is None or identidade.usuario_id is None:
            await registrar_negativa(request, None, identidade=identidade, motivo="sem_sessao")
            raise _negar()
        return identidade


# Instancia unica, ao contrario do `Exige`, que e construido na assinatura da
# rota com a permissao dela. Aqui nao ha argumento nenhum que a assinatura
# precise mostrar, entao a constante nao afasta informacao de lugar nenhum --
# e dispensa mais uma entrada no `extend-immutable-calls` do `pyproject.toml`.
EXIGE_SESSAO = ExigeSessao()


def _template_da_rota(request: Request) -> str:
    """A rota como foi declarada (`/api/v1/handoffs/{handoff_id}/aceitar`).

    O FastAPI poe a rota resolvida em `request.scope["route"]` antes de rodar
    as dependencias. Sem ela -- nao acontece nas rotas guardadas, mas o custo
    de nao quebrar e uma linha --, cai para o caminho cru, no teto da coluna.
    """
    caminho = getattr(request.scope.get("route"), "path", None)
    if isinstance(caminho, str):
        return caminho
    return request.url.path[:200]


async def registrar_negativa(
    request: Request,
    permissao: Permissao | None,
    *,
    identidade: IdentidadeDaRequisicao | None,
    motivo: str = "sem_permissao",
) -> None:
    """A tentativa negada, registrada. TEC-202, D6; TEC-206, D7.

    **Sempre no log; na trilha, so quando ha identidade.** O log
    `autorizacao.negada` sai em toda negativa, com o formato da TEC-202. A
    linha em `eventos_auditoria` sai so quando `identidade` foi resolvida.
    A negativa sem credencial continua so em log, e o argumento e o que o
    docstring de `RateLimitEvent` escreve: "escrever uma linha por requisicao
    transformaria o registro de abuso no proprio vetor de abuso". Negacao sem
    credencial e o que um varredor de endpoints produz EM RAJADA, e cada 403
    viraria uma escrita no Postgres do defensor. Com identidade, quem produz a
    negativa e alguem identificavel -- e e esse o registro que a TEC-343 pede.

    **A escrita commita antes de o 403 sair**, numa sessao curta propria: nao
    ha transacao de negocio a que ela se juntar. Se o banco falhar, a resposta
    e erro, e nao um 403 sem registro.

    **Nunca o token e nunca o corpo** -- so quem, o que foi exigido e onde. Na
    trilha, "onde" e o template da rota, e nao o caminho com o id.

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
    if identidade is None:
        return
    async with get_sessionmaker()() as session:
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.ACESSO_NEGADO,
            entidade=Entidade.ROTA,
            entidade_id=_template_da_rota(request),
            detalhes=detalhes_da_negativa(
                permissao=permissao.value if permissao is not None else None,
                motivo=motivo,
                papel=identidade.papel,
                metodo=request.method,
            ),
            origem=origem_da_requisicao(request),
        )
        await session.commit()


async def exigir_dono(
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
    terceiro e a funcao (Emenda E-05 a RN-16.4).

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
    await registrar_negativa(
        request, permissao, identidade=identidade, motivo="corretor_nao_e_o_dono"
    )
    raise _negar()
