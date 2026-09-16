# TEC-136 — Tratar mudança de intenção preservando os campos válidos

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a intenção acumulada do lead muda para uma intenção de outra banda de valor, o orçamento gravado é descartado (e a marca de "já perguntei" com ele), a mudança fica registrada em tabela própria, e a trilha do score diz que o motivo foi a troca de intenção.

**Architecture:** Uma função nova em `context/repositorio.py` roda **antes** de `gravar_estado`, no mesmo bloco transacional do turno: toma `SELECT ... FOR UPDATE` na linha de qualificação, compara a intenção acumulada com a do turno, e — quando as bandas diferem — anula a faixa e remove a marca do orçamento por `UPDATE`, gravando uma linha de histórico. `gravar_estado` roda logo depois, **sem alteração nenhuma**, e escreve o orçamento novo por cima quando o lead o disse no mesmo turno.

**Tech Stack:** Python 3.13, SQLAlchemy async, Postgres, Alembic, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-15-tec-136-mudanca-de-intencao-design.md`

## Desvio declarado em relação à D3 do desenho

**O desenho põe o descarte dentro do `ON CONFLICT DO UPDATE` de `gravar_estado`, com um `CASE`. Este plano o põe num `UPDATE` separado, antes do upsert, e não toca em `gravar_estado`.**

A razão é que a D6 já exige `SELECT ... FOR UPDATE` para o histórico saber a intenção **anterior**. Com esse lock na mão, a intenção anterior está em Python — e o `CASE` em SQL passa a não comprar nada: ele existia só para decidir sem ter lido o valor antigo. As duas garantias que a D3 protegia continuam de pé, pelo lock em vez de pela atomicidade do `CASE`.

Ganhos concretos da forma deste plano:

- `gravar_estado` fica **intocada**, e os seus 30 sítios de chamada em quatro arquivos não se mexem.
- O descarte vira uma função com nome próprio, testável sozinha, em vez de mais um ramo no `set_` que a docstring do próprio arquivo chama de "o trecho mais denso de `gravar_estado`".
- A ordem "descarta, depois grava" faz o turno que traz número novo funcionar sem caso especial: o `UPDATE` anula, o upsert escreve o valor novo por cima.

Se quem revisa preferir a forma da D3, a diferença é local a esta decisão e não muda nenhuma outra tarefa.

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o valor.
- **Prosa em `docs/`: COM acento.**
- **Nada do bloco de investidor é descartado**, nem `forma_pagamento`, nem `tem_imovel_para_vender`. Só a faixa de preço. (D2)
- **`perguntas_feitas` continua monotônico.** Nada decrementa o contador do teto da RN-05.5.
- **`test_null_nao_apaga` tem de continuar passando.** O descarte é caminho distinto, não afrouxamento da garantia "None no campo não apaga".
- **A regra das bandas mora em `dinheiro.py`.** Nenhuma tabela de bandas transcrita para outro módulo ou para dentro do SQL.
- **O nome da marca do orçamento vem de `_MARCA_DO_ORCAMENTO`**, nunca de um literal — o nome tem três grafias no repo e o comentário daquela constante termina em "Nao apague".
- **Mensagem de commit:** `tipo(TEC-136): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates, com este escopo exato, antes de qualquer commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Testes:** `tests/unit/` não precisa de Docker; `tests/integration/` exige `docker compose` de pé. Rode o arquivo inteiro, sem `-k`.

---

## File Structure

| arquivo | responsabilidade |
| --- | --- |
| `src/mobia/domain/agente/dinheiro.py` (modifica) | a regra de qual intenção compartilha banda com qual |
| `src/mobia/domain/context/models.py` (modifica) | o modelo `ConversationIntentAudit` |
| `alembic/versions/0035_auditoria_de_intencao.py` (cria) | a tabela |
| `src/mobia/domain/context/repositorio.py` (modifica) | `intencao_e_gravavel` e `aplicar_mudanca_de_intencao` |
| `src/mobia/domain/context/auditoria.py` (modifica) | `CAUSA_MUDANCA_DE_INTENCAO` |
| `src/mobia/domain/agente/turno.py` (modifica) | chama a função nova e informa a causa |
| `tests/unit/test_bandas_de_intencao.py` (cria) | a regra pura |
| `tests/integration/test_mudanca_de_intencao.py` (cria) | descarte, preservação e histórico |

---

### Task 1: A regra de banda

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py` (logo depois de `_BANDAS` e do comentário de `_BANDA_FROUXA`)
- Test: `tests/unit/test_bandas_de_intencao.py` (cria)

**Interfaces:**
- Consumes: nada
- Produces: `mudou_de_banda(antiga: Intencao | None, nova: Intencao) -> bool`

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_bandas_de_intencao.py`:

