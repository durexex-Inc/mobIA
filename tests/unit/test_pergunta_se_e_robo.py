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

**Os negativos deste arquivo sao quatro classes de defeito ja medidas, uma por
rodada de review**, e cada uma tem o seu teste: prefixo de palavra maior
(round 1), "e" de conjuncao com sujeito errado (round 2), sujeito anaforico
"isso" (round 3) e pergunta de ROTEAMENTO com o sujeito certo (round 4). Quem
mexer na tabela reabre alguma delas se apagar o teste correspondente.
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
        # Fix round 4 (review): a armadilha da regra nova. "de verdade" tem a
        # MESMA preposicao de "de vendas", e e provavelmente a frasagem mais
        # natural deste eixo -- qualquer guarda que barre a preposicao em
        # bloco derruba estas duas. Ver
        # `test_pergunta_de_roteamento_nao_dispara`.
        "estou falando com uma pessoa de verdade?",
        "to falando com uma pessoa de verdade?",
    ],
)
def test_a_pergunta_dispara(texto: str) -> None:
    """Tres das quatro frasagens que a TEC-139 sondou, mais o que cada round fixou.

    Nenhuma delas e fala real observada -- ver a docstring do modulo. Elas
    fixam a faixa, nao a validam.

    **A quarta frasagem da TEC-139, "isso e automatico ou tem alguem ai?", e
    "isso aqui é um bot?" (variante que dependia da mesma familia) sairam
    daqui na fix round 3 (review).** A familia de sujeito "isso"/"isso ai"/
    "isso aqui" saiu inteira da tabela: "isso" e anaforico, e o antecedente
    pode ser qualquer coisa que a conversa tenha citado -- um robo aspirador
    de piscina, um contrato --, nunca so o interlocutor. Ver
    `test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada`, que fixa
    essa perda como decisao, e o comentario de `_TERMOS_DE_SEGUNDA_PESSOA` em
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
    """Fix round 1 (review), Critical: o `\\b` de fechamento do padrao.

    Na epoca desta rodada havia um padrao so, e ele ancorava apenas o INICIO
    de cada alternativa. "e maquina ou" casava escondido em "e maquina outra
    vez", "e automatico ou" em "e automatico outro portao", "e humano ou" em
    "e humano outra pergunta", e "e um bot" em "e um botao" -- e todas as
    cinco falas acima sao fala corrente de quem pergunta sobre portao/imovel,
    nao duvida sobre falar com maquina.

    Hoje o `\\b` de fechamento vive em `_PADRAO_DE_SEGUNDA_PESSOA`, e o
    comentario dele explica por que `context/gatilhos.py`, o molde, dispensa
    esse fechamento e por que aqui nao dava para dispensar.
    `_PADRAO_DE_PRIMEIRA_PESSOA` fecha mais forte ainda, em `$` -- ver
    `test_pergunta_de_roteamento_nao_dispara`.
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
    do conserto. O comentario de `_TERMOS_DE_SEGUNDA_PESSOA` explica por que
    o sujeito entra por extenso em cada termo.
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
    e o comentario de `_TERMOS_DE_SEGUNDA_PESSOA`), e nao ha como distinguir
    esta frase de "isso e automatico ou tem alguem que assina esse contrato?"
    sem ver o discurso anterior.

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


