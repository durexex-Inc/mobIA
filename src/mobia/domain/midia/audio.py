"""O que se sabe do audio antes de pagar a transcricao. TEC-131, D2.

**A duracao se mede aqui, e nao pela Whisper, porque a card manda NAO
transcrever o audio longo.** Perguntar a duracao ao provedor seria pagar a
transcricao para descobrir que ela nao devia ter sido feita. A nota de voz do
WhatsApp e sempre Ogg/Opus, e para esse formato a conta e barata: a ultima
pagina Ogg diz quantas amostras o fluxo tem.

So Ogg/Opus, e sem dependencia nova. O `mutagen` mediria todo formato, mas e
GPL. Os outros formatos (MP3, M4A, AAC, AMR) chegam por audio encaminhado, nao
por nota de voz, e para eles a duracao sai da resposta da Whisper, depois --
ver o passo 6 da D2 no desenho.
"""

import math
import struct
from datetime import timedelta

# Quanto tempo um audio sem desfecho de transcricao segura o turno da rajada
# (D1). Cobre o pior caso do job -- ate 10s para resolver na Graph API, o
# download, e os 30s da Whisper sem retentativa -- com folga para a fila. Passado
# isso, o job se perdeu, e o turno segue sem a transcricao em vez de esperar
# para sempre.
PRAZO_DA_TRANSCRICAO = timedelta(seconds=90)

# O Opus conta amostras a 48 kHz qualquer que seja a taxa do audio original
# (RFC 7845, secao 4): o granule position de toda pagina esta nessa escala.
_AMOSTRAS_POR_SEGUNDO_DO_OPUS = 48_000

# Cabecalho fixo de uma pagina Ogg (RFC 3533): "OggS", versao, tipo, granule
# (int64), serial, sequencia, CRC e o numero de segmentos.
_CABECALHO_DA_PAGINA = struct.Struct("<4sBBqIIIB")

# O que a Whisper aceita, pela extensao do nome do arquivo -- e ela que decide o
# decodificador. AAC cru (ADTS) e AMR ficam de fora: a API os recusa, e manda-los
# seria pagar uma chamada que volta erro.
_EXTENSAO_DO_TIPO = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def extensao_para_transcricao(mime: str) -> str | None:
    """A extensao com que o arquivo vai para a Whisper, ou None se ela nao aceita."""
    # Mesma limpeza de `tipo_permitido`: a Meta manda "audio/ogg; codecs=opus".
    return _EXTENSAO_DO_TIPO.get(mime.split(";", 1)[0].strip().lower())


def dentro_do_limite(duracao_segundos: float, limite_segundos: int) -> bool:
    """O audio cabe no limite?

    **O corte e no segundo inteiro, e nao no valor fracionario.** Um audio que o
    WhatsApp mostra como `2:00` pode medir 120,4s, e a card manda aceitar o
    "exatamente 120 segundos". Comparar com `<= 120` recusaria justamente esse.
    """
    return math.floor(duracao_segundos) <= limite_segundos


def duracao_do_ogg_opus(dados: bytes) -> float | None:
    """A duracao, em segundos, de um fluxo Ogg/Opus -- ou None se nao for um.

    Percorre as paginas em ordem, pelas tabelas de segmento, em vez de procurar
    o ultimo "OggS" com `rfind`: o padrao pode aparecer dentro do audio
    comprimido, e uma pagina falsa no fim daria uma duracao inventada. Arquivo
    truncado no meio de uma pagina para na ultima pagina inteira, que e o que
    um decodificador tocaria.

    A duracao e o granule da ultima pagina do fluxo menos o pre-skip do
    `OpusHead` (RFC 7845, secao 4.2), sobre 48 kHz. So granule positivo conta:
    -1 marca pagina em que nenhum pacote termina, e 0 e o das paginas de
    cabecalho (`OpusHead`, `OpusTags`). Sem este corte, um arquivo cortado logo
    depois dos cabecalhos mediria 0s e passaria pelo limite como audio curto.
    """
    posicao = 0
    serial_do_opus: int | None = None
    pre_skip = 0
    ultimo_granule: int | None = None
    while posicao + _CABECALHO_DA_PAGINA.size <= len(dados):
        captura, _versao, _tipo, granule, serial, _seq, _crc, segmentos = (
            _CABECALHO_DA_PAGINA.unpack_from(dados, posicao)
        )
        if captura != b"OggS":
            break
        inicio_da_tabela = posicao + _CABECALHO_DA_PAGINA.size
        tabela = dados[inicio_da_tabela : inicio_da_tabela + segmentos]
        if len(tabela) < segmentos:
            break
        inicio_do_corpo = inicio_da_tabela + segmentos
        fim_do_corpo = inicio_do_corpo + sum(tabela)
        if fim_do_corpo > len(dados):
            break
        corpo = dados[inicio_do_corpo:fim_do_corpo]

        if serial_do_opus is None:
            # A primeira pagina do fluxo carrega o OpusHead. Sem ele o fluxo nao
            # e Opus -- Vorbis, por exemplo, conta amostras em outra escala.
            if not corpo.startswith(b"OpusHead") or len(corpo) < 12:
                return None
            serial_do_opus = serial
            pre_skip = struct.unpack_from("<H", corpo, 10)[0]
        elif serial == serial_do_opus and granule > 0:
            ultimo_granule = granule
        posicao = fim_do_corpo

    if ultimo_granule is None:
        return None
    return max(0, ultimo_granule - pre_skip) / _AMOSTRAS_POR_SEGUNDO_DO_OPUS