```python
"""Quais trocas de intencao invalidam o orcamento ja declarado. TEC-136.

Puro: nao toca banco nem modelo. O que se testa e a REGRA -- quais pares de
intencao mudam a banda de valor --, e nao o efeito dela no estado.
"""

import pytest

from mobia.domain.agente.dinheiro import mudou_de_banda
from mobia.domain.agente.schemas import Intencao


@pytest.mark.parametrize(
    ("antiga", "nova"),
    [
        (Intencao.ALUGUEL, Intencao.COMPRA),
        (Intencao.COMPRA, Intencao.ALUGUEL),
        (Intencao.ALUGUEL, Intencao.INVESTIMENTO),
        (Intencao.INVESTIMENTO, Intencao.ALUGUEL),
    ],
)
def test_trocar_entre_aluguel_e_venda_muda_a_banda(antiga: Intencao, nova: Intencao) -> None:
    """O caso da card, nos dois sentidos e pelas duas intencoes de compra.

    `_BANDA_DE_ALUGUEL` vai de R$ 300 a R$ 200 mil e `_BANDA_DE_COMPRA` de
    R$ 30 mil a R$ 1 bilhao: um numero admitido sob uma nao significa o mesmo
    sob a outra, e e por isso que o orcamento nao atravessa a troca.
    """
    assert mudou_de_banda(antiga, nova) is True


@pytest.mark.parametrize(
    ("antiga", "nova"),
    [
        (Intencao.COMPRA, Intencao.INVESTIMENTO),
        (Intencao.INVESTIMENTO, Intencao.COMPRA),
        (Intencao.COMPRA, Intencao.VENDER_IMOVEL),
        (Intencao.COMPRA, Intencao.COMPRA),
        (Intencao.ALUGUEL, Intencao.ALUGUEL),
    ],
)
def test_mesma_banda_nao_invalida_o_orcamento(antiga: Intencao, nova: Intencao) -> None:
    """A contraprova, e ela e a que impede o descarte incondicional.

    COMPRA, INVESTIMENTO e VENDER_IMOVEL partilham `_BANDA_DE_COMPRA`. Um lead
    que decide investir em vez de morar continua com o mesmo orcamento
    significando a mesma coisa -- apagar ali seria reperguntar por nada.
    """
    assert mudou_de_banda(antiga, nova) is False


def test_sem_intencao_anterior_a_banda_muda() -> None:
    """A segunda porta do defeito, a que o Gherkin da card nao menciona.

    Faixa gravada com a intencao acumulada ainda nula quer dizer que o numero
    foi admitido sob `_BANDA_FROUXA`, a uniao das duas. O comentario de
    `piso_do_numero_nu` descreve o estrago: "o valor admitido enquanto a
    intencao era INDEFINIDA sobrevive para dentro de uma conversa depois
    classificada COMPRA e vira o filtro da busca la".
    """
    assert mudou_de_banda(None, Intencao.COMPRA) is True
    assert mudou_de_banda(None, Intencao.ALUGUEL) is True


@pytest.mark.parametrize("nova", [Intencao.SUPORTE_CONTRATO, Intencao.INDEFINIDA])
def test_intencao_sem_banda_propria_nao_descarta(nova: Intencao) -> None:
    """Quem nao esta em `_BANDAS` cai na banda frouxa, e frouxa nao invalida.

    Nao ha caminho que chame isto com INDEFINIDA -- `campos_a_gravar` nunca a
    grava --, e a guarda existe para que a regra seja total em vez de depender
    do chamador. SUPORTE_CONTRATO chega: e intencao gravavel e nao tem banda.
    """
    assert mudou_de_banda(Intencao.COMPRA, nova) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_bandas_de_intencao.py --tb=short`
Expected: FAIL com `ImportError: cannot import name 'mudou_de_banda'`

- [ ] **Step 3: Write minimal implementation**

Em `dinheiro.py`, logo depois do bloco de `_BANDA_FROUXA`:

```python
def mudou_de_banda(antiga: Intencao | None, nova: Intencao) -> bool:
    """A intencao nova admite valores de outra faixa que a antiga? TEC-136.

    Existe aqui, e nao em `context/`, porque a resposta e uma consequencia de
    `_BANDAS` -- a mesma tabela que `parsear` usa para recusar numero
    implausivel. Duas copias dessa tabela divergiriam em silencio, e a
    divergencia so apareceria como orcamento sobrevivendo a uma troca que
    deveria te-lo apagado.

    `antiga is None` e "a conversa ainda nao tinha intencao acumulada quando o
    numero foi dito", e devolve True de proposito: o valor entrou sob
    `_BANDA_FROUXA`, que e a uniao das duas e portanto nao validou nada. E a
    porta que o comentario de `piso_do_numero_nu` descreve.

    Intencao fora de `_BANDAS` devolve False -- a banda frouxa nao restringe,
    entao nao ha o que invalidar. Vale para SUPORTE_CONTRATO, que e gravavel,
    e nao chega a valer para INDEFINIDA, que `campos_a_gravar` nunca grava.
    """
    if nova not in _BANDAS:
        return False
    if antiga is None:
        return True
    return _BANDAS.get(antiga) is not _BANDAS[nova]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_bandas_de_intencao.py --tb=short`
