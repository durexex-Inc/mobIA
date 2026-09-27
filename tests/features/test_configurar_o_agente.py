"""Criterios de aceite da TEC-198 como testes executaveis. RF-19, RN-19.3, CA-19.1.

Os quatro cenarios do Gherkin, contra banco e sem reiniciar nada: a
configuracao e gravada pela rota e lida pelo proximo recalculo, turno ou
varredura -- no mesmo processo, sem cache a invalidar (D1 do desenho). Mais a
cadencia (D5), a trilha (D1) e o recorte por papel.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.agente.turno import TEXTO_DO_LIMITE_DE_PERGUNTAS
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.configuracao.repositorio import configuracao_vigente
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.followup.cadencia import cadencia_de, intervalo_minimo
from mobia.domain.followup.repositorio import candidatos_a_followup
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.usuarios import tokens
from mobia.infra.crypto import aad_de, encrypt

ROTA = "/api/v1/configuracao/agente"
# Os de `rodar_turno`, em `tests/conftest.py`.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _bearer(papel: str = "ADMIN", usuario: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        usuario or uuid.uuid4(),
        papel,
        mfa=papel == "ADMIN",
        corretor_id=None,
        settings=get_settings(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _qualificacao(session: AsyncSession, **campos: object) -> None:
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    base.update(campos)
    session.add(LeadQualification(**base))
    await session.commit()


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_alterar_o_peso_vale_no_proximo_recalculo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1: urgencia 25 -> 30, e o recalculo seguinte usa 30."""
    await _qualificacao(session)
    antes = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert antes is not None and antes.trilha is not None
    assert antes.trilha.urgencia == 25

    resposta = await client.patch(ROTA, json={"pesoUrgencia": 30}, headers=_bearer())
    depois = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert resposta.status_code == 200, resposta.text
    assert depois is not None and depois.trilha is not None
    assert depois.trilha.urgencia == 30
    assert "URGENCIA" in depois.trilha.causas


async def test_limite_de_6_perguntas_encaminha_na_setima(
    session: AsyncSession,
    client: AsyncClient,
    rodar_turno: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
) -> None:
    """Cenario 2: com o limite em 6 e seis perguntas feitas, a proxima nao sai.

    "Param na sexta pergunta" e a regra do `>` de `excedeu_o_teto`: a sexta e
    permitida, a setima nao -- como a oitava e a ultima com o limite padrao.
    Com o padrao, este mesmo turno sairia com a pergunta.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado antes")
    await _qualificacao(session, urgencia=None, perguntas_feitas=6)
    assert (
        await client.patch(ROTA, json={"tetoDePerguntas": 6}, headers=_bearer())
    ).status_code == 200
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert TEXTO_DO_LIMITE_DE_PERGUNTAS in entregador.entregues


async def test_peso_negativo_e_recusado_e_o_anterior_fica(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 3: 422 com a regra escrita, e a vigente continua a de antes."""
    resposta = await client.patch(ROTA, json={"pesoUrgencia": -5}, headers=_bearer())

    assert resposta.status_code == 422
    assert "peso de urgencia -5 fora da faixa" in resposta.json()["detail"]
    vigente = (await client.get(ROTA, headers=_bearer())).json()["configuracao"]
    assert vigente["pesoUrgencia"] == 25


