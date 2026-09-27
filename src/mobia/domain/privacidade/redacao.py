"""Redigir o dado sensivel que o lead informa sem ninguem pedir. TEC-380, RNF-20.

**Regra, e nao modelo** (D1). A RNF-20 manda redigir ANTES da persistencia, e a
mensagem e gravada no ciclo do webhook, onde a RN-01.2 proibe LLM. Um modelo
so poderia olhar depois de gravar -- e ai o dado ja estaria no banco. E uma
regra de LGPD nao pode depender de um provedor estar de pe, pelo mesmo
argumento de `pediu_optout`.

**O preco e o recall, declarado.** Termo fora da lista, parafrase ("tenho
acucar alto"), erro de digitacao e dado de terceiro na forma identitaria
("meu marido e evangelico") passam. Dado genetico ou biometrico nao entra:
"biometria" e a portaria do predio, e ninguem digita uma digital.

**Duas faixas, pela precisao** (D1). A inequivoca casa em qualquer posicao:
nomes de condicao de saude que nao aparecem em conversa de imovel com outro
sentido. A identitaria -- religiao, politica, raca, orientacao -- so casa na
primeira pessoa ("sou catolica"): "perto da Catolica" e um bairro, e redigir ali
apagaria justamente o pedido de imovel.

**So o trecho sai** (D2, decisao do Eduardo), com um marcador generico: um
marcador por categoria ("[dado sensivel: saude]") diria sozinho que a pessoa
tem uma condicao de saude. A excecao e a acessibilidade, que vira um marcador
proprio para o requisito de imovel sobreviver sem a condicao.
"""

import re
import unicodedata
from typing import Any, NamedTuple

# Com acento: aparecem no painel, para o corretor.
MARCADOR_DE_DADO_SENSIVEL = "[dado sensível removido]"
MARCADOR_DE_ACESSIBILIDADE = "[necessidade de acessibilidade]"

# Os padroes sao escritos sobre o texto DOBRADO (`_dobrar`): minusculo e sem
# acento. Cada alternativa e uma palavra ou locucao inteira -- `\b` nas duas
# pontas vem de `_compilar`.
_SAUDE = (
    r"diabetes",
    r"diabetic[oa]s?",
    r"hiv",
    r"aids",
    r"soropositiv[oa]s?",
    r"cancer",
    r"leucemia",
    r"metastases?",
    r"quimioterapia",
    r"radioterapia",
    r"hemodialise",
    r"dialise",
    r"autismo",
    r"autistas?",
    r"tdah",
    r"esquizofreni(?:a|c[oa]s?)",
    r"bipolaridade",
    r"transtorno bipolar",
    r"transtorno de ansiedade",
    r"crises? de ansiedade",
    r"sindrome do panico",
    r"sindrome de down",
    r"depressao",
    r"depressiv[oa]s?",
    r"epilepsia",
    r"epileptic[oa]s?",
    r"alzheimer",
    r"parkinson",
    r"avc",
    r"infarto",
    r"cardiopatas?",
    r"hipertensao",
    r"hipertens[oa]s?",
    r"asma",
    r"asmatic[oa]s?",
    r"cirurgias?",
    r"gravidas?",
    r"gravidez",
    r"gestantes?",
)

_ACESSIBILIDADE = (
    r"cadeirantes?",
    r"cadeiras? de rodas",
    r"mobilidade reduzida",
    r"paraplegic[oa]s?",
    r"tetraplegic[oa]s?",
    r"deficiencias? (?:fisicas?|visua(?:l|is)|auditivas?|intelectua(?:l|is)|motoras?)",
    r"deficientes? (?:fisic[oa]s?|visua(?:l|is)|auditiv[oa]s?|intelectua(?:l|is))",
    r"pcd",
    r"ceg[oa]s?",
    r"surd[oa]s?",
)

# Inequivocos fora da saude: nao aparecem em conversa de imovel com outro
# sentido, entao nao precisam da primeira pessoa.
_OUTROS_INEQUIVOCOS = (
    r"sindicalizad[oa]s?",
    r"filiad[oa]s? (?:ao|a um|ao meu) sindicato",
    r"homossexua(?:l|is)",
    r"bissexua(?:l|is)",
    r"lesbicas?",
    r"transexua(?:l|is)",
    r"homoafetiv[oa]s?",
    r"casal gay",
)

# Identitarios: so depois de "sou", "somos", "eu sou". O adverbio opcional
# cobre "sou muito catolica", "somos bem de esquerda".
_IDENTITARIOS = (
    # Conviccao religiosa.
    r"evangelic[oa]s?",
    r"catolic[oa]s?",
    r"espiritas?",
    r"umbandistas?",
    r"candomblecistas?",
    r"judeus?",
    r"judias?",
    r"muculman[oa]s?",
    r"ateus?",
    r"ateias?",
    r"protestantes?",
    r"adventistas?",
    r"testemunhas? de jeova",
    r"budistas?",
    r"crentes?",
    # Opiniao politica.
    r"petistas?",
    r"bolsonaristas?",
    r"lulistas?",
    r"de esquerda",
    r"de direita",
    r"comunistas?",
    r"socialistas?",
    r"anarquistas?",
    # Origem racial ou etnica.
    r"negr[oa]s?",
    r"pret[oa]s?",
    r"pard[oa]s?",
    r"branc[oa]s?",
    r"indigenas?",
    r"quilombolas?",
    # Vida sexual.
    r"gays?",
    r"trans",
    r"travestis?",
    r"assexua(?:l|is)",
)

