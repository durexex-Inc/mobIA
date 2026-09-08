import json
import logging
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx2
import pytest
from anthropic import transform_schema

from mobia.domain.agente import classificador as classificador_mod
from mobia.domain.agente.classificador import (
    MAX_TOKENS_DA_PERGUNTA,
    SCHEMA_DA_RESPOSTA,
    SISTEMA_DA_DESAMBIGUACAO,
    SISTEMA_DO_AGENTE,
    ClassificadorAnthropic,
    RespostaInvalida,
    _lista_de_nomes,
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


def _instalar_e_capturar(
    monkeypatch: pytest.MonkeyPatch, resposta: SimpleNamespace
) -> _ClienteFalso:
    """Como `_instalar_cliente_falso`, mas devolve o dublê.

    Os testes da desambiguacao asseguram o **formato da requisicao** (sem
    schema estrito, com teto de tokens curto), entao precisam do `AsyncMock`
    para ler `call_args`.
    """
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)
    return cliente


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


def test_lista_de_nomes_chega_como_tupla():
    """Serve `perguntou` e `recusou`: os dois sao o modelo relatando nomes de
    campo sobre o proprio turno, e a normalizacao e a mesma."""
    assert _lista_de_nomes(["regiao", "vagas"]) == ("regiao", "vagas")


def test_lista_de_nomes_tolera_forma_errada_sem_levantar():
    """O turno ja foi pago e ja tem resposta valida para o lead: forma errada
    num campo de relato nao pode custa-lo."""
    assert _lista_de_nomes(None) == ()
    assert _lista_de_nomes("regiao") == ()
    assert _lista_de_nomes(["regiao", 7, None, "bairro"]) == ("regiao", "bairro")


def test_a_ordem_dos_campos_poe_perguntou_depois_de_resposta():
    """TEC-244: a ordem do schema e a ordem de geracao, e ela e deliberada.

    `perguntou` relata o que a resposta ja escrita pergunta. Antes de
    `resposta`, seria um compromisso a honrar -- pedido diferente, nunca
    medido.
    """
    ordem = list(SCHEMA_DA_RESPOSTA["properties"])
    assert ordem.index("perguntou") > ordem.index("resposta")
    assert SCHEMA_DA_RESPOSTA["required"] == ordem


