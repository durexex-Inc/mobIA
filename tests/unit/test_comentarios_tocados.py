"""A ferramenta que lista comentarios a reconferir, testada.

TEC-277. Pura: as partes que decidem o que e ALTERADO e o que e VIZINHO nao
tocam git nem disco -- recebem texto de diff, fonte e um conjunto de linhas.
Antes desta card o script nao tinha teste nenhum.
"""

import ast
import textwrap
from pathlib import Path

import scripts.comentarios_tocados as ferramenta
from scripts.comentarios_tocados import (
    _blocos,
    _comentarios,
    _docstrings,
    examinar,
)


def test_comentario_dentro_de_string_nao_e_comentario() -> None:
    """A razao de o script usar `tokenize` e nao regex, e nada provava isso.

    Um `#` dentro de string e texto, nao comentario. Com regex, este caso sai
    como comentario e a listagem passa a apontar linhas que nao existem.
    """
    fonte = textwrap.dedent("""
        url = "http://exemplo/#ancora"
        # este sim
    """)
    achados = _comentarios(fonte)
    assert [texto for _, texto in achados] == ["# este sim"]


def test_docstring_de_modulo_classe_funcao_e_async() -> None:
    """A ordem segue `ast.walk`, que e BFS -- nao a ordem de leitura do texto.

    Medido: modulo, depois classe C, depois a funcao async (irma de C dentro
    do modulo), e so por ultimo o metodo m (neto do modulo, filho de C). BFS
    visita por nivel de profundidade, entao a async de nivel 1 vem antes do
    metodo de nivel 2, mesmo aparecendo depois no arquivo.
    """
    fonte = textwrap.dedent('''
        """do modulo"""


        class C:
            """da classe"""

            def m(self):
                """do metodo"""


        async def f():
            """da async"""
    ''')
    textos = [texto for _, _, texto in _docstrings(ast.parse(fonte))]
    assert textos == [
        '"""do modulo',
        '"""da classe',
        '"""da async',
        '"""do metodo',
    ]


def test_string_solta_no_corpo_nao_e_docstring() -> None:
    """So a PRIMEIRA expressao do corpo conta. Uma string no meio e valor."""
    fonte = textwrap.dedent("""
        def f():
            x = 1
            "isto nao e docstring"
    """)
    assert _docstrings(ast.parse(fonte)) == []


def test_blocos_devolve_faixa_de_cada_def_e_class(tmp_path: Path) -> None:
    fonte = textwrap.dedent("""
        class C:
            def m(self):
                pass
    """)
    faixas = _blocos(ast.parse(fonte))
    # A classe contem o metodo: as duas faixas se sobrepoem, e e por isso que
    # mexer no metodo marca os comentarios de todos os outros metodos da
    # classe. Lacuna medida na TEC-277: cortar isso renderia 0,036%.
    assert len(faixas) == 2


def _escrever(tmp_path: Path, fonte: str) -> Path:
    arquivo = tmp_path / "alvo.py"
    arquivo.write_text(textwrap.dedent(fonte), encoding="utf-8")
    return arquivo


def test_comentario_na_linha_alterada_e_alterado(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # este comentario
            return 1
    """,
    )
    (achado,) = examinar(arquivo, {3})
    assert achado.alterado is True


def test_comentario_no_bloco_mexido_e_vizinho(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # este comentario
            return 1
    """,
    )
    (achado,) = examinar(arquivo, {4})
    assert achado.alterado is False


