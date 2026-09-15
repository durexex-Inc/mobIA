"""O encaminhamento de VENDER_IMOVEL e SUPORTE_CONTRATO. TEC-137.

O handoff, a etiqueta, o log e o resumo destas duas intencoes ja existem desde
a TEC-174 e nao sao assunto deste arquivo -- `test_handoff_no_turno.py` cuida
deles. O que se afirma aqui e o que o LEAD recebe: um texto nosso em lugar da
prosa do modelo, que podia carregar a pergunta de qualificacao de COMPRADOR
que a RN-03.4 tira destas duas conversas.
"""

from typing import Any

import pytest
from sqlalchemy import text

from mobia.app.config import get_settings
from mobia.domain.agente import turno as turno_mod
from mobia.domain.agente.schemas import Intencao
from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
)
from mobia.domain.context.models import LeadQualification
from mobia.domain.moderacao.port import TEXTO_NEUTRO_DE_SAIDA

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_turno_teto_de_perguntas.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"

# Pergunta de qualificacao de COMPRADOR -- exatamente o que a RN-03.4 tira
# destas duas intencoes. Ate a TEC-137 era isto que saia.
PROSA_DO_MODELO = "Legal! Em que bairro voce procura e qual a sua faixa de preco?"


@pytest.fixture(autouse=True)
def janela_aberta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Congela a janela de atendimento em ABERTA para todo teste deste arquivo.

    Sem isto o arquivo passaria ou reprovaria conforme a HORA em que a suite
    roda: `dentro_da_janela_de_atendimento` le o relogio real, e fora do
    expediente todo texto esperado ganharia o `SUFIXO_FORA_DA_JANELA`. O teste
    de fora da janela desfaz isto localmente, e e o unico que precisa.
    """
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: True)


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma fala anterior do lead para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Sem isto a identificacao da RN-04.1 e concatenada NO MESMO texto que sai, e
    as assertas de lista exata deste arquivo comparariam contra uma string com
    um prefixo que nao e sobre encaminhamento nenhum. Mesmo recurso, e pela
    mesma razao, que `test_turno_teto_de_perguntas.py`.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def _semear_estado(session: Any, *, perguntas_feitas: int) -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            perguntas_feitas=perguntas_feitas,
        )
    )
    await session.commit()


async def _handoffs(session: Any) -> list[dict]:
    resultado = await session.execute(
        text("SELECT gatilho, etiqueta FROM handoffs ORDER BY criado_em")
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_venda_de_imovel_entrega_o_texto_proprio_e_nao_a_prosa_do_modelo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O caso da card: o proprietario nao pode ser qualificado como comprador."""
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero colocar meu apartamento a venda com voces",
    )

    # Lista exata, e nao so a negativa: `PROSA_DO_MODELO not in entregues`
    # passaria com `entregues` VAZIO, ou seja com o turno sem entregar nada. A
    # forma de lista fixa que houve entrega, que houve UMA so, e deixa o "a
    # prosa nao saiu" como consequencia dela.
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert PROSA_DO_MODELO not in entregador.entregues

    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "venda-imovel"


async def test_suporte_de_contrato_entrega_o_outro_texto(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Fila diferente, texto diferente: quem tem duvida de contrato JA e cliente.

    A asserta contra o texto de VENDA nao e enfeite -- com um literal unico
    para as duas intencoes este teste continuaria verde, e o lead de suporte
    ouviria "que bom que pensou na gente para vender seu imovel".
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.SUPORTE_CONTRATO, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="tenho uma duvida sobre a clausula de reajuste do meu contrato",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE]
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA not in entregador.entregues
    assert PROSA_DO_MODELO not in entregador.entregues

    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "suporte-contrato"


async def test_fora_da_janela_o_texto_nomeia_o_horario(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3: as horas vem de `Settings`, e nao de um literal.

    Por isso a asserta compara contra o valor da configuracao formatado, e nao
    contra "9" e "18" escritos aqui: o Gherkin da card diz "das 9h as 19h"
    enquanto a janela real (TEC-143) e outra, e um numero transcrito neste
    arquivo fixaria a mentira em vez do comportamento.
    """
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: False)
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    settings = get_settings()
    sufixo = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA + sufixo]
    assert entregador.entregues[-1].startswith(TEXTO_DO_ENCAMINHAMENTO_DE_VENDA)
    assert str(settings.atendimento_horario_inicio) in entregador.entregues[-1]
    assert str(settings.atendimento_horario_fim) in entregador.entregues[-1]


async def test_dentro_da_janela_o_texto_nao_nomeia_horario(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A contraprova do teste acima. Sem ela um sufixo INCONDICIONAL passaria.

    A janela vem aberta pela fixture autouse deste arquivo, entao o unico jeito
    de esta asserta ser verdadeira e o sufixo depender de fato da janela.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    settings = get_settings()
    sufixo = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert sufixo not in entregador.entregues[-1]


async def test_o_segundo_turno_com_a_mesma_intencao_entrega_de_novo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """D2: a substituicao roda em TODO turno com a intencao, nao so no primeiro.

    A alternativa devolveria ao modelo a palavra no segundo turno, e com ela a
    pergunta de qualificacao que a regra proibe. O handoff continua sendo UM --
    `registrar_handoff` acumula em `gatilhos_adicionais` sem duplicar linha.
    """
    await _conversa_ja_existe(session)

    primeiro = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        primeiro,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    segundo = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        segundo,
        resumidor_fake(),
        contador_fake(),
        texto="e como funciona a avaliacao do imovel?",
    )

    assert primeiro.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert segundo.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert len(await _handoffs(session)) == 1


async def test_o_encaminhamento_vence_o_teto_de_perguntas(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Quem vai para a fila de venda nao precisa ouvir "ja perguntei bastante".

    Os dois textos prometem corretor, entao a diferenca nao e de gentileza: o
    do teto fala de qualificacao, que estas duas intencoes nao recebem.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(
            Intencao.VENDER_IMOVEL, perguntou=("urgencia",), resposta=PROSA_DO_MODELO
        ),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues


async def test_saida_bloqueada_vence_o_encaminhamento(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """`TEXTO_NEUTRO_DE_SAIDA` e a resposta declarada da politica de moderacao.

    Sobrepor a nossa a ela tornaria impossivel saber depois qual das duas agiu
    -- e a mesma guarda que o bloco do teto ja carrega, pela mesma razao.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_saida=True),
        texto="quero vender meu apartamento",
    )

    assert entregador.entregues == [TEXTO_NEUTRO_DE_SAIDA]
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA not in entregador.entregues