def test_recusou_esta_no_schema_como_array_de_string():
    from mobia.domain.agente.classificador import SCHEMA_DA_RESPOSTA

    assert SCHEMA_DA_RESPOSTA["properties"]["recusou"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_recusou_vem_depois_de_perguntou_na_ordem_dos_campos():
    """A TEC-240 recusou reordenar campos do schema mesmo a custo zero de
    tokens: muda a ordem de geracao do modelo num caminho pago, em todo turno
    de producao. Acrescentar no fim e a unica posicao que nao mexe no que ja
    existe.
    """
    from mobia.domain.agente.classificador import _ORDEM_DOS_CAMPOS

    assert _ORDEM_DOS_CAMPOS[-2:] == ("perguntou", "recusou")


def test_recusou_default_e_tupla_vazia_no_dataclass():
    """Turno que nao relata recusa nao e turno com recusa vazia por acidente:
    o default explicito e o que faz o chamador antigo continuar valendo."""
    from dataclasses import fields

    from mobia.domain.agente.schemas import RespostaDoAgente

    campo = next(f for f in fields(RespostaDoAgente) if f.name == "recusou")
    assert campo.default == ()


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
    # Bloco com `cache_control`, e nao string crua, desde a TEC-251: o prefixo
    # e identico em toda chamada e sem o marcador e pago inteiro toda vez. O
    # que este teste guarda continua sendo o MESMO -- que a persona vai no
    # campo dedicado --, so que na forma que o cache exige.
    assert kwargs["system"] == [
        {
            "type": "text",
            "text": classificador_mod.SISTEMA_DO_AGENTE,
            "cache_control": {"type": "ephemeral"},
        }
    ]
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


async def test_classificar_recusa_confianca_inteira_gigante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Um inteiro JSON de ~320 digitos nao pode escapar como OverflowError.

    `json.loads` devolve um `int` de precisao arbitraria sem reclamar.
    Converte-lo para float (era o que `math.isfinite` fazia, antes da faixa)
    levanta OverflowError -- ArithmeticError, fora do `except` do boundary --
    e a excecao escapava crua, quebrando o contrato de que RespostaInvalida e
    o unico modo de falha deste modulo. A comparacao `0 <= x <= 1` trabalha em
    precisao arbitraria e rejeita antes de qualquer conversao.
    """
    resposta = _resposta_json(confianca=10**320)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "intervalo" in str(erro.value)


async def test_classificar_arredonda_confianca_como_o_numeric_3_2_do_banco(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`conversation_intent.confianca` e `numeric(3,2)`: o Postgres arredonda
    ao gravar. Um `Decimal` sem arredondar aqui seria dois valores para o
    mesmo limiar -- 0.599 desambigua em memoria, mas a linha gravada guardaria
    0.60, que `efetiva` leria como confiante. Pino no resultado, nao no valor
    bruto: 0.599 quantizado para escala 0.01 vira 0.60.
    """
    resposta = _resposta_json(confianca=0.599)
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.confianca == Decimal("0.60")


async def test_classificar_arredonda_para_cima_na_borda_como_o_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ROUND_HALF_UP`, nao o `ROUND_HALF_EVEN` default do `Decimal`.

    Os dois modos so divergem exatamente na borda de 0,005: o Postgres
    arredonda `numeric` para longe do zero e devolve 0.59; o bankers' rounding
    do Python devolveria 0.58. O valor gravado tem de bater com o que o banco
    faria, nao com o default da linguagem.
    """
    resposta = _resposta_json(confianca=0.585)
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.confianca == Decimal("0.59")


PERGUNTA = "O que voce esta buscando agora nesse momento?"


async def test_desambiguar_devolve_a_pergunta_e_a_telemetria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _instalar_cliente_falso(monkeypatch, _resposta_falsa(texto=f"  {PERGUNTA}  "))

    pergunta = await ClassificadorAnthropic().desambiguar(_contexto())

    assert pergunta.texto == PERGUNTA, "espacos das pontas nao vao para o lead"
    assert pergunta.tokens_in == 4000
    assert pergunta.tokens_out == 200
    assert pergunta.latency_ms >= 0


async def test_desambiguar_nao_manda_schema_estrito(monkeypatch: pytest.MonkeyPatch) -> None:
    """A saida e uma frase. Nao ha campo para validar, entao nao ha schema.

    O schema do `classificar` existe porque intencao e confianca sao regra de
    negocio; aqui ele so custaria tokens e uma chance a mais de 400.
    """
    cliente = _instalar_e_capturar(monkeypatch, _resposta_falsa(texto=PERGUNTA))

    await ClassificadorAnthropic().desambiguar(_contexto())

    kwargs = cliente.messages.create.call_args.kwargs
    assert "output_config" not in kwargs
    assert kwargs["max_tokens"] == MAX_TOKENS_DA_PERGUNTA
    assert kwargs["system"] == [
        {
            "type": "text",
            "text": SISTEMA_DA_DESAMBIGUACAO,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_desambiguar_pede_uma_pergunta_aberta() -> None:
    """O prompt e a unica coisa que segura a regra "sem menu numerado".

    Nada no codigo verifica o texto devolvido -- ver a secao de lacunas do
    spec. Se esta instrucao sumir do system prompt, some a regra inteira.
    """
    assert "menu" in SISTEMA_DA_DESAMBIGUACAO.lower()
    assert "uma unica pergunta" in SISTEMA_DA_DESAMBIGUACAO.lower()


def test_o_prompt_do_agente_nomeia_as_tres_tarefas() -> None:
    """Ate a TEC-240 o prompt dizia "duas coisas" -- a TEC-145 pos um objeto
    `extracao` de nove campos no schema e nao contou ao modelo.

    Guarda contra alguem reverter a abertura ao editar o prompt por outro
    motivo: o schema continuaria pedindo extracao, e o modelo voltaria a nao
    saber que ela existe.
    """
    assert "tres coisas" in SISTEMA_DO_AGENTE
    assert "extrai o que ele procura" in SISTEMA_DO_AGENTE


def test_o_prompt_do_agente_explica_a_semantica_de_null() -> None:
    """`null` significa "o lead nao falou disso NESTE turno", e a metrica pune
    inferencia tanto quanto omissao. As duas coisas chegavam ao modelo como
    nomes de campo crus.

    Os dois primeiros asserts (ja existentes) so travam substrings soltas --
    nao a frase que a card existe para escrever. Sem o terceiro assert, uma
    edicao futura podia cortar exatamente a definicao explicita de `null` (a
    unica que o modelo recebe) mantendo "DESTE turno" e "Nao infira" em outro
    lugar do texto, e este teste continuaria verde.
    """
    assert "DESTE turno" in SISTEMA_DO_AGENTE
    assert "Nao infira" in SISTEMA_DO_AGENTE
    assert 'null e "nao falou disso agora"' in SISTEMA_DO_AGENTE
    # Unico ponto onde o prompt usa o nome do campo do schema -- nada mais
    # trava isso.
    assert "Na extracao" in SISTEMA_DO_AGENTE


async def test_desambiguar_recusa_parada_anormal(monkeypatch: pytest.MonkeyPatch) -> None:
    """`max_tokens` corta a pergunta no meio; meia pergunta nao vai ao lead."""
    _instalar_cliente_falso(monkeypatch, _resposta_falsa(texto=PERGUNTA, stop_reason="max_tokens"))

    with pytest.raises(RespostaInvalida):
        await ClassificadorAnthropic().desambiguar(_contexto())


async def test_desambiguar_recusa_pergunta_vazia(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar_cliente_falso(monkeypatch, _resposta_falsa(texto="   "))

    with pytest.raises(RespostaInvalida):
        await ClassificadorAnthropic().desambiguar(_contexto())


async def test_desambiguar_nao_loga_a_pergunta_nem_o_prompt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Mesma regra do `classificar`: so numeros e id de modelo."""
    _instalar_cliente_falso(
        monkeypatch, _resposta_falsa(texto=f"{TEXTO_DA_RESPOSTA} qual e a sua duvida?")
    )

    with caplog.at_level(logging.INFO):
        await ClassificadorAnthropic().desambiguar(_contexto())

    assert "SENTINELA-RESPOSTA" not in caplog.text
    assert "SENTINELA-SISTEMA" not in caplog.text
    assert "SENTINELA-RESUMO" not in caplog.text
    assert "agente.desambiguacao_gerada" in caplog.text


async def test_extracao_entra_na_resposta_do_agente(monkeypatch: pytest.MonkeyPatch) -> None:
    dados = dict(_DADOS_VALIDOS, extracao={"quartos": 3, "regiao": "moema"})
    resposta = _resposta_falsa(texto=json.dumps(dados))
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.extracao.quartos == 3
    assert resultado.extracao.regiao == "moema"


async def test_extracao_malformada_nao_derruba_o_turno(monkeypatch: pytest.MonkeyPatch) -> None:
    """O contrato central desta card: a resposta ao lead sobrevive."""
    dados = dict(_DADOS_VALIDOS, extracao="isto nao e um objeto")
    resposta = _resposta_falsa(texto=json.dumps(dados))
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.resposta == TEXTO_DA_RESPOSTA
    assert resultado.extracao.vazia() is True


async def test_resposta_sem_extracao_continua_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_DADOS_VALIDOS` nao tem `extracao`. Se isto falhar, o parse ficou
    rigido onde deveria ser tolerante."""
    resposta = _resposta_falsa(texto=json.dumps(_DADOS_VALIDOS))
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.extracao.vazia() is True


async def test_recusou_do_modelo_chega_no_resultado_pelo_parse_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEC-148: o unico teste que morre se a leitura de `recusou` sumir.

    Toda a integracao passa por `ClassificadorFake`, que constroi
    `RespostaDoAgente` direto -- e o campo tem default `()`. Apagar a linha
    `recusou=_lista_de_nomes(dados.get("recusou"))` daqui deixaria a feature
    morta em producao com a suite inteira verde: nenhum teste que nao passe
    pelo parse de verdade consegue ver a diferenca.
    """
    dados = dict(_DADOS_VALIDOS, recusou=["regiao"])
    resposta = _resposta_falsa(texto=json.dumps(dados))
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.recusou == ("regiao",)


async def test_resposta_sem_recusou_continua_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_DADOS_VALIDOS` nao tem `recusou`. O campo e relato do modelo sobre o
    proprio turno: ausencia dele nao pode custar um turno ja pago que ja tem
    resposta valida para o lead."""
    resposta = _resposta_falsa(texto=json.dumps(_DADOS_VALIDOS))
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.recusou == ()


async def test_extracao_nao_vaza_no_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`regiao` e fala do lead. O log deste modulo carrega so numeros e modelo."""
    dados = dict(_DADOS_VALIDOS, extracao={"regiao": "SENTINELA-REGIAO Rua das Palmeiras"})
    resposta = _resposta_falsa(texto=json.dumps(dados))
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO):
        await ClassificadorAnthropic().classificar(_contexto())

    # `extrair` agora grava `regiao` em `casefold` (TEC-241): se vazasse,
    # apareceria como "sentinela-regiao", nao mais na caixa injetada acima.
    # Comparar em caixa original deixaria este teste verde sem testar nada.
    assert "sentinela-regiao" not in caplog.text.casefold()


# --- TEC-250: as tres regras que o corpus aplicava e o prompt nao dizia ----


def test_o_prompt_manda_extrair_mesmo_o_que_ja_esta_no_estado() -> None:
    """A ambiguidade que produziu 7 das 15 discrepancias de 30/08.

    O prompt oferecia o estado acumulado como memoria e proibia reemiti-lo na
    extracao. Quando um turno posterior RE-AFIRMA algo que ja esta no estado
    -- "pode ser flat tambem", "o sobrado tem escritura" --, as duas
    instrucoes apontam para lados opostos, e o modelo resolvia isso de forma
    inconsistente: 6 vezes nao reemitiu onde o corpus esperava que sim, 1 vez
    reemitiu onde esperava que nao.

    O corpus sempre foi inequivoco -- anota o que ESTE turno afirma, esteja no
    estado ou nao. Faltava o prompt dizer o mesmo.
    """
    assert "mesmo que ja esteja no estado" in SISTEMA_DO_AGENTE


def test_o_prompt_diz_que_o_imovel_que_o_lead_TEM_nao_e_o_que_procura() -> None:
    """Regra da TEC-239 que vivia so no docstring de `TurnoAnotado`.

    `follow-up-03[0]` e `follow-up-06[0]` -- "comprei um apartamento com voces
    e agora preciso vender" -- extraiam `tipo_imovel: APARTAMENTO`, e o corpus
    anota so `tem_imovel_para_vender`. O modelo nao tinha como acertar: era
    medido contra uma regra que nunca recebeu.
    """
    assert "O imovel que o lead ja tem nao e o que ele procura" in SISTEMA_DO_AGENTE


def test_o_prompt_exige_marco_temporal_para_urgencia() -> None:
    """A outra regra da TEC-239 que so o corpus conhecia.

    `follow-up-07[2]` ("quero fechar logo") e `follow-up-08[0]` ("bora marcar")
    extraiam `urgencia: IMEDIATA`; a barra do corpus e marco temporal
    explicito, e entusiasmo nao e marco. Em `follow-up-08` isso produzia um
    off-by-one visivel: `urgencia` disparava no turno 0, sem marco, e faltava
    no turno 1, que tem "essa sexta a tarde".
    """
    assert "Urgencia so com marco temporal explicito" in SISTEMA_DO_AGENTE


def test_as_regras_de_anotacao_do_corpus_estao_no_prompt() -> None:
    """A invariante que as tres acima instanciam.

    O docstring de `TurnoAnotado` (`mobia.evals.corpus`) e a regua; o prompt e
    o que o modelo le. Toda regra que a regua aplica e o prompt nao diz e uma
    discrepancia garantida -- o modelo e cobrado por um contrato que nao
    recebeu, e nenhuma execucao paga consegue distinguir isso de erro do
    modelo.
    """
    for regra in (
        "mesmo que ja esteja no estado",
        "O imovel que o lead ja tem",
        "marco temporal explicito",
    ):
        assert regra in SISTEMA_DO_AGENTE, f"regra ausente do prompt: {regra!r}"


# --- TEC-265: o laco de tool use em _chamar --------------------------------


def _bloco_tool_use(entrada: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="toolu_01", name="buscar_imoveis", input=entrada)


def _resposta_tool_use(entrada: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[_bloco_tool_use(entrada)],
        usage=SimpleNamespace(input_tokens=4000, output_tokens=200),
        stop_reason="tool_use",
    )


def _instalar_sequencia(
    monkeypatch: pytest.MonkeyPatch, respostas: list[SimpleNamespace]
) -> _ClienteFalso:
    """Um duble que devolve uma resposta por chamada, na ordem dada.

    O `_ClienteFalso` de hoje tem `return_value` e serviria para uma chamada
    so; o laco de tool use faz duas.
    """
    cliente = _ClienteFalso(respostas[0])
    cliente.messages = SimpleNamespace(create=AsyncMock(side_effect=respostas))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)
    return cliente


async def test_classificar_executa_a_ferramenta_e_chama_de_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "VENDA"}), _resposta_json()]
    )
    chamadas: list[dict[str, object]] = []

    async def porta(entrada: dict[str, object]) -> dict[str, object]:
        chamadas.append(entrada)
        return {"candidatos": [{"imovel_id": "abc", "preco_centavos": 100}], "total_candidatos": 1}

    resposta = await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    assert chamadas == [{"operacao": "VENDA"}]
    assert cliente.messages.create.await_count == 2
    assert resposta.candidatos == [{"imovel_id": "abc", "preco_centavos": 100}]


async def test_a_segunda_chamada_leva_o_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "VENDA"}), _resposta_json()]
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"candidatos": [], "total_candidatos": 0}

    await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    segunda = cliente.messages.create.await_args_list[1].kwargs
    blocos = segunda["messages"][-1]["content"]
    assert blocos[0]["type"] == "tool_result"
    assert blocos[0]["tool_use_id"] == "toolu_01"
    assert blocos[0].get("is_error") is not True


async def test_erro_da_porta_vira_tool_result_com_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9: o turno nao cai por causa de uma busca."""
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "COMPRA"}), _resposta_json()]
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"erro": "operacao invalida: use VENDA ou ALUGUEL"}

    resposta = await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    blocos = cliente.messages.create.await_args_list[1].kwargs["messages"][-1]["content"]
    assert blocos[0]["is_error"] is True
    assert resposta.candidatos == []


async def test_um_segundo_tool_use_nao_e_atendido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4: o teto e um round-trip por turno.

    Sem ele, quantas chamadas o turno faz e decisao do modelo -- e a RNF-02
    (p95 <= 6 s) e a RNF-06 (US$ 0,12 por conversa) ficam a merce dela.
    """
    cliente = _instalar_sequencia(
        monkeypatch,
        [_resposta_tool_use({"operacao": "VENDA"}), _resposta_tool_use({"operacao": "VENDA"})],
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"candidatos": [], "total_candidatos": 0}

    with pytest.raises(classificador_mod.LacoDeBuscaExcedido):
        await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    assert cliente.messages.create.await_count == 2


async def test_sem_porta_a_ferramenta_nao_e_declarada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turno sem porta injetada continua sendo uma chamada so, sem `tools`."""
    cliente = _instalar_sequencia(monkeypatch, [_resposta_json()])

    await ClassificadorAnthropic().classificar(_contexto())

    assert "tools" not in cliente.messages.create.await_args.kwargs
    assert cliente.messages.create.await_count == 1
