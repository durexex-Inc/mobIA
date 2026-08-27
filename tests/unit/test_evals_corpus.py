from pathlib import Path

import pytest

from mobia.domain.agente.schemas import Intencao
from mobia.evals.corpus import CorpusInvalido, carregar, total_de_turnos


def _escrever(diretorio: Path, nome: str, conteudo: str) -> None:
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


def test_rotulo_fora_do_enum_e_recusado_nomeando_a_conversa(tmp_path: Path) -> None:
    """Um COMPRA_ com typo viraria turno silenciosamente sempre-errado.

    A acuracia cairia por defeito do corpus, nao do prompt, e o gate barraria
    um merge inocente apontando para o lugar errado. A mensagem tem de dizer
    qual conversa, senao achar o typo em 50 arquivos e busca manual.
    """
    _escrever(
        tmp_path,
        "compra.yaml",
        "- id: compra-01\n"
        "  descricao: teste\n"
        "  turnos:\n"
        "    - lead: quanto custa o apartamento\n"
        "      intencao: COMPRA_\n",
    )

    with pytest.raises(CorpusInvalido, match="compra-01"):
        carregar(tmp_path)


def test_id_duplicado_entre_arquivos_e_recusado(tmp_path: Path) -> None:
    """Dois turnos com o mesmo id tornam o relatorio ambiguo: apontar
    'compra-01 errou' deixa de identificar uma conversa.
    """
    corpo = (
        "- id: repetido\n"
        "  descricao: teste\n"
        "  turnos:\n"
        "    - lead: quero comprar\n"
        "      intencao: COMPRA\n"
    )
    _escrever(tmp_path, "compra.yaml", corpo)
    _escrever(tmp_path, "aluguel.yaml", corpo)

    with pytest.raises(CorpusInvalido, match="repetido"):
        carregar(tmp_path)


def test_conversa_sem_turnos_e_recusada(tmp_path: Path) -> None:
    """Conversa vazia nao mede nada e inflaria a contagem de conversas sem
    acrescentar um turno sequer ao denominador.
    """
    _escrever(tmp_path, "compra.yaml", "- id: vazia\n  descricao: teste\n  turnos: []\n")

    with pytest.raises(CorpusInvalido, match="vazia"):
        carregar(tmp_path)


def test_carrega_conversas_tipadas_e_soma_os_turnos(tmp_path: Path) -> None:
    _escrever(
        tmp_path,
        "compra.yaml",
        "- id: compra-01\n"
        "  descricao: lead abre por preco e vira aluguel\n"
        "  turnos:\n"
        "    - lead: quanto custa o apartamento\n"
        "      intencao: COMPRA\n"
        "    - lead: pra comprar ta fora, tem pra alugar\n"
        "      intencao: ALUGUEL\n",
    )

    conversas = carregar(tmp_path)

    assert len(conversas) == 1
    assert conversas[0].id == "compra-01"
    assert [turno.intencao for turno in conversas[0].turnos] == [
        Intencao.COMPRA,
        Intencao.ALUGUEL,
    ]
    assert total_de_turnos(conversas) == 2


def test_turno_nao_mapeamento_e_recusado_nomeando_conversa(tmp_path: Path) -> None:
    """Turno que nao e um mapeamento (string, numero, etc) nao pode ser
    indexado e vira AttributeError cru se nao validado. Mensagem deve nomear
    arquivo e conversa como as demais recusas.
    """
    _escrever(
        tmp_path,
        "compra.yaml",
        "- id: compra-01\n  descricao: teste\n  turnos:\n    - turno_invalido_como_string\n",
    )

    with pytest.raises(CorpusInvalido, match="compra-01"):
        carregar(tmp_path)
