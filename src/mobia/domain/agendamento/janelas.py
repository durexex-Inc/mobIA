"""Ate 3 janelas de horario em que uma visita ou reuniao caberia. TEC-165, RN-11.1.

Puro: nao toca banco, rede nem relogio -- `agora` entra como parametro, como
em todo o dominio. **Nenhum codigo de producao chama este modulo ainda.** A
conversa so passa a oferecer horario quando houver como grava-lo (TEC-168) e
a quem atribui-lo (TEC-166); oferecer antes seria prometer o que o sistema
nao faz. Ver docs/superpowers/specs/2026-09-24-tec-165-propor-janelas-design.md.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from mobia.app.config import get_settings
from mobia.domain.corretores.models import Corretor
from mobia.domain.humano.deteccao import dentro_da_janela_de_atendimento


class TipoDeCompromisso(StrEnum):
    # Os mesmos nomes do campo `tipo` de `POST /api/v1/agendamentos` (SRS
    # 6.4): a TEC-168, que grava, nao precisa traduzir.
    VISITA_PRESENCIAL = "VISITA_PRESENCIAL"
    REUNIAO_REMOTA = "REUNIAO_REMOTA"


# RN-11.1. Regra do SRS e nao configuracao de implantacao -- o mesmo argumento
# da D4 da TEC-285 para os dias da janela de atendimento: um campo em
# `Settings` com um unico valor legal convida a ser mexido sem que a spec
# acompanhe.
ANTECEDENCIA_MINIMA = timedelta(hours=3)
DURACAO = {
    TipoDeCompromisso.VISITA_PRESENCIAL: timedelta(minutes=60),
    TipoDeCompromisso.REUNIAO_REMOTA: timedelta(minutes=30),
}
# Inicios em :00 e :30. Sem grade, `agora + 3h` produziria 17h07; com grade de
# uma hora, a reuniao de 30 minutos e a janela logo depois de um compromisso
# que termina as 10h30 nunca seriam oferecidas.
GRADE = timedelta(minutes=30)
MAXIMO_DE_JANELAS = 3


def _exigir_fuso(nome: str, momento: datetime) -> None:
    # Horario ingenuo e ambiguo exatamente no eixo que este modulo existe para
    # acertar -- mesma recusa de `dentro_da_janela_de_atendimento`.
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError(f"`{nome}` sem fuso: {momento!r}")


@dataclass(frozen=True)
class Intervalo:
    inicio: datetime
    fim: datetime

    def __post_init__(self) -> None:
        _exigir_fuso("inicio", self.inicio)
        _exigir_fuso("fim", self.fim)
        if not self.inicio < self.fim:
            raise ValueError(f"intervalo vazio ou invertido: {self.inicio} >= {self.fim}")

    def sobrepoe(self, outro: "Intervalo") -> bool:
        # Estrito: encostar nao e sobrepor. Um compromisso das 10h as 11h deixa
        # livre a janela das 11h as 12h.
        return self.inicio < outro.fim and outro.inicio < self.fim


def _primeiro_ponto_da_grade(momento: datetime, fuso: ZoneInfo) -> datetime:
    local = momento.astimezone(fuso)
    ponto = local.replace(minute=0, second=0, microsecond=0)
    while ponto < local:
        ponto += GRADE
    return ponto


def _cabe(
    janela: Intervalo,
    jornada_inicio: int,
    jornada_fim: int,
    ocupados: Sequence[Intervalo],
    fuso: ZoneInfo,
) -> bool:
    # A janela da imobiliaria vem inteira de `dentro_da_janela_de_atendimento`
    # -- dias, horas e borda inclusiva no minuto. Checar as duas pontas
    # garante que ambas caem dentro da grade de atendimento.
    if not (
        dentro_da_janela_de_atendimento(janela.inicio)
        and dentro_da_janela_de_atendimento(janela.fim)
    ):
        return False
    inicio, fim = janela.inicio.astimezone(fuso), janela.fim.astimezone(fuso)
    # A janela nunca deve atravessar a meia-noite -- se comeca num dia,
    # termina nele mesmo.
    if inicio.date() != fim.date():
        return False
    # A jornada do corretor e interseccionada com a da imobiliaria, e nao a
    # substitui: ela nao tem dia da semana (Emenda E-02 do modelo Corretor), e
    # os dias vem so da checagem acima.
    if inicio.hour * 60 + inicio.minute < jornada_inicio * 60:
        return False
    if fim.hour * 60 + fim.minute > jornada_fim * 60:
        return False
    return not any(janela.sobrepoe(ocupado) for ocupado in ocupados)


def _escolher(validas: list[Intervalo], fuso: ZoneInfo) -> list[Intervalo]:
    # A primeira de cada dia distinto, para dar escolha real de dia; se houver
    # menos dias que o maximo, completa com as proximas em ordem cronologica.
    escolhidas: list[Intervalo] = []
    dias: set[date] = set()
    for janela in validas:
        dia = janela.inicio.astimezone(fuso).date()
        if dia not in dias:
            dias.add(dia)
            escolhidas.append(janela)
    for janela in validas:
        if len(escolhidas) >= MAXIMO_DE_JANELAS:
            break
        if janela not in escolhidas:
            escolhidas.append(janela)
    return sorted(escolhidas[:MAXIMO_DE_JANELAS], key=lambda j: j.inicio)


def propor_janelas(
    *,
    agora: datetime,
    ate: datetime,
    jornada_inicio: int,
    jornada_fim: int,
    ocupados: Sequence[Intervalo],
    tipo: TipoDeCompromisso,
) -> list[Intervalo]:
    """Ate `MAXIMO_DE_JANELAS` janelas livres entre `agora + 3h` e `ate`.

    `jornada_inicio`/`jornada_fim` sao as horas inteiras de
    `Corretor.horario_inicio`/`horario_fim`. `ate` vem de quem chama: a TEC-169
    usa 72h para decidir a lista de espera (RN-11.5), e este modulo nao escolhe
    por ela.
    """
    _exigir_fuso("agora", agora)
    _exigir_fuso("ate", ate)
    fuso = get_settings().fuso_de_envio
    duracao = DURACAO[tipo]

    validas: list[Intervalo] = []
    dias: set[date] = set()
    inicio = _primeiro_ponto_da_grade(agora + ANTECEDENCIA_MINIMA, fuso)
    while inicio + duracao <= ate:
        janela = Intervalo(inicio, inicio + duracao)
        if _cabe(janela, jornada_inicio, jornada_fim, ocupados, fuso):
            validas.append(janela)
            dias.add(inicio.date())
            # Com o terceiro dia distinto achado, nada adiante muda a escolha:
            # a primeira de cada um dos tres ja esta em `validas`. Parar aqui e
            # o que deixa um horizonte de meses custar o mesmo que um de dias.
            if len(dias) >= MAXIMO_DE_JANELAS:
                break
        inicio += GRADE
    return _escolher(validas, fuso)


class AgendaDoCorretor(Protocol):
    """Os compromissos que ja ocupam o corretor, sobrepostos a [de, ate].

    Devolve cada intervalo que se sobrepoe com [de, ate], nao apenas os
    contidos nela -- um compromisso que comecou antes de `de` e termina
    depois ainda bloqueia. A implementacao real nasce com a tabela de
    agendamentos da TEC-168. Ate la o unico implementador e o fake dos testes.
    """

    async def ocupados(
        self, corretor_id: uuid.UUID, de: datetime, ate: datetime
    ) -> list[Intervalo]: ...


async def propor_janelas_do_corretor(
    *,
    corretor: Corretor,
    agenda: AgendaDoCorretor,
    agora: datetime,
    ate: datetime,
    tipo: TipoDeCompromisso,
) -> list[Intervalo]:
    """A costura entre a agenda e o motor, no lugar em que a TEC-168 a usara."""
    ocupados = await agenda.ocupados(corretor.id, agora, ate)
    return propor_janelas(
        agora=agora,
        ate=ate,
        jornada_inicio=corretor.horario_inicio,
        jornada_fim=corretor.horario_fim,
        ocupados=ocupados,
        tipo=tipo,
    )
