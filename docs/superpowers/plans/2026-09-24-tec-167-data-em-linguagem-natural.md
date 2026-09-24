# TEC-167 — Data em linguagem natural — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver data falada ("quinta de manhã", "amanhã às 15h") para instante/período/dia/semana no fuso de São Paulo, ou para uma pergunta quando ambígua; transformar a resolução em janelas pelo motor da TEC-165; e formatar a data e a hora absolutas da confirmação.

**Architecture:** Módulo puro novo `domain/agendamento/data_falada.py` com gramática por regras (molde de `domain/agente/dinheiro.py`), que nunca levanta para texto do lead. O motor `propor_janelas` ganha `de` opcional. Uma ponte `janelas_para` liga os dois. Nada de produção chama nada disto ainda.

**Tech Stack:** Python 3.13 stdlib (`re`, `datetime`, `zoneinfo`, `dataclasses`, `enum`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-167-data-em-linguagem-natural-design.md`

## Global Constraints

- Comentários e docstrings em `src/` e `tests/`: português **sem** acento. Os literais `TEXTO_...` e os nomes de dia/mês que chegam ao lead: português **com** acento (TEC-267).
- `resolver` nunca levanta para texto do lead; só `agora` sem fuso levanta `ValueError`.
- Fuso sempre via `get_settings().fuso_de_envio` (propriedade, sem parênteses).
- Períodos: manhã 9h–12h, tarde 12h–19h.
- Nenhuma mudança em `turno.py`, `classificador.py`, tabela, migration ou rota.
- Gates: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Nenhuma linha acrescentada a `.md` fora de `docs/superpowers/plans/` com `nome.py:` + dígito fora de bloco cercado.
- Commit: `tipo(TEC-167): o que passou a ser verdade`, sem acento no assunto, trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Texto enorme ou lixo** (linha digitável de boleto, 10 mil caracteres) — sem exceção e sem regex catastrófica (teste na Task 2).
2. **"hoje" dito no fim do dia** ("hoje de tarde" às 19h30) — período já passou → pergunta (teste na Task 2).
3. **"amanhã" dito num sábado** — cai no domingo → pergunta do domingo, não `Dia` (teste na Task 2).
4. **Hora com minuto inválido** ("15h75") — ignora a hora, não levanta (teste na Task 2).
5. **`Instante` fora da grade** ("quinta às 15h10") — a ponte cai nas janelas do dia, não devolve lista vazia (teste na Task 3).

---

### Task 1: `de` opcional no motor

**Files:**
- Modify: `src/mobia/domain/agendamento/janelas.py` (`propor_janelas`)
- Test: `tests/unit/test_janelas_de_agendamento.py`

**Interfaces:**
- Produces: `propor_janelas(*, agora, ate, jornada_inicio, jornada_fim, ocupados, tipo, de: datetime | None = None)`. Task 3 usa `de`.

- [ ] **Step 1: Testes que falham** — acrescente ao fim de `tests/unit/test_janelas_de_agendamento.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_janelas_de_agendamento.py --tb=short -q` → `TypeError: propor_janelas() got an unexpected keyword argument 'de'`.

- [ ] **Step 3: Implementar** — em `propor_janelas`, acrescente o parâmetro por último, `de: datetime | None = None`, e troque o cálculo do primeiro início:

```python
    _exigir_fuso("agora", agora)
    _exigir_fuso("ate", ate)
    if de is not None:
        _exigir_fuso("de", de)
    fuso = get_settings().fuso_de_envio
    duracao = DURACAO[tipo]

    # `de` so adia o inicio da busca: nunca o antecipa para antes das 3 horas
    # de antecedencia. E o que deixa a TEC-167 buscar "a manha de quinta" sem
    # que "hoje de manha", dito as 14h, ofereca horario em cima da hora.
    comeco = agora + ANTECEDENCIA_MINIMA
    if de is not None and de > comeco:
        comeco = de
    ...
    inicio = _primeiro_ponto_da_grade(comeco, fuso)
```

Atualize a docstring: a busca vai de `max(agora + 3h, de)` a `ate`, e `de` é da TEC-167.

- [ ] **Step 4: Rodar e ver passar** — o arquivo inteiro (os 23 antigos + 3 novos).

- [ ] **Step 5: Gates e commit**

```bash
git add src/mobia/domain/agendamento/janelas.py tests/unit/test_janelas_de_agendamento.py
git commit -m "feat(TEC-167): o motor aceita um inicio de busca, sem furar as 3 horas de antecedencia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: O interpretador, as perguntas e a data absoluta

**Files:**
- Create: `src/mobia/domain/agendamento/data_falada.py`
- Create: `tests/unit/test_data_falada.py`
- Modify: `tests/unit/literais_ao_lead.py` (importar e listar as 8 perguntas)
- Modify: `tests/unit/test_literais_ao_lead.py` (o tamanho da lista vai de 20 para 28)

**Interfaces:**
- Produces: `PeriodoDoDia` (`MANHA`, `TARDE`), `LIMITES_DO_PERIODO: dict[PeriodoDoDia, tuple[int, int]]`, `Instante(momento)`, `Periodo(dia, periodo)`, `Dia(dia)`, `Semana(segunda)`, `Ambigua(pergunta)`, `NaoReconhecida()`, `Resolucao` (união dos seis), `resolver(texto, *, agora) -> Resolucao`, `data_absoluta(dia) -> str`, `data_e_hora_absolutas(momento) -> str`, e as constantes `TEXTO_DO_FIM_DE_SEMANA`, `TEXTO_DO_DOMINGO`, `TEXTO_DE_HOJE_OU_DA_PROXIMA`, `TEXTO_DA_HORA_AMBIGUA`, `TEXTO_DO_PASSADO`, `TEXTO_DE_DOIS_DIAS`, `TEXTO_DA_NOITE`, `TEXTO_DA_DATA_INEXISTENTE`. Task 3 consome as seis formas, `LIMITES_DO_PERIODO` e `resolver`.

- [ ] **Step 1: Testes que falham** — `tests/unit/test_data_falada.py`:

```python
"""A data falada pelo lead, resolvida. TEC-167, RN-11.3.

Puro: `agora` e sempre um literal com fuso. O `agora` padrao e o da card:
terca-feira, 25/08/2026, 14h.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.data_falada import (
    TEXTO_DA_DATA_INEXISTENTE,
    TEXTO_DA_NOITE,
    TEXTO_DO_DOMINGO,
    TEXTO_DO_PASSADO,
    Ambigua,
    Dia,
    Instante,
    NaoReconhecida,
    Periodo,
    PeriodoDoDia,
    Semana,
    data_absoluta,
    data_e_hora_absolutas,
    resolver,
)

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 25, 14, 0, tzinfo=SP)


def _ago(dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=SP)


def _set(dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(2026, 9, dia, hora, minuto, tzinfo=SP)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # a tabela da card
        ("amanhã de tarde", Periodo(date(2026, 8, 26), PeriodoDoDia.TARDE)),
        ("quinta às 15h", Instante(_ago(27, 15))),
        ("semana que vem", Semana(date(2026, 8, 31))),
        # o primeiro cenario da card
        ("pode ser quinta de manhã", Periodo(date(2026, 8, 27), PeriodoDoDia.MANHA)),
        # dias
        ("próxima semana", Semana(date(2026, 8, 31))),
        ("quinta", Dia(date(2026, 8, 27))),
        ("quinta-feira", Dia(date(2026, 8, 27))),
        ("sexta que vem", Dia(date(2026, 8, 28))),
        ("próxima sexta", Dia(date(2026, 8, 28))),
        ("sábado", Dia(date(2026, 8, 29))),
        ("segunda", Dia(date(2026, 8, 31))),
        ("amanhã", Dia(date(2026, 8, 26))),
        ("depois de amanhã", Dia(date(2026, 8, 27))),
        ("dia 3", Dia(date(2026, 9, 3))),
        ("dia 25", Dia(date(2026, 9, 25))),
        ("dia 20", Dia(date(2026, 9, 20))),
        ("3/9", Dia(date(2026, 9, 3))),
        ("03/09", Dia(date(2026, 9, 3))),
        ("quinta da semana que vem", Dia(date(2026, 9, 3))),
        # periodos e horas
        ("hoje de tarde", Periodo(date(2026, 8, 25), PeriodoDoDia.TARDE)),
        ("hoje às 16h30", Instante(_ago(25, 16, 30))),
        ("amanhã 10h", Instante(_ago(26, 10))),
        ("amanha as 15:30", Instante(_ago(26, 15, 30))),
        ("quinta 3 da tarde", Instante(_ago(27, 15))),
        ("sexta 10 da manhã", Instante(_ago(28, 10))),
        ("às 16h", Instante(_ago(25, 16))),
        ("AMANHÃ DE TARDE", Periodo(date(2026, 8, 26), PeriodoDoDia.TARDE)),
    ],
)
def test_resolve_expressoes_comuns(texto: str, esperado: object) -> None:
    assert resolver(texto, agora=AGORA) == esperado


def test_amanha_numa_sexta_e_o_sabado() -> None:
    sexta = _ago(28, 14)
    assert resolver("amanhã", agora=sexta) == Dia(date(2026, 8, 29))


# --- o que pergunta ---


def _pergunta(texto: str, agora: datetime = AGORA) -> str:
    resolucao = resolver(texto, agora=agora)
    assert isinstance(resolucao, Ambigua), resolucao
    return resolucao.pergunta


def test_fim_de_semana_pergunta_pelo_sabado() -> None:
    pergunta = _pergunta("no fim de semana")
    assert "sábado, 29 de agosto" in pergunta
    assert "domingo" in pergunta.lower()


def test_domingo_pergunta_outro_dia() -> None:
    assert _pergunta("domingo") == TEXTO_DO_DOMINGO


def test_amanha_num_sabado_cai_no_domingo_e_pergunta() -> None:
    assert _pergunta("amanhã", agora=_ago(29, 14)) == TEXTO_DO_DOMINGO


def test_o_dia_da_semana_de_hoje_pergunta_qual() -> None:
    pergunta = _pergunta("terça")
    assert "25 de agosto" in pergunta
    assert "1º de setembro" in pergunta


def test_hora_de_1_a_7_sem_periodo_pergunta() -> None:
    assert "15h" in _pergunta("quinta às 3")


def test_passado_pergunta() -> None:
    assert _pergunta("hoje às 10h") == TEXTO_DO_PASSADO
    assert _pergunta("3/8") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de manhã") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de tarde", agora=_ago(25, 19, 30)) == TEXTO_DO_PASSADO


def test_dois_dias_pergunta_qual() -> None:
    pergunta = _pergunta("quinta ou sexta")
    assert "27 de agosto" in pergunta
    assert "28 de agosto" in pergunta


def test_noite_pergunta_pelo_fim_da_tarde() -> None:
    assert _pergunta("quinta à noite") == TEXTO_DA_NOITE


def test_data_inexistente_pergunta() -> None:
    assert _pergunta("31/9") == TEXTO_DA_DATA_INEXISTENTE
    assert _pergunta("dia 31", agora=_set(5, 14)) == TEXTO_DA_DATA_INEXISTENTE


# --- o que nao reconhece, e o que nao pode derrubar ---


def test_texto_sem_data_nao_e_reconhecido() -> None:
    assert resolver("tanto faz", agora=AGORA) == NaoReconhecida()
    assert resolver("", agora=AGORA) == NaoReconhecida()


@pytest.mark.parametrize(
    "texto",
    [
        "9" * 10_000,
        "23793.38128 60000.000003 00000.000400 1 84340000012345",
        "15h75",
        "quinta às 99h",
        "33/13",
        "dia 0",
    ],
)
def test_lixo_nao_levanta(texto: str) -> None:
    resolver(texto, agora=AGORA)


def test_hora_com_minuto_invalido_e_ignorada() -> None:
    assert resolver("quinta 15h75", agora=AGORA) == Dia(date(2026, 8, 27))


def test_agora_sem_fuso_reprova() -> None:
    with pytest.raises(ValueError):
        resolver("amanhã", agora=datetime(2026, 8, 25, 14))


# --- a data absoluta ---


def test_data_e_hora_absolutas() -> None:
    assert data_e_hora_absolutas(_ago(27, 15)) == "quinta-feira, 27 de agosto, às 15h"
    assert data_e_hora_absolutas(_ago(27, 15, 30)) == "quinta-feira, 27 de agosto, às 15h30"


def test_data_e_hora_absolutas_converte_para_sao_paulo() -> None:
    em_utc = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
    assert data_e_hora_absolutas(em_utc) == "quinta-feira, 27 de agosto, às 15h"


def test_data_absoluta_usa_ordinal_no_dia_primeiro() -> None:
    assert data_absoluta(date(2026, 9, 1)) == "terça-feira, 1º de setembro"
    assert data_absoluta(date(2026, 8, 29)) == "sábado, 29 de agosto"
```

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_data_falada.py --tb=short -q` → `ModuleNotFoundError: No module named 'mobia.domain.agendamento.data_falada'`.

- [ ] **Step 3: Implementar** — `src/mobia/domain/agendamento/data_falada.py`:

```python
"""A data que o lead fala, resolvida para o calendario. TEC-167, RN-11.3.

Puro de proposito, no molde de `domain/agente/dinheiro.py`: sem I/O, sem
banco, sem chamada ao modelo, e `agora` entra como parametro. A gramatica e
lista fixa e erra por falta -- e a falta vira pergunta, nunca chute, porque
chute aqui e visita no dia errado (RT-10). Estende-la e decisao de card.

**`resolver` nao levanta para texto do lead.** Qualquer sequencia de
caracteres e entrada valida, e uma excecao aqui derrubaria o turno inteiro --
o argumento e o mesmo da docstring de `dinheiro.py`. So `agora` sem fuso
levanta: e erro de programacao, nao de fala.

Nenhum codigo de producao chama este modulo ainda: ver o desenho,
docs/superpowers/specs/2026-09-24-tec-167-data-em-linguagem-natural-design.md.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from mobia.app.config import get_settings
from mobia.domain.texto import dobrar


class PeriodoDoDia(StrEnum):
    MANHA = "MANHA"
    TARDE = "TARDE"


# A tarde termina onde o atendimento termina (`atendimento_horario_fim`), e
# nao as 18h: um periodo que prometesse ate as 18h esconderia a ultima hora
# em que ainda ha corretor.
LIMITES_DO_PERIODO: dict[PeriodoDoDia, tuple[int, int]] = {
    PeriodoDoDia.MANHA: (9, 12),
    PeriodoDoDia.TARDE: (12, 19),
}


@dataclass(frozen=True)
class Instante:
    momento: datetime


@dataclass(frozen=True)
class Periodo:
    dia: date
    periodo: PeriodoDoDia


@dataclass(frozen=True)
class Dia:
    dia: date


@dataclass(frozen=True)
class Semana:
    segunda: date


@dataclass(frozen=True)
class Ambigua:
    # Texto pronto para o lead: uma das constantes `TEXTO_...` abaixo, ja com
    # as datas preenchidas.
    pergunta: str


@dataclass(frozen=True)
class NaoReconhecida:
    pass


Resolucao = Instante | Periodo | Dia | Semana | Ambigua | NaoReconhecida

# O texto que o lead le: portugues com acento (TEC-267). Registrados em
# `tests/unit/literais_ao_lead.py`, para as guardas de acento e de promessa.
TEXTO_DO_FIM_DE_SEMANA = "Aos domingos não há atendimento. Pode ser no {sabado}?"
TEXTO_DO_DOMINGO = "Aos domingos não há atendimento. Que outro dia fica bom para você?"
TEXTO_DE_HOJE_OU_DA_PROXIMA = "Você quer dizer hoje, {hoje}, ou a próxima, {proxima}?"
TEXTO_DA_HORA_AMBIGUA = "Você quer dizer às {hora}h?"
TEXTO_DO_PASSADO = "Esse horário já passou. Que outro dia e horário ficam bons para você?"
TEXTO_DE_DOIS_DIAS = "Qual dos dois fica melhor para você: {primeiro} ou {segundo}?"
TEXTO_DA_NOITE = "O atendimento vai até as 19h. Pode ser no fim da tarde?"
TEXTO_DA_DATA_INEXISTENTE = (
    "Não encontrei essa data no calendário. Que outro dia fica bom para você?"
)

DIAS_DA_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_DOMINGO = 6

# Teto do texto examinado. A fala do lead e curta; o teto existe para que uma
# colagem de 10 mil caracteres custe o mesmo que uma frase.
_TAMANHO_MAXIMO = 300

# Sobre o texto ja dobrado (sem acento, caixa dobrada). `\b` em toda palavra:
# sem ele "amanha" conteria "manha" e todo "amanha" viraria periodo da manha.
_FIM_DE_SEMANA = re.compile(r"\b(?:fim|final) de semana\b")
_SEMANA_QUE_VEM = re.compile(r"\b(?:semana que vem|proxima semana)\b")
_DEPOIS_DE_AMANHA = re.compile(r"\bdepois de amanha\b")
_AMANHA = re.compile(r"\bamanha\b")
_HOJE = re.compile(r"\bhoje\b")
_DIA_DA_SEMANA = re.compile(
    r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:[- ]feira)?\b"
)
_DIA_E_MES = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_DIA_DO_MES = re.compile(r"\bdia (\d{1,2})\b")
_NOITE = re.compile(r"\bnoite\b")
_MANHA = re.compile(r"\bmanha\b")
_TARDE = re.compile(r"\btarde\b")
_HORA_E_MINUTO = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")
_HORA_COM_PERIODO = re.compile(r"\b(\d{1,2}) da (manha|tarde)\b")
_HORA_COM_H = re.compile(r"\b(\d{1,2}) ?h\b")
_HORA_APOS_AS = re.compile(r"\bas (\d{1,2})\b")

_NOMES = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")


def data_absoluta(dia: date) -> str:
    """ "quinta-feira, 27 de agosto" -- o ordinal no dia primeiro ("1º")."""
    numero = "1º" if dia.day == 1 else str(dia.day)
    return f"{DIAS_DA_SEMANA[dia.weekday()]}, {numero} de {MESES[dia.month - 1]}"


def data_e_hora_absolutas(momento: datetime) -> str:
    """ "quinta-feira, 27 de agosto, as 15h" -- sempre no fuso de Sao Paulo.

    As tres coisas que a RN-11.3 exige na confirmacao: dia da semana, dia do
    mes e horario. Qualquer que seja o fuso de `momento`, o que o lead le e a
    hora local dele.
    """
    local = momento.astimezone(get_settings().fuso_de_envio)
    hora = f"{local.hour}h" if local.minute == 0 else f"{local.hour}h{local.minute:02d}"
    return f"{data_absoluta(local.date())}, às {hora}"


def _apagar(texto: str, casa: re.Match[str]) -> str:
    # Troca o trecho casado por espacos do mesmo tamanho: as posicoes dos
    # outros achados continuam valendo, e "3/9" nao sobra para virar hora.
    return texto[: casa.start()] + " " * (casa.end() - casa.start()) + texto[casa.end() :]


def _data(ano: int, mes: int, dia: int) -> date | None:
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def resolver(texto: str, *, agora: datetime) -> Resolucao:
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ValueError(f"`agora` sem fuso: {agora!r}")
    fuso = get_settings().fuso_de_envio
    local = agora.astimezone(fuso)
    hoje = local.date()
    falado = dobrar(texto)[:_TAMANHO_MAXIMO]

    if _FIM_DE_SEMANA.search(falado):
        sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7)
        return Ambigua(TEXTO_DO_FIM_DE_SEMANA.format(sabado=data_absoluta(sabado)))

    # Dias achados, com a posicao na frase: a posicao ordena a pergunta de
    # "dois dias" na ordem em que o lead os disse.
    dias: list[tuple[int, date]] = []

    for casa in _DIA_E_MES.finditer(falado):
        falado = _apagar(falado, casa)
        dia = _data(hoje.year, int(casa.group(2)), int(casa.group(1)))
        if dia is None:
            return Ambigua(TEXTO_DA_DATA_INEXISTENTE)
        if dia < hoje:
            return Ambigua(TEXTO_DO_PASSADO)
        dias.append((casa.start(), dia))

    for casa in _DIA_DO_MES.finditer(falado):
        falado = _apagar(falado, casa)
        numero = int(casa.group(1))
        # Estritamente no futuro: "dia 25" dito no dia 25 e o do mes que vem --
        # quem quer hoje diz "hoje".
        if numero > hoje.day:
            dia = _data(hoje.year, hoje.month, numero)
        else:
            ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
            dia = _data(ano, mes, numero)
        if dia is None:
            return Ambigua(TEXTO_DA_DATA_INEXISTENTE)
        dias.append((casa.start(), dia))

    semana_que_vem = _SEMANA_QUE_VEM.search(falado)
    proxima_segunda = hoje + timedelta(days=7 - hoje.weekday())

    for padrao, deslocamento in ((_DEPOIS_DE_AMANHA, 2), (_AMANHA, 1), (_HOJE, 0)):
        for casa in padrao.finditer(falado):
            falado = _apagar(falado, casa)
            dias.append((casa.start(), hoje + timedelta(days=deslocamento)))

    for casa in _DIA_DA_SEMANA.finditer(falado):
        falado = _apagar(falado, casa)
        alvo = _NOMES.index(casa.group(1))
        if alvo == _DOMINGO:
            return Ambigua(TEXTO_DO_DOMINGO)
        if semana_que_vem:
            dias.append((casa.start(), proxima_segunda + timedelta(days=alvo)))
            continue
        delta = (alvo - hoje.weekday()) % 7
        if delta == 0:
            return Ambigua(
                TEXTO_DE_HOJE_OU_DA_PROXIMA.format(
                    hoje=data_absoluta(hoje),
                    proxima=data_absoluta(hoje + timedelta(days=7)),
                )
            )
        dias.append((casa.start(), hoje + timedelta(days=delta)))

    distintos = sorted({dia for _, dia in dias}, key=lambda d: min(p for p, x in dias if x == d))
    if len(distintos) > 1:
        return Ambigua(
            TEXTO_DE_DOIS_DIAS.format(
                primeiro=data_absoluta(distintos[0]), segundo=data_absoluta(distintos[1])
            )
        )
    dia_falado = distintos[0] if distintos else None
    if dia_falado is not None and dia_falado.weekday() == _DOMINGO:
        return Ambigua(TEXTO_DO_DOMINGO)

    # Hora. As formas mais especificas primeiro, e cada uma apaga o que casou.
    hora: int | None = None
    minuto = 0
    periodo_da_hora: str | None = None
    if casa := _HORA_E_MINUTO.search(falado):
        falado = _apagar(falado, casa)
        h, m = int(casa.group(1)), int(casa.group(2))
        if h <= 23 and m <= 59:
            hora, minuto = h, m
    elif casa := _HORA_COM_PERIODO.search(falado):
        falado = _apagar(falado, casa)
        h, periodo_da_hora = int(casa.group(1)), casa.group(2)
        if h <= 23:
            hora = h + 12 if periodo_da_hora == "tarde" and h < 12 else h
    elif casa := _HORA_COM_H.search(falado) or _HORA_APOS_AS.search(falado):
        falado = _apagar(falado, casa)
        h = int(casa.group(1))
        if h <= 23:
            hora = h

    if _NOITE.search(falado):
        return Ambigua(TEXTO_DA_NOITE)
    periodo: PeriodoDoDia | None = None
    if _MANHA.search(falado):
        periodo = PeriodoDoDia.MANHA
    elif _TARDE.search(falado):
        periodo = PeriodoDoDia.TARDE

    if hora is not None and periodo_da_hora is None:
        if periodo is PeriodoDoDia.TARDE and hora < 12:
            hora += 12
        elif periodo is None and 1 <= hora <= 7:
            # 3h ou 15h? Ninguem visita imovel as 3h, mas a regra e perguntar,
            # nao supor: supor aqui e o chute que a RN-11.3 proibe.
            return Ambigua(TEXTO_DA_HORA_AMBIGUA.format(hora=hora + 12))

    if semana_que_vem and dia_falado is None:
        return Semana(proxima_segunda)
    if dia_falado is None and hora is None and periodo is None:
        return NaoReconhecida()
    dia = dia_falado if dia_falado is not None else hoje

    if hora is not None:
        momento = datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=fuso)
        if momento < local:
            return Ambigua(TEXTO_DO_PASSADO)
        return Instante(momento)
    if periodo is not None:
        fim = datetime(dia.year, dia.month, dia.day, LIMITES_DO_PERIODO[periodo][1], tzinfo=fuso)
        if fim <= local:
            return Ambigua(TEXTO_DO_PASSADO)
        return Periodo(dia, periodo)
    return Dia(dia)
```

Notas para quem implementa:
- A expressão `distintos = sorted(...)` ordena os dias pela primeira posição em que apareceram. Se preferir escrever de outro jeito mais legível (um dict `dia -> primeira posição`), faça — o comportamento é o que os testes pedem.
- `_HORA_COM_H.search(falado) or _HORA_APOS_AS.search(falado)` dentro do walrus: se o `mypy` ou o `ruff` reclamarem, desdobre em duas linhas.
- Se algum teste esperado não bater, **não ajuste o teste nem force o código**: confira contra o D3/D4 da spec e relate a divergência como DONE_WITH_CONCERNS.

Registro dos literais — em `tests/unit/literais_ao_lead.py`, importe as 8 constantes `TEXTO_...` de `mobia.domain.agendamento.data_falada` e acrescente-as ao fim de `LITERAIS_AO_LEAD`; em `tests/unit/test_literais_ao_lead.py`, o tamanho esperado vai de 20 para 28. Se a guarda de acento ou a de promessa reprovar algum texto, corrija o **texto** (acento que falta, promessa de contato), não a guarda, e relate.

- [ ] **Step 4: Rodar e ver passar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_data_falada.py tests/unit/test_acento_no_texto_ao_lead.py tests/unit/test_literais_ao_lead.py tests/unit/test_promessa_ao_lead.py --tb=short -q`.

- [ ] **Step 5: Gates, suíte unitária e commit**

```bash
git add src/mobia/domain/agendamento/data_falada.py tests/unit/test_data_falada.py tests/unit/literais_ao_lead.py tests/unit/test_literais_ao_lead.py
git commit -m "feat(TEC-167): a data falada vira dia, periodo ou instante, e o ambiguo vira pergunta

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A ponte entre a data falada e o motor

**Files:**
- Modify: `src/mobia/domain/agendamento/data_falada.py` (acrescentar `janelas_para`)
- Test: `tests/unit/test_data_falada.py`

**Interfaces:**
- Consumes: `propor_janelas(..., de=...)`, `Intervalo`, `TipoDeCompromisso`, `DURACAO` (Task 1 / TEC-165); as seis formas e `LIMITES_DO_PERIODO` (Task 2).
- Produces: `janelas_para(resolucao, *, agora, jornada_inicio, jornada_fim, ocupados, tipo) -> list[Intervalo] | Ambigua | NaoReconhecida`.

- [ ] **Step 1: Testes que falham** — acrescente ao fim de `tests/unit/test_data_falada.py` (e os imports `from datetime import timedelta`, `from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso` e `janelas_para` no import de `data_falada`):

```python
# --- a ponte com o motor ---


def _janela(inicio: datetime, minutos: int = 60) -> Intervalo:
    return Intervalo(inicio, inicio + timedelta(minutes=minutos))


def _janelas(texto: str, ocupados: tuple[Intervalo, ...] = ()) -> object:
    return janelas_para(
        resolver(texto, agora=AGORA),
        agora=AGORA,
        jornada_inicio=9,
        jornada_fim=19,
        ocupados=list(ocupados),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    )


def test_quinta_de_manha_propoe_so_a_manha_de_quinta() -> None:
    """O primeiro cenario da card."""
    assert _janelas("pode ser quinta de manhã") == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_instante_livre_devolve_so_ele() -> None:
    assert _janelas("quinta às 15h") == [_janela(_ago(27, 15))]


def test_instante_ocupado_devolve_as_janelas_do_dia() -> None:
    ocupado = Intervalo(_ago(27, 15), _ago(27, 16))
    assert _janelas("quinta às 15h", (ocupado,)) == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_instante_fora_da_grade_devolve_as_janelas_do_dia() -> None:
    assert _janelas("quinta às 15h10") == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_dia_propoe_janelas_do_dia() -> None:
    assert _janelas("sexta") == [
        _janela(_ago(28, 9)),
        _janela(_ago(28, 9, 30)),
        _janela(_ago(28, 10)),
    ]


def test_semana_propoe_uma_por_dia_da_semana_que_vem() -> None:
    assert _janelas("semana que vem") == [
        _janela(_ago(31, 9)),
        _janela(_set(1, 9)),
        _janela(_set(2, 9)),
    ]


def test_ambigua_e_nao_reconhecida_passam_sem_chamar_o_motor() -> None:
    assert isinstance(_janelas("no fim de semana"), Ambigua)
    assert _janelas("tanto faz") == NaoReconhecida()
```

- [ ] **Step 2: Rodar e ver falhar** — `ImportError: cannot import name 'janelas_para'`.

- [ ] **Step 3: Implementar** — em `data_falada.py`, importe `from collections.abc import Sequence` e `from mobia.domain.agendamento.janelas import DURACAO, Intervalo, TipoDeCompromisso, propor_janelas`, e acrescente no fim:

```python
def janelas_para(
    resolucao: Resolucao,
    *,
    agora: datetime,
    jornada_inicio: int,
    jornada_fim: int,
    ocupados: Sequence[Intervalo],
    tipo: TipoDeCompromisso,
) -> list[Intervalo] | Ambigua | NaoReconhecida:
    """As janelas que a data falada pede, ou a resolucao que pede pergunta.

    `Ambigua` e `NaoReconhecida` voltam como vieram, sem chamar o motor:
    quem chama faz a pergunta. As outras viram um `[de, ate]` para
    `propor_janelas`. Um `Instante` que nao cabe -- ocupado, fora da grade,
    fora do atendimento -- cai nas janelas do mesmo dia, para o lead receber
    alternativa em vez de silencio.
    """
    fuso = get_settings().fuso_de_envio

    def buscar(de: datetime, ate: datetime) -> list[Intervalo]:
        return propor_janelas(
            agora=agora,
            de=de,
            ate=ate,
            jornada_inicio=jornada_inicio,
            jornada_fim=jornada_fim,
            ocupados=ocupados,
            tipo=tipo,
        )

    def meia_noite(dia: date) -> datetime:
        return datetime(dia.year, dia.month, dia.day, tzinfo=fuso)

    match resolucao:
        case Instante(momento=momento):
            exata = buscar(momento, momento + DURACAO[tipo])
            if exata and exata[0].inicio == momento:
                return exata[:1]
            dia = momento.astimezone(fuso).date()
            return buscar(meia_noite(dia), meia_noite(dia + timedelta(days=1)))
        case Periodo(dia=dia, periodo=periodo):
            inicio, fim = LIMITES_DO_PERIODO[periodo]
            base = meia_noite(dia)
            return buscar(base + timedelta(hours=inicio), base + timedelta(hours=fim))
        case Dia(dia=dia):
            return buscar(meia_noite(dia), meia_noite(dia + timedelta(days=1)))
        case Semana(segunda=segunda):
            return buscar(meia_noite(segunda), meia_noite(segunda + timedelta(days=7)))
        case Ambigua() | NaoReconhecida():
            return resolucao
```

Nota: `meia_noite(...) + timedelta(hours=...)` é aritmética de relógio de parede com `ZoneInfo`; `America/Sao_Paulo` não tem horário de verão desde 2019, o mesmo argumento do plano da TEC-165. Atualize a docstring do módulo: ele passa a importar o motor, e a ponte é a única peça que conhece os dois.

- [ ] **Step 4: Rodar e ver passar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_data_falada.py tests/unit/test_janelas_de_agendamento.py --tb=short -q`.

- [ ] **Step 5: Gates, suíte unitária e commit**

```bash
git add src/mobia/domain/agendamento/data_falada.py tests/unit/test_data_falada.py
git commit -m "feat(TEC-167): a data falada vira janelas do motor, e o que nao cabe cai no mesmo dia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
