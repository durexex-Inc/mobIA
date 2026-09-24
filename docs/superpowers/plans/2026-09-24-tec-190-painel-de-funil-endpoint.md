# Painel de funil — endpoint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar `GET /api/v1/metricas/funil` — as seis etapas da RN-17.2 com conversão, os indicadores da RN-17.1 e os cinco filtros da RN-17.3.

**Architecture:** Um pacote `src/mobia/domain/metricas/` novo, com vocabulário e aritmética puros (testáveis sem banco), um repositório de consultas agregadas e um router fino que só monta a resposta. A coluna `qualificado_em` entra por migration antes de tudo, porque duas etapas dependem dela.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Postgres 16, pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-190-painel-de-funil-design.md`

**Entrega-se sozinho.** O plano do frontend (`2026-09-24-tec-190-painel-de-funil-frontend.md`) consome este endpoint e é executado depois.

## Global Constraints

- **`line-length = 100`**, `target-version = "py313"`, ruff `select = ["E", "F", "I", "UP", "B"]`.
- **Os três gates rodam antes de cada commit**, nesta ordem e neste escopo:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O `mypy` roda **sem argumento** — o escopo mora em `[tool.mypy].files`, e a migration nova passa por ele.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Valor citado segue o valor.
- **Repositório não commita** — o commit é de quem chama.
- **Resposta é `dict[str, object]` em camelCase, montado à mão. Sem `response_model`.**
- **Toda tabela nova em `TABELAS` (`tests/conftest.py`)** — esta card não cria tabela, então nada muda ali.
- **A migration nova é `revision = "0040"`, `down_revision = "0039"`.** Confirme que não existe `0040` antes de fixar.

## D10 — O funil é COORTE, e isto não estava na spec

Decisão tomada ao escrever o plano, e ela precisa virar emenda à spec.

Duas semânticas eram possíveis. **Por atividade** — contar eventos de cada tipo ocorridos no período — a conversão entre etapas pode passar de 100%: um lead recomendado em agosto pode ter nascido em julho, e `Recomendado / Em conversa` daria mais que 1. A RN-17.2 pede "taxa de conversão entre etapas", e uma taxa acima de 100% não é conversão, é erro de leitura.

**Por coorte** — os leads cujo primeiro contato caiu no período, contando quantos *desses* alcançaram cada etapa, inclusive depois do fim do período — a conversão é monotônica e ≤ 100% por construção. É o que a gerente quer dizer com "onde estamos perdendo lead".

**Escolhida: coorte, e todos os indicadores herdam o mesmo recorte** — `conversasAtivas` é quantas da coorte ainda estão `ATIVA`, `taxaQualificacao` é qualificados da coorte sobre o tamanho dela, e as duas médias de tempo são sobre a coorte. Um recorte só, em todo o payload; misturar coorte e atividade no mesmo cartão é o defeito que esta decisão evita.

## Review Focus

Classes de entrada que a spec implica e que nenhuma tarefa exercitaria por si:

1. **Etapa anterior em zero** — `118/0` na conversão. Não pode virar `ZeroDivisionError` nem `0.0`: é `null`, e é uma **terceira** origem de nulo além das duas que a spec nomeia. Pinado na Tarefa 2.
2. **Fronteira do dia e fuso** — `de=2026-08-01` é data, as colunas são `timestamptz`. Interpretar em UTC desloca a fronteira em 3 horas e põe o lead da madrugada no dia errado. Usa `settings.fuso_de_envio`, com intervalo semiaberto. Tarefa 3.
3. **`de` depois de `ate`** — 422 com a razão, nunca um funil vazio que se lê como "nenhum lead". Tarefa 3.
4. **Valor de filtro fora do vocabulário** (`temperatura=MORNA`) — 422 nomeando o valor, nunca zero resultados em silêncio, que a gerente leria como fato do negócio. Tarefa 3.
5. **Período sem lead nenhum** — todas as etapas em zero, `taxaQualificacao` nula (0/0 não é 0%), e **200**, não 404. Tarefa 6.

---

## Estrutura de arquivos

| arquivo | responsabilidade |
| --- | --- |
| `alembic/versions/0040_carimbo_de_qualificacao.py` | a coluna |
| `src/mobia/domain/context/models.py` | a coluna no modelo |
| `src/mobia/domain/context/repositorio.py` | `carimbar_qualificacao` |
| `src/mobia/domain/agente/turno.py` | a chamada, e o comentário que deixa de valer |
| `src/mobia/domain/metricas/vocabulario.py` | os nomes das seis etapas e quais têm fonte |
| `src/mobia/domain/metricas/calculo.py` | conversão entre etapas; aritmética pura |
| `src/mobia/domain/metricas/filtros.py` | o recorte, e a recusa do inválido |
| `src/mobia/domain/metricas/repositorio.py` | as consultas agregadas |
| `src/mobia/api/routes/metricas.py` | a rota |
| `src/mobia/app/main.py` | o registro |

---

### Task 1: `qualificado_em`

**Files:**
- Create: `alembic/versions/0040_carimbo_de_qualificacao.py`, `tests/integration/test_carimbo_de_qualificacao.py`
- Modify: `src/mobia/domain/context/models.py` (perto de `temperatura_forcada_em`), `src/mobia/domain/context/repositorio.py`, `src/mobia/domain/agente/turno.py:2113-2120` e o comentário em `turno.py:2240-2252`

**Interfaces:**
- Produces: `LeadQualification.qualificado_em: Mapped[datetime | None]`; `async def carimbar_qualificacao(session: AsyncSession, *, channel: str, conversation_key: str, quando: datetime) -> bool` — `True` quando carimbou, `False` quando já havia carimbo.

- [ ] **Step 1: Escrever o teste que falha**

`tests/integration/test_carimbo_de_qualificacao.py`:

```python
"""O carimbo da primeira travessia de qualificacao. TEC-190, D2 e D3.

A coluna existe para a metrica RN-17.1, e o comentario de `turno.py` sobre a
reemissao de `lead.qualificado` declarou que a decisao era de quem fosse dono
dessa metrica. E esta card.
"""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import carimbar_qualificacao

CANAL = "whatsapp"
CONVERSA = "5511911112222"
AGORA = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _linha(session) -> None:
    session.add(LeadQualification(channel=CANAL, conversation_key=CONVERSA))
    await session.commit()


async def test_carimba_quando_a_coluna_esta_nula(session) -> None:
    await _linha(session)

    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA
    )
    await session.commit()

    assert carimbou is True
    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em == AGORA


async def test_a_segunda_travessia_nao_move_o_carimbo(session) -> None:
    """A ida-e-volta da TEC-148 conta UMA vez. E a D3 do desenho."""
    await _linha(session)
    await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA
    )
    await session.commit()

    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA + timedelta(days=3)
    )
    await session.commit()

    assert carimbou is False
    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em == AGORA


async def test_lead_sem_linha_nao_cria_linha(session) -> None:
    """O UPDATE nao e upsert: sem linha, nao ha o que carimbar."""
    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=f"55119{uuid.uuid4().hex[:8]}", quando=AGORA
    )
    await session.commit()

    assert carimbou is False