def test_alterado_ganha_de_vizinho(tmp_path: Path) -> None:
    """Quando as duas condicoes valem, nao ha dupla contagem."""
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # este comentario
            return 1
    """,
    )
    achados = examinar(arquivo, {3, 4})
    assert len(achados) == 1
    assert achados[0].alterado is True


def test_comentario_fora_de_bloco_nunca_e_vizinho(tmp_path: Path) -> None:
    """Lacuna L2 do desenho, travada em teste para nao sumir sem alguem notar.

    Comentario de nivel de modulo nao esta contido em def nem class, entao
    `dentro_de_bloco_mexido` nunca o alcanca. Se um dia isto passar a marcar,
    foi mudanca deliberada e este teste e o lugar de registra-la.
    """
    arquivo = _escrever(
        tmp_path,
        """
        # comentario de modulo


        def f():
            return 1
    """,
    )
    assert examinar(arquivo, {5}) == []


def test_arquivo_que_nao_parseia_devolve_lista_vazia(tmp_path: Path) -> None:
    arquivo = tmp_path / "quebrado.py"
    arquivo.write_text("def (", encoding="utf-8")
    assert examinar(arquivo, {1}) == []


def test_a_distancia_e_ate_a_linha_alterada_mais_proxima(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # comentario
            a = 1
            b = 2
            c = 3
            return a
    """,
    )
    # alteradas: 6 e 7. O comentario esta na 3, entao a mais proxima e a 6.
    (achado,) = [a for a in examinar(arquivo, {6, 7}) if not a.alterado]
    assert achado.distancia == 3


def test_a_distancia_de_um_alterado_e_zero(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # comentario
            return 1
    """,
    )
    (achado,) = examinar(arquivo, {3})
    assert achado.distancia == 0


def test_a_distancia_de_docstring_mede_da_faixa_inteira(tmp_path: Path) -> None:
    """A docstring ocupa varias linhas; a distancia sai da borda mais proxima,
    nao da primeira linha -- senao uma docstring longa parece longe de uma
    alteracao colada no fim dela."""
    arquivo = _escrever(
        tmp_path,
        '''
        def f():
            """linha um
            linha dois
            linha tres
            """
            return 1
    ''',
    )
    (achado,) = [a for a in examinar(arquivo, {7}) if not a.alterado]
    assert achado.distancia == 1


def test_o_bloco_dono_e_o_menor_que_contem_o_achado(tmp_path: Path) -> None:
    """Para ATRIBUIR, e nao para classificar.

    O desenho mediu que usar o menor bloco para CLASSIFICAR rende 0,036% e nao
    vale. Mas para dizer "+K em qual funcao" o menor bloco e o unico nome util:
    dizer "+703 em C" quando o comentario esta em `C.m` nao ajuda ninguem.
    """
    arquivo = _escrever(
        tmp_path,
        """
        class C:
            def m(self):
                # comentario
                return 1
    """,
    )
    (achado,) = [a for a in examinar(arquivo, {5}) if not a.alterado]
    assert achado.bloco == "m"


def test_alterado_nao_recebe_bloco(tmp_path: Path) -> None:
    """O teto nao morde ALTERADO, entao ele nao precisa de dono."""
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            # comentario
            return 1
    """,
    )
    (achado,) = examinar(arquivo, {3})
    assert achado.bloco == ""


def _com_diff(monkeypatch, saida: str) -> dict:
    monkeypatch.setattr(ferramenta, "_rodar", lambda *_: saida)
    return ferramenta.linhas_alteradas("qualquer")


def test_hunk_sem_virgula_conta_uma_linha(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1 +12 @@\n")
    assert resultado == {Path("a.py"): {12}}


def test_hunk_com_contagem_conta_todas(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1,3 +12,3 @@\n")
    assert resultado == {Path("a.py"): {12, 13, 14}}


def test_hunk_de_remocao_pura_nao_gera_linha(monkeypatch) -> None:
    """Lacuna L3 do desenho. Apagar o codigo que um comentario descrevia e
    deixar o comentario nao dispara ALTERADO -- so VIZINHO, e so se houver
    alguma linha adicionada no mesmo bloco. Travado para nao mudar por acaso."""
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1,3 +12,0 @@\n")
    assert resultado == {}


def test_arquivo_deletado_e_ignorado(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ /dev/null\n@@ -1,3 +0,0 @@\n")
    assert resultado == {}
