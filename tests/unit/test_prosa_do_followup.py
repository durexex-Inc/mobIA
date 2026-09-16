"""Testes da abertura que o modelo escreve para o followup.

TEC-184, Task 5. Nenhum destes testes toca a rede nem o banco: o provedor
entra por `monkeypatch` sobre `get_client` (mesmo molde de
`tests/unit/test_handoff_redator.py`) e a sessao e um duble com o unico
metodo que `ler_resumo` chama.

`ler_resumo` de verdade roda aqui -- o que e dublado e a LINHA que ela
encontra, cifrada com a mesma chave e o mesmo AAD de producao. Dublar a
funcao inteira deixaria de exercitar a decifragem, que e o caminho por onde
o resumo chega ao prompt.
"""

import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.context.models import ConversationSummary, aad_do_resumo
from mobia.domain.followup import prosa as prosa_mod
from mobia.domain.followup.mensagem import QuedaDePreco
from mobia.domain.followup.prosa import (
    MAX_TOKENS_DA_ABERTURA,
    SISTEMA_DO_FOLLOWUP,
    redigir_abertura,
)
from mobia.infra.crypto import encrypt

CANAL = "whatsapp"
CONVERSA = "5548999990000"

FICHA = Ficha(
    id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=51646430,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial="churrasqueira e mobiliado",
    foto=None,
)

QUEDA = QuedaDePreco(
    imovel_id=FICHA.id,
    preco_antes_centavos=62_000_000,
    preco_agora_centavos=FICHA.preco_centavos,
)

# Se qualquer uma destas aparecer em caplog.text, o boundary vazou o que a
# guarda impediu de sair ou o resumo que gerou a prosa. Mesmo molde de
# tests/unit/test_handoff_redator.py.
SENTINELA_RESUMO = "SENTINELA-RESUMO o lead mora na Rua das Palmeiras"
SENTINELA_PROSA = "SENTINELA-PROSA vi que voce procurava perto da praia"


class _Sessao:
    """O que `redigir_abertura` toca numa sessao: `get` e, no caminho de
    falha, `rollback`.

    `rollback` mora na base porque as tres sessoes o expoem pela mesma razao:
    o `except` de `redigir_abertura` desfaz a transacao antes de devolver
    `None`, e sem isso o contrato "nunca levanta" valeria aqui e mentiria uma
    chamada adiante, no `PendingRollbackError` de quem emprestou a sessao.
    `rollbacks` conta para o teste poder afirmar que ele aconteceu.
    """

    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessaoSemResumo(_Sessao):
    """Duble da sessao: `ler_resumo` so chama `get`, e sem linha devolve None."""

    async def get(self, *_args: object, **_kwargs: object) -> None:
        return None


class _SessaoComResumo(_Sessao):
    """A linha existe e esta cifrada como em producao."""

    def __init__(self, texto: str) -> None:
        super().__init__()
        self._texto = texto

    async def get(self, _modelo: object, chave: tuple[str, str], **_kwargs: object) -> object:
        canal, conversa = chave
        return ConversationSummary(
            channel=canal,
            conversation_key=conversa,
            resumo=encrypt(self._texto, aad_do_resumo(canal, conversa)),
            watermark_created_at=None,
            watermark_message_id=uuid.uuid4(),
            mensagens_cobertas=12,
            modelo="claude-sonnet-5",
        )


class _SessaoQueLevanta(_Sessao):
    async def get(self, *_args: object, **_kwargs: object) -> None:
        raise ConnectionResetError("[WinError 64] a conexao caiu")


