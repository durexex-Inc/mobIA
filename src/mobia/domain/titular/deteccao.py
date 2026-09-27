"""Deteccao do pedido de titular no texto, e o texto que confirma ao lead.

TEC-207, D3 do desenho. Deterministico e sem chamada paga, no molde de
`optout/deteccao.py::pediu_optout` e `humano/deteccao.py::pediu_humano`: uma
decisao de LGPD (o titular tem direito de acesso e de eliminacao dos proprios
dados, e o prazo de 15 dias so comeca a contar quando o turno registra o
pedido) nao pode depender de um provedor de LLM estar de pe.

**Colisao com o opt-out, e a precedencia e por OBJETO, nao por lista.** "Remover
meu contato" fala de CONTATO/MENSAGERIA e e opt-out; "apagar meus dados" fala
de DADOS e e pedido de titular. Os dois detectores rodam sobre o mesmo texto
e podem concordar ou nao -- o teste de precedencia (`test_titular_deteccao.py`)
verifica so que `pedido_de_titular` ignora o que `pediu_optout` decide, e
vice-versa; nenhum dos dois consulta o outro.

**Colisao com pergunta sobre o IMOVEL, e o veto e SO POR COLAGEM, nunca pela
mensagem inteira.** "Dados" seguido de perto por um substantivo de
imovel/anuncio ("do imovel", "do condominio", "da casa", "do apartamento", "do
anuncio") e assunto do imovel, nao do titular -- mesmo quando a mesma frase
tambem contem "meus" ou "que voces tem": "quais dados que voces tem do
condominio?" e "quais dados que voces tem a respeito do imovel anunciado?"
sao `None`, porque o substantivo de imovel esta COLADO ao objeto de dados
(achado da primeira revisao, TEC-207).

**Mas a mesma mensagem pode falar de dados E de imovel em partes
independentes, e ai o veto NAO pode alcancar** -- achado da segunda revisao:
`"apaguem meus dados e parem de mandar imoveis"` e `"quero apagar meus dados,
nao quero mais apartamento"` sao pedidos explicitos de ELIMINACAO cujo
"imoveis"/"apartamento" fala de OUTRO assunto (o que o lead nao quer mais
receber), nao do "dados". Um veto que olhasse a mensagem inteira, como a
primeira versao deste modulo fazia, apagava os dois -- e um pedido legal
perdido e pior que uma pergunta sobre o imovel deixada passar. Por isso o veto
mede DISTANCIA a partir do fim do objeto casado (`_OBJETO_DE_DADOS_DO_LEAD`):
so vale quando o substantivo de imovel aparece a no maximo 4 palavras dali E
colado a uma preposicao (`do`/`da`/`dos`/`das`/`sobre`/`de`) IMEDIATAMENTE
antes dele (a menos de um artigo entre as duas -- ver o paragrafo seguinte),
sem outro recheio. O recheio entre o objeto e a preposicao existe para
alcancar "dados QUE VOCES TEM do condominio" e "dados QUE VOCES TEM A
RESPEITO DO imovel"; a falta de recheio entre a preposicao e o substantivo
existe para NAO alcancar "parem DE MANDAR imoveis" -- ali "de" e preposicao do
verbo "mandar", nao do substantivo de imovel, e um recheio generico ali
reabriria o mesmo defeito que esta revisao fechou.

**"sobre" nao contrai com o artigo, e um artigo aqui NAO e o recheio generico
acima** -- achado da terceira revisao: `do`/`da`/`dos`/`das` ja SAO
preposicao+artigo fundidos ("de" + "o" = "do"), mas "sobre" e "de" sozinhos
nao contraem -- portugues natural e "sobre O imovel", nao "sobreimovel". Sem
isso, `"apague meus dados sobre o imovel"` e `"...sobre a casa"` escapavam do
veto e um pedido sobre o IMOVEL virava ELIMINACAO/ACESSO. Por isso, entre a
preposicao e o substantivo, so um artigo (`o`/`a`/`os`/`as`) e permitido --
nada mais --, porque um artigo nao e um verbo como "mandar": ele nao introduz
um OBJETO novo, so concorda com o substantivo que vem a seguir. Continua
distinto do recheio generico do lado do objeto (paragrafo acima), que aceita
`{0,4}` palavras quaisquer -- aqui e literalmente so o artigo, ou nada.
"""

