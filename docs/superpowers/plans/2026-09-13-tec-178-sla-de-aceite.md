# TEC-178 — SLA de aceite e escalada: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um handoff que ninguém aceita deixa de ficar parado: ele ganha prazo, e quando o prazo estoura ele escala ao gerente e sai da fila de pendentes.

**Architecture:** Uma função pura calcula o prazo a partir da temperatura do lead e da jornada do corretor destinatário. O job de notificação — que é onde o destinatário é conhecido — grava esse prazo. Uma varredura de cinco em cinco minutos marca como `ESCALADO` o que passou do prazo e notifica o gerente. Uma rota nova deixa o handoff sair de `PENDENTE` por aceite.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, ARQ, FastAPI, pytest.

**Spec:** [`docs/superpowers/specs/2026-09-13-tec-178-sla-de-aceite-design.md`](../specs/2026-09-13-tec-178-sla-de-aceite-design.md)

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  **`alembic/` está no escopo do formatador.**
- **`ruff`:** `select = ["E","F","I","UP","B"]`, `line-length = 100`.
- **A cadeia de migration na `main` termina em `0027`. A desta card é a `0028`.** Confira com `ls alembic/versions/`.
- **Suíte inteira:** `-n 8 --dist loadfile`, uma vez. **Se dezenas de testes falharem com `relation ... does not exist`, não é a sua migration** — são os bancos dos workers com o carimbo do alembic adiantado, e o sintoma **se repete idêntico na segunda execução**. `docker compose exec -T postgres psql -U mobia -d mobia_gwN` para conferir; **não há `psql` no PATH**. O CLAUDE.md tem o parágrafo.
- **`ConnectionResetError [WinError 64]`** é ruído (~5% dos connects): espere e retente.
- **Prazos:** `QUENTE` = **15 minutos**; `MORNO`, `FRIO` e temperatura nula = **4 horas**.
- **Mensagens de commit:** `tipo(TEC-178): ...`, assunto sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/handoff/sla.py` | **Criar.** Puro: os prazos e o cálculo do limite dentro da jornada. |
| `alembic/versions/0028_sla_de_aceite.py` | **Criar.** `handoffs.sla_limite_em`, `handoffs.aceito_em`, `corretores.gerente`. |
| `src/mobia/domain/handoff/models.py` | **Modificar.** As duas colunas de handoff. |
| `src/mobia/domain/corretores/models.py` | **Modificar.** A flag `gerente`. |
| `src/mobia/domain/notificacao/destinatario.py` | **Modificar.** A cascata do gerente, espelhando a do plantão. |
| `src/mobia/domain/notificacao/envio.py` | **Modificar.** Grava o prazo; sem destinatário, escala na hora. |
| `src/mobia/domain/handoff/escalada.py` | **Criar.** A varredura que escala e notifica o gerente. |
| `src/mobia/workers/jobs/sweep_sla.py` | **Criar.** O job ARQ. |
| `src/mobia/workers/main.py` | **Modificar.** Registrar o cron. |
| `src/mobia/api/routes/handoffs.py` | **Modificar.** A rota de aceite. |

---

### Task 1: O prazo, puro e sem I/O

**Files:**
- Create: `src/mobia/domain/handoff/sla.py`
- Test: `tests/unit/test_handoff_sla.py`

**Interfaces:**
- Consumes: nada.
- Produces: `PRAZO_QUENTE_MINUTOS = 15`, `PRAZO_PADRAO_MINUTOS = 240`, `prazo_em_minutos(temperatura: str | None) -> int`, `limite_de_aceite(*, inicio: datetime, minutos: int, jornada_inicio: int, jornada_fim: int, fuso: ZoneInfo) -> datetime`.

**O ponto de desenho desta task:** `limite_de_aceite` responde *"dado um instante e N minutos de jornada, quando o prazo acaba?"*. Isso **não** é a pergunta que `outbound/horario.py` responde (*"o relógio permite enviar agora?"*), então não reuse aquela função nem a estenda — leia a docstring dela, que explica por que ela mora onde mora, e escreva a sua no mesmo espírito.

Três casos que o cálculo tem de acertar, e os testes os cobrem:
- o instante já está **dentro** da jornada e os minutos cabem antes do fechamento → soma direta;
- está dentro mas os minutos **atravessam** o fechamento → o resto continua na abertura seguinte;
- está **fora** da jornada → a contagem só começa na próxima abertura.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_handoff_sla.py
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from mobia.domain.handoff.sla import (
    PRAZO_PADRAO_MINUTOS,
    PRAZO_QUENTE_MINUTOS,
    limite_de_aceite,
    prazo_em_minutos,
)

SP = ZoneInfo("America/Sao_Paulo")


def _em_sp(ano: int, mes: int, dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=SP)


def test_quente_tem_quinze_minutos() -> None:
    assert prazo_em_minutos("QUENTE") == PRAZO_QUENTE_MINUTOS == 15


def test_morno_e_frio_tem_quatro_horas() -> None:
    assert prazo_em_minutos("MORNO") == PRAZO_PADRAO_MINUTOS == 240
    assert prazo_em_minutos("FRIO") == PRAZO_PADRAO_MINUTOS


def test_temperatura_nula_conta_como_nao_quente() -> None:
    """D2: dar 15 minutos a um lead cuja temperatura ninguem calculou
    inventaria urgencia. NULL e "linha anterior a TEC-151", nao FRIO."""
    assert prazo_em_minutos(None) == PRAZO_PADRAO_MINUTOS


def test_dentro_da_jornada_soma_direto() -> None:
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 10, 0), minutos=15,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 15, 10, 15)


def test_fora_da_jornada_comeca_na_proxima_abertura() -> None:
    """Terceiro cenario do Gherkin: as 22h de terca conta a partir das 9h de quarta."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 22, 0), minutos=15,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 16, 9, 15)


def test_antes_da_abertura_no_mesmo_dia_espera_a_abertura() -> None:
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 6, 0), minutos=30,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 15, 9, 30)


def test_o_que_nao_cabe_antes_do_fechamento_continua_no_dia_seguinte() -> None:
    """Comecar as 17h50 com 30 minutos: 10 antes do fechamento, 20 depois."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 17, 50), minutos=30,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 16, 9, 20)


def test_um_prazo_maior_que_o_dia_atravessa_varios_dias() -> None:
    """Quatro horas comecando as 17h30 de uma jornada que fecha as 18h."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 17, 30), minutos=PRAZO_PADRAO_MINUTOS,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    # 30 minutos hoje, 210 restantes a partir das 9h de amanha.
    assert limite == _em_sp(2026, 9, 16, 12, 30)


def test_instante_ingenuo_levanta() -> None:
    """Mesma razao de `horario_permite_envio`: `astimezone` num naive assume o
    fuso do SISTEMA, e esta maquina difere do runner do CI."""
    import pytest

    with pytest.raises(ValueError, match="tzinfo"):
        limite_de_aceite(
            inicio=datetime(2026, 9, 15, 10, 0), minutos=15,
            jornada_inicio=9, jornada_fim=18, fuso=SP,
        )


def test_o_limite_devolvido_e_aware_e_em_utc() -> None:
    limite = limite_de_aceite(
        inicio=datetime(2026, 9, 15, 13, 0, tzinfo=UTC), minutos=15,
        jornada_inicio=9, jornada_fim=18, fuso=SP,
    )
    assert limite.tzinfo is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_sla.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.sla'`

