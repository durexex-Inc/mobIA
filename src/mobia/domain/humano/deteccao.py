"""O lead pediu para falar com uma pessoa.

TEC-143. Deterministico e sem chamada paga, pela mesma razao que
`domain/optout/deteccao.py` declara para o opt-out: a decisao nao pode depender
de um provedor estar de pe. Aqui o argumento e ainda mais direto -- o provedor
falha pior justamente quando o lead ja esta irritado o bastante para pedir uma
pessoa.

Medido na TEC-143: acrescentar `FALAR_COM_HUMANO` ao enum `Intencao` custaria
5 tokens no schema compilado e levaria a margem do orcamento de prompt de 6,2
para 1,2 -- mas o que decidiu nao foi o custo, foi a dependencia.
"""

import re
import unicodedata

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")

# Casam por substring: carregam o verbo ou a preposicao que os torna um pedido,
# e nenhum e palavra solta.
#
# **Nenhum termo aqui e so um substantivo, e isso e deliberado.** O modulo de
# opt-out registra o preco de errar nisso: "nao quero mais receber nada" saiu
# dos inequivocos porque "nada" aceita complemento partitivo e cada refinamento
# de busca silenciava um comprador. O analogo aqui e "pessoa" -- medido contra
# as 147 mensagens de lead do corpus de evals, ele aparece 2 vezes, as duas
# dentro de "pessoalmente", em perguntas sobre assinar a distancia.
#
# Foram removidos por falso positivo (TEC-143, revisao fix round 1):
# - "quero uma pessoa" e "queria uma pessoa" casavam "pessoa fisica" vs
#   "pessoa juridica", vocabulario corriqueiro de contrato imobiliario que nao e
#   pedido de transferencia. O custo de recall e aceitavel.
# - "atendimento humano" bare violava o invariante -- todo termo deve carregar o
#   verbo ou preposicao. Um lead reclamando do atendimento de OUTRA imobiliaria
#   nao pede transferencia. "quero atendimento humano" permanece e cobre o caso
#   real.
# - "me transfere" e verbo sem objeto -- "me transfere o comprovante do pix"
#   aparece em conversa sobre pagamento. Substituido por formas com objeto.
_TERMOS_INEQUIVOCOS: tuple[str, ...] = (
    "falar com uma pessoa",
    "falar com um humano",
    "falar com humano",
    "falar com um atendente",
    "falar com uma atendente",
    "falar com atendente",
    "falar com alguem de verdade",
    "falar com um corretor de verdade",
    "quero uma pessoa de verdade",
    "quero uma pessoa da equipe",
    "queria uma pessoa de verdade",
    "me passa pra uma pessoa",
    "me passa para uma pessoa",
    "me passa pra um atendente",
    "me passa para um atendente",
    "me transfere pra um atendente",
    "me transfere para um atendente",
    "me transfere pra uma pessoa",
    "me transfere para uma pessoa",
    "quero atendimento humano",
    "nao quero falar com robo",
    "cansei de robo",
    "para de robo",
)

# So casam a mensagem INTEIRA. Um lead que escreve so "atendente" esta pedindo;
# o mesmo substantivo dentro de uma frase e assunto, nao pedido.
_TERMOS_AMBIGUOS: frozenset[str] = frozenset({"atendente", "humano", "pessoa real"})


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    Mesmo normalizador do opt-out, e pela mesma razao: "ATENDENTE!" e
    "atendente" sao a forma que um lead irritado escreve, e a faixa estrita
    compara a mensagem inteira.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def pediu_humano(texto: str) -> bool:
    """O lead pediu explicitamente para ser atendido por uma pessoa."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if normalizado in _TERMOS_AMBIGUOS:
        return True
    return any(termo in normalizado for termo in _TERMOS_INEQUIVOCOS)


# Mora aqui, e nao em `turno.py`, pelo mesmo motivo que
# `TEXTO_DA_CONFIRMACAO_DE_OPTOUT` mora no modulo de opt-out: o texto pertence
# ao assunto, nao ao orquestrador que o entrega.
#
# COM acento: e texto que chega ao lead (TEC-267).
TEXTO_DO_PEDIDO_DE_HUMANO = (
    "Claro! Já avisei nossa equipe e um corretor vai falar com você por aqui. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# `{inicio}` e `{fim}` sao preenchidos com as horas locais da janela.
TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO = (
    "Claro! Já avisei nossa equipe. Nosso atendimento é das {inicio}h às {fim}h, "
    "então um corretor vai falar com você no próximo horário. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# Kind proprio pela mesma razao do kind da confirmacao de opt-out: a reserva em
# `outbound_dispatches` nao pode colidir com a resposta que este turno nao vai
# mandar.
KIND_DO_PEDIDO_DE_HUMANO = "pedido_de_humano"

SUBAGENTE_PEDIDO_DE_HUMANO = "pedido_de_humano"