import re
from datetime import timedelta

from mobia.domain.optout.deteccao import normalizar
from mobia.domain.titular.vocabulario import TipoDeSolicitacao

# Fala de DADOS DO PROPRIO LEAD, e nao de dados em geral (do imovel, do
# condominio). "Dados" sozinho nao casa -- e o que separa "os dados do imovel
# estao errados" (assunto do imovel) de "meus dados" (assunto do titular).
#
# A terceira alternativa ("dados ... de mim") aceita ate 3 palavras de recheio
# entre "dados" e "de mim" -- o bastante para "quais dados voces tem de mim"
# sem abrir tanto a ponto de casar frases sem relacao nenhuma entre os dois
# extremos.
_OBJETO_DE_DADOS_DO_LEAD = re.compile(
    r"meus dados"
    r"|dados pessoais"
    r"|dados(?:\s+\w+){0,3}\s+de mim\b"
    r"|dados que voces tem"
)

# Substantivos que, colados ao objeto de dados por uma preposicao, trocam o
# assunto de titular para imovel/anuncio. Lista pequena e generica de
# proposito -- ver o docstring do modulo -- em vez de excecao caso a caso para
# cada frase que a revisao achasse.
_QUALIFICADORES_DE_IMOVEL: tuple[str, ...] = (
    "imovel",
    "imoveis",
    "apartamento",
    "apartamentos",
    "condominio",
    "condominios",
    "casa",
    "casas",
    "anuncio",
    "anuncios",
)

# Preposicoes que colam um substantivo de imovel ao objeto ("dados DO
# condominio", "dados DE imoveis", "dados SOBRE o imovel"). So estas -- um
# substantivo de imovel introduzido por outra coisa ("mandar imoveis", "mais
# apartamento") nao caracteriza colagem ao objeto de dados.
_PREPOSICOES_DE_QUALIFICADOR: tuple[str, ...] = ("do", "da", "dos", "das", "sobre", "de")

# Colado ao FIM do objeto casado (nao a mensagem inteira): ate 4 palavras de
# recheio entre o objeto e a preposicao -- o bastante para "dados QUE VOCES
# TEM do condominio" e "dados QUE VOCES TEM A RESPEITO DO imovel" --, um
# artigo OPCIONAL entre a preposicao e o substantivo -- "sobre o imovel", "de
# a casa" nao existe mas nao custa aceitar -- e nada alem disso, para NAO
# alcancar "parem DE MANDAR imoveis", onde "de" e preposicao do verbo "mandar"
# e nao do substantivo de imovel. Ver o docstring do modulo para os tres
# achados de revisao que fixaram esta forma.
_ARTIGO: tuple[str, ...] = ("os", "as", "o", "a")

_QUALIFICADOR_COLADO_AO_OBJETO = re.compile(
    r"(?:\s+\w+){0,4}?"
    r"\s+(?:" + "|".join(_PREPOSICOES_DE_QUALIFICADOR) + r")"
    r"(?:\s+(?:" + "|".join(_ARTIGO) + r"))?"
    r"\s+(?:" + "|".join(_QUALIFICADORES_DE_IMOVEL) + r")\b"
)


def _fala_de_dados_do_lead(normalizado: str) -> bool:
    """Se a mensagem fala dos dados do PROPRIO lead, e nao do imovel/anuncio.

    Casar `_OBJETO_DE_DADOS_DO_LEAD` e necessario mas nao suficiente: um
    qualificador de imovel COLADO ao fim do objeto ("do condominio", "do
    imovel anunciado") deixa claro que "dados" e do IMOVEL, mesmo quando a
    mesma frase tambem contem "meus" ou "que voces tem". A colagem se mede a
    partir do FIM do objeto casado, nao da mensagem inteira -- um qualificador
    de imovel em outra parte da mensagem (outro assunto, nao os "dados") nao
    veta. Ver o docstring do modulo para os casos que fixaram esta forma.
    """
    objeto = _OBJETO_DE_DADOS_DO_LEAD.search(normalizado)
    if not objeto:
        return False
    resto = normalizado[objeto.end() :]
    return _QUALIFICADOR_COLADO_AO_OBJETO.match(resto) is None


