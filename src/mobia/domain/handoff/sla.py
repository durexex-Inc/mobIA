"""O prazo de aceite de um handoff, contado dentro da jornada do corretor. TEC-178.

Pura de proposito, no molde de `vocabulario.py`, `context/score.py` e
`outbound/horario.py`: sem I/O, sem banco, sem chamada ao modelo. Quem grava
o prazo e o repositorio; aqui so se calcula quando ele vence.

**Nao reusa nem estende `horario_permite_envio` (`outbound/horario.py`).**
Aquela funcao responde "o relogio permite enviar automatico agora?" -- uma
pergunta pontual, de sim ou nao, sobre UM instante. Esta responde "dado um
instante e N minutos de jornada, quando o prazo acaba?" -- uma pergunta de
soma, cujo resultado pode cair em outro dia. Sao perguntas diferentes o
bastante para que uma segunda funcao seja mais clara que a mesma com um
parametro a mais.

**`inicio` ingenuo levanta, pela mesma razao que `horario_permite_envio` ja
documenta:** `astimezone()` num naive nao erra, ele assume o fuso do
SISTEMA. Esta maquina esta em UTC-3 e o runner do CI esta em UTC; um naive
daria limites diferentes nos dois lugares, e o bug ficaria invisivel aqui e
apareceria so no CI.

**Jornada degenerada (`jornada_inicio >= jornada_fim`) levanta.** O CHECK
`ck_corretores_jornada` ja proibe isso no banco, mas esta funcao e pura e
pode ser chamada de qualquer lugar -- inclusive de um teste ou script que
nunca chegou perto do banco. E o motivo nao e so defensivo: com
`inicio >= fim` a janela disponivel em qualquer dia e sempre zero ou
negativa, e o laco que soma dia a dia nunca acharia uma folga positiva para
consumir -- um loop infinito em vez de um erro claro. Recusar na entrada e
melhor do que travar em producao.

Tudo keyword-only: `jornada_inicio` e `jornada_fim` sao dois `int`
adjacentes, e troca-los inverte a janela sem levantar, sem erro de tipo e
sem o mypy ver. Mesma razao de `horario_permite_envio` e de `temperatura_de`.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PRAZO_QUENTE_MINUTOS = 15
PRAZO_PADRAO_MINUTOS = 240


def prazo_em_minutos(temperatura: str | None) -> int:
    """Quantos minutos o corretor tem para aceitar, pela temperatura do lead.

    `None` conta como nao-QUENTE, nao como FRIO: e a "linha anterior a
    TEC-151", um lead cuja temperatura ninguem calculou ainda. Dar 15 minutos
    a ele inventaria uma urgencia que a temperatura nunca afirmou.
    """
    if temperatura == "QUENTE":
        return PRAZO_QUENTE_MINUTOS
    return PRAZO_PADRAO_MINUTOS


def limite_de_aceite(
    *,
    inicio: datetime,
    minutos: int,
    jornada_inicio: int,
    jornada_fim: int,
    fuso: ZoneInfo,
) -> datetime:
    """Quando o prazo de aceite vence, contando so dentro da jornada do corretor.

    `jornada_inicio` e `jornada_fim` sao horas locais no `fuso`. Tres casos:
    o instante ja esta dentro da jornada e os minutos cabem antes do
    fechamento -- soma direta; esta dentro mas os minutos atravessam o
    fechamento -- o resto continua na abertura do dia seguinte; esta fora da
    jornada -- a contagem so comeca na proxima abertura. O laco cobre os tres
    e tambem um prazo maior que um dia inteiro de jornada, consumindo um dia
    de cada vez ate os `minutos` se esgotarem.

    Devolve um datetime aware em UTC.
    """
    if inicio.tzinfo is None:
        raise ValueError(
            "inicio sem tzinfo: `astimezone` assumiria o fuso do sistema, que "
            "difere entre esta maquina (UTC-3) e o runner do CI (UTC), e o erro "
            "ficaria invisivel em um dos dois. Passe um datetime aware."
        )
    if jornada_inicio >= jornada_fim:
        raise ValueError(
            f"jornada degenerada: inicio={jornada_inicio} >= fim={jornada_fim}. "
            "O CHECK ck_corretores_jornada ja proibe isso no banco; com "
            "inicio >= fim a janela disponivel por dia nunca e positiva e o "
            "laco que soma dia a dia nunca terminaria."
        )

    cursor = inicio.astimezone(fuso)
    # float e nao int: `disponivel_minutos` (abaixo) vem de uma divisao e e
    # sempre float, e `restante -= disponivel_minutos` precisa dos dois lados
    # no mesmo tipo para o mypy aceitar. Nao e uma porta para minutos
    # fracionarios -- os dez casos de teste so operam em inteiros, e
    # `timedelta(minutes=...)` aceita float de qualquer forma.
    restante: float = minutos

    while True:
        abertura = cursor.replace(hour=jornada_inicio, minute=0, second=0, microsecond=0)
        fechamento = cursor.replace(hour=jornada_fim, minute=0, second=0, microsecond=0)

        if cursor < abertura:
            cursor = abertura
        elif cursor >= fechamento:
            cursor = abertura + timedelta(days=1)
            continue

        disponivel_minutos = (fechamento - cursor).total_seconds() / 60
        if restante <= disponivel_minutos:
            return (cursor + timedelta(minutes=restante)).astimezone(UTC)

        restante -= disponivel_minutos
        cursor = abertura + timedelta(days=1)
