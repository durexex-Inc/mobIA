"""As quatro rotas de autenticacao do dashboard. TEC-201, RNF-11.

`login`, `mfa`, `refresh` e `logout`. A checagem de papel por rota e a TEC-202
e nao esta aqui -- o JWT CARREGA o papel, e ninguem ainda o exige alem do
`ADMIN` que `exigir_admin` confere.

**Estas rotas nao sao guardadas por `exigir_admin`**, obviamente: sao elas que
produzem a credencial que ele valida. `refresh` e `logout` se autenticam pelo
proprio refresh token apresentado.
"""

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mobia.app.config import get_settings
from mobia.domain.usuarios import repositorio, senha, sessoes, tokens, totp
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Quanto tempo o desafio de MFA vale (D5).
#
# Curto de proposito: ele e uma credencial de meio caminho -- prova que a senha
# estava certa e ainda nao prova o segundo fator. Cinco minutos dao folga para
# abrir o aplicativo e digitar, sem deixar um desafio roubado util por muito
# tempo.
MINUTOS_DO_DESAFIO = 5

# A recusa e SEMPRE esta, com este texto, para senha errada, usuario
# inexistente e usuario desativado.
#
# **Distinguir os tres contaria a quem sonda qual deles ele acertou** -- e o
# primeiro passo de enumerar usuarios e de saber que vale a pena insistir num
# e-mail. O log distingue; a resposta nao.
_CREDENCIAL_INVALIDA = "credencial_invalida"


class PedidoDeLogin(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    senha: str = Field(min_length=1, max_length=256)


class PedidoDeMfa(BaseModel):
    desafio: str = Field(min_length=1)
    codigo: str = Field(min_length=6, max_length=6)


class PedidoComRefresh(BaseModel):
    refresh: str = Field(min_length=1)


def _recusar() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CREDENCIAL_INVALIDA)


@router.post("/login")
async def login(pedido: PedidoDeLogin) -> dict[str, object]:
    """Senha correta devolve o par de tokens -- ou um desafio, se houver MFA.

    **O ADMIN com MFA nao recebe tokens aqui.** Ele recebe `mfa_requerido` e um
    desafio; so `POST /auth/mfa` emite o par. E a D5: a regra vale no login, e
    nao espalhada por rota.

    **ADMIN sem `mfa_habilitado` nao entra.** Nao e lacuna, e a RNF-11 -- e por
    isso nao ha ramo que o deixe passar. Ver a lacuna L2 do desenho: nao ha
    rota que habilite TOTP nesta card, entao o primeiro ADMIN precisa nascer
    com a semente gravada.
    """
    settings = get_settings()

    async with get_sessionmaker()() as session:
        usuario = await repositorio.por_email(session, pedido.email)

        # **A senha e conferida mesmo sem usuario**, contra um hash descartavel,
        # para que o tempo da resposta nao revele se o e-mail existe. Sem isto,
        # um e-mail inexistente responde na hora e um existente demora o Argon2
        # inteiro -- que e um oraculo de enumeracao medindo o relogio.
        hash_para_conferir = (
            usuario.senha_hash if usuario is not None else senha.gerar_hash("descartavel")
        )
        if not senha.confere(pedido.senha, hash_para_conferir) or usuario is None:
            log.warning("auth.login_recusado", email=pedido.email)
            raise _recusar()

        if usuario.papel == "ADMIN":
            if not usuario.mfa_habilitado:
                # Falha ALTA e com motivo proprio: e configuracao incompleta,
                # nao credencial errada, e quem administra precisa distinguir
                # as duas ao ler o log.
                log.error("auth.admin_sem_mfa", usuario_id=str(usuario.id))
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="administradores precisam de MFA habilitado",
                )
            desafio = tokens.emitir_desafio(
                usuario.id, usuario.papel, minutos=MINUTOS_DO_DESAFIO, settings=settings
            )
            return {"mfa_requerido": True, "desafio": desafio}

        emitido = await sessoes.emitir(session, usuario_id=usuario.id, settings=settings)
        await session.commit()

    return {
        "access": tokens.emitir(usuario.id, usuario.papel, mfa=False, settings=settings),
        "refresh": emitido.token,
    }