# So as formas conjugadas de PEDIR, cada uma entre fronteiras de palavra:
# infinitivo ("quero apagar"), infinitivo pessoal ("para voces apagarem"),
# subjuntivo singular e plural ("apague", "exclua", "quero que apaguem",
# "removam") e o imperativo singular do portugues falado ("apaga meus dados",
# "exclui", "remove"). Pela conjugacao: no -ar o subjuntivo termina em
# -e/-em, no -er/-ir em -a/-am.
#
# **O presente do indicativo no plural fica de fora** ("apagam", "deletam",
# "excluem", "removem", "esquecem"): e pergunta ou constatacao -- "voces
# apagam meus dados?", "voces excluem meus dados depois de quanto tempo?" --,
# nao pedido. **O singular fica dentro, e isso e uma ambiguidade aceita:**
# "apaga", "exclui" e "remove" sao tambem o presente do indicativo de terceira
# pessoa, e "o sistema apaga meus dados depois?" vira ELIMINACAO. Aceita
# porque o imperativo singular e a forma mais comum de pedir no Brasil
# ("apaga meus dados"), e perde-lo seria perder pedido legal; o lead que
# so perguntava recebe a pergunta de confirmacao e nao responde "apagar".
#
# A primeira versao casava o RADICAL solto (`apag|exclu|...`) em qualquer
# ponto do texto, e isso transformava em ELIMINACAO frases que so continham o
# radical dentro de outra palavra: "uma copia dos meus dados, EXCLUsivamente
# por e-mail", "ESQUECi de mandar meus dados pessoais", "o anuncio foi
# REMOVido?". Um falso positivo aqui nao e inofensivo, mesmo com a
# confirmacao em dois passos (ver `_CONFIRMACOES_DE_ELIMINACAO`): ele troca a
# resposta do modelo pela pergunta de confirmacao, e o lead que queria outra
# coisa fica sem ela naquele turno. O participio ("apagado", "removido") fica de fora de proposito:
# e pergunta ou constatacao ("meus dados foram apagados?"), nao pedido.
_TERMINACOES_DE_PEDIDO: dict[str, tuple[str, ...]] = {
    "apag": ("ar", "arem", "a", "ue", "uem"),
    "delet": ("ar", "arem", "a", "e", "em"),
    "elimin": ("ar", "arem", "a", "e", "em"),
    "exclu": ("ir", "irem", "i", "a", "am"),
    "remov": ("er", "erem", "e", "a", "am"),
    # Sem acento: `normalizar` ja tirou o cedilha de "esqueca"/"esquecam".
    "esquec": ("er", "erem", "e", "a", "am"),
}
_VERBO_DE_ELIMINAR = re.compile(
    r"\b(?:"
    + "|".join(
        radical + "(?:" + "|".join(terminacoes) + ")"
        for radical, terminacoes in _TERMINACOES_DE_PEDIDO.items()
    )
    + r")\b"
)

