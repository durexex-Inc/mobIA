"""Os cinco cenarios do Gherkin da TEC-201, contra banco de verdade.

Mais os dois que o desenho acrescentou: o reuso de refresh (D4) e a
convivencia com o token compartilhado (D2).
"""

import uuid
from datetime import UTC, datetime

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.usuarios import senha, totp
from mobia.domain.usuarios.models import SessaoDeRefresh, Usuario

SENHA = "senha-de-teste-correta"


async def _semear(
    session: AsyncSession,
    *,
    email: str,
    papel: str = "GERENTE",
    com_mfa: bool = False,
    ativo: bool = True,
) -> tuple[uuid.UUID, str | None]:
    """Cria um usuario. Devolve o id e a semente TOTP, quando houver.

    A semente volta em CLARO porque o teste precisa gerar o codigo do momento
    -- e o unico lugar do projeto onde ela sai da cifra.
    """
    usuario_id = uuid.uuid4()
    agora = datetime.now(UTC)
    semente = None
    cifrada = None
    if com_mfa:
        semente = totp.gerar_semente()
        cifrada = totp.cifrar_semente(semente, usuario_id)

    session.add(
        Usuario(
            id=usuario_id,
            nome="Pessoa de Teste",
            email=email,
            papel=papel,
            senha_hash=senha.gerar_hash(SENHA),
            totp_segredo=cifrada,
            mfa_habilitado=com_mfa,
            ativo=ativo,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.commit()
    return usuario_id, semente


async def test_login_com_senha_certa_devolve_os_dois_tokens(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _semear(session, email="gerente@x.com")

    resposta = await client.post(
        "/api/v1/auth/login", json={"email": "gerente@x.com", "senha": SENHA}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["access"]
    assert corpo["refresh"]


async def test_senha_errada_e_email_inexistente_respondem_igual(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Distinguir os dois seria oraculo de enumeracao de usuario.

    A asserta e de IGUALDADE entre as duas respostas, e nao sobre o texto de
    cada uma: e a indistinguibilidade que importa, e ela continua valendo se
    alguem trocar a mensagem.
    """
    await _semear(session, email="existe@x.com")

    errada = await client.post(
        "/api/v1/auth/login", json={"email": "existe@x.com", "senha": "outra"}
    )
    inexistente = await client.post(
        "/api/v1/auth/login", json={"email": "nao-existe@x.com", "senha": SENHA}
    )

    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()


async def test_usuario_desativado_nao_entra(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _semear(session, email="saiu@x.com", ativo=False)

    resposta = await client.post("/api/v1/auth/login", json={"email": "saiu@x.com", "senha": SENHA})

    assert resposta.status_code == 401


async def test_admin_sem_segundo_fator_nao_recebe_token(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Quarto cenario do Gherkin.

    O login devolve um DESAFIO, nao o par de tokens: a regra vale no login, e
    nao espalhada por rota (D5).
    """
    await _semear(session, email="admin@x.com", papel="ADMIN", com_mfa=True)

    resposta = await client.post(
        "/api/v1/auth/login", json={"email": "admin@x.com", "senha": SENHA}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["mfa_requerido"] is True
    assert corpo["desafio"]
    assert "access" not in corpo


async def test_admin_conclui_com_o_codigo_do_momento(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    _, semente = await _semear(session, email="admin2@x.com", papel="ADMIN", com_mfa=True)
    assert semente is not None

    login = await client.post("/api/v1/auth/login", json={"email": "admin2@x.com", "senha": SENHA})
    resposta = await client.post(
        "/api/v1/auth/mfa",
        json={"desafio": login.json()["desafio"], "codigo": pyotp.TOTP(semente).now()},
    )

    assert resposta.status_code == 200
    assert resposta.json()["access"]


async def test_admin_com_codigo_errado_nao_entra(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _semear(session, email="admin3@x.com", papel="ADMIN", com_mfa=True)

    login = await client.post("/api/v1/auth/login", json={"email": "admin3@x.com", "senha": SENHA})
    resposta = await client.post(
        "/api/v1/auth/mfa", json={"desafio": login.json()["desafio"], "codigo": "000000"}
    )

    assert resposta.status_code == 401


async def test_admin_sem_mfa_habilitado_e_barrado_com_motivo_proprio(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Nao e lacuna, e a RNF-11: ADMIN sem segundo fator nao entra.

    403 e nao 401, e com mensagem propria: e configuracao incompleta, nao
    credencial errada, e quem administra precisa distinguir as duas.
    """
    await _semear(session, email="admin4@x.com", papel="ADMIN", com_mfa=False)

    resposta = await client.post(
        "/api/v1/auth/login", json={"email": "admin4@x.com", "senha": SENHA}
    )

    assert resposta.status_code == 403
    assert "MFA" in resposta.json()["detail"]


async def test_refresh_renova_sem_novo_login(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Terceiro cenario do Gherkin."""
    await _semear(session, email="renova@x.com")
    login = await client.post("/api/v1/auth/login", json={"email": "renova@x.com", "senha": SENHA})
    refresh = login.json()["refresh"]

    resposta = await client.post("/api/v1/auth/refresh", json={"refresh": refresh})

    assert resposta.status_code == 200
    # O refresh e ROTATIVO: o novo tem de ser outro valor, ou a rotacao nao
    # aconteceu e a deteccao de reuso abaixo nunca dispararia.
    assert resposta.json()["refresh"] != refresh


async def test_refresh_reusado_derruba_a_familia_inteira(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D4, e o teste que mais importa depois do de expiracao.

    Um refresh ja consumido, apresentado de novo, significa que duas partes tem
    o mesmo valor. Nao ha como saber qual esta pedindo, e deixar passar seria
    escolher ficar com o ladrao dentro -- entao a corrente inteira cai,
    inclusive o token novo que o legitimo acabou de receber.
    """
    await _semear(session, email="roubado@x.com")
    login = await client.post("/api/v1/auth/login", json={"email": "roubado@x.com", "senha": SENHA})
    primeiro = login.json()["refresh"]

    segundo = (await client.post("/api/v1/auth/refresh", json={"refresh": primeiro})).json()[
        "refresh"
    ]

    # O ladrao usa o primeiro de novo.
    reuso = await client.post("/api/v1/auth/refresh", json={"refresh": primeiro})
    assert reuso.status_code == 401

    # E o legitimo, com o token NOVO e valido, tambem perde a sessao.
    depois = await client.post("/api/v1/auth/refresh", json={"refresh": segundo})
    assert depois.status_code == 401


async def test_logout_invalida_o_refresh(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Quinto cenario do Gherkin."""
    await _semear(session, email="sai@x.com")
    login = await client.post("/api/v1/auth/login", json={"email": "sai@x.com", "senha": SENHA})
    refresh = login.json()["refresh"]

    assert (await client.post("/api/v1/auth/logout", json={"refresh": refresh})).status_code == 200

    depois = await client.post("/api/v1/auth/refresh", json={"refresh": refresh})
    assert depois.status_code == 401


async def test_logout_de_token_desconhecido_responde_ok(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Logout nao conta a ninguem se um token era valido.

    E um cliente que perdeu a sessao tem de conseguir sair sem receber erro.
    """
    resposta = await client.post("/api/v1/auth/logout", json={"refresh": "nao-existe"})

    assert resposta.status_code == 200


async def test_refresh_expirado_e_recusado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Envelhece a linha no banco em vez de esperar sete dias."""
    await _semear(session, email="velho@x.com")
    login = await client.post("/api/v1/auth/login", json={"email": "velho@x.com", "senha": SENHA})

    await session.execute(
        update(SessaoDeRefresh).values(expira_em=datetime(2020, 1, 1, tzinfo=UTC))
    )
    await session.commit()

    resposta = await client.post("/api/v1/auth/refresh", json={"refresh": login.json()["refresh"]})

    assert resposta.status_code == 401


@pytest.mark.parametrize("rota", ["/api/v1/corretores", "/api/v1/metricas/funil"])
async def test_rota_administrativa_aceita_jwt_e_o_token_compartilhado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, rota: str
) -> None:
    """A convivencia da D2, que e o que garante que esta card nao quebrou o painel.

    Escrito quando o BFF do frontend ainda mandava `X-Admin-Token`. Desde a
    TEC-309 ele manda o JWT de quem esta logado, e o token so vale para quem
    chama a API direto; os dois caminhos funcionam ate a TEC-382 apagar o
    segundo -- e o terceiro, sem credencial nenhuma, precisa recusar.
    """
    await _semear(session, email="admin-rota@x.com", papel="ADMIN", com_mfa=True)
    from mobia.app.config import get_settings
    from mobia.domain.usuarios import tokens

    settings = get_settings()
    usuario = (
        await session.execute(Usuario.__table__.select().where(Usuario.email == "admin-rota@x.com"))
    ).one()
    jwt_de_admin = tokens.emitir(usuario.id, "ADMIN", mfa=True, corretor_id=None, settings=settings)

    com_jwt = await client.get(rota, headers={"Authorization": f"Bearer {jwt_de_admin}"})
    com_token = await client.get(rota, headers={"X-Admin-Token": settings.catalogo_admin_token})
    sem_nada = await client.get(rota)

    assert com_jwt.status_code != 403
    assert com_token.status_code != 403
    assert sem_nada.status_code == 403


async def test_jwt_de_papel_nao_admin_nao_abre_rota_administrativa(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O papel entra na guarda, e nao so a validade do token.

    Sem isto, qualquer usuario autenticado -- inclusive `LEITURA` -- abriria o
    cadastro de corretores. **A checagem por papel em TODA rota chegou na
    TEC-202**, e esta deixou de ser a unica: o cadastro de corretores hoje
    exige `GERIR_CORRETORES`, e a tabela dos quatro papeis esta em
    `tests/integration/test_autorizacao_por_papel.py`. Este teste fica porque e
    o que prende a propriedade ao caminho da TEC-201 -- token valido e papel
    insuficiente -- sem depender da matriz da outra card.
    """
    from mobia.app.config import get_settings
    from mobia.domain.usuarios import tokens

    token = tokens.emitir(
        uuid.uuid4(), "LEITURA", mfa=False, corretor_id=None, settings=get_settings()
    )

    resposta = await client.get("/api/v1/corretores", headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 403


async def test_rota_administrativa_existe_mesmo_sem_o_token_compartilhado(
    session: AsyncSession, client_sem_token_compartilhado: AsyncClient, banco_limpo: None
) -> None:
    """A condicional da TEC-156 caiu, e este teste e o que a impede de voltar.

    Ate esta card, sem `CATALOGO_ADMIN_TOKEN` os routers administrativos NAO
    entravam no app -- e a resposta era 404. Com autenticacao de verdade isso
    passou a ter efeito perverso: quem configurasse so o JWT nao teria rota
    nenhuma, e precisaria manter justamente o token que a card veio substituir.

    O que se afirma aqui e a diferenca entre 403 e 404: a rota EXISTE e recusa.
    """
    resposta = await client_sem_token_compartilhado.get("/api/v1/corretores")

    assert resposta.status_code == 403
