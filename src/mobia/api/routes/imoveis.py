"""Importacao do catalogo por HTTP (TEC-156, RN-08.1, secao 6.3 do SRS).

Assincrono como o SRS descreve: o POST devolve 202 com o id e enfileira, e o
GET devolve o relatorio. Nao e fidelidade cega -- a TEC-157 acrescenta a
geracao de embedding, que sao ~500 chamadas de API por importacao, e ali o
assincrono deixa de ser escolha. Fazer sincrono agora significaria emendar o
SRS duas vezes em duas cards. Ver D2 do desenho.
"""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from mobia.api.deps import exigir_admin
from mobia.domain.catalogo.enums import OrigemImportacao
from mobia.domain.catalogo.importacao import registrar
from mobia.domain.catalogo.models import Importacao
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/imoveis", tags=["catalogo"])

# ~40 mil imoveis. Acima disso o caminho e a CLI, que nao passa por upload.
TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024


@router.post("/importar", status_code=status.HTTP_202_ACCEPTED)
async def importar(
    request: Request,
    arquivo: Annotated[UploadFile, File()],
    _: None = Depends(exigir_admin),
) -> dict[str, str]:
    conteudo = await arquivo.read()
    if len(conteudo) > TETO_DE_UPLOAD_EM_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"arquivo acima de {TETO_DE_UPLOAD_EM_BYTES} bytes; use a CLI de seed",
        )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        importacao_id = await registrar(
            session,
            origem=OrigemImportacao.HTTP,
            nome_arquivo=arquivo.filename or "sem-nome",
            conteudo=conteudo,
        )
        await session.commit()

    pool = getattr(request.app.state, "redis_pool", None)
    if pool is not None:
        await pool.enqueue_job("importar_catalogo", str(importacao_id))

    log.info("catalogo.importacao_enfileirada", importacao_id=str(importacao_id))
    return {"importacaoId": str(importacao_id), "status": "PROCESSANDO"}


@router.get("/importacoes/{importacao_id}")
async def consultar(importacao_id: uuid.UUID, _: None = Depends(exigir_admin)) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)

    if importacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrada")

    # Enquanto o job nao termina, isto devolve PROCESSANDO com os totais em
    # zero. E o status que o consumidor le, nao o codigo HTTP.
    return {
        "importacaoId": str(importacao.id),
        "status": importacao.status,
        "nomeArquivo": importacao.nome_arquivo,
        "processados": importacao.processados,
        "inseridos": importacao.inseridos,
        "atualizados": importacao.atualizados,
        "inalterados": importacao.inalterados,
        "rejeitados": importacao.rejeitados,
        "erros": importacao.erros,
    }
