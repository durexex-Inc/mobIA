"""O lead quer marcar visita, aceita o horario, ou recusa. TEC-371, D2.

Deterministico e sem chamada paga, como `domain/optout/deteccao.py` e
`domain/humano/deteccao.py`. Duas razoes, e a segunda e a que decide:

  - O orcamento do prompt nao cabe. Medido em 25/09/2026, a margem de
    `test_a_margem_do_orcamento_do_prompt_e_deliberada` e de **6,2 tokens**, e
    uma ferramenta nova em `tools=` custa a ordem de grandeza da ferramenta de
    busca -- 131,2. O ritual manda perguntar "o que sai do prompt para o novo
    texto entrar?", e esta card nao tem resposta.
  - A decisao nao pode depender de o provedor estar de pe. Um lead que
    pergunta "pode ser quinta de manha?" durante uma indisponibilidade do
    modelo continua tendo horario para escolher.

**Este modulo NAO e o `MOTIVO_VISITA` de `domain/context/gatilhos.py`, e a
diferenca e a assimetria de erro, nao o vocabulario.** A docstring daquele
modulo declara a faixa dele como estrita porque um falso positivo forca
QUENTE **permanentemente** e toca o telefone do corretor, sem tela para
desfazer -- e paga isso em recall, nomeando o caso: "posso ver o apartamento
amanha?" nao dispara la.

Aqui a conta e a inversa:

  - Falso positivo: o agente oferece tres horarios a quem nao pediu. O lead
    ignora ou diz que nao quer, e o turno seguinte segue normal. Visivel,
    barato, reversivel pela propria conversa.
  - Falso negativo: o lead pediu para marcar visita e o agente responde como
    se nao tivesse pedido. E o epico inteiro nao acontecendo, e ele nao tem
    como insistir de outro jeito -- ja disse a frase certa.

Reversivel e visivel perde para invisivel e irreversivel na `gatilhos.py`;
aqui os papeis se trocam. **Por isso sao dois detectores, e nenhum importa o
outro.** Quem quiser deduplica-los depois tem de reabrir as duas assimetrias,
nao so as duas listas.

**Desmarcar, remarcar, reagendar e cancelar tem VETO, e nao so ausencia.**
Sao a TEC-372 e a TEC-172, e reconhece-los aqui faria o agente oferecer
horario novo a quem quis desmarcar -- o oposto do que a fala diz. Deixa-los
so de fora das listas nao bastava: a segunda via (enquadramento mais data)
dispara em "quero remarcar, pode ser quinta de manha?" sem precisar de termo
nenhum. Ver `_TERMOS_DE_OUTRA_CARD`.
"""

import re
import unicodedata
from datetime import datetime

from mobia.domain.agendamento.data_falada import NaoReconhecida, resolver

# **Os termos casam com limite de palavra nos DOIS lados, e a `gatilhos.py` so
# no inicio.** La todo termo termina em substantivo ("visita", "proposta"), e
# o objeto ser prefixo de palavra maior nao era o problema que a correcao
# resolvia. Aqui ha termos curtos -- "sim", "ok", "nao" -- que sao substring
# de palavra comum: sem o limite no fim, "sim" casaria dentro de "simples" e
# "nao" dentro de "naosei" que um lead apressado escreve junto. O custo do
# limite no fim e perder flexao ("visitarei" nao casa "visitar"), e por isso a
# lista traz as formas que se quer, em vez de contar com prefixo.
_TERMOS_DO_PEDIDO: tuple[str, ...] = (
    # Verbo de acao junto do objeto, como na `gatilhos.py`.
    "agendar visita",
    "agendar uma visita",
    "agendar a visita",
    "agendar um horario",
    "agendar horario",
    "marcar visita",
    "marcar uma visita",
    "marcar a visita",
    "marcar um horario",
    "marcar horario",
    "marcar um dia",
    "fazer uma visita",
    "fazer a visita",
    # O verbo sozinho, quando ele ja e inequivoco neste dominio. **O
    # substantivo sozinho NAO entra**, e a razao e a que a `gatilhos.py`
    # escreve: o criterio e o verbo de acao junto do objeto, nunca o objeto
    # sozinho. Com `"visita"` na lista, "quero desmarcar a visita" disparava
    # -- um lead CANCELANDO recebia tres horarios novos.
    "visitar",
    # Ver e conhecer pedem o objeto: "posso ver?" sozinho tanto pede visita
    # quanto pede foto, e a ficha de imovel e o que o lead ve mais vezes na
    # conversa. Com o objeto, a leitura de visita e a unica que sobra.
    "ver o imovel",
    "ver o apartamento",
    "ver a casa",
    "ver o terreno",
    "ver pessoalmente",
    "conhecer o imovel",
    "conhecer o apartamento",
    "conhecer a casa",
    "conhecer o terreno",
    "conhecer pessoalmente",
)