- [ ] **Step 3: Write the implementation**

Módulo puro, com o cabeçalho explicando **por que não reusa `horario_permite_envio`** (pergunta diferente) e por que `inicio` ingênuo levanta (o fuso desta máquina difere do runner do CI — o mesmo argumento que aquela função já escreveu).

Cuidado com dois pontos:
- **A jornada pode não conter o instante nem hoje nem nunca** se alguém gravar `inicio == fim`. O CHECK `ck_corretores_jornada` já proíbe isso no banco (`horario_inicio < horario_fim`), mas a função é pura e pode ser chamada de qualquer lugar — decida se valida e **escreva a razão**.
- **A soma atravessa dias.** Não assuma que o prazo cabe num dia só: quatro horas começando perto do fechamento não cabem, e o teste prova.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_sla.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/sla.py tests/unit/test_handoff_sla.py
git commit -m "feat(TEC-178): o prazo de aceite conta dentro da jornada do corretor"
```

---

### Task 2: As colunas e a flag do gerente

**Files:**
- Create: `alembic/versions/0028_sla_de_aceite.py`
- Modify: `src/mobia/domain/handoff/models.py`, `src/mobia/domain/corretores/models.py`
- Test: `tests/integration/test_handoff_schema.py`, `tests/integration/test_corretores_schema.py`

**Interfaces:**
- Produces: `Handoff.sla_limite_em: datetime | None`, `Handoff.aceito_em: datetime | None`, `Corretor.gerente: bool`.

**Leia `alembic/versions/0026_notificacao_do_handoff.py` e `0025_corretores.py` antes** — são as duas migrations irmãs, uma sobre cada tabela que esta toca.

Três pontos que os comentários têm de explicar:

- **`sla_limite_em` é NULÁVEL, contra o "Sim" do modelo da seção 5 do SRS.** A emenda E-01 da RN-16.3 declara o porquê: o prazo usa a jornada do corretor destinatário, que só é conhecida no job de notificação. Nulo significa "ainda não notificado" ou "não havia a quem cobrar" — **nunca "prazo zero"**.
- **`gerente` nasce falso**, pela mesma razão que `plantao`: verdadeiro faria todo corretor cadastrado virar gerente.
- **`gerente` e `plantao` são independentes**, não excludentes — um corretor pode ser os dois numa imobiliária pequena. Se você achar que devem ser exclusivos, **não decida sozinho**: registre no relatório.

- [ ] **Step 1: Write the failing tests**

Em `test_handoff_schema.py`, um teste provando que as duas colunas nascem nulas. Em `test_corretores_schema.py`, um provando que `gerente` nasce falso e outro provando que um corretor pode ser gerente **e** plantão ao mesmo tempo.

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Write the migration and the columns.**
- [ ] **Step 4: Apply and run** `test_handoff_schema.py`, `test_corretores_schema.py`, `test_corretores_repositorio.py`.
- [ ] **Step 5: Run the static gates.** `alembic/` está no escopo do formatador.
- [ ] **Step 6: Commit**

```bash
git commit -m "feat(TEC-178): o handoff ganha prazo e aceite, e o corretor pode ser gerente"
```

---

### Task 3: O gerente como destinatário da escalada

**Files:**
- Modify: `src/mobia/domain/notificacao/destinatario.py`
- Test: `tests/integration/test_notificacao_destinatario.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `gerente_ativo(session) -> Corretor | None`.

