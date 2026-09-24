# TEC-165 — Motor de janelas — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um módulo de domínio puro, `domain/agendamento/janelas.py`, que devolve até 3 janelas de visita (60 min) ou reunião remota (30 min) para um corretor, mais a porta `AgendaDoCorretor` e a função fina que a usa.

**Architecture:** Função pura que varre inícios numa grade de 30 min a partir de `agora + 3h`, filtra pela janela da imobiliária (reaproveitando `dentro_da_janela_de_atendimento`), pela jornada do corretor e pelos intervalos ocupados, e escolhe a primeira de cada dia distinto, completando cronologicamente. Nada de produção a chama ainda.

**Tech Stack:** Python 3.13 stdlib (`datetime`, `zoneinfo`, `dataclasses`, `enum`, `typing.Protocol`), pytest com `asyncio_mode = "auto"`.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-165-propor-janelas-design.md`

## Global Constraints

- Comentários e docstrings em `src/` e `tests/`: português **sem** acento. Comentário diz o porquê, não o quê.
- Constantes da RN-11.1 em código, não em `Settings`: `ANTECEDENCIA_MINIMA = timedelta(hours=3)`, 60 min visita, 30 min reunião remota, `GRADE = timedelta(minutes=30)`, `MAXIMO_DE_JANELAS = 3`.
- Nomes do enum: `VISITA_PRESENCIAL`, `REUNIAO_REMOTA` (os do SRS 6.4).
- Janela da imobiliária só via `dentro_da_janela_de_atendimento` (`src/mobia/domain/humano/deteccao.py`) — não reescrever a regra de dia/hora. Fuso via `get_settings().fuso_de_envio` (propriedade, sem parênteses).
- Nenhuma tabela, migration, rota ou mudança em `turno.py`/`classificador.py`.
- Gates: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Nenhuma linha acrescentada a `.md` fora de `docs/superpowers/plans/` com `nome.py:` + dígito fora de bloco cercado (o `--checar` do CI reprova).
- Commit: `tipo(TEC-165): o que passou a ser verdade`, sem acento no assunto, trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Horizonte longo** (ex.: 30 dias) — a varredura para ao achar o 3º dia distinto; não deve varrer o horizonte inteiro à toa (coberto pelo desenho do laço; teste de horizonte de 60 dias abaixo).
2. **`agora` em outro fuso** (UTC) — o resultado tem de ser o mesmo que com `agora` em `America/Sao_Paulo` (teste abaixo).
3. **Jornada do corretor mais estreita que a grade** (ex.: 9h às 10h e reunião de 30 min) — cabem 9:00 e 9:30 (teste abaixo).
4. **Ocupado que atravessa a noite** (19h de um dia às 10h do outro) — bloqueia a manhã seguinte até 10h (teste abaixo).
5. **Jornada que não intersecta a da imobiliária** (ex.: 19h às 23h) — lista vazia, sem erro (teste abaixo).

---

### Task 1: O motor, a porta e os testes

**Files:**
- Create: `src/mobia/domain/agendamento/__init__.py` (vazio)
- Create: `src/mobia/domain/agendamento/janelas.py`
- Create: `tests/unit/test_janelas_de_agendamento.py`

**Interfaces:**
- Produces: `TipoDeCompromisso`, `Intervalo`, `propor_janelas(*, agora, ate, jornada_inicio, jornada_fim, ocupados, tipo) -> list[Intervalo]`, `AgendaDoCorretor`, `propor_janelas_do_corretor(*, corretor, agenda, agora, ate, tipo) -> list[Intervalo]`. A TEC-168/169/170 consomem estes nomes.

- [ ] **Step 1: Escrever os testes que falham**

`tests/unit/test_janelas_de_agendamento.py`:

```python
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
    """Corretor das 10h as 20h: a imobiliaria fecha as 19h."""
    janelas = _propor(_ago(26, 14), _ago(26, 23))
    so_quarta_tarde = _propor(_ago(26, 14), _ago(26, 23), jornada=(10, 20))
    assert so_quarta_tarde == janelas
    assert all(j.fim.astimezone(SP).hour <= 19 for j in so_quarta_tarde)


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


# --- a porta ---


class _AgendaFalsa:
    def __init__(self, ocupados: list[Intervalo]) -> None:
        self._ocupados = ocupados
        self.chamadas: list[tuple[uuid.UUID, datetime, datetime]] = []

    async def ocupados(self, corretor_id: uuid.UUID, de: datetime, ate: datetime) -> list[Intervalo]:
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_janelas_de_agendamento.py --tb=short -q`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'mobia.domain.agendamento'`.

- [ ] **Step 3: Implementar**

`src/mobia/domain/agendamento/__init__.py`: arquivo vazio.

`src/mobia/domain/agendamento/janelas.py`:

```python
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
    # -- dias, horas e borda inclusiva no minuto (19:00 cabe, 19:01 nao). Checar
    # as duas pontas e o bastante: a janela nunca atravessa a noite, porque o
    # fim as 19h ja recusa o que passaria dele.
    if not (
        dentro_da_janela_de_atendimento(janela.inicio)
        and dentro_da_janela_de_atendimento(janela.fim)
    ):
        return False
    # A jornada do corretor e interseccionada com a da imobiliaria, e nao a
    # substitui: ela nao tem dia da semana (Emenda E-02 do modelo Corretor), e
    # os dias vem so da checagem acima.
    inicio, fim = janela.inicio.astimezone(fuso), janela.fim.astimezone(fuso)
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
    """Os compromissos que ja ocupam o corretor entre `de` e `ate`.

    A implementacao real nasce com a tabela de agendamentos da TEC-168. Ate
    la o unico implementador e o fake dos testes.
    """

    async def ocupados(self, corretor_id: uuid.UUID, de: datetime, ate: datetime) -> list[Intervalo]: ...


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
```

Notas para quem implementa:
- `inicio` na varredura é hora local (`astimezone(fuso)`), então `inicio.date()` já é o dia local. Somar `GRADE` a um `datetime` com `ZoneInfo` é aritmética de relógio de parede; `America/Sao_Paulo` não tem horário de verão desde 2019, e isso basta para esta card.
- Se `ruff format` reformatar a assinatura longa de `AgendaDoCorretor.ocupados` ou dos testes, aceite o formato dele.
- Se algum teste esperado não bater, **não ajuste o teste para passar sem entender**: confira contra a regra do desenho (D2/D3) e relate a divergência.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_janelas_de_agendamento.py --tb=short -q`
Expected: todos passam.

- [ ] **Step 5: Gates, suíte unitária e commit**

Rode os três gates e `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q`. Depois:

```bash
git add src/mobia/domain/agendamento tests/unit/test_janelas_de_agendamento.py
git commit -m "feat(TEC-165): o motor propoe ate 3 janelas livres do corretor, uma por dia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
