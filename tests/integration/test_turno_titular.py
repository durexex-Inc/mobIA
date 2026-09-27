"""O turno detecta o pedido de titular, registra e confirma (TEC-207, D3).

No molde de `tests/integration/test_turno_optout.py`: mesmas fixtures de
`tests/conftest.py` para os dubles, e um helper proprio de semeadura porque o
texto do lead precisa ser controlado.

O que se prova aqui e a ORDEM do bloco no turno: ele roda antes do portao de
silencio por opt-out, antes da guarda de atendimento humano e antes da
moderacao de entrada -- quem ja pediu para sair, ou cuja conversa um corretor
assumiu, continua podendo exercer o direito, e a confirmacao sai com um kind
que fura as duas guardas de `GuardedOutbound.send`.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agente.turno import executar_turno
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.moderacao.port import Direcao
from mobia.domain.optout.models import OptoutEvent
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.titular.deteccao import (
    KIND_DA_PERGUNTA_DE_ELIMINACAO,
    TEXTO_DA_CONFIRMACAO_DE_ACESSO,
    TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO,
    TEXTO_DA_PERGUNTA_DE_ELIMINACAO,
)
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _mensagem_gravada(session, *, texto: str) -> Message:
    """Uma mensagem INBOUND com corpo cifrado, pronta para `executar_turno`.

    Copia de `_mensagem_gravada` de `test_turno_optout.py`.
    """
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA,
        recipient_external_id="222222222",
        conversation_key=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _rodar(session, texto, *, classificador, outbound, moderador, resumidor, contador):
    mensagem = await _mensagem_gravada(session, texto=texto)
    return await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador,
        resumidor=resumidor,
        contador=contador,
        outbound=outbound,
        moderador=moderador,
        agendador=AgendadorNoop(),
        agendador_de_avisos=AgendadorDeAvisosNoop(),
    )


async def _solicitacoes(session) -> list[SolicitacaoDeTitular]:
    # `expire_all` porque o turno escreve por sessoes proprias, e esta sessao
    # do teste pode ter as linhas em cache de uma leitura anterior.
    session.expire_all()
    return list((await session.execute(select(SolicitacaoDeTitular))).scalars().all())


async def _encerramento(session) -> tuple[str | None, str | None]:
    """(status, motivo) da conversa do par, ou (None, None) sem linha."""
    session.expire_all()
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.motivo_do_encerramento).where(
                Conversa.channel == CANAL, Conversa.conversation_key == CONVERSA
            )
        )
    ).one_or_none()
    return (None, None) if linha is None else (linha.status, linha.motivo_do_encerramento)


async def _eventos_de_optout(session) -> int:
    return (await session.execute(select(func.count()).select_from(OptoutEvent))).scalar_one()


async def test_pedido_de_eliminacao_so_pergunta_e_nao_registra_nada(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """O primeiro passo da eliminacao (C2 da revisao final, decisao do
    Eduardo): o pedido nao registra solicitacao, nao grava opt-out e nao
    encerra a conversa -- so pergunta. Continua sem chamar o classificador.

    A moderacao de entrada roda uma vez, no fecho de `executar_turno` (TEC-297).
    """
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake()

    resultado = await _rodar(
        session,
        "quero apagar meus dados",
        classificador=classificador,
        outbound=outbound,
        moderador=moderador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "confirmacao_de_titular_pedida"
    assert classificador.chamadas == 0
    assert moderador.direcoes == [Direcao.ENTRADA]
    assert await _solicitacoes(session) == []
    assert not await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)
    assert (await _encerramento(session))[0] != Status.ENCERRADA
    # `in` e nao `==`: primeira mensagem da conversa, entao a entrega carrega o
    # prefixo de identificacao da TEC-139.
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_PERGUNTA_DE_ELIMINACAO in outbound.entregues[0]


async def test_apagar_depois_da_pergunta_registra_optout_encerra_e_confirma(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """O segundo passo: "APAGAR" logo depois da pergunta faz o que o pedido
    fazia em um passo so -- solicitacao ABERTA de origem WHATSAPP, opt-out,
    conversa encerrada com motivo OPTOUT e a confirmacao --, sem o modelo."""
    classificador = classificador_fake()
    outbound = outbound_fake()
    kwargs = dict(
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    primeiro = await _rodar(session, "quero apagar meus dados", **kwargs)
    assert primeiro == "confirmacao_de_titular_pedida"
    resultado = await _rodar(session, "APAGAR", **kwargs)

    assert resultado == "pedido_de_titular"
    assert classificador.chamadas == 0
    [linha] = await _solicitacoes(session)
    assert linha.tipo == TipoDeSolicitacao.ELIMINACAO
    assert linha.origem == OrigemDaSolicitacao.WHATSAPP
    assert linha.status == StatusDaSolicitacao.ABERTA
    assert (linha.channel, linha.conversation_key) == (CANAL, CONVERSA)
    assert await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)
    # Escrituracao do opt-out que o pedido gravou (TEC-130, D6), igual ao
    # bloco de opt-out: a conversa fecha com data e motivo.
    assert await _encerramento(session) == (Status.ENCERRADA, MotivoDoEncerramento.OPTOUT)
    assert len(outbound.entregues) == 2
    assert TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO in outbound.entregues[1]


@pytest.mark.parametrize("confirmacao", ["Sim, apagar!", "confirmo apagar"])
async def test_sim_apagar_e_confirmo_apagar_tambem_confirmam(
    confirmacao,
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    classificador = classificador_fake()
    outbound = outbound_fake()
    kwargs = dict(
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    await _rodar(session, "apaga meus dados", **kwargs)

    assert await _rodar(session, confirmacao, **kwargs) == "pedido_de_titular"
    assert len(await _solicitacoes(session)) == 1


async def test_apagar_depois_de_24_horas_nao_confirma(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """A pergunta vale por 24 horas: depois disso "apagar" e so uma palavra, e
    o turno segue normal -- chama o modelo e nao registra nada."""
    classificador = classificador_fake()
    outbound = outbound_fake()
    kwargs = dict(
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    await _rodar(session, "quero apagar meus dados", **kwargs)
    # Envelhece a reserva da pergunta, que e o carimbo que o segundo passo le.
    await session.execute(
        update(OutboundDispatch)
        .where(OutboundDispatch.kind == KIND_DA_PERGUNTA_DE_ELIMINACAO)
        .values(created_at=func.now() - timedelta(hours=24, minutes=1))
    )
    await session.commit()

    resultado = await _rodar(session, "apagar", **kwargs)

    assert resultado == "respondido"
    assert classificador.chamadas == 1
    assert await _solicitacoes(session) == []
    assert not await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)


async def test_lead_que_continua_a_conversa_e_atendido_e_apagar_depois_nao_confirma(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Quem nao confirma e so continua a conversa recebe a resposta do modelo,
    e nada e registrado. Um "apagar" depois disso nao confirma: a ultima fala
    do agente ja nao e a pergunta.

    A primeira frase e a correcao de cadastro que motivou os dois passos: o
    detector a le como eliminacao, e antes ela gravava opt-out e encerrava a
    conversa na hora."""
    classificador = classificador_fake()
    outbound = outbound_fake()
    kwargs = dict(
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    pergunta = await _rodar(
        session, "pode excluir meus dados do cadastro antigo e manter o novo?", **kwargs
    )
    assert pergunta == "confirmacao_de_titular_pedida"

    seguiu = await _rodar(session, "tem apartamento de 2 quartos em Pinheiros?", **kwargs)
    assert seguiu == "respondido"
    assert classificador.chamadas == 1

    resultado = await _rodar(session, "apagar", **kwargs)

    assert resultado == "respondido"
    assert classificador.chamadas == 2
    assert await _solicitacoes(session) == []
    assert not await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)
    assert (await _encerramento(session))[0] != Status.ENCERRADA


