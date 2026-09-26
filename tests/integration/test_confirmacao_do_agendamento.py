"""Os tres avisos de um agendamento CONFIRMADO, de ponta a ponta. TEC-170.

Arquivo autocontido, como os demais de integracao deste repo: `_imovel` e
copiado de `test_busca_no_turno.py`, e os dubles de `_CanalEspiao` /
`_CanalQueFalha` de `test_notificacao_envio.py`. Onde a reserva de
`outbound_dispatches` e o que se testa, entra o `OutboundFake` do conftest,
que herda de `GuardedOutbound` e reserva de verdade.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import OutboundFake, eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.calendario import CalendarioNoop, FalhaDeCalendario
from mobia.domain.agendamento.confirmacao import avisar_confirmacao, kind_da_confirmacao
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.identidade.models import IdentidadeDeLead, aad_da_identidade
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.mensagem import Aviso
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.crypto import encrypt

SP = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 8, 27, 15, tzinfo=SP)
FIM = datetime(2026, 8, 27, 16, tzinfo=SP)
CANAL = "whatsapp"
CONVERSA = "5511911111111"
AGORA = datetime(2026, 8, 27, 20, tzinfo=UTC)


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    """Um imovel disponivel para venda. Copiado de test_busca_no_turno.py --
    os arquivos de integracao deste repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "bairro": "Moema",
        "bairro_busca": "moema",
        "cidade": "São Paulo",
        "uf": "SP",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def _agendamento(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    imovel_id: uuid.UUID,
    status: str = StatusDoAgendamento.CONFIRMADO,
    inicio: datetime = INICIO,
    fim: datetime = FIM,
) -> Agendamento:
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=CANAL,
        conversation_key=CONVERSA,
        imovel_id=imovel_id,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=fim,
        status=status,
        reservado_ate=INICIO,
        criado_em=INICIO,
        confirmado_em=INICIO if status == StatusDoAgendamento.CONFIRMADO else None,
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _identidade(session: AsyncSession) -> None:
    """A identidade por tras de CONVERSA -- TEC-203: `descrever_lead` revela o
    telefone, e sem esta linha `telefones_de` devolve `None`. `valor` e o
    proprio CONVERSA porque ele ja e um telefone canonico valido."""
    session.add(
        IdentidadeDeLead(
            channel=CANAL,
            conversation_key=CONVERSA,
            valor_cifrado=encrypt(CONVERSA, aad_da_identidade(CANAL, CONVERSA)),
        )
    )
    await session.commit()


async def _mensagem_do_lead(session: AsyncSession) -> Message:
    """Copiado do molde de `semear`, em tests/conftest.py."""
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
    )
    session.add(mensagem)
    await session.commit()
    return mensagem


async def _recarregar(session: AsyncSession, agendamento: Agendamento) -> Agendamento:
    # `id` capturado ANTES do expire: depois dele, ler `agendamento.id` dispara
    # um refresh sincrono contra a engine assincrona e derruba com
    # `MissingGreenlet` -- expirar apaga a PK em memoria junto com o resto.
    identificador = agendamento.id
    session.expire(agendamento)
    return (
        await session.execute(select(Agendamento).where(Agendamento.id == identificador))
    ).scalar_one()


class _OutboundEspiao:
    """Duble de OutboundPort: registra as chamadas e devolve um bool configuravel."""

    def __init__(self, *, aceita: bool = True) -> None:
        self.aceita = aceita
        self.chamadas: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        self.chamadas.append((message_id, kind, payload))
        return self.aceita


class _CanalEspiao:
    """Copiado de test_notificacao_envio.py."""

    def __init__(self, nome: str = "email") -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, Aviso]] = []

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        self.recebidas.append((destino, aviso))


class _CanalQueFalha:
    """Copiado de test_notificacao_envio.py."""

    def __init__(self, nome: str = "email") -> None:
        self.nome = nome

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        raise FalhaDeCanal(f"{self.nome} recusou")


class _OutboundQueLevanta:
    """`send` que levanta um tipo fora da lista curta, como um adaptador faria."""

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        raise RuntimeError("adaptador caiu")


class _CalendarioEspiao:
    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    async def criar_evento(
        self,
        *,
        evento_id: str,
        inicio: datetime,
        fim: datetime,
        titulo: str,
        descricao: str,
        convidado: str,
    ) -> str | None:
        self.chamadas.append(
            {
                "evento_id": evento_id,
                "inicio": inicio,
                "fim": fim,
                "titulo": titulo,
                "descricao": descricao,
                "convidado": convidado,
            }
        )
        return "evento-1"


class _CalendarioQueFalha:
    async def criar_evento(
        self,
        *,
        evento_id: str,
        inicio: datetime,
        fim: datetime,
        titulo: str,
        descricao: str,
        convidado: str,
    ) -> str | None:
        raise FalhaDeCalendario("Google inacessivel: ConnectError")


