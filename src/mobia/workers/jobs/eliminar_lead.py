"""O job que executa a eliminacao pedida pelo titular. TEC-207, D4.

`DELETE /leads/{lead_id}/dados-pessoais` enfileira este job com o
`solicitacao_id` que ela mesma registrou (ou reaproveitou) -- quem decide se
ha o que fazer e `eliminacao.anonimizar`, que e no-op e loga quando a
solicitacao ja nao esta ABERTA ou nao e de ELIMINACAO. Ver o docstring dela.
"""

import uuid
from typing import Any

from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.titular.eliminacao import anonimizar

ELIMINAR_LEAD_JOB = "eliminar_lead"


async def eliminar_lead(ctx: dict[str, Any], solicitacao_id: str) -> None:
    await anonimizar(
        ctx["session_factory"],
        armazem_da_config(ctx["settings"]),
        solicitacao_id=uuid.UUID(solicitacao_id),
    )
