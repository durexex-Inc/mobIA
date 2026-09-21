"""Os returns antecipados de `executar_turno` e a moderacao de entrada.

Antes da TEC-297 a moderacao rodava num ponto so, depois de cinco saidas que
retornam antes dele. A fala que disparava qualquer uma delas nunca era
moderada: `bloqueada_em` ficava nulo e os leitores dessa coluna a tratavam
como fala legitima.

O que este arquivo prova, parametrizado nos cinco ramos (silenciado,
atendimento humano, fora de escopo, opt-out e pedido de humano): a marca, a
auditoria no mesmo commit (TEC-142), e a AUSENCIA em `literais_apos` -- a
funcao de producao por onde todo contexto e todo resumo passam, e por isso a
prova de que a fala nao chega ao prompt nem ao resumo permanente (TEC-236).
Tambem prova que nenhum dos cinco ramos entrega a recusa de entrada (D2), que
o handoff existe antes de a moderacao ser chamada (CA-04.3) e que o
fail-open nao custa a acao do ramo. `test_mensagem_sem_corpo_nao_paga_moderacao`
prova que audio/imagem/documento nao pagam moderacao nenhuma.
"""

import uuid
from datetime import UTC, datetime

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import Direcao
from mobia.infra.db import get_sessionmaker

TEXTO_REPROVAVEL = "quero falar com uma pessoa agora"


async def _preparar_silenciado(session, **_):
    """Ramo #1: lead ja em opt-out. Fala anterior registra o opt-out."""
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.optout.repositorio import registrar_optout

    anterior = await _entrada_do_lead(session, texto="parar")
    await registrar_optout(
        get_sessionmaker(),
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        message_id=anterior.id,
    )
    return "qualquer coisa"


async def _preparar_atendimento_humano(session, *, semear_corretor, **_):
    """Ramo #2: handoff ja assumido. O de maior volume dos cinco."""
    from mobia.domain.atendimento.repositorio import assumir

    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()
    return "qualquer coisa"


async def _preparar_fora_de_escopo(session, **_):
    """Ramo #3: conversa encerrada por fora de escopo, dentro da janela."""
    from mobia.domain.conversa.repositorio import encerrar_conversa
    from mobia.domain.conversa.vocabulario import MotivoDoEncerramento

    await encerrar_conversa(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=datetime.now(UTC),
    )
    await session.commit()
    return "qualquer coisa"


async def _preparar_opt_out(session, **_):
    """Ramo #4: a propria fala pede opt-out."""
    return "parar"


async def _preparar_pedido_de_humano(session, **_):
    """Ramo #5: a propria fala pede humano."""
    return TEXTO_REPROVAVEL


OS_CINCO_RAMOS = [
    ("silenciado", _preparar_silenciado),
    ("atendimento_humano", _preparar_atendimento_humano),
    ("fora_de_escopo", _preparar_fora_de_escopo),
    ("opt_out", _preparar_opt_out),
    ("pedido_de_humano", _preparar_pedido_de_humano),
]


