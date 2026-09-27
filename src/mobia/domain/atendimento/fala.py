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
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.tomada import assumir_conversa
from mobia.domain.messages.ancora import ancora_do_lead
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.janela import dentro_da_janela
from mobia.domain.outbound.kinds import kind_da_fala_do_corretor
from mobia.domain.outbound.models import OutboundDispatch
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
    `JANELA_FECHADA` e conferida antes da Meta desde a TEC-328 (D2), e a
    recusa do canal fica como segunda linha; `LEAD_EM_OPTOUT` vem da guarda.
    Nenhum dos dois muda tentando de novo. `CANAL_FALHOU` e o unico que pode.

    `MESSAGE_ID_EM_USO` e `FALA_EM_ENVIO` sao do `messageId` do cliente
    (TEC-328, D1): o id ja e de outra fala, ou ja ha reserva de envio para ele
    sem a fala gravada. Nos dois, enviar seria mandar algo que o id nao pediu.
    """

    CONVERSA_DE_OUTRO = "conversa_de_outro"
    SEM_FALA_DO_LEAD = "sem_fala_do_lead"
    JANELA_FECHADA = "janela_fechada"
    LEAD_EM_OPTOUT = "lead_em_optout"
    CANAL_FALHOU = "canal_falhou"
    MESSAGE_ID_EM_USO = "message_id_em_uso"
    FALA_EM_ENVIO = "fala_em_envio"


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
    fala_id: uuid.UUID | None = None,
) -> FalaEnviada:
    """Assume, envia, grava. Levanta `FalaNaoEnviada` com a razao.

    **`fala_id` e o `messageId` do cliente** (TEC-328, D1), e e o que torna o
    reenvio seguro: a fala ja gravada com ele volta como enviada, sem sair de
    novo. Sem ele, o id nasce aqui, como antes.

    **Sessoes curtas, e nao uma longa, com a chamada de rede entre elas**: uma
    antes do envio (conferencias do id e tomada), uma depois (a fala gravada),
    e uma terceira so quando a guarda devolve `False`. Segurar uma transacao
    aberta enquanto a Meta responde prenderia o lock de `atendimento_humano`
    pelo tempo do HTTP. A tomada e commitada antes do
    envio de proposito (ver a docstring do modulo); se o envio falhar, a
    conversa FICA assumida -- o corretor quis falar, e o agente voltar a
    responder por causa de uma falha de rede seria a surpresa pior.
    """
    channel, conversation_key = par
    fala_id = fala_id or uuid.uuid4()
    kind = kind_da_fala_do_corretor(fala_id)
    async with session_factory() as session:
        gravada = await _fala_ja_gravada(session, fala_id=fala_id, par=par)
        if gravada is not None:
            return gravada
        if await _reservada(session, kind=kind):
            raise FalaNaoEnviada(Recusa.FALA_EM_ENVIO)
        if await assumir_conversa(session, par=par, corretor_id=corretor_id) is None:
            raise FalaNaoEnviada(Recusa.CONVERSA_DE_OUTRO)
        ancora = await ancora_do_lead(session, channel=channel, conversation_key=conversation_key)
        await session.commit()

    if ancora is None or ancora.de is None:
        # Sem fala do lead nao ha de que numero mandar. Nao acontece com lead
        # que chegou pela lista -- ele existe porque falou -- e a TEC-207 nao
        # mudou isso: a eliminacao e a retencao mantem as linhas de `messages`
        # e o `recipient_external_id` delas, e o lead anonimizado nem chega
        # aqui, porque o apelido dele deixa de resolver. A guarda fica pelo
        # contrato de `Ancora.de`, que e nulavel: isto nao pode virar um POST
        # sem remetente.
        raise FalaNaoEnviada(Recusa.SEM_FALA_DO_LEAD)

    # A janela antes da Meta (TEC-328, D2): a mesma regra de follow-up,
    # lembrete e remarcacao, com a mesma ancora. A recusa da Meta (131047),
    # logo abaixo, fica como segunda linha -- o relogio daqui e o do servidor,
    # e o que vale e o dela.
    if channel == CANAL_WHATSAPP and not dentro_da_janela(
        ancora_em=ancora.criada_em, agora=datetime.now(UTC)
    ):
        raise FalaNaoEnviada(Recusa.JANELA_FECHADA)

    try:
        aceito = await outbound.send(
            ancora.message_id,
            kind,
            {"para": conversation_key, "de": ancora.de, "texto": texto},
        )
    except EnvioForaDaJanela as erro:
        raise FalaNaoEnviada(Recusa.JANELA_FECHADA) from erro
    except (EnvioRetentavel, EnvioRecusado) as erro:
        raise FalaNaoEnviada(Recusa.CANAL_FALHOU) from erro

    if not aceito:
        # Dois `False` possiveis. O da guarda de opt-out, que barra ANTES de
        # reservar; e o da reserva duplicada, que desde o `messageId` do
        # cliente (TEC-328, D1) acontece quando duas chamadas com o mesmo id
        # passam juntas pelas conferencias de cima. A guarda de atendimento
        # humano deixa este kind passar. A reserva existir e o que separa os
        # dois.
        async with session_factory() as session:
            if await _reservada(session, kind=kind):
                raise FalaNaoEnviada(Recusa.FALA_EM_ENVIO)
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


async def _fala_ja_gravada(
    session: AsyncSession, *, fala_id: uuid.UUID, par: tuple[str, str]
) -> FalaEnviada | None:
    """A fala deste id, se ja foi gravada para este lead. TEC-328, D1.

    Um id que existe e e de outra coisa -- fala do lead, do agente, de outro
    lead -- e `MESSAGE_ID_EM_USO`: devolve-lo como "enviada" mentiria sobre o
    que o lead recebeu.
    """
    linha = (
        await session.execute(
            select(
                Message.channel, Message.conversation_key, Message.role, Message.created_at
            ).where(Message.id == fala_id)
        )
    ).one_or_none()
    if linha is None:
        return None
    canal, chave, papel, criada_em = linha
    if (canal, chave) != par or papel != MessageRole.CORRETOR:
        raise FalaNaoEnviada(Recusa.MESSAGE_ID_EM_USO)
    return FalaEnviada(id=fala_id, em=criada_em)


async def _reservada(session: AsyncSession, *, kind: str) -> bool:
    """Ha reserva de envio para esta fala, por qualquer ancora. TEC-328, D1.

    Pelo `kind`, e nao pelo par da UNIQUE: o `message_id` da reserva e a
    ancora, e se o lead falou entre as duas tentativas a ancora mudou -- a
    UNIQUE deixaria a segunda sair.
    """
    total = (
        await session.execute(
            select(func.count()).select_from(OutboundDispatch).where(OutboundDispatch.kind == kind)
        )
    ).scalar_one()
    return bool(total)
