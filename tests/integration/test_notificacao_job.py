"""O job do resumo encadeia a notificacao, e o job da notificacao chama `notificar`.

TEC-177, Task 5.
"""

import logging
import uuid
from typing import Any

import pytest

from mobia.domain.handoff.resumo import MARCADORES, ResumoDeHandoffGerado
from mobia.workers.jobs.gerar_resumo import gerar_resumo
from mobia.workers.jobs.notificar import NOTIFICAR_JOB, notificar_corretor


class _RedatorFalso:
    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        return ResumoDeHandoffGerado(
            texto="\n".join(f"{m}\nconteudo" for m in MARCADORES),
            modelo="claude-sonnet-5",
            tokens_in=900,
            tokens_out=400,
            latency_ms=120,
            comprimiu=False,
        )


class _RedisEspiao:
    """Duble do pool ARQ: so registra o enqueue, nao fala com Redis de verdade."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(
        self, function: str, *args: Any, _job_id: str | None = None, **kwargs: Any
    ) -> object:
        self.chamadas.append((function, args, _job_id))
        return object()


class _RedisQueFalha:
    """Duble que simula o Redis fora do ar -- o enqueue nunca pode propagar."""

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> object:
        raise ConnectionError("redis indisponivel")


async def test_resumo_gerado_enfileira_a_notificacao(semear_lead_completo) -> None:
    """Caminho feliz: o resumo grava, e o job enfileira `NOTIFICAR_JOB` mesmo assim."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    redis = _RedisEspiao()
    ctx: dict[str, Any] = {"redator": _RedatorFalso(), "redis": redis}

    resultado = await gerar_resumo(ctx, str(handoff_id))

    assert resultado == "gravado"
    assert len(redis.chamadas) == 1
    funcao, args, job_id = redis.chamadas[0]
    assert funcao == NOTIFICAR_JOB
    assert args == (str(handoff_id),)
    assert job_id == f"notificar:{handoff_id}"


async def test_resumo_sem_dossie_enfileira_a_notificacao_do_mesmo_jeito() -> None:
    """D2: o handoff sem resumo e o que MAIS precisa do aviso, nao um caso a pular.

    Ate a TEC-176, uma falha do redator deixava `gerar_resumo` sem gravar
    nada e este teste exercitava esse caminho com `_RedatorQueFalha`. Depois
    da TEC-176 (fallback deterministico -- RN-15.4), essa mesma falha grava o
    template e devolve "gravado" (ver `test_geracao_de_resumo.py` e
    `domain/handoff/geracao.gerar_resumo`); a UNICA falha que ainda deixa
    `gerar_resumo` sem gravar e o dossie ausente, entao e esse o caminho que
    prova a decisao "enfileira mesmo sem resumo".

    A forma ingenua (`if gravou: enfileira`) inverteria essa decisao em
    silencio -- este teste existe para que a inversao quebre a suite, nao
    para so documentar a intencao em prosa.
    """
    handoff_id = uuid.uuid4()
    redis = _RedisEspiao()
    ctx: dict[str, Any] = {"redator": _RedatorFalso(), "redis": redis}

    resultado = await gerar_resumo(ctx, str(handoff_id))

    assert resultado == "sem_resumo"
    assert len(redis.chamadas) == 1
    funcao, args, job_id = redis.chamadas[0]
    assert funcao == NOTIFICAR_JOB
    assert args == (str(handoff_id),)
    assert job_id == f"notificar:{handoff_id}"


async def test_falha_no_enfileiramento_nao_derruba_o_job_do_resumo(
    semear_lead_completo, caplog: pytest.LogCaptureFixture
) -> None:
    """O resumo ja esta gravado quando o enqueue acontece -- uma falha do Redis
    ali perde so a notificacao, nunca o trabalho que `_gerar` ja fez.

    A asserta sobre `caplog` prova que o `except` de fato loga e nao so
    engole a falha em silencio -- sem ela, um `except Exception: pass` no
    lugar do `log.warning` deixaria este teste verde do mesmo jeito.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    ctx: dict[str, Any] = {"redator": _RedatorFalso(), "redis": _RedisQueFalha()}

    with caplog.at_level(logging.WARNING):
        resultado = await gerar_resumo(ctx, str(handoff_id))

    assert resultado == "gravado"
    assert "notificacao.nao_agendada" in caplog.text
    # Agulha sem acento de proposito: o JSONRenderer serializa com
    # ensure_ascii=True, entao acento na asserta seria armadilha (TEC-289).
    assert "redis indisponivel" in caplog.text


class _CanalEspiao:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, str, str]] = []

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        self.recebidas.append((destino, assunto, corpo))


class _OutboundFalso:
    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        return True


async def test_job_de_notificacao_resolve_os_canais_do_ctx_e_chama_notificar(
    session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    corretor = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    canal = _CanalEspiao("email")
    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "canais_de_notificacao": (canal,),
        "outbound": _OutboundFalso(),
    }

    resultado = await notificar_corretor(ctx, str(handoff_id))

    assert resultado == "notificado"
    assert len(canal.recebidas) == 1
    assert canal.recebidas[0][0] == corretor.email


async def test_job_de_notificacao_devolve_aviso_manual_quando_nenhum_canal_aceita(
    session_factory, semear_handoff_com_resumo
) -> None:
    """Sem corretor cadastrado: `notificar` devolve False, e o job traduz isso
    num rotulo proprio para o log do ARQ, sem propagar excecao nenhuma."""
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "canais_de_notificacao": (_CanalEspiao("email"),),
        "outbound": _OutboundFalso(),
    }

    resultado = await notificar_corretor(ctx, str(handoff_id))

    assert resultado == "aviso_manual"