# O pedido de acesso e o VERBO LIGADO AO OBJETO, nunca um verbo solto em
# qualquer ponto da mensagem -- achado da revisao final (C1). A primeira versao
# aceitava "quero", "ver" e "quais" como sinais independentes, e bastava a
# mensagem tambem conter "meus dados" para uma frase de venda virar ACESSO:
# "quero agendar uma visita, meus dados: ...", "ja mandei meus dados, quero ver
# o apartamento", "quais dados pessoais voces precisam pra visita?", "quero
# corrigir meus dados". O custo desse falso positivo e o turno inteiro: ele
# registra a solicitacao, responde com o texto fixo e nunca chama o modelo.
#
# Duas formas, e so elas:
#
# - verbo de querer/pedir SEGUIDO do objeto, com no maximo um verbo de acesso
#   ("ver", "receber"...) e um "uma copia dos" no meio: "quero meus dados",
#   "quero ver os meus dados", "me mandem uma copia dos meus dados". Um verbo
#   que nao e de acesso entre os dois ("quero CORRIGIR meus dados", "quero
#   AGENDAR uma visita, meus dados") quebra a colagem, de proposito.
# - a pergunta "quais dados ... voces tem DE MIM": o "de mim"/"sobre mim" e
#   obrigatorio, porque "quais dados voces precisam" sem ele e pergunta de
#   cadastro, nao de titular.
#
# O preco aceito e o recall: "gostaria de saber o que voces sabem sobre mim"
# nao casa. Perder um pedido aqui deixa o lead sem o texto fixo, mas o modelo
# ainda responde e o ADMIN ainda pode atender pela exportacao
# (`GET /api/v1/leads/{id}/dados-pessoais`); sequestrar uma
# frase de venda cala o agente justamente na conversa que importa.
_PEDIDO_DE_ACESSO = re.compile(
    r"\b(?:quero|queria|gostaria de|mandem|enviem|manda|envia)"
    r"(?: me)?"
    r"(?: (?:ver|receber|acessar|consultar|saber))?"
    r"(?: (?:uma|a) copia d(?:os|e))?"
    r"(?: todos)?(?: os)?"
    r" (?:meus dados|dados pessoais)\b"
    r"|\bquais (?:sao )?(?:os )?dados(?: pessoais)?(?: que)? voces "
    r"(?:tem|guardam|possuem|armazenam) (?:de|sobre) mim\b"
)

# So nega o que esta imediatamente antes do verbo (ate 2 palavras, para cobrir
# "nao quero apagar" alem de "nao apague"), no mesmo espirito da guarda de
# `humano/deteccao.py::_casa_sem_negacao` -- mas mais simples, porque aqui nao
# ha o caso do "nao" de contraste ("nao, quero apagar") que la exigiu uma
# segunda normalizacao com pontuacao preservada. Nenhum teste desta card exige
# essa distincao; se um dia exigir, e ali que ela entra.
_NEGACAO_ANTES_DO_VERBO = re.compile(r"\bnao\b(?:\s+\w+){0,2}\s*$")


def _tem_negacao_antes(normalizado: str, indice: int) -> bool:
    return _NEGACAO_ANTES_DO_VERBO.search(normalizado[:indice]) is not None


def pedido_de_titular(texto: str) -> TipoDeSolicitacao | None:
    """O lead pediu para exercer um direito de titular: acesso ou eliminacao.

    `None` cobre tanto "nao e pedido nenhum" quanto "e pedido, mas negado"
    (`"nao quero apagar meus dados"`) -- as duas devolvem o mesmo `None` porque
    a chamadora (o turno) trata as duas do mesmo jeito: nao registra nada.
    """
    normalizado = normalizar(texto)
    if not normalizado:
        return None
    if not _fala_de_dados_do_lead(normalizado):
        return None

    verbo_de_eliminar = _VERBO_DE_ELIMINAR.search(normalizado)
    if verbo_de_eliminar:
        if _tem_negacao_antes(normalizado, verbo_de_eliminar.start()):
            return None
        return TipoDeSolicitacao.ELIMINACAO

    if _PEDIDO_DE_ACESSO.search(normalizado):
        return TipoDeSolicitacao.ACESSO
    return None


