"""A exportacao do handoff para o CRM. TEC-180, RN-16.5.

Os quatro cenarios do Gherkin da card, mais os dois que o desenho acrescentou:
a contagem que nao pode ser do ARQ (D3) e a exportacao desligada (D2).
"""

import logging
import uuid
from typing import Any

import pytest
from arq.worker import Retry
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.vocabulario import ATOR_AGENTE
from mobia.domain.crm.port import FalhaDeExportacao
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.workers.jobs.exportar_crm import exportar_crm
from mobia.workers.jobs.sweep_crm_pendentes import sweep_crm_pendentes


class _CrmEspiao:
    """Registra o que recebeu, e falha quantas vezes mandarem.

    `falhas` e um contador decrescente, e nao um booleano: o cenario que
    importa e "falha tres vezes e depois volta a responder", que e o terceiro
    do Gherkin.
    """

    nome = "espiao"

    def __init__(self, falhas: int = 0, motivo: str = "HTTP 503") -> None:
        self.falhas = falhas
        self.motivo = motivo
        self.recebidos: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def exportar(self, *, handoff_id: uuid.UUID, payload: dict[str, Any]) -> None:
        if self.falhas > 0:
            self.falhas -= 1
            raise FalhaDeExportacao(self.motivo)
        self.recebidos.append((handoff_id, payload))


class _RedisEspiao:
    def __init__(self) -> None:
        self.enfileirados: list[str] = []

    async def enqueue_job(self, nome: str, *args: str, **kwargs: object) -> None:
        self.enfileirados.append(args[0])


def _ctx(session_factory: Any, crm: Any, **extras: Any) -> dict[str, Any]:
    return {"session_factory": session_factory, "crm": crm, **extras}


async def _semear(session: AsyncSession, *, conversa: str) -> uuid.UUID:
    registro = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key=conversa,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    return registro.id


async def _linha(session: AsyncSession, handoff_id: uuid.UUID) -> Handoff:
    session.expire_all()
    return (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()


async def _marcar(session: AsyncSession, *, handoff_id: uuid.UUID, **campos: object) -> None:
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(**campos))
    await session.commit()


async def test_a_exportacao_entrega_o_payload_versionado_e_carimba(
    session, session_factory, banco_limpo
) -> None:
    """Primeiro cenario do Gherkin."""
    handoff_id = await _semear(session, conversa="5511900000101")
    crm = _CrmEspiao()

    resultado = await exportar_crm(_ctx(session_factory, crm), str(handoff_id))

    assert resultado == "exportado"
    assert crm.recebidos[0][0] == handoff_id
    # v2 desde a TEC-203 -- `lead.conversa` deixou de ser o telefone.
    assert crm.recebidos[0][1]["versao"] == 2
    linha = await _linha(session, handoff_id)
    assert linha.crm_sincronizado_em is not None


async def test_tres_falhas_alertam_e_nao_deixam_o_arq_decidir(
    session, session_factory, banco_limpo, caplog: pytest.LogCaptureFixture
) -> None:
    """Segundo cenario do Gherkin, e a D3 do desenho.

    **O que este teste protege e a ULTIMA linha do assert.** As duas primeiras
    falhas levantam `Retry`, que devolve o job a fila; a terceira NAO levanta,
    porque se levantasse o `job_try` estouraria o `max_tries` do ARQ e ele
    encerraria o job SEM chamar a corrotina -- nada marcaria a linha e nada
    emitiria o alerta.

    E o teste que reprova se alguem "simplificar" a contagem para
    `max_tries=3` na inscricao do job: essa mudanca parece equivalente, passa
    em todos os outros testes deste arquivo e reintroduz a perda silenciosa que
    a RN-16.5 proibe.
    """
    handoff_id = await _semear(session, conversa="5511900000102")
    crm = _CrmEspiao(falhas=99, motivo="HTTP 503")
    ctx = _ctx(session_factory, crm, settings=_settings_com_backoff_curto())

    for esperada in (1, 2):
        with pytest.raises(Retry):
            await exportar_crm(ctx, str(handoff_id))
        assert (await _linha(session, handoff_id)).crm_tentativas == esperada

    # A terceira NAO levanta.
    with caplog.at_level(logging.ERROR):
        resultado = await exportar_crm(ctx, str(handoff_id))

    assert resultado == "falhou"
    linha = await _linha(session, handoff_id)
    assert linha.crm_tentativas == 3
    assert linha.crm_ultimo_erro == "HTTP 503"
    assert linha.crm_sincronizado_em is None
    # "Falha permanente vira alerta" e o que a RN-16.5 pede, e o rotulo
    # devolvido nao prova isso: um `return "falhou"` sem o `log.error` deixaria
    # as assertas acima verdes. E o NOME do evento que o monitoramento externo
    # casa -- nao existe regra de alerta neste repositorio --, entao mudar o
    # nome e quebrar o alerta de alguem, e esta linha e o que avisa.
    assert "crm.exportacao_falhou_permanente" in caplog.text
    assert str(handoff_id) in caplog.text


