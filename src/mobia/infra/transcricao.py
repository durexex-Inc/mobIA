"""A Whisper API, atras da porta `TranscritorPort`. TEC-131, D2.

Mesmo cliente do `infra/embeddings.py` -- mesma chave, mesmo SDK --, com teto e
tentativas proprios. **30s e zero retentativas** porque o lead esta esperando:
o turno fica parado ate este job gravar um desfecho (D1), e o desfecho para
"nao deu" ja existe e e rapido -- o pedido de texto. Uma retentativa dobraria a
espera para ganhar um audio que o lead pode reescrever em dez segundos.

**Os 30s nao foram medidos**, pelo mesmo motivo que o `TETO_DA_CONSULTA_DO_TURNO`
de `infra/embeddings.py` registra: nao ha chave do OpenAI nesta maquina. Sao a
estimativa para um audio de ate dois minutos; quem tiver a chave mede e corrige,
e `PRAZO_DA_TRANSCRICAO` (`domain/midia/audio.py`) tem de continuar cobrindo o
numero novo.
"""

from openai import OpenAIError

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.domain.midia.transcricao import Transcricao, TranscricaoIndisponivel
from mobia.infra.embeddings import get_client

TIMEOUT_SEGUNDOS = 30.0
MAX_TENTATIVAS = 0


class TranscritorWhisper:
    async def transcrever(self, dados: bytes, extensao: str) -> Transcricao:
        """Transcreve em portugues e devolve o texto e a duracao medida.

        `verbose_json`, e nao o `json` padrao, porque e o unico formato que traz
        `duration` -- a segunda conferencia do limite (D2, passo 6).

        Toda falha vira `TranscricaoIndisponivel` com o NOME do tipo, nunca o
        `str()`: o corpo de erro do SDK pode ecoar o pedido, e o pedido aqui e
        a voz do lead.
        """
        try:
            cliente = get_client().with_options(max_retries=MAX_TENTATIVAS)
            resposta = await cliente.audio.transcriptions.create(
                model=get_settings().transcricao_modelo,
                # O nome e so a extensao: e por ela que a API escolhe o
                # decodificador, e um nome com o id da mensagem iria parar no
                # log do provedor sem servir para nada.
                file=(f"audio.{extensao}", dados),
                language="pt",
                response_format="verbose_json",
                timeout=TIMEOUT_SEGUNDOS,
            )
        except (OpenAIError, ConfiguracaoInsegura) as exc:
            raise TranscricaoIndisponivel(type(exc).__name__) from exc
        return Transcricao(texto=resposta.text, duracao_segundos=resposta.duration)
