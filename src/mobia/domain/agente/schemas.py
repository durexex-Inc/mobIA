import re
import unicodedata
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import StrEnum


class Intencao(StrEnum):
    """As sete intencoes da RN-03.1.

    O schema estrito da chamada ao modelo e derivado deste enum: acrescentar um
    membro aqui muda o conjunto de valores que o modelo pode devolver.
    """

    COMPRA = "COMPRA"
    ALUGUEL = "ALUGUEL"
    INVESTIMENTO = "INVESTIMENTO"
    VENDER_IMOVEL = "VENDER_IMOVEL"
    SUPORTE_CONTRATO = "SUPORTE_CONTRATO"
    INDEFINIDA = "INDEFINIDA"
    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"


class TipoImovel(StrEnum):
    """Vocabulario fechado porque a coluna e filtrada em SQL pela TEC-158.

    `lead_qualification.tipo_imovel` e `String(32)`: texto livre ali envenena
    o filtro estruturado. Acrescentar membro aqui muda o conjunto de valores
    que o modelo pode devolver, como no `Intencao`.
    """

    APARTAMENTO = "APARTAMENTO"
    CASA = "CASA"
    TERRENO = "TERRENO"
    COMERCIAL = "COMERCIAL"
    RURAL = "RURAL"


class Urgencia(StrEnum):
    """Faixas, nao datas. O lead diz "em janeiro"; o que importa e a pressa."""

    IMEDIATA = "IMEDIATA"
    ATE_3_MESES = "ATE_3_MESES"
    ATE_6_MESES = "ATE_6_MESES"
    SEM_PRESSA = "SEM_PRESSA"


class FormaPagamento(StrEnum):
    A_VISTA = "A_VISTA"
    FINANCIAMENTO = "FINANCIAMENTO"
    CONSORCIO = "CONSORCIO"
    FGTS = "FGTS"
    INDEFINIDA = "INDEFINIDA"


# Limiar da RN-03.2. `Decimal` e nao `float` porque a coluna e `numeric(3,2)` e
# a comparacao e de igualdade na borda: `0.6` em binario nao e 0,6, e "confianca
# exatamente 0,6 nao desambigua" e criterio de aceite.
#
# Fechado por cima: `< LIMIAR` desambigua, `>= LIMIAR` nao.
#
# **O numero veio do SRS sem calibragem, e a TEC-235 o mediu. Ele fica em 0,6,
# e agora por medicao e nao por omissao.** Confianca continua sendo
# autoavaliacao do modelo, nao probabilidade calibrada -- o que mudou e que
# existe evidencia sobre o efeito do corte.
#
# Duas coisas o gate mede a cada execucao: quantos acertos o rebaixamento
# transforma em INDEFINIDA (o custo) e quantos erros ele transforma em acerto
# (o beneficio).
#
#   27/08/2026, duas execucoes, opus-5, corpus de 136 turnos
#     custo:     4 e 6 acertos rebaixados       beneficio: 0 e 0
#     3 pontos separavam a acuracia crua da efetiva
#
#   30/08/2026, quatro execucoes, sonnet-5, corpus de 146 turnos
#     custo:     0 em todas as quatro           beneficio: 0 em todas
#     acuracia efetiva == acuracia crua, nas quatro
#
# O custo que motivou a TEC-235 **desapareceu sem que ninguem mexesse no
# limiar**: entre as duas datas trocou o modelo (opus-5 -> sonnet-5) e o prompt
# cresceu (TEC-240, TEC-250), e a distribuicao de confianca subiu junto. Os
# turnos de compra com transacao implicita -- "quanto ta pedindo?", "da pra
# negociar o valor?" -- que voltavam entre 0,50 e 0,58 pararam de voltar.
#
# Baixar o limiar hoje compraria um beneficio medido de **zero** e assumiria
# risco nao medido, que e o oposto do que a card pedia.
#
# **O beneficio nunca foi medido, e isso e fato sobre o corpus.** Em seis
# execucoes o rebaixamento nao salvou um unico erro -- mas o corpus tambem nao
# tem turnos de ambiguidade genuina, daqueles em que perguntar e a resposta
# certa. Isso e licenca para manter o limiar sem medo, e nao para elimina-lo:
# quem quiser mexer nele precisa primeiro anotar turnos que exercitem o outro
# lado da conta.
#
# Nao ha segundo limiar. O `0,8` que comentarios antigos citavam ao lado deste
# nunca governou decisao nenhuma -- a TEC-235 varreu e tirou as mencoes.
LIMIAR_DE_DESAMBIGUACAO = Decimal("0.6")


