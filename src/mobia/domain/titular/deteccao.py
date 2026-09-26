"""Deteccao do pedido de titular no texto, e o texto que confirma ao lead.

TEC-207, D3 do desenho. Deterministico e sem chamada paga, no molde de
`optout/deteccao.py::pediu_optout` e `humano/deteccao.py::pediu_humano`: uma
decisao de LGPD (o titular tem direito de acesso e de eliminacao dos proprios
dados, e o prazo comeca a contar da mensagem) nao pode depender de um
provedor de LLM estar de pe.

**Colisao com o opt-out, e a precedencia e por OBJETO, nao por lista.** "Remover
meu contato" fala de CONTATO/MENSAGERIA e e opt-out; "apagar meus dados" fala
de DADOS e e pedido de titular. Os dois detectores rodam sobre o mesmo texto
e podem concordar ou nao -- o teste de precedencia (`test_titular_deteccao.py`)
verifica so que `pedido_de_titular` ignora o que `pediu_optout` decide, e
vice-versa; nenhum dos dois consulta o outro.

**Colisao com pergunta sobre o IMOVEL, e o mesmo principio.** "Dados" perto de
um substantivo de imovel/anuncio ("do imovel", "do condominio", "da casa", "do
apartamento", "do anuncio") e assunto do imovel, nao do titular, mesmo quando a
frase tambem contem "meus" ou "que voces tem" -- achado de revisao (TEC-207):
"quais dados que voces tem do condominio?" e "quais dados que voces tem a
respeito do imovel anunciado?" casavam `_OBJETO_DE_DADOS_DO_LEAD` sem essa
guarda, porque "dados que voces tem" e substring livre, sem nada que exija que
os dados sejam os do PROPRIO lead. A guarda e uma lista pequena de
qualificadores de imovel (`_QUALIFICADORES_DE_IMOVEL`), nao excecoes uma a uma:
qualquer um deles perto de "dados" derruba o casamento inteiro, incluindo
"meus dados do imovel" -- o qualificador de imovel pesa mais que "meus" porque
o assunto da frase e o IMOVEL, e o "meus" ali e so posse gramatical ("os dados
[que eu tenho] do imovel"), nao o titular pedindo os proprios dados pessoais.
"""

import re

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

# Substantivos que, do lado de "dados", trocam o assunto de titular para
# imovel/anuncio. Lista pequena e generica de proposito -- ver o paragrafo
# acima no docstring do modulo -- em vez de excecao caso a caso para cada
# frase que a revisao achasse.
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
_QUALIFICADOR_DE_IMOVEL = re.compile(r"\b(?:" + "|".join(_QUALIFICADORES_DE_IMOVEL) + r")\b")


def _fala_de_dados_do_lead(normalizado: str) -> bool:
    """Se a mensagem fala dos dados do PROPRIO lead, e nao do imovel/anuncio.

    Casar `_OBJETO_DE_DADOS_DO_LEAD` e necessario mas nao suficiente: um
    qualificador de imovel na mesma mensagem ("do condominio", "do imovel
    anunciado") deixa claro que "dados" e do IMOVEL, mesmo quando a mesma
    frase tambem contem "meus" ou "que voces tem" -- ver o docstring do
    modulo para os dois casos que a revisao achou.
    """
    if not _OBJETO_DE_DADOS_DO_LEAD.search(normalizado):
        return False
    return _QUALIFICADOR_DE_IMOVEL.search(normalizado) is None


# Stems, de proposito: cada um casa varias conjugacoes ("apagar", "apague",
# "apaguem") sem listar uma por uma, no mesmo molde de `optout/deteccao.py`.
_VERBO_DE_ELIMINAR = re.compile(r"apag|exclu|delet|remov|esquec|elimin")

# Ao contrario do verbo de eliminar, estes sao palavras inteiras (fronteira de
# palavra) -- "ver", "quero" e "quais" sao curtos o bastante para colidir com
# substring de outra palavra ("resolver" contem "ver") se comparados sem
# fronteira.
_SINAL_DE_ACESSO = re.compile(r"\bquero\b|\bver\b|\bcopia\b|\bmandem\b|\benviem\b|\bquais\b")

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

    if _SINAL_DE_ACESSO.search(normalizado):
        return TipoDeSolicitacao.ACESSO
    return None


# Kind proprio, no mesmo molde de `KIND_DA_CONFIRMACAO_DE_OPTOUT`: fura as
# guardas de opt-out e de atendimento humano de `GuardedOutbound.send` (D3 do
# desenho) -- e reconhecimento legal de um pedido do proprio lead, entao ele
# sai mesmo que o mesmo pedido de eliminacao acabe de registrar opt-out.
KIND_DA_CONFIRMACAO_DE_TITULAR = "titular_confirmacao"

# COM acento: e texto que chega ao lead (TEC-267). Um por tipo, verbatim da D3
# do desenho.
TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO = (
    "Registrei seu pedido para apagar seus dados. Ele será atendido em até 15 "
    "dias, e até lá não vou mais te enviar mensagens."
)
TEXTO_DA_CONFIRMACAO_DE_ACESSO = (
    "Registrei seu pedido de acesso aos seus dados. Ele será atendido em até 15 dias."
)