async def test_a_coluna_nasce_nula(session) -> None:
    """Sem backfill: `NULL` e "linha anterior a esta card". Lacuna L1."""
    await _linha(session)

    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em is None
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_carimbo_de_qualificacao.py --tb=short`
Expected: FAIL — `ImportError: cannot import name 'carimbar_qualificacao'`.

- [ ] **Step 3: Escrever a migration**

Confirme primeiro que a `0040` não existe: `ls alembic/versions/ | grep 0040` deve não devolver nada.

`alembic/versions/0040_carimbo_de_qualificacao.py`:

```python
"""quando o lead cruzou a borda da qualificacao

TEC-190, RN-17.1 e RN-17.2. Coluna nulavel e sem backfill: o instante nunca
foi gravado em lugar nenhum, entao nao ha de onde o backfill sair. `NULL`
significa "nao qualificou" ou "qualificou antes desta card", e as duas se
leem igual na metrica -- fora da contagem. Lacuna L1 do desenho.

Sem indice nesta card. O predicado do funil e
`qualificado_em >= :de AND qualificado_em < :ate`, e o teste de latencia da
Tarefa 8 e quem decide se ele precisa de indice -- medir antes, e nao criar
indice por precaucao sobre uma tabela que o painel varre uma vez por minuto.

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("qualificado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "qualificado_em")
```

- [ ] **Step 4: Acrescentar a coluna ao modelo**

Em `src/mobia/domain/context/models.py`, logo depois do bloco de `temperatura_forcada_motivos` e antes de `updated_at`:

```python
    # TEC-190, RN-17.1. Quando o lead cruzou a borda de `esta_qualificado` pela
    # PRIMEIRA vez -- `carimbar_qualificacao` guarda por `qualificado_em IS
    # NULL`, entao a ida-e-volta que a TEC-148 tornou possivel (qualifica,
    # recusa um campo, requalifica) conta uma vez so.
    #
    # E esse "uma vez so" que fecha a lacuna que `turno.py` declarou ao lado do
    # `log.info("lead.qualificado", ...)`: la esta escrito que tornar a
    # emissao idempotente exigia "estado persistido de ja emiti uma vez", e que
    # a decisao era de quem fosse dono da metrica RN-17.1. Esta coluna e esse
    # estado.
    #
    # **`NULL` nao distingue "nunca qualificou" de "qualificou antes da
    # migration 0040"**, e nao ha como distinguir: o instante nao era gravado.
    # A etapa Qualificado do painel conta so a partir da migration, e o numero
    # e baixo nas primeiras semanas sem que nada esteja errado. Lacuna L1.
    #
    # Diferente de `updated_at`, que e o ULTIMO toque: um lead qualificado em
    # julho que responde hoje tem `updated_at` de hoje, e filtrar a etapa por
    # ele poria esse lead no funil de agosto.
    qualificado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 5: Escrever `carimbar_qualificacao`**

Em `src/mobia/domain/context/repositorio.py`, depois de `gravar_estado`:

```python
async def carimbar_qualificacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    quando: datetime,
) -> bool:
    """Grava a hora da PRIMEIRA travessia da borda de qualificacao. TEC-190.

    Devolve `True` quando carimbou e `False` quando nao havia o que carimbar
    -- ou porque a linha ja tem carimbo, ou porque a linha nao existe.

    **A guarda `qualificado_em IS NULL` esta no SQL e nao em Python de
    proposito.** Ela e o que torna a escrita idempotente por lead mesmo com
    dois turnos concorrentes da mesma conversa: um `if linha.qualificado_em is
    None` lido antes do UPDATE seria verdadeiro nos dois, e o segundo moveria
    o carimbo. No WHERE, o segundo UPDATE simplesmente nao casa.

    **Nao e upsert.** Um lead sem linha em `lead_qualification` nao qualificou
    -- `esta_qualificado(None)` e False --, entao criar linha aqui inventaria
    estado. Ver o caminho "Deliberadamente NAO cria linha" de `gravar_estado`.

    Nao commita, como as vizinhas deste modulo.
    """
    resultado = await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
            LeadQualification.qualificado_em.is_(None),
        )
        .values(qualificado_em=quando)
        .returning(LeadQualification.qualificado_em)
        .execution_options(populate_existing=True)
    )
    return resultado.scalar_one_or_none() is not None
```

- [ ] **Step 6: Rodar para ver passar**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_carimbo_de_qualificacao.py --tb=short
```
Expected: PASS, 4 testes.

- [ ] **Step 7: Chamar do turno**

Em `src/mobia/domain/agente/turno.py`, logo depois do `gravar_estado` que termina na linha 2120 e **antes** do comentário de `registrar_recalculo`:

```python
        # TEC-190, D3. O carimbo entra AQUI, dentro da transacao, e nao junto
        # do `log.info("lead.qualificado", ...)` la embaixo. Os dois marcam a
        # mesma travessia e a posicao de cada um segue do que ele e: o log
        # existe para quem le o log, e sai depois do commit porque "logar uma
        # transicao que o rollback desfez e mentir para quem le o log"; a
        # coluna e DADO, e se a transacao volta atras a qualificacao nao
        # aconteceu e o carimbo tem de voltar junto.
        #
        # Nao introduz ordem de lock nova: `gravar_estado`, uma linha acima, ja
        # deixou esta transacao com a linha de `lead_qualification` na mao. Ver
        # os comentarios acima de `aplicar_mudanca_de_intencao` sobre a ordem
        # de aquisicao ser carga e nao acaso.
        if depois_do_estado is not None and esta_qualificado(
            depois_do_estado, _recusados_de(depois_do_estado)
        ):
            await carimbar_qualificacao(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                quando=datetime.now(UTC),
            )
```

Acrescente `carimbar_qualificacao` ao import de `mobia.domain.context.repositorio` no topo do arquivo.

- [ ] **Step 8: Corrigir o comentário que deixou de valer**

Em `turno.py`, no comentário acima do `if not antes and esta_qualificado(...)`, o trecho que hoje diz:

> Isto NAO esta corrigido aqui: tornar a emissao idempotente por lead exige estado persistido de "ja emiti uma vez", que e decisao de quem e dono da metrica RN-17.1, nao desta card -- so fica declarado, para quem ler essa metrica saber que uma travessia de ida-e-volta agora conta duas vezes.

passa a:

```
    # **O LOG continua reemitindo, e a METRICA nao.** A TEC-190, dona da
    # RN-17.1, criou o estado persistido que faltava: `qualificado_em`,
    # carimbado logo acima dentro da transacao, com guarda `IS NULL` no
    # proprio UPDATE. A ida-e-volta -- turno A completa os quatro
    # obrigatorios, turno B recusa um, turno C o devolve -- faz este `if`
    # disparar duas vezes e o carimbo nao se mover. Quem conta lead
    # qualificado le a coluna, nao este log.
```

- [ ] **Step 9: Rodar os testes que tocam o turno**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py tests/integration/test_auditoria_score.py tests/integration/test_carimbo_de_qualificacao.py --tb=short
```
Expected: PASS. Se algum teste de turno reprovar com `ConnectionResetError`, é o `[WinError 64]` do `CLAUDE.md` — rode de novo antes de investigar.

- [ ] **Step 10: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0040_carimbo_de_qualificacao.py src/mobia/domain/context/models.py src/mobia/domain/context/repositorio.py src/mobia/domain/agente/turno.py tests/integration/test_carimbo_de_qualificacao.py
git commit -m "feat(TEC-190): a primeira travessia da qualificacao tem carimbo, e ele nao se move"
```

---

### Task 2: Vocabulário das etapas e a aritmética da conversão

**Files:**
- Create: `src/mobia/domain/metricas/__init__.py`, `src/mobia/domain/metricas/vocabulario.py`, `src/mobia/domain/metricas/calculo.py`, `tests/unit/test_calculo_do_funil.py`

**Interfaces:**
- Produces:
  - `class Etapa(StrEnum)` com `NOVO`, `EM_CONVERSA`, `QUALIFICADO`, `RECOMENDADO`, `AGENDADO`, `HANDOFF_ACEITO`; os valores são os rótulos da RN-17.2 (`"Novo"`, `"Em conversa"`, …).
  - `ETAPAS: tuple[Etapa, ...]` na ordem do funil.
  - `SEM_FONTE: frozenset[Etapa]` — hoje `{Etapa.AGENDADO}`.
  - `INDICADORES_SEM_FONTE: tuple[str, ...]`.
  - `@dataclass(frozen=True) class EtapaDoFunil` com `nome: str`, `quantidade: int | None`, `disponivel: bool`, `conversao_da_anterior: float | None`.
  - `def montar_funil(quantidades: Mapping[Etapa, int]) -> list[EtapaDoFunil]`

- [ ] **Step 1: Escrever o teste que falha**

`tests/unit/test_calculo_do_funil.py`:

```python
"""A aritmetica do funil, sem banco. TEC-190, RN-17.2."""

from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.vocabulario import ETAPAS, Etapa

CHEIO = {
    Etapa.NOVO: 320,
    Etapa.EM_CONVERSA: 268,
    Etapa.QUALIFICADO: 141,
    Etapa.RECOMENDADO: 118,
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


def test_a_etapa_sem_fonte_sai_nula_e_nunca_zero() -> None:
    """D1: zero afirmaria que nenhuma visita foi marcada."""
    agendado = montar_funil(CHEIO)[4]

    assert agendado.nome == "Agendado"
    assert agendado.quantidade is None
    assert agendado.disponivel is False
    assert agendado.conversao_da_anterior is None


def test_a_etapa_depois_da_indisponivel_nao_tem_conversao() -> None:
    """Segunda origem de nulo: a anterior nao tem numero.

    Pular `Agendado` e dividir `Handoff aceito` por `Recomendado` daria um
    numero plausivel e errado.
    """
    handoff = montar_funil(CHEIO)[5]

    assert handoff.quantidade == 39
    assert handoff.conversao_da_anterior is None


def test_anterior_em_zero_da_conversao_nula_e_nao_divisao_por_zero() -> None:
    """Terceira origem de nulo -- a que nem a spec nomeava."""
    funil = montar_funil({**CHEIO, Etapa.EM_CONVERSA: 0, Etapa.QUALIFICADO: 0})

    assert funil[1].quantidade == 0
    assert funil[2].quantidade == 0
    assert funil[2].conversao_da_anterior is None


def test_periodo_sem_lead_nenhum_zera_tudo_sem_estourar() -> None:
    funil = montar_funil({etapa: 0 for etapa in ETAPAS if etapa is not Etapa.AGENDADO})

    assert [e.quantidade for e in funil] == [0, 0, 0, 0, None, 0]
    assert all(e.conversao_da_anterior is None for e in funil)


def test_etapa_disponivel_com_zero_continua_disponivel() -> None:
    """Zero medido NAO e ausencia de fonte -- e a distincao inteira da D1."""
    funil = montar_funil({**CHEIO, Etapa.QUALIFICADO: 0})

    assert funil[2].quantidade == 0
    assert funil[2].disponivel is True
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_calculo_do_funil.py --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.metricas'`.

- [ ] **Step 3: Escrever o vocabulário**

`src/mobia/domain/metricas/__init__.py`: arquivo vazio.

`src/mobia/domain/metricas/vocabulario.py`:

```python
"""As seis etapas do funil e o que ainda nao tem fonte. TEC-190, RN-17.2.

