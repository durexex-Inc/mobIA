"""TEC-131, D2: o que se sabe do audio antes de pagar a transcricao."""

import pytest
from conftest import ogg_opus

from mobia.domain.midia.audio import (
    dentro_do_limite,
    duracao_do_ogg_opus,
    extensao_para_transcricao,
)


@pytest.mark.parametrize("segundos", [1.0, 40.0, 120.0, 150.0])
def test_a_duracao_do_ogg_opus_desconta_o_pre_skip(segundos: float) -> None:
    assert duracao_do_ogg_opus(ogg_opus(segundos)) == pytest.approx(segundos)


def test_o_pre_skip_e_lido_do_opushead_e_nao_suposto() -> None:
    # Com um pre-skip diferente do padrao do encoder, a duracao continua certa:
    # se o parser supusesse 312, esta afirmacao erraria por 0,02s.
    assert duracao_do_ogg_opus(ogg_opus(40.0, pre_skip=3840)) == pytest.approx(40.0)


def test_arquivo_truncado_para_na_ultima_pagina_inteira() -> None:
    # Cortada no meio da pagina de audio, sobra so o cabecalho: nao ha granule
    # de audio nenhum, e inventar uma duracao seria pior que nao saber.
    inteiro = ogg_opus(40.0)
    assert duracao_do_ogg_opus(inteiro[:-10]) is None


def test_um_ogg_que_nao_e_opus_nao_tem_duracao() -> None:
    vorbis = ogg_opus(40.0).replace(b"OpusHead", b"\x01vorbis\x00", 1)
    assert duracao_do_ogg_opus(vorbis) is None


def test_um_mp3_nao_tem_duracao() -> None:
    assert duracao_do_ogg_opus(b"ID3\x04\x00" + b"\x00" * 200) is None


def test_bytes_vazios_nao_tem_duracao() -> None:
    assert duracao_do_ogg_opus(b"") is None


@pytest.mark.parametrize(
    ("duracao", "cabe"),
    [(119.9, True), (120.0, True), (120.9, True), (121.0, False), (150.0, False)],
)
def test_o_limite_e_no_segundo_inteiro(duracao: float, cabe: bool) -> None:
    assert dentro_do_limite(duracao, 120) is cabe


@pytest.mark.parametrize(
    ("mime", "extensao"),
    [
        ("audio/ogg; codecs=opus", "ogg"),
        ("audio/OGG", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "m4a"),
        ("audio/aac", None),
        ("audio/amr", None),
        ("", None),
    ],
)
def test_so_vai_para_a_whisper_o_que_ela_aceita(mime: str, extensao: str | None) -> None:
    assert extensao_para_transcricao(mime) == extensao
