# TEC-278 — Um handoff por conversa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enquanto um handoff não é concluído, a conversa não gera outro — e `devolver` passa a concluí-lo, dando ao `CONCLUIDO` o primeiro escritor da vida dele.

**Architecture:** O índice parcial único de `handoffs` deixa de cobrir só `status = 'PENDENTE'` e passa a cobrir `status <> 'CONCLUIDO'`. O `ON CONFLICT DO UPDATE` de `registrar_handoff` já existe e já faz a coisa certa (mescla o gatilho, escala a prioridade, não toca no status); a mudança é apenas em quando ele é alcançado. `POST /api/v1/conversas/devolver` ganha um segundo efeito, espelhando a D6 da TEC-179: assumir aceita o handoff, devolver o conclui.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async (dialeto `postgresql`), Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-278-um-handoff-por-conversa-design.md`

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Prosa em `docs/`: com acento. Nenhum linter checa isto.
- **Comentário desatualizado é defeito, não sujeira.** Esta card torna falso pelo menos um docstring de teste que ela não edita — ver a Task 1, Step 5.
- **Nenhum conteúdo de lead em log.** `channel`, `conversation_key`, ids e `gatilho` são permitidos.
- **Os três gates do CI, nesta ordem e neste escopo:** `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`. **O formatador é gate separado do linter.** Local: `./.venv/Scripts/python.exe -m ...`.
- **`ruff format` NÃO quebra string longa** — um literal comprido continua reprovando `E501` (limite 100) depois de formatado.
- **Nunca um `SELECT` que decide, seguido de um `UPDATE` que grava.** A condição vai no próprio `WHERE` e o `RETURNING` decide a resposta. É o padrão que a TEC-174, a TEC-178 e a TEC-179 gastaram uma decisão cada para estabelecer, porque a suíte roda com oito workers e a corrida é real.
- Testes: `./.venv/Scripts/python.exe -m pytest tests/unit` roda sem Docker. Integração exige `docker compose` de pé.
- Mensagens de commit em português sem acento no assunto, `tipo(TEC-278): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Emendas ao SRS entram como item aninhado `Emenda E-nn (TEC-278, 13/09/2026)` **abaixo** da regra que alteram, nunca reescrevendo o texto de 22/08/2026.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `alembic/versions/0030_handoff_aberto.py` | troca o predicado do índice; encadeia em `0029` |
| `src/mobia/domain/handoff/models.py` | o `postgresql_where` do `Index` (modificar) |
| `src/mobia/domain/handoff/repositorio.py` | o `index_where` do `ON CONFLICT` (modificar) |
| `src/mobia/api/routes/conversas.py` | `devolver` conclui o handoff (modificar) |
| `tests/integration/test_handoff_schema.py` | o invariante, e o docstring que deixou de valer (modificar) |
| `tests/integration/test_rota_de_conversas.py` | a conclusão pelo devolver (modificar) |
| `tests/integration/test_um_handoff_por_conversa.py` | os cenários do Gherkin, ponta a ponta (criar) |

---

### Task 1: O índice passa a cobrir todo handoff aberto

**Files:**
- Create: `alembic/versions/0030_handoff_aberto.py`
- Modify: `src/mobia/domain/handoff/models.py` — o `Index` dentro de `__table_args__` (~linha 170)
- Modify: `src/mobia/domain/handoff/repositorio.py` — o `index_where` do `on_conflict_do_update` (~linha 80)
- Test: `tests/integration/test_handoff_schema.py` (modificar)

**Interfaces:**
- Consumes: nada de tasks anteriores
- Produces: o invariante `um handoff não-CONCLUIDO por (channel, conversation_key)`, do qual as Tasks 2 e 3 dependem

**Contexto que você precisa saber:**

A revisão `head` de hoje é `0029`. Confirme com `./.venv/Scripts/python.exe -m alembic heads` antes de começar; se voltar outra coisa, **pare e reporte BLOCKED**.

