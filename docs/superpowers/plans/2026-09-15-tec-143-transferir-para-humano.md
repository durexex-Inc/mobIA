# TEC-143 — Transferir para humano ao pedido explícito

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando o lead pede para falar com uma pessoa, o turno cria handoff de prioridade ALTA sem chamar o modelo, avisa o lead (com a janela de atendimento se estiver fora dela), e o agente cala enquanto o handoff estiver aberto.

**Architecture:** Uma guarda determinística em `executar_turno`, no molde exato da guarda de opt-out que já existe logo acima dela — detecção pura em módulo próprio, sem chamada paga. O gatilho `PEDIDO_DE_HUMANO` e `registrar_handoff` já existem e só ganham um chamador. O silêncio vem de uma consulta nova por handoff aberto, e **não** de `AtendimentoHumano`, que exige um corretor que ainda não existe no instante do pedido.

**Tech Stack:** Python 3.13, SQLAlchemy async, Pydantic Settings, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-15-tec-143-transferir-para-humano-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o valor.
- **Texto que o lead recebe: português COM acento** (TEC-267). Vale para `TEXTO_DO_PEDIDO_DE_HUMANO` e `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`.
- **Mensagem de commit:** `tipo(TEC-143): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates, com este escopo exato, antes de qualquer commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter.
- **Testes:** `tests/unit/` não precisa de Docker. `tests/integration/` e `tests/features/` exigem `docker compose` de pé. Rode o arquivo inteiro, sem `-k`.
- **A ordem das guardas é invariante de LGPD:** opt-out sempre antes do pedido de humano. O comentário em `turno.py:749-758` registra o Critical em que uma guarda incondicional engoliu o registro do opt-out.
- **`Gatilho.PEDIDO_DE_HUMANO` já existe** e `PRIORIDADE_DE` já o mapeia para `ALTA`. Não mexa no enum nem no mapa.

---

## File Structure

| arquivo | responsabilidade |
| --- | --- |
| `src/mobia/domain/humano/__init__.py` (cria) | pacote novo |
| `src/mobia/domain/humano/deteccao.py` (cria) | `pediu_humano`, os dois textos ao lead, o kind e o subagente |
| `src/mobia/domain/handoff/repositorio.py` (modifica) | acrescenta `tem_handoff_de_humano_aberto` |
| `src/mobia/app/config.py` (modifica) | `atendimento_horario_inicio` / `atendimento_horario_fim` |
| `src/mobia/domain/agente/turno.py` (modifica) | a guarda, e o literal novo de `ResultadoDoTurno` |
| `tests/unit/test_deteccao_de_humano.py` (cria) | a detecção, pura |
| `tests/integration/test_pedido_de_humano.py` (cria) | a guarda dentro do turno |

---

### Task 1: A detecção do pedido

**Files:**
- Create: `src/mobia/domain/humano/__init__.py` (vazio), `src/mobia/domain/humano/deteccao.py`
- Test: `tests/unit/test_deteccao_de_humano.py`

**Interfaces:**
- Consumes: nada
- Produces: `pediu_humano(texto: str) -> bool`

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_deteccao_de_humano.py`:

