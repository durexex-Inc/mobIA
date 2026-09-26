"""O corretor fala com o lead pelo dashboard. TEC-194, D3.

**Envia, e so depois grava** -- a mesma ordem que o turno usa para a fala do
agente. Gravar antes deixaria na transcricao uma fala que o lead nunca
recebeu, e e justamente a transcricao que o proximo corretor le para saber o
que ja foi dito.

**Ancorada na ultima fala do lead** (`messages/ancora.py`), como todo envio
fora do turno: e dela que sai o numero do canal que fala com este lead, e e
pela conversa dela que as guardas de `GuardedOutbound` decidem. O `kind` e
unico por fala (`outbound/kinds.py::kind_da_fala_do_corretor`), e por isso
atravessa a guarda de atendimento humano e nao a de opt-out.

**A conversa e assumida antes do envio, na mesma chamada.** O primeiro cenario
da card pede que enviar SILENCIE o agente, e a ordem importa: com o envio
primeiro, um turno do agente que rodasse no intervalo responderia por cima do
que o corretor acabou de dizer.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.tomada import assumir_conversa
from mobia.domain.messages.ancora import ancora_do_lead
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.kinds import kind_da_fala_do_corretor
from mobia.domain.outbound.port import (
    EnvioForaDaJanela,
    EnvioRecusado,
    EnvioRetentavel,
    OutboundPort,
)
from mobia.infra.crypto import aad_de, encrypt

# O teto de texto da Meta para mensagem de sessao. O do web e maior, e o
# menor dos dois vale para os dois: um corretor nao deve precisar saber em que
# canal o lead esta para saber quanto pode escrever.
TETO_DA_FALA = 4096


class Recusa(StrEnum):
    """Por que a fala nao saiu. Cada valor vira uma resposta HTTP distinta.

    `CONVERSA_DE_OUTRO` e decidido antes de qualquer envio: outro corretor tem
    a conversa, e falar por cima dele e o que a TEC-179 existe para impedir.
    `JANELA_FECHADA` vem do canal e `LEAD_EM_OPTOUT` da guarda; nenhum dos
    dois muda tentando de novo. `CANAL_FALHOU` e o unico que pode.
    """

    CONVERSA_DE_OUTRO = "conversa_de_outro"
    SEM_FALA_DO_LEAD = "sem_fala_do_lead"
    JANELA_FECHADA = "janela_fechada"
    LEAD_EM_OPTOUT = "lead_em_optout"
    CANAL_FALHOU = "canal_falhou"


@dataclass(frozen=True)
class FalaEnviada:
    id: uuid.UUID
    em: datetime


class FalaNaoEnviada(Exception):
    def __init__(self, recusa: Recusa) -> None:
        super().__init__(recusa.value)
        self.recusa = recusa


async def falar_com_o_lead(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    par: tuple[str, str],
    corretor_id: uuid.UUID,
    texto: str,
    outbound: OutboundPort,
) -> FalaEnviada:
    """Assume, envia, grava. Levanta `FalaNaoEnviada` com a razao.

    **Tres sessoes curtas, e nao uma longa**, e a do meio e a chamada de rede:
    segurar uma transacao aberta enquanto a Meta responde prenderia o lock de
    `atendimento_humano` pelo tempo do HTTP. A tomada e commitada antes do
    envio de proposito (ver a docstring do modulo); se o envio falhar, a
    conversa FICA assumida -- o corretor quis falar, e o agente voltar a
    responder por causa de uma falha de rede seria a surpresa pior.
    """
    channel, conversation_key = par
    async with session_factory() as session:
        if await assumir_conversa(session, par=par, corretor_id=corretor_id) is None:
            raise FalaNaoEnviada(Recusa.CONVERSA_DE_OUTRO)
        ancora = await ancora_do_lead(session, channel=channel, conversation_key=conversation_key)
        await session.commit()

    if ancora is None or ancora.de is None:
        # Sem fala do lead nao ha de que numero mandar. Nao acontece com lead
        # que chegou pela lista -- ele existe porque falou --, mas a TEC-207 vai
        # eliminar mensagens, e isto nao pode virar um POST sem remetente.
        raise FalaNaoEnviada(Recusa.SEM_FALA_DO_LEAD)

    fala_id = uuid.uuid4()
    try:
        aceito = await outbound.send(
            ancora.message_id,
            kind_da_fala_do_corretor(fala_id),
            {"para": conversation_key, "de": ancora.de, "texto": texto},
        )
    except EnvioForaDaJanela as erro:
        raise FalaNaoEnviada(Recusa.JANELA_FECHADA) from erro
    except (EnvioRetentavel, EnvioRecusado) as erro:
        raise FalaNaoEnviada(Recusa.CANAL_FALHOU) from erro

    if not aceito:
        # O kind e unico por fala, entao a reserva nunca e duplicata, e a
        # guarda de atendimento humano deixa este kind passar: o unico `False`
        # possivel e o da guarda de opt-out.
        raise FalaNaoEnviada(Recusa.LEAD_EM_OPTOUT)

    async with session_factory() as session:
        linha = Message(
            id=fala_id,
            channel=channel,
            conversation_key=conversation_key,
            role=MessageRole.CORRETOR,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            # O par trocado em relacao a fala do lead, como na fala do agente:
            # quem manda e o numero do canal, quem recebe e o lead.
            sender_external_id=ancora.de,
            recipient_external_id=conversation_key,
            text_body=encrypt(texto, aad_de(fala_id, "text_body")),
            # `status` nulo: a linha de saida nao participa do pipeline de
            # ingestao (ver o comentario da coluna), e um QUEUED aqui faria o
            # sweeper entrega-la ao `process_message` como se o lead a tivesse
            # escrito.
            status=None,
        )
        session.add(linha)
        await session.commit()
        await session.refresh(linha)
        return FalaEnviada(id=linha.id, em=linha.created_at)