**Postgres não permite alterar o predicado de um índice parcial.** A migration tem de `drop_index` e `create_index`. Mantenha o **mesmo nome** — `uq_handoffs_conversa_pendente` — mesmo que ele tenha ficado impreciso. Renomear é churn sem ganho, e o nome aparece em comentário e em teste; se você o renomear, **todos** eles mudam junto. Se preferir renomear mesmo assim, é decisão sua: registre-a no relatório e faça a varredura completa.

**A criação do índice único REPROVA se existir conversa com dois handoffs abertos.** Isso é o comportamento certo e está na L4 do desenho: dois handoffs abertos para a mesma conversa é exatamente o estado que esta card declara impossível, e descobri-lo na migration é melhor que descobri-lo depois. **Não** acrescente limpeza silenciosa de dados.

- [ ] **Step 1: Escreva os testes que falham**

Em `tests/integration/test_handoff_schema.py`, acrescente **dois** testes ao lado dos que já existem (o arquivo já tem `_linha(status=..., conversa=...)` como helper — use-o):

```python
async def test_um_escalado_bloqueia_um_pendente_novo(session: AsyncSession) -> None:
    """O caso que a card existe para fechar (TEC-278).

    Antes desta card o handoff escalado liberava a conversa: o proximo
    gatilho criava outro, com resumo novo e prazo novo, e cinco minutos
    depois a varredura cobrava a gerente pela SEGUNDA vez pelo mesmo lead.
    """
    session.add(_linha(status="ESCALADO"))
    await session.commit()
    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_um_aceito_bloqueia_um_pendente_novo(session: AsyncSession) -> None:
    """Mesmo invariante pelo outro lado: handoff aceito e handoff aberto.

    A TEC-179 ja impedia este caminho por outra via -- assumir silencia a
    conversa, e sem turno nao ha gatilho. Aqui a garantia vira do banco, que
    e onde ela nao depende de nenhum caminho de codigo continuar existindo.
    """
    session.add(_linha(status="ACEITO"))
    await session.commit()
    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Rode e confirme que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -v`
Expected: os dois novos FALHAM (`DID NOT RAISE IntegrityError`); os existentes passam.

- [ ] **Step 3: Escreva a migration**

`alembic/versions/0030_handoff_aberto.py`:

```python
"""o handoff bloqueia a conversa ate ser concluido, nao ate sair de PENDENTE

TEC-278, RF-16.

**Por que o predicado muda.** O indice nasceu na 0023 cobrindo
`status = 'PENDENTE'`, e a L4 do desenho da TEC-174 registrou o porque: nada
tirava handoff de PENDENTE, entao o indice "nunca libera a conversa enquanto a
TEC-178 nao existir -- e e o comportamento certo". A TEC-178 e a TEC-179
chegaram. Um handoff que vira ACEITO ou ESCALADO passou a liberar a chave, e o
proximo gatilho de intencao -- que dispara em TODO turno com a classificacao
certa -- inseria um handoff novo, com resumo novo (chamada paga ao provedor) e
prazo novo. Cinco minutos depois a varredura cobrava a gerente de novo, pelo
mesmo lead.

**Por que `<> 'CONCLUIDO'` e nao um UNIQUE simples.** Um lead atendido meses
atras que volta merece handoff novo. O que separa "aberto" de "encerrado"
passa a ser CONCLUIDO -- que ate a TEC-278 nao tinha escritor nenhum, e ganha
o primeiro em `POST /api/v1/conversas/devolver`. Sem aquele escritor este
indice prenderia cada conversa ao primeiro handoff dela para sempre.

**Drop e create, porque o Postgres nao altera predicado de indice parcial.** O
nome fica como estava: ele aparece em comentario e em teste, e renomear seria
churn.

**A criacao REPROVA se existir conversa com dois handoffs abertos**, e isso e
deliberado (L4 do desenho). Esse estado e o que esta card declara impossivel;
descobri-lo aqui e melhor que descobri-lo depois. Nao ha limpeza silenciosa.
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_NOME = "uq_handoffs_conversa_pendente"


def upgrade() -> None:
    op.drop_index(_NOME, table_name="handoffs")
    op.create_index(
        _NOME,
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'CONCLUIDO'"),
    )


def downgrade() -> None:
    op.drop_index(_NOME, table_name="handoffs")
    op.create_index(
        _NOME,
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )
```

