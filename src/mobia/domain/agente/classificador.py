import json
import time
from decimal import Decimal
from typing import Any, Protocol

import structlog

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
# sabe converter.
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
            messages=[{"role": "user", "content": montar_prompt(contexto)}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA_DA_RESPOSTA}},
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
            resultado = RespostaDoAgente(
                intencao=Intencao(dados["intencao"]),
                confianca=Decimal(str(dados["confianca"])),
                resposta=dados["resposta"].strip(),
                modelo=settings.modelo_agente,
                tokens_in=resposta.usage.input_tokens,
                tokens_out=resposta.usage.output_tokens,
                latency_ms=latency_ms,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # Nunca interpola `texto`: ele carrega a resposta destinada ao lead.
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
