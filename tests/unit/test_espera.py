"""A regra pura da lista de espera. TEC-169, RN-11.5.

Nao toca banco. Ver o conftest raiz: `tests/unit/` sai cedo de `banco_limpo`.

O que os textos afirmam e checado em `test_promessa_ao_lead.py` e
`test_acento_no_texto_ao_lead.py`, que leem `literais_ao_lead.py` -- aqui se
verifica o que e proprio deste modulo: o kind, o template e o horizonte.
"""

import uuid
from datetime import timedelta

from mobia.domain.agendamento.espera import (
    HORIZONTE_ESTENDIDO,
    PREFIXO_DO_KIND,
    TEMPLATE_DO_AVISO,
    kind_do_aviso,
    template_do_aviso,
)


def test_o_kind_cabe_na_coluna() -> None:
    """`outbound_dispatches.kind` e String(32). Estourar so apareceria no INSERT.

    Doze do prefixo mais vinte do hex fecham exatamente trinta e dois -- a
    mesma conta de `kind_da_confirmacao`, `kind_do_lembrete` e
    `kind_do_convite`.
    """
    assert len(PREFIXO_DO_KIND) == 12
    assert len(kind_do_aviso(uuid.uuid4())) == 32


def test_o_kind_e_por_linha_da_fila_e_nao_fixo() -> None:
    """Duas passagens pela fila do mesmo lead nao podem colidir.

    A reserva de `outbound_dispatches` e UNIQUE (message_id, kind) e a ancora
    e a ultima mensagem DO LEAD: com um kind fixo, o segundo aviso seria
    suprimido como reentrega para sempre.
    """
    assert kind_do_aviso(uuid.uuid4()) != kind_do_aviso(uuid.uuid4())


def test_sem_aprovacao_da_meta_nao_ha_template() -> None:
    """O default de `WHATSAPP_TEMPLATES_APROVADOS` e vazio, e e a realidade do RT-03."""
    assert template_do_aviso(aprovados=frozenset()) is None


def test_com_aprovacao_o_template_sai() -> None:
    assert template_do_aviso(aprovados=frozenset({TEMPLATE_DO_AVISO})) == TEMPLATE_DO_AVISO


def test_o_template_de_outra_card_nao_serve() -> None:
    """A aprovacao e por NOME: ter o do lembrete nao libera o desta card."""
    assert template_do_aviso(aprovados=frozenset({"lembrete_visita_24h"})) is None


def test_o_horizonte_estendido_e_maior_que_as_72_horas() -> None:
    """A relacao entre os dois numeros e o que faz a recusa valer a pena.

    Importado aqui dentro e nao no topo: `conversa.py` puxa banco e handoff, e
    este arquivo e de `tests/unit/`. O que se afirma e a ordem entre os dois,
    nao o valor de nenhum -- quem medir e mudar `HORIZONTE_ESTENDIDO` nao
    deveria precisar reescrever esta asserta, mas deveria reprovar se o
    encolhesse abaixo da regra do SRS.
    """
    from mobia.domain.agendamento.conversa import HORIZONTE

    assert HORIZONTE == timedelta(hours=72)
    assert HORIZONTE_ESTENDIDO > HORIZONTE