@router.post("/mfa")
async def confirmar_mfa(pedido: PedidoDeMfa) -> dict[str, object]:
    """Troca o desafio mais o codigo TOTP pelo par de tokens."""
    settings = get_settings()

    try:
        identidade = tokens.validar(pedido.desafio, settings)
    except tokens.TokenInvalido as falha:
        log.warning("auth.desafio_invalido", motivo=str(falha))
        raise _recusar() from falha

    # Um token com `mfa: True` ja passou pelo segundo fator -- aceita-lo aqui
    # deixaria um token de ACESSO ser trocado por outro par, indefinidamente,
    # sem senha.
    if identidade.mfa:
        raise _recusar()

    async with get_sessionmaker()() as session:
        usuario = await repositorio.por_id(session, identidade.usuario_id)
        if usuario is None or not totp.confere_codigo(
            usuario.totp_segredo, usuario.id, pedido.codigo
        ):
            log.warning("auth.mfa_recusado", usuario_id=str(identidade.usuario_id))
            raise _recusar()

        emitido = await sessoes.emitir(session, usuario_id=usuario.id, settings=settings)
        await session.commit()
        papel = usuario.papel
        usuario_id = usuario.id

    return {
        "access": tokens.emitir(usuario_id, papel, mfa=True, settings=settings),
        "refresh": emitido.token,
    }


@router.post("/refresh")
async def renovar(pedido: PedidoComRefresh) -> dict[str, object]:
    """Renova sem novo login, dentro dos 7 dias (terceiro cenario do Gherkin).

    O refresh e ROTATIVO: o apresentado morre e um novo nasce. Reapresentar um
    ja usado derruba a familia inteira -- ver `sessoes.consumir`.

    **O `mfa` do token novo herda o do usuario, e nao o da sessao anterior.**
    Um ADMIN so chega a ter refresh depois de passar pelo segundo fator, entao
    herdar `mfa_habilitado` diz a verdade sem guardar estado a mais.
    """
    settings = get_settings()

    async with get_sessionmaker()() as session:
        try:
            usuario_id, novo = await sessoes.consumir(session, pedido.refresh, settings=settings)
        except sessoes.RefreshInvalido as falha:
            # O commit acontece MESMO na recusa por reuso: a revogacao da
            # familia e efeito que precisa persistir, e um rollback aqui a
            # desfaria, deixando o ladrao com a corrente viva.
            await session.commit()
            log.warning("auth.refresh_recusado", motivo=str(falha))
            raise _recusar() from falha

        usuario = await repositorio.por_id(session, usuario_id)
        if usuario is None:
            # Desativado entre o login e agora. A renovacao e o ponto em que
            # isso passa a valer (ver `repositorio.por_id`).
            await session.rollback()
            raise _recusar()

        await session.commit()
        papel = usuario.papel
        mfa = usuario.mfa_habilitado

    return {
        "access": tokens.emitir(usuario_id, papel, mfa=mfa, settings=settings),
        "refresh": novo.token,
    }


@router.post("/logout")
async def sair(pedido: PedidoComRefresh) -> dict[str, object]:
    """Revoga a familia do refresh apresentado (quinto cenario do Gherkin).

    **Responde 200 mesmo para um refresh que nao existe.** Logout nao deve
    contar a ninguem se um token era valido, e um cliente que perdeu a sessao
    tem de conseguir "sair" sem receber erro.

    **Revoga a FAMILIA, nao a linha.** Revogar so a linha apresentada deixaria
    viva a corrente que a precedeu -- e e a corrente inteira que representa
    aquela sessao. Nao alcanca outros navegadores da mesma pessoa: e a lacuna
    L4, e e o que o Gherkin descreve.
    """
    async with get_sessionmaker()() as session:
        if await sessoes.revogar_por_token(session, pedido.refresh):
            await session.commit()

    return {"ok": True}
