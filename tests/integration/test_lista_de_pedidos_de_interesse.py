"""TEC-404: GET /api/v1/interesses -- quem ve o que, mascarado, paginado.

Basename distinto de tudo em `tests/unit/`. Os helpers sao copiados de
`test_portal_interesse_endpoint.py`, e nao importados: um arquivo de teste nao
depende de outro.
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


async def test_admin_ve_o_pedido_mascarado(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session, codigo="AP-0404", titulo="Cobertura duplex")
    await _pedir(client, imovel, "11988887777", nome="Juarez", email="juarez@ex.com")

    resposta = await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["proximoCursor"] is None
    [item] = corpo["itens"]
    assert item["nome"] == "Juarez"
    # Literais conferidos contra `mascarar_telefone`/`mascarar_email` reais.
    assert item["telefoneMascarado"] == "+55 11 9****-**77"
    assert item["emailMascarado"] == "j****z@*x.com"
    assert item["imovel"] == {"id": str(imovel), "codigo": "AP-0404", "titulo": "Cobertura duplex"}
    uuid.UUID(item["leadId"])
    assert item["atendimento"]["status"] == "PENDENTE"
    assert item["atendimento"]["corretor"] is None
    assert item["atendimento"]["semCorretor"] is False
    assert item["atendimento"]["notificadoEm"] is None
    assert "11988887777" not in resposta.text
    assert "juarez@ex.com" not in resposta.text


async def test_pedido_sem_email_vem_com_email_nulo(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")

    [item] = (await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))).json()["itens"]

    assert item["emailMascarado"] is None
    assert item["nome"] is None


async def test_corretor_so_ve_os_dele(client: AsyncClient, session: Any, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")
    await _vincular(session, a.id)

    do_a = await client.get(
        "/api/v1/interesses", headers=cabecalho_de("CORRETOR", corretor_id=a.id)
    )
    do_b = await client.get(
        "/api/v1/interesses", headers=cabecalho_de("CORRETOR", corretor_id=b.id)
    )

    [item] = do_a.json()["itens"]
    assert item["atendimento"]["corretor"] == {"id": str(a.id), "nome": a.nome}
    assert do_b.json()["itens"] == []


async def test_corretor_sem_vinculo_recebe_lista_vazia(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")

    resposta = await client.get("/api/v1/interesses", headers=cabecalho_de("CORRETOR"))

    assert resposta.status_code == 200
    assert resposta.json() == {"itens": [], "proximoCursor": None}


async def test_segundo_imovel_do_mesmo_telefone_aponta_o_mesmo_atendimento(
    client: AsyncClient, session: Any
) -> None:
    primeiro = await _semear_imovel(session)
    segundo = await _semear_imovel(session)
    await _pedir(client, primeiro, "11988887777")
    await _pedir(client, segundo, "11988887777")

    itens = (await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))).json()["itens"]

    assert len(itens) == 2
    assert itens[0]["atendimento"]["id"] == itens[1]["atendimento"]["id"]
    assert itens[0]["leadId"] == itens[1]["leadId"]


async def test_pedido_antigo_continua_no_atendimento_antigo(
    client: AsyncClient, session: Any
) -> None:
    """D4: depois do CONCLUIDO, um pedido novo abre outro atendimento."""
    primeiro = await _semear_imovel(session)
    segundo = await _semear_imovel(session)
    await _pedir(client, primeiro, "11988887777")
    await session.execute(text("UPDATE handoffs SET status = 'CONCLUIDO'"))
    await session.commit()
    await _pedir(client, segundo, "11988887777")

    itens = (
        await client.get("/api/v1/interesses?estado=todos", headers=cabecalho_de("ADMIN"))
    ).json()["itens"]

    por_imovel = {i["imovel"]["id"]: i["atendimento"] for i in itens}
    assert por_imovel[str(primeiro)]["status"] == "CONCLUIDO"
    assert por_imovel[str(segundo)]["status"] == "PENDENTE"
    assert por_imovel[str(primeiro)]["id"] != por_imovel[str(segundo)]["id"]


async def test_filtro_pendentes_esconde_aceito(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")
    await session.execute(text("UPDATE handoffs SET status = 'ACEITO', aceito_em = now()"))
    await session.commit()

    pendentes = await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))
    todos = await client.get("/api/v1/interesses?estado=todos", headers=cabecalho_de("ADMIN"))

    assert pendentes.json()["itens"] == []
    assert len(todos.json()["itens"]) == 1


async def test_filtro_pendentes_inclui_escalado(client: AsyncClient, session: Any) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await session.execute(
        text("UPDATE handoffs SET status = 'ESCALADO', aviso_manual_pendente = true")
    )
    await session.commit()

    [item] = (await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))).json()["itens"]

    assert item["atendimento"]["status"] == "ESCALADO"
    assert item["atendimento"]["semCorretor"] is True


async def test_pedido_sem_atendimento_so_aparece_em_todos(
    client: AsyncClient, session: Any
) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await session.execute(text("DELETE FROM handoffs"))
    await session.commit()

    pendentes = await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))
    todos = await client.get("/api/v1/interesses?estado=todos", headers=cabecalho_de("ADMIN"))

    assert pendentes.json()["itens"] == []
    [item] = todos.json()["itens"]
    assert item["atendimento"] is None


async def test_paginacao_sem_repetir(client: AsyncClient, session: Any) -> None:
    for telefone in ("11988880001", "11988880002", "11988880003"):
        await _pedir(client, await _semear_imovel(session), telefone)

    primeira = (
        await client.get("/api/v1/interesses?limite=2", headers=cabecalho_de("ADMIN"))
    ).json()
    segunda = (
        await client.get(
            f"/api/v1/interesses?limite=2&cursor={primeira['proximoCursor']}",
            headers=cabecalho_de("ADMIN"),
        )
    ).json()

    ids = [i["id"] for i in primeira["itens"]] + [i["id"] for i in segunda["itens"]]
    assert len(ids) == 3 == len(set(ids))
    criados = [i["criadoEm"] for i in primeira["itens"] + segunda["itens"]]
    assert criados == sorted(criados, reverse=True)
    assert segunda["proximoCursor"] is None


async def test_paginacao_desempata_pelo_id(client: AsyncClient, session: Any) -> None:
    """Tres pedidos no MESMO instante: o keyset precisa do `id` para nao
    repetir nem pular, e a ordem dentro do empate e `id` decrescente."""
    for telefone in ("11988880001", "11988880002", "11988880003"):
        await _pedir(client, await _semear_imovel(session), telefone)
    await session.execute(
        text("UPDATE solicitacoes_de_interesse SET criado_em = '2026-10-09T12:00:00+00'")
    )
    await session.commit()

    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        url = "/api/v1/interesses?estado=todos&limite=1"
        if cursor:
            url += f"&cursor={cursor}"
        corpo = (await client.get(url, headers=cabecalho_de("ADMIN"))).json()
        vistos += [i["id"] for i in corpo["itens"]]
        cursor = corpo["proximoCursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(vistos) == 3 == len(set(vistos))
    assert vistos == sorted(vistos, key=uuid.UUID, reverse=True)


async def test_cursor_adulterado_e_422(client: AsyncClient) -> None:
    resposta = await client.get("/api/v1/interesses?cursor=lixo", headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 422
    assert resposta.json()["detail"] == "cursor invalido"


async def test_estado_desconhecido_e_422(client: AsyncClient) -> None:
    resposta = await client.get("/api/v1/interesses?estado=x", headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 422


async def test_limite_fora_da_faixa_e_422(client: AsyncClient) -> None:
    for limite in (0, 101):
        resposta = await client.get(
            f"/api/v1/interesses?limite={limite}", headers=cabecalho_de("ADMIN")
        )
        assert resposta.status_code == 422


async def test_sem_token_e_403(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/interesses")).status_code == 403
