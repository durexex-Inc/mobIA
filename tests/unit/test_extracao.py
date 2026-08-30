from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from anthropic import transform_schema

from mobia.domain.agente.classificador import SCHEMA_DA_EXTRACAO, extrair
from mobia.domain.agente.schemas import (
    _PREFIXOS_DE_REFERENCIA,
    Extracao,
    FormaPagamento,
    TipoImovel,
    Urgencia,
    normalizar_regiao,
)


def test_vocabulario_de_tipo_de_imovel():
    assert [membro.value for membro in TipoImovel] == [
        "APARTAMENTO",
        "CASA",
        "TERRENO",
        "COMERCIAL",
        "RURAL",
    ]


def test_vocabulario_de_urgencia():
    assert [membro.value for membro in Urgencia] == [
        "IMEDIATA",
        "ATE_3_MESES",
        "ATE_6_MESES",
        "SEM_PRESSA",
    ]


def test_vocabulario_de_forma_de_pagamento():
    assert [membro.value for membro in FormaPagamento] == [
        "A_VISTA",
        "FINANCIAMENTO",
        "CONSORCIO",
        "FGTS",
        "INDEFINIDA",
    ]


def test_extracao_sem_argumento_e_toda_none():
    vazia = Extracao()
    assert vazia.vazia() is True
    assert vazia.preenchidos() == {}


def test_preenchidos_devolve_so_os_campos_com_valor():
    extracao = Extracao(quartos=2, regiao="zona sul")
    assert extracao.vazia() is False
    assert extracao.preenchidos() == {"quartos": 2, "regiao": "zona sul"}


def test_preenchidos_nao_esconde_falso_nem_zero():
    """`if valor` descartaria `False` e `0`; a regra e `is not None`.

    Um lead que diz "nao tenho imovel pra vender" informou algo, e "sem vaga"
    e um criterio de busca tao real quanto "duas vagas".
    """
    extracao = Extracao(tem_imovel_para_vender=False, vagas=0)
    assert extracao.preenchidos() == {"tem_imovel_para_vender": False, "vagas": 0}


def test_extracao_e_imutavel():
    extracao = Extracao(quartos=2)
    with pytest.raises(FrozenInstanceError):
        extracao.quartos = 3  # type: ignore[misc]


def test_preco_guarda_precisao_de_decimal():
    extracao = Extracao(faixa_preco_max=Decimal("600000.00"))
    assert extracao.preenchidos() == {"faixa_preco_max": Decimal("600000.00")}


def test_schema_da_extracao_sobrevive_ao_compilador_do_sdk():
    """`transform_schema` encerra em `assert_never` para tipo desconhecido.

    `{"type": ["string", "null"]}` nao casa com nenhum ramo do dispatch e
    estoura aqui. `anyOf` e tratado por recursao. Este teste e a guarda contra
    alguem "simplificar" a anulabilidade de volta para lista.
    """
    compilado = transform_schema(SCHEMA_DA_EXTRACAO)
    assert compilado["type"] == "object"
    assert compilado["additionalProperties"] is False


def test_todos_os_nove_campos_sao_obrigatorios_e_anulaveis():
    propriedades = SCHEMA_DA_EXTRACAO["properties"]
    assert set(SCHEMA_DA_EXTRACAO["required"]) == set(propriedades)
    assert len(propriedades) == 9
    for nome, forma in propriedades.items():
        variantes = [variante.get("type") for variante in forma["anyOf"]]
        assert "null" in variantes, nome


def test_enums_do_schema_saem_dos_stre_enums():
    propriedades = SCHEMA_DA_EXTRACAO["properties"]
    for nome, enum in (
        ("tipo_imovel", TipoImovel),
        ("urgencia", Urgencia),
        ("forma_pagamento", FormaPagamento),
    ):
        nao_nulo = next(v for v in propriedades[nome]["anyOf"] if v.get("type") == "string")
        assert nao_nulo["enum"] == [membro.value for membro in enum]


def test_extrair_de_dicionario_completo():
    obtido = extrair(
        {
            "faixa_preco_min": None,
            "faixa_preco_max": 600000,
            "regiao": "zona sul",
            "tipo_imovel": "APARTAMENTO",
            "quartos": 2,
            "vagas": None,
            "urgencia": "ATE_3_MESES",
            "forma_pagamento": None,
            "tem_imovel_para_vender": False,
        }
    )
    assert obtido == Extracao(
        faixa_preco_max=Decimal("600000"),
        regiao="zona sul",
        tipo_imovel=TipoImovel.APARTAMENTO,
        quartos=2,
        urgencia=Urgencia.ATE_3_MESES,
        tem_imovel_para_vender=False,
    )


