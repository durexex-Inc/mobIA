from pathlib import Path

import pytest
import yaml

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "moderacao"
ARQUIVOS = (
    "entrada_bloqueia",
    "entrada_libera",
    "saida_bloqueia",
    "saida_libera",
    "entrada_injecao",
    "entrada_injecao_benigna",
)


def _casos(nome: str) -> list[dict]:
    return yaml.safe_load((CORPUS / f"{nome}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("nome", ARQUIVOS)
def test_cada_arquivo_tem_massa_minima(nome: str) -> None:
    """Dez por arquivo. Menos que isso e uma taxa em que um caso vale 10 pontos,
    e o numero vira ruido em vez de medida.
    """
    assert len(_casos(nome)) >= 10


@pytest.mark.parametrize("nome", ARQUIVOS)
def test_todo_caso_tem_id_texto_e_porque(nome: str) -> None:
    """`porque` nao e enfeite: e a anotacao a mao que justifica o rotulo. Sem
    ela ninguem consegue revisar o corpus, e corpus irrevisavel nao mede.
    """
    for caso in _casos(nome):
        assert caso["id"]
        assert caso["texto"]
        assert caso["porque"]


def test_os_dois_lados_existem_nas_duas_direcoes() -> None:
    """Um moderador que bloqueia tudo passa em corpus so-positivo, e parece
    seguro. O corpus de controle e o que separa moderacao de censura.
    """
    for direcao in ("entrada", "saida"):
        assert _casos(f"{direcao}_bloqueia")
        assert _casos(f"{direcao}_libera")


def test_o_controle_de_entrada_cobre_o_falso_positivo_caro() -> None:
    """Lead irritado, palavrao como enfase e reclamacao dura precisam estar no
    corpus que NAO deve bloquear. Bloquear reclamacao legitima e o falso
    positivo mais caro deste sistema: perde o cliente que estava reclamando.
    """
    ids = {caso["id"] for caso in _casos("entrada_libera")}
    for esperado in ("entrada-libera-reclamacao", "entrada-libera-palavrao-enfase"):
        assert esperado in ids


def test_ids_sao_unicos_entre_todos_os_arquivos() -> None:
    vistos: set[str] = set()
    for nome in ARQUIVOS:
        for caso in _casos(nome):
            assert caso["id"] not in vistos, caso["id"]
            vistos.add(caso["id"])


def test_a_injecao_tem_o_gemeo_benigno() -> None:
    """TEC-204, D3. Detectar injecao em corpus so de ataque parece preciso;
    "esquece o que eu falei, quero 3 quartos" e o falso positivo que o
    desenho nomeia, e ele precisa estar no corpus."""
    assert _casos("entrada_injecao")
    ids = {caso["id"] for caso in _casos("entrada_injecao_benigna")}
    assert "entrada-injecao-benigna-corrige-o-pedido" in ids
