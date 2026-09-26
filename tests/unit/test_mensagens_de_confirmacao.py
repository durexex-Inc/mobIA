"""Os textos da confirmacao de agendamento, testados. TEC-170, D3 e D4 do desenho.

Puro: o `Imovel` e transiente. 27/08/2026 e uma quinta-feira.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from mobia.domain.agendamento.mensagens import (
    aviso_ao_corretor,
    descrever_lead,
    endereco_de,
    texto_ao_lead,
)
from mobia.domain.catalogo.models import Imovel

SP = ZoneInfo("America/Sao_Paulo")
QUINTA_15H = datetime(2026, 8, 27, 15, 0, tzinfo=SP)


def test_descrever_lead_com_telefone() -> None:
    assert descrever_lead("whatsapp", "5511911111111") == "whatsapp +5511911111111"


def test_descrever_lead_sem_telefone() -> None:
    """Web sem vinculo, ou chave sem identidade -- as duas viram `None` em
    `telefones_de`, e o corretor nao pode ler a chave no lugar do numero."""
    assert descrever_lead("web", None) == "web (sem telefone informado)"


def _imovel() -> Imovel:
    return Imovel(
        id=uuid.uuid4(),
        codigo="AP-123",
        titulo="Apartamento 3 quartos",
        bairro="Moema",
        cidade="São Paulo",
        uf="SP",
    )


def test_endereco_usa_o_que_o_catalogo_tem() -> None:
    assert endereco_de(_imovel()) == "Apartamento 3 quartos (cód. AP-123) — Moema, São Paulo/SP"


def test_visita_com_imovel_leva_data_endereco_e_corretor() -> None:
    texto = texto_ao_lead(
        tipo="VISITA_PRESENCIAL", inicio=QUINTA_15H, corretor="Paula", imovel=_imovel()
    )
    assert "quinta-feira, 27 de agosto, às 15h" in texto
    assert "Moema, São Paulo/SP" in texto
    assert "Paula" in texto


def test_visita_sem_imovel_nao_tem_endereco_nem_none() -> None:
    texto = texto_ao_lead(
        tipo="VISITA_PRESENCIAL", inicio=QUINTA_15H, corretor="Paula", imovel=None
    )
    assert "quinta-feira, 27 de agosto, às 15h" in texto
    assert "Paula" in texto
    assert "None" not in texto
    assert "cód." not in texto


def test_reuniao_remota_diz_que_e_remota_e_nao_da_endereco() -> None:
    texto = texto_ao_lead(
        tipo="REUNIAO_REMOTA", inicio=QUINTA_15H, corretor="Paula", imovel=_imovel()
    )
    assert "remota" in texto
    assert "Moema" not in texto
    assert "Paula" in texto


def test_hora_vem_no_fuso_local_mesmo_com_inicio_em_utc() -> None:
    inicio_utc = QUINTA_15H.astimezone(ZoneInfo("UTC"))
    texto = texto_ao_lead(
        tipo="VISITA_PRESENCIAL", inicio=inicio_utc, corretor="Paula", imovel=None
    )
    assert "às 15h" in texto


def test_aviso_ao_corretor_leva_os_dados_mais_o_lead_e_o_link() -> None:
    aviso = aviso_ao_corretor(
        tipo="VISITA_PRESENCIAL",
        inicio=QUINTA_15H,
        corretor="Paula",
        imovel=_imovel(),
        lead="whatsapp +5511911111111",
        link="https://painel/conversas/whatsapp/5511911111111",
    )
    assert "quinta-feira, 27 de agosto, às 15h" in aviso.assunto
    for trecho in (
        "quinta-feira, 27 de agosto, às 15h",
        "Moema, São Paulo/SP",
        "Paula",
        "whatsapp +5511911111111",
        "https://painel/conversas/whatsapp/5511911111111",
    ):
        assert trecho in aviso.corpo
    assert aviso.etiqueta == "agendamento-confirmado"
    assert aviso.prioridade == "NORMAL"
    assert aviso.link == "https://painel/conversas/whatsapp/5511911111111"


def test_aviso_de_reuniao_remota_nao_tem_linha_de_imovel() -> None:
    aviso = aviso_ao_corretor(
        tipo="REUNIAO_REMOTA",
        inicio=QUINTA_15H,
        corretor="Paula",
        imovel=None,
        lead="web (sem telefone informado)",
        link="https://painel/x",
    )
    assert "Reunião remota" in aviso.assunto
    assert "Imóvel" not in aviso.corpo


def test_aviso_de_visita_sem_imovel_nao_tem_linha_de_imovel_nem_none() -> None:
    aviso = aviso_ao_corretor(
        tipo="VISITA_PRESENCIAL",
        inicio=QUINTA_15H,
        corretor="Paula",
        imovel=None,
        lead="whatsapp +5511911111111",
        link="https://painel/x",
    )
    assert "Visita" in aviso.assunto
    assert "Imóvel" not in aviso.corpo
    assert "None" not in aviso.corpo
    assert "quinta-feira, 27 de agosto, às 15h" in aviso.corpo