- [ ] **Step 4: Mude o modelo e o `index_where`, que têm de andar juntos**

Em `src/mobia/domain/handoff/models.py`, no `Index` dentro de `__table_args__`, troque `postgresql_where=text("status = 'PENDENTE'")` por `postgresql_where=text("status <> 'CONCLUIDO'")`, e acrescente acima dele um comentário dizendo **por quê** — que o handoff bloqueia a conversa até ser concluído, que `CONCLUIDO` ganhou escritor em `devolver`, e que o nome do índice ficou impreciso de propósito (renomear é churn).

Em `src/mobia/domain/handoff/repositorio.py`, no `on_conflict_do_update`, troque `index_where=text("status = 'PENDENTE'")` pelo mesmo predicado novo. **Os dois têm de casar exatamente**: o `index_where` diz ao Postgres qual índice parcial usar para resolver o conflito, e se ele divergir do índice real o `ON CONFLICT` não encontra índice e o statement estoura.

Escreva um comentário ali dizendo que os dois andam juntos, e onde mora o outro.

- [ ] **Step 5: Corrija o docstring que esta card tornou falso**

`tests/integration/test_handoff_schema.py`, no teste `test_um_concluido_nao_bloqueia_um_pendente_novo`: o docstring diz **"O indice so olha para PENDENTE."** Deixou de ser verdade.

O teste continua correto e continua passando — o que muda é a razão. Reescreva o docstring para dizer que o índice olha para todo handoff **aberto**, e que `CONCLUIDO` é a única saída.

**Este passo é o motivo de a Task 1 existir como está.** A ferramenta `comentarios_tocados.py` marca esse arquivo porque ele muda; mas se você tivesse acrescentado os testes novos noutro arquivo, ela não o marcaria, e o docstring falso sobreviveria.

- [ ] **Step 6: Aplique e rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -v
```
Expected: `alembic heads` passa a `0030`; todos os testes do arquivo PASSAM, incluindo os dois novos.

- [ ] **Step 7: Prove o `downgrade`**

```bash
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: os dois sem erro. Uma migration cujo downgrade ninguém rodou é uma migration que ninguém consegue reverter.

- [ ] **Step 8: Rode os testes de handoff que já existiam**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k handoff -q`
Expected: todos PASSAM. **Se algum falhar, leia antes de consertar**: pode ser um teste que dependia do comportamento antigo e cuja expectativa mudou legitimamente — ou pode ser esta card quebrando algo. Registre qual foi no relatório.

- [ ] **Step 9: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add alembic/versions/0030_handoff_aberto.py src/mobia/domain/handoff/models.py src/mobia/domain/handoff/repositorio.py tests/integration/test_handoff_schema.py
git commit -m "feat(TEC-278): o handoff bloqueia a conversa ate ser concluido"
```

---

### Task 2: `devolver` conclui o handoff

**Files:**
- Modify: `src/mobia/api/routes/conversas.py` — a rota `devolver` (~linha 163-190)
- Test: `tests/integration/test_rota_de_conversas.py` (modificar)

**Interfaces:**
- Consumes: o índice da Task 1; `atendimento_repo.devolver(session, *, channel, conversation_key, corretor_id) -> Atendimento | None`
- Produces: `CONCLUIDO` passa a ter escritor — é o que torna a Task 3 possível

**Contexto que você precisa saber:**

É o espelho exato da D6 da TEC-179, que você encontra na rota `assumir` do mesmo arquivo: **assumir → `ACEITO`, devolver → `CONCLUIDO`**. Leia `assumir` inteira antes de escrever; o `UPDATE` dela é o molde.