async def test_confirmado_avisa_lead_corretor_e_cria_evento(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)
    await _identidade(session)
    outbound, email, calendario = _OutboundEspiao(), _CanalEspiao(), _CalendarioEspiao()

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=outbound,
        email=email,
        calendario=calendario,
        agora=AGORA,
    )

    assert len(outbound.chamadas) == 1
    _, kind, payload = outbound.chamadas[0]
    assert kind == kind_da_confirmacao(agendamento.id)
    assert payload["para"] == CONVERSA
    assert payload["de"] == "222222222"
    assert "Moema" in payload["texto"]
    assert corretor.nome in payload["texto"]

    assert len(email.recebidas) == 1
    destino, aviso = email.recebidas[0]
    assert destino == corretor.email
    # TEC-203: `Lead:` leva o telefone revelado, e nao mais o `conversation_key` cru.
    assert f"+{CONVERSA}" in aviso.corpo

    assert len(calendario.chamadas) == 1
    chamada = calendario.chamadas[0]
    assert chamada["convidado"] == corretor.email
    assert chamada["inicio"] == INICIO
    assert chamada["fim"] == FIM
    assert chamada["evento_id"] == agendamento.id.hex

    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em == AGORA
    assert linha.corretor_avisado_em == AGORA
    assert linha.calendar_event_id == "evento-1"
    assert linha.status == StatusDoAgendamento.CONFIRMADO


async def test_calendario_indisponivel_nao_impede_os_avisos(
    session: AsyncSession, session_factory, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)

    with caplog.at_level("ERROR"):
        await avisar_confirmacao(
            session_factory,
            agendamento_id=agendamento.id,
            outbound=_OutboundEspiao(),
            email=_CanalEspiao(),
            calendario=_CalendarioQueFalha(),
            agora=AGORA,
        )

    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is not None
    assert linha.corretor_avisado_em is not None
    assert linha.calendar_event_id is None
    assert linha.status == StatusDoAgendamento.CONFIRMADO

    avisos = eventos_de_log(caplog, "agendamento.calendario_falhou")
    assert len(avisos) == 1
    assert avisos[0].nivel == "ERROR"


async def test_flag_desligada_nao_chama_calendario(
    session: AsyncSession, session_factory, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)

    with caplog.at_level("ERROR"):
        await avisar_confirmacao(
            session_factory,
            agendamento_id=agendamento.id,
            outbound=_OutboundEspiao(),
            email=_CanalEspiao(),
            calendario=CalendarioNoop(),
            agora=AGORA,
        )

    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is not None
    assert linha.corretor_avisado_em is not None
    assert linha.calendar_event_id is None

    assert eventos_de_log(caplog, "agendamento.calendario_falhou") == []


async def test_email_que_falha_vira_alerta_e_o_resto_segue(
    session: AsyncSession, session_factory, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)

    with caplog.at_level("ERROR"):
        await avisar_confirmacao(
            session_factory,
            agendamento_id=agendamento.id,
            outbound=_OutboundEspiao(),
            email=_CanalQueFalha(),
            calendario=_CalendarioEspiao(),
            agora=AGORA,
        )

    linha = await _recarregar(session, agendamento)
    assert linha.corretor_avisado_em is None
    assert linha.lead_avisado_em is not None
    assert linha.calendar_event_id is not None

    avisos = eventos_de_log(caplog, "agendamento.aviso_ao_corretor_falhou")
    assert len(avisos) == 1
    assert avisos[0].nivel == "ERROR"


async def test_reexecucao_nao_repete_nada(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)
    outbound, email, calendario = _OutboundEspiao(), _CanalEspiao(), _CalendarioEspiao()

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=outbound,
        email=email,
        calendario=calendario,
        agora=AGORA,
    )

    # Uma mensagem NOVA do lead entre as duas execucoes: se `_avisar_lead`
    # rodasse de novo, ela seria a candidata; a marca de feito e o que evita.
    await _mensagem_do_lead(session)

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=outbound,
        email=email,
        calendario=calendario,
        agora=AGORA,
    )

    assert len(outbound.chamadas) == 1
    assert len(email.recebidas) == 1
    assert len(calendario.chamadas) == 1


async def test_guarda_do_outbound_recusa_e_lead_avisado_fica_nulo(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=_OutboundEspiao(aceita=False),
        email=_CanalEspiao(),
        calendario=_CalendarioEspiao(),
        agora=AGORA,
    )

    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is None
    assert linha.corretor_avisado_em is not None
    assert linha.calendar_event_id is not None


async def test_sem_mensagem_do_lead_pula_o_aviso_ao_lead(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    outbound = _OutboundEspiao()

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=outbound,
        email=_CanalEspiao(),
        calendario=_CalendarioEspiao(),
        agora=AGORA,
    )

    assert outbound.chamadas == []
    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is None
    assert linha.corretor_avisado_em is not None
    assert linha.calendar_event_id is not None