**Espelhe `destinatario_do_handoff` exatamente:** `gerente = true`, `ativo = true`, `ORDER BY criado_em` ascendente, `limit(1)`, `None` sem levantar. **Com mais de um gerente ativo, o mais antigo** — pela mesma razão escrita lá: é o que não muda quando alguém cadastra outro.

A fixture `semear_corretor` (em `tests/conftest.py`) precisa aceitar `gerente`.

Testes: sem gerente devolve `None`; com um, devolve; com dois, o mais antigo (**com carimbos que diferem de fato** — um teste com carimbos iguais não prova ordenação); gerente inativo não conta.

- [ ] **Step 1–6:** mesmo ciclo — teste que falha, implementação, gates, commit.

```bash
git commit -m "feat(TEC-178): o gerente se resolve como o plantao, e o inativo nao conta"
```

---

### Task 4: O prazo gravado, e a escalada imediata sem destinatário

**Files:**
- Modify: `src/mobia/domain/notificacao/envio.py`
- Test: `tests/integration/test_notificacao_envio.py`

**Interfaces:**
- Consumes: `prazo_em_minutos`, `limite_de_aceite` (Task 1); as colunas (Task 2).

Duas mudanças em `notificar`, as duas na **primeira sessão**, onde o handoff e o corretor já estão carregados:

**(a) O ramo do destinatário resolvido grava `sla_limite_em`.** Precisa da temperatura, que vem de `lead_qualification` — uma consulta a mais nessa mesma sessão, pelo par `(channel, conversation_key)` do handoff. **Não derive a temperatura do gatilho** (D2): `LEAD_QUENTE` significa "acabou de atravessar a borda", e um `PEDIDO_DE_HUMANO` sobre lead já quente merece os mesmos 15 minutos.

**(b) O ramo `corretor is None` passa a escalar na hora.** Além do `aviso_manual_pendente = True` que ele já faz, marca `status = ESCALADO` e mantém `sla_limite_em` nulo. O log de `notificacao.sem_destinatario` continua, e o motivo passa a dizer que escalou.

**Cuidado:** o `handoff` daquela sessão é objeto ORM. As mudanças da (b) precisam entrar no mesmo `commit()` que já existe ali.

Testes: handoff de lead `QUENTE` ganha prazo de 15 minutos contado da jornada do destinatário; de lead `MORNO`, 4 horas; sem destinatário nasce `ESCALADO` com `sla_limite_em` nulo; e **o caminho feliz continua passando** — os testes existentes de `test_notificacao_envio.py` não podem quebrar.

- [ ] **Step 1–6:** mesmo ciclo.

```bash
git commit -m "feat(TEC-178): a notificacao grava o prazo, e o handoff sem dono escala na hora"
```

---

### Task 5: A varredura que escala

**Files:**
- Create: `src/mobia/domain/handoff/escalada.py`, `src/mobia/workers/jobs/sweep_sla.py`
- Modify: `src/mobia/workers/main.py`
- Test: `tests/integration/test_escalada_de_sla.py`, `tests/integration/test_queue.py`

**Interfaces:**
- Consumes: `gerente_ativo` (Task 3); os canais de notificação (`ctx["canais_de_notificacao"]`).
- Produces: `escalar_vencidos(session_factory, *, canais, limite: int = 100) -> int`; `SWEEP_SLA_JOB`.

