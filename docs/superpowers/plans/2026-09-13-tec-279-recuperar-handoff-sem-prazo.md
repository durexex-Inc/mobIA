# TEC-279 — Recuperar o handoff que ficou sem prazo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um handoff que ficou `PENDENTE` sem prazo porque o enfileiramento falhou volta a ser visto, e o critério não depende do dado que a falha apagou.

**Architecture:** Uma função nova no domínio, `recuperar_sem_prazo`, no molde exato de `escalar_vencidos`: recebe `session_factory` e uma porta, devolve quantos recuperou. Ela seleciona pelo **estado** (`PENDENTE`, sem prazo, sem `notificado_em`, sem `aviso_manual_pendente`, mais velho que dez minutos) e reenfileira `gerar_resumo` ou `notificar` conforme o handoff já tenha resumo. Entra no `sweep_sla`, que já roda de cinco em cinco minutos.

**Tech Stack:** Python 3.13, SQLAlchemy async, ARQ, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-279-recuperar-handoff-sem-prazo-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento. Nenhum linter checa isto.
- **Comentário desatualizado é defeito, não sujeira.**
- **Nenhum conteúdo de lead em log.** `channel`, `conversation_key`, `handoff_id`, `gatilho`, `etiqueta` e `prioridade` são permitidos. Corpo de mensagem, resumo e dossiê **nunca**.
- **Os três gates do CI, nesta ordem e neste escopo:** `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`. **O formatador é gate separado do linter.** Local: `./.venv/Scripts/python.exe -m ...`.
- **`ruff format` NÃO quebra string longa** — E501, limite 100.
- **Nunca use um dublê de teste como default de produção.** Nada de `ctx.get("x") or NoopX()` — ver a guarda em `workers/main.py`.
- **Esta card NÃO cria migration e NÃO emenda o SRS.** Se você se vir escrevendo qualquer um dos dois, pare: o desenho não prevê, e isso é sinal de que algo saiu do escopo.
- Mensagens de commit em português sem acento no assunto, `tipo(TEC-279): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/handoff/recuperacao.py` | a porta, o adaptador ARQ e `recuperar_sem_prazo` (criar) |
| `src/mobia/domain/notificacao/envio.py` | passa a ser a casa de `NOTIFICAR_JOB` (modificar) |
| `src/mobia/workers/jobs/notificar.py` | importa `NOTIFICAR_JOB` do domínio (modificar) |
| `src/mobia/workers/jobs/sweep_sla.py` | chama a recuperação junto com a escalada (modificar) |
| `src/mobia/workers/main.py` | `ctx["reenfileirador"]` (modificar) |
| `tests/integration/test_recuperacao_sem_prazo.py` | os quatro cenários do Gherkin (criar) |

---

### Task 1: A porta e a recuperação

**Files:**
- Create: `src/mobia/domain/handoff/recuperacao.py`
- Test: `tests/integration/test_recuperacao_sem_prazo.py`

**Interfaces:**
- Consumes: `Handoff` e `Status` de `mobia.domain.handoff`; `GERAR_RESUMO_JOB` de `mobia.domain.handoff.agendador`; `NOTIFICAR_JOB` de `mobia.domain.notificacao.envio` (**ver a mudança de casa abaixo**)
- Produces:
  - `INTERVALO_DE_RECUPERACAO: timedelta` (dez minutos)
  - `class ReenfileiradorPort(Protocol)` com `agendar_resumo(handoff_id: uuid.UUID) -> None` e `agendar_notificacao(handoff_id: uuid.UUID) -> None`
  - `class ReenfileiradorArq` — `__init__(self, pool: ArqRedis)`
  - `async def recuperar_sem_prazo(session_factory, *, reenfileirador: ReenfileiradorPort, limite: int = 100) -> int`

**Contexto que você precisa saber:**