def _resposta(texto: str | None, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)] if texto is not None else [],
        usage=SimpleNamespace(input_tokens=700, output_tokens=30),
        stop_reason=stop_reason,
    )


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic: so o que `redigir_abertura` toca."""

    def __init__(self, *respostas: object) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(side_effect=list(respostas)))


def _instalar(monkeypatch: pytest.MonkeyPatch, *respostas: object) -> _ClienteFalso:
    cliente = _ClienteFalso(*respostas)
    monkeypatch.setattr(prosa_mod, "get_client", lambda: cliente)
    return cliente


async def _redigir(
    sessao: Any,
    *,
    ficha: Ficha | None = FICHA,
    queda: QuedaDePreco | None = None,
) -> str | None:
    return await redigir_abertura(
        sessao,
        channel=CANAL,
        conversation_key=CONVERSA,
        ficha=ficha,
        queda=queda,
    )


def test_o_prompt_proibe_numero_e_saudacao_vazia() -> None:
    """Os dois riscos desta chamada, e os dois estao no prompt de proposito:
    numero inventado com cara de fato, e "oi, tudo bem?" que a RN-13.2 proibe.
    """
    baixo = SISTEMA_DO_FOLLOWUP.lower()
    assert "preco" in baixo or "numero" in baixo
    assert "saudacao" in baixo or "oi, tudo bem" in baixo


async def test_prosa_que_e_so_saudacao_vira_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """D6: o que a validacao descarta e a PROSA, nunca o envio -- o fato sai
    sozinho e a mensagem nunca fica vazia."""
    _instalar(monkeypatch, _resposta("Oi, tudo bem?"))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_saudacao_com_acento_tambem_e_saudacao(monkeypatch: pytest.MonkeyPatch) -> None:
    """O modelo escreve portugues com acento -- so o codigo deste repo e que
    escreve sem. Uma guarda que comparasse bytes crus deixaria passar
    exatamente a forma mais provavel."""
    _instalar(monkeypatch, _resposta("Olá! Tudo bem com você?"))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_prosa_que_cita_imovel_de_fora_vira_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5: a guarda de citacao da TEC-161 passa a valer aqui. O imovel da
    novidade existe por construcao; o que sobra e o modelo inventar um
    segundo na abertura."""
    _instalar(monkeypatch, _resposta("Lembrei de voce quando vi o AP-9999 na Lagoa."))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_preco_inventado_na_abertura_vira_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A outra metade da guarda da TEC-161. O prompt proibe numero; quando o
    modelo desobedece, quem barra e `divergencias_de`, e nao a boa vontade."""
    _instalar(monkeypatch, _resposta("Apareceu uma oportunidade por R$ 250.000 para voce."))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_falha_da_chamada_vira_none_e_nao_excecao(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prosa e ornamento: uma falha nela nao pode custar ao lead o follow-up
    inteiro. E a mesma postura da porta de busca, que devolve `erro` no
    tool_result em vez de derrubar o turno."""
    _instalar(monkeypatch, RuntimeError("o provedor caiu"))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_falha_ao_ler_o_resumo_vira_none_e_nao_excecao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leitura do resumo esta dentro da mesma guarda que a chamada. Um
    `ConnectionResetError` -- rotineiro neste repo -- nao pode custar o
    follow-up, que nao depende do resumo para ter conteudo.

    **E a sessao volta USAVEL, nao so a funcao volta `None`.** Depois de um
    erro de statement a transacao fica desativada, e a proxima operacao de
    quem emprestou a sessao levantaria `PendingRollbackError` -- em
    `sweep_followups` a proxima e o `scalar` do `de`, e o candidato SEGUINTE
    morreria no `esta_em_optout`. Sem o `rollback`, o contrato "nunca levanta"
    seria verdade aqui e mentira uma chamada adiante."""
    _instalar(monkeypatch, _resposta("Vi que voce procurava perto da praia."))
    sessao = _SessaoQueLevanta()

    assert await _redigir(sessao) is None
    assert sessao.rollbacks == 1


async def test_parada_anormal_vira_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`max_tokens` corta a frase no meio e ela sai parecendo inteira. Mesma
    guarda de `handoff/resumo.py`, e aqui o desfecho e descartar, nao levantar."""
    _instalar(
        monkeypatch, _resposta("Vi que voce procurava um imovel com", stop_reason="max_tokens")
    )

    assert await _redigir(_SessaoSemResumo()) is None


async def test_texto_vazio_vira_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta("   "))

    assert await _redigir(_SessaoSemResumo()) is None


async def test_prosa_boa_volta_inteira(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta("Vi que voce procurava 3 quartos no Centro."))

    prosa = await _redigir(_SessaoSemResumo())

    assert prosa == "Vi que voce procurava 3 quartos no Centro."


