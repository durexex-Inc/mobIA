"""A funcao que modera a entrada e marca, isolada dos tres chamadores.

Unitario e nao integracao: o que se prova aqui e a sequencia de decisoes --
fail-open devolve None, liberado nao marca, bloqueado marca com a categoria
certa. Quem grava e `marcar_bloqueada`, que ja tem cobertura propria de
integracao; aqui ela e um espiao, porque o ponto e QUANDO ela e chamada.
"""

from uuid import uuid4

import pytest

from mobia.domain.messages import bloqueio
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    Veredito,
)


class _ModeradorFalso:
    def __init__(self, veredito=None, erro=None):
        self._veredito = veredito
        self._erro = erro
        self.chamadas: list = []

    async def moderar(self, texto, *, direcao):
        self.chamadas.append((texto, direcao))
        if self._erro is not None:
            raise self._erro
        return self._veredito


@pytest.fixture
def espiao_de_marca(monkeypatch):
    """Substitui `marcar_bloqueada` no modulo por um espiao que registra."""
    chamadas: list = []

    async def espiao(session_factory, message_id, *, channel, conversation_key, categoria):
        chamadas.append(
            {
                "message_id": message_id,
                "channel": channel,
                "conversation_key": conversation_key,
                "categoria": categoria,
            }
        )

    monkeypatch.setattr(bloqueio, "marcar_bloqueada", espiao)
    return chamadas


async def _chamar(moderador, corpo="qualquer coisa"):
    return await bloqueio.moderar_entrada_e_marcar(
        None,
        moderador,
        message_id=uuid4(),
        channel="whatsapp",
        conversation_key="conversa-1",
        corpo=corpo,
    )


async def test_provedor_indisponivel_devolve_none_e_nao_marca(espiao_de_marca) -> None:
    """Fail-open: `None` e o unico valor que diz "nao deu para moderar".

    Devolver um `Veredito(bloqueado=False)` aqui seria transformar um
    moderador caido num moderador que libera, que e exatamente o que o
    `ModeracaoIndisponivel` existe para impedir.
    """
    moderador = _ModeradorFalso(erro=ModeracaoIndisponivel("provedor fora"))

    assert await _chamar(moderador) is None
    assert espiao_de_marca == []


async def test_liberado_devolve_o_veredito_e_nao_marca(espiao_de_marca) -> None:
    moderador = _ModeradorFalso(Veredito(bloqueado=False, motivo="ok"))

    veredito = await _chamar(moderador)

    assert veredito is not None
    assert veredito.bloqueado is False
    assert espiao_de_marca == []


async def test_bloqueado_marca_com_a_categoria_do_veredito(espiao_de_marca) -> None:
    moderador = _ModeradorFalso(
        Veredito(bloqueado=True, motivo="discurso", categoria="DISCRIMINACAO")
    )

    veredito = await _chamar(moderador)

    assert veredito is not None and veredito.bloqueado is True
    assert len(espiao_de_marca) == 1
    assert espiao_de_marca[0]["categoria"] == "DISCRIMINACAO"
    assert espiao_de_marca[0]["channel"] == "whatsapp"
    assert espiao_de_marca[0]["conversation_key"] == "conversa-1"


async def test_bloqueado_sem_categoria_cai_no_outro(espiao_de_marca) -> None:
    """`ModeradorPort` e um Protocol: um adaptador futuro pode devolver
    bloqueado sem categoria, e a coluna e `not null`. A alternativa seria a
    marca estourar por causa de um campo de auditoria.
    """
    moderador = _ModeradorFalso(Veredito(bloqueado=True, motivo="sem categoria"))

    await _chamar(moderador)

    assert espiao_de_marca[0]["categoria"] == CATEGORIA_OUTRO


async def test_modera_com_direcao_de_entrada_e_so_o_corpo() -> None:
    """A direcao nao e parametro de quem chama: esta funcao e so de ENTRADA.

    E o moderador recebe o corpo e nada mais -- nenhum contexto, nenhum
    identificador. Um refactor que passasse a conversa inteira mudaria o que
    o provedor julga sem que nenhuma assercao de comportamento reclamasse.
    """
    moderador = _ModeradorFalso(Veredito(bloqueado=False, motivo="ok"))

    await _chamar(moderador, corpo="o texto exato")

    assert moderador.chamadas == [("o texto exato", Direcao.ENTRADA)]
