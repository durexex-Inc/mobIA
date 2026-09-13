"""O turno cala quando um corretor assumiu a conversa. TEC-179, RN-16.4.

Espelha `tests/integration/test_turno_optout.py` na forma -- mesmas fixtures
(`rodar_turno`, os dubles de `tests/conftest.py`) --, mas exercita a guarda de
atendimento humano em vez da de opt-out. So os tres cenarios do Gherkin desta
task: a saida barata do topo, a mensagem do lead que continua registrada, e a
devolucao que reabre o turno.

A armadilha do setup: `rodar_turno` chama `executar_turno(get_sessionmaker(),
...)`, e o turno abre sessoes proprias. `assumir` (e `devolver`) tem de estar
COMMITADO antes de `rodar_turno` rodar, ou a guarda le um banco sem o estado
que o teste acabou de escrever.
"""

import uuid

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE
from sqlalchemy import func, select

from mobia.domain.atendimento.repositorio import assumir, devolver
from mobia.domain.messages.models import Message

pytestmark = pytest.mark.asyncio


async def test_conversa_assumida_o_turno_nao_responde(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Primeiro cenario do Gherkin. O desfecho e `atendimento_humano`."""
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    linha = await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    assert linha is not None
    await session.commit()

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "atendimento_humano"
    assert outbound.entregues == []
    # A saida e ANTES do modelo -- e isso que faz a guarda ser barata.
    assert classificador.chamadas == 0


async def test_a_mensagem_do_lead_continua_registrada(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Segundo cenario do Gherkin -- e ele passa SEM codigo novo.

    A mensagem e gravada pelo webhook, que commita o lote antes sequer de
    enfileirar o job (`api/routes/whatsapp.py`); o `process_message` so
    reivindica a linha e a le. Quando `executar_turno` roda, o registro ja
    esta commitado -- a saida antecipada nao tem como alcanca-lo.

    Este teste existe para provar que continua assim, nao para construir
    nada. Se ele algum dia reprovar, alguem moveu o registro para depois do
    turno e o silencio passou a comer mensagem do lead.
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "atendimento_humano"
    total = (await session.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 1, "a fala do lead continua gravada -- o silencio nao apaga nada"


async def test_devolvida_o_turno_volta_a_responder(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Prova que a guarda le o estado CORRENTE."""
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    devolvida = await devolver(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    assert devolvida is not None
    await session.commit()

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues != []
    assert classificador.chamadas == 1
