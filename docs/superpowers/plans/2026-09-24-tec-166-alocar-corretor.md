# TEC-166 — Alocar o corretor: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decidir qual corretor atende um lead em cada dia — especialidade + região, capacidade diária de visitas, plantão como rede — e gravar o motivo no agendamento.

**Architecture:** Uma função pura `alocar` devolve os candidatos em ordem com o motivo de cada um; `janelas_alocadas` percorre as datas locais do horizonte, pede os candidatos do dia e fica com a primeira janela livre do primeiro candidato que tiver uma. A contagem de visitas por dia é um port próprio (`ContadorDeVisitas`), implementado por `AgendaPostgres`; o motivo vai para a coluna nova `agendamentos.motivo_da_alocacao` pela `reservar`.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (migrations escritas à mão), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-166-alocar-corretor-design.md`

## Global Constraints

- Comentários e docstrings em `src/` e `tests/`: português **sem acento**. Prosa em `docs/`: com acento.
- Nenhum texto ao lead nesta card — nada entra em `tests/unit/literais_ao_lead.py`.
- Status/vocabulário no banco: `String` + `CHECK`, nunca enum nativo (regra desde a 0016).
- Migrations escritas à mão; nunca aceitar proposta do autogenerate para derrubar `ex_agendamentos_sem_sobreposicao`.
- `agora` sempre entra como parâmetro com fuso; datetime ingênuo levanta `ValueError`.
- Fuso das datas locais: `get_settings().fuso_de_envio` (Python) / `get_settings().followup_fuso` (string para o SQL). Nunca data UTC.
- Desempate: `criado_em` mais antigo primeiro (e `id` como segundo critério, para ser total).
- Capacidade conta **só `VISITA_PRESENCIAL`**; reunião remota nunca é barrada por capacidade.
- Bairro não vira zona: região casa por `normalizar_regiao` igual dos dois lados, ou por zona em comum via `zonas_de`.
- Os três gates antes de todo commit: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Commit: `tipo(TEC-166): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Citação de código em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.

## Review Focus

1. **Plantão que também tem match exato** — tem de aparecer uma vez só na lista, como `MATCH_EXATO`, e não de novo como plantão. Teste em Task 2.
2. **Visita de hoje antes de `agora`** — a visita das 9h gasta a capacidade de hoje mesmo com a busca às 14h; o contador trabalha com datas locais inteiras. Teste em Task 4.
3. **Visita às 23h30 local** — é da data local, não da UTC (já do dia seguinte em UTC). Teste em Task 4.
4. **Reserva vencida** — não gasta capacidade (mesmo predicado de vida de `ocupados`). Teste em Task 4.
5. **Corretor inativo com match** — nunca entra, nem conta como "havia match" para o motivo do plantão. Teste em Task 2.

---

### Task 1: Vocabulário do motivo e o critério do lead

**Files:**
- Create: `src/mobia/domain/agendamento/vocabulario.py`
- Create: `src/mobia/domain/agendamento/alocacao.py`
- Test: `tests/unit/test_alocacao_do_corretor.py`

**Interfaces:**
- Produces:
  - `MotivoDaAlocacao(StrEnum)`: `MATCH_EXATO`, `SEM_MATCH`, `MATCH_SEM_CAPACIDADE`
  - `CriterioDoLead(especialidade: Especialidade | None, regiao: str | None)` (frozen dataclass)
  - `criterio_de(qualificacao: LeadQualification) -> CriterioDoLead`
  - `regiao_casa(do_lead: str, do_corretor: str) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_alocacao_do_corretor.py`:

```python
"""Alocacao do corretor por especialidade e regiao, testada. TEC-166, RN-11.2, RN-07.4.

Puro: os `Corretor` sao objetos transientes, nunca gravados, e a contagem de
visitas do dia entra como dicionario.
"""

import pytest

from mobia.domain.agendamento.alocacao import CriterioDoLead, criterio_de, regiao_casa
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.vocabulario import Especialidade


def _qualificacao(**campos: object) -> LeadQualification:
    return LeadQualification(channel="whatsapp", conversation_key="5511911111111", **campos)


# --- o criterio do lead ---


@pytest.mark.parametrize("intencao", ["COMPRA", "ALUGUEL"])
def test_compra_e_aluguel_viram_a_especialidade_de_mesmo_nome(intencao: str) -> None:
    criterio = criterio_de(_qualificacao(intencao=intencao, regiao="zona sul"))
    assert criterio == CriterioDoLead(Especialidade(intencao), "zona sul")


def test_investimento_abaixo_do_limiar_e_investimento() -> None:
    criterio = criterio_de(
        _qualificacao(intencao="INVESTIMENTO", ticket_investimento_centavos=99_999_999)
    )
    assert criterio.especialidade == Especialidade.INVESTIMENTO


def test_investimento_no_limiar_exato_e_alto_ticket() -> None:
    criterio = criterio_de(
        _qualificacao(intencao="INVESTIMENTO", ticket_investimento_centavos=100_000_000)
    )
    assert criterio.especialidade == Especialidade.INVESTIMENTO_ALTO_TICKET


def test_investimento_sem_ticket_e_investimento() -> None:
    criterio = criterio_de(_qualificacao(intencao="INVESTIMENTO"))
    assert criterio.especialidade == Especialidade.INVESTIMENTO


@pytest.mark.parametrize(
    "intencao", ["INDEFINIDA", "VENDER_IMOVEL", "SUPORTE_CONTRATO", "FORA_DE_ESCOPO", None]
)
def test_intencao_sem_especialidade_vira_nulo(intencao: str | None) -> None:
    assert criterio_de(_qualificacao(intencao=intencao)).especialidade is None


def test_regiao_vazia_vira_nulo() -> None:
    assert criterio_de(_qualificacao(intencao="COMPRA", regiao="")).regiao is None
    assert criterio_de(_qualificacao(intencao="COMPRA")).regiao is None


# --- o casamento de regiao ---


@pytest.mark.parametrize(
    ("do_lead", "do_corretor"),
    [
        ("pinheiros", "pinheiros"),
        ("zona sul", "zona sul"),
        ("zona sul", "sul"),
        ("sul", "zona sul"),
        ("centro", "regiao do centro"),
    ],
)
def test_regioes_que_casam(do_lead: str, do_corretor: str) -> None:
    assert regiao_casa(do_lead, do_corretor)


@pytest.mark.parametrize(
    ("do_lead", "do_corretor"),
    [
        ("moema", "zona sul"),  # bairro nao vira zona (D2)
        ("zona sul", "zona norte"),
        ("pinheiros", "moema"),
    ],
)
def test_regioes_que_nao_casam(do_lead: str, do_corretor: str) -> None:
    assert not regiao_casa(do_lead, do_corretor)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_alocacao_do_corretor.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.agendamento.alocacao'`