Expected: 12 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/dinheiro.py tests/unit/test_bandas_de_intencao.py
git commit -m "feat(TEC-136): a regra de qual troca de intencao invalida o orcamento

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A tabela de histórico

**Files:**
- Modify: `src/mobia/domain/context/models.py` (depois de `LeadScoreAudit`)
- Create: `alembic/versions/0035_auditoria_de_intencao.py`
- Test: coberta pela Task 4; esta tarefa entrega schema, e o teste dela é o `alembic upgrade head` rodar

**Interfaces:**
- Consumes: nada
- Produces: `ConversationIntentAudit` com as colunas `id`, `channel`, `conversation_key`, `de`, `para`, `faixa_descartada`, `created_at`

- [ ] **Step 1: Escrever o modelo**

Em `models.py`, depois de `LeadScoreAudit`:

```python
class ConversationIntentAudit(Base):
    """Uma linha por mudanca da intencao ACUMULADA. Append-only. TEC-136.

    Nao e `conversation_intent`: aquela guarda a saida crua do classificador e
    e sobrescrita a cada turno, de proposito. Virar historico la escreveria
    uma linha por turno da conversa inteira para responder uma pergunta que
    muda meia duzia de vezes.

    Nao e `lead_score_audit`: aquela so grava quando o resultado MUDA (a tupla
    vazia de `causas_do_recalculo` e o sinal de nao gravar), entao uma troca de
    intencao que nao mexesse em nenhum dos cinco fatores sumiria -- e o
    Gherkin da card pede que a mudanca fique registrada, mexendo ou nao no
    score.

    `de` e nulo na primeira vez que a conversa ganha intencao acumulada. A
    linha existe mesmo assim, e nao so nas trocas de verdade, porque e ela que
    explica o descarte: NULL -> COMPRA apaga o orcamento dito sob banda
    frouxa, e sem esta linha o orcamento sumiria sem registro nenhum.

    `clock_timestamp()` e nao `now()`, pela razao que `lead_score_audit`
    escreve por extenso: `now()` congela no primeiro statement da transacao, e
    dois turnos concorrentes da mesma conversa sairiam carimbados pela ordem em
    que COMECARAM. O INSERT acontece com o lock de `lead_qualification` na
    mao, entao o relogio de statement da uma ordem total igual a do lock.
    """

    __tablename__ = "conversation_intent_audit"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nulo so na primeira vez. Ver o docstring acima.
    de: Mapped[str | None] = mapped_column(String(16), nullable=True)
    para: Mapped[str] = mapped_column(String(16), nullable=False)
    # Redundante com `de`/`para` mais a tabela de bandas, e deliberado: quem le
    # a trilha quer saber se o lead perdeu o que tinha dito sem ter de
    # reimplementar `mudou_de_banda` em SQL. E a mesma razao que `total_novo`
    # e denormalizado em `lead_score_audit`.
    faixa_descartada: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        Index(
            "ix_conversation_intent_audit_conversa",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )
```

**Confira os imports do topo de `models.py` antes de commitar:** `uuid`, `datetime`, `Boolean`, `Index`, `text`, `PGUUID` e `String` já devem estar lá por causa de `LeadScoreAudit`. Acrescente só o que faltar.

- [ ] **Step 2: Escrever a migration**

Crie `alembic/versions/0035_auditoria_de_intencao.py`:

```python
"""trilha append-only das mudancas de intencao acumulada

TEC-136, RN-03.3. Uma linha por mudanca de `lead_qualification.intencao`.

Sem FK para `lead_qualification`, pela razao da 0010 e da 0012: a retencao
desta trilha nao pode ser encurtada por cascata da limpeza de outra tabela.

`clock_timestamp()` e nao `now()` pelo argumento que a 0012 escreve por
extenso -- o INSERT acontece com o lock de `lead_qualification` na mao, varios
statements depois do primeiro da transacao, e `now()` carimbaria pela ordem em
que os turnos COMECARAM.

A trigger recusa UPDATE e nao DELETE, como a da 0012 e pela mesma razao:
imutavel significa "nao se altera o que foi registrado", e expurgo por politica
de retencao e ato deliberado.

Sem CHECK ligando `faixa_descartada` a `de`/`para`: a regra de banda mora em
`dinheiro.py` e transcreve-la para uma restricao do banco criaria a segunda
copia que o proprio `mudou_de_banda` existe para evitar.

Revision ID: 0035
Revises: 0034
"""

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_FUNCAO_DA_TRIGGER = """
CREATE FUNCTION conversation_intent_audit_recusa_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'conversation_intent_audit e imutavel: UPDATE recusado';
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER conversation_intent_audit_imutavel
    BEFORE UPDATE ON conversation_intent_audit
    FOR EACH ROW EXECUTE FUNCTION conversation_intent_audit_recusa_update()
"""


def upgrade() -> None:
    op.create_table(
        "conversation_intent_audit",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("de", sa.String(16), nullable=True),
        sa.Column("para", sa.String(16), nullable=False),
        sa.Column("faixa_descartada", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
    )
    op.create_index(
        "ix_conversation_intent_audit_conversa",
        "conversation_intent_audit",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )
    op.execute(_FUNCAO_DA_TRIGGER)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS conversation_intent_audit_imutavel ON conversation_intent_audit")
    op.execute("DROP FUNCTION IF EXISTS conversation_intent_audit_recusa_update()")
    op.drop_index("ix_conversation_intent_audit_conversa", table_name="conversation_intent_audit")
    op.drop_table("conversation_intent_audit")
```

