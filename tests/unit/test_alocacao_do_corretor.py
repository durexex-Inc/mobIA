"""Alocacao do corretor por especialidade e regiao, testada. TEC-166, RN-11.2, RN-07.4.

Puro: os `Corretor` sao objetos transientes, nunca gravados, e a contagem de
visitas do dia entra como dicionario.
"""

import pytest

from mobia.domain.agendamento.alocacao import CriterioDoLead, criterio_de, regiao_casa
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.vocabulario import Especialidade


def _qualificacao(**campos: object) -> LeadQualification:
    return LeadQualification(channel="whatsapp", conversation_key="5511911111111", **campos)


# --- o criterio do lead ---


@pytest.mark.parametrize("intencao", ["COMPRA", "ALUGUEL"])
def test_compra_e_aluguel_viram_a_especialidade_de_mesmo_nome(intencao: str) -> None:
    criterio = criterio_de(_qualificacao(intencao=intencao, regiao="zona sul"))
    assert criterio == CriterioDoLead(Especialidade(intencao), "zona sul")


def test_investimento_abaixo_do_limiar_e_investimento() -> None:
    criterio = criterio_de(
        _qualificacao(intencao="INVESTIMENTO", ticket_investimento_centavos=99_999_999)
    )
    assert criterio.especialidade == Especialidade.INVESTIMENTO


def test_investimento_no_limiar_exato_e_alto_ticket() -> None:
    criterio = criterio_de(
        _qualificacao(intencao="INVESTIMENTO", ticket_investimento_centavos=100_000_000)
    )
    assert criterio.especialidade == Especialidade.INVESTIMENTO_ALTO_TICKET


def test_investimento_sem_ticket_e_investimento() -> None:
    criterio = criterio_de(_qualificacao(intencao="INVESTIMENTO"))
    assert criterio.especialidade == Especialidade.INVESTIMENTO


@pytest.mark.parametrize(
    "intencao", ["INDEFINIDA", "VENDER_IMOVEL", "SUPORTE_CONTRATO", "FORA_DE_ESCOPO", None]
)
def test_intencao_sem_especialidade_vira_nulo(intencao: str | None) -> None:
    assert criterio_de(_qualificacao(intencao=intencao)).especialidade is None


def test_regiao_vazia_vira_nulo() -> None:
    assert criterio_de(_qualificacao(intencao="COMPRA", regiao="")).regiao is None
    assert criterio_de(_qualificacao(intencao="COMPRA")).regiao is None


# --- o casamento de regiao ---


@pytest.mark.parametrize(
    ("do_lead", "do_corretor"),
    [
        ("pinheiros", "pinheiros"),
        ("zona sul", "zona sul"),
        ("zona sul", "sul"),
        ("sul", "zona sul"),
        ("centro", "regiao do centro"),
    ],
)
def test_regioes_que_casam(do_lead: str, do_corretor: str) -> None:
    assert regiao_casa(do_lead, do_corretor)


@pytest.mark.parametrize(
    ("do_lead", "do_corretor"),
    [
        ("moema", "zona sul"),  # bairro nao vira zona (D2)
        ("zona sul", "zona norte"),
        ("pinheiros", "moema"),
    ],
)
def test_regioes_que_nao_casam(do_lead: str, do_corretor: str) -> None:
    assert not regiao_casa(do_lead, do_corretor)
