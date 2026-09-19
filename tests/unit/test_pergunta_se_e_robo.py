"""A faixa do detector da pergunta "voce e um robo?" (TEC-272).

**A afirmacao forte deste arquivo e a NEGATIVA, e a razao esta na D3 do
desenho.** Nao existe fala real deste eixo em `evals/corpus/` -- zero
ocorrencias nos cinco arquivos --, entao todo termo do detector e invencao, e
medi-lo contra as frasagens que ele foi escrito para pegar seria medi-lo
contra o proprio vocabulario. O que da para provar e que ele nao dispara em
nenhum dos mil e tantos turnos de fala real que o corpus tem, e e isso que
`test_nao_dispara_em_nenhum_turno_do_corpus` faz.

A assimetria que justifica a faixa estrita e a de `gatilhos.py`, nao a do
opt-out: falso negativo devolve o comportamento de hoje, falso positivo gruda
uma oferta de corretor numa fala que nao pediu -- que e literalmente o segundo
criterio de aceite desta card.
"""

from pathlib import Path

import pytest

from mobia.domain.agente.identificacao import perguntou_se_e_robo
from mobia.evals.corpus import carregar

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


@pytest.mark.parametrize(
    "texto",
    [
        "vc e um robo?",
        "você é um robô?",
        "to falando com uma pessoa?",
        "voce e humano ou maquina?",
    ],
)
def test_a_pergunta_dispara(texto: str) -> None:
    """Tres das quatro frasagens que a TEC-139 sondou, mais uma variante acentuada.

    Nenhuma delas e fala real observada -- ver a docstring do modulo. Elas
    fixam a faixa, nao a validam.

    **A quarta frasagem da TEC-139, "isso e automatico ou tem alguem ai?", e
    "isso aqui é um bot?" (variante que dependia da mesma familia) saem daqui
    na fix round 3 (review).** A familia de sujeito "isso"/"isso ai"/"isso
    aqui" saiu inteira de `_TERMOS_DA_PERGUNTA`: "isso" e anaforico, e o
    antecedente pode ser qualquer coisa que a conversa tenha citado -- um
    robo aspirador de piscina, um contrato --, nunca so o interlocutor. Ver
    `test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada`, que fixa
    essa perda como decisao, e o comentario de `_TERMOS_DA_PERGUNTA` em
    `identificacao.py`, que traz o numero que a torna barata.
    """
    assert perguntou_se_e_robo(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "quero um apartamento automatico de 2 quartos",
        "o portao e automatico?",
        "tem maquina de lavar no apartamento?",
        "o predio tem elevador automatico?",
        "somos em cinco pessoas",
        "preciso falar com uma pessoa sobre o contrato",
    ],
)
def test_fala_vizinha_nao_dispara(texto: str) -> None:
    """O objeto sozinho nunca basta.

    "automatico" qualificando portao ou elevador, "maquina" de lavar e
    "pessoa" como sujeito sao fala corrente de quem procura imovel. Um
    detector que casasse o substantivo solto grudaria oferta de corretor em
    cada um deles.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        # Fix round 1 (review), Critical: sem `\b` de fechamento, o termo
        # casava como PREFIXO da palavra seguinte. Estas tres provam o buraco
        # dos termos terminados em "ou".
        "e maquina outra vez que quebrou, poderiam consertar antes da entrega?",
        "e automatico outro portao que tem la no fundo?",
        "e humano outra pergunta, quantos quartos tem mesmo?",
        # Mesmo buraco, termo "e um bot": imovel com portao automatico fala
        # em "botao" o tempo todo, e "bot" e prefixo de "botao".
        "quero saber se e um botao ou controle remoto pro portao",
        "e um botao vermelho que abre o portao?",
    ],
)
def test_prefixo_de_palavra_maior_nao_dispara(texto: str) -> None:
    """Fix round 1 (review), Critical: o `\\b` de fechamento em `_PADRAO_DA_PERGUNTA`.

    Antes desta rodada, `_PADRAO_DA_PERGUNTA` so ancorava o INICIO de cada
    alternativa. "e maquina ou" casava escondido em "e maquina outra vez", "e
    automatico ou" em "e automatico outro portao", "e humano ou" em "e humano
    outra pergunta", e "e um bot" em "e um botao" -- e todas as cinco falas
    acima sao fala corrente de quem pergunta sobre portao/imovel, nao duvida
    sobre falar com maquina. O comentario de `_PADRAO_DA_PERGUNTA` explica por
    que `context/gatilhos.py`, o molde, dispensa esse fechamento e por que
    aqui nao dava para dispensar.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        "oi, tem alguem ai? preciso de uma info rapida",
        "tem alguem ai disponivel pra me passar as opcoes de apartamento no bairro?",
    ],
)
def test_pedido_de_presenca_nu_nao_dispara(texto: str) -> None:
    """Fix round 1 (review), Important: "tem alguem ai" saiu da tabela.

    Sem exigir "automatico"/"robo"/"humano"/"maquina" por perto, "tem alguem
    ai" casava pedido corrente de atencao -- a mesma licao que o comentario
    da tabela ja registra para "automatico"/"maquina"/"pessoa" soltos, so que
    nao tinha sido aplicada a este termo (nem a "tem alguem ai ou" e "tem
    gente ai", que saem pelo mesmo motivo). Na epoca desta rodada (fix round
    1), a frase canonica da TEC-139 que motivou o termo, "isso e automatico
    ou tem alguem ai?", continuava disparando sem ele, por "e automatico ou".

    **Nota da fix round 3:** essa frase canonica saiu de `test_a_pergunta_dispara`
    depois, por um motivo diferente e mais largo -- a familia de sujeito
    "isso" inteira e anaforica e saiu da tabela. Ver
    `test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada`. Esta
    assercao aqui continua valendo (nunca dependeu de "isso"), so a
    referencia cruzada acima ficou historica.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        # "e uma maquina" via CONJUNCAO, nao verbo: o sujeito e o
        # apartamento/a area de servico, nunca o interlocutor.
        "o apartamento tem ar condicionado e uma maquina de lavar",
        "a area de servico tem tanque e uma maquina de lavar nova",
        # Mesma classe: sujeito e o condominio, nao quem fala.
        "o condominio tem piscina e robo aspirador de folhas",
        # "e automatico ou" sem sujeito interlocutor: sujeito e o
        # portao/elevador, fala corrente de quem pergunta sobre o imovel.
        "o portao e automatico ou manual, esse do prospecto?",
        "o elevador e automatico ou precisa de chave?",
        # "tudo automatico" sem "isso" antes: sujeito e o condominio/o
        # showroom.
        "no condominio e tudo automatico, ate a garagem abre sozinha",
        "showroom mostra tudo automatico: portao, luz, cortina",
        # "e gente ou" com sujeito que e o bairro, nao o interlocutor.
        "nesse bairro e gente ou mais empresas que moram",
        # "humano ou maquina" como assunto de atendimento, sem "voce e"/"isso
        # e" antes -- o lead fala da PREFERENCIA dele, nao pergunta com quem
        # fala.
        "prefiro atendimento humano ou maquina, tanto faz pra mim resolver isso",
    ],
)
def test_conjuncao_ou_sujeito_errado_nao_dispara(texto: str) -> None:
    """Fix round 2 (review): a tabela passou a exigir o SUJEITO por extenso.

    `_normalizar` tira acento, entao "e" (conjuncao) e "e" (verbo "e") viram
    o mesmo token depois da normalizacao. Antes desta rodada, todo termo da
    forma "e <ancora>" -- sem exigir "voce"/"vc"/"isso" antes -- casava
    qualquer frase que usasse "e" como CONJUNCAO perto de robo/maquina/
    automatico/gente, com sujeito nenhum a ver com o interlocutor: o
    apartamento, o condominio, o portao, o bairro. As nove falas acima sao
    fala real de mercado imobiliario com essa forma, e todas disparavam antes
    do conserto. O comentario da tabela (`_TERMOS_DA_PERGUNTA`) explica por
    que o sujeito agora entra por extenso em cada termo.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        # "isso" aponta para um robo aspirador de PISCINA -- um produto do
        # imovel, nao o interlocutor.
        "isso e um robo que limpa a piscina sozinho, e super pratico",
        "isso ai e um robo aspirador que veio com o apartamento",
        # "isso" aponta para a PORTARIA/o PREDIO.
        "a portaria funciona 24 horas? isso e automatico ou tem alguem la sempre",
        "esse predio, isso aqui e tudo automatico ou tem porteiro presencial?",
        # "isso" aponta para o CONTRATO -- estruturalmente identica a frase
        # canonica da TEC-139 ("isso e automatico ou tem alguem ai?"), que so
        # se distingue pelo que "isso" retoma no discurso anterior.
        "isso e automatico ou tem alguem que assina manualmente esse contrato?",
    ],
)
def test_isso_anaforico_nao_dispara(texto: str) -> None:
    """Fix round 3 (review): a familia de sujeito "isso" saiu inteira da tabela.

    "isso" e anaforico -- o antecedente pode ser qualquer coisa que a
    conversa tenha acabado de citar (um robo aspirador, uma portaria, um
    contrato), nunca so o interlocutor. O comentario do modulo afirmava "o
    sujeito e sempre O INTERLOCUTOR" e o codigo so exigia o TOKEN "isso", nao
    o referente -- a mesma classe de defeito da fix round 1 (comentario
    prometendo protecao que o codigo nao dava), so que na camada semantica em
    vez da lexica. Nao ha aperto de palavra-chave que resolva isso: a ultima
    fala acima e estruturalmente identica a frase canonica da TEC-139 que
    caiu de `test_a_pergunta_dispara`, e as duas so se distinguem pelo
    discurso anterior, que este detector nunca ve.
    """
    assert perguntou_se_e_robo(texto) is False


