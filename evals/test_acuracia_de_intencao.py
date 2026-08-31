"""A medicao. Chama o modelo de verdade -- custa dinheiro e nao e deterministica.

Rodar contra resposta gravada seria barato e mediria nada: o que este gate
existe para pegar e a mudanca de prompt alterando o que o modelo devolve, e um
replay passaria verde com o prompt destruido.
"""

import os
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import campos_a_gravar, campos_a_marcar
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico
from mobia.evals.corpus import ConversaAnotada
from mobia.evals.metricas import (
    CAMPOS_DA_EXTRACAO,
    PISO_DE_TURNOS,
    PISO_DE_TURNOS_ANOTADOS,
    PISO_DE_TURNOS_NEGATIVOS,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    EstadoDaConversa,
    ExtracaoObservada,
    FalhaDeInfraestrutura,
    PerguntaObservada,
    RespostaObservada,
    ResultadoDaMetrica,
    acuracia_de_intencao,
    acuracia_efetiva,
    aderencia_ao_tom,
    bloqueia,
    campos_perguntados,
    decomposicao_da_extracao,
    discrepancias_da_extracao,
    eh_negativo,
    erros,
    insistencias,
    matriz_de_confusao,
    precisao_da_extracao,
    precisao_efetiva_da_extracao,
    resumo_de_confianca,
    resumo_de_negativos,
    resumo_do_formato,
    sem_mecanismo,
)
from mobia.evals.relatorio import DIRETORIO_DE_RELATORIOS, preservar, render
from mobia.infra.anthropic import motivo_do_provedor


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
def _reperguntou(texto: str, campos_conhecidos: Iterable[str]) -> list[str]:
    """Os campos que o estado JA SABE e sobre os quais a resposta pergunta.

    A deteccao mora em `campos_perguntados` (`mobia.evals.metricas`) desde a
    TEC-256, junto da tabela de marcadores: dois proxies dependem dela -- este
    e `insistencias`, que pergunta o oposto (campo NAO sabido, perguntado de
    novo) -- e duas copias divergiriam, que e o defeito que `campos_a_gravar` e
    `_subcontagem` ja custaram a este projeto. Os erros do proxy sao os de la e
    continuam declarados: pista, nao prova, nas duas direcoes.

    Ordena para o relatorio nao mudar de ordem entre execucoes por causa da
    iteracao de um `set`.
    """
    return sorted(campos_perguntados(texto) & set(campos_conhecidos))


# A chave que `campos_a_marcar` acumula no estado sintetico. Nao e campo de
# extracao, e por isso nao pode entrar em `conhecidos_antes`.
CHAVE_DA_MARCA = "perguntados_sem_resposta"


