"""Allowlist e chave do objeto. TEC-132, D1 e D3."""

import uuid

import pytest

from mobia.domain.midia.politica import chave_do_objeto, tipo_permitido


@pytest.mark.parametrize(
    "mime",
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "IMAGE/JPEG",
        "image/jpeg; charset=binary",
    ],
)
def test_permitidos(mime: str) -> None:
    assert tipo_permitido(mime)


@pytest.mark.parametrize(
    "mime", ["image/gif", "application/zip", "application/x-msdownload", "text/html", ""]
)
def test_recusados(mime: str) -> None:
    assert not tipo_permitido(mime)


def test_a_chave_nao_leva_nada_alem_do_id() -> None:
    identificador = uuid.uuid4()
    assert chave_do_objeto(identificador) == f"midias/{identificador}"
