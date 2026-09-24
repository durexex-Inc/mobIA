"""A aritmetica do funil, sem banco. TEC-190, RN-17.2."""

from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.vocabulario import ETAPAS, Etapa

CHEIO = {
    Etapa.NOVO: 320,
    Etapa.EM_CONVERSA: 268,
    Etapa.QUALIFICADO: 141,
    Etapa.RECOMENDADO: 118,
    Etapa.HANDOFF_ACEITO: 39,
}


def test_as_seis_etapas_saem_sempre_e_na_ordem() -> None:
    funil = montar_funil(CHEIO)

    assert [e.nome for e in funil] == [
        "Novo",
        "Em conversa",
        "Qualificado",
        "Recomendado",
        "Agendado",
        "Handoff aceito",
    ]
    assert len(ETAPAS) == 6


def test_a_conversao_e_sobre_a_etapa_anterior() -> None:
    funil = montar_funil(CHEIO)

    assert funil[1].conversao_da_anterior == 268 / 320
    assert funil[2].conversao_da_anterior == 141 / 268


def test_a_primeira_etapa_nao_tem_conversao() -> None:
    """Primeira origem de nulo: nao ha anterior."""
    assert montar_funil(CHEIO)[0].conversao_da_anterior is None


def test_a_etapa_sem_fonte_sai_nula_e_nunca_zero() -> None:
    """D1: zero afirmaria que nenhuma visita foi marcada."""
    agendado = montar_funil(CHEIO)[4]

    assert agendado.nome == "Agendado"
    assert agendado.quantidade is None
    assert agendado.disponivel is False
    assert agendado.conversao_da_anterior is None


def test_a_etapa_depois_da_indisponivel_nao_tem_conversao() -> None:
    """Segunda origem de nulo: a anterior nao tem numero.

    Pular `Agendado` e dividir `Handoff aceito` por `Recomendado` daria um
    numero plausivel e errado.
    """
    handoff = montar_funil(CHEIO)[5]

    assert handoff.quantidade == 39
    assert handoff.conversao_da_anterior is None


def test_anterior_em_zero_da_conversao_nula_e_nao_divisao_por_zero() -> None:
    """Terceira origem de nulo -- a que nem a spec nomeava."""
    funil = montar_funil({**CHEIO, Etapa.EM_CONVERSA: 0, Etapa.QUALIFICADO: 0})

    assert funil[1].quantidade == 0
    assert funil[2].quantidade == 0
    assert funil[2].conversao_da_anterior is None


def test_periodo_sem_lead_nenhum_zera_tudo_sem_estourar() -> None:
    funil = montar_funil({etapa: 0 for etapa in ETAPAS if etapa is not Etapa.AGENDADO})

    assert [e.quantidade for e in funil] == [0, 0, 0, 0, None, 0]
    assert all(e.conversao_da_anterior is None for e in funil)


def test_etapa_disponivel_com_zero_continua_disponivel() -> None:
    """Zero medido NAO e ausencia de fonte -- e a distincao inteira da D1."""
    funil = montar_funil({**CHEIO, Etapa.QUALIFICADO: 0})

    assert funil[2].quantidade == 0
    assert funil[2].disponivel is True