Modulo sem I/O, no molde de `conversa/vocabulario.py` e `handoff/
vocabulario.py`: e o que deixa a regra ser testada em `tests/unit/` sem
Postgres de pe.
"""

from enum import StrEnum


class Etapa(StrEnum):
    """Os seis estagios da RN-17.2, na ordem do funil.

    O VALOR e o rotulo que sai na resposta HTTP, e nao um codigo interno: o
    contrato do SRS (secao 6.6) lista `{"nome": "Novo", ...}`, e manter o
    rotulo aqui evita um segundo mapa de traducao que poderia divergir.
    """

    NOVO = "Novo"
    EM_CONVERSA = "Em conversa"
    QUALIFICADO = "Qualificado"
    RECOMENDADO = "Recomendado"
    AGENDADO = "Agendado"
    HANDOFF_ACEITO = "Handoff aceito"


# A ordem importa: a conversao de cada etapa e sobre a IMEDIATAMENTE anterior
# nesta tupla.
ETAPAS: tuple[Etapa, ...] = tuple(Etapa)

# Nao existe tabela de agendamento neste repo -- marcar visita e RF-11 e
# RF-12, epicos nao construidos. Enquanto for assim, a etapa sai com
# `quantidade: null` e `disponivel: false`, e NUNCA com zero: zero afirmaria
# que nenhuma visita foi marcada no periodo, quando a verdade e que nenhuma e
# registrada em lugar nenhum. Ver a D1 do desenho.
#
# Quando a RF-12 existir, tire `AGENDADO` daqui e escreva a consulta. Nem o
# contrato nem o frontend mudam.
SEM_FONTE: frozenset[Etapa] = frozenset({Etapa.AGENDADO})

# Os indicadores da RN-17.1 que dependem da mesma tabela ausente.
INDICADORES_SEM_FONTE: tuple[str, ...] = (
    "agendamentosCriados",
    "agendamentosConfirmados",
    "agendamentosRealizados",
    "taxaNoShow",
)
```

- [ ] **Step 4: Escrever a aritmética**

`src/mobia/domain/metricas/calculo.py`:

```python
"""A aritmetica do funil. TEC-190, RN-17.2. Sem I/O."""

from collections.abc import Mapping
from dataclasses import dataclass

from mobia.domain.metricas.vocabulario import ETAPAS, SEM_FONTE, Etapa


@dataclass(frozen=True)
class EtapaDoFunil:
    """Uma etapa pronta para a resposta HTTP."""

    nome: str
    quantidade: int | None
    disponivel: bool
    conversao_da_anterior: float | None


def _conversao(anterior: int | None, atual: int | None) -> float | None:
    """A fracao da etapa anterior que chegou nesta, ou `None`.

    **Sao TRES as origens de `None`, e nenhuma delas e zero por cento:**

    1. nao ha etapa anterior (a primeira do funil);
    2. a anterior nao tem numero (`SEM_FONTE`) -- pular a etapa cega e dividir
       pela penultima daria um numero plausivel e errado;
    3. a anterior e zero -- 0 lead nao converteu em nada e tambem nao deixou
       de converter; a fracao nao existe. Devolver 0.0 aqui diria "ninguem
       passou", que e afirmacao diferente de "nao ha o que medir".
    """
    if anterior is None or atual is None or anterior == 0:
        return None
    return atual / anterior


def montar_funil(quantidades: Mapping[Etapa, int]) -> list[EtapaDoFunil]:
    """As seis etapas, sempre as seis, com a conversao entre consecutivas.

    Uma etapa em `SEM_FONTE` sai com `quantidade` nula ainda que `quantidades`
    traga numero para ela -- a ausencia de fonte e propriedade do vocabulario,
    e nao de quem consultou o banco.
    """
    valores: list[int | None] = [
        None if etapa in SEM_FONTE else quantidades.get(etapa, 0) for etapa in ETAPAS
    ]

    return [
        EtapaDoFunil(
            nome=etapa.value,
            quantidade=valores[indice],
            disponivel=etapa not in SEM_FONTE,
            conversao_da_anterior=(
                None if indice == 0 else _conversao(valores[indice - 1], valores[indice])
            ),
        )
        for indice, etapa in enumerate(ETAPAS)
    ]
```

- [ ] **Step 5: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_calculo_do_funil.py --tb=short`
Expected: PASS, 8 testes.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/metricas tests/unit/test_calculo_do_funil.py
git commit -m "feat(TEC-190): as seis etapas e as tres origens de conversao nula"
```

---

### Task 3: O recorte, e a recusa do filtro inválido

**Files:**
- Create: `src/mobia/domain/metricas/filtros.py`, `tests/unit/test_filtros_do_funil.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Recorte` com `inicio: datetime`, `fim: datetime`, `canal: str | None`, `intencao: str | None`, `temperatura: str | None`, `corretor_id: uuid.UUID | None`.
  - `class FiltroInvalido(ValueError)` com atributo `campo: str`.
  - `def montar_recorte(*, de: date, ate: date, fuso: ZoneInfo, canal: str | None = None, intencao: str | None = None, temperatura: str | None = None, corretor_id: uuid.UUID | None = None) -> Recorte`

- [ ] **Step 1: Escrever o teste que falha**

`tests/unit/test_filtros_do_funil.py`:

```python
"""O recorte do painel e a recusa do filtro invalido. TEC-190, RN-17.3."""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.metricas.filtros import FiltroInvalido, montar_recorte

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def test_o_dia_comeca_a_meia_noite_do_fuso_e_nao_de_utc() -> None:
    """Sem isto, o lead da madrugada cai no dia errado.

    Sao Paulo e UTC-3, entao 2026-08-01 00:00 local e 2026-08-01 03:00Z.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.inicio == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)


def test_o_intervalo_e_semiaberto_e_inclui_o_dia_final_inteiro() -> None:
    """`fim` e a meia-noite do dia SEGUINTE, entao 22/08 23:59 entra.

    Um `<=` sobre 22/08 23:59:59 deixaria de fora o que acontecesse no ultimo
    segundo, e um `<= 23:59:59.999999` e a mesma aproximacao escrita pior.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.fim == datetime(2026, 8, 23, 3, 0, tzinfo=UTC)


def test_um_dia_so_e_periodo_valido() -> None:
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 1), fuso=SAO_PAULO)

    assert recorte.fim > recorte.inicio


def test_de_depois_de_ate_e_recusado() -> None:
    """422, e nao funil vazio: vazio se le como "nenhum lead"."""
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(de=date(2026, 8, 22), ate=date(2026, 8, 1), fuso=SAO_PAULO)

    assert erro.value.campo == "de"


def test_temperatura_fora_do_vocabulario_e_recusada() -> None:
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(
            de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, temperatura="MORNA"
        )

    assert erro.value.campo == "temperatura"
    assert "MORNA" in str(erro.value)


def test_intencao_fora_do_vocabulario_e_recusada() -> None:
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(
            de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, intencao="BANANA"
        )

    assert erro.value.campo == "intencao"


def test_os_valores_do_vocabulario_passam() -> None:
    recorte = montar_recorte(
        de=date(2026, 8, 1),
        ate=date(2026, 8, 22),
        fuso=SAO_PAULO,
        temperatura="QUENTE",
        intencao="COMPRA",
    )

    assert recorte.temperatura == "QUENTE"
    assert recorte.intencao == "COMPRA"


def test_canal_e_texto_livre_e_nao_e_recusado() -> None:
    """`messages.channel` e `String(32)` sem CHECK: nao ha vocabulario fechado
    para recusar contra. Hoje so `whatsapp` e produzido; o canal web e a
    TEC-124.
    """
    recorte = montar_recorte(
        de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, canal="web"
    )

    assert recorte.canal == "web"


def test_filtro_ausente_fica_nulo() -> None:
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.canal is None
    assert recorte.intencao is None
    assert recorte.temperatura is None
    assert recorte.corretor_id is None


def test_corretor_id_atravessa() -> None:
    identificador = uuid.uuid4()
    recorte = montar_recorte(
        de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, corretor_id=identificador
    )

    assert recorte.corretor_id == identificador
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_filtros_do_funil.py --tb=short`
Expected: FAIL — módulo `filtros` não existe.

- [ ] **Step 3: Implementar**

`src/mobia/domain/metricas/filtros.py`:

```python
"""O recorte do painel. TEC-190, RN-17.3. Sem I/O."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.temperatura import Temperatura


class FiltroInvalido(ValueError):
    """Um filtro veio com valor que o vocabulario nao tem.

    Carrega o NOME do campo para a rota poder dize-lo no 422. Um 422 generico
    manda quem usa procurar o erro em cinco filtros.
    """

    def __init__(self, campo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.campo = campo


@dataclass(frozen=True)
class Recorte:
    """O periodo em instantes UTC, mais os quatro filtros opcionais.

    `inicio` inclusivo, `fim` EXCLUSIVO.
    """

    inicio: datetime
    fim: datetime
    canal: str | None
    intencao: str | None
    temperatura: str | None
    corretor_id: uuid.UUID | None


def _instante(dia: date, fuso: ZoneInfo) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=fuso).astimezone(UTC)


def montar_recorte(
    *,
    de: date,
    ate: date,
    fuso: ZoneInfo,
    canal: str | None = None,
    intencao: str | None = None,
    temperatura: str | None = None,
    corretor_id: uuid.UUID | None = None,
) -> Recorte:
    """Traduz os filtros da borda em recorte, ou levanta `FiltroInvalido`.

    **A fronteira do dia e a do FUSO, nao a de UTC.** As colunas sao
    `timestamptz`, e Sao Paulo e UTC-3: interpretar `2026-08-01` como
    `00:00Z` poria as tres primeiras horas do dia 1 local no dia 31. O fuso
    vem por parametro e sai de `settings.fuso_de_envio`, que o `config.py`
    declara ser o fuso UNICO da POC, reaproveitado -- e nao um campo novo.

    **O intervalo e semiaberto**: `fim` e a meia-noite do dia SEGUINTE a
    `ate`. Assim o dia final entra inteiro sem a aproximacao de `23:59:59` --
    que perde o ultimo segundo -- nem a de `23:59:59.999999`, que e a mesma
    coisa com mais digitos.

    `canal` NAO e validado: `messages.channel` e `String(32)` sem CHECK, entao
    nao ha vocabulario fechado contra o que recusar.
    """
    if de > ate:
        raise FiltroInvalido("de", f"de={de.isoformat()} e depois de ate={ate.isoformat()}")

    if temperatura is not None and temperatura not in {t.value for t in Temperatura}:
        raise FiltroInvalido(
            "temperatura",
            f"temperatura={temperatura!r} nao e um valor conhecido",
        )

    if intencao is not None and intencao not in {i.value for i in Intencao}:
        raise FiltroInvalido("intencao", f"intencao={intencao!r} nao e um valor conhecido")

    return Recorte(
        inicio=_instante(de, fuso),
        fim=_instante(ate + timedelta(days=1), fuso),
        canal=canal,
        intencao=intencao,
        temperatura=temperatura,
        corretor_id=corretor_id,
    )
```

- [ ] **Step 4: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_filtros_do_funil.py --tb=short`
Expected: PASS, 10 testes.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/metricas/filtros.py tests/unit/test_filtros_do_funil.py
git commit -m "feat(TEC-190): o recorte respeita o fuso e recusa filtro fora do vocabulario"
```

---

### Task 4: As consultas do funil

**Files:**
- Create: `src/mobia/domain/metricas/repositorio.py`, `tests/integration/test_repositorio_de_metricas.py`
- Modify: `tests/conftest.py` (os helpers de semeadura, no fim do arquivo)

**Interfaces:**
- Consumes: `Recorte` (Tarefa 3), `Etapa` (Tarefa 2).
- Produces: `async def contar_etapas(session: AsyncSession, *, recorte: Recorte) -> dict[Etapa, int]`; e os helpers `_falar`, `_lead`, `_recomendar`, `_handoff_aceito` em `tests/conftest.py`, que as Tarefas 5 e 7 consomem.

> **Por que os helpers vão para `tests/conftest.py` e não ficam locais.** O padrão do repo é helper local por arquivo, e ele vale enquanto ninguém mais precisa dele — aqui três arquivos de teste precisam da mesma semeadura de coorte. **Um `from tests.integration.test_repositorio_de_metricas import _lead` NÃO funciona**: `tests/` não é pacote e não está em `sys.path` por esse nome. O único caminho comprovado neste repo é `from conftest import ...`, que 15 arquivos já usam (por exemplo `_entrada_do_lead` em `test_apresentacao_no_turno.py`) e que só funciona porque, no import mode `prepend`, existe UM módulo de topo chamado `conftest`.

- [ ] **Step 1: Pôr os helpers de semeadura no `tests/conftest.py`**

No fim de `tests/conftest.py`, depois das fixtures. São helpers, não fixtures — ficam aqui só porque este é o único módulo que três arquivos de teste conseguem importar.

```python
# --- Semeadura do painel de funil (TEC-190) -------------------------------
#
# Helpers e nao fixtures, e aqui e nao num modulo proprio: `tests/` nao e
# pacote, entao `from tests.integration.x import y` nao resolve. O caminho
# comprovado e `from conftest import ...`, que so funciona porque no import
# mode `prepend` existe UM modulo de topo chamado `conftest`. Mesma razao
# pela qual nao pode haver um segundo conftest.py em subdiretorio.

