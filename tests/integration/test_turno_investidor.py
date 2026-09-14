"""A trilha do investidor vista do turno inteiro. TEC-153, RN-07.1 e RN-07.2.

O que so o turno inteiro consegue afirmar, porque nada disso e sobre uma
funcao isolada: quantas chamadas ao modelo o turno paga, qual das duas
respostas chega ao lead, quem vence quando desambiguacao e virada coincidem, e
o que sobra gravado em `lead_qualification` depois de tudo.

Mais dois que sao as armadilhas desta task. O perfil da RN-07.2 depende de
DOIS campos, e eles podem chegar em turnos diferentes -- classificar so com o
que veio neste turno devolveria `None` para um lead que ja respondeu os dois.
E na virada a chamada 1 foi descartada, entao a pergunta dela nao pode ser
marcada nem contada: seria queimar em silencio a chance de perguntar aquele
campo.
"""

from decimal import Decimal
from typing import Any

from conftest import RESPOSTA_DO_INVESTIDOR_FAKE  # type: ignore[import-not-found]
from sqlalchemy import select

from mobia.domain.agente.investidor import (
    ExtracaoDoInvestidor,
    Horizonte,
    RetornoEsperadoTipo,
)
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_turno_teto_de_perguntas.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"

# Abaixo de `LIMIAR_DE_DESAMBIGUACAO`, que e o que poe o turno no caminho do
# desambiguador. O mesmo valor que `BAIXA` em `test_turno.py`.
CONFIANCA_BAIXA = Decimal("0.45")


async def _semear_estado(session: Any, **campos: object) -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            **campos,
        )
    )
    await session.commit()


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma fala anterior do lead para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Sem isto a identificacao da RN-04.1 e concatenada NO MESMO texto que sai, e
    a asserta de que o texto entregue e o do investidor compararia contra uma
    string com prefixo. Mesmo recurso, e pela mesma razao, que
    `test_turno_teto_de_perguntas.py`.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def _linha(session: Any) -> LeadQualification:
    # `expire_all` antes de reler: a gravacao aconteceu noutra sessao, e o
    # objeto que esta aqui em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha


async def test_a_virada_para_investimento_chama_o_subagente(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A virada: o lead nao era investidor e passou a ser NESTE turno.

    E o unico turno com duas chamadas -- a generica, cuja resposta e
    descartada, e a do investidor, que e a entregue.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.chamadas == 1
    assert classificador.investidores == 1
    # O que o lead RECEBEU e a resposta da segunda chamada. Sem esta asserta o
    # teste ficaria verde com o subagente rodando e a prosa generica saindo.
    assert RESPOSTA_DO_INVESTIDOR_FAKE in entregador.entregues
    # A ferramenta de busca chega a chamada do investidor: sem ela ele nunca
    # receberia ficha de imovel nenhuma.
    assert classificador.portas_do_investidor[0] is not None


async def test_investidor_ja_conhecido_nao_paga_segunda_chamada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Do SEGUNDO turno em diante a chamada volta a ser uma so.

    A intencao ja esta no estado que `montar_contexto` leu, entao o prompt do
    investidor e escolhido ANTES da chamada e a generica nem acontece.

    O estado e semeado SEM `conversation_intent` de proposito, e nao por
    economia de fixture: e o retrato das duas fontes divergindo, que e o
    cenario real de um investidor que mandou um "obrigado" no meio da conversa
    -- `gravar_intencao` guarda INDEFINIDA, `campos_a_gravar` nao deixa
    INDEFINIDA sobrescrever a coluna do estado. Sem a guarda `not
    ja_e_investidor` em `virou_investidor`, o turno pede DUAS chamadas do
    investidor aqui, a primeira paga e descartada.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.chamadas == 0
    assert classificador.investidores == 1
    assert RESPOSTA_DO_INVESTIDOR_FAKE in entregador.entregues


async def test_desambiguacao_vence_a_virada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Ambiguo E investidor ao mesmo tempo: desambigua.

    Sem intencao confiavel nao ha trilha a escolher (D1), e gastar a chamada do
    investidor sobre um palpite que a confianca nao sustenta erraria a trilha
    alem de pagar por ela.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(Intencao.INVESTIMENTO, confianca=CONFIANCA_BAIXA)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1
    assert classificador.investidores == 0
    assert classificador.pergunta in entregador.entregues


async def test_o_perfil_e_gravado_a_partir_dos_campos(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Horizonte LONGO + ALUGUEL viram RENDA na coluna, gravados pelo turno."""
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        investidor=ExtracaoDoInvestidor(
            ticket_expressao="uns 800 mil",
            horizonte=Horizonte.LONGO,
            retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL,
        ),
    )

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = await _linha(session)
    assert linha.horizonte == "LONGO"
    assert linha.retorno_esperado_tipo == "ALUGUEL"
    assert linha.perfil_investidor == "RENDA"
    # `ticket_de` normaliza a fala do lead; o modelo nunca devolve centavos.
    assert linha.ticket_investimento_centavos == 80_000_000


async def test_a_virada_nao_marca_a_pergunta_da_chamada_descartada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Na virada, `gerada.perguntou` descreve um texto que ninguem leu.

    A chamada 1 foi descartada e o lead recebeu a prosa do subagente. Marcar
    aquela pergunta queimaria PARA SEMPRE a chance de perguntar o campo -- a
    uniao no SQL nunca remove --, e contar gastaria orcamento do teto da
    RN-05.5 por uma pergunta que nao saiu. E o mesmo dano que o caminho da
    desambiguacao ja evita, pela mesma causa.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.COMPRA.value)
    classificador = classificador_fake(Intencao.INVESTIMENTO, perguntou=("regiao",))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    linha = await _linha(session)
    assert "regiao" not in (linha.perguntados_sem_resposta or ())
    assert linha.perguntas_feitas == 0


async def test_o_perfil_sai_do_estado_mesclado_e_nao_so_deste_turno(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O horizonte veio num turno anterior e so o tipo de retorno chega agora.

    Classificar so com os campos deste turno daria `None` -- `perfil_de` exige
    os dois -- e o lead que ja respondeu os dois ficaria sem perfil para
    sempre. E o mesmo cuidado que impede `None` de apagar campo antigo: nada
    que o lead ja disse pode sumir por causa do turno seguinte.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(
        session, intencao=Intencao.INVESTIMENTO.value, horizonte=Horizonte.LONGO.value
    )
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        investidor=ExtracaoDoInvestidor(retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL),
    )

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = await _linha(session)
    # O horizonte antigo SOBREVIVEU: este turno nao o trouxe, e `None` nao apaga.
    assert linha.horizonte == "LONGO"
    assert linha.perfil_investidor == "RENDA"
