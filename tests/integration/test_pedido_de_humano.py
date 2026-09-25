"""A transferencia para humano ao pedido do lead, ponta a ponta.

TEC-143.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.agente import turno as turno_mod
from mobia.domain.auditoria.vocabulario import ATOR_AGENTE
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff, tem_handoff_de_humano_aberto
from mobia.domain.handoff.vocabulario import Gatilho, Prioridade
from mobia.domain.humano.deteccao import (
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
)
from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.moderacao.port import Direcao
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
from mobia.infra.db import get_sessionmaker


@pytest.fixture(autouse=True)
def janela_aberta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Congela a janela de atendimento em ABERTA para todo teste deste arquivo.

    TEC-288. Sem isto o arquivo passava ou reprovava conforme a HORA em que a
    suite rodasse: `dentro_da_janela_de_atendimento` le o relogio real, e fora
    do expediente o lead recebe `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` em
    lugar da variante que dois testes aqui afirmam. A `main` ficava vermelha em
    toda execucao noturna.

    **O custo disso nao era o teste, era o sinal.** A regra de diagnostico do
    CLAUDE.md -- rode de novo antes de culpar sua mudanca -- NAO separa este
    caso: a falha e deterministica dentro da janela de tempo errada e reproduz
    identica nas duas execucoes, entao quem seguisse a regra a risca concluia
    que a propria mudanca tinha quebrado algo.

    Aberta, e nao fechada, porque e o estado que a maioria dos testes daqui
    pressupoe: o texto de dentro do horario e o caminho principal do pedido de
    humano. `test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito`
    desfaz isto localmente -- o `setattr` dele roda depois desta fixture e
    vence -- e continua sendo o unico que precisa.

    O alvo e `turno_mod.dentro_da_janela_de_atendimento`, o nome COMO IMPORTADO
    em `turno.py`, e nao a definicao em `deteccao.py`: e no modulo do turno que
    o nome e resolvido. Mesma forma da fixture que a TEC-137 escreveu em
    `test_encaminhamento_por_intencao.py`, que e o molde.
    """
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: True)


class _AgendadorEspiao:
    """Mesmo duble de `test_handoff_agenda_resumo.py`, e de proposito.

    A esteira que se afirma aqui e a mesma daquele arquivo -- `_agendar_resumo`
    e o primeiro elo de `gerar_resumo` -> `NOTIFICAR_JOB` -> `sla_limite_em` ->
    `escalar_vencidos` --, entao o duble tambem e o mesmo.
    """

    def __init__(self) -> None:
        self.pedidos: list[uuid.UUID] = []

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        self.pedidos.append(handoff_id)


async def test_sem_handoff_a_conversa_nao_esta_esperando_humano(session: AsyncSession) -> None:
    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110001"
        )
        is False
    )


async def test_handoff_de_pedido_de_humano_deixa_a_conversa_esperando(
    session: AsyncSession,
) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110002",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110002"
        )
        is True
    )


async def test_handoff_de_outro_gatilho_nao_cala_o_agente(session: AsyncSession) -> None:
    """Um lead que esquentou tem handoff aberto e continua sendo atendido.

    Calar por qualquer handoff aberto tiraria o agente de toda conversa que
    virou QUENTE -- que e o oposto do que o gatilho QUENTE significa. So o
    pedido explicito do lead cala.
    """
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110003",
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110003"
        )
        is False
    )


async def test_pedido_que_chega_depois_do_quente_tambem_cala(session: AsyncSession) -> None:
    """O gatilho pode estar em `gatilhos_adicionais`, e nao na coluna `gatilho`.

    Um lead que esquentou ja tem handoff aberto; quando ele pede uma pessoa,
    `registrar_handoff` ACUMULA o gatilho na linha existente em vez de criar
    outra. Olhar so a coluna `gatilho` perderia exatamente este caso, que e o
    mais comum: quem ja conversou o bastante para esquentar e quem mais se
    cansa de robo.
    """
    for gatilho in (Gatilho.LEAD_QUENTE, Gatilho.PEDIDO_DE_HUMANO):
        await registrar_handoff(
            session,
            channel="whatsapp",
            conversation_key="5511911110005",
            gatilho=gatilho,
            ator=ATOR_AGENTE,
        )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110005"
        )
        is True
    )


