import re
from dataclasses import fields
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    Intencao,
    TipoImovel,
    Urgencia,
    normalizar_regiao,
)
from mobia.evals.corpus import ConversaAnotada, carregar, total_de_turnos
from mobia.evals.metricas import PISO_DE_TURNOS, PISO_DE_TURNOS_ANOTADOS, PISO_DE_TURNOS_NEGATIVOS

_VOCABULARIO = {
    "tipo_imovel": TipoImovel,
    "urgencia": Urgencia,
    "forma_pagamento": FormaPagamento,
}

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


@pytest.fixture(scope="module")
def conversas() -> list[ConversaAnotada]:
    return carregar(CORPUS)


def test_o_corpus_tem_as_cinquenta_conversas_do_card(
    conversas: list[ConversaAnotada],
) -> None:
    assert len(conversas) == 50


def test_o_corpus_passa_do_piso_de_turnos(conversas: list[ConversaAnotada]) -> None:
    """Abaixo do piso, um unico turno vale mais de 0,8% e a faixa amarela
    deixa de absorver o ruido entre execucoes."""
    assert total_de_turnos(conversas) >= PISO_DE_TURNOS


def test_toda_intencao_do_enum_aparece(conversas: list[ConversaAnotada]) -> None:
    """Uma intencao ausente do corpus e uma intencao cuja regressao o gate
    nao pega."""
    vistas = {turno.intencao for conversa in conversas for turno in conversa.turnos}

    assert vistas == set(Intencao)


def test_ha_conversas_com_mudanca_de_intencao_no_meio(
    conversas: list[ConversaAnotada],
) -> None:
    """Caso de borda exigido pelo card, e o unico que so faz sentido medido
    por turno."""
    mudam = [c for c in conversas if len({t.intencao for t in c.turnos}) > 1]

    assert len(mudam) >= 5


@pytest.mark.parametrize(
    ("intencao", "minimo"),
    [(Intencao.FORA_DE_ESCOPO, 3), (Intencao.INDEFINIDA, 3)],
)
def test_casos_de_borda_tem_massa_suficiente(
    conversas: list[ConversaAnotada], intencao: Intencao, minimo: int
) -> None:
    """Pedido fora de escopo e lead evasivo sao exigidos pelo card. Com um
    exemplo so, a metrica daquele caso e ruido."""
    quantos = sum(1 for c in conversas for t in c.turnos if t.intencao is intencao)

    assert quantos >= minimo


def test_ha_tentativas_de_injecao_marcadas(conversas: list[ConversaAnotada]) -> None:
    """Exigido pelo card. A convencao e o prefixo do id, porque nao ha campo
    proprio -- e nao vale a pena criar um so para isto."""
    injecoes = [c for c in conversas if c.id.startswith("borda-injecao")]

    assert len(injecoes) >= 2


def test_todo_id_e_prefixado_pela_categoria(conversas: list[ConversaAnotada]) -> None:
    prefixos = ("compra-", "aluguel-", "investimento-", "follow-up-", "borda-")

    for conversa in conversas:
        assert conversa.id.startswith(prefixos), conversa.id


def test_corpus_tem_turnos_anotados_suficientes(conversas: list[ConversaAnotada]) -> None:
    """Piso proprio: sem ele, anotar tres turnos faceis daria 100% de precisao
    num corpus que nao mede nada."""
    anotados = sum(1 for c in conversas for t in c.turnos if t.positivo)
    assert anotados >= PISO_DE_TURNOS_ANOTADOS


def test_todo_campo_de_extracao_tem_anotacao(conversas: list[ConversaAnotada]) -> None:
    """Campo sem anotacao nenhuma so pode subtrair da precisao da extracao.

    O denominador de `precisao_da_extracao` e a uniao do esperado com o obtido
    por turno. Um campo que o corpus nunca anota nao tem como somar acerto --
    nao ha anotacao contra a qual bater -- mas entra no total toda vez que o
    modelo o extrai. O gate passa a premiar quem se recusa a extrair aquele
    campo, que e o oposto do que a TEC-145 existe para medir.

    A lista sai de `fields(Extracao)` e nao de um literal: a proxima card que
    acrescentar campo quebra este teste, em vez de reabrir o buraco em
    silencio.
    """
    anotados = {
        nome
        for conversa in conversas
        for turno in conversa.turnos
        if turno.positivo
        for nome in turno.campos
    }
    todos = {campo.name for campo in fields(Extracao)}

    assert todos - anotados == set()


