"""O relaxamento da RN-09.3 contra o banco.

TEC-160. Os quatro cenarios do Gherkin da card, mais a divida que a TEC-158
deixou nomeada: o clamp em 0 da aderencia e o decaimento para 0,9, que so sao
alcancaveis quando o filtro deixa de ser duro.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.texto import dobrar

TETO = 40000000  # R$ 400.000,00 em centavos -- o numero do cenario 1 da card


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `test_busca_hibrida.py`.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 35000000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
        "zona": "CENTRO",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_o_filtro_relaxado_admite_dez_por_cento_acima_do_teto(session: Any) -> None:
    """D3. O `WHERE` cede; e o numero do cenario 1 da card (400 -> 440 mil)."""
    acima = await _imovel(session, "AP-201", preco_venda=44000000)

    duro = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO))
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [acima]


async def test_a_ancora_da_ordenacao_nao_se_move_com_o_where(session: Any) -> None:
    """D2, e a divida que o plano da TEC-158 deixou para esta card.

    A emenda E-01 da RN-09.6 promete que "10% acima do teto sai com 0,9". Isso
    so vale se `_aderencia` continuar ancorada no teto ORIGINAL. Se a ancora
    viajasse junto com o `WHERE`, este imovel sairia com 1,0 -- e a ordenacao
    passaria a favorecer o mais caro do conjunto AMPLIADO, que e a direcao em
    que um erro de calibragem vira upsell.

    Sem vetor de consulta a similaridade vale 0 para todos, entao o score e
    `0,4 * aderencia` -- e 0,4 * 0,9 = 0,36.
    """
    await _imovel(session, "AP-202", preco_venda=44000000)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert resultado.candidatos[0].score == 0.36


async def test_o_piso_tambem_cede_no_passe_relaxado(session: Any) -> None:
    """D3: "faixa de preco em ate 10%" e sobre o intervalo, nao so o teto."""
    abaixo = await _imovel(session, "AP-203", preco_venda=19000000)

    duro = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000)
    )
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [abaixo]


async def test_relaxado_sem_teto_nem_piso_nao_muda_nada(session: Any) -> None:
    """A folga se aplica ao que existe; `None` continua sendo "sem essa ponta"."""
    dentro = await _imovel(session, "AP-204")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, relaxado=True))

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]
