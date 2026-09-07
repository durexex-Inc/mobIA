"""Orquestra a importacao: le o arquivo da tabela, parseia, grava, relata.

TEC-156. Este e o ponto unico que as duas entradas chamam -- a CLI direto no
proprio processo, o endpoint HTTP atraves do job ARQ. A diferenca entre elas
esta em QUEM chama e de onde, nunca no que acontece.

**Commit por lote, e nao uma transacao unica.** Se algo estourar na linha 800,
os 500 primeiros imoveis ficam gravados e a `importacoes` registra FALHOU com
os totais parciais REAIS. Um COMMIT no fim desfaria trabalho bom e
transformaria erro tardio em "nada aconteceu" -- que e exatamente o resultado
que a historia da card descarta. A importacao nao e atomica, e isso e a
premissa da RN-08.5 ("registra falhas por linha sem abortar o lote"), nao um
efeito colateral: atomicidade e sucesso parcial sao requisitos opostos.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.models import Importacao
from mobia.domain.catalogo.parser import ArquivoInvalido, parsear
from mobia.domain.catalogo.repositorio import TAMANHO_DO_LOTE, sincronizar
from mobia.domain.catalogo.schemas import RegistroImovel, Rejeicao, Relatorio

log = structlog.get_logger(__name__)


async def registrar(
    session: AsyncSession,
    *,
    origem: OrigemImportacao,
    nome_arquivo: str,
    conteudo: bytes,
) -> uuid.UUID:
    """Cria a linha PROCESSANDO com os bytes, e devolve o id.

    A linha existe desde o POST -- e por isso que consultar antes de o job
    terminar devolve 200 com status PROCESSANDO, e nao 404.
    """
    importacao = Importacao(
        id=uuid.uuid4(),
        origem=str(origem),
        nome_arquivo=nome_arquivo,
        arquivo=conteudo,
        status=str(StatusImportacao.PROCESSANDO),
    )
    session.add(importacao)
    await session.flush()
    return importacao.id


async def executar(
    sessionmaker: async_sessionmaker[AsyncSession], *, importacao_id: uuid.UUID
) -> Relatorio:
    async with sessionmaker() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            raise LookupError(f"importacao {importacao_id} nao existe")
        conteudo = importacao.arquivo
        nome_arquivo = importacao.nome_arquivo

    relatorio = Relatorio()

    try:
        itens = list(parsear(conteudo, nome_arquivo=nome_arquivo))
    except ArquivoInvalido as erro:
        # Nao e "uma linha": o arquivo inteiro nao pode ser processado. Linha 0
        # porque o relatorio precisa carregar o motivo em algum lugar, e
        # nenhuma linha real tem esse numero.
        await _concluir(
            sessionmaker,
            importacao_id,
            relatorio,
            status=StatusImportacao.FALHOU,
            falha=Rejeicao(linha=0, motivo=str(erro)),
        )
        log.warning(
            "catalogo.importacao_falhou",
            importacao_id=str(importacao_id),
            motivo=str(erro),
        )
        return relatorio

    validos: list[RegistroImovel] = []
    for item in itens:
        if isinstance(item, Rejeicao):
            relatorio.registrar_rejeicao(item)
        else:
            validos.append(item)

    try:
        # Este laco fatia de novo o que `sincronizar` ja fatia internamente, e
        # a redundancia e intencional -- nao simplifique. Os dois cortes tem
        # propositos diferentes: o de dentro limita o tamanho do `IN (...)` do
        # SELECT, o daqui define a FRONTEIRA DE COMMIT. Chamar `sincronizar`
        # uma vez com a lista inteira gravaria tudo numa transacao so, e uma
        # falha na linha 800 desfaria os 500 primeiros imoveis -- exatamente o
        # "nada aconteceu" que a RN-08.5 recusa.
        for comeco in range(0, len(validos), TAMANHO_DO_LOTE):
            lote = validos[comeco : comeco + TAMANHO_DO_LOTE]
            async with sessionmaker() as session:
                inseridos, atualizados, inalterados = await sincronizar(session, lote)
                await session.commit()
            relatorio.inseridos += inseridos
            relatorio.atualizados += atualizados
            relatorio.inalterados += inalterados
            relatorio.processados += len(lote)
    except Exception as erro:  # excecao ampla e deliberada -- ver docstring do modulo
        # Os lotes ja comitados ficam. O relatorio guarda os totais parciais
        # reais, que e mais util que "nada aconteceu".
        await _concluir(
            sessionmaker,
            importacao_id,
            relatorio,
            status=StatusImportacao.FALHOU,
            falha=Rejeicao(linha=0, motivo=f"falha durante a gravacao: {erro}"),
        )
        log.exception(
            "catalogo.importacao_interrompida",
            importacao_id=str(importacao_id),
        )
        return relatorio

    await _concluir(sessionmaker, importacao_id, relatorio, status=StatusImportacao.CONCLUIDO)
    log.info(
        "catalogo.importacao_concluida",
        importacao_id=str(importacao_id),
        processados=relatorio.processados,
        inseridos=relatorio.inseridos,
        atualizados=relatorio.atualizados,
        inalterados=relatorio.inalterados,
        rejeitados=relatorio.rejeitados,
    )
    return relatorio


async def _concluir(
    sessionmaker: async_sessionmaker[AsyncSession],
    importacao_id: uuid.UUID,
    relatorio: Relatorio,
    *,
    status: StatusImportacao,
    falha: Rejeicao | None = None,
) -> None:
    erros: Sequence[Rejeicao] = relatorio.erros if falha is None else [falha, *relatorio.erros]
    async with sessionmaker() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            return
        importacao.status = str(status)
        importacao.processados = relatorio.processados
        importacao.inseridos = relatorio.inseridos
        importacao.atualizados = relatorio.atualizados
        importacao.inalterados = relatorio.inalterados
        importacao.rejeitados = relatorio.rejeitados
        importacao.erros = [{"linha": e.linha, "motivo": e.motivo} for e in erros]
        importacao.concluida_em = datetime.now(UTC)
        await session.commit()
