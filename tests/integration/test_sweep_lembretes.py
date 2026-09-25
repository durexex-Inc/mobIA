"""A varredura dos lembretes de agendamento, ponta a ponta. TEC-171, RN-12.2.

A regua mora na funcao pura (`tests/unit/test_lembretes_de_agendamento.py`);
o que so da para verificar contra o banco e quem entra na consulta, o que sai
pela porta e o que fica gravado.

Arquivo autocontido, como os demais de integracao deste repo: `_imovel` e
`_agendamento` vem do molde de `test_confirmacao_do_agendamento.py`.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import OutboundFake, eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import Settings
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.lembretes import (
    LEMBRETE_DE_2H,
    LEMBRETE_DE_24H,
    kind_do_lembrete,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioRetentavel
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_lembretes import sweep_lembretes

CANAL = "whatsapp"
CONVERSA = "5511911111111"

NOME_DO_FUSO = "America/Sao_Paulo"
FUSO = ZoneInfo(NOME_DO_FUSO)

# A visita e as 15h locais de um sabado. Todo teste deste arquivo fixa `agora`
# em relacao a ela, pela razao que `test_sweep_followups.py` ja escreve: com a
# guarda de horario (RN-13.3) a varredura depende da hora do dia, e sem fixar
# o momento a suite passaria ou reprovaria conforme a hora do CI.
INICIO = datetime(2026, 9, 26, 15, tzinfo=FUSO)
FIM = datetime(2026, 9, 26, 16, tzinfo=FUSO)
# Vinte e seis horas antes -- o "Dado" da CA-12.1.
CONFIRMADO_EM = INICIO - timedelta(hours=26)


async def _imovel(session: AsyncSession) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo="AP-001",
            titulo="Apartamento na Vila Mariana",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=74900000,
            bairro="Moema",
            bairro_busca="moema",
            cidade="São Paulo",
            uf="SP",
            area_util_m2=78,
            quartos=3,
            suites=1,
            banheiros=2,
            vagas=2,
            caracteristicas=["varanda"],
            fotos=[],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


async def _agendamento(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    imovel_id: uuid.UUID | None = None,
    status: str = StatusDoAgendamento.CONFIRMADO,
    inicio: datetime = INICIO,
    fim: datetime = FIM,
    confirmado_em: datetime | None = CONFIRMADO_EM,
    tipo: str = str(TipoDeCompromisso.VISITA_PRESENCIAL),
) -> Agendamento:
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=CANAL,
        conversation_key=CONVERSA,
        imovel_id=imovel_id,
        tipo=tipo,
        inicio=inicio,
        fim=fim,
        status=status,
        reservado_ate=inicio,
        criado_em=confirmado_em or inicio,
        confirmado_em=confirmado_em,
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _mensagem_do_lead(session: AsyncSession, *, criada_em: datetime) -> Message:
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CANAL,
        provider_message_id=f"wamid.{uuid.uuid4().hex[:10]}",
        sender_external_id=CONVERSA,
        recipient_external_id="222222222",
        conversation_key=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        created_at=criada_em,
    )
    session.add(mensagem)
    await session.commit()
    return mensagem


def _ctx(outbound: object | None = None, *, templates_aprovados: str = "") -> dict[str, Any]:
    """A janela de contato (9h-20h no fuso do modulo) explicita, e nao herdada.

    Mesmo cuidado de `test_sweep_followups.py::_ctx`: `_env_file=None` desliga
    o `.env` mas nao a variavel do processo, e o `followup_fuso` precisa vir
    pelo kwarg para o fuso do relogio do teste e o da varredura nao poderem
    divergir.

    A chave `outbound` e a MESMA que producao usa -- `startup` grava ali o
    `RoteadorPorCanal`.
    """
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound if outbound is not None else OutboundFake(get_sessionmaker()),
        "settings": Settings(
            _env_file=None,
            followup_horario_inicio=9,
            followup_horario_fim=20,
            followup_fuso=NOME_DO_FUSO,
            whatsapp_templates_aprovados=templates_aprovados,
        ),
    }


async def _recarregar(session: AsyncSession, identificador: uuid.UUID) -> Agendamento:
    session.expire_all()
    return (
        await session.execute(select(Agendamento).where(Agendamento.id == identificador))
    ).scalar_one()


async def _kinds_reservados(session: AsyncSession) -> list[str]:
    return list((await session.execute(select(OutboundDispatch.kind))).scalars().all())


# --------------------------------------------------------- o caminho feliz


async def test_o_lembrete_de_24h_sai_uma_vez_quando_o_relogio_chega(
    session: AsyncSession, semear_corretor
) -> None:
    """CA-12.1, o criterio de aceite inteiro.

    "Dado um agendamento confirmado para daqui a 26 horas, quando o relogio
    chega a 24 h antes, entao o lembrete e enviado uma unica vez."
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    imovel = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel)
    # A ancora dentro da janela de 24h da Meta, para o envio ser texto livre.
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24))

    assert enviados == 1
    assert len(outbound.entregues) == 1
    assert "sua visita" in outbound.entregues[0]
    assert "AP-001" in outbound.entregues[0]
    assert kind_do_lembrete(LEMBRETE_DE_24H, agendamento.id) in await _kinds_reservados(session)

    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None
    assert linha.lembrete_2h_em is None
    # Nenhum passo escreve em `status`.
    assert linha.status == StatusDoAgendamento.CONFIRMADO


