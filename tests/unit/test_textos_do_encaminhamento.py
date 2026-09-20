"""Os textos que o lead recebe ao ser encaminhado. TEC-137.

Puro: nao toca banco nem modelo. O que se testa aqui e o que e PROPRIO destes
dois textos: serem distintos, nao terminarem em pergunta, e o sufixo de fora
da janela formatar as horas sem marcar hora de resposta.

**A promessa de contato nao e guardada aqui desde a TEC-286.** Ela era, e por
tres palavras (`avisei`/`avisamos`/`avisado`) -- alcance curto demais: o texto
do teto de perguntas prometia contato sem usar nenhuma das tres e passou por
tres revisoes. Quem guarda isso hoje e `tests/unit/test_promessa_ao_lead.py`,
que barra frases e roda sobre todo literal ao lead, estes dois inclusive.
"""

import pytest

from mobia.app.config import get_settings
from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
)


def test_os_dois_textos_sao_distintos() -> None:
    """Quem quer vender e quem tem duvida de contrato nao sao a mesma fila.

    O Gherkin da card pede etiquetas distintas (`venda-imovel` e
    `suporte-contrato`) porque sao trabalhos diferentes para o corretor. Um
    texto generico serviria mal a quem JA e cliente e so tem duvida de reajuste.
    """
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA != TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE


def test_o_sufixo_de_fora_da_janela_nomeia_o_horario_e_os_dias() -> None:
    """O sufixo formata as HORAS a partir da configuracao e escreve os DIAS por extenso.

    As horas vem de `Settings` porque ate a TEC-285 o Gherkin da TEC-137 dizia
    "das 9h as 19h" enquanto a janela real era 9h-18h, e citar o numero da card
    faria o texto mentir. A TEC-285 fechou essa divergencia subindo a janela --
    o numero passou a bater --, mas a regra de formatar em vez de literalizar
    fica: ela nao existia por causa daquela divergencia especifica.

    Os dias sao literais porque eles nao vem de `Settings`: sao regra em
    codigo, em `_DOMINGO` (`domain/humano/deteccao.py`), e o comentario de la
    registra que mudar os dias e mudanca de codigo E de texto.
    """
    settings = get_settings()
    formatado = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio, fim=settings.atendimento_horario_fim
    )

    assert str(settings.atendimento_horario_inicio) in formatado
    assert str(settings.atendimento_horario_fim) in formatado
    assert "{inicio}" not in formatado
    assert "de segunda a sábado" in formatado


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

    O whatsapp ao corretor (TEC-281) continua so registrando, e mesmo o
    e-mail (TEC-280, que ja entrega por SMTP) so garante que o servidor
    aceitou, nao que uma PESSOA abriu a fila e respondeu. "a resposta vem no
    próximo horário" nao e a promessa banida de
    `test_nenhum_texto_promete_que_alguem_foi_avisado`, mas e a vizinha dela:
    afirma um prazo que o sistema nao controla.

    A frase espelha a irma escrita ontem pela TEC-143 para a MESMA situacao,
    `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` em `domain/humano/deteccao.py`,
    que ja dizia "pode demorar até o próximo horário". Duas redacoes para o
    mesmo fato seriam duas coisas para manter em sincronia.
    """
    settings = get_settings()
    formatado = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio, fim=settings.atendimento_horario_fim
    )
    assert "pode demorar" in formatado
    assert "vem no próximo" not in formatado
