"""A regua dos dois lembretes, os seis textos e o kind. TEC-171, RN-12.2.

Puro: nada aqui toca banco nem rede. Quem consulta e entrega e
`workers/jobs/sweep_lembretes.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.lembretes import (
    LEMBRETE_DE_2H,
    LEMBRETE_DE_24H,
    LEMBRETES,
    TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL,
    TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL,
    escolher_template_do_lembrete,
    kind_do_lembrete,
    lembrete_devido,
    parametros_do_template_do_lembrete,
    texto_do_lembrete,
)
from mobia.domain.catalogo.models import Imovel

INICIO = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)
AGENDAMENTO = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
# Difere do primeiro ja no comeco do hex, e nao no fim: o kind usa so os VINTE
# primeiros caracteres (`kind_do_lembrete`), entao dois ids que so divergem
# depois disso produzem o mesmo kind. E a colisao que a TEC-170 aceitou ao
# truncar -- oitenta bits de um uuid4 --, nao um defeito; um fixture que
# divergisse so no ultimo digito estaria testando a truncagem, e nao o kind.
OUTRO = uuid.UUID("a1b2c3d4-4f89-11d3-9a0c-0305e82c3301")


def _imovel() -> Imovel:
    return Imovel(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        codigo="A-120",
        titulo="Apartamento na Lagoa da Conceição",
        bairro="Lagoa da Conceição",
        cidade="Florianópolis",
        uf="SC",
    )


# ---------------------------------------------------------------- a regua


def test_o_lembrete_e_devido_no_piso_da_faixa() -> None:
    """CA-12.1: "quando o relogio chega a 24 h antes, o lembrete e enviado"."""
    assert (
        lembrete_devido(
            LEMBRETE_DE_24H,
            inicio=INICIO,
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO - timedelta(hours=24),
        )
        is True
    )


def test_o_lembrete_e_devido_no_meio_da_faixa() -> None:
    """A passagem do cron cai a cada 5 minutos, nunca no instante exato."""
    assert (
        lembrete_devido(
            LEMBRETE_DE_24H,
            inicio=INICIO,
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO - timedelta(hours=12),
        )
        is True
    )


def test_o_lembrete_de_24h_nao_e_devido_depois_do_marco_do_de_2h() -> None:
    """O teto da faixa, e a razao dele.

    Sem teto, um worker parado tres horas mandaria o lembrete de 24 horas
    JUNTO com o de 2 horas -- e perguntar "voce consegue ir?" noventa minutos
    antes da visita e outra mensagem, nao a mesma atrasada.
    """
    assert (
        lembrete_devido(
            LEMBRETE_DE_24H,
            inicio=INICIO,
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO - timedelta(minutes=90),
        )
        is False
    )


def test_o_lembrete_de_2h_nao_e_devido_depois_do_inicio() -> None:
    assert (
        lembrete_devido(
            LEMBRETE_DE_2H,
            inicio=INICIO,
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO + timedelta(minutes=1),
        )
        is False
    )


def test_o_lembrete_de_2h_e_devido_na_propria_faixa() -> None:
    assert (
        lembrete_devido(
            LEMBRETE_DE_2H,
            inicio=INICIO,
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO - timedelta(hours=2),
        )
        is True
    )


def test_o_lembrete_cujo_momento_ja_passara_na_confirmacao_nunca_existiu() -> None:
    """Agendamento confirmado tres horas antes da visita nao tem lembrete de 24h.

    Sem esta condicao ele receberia a confirmacao da TEC-170 e, minutos
    depois, um "lembrete de 24 horas" -- repetindo a mesma data, a mesma hora
    e o mesmo endereco que a confirmacao acabou de levar.
    """
    confirmado = INICIO - timedelta(hours=3)
    assert (
        lembrete_devido(LEMBRETE_DE_24H, inicio=INICIO, confirmado_em=confirmado, agora=confirmado)
        is False
    )
    # E o de 2 horas continua valendo para o mesmo agendamento: o momento dele
    # ainda estava no futuro quando a confirmacao aconteceu.
    assert (
        lembrete_devido(
            LEMBRETE_DE_2H,
            inicio=INICIO,
            confirmado_em=confirmado,
            agora=INICIO - timedelta(hours=2),
        )
        is True
    )


def test_agendamento_sem_confirmado_em_nao_recebe_lembrete() -> None:
    """`confirmado_em` e nulavel na tabela, e nulo nao autoriza envio.

    Um agendamento CONFIRMADO sem carimbo de confirmacao seria um estado que
    `confirmar` nao produz; tratar o nulo como "confirmado ha muito tempo"
    mandaria mensagem por causa de uma linha adulterada a mao.
    """
    for lembrete in LEMBRETES:
        assert (
            lembrete_devido(
                lembrete,
                inicio=INICIO,
                confirmado_em=None,
                agora=INICIO - timedelta(hours=24),
            )
            is False
        )


def test_a_regua_exige_datetime_com_fuso() -> None:
    with pytest.raises(ValueError, match="sem tzinfo"):
        lembrete_devido(
            LEMBRETE_DE_24H,
            inicio=INICIO.replace(tzinfo=None),
            confirmado_em=INICIO - timedelta(hours=26),
            agora=INICIO - timedelta(hours=24),
        )


# ----------------------------------------------------------------- o kind


def test_o_kind_cabe_nos_trinta_e_dois_caracteres_da_coluna() -> None:
    for lembrete in LEMBRETES:
        assert len(kind_do_lembrete(lembrete, AGENDAMENTO)) == 32


def test_o_kind_e_estavel_para_o_mesmo_agendamento_e_muda_entre_lembretes() -> None:
    assert kind_do_lembrete(LEMBRETE_DE_24H, AGENDAMENTO) == kind_do_lembrete(
        LEMBRETE_DE_24H, AGENDAMENTO
    )
    assert kind_do_lembrete(LEMBRETE_DE_24H, AGENDAMENTO) != kind_do_lembrete(
        LEMBRETE_DE_2H, AGENDAMENTO
    )


def test_dois_agendamentos_tem_kinds_diferentes_no_mesmo_lembrete() -> None:
    """A ancora e a ultima mensagem DO LEAD, e dois agendamentos caem nela.

    A reserva de `outbound_dispatches` e UNIQUE (message_id, kind): com um
    kind fixo por lembrete, o segundo agendamento do mesmo lead teria o
    lembrete suprimido como reentrega. Mesmo raciocinio de
    `kind_da_confirmacao` (TEC-170).
    """
    assert kind_do_lembrete(LEMBRETE_DE_24H, AGENDAMENTO) != kind_do_lembrete(
        LEMBRETE_DE_24H, OUTRO
    )


# ---------------------------------------------------------------- o texto


def test_o_lembrete_de_24h_de_visita_leva_data_endereco_e_corretor() -> None:
    texto = texto_do_lembrete(
        LEMBRETE_DE_24H,
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        inicio=INICIO,
        corretor="Ana",
        imovel=_imovel(),
    )
    assert "sábado, 26 de setembro" in texto
    assert "A-120" in texto
    assert "Ana" in texto


def test_o_lembrete_de_24h_oferece_confirmar_remarcar_e_cancelar() -> None:
    """RN-12.2: o de 24 h pede confirmacao de presenca ("sim/remarcar/cancelar").

    Nada le a resposta ainda -- `domain/agente/turno.py` nao importa nada de
    `domain/agendamento/`. O texto CONVIDA a responder e nao promete que
    alguem remarca ou cancela, que e a licao da TEC-174.
    """
    for texto in (
        TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA,
        TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL,
        TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO,
    ):
        assert "remarcar" in texto
        assert "cancelar" in texto


def test_o_lembrete_de_2h_nao_pergunta_nada() -> None:
    """Faltando duas horas, o que serve e a hora e o endereco."""
    for texto in (
        TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA,
        TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL,
        TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO,
    ):
        assert "?" not in texto
        assert "remarcar" not in texto


def test_visita_sem_imovel_nao_inventa_endereco() -> None:
    """O schema permite `imovel_id` nulo, e endereco inventado e pior que nenhum."""
    texto = texto_do_lembrete(
        LEMBRETE_DE_24H,
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        inicio=INICIO,
        corretor="Ana",
        imovel=None,
    )
    assert "None" not in texto
    assert "A-120" not in texto
    assert "Ana" in texto


def test_reuniao_remota_diz_que_e_remota_e_nao_da_endereco() -> None:
    texto = texto_do_lembrete(
        LEMBRETE_DE_2H,
        tipo=TipoDeCompromisso.REUNIAO_REMOTA,
        inicio=INICIO,
        corretor="Ana",
        imovel=_imovel(),
    )
    assert "remota" in texto
    assert "A-120" not in texto


def test_a_hora_vem_no_fuso_local_mesmo_com_inicio_em_utc() -> None:
    """18h UTC sao 15h em Sao Paulo, e e a hora local que o lead le."""
    texto = texto_do_lembrete(
        LEMBRETE_DE_2H,
        tipo=TipoDeCompromisso.REUNIAO_REMOTA,
        inicio=INICIO,
        corretor="Ana",
        imovel=None,
    )
    assert "15h" in texto


# -------------------------------------------------------------- o template


def test_sem_template_aprovado_nao_ha_template() -> None:
    """O default do RT-03: `WHATSAPP_TEMPLATES_APROVADOS` vazio.

    Fora da janela de 24h isso significa que o lembrete nao sai -- declarado
    na D4 do desenho, e a lacuna maior desta card.
    """
    for lembrete in LEMBRETES:
        assert escolher_template_do_lembrete(lembrete, aprovados=frozenset()) is None


def test_com_o_template_aprovado_cada_lembrete_escolhe_o_proprio() -> None:
    aprovados = frozenset({lembrete.template for lembrete in LEMBRETES})
    escolhidos = {
        lembrete.chave: escolher_template_do_lembrete(lembrete, aprovados=aprovados)
        for lembrete in LEMBRETES
    }
    assert escolhidos[LEMBRETE_DE_24H.chave] == LEMBRETE_DE_24H.template
    assert escolhidos[LEMBRETE_DE_2H.chave] == LEMBRETE_DE_2H.template
    assert LEMBRETE_DE_24H.template != LEMBRETE_DE_2H.template


def test_o_template_de_um_lembrete_nao_serve_ao_outro() -> None:
    aprovados = frozenset({LEMBRETE_DE_24H.template})
    assert escolher_template_do_lembrete(LEMBRETE_DE_24H, aprovados=aprovados) is not None
    assert escolher_template_do_lembrete(LEMBRETE_DE_2H, aprovados=aprovados) is None


def test_os_parametros_do_template_sao_os_mesmos_dados_do_texto_livre() -> None:
    """Quando, onde e quem -- os tres que o texto livre leva.

    O template e a mesma mensagem dita sob a restricao da Meta, e nao outra:
    dado que o texto livre nao leva faria o lead receber duas mensagens
    diferentes conforme a janela.
    """
    parametros = parametros_do_template_do_lembrete(
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        inicio=INICIO,
        corretor="Ana",
        imovel=_imovel(),
    )
    quando, endereco, corretor = parametros
    assert "sábado, 26 de setembro" in quando
    assert "A-120" in endereco
    assert corretor == "Ana"


def test_sem_endereco_a_posicao_dele_vai_vazia_e_nao_some() -> None:
    """A Meta casa parametro por POSICAO.

    Encurtar a lista deslocaria o nome do corretor para o buraco do endereco,
    e o lead leria "Ana" onde deveria ler o endereco.
    """
    for tipo, imovel in (
        (TipoDeCompromisso.REUNIAO_REMOTA, _imovel()),
        (TipoDeCompromisso.VISITA_PRESENCIAL, None),
    ):
        parametros = parametros_do_template_do_lembrete(
            tipo=tipo, inicio=INICIO, corretor="Ana", imovel=imovel
        )
        assert len(parametros) == 3
        assert parametros[1] == ""
        assert parametros[2] == "Ana"
