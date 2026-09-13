"""A notificacao do handoff, de ponta a ponta. TEC-177, RN-16.2."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal
from mobia.domain.notificacao.destinatario import destinatario_do_handoff
from mobia.domain.notificacao.mensagem import montar
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.port import OutboundPort
from mobia.infra.crypto import decrypt

log = structlog.get_logger(__name__)

# O `kind` do aviso ao lead. Chaveado na ULTIMA mensagem DO LEAD da conversa, e
# nao no handoff: a UNIQUE (message_id, kind) de `outbound_dispatches` da a
# deduplicacao, e a guarda de opt-out de `GuardedOutbound` vem junto -- um lead
# que pediu para nao ser contatado nao recebe, e nao foi preciso escrever nada
# para isso. Ver a D5 do desenho.
KIND_DA_JANELA_HUMANA = "janela_humana"

TEXTO_DA_JANELA_HUMANA = (
    "Ja avisei um corretor sobre a sua conversa. "
    "O atendimento humano funciona de segunda a sabado, das {inicio}h as {fim}h, "
    "entao a resposta deve vir na proxima janela."
)


async def notificar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    canais: Sequence[CanalDeNotificacaoPort],
    outbound: OutboundPort,
    handoff_id: uuid.UUID,
) -> bool:
    """Notifica o corretor do handoff pelos canais dados. Devolve se alguem recebeu.

    **Sessao por FACTORY, nao por instancia** -- mesma razao de `_agendar_resumo`
    (TEC-175) e de `GuardedOutbound`: as chamadas a `canal.enviar` sao rede, e
    uma transacao aberta durante um envio de rede e exatamente o que este
    desenho evita. Por isso a funcao abre tres sessoes curtas em vez de uma
    unica que atravessaria os `await canal.enviar(...)` do meio.

    **Cada canal, no seu proprio `try`, capturando SO `FalhaDeCanal`.** Um
    `except Exception` ali engoliria `TypeError`/`AttributeError` como se
    fossem falha de entrega, e o handoff sairia marcado como pendente de aviso
    manual por um bug que ninguem veria -- ver o docstring de `FalhaDeCanal`.

    **NUNCA loga `corpo` nem o resumo decifrado.** E prosa destilada do que o
    lead escreveu, a mesma razao de `handoffs.resumo` ser cifrado em repouso.
    """
    agora = datetime.now(UTC)

    async with session_factory() as session:
        handoff = (
            await session.execute(select(Handoff).where(Handoff.id == handoff_id))
        ).scalar_one_or_none()
        if handoff is None:
            # Sumiu entre o agendamento e a execucao (um TRUNCATE de teste, uma
            # limpeza futura) -- nao e erro de quem chama, e nao ha o que gravar.
            log.error("notificacao.handoff_sumiu", handoff_id=str(handoff_id))
            return False

        corretor = await destinatario_do_handoff(session, handoff=handoff)
        if corretor is None:
            handoff.aviso_manual_pendente = True
            await session.commit()
            log.error(
                "notificacao.sem_destinatario",
                handoff_id=str(handoff_id),
                motivo="nenhum corretor alocado nem de plantao",
            )
            return False

        # Tudo que sobrevive ao fechamento desta sessao vira variavel local --
        # o objeto `handoff`/`corretor` nao atravessa as sessoes seguintes.
        channel = handoff.channel
        conversation_key = handoff.conversation_key
        resumo_texto = decrypt(handoff.resumo, aad_do_resumo_de_handoff(handoff.id))
        link = link_da_transcricao(handoff.channel, handoff.conversation_key)
        assunto, corpo = montar(
            resumo=resumo_texto,
            link=link,
            etiqueta=handoff.etiqueta,
            prioridade=handoff.prioridade,
        )
        # `canal.nome` -> destino. So os dois canais que `canais.py` define
        # hoje; um `canal.nome` fora deste mapa e configuracao errada, e o
        # KeyError que ele produz sobe cru, como o defeito de programacao que
        # e -- nao vira `aviso_manual_pendente` por engano.
        destino_por_canal = {
            "email": corretor.email,
            "whatsapp": corretor.telefone,
        }
        corretor_horario_inicio = corretor.horario_inicio
        corretor_horario_fim = corretor.horario_fim

    # FORA de qualquer transacao -- e o ponto inteiro da factory acima.
    motivos: dict[str, str] = {}
    algum_canal_aceitou = False
    for canal in canais:
        destino = destino_por_canal[canal.nome]
        try:
            await canal.enviar(destino=destino, assunto=assunto, corpo=corpo)
        except FalhaDeCanal as falha:
            motivos[canal.nome] = str(falha)
        else:
            algum_canal_aceitou = True

    async with session_factory() as session:
        if algum_canal_aceitou:
            await session.execute(
                update(Handoff)
                .where(Handoff.id == handoff_id)
                .values(notificado_em=agora, atualizado_em=agora)
            )
        else:
            await session.execute(
                update(Handoff)
                .where(Handoff.id == handoff_id)
                .values(aviso_manual_pendente=True, atualizado_em=agora)
            )
        await session.commit()

    if not algum_canal_aceitou:
        log.error("notificacao.nenhum_canal_aceitou", handoff_id=str(handoff_id), motivos=motivos)
        return False

    # O corretor ja foi avisado nesta altura -- o que segue e secundario, e
    # nao pode derrubar o `True` que a linha acima ja ganhou. Mesmo molde do
    # `_agendar_resumo`/`_encaminhar_por_erro`: falha aqui vira log e segue.
    if not horario_permite_envio(
        momento=datetime.now(UTC),
        inicio=corretor_horario_inicio,
        fim=corretor_horario_fim,
        fuso=get_settings().fuso_de_envio,
    ):
        await _avisar_lead_da_janela_humana(
            session_factory,
            outbound=outbound,
            channel=channel,
            conversation_key=conversation_key,
            inicio=corretor_horario_inicio,
            fim=corretor_horario_fim,
        )

    return True


async def _avisar_lead_da_janela_humana(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    outbound: OutboundPort,
    channel: str,
    conversation_key: str,
    inicio: int,
    fim: int,
) -> None:
    """Avisa o lead que o corretor so responde na proxima janela.

    **Chaveado na mensagem mais recente DO LEAD (`MessageRole.LEAD`), nao na
    mais recente da conversa.** Uma linha de SAIDA do agente grava o proprio
    numero do lead em `recipient_external_id` (ver `turno.py`) -- ali dentro
    esse campo responde "para quem foi", nao "de quem". Usar a mais recente
    qualquer arriscaria pegar uma dessas e mandar o aviso sair do numero
    errado. A mensagem do lead e a unica que carrega, em
    `recipient_external_id`, o numero do PROPRIO canal que fala com ele -- o
    mesmo campo que `_encaminhar_por_erro` (`process_message.py`) usa como
    `"de"` ao responder.

    **Sem mensagem nenhuma do lead nesta conversa, o aviso e pulado.** Um
    handoff nasce de uma fala do lead, entao isso nao deveria acontecer em
    producao; mas sem uma linha de onde tirar o `message_id` e o `"de"`, nao
    ha como montar a chamada -- so um log marca a lacuna.

    **Excecao daqui nunca sobe.** O corretor ja foi avisado antes desta
    chamada; perder o aviso ao lead e secundario e vira log, no mesmo molde
    do `_agendar_resumo` da TEC-175.
    """
    async with session_factory() as session:
        ultima_do_lead = (
            await session.execute(
                select(Message)
                .where(
                    Message.channel == channel,
                    Message.conversation_key == conversation_key,
                    Message.role == MessageRole.LEAD,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if ultima_do_lead is None:
        log.info(
            "notificacao.aviso_ao_lead_sem_mensagem",
            channel=channel,
            conversation_key=conversation_key,
        )
        return

    try:
        await outbound.send(
            ultima_do_lead.id,
            KIND_DA_JANELA_HUMANA,
            {
                "para": conversation_key,
                "de": ultima_do_lead.recipient_external_id,
                "texto": TEXTO_DA_JANELA_HUMANA.format(inicio=inicio, fim=fim),
            },
        )
    except Exception as falha:
        log.warning(
            "notificacao.aviso_ao_lead_falhou",
            channel=channel,
            conversation_key=conversation_key,
            reason=type(falha).__name__,
        )