**Confira o import de `postgresql` no topo** — a 0012 usa `from sqlalchemy.dialects import postgresql` e depois `postgresql.UUID(...)`. Siga o que estiver lá em vez de `sa.dialects.postgresql`.

- [ ] **Step 3: Acrescentar a tabela ao TRUNCATE dos testes**

Em `tests/conftest.py`, acrescente `conversation_intent_audit` à tupla `TABELAS`. Ela entra no mesmo `TRUNCATE a, b, c CASCADE` que já existe — não é um statement a mais por teste, é uma tabela a mais no mesmo statement.

- [ ] **Step 4: Rodar a migration nos dois sentidos**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: os três sem erro. Se o primeiro reprovar com `ConnectionResetError [WinError 64]` na negociação SSL, espere e retente — é conhecido neste repo e não é defeito de código.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/models.py alembic/versions/0035_auditoria_de_intencao.py tests/conftest.py
git commit -m "feat(TEC-136): a mudanca de intencao tem tabela propria, append-only

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: O descarte e o histórico

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (acrescenta `intencao_e_gravavel` junto de `campos_a_gravar`, e `aplicar_mudanca_de_intencao` depois de `gravar_estado`)
- Test: `tests/integration/test_mudanca_de_intencao.py` (cria)

**Interfaces:**
- Consumes: `mudou_de_banda` (Task 1); `ConversationIntentAudit` (Task 2)
- Produces: `MudancaDeIntencao` (dataclass com `de: str | None`, `para: str`, `faixa_descartada: bool`) e `aplicar_mudanca_de_intencao(session, *, channel, conversation_key, intencao) -> MudancaDeIntencao | None`

**`gravar_estado` NÃO é alterada nesta tarefa nem em nenhuma outra.**

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_mudanca_de_intencao.py`. A fixture `session` e os helpers de semeadura estão em `tests/conftest.py`; **confira como `test_repositorio_contexto.py` semeia estado antes de escrever** e use o mesmo caminho.

```python
"""O descarte do orcamento quando a intencao troca de banda. TEC-136."""

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.models import ConversationIntentAudit, LeadQualification
from mobia.domain.context.repositorio import (
    aplicar_mudanca_de_intencao,
    gravar_estado,
    ler_estado,
)

CANAL = "whatsapp"


async def _semear(session, chave: str, intencao: Intencao, **extras) -> None:
    """Grava um estado inicial pelo caminho de producao, e nao por INSERT cru.

    Passar pelo `gravar_estado` de verdade e o que garante que o estado de
    partida destes testes e um estado que o turno de fato produz -- um INSERT
    a mao poderia montar combinacao que `campos_a_gravar` nunca gera.
    """
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=chave,
        intencao=intencao,
        extracao=Extracao(**extras),
    )
    await session.flush()


async def test_trocar_de_aluguel_para_compra_descarta_o_orcamento(session) -> None:
    """O cenario 2 do Gherkin: o valor mensal nao vira faixa de preco de compra.

    R$ 2.500 e um aluguel plausivel e um preco de compra absurdo. Ate esta
    card ele sobrevivia a troca e virava o filtro da busca de compra.
    """
    # 250_000 centavos = R$ 2.500. Dentro de `_BANDA_DE_ALUGUEL` (R$ 300 a
    # R$ 200 mil) e ABAIXO do piso de `_BANDA_DE_COMPRA` (R$ 30 mil): e o par
    # de numeros que torna o cenario da card verificavel em vez de plausivel.
    await _semear(
        session,
        "5511900000001",
        Intencao.ALUGUEL,
        faixa_preco_max_centavos=250_000,
        regiao="zona sul",
        quartos=2,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000001",
        intencao=Intencao.COMPRA,
    )

    assert mudanca is not None
    assert mudanca.faixa_descartada is True

    estado = await ler_estado(session, CANAL, "5511900000001")
    assert estado is not None
    assert estado.faixa_preco_min_centavos is None
    assert estado.faixa_preco_max_centavos is None
    # O cenario 1 do Gherkin, na mesma asserta: o que continua valido fica.
    assert estado.regiao == "zona sul"
    assert estado.quartos == 2


