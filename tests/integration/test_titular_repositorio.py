"""O repositorio de solicitacao de titular: o que so o Postgres prova."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.identidade.indice import chave_de
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import (
    SolicitacaoNaoAberta,
    listar,
    marcar_atendida,
    recusar,
    registrar_solicitacao,
    solicitacao_aberta,
    vencidas,
)
from mobia.domain.titular.vocabulario import (
    PRAZO_DO_TITULAR,
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)

CANAL = "whatsapp"
CONVERSA = chave_de("whatsapp", "5548999990000")


async def _total_eventos(session: AsyncSession, acao: str) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(EventoAuditoria).where(EventoAuditoria.acao == acao)
        )
    ).scalar_one()


async def test_registrar_cria_com_prazo_de_15_dias_e_evento_na_trilha(
    session: AsyncSession,
) -> None:
    antes = datetime.now(UTC)
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ABERTA.value
    assert linha.channel == CANAL
    assert linha.conversation_key == CONVERSA
    # `recebida_em` e o `server_default=func.now()` do Postgres; `prazo_em` e
    # calculado em Python antes do INSERT. Dois relogios, duas leituras --
    # nao sao o MESMO instante, entao a comparacao e por faixa e nao por
    # igualdade exata.
    assert antes + PRAZO_DO_TITULAR <= linha.prazo_em <= datetime.now(UTC) + PRAZO_DO_TITULAR

    evento = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == "TITULAR_SOLICITOU")
        )
    ).scalar_one()
    assert evento.entidade == "solicitacao_de_titular"
    assert evento.entidade_id == str(solicitacao_id)


async def test_registrar_de_novo_o_mesmo_tipo_devolve_o_mesmo_id_e_nao_cria_evento(
    session: AsyncSession,
) -> None:
    primeiro = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    segundo = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    assert segundo == primeiro
    assert await _total_eventos(session, "TITULAR_SOLICITOU") == 1
    total_linhas = (
        await session.execute(select(func.count()).select_from(SolicitacaoDeTitular))
    ).scalar_one()
    assert total_linhas == 1


async def test_tipos_diferentes_coexistem(session: AsyncSession) -> None:
    eliminacao = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    acesso = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    assert eliminacao != acesso
    total_linhas = (
        await session.execute(select(func.count()).select_from(SolicitacaoDeTitular))
    ).scalar_one()
    assert total_linhas == 2


async def test_recusar_sem_motivo_reprova(session: AsyncSession) -> None:
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    with pytest.raises(ValueError):
        await recusar(session, solicitacao_id, motivo="   ", ator=ATOR_SISTEMA)


async def test_recusar_zera_o_par_e_registra_evento(session: AsyncSession) -> None:
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    await recusar(session, solicitacao_id, motivo="retencao legal", ator=ATOR_SISTEMA)
    await session.commit()

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.RECUSADA.value
    assert linha.motivo_da_recusa == "retencao legal"
    assert linha.channel is None
    assert linha.conversation_key is None

    evento = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == "TITULAR_RECUSADO")
        )
    ).scalar_one()
    assert evento.entidade_id == str(solicitacao_id)


async def test_marcar_atendida_zera_o_par(session: AsyncSession) -> None:
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    agora = datetime.now(UTC)
    await marcar_atendida(session, solicitacao_id, agora=agora)
    await session.commit()

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ATENDIDA.value
    assert linha.atendida_em == agora
    assert linha.channel is None
    assert linha.conversation_key is None
    assert (
        await solicitacao_aberta(
            session, channel=CANAL, conversation_key=CONVERSA, tipo=TipoDeSolicitacao.ACESSO
        )
        is None
    )


async def test_recusar_uma_atendida_levanta_solicitacao_nao_aberta(session: AsyncSession) -> None:
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    await marcar_atendida(session, solicitacao_id, agora=datetime.now(UTC))
    await session.commit()

    with pytest.raises(SolicitacaoNaoAberta):
        await recusar(session, solicitacao_id, motivo="tarde demais", ator=ATOR_SISTEMA)


async def test_marcar_atendida_de_uma_recusada_levanta_e_nao_muda_nada(
    session: AsyncSession,
) -> None:
    """A corrida que a revisao achou: sem o WHERE status='ABERTA', esta

    chamada reviveria uma RECUSADA como ATENDIDA em silencio -- duas
    chamadas concorrentes (`recusar` e `marcar_atendida`) sobre o MESMO id
    podiam terminar com a RECUSADA sobrescrita, sem que nenhuma das duas
    soubesse da outra.
    """
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    await recusar(session, solicitacao_id, motivo="retencao legal", ator=ATOR_SISTEMA)
    await session.commit()

    with pytest.raises(SolicitacaoNaoAberta):
        await marcar_atendida(session, solicitacao_id, agora=datetime.now(UTC))

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.RECUSADA.value
    assert linha.atendida_em is None


async def test_marcar_atendida_de_um_id_inexistente_levanta(session: AsyncSession) -> None:
    with pytest.raises(SolicitacaoNaoAberta):
        await marcar_atendida(session, uuid.uuid4(), agora=datetime.now(UTC))


async def test_vencidas_so_devolve_as_abertas_com_prazo_passado(session: AsyncSession) -> None:
    conversa_vencida = chave_de("whatsapp", "5548999990001")
    conversa_no_prazo = chave_de("whatsapp", "5548999990002")
    conversa_atendida = chave_de("whatsapp", "5548999990003")

    vencida_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa_vencida,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa_no_prazo,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    atendida_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa_atendida,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    # Empurra o prazo da primeira para o passado, direto no banco -- e o
    # jeito de simular "15 dias se passaram" sem esperar 15 dias de verdade.
    vencida = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == vencida_id)
        )
    ).scalar_one()
    vencida.prazo_em = datetime.now(UTC) - timedelta(days=1)
    atendida = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == atendida_id)
        )
    ).scalar_one()
    atendida.prazo_em = datetime.now(UTC) - timedelta(days=1)
    await session.commit()
    await marcar_atendida(session, atendida_id, agora=datetime.now(UTC))
    await session.commit()

    resultado = await vencidas(session, agora=datetime.now(UTC), tipo=TipoDeSolicitacao.ELIMINACAO)

    assert [linha.id for linha in resultado] == [vencida_id]


async def test_listar_ordena_por_prazo(session: AsyncSession) -> None:
    conversa_a = chave_de("whatsapp", "5548999990004")
    conversa_b = chave_de("whatsapp", "5548999990005")

    primeiro_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa_a,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    segundo_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa_b,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    linha_b = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == segundo_id)
        )
    ).scalar_one()
    linha_b.prazo_em = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    resultado = await listar(session, status=StatusDaSolicitacao.ABERTA)

    assert [linha.id for linha in resultado] == [segundo_id, primeiro_id]


async def test_o_par_incompleto_e_recusado_pelo_banco(session: AsyncSession) -> None:
    """`ck_solicitacoes_de_titular_par_completo` -- o CHECK que faltava.

    `channel` preenchido com `conversation_key` nulo passaria pelo CHECK
    `_par_com_status` sozinho (ele so olha o status contra `channel`); e esta
    linha que fecha o buraco.
    """
    session.add(
        SolicitacaoDeTitular(
            id=uuid.uuid4(),
            lead_ref="a" * 64,
            channel=CANAL,
            conversation_key=None,
            tipo=TipoDeSolicitacao.ELIMINACAO.value,
            origem=OrigemDaSolicitacao.WHATSAPP.value,
            status=StatusDaSolicitacao.ABERTA.value,
            prazo_em=datetime.now(UTC) + PRAZO_DO_TITULAR,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