async def test_a_segunda_passagem_sobre_o_mesmo_estado_nao_manda_de_novo(
    session: AsyncSession, semear_corretor
) -> None:
    """ "Reprocessamento nao duplica" -- o segundo cenario do Gherkin da card."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(session, corretor_id=corretor.id, imovel_id=await _imovel(session))
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    agora = INICIO - timedelta(hours=24)
    assert await sweep_lembretes(_ctx(outbound), agora=agora) == 1
    assert await sweep_lembretes(_ctx(outbound), agora=agora) == 0
    assert len(outbound.entregues) == 1


async def test_o_lembrete_de_2h_sai_e_o_de_24h_nao_sai_de_novo(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 1
    # A ancora precisa continuar dentro da janela para o segundo envio ser
    # texto livre; uma fala nova do lead a move.
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=3))
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=2)) == 1

    assert len(outbound.entregues) == 2
    assert "daqui a pouco" in outbound.entregues[1]

    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None
    assert linha.lembrete_2h_em is not None

    reservados = await _kinds_reservados(session)
    assert kind_do_lembrete(LEMBRETE_DE_24H, agendamento.id) in reservados
    assert kind_do_lembrete(LEMBRETE_DE_2H, agendamento.id) in reservados


# ------------------------------------------------------ as bordas da faixa


async def test_o_lembrete_de_24h_nao_sai_depois_do_marco_do_de_2h(
    session: AsyncSession, semear_corretor
) -> None:
    """O teto da faixa (D2), visto de ponta a ponta.

    Um worker parado tres horas encontra o de 24h ainda nulo. Sem o teto, ele
    sairia agora -- noventa minutos antes da visita, perguntando se da para
    remarcar.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(minutes=90))

    # Sai o de 2 horas, que e o devido agora -- e so ele.
    assert enviados == 1
    assert "daqui a pouco" in outbound.entregues[0]
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is None
    assert linha.lembrete_2h_em is not None


