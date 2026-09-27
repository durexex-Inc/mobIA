"""As rotas do titular: a fila, a exportacao, a eliminacao e a recusa. TEC-207, D4.

Todas exigem `Permissao.ATENDER_TITULAR`, que so o ADMIN tem por construcao
(ver o comentario dela em `usuarios/permissoes.py`) -- nao ha papel de DPO
neste sistema.

**Duas rotas moram no prefixo de `leads`, e nao no de `titular`.** `GET` e
`DELETE /leads/{lead_id}/dados-pessoais` continuam o vocabulario da TEC-193
("o painel abre um LEAD, nao uma SOLICITACAO"), e por isso entram aqui com o
caminho completo em vez do prefixo deste router -- o `APIRouter` deste modulo
nao declara `prefix=` por causa disso.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Entidade
from mobia.domain.leads.repositorio import par_de, referencias_para
from mobia.domain.titular.exportacao import exportar
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import (
    SolicitacaoNaoAberta,
    listar,
    marcar_atendida,
    recusar,
    registrar_solicitacao,
    solicitacao_aberta,
)
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.eliminar_lead import ELIMINAR_LEAD_JOB

router = APIRouter(tags=["titular"])

_ATENDE_TITULAR = Depends(Exige(Permissao.ATENDER_TITULAR))


def _item(
    linha: SolicitacaoDeTitular, apelidos: dict[tuple[str, str], uuid.UUID]
) -> dict[str, object]:
    """Uma linha da fila, no camelCase da API. `leadId` e nulo para quem ja
    foi atendida ou recusada -- o par some da linha nesses dois status
    (`ck_solicitacoes_de_titular_par_com_status`), e nao ha apelido a buscar."""
    par = (
        (linha.channel, linha.conversation_key)
        if linha.channel is not None and linha.conversation_key is not None
        else None
    )
    return {
        "id": str(linha.id),
        "tipo": linha.tipo,
        "origem": linha.origem,
        "status": linha.status,
        "recebidaEm": linha.recebida_em.isoformat(),
        "prazoEm": linha.prazo_em.isoformat(),
        "atendidaEm": linha.atendida_em.isoformat() if linha.atendida_em else None,
        "motivoDaRecusa": linha.motivo_da_recusa,
        "leadId": str(apelidos[par]) if par is not None else None,
    }


@router.get("/api/v1/titular/solicitacoes")
async def solicitacoes(
    status_da_fila: Annotated[str | None, Query(alias="status")] = None,
    _: IdentidadeDaRequisicao = _ATENDE_TITULAR,
) -> dict[str, object]:
    """A fila, por prazo -- quem vence primeiro aparece primeiro (D4)."""
    status_enum: StatusDaSolicitacao | None = None
    if status_da_fila is not None:
        try:
            status_enum = StatusDaSolicitacao(status_da_fila)
        except ValueError as erro:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"status invalido: {status_da_fila}",
            ) from erro

    async with get_sessionmaker()() as session:
        linhas = await listar(session, status=status_enum)
        pares = [
            (linha.channel, linha.conversation_key)
            for linha in linhas
            if linha.channel is not None and linha.conversation_key is not None
        ]
        apelidos = await referencias_para(session, pares)
        await session.commit()

    return {"itens": [_item(linha, apelidos) for linha in linhas]}


async def _par_ou_404(session: AsyncSession, lead_id: uuid.UUID) -> tuple[str, str]:
    par = await par_de(session, lead_id)
    if par is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")
    return par


@router.get("/api/v1/leads/{lead_id}/dados-pessoais")
async def dados_pessoais(
    lead_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ATENDE_TITULAR,
) -> dict[str, object]:
    """A exportacao inteira do lead -- RN de acesso do titular. D4.

    **A trilha e gravada antes de a ACESSO aberta virar ATENDIDA**, e as duas
    coisas commitam juntas com o resto: se a escrita falhar, a resposta e erro
    e nada desta chamada persiste, no mesmo molde de `leads.py::revelar`.
    """
    async with get_sessionmaker()() as session:
        par = await _par_ou_404(session, lead_id)

        exportado = await exportar(session, lead_id=lead_id, par=par)
        if exportado is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")

        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADOS_EXPORTADOS,
            entidade=Entidade.LEAD,
            entidade_id=str(lead_id),
            lead=par,
            origem=origem_da_requisicao(request),
        )

        aberta = await solicitacao_aberta(
            session, channel=par[0], conversation_key=par[1], tipo=TipoDeSolicitacao.ACESSO
        )
        if aberta is not None:
            await marcar_atendida(session, aberta.id, agora=datetime.now(UTC))

        await session.commit()

    return exportado


@router.delete("/api/v1/leads/{lead_id}/dados-pessoais", status_code=status.HTTP_202_ACCEPTED)
async def eliminar(
    lead_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ATENDE_TITULAR,
) -> dict[str, object]:
    """Registra (ou reaproveita) a ELIMINACAO e enfileira o job que a executa.

    **A rota deixa a solicitacao ABERTA** -- `registrar_solicitacao` e
    idempotente pelo par e pelo tipo, entao um pedido de ELIMINACAO do
    proprio WhatsApp que ja estivesse aberto e reaproveitado, sem origem
    trocada. Quem fecha a solicitacao e o job, via `eliminacao.anonimizar`.

    **Sem pool, ou com o enqueue falhando, e 503** -- no molde de
    `imoveis.py::importar`. Ao contrario daquela rota, nao ha nada a desfazer
    aqui: a solicitacao so fica ABERTA, que e o estado correto ate o job
    rodar, e uma chamada seguinte reaproveita a mesma linha e tenta enfileirar
    de novo.
    """
    async with get_sessionmaker()() as session:
        par = await _par_ou_404(session, lead_id)

        solicitacao_id = await registrar_solicitacao(
            session,
            channel=par[0],
            conversation_key=par[1],
            tipo=TipoDeSolicitacao.ELIMINACAO,
            origem=OrigemDaSolicitacao.ADMIN,
            ator=identidade.como_ator(),
        )
        await session.commit()

    pool = getattr(request.app.state, "redis_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sem pool do Redis no app: o job de eliminacao nao foi enfileirado",
        )
    try:
        await pool.enqueue_job(
            ELIMINAR_LEAD_JOB, str(solicitacao_id), _job_id=f"titular:{solicitacao_id}"
        )
    except Exception as erro:  # ampla de proposito -- mesmo argumento de `imoveis.py`
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"falha ao enfileirar o job: {type(erro).__name__}",
        ) from erro

    return {"solicitacaoId": str(solicitacao_id), "status": StatusDaSolicitacao.ABERTA.value}


class PedidoDeRecusa(BaseModel):
    """O motivo da recusa. 1..2000 caracteres, e nao so espaco."""

    motivo: str = Field(min_length=1, max_length=2000)

    @field_validator("motivo")
    @classmethod
    def _nao_so_espaco(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("motivo nao pode ser so espaco")
        return valor


@router.post("/api/v1/titular/solicitacoes/{solicitacao_id}/recusa")
async def recusa(
    solicitacao_id: uuid.UUID,
    pedido: PedidoDeRecusa,
    identidade: IdentidadeDaRequisicao = _ATENDE_TITULAR,
) -> dict[str, object]:
    """404 se a solicitacao nao existe; 409 se ja nao esta ABERTA. D4."""
    async with get_sessionmaker()() as session:
        linha = await session.get(SolicitacaoDeTitular, solicitacao_id)
        if linha is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="solicitacao nao existe"
            )

        try:
            await recusar(
                session, solicitacao_id, motivo=pedido.motivo, ator=identidade.como_ator()
            )
        except SolicitacaoNaoAberta as erro:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(erro)) from erro
        await session.commit()

        atualizada = await session.get(SolicitacaoDeTitular, solicitacao_id)
        assert atualizada is not None

    return _item(atualizada, {})
