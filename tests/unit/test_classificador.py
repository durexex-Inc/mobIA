import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx2
import pytest
from anthropic import transform_schema

from mobia.domain.agente import classificador as classificador_mod
from mobia.domain.agente.classificador import (
    SCHEMA_DA_RESPOSTA,
    ClassificadorAnthropic,
    RespostaInvalida,
)
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.montagem import ContextoMontado

# Strings que nao podem, sob nenhuma circunstancia, sobreviver ao log nem a
# uma excecao. Se um destes valores aparecer em `caplog.text` ou em
# `str(erro.value)`, o boundary vazou conteudo do lead ou o prompt que o
# gerou -- exatamente o que o `process_message` da TEC-134 grava em
# `messages.last_error` e loga sem a mascara de PII.
TEXTO_DA_RESPOSTA = "SENTINELA-RESPOSTA o apartamento fica na Rua das Palmeiras"
SISTEMA_DO_PROMPT = "SENTINELA-SISTEMA instrucao confidencial do agente"
RESUMO_DO_PROMPT = "SENTINELA-RESUMO lead mora na Rua das Palmeiras, quer 2 quartos"

_DADOS_VALIDOS = {"intencao": "COMPRA", "confianca": 0.9, "resposta": TEXTO_DA_RESPOSTA}


def _contexto(*, resumo: str | None = RESUMO_DO_PROMPT) -> ContextoMontado:
    return ContextoMontado(
        sistema=SISTEMA_DO_PROMPT,
        resumo=resumo,
        literais=[],
        estado=None,
        tokens=100,
        degradado=False,
    )


def _bloco_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _resposta_falsa(
    *,
    texto: str | None,
    stop_reason: str = "end_turn",
    tokens_in: int = 4000,
    tokens_out: int = 200,
) -> SimpleNamespace:
    blocos = [_bloco_texto(texto)] if texto else []
    return SimpleNamespace(
        content=blocos,
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
        stop_reason=stop_reason,
    )


def _resposta_json(
    *,
    intencao: str = "COMPRA",
    confianca: object = 0.9,
    resposta: object = TEXTO_DA_RESPOSTA,
    stop_reason: str = "end_turn",
) -> SimpleNamespace:
    texto = json.dumps({"intencao": intencao, "confianca": confianca, "resposta": resposta})
    return _resposta_falsa(texto=texto, stop_reason=stop_reason)


class _ClienteFalso:
    """Dublê minimo do `AsyncAnthropic`: so o que `classificar` toca.

    Nao e um dublê de rede -- e um objeto Python comum que nunca abre socket.
    """

    def __init__(self, resposta: SimpleNamespace) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


def _instalar_cliente_falso(monkeypatch: pytest.MonkeyPatch, resposta: SimpleNamespace) -> None:
    """Troca o `get_client` que `classificador.py` enxerga, nao o global cacheado.

    Mesma tecnica de `test_resumo.py`: o modulo importa `get_client` por nome,
    entao substituir a referencia isola o teste do `@lru_cache` de
    `mobia.infra.anthropic.get_client` e da `ANTHROPIC_API_KEY`.
    """
    monkeypatch.setattr(classificador_mod, "get_client", lambda: _ClienteFalso(resposta))