async def test_confirmado_em_cima_da_hora_nao_recebe_o_lembrete_de_24h(
    session: AsyncSession, semear_corretor
) -> None:
    """A terceira condicao da D2.

    O lead acabou de receber a confirmacao da TEC-170, com a mesma data, a
    mesma hora e o mesmo endereco. Um "lembrete de 24 horas" minutos depois
    repetiria tudo.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    confirmado = INICIO - timedelta(hours=3)
    agendamento = await _agendamento(
        session,
        corretor_id=corretor.id,
        imovel_id=await _imovel(session),
        confirmado_em=confirmado,
    )
    await _mensagem_do_lead(session, criada_em=confirmado)

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=confirmado) == 0
    assert outbound.entregues == []

    # E o de 2 horas, cujo momento ainda estava no futuro, continua valendo.
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=2)) == 1
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is None
    assert linha.lembrete_2h_em is not None


async def test_depois_do_inicio_nao_ha_lembrete_nenhum(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(session, corretor_id=corretor.id, imovel_id=await _imovel(session))
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO + timedelta(minutes=1)) == 0
    assert outbound.entregues == []


# --------------------------------------------------------------- o status


@pytest.mark.parametrize("status", [StatusDoAgendamento.RESERVADO, StatusDoAgendamento.EXPIRADO])
async def test_so_agendamento_confirmado_recebe_lembrete(
    session: AsyncSession, semear_corretor, status: str
) -> None:
    """O quarto cenario do Gherkin, no que ele tem de exercitavel hoje.

    A card diz "agendamento cancelado nao recebe lembrete", e o status
    `CANCELADO` nao existe -- ele e a TEC-172, e o CHECK de `agendamentos`
    so aceita tres valores. O filtro que o excluiria e o MESMO
    `status = 'CONFIRMADO'` que exclui estes dois, entao e ele que se
    exercita: quando a TEC-172 acrescentar `CANCELADO`, esta varredura ja o
    ignora sem uma linha de mudanca.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(
        session,
        corretor_id=corretor.id,
        imovel_id=await _imovel(session),
        status=status,
        confirmado_em=None,
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 0
    assert outbound.entregues == []


# ---------------------------------------------------- horario e janela 24h


async def test_fora_do_horario_de_contato_a_varredura_nao_toca_o_banco(
    session: AsyncSession, semear_corretor
) -> None:
    """RN-13.3. A guarda roda no topo, antes da consulta.

    Um lembrete devido as 3h da manha nao sai; se a faixa dele ainda estiver
    aberta na proxima passagem dentro do horario, ele sai la.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session,
        corretor_id=corretor.id,
        imovel_id=await _imovel(session),
        # Visita as 5h da manha: a faixa do lembrete de 2h vai das 3h as 5h,
        # inteira fora da janela de contato.
        inicio=datetime(2026, 9, 26, 5, tzinfo=FUSO),
        fim=datetime(2026, 9, 26, 6, tzinfo=FUSO),
        confirmado_em=datetime(2026, 9, 25, 10, tzinfo=FUSO),
    )
    await _mensagem_do_lead(session, criada_em=datetime(2026, 9, 26, 2, tzinfo=FUSO))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lembretes(
        _ctx(outbound), agora=datetime(2026, 9, 26, 3, tzinfo=FUSO).astimezone(UTC)
    )

    assert enviados == 0
    assert outbound.entregues == []
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_2h_em is None


async def test_fora_da_janela_de_24h_sem_template_nao_sai_nada(
    session: AsyncSession, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    """D4, e a lacuna maior desta card.

    `WHATSAPP_TEMPLATES_APROVADOS` vazio e o default do RT-03, e um lead que
    marcou visita ontem nao escreveu desde entao. A coluna e gravada mesmo
    assim: a passagem seguinte teria a mesma resposta.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(days=3))

    outbound = OutboundFake(get_sessionmaker())
    with caplog.at_level(logging.WARNING):
        enviados = await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24))

    assert enviados == 0
    assert outbound.entregues == []
    assert eventos_de_log(caplog, "lembrete.sem_template")
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None


async def test_fora_da_janela_de_24h_com_template_aprovado_sai_o_template(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(session, corretor_id=corretor.id, imovel_id=await _imovel(session))
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(days=3))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lembretes(
        _ctx(outbound, templates_aprovados=LEMBRETE_DE_24H.template),
        agora=INICIO - timedelta(hours=24),
    )

    assert enviados == 1
    assert outbound.entregues == [LEMBRETE_DE_24H.template]
    (payload,) = outbound.payloads
    assert payload["tipo"] == "template"
    assert payload["template"] == LEMBRETE_DE_24H.template


# ----------------------------------------------- o que a coluna quer dizer


async def test_lead_em_optout_nao_recebe_e_a_varredura_nao_tenta_de_novo(
    session: AsyncSession, semear_corretor
) -> None:
    """D3: a guarda recusou, e a coluna e gravada assim mesmo.

    E aqui que esta card diverge da TEC-170, e o motivo e o cron: deixar nulo
    produziria uma tentativa barrada a cada cinco minutos por ate vinte e duas
    horas.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 0
    assert outbound.entregues == []

    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None

    # A passagem seguinte nao encontra mais a linha.
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=23)) == 0


async def test_falha_de_canal_deixa_a_coluna_nula_e_a_proxima_passagem_tenta(
    session: AsyncSession, semear_corretor
) -> None:
    """D3, o outro lado: falha de rede e o caso em que retentar resolve.

    A faixa e o teto da retentativa -- quando ela fecha, a linha deixa de
    aparecer na consulta.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    que_falha = OutboundFake(get_sessionmaker(), erro=EnvioRetentavel("5xx"))
    assert await sweep_lembretes(_ctx(que_falha), agora=INICIO - timedelta(hours=24)) == 0
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is None

    bom = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(bom), agora=INICIO - timedelta(hours=23)) == 1
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None


