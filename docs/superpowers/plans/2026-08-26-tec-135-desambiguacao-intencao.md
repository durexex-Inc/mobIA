# TEC-135 — Desambiguar quando a confiança fica abaixo de 0,6 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando o classificador devolve confiança abaixo de 0,6, o lead recebe uma única pergunta aberta em vez de uma resposta que assume a intenção — uma vez por episódio de ambiguidade.

**Architecture:** O turno do TEC-134 ganha um ramo. A primeira chamada ao modelo continua idêntica; se a confiança ficar abaixo do limiar e o episódio ainda não tiver desambiguado, o código descarta a resposta gerada e faz uma segunda chamada dedicada à pergunta. Uma coluna nova em `conversation_intent` (`desambiguado_em`) marca o episódio, é escrita **depois** da entrega confirmada e é limpa por qualquer classificação com confiança no limiar ou acima.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async, asyncpg, Alembic, arq, Anthropic SDK, pytest-asyncio, structlog, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-26-tec-135-desambiguacao-intencao-design.md`

## Global Constraints

- **Nenhum teste toca a rede.** O classificador é sempre dublê; nenhum teste constrói cliente Anthropic real nem chama a API do modelo.
- **Nada loga conteúdo do lead nem a fala do agente.** Logs carregam só números, ids de modelo e chaves estruturadas. `RespostaInvalida` nunca interpola o texto recebido.
- **Confiança é `Decimal`, nunca `float`.** A coluna é `numeric(3,2)` e o critério de aceite é uma igualdade de borda em 0,6.
- **O marcador só é escrito depois de `send()` devolver `True`.** `expirado`, `recusado` e `reentrega_suprimida` não marcam.
- **A tabela guarda o que o classificador devolveu, sem edição.** `INDEFINIDA` abaixo do limiar é derivado na leitura, nunca gravado por cima do palpite.
- Gates de toda task: `pytest -q`, `ruff check src tests alembic`, `ruff format --check src tests alembic`, `mypy`.
- Commits em português, sem acentos na mensagem, prefixo convencional com `(TEC-135)`.
- Branch: `feat/tec-135-desambiguacao-intencao` (já criada, com o spec commitado).

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/agente/schemas.py` | **Modifica.** Ganha `LIMIAR_DE_DESAMBIGUACAO` e o dataclass `PerguntaDeDesambiguacao`. |
| `src/mobia/domain/agente/desambiguacao.py` | **Cria.** As duas decisões puras: se deve perguntar, e qual é a intenção efetiva. Sem I/O. |
| `src/mobia/domain/agente/models.py` | **Modifica.** Coluna `desambiguado_em`. |
| `alembic/versions/0007_desambiguacao_de_intencao.py` | **Cria.** `add_column` / `drop_column`. |
| `src/mobia/domain/agente/repositorio.py` | **Modifica.** Lê e limpa o marcador; nova `marcar_desambiguacao`; propriedade `efetiva`. |
| `src/mobia/domain/agente/classificador.py` | **Modifica.** `SISTEMA_DA_DESAMBIGUACAO`, `desambiguar()` no port e na implementação. |
| `src/mobia/domain/agente/turno.py` | **Modifica.** O ramo, a escolha do texto e a gravação do marcador. |
| `tests/conftest.py` | **Modifica.** `ClassificadorFake` ganha `desambiguar`. |

---

## Task 1: O limiar e as duas decisões puras

Nada de banco, nada de modelo. Esta task existe primeiro porque é ela que torna o cenário do limite exato um teste de três linhas, e porque as tasks 2 e 4 importam dela.

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py`
- Create: `src/mobia/domain/agente/desambiguacao.py`
- Test: `tests/unit/test_desambiguacao.py`

**Interfaces:**
- Consumes: `Intencao` de `mobia.domain.agente.schemas`.
- Produces:
  - `LIMIAR_DE_DESAMBIGUACAO: Decimal` (em `schemas.py`)
  - `deve_desambiguar(confianca: Decimal, desambiguado_em: datetime | None) -> bool`
  - `intencao_efetiva(intencao: Intencao, confianca: Decimal) -> Intencao`

- [ ] **Step 1: Escrever os testes que vão falhar**

Criar `tests/unit/test_desambiguacao.py`:

```python
"""As duas decisoes do TEC-135, sem banco e sem modelo.

O cenario de aceite "confianca exatamente 0,6 nao desambigua" mora aqui e nao
num teste de integracao: e uma comparacao de borda, e o resto do turno nao
acrescenta nada a prova.
"""

from datetime import UTC, datetime
from decimal import Decimal

from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao

JA_PERGUNTOU = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_confianca_no_limiar_exato_nao_desambigua() -> None:
    """Criterio de aceite: 0,6 e fechado por cima."""
    assert deve_desambiguar(Decimal("0.6"), None) is False


def test_logo_abaixo_do_limiar_desambigua() -> None:
    assert deve_desambiguar(Decimal("0.59"), None) is True


def test_marcador_preenchido_impede_a_segunda_pergunta() -> None:
    """Ambiguidade persistente nao vira insistencia."""
    assert deve_desambiguar(Decimal("0.45"), JA_PERGUNTOU) is False


def test_confianca_alta_nao_desambigua_com_ou_sem_marcador() -> None:
    assert deve_desambiguar(Decimal("0.91"), None) is False
    assert deve_desambiguar(Decimal("0.91"), JA_PERGUNTOU) is False


def test_intencao_abaixo_do_limiar_e_indefinida() -> None:
    """O palpite existe na tabela, mas ninguem roteia por ele."""
    assert intencao_efetiva(Intencao.COMPRA, Decimal("0.45")) is Intencao.INDEFINIDA


