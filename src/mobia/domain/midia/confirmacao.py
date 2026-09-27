"""A confirmacao fixa de midia recebida sem texto do lead (TEC-132, D4).

Fixa, e nao gerada pelo modelo, por duas razoes. A primeira e a garantia: o
agente nao ve a midia, e um texto constante e a unica forma de GARANTIR que
nada se afirma sobre o conteudo dela -- um modelo convidado a responder a uma
foto sem texto tende a descreve-la, e a descricao seria inventada. A segunda
e o preco: zero token, porque nao ha texto do lead a moderar nem pergunta a
fazer ao modelo.

"Recebi" e verdade mesmo que o download falhe depois: a confirmacao nao le
`midias_recebidas` e nao espera o job de download.

Quem decide QUANDO ela sai e o turno (`domain/agente/turno.py`), depois das
guardas de opt-out, atendimento humano e conversa encerrada, e so quando nao
ha texto do lead pendente na rajada (`ha_fala_pendente_antes(...,
com_texto=True)`, em `domain/messages/rajada.py`) -- e nao sai de novo
quando a ultima fala do agente ja foi ela, ha pouco (`ja_confirmou_ha_pouco`).

Desde a TEC-131 (D4), o audio sem transcricao tambem recebe texto fixo, pelo
mesmo ramo do turno e com as mesmas guardas -- mas com texto, kind e subagente
proprios (`aviso_de_audio`), e sem a regra do "ja confirmou ha pouco". O audio
transcrito nao passa por aqui: ele tem texto, e segue o turno de sempre.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageContentType, MessageDirection
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.midia.models import MidiaRecebida, MotivoDaTranscricao

TEXTO_DA_CONFIRMACAO_DE_IMAGEM = (
    "Recebi sua imagem! Por aqui eu ainda não consigo ver fotos. "
    "Me conta em texto qual imóvel ou característica te interessou?"
)

TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO = (
    "Recebi seu arquivo! Por aqui eu ainda não consigo abrir documentos. "
    "Me conta em texto o que você precisa, que eu te ajudo?"
)

# Kind proprio pela mesma razao do kind da confirmacao de opt-out: a reserva
# em `outbound_dispatches` e UNIQUE (message_id, kind), e nao pode colidir com
# a resposta que este turno nao vai mandar.
KIND_DA_CONFIRMACAO_DE_MIDIA = "confirmacao_de_midia"

# Rotulo de `message_telemetry.subagent`. A coluna e `String(32)` sem CHECK e
# sem `Literal`: o vocabulario e aberto, e um rotulo novo nao pede migration.
SUBAGENTE_MIDIA = "midia"

# So imagem e documento. O audio e guardado desde a TEC-131, mas nao recebe
# esta confirmacao: o "recebi" daqui cobre as midias seguintes por dez minutos
# (`ja_confirmou_ha_pouco`), e o aviso de audio nao pode cobrir -- ver
# `aviso_de_audio`.
CONFIRMACOES_DE_MIDIA: dict[str, str] = {
    MessageContentType.IMAGEM: TEXTO_DA_CONFIRMACAO_DE_IMAGEM,
    MessageContentType.DOCUMENTO: TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO,
}

# Quanto tempo uma confirmacao cobre as midias sem texto que chegam depois
# dela. O debounce agrupa so as fotos de uma mesma janela; quem manda cinco
# fotos de um imovel ao longo de dois ou tres minutos atravessa varias janelas
# e rodaria um turno por foto, recebendo o mesmo texto fixo a cada uma -- um
# robo repetindo a mesma frase. Dez minutos cobrem essa sequencia com folga e
# sao curtos o bastante para uma foto mandada depois de uma pausa real ser
# confirmada de novo: ai ela e um envio novo, e o silencio pareceria perda.
JANELA_DA_CONFIRMACAO_DE_MIDIA = timedelta(minutes=10)


async def ja_confirmou_ha_pouco(session: AsyncSession, message: Message) -> bool:
    """A ultima fala do agente nesta conversa foi uma confirmacao de midia, a
    menos de `JANELA_DA_CONFIRMACAO_DE_MIDIA` de `message`?

    **O kind da fala sai de `message_telemetry.subagent`, e nao de
    `outbound_dispatches`.** A reserva e chaveada pela mensagem INBOUND que o
    turno respondeu, e nada liga a reserva a linha OUTBOUND que a entrega
    gravou; a telemetria e gravada NA linha OUTBOUND, e `SUBAGENTE_MIDIA` so
    e usado por esta confirmacao. Sem telemetria (o recorder a grava por
    melhor esforco), a resposta e False e a confirmacao sai: o erro vai para
    o lado da duplicata visivel, e nao do silencio.

    "Ultima fala do agente" e a mesma definicao de `ha_fala_pendente_antes`
    (`domain/messages/rajada.py`): a OUTBOUND mais nova da conversa. Qualquer
    resposta do agente depois da confirmacao a desbanca, e a proxima midia
    confirma de novo.

    O relogio e o `created_at` de `message`, e nao o agora: a pergunta e
    sobre o intervalo entre os envios do lead, e uma retentativa atrasada da
    mesma mensagem tem de chegar a mesma resposta.
    """
    ultima = await session.scalar(
        select(func.max(Message.created_at)).where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.OUTBOUND,
        )
    )
    if ultima is None or message.created_at - ultima >= JANELA_DA_CONFIRMACAO_DE_MIDIA:
        return False
    subagente = await session.scalar(
        select(MessageTelemetry.subagent)
        .join(Message, Message.id == MessageTelemetry.message_id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.OUTBOUND,
            Message.created_at == ultima,
        )
        .limit(1)
    )
    return subagente == SUBAGENTE_MIDIA


# TEC-131, D4. Os dois avisos do audio sem transcricao. Com acento: e texto que o
# lead recebe (TEC-267).
TEXTO_DO_AUDIO_LONGO = (
    "Recebi seu áudio! Por aqui eu só consigo ouvir áudios de até 2 minutos. "
    "Pode me mandar por escrito o que você precisa?"
)

TEXTO_DO_AUDIO_NAO_TRANSCRITO = (
    "Recebi seu áudio, mas não consegui ouvir direito. Pode me escrever o que você disse?"
)

# Kind proprio pela razao do de cima: a UNIQUE (message_id, kind) de
# `outbound_dispatches` nao pode colidir com a resposta que o turno nao manda.
KIND_DO_AVISO_DE_AUDIO = "aviso_de_audio"

# Subagente proprio, e nao `SUBAGENTE_MIDIA`: `ja_confirmou_ha_pouco` le este
# rotulo, e um aviso de audio contado como confirmacao de midia silenciaria a
# foto mandada logo depois -- que precisa do "recebi" dela.
SUBAGENTE_AUDIO = "audio"


async def aviso_de_audio(session: AsyncSession, message: Message) -> str:
    """O texto fixo do audio que chegou ao turno sem transcricao.

    Acima da duracao, o aviso do limite; qualquer outro caso -- falha da
    Whisper, da Meta, formato, silencio, ou o prazo da espera vencido sem
    desfecho --, o de falha. Para o lead a diferenca que importa e so esta: no
    primeiro, um audio mais curto resolveria; no segundo, nao ha o que ele
    corrija, e o pedido e para escrever.

    **Sem a regra do "ja confirmou ha pouco"**, e isso e deliberado (D4). Na
    imagem, a segunda foto em silencio nao perde nada: o "recebi" da primeira
    vale para as duas. Aqui cada aviso diz o que aconteceu com AQUELE audio, e
    quem recebeu "ate 2 minutos" e mandou um de 1:50 que falhou nao pode ficar
    em silencio.
    """
    motivo = await session.scalar(
        select(MidiaRecebida.motivo_da_transcricao).where(MidiaRecebida.message_id == message.id)
    )
    if motivo == MotivoDaTranscricao.ACIMA_DA_DURACAO:
        return TEXTO_DO_AUDIO_LONGO
    return TEXTO_DO_AUDIO_NAO_TRANSCRITO
