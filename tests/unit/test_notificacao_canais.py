import logging

import pytest

from mobia.domain.notificacao.canais import EmailRegistrado, WhatsAppRegistrado

SENTINELA = "SENTINELA-CORPO o lead mora na Rua das Palmeiras"


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_canal_tem_nome_e_nao_levanta(canal, caplog: pytest.LogCaptureFixture) -> None:
    assert canal.nome

    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="lead quente", corpo=SENTINELA)

    assert "notificacao.nao_entregue" in caplog.text


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_log_nunca_carrega_o_corpo(canal, caplog: pytest.LogCaptureFixture) -> None:
    """O corpo carrega o resumo, que e prosa sobre o que o lead escreveu."""
    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="lead quente", corpo=SENTINELA)

    assert SENTINELA not in caplog.text


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_log_diz_por_que_nao_entregou(canal, caplog: pytest.LogCaptureFixture) -> None:
    """Sem o motivo, o log vira ruido que ninguem sabe interpretar."""
    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="a", corpo="b")

    assert "motivo" in caplog.text