# Prefixos de referencia: o jeito de o lead localizar sem nomear. "perto da
# usp" nao e uma regiao, e uma frase com preposicao, e `_comparavel` faz so
# `strip` e `casefold` -- qualquer diferenca de forma contava erro cheio.
#
# `zona` NAO esta aqui, de proposito: `zona leste`, `zona sul` e `zona oeste`
# sao o nome, nao ruido, e tres anotacoes do corpus dependem disso.
#
# A TEC-246 fechou a assimetria: `na regiao` tinha `da`/`do` e ignorava
# `de`/`das`/`dos`, e `proximo`/`perto` tinham o singular e nao o plural. O
# corpus so exercitava `na regiao da/do`, entao o furo era latente -- e
# latente e o pior estado, porque a fala do lead nao pede licenca. O espaco
# final de cada entrada e o que mantem
# `test_nenhum_prefixo_de_referencia_e_prefixo_de_outro` verde: sem ele,
# `na regiao da ` seria prefixo de `na regiao das `.
_PREFIXOS_DE_REFERENCIA = (
    "na regiao da ",
    "na regiao do ",
    "na regiao de ",
    "na regiao das ",
    "na regiao dos ",
    "regiao das ",
    "regiao dos ",
    "regiao da ",
    "regiao do ",
    "regiao de ",
    "proximo da ",
    "proximo do ",
    "proximo de ",
    "proximo das ",
    "proximo dos ",
    "proximo ao ",
    "proximo a ",
    "perto da ",
    "perto do ",
    "perto de ",
    "perto das ",
    "perto dos ",
    "estacao ",
    # Logradouro, mesma classe de conteiner que `estacao`: a TEC-248 mediu o
    # modelo devolvendo "avenida paulista" onde o corpus anota "paulista".
    # So `avenida ` foi observada; `av. ` e `av ` entram por simetria, que e a
    # licao que a TEC-246 tirou do proprio caro: lista de prefixo assimetrica e
    # bug latente que so aparece quando um lead escreve a forma que faltava.
    "avenida ",
    "av. ",
    "av ",
)


_PARENTESES = re.compile(r"\([^)]*\)")


def _sem_acento(texto: str) -> str:
    """Dobra acento, porque o modelo nao e consistente com ele.

    A TEC-248 mediu os dois comportamentos no mesmo corpus e na mesma
    execucao: o modelo devolveu `saude` como "saude" com acento e
    `aclimacao` como "aclimacao" com acento, mas devolveu `butanta` e
    `tatuape` **sem** acento -- e essas duas casaram justamente por isso.
    Uma regua que dependa de adivinhar qual dos dois vem depende de sorte.

    NFD separa o diacritico do caractere base e `combining` identifica o que
    sobra para descartar. Pega cedilha junto: "aclimacao" com til e cedilha
    decompoe nos dois, e os dois somem.
    """
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if not unicodedata.combining(caractere)
    )


def normalizar_regiao(texto: str) -> str:
    """A forma canonica de `regiao`, na gravacao e na medicao.

    Existe uma so, com dois consumidores -- `extrair` e o `_comparavel` do eval
    --, porque duas regras de forma divergem e a divergencia so aparece na
    borda. Mesmo motivo de `faixa_de_catastrofe` ter sido deletada e de
    `campos_a_gravar` ter sido extraida.

    Normalizar perde informacao de proposito: "perto da usp" e "usp" viram a
    mesma coisa, e o lead que disse "perto da usp" queria proximidade, nao o
    campus. A troca e a favor do filtro estruturado da TEC-158, que compara
    `regiao` por igualdade em SQL -- "usp" e filtravel, "perto da usp" nao. O
    texto original da fala continua no historico de mensagens, cifrado, que e
    onde ele pertence.
    """
    limpo = " ".join(texto.split()).casefold()
    # Acento sai ANTES dos prefixos, e a ordem nao e detalhe: o modelo devolveu
    # "vila madalena (perto da estacao)" com acento em `estacao`, e um prefixo
    # escrito sem acento nunca casaria com ele. Dobrar depois deixaria o
    # prefixo dentro do valor.
    limpo = _sem_acento(limpo)
    # Qualificador entre parenteses e ruido de referencia como os prefixos, so
    # que no fim em vez de no comeco: "sao roque (sp)" e "sao roque".
    limpo = _PARENTESES.sub(" ", limpo)
    # O modelo devolve o lugar, nao a string do lead, e anexa o contexto mais
    # largo depois de virgula: "vila madalena, sao paulo". O que filtra e o
    # primeiro pedaco.
    limpo = limpo.split(",")[0]
    limpo = " ".join(limpo.split())
    # Repete enquanto casar: "perto da estacao vila madalena" perde `perto da`
    # e so entao `estacao`. Um passe so deixaria metade do ruido -- a fala de
    # `aluguel-06` e exatamente esse caso --, e repetir e o que torna a funcao
    # idempotente por construcao em vez de por sorte.
    mudou = True
    while mudou:
        mudou = False
        for prefixo in _PREFIXOS_DE_REFERENCIA:
            if limpo == prefixo.strip():
                limpo = ""
                mudou = True
                break
            if limpo.startswith(prefixo):
                limpo = limpo[len(prefixo) :]
                mudou = True
                break
    return limpo


