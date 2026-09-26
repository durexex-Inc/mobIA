"""As duas rotas que escrevem o silencio do agente sobre uma conversa.

TEC-179, RN-16.4, D6 do desenho (o aceite do handoff junto), a Emenda E-01
da secao 6.5 do SRS (aceitar depois da escalada e permitido) e a TEC-278
(D2: devolver conclui o handoff aberto da mesma conversa).

**Nao existe `conversaId` (D9 do desenho).** O SRS escreve
`/conversas/{conversaId}`, mas essa entidade nao existe neste sistema -- a
conversa e o par `(channel, conversation_key)`, o mesmo que `handoffs` e
`optout_events` ja usam. As duas rotas abaixo recebem o par no CORPO, e nao
na URL. Vira emenda na Task 7.

Guardadas por `ATENDER_LEAD` (TEC-202), a mesma permissao de `handoffs.py`:
estas rotas governam quem fala com qual lead, entao o argumento da TEC-156
(rota sem token nao pode existir, e nao responder 401) vale aqui com mais
forca, nao menos.

**E o `corretor_id` do corpo deixou de ser so afirmacao para o papel
CORRETOR** -- ver `_exigir_que_seja_ele_mesmo` e a Emenda E-05 a RN-16.4.

**O dashboard nao usa estas rotas desde a TEC-194.** Ele conhece o lead pelo
`leadId` (TEC-195) e nao tem o par -- no WhatsApp ele era o telefone, e desde
a TEC-203 e o HMAC dele, pseudonimo estavel do lead; as rotas dele
sao `POST /leads/{leadId}/assumir` e `/devolver`, em `leads.py`, e tiram o
corretor da claim em vez do corpo. Estas ficam para quem tem o par -- o
`X-Admin-Token` e os testes que ja existem --, e as duas portas passam pela
mesma logica, `atendimento/tomada.py`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono
from mobia.domain.atendimento import tomada
from mobia.domain.corretores.models import Corretor
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/conversas", tags=["conversas"])


class PedidoDeAtendimento(BaseModel):
    """O par que identifica a conversa, mais quem pede.

    **`corretor_id` continua vindo no corpo, e desde a TEC-202 ele e
    CONFERIDO quando quem chama e um CORRETOR** (Emenda E-05 a RN-16.4).

    A D2 desta card registrou que o campo era "afirmacao de quem chama, nao
    identidade provada", porque o `X-Admin-Token` nao carrega QUEM o esta
    usando. O JWT carrega: para papel CORRETOR, mandar o id de outro e 403 com
    registro. Para ADMIN e GERENTE -- e para o token compartilhado, que resolve
    para ADMIN --, o campo SEGUE sendo afirmacao, porque agir em nome de
    terceiro e a funcao desses papeis, e o custo que a D2 aceitou permanece
    inteiro para quem usa o token.
    """

    model_config = ConfigDict(extra="forbid")

    # Mesmo teto das colunas (`String(32)`/`String(64)` na migration 0029).
    # Sem o limite, uma `conversation_key` de mais de 64 caracteres passa no
    # Pydantic e vira `StringDataRightTruncationError` no flush -- que nao e
    # `IntegrityError`, escapa do `except` do repositorio e vira 500 em vez de
    # 422. Precedente: `corretores.py:44-49`.
    channel: str = Field(max_length=32)
    conversation_key: str = Field(max_length=64)
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


async def _exigir_que_seja_ele_mesmo(
    request: Request, identidade: IdentidadeDaRequisicao, corretor_id: uuid.UUID
) -> None:
    """O CORRETOR so assume e devolve em nome de si mesmo. TEC-202, D5.

    **Antes de `_corretor_apto`, de proposito.** Aquela checagem responde 404
    para corretor inexistente ou inativo, e deixa-la primeiro daria a um
    corretor um oraculo sobre o cadastro dos colegas: 404 para id que nao
    existe, 403 para id que existe. Autorizacao antes de existencia.
    """
    await exigir_dono(
        request, identidade, permissao=Permissao.ATENDER_LEAD, corretor_id=corretor_id
    )


async def _corretor_apto(session: AsyncSession, corretor_id: uuid.UUID) -> bool:
    """Existe e esta ativo. Um FALSE so cobre os dois casos -- ambos viram 404."""
    ativo = await session.scalar(select(Corretor.ativo).where(Corretor.id == corretor_id))
    return bool(ativo)


@router.post("/assumir")
async def assumir(
    pedido: PedidoDeAtendimento,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
    """O corretor assume a conversa: o agente cala, e o handoff pendente sai da fila.

    `corretor_id` vem no corpo, e para o papel CORRETOR ele e conferido
    contra a claim do token desde a TEC-202 -- ver o docstring de
    `PedidoDeAtendimento`.

    **Aceita junto o handoff PENDENTE ou ESCALADO da mesma conversa (D6),
    na mesma transacao** -- o como e o porque moram em
    `atendimento/tomada.py::assumir_conversa` desde a TEC-194, que precisou
    da mesma logica nas rotas por `leadId`.
    """
    await _exigir_que_seja_ele_mesmo(request, identidade, pedido.corretor_id)

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        if not await _corretor_apto(session, pedido.corretor_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="corretor nao existe ou esta inativo",
            )

        atendimento = await tomada.assumir_conversa(
            session,
            par=(pedido.channel, pedido.conversation_key),
            corretor_id=pedido.corretor_id,
        )
        if atendimento is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="conversa ja assumida por outro",
            )
        await session.commit()

    return {
        "status": "SILENCIADA",
        "assumidoPor": str(atendimento.assumido_por),
        "assumidoEm": atendimento.assumido_em.isoformat(),
    }


@router.post("/devolver")
async def devolver(
    pedido: PedidoDeAtendimento,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
    """O corretor devolve a conversa: o agente volta a falar.

    **Conclui junto o handoff aberto da mesma conversa (D2), na mesma
    transacao** -- ver `atendimento/tomada.py::devolver_conversa`.

    Qualquer corretor pode devolver, nao so quem assumiu -- ver o docstring
    de `devolver` em `domain/atendimento/repositorio.py`. **A TEC-202 nao
    mudou isso**, e a distincao importa: ela passou a exigir que o CORRETOR
    devolva em nome de si mesmo, nao que ele seja quem assumiu. Exigir o
    segundo travaria o caso real de quem assumiu e saiu de ferias, que e a
    razao escrita na D2. Isso e sobre QUEM devolve nao precisar
    ser quem assumiu -- nao sobre dispensar a validacao do corretor: o
    `corretor_id` grava em `devolvido_por`, que tem a mesma FK para
    `corretores.id` que `assumido_por` tem, entao esta rota valida o
    corretor do mesmo jeito que `assumir` (`_corretor_apto`, existe e
    ativo). Sem isto, um `corretor_id` inexistente numa conversa de fato
    assumida faria o UPDATE achar a linha, tentar gravar o FK invalido, e
    estourar `IntegrityError` -- 500 em vez do 404 previsivel.

    A resposta confirma quem tinha a conversa e desde quando -- nao "quem
    devolveu". Duas razoes: `corretor_id` ja e informacao que quem chamou
    possui, foi ele quem mandou; e o repositorio nao devolve o carimbo da
    devolucao, so o de quem tinha assumido antes (`Atendimento` e o mesmo
    dataclass para as duas funcoes). Um segundo `datetime.now(UTC)` calculado
    aqui na rota so para relatar "devolvidoEm" arriscaria divergir, por
    microssegundos, do carimbo que o UPDATE de fato gravou -- melhor devolver
    so o que se sabe ser exato.
    """
    await _exigir_que_seja_ele_mesmo(request, identidade, pedido.corretor_id)

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        if not await _corretor_apto(session, pedido.corretor_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="corretor nao existe ou esta inativo",
            )

        atendimento = await tomada.devolver_conversa(
            session,
            par=(pedido.channel, pedido.conversation_key),
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
