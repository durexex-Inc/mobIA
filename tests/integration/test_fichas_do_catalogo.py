"""A ponte entre o catalogo e a ficha. TEC-162.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from decimal import Decimal
from typing import Any

from mobia.domain.agente.ferramenta_de_busca import fichas_do_catalogo
from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento em Lagoa da Conceicao",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 51646430,
        "preco_aluguel": 350000,
        "condominio": 55000,
        "bairro": "Lagoa da Conceicao",
        "bairro_busca": "lagoa da conceicao",
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 54,
        "quartos": 4,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["churrasqueira", "mobiliado", "piscina"],
        "fotos": ["https://exemplo.com/ap-1004-1.jpg"],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_a_ficha_sai_completa_do_catalogo(session: Any) -> None:
    identificador = await _imovel(session, "AP-1004")

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.titulo == "Apartamento em Lagoa da Conceicao"
    assert ficha.bairro == "Lagoa da Conceicao"
    assert ficha.preco_centavos == 51646430
    assert ficha.quartos == 4
    assert ficha.vagas == 2
    assert ficha.area_util_m2 == 54
    assert ficha.condominio_centavos == 55000
    assert ficha.diferencial == "churrasqueira e mobiliado"
    assert ficha.foto == "https://exemplo.com/ap-1004-1.jpg"


async def test_o_preco_vem_do_candidato_e_nao_da_coluna(session: Any) -> None:
    """D7. A linha tem `preco_venda` E `preco_aluguel` e nao diz qual usar --
    a operacao buscada so existe dentro de `porta_de_busca`. O dict do
    candidato ja traz o preco da operacao certa.

    Se este teste falhar porque alguem passou a ler `preco_venda` da linha,
    toda busca de ALUGUEL passara a mostrar o preco de venda ao lead.
    """
    identificador = await _imovel(session, "AP-1004")

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 350000}
    )

    assert ficha.preco_centavos == 350000


async def test_sem_foto_a_ficha_sai_com_foto_none(session: Any) -> None:
    """D13: o imovel e apresentado de todo jeito, pelo caminho de texto."""
    identificador = await _imovel(session, "AP-1004", fotos=[])

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.foto is None


async def test_sem_caracteristica_o_diferencial_e_none(session: Any) -> None:
    identificador = await _imovel(session, "AP-1004", caracteristicas=[])

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.diferencial is None


async def test_a_ordem_pedida_atravessa_a_ponte(session: Any) -> None:
    primeiro = await _imovel(session, "AP-001")
    segundo = await _imovel(session, "AP-002")

    fichas = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[segundo, primeiro],
        precos={primeiro: 10000000, segundo: 20000000},
    )

    assert [f.preco_centavos for f in fichas] == [20000000, 10000000]


async def test_sem_a_flag_a_ficha_nao_traz_rentabilidade(session: Any) -> None:
    """A trilha padrao nao muda de comportamento por causa desta card."""
    identificador = await _imovel(session, "AP-2001", iptu_mensal=32000)

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.rentabilidade is None


async def test_o_yield_sai_do_preco_de_venda_e_nao_do_preco_apresentado(
    session: Any,
) -> None:
    """D2: NUNCA de `Ficha.preco_centavos`.

    O `precos` passado aqui e o ALUGUEL, que e o que um investidor buscando
    ALUGUEL produziria. Se o yield saisse dele, a conta seria 1200% ao ano.
    Saindo de `preco_venda`, e 6,0% -- e 5,8% se alguem trocar a fonte pelo
    `preco_centavos` do default do helper, entao o numero desta assercao
    distingue as tres possibilidades.
    """
    identificador = await _imovel(
        session,
        "AP-2002",
        preco_venda=50_000_000,
        preco_aluguel=250_000,
        iptu_mensal=32000,
    )

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[identificador],
        precos={identificador: 250_000},
        com_rentabilidade=True,
    )

    assert ficha.rentabilidade is not None
    assert ficha.rentabilidade.aluguel_centavos == 250_000
    assert ficha.rentabilidade.yield_pct == Decimal("6.0")
    assert ficha.rentabilidade.custos_centavos == 55000 + 32000


async def test_imovel_sem_aluguel_ganha_rentabilidade_sem_numero(session: Any) -> None:
    """O objeto EXISTE (e investidor) e o aluguel e None (o catalogo nao tem).

    Devolver `None` no lugar do objeto colapsaria os dois estados, e a ficha
    nao teria como imprimir `Aluguel estimado: nao informado`.
    """
    identificador = await _imovel(session, "AP-2003", preco_aluguel=None, iptu_mensal=32000)

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[identificador],
        precos={identificador: 51646430},
        com_rentabilidade=True,
    )

    assert ficha.rentabilidade is not None
    assert ficha.rentabilidade.aluguel_centavos is None
    assert ficha.rentabilidade.yield_pct is None
    assert ficha.rentabilidade.custos_centavos == 55000 + 32000