- [ ] **Step 3: Write the vocabulary module**

`src/mobia/domain/agendamento/vocabulario.py`:

```python
"""Por que aquele corretor foi alocado. TEC-166, D4 do desenho.

Modulo sem I/O, no molde de `handoff/vocabulario.py`. Categoria e nao texto
livre: o que a gerente le e o motivo junto do corretor e do lead, montado
pela tela que existir -- texto gravado envelhece quando a regra muda.
"""

from enum import StrEnum


class MotivoDaAlocacao(StrEnum):
    # Especialidade e regiao casaram.
    MATCH_EXATO = "MATCH_EXATO"
    # Nenhum corretor ativo tinha especialidade e regiao; foi o plantao.
    SEM_MATCH = "SEM_MATCH"
    # Havia match exato, mas nenhum pode naquele dia -- sem capacidade ou
    # sem horario livre; foi o plantao.
    MATCH_SEM_CAPACIDADE = "MATCH_SEM_CAPACIDADE"
```

- [ ] **Step 4: Write the criterion and region matching**

`src/mobia/domain/agendamento/alocacao.py`:

```python
"""Qual corretor atende o lead num dado dia. TEC-166, RN-11.2, RN-07.4.

Puro: nao toca banco, rede nem relogio. A contagem de visitas do dia entra
pronta, e quem percorre as datas e `janelas_alocadas` (`janelas.py`). Ver
docs/superpowers/specs/2026-09-24-tec-166-alocar-corretor-design.md.
"""

from dataclasses import dataclass

from mobia.domain.agente.schemas import normalizar_regiao
from mobia.domain.catalogo.busca import zonas_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.vocabulario import Especialidade, especialidade_de


@dataclass(frozen=True)
class CriterioDoLead:
    especialidade: Especialidade | None
    regiao: str | None


# COMPRA e ALUGUEL sao grafadas identicas em `Intencao` e em `Especialidade`
# (D3 da TEC-196): a traducao e por igualdade de string.
_POR_IGUALDADE = (Especialidade.COMPRA, Especialidade.ALUGUEL)


def criterio_de(qualificacao: LeadQualification) -> CriterioDoLead:
    """O que a alocacao precisa saber do lead. D1 do desenho.

    Investimento sem ticket fica `INVESTIMENTO`: nao ha como afirmar alto
    ticket sem o numero. Intencao que nao e especialidade de ninguem vira
    `None`, e criterio com `None` nunca tem match exato.
    """
    intencao = qualificacao.intencao
    especialidade: Especialidade | None
    if intencao == Especialidade.INVESTIMENTO:
        ticket = qualificacao.ticket_investimento_centavos
        especialidade = Especialidade.INVESTIMENTO if ticket is None else especialidade_de(ticket)
    elif intencao in _POR_IGUALDADE:
        especialidade = Especialidade(intencao)
    else:
        especialidade = None
    return CriterioDoLead(especialidade, qualificacao.regiao or None)


def regiao_casa(do_lead: str, do_corretor: str) -> bool:
    """Igualdade canonica, ou uma zona em comum. D2 do desenho.

    A do corretor foi gravada so com `dobrar()` (D4 da TEC-196); passar as
    duas por `normalizar_regiao` tira "regiao do" e "perto da" dos dois lados.
    **Bairro nao vira zona**: "moema" nao casa "zona sul", porque nao existe
    mapeamento bairro->zona no repo.
    """
    lead, corretor = normalizar_regiao(do_lead), normalizar_regiao(do_corretor)
    if lead == corretor:
        return True
    return bool(set(zonas_de([lead])) & set(zonas_de([corretor])))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_alocacao_do_corretor.py -v --tb=short`
Expected: PASS (all). If `("centro", "regiao do centro")` fails, print `normalizar_regiao("regiao do centro")` — measured on 24/09/2026 it returns `"centro"`.

- [ ] **Step 6: Run the three gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/vocabulario.py src/mobia/domain/agendamento/alocacao.py tests/unit/test_alocacao_do_corretor.py
git commit -m "feat(TEC-166): o lead vira criterio de especialidade e regiao

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `alocar` — os candidatos do dia, em ordem

**Files:**
- Modify: `src/mobia/domain/agendamento/alocacao.py`
- Test: `tests/unit/test_alocacao_do_corretor.py` (append)

**Interfaces:**
- Consumes: `CriterioDoLead`, `regiao_casa`, `MotivoDaAlocacao` (Task 1)
- Produces:
  - `Alocacao(corretor: Corretor, motivo: MotivoDaAlocacao)` (frozen dataclass)
  - `alocar(*, criterio: CriterioDoLead, corretores: Sequence[Corretor], visitas_na_data: Mapping[uuid.UUID, int]) -> list[Alocacao]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_alocacao_do_corretor.py` (merge the imports into the top of the file):

