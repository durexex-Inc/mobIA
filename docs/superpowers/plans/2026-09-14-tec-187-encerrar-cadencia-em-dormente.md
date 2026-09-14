# TEC-187 — Encerrar a cadência e marcar o lead como DORMENTE

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar nome, sinal e consulta ao lead que esgotou a cadência de follow-up, sem persistir estado novo e sem alterar comportamento de envio.

**Architecture:** `DORMENTE` é estado derivado, não coluna. Uma função pura (`esta_dormente`) responde a pergunta a partir da `CADENCIA` que já existe; uma consulta (`listar_dormentes`) inverte o corte de candidatura reusando as CTEs da âncora; e o sweep emite `followup.dormente` no instante em que grava a tentativa que fecha o teto. Nenhuma migration — `alembic` continua em `0033`.

**Tech Stack:** Python 3.13, SQLAlchemy async (`text()` cru para as consultas da cadência), Postgres, ARQ, structlog, pytest / pytest-asyncio / pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-187-encerrar-cadencia-em-dormente-design.md`

## Global Constraints

- **Os três gates, nesta ordem, antes de qualquer commit.** O formatador é gate separado do linter; passar num não diz nada sobre o outro.
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m mypy`
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Não é checado por linter nenhum. A prosa em `docs/` leva acento normalmente.
- **Comentário explica o porquê, não o quê.** Comentário desatualizado é defeito. Antes do PR, rodar `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` e reconferir tudo que sair como `ALTERADO` e como `VIZINHO`.
- **Mensagem de commit:** `tipo(TEC-187): o que passou a ser verdade`, assunto em português sem acento, e ao final a linha `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Unitários rodam sem Docker e sem `-n`:** `./.venv/Scripts/python.exe -m pytest tests/unit`. Integração exige `docker compose` de pé.
- **A suíte inteira roda UMA vez, com `-n 8 --dist loadfile` e `--tb=short`.** Uma execução verde basta. Segunda execução só como diagnóstico, quando a primeira falha.
- **Nada nesta card toca** `tentativa_devida`, `CADENCIA`, as guardas de horário, opt-out, silenciamento ou anti-spam, nem cria migration.

---

### Task 1: `esta_dormente`, a função pura

**Files:**
- Modify: `src/mobia/domain/followup/cadencia.py` (acrescenta ao fim, depois de `tentativa_devida`)
- Test: `tests/unit/test_cadencia.py` (acrescenta ao fim)

**Interfaces:**
- Consumes: `CADENCIA: dict[Temperatura, tuple[timedelta, ...]]` e `Temperatura`, ambos já no módulo.
- Produces: `esta_dormente(*, temperatura: Temperatura, ja_disparada: int) -> bool`. As Tasks 2 e 3 a importam de `mobia.domain.followup.cadencia`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `tests/unit/test_cadencia.py`. O import da primeira linha do arquivo passa a incluir `esta_dormente`:

```python
from mobia.domain.followup.cadencia import (
    CADENCIA,
    INTERVALO_MINIMO,
    esta_dormente,
    tentativa_devida,
)
```

E os testes:

```python
@pytest.mark.parametrize("temperatura", list(Temperatura))
def test_quem_nunca_recebeu_nada_nao_esta_dormente(temperatura: Temperatura) -> None:
    """Zero e o valor de "nunca disparou sob esta ancora"."""
    assert esta_dormente(temperatura=temperatura, ja_disparada=0) is False


@pytest.mark.parametrize("temperatura", list(Temperatura))
def test_uma_tentativa_antes_do_teto_ainda_nao_esta_dormente(temperatura: Temperatura) -> None:
    teto = len(CADENCIA[temperatura])
    assert esta_dormente(temperatura=temperatura, ja_disparada=teto - 1) is False


@pytest.mark.parametrize("temperatura", list(Temperatura))
def test_alcancar_o_teto_da_temperatura_adormece(temperatura: Temperatura) -> None:
    """O teto sai de CADENCIA, nunca escrito a mao aqui: um numero literal
    neste teste seria uma segunda fonte, e passaria a mentir no dia em que
    alguem alongasse a tabela da RN-13.1."""
    teto = len(CADENCIA[temperatura])
    assert esta_dormente(temperatura=temperatura, ja_disparada=teto) is True


@pytest.mark.parametrize("temperatura", list(Temperatura))
def test_passar_do_teto_continua_dormente(temperatura: Temperatura) -> None:
    """Alcancavel de verdade: um lead esgota QUENTE em 4 e depois esfria para
    MORNO, cujo teto e 3 -- `ja_disparada` fica acima do teto vigente."""
    teto = len(CADENCIA[temperatura])
    assert esta_dormente(temperatura=temperatura, ja_disparada=teto + 1) is True