async def test_o_orcamento_volta_a_ser_perguntavel(session) -> None:
    """A D4: descartar o campo sem tirar a marca nao repergunta nada.

    Este teste afirma o EFEITO, e nao so o conteudo do array: com a marca de
    `faixa_preco_max` ainda no `perguntados_sem_resposta`, o agente trataria o
    orcamento como ja perguntado e o cenario 2 do Gherkin ("E o agente pergunta
    o orcamento de compra") nunca aconteceria.
    """
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key="5511900000002",
        intencao=Intencao.ALUGUEL,
        extracao=Extracao(regiao="centro"),
        perguntou=("faixa_preco_expressao",),
    )
    await session.flush()
    antes = await ler_estado(session, CANAL, "5511900000002")
    assert antes is not None
    assert "faixa_preco_max" in (antes.perguntados_sem_resposta or [])

    await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000002",
        intencao=Intencao.COMPRA,
    )

    depois = await ler_estado(session, CANAL, "5511900000002")
    assert depois is not None
    assert "faixa_preco_max" not in (depois.perguntados_sem_resposta or [])


async def test_mesma_banda_preserva_o_orcamento(session) -> None:
    """A contraprova. Sem ela, um descarte incondicional passaria nos outros."""
    await _semear(
        session,
        "5511900000003",
        Intencao.COMPRA,
        faixa_preco_max_centavos=80_000_000,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000003",
        intencao=Intencao.INVESTIMENTO,
    )

    assert mudanca is not None
    assert mudanca.faixa_descartada is False
    estado = await ler_estado(session, CANAL, "5511900000003")
    assert estado is not None
    assert estado.faixa_preco_max_centavos is not None


async def test_turno_indefinido_nao_muda_nada(session) -> None:
    """INDEFINIDA nunca grava intencao, entao nunca pode disparar descarte.

    E o turno mais comum de todos depois do primeiro: um "obrigado" no meio da
    conversa classifica INDEFINIDA. Se ele descartasse, o orcamento do lead
    evaporaria por educacao.
    """
    await _semear(
        session,
        "5511900000004",
        Intencao.ALUGUEL,
        faixa_preco_max_centavos=250_000,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000004",
        intencao=Intencao.INDEFINIDA,
    )

    assert mudanca is None
    estado = await ler_estado(session, CANAL, "5511900000004")
    assert estado is not None
    assert estado.faixa_preco_max_centavos is not None


async def test_a_mudanca_grava_uma_linha_de_historico(session) -> None:
    """Uma linha por troca, com origem e destino."""
    await _semear(session, "5511900000005", Intencao.ALUGUEL, regiao="centro")

    await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000005",
        intencao=Intencao.COMPRA,
    )
    await session.flush()

    linhas = (
        await session.scalars(
            select(ConversationIntentAudit).where(
                ConversationIntentAudit.conversation_key == "5511900000005"
            )
        )
    ).all()
    assert len(linhas) == 1
    assert linhas[0].de == Intencao.ALUGUEL.value
    assert linhas[0].para == Intencao.COMPRA.value


async def test_a_intencao_repetida_nao_grava_historico(session) -> None:
    """Todo turno chama esta funcao; so a MUDANCA gera linha.

    Sem esta guarda a tabela ganharia uma linha por turno, que e exatamente o
    que o docstring do modelo diz que ela nao e.
    """
    await _semear(session, "5511900000006", Intencao.COMPRA, regiao="centro")

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000006",
        intencao=Intencao.COMPRA,
    )
    await session.flush()

    assert mudanca is None
    linhas = (
        await session.scalars(
            select(ConversationIntentAudit).where(
                ConversationIntentAudit.conversation_key == "5511900000006"
            )
        )
    ).all()
    assert linhas == []


