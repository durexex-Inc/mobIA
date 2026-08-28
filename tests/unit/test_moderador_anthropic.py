from typing import Any

import pytest

from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel


class RespostaFalsa:
    """Molda o que o SDK devolve, sem tocar a rede."""

    def __init__(self, texto: str, stop_reason: str = "end_turn") -> None:
        class Bloco:
            type = "text"

            def __init__(self, t: str) -> None:
                self.text = t

        self.content = [Bloco(texto)]
        self.stop_reason = stop_reason


class ClienteFalso:
    def __init__(self, resposta: Any = None, erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.kwargs: dict[str, Any] = {}
        self.messages = self

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.erro is not None:
            raise self.erro
        return self.resposta


def _moderador(monkeypatch: pytest.MonkeyPatch, cliente: ClienteFalso):
    from mobia.infra import moderacao

    monkeypatch.setattr(moderacao, "get_moderation_client", lambda: cliente)
    return moderacao.ModeradorAnthropic()


async def test_bloquear_vira_veredito_bloqueado(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True


async def test_liberar_vira_veredito_liberado(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is False


async def test_resposta_fora_do_protocolo_e_indisponibilidade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Palavra que nao e nenhuma das duas nao pode virar "liberado".

    Interpretar o desconhecido como liberado transforma um moderador confuso em
    um moderador desligado, e desligado em silencio -- que e o modo de falha
    que este subsistema existe para nao ter.
    """
    cliente = ClienteFalso(RespostaFalsa("talvez"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


async def test_parada_anormal_e_indisponibilidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Veredito com parada anormal nao e veredito, mesmo que a palavra sirva.

    O texto aqui e `BLOQUEAR` inteiro, e nao truncado, de proposito: com uma
    palavra invalida o `else` final do parser reprovaria sozinho, e o teste
    passaria mesmo sem a checagem de `stop_reason` -- nao guardaria nada. Com a
    palavra valida, so a checagem de parada pode reprovar, e remove-la faz este
    teste falhar.
    """
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR", stop_reason="max_tokens"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


async def test_erro_do_provedor_vira_indisponibilidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qualquer falha da chamada e "nao deu para moderar", nunca "liberado"."""
    cliente = ClienteFalso(erro=TimeoutError("estourou"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)


async def test_a_direcao_escolhe_o_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se a direcao nao trocar o prompt, ela e decoracao e o criterio da saida
    (mais estrito, porque e a empresa falando) nunca e aplicado.
    """
    from mobia.infra.moderacao import SISTEMA_DA_ENTRADA, SISTEMA_DA_SAIDA

    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    moderador = _moderador(monkeypatch, cliente)

    await moderador.moderar("x", direcao=Direcao.ENTRADA)
    assert cliente.kwargs["system"] == SISTEMA_DA_ENTRADA

    await moderador.moderar("x", direcao=Direcao.SAIDA)
    assert cliente.kwargs["system"] == SISTEMA_DA_SAIDA
    assert SISTEMA_DA_ENTRADA != SISTEMA_DA_SAIDA


def test_o_cliente_da_moderacao_tem_teto_proprio_e_nao_retenta() -> None:
    """O cliente do turno tem pior caso de 120s por chamada (60s x 2 tentativas)
    contra um `job_timeout` de 240 que o turno ja estoura. Moderar com o mesmo
    cliente somaria 240s; com teto de 5s e sem retentativa, soma 10s.
    """
    from mobia.infra.anthropic import MAX_TENTATIVAS, TIMEOUT_SEGUNDOS
    from mobia.infra.moderacao import (
        MAX_TENTATIVAS_DA_MODERACAO,
        TIMEOUT_DA_MODERACAO_SEGUNDOS,
    )

    assert TIMEOUT_DA_MODERACAO_SEGUNDOS < TIMEOUT_SEGUNDOS
    assert MAX_TENTATIVAS_DA_MODERACAO == 0
    assert MAX_TENTATIVAS_DA_MODERACAO < MAX_TENTATIVAS
    pior_caso = TIMEOUT_DA_MODERACAO_SEGUNDOS * (1 + MAX_TENTATIVAS_DA_MODERACAO)
    assert pior_caso * 2 <= 15
