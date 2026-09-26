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
antes dele, sem recheio entre a preposicao e o substantivo. O recheio entre o
objeto e a preposicao existe para alcancar "dados QUE VOCES TEM do
condominio" e "dados QUE VOCES TEM A RESPEITO DO imovel"; a falta de recheio
entre a preposicao e o substantivo existe para NAO alcancar "parem DE MANDAR
imoveis" -- ali "de" e preposicao do verbo "mandar", nao do substantivo de
imovel, e um recheio ali reabriria o mesmo defeito que esta revisao fechou.
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
# TEM do condominio" e "dados QUE VOCES TEM A RESPEITO DO imovel" --, e ZERO
# recheio entre a preposicao e o substantivo -- para NAO alcancar "parem DE
# MANDAR imoveis", onde "de" e preposicao do verbo "mandar" e nao do
# substantivo de imovel. Ver o docstring do modulo para os dois achados de
# revisao que fixaram esta forma.
_QUALIFICADOR_COLADO_AO_OBJETO = re.compile(
    r"(?:\s+\w+){0,4}?"
    r"\s+(?:" + "|".join(_PREPOSICOES_DE_QUALIFICADOR) + r")"
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
