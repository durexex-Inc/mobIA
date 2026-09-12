"""As regras puras da recomendacao e da reacao.

TEC-163. Sem banco, sem I/O. Basename distinto de tudo em
`tests/integration/`.
"""

from mobia.domain.agente.recomendacao import motivo_do_match


def test_o_motivo_lista_os_criterios_que_casaram() -> None:
    """D5: derivado do que a busca sabe, nunca escrito pelo modelo."""
    assert motivo_do_match(["3 quartos", "Trindade", "ate R$ 400 mil"]) == (
        "3 quartos, Trindade, ate R$ 400 mil"
    )


def test_um_criterio_so_nao_ganha_virgula() -> None:
    assert motivo_do_match(["Trindade"]) == "Trindade"


def test_busca_sem_criterio_diz_isso_em_vez_de_ficar_vazia() -> None:
    """`motivo_match` e NOT NULL, e string vazia num campo de explicabilidade
    e pior que uma frase honesta: quem le a linha meses depois precisa saber
    que nao houve filtro, nao ficar sem saber o que aconteceu."""
    assert motivo_do_match([]) == "sem filtro: o lead nao restringiu a busca"


def test_o_motivo_e_ascii() -> None:
    """Vai para o banco e pode ser lido em relatorio; segue a disciplina do
    repo para texto que nao e prosa de docs."""
    assert motivo_do_match(["3 quartos", "Trindade"]).isascii()
