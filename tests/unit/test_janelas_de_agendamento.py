"""O motor que propoe ate 3 janelas de horario, testado. TEC-165, RN-11.1.

Puro: `agora` e sempre um literal com fuso, e a janela da imobiliaria fica
nos valores padrao de `Settings` (segunda a sabado, 9h as 19h). 25/08/2026 e
uma terca-feira, a data que a card usa.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.janelas import (
    Intervalo,
    TipoDeCompromisso,
    propor_janelas,
    propor_janelas_do_corretor,
)
from mobia.domain.corretores.models import Corretor

SP = ZoneInfo("America/Sao_Paulo")


def _sp(mes: int, dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=SP)


def _ago(dia: int, hora: int, minuto: int = 0) -> datetime:
    return _sp(8, dia, hora, minuto)


def _propor(
    agora: datetime,
    ate: datetime,
    *,
    jornada: tuple[int, int] = (9, 19),
    ocupados: tuple[Intervalo, ...] = (),
    tipo: TipoDeCompromisso = TipoDeCompromisso.VISITA_PRESENCIAL,
) -> list[Intervalo]:
    return propor_janelas(
        agora=agora,
        ate=ate,
        jornada_inicio=jornada[0],
        jornada_fim=jornada[1],
        ocupados=list(ocupados),
        tipo=tipo,
    )


def _janela(inicio: datetime, minutos: int = 60) -> Intervalo:
    return Intervalo(inicio, inicio + timedelta(minutes=minutos))


# --- os cinco cenarios da card ---


def test_propoe_tres_janelas_livres_de_60_minutos() -> None:
    janelas = _propor(_ago(25, 14), _ago(29, 19))
    assert janelas == [_janela(_ago(25, 17)), _janela(_ago(26, 9)), _janela(_ago(27, 9))]
    assert all(j.fim - j.inicio == timedelta(minutes=60) for j in janelas)


def test_respeita_a_antecedencia_minima() -> None:
    janelas = _propor(_ago(25, 14), _ago(29, 19))
    mesmo_dia = [j for j in janelas if j.inicio.astimezone(SP).date() == _ago(25, 0).date()]
    assert mesmo_dia
    assert all(j.inicio >= _ago(25, 17) for j in mesmo_dia)


def test_nao_oferece_fora_da_janela_comercial() -> None:
    """Sabado ao meio-dia, horizonte que atravessa o domingo."""
    janelas = _propor(_ago(29, 12), _sp(9, 1, 19))
    assert janelas == [_janela(_ago(29, 15)), _janela(_ago(31, 9)), _janela(_sp(9, 1, 9))]
    for j in janelas:
        local_inicio, local_fim = j.inicio.astimezone(SP), j.fim.astimezone(SP)
        assert local_inicio.weekday() != 6
        assert (local_inicio.hour, local_inicio.minute) >= (9, 0)
        assert (local_fim.hour, local_fim.minute) <= (19, 0)


def test_compromisso_existente_bloqueia_a_janela() -> None:
    """Horizonte so na quinta: as tres saem dela, contornando 10h-11h."""
    ocupado = Intervalo(_ago(27, 10), _ago(27, 11))
    janelas = _propor(_ago(26, 20), _ago(27, 19), ocupados=(ocupado,))
    assert janelas == [_janela(_ago(27, 9)), _janela(_ago(27, 11)), _janela(_ago(27, 11, 30))]
    assert not any(j.sobrepoe(ocupado) for j in janelas)


def test_reuniao_remota_usa_30_minutos() -> None:
    janelas = _propor(_ago(25, 14), _ago(29, 19), tipo=TipoDeCompromisso.REUNIAO_REMOTA)
    assert janelas[0] == _janela(_ago(25, 17), 30)
    assert all(j.fim - j.inicio == timedelta(minutes=30) for j in janelas)


# --- bordas ---


def test_jornada_do_corretor_intersecta_a_da_imobiliaria_pela_manha() -> None:
    """Corretor das 8h as 12h: a imobiliaria so abre as 9h."""
    janelas = _propor(_ago(25, 20), _ago(29, 19), jornada=(8, 12))
    assert janelas == [_janela(_ago(26, 9)), _janela(_ago(27, 9)), _janela(_ago(28, 9))]


def test_jornada_do_corretor_intersecta_a_da_imobiliaria_a_noite() -> None:
    """A imobiliaria fecha as 19h: sem ela, 18h30-19h30 sairia tambem.

    Ocupacao 17h-17h30, broker 10h-20h, horizonte quarta. Candidatos validos
    sem fechar as 19h seriam 17h30-18h30, 18h-19h, 18h30-19h30, 19h-20h -- o
    preenchimento pega os tres primeiros. Com a regra de fechar as 19h,
    18h30-19h30 cai porque fim=19h30 fica fora das 9h-19h.
    """
    ocupado = Intervalo(_ago(26, 17), _ago(26, 17, 30))
    janelas = _propor(_ago(26, 14), _ago(26, 23), jornada=(10, 20), ocupados=(ocupado,))
    assert janelas == [_janela(_ago(26, 17, 30)), _janela(_ago(26, 18))]


def test_compromisso_que_encosta_nao_bloqueia() -> None:
    ocupado = Intervalo(_ago(27, 9), _ago(27, 11))
    janelas = _propor(_ago(26, 20), _ago(27, 19), ocupados=(ocupado,))
    assert janelas[0] == _janela(_ago(27, 11))


def test_visita_das_18h_cabe_e_a_das_18h30_nao() -> None:
    janelas = _propor(_ago(25, 15), _ago(25, 19, 30))
    assert janelas == [_janela(_ago(25, 18))]


def test_agora_depois_das_19h_empurra_para_o_dia_seguinte() -> None:
    janelas = _propor(_ago(25, 19, 30), _ago(29, 19))
    assert janelas[0] == _janela(_ago(26, 9))


def test_sabado_a_noite_pula_o_domingo() -> None:
    janelas = _propor(_ago(29, 18), _sp(9, 2, 19))
    assert janelas[0] == _janela(_ago(31, 9))


def test_agora_fora_da_grade_arredonda_para_cima() -> None:
    janelas = _propor(_ago(25, 13, 7), _ago(29, 19))
    assert janelas[0] == _janela(_ago(25, 16, 30))


def test_horizonte_sem_vaga_devolve_lista_vazia() -> None:
    assert _propor(_ago(25, 14), _ago(25, 16)) == []


def test_um_dia_so_com_vaga_completa_as_tres_com_ele() -> None:
    janelas = _propor(_ago(25, 14), _ago(25, 19))
    assert janelas == [_janela(_ago(25, 17)), _janela(_ago(25, 17, 30)), _janela(_ago(25, 18))]


def test_agora_em_utc_da_o_mesmo_resultado() -> None:
    em_sp = _propor(_ago(25, 14), _ago(29, 19))
    em_utc = _propor(_ago(25, 14).astimezone(UTC), _ago(29, 19).astimezone(UTC))
    assert em_utc == em_sp


def test_jornada_de_uma_hora_com_reuniao_de_30_minutos() -> None:
    janelas = _propor(
        _ago(25, 20), _ago(26, 19), jornada=(9, 10), tipo=TipoDeCompromisso.REUNIAO_REMOTA
    )
    assert janelas == [_janela(_ago(26, 9), 30), _janela(_ago(26, 9, 30), 30)]


def test_ocupado_que_atravessa_a_noite_bloqueia_a_manha_seguinte() -> None:
    ocupado = Intervalo(_ago(26, 19), _ago(27, 10))
    janelas = _propor(_ago(26, 14), _ago(27, 19), ocupados=(ocupado,))
    assert all(not j.sobrepoe(ocupado) for j in janelas)
    assert _janela(_ago(27, 10)) in janelas


def test_jornada_fora_da_janela_da_imobiliaria_devolve_vazio() -> None:
    assert _propor(_ago(25, 14), _ago(29, 19), jornada=(19, 23)) == []


def test_horizonte_longo_devolve_os_tres_primeiros_dias() -> None:
    janelas = _propor(_ago(25, 14), _ago(25, 14) + timedelta(days=60))
    assert janelas == [_janela(_ago(25, 17)), _janela(_ago(26, 9)), _janela(_ago(27, 9))]


def test_agora_sem_fuso_reprova() -> None:
    with pytest.raises(ValueError):
        _propor(datetime(2026, 8, 25, 14), _ago(29, 19))


def test_intervalo_sem_fuso_ou_invertido_reprova() -> None:
    with pytest.raises(ValueError):
        Intervalo(datetime(2026, 8, 25, 9), _ago(25, 10))
    with pytest.raises(ValueError):
        Intervalo(_ago(25, 10), _ago(25, 9))


def test_janela_que_atravessa_meia_noite_e_recusada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nenhuma janela deve sair do dia em que comecou, mesmo com Settings abertos.

    Simula uma imobiliaria aberta 0h-23h e um corretor 22h-23h: sem a verificacao
    de data, uma janela 23h-00h passaria todas as checagens. Deve ser recusada.
    """
    from mobia.app import config as config_mod

    monkeypatch.setattr(config_mod.get_settings(), "atendimento_horario_inicio", 0)
    monkeypatch.setattr(config_mod.get_settings(), "atendimento_horario_fim", 23)
    janelas = _propor(_ago(25, 20), _ago(26, 19), jornada=(22, 23))
    for j in janelas:
        local_inicio, local_fim = j.inicio.astimezone(SP), j.fim.astimezone(SP)
        assert local_inicio.date() == local_fim.date()


