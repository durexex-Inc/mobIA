import uuid
from typing import Any

from mobia.domain.agendamento.agendador import (
    AgendadorDeConfirmacaoArq,
    AgendadorDeConfirmacaoNoop,
)

# A constante e a de confirmacao.py, o dono unico dela (ver o comentario em
# agendador.py) -- afirmar contra ela, e nao contra a copia importada, e o
# que faz este teste pegar uma redefinicao divergente se alguem reintroduzir
# uma.
from mobia.domain.agendamento.confirmacao import AVISAR_CONFIRMACAO_JOB
from mobia.workers.jobs.avisar_confirmacao import avisar_confirmacao


class _PoolFalso:
    """Registra a chamada em vez de falar com o Redis. Mesmo papel do
    espiao que os outros testes de porta de agendamento usam."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.chamadas.append((args, kwargs))


async def test_agendador_arq_enfileira_com_job_id_fixo_por_agendamento() -> None:
    pool = _PoolFalso()
    agendamento_id = uuid.uuid4()

    await AgendadorDeConfirmacaoArq(pool).agendar(agendamento_id)

    assert pool.chamadas == [
        (
            (AVISAR_CONFIRMACAO_JOB, str(agendamento_id)),
            {"_job_id": f"confirmacao:{agendamento_id}"},
        )
    ]


async def test_agendador_noop_nao_faz_nada() -> None:
    assert await AgendadorDeConfirmacaoNoop().agendar(uuid.uuid4()) is None


def test_nome_da_corrotina_do_job_e_o_contrato_com_o_agendador() -> None:
    """O ARQ registra o job pelo `__name__` da funcao -- ver o docstring do job."""
    assert avisar_confirmacao.__name__ == AVISAR_CONFIRMACAO_JOB
