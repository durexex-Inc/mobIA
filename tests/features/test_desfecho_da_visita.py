"""Criterios de aceite do TEC-374 como testes executaveis. RF-12, RN-12.4 e RN-12.5.

Os quatro cenarios do Gherkin da card. **O terceiro chega aqui na forma de
API**: ele diz "as acoes de realizado e nao comparecimento nao estao
disponiveis", que e afirmacao sobre a TELA, e a tela depende da TEC-323. O
correspondente construivel e o que esta card poe no dominio -- marcar antes da
hora e recusado --, e e ele que se exercita.

**O relogio destes testes e o de verdade.** A rota usa `datetime.now(UTC)`, e
nao ha injecao de relogio nela: o agendamento e semeado com `inicio` no
passado ou no futuro em relacao a agora, que e como a tela vai encontra-lo.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import _corretor
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.ciclo import PONTOS_POR_NAO_COMPARECIMENTO
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.auditoria import CAUSA_NAO_COMPARECIMENTO, CAUSA_PENALIDADE
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/agendamentos"
CANAL = "whatsapp"
CONVERSA = "5511911111111"


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _agendamento(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    status: str = StatusDoAgendamento.CONFIRMADO,
    daqui: timedelta = timedelta(hours=-2),
) -> uuid.UUID:
    """Um agendamento comecando `daqui` a partir de AGORA de verdade.

    Negativo e o caso comum destes testes -- a visita ja aconteceu, e o
    corretor esta marcando o desfecho dela.
    """
    inicio = datetime.now(UTC) + daqui
    identificador = uuid.uuid4()
    session.add(
        Agendamento(
            id=identificador,
            corretor_id=corretor_id,
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=None,
            tipo="VISITA_PRESENCIAL",
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status=status,
            reservado_ate=inicio,
            criado_em=inicio - timedelta(days=1),
            confirmado_em=(
                inicio - timedelta(days=1) if status == StatusDoAgendamento.CONFIRMADO else None
            ),
            motivo_da_alocacao="MATCH_EXATO",
        )
    )
    await session.commit()
    return identificador


async def _lead_com_score(session: AsyncSession) -> int:
    """Um lead qualificado, e o score dele antes de qualquer penalidade."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=60_000_000,
            regiao="zona sul",
            urgencia=Urgencia.IMEDIATA.value,
            forma_pagamento=FormaPagamento.A_VISTA.value,
        )
    )
    await session.commit()
    antes = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert antes is not None
    return int(antes.total)


async def _status_de(session: AsyncSession, identificador: uuid.UUID) -> str:
    return (
        await session.execute(select(Agendamento.status).where(Agendamento.id == identificador))
    ).scalar_one()


