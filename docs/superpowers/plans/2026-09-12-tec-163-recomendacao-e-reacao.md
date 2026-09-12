# TEC-163 — Recomendação e reação: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar toda apresentação como uma `Recomendacao` com o motivo do match, capturar a reação do lead, e realimentar o filtro da mesma conversa — informando o lead de todo ajuste.

**Architecture:** A tabela `recomendacoes` é ao mesmo tempo o registro e o **estado**: o filtro realimentado é uma consulta sobre ela, sem coluna nova em lugar nenhum. A reação vem de uma **segunda chamada dedicada** ao modelo, no molde de `desambiguar`, porque o orçamento do prompt principal tem 6,2 tokens de margem e esta card precisaria de ~50. O modelo devolve **ordinal**, nunca UUID.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x async (Core), Alembic, Postgres 16 + pgvector, Anthropic API, pytest-asyncio, structlog, mypy, ruff.

**Spec:** [`docs/superpowers/specs/2026-09-12-tec-163-recomendacao-e-reacao-design.md`](../specs/2026-09-12-tec-163-recomendacao-e-reacao-design.md) (commit `237bbcd`). **Leia o desenho antes de começar** — cada task cita a decisão (D1–D16) que a justifica, e o desenho é onde mora o porquê.

**Card:** [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163) — História, Should, prioridade High, épico TEC-155. Os quatro cenários do Gherkin estão mapeados nas Tasks 3, 7 e 10.

**Branch:** `feat/tec-163-recomendacao-e-reacao` (já criada, já contém o desenho).

**A ordem das tasks entrega a peça A primeiro (D1).** Tasks 1–3 fecham a RN-10.3 e pagam a L1 da TEC-162; elas valem sozinhas. Se algo travar depois, a card já entregou isso.

---

## Global Constraints

Valem para **toda** task. Não estão repetidas dentro de cada uma.

- **Os três gates estáticos, com o escopo exato do CI.** Rode os três antes de cada commit — passar no linter não diz nada sobre o formatador:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  Rode `ruff format` **sem** `--check` primeiro, depois o `--check` como verificação. Ruff: `select = ["E","F","I","UP","B"]`, `line-length = 100`, py313. **Imports no topo do arquivo, ordenados** — `E402` e isort são gates.
- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Nenhum linter checa. Prosa em `docs/`: com acento.
- **Todo texto que sai para o lead é ASCII sem acento.**
- **Comentário não mente.** Este repo comenta o *porquê* e trata comentário desatualizado como defeito igual a defeito de código.
- **Mensagens de commit:** português sem acento no assunto, `tipo(TEC-163): o que passou a ser verdade`. A mensagem termina com esta linha, caractere por caractere — **não substitua pelo nome do seu modelo**:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Basenames únicos entre `tests/unit/` e `tests/integration/`** — colisão aborta a coleta da suíte inteira e **não** aparece em execução isolada. Os desta card: `test_recomendacao_regras.py` (unit) e `test_recomendacao_e_reacao.py` (integração).
- **Toda comparação de bairro é entre formas dobradas** (`mobia.domain.texto.dobrar`). A TEC-160 quase mandou para produção a metade de bairros da RN-09.3 desligada por comparar cru contra dobrado, com 1534 testes verdes.
- **Não rode a suíte inteira** durante o desenvolvimento — leva ~20 minutos. Só os arquivos da task. A suíte completa é a Task 12.
- **Flakes conhecidos desta máquina, nenhum deles seu:** `ConnectionResetError [WinError 64]` na negociação SSL do asyncpg (~5% dos connects, em rajada, sempre na fixture e nunca numa asserção) e `CannotConnectNowError: ... recovery mode` em container frio por ~15s. Espere e retente; uma falha isolada com qualquer um dos dois não autoriza conclusão nenhuma.
- **Postgres e Redis já estão de pé.** Não reinicie.

---

## Estrutura de arquivos

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `alembic/versions/0022_recomendacoes.py` | Schema da tabela |
| `src/mobia/domain/agente/recomendacao.py` | As regras puras: `motivo_match`, o limiar dos dois descartes, o mapeamento de ordinal |
| `tests/unit/test_recomendacao_regras.py` | As regras puras |
| `tests/integration/test_recomendacao_e_reacao.py` | Contra banco, e os quatro cenários |

**Modificados:**

| Arquivo | O quê |
|---|---|
| `src/mobia/domain/agente/models.py` | Modelo `Recomendacao` |
| `src/mobia/domain/agente/schemas.py` | `ReacaoLead`, `CategoriaDescarte`, `ReacaoDoLead` |
| `src/mobia/domain/agente/repositorio.py` | Gravar recomendações, gravar reações, consultar exclusões |
| `src/mobia/domain/agente/classificador.py` | `SISTEMA_DA_REACAO`, `SCHEMA_DA_REACAO`, `reagir` — e a correção do comentário falso |
| `src/mobia/domain/agente/ferramenta_de_busca.py` | Os critérios no `tool_result`; liga a exclusão ao filtro |
| `src/mobia/domain/agente/turno.py` | Chama `reagir`, grava as recomendações, envia o aviso do ajuste |
| `src/mobia/domain/catalogo/schemas.py` | `FiltroDeBusca.bairros_excluidos` |
| `src/mobia/domain/catalogo/busca.py` | A condição de exclusão no `WHERE` |
| `src/mobia/domain/catalogo/relaxamento.py` | `alargar` subtrai os excluídos |
| `tests/conftest.py` | `recomendacoes` em `TABELAS` |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Três emendas e três linhas no índice |

---

# PEÇA A — a tabela e a persistência

Fecha a RN-10.3 e paga a L1 da TEC-162. Vale sozinha.

## Task 1: A tabela `recomendacoes`

**Files:**
- Create: `alembic/versions/0022_recomendacoes.py`
- Modify: `src/mobia/domain/agente/models.py`, `src/mobia/domain/agente/schemas.py`, `tests/conftest.py`
- Test: `tests/integration/test_recomendacao_e_reacao.py` (arquivo novo)

**Interfaces:**
- Consumes: nada.
- Produces: tabela `recomendacoes`; modelo `Recomendacao`; enums `ReacaoLead` (`INTERESSE`/`DESCARTE`/`NEUTRO`/`SEM_RESPOSTA`) e `CategoriaDescarte` (`DISTANCIA`/`PRECO`/`TAMANHO`/`OUTRO`), ambos `StrEnum` em `agente/schemas.py`.

- [ ] **Step 1: Confirme que `0021` é o head**

```bash
./.venv/Scripts/python.exe -m alembic heads
```
Expected: `0021`.

- [ ] **Step 2: Escreva os testes que falham**

Crie `tests/integration/test_recomendacao_e_reacao.py`:

