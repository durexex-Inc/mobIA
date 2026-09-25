"""A cascata: corretor alocado, senao o plantao mais antigo, senao ninguem."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.vocabulario import ATOR_AGENTE
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.notificacao.destinatario import destinatario_do_handoff, gerente_ativo

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _handoff(session: AsyncSession) -> Handoff:
    registro = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    return (await session.execute(select(Handoff).where(Handoff.id == registro.id))).scalar_one()


async def test_sem_corretor_nenhum_devolve_none(session: AsyncSession) -> None:
    """D4: nao ha para quem mandar, e fingir que mandou seria pior."""
    assert await destinatario_do_handoff(session, handoff=await _handoff(session)) is None


async def test_sem_alocado_devolve_o_plantao(session: AsyncSession, semear_corretor) -> None:
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    await semear_corretor(email="comum@x.com", plantao=False)

    escolhido = await destinatario_do_handoff(session, handoff=await _handoff(session))

    assert escolhido is not None
    assert escolhido.id == plantao.id


async def test_com_dois_plantoes_devolve_o_mais_antigo(
    session: AsyncSession, semear_corretor
) -> None:
    """D3: a card nao escreveu a regra, e esta card precisa de UMA resposta.

    O mais antigo e o que nao muda quando alguem cadastra um plantao novo.
    """
    agora = datetime.now(UTC)
    antigo = await semear_corretor(
        email="antigo@x.com", plantao=True, criado_em=agora - timedelta(days=2)
    )
    await semear_corretor(email="novo@x.com", plantao=True, criado_em=agora)

    escolhido = await destinatario_do_handoff(session, handoff=await _handoff(session))

    assert escolhido is not None
    assert escolhido.id == antigo.id


async def test_plantao_inativo_nao_recebe(session: AsyncSession, semear_corretor) -> None:
    await semear_corretor(email="plantao@x.com", plantao=True, ativo=False)

    assert await destinatario_do_handoff(session, handoff=await _handoff(session)) is None


async def test_alocado_ganha_do_plantao(session: AsyncSession, semear_corretor) -> None:
    """O ramo que hoje nunca roda em producao -- ver a L4 do desenho."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    alocado = await semear_corretor(email="alocado@x.com", plantao=False)

    handoff = await _handoff(session)
    handoff.corretor_id = alocado.id
    await session.commit()

    escolhido = await destinatario_do_handoff(session, handoff=handoff)

    assert escolhido is not None
    assert escolhido.id == alocado.id


async def test_alocado_inativo_cai_para_o_plantao(session: AsyncSession, semear_corretor) -> None:
    """Corretor desativado nao recebe alocacao nova -- e nem notificacao velha."""
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    alocado = await semear_corretor(email="saiu@x.com", plantao=False, ativo=False)

    handoff = await _handoff(session)
    handoff.corretor_id = alocado.id
    await session.commit()

    escolhido = await destinatario_do_handoff(session, handoff=handoff)

    assert escolhido is not None
    assert escolhido.id == plantao.id


async def test_sem_gerente_nenhum_devolve_none(session: AsyncSession) -> None:
    """A ausencia de gerente e estado previsto -- quem chama decide o resto."""
    assert await gerente_ativo(session) is None


async def test_com_um_gerente_devolve_ele(session: AsyncSession, semear_corretor) -> None:
    gerente = await semear_corretor(email="gerente@x.com", gerente=True)

    escolhido = await gerente_ativo(session)

    assert escolhido is not None
    assert escolhido.id == gerente.id


async def test_com_dois_gerentes_devolve_o_mais_antigo(
    session: AsyncSession, semear_corretor
) -> None:
    """O mais antigo e o que nao muda quando alguem cadastra outro gerente.

    Cadastrado por ultimo mas com `criado_em` mais antigo -- se a cascata
    usasse ordem de insercao, ou `ORDER BY criado_em DESC`, este teste
    escolheria o gerente errado.
    """
    agora = datetime.now(UTC)
    await semear_corretor(email="novo@x.com", gerente=True, criado_em=agora)
    antigo = await semear_corretor(
        email="antigo@x.com", gerente=True, criado_em=agora - timedelta(days=2)
    )

    escolhido = await gerente_ativo(session)

    assert escolhido is not None
    assert escolhido.id == antigo.id


async def test_gerente_inativo_nao_conta(session: AsyncSession, semear_corretor) -> None:
    await semear_corretor(email="gerente@x.com", gerente=True, ativo=False)

    assert await gerente_ativo(session) is None


async def test_gerente_e_plantao_sao_cascatas_independentes(
    session: AsyncSession, semear_corretor
) -> None:
    """Um corretor pode ser gerente e plantao ao mesmo tempo (D7, Emenda E-03 da RN-16.3).

    As duas funcoes resolvem o mesmo corretor cada uma pela sua propria
    coluna -- a prova de que uma cascata nao influencia a outra.
    """
    corretor = await semear_corretor(email="dobrado@x.com", plantao=True, gerente=True)

    escolhido_plantao = await destinatario_do_handoff(session, handoff=await _handoff(session))
    escolhido_gerente = await gerente_ativo(session)

    assert escolhido_plantao is not None
    assert escolhido_plantao.id == corretor.id
    assert escolhido_gerente is not None
    assert escolhido_gerente.id == corretor.id