_CANAL_DO_FUNIL = "whatsapp"

# O instante padrao de nascimento. Os testes que medem a FRONTEIRA do periodo
# passam `nasceu_em` explicito; os que nao a medem herdam este, que cai no
# meio de agosto de 2026 -- dentro do recorte que todos eles usam.
_NASCEU_PADRAO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


async def _falar(
    session: AsyncSession,
    *,
    conversa: str,
    em: datetime,
    canal: str = _CANAL_DO_FUNIL,
    direcao: str = MessageDirection.INBOUND,
) -> uuid.UUID:
    """Uma fala, na direcao pedida, no instante pedido."""
    identificador = uuid.uuid4()
    entrada = direcao == MessageDirection.INBOUND
    session.add(
        Message(
            id=identificador,
            channel=canal,
            provider_message_id=f"wamid.{identificador.hex[:12]}",
            sender_external_id=conversa if entrada else "222222222",
            recipient_external_id="222222222" if entrada else conversa,
            conversation_key=conversa,
            role=MessageRole.LEAD if entrada else MessageRole.AGENTE,
            direction=direcao,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=em,
        )
    )
    return identificador


async def _lead(
    session: AsyncSession,
    *,
    conversa: str,
    nasceu_em: datetime = _NASCEU_PADRAO,
    canal: str = _CANAL_DO_FUNIL,
    falas: int = 1,
    qualificado_em: datetime | None = None,
    temperatura: str | None = None,
    intencao: str | None = None,
) -> None:
    """Um lead com `falas` mensagens de entrada, a primeira em `nasceu_em`.

    A linha de `lead_qualification` so nasce quando algum dos tres campos dela
    foi pedido -- e o que `gravar_estado` faz em producao, onde um turno sem
    campo nenhum "deliberadamente NAO cria linha".
    """
    for numero in range(falas):
        await _falar(
            session, conversa=conversa, em=nasceu_em + timedelta(minutes=numero), canal=canal
        )
    session.add(Conversa(channel=canal, conversation_key=conversa, status=Status.ATIVA))
    if qualificado_em is not None or temperatura is not None or intencao is not None:
        session.add(
            LeadQualification(
                channel=canal,
                conversation_key=conversa,
                intencao=intencao,
                regiao="vila mariana",
                urgencia=Urgencia.IMEDIATA.value,
                temperatura=temperatura,
                qualificado_em=qualificado_em,
            )
        )
    await session.commit()


async def _recomendar(session: AsyncSession, *, conversa: str, em: datetime) -> None:
    """Uma ficha apresentada ao lead. O imovel e novo a cada chamada porque
    `imoveis.codigo` e UNIQUE.
    """
    imovel = Imovel(id=uuid.uuid4(), codigo=f"AP{uuid.uuid4().hex[:8]}")
    session.add(imovel)
    await session.flush()
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=_CANAL_DO_FUNIL,
            conversation_key=conversa,
            imovel_id=imovel.id,
            score_match=Decimal("0.900"),
            motivo_match="bate",
            apresentado_em=em,
        )
    )
    await session.commit()


async def _handoff_aceito(
    session: AsyncSession,
    *,
    conversa: str,
    em: datetime,
    corretor_id: uuid.UUID | None = None,
    sla_limite_em: datetime | None = None,
    ja_aceito: bool = True,
) -> None:
    """Um handoff, aceito por omissao.

    `sla_limite_em=None` e o handoff escalado sem destinatario da Emenda E-02
    da RN-16.3 -- e o caso que a taxa de SLA tem de excluir do denominador.
    """
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel=_CANAL_DO_FUNIL,
            conversation_key=conversa,
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status="ACEITO" if ja_aceito else "PENDENTE",
            corretor_id=corretor_id,
            aceito_em=em if ja_aceito else None,
            sla_limite_em=sla_limite_em,
            criado_em=em - timedelta(minutes=10),
            atualizado_em=em,
        )
    )
    await session.commit()
```

Acrescente ao topo de `tests/conftest.py` os imports que faltarem: `uuid`, `Decimal`, `timedelta`, e `Recomendacao`, `Imovel`, `LeadQualification`, `Conversa`, `Status`, `Handoff`, `Urgencia`, `Message`, `MessageContentType`, `MessageDirection`, `MessageRole`, `MessageStatus`, `aad_de`, `encrypt`.

- [ ] **Step 2: Escrever o teste que falha**

`tests/integration/test_repositorio_de_metricas.py`:

```python
"""As contagens do funil contra o banco. TEC-190, RN-17.2 e D10 (coorte)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import _handoff_aceito, _lead, _recomendar

from mobia.domain.agente.schemas import Intencao
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import contar_etapas
from mobia.domain.metricas.vocabulario import Etapa

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
FORA = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=canal,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=conversa,
            recipient_external_id="222222222",
            conversation_key=conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=em,
        )
    )
    return identificador


async def _lead(
    session,
    *,
    conversa: str,
    nasceu_em: datetime = DENTRO,
    canal: str = CANAL,
    falas: int = 1,
    qualificado_em: datetime | None = None,
    temperatura: str | None = None,
    intencao: str | None = None,
) -> None:
    """Um lead com `falas` mensagens, a primeira em `nasceu_em`."""
    for numero in range(falas):
        await _falar(
            session, conversa=conversa, em=nasceu_em + timedelta(minutes=numero), canal=canal
        )
    session.add(Conversa(channel=canal, conversation_key=conversa, status=Status.ATIVA))
    if qualificado_em is not None or temperatura is not None or intencao is not None:
        session.add(
            LeadQualification(
                channel=canal,
                conversation_key=conversa,
                intencao=intencao,
                regiao="vila mariana",
                urgencia=Urgencia.IMEDIATA.value,
                temperatura=temperatura,
                qualificado_em=qualificado_em,
            )
        )
    await session.commit()


async def _recomendar(session, *, conversa: str, em: datetime) -> None:
    imovel = Imovel(id=uuid.uuid4(), codigo=f"AP{uuid.uuid4().hex[:8]}")
    session.add(imovel)
    await session.flush()
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=conversa,
            imovel_id=imovel.id,
            score_match=0.9,
            motivo_match="bate",
            apresentado_em=em,
        )
    )
    await session.commit()


async def _handoff_aceito(session, *, conversa: str, em: datetime, corretor_id=None) -> None:
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=conversa,
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status="ACEITO",
            corretor_id=corretor_id,
            aceito_em=em,
            sla_limite_em=em + timedelta(hours=1),
            criado_em=em - timedelta(minutes=10),
            atualizado_em=em,
        )
    )
    await session.commit()


async def test_a_coorte_e_quem_nasceu_no_periodo(session) -> None:
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _lead(session, conversa="5511900000002", nasceu_em=FORA)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 1


async def test_em_conversa_exige_mais_de_uma_fala_do_lead(session) -> None:
    await _lead(session, conversa="5511900000001", falas=1)
    await _lead(session, conversa="5511900000002", falas=3)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 2
    assert etapas[Etapa.EM_CONVERSA] == 1


async def test_qualificado_sai_do_carimbo_e_nao_de_updated_at(session) -> None:
    await _lead(session, conversa="5511900000001", qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000002")

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.QUALIFICADO] == 1


async def test_lead_da_coorte_que_qualificou_depois_do_periodo_conta(session) -> None:
    """Coorte: a etapa mede se o lead CHEGOU la, nao quando. D10."""
    await _lead(
        session,
        conversa="5511900000001",
        nasceu_em=DENTRO,
        qualificado_em=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.QUALIFICADO] == 1


async def test_recomendado_conta_quem_recebeu_ficha(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _recomendar(session, conversa="5511900000001", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.RECOMENDADO] == 1


async def test_duas_recomendacoes_para_o_mesmo_lead_contam_um(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _recomendar(session, conversa="5511900000001", em=DENTRO)
    await _recomendar(session, conversa="5511900000001", em=DENTRO + timedelta(hours=1))

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.RECOMENDADO] == 1


async def test_handoff_aceito_conta_so_o_aceito(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _handoff_aceito(session, conversa="5511900000001", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.HANDOFF_ACEITO] == 1


async def test_agendado_nao_aparece_nas_contagens(session) -> None:
    """Nao ha consulta para ele -- o `montar_funil` e quem poe o nulo."""
    await _lead(session, conversa="5511900000001")

    etapas = await contar_etapas(session, recorte=_recorte())

    assert Etapa.AGENDADO not in etapas


async def test_filtro_por_canal_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", canal="whatsapp")
    await _lead(session, conversa="5511900000002", canal="web")

    etapas = await contar_etapas(session, recorte=_recorte(canal="web"))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_temperatura_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura="QUENTE")
    await _lead(session, conversa="5511900000002", temperatura="FRIO")

    etapas = await contar_etapas(session, recorte=_recorte(temperatura="QUENTE"))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_intencao_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", intencao=Intencao.COMPRA.value)
    await _lead(session, conversa="5511900000002", intencao=Intencao.ALUGUEL.value)

    etapas = await contar_etapas(session, recorte=_recorte(intencao=Intencao.COMPRA.value))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_corretor_alcanca_as_etapas_anteriores(session) -> None:
    """D6: o funil e o dos leads QUE ACABARAM com aquele corretor.

    O lead nao tem dono antes do repasse, entao filtrar por corretor conta a
    mesma conversa nos estagios anteriores ao handoff dele.
    """
    corretor = uuid.uuid4()
    await _lead(session, conversa="5511900000001", falas=3)
    await _lead(session, conversa="5511900000002", falas=3)
    await _handoff_aceito(session, conversa="5511900000001", em=DENTRO, corretor_id=corretor)
    await _handoff_aceito(session, conversa="5511900000002", em=DENTRO, corretor_id=uuid.uuid4())

    etapas = await contar_etapas(session, recorte=_recorte(corretor_id=corretor))

    assert etapas[Etapa.NOVO] == 1
    assert etapas[Etapa.EM_CONVERSA] == 1
    assert etapas[Etapa.HANDOFF_ACEITO] == 1


async def test_lead_sem_handoff_some_do_filtro_por_corretor(session) -> None:
    """Lacuna L2, escrita como teste para nao ser descoberta como surpresa."""
    await _lead(session, conversa="5511900000001")

    etapas = await contar_etapas(session, recorte=_recorte(corretor_id=uuid.uuid4()))

    assert etapas[Etapa.NOVO] == 0


async def test_periodo_sem_lead_devolve_zeros_e_nao_erro(session) -> None:
    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 0
    assert etapas[Etapa.HANDOFF_ACEITO] == 0


async def test_a_fronteira_do_dia_e_a_do_fuso(session) -> None:
    """2026-08-01 01:00Z e 31/07 22:00 em Sao Paulo: esta FORA de agosto."""
    await _lead(session, conversa="5511900000001", nasceu_em=datetime(2026, 8, 1, 1, 0, tzinfo=UTC))
    await _lead(session, conversa="5511900000002", nasceu_em=datetime(2026, 8, 1, 5, 0, tzinfo=UTC))

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 1
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_de_metricas.py --tb=short`
Expected: FAIL — `ImportError: cannot import name 'contar_etapas'`.

- [ ] **Step 4: Implementar**

`src/mobia/domain/metricas/repositorio.py`:

```python
"""As consultas agregadas do painel. TEC-190, RN-17.1 e RN-17.2.

