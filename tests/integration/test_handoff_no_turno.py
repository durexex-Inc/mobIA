"""A fiacao do handoff dentro do turno."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.schemas import Intencao


async def _handoffs(session: AsyncSession) -> list[dict]:
    resultado = await session.execute(
        text("SELECT gatilho, etiqueta, prioridade FROM handoffs ORDER BY criado_em")
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_lead_que_esquenta_ganha_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-06.5 ganha destino: o comentario de `turno.py` dizia que nao havia.

    "quero agendar visita" e o gatilho da RN-06.3 que forca QUENTE num turno so.
    E o mesmo texto que `test_temperatura_no_turno.py` usa -- reusado de
    proposito: se o gatilho mudar, os dois arquivos falham juntos e ninguem
    descobre pela metade.
    """
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "LEAD_QUENTE"
    assert linhas[0]["etiqueta"] == "lead-quente"


async def test_lead_que_nao_esquenta_nao_ganha_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )
    assert await _handoffs(session) == []


async def test_vender_imovel_cria_handoff_e_o_lead_ainda_recebe_resposta(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-03.4 ganha destino.

    O lead CONTINUA recebendo resposta neste turno -- desde a TEC-137 o texto
    fixo de `_TEXTO_DO_ENCAMINHAMENTO`, nao mais a prosa do modelo -- e isso
    nao e a mesma coisa que ser silenciado: silenciar e a RN-16.4, que e a
    TEC-179, e nenhuma das duas cards faz isso. A segunda asserta e a
    nao-regressao dessa decisao, nao enfeite.

    De proposito ela afirma so que ALGO saiu, e nao O QUE saiu: qual texto e
    assunto de `test_encaminhamento_por_intencao.py`, e duplicar o literal aqui
    daria duas coisas para manter em sincronia. Foi essa divisao que deixou
    este docstring mentir por tres commits -- a branch nao toca este arquivo,
    entao `comentarios_tocados.py` nao tinha como aponta-lo nem como ALTERADO
    nem como VIZINHO.
    """
    entregador = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )
    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "VENDA_IMOVEL"
    assert entregador.entregues, "o lead deixou de receber resposta"


async def test_suporte_contrato_tem_etiqueta_propria(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Fila diferente da de quem quer vender."""
    await rodar_turno(
        session,
        classificador_fake(Intencao.SUPORTE_CONTRATO),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )
    linhas = await _handoffs(session)
    assert linhas[0]["etiqueta"] == "suporte-contrato"