async def test_sem_linha_de_qualificacao_nao_faz_nada(session) -> None:
    """Primeiro turno da conversa: nao ha estado, nao ha o que descartar.

    `aplicar_mudanca_de_intencao` roda ANTES de `gravar_estado`, entao no
    primeiro turno a linha ainda nem existe. Devolver None aqui e o que impede
    a funcao de criar linha -- criar moveria o score do lead pelo mesmo
    argumento que o `if not campos:` de `gravar_estado` ja registra.
    """
    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000007",
        intencao=Intencao.COMPRA,
    )

    assert mudanca is None
    assert await session.get(LeadQualification, (CANAL, "5511900000007")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_mudanca_de_intencao.py --tb=short`
Expected: FAIL com `ImportError: cannot import name 'aplicar_mudanca_de_intencao'`

- [ ] **Step 3: Write minimal implementation**

Primeiro, junto de `campos_a_gravar`, extraia a regra que hoje está embutida nela:

```python
def intencao_e_gravavel(intencao: Intencao) -> bool:
    """Esta intencao chega a ser gravada em `lead_qualification.intencao`?

    Extraida de `campos_a_gravar` na TEC-136 para ter UM dono. A pergunta
    passou a ter um segundo interessado (`aplicar_mudanca_de_intencao`, que so
    descarta quando a intencao de fato muda a coluna), e duas copias da regra
    divergiriam no dia em que uma oitava intencao entrasse no enum.
    """
    return intencao not in (Intencao.FORA_DE_ESCOPO, Intencao.INDEFINIDA)
```

E faça `campos_a_gravar` usá-la, **sem mudar o comportamento dela**:

```python
    if intencao is Intencao.FORA_DE_ESCOPO:
        return {}
    if not intencao_e_gravavel(intencao):
        return extracao.preenchidos()
    return {"intencao": intencao.value, **extracao.preenchidos()}
```

Depois, a função nova, logo abaixo de `gravar_estado`:

```python
@dataclass(frozen=True)
class MudancaDeIntencao:
    """O que a troca de intencao deste turno mudou. TEC-136."""

    de: str | None
    para: str
    faixa_descartada: bool


async def aplicar_mudanca_de_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
) -> MudancaDeIntencao | None:
    """Descarta o que a intencao nova invalida e registra a troca. RN-03.3.

    Devolve `None` quando nao houve mudanca a aplicar: intencao que nao se
    grava, conversa sem estado ainda, ou intencao igual a que ja estava.

    **Roda ANTES de `gravar_estado`, e a ordem e o desenho.** O descarte e um
    UPDATE que anula a faixa; o upsert de `gravar_estado` vem depois e escreve
    por cima o valor novo quando o lead o disse no mesmo turno ("na verdade
    quero comprar, ate 800 mil"). Invertendo a ordem, o descarte apagaria o
    numero que o lead acabou de dar.

    **Nao cria linha.** Primeiro turno da conversa nao tem estado a invalidar,
    e criar linha aqui moveria o score do lead pelo mesmo argumento que o
    `if not campos:` de `gravar_estado` registra por extenso.

    **O lock nao e decorativo.** Turnos da mesma conversa nao sao
    serializados -- a deduplicacao do ARQ e por mensagem, nao por conversa --,
    e sem ele dois turnos concorrentes leem a mesma intencao anterior e ambos
    gravam linha de historico para a mesma troca. E a corrida que
    `registrar_recalculo` fechou com este mesmo cadeado. Ele ja e tomado nesta
    transacao, mais adiante, por aquela funcao: tomar aqui antes preserva a
    ordem de aquisicao e nao cria deadlock novo.
    """
    if not intencao_e_gravavel(intencao):
        return None

    estado = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if estado is None:
        return None

    antiga = Intencao(estado.intencao) if estado.intencao is not None else None
    if antiga is intencao:
        return None

    descartar = mudou_de_banda(antiga, intencao)
    if descartar:
        await session.execute(
            update(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .values(
                faixa_preco_min_centavos=None,
                faixa_preco_max_centavos=None,
                # `array_remove` e o mesmo built-in que `_sem_os_respondidos`
                # usa, e pela mesma razao: Postgres nao tem subtracao de array.
                # O nome vem de `_MARCA_DO_ORCAMENTO` porque a marca tem tres
                # grafias no repo e escrever qualquer uma a mao reintroduziria
                # a divergencia que aquela constante fechou.
                perguntados_sem_resposta=func.array_remove(
                    LeadQualification.perguntados_sem_resposta, _MARCA_DO_ORCAMENTO
                ),
            )
        )

    session.add(
        ConversationIntentAudit(
            id=uuid.uuid4(),
            channel=channel,
            conversation_key=conversation_key,
            de=estado.intencao,
            para=intencao.value,
            faixa_descartada=descartar,
        )
    )
    # Flush e nao commit: a sessao e emprestada, como em `gravar_estado`, e a
    # linha tem de estar visivel a uma leitura posterior na mesma transacao.
    await session.flush()
    return MudancaDeIntencao(de=estado.intencao, para=intencao.value, faixa_descartada=descartar)
```

**Confira quatro coisas antes de commitar, porque o plano não as adivinha:**
1. `update`, `func`, `uuid` e `dataclass` já estão importados em `repositorio.py`? Acrescente o que faltar.
2. `mudou_de_banda` e `ConversationIntentAudit` precisam de import novo.
3. `Intencao(estado.intencao)` levanta `ValueError` se a coluna tiver string fora do enum. Ela é escrita só por `campos_a_gravar`, sempre a partir de `Intencao.value` — confirme e, se for o caso, deixe como está em vez de acrescentar guarda para um caso que não existe.
4. A sessão pode já ter a linha carregada no identity map. `gravar_estado` resolve isso com `populate_existing=True` e o comentário de lá explica por quê; confira se o `select ... with_for_update` daqui precisa do mesmo.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_mudanca_de_intencao.py --tb=short`
Expected: 7 passed

- [ ] **Step 5: Gates, arquivos vizinhos e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py tests/integration/test_repositorio_contexto.py tests/unit/test_estado_marcado.py --tb=short
```

O terceiro comando é o que prova que a extração de `intencao_e_gravavel` não mudou o comportamento de `campos_a_gravar`, e que `test_null_nao_apaga` continua passando.

```bash
git add src/mobia/domain/context/repositorio.py tests/integration/test_mudanca_de_intencao.py
git commit -m "feat(TEC-136): a troca de banda descarta o orcamento e registra a mudanca

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A ligação no turno e a causa na trilha

**Files:**
- Modify: `src/mobia/domain/context/auditoria.py` (a causa nova)
- Modify: `src/mobia/domain/context/repositorio.py` (`registrar_recalculo` ganha `causas_externas`)
- Modify: `src/mobia/domain/agente/turno.py` (o bloco transacional perto de `gravar_estado`)
- Test: acrescenta a `tests/integration/test_mudanca_de_intencao.py`

**Interfaces:**
- Consumes: `aplicar_mudanca_de_intencao` (Task 3)
- Produces: nada que tarefas posteriores consumam

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_mudanca_de_intencao.py`. **Confira a assinatura de `rodar_turno` e o `ClassificadorFake` em `tests/conftest.py` antes de escrever** — `test_encaminhamento_por_intencao.py` é o arquivo irmão a copiar.

```python
async def test_a_troca_de_intencao_aparece_na_trilha_do_score(
    session, outbound, resumidor, contador, rodar_turno
) -> None:
    """O cenario 3 do Gherkin, e o unico ponto em que a D7 muda um invariante.

    `registrar_recalculo` grava a trilha quando `causas_do_recalculo` devolve
    alguma coisa, e tupla vazia e o sinal declarado de NAO gravar. Uma troca de
    intencao que nao mova nenhum dos cinco fatores cairia nesse vazio e sumiria
    -- e a card pede que a mudanca fique registrada COM o motivo. A causa vem
    do chamador, como as duas que `auditoria.py` ja declara sem produtor.
    """
    primeiro = ClassificadorFake(
        intencao=Intencao.ALUGUEL,
        extracao=Extracao(faixa_preco_max_centavos=250_000, regiao="zona sul"),
    )
    await rodar_turno(
        session,
        primeiro,
        outbound,
        resumidor,
        contador,
        texto="procuro apartamento para alugar na zona sul ate 2500",
    )

    segundo = ClassificadorFake(intencao=Intencao.COMPRA, extracao=Extracao())
    await rodar_turno(
        session,
        segundo,
        outbound,
        resumidor,
        contador,
        texto="na verdade quero comprar",
    )

    trilha = (
        await session.scalars(
            select(LeadScoreAudit).order_by(LeadScoreAudit.created_at.desc()).limit(1)
        )
    ).first()
    assert trilha is not None
    assert CAUSA_MUDANCA_DE_INTENCAO in trilha.causas
```

Acrescente ao topo do arquivo os imports que este teste precisa: `from conftest import ClassificadorFake` (o idioma do repo, ver `test_cancelamento_do_worker.py`), `LeadScoreAudit` de `mobia.domain.context.models` e `CAUSA_MUDANCA_DE_INTENCAO` de `mobia.domain.context.auditoria`.

**Confira dois pontos antes de rodar**, porque o plano não os adivinha:

1. **A conversa tem de ser a mesma nos dois turnos.** `rodar_turno` semeia a entrada por `_entrada_do_lead`, e é a `conversation_key` dela que decide se o segundo turno enxerga o estado do primeiro. Se o helper gerar chave nova a cada chamada, o teste passa a medir outra coisa — use o caminho que `test_encaminhamento_por_intencao.py` usa para encadear turnos na mesma conversa.
2. **O segundo turno tem de mudar a intenção sem mexer em nenhum fator do score**, senão o teste passa pelo motivo errado: `causas_do_recalculo` acharia diferença sozinho e a linha existiria mesmo sem a D7. `Extracao()` vazia no segundo turno é o que garante isso — se ainda assim algum fator se mover (a contagem de mensagens alimenta `engajamento`), afirme também que a causa da troca está lá **junto** das outras, e diga no relatório que o teste não isola a D7 sozinho.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_mudanca_de_intencao.py --tb=short`
Expected: FAIL — a trilha não menciona a troca

- [ ] **Step 3: Write minimal implementation**

Em `auditoria.py`, junto das duas causas sem produtor:

```python
# Da mesma natureza das duas acima -- fato sobre a ORIGEM do gatilho, e nao
# sobre o que se moveu --, e por isso tambem informada pelo chamador em vez de
# derivada do diff. A diferenca e que esta JA TEM produtor: a TEC-136.
CAUSA_MUDANCA_DE_INTENCAO = "MUDANCA_DE_INTENCAO"
```

Em `registrar_recalculo`, acrescente o parâmetro e una antes da guarda:

```python
    causas_externas: tuple[str, ...] = (),
```

```python
    causas = causas_externas + causas_do_recalculo(_score_do_registro(ultimo), novo)
    if not causas:
```

Documente na docstring **por que a união vem antes da guarda**: a tupla vazia continua sendo o sinal de "não grave", e uma causa informada pelo chamador é uma razão para gravar mesmo quando nenhum fator se moveu — que é exatamente o caso de uma troca de intenção que não mexe no score.

Em `turno.py`, no bloco transacional, **antes** da chamada a `gravar_estado`:

```python
        mudanca = await aplicar_mudanca_de_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
        )
```

e na chamada a `registrar_recalculo`:

```python
            causas_externas=(CAUSA_MUDANCA_DE_INTENCAO,) if mudanca is not None else (),
```

Escreva no comentário do sítio por que a chamada vem **antes** de `gravar_estado` (a ordem descarta-depois-grava da Task 3) — sem isso, o próximo leitor move a linha.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_mudanca_de_intencao.py --tb=short`
Expected: 8 passed

- [ ] **Step 5: Gates, suíte inteira e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta. Se falhar, rode de novo sobre a mesma árvore antes de culpar a mudança — há falhas conhecidas de `ConnectionResetError [WinError 64]` e de flake sob carga neste repo. Se persistir idêntica em duas execuções, **pare e relate**.

**Atenção especial nesta suíte:** `tests/integration/test_auditoria_score.py` fixa o vocabulário de causas e o comportamento de "não grava quando nada muda". Se algum teste de lá reprovar, **não o relaxe sem entender**: ou ele fixa o invariante que a D7 muda de propósito — e aí é atualizar e declarar no relatório qual era e por quê — ou pegou regressão de verdade.

```bash
git add src/mobia/domain/context/auditoria.py src/mobia/domain/context/repositorio.py src/mobia/domain/agente/turno.py tests/integration/test_mudanca_de_intencao.py
git commit -m "feat(TEC-136): o turno aplica a troca de intencao e a trilha diz o motivo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A prosa que a mudança tornou desatualizada

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py` (o comentário de `piso_do_numero_nu`)
- Modify: `src/mobia/domain/context/repositorio.py` (os comentários que afirmam que nada apaga)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emenda à RN-03.3)

- [ ] **Step 1: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main --tudo
```

Releia o que ela apontar, com atenção aos `VIZINHO`. Ela é cega a docstring de módulo (TEC-283, aberta) — confira à mão a docstring de topo de cada arquivo tocado.

- [ ] **Step 2: Corrigir o comentário de `piso_do_numero_nu`**

Ele diz hoje que *"`campos_a_gravar` nunca APAGA e turno nenhum revalida o que ja esta gravado, entao o valor admitido enquanto a intencao era INDEFINIDA sobrevive para dentro de uma conversa depois classificada COMPRA e vira o filtro da busca la"*.

**A segunda metade deixou de ser verdade** — é exatamente o que esta card conserta. A primeira metade continua verdadeira (`campos_a_gravar` de fato não apaga; quem apaga é `aplicar_mudanca_de_intencao`). Reescreva mantendo a distinção e apontando para quem agora fecha a porta.

- [ ] **Step 3: Reconferir os comentários que afirmam que nada apaga**

`repositorio.py` afirma "None no campo nao apaga" em pelo menos três docstrings (`campos_a_gravar`, `gravar_estado`, `gravar_investidor`). **As três continuam verdadeiras** — o descarte não é `None` num campo, é um UPDATE explícito por outro caminho. Não as reescreva por reflexo; acrescente a ressalva **só** onde um leitor concluiria que nenhum campo jamais é apagado nesta tabela, o que depois desta card é falso.

Julgue cada uma. Diga no relatório quais mudou e quais deixou, com a razão.

- [ ] **Step 4: Emendar o SRS**

A RN-03.3 é a regra de mudança de intenção. Acrescente **`Emenda E-01 (TEC-136, 15/09/2026)`** como item aninhado abaixo dela — a RN-03.3 não tem emenda hoje, então `E-01` é o próximo livre; **confirme** antes de escrever. **Sem reescrever** o texto de 22/08/2026.

A emenda declara: o descarte vale para toda troca de **banda de valor**, e não só para o par ALUGUEL↔COMPRA do Gherkin; conversa sem intenção acumulada conta como troca, porque o número entrou sob banda frouxa; só o orçamento é descartado, e `forma_pagamento`, `tem_imovel_para_vender` e o bloco de investidor sobrevivem; o teto de perguntas não devolve nada; e a mudança fica em `conversation_intent_audit`, com a trilha do score nomeando a causa.

Prosa em `docs/` vai **COM** acento.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/dinheiro.py src/mobia/domain/context/repositorio.py docs/srs/
git commit -m "docs(TEC-136): a RN-03.3 ganha a emenda do descarte, e o comentario para de dizer que o valor sobrevive

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite da card

| cenário Gherkin | onde é exercitado |
| --- | --- |
| Migrar de aluguel para compra preservando o que continua válido | T3 teste 1 — região e quartos sobrevivem, faixa vai a `NULL` |
| Valor que perde sentido não é reaproveitado | T3 testes 1 e 2 — a faixa é apagada **e** volta a ser perguntável |
| A mudança fica registrada no histórico | T3 testes 5 e 6 — uma linha por troca, nenhuma quando a intenção repete |
| Mudança dispara recálculo do score | T4 — a trilha grava com `CAUSA_MUDANCA_DE_INTENCAO` mesmo quando nenhum fator se move |
| "a qualificação é reavaliada" | já existia: `registrar_recalculo` roda em todo turno |

**Lacunas declaradas** (todas no desenho, e vão no comentário da card): `forma_pagamento` e `tem_imovel_para_vender` sobrevivem e inflam a completude; o bloco de investidor sobrevive inteiro; o teto de perguntas não devolve nada; buscas anteriores à troca não são refeitas; um lead que oscile entre intenções gera uma linha por oscilação e perde o orçamento em cada uma.
