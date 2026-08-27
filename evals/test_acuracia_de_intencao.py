"""A medicao. Chama o modelo de verdade -- custa dinheiro e nao e deterministica.

Rodar contra resposta gravada seria barato e mediria nada: o que este gate
existe para pegar e a mudanca de prompt alterando o que o modelo devolve, e um
replay passaria verde com o prompt destruido.
"""

import pytest

from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico
from mobia.evals.corpus import ConversaAnotada
from mobia.evals.metricas import (
    PISO_DE_TURNOS,
    Classificacao,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    matriz_de_confusao,
    resumo_de_confianca,
    sem_mecanismo,
)
from mobia.evals.relatorio import render


class InfraestruturaFalhou(RuntimeError):
    """Um 429, um timeout ou um RespostaInvalida.

    Nao e o modelo errando a intencao. Contar como turno errado faria rede
    instavel ler como regressao de prompt e barrar um merge inocente.
    """


async def _rodar_conversa(
    classificador: ClassificadorAnthropic, conversa: ConversaAnotada
) -> list[Classificacao]:
    """Os turnos sao sequenciais, e a resposta real do agente volta ao historico.

    Mostrar so as falas do lead mediria um contexto que nunca existe: o
    classificador ve a conversa inteira, com as duas partes.

    Nao e identico a producao no turno ambiguo. Com confianca abaixo de
    `LIMIAR_DE_DESAMBIGUACAO` e o episodio ainda limpo, `executar_turno`
    descarta a resposta desta chamada e entrega o texto de
    `classificador.desambiguar` -- e essa pergunta, nao esta resposta, que
    entra no historico do turno seguinte. Replicar isso aqui dobraria as
    chamadas pagas nos turnos afetados; e decisao de escopo, nao detalhe de
    implementacao, e esta fora da TEC-210. O efeito da divergencia esta
    limitado ao contexto dos turnos que vem depois de um turno ambiguo -- a
    classificacao medida em cada turno e sempre a da primeira chamada, que e
    a mesma que producao grava em `conversation_intent`.
    """
    historico: list[tuple[MessageRole, str]] = []
    resultados: list[Classificacao] = []

    for indice, turno in enumerate(conversa.turnos):
        historico.append((MessageRole.LEAD, turno.lead))
        contexto = contexto_do_historico(historico, sistema=SISTEMA_DO_AGENTE)
        try:
            resposta = await classificador.classificar(contexto)
        except Exception as exc:
            # `RespostaInvalida` e o caso previsto, mas um 429 ou um timeout do
            # httpx sobem como outra coisa e tem o mesmo significado aqui:
            # nao foi o modelo errando a intencao.
            raise InfraestruturaFalhou(
                f"{conversa.id} turno {indice}: {type(exc).__name__}"
            ) from exc

        resultados.append(
            Classificacao(
                conversa_id=conversa.id,
                indice=indice,
                esperada=turno.intencao,
                obtida=resposta.intencao,
                # A confianca vem junto porque metade da medicao depende dela:
                # producao roteia pela intencao efetiva, nao por `obtida`, e
                # descartar este campo aqui e o que cegava o gate para
                # regressao de calibragem.
                confianca=resposta.confianca,
            )
        )
        historico.append((MessageRole.AGENTE, resposta.resposta))

    return resultados


async def test_acuracia_de_intencao_no_corpus(
    conversas: list[ConversaAnotada], capsys: pytest.CaptureFixture[str]
) -> None:
    classificador = ClassificadorAnthropic()

    resultados: list[Classificacao] = []
    for conversa in conversas:
        resultados.extend(await _rodar_conversa(classificador, conversa))

    assert len(resultados) >= PISO_DE_TURNOS

    metricas = [
        acuracia_de_intencao(resultados),
        # Bloqueia junto com a crua. E a que corresponde ao comportamento
        # observavel: `executar_turno` roteia pela intencao efetiva, entao um
        # prompt com acuracia crua intacta e confianca destruida reprova aqui
        # e so aqui.
        acuracia_efetiva(resultados),
        sem_mecanismo("precisao de extracao", "sem mecanismo: TEC-145 nao existe"),
        sem_mecanismo("taxa de alucinacao", "sem mecanismo: bloqueada pela TEC-161"),
        sem_mecanismo("aderencia ao tom", "sem mecanismo: TEC-140 nao existe"),
    ]

    relatorio = render(
        metricas,
        matriz_de_confusao(resultados),
        confianca=resumo_de_confianca(resultados),
    )
    with capsys.disabled():
        print("\n" + relatorio)

    assert not bloqueia(metricas), relatorio