**Todo numero deste modulo e sobre a COORTE** -- os leads cujo PRIMEIRO
contato caiu no periodo --, e nao sobre eventos ocorridos no periodo. Ver a
D10 do plano: por atividade, um lead recomendado em agosto que nasceu em
julho faria `Recomendado / Em conversa` passar de 100%, e a RN-17.2 pede uma
taxa de conversao, nao um numero acima de um.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos dez repositorios deste repo.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import Recomendacao
from mobia.domain.context.models import LeadQualification
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.metricas.filtros import Recorte
from mobia.domain.metricas.vocabulario import Etapa

# O status de handoff que conta como aceito. Nao e enum importado porque
# `handoff/vocabulario.py` nomeia o ciclo inteiro e so este valor interessa
# aqui; ver `StatusDoHandoff` la se a lista crescer.
_ACEITO = "ACEITO"


def _coorte(recorte: Recorte) -> Select[tuple[str, str]]:
    """As conversas cujo PRIMEIRO contato caiu no periodo, ja filtradas.

    `conversas` nao tem `criado_em` -- as colunas dela sao `channel`,
    `conversation_key`, `status`, `motivo_do_encerramento` e `encerrada_em` --,
    entao o nascimento do lead sai da primeira linha em `messages`, que e a
    unica tabela com esse instante.
    """
    nascimento = (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at).label("nasceu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )

    consulta = select(nascimento.c.channel, nascimento.c.conversation_key).where(
        nascimento.c.nasceu_em >= recorte.inicio,
        nascimento.c.nasceu_em < recorte.fim,
    )

    if recorte.canal is not None:
        consulta = consulta.where(nascimento.c.channel == recorte.canal)

    if recorte.intencao is not None or recorte.temperatura is not None:
        consulta = consulta.join(
            LeadQualification,
            (LeadQualification.channel == nascimento.c.channel)
            & (LeadQualification.conversation_key == nascimento.c.conversation_key),
        )
        if recorte.intencao is not None:
            consulta = consulta.where(LeadQualification.intencao == recorte.intencao)
        if recorte.temperatura is not None:
            consulta = consulta.where(LeadQualification.temperatura == recorte.temperatura)

    if recorte.corretor_id is not None:
        # D6 e lacuna L2: `corretor_id` so existe em `handoffs`, entao o lead
        # que ainda nao foi repassado nao aparece em filtro de corretor
        # nenhum. O funil filtrado e o dos leads que ACABARAM com ele.
        consulta = consulta.join(
            Handoff,
            (Handoff.channel == nascimento.c.channel)
            & (Handoff.conversation_key == nascimento.c.conversation_key),
        ).where(Handoff.corretor_id == recorte.corretor_id)

    return consulta


async def _quantos(session: AsyncSession, consulta: Select[tuple[str, str]]) -> int:
    alvo = consulta.distinct().subquery()
    return int((await session.execute(select(func.count()).select_from(alvo))).scalar_one())


async def contar_etapas(session: AsyncSession, *, recorte: Recorte) -> dict[Etapa, int]:
    """Quantos da coorte alcancaram cada etapa. `AGENDADO` nao esta aqui.

    A ausencia de `AGENDADO` no dicionario e deliberada e nao um esquecimento:
    nao existe tabela de agendamento, e quem poe o `None` na resposta e
    `montar_funil`, a partir de `SEM_FONTE`. Uma chave com zero aqui viraria
    zero la, que e exatamente o que a D1 recusa.
    """
    coorte = _coorte(recorte).subquery()

    novos = await _quantos(session, _coorte(recorte))

    # "Em conversa" e o lead que falou mais de uma vez: uma fala so e o
    # primeiro contato, que ja e a etapa Novo. Sem este piso, as duas etapas
    # dariam sempre o mesmo numero e a conversao entre elas seria 100% fixo.
    em_conversa = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key)
        .join(
            Message,
            (Message.channel == coorte.c.channel)
            & (Message.conversation_key == coorte.c.conversation_key),
        )
        .where(Message.direction == MessageDirection.INBOUND)
        .group_by(coorte.c.channel, coorte.c.conversation_key)
        .having(func.count(Message.id) > 1),
    )

    qualificados = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            LeadQualification,
            (LeadQualification.channel == coorte.c.channel)
            & (LeadQualification.conversation_key == coorte.c.conversation_key)
            & LeadQualification.qualificado_em.is_not(None),
        ),
    )

    recomendados = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            Recomendacao,
            (Recomendacao.channel == coorte.c.channel)
            & (Recomendacao.conversation_key == coorte.c.conversation_key),
        ),
    )

    aceitos = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            Handoff,
            (Handoff.channel == coorte.c.channel)
            & (Handoff.conversation_key == coorte.c.conversation_key)
            & (Handoff.status == _ACEITO),
        ),
    )

    return {
        Etapa.NOVO: novos,
        Etapa.EM_CONVERSA: em_conversa,
        Etapa.QUALIFICADO: qualificados,
        Etapa.RECOMENDADO: recomendados,
        Etapa.HANDOFF_ACEITO: aceitos,
    }
```

- [ ] **Step 5: Conferir os imports**

`Conversa` e `Status` **não** são usados nesta tarefa — eles entram na Tarefa 5. Não os importe agora: o `ruff` reprova import não usado (`F401`) e o gate roda antes do commit.

- [ ] **Step 6: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_de_metricas.py --tb=short`
Expected: PASS, 15 testes.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/conftest.py src/mobia/domain/metricas/repositorio.py tests/integration/test_repositorio_de_metricas.py
git commit -m "feat(TEC-190): o funil conta a coorte que nasceu no periodo"
```

---

### Task 5: Os indicadores da RN-17.1

**Files:**
- Modify: `src/mobia/domain/metricas/repositorio.py`
- Create: `tests/integration/test_indicadores_de_metricas.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Indicadores` com `conversas_ativas: int`, `taxa_qualificacao: float | None`, `distribuicao_por_temperatura: dict[str, int]`, `tempo_medio_primeira_resposta_seg: float | None`, `tempo_medio_qualificacao_seg: float | None`, `sla_handoff_cumprido_pct: float | None`; e `async def calcular_indicadores(session: AsyncSession, *, recorte: Recorte, novos: int) -> Indicadores`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/integration/test_indicadores_de_metricas.py`:

```python
"""Os indicadores da RN-17.1 contra o banco. TEC-190."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import _falar, _lead

from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa

CANAL = "whatsapp"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)


async def _indicadores(session, **extra):
    recorte = _recorte(**extra)
    etapas = await contar_etapas(session, recorte=recorte)
    return await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])


async def _responder(session, *, conversa: str, em: datetime) -> None:
    """A saida do agente. `_falar` do conftest ja sabe montar as duas direcoes."""
    await _falar(session, conversa=conversa, em=em, direcao=MessageDirection.OUTBOUND)
    await session.commit()


async def test_conversas_ativas_conta_so_as_nao_encerradas(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    conversa = await session.get(Conversa, (CANAL, "5511900000002"))
    assert conversa is not None
    conversa.status = Status.ENCERRADA
    conversa.motivo_do_encerramento = MotivoDoEncerramento.INATIVIDADE
    conversa.encerrada_em = DENTRO
    await session.commit()

    indicadores = await _indicadores(session)

    assert indicadores.conversas_ativas == 1


async def test_taxa_de_qualificacao_e_sobre_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000002")
    await _lead(session, conversa="5511900000003")
    await _lead(session, conversa="5511900000004")

    indicadores = await _indicadores(session)

    assert indicadores.taxa_qualificacao == 0.25


async def test_coorte_vazia_da_taxa_nula_e_nao_zero(session) -> None:
    """0/0 nao e 0%. Item 5 do Review Focus."""
    indicadores = await _indicadores(session)

    assert indicadores.taxa_qualificacao is None


async def test_distribuicao_por_temperatura_traz_as_faixas_presentes(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura="QUENTE")
    await _lead(session, conversa="5511900000002", temperatura="QUENTE")
    await _lead(session, conversa="5511900000003", temperatura="FRIO")

    indicadores = await _indicadores(session)

    assert indicadores.distribuicao_por_temperatura == {"QUENTE": 2, "FRIO": 1}


async def test_lead_sem_temperatura_nao_entra_na_distribuicao(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura=None)

    indicadores = await _indicadores(session)

    assert indicadores.distribuicao_por_temperatura == {}


async def test_tempo_de_primeira_resposta_e_da_primeira_fala_ate_a_primeira_saida(
    session,
) -> None:
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _responder(session, conversa="5511900000001", em=DENTRO + timedelta(seconds=30))

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_primeira_resposta_seg == 30.0


async def test_lead_sem_resposta_nao_entra_na_media(session) -> None:
    """Media sobre quem FOI respondido: incluir o nao respondido como zero
    baixaria a media justamente quando o atendimento esta pior.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _responder(session, conversa="5511900000001", em=DENTRO + timedelta(seconds=30))
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO)

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_primeira_resposta_seg == 30.0


async def test_tempo_de_qualificacao_e_do_nascimento_ate_o_carimbo(session) -> None:
    await _lead(
        session,
        conversa="5511900000001",
        nasceu_em=DENTRO,
        qualificado_em=DENTRO + timedelta(minutes=10),
    )

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_qualificacao_seg == 600.0


async def test_ninguem_qualificado_da_tempo_nulo(session) -> None:
    await _lead(session, conversa="5511900000001")

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_qualificacao_seg is None


async def test_sla_exclui_o_handoff_sem_limite_do_denominador(session) -> None:
    """Emenda E-01 da RN-16.3: `sla_limite_em` nulo sai `dentroDoSla` true por
    VACUIDADE, nunca por pontualidade. Incluir infla a taxa.
    """
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _lead(session, conversa="5511900000003")
    # No prazo.
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key="5511900000001",
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status="ACEITO",
            aceito_em=DENTRO,
            sla_limite_em=DENTRO + timedelta(hours=1),
            criado_em=DENTRO,
            atualizado_em=DENTRO,
        )
    )
    # Fora do prazo.
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key="5511900000002",
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status="ACEITO",
            aceito_em=DENTRO + timedelta(hours=2),
            sla_limite_em=DENTRO + timedelta(hours=1),
            criado_em=DENTRO,
            atualizado_em=DENTRO,
        )
    )
    # Escalado sem destinatario: `sla_limite_em` nulo para sempre.
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key="5511900000003",
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status="ACEITO",
            aceito_em=DENTRO,
            sla_limite_em=None,
            criado_em=DENTRO,
            atualizado_em=DENTRO,
        )
    )
    await session.commit()

    indicadores = await _indicadores(session)

    # 1 de 2, e nao 2 de 3.
    assert indicadores.sla_handoff_cumprido_pct == 0.5


async def test_sem_handoff_com_prazo_a_taxa_e_nula(session) -> None:
    await _lead(session, conversa="5511900000001")

    indicadores = await _indicadores(session)

    assert indicadores.sla_handoff_cumprido_pct is None
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_indicadores_de_metricas.py --tb=short`
Expected: FAIL — `ImportError: cannot import name 'calcular_indicadores'`.

