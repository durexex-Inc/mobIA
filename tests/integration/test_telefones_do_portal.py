"""TEC-404, D8: o lead do portal guarda o telefone em IdentidadeDeLead, como o WhatsApp."""

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.identidade.indice import registrar, telefones_de
from mobia.domain.messages.canais import CANAL_PORTAL


async def test_telefone_do_lead_do_portal(session: AsyncSession) -> None:
    chave = await registrar(session, CANAL_PORTAL, "5511988887777")
    await session.commit()

    telefones = await telefones_de(session, [(CANAL_PORTAL, chave)])

    assert telefones[(CANAL_PORTAL, chave)] == "5511988887777"
