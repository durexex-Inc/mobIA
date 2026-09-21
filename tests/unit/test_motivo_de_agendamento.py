"""O texto da falha de agendamento continua no log, agora por kwarg.

Saneado o traceback (TEC-293), estes tres sitios ficariam reduzidos a
`RedisError`. O texto e seguro aqui porque a unica coisa que estas chamadas
passam adiante e um UUID gerado por este projeto -- e a D3 da TEC-292.

Este arquivo exercita so `_agendar_resumo` (turno.py). O de
`workers/jobs/gerar_resumo.py` tem asserta propria em
`tests/integration/test_notificacao_job.py`
(test_falha_no_enfileiramento_nao_derruba_o_job_do_resumo). O terceiro,
`workers/jobs/process_message.py`, continua sem asserta propria em lugar
nenhum -- so `motivo=str(falha)` no codigo, sem teste que confira o texto.
"""

import logging
import uuid
from dataclasses import dataclass

from mobia.domain.agente.turno import _agendar_resumo


@dataclass
class _RegistroFalso:
    id: uuid.UUID
    criado: bool


class _AgendadorQueFalha:
    async def agendar(self, handoff_id: uuid.UUID) -> None:
        raise ConnectionError("Error 111 connecting to localhost:6379")


async def test_o_motivo_da_falha_de_agendamento_vai_para_o_log(caplog) -> None:
    registro = _RegistroFalso(id=uuid.uuid4(), criado=True)

    with caplog.at_level(logging.WARNING):
        await _agendar_resumo(_AgendadorQueFalha(), registro)

    assert "Error 111 connecting to localhost:6379" in caplog.text
    assert "resumo_handoff.nao_agendado" in caplog.text