- [ ] **Step 3: Implementar**

Acrescente a `src/mobia/domain/metricas/repositorio.py` (e traga de volta os imports de `Conversa` e `Status`, mais `dataclass`):

```python
@dataclass(frozen=True)
class Indicadores:
    """Os indicadores da RN-17.1 que tem fonte.

    Os quatro de agendamento NAO estao aqui: nao ha tabela, e quem os poe
    nulos na resposta e a rota, a partir de `INDICADORES_SEM_FONTE`.

    **Nulo e "nao ha o que medir", e nunca zero.** Uma coorte vazia da
    `taxa_qualificacao` nula porque 0/0 nao e 0% -- dizer 0% afirmaria que
    ninguem qualificou, quando nao houve ninguem.
    """

    conversas_ativas: int
    taxa_qualificacao: float | None
    distribuicao_por_temperatura: dict[str, int]
    tempo_medio_primeira_resposta_seg: float | None
    tempo_medio_qualificacao_seg: float | None
    sla_handoff_cumprido_pct: float | None


async def calcular_indicadores(
    session: AsyncSession, *, recorte: Recorte, novos: int
) -> Indicadores:
    """Os indicadores da RN-17.1, todos sobre a mesma coorte da D10.

    `novos` vem de fora, ja contado por `contar_etapas`: e o denominador da
    taxa de qualificacao, e recontar aqui seria uma segunda consulta com a
    mesma resposta.
    """
    coorte = _coorte(recorte).subquery()

    ativas = int(
        (
            await session.execute(
                select(func.count())
                .select_from(coorte)
                .join(
                    Conversa,
                    (Conversa.channel == coorte.c.channel)
                    & (Conversa.conversation_key == coorte.c.conversation_key),
                )
                .where(Conversa.status == Status.ATIVA)
            )
        ).scalar_one()
    )

    qualificados = int(
        (
            await session.execute(
                select(func.count())
                .select_from(coorte)
                .join(
                    LeadQualification,
                    (LeadQualification.channel == coorte.c.channel)
                    & (LeadQualification.conversation_key == coorte.c.conversation_key),
                )
                .where(LeadQualification.qualificado_em.is_not(None))
            )
        ).scalar_one()
    )

    temperaturas = {
        faixa: int(quantos)
        for faixa, quantos in (
            await session.execute(
                select(LeadQualification.temperatura, func.count())
                .select_from(coorte)
                .join(
                    LeadQualification,
                    (LeadQualification.channel == coorte.c.channel)
                    & (LeadQualification.conversation_key == coorte.c.conversation_key),
                )
                .where(LeadQualification.temperatura.is_not(None))
                .group_by(LeadQualification.temperatura)
            )
        ).all()
    }

    # Por lead: o instante da primeira fala dele e o da primeira saida nossa.
    # `MIN` dos dois na mesma agregacao, e a media das diferencas so de quem
    # tem os dois -- o lead nunca respondido fica FORA da media, porque
    # conta-lo como zero baixaria o indicador justamente quando o atendimento
    # esta pior.
    por_lead = (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at)
            .filter(Message.direction == MessageDirection.INBOUND)
            .label("falou_em"),
            func.min(Message.created_at)
            .filter(Message.direction == MessageDirection.OUTBOUND)
            .label("respondeu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )
    primeira_resposta = (
        await session.execute(
            select(
                func.avg(
                    func.extract("epoch", por_lead.c.respondeu_em - por_lead.c.falou_em)
                )
            )
            .select_from(coorte)
            .join(
                por_lead,
                (por_lead.c.channel == coorte.c.channel)
                & (por_lead.c.conversation_key == coorte.c.conversation_key),
            )
            .where(por_lead.c.respondeu_em.is_not(None), por_lead.c.falou_em.is_not(None))
        )
    ).scalar_one_or_none()

    nascimento = (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at).label("nasceu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )
    ate_qualificar = (
        await session.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch", LeadQualification.qualificado_em - nascimento.c.nasceu_em
                    )
                )
            )
            .select_from(coorte)
            .join(
                nascimento,
                (nascimento.c.channel == coorte.c.channel)
                & (nascimento.c.conversation_key == coorte.c.conversation_key),
            )
            .join(
                LeadQualification,
                (LeadQualification.channel == coorte.c.channel)
                & (LeadQualification.conversation_key == coorte.c.conversation_key),
            )
            .where(LeadQualification.qualificado_em.is_not(None))
        )
    ).scalar_one_or_none()

    # **O denominador exclui `sla_limite_em IS NULL`**, e isto nao e escolha
    # desta card: a Emenda E-01 da RN-16.3 (TEC-178) decidiu e escreveu para
    # quem fosse calcular esta metrica. O handoff escalado sem destinatario
    # tem `sla_limite_em` nulo para sempre, e `dentroDoSla` sai true por
    # VACUIDADE, nunca por pontualidade -- inclui-lo infla a taxa.
    com_prazo = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Handoff.aceito_em <= Handoff.sla_limite_em),
            )
            .select_from(coorte)
            .join(
                Handoff,
                (Handoff.channel == coorte.c.channel)
                & (Handoff.conversation_key == coorte.c.conversation_key),
            )
            .where(Handoff.aceito_em.is_not(None), Handoff.sla_limite_em.is_not(None))
        )
    ).one()
    total_com_prazo, no_prazo = int(com_prazo[0]), int(com_prazo[1])

    return Indicadores(
        conversas_ativas=ativas,
        taxa_qualificacao=(qualificados / novos) if novos else None,
        distribuicao_por_temperatura=temperaturas,
        tempo_medio_primeira_resposta_seg=(
            float(primeira_resposta) if primeira_resposta is not None else None
        ),
        tempo_medio_qualificacao_seg=(
            float(ate_qualificar) if ate_qualificar is not None else None
        ),
        sla_handoff_cumprido_pct=(no_prazo / total_com_prazo) if total_com_prazo else None,
    )
```

- [ ] **Step 4: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_indicadores_de_metricas.py --tb=short`
Expected: PASS, 11 testes.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/metricas/repositorio.py tests/integration/test_indicadores_de_metricas.py
git commit -m "feat(TEC-190): os indicadores da RN-17.1, com o SLA excluindo prazo nulo"
```

---

### Task 6: A rota

**Files:**
- Create: `src/mobia/api/routes/metricas.py`, `tests/integration/test_rota_de_metricas.py`
- Modify: `src/mobia/app/main.py`

**Interfaces:**
- Consumes: tudo das Tarefas 2 a 5.
- Produces: `GET /api/v1/metricas/funil`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/integration/test_rota_de_metricas.py`:

```python
"""O endpoint do painel de funil. TEC-190, RF-17."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app

TOKEN = "token-de-teste-de-metricas"
ROTA = "/api/v1/metricas/funil"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-31"}


@pytest.fixture
async def app_com_token(monkeypatch: Any, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `app_com_token` em `test_rota_de_corretores.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_sem_token_e_403(app_com_token) -> None:
    resposta = await app_com_token.get(ROTA, params=PERIODO)

    assert resposta.status_code == 403


async def test_periodo_sem_lead_devolve_200_com_as_seis_etapas(app_com_token) -> None:
    """Item 5 do Review Focus: vazio e 200, nunca 404."""
    resposta = await app_com_token.get(
        ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["nome"] for e in corpo["etapas"]] == [
        "Novo",
        "Em conversa",
        "Qualificado",
        "Recomendado",
        "Agendado",
        "Handoff aceito",
    ]
    assert corpo["indicadores"]["taxaQualificacao"] is None


async def test_a_etapa_agendado_sai_indisponivel(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN}
    )

    agendado = next(e for e in resposta.json()["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] is None
    assert agendado["disponivel"] is False


async def test_os_quatro_indicadores_de_visita_saem_nulos_e_listados(app_com_token) -> None:
    corpo = (
        await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})
    ).json()

    assert corpo["indisponiveis"] == [
        "agendamentosCriados",
        "agendamentosConfirmados",
        "agendamentosRealizados",
        "taxaNoShow",
    ]
    for chave in corpo["indisponiveis"]:
        assert corpo["indicadores"][chave] is None


async def test_de_depois_de_ate_e_422_nomeando_o_campo(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA,
        params={"de": "2026-08-31", "ate": "2026-08-01"},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 422
    assert "de" in resposta.json()["detail"]


async def test_temperatura_invalida_e_422_e_nao_funil_vazio(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA,
        params={**PERIODO, "temperatura": "MORNA"},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 422
    assert "MORNA" in resposta.json()["detail"]


async def test_data_malformada_e_422(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA, params={"de": "ontem", "ate": "2026-08-31"}, headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 422


async def test_periodo_e_obrigatorio(app_com_token) -> None:
    resposta = await app_com_token.get(ROTA, headers={"X-Admin-Token": TOKEN})

    assert resposta.status_code == 422
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_metricas.py --tb=short`
Expected: FAIL — 404 em todas (a rota não existe).

- [ ] **Step 3: Implementar a rota**

`src/mobia/api/routes/metricas.py`:

```python
"""O painel de funil. TEC-190, RF-17 e RN-17.1 a RN-17.3.

