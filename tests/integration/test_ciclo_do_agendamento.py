"""As quatro transicoes do ciclo, contra o banco. TEC-172, RN-12.3 a RN-12.5.

A maquina de estados e uma tabela (`_ORIGENS_DE`) e da para ler; o que so o
banco responde e se o slot foi de fato liberado, se os dois lados da
remarcacao entram no mesmo commit, e se a penalidade sobrevive ao recalculo
seguinte.

Arquivo autocontido, no molde de `test_confirmacao_do_agendamento.py`.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.cancelamento import avisar_cancelamento
from mobia.domain.agendamento.ciclo import (
    MOTIVO_INEXISTENTE,
    MOTIVO_ORIGEM_ILEGAL,
    PONTOS_POR_NAO_COMPARECIMENTO,
    NaoCompareceu,
    Recusado,
    Remarcado,
    Transicionado,
    cancelar,
    marcar_nao_comparecimento,
    marcar_realizado,
    remarcar,
)
from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.mensagens import ETIQUETA_DO_CANCELAMENTO
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import Reserva, reservar
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.auditoria import CAUSA_NAO_COMPARECIMENTO, CAUSA_PENALIDADE
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.mensagem import Aviso
from mobia.infra.db import get_sessionmaker

SP = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 9, 26, 15, tzinfo=SP)
FIM = datetime(2026, 9, 26, 16, tzinfo=SP)
CANAL = "whatsapp"
CONVERSA = "5511911111111"
AGORA = datetime(2026, 9, 25, 12, tzinfo=UTC)


async def _agendamento(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    status: str = StatusDoAgendamento.CONFIRMADO,
    inicio: datetime = INICIO,
    fim: datetime = FIM,
) -> Agendamento:
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=CANAL,
        conversation_key=CONVERSA,
        imovel_id=None,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=fim,
        status=status,
        reservado_ate=inicio,
        criado_em=AGORA,
        confirmado_em=AGORA if status == StatusDoAgendamento.CONFIRMADO else None,
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _lead_com_score(session: AsyncSession, **campos: object) -> None:
    """Um lead qualificado, para o score ter de onde sair."""
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 60_000_000,
        "regiao": "zona sul",
        "urgencia": Urgencia.IMEDIATA.value,
        "forma_pagamento": FormaPagamento.A_VISTA.value,
    }
    session.add(LeadQualification(**{**base, **campos}))
    await session.commit()


async def _recarregar(session: AsyncSession, identificador: uuid.UUID) -> Agendamento:
    """Le a linha do banco de novo, sem expirar o resto da sessao.

    **`populate_existing` e nao `expire_all`**, e a diferenca morde: com
    `expire_all`, a SEGUNDA chamada num teste expira o objeto que a primeira
    devolveu, e ler qualquer atributo dele depois dispara um refresh sincrono
    contra a engine assincrona -- `MissingGreenlet`, longe da linha culpada.
    A opcao faz o SELECT sobrescrever o identity map so desta linha, que e o
    que se quer: ler de novo o que outro statement acabou de mudar.
    """
    return (
        await session.execute(
            select(Agendamento)
            .where(Agendamento.id == identificador)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _trilha(session: AsyncSession) -> list[LeadScoreAudit]:
    return list(
        (
            await session.execute(
                select(LeadScoreAudit)
                .where(LeadScoreAudit.conversation_key == CONVERSA)
                .order_by(LeadScoreAudit.created_at)
            )
        )
        .scalars()
        .all()
    )


# ----------------------------------------------------------- o cancelamento


async def test_cancelar_de_confirmado_carimba_e_muda_o_status(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    resultado = await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, Transicionado)
    linha = await _recarregar(session, agendamento.id)
    assert linha.status == StatusDoAgendamento.CANCELADO
    assert linha.cancelado_em is not None


async def test_cancelar_tambem_vale_para_reserva_nao_confirmada(
    session: AsyncSession, semear_corretor
) -> None:
    """Uma reserva de cinco minutos tambem se desiste."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, status=StatusDoAgendamento.RESERVADO
    )

    assert isinstance(
        await cancelar(session, agendamento_id=agendamento.id, agora=AGORA), Transicionado
    )


