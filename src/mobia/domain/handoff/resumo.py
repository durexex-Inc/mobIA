"""O resumo de handoff: os seis blocos, o validador e o redator.

TEC-175, RF-15.
"""

import time
from dataclasses import dataclass
from typing import Protocol

import structlog

from mobia.app.config import get_settings
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

# RN-15.2. O numero mora aqui e so aqui -- quem precisa dele importa a
# constante, para nao existir uma segunda copia livre para divergir.
LIMITE_DE_CARACTERES = 1500

# Os seis blocos da RN-15.1, como marcadores LITERAIS e nao como instrucao em
# prosa. Sem marcador fixo, o primeiro cenario do Gherkin -- "contem os seis
# blocos na ordem definida" -- nao e testavel: vira opiniao sobre um texto
# corrido. O custo e um resumo com cara de formulario; o ganho e um criterio
# de aceite que e asercao, e nao leitura.
MARCADORES = (
    "## Quem e o lead",
    "## O que procura",
    "## Score e temperatura",
    "## Imoveis apresentados",
    "## Pontos de atencao",
    "## Proxima acao",
)


def link_da_transcricao(canal: str, conversa: str) -> str:
    """O link da RN-15.5, composto aqui e nunca pelo modelo.

    Campo separado e nao conteudo do resumo (D10): se entrasse no texto,
    gastaria orcamento dos 1.500 caracteres da RN-15.2 e passaria a depender
    de o modelo transcrever uma URL sem errar um caractere.

    Vive aqui e nao em `dossie.py`: aquele modulo se declara sem I/O, e
    `get_settings()` o quebraria na primeira linha depois de uma docstring
    que promete o contrario. Este modulo ja importa `get_settings` desde a
    RedatorAnthropic.

    **O destino ainda nao existe** -- e a E8. Ver a L4 do desenho.
    """
    return f"{get_settings().dashboard_base_url}/conversas/{canal}/{conversa}"


class ResumoDeHandoffInvalido(RuntimeError):
    """A resposta do modelo nao e um resumo utilizavel.

    Mesmo papel do `ResumoInvalido` de `context/resumo.py`: levantar aqui, em
    vez de gravar um resumo manco, e o que da ao chamador a chance de nao
    gravar nada. Um resumo truncado e pior que resumo nenhum -- ele corta o
    fim, e o fim e o bloco da proxima acao, que e o que diz ao corretor o que
    fazer. Ver a D7 do desenho.
    """


class ResumoAcimaDoLimite(ResumoDeHandoffInvalido):
    """Resumo excedeu o limite de caracteres.

    E o unico caso de ResumoDeHandoffInvalido com segunda chance: se o tamanho
    passar do limite, a compressao pode trazê-lo de volta. Bloco ausente ou fora
    de ordem nao tem segunda chance -- comprimir nao resolve. Separa-la aqui
    tira o controle de fluxo de cima do texto da mensagem de erro, eliminando
    a fragilidade de um `if "acima do limite" not in str(falha)`.
    """


def validar(texto: str) -> str:
    """Devolve o texto quando ele e um resumo valido; levanta quando nao e.

    A ordem e conferida por posicao crescente e nao por presenca: seis blocos
    presentes fora de ordem satisfazem "contem os seis" e mesmo assim nao sao
    o que a RN-15.1 pede.
    """
    limpo = texto.strip()
    if not limpo:
        raise ResumoDeHandoffInvalido("resumo vazio ou so com espaco em branco")

    if len(limpo) > LIMITE_DE_CARACTERES:
        raise ResumoAcimaDoLimite(
            f"resumo acima do limite: {len(limpo)} de {LIMITE_DE_CARACTERES} caracteres"
        )

    posicoes = []
    for marcador in MARCADORES:
        posicao = limpo.find(marcador)
        if posicao < 0:
            raise ResumoDeHandoffInvalido(f"bloco ausente: {marcador!r}")
        posicoes.append(posicao)

    if posicoes != sorted(posicoes):
        raise ResumoDeHandoffInvalido("blocos fora de ordem")

    return limpo


# Folga sobre os 1.500 caracteres da RN-15.2: o modelo precisa de espaco para
# errar para cima e ainda ser corrigido pela compressao, mas nao tanto que uma
# resposta desgovernada custe uma eternidade antes de ser recusada.
MAX_TOKENS_DO_RESUMO = 1200

