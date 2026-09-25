"""O que acontece depois que o agendamento e confirmado. TEC-170, RN-12.1.

Tres passos independentes -- avisar o lead, avisar o corretor, criar o evento
na agenda dele --, cada um com a propria sessao curta e sem transacao aberta
durante chamada de rede (o molde de `notificar`, em `notificacao/envio.py`).
A falha de um vira alerta e nao impede o seguinte; nenhum escreve em
`status`. Cada passo tem a sua coluna como marca de feito, e e ela que deixa
o job ser reexecutado sem repetir nada (D2 do desenho).

**Nenhum caminho de producao chama isto ainda**: quem ligar o agendamento a
conversa enfileira o job depois do commit de `confirmar()`. Ver
docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agendamento.calendario import CalendarioPort, FalhaDeCalendario
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.mensagens import aviso_ao_corretor, texto_ao_lead
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal
from mobia.domain.outbound.port import OutboundPort

log = structlog.get_logger()

AVISAR_CONFIRMACAO_JOB = "avisar_confirmacao"
KIND_DA_CONFIRMACAO = "confirmacao_de_agendamento"


@dataclass(frozen=True)
class _Retrato:
    """O que os tres passos precisam, lido uma vez e fora de sessao.

    Os passos rodam com sessoes proprias; carregar os objetos do ORM de uma
    sessao ja fechada para dentro de outra convidaria atributo expirado.
    """

    id: uuid.UUID
    tipo: str
    inicio: datetime
    fim: datetime
    channel: str
    conversation_key: str
    corretor_nome: str
    corretor_email: str
    imovel: Imovel | None
    lead_avisado: bool
    corretor_avisado: bool
    evento_criado: bool


async def avisar_confirmacao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agendamento_id: uuid.UUID,
    outbound: OutboundPort,
    email: CanalDeNotificacaoPort,
    calendario: CalendarioPort,
    agora: datetime,
) -> None:
    """Os tres avisos de um agendamento CONFIRMADO; qualquer outro e no-op (D1)."""
    retrato = await _retratar(session_factory, agendamento_id)
    if retrato is None:
        return
    link = link_da_transcricao(retrato.channel, retrato.conversation_key)
    if not retrato.lead_avisado:
        await _avisar_lead(session_factory, retrato, outbound=outbound, agora=agora)
    if not retrato.corretor_avisado:
        await _avisar_corretor(session_factory, retrato, email=email, link=link, agora=agora)
    if not retrato.evento_criado:
        await _criar_evento(session_factory, retrato, calendario=calendario, link=link)


async def _retratar(
    session_factory: async_sessionmaker[AsyncSession], agendamento_id: uuid.UUID
) -> _Retrato | None:
    async with session_factory() as session:
        agendamento = await session.get(Agendamento, agendamento_id)
        if agendamento is None or agendamento.status != StatusDoAgendamento.CONFIRMADO:
            # O job pode ter sido enfileirado por um caminho que depois nao
            # commitou a confirmacao.
            log.info(
                "agendamento.confirmacao_ignorada",
                agendamento_id=str(agendamento_id),
                status=None if agendamento is None else agendamento.status,
            )
            return None
        corretor = await session.get(Corretor, agendamento.corretor_id)
        assert corretor is not None  # FK NOT NULL
        imovel = await session.get(Imovel, agendamento.imovel_id) if agendamento.imovel_id else None
        if imovel is not None:
            session.expunge(imovel)
        return _Retrato(
            id=agendamento.id,
            tipo=agendamento.tipo,
            inicio=agendamento.inicio,
            fim=agendamento.fim,
            channel=agendamento.channel,
            conversation_key=agendamento.conversation_key,
            corretor_nome=corretor.nome,
            corretor_email=corretor.email,
            imovel=imovel,
            lead_avisado=agendamento.lead_avisado_em is not None,
            corretor_avisado=agendamento.corretor_avisado_em is not None,
            evento_criado=agendamento.calendar_event_id is not None,
        )


async def _marcar(
    session_factory: async_sessionmaker[AsyncSession], agendamento_id: uuid.UUID, **valores: object
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Agendamento).where(Agendamento.id == agendamento_id).values(**valores)
        )
        await session.commit()


async def _avisar_lead(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    outbound: OutboundPort,
    agora: datetime,
) -> None:
    # Ancorado na ultima mensagem DO LEAD, pelo motivo que a docstring de
    # `_avisar_lead_da_janela_humana` (`notificacao/envio.py`) explica: e ela
    # que carrega, em `recipient_external_id`, o numero do canal que fala com
    # ele.
    async with session_factory() as session:
        ultima_do_lead = (
            await session.execute(
                select(Message)
                .where(
                    Message.channel == retrato.channel,
                    Message.conversation_key == retrato.conversation_key,
                    Message.role == MessageRole.LEAD,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if ultima_do_lead is None:
        log.info("agendamento.aviso_ao_lead_sem_mensagem", agendamento_id=str(retrato.id))
        return
    texto = texto_ao_lead(
        tipo=retrato.tipo,
        inicio=retrato.inicio,
        corretor=retrato.corretor_nome,
        imovel=retrato.imovel,
    )
    try:
        aceito = await outbound.send(
            ultima_do_lead.id,
            KIND_DA_CONFIRMACAO,
            {
                "para": retrato.conversation_key,
                "de": ultima_do_lead.recipient_external_id,
                "texto": texto,
            },
        )
    # `except Exception` aqui, e nao a lista curta dos outros passos: e o
    # mesmo contrato de `_avisar_lead_da_janela_humana`, porque o `outbound`
    # levanta tipos distintos por adaptador (`EnvioRetentavel`,
    # `EnvioRecusado`, `EnvioForaDaJanela`) e nenhum deles pode impedir o
    # aviso ao corretor.
    except Exception as falha:
        log.error(
            "agendamento.aviso_ao_lead_falhou",
            agendamento_id=str(retrato.id),
            reason=type(falha).__name__,
        )
        return
    if not aceito:
        # A guarda recusou (opt-out, atendimento humano) ou a mesma chave ja
        # tinha saido: nao e falha, e a coluna fica nula.
        log.info("agendamento.aviso_ao_lead_recusado", agendamento_id=str(retrato.id))
        return
    await _marcar(session_factory, retrato.id, lead_avisado_em=agora)


async def _avisar_corretor(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    email: CanalDeNotificacaoPort,
    link: str,
    agora: datetime,
) -> None:
    aviso = aviso_ao_corretor(
        tipo=retrato.tipo,
        inicio=retrato.inicio,
        corretor=retrato.corretor_nome,
        imovel=retrato.imovel,
        channel=retrato.channel,
        conversation_key=retrato.conversation_key,
        link=link,
    )
    try:
        await email.enviar(destino=retrato.corretor_email, aviso=aviso)
    except FalhaDeCanal as falha:
        log.error(
            "agendamento.aviso_ao_corretor_falhou",
            agendamento_id=str(retrato.id),
            reason=type(falha).__name__,
        )
        return
    await _marcar(session_factory, retrato.id, corretor_avisado_em=agora)


async def _criar_evento(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    calendario: CalendarioPort,
    link: str,
) -> None:
    remota = retrato.tipo == TipoDeCompromisso.REUNIAO_REMOTA
    titulo = "Reunião remota" if remota else "Visita"
    if not remota and retrato.imovel is not None:
        titulo = f"{titulo}: {retrato.imovel.titulo} ({retrato.imovel.codigo})"
    try:
        identificador = await calendario.criar_evento(
            inicio=retrato.inicio,
            fim=retrato.fim,
            titulo=titulo,
            descricao=f"Lead: {retrato.channel} {retrato.conversation_key}\n{link}",
            convidado=retrato.corretor_email,
        )
    except FalhaDeCalendario as falha:
        log.error(
            "agendamento.calendario_falhou",
            agendamento_id=str(retrato.id),
            reason=str(falha),
        )
        return
    if identificador is not None:
        await _marcar(session_factory, retrato.id, calendar_event_id=identificador)
