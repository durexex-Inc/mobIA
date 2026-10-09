"""TEC-404, D8: o cursor da lista de pedidos e opaco e recusa lixo."""

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.portal.pedidos import CursorDePedidos, CursorInvalido, decodificar_cursor


def _b64(corpo: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(corpo).encode("utf-8")).decode("ascii")


def test_ida_e_volta() -> None:
    cursor = CursorDePedidos(criado_em=datetime(2026, 10, 9, 16, 48, tzinfo=UTC), id=uuid.uuid4())
    assert decodificar_cursor(cursor.codificar()) == cursor


@pytest.mark.parametrize(
    "texto",
    [
        "lixo",
        "",
        "eyJ4IjoxfQ==",
        # JSON valido que nao e objeto.
        _b64([]),
        _b64(None),
        # Data sem fuso: comparada com `timestamptz` ela seria lida no fuso da
        # sessao do banco, e a pagina seguinte pularia ou repetiria linhas.
        _b64({"c": "2026-10-09T16:48:00", "i": str(uuid.uuid4())}),
    ],
)
def test_lixo_e_cursor_invalido(texto: str) -> None:
    with pytest.raises(CursorInvalido):
        decodificar_cursor(texto)