def test_intencao_no_limiar_exato_e_preservada() -> None:
    assert intencao_efetiva(Intencao.COMPRA, LIMIAR_DE_DESAMBIGUACAO) is Intencao.COMPRA


def test_intencao_confiante_passa_intacta() -> None:
    assert intencao_efetiva(Intencao.ALUGUEL, Decimal("0.91")) is Intencao.ALUGUEL
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/unit/test_desambiguacao.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.agente.desambiguacao'`.

- [ ] **Step 3: Acrescentar o limiar em `schemas.py`**

Logo depois da classe `Intencao`, antes de `RespostaDoAgente`:

```python
# Limiar da RN-03.2. `Decimal` e nao `float` porque a coluna e `numeric(3,2)` e
# a comparacao e de igualdade na borda: `0.6` em binario nao e 0,6, e "confianca
# exatamente 0,6 nao desambigua" e criterio de aceite.
#
# Fechado por cima: `< LIMIAR` desambigua, `>= LIMIAR` nao. O numero vem do SRS
# e nao esta calibrado -- confianca e autoavaliacao do modelo, nao
# probabilidade. Quem vai medi-lo contra as 50 conversas anotadas e a TEC-210, e
# este e o unico lugar que ela precisa mexer.
LIMIAR_DE_DESAMBIGUACAO = Decimal("0.6")
```

- [ ] **Step 4: Criar `desambiguacao.py`**

```python
"""As decisoes do TEC-135, isoladas de banco, modelo e entrega.

Duas funcoes puras. O turno faz I/O; o que ele decide, decide aqui.
"""

from datetime import datetime
from decimal import Decimal

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao


def deve_desambiguar(confianca: Decimal, desambiguado_em: datetime | None) -> bool:
    """Se este turno deve perguntar em vez de responder.

    Duas condicoes, e as duas importam. A confianca abaixo do limiar diz que o
    palpite nao e confiavel; o marcador vazio diz que este episodio de
    ambiguidade ainda nao gastou a sua pergunta. Com o marcador preenchido o
    agente segue com `INDEFINIDA` -- o ticket e explicito em que ambiguidade
    persistente nao vira insistencia.
    """
    return confianca < LIMIAR_DE_DESAMBIGUACAO and desambiguado_em is None


def intencao_efetiva(intencao: Intencao, confianca: Decimal) -> Intencao:
    """A intencao que se pode usar para rotear, dado o quanto ela e confiavel.

    `conversation_intent` guarda o que o classificador devolveu, sem edicao --
    e desse par (palpite, confianca) que a TEC-210 precisa para medir o limiar.
    Quem consome nao quer o palpite cru: abaixo do limiar, "COMPRA com 0,45" e
    operacionalmente `INDEFINIDA`, e e por aqui que o TEC-136 e o TEC-137 leem.
    """
    if confianca < LIMIAR_DE_DESAMBIGUACAO:
        return Intencao.INDEFINIDA
    return intencao
```

- [ ] **Step 5: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/unit/test_desambiguacao.py -q
```
Expected: 7 passed.

- [ ] **Step 6: Gates e commit**

```bash
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
git add src/mobia/domain/agente/schemas.py src/mobia/domain/agente/desambiguacao.py tests/unit/test_desambiguacao.py
git commit -m "feat(TEC-135): limiar de confianca sai do comentario e vira decisao testavel"
```

---

## Task 2: A coluna, a migração e o repositório

**Files:**
- Modify: `src/mobia/domain/agente/models.py`
- Create: `alembic/versions/0007_desambiguacao_de_intencao.py`
- Modify: `src/mobia/domain/agente/repositorio.py`
- Test: `tests/integration/test_repositorio_intencao.py`

**Interfaces:**
- Consumes: `intencao_efetiva` e `LIMIAR_DE_DESAMBIGUACAO` da Task 1. (`deve_desambiguar` é do turno, Task 4 — não aparece aqui.)
- Produces:
  - `ConversationIntent.desambiguado_em: Mapped[datetime | None]`
  - `IntencaoDaConversa.desambiguado_em: datetime | None` e a propriedade `IntencaoDaConversa.efetiva -> Intencao`
  - `marcar_desambiguacao(session, *, channel: str, conversation_key: str, quando: datetime | None = None) -> None`
  - `gravar_intencao(...)` inalterada na assinatura, com a limpeza do marcador embutida

- [ ] **Step 1: Escrever os testes que vão falhar**

Acrescentar ao fim de `tests/integration/test_repositorio_intencao.py` (o arquivo já tem o helper `gravar`, `CANAL` e `CONVERSA`):

```python
async def test_marcador_comeca_vazio(session) -> None:
    """Primeira ambiguidade de uma conversa nova tem de poder perguntar."""
    await gravar(session, Intencao.COMPRA, "0.45")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is None


async def test_marcar_desambiguacao_persiste(session) -> None:
    await gravar(session, Intencao.COMPRA, "0.45")

    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is not None


async def test_confianca_baixa_preserva_o_marcador(session) -> None:
    """O episodio de ambiguidade continua aberto -- a pergunta ja foi gasta."""
    await gravar(session, Intencao.COMPRA, "0.45")
    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    await gravar(session, Intencao.ALUGUEL, "0.50")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is not None, "ambiguidade que persiste nao devolve a pergunta"


async def test_confianca_no_limiar_limpa_o_marcador(session) -> None:
    """Uma classificacao confiante encerra o episodio e abre outro.

    E o limiar exato que faz isso, nao um valor folgado: a mesma borda dos dois
    lados da regra.
    """
    await gravar(session, Intencao.COMPRA, "0.45")
    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    await gravar(session, Intencao.COMPRA, "0.60")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is None


async def test_efetiva_esconde_o_palpite_de_baixa_confianca(session) -> None:
    """A coluna guarda COMPRA; quem roteia enxerga INDEFINIDA."""
    await gravar(session, Intencao.COMPRA, "0.45")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.COMPRA, "a tabela registra o classificador sem edicao"
    assert lida.efetiva is Intencao.INDEFINIDA


