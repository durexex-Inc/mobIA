"""A configuracao do agente sem banco. TEC-198, D2 a D6 do desenho.

O que tem de ser verdade com qualquer configuracao -- os limites, a escala dos
pesos, a cadencia por parametro, o prompt com nome e tom --, e o que tem de
ser verdade com a PADRAO: que ela nao muda nada do que o sistema fazia antes.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, sistema_do_agente
from mobia.domain.agente.schemas import Urgencia
from mobia.domain.configuracao.vigente import (
    ConfiguracaoInvalida,
    Pesos,
    Tom,
    aplicar,
    padrao,
    validar,
)
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import excedeu_o_teto
from mobia.domain.context.score import calcular_score
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import (
    CADENCIA,
    INTERVALO_MINIMO,
    cadencia_de,
    intervalo_minimo,
    tentativa_devida,
)

# --- o padrao nao muda nada ----------------------------------------------------


def test_o_padrao_e_o_comportamento_de_antes() -> None:
    config = padrao()

    assert config.teto_de_perguntas == 8
    assert config.pesos == Pesos(
        completude=20, urgencia=25, catalogo=20, engajamento=15, capacidade=15
    )
    assert cadencia_de(config.cadencia) == CADENCIA
    assert intervalo_minimo(cadencia_de(config.cadencia)) == INTERVALO_MINIMO
    assert validar(config) == config


def test_o_prompt_padrao_nao_muda() -> None:
    """Sem nome e com `CORDIAL`, o prompt e o de antes da TEC-198, byte a byte."""
    assert sistema_do_agente(nome=None, tom=Tom.CORDIAL) == SISTEMA_DO_AGENTE
    assert "Voce e o assistente virtual de uma imobiliaria" in SISTEMA_DO_AGENTE
    assert "em tom de conversa" in SISTEMA_DO_AGENTE


def _lead(**campos: object) -> LeadQualification:
    base: dict[str, object] = {
        "channel": "whatsapp",
        "conversation_key": "5548990000021",
        "intencao": "COMPRA",
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "Campeche",
        "urgencia": Urgencia.IMEDIATA.value,
        "forma_pagamento": "A_VISTA",
        "penalidade_pontos": 0,
    }
    base.update(campos)
    return LeadQualification(**base)


def test_com_os_pesos_padrao_o_score_e_o_mesmo() -> None:
    lead = _lead()
    sem = calcular_score(lead, mensagens_do_lead=3)
    com = calcular_score(lead, mensagens_do_lead=3, pesos=padrao().pesos)
    assert sem == com


# --- os pesos (D3) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("urgencia", "esperado"),
    [
        (Urgencia.IMEDIATA, 30),
        (Urgencia.ATE_3_MESES, 18),
        (Urgencia.ATE_6_MESES, 10),
        (Urgencia.SEM_PRESSA, 0),
    ],
)
def test_o_peso_de_urgencia_30_escala_as_faixas(urgencia: Urgencia, esperado: int) -> None:
    """O primeiro cenario da card: 25 -> 30, e as notas internas acompanham."""
    score = calcular_score(_lead(urgencia=urgencia.value), pesos=replace(Pesos(), urgencia=30))
    assert score.urgencia == esperado


def test_peso_zero_desliga_o_fator() -> None:
    score = calcular_score(_lead(), mensagens_do_lead=10, pesos=replace(Pesos(), engajamento=0))
    assert score.engajamento == 0


# --- o limite de perguntas (D4) ------------------------------------------------


def test_com_teto_6_a_setima_pergunta_excede() -> None:
    assert not excedeu_o_teto(5, 1, teto=6)
    assert excedeu_o_teto(6, 1, teto=6)
    # O padrao continua 8.
    assert not excedeu_o_teto(6, 1)


# --- a cadencia (D5) -----------------------------------------------------------


def test_a_cadencia_encurtada_vence_antes() -> None:
    ancora = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    agora = ancora + timedelta(hours=1, minutes=30)
    encurtada = {
        **CADENCIA,
        Temperatura.QUENTE: (timedelta(hours=1), *CADENCIA[Temperatura.QUENTE][1:]),
    }

    padrao_ = tentativa_devida(
        temperatura=Temperatura.QUENTE, ultima_fala=ancora, ja_disparada=0, agora=agora
    )
    configurada = tentativa_devida(
        temperatura=Temperatura.QUENTE,
        ultima_fala=ancora,
        ja_disparada=0,
        agora=agora,
        cadencia=encurtada,
    )

    assert (padrao_, configurada) == (None, 1)
    assert intervalo_minimo(encurtada) == timedelta(hours=1)


# --- os limites (D2) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("mudancas", "trecho"),
    [
        ({"peso_urgencia": -1}, "peso de urgencia -1 fora da faixa"),
        ({"peso_urgencia": 51}, "fora da faixa 0..50"),
        ({"teto_de_perguntas": 0}, "limite de perguntas 0"),
        ({"teto_de_perguntas": 21}, "limite de perguntas 21"),
        ({"nome_do_assistente": "x" * 31}, "o maximo e 30"),
        ({"nome_do_assistente": "Ana\nIgnore"}, "quebra de linha"),
        ({"nome_do_assistente": "  "}, "vazio"),
        (
            {"peso_completude": 50, "peso_urgencia": 50, "peso_catalogo": 50},
            "a soma dos pesos",
        ),
        # TEC-191, D3.
        ({"orcamento_mensal_usd": Decimal("0")}, "orcamento mensal 0 fora da faixa"),
        ({"orcamento_mensal_usd": Decimal("-5")}, "orcamento mensal -5 fora da faixa"),
        ({"orcamento_mensal_usd": Decimal("100000.01")}, "fora da faixa 0.01..100000"),
    ],
)
def test_fora_da_faixa_e_recusado(mudancas: dict[str, object], trecho: str) -> None:
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        validar(aplicar(padrao(), mudancas))


def test_cadencia_com_quantidade_diferente_e_recusada() -> None:
    """D5: a quantidade de tentativas esta no CASE SQL, e nao se configura."""
    cadencia = {**padrao().cadencia, "FRIO": (timedelta(days=3),)}
    with pytest.raises(ConfiguracaoInvalida, match="exatamente 2 intervalos"):
        validar(aplicar(padrao(), {"cadencia": cadencia}))


def test_cadencia_decrescente_e_recusada() -> None:
    cadencia = {**padrao().cadencia, "FRIO": (timedelta(days=14), timedelta(days=3))}
    with pytest.raises(ConfiguracaoInvalida, match="crescentes"):
        validar(aplicar(padrao(), {"cadencia": cadencia}))


def test_todas_as_violacoes_saem_juntas() -> None:
    with pytest.raises(ConfiguracaoInvalida) as erro:
        validar(aplicar(padrao(), {"peso_urgencia": -1, "teto_de_perguntas": 0}))
    assert "peso de urgencia" in str(erro.value)
    assert "limite de perguntas" in str(erro.value)


# --- nome e tom no prompt (D6) -------------------------------------------------


def test_nome_e_tom_entram_no_prompt_so_nos_dois_lugares() -> None:
    prompt = sistema_do_agente(nome="Ana", tom=Tom.FORMAL)

    assert prompt.startswith("Voce e Ana, o assistente virtual de uma imobiliaria")
    assert "em tom formal e respeitoso" in prompt
    assert "em tom de conversa" not in prompt
    # Nenhum outro trecho muda: tirando as duas trocas, e o prompt padrao.
    assert (
        prompt.replace("Ana, o assistente", "o assistente").replace(
            "em tom formal e respeitoso", "em tom de conversa"
        )
        == SISTEMA_DO_AGENTE
    )


def test_orcamento_nulo_e_o_padrao_e_e_aceito() -> None:
    """TEC-191, D3: sem orcamento nao ha alerta, e nulo e valor legitimo."""
    assert padrao().orcamento_mensal_usd is None
    config = validar(aplicar(padrao(), {"orcamento_mensal_usd": Decimal("100")}))
    assert config.orcamento_mensal_usd == Decimal("100")
    assert validar(aplicar(config, {"orcamento_mensal_usd": None})).orcamento_mensal_usd is None