```python
"""A recomendacao e a reacao do lead, contra o banco.

TEC-163. Os quatro cenarios do Gherkin da card, mais o que o desenho decidiu.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoLead
from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar

CANAL = "whatsapp"
CONVERSA = "5548999990000"


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `tests/integration/test_relaxamento_busca.py`.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 35000000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
        "zona": "CENTRO",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def _recomendar(session: Any, imovel_id: uuid.UUID, **sobrescritas: object) -> None:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "imovel_id": imovel_id,
        "score_match": 0.870,
        "motivo_match": "3 quartos, Trindade, dentro do teto",
        "apresentado_em": datetime.now(UTC),
    }
    campos.update(sobrescritas)
    session.add(Recomendacao(**campos))
    await session.commit()


async def test_a_recomendacao_nasce_sem_reacao(session: Any) -> None:
    """D8: linha pendente e o gatilho da chamada de reacao."""
    imovel = await _imovel(session, "AP-401")

    await _recomendar(session, imovel)

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.reacao_lead is None
    assert linha.motivo_descarte is None


async def test_o_mesmo_imovel_nao_entra_duas_vezes_na_conversa(session: Any) -> None:
    """D3: o cenario 4 do Gherkin vira garantia de schema.

    "Os ja apresentados nao sao repetidos" deixa de depender de disciplina de
    consulta -- o banco recusa.
    """
    imovel = await _imovel(session, "AP-402")
    await _recomendar(session, imovel)

    with pytest.raises(IntegrityError):
        await _recomendar(session, imovel)


async def test_o_mesmo_imovel_entra_em_conversas_diferentes(session: Any) -> None:
    """O UNIQUE e por conversa: outro lead pode ver o mesmo imovel."""
    imovel = await _imovel(session, "AP-403")
    await _recomendar(session, imovel)

    await _recomendar(session, imovel, conversation_key="5548999991111")

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert len(linhas) == 2


async def test_a_reacao_e_a_categoria_gravam(session: Any) -> None:
    """D13: `motivo_descarte` guarda a CATEGORIA, nao a frase do lead."""
    imovel = await _imovel(session, "AP-404")

    await _recomendar(
        session,
        imovel,
        reacao_lead=ReacaoLead.DESCARTE.value,
        motivo_descarte=CategoriaDescarte.DISTANCIA.value,
    )

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.reacao_lead == "DESCARTE"
    assert linha.motivo_descarte == "DISTANCIA"
```

- [ ] **Step 3: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'Recomendacao'`.

- [ ] **Step 4: Acrescente os dois enums**

Em `src/mobia/domain/agente/schemas.py`, junto dos outros enums do módulo:

```python
class ReacaoLead(StrEnum):
    """O que o lead fez com um imovel apresentado. RN-10.4.

    `NEUTRO` e "o lead respondeu, mas nao falou deste imovel"; `SEM_RESPOSTA`
    e "uma apresentacao nova superou esta linha antes de o lead reagir". Os
    dois significam ausencia de opiniao e sao contados diferente: NEUTRO e
    evidencia de que o lead viu, SEM_RESPOSTA nao e evidencia de nada.
    """

    INTERESSE = "INTERESSE"
    DESCARTE = "DESCARTE"
    NEUTRO = "NEUTRO"
    SEM_RESPOSTA = "SEM_RESPOSTA"


class CategoriaDescarte(StrEnum):
    """Por que o lead descartou, em forma comparavel. TEC-163, D13.

    **Categoria e nao a frase do lead**, e a RN-10.4 e quem exige: ela conta
    "dois descartes por DISTANCIA", o que so e computavel se o motivo for
    comparavel. A observacao do campo no modelo de dados do SRS diz
    "Realimenta o filtro", e texto livre nao realimenta nada.

    A frase do lead nao se perde -- ela esta na mensagem, que a linha do tempo
    ja guarda. Duplica-la aqui criaria uma segunda copia que envelhece
    sozinha, e o campo passaria a ter dois propositos incompativeis: ser lido
    por humano e ser contado por codigo.
    """

    DISTANCIA = "DISTANCIA"
    PRECO = "PRECO"
    TAMANHO = "TAMANHO"
    OUTRO = "OUTRO"
```

- [ ] **Step 5: Acrescente o modelo**

No fim de `src/mobia/domain/agente/models.py` (precisa de `import uuid`, `Text`, `UniqueConstraint`, `ForeignKey` e `from sqlalchemy.dialects.postgresql import UUID as PgUUID` — todos no topo, ordenados):

```python
class Recomendacao(Base):
    """Um imovel apresentado a um lead, e o que ele fez com isso. RN-10.3.

    **Chaveada pelo par `(channel, conversation_key)`, e nao por `conversa_id`.**
    O SRS especifica uma FK para `Conversa`, e `Conversa` nao e entidade neste
    sistema e nunca foi: `conversation_summaries`, `lead_qualification` e
    `conversation_intent` usam todas o par. Seguir o SRS aqui introduziria um
    SEGUNDO jeito de identificar conversa, que e pior que a divergencia. Ver a
    D2 e a emenda E-01 da RN-10.3.

    **O `UNIQUE` e o cenario 4 do Gherkin.** "Os ja apresentados nao sao
    repetidos" vira garantia de schema em vez de disciplina de consulta: o
    banco recusa a segunda insercao do mesmo imovel na mesma conversa.

    `reacao_lead` NULL significa "ainda nao reagiu", e e o gatilho da chamada
    de reacao (D8). `motivo_descarte` guarda a CATEGORIA (`CategoriaDescarte`),
    nao a frase do lead -- ver a D13.
    """

    __tablename__ = "recomendacoes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    imovel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("imoveis.id"), nullable=False
    )

    # A relevancia da RN-09.6, no tipo que a ficha da tabela do SRS escreve.
    score_match: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    # Derivado dos criterios da busca, nunca escrito pelo modelo (D5). E por
    # BUSCA e nao por imovel: os candidatos de uma mesma busca casaram o mesmo
    # filtro, e o que os distingue e o `score_match` (D4).
    motivo_match: Mapped[str] = mapped_column(Text, nullable=False)

    reacao_lead: Mapped[str | None] = mapped_column(String(16), nullable=True)
    motivo_descarte: Mapped[str | None] = mapped_column(String(80), nullable=True)

    apresentado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "channel", "conversation_key", "imovel_id", name="uq_recomendacoes_conversa_imovel"
        ),
    )