async def test_a_consulta_e_por_conversa_e_por_canal(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110004",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(session, channel="web", conversation_key="5511911110004")
        is False
    )


async def _handoff_da_conversa(session: AsyncSession, *, channel: str, conversation_key: str):
    return (
        await session.execute(
            select(Handoff).where(
                Handoff.channel == channel, Handoff.conversation_key == conversation_key
            )
        )
    ).scalar_one_or_none()


async def test_pedido_de_humano_cria_handoff_alta_e_nao_chama_o_modelo(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    handoff = await _handoff_da_conversa(
        session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE
    )
    assert handoff is not None
    assert handoff.gatilho == Gatilho.PEDIDO_DE_HUMANO.value
    assert handoff.prioridade == Prioridade.ALTA.value

    assert classificador.chamadas == 0
    assert resultado == "pedido_de_humano"
    assert outbound.entregues != [], "o aviso tem de sair"
    # Fecha a simetria com o teste de fora do horario: aquele confere o texto
    # da outra metade do if/else. Sem esta assercao uma inversao das duas
    # branches passaria despercebida -- "algo foi entregue" e verdade nos dois
    # casos.
    assert TEXTO_DO_PEDIDO_DE_HUMANO in outbound.entregues[-1]
    assert (
        TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
            inicio=get_settings().atendimento_horario_inicio,
            fim=get_settings().atendimento_horario_fim,
        )
        not in outbound.entregues[-1]
    )


async def test_optout_na_mesma_mensagem_vence_o_pedido_de_humano(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Fix de revisao (Critical) em `turno.py`. A guarda de atendimento humano

    -- e, pelo mesmo criterio, o bloco novo do pedido de humano -- so pode
    rodar `if not pedido_de_optout:`. Sem essa ordem, uma mensagem que e AO
    MESMO TEMPO opt-out e pedido de humano registraria o handoff e nunca
    gravaria a saida -- o mesmo defeito de LGPD que o comentario de
    `turno.py:749-758` (guarda de atendimento humano incondicional) descreve
    para o corretor que ja tinha assumido.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="pare de me mandar mensagens, quero falar com uma pessoa",
    )

    assert await esta_em_optout(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE), (
        "o opt-out tem de vencer e ficar gravado"
    )
    assert resultado == "opt_out"
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is None
    ), "o opt-out venceu -- nenhum handoff de pedido de humano nasce desta mensagem"


async def test_depois_do_pedido_o_agente_cala_e_a_mensagem_e_registrada(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    primeiro_resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )
    assert primeiro_resultado == "pedido_de_humano"

    classificador = classificador_fake()
    outbound = outbound_fake()

    segundo_resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="ainda estou esperando",
    )

    assert segundo_resultado == "atendimento_humano"
    assert outbound.entregues == [], "o agente cala -- nenhum envio novo"
    assert classificador.chamadas == 0

    total_do_lead = (
        await session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.role == MessageRole.LEAD, Message.direction == MessageDirection.INBOUND)
        )
    ).scalar_one()
    assert total_do_lead == 2, (
        "as duas falas do lead continuam registradas -- o silencio nao apaga nada"
    )


async def test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    monkeypatch: object,
) -> None:
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: False)

    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    assert resultado == "pedido_de_humano"
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is not None
    )

    settings = get_settings()
    texto_esperado = TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert outbound.entregues != []
    assert texto_esperado in outbound.entregues[-1]
    assert str(settings.atendimento_horario_inicio) in outbound.entregues[-1]
    assert str(settings.atendimento_horario_fim) in outbound.entregues[-1]