@pytest.mark.parametrize(
    "bruto",
    [None, "texto", 42, [], {"quartos": {"aninhado": 1}}],
)
def test_extrair_nunca_levanta(bruto):
    """Extracao e enriquecimento; a resposta ao lead vem da mesma chamada."""
    assert isinstance(extrair(bruto), Extracao)


def test_chave_ausente_nao_e_erro():
    assert extrair({"quartos": 2}) == Extracao(quartos=2)


@pytest.mark.parametrize(
    "valor",
    [-1, 0, 10**9 + 1, "seiscentos mil", float("nan"), float("inf"), True],
)
def test_preco_fora_da_faixa_e_descartado(valor):
    assert extrair({"faixa_preco_max": valor, "quartos": 2}) == Extracao(quartos=2)


def test_faixa_invertida_descarta_os_dois_precos():
    obtido = extrair({"faixa_preco_min": 900000, "faixa_preco_max": 600000, "quartos": 2})
    assert obtido == Extracao(quartos=2)


def test_faixa_igual_nos_dois_lados_e_valida():
    """ "exatamente 600 mil" nao e faixa invertida."""
    obtido = extrair({"faixa_preco_min": 600000, "faixa_preco_max": 600000})
    assert obtido.faixa_preco_min == Decimal("600000")
    assert obtido.faixa_preco_max == Decimal("600000")


@pytest.mark.parametrize("campo", ["quartos", "vagas"])
@pytest.mark.parametrize("valor", [-1, 21, 2.5, "dois", True])
def test_inteiro_fora_da_faixa_e_descartado(campo, valor):
    assert extrair({campo: valor, "regiao": "centro"}) == Extracao(regiao="centro")


@pytest.mark.parametrize("campo", ["quartos", "vagas"])
def test_zero_e_valido(campo):
    """Kitnet tem 0 quarto e imovel sem garagem tem 0 vaga."""
    assert extrair({campo: 0}).preenchidos() == {campo: 0}


def test_valor_de_enum_desconhecido_e_descartado():
    obtido = extrair({"tipo_imovel": "IATE", "quartos": 2})
    assert obtido == Extracao(quartos=2)


def test_regiao_vazia_ou_so_espaco_e_descartada():
    assert extrair({"regiao": "   "}) == Extracao()


def test_regiao_e_truncada_no_limite_da_coluna():
    """`lead_qualification.regiao` e `String(120)`: 121 caracteres seria
    DataError no commit, derrubando o turno inteiro por um campo opcional."""
    obtido = extrair({"regiao": "a" * 200})
    assert obtido.regiao is not None
    assert len(obtido.regiao) == 120


def test_regiao_com_prefixo_e_truncada_depois_de_normalizar():
    """Prefixo e truncamento juntos, sem teste ate agora: `_regiao` normaliza
    antes de truncar (ver docstring), entao o prefixo tem de sair antes da
    contagem dos 120 caracteres, nao depois."""
    obtido = extrair({"regiao": "perto da " + "a" * 200})
    assert obtido.regiao is not None
    assert len(obtido.regiao) == 120
    assert obtido.regiao == "a" * 120


def test_booleano_so_aceita_booleano():
    assert extrair({"tem_imovel_para_vender": "sim"}) == Extracao()


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        # O lado ANOTADO sujo: as duas unicas anotacoes do corpus com preposicao.
        ("perto da usp", "usp"),
        ("perto da unicamp", "unicamp"),
        # O lado OBTIDO sujo, que e o caso maioritario: o modelo devolve a
        # forma da fala, e 16 das 18 anotacoes ja sao toponimo limpo.
        ("regiao do brooklin", "brooklin"),
        ("regiao dos jardins", "jardins"),
        ("regiao da paulista", "paulista"),
        ("na regiao da paulista", "paulista"),
        ("estacao vila madalena", "vila madalena"),
        # Prefixos encadeados caem no mesmo passe.
        ("perto da estacao vila madalena", "vila madalena"),
        # Caixa e espaco sobrando.
        ("  Vila   Mariana  ", "vila mariana"),
    ],
)
def test_normalizar_regiao_tira_o_ruido_de_referencia(bruto: str, esperado: str) -> None:
    assert normalizar_regiao(bruto) == esperado