**Guardado pelo `exigir_admin`, e nao por papel GERENTE.** O SRS (secao 6.6)
preve Bearer JWT com papel, e ele nao existe: `corretores.gerente` e booleana
de roteamento de escalada de SLA, nao autorizacao HTTP, e JWT com papeis e a
TEC-201. Mesma divergencia que a Emenda E-01 da RN-19.5 ja declarou para o
modulo administrativo, aqui estendida a esta rota.

**Consequencia: quem tem o token le o funil inteiro da operacao.** Nao ha
dado pessoal de lead na resposta -- so contagens e medias --, o que torna
esta exposicao menos grave que a de `corretores.py`, mas ela existe.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.deps import exigir_admin
from mobia.app.config import get_settings
from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.filtros import FiltroInvalido, montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import INDICADORES_SEM_FONTE, Etapa
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/metricas", tags=["metricas"])


@router.get("/funil")
async def funil(
    de: Annotated[date, Query()],
    ate: Annotated[date, Query()],
    canal: Annotated[str | None, Query()] = None,
    intencao: Annotated[str | None, Query()] = None,
    temperatura: Annotated[str | None, Query()] = None,
    corretor_id: Annotated[uuid.UUID | None, Query(alias="corretorId")] = None,
    _: None = Depends(exigir_admin),
) -> dict[str, object]:
    """O funil da coorte e os indicadores do periodo.

    Periodo sem lead nenhum devolve 200 com tudo zerado e as taxas nulas --
    nao 404. Ausencia de lead e um fato sobre o negocio, nao sobre a rota.
    """
    try:
        recorte = montar_recorte(
            de=de,
            ate=ate,
            fuso=get_settings().fuso_de_envio,
            canal=canal,
            intencao=intencao,
            temperatura=temperatura,
            corretor_id=corretor_id,
        )
    except FiltroInvalido as erro:
        # 422 com o nome do campo e o valor recusado. Um funil vazio aqui se
        # leria como "nenhum lead no periodo", que e afirmacao sobre o
        # negocio -- e o erro e de quem chamou.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        etapas = await contar_etapas(session, recorte=recorte)
        indicadores = await calcular_indicadores(
            session, recorte=recorte, novos=etapas[Etapa.NOVO]
        )

    corpo_dos_indicadores: dict[str, object] = {
        "leadsNovos": etapas[Etapa.NOVO],
        "conversasAtivas": indicadores.conversas_ativas,
        "taxaQualificacao": indicadores.taxa_qualificacao,
        "distribuicaoPorTemperatura": indicadores.distribuicao_por_temperatura,
        "tempoMedioPrimeiraRespostaSeg": indicadores.tempo_medio_primeira_resposta_seg,
        "tempoMedioQualificacaoSeg": indicadores.tempo_medio_qualificacao_seg,
        "slaHandoffCumpridoPct": indicadores.sla_handoff_cumprido_pct,
    }
    # Os quatro de visita saem SEMPRE, e sempre nulos: omiti-los faria o
    # consumidor tratar a ausencia como erro dele, e zera-los mentiria. Ver a
    # D1 do desenho.
    corpo_dos_indicadores.update(dict.fromkeys(INDICADORES_SEM_FONTE))

    return {
        "etapas": [
            {
                "nome": etapa.nome,
                "quantidade": etapa.quantidade,
                "disponivel": etapa.disponivel,
                "conversaoDaAnterior": etapa.conversao_da_anterior,
            }
            for etapa in montar_funil(etapas)
        ],
        "indicadores": corpo_dos_indicadores,
        "indisponiveis": list(INDICADORES_SEM_FONTE),
    }
```

- [ ] **Step 4: Registrar no app**

Em `src/mobia/app/main.py`, dentro do `if settings.catalogo_admin_token:`, acrescente o import lazy e o `include_router` junto dos outros quatro:

```python
        from mobia.api.routes.metricas import router as metricas_router
```
e
```python
        app.include_router(metricas_router)
```

- [ ] **Step 5: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_metricas.py --tb=short`
Expected: PASS, 8 testes.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/metricas.py src/mobia/app/main.py tests/integration/test_rota_de_metricas.py
git commit -m "feat(TEC-190): GET /api/v1/metricas/funil responde as seis etapas"
```

---

### Task 7: Os critérios de aceite como testes

**Files:**
- Create: `tests/features/test_painel_de_funil.py`

- [ ] **Step 1: Escrever os cenários**

`tests/features/test_painel_de_funil.py`:

```python
"""Criterios de aceite do TEC-190 como testes executaveis. RF-17.

Tres dos quatro cenarios do Gherkin da card. **O quarto -- "Agendamento novo
reflete no painel" (CA-17.1) -- NAO esta aqui e nao pode estar**: nao existe
tabela de agendamento neste repo, e marcar visita e RF-11 e RF-12, epicos nao
construidos. Nao ha como criar o "agendamento criado agora" que o Dado do
cenario exige.

Escrever o cenario com uma tabela inventada so para ele passar e o modo de
falha que o CLAUDE.md nomeia -- teste que inventa a entidade que falta para se
auto-satisfazer. O que se testa no lugar e que o campo sai declaradamente sem
fonte, no `test_o_painel_declara_que_nao_sabe_de_visitas` abaixo. A CA-17.1
volta quando a RF-12 existir. Ver a D1 do desenho.

O quarto cenario do Gherkin, "Carregamento dentro do SLA", vive em
`tests/perf/test_funil_latency.py`, fora do run padrao.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.metricas.filtros import montar_recorte
from conftest import _lead, _recomendar

TOKEN = "token-do-criterio-de-aceite"
ROTA = "/api/v1/metricas/funil"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-31"}
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
async def app_com_token(monkeypatch: Any, caches_de_cliente_limpos, banco_limpo, redis_pool):
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_funil_mostra_as_seis_etapas_com_conversao(app_com_token, session) -> None:
    """Cenario: Funil mostra as seis etapas com conversao."""
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO, falas=3,
                qualificado_em=DENTRO + timedelta(minutes=5))
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO, falas=3)
    await _lead(session, conversa="5511900000003", nasceu_em=DENTRO, falas=1)
    await _recomendar(session, conversa="5511900000001", em=DENTRO)

    corpo = (
        await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})
    ).json()

    assert len(corpo["etapas"]) == 6
    assert corpo["etapas"][0]["quantidade"] == 3
    assert corpo["etapas"][1]["quantidade"] == 2
    # 2 de 3 leads falaram mais de uma vez.
    assert corpo["etapas"][1]["conversaoDaAnterior"] == pytest.approx(2 / 3)
    assert corpo["etapas"][2]["conversaoDaAnterior"] == pytest.approx(1 / 2)


async def test_filtro_por_canal_recalcula_os_indicadores(app_com_token, session) -> None:
    """Cenario: Filtro por canal recalcula os indicadores.

    O Gherkin fala de "leads de WhatsApp e de web", e os dois existem aqui
    como dado semeado: so `whatsapp` e produzido pelo ingresso real hoje -- o
    canal web e a TEC-124, que nao existe. `messages.channel` e `String(32)`
    livre, entao a semeadura e fiel ao que a coluna aceita.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO, canal="whatsapp")
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO, canal="whatsapp")
    await _lead(session, conversa="5511900000003", nasceu_em=DENTRO, canal="web")

    todos = (
        await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})
    ).json()
    so_whatsapp = (
        await app_com_token.get(
            ROTA, params={**PERIODO, "canal": "whatsapp"}, headers={"X-Admin-Token": TOKEN}
        )
    ).json()

    assert todos["indicadores"]["leadsNovos"] == 3
    assert so_whatsapp["indicadores"]["leadsNovos"] == 2
    assert so_whatsapp["etapas"][0]["quantidade"] == 2


async def test_o_painel_declara_que_nao_sabe_de_visitas(app_com_token, session) -> None:
    """No lugar da CA-17.1, que nao e exercitavel. Ver a docstring do modulo.

    O que se afirma aqui e o CONTRARIO de um contador de agendamento: que o
    painel diz nao ter fonte, em vez de dizer zero.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)

    corpo = (
        await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})
    ).json()

    agendado = next(e for e in corpo["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] is None
    assert agendado["disponivel"] is False
    assert corpo["indicadores"]["taxaNoShow"] is None
    assert "taxaNoShow" in corpo["indisponiveis"]


async def test_o_recorte_do_periodo_usa_o_fuso_da_operacao(app_com_token) -> None:
    """Nao e cenario do Gherkin -- e a fronteira que o Gherkin pressupoe.

    "Um periodo com leads" so significa alguma coisa se o periodo tiver
    fronteira definida, e a daqui e a de `settings.fuso_de_envio`.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)

    assert recorte.inicio == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    assert recorte.fim == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
