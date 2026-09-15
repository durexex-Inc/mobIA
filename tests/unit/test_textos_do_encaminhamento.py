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


def test_o_sufixo_nao_promete_quando_a_resposta_chega() -> None:
    """R7 da revisao final: o sufixo hedgea, e nao marca hora.

    Nada notifica ninguem enquanto TEC-280 e TEC-281 estiverem abertas -- a
    resposta depende de uma PESSOA abrir a fila. "a resposta vem no proximo
    horario" nao e a promessa banida de `test_nenhum_texto_promete_que_alguem_
    foi_avisado`, mas e a vizinha dela: afirma um prazo que o sistema nao
    controla.

    A frase espelha a irma escrita ontem pela TEC-143 para a MESMA situacao,
    `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` em `domain/humano/deteccao.py`,
    que ja dizia "pode demorar ate o proximo horario". Duas redacoes para o
    mesmo fato seriam duas coisas para manter em sincronia.
    """
    formatado = SUFIXO_FORA_DA_JANELA.format(inicio=9, fim=18)
    assert "pode demorar" in formatado
    assert "vem no próximo" not in formatado