def _campos_conhecidos(estado: dict[str, Any]) -> set[str]:
    """Os campos que o estado sintetico ja sabe, sem a chave da marca.

    A armadilha que isto fecha: `set(estado_acumulado)` cru poria a string
    "perguntados_sem_resposta" na lista de campos conhecidos, e os dois
    proxies passariam a tratar a marca como um campo que o lead respondeu.
    `intencao` fica -- ela sempre esteve aqui, vem de `campos_a_gravar`, e
    nenhum marcador de repergunta casa com ela.
    """
    return set(estado) - {CHAVE_DA_MARCA}


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
) -> tuple[
    list[Classificacao],
    list[ExtracaoObservada],
    list[tuple[str, int, str]],
    list[RespostaObservada],
    list[PerguntaObservada],
    EstadoDaConversa,
]:
    """Os turnos sao sequenciais, e a resposta real do agente volta ao historico.

    Devolve tres listas -- classificacoes, observacoes de extracao e
    reperguntas detectadas pelo proxy -- porque a TEC-145 acrescentou duas
    medidas novas a mesma passada sequencial, e refazer o laco so pra separar
    as tres pagaria a chamada de novo. A TEC-252 acrescentou a quarta, o
    estado final da conversa, pela mesma razao.

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
    # A anotacao acumulada com a mesma regra do estado: "mais novo vence".
    # E o que o corpus diz que a conversa deveria ter deixado gravado.
    esperado_acumulado: dict[str, Any] = {}
    # O texto que o agente devolveu, que ate a TEC-140 era usado so pelo proxy
    # de reperguntas e pelo historico, e depois jogado fora. Medir o formato
    # dele nao custa chamada nenhuma: ele ja foi gerado e pago.
    respostas: list[RespostaObservada] = []
    # Os campos ainda desconhecidos sobre os quais o agente perguntou, por
    # turno. E a materia-prima de `insistencias` (TEC-256): o proxy irmao mede
    # o que o estado ja sabe, este o que o lead nao respondeu.
    perguntas: list[PerguntaObservada] = []
    observadas: list[ExtracaoObservada] = []
    reperguntados: list[tuple[str, int, str]] = []

    for indice, turno in enumerate(conversa.turnos):
        historico.append((MessageRole.LEAD, turno.lead))
        # Capturado antes da chamada: a pergunta do proxy e sobre o que ja era
        # conhecido *antes* deste turno, nao sobre o que este turno acabou de
        # extrair.
        conhecidos_antes = _campos_conhecidos(estado_acumulado)
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
                    conversa_id=conversa.id,
                    indice=indice,
                    erro=type(exc).__name__,
                    # Sem isto, 91 linhas de `BadRequestError` e nenhuma pista:
                    # foi o que custou um dia de diagnostico em 28/08, quando a
                    # causa era saldo esgotado e vinha escrita no corpo do 400.
                    motivo=motivo_do_provedor(exc),
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
        if turno.anotado:
            esperado_acumulado.update(turno.campos)
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
        # `- conhecidos_antes`: o que ja estava no estado e repergunta, e cai
        # na lista acima. Aqui so entra o que o lead ainda nao respondeu.
        ainda_sem_resposta = campos_perguntados(resposta.resposta) - conhecidos_antes
        if ainda_sem_resposta:
            perguntas.append(
                PerguntaObservada(
                    conversa_id=conversa.id,
                    indice=indice,
                    campos=frozenset(ainda_sem_resposta),
                )
            )
        # Acumula com a MESMA regra de producao -- `campos_a_gravar`, a
        # funcao que `gravar_estado` tambem usa: guarda de `FORA_DE_ESCOPO`
        # (nao acumula nada neste turno), mais novo vence (o `update` por
        # cima do que ja havia), `None` nao apaga, e `intencao` sempre entra
        # quando ha gravacao.
        #
        # A marca da TEC-257 segue o mesmo caminho e a mesma guarda, por
        # `campos_a_marcar`: sem isto o prompt sintetico do eval nao carrega
        # a linha "(perguntado, sem resposta)" que producao carrega, e o eval
        # nao consegue medir o conserto. E o mesmo defeito que fez
        # `campos_a_gravar` existir, um andar acima.
        campos_do_turno = campos_a_gravar(resposta.intencao, resposta.extracao)
        if campos_do_turno:
            marcados = set(estado_acumulado.get(CHAVE_DA_MARCA) or ())
            marcados |= campos_a_marcar(resposta.perguntou, set(campos_do_turno))
            estado_acumulado.update(campos_do_turno)
            estado_acumulado[CHAVE_DA_MARCA] = sorted(marcados)

        respostas.append(
            RespostaObservada(conversa_id=conversa.id, indice=indice, texto=resposta.resposta)
        )
        historico.append((MessageRole.AGENTE, resposta.resposta))

    # `estado_acumulado` carrega tambem `intencao`, que `campos_a_gravar` poe
    # e que nao e campo de extracao -- nao ha anotacao contra a qual compara-la
    # aqui. O filtro sai de `Extracao`, nao de uma lista escrita a mao.
    return (
        resultados,
        observadas,
        reperguntados,
        respostas,
        perguntas,
        EstadoDaConversa(
            conversa_id=conversa.id,
            esperado=esperado_acumulado,
            obtido={
                campo: valor
                for campo, valor in estado_acumulado.items()
                if campo in CAMPOS_DA_EXTRACAO
            },
        ),
    )


def _positivas_e_negativas(observadas: list[ExtracaoObservada]) -> tuple[int, int]:
    """Quantas `observadas` afirmam algo, e quantas sao negativas.

    "Negativa" e `eh_negativo` (`mobia.evals.metricas`), o mesmo criterio que
    `resumo_de_negativos` usa: as duas contagens tem de vir da mesma formula
    para nao divergir em silencio.

    Extraida porque a mesma conta guarda dois pontos: a guarda de
    `precisao_da_extracao` dentro de `_metricas_de`, e o assert irmao em
    `test_acuracia_de_intencao_no_corpus` que existe para reprovar com
    mensagem clara em vez de deixar a metrica cair muda em `sem_mecanismo`.
    Duplicar a formula nos dois lugares e o jeito de um deles ficar
    desalinhado do outro sem nenhum teste acusar.
    """
    negativas = sum(1 for o in observadas if eh_negativo(o))
    return len(observadas) - negativas, negativas


def _metricas_de(
    resultados: list[Classificacao],
    observadas: list[ExtracaoObservada],
    respostas: list[RespostaObservada],
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
    positivas, negativas = _positivas_e_negativas(observadas)
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
        # Deixou de ser slot vazio na TEC-140. Mede as duas regras do RF-04 que
        # sao decidiveis sobre o texto -- tamanho e numero de perguntas -- com
        # piso-ANDAIME, porque ninguem sabe ainda qual aderencia e saudavel.
        # Sem amostra ela cai de volta no slot, como as outras.
        aderencia_ao_tom(respostas)
        if respostas
        else sem_mecanismo("aderencia ao tom", "nenhuma resposta sobreviveu a execucao"),
    ]


def _condicoes_da_execucao(
    conversas: Sequence[ConversaAnotada],
    resultados: Sequence[Classificacao],
    observadas: Sequence[ExtracaoObservada],
    abandonadas: Sequence[FalhaDeInfraestrutura],
) -> list[str]:
    """O que faz esta execucao valer como medida, ao lado do numero que ela mede.

    Existe porque uma execucao que rocou um piso vale menos que uma folgada, e
    o relatorio sozinho nao diz qual das duas foi: `_secao_de_infraestrutura`
    so aparece quando houve falha -- zero abandono nao imprime nada --, e os
    tres pisos nao aparecem em lugar nenhum quando a execucao passa por eles.
    Sem estas linhas, um baseline lido daqui a tres cards nao teria como saber
    se a amostra que o produziu era confortavel ou estava na borda.

    Fica no runner, e nao em `render`: sao condicoes da **execucao** (que
    modelo, que dia, quanto sobrou depois do abandono), e nao do conteudo
    medido. `render` e puro e nao sabe nenhuma delas.

    A data e UTC e explicita no texto. Baseline sem data e baseline sem prazo
    de validade, e foi assim que o numero de 28/08/2026 se perdeu.
    """
    positivas, negativas = _positivas_e_negativas(observadas)

    def folga(medido: int, piso: int) -> str:
        return f"{medido}/{piso}, folga de {medido - piso}"

    return [
        "# Condicoes de validade da execucao",
        "",
        f"- data: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- modelo: {get_settings().modelo_agente}",
        f"- corpus no disco: {len(conversas)} conversas, "
        f"{sum(len(conversa.turnos) for conversa in conversas)} turnos",
        f"- conversas abandonadas por infraestrutura: {len(abandonadas)}, "
        f"teto {TETO_DE_CONVERSAS_ABANDONADAS}",
        f"- turnos medidos: {folga(len(resultados), PISO_DE_TURNOS)}",
        f"- turnos anotados positivos: {folga(positivas, PISO_DE_TURNOS_ANOTADOS)}",
        f"- turnos anotados negativos: {folga(negativas, PISO_DE_TURNOS_NEGATIVOS)}",
        "",
        "Folga negativa em qualquer linha acima invalida a execucao: o numero",
        "medido nao tem amostra que o sustente, e re-rodar e mais barato que",
        "acreditar nele.",
        "",
    ]


def _destino_do_relatorio() -> Path:
    """Onde o artefato desta execucao e gravado.

    `RELATORIO_DE_EVAL` existe para o disparo manual poder nomear o arquivo
    (o commit do corpus nao cabe numa data), e o default dateado existe para
    que esquecer de definir a variavel nao volte a produzir uma execucao paga
    sem artefato -- que e exatamente o que a TEC-247 esta consertando.
    """
    escolhido = os.environ.get("RELATORIO_DE_EVAL")
    if escolhido:
        return Path(escolhido)
    # Ancorado no arquivo, e nao no cwd: `DIRETORIO_DE_RELATORIOS` e relativo
    # ao repositorio, e um `pytest evals` disparado de outro diretorio
    # gravaria o artefato de uma execucao paga fora da arvore -- onde ninguem
    # o commitaria. Mesmo motivo do `Path(__file__)` em `evals/conftest.py`.
    raiz = Path(__file__).resolve().parent.parent
    return raiz / DIRETORIO_DE_RELATORIOS / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.md"


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
    caiu, re-rode", os pisos (turnos, e turnos anotados separados em positivos
    e negativos) sao "sobrou amostra de menos", `bloqueia` e "o prompt
    regrediu". Vermelho por rede vem antes de vermelho por regressao.
    """
    classificador = ClassificadorAnthropic()

    resultados: list[Classificacao] = []
    observadas: list[ExtracaoObservada] = []
    reperguntados: list[tuple[str, int, str]] = []
    abandonadas: list[FalhaDeInfraestrutura] = []
    estados: list[EstadoDaConversa] = []
    respostas: list[RespostaObservada] = []
    perguntas: list[PerguntaObservada] = []
    for conversa in conversas:
        try:
            (
                resultados_conversa,
                observadas_conversa,
                reperguntados_conversa,
                respostas_conversa,
                perguntas_conversa,
                estado_da_conversa,
            ) = await _rodar_conversa(classificador, conversa)
            resultados.extend(resultados_conversa)
            observadas.extend(observadas_conversa)
            reperguntados.extend(reperguntados_conversa)
            respostas.extend(respostas_conversa)
            perguntas.extend(perguntas_conversa)
            estados.append(estado_da_conversa)
        except InfraestruturaFalhou as exc:
            abandonadas.append(exc.falha)

    metricas = _metricas_de(resultados, observadas, respostas)
    relatorio = render(
        metricas,
        matriz_de_confusao(resultados),
        confianca=resumo_de_confianca(resultados) if resultados else None,
        erradas=erros(resultados),
        infraestrutura=abandonadas,
        # Diagnostico, nao gate -- mesmo motivo de `ResumoDeConfianca`: o proxy
        # de repergunta (ver `campos_perguntados`, em metricas.py) tem falso
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
        # Turno negativo e o unico lugar onde `extra` deixa de ser ambiguo: o
        # turno esta anotado por completo, e o completo e vazio. Sem esta
        # contagem, o relatorio nao diria se a invencao veio de dois turnos
        # medidos ou de todos os negativos do corpus.
        negativos=resumo_de_negativos(observadas),
        # A mesma conta da metrica que trava, aberta em parcelas que se movem
        # diferente -- e o aviso de quanto uma execucao resolve. A TEC-253
        # mediu 5,7 pontos de diferenca entre duas execucoes do mesmo codigo,
        # e sem este bloco quem compara com a execucao anterior nao tem como
        # saber que o numero de manchete nao suporta a comparacao.
        decomposicao=decomposicao_da_extracao(observadas),
        # A extracao como producao a experimenta: estado final da conversa,
        # nao turno a turno. `None` nao apaga, entao um campo que o modelo
        # deixou de reemitir num turno posterior continua gravado -- a TEC-252
        # mediu que seis das oito faltas turno a turno eram exatamente isso.
        efetiva=precisao_efetiva_da_extracao(estados) if estados else None,
        # O formato aberto por regra: tamanho e perguntas decidem consertos
        # diferentes, e a contagem de emoji e diagnostico puro -- a regra de
        # "informacao essencial nao depende de emoji" nao e mecanizavel.
        formato=resumo_do_formato(respostas) if respostas else None,
        # Campo perguntado em mais de um turno da mesma conversa, sem o lead
        # ter respondido. Diagnostico -- ninguem decidiu ainda se reinsistir e
        # defeito, e reinsistir nao e errado em si (TEC-256).
        insistencia=insistencias(perguntas) if perguntas else None,
    )
    condicoes = "\n".join(_condicoes_da_execucao(conversas, resultados, observadas, abandonadas))
    artefato = condicoes + "\n" + relatorio

    # Grava ANTES das asercoes, e nao depois: o `assert` que reprova a
    # execucao aborta o teste, e um artefato escrito depois dele nao
    # existiria justamente na execucao vermelha -- a que mais precisa ser
    # lida turno a turno. Pelo mesmo motivo o disco nao pode derrubar a
    # medicao: se a gravacao falhar, o relatorio ainda sai no terminal e a
    # execucao segue reprovando (ou passando) pelo que mediu, com o motivo
    # da falha impresso ao lado.
    destino = _destino_do_relatorio()
    try:
        preservar(artefato, destino)
    except OSError as exc:
        aviso = f"[!] o relatorio NAO foi gravado em {destino}: {type(exc).__name__}: {exc}"
    else:
        aviso = f"[OK] relatorio preservado em {destino}"

    with capsys.disabled():
        print("\n" + artefato)
        print(aviso)

    assert len(abandonadas) <= TETO_DE_CONVERSAS_ABANDONADAS, (
        f"{len(abandonadas)} conversas perdidas para infraestrutura, teto "
        f"{TETO_DE_CONVERSAS_ABANDONADAS}. Execucao invalida, nao regressao de "
        f"prompt: re-rode.\n{relatorio}"
    )
    # O piso deixou de ser estruturalmente vazio: antes nada era descartado, o
    # total era sempre o do corpus, e a lista nunca encolhia. Agora ela
    # encolhe de verdade com o abandono -- mas com o corpus de hoje esta
    # asercao nao e a que dispara primeiro: o teto acima estoura antes dela,
    # porque o pior caso (a soma das cinco conversas mais longas, hoje
    # 4+4+3+3+3 = 17 turnos perdidos) cabe dentro da folga de 138 - 120 = 18
    # turnos sobre o piso de 120 (a conta esta travada por teste em
    # `metricas.py`, `TETO_DE_CONVERSAS_ABANDONADAS`). Ela so fica alcancavel
    # se essa folga diminuir. O piso do corpus em si sai de graca em
    # `tests/unit/test_evals_corpus_real.py` e no pre-voo da fixture
    # `conversas`. O que ela guarda aqui e o que **sobrou** da execucao.
    assert len(resultados) >= PISO_DE_TURNOS, (
        f"{len(resultados)} turnos medidos, piso {PISO_DE_TURNOS}. Amostra "
        f"insuficiente depois do abandono: a faixa amarela nao absorve o ruido "
        f"neste tamanho.\n{relatorio}"
    )
    # `PISO_DE_TURNOS_ANOTADOS` e `PISO_DE_TURNOS_NEGATIVOS` sao irmaos de
    # `PISO_DE_TURNOS`, mas o abandono nao encolhe os tres na mesma proporcao:
    # as conversas mais longas nao sao as mais anotadas, nem as mais anotadas
    # sao as mais negativas, entao perder o teto de conversas inteiro (5) pode
    # deixar o total de turnos acima do piso e um dos dois subconjuntos --
    # positivos ou negativos -- bem abaixo do dele.
    #
    # `len(observadas) >= PISO_DE_TURNOS_ANOTADOS` sozinho se auto-satisfaz
    # desde que `observadas` passou a incluir os dois: perder os 55 positivos
    # inteiros ainda deixa 66 negativos, 121 >= 38, e o assert nunca dispara --
    # exatamente o furo que a guarda de `_metricas_de` fecha contando os dois
    # em separado. Este assert usa a mesma conta de `_positivas_e_negativas`
    # para nao reabrir o furo aqui, no ponto irmao.
    #
    # Sem este assert, `_metricas_de` ainda protege o gate (vira
    # `sem_mecanismo` abaixo de qualquer um dos dois pisos, nunca calcula
    # `precisao_da_extracao` com amostra pequena de mais), mas o relatorio sai
    # mudo sobre qual dos dois faltou -- e essa e a mesma razao de existir do
    # assert do piso de turnos, duas linhas acima.
    positivas, negativas = _positivas_e_negativas(observadas)
    assert positivas >= PISO_DE_TURNOS_ANOTADOS and negativas >= PISO_DE_TURNOS_NEGATIVOS, (
        f"{positivas} turnos anotados (piso {PISO_DE_TURNOS_ANOTADOS}) e {negativas} "
        f"negativos (piso {PISO_DE_TURNOS_NEGATIVOS}) sobraram na execucao. Amostra "
        f"insuficiente para a precisao da extracao significar algo depois do "
        f"abandono: re-rode.\n{relatorio}"
    )
    assert not bloqueia(metricas), relatorio