@pytest.mark.parametrize(
    ("fala", "esperado"),
    [
        # A familia `na regiao` tinha `da` e `do` e faltavam tres.
        ("na regiao de sao roque", "sao roque"),
        ("na regiao das flores", "flores"),
        ("na regiao dos lagos", "lagos"),
        # `proximo` e `perto` tinham o singular e faltava o plural.
        ("proximo das clinicas", "clinicas"),
        ("proximo dos jardins", "jardins"),
        ("perto das lojas", "lojas"),
        ("perto dos jardins", "jardins"),
        # `perto` tinha `de` e `proximo` nao. Terceira assimetria da
        # familia, fechada na revisao final da TEC-246.
        ("proximo de sao roque", "sao roque"),
    ],
)
def test_normalizar_regiao_trata_as_familias_de_prefixo_simetricamente(
    fala: str, esperado: str
) -> None:
    """A lista tinha `na regiao da/do` e ignorava `de/das/dos`.

    O corpus so exercitava `da` e `do`, entao o furo era latente -- mas "na
    regiao de" e portugues corrente, e forma nao-canonica de `regiao` respondeu
    por 10 das 29 discrepancias de 28/08. Foi o que originou a TEC-241.
    """
    assert normalizar_regiao(fala) == esperado


def test_normalizar_regiao_nao_come_o_de_de_um_toponimo() -> None:
    """`das` so sai depois de `regiao`, `proximo` ou `perto`.

    `compra-04` anota `regiao: jardim das flores`. Se a lista ganhasse `das `
    solto, o toponimo viraria "flores" e a anotacao existente passaria a nao
    casar consigo mesma.
    """
    assert normalizar_regiao("jardim das flores") == "jardim das flores"


@pytest.mark.parametrize("nome", ["zona leste", "zona sul", "zona oeste"])
def test_normalizar_regiao_nao_come_zona(nome: str) -> None:
    """`zona` e o nome, nao ruido. Tres anotacoes do corpus dependem disto, e
    perde-las transformaria a normalizacao no defeito que ela vem consertar."""
    assert normalizar_regiao(nome) == nome


@pytest.mark.parametrize(
    "nome", ["brooklin", "itaim bibi", "jardim das flores", "tatuape", "sp", "cotia"]
)
def test_normalizar_regiao_nao_mexe_em_toponimo_limpo(nome: str) -> None:
    assert normalizar_regiao(nome) == nome


def test_normalizar_regiao_so_tira_prefixo_e_nao_subcadeia() -> None:
    """ "estacao" no meio de um nome sobrevive. So some quando abre a string."""
    assert normalizar_regiao("bairro estacao velha") == "bairro estacao velha"
    # Perda conhecida e aceita, nao bug: quando "estacao" abre a string, o
    # prefixo casa mesmo em toponimo real, e o primeiro token some junto.
    # "Estacao Velha" e bairro de Campina Grande; "regiao dos lagos" e nome
    # proprio no RJ (ver D2 do spec). O corpus desta card e SP-only, entao
    # nenhum dos dois aparece nele -- mas o prefixo nao sabe disso, e por isso
    # o risco fica medido aqui em vez de so declarado em prosa.
    assert normalizar_regiao("estacao velha") == "velha"


def test_regiao_que_e_so_ruido_vira_vazio() -> None:
    """Quem decide o que fazer com o vazio e o chamador: `extrair` descarta o
    campo. Devolver o original aqui gravaria ruido no banco."""
    assert normalizar_regiao("perto da") == ""
    assert normalizar_regiao("   ") == ""


def test_normalizar_regiao_e_idempotente() -> None:
    """Vale por construcao, porque a remocao repete ate nao casar -- este teste
    e o que garante que continue valendo se alguem trocar o laco por um passe."""
    for bruto in ("perto da estacao vila madalena", "regiao do brooklin", "zona sul"):
        uma = normalizar_regiao(bruto)
        assert normalizar_regiao(uma) == uma


def test_extrair_grava_regiao_na_forma_canonica() -> None:
    """O banco passa a guardar o que a TEC-158 consegue filtrar. Sem isto, a
    normalizacao existiria so para a medicao e o filtro SQL continuaria
    comparando formas que o modelo escolheu."""
    extracao = extrair({"regiao": "perto da estacao Vila Madalena"})

    assert extracao.regiao == "vila madalena"


def test_extrair_descarta_regiao_que_e_so_ruido() -> None:
    """Vazio nao pode ser gravado: a TEC-158 filtraria por string vazia. Segue
    a mesma regra das outras guardas de `extrair` -- campo malformado e
    descartado um a um, sem derrubar a resposta."""
    assert extrair({"regiao": "perto da"}).regiao is None


