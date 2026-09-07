"""Importacao do catalogo por HTTP (TEC-156, RN-08.1, secao 6.3 do SRS).

Assincrono como o SRS descreve: o POST devolve 202 com o id e enfileira, e o
GET devolve o relatorio. Nao e fidelidade cega -- a TEC-157 acrescenta a
geracao de embedding, que sao ~500 chamadas de API por importacao, e ali o
assincrono deixa de ser escolha. Fazer sincrono agora significaria emendar o
SRS duas vezes em duas cards. Ver D2 do desenho.

**A linha e comitada antes do enqueue, e isso obriga a fechar o buraco.** O
job recebe so o `importacao_id` e le os bytes da propria linha (D9), entao a
linha precisa existir antes. Se o enqueue nao acontece -- Redis fora, app sem
pool --, ninguem mais toca nessa linha: nao ha job para roda-la e nao ha sweep
que varra importacao parada. Por isso o handler a fecha em FALHOU com motivo e
responde 503 com o id, em vez de devolver 202 sobre trabalho que nao comecou.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from mobia.api.deps import exigir_admin
from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
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
        # HTTP_413_CONTENT_TOO_LARGE, nao HTTP_413_REQUEST_ENTITY_TOO_LARGE: e
        # o mesmo codigo 413, mas o segundo nome esta deprecated nesta versao
        # do Starlette e emite warning a cada chamada.
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

    # `motivo` continua None so quando o job foi de fato para a fila. As duas
    # falhas possiveis -- app sem pool e enqueue que levanta -- tem a mesma
    # consequencia para a linha ja comitada, e por isso o mesmo tratamento.
    pool = getattr(request.app.state, "redis_pool", None)
    motivo: str | None = None
    if pool is None:
        motivo = "sem pool do Redis no app: o job de importacao nao foi enfileirado"
    else:
        try:
            await pool.enqueue_job("importar_catalogo", str(importacao_id))
        except Exception as erro:  # ampla de proposito -- ver `_marcar_falha`
            motivo = f"falha ao enfileirar o job: {erro}"

    if motivo is not None:
        await _marcar_falha(importacao_id, motivo)
        # 503 com o id no corpo, e nao o 500 vazio de antes: a linha ja foi
        # comitada, e sem o `importacaoId` o cliente nao tem como ler o motivo
        # no GET nem como saber que existe uma importacao para descartar.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "importacaoId": str(importacao_id),
                "status": str(StatusImportacao.FALHOU),
                "mensagem": "a importacao foi registrada mas nao pode ser enfileirada",
            },
        )

    # Depois do enqueue, e nunca antes: uma linha de log que afirma um evento
    # que nao aconteceu e, nesta base, o mesmo defeito de um comentario que
    # mente. Era o que acontecia sem `redis_pool` -- 202, status PROCESSANDO e
    # "importacao_enfileirada" no log, com a fila vazia.
    log.info("catalogo.importacao_enfileirada", importacao_id=str(importacao_id))
    return {"importacaoId": str(importacao_id), "status": "PROCESSANDO"}


async def _marcar_falha(importacao_id: uuid.UUID, motivo: str) -> None:
    """Fecha em FALHOU a linha que ficaria orfa em PROCESSANDO.

    A linha e comitada antes do enqueue -- e tem de ser, porque o job recebe
    so o id e precisa achar os bytes. Quando o enqueue nao acontece, ninguem
    mais vai tocar nessa linha: nao ha job para roda-la e nao ha sweep que
    varra importacao parada. Deixa-la em PROCESSANDO faz um trabalho que nunca
    comecou parecer trabalho em andamento, e prende ate 10 MB por vez.

    A excecao de quem chama e ampla de proposito: qualquer falha do Redis
    (timeout, conexao recusada, serializacao) tem a mesma consequencia para
    esta linha, e distinguir a causa aqui nao muda o que precisa ser gravado.
    """
    log.error(
        "catalogo.importacao_nao_enfileirada",
        importacao_id=str(importacao_id),
        motivo=motivo,
    )
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            return
        importacao.status = str(StatusImportacao.FALHOU)
        importacao.erros = [{"linha": 0, "motivo": motivo}]
        importacao.concluida_em = datetime.now(UTC)
        await session.commit()


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
