"""Rotaciona a chave de indice do lead, ou a do `lead_ref`. TEC-203, D1/D3.

Roda com webhook e worker PARADOS: reescreve o `conversation_key` de ~20
tabelas, inclusive PK, numa transacao so. Ver `docs/seguranca/segredos.md`.

Chave de indice nova: ponha a nova em LEAD_INDICE_CHAVE (e LEAD_INDICE_CHAVE_ID)
e rode sem argumento. Chave do `lead_ref` nova: ponha a nova em
AUDITORIA_CHAVE_DO_LEAD, a velha em AUDITORIA_CHAVE_DO_LEAD_ANTERIOR, e rode.
"""

import asyncio
import os
import sys

from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de, indice_de_telefone
from mobia.domain.identidade.reindexacao import (
    TABELAS_COM_CHAVE_DE_LEAD,
    Reindexacao,
    reindexar,
    reindexar_telefones_dos_vinculos,
)
from mobia.infra.db import dispose_engine, get_engine


def avisos(*, anterior: str, atual: str, resultado: Reindexacao) -> list[str]:
    """O que o operador precisa ler alem da contagem.

    Nenhum dos dois reprova: a transacao ja commitou quando isto roda, e o
    par pulado continua onde estava. Mas os dois pedem olho humano.
    """
    saida = []
    if resultado.sem_identidade:
        saida.append(
            f"AVISO: {resultado.sem_identidade} par(es) sem identidade ficaram na chave"
            " antiga -- ver `reindexacao.par_sem_identidade` no log"
        )
    # Chave do `lead_ref` trocada e nenhuma linha recalculada: ou a trilha esta
    # vazia, ou AUDITORIA_CHAVE_DO_LEAD_ANTERIOR nao e a chave que a gravou.
    if anterior != atual and resultado.lead_refs_recalculados == 0:
        saida.append(
            "AVISO: nenhum lead_ref foi recalculado -- confira se"
            " AUDITORIA_CHAVE_DO_LEAD_ANTERIOR e a chave que gravou a trilha"
        )
    return saida


async def _rodar() -> int:
    atual = get_settings().auditoria_chave_do_lead
    anterior = os.environ.get("AUDITORIA_CHAVE_DO_LEAD_ANTERIOR") or atual
    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga=anterior,
                chave_do_lead_nova=atual,
            )
        )
        await conexao.run_sync(
            lambda conn: reindexar_telefones_dos_vinculos(conn, indice_de_telefone)
        )
    await dispose_engine()
    print(f"{resultado.mudados} lead(s) reindexado(s)")
    for aviso in avisos(anterior=anterior, atual=atual, resultado=resultado):
        print(aviso)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_rodar()))
