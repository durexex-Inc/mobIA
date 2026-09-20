"""A ferramenta que lista comentarios, docstrings e prosa a reconferir, testada.

TEC-277, TEC-282 e TEC-283. Pura: as partes que decidem as cinco marcas --
ALTERADO, VIZINHO, PROSA, FALSO e NOMEIA -- nao tocam git nem disco, recebem
texto de diff, fonte, documento e conjuntos de linhas e nomes. Antes da
TEC-277 o script nao tinha teste nenhum.
"""

import ast
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import scripts.comentarios_tocados as ferramenta
from scripts.comentarios_tocados import (
    BALDE_DO_MODULO,
    MAXIMO_DE_CITACOES_POR_DOCUMENTO,
    MAXIMO_DE_VIZINHOS_POR_BLOCO,
    Achado,
    Citacao,
    _blocos,
    _comentarios,
    _docstrings,
    citacoes_do_texto,
    classificar,
    examinar,
    examinar_prosa,
    limitar,
    limitar_citacoes,
    resolver,
    scripts_nomeados,
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


def test_blocos_devolve_faixa_de_cada_def_e_class() -> None:
    fonte = textwrap.dedent("""
        class C:
            def m(self):
                pass
    """)
    faixas = _blocos(ast.parse(fonte))
    # A classe contem o metodo: as duas faixas se sobrepoem, e e por isso que
    # mexer no metodo marca os comentarios de todos os outros metodos da
    # classe. Lacuna medida na TEC-277: cortar isso renderia 0,036%.
    assert faixas == [(2, 4, "C"), (3, 4, "m")]


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


def test_docstring_de_modulo_intocada_e_vizinho(tmp_path: Path) -> None:
    """A lacuna que a TEC-283 fecha, e o caso que a TEC-282 viveu.

    Naquela branch a docstring de topo de um arquivo de teste seguiu dizendo
    "ALTERADO e VIZINHO", duas marcas de cinco, enquanto o arquivo crescia 410
    linhas por baixo dela. A ferramenta rodou contra a propria branch e nao
    apontou nada.
    """
    arquivo = _escrever(
        tmp_path,
        '''
        """Esta docstring descreve o que a funcao abaixo faz."""


        def f():
            return 1
    ''',
    )
    (achado,) = examinar(arquivo, {6})
    assert achado.alterado is False
    assert achado.linha == 2
    assert achado.bloco == BALDE_DO_MODULO


def test_arquivo_sem_docstring_de_modulo_nao_ganha_achado(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            return 1
    """,
    )
    assert examinar(arquivo, {3}) == []


def test_docstring_de_modulo_alterada_continua_alterado(tmp_path: Path) -> None:
    """Um achado so: os dois ramos sao mutuamente exclusivos, nao somam."""
    arquivo = _escrever(
        tmp_path,
        '''
        """Esta docstring mudou nesta branch."""


        def f():
            return 1
    ''',
    )
    achados = examinar(arquivo, {2, 6})
    assert len(achados) == 1
    assert achados[0].alterado is True


def test_comentario_solto_continua_fora_mesmo_com_docstring_de_modulo(
    tmp_path: Path,
) -> None:
    """A D2 do desenho, travada em teste.

    A implementacao errada e acrescentar a faixa do modulo a `_blocos`: ela
    contem todas as outras, entao todo comentario solto do arquivo viraria
    VIZINHO. Aqui o arquivo tem docstring de modulo E comentario solto, e so a
    docstring pode sair.
    """
    arquivo = _escrever(
        tmp_path,
        '''
        """Docstring de modulo."""

        # comentario solto, fora de qualquer def


        def f():
            return 1
    ''',
    )
    (achado,) = examinar(arquivo, {8})
    assert achado.linha == 2
    assert achado.bloco == BALDE_DO_MODULO


def test_o_balde_do_modulo_nao_colide_com_def_homonimo() -> None:
    """`limitar` chaveia por NOME de bloco: o balde do modulo tem de ser seu.

    Um def nao pode se chamar `<modulo>` -- os delimitadores nao sao validos em
    identificador --, entao a colisao e impossivel por construcao. Este teste
    fixa a consequencia: os dois baldes tem teto proprio.
    """
    vizinhos_do_def = [
        Achado(linha, "# vizinho", False, linha, "f")
        for linha in range(10, 10 + MAXIMO_DE_VIZINHOS_POR_BLOCO + 2)
    ]
    do_modulo = Achado(1, '"""do modulo', False, 9, BALDE_DO_MODULO)
    ficam, omitidos = limitar([do_modulo, *vizinhos_do_def], teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert do_modulo in ficam
    assert omitidos == {"f": 2}


def test_o_achado_do_modulo_nunca_e_cortado() -> None:
    """O balde `<modulo>`, com um achado so, passa inteiro pelo teto e nao
    entra em `omitidos`.

    A invariante "no maximo um achado de modulo por arquivo" e coberta
    incidentalmente pelos testes que fazem `(achado,) = examinar(...)`, onde
    um segundo achado faria o desempacotamento reprovar.
    """
    do_modulo = Achado(1, '"""do modulo', False, 500, BALDE_DO_MODULO)
    ficam, omitidos = limitar([do_modulo], teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert ficam == [do_modulo]
    assert omitidos == {}


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


def _vizinho(linha: int, distancia: int, bloco: str = "f") -> Achado:
    return Achado(linha, f"# {linha}", False, distancia, bloco)


def test_bloco_abaixo_do_teto_passa_inteiro() -> None:
    achados = [_vizinho(n, n) for n in range(1, MAXIMO_DE_VIZINHOS_POR_BLOCO + 1)]
    ficam, omitidos = limitar(achados, teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert len(ficam) == MAXIMO_DE_VIZINHOS_POR_BLOCO
    assert omitidos == {}


def test_bloco_com_menos_vizinhos_que_o_teto_nao_reporta_omissao() -> None:
    """Um inteiro negativo e verdadeiro em Python: sem a comparacao explicita,
    tres vizinhos sob teto cinco gravariam -2 como omitidos, e a saida diria
    "+-2 vizinho(s)"."""
    achados = [_vizinho(n, n) for n in range(1, 4)]
    ficam, omitidos = limitar(achados, teto=5)
    assert len(ficam) == 3
    assert omitidos == {}


def test_o_teto_guarda_os_mais_proximos() -> None:
    achados = [_vizinho(n, distancia=n) for n in range(1, 11)]
    ficam, omitidos = limitar(achados, teto=3)
    assert [a.distancia for a in ficam] == [1, 2, 3]
    assert omitidos == {"f": 7}


def test_o_teto_e_por_bloco_e_nao_global() -> None:
    achados = [_vizinho(n, n, "f") for n in range(1, 6)] + [
        _vizinho(n, n, "g") for n in range(1, 6)
    ]
    ficam, omitidos = limitar(achados, teto=2)
    assert len(ficam) == 4
    assert omitidos == {"f": 3, "g": 3}


def test_alterado_nao_e_limitado() -> None:
    """A obrigacao sobre ALTERADO e de outra natureza: e o comentario que voce
    mesmo acabou de tocar. O teto existe contra ruido de vizinhanca."""
    achados = [Achado(n, f"# {n}", True) for n in range(1, 21)]
    ficam, omitidos = limitar(achados, teto=3)
    assert len(ficam) == 20
    assert omitidos == {}


def test_o_que_fica_sai_em_ordem_de_linha() -> None:
    """Ordena por distancia para ESCOLHER, por linha para IMPRIMIR -- a saida
    tem de continuar navegavel de cima para baixo no arquivo."""
    achados = [_vizinho(10, 1), _vizinho(2, 2), _vizinho(30, 3)]
    ficam, _ = limitar(achados, teto=3)
    assert [a.linha for a in ficam] == [2, 10, 30]


def test_teto_zero_desliga_o_corte() -> None:
    """E como `--tudo` e implementado: um teto que nao morde."""
    achados = [_vizinho(n, n) for n in range(1, 51)]
    ficam, omitidos = limitar(achados, teto=0)
    assert len(ficam) == 50
    assert omitidos == {}


def test_citacao_reconhece_linha_unica_e_faixa() -> None:
    """As duas formas que a prosa deste repo usa, medidas na TEC-282.

    Faixa devolve inicio e fim distintos; linha unica devolve os dois iguais,
    para o resto do codigo nao precisar de dois caminhos.
    """
    texto = "olha `tests/conftest.py:464` e tambem turno.py:132-142 aqui"
    assert citacoes_do_texto(texto) == [
        (1, "tests/conftest.py", 464, 464),
        (1, "turno.py", 132, 142),
    ]


def test_citacao_ignora_a_cauda_de_um_nome_pontuado() -> None:
    """O que o lookbehind de fato impede, medido contra a regex sem ele.

    Em `mobia.infra.crypto.py:10` o motor casaria `crypto.py`, que nao e
    caminho de arquivo nenhum e resolveria para vazio. O caminho com barra
    continua saindo inteiro -- esse o guloso ja garantia sozinho.
    """
    assert citacoes_do_texto("veja mobia.infra.crypto.py:10 aqui") == []
    assert citacoes_do_texto("src/mobia/turno.py:10") == [(1, "src/mobia/turno.py", 10, 10)]


def test_citacao_ignora_o_que_nao_e_citacao() -> None:
    """Extensao vizinha e link com `#L` nao sao a forma `arquivo.py:linha`.

    O link markdown deste repo traz o texto visivel `turno.py:508` junto, e e
    ele que casa -- o alvo do link nao precisa casar tambem, sob pena de o
    mesmo ponto virar dois achados.
    """
    assert citacoes_do_texto("nada.pyc:12 nem x.py sozinho") == []
    assert citacoes_do_texto("[`turno.py:508`](../src/turno.py#L508)") == [
        (1, "turno.py", 508, 508)
    ]


def test_citacao_informa_a_linha_do_documento() -> None:
    """A linha e a do .md, nao a citada -- e por ela que o revisor abre o texto."""
    assert citacoes_do_texto("primeira\nsegunda\nveja turno.py:50") == [(3, "turno.py", 50, 50)]


_PY = {
    "src/mobia/domain/agente/turno.py",
    "src/mobia/domain/followup/repositorio.py",
    "src/mobia/domain/outbound/repositorio.py",
    "tests/conftest.py",
}


def test_resolver_aceita_o_caminho_exato() -> None:
    assert resolver("tests/conftest.py", _PY) == ["tests/conftest.py"]


def test_resolver_aceita_sufixo_de_caminho() -> None:
    """`agente/turno.py` designa o arquivo sem que a prosa repita src/mobia/."""
    assert resolver("agente/turno.py", _PY) == ["src/mobia/domain/agente/turno.py"]


def test_resolver_aceita_o_nome_sozinho() -> None:
    """55 das 155 citacoes medidas na TEC-282 sao so o nome, sem caminho."""
    assert resolver("turno.py", _PY) == ["src/mobia/domain/agente/turno.py"]


def test_resolver_devolve_os_dois_quando_o_nome_e_ambiguo() -> None:
    """`repositorio.py` bate 9 arquivos no repo real.

    A ferramenta nao escolhe um: devolve os candidatos e deixa a classificacao
    decidir, que e onde a regra de errar por sobra e nao por falta mora.
    """
    assert resolver("repositorio.py", _PY) == [
        "src/mobia/domain/followup/repositorio.py",
        "src/mobia/domain/outbound/repositorio.py",
    ]


def test_resolver_devolve_vazio_para_arquivo_que_nao_existe() -> None:
    assert resolver("inventado.py", _PY) == []


def test_resolver_exige_fronteira_de_diretorio_no_sufixo() -> None:
    """A barra na comparacao de sufixo, e o alvo que a exercita de verdade.

    `tout/repositorio.py` e um truncamento de `optout/repositorio.py`. Sem a
    barra na comparacao, ele casaria; com ela, nao casa nada -- que e o certo,
    porque `tout/` nao e diretorio nenhum.
    """
    assert resolver("tout/repositorio.py", _PY) == []
    assert resolver("followup/repositorio.py", _PY) == ["src/mobia/domain/followup/repositorio.py"]


def test_resolver_exige_nome_inteiro_no_terceiro_degrau() -> None:
    """`no.py` nao casa com `turno.py`, e quem o impede e a igualdade de nome.

    O alvo nao tem barra, entao o ramo de sufixo nem roda: a protecao aqui vem
    do terceiro degrau comparar o nome inteiro, nao por sufixo.
    """
    assert resolver("no.py", _PY) == []


def _tamanhos(mapa: dict[str, int]) -> Callable[[str], int]:
    return lambda caminho: mapa[caminho]


def test_citacao_a_arquivo_alterado_e_prosa() -> None:
    marca = classificar(["a/turno.py"], 50, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "PROSA"


def test_citacao_a_arquivo_intocado_nao_vira_achado() -> None:
    """A ferramenta continua sendo sobre o que a branch tocou."""
    assert classificar(["a/turno.py"], 50, {"outro.py"}, _tamanhos({"a/turno.py": 300})) is None


def test_citacao_que_nao_resolve_nao_vira_achado() -> None:
    assert classificar([], 50, {"a/turno.py"}, _tamanhos({})) is None


def test_faixa_alem_do_fim_do_arquivo_e_falso() -> None:
    """A unica marca que afirma, em vez de suspeitar."""
    marca = classificar(["a/turno.py"], 900, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "FALSO"


def test_a_ultima_linha_do_arquivo_ainda_e_prosa() -> None:
    """A fronteira e `>`, nao `>=`: citar a ultima linha e citacao valida."""
    marca = classificar(["a/turno.py"], 300, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "PROSA"


def test_arquivo_ilegivel_nao_vira_falso() -> None:
    """Falha de leitura nao autoriza afirmar que a citacao e falsa.

    Um tamanho 0 faria qualquer citacao parecer alem do fim do arquivo, e FALSO e
    a marca que dispensa o revisor de conferir. O fallback e `maxsize` para a
    citacao cair em PROSA: errar por sobra de suspeita e barato, afirmar o que nao
    se sabe nao e.
    """
    marca = classificar(["x.py"], 5, {"x.py"}, lambda _: sys.maxsize)
    assert marca == "PROSA"


def test_citacao_ambigua_alem_do_fim_sai_como_prosa_e_nao_falso() -> None:
    """FALSO exige resolucao inequivoca, e a razao e a direcao do erro.

    Declarar falsa uma citacao que talvez aponte o OUTRO candidato seria a
    ferramenta afirmando o que nao sabe -- o unico erro que ela nao pode
    cometer, porque `FALSO` e a marca que dispensa o revisor de conferir.
    """
    marca = classificar(
        ["a/repositorio.py", "b/repositorio.py"],
        900,
        {"a/repositorio.py"},
        _tamanhos({"a/repositorio.py": 300, "b/repositorio.py": 1000}),
    )
    assert marca == "PROSA"


def test_arquivo_intocado_vence_a_faixa_alem_do_fim() -> None:
    """A ordem das duas checagens em `classificar`, fixada por teste.

    Candidato unico, faixa que estoura o arquivo, mas arquivo que a branch nao
    tocou: o certo e None. Invertendo as duas checagens, sairia FALSO para
    arquivo intocado -- e a ferramenta afirmaria coisa sobre codigo que esta
    branch nao mexeu. O CLAUDE.md registra na TEC-146 o preco de ordem de
    checagem sem rede.
    """
    marca = classificar(["a/turno.py"], 900, {"outro.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca is None


def test_nomeia_encontra_o_script_alterado_no_texto() -> None:
    texto = "rode `scripts/comentarios_tocados.py` antes do PR"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [(1, "comentarios_tocados.py")]


def test_nomeia_ignora_script_que_a_branch_nao_tocou() -> None:
    assert scripts_nomeados("veja gerar_base_simulada.py", {"comentarios_tocados.py"}) == []


def test_nomeia_sai_uma_vez_so_por_script() -> None:
    """O CLAUDE.md nomeia o script duas vezes e e um documento a reconferir, nao dois.

    Repetir a marca por ocorrencia encheria a secao com o mesmo aviso e e
    exatamente o volume que a TEC-277 mediu e cortou.
    """
    texto = "comentarios_tocados.py\noutra linha\ncomentarios_tocados.py --tudo"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [(1, "comentarios_tocados.py")]


def test_nomeia_encontra_dentro_de_bloco_de_codigo() -> None:
    """Medido na TEC-282: no CLAUDE.md as duas mencoes estao DENTRO de fences.

    Filtrar bloco de codigo excluiria justamente o documento que a card existe
    para pegar -- a prosa que descreve o script vive ao redor do bloco, sem
    repetir o nome do arquivo.
    """
    texto = "```bash\n./.venv/Scripts/python.exe scripts/comentarios_tocados.py\n```"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [(2, "comentarios_tocados.py")]


def test_nomeia_exige_fronteira_e_nao_casa_dentro_de_outro_nome() -> None:
    """Mesma protecao que `_CITACAO` e o terceiro degrau de `resolver` ja tinham.

    Um script de nome curto casaria dentro de outro nome de arquivo. Nao acontece
    com os dois scripts de hoje, e e por isso que a protecao precisa de teste: e o
    script futuro de nome curto que a quebraria em silencio.
    """
    assert scripts_nomeados("veja ba.py para outro contexto", {"a.py"}) == []
    assert scripts_nomeados("rode scripts/a.py agora", {"a.py"}) == [(1, "a.py")]


def test_nomeia_tolera_mencao_que_nao_descreve_o_script() -> None:
    """A tolerancia declarada: a busca nao distingue descricao de mencao.

    O CLAUDE.md cita `gerar_base_simulada.py` num relato historico sobre o gate
    de formatacao, que nao descreve o script. Ele sai como NOMEIA do mesmo jeito.
    Separar os dois casos e semantica, que esta card poe fora de escopo, e a marca
    e suspeita e nao veredito -- o revisor descarta em segundos.
    """
    texto = "o `ruff format --check` reprovou `gerar_base_simulada.py` de primeira"
    assert scripts_nomeados(texto, {"gerar_base_simulada.py"}) == [(1, "gerar_base_simulada.py")]


def _prosa(linha: int, marca: str = "PROSA") -> Citacao:
    return Citacao(documento="d.md", linha=linha, texto="x.py:1", marca=marca)


def test_documento_abaixo_do_teto_passa_inteiro() -> None:
    citacoes = [_prosa(n) for n in range(1, MAXIMO_DE_CITACOES_POR_DOCUMENTO + 1)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=MAXIMO_DE_CITACOES_POR_DOCUMENTO)
    assert len(ficam) == MAXIMO_DE_CITACOES_POR_DOCUMENTO
    assert omitidas == 0


def test_o_teto_corta_prosa_e_conta_o_que_omitiu() -> None:
    citacoes = [_prosa(n) for n in range(1, 10)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=5)
    assert [c.linha for c in ficam] == [1, 2, 3, 4, 5]
    assert omitidas == 4


def test_falso_e_nomeia_escapam_do_teto() -> None:
    """Pela mesma razao que ALTERADO escapa: o teto existe contra vizinhanca.

    Um FALSO cortado seria a ferramenta escondendo a unica coisa que ela sabe
    com certeza estar errada.
    """
    citacoes = [_prosa(n) for n in range(1, 10)]
    citacoes.append(_prosa(20, marca="FALSO"))
    citacoes.append(_prosa(21, marca="NOMEIA"))
    ficam, omitidas = limitar_citacoes(citacoes, teto=2)
    assert [c.linha for c in ficam] == [1, 2, 20, 21]
    assert omitidas == 7


def test_teto_zero_desliga_o_corte_das_citacoes() -> None:
    """E assim que --tudo e implementado, sem caminho separado que possa divergir."""
    citacoes = [_prosa(n) for n in range(1, 10)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=0)
    assert len(ficam) == 9
    assert omitidas == 0


def test_as_citacoes_saem_em_ordem_de_linha_do_documento() -> None:
    ficam, _ = limitar_citacoes([_prosa(9), _prosa(2), _prosa(5)], teto=0)
    assert [c.linha for c in ficam] == [2, 5, 9]


def test_examinar_prosa_monta_as_tres_marcas() -> None:
    texto = (
        "o corte em repositorio.py:209 explica tudo\n"
        "e test_x.py:900 aponta alem do fim\n"
        "rode scripts/comentarios_tocados.py antes do PR\n"
        "mas intocado.py:5 nao interessa\n"
    )
    achados = examinar_prosa(
        "CLAUDE.md",
        texto,
        arquivos_py={"a/repositorio.py", "t/test_x.py", "intocado.py"},
        alterados={"a/repositorio.py", "t/test_x.py"},
        scripts={"comentarios_tocados.py"},
        tamanho_de=lambda c: 300,
    )
    assert [(c.linha, c.marca) for c in achados] == [
        (1, "PROSA"),
        (2, "FALSO"),
        (3, "NOMEIA"),
    ]


def test_examinar_prosa_preenche_o_destino_so_quando_ele_acrescenta() -> None:
    """Para `repositorio.py:209` o destino diz onde o arquivo mora.

    Para um alvo que ja veio com caminho completo, repetir o caminho na saida
    seria ruido -- o revisor ja leu a mesma string dois centimetros antes.
    """
    achados = examinar_prosa(
        "d.md",
        "repositorio.py:9 e a/turno.py:9",
        arquivos_py={"a/repositorio.py", "a/turno.py"},
        alterados={"a/repositorio.py", "a/turno.py"},
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert [c.destino for c in achados] == ["a/repositorio.py", ""]


def test_examinar_prosa_preenche_linhas_do_arquivo_so_para_falso() -> None:
    """A evidencia da unica marca que afirma em vez de suspeitar.

    `classificar` so devolve FALSO com resolucao inequivoca, entao o indice 0
    de `candidatos` e seguro. PROSA nao ganha a contagem -- ela nao afirma
    nada sobre o tamanho do arquivo.
    """
    achados = examinar_prosa(
        "d.md",
        "turno.py:9 esta ok, mas test_x.py:900 aponta alem do fim\n",
        arquivos_py={"t/test_x.py", "a/turno.py"},
        alterados={"t/test_x.py", "a/turno.py"},
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert [(c.marca, c.linhas_do_arquivo) for c in achados] == [
        ("PROSA", 0),
        ("FALSO", 300),
    ]


def test_examinar_prosa_nao_marca_nada_sem_script_alterado() -> None:
    achados = examinar_prosa(
        "CLAUDE.md",
        "rode scripts/comentarios_tocados.py",
        arquivos_py=set(),
        alterados=set(),
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert achados == []


def test_examinar_prosa_reproduz_a_faixa_como_o_documento_a_escreveu() -> None:
    """A saida tem de ser encontravel no .md que ela manda reconferir.

    Mostrar so o fim de `turno.py:132-142` daria `turno.py:142`, string que nao
    existe no documento -- e quem fosse procura-la nao acharia nada. Medido na
    TEC-282: 24 das 62 citacoes no escopo sao faixas.
    """
    achados = examinar_prosa(
        "d.md",
        "veja a/turno.py:132-142 aqui",
        arquivos_py={"a/turno.py"},
        alterados={"a/turno.py"},
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert [c.texto for c in achados] == ["a/turno.py:132-142"]


def test_o_escopo_exclui_planos_e_inclui_o_claude_md(monkeypatch) -> None:
    """D1 do desenho: 70% do volume medido vinha de planos de branches fechadas."""
    monkeypatch.setattr(
        ferramenta,
        "_rodar",
        lambda *a: "CLAUDE.md\ndocs/superpowers/plans/x.md\ndocs/superpowers/specs/y.md\n",
    )
    assert ferramenta._documentos_no_escopo() == ["CLAUDE.md", "docs/superpowers/specs/y.md"]


def test_main_imprime_a_secao_de_prosa(monkeypatch, capsys, tmp_path) -> None:
    """O caminho inteiro, de ponta a ponta, com git e disco falsos."""
    alvo = tmp_path / "turno.py"
    alvo.write_text("x = 1\n" * 300, encoding="utf-8")
    documento = tmp_path / "CLAUDE.md"
    documento.write_text("o corte em turno.py:50 explica tudo\n", encoding="utf-8")

    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            return "+++ b/turno.py\n@@ -1 +40,3 @@\n"
        if argumentos[:2] == ("ls-files", "*.md"):
            return "CLAUDE.md\n"
        if argumentos[:2] == ("ls-files", "*.py"):
            return "turno.py\n"
        return ""

    monkeypatch.setattr(ferramenta, "_rodar", _git)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py"])

    assert ferramenta.main() == 0
    saida = capsys.readouterr().out
    assert "CLAUDE.md" in saida
    assert "PROSA" in saida
    assert "turno.py:50" in saida
    assert "1 em prosa" in saida


def test_main_continua_devolvendo_zero_com_prosa_falsa(monkeypatch, capsys, tmp_path) -> None:
    """A ferramenta informa e nao reprova, e a marca FALSO nao muda isso."""
    (tmp_path / "turno.py").write_text("x = 1\n" * 10, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("veja turno.py:900\n", encoding="utf-8")

    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            return "+++ b/turno.py\n@@ -1 +5,1 @@\n"
        if argumentos[:2] == ("ls-files", "*.md"):
            return "CLAUDE.md\n"
        if argumentos[:2] == ("ls-files", "*.py"):
            return "turno.py\n"
        return ""

    monkeypatch.setattr(ferramenta, "_rodar", _git)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py"])

    assert ferramenta.main() == 0
    saida = capsys.readouterr().out
    assert "FALSO" in saida
    assert "comprovadamente falsa" in saida
    assert "(o arquivo tem 10 linhas)" in saida