async def test_o_slot_volta_ao_pool_assim_que_o_cancelamento_commita(
    session: AsyncSession, semear_corretor
) -> None:
    """CA-12.2: "o slot volta ao pool em menos de 10 segundos".

    O que existe e o tempo de um UPDATE, porque o WHERE da
    `ex_agendamentos_sem_sobreposicao` e allowlist de RESERVADO e CONFIRMADO.
    **Este teste prova a ponta que importa**: depois do cancelamento, uma
    reserva NOVA no MESMO horario e para o MESMO corretor e aceita -- e antes
    dele nao seria (`test_agendamento_schema.py` prova o outro lado).
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    nova = await reservar(
        session,
        corretor_id=corretor.id,
        channel=CANAL,
        conversation_key="5511922222222",
        janela=Intervalo(INICIO, FIM),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=AGORA,
        motivo=MotivoDaAlocacao.MATCH_EXATO,
    )
    await session.commit()

    assert isinstance(nova, Reserva)


async def test_cancelar_duas_vezes_recusa_a_segunda(session: AsyncSession, semear_corretor) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()
    segunda = await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)

    assert isinstance(segunda, Recusado)
    assert segunda.motivo == MOTIVO_ORIGEM_ILEGAL


async def test_transicao_de_agendamento_inexistente_diz_que_nao_existe(
    session: AsyncSession,
) -> None:
    """Dois motivos e nao um bool: "ja estava assim" e "id errado" sao coisas
    diferentes, e responder o mesmo esconde a segunda."""
    resultado = await cancelar(session, agendamento_id=uuid.uuid4(), agora=AGORA)
    assert isinstance(resultado, Recusado)
    assert resultado.motivo == MOTIVO_INEXISTENTE


# ------------------------------------------------------------ a remarcacao


async def test_remarcar_poe_o_original_em_reagendado_e_vincula_o_novo(
    session: AsyncSession, semear_corretor
) -> None:
    """Quarto cenario do Gherkin, inteiro."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    original = await _agendamento(session, corretor_id=corretor.id)
    nova_janela = Intervalo(INICIO + timedelta(days=1), FIM + timedelta(days=1))

    resultado = await remarcar(session, agendamento_id=original.id, janela=nova_janela, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, Remarcado)
    velho = await _recarregar(session, original.id)
    novo = await _recarregar(session, resultado.novo_id)
    assert velho.status == StatusDoAgendamento.REAGENDADO
    assert novo.status == StatusDoAgendamento.CONFIRMADO
    assert novo.origem_id == original.id
    assert novo.inicio == nova_janela.inicio


