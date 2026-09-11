import re
import time
from functools import lru_cache
from typing import Any, cast

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    CATEGORIAS_POR_DIRECAO,
    Direcao,
    ModeracaoIndisponivel,
    Veredito,
)
from mobia.infra.anthropic import motivo_do_provedor

log = structlog.get_logger(__name__)

# Teto proprio, e nao o do cliente do turno. Aquele tem 60s com uma
# retentativa, ou 120s de pior caso por chamada, contra um `job_timeout` de
# 240s que o turno ja estoura (`resumir` + `classificar` + `desambiguar` dao
# 360s -- ver o comentario de `job_timeout` em `workers/main.py`). Moderar as
# duas pontas com aquele cliente somaria 240s a um orcamento ja estourado; com
# 5s e sem retentativa soma 10s, que e ruido contra a folga que ja nao existe.
#
# Sem retentativa de proposito: uma segunda tentativa dobraria o teto para
# ganhar pouco, e "nao deu para moderar" ja tem tratamento definido nas duas
# pontas. Reduzir a chance de o turno estourar e a TEC-228.
TIMEOUT_DA_MODERACAO_SEGUNDOS = 5.0
MAX_TENTATIVAS_DA_MODERACAO = 0

# Duas palavras cabem aqui com folga; o teto continua existindo para fazer do
# truncamento um erro tipado em vez de um veredito pela metade -- "BLOQUEAR
# DISCRIMIN" nao e resposta. Sao tokens de SAIDA, duas vezes por turno, no
# modelo mais barato da configuracao.
MAX_TOKENS_DO_VEREDITO = 16

_BLOQUEAR = "BLOQUEAR"
_LIBERAR = "LIBERAR"

# Tolerante na forma, rigido no conteudo. O protocolo pede a palavra (e a
# categoria, quando for BLOQUEAR) sem pontuacao e o modelo quase sempre obedece,
# mas "quase" e caro: `BLOQUEAR.` comparado por igualdade vira
# `ModeracaoIndisponivel`, e na saida a indisponibilidade propaga -- a linha
# vira FAILED, o sweeper roda o turno inteiro de novo pagando `classificar`
# outra vez ate `sweep_max_attempts`, e depois disso fica em FAILED para
# sempre, sem o lead receber nada. Trocar um turno por um ponto final e o
# negocio errado.
#
# Uma ou duas corridas de letras, cercadas so de nao-letras. Continua **nao**
# procurando a palavra dentro de uma frase: `nao vou BLOQUEAR` tem tres
# corridas e fica fora do protocolo, como sempre esteve -- e e por isso que o
# grupo so aceita ATE duas corridas, nunca mais: uma terceira corrida (como em
# "LIBERAR se quiser") nao encontra onde entrar na expressao e o fullmatch
# falha, preservando a garantia de que o desconhecido nunca vira liberado.
_ATE_DUAS_PALAVRAS = re.compile(r"[^A-Z]*([A-Z]+)(?:[^A-Z]+([A-Z]+))?[^A-Z]*")


def _protocolo_de(direcao: Direcao) -> str:
    """O que se pede tem que ser o que se le.

    As categorias vem de `CATEGORIAS_POR_DIRECAO` e nao de uma lista escrita a
    mao aqui: duas copias do vocabulario divergiriam na primeira card que
    acrescentasse categoria, e a divergencia seria silenciosa -- o modelo
    responderia um rotulo que a leitura nao reconhece, e toda a auditoria
    viraria OUTRO.
    """
    categorias = " | ".join(sorted(CATEGORIAS_POR_DIRECAO[direcao]))
    return (
        f"Responda com {_LIBERAR} sozinho, ou com {_BLOQUEAR} seguido de uma "
        f"categoria. Sem pontuacao e sem explicacao.\n"
        f"Categorias: {categorias}"
    )


SISTEMA_DA_ENTRADA = (
    "Voce e um filtro de conteudo de uma imobiliaria brasileira. Recebe a "
    "mensagem que um lead enviou por WhatsApp e decide se ela pode entrar no "
    "atendimento.\n\n"
    "BLOQUEAR quando houver conteudo discriminatorio (racismo, machismo, "
    "homofobia, xenofobia, capacitismo, intolerancia religiosa, restricao de "
    "vizinhanca por composicao familiar), ameaca, assedio sexual, ou "
    "incitacao a violencia -- inclusive de forma velada, ironica ou em tom "
    "de piada.\n\n"
    "LIBERAR o resto, e o resto e a maioria. Lead irritado, reclamacao dura, "
    "giria, palavrao usado como enfase ('que porcaria de atendimento', 'caramba'), "
    "cobranca, ironia sobre o servico e pergunta fora do assunto imobiliario "
    "sao todos LIBERAR. Bloquear lead legitimo custa atendimento e e erro, nao "
    "cautela.\n\n" + _protocolo_de(Direcao.ENTRADA)
)

