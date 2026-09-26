"""O cursor e o limite da transcricao do lead, sem banco. TEC-193, D5."""

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.leads.consulta import FiltroInvalido
from mobia.domain.leads.transcricao import (
    LIMITE_MAXIMO_DA_TRANSCRICAO,
    LIMITE_PADRAO_DA_TRANSCRICAO,
    CursorDaTranscricao,
    decodificar_cursor_da_transcricao,
    validar_limite_da_transcricao,
)


def test_o_cursor_volta_igual() -> None:
    cursor = CursorDaTranscricao(
        em=datetime(2026, 9, 26, 10, 30, 0, 123456, tzinfo=UTC), message_id=uuid.uuid4()
    )
    assert decodificar_cursor_da_transcricao(cursor.codificar()) == cursor


@pytest.mark.parametrize(
    "texto",
    [
        "nao-e-base64!",
        base64.urlsafe_b64encode(b"nao e json").decode(),
        base64.urlsafe_b64encode(json.dumps({"t": "2026-09-26T10:00:00+00:00"}).encode()).decode(),
        # UUID fixo, e nao `uuid4()`: o valor entra no id do parametro, e com
        # `-n` cada worker do xdist coletaria um id diferente e recusaria a
        # execucao inteira ("Different tests were collected").
        base64.urlsafe_b64encode(
            json.dumps({"t": "ontem", "m": "888e6a31-7176-4b93-8f11-400f8cd00e11"}).encode()
        ).decode(),
        base64.urlsafe_b64encode(
            json.dumps({"t": "2026-09-26T10:00:00+00:00", "m": "nao-e-uuid"}).encode()
        ).decode(),
    ],
)
def test_cursor_corrompido_e_recusado(texto: str) -> None:
    """Recusado, e nao tratado como a pagina mais recente: quem chamou perdeu o
    lugar, e a tela empilharia o fim da conversa acima do que ja mostra."""
    with pytest.raises(FiltroInvalido):
        decodificar_cursor_da_transcricao(texto)


def test_cursor_sem_fuso_e_recusado() -> None:
    """Comparado a `timestamptz`, um instante ingenuo seria lido no fuso da
    sessao do banco -- e o cursor apontaria para outro lugar, em silencio."""
    texto = base64.urlsafe_b64encode(
        json.dumps({"t": "2026-09-26T10:00:00", "m": str(uuid.uuid4())}).encode()
    ).decode()
    with pytest.raises(FiltroInvalido):
        decodificar_cursor_da_transcricao(texto)


def test_o_limite_padrao_e_o_da_tec_324() -> None:
    assert LIMITE_PADRAO_DA_TRANSCRICAO == 100


@pytest.mark.parametrize("limite", [0, -1, LIMITE_MAXIMO_DA_TRANSCRICAO + 1])
def test_limite_fora_da_faixa_e_recusado(limite: int) -> None:
    with pytest.raises(FiltroInvalido):
        validar_limite_da_transcricao(limite)