_PRIMEIRA_PESSOA = r"\b(?:eu )?(?:sou|somos)(?: (?:muito|bem|um|uma))? "


def _compilar(alternativas: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(alternativas) + r")\b")


_INEQUIVOCOS = _compilar(_SAUDE + _OUTROS_INEQUIVOCOS)
_DE_ACESSIBILIDADE = _compilar(_ACESSIBILIDADE)
# O grupo `alvo` e so o termo: "sou catolica" vira "sou [dado sensivel
# removido]", e o "sou" fica -- o que sai e a conviccao, nao a frase.
_EM_PRIMEIRA_PESSOA = re.compile(_PRIMEIRA_PESSOA + r"(?P<alvo>" + "|".join(_IDENTITARIOS) + r")\b")


class Redacao(NamedTuple):
    texto: str
    trechos: int


def _dobrar(texto: str) -> str:
    """Minusculo e sem acento, com EXATAMENTE um caractere por caractere.

    E o que permite achar o trecho no dobrado e recorta-lo do original: os
    indices batem. A normalizacao de `pediu_optout` nao serve aqui porque apaga
    pontuacao e colapsa espacos. Espaco em branco de qualquer tipo vira espaco
    simples, para "cadeira\\nde rodas" casar como "cadeira de rodas".
    """
    dobrado = []
    for caractere in texto:
        if caractere.isspace():
            dobrado.append(" ")
            continue
        base = unicodedata.normalize("NFD", caractere)[0].lower()
        # `lower()` pode crescer ("İ" vira dois): fica o primeiro.
        dobrado.append(base[0] if base else caractere)
    return "".join(dobrado)


def redigir(texto: str) -> Redacao:
    """O texto com cada trecho sensivel trocado pelo marcador, e quantos foram.

    Trechos que se sobrepoem viram um so. O marcador nao casa com nenhum
    padrao, entao redigir de novo nao muda nada -- a reentrega e a
    retentativa passam pelo mesmo caminho.
    """
    dobrado = _dobrar(texto)
    trechos: list[tuple[int, int, str]] = []
    for achado in _INEQUIVOCOS.finditer(dobrado):
        trechos.append((achado.start(), achado.end(), MARCADOR_DE_DADO_SENSIVEL))
    for achado in _DE_ACESSIBILIDADE.finditer(dobrado):
        trechos.append((achado.start(), achado.end(), MARCADOR_DE_ACESSIBILIDADE))
    for achado in _EM_PRIMEIRA_PESSOA.finditer(dobrado):
        trechos.append((achado.start("alvo"), achado.end("alvo"), MARCADOR_DE_DADO_SENSIVEL))
    if not trechos:
        return Redacao(texto, 0)

    trechos.sort()
    unidos: list[tuple[int, int, str]] = []
    for inicio, fim, marcador in trechos:
        if unidos and inicio < unidos[-1][1]:
            anterior = unidos[-1]
            # Na sobreposicao vence o generico: e o que esconde mais.
            vencedor = (
                MARCADOR_DE_DADO_SENSIVEL
                if MARCADOR_DE_DADO_SENSIVEL
                in (
                    anterior[2],
                    marcador,
                )
                else marcador
            )
            unidos[-1] = (anterior[0], max(anterior[1], fim), vencedor)
        else:
            unidos.append((inicio, fim, marcador))

    partes = []
    cursor = 0
    for inicio, fim, marcador in unidos:
        partes.append(texto[cursor:inicio])
        partes.append(marcador)
        cursor = fim
    partes.append(texto[cursor:])
    return Redacao("".join(partes), len(unidos))


def redigir_payload(valor: Any) -> tuple[Any, int]:
    """O envelope com toda string redigida, e quantos trechos no total.

    Recursivo, e sobre TODA string, e nao so sobre `text.body`: o envelope da
    Meta leva o texto tambem na legenda (`image.caption`, `document.caption`) e
    no nome do arquivo, e o frame do widget o leva em `texto`. Uma lista de
    caminhos esqueceria o proximo campo que alguem acrescentar. Chaves nao sao
    redigidas -- sao do protocolo, nunca do lead. Ids e wamids nao casam com
    padrao nenhum.
    """
    if isinstance(valor, str):
        redacao = redigir(valor)
        return redacao.texto, redacao.trechos
    if isinstance(valor, dict):
        total = 0
        novo_dict: dict[Any, Any] = {}
        for chave, item in valor.items():
            novo_dict[chave], trechos = redigir_payload(item)
            total += trechos
        return novo_dict, total
    if isinstance(valor, list):
        total = 0
        nova_lista = []
        for item in valor:
            novo_item, trechos = redigir_payload(item)
            nova_lista.append(novo_item)
            total += trechos
        return nova_lista, total
    return valor, 0