**Abra `src/mobia/domain/handoff/escalada.py` inteiro antes de escrever uma linha.** É o molde: mesma assinatura (`session_factory` posicional, porta por keyword, `limite` com default 100), mesmo formato de docstring, mesmo estilo de log. `recuperar_sem_prazo` é a irmã dela.

**Abra também `src/mobia/domain/handoff/agendador.py`** — é o molde da porta e do adaptador ARQ, incluindo a convenção de `_job_id`. **Não** copie o `AgendadorNoop`: ele existe porque ~30 testes de turno o passam como default, e um noop de reenfileirador não teria usuário nenhum — seria código morto, que o rubrico de revisão trata como defeito.

**`NOTIFICAR_JOB` muda de casa, e isto é parte da task.** Hoje ele é definido em `src/mobia/workers/jobs/notificar.py`. Importá-lo de lá faria `domain/` depender de `workers/` — e **nenhum módulo de `src/mobia/domain/` importa `mobia.workers` hoje**; a direção é sempre a inversa. `GERAR_RESUMO_JOB` mora em `domain/handoff/agendador.py` exatamente por isso, e é o worker que o importa.

Mova `NOTIFICAR_JOB = "notificar_corretor"` para `src/mobia/domain/notificacao/envio.py`, onde mora a função `notificar` do domínio, e faça `workers/jobs/notificar.py` importá-lo de lá. `workers/jobs/gerar_resumo.py` já o importa de `workers/jobs/notificar.py` e **continua funcionando sem mudança**. Escreva um comentário na constante dizendo por que ela mora no domínio.

Os dois `_job_id` que você tem de reusar, **exatamente como já existem**:
- `gerar_resumo` → `_job_id=f"resumo:{handoff_id}"` (em `agendador.py:48`)
- `notificar` → `_job_id=f"notificar:{handoff_id}"` (em `workers/jobs/gerar_resumo.py:46`)

Reusá-los é o que faz o reenfileiramento ser idempotente **enquanto o job original estiver vivo**. Depois que ele termina, a chave some (`keep_result=0`) — e é por isso que o critério da D1 precisa das três colunas, não do `_job_id`.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_recuperacao_sem_prazo.py`. **Abra `tests/integration/test_escalada_de_sla.py` e copie a montagem dele** — ele já tem os helpers `_marcar_sla` e `_marcar_status` e sabe criar handoff.

O dublê da porta:

```python
class _ReenfileiradorEspiao:
    """Registra o que foi reenfileirado, e para qual handoff.

    E a unica prova da D3: sem ele o teste so saberia que algo foi
    reenfileirado, nao QUAL job -- e a escolha entre `gerar_resumo` e
    `notificar` e justamente a decisao que a D3 toma.
    """

    def __init__(self) -> None:
        self.resumos: list[uuid.UUID] = []
        self.notificacoes: list[uuid.UUID] = []

    async def agendar_resumo(self, handoff_id: uuid.UUID) -> None:
        self.resumos.append(handoff_id)

    async def agendar_notificacao(self, handoff_id: uuid.UUID) -> None:
        self.notificacoes.append(handoff_id)
```

Os seis testes, com corpo:

```python
async def test_handoff_sem_resumo_reenfileira_a_geracao(session, session_factory, banco_limpo):
    """Primeiro ramo da D3. `gerar_resumo` gera E enfileira `notificar` no fim.

    Reenfileirar `notificar` direto aqui perderia o resumo para sempre: o
    corretor receberia `TEXTO_SEM_RESUMO`, que e o caminho degradado da D2 da
    TEC-177 -- legitimo quando o resumo falhou, indevido quando ele nem foi
    tentado.
    """
    # handoff PENDENTE, resumo NULL, criado ha 20 minutos
    # assere: espiao.resumos == [handoff_id] e espiao.notificacoes == []


