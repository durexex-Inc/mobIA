from decimal import Decimal

from conftest import CANAL_AGENTE, CONVERSA_AGENTE

from mobia.domain.agente.schemas import Extracao, Intencao, TipoImovel, Urgencia
from mobia.domain.context.repositorio import ler_estado


async def test_quatro_campos_de_uma_frase_so(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Gherkin 1 do card."""
    classificador = classificador_fake(
        Intencao.COMPRA,
        extracao=Extracao(
            tipo_imovel=TipoImovel.APARTAMENTO,
            quartos=2,
            regiao="zona sul",
            faixa_preco_max=Decimal("600000"),
            urgencia=Urgencia.ATE_3_MESES,
        ),
    )

    resultado = await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"

    estado = await ler_estado(session, CANAL_AGENTE, CONVERSA_AGENTE)
    assert estado is not None
    assert (estado.tipo_imovel, estado.quartos, estado.regiao) == (
        "APARTAMENTO",
        2,
        "zona sul",
    )
    assert estado.faixa_preco_max == Decimal("600000.00")
    assert estado.urgencia == "ATE_3_MESES"


async def test_saida_bloqueada_ainda_grava_a_extracao(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O oposto deliberado da correcao da TEC-233, e a razao esta no spec: la o
    fato era sobre o que **nos** dissemos (a pergunta nunca foi feita); aqui e
    sobre o que **o lead** disse, e ele disse independentemente de a nossa
    resposta ter sido entregue. O comentario de `turno.py` ja fazia esse
    argumento para a intencao: "a classificacao e sobre a mensagem do lead, que
    existe, e nao sobre a resposta que pode nao sair"."""
    moderador = moderador_fake(bloqueia_saida=True)
    classificador = classificador_fake(Intencao.COMPRA, extracao=Extracao(quartos=3))

    resultado = await rodar_turno(
        session,
        classificador,
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    assert resultado == "respondido"

    estado = await ler_estado(session, CANAL_AGENTE, CONVERSA_AGENTE)
    assert estado is not None
    assert estado.quartos == 3