```python
"""A guarda que manda o lead para uma pessoa, testada.

TEC-143. Pura: nao toca banco, nao toca modelo. A decisao de transferir nao
pode depender de um provedor estar de pe, pelo mesmo motivo que a de opt-out
nao pode -- ver `domain/optout/deteccao.py`.
"""

import pytest

from mobia.domain.humano.deteccao import pediu_humano


@pytest.mark.parametrize(
    "texto",
    [
        "quero falar com uma pessoa",
        "Quero Falar Com Uma Pessoa!",
        "me passa pra um atendente por favor",
        "prefiro falar com um humano",
        "queria falar com atendente",
        "quero atendimento humano",
        "cansei de robo, quero uma pessoa",
    ],
)
def test_pedido_explicito_dispara(texto: str) -> None:
    assert pediu_humano(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        # Os dois casos reais do corpus de evals, ambos sobre assinar a
        # distancia. Medido na TEC-143: "pessoa" aparece 2 vezes nas 147
        # mensagens do corpus, as duas dentro de "pessoalmente".
        "consigo fechar tudo a distancia, sem vir pessoalmente antes?",
        "precisa vir pessoalmente pra assinar ou consigo por procuracao?",
        # O corretor como ASSUNTO, nao como pedido de transferencia.
        "o corretor falou que tem vaga dupla",
        "depois eu falo com o corretor sobre o financiamento",
        # Qualificacao normal.
        "quero um apartamento de dois quartos em Pinheiros",
        "",
    ],
)
def test_conversa_normal_nao_dispara(texto: str) -> None:
    assert pediu_humano(texto) is False


def test_pessoa_sozinha_nao_e_pedido() -> None:
    """A armadilha analoga a do opt-out, e a razao de nenhum termo ser palavra solta.

    `domain/optout/deteccao.py` registra que "nao quero mais receber nada" saiu
    dos inequivocos porque "nada" aceita complemento partitivo. Aqui o termo
    perigoso e "pessoa": casado por substring ele pega "pessoalmente", que no
    corpus aparece so em pergunta sobre procuracao. Todo termo desta lista
    carrega o verbo ou a preposicao que o torna um pedido.
    """
    assert pediu_humano("pessoa") is False
    assert pediu_humano("vou pessoalmente ver o imovel") is False


@pytest.mark.parametrize("texto", ["atendente", "Atendente?", "humano"])
def test_termo_ambiguo_so_casa_a_mensagem_inteira(texto: str) -> None:
    """Mesma faixa estrita do opt-out: sozinho e pedido, no meio de frase nao.

    Um lead que escreve so "atendente" esta pedindo. O mesmo substantivo dentro
    de "o atendente anterior me falou outro valor" e assunto.
    """
    assert pediu_humano(texto) is True
    assert pediu_humano("o atendente anterior me falou outro valor") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.humano'`

- [ ] **Step 3: Write minimal implementation**

Crie `src/mobia/domain/humano/__init__.py` vazio e `src/mobia/domain/humano/deteccao.py`:

```python
"""O lead pediu para falar com uma pessoa.

TEC-143. Deterministico e sem chamada paga, pela mesma razao que
`domain/optout/deteccao.py` declara para o opt-out: a decisao nao pode depender
de um provedor estar de pe. Aqui o argumento e ainda mais direto -- o provedor
falha pior justamente quando o lead ja esta irritado o bastante para pedir uma
pessoa.

Medido na TEC-143: acrescentar `FALAR_COM_HUMANO` ao enum `Intencao` custaria
5 tokens no schema compilado e levaria a margem do orcamento de prompt de 6,2
para 1,2 -- mas o que decidiu nao foi o custo, foi a dependencia.
"""

import re
import unicodedata

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")

# Casam por substring: carregam o verbo ou a preposicao que os torna um pedido,
# e nenhum e palavra solta.
#
# **Nenhum termo aqui e so um substantivo, e isso e deliberado.** O modulo de
# opt-out registra o preco de errar nisso: "nao quero mais receber nada" saiu
# dos inequivocos porque "nada" aceita complemento partitivo e cada refinamento
# de busca silenciava um comprador. O analogo aqui e "pessoa" -- medido contra
# as 147 mensagens de lead do corpus de evals, ele aparece 2 vezes, as duas
# dentro de "pessoalmente", em perguntas sobre assinar a distancia.
_TERMOS_INEQUIVOCOS: tuple[str, ...] = (
    "falar com uma pessoa",
    "falar com um humano",
    "falar com humano",
    "falar com um atendente",
    "falar com uma atendente",
    "falar com atendente",
    "falar com alguem de verdade",
    "falar com um corretor de verdade",
    "quero uma pessoa",
    "queria uma pessoa",
    "me passa pra uma pessoa",
    "me passa para uma pessoa",
    "me passa pra um atendente",
    "me passa para um atendente",
    "me transfere",
    "quero atendimento humano",
    "atendimento humano",
    "nao quero falar com robo",
    "cansei de robo",
    "para de robo",
)

# So casam a mensagem INTEIRA. Um lead que escreve so "atendente" esta pedindo;
# o mesmo substantivo dentro de uma frase e assunto, nao pedido.
_TERMOS_AMBIGUOS: frozenset[str] = frozenset({"atendente", "humano", "pessoa real"})


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    Mesmo normalizador do opt-out, e pela mesma razao: "ATENDENTE!" e
    "atendente" sao a forma que um lead irritado escreve, e a faixa estrita
    compara a mensagem inteira.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def pediu_humano(texto: str) -> bool:
    """O lead pediu explicitamente para ser atendido por uma pessoa."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if normalizado in _TERMOS_AMBIGUOS:
        return True
    return any(termo in normalizado for termo in _TERMOS_INEQUIVOCOS)


# Mora aqui, e nao em `turno.py`, pelo mesmo motivo que
# `TEXTO_DA_CONFIRMACAO_DE_OPTOUT` mora no modulo de opt-out: o texto pertence
# ao assunto, nao ao orquestrador que o entrega.
#
# COM acento: e texto que chega ao lead (TEC-267).
TEXTO_DO_PEDIDO_DE_HUMANO = (
    "Claro! Já avisei nossa equipe e um corretor vai falar com você por aqui. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# `{inicio}` e `{fim}` sao preenchidos com as horas locais da janela.
TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO = (
    "Claro! Já avisei nossa equipe. Nosso atendimento é das {inicio}h às {fim}h, "
    "então um corretor vai falar com você no próximo horário. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# Kind proprio pela mesma razao do kind da confirmacao de opt-out: a reserva em
# `outbound_dispatches` nao pode colidir com a resposta que este turno nao vai
# mandar.
KIND_DO_PEDIDO_DE_HUMANO = "pedido_de_humano"

SUBAGENTE_PEDIDO_DE_HUMANO = "pedido_de_humano"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py --tb=short`
Expected: todos passam

