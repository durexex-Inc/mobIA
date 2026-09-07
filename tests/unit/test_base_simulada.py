"""A base simulada que acompanha a POC atravessa o parser sem rejeicao.

TEC-156, RN-08.1 e o quarto cenario Gherkin. Puro: le o arquivo do repo e
passa pelo parser, sem banco. O ponto e que o seed exercita EXATAMENTE o mesmo
caminho da importacao real -- se o formato do arquivo divergir do parser, este
teste quebra antes de qualquer um notar em producao. Ver D8 do desenho.
"""

from collections import Counter
from pathlib import Path

from mobia.domain.catalogo.parser import parsear
from mobia.domain.catalogo.schemas import RegistroImovel, Rejeicao

ARQUIVO = Path(__file__).resolve().parents[2] / "data" / "seed" / "imoveis.csv"


def _itens():
    return list(parsear(ARQUIVO.read_bytes(), nome_arquivo=ARQUIVO.name))


def test_o_arquivo_existe():
    assert ARQUIVO.is_file(), f"seed ausente em {ARQUIVO}"


def test_tem_pelo_menos_500_imoveis():
    assert len(_itens()) >= 500


def test_nenhuma_linha_e_rejeitada():
    rejeitadas = [i for i in _itens() if isinstance(i, Rejeicao)]
    assert rejeitadas == [], [(r.linha, r.motivo) for r in rejeitadas[:5]]


def test_codigos_sao_unicos():
    registros = [i for i in _itens() if isinstance(i, RegistroImovel)]
    codigos = Counter(r.codigo for r in registros)
    assert [c for c, n in codigos.items() if n > 1] == []


def test_distribuicao_e_realista():
    """A RN-08.1 pede distribuicao realista de bairros, precos e tipologias.

    "Realista" nao e verificavel por assercao; o que da para exigir e que a
    base nao seja degenerada -- um unico bairro ou um unico tipo tornaria a
    demo de busca inutil e a TEC-158 nao teria o que filtrar.
    """
    registros = [i for i in _itens() if isinstance(i, RegistroImovel)]
    assert len({r.bairro for r in registros}) >= 8
    assert len({r.tipo for r in registros}) >= 4
    precos = [r.preco_venda for r in registros if r.preco_venda]
    assert max(precos) >= 3 * min(precos)