async def test_pedido_de_humano_agenda_o_resumo(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Critical 1 da revisao final. O handoff do pedido entrava na fila e saia da esteira.

    Os outros cinco sitios de `registrar_handoff` chamam `_agendar_resumo`
    depois do commit; este bloco nascia sem a chamada, e a cadeia inteira caia
    atras dela: sem `_agendar_resumo` nao ha `gerar_resumo`, sem ele nao ha
    `enqueue_job(NOTIFICAR_JOB)`, sem ele nao ha `sla_limite_em`, e
    `escalar_vencidos` nunca via o handoff. Quem o pegava era a rede de
    recuperacao da TEC-279, 10 a 15 minutos depois e em warning -- a rede de
    seguranca como caminho normal do UNICO gatilho `ALTA` da RN-16.1.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    espiao = _AgendadorEspiao()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        agendador=espiao,
        texto="quero falar com uma pessoa",
    )

    assert resultado == "pedido_de_humano"
    handoff = await _handoff_da_conversa(
        session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE
    )
    assert handoff is not None
    assert espiao.pedidos == [handoff.id], (
        "sem o agendamento o handoff ALTA nunca ganha prazo nem notificacao"
    )


async def test_repetir_o_pedido_nao_reagenda_o_resumo(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """A acumulacao de gatilho continua correta sem condicao extra no chamador.

    `_agendar_resumo` ja sai cedo quando `not registro.criado`. E o que permite
    o `not pedido_de_humano` da guarda de silencio (Critical 2) sem pagar uma
    geracao de resumo por mensagem repetida.
    """
    espiao = _AgendadorEspiao()
    for _ in range(2):
        await rodar_turno(
            session,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            agendador=espiao,
            texto="quero falar com uma pessoa",
        )

    assert len(espiao.pedidos) == 1


async def test_falha_retentavel_no_aviso_e_reentregue_no_turno_seguinte(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Critical 2 da revisao final. O aviso se perdia PARA SEMPRE numa falha retentavel.

    `_entregar_texto_fixo` nao captura `EnvioRetentavel`: a excecao sobe,
    `process_message` marca a linha FAILED e o sweeper reenfileira a MESMA
    mensagem. No turno 2 `pedido_de_optout` e False, a guarda de silencio
    rodava, `tem_handoff_de_humano_aberto` ja devolvia True (o turno 1 commitou
    o handoff antes de entregar), o turno fechava em "atendimento_humano" --
    PROCESSED -- e o lead nunca era avisado de nada.

    O mesmo defeito, pela fonte de silencio do opt-out, ja esta descrito no
    comentario daquela guarda em `turno.py`. Esta card o reintroduziu uma
    guarda abaixo, pela fonte de silencio nova.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE, ModeradorFake, _entrada_do_lead

    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    linha = await _entrada_do_lead(session, texto="quero falar com uma pessoa")

    async def _turno(outbound) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
            agendador=AgendadorNoop(),
            agendador_de_confirmacao=AgendadorDeConfirmacaoNoop(),
        )

    with pytest.raises(EnvioRetentavel):
        await _turno(outbound_fake(erro=EnvioRetentavel("http 503")))

    # O handoff ja esta gravado: o commit vem antes da entrega, de proposito.
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is not None
    )

    # Turno 2 sobre a MESMA Message, como o sweeper faz. Uma Message nova nao
    # provaria nada: a reserva de saida e por (message_id, kind), e a guarda de
    # silencio que este teste exercita so passa a valer com o handoff do turno
    # 1 ja no banco.
    segundo = outbound_fake()
    assert await _turno(segundo) == "pedido_de_humano"
    assert segundo.entregues != [], "o aviso tem de ser reentregue, nao perdido"
    assert TEXTO_DO_PEDIDO_DE_HUMANO in segundo.entregues[-1]


