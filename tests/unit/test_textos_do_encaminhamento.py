"""Os textos que o lead recebe ao ser encaminhado. TEC-137.

Puro: nao toca banco nem modelo. O que se testa aqui e o CONTEUDO -- em
especial que nenhum dos dois promete que alguem foi avisado, que e a frase que
este repo ja reescreveu duas vezes (TEC-174 e TEC-143).
"""

import pytest

from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
)


@pytest.mark.parametrize(
    "texto",
    [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA, TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE],
)
def test_nenhum_texto_promete_que_alguem_foi_avisado(texto: str) -> None:
    """A frase que o repo ja reescreveu duas vezes, barrada por teste.

    `notificacao/envio.py` proibe a promessa por escrito e nomeia o precedente:
    a TEC-174 escreveu "ja avisei um corretor" e teve de reescrever, porque
    nada notificava. A TEC-143 a reintroduziu e a revisao final a pegou. Criar
    handoff nao notifica ninguem -- TEC-280 e TEC-281 estao abertas.
    """
    minusculo = texto.lower()
    assert "avisei" not in minusculo
    assert "avisamos" not in minusculo
    assert "avisado" not in minusculo


def test_os_dois_textos_sao_distintos() -> None:
    """Quem quer vender e quem tem duvida de contrato nao sao a mesma fila.

    O Gherkin da card pede etiquetas distintas (`venda-imovel` e
    `suporte-contrato`) porque sao trabalhos diferentes para o corretor. Um
    texto generico serviria mal a quem JA e cliente e so tem duvida de reajuste.
    """
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA != TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE


def test_o_sufixo_de_fora_da_janela_nomeia_o_horario() -> None:
    """O sufixo formata a partir da configuracao, e nao cita numero fixo.

    O Gherkin da card diz "das 9h as 19h" e a janela real da TEC-143 e 9h-18h.
    Citar o numero da card num literal faria o texto mentir sobre o que o
    sistema faz -- por isso ele vem de `Settings`. A divergencia esta declarada
    na D3 do desenho.
    """
    formatado = SUFIXO_FORA_DA_JANELA.format(inicio=9, fim=18)
    assert "9" in formatado
    assert "18" in formatado
    assert "{inicio}" not in formatado


@pytest.mark.parametrize(
    "texto",
    [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA, TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE],
)
def test_nenhum_texto_faz_pergunta_de_qualificacao(texto: str) -> None:
    """A RN-03.4 tira estas intencoes do SDR, e o texto nao pode reintroduzi-la.

    Nao ha como provar ausencia de pergunta por analise de texto, entao o que
    esta guarda checa e o sinal mais grosseiro: o texto de encaminhamento nao
    termina em pergunta. Um "qual o bairro?" aqui seria a qualificacao de
    comprador entrando pela porta que a card fechou.
    """
    assert not texto.rstrip().endswith("?")
