"""O job da retencao do lead: transcricao de 12 meses, lead parado ha 24. TEC-207, D5."""

from typing import Any

import structlog

from mobia.domain.titular.retencao import (
    LOTE_PADRAO_DE_LEADS,
    LOTE_PADRAO_DE_TRANSCRICOES,
    anonimizar_leads_vencidos,
    cumprir_eliminacoes_vencidas,
    esvaziar_transcricoes_vencidas,
)

log = structlog.get_logger(__name__)

SWEEP_RETENCAO_DE_LEADS_JOB = "sweep_retencao_de_leads"


async def sweep_retencao_de_leads(
    ctx: dict[str, Any],
    lote: int = LOTE_PADRAO_DE_TRANSCRICOES,
    lote_de_leads: int = LOTE_PADRAO_DE_LEADS,
) -> int:
    """Fino de proposito, como `sweep_retencao_auditoria`.

    Chama as tres funcoes de `domain/titular/retencao.py` nesta ordem --
    cumprir uma ELIMINACAO vencida primeiro, depois anonimizar quem parou ha
    24 meses, por ultimo esvaziar transcricao de 12 meses. A ordem decide
    QUAL funcao processa um lead que se encaixa em mais de uma regra no
    mesmo dia: um par que ja tinha uma ELIMINACAO aberta e vencida e cumprido
    por `cumprir_eliminacoes_vencidas`, e some da consulta de
    `anonimizar_leads_vencidos` (que exige `identidades_de_lead`, apagada
    pela anonimizacao) antes dela rodar -- sem essa ordem, as duas
    poderiam competir pelo mesmo par. Pela mesma razao, as duas rodam antes
    de `esvaziar_transcricoes_vencidas`: um lead anonimizado nesta mesma
    passagem ja tem o conteudo zerado por `anonimizacao.py`, e a varredura de
    transcricao so re-visita linhas que ainda tem conteudo (ver o `WHERE` de
    `_SELECIONAR_LOTE_DE_MENSAGENS_VENCIDAS`), entao ela nao paga o custo de
    reprocessar quem ja foi.

    **Cada uma das tres roda mesmo que a anterior tenha falhado por
    inteiro.** Cada chamada esta no seu proprio `try/except Exception`: se
    `cumprir_eliminacoes_vencidas` levantar antes mesmo do laco por item
    comecar (por exemplo, o SELECT de `vencidas` falhando por uma
    instabilidade transitoria do banco), isso nao impede
    `anonimizar_leads_vencidos` nem `esvaziar_transcricoes_vencidas` de
    rodar na mesma passagem -- a etapa que falhou loga
    `titular.sweep_retencao_etapa_falhou` com o nome dela, e a proxima
    passagem do cron tenta de novo. Isto e alem da resiliencia por ITEM que
    `anonimizar_leads_vencidos` e `cumprir_eliminacoes_vencidas` ja tem
    internamente (ver as docstrings delas) -- aqui a preocupacao e uma etapa
    inteira falhar antes do laco dela sequer comecar.

    **Cada uma das tres tambem tem um teto de trabalho por passagem**
    (`max_lotes` em `esvaziar_transcricoes_vencidas` e em
    `anonimizar_leads_vencidos`; `lote` em `cumprir_eliminacoes_vencidas`,
    que poda a lista em vez de reconsultar) -- e por isso este job registra
    um `timeout` proprio, maior que o `job_timeout` global do worker. Ver o
    comentario de `func(sweep_retencao_de_leads, ...)` em `workers/main.py`
    para a conta.

    `lote_de_leads` e separado de `lote`: `anonimizar_leads_vencidos` teria,
    sem ele, herdado o `lote` de transcricao (500) no lugar do proprio
    default (100) -- unidades de trabalho bem mais caras (um lead inteiro
    anonimizado contra uma linha de mensagem esvaziada), que merecem um
    tamanho de lote proprio.

    O rastro da passagem sao as linhas de log que cada funcao emite, e nao
    este retorno, que o ARQ descarta (`keep_result=0`).
    """
    session_factory = ctx["session_factory"]
    armazem = ctx["armazem"]
    total = 0
    for nome, corrotina in (
        ("cumprir_eliminacoes_vencidas", cumprir_eliminacoes_vencidas(session_factory, armazem)),
        (
            "anonimizar_leads_vencidos",
            anonimizar_leads_vencidos(session_factory, armazem, lote=lote_de_leads),
        ),
        (
            "esvaziar_transcricoes_vencidas",
            esvaziar_transcricoes_vencidas(session_factory, armazem, lote=lote),
        ),
    ):
        try:
            total += await corrotina
        except Exception:
            log.warning("titular.sweep_retencao_etapa_falhou", etapa=nome, exc_info=True)
    return total
