"""Guarda a sonda da TEC-271 contra as duas divergencias que ela nao anuncia.

A sonda le os textos do corpus por id e enxerta as candidatas em
`SISTEMA_DA_ENTRADA` por ancora. As duas coisas erram em silencio: um id
renomeado mede zero caso, uma ancora quebrada mede o braco atual tres vezes --
e nenhuma das duas apareceria antes de 240 chamadas pagas, numa tabela que
parece uma tabela.

Nada aqui chama o modelo. O import da sonda so manipula string, e a primeira
chamada dela sai dentro de `main()`.
"""

import re
import unicodedata

from evals.sonda_composicao_familiar import BRACOS, CASOS, REPETICOES, textos_do_corpus
from mobia.infra.moderacao import SISTEMA_DA_ENTRADA


def _normalizar(texto: str) -> list[str]:
    """Minusculas, sem acento, so as palavras.

    O corpus e acentuado e o prompt de sistema nao, por convencao do repo.
    Comparar os dois crus nunca acharia nada, e o teste de citacao abaixo
    passaria sempre, sem guardar coisa nenhuma.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.findall(r"[a-z]+", sem_acento)


def _quadrigramas(texto: str) -> set[tuple[str, ...]]:
    palavras = _normalizar(texto)
    return {tuple(palavras[i : i + 4]) for i in range(len(palavras) - 3)}


def test_os_quatro_ids_do_eixo_existem_no_corpus() -> None:
    """Um id renomeado no YAML nao levanta nada: mede zero caso e imprime tabela."""
    textos = textos_do_corpus()

    assert len(textos) == 4
    assert all(textos[caso_id].strip() for caso_id, _, _ in CASOS)


def test_os_dois_bracos_sao_distintos_e_o_atual_e_o_de_producao() -> None:
    """O braco `atual` e o **antes** da medicao.

    Se ele nao for byte a byte o prompt de producao, a comparacao entre bracos
    deixa de medir a mudanca e passa a medir uma diferenca que ninguem escreveu.
    """
    assert len(BRACOS) == 2
    assert BRACOS["atual"] == SISTEMA_DA_ENTRADA
    assert len(set(BRACOS.values())) == 2


def test_as_candidatas_preservam_o_prompt_de_producao() -> None:
    """Enxerto que apaga texto e o modo silencioso de o experimento mentir.

    Uma candidata que tivesse comido a lista de discriminacao mediria "o prompt
    sem a lista", nao "o prompt mais a frase nova" -- e a tabela sairia igual,
    com numeros que ninguem saberia reinterpretar.
    """
    for nome, prompt in BRACOS.items():
        assert "restricao de vizinhanca por composicao familiar" in prompt, nome
        assert "Bloquear lead legitimo custa atendimento" in prompt, nome
        assert "Categorias: " in prompt, nome
        if nome != "atual":
            assert len(prompt) > len(SISTEMA_DA_ENTRADA), nome


def test_as_candidatas_nao_citam_o_texto_dos_casos() -> None:
    """A D3 do desenho, virada teste.

    Uma redacao que cita as palavras do caso -- "so de casal sem filho" --
    venceria a medicao sem significar nada: o corpus e ao mesmo tempo o alvo e o
    instrumento, e o 12/12 viraria tautologia.

    Quatro palavras seguidas e a fronteira, e ela e deliberadamente modesta:
    pega a citacao literal, que e o que a D3 descarta, e nao pega parafrase,
    que teste nenhum pegaria. As candidatas ilustram a **forma** do pedido
    ("prefiro um predio so de...") de proposito -- ensinar que enquadrar como
    preferencia nao descaracteriza a restricao e exatamente o que a candidata A
    faz, e isso exige mostrar o enquadramento. O que elas nao fazem e nomear o
    **conteudo** do caso.
    """
    do_corpus: set[tuple[str, ...]] = set()
    for texto in textos_do_corpus().values():
        do_corpus |= _quadrigramas(texto)

    for nome, prompt in BRACOS.items():
        if nome == "atual":
            continue
        repetidos = _quadrigramas(prompt) & do_corpus
        assert not repetidos, f"o braco {nome} cita o corpus: {sorted(repetidos)}"


def test_o_orcamento_da_sonda_e_o_autorizado() -> None:
    """160 chamadas e o orcamento de uma re-execucao, nao o desta card.

    A card mediu 3 bracos x 4 casos x 20 repeticoes = 240 chamadas; com a
    vencedora aplicada em `SISTEMA_DA_ENTRADA` e fora de `BRACOS` (Step 2b),
    uma nova rodada custa 2 bracos x 4 casos x 20 repeticoes. O numero mora em
    tres constantes que ninguem le juntas; subir `REPETICOES` para 50 e um
    caractere de diff e 240 chamadas a mais.
    """
    assert len(BRACOS) * len(CASOS) * REPETICOES == 160
