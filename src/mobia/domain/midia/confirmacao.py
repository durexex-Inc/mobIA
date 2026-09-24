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
com_texto=True)`, em `domain/messages/rajada.py`).
"""

from mobia.domain.messages.enums import MessageContentType

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

# So os dois tipos que a TEC-132 guarda. Audio fica de fora de proposito: ele
# nao e guardado e nao recebe esta confirmacao -- segue o turno de sempre.
CONFIRMACOES_DE_MIDIA: dict[str, str] = {
    MessageContentType.IMAGEM: TEXTO_DA_CONFIRMACAO_DE_IMAGEM,
    MessageContentType.DOCUMENTO: TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO,
}
