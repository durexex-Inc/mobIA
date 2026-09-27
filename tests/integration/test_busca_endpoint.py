"""O endpoint da busca hibrida, e a guarda que o protege.

TEC-158, secao 6.3 do SRS. `BUSCAR_IMOVEIS` e a unica permissao que os quatro
papeis tem (TEC-202); os testes usam LEITURA, o menos privilegiado. Ate a
TEC-201 a autenticacao era o token compartilhado do administrativo -- ver D10.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from httpx import AsyncClient

from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar
from tests.conftest import cabecalho_de


async def _semear(session: Any, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": "AP-1042",
        "titulo": "Apartamento com vista",
        "descricao": "Sala ampla com varanda.",
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
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_a_busca_devolve_o_contrato_da_secao_6_3(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={
            "filtros": {
                "operacao": "VENDA",
                "precoMax": 60000000,
                "quartosMin": 2,
                "regioes": ["Zona Sul"],
            },
            "limite": 10,
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["totalCandidatos"] == 1
    assert corpo["consultaVetorizada"] is False
    assert corpo["candidatosSemVetor"] == 1
    item = corpo["itens"][0]
    assert item["id"] == str(identificador)
    assert item["codigo"] == "AP-1042"
    # `preco`, e nao `precoVenda`: o exemplo do SRS e de uma busca de venda, e
    # copia-lo ao pe da letra faria a busca de aluguel devolver o campo
    # errado. Ver o contrato do endpoint no desenho.
    assert item["preco"] == 58000000
    # 0,387 e nao 0,4: sem vetor a similaridade vale 0, entao o score e
    # `0,4 x aderencia`, e a aderencia de R$ 580.000 contra um teto de
    # R$ 600.000 e `1 - 2/60 = 0,9667`. Conferido no Postgres:
    # `round((0.4 * (1 - abs(58000000-60000000)::float8/60000000))::numeric, 3)`
    # da 0.387. O imovel no teto exato e que daria 0,4 -- ver
    # `test_a_aderencia_vale_um_no_teto_e_meio_na_metade`.
    assert item["scoreMatch"] == 0.387


async def test_regiao_em_caixa_alta_casa_igual(client: AsyncClient, session: Any) -> None:
    """O chamador HTTP nao precisa saber que a comparacao e dobrada. D4."""
    await _semear(session)

    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={"filtros": {"operacao": "VENDA", "regioes": ["VILA MARIANA"]}},
    )

    assert resposta.status_code == 200
    assert resposta.json()["totalCandidatos"] == 1


async def test_limite_acima_de_dez_e_recusado(client: AsyncClient) -> None:
    """RN-09.2 na borda: o cliente e informado, em vez de receber 10 calado."""
    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={"filtros": {"operacao": "VENDA"}, "limite": 50},
    )

    assert resposta.status_code == 422


async def test_filtro_sem_operacao_e_recusado(client: AsyncClient) -> None:
    """D2. Sem operacao nao ha coluna de preco a comparar."""
    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={"filtros": {"precoMax": 60000000}},
    )

    assert resposta.status_code == 422


async def test_sem_token_e_proibido(client: AsyncClient) -> None:
    resposta = await client.post(
        "/api/v1/imoveis/busca",
        json={"filtros": {"operacao": "VENDA"}},
    )

    assert resposta.status_code == 403


async def test_busca_de_ambos_e_recusada_com_422(client: AsyncClient) -> None:
    """`AMBOS` passa no enum e nao e busca valida.

    Sem a guarda na borda, o `ValueError` do dominio viraria 500 para uma
    requisicao sintaticamente correta.
    """
    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={"filtros": {"operacao": "AMBOS"}},
    )

    assert resposta.status_code == 422


async def test_o_contrato_da_secao_6_3_devolve_relaxamento_aplicado(
    client: AsyncClient, session: Any
) -> None:
    """Secao 6.3 do SRS: `relaxamentoAplicado` esta no exemplo de resposta.

    Busca que acha no filtro duro devolve `false` -- e o valor que o exemplo
    do SRS escreve.
    """
    await _semear(session)

    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={
            "filtros": {
                "operacao": "VENDA",
                "precoMax": 60000000,
                "quartosMin": 2,
                "regioes": ["Zona Sul"],
            },
            "limite": 10,
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["relaxamentoAplicado"] is False


async def test_zero_no_filtro_duro_relaxa_e_devolve_relaxamento_aplicado(
    client: AsyncClient, session: Any
) -> None:
    """RN-09.3 pela borda HTTP: zero no passe duro relaxa a faixa de preco.

    `precoMax` de R$ 600.000 nao acha o imovel de R$ 620.000 no filtro duro,
    mas acha nos 10% de folga do passe relaxado (RN-09.3): 620.000 <=
    600.000 * 1,10 = 660.000. Sem `regioes`, so o preco cede -- nao ha tabela
    de bairro adjacente para "Vila Mariana" tornar isto sobre bairro tambem.
    """
    identificador = await _semear(session, preco_venda=62000000)

    resposta = await client.post(
        "/api/v1/imoveis/busca",
        headers=cabecalho_de("LEITURA"),
        json={"filtros": {"operacao": "VENDA", "precoMax": 60000000}},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["relaxamentoAplicado"] is True
    assert corpo["itens"][0]["id"] == str(identificador)
