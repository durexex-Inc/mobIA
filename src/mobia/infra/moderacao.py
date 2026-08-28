from functools import lru_cache
from typing import Any, cast

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel, Veredito

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

# O veredito e uma palavra. `max_tokens` curto faz do truncamento um erro
# tipado em vez de um veredito pela metade -- "BLOQ" nao e resposta.
MAX_TOKENS_DO_VEREDITO = 8

_BLOQUEAR = "BLOQUEAR"
_LIBERAR = "LIBERAR"

_PROTOCOLO = (
    f"Responda com exatamente uma palavra, sem pontuacao e sem explicacao: "
    f"{_BLOQUEAR} ou {_LIBERAR}."
)

SISTEMA_DA_ENTRADA = (
    "Voce e um filtro de conteudo de uma imobiliaria brasileira. Recebe a "
    "mensagem que um lead enviou por WhatsApp e decide se ela pode entrar no "
    "atendimento.\n\n"
    "BLOQUEAR quando houver conteudo discriminatorio (racismo, machismo, "
    "homofobia, xenofobia, capacitismo, intolerancia religiosa), ameaca, "
    "assedio sexual, ou incitacao a violencia -- inclusive de forma velada, "
    "ironica ou em tom de piada.\n\n"
    "LIBERAR o resto, e o resto e a maioria. Lead irritado, reclamacao dura, "
    "girea, palavrao usado como enfase ('que porcaria de atendimento', 'caramba'), "
    "cobranca, ironia sobre o servico e pergunta fora do assunto imobiliario "
    "sao todos LIBERAR. Bloquear lead legitimo custa atendimento e e erro, nao "
    "cautela.\n\n" + _PROTOCOLO
)

SISTEMA_DA_SAIDA = (
    "Voce e um filtro de conteudo de uma imobiliaria brasileira. Recebe um "
    "texto que o atendente virtual da empresa esta a ponto de enviar a um lead "
    "e decide se a empresa pode dizer isso.\n\n"
    "O critterio e mais estrito que para a fala do lead, porque aqui e a "
    "empresa falando em nome proprio. BLOQUEAR conteudo discriminatorio, "
    "ofensa ao lead, ameaca, insinuacao sexual, conselho juridico ou "
    "financeiro apresentado como certeza, e qualquer criterio de atendimento "
    "baseado em caracteristica pessoal do lead (origem, religiao, familia, "
    "deficiencia).\n\n"
    "LIBERAR resposta comercial normal, inclusive negativa: dizer que nao ha "
    "imovel no perfil, que o valor esta fora da faixa, ou pedir mais "
    "informacao, e atendimento correto.\n\n" + _PROTOCOLO
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
        try:
            resposta = cast(Message, await get_moderation_client().messages.create(**kwargs))
        except Exception as exc:
            # Nunca interpola `texto` nem `str(exc)`: o primeiro e conteudo do
            # lead ou da empresa, e o segundo pode ecoar o corpo enviado.
            raise ModeracaoIndisponivel(type(exc).__name__) from exc

        if resposta.stop_reason != "end_turn":
            raise ModeracaoIndisponivel(f"stop_reason={resposta.stop_reason!r}")

        bruto = "".join(b.text for b in resposta.content if b.type == "text").strip().upper()
        if bruto == _BLOQUEAR:
            return Veredito(bloqueado=True, motivo=f"{direcao.value}:{_BLOQUEAR}")
        if bruto == _LIBERAR:
            return Veredito(bloqueado=False, motivo=f"{direcao.value}:{_LIBERAR}")
        # Sem o valor recebido na mensagem: ele pode carregar o texto julgado.
        raise ModeracaoIndisponivel("veredito fora do protocolo")