```

- [ ] **Step 6: Escreva a migration**

Crie `alembic/versions/0022_recomendacoes.py`:

```python
"""a recomendacao: o imovel apresentado, e o que o lead fez com ele

TEC-163, RN-10.3 e RN-10.4.

**Chaveada pelo par `(channel, conversation_key)`.** O SRS pede
`conversa_id UUID FK -> Conversa`, e `Conversa` nao existe neste sistema:
`conversation_summaries`, `lead_qualification` e `conversation_intent` usam
todas o par, desde as respectivas cards. A emenda E-01 da RN-10.3 declara a
divergencia -- que e do sistema e nao desta tabela, e estava tres tabelas
atrasada.

**O UNIQUE nao esta no SRS, e e de proposito.** Ele faz o cenario 4 do Gherkin
("os ja apresentados nao sao repetidos") ser garantia de schema em vez de
disciplina de consulta.

**Sem indice alem do UNIQUE.** As duas consultas desta card -- linhas
pendentes da conversa, e descartes por distancia da conversa -- filtram por
`(channel, conversation_key)`, que e o prefixo do UNIQUE e portanto ja e
servido por ele. Um indice a mais seria custo de escrita sem retorno de
leitura, que e exatamente a TEC-266.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recomendacoes",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("score_match", sa.Numeric(4, 3), nullable=False),
        sa.Column("motivo_match", sa.Text(), nullable=False),
        sa.Column("reacao_lead", sa.String(16), nullable=True),
        sa.Column("motivo_descarte", sa.String(80), nullable=True),
        sa.Column("apresentado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recomendacoes"),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_recomendacoes_imovel"),
        sa.UniqueConstraint(
            "channel", "conversation_key", "imovel_id", name="uq_recomendacoes_conversa_imovel"
        ),
    )


def downgrade() -> None:
    op.drop_table("recomendacoes")
```

- [ ] **Step 7: Acrescente `recomendacoes` a `TABELAS`**

Em `tests/conftest.py`, dentro da tupla `TABELAS`, com este comentário:

```python
    # TEC-163. Entra aqui, ao contrario de `bairros_adjacentes`, porque e
    # escrita pelos TESTES e nao pelo schema: sem o truncate, as recomendacoes
    # de um teste viram historico do proximo e o ajuste de filtro da RN-10.4
    # dispara onde ninguem pediu. Custo conhecido e aceito -- um TRUNCATE por
    # teste da suite inteira --, pelo mesmo argumento que `imoveis` e
    # `lead_score_audit` ja registram acima: a alternativa e teste que passa
    # sozinho e falha em conjunto.
    "recomendacoes",
```

- [ ] **Step 8: Aplique, verifique o downgrade, rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -v --tb=short
```
Expected: as migrations sem erro nas três, e 4 passed. Migration que não desce é migration que ninguém reverte em produção.

- [ ] **Step 9: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff format src tests alembic evals
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0022_recomendacoes.py src/mobia/domain/agente/ tests/
git commit -m "feat(TEC-163): o imovel apresentado passa a ter onde ser registrado"
```

---

## Task 2: Os critérios da busca e a frase do `motivo_match`

Puro. Sem banco.

**Files:**
- Create: `src/mobia/domain/agente/recomendacao.py`, `tests/unit/test_recomendacao_regras.py`
- Modify: `src/mobia/domain/agente/ferramenta_de_busca.py`
- Test: `tests/unit/test_recomendacao_regras.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `motivo_do_match(criterios: Sequence[str]) -> str` em `domain/agente/recomendacao.py`; a chave `"criterios"` no dict do `tool_result`, uma lista de strings curtas por **busca**.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/unit/test_recomendacao_regras.py`:

```python
"""As regras puras da recomendacao e da reacao.

TEC-163. Sem banco, sem I/O. Basename distinto de tudo em
`tests/integration/`.
"""

from mobia.domain.agente.recomendacao import motivo_do_match


def test_o_motivo_lista_os_criterios_que_casaram() -> None:
    """D5: derivado do que a busca sabe, nunca escrito pelo modelo."""
    assert motivo_do_match(["3 quartos", "Trindade", "ate R$ 400 mil"]) == (
        "3 quartos, Trindade, ate R$ 400 mil"
    )


def test_um_criterio_so_nao_ganha_virgula() -> None:
    assert motivo_do_match(["Trindade"]) == "Trindade"


def test_busca_sem_criterio_diz_isso_em_vez_de_ficar_vazia() -> None:
    """`motivo_match` e NOT NULL, e string vazia num campo de explicabilidade
    e pior que uma frase honesta: quem le a linha meses depois precisa saber
    que nao houve filtro, nao ficar sem saber o que aconteceu."""
    assert motivo_do_match([]) == "sem filtro: o lead nao restringiu a busca"


def test_o_motivo_e_ascii() -> None:
    """Vai para o banco e pode ser lido em relatorio; segue a disciplina do
    repo para texto que nao e prosa de docs."""
    assert motivo_do_match(["3 quartos", "Trindade"]).isascii()
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_recomendacao_regras.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.agente.recomendacao'`.

- [ ] **Step 3: Crie o módulo**

Crie `src/mobia/domain/agente/recomendacao.py`:

```python
"""As regras puras da recomendacao e da reacao do lead.