@pytest.mark.parametrize(
    "texto",
    [
        "estou falando com uma pessoa da area de locacao ou de vendas?",
        "estou falando com uma pessoa da locacao?",
        "to falando com uma pessoa do financeiro?",
        "estou falando com uma pessoa de vendas ou de locacao?",
        "estou falando com uma pessoa do juridico sobre o contrato?",
        "to falando com uma pessoa da imobiliaria?",
        "estou falando com um humano do suporte?",
    ],
)
def test_pergunta_de_roteamento_nao_dispara(texto: str) -> None:
    """Fix round 4 (review), Critical: sujeito certo, pergunta errada.

    As sete falas tem o sujeito inequivoco que as tres rodadas anteriores
    perseguiram -- primeira pessoa implicita na conjugacao, sempre o proprio
    lead -- e mesmo assim nenhuma pergunta se quem responde e uma maquina.
    Todas perguntam por ROTEAMENTO: se o lead caiu no setor certo. "setor de
    locacao", "financeiro", "juridico", "vendas" e "suporte" sao vocabulario
    corrente de atendimento imobiliario, entao a classe e frequente, e cada
    falso positivo aqui staplea a oferta de corretor numa fala que nao
    perguntou nada.

    O discriminante nao esta no sujeito nem no termo: esta no que vem DEPOIS
    do sintagma, dentro da mesma frase. "uma pessoa" NU pergunta pela
    natureza do interlocutor; "uma pessoa da locacao" pergunta por qual
    interlocutor. `_PADRAO_DE_PRIMEIRA_PESSOA` fecha em `$` com uma allowlist
    de reforcos de identidade -- ver o comentario dele, e ver
    `test_a_pergunta_dispara`, que trava as duas frasagens com "de verdade"
    que uma blocklist de preposicao derrubaria junto com estas sete.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        # Modificador por ADJETIVO -- nenhuma blocklist de preposicao pegaria.
        "estou falando com uma pessoa responsavel pela locacao?",
        "to falando com uma pessoa autorizada a negociar o valor?",
        "estou falando com uma pessoa especializada em investimento?",
        "to falando com uma pessoa credenciada pelo CRECI?",
        # Modificador por oracao RELATIVA.
        "estou falando com uma pessoa que cuida da locacao?",
        "to falando com uma pessoa que entende de financiamento?",
        # Modificador por preposicao que nao e "de"/"da"/"do".
        "estou falando com uma pessoa no escritorio de Moema?",
        "estou falando com uma pessoa com procuracao do proprietario?",
        # Sintagma seguido de nome proprio ou de papel.
        "estou falando com uma pessoa chamada Marina?",
        "to falando com uma pessoa corretora ou com a secretaria?",
        # Relato de atendimento paralelo -- o lead nao pergunta nada.
        "ja estou falando com uma pessoa da sua equipe sobre esse apto",
        "olha, estou falando com uma pessoa que me indicou voces",
        # Reforco de identidade seguido de setor: o reforco nao pode abrir a
        # porta que o resto da regra fecha.
        "to falando com uma pessoa viva la do financeiro?",
        "estou falando com uma pessoa real de vendas?",
    ],
)
def test_modificador_do_sintagma_nao_dispara(texto: str) -> None:
    """Fix round 4 (review), cacada propria: a classe e maior que a preposicao.

    O achado da review trouxe sete falas, todas com "da"/"do"/"de" + setor.
    Estas catorze sao as que eu inventei depois, contra a tabela ja
    consertada, e elas mostram por que a regra teve de ser uma ALLOWLIST
    ancorada em `$` e nao uma blocklist: adjetivo ("responsavel pela
    locacao"), oracao relativa ("que cuida da locacao"), outra preposicao
    ("no escritorio de Moema") e nome proprio ("chamada Marina") restringem o
    sintagma do mesmo jeito, e nenhum deles comeca por preposicao de setor.
    Com allowlist, palavra desconhecida depois do sintagma derruba o
    casamento por omissao, sem precisar ser prevista.

    As duas ultimas fecham a porta do proprio conserto: um reforco de
    identidade ("viva", "real") nao pode servir de ponte para o complemento
    de setor que vem depois dele.
    """
    assert perguntou_se_e_robo(texto) is False


@pytest.mark.parametrize(
    "texto",
    [
        # Reforco de identidade: aperta a mesma pergunta, nao restringe.
        "estou falando com uma pessoa mesmo?",
        "to falando com uma pessoa viva?",
        "estou falando com um humano de carne e osso?",
        "to falando com uma pessoa ai?",
        # "ou" + alternativa explicita: a disjuncao e a propria pergunta de
        # identidade, porque o primeiro membro dela ja e o sintagma nu.
        "Oi! To falando com uma pessoa ou com um robo?",
        "estou falando com uma pessoa ou e tudo automatico?",
    ],
)
def test_o_reforco_de_identidade_dispara(texto: str) -> None:
    """Fix round 4 (review): o outro lado da allowlist de `_REFORCOS_DE_IDENTIDADE`.

    Uma regra que so exigisse o sintagma no fim absoluto da frase mataria
    estas seis, que sao as frasagens mais naturais deste eixo depois das duas
    da sonda da TEC-139. Elas existem para que uma proxima rodada que aperte
    a faixa perceba o que esta pagando por isso.
    """
    assert perguntou_se_e_robo(texto) is True


def test_a_pergunta_seguida_de_outra_frase_dispara() -> None:
    """Fix round 4 (review): o corte por frase, e nao pela mensagem inteira.

    `_normalizar` troca pontuacao por espaco, entao um `$` sobre o recado
    inteiro cairia so no fim do ultimo recado -- e "to falando com uma
    pessoa? preciso de ajuda" deixaria de disparar, apesar de a pergunta
    estar inteira e nua na primeira frase. `_FIM_DE_FRASE` corta antes de
    normalizar, e a regra de primeira pessoa corre frase a frase.

    O corte nao inclui `\\n` de proposito: quebra de linha no meio da frase e
    comum no WhatsApp, e cortar ali parteria o proprio termo. O custo disso
    esta na segunda assercao -- sem pontuacao nenhuma, a pergunta com
    continuacao nao dispara, e essa e a lacuna declarada da round 4.
    """
    assert perguntou_se_e_robo("to falando com uma pessoa? preciso de ajuda urgente") is True
    assert perguntou_se_e_robo("to falando com uma pessoa preciso de ajuda urgente") is False


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
