"""Assumir, devolver, e a pergunta que as quatro guardas fazem. TEC-179."""

import uuid

import pytest

from mobia.domain.atendimento.repositorio import (
    assumir,
    devolver,
    esta_silenciada,
    esta_silenciada_por_mensagem,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message

pytestmark = pytest.mark.asyncio

CHANNEL = "whatsapp"
CHAVE = "5511988887777"


async def test_sem_linha_nenhuma_a_conversa_nao_esta_silenciada(
    session, semear_corretor, banco_limpo
):
    """O estado default e "o agente pode falar" -- mesma forma do opt-out."""
    assert not await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_assumir_silencia(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    assert (
        await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
        is not None
    )
    assert await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_devolver_devolve_a_voz_ao_agente(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert (
        await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
        is not None
    )
    assert not await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_outro_corretor_nao_assume_o_que_ja_tem_dono(session, semear_corretor, banco_limpo):
    """O 409 do SRS: "ja assumida por outro"."""
    paulo = (await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")).id
    marina = (await semear_corretor(email=f"marina-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)
    assert (
        await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=marina) is None
    )


async def test_reassumir_pela_mesma_pessoa_nao_move_o_carimbo(
    session, semear_corretor, banco_limpo
):
    """D3: idempotente, e `assumido_em` fica onde estava.

    Mesmo argumento que a D8 da TEC-178 faz sobre `aceito_em`: um carimbo que
    anda para frente faria o corretor parecer ter pegado a conversa mais tarde
    do que pegou. Este teste falharia se o `ON CONFLICT` gravasse `agora` sem
    condicao -- os dois `datetime.now(UTC)` das duas chamadas nao coincidem.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    primeiro = await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    )
    assert primeiro is not None
    segundo = await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    )
    assert segundo is not None
    assert segundo.assumido_em == primeiro.assumido_em


async def test_depois_de_devolvida_qualquer_um_reassume(session, semear_corretor, banco_limpo):
    """E a linha e reusada -- o UNIQUE impede uma segunda."""
    paulo = (await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")).id
    marina = (await semear_corretor(email=f"marina-{uuid.uuid4().hex[:8]}@ex.com")).id
    primeiro = await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)
    assert primeiro is not None
    await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)

    segundo = await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=marina)
    assert segundo is not None
    assert segundo.assumido_por == marina
    # O carimbo ANDA aqui, ao contrario do teste acima: e um assumir novo.
    assert segundo.assumido_em > primeiro.assumido_em
    assert await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_devolver_o_que_ninguem_assumiu_e_recusado(session, semear_corretor, banco_limpo):
    """Nao e 200 silencioso: devolver exige que alguem tenha assumido."""
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    assert (
        await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
        is None
    )


async def test_devolver_duas_vezes_e_recusado_na_segunda(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert (
        await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
        is not None
    )
    assert (
        await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
        is None
    )


async def test_por_mensagem_resolve_o_par_e_responde_o_mesmo(session, semear_corretor, banco_limpo):
    """A forma que o `GuardedOutbound.send` precisa -- so tem o message_id."""
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CHANNEL,
        conversation_key=CHAVE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSED",
    )
    session.add(mensagem)
    await session.flush()

    assert not await esta_silenciada_por_mensagem(session, mensagem.id)
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert await esta_silenciada_por_mensagem(session, mensagem.id)


async def test_mensagem_inexistente_nao_esta_silenciada(session, semear_corretor, banco_limpo):
    """Mesma decisao de `esta_em_optout_por_mensagem`: sem lead, nada a barrar.

    Recusar o envio aqui esconderia o defeito real -- um `message_id` que nao
    existe e problema de quem chamou, nao uma conversa assumida.
    """
    assert not await esta_silenciada_por_mensagem(session, uuid.uuid4())