async def test_efetiva_devolve_a_intencao_quando_ha_confianca(session) -> None:
    await gravar(session, Intencao.ALUGUEL, "0.91")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.efetiva is Intencao.ALUGUEL
```

E acrescentar `marcar_desambiguacao` ao import no topo do arquivo:

```python
from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/integration/test_repositorio_intencao.py -q
```
Expected: FAIL na coleta — `ImportError: cannot import name 'marcar_desambiguacao'`.

- [ ] **Step 3: Acrescentar a coluna ao modelo**

Em `src/mobia/domain/agente/models.py`, dentro de `ConversationIntent`, depois de `modelo` e antes de `updated_at`:

```python
    # NULL = nenhum episodio de ambiguidade em aberto. Preenchido = a pergunta
    # de desambiguacao ja foi feita e entregue neste episodio, e nao se
    # pergunta de novo. Uma classificacao com confianca >=
    # LIMIAR_DE_DESAMBIGUACAO limpa o marcador -- e a evidencia de que a
    # ambiguidade anterior foi resolvida.
    #
    # Timestamp e nao booleano porque ocupa o mesmo espaco e responde "quando"
    # numa investigacao, igual ao `updated_at` logo abaixo.
    desambiguado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

E acrescentar uma advertência ao comentário da coluna `intencao`, logo acima dela:

```python
    # O palpite cru do classificador, mesmo quando a confianca nao o sustenta.
    # **Nao roteie por esta coluna**: use `IntencaoDaConversa.efetiva`, que
    # devolve INDEFINIDA abaixo do limiar. O valor cru fica aqui porque e dele
    # que a TEC-210 precisa para calibrar o limiar.
    intencao: Mapped[str] = mapped_column(String(20), nullable=False)
```

- [ ] **Step 4: Escrever a migração 0007**

Criar `alembic/versions/0007_desambiguacao_de_intencao.py`:

```python
"""marcador de desambiguacao na intencao da conversa

TEC-135. NULL = nenhum episodio de ambiguidade em aberto.

Nullable e sem backfill de proposito: uma conversa que ja existe e que nunca
desambiguou tem exatamente a semantica de NULL, entao o default correto para
todas as linhas antigas ja e o que o add_column deixa.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_intent",
        sa.Column("desambiguado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_intent", "desambiguado_em")
```

- [ ] **Step 5: Estender o repositório**

Em `src/mobia/domain/agente/repositorio.py`, ajustar os imports do topo:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.desambiguacao import intencao_efetiva
from mobia.domain.agente.models import ConversationIntent
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
```

Trocar o dataclass e a leitura:

```python
@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str
    desambiguado_em: datetime | None

    @property
    def efetiva(self) -> Intencao:
        """A intencao que se pode usar para rotear. **Leia por aqui.**

        `intencao` e o palpite cru, que abaixo do limiar nao sustenta decisao
        nenhuma. Ver `intencao_efetiva`.
        """
        return intencao_efetiva(self.intencao, self.confianca)


async def ler_intencao(
    session: AsyncSession, channel: str, conversation_key: str
) -> IntencaoDaConversa | None:
    linha = await session.get(ConversationIntent, (channel, conversation_key))
    if linha is None:
        return None
    return IntencaoDaConversa(
        intencao=Intencao(linha.intencao),
        confianca=linha.confianca,
        modelo=linha.modelo,
        desambiguado_em=linha.desambiguado_em,
    )
```

Em `gravar_intencao`, incluir o marcador nos valores do INSERT e limpá-lo no UPDATE só quando a confiança sustenta a classificação. O corpo passa a ser:

```python
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": str(intencao),
        "confianca": confianca,
        "modelo": modelo,
        # Linha nova comeca sem episodio em aberto: a primeira ambiguidade de
        # uma conversa tem de poder perguntar.
        "desambiguado_em": None,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)

    atualizacoes = {
        chave: statement.excluded[chave]
        for chave in ("intencao", "confianca", "modelo", "updated_at")
    }
    if confianca >= LIMIAR_DE_DESAMBIGUACAO:
        # Classificacao confiante encerra o episodio de ambiguidade: o proximo
        # trecho vago da conversa tem direito a uma pergunta nova.
        atualizacoes["desambiguado_em"] = None
    # Abaixo do limiar o marcador **nao** entra no set_: a ambiguidade e a
    # mesma, e a pergunta dela ja foi gasta.

    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_=atualizacoes,
        )
    )
```

E acrescentar a função nova ao fim do arquivo:

```python
async def marcar_desambiguacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    quando: datetime | None = None,
) -> None:
    """Registra que a pergunta de desambiguacao ja foi feita. **Nao commita.**

    Chamada **depois** da entrega confirmada, nunca antes: o marcador afirma
    "eu ja perguntei", e isso so e verdade se a pergunta chegou. Escrito antes,
    um 5xx da Meta queimaria a unica chance de desambiguar -- o sweeper
    reprocessa, encontra o marcador, e o lead fica em INDEFINIDA sem ninguem
    ter perguntado nada.

    A linha sempre existe neste ponto: `gravar_intencao` rodou e commitou mais
    cedo no mesmo turno.
    """
    await session.execute(
        update(ConversationIntent)
        .where(
            ConversationIntent.channel == channel,
            ConversationIntent.conversation_key == conversation_key,
        )
        .values(desambiguado_em=quando or datetime.now(UTC))
    )