```python
import uuid
from datetime import UTC, datetime

from mobia.domain.agendamento.alocacao import Alocacao, alocar
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.corretores.models import Corretor

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _corretor(
    nome: str,
    *,
    especialidades: tuple[str, ...] = ("COMPRA",),
    regioes: tuple[str, ...] = ("zona sul",),
    plantao: bool = False,
    ativo: bool = True,
    capacidade: int = 3,
    ordem: int = 0,
) -> Corretor:
    return Corretor(
        id=uuid.uuid4(),
        nome=nome,
        especialidades=list(especialidades),
        regioes_atuacao=list(regioes),
        plantao=plantao,
        ativo=ativo,
        capacidade_diaria=capacidade,
        horario_inicio=9,
        horario_fim=18,
        criado_em=_BASE.replace(day=1 + ordem),
    )


def _nomes(alocacoes: list[Alocacao]) -> list[tuple[str, MotivoDaAlocacao]]:
    return [(a.corretor.nome, a.motivo) for a in alocacoes]


COMPRA_SUL = CriterioDoLead(Especialidade.COMPRA, "zona sul")


# --- os cenarios da card ---


def test_match_exato_e_escolhido_com_o_motivo() -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", especialidades=("ALUGUEL",), regioes=("norte",), plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao, ana], visitas_na_data={})
    assert _nomes(resultado)[0] == ("ana", MotivoDaAlocacao.MATCH_EXATO)


def test_alto_ticket_so_considera_o_especialista() -> None:
    comum = _corretor("comum", especialidades=("INVESTIMENTO",), ordem=0)
    alto = _corretor("alto", especialidades=("INVESTIMENTO_ALTO_TICKET",), ordem=1)
    criterio = CriterioDoLead(Especialidade.INVESTIMENTO_ALTO_TICKET, "zona sul")
    resultado = alocar(criterio=criterio, corretores=[comum, alto], visitas_na_data={})
    assert _nomes(resultado) == [("alto", MotivoDaAlocacao.MATCH_EXATO)]


def test_sem_match_cai_no_plantao_com_o_motivo() -> None:
    ana = _corretor("ana", regioes=("zona norte",))
    plantao = _corretor("plantao", especialidades=("COMPRA",), regioes=("oeste",), plantao=True)
    criterio = CriterioDoLead(Especialidade.ALUGUEL, "zona leste")
    resultado = alocar(criterio=criterio, corretores=[ana, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_capacidade_esgotada_exclui_na_data() -> None:
    ana = _corretor("ana", capacidade=2, ordem=0)
    bia = _corretor("bia", capacidade=2, ordem=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana, bia], visitas_na_data={ana.id: 2})
    assert _nomes(resultado) == [("bia", MotivoDaAlocacao.MATCH_EXATO)]


# --- as bordas ---


def test_match_esgotado_leva_o_plantao_com_match_sem_capacidade() -> None:
    ana = _corretor("ana", capacidade=1)
    plantao = _corretor("plantao", regioes=("norte",), plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana, plantao], visitas_na_data={ana.id: 1})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE)]


def test_plantao_tambem_esgotado_da_lista_vazia() -> None:
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, capacidade=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={plantao.id: 1})
    assert resultado == []


def test_alto_ticket_sem_especialista_cai_no_plantao() -> None:
    comum = _corretor("comum", especialidades=("INVESTIMENTO",))
    plantao = _corretor("plantao", especialidades=("COMPRA",), regioes=("norte",), plantao=True)
    criterio = CriterioDoLead(Especialidade.INVESTIMENTO_ALTO_TICKET, "zona sul")
    resultado = alocar(criterio=criterio, corretores=[comum, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


@pytest.mark.parametrize(
    "criterio",
    [
        CriterioDoLead(Especialidade.COMPRA, None),
        CriterioDoLead(None, "zona sul"),
        CriterioDoLead(None, None),
    ],
)
def test_criterio_incompleto_nao_tem_match(criterio: CriterioDoLead) -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, ordem=1)
    resultado = alocar(criterio=criterio, corretores=[ana, plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_empate_vai_para_o_mais_antigo() -> None:
    nova = _corretor("nova", ordem=5)
    antiga = _corretor("antiga", ordem=1)
    p_novo = _corretor("p_novo", regioes=("norte",), plantao=True, ordem=4)
    p_antigo = _corretor("p_antigo", regioes=("norte",), plantao=True, ordem=2)
    resultado = alocar(
        criterio=COMPRA_SUL, corretores=[nova, p_novo, antiga, p_antigo], visitas_na_data={}
    )
    assert _nomes(resultado) == [
        ("antiga", MotivoDaAlocacao.MATCH_EXATO),
        ("nova", MotivoDaAlocacao.MATCH_EXATO),
        ("p_antigo", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
        ("p_novo", MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
    ]


def test_zona_casa_com_e_sem_prefixo() -> None:
    ana = _corretor("ana", regioes=("sul",))
    resultado = alocar(criterio=COMPRA_SUL, corretores=[ana], visitas_na_data={})
    assert _nomes(resultado) == [("ana", MotivoDaAlocacao.MATCH_EXATO)]


def test_bairro_nao_casa_zona() -> None:
    ana = _corretor("ana", regioes=("zona sul",))
    criterio = CriterioDoLead(Especialidade.COMPRA, "moema")
    assert alocar(criterio=criterio, corretores=[ana], visitas_na_data={}) == []


def test_inativo_nunca_entra_nem_conta_como_match() -> None:
    inativa = _corretor("inativa", ativo=False)
    plantao_inativo = _corretor("p_inativo", regioes=("norte",), plantao=True, ativo=False)
    plantao = _corretor("plantao", regioes=("norte",), plantao=True, ordem=1)
    resultado = alocar(
        criterio=COMPRA_SUL, corretores=[inativa, plantao_inativo, plantao], visitas_na_data={}
    )
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.SEM_MATCH)]


def test_plantao_com_match_aparece_uma_vez_como_match() -> None:
    plantao = _corretor("plantao", plantao=True)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={})
    assert _nomes(resultado) == [("plantao", MotivoDaAlocacao.MATCH_EXATO)]


def test_plantao_com_match_esgotado_nao_volta_como_plantao() -> None:
    plantao = _corretor("plantao", plantao=True, capacidade=1)
    resultado = alocar(criterio=COMPRA_SUL, corretores=[plantao], visitas_na_data={plantao.id: 1})
    assert resultado == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_alocacao_do_corretor.py -v --tb=short`
Expected: FAIL with `ImportError: cannot import name 'Alocacao'`

- [ ] **Step 3: Implement `alocar`**

Append to `src/mobia/domain/agendamento/alocacao.py` (merge imports at the top: `import uuid`, `from collections.abc import Mapping, Sequence`, `from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao`, `from mobia.domain.corretores.models import Corretor`):

