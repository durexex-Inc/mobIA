"""Quem, na rajada, e o turno -- e se sobrou pergunta sem resposta.

Duas perguntas sobre a vizinhanca de uma mensagem na conversa, cada uma a
servico de uma regra diferente. `superada_por_mais_nova` responde a RN-01.6
com a emenda E-01: a ultima mensagem do lead responde por todas -- "chegou
algo mais novo deste lead?". `ha_fala_pendente_antes` responde a TEC-295: o
turno bloqueado pela moderacao pode continuar sem cair no engajamento que a
TEC-233 recusou? So se nao existir, antes dele, uma fala do lead sem resposta.

Nenhuma das duas guarda estado. "A janela ainda esta aberta" e "ficou
pergunta pendente" nao sao gravados em lugar nenhum: sao recomputados de
`messages`, que e onde ja esta.
"""

from datetime import datetime

from sqlalchemy import func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message


async def superada_por_mais_nova(session: AsyncSession, message: Message) -> bool:
    """Chegou INBOUND mais nova deste lead depois de `message`?

    **O desempate por `id` nao e zelo, e obrigatorio.** Um envelope da Meta pode
    trazer varias mensagens, e `IngestionService._persist` as insere num `INSERT`
    so, numa transacao so. Como `created_at` e `server_default=func.now()` e o
    `now()` do Postgres e o instante da TRANSACAO, as irmas do mesmo envelope
    nascem com `created_at` identico. Comparar so por `created_at` faria cada uma
    se considerar superada pelas outras, e NENHUMA responderia -- o lead ficaria
    sem resposta, que e pior que as tres respostas que esta card veio corrigir.

    O par ordenado e o mesmo de `literais_apos` (`context/janela.py`), e pela
    mesma razao; casa com `ix_messages_timeline (channel, conversation_key,
    created_at DESC)`.

    O filtro de direcao existe porque a fala do proprio agente vai para esta
    tabela com o mesmo `conversation_key` da conversa. Sem ele, a resposta de um
    turno superaria a mensagem seguinte do lead e ela nunca seria respondida.
    """
    mais_nova = await session.scalar(
        select(Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            tuple_(Message.created_at, Message.id)
            > tuple_(literal(message.created_at), literal(message.id)),
        )
        .limit(1)
    )
    return mais_nova is not None


async def ha_fala_pendente_antes(
    session: AsyncSession,
    message: Message,
    *,
    teto_do_agente: datetime | None = None,
) -> bool:
    """Ficou fala do lead sem resposta antes desta mensagem?

    Existe INBOUND deste lead, nao bloqueada, mais antiga que `message` e mais
    nova que a ultima fala do agente? Se existe, o lead perguntou alguma coisa
    que ninguem respondeu -- tipicamente uma irma de rajada que fechou
    "agrupado" enquanto esta mensagem carregava o turno.

    **Nao basta olhar a mensagem imediatamente anterior.** Numa rajada em que a
    penultima foi bloqueada pela moderacao e a antepenultima era legitima, a
    imediatamente anterior esta bloqueada e a pergunta legitima ficaria orfa.
    Por isso a fronteira e a ultima fala do AGENTE, e nao a linha vizinha.

    A fronteira do agente compara so `created_at`, e nao o par ordenado que
    `superada_por_mais_nova` usa contra `message`: fala do agente nasce uma de
    cada vez, pelo recorder, nunca num lote de envelope, entao nao ha ali o
    empate de instante que obriga o desempate por `id` do lado do lead.

    `bloqueada_em IS NULL` e a mesma definicao de "fala do lead" que
    `contar_mensagens_do_lead` (`context/repositorio.py`) e a ancora da
    cadencia de follow-up (`followup/repositorio.py`) usam. `context/score.py`
    registra que as tres leituras tem de concordar; esta e a quarta.

    **`teto_do_agente` existe porque a propria recusa apaga a pendencia
    (TEC-298, D1).** Numa retentativa, a recusa que a passada anterior
    entregou ja esta em `messages` como OUTBOUND e vira a ultima fala do
    agente -- mesmo nao tendo respondido nada. Com o teto no instante da
    RESERVA da recusa (`outbound_dispatches.created_at`, que e commitado
    antes do envio e portanto anterior a linha dela), a fronteira volta a ser
    a que existia antes da recusa.

    **Quem chama tem de saber que precisa passar isto, e hoje ha um chamador
    so.** A funcao nao descobre o teto sozinha de proposito: descobri-lo
    exigiria conhecer `outbound_dispatches` e o kind da recusa, e este modulo
    nao pode depender de `domain/outbound` -- a dependencia so corre no outro
    sentido. A D2 do desenho registra o risco: um chamador futuro que
    esquecer o teto cai no defeito de hoje, em silencio.

    O default `None` mantem todo chamador antigo correto: sem teto, a
    fronteira e exatamente a de antes desta card.
    """
    fronteira = [
        Message.channel == message.channel,
        Message.conversation_key == message.conversation_key,
        Message.direction == MessageDirection.OUTBOUND,
    ]
    if teto_do_agente is not None:
        fronteira.append(Message.created_at < teto_do_agente)
    ultima_do_agente = select(func.max(Message.created_at)).where(*fronteira).scalar_subquery()
    pendente = await session.scalar(
        select(Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            Message.bloqueada_em.is_(None),
            tuple_(Message.created_at, Message.id)
            < tuple_(literal(message.created_at), literal(message.id)),
            # Conversa sem nenhuma fala do agente ainda: `MAX` devolve NULL e
            # toda INBOUND anterior conta.
            or_(ultima_do_agente.is_(None), Message.created_at > ultima_do_agente),
        )
        .limit(1)
    )
    return pendente is not None