```

- [ ] **Step 6: Aplicar a migração e rodar os testes**

```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest tests/integration/test_repositorio_intencao.py -q
```
Expected: 10 passed (os 4 que já existiam mais os 6 novos).

- [ ] **Step 7: Provar reversibilidade e ausência de drift**

```bash
.venv/Scripts/python -m alembic downgrade 0006
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic check
```
Expected: sem erro, e `No new upgrade operations detected.`

> Se `downgrade` falhar com `TooManyColumnsError: tables can have at most 1600 columns`, o problema é o banco de dev local, não a migração: ciclos repetidos de downgrade/upgrade da 0004 acumulam slots de coluna derrubada em `messages`, e o Postgres nunca os reaproveita. O conserto é recriar o banco (`docker exec mobia-postgres-1 dropdb -U mobia mobia && createdb -U mobia mobia`, seguido de `alembic upgrade head`).

- [ ] **Step 8: Gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
git add src/mobia/domain/agente/models.py src/mobia/domain/agente/repositorio.py alembic/versions/0007_desambiguacao_de_intencao.py tests/integration/test_repositorio_intencao.py
git commit -m "feat(TEC-135): marcador de episodio de ambiguidade na intencao da conversa"
```

---

## Task 3: A segunda chamada ao modelo

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py`
- Modify: `src/mobia/domain/agente/classificador.py`
- Test: `tests/unit/test_classificador.py`

**Interfaces:**
- Consumes: `ContextoMontado` e `montar_prompt` de `mobia.domain.context.montagem`; `RespostaInvalida` do próprio módulo.
- Produces:
  - `PerguntaDeDesambiguacao(texto: str, modelo: str, tokens_in: int, tokens_out: int, latency_ms: int)` (frozen dataclass, em `schemas.py`)
  - `SISTEMA_DA_DESAMBIGUACAO: str`, `MAX_TOKENS_DA_PERGUNTA: int`
  - `ClassificadorPort.desambiguar(contexto: ContextoMontado) -> PerguntaDeDesambiguacao`
  - `ClassificadorAnthropic.desambiguar` com a mesma assinatura

- [ ] **Step 1: Escrever os testes que vão falhar**

Acrescentar ao fim de `tests/unit/test_classificador.py`. O arquivo já tem `_contexto`, `_resposta_falsa`, `_ClienteFalso`, `_instalar_cliente_falso` e as sentinelas — reuse todos. Primeiro, um helper novo logo abaixo de `_instalar_cliente_falso`, porque estes testes precisam inspecionar os argumentos da chamada:

```python
def _instalar_e_capturar(
    monkeypatch: pytest.MonkeyPatch, resposta: SimpleNamespace
) -> _ClienteFalso:
    """Como `_instalar_cliente_falso`, mas devolve o dublê.

    Os testes da desambiguacao asseguram o **formato da requisicao** (sem
    schema estrito, com teto de tokens curto), entao precisam do `AsyncMock`
    para ler `call_args`.
    """
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)
    return cliente
```

E os testes:

```python
PERGUNTA = "O que voce esta buscando agora nesse momento?"


async def test_desambiguar_devolve_a_pergunta_e_a_telemetria(monkeypatch) -> None:
    _instalar_cliente_falso(monkeypatch, _resposta_falsa(texto=f"  {PERGUNTA}  "))

    pergunta = await ClassificadorAnthropic().desambiguar(_contexto())

    assert pergunta.texto == PERGUNTA, "espacos das pontas nao vao para o lead"
    assert pergunta.tokens_in == 4000
    assert pergunta.tokens_out == 200
    assert pergunta.latency_ms >= 0


async def test_desambiguar_nao_manda_schema_estrito(monkeypatch) -> None:
    """A saida e uma frase. Nao ha campo para validar, entao nao ha schema.

    O schema do `classificar` existe porque intencao e confianca sao regra de
    negocio; aqui ele so custaria tokens e uma chance a mais de 400.
    """
    cliente = _instalar_e_capturar(monkeypatch, _resposta_falsa(texto=PERGUNTA))

    await ClassificadorAnthropic().desambiguar(_contexto())

    kwargs = cliente.messages.create.call_args.kwargs
    assert "output_config" not in kwargs
    assert kwargs["max_tokens"] == MAX_TOKENS_DA_PERGUNTA
    assert kwargs["system"] is SISTEMA_DA_DESAMBIGUACAO


def test_desambiguar_pede_uma_pergunta_aberta() -> None:
    """O prompt e a unica coisa que segura a regra "sem menu numerado".

    Nada no codigo verifica o texto devolvido -- ver a secao de lacunas do
    spec. Se esta instrucao sumir do system prompt, some a regra inteira.
    """
    assert "menu" in SISTEMA_DA_DESAMBIGUACAO.lower()
    assert "uma" in SISTEMA_DA_DESAMBIGUACAO.lower()


async def test_desambiguar_recusa_parada_anormal(monkeypatch) -> None:
    """`max_tokens` corta a pergunta no meio; meia pergunta nao vai ao lead."""
    _instalar_cliente_falso(
        monkeypatch, _resposta_falsa(texto=PERGUNTA, stop_reason="max_tokens")
    )

    with pytest.raises(RespostaInvalida):
        await ClassificadorAnthropic().desambiguar(_contexto())


async def test_desambiguar_recusa_pergunta_vazia(monkeypatch) -> None:
    _instalar_cliente_falso(monkeypatch, _resposta_falsa(texto="   "))

    with pytest.raises(RespostaInvalida):
        await ClassificadorAnthropic().desambiguar(_contexto())


async def test_desambiguar_nao_loga_a_pergunta_nem_o_prompt(monkeypatch, caplog) -> None:
    """Mesma regra do `classificar`: so numeros e id de modelo."""
    _instalar_cliente_falso(
        monkeypatch, _resposta_falsa(texto=f"{TEXTO_DA_RESPOSTA} qual e a sua duvida?")
    )

    with caplog.at_level(logging.INFO):
        await ClassificadorAnthropic().desambiguar(_contexto())

    assert "SENTINELA-RESPOSTA" not in caplog.text
    assert "SENTINELA-SISTEMA" not in caplog.text
    assert "SENTINELA-RESUMO" not in caplog.text
    assert "agente.desambiguacao_gerada" in caplog.text
