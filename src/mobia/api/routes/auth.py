"""As rotas de autenticacao do dashboard. TEC-201 e TEC-202, RNF-11 e RNF-12.

`login`, `mfa`, `refresh` e `logout` produzem e encerram a credencial; `me`
conta a quem ja a tem o que ela vale.

**As quatro primeiras nao sao guardadas por permissao nenhuma**, obviamente:
sao elas que produzem a credencial que a guarda valida. `refresh` e `logout` se
autenticam pelo proprio refresh token apresentado, e estao na `ROTAS_PUBLICAS`
de `api/autorizacao.py` com essa razao escrita.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from mobia.api.autorizacao import EXIGE_SESSAO, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.usuarios import repositorio, senha, sessoes, tokens, totp
from mobia.domain.usuarios.permissoes import permissoes_de
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
    """Senha correta devolve o par de tokens direto, sem exigir MFA do ADMIN.

    **A exigencia de MFA para ADMIN (RNF-11, D5) esta desligada de proposito.**
    `POST /auth/mfa` e `tokens.emitir_desafio` continuam existindo -- um ADMIN
    com `mfa_habilitado` ainda pode completar o desafio se outra rota o
    emitir --, mas o login nao o exige nem o emite mais. Decisao explicita
    para o ambiente de desenvolvimento local, nao lacuna.
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

        emitido = await sessoes.emitir(session, usuario_id=usuario.id, settings=settings)
        await session.commit()
        acesso = tokens.emitir(
            usuario.id,
            usuario.papel,
            mfa=False,
            corretor_id=usuario.corretor_id,
            settings=settings,
        )

    return {"access": acesso, "refresh": emitido.token}


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
        corretor_id = usuario.corretor_id

    return {
        "access": tokens.emitir(
            usuario_id, papel, mfa=True, corretor_id=corretor_id, settings=settings
        ),
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
        # O vinculo de corretor e relido do banco a cada renovacao, como o
        # papel: e por aqui que uma mudanca de vinculo passa a valer, em ate 60
        # minutos. Ver a D4 da TEC-202, que herda a janela da lacuna L5 da 201.
        corretor_id = usuario.corretor_id

    return {
        "access": tokens.emitir(
            usuario_id, papel, mfa=mfa, corretor_id=corretor_id, settings=settings
        ),
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


@router.get("/me")
async def quem_sou_eu(
    identidade: IdentidadeDaRequisicao = Depends(EXIGE_SESSAO),
) -> dict[str, object]:
    """Papel, vinculo e permissoes de quem apresenta o token. TEC-202, D7.

    **Existe porque `VER_DADOS_COMPLETOS` precisava de um consumidor real.** A
    card concede a permissao por papel, e o mascaramento que a consumiria e a
    TEC-195, que nao esta entregue -- ao contrario do que o texto da card diz.
    Uma permissao que nenhum codigo consulta e codigo morto, e codigo morto
    numa matriz de seguranca e pior que ausente: parece protecao.

    **E quem pediu foi outra card.** A RN-FE-03.2 (TEC-312) diz que "papeis e
    permissoes vem de `GET /bff/me`; o cliente nao decodifica JWT" -- o BFF da
    TEC-302 precisa de uma origem para esses dados, e e esta.

    **Le so o token, nao o banco.** Papel e vinculo saem das claims, pela mesma
    razao que a D4 escolheu a claim em vez da consulta: a janela de defasagem
    ja existe e e de ate 60 minutos. Uma consulta aqui daria a esta rota uma
    frescura que nenhuma outra tem, e o painel leria dela uma verdade que a
    requisicao seguinte nao confirmaria.

    `permissoes` sai ORDENADA, e nao na ordem do `frozenset`, que varia entre
    processos: resposta que muda de forma sem mudar de conteudo quebra cache e
    atrapalha diff em teste.
    """
    return {
        "usuarioId": str(identidade.usuario_id),
        "papel": identidade.papel,
        "corretorId": str(identidade.corretor_id) if identidade.corretor_id else None,
        "permissoes": sorted(p.value for p in permissoes_de(identidade.papel)),
    }
