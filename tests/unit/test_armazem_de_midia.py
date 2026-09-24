"""Os dois adaptadores da porta. TEC-132, D1."""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from mobia.domain.midia.armazem import ArmazemLocal, ArmazemS3


async def test_local_ida_e_volta(tmp_path) -> None:
    armazem = ArmazemLocal(tmp_path)
    await armazem.guardar("midias/abc", b"\x00\x01dados")
    assert await armazem.ler("midias/abc") == b"\x00\x01dados"
    assert (tmp_path / "midias" / "abc").exists()


async def test_local_recusa_chave_que_sai_do_diretorio(tmp_path) -> None:
    with pytest.raises(ValueError):
        await ArmazemLocal(tmp_path).guardar("../fora", b"x")


class _Corpo:
    def __init__(self, dados: bytes) -> None:
        self._dados = dados

    async def read(self) -> bytes:
        return self._dados


class _ClienteS3Falso:
    def __init__(self) -> None:
        self.objetos: dict[tuple[str, str], bytes] = {}

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: Any) -> dict:
        self.objetos[(Bucket, Key)] = Body
        return {}

    async def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": _Corpo(self.objetos[(Bucket, Key)])}


async def test_s3_ida_e_volta_contra_cliente_falso() -> None:
    falso = _ClienteS3Falso()

    @asynccontextmanager
    async def cliente():
        yield falso

    armazem = ArmazemS3("meu-bucket", "sa-east-1", cliente=cliente)
    await armazem.guardar("midias/abc", b"dados")
    assert falso.objetos[("meu-bucket", "midias/abc")] == b"dados"
    assert await armazem.ler("midias/abc") == b"dados"