async def test_apagar_sem_pergunta_pendente_segue_o_turno_normal(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    classificador = classificador_fake()

    resultado = await _rodar(
        session,
        "apagar",
        classificador=classificador,
        outbound=outbound_fake(),
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 1
    assert await _solicitacoes(session) == []


async def test_pedido_de_acesso_nao_registra_optout(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Acesso nao e pedido de silencio: o lead que quer ver os proprios dados
    continua sendo atendido normalmente depois."""
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        session,
        "quero meus dados",
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "pedido_de_titular"
    assert classificador.chamadas == 0
    [linha] = await _solicitacoes(session)
    assert linha.tipo == TipoDeSolicitacao.ACESSO
    assert linha.status == StatusDaSolicitacao.ABERTA
    assert not await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)
    assert (await _encerramento(session))[0] != Status.ENCERRADA
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_CONFIRMACAO_DE_ACESSO in outbound.entregues[0]


async def test_pedido_de_acesso_junto_com_optout_registra_os_dois(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """O bloco de titular devolve antes do bloco de opt-out; sem registrar o
    opt-out ali, "pare de mandar mensagem, quero meus dados" perderia o pedido
    de saida em silencio -- o defeito de LGPD que as guardas de opt-out deste
    turno ja pagaram uma vez."""
    outbound = outbound_fake()

    resultado = await _rodar(
        session,
        "pare de mandar mensagem e quero meus dados",
        classificador=classificador_fake(),
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "pedido_de_titular"
    [linha] = await _solicitacoes(session)
    assert linha.tipo == TipoDeSolicitacao.ACESSO
    assert await esta_em_optout(session, channel=CANAL, conversation_key=CONVERSA)
    assert await _encerramento(session) == (Status.ENCERRADA, MotivoDoEncerramento.OPTOUT)
    assert TEXTO_DA_CONFIRMACAO_DE_ACESSO in outbound.entregues[0]


async def test_lead_ja_em_optout_ainda_exerce_o_direito(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Antes do portao de silencio por opt-out: quem ja pediu para sair nao
    perde o direito de pedir que apaguem os dados -- a pergunta e a
    confirmacao atravessam a guarda de opt-out da porta de saida, e o
    "apagar" de quem ja optou ainda confirma."""
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=CONVERSA, message_id=uuid.uuid4()
    )
    classificador = classificador_fake()
    outbound = outbound_fake()
    kwargs = dict(
        classificador=classificador,
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    primeiro = await _rodar(session, "quero apagar meus dados", **kwargs)
    assert primeiro == "confirmacao_de_titular_pedida"
    resultado = await _rodar(session, "apagar", **kwargs)

    assert resultado == "pedido_de_titular"
    [linha] = await _solicitacoes(session)
    assert linha.tipo == TipoDeSolicitacao.ELIMINACAO
    # O opt-out ja valia: o bloco nao acrescenta um segundo evento a tabela
    # append-only.
    assert await _eventos_de_optout(session) == 1
    assert len(outbound.entregues) == 2
    assert TEXTO_DA_PERGUNTA_DE_ELIMINACAO in outbound.entregues[0]
    assert TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO in outbound.entregues[1]


async def test_conversa_em_atendimento_humano_ainda_confirma(
    session,
    semear_corretor,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """Antes da guarda de atendimento humano, e o kind fura a guarda da porta:
    um corretor ter assumido a conversa nao suspende direito do titular."""
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(session, channel=CANAL, conversation_key=CONVERSA, corretor_id=corretor.id)
    await session.commit()
    outbound = outbound_fake()

    resultado = await _rodar(
        session,
        "quero meus dados",
        classificador=classificador_fake(),
        outbound=outbound,
        moderador=moderador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "pedido_de_titular"
    assert len(await _solicitacoes(session)) == 1
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_CONFIRMACAO_DE_ACESSO in outbound.entregues[0]


async def test_registro_nao_depende_da_moderacao_aprovar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Mesmo CRITICAL que `test_turno_optout.py` prende para o opt-out: uma
    fala que e pedido de titular E reprovada pela moderacao tem o pedido
    registrado e confirmado, e a recusa de entrada nao sai. Vale para o
    primeiro passo da eliminacao tambem: a pergunta sai no lugar da recusa."""
    outbound = outbound_fake()

    resultado = await _rodar(
        session,
        "quero meus dados, seus golpistas",
        classificador=classificador_fake(),
        outbound=outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert resultado == "pedido_de_titular"
    assert len(await _solicitacoes(session)) == 1
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_CONFIRMACAO_DE_ACESSO in outbound.entregues[0]

    pergunta = await _rodar(
        session,
        "apaguem meus dados, seus golpistas",
        classificador=classificador_fake(),
        outbound=outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
    )

    assert pergunta == "confirmacao_de_titular_pedida"
    assert len(outbound.entregues) == 2
    assert TEXTO_DA_PERGUNTA_DE_ELIMINACAO in outbound.entregues[1]


async def test_pedir_duas_vezes_cria_uma_solicitacao_e_confirma_as_duas(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Idempotencia de `registrar_solicitacao` por lead e tipo: o segundo
    pedido nao abre outra linha, mas o lead que repete recebe a confirmacao de
    novo -- mensagem nova, reserva nova em `outbound_dispatches`."""
    outbound = outbound_fake()
    for _ in range(2):
        resultado = await _rodar(
            session,
            "quero meus dados",
            classificador=classificador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
        )
        assert resultado == "pedido_de_titular"

    assert len(await _solicitacoes(session)) == 1
    assert len(outbound.entregues) == 2
    assert all(TEXTO_DA_CONFIRMACAO_DE_ACESSO in texto for texto in outbound.entregues)
