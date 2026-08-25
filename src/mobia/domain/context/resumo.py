import time
from dataclasses import dataclass
from typing import Protocol

import structlog

from mobia.app.config import get_settings
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

MAX_TOKENS_DO_RESUMO = 2000

INSTRUCAO_DOBRAR = (
    "Voce mantem a memoria de uma conversa entre um lead imobiliario e um agente. "
    "Incorpore as mensagens abaixo ao resumo existente, preservando fatos concretos: "
    "orcamento, regiao, tipo de imovel, quartos, vagas, prazo, forma de pagamento, "
    "objecoes e compromissos assumidos. Descarte cortesia e repeticao. "
    "Escreva em terceira pessoa, em portugues, sem inventar nada que nao esteja no texto."
)

INSTRUCAO_COMPRIMIR = (
    "Comprima o resumo abaixo pela metade, preservando todo fato concreto sobre o lead "
    "-- orcamento, regiao, tipo de imovel, quartos, vagas, prazo, forma de pagamento, "
    "objecoes e compromissos. Descarte narrativa e transicao. Nao invente nada."
)


@dataclass(frozen=True)
class ResumoGerado:
    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class ResumoInvalido(RuntimeError):
    """Resposta do modelo nao e um resumo utilizavel.

    Cobre truncamento por `max_tokens` (a resposta e uma frase pela metade que
    parece completa) e texto vazio ou so espaco em branco (recusa, bloqueio de
    conteudo, resposta so com tool_use). Levantar aqui, e nao devolver um
    `ResumoGerado` manco, e o que da ao chamador (Task 5) a chance de degradar
    para o resumo anterior em vez de gravar um resumo vazio ou truncado como se
    fosse bom e avancar a marca por cima das mensagens que ele deveria ter
    absorvido.
    """


class ResumidorPort(Protocol):
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado: ...


class ContadorPort(Protocol):
    async def contar(self, texto: str) -> int: ...


class ResumidorAnthropic:
    """Resumo pelo modelo padrao do projeto.

    Nao rebaixa o modelo: o resumo nao e saida descartavel, e entrada de todo
    turno seguinte. Um resumo pobre erra em todas as respostas dali em diante e
    sem ninguem perceber, e a regua que mediria isso so chega na TEC-210.
    """

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        settings = get_settings()
        comeco = time.monotonic()
        resposta = await get_client().messages.create(
            model=settings.modelo_resumo,
            max_tokens=MAX_TOKENS_DO_RESUMO,
            system=instrucao,
            messages=[{"role": "user", "content": conteudo}],
        )
        latency_ms = int((time.monotonic() - comeco) * 1000)

        # end_turn e a unica parada normal. max_tokens corta a resposta no meio
        # de uma frase e ela sai parecendo completa; tool_use/stop_sequence/
        # pause_turn/refusal/model_context_window_exceeded nao sao resumo
        # nenhum. Checar antes de olhar o texto, porque um max_tokens pode
        # muito bem ter texto (truncado) e passaria incolume pela checagem
        # de vazio logo abaixo.
        if resposta.stop_reason != "end_turn":
            raise ResumoInvalido(
                f"resumo interrompido antes do fim: stop_reason={resposta.stop_reason!r}"
            )

        # .strip() antes de testar e antes de guardar: "   \n  " nao e vazio
        # para `not texto`, mas nao carrega fato nenhum sobre o lead. Sem o
        # strip aqui, esse texto passaria a checagem, viraria ResumoGerado.texto
        # e o espaco em branco de sobra seria concatenado no prompt do proximo
        # turno para sempre.
        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        if not texto:
            raise ResumoInvalido("resumo veio vazio ou so com espaco em branco")

        gerado = ResumoGerado(
            texto=texto,
            modelo=settings.modelo_resumo,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=latency_ms,
        )

        # Gasto de LLM que nao e resposta ao lead nao cabe em message_telemetry,
        # que tem FK para messages.id. Fica em log estruturado ate o painel de
        # custo (E8) e a TEC-220 decidirem onde isso mora. Nunca loga o texto.
        log.info(
            "resumo.gerado",
            modelo=gerado.modelo,
            tokens_in=gerado.tokens_in,
            tokens_out=gerado.tokens_out,
            latency_ms=gerado.latency_ms,
            custo_usd=str(custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)),
        )
        return gerado


class ContadorAnthropic:
    """Contagem real de tokens pela API.

    Nunca `tiktoken` nem heuristica de caractere como fonte de verdade: o teto
    de 12.000 e criterio de aceite, e errar a contagem para menos significa a
    chamada ser recusada em producao.
    """

    async def contar(self, texto: str) -> int:
        resposta = await get_client().messages.count_tokens(
            model=get_settings().modelo_resumo,
            messages=[{"role": "user", "content": texto}],
        )
        return int(resposta.input_tokens)