def test_anotacao_nunca_usa_valor_fora_do_vocabulario(conversas: list[ConversaAnotada]) -> None:
    """`carregar` ja levanta nesse caso; este teste guarda o corpus commitado."""
    for conversa in conversas:
        for turno in conversa.turnos:
            for nome, enum in _VOCABULARIO.items():
                if turno.positivo and nome in turno.campos:
                    assert turno.campos[nome] in [membro.value for membro in enum]


def test_o_corpus_tem_turnos_negativos_anotados(conversas: list[ConversaAnotada]) -> None:
    """Sem turno negativo, invencao so e medida onde o lead afirmou alguma
    coisa -- e um modelo que inventa em todo turno nao anotado tira 100%."""
    negativos = sum(1 for c in conversas for t in c.turnos if t.negativo)

    assert negativos >= PISO_DE_TURNOS_NEGATIVOS


def test_ha_turno_de_correcao_anotado(conversas: list[ConversaAnotada]) -> None:
    """A sobrescrita pelo mais novo (D4 do spec) precisa de caso no corpus."""
    for conversa in conversas:
        regioes = [
            turno.campos["regiao"]
            for turno in conversa.turnos
            if turno.positivo and "regiao" in turno.campos
        ]
        if len(regioes) >= 2 and len(set(regioes)) >= 2:
            return
    pytest.fail("nenhuma conversa anotada troca de regiao: a sobrescrita nao e medida")


# As duas unicas anotacoes com preposicao do corpus (D5 do spec): ficam como
# estao, de proposito, e a normalizacao existe para fundi-las com o toponimo
# limpo que uma anotacao nova, seguindo a regra do cabecalho do YAML, vai
# escrever. Uma anotacao nova de `usp` colide com `perto da usp` por
# construcao -- e esse merge e o motivo da TEC-241 existir, nao uma regressao.
_ANOTACOES_COM_PREPOSICAO_GRANDFATHERED = {"perto da usp", "perto da unicamp"}


def test_anotacoes_de_regiao_nao_colidem_depois_de_normalizadas(
    conversas: list[ConversaAnotada],
) -> None:
    """Fora das duas excecoes grandfathered, normalizar nao pode fundir duas
    anotacoes de regiao distintas numa so.

    `perto da usp` e `perto da unicamp` colidem de proposito com `usp` e
    `unicamp` -- essas duas ja sao excluidas do agrupamento, porque colidir e
    exatamente o que a TEC-241 existe para produzir (ver D5 do spec): elas
    ficam com preposicao, grandfathered, enquanto uma anotacao nova do mesmo
    lugar ja nasce como toponimo limpo. Fora dessas duas, uma colisao seria
    sinal real de que a normalizacao esta fundindo regioes que nao deveriam
    virar a mesma string, e e isso que este teste continua guardando.
    """
    por_forma: dict[str, set[str]] = {}
    for conversa in conversas:
        for turno in conversa.turnos:
            if turno.campos and "regiao" in turno.campos:
                bruta = turno.campos["regiao"]
                if bruta in _ANOTACOES_COM_PREPOSICAO_GRANDFATHERED:
                    continue
                por_forma.setdefault(normalizar_regiao(bruta), set()).add(bruta)

    colisoes = {forma: brutas for forma, brutas in por_forma.items() if len(brutas) > 1}

    assert colisoes == {}, f"formas distintas normalizam para a mesma: {colisoes}"


# Palavras que o lead usa e que NAO estao em `TipoImovel`. Seis, e nao as
# cinco do mapa da TEC-242: `republica` entra aqui de proposito, apesar de nao
# ter traducao, por motivo prospectivo -- hoje ela nao muda nada (o unico
# turno que a usa, `aluguel-07` i0, ja contem "kitnet" e seria detectado sem
# ela), mas um turno futuro que diga so "procuro uma republica perto da puc",
# sem outro sinonimo junto, precisa ser detectado e forcado a uma decisao
# explicita -- entrar na lista de excecoes ou ganhar `tipo_imovel` -- em vez
# de entrar sem tipo em silencio.
#
# Fronteira de palavra, e nao substring crua: `studio` e substring de
# "estudio", e `cobertura` e polissemica em portugues ("o seguro tem
# cobertura pra danos?"). A polissemia de `cobertura` e inerente a lingua, e a
# lista de excecoes abaixo e a valvula para ela -- nao ha regex que a
# elimine.
_SINONIMOS_DE_TIPO_IMOVEL = re.compile(r"\b(kitnet|studio|flat|cobertura|sobrado|republica)\b")