async def test_a_remarcacao_encadeia(session: AsyncSession, semear_corretor) -> None:
    """A -> B -> C, sem teto: quem quiser a origem primeira sobe a cadeia."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    a = await _agendamento(session, corretor_id=corretor.id)

    primeiro = await remarcar(
        session,
        agendamento_id=a.id,
        janela=Intervalo(INICIO + timedelta(days=1), FIM + timedelta(days=1)),
        agora=AGORA,
    )
    await session.commit()
    assert isinstance(primeiro, Remarcado)

    segundo = await remarcar(
        session,
        agendamento_id=primeiro.novo_id,
        janela=Intervalo(INICIO + timedelta(days=2), FIM + timedelta(days=2)),
        agora=AGORA,
    )
    await session.commit()
    assert isinstance(segundo, Remarcado)

    c = await _recarregar(session, segundo.novo_id)
    assert c.origem_id is not None
    b = await _recarregar(session, c.origem_id)
    assert b.origem_id == a.id


async def test_remarcar_o_que_ja_foi_cancelado_e_recusado(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, status=StatusDoAgendamento.CANCELADO
    )

    resultado = await remarcar(
        session,
        agendamento_id=agendamento.id,
        janela=Intervalo(INICIO + timedelta(days=1), FIM + timedelta(days=1)),
        agora=AGORA,
    )

    assert isinstance(resultado, Recusado)
    assert resultado.motivo == MOTIVO_ORIGEM_ILEGAL
    # E nenhum sucessor nasceu.
    assert (
        await session.execute(select(Agendamento).where(Agendamento.origem_id == agendamento.id))
    ).first() is None


# ----------------------------------------------------- o nao comparecimento


async def test_o_no_show_tira_quinze_pontos_e_deixa_as_duas_causas_na_trilha(
    session: AsyncSession, semear_corretor
) -> None:
    """Segundo cenario do Gherkin: score 68 -> 53, com registro de auditoria.

    As DUAS causas: `PENALIDADE` diz o que se moveu, `NAO_COMPARECIMENTO` diz
    por que. Uma so apagaria metade da resposta.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)
    await _lead_com_score(session)
    antes = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert antes is not None

    resultado = await marcar_nao_comparecimento(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, NaoCompareceu)
    assert resultado.penalidade_total == PONTOS_POR_NAO_COMPARECIMENTO
    assert resultado.recalculo is not None
    assert resultado.recalculo.total == antes.total - PONTOS_POR_NAO_COMPARECIMENTO

    ultima = (await _trilha(session))[-1]
    assert CAUSA_NAO_COMPARECIMENTO in ultima.causas
    assert CAUSA_PENALIDADE in ultima.causas
    assert ultima.penalidade == PONTOS_POR_NAO_COMPARECIMENTO
    assert ultima.total_novo == antes.total - PONTOS_POR_NAO_COMPARECIMENTO

    linha = await _recarregar(session, agendamento.id)
    assert linha.status == StatusDoAgendamento.NO_SHOW
    assert linha.nao_compareceu_em is not None