SISTEMA_DA_SAIDA = (
    "Voce e um filtro de conteudo de uma imobiliaria brasileira. Recebe um "
    "texto que o atendente virtual da empresa esta a ponto de enviar a um lead "
    "e decide se a empresa pode dizer isso.\n\n"
    "O criterio e mais estrito que para a fala do lead, porque aqui e a "
    "empresa falando em nome proprio. BLOQUEAR conteudo discriminatorio, "
    "ofensa ao lead, ameaca, insinuacao sexual, conselho juridico ou "
    "financeiro apresentado como certeza, promessa de desconto ou negociacao "
    "de valor em nome da imobiliaria, e qualquer criterio de atendimento "
    "baseado em caracteristica pessoal do lead (origem, religiao, familia, "
    "deficiencia).\n\n"
    "LIBERAR resposta comercial normal, inclusive negativa: dizer que nao ha "
    "imovel no perfil, que o valor esta fora da faixa, ou pedir mais "
    "informacao, e atendimento correto. Dizer que o valor esta fora da faixa "
    "do lead nao e negociar: e informar.\n\n" + _protocolo_de(Direcao.SAIDA)
)

_SISTEMA_POR_DIRECAO = {
    Direcao.ENTRADA: SISTEMA_DA_ENTRADA,
    Direcao.SAIDA: SISTEMA_DA_SAIDA,
}


@lru_cache
def get_moderation_client() -> AsyncAnthropic:
    """Cliente separado do `get_client()` do turno, com teto proprio.

    Construido sob demanda e nao no import, pelo mesmo motivo de
    `infra/anthropic.py`: importar o modulo nao pode exigir credencial.
    """
    chave = get_settings().anthropic_api_key
    if not chave:
        raise ConfiguracaoInsegura(
            "ANTHROPIC_API_KEY nao configurada. A moderacao da TEC-233 precisa "
            "dela; defina no .env ou no ambiente antes de subir o worker."
        )
    return AsyncAnthropic(
        api_key=chave,
        timeout=TIMEOUT_DA_MODERACAO_SEGUNDOS,
        max_retries=MAX_TENTATIVAS_DA_MODERACAO,
    )


class ModeradorAnthropic:
    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito:
        """Classificacao binaria. Qualquer duvida vira `ModeracaoIndisponivel`.

        Nunca interpreta o desconhecido como liberado: isso transformaria um
        moderador confuso em um moderador desligado, e desligado em silencio.
        Quem chama decide o que fazer com a indisponibilidade, e a decisao e
        assimetrica entre as duas pontas.
        """
        settings = get_settings()
        kwargs: dict[str, Any] = {
            "model": settings.modelo_moderacao,
            "max_tokens": MAX_TOKENS_DO_VEREDITO,
            "system": _SISTEMA_POR_DIRECAO[direcao],
            "messages": [{"role": "user", "content": texto}],
        }
        comecou = time.perf_counter()
        try:
            resposta = cast(Message, await get_moderation_client().messages.create(**kwargs))
        except Exception as exc:
            # Nunca interpola `texto` nem `str(exc)`: o primeiro e conteudo do
            # lead ou da empresa, e o segundo pode ecoar o corpo enviado.
            #
            # `motivo_do_provedor` nao afrouxa isso (TEC-237): ele devolve
            # `None` para qualquer excecao que nao seja `APIStatusError`, e
            # para essas devolve o corpo de erro que o servidor escreveu. Foi
            # este caminho que somou 41 das 91 falhas cegas de 28/08.
            raise ModeracaoIndisponivel(motivo_do_provedor(exc) or type(exc).__name__) from exc

        # Antes de qualquer recusa abaixo: a chamada ja foi paga, e o veredito
        # fora do protocolo custa igual ao veredito bom. Registrar so no
        # caminho feliz esconderia justamente o gasto que nao produziu nada.
        #
        # So numeros, direcao e id de modelo -- a mesma regra do log do
        # classificador, e aqui ela aperta: o que a moderacao ve e conteudo do
        # lead ou da empresa, e `resposta` carrega o veredito sobre ele.
        # Nunca o texto julgado, nunca a resposta.
        log.info(
            "moderacao.avaliada",
            modelo=resposta.model,
            direcao=direcao.value,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=int((time.perf_counter() - comecou) * 1000),
            custo_usd=str(
                custo_em_dolar(
                    resposta.model, resposta.usage.input_tokens, resposta.usage.output_tokens
                )
            ),
        )

        if resposta.stop_reason != "end_turn":
            raise ModeracaoIndisponivel(f"stop_reason={resposta.stop_reason!r}")

        bruto = "".join(b.text for b in resposta.content if b.type == "text").strip().upper()
        achado = _ATE_DUAS_PALAVRAS.fullmatch(bruto)
        if achado is None:
            # Sem o valor recebido na mensagem: ele pode carregar o texto julgado.
            raise ModeracaoIndisponivel("veredito fora do protocolo")
        palavra, segunda = achado.group(1), achado.group(2)

        if palavra == _LIBERAR and segunda is None:
            return Veredito(bloqueado=False, motivo=f"{direcao.value}:{_LIBERAR}")
        if palavra == _BLOQUEAR and segunda not in (_BLOQUEAR, _LIBERAR):
            # Duas palavras em que a segunda tambem e um veredito nao sao
            # rotulo mal escolhido: sao o modelo em duvida entre os dois
            # desfechos, e resolver a duvida dele para o lado do bloqueio
            # recusaria lead legitimo -- o falso positivo mais caro deste
            # sistema. Por isso `BLOQUEAR LIBERAR` cai fora, junto com o resto.
            categoria = segunda if segunda in CATEGORIAS_POR_DIRECAO[direcao] else CATEGORIA_OUTRO
            return Veredito(
                bloqueado=True,
                motivo=f"{direcao.value}:{_BLOQUEAR}:{categoria}",
                categoria=categoria,
            )
        raise ModeracaoIndisponivel("veredito fora do protocolo")
