"""`apagar` nos dois adaptadores da porta. TEC-207, D1.

A anonimizacao apaga o arquivo de midia do lead depois do commit; a linha de
`midias_recebidas` ja sumiu, e o blob seria o unico resto do conteudo.
"""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from mobia.domain.midia.armazem import ArmazemLocal, ArmazemS3


async def test_local_apaga_o_arquivo(tmp_path) -> None:
    armazem = ArmazemLocal(tmp_path)
    await armazem.guardar("midias/abc", b"dados")

    await armazem.apagar("midias/abc")

    assert not (tmp_path / "midias" / "abc").exists()


async def test_local_apagar_inexistente_nao_levanta(tmp_path) -> None:
    # Idempotente: uma segunda anonimizacao, ou um retry depois de apagar
    # metade, nao reprova pelo arquivo que ja nao esta la.
    await ArmazemLocal(tmp_path).apagar("midias/nunca-existiu")


async def test_local_apagar_recusa_chave_que_sai_do_diretorio(tmp_path) -> None:
    with pytest.raises(ValueError):
        await ArmazemLocal(tmp_path).apagar("../fora")


class _ClienteS3Falso:
    def __init__(self) -> None:
        self.apagados: list[tuple[str, str]] = []

    async def delete_object(self, *, Bucket: str, Key: str, **_: Any) -> dict:
        self.apagados.append((Bucket, Key))
        return {}


async def test_s3_apagar_chama_delete_object() -> None:
    falso = _ClienteS3Falso()

    @asynccontextmanager
    async def cliente():
        yield falso

    await ArmazemS3("meu-bucket", "sa-east-1", cliente=cliente).apagar("midias/abc")

    assert falso.apagados == [("meu-bucket", "midias/abc")]
