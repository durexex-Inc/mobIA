import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import structlog
from anthropic import transform_schema

from mobia.app.config import get_settings
from mobia.domain.agente.schemas import Intencao, RespostaDoAgente
from mobia.domain.context.montagem import ContextoMontado, montar_prompt
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

MAX_TOKENS_DA_RESPOSTA = 1500

SISTEMA_DO_AGENTE = (
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz duas coisas: classifica a intencao do "
    "lead e responde a ele.\n\n"
    "Intencoes possiveis: COMPRA (quer comprar para morar), ALUGUEL (quer alugar), "
    "INVESTIMENTO (compra para renda ou revenda, nao para morar), VENDER_IMOVEL "
    "(quer vender o que tem), SUPORTE_CONTRATO (duvida sobre contrato vigente), "
    "INDEFINIDA (ainda nao da para saber), FORA_DE_ESCOPO (nao e assunto "
    "imobiliario).\n\n"
    "A confianca e o quanto voce considera a classificacao segura, de 0 a 1.\n\n"
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o que ja esta "
    "preenchido. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto."
)

# Derivado do enum de proposito: duas listas mantidas a mao divergem, e a
# divergencia so aparece quando o modelo devolve um valor que o codigo nao
# sabe converter. `minimum`/`maximum` ficam aqui como parte do contrato do
# modulo (testados abaixo) mesmo sabendo que o compilador de schema da API
# nao os suporta -- ver `_SCHEMA_COMPILADO`.
SCHEMA_DA_RESPOSTA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intencao": {"type": "string", "enum": [membro.value for membro in Intencao]},
        "confianca": {"type": "number", "minimum": 0, "maximum": 1},
        "resposta": {"type": "string"},
    },
    "required": ["intencao", "confianca", "resposta"],
    "additionalProperties": False,
}

# `output_config.format` bruto (sem `output_format=` Pydantic) vai direto pro
# corpo da requisicao sem passar pelo `transform_schema` do SDK -- essa
# funcao so roda no caminho de `client.messages.parse()`. `minimum`/`maximum`
# nao estao na lista de palavras-chave que o compilador de schema do servidor
# aceita (ver a doc da skill claude-api, "JSON Schema Limitations"), entao
# manda-los seria um 400 na primeira chamada real. `transform_schema` dobra
# as duas chaves para dentro de `description` (o modelo ainda le o intervalo,
# so que como texto) e nao muta `SCHEMA_DA_RESPOSTA` -- os testes de schema
# continuam lendo o dict original. Compilado uma vez no import: e uma funcao
# pura do dict acima, que nao muda em runtime.
_SCHEMA_COMPILADO = transform_schema(SCHEMA_DA_RESPOSTA)


class RespostaInvalida(RuntimeError):
    """O modelo nao devolveu algo utilizavel neste turno."""


class ClassificadorPort(Protocol):
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente: ...


class ClassificadorAnthropic:
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente:
        settings = get_settings()
        comeco = time.monotonic()
        resposta = await get_client().messages.create(
            model=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_RESPOSTA,
            system=SISTEMA_DO_AGENTE,
            # omitir_sistema=True: SISTEMA_DO_AGENTE ja cobre a persona pelo
            # canal `system` dedicado. Reenviar `contexto.sistema` aqui
            # duplicaria a mesma instrucao, mais fraca, dentro do turno do
            # usuario.
            messages=[{"role": "user", "content": montar_prompt(contexto, omitir_sistema=True)}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA_COMPILADO}},
        )
        latency_ms = int((time.monotonic() - comeco) * 1000)

        # end_turn e a unica parada normal aqui: sem tools declaradas, sem
        # stop_sequence configurada. refusal e max_tokens sao os dois outros
        # jeitos documentados de sair de um json_schema estrito, e nenhum dos
        # dois produz um JSON que valha a pena tentar decodificar.
        if resposta.stop_reason != "end_turn":
            raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        if not texto:
            raise RespostaInvalida("resposta veio vazia")

        try:
            dados = json.loads(texto)
            intencao = Intencao(dados["intencao"])

            confianca_bruta = dados["confianca"]
            # additionalProperties/enum/type sao os unicos campos que o
            # compilador do servidor de fato impoe (ver _SCHEMA_COMPILADO
            # acima) -- o intervalo [0, 1] de `confianca` nunca foi garantido
            # la.
            #
            # A comparacao de faixa e a **primeira** checagem depois do tipo, e
            # a ordem importa. Um `math.isfinite` aqui na frente recebe o int
            # arbitrario que `json.loads` aceita sem reclamar (um inteiro JSON
            # de ~320 digitos) e levanta OverflowError ao converter para float
            # -- ArithmeticError, fora do `except` abaixo, escapando cru e
            # quebrando o contrato de que RespostaInvalida e o unico modo de
            # falha deste modulo. `0 <= x <= 1` trabalha em precisao
            # arbitraria e rejeita o valor sem converter nada.
            #
            # E ela sozinha ja cobre `NaN`/`Infinity`/`-Infinity`, os literais
            # nao-padrao que `json.loads` aceita: toda comparacao com NaN e
            # falsa e os infinitos caem fora da faixa. Nenhum deles chega ao
            # `Decimal(str(...))` -- um NaN ali nunca satisfaria `>= 0.8` nem
            # `< 0.6` de quem consome depois, e a ramificacao simplesmente nao
            # aconteceria, em silencio.
            if (
                isinstance(confianca_bruta, bool)
                or not isinstance(confianca_bruta, int | float)
                or not (0 <= confianca_bruta <= 1)
            ):
                # RuntimeError nao esta no tuple do except abaixo -- propaga
                # direto, sem virar `type(exc).__name__`. Mensagem fixa, sem
                # o valor: e erro de contrato, nao motivo para expor o que
                # veio.
                raise RespostaInvalida("campo confianca fora do intervalo [0, 1]")

            resultado = RespostaDoAgente(
                intencao=intencao,
                confianca=Decimal(str(confianca_bruta)),
                resposta=dados["resposta"].strip(),
                modelo=settings.modelo_agente,
                tokens_in=resposta.usage.input_tokens,
                tokens_out=resposta.usage.output_tokens,
                latency_ms=latency_ms,
            )
        except (
            json.JSONDecodeError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            InvalidOperation,
        ) as exc:
            # Nunca interpola `texto` nem `dados`: carregam a resposta
            # destinada ao lead. So o nome da classe, nunca `str(exc)` --
            # `KeyError`/`TypeError` de um schema com formato inesperado
            # podem ecoar o proprio valor recebido na mensagem da excecao.
            raise RespostaInvalida(type(exc).__name__) from exc

        if not resultado.resposta:
            raise RespostaInvalida("campo resposta veio vazio")

        # So numeros e id de modelo. Nem a resposta, nem o prompt, nem a
        # intencao classificada -- essa ultima nao e conteudo do lead, mas
        # tambem nao ajuda em log e mantem a regra simples.
        log.info(
            "agente.turno_gerado",
            modelo=resultado.modelo,
            tokens_in=resultado.tokens_in,
            tokens_out=resultado.tokens_out,
            latency_ms=resultado.latency_ms,
            custo_usd=str(
                custo_em_dolar(resultado.modelo, resultado.tokens_in, resultado.tokens_out)
            ),
        )
        return resultado
