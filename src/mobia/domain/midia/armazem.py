"""Onde o arquivo de midia mora. TEC-132, D1.

**O que chega aqui ja vem cifrado** (`encrypt_bytes`, AAD
`aad_de(message_id, "midia")`): a porta nao sabe cifrar e nao precisa. Um
bucket vazado, ou um diretorio copiado, entrega blobs que so a chave de
conteudo abre -- e a chave nao mora junto.
"""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol

from mobia.app.config import Settings


class ArmazemDeMidia(Protocol):
    async def guardar(self, chave: str, dados: bytes) -> None: ...

    async def ler(self, chave: str) -> bytes: ...


class ArmazemLocal:
    """Diretorio no disco. O padrao de desenvolvimento e dos testes."""

    def __init__(self, diretorio: Path) -> None:
        self._raiz = diretorio.resolve()

    def _caminho(self, chave: str) -> Path:
        caminho = (self._raiz / chave).resolve()
        # A chave vem do proprio codigo (`chave_do_objeto`), mas a porta nao
        # confia nisso: um `..` escaparia do diretorio.
        if not caminho.is_relative_to(self._raiz):
            raise ValueError("chave fora do diretorio do armazem")
        return caminho

    async def guardar(self, chave: str, dados: bytes) -> None:
        caminho = self._caminho(chave)

        def _gravar() -> None:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(dados)

        await asyncio.to_thread(_gravar)

    async def ler(self, chave: str) -> bytes:
        return await asyncio.to_thread(self._caminho(chave).read_bytes)


class ArmazemS3:
    """S3, para producao. O bucket e as credenciais sao da TEC-219."""

    def __init__(
        self,
        bucket: str,
        regiao: str,
        *,
        cliente: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        self._bucket = bucket
        self._regiao = regiao
        self._cliente = cliente or self._cliente_aioboto3

    def _cliente_aioboto3(self) -> AbstractAsyncContextManager[Any]:
        import aioboto3  # import tardio: so quem liga o S3 paga o import

        return aioboto3.Session().client("s3", region_name=self._regiao)

    async def guardar(self, chave: str, dados: bytes) -> None:
        async with self._cliente() as s3:
            await s3.put_object(Bucket=self._bucket, Key=chave, Body=dados)

    async def ler(self, chave: str) -> bytes:
        async with self._cliente() as s3:
            resposta = await s3.get_object(Bucket=self._bucket, Key=chave)
            dados: bytes = await resposta["Body"].read()
            return dados


def armazem_da_config(settings: Settings) -> ArmazemDeMidia:
    if settings.midia_armazem == "s3":
        return ArmazemS3(settings.midia_s3_bucket, settings.midia_s3_regiao)
    return ArmazemLocal(Path(settings.midia_diretorio))
