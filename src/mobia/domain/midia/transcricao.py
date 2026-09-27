"""A porta da transcricao de audio. TEC-131, D2.

O dominio conhece so isto; o adaptador da Whisper mora em
`infra/transcricao.py`, e os testes usam o `TranscritorFake` do conftest.
"""

from typing import NamedTuple, Protocol


class TranscricaoIndisponivel(Exception):
    """O provedor nao transcreveu: rede, 5xx, 4xx ou chave ausente.

    Uma classe so para todas, de proposito: o job nao retenta nenhuma delas
    (D2 -- o lead esta esperando), entao distinguir so serviria ao log, e o log
    leva o nome do tipo original.
    """


class Transcricao(NamedTuple):
    texto: str
    # A duracao que o provedor mediu, quando ele a devolve. E a segunda
    # conferencia do limite, para os formatos em que `duracao_do_ogg_opus` nao
    # mede (D2, passo 6).
    duracao_segundos: float | None


class TranscritorPort(Protocol):
    async def transcrever(self, dados: bytes, extensao: str) -> Transcricao: ...