```

- [ ] **Step 2: Rodar**

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_painel_de_funil.py --tb=short`
Expected: PASS, 4 testes.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/features/test_painel_de_funil.py
git commit -m "test(TEC-190): os criterios de aceite exercitaveis, e por que um nao e"
```

---

### Task 8: A medição da RNF-04, e o cache só se ela pedir

**Files:**
- Create: `tests/perf/test_funil_latency.py`

**Interfaces:**
- Produces: a evidência medida, na docstring. E, **condicionalmente**, o cache.

- [ ] **Step 1: Escrever o teste de latência**

`tests/perf/test_funil_latency.py`:

```python
"""Criterio de aceite do TEC-190: p95 do painel abaixo de 2 s com 1.000 leads
(RNF-04, e o quarto cenario do Gherkin da card).

Marcado `perf` e fora do run padrao, no molde de `test_busca_latency.py`: a
medicao depende da maquina, e o `CLAUDE.md` registra que medir p95 em runner
compartilhado seria flake e nao sinal. Rode com `python -m pytest -m perf`.

**A fronteira medida e o BANCO**, e nao o HTTP: o que a RNF-04 poe em risco
sao seis agregacoes sobre a coorte, e nao a serializacao de um dicionario com
vinte chaves. Medir pelo `AsyncClient` acrescentaria o ASGI e o middleware de
rate limit ao numero sem acrescentar risco.

**Dois grupos, nunca uma media.** Sem filtro e o caminho de custo pleno --
toda a coorte do periodo. Com filtro de corretor e o mais estreito, porque o
JOIN com `handoffs` corta a coorte antes das agregacoes. Uma media dos dois
esconderia qual dos dois estoura o orcamento.

## Evidencia medida

(Preencher ao rodar. Registre: data, maquina, versao do Python, numero de
leads, p50/p95/p99 de cada grupo, e a margem contra os 2 s.)
"""

import statistics
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.context.models import LeadQualification
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa
from mobia.infra.crypto import aad_de, encrypt

pytestmark = pytest.mark.perf

CANAL = "whatsapp"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
LEADS = 1000
TETO_SEGUNDOS = 2.0
MEDICOES = 20


async def _semear(session, corretor_alvo: uuid.UUID) -> None:
    """1.000 leads espalhados por agosto, um quinto com handoff do alvo."""
    for indice in range(LEADS):
        conversa = f"5511{indice:09d}"
        nasceu = INICIO + timedelta(minutes=indice * 20)
        for fala in range(2):
            identificador = uuid.uuid4()
            session.add(
                Message(
                    id=identificador,
                    channel=CANAL,
                    provider_message_id=f"wamid.{identificador.hex[:12]}",
                    sender_external_id=conversa,
                    recipient_external_id="222222222",
                    conversation_key=conversa,
                    role=MessageRole.LEAD,
                    direction=MessageDirection.INBOUND,
                    content_type=MessageContentType.TEXTO,
                    text_body=encrypt("oi", aad_de(identificador, "text_body")),
                    raw_payload=None,
                    status=MessageStatus.PROCESSED,
                    created_at=nasceu + timedelta(minutes=fala),
                )
            )
        session.add(Conversa(channel=CANAL, conversation_key=conversa, status=Status.ATIVA))
        session.add(
            LeadQualification(
                channel=CANAL,
                conversation_key=conversa,
                temperatura=("QUENTE", "MORNO", "FRIO")[indice % 3],
                qualificado_em=(nasceu + timedelta(minutes=30)) if indice % 2 else None,
            )
        )
        if indice % 5 == 0:
            session.add(
                Handoff(
                    id=uuid.uuid4(),
                    channel=CANAL,
                    conversation_key=conversa,
                    gatilho="QUENTE",
                    etiqueta="LEAD_QUENTE",
                    prioridade="ALTA",
                    status="ACEITO",
                    corretor_id=corretor_alvo,
                    aceito_em=nasceu + timedelta(hours=1),
                    sla_limite_em=nasceu + timedelta(hours=2),
                    criado_em=nasceu,
                    atualizado_em=nasceu,
                )
            )
        if indice % 100 == 0:
            await session.commit()
    await session.commit()


async def _medir(session, recorte) -> float:
    comeco = time.perf_counter()
    etapas = await contar_etapas(session, recorte=recorte)
    await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])
    return time.perf_counter() - comeco


async def test_p95_do_painel_com_mil_leads(session) -> None:
    corretor = uuid.uuid4()
    await _semear(session, corretor)
    await session.execute(__import__("sqlalchemy").text("ANALYZE messages, lead_qualification"))

    for rotulo, recorte in (
        ("sem filtro", montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)),
        (
            "por corretor",
            montar_recorte(
                de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, corretor_id=corretor
            ),
        ),
    ):
        duracoes = sorted([await _medir(session, recorte) for _ in range(MEDICOES)])
        p95 = duracoes[int(len(duracoes) * 0.95) - 1]
        print(
            f"\n{rotulo}: p50={statistics.median(duracoes):.3f}s "
            f"p95={p95:.3f}s max={duracoes[-1]:.3f}s"
        )
        assert p95 < TETO_SEGUNDOS, f"{rotulo}: p95={p95:.3f}s estourou o teto de {TETO_SEGUNDOS}s"
```

- [ ] **Step 2: Rodar a medição**

Run: `./.venv/Scripts/python.exe -m pytest tests/perf/test_funil_latency.py -m perf -s --tb=short`
Expected: os dois p95 impressos. **Anote os números.**

- [ ] **Step 3: Escrever a evidência na docstring**

Substitua o "(Preencher ao rodar…)" pelos números medidos, no formato que `test_busca_latency.py` usa: data, máquina, versão do Python, quantidade de leads, p50/p95/p99 por grupo e a margem contra os 2 s.

- [ ] **Step 4: Decidir sobre o cache, com o número na mão**

**Se os dois p95 passaram:** não há cache nesta card. Escreva na docstring que a consulta ao vivo atende a RNF-04 com a margem medida, e que o cache foi **recusado por falta de necessidade demonstrada** — a D5 do desenho.

**Se algum p95 estourou:** o cache entra, e só então. Redis, chave derivada da tupla do `Recorte`, **TTL de 60 s** (o teto da RN-17.3, que um TTL maior violaria), e fail-open no molde de `infra/rate_limit.py` — `RedisError` devolve o dado vivo, nunca um erro. O pool chega por `getattr(request.app.state, "redis_pool", None)`, como nos outros consumidores. Acrescente um teste de que o segundo pedido idêntico não toca o banco e outro de que Redis fora do ar ainda responde 200.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/perf/test_funil_latency.py
git commit -m "test(TEC-190): a medicao da RNF-04, com a evidencia na docstring"
```

---

### Task 9: A suíte inteira, as emendas ao SRS e o CLAUDE.md

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, `docs/superpowers/specs/2026-09-24-tec-190-painel-de-funil-design.md`

- [ ] **Step 1: Rodar a suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — é a queda do Postgres sob paralelismo que o `CLAUDE.md` documenta; rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).

- [ ] **Step 2: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`. O comentário de `turno.py` sobre a reemissão já foi corrigido na Tarefa 1 — confirme que a listagem não aponta outro que a branch tornou falso.

- [ ] **Step 3: Escrever as emendas ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, como itens aninhados **abaixo** da regra que alteram, sem reescrever o texto de 22/08/2026:

- Sob **RN-17.1**: `Emenda E-01 (TEC-190, 24/09/2026)` — os quatro indicadores de agendamento saem `null` com `disponivel: false` enquanto RF-11 e RF-12 não existirem; não há tabela de agendamento. Os demais indicadores são sobre a **coorte** do período (D10), não sobre eventos ocorridos nele.
- Sob **RN-17.2**: `Emenda E-01 (TEC-190, 24/09/2026)` — a etapa `Agendado` idem, e `conversaoDaAnterior` de `Handoff aceito` é nula por consequência: pular a etapa cega e dividir por `Recomendado` daria número plausível e errado.
- Sob **RN-17.3**: `Emenda E-01 (TEC-190, 24/09/2026)` — a query ganha `temperatura`, que a regra exigia e a §6.6 não tinha. A fronteira do dia é a de `settings.fuso_de_envio`, com intervalo semiaberto.
- Sob **CA-17.1**: `Emenda E-01 (TEC-190, 24/09/2026)` — não exercitável nesta card; volta com a RF-12.
- Na **§6.6**, sob `GET /api/v1/metricas/funil`: `Emenda E-01 (TEC-190, 24/09/2026)` — o corpo passa ao contrato da spec, que cobre a RN-17.1 e a RN-17.2 inteiras; a autenticação é `X-Admin-Token` via `exigir_admin`, e não Bearer JWT, até a TEC-201.

- [ ] **Step 4: Emendar a spec com o que o plano decidiu**

Acrescente à spec a **D10** (o funil é coorte, com o argumento da conversão acima de 100%) e a nota de que a D9 foi refinada: Server Component com busca no servidor, no lugar do Route Handler — mesma propriedade de o token nunca chegar ao navegador, mesmo argumento de rate limit, um hop a menos.

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-24-tec-190-painel-de-funil-design.md
git commit -m "docs(TEC-190): emendas do painel ao SRS, e a coorte que o plano decidiu"
```

---

## Self-review

**Cobertura da spec.** D1 → Tarefas 2 (`SEM_FONTE`), 6 (resposta) e 7 (critério). D2 e D3 → Tarefa 1. D4 (regra não reescrita em SQL) → Tarefa 4, onde o predicado é `qualificado_em IS NOT NULL` e não os quatro `CAMPOS_OBRIGATORIOS`. D5 → Tarefa 8, com a decisão condicionada à medição. D6 → Tarefa 4, com teste da lacuna L2. D7 → Tarefa 5, com o teste dos três handoffs. D8 → Tarefa 6. D10 → Tarefas 4 e 5. Contrato → Tarefa 6. Emendas → Tarefa 9. **A metade do frontend (D9) é o outro plano.**

**Placeholders.** A única marca deliberada é a seção "Evidencia medida" da Tarefa 8, que só pode ser preenchida rodando — e o Step 3 daquela tarefa é o passo que a preenche. O andaime `da_coorte`/`del` da Tarefa 4 tem um passo próprio (Step 4) que o remove, e o `ruff` reprova se ficar.

**Consistência de tipos.** `Recorte` nasce na Tarefa 3 e é consumido nas 4, 5, 6 e 8. `Etapa` e `montar_funil` nascem na 2 e são consumidos na 4 e na 6. `contar_etapas` devolve `dict[Etapa, int]` sem a chave `AGENDADO`, e `montar_funil` usa `.get(etapa, 0)` — combinam. `calcular_indicadores` recebe `novos: int`, que a rota tira de `etapas[Etapa.NOVO]`. `FiltroInvalido.campo` é usado no 422 da Tarefa 6 e assertado na 3.

**Review Focus.** Os cinco têm teste: 1 na Tarefa 2 (`test_anterior_em_zero_...`), 2 nas Tarefas 3 e 4 (`test_a_fronteira_do_dia_e_a_do_fuso`), 3 nas Tarefas 3 e 6, 4 nas Tarefas 3 e 6, 5 nas Tarefas 4, 5 (`test_coorte_vazia_da_taxa_nula_e_nao_zero`) e 6.
