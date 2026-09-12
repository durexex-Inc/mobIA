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
