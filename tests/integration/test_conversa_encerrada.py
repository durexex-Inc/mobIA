"""O ciclo de vida da conversa: encerrar, perguntar e reabrir. TEC-138.

Espelha `tests/integration/test_identificacao_fronteira.py` para a janela de
tempo (`agora` por parametro, sem congelar relogio) e
`tests/integration/test_turno_optout.py` para o padrao geral de teste de
repositorio contra a fixture `session`.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.repositorio import encerrar_conversa, esta_encerrada, reabrir_conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status

CANAL = "whatsapp"
CONVERSA = "5511900001111"


async def test_sem_linha_nao_esta_encerrada(session: AsyncSession) -> None:
    """Estado default e "pode receber", igual ao de `esta_em_optout` -- sem
    nenhum encerramento gravado, a conversa nao esta encerrada.
    """
    assert (
        await esta_encerrada(
            session, channel=CANAL, conversation_key=CONVERSA, agora=datetime.now(UTC)
        )
        is False
    )


async def test_encerrar_marca_status_motivo_e_carimbo(session: AsyncSession) -> None:
    agora = datetime.now(UTC)

    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=agora,
    )

    assert (
        await esta_encerrada(session, channel=CANAL, conversation_key=CONVERSA, agora=agora) is True
    )
    linha = (
        await session.execute(
            select(Conversa).where(Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.status == Status.ENCERRADA
    assert linha.motivo_do_encerramento == MotivoDoEncerramento.FORA_DE_ESCOPO
    assert linha.encerrada_em == agora


async def test_janela_expirada_nao_esta_encerrada_mas_status_continua_encerrada(
    session: AsyncSession,
) -> None:
    """31 dias depois do encerramento, a janela expirou.

    **Esta e a asserta que prova que a decisao e do tempo, e nao so do
    status.** Sem a segunda metade -- reconferir a coluna depois de perguntar
    -- um `esta_encerrada` que ignorasse `agora` e devolvesse sempre `True`
    enquanto a coluna diz ENCERRADA passaria por aqui do mesmo jeito. Quem
    reabre a linha e o turno (Task 4), e ele so roda quando chega mensagem
    nova -- ate la a coluna fica como estava.
    """
    encerrada_em = datetime.now(UTC)
    agora = encerrada_em + timedelta(days=31)

    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=encerrada_em,
    )

    assert (
        await esta_encerrada(session, channel=CANAL, conversation_key=CONVERSA, agora=agora)
        is False
    )
    linha = (
        await session.execute(
            select(Conversa).where(Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.status == Status.ENCERRADA, (
        "a coluna nao mudou -- a resposta False veio do tempo, nao de um UPDATE"
    )


async def test_janela_de_29_dias_ainda_esta_encerrada(session: AsyncSession) -> None:
    """Contraprova do teste anterior: sem ela, um `esta_encerrada` que
    ignorasse o tempo e devolvesse sempre `False` tambem passaria.
    """
    encerrada_em = datetime.now(UTC)
    agora = encerrada_em + timedelta(days=29)

    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=encerrada_em,
    )

    assert (
        await esta_encerrada(session, channel=CANAL, conversation_key=CONVERSA, agora=agora) is True
    )


async def test_o_limite_exato_de_30_dias_ainda_esta_encerrada(session: AsyncSession) -> None:
    """O empate nao fica ao acaso (fix da revisao, Important 1).

    Mesmo raciocinio de `test_o_limite_exato_de_30_dias_tem_lado_definido`
    em `test_identificacao_fronteira.py`, e tem de dar o mesmo lado: as duas
    funcoes compartilham `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`, e a reabertura
    tem de coincidir com o instante em que `e_conversa_nova` passa a
    considerar conversa nova, nao acontecer um instante antes. Exatamente 30
    dias depois do encerramento AINDA e encerrada; reabre so depois disso.
    Sem este teste, um `<=` trocado de volta por `<` nao ficaria vermelho.
    """
    encerrada_em = datetime.now(UTC)
    agora = encerrada_em + timedelta(days=30)

    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=encerrada_em,
    )

    assert (
        await esta_encerrada(session, channel=CANAL, conversation_key=CONVERSA, agora=agora) is True
    )


async def test_reabrir_volta_para_ativa_e_limpa_motivo_e_carimbo(session: AsyncSession) -> None:
    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=datetime.now(UTC),
    )

    await reabrir_conversa(session, channel=CANAL, conversation_key=CONVERSA)

    linha = (
        await session.execute(
            select(Conversa).where(Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.status == Status.ATIVA
    assert linha.motivo_do_encerramento is None
    assert linha.encerrada_em is None


async def test_reabrir_sem_linha_nenhuma_nao_levanta(session: AsyncSession) -> None:
    """Confirmacao 4 do brief: `UPDATE` sem linha e no-op, e esta certo -- nao
    havia o que reabrir.
    """
    await reabrir_conversa(session, channel=CANAL, conversation_key=CONVERSA)

    linha = (
        await session.execute(
            select(Conversa).where(Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA)
        )
    ).one_or_none()
    assert linha is None


async def test_encerrar_duas_vezes_e_idempotente_e_fica_com_o_carimbo_da_segunda(
    session: AsyncSession,
) -> None:
    """E' upsert, nao INSERT: a conversa pode ja ter linha de um encerramento
    anterior que a janela dos 30 dias ja reabriu (`deve_encerrar` usa `>=`
    pela mesma razao -- admite a repeticao).
    """
    primeiro = datetime.now(UTC)
    segundo = primeiro + timedelta(minutes=5)

    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=primeiro,
    )
    await encerrar_conversa(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=segundo,
    )

    linha = (
        await session.execute(
            select(Conversa).where(Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.status == Status.ENCERRADA
    assert linha.encerrada_em == segundo