async def test_classificar_devolve_intencao_confianca_e_resposta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resposta = _resposta_json(intencao="ALUGUEL", confianca=0.75, resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.intencao == Intencao.ALUGUEL
    assert resultado.confianca == pytest.approx(0.75)
    assert resultado.resposta == TEXTO_DA_RESPOSTA
    assert resultado.tokens_in == 4000
    assert resultado.tokens_out == 200


async def test_classificar_loga_metricas_sem_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`agente.turno_gerado` carrega numeros; nunca a resposta nem o prompt."""
    resposta = _resposta_json(resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO):
        await ClassificadorAnthropic().classificar(_contexto())

    assert "agente.turno_gerado" in caplog.text
    assert '"tokens_in"' in caplog.text
    assert '"tokens_out"' in caplog.text
    assert '"custo_usd"' in caplog.text
    assert '"latency_ms"' in caplog.text
    assert '"modelo"' in caplog.text

    # a parte que importa: nem a resposta, nem o sistema, nem o resumo
    # aparecem no log estruturado.
    assert TEXTO_DA_RESPOSTA not in caplog.text
    assert SISTEMA_DO_PROMPT not in caplog.text
    assert RESUMO_DO_PROMPT not in caplog.text


async def test_classificar_recusa_stop_reason_diferente_de_end_turn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    resposta = _resposta_falsa(texto=None, stop_reason="max_tokens")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "max_tokens" in str(erro.value)
    assert "agente.turno_gerado" not in caplog.text


async def test_classificar_recusa_resposta_vazia(monkeypatch: pytest.MonkeyPatch) -> None:
    resposta = _resposta_falsa(texto=None, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "vazia" in str(erro.value)


async def test_classificar_recusa_campo_resposta_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    resposta = _resposta_json(resposta="   ")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "vazio" in str(erro.value)


async def test_classificar_recusa_json_invalido_sem_ecoar_o_texto(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A resposta destinada ao lead nunca pode aparecer na mensagem da excecao.

    `process_message` grava `f"{type(exc).__name__}: {exc}"` em
    `messages.last_error` e loga `error=str(exc)` sem a mascara de PII -- o
    texto que o modelo escreveu para o lead nao pode chegar ali por essa
    porta, mesmo quando o JSON vem malformado (ex.: o modelo devolveu prosa
    em vez de JSON, ou um JSON com a resposta cortada no meio).
    """
    texto_malformado = f'{{"intencao": "COMPRA", "confianca": 0.9, "resposta": "{TEXTO_DA_RESPOSTA}'
    resposta = _resposta_falsa(texto=texto_malformado, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    # Pino exato, nao so "a sentinela nao esta la": um `str(erro.value) not
    # in TEXTO_DA_RESPOSTA` continua verde se o guard virar
    # `f"{type(exc).__name__}: {exc}"` (o mesmo padrao que `process_message`
    # usa) sempre que a excecao daquele tipo por acaso nao ecoar o texto --
    # e exatamente o caso de `JSONDecodeError`, cuja mensagem cita posicao,
    # nao conteudo. Fixar a mensagem inteira pega essa mutacao mesmo assim.
    assert str(erro.value) == "JSONDecodeError"
    assert TEXTO_DA_RESPOSTA not in caplog.text
    assert "agente.turno_gerado" not in caplog.text


async def test_classificar_recusa_intencao_desconhecida_sem_ecoar_o_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valor de `intencao` fora do enum e o mesmo furo que a Task 5 lista

    explicitamente: o modelo pode devolver algo que o schema deveria ter
    impedido. A excecao ainda nao pode carregar `resposta`.
    """
    resposta = _resposta_json(intencao="MUDANCA_DE_PAIS", resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    # Pino exato pelo mesmo motivo do teste de JSON malformado acima.
    assert str(erro.value) == "ValueError"


async def test_classificar_usa_modelo_agente_das_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mobia.app import config as config_mod

    monkeypatch.setattr(config_mod.get_settings(), "modelo_agente", "claude-modelo-de-teste")
    resposta = _resposta_json()
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.modelo == "claude-modelo-de-teste"
    _, kwargs = cliente.messages.create.call_args
    assert kwargs["model"] == "claude-modelo-de-teste"


async def test_classificar_envia_schema_compilado_no_output_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ligacao com o SDK e o unico ponto que nenhum dublê alcanca -- fixa a
    forma exata do parametro para que uma regressao apareca aqui, nao so em
    producao.

    O schema enviado e o *compilado* (`transform_schema`), nao
    `SCHEMA_DA_RESPOSTA` cru: `output_config.format` bruto nunca passa pelo
    `transform_schema` que o SDK roda no caminho de `output_format=`
    Pydantic, e `minimum`/`maximum` nao sao palavras-chave que o compilador
    de schema do servidor aceita (ver a doc da skill claude-api). Mandar
    `SCHEMA_DA_RESPOSTA` sem transformar arriscava 400 na primeira chamada
    real -- e nenhum dublê pegaria isso, porque nenhum deles fala com a API.
    """
    resposta = _resposta_json()
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    await ClassificadorAnthropic().classificar(_contexto())

    _, kwargs = cliente.messages.create.call_args
    schema_enviado = kwargs["output_config"]["format"]["schema"]
    assert schema_enviado == transform_schema(SCHEMA_DA_RESPOSTA)
    assert "minimum" not in schema_enviado["properties"]["confianca"]
    assert "maximum" not in schema_enviado["properties"]["confianca"]
    # SCHEMA_DA_RESPOSTA em si continua intocado: os testes de
    # tests/unit/test_intencao.py leem esse dict diretamente.
    assert SCHEMA_DA_RESPOSTA["properties"]["confianca"]["minimum"] == 0
    assert SCHEMA_DA_RESPOSTA["properties"]["confianca"]["maximum"] == 1


async def test_classificar_envia_payload_real_sem_minimum_maximum_via_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verificacao fim a fim contra o SDK de verdade, sem tocar rede.

    Todo outro teste deste arquivo troca `get_client()` por um dublê que
    nunca executa o codigo do `anthropic.AsyncAnthropic` -- e foi exatamente
    esse ponto cego que deixou passar `minimum`/`maximum` crus no corpo da
    requisicao. Este teste usa um `AsyncAnthropic` real com
    `httpx2.MockTransport` interceptando a conexao dentro do processo: o
    corpo capturado aqui e byte a byte o que sairia para a rede.
    """
    corpo_capturado: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        corpo_capturado["body"] = json.loads(request.content)
        payload = {
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(_DADOS_VALIDOS)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return httpx2.Response(200, json=payload, request=request)

    cliente_real = anthropic.AsyncAnthropic(
        api_key="chave-de-teste-sem-uso-real",
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente_real)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.intencao == Intencao.COMPRA
    schema_no_corpo = corpo_capturado["body"]["output_config"]["format"]["schema"]
    propriedade_confianca = schema_no_corpo["properties"]["confianca"]
    # Nem `minimum` nem `maximum` como *palavra-chave* do schema -- o
    # compilador do servidor rejeitaria isso. O intervalo ainda chega ao
    # modelo, so que como texto dentro de `description` (ver assert abaixo).
    assert "minimum" not in propriedade_confianca
    assert "maximum" not in propriedade_confianca
    assert propriedade_confianca["description"] == "{minimum: 0, maximum: 1}"


async def test_classificar_nao_duplica_a_persona_no_turno_do_usuario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SISTEMA_DO_AGENTE` vai no campo `system` dedicado; `contexto.sistema`
    nao pode ser reenviado dentro do turno do usuario -- seria a mesma
    persona, mais fraca, duas vezes.
    """
    resposta = _resposta_json()
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    await ClassificadorAnthropic().classificar(_contexto())

    _, kwargs = cliente.messages.create.call_args
    assert kwargs["system"] == classificador_mod.SISTEMA_DO_AGENTE
    conteudo_do_turno = kwargs["messages"][0]["content"]
    assert SISTEMA_DO_PROMPT not in conteudo_do_turno


@pytest.mark.parametrize("confianca_invalida", [5.0, -0.3, 1.0001, -0.0001])
async def test_classificar_recusa_confianca_fora_do_intervalo(
    monkeypatch: pytest.MonkeyPatch, confianca_invalida: float
) -> None:
    resposta = _resposta_json(confianca=confianca_invalida)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "intervalo" in str(erro.value)
    # O valor recusado nunca entra na mensagem.
    assert str(confianca_invalida) not in str(erro.value)


@pytest.mark.parametrize("confianca_boundary", [0, 0.0, 1, 1.0])
async def test_classificar_aceita_confianca_nos_limites(
    monkeypatch: pytest.MonkeyPatch, confianca_boundary: float
) -> None:
    """0 e 1 sao validos -- a checagem e `0 <= x <= 1`, nao um intervalo aberto."""
    resposta = _resposta_json(confianca=confianca_boundary)
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.confianca == pytest.approx(float(confianca_boundary))


@pytest.mark.parametrize("literal_nao_finito", ["NaN", "Infinity", "-Infinity"])
async def test_classificar_recusa_confianca_nao_finita(
    monkeypatch: pytest.MonkeyPatch, literal_nao_finito: str
) -> None:
    """`json.loads` aceita os literais nao-padrao `NaN`/`Infinity`/`-Infinity`.

    Sem esta checagem, `NaN` passa por `Decimal(str(...))`, e um `NaN` e
    falso tanto em `>= 0.8` quanto em `< 0.6` -- a ramificacao de
    desambiguacao de uma story futura simplesmente nao faria nada naquele
    turno, em silencio.
    """
    texto = f'{{"intencao": "COMPRA", "confianca": {literal_nao_finito}, "resposta": "oi"}}'
    resposta = _resposta_falsa(texto=texto, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "intervalo" in str(erro.value)


async def test_classificar_recusa_confianca_booleana(monkeypatch: pytest.MonkeyPatch) -> None:
    """`True`/`False` sao `int` em Python -- sem a guarda explicita, `True`
    passaria como confianca 1.0 e `False` como 0.0, os dois dentro do
    intervalo e finitos.
    """
    resposta = _resposta_json(confianca=True)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "intervalo" in str(erro.value)


async def test_classificar_recusa_confianca_nao_numerica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma string em `confianca` violaria o schema, mas o schema so e um
    pedido, nao uma garantia -- o modelo pode devolver isso mesmo assim.
    """
    resposta = _resposta_json(confianca="alta")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "alta" not in str(erro.value)


async def test_classificar_recusa_resposta_que_nao_e_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dados["resposta"].strip()` levanta `AttributeError` se o campo vier
    como numero -- essa excecao nao estava no tuple original e escapava crua.
    """
    resposta = _resposta_json(resposta=123)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert str(erro.value) == "AttributeError"


async def test_classificar_recusa_corpo_que_nao_e_objeto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma lista JSON valida ainda nao e um objeto com os tres campos
    esperados -- `dados["intencao"]` levanta `TypeError`, nao capturado
    antes do widening do tuple de excecoes.
    """
    resposta = _resposta_falsa(texto="[1, 2, 3]", stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert str(erro.value) == "TypeError"
