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


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("BLOQUEAR.", True),
        ("LIBERAR\n.", False),
        ("**LIBERAR**", False),
        ("  bloquear  ", True),
    ],
)
async def test_pontuacao_em_volta_do_veredito_nao_perde_o_turno(
    monkeypatch: pytest.MonkeyPatch, bruto: str, esperado: bool
) -> None:
    """Tolerante na forma, rigido no conteudo.

    O protocolo pede uma palavra sem pontuacao, e o modelo quase sempre
    obedece -- mas "quase" nao serve aqui. Um ponto final que escapa vira
    `ModeracaoIndisponivel`, e na saida a indisponibilidade nao e inofensiva:
    propaga, a linha vira FAILED, o sweeper roda o turno inteiro de novo
    pagando `classificar` outra vez ate `sweep_max_attempts`, e depois disso a
    linha fica em FAILED para sempre. O lead nao recebe nada -- silencio, o
    desfecho que este repositorio trata como o pior de todos. Trocar um turno
    por um ponto final e o negocio errado.
    """
    cliente = ClienteFalso(RespostaFalsa(bruto))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is esperado


@pytest.mark.parametrize("bruto", ["BLOQUEAR LIBERAR", "talvez", "LIBERAR se quiser", ""])
async def test_a_tolerancia_de_forma_nao_afrouxa_o_conteudo(
    monkeypatch: pytest.MonkeyPatch, bruto: str
) -> None:
    """Limpar as pontas nao pode virar "achar a palavra em qualquer lugar".

    A garantia que nao pode ceder e a de que o desconhecido nunca vira
    liberado. Duas palavras nao sao um veredito -- nao da para saber qual
    delas o modelo quis --, e uma resposta que explica em vez de decidir
    tambem nao e. Se a normalizacao passasse a procurar a palavra dentro de
    uma frase, "nao vou BLOQUEAR" e "BLOQUEAR LIBERAR" viravam veredito, e o
    moderador confuso viraria moderador desligado.
    """
    cliente = ClienteFalso(RespostaFalsa(bruto))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


def test_o_cliente_da_moderacao_e_construido_com_o_teto_curto(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O teste acima relaciona constantes; este prova que elas chegam ao cliente.

    Sem ele, apagar `timeout=` e `max_retries=` de `get_moderation_client()`
    passa na suite inteira: as constantes continuam la, a relacao entre elas
    continua valendo, e o cliente volta ao default do SDK -- 10 min com
    retentativa interna, ou seja o pior caso que o argumento de custo deste
    card existe para evitar, com o card inteiro parecendo intacto. E o mesmo
    padrao de `test_cliente_falha_tipado_antes_de_o_arq_cancelar`, em
    `tests/unit/test_config.py`, para o cliente do turno.
    """
    from mobia.infra.moderacao import (
        MAX_TENTATIVAS_DA_MODERACAO,
        TIMEOUT_DA_MODERACAO_SEGUNDOS,
        get_moderation_client,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    cliente = get_moderation_client()

    assert cliente.timeout == TIMEOUT_DA_MODERACAO_SEGUNDOS
    assert cliente.max_retries == MAX_TENTATIVAS_DA_MODERACAO


def test_o_cliente_da_moderacao_recusa_subir_sem_chave(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Chave ausente falha aqui, com mensagem util, e nao no meio de um turno.

    Mesma guarda que `get_client()` tem desde a TEC-127, e pelo mesmo motivo --
    so que este cliente e chamado na primeira linha do turno, onde a falha nao
    tipada seria confundida com "o moderador caiu" e trataria configuracao
    ausente como indisponibilidade passageira.
    """
    from mobia.app.config import ConfiguracaoInsegura
    from mobia.infra.moderacao import get_moderation_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ConfiguracaoInsegura, match="ANTHROPIC_API_KEY"):
        get_moderation_client()
