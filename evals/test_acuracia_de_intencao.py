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
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    FalhaDeInfraestrutura,
    ResultadoDaMetrica,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    erros,
    matriz_de_confusao,
    resumo_de_confianca,
    sem_mecanismo,
)
from mobia.evals.relatorio import render


class InfraestruturaFalhou(RuntimeError):
    """Um 429, um timeout ou um RespostaInvalida.

    Nao e o modelo errando a intencao. Contar como turno errado faria rede
    instavel ler como regressao de prompt e barrar um merge inocente.

    Carrega a `FalhaDeInfraestrutura` em vez de so a mensagem: quem captura
    precisa dela estruturada para o relatorio, e reconstruir de `str(exc)` no
    outro lado seria parsear a propria mensagem de erro.
    """

    def __init__(self, falha: FalhaDeInfraestrutura) -> None:
        super().__init__(f"{falha.conversa_id} turno {falha.indice}: {falha.erro}")
        self.falha = falha


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

    Levanta na primeira falha de infraestrutura e nao devolve os turnos que
    ja tinham dado certo nesta conversa. E de proposito: o historico e
    sequencial, entao o que sobra de uma conversa interrompida e sempre o
    prefixo dela -- e os turnos faceis moram no prefixo. O corpus poe a
    mudanca de intencao no meio ou no fim justamente porque e o turno
    dificil, e aproveitar prefixos enviesaria a acuracia para cima em toda
    execucao com rede instavel. Uma conversa vale inteira ou nao vale.
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
                FalhaDeInfraestrutura(
                    conversa_id=conversa.id, indice=indice, erro=type(exc).__name__
                )
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


def _metricas_de(resultados: list[Classificacao]) -> list[ResultadoDaMetrica]:
    """As tres declaradas sem mecanismo saem sempre; as duas medidas, so com amostra.

    `acuracia_de_intencao([])` levanta de proposito -- `faixa_de` recusa total
    zero para que um corpus que falhou ao carregar nao abra o gate com 0/0. Mas
    levantar **aqui** apagaria o relatorio, que e o unico artefato de uma
    execucao paga que morreu na rede. Com zero turnos nenhuma metrica e medida,
    ninguem fica verde, e quem reprova a execucao e o teto de conversas
    abandonadas.
    """
    medidas = (
        [
            acuracia_de_intencao(resultados),
            # Bloqueia junto com a crua. E a que corresponde ao comportamento
            # observavel: `executar_turno` roteia pela intencao efetiva, entao
            # um prompt com acuracia crua intacta e confianca destruida reprova
            # aqui e so aqui.
            acuracia_efetiva(resultados),
        ]
        if resultados
        else []
    )
    return [
        *medidas,
        sem_mecanismo("precisao de extracao", "sem mecanismo: TEC-145 nao existe"),
        sem_mecanismo("taxa de alucinacao", "sem mecanismo: bloqueada pela TEC-161"),
        sem_mecanismo("aderencia ao tom", "sem mecanismo: TEC-140 nao existe"),
    ]


async def test_acuracia_de_intencao_no_corpus(
    conversas: list[ConversaAnotada], capsys: pytest.CaptureFixture[str]
) -> None:
    """Uma falha de rede nao pode custar a execucao paga inteira.

    Sao ~136 chamadas sequenciais com `MAX_TENTATIVAS = 1`. Antes, um 429 no
    turno 90 subia pelo `for` e levava o dinheiro e os 89 resultados sem
    imprimir nada. Agora cada conversa e um envelope: a que falha e abandonada,
    registrada, e a proxima comeca. O relatorio sai sempre -- inclusive numa
    execucao que perdeu tudo --, porque ele e o unico artefato que sobra de
    dinheiro ja gasto.

    As tres asercoes estao nesta ordem porque a primeira que estourar e a
    mensagem que o CI mostra, e elas nao dizem a mesma coisa: teto e "a rede
    caiu, re-rode", piso e "sobrou amostra de menos", `bloqueia` e "o prompt
    regrediu". Vermelho por rede vem antes de vermelho por regressao.
    """
    classificador = ClassificadorAnthropic()

    resultados: list[Classificacao] = []
    abandonadas: list[FalhaDeInfraestrutura] = []
    for conversa in conversas:
        try:
            resultados.extend(await _rodar_conversa(classificador, conversa))
        except InfraestruturaFalhou as exc:
            abandonadas.append(exc.falha)

    metricas = _metricas_de(resultados)
    relatorio = render(
        metricas,
        matriz_de_confusao(resultados),
        confianca=resumo_de_confianca(resultados) if resultados else None,
        erradas=erros(resultados),
        infraestrutura=abandonadas,
    )
    with capsys.disabled():
        print("\n" + relatorio)

    assert len(abandonadas) <= TETO_DE_CONVERSAS_ABANDONADAS, (
        f"{len(abandonadas)} conversas perdidas para infraestrutura, teto "
        f"{TETO_DE_CONVERSAS_ABANDONADAS}. Execucao invalida, nao regressao de "
        f"prompt: re-rode.\n{relatorio}"
    )
    # O piso deixou de ser estruturalmente vazio: antes nada era descartado, o
    # total era sempre o do corpus, e a lista nunca encolhia. Agora ela
    # encolhe de verdade com o abandono -- mas com o corpus de hoje esta
    # asercao nao e a que dispara primeiro: o teto acima estoura antes dela,
    # porque 5 x 3 = 15 turnos perdidos no pior caso cabem dentro da folga de
    # 16 turnos sobre o piso de 120 (a conta esta travada por teste em
    # `metricas.py`). Ela so fica alcancavel se essa folga diminuir. O piso do
    # corpus em si sai de graca em `tests/unit/test_evals_corpus_real.py` e no
    # pre-voo da fixture `conversas`. O que ela guarda aqui e o que **sobrou**
    # da execucao.
    assert len(resultados) >= PISO_DE_TURNOS, (
        f"{len(resultados)} turnos medidos, piso {PISO_DE_TURNOS}. Amostra "
        f"insuficiente depois do abandono: a faixa amarela nao absorve o ruido "
        f"neste tamanho.\n{relatorio}"
    )
    assert not bloqueia(metricas), relatorio