async def test_o_handoff_esta_gravado_quando_a_entrega_falha(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Important 6 da revisao final, ordem 3: commit do handoff antes da entrega.

    O comentario em `turno.py` afirma que o commit vem primeiro para o lead nao
    receber o aviso sem a linha existir; nenhum teste exercitava o outro lado
    dessa ordem -- entrega falhando com o handoff ja gravado. `EnvioRecusado` e
    a falha PERMANENTE: o turno devolve "sem_resposta" sem levantar, o lead
    fica transferido e em silencio, e essa e uma das saidas terminais que o
    comentario do fim do bloco declara como aceitas.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(erro=EnvioRecusado("http 400")),
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    assert resultado == "sem_resposta"
    handoff = await _handoff_da_conversa(
        session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE
    )
    assert handoff is not None, "a transferencia acontece mesmo quando o aviso nao sai"
    assert handoff.prioridade == Prioridade.ALTA.value


async def test_pedido_de_humano_passa_antes_da_moderacao_de_entrada(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """Important 6 da revisao final, ordem 1: a guarda corre ANTES da moderacao.

    A D4 do desenho fixou a ordem por razao de LGPD, e ela nao muda aqui -- o
    que faltava era um teste que a fixasse. O handoff nasce e o aviso sai sem
    esperar chamada paga nenhuma, e e isso que o nome deste teste afirma.

    O outro lado da mesma moeda e o motivo de a ordem ser essa: o lead irritado
    que xinga e pede uma pessoa na mesma frase e justamente quem a card existe
    para tirar do robo.

    **A TEC-297 mudou o depois, nao a ordem.** Ate ela, a consequencia declarada
    aqui e no comentario do bloco em `turno.py` era que essa fala saia do turno
    sem NUNCA ter sido moderada -- e ela entrava no contexto, no resumo, no lead
    score e na ancora de follow-up como fala legitima. Agora o fecho de
    `executar_turno` a modera depois do handoff e depois do aviso: uma chamada
    de ENTRADA, nenhuma de SAIDA. A ordem que este teste trava continua intacta;
    o que deixou de existir e o buraco no fim dela.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    moderador = moderador_fake(bloqueia_entrada=True)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto="quero falar com uma pessoa, seus incompetentes",
    )

    assert resultado == "pedido_de_humano"
    # TEC-297: exatamente uma de ENTRADA e nenhuma de SAIDA. A lista, e nao o
    # contador, porque ela reprova tambem o "moderou na direcao errada".
    assert moderador.direcoes == [Direcao.ENTRADA]
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is not None
    )
    assert outbound.entregues != []


async def test_optout_ja_registrado_vence_o_pedido_de_humano(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Important 6 da revisao final, ordem 2: quem ja pediu silencio nao vira handoff.

    `esta_em_optout` corre antes -- a guarda barata do topo do turno --, entao
    um lead ja em opt-out que peca humano recebe "silenciado" e nenhum handoff
    nasce. E o comportamento certo (nada pode ser enviado a quem pediu para
    sair, nem o aviso de transferencia) e ninguem o fixava. Repare que o
    `not pedido_de_humano` do Critical 2 NAO alcanca esta guarda: ele
    condiciona so a fonte de handoff da guarda de atendimento humano, a de
    baixo.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE, _entrada_do_lead

    anterior = await _entrada_do_lead(session, texto="pare de me mandar mensagens")
    await registrar_optout(
        get_sessionmaker(),
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        message_id=anterior.id,
    )

    outbound = outbound_fake()
    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    assert resultado == "silenciado"
    assert outbound.entregues == []
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is None
    )


async def test_conversa_ja_assumida_nao_gera_handoff_nem_notificacao(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    semear_corretor,
) -> None:
    """O caso que a forma ESTREITA do Critical 2 protege, e a ampla estragava.

    A primeira versao do fix condicionava a guarda inteira
    (`if not pedido_de_optout and not pedido_de_humano:`), o que pulava
    `esta_silenciada` junto. So a fonte de handoff causava o Critical 2;
    `esta_silenciada` responde outra pergunta -- um corretor ASSUMIU esta
    conversa (TEC-179, RN-16.4).

    Pulando-a, um lead ja atendido por gente de verdade que pedisse humano
    caia no bloco de baixo e, sem handoff aberto na conversa -- o corretor que
    assume por conta propria --, nascia handoff NOVO com `criado=True`. Desde o
    fix da esteira (Critical 1) isso agenda resumo e notificacao para uma
    conversa que ja tem dono: ruido operacional que chega a um corretor.

    Aqui a conversa e assumida SEM handoff nenhum, de proposito -- e a unica
    montagem em que a versao ampla criava linha nova em vez de so acumular
    gatilho.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    from mobia.domain.atendimento.repositorio import assumir

    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()

    espiao = _AgendadorEspiao()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        agendador=espiao,
        texto="quero falar com uma pessoa",
    )

    assert resultado == "atendimento_humano"
    assert outbound.entregues == [], "quem ja tem corretor nao recebe aviso de transferencia"
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is None
    ), "conversa assumida nao gera handoff novo"
    assert espiao.pedidos == [], "e por isso nada e notificado"
