"""A janela de 24h, o catalogo de templates e a escolha por contexto.

TEC-186, RN-13.6. Puro: nenhum destes toca banco.

A janela mora em `domain/outbound/janela.py` desde a TEC-171, e nao mais em
`followup/template.py`; continua exercitada daqui porque a decisao de canal do
follow-up e feita com ela e o catalogo juntos.
"""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.followup.mensagem import QuedaDePreco
from mobia.domain.followup.template import (
    CATEGORIA_CONVITE,
    CATEGORIA_IMOVEL_NOVO,
    CATEGORIA_QUEDA,
    TEMPLATES,
    categoria_da_novidade,
    escolher_template,
    parametros_do_template,
)
from mobia.domain.outbound.janela import JANELA_DE_SERVICO, dentro_da_janela

ANCORA = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

FICHA = Ficha(
    id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=59_000_000,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial=None,
    foto=None,
)
QUEDA = QuedaDePreco(
    imovel_id=FICHA.id, preco_antes_centavos=62_000_000, preco_agora_centavos=59_000_000
)


def test_a_janela_e_de_24h_e_a_borda_e_estrita() -> None:
    assert JANELA_DE_SERVICO == timedelta(hours=24)
    # Cenario 2: 4h < 24h -> dentro -> mensagem livre.
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=4)) is True
    # Cenario 1: 30h >= 24h -> fora -> template.
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=30)) is False
    # A borda exata ja esta FORA -- e a regra da Meta.
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=24)) is False


def test_o_catalogo_mantem_no_minimo_tres_e_uma_por_contexto() -> None:
    """RN-13.6: no minimo 3 templates, um por contexto do follow-up."""
    assert len(TEMPLATES) >= 3
    categorias = {t.categoria for t in TEMPLATES}
    assert categorias >= {CATEGORIA_QUEDA, CATEGORIA_IMOVEL_NOVO, CATEGORIA_CONVITE}
    # Nomes unicos: `escolher_template` devolve o primeiro que casa, e dois com
    # o mesmo nome/categoria esconderiam um.
    assert len({t.nome for t in TEMPLATES}) == len(TEMPLATES)
    assert all(t.idioma == "pt_BR" for t in TEMPLATES)


def test_a_categoria_segue_a_precedencia_de_texto_do_followup() -> None:
    assert categoria_da_novidade(ficha=FICHA, queda=QUEDA) == CATEGORIA_QUEDA
    assert categoria_da_novidade(ficha=FICHA, queda=None) == CATEGORIA_IMOVEL_NOVO
    assert categoria_da_novidade(ficha=None, queda=None) == CATEGORIA_CONVITE


def test_escolhe_o_template_da_categoria_quando_aprovado() -> None:
    aprovado = next(t for t in TEMPLATES if t.categoria == CATEGORIA_CONVITE)
    escolhido = escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset({aprovado.nome}))
    assert escolhido is not None
    assert escolhido.nome == aprovado.nome
    assert escolhido.categoria == CATEGORIA_CONVITE


def test_sem_o_template_da_categoria_aprovado_devolve_none() -> None:
    """Cenario 3: nenhum template aplicavel ao contexto -> None -> tarefa."""
    outra = next(t for t in TEMPLATES if t.categoria == CATEGORIA_QUEDA)
    # Ha um template aprovado, mas de OUTRA categoria: nao serve ao convite.
    assert escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset({outra.nome})) is None
    # Default do RT-03: nada aprovado -> nada aplicavel.
    assert escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset()) is None


def test_os_parametros_da_queda_trazem_os_dois_precos_por_reais_de() -> None:
    template = next(t for t in TEMPLATES if t.categoria == CATEGORIA_QUEDA)
    params = parametros_do_template(template=template, ficha=FICHA, queda=QUEDA)
    assert all(isinstance(p, str) for p in params)
    assert any("620.000" in p for p in params)  # preco antigo, reais_de(62_000_000)
    assert any("590.000" in p for p in params)  # preco novo, reais_de(59_000_000)


def test_os_parametros_do_imovel_novo_trazem_titulo_e_bairro() -> None:
    template = next(t for t in TEMPLATES if t.categoria == CATEGORIA_IMOVEL_NOVO)
    params = parametros_do_template(template=template, ficha=FICHA, queda=None)
    assert FICHA.titulo in params
    assert FICHA.bairro in params


def test_o_convite_nao_tem_parametros() -> None:
    template = next(t for t in TEMPLATES if t.categoria == CATEGORIA_CONVITE)
    assert parametros_do_template(template=template, ficha=None, queda=None) == []