```

Acrescentar ao import do módulo sob teste, no topo do arquivo:

```python
from mobia.domain.agente.classificador import (
    MAX_TOKENS_DA_PERGUNTA,
    SCHEMA_DA_RESPOSTA,
    SISTEMA_DA_DESAMBIGUACAO,
    ClassificadorAnthropic,
    RespostaInvalida,
)
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/unit/test_classificador.py -q
```
Expected: FAIL na coleta — `ImportError: cannot import name 'MAX_TOKENS_DA_PERGUNTA'`.

- [ ] **Step 3: Acrescentar o dataclass em `schemas.py`**

Ao fim do arquivo, depois de `RespostaDoAgente`:

```python
@dataclass(frozen=True)
class PerguntaDeDesambiguacao:
    """O que a segunda chamada devolve quando o lead foi vago demais.

    Nao tem `intencao` nem `confianca` de proposito: esta chamada nao
    classifica nada. Quem classificou foi a primeira, e o resultado dela ja
    esta gravado quando esta acontece.

    Os campos de telemetria repetem os de `RespostaDoAgente` porque o turno
    trata os dois do mesmo jeito na hora de gravar a fala do agente.
    """

    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
```

- [ ] **Step 4: Escrever o prompt e o método**

Em `src/mobia/domain/agente/classificador.py`, acrescentar depois de `SISTEMA_DO_AGENTE`:

```python
MAX_TOKENS_DA_PERGUNTA = 300

SISTEMA_DA_DESAMBIGUACAO = (
    "Voce e o assistente virtual de uma imobiliaria brasileira. A ultima "
    "mensagem do lead nao deixou claro o que ele quer, e voce nao pode "
    "adivinhar.\n\n"
    "Escreva uma unica pergunta, aberta, em portugues do Brasil e em tom de "
    "conversa, que ajude o lead a explicar o que procura. Nao ofereca menu de "
    "opcoes numeradas. Nao assuma nenhuma intencao. Nao faca mais de uma "
    "pergunta. Devolva apenas o texto da pergunta, sem aspas e sem comentario."
)
```

Acrescentar o método ao Protocol:

```python
class ClassificadorPort(Protocol):
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente: ...
    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao: ...
```

E o método à implementação, ao fim de `ClassificadorAnthropic`:

```python
    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao:
        """A segunda chamada do turno ambiguo: uma pergunta, sem schema.

        Recebe o mesmo contexto da primeira -- o prefixo esta quente no cache
        -- e troca so o system prompt. Sem `output_config`: a saida e uma
        frase, nao ha campo para validar, e o compilador de schema do servidor
        e uma chance a mais de 400 num caminho que ja e o de excecao.
        """
        settings = get_settings()
        comeco = time.monotonic()
        resposta = await get_client().messages.create(
            model=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_PERGUNTA,
            system=SISTEMA_DA_DESAMBIGUACAO,
            messages=[{"role": "user", "content": montar_prompt(contexto, omitir_sistema=True)}],
        )
        latency_ms = int((time.monotonic() - comeco) * 1000)

        # Mesmo criterio do `classificar`, e aqui `max_tokens` e um risco real:
        # o teto e curto de proposito, e meia pergunta e pior que nenhuma.
        if resposta.stop_reason != "end_turn":
            raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        if not texto:
            raise RespostaInvalida("pergunta veio vazia")

        # So numeros e id de modelo -- a pergunta vai para o lead, nao para o log.
        log.info(
            "agente.desambiguacao_gerada",
            modelo=settings.modelo_agente,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=latency_ms,
            custo_usd=str(
                custo_em_dolar(
                    settings.modelo_agente,
                    resposta.usage.input_tokens,
                    resposta.usage.output_tokens,
                )
            ),
        )
        return PerguntaDeDesambiguacao(
            texto=texto,
            modelo=settings.modelo_agente,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=latency_ms,
        )
```

E acrescentar `PerguntaDeDesambiguacao` ao import de `schemas` no topo do módulo:

```python
from mobia.domain.agente.schemas import Intencao, PerguntaDeDesambiguacao, RespostaDoAgente
```

- [ ] **Step 5: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/unit/test_classificador.py -q
```
Expected: todos passam (os que já existiam mais os 6 novos).

- [ ] **Step 6: Gates e commit**

```bash
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
git add src/mobia/domain/agente/schemas.py src/mobia/domain/agente/classificador.py tests/unit/test_classificador.py
git commit -m "feat(TEC-135): segunda chamada devolve uma pergunta aberta, sem schema"
```

---

## Task 4: O ramo no turno