# **A segunda via, e a razao dela e o proprio Gherkin da card.** O primeiro
# cenario e "pode ser quinta de manha?" -- uma fala sem verbo de agendamento
# e sem a palavra visita, que nenhuma lista de termos pega sem ficar larga
# demais. O que ela tem e um ENQUADRAMENTO de proposta mais uma data que
# `data_falada::resolver` reconhece, e sao as duas coisas juntas que a tornam
# um pedido de horario.
#
# Exigir as duas e o que separa "pode ser quinta de manha?" de "meu contrato
# vence dia 15": a segunda tem data e nenhum enquadramento. E separa tambem de
# "pode ser mais barato?", que tem enquadramento e nenhuma data.
_FRAMES_DE_PROPOSTA: tuple[str, ...] = (
    "pode ser",
    "poderia ser",
    "da pra ser",
    "da para ser",
    "que tal",
    "consigo ir",
    "posso ir",
    "fica melhor",
    "seria melhor",
    "estou livre",
    "to livre",
    "tenho disponibilidade",
    "prefiro",
)

# **O veto, e ele vem antes de tudo.** Desfazer o que ja esta marcado e a
# TEC-372 (ler a resposta ao lembrete) e a TEC-172 (as transicoes), e nenhuma
# das duas tem leitor de conversa ainda. Sem o veto, "quero remarcar, pode ser
# quinta de manha?" dispararia pela segunda via -- enquadramento mais data --
# e o agente ofereceria horario NOVO a quem quer mexer no que ja existe, sem
# nunca cancelar o antigo.
#
# O limite de palavra nos dois lados e o que mantem o veto estreito: ele nao
# pode engolir "marcar" nem "agendar", que sao o pedido legitimo.
_TERMOS_DE_OUTRA_CARD: tuple[str, ...] = (
    "desmarcar",
    "remarcar",
    "reagendar",
    "cancelar",
    "cancela",
    "adiar",
    "transferir a visita",
)

_TERMOS_DA_CONFIRMACAO: tuple[str, ...] = (
    "sim",
    "isso",
    "isso mesmo",
    "confirmo",
    "confirmado",
    "confirma",
    "pode marcar",
    "pode agendar",
    "pode confirmar",
    "pode ser",
    "fechado",
    "combinado",
    "ok",
    "okay",
    "beleza",
    "perfeito",
    "otimo",
    "ta bom",
    "tudo bem",
    "claro",
    "bora",
)

_TERMOS_DA_RECUSA: tuple[str, ...] = (
    "nao",
    "nao posso",
    "nao da",
    "nao consigo",
    "nao serve",
    "nao vai dar",
    "nenhum",
    "nenhum deles",
    "outro horario",
    "outro dia",
    "outra data",
    "impossivel",
)


def _padrao(termos: tuple[str, ...]) -> re.Pattern[str]:
    """Um padrao por lista, com limite de palavra nos dois lados de cada alternativa.

    Ordenado do mais longo para o mais curto so para o `finditer` preferir o
    casamento maior quando dois termos comecam no mesmo ponto -- nao muda o
    veredito (`any` sobre alternativas), muda o que a guarda de negacao le.
    """
    alternativas = "|".join(re.escape(termo) for termo in sorted(termos, key=len, reverse=True))
    return re.compile(r"\b(?:" + alternativas + r")\b")


_PADRAO_DO_PEDIDO = _padrao(_TERMOS_DO_PEDIDO)
_PADRAO_DE_OUTRA_CARD = _padrao(_TERMOS_DE_OUTRA_CARD)
_PADRAO_DO_FRAME = _padrao(_FRAMES_DE_PROPOSTA)
_PADRAO_DA_CONFIRMACAO = _padrao(_TERMOS_DA_CONFIRMACAO)
_PADRAO_DA_RECUSA = _padrao(_TERMOS_DA_RECUSA)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")