INSTRUCAO_REDIGIR = (
    "Voce escreve o resumo de um lead imobiliario para o corretor que vai assumir "
    "a conversa. Use EXATAMENTE os seis titulos abaixo, nesta ordem, cada um em "
    "sua propria linha:\n"
    + "\n".join(MARCADORES)
    + "\n\nEscreva em portugues, em terceira pessoa, direto ao ponto. "
    f"O texto inteiro deve caber em {LIMITE_DE_CARACTERES} caracteres.\n\n"
    "**Use apenas os dados do dossie abaixo.** Nao estime, nao arredonde, nao "
    "complete o que estiver como 'nao informado' -- escreva que nao foi "
    "informado. Todo numero que voce citar tem de aparecer literalmente no "
    "dossie."
)

INSTRUCAO_COMPRIMIR = (
    "O resumo abaixo passou do limite. Reescreva-o em no maximo "
    f"{LIMITE_DE_CARACTERES} caracteres, mantendo os seis titulos na mesma ordem "
    "e todo dado factual. Corte narrativa e transicao, nunca numero nem titulo."
)


@dataclass(frozen=True)
class ResumoDeHandoffGerado:
    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    comprimiu: bool


class RedatorPort(Protocol):
    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado: ...


class RedatorAnthropic:
    """Redige os seis blocos a partir do dossie, e so do dossie.

    Nao rebaixa o modelo, pelo mesmo argumento de `context/resumo.py`: e a
    partir deste texto que o corretor decide como entrar na conversa, e um
    resumo pobre custa o lead inteiro.
    """

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        settings = get_settings()
        comeco = time.monotonic()
        bruto, uso = await self._chamar(INSTRUCAO_REDIGIR, dossie_em_texto, settings.modelo_resumo)

        comprimiu = False
        try:
            texto = validar(bruto)
        except ResumoAcimaDoLimite:
            # SO o estouro de tamanho tem segunda chance. Bloco ausente ou
            # fora de ordem nao e problema de tamanho, e comprimir um resumo
            # que ja perdeu um bloco nao o traz de volta -- so gastaria a
            # segunda chamada para falhar igual.
            comprimiu = True
            bruto, uso_da_compressao = await self._chamar(
                INSTRUCAO_COMPRIMIR, bruto, settings.modelo_resumo
            )
            uso = (uso[0] + uso_da_compressao[0], uso[1] + uso_da_compressao[1])
            texto = validar(bruto)

        gerado = ResumoDeHandoffGerado(
            texto=texto,
            modelo=settings.modelo_resumo,
            tokens_in=uso[0],
            tokens_out=uso[1],
            latency_ms=int((time.monotonic() - comeco) * 1000),
            comprimiu=comprimiu,
        )

        # `latency_ms` esta aqui porque e a UNICA medicao do p95 de 8s da
        # RNF-05 que este sistema produz: o terceiro cenario do Gherkin pede
        # 100 geracoes medidas em homologacao, e a suite exclui `-m perf` de
        # proposito. Ver a L2 do desenho. Nunca loga o dossie nem o texto.
        log.info(
            "resumo_handoff.gerado",
            modelo=gerado.modelo,
            tokens_in=gerado.tokens_in,
            tokens_out=gerado.tokens_out,
            latency_ms=gerado.latency_ms,
            comprimiu=gerado.comprimiu,
            caracteres=len(gerado.texto),
            custo_usd=str(custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)),
        )
        return gerado

    async def _chamar(
        self, instrucao: str, conteudo: str, modelo: str
    ) -> tuple[str, tuple[int, int]]:
        resposta = await get_client().messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_DO_RESUMO,
            system=instrucao,
            messages=[{"role": "user", "content": conteudo}],
        )
        # Mesma guarda de `context/resumo.py`, e pela mesma razao: `max_tokens`
        # corta a resposta no meio de uma frase e ela sai parecendo completa.
        # Checar antes de olhar o texto.
        if resposta.stop_reason != "end_turn":
            raise ResumoDeHandoffInvalido(
                f"resumo interrompido antes do fim: stop_reason={resposta.stop_reason!r}"
            )
        texto = "".join(b.text for b in resposta.content if b.type == "text")
        return texto, (resposta.usage.input_tokens, resposta.usage.output_tokens)
