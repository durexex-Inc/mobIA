"""A notificacao do handoff, de ponta a ponta. TEC-177, RN-16.2."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.handoff.sla import limite_de_aceite, prazo_em_minutos
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal
from mobia.domain.notificacao.destinatario import destinatario_do_handoff
from mobia.domain.notificacao.mensagem import montar
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.port import OutboundPort
from mobia.infra.crypto import DecryptionError, decrypt

log = structlog.get_logger(__name__)

# Mora aqui, e nao em `workers/jobs/notificar.py` (onde nasceu na TEC-177),
# porque `domain/handoff/recuperacao.py` (TEC-279) precisa da constante para
# reenfileirar este job pelo mesmo `_job_id` -- e nenhum modulo de
# `src/mobia/domain/` importa `mobia.workers` hoje; a direcao e sempre a
# inversa. Mesma razao de `GERAR_RESUMO_JOB` morar em
# `domain/handoff/agendador.py`. `workers/jobs/notificar.py` importa esta
# constante daqui, para o nome do job ARQ continuar unico.
NOTIFICAR_JOB = "notificar_corretor"

# O `kind` do aviso ao lead. Chaveado na ULTIMA mensagem DO LEAD da conversa, e
# nao no handoff: a UNIQUE (message_id, kind) de `outbound_dispatches` da a
# deduplicacao, e a guarda de opt-out de `GuardedOutbound` vem junto -- um lead
# que pediu para nao ser contatado nao recebe, e nao foi preciso escrever nada
# para isso. Ver a D5 do desenho.
KIND_DA_JANELA_HUMANA = "janela_humana"

# **Nao afirma que um corretor foi avisado, nem que alguem vai responder.**
# Nenhuma das duas coisas e garantida hoje: os dois adaptadores de `canais.py`
# REGISTRAM e NAO ENTREGAM -- o e-mail nao tem provedor configurado neste
# projeto, o whatsapp ao corretor exige template aprovado pela Meta que nao
# existe --, entao `notificar` devolver `True` so significa "um canal aceitou
# a mensagem", nunca "um corretor recebeu" ou "um corretor vai responder".
# Este repo ja pagou por essa frase exata uma vez: o aviso ao lead da
# TEC-174 tambem dizia "ja avisei um corretor" e teve de ser reescrito
# porque a notificacao (esta card, TEC-177) ainda nao existia -- ver o
# fluxo de saida de card no CLAUDE.md. Nao reintroduza a promessa.
#
# "de segunda a sabado" e literal fixo, nao vem do `Corretor`: a L2 do
# desenho declara que o modelo nao tem dia da semana, so uma janela unica de
# horas (`horario_inicio`/`horario_fim`), e a checagem de `horario_permite_envio`
# compara so a hora. O texto bate com o PR-06 do SRS hoje, mas o sistema trata
# domingo como dia util enquanto esta frase promete que nao -- ela vai
# divergir em silencio quando a agenda por dia (TEC-170) chegar, e tera de
# mudar junto.
TEXTO_DA_JANELA_HUMANA = (
    "O atendimento humano funciona de segunda a sabado, das {inicio}h as {fim}h. "
    "Fora desse horario a resposta pode demorar mais."
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

    **O aviso ao lead sobre a janela humana roda independente do retorno.**
    Ele so informa o horario de atendimento -- nunca que um corretor foi
    avisado -- entao dispara sempre que ha destinatario e a jornada dele
    esta fechada, mesmo quando nenhum canal aceitou a notificacao. Ver o
    comentario de `TEXTO_DA_JANELA_HUMANA`.
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
            # Sem corretor nao ha jornada contra a qual contar um prazo -- dar
            # um prazo generico inventaria um dono que nao existe. Escala na
            # hora, com `sla_limite_em` nulo PARA SEMPRE (emenda E-02 da
            # RN-16.3): "ninguem sequer foi avisado" e a versao mais forte do
            # que esta card leva ao gerente.
            handoff.aviso_manual_pendente = True
            handoff.status = Status.ESCALADO
            handoff.atualizado_em = agora
            await session.commit()
            log.error(
                "notificacao.sem_destinatario",
                handoff_id=str(handoff_id),
                motivo="nenhum corretor alocado nem de plantao, escalado na hora",
            )
            return False

        # A temperatura vem de `lead_qualification`, NUNCA do `gatilho` do
        # handoff (D2, emenda E-01 da RN-16.3): `LEAD_QUENTE` significa
        # "acabou de atravessar a borda", e um handoff aberto por
        # `PEDIDO_DE_HUMANO` sobre um lead que JA estava quente merece o
        # mesmo prazo de 15 minutos. `None` (par sem linha, ou linha anterior
        # a TEC-151) conta como nao-QUENTE em `prazo_em_minutos`.
        qualificacao = (
            await session.execute(
                select(LeadQualification).where(
                    LeadQualification.channel == handoff.channel,
                    LeadQualification.conversation_key == handoff.conversation_key,
                )
            )
        ).scalar_one_or_none()
        temperatura = qualificacao.temperatura if qualificacao is not None else None
        # D1: "gravado uma vez e nao recalculado" -- e nao e hipotese: a L3 da
        # TEC-177 (`keep_result=0` em `gerar_resumo`) deixa uma retentativa do
        # ARQ enfileirar `notificar` de novo DEPOIS de uma execucao anterior ja
        # ter concluido, e o proprio `notificar_corretor` retenta sozinho ate
        # `max_tries=5`. Recalcular incondicionalmente moveria o prazo para
        # frente a cada retentativa -- o mesmo defeito que a D8 evita para
        # `aceito_em`, aberto na coluna vizinha. `status == PENDENTE` importa
        # tanto quanto o prazo ja gravado: sem essa condicao, uma retentativa
        # tardia escreveria um prazo novo sobre um handoff ja ESCALADO ou
        # ACEITO, inventando um SLA depois do desfecho.
        if handoff.sla_limite_em is None and handoff.status == Status.PENDENTE.value:
            handoff.sla_limite_em = limite_de_aceite(
                inicio=agora,
                minutos=prazo_em_minutos(temperatura),
                jornada_inicio=corretor.horario_inicio,
                jornada_fim=corretor.horario_fim,
                fuso=get_settings().fuso_de_envio,
            )
        await session.commit()

        # Tudo que sobrevive ao fechamento desta sessao vira variavel local --
        # o objeto `handoff`/`corretor` nao atravessa as sessoes seguintes.
        channel = handoff.channel
        conversation_key = handoff.conversation_key
        # `DecryptionError` (rotacao de chave, escrita parcial, restore de
        # outro ambiente) degrada para None em vez de subir: sem esta guarda
        # e o unico modo de falha desta funcao sem caminho degradado, e nao e
        # mais raro que a queda de um canal -- o job falharia, retentaria,
        # falharia de novo, e o handoff terminaria sem `notificado_em` e sem
        # `aviso_manual_pendente`, invisivel para a fila futura da E8.
        # Mesmo argumento e mesmo molde do `contexto.resumo_ilegivel`
        # em `domain/context/montagem.py`. `TEXTO_SEM_RESUMO` (`mensagem.py`)
        # ja e o caminho degradado testado da D2 -- reusado aqui, nao um novo.
        try:
            resumo_texto = decrypt(handoff.resumo, aad_do_resumo_de_handoff(handoff.id))
        except DecryptionError as falha:
            resumo_texto = None
            log.warning(
                "notificacao.resumo_ilegivel",
                handoff_id=str(handoff_id),
                erro=type(falha).__name__,
            )
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
            # `aviso_manual_pendente=False` junto: as duas colunas dizem o
            # estado CORRENTE (D6 do desenho), nao um historico de tentativas.
            # Sem isto, um handoff que falhou (plantao ainda nao cadastrado)
            # e que depois e aceito numa retentativa do ARQ terminaria com
            # `notificado_em` preenchido E `aviso_manual_pendente` ainda
            # verdadeiro -- as duas dizendo coisas incompativeis ao mesmo
            # tempo. A TEC-178 chegou e NAO le este par: ela escala por
            # `status` e `sla_limite_em`. Entao o unico leitor previsto
            # destas duas colunas continua sendo o painel da E8, que nao
            # existe -- manter as duas coerentes e disciplina paga
            # adiantado, nao requisito de quem le hoje.
            await session.execute(
                update(Handoff)
                .where(Handoff.id == handoff_id)
                .values(notificado_em=agora, aviso_manual_pendente=False, atualizado_em=agora)
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

    # **Roda independente de `algum_canal_aceitou`.** O texto de
    # `TEXTO_DA_JANELA_HUMANA` nao promete que um corretor foi avisado -- so
    # informa a janela de atendimento humano, que e verdadeira nos dois casos:
    # o handoff existe quer o canal tenha aceitado quer nao, e a jornada do
    # corretor designado esta fechada (ou nao) independente disso. Gatear
    # pelo resultado dos canais faria sentido SE o texto ainda prometesse
    # entrega, mas ele nao promete mais -- ver o comentario da constante.
    # Falha aqui nunca derruba o retorno: mesmo molde do
    # `_agendar_resumo`/`_encaminhar_por_erro`.
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

    return algum_canal_aceitou


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

    **Excecao daqui nunca sobe.** Chamada depois de `notificar` ja ter
    decidido o desfecho do handoff (gravado `notificado_em` ou
    `aviso_manual_pendente`, tanto faz); perder o aviso ao lead e secundario e
    vira log, no mesmo molde do `_agendar_resumo` da TEC-175.
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
