"""O aviso ao corretor de que o agendamento caiu. TEC-172, RN-12.3.

Molde de `confirmacao.py::_avisar_corretor`: sessao curta para ler, chamada de
rede fora de transacao, e uma coluna como marca de resolvido. Falha de canal
vira alerta e deixa a coluna nula; erro de banco nao e capturado e sobe.

**Sem job ARQ e sem porta de enfileiramento, ao contrario da TEC-170.** Aquela
card tinha tres passos com rede -- outbound, e-mail e Google --, e enfileirar
tirava os tres do caminho do turno. Aqui e um passo e um canal, e **nao ha
chamador nenhum para servir**: quem ligar o cancelamento a conversa decide
naquele momento se chama isto em processo ou enfileira. Criar o job e a porta
agora seria superficie morta com duas copias do mesmo literal para manter em
sincronia.

**Nenhum caminho de producao chama isto**, e a TEC-371 nao mudou isso: ela
criou o caminho de marcar visita, e nao o de cancelar (que e a TEC-372). Ver
docs/superpowers/specs/2026-09-25-tec-172-cancelar-remarcar-e-nao-comparecimento-design.md.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agendamento.mensagens import aviso_de_cancelamento
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal

log = structlog.get_logger()

# TEC-372. O nome do job que chama esta funcao, pelo mesmo motivo que
# `AVISAR_CONFIRMACAO_JOB` mora em `confirmacao.py`: o dono da constante e
# o modulo que guarda a funcao de dominio, e o job fino a importa de la.
# Duas copias do literal e a deriva que quebra o enfileiramento em
# silencio.
AVISAR_CANCELAMENTO_JOB = "avisar_cancelamento"


async def avisar_cancelamento(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agendamento_id: uuid.UUID,
    email: CanalDeNotificacaoPort,
    agora: datetime,
) -> None:
    """Manda o e-mail do cancelamento, uma vez so.

    **So age sobre `CANCELADO`**, e qualquer outro estado e no-op com uma
    linha de log -- mesma guarda e mesma razao de `avisar_confirmacao`: quem
    chamar isto pode te-lo feito por um caminho que depois nao commitou o
    cancelamento.

    A marca de feito e `corretor_avisado_do_cancelamento_em`, **coluna
    propria** e nao a `corretor_avisado_em` da TEC-170: com uma coluna so, o
    aviso do cancelamento seria suprimido porque o da confirmacao ja tinha
    acontecido, e sao dois fatos diferentes sobre o mesmo agendamento.
    """
    async with session_factory() as session:
        agendamento = await session.get(Agendamento, agendamento_id)
        if agendamento is None or agendamento.status != StatusDoAgendamento.CANCELADO:
            log.info(
                "agendamento.cancelamento_ignorado",
                agendamento_id=str(agendamento_id),
                status=None if agendamento is None else agendamento.status,
            )
            return
        if agendamento.corretor_avisado_do_cancelamento_em is not None:
            return
        corretor = await session.get(Corretor, agendamento.corretor_id)
        assert corretor is not None  # FK NOT NULL
        imovel = await session.get(Imovel, agendamento.imovel_id) if agendamento.imovel_id else None
        # Solto da sessao pela razao de `_retratar` em `confirmacao.py`: o
        # envio roda com a sessao ja fechada, e um objeto do ORM preso a ela
        # convidaria atributo expirado.
        if imovel is not None:
            session.expunge(imovel)
        dados = (
            agendamento.tipo,
            agendamento.inicio,
            corretor.nome,
            corretor.email,
            agendamento.channel,
            agendamento.conversation_key,
        )

    tipo, inicio, corretor_nome, corretor_email, channel, conversation_key = dados
    link = link_da_transcricao(channel, conversation_key)
    aviso = aviso_de_cancelamento(
        tipo=tipo,
        inicio=inicio,
        corretor=corretor_nome,
        imovel=imovel,
        channel=channel,
        conversation_key=conversation_key,
        link=link,
    )
    try:
        await email.enviar(destino=corretor_email, aviso=aviso)
    except FalhaDeCanal as falha:
        # Alerta e log estruturado com nome estavel, que o monitoramento
        # externo casa -- nao ha sistema de alerta neste repo (TEC-177, D7).
        # A coluna fica nula, que e o registro de que o aviso nao saiu.
        log.error(
            "agendamento.aviso_de_cancelamento_falhou",
            agendamento_id=str(agendamento_id),
            reason=type(falha).__name__,
        )
        return

    async with session_factory() as session:
        # So grava onde a coluna ainda e nula, pela razao de `_marcar` em
        # `confirmacao.py`: uma execucao concorrente que marcou primeiro --
        # durante a chamada de rede desta -- fica com a marca dela.
        await session.execute(
            update(Agendamento)
            .where(
                Agendamento.id == agendamento_id,
                Agendamento.corretor_avisado_do_cancelamento_em.is_(None),
            )
            .values(corretor_avisado_do_cancelamento_em=agora)
        )
        await session.commit()
