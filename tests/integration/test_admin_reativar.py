import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.admin.reativar import _executar, main
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout


async def test_reativacao_devolve_o_lead_ao_estado_respondivel(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Chama `_executar` direto, nao `main`.

    `main` chama `asyncio.run`, e este teste ja roda dentro de um loop -- ver
    a nota em `mobia.admin.reativar._executar`.
    """
    await registrar_optout(
        session_factory, channel="wa", conversation_key="5548999998888", message_id=uuid.uuid4()
    )

    codigo = await _executar(
        channel="wa", key="5548999998888", autor="Paulo M.", motivo="lead pediu por telefone"
    )

    assert codigo == 0
    assert await esta_em_optout(session, channel="wa", conversation_key="5548999998888") is False


def test_sem_motivo_o_comando_falha() -> None:
    """A RN-14.3 exige justificativa.

    `argparse` sai com SystemExit(2) em argumento obrigatorio ausente, e e o
    comportamento certo: sem justificativa a reativacao nao acontece.
    """
    with pytest.raises(SystemExit) as erro:
        main(["--channel", "wa", "--key", "5548999998888", "--autor", "Paulo M."])

    assert erro.value.code == 2