async def test_o_recalculo_seguinte_nao_devolve_os_pontos(
    session: AsyncSession, semear_corretor
) -> None:
    """O teste que separa esta solucao da que so grava na trilha.

    O score e derivado: sem a penalidade PERSISTIDA, o recalculo seguinte
    recomporia os cinco fatores e o desconto evaporaria -- a trilha diria 53 e
    o lead valeria 68.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)
    await _lead_com_score(session)

    penalizado = await marcar_nao_comparecimento(
        session, agendamento_id=agendamento.id, agora=AGORA
    )
    await session.commit()
    assert isinstance(penalizado, NaoCompareceu)
    assert penalizado.recalculo is not None

    depois = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert depois is not None
    assert depois.total == penalizado.recalculo.total


async def test_dois_nao_comparecimentos_acumulam(session: AsyncSession, semear_corretor) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _lead_com_score(session)
    primeiro = await _agendamento(session, corretor_id=corretor.id)
    segundo = await _agendamento(
        session,
        corretor_id=corretor.id,
        inicio=INICIO + timedelta(days=1),
        fim=FIM + timedelta(days=1),
    )

    await marcar_nao_comparecimento(session, agendamento_id=primeiro.id, agora=AGORA)
    await session.commit()
    resultado = await marcar_nao_comparecimento(session, agendamento_id=segundo.id, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, NaoCompareceu)
    assert resultado.penalidade_total == 2 * PONTOS_POR_NAO_COMPARECIMENTO


async def test_o_total_nao_fica_negativo(session: AsyncSession, semear_corretor) -> None:
    """Piso zero. A COLUNA acumula de verdade; quem corta e o total."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _lead_com_score(session, urgencia=None, forma_pagamento=None, regiao=None)
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    resultado = await marcar_nao_comparecimento(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, NaoCompareceu)
    assert resultado.recalculo is not None
    assert resultado.recalculo.total >= 0
    linha = (
        await session.execute(
            select(LeadQualification).where(LeadQualification.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.penalidade_pontos == PONTOS_POR_NAO_COMPARECIMENTO


async def test_no_show_de_lead_sem_qualificacao_nao_levanta(
    session: AsyncSession, semear_corretor
) -> None:
    """Um agendamento pode existir para uma conversa que nunca qualificou."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    resultado = await marcar_nao_comparecimento(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    assert isinstance(resultado, NaoCompareceu)
    assert resultado.penalidade_total == 0
    assert resultado.recalculo is None


# ------------------------------------------------------------- o realizado


async def test_marcar_realizado_nao_custa_nada_ao_lead(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _lead_com_score(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    assert isinstance(
        await marcar_realizado(session, agendamento_id=agendamento.id, agora=AGORA),
        Transicionado,
    )
    await session.commit()

    linha = (
        await session.execute(
            select(LeadQualification).where(LeadQualification.conversation_key == CONVERSA)
        )
    ).scalar_one()
    assert linha.penalidade_pontos == 0


@pytest.mark.parametrize("status", [StatusDoAgendamento.RESERVADO, StatusDoAgendamento.EXPIRADO])
async def test_so_confirmado_pode_ser_realizado_ou_faltado(
    session: AsyncSession, semear_corretor, status: str
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id, status=status)

    assert isinstance(
        await marcar_realizado(session, agendamento_id=agendamento.id, agora=AGORA), Recusado
    )
    assert isinstance(
        await marcar_nao_comparecimento(session, agendamento_id=agendamento.id, agora=AGORA),
        Recusado,
    )


# ---------------------------------------- o aviso de cancelamento ao corretor


class _CanalEspiao:
    """Duble de `CanalDeNotificacaoPort`. Copiado de test_notificacao_envio.py."""

    def __init__(self) -> None:
        self.recebidas: list[tuple[str, Aviso]] = []

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        self.recebidas.append((destino, aviso))


class _CanalQueFalha:
    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        raise FalhaDeCanal("smtp recusou")


async def test_o_corretor_e_avisado_do_cancelamento_uma_vez_so(
    session: AsyncSession, semear_corretor
) -> None:
    """RN-12.3: "notifica o corretor"."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)
    await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    canal = _CanalEspiao()
    await avisar_cancelamento(
        get_sessionmaker(), agendamento_id=agendamento.id, email=canal, agora=AGORA
    )
    await avisar_cancelamento(
        get_sessionmaker(), agendamento_id=agendamento.id, email=canal, agora=AGORA
    )

    assert len(canal.recebidas) == 1
    destino, aviso = canal.recebidas[0]
    assert destino == "ana@imob.com.br"
    assert "cancelada" in aviso.assunto
    assert aviso.etiqueta == ETIQUETA_DO_CANCELAMENTO
    assert CONVERSA in aviso.corpo

    linha = await _recarregar(session, agendamento.id)
    assert linha.corretor_avisado_do_cancelamento_em is not None


async def test_a_coluna_do_cancelamento_e_propria_e_nao_a_da_confirmacao(
    session: AsyncSession, semear_corretor
) -> None:
    """Com uma coluna so, o aviso do cancelamento seria suprimido porque o da
    confirmacao ja tinha acontecido -- e sao dois fatos diferentes."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)
    agendamento.corretor_avisado_em = AGORA
    await session.commit()
    await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    canal = _CanalEspiao()
    await avisar_cancelamento(
        get_sessionmaker(), agendamento_id=agendamento.id, email=canal, agora=AGORA
    )

    assert len(canal.recebidas) == 1


async def test_agendamento_que_nao_esta_cancelado_nao_gera_aviso(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)

    canal = _CanalEspiao()
    await avisar_cancelamento(
        get_sessionmaker(), agendamento_id=agendamento.id, email=canal, agora=AGORA
    )

    assert canal.recebidas == []


async def test_falha_de_canal_deixa_a_coluna_nula(
    session: AsyncSession, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    """A coluna nula e o registro de que o aviso nao saiu."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(session, corretor_id=corretor.id)
    await cancelar(session, agendamento_id=agendamento.id, agora=AGORA)
    await session.commit()

    with caplog.at_level(logging.ERROR):
        await avisar_cancelamento(
            get_sessionmaker(), agendamento_id=agendamento.id, email=_CanalQueFalha(), agora=AGORA
        )

    assert eventos_de_log(caplog, "agendamento.aviso_de_cancelamento_falhou")
    linha = await _recarregar(session, agendamento.id)
    assert linha.corretor_avisado_do_cancelamento_em is None