# --- a porta ---


class _AgendaFalsa:
    def __init__(self, ocupados: list[Intervalo]) -> None:
        self._ocupados = ocupados
        self.chamadas: list[tuple[uuid.UUID, datetime, datetime]] = []

    async def ocupados(
        self, corretor_id: uuid.UUID, de: datetime, ate: datetime
    ) -> list[Intervalo]:
        self.chamadas.append((corretor_id, de, ate))
        return self._ocupados


async def test_a_funcao_da_porta_usa_a_jornada_e_os_ocupados_do_corretor() -> None:
    corretor = Corretor(id=uuid.uuid4(), horario_inicio=10, horario_fim=19)
    agenda = _AgendaFalsa([Intervalo(_ago(26, 10), _ago(26, 12))])
    janelas = await propor_janelas_do_corretor(
        corretor=corretor,
        agenda=agenda,
        agora=_ago(25, 20),
        ate=_ago(29, 19),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    )
    assert agenda.chamadas == [(corretor.id, _ago(25, 20), _ago(29, 19))]
    assert janelas == [_janela(_ago(26, 12)), _janela(_ago(27, 10)), _janela(_ago(28, 10))]


# --- o `de` da TEC-167 ---


def test_de_posterior_a_antecedencia_comeca_a_busca_nele() -> None:
    janelas = propor_janelas(
        agora=_ago(25, 14),
        de=_ago(27, 9),
        ate=_ago(27, 12),
        jornada_inicio=9,
        jornada_fim=19,
        ocupados=[],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    )
    assert janelas == [_janela(_ago(27, 9)), _janela(_ago(27, 9, 30)), _janela(_ago(27, 10))]


def test_de_anterior_a_antecedencia_nao_fura_as_3_horas() -> None:
    janelas = propor_janelas(
        agora=_ago(25, 14),
        de=_ago(25, 9),
        ate=_ago(25, 19),
        jornada_inicio=9,
        jornada_fim=19,
        ocupados=[],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    )
    assert janelas[0] == _janela(_ago(25, 17))


def test_de_sem_fuso_reprova() -> None:
    with pytest.raises(ValueError):
        propor_janelas(
            agora=_ago(25, 14),
            de=datetime(2026, 8, 27, 9),
            ate=_ago(27, 12),
            jornada_inicio=9,
            jornada_fim=19,
            ocupados=[],
            tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        )
