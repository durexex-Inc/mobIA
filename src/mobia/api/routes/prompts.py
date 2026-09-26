"""Versoes de prompt, publicacao e rollback. TEC-199, RN-19.4 e CA-19.2.

Todas com `CONFIGURAR_AGENTE`, a permissao da TEC-198 -- so ADMIN, de escrita.
Uma segunda permissao so teria sentido se algum papel pudesse mexer no prompt
e nao na configuracao, e nenhum pode.

**O rollback vale no turno seguinte, sem reiniciar nada** (D5): cada turno le
os modelos vigentes na hora -- ver `domain/prompts/repositorio.py`.

**O texto de uma versao e um MODELO** (D2): tem `{assistente}` e `{tom}`, que a
configuracao da TEC-198 preenche, e nao tem a clausula de dado nao confiavel,
que o codigo anexa. A versao 0 e o padrao escrito no codigo.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Entidade
from mobia.domain.prompts import repositorio
from mobia.domain.prompts.modelo import (
    AgenteDoPrompt,
    ModeloInvalido,
    modelo_padrao,
    teto_de_caracteres,
    validar_modelo,
)
from mobia.domain.prompts.models import AtivacaoDePrompt, VersaoDePrompt
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])

_ADMIN = Depends(Exige(Permissao.CONFIGURAR_AGENTE))

_Agente = Annotated[AgenteDoPrompt, Path()]


def _ativa_na_api(a: repositorio.Ativa) -> dict[str, object]:
    return {
        "agente": a.agente.value,
        "versao": a.numero,
        "padrao": a.numero == 0,
        "publicadaPor": a.publicada_por,
        "publicadaEm": a.publicada_em.isoformat() if a.publicada_em else None,
        "ativadaPor": a.ativada_por,
        "ativadaEm": a.ativada_em.isoformat() if a.ativada_em else None,
        "motivo": a.motivo.value if a.motivo else None,
    }


def _versao_na_api(v: VersaoDePrompt, *, com_texto: bool) -> dict[str, object]:
    corpo: dict[str, object] = {
        "versao": v.numero,
        "anterior": v.anterior,
        "autor": v.autor,
        "em": v.criado_em.isoformat(),
        "diff": v.diff,
    }
    if com_texto:
        corpo["texto"] = v.texto
    return corpo


def _ativacao_na_api(a: AtivacaoDePrompt) -> dict[str, object]:
    return {
        "versao": a.numero,
        "motivo": a.motivo,
        "autor": a.autor,
        "em": a.criado_em.isoformat(),
    }


@router.get("")
async def listar_agentes(_: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    """Os prompts versionados, cada um com a versao que vale agora."""
    async with get_sessionmaker()() as session:
        itens = [
            _ativa_na_api(await repositorio.ativa(session, agente)) for agente in AgenteDoPrompt
        ]
    return {"itens": itens}


@router.get("/{agente}")
async def ler(agente: _Agente, _: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    """A ativa com o texto, e os limites da publicacao.

    O `padrao` vai junto mesmo quando a ativa e outra versao: e o que deixa a
    tela mostrar que o desenvolvimento mudou o padrao depois que a versao
    ativa foi publicada (L1 do desenho).
    """
    async with get_sessionmaker()() as session:
        vigente = await repositorio.ativa(session, agente)
    return {
        "ativa": {**_ativa_na_api(vigente), "texto": vigente.texto},
        "padrao": modelo_padrao(agente),
        "limites": {
            "marcadores": ["{assistente}", "{tom}"],
            "maximoDeCaracteres": teto_de_caracteres(agente),
        },
    }


@router.get("/{agente}/versoes")
async def listar_versoes(
    agente: _Agente,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """As versoes publicadas, a mais nova primeiro, cada uma com o diff contra
    a que valia quando ela foi publicada. Sem o texto -- ele vem no `GET` da
    versao."""
    async with get_sessionmaker()() as session:
        vigente = await repositorio.ativa(session, agente)
        versoes = await repositorio.listar_versoes(session, agente=agente, limite=limite)
    return {
        "ativa": vigente.numero,
        "itens": [_versao_na_api(v, com_texto=False) for v in versoes],
    }


@router.get("/{agente}/versoes/{numero}")
async def ler_versao(
    agente: _Agente,
    numero: Annotated[int, Path(ge=0)],
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Uma versao com o texto. A 0 e o padrao do codigo, sem autor nem diff."""
    if numero == 0:
        return {"versao": 0, "padrao": True, "texto": modelo_padrao(agente)}
    async with get_sessionmaker()() as session:
        try:
            versao = await repositorio.versao(session, agente=agente, numero=numero)
        except repositorio.VersaoInexistente as erro:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    return _versao_na_api(versao, com_texto=True)


class PedidoDePublicacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str


@router.post("/{agente}/versoes", status_code=status.HTTP_201_CREATED)
async def publicar(
    agente: _Agente,
    pedido: PedidoDePublicacao,
    request: Request,
    response: Response,
    identidade: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Publica o texto como versao seguinte e a ativa. O primeiro cenario.

    **422 fora das regras, e nada e gravado** (D2, D3). **Texto igual ao
    vigente nao grava nada**: uma versao identica poria no historico uma
    mudanca que nao aconteceu -- responde 200 com a vigente e `publicada: false`.
    Duas publicacoes simultaneas colidem no numero, e a segunda leva **409**.

    **`PROMPT_PUBLICADO` na trilha, no mesmo commit**, com o agente em `campo`
    e sem o texto.
    """
    try:
        texto = validar_modelo(agente, pedido.texto)
    except ModeloInvalido as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        vigente = await repositorio.ativa(session, agente)
        if vigente.texto == texto:
            response.status_code = status.HTTP_200_OK
            return {"publicada": False, "ativa": _ativa_na_api(vigente)}
        try:
            versao, ativacao = await repositorio.publicar(
                session, agente=agente, texto=texto, autor=identidade.para_log()
            )
        except IntegrityError as erro:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="outra publicacao deste prompt aconteceu ao mesmo tempo; recarregue",
            ) from erro
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.PROMPT_PUBLICADO,
            entidade=Entidade.CONFIGURACAO_AGENTE,
            entidade_id=str(ativacao.id),
            campo=agente.value,
            origem=origem_da_requisicao(request),
        )
        await session.commit()
        nova = await repositorio.ativa(session, agente)
    return {
        "publicada": True,
        "ativa": _ativa_na_api(nova),
        "versao": _versao_na_api(versao, com_texto=False),
    }


class PedidoDeRollback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: Annotated[int, Field(ge=0, strict=True)]


@router.post("/{agente}/rollback")
async def reverter(
    agente: _Agente,
    pedido: PedidoDeRollback,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Volta a valer uma versao ja publicada, ou o padrao (0). O segundo cenario.

    So grava a ativacao -- o texto ja existe. Vale no proximo turno que
    comecar, porque cada turno le o vigente na hora. **404** para versao que
    nunca existiu, **409** para a que ja e a ativa.

    **`PROMPT_REVERTIDO` na trilha, no mesmo commit.** Reverter um agente nao
    toca o outro: cada ativacao e de um agente so.
    """
    async with get_sessionmaker()() as session:
        try:
            ativacao = await repositorio.reverter(
                session, agente=agente, numero=pedido.versao, autor=identidade.para_log()
            )
        except repositorio.VersaoInexistente as erro:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
        except repositorio.JaEAtiva as erro:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(erro)) from erro
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.PROMPT_REVERTIDO,
            entidade=Entidade.CONFIGURACAO_AGENTE,
            entidade_id=str(ativacao.id),
            campo=agente.value,
            origem=origem_da_requisicao(request),
        )
        await session.commit()
        nova = await repositorio.ativa(session, agente)
    return {"ativa": _ativa_na_api(nova)}


@router.get("/{agente}/historico")
async def ler_historico(
    agente: _Agente,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Cada vez que uma versao passou a valer, por publicacao ou rollback, com
    autor, instante e a versao de destino. O quarto cenario."""
    async with get_sessionmaker()() as session:
        ativacoes = await repositorio.historico(session, agente=agente, limite=limite)
    return {"itens": [_ativacao_na_api(a) for a in ativacoes]}