# **A eliminacao pelo WhatsApp e em dois passos** -- decisao do Eduardo na
# revisao final da TEC-207 (C2). `pedido_de_titular` devolver ELIMINACAO nao
# registra nada: o turno responde com `TEXTO_DA_PERGUNTA_DE_ELIMINACAO` e so
# registra quando a mensagem SEGUINTE do lead e a palavra de confirmacao e a
# ultima coisa que o agente mandou a ele foi essa pergunta, ha menos de
# `JANELA_DA_CONFIRMACAO_DE_ELIMINACAO`. A razao sao as frases de CORRECAO de
# cadastro -- "apaga meus dados antigos e usa esse telefone novo", "pode excluir
# meus dados do cadastro antigo e manter o novo?" -- que o detector nao tem
# como separar de um pedido legal: em um passo so, cada uma delas gravava
# opt-out, encerrava a conversa e, sem recusa do ADMIN, anonimizava o lead uns
# 14 dias depois. O acesso continua em um passo: nao destroi nada.
#
# Normalizadas por `normalizar` (minusculas, sem acento, sem pontuacao), entao
# "APAGAR", "Apagar!" e "sim, apagar" casam. A mensagem INTEIRA tem de ser uma
# destas -- "apagar o que?" nao e confirmacao.
_CONFIRMACOES_DE_ELIMINACAO: frozenset[str] = frozenset({"apagar", "sim apagar", "confirmo apagar"})

# A pergunta vale por 24 horas. Depois disso um "apagar" solto e so uma
# palavra, e o lead que ainda quiser apagar pede de novo e recebe outra
# pergunta.
JANELA_DA_CONFIRMACAO_DE_ELIMINACAO = timedelta(hours=24)


def e_palavra_de_confirmacao(texto: str) -> bool:
    """O texto INTEIRO e a palavra que confirma a eliminacao ("apagar").

    Puro, sem consulta: diz so se a forma bate. Se e confirmacao de fato
    depende de a ultima mensagem do agente ter sido a pergunta -- quem decide
    e `titular/repositorio.py::pergunta_de_eliminacao_pendente`, chamada pelo
    turno. `IngestionService` e `process_message` usam so esta checagem para
    deixar a palavra furar o debounce e o fecho "agrupado": a palavra solta
    furar sem ser confirmacao e inofensivo (o turno roda normalmente), e
    segurar uma confirmacao de verdade atrasaria o registro do pedido.
    """
    return normalizar(texto) in _CONFIRMACOES_DE_ELIMINACAO


# Kind proprio, no mesmo molde de `KIND_DA_CONFIRMACAO_DE_OPTOUT`: fura as
# guardas de opt-out e de atendimento humano de `GuardedOutbound.send` (D3 do
# desenho) -- e reconhecimento legal de um pedido do proprio lead, entao ele
# sai mesmo que o mesmo pedido de eliminacao acabe de registrar opt-out.
KIND_DA_CONFIRMACAO_DE_TITULAR = "titular_confirmacao"

# Kind da pergunta que abre o segundo passo da eliminacao. Fura as mesmas
# duas guardas que a confirmacao, pela mesma razao: quem ja optou, ou cuja
# conversa um corretor assumiu, continua podendo exercer o direito -- e sem a
# pergunta nao ha como confirmar. E tambem a marca que o segundo passo procura
# em `outbound_dispatches`: a pergunta esta pendente se a reserva mais recente
# da conversa e deste kind (ver `pergunta_de_eliminacao_pendente`).
KIND_DA_PERGUNTA_DE_ELIMINACAO = "titular_pergunta_eliminacao"

# COM acento: e texto que chega ao lead (TEC-267). A pergunta nao promete
# nada: so diz como confirmar e que continuar a conversa basta para desistir.
TEXTO_DA_PERGUNTA_DE_ELIMINACAO = (
    "Para confirmar que você quer apagar seus dados, responda APAGAR. Se não era "
    "isso, é só continuar a conversa."
)

# COM acento: e texto que chega ao lead (TEC-267). Um por tipo, verbatim da D3
# do desenho.
TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO = (
    "Registrei seu pedido para apagar seus dados. Ele será atendido em até 15 "
    "dias, e até lá não vou mais te enviar mensagens."
)
TEXTO_DA_CONFIRMACAO_DE_ACESSO = (
    "Registrei seu pedido de acesso aos seus dados. Ele será atendido em até 15 dias."
)