@dataclass(frozen=True)
class Extracao:
    """O que o lead disse sobre o que procura, neste turno.

    Todos os campos sao anulaveis, e `None` tem um significado exato: **o lead
    nao falou disso neste turno**. Nunca "esqueca o que sabia". `gravar_estado`
    depende dessa leitura -- ver `preenchidos`.

    `FormaPagamento.INDEFINIDA` nao e sinonimo de `None`, e a diferenca e o
    que a medicao cobra: `None` e "o lead nao falou de pagamento neste turno",
    `INDEFINIDA` e "o lead afirmou que ainda nao decidiu". A fala de
    `compra-15` indice 0 -- "ainda nao decidi se vou financiar ou pagar a
    vista" -- e o caso: ele falou de pagamento, e o que disse foi que nao
    escolheu.

    Nao tem `intencao` de proposito: quem classifica intencao e o
    classificador, e duas fontes para o mesmo fato divergiriam. Nao tem
    telemetria porque a extracao viaja na chamada de `RespostaDoAgente`, que ja
    carrega a dela.
    """

    faixa_preco_min_centavos: int | None = None
    faixa_preco_max_centavos: int | None = None
    regiao: str | None = None
    tipo_imovel: TipoImovel | None = None
    quartos: int | None = None
    vagas: int | None = None
    urgencia: Urgencia | None = None
    forma_pagamento: FormaPagamento | None = None
    tem_imovel_para_vender: bool | None = None

    def preenchidos(self) -> dict[str, object]:
        """Os campos que o lead informou, e so eles.

        `is not None` e nao a veracidade do valor: `False`
        (`tem_imovel_para_vender`) e `0` (`vagas`) sao informacao, e um `if
        valor` os descartaria em silencio -- o lead que diz "nao tenho nada pra
        vender" respondeu a pergunta.
        """
        return {
            campo.name: valor
            for campo in fields(self)
            if (valor := getattr(self, campo.name)) is not None
        }

    def vazia(self) -> bool:
        return not self.preenchidos()


@dataclass(frozen=True)
class RespostaDoAgente:
    """O que uma chamada ao modelo devolve num turno.

    Intencao, confianca e resposta vem juntas porque vem da mesma chamada: o
    modelo enxerga a conversa inteira ao decidir as tres, entao a resposta ja
    sai coerente com a intencao que ele mesmo atribuiu.

    `extracao` vem junto pelo mesmo motivo que `intencao` e `resposta`: sai da
    mesma chamada. O modelo enxerga a conversa inteira ao decidir as quatro
    coisas, e a resposta ja sai coerente com o que ele mesmo extraiu -- e por
    isso ele nao repergunta o que acabou de ouvir.
    """

    intencao: Intencao
    confianca: Decimal
    resposta: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    extracao: Extracao

    # TEC-257. Os campos sobre os quais esta resposta pergunta, declarados
    # pelo proprio modelo. Vem depois de `resposta` no schema porque relata o
    # texto ja escrito -- ver `_ORDEM_DOS_CAMPOS`.
    #
    # Tupla e nao list: o dataclass e frozen, e uma list mutavel dentro dele
    # seria congelamento de fachada.
    perguntou: tuple[str, ...] = ()

    # Zero, e nao `None`, porque "nao cacheou" e uma quantidade e nao uma
    # ausencia: o modelo respondeu, o prefixo foi enviado, e o que o cache
    # poupou foi nada. `None` em `message_telemetry` significa outra coisa --
    # "esta linha e anterior a TEC-231 e ninguem media" --, e as duas leituras
    # nao podem colidir na mesma coluna.
    cache_write: int = 0
    cache_read: int = 0


@dataclass(frozen=True)
class PerguntaDeDesambiguacao:
    """O que a segunda chamada devolve quando o lead foi vago demais.

    Nao tem `intencao` nem `confianca` de proposito: esta chamada nao
    classifica nada. Quem classificou foi a primeira, e o resultado dela ja
    esta gravado quando esta acontece.

    Os campos de telemetria repetem os de `RespostaDoAgente` porque o turno
    trata os dois do mesmo jeito na hora de gravar a fala do agente.
    """

    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int

    # Zero, e nao `None`, porque "nao cacheou" e uma quantidade e nao uma
    # ausencia: o modelo respondeu, o prefixo foi enviado, e o que o cache
    # poupou foi nada. `None` em `message_telemetry` significa outra coisa --
    # "esta linha e anterior a TEC-231 e ninguem media" --, e as duas leituras
    # nao podem colidir na mesma coluna.
    cache_write: int = 0
    cache_read: int = 0