async def test_nenhum_preco_do_imovel_chega_ao_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A regra que esta card firma pela terceira vez (D7 da TEC-265, D8 da
    TEC-154): preco DO IMOVEL nao passa pelo modelo. Confere o payload
    inteiro -- system e turno --, nas tres formas em que o preco poderia
    escapar: centavos, reais e o texto ja formatado.

    **"Do imovel" e o limite exato, e a sessao sem resumo e o que o isola.**
    O turno leva tambem `resumo.texto`, e o resumo carrega rotineiramente o
    orcamento que o LEAD declarou, em reais -- "nenhum numero de preco passa
    pelo modelo" seria mais forte do que o codigo garante. O que este teste
    prende e o preco do imovel: o de hoje, da ficha, e o antigo, da queda."""
    cliente = _instalar(monkeypatch, _resposta("Lembrei de voce ao ver uma novidade na Lagoa."))

    await _redigir(_SessaoSemResumo(), ficha=FICHA, queda=QUEDA)

    enviado = str(cliente.messages.create.await_args.kwargs)
    for proibido in ("51646430", "516464", "516.464", "62000000", "620000", "620.000"):
        assert proibido not in enviado


async def test_o_resumo_da_conversa_entra_no_turno(monkeypatch: pytest.MonkeyPatch) -> None:
    """D4: o contexto de conversa que a card pede e o resumo ja gravado em
    `conversation_summaries` -- nao ha segunda montagem de contexto."""
    cliente = _instalar(monkeypatch, _resposta("Lembrei de voce ao ver uma novidade na Lagoa."))

    await _redigir(_SessaoComResumo("o lead procura 3 quartos perto da praia"))

    enviado = str(cliente.messages.create.await_args.kwargs)
    assert "o lead procura 3 quartos perto da praia" in enviado


async def test_sem_resumo_a_abertura_ainda_e_escrita(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conversa sem resumo gravado e o caso comum de lead que falou pouco --
    e justamente quem a cadencia alcanca primeiro. Sem resumo a chamada
    continua valendo: sobra a novidade."""
    cliente = _instalar(monkeypatch, _resposta("Lembrei de voce ao ver uma novidade na Lagoa."))

    prosa = await _redigir(_SessaoSemResumo())

    assert prosa == "Lembrei de voce ao ver uma novidade na Lagoa."
    assert cliente.messages.create.await_count == 1


async def test_o_teto_de_tokens_e_o_desta_chamada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma frase. O teto nao e o do turno normal -- e o que impede uma
    resposta longa de pagar tokens que a regra dos 600 caracteres corta
    depois."""
    cliente = _instalar(monkeypatch, _resposta("Lembrei de voce ao ver uma novidade na Lagoa."))

    await _redigir(_SessaoSemResumo())

    assert cliente.messages.create.await_args.kwargs["max_tokens"] == MAX_TOKENS_DA_ABERTURA


async def test_o_log_carrega_metrica_e_nunca_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nem o resumo que entrou nem a prosa que saiu. O mesmo criterio de
    `citacao.py`: os valores divergentes entram no log, o texto nunca."""
    _instalar(monkeypatch, _resposta(SENTINELA_PROSA))

    with caplog.at_level(logging.INFO):
        await _redigir(_SessaoComResumo(SENTINELA_RESUMO))

    assert "followup.abertura_redigida" in caplog.text
    assert SENTINELA_RESUMO not in caplog.text
    assert SENTINELA_PROSA not in caplog.text


async def test_a_abertura_do_followup_nao_manda_teto_proprio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fica no piso de construcao do cliente, e isso e deliberado (TEC-228).

    Mesma razao de `handoff/resumo.py`: esta chamada nao disputa o
    `job_timeout` do turno, e ninguem a mediu. O que a governa e outro teto --
    o `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS` da varredura, cuja conta cita o
    `TIMEOUT_SEGUNDOS`/`MAX_TENTATIVAS` deste cliente pelo nome.

    Por isso a ausencia e testada: um `timeout=` aqui mudaria uma conta que
    mora noutro arquivo, e o comentario de la avisa exatamente disso.
    """
    cliente = _instalar(monkeypatch, _resposta("Vi que voce procurava 3 quartos."))

    await _redigir(_SessaoSemResumo())

    assert "timeout" not in cliente.messages.create.call_args.kwargs