def test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada() -> None:
    """Fix round 3 (review), fixada como LACUNA e nao como conserto.

    Molde: `test_o_interlocutor_de_terceiro_dispara_e_e_lacuna_declarada`
    (`tests/unit/test_deteccao_de_humano.py`).

    "isso e automatico ou tem alguem ai?" e a terceira das quatro frasagens
    que a sonda da TEC-139 mediu
    (`evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`), e a
    unica que usa "isso" como sujeito. Ela deixou de disparar de proposito: a
    familia de sujeito "isso" e anaforica (ver `test_isso_anaforico_nao_dispara`
    e o comentario de `_TERMOS_DA_PERGUNTA`), e nao ha como distinguir esta
    frase de "isso e automatico ou tem alguem que assina esse contrato?" sem
    ver o discurso anterior.

    A perda e barata porque tem numero: a propria sonda da TEC-139 mediu essa
    frasagem (caso 3) com "confirma: SIM, oferece corretor: SIM" -- o modelo
    ja resolve essa pergunta sozinho, sem ajuda deste detector. Os dois casos
    que a sonda mediu FALHANDO -- "vc e um robo?" e "to falando com uma
    pessoa?" (casos 1 e 2), os dois com sujeito inequivoco -- sao a razao
    desta card existir, e continuam cobertos por `test_a_pergunta_dispara`.
    Esta assercao existe para o dia em que alguem "consertar" isso descobrir
    que a decisao foi deliberada.
    """
    assert perguntou_se_e_robo("isso e automatico ou tem alguem ai?") is False


def test_texto_vazio_nao_levanta() -> None:
    """Mesma garantia de `gatilhos_de`: texto sem letra nenhuma devolve False."""
    assert perguntou_se_e_robo("") is False
    assert perguntou_se_e_robo("!!! 123 ???") is False


def test_nao_dispara_em_nenhum_turno_do_corpus() -> None:
    """A unica afirmacao forte disponivel sobre a faixa (D3 do desenho).

    Mil e tantos turnos de fala de lead, e nenhum deles e esta pergunta --
    conferido por grep antes de escrever o detector. Se um deles passar a
    disparar, ou o corpus ganhou um caso deste eixo (e ai o teste conta uma
    novidade boa) ou a faixa ficou larga demais (e ai ele pegou o defeito que
    o corpus inventado nunca pegaria).

    Sem chamada paga: `carregar` so le YAML.
    """
    disparam = [
        turno.lead
        for conversa in carregar(CORPUS)
        for turno in conversa.turnos
        if perguntou_se_e_robo(turno.lead)
    ]

    assert disparam == []