# `aluguel-07` i0 diz "procuro republica ou kitnet": o lead oferece duas
# tipologias e nao escolhe nenhuma. Anotar uma delas puniria o modelo por
# escolher a outra, que e o erro simetrico que a regua ja pune.
#
# A lista acolhe mais de um caso: tambem cabe aqui o turno em que o sinonimo
# descreve o imovel que o lead **tem**, e nao o que procura -- pela mesma
# regra que exclui `tem_imovel_para_vender` de `tipo_imovel` (ver docstring
# de `TurnoAnotado`). "comprei um sobrado com voces e agora preciso vender"
# anota `{tem_imovel_para_vender: true}`, sem `tipo_imovel`, e o guarda exige
# tipo ou excecao -- e essa e a excecao.
_SEM_TIPO_APESAR_DO_SINONIMO = {("aluguel-07", 0)}


def _turnos_sem_tipo_imovel(
    conversas: list[ConversaAnotada],
    padrao: re.Pattern[str],
    excecoes: set[tuple[str, int]],
) -> list[tuple[str, int, str]]:
    """Turnos cuja fala casa `padrao` e que nao anotam `tipo_imovel`.

    Os dois guardas de tipologia diferem so no vocabulario que varrem e nas
    excecoes que aceitam; o laco e o mesmo, e duas copias dele divergiriam.
    """
    faltando = []
    for conversa in conversas:
        for indice, turno in enumerate(conversa.turnos):
            if (conversa.id, indice) in excecoes:
                continue
            if not padrao.search(turno.lead.casefold()):
                continue
            if not (turno.campos and "tipo_imovel" in turno.campos):
                faltando.append((conversa.id, indice, turno.lead[:50]))
    return faltando


def test_todo_turno_com_sinonimo_tem_tipo_imovel_anotado(
    conversas: list[ConversaAnotada],
) -> None:
    """A traducao que o modelo faz certo nao pode contar erro.

    O schema da chamada e estrito: o modelo nunca devolve "kitnet", ele
    devolve `APARTAMENTO`. Se o corpus nao anota nada nesse turno, a uniao
    conta o campo como `extra` -- erro cheio, por acertar. Foi assim que
    `tipo_imovel` virou 8 das 29 discrepancias da execucao de 28/08.

    Sem este teste, o proximo turno com "kitnet" entra sem tipo e a punicao
    volta em silencio.
    """
    faltando = _turnos_sem_tipo_imovel(
        conversas, _SINONIMOS_DE_TIPO_IMOVEL, _SEM_TIPO_APESAR_DO_SINONIMO
    )
    assert faltando == [], f"turnos com sinonimo e sem `tipo_imovel`: {faltando}"


# As palavras do proprio vocabulario, e nao os sinonimos da TEC-242. O guarda
# dela varre "kitnet" e "sobrado"; um turno que diz "apartamento" com todas as
# letras passava batido, e dois turnos POSITIVOS -- anotacao declarada
# completa -- estavam nesse estado.
#
# `apto` entra porque o corpus ja o usa (`aluguel-05` i0, `borda-injecao-01`
# i1). `sala comercial` entra como locucao, e nao `comercial` sozinho, que
# aparece em "uso comercial de saude" descrevendo alvara e nao tipologia.
#
# O plural entra em todas elas: "apartamentos", "casas", "terrenos", "salas
# comerciais". Nenhum turno do corpus pluraliza hoje, entao a forma larga nao
# muda contagem nenhuma agora -- ela existe pra que a promessa do guarda
# ("turno novo tem de anotar o tipo ou entrar na lista de excecao") valha
# tambem pra fala que cita mais de um imovel.
#
# `sala comercial` e `salas comerciais` vao escritas por extenso, e nao como
# `salas? comerciais?`: esse sufixo opcional casa "salas comerciais", mas NAO
# o singular "sala comercial" -- que e a forma que o corpus usa (`aluguel-08`
# i0) --, porque o plural de "comercial" e "comerciais" e nao "comercials".
# Locucao com duas palavras flexionadas nao pluraliza com um `?` em cada.
_LITERAIS_DE_TIPO_IMOVEL = re.compile(
    r"\b(apartamentos?|aptos?|casas?|terrenos?|sala comercial|salas comerciais)\b"
)