async def test_o_backoff_cresce_entre_as_tentativas(session, session_factory, banco_limpo) -> None:
    """ "Backoff exponencial" da RN-16.5, no valor que o `Retry` carrega."""
    handoff_id = await _semear(session, conversa="5511900000103")
    ctx = _ctx(session_factory, _CrmEspiao(falhas=99), settings=_settings_com_backoff_curto())

    esperas = []
    for _ in (1, 2):
        with pytest.raises(Retry) as capturada:
            await exportar_crm(ctx, str(handoff_id))
        esperas.append(capturada.value.defer_score)

    assert esperas[1] == esperas[0] * 2


async def test_handoff_ja_sincronizado_nao_vai_de_novo(
    session, session_factory, banco_limpo
) -> None:
    """Terceiro cenario do Gherkin, na metade que e nossa.

    A outra metade -- a resposta perdida depois de o CRM ja ter gravado -- so o
    consumidor fecha, com a chave de idempotencia. E a lacuna L1 do desenho.
    """
    handoff_id = await _semear(session, conversa="5511900000104")
    crm = _CrmEspiao()
    ctx = _ctx(session_factory, crm)

    await exportar_crm(ctx, str(handoff_id))
    resultado = await exportar_crm(ctx, str(handoff_id))

    assert resultado == "ja_sincronizado"
    assert len(crm.recebidos) == 1


async def test_a_varredura_reabre_a_rodada_esgotada_e_o_envio_conclui(
    session, session_factory, banco_limpo
) -> None:
    """Terceiro cenario do Gherkin, inteiro: o webhook volta e a entrega sai."""
    handoff_id = await _semear(session, conversa="5511900000105")
    await _marcar(session, handoff_id=handoff_id, crm_tentativas=3)
    redis = _RedisEspiao()
    crm = _CrmEspiao()

    total = await sweep_crm_pendentes(_ctx(session_factory, crm, redis=redis))

    assert total == 1
    assert redis.enfileirados == [str(handoff_id)]
    # A rodada nova comeca do zero -- e o que permite tres tentativas de novo.
    assert (await _linha(session, handoff_id)).crm_tentativas == 0

    assert await exportar_crm(_ctx(session_factory, crm), str(handoff_id)) == "exportado"
    assert (await _linha(session, handoff_id)).crm_sincronizado_em is not None


async def test_a_varredura_nao_recolhe_rodada_em_voo(session, session_factory, banco_limpo) -> None:
    """`0 < crm_tentativas < 3` e uma rodada com `Retry` pendente na fila.

    Recolhe-la dispararia uma segunda rodada em paralelo com a primeira, e o
    CRM levaria dois POSTs do mesmo lead por conta nossa -- nao por falha dele.
    """
    handoff_id = await _semear(session, conversa="5511900000106")
    await _marcar(session, handoff_id=handoff_id, crm_tentativas=2)
    redis = _RedisEspiao()

    total = await sweep_crm_pendentes(_ctx(session_factory, _CrmEspiao(), redis=redis))

    assert total == 0
    assert redis.enfileirados == []


async def test_a_varredura_nao_recolhe_o_que_ja_foi_sincronizado(
    session, session_factory, banco_limpo
) -> None:
    handoff_id = await _semear(session, conversa="5511900000107")
    crm = _CrmEspiao()
    await exportar_crm(_ctx(session_factory, crm), str(handoff_id))
    redis = _RedisEspiao()

    total = await sweep_crm_pendentes(_ctx(session_factory, crm, redis=redis))

    assert total == 0


async def test_sem_porta_o_job_e_a_varredura_saem_cedo(
    session, session_factory, banco_limpo
) -> None:
    """D2: sem `CRM_WEBHOOK_URL` a exportacao esta desligada.

    A varredura precisa sair ANTES do banco: sem porta, todo handoff existente
    se encaixa no ramo "nunca tentou" e ela reenfileiraria a tabela inteira a
    cada ciclo de cron, para que cada job saisse com "desligado".
    """
    handoff_id = await _semear(session, conversa="5511900000108")
    redis = _RedisEspiao()

    assert await exportar_crm(_ctx(session_factory, None), str(handoff_id)) == "desligado"
    assert await sweep_crm_pendentes(_ctx(session_factory, None, redis=redis)) == 0
    assert redis.enfileirados == []
    assert (await _linha(session, handoff_id)).crm_sincronizado_em is None


async def test_handoff_que_sumiu_nao_derruba_o_job(session_factory, banco_limpo) -> None:
    """O job pode chegar depois de a linha sumir. Loga e sai, nao estoura."""
    resultado = await exportar_crm(_ctx(session_factory, _CrmEspiao()), str(uuid.uuid4()))

    assert resultado == "sem_handoff"


def _settings_com_backoff_curto() -> Any:
    """`get_settings()` com a base do backoff em centesimos de segundo.

    Nao e so velocidade: `Retry.defer_score` guarda milissegundos inteiros, e
    com a base de 30 s o teste do dobro funcionaria igual -- o que este valor
    evita e um `defer` de minutos ficar registrado no espiao e confundir quem
    ler o teste achando que algo esperou de verdade.
    """
    from mobia.app.config import get_settings

    settings = get_settings()
    return settings.model_copy(update={"crm_backoff_base_segundos": 0.01})