async def test_o_historico_traz_autor_anterior_novo_e_instante(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 4. A primeira versao e comparada com o padrao, que valeu ate ela."""
    admin = uuid.uuid4()
    await client.patch(ROTA, json={"pesoUrgencia": 30}, headers=_bearer(usuario=admin))
    await client.patch(
        ROTA, json={"pesoUrgencia": 28, "nomeDoAssistente": "Ana"}, headers=_bearer(usuario=admin)
    )

    itens = (await client.get(f"{ROTA}/historico", headers=_bearer())).json()["itens"]

    assert len(itens) == 2
    recente, primeira = itens
    assert recente["autor"] == str(admin)
    assert datetime.fromisoformat(recente["em"]) >= datetime.fromisoformat(primeira["em"])
    assert {m["campo"]: (m["anterior"], m["novo"]) for m in recente["mudancas"]} == {
        "pesoUrgencia": (30, 28),
        "nomeDoAssistente": (None, "Ana"),
    }
    assert primeira["mudancas"] == [{"campo": "pesoUrgencia", "anterior": 25, "novo": 30}]


# --- o que o desenho acrescentou -----------------------------------------------


async def test_nada_mudou_nada_e_gravado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.patch(ROTA, json={"pesoUrgencia": 25}, headers=_bearer())

    assert resposta.json()["alterados"] == []
    assert (await client.get(f"{ROTA}/historico", headers=_bearer())).json()["itens"] == []


async def test_a_trilha_registra_cada_campo_sem_o_valor(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await client.patch(ROTA, json={"pesoUrgencia": 30, "tom": "FORMAL"}, headers=_bearer())

    eventos = (
        (
            await session.execute(
                select(EventoAuditoria).where(
                    EventoAuditoria.acao == Acao.CONFIGURACAO_ALTERADA.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(e.campo for e in eventos) == ["pesoUrgencia", "tom"]
    assert all(e.entidade == "configuracao_agente" for e in eventos)
    assert "30" not in str([e.detalhes for e in eventos])


async def test_a_cadencia_encurtada_acha_o_lead_que_o_corte_antigo_escondia(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D5: com o primeiro intervalo QUENTE em 1h, um lead calado ha 90 minutos
    vira candidato -- com o corte da constante (2h) ele nao passaria."""
    ancora = datetime.now(UTC) - timedelta(minutes=90)
    await _qualificacao(session, temperatura="QUENTE")
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"id.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            status=MessageStatus.PROCESSED,
            created_at=ancora,
        )
    )
    await session.commit()
    agora = datetime.now(UTC)
    assert await candidatos_a_followup(session, agora=agora) == []

    resposta = await client.patch(
        ROTA,
        json={"cadencia": {"QUENTE": [1, 24, 72, 168], "MORNO": [24, 96, 240], "FRIO": [72, 336]}},
        headers=_bearer(),
    )
    cadencia = cadencia_de((await configuracao_vigente(session)).cadencia)
    candidatos = await candidatos_a_followup(
        session, agora=agora, corte_minimo=intervalo_minimo(cadencia)
    )

    assert resposta.status_code == 200, resposta.text
    assert [c.conversation_key for c in candidatos] == [CONVERSA]


@pytest.mark.parametrize("papel", ["GERENTE", "CORRETOR", "LEITURA"])
async def test_so_admin_configura_o_agente(
    client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    respostas = [
        await client.get(ROTA, headers=_bearer(papel)),
        await client.patch(ROTA, json={"pesoUrgencia": 30}, headers=_bearer(papel)),
        await client.get(f"{ROTA}/historico", headers=_bearer(papel)),
    ]
    assert [r.status_code for r in respostas] == [403, 403, 403]


# --- TEC-344: a aparencia do chat web ------------------------------------------


async def test_cor_e_posicao_do_botao_se_gravam_e_se_leem(
    client: AsyncClient, banco_limpo: None
) -> None:
    antes = (await client.get(ROTA, headers=_bearer())).json()
    assert antes["configuracao"]["corPrimaria"] == "#1D4ED8"
    assert antes["configuracao"]["posicaoDoBotao"] == "DIREITA"
    assert antes["limites"]["posicaoDoBotao"] == {"valores": ["DIREITA", "ESQUERDA"]}

    resposta = await client.patch(
        ROTA, json={"corPrimaria": "#0A7F5A", "posicaoDoBotao": "ESQUERDA"}, headers=_bearer()
    )

    assert resposta.status_code == 200, resposta.text
    assert sorted(resposta.json()["alterados"]) == ["corPrimaria", "posicaoDoBotao"]
    depois = (await client.get(ROTA, headers=_bearer())).json()["configuracao"]
    assert (depois["corPrimaria"], depois["posicaoDoBotao"]) == ("#0A7F5A", "ESQUERDA")


@pytest.mark.parametrize(
    "pedido",
    [
        {"corPrimaria": "#0A7F5AFF"},
        {"corPrimaria": None},
        {"posicaoDoBotao": None},
    ],
)
async def test_aparencia_invalida_e_recusada_e_nada_se_grava(
    client: AsyncClient, banco_limpo: None, pedido: dict[str, object]
) -> None:
    resposta = await client.patch(ROTA, json=pedido, headers=_bearer())

    assert resposta.status_code == 422, resposta.text
    historico = (await client.get(f"{ROTA}/historico", headers=_bearer())).json()
    assert historico["itens"] == []


async def test_posicao_fora_do_vocabulario_e_recusada_na_borda(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.patch(ROTA, json={"posicaoDoBotao": "CIMA"}, headers=_bearer())

    assert resposta.status_code == 422, resposta.text
