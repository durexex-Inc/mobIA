"""A legenda de imagem e documento vira texto. TEC-132, D3."""

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import parse_meta_envelope


def _envelope(mensagem: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "pn-1"},
                            "messages": [{"id": "wamid.1", "from": "5548999990000", **mensagem}],
                        }
                    }
                ]
            }
        ]
    }


def test_imagem_com_legenda() -> None:
    [msg] = parse_meta_envelope(
        _envelope(
            {
                "type": "image",
                "image": {"id": "m1", "mime_type": "image/jpeg", "caption": "esse aqui"},
            }
        )
    )
    assert (msg.content_type, msg.text_body) == (MessageContentType.IMAGEM, "esse aqui")


def test_documento_com_legenda() -> None:
    [msg] = parse_meta_envelope(
        _envelope(
            {
                "type": "document",
                "document": {"id": "d1", "mime_type": "application/pdf", "caption": "contrato"},
            }
        )
    )
    assert (msg.content_type, msg.text_body) == (MessageContentType.DOCUMENTO, "contrato")


def test_imagem_sem_legenda_fica_sem_texto() -> None:
    [msg] = parse_meta_envelope(
        _envelope({"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg"}})
    )
    assert msg.text_body is None


def test_legenda_so_de_espacos_fica_sem_texto() -> None:
    [msg] = parse_meta_envelope(
        _envelope(
            {"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg", "caption": "   "}}
        )
    )
    assert msg.text_body is None