`assumir` usa a constante `_ACEITAVEIS`, importada de `handoffs.py`, que é `(PENDENTE, ESCALADO)`. **Para concluir, NÃO use uma lista.** Use `Handoff.status != Status.CONCLUIDO.value`, pelo mesmo raciocínio do predicado do índice: uma lista precisaria ser atualizada toda vez que o enum crescesse, e `!= CONCLUIDO` espelha o índice exatamente e não pode divergir dele. Escreva isso no comentário.

**A rota `devolver` ainda não calcula `agora`.** A função `devolver` do repositório calcula o dela própria e devolve só o carimbo de quem tinha assumido. Você vai precisar de um `agora = datetime.now(UTC)` na rota para o `atualizado_em` do handoff. `from datetime import UTC, datetime` **já está** na linha 19 do arquivo, e `update` já vem de `sqlalchemy` na linha 23 — não duplique imports.

Confira também de onde `Handoff` e `Status` vêm no arquivo: `assumir` já usa os dois.

**Uma conversa sem handoff aberto devolve normalmente.** O `UPDATE` casar zero linhas não é erro — nem toda conversa assumida gerou handoff. Não acrescente guarda de resultado.

- [ ] **Step 1: Escreva os testes que falham**

Em `tests/integration/test_rota_de_conversas.py`, ao lado dos que já existem (copie a montagem do `test_assumir_aceita_o_handoff_pendente_junto`, que já sabe criar handoff e chamar a rota):

```python
async def test_devolver_conclui_o_handoff_aberto(...):
    """D2: o espelho da D6 da TEC-179. Assumir aceita, devolver conclui.

    E a valvula de saida do indice da Task 1: sem ela a conversa ficaria
    presa ao mesmo handoff para sempre, porque `CONCLUIDO` nao tinha
    escritor nenhum antes desta card.
    """


async def test_devolver_conclui_tambem_o_handoff_escalado(...):
    """Nao ha lista de estados: o criterio e "nao esta CONCLUIDO".

    Um handoff escalado que alguem assumiu e devolveu esta tao encerrado
    quanto um aceito.
    """


async def test_devolver_sem_handoff_nenhum_funciona(...):
    """Nem toda conversa assumida gerou handoff -- exigir um quebraria o
    caso comum, pelo mesmo argumento que `assumir` ja aplica."""


async def test_devolver_duas_vezes_nao_toca_o_handoff_na_segunda(...):
    """A segunda devolucao ja e 409 (a conversa nao esta assumida), entao o
    UPDATE do handoff nem chega a rodar. Este teste prova que o 409 vem
    ANTES, e nao que o UPDATE e idempotente por acaso."""
```

**Escreva os corpos**, seguindo o estilo do arquivo. Para o último, assere o `atualizado_em` do handoff — se o `UPDATE` rodasse na segunda chamada, ele andaria.

