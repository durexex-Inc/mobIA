"""O script de criar usuario, contra banco de verdade. TEC-309, D8.

O teste que importa e o primeiro: o ADMIN que o script cria consegue ENTRAR,
passando pelas rotas reais da TEC-201 com um codigo gerado da URI que o script
imprime. Um script que grava uma linha sem que ela sirva para logar seria
exatamente o problema que ele existe para resolver.
"""

import uuid
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.admin.usuarios import RecusaDeCadastro, criar_usuario
from mobia.domain.usuarios.models import Usuario

SENHA = "senha-bem-comprida"


def _semente_da_uri(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


async def test_o_admin_criado_entra_com_senha_e_codigo_do_totp(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    criado = await criar_usuario(
        session, email="Ana@X.com", nome="Ana", papel="admin", senha_em_claro=SENHA
    )
    await session.commit()

    assert criado.uri_do_totp is not None
    assert criado.uri_do_totp.startswith("otpauth://totp/mobIA:ana%40x.com")

    # O e-mail foi gravado em minusculas: e assim que o login o procura.
    login = await client.post("/api/v1/auth/login", json={"email": "ana@x.com", "senha": SENHA})
    assert login.status_code == 200
    desafio = login.json()["desafio"]

    codigo = pyotp.TOTP(_semente_da_uri(criado.uri_do_totp)).now()
    mfa = await client.post("/api/v1/auth/mfa", json={"desafio": desafio, "codigo": codigo})

    assert mfa.status_code == 200
    assert mfa.json()["access"]


async def test_gerente_nasce_sem_mfa_e_entra_so_com_a_senha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    criado = await criar_usuario(
        session, email="gerente@x.com", nome="Anelise", papel="GERENTE", senha_em_claro=SENHA
    )
    await session.commit()

    assert criado.uri_do_totp is None
    login = await client.post(
        "/api/v1/auth/login", json={"email": "gerente@x.com", "senha": SENHA}
    )
    assert login.status_code == 200
    assert login.json()["access"]


async def test_mfa_pedido_num_papel_que_nao_o_exige(
    session: AsyncSession, banco_limpo: None
) -> None:
    criado = await criar_usuario(
        session,
        email="leitura@x.com",
        nome="Leitura",
        papel="LEITURA",
        senha_em_claro=SENHA,
        com_mfa=True,
    )
    await session.commit()

    usuario = await session.get(Usuario, criado.usuario_id)
    assert usuario is not None
    assert usuario.mfa_habilitado
    assert usuario.totp_segredo is not None
    assert criado.uri_do_totp is not None


async def test_corretor_leva_o_vinculo(
    session: AsyncSession, semear_corretor, banco_limpo: None
) -> None:
    corretor = await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")

    criado = await criar_usuario(
        session,
        email="paulo@x.com",
        nome="Paulo",
        papel="CORRETOR",
        senha_em_claro=SENHA,
        corretor_id=corretor.id,
    )
    await session.commit()

    usuario = await session.get(Usuario, criado.usuario_id)
    assert usuario is not None
    assert usuario.corretor_id == corretor.id


async def test_email_repetido_e_recusado_mesmo_com_outra_caixa(
    session: AsyncSession, banco_limpo: None
) -> None:
    await criar_usuario(
        session, email="ana@x.com", nome="Ana", papel="GERENTE", senha_em_claro=SENHA
    )
    await session.commit()

    with pytest.raises(RecusaDeCadastro, match="ja existe"):
        await criar_usuario(
            session, email="ANA@x.com", nome="Outra", papel="GERENTE", senha_em_claro=SENHA
        )

    total = len((await session.scalars(select(Usuario))).all())
    assert total == 1


@pytest.mark.parametrize(
    ("papel", "corretor_id", "senha", "motivo"),
    [
        ("DONO", None, SENHA, "papel desconhecido"),
        ("CORRETOR", None, SENHA, "precisa de --corretor-id"),
        ("GERENTE", uuid.UUID("0c7d2b1e-7f4a-4a3e-9c1d-3b8f2e6a5d10"), SENHA, "so um usuario"),
        ("GERENTE", None, "curta", "pelo menos"),
    ],
    ids=["papel-desconhecido", "corretor-sem-vinculo", "vinculo-fora-de-corretor", "senha-curta"],
)
async def test_recusas_nao_gravam_nada(
    session: AsyncSession,
    banco_limpo: None,
    papel: str,
    corretor_id: uuid.UUID | None,
    senha: str,
    motivo: str,
) -> None:
    with pytest.raises(RecusaDeCadastro, match=motivo):
        await criar_usuario(
            session,
            email="x@x.com",
            nome="X",
            papel=papel,
            senha_em_claro=senha,
            corretor_id=corretor_id,
        )

    assert (await session.scalars(select(Usuario))).all() == []