- [ ] **Step 5: Confirmar que a lista nao regride contra o corpus**

Este comando é a medição da D2 do desenho, refeita contra o código real. Rode e confirme `0`:

```bash
./.venv/Scripts/python.exe -c "
import sys, pathlib, yaml; sys.path.insert(0, 'src')
from mobia.domain.humano.deteccao import pediu_humano
msgs = []
for f in pathlib.Path('evals/corpus').glob('*.yaml'):
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('mensagem','texto','lead','entrada') and isinstance(v, str): msgs.append(v)
                else: walk(v)
        elif isinstance(o, list):
            for i in o: walk(i)
    walk(yaml.safe_load(f.read_text(encoding='utf-8')))
falsos = [m for m in msgs if pediu_humano(m)]
print(f'{len(msgs)} mensagens, {len(falsos)} falso(s) positivo(s)')
for m in falsos: print('  ', m)
"
```

Expected: `147 mensagens, 0 falso(s) positivo(s)`. Se aparecer algum, **não relaxe o teste** — tire o termo culpado da lista e registre a razão num comentário, como o opt-out fez com "nada".

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/humano tests/unit/test_deteccao_de_humano.py
git commit -m "feat(TEC-143): o pedido de humano e detectado sem chamada paga

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A consulta de handoff aberto por pedido de humano

**Files:**
- Modify: `src/mobia/domain/handoff/repositorio.py` (acrescenta a função ao final)
- Test: `tests/integration/test_pedido_de_humano.py` (cria)

