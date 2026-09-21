"""O processador que poe a pilha no log e deixa a mensagem de fora.

Os testes chamam `_sanear_traceback` direto, sem o pipeline: o que se
prova aqui e a FORMA do texto produzido. O acoplamento com o resto dos
processadores e provado em `test_logging_mascara.py`.
"""

import sys

import pytest

from mobia.app.logging import _ELO_CAUSA, _ELO_CONTEXTO, _sanear_traceback


def _capturar(modo: str) -> tuple:
    """Levanta uma cadeia de duas excecoes no modo pedido e devolve o exc_info.

    A mensagem de cada uma carrega uma agulha reconhecivel, para os testes
    poderem afirmar que ela NAO sobreviveu.
    """

    def fundo() -> None:
        raise ValueError("fala do lead: quero 3 quartos, tel 5511987654321")

    try:
        if modo == "context":
            try:
                fundo()
            except ValueError:
                raise RuntimeError("wrapper implicito")  # noqa: B904
        else:
            try:
                fundo()
            except ValueError as causa:
                if modo == "cause":
                    raise RuntimeError("DETAIL: Failing row contains (...)") from causa
                else:  # suppress
                    raise RuntimeError("wrapper limpo") from None
    except RuntimeError:
        return sys.exc_info()
    raise AssertionError("o helper tem de levantar")


def _sanear(exc_info: object) -> str:
    evento = _sanear_traceback(None, "error", {"event": "e", "exc_info": exc_info})
    return evento["exception"]


@pytest.mark.parametrize("modo", ["cause", "context", "suppress"])
def test_a_mensagem_da_excecao_nao_sobrevive(modo: str) -> None:
    """Nenhum dos tres modos de encadeamento deixa passar texto de mensagem."""
    saneado = _sanear(_capturar(modo))

    assert "quero 3 quartos" not in saneado
    assert "5511987654321" not in saneado
    assert "Failing row contains" not in saneado
    assert "wrapper" not in saneado


@pytest.mark.parametrize("modo", ["cause", "context", "suppress"])
def test_o_tipo_e_a_pilha_sobrevivem(modo: str) -> None:
    """O que torna o erro diagnosticavel fica: tipo qualificado e frames."""
    saneado = _sanear(_capturar(modo))

    assert "RuntimeError" in saneado
    assert "test_sanear_traceback.py" in saneado
    assert "in _capturar" in saneado


def test_a_causa_explicita_aparece_com_o_elo_do_python() -> None:
    """`raise ... from exc` produz duas secoes e o elo de causa direta."""
    saneado = _sanear(_capturar("cause"))

    assert _ELO_CAUSA in saneado
    assert _ELO_CONTEXTO not in saneado
    assert saneado.count("Traceback (most recent call last):") == 2
    assert "ValueError" in saneado


def test_o_contexto_implicito_aparece_com_o_outro_elo() -> None:
    """Excecao levantada DENTRO de um except traz a anterior, com o elo dela."""
    saneado = _sanear(_capturar("context"))

    assert _ELO_CONTEXTO in saneado
    assert _ELO_CAUSA not in saneado
    assert saneado.count("Traceback (most recent call last):") == 2


def test_from_none_esconde_a_anterior() -> None:
    """`__suppress_context__` existe para esconder, e e respeitado."""
    saneado = _sanear(_capturar("suppress"))

    assert saneado.count("Traceback (most recent call last):") == 1
    assert "ValueError" not in saneado


def test_a_linha_de_codigo_fonte_fica_de_fora() -> None:
    """Arquivo, linha e funcao localizam o frame; o fonte esta versionado."""
    saneado = _sanear(_capturar("cause"))

    assert "raise RuntimeError" not in saneado
    assert "fundo()" not in saneado


def test_cadeia_ciclica_nao_pendura() -> None:
    """Quem corta o ciclo e o `TracebackException`, nao uma guarda nossa.

    Isto e garantia de terceiro da qual passamos a depender: sem ela, o laco
    da travessia nao terminaria. O teste existe para a dependencia ficar
    fixada, e nao para provar codigo nosso.
    """
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a

    saneado = _sanear((type(a), a, None))

    assert saneado.count("Traceback (most recent call last):") <= 3


def test_excecao_passada_como_instancia() -> None:
    """`exc_info=<excecao>` e uma das tres formas que o structlog aceita."""
    try:
        raise KeyError("conversation_key")
    except KeyError as erro:
        saneado = _sanear(erro)

    assert "KeyError" in saneado
    assert "conversation_key" not in saneado


def test_sem_excecao_nao_cria_a_chave() -> None:
    """`exc_info` falso ou ausente nao inventa chave `exception` no evento."""
    evento = _sanear_traceback(None, "info", {"event": "e", "exc_info": False})

    assert "exception" not in evento
    assert "exc_info" not in evento
