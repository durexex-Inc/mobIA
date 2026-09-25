import uuid
from typing import Any

from mobia.domain.agendamento.agendador import (
    AgendadorDeAvisosArq,
    AgendadorDeAvisosNoop,
)

# As constantes sao as dos modulos de dominio, donos unicos delas (ver o
# comentario em agendador.py) -- afirmar contra elas, e nao contra as copias
# importadas, e o que faz este teste pegar uma redefinicao divergente se
# alguem reintroduzir uma.
from mobia.domain.agendamento.cancelamento import AVISAR_CANCELAMENTO_JOB
from mobia.domain.agendamento.confirmacao import AVISAR_CONFIRMACAO_JOB
from mobia.workers.jobs.avisar_cancelamento import avisar_cancelamento
from mobia.workers.jobs.avisar_confirmacao import avisar_confirmacao


class _PoolFalso:
    """Registra a chamada em vez de falar com o Redis. Mesmo papel do
    espiao que os outros testes de porta de agendamento usam."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.chamadas.append((args, kwargs))


async def test_a_confirmacao_enfileira_com_job_id_fixo_por_agendamento() -> None:
    pool = _PoolFalso()
    agendamento_id = uuid.uuid4()

    await AgendadorDeAvisosArq(pool).confirmacao(agendamento_id)

    assert pool.chamadas == [
        (
            (AVISAR_CONFIRMACAO_JOB, str(agendamento_id)),
            {"_job_id": f"confirmacao:{agendamento_id}"},
        )
    ]


async def test_o_cancelamento_enfileira_com_job_id_fixo_por_agendamento() -> None:
    pool = _PoolFalso()
    agendamento_id = uuid.uuid4()

    await AgendadorDeAvisosArq(pool).cancelamento(agendamento_id)

    assert pool.chamadas == [
        (
            (AVISAR_CANCELAMENTO_JOB, str(agendamento_id)),
            {"_job_id": f"cancelamento:{agendamento_id}"},
        )
    ]


async def test_os_dois_avisos_do_mesmo_agendamento_nao_se_engolem() -> None:
    """TEC-372: prefixos diferentes, senao o cancelamento some.

    Um agendamento confirmado e depois cancelado gera os dois enqueues. Com
    um `_job_id` comum, o segundo seria engolido pelo primeiro e o corretor
    saberia da visita e nunca do cancelamento dela.
    """
    pool = _PoolFalso()
    agendamento_id = uuid.uuid4()
    agendador = AgendadorDeAvisosArq(pool)

    await agendador.confirmacao(agendamento_id)
    await agendador.cancelamento(agendamento_id)

    ids = [kwargs["_job_id"] for _, kwargs in pool.chamadas]
    assert ids == [f"confirmacao:{agendamento_id}", f"cancelamento:{agendamento_id}"]
    assert len(set(ids)) == 2


async def test_agendador_noop_nao_faz_nada() -> None:
    assert await AgendadorDeAvisosNoop().confirmacao(uuid.uuid4()) is None
    assert await AgendadorDeAvisosNoop().cancelamento(uuid.uuid4()) is None


def test_nome_da_corrotina_do_job_e_o_contrato_com_o_agendador() -> None:
    """O ARQ registra o job pelo `__name__` da funcao -- ver o docstring do job."""
    assert avisar_confirmacao.__name__ == AVISAR_CONFIRMACAO_JOB
    assert avisar_cancelamento.__name__ == AVISAR_CANCELAMENTO_JOB