```python
@dataclass(frozen=True)
class Alocacao:
    corretor: Corretor
    motivo: MotivoDaAlocacao


def _tem_match(corretor: Corretor, criterio: CriterioDoLead) -> bool:
    # A card pede especialidade E regiao: criterio incompleto nunca casa.
    if criterio.especialidade is None or criterio.regiao is None:
        return False
    if criterio.especialidade not in corretor.especialidades:
        return False
    return any(regiao_casa(criterio.regiao, regiao) for regiao in corretor.regioes_atuacao)


def alocar(
    *,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    visitas_na_data: Mapping[uuid.UUID, int],
) -> list[Alocacao]:
    """Os candidatos daquela data, em ordem de preferencia. D3 do desenho.

    Primeiro os ativos com match exato e capacidade sobrando; depois os
    plantoes ativos com capacidade que ainda nao estao na lista. Devolve a
    lista, e nao um so, porque quem chama desce para o proximo quando o
    primeiro nao tem horario livre (D5).

    O motivo do plantao depende so de EXISTIR match ativo, esgotado ou nao:
    se o plantao acabou escolhido havendo match, o match nao pode naquele
    dia -- por capacidade aqui, ou por falta de horario em `janelas_alocadas`.

    Desempate por `criado_em` mais antigo, e `id` para a ordem ser total --
    o mesmo criterio de `destinatario_do_handoff`. Balancear carga esta fora
    da card.
    """
    ativos = sorted(
        (corretor for corretor in corretores if corretor.ativo),
        key=lambda corretor: (corretor.criado_em, str(corretor.id)),
    )

    def _cabe(corretor: Corretor) -> bool:
        return visitas_na_data.get(corretor.id, 0) < corretor.capacidade_diaria

    com_match = [corretor for corretor in ativos if _tem_match(corretor, criterio)]
    candidatos = [
        Alocacao(corretor, MotivoDaAlocacao.MATCH_EXATO)
        for corretor in com_match
        if _cabe(corretor)
    ]
    motivo_do_plantao = (
        MotivoDaAlocacao.MATCH_SEM_CAPACIDADE if com_match else MotivoDaAlocacao.SEM_MATCH
    )
    # Plantao que tambem casou ja foi decidido acima -- entrou como match, ou
    # saiu por capacidade. Nao volta pela porta do plantao.
    ja_decididos = {corretor.id for corretor in com_match}
    candidatos += [
        Alocacao(corretor, motivo_do_plantao)
        for corretor in ativos
        if corretor.plantao and corretor.id not in ja_decididos and _cabe(corretor)
    ]
    return candidatos
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_alocacao_do_corretor.py -v --tb=short`
Expected: PASS (all)

- [ ] **Step 5: Run the three gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/alocacao.py tests/unit/test_alocacao_do_corretor.py
git commit -m "feat(TEC-166): a alocacao ordena os candidatos do dia com o motivo de cada um

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `janelas_alocadas` — uma janela por dia, com corretor

**Files:**
- Modify: `src/mobia/domain/agendamento/janelas.py`
- Test: `tests/unit/test_janelas_alocadas.py`

**Interfaces:**
- Consumes: `CriterioDoLead`, `alocar`, `Alocacao` (Tasks 1–2); `propor_janelas`, `AgendaDoCorretor`, `Intervalo`, `TipoDeCompromisso`, `ANTECEDENCIA_MINIMA`, `MAXIMO_DE_JANELAS`, `_exigir_fuso` (existing in `janelas.py`)
- Produces:
  - `ContadorDeVisitas(Protocol)` with `async visitas_por_dia(self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime) -> dict[tuple[uuid.UUID, date], int]`
  - `JanelaAlocada(janela: Intervalo, corretor_id: uuid.UUID, motivo: MotivoDaAlocacao)` (frozen dataclass)
  - `async janelas_alocadas(*, criterio, corretores, agenda, visitas, agora, ate, tipo) -> list[JanelaAlocada]`