- [ ] **Step 2: Rode e confirme que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_conversas.py -v -k devolver`
Expected: os três primeiros FALHAM (o handoff continua no status anterior).

- [ ] **Step 3: Acrescente o `UPDATE` à rota**

Em `src/mobia/api/routes/conversas.py`, dentro de `devolver`, **depois** do `if atendimento is None:` e **antes** do `await session.commit()`:

```python
        # D2 do desenho: o espelho da Emenda E-02 da RN-16.4, que fez
        # `assumir` aceitar o handoff. Aqui ele e CONCLUIDO -- o handoff
        # existe para entregar o lead a um humano, e quando o humano devolve
        # a conversa ao agente essa entrega acabou.
        #
        # **`!= CONCLUIDO` e nao uma lista de estados**, ao contrario do
        # `_ACEITAVEIS` que `assumir` usa tres funcoes acima. Duas razoes: o
        # criterio aqui e literalmente "ainda esta aberto", e uma lista
        # precisaria de manutencao toda vez que o enum crescesse; e este e
        # exatamente o predicado do indice parcial
        # `uq_handoffs_conversa_pendente` (ver `handoff/models.py`), que os
        # dois precisam espelhar para nao divergirem em silencio.
        #
        # Casar zero linhas nao e erro: nem toda conversa assumida gerou
        # handoff, mesmo argumento que `assumir` ja aplica.
        #
        # **Concluir o handoff NAO encerra a conversa** -- a RN-02.3 junta os
        # dois e a emenda da TEC-278 os separa. Devolver a conversa ao agente
        # e retomar o atendimento automatico, nao encerra-lo.
        await session.execute(
            update(Handoff)
            .where(
                Handoff.channel == pedido.channel,
                Handoff.conversation_key == pedido.conversation_key,
                Handoff.status != Status.CONCLUIDO.value,
            )
            .values(status=Status.CONCLUIDO.value, atualizado_em=agora)
        )
```

E acrescente `agora = datetime.now(UTC)` no início do bloco `async with`, se ainda não houver.

- [ ] **Step 4: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_conversas.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_aceite.py tests/integration/test_escalada_de_sla.py -q
```
Expected: todos PASSAM. Os dois últimos porque `CONCLUIDO` ganhou escritor e eles vivem no mesmo território.

- [ ] **Step 5: Falsifique**

Comente o `UPDATE` que você acrescentou. Rode `test_devolver_conclui_o_handoff_aberto`. Ele **tem** de reprovar. Restaure. Registre a saída no relatório.

- [ ] **Step 6: O docstring de `Status` deixou de valer**

`src/mobia/domain/handoff/vocabulario.py:39` diz **`"""CONCLUIDO ainda nao tem escritor -- a TEC-179 nao o trouxe. Ver o modelo."""`**. Esta task o trouxe. Corrija — e confira se `src/mobia/domain/handoff/models.py` tem a frase gêmea (a TEC-179 corrigiu as duas juntas uma vez; procure por `CONCLUIDO` no arquivo).

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/api/routes/conversas.py src/mobia/domain/handoff/vocabulario.py src/mobia/domain/handoff/models.py tests/integration/test_rota_de_conversas.py
git commit -m "feat(TEC-278): devolver conclui o handoff, e CONCLUIDO ganha escritor"
```

---

### Task 3: Os cenários do Gherkin, ponta a ponta

**Files:**
- Test: `tests/integration/test_um_handoff_por_conversa.py` (criar)

**Interfaces:**
- Consumes: o índice (Task 1); `devolver` concluindo (Task 2)
- Produces: nada — é a prova de que as duas tasks anteriores entregam o comportamento que a card pede

**Contexto que você precisa saber:**

A Task 1 prova o **invariante de schema** escrevendo linhas direto no modelo. Esta task prova o **comportamento**: que o lead conversando de verdade não gera handoff novo, e que a gerente não é cobrada duas vezes.

Use as fixtures que já existem: `rodar_turno` (`tests/conftest.py:481`), com a assinatura

```python
await rodar_turno(
    session, classificador, outbound, resumidor, contador,
    moderador=None, agendador=None, *, texto=TEXTO_PADRAO_DO_LEAD,
) -> str
```

e os dublês `classificador_fake`, `outbound_fake`, `resumidor_fake`, `contador_fake`, `moderador_fake`, mais `semear_corretor`. **Abra `tests/integration/test_handoff_no_turno.py`** — ele já exercita a criação de handoff pelo turno e é o molde mais próximo.

**A armadilha desta branch, herdada da TEC-179:** `rodar_turno` chama `executar_turno(get_sessionmaker(), ...)`, então o turno abre sessões **próprias**. Qualquer estado que você montar com a fixture `session` tem de ser **commitado** antes.

**Para o cenário da escalada**, use `escalar_vencidos` (`src/mobia/domain/handoff/escalada.py`), assinatura `escalar_vencidos(session_factory, *, canais, limite=100) -> int` — ela devolve **quantos** escalou, e é esse número que prova "a gerente não é cobrada duas vezes".

- [ ] **Step 1: Escreva os quatro testes**

Crie `tests/integration/test_um_handoff_por_conversa.py`. Um por cenário do Gherkin:

```python
"""Um handoff por conversa enquanto ele nao se encerra. TEC-278."""