async def test_handoff_com_resumo_reenfileira_so_a_notificacao(
    session, session_factory, banco_limpo
):
    """Segundo ramo da D3, e a razao de ele existir.

    `gerar_resumo` NAO checa se o resumo ja existe -- ele carrega o dossie e
    chama o redator incondicionalmente. Reenfileira-lo aqui pagaria uma
    segunda chamada ao provedor por nada.
    """
    # mesmo handoff, com `resumo` preenchido (bytes quaisquer -- a
    # recuperacao so olha se e nulo, nunca decifra)
    # assere: espiao.notificacoes == [handoff_id] e espiao.resumos == []


async def test_handoff_recem_criado_nao_e_recuperado(session, session_factory, banco_limpo):
    """Segundo cenario do Gherkin -- passa por construcao (D2).

    O caminho normal ainda pode concluir. Recuperar aqui competiria com ele:
    o `_job_id` fixo protege enquanto o job original esta vivo, mas nao
    depois que ele termina.
    """
    # handoff criado agora
    # assere: devolve 0, e o espiao nao recebeu nada


async def test_handoff_ja_notificado_nao_e_recuperado(session, session_factory, banco_limpo):
    """Quarto cenario do Gherkin -- passa por construcao (D2).

    `notificado_em` preenchido significa que `notificar` rodou e um canal
    aceitou. Reenfileirar duplicaria a notificacao.
    """
    # handoff velho, `sla_limite_em` nulo, mas `notificado_em` preenchido
    # assere: devolve 0


async def test_handoff_com_aviso_manual_pendente_nao_e_recuperado(
    session, session_factory, banco_limpo
):
    """`notificar` rodou e NENHUM canal aceitou.

    Nao e um handoff perdido -- e um que o sistema ja viu e cujo desfecho ja
    esta gravado. A D1 exige `aviso_manual_pendente = false` exatamente por
    isso.
    """
    # handoff velho, prazo nulo, `notificado_em` nulo, mas
    # `aviso_manual_pendente=True`
    # assere: devolve 0


async def test_handoff_escalado_sem_destinatario_nao_e_recuperado(
    session, session_factory, banco_limpo
):
    """Terceiro cenario do Gherkin -- passa por construcao (D2).

    `notificar` marca ESCALADO quando nao ha corretor nenhum (emenda E-02 da
    RN-16.3), e o prazo fica nulo PARA SEMPRE. O `status = 'PENDENTE'` da D1
    ja o filtra -- este teste existe para provar que continua assim.
    """
    # handoff velho, prazo nulo, status ESCALADO, aviso_manual_pendente=True
    # assere: devolve 0
```

**Escreva os corpos.** Para "criado há 20 minutos", grave `criado_em` no passado direto no modelo — `criado_em` não tem `server_default`, então você o controla.

- [ ] **Step 2: Rode e confirme que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_recuperacao_sem_prazo.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.recuperacao'`

- [ ] **Step 3: Escreva o módulo**

`src/mobia/domain/handoff/recuperacao.py`. Estrutura obrigatória:

- Docstring de módulo dizendo **por que a rede de segurança de hoje não pega este caso**: `escalar_vencidos` exige `sla_limite_em IS NOT NULL`, o prazo é gravado pelo job de notificação, e se o enfileiramento falha o prazo nunca existe — a rede depende da peça que falhou.
- `INTERVALO_DE_RECUPERACAO = timedelta(minutes=10)`, com comentário dizendo **as duas razões** do número: folgado para o caminho normal concluir com provedor lento e uma retentativa do ARQ, e **dentro do SLA de 15 minutos do lead QUENTE**, para a recuperação não gravar um prazo que já nasce vencido.
- `ReenfileiradorPort` e `ReenfileiradorArq` — no molde de `agendador.py`, com os dois `_job_id` reusados verbatim. **Sem noop** (ver acima).
- `recuperar_sem_prazo(session_factory, *, reenfileirador, limite=100) -> int`.

O `SELECT`, com as cinco condições da D1:

```python
        candidatos = (
            await session.execute(
                select(Handoff.id, Handoff.resumo)
                .where(
                    Handoff.status == Status.PENDENTE.value,
                    Handoff.sla_limite_em.is_(None),
                    Handoff.notificado_em.is_(None),
                    Handoff.aviso_manual_pendente.is_(False),
                    Handoff.criado_em < agora - INTERVALO_DE_RECUPERACAO,
                )
                # Mais velho primeiro, mesmo criterio de `escalar_vencidos`:
                # sob o teto de `limite`, quem esta perdido ha mais tempo nao
                # fica esfomeado por handoffs perdidos depois.
                .order_by(Handoff.criado_em)
                .limit(limite)
            )
        ).all()
```

**Escreva no docstring por que as três condições do meio existem juntas**, porque é a decisão inteira da card: `notificar` grava `sla_limite_em` cedo e `notificado_em`/`aviso_manual_pendente` no fim, e nenhum dos três preenchido é a assinatura de "essa função nunca rodou". Um handoff em que ela rodou e a entrega falhou tem `aviso_manual_pendente = true` e **não** é perdido — é um que o sistema já viu.

O laço:

```python
    for linha in candidatos:
        if linha.resumo is None:
            await reenfileirador.agendar_resumo(linha.id)
        else:
            await reenfileirador.agendar_notificacao(linha.id)
        log.warning(
            "handoff.recuperado_sem_prazo",
            handoff_id=str(linha.id),
            tinha_resumo=linha.resumo is not None,
        )
```

**`warning` e não `info`**, pelo mesmo critério do `outbound.optout_bloqueou`: uma linha aqui significa que um handoff ficou invisível tempo suficiente para a rede de emergência agir. Não é erro nosso — a guarda funcionou —, mas é o sintoma de que o enfileiramento falhou em algum ponto.

**Nunca o `resumo` no log** — só se ele é nulo ou não. O campo é `LargeBinary` cifrado, e decifrá-lo aqui seria trabalho inútil e vazamento.

**A recuperação NÃO grava nada no handoff.** Ela só reenfileira. Quem grava `sla_limite_em` é o `notificar`, e quem grava o resumo é o `gerar_resumo` — a D4 não tem contador e a card não acrescenta coluna nenhuma. Se você se vir escrevendo um `update(Handoff)`, pare e releia a D4.

- [ ] **Step 4: Rode**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_recuperacao_sem_prazo.py -v`
Expected: os seis PASSAM.

- [ ] **Step 5: Falsifique DUAS condições, não uma**

A D1 tem cinco condições e cada uma exclui um caso real. Duas merecem prova:

1. Remova `Handoff.notificado_em.is_(None)` do `where`. Rode `test_handoff_ja_notificado_nao_e_recuperado`. Tem de reprovar.
2. Inverta a ramificação da D3 (`if linha.resumo is not None:`). Rode os dois primeiros testes. Os dois têm de reprovar.

Restaure depois de cada uma e registre as saídas no relatório. Um teste que passa com a guarda invertida não prova nada.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/handoff/recuperacao.py src/mobia/domain/notificacao/envio.py src/mobia/workers/jobs/notificar.py tests/integration/test_recuperacao_sem_prazo.py
git commit -m "feat(TEC-279): o handoff perdido pela fila volta a ser visto"
```

---

