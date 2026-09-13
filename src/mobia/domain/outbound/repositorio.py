"""Leitura das reservas de envio. TEC-275.

Arquivo proprio, e nao uma consulta dentro de `domain/agente`: a reserva e
fato do dominio de saida, e quem pergunta por ela (a continuacao da entrega)
nao devia precisar conhecer o schema de `outbound_dispatches`.
"""

import uuid
from typing import Any

from sqlalchemy import select

from mobia.domain.outbound.models import OutboundDispatch


async def kinds_reservados(session_factory: Any, *, message_id: uuid.UUID) -> frozenset[str]:
    """Os kinds que esta mensagem ja reservou.

    **Presenca significa "encerrado", nao "entregue".** A reserva e committada
    ANTES do efeito externo e so e liberada em `EnvioRetentavel` ou
    cancelamento (ver `GuardedOutbound.send`): falha permanente a MANTEM, de
    proposito, porque nao havera outra tentativa. Quem le isto para decidir o
    que reenviar esta perguntando "esta posicao ainda vai sair?", e a resposta
    certa para uma recusa permanente e nao.

    A linha que a recusa PERMANENTE deixa em `recomendacoes` e apagada na hora
    da recusa (`apagar_recomendacao_nao_entregue`, D8 da TEC-275), entao por
    esse lado a assimetria entre "reservado" e "entregue" nao vaza para a lista
    de pendentes.

    **Por outro lado ela vaza, e o comentario anterior dizia que nao.** A
    reserva tambem sobrevive quando a ficha NAO saiu: a liberacao do
    `EnvioRetentavel` pode falhar -- o proprio `send` antecipa deadlock e
    conexao caida e loga `outbound.liberacao_falhou` -- e um kill entre o
    commit da reserva e o `_deliver` deixa o mesmo estado. Nao houve recusa,
    entao nada apaga a linha, e quem le isto pula aquele kind achando que o
    lead viu a ficha: `ler_pendentes` devolve uma linha a mais e o ordinal do
    lead desloca. Fechar isso exige um fato de ENTREGA separado da reserva;
    enquanto ele nao existir, "reservado => encerrado" segue sendo o default,
    e este paragrafo e o preco dele.
    """
    async with session_factory() as session:
        linhas = await session.execute(
            select(OutboundDispatch.kind).where(OutboundDispatch.message_id == message_id)
        )
    return frozenset(linhas.scalars().all())