async def test_lead_escalado_que_continua_conversando_nao_gera_handoff_novo(...):
    """Primeiro cenario, e a razao de existir da card.

    Monte: handoff PENDENTE pelo turno, prazo vencido, `escalar_vencidos`
    marca ESCALADO e devolve 1. Depois rode outro turno que dispare o
    gatilho de intencao.

    Assere DUAS coisas: `SELECT count(*) FROM handoffs` continua 1, e uma
    segunda passagem de `escalar_vencidos` devolve **0**. So a primeira
    asercao passaria mesmo se o handoff novo nascesse e ainda nao tivesse
    vencido -- e a cobranca dupla da gerente e o dano que a card nomeia.
    """


async def test_lead_aceito_que_continua_conversando_nao_gera_handoff_novo(...):
    """Segundo cenario. Aqui o handoff esta ACEITO, e o turno roda mesmo
    assim -- a conversa NAO foi silenciada (o aceite veio pela rota de
    handoffs, nao por `assumir`). E exatamente o caminho da L2 do desenho."""


async def test_conversa_concluida_aceita_um_handoff_novo(...):
    """Terceiro cenario, e a prova de que a valvula da Task 2 funciona.

    Um lead atendido meses atras que volta merece handoff novo. Conclua o
    handoff e rode um turno com gatilho: nasce linha nova, e sao 2 no total.
    """


async def test_o_gatilho_novo_acumula_em_gatilhos_adicionais(...):
    """O que a mesclagem de fato faz com o gatilho que nao virou handoff.

    Nao e so "nada acontece": o `ON CONFLICT` acumula o gatilho novo em
    `gatilhos_adicionais` sem duplicar, e escala `prioridade` para ALTA
    quando e o caso. Este teste existe para que a proxima pessoa saiba onde
    o sinal foi parar -- ele nao se perde, so nao chega a ninguem (L1).
    """
```

**Escreva os corpos.** Para o primeiro, o handoff precisa de `sla_limite_em` no passado — grave-o direto no modelo, como `test_escalada_de_sla.py` faz.

- [ ] **Step 2: Rode**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_um_handoff_por_conversa.py -v`
Expected: PASSAM, porque as Tasks 1 e 2 já entregaram o comportamento. **Se algum falhar, é achado real** — significa que o invariante de schema não produz o comportamento que a card pede, e o relatório tem de dizer qual e por quê.

- [ ] **Step 3: Falsifique o primeiro**

Reverta o predicado do índice para `status = 'PENDENTE'` (só no modelo, não na migration — é temporário), rode `test_lead_escalado_que_continua_conversando_nao_gera_handoff_novo`, confirme que reprova, restaure com `git checkout --`. Registre a saída.

