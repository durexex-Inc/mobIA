"""As leituras de usuario que a autenticacao precisa. TEC-201."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.usuarios.models import Usuario


async def por_email(session: AsyncSession, email: str) -> Usuario | None:
    """O usuario ATIVO com este e-mail, ou None.

    **O filtro de `ativo` mora aqui e nao no chamador**, para que nao exista
    caminho de autenticacao que esqueca de aplica-lo. Desativar um usuario tem
    de bastar para ele nao entrar mais.

    O e-mail e normalizado para minusculas: o `UNIQUE` da coluna e sensivel a
    caixa, e sem isto "Ana@x.com" e "ana@x.com" seriam dois usuarios. Quem
    cadastrar (outra card -- ver a lacuna L2) precisa gravar em minusculas pela
    mesma razao.
    """
    return (
        await session.execute(
            select(Usuario).where(Usuario.email == email.strip().lower(), Usuario.ativo.is_(True))
        )
    ).scalar_one_or_none()


async def por_id(session: AsyncSession, usuario_id: uuid.UUID) -> Usuario | None:
    """O usuario ATIVO com este id, ou None.

    Usado no refresh: entre o login e a renovacao, alguem pode ter sido
    desativado, e a renovacao e o ponto em que isso passa a valer. O JWT ja
    emitido continua valido ate expirar -- e a lacuna L5 do desenho.
    """
    return (
        await session.execute(
            select(Usuario).where(Usuario.id == usuario_id, Usuario.ativo.is_(True))
        )
    ).scalar_one_or_none()
