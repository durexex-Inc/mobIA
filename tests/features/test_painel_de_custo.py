"""Criterios de aceite da TEC-191 como testes executaveis. RF-17, RN-17.4, RNF-06.

Os quatro cenarios do Gherkin, contra banco: a telemetria e semeada como a
TEC-126 a grava -- uma linha por resposta do agente, com o custo ja calculado
--, e o painel so a agrega. Mais as bordas da D2 e da D3.

O periodo e agosto de 2026 com 30 dias (01 a 30), para que o orcamento do
periodo seja o mensal inteiro, como no terceiro cenario da card.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/metricas/custo-ia"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-30"}
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
FORA = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _bearer(papel: str = "GERENTE") -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _resposta(
    session: AsyncSession,
    *,
    conversa: str,
    custo: Decimal | None,
    canal: str = "whatsapp",
    modelo: str = "claude-sonnet-5",
    em: datetime = DENTRO,
    tokens_in: int = 1000,
    tokens_out: int = 100,
) -> None:
    """Uma resposta do agente e a telemetria dela, como a TEC-126 grava."""
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=canal,
            provider_message_id=None,
            conversation_key=conversa,
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=None,
            created_at=em,
        )
    )
    await session.flush()
    session.add(
        MessageTelemetry(
            message_id=identificador,
            model=modelo,
            subagent="classificador",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=custo,
            latency_ms=900,
            created_at=em,
        )
    )
    await session.commit()


async def _qualificado(session: AsyncSession, conversa: str, *, em: datetime = DENTRO) -> None:
    session.add(
        LeadQualification(
            channel="whatsapp", conversation_key=conversa, intencao="COMPRA", qualificado_em=em
        )
    )
    await session.commit()


async def _orcamento(client: AsyncClient, mensal: float) -> None:
    resposta = await client.patch(
        "/api/v1/configuracao/agente",
        json={"orcamentoMensalUsd": mensal},
        headers=_bearer("ADMIN"),
    )
    assert resposta.status_code == 200, resposta.text


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_os_quatro_indicadores_com_50_conversas(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1."""
    for i in range(50):
        await _resposta(session, conversa=f"55119{i:08d}", custo=Decimal("0.010000"))
    for i in range(5):
        await _qualificado(session, f"55119{i:08d}")

    corpo = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()

    assert corpo["custoTotalUsd"] == 0.5
    assert corpo["custoPorConversaUsd"] == 0.01
    assert corpo["custoPorLeadQualificadoUsd"] == 0.1
    assert corpo["tokensPorModelo"] == {
        "claude-sonnet-5": {
            "entrada": 50_000,
            "saida": 5_000,
            "cacheLeitura": 0,
            "cacheEscrita": 0,
        }
    }
    assert corpo["conversas"] == 50
    assert corpo["leadsQualificados"] == 5
    assert corpo["alvoPorLeadQualificadoUsd"] == 0.12
    assert corpo["acimaDoAlvo"] is False


async def test_dez_mensagens_somando_0_84_dao_0_84(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 2: soma exata, sem arredondamento de float no caminho."""
    for _ in range(10):
        await _resposta(session, conversa="5511911112222", custo=Decimal("0.084000"))

    corpo = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()

    assert corpo["custoTotalUsd"] == 0.84


async def test_orcamento_de_100_com_80_gastos_acende_o_alerta(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 3: 30 dias, orcamento mensal de 100, gasto de 80."""
    await _orcamento(client, 100)
    await _resposta(session, conversa="5511911112222", custo=Decimal("80"))

    orcamento = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()["orcamento"]

    assert orcamento == {
        "mensalUsd": 100.0,
        "doPeriodoUsd": 100.0,
        "consumidoUsd": 80.0,
        "consumidoPct": 80.0,
        "alerta": True,
    }


async def test_periodo_sem_conversa_zera_sem_erro(client: AsyncClient, banco_limpo: None) -> None:
    """Cenario 4: 200, total zero, medias nulas, nada por modelo."""
    resposta = await client.get(ROTA, params=PERIODO, headers=_bearer())

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["custoTotalUsd"] == 0
    assert corpo["custoPorConversaUsd"] is None
    assert corpo["custoPorLeadQualificadoUsd"] is None
    assert corpo["tokensPorModelo"] == {}
    assert corpo["acimaDoAlvo"] is None
    assert corpo["orcamento"] is None


# --- as bordas -----------------------------------------------------------------


async def test_o_que_caiu_fora_do_periodo_nao_entra(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D1: o instante do gasto decide, e nao o nascimento da conversa."""
    await _resposta(session, conversa="5511911112222", custo=Decimal("1"), em=DENTRO)
    await _resposta(session, conversa="5511911112222", custo=Decimal("5"), em=FORA)

    corpo = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()

    assert corpo["custoTotalUsd"] == 1.0


async def test_mensagem_sem_preco_e_contada_a_parte(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D2: fora do total, e o numero diz quantas ficaram de fora."""
    await _resposta(session, conversa="5511911112222", custo=Decimal("0.5"))
    await _resposta(session, conversa="5511911112222", custo=None, modelo="modelo-sem-preco")

    corpo = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()

    assert corpo["custoTotalUsd"] == 0.5
    assert corpo["mensagensSemPreco"] == 1
    assert set(corpo["tokensPorModelo"]) == {"claude-sonnet-5", "modelo-sem-preco"}


async def test_o_filtro_de_canal_nao_muda_o_consumo_do_orcamento(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D3: o orcamento e da operacao inteira."""
    await _orcamento(client, 100)
    await _resposta(session, conversa="5511911112222", custo=Decimal("70"), canal="whatsapp")
    await _resposta(session, conversa="sessao-web-1", custo=Decimal("15"), canal="web")

    corpo = (await client.get(ROTA, params={**PERIODO, "canal": "web"}, headers=_bearer())).json()

    assert corpo["custoTotalUsd"] == 15.0
    assert corpo["orcamento"]["consumidoUsd"] == 85.0
    assert corpo["orcamento"]["alerta"] is True


async def test_acima_do_alvo(session: AsyncSession, client: AsyncClient, banco_limpo: None) -> None:
    await _resposta(session, conversa="5511911112222", custo=Decimal("0.30"))
    await _qualificado(session, "5511911112222")

    corpo = (await client.get(ROTA, params=PERIODO, headers=_bearer())).json()

    assert corpo["custoPorLeadQualificadoUsd"] == 0.3
    assert corpo["acimaDoAlvo"] is True


async def test_corretor_nao_ve_o_painel(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.get(ROTA, params=PERIODO, headers=_bearer("CORRETOR"))
    assert resposta.status_code == 403
