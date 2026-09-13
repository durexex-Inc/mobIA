"""As duas rotas que escrevem o silencio do agente sobre uma conversa.

TEC-179, RN-16.4, D6 do desenho (o aceite do handoff junto) e a Emenda E-01
da secao 6.5 do SRS (aceitar depois da escalada e permitido).

**Nao existe `conversaId` (D9 do desenho).** O SRS escreve
`/conversas/{conversaId}`, mas essa entidade nao existe neste sistema -- a
conversa e o par `(channel, conversation_key)`, o mesmo que `handoffs` e
`optout_events` ja usam. As duas rotas abaixo recebem o par no CORPO, e nao
na URL. Vira emenda na Task 7.

Guardadas por `exigir_admin`, a mesma guarda de `handoffs.py` e
`corretores.py`: esta rota governa quem fala com qual lead, entao o
argumento da TEC-156 (rota sem token nao pode existir, e nao responder 401)
vale aqui com mais forca, nao menos.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.api.deps import exigir_admin
from mobia.api.routes.handoffs import _ACEITAVEIS
from mobia.domain.atendimento import repositorio as atendimento_repo
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/conversas", tags=["conversas"])


class PedidoDeAtendimento(BaseModel):
    """O par que identifica a conversa, mais quem pede.

    **`corretor_id` vem no corpo, e nao de alguma identidade autenticada
    (D2 do desenho).** Este endpoint so tem o token administrativo de
    `exigir_admin`, e aquele token nao carrega QUEM o esta usando --
    `corretor_id` e afirmacao de quem chama, nao identidade provada. O custo,
    aceito na D2, e que quem tem o token pode assumir ou devolver em nome de
    qualquer corretor cadastrado.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str
    conversation_key: str
    corretor_id: uuid.UUID

    @field_validator("channel", "conversation_key")
    @classmethod
    def _nao_vazio(cls, valor: str, info: object) -> str:
        # ValueError, nunca assert: assert dentro de um validador Pydantic
        # some sob `python -O` (mesma regra de corretores.py). E nao
        # normaliza para string tambem -- o Pydantic ja recusa `None` aqui
        # antes de chegar neste validador, porque o campo e `str` obrigatorio.
        if not valor.strip():
            raise ValueError(f"{info.field_name} nao pode ser vazio")  # type: ignore[attr-defined]
        return valor


async def _corretor_apto(session: AsyncSession, corretor_id: uuid.UUID) -> bool:
    """Existe e esta ativo. Um FALSE so cobre os dois casos -- ambos viram 404."""
    ativo = await session.scalar(select(Corretor.ativo).where(Corretor.id == corretor_id))
    return bool(ativo)


@router.post("/assumir")
async def assumir(
    pedido: PedidoDeAtendimento, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    """O corretor assume a conversa: o agente cala, e o handoff pendente sai da fila.

    `corretor_id` vem no corpo e nao no token -- ver o docstring de
    `PedidoDeAtendimento` (D2).

    **Aceita junto o handoff PENDENTE ou ESCALADO da mesma conversa (D6),
    na mesma transacao.** Nao e um segundo commit: se o processo caisse
    entre os dois, um corretor apareceria com a conversa silenciada mas a
    gerente continuaria sendo cobrada pelo SLA do handoff que ele acabou de
    pegar -- exatamente o cenario que a D6 existe para fechar. A lista de
    estados aceitaveis (`_ACEITAVEIS`) e importada de `handoffs.py`: as duas
    rotas decidem a mesma pergunta ("isto ainda pode virar ACEITO?"), e uma
    segunda copia da lista aqui poderia divergir da original em silencio --
    ver o comentario ao lado da constante, em `handoffs.py`, que agora
    tambem cita este segundo escritor.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        if not await _corretor_apto(session, pedido.corretor_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="corretor nao existe ou esta inativo",
            )

        atendimento = await atendimento_repo.assumir(
            session,
            channel=pedido.channel,
            conversation_key=pedido.conversation_key,
            corretor_id=pedido.corretor_id,
        )
        if atendimento is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="conversa ja assumida por outro",
            )

        agora = datetime.now(UTC)
        await session.execute(
            update(Handoff)
            .where(
                Handoff.channel == pedido.channel,
                Handoff.conversation_key == pedido.conversation_key,
                Handoff.status.in_(_ACEITAVEIS),
            )
            .values(status=Status.ACEITO.value, aceito_em=agora, atualizado_em=agora)
        )
        await session.commit()

    return {
        "status": "SILENCIADA",
        "assumidoPor": str(atendimento.assumido_por),
        "assumidoEm": atendimento.assumido_em.isoformat(),
    }


@router.post("/devolver")
async def devolver(
    pedido: PedidoDeAtendimento, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    """O corretor devolve a conversa: o agente volta a falar.

    Qualquer corretor pode devolver, nao so quem assumiu -- ver o docstring
    de `devolver` em `domain/atendimento/repositorio.py` (mesma D2: nao ha
    identidade provada, exigir o mesmo corretor travaria o caso real de
    quem assumiu e saiu de ferias).

    A resposta confirma quem tinha a conversa e desde quando -- nao "quem
    devolveu". Duas razoes: `corretor_id` ja e informacao que quem chamou
    possui, foi ele quem mandou; e o repositorio nao devolve o carimbo da
    devolucao, so o de quem tinha assumido antes (`Atendimento` e o mesmo
    dataclass para as duas funcoes). Um segundo `datetime.now(UTC)` calculado
    aqui na rota so para relatar "devolvidoEm" arriscaria divergir, por
    microssegundos, do carimbo que o UPDATE de fato gravou -- melhor devolver
    so o que se sabe ser exato.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        atendimento = await atendimento_repo.devolver(
            session,
            channel=pedido.channel,
            conversation_key=pedido.conversation_key,
            corretor_id=pedido.corretor_id,
        )
        if atendimento is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="conversa nao esta assumida",
            )
        await session.commit()

    return {
        "status": "REATIVADA",
        "assumidoPor": str(atendimento.assumido_por),
        "assumidoEm": atendimento.assumido_em.isoformat(),
    }