É a task que liga tudo. Note a ordem: a intenção é gravada antes da entrega, o marcador depois.

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_turno.py`

**Interfaces:**
- Consumes: `deve_desambiguar` (Task 1); `ler_intencao`, `marcar_desambiguacao`, `IntencaoDaConversa.desambiguado_em` (Task 2); `ClassificadorPort.desambiguar` e `PerguntaDeDesambiguacao` (Task 3).
- Produces: `SUBAGENTE_CLASSIFICADOR = "classificador"` e `SUBAGENTE_DESAMBIGUADOR = "desambiguador"`; `ResultadoDoTurno` **inalterado** — desambiguar continua sendo `"respondido"`, porque do ponto de vista do worker o turno respondeu ao lead.

- [ ] **Step 1: Ensinar o dublê a desambiguar**

Em `tests/conftest.py`, substituir `ClassificadorFake` por:

```python
class ClassificadorFake:
    """Duble do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(
        self,
        intencao: "Intencao" = None,  # type: ignore[assignment]
        confianca: Decimal = Decimal("0.91"),
        erro: Exception | None = None,
        pergunta: str = "Me conta um pouco mais sobre o que voce procura?",
        erro_da_desambiguacao: Exception | None = None,
    ) -> None:
        from mobia.domain.agente.schemas import Intencao as _Intencao

        self.intencao = intencao or _Intencao.COMPRA
        self.confianca = confianca
        self.erro = erro
        self.pergunta = pergunta
        self.erro_da_desambiguacao = erro_da_desambiguacao
        self.chamadas = 0
        self.desambiguacoes = 0

    async def classificar(self, contexto):
        from mobia.domain.agente.schemas import RespostaDoAgente

        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return RespostaDoAgente(
            intencao=self.intencao,
            confianca=self.confianca,
            resposta="Ola! Em qual regiao voce procura?",
            modelo="claude-opus-5",
            tokens_in=1200,
            tokens_out=180,
            latency_ms=900,
        )

    async def desambiguar(self, contexto):
        from mobia.domain.agente.schemas import PerguntaDeDesambiguacao

        self.desambiguacoes += 1
        if self.erro_da_desambiguacao is not None:
            raise self.erro_da_desambiguacao
        return PerguntaDeDesambiguacao(
            texto=self.pergunta,
            modelo="claude-opus-5",
            tokens_in=1100,
            tokens_out=40,
            latency_ms=600,
        )
```

- [ ] **Step 2: Escrever os testes que vão falhar**

Acrescentar ao fim de `tests/integration/test_turno.py`. Precisa de um import novo no topo — a linha do `turno` ganha a constante do subagente; a do `repositorio` já existe e não muda:

```python
from mobia.domain.agente.turno import KIND_DA_RESPOSTA, SUBAGENTE_DESAMBIGUADOR, executar_turno
```

```python
BAIXA = Decimal("0.45")


async def test_confianca_baixa_entrega_a_pergunta_no_lugar_da_resposta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 1: abaixo do limiar o lead recebe pergunta, nao suposicao.

    A resposta da primeira chamada foi escrita assumindo COMPRA -- e ela que
    nao pode chegar ao lead.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert classificador.desambiguacoes == 1
    assert outbound.entregues == [classificador.pergunta]
    assert "Em qual regiao" not in outbound.entregues[0], "a resposta que assumia COMPRA nao sai"


async def test_confianca_no_limiar_exato_responde_sem_perguntar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 2: 0,6 nao desambigua, e nem chega a pagar a segunda chamada."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.60"))
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 0
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_o_palpite_cru_e_gravado_e_a_efetiva_e_indefinida(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A tabela nao edita o classificador; quem roteia le pela `efetiva`."""
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA
    assert gravada.confianca == BAIXA
    assert gravada.efetiva is Intencao.INDEFINIDA


async def test_ambiguidade_persistente_nao_repete_a_pergunta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 4: a resposta do lead continuou vaga, e o agente nao insiste.

    O segundo turno entrega a resposta normal da primeira chamada -- que e a
    "qualificacao generica" possivel hoje, ja que trilha nenhuma existe antes
    da TEC-137. Ver a secao de escopo do spec.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1, "uma pergunta por episodio, nao por turno"
    assert outbound.entregues[1] == "Ola! Em qual regiao voce procura?"