**Import cycle warning:** `alocacao.py` must NOT import `janelas.py`. `janelas.py` imports `alocacao.py` — one direction only. Import inside `janelas.py` at module top: `from mobia.domain.agendamento.alocacao import CriterioDoLead, alocar` and `from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao`. If `ruff`/runtime reports a cycle through `catalogo.busca` → something → `janelas`, move the `alocacao` import into the body of `janelas_alocadas` and say so in a comment.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_janelas_alocadas.py`:

```python
"""Janelas com corretor alocado, uma por dia. TEC-166, D5 do desenho.

25/08/2026 e uma terca-feira; a janela da imobiliaria fica nos valores padrao
de `Settings` (segunda a sabado, 9h as 19h). A jornada dos corretores e 9h-18h.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from mobia.domain.agendamento.alocacao import CriterioDoLead
from mobia.domain.agendamento.janelas import (
    Intervalo,
    JanelaAlocada,
    TipoDeCompromisso,
    janelas_alocadas,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.vocabulario import Especialidade

SP = ZoneInfo("America/Sao_Paulo")
COMPRA_SUL = CriterioDoLead(Especialidade.COMPRA, "zona sul")
VISITA = TipoDeCompromisso.VISITA_PRESENCIAL


def _ago(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=SP)


def _hora(inicio: datetime, minutos: int = 60) -> Intervalo:
    return Intervalo(inicio, inicio + timedelta(minutes=minutos))


def _corretor(nome: str, *, plantao: bool = False, capacidade: int = 1, ordem: int = 0) -> Corretor:
    return Corretor(
        id=uuid.uuid4(),
        nome=nome,
        especialidades=["COMPRA"],
        regioes_atuacao=["norte"] if plantao else ["zona sul"],
        plantao=plantao,
        ativo=True,
        capacidade_diaria=capacidade,
        horario_inicio=9,
        horario_fim=18,
        criado_em=datetime(2026, 1, 1 + ordem, tzinfo=UTC),
    )


class _AgendaPorCorretor:
    def __init__(self, ocupados: dict[uuid.UUID, list[Intervalo]] | None = None) -> None:
        self._ocupados = ocupados or {}

    async def ocupados(
        self, corretor_id: uuid.UUID, de: datetime, ate: datetime
    ) -> list[Intervalo]:
        return self._ocupados.get(corretor_id, [])


class _ContadorFalso:
    def __init__(self, visitas: dict[tuple[uuid.UUID, date], int] | None = None) -> None:
        self._visitas = visitas or {}
        self.chamadas: list[tuple[list[uuid.UUID], date, date, datetime]] = []

    async def visitas_por_dia(
        self, corretor_ids, *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]:
        self.chamadas.append((list(corretor_ids), de, ate, agora))
        return self._visitas


async def _alocar(corretores, *, agenda=None, visitas=None, tipo=VISITA, ate=None):
    return await janelas_alocadas(
        criterio=COMPRA_SUL,
        corretores=corretores,
        agenda=agenda or _AgendaPorCorretor(),
        visitas=visitas or _ContadorFalso(),
        agora=_ago(25, 14),
        ate=ate or _ago(29, 19),
        tipo=tipo,
    )


async def test_quinta_esgotada_vai_para_o_proximo_candidato() -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", plantao=True, ordem=1)
    visitas = _ContadorFalso({(ana.id, date(2026, 8, 27)): 1})
    resultado = await _alocar([ana, plantao], visitas=visitas)
    assert resultado == [
        JanelaAlocada(_hora(_ago(25, 17)), ana.id, MotivoDaAlocacao.MATCH_EXATO),
        JanelaAlocada(_hora(_ago(26, 9)), ana.id, MotivoDaAlocacao.MATCH_EXATO),
        JanelaAlocada(_hora(_ago(27, 9)), plantao.id, MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
    ]


async def test_match_sem_horario_livre_cai_no_plantao() -> None:
    ana = _corretor("ana", capacidade=5)
    plantao = _corretor("plantao", plantao=True, ordem=1)
    # Terca: a unica janela depois das 3h de antecedencia e 17h-18h.
    agenda = _AgendaPorCorretor({ana.id: [_hora(_ago(25, 17))]})
    resultado = await _alocar([ana, plantao], agenda=agenda)
    assert resultado[0] == JanelaAlocada(
        _hora(_ago(25, 17)), plantao.id, MotivoDaAlocacao.MATCH_SEM_CAPACIDADE
    )
    assert resultado[1].corretor_id == ana.id


async def test_contador_recebe_as_datas_locais_inteiras_e_o_agora() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso()
    await _alocar([ana], visitas=visitas)
    assert visitas.chamadas == [([ana.id], date(2026, 8, 25), date(2026, 8, 29), _ago(25, 14))]


async def test_reuniao_remota_ignora_a_capacidade() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso(
        {(ana.id, date(2026, 8, dia)): 9 for dia in range(25, 30)}
    )
    resultado = await _alocar([ana], visitas=visitas, tipo=TipoDeCompromisso.REUNIAO_REMOTA)
    assert visitas.chamadas == []
    assert [j.corretor_id for j in resultado] == [ana.id, ana.id, ana.id]


async def test_no_maximo_tres_uma_por_dia() -> None:
    ana = _corretor("ana", capacidade=5)
    resultado = await _alocar([ana], ate=_sp_setembro(5))
    dias = [j.janela.inicio.astimezone(SP).date() for j in resultado]
    assert len(resultado) == 3
    assert len(set(dias)) == 3


async def test_ninguem_pode_da_lista_vazia() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso({(ana.id, date(2026, 8, dia)): 1 for dia in range(25, 30)})
    assert await _alocar([ana], visitas=visitas) == []


def _sp_setembro(dia: int) -> datetime:
    return datetime(2026, 9, dia, 19, tzinfo=SP)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_janelas_alocadas.py -v --tb=short`
Expected: FAIL with `ImportError: cannot import name 'JanelaAlocada'`

- [ ] **Step 3: Implement the port and the function**

In `src/mobia/domain/agendamento/janelas.py`: add `time` to the `datetime` import; add the imports of `CriterioDoLead`, `alocar`, `MotivoDaAlocacao`; then append after `propor_janelas_do_corretor`:

```python
class ContadorDeVisitas(Protocol):
    """Quantas visitas cada corretor tem em cada data local. TEC-166, D6.

    Port proprio, e nao um metodo a mais em `AgendaDoCorretor`: os fakes da
    TEC-165 e da TEC-167 so implementam `ocupados`, e um Protocol maior os
    reprovaria no mypy sem que nada neles tivesse mudado. `AgendaPostgres`
    implementa os dois.

    `de` e `ate` sao DATAS locais inteiras: a visita das 9h de hoje gasta a
    capacidade de hoje mesmo quando a busca comeca as 14h. A vida da reserva
    e avaliada em `agora`.
    """

    async def visitas_por_dia(
        self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]: ...


@dataclass(frozen=True)
class JanelaAlocada:
    janela: Intervalo
    corretor_id: uuid.UUID
    motivo: MotivoDaAlocacao


async def janelas_alocadas(
    *,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    agora: datetime,
    ate: datetime,
    tipo: TipoDeCompromisso,
) -> list[JanelaAlocada]:
    """Ate `MAXIMO_DE_JANELAS` janelas, uma por data local, cada uma com corretor. D5.

    Para cada data, pede os candidatos a `alocar` e desce por eles ate um ter
    janela livre naquele dia. Uma janela por dia mantem o espalhamento da
    TEC-165. Lista vazia -- ninguem pode em data nenhuma -- e onde a TEC-169
    comeca.

    Capacidade so barra visita: para reuniao remota o contador nem e
    consultado, e todo corretor entra com zero visitas.
    """
    _exigir_fuso("agora", agora)
    _exigir_fuso("ate", ate)
    fuso = get_settings().fuso_de_envio
    primeiro_dia = (agora + ANTECEDENCIA_MINIMA).astimezone(fuso).date()
    ultimo_dia = ate.astimezone(fuso).date()

    contagem: dict[tuple[uuid.UUID, date], int] = {}
    if tipo is TipoDeCompromisso.VISITA_PRESENCIAL:
        contagem = await visitas.visitas_por_dia(
            [corretor.id for corretor in corretores],
            de=agora.astimezone(fuso).date(),
            ate=ultimo_dia,
            agora=agora,
        )

    # A agenda de cada corretor e lida uma vez para o horizonte inteiro, e so
    # de quem chegou a ser candidato.
    ocupados_de: dict[uuid.UUID, list[Intervalo]] = {}
    escolhidas: list[JanelaAlocada] = []
    dia = primeiro_dia
    while dia <= ultimo_dia and len(escolhidas) < MAXIMO_DE_JANELAS:
        visitas_na_data = {cid: n for (cid, data), n in contagem.items() if data == dia}
        inicio_do_dia = datetime.combine(dia, time(0), tzinfo=fuso)
        fim_do_dia = min(ate, inicio_do_dia + timedelta(days=1))
        for alocacao in alocar(
            criterio=criterio, corretores=corretores, visitas_na_data=visitas_na_data
        ):
            corretor = alocacao.corretor
            if corretor.id not in ocupados_de:
                ocupados_de[corretor.id] = await agenda.ocupados(corretor.id, agora, ate)
            janelas = propor_janelas(
                agora=agora,
                ate=fim_do_dia,
                jornada_inicio=corretor.horario_inicio,
                jornada_fim=corretor.horario_fim,
                ocupados=ocupados_de[corretor.id],
                tipo=tipo,
                de=inicio_do_dia,
            )
            if janelas:
                escolhidas.append(JanelaAlocada(janelas[0], corretor.id, alocacao.motivo))
                break
        dia += timedelta(days=1)
    return escolhidas
```

Note: `datetime.combine(..., tzinfo=fuso)` builds local midnight; `America/Sao_Paulo` has no DST since 2019, and `+ timedelta(days=1)` on an aware datetime is wall-clock arithmetic, which is what "the next local day" means here.

- [ ] **Step 4: Run the new and the existing window tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_janelas_alocadas.py tests/unit/test_janelas_de_agendamento.py tests/unit/test_data_falada.py -v --tb=short`
Expected: PASS (all). If `test_match_sem_horario_livre_cai_no_plantao` fails because Tuesday has a 17h30 window, check `_primeiro_ponto_da_grade`: with `agora` 14h the first start is 17h, and a 60-minute visit starting at 17h30 ends 18h30, past the 18h jornada — so 17h is the only Tuesday window.

- [ ] **Step 5: Run the three gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/janelas.py tests/unit/test_janelas_alocadas.py
git commit -m "feat(TEC-166): as janelas saem com o corretor alocado em cada dia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Migration 0045, o motivo na reserva e a contagem de visitas no Postgres

**Files:**
- Create: `alembic/versions/0045_motivo_da_alocacao.py`
- Modify: `src/mobia/domain/agendamento/models.py`
- Modify: `src/mobia/domain/agendamento/repositorio.py`
- Modify: `tests/integration/test_agendamento_repositorio.py` (helper `_reservar` and every direct call to `reservar`/`reservar_ou_alternativas`)
- Modify: `tests/integration/test_agendamento_schema.py` (the raw `_inserir`)
- Test: `tests/integration/test_visitas_por_dia.py`

**Interfaces:**
- Consumes: `MotivoDaAlocacao` (Task 1), `ContadorDeVisitas` (Task 3)
- Produces:
  - column `Agendamento.motivo_da_alocacao: Mapped[str]`, `String(24)`, NOT NULL, CHECK `ck_agendamentos_motivo_da_alocacao`
  - `reservar(..., motivo: MotivoDaAlocacao)` — new required keyword
  - `reservar_ou_alternativas(..., motivo: MotivoDaAlocacao)` — new required keyword, passed through
  - `AgendaPostgres.visitas_por_dia(corretor_ids, *, de: date, ate: date, agora: datetime) -> dict[tuple[uuid.UUID, date], int]`

Requires `docker compose` up (Postgres + Redis).

- [ ] **Step 1: Write the failing integration tests**

`tests/integration/test_visitas_por_dia.py`:

```python
"""A contagem de visitas por data local, no banco. TEC-166, D6 do desenho.

