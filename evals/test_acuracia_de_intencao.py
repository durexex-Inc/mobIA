"""A medicao. Chama o modelo de verdade -- custa dinheiro e nao e deterministica.

Rodar contra resposta gravada seria barato e mediria nada: o que este gate
existe para pegar e a mudanca de prompt alterando o que o modelo devolve, e um
replay passaria verde com o prompt destruido.
"""

import re
from collections.abc import Iterable
from typing import Any

import pytest

from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import campos_a_gravar
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico
from mobia.evals.corpus import ConversaAnotada
from mobia.evals.metricas import (
    PISO_DE_TURNOS,
    PISO_DE_TURNOS_ANOTADOS,
    PISO_DE_TURNOS_NEGATIVOS,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    ExtracaoObservada,
    FalhaDeInfraestrutura,
    ResultadoDaMetrica,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    discrepancias_da_extracao,
    erros,
    matriz_de_confusao,
    precisao_da_extracao,
    resumo_de_confianca,
    sem_mecanismo,
)
from mobia.evals.relatorio import render

# Marcadores por campo para o proxy de repergunta. Sao regex (nao substring
# crua) casadas com fronteira de palavra nas duas pontas, e cada uma e pista,
# nao gramatica: a heuristica tem falso negativo por construcao -- um "e onde
# voce quer?" com outra palavra escapa. "valor" e "casa" sairam da lista de
# proposito: apareciam na resposta do agente DESCREVENDO um imovel ("o valor
# do condominio e R$ 650", "esse apartamento e uma casa") tao ou mais vezes
# que numa repergunta de verdade, e nao ha fronteira de palavra que resolva
# isso -- sao ambiguos mesmo como palavra inteira. O numero final NAO e cota
# inferior nem superior de reperguntas: e indicador aproximado, com erro nas
# duas direcoes. Esta limitacao esta declarada no README de proposito, e os
# seis casos que motivaram este aperto -- quatro negativos, dois positivos --
# estao travados em `tests/unit/test_evals_reperguntas.py`.
MARCADORES_DE_REPERGUNTA: dict[str, tuple[str, ...]] = {
    "regiao": (r"regiao", r"bairro", r"onde", r"localiza"),
    "quartos": (r"quartos?", r"dormitorios?"),
    "vagas": (r"vagas?", r"garagem"),
    "tipo_imovel": (r"apartamentos?", r"tipo de imovel"),
    "faixa_preco_max": (r"orcamento", r"faixa de preco", r"quanto pretende"),
    "urgencia": (r"prazo", r"quando pretende", r"pressa"),
    "forma_pagamento": (r"pagamento", r"financiamento", r"a vista"),
    "tem_imovel_para_vender": (r"imovel para vender", r"tem imovel"),
}


