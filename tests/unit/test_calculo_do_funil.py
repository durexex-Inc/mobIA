"""A aritmetica do funil, sem banco. TEC-190, RN-17.2."""

from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.vocabulario import ETAPAS, Etapa

CHEIO = {
    Etapa.NOVO: 320,
    Etapa.EM_CONVERSA: 268,
    Etapa.QUALIFICADO: 141,
    Etapa.RECOMENDADO: 118,
    Etapa.AGENDADO: 62,
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


def test_a_etapa_agendado_tem_numero_como_as_outras_cinco() -> None:
    """O contrario do que este arquivo afirmava ate a TEC-376.

    Ate ela, `Agendado` saia `quantidade: None` e `disponivel: False` porque
    nenhum caminho de producao criava agendamento. A TEC-371 passou a criar.
    """
    agendado = montar_funil(CHEIO)[4]

    assert agendado.nome == "Agendado"
    assert agendado.quantidade == 62
    assert agendado.disponivel is True
    assert agendado.conversao_da_anterior == 62 / 118


def test_a_conversao_de_handoff_aceito_deixou_de_ser_nula() -> None:
    """A segunda origem de nulo caiu junto com a etapa cega (TEC-376).

    Ela existia porque pular `Agendado` e dividir `Handoff aceito` por
    `Recomendado` daria um numero plausivel e errado. Sem etapa cega, a
    divisao e sobre a anterior de verdade.
    """
    handoff = montar_funil(CHEIO)[5]

    assert handoff.quantidade == 39
    assert handoff.conversao_da_anterior == 39 / 62


def test_anterior_em_zero_da_conversao_nula_e_nao_divisao_por_zero() -> None:
    """A unica origem de nulo que sobrou, alem da primeira etapa."""
    funil = montar_funil({**CHEIO, Etapa.EM_CONVERSA: 0, Etapa.QUALIFICADO: 0})

    assert funil[1].quantidade == 0
    assert funil[2].quantidade == 0
    assert funil[2].conversao_da_anterior is None


def test_periodo_sem_lead_nenhum_zera_tudo_sem_estourar() -> None:
    funil = montar_funil({etapa: 0 for etapa in ETAPAS})

    assert [e.quantidade for e in funil] == [0, 0, 0, 0, 0, 0]
    assert all(e.conversao_da_anterior is None for e in funil)


def test_etapa_ausente_do_mapa_conta_zero_e_continua_disponivel() -> None:
    """Zero medido NAO e ausencia de fonte -- e a distincao que a D1 da
    TEC-190 abriu e que a TEC-376 manteve ao apagar `SEM_FONTE`.

    Chave que nao veio do repositorio vale zero, e nao nulo: o repositorio
    devolve as seis, e uma faltando seria defeito dele, nao ausencia de fonte.
    """
    funil = montar_funil({**CHEIO, Etapa.QUALIFICADO: 0})

    assert funil[2].quantidade == 0
    assert funil[2].disponivel is True
