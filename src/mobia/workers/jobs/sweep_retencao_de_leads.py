"""O job da retencao do lead: transcricao de 12 meses, lead parado ha 24. TEC-207, D5."""

from typing import Any

from mobia.domain.titular.retencao import (
    LOTE_PADRAO_DE_TRANSCRICOES,
    anonimizar_leads_vencidos,
    cumprir_eliminacoes_vencidas,
    esvaziar_transcricoes_vencidas,
)

SWEEP_RETENCAO_DE_LEADS_JOB = "sweep_retencao_de_leads"


async def sweep_retencao_de_leads(
    ctx: dict[str, Any], lote: int = LOTE_PADRAO_DE_TRANSCRICOES
) -> int:
    """Fino de proposito, como `sweep_retencao_auditoria`.

    Chama as tres funcoes de `domain/titular/retencao.py` nesta ordem -- e a
    ordem importa: cumprir uma ELIMINACAO vencida primeiro evita que ela seja
    contada de novo por `anonimizar_leads_vencidos` (o par que ela cumpre pode
    ser o mesmo que estaria parado ha 24 meses), e as duas rodam antes de
    `esvaziar_transcricoes_vencidas` para que um lead anonimizado nesta
    mesma passagem ja tenha o conteudo zerado por `anonimizacao.py`, e nao
    pague o custo de ser varrido de novo por conteudo que ja sumiu.

    O rastro da passagem sao as tres linhas de log que cada funcao emite, e
    nao este retorno, que o ARQ descarta (`keep_result=0`).
    """
    session_factory = ctx["session_factory"]
    armazem = ctx["armazem"]
    cumpridas = await cumprir_eliminacoes_vencidas(session_factory, armazem)
    anonimizados = await anonimizar_leads_vencidos(session_factory, armazem, lote=lote)
    esvaziadas = await esvaziar_transcricoes_vencidas(session_factory, armazem, lote=lote)
    return cumpridas + anonimizados + esvaziadas