async def test_o_corretor_marca_a_visita_como_realizada(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1: fica REALIZADO, e o score do lead NAO muda.

    A segunda asserta e a que separa esta rota da vizinha -- sem ela, as duas
    poderiam penalizar e o teste do no-show continuaria verde.
    """
    corretor = await _corretor(session)
    antes = await _lead_com_score(session)
    agendamento = await _agendamento(session, corretor_id=corretor)

    resposta = await client.post(
        f"{ROTA}/{agendamento}/realizado", headers=_bearer("CORRETOR", corretor_id=corretor)
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == StatusDoAgendamento.REALIZADO
    assert await _status_de(session, agendamento) == StatusDoAgendamento.REALIZADO

    depois = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert depois is not None
    assert depois.total == antes


async def test_o_corretor_marca_nao_comparecimento_e_o_score_cai_quinze(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 2: NO_SHOW, score menos 15, e as duas causas na trilha.

    **A resposta carrega o custo** (D7): a tela precisa do numero para avisar
    antes de confirmar, e um 15 escrito a mao no frontend envelheceria no dia
    em que a RN-12.4 mudasse.
    """
    corretor = await _corretor(session)
    antes = await _lead_com_score(session)
    agendamento = await _agendamento(session, corretor_id=corretor)

    resposta = await client.post(
        f"{ROTA}/{agendamento}/nao-comparecimento",
        headers=_bearer("CORRETOR", corretor_id=corretor),
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == StatusDoAgendamento.NO_SHOW
    assert corpo["penalidade"] == PONTOS_POR_NAO_COMPARECIMENTO
    assert corpo["penalidadeTotal"] == PONTOS_POR_NAO_COMPARECIMENTO
    assert corpo["scoreNovo"] == antes - PONTOS_POR_NAO_COMPARECIMENTO

    assert await _status_de(session, agendamento) == StatusDoAgendamento.NO_SHOW

    ultima = (
        (
            await session.execute(
                select(LeadScoreAudit)
                .where(LeadScoreAudit.conversation_key == CONVERSA)
                .order_by(LeadScoreAudit.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert ultima is not None
    assert CAUSA_NAO_COMPARECIMENTO in ultima.causas
    assert CAUSA_PENALIDADE in ultima.causas


@pytest.mark.parametrize("acao", ["realizado", "nao-comparecimento"])
async def test_antes_da_hora_recusa_com_409_e_nao_muda_nada(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, acao: str
) -> None:
    """Cenario 3, na forma de API. Ver a docstring do modulo.

    **E a asserta do score que fecha o caso do no-show**: a penalidade e
    somada depois da transicao, entao uma guarda que recusasse no fim
    deixaria 15 pontos gravados sobre um desfecho que nao aconteceu.
    """
    corretor = await _corretor(session)
    antes = await _lead_com_score(session)
    agendamento = await _agendamento(session, corretor_id=corretor, daqui=timedelta(hours=2))

    resposta = await client.post(
        f"{ROTA}/{agendamento}/{acao}", headers=_bearer("CORRETOR", corretor_id=corretor)
    )

    assert resposta.status_code == 409
    assert "ainda não começou" in resposta.json()["detail"]
    assert await _status_de(session, agendamento) == StatusDoAgendamento.CONFIRMADO

    depois = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert depois is not None
    assert depois.total == antes


async def test_agendamento_cancelado_recusa_dizendo_que_foi_cancelado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 4: a recusa e dita como tal, e nao como erro generico.

    E a razao de `Recusado` ter ganhado `status_atual` (D3): `ORIGEM_ILEGAL`
    sozinho nao diz de qual origem ilegal se trata.
    """
    corretor = await _corretor(session)
    agendamento = await _agendamento(
        session, corretor_id=corretor, status=StatusDoAgendamento.CANCELADO
    )

    resposta = await client.post(
        f"{ROTA}/{agendamento}/realizado", headers=_bearer("CORRETOR", corretor_id=corretor)
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == "este agendamento já foi cancelado"


async def test_ja_marcado_recusa_dizendo_o_que_ja_aconteceu(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A segunda chamada nao e idempotente em silencio -- ela explica.

    Nao esta no Gherkin e e o caso que a tela mais vai produzir: dois cliques
    no mesmo botao, ou duas abas abertas.
    """
    corretor = await _corretor(session)
    agendamento = await _agendamento(session, corretor_id=corretor)

    primeira = await client.post(
        f"{ROTA}/{agendamento}/realizado", headers=_bearer("CORRETOR", corretor_id=corretor)
    )
    segunda = await client.post(
        f"{ROTA}/{agendamento}/realizado", headers=_bearer("CORRETOR", corretor_id=corretor)
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 409
    assert segunda.json()["detail"] == "esta visita já foi marcada como realizada"


async def test_o_corretor_nao_marca_a_visita_de_outro(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """ "So o corretor dono do agendamento", presa por teste."""
    dono = await _corretor(session)
    outro = await _corretor(session)
    agendamento = await _agendamento(session, corretor_id=dono)

    resposta = await client.post(
        f"{ROTA}/{agendamento}/realizado", headers=_bearer("CORRETOR", corretor_id=outro)
    )

    assert resposta.status_code == 403
    assert await _status_de(session, agendamento) == StatusDoAgendamento.CONFIRMADO


async def test_o_gerente_marca_a_visita_de_qualquer_corretor(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A outra metade da regra: "-- ou um gerente".

    Para ADMIN e GERENTE, agir em nome de terceiro e a funcao (Emenda E-05 a
    RN-16.4), e `exigir_dono` so morde o papel CORRETOR.
    """
    dono = await _corretor(session)
    agendamento = await _agendamento(session, corretor_id=dono)

    resposta = await client.post(f"{ROTA}/{agendamento}/realizado", headers=_bearer("GERENTE"))

    assert resposta.status_code == 200


async def test_id_que_nao_existe_e_404_e_nao_403(client: AsyncClient, banco_limpo: None) -> None:
    """A guarda de dono nao pode virar oraculo ao contrario.

    403 sobre um id inexistente diria "este id nao e seu" sobre um id que nao
    e de ninguem -- e transformaria a negativa num sinal de existencia.
    """
    corretor = uuid.uuid4()
    resposta = await client.post(
        f"{ROTA}/{uuid.uuid4()}/realizado", headers=_bearer("CORRETOR", corretor_id=corretor)
    )

    assert resposta.status_code == 404


@pytest.mark.parametrize("acao", ["realizado", "nao-comparecimento"])
async def test_leitura_nao_marca_desfecho(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, acao: str
) -> None:
    """`ATENDER_LEAD` e de ADMIN, GERENTE e CORRETOR -- e de mais ninguem."""
    corretor = await _corretor(session)
    agendamento = await _agendamento(session, corretor_id=corretor)

    resposta = await client.post(f"{ROTA}/{agendamento}/{acao}", headers=_bearer("LEITURA"))

    assert resposta.status_code == 403
    assert await _status_de(session, agendamento) == StatusDoAgendamento.CONFIRMADO