@pytest.mark.parametrize("temperatura", list(Temperatura))
@pytest.mark.parametrize("ja_disparada", [0, 1, 2, 3, 4, 5])
def test_dormente_e_a_negacao_exata_do_corte_de_candidatura(
    temperatura: Temperatura, ja_disparada: int
) -> None:
    """A guarda central desta card.

    `esta_dormente` e o corte SQL `ja_disparada < CASE temperatura ... END` de
    `repositorio.py` sao a mesma afirmacao escrita duas vezes, uma em Python e
    outra em SQL. Elas nao divergem porque as duas derivam de `CADENCIA` -- e
    este teste e o que falha se alguem quebrar essa derivacao num dos lados.
    """
    seria_candidato = ja_disparada < len(CADENCIA[temperatura])
    assert esta_dormente(temperatura=temperatura, ja_disparada=ja_disparada) is not seria_candidato


def test_os_argumentos_de_esta_dormente_sao_keyword_only() -> None:
    """Mesma razao de `tentativa_devida`: `temperatura` e `ja_disparada` nao
    sao confundiveis por tipo, mas a chamada posicional convida a inverter com
    os outros argumentos da familia, e o mypy nao veria."""
    with pytest.raises(TypeError):
        esta_dormente(Temperatura.MORNO, 3)  # type: ignore[misc,call-arg]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_cadencia.py -q --tb=short`
Expected: FAIL na coleta — `ImportError: cannot import name 'esta_dormente' from 'mobia.domain.followup.cadencia'`.

- [ ] **Step 3: Escrever a implementação mínima**

Acrescentar ao fim de `src/mobia/domain/followup/cadencia.py`:

```python
def esta_dormente(*, temperatura: Temperatura, ja_disparada: int) -> bool:
    """RN-13.5: o lead esgotou a cadencia e saiu da automacao.

    **E derivado, e nao um estado gravado.** Nao ha coluna `status` em lugar
    nenhum, e esta funcao nao le nem escreve banco: a pergunta e respondida
    pela tabela da RN-13.1 e pelo que `followups` ja guarda. A data e a
    contagem que a card pede da transicao sao o `created_at` e o
    `tentativa_numero` da linha da ultima tentativa. Ver a D1 do desenho.

    **Esta expressao e a negacao exata do corte de candidatura** em
    `repositorio.py` (`ja_disparada < CASE temperatura ... END`). Nao sao duas
    fontes que podem divergir: aquele `CASE` e GERADO a partir de `CADENCIA`
    por `_TETOS_POR_TEMPERATURA`, e esta funcao le o mesmo dict. Quem alongar a
    tabela move os dois. `test_dormente_e_a_negacao_exata_do_corte_de_candidatura`
    e a guarda de que continuam iguais.

    **`>=` e nao `==`**: `ja_disparada` pode passar do teto vigente sem erro
    nenhum -- um lead esgota QUENTE em 4 e depois esfria para MORNO, cujo teto
    e 3. Com `==` ele deixaria de ser dormente ao esfriar, que e o contrario do
    que a temperatura mais fria significa.

    **`temperatura` e `Temperatura`, e nao `str | None`.** Lead com
    `temperatura IS NULL` (escreveu antes da TEC-151 e nunca mais falou) nao e
    candidato nem dormente: as duas consultas o excluem pelo `IN`. A tipagem
    recusa a pergunta em vez de inventar uma resposta -- lacuna L3 do desenho.
    """
    return ja_disparada >= len(CADENCIA[temperatura])
```

- [ ] **Step 4: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_cadencia.py -q --tb=short`
Expected: PASS, todos.

- [ ] **Step 5: Rodar os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```
Expected: `All checks passed!`, `N files already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commitar**

```bash
git add src/mobia/domain/followup/cadencia.py tests/unit/test_cadencia.py
git commit -F- <<'MSG'
feat(TEC-187): esgotar a cadencia tem nome, e a negacao do corte de candidatura