**Interfaces:**
- Consumes: `Gatilho.PEDIDO_DE_HUMANO`, `Status` e o modelo `Handoff`, todos já existentes
- Produces: `tem_handoff_de_humano_aberto(session: AsyncSession, *, channel: str, conversation_key: str) -> bool`

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_pedido_de_humano.py`:

```python
"""A transferencia para humano ao pedido do lead, ponta a ponta.

TEC-143.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.repositorio import registrar_handoff, tem_handoff_de_humano_aberto
from mobia.domain.handoff.vocabulario import Gatilho


async def test_sem_handoff_a_conversa_nao_esta_esperando_humano(session: AsyncSession) -> None:
    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110001"
        )
        is False
    )


async def test_handoff_de_pedido_de_humano_deixa_a_conversa_esperando(
    session: AsyncSession,
) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110002",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110002"
        )
        is True
    )


async def test_handoff_de_outro_gatilho_nao_cala_o_agente(session: AsyncSession) -> None:
    """Um lead que esquentou tem handoff aberto e continua sendo atendido.

    Calar por qualquer handoff aberto tiraria o agente de toda conversa que
    virou QUENTE -- que e o oposto do que o gatilho QUENTE significa. So o
    pedido explicito do lead cala.
    """
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110003",
        gatilho=Gatilho.LEAD_QUENTE,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110003"
        )
        is False
    )


async def test_pedido_que_chega_depois_do_quente_tambem_cala(session: AsyncSession) -> None:
    """O gatilho pode estar em `gatilhos_adicionais`, e nao na coluna `gatilho`.

    Um lead que esquentou ja tem handoff aberto; quando ele pede uma pessoa,
    `registrar_handoff` ACUMULA o gatilho na linha existente em vez de criar
    outra. Olhar so a coluna `gatilho` perderia exatamente este caso, que e o
    mais comum: quem ja conversou o bastante para esquentar e quem mais se
    cansa de robo.
    """
    for gatilho in (Gatilho.LEAD_QUENTE, Gatilho.PEDIDO_DE_HUMANO):
        await registrar_handoff(
            session,
            channel="whatsapp",
            conversation_key="5511911110005",
            gatilho=gatilho,
        )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110005"
        )
        is True
    )


async def test_a_consulta_e_por_conversa_e_por_canal(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110004",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="web", conversation_key="5511911110004"
        )
        is False
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_pedido_de_humano.py --tb=short`
Expected: FAIL com `ImportError: cannot import name 'tem_handoff_de_humano_aberto'`

- [ ] **Step 3: Write minimal implementation**

Acrescente ao final de `src/mobia/domain/handoff/repositorio.py`. Todos os nomes abaixo já existem no arquivo: `Handoff.gatilho` é o gatilho que CRIOU o handoff, `Handoff.gatilhos_adicionais` é a lista dos que chegaram depois, e `any_` e `or_` já estão nos imports:

```python
async def tem_handoff_de_humano_aberto(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> bool:
    """A conversa esta esperando uma pessoa porque o lead pediu.

    **E daqui que vem o silencio do agente na TEC-143, e nao de
    `atendimento.esta_silenciada`.** Aquela responde "um corretor assumiu", e
    `assumir` exige `corretor_id`: no instante do pedido nao ha corretor
    nenhum, o handoff acabou de nascer e esta na fila. Esta funcao responde a
    pergunta que existe nesse instante -- "tem gente a caminho?".

    Olha as DUAS colunas de gatilho. Um lead que esquentou e so depois pediu
    uma pessoa tem `PEDIDO_DE_HUMANO` em `gatilhos_adicionais`, nao em
    `gatilho` -- e o silencio vale igual. `registrar_handoff` acumula em vez de
    criar linha nova, e a `0030` garante no banco no maximo um handoff aberto
    por conversa.

    So o gatilho `PEDIDO_DE_HUMANO` cala. Calar por qualquer handoff aberto
    tiraria o agente de toda conversa que virou QUENTE, que e o oposto do que
    aquele gatilho significa.

    "Aberto" e `status <> CONCLUIDO`, o mesmo criterio do `index_where` do
    indice parcial que arbitra a deduplicacao -- um handoff ACEITO ou ESCALADO
    continua sendo gente a caminho.
    """
    alvo = Gatilho.PEDIDO_DE_HUMANO.value
    existe = await session.scalar(
        select(Handoff.id)
        .where(
            Handoff.channel == channel,
            Handoff.conversation_key == conversation_key,
            Handoff.status != Status.CONCLUIDO.value,
            or_(
                Handoff.gatilho == alvo,
                literal(alvo) == any_(Handoff.gatilhos_adicionais),
            ),
        )
        .limit(1)
    )
    return existe is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_pedido_de_humano.py --tb=short`
Expected: 5 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/handoff/repositorio.py tests/integration/test_pedido_de_humano.py
git commit -m "feat(TEC-143): o handoff aberto por pedido de humano e consultavel

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A janela de atendimento

**Files:**
- Modify: `src/mobia/app/config.py` (acrescenta os dois campos junto dos `followup_horario_*`)
- Test: `tests/unit/test_deteccao_de_humano.py` (acrescenta)

**Interfaces:**
- Consumes: nada
- Produces: `Settings.atendimento_horario_inicio: int` (default 9), `Settings.atendimento_horario_fim: int` (default 18), e `dentro_da_janela_de_atendimento(agora: datetime) -> bool` em `domain/humano/deteccao.py`

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/unit/test_deteccao_de_humano.py`:

```python
from datetime import UTC, datetime

from mobia.domain.humano.deteccao import dentro_da_janela_de_atendimento


def test_a_janela_inclui_a_hora_de_abertura() -> None:
    """9h em ponto ja e atendimento, com o default de inicio 9."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 12, 0, tzinfo=UTC)) is True