@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_fala_reprovavel_e_marcada_e_sai_da_janela_nos_cinco_ramos(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """A garantia da TEC-236, provada pela janela real e nao pelo desfecho.

    `literais_apos` e a funcao de producao por onde TODO contexto e TODO
    resumo passam -- `dividir` recebe o que ela devolve, entao o que nao sai
    dela nunca chega a dobra dos ~40 turnos. Asserir pelo desfecho do turno
    provaria so que o ramo retornou, que e o que ja acontecia quando o
    defeito existia.
    """
    from mobia.domain.context.janela import literais_apos

    texto = await preparar(session, semear_corretor=semear_corretor)
    moderador = moderador_fake(bloqueia_entrada=True)

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=texto,
    )

    assert desfecho == desfecho_esperado
    # `.direcoes` e nao `.entradas`: pega tanto "moderou demais" quanto
    # "moderou na direcao errada", e e a forma que os cinco testes da Task 3
    # usavam antes de serem revertidos.
    assert moderador.direcoes == [Direcao.ENTRADA]

    marcadas = (
        (
            await session.execute(
                select(Message).where(
                    Message.channel == CANAL_AGENTE,
                    Message.conversation_key == CONVERSA_AGENTE,
                    Message.bloqueada_em.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(marcadas) == 1

    eventos = (
        (
            await session.execute(
                select(ModerationEvent).where(ModerationEvent.message_id == marcadas[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(eventos) == 1, "marca e auditoria no mesmo commit (TEC-142)"

    na_janela = await literais_apos(session, CANAL_AGENTE, CONVERSA_AGENTE, None)
    assert marcadas[0].id not in {linha.id for linha in na_janela}, (
        "a fala bloqueada nao pode entrar no contexto nem, por consequencia, no resumo"
    )


@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_nenhum_dos_cinco_ramos_entrega_recusa(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """A D2: marca e auditoria, sem recusa.

    Nos ramos silenciosos a recusa quebraria o silencio que a guarda existe
    para manter. No ramo do opt-out seria mandar uma segunda mensagem a quem
    acabou de pedir para sair -- a violacao que a RN-14.1 existe para impedir.
    """
    from mobia.domain.moderacao.port import (
        KIND_DA_RECUSA_DE_ENTRADA,
        TEXTO_DA_RECUSA_DE_ENTRADA,
    )
    from mobia.domain.outbound.repositorio import kinds_reservados

    texto = await preparar(session, semear_corretor=semear_corretor)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
        texto=texto,
    )

    assert not any(TEXTO_DA_RECUSA_DE_ENTRADA in entregue for entregue in entregador.entregues)

    # A asserta sobre `entregues` sozinha e fraca: ela nao pega uma recusa que
    # RESERVOU o kind e falhou na entrega. `kinds_reservados` responde
    # "encerrado", nao "entregue", e e por isso que ela e a asserta forte aqui.
    marcada = (
        await session.execute(
            select(Message).where(
                Message.channel == CANAL_AGENTE,
                Message.conversation_key == CONVERSA_AGENTE,
                Message.bloqueada_em.is_not(None),
            )
        )
    ).scalar_one()
    reservados = await kinds_reservados(get_sessionmaker(), message_id=marcada.id)
    assert KIND_DA_RECUSA_DE_ENTRADA not in reservados


async def test_o_handoff_existe_antes_de_a_moderacao_ser_chamada(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    rodar_turno,
) -> None:
    """Trava a CA-04.3: "um handoff e criado em ate 5 s".

    O prazo mede ate a LINHA existir, e a moderacao tem teto de 5s sozinha.
    Se alguem mover a moderacao para antes de `registrar_handoff`, o pior caso
    do prazo dobra -- e o teste que pega isso nao pode ser sobre latencia
    (flake em runner compartilhado), tem de ser sobre ORDEM. Dai o duble que
    consulta o banco no momento em que e chamado.
    """
    from mobia.domain.handoff.models import Handoff
    from mobia.domain.moderacao.port import Veredito

    handoffs_no_momento_da_moderacao: list = []

    class _ModeradorQueOlhaOBanco:
        def __init__(self) -> None:
            self.entradas = 0

        async def moderar(self, texto, *, direcao):
            self.entradas += 1
            async with get_sessionmaker()() as sessao:
                linhas = (
                    (
                        await sessao.execute(
                            select(Handoff).where(
                                Handoff.channel == CANAL_AGENTE,
                                Handoff.conversation_key == CONVERSA_AGENTE,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                handoffs_no_momento_da_moderacao.extend(linhas)
            return Veredito(bloqueado=True, motivo="fake", categoria="DISCRIMINACAO")

    moderador = _ModeradorQueOlhaOBanco()

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=TEXTO_REPROVAVEL,
    )

    assert desfecho == "pedido_de_humano"
    assert moderador.entradas == 1
    assert len(handoffs_no_momento_da_moderacao) == 1, (
        "o handoff tem de estar gravado ANTES de a chamada paga acontecer (CA-04.3)"
    )


@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_moderacao_indisponivel_nao_impede_a_acao_do_ramo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """Fail-open: provedor caido nao pode custar o opt-out nem o handoff.

    A consequencia e honesta e esta declarada: provedor fora do ar significa
    fala nao moderada entrando no contexto, como ja acontece no turno normal.
    """
    from mobia.domain.moderacao.port import ModeracaoIndisponivel

    texto = await preparar(session, semear_corretor=semear_corretor)
    moderador = moderador_fake(erro_na_entrada=ModeracaoIndisponivel("provedor fora"))

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=texto,
    )

    assert desfecho == desfecho_esperado, "o ramo acontece igual"
    marcadas = (
        (await session.execute(select(Message).where(Message.bloqueada_em.is_not(None))))
        .scalars()
        .all()
    )
    assert marcadas == [], "indisponivel nao marca nada"


async def test_mensagem_sem_corpo_nao_paga_moderacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """O `if corpo` mudou de lugar e continua valendo.

    Audio, imagem e documento chegam com `text_body` nulo. Moderar ali
    mandaria string vazia ao provedor e pagaria por nada.

    `_entrada_do_lead` nao aceita `texto=None` (tipo `str`, sempre cifra
    algo), e `gravar` de `test_rajada.py` tambem nao -- as duas sempre
    cifram um corpo. A linha e montada direto, no mesmo molde de
    `_mensagem_sem_texto_gravada` (`test_turno_optout.py:62-86`), que ja
    prova esse caminho contra `executar_turno`.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_AGENTE,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA_AGENTE,
        recipient_external_id="222222222",
        conversation_key=CONVERSA_AGENTE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.AUDIO,
        text_body=None,
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    moderador = moderador_fake()

    await executar_turno(
        get_sessionmaker(),
        message=linha,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=moderador,
        agendador=AgendadorNoop(),
    )

    assert moderador.entradas == 0