# O imovel que o lead TEM nao e o que ele procura -- a regra da TEC-239, que
# ja esta no docstring de `TurnoAnotado` e ate agora nao tinha teste. Estes
# dois turnos sao o caso literal dela: os dois anotam
# `tem_imovel_para_vender: true` e nenhum anota `tipo_imovel`, e os dois estao
# certos.
_TIPO_E_DO_IMOVEL_QUE_O_LEAD_TEM = {("follow-up-03", 0), ("follow-up-06", 0)}


def test_todo_turno_com_palavra_do_vocabulario_tem_tipo_imovel_anotado(
    conversas: list[ConversaAnotada],
) -> None:
    """A regra do imovel que o lead TEM ganha guarda.

    A TEC-242 fechou isto para sinonimos e deixou aberto para as palavras
    literais: um turno novo que diga "apartamento" e nao anote `tipo_imovel`
    entrava sem tipo em silencio, e a extracao certa contava `extra`.

    As excecoes nao sao valvula de escape: cada uma e um turno em que a
    tipologia descreve o imovel que o lead ja possui. Turno novo tem de
    escolher entre anotar o tipo ou entrar aqui com motivo escrito.
    """
    faltando = _turnos_sem_tipo_imovel(
        conversas, _LITERAIS_DE_TIPO_IMOVEL, _TIPO_E_DO_IMOVEL_QUE_O_LEAD_TEM
    )
    assert faltando == [], f"turnos com palavra do vocabulario e sem `tipo_imovel`: {faltando}"


# Os turnos que ficam FORA da medicao de extracao, e o motivo de cada um em
# uma linha. A lista e exaustiva de proposito: turno novo sem `campos` quebra
# este teste, e quem o acrescentar tem de decidir -- anotar ou entrar aqui.
#
# Antes desta card havia 56 turnos fora da medicao e cinco motivos escritos.
# Os outros 51 nao eram decisao tomada, eram silencio, e silencio numa regua
# le como "nao ha o que medir aqui" quando na verdade era "ninguem olhou".
_FORA_DA_MEDICAO = {
    ("aluguel-03", 1): "atributo (terrea) sugere CASA sem nomear a tipologia",
    ("borda-evasivo-02", 1): "omissao nao e asercao de completude (TEC-238)",
    ("borda-evasivo-02", 2): "omissao nao e asercao de completude (TEC-238)",
    ("borda-mista-01", 2): "escritura: pressupoe o terreno do turno anterior",
    ("borda-mista-02", 2): "perto do metro: proximidade sem toponimo",
    ("compra-01", 1): "850 mil acima do que consigo: teto sugerido, nao afirmado",
    ("compra-02", 2): "perto de metro: proximidade sem toponimo",
    ("compra-04", 1): "mais que o dobro do que eu tinha em mente: teto sugerido",
    ("compra-07", 1): "sabado de manha: sem ancora de semana",
    ("compra-08", 2): "parcelamento direto nao e valor de FormaPagamento",
    ("compra-11", 1): "permuta com carro nao e valor de FormaPagamento",
    ("follow-up-01", 1): "juntar entrada sugere financiamento sem nomear",
    ("follow-up-03", 1): "pergunta de processo que pressupoe o imovel (TEC-238)",
    ("follow-up-03", 2): "financiamento que o lead ja tem, nao o pretendido (TEC-238)",
    ("investimento-04", 1): "pressupoe o financiamento, nao pergunta se pode usar",
    ("investimento-05", 0): "grana parada sugere A_VISTA sem afirmar",
}


def test_todo_turno_fora_da_medicao_tem_motivo_escrito(
    conversas: list[ConversaAnotada],
) -> None:
    """Fora da medicao passa a ser decisao, e nao esquecimento.

    Turno sem `campos` nao tem cobertura de invencao nenhuma: nao ha
    `esperado` contra o qual comparar, entao o turno sai da conta inteiro. Que
    isso seja verdade para 16 turnos e escolha; que fosse verdade para 56 sem
    ninguem ter olhado era acidente.

    Comentario de YAML nao sobrevive ao `yaml.safe_load`, entao o conjunto
    declarado aqui e o que guarda -- o comentario no arquivo e para quem le o
    corpus.
    """
    fora = {
        (conversa.id, indice)
        for conversa in conversas
        for indice, turno in enumerate(conversa.turnos)
        if turno.campos is None
    }
    assert fora == set(_FORA_DA_MEDICAO), (
        f"sem motivo escrito: {sorted(fora - set(_FORA_DA_MEDICAO))}; "
        f"declarados e ja anotados: {sorted(set(_FORA_DA_MEDICAO) - fora)}"
    )
