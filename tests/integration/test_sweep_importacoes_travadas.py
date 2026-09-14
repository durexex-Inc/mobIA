"""A varredura que encerra importacao parada em PROCESSANDO. TEC-261."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.models import Importacao
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_importacoes_travadas import (
    MOTIVO_DA_VARREDURA,
    sweep_importacoes_travadas,
)


def _ctx() -> dict[str, Any]:
    """Molde do ctx que os testes de `sweep_stalled` montam."""
    return {"session_factory": get_sessionmaker()}


async def _importacao(
    session: Any,
    *,
    status: StatusImportacao,
    idade_segundos: int,
    processados: int = 0,
) -> uuid.UUID:
    """Uma linha com idade controlada.

    `criada_em` tem `server_default=clock_timestamp()`, entao envelhecer a
    linha exige passar o valor explicitamente -- sem isso toda linha nasce
    recente e nenhum cenario de limite e exercitado.
    """
    identificador = uuid.uuid4()
    session.add(
        Importacao(
            id=identificador,
            origem=str(OrigemImportacao.HTTP),
            nome_arquivo="catalogo.csv",
            arquivo=b"codigo,titulo\n",
            status=str(status),
            processados=processados,
            criada_em=datetime.now(UTC) - timedelta(seconds=idade_segundos),
        )
    )
    await session.commit()
    return identificador


async def test_importacao_parada_alem_do_limite_e_encerrada(session: Any) -> None:
    """Cenario 1. O relatorio passa a dizer "nao terminou" em vez de "processando".

    Sem isto, `PROCESSANDO` significa duas coisas -- "o worker esta
    trabalhando" e "o worker morreu" -- e quem consulta nao sabe se espera ou
    reimporta.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.PROCESSANDO, idade_segundos=3600
    )

    assert await sweep_importacoes_travadas(_ctx()) == 1

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.FALHOU)
    assert lida.concluida_em is not None, (
        "uma linha FALHOU sem timestamp de fim nao diz quando parou"
    )
    assert lida.erros == [{"linha": 0, "motivo": MOTIVO_DA_VARREDURA}], (
        "mesma forma que `_marcar_falha` grava -- linha 0 e a convencao da "
        "TEC-156 para falha de arquivo inteiro"
    )


async def test_importacao_recente_nao_e_tocada(session: Any) -> None:
    """Cenario 2. O limite existe para nao matar trabalho vivo.

    Uma importacao pode legitimamente levar ate 20 minutos de processamento
    (5 tentativas de `job_timeout=240`), e fechar uma que ainda esta rodando e
    a mentira que esta card existe para acabar.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.PROCESSANDO, idade_segundos=60
    )

    assert await sweep_importacoes_travadas(_ctx()) == 0

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.PROCESSANDO)
    assert lida.concluida_em is None


async def test_importacao_concluida_nao_e_tocada(session: Any) -> None:
    """Cenario 3. So `PROCESSANDO` entra na varredura.

    Uma linha CONCLUIDO velha e o caso NORMAL -- toda importacao bem-sucedida
    vira uma. Se o filtro fosse so pela idade, a varredura reescreveria o
    relatorio de toda importacao antiga do sistema.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.CONCLUIDO, idade_segundos=3600, processados=42
    )

    assert await sweep_importacoes_travadas(_ctx()) == 0

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.CONCLUIDO)
    assert lida.processados == 42
    assert lida.erros == []
