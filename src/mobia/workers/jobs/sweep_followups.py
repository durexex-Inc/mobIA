"""A varredura da cadencia de reengajamento.

TEC-183, RN-13.1 e RN-13.4. Molde do `sweep_stalled`: um job `cron` que
consulta trabalho vencido e age. A diferenca esta no relogio -- ver o
comentario do registro em `workers/main.py`.

**Nada e enviado ao lead.** A card grava a tentativa e emite `followup.devido`;
o texto e a entrega sao da TEC-184, e a RN-13.2 proibe follow-up sem
informacao nova, entao um texto provisorio violaria a regra de frente. Lacuna
declarada no desenho.
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from mobia.domain.followup.cadencia import CADENCIA, tentativa_devida
from mobia.domain.followup.repositorio import candidatos_a_followup, registrar_followup
from mobia.domain.optout.repositorio import esta_em_optout

log = structlog.get_logger(__name__)


async def sweep_followups(ctx: dict[str, Any], limite: int = 500) -> int:
    """Registra as tentativas de follow-up que venceram. Devolve quantas.

    **A ordem das duas guardas e proposital: `tentativa_devida` primeiro,
    `esta_em_optout` so para quem passou.** A primeira e funcao pura, sem
    I/O; a segunda e uma ida ao banco. Checar o opt-out antes pagaria essa
    consulta para todo candidato, inclusive os que nem estao devidos -- e a
    premissa que justifica consultar por candidato em vez de juntar na query
    (comentario abaixo) e que o conjunto que sobra depois do primeiro corte e
    pequeno. Invertida, essa premissa deixa de valer.

    O opt-out e consultado por candidato, e nao juntado na consulta:
    `esta_em_optout` e a unica implementacao daquele fato, e escreve-lo uma
    segunda vez em SQL criaria duas fontes que divergem em silencio -- o
    defeito que a TEC-146 gastou uma card inteira consertando. O preco e uma
    consulta por candidato devido, e esses sao poucos por construcao: so quem
    tem temperatura, calou ha mais de duas horas, ainda nao esgotou e tem
    tentativa vencida agora.

    **A conversa silenciada NAO e checada, e o criterio de aceite pede.** O
    estado nao existe -- e a TEC-179, e nada no produto o produz hoje. Quando
    ela existir, o predicado entra nesta mesma lista de guardas, ao lado do
    opt-out. Lacuna declarada.

    Um `registrar_followup` que devolve `None` significa que outra varredura
    chegou primeiro (o `ON CONFLICT DO NOTHING` absorveu). Nao e erro e nao
    entra na contagem.

    Tudo numa transacao so: a varredura nao tem efeito externo, entao nao ha o
    risco que faz o `sweep_stalled` soltar os locks antes do I/O de rede.
    """
    session_factory = ctx["session_factory"]
    agora = datetime.now(UTC)
    gravadas = 0

    async with session_factory() as session:
        candidatos = await candidatos_a_followup(session, agora=agora, limite=limite)

        for candidato in candidatos:
            tentativa = tentativa_devida(
                temperatura=candidato.temperatura,
                ultima_fala=candidato.ancora_em,
                ja_disparada=candidato.ja_disparada,
                agora=agora,
            )
            if tentativa is None:
                continue

            if await esta_em_optout(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
            ):
                continue

            devido_em = candidato.ancora_em + CADENCIA[candidato.temperatura][tentativa - 1]
            linha = await registrar_followup(
                session, candidato=candidato, tentativa=tentativa, devido_em=devido_em
            )
            if linha is None:
                continue

            gravadas += 1
            # O texto do lead nao entra: a regra de PII que
            # `moderacao.entrada_bloqueada` respeita vale igual aqui.
            log.info(
                "followup.devido",
                channel=candidato.channel,
                tentativa=tentativa,
                temperatura=candidato.temperatura.value,
                ancora_em=candidato.ancora_em.isoformat(),
                devido_em=devido_em.isoformat(),
            )

        await session.commit()

    return gravadas