def test_fora_da_janela_de_madrugada() -> None:
    """As 23h de uma terca -- o cenario Gherkin da card."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 16, 2, 0, tzinfo=UTC)) is False
```

**Atenção ao fuso:** os horários da janela são locais (o mesmo `followup_fuso` da POC, PR-04), e o `datetime` do teste está em UTC. Ajuste as horas do teste para que, convertidas ao fuso local configurado, caiam dentro e fora da janela — rode e confira, não presuma o deslocamento.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py --tb=short`
Expected: FAIL com `ImportError: cannot import name 'dentro_da_janela_de_atendimento'`

- [ ] **Step 3: Write minimal implementation**

Em `src/mobia/app/config.py`, junto dos campos `followup_horario_inicio`/`followup_horario_fim`:

```python
    # RN-16.1 (TEC-143): a janela em que existe gente para atender, em horas
    # locais do `followup_fuso`. Fora dela o handoff e criado do mesmo jeito --
    # so o texto que o lead recebe muda, porque a card e explicita em que ele
    # nunca fica em espera silenciosa.
    #
    # Janela da imobiliaria, e nao a jornada do corretor designado: no instante
    # do pedido ninguem foi designado ainda, e a alocacao por especialidade e
    # regiao e a TEC-166. Uma janela unica responde "quando alguem te atende"
    # sem precisar saber quem.
    atendimento_horario_inicio: int = 9
    atendimento_horario_fim: int = 18
```

Em `domain/humano/deteccao.py`, acrescente a função. Ela lê `get_settings()`, converte `agora` para o fuso local configurado e compara a hora contra a janela. **Use a mesma convenção de borda que `followup_horario_fim` documenta** — leia aquele comentário em `config.py` antes de escolher entre `<` e `<=`, e escreva no seu comentário qual convenção adotou e por quê.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py --tb=short`
Expected: todos passam

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/app/config.py src/mobia/domain/humano/deteccao.py tests/unit/test_deteccao_de_humano.py
git commit -m "feat(TEC-143): a janela de atendimento da imobiliaria vira configuracao

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A guarda no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — o literal de `ResultadoDoTurno` (perto da linha 336) e a guarda nova (depois do bloco `if pedido_de_optout:` que começa na linha 774)
- Test: `tests/integration/test_pedido_de_humano.py` (acrescenta)

**Interfaces:**
- Consumes: `pediu_humano`, `TEXTO_DO_PEDIDO_DE_HUMANO`, `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`, `KIND_DO_PEDIDO_DE_HUMANO`, `SUBAGENTE_PEDIDO_DE_HUMANO`, `dentro_da_janela_de_atendimento` (T1 e T3); `tem_handoff_de_humano_aberto` (T2); `registrar_handoff` e `Gatilho.PEDIDO_DE_HUMANO` (já existiam)
- Produces: o literal `"pedido_de_humano"` em `ResultadoDoTurno`

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_pedido_de_humano.py` os testes de turno. Use a fixture `rodar_turno` que já existe em `tests/conftest.py` — **leia a assinatura dela antes de escrever**, ela semeia a entrada e roda o turno inteiro.

Os testes a escrever, um por comportamento:

1. `test_pedido_de_humano_cria_handoff_alta_e_nao_chama_o_modelo` — o lead escreve "quero falar com uma pessoa" no meio da qualificação. Afirma: existe handoff com gatilho `PEDIDO_DE_HUMANO` e prioridade `ALTA`; o `ClassificadorFake` **não** foi chamado; o desfecho é `"pedido_de_humano"`.
2. `test_optout_na_mesma_mensagem_vence_o_pedido_de_humano` — mensagem que é as duas coisas. Afirma: o opt-out **está gravado**; o desfecho é `"opt_out"`. Docstring citando o Critical de `turno.py:749-758`.
3. `test_depois_do_pedido_o_agente_cala_e_a_mensagem_e_registrada` — segundo turno na mesma conversa. Afirma: nenhuma resposta do agente foi enviada; a linha da mensagem nova existe em `messages`.
4. `test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito` — congele o relógio fora da janela. Afirma: o handoff existe; o texto entregue é o de fora do horário e nomeia a janela.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_pedido_de_humano.py --tb=short`
Expected: FAIL — a guarda não existe, o turno segue para o classificador

- [ ] **Step 3: Write minimal implementation**

Primeiro, o literal novo. Em `turno.py`, perto da linha 336, depois de `"bloqueado_por_atendimento_humano"`:

```python
    # A TEC-143 acrescentou este. Nao reuse "atendimento_humano": aquele e o
    # turno que nao fez nada porque um corretor JA tinha assumido; este e o
    # turno em que o LEAD pediu e o handoff acabou de nascer. Duas historias
    # com donos diferentes -- mesmo criterio que o comentario acima aplica aos
    # tres do opt-out.
    "pedido_de_humano",
```

Depois, a guarda. Ela entra **depois** do bloco `if pedido_de_optout:` (linha 774) e **antes** da moderação de entrada. Estrutura:

```python
    # ORDEM: depois do opt-out, antes do classificador.
    #
    # Depois do opt-out porque opt-out e direito do lead e vence tudo -- uma
    # mensagem que pede humano E pede saida grava a saida. O comentario da
    # guarda de atendimento humano, algumas linhas acima, registra o Critical
    # em que uma guarda incondicional engoliu exatamente esse registro.
    #
    # Antes do classificador porque um pedido de humano nao precisa de modelo
    # para ser atendido, e a card pede handoff em ate 5 segundos. Pulando a
    # chamada, o prazo vira consequencia da arquitetura em vez de aposta na
    # latencia do provedor -- e nao ha chamada paga para falhar justamente
    # quando o lead ja esta irritado.
    if corpo and pediu_humano(corpo):
        ...
```

O corpo completo, no molde do bloco de opt-out (linhas 774-820):

```python
    if corpo and pediu_humano(corpo):
        async with session_factory() as sessao:
            await registrar_handoff(
                sessao,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.PEDIDO_DE_HUMANO,
            )
            # `registrar_handoff` NAO commita -- a docstring dela diz que o
            # commit e de quem chama, para o handoff poder entrar na mesma
            # transacao de um recalculo. Aqui nao ha nada para juntar, entao o
            # commit e imediato: o lead nao pode receber "ja avisei a equipe"
            # sem a linha existir.
            await sessao.commit()

        settings = get_settings()
        texto = (
            TEXTO_DO_PEDIDO_DE_HUMANO
            if dentro_da_janela_de_atendimento(datetime.now(UTC))
            else TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
                inicio=settings.atendimento_horario_inicio,
                fim=settings.atendimento_horario_fim,
            )
        )
        log.info(
            "turno.pedido_de_humano",
            channel=message.channel,
            message_id=str(message.id),
        )
        # Nome distinto de `entregue` pelo mesmo motivo que o bloco do opt-out
        # explica: o mypy infere um tipo unico por nome de variavel na funcao
        # inteira, e este e o `ResultadoDoTurno` de `_entregar_texto_fixo`.
        desfecho_do_aviso = await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=texto,
            kind=KIND_DO_PEDIDO_DE_HUMANO,
            subagent=SUBAGENTE_PEDIDO_DE_HUMANO,
        )
        # O handoff JA esta gravado. Se o aviso nao saiu, o desfecho do envio
        # passa adiante como esta -- mas a transferencia aconteceu de qualquer
        # forma, que e o que a card garante ao lead.
        return "pedido_de_humano" if desfecho_do_aviso == "respondido" else desfecho_do_aviso
```

**Confira duas coisas antes de commitar, porque o plano não as adivinha:** se `get_settings` e `log` já estão no escopo daquele ponto de `turno.py` (provavelmente sim, o bloco de opt-out usa ambos), e se `_entregar_texto_fixo` pula a checagem de atendimento humano para o kind novo — leia os dois `if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` lá dentro. **Se ele não pular, o aviso é barrado pela própria guarda de silêncio que este bloco acabou de ativar**, e o lead não recebe nada. Se for o caso, o kind novo precisa do mesmo tratamento, e isso vira um comentário explicando por quê.

Por fim, a guarda do silêncio: no bloco que hoje chama `esta_silenciada` (linha 762), acrescente a segunda fonte — a conversa também cala quando `tem_handoff_de_humano_aberto` responde `True`. Mantenha o resultado `"atendimento_humano"` quando for o corretor que assumiu.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_pedido_de_humano.py --tb=short`
Expected: todos passam

- [ ] **Step 5: Gates, suíte inteira e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta. Se falhar, rode de novo sobre a mesma árvore antes de culpar a mudança — há falhas conhecidas de `ConnectionResetError [WinError 64]` neste repo. Se persistir idêntica em duas execuções, **pare e relate**.

```bash
git add src/mobia/domain/agente/turno.py tests/integration/test_pedido_de_humano.py
git commit -m "feat(TEC-143): o pedido de humano interrompe a qualificacao e cala o agente

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A prosa que descreve o que mudou

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emenda à RN-16.1)
- Test: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py main`

- [ ] **Step 1: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
```

Releia o que ela apontar. Ela agora aponta também prosa em `.md` (TEC-282). **A ferramenta é cega a docstring de módulo** (TEC-283, aberta), então confira à mão a docstring de topo de todo arquivo que você tocou.

- [ ] **Step 2: Emendar o SRS**

A RN-16.1 lista os gatilhos de handoff. Esta card é a primeira a acionar `PEDIDO_DE_HUMANO` de verdade, e acrescenta a janela de atendimento, que a regra não previa. Entre como item aninhado **`Emenda E-nn (TEC-143, 15/09/2026)`** abaixo da regra, **sem reescrever** o texto de 22/08/2026 — é a convenção do CLAUDE.md. Use o próximo `nn` livre naquela regra.

A emenda declara: a detecção é determinística e não semântica; fora da janela de atendimento o handoff é criado do mesmo jeito e só o texto ao lead muda; e o agente cala enquanto o handoff de pedido de humano estiver aberto.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add docs/srs/
git commit -m "docs(TEC-143): a RN-16.1 ganha a emenda da janela e da deteccao deterministica

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite da card

| cenário Gherkin | onde é exercitado |
| --- | --- |
| Pedido explícito interrompe a qualificação | T4 `test_pedido_de_humano_cria_handoff_alta_e_nao_chama_o_modelo` — inclusive a parte "nenhuma tentativa de retenção", já que o modelo não é chamado |
| Registro continua após a transferência | T4 `test_depois_do_pedido_o_agente_cala_e_a_mensagem_e_registrada` |
| Pedido fora do horário de atendimento | T3 (a janela) e T4 `test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito` |

**Fica sem teste automatizado:** o "em até 5 segundos" da regra de negócio. Não é medido por asserção de tempo — medir latência em runner compartilhado seria flake, e o `addopts` do projeto exclui os testes de latência justamente por isso. O prazo é garantido por construção: quando a guarda dispara, nenhuma chamada ao modelo acontece. Isso vai no comentário da card.

**Divergência em relação à card, decidida no desenho (D3):** a card sugeria que o agente parasse de conduzir a qualificação pelo mecanismo existente; o silêncio vem de uma consulta nova por handoff aberto, porque `AtendimentoHumano` exige um corretor que não existe no instante do pedido.