TEC-163. Sem I/O e sem banco: o que precisa de sessao mora em
`repositorio.py`, e o que precisa do modelo mora em `classificador.py`. Aqui
ficam as decisoes que se testam sem nada de pe.
"""

from collections.abc import Sequence

_SEM_CRITERIO = "sem filtro: o lead nao restringiu a busca"


def motivo_do_match(criterios: Sequence[str]) -> str:
    """A frase de explicabilidade da RN-10.3, montada dos criterios da busca.

    **Derivada, nunca escrita pelo modelo (D5).** Um motivo inventado ficaria
    gravado no banco como se fosse fato, e explicabilidade falsa e pior que
    explicabilidade pobre: a pobre se reconhece, a falsa nao.

    **E por BUSCA e nao por imovel (D4).** Todos os candidatos de uma busca
    casaram o mesmo filtro; o que os distingue e o `score_match`, que tem
    coluna propria. Um motivo por candidato seria a mesma frase repetida tres
    vezes, paga em tokens no `tool_result` de todo turno que busca.

    Lista vazia devolve uma frase e nao string vazia: a coluna e NOT NULL, e
    um campo de explicabilidade em branco deixa quem le a linha meses depois
    sem saber se nao houve filtro ou se alguem esqueceu de gravar.
    """
    return ", ".join(criterios) if criterios else _SEM_CRITERIO
```

- [ ] **Step 4: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_recomendacao_regras.py -v`
Expected: 4 passed.

- [ ] **Step 5: Escreva o teste dos critérios no `tool_result`**

Encontre o molde: `grep -n "_FabricaFalsa\|_BuscaEspia\|def _porta" tests/unit/test_ferramenta_de_busca.py`. **Reúse os helpers que estiverem lá**, não crie outros. Acrescente:

```python
async def test_o_tool_result_leva_os_criterios_da_busca() -> None:
    """TEC-163, D4. Um campo por BUSCA, nao um por candidato.

    Sao os criterios que de fato entraram no WHERE -- o turno renderiza a
    frase do `motivo_match` a partir deles, em Python, fora do contexto do
    modelo.
    """
    saida = await _porta({"operacao": "VENDA", "quartos_min": 3, "regioes": ["Trindade"]})

    assert saida["criterios"] == ["3 quartos", "Trindade"]


async def test_busca_sem_filtro_leva_lista_de_criterios_vazia() -> None:
    saida = await _porta({"operacao": "VENDA"})

    assert saida["criterios"] == []
```

- [ ] **Step 6: Implemente os critérios na porta**

Em `src/mobia/domain/agente/ferramenta_de_busca.py`, acrescente a função e a chave no dict devolvido:

```python
def _criterios_de(filtro: FiltroDeBusca) -> list[str]:
    """Os criterios que entraram no WHERE, em forma legivel. TEC-163, D4.

    Um por BUSCA e nao por candidato: e a mesma lista para todos os imoveis
    daquela apresentacao, e repeti-la por candidato pagaria tokens no
    `tool_result` para dizer tres vezes a mesma coisa.

    `operacao` fica de fora de proposito: ela nao restringe o que o lead
    pediu, escolhe a coluna de preco. "VENDA" como motivo de match nao
    explica nada a quem le a linha depois.
    """
    criterios: list[str] = []
    if filtro.quartos_min is not None:
        criterios.append(f"{filtro.quartos_min} quartos")
    if filtro.vagas_min is not None:
        criterios.append(f"{filtro.vagas_min} vagas")
    if filtro.tipo is not None:
        criterios.append(filtro.tipo.value.lower())
    if filtro.regioes:
        criterios.extend(filtro.regioes)
    if filtro.preco_max_centavos is not None:
        criterios.append(f"ate {reais_de(filtro.preco_max_centavos)}")
    return criterios
```

`reais_de` vem de `mobia.domain.agente.apresentacao` — import no topo, ordenado. E no dict devolvido pela porta, junto dos campos de relaxamento:

```python
            # TEC-163, D4. Um campo por busca: o turno monta o `motivo_match`
            # a partir daqui, em Python. Sem isto, ou o motivo seria escrito
            # pelo modelo (D5 recusa) ou o turno nao teria como saber o que
            # o filtro pediu -- ele so ve os candidatos.
            "criterios": _criterios_de(filtro),
```

- [ ] **Step 7: Rode os dois arquivos**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_recomendacao_regras.py tests/unit/test_ferramenta_de_busca.py -v --tb=short
```

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff format src tests alembic evals
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ tests/unit/
git commit -m "feat(TEC-163): a busca diz quais criterios casou, uma vez por busca"
```

---

## Task 3: `_apresentar` grava a recomendação

Aqui a L1 da TEC-162 é paga.

**Files:**
- Modify: `src/mobia/domain/agente/repositorio.py`, `src/mobia/domain/agente/turno.py`
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: `Recomendacao` (Task 1), `motivo_do_match` (Task 2), a chave `"criterios"` do `tool_result` (Task 2).
- Produces: `gravar_recomendacoes(session_factory, *, channel, conversation_key, candidatos, scores, criterios, agora) -> None` em `domain/agente/repositorio.py`.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/integration/test_recomendacao_e_reacao.py`:

```python
async def test_cenario_2_a_recomendacao_registra_motivo_e_momento(
    session: Any, session_factory: Any
) -> None:
    """Cenario 2 do Gherkin: "ela registra o motivo do match e o momento"."""
    imovel = await _imovel(session, "AP-410")
    agora = datetime.now(UTC)

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[{"imovel_id": str(imovel), "score": 0.87}],
        criterios=["3 quartos", "Trindade"],
        agora=agora,
    )

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.motivo_match == "3 quartos, Trindade"
    assert linha.apresentado_em == agora
    assert float(linha.score_match) == 0.87


async def test_gravar_duas_vezes_o_mesmo_imovel_nao_levanta(
    session: Any, session_factory: Any
) -> None:
    """A reapresentacao acontece: o lead pede "mostra de novo aquele".

    O UNIQUE existe para impedir DUPLICATA, nao para derrubar o turno. Gravar
    de novo e no-op -- a linha original, com a reacao que ja tiver, sobrevive.
    """
    imovel = await _imovel(session, "AP-411")
    candidatos = [{"imovel_id": str(imovel), "score": 0.87}]

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        criterios=["Trindade"],
        agora=datetime.now(UTC),
    )
    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        criterios=["Trindade"],
        agora=datetime.now(UTC),
    )

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert len(linhas) == 1
```

Acrescente `from mobia.domain.agente.repositorio import gravar_recomendacoes` ao bloco de imports do topo, ordenado.

- [ ] **Step 2: Rode para ver falhar**

Expected: `ImportError: cannot import name 'gravar_recomendacoes'`.

- [ ] **Step 3: Implemente o repositório**

Em `src/mobia/domain/agente/repositorio.py` (o `pg_insert` já está importado):

```python
async def gravar_recomendacoes(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    candidatos: Sequence[Mapping[str, Any]],
    scores: Mapping[uuid.UUID, float],
    criterios: Sequence[str],
    agora: datetime,
) -> None:
    """Uma linha por imovel apresentado. RN-10.3, e a L1 da TEC-162.

    **`ON CONFLICT DO NOTHING`, e nao um `raise`.** O UNIQUE existe para
    impedir DUPLICATA, nao para derrubar o turno: o lead pede "mostra de novo
    aquele do Campeche" e a reapresentacao e legitima. Deixar o IntegrityError
    subir mataria o turno por causa de um registro, e a D9 da TEC-265 ja
    escreveu a regra oposta para este caminho.

    A linha original sobrevive com a reacao que ja tiver -- que e o
    comportamento certo: a opiniao do lead sobre aquele imovel nao muda porque
    ele o viu de novo.

    **Gravada ANTES da entrega**, por quem chama. O docstring de `_apresentar`
    registra que uma falha parcial perde o conjunto escolhido e o turno
    seguinte pode reapresentar os mesmos imoveis; gravar depois manteria esse
    buraco aberto.
    """
    if not candidatos:
        return

    motivo = motivo_do_match(criterios)
    linhas = [
        {
            "id": uuid.uuid4(),
            "channel": channel,
            "conversation_key": conversation_key,
            "imovel_id": uuid.UUID(str(candidato["imovel_id"])),
            "score_match": Decimal(str(scores[uuid.UUID(str(candidato["imovel_id"]))])),
            "motivo_match": motivo,
            "apresentado_em": agora,
        }
        for candidato in candidatos
    ]

    async with session_factory() as session:
        await session.execute(pg_insert(Recomendacao).values(linhas).on_conflict_do_nothing())
        await session.commit()
```

Imports novos no topo, ordenados: `uuid`, `Mapping`/`Sequence` de `collections.abc`, `Recomendacao` de `agente.models`, `motivo_do_match` de `agente.recomendacao`.

> **Atenção ao `score` — leia a D17 do desenho antes deste passo.**
>
> `_candidato_serializavel` em `ferramenta_de_busca.py` **não** inclui `score` no dict que o modelo vê: a D7 da TEC-265 o removeu de propósito, porque `score` no prompt convida o modelo a dizer "97% de compatibilidade" ao lead. Então `candidatos[i]["score"]` **não existe** no dict que chega ao turno.
>
> **Não conserte passando o score pelo `tool_result`** — isso desfaz aquela decisão pelo motivo exato que ela nomeia.
>
> **A solução é a D17:** `porta_de_busca` é uma closure criada por turno, e guarda os scores da última busca num dicionário capturado, por `imovel_id`. O turno o lê ao gravar. O score nunca entra no contexto do modelo e a coluna recebe o número real. Implemente isso nesta task, com um teste afirmando que **duas portas distintas não compartilham scores** — sem ele, a próxima card que tornar a porta reutilizável vaza score entre conversas sem ninguém notar.
>
> Gravar `0.0` **não** é aceitável: tornaria a coluna decorativa e derrubaria a justificativa da D4, que afirma que o que distingue os imóveis de uma recomendação é justamente o `score_match`.

- [ ] **Step 4: Ligue em `_apresentar`**

Em `turno.py`, dentro de `_apresentar`, **depois** de `escolhidos = candidatos[:MAX_IMOVEIS_POR_TURNO]` e **antes** do laço de entrega:

```python
    # RN-10.3, e a L1 desta funcao. Gravado ANTES da entrega de proposito: o
    # docstring acima registra que uma falha parcial perde o conjunto
    # escolhido e o turno seguinte pode reapresentar os mesmos imoveis.
    # Gravando aqui, o conjunto e recuperavel mesmo quando a segunda ficha
    # toma um 5xx -- que e a correcao que aquele paragrafo prometeu.
    await gravar_recomendacoes(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        candidatos=escolhidos,
        criterios=criterios,
        agora=datetime.now(UTC),
    )
```

`_apresentar` ganha o parâmetro `criterios: Sequence[str]`, e quem a chama passa `gerada.criterios`. Isso exige que `criterios` viaje do `tool_result` até `gerada` — **siga exatamente o caminho que `candidatos` já percorre**: um extrator ao lado de `_candidatos_de` em `classificador.py`, o valor na tupla de `_chamar`, e um campo em `RespostaDoAgente`. Leia como `candidatos` faz e espelhe.

> A tupla de `_chamar` já tem 8 posições depois da TEC-160. Esta vira a nona. Confira o segundo chamador (`desambiguar`), que descarta os campos com prefixo `_`, e **mantenha o comentário dele verdadeiro** — ele enumera o que não serve àquela chamada.

- [ ] **Step 5: Atualize a L1 no desenho da TEC-162**

`docs/superpowers/specs/2026-09-09-tec-162-ficha-por-canal-design.md` declara a L1 como aberta. Ela deixou de ser. Acrescente uma linha à lacuna dizendo que a TEC-163 a fechou e como — **sem apagar o texto original**, que continua descrevendo o estado da TEC-162.

- [ ] **Step 6: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -v --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_turno.py -q --tb=short
```
Expected: os novos passam e **nenhum dos existentes quebra**.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff format src tests alembic evals
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/ tests/ docs/superpowers/specs/
git commit -m "feat(TEC-163): o conjunto apresentado fica gravado antes de a entrega comecar"
```

**A peça A está entregue.** A RN-10.3 fecha e a L1 da TEC-162 está paga. As tasks seguintes são a B e a C.

---

# PEÇA B — a captura da reação

## Task 4: O schema e a forma da reação

Puro.

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py`, `src/mobia/domain/agente/recomendacao.py`
- Test: `tests/unit/test_recomendacao_regras.py`

**Interfaces:**
- Consumes: `ReacaoLead`, `CategoriaDescarte` (Task 1).
- Produces: `ReacaoDoImovel` (dataclass: `ordinal: int`, `reacao: ReacaoLead`, `categoria: CategoriaDescarte | None`) e `ReacoesDoTurno` (dataclass: `reacoes: tuple[ReacaoDoImovel, ...]`, `modelo: str`) em `agente/schemas.py`; `resolver_ordinais(reacoes, apresentados) -> tuple[tuple[uuid.UUID, ReacaoDoImovel], ...]` em `agente/recomendacao.py`.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/unit/test_recomendacao_regras.py`:

```python
def test_o_ordinal_vira_o_imovel_daquela_posicao() -> None:
    """D7: o modelo devolve ordinal, e o codigo resolve."""
    apresentados = [PRIMEIRO, SEGUNDO, TERCEIRO]
    reacoes = (ReacaoDoImovel(ordinal=2, reacao=ReacaoLead.INTERESSE, categoria=None),)

    assert resolver_ordinais(reacoes, apresentados) == ((SEGUNDO, reacoes[0]),)


def test_ordinal_fora_de_faixa_nao_derruba_os_outros() -> None:
    """D7 e a degradacao do desenho. Um ordinal inventado nao pode invalidar
    os que o modelo acertou -- o lead perderia a reacao correta junto com a
    errada, e o turno nao tem como pedir de novo."""
    apresentados = [PRIMEIRO, SEGUNDO]
    reacoes = (
        ReacaoDoImovel(ordinal=1, reacao=ReacaoLead.DESCARTE, categoria=CategoriaDescarte.DISTANCIA),
        ReacaoDoImovel(ordinal=9, reacao=ReacaoLead.INTERESSE, categoria=None),
    )

    resolvidas = resolver_ordinais(reacoes, apresentados)

    assert [imovel for imovel, _ in resolvidas] == [PRIMEIRO]


def test_ordinal_zero_e_negativo_tambem_saem() -> None:
    """`apresentados[-1]` em Python devolve o ULTIMO item, entao um ordinal
    negativo que passasse pela guarda marcaria o imovel errado -- e o lead
    veria a reacao dele aplicada a outro imovel."""
    apresentados = [PRIMEIRO, SEGUNDO]
    reacoes = (
        ReacaoDoImovel(ordinal=0, reacao=ReacaoLead.INTERESSE, categoria=None),
        ReacaoDoImovel(ordinal=-1, reacao=ReacaoLead.INTERESSE, categoria=None),
    )

    assert resolver_ordinais(reacoes, apresentados) == ()
```

Defina `PRIMEIRO`, `SEGUNDO`, `TERCEIRO` como `uuid.uuid4()` no topo do arquivo, e acrescente os imports.

- [ ] **Step 2: Rode para ver falhar**

Expected: `ImportError`.

- [ ] **Step 3: Implemente as duas formas e o resolvedor**

Em `agente/schemas.py`:

```python
@dataclass(frozen=True, slots=True)
class ReacaoDoImovel:
    """A reacao do lead a UM imovel apresentado, por ordinal. TEC-163, D7.

    **Ordinal e nao `imovel_id`.** Um UUID inventado pelo modelo e
    indistinguivel de um verdadeiro ate bater no banco; um ordinal fora de
    1..N e rejeitado por comparacao com um inteiro. E a disciplina da TEC-161
    aplicada na ENTRADA: o modelo nunca produz identificador que o codigo nao
    consiga conferir.
    """

    ordinal: int
    reacao: ReacaoLead
    categoria: CategoriaDescarte | None = None


@dataclass(frozen=True, slots=True)
class ReacoesDoTurno:
    """O que a segunda chamada devolve. Vazio nao e erro: o lead pode ter
    respondido sem falar de imovel nenhum, e ai todas as linhas pendentes
    fecham como NEUTRO."""

    reacoes: tuple[ReacaoDoImovel, ...]
    modelo: str
```

Em `agente/recomendacao.py`:

```python
def resolver_ordinais(
    reacoes: Sequence[ReacaoDoImovel], apresentados: Sequence[uuid.UUID]
) -> tuple[tuple[uuid.UUID, ReacaoDoImovel], ...]:
    """Casa cada reacao com o imovel daquela posicao. D7.

    **Ordinal fora de 1..N sai, e os outros ficam.** Um ordinal inventado nao
    pode invalidar as reacoes que o modelo acertou: o lead perderia a opiniao
    correta junto com a errada, e o turno nao tem como perguntar de novo.

    A guarda e `1 <= ordinal <= len(apresentados)` e nao um `try/except
    IndexError`, porque `apresentados[-1]` em Python devolve o ULTIMO item em
    vez de levantar -- um ordinal negativo marcaria o imovel errado, em
    silencio, e o lead veria a reacao dele aplicada a outro imovel.
    """
    return tuple(
        (apresentados[reacao.ordinal - 1], reacao)
        for reacao in reacoes
        if 1 <= reacao.ordinal <= len(apresentados)
    )
```

- [ ] **Step 4: Rode e commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_recomendacao_regras.py -v
./.venv/Scripts/python.exe -m ruff format src tests alembic evals
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ tests/unit/
git commit -m "feat(TEC-163): a reacao do lead tem forma, e o ordinal inventado nao contamina os outros"
```

---

## Task 5: `classificador.reagir` — a segunda chamada

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py`
- Test: `tests/unit/test_classificador.py`

**Interfaces:**
- Consumes: `ReacaoDoImovel`, `ReacoesDoTurno` (Task 4).
- Produces: `SISTEMA_DA_REACAO`, `SCHEMA_DA_REACAO`, e `reagir(contexto, apresentados) -> ReacoesDoTurno` no protocolo e na implementação.

- [ ] **Step 1: Corrija o comentário falso de `desambiguar`**

`classificador.py`, no docstring de `desambiguar`, afirma: *"este projeto nao declara nenhum `cache_control` (ver `grep -rn "cache_control" src/ tests/`)"*.

**Isso é falso.** A linha 486 do mesmo arquivo envia `"system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]` desde a TEC-251, e a grep que o comentário manda rodar o desmente. Corrija a premissa mantendo a conclusão na parte em que ela continua valendo: o `system` **é** enviado com `cache_control`, mas `desambiguar` manda um system prompt **diferente** do de `classificar`, então não aproveita o prefixo quente daquela — e `system` precede `messages`, então trocar o system invalida o que vem depois.

Isto entra nesta task porque `reagir` vai sentar ao lado e herdaria a premissa falsa ao raciocinar sobre custo.

- [ ] **Step 2: Escreva os testes que falham**

Em `tests/unit/test_classificador.py`, no molde dos testes existentes de `desambiguar` (encontre com `grep -n "desambiguar" tests/unit/test_classificador.py`):

```python
async def test_reagir_devolve_as_reacoes_por_ordinal() -> None:
    """D6: segunda chamada dedicada, fora do orcamento do prompt principal."""
    # ... monte a resposta falsa do cliente com o JSON das reacoes ...
    resultado = await classificador.reagir(contexto, apresentados=["1. Apto na Trindade"])

    assert resultado.reacoes == (
        ReacaoDoImovel(ordinal=2, reacao=ReacaoLead.INTERESSE, categoria=None),
    )


async def test_reagir_com_resposta_vazia_devolve_tupla_vazia() -> None:
    """Vazio nao e erro: o lead pode ter respondido sem falar de imovel."""
    # ... resposta falsa com lista vazia ...
    assert (await classificador.reagir(contexto, apresentados=["1. Apto"])).reacoes == ()
```

- [ ] **Step 3: Implemente**

```python
SISTEMA_DA_REACAO = (
    "O lead acabou de ver os imoveis abaixo, numerados. Diga, para cada um que "
    "ele mencionou, se houve INTERESSE ou DESCARTE, e no descarte a categoria: "
    "DISTANCIA, PRECO, TAMANHO ou OUTRO. Use o numero do imovel. Imovel que ele "
    "nao mencionou fica de fora da lista."
)
```

Com este comentário acima:

```python
# TEC-163, D6. Segunda chamada, no molde de SISTEMA_DA_DESAMBIGUACAO: este
# texto NAO entra na subcontagem de `test_a_margem_do_orcamento_do_prompt_e_
# deliberada`, que mede SISTEMA_DO_AGENTE, o schema compilado, os rotulos de
# montar_prompt e o `tools=`. Os campos de reacao no schema PRINCIPAL
# custariam ~50 tokens contra uma margem de 6,2 -- por isso a chamada e
# separada, e por isso alongar ESTE texto e barato enquanto alongar aquele nao e.
#
# "Use o numero do imovel" e a D7: ordinal, nunca UUID. O modelo nunca produz
# identificador que o codigo nao consiga conferir.
```

`SCHEMA_DA_REACAO` com uma lista de objetos `{ordinal: integer, reacao: enum, categoria: enum|null}`, e `reagir` chamando `self._chamar` com `system=SISTEMA_DA_REACAO`, os imóveis numerados na mensagem, e sem `tools`/`porta` — esta chamada nunca busca imóvel.

- [ ] **Step 4: Confirme que o orçamento não se mexeu**

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```
Expected: margem **6,2**, inalterada. Se esse número mudou, você tocou o schema principal e não devia.

- [ ] **Step 5: Rode e commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -v --tb=short
./.venv/Scripts/python.exe -m ruff format src tests alembic evals
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/classificador.py tests/unit/
git commit -m "feat(TEC-163): o agente sabe perguntar o que o lead achou dos imoveis"
```

---

## Task 6: Gravar as reações, e fechar as pendentes

**Files:**
- Modify: `src/mobia/domain/agente/repositorio.py`
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: `resolver_ordinais` (Task 4), `Recomendacao` (Task 1).
- Produces: `ler_pendentes(session_factory, *, channel, conversation_key) -> tuple[RecomendacaoPendente, ...]` e `gravar_reacoes(session_factory, *, channel, conversation_key, resolvidas) -> None`, ambas em `repositorio.py`. `RecomendacaoPendente` é um dataclass com `imovel_id`, `titulo`, `bairro`, `preco_centavos`, na ordem de `apresentado_em`.

- [ ] **Step 1: Escreva os testes**

Cubra: `ler_pendentes` devolve só as `reacao_lead IS NULL` desta conversa, **na ordem de `apresentado_em`** (a ordem É o ordinal — "o segundo" é o segundo apresentado); `gravar_reacoes` grava reação e categoria; e **as pendentes não mencionadas fecham como `NEUTRO`** (D8 — sem isso, o lead que muda de assunto por três turnos paga três chamadas).

- [ ] **Step 2..4: Falhar, implementar, passar.** Mesmo ciclo das anteriores.

- [ ] **Step 5: Gates e commit**

```
git commit -m "feat(TEC-163): a reacao do lead fica gravada, e nenhuma linha pendente sobra em aberto"
```

---

## Task 7: Ligar a reação no turno, antes da busca

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: `reagir` (Task 5), `ler_pendentes`/`gravar_reacoes` (Task 6), `resolver_ordinais` (Task 4).
- Produces: nada que tasks seguintes consumam além do estado no banco.

- [ ] **Step 1: Escreva os testes**

**Cenário 1 do Gherkin**: três imóveis apresentados no turno anterior, o lead responde "gostei do segundo", o imóvel correto fica `INTERESSE`. **Cenário 4**: "tem mais alguma coisa?" não marca `DESCARTE` em ninguém e não repete os anteriores. Mais: **falha de `reagir()` não derruba o turno** — as linhas continuam pendentes, o filtro não se ajusta, e a resposta ao lead sai normal.

- [ ] **Step 2: Implemente a ordem da D9**

No início do turno, **antes** de `classificar`:

```python
    # D9. A reacao e capturada ANTES da busca deste turno, e nao depois.
    # O lead escreve "nao gostei desses, tem outros?" -- reacao e busca nova no
    # MESMO turno. Capturando depois, a busca deste turno nao saberia do
    # descarte e devolveria mais do mesmo, que e literalmente a dor da
    # historia da card.
    #
    # `except Exception` amplo: provedor fora, timeout e resposta malformada
    # tem a mesma consequencia aqui, e distinguir nao muda o que o turno faz.
    # Molde de `vetor_da_consulta` e da D6 da TEC-265 -- derrubar a dimensao,
    # nao a busca. O lead perde o ajuste neste turno, nao o atendimento.
```

- [ ] **Step 3..5: Rodar, gates, commit**

```
git commit -m "feat(TEC-163): o que o lead achou dos imoveis chega antes da busca do mesmo turno"
```

---

# PEÇA C — a realimentação e o aviso

## Task 8: `bairros_excluidos` no filtro e no `WHERE`

**Files:**
- Modify: `src/mobia/domain/catalogo/schemas.py`, `src/mobia/domain/catalogo/busca.py`, `src/mobia/domain/catalogo/relaxamento.py`
- Test: `tests/integration/test_relaxamento_busca.py`

**Interfaces:**
- Consumes: nada.
- Produces: `FiltroDeBusca.bairros_excluidos: tuple[str, ...] = ()`, na forma **dobrada**.

- [ ] **Step 1: Escreva os testes — os dois em negrito são o ponto desta task**

```python
async def test_bairro_excluido_nao_volta_pela_zona(session: Any) -> None:
    """D12. O filtro de zona casa o bairro excluido pelo outro lado do OR;
    so a condicao de exclusao, em AND, o segura."""


async def test_bairro_excluido_nao_volta_pelo_relaxamento(session: Any) -> None:
    """**D12, metade 1.** O relaxamento amplia para adjacentes, e o vizinho do
    bairro excluido pode ser o proprio excluido por outro caminho. Iniciativa
    nossa nao anula pedido do lead."""


async def test_relaxou_bairro_e_falso_quando_o_unico_adjacente_era_excluido(
    session: Any,
) -> None:
    """**D12, metade 2.** Sem a subtracao em `alargar`, `relaxou_bairro` sairia
    True e o lead ouviria "inclui bairros vizinhos" tendo recebido zero bairro
    novo -- a mesma classe de mentira que a revisao final da TEC-160 pegou em
    `relaxou_bairro=bool(adjacentes)`."""
```

- [ ] **Step 2: Implemente os dois mecanismos**

No `WHERE` de `busca.py`:

```python
    if filtro.bairros_excluidos:
        # TEC-163, D12. Excluido e excluido, relaxado ou nao. Necessario mesmo
        # sem relaxamento: se o lead pediu "zona sul" e o Campeche foi
        # excluido, o filtro de zona o casa pelo outro lado do OR de regiao --
        # so esta condicao, em AND, o segura.
        condicoes.append(Imovel.bairro_busca.not_in(filtro.bairros_excluidos))
```

E em `alargar`, em `relaxamento.py`, subtraia os excluídos dos adjacentes, com este comentário:

```python
    # TEC-163, D12. Nao e redundancia do NOT IN da busca: sem esta subtracao,
    # `relaxou_bairro` sairia True num relaxamento cujo unico bairro novo era
    # um excluido -- que o WHERE descarta em seguida --, e o lead ouviria
    # "inclui bairros vizinhos" tendo recebido zero bairro novo.
    #
    # O WHERE garante que o imovel excluido NAO VOLTA; esta linha garante que
    # o AVISO NAO MENTE. Um protege o lead do resultado, o outro da frase.
```

- [ ] **Step 3..5: Rodar, gates, commit**

```
git commit -m "feat(TEC-163): bairro que o lead descartou nao volta, nem pelo relaxamento"
```

---

## Task 9: A consulta de exclusão, ligada ao filtro

**Files:**
- Modify: `src/mobia/domain/agente/recomendacao.py`, `src/mobia/domain/agente/repositorio.py`, `src/mobia/domain/agente/ferramenta_de_busca.py`
- Test: `tests/unit/test_recomendacao_regras.py`, `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: `Recomendacao` (Task 1), `bairros_excluidos` (Task 8).
- Produces: `bairros_a_excluir(descartes: Sequence[DescartePorBairro]) -> tuple[str, ...]` (puro, em `recomendacao.py`, com `LIMIAR_DE_DESCARTES = 2`) e `ler_descartes_por_distancia(...)` em `repositorio.py`.

- [ ] **Step 1: Testes puros do limiar**

Um descarte por distância **não** exclui; dois **excluem**; dois descartes de categorias diferentes **não** excluem; descarte com categoria ausente **não conta**.

- [ ] **Step 2: A ligação, e a invariante que ela não pode quebrar**

`ferramenta_de_busca.py` consulta e põe em `bairros_excluidos` — **e só ele**. É a invariante que a TEC-265 escreveu e a TEC-160 respeitou: aquele é o único arquivo onde `domain/agente` toca `domain/catalogo`. A busca continua sem saber que recomendação existe.

**A D14 entra aqui:** bairro que o lead nomear explicitamente neste turno sai da exclusão. Exclusão é inferência nossa; nomear é declaração dele. Teste próprio.

**Dobre os nomes.** Os bairros vêm de `Imovel.bairro_busca` (já dobrado) e as regiões do lead chegam cruas — a TEC-160 quase mandou a metade de bairros da RN-09.3 desligada para produção por não dobrar de um lado.

- [ ] **Step 3..5: Rodar, gates, commit**

```
git commit -m "feat(TEC-163): dois descartes por distancia tiram aquele bairro das buscas seguintes"
```

---

## Task 10: O aviso do ajuste

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Test: `tests/integration/test_apresentacao_no_turno.py`, `tests/unit/test_recomendacao_regras.py`

**Interfaces:**
- Consumes: a exclusão (Task 9).
- Produces: `TEXTO_DO_FILTRO_AJUSTADO`, `KIND_DO_FILTRO_AJUSTADO = "filtro_ajustado"`, `aviso_de_ajuste(bairros) -> str`.

- [ ] **Step 1: Testes**

O aviso **nomeia os bairros** (D15 — divergência deliberada da D11 da TEC-160, porque aqui os bairros são os que o lead descartou, não escolha nossa); é ASCII; **a ordem no turno é identificação → ajuste → ampliação → fichas**, afirmada por índice e não por presença; e **não repete enquanto o ajuste não muda**.

- [ ] **Step 2: Kind próprio, e por quê**

`outbound_dispatches` tem `UNIQUE (message_id, kind)` (`uq_outbound_message_kind`, criada na `0002`). Reusar `KIND_DA_RESPOSTA` faria a mensagem colidir com a identificação e ser descartada como reprocessamento. `"filtro_ajustado"` tem 15 caracteres; a coluna é `String(32)`.

- [ ] **Step 3: Atualize o comentário das trilhas**

`turno.py` tem um comentário que **conta** quantas trilhas chegam ao ponto da moderação do texto constante — a TEC-160 já o corrigiu de três para quatro. Confira se esta card acrescenta uma quinta e, se acrescentar, corrija contagem **e** enumeração. Comentário que conta errado é defeito neste repo.

- [ ] **Step 4..6: Rodar, gates, commit**

```
git commit -m "feat(TEC-163): o lead sabe quais bairros sairam da busca, e por que"
```

---

## Task 11: As três emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

O texto de cada emenda está na seção "As emendas ao SRS" do desenho. Regras:

- Item **aninhado** abaixo da regra, no formato `**Emenda E-nn (TEC-163, 12/09/2026):**`. **Nunca reescreva o texto de 22/08/2026.**
- Três linhas novas no índice do topo: `RN-10.3` E-01, `RN-10.4` E-01, `RN-04.2` **E-03** (a RN-04.2 já tem E-01 da TEC-255 e E-02 da TEC-162 — confira antes de numerar).
- Prosa em `docs/` é **com** acento; o assunto do commit é sem.
- Antes de commitar: `git diff docs/srs/` deve mostrar **só adições**. Qualquer remoção fora da tabela do índice é falha desta task.

```
git commit -m "docs(TEC-163): o SRS admite que Conversa nao e entidade, e diz o que restringir o bairro faz"
```

---

## Task 12: Verificação final

- [ ] **Step 1: Os três gates.**
- [ ] **Step 2: A suíte inteira, com o hash guardado**

```bash
git rev-parse --short HEAD
./.venv/Scripts/python.exe -u -m pytest -v --tb=short > suite.txt 2>&1
```

Leva ~20 minutos. **Guarde o hash junto com o resultado** — a evidência que fecha o argumento contra "é regressão" é a mesma árvore duas vezes.

- [ ] **Step 3: Triagem de falha**

Traceback de `ConnectionResetError [WinError 64]`, `CannotConnectNowError` ou erro de Redis: **rode o arquivo sozinho**. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham sob carga e passam isolados. **Alvo diferente a cada execução é máquina doente, não flake de teste** — e nesse caso a execução inteira não vale.

- [ ] **Step 4: Os quatro cenários da card, nomeados**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -v -k cenario
```

- [ ] **Step 5: PR**

```bash
git push -u origin feat/tec-163-recomendacao-e-reacao
gh pr create --base main --title "TEC-163: registrar a recomendacao e realimentar os filtros com a reacao"
```

O corpo cita o desenho, os quatro cenários, as três emendas, **a L1 da TEC-162 paga**, e as lacunas declaradas — incluindo a do `score_match` (Task 3) e a latência medida (L1 do desenho). Termina com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Auto-revisão deste plano

**Cobertura do desenho:** D1→ordem das tasks; D2,D3→T1; D4,D5→T2; D6→T5; D7→T4; D8→T6; D9→T7; D10→T8,T9; D11→T9; D12→T8; D13→T1; D14→T9; D15→T10; D16→nada a fazer (é uma não-ação, e a T10 a respeita). Emendas→T11. L1 da TEC-162→T3.

**Um defeito do desenho que a escrita do plano encontrou, e que virou a D17 do desenho:** o `score_match` é `NOT NULL`, mas `_candidato_serializavel` **não** expõe `score` ao modelo — a D7 da TEC-265 o removeu de propósito, para o modelo não dizer "97% de compatibilidade" ao lead. Então o turno não tem o score na mão. Gravar `0.0` derrubaria a justificativa da D4, que afirma que o score e o que distingue os imoveis de uma recomendacao. A D17 resolve: a porta e uma closure POR TURNO e carrega os scores por fora do `tool_result`. A Task 3 implementa isso, com teste de que duas portas nao compartilham estado.

**Tasks 6, 7, 9 e 10 têm passos com prosa em vez de código completo.** É deliberado e limitado: os testes ali dependem de fixtures e dublês que já existem naqueles arquivos (`OutboundFake`, os helpers de `test_classificador.py`, o molde de `test_apresentacao_no_turno.py`), e inventar um segundo jeito de montar o mesmo teste é pior que mandar o implementador ler o primeiro. Cada passo diz o que procurar e o que afirmar. **As tasks da peça A — as que precisam valer sozinhas — têm o código completo.**