### Task 2: A recuperação entra na varredura

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_sla.py`
- Modify: `src/mobia/workers/main.py` — o `startup`, ao lado de `ctx["agendador"]` (linha ~85)
- Test: `tests/integration/test_queue.py` (modificar, se houver teste de registro do job)

**Interfaces:**
- Consumes: `recuperar_sem_prazo` e `ReenfileiradorArq` (Task 1)
- Produces: `ctx["reenfileirador"]`

**Contexto que você precisa saber:**

`sweep_sla` hoje é três linhas: chama `escalar_vencidos` e devolve o retorno. Agora faz duas coisas.

**O retorno passa a ser a soma.** O número do job é "quantos handoffs esta passagem tocou", e a soma é a resposta honesta; os dois números vão para o log separados, então nada some. **Já verifiquei: nenhum teste assere esse retorno** — a única referência em `tests/` é `test_queue.py:73`, que prova o nome com que o job é registrado. Mudar o retorno é seguro.

**A ordem entre as duas não importa funcionalmente** — os conjuntos são disjuntos por construção (`sla_limite_em IS NULL` contra `IS NOT NULL`). Escreva a recuperação **depois** da escalada e diga no comentário que a ordem é indiferente e por quê; sem isso, o próximo leitor vai supor que há uma dependência e não mexer com medo.

**`ctx["reenfileirador"]` vem do `startup`, nunca com default.** Ver a guarda de `WHATSAPP_ACCESS_TOKEN` em `workers/main.py`: um `ctx.get("reenfileirador") or <qualquer dublê>` faria a recuperação **descartar em silêncio** se alguém esquecesse de popular a chave, e o sintoma seria nenhum handoff recuperado, para sempre, sem log e sem erro. Use `ctx["reenfileirador"]` direto, para o `KeyError` subir alto na primeira passagem.

- [ ] **Step 1: Escreva o teste que falha**

Em `tests/integration/test_queue.py` (ou onde o registro dos jobs é testado — procure por `SWEEP_SLA_JOB`), acrescente a prova de que `sweep_sla` chama as duas coisas. Se a montagem de lá não servir, escreva em `tests/integration/test_recuperacao_sem_prazo.py` um teste que monta um `ctx` falso e chama `sweep_sla` diretamente, assertando que um handoff perdido **e** um handoff vencido são ambos tratados numa passagem.

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_recuperacao_sem_prazo.py tests/integration/test_queue.py -v`
Expected: o teste novo FALHA.

- [ ] **Step 3: Mude o `sweep_sla`**

```python
async def sweep_sla(ctx: dict[str, Any], limite: int = 100) -> int:
    """Escala os vencidos e recupera os perdidos. Devolve quantos ao todo.

    **Duas varreduras, nao uma.** `escalar_vencidos` (TEC-178) pega o handoff
    que TEM prazo e o estourou; `recuperar_sem_prazo` (TEC-279) pega o que
    nunca ganhou prazo porque o enfileiramento da notificacao falhou. Os
    conjuntos sao disjuntos por construcao -- um exige `sla_limite_em IS NOT
    NULL` e o outro `IS NULL` --, entao **a ordem entre as duas e
    indiferente** e nenhuma depende do que a outra fez nesta passagem.

    O retorno e a soma porque o numero do job e "quantos handoffs esta
    passagem tocou". Os dois numeros vao para o log separados, em
    `escalar_vencidos` e `recuperar_sem_prazo`, entao nenhum some na soma.

    Tudo vem do `ctx`, no mesmo molde de `notificar_corretor`: e o `startup`
    do worker que decide a implementacao, e o teste troca a decisao sem tocar
    neste job.
    """
    escalados = await escalar_vencidos(
        ctx["session_factory"], canais=ctx["canais_de_notificacao"], limite=limite
    )
    recuperados = await recuperar_sem_prazo(
        ctx["session_factory"], reenfileirador=ctx["reenfileirador"], limite=limite
    )
    return escalados + recuperados
```

- [ ] **Step 4: Popule o `ctx` no `startup`**

Em `src/mobia/workers/main.py`, ao lado de `ctx["agendador"] = AgendadorArq(ctx["redis"])`:

```python
    ctx["reenfileirador"] = ReenfileiradorArq(ctx["redis"])
```

Mesmo `ctx["redis"]` que o `agendador` usa — o docstring do `startup` explica que o ARQ já o gravou antes deste hook e que criar um segundo pool seria redundante.

- [ ] **Step 5: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recuperacao_sem_prazo.py tests/integration/test_queue.py tests/integration/test_escalada_de_sla.py -v
```
Expected: todos PASSAM, incluindo os que já existiam.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/workers/jobs/sweep_sla.py src/mobia/workers/main.py tests/
git commit -m "feat(TEC-279): a varredura de SLA passa a recuperar tambem os perdidos"
```

