"""O enfileiramento da geracao nos pontos que criam handoff.

Sem numero de proposito: eram tres quando este arquivo nasceu, sao seis desde
a TEC-143 (quatro em `turno.py`, o de `process_message.py` e o do pedido de
humano), e um numero escrito aqui envelhece a cada card que acrescenta
chamador. O enfileiramento do pedido de humano e afirmado em
`test_pedido_de_humano.py`, junto do resto daquela guarda.
"""

import uuid

from mobia.domain.agente.schemas import Intencao


class _AgendadorEspiao:
    def __init__(self) -> None:
        self.pedidos: list[uuid.UUID] = []

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        self.pedidos.append(handoff_id)


class _AgendadorQueExplode:
    async def agendar(self, handoff_id: uuid.UUID) -> None:
        raise RuntimeError("redis caiu")


async def test_handoff_novo_agenda_a_geracao(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-06.3/RN-06.5: "quero agendar visita" leva o lead a QUENTE num turno so,

    e o handoff que NASCE dessa travessia pede o resumo.
    """
    espiao = _AgendadorEspiao()
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        agendador=espiao,
        texto="quero agendar visita",
    )
    assert len(espiao.pedidos) == 1


async def test_gatilho_adicional_nao_reagenda(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O gatilho da intencao dispara em TODO turno -- ver a D3 do desenho.

    Reagendar aqui seria uma chamada de LLM por turno para um resumo que
    ninguem pediu. `Intencao.VENDER_IMOVEL` vai direto para handoff em todo
    turno (RN-03.4), sem condicao de borda -- o mesmo classificador e
    outbound reusados nos dois turnos, para isolar a variavel em teste: so o
    numero de agendamentos.
    """
    espiao = _AgendadorEspiao()
    classificador = classificador_fake(Intencao.VENDER_IMOVEL)
    outbound = outbound_fake()
    await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), agendador=espiao
    )
    await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), agendador=espiao
    )
    assert len(espiao.pedidos) == 1


async def test_falha_ao_agendar_nao_derruba_o_turno(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O handoff ja esta commitado quando o enfileiramento acontece.

    Perde-se o resumo, que a rota de regeneracao recupera -- nao o handoff, e
    nao a resposta ao lead.
    """
    resultado = await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        agendador=_AgendadorQueExplode(),
        texto="quero agendar visita",
    )
    assert resultado == "respondido"