@pytest.mark.parametrize("status", [StatusDoAgendamento.RESERVADO, StatusDoAgendamento.EXPIRADO])
async def test_agendamento_nao_confirmado_e_no_op(
    status: str, session: AsyncSession, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(
        session, corretor_id=corretor.id, imovel_id=imovel_id, status=status
    )
    outbound, email, calendario = _OutboundEspiao(), _CanalEspiao(), _CalendarioEspiao()

    await avisar_confirmacao(
        session_factory,
        agendamento_id=agendamento.id,
        outbound=outbound,
        email=email,
        calendario=calendario,
        agora=AGORA,
    )

    assert outbound.chamadas == []
    assert email.recebidas == []
    assert calendario.chamadas == []
    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is None
    assert linha.corretor_avisado_em is None
    assert linha.calendar_event_id is None


async def test_agendamento_inexistente_e_no_op(session_factory) -> None:
    outbound, email, calendario = _OutboundEspiao(), _CanalEspiao(), _CalendarioEspiao()

    await avisar_confirmacao(
        session_factory,
        agendamento_id=uuid.uuid4(),
        outbound=outbound,
        email=email,
        calendario=calendario,
        agora=AGORA,
    )

    assert outbound.chamadas == []
    assert email.recebidas == []
    assert calendario.chamadas == []


def test_kind_da_confirmacao_cabe_na_coluna_e_e_um_por_agendamento() -> None:
    um, outro = uuid.uuid4(), uuid.uuid4()
    limite = OutboundDispatch.__table__.c.kind.type.length
    assert len(kind_da_confirmacao(um)) <= limite
    assert kind_da_confirmacao(um) == kind_da_confirmacao(um)
    assert kind_da_confirmacao(um) != kind_da_confirmacao(outro)


async def test_dois_agendamentos_da_mesma_mensagem_do_lead_saem_os_dois(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    """A reserva e UNIQUE (message_id, kind) e a ancora e a ultima mensagem do
    lead: com um kind fixo, o segundo agendamento confirmado sobre a mesma
    mensagem teria o `send` suprimido para sempre."""
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    primeiro = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    segundo = await _agendamento(
        session,
        corretor_id=corretor.id,
        imovel_id=imovel_id,
        inicio=datetime(2026, 8, 28, 15, tzinfo=SP),
        fim=datetime(2026, 8, 28, 16, tzinfo=SP),
    )
    await _mensagem_do_lead(session)
    outbound = OutboundFake(session_factory)

    for agendamento in (primeiro, segundo):
        await avisar_confirmacao(
            session_factory,
            agendamento_id=agendamento.id,
            outbound=outbound,
            email=_CanalEspiao(),
            calendario=_CalendarioEspiao(),
            agora=AGORA,
        )

    assert len(outbound.payloads) == 2
    assert "quinta-feira" in outbound.payloads[0]["texto"]
    assert "sexta-feira" in outbound.payloads[1]["texto"]
    assert (await _recarregar(session, primeiro)).lead_avisado_em == AGORA
    assert (await _recarregar(session, segundo)).lead_avisado_em == AGORA


async def test_outbound_que_levanta_vira_alerta_e_o_resto_segue(
    session: AsyncSession, session_factory, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    await _mensagem_do_lead(session)
    email, calendario = _CanalEspiao(), _CalendarioEspiao()

    with caplog.at_level("ERROR"):
        await avisar_confirmacao(
            session_factory,
            agendamento_id=agendamento.id,
            outbound=_OutboundQueLevanta(),
            email=email,
            calendario=calendario,
            agora=AGORA,
        )

    assert len(email.recebidas) == 1
    assert len(calendario.chamadas) == 1
    linha = await _recarregar(session, agendamento)
    assert linha.lead_avisado_em is None
    assert linha.corretor_avisado_em == AGORA
    assert linha.calendar_event_id == "evento-1"

    avisos = eventos_de_log(caplog, "agendamento.aviso_ao_lead_falhou")
    assert len(avisos) == 1
    assert avisos[0].nivel == "ERROR"


async def test_marca_de_feito_nao_sobrescreve_a_de_uma_execucao_concorrente(
    session: AsyncSession, session_factory, semear_corretor
) -> None:
    """Uma segunda execucao marca a coluna ENQUANTO esta espera o Google: a
    marca que chegou primeiro fica."""
    corretor = await semear_corretor(email="corretor@x.com")
    imovel_id = await _imovel(session)
    agendamento = await _agendamento(session, corretor_id=corretor.id, imovel_id=imovel_id)
    identificador = agendamento.id

    class _CalendarioComConcorrente(_CalendarioEspiao):
        async def criar_evento(self, **campos: Any) -> str | None:  # type: ignore[override]
            async with session_factory() as outra:
                await outra.execute(
                    update(Agendamento)
                    .where(Agendamento.id == identificador)
                    .values(calendar_event_id="da-outra-execucao")
                )
                await outra.commit()
            return await super().criar_evento(**campos)

    await avisar_confirmacao(
        session_factory,
        agendamento_id=identificador,
        outbound=_OutboundEspiao(),
        email=_CanalEspiao(),
        calendario=_CalendarioComConcorrente(),
        agora=AGORA,
    )

    linha = await _recarregar(session, agendamento)
    assert linha.calendar_event_id == "da-outra-execucao"