27/08/2026 e uma quinta. As linhas entram direto pelo modelo: o que se testa
aqui e a leitura, nao a reserva.
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import AgendaPostgres, Reserva, reservar
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 27, 14, 0, tzinfo=SP)
QUINTA = date(2026, 8, 27)
SEXTA = date(2026, 8, 28)


async def _gravar(
    session,
    corretor_id,
    inicio: datetime,
    *,
    status=StatusDoAgendamento.CONFIRMADO,
    tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    reservado_ate: datetime | None = None,
) -> None:
    session.add(
        Agendamento(
            id=uuid.uuid4(),
            corretor_id=corretor_id,
            channel="whatsapp",
            conversation_key=str(uuid.uuid4())[:20],
            imovel_id=None,
            tipo=str(tipo),
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status=status,
            reservado_ate=reservado_ate or inicio,
            criado_em=AGORA,
            confirmado_em=None,
            motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
        )
    )
    await session.commit()


async def _contar(session_factory, corretor_ids, *, de=QUINTA, ate=SEXTA):
    return await AgendaPostgres(session_factory).visitas_por_dia(
        corretor_ids, de=de, ate=ate, agora=AGORA
    )


async def test_conta_confirmada_e_reserva_viva(session, session_factory, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 27, 10, tzinfo=SP))
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 16, tzinfo=SP),
        status=StatusDoAgendamento.RESERVADO,
        reservado_ate=AGORA + timedelta(minutes=3),
    )
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 2}


async def test_visita_de_hoje_antes_do_agora_gasta_capacidade(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 27, 9, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 1}


async def test_ignora_reserva_vencida_expirada_e_reuniao(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 10, tzinfo=SP),
        status=StatusDoAgendamento.RESERVADO,
        reservado_ate=AGORA - timedelta(minutes=1),
    )
    await _gravar(
        session, ana.id, datetime(2026, 8, 27, 12, tzinfo=SP), status=StatusDoAgendamento.EXPIRADO
    )
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 16, tzinfo=SP),
        tipo=TipoDeCompromisso.REUNIAO_REMOTA,
    )
    assert await _contar(session_factory, [ana.id]) == {}