def test_extrair_preserva_toponimo_limpo() -> None:
    assert extrair({"regiao": "Itaim Bibi"}).regiao == "itaim bibi"


def test_nenhum_prefixo_de_referencia_e_prefixo_de_outro() -> None:
    """Guarda estrutural: sem ela, acrescentar por exemplo "regiao " solto a
    lista faria o resultado de `normalizar_regiao` passar a depender da ordem
    de iteracao de `_PREFIXOS_DE_REFERENCIA` -- o laco para no primeiro que
    casar, entao dois prefixos em relacao de prefixo-de-prefixo dariam
    resultados diferentes conforme qual deles o `for` visita primeiro, em
    silencio, sem nenhum teste acusando."""
    colisoes = [
        (a, b)
        for a in _PREFIXOS_DE_REFERENCIA
        for b in _PREFIXOS_DE_REFERENCIA
        if a != b and b.startswith(a)
    ]
    assert colisoes == []


# --- TEC-248: os quatro mecanismos que a sonda dos sete mediu ---------------
#
# Cada par abaixo e um valor REAL devolvido pelo modelo em
# `evals/relatorios/2026-08-30-sonda-regiao.md`, e nao um par inventado. Foi
# essa a diferenca que fez a TEC-248 custar nove chamadas em vez de outra
# execucao de 146: sem os valores nao havia como saber o que consertar.


@pytest.mark.parametrize(
    ("obtido", "esperado"),
    [
        # Acento puro. `saude` e `aclimacao`, os dois turnos em que o unico
        # desacordo era o diacritico.
        ("saude", "saude"),
        ("aclimacao", "aclimacao"),
        # Cedilha decompoe junto com o til: um caractere, dois diacriticos.
        ("assuncao", "assuncao"),
    ],
)
def test_normalizar_regiao_dobra_acento(obtido: str, esperado: str) -> None:
    """O modelo nao e consistente com acento, e a regua nao pode depender disso.

    A mesma execucao devolveu `saude` e `aclimacao` COM acento e `butanta` e
    `tatuape` SEM -- e as duas ultimas casaram justamente por isso. Adivinhar
    qual das duas formas vem e depender de sorte.
    """
    assert normalizar_regiao(obtido) == esperado


def test_normalizar_regiao_derruba_qualificador_entre_parenteses() -> None:
    """`compra-13[0]`: o modelo devolveu "sao roque (sp)" para um corpus que
    anota "sao roque". Parentese e ruido de referencia como os prefixos, so
    que no fim em vez de no comeco."""
    assert normalizar_regiao("sao roque (sp)") == "sao roque"


def test_normalizar_regiao_fica_com_o_pedaco_antes_da_virgula() -> None:
    """`aluguel-06[1]`: o modelo devolveu "vila madalena (perto da estacao),
    sao paulo". Ele responde o LUGAR, e anexa o contexto mais largo depois da
    virgula -- o que o filtro SQL compara e o primeiro pedaco.

    Exercita os tres passes de uma vez, e a ordem entre eles: o acento tem de
    cair antes dos prefixos, senao `estacao` com acento nunca casaria com o
    prefixo `estacao ` que e escrito sem.
    """
    assert normalizar_regiao("vila madalena (perto da estacao), sao paulo") == "vila madalena"


@pytest.mark.parametrize("fala", ["avenida paulista", "av. paulista", "av paulista"])
def test_normalizar_regiao_derruba_logradouro(fala: str) -> None:
    """`compra-08[1]`: "avenida paulista" contra "paulista" anotado.

    So `avenida ` foi observada. `av. ` e `av ` entram por simetria -- a
    licao que a TEC-246 tirou do proprio caro e que lista de prefixo
    assimetrica e bug latente, que so aparece quando alguem escreve a forma
    que faltava.
    """
    assert normalizar_regiao(fala) == "paulista"


def test_normalizar_regiao_nao_inventa_expansao_de_abreviacao() -> None:
    """ "sp" e "sao paulo" continuam DIFERENTES, e isso e de proposito.

    Os dois turnos com `sp` nao eram defeito de regua: o modelo devolveu o
    lugar ("sao paulo") e o corpus anotava a abreviacao do lead. Quem estava
    errado era a anotacao, e ela foi corrigida -- ver a regra em
    `TurnoAnotado`. Resolver isso na normalizacao exigiria uma tabela de
    apelidos, que e onde a funcao deixaria de normalizar forma e passaria a
    decidir semantica.
    """
    assert normalizar_regiao("sp") != normalizar_regiao("sao paulo")
