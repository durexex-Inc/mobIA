"""O job que fecha por inatividade a conversa parada ha 30 dias. TEC-130, RN-02.3."""

from datetime import UTC, datetime
from typing import Any

from mobia.domain.conversa.repositorio import encerrar_inativas

SWEEP_CONVERSAS_INATIVAS_JOB = "sweep_conversas_inativas"


async def sweep_conversas_inativas(ctx: dict[str, Any], limite: int = 500) -> int:
    """Fecha as vencidas e devolve quantas. Fino de proposito, como `sweep_sla`.

    **E fino pela mesma razao que `sweep_sla` e**: `encerrar_inativas` emite
    `conversa.encerrada` uma vez por conversa que fecha, entao o rastro desta
    passagem esta nas linhas do log e nao neste numero -- exatamente como
    `escalar_vencidos` loga um `handoff.escalado` por handoff. Um job fino sem
    essa linha por baixo seria uma varredura rodando as 3h sem deixar rastro
    nenhum, que e o que esta card corrigiu na rodada final de revisao.

    **Este job nao e o que faz a conversa nova comecar limpa.** Quem decide
    que a transcricao anterior nao entra no prompt e o turno, pelo relogio
    (D3 do desenho) -- aqui e so a escrituracao que a RN-02.3 pede: data e
    motivo. Uma passagem perdida atrasa o registro e nao muda uma linha do
    que o lead recebe.

    `datetime.now(UTC)` aqui, e nao no repositorio, pelo mesmo motivo que
    `situacao_da_conversa` recebe `agora` por parametro: e o que torna a
    janela testavel sem congelar relogio.
    """
    return await encerrar_inativas(ctx["session_factory"], agora=datetime.now(UTC), limite=limite)