# A guarda de negacao e a mesma de `humano/deteccao.py`, e pelo mesmo motivo:
# "nao quero marcar visita" e uma recusa, "nao, quero marcar visita" e um
# pedido, e depois de apagar a pontuacao as duas viram a mesma string. Por
# isso a guarda le uma segunda normalizacao, em que cada corrida de pontuacao
# vira um token de pausa que empurra o "nao" para longe do termo.
#
# **Nao "simplifique" isto reusando `_normalizar`:** a unica coisa que
# distingue um pedido de uma recusa aqui e a pontuacao que ele apaga.
_NEGACAO_ANTES = re.compile(r"(?:^| )nao(?: (?:quero|queria|quis|posso|pretendo|preciso))? $")
_PAUSA = "|"
_PONTUACAO_DE_PAUSA = re.compile(r"[,.;:!?]+")
_SO_LETRAS_ESPACO_E_PAUSA = re.compile(r"[^a-z |]+")


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    E o mesmo transform de `gatilhos.py`, de `optout/deteccao.py` e de
    `humano/deteccao.py`, e a quarta copia e deliberada pelo argumento que a
    segunda ja escreve: compartilhar acoplaria detectores com assimetrias
    diferentes, e toda mudanca aqui viraria mudanca no caminho de LGPD. A casa
    tem normalizadores por proposito, nao um compartilhado.
    """
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", _sem_acento(texto))).strip()


def _normalizar_com_pausa(texto: str) -> str:
    marcado = _PONTUACAO_DE_PAUSA.sub(f" {_PAUSA} ", _sem_acento(texto))
    return _ESPACOS.sub(" ", _SO_LETRAS_ESPACO_E_PAUSA.sub(" ", marcado)).strip()


def _dispara(texto: str, padrao: re.Pattern[str]) -> bool:
    """Se `padrao` casa ao menos uma vez sem negacao imediatamente antes.

    Duas strings e duas perguntas, como em `humano/deteccao.py::_dispara`:
    quem decide se o termo ESTA na mensagem e a normalizacao de sempre; quem
    decide se ele esta NEGADO e a com pausa, porque os deslocamentos de uma
    nao valem na outra.

    Termo partido por pontuacao ("marcar, visita") existe na primeira e some
    da segunda. A guarda nao julga negacao de um termo que nao acha, e o lado
    barato e disparar -- o custo de um falso positivo aqui e uma oferta de
    horario que o lead ignora.

    Percorre TODAS as ocorrencias: basta uma limpa. Parar na primeira
    transformaria a guarda de negacao numa guarda de ordem das frases.
    """
    normalizado = _normalizar(texto)
    if not normalizado or padrao.search(normalizado) is None:
        return False
    com_pausa = _normalizar_com_pausa(texto)
    casamentos = list(padrao.finditer(com_pausa))
    if not casamentos:
        return True
    return any(_NEGACAO_ANTES.search(com_pausa[: casa.start()]) is None for casa in casamentos)


def quer_agendar(texto: str, *, agora: datetime) -> bool:
    """O lead pediu para marcar visita, por termo explicito ou por data proposta.

    `agora` entra porque a segunda via pergunta a `data_falada::resolver` se
    ha data na fala, e resolver data sem relogio nao e possivel. Nunca levanta
    para texto do lead -- `resolver` tambem nao, por decisao propria dele.
    """
    # O veto primeiro: desfazer o que ja esta marcado nao e pedir horario
    # novo, e as duas vias abaixo nao sabem disso sozinhas. Sem guarda de
    # negacao de proposito -- "nao quero cancelar, quero marcar visita" cai
    # fora, e cair fora aqui e o turno normal acontecendo, que e barato.
    if _PADRAO_DE_OUTRA_CARD.search(_normalizar(texto)) is not None:
        return False
    if _dispara(texto, _PADRAO_DO_PEDIDO):
        return True
    if not _dispara(texto, _PADRAO_DO_FRAME):
        return False
    return not isinstance(resolver(texto, agora=agora), NaoReconhecida)


def confirmou(texto: str) -> bool:
    """O lead assentiu ao horario que o agente acabou de repetir por extenso.

    **Perguntado ANTES de `recusou`, e a ordem importa.** "nao, pode ser" tem
    termo das duas listas: a pausa depois do "nao" faz a guarda de negacao
    liberar a confirmacao, e e essa a leitura certa -- o lead se corrigiu.
    Perguntar a recusa primeiro leria a correcao como negativa.
    """
    return _dispara(texto, _PADRAO_DA_CONFIRMACAO)


def recusou(texto: str) -> bool:
    """O lead disse que o horario nao serve.

    Sem guarda de negacao, porque aqui a negacao E o sinal: "nao" e o termo,
    e "nao, pode ser" ja foi resolvido por `confirmou`, perguntado antes.
    """
    normalizado = _normalizar(texto)
    return bool(normalizado) and _PADRAO_DA_RECUSA.search(normalizado) is not None