async def test_visita_as_23h30_e_da_data_local(session, session_factory, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    # 23h30 de quinta em Sao Paulo ja e sexta em UTC.
    await _gravar(session, ana.id, datetime(2026, 8, 27, 23, 30, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 1}


async def test_fora_das_datas_e_de_outro_corretor_nao_entra(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    bia = await semear_corretor(email="bia@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 29, 10, tzinfo=SP))
    await _gravar(session, bia.id, datetime(2026, 8, 27, 10, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {}


async def test_sem_corretores_nao_consulta(session_factory) -> None:
    assert await _contar(session_factory, []) == {}


async def test_reservar_grava_o_motivo(session, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    inicio = datetime(2026, 8, 28, 10, tzinfo=SP)
    resultado = await reservar(
        session,
        corretor_id=ana.id,
        channel="whatsapp",
        conversation_key="5511911111111",
        janela=Intervalo(inicio, inicio + timedelta(hours=1)),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=AGORA,
        motivo=MotivoDaAlocacao.SEM_MATCH,
    )
    await session.commit()
    assert isinstance(resultado, Reserva)
    session.expire_all()
    linha = await session.get(Agendamento, resultado.id)
    assert linha is not None
    assert linha.motivo_da_alocacao == MotivoDaAlocacao.SEM_MATCH


async def test_motivo_fora_do_vocabulario_e_recusado(session, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    with pytest.raises(IntegrityError):
        await _gravar_com_motivo(session, ana.id, "PORQUE_SIM")


async def _gravar_com_motivo(session, corretor_id, motivo: str) -> None:
    inicio = datetime(2026, 8, 28, 10, tzinfo=SP)
    session.add(
        Agendamento(
            id=uuid.uuid4(),
            corretor_id=corretor_id,
            channel="whatsapp",
            conversation_key="5511922222222",
            imovel_id=None,
            tipo="VISITA_PRESENCIAL",
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status="CONFIRMADO",
            reservado_ate=inicio,
            criado_em=AGORA,
            confirmado_em=None,
            motivo_da_alocacao=motivo,
        )
    )
    await session.commit()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_visitas_por_dia.py -v --tb=short`
Expected: FAIL — `TypeError: 'motivo_da_alocacao' is an invalid keyword argument for Agendamento`.

- [ ] **Step 3: Write the migration**

`alembic/versions/0045_motivo_da_alocacao.py`:

```python
"""o motivo da alocacao do corretor, gravado no agendamento

TEC-166, RN-11.2. A gerente precisa entender por que aquele corretor foi
escolhido; a categoria mora ao lado do agendamento que ela vai olhar.

**NOT NULL sem valor padrao, e sem backfill.** Nenhum caminho de producao
grava em `agendamentos` ate esta card -- `reservar` nao tem chamador fora dos
testes --, entao nao ha linha antiga para receber um motivo inventado. Se um
dia esta migration encontrar linha, o `ADD COLUMN` reprova, e isso e o certo:
motivo inventado seria pior que a falha.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agendamentos", sa.Column("motivo_da_alocacao", sa.String(24), nullable=False)
    )
    op.create_check_constraint(
        "ck_agendamentos_motivo_da_alocacao",
        "agendamentos",
        "motivo_da_alocacao IN ('MATCH_EXATO','SEM_MATCH','MATCH_SEM_CAPACIDADE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agendamentos_motivo_da_alocacao", "agendamentos", type_="check")
    op.drop_column("agendamentos", "motivo_da_alocacao")
```

Before relying on the name: check how 0044's CHECKs ended up named in the database (`\d agendamentos` via `docker compose exec postgres psql -U <user> -d mobia`, or `SELECT conname FROM pg_constraint WHERE conrelid = 'agendamentos'::regclass`). If `Base.metadata` has a naming convention that prefixes `ck_<tabela>_`, pass only `motivo_da_alocacao` as the name, as 0044 does for its CHECKs. The grep on 24/09/2026 found no `naming_convention` in `domain/messages/models.py`, so the full name is expected to be right.

- [ ] **Step 4: Add the column to the model**

In `src/mobia/domain/agendamento/models.py`, after `confirmado_em`:

```python
    # TEC-166. Categoria de `MotivoDaAlocacao` (`agendamento/vocabulario.py`):
    # por que este corretor, e nao outro. NOT NULL sem padrao -- ver a
    # docstring da migration 0045.
    motivo_da_alocacao: Mapped[str] = mapped_column(String(24), nullable=False)
```

and in `__table_args__`:

```python
        CheckConstraint(
            "motivo_da_alocacao IN ('MATCH_EXATO','SEM_MATCH','MATCH_SEM_CAPACIDADE')",
            name="ck_agendamentos_motivo_da_alocacao",
        ),
```

- [ ] **Step 5: The repository — `motivo`, the shared liveness predicate, and `visitas_por_dia`**

In `src/mobia/domain/agendamento/repositorio.py`:

1. Imports: `from datetime import date, datetime, timedelta`; `from sqlalchemy import Date, and_, cast, func, or_, select, update`; `from sqlalchemy.sql.elements import ColumnElement`; `from typing import Any`; `from collections.abc import Sequence`; `from mobia.app.config import get_settings`; `from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao`.

2. Add, above `class AgendaPostgres`:

```python
def _ocupa_em(momento: datetime) -> ColumnElement[Any]:
    """O compromisso que ocupa o corretor em `momento`. D3 da TEC-168.

    Confirmado ocupa sempre; reservado, so enquanto a reserva vale. Uma
    funcao so para `ocupados` e `visitas_por_dia` (TEC-166, D6): a
    disponibilidade e a capacidade nunca podem discordar sobre uma reserva
    vencida.
    """
    return or_(
        Agendamento.status == StatusDoAgendamento.CONFIRMADO,
        and_(
            Agendamento.status == StatusDoAgendamento.RESERVADO,
            Agendamento.reservado_ate > momento,
        ),
    )
```

3. In `ocupados`, replace the inline `or_(...)` with `_ocupa_em(de)`. The comment above it stays true — keep it.

4. Add the method to `AgendaPostgres`, and update its docstring's first line to say it implements `AgendaDoCorretor` **e** `ContadorDeVisitas`:

```python
    async def visitas_por_dia(
        self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]:
        # A data e a de `inicio` no fuso da imobiliaria, calculada no SQL: uma
        # visita as 23h30 de quinta em Sao Paulo ja e sexta em UTC, e conta
        # para quinta.
        if not corretor_ids:
            return {}
        data_local = cast(func.timezone(get_settings().followup_fuso, Agendamento.inicio), Date)
        # Subconsulta, e nao GROUP BY sobre `data_local` direto: cada uso da
        # expressao vira um bind parameter proprio (`$1`, `$2`), e o Postgres
        # nao reconhece `timezone($2, inicio)` no GROUP BY como a mesma
        # expressao de `timezone($1, inicio)` no SELECT.
        visitas = (
            select(Agendamento.corretor_id.label("corretor_id"), data_local.label("dia"))
            .where(
                Agendamento.corretor_id.in_(corretor_ids),
                Agendamento.tipo == TipoDeCompromisso.VISITA_PRESENCIAL,
                data_local >= de,
                data_local <= ate,
                _ocupa_em(agora),
            )
            .subquery()
        )
        async with self._session_factory() as session:
            linhas = await session.execute(
                select(visitas.c.corretor_id, visitas.c.dia, func.count()).group_by(
                    visitas.c.corretor_id, visitas.c.dia
                )
            )
            return {(corretor_id, dia): total for corretor_id, dia, total in linhas.all()}
```

5. `reservar`: add `motivo: MotivoDaAlocacao` as the last keyword; set `motivo_da_alocacao=str(motivo)` in the `Agendamento(...)`. Add one line to its docstring: "`motivo` e o que `alocar` deu a este corretor (TEC-166); a reserva o grava para a gerente ler depois."

6. `reservar_ou_alternativas`: add `motivo: MotivoDaAlocacao`, pass it to `reservar`. Add to its docstring: "As alternativas continuam no mesmo corretor (D7 da TEC-166): o conflito e sobre um slot dele, e realocar no meio da disputa trocaria o corretor sem que nada na alocacao tivesse mudado."

- [ ] **Step 6: Fix the existing callers in the tests**

- `tests/integration/test_agendamento_repositorio.py`: add `motivo=MotivoDaAlocacao.MATCH_EXATO` to the helper `_reservar` and to every direct `reservar(`/`reservar_ou_alternativas(` call (grep the file for both). Import `MotivoDaAlocacao` from `mobia.domain.agendamento.vocabulario`.
- `tests/integration/test_agendamento_schema.py`: in `_inserir`, add `motivo_da_alocacao` to the column list and `'MATCH_EXATO'` to `VALUES`.
- Grep the whole repo once more: `grep -rn "reservar(\|reservar_ou_alternativas(\|INSERT INTO agendamentos" src tests evals scripts` — every hit must pass a motivo.

- [ ] **Step 7: Run the agendamento integration tests and the migration tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_visitas_por_dia.py tests/integration/test_agendamento_repositorio.py tests/integration/test_agendamento_schema.py -v --tb=short`
Expected: PASS (all). The session fixture `migrar_banco` runs `upgrade head`, so 0045 is applied.

Then: `./.venv/Scripts/python.exe -m pytest tests/integration -k "migra or alembic" --tb=short`
Expected: PASS. If a test checks model-versus-migration drift, it must be satisfied by Step 4.

If dozens of tests fail with `column "motivo_da_alocacao" does not exist`, it is the stale-worker-database trap in CLAUDE.md ("`relation ... does not exist` em dezenas de testes"): check `alembic_version` in the worker database before touching code.

- [ ] **Step 8: Run the three gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0045_motivo_da_alocacao.py src/mobia/domain/agendamento/models.py src/mobia/domain/agendamento/repositorio.py tests/integration/test_visitas_por_dia.py tests/integration/test_agendamento_repositorio.py tests/integration/test_agendamento_schema.py
git commit -m "feat(TEC-166): a reserva grava o motivo da alocacao e o Postgres conta as visitas do dia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Os comentários que diziam "espera a TEC-166"

**Files (each one: read the sentence, decide if it became false, rewrite or leave):**
- `src/mobia/domain/agendamento/janelas.py` (module docstring: "falta a quem atribuir o agendamento (TEC-166)")
- `src/mobia/domain/corretores/vocabulario.py` (`especialidade_de` docstring: "Nasce sem chamador"; `Especialidade` docstring: "a TEC-166 vai mapear")
- `src/mobia/domain/corretores/models.py` (comment on `plantao`: "escolher entre eles e a TEC-166"; the comment near `regioes_atuacao`)
- `src/mobia/domain/notificacao/destinatario.py` (module docstring)
- `src/mobia/domain/handoff/models.py` (comment on `corretor_id`: "alocar e a TEC-166")
- `src/mobia/domain/metricas/filtros.py` (`montar_recorte`: the `FiltroInvalido` message and comment) and `src/mobia/domain/metricas/repositorio.py` (the `recorte.corretor_id` comment)
- `src/mobia/app/config.py` (the comment that mentions TEC-166 near the office-hours window)
- `src/mobia/workers/jobs/process_message.py` (the comment that mentions TEC-166)
- `alembic/versions/0025_corretores.py` — **do not edit**: a migration docstring records what was true when it was written.
- Tests that assert the text: `tests/unit/test_filtros_do_funil.py::test_filtro_por_corretor_e_recusado_enquanto_ninguem_aloca` (asserts `"TEC-166"` in the 422 message).

**What is true after this card** (use this to judge each sentence):
- A allocation rule exists (`alocacao.py::alocar`) and `janelas_alocadas` uses it. **No production path calls either**; the turn still books nothing.
- `especialidade_de` now has a caller (`alocacao.py::criterio_de`).
- The choice between several plantões **for a scheduling** is made (oldest `criado_em`). The choice **for a handoff** (`destinatario_do_handoff`) is unchanged, and it is deliberately still its own rule — this card did not touch it.
- `handoffs.corretor_id` still has no writer. The funnel filter still needs it. Nothing about them changed, so a sentence that says "espera a TEC-166" there is now false: the correct text says it waits for **someone to write `handoffs.corretor_id`**, with no card number (none exists — never invent one).

- [ ] **Step 1: List the references**

Run: `grep -rn "TEC-166" src tests alembic evals scripts`
Expected: the files above, plus the new code from Tasks 1–4 (which is correct and stays).

- [ ] **Step 2: Rewrite each false sentence, in place**

Rules: comments without accents; keep the *why*; say what is still missing instead of pointing to a card that is merged. The filter's 422 message is shown to the dashboard user, so it may keep accents only if the current literal has them — match the existing literal's style exactly.

For the funnel filter, the message must still explain why the filter is refused. Replace the TEC-166 reference with the real reason, e.g. `"o funil ainda nao sabe qual corretor atende cada handoff"`, and update `test_filtro_por_corretor_e_recusado_enquanto_ninguem_aloca` so it asserts the new reason instead of `"TEC-166"`. Rename the test only if its name became false (it did not: nobody allocates handoffs yet).

- [ ] **Step 3: Run the touched unit tests and the comments listing**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_filtros_do_funil.py tests/unit/test_corretores_vocabulario.py tests/unit/test_especialidade_por_ticket.py -v --tb=short`
Expected: PASS

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` and read every `ALTERADO` and `VIZINHO` it lists for the branch. Fix any sentence that the code of Tasks 1–4 made false (e.g. the `reservar` and `AgendaPostgres` docstrings, the `janelas.py` docstring).

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`
Expected: exit 0 (no broken anchors, no new line-number citations).

- [ ] **Step 4: Update the spec status**

In `docs/superpowers/specs/2026-09-24-tec-166-alocar-corretor-design.md`, change `**Status:**` to `implementado`.

- [ ] **Step 5: Run the three gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A src tests docs
git commit -m "docs(TEC-166): os comentarios que esperavam a alocacao dizem o que ainda falta

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Final: suíte inteira, uma vez

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
If it comes back with hundreds of setup `ERROR`s or `CannotConnectNowError`, follow CLAUDE.md "Quando o `-n 8` derruba o Postgres" and run by blocks (`tests/unit`, `tests/integration`, `tests/features`). Record the commit hash with the result.
