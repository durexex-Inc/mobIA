import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.turno import SUBAGENTE_MODERACAO
from mobia.domain.messages.models import MessageTelemetry
from mobia.domain.moderacao.port import TEXTO_DA_RECUSA_DE_ENTRADA, Direcao, ModeracaoIndisponivel
from mobia.domain.outbound.port import EnvioForaDaJanela


def _espionar_montagem(monkeypatch: object) -> list:
    """Substitui `montar_contexto` no modulo do turno por um espiao que delega.

    Delega no original em vez de substituir de verdade: quem usa o espiao no
    caminho liberado continua exercitando a montagem de contexto real, e nao
    so registrando que ela "deveria" ter rodado.

    Devolve uma lista de 1 item (mutavel por referencia) em vez de um bool
    solto porque o espiao fecha sobre ela de dentro de uma corrotina --
    `nonlocal` exigiria a variavel na mesma funcao, e aqui a variavel precisa
    sair para o corpo do teste.
    """
    from mobia.domain.agente import turno as modulo_do_turno

    chamadas: list = []
    original = modulo_do_turno.montar_contexto

    async def espiao(*args: object, **kwargs: object) -> object:
        chamadas.append(True)
        return await original(*args, **kwargs)

    monkeypatch.setattr(modulo_do_turno, "montar_contexto", espiao)
    return chamadas


async def test_entrada_bloqueada_entrega_recusa_e_nao_chama_o_modelo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    monkeypatch: object,
) -> None:
    """Bloquear antes de montar contexto economiza o turno inteiro.

    `montar_contexto` nao e barato: ele dispara `resumidor` a cada ~40
    mensagens e `contador` quando a estimativa chega perto do teto, e as duas
    sao chamadas pagas. Um refactor que mova a moderacao para depois passa a
    pagar resumo em mensagem bloqueada, em silencio.

    O espiao existe porque asserir por efeito colateral nao pega isso: com uma
    mensagem semeada, `montar_contexto` nao custa nada observavel, e o teste
    passava com o bloco movido para depois dele.
    """
    chamadas_de_montagem = _espionar_montagem(monkeypatch)
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(bloqueia_entrada=True)

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert chamadas_de_montagem == []
    assert classificador.chamadas == 0
    assert outbound.entregues[-1] == TEXTO_DA_RECUSA_DE_ENTRADA


async def test_entrada_liberada_segue_o_turno(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    monkeypatch: object,
) -> None:
    """O espiao aqui e o contraponto do teste acima.

    Sem ele, um mutante que parasse de montar contexto sempre (nao so no
    caminho bloqueado) so seria pego indiretamente -- via NameError em
    `contexto` na chamada ao classificador, que e um acidente de escopo, nao
    uma assercao sobre a regra. Este teste torna "o caminho liberado monta
    contexto de verdade" uma garantia explicita.
    """
    chamadas_de_montagem = _espionar_montagem(monkeypatch)
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert chamadas_de_montagem == [True]
    assert classificador.chamadas == 1
    assert moderador.entradas == 1


async def test_moderador_indisponivel_na_entrada_deixa_o_turno_seguir(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Falha aberta na entrada, e a assimetria e deliberada.

    A fala do lead ja esta cifrada no banco -- a ingestao a gravou antes de o
    worker existir. Negar atendimento a lead legitimo porque um servico caiu
    pune o inocente por um problema alheio a conversa dele.
    """
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(erro_na_entrada=ModeracaoIndisponivel("TimeoutError"))

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 1


async def test_a_entrada_e_moderada_na_direcao_certa(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Moderar a fala do lead com o criterio da saida bloquearia reclamacao
    legitima, que e o falso positivo mais caro deste sistema.
    """
    classificador = classificador_fake()
    moderador = moderador_fake()

    await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake(), moderador
    )

    assert Direcao.ENTRADA in moderador.direcoes


async def test_recusa_fora_da_janela_expira_e_nao_vira_recusa_permanente(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """A mesma excecao tem de significar a mesma coisa nos dois caminhos.

    No caminho principal `EnvioForaDaJanela` vira `outbound.fora_da_janela` em
    `warning` e desfecho `"expirado"`; aqui ela caia junto com `EnvioRecusado`,
    virava `error` e desfecho `"sem_resposta"`. Janela de 24h fechada nao e
    recusa permanente -- e o `Literal` de `ResultadoDoTurno` existe justamente
    para essa distincao nao se perder. Classificada errado, ela acorda o alerta
    de `error` por uma janela que so fechou, e "expirado" some das contagens
    exatamente nas mensagens bloqueadas.
    """
    outbound = outbound_fake(EnvioForaDaJanela("131047"))
    moderador = moderador_fake(bloqueia_entrada=True)

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session,
            classificador_fake(),
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert resultado == "expirado"
    assert "outbound.fora_da_janela" in caplog.text
    assert "moderacao.texto_fixo_nao_entregue" not in caplog.text


async def test_a_entrega_da_recusa_nao_finge_lacuna_de_preco(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """Entrada bloqueada nao chama modelo nenhum, e a telemetria tem de dizer isso.

    Com `model=""` o custo saia None e o recorder emitia
    `telemetry.unknown_model`, cujo proposito documentado e "None aparece como
    lacuna e alguem conserta". Toda entrada bloqueada abriria um chamado para
    uma lacuna que nao existe -- e o alarme falso que se repete e o que ensina
    a ignorar o alarme. `MODELO_SEM_CHAMADA` esta na tabela de precos a custo
    zero, que aqui e o custo exato: nao houve chamada.
    """
    moderador = moderador_fake(bloqueia_entrada=True)

    with caplog.at_level(logging.WARNING):
        await rodar_turno(
            session,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert "telemetry.unknown_model" not in caplog.text
    linha = (
        await session.execute(
            select(MessageTelemetry).where(MessageTelemetry.subagent == SUBAGENTE_MODERACAO)
        )
    ).scalar_one()
    assert linha.model == MODELO_SEM_CHAMADA
    assert linha.cost_usd == Decimal("0")
