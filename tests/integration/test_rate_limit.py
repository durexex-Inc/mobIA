"""O limitador de janela deslizante contra Redis real (TEC-205).

Integracao e nao unitario de proposito: o que este modulo afirma -- que quatro
comandos num pipeline produzem uma janela deslizante correta -- e afirmacao
sobre o Redis, nao sobre aritmetica nossa. Um duble provaria so o duble.

O relogio entra por parametro (`agora`), entao nenhum teste dorme e nenhum
depende de onde caiu a borda do minuto.
"""

import math

import pytest

from mobia.infra.rate_limit import (
    JANELA_DE_UM_MINUTO,
    chave_de_ip,
    chave_de_numero,
    consumir,
)


async def test_abaixo_do_limite_permite(redis_pool) -> None:
    for i in range(3):
        consumo = await consumir(
            redis_pool, chave="t:1", limite=3, janela_segundos=60.0, agora=1000.0 + i
        )
        assert consumo.permitido is True
    assert consumo.volume == 3


async def test_o_excedente_e_bloqueado(redis_pool) -> None:
    for i in range(3):
        await consumir(redis_pool, chave="t:2", limite=3, janela_segundos=60.0, agora=1000.0 + i)
    consumo = await consumir(redis_pool, chave="t:2", limite=3, janela_segundos=60.0, agora=1003.0)
    assert consumo.permitido is False
    assert consumo.volume == 4


async def test_a_janela_desliza(redis_pool) -> None:
    """O mais antigo sai da janela e a vaga volta -- sem esperar 60s."""
    for i in range(3):
        await consumir(redis_pool, chave="t:3", limite=3, janela_segundos=60.0, agora=1000.0 + i)
    # 1061 deixa 1000 e 1001 para tras (a remocao e por score <= agora-janela)
    # e mantem 1002. Uma vaga livre, entao permite.
    consumo = await consumir(redis_pool, chave="t:3", limite=3, janela_segundos=60.0, agora=1061.0)
    assert consumo.permitido is True
    assert consumo.volume == 2


async def test_limite_zero_desliga(redis_pool) -> None:
    """Zero desliga, como `debounce_de_rajada_segundos`. Nem toca no Redis."""
    for _ in range(50):
        consumo = await consumir(
            redis_pool, chave="t:4", limite=0, janela_segundos=60.0, agora=1000.0
        )
        assert consumo.permitido is True
    assert await redis_pool.exists("t:4") == 0


async def test_pool_ausente_permite(redis_pool) -> None:
    """Fail-open: um guarda indisponivel nao pode virar a negacao de servico
    que ele existia para evitar. Mesmo contrato de `moderar_entrada_e_marcar`.
    """
    consumo = await consumir(None, chave="t:5", limite=1, janela_segundos=60.0)
    assert consumo.permitido is True
    assert consumo.volume == 0


async def test_a_chave_expira_sozinha(redis_pool) -> None:
    await consumir(redis_pool, chave="t:6", limite=5, janela_segundos=60.0, agora=1000.0)
    assert 0 < await redis_pool.ttl("t:6") <= 60


async def test_chaves_de_escopos_diferentes_nao_se_misturam(redis_pool) -> None:
    assert chave_de_numero("whatsapp", "5511999") != chave_de_ip("5511999")
    assert chave_de_numero("whatsapp", "5511999").startswith("ratelimit:")
    assert chave_de_ip("203.0.113.7").startswith("ratelimit:")


@pytest.mark.parametrize("janela", [0.5, 60.0, 90.0])
async def test_o_ttl_cobre_a_janela_inteira(redis_pool, janela: float) -> None:
    """`EXPIRE` so aceita inteiro: arredondar para baixo apagaria a janela
    antes de ela fechar, e o limite abriria mais cedo do que devia.
    """
    await consumir(
        redis_pool, chave=f"t:7:{janela}", limite=5, janela_segundos=janela, agora=1000.0
    )
    # `- 1` porque o TTL e inteiro e ja pode ter descontado o segundo
    # corrente entre o EXPIRE e a leitura. Sem essa folga a assercao e flaky
    # por construcao, nao por ambiente.
    assert await redis_pool.ttl(f"t:7:{janela}") >= math.ceil(janela) - 1


def test_a_janela_do_card_e_de_um_minuto() -> None:
    assert JANELA_DE_UM_MINUTO == 60.0
