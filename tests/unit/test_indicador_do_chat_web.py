"""O frame `digitando` do chat web. TEC-362, RN-04.7.

Unitario e nao de integracao: o que se exercita aqui e a FORMA do frame e o
relogio de `ate`. O caminho do turno ate o disparo ja e coberto por
`tests/integration/test_indicador_de_digitacao.py`, que nao precisa saber o
formato.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.outbound.web import DURACAO_DO_INDICADOR, WebIndicador, canal_da_sessao

SESSAO = "3f1a2b4c-5d6e-7f80-9a1b-2c3d4e5f6071"


class RedisEspiao:
    """So o `publish`, que e tudo que o indicador usa."""

    def __init__(self, ouvintes: int = 1) -> None:
        self.publicacoes: list[tuple[str, str]] = []
        self._ouvintes = ouvintes

    async def publish(self, canal: str, corpo: str) -> int:
        self.publicacoes.append((canal, corpo))
        return self._ouvintes


async def test_publica_no_canal_da_sessao_com_tipo_digitando() -> None:
    redis = RedisEspiao()

    await WebIndicador(redis).indicar_digitacao(
        provider_message_id=f"{SESSAO}:frame-1", de="widget", para=SESSAO
    )

    canal, corpo = redis.publicacoes[0]
    assert canal == canal_da_sessao(SESSAO)
    assert json.loads(corpo)["tipo"] == "digitando"


async def test_o_ate_e_agora_mais_a_duracao_em_iso_com_fuso() -> None:
    """Medido, e nao "perto de 25".

    Sem congelar o relogio a asserta viraria uma faixa, e uma faixa larga o
    bastante para nao flakear tambem passaria se a duracao mudasse.
    """
    redis = RedisEspiao()

    antes = datetime.now(UTC)
    await WebIndicador(redis).indicar_digitacao(provider_message_id="x", de="widget", para=SESSAO)
    depois = datetime.now(UTC)

    ate = datetime.fromisoformat(json.loads(redis.publicacoes[0][1])["ate"])
    assert ate.tzinfo is not None, "sem fuso, o cliente nao sabe contra que relogio comparar"
    assert antes + DURACAO_DO_INDICADOR <= ate <= depois + DURACAO_DO_INDICADOR


def test_a_duracao_e_a_do_whatsapp() -> None:
    """Paridade entre canais, que e a razao do numero (D2 do desenho).

    A Emenda E-01 da RN-04.7 registra que o indicador da Meta some apos 25 s.
    Um valor diferente aqui faria o MESMO turno parecer diferente em cada
    canal, sem nada no produto que justificasse.
    """
    assert DURACAO_DO_INDICADOR == timedelta(seconds=25)


async def test_sem_sessao_nao_publica() -> None:
    """`para` nulo: nao ha canal para onde publicar.

    O agendador nao barra este caso de proposito -- barra-lo la faria um turno
    do WhatsApp que hoje indica deixar de indicar. A ausencia vira log aqui,
    que e onde ela impede alguma coisa.
    """
    redis = RedisEspiao()

    await WebIndicador(redis).indicar_digitacao(provider_message_id="x", de="widget", para=None)

    assert redis.publicacoes == []


async def test_sem_redis_nao_levanta() -> None:
    await WebIndicador(None).indicar_digitacao(provider_message_id="x", de="widget", para=SESSAO)


async def test_zero_ouvintes_e_o_caso_normal_e_nao_levanta() -> None:
    """Aba fechada. Menos grave que na entrega: indicador nao vale nada fora
    do instante, entao nao ha o que recuperar depois."""
    redis = RedisEspiao(ouvintes=0)

    await WebIndicador(redis).indicar_digitacao(provider_message_id="x", de="widget", para=SESSAO)

    assert len(redis.publicacoes) == 1


async def test_a_excecao_do_redis_PROPAGA_crua() -> None:
    """Ao contrario de `WebOutbound._deliver`, que captura e loga.

    Nao e divergencia por descuido: `OutboundPort.send` tem semantica de
    excecao -- o tipo decide o desfecho do turno --, e
    `IndicadorDePresencaPort` declara o oposto, que o agendador engole tudo e
    loga. Capturar aqui daria duas linhas de log para o mesmo evento.
    """

    class RedisQueFalha:
        async def publish(self, canal: str, corpo: str) -> int:
            raise RuntimeError("redis fora")

    with pytest.raises(RuntimeError):
        await WebIndicador(RedisQueFalha()).indicar_digitacao(
            provider_message_id="x", de="widget", para=SESSAO
        )
