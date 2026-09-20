"""A fronteira do acento, no sentido que a TEC-267 fixou.

Substitui as cinco assercoes `.isascii()` que guardavam a politica anterior.

**Esta guarda erra de menos, nunca de mais, e e isso que a torna aceitavel.**
A versao obvia -- "todo literal ao lead tem ao menos um caractere acentuado"
-- e FALSA: `m2`, `Destaque:` e `De {} por {}` nao tem vogal que receba
acento, e excetua-las viraria uma lista a mao que reprova texto certo. Esta
aqui tem a assimetria oposta: uma palavra faltando na lista so deixa de pegar
um caso, nunca reprova um caso correto.

**O que a lista cobre, e o que ela nao cobre, esta com a lista.** Desde a
TEC-286 ela vive em `tests/unit/literais_ao_lead.py`, porque a guarda de
promessa (`test_promessa_ao_lead.py`) le a mesma lista -- e o paragrafo que
explicava por que os rotulos da ficha de imovel ficam de fora descreve a
LISTA, nao esta guarda, entao foi junto.
"""

import re

import pytest

from tests.unit.literais_ao_lead import LITERAIS_AO_LEAD

# As formas sem acento que o dominio usa de fato. Nao e o portugues inteiro:
# e a lista das palavras que apareciam nos literais desta card, mais as que
# um texto de imobiliaria escreve toda hora.
#
# A comparacao usa fronteira de palavra (`\b`), nao substring nem espaco nas
# pontas. Espaco nas pontas foi a primeira tentativa e tinha dois buracos
# simetricos: " mes " (com espaco dos dois lados) nao casa em "R$ 2.615/mes"
# -- a barra cola no "mes", sem espaco a esquerda, e e assim que a palavra
# aparece de verdade em `apresentacao.py` --, e " ja " nao casa em "Ja
# perguntei..." quando "ja" e a PRIMEIRA palavra da frase, sem espaco antes.
# `\b` resolve os dois: barra e inicio de string sao fronteira de palavra
# tanto quanto espaco, e "veja se"/"mesmo"/"mesa" continuam fora porque ali
# nao ha fronteira nenhuma entre "ja"/"mes" e as letras vizinhas.
#
# De proposito, NAO ha forma de uma ou duas letras aqui (nao ha "as" para
# "as", nem "e" para "e"/"os"). "as" colidiria com "mas" e com o "as" de
# qualquer plural feminino; "e" colidiria com a conjuncao "e", com "gas",
# com "area" -- e ambas reprovariam texto certo o tempo todo, exatamente o
# erro que esta guarda existe para nao cometer.
#
# O teste antes de acrescentar qualquer forma nova: ela so entra aqui se a
# grafia SEM acento nao for, por si so, palavra portuguesa valida. "voce",
# "imovel", "regiao" passam nesse teste -- nao existem sem o acento. Duas
# formas ficaram de fora por reprovarem nele: "inclui" e "ultima" existem
# sem acento nenhum -- sao a terceira pessoa do presente de "incluir" ("a
# busca inclui bairros vizinhos") e de "ultimar" ("o corretor ultima o
# contrato antes de enviar") --, e uma guarda que as contivesse reprovaria
# um literal certo como "Isso ja inclui o condominio." ou "O corretor
# ultima os detalhes", que e o unico erro que esta guarda nao pode
# cometer. A perda destas duas formas e alinhada ao principio: a guarda
# erra por falta, nunca por sobra.
FORMAS_SEM_ACENTO = (
    "voce",
    "nao",
    "imovel",
    "imoveis",
    "regiao",
    "preco",
    "condominio",
    "criterio",
    "sabado",
    "horario",
    "tecnico",
    "informacao",
    "opcoes",
    "interrogatorio",
    "tambem",
    "alem",
    "ja",
    "e so",
    "mes",
    "area",
    "imobiliaria",
    "entao",
)


@pytest.mark.parametrize("texto", LITERAIS_AO_LEAD)
def test_nenhum_literal_ao_lead_tem_forma_sem_acento(texto: str) -> None:
    """A TEC-267 fixou que o texto que o lead le e portugues acentuado."""
    minusculo = texto.lower()
    achadas = [
        forma for forma in FORMAS_SEM_ACENTO if re.search(rf"\b{re.escape(forma)}\b", minusculo)
    ]
    assert not achadas, f"{achadas} em {texto!r}"
