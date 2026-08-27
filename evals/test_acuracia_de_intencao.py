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
    bloqueia,
    matriz_de_confusao,
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

    E o que producao faz. Mostrar so as falas do lead mediria um contexto que
    nunca existe.
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
        sem_mecanismo("precisao de extracao", "sem mecanismo: TEC-145 nao existe"),
        sem_mecanismo("taxa de alucinacao", "sem mecanismo: bloqueada pela TEC-161"),
        sem_mecanismo("aderencia ao tom", "sem mecanismo: TEC-140 nao existe"),
    ]

    relatorio = render(metricas, matriz_de_confusao(resultados))
    with capsys.disabled():
        print("\n" + relatorio)

    assert not bloqueia(metricas), relatorio
