"""TEC-203: a ingestao grava a chave no lugar do remetente, e a identidade junto."""

import pytest
from sqlalchemy import select

from mobia.domain.identidade.indice import chave_de, indice_de_telefone, revelar
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService


@pytest.fixture
def parsed_de():
    """Fabrica um `ParsedMessage` do WhatsApp com o remetente escolhido.

    Molde do helper `parsed` de `test_ingestion_service.py`, que e local
    aquele arquivo -- copiado aqui porque este teste precisa escolher o
    numero do remetente por caso, e o de la o fixa em "5511911112222".
    """

    def _construir(numero: str, provider_message_id: str = "wamid.SERVICO") -> ParsedMessage:
        return ParsedMessage(
            provider_message_id=provider_message_id,
            sender_external_id=numero,
            recipient_external_id="222222222",
            content_type=MessageContentType.TEXTO,
            text_body="quero agendar visita",
            raw_payload={"id": provider_message_id, "type": "text"},
        )

    return _construir


async def test_mensagem_do_whatsapp_grava_a_chave_e_a_identidade(
    banco_limpo, session_factory, parsed_de
) -> None:
    await IngestionService(session_factory, None).ingest([parsed_de("5548999990000")])
    async with session_factory() as session:
        linha = (await session.scalars(select(Message))).one()
        chave = chave_de("whatsapp", "5548999990000")
        assert linha.conversation_key == chave
        assert linha.sender_external_id == chave
        assert await revelar(session, "whatsapp", chave) == "5548999990000"


async def test_fala_no_widget_com_telefone_vincula_pelo_indice(ws_cliente, session) -> None:
    """A sessao web tambem entra pela chave: TEC-203, D4, linha "Entrada"."""
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": None})
    await ws.receber()
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "meu numero e 48 99999-0000"})
        assert await ws.receber() == {"tipo": "ack", "messageId": "m-1"}
    finally:
        await ws.__aexit__()

    vinculo = (await session.execute(select(VinculoDeSessao))).scalar_one()
    assert vinculo.telefone_indice == indice_de_telefone("5548999990000")
    # Nenhuma coluna de texto guarda o numero: nem a sessao (que virou HMAC),
    # nem o telefone (que so mora cifrado em `telefone_cifrado`).
    for coluna in (vinculo.conversation_key, vinculo.telefone_indice):
        assert "99999" not in coluna