def _reperguntou(texto: str, campos_conhecidos: Iterable[str]) -> list[str]:
    """Proxy de palavra-chave: pista, nao prova, nas duas direcoes.

    Duas guardas alem da fronteira de palavra: exige `?` na resposta --
    sem isso "esse apartamento tem 2 quartos e 1 vaga" (o agente descrevendo
    um imovel, sem perguntar nada) contava como tres reperguntas -- e usa
    `\\bmarcador\\b`, nao substring crua, porque "onde" e substring de
    "responder" ("resp-onde-r") e contaria repergunta de regiao numa recusa
    que nem menciona regiao. Mesmo com as duas guardas o proxy ainda erra
    para os dois lados: uma pergunta com outra palavra escapa (falso
    negativo), e o agente pode descrever um imovel numa frase que termina
    perguntando outra coisa (falso positivo). Ver os testes deste modulo.
    """
    if "?" not in texto:
        return []
    baixo = texto.casefold()
    return [
        campo
        for campo in campos_conhecidos
        if any(
            re.search(rf"\b{marcador}\b", baixo)
            for marcador in MARCADORES_DE_REPERGUNTA.get(campo, ())
        )
    ]


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
) -> tuple[list[Classificacao], list[ExtracaoObservada], list[tuple[str, int, str]]]:
    """Os turnos sao sequenciais, e a resposta real do agente volta ao historico.

    Devolve tres listas -- classificacoes, observacoes de extracao e
    reperguntas detectadas pelo proxy -- porque a TEC-145 acrescentou duas
    medidas novas a mesma passada sequencial, e refazer o laco so pra separar
    as tres pagaria a chamada de novo.

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
    estado_acumulado: dict[str, Any] = {}
    observadas: list[ExtracaoObservada] = []
    reperguntados: list[tuple[str, int, str]] = []

    for indice, turno in enumerate(conversa.turnos):
        historico.append((MessageRole.LEAD, turno.lead))
        # Capturado antes da chamada: a pergunta do proxy e sobre o que ja era
        # conhecido *antes* deste turno, nao sobre o que este turno acabou de
        # extrair.
        conhecidos_antes = set(estado_acumulado)
        contexto = contexto_do_historico(
            historico,
            sistema=SISTEMA_DO_AGENTE,
            estado=LeadQualification(**estado_acumulado) if estado_acumulado else None,
        )
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

        obtido = resposta.extracao.preenchidos()
        if turno.campos is not None:
            observadas.append(
                ExtracaoObservada(
                    conversa_id=conversa.id,
                    indice=indice,
                    esperado=turno.campos,
                    obtido=obtido,
                )
            )
        reperguntados.extend(
            (conversa.id, indice, campo)
            for campo in _reperguntou(resposta.resposta, conhecidos_antes)
        )
        # Acumula com a MESMA regra de producao -- `campos_a_gravar`, a
        # funcao que `gravar_estado` tambem usa: guarda de `FORA_DE_ESCOPO`
        # (nao acumula nada neste turno), mais novo vence (o `update` por
        # cima do que ja havia), `None` nao apaga, e `intencao` sempre entra
        # quando ha gravacao. Antes desta funcao existir o runner divergia de
        # producao nas duas ultimas: acumulava atraves de `FORA_DE_ESCOPO` e
        # nunca guardava `intencao`, entao o prompt sintetico do eval nunca
        # carregava a linha `intencao: X` que `montagem._texto_do_estado`
        # poe no prompt real a partir do segundo turno.
        estado_acumulado.update(campos_a_gravar(resposta.intencao, resposta.extracao))

        historico.append((MessageRole.AGENTE, resposta.resposta))

    return resultados, observadas, reperguntados


def _metricas_de(
    resultados: list[Classificacao], observadas: list[ExtracaoObservada]
) -> list[ResultadoDaMetrica]:
    """As duas declaradas sem mecanismo saem sempre; as demais, so com amostra.

    `acuracia_de_intencao([])` levanta de proposito -- `faixa_de` recusa total
    zero para que um corpus que falhou ao carregar nao abra o gate com 0/0. Mas
    levantar **aqui** apagaria o relatorio, que e o unico artefato de uma
    execucao paga que morreu na rede. Com zero turnos nenhuma metrica e medida,
    ninguem fica verde, e quem reprova a execucao e o teto de conversas
    abandonadas.

    `precisao_da_extracao` tem guarda irma, mas contra `PISO_DE_TURNOS_ANOTADOS`
    e nao contra 1: `observadas` so tem os turnos cujo `campos` sobreviveu ao
    abandono por infraestrutura, e o pior caso medido -- abandonar as
    `TETO_DE_CONVERSAS_ABANDONADAS` conversas com mais anotacao -- deixa uma
    amostra pequena de mais para o piso de 85% significar algo, sem chegar a
    zero. Uma guarda que so testasse "zero turnos anotados" deixaria passar
    exatamente esse caso: `precisao_da_extracao` mediria e bloquearia (ou
    liberaria) um gate pago com uma amostra abaixo do piso que o corpus
    declara, e o resultado seria ruido lido como sinal.

    A guarda conta positivos e negativos em separado, e nao `len(observadas)`
    direto: `observadas` inclui os dois desde a TEC-238, e um total unico se
    auto-satisfaria com 30 negativos e nenhum positivo (ou o inverso) -- o
    mesmo furo que o piso de negativos existe para fechar, entrando por outra
    porta. `precisao_da_extracao(observadas)` continua recebendo **todas** as
    observadas, positivas e negativas: e so a guarda que precisa saber a
    composicao, porque um dos dois grupos sozinho nao sustenta o piso de 85%.
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
    positivas = sum(1 for o in observadas if o.esperado != {})
    negativas = len(observadas) - positivas
    extracao = (
        [precisao_da_extracao(observadas)]
        if positivas >= PISO_DE_TURNOS_ANOTADOS and negativas >= PISO_DE_TURNOS_NEGATIVOS
        else [
            sem_mecanismo(
                "precisao da extracao",
                f"{positivas} turnos anotados (piso {PISO_DE_TURNOS_ANOTADOS}) e "
                f"{negativas} negativos (piso {PISO_DE_TURNOS_NEGATIVOS}) sobraram "
                f"na execucao: amostra pequena de mais para o piso de 85% "
                f"significar algo",
            )
        ]
    )
    return [
        *medidas,
        *extracao,
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

    As quatro asercoes estao nesta ordem porque a primeira que estourar e a
    mensagem que o CI mostra, e elas nao dizem a mesma coisa: teto e "a rede
    caiu, re-rode", os dois pisos (turnos e turnos anotados) sao "sobrou
    amostra de menos", `bloqueia` e "o prompt regrediu". Vermelho por rede
    vem antes de vermelho por regressao.
    """
    classificador = ClassificadorAnthropic()

    resultados: list[Classificacao] = []
    observadas: list[ExtracaoObservada] = []
    reperguntados: list[tuple[str, int, str]] = []
    abandonadas: list[FalhaDeInfraestrutura] = []
    for conversa in conversas:
        try:
            (
                resultados_conversa,
                observadas_conversa,
                reperguntados_conversa,
            ) = await _rodar_conversa(classificador, conversa)
            resultados.extend(resultados_conversa)
            observadas.extend(observadas_conversa)
            reperguntados.extend(reperguntados_conversa)
        except InfraestruturaFalhou as exc:
            abandonadas.append(exc.falha)

    metricas = _metricas_de(resultados, observadas)
    relatorio = render(
        metricas,
        matriz_de_confusao(resultados),
        confianca=resumo_de_confianca(resultados) if resultados else None,
        erradas=erros(resultados),
        infraestrutura=abandonadas,
        # Diagnostico, nao gate -- mesmo motivo de `ResumoDeConfianca`: o proxy
        # de repergunta (ver MARCADORES_DE_REPERGUNTA acima) tem falso
        # negativo E falso positivo por construcao, entao o numero e um
        # indicador aproximado, nunca cota inferior nem prova de que a
        # repergunta aconteceu ou nao. Nao entra em `_metricas_de` nem em
        # `bloqueia`.
        reperguntas=reperguntados,
        # Releitura das mesmas `observadas`, sem nenhuma chamada nova ao
        # modelo: o numero da precisao nao diz se o corpus mede errado ou se
        # o modelo extrai mal, e essa distincao decide entre TEC-239
        # (anotar) e TEC-240 (prompt). Diagnostico -- nao entra em
        # `_metricas_de` nem em `bloqueia`.
        discrepancias=discrepancias_da_extracao(observadas),
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
    # `PISO_DE_TURNOS_ANOTADOS` e irmao de `PISO_DE_TURNOS`, mas o abandono
    # nao encolhe os dois na mesma proporcao: as conversas mais longas nao
    # sao as mais anotadas, entao perder o teto de conversas inteiro (5) pode
    # deixar o total de turnos acima do piso e o subconjunto anotado bem
    # abaixo do dele -- o caso medido e abandonar as cinco conversas com mais
    # anotacao, que sozinho derruba os turnos anotados a 1/3 do piso sem
    # tocar o piso de turnos. Sem este assert, `_metricas_de` ainda protege o
    # gate (vira `sem_mecanismo` abaixo do piso, nunca calcula
    # `precisao_da_extracao` com amostra pequena de mais), mas o relatorio sai
    # mudo sobre o motivo -- e essa e a mesma razao de existir do assert do
    # piso de turnos, uma linha acima.
    assert len(observadas) >= PISO_DE_TURNOS_ANOTADOS, (
        f"{len(observadas)} turnos anotados sobraram na execucao, piso "
        f"{PISO_DE_TURNOS_ANOTADOS}. Amostra insuficiente para a precisao da "
        f"extracao significar algo depois do abandono: re-rode.\n{relatorio}"
    )
    assert not bloqueia(metricas), relatorio
