"""O dossie montado a partir das quatro tabelas, e o resumo de volta cifrado."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.repositorio import (
    carregar_dossie,
    gravar_resumo,
    registrar_handoff,
)
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.infra.crypto import decrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def test_dossie_de_handoff_inexistente_e_none(session: AsyncSession) -> None:
    assert await carregar_dossie(session, handoff_id=uuid.uuid4()) is None


async def test_dossie_traz_os_numeros_das_quatro_tabelas(
    session: AsyncSession, semear_lead_completo
) -> None:
    """Este e o segundo cenario do Gherkin, afirmado no dossie.

    Afirmar sobre a prosa exigiria o modelo real no CI. Como o modelo so ve o
    dossie (D5), um numero certo aqui e a unica maneira de um numero certo
    sair do outro lado -- ver a L3 do desenho.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    dossie = await carregar_dossie(session, handoff_id=handoff_id)

    assert dossie is not None
    assert dossie.score_total == 72
    assert dossie.faixa_max_centavos == 60_000_000
    assert len(dossie.imoveis) == 3


async def test_gravar_resumo_cifra_em_repouso(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()

    await gravar_resumo(
        session, handoff_id=registro.id, texto="## Quem e o lead\nfulano", modelo="claude-sonnet-5"
    )
    await session.commit()

    bruto = (
        await session.execute(select(Handoff.resumo).where(Handoff.id == registro.id))
    ).scalar_one()
    assert bruto is not None
    assert b"Quem e o lead" not in bruto
    assert decrypt(bruto, aad_do_resumo_de_handoff(registro.id)) == "## Quem e o lead\nfulano"


async def test_o_aad_amarra_o_resumo_ao_proprio_handoff(session: AsyncSession) -> None:
    """Mover o ciphertext para outra linha tem de falhar a decifra."""
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    await gravar_resumo(session, handoff_id=registro.id, texto="segredo", modelo="m")
    await session.commit()

    bruto = (
        await session.execute(select(Handoff.resumo).where(Handoff.id == registro.id))
    ).scalar_one()

    from mobia.infra.crypto import DecryptionError

    with pytest.raises(DecryptionError):
        decrypt(bruto, aad_do_resumo_de_handoff(uuid.uuid4()))
