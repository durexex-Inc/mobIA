"""TEC-404, D5: quem revela telefone e e-mail do pedido, e a trilha.

Basename distinto de tudo em `tests/unit/`. Os helpers sao copiados de
`test_lista_de_pedidos_de_interesse.py`, e nao importados: um arquivo de teste
nao depende de outro.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text, update

from mobia.domain.catalogo.models import Imovel
from mobia.domain.handoff.models import Handoff
from mobia.domain.texto import dobrar
from tests.conftest import cabecalho_de


async def _semear_imovel(session: Any, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": f"AP-{uuid.uuid4().hex[:8]}",
        "titulo": "Apartamento com varanda",
        "descricao": "Sala ampla, dois quartos, varanda com vista para o parque.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 58000000,
        "bairro": "Vila Mariana",
        "bairro_busca": dobrar("Vila Mariana"),
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
        "area_util_m2": 74,
        "quartos": 2,
        "suites": 1,
        "banheiros": 2,
        "vagas": 1,
        "caracteristicas": [],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def _pedir(client: AsyncClient, imovel_id: uuid.UUID, telefone: str, **extra: str) -> None:
    resposta = await client.post(
        f"/portal/imoveis/{imovel_id}/interesse", json={"telefone": telefone, **extra}
    )
    assert resposta.status_code == 201, resposta.text


async def _vincular(session: Any, corretor_id: uuid.UUID | None) -> None:
    """Simula a notificacao, que e quem grava o corretor no handoff."""
    await session.execute(update(Handoff).values(corretor_id=corretor_id))
    await session.commit()


async def _id_do_pedido(session: Any) -> uuid.UUID:
    return (await session.execute(text("SELECT id FROM solicitacoes_de_interesse"))).scalar_one()


async def _eventos(session: Any) -> list[Any]:
    return list(
        (await session.execute(text("SELECT acao, campo, entidade FROM eventos_auditoria")))
        .mappings()
        .all()
    )


async def test_admin_revela_telefone_e_a_trilha_registra(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777", email="j@ex.com")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"campo": "telefone", "valor": "+5511988887777"}
    [evento] = [e for e in await _eventos(session) if e["acao"] == "DADO_PESSOAL_ACESSADO"]
    assert evento["campo"] == "telefone"
    assert evento["entidade"] == "lead"


async def test_admin_revela_email(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777", email="j@ex.com")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "email"},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.json()["valor"] == "j@ex.com"


async def test_email_ausente_e_nulo_com_trilha(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "email"},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200
    assert resposta.json()["valor"] is None
    assert any(e["campo"] == "email" for e in await _eventos(session))


async def test_corretor_dono_revela(client: AsyncClient, session: Any, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await _vincular(session, a.id)
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("CORRETOR", corretor_id=a.id),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["valor"] == "+5511988887777"


async def test_corretor_alheio_e_403_e_negativa_na_trilha(
    client: AsyncClient, session: Any, semear_corretor
) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await _vincular(session, a.id)
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("CORRETOR", corretor_id=b.id),
    )

    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "forbidden"}
    acoes = [e["acao"] for e in await _eventos(session)]
    assert "ACESSO_NEGADO" in acoes
    assert "DADO_PESSOAL_ACESSADO" not in acoes


async def test_leitura_sem_ver_dados_completos_e_403(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("LEITURA"),
    )

    assert resposta.status_code == 403
    acoes = [e["acao"] for e in await _eventos(session)]
    assert "ACESSO_NEGADO" in acoes
    assert "DADO_PESSOAL_ACESSADO" not in acoes


async def test_campo_desconhecido_e_422(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "cpf"},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 422


async def test_pedido_inexistente_e_404(client: AsyncClient) -> None:
    resposta = await client.post(
        f"/api/v1/interesses/{uuid.uuid4()}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 404
