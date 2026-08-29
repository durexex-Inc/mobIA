from pathlib import Path

import pytest

from mobia.domain.agente.schemas import Intencao
from mobia.evals.corpus import CorpusInvalido, TurnoAnotado, _turno_de, carregar, total_de_turnos

# O corpus real, ja com anotacao de `campos` desde a TEC-145 T5.
CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


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


def test_turno_sem_campos_tem_campos_none() -> None:
    """Turno nao anotado nao entra na medicao de extracao."""
    conversas = carregar(CORPUS)
    assert any(turno.campos is None for conversa in conversas for turno in conversa.turnos)


def test_campo_desconhecido_no_corpus_e_erro() -> None:
    with pytest.raises(CorpusInvalido):
        _turno_de(
            {"lead": "oi", "intencao": "COMPRA", "campos": {"piscina": True}},
            "compra-99",
            "compra.yaml",
        )


def test_valor_fora_do_vocabulario_e_erro() -> None:
    with pytest.raises(CorpusInvalido):
        _turno_de(
            {"lead": "oi", "intencao": "COMPRA", "campos": {"tipo_imovel": "IATE"}},
            "compra-99",
            "compra.yaml",
        )


def test_campos_vazio_e_aceito_como_turno_negativo(tmp_path: Path) -> None:
    """`{}` e o unico jeito de dizer "o lead nao afirmou nada aqui".

    Sem ele, invencao so pode ser medida nos turnos que afirmam alguma coisa,
    e um modelo que inventa em todo turno nao anotado tira 100%.
    """
    (tmp_path / "c.yaml").write_text(
        "- id: compra-01\n"
        "  descricao: teste\n"
        "  turnos:\n"
        '    - lead: "quanto tempo leva pra aprovar o cadastro?"\n'
        "      intencao: COMPRA\n"
        "      campos: {}\n",
        encoding="utf-8",
    )

    turno = carregar(tmp_path)[0].turnos[0]

    assert turno.campos == {}
    assert turno.negativo


def test_campos_sem_valor_e_recusado_por_ser_ambiguo(tmp_path: Path) -> None:
    """`campos:` nulo e `campos: {}` sao dois caracteres de diferenca e
    significados opostos -- "fora da medicao" contra "tudo que vier e erro".
    A mensagem tem de dizer as duas saidas, senao quem errar o typo nao sabe
    qual das duas queria."""
    (tmp_path / "c.yaml").write_text(
        "- id: compra-01\n"
        "  descricao: teste\n"
        "  turnos:\n"
        '    - lead: "oi"\n'
        "      intencao: COMPRA\n"
        "      campos:\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusInvalido) as erro:
        carregar(tmp_path)

    assert "compra-01" in str(erro.value)
    assert "campos: {}" in str(erro.value)


def test_os_tres_estados_de_anotacao_tem_propriedade_propria() -> None:
    """Quatro lugares do codigo testavam `campos` por veracidade e um por
    `is not None`. Isso era inocuo so enquanto `{}` era impossivel."""
    fora = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos=None)
    negativo = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos={})
    positivo = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos={"quartos": 2})

    assert (fora.anotado, fora.positivo, fora.negativo) == (False, False, False)
    assert (negativo.anotado, negativo.positivo, negativo.negativo) == (True, False, True)
    assert (positivo.anotado, positivo.positivo, positivo.negativo) == (True, True, False)