esta_dormente le o mesmo CADENCIA de que o CASE do SQL e gerado, entao as
duas afirmacoes nao podem divergir sem que um teste caia. Nada e gravado:
a RN-13.5 descreve um estado que ja existia sem rotulo desde a TEC-183.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: `listar_dormentes`, a consulta que segmenta a base

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py:152-213` (extrai `_CTES_DA_ANCORA`, acrescenta `_SELECIONAR_DORMENTES`, `LeadDormente` e `listar_dormentes`)
- Test: `tests/integration/test_listar_dormentes.py` (criar)

**Interfaces:**
- Consumes: `esta_dormente` da Task 1 (só na docstring, como referência cruzada — a consulta usa o `CASE` do SQL); `CADENCIA`, `_CASE_TETO_POR_TEMPERATURA`, `_TETOS_POR_TEMPERATURA`, `_VALORES_TEMPERATURA_VALIDOS`, já no módulo; `esta_em_optout(session, *, channel, conversation_key) -> bool` de `mobia.domain.optout.repositorio`.
- Produces: `LeadDormente` (frozen dataclass: `channel: str`, `conversation_key: str`, `temperatura: Temperatura`, `ancora_em: datetime`, `tentativas: int`, `adormeceu_em: datetime`) e `listar_dormentes(session: AsyncSession, *, agora: datetime, limite: int = 500) -> list[LeadDormente]`. A TEC-189 consome os dois; nenhuma task posterior deste plano depende deles.

- [ ] **Step 1: Extrair as CTEs partilhadas, sem mudar comportamento**

Em `src/mobia/domain/followup/repositorio.py`, recortar o bloco `WITH falas_do_lead AS (...), ultima_fala AS (...)` de dentro de `_SELECIONAR_CANDIDATOS` para uma constante de módulo imediatamente acima dele. **Copiar o comentário de `id DESC` inteiro, sem reescrever** — ele explica um defeito real e é a parte que as duas consultas precisam partilhar:

```python
# As duas consultas da cadencia -- quem esta devido e quem adormeceu --
# precisam concordar sobre o que e "a ultima fala do lead", e e por isso que
# estas duas CTEs sao uma constante e nao duas copias. A terceira CTE, a da
# agregacao, NAO e partilhada: `listar_dormentes` precisa de MAX(created_at),
# que a varredura nao calcula, e nao precisa de `ja_enviadas` nem de
# `mensagem_id`. Junta-las acrescentaria uma subconsulta correlacionada por
# linha a varredura que roda de cinco em cinco minutos, para alimentar uma
# coluna que ela descarta.
_CTES_DA_ANCORA = """
    falas_do_lead AS (
        -- `id DESC` desempata, e nao e arbitrario: `IngestionService._persist`
        -- grava o lote inteiro de um envelope num unico INSERT multi-VALUES,
        -- sem passar `created_at` -- a coluna cai no `server_default`
        -- `now()`, que e CONSTANTE dentro do mesmo statement. Duas mensagens
        -- do mesmo lead entregues no mesmo envelope gravam o MESMO carimbo, e
        -- sem desempate o Postgres escolheria qualquer uma das duas para
        -- `posicao = 1` -- nao de forma estavel entre execucoes (plano,
        -- indice ou paralelismo mudam a ordem fisica). Qual delas ganha nao
        -- importa para o negocio (o carimbo empatado faz `ancora_em` sair
        -- igual de qualquer jeito); o que importa e que a mesma consulta
        -- sobre o mesmo dado sempre escolha a MESMA linha, porque e essa
        -- linha que ancora a reserva de `outbound_dispatches`.
        SELECT channel, conversation_key, created_at, id,
               ROW_NUMBER() OVER (
                   PARTITION BY channel, conversation_key
                   ORDER BY created_at DESC, id DESC
               ) AS posicao
          FROM messages
         WHERE direction = 'INBOUND'
           AND bloqueada_em IS NULL
    ),
    ultima_fala AS (
        SELECT channel, conversation_key, created_at AS ancora, id AS mensagem_id
          FROM falas_do_lead
         WHERE posicao = 1
           AND created_at <= :corte
    )
"""
```

E `_SELECIONAR_CANDIDATOS` passa a abrir com a constante, mantendo todo o resto idêntico:

```python
_SELECIONAR_CANDIDATOS = text(
    f"""
    WITH {_CTES_DA_ANCORA},
    candidatos AS (
```

(o corpo de `candidatos AS (...)` em diante fica exatamente como está hoje, incluindo o `SELECT ... WHERE ja_disparada < CASE ... LIMIT :limite` e o `.bindparams(...)`.)

- [ ] **Step 2: Provar que a extração não mudou nada**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py tests/integration/test_followups_model.py -q --tb=short`
Expected: PASS, exatamente os mesmos testes que passavam antes. Esta é uma refatoração pura — se algo cair aqui, o recorte do SQL saiu errado (vírgula a mais depois do `}`, ou a constante começando com `WITH`).

- [ ] **Step 3: Escrever os testes que falham**

Criar `tests/integration/test_listar_dormentes.py`. O helper `_lead_dormente` é modelado no `_lead` de `tests/integration/test_sweep_followups.py:63-118` — mesma forma de semear `LeadQualification` e `Message` —, mas é local e não importado, por duas diferenças reais: aqui vários leads coexistem (chaves distintas), e as linhas de `followups` precisam de `created_at` explícito e crescente, porque é ele que `adormeceu_em` lê. Note que **os testes deste repo não levam `@pytest.mark.asyncio`** (o modo asyncio é automático) e que o canal é `"whatsapp"`.

```python
"""A RN-13.5 pelo lado da consulta: quem esgotou a cadencia e ainda da para
segmentar.

TEC-187. Integracao: a pergunta e sobre o que a consulta enxerga.
"""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA
from mobia.domain.followup.models import FollowUp
from mobia.domain.followup.repositorio import listar_dormentes
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
AGORA = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

TETO_MORNO = len(CADENCIA[Temperatura.MORNO])


async def _falar(session, *, conversa: str, em: datetime) -> uuid.UUID:
    """Uma fala de entrada do lead no momento pedido. E ela que ancora."""
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
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


async def _lead_dormente(
    session,
    *,
    conversa: str,
    temperatura: str | None = "MORNO",
    calado_ha: timedelta = timedelta(days=30),
    tentativas: int = TETO_MORNO,
) -> datetime:
    """Um lead calado com `tentativas` follow-ups gravados sob a ancora.

    Devolve a ancora. O `created_at` de cada linha e explicito e crescente
    porque e ele que `adormeceu_em` le -- em producao quem as grava e a
    varredura, uma por passagem, e a ordem sai da mesma monotonicidade.
    """
    ancora = AGORA - calado_ha
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=conversa,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    await _falar(session, conversa=conversa, em=ancora)
    for numero in range(1, tentativas + 1):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=conversa,
                tentativa_numero=numero,
                temperatura=temperatura or "MORNO",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
                created_at=ancora + timedelta(days=numero),
            )
        )
    await session.commit()
    return ancora


async def test_o_lead_que_esgotou_o_morno_aparece(session) -> None:
    """Cenario 1 da card: tres tentativas sem resposta, e ele esta dormente."""
    await _lead_dormente(session, conversa="5511900000001")

    dormentes = await listar_dormentes(session, agora=AGORA)

    assert [d.conversation_key for d in dormentes] == ["5511900000001"]


async def test_uma_tentativa_abaixo_do_teto_nao_aparece(session) -> None:
    """A outra metade da assertiva acima: a consulta nao pode devolver todo
    mundo que tem alguma linha de `followups`."""
    await _lead_dormente(session, conversa="5511900000002", tentativas=TETO_MORNO - 1)

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_a_data_e_a_contagem_da_transicao(session) -> None:
    """Cenario 2 da card.

    Nada disto e gravado por esta card: sai da linha de `followups` de maior
    `tentativa_numero`, que a TEC-183 ja grava.
    """
    ancora = await _lead_dormente(session, conversa="5511900000003")

    (dormente,) = await listar_dormentes(session, agora=AGORA)

    assert dormente.tentativas == TETO_MORNO
    assert dormente.adormeceu_em == ancora + timedelta(days=TETO_MORNO)
    assert dormente.ancora_em == ancora
    assert dormente.temperatura is Temperatura.MORNO


async def test_quem_respondeu_depois_de_esgotar_deixa_de_ser_dormente(session) -> None:
    """Cenario 4 da card, e sem codigo de reativacao nenhum: a fala nova move
    a ancora, e nao ha linha de `followups` sob a ancora nova."""
    await _lead_dormente(session, conversa="5511900000004")
    await _falar(session, conversa="5511900000004", em=AGORA - timedelta(hours=1))
    await session.commit()

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_o_dormente_com_optout_fica_de_fora(session) -> None:
    """A lista alimenta campanha manual, e a RN-14.3 condiciona qualquer novo
    contato de quem pediu opt-out a acao humana com justificativa."""
    await _lead_dormente(session, conversa="5511900000005")
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key="5511900000005",
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_o_lead_sem_temperatura_nao_aparece(session) -> None:
    """Lacuna L3 do desenho, testada para ser verificavel e nao so afirmada.

    Quem escreveu antes da TEC-151 e nunca mais falou nao e candidato NEM
    dormente -- e invisivel as duas consultas, e esta linha e o registro de
    que isso e escolha e nao esquecimento.
    """
    await _lead_dormente(session, conversa="5511900000006", temperatura=None, tentativas=4)

    assert await listar_dormentes(session, agora=AGORA) == []
```

> **Confira duas coisas contra o código antes de rodar**, em vez de confiar neste plano: que `OptoutEvent` aceita `evento=` posicionalmente como escrito (`tests/integration/test_sweep_followups.py` já o instancia — copie de lá) e que `FollowUp` aceita `created_at` explícito (a coluna tem `server_default`, e passar valor explícito deve vencê-lo). Se `created_at` for recusado, grave as linhas e depois faça `UPDATE` do carimbo — `adormeceu_em` precisa de valores distintos para o teste da data significar alguma coisa.

- [ ] **Step 4: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_listar_dormentes.py -q --tb=short`
Expected: FAIL na coleta — `ImportError: cannot import name 'listar_dormentes'`.

> Se em vez disso aparecer `ConnectionResetError [WinError 64]` na negociação SSL, **não é o seu código**: é o Postgres deste ambiente, que reprova ~5% dos connects em rajada. Espere e rode de novo antes de diagnosticar qualquer coisa.

- [ ] **Step 5: Escrever a consulta e a função**

Acrescentar em `src/mobia/domain/followup/repositorio.py`, depois de `candidatos_a_followup`:

```python
_SELECIONAR_DORMENTES = text(
    f"""
    WITH {_CTES_DA_ANCORA},
    esgotados AS (
        SELECT lq.channel,
               lq.conversation_key,
               lq.temperatura,
               u.ancora,
               COALESCE(
                   (SELECT MAX(f.tentativa_numero)
                      FROM followups f
                     WHERE f.channel = lq.channel
                       AND f.conversation_key = lq.conversation_key
                       AND f.ancora_em = u.ancora),
                   0
               ) AS ja_disparada,
               (SELECT MAX(f.created_at)
                  FROM followups f
                 WHERE f.channel = lq.channel
                   AND f.conversation_key = lq.conversation_key
                   AND f.ancora_em = u.ancora) AS adormeceu_em
          FROM lead_qualification lq
          JOIN ultima_fala u
            ON u.channel = lq.channel
           AND u.conversation_key = lq.conversation_key
         WHERE lq.temperatura IN :temperaturas_validas
    )
    SELECT channel, conversation_key, temperatura, ancora, ja_disparada, adormeceu_em
      FROM esgotados
     WHERE ja_disparada >= CASE temperatura {_CASE_TETO_POR_TEMPERATURA} END
     ORDER BY adormeceu_em DESC, channel, conversation_key
     LIMIT :limite
    """
).bindparams(bindparam("temperaturas_validas", expanding=True))


@dataclass(frozen=True)
class LeadDormente:
    """Um lead que esgotou a cadencia da sua temperatura (RN-13.5).

    `tentativas` e `adormeceu_em` sao a "data e a quantidade de tentativas
    realizadas" que a card exige da transicao. Nenhum dos dois e gravado por
    esta card: sao o `tentativa_numero` e o `created_at` da linha de
    `followups` de maior tentativa sob a ancora atual.

    **`adormeceu_em` e `MAX(created_at)`, e isso so coincide com a linha de
    maior `tentativa_numero` porque `tentativa_devida` nunca devolve tentativa
    menor que `ja_disparada`** -- as insercoes sob uma ancora sao monotonicas.
    Se a regua um dia passar a devolver tentativa intermediaria, a igualdade
    quebra, e o lugar de consertar e aqui.
    """

    channel: str
    conversation_key: str
    temperatura: Temperatura
    ancora_em: datetime
    tentativas: int
    adormeceu_em: datetime


async def listar_dormentes(
    session: AsyncSession, *, agora: datetime, limite: int = 500
) -> list[LeadDormente]:
    """Os leads que esgotaram a cadencia e seguem elegiveis a campanha manual.

    A inversa de `candidatos_a_followup`: la o corte e
    `ja_disparada < CASE temperatura ... END`, aqui e `>=`. O mesmo `CASE`
    gerado de `CADENCIA` nos dois, e `esta_dormente` diz a mesma coisa em
    Python -- ver a D1 do desenho.

    **`corte` e ligado a `agora`, e nao a `agora - INTERVALO_MINIMO`.** A
    subtracao e um corte barato que so serve a quem vai disparar: nao vale
    consultar a regua para quem falou ha cinco minutos. Aqui ela seria inocua
    -- o dormente mais recente possivel falou ha sete dias, o deslocamento da
    quarta tentativa do QUENTE -- e liga-la seria escrever no codigo uma
    intencao que nao existe.

    **O opt-out e consultado por lead, e nao juntado no SQL.**
    `esta_em_optout` e a funcao que decide o que e opt-out, e a varredura ja a
    chama assim; um JOIN aqui seria uma segunda fonte para a mesma pergunta --
    o defeito que a TEC-146 gastou uma card inteira consertando. E a razao de
    EXCLUIR, em vez de so marcar: esta lista existe para alimentar campanha
    manual, e a RN-14.3 condiciona qualquer novo contato de quem pediu opt-out
    a acao humana explicita com justificativa registrada. Entrega-lo numa
    lista rotulada "elegivel a campanha" convida exatamente o disparo que a
    regra proibe.

    **O `LIMIT` e aplicado antes do filtro de opt-out**, entao a lista pode vir
    com menos que `limite` havendo mais dormentes. E o mesmo comportamento de
    `candidatos_a_followup`, que corta em `:limite` e depois descarta nas
    guardas.

    `ORDER BY adormeceu_em DESC` poe quem adormeceu ha menos tempo primeiro:
    e o lead com mais chance de responder a uma campanha, e o unico criterio
    de ordem que a card sugere ao falar em segmentar a base.

    **Nao ha rota HTTP para isto, de proposito.** O projeto nao tem camada de
    autenticacao, e uma listagem sem auth expoe a base inteira de leads --
    mesmo argumento pelo qual a reativacao de opt-out da TEC-182 ficou sem
    rota. A TEC-189 chama esta funcao quando existir.
    """
    resultado = list(
        await session.execute(
            _SELECIONAR_DORMENTES,
            {
                "corte": agora,
                "limite": limite,
                "temperaturas_validas": _VALORES_TEMPERATURA_VALIDOS,
                **_TETOS_POR_TEMPERATURA,
            },
        )
    )
    if len(resultado) == limite:
        log.warning("followup.dormentes_saturados", limite=limite)
    dormentes = []
    for linha in resultado:
        if await esta_em_optout(
            session, channel=linha.channel, conversation_key=linha.conversation_key
        ):
            continue
        dormentes.append(
            LeadDormente(
                channel=linha.channel,
                conversation_key=linha.conversation_key,
                temperatura=Temperatura(linha.temperatura),
                ancora_em=linha.ancora,
                tentativas=linha.ja_disparada,
                adormeceu_em=linha.adormeceu_em,
            )
        )
    return dormentes
```

E acrescentar ao bloco de imports do topo do arquivo:

```python
from mobia.domain.optout.repositorio import esta_em_optout
```

> **Antes de escrever o import, confira que ele não cria ciclo.** `optout.repositorio` não importa nada de `followup`; se o `ruff check` ou o `mypy` acusarem import circular, o conserto é importar dentro da função, não inverter a dependência.

- [ ] **Step 6: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_listar_dormentes.py -q --tb=short`
Expected: PASS, os seis.

- [ ] **Step 7: Rodar os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 8: Commitar**

```bash
git add src/mobia/domain/followup/repositorio.py tests/integration/test_listar_dormentes.py
git commit -F- <<'MSG'
feat(TEC-187): a base de dormentes passa a ser consultavel, sem rota HTTP

listar_dormentes inverte o corte de candidatura e reusa as duas CTEs que
definem a ancora -- a agregacao nao e partilhada porque diverge de verdade.
Exclui quem tem opt-out: a lista alimenta campanha manual, e a RN-14.3 quer
acao humana com justificativa antes de qualquer novo contato.

Sem rota, pelo mesmo motivo da reativacao de opt-out da TEC-182: nao ha
camada de autenticacao, e uma listagem sem auth expoe a base inteira.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: O evento `followup.dormente`

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py:487-507` (acrescenta o bloco depois do `followup.antispam_atingido`)
- Test: `tests/integration/test_sweep_followups.py` (acrescenta ao fim)

**Interfaces:**
- Consumes: `esta_dormente` da Task 1, importado de `mobia.domain.followup.cadencia` (o módulo já importa `CADENCIA` de lá).
- Produces: o evento de log `followup.dormente`, com os campos `channel`, `conversation_key`, `temperatura`, `tentativas`, `ancora_em`. Nada de código depende dele.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `tests/integration/test_sweep_followups.py`, copiando a forma dos dois testes do evento de anti-spam que já estão lá (`:511-569`) — mesmo `_lead`, mesmo `_ctx()`, mesma contagem sobre `caplog.records`. O lead é `MORNO` e não `QUENTE` (o default de `_lead`) de propósito: é a temperatura do cenário 1 da card, e é a que prova que o evento não depende do teto coincidir com `MAXIMO_SEM_RESPOSTA`.

```python
async def test_a_tentativa_que_fecha_o_teto_emite_followup_dormente(session, caplog) -> None:
    """RN-13.5, cenario 1 da card. O evento marca o INSTANTE em que o lead
    adormece.

    Lead MORNO calado ha onze dias, com as tentativas 1 e 2 ja gravadas sob a
    ancora. A terceira vence (+10d) e e o teto do MORNO, entao grava-la
    adormece o lead.

    MORNO e nao QUENTE porque este evento nao pode depender do teto coincidir
    com `MAXIMO_SEM_RESPOSTA` -- e o defeito que deixou o
    `followup.antispam_atingido` alcancavel so no QUENTE.
    """
    parou_ha = timedelta(days=11)
    await _lead(session, temperatura="MORNO", calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    for numero in (1, 2):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                tentativa_numero=numero,
                temperatura="MORNO",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
            )
        )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.dormente" in r.getMessage()) == 1


async def test_a_tentativa_antes_do_teto_nao_emite_followup_dormente(session, caplog) -> None:
    """A outra metade: adormecer cedo e adormecer sempre sao defeitos
    diferentes, e um teste so nao separa os dois.

    Mesmo lead MORNO, uma tentativa gravada em vez de duas, e silencio de
    cinco dias -- bastante para a tentativa 2 (+4d) e nao para a 3 (+10d).
    """
    parou_ha = timedelta(days=5)
    await _lead(session, temperatura="MORNO", calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    session.add(
        FollowUp(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            tentativa_numero=1,
            temperatura="MORNO",
            ancora_em=ancora,
            devido_em=ancora + timedelta(days=1),
        )
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.dormente" in r.getMessage()) == 0
```

`caplog.at_level(logging.INFO)` basta mesmo o evento sendo `warning` — `WARNING` está acima de `INFO`, e é o mesmo nível que os testes do anti-spam já usam para capturar um `log.warning`.

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -q --tb=short -k dormente`
Expected: FAIL — `assert len([]) == 1`, porque nada emite o evento ainda.

- [ ] **Step 3: Escrever a implementação**

Em `src/mobia/workers/jobs/sweep_followups.py`, logo **depois** do bloco `if candidato.ja_enviadas + 1 == MAXIMO_SEM_RESPOSTA:` e antes de `enviados += 1`:

```python
            # RN-13.5. Depois do `commit` acima, pela mesma regra do
            # `followup.devido` logo acima: nada e logado antes de estar
            # gravado.
            #
            # **`DORMENTE` nao e gravado em lugar nenhum** -- e derivado de
            # `followups` por `esta_dormente`, e esta linha e so o instante
            # ficando visivel. Quem quiser o estado consulta
            # `listar_dormentes`; quem quiser o momento le este evento.
            #
            # **Dispara quando a ultima tentativa E ENVIADA, e nao depois de
            # ela ficar sem resposta.** O cenario 1 da card diz "quando a
            # ultima tentativa se esgota", e no desenho derivado esse instante
            # nao existe: nao ha tentativa pendente que expire, ha uma linha
            # que e gravada. Um lead que responder dez minutos depois ja terá
            # gerado esta linha -- e sairá de dormente na varredura seguinte,
            # porque a fala move a ancora. Divergencia declarada na D3.
            #
            # `esta_dormente` e nao `tentativa == len(CADENCIA[...])`: a conta
            # e a mesma, mas escrita aqui seria uma quarta copia do teto.
            if esta_dormente(temperatura=candidato.temperatura, ja_disparada=tentativa):
                # `warning` e nao `info`, mesmo nivel do
                # `followup.antispam_atingido` logo acima e pela mesma razao:
                # funcionou como desenhado, e alguem precisa saber -- um lead
                # acabou de sair do alcance da automacao. `conversation_key`
                # viaja porque o proposito da RN-13.5 e que a gerente consiga
                # agir sobre ESTE lead; `structlog` o mascara para os quatro
                # ultimos digitos antes de chegar ao log de verdade.
                log.warning(
                    "followup.dormente",
                    channel=candidato.channel,
                    conversation_key=candidato.conversation_key,
                    temperatura=candidato.temperatura.value,
                    tentativas=tentativa,
                    ancora_em=candidato.ancora_em.isoformat(),
                )
```

E no import de `cadencia` no topo do módulo, acrescentar `esta_dormente`:

```python
from mobia.domain.followup.cadencia import CADENCIA, esta_dormente
```

(confira a forma exata do import que já está lá e acrescente o nome, sem reescrever a linha inteira.)

- [ ] **Step 4: Rodar para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -q --tb=short`
Expected: PASS, os novos e todos os que já existiam.

- [ ] **Step 5: Rodar os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 6: Commitar**

```bash
git add src/mobia/workers/jobs/sweep_followups.py tests/integration/test_sweep_followups.py
git commit -F- <<'MSG'
feat(TEC-187): o instante em que um lead adormece fica visivel no log

followup.dormente sai depois do commit da linha, como followup.devido, e
usa esta_dormente em vez de recontar o teto. Diferente do
followup.antispam_atingido, e alcancavel nas tres temperaturas.

Dispara quando a ultima tentativa E ENVIADA: no desenho derivado nao existe
o instante em que uma tentativa pendente expira. Divergencia declarada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: A Emenda E-01 da RN-13.5 no SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (a linha da RN-13.5, e a tabela-índice do topo)

**Interfaces:**
- Consumes: o teor da emenda, já redigido na seção `## Emendas ao SRS` da spec.
- Produces: nada que o código consuma.

- [ ] **Step 1: Acrescentar a emenda abaixo da RN-13.5**

A RN-13.5 está na seção 2.5, **por volta da linha 375** — confirme localizando o texto, não o número. Acrescentar um item **aninhado** logo abaixo dela, **sem tocar no texto original de 22/08/2026**:

```markdown
  - **Emenda E-01 (TEC-187, 14/09/2026):** a regra manda que o lead esgotado vire `DORMENTE`, saia da cadência automática e permaneça elegível a campanha manual. Fica fixado que `DORMENTE` é **estado derivado e não coluna**: o lead está dormente quando o número de tentativas já disparadas sob a âncora atual alcança o teto da sua temperatura viva, e a pergunta é respondida por função pura (`esta_dormente`) e pela consulta `listar_dormentes`, sem nenhuma escrita nova no banco. **Consequência declarada:** a coluna `status` da entidade Lead da seção 5 continua não existindo, e dos sete valores que ela lista apenas `DORMENTE` ganha significado operacional — os outros seis seguem sem dono. Fica declarado também que *"sai da cadência automática"* já era verdade desde a Emenda E-01 da RN-13.4: o corte por temperatura da consulta de candidatos deixa de devolver o lead esgotado, e esta card não altera envio nenhum. A *"data e a quantidade de tentativas realizadas"* que a transição registra não são gravadas por esta card: são o `created_at` e o `tentativa_numero` da linha de `followups` da última tentativa. A elegibilidade a campanha manual é entregue como função de repositório **sem rota HTTP**, pelo mesmo motivo da reativação de opt-out da TEC-182, e a lista **exclui** o lead com opt-out registrado, porque a RN-14.3 condiciona qualquer novo contato dele a ação humana com justificativa. Por fim, a reativação do cenário 4 da card acontece **sem código**: a resposta do lead move a âncora e a contagem sob a âncora nova começa em zero — o estado `EM_CONVERSA` que o critério nomeia não é entregue, e o efeito observável que ele descreve é.
```

- [ ] **Step 2: Acrescentar a linha à tabela-índice do topo**

Na tabela de emendas do cabeçalho (por volta das linhas 18-36), acrescentar na ordem cronológica das vizinhas:

```markdown
| E-01 | RN-13.5 | [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187) | 14/09/2026 |
```

Copie a forma exata do link das linhas vizinhas — se elas usam outro formato de URL, use o delas.

- [ ] **Step 3: Conferir que o corpo original ficou intacto**

Run: `git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md`
Expected: **só linhas acrescentadas** (`+`), nenhuma removida ou alterada fora da tabela-índice. Se aparecer um `-` numa linha de regra, o texto de 22/08/2026 foi reescrito — desfaça.

- [ ] **Step 4: Commitar**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -F- <<'MSG'
docs(TEC-187): a RN-13.5 passa a dizer que DORMENTE e derivado e nao coluna

Emenda E-01, aninhada abaixo da regra, sem reescrever o texto de 22/08/2026.
Declara que a coluna status da secao 5 continua inexistente, que "sai da
cadencia automatica" ja valia desde a TEC-183, e que EM_CONVERSA nao e
entregue -- so o efeito observavel que o criterio descreve.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: Fechamento — comentários vizinhos e a suíte inteira

**Files:**
- Modify: o que a listagem de comentários apontar.

**Interfaces:**
- Consumes: tudo das Tasks 1 a 4.
- Produces: a árvore pronta para PR.

- [ ] **Step 1: Listar os comentários que a branch precisa reconferir**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

Ler **tudo**, nas duas categorias. `VIZINHO` é a que pega o defeito: comentário que ninguém editou, dentro de um `def`/`class` cujo código mudou — ele não aparece no diff, e por isso ninguém o relê.

Dois candidatos conhecidos, que provavelmente sairão como `VIZINHO`:

- A docstring de `candidatos_a_followup`, que descreve o corte de esgotamento e agora tem uma consulta irmã que o inverte. Se ela ficar como está, ela não mente — mas vale uma frase apontando para `listar_dormentes`, porque quem lê "o lead some da candidatura" agora pode perguntar para onde ele vai.
- O comentário de `id DESC`, que foi **movido** para `_CTES_DA_ANCORA`. Confira que ele continua fazendo sentido no lugar novo e que não sobrou uma cópia órfã no `_SELECIONAR_CANDIDATOS`.

Não é gate e não reprova nada: decidir se um comentário está certo é o julgamento que a listagem existe para devolver a uma pessoa.

- [ ] **Step 2: Rodar a suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: verde. Guarde o hash junto com o resultado.

> Se falhar: **não** conclua nada ainda. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados. Uma falha única com `ConnectionResetError [WinError 64]` não autoriza conclusão nenhuma. E dezenas de `relation ... does not exist` quase nunca são a sua migration — aqui não há migration nenhuma, então esse sintoma seria estado adiantado nos bancos dos workers, não a sua mudança. A segunda execução é ferramenta de diagnóstico, e só quando a primeira falha.

- [ ] **Step 3: Rodar os três gates uma última vez**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 4: Abrir o PR contra `main`**

E então, **na card**: comentar e mover para **Em análise** (não para Feito — quem mergeia é que fecha). O comentário precisa registrar, no mínimo:

- Que `EM_CONVERSA` **não foi entregue** (cenário 4 coberto pelo efeito, não pelo nome).
- Que o cenário 3 **não foi exercitado**: existe `listar_dormentes`, não existe dashboard nem rota — e a razão (sem camada de auth, precedente TEC-182).
- Que a card **não muda envio nenhum**: "sai da automação" já valia desde a TEC-183.
- Que a coluna `status` da seção 5 do SRS continua inexistente, contrariando o que o desenho da TEC-147 previa (`L1`).
- Que a estabilidade do estado derivado é uma medição de hoje, e a TEC-158 e a TEC-192 a quebram (`L4`) — **isso é decisão de produto, não de código**.
- A Emenda E-01 da RN-13.5, nomeada.

## Cobertura dos critérios de aceite

| Cenário da card | Onde | Situação |
| --- | --- | --- |
| 1 — Esgotar as tentativas marca o lead como dormente | Task 1 (`esta_dormente`), Task 3 (o evento) | Coberto. "Nenhuma nova tentativa é agendada" já valia desde a TEC-183 e tem teste lá |
| 2 — Registro da transição (data e nº de tentativas) | Task 2, `test_a_data_e_a_contagem_da_transicao` | Coberto, lendo o que a TEC-183 já grava |
| 3 — Dormente aparece no filtro do dashboard | Task 2, `listar_dormentes` | **Parcial.** A consulta existe e é testada; o dashboard não existe (TEC-189) e não há rota — `L2` |
| 4 — Resposta reativa o lead | Task 2, `test_quem_respondeu_depois_de_esgotar_deixa_de_ser_dormente` | **Pelo efeito, não pelo nome.** A nova cadência a partir da nova última mensagem está coberta; `EM_CONVERSA` não é entregue — `D4` |