**O molde é `sweep_followups`** — leia-o antes, incluindo o comentário que justifica o intervalo do cron.

**D6 é o coração desta task:** a varredura seleciona `status = 'PENDENTE' AND sla_limite_em IS NOT NULL AND sla_limite_em < now()`. Escalar muda o status para `ESCALADO`, e a linha **sai do conjunto sozinha** — nenhuma coluna de "já escalei", nenhum `if`. É o mesmo raciocínio do `UNIQUE` parcial da TEC-174, e é o que faz "escalonamento não se repete" ser garantia de schema.

**O cron roda de cinco em cinco minutos**, como o `sweep_followups`, e pela mesma razão: o menor prazo é de quinze minutos, então precisão de segundos custa varredura sem comprar nada. **Escreva o argumento no comentário**, não o número sozinho.

**A notificação ao gerente reusa os canais da TEC-177 e não entrega** (L2). Isso não é pendência: escreva no comentário que o estado no banco é o que existe de fato hoje.

Testes: um handoff vencido escala; um dentro do prazo não; um já `ESCALADO` não escala de novo (a prova da D6); um com `sla_limite_em` nulo não é tocado pela varredura; sem gerente cadastrado, o handoff ainda escala e o log diz que não houve a quem avisar. Mais o teste que amarra `SWEEP_SLA_JOB` ao nome registrado — molde em `test_queue.py`.

- [ ] **Step 1–6:** mesmo ciclo.

```bash
git commit -m "feat(TEC-178): a varredura escala o que passou do prazo, e so uma vez"
```

---

### Task 6: A rota de aceite

**Files:**
- Modify: `src/mobia/api/routes/handoffs.py`
- Test: `tests/integration/test_rota_de_resumo.py` (ou arquivo novo)

**Interfaces:**
- Produces: `POST /api/v1/handoffs/{handoff_id}/aceitar`.

A rota está na seção 6.5 do SRS desde 22/08/2026 e nada a implementa. Guardada por `exigir_admin`, com a mesma exposição que a emenda E-01 da RN-19.5 declarou.

**Aceitar é idempotente até o primeiro aceite e recusado depois dele (D8).** Um segundo aceite sobre handoff já aceito devolve **409**, não sobrescreve `aceito_em` — o carimbo alimenta a taxa de aceite no prazo da RN-17.1, e um carimbo que anda para frente faria um aceite atrasado parecer pontual.

**Decida e registre no relatório:** o que acontece ao aceitar um handoff já `ESCALADO`. Aceitar depois da escalada é o caso real de o gerente cobrar e alguém pegar — recusar seria punir o que a card quer que aconteça. **Minha inclinação é permitir**, registrando `aceito_em`; se você concluir o contrário, escreva a razão.

Testes: sem token, 403; handoff inexistente, 404; aceite registra `aceito_em` e muda o status; segundo aceite, 409; aceite de um `ESCALADO` segundo a sua decisão.

- [ ] **Step 1–6:** mesmo ciclo.

```bash
git commit -m "feat(TEC-178): o handoff enfim sai de PENDENTE por aceite"
```

---

### Task 7: Fechamento

- [ ] **Step 1: Suíte inteira, uma vez.**
- [ ] **Step 2: Comentários tocados.** `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

**Esta branch muda um contrato e a ferramenta não vê fora do diff** — foi assim que a TEC-176 deixou dois comentários falsos. Procure à mão quem descreve o que mudou: `status` que "nasce e permanece PENDENTE" (`handoff/models.py`), `Status.ACEITO`/`ESCALADO` "sem escritor" (`vocabulario.py`), a L4 da TEC-174, e qualquer menção a `notificado_em`/`aviso_manual_pendente` sem leitor.

- [ ] **Step 3: Orçamento do prompt.** Inalterado — esta card não toca `SISTEMA_DO_AGENTE`.
- [ ] **Step 4: Os três gates, `alembic heads` com uma cabeça, e push.**

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 4. D2 → Tasks 1 e 4. D3 → Tasks 1 e 4. D4 → Task 4. D5 → Task 5. D6 → Task 5. D7 → Tasks 2 e 3. D8 → Task 6. L1–L4 → declaradas; sem task, por construção.

**Consistência de tipos:** `limite_de_aceite` e `prazo_em_minutos` na Task 1, usados na 4; `gerente_ativo` na 3, usado na 5; as colunas na 2, usadas em 4, 5 e 6.

**Três pontos que o executor decide e registra:** se `limite_de_aceite` valida jornada degenerada; se `gerente` e `plantao` são exclusivos; e o que acontece ao aceitar um handoff já escalado.