Se o teste **passar** com o índice antigo, ele não prova nada e precisa ser reescrito.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add tests/integration/test_um_handoff_por_conversa.py
git commit -m "feat(TEC-278): os quatro cenarios provados pelo turno, nao so pelo schema"
```

---

### Task 4: As emendas e o fechamento

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: Escreva as duas emendas**

**Nunca reescreva o texto de 22/08/2026.** Cada emenda é item aninhado abaixo da regra que altera. Veja como as emendas da TEC-177, TEC-178 e TEC-179 estão escritas no mesmo arquivo e siga o formato.

1. **Abaixo da RN-02.3** (`grep -n "RN-02.3" docs/srs/...`) — `Emenda E-01 (TEC-278, 13/09/2026)`: concluir o handoff **não** encerra a conversa. A regra original junta *"30 dias sem interação, ou por handoff concluído, ou por opt-out"* como se fossem o mesmo fato; este sistema precisa separá-los. O handoff acaba quando o humano termina o atendimento — e `POST /api/v1/conversas/devolver`, que é quem o conclui, significa **retomar** o atendimento automático, não encerrá-lo. Se concluir encerrasse, o lead que o corretor acabou de atender voltaria a falar com um agente sem memória do que aconteceu. O encerramento de conversa segue sendo por inatividade (TEC-130) ou opt-out. **A TEC-130 tem de respeitar essa separação quando chegar.**

2. **Abaixo da RN-16.4** — `Emenda E-04 (TEC-278, 13/09/2026)` (confira o número: a TEC-179 deixou E-01 a E-03 ali): `POST /api/v1/conversas/devolver` passa a **concluir** o handoff aberto da conversa, espelhando a Emenda E-02 que fez `assumir` aceitá-lo. É o que dá ao `CONCLUIDO` o primeiro escritor, e sem ele o índice de `handoffs` — que desde esta card cobre todo status menos `CONCLUIDO` — prenderia a conversa ao primeiro handoff dela para sempre.

- [ ] **Step 2: A suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: tudo verde. **Guarde o hash junto com o resultado.**

Se falhar, rode **de novo sobre a mesma árvore** antes de culpar sua mudança. E se aparecerem dezenas de `relation ... does not exist`, leia a seção do CLAUDE.md sobre os bancos dos workers com o carimbo adiantado — isso repete idêntico na segunda execução e não é a sua migration.

- [ ] **Step 3: Comentários tocados, e a busca à mão**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

**Esta branch muda um invariante e a ferramenta não vê fora do diff.** Procure à mão quem descreve o que mudou:

- qualquer texto que diga que o índice cobre `PENDENTE`, ou que um handoff não-pendente libera a conversa
- a **L4 do desenho da TEC-174** (`docs/superpowers/specs/`) — ela dizia que o índice "nunca libera a conversa enquanto a TEC-178 não existir". Specs datadas são histórico e **não se corrigem**; o que se confere é se algum **código** repete aquela afirmação.
- qualquer comentário que afirme que `CONCLUIDO` não tem escritor
- `src/mobia/domain/handoff/escalada.py` e `agendador.py`, que falam sobre quando um handoff sai de `PENDENTE`

- [ ] **Step 4: Os três gates e `alembic heads`**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m alembic heads
```
Expected: três verdes, e **uma só cabeça** (`0030`).

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-278): duas emendas -- devolver conclui, e concluir nao encerra"
```

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 1. D2 → Task 2. D3 → Task 4. D4 → Task 3 (o quarto teste prova que a mesclagem acumula sem renotificar; a guarda de `criado` já existia e a card não a toca). L1–L4 → declaradas; sem task, por construção.

**Consistência de tipos:** o predicado `status <> 'CONCLUIDO'` aparece na migration, no `postgresql_where` do modelo e no `index_where` do repositório — os três têm de casar, e a Task 1 diz isso explicitamente. A rota da Task 2 usa `Handoff.status != Status.CONCLUIDO.value`, que é o mesmo predicado em SQLAlchemy e está justificado no comentário.

**Ordem:** a Task 2 depende da Task 1 (sem o índice novo, concluir não muda nada observável) e a Task 3 depende das duas. A Task 1 sozinha deixa a árvore num estado em que a conversa trava — é por isso que as duas primeiras não devem ser separadas por muito tempo, mas continuam sendo tasks distintas porque um revisor pode aprovar o índice e rejeitar a rota.

**Três pontos que o executor decide e registra:** se renomeia o índice (o nome ficou impreciso); se o 409 de `devolver` deve vir antes ou depois do `UPDATE` do handoff (o plano assume antes, e o quarto teste da Task 2 o prova); e o que fazer se algum teste existente de handoff reprovar na Task 1, Step 8.
