"""O corretor intervem no lead pelo dashboard. TEC-194, RN-18.3 e RN-18.4.

Cinco rotas, todas por `leadId` e todas com `ATENDER_LEAD`: assumir e devolver
a conversa, falar com o lead, corrigir a qualificacao e pedir o recalculo do
score. Mesmo prefixo de `leads.py`, e arquivo proprio porque aquele e de
LEITURA -- as rotas de la gravam acesso na trilha; estas mudam estado.

**Por `leadId`, e nao pelo par** (D1). Desde a TEC-195 o dashboard nao tem o
par -- no WhatsApp ele era o telefone, e desde a TEC-203 e o HMAC dele,
pseudonimo estavel do lead. As rotas antigas de `conversas.py` recebem o
par no corpo e continuam existindo; as duas portas passam pela mesma logica,
`atendimento/tomada.py`.

**O recorte e o do detalhe** (TEC-193, D2): apelido inexistente e 404 para
todo papel; o CORRETOR so age sobre lead com handoff para ele, e o contrario e
403 com `ACESSO_NEGADO` -- ver `_abrir`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono
from mobia.api.middleware import origem_da_requisicao
from mobia.api.saida import porta_de_saida
from mobia.domain.agente.schemas import FormaPagamento, TipoImovel, Urgencia
from mobia.domain.atendimento import tomada
from mobia.domain.atendimento.fala import TETO_DA_FALA, FalaNaoEnviada, Recusa, falar_com_o_lead
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Entidade
from mobia.domain.corretores.models import Corretor
from mobia.domain.leads.edicao import (
    CONVERSA_ENCERRADA,
    FAIXA_INVERTIDA,
    EdicaoRecusada,
    Resultado,
    editar_qualificacao,
    recalcular_a_pedido,
)
from mobia.domain.leads.repositorio import e_lead_do_corretor, par_de
from mobia.domain.outbound.port import OutboundPort
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])

_ATENDER = Depends(Exige(Permissao.ATENDER_LEAD))


async def _abrir(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao,
) -> tuple[str, str]:
    """404, depois o recorte do CORRETOR. O molde de `leads._abrir_para_leitura`.

    Sem o registro de leitura daquela: estas rotas mudam estado, e o que elas
    gravam na trilha e o que mudou (`QUALIFICACAO_ALTERADA`), nao o acesso.
    """
    par = await par_de(session, lead_id)
    if par is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")
    if identidade.e_corretor:
        dono = await e_lead_do_corretor(session, par=par, corretor_id=identidade.corretor_id)
        await exigir_dono(
            request,
            identidade,
            permissao=Permissao.ATENDER_LEAD,
            corretor_id=identidade.corretor_id if dono else None,
        )
    return par


async def _corretor_de(session: AsyncSession, identidade: IdentidadeDaRequisicao) -> uuid.UUID:
    """O corretor em nome de quem se assume, devolve e fala. D2 do desenho.

    **Da claim do JWT, nunca do corpo.** `atendimento_humano.assumido_por` tem
    FK para `corretores.id`, e as rotas antigas (`conversas.py`) aceitam o id
    no corpo porque nasceram quando so havia o `X-Admin-Token`, que nao
    carregava identidade nenhuma -- ramo que a TEC-382 apagou. Aqui a
    identidade existe, e aceitar o corpo reabriria o "falar em nome de
    terceiro" para ADMIN e GERENTE. Decisao do Eduardo, 26/09/2026.

    **409, e nao 403**: quem chama tem a permissao; o que falta e o cadastro
    de corretor, que e estado e nao autorizacao. Inativo e o mesmo caso -- um
    corretor desligado nao fala com lead nenhum.
    """
    corretor_id = identidade.corretor_id
    ativo = (
        await session.scalar(select(Corretor.ativo).where(Corretor.id == corretor_id))
        if corretor_id is not None
        else None
    )
    if corretor_id is None or not ativo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="usuario sem vinculo de corretor ativo: nao ha em nome de quem atender",
        )
    return corretor_id


@router.post("/{lead_id}/assumir")
async def assumir(
    lead_id: uuid.UUID, request: Request, identidade: IdentidadeDaRequisicao = _ATENDER
) -> dict[str, object]:
    """O agente cala nesta conversa, e o handoff aberto e aceito junto."""
    async with get_sessionmaker()() as session:
        par = await _abrir(session, lead_id=lead_id, request=request, identidade=identidade)
        corretor_id = await _corretor_de(session, identidade)
        atendimento = await tomada.assumir_conversa(session, par=par, corretor_id=corretor_id)
        if atendimento is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="conversa ja assumida por outro"
            )
        await session.commit()
    return {
        "status": "SILENCIADA",
        "assumidoPor": str(atendimento.assumido_por),
        "assumidoEm": atendimento.assumido_em.isoformat(),
    }


@router.post("/{lead_id}/devolver")
async def devolver(
    lead_id: uuid.UUID, request: Request, identidade: IdentidadeDaRequisicao = _ATENDER
) -> dict[str, object]:
    """O agente volta a falar. Quarto cenario do Gherkin.

    **A devolucao ja e registrada com autor e momento** --
    `atendimento_humano.devolvido_por` e `devolvido_em`, desde a TEC-179 (D7).
    Nao entra na trilha de auditoria: a RNF-18 nao a lista.
    """
    async with get_sessionmaker()() as session:
        par = await _abrir(session, lead_id=lead_id, request=request, identidade=identidade)
        corretor_id = await _corretor_de(session, identidade)
        atendimento = await tomada.devolver_conversa(session, par=par, corretor_id=corretor_id)
        if atendimento is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="conversa nao esta assumida"
            )
        await session.commit()
    return {
        "status": "REATIVADA",
        "assumidoPor": str(atendimento.assumido_por),
        "assumidoEm": atendimento.assumido_em.isoformat(),
    }


class PedidoDeFala(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TETO_DA_FALA)
    ]


# O status HTTP de cada recusa. 409 para o que e estado da conversa e nao muda
# tentando de novo; 502 para o canal, que e o unico que pode.
_STATUS_DA_RECUSA = {
    Recusa.CONVERSA_DE_OUTRO: status.HTTP_409_CONFLICT,
    Recusa.SEM_FALA_DO_LEAD: status.HTTP_409_CONFLICT,
    Recusa.JANELA_FECHADA: status.HTTP_409_CONFLICT,
    Recusa.LEAD_EM_OPTOUT: status.HTTP_409_CONFLICT,
    Recusa.CANAL_FALHOU: status.HTTP_502_BAD_GATEWAY,
}


@router.post("/{lead_id}/mensagens", status_code=status.HTTP_201_CREATED)
async def falar(
    lead_id: uuid.UUID,
    pedido: PedidoDeFala,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ATENDER,
    outbound: OutboundPort = Depends(porta_de_saida),
) -> dict[str, object]:
    """O corretor fala com o lead, e o agente cala. Primeiro cenario. D3.

    **Sincrono**: a resposta ja diz se a mensagem saiu. O `detail` de cada
    recusa e o valor de `Recusa`, e nao frase -- e o que a tela da TEC-328 le
    para decidir o que mostrar, e uma frase mudaria sem aviso.
    """
    async with get_sessionmaker()() as session:
        par = await _abrir(session, lead_id=lead_id, request=request, identidade=identidade)
        corretor_id = await _corretor_de(session, identidade)

    try:
        fala = await falar_com_o_lead(
            get_sessionmaker(),
            par=par,
            corretor_id=corretor_id,
            texto=pedido.texto,
            outbound=outbound,
        )
    except FalaNaoEnviada as erro:
        raise HTTPException(
            status_code=_STATUS_DA_RECUSA[erro.recusa], detail=erro.recusa.value
        ) from erro
    return {"id": str(fala.id), "em": fala.em.isoformat()}


class PedidoDeEdicao(BaseModel):
    """Os campos editaveis de `leads/edicao.py::EDITAVEIS`, todos opcionais.

    **Ausente nao muda; `null` explicito limpa.** A diferenca so existe em
    `model_fields_set`, e e por ele que a rota monta o que vai para o dominio
    -- um `model_dump()` simples mandaria `None` para todo campo nao enviado e
    apagaria a ficha inteira.
    """

    model_config = ConfigDict(extra="forbid")

    faixaPrecoMinCentavos: int | None = Field(default=None, ge=0)  # noqa: N815
    faixaPrecoMaxCentavos: int | None = Field(default=None, ge=0)  # noqa: N815
    regiao: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    tipoImovel: TipoImovel | None = None  # noqa: N815
    quartos: int | None = Field(default=None, ge=0, le=50)
    vagas: int | None = Field(default=None, ge=0, le=50)
    urgencia: Urgencia | None = None
    formaPagamento: FormaPagamento | None = None  # noqa: N815
    temImovelParaVender: bool | None = None  # noqa: N815


def _resposta(resultado: Resultado) -> dict[str, object]:
    return {
        "alterados": list(resultado.alterados),
        "scoreAnterior": resultado.score_anterior,
        "scoreAtual": resultado.score_atual,
        "temperatura": resultado.temperatura,
    }


_STATUS_DA_EDICAO = {
    CONVERSA_ENCERRADA: status.HTTP_409_CONFLICT,
    FAIXA_INVERTIDA: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


@router.patch("/{lead_id}/qualificacao")
async def editar(
    lead_id: uuid.UUID,
    pedido: PedidoDeEdicao,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ATENDER,
) -> dict[str, object]:
    """Corrige a qualificacao e recalcula o score. Segundo cenario. D4.

    **Um `QUALIFICACAO_ALTERADA` por campo que mudou**, no mesmo commit da
    edicao e da trilha de score. O valor NAO vai para a trilha -- "o registro
    diz qual campo mudou, nao para que" (TEC-206). Quem quiser o valor novo le
    a qualificacao; o antigo nao fica em lugar nenhum, e isso e a regra.
    """
    campos = {
        nome: (valor.value if hasattr(valor, "value") else valor)
        for nome in pedido.model_fields_set
        for valor in (getattr(pedido, nome),)
    }
    async with get_sessionmaker()() as session:
        par = await _abrir(session, lead_id=lead_id, request=request, identidade=identidade)
        try:
            resultado = await editar_qualificacao(
                session, par=par, campos=campos, autor=identidade.para_log()
            )
        except EdicaoRecusada as erro:
            raise HTTPException(
                status_code=_STATUS_DA_EDICAO[erro.motivo], detail=erro.motivo
            ) from erro
        for campo in resultado.alterados:
            await registrar_evento(
                session,
                ator=identidade.como_ator(),
                acao=Acao.QUALIFICACAO_ALTERADA,
                entidade=Entidade.LEAD_QUALIFICATION,
                # O apelido, e nunca o par -- a regra de `revelar`.
                entidade_id=str(lead_id),
                campo=campo,
                lead=par,
                origem=origem_da_requisicao(request),
            )
        await session.commit()
    return _resposta(resultado)


@router.post("/{lead_id}/score/recalcular")
async def recalcular(
    lead_id: uuid.UUID, request: Request, identidade: IdentidadeDaRequisicao = _ATENDER
) -> dict[str, object]:
    """Grava um recalculo com `RECALCULO_MANUAL` e o autor. Terceiro cenario. D5."""
    async with get_sessionmaker()() as session:
        par = await _abrir(session, lead_id=lead_id, request=request, identidade=identidade)
        try:
            resultado = await recalcular_a_pedido(session, par=par, autor=identidade.para_log())
        except EdicaoRecusada as erro:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=erro.motivo) from erro
        await session.commit()
    return _resposta(resultado)
