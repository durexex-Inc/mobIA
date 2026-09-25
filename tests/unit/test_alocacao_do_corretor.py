"""Alocacao do corretor por especialidade e regiao, testada. TEC-166, RN-11.2, RN-07.4.

Puro: os `Corretor` sao objetos transientes, nunca gravados, e a contagem de
visitas do dia entra como dicionario.
"""

import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.agendamento.alocacao import (
    Alocacao,
    CriterioDoLead,
    alocar,
    criterio_de,
    regiao_casa,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.models import Corretor
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


# --- a alocacao ---


_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _corretor(
    nome: str,
    *,
    especialidades: tuple[str, ...] = ("COMPRA",),
    regioes: tuple[str, ...] = ("zona sul",),
    plantao: bool = False,
    ativo: bool = True,
    capacidade: int = 3,
    ordem: int = 0,
) -> Corretor:
    return Corretor(
        id=uuid.uuid4(),
        nome=nome,
        especialidades=list(especialidades),
        regioes_atuacao=list(regioes),
        plantao=plantao,
        ativo=ativo,
        capacidade_diaria=capacidade,
        horario_inicio=9,
        horario_fim=18,
        criado_em=_BASE.replace(day=1 + ordem),
    )


def _nomes(alocacoes: list[Alocacao]) -> list[tuple[str, MotivoDaAlocacao]]:
    return [(a.corretor.nome, a.motivo) for a in alocacoes]


COMPRA_SUL = CriterioDoLead(Especialidade.COMPRA, "zona sul")


# --- os cenarios da card ---


def test_match_exato_e_escolhido_com_o_motivo() -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", especialidades=("ALUGUEL",), regioes=("norte",), plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao, ana], visitas_na_data={})
    assert _nomes(resultado)[0] == ("ana", MotivoDaAlocacao.MATCH_EXATO)


def test_alto_ticket_so_considera_o_especialista() -> None:
    comum = _corretor("comum", especialidades=("INVESTIMENTO",), ordem=0)
    alto = _corretor("alto", especialidades=("INVESTIMENTO_ALTO_TICKET",), ordem=1)
    criterio = CriterioDoLead(Especialidade.INVESTIMENTO_ALTO_TICKET, "zona sul")
    resultado = alocar(criterio=criterio, corretores=[comum, alto], visitas_na_data={})
    assert _nomes(resultado) == [("alto", MotivoDaAlocacao.MATCH_EXATO)]


def test_sem_match_cai_no_plantao_com_o_motivo() -> None:
    ana = _corretor("ana", regioes=("zona norte",))
    plantao = _corretor("plantao", especialidades=("COMPRA",), regioes=("oeste",), plantao=True)
    criterio = CriterioDoLead(Especialidade.ALUGUEL, "zona leste")
    resultado = alocar(criterio=criterio, corretores=[ana, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_capacidade_esgotada_exclui_na_data() -> None:
    ana = _corretor("ana", capacidade=2, ordem=0)
    bia = _corretor("bia", capacidade=2, ordem=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana, bia], visitas_na_data={ana.id: 2})
    assert _nomes(resultado) == [("bia", MotivoDaAlocacao.MATCH_EXATO)]


# --- as bordas ---


def test_match_esgotado_leva_o_plantao_com_match_sem_capacidade() -> None:
    ana = _corretor("ana", capacidade=1)
    plantao = _corretor("plantao", regioes=("norte",), plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana, plantao], visitas_na_data={ana.id: 1})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE)]


def test_plantao_tambem_esgotado_da_lista_vazia() -> None:
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, capacidade=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={plantao.id: 1})
    assert resultado == []


def test_alto_ticket_sem_especialista_cai_no_plantao() -> None:
    comum = _corretor("comum", especialidades=("INVESTIMENTO",))
    plantao = _corretor("plantao", especialidades=("COMPRA",), regioes=("norte",), plantao=True)
    criterio = CriterioDoLead(Especialidade.INVESTIMENTO_ALTO_TICKET, "zona sul")
    resultado = alocar(criterio=criterio, corretores=[comum, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


@pytest.mark.parametrize(
    "criterio",
    [
        CriterioDoLead(Especialidade.COMPRA, None),
        CriterioDoLead(None, "zona sul"),
        CriterioDoLead(None, None),
    ],
)
def test_criterio_incompleto_nao_tem_match(criterio: CriterioDoLead) -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, ordem=1)
    resultado = alocar(criterio=criterio, corretores=[ana, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_empate_vai_para_o_mais_antigo() -> None:
    nova = _corretor("nova", ordem=5)
    antiga = _corretor("antiga", ordem=1)
    p_novo = _corretor("p_novo", regioes=("norte",), plantao=True, ordem=4)
    p_antigo = _corretor("p_antigo", regioes=("norte",), plantao=True, ordem=2)
    resultado = alocar(
        criterio=COMPRA_SUL, corretores=[nova, p_novo, antiga, p_antigo], visitas_na_data={}
    )
    assert _nomes(resultado) == [
        ("antiga", MotivoDaAlocacao.MATCH_EXATO),
        ("nova", MotivoDaAlocacao.MATCH_EXATO),
        ("p_antigo", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
        ("p_novo", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
    ]


def test_zona_casa_com_e_sem_prefixo() -> None:
    ana = _corretor("ana", regioes=("sul",))
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana], visitas_na_data={})
    assert _nomes(resultado) == [("ana", MotivoDaAlocacao.MATCH_EXATO)]


def test_bairro_nao_casa_zona() -> None:
    ana = _corretor("ana", regioes=("zona sul",))
    criterio = CriterioDoLead(Especialidade.COMPRA, "moema")
    assert alocar(criterio=criterio, corretores=[ana], visitas_na_data={}) == []


def test_inativo_nunca_entra_nem_conta_como_match() -> None:
    inativa = _corretor("inativa", ativo=False)
    plantao_inativo = _corretor("p_inativo", regioes=("norte",), plantao=True, ativo=False)
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, ordem=1)
    resultado = alocar(
        criterio=COMPRA_SUL, corretores=[inativa, plantao_inativo, plantao], visitas_na_data={}
    )
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_plantao_com_match_aparece_uma_vez_como_match() -> None:
    plantao = _corretor("plantao", plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.MATCH_EXATO)]


def test_plantao_com_match_esgotado_nao_volta_como_plantao() -> None:
    plantao = _corretor("plantao", plantao=True, capacidade=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={plantao.id: 1})
    assert resultado == []