async def test_classificacao_confiante_abre_um_episodio_novo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Uma conversa longa que fica clara e volta a ficar vaga pode perguntar de novo.

    E o "por episodio" da regra: a classificacao confiante no meio e a
    evidencia de que a ambiguidade anterior foi resolvida.
    """
    vago = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    claro = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.91"))
    outbound = outbound_fake()

    await rodar_turno(session, vago, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, claro, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, vago, outbound, resumidor_fake(), contador_fake())

    assert vago.desambiguacoes == 2
    assert claro.desambiguacoes == 0


async def test_entrega_expirada_nao_queima_a_pergunta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O marcador afirma "eu ja perguntei" -- e nada chegou ao lead.

    Marca-lo aqui deixaria a conversa em INDEFINIDA para sempre sem ninguem
    ter perguntado nada.
    """
    outbound = outbound_fake(EnvioForaDaJanela("131047"))

    resultado = await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "expirado"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_reentrega_suprimida_nao_marca_o_episodio(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """`send()` devolveu False: `_deliver` nunca foi chamado nesta passada.

    Mesmo criterio da fala fantasma -- sem confirmacao de entrega, nada que
    afirme "ja perguntei" pode ser gravado.
    """
    from conftest import _entrada_do_lead

    linha = await _entrada_do_lead(session)
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=linha.id, kind=KIND_DA_RESPOSTA))
    await session.commit()

    resultado = await executar_turno(
        get_sessionmaker(),
        message=linha,
        classificador=classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
    )

    assert resultado == "reentrega_suprimida"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_a_fala_gravada_e_a_pergunta_com_a_telemetria_da_segunda_chamada(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O que o lead recebeu foi a pergunta -- e e ela que entra na linha do tempo.

    Os tokens sao os da chamada 2. Os da chamada 1, cuja resposta foi
    descartada, ficam so no log `agente.turno_gerado`: o custo do turno
    ambiguo esta inteiro nos logs, repartido em duas linhas, e so uma delas
    vira linha no banco. Ver a secao de telemetria do spec.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = (
        await session.execute(
            sql(
                "SELECT m.id, t.subagent, t.tokens_out FROM messages m"
                " JOIN message_telemetry t ON t.message_id = m.id"
                " WHERE m.direction = 'OUTBOUND'"
            )
        )
    ).one()
    assert linha.subagent == SUBAGENTE_DESAMBIGUADOR
    assert linha.tokens_out == 40, "telemetria da chamada 2, nao da 1"


async def test_falha_da_segunda_chamada_derruba_o_turno(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Nenhuma politica nova: propaga, o job marca FAILED, o sweeper retenta.

    E como o marcador so e escrito depois da entrega, a retentativa desambigua
    de verdade em vez de encontrar o marcador e desistir.
    """
    classificador = classificador_fake(
        Intencao.COMPRA,
        confianca=BAIXA,
        erro_da_desambiguacao=RespostaInvalida("stop_reason='max_tokens'"),
    )
    outbound = outbound_fake()

    with pytest.raises(RespostaInvalida):
        await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert outbound.entregues == [], "nada foi entregue"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA, "a classificacao aconteceu e fica registrada"
    assert gravada.desambiguado_em is None, "a proxima passada ainda pode perguntar"
```

Este último teste precisa de mais um import no topo do arquivo:

```python
from mobia.domain.agente.classificador import RespostaInvalida
```

Acrescentar `from decimal import Decimal` ao topo se ainda não estiver lá (já está — o arquivo usa `Decimal("0.91")`).

- [ ] **Step 3: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/integration/test_turno.py -q
```
Expected: FAIL na coleta — `ImportError: cannot import name 'SUBAGENTE_DESAMBIGUADOR'`.

- [ ] **Step 4: Implementar o ramo**

Em `src/mobia/domain/agente/turno.py`, ajustar os imports:

```python
from mobia.domain.agente.classificador import ClassificadorPort
from mobia.domain.agente.desambiguacao import deve_desambiguar
from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
```

Acrescentar as constantes ao lado de `KIND_DA_RESPOSTA`:

```python
SUBAGENTE_CLASSIFICADOR = "classificador"
SUBAGENTE_DESAMBIGUADOR = "desambiguador"
```

Trocar o bloco que grava a intenção por:

```python
    # Gravada antes da entrega de proposito: a classificacao e sobre a mensagem
    # do lead, que existe, e nao sobre a resposta que pode nao sair.
    #
    # A leitura vem **antes** da gravacao no mesmo bloco: `gravar_intencao`
    # limpa o marcador quando a confianca sustenta a classificacao, entao
    # depois dela nao da mais para saber se este episodio ja tinha perguntado.
    async with session_factory() as session:
        anterior = await ler_intencao(session, message.channel, message.conversation_key)
        await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
        )
        await session.commit()

    desambiguando = deve_desambiguar(
        gerada.confianca, anterior.desambiguado_em if anterior else None
    )
    if desambiguando:
        # A resposta da chamada 1 foi escrita assumindo um palpite que a
        # confianca nao sustenta. Ela e descartada -- paga e nao entregue.
        pergunta = await classificador.desambiguar(contexto)
        texto, telemetria, subagente = pergunta.texto, pergunta, SUBAGENTE_DESAMBIGUADOR
    else:
        texto, telemetria, subagente = gerada.resposta, gerada, SUBAGENTE_CLASSIFICADOR
```

No `outbound.send`, trocar `"texto": gerada.resposta` por `"texto": texto`.

Depois do bloco `if not entregue:` e **antes** do `MessageRecorder`:

```python
    if desambiguando:
        # Depois da entrega confirmada, nunca antes: ver `marcar_desambiguacao`.
        # A ordem entre esta gravacao e a da fala do agente nao e carregada --
        # as duas sao pos-entrega, e a guarda do outbound suprime qualquer
        # reentrega se o turno cair entre elas.
        async with session_factory() as session:
            await marcar_desambiguacao(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
            await session.commit()
        log.info(
            "turno.desambiguou",
            channel=message.channel,
            message_id=str(message.id),
        )
```

E no `record_agent_message`, trocar os cinco campos que vinham de `gerada`:

```python
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=texto,
        model=telemetria.modelo,
        subagent=subagente,
        tokens_in=telemetria.tokens_in,
        tokens_out=telemetria.tokens_out,
        latency_ms=telemetria.latency_ms,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
```

Por fim, acrescentar ao docstring de `executar_turno`, depois do parágrafo que já existe:

```
    Abaixo de `LIMIAR_DE_DESAMBIGUACAO` e com o episodio ainda limpo, a
    resposta da chamada 1 e descartada e uma segunda chamada produz uma
    pergunta aberta. O marcador que impede a repeticao so e gravado depois da
    entrega confirmada -- marca-lo antes queimaria a unica chance de perguntar
    num 5xx da Meta.
```

- [ ] **Step 5: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/integration/test_turno.py -q
```
Expected: todos passam (os 6 que já existiam mais os 9 novos).

- [ ] **Step 6: Suíte inteira, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
git add src/mobia/domain/agente/turno.py tests/conftest.py tests/integration/test_turno.py
git commit -m "feat(TEC-135): turno pergunta em vez de supor quando a confianca nao sustenta"
```

---

## Task 5: Critérios de aceite e README

**Files:**
- Create: `tests/features/test_desambiguacao_de_intencao.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: tudo das tasks 1–4. Nada novo é produzido.

- [ ] **Step 1: Escrever os quatro cenários do ticket**

Criar `tests/features/test_desambiguacao_de_intencao.py`:

```python
"""Criterios de aceite do TEC-135 como testes executaveis.

O que estes testes provam e **o ramo**: abaixo do limiar o turno chama o
desambiguador e entrega o texto dele; no limiar exato, nao; uma vez por
episodio; e uma classificacao confiante reabre o direito de perguntar.

O que eles **nao** provam e a qualidade da pergunta. O classificador e sempre
um duble e o texto e argumento de construtor, entao nada aqui garante que o
modelo real escreva uma pergunta aberta em vez de um menu numerado. Isso e
medicao de qualidade de saida, e e a TEC-210 que a tem no escopo -- ver a
secao de lacunas do spec.

Dois cenarios do ticket falam em "seguir pela trilha de aluguel" e "conduzir
pela qualificacao generica". Trilha nenhuma existe antes da TEC-137, e a
escolha da pergunta de qualificacao e a TEC-145. O observavel aqui e a
intencao persistida e a volta da resposta normal.
"""

from decimal import Decimal

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"
VAGA = Decimal("0.45")


async def test_mensagem_vaga_gera_pergunta_aberta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 1: confianca 0,45 vira pergunta, e nenhuma intencao e assumida."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=VAGA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert outbound.entregues == [classificador.pergunta]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.INDEFINIDA, "nenhuma das duas intencoes foi assumida"


async def test_confianca_exatamente_no_limite_nao_desambigua(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 2: 0,6 segue com a intencao classificada, sem perguntar."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.60"))
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 0
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.COMPRA


async def test_resposta_a_desambiguacao_reclassifica_a_intencao(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 3: o lead respondeu "e para alugar mesmo".

    O turno seguinte classifica com confianca alta, a intencao efetiva passa a
    ALUGUEL e o agente volta a responder em vez de perguntar. "Seguir pela
    trilha de aluguel" e a TEC-137.
    """
    outbound = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=VAGA),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    depois = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.88"))
    await rodar_turno(session, depois, outbound, resumidor_fake(), contador_fake())

    assert depois.desambiguacoes == 0

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.ALUGUEL


async def test_ambiguidade_persistente_nao_vira_insistencia(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 4: a resposta continuou ambigua, e o agente nao repete a pergunta."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=VAGA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1
    assert outbound.entregues[1] != classificador.pergunta

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.INDEFINIDA
```

- [ ] **Step 2: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/features/test_desambiguacao_de_intencao.py -q
```
Expected: 4 passed. (Aqui não há passo de "confirmar que falha": a implementação inteira já existe nas tasks 1–4, e estes testes são a tradução dos critérios de aceite, não o motor do design.)

- [ ] **Step 3: Documentar no README**

Acrescentar depois da seção `## TEC-134 — Classificação de intenção e o primeiro turno` e das garantias dela:

```markdown
## TEC-135 — Desambiguação abaixo de 0,6

| Cenário Gherkin | Teste |
|---|---|
| Mensagem vaga gera pergunta aberta | `tests/features/test_desambiguacao_de_intencao.py::test_mensagem_vaga_gera_pergunta_aberta` |
| Confiança exatamente no limite não desambigua | `tests/features/test_desambiguacao_de_intencao.py::test_confianca_exatamente_no_limite_nao_desambigua` |
| Resposta à desambiguação reclassifica a intenção | `tests/features/test_desambiguacao_de_intencao.py::test_resposta_a_desambiguacao_reclassifica_a_intencao` |
| Ambiguidade persistente não vira insistência | `tests/features/test_desambiguacao_de_intencao.py::test_ambiguidade_persistente_nao_vira_insistencia` |

### Garantias

- Abaixo de `LIMIAR_DE_DESAMBIGUACAO` (0,6) o lead recebe **uma** pergunta aberta
  em vez de uma resposta que assume a intenção. O limiar é fechado por cima:
  exatamente 0,6 segue sem perguntar.
- Uma pergunta por **episódio** de ambiguidade, não por conversa. Uma
  classificação com confiança no limiar ou acima limpa o marcador e abre um
  episódio novo.
- `desambiguado_em` só é gravado depois de a entrega ser confirmada. Falha de
  entrega — expirada, recusada ou reentrega suprimida — não queima a pergunta.
- `conversation_intent.intencao` continua guardando o palpite cru do
  classificador. **Não roteie por essa coluna**: `IntencaoDaConversa.efetiva`
  devolve `INDEFINIDA` abaixo do limiar, e é por ela que TEC-136 e TEC-137 leem.
- O turno ambíguo custa **duas** chamadas ao modelo: a resposta da primeira é
  descartada. A fala gravada leva a telemetria da segunda; o custo da primeira
  fica só no log `agente.turno_gerado`.

### Lacunas conhecidas

- Nada no código garante que a segunda chamada devolva uma pergunta aberta em vez
  de um menu numerado. A regra vive inteira no `SISTEMA_DA_DESAMBIGUACAO`, e
  medir a saída é a TEC-210.
- O limiar de 0,6 continua não calibrado. Ele saiu de um comentário e virou
  constante nomeada — que é o pré-requisito para a TEC-210 mexer nele.
```

- [ ] **Step 4: Rodar a suíte inteira e os gates**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
.venv/Scripts/python -m alembic downgrade 0006 && .venv/Scripts/python -m alembic upgrade head
```
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add tests/features/test_desambiguacao_de_intencao.py README.md
git commit -m "test(TEC-135): criterios de aceite como testes executaveis"
```

---

## Verificação final

- [ ] `.venv/Scripts/python -m pytest -q` — verde
- [ ] `.venv/Scripts/python -m pytest -m perf` — o p95 do webhook do TEC-122 não pode ter mudado: a segunda chamada roda no worker, não no caminho da requisição. O teste é bimodal nesta máquina — repita algumas vezes.
- [ ] `alembic downgrade 0006 && alembic upgrade head` — sem erro
- [ ] `alembic check` — `No new upgrade operations detected`
- [ ] `ruff check`, `ruff format --check`, `mypy` — sem erro
- [ ] Nenhum teste chama a API do modelo: `git grep -n "desambiguar" tests | grep -v Fake` não pode encontrar cliente real
- [ ] `git grep -n "pergunta\|texto" src | grep "log\."` — nada loga a pergunta enviada ao lead
- [ ] O turno com confiança alta continua fazendo **uma** chamada: `test_confianca_no_limiar_exato_responde_sem_perguntar` prova isso via `desambiguacoes == 0`