---

### Task 3: Fechamento

**Files:** nenhum, exceto o que a busca de comentários mandar corrigir.

**Esta card não emenda o SRS e não cria migration.** Se você achar que precisa de um dos dois, **pare e reporte** — o desenho não prevê.

- [ ] **Step 1: A suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: tudo verde. **Guarde o hash junto com o resultado.**

Se falhar, rode **de novo sobre a mesma árvore** antes de culpar a branch — é a única coisa que separa flake de regressão. E se aparecerem dezenas de `relation ... does not exist`, leia a seção do CLAUDE.md sobre os bancos dos workers com o carimbo adiantado: isso repete idêntico na segunda execução e não é sua mudança.

- [ ] **Step 2: Comentários tocados, e a busca à mão**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

**Esta branch dá leitor a duas colunas que não tinham nenhum, e a ferramenta não vê fora do diff.** Procure à mão:

- **`notificado_em` e `aviso_manual_pendente`**: esta card lhes dá o primeiro leitor da vida delas, e há pelo menos um comentário afirmando o contrário. **Já localizei o principal: `src/mobia/domain/notificacao/envio.py:214-215`** diz que *"o unico leitor previsto destas duas colunas continua sendo o painel da E8, que nao existe"*. Deixou de ser verdade — `recuperar_sem_prazo` as lê. Corrija, e **procure irmãs** (`grep -rn "leitor" src/`).

  `envio.py:162` diz que sem a guarda o handoff ficaria *"invisivel para a fila futura da E8"*. Julgue: continua verdade, ou a recuperação agora o veria? A resposta muda a frase, e é decisão sua — registre-a no relatório.

  **Migrations são histórico datado e não se corrigem** — `alembic/versions/0026` fala de E8 e TEC-178, e aquilo era verdade quando foi escrito.
- `handoff/escalada.py`: o docstring explica por que `sla_limite_em IS NOT NULL` exclui handoffs sem prazo. **Continua verdade**, mas agora existe uma irmã que os pega — vale uma frase apontando, e é julgamento seu se ela ajuda ou polui.
- qualquer texto afirmando que nada recupera um handoff perdido, ou que a varredura de SLA é a única rede.

- [ ] **Step 3: Os três gates e `alembic heads`**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m alembic heads
```
Expected: três verdes, e `alembic heads` = **`0030`, inalterado** — esta card não cria migration. Se mudou, algo saiu do escopo.

- [ ] **Step 4: Commit, se a busca de comentários achou algo**

```bash
git add -A
git commit -m "docs(TEC-279): os comentarios que diziam que ninguem le notificado_em"
```

Se não achou nada, diga isso no relatório e não force um commit vazio.

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 1 (o `SELECT`). D2 → Task 1 (os quatro testes que passam por construção). D3 → Task 1 (a ramificação e a falsificação dela). D4 → Task 1 (nenhum `update`, nenhum contador — dito explicitamente no Step 3). D5 → Task 1 (`INTERVALO_DE_RECUPERACAO`). D6 → Tasks 1 e 2. L1–L4 → declaradas; sem task, por construção.

**Consistência de tipos:** `ReenfileiradorPort` com `agendar_resumo`/`agendar_notificacao` é definida na Task 1 e consumida na 2 pelo `ReenfileiradorArq`; o dublê da Task 1 implementa os mesmos dois nomes. `recuperar_sem_prazo(session_factory, *, reenfileirador, limite=100) -> int` aparece igual nas duas tasks.

**Ordem:** a Task 2 depende da 1. A Task 1 sozinha deixa a árvore com código correto e não alcançado por nada — é um estado válido para um revisor avaliar, e é por isso que são duas tasks e não uma.

**Dois pontos que o executor decide e registra:** onde pôr o teste de integração do `sweep_sla` (em `test_queue.py`, se a montagem servir, ou no arquivo novo); e se a frase apontando para a irmã ajuda ou polui o docstring de `escalada.py`.
