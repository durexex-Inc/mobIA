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
from datetime import datetime
from zoneinfo import ZoneInfo

from mobia.app.config import get_settings

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")

# Casam por substring: carregam o verbo ou a preposicao que os torna um pedido,
# e nenhum e palavra solta.
#
# **Nenhum termo aqui e so um substantivo, e isso e deliberado.** O modulo de
# opt-out registra o preco de errar nisso: "nao quero mais receber nada" saiu
# dos inequivocos porque "nada" aceita complemento partitivo e cada refinamento
# de busca silenciava um comprador.
#
# **INVARIANTE: quando "pessoa", "humano" ou "alguem" ocupam papel de DESTINO
# ("quero uma ___", "me transfere pra uma ___", "me passa pra uma ___"),
# carregam qualificador explicitado.** Quando ocupam papel de INTERLOCUTOR
# ("falar com uma ___"), nao carregam qualificador porque o verbo ja os
# desambigua. Quando ocupam papel de ATRIBUTO, qualificando outro substantivo
# ("atendimento humano"), nao carregam qualificador porque nao ocupam o lugar
# onde "fisica/juridica" apareceria. "Pessoa fisica" e "pessoa juridica" sao
# vocabulario de contrato imobiliario neste dominio -- "quero uma pessoa fisica
# no contrato" nao e pedido de transferencia, e "mudar o titular para uma pessoa
# juridica" e assunto de reescritura. Mas "falar com uma pessoa juridica" e
# pedido legitimo -- quem pergunta "posso falar com uma pessoa juridica?" quer
# mesmo um humano, e essa colisao erra na direcao barata (transferencia extra,
# nao silencio).
#
# Foram removidos por falso positivo durante as revisoes:
# - "quero uma pessoa", "queria uma pessoa": colisao com pessoa fisica/juridica
#   (papel de DESTINO)
# - "me passa pra uma pessoa", "me passa para uma pessoa": objeto "pessoa" nua
#   (papel de DESTINO)
# - "me transfere": verbo sem objeto
# - "me transfere pra uma pessoa", "me transfere para uma pessoa": objeto nua
#   (papel de DESTINO)
# - "atendimento humano" bare: violava invariante de verbo/preposicao
#
# Em lugar deles, os termos mantidos sao formas com qualificador explicitado
# ("de verdade", "da equipe", "de alguem") quando pessoa/humano sao DESTINO,
# ou termos onde pessoa/humano sao INTERLOCUTOR ("falar com uma ___"), ou
# formas com objeto que nao colide ("atendente", "corretor", "robo"). Custo de
# recall e aceitavel -- o desenho ja declara recall como lacuna.
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
    "me passa pra um atendente",
    "me passa para um atendente",
    "me transfere pra um atendente",
    "me transfere para um atendente",
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


def dentro_da_janela_de_atendimento(agora: datetime) -> bool:
    """Se `agora` cai dentro da janela local em que existe gente para atender.

    RN-16.1 (TEC-143). Le `atendimento_horario_inicio`/`_fim` e `followup_fuso`
    de `get_settings()` -- o comentario deles em `config.py` explica por que a
    janela e da imobiliaria e nao do corretor designado, e por que reaproveita
    o fuso do follow-up em vez de um campo proprio.

    **Convencao de borda: inclusiva nas duas pontas, igual `followup_horario_fim`
    documenta em `config.py` e `horario_permite_envio` (`domain/outbound/horario.py`)
    aplica.** `fim` nomeia o ultimo MINUTO em que a janela ainda vale, nao a
    ultima hora inteira -- com o default 18 a comparacao e `<=`, entao 18:00
    esta dentro e 18:01 esta fora. Confirmado rodando
    `test_a_janela_inclui_a_hora_de_abertura` (9:00 dentro, borda de inicio) e
    o teste da borda de fim deste modulo.

    `agora` precisa ser aware pela mesma razao que `horario_permite_envio`
    exige: um naive faria `astimezone` assumir o fuso do SISTEMA, que diverge
    entre esta maquina e o runner de CI, e o erro apareceria so em um dos dois.
    """
    if agora.tzinfo is None:
        raise ValueError(
            "agora sem tzinfo: astimezone assumiria o fuso do sistema, que "
            "diverge entre esta maquina e o runner de CI. Passe um datetime aware."
        )
    settings = get_settings()
    local = agora.astimezone(ZoneInfo(settings.followup_fuso))
    minuto_do_dia = local.hour * 60 + local.minute
    inicio = settings.atendimento_horario_inicio * 60
    fim = settings.atendimento_horario_fim * 60
    return inicio <= minuto_do_dia <= fim


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