async def test_sem_mensagem_do_lead_nao_ha_de_quem_mandar(
    session: AsyncSession, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    """Sem ancora nao ha `recipient_external_id`, que e o "de" do canal.

    Mesmo desfecho e mesmo motivo que `_avisar_lead` da TEC-170 documenta. A
    coluna e gravada porque a ausencia de fala do lead nao se resolve sozinha
    nas passagens seguintes.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=await _imovel(session)
    )

    outbound = OutboundFake(get_sessionmaker())
    with caplog.at_level(logging.INFO):
        assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 0

    assert outbound.entregues == []
    assert eventos_de_log(caplog, "lembrete.sem_ancora")
    linha = await _recarregar(session, agendamento.id)
    assert linha.lembrete_24h_em is not None


# ------------------------------------------------------- as formas do texto


async def test_visita_sem_imovel_nao_inventa_endereco(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(session, corretor_id=corretor.id, imovel_id=None)
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 1
    assert "None" not in outbound.entregues[0]
    assert "AP-001" not in outbound.entregues[0]


async def test_reuniao_remota_nao_leva_endereco(session: AsyncSession, semear_corretor) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _agendamento(
        session,
        corretor_id=corretor.id,
        imovel_id=await _imovel(session),
        tipo=str(TipoDeCompromisso.REUNIAO_REMOTA),
    )
    await _mensagem_do_lead(session, criada_em=INICIO - timedelta(hours=25))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24)) == 1
    assert "remota" in outbound.entregues[0]
    assert "AP-001" not in outbound.entregues[0]


# --------------------------------------------------------------- o lote


async def test_uma_falha_nao_derruba_os_outros_do_lote(
    session: AsyncSession, semear_corretor
) -> None:
    """Molde de `sweep_followups`: cada linha em seu `try`.

    O primeiro agendamento nao tem fala do lead e o segundo tem. O primeiro
    nao pode custar o lembrete do segundo.

    Os dois no MESMO horario, para os dois lembretes vencerem na mesma
    passagem -- e por isso com corretores diferentes, que e o que a exclusao
    por intervalo (`ex_agendamentos_sem_sobreposicao`) separa.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    outro_corretor = await semear_corretor(email="bruno@imob.com.br")
    imovel = await _imovel(session)
    outra_conversa = "5511922222222"

    await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel)

    segundo = Agendamento(
        id=uuid.uuid4(),
        corretor_id=outro_corretor.id,
        channel=CANAL,
        conversation_key=outra_conversa,
        imovel_id=imovel,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=INICIO,
        fim=FIM,
        status=StatusDoAgendamento.CONFIRMADO,
        reservado_ate=INICIO,
        criado_em=CONFIRMADO_EM,
        confirmado_em=CONFIRMADO_EM,
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
    )
    session.add(segundo)
    session.add(
        Message(
            id=uuid.uuid4(),
            channel=CANAL,
            provider_message_id=f"wamid.{uuid.uuid4().hex[:10]}",
            sender_external_id=outra_conversa,
            recipient_external_id="222222222",
            conversation_key=outra_conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            created_at=INICIO - timedelta(hours=25),
        )
    )
    await session.commit()

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lembretes(_ctx(outbound), agora=INICIO - timedelta(hours=24))

    assert enviados == 1
    assert len(outbound.entregues) == 1


def test_sweep_lembretes_esta_no_cron_de_cinco_em_cinco_minutos() -> None:
    """Sem este teste, apagar a entrada `cron(...)` nao quebra nada: os testes
    acima chamam a funcao direto, sem passar pelo `WorkerSettings`.

    O sintoma silencioso seria lembrete nenhum saindo em producao, com a suite
    inteira desta card verde. Ver o irmao de `sweep_followups` em
    `test_worker_startup.py`, que explica por que `functions` e `cron_jobs`
    sao duas afirmacoes diferentes.
    """
    from mobia.workers.main import WorkerSettings

    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == "sweep_lembretes"
    )
    assert registrada.keep_result_s == 0

    candidatos = [job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_lembretes]
    assert len(candidatos) == 1
    assert candidatos[0].minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
    assert candidatos[0].run_at_startup is False
