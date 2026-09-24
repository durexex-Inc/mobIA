# TEC-129 — Histórico unificado entre WhatsApp e web: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o turno do WhatsApp passa a conhecer o que a mesma pessoa disse no widget web, vinculado pelo telefone que ela digitou no site — e o turno web continua sem enxergar nada do WhatsApp.

**Architecture:** uma regex pura extrai e normaliza o telefone da fala web; a rota do widget grava o vínculo `('web', sessão) → telefone` numa tabela nova. No começo de todo turno WhatsApp, a absorção preenche os critérios vazios de `lead_qualification` com os das sessões vinculadas e devolve os pares delas, que `montar_contexto` inclui na janela de literais. Nada escreve no par web.

**Tech Stack:** Python 3.13, FastAPI (WebSocket), SQLAlchemy 2 async + asyncpg, Alembic, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-129-historico-unificado-design.md` — leia antes de começar; as decisões D1–D5 são referidas por número abaixo.

## Global Constraints

- **Assimetria (D1):** nenhum código desta card escreve em par `('web', …)` fora do vínculo, e nenhum turno web lê estado ou falas de outro par.
- Canal: literais `CANAL_WEB` e `CANAL_WHATSAPP` de `mobia.domain.messages.canais` — nunca string solta.
- Telefone canônico: só dígitos, com `55`; celular 13 dígitos, fixo 12. Só número brasileiro.
- Comentários e docstrings em `src/` e `tests/`: português **sem** acento. Prosa em `docs/`: com acento.
- Commits: `tipo(TEC-129): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gates antes de todo commit, os três, sem pipe (um `| tail` engole o exit code):
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Testes de integração e features exigem `docker compose` de pé. Unitários não.
- Não use `grep -rn` no shell sobre `tests/` — pendura. Use a ferramenta Grep.
- O prompt do sistema e o schema do classificador **não mudam** nesta card: se `-k margem_do_orcamento` mudar de resultado, algo errado entrou.

## Review Focus

1. **Web → WhatsApp com resumo já dobrado:** se o WhatsApp já tem resumo cuja marca é posterior às falas web vinculadas, essas falas ficam fora da janela (a marca é uma tupla global `(created_at, id)`). Esperado: os critérios chegam mesmo assim, pela qualificação. Coberto pelo teste `test_criterios_chegam_mesmo_com_falas_web_antes_da_marca` na Task 5.
2. **Campo recusado no site e respondido no WhatsApp:** a união de `campos_recusados` não pode reintroduzir um campo que o WhatsApp já tem preenchido. Coberto por `test_recusa_web_nao_volta_sobre_campo_preenchido` na Task 4.
3. **Falha ao gravar o vínculo:** a mensagem já foi persistida e confirmada; um erro no vínculo não pode fechar o socket nem perder o `recebido`. Coberto por `test_falha_no_vinculo_nao_derruba_a_conversa` na Task 3.
4. **`wa_id` que não é brasileiro:** `normalizar` devolve `None`, e o turno WhatsApp segue exatamente como hoje, sem consulta a mais que falhe. Coberto por `test_wa_id_estrangeiro_nao_absorve` na Task 4.
5. **Reenvio da mesma mensagem web** (mesmo `id`, a UNIQUE descarta): `ingest` devolve lista vazia e o vínculo não é tentado de novo. Coberto por `test_reenvio_nao_tenta_vincular_de_novo` na Task 3.

---

## Mapa de arquivos

| arquivo | responsabilidade |
| --- | --- |
| Create `src/mobia/domain/identidade/__init__.py` | pacote |
| Create `src/mobia/domain/identidade/telefone.py` | regex e normalização, puras (D2) |
| Create `src/mobia/domain/identidade/models.py` | `VinculoDeSessao` (D3) |
| Create `src/mobia/domain/identidade/repositorio.py` | `vincular_sessao`, `sessoes_vinculadas` |
| Create `src/mobia/domain/identidade/absorcao.py` | `absorver_sessoes_vinculadas` (D4) |
| Create `alembic/versions/0041_vinculos_de_sessao.py` | a tabela |
| Modify `src/mobia/api/routes/widget.py` (`_ler_do_lead`, ~l.353-400) | grava o vínculo depois do `ingest` |
| Modify `src/mobia/domain/context/janela.py` (`literais_apos`) | aceita `pares_vinculados` |
| Modify `src/mobia/domain/context/montagem.py` (`montar_contexto`, ~l.552-605) | repassa `pares_vinculados` |
| Modify `src/mobia/domain/agente/turno.py` (~l.1739, antes de `montar_contexto`) | chama a absorção no turno WhatsApp |
| Modify `src/mobia/domain/messages/models.py:39-44` | o comentário que atribui à TEC-129 "um id proprio de conversa" deixa de ser verdade |
| Modify `tests/conftest.py` (`TABELAS`) | `vinculos_de_sessao` |
| Modify `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (abaixo da RN-01.1 E-01) | Emenda E-02 |
| Tests | `tests/unit/test_telefone.py`, `tests/integration/test_vinculos_de_sessao.py`, `tests/integration/test_vinculo_pelo_widget.py`, `tests/integration/test_absorcao_de_sessoes.py`, `tests/integration/test_janela_com_pares_vinculados.py`, `tests/features/test_historico_unificado.py` |

**Antes de criar os arquivos de teste**, confira com a ferramenta Glob que nenhum basename acima já existe em outro diretório de `tests/` (`**/test_telefone.py` etc.). Basename repetido entre `unit` e `integration` aborta a coleta da suíte inteira.

---

### Task 1: extrair e normalizar telefone

**Files:**
- Create: `src/mobia/domain/identidade/__init__.py` (vazio)
- Create: `src/mobia/domain/identidade/telefone.py`
- Test: `tests/unit/test_telefone.py`

**Interfaces:**
- Produces: `normalizar(bruto: str) -> str | None` e `extrair_telefone(texto: str) -> str | None`, ambas em `mobia.domain.identidade.telefone`.

- [ ] **Step 1: Escrever os testes que falham**

```python
"""Regex e normalizacao de telefone brasileiro. TEC-129, D2."""

import pytest

from mobia.domain.identidade.telefone import extrair_telefone, normalizar


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("meu whats e (48) 99999-0000", "5548999990000"),
        ("+55 48 99999-0000", "5548999990000"),
        ("+5548999990000", "5548999990000"),
        ("48999990000", "5548999990000"),
        ("48 9 9999 0000", None),  # nove solto nao e mascara que a regex aceita
        ("liga no 48.99999.0000", "5548999990000"),
        # celular sem o 9: ganha o 9
        ("(48) 9999-0000", "5548999990000"),
        # fixo: fica com 12
        ("fixo (48) 3222-1234", "554832221234"),
    ],
)
def test_extrai_as_mascaras_comuns(texto: str, esperado: str | None) -> None:
    assert extrair_telefone(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "o CEP e 88010-400",
        "ate R$ 1.250.000",
        "orcamento de 900000",
        "meu CPF e 123.456.789-09",
        "visita dia 24/09/2026",
        "DDD invalido (20) 99999-0000",
        "tres quartos e duas vagas",
    ],
)
def test_nao_casa_o_que_nao_e_telefone(texto: str) -> None:
    assert extrair_telefone(texto) is None


def test_cpf_cru_com_9_na_terceira_posicao_e_falso_positivo_conhecido() -> None:
    # Onze digitos com DDD valido e 9 na terceira posicao sao indistinguiveis
    # de um celular. A spec aceita o falso positivo (D2); este teste existe
    # para que ninguem o "conserte" sem reler a decisao.
    assert extrair_telefone("12945678909") == "5512945678909"


def test_dois_telefones_diferentes_nao_devolvem_nenhum() -> None:
    assert extrair_telefone("(48) 99999-0000 ou (48) 98888-1111") is None


def test_o_mesmo_telefone_duas_vezes_devolve_ele() -> None:
    assert extrair_telefone("(48) 99999-0000, repito: 48999990000") == "5548999990000"


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        # wa_id da Meta com o 9 e sem ele: a mesma forma canonica
        ("5548999990000", "5548999990000"),
        ("554899990000", "5548999990000"),
        ("554832221234", "554832221234"),
        # estrangeiro, curto, lixo
        ("14155550123", None),
        ("12345", None),
        ("", None),
    ],
)
def test_normaliza_o_wa_id(bruto: str, esperado: str | None) -> None:
    assert normalizar(bruto) == esperado
```

Atenção ao caso `"14155550123"`: são 11 dígitos com DDD `14` válido e assinante `155550123` começando por 1 — não é celular (não começa por 9), então `None`. É o que faz um número dos EUA não virar telefone de Bauru.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_telefone.py --tb=short`
Expected: FAIL na coleta, `ModuleNotFoundError: No module named 'mobia.domain.identidade'`.

- [ ] **Step 3: Implementar**

```python
"""Telefone brasileiro: achar na fala do lead e levar a uma forma so. TEC-129, D2.

**Deterministico de proposito.** A alternativa era um campo `telefone` na
extracao do classificador, e ela custaria prompt e schema -- que o teste da
margem do orcamento vigia -- em troca de uma extracao que muda de uma chamada
para outra. Um vinculo de identidade que muda de uma chamada para outra nao e
vinculo.

**A forma canonica e a do `wa_id` da Meta, com o 9**: so digitos, com o `55`.
Celular tem 13 digitos, fixo tem 12. A Meta entrega parte dos celulares
brasileiros SEM o 9 -- `554899990000` --, e e por isso que `normalizar`
insere o 9 em celular de oito digitos: e a mesma regra que faz o `wa_id` e o
numero digitado no site se encontrarem.

So numero brasileiro. Estrangeiro nao e reconhecido, e isso e limite declarado
da spec, nao descuido.
"""

import re

# DDDs em uso no Brasil. Sem esta lista, qualquer sequencia de dez digitos
# comecando por 20, 23, 25... viraria telefone.
_DDDS = frozenset(
    {
        "11", "12", "13", "14", "15", "16", "17", "18", "19",
        "21", "22", "24", "27", "28",
        "31", "32", "33", "34", "35", "37", "38",
        "41", "42", "43", "44", "45", "46", "47", "48", "49",
        "51", "53", "54", "55",
        "61", "62", "63", "64", "65", "66", "67", "68", "69",
        "71", "73", "74", "75", "77", "79",
        "81", "82", "83", "84", "85", "86", "87", "88", "89",
        "91", "92", "93", "94", "95", "96", "97", "98", "99",
    }
)  # fmt: skip

# `(?<!\d)` e `(?!\d)` impedem casar um pedaco de uma corrida maior de digitos
# -- sem eles, os onze primeiros digitos de um numero de protocolo virariam
# telefone. O separador entre os blocos e UM de espaco, ponto ou hifen, ou
# nenhum; virgula nao entra, porque e o separador decimal do preco.
_CANDIDATO = re.compile(
    r"(?<!\d)(?:\+?55[\s.-]?)?\(?\d{2}\)?[\s.-]?\d{4,5}[\s.-]?\d{4}(?!\d)"
)


def normalizar(bruto: str) -> str | None:
    """A forma canonica do telefone, ou `None` se nao for telefone brasileiro."""
    digitos = re.sub(r"\D", "", bruto)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        nacional = digitos[2:]
    elif len(digitos) in (10, 11):
        nacional = digitos
    else:
        return None

    ddd, assinante = nacional[:2], nacional[2:]
    if ddd not in _DDDS:
        return None
    if len(assinante) == 9:
        # Nove digitos so existem em celular, e celular comeca por 9.
        if not assinante.startswith("9"):
            return None
    elif assinante[0] in "6789":
        # Celular de oito digitos: o `wa_id` sem o 9, ou um numero anotado
        # antes de 2016. Os dois ganham o 9.
        assinante = "9" + assinante
    elif assinante[0] not in "2345":
        # Fixo comeca de 2 a 5; o resto nao e numero em uso.
        return None
    return "55" + ddd + assinante


def extrair_telefone(texto: str) -> str | None:
    """O telefone da fala, se houver exatamente um.

    **Dois telefones diferentes devolvem `None`.** Nao ha como saber qual e o da
    pessoa -- "o meu e X, o da minha esposa e Y" --, e vincular o errado poe o
    que ela disse no contexto do WhatsApp de outra pessoa. O mesmo numero
    repetido conta como um.
    """
    encontrados = {
        canonico
        for candidato in _CANDIDATO.finditer(texto)
        if (canonico := normalizar(candidato.group())) is not None
    }
    if len(encontrados) != 1:
        return None
    return encontrados.pop()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_telefone.py --tb=short`
Expected: PASS. Se o caso `"48 9 9999 0000"` falhar porque a regex casou, **não afrouxe o teste**: esse formato não passa pela regex (são dois separadores seguidos), e a spec não pede que passe. Se casar, a regex tem um separador sobrando.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/identidade tests/unit/test_telefone.py
git commit -m "feat(TEC-129): o telefone brasileiro digitado no site tem uma forma canonica, a mesma do wa_id

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: a tabela de vínculos e o repositório

**Files:**
- Create: `src/mobia/domain/identidade/models.py`
- Create: `src/mobia/domain/identidade/repositorio.py`
- Create: `alembic/versions/0041_vinculos_de_sessao.py`
- Modify: `tests/conftest.py` (`TABELAS`, ~l.143-200)
- Test: `tests/integration/test_vinculos_de_sessao.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces:
  - `VinculoDeSessao` (tabela `vinculos_de_sessao`) em `mobia.domain.identidade.models`.
  - `async def vincular_sessao(session_factory: async_sessionmaker[AsyncSession], *, channel: str, conversation_key: str, telefone: str, message_id: uuid.UUID) -> bool` — `True` se criou; `False` se a sessão já tinha vínculo.
  - `async def sessoes_vinculadas(session: AsyncSession, telefone: str) -> list[tuple[str, str]]` — pares `(channel, conversation_key)`, do vínculo mais antigo para o mais novo.

- [ ] **Step 1: Escrever os testes que falham**

Os testes criam a mensagem de evidência direto no banco, porque o vínculo exige FK para `messages.id`. Use o mesmo padrão de inserção de `Message` que `tests/integration/test_migrations.py` usa (colunas obrigatórias: `channel`, `conversation_key`, `role`, `direction`, `content_type`, `status`).

```python
"""O vinculo sessao web -> telefone. TEC-129, D3."""

import uuid

from sqlalchemy import select

from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.identidade.repositorio import sessoes_vinculadas, vincular_sessao
from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker

TELEFONE = "5548999990000"


async def _mensagem_web(session, sessao: str) -> uuid.UUID:
    linha = Message(
        channel=CANAL_WEB,
        conversation_key=sessao,
        sender_external_id=sessao,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.RECEIVED,
    )
    session.add(linha)
    await session.commit()
    return linha.id


async def test_cria_o_vinculo(session) -> None:
    sessao = str(uuid.uuid4())
    evidencia = await _mensagem_web(session, sessao)

    criou = await vincular_sessao(
        get_sessionmaker(),
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone=TELEFONE,
        message_id=evidencia,
    )

    assert criou is True
    linha = (await session.execute(select(VinculoDeSessao))).scalar_one()
    assert (linha.channel, linha.conversation_key, linha.telefone) == (CANAL_WEB, sessao, TELEFONE)
    assert linha.message_id == evidencia


async def test_o_primeiro_telefone_vence(session) -> None:
    sessao = str(uuid.uuid4())
    primeira = await _mensagem_web(session, sessao)
    segunda = await _mensagem_web(session, sessao)
    fabrica = get_sessionmaker()

    await vincular_sessao(
        fabrica, channel=CANAL_WEB, conversation_key=sessao, telefone=TELEFONE, message_id=primeira
    )
    criou = await vincular_sessao(
        fabrica,
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone="5548988881111",
        message_id=segunda,
    )

    assert criou is False
    assert (await session.execute(select(VinculoDeSessao.telefone))).scalar_one() == TELEFONE


async def test_duas_sessoes_para_o_mesmo_telefone(session) -> None:
    fabrica = get_sessionmaker()
    sessoes = [str(uuid.uuid4()), str(uuid.uuid4())]
    for sessao in sessoes:
        await vincular_sessao(
            fabrica,
            channel=CANAL_WEB,
            conversation_key=sessao,
            telefone=TELEFONE,
            message_id=await _mensagem_web(session, sessao),
        )

    assert await sessoes_vinculadas(session, TELEFONE) == [(CANAL_WEB, s) for s in sessoes]


async def test_telefone_sem_vinculo_devolve_vazio(session) -> None:
    assert await sessoes_vinculadas(session, TELEFONE) == []
```

Confira em `tests/conftest.py` o nome da fixture de sessão usada pelos testes de integração (`session`, como em `tests/features/test_atendimento_pelo_widget_web.py`) e se `banco_limpo` é autouse. Se não for, peça-a como os vizinhos pedem.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_vinculos_de_sessao.py --tb=short`
Expected: FAIL na coleta, `ModuleNotFoundError: No module named 'mobia.domain.identidade.models'`.

- [ ] **Step 3: O modelo**

```python
"""A sessao web vinculada a um telefone. TEC-129, D3.

**Uma linha por sessao, e nao por telefone.** A mesma pessoa em dois
navegadores sao duas sessoes apontando para o mesmo numero; o que a PK proibe
e a mesma sessao apontar para dois numeros. O primeiro telefone vale, e um
segundo diferente e ignorado -- ver `vincular_sessao`.

**So a sessao web tem linha aqui.** O lado WhatsApp nao precisa: o
`conversation_key` dele ja e o numero, e `normalizar` o leva a mesma forma
canonica deste `telefone`.

**O vinculo e so de ida, e isso e a decisao central da card (D1).** Quem le
esta tabela e o turno do WhatsApp, para absorver o que a sessao disse. O turno
web nunca a consulta: a sessao e anonima e nada verifica que o numero e de quem
o digitou, entao ler o WhatsApp a partir daqui entregaria a conversa de uma
pessoa a qualquer um que soubesse o telefone dela.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class VinculoDeSessao(Base):
    __tablename__ = "vinculos_de_sessao"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Forma canonica de `domain/identidade/telefone.py`: so digitos, com o 55.
    # Em claro, como o `conversation_key` do WhatsApp ja e.
    telefone: Mapped[str] = mapped_column(String(16), nullable=False)

    # A fala que trouxe o numero. CASCADE porque o vinculo e derivado do
    # conteudo dela: apagada a mensagem (retencao, direito do titular), nao
    # sobra evidencia que sustente o vinculo.
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_vinculos_de_sessao_telefone", "telefone"),)
```

- [ ] **Step 4: A migration**

```python
"""a sessao web vinculada ao telefone que o visitante digitou

TEC-129, D3. Tabela nova e vazia: nao ha backfill porque nenhum telefone foi
extraido de fala nenhuma antes desta card, e reprocessar o historico web
vincularia sessoes a numeros sem que a pessoa estivesse ali para isso.

O indice em `telefone` e o caminho da unica leitura: o turno do WhatsApp
perguntando quais sessoes apontam para o seu numero.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vinculos_de_sessao",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("telefone", sa.String(16), nullable=False),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_vinculos_de_sessao_telefone", "vinculos_de_sessao", ["telefone"])


def downgrade() -> None:
    op.drop_index("ix_vinculos_de_sessao_telefone", table_name="vinculos_de_sessao")
    op.drop_table("vinculos_de_sessao")
```

- [ ] **Step 5: O repositório**

```python
"""Gravar e ler o vinculo sessao web -> telefone. TEC-129, D3."""

import uuid
from typing import cast

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.identidade.models import VinculoDeSessao


async def vincular_sessao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    telefone: str,
    message_id: uuid.UUID,
) -> bool:
    """Grava o vinculo se a sessao ainda nao tem um. Devolve se gravou.

    `ON CONFLICT DO NOTHING` e nao upsert: o primeiro telefone vale. Trocar o
    numero de uma sessao ja vinculada moveria o que ela disse de um lead para
    outro no meio da conversa, e o segundo numero tem menos chance de ser o da
    pessoa que o primeiro -- "o meu e X; anota tambem o do meu marido, Y".
    """
    async with session_factory() as session:
        resultado = cast(
            CursorResult[object],
            await session.execute(
                pg_insert(VinculoDeSessao)
                .values(
                    channel=channel,
                    conversation_key=conversation_key,
                    telefone=telefone,
                    message_id=message_id,
                )
                .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
            ),
        )
        await session.commit()
    return resultado.rowcount == 1


async def sessoes_vinculadas(session: AsyncSession, telefone: str) -> list[tuple[str, str]]:
    """Os pares das sessoes que apontam para este telefone, do mais antigo ao mais novo."""
    linhas = await session.execute(
        select(VinculoDeSessao.channel, VinculoDeSessao.conversation_key)
        .where(VinculoDeSessao.telefone == telefone)
        .order_by(VinculoDeSessao.criado_em, VinculoDeSessao.conversation_key)
    )
    return [(channel, chave) for channel, chave in linhas.all()]
```

Se o mypy reclamar do `cast(CursorResult[object], …)`, copie a forma exata que `src/mobia/domain/messages/service.py` usa para o mesmo `rowcount` — ela já passa no gate.

- [ ] **Step 6: `TABELAS`**

Em `tests/conftest.py`, acrescente ao fim da tupla `TABELAS`:

```python
    # TEC-129. Mutavel, e com PK na sessao: sem o truncate, o vinculo gravado
    # por um teste faz o `vincular_sessao` do proximo devolver False sobre a
    # mesma sessao -- e a absorcao de um teste encontraria as sessoes do outro.
    "vinculos_de_sessao",
```

- [ ] **Step 7: Migrar e rodar**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_vinculos_de_sessao.py tests/integration/test_migrations.py --tb=short
```
Expected: PASS. Se a primeira tentativa do `alembic` falhar com `[WinError 64]`, espere alguns segundos e repita — ver CLAUDE.md, "O banco demora mais que o healthcheck diz".

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/identidade alembic/versions/0041_vinculos_de_sessao.py tests/conftest.py tests/integration/test_vinculos_de_sessao.py
git commit -m "feat(TEC-129): a sessao web guarda o primeiro telefone que o visitante digitou

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: a rota do widget grava o vínculo

**Files:**
- Modify: `src/mobia/api/routes/widget.py` — `_ler_do_lead` (~l.312-410), no bloco `try: await service.ingest(...)`.
- Test: `tests/integration/test_vinculo_pelo_widget.py`

**Interfaces:**
- Consumes: `extrair_telefone` (Task 1); `vincular_sessao` (Task 2).
- Produces: nada que outra task chame; o efeito é a linha em `vinculos_de_sessao`.

- [ ] **Step 1: Escrever os testes que falham**

Os helpers `_abrir` e `_linha_da_sessao` são os de `tests/features/test_atendimento_pelo_widget_web.py`. Copie-os para este arquivo em vez de importar: `tests/` não é pacote.

```python
"""A rota do widget grava o vinculo quando a fala traz um telefone. TEC-129, D3."""

from typing import Any

import pytest
from sqlalchemy import select

from mobia.domain.identidade.models import VinculoDeSessao


async def _abrir(ws_cliente, sessao: str | None = None) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    return ws, (await ws.receber())["sessao"]


async def _vinculos(session) -> list[VinculoDeSessao]:
    return list((await session.execute(select(VinculoDeSessao))).scalars())


async def test_fala_com_telefone_vincula_a_sessao(ws_cliente, session) -> None:
    ws, sessao = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "meu whats e (48) 99999-0000"})
        assert (await ws.receber())["tipo"] == "recebido"
    finally:
        await ws.__aexit__()

    [vinculo] = await _vinculos(session)
    assert (vinculo.conversation_key, vinculo.telefone) == (sessao, "5548999990000")


async def test_fala_sem_telefone_nao_vincula(ws_cliente, session) -> None:
    ws, _ = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "quero dois quartos"})
        await ws.receber()
    finally:
        await ws.__aexit__()

    assert await _vinculos(session) == []


async def test_reenvio_nao_tenta_vincular_de_novo(ws_cliente, session, monkeypatch) -> None:
    import mobia.api.routes.widget as rota

    chamadas: list[str] = []
    original = rota.vincular_sessao

    async def contando(*args: Any, **kwargs: Any) -> bool:
        chamadas.append(kwargs["conversation_key"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(rota, "vincular_sessao", contando)
    ws, _ = await _abrir(ws_cliente)
    try:
        for _ in range(2):
            await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "(48) 99999-0000"})
            assert (await ws.receber())["tipo"] == "recebido"
    finally:
        await ws.__aexit__()

    # A UNIQUE descartou o reenvio, `ingest` devolveu vazio, e o vinculo nao
    # foi tentado de novo.
    assert len(chamadas) == 1


async def test_falha_no_vinculo_nao_derruba_a_conversa(ws_cliente, session, monkeypatch) -> None:
    import mobia.api.routes.widget as rota

    async def quebrado(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("banco sumiu no meio")

    monkeypatch.setattr(rota, "vincular_sessao", quebrado)
    ws, _ = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "(48) 99999-0000"})
        # A mensagem ja estava persistida: o `recebido` chega, e o socket segue.
        assert (await ws.receber())["tipo"] == "recebido"
        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "e dois quartos"})
        assert (await ws.receber())["tipo"] == "recebido"
    finally:
        await ws.__aexit__()
```

Se `ws.receber()` devolver primeiro um frame do agente em vez do `recebido`, não há worker rodando neste teste, então isso não deve acontecer. Se acontecer, confira como `test_atendimento_pelo_widget_web.py` lida com a ordem.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_vinculo_pelo_widget.py --tb=short`
Expected: `test_fala_com_telefone_vincula_a_sessao` FAIL (nenhum vínculo); os dois com `monkeypatch` FAIL com `AttributeError: ... has no attribute 'vincular_sessao'`.

- [ ] **Step 3: Implementar**

Em `widget.py`, acrescente os imports:

```python
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.identidade.telefone import extrair_telefone
```

No `try:` de `_ler_do_lead`, troque `await service.ingest(` por `gravadas = await service.ingest(`. Logo **depois** do bloco `except` que fecha com `CODIGO_INDISPONIVEL` e **antes** do `await websocket.send_json({"tipo": "recebido", ...})`, acrescente:

```python
        # TEC-129, D3. So quando a linha e NOVA: um reenvio que a UNIQUE
        # descartou volta vazio de `ingest`, e o vinculo da primeira vez ja
        # foi tentado. E so depois do `ingest`, porque o vinculo tem FK para a
        # mensagem que o sustenta.
        telefone = extrair_telefone(texto) if gravadas else None
        if telefone is not None:
            try:
                criou = await vincular_sessao(
                    get_sessionmaker(),
                    channel=CANAL_WEB,
                    conversation_key=sessao,
                    telefone=telefone,
                    message_id=gravadas[0],
                )
            except Exception as exc:
                # A mensagem JA esta persistida, e e ela a promessa desta rota.
                # Fechar o socket aqui faria o cliente reconectar e reenviar um
                # id que a UNIQUE descarta -- e o vinculo nunca mais seria
                # tentado. Perder o vinculo e o custo menor: o WhatsApp dessa
                # pessoa so nao herda o que ela disse no site.
                log.exception(
                    "widget.vinculo_falhou",
                    sessao=sessao,
                    reason=type(exc).__name__,
                    detail=motivo_do_erro_de_banco(exc),
                )
            else:
                if not criou:
                    # Sessao ja vinculada: o primeiro telefone vale. O numero
                    # nao vai no log -- a mascara de PII cobre corridas de
                    # digitos, mas nao ha por que confiar nela para isto.
                    log.info("widget.vinculo_mantido", sessao=sessao)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_vinculo_pelo_widget.py tests/integration/test_widget_handshake.py tests/features/test_atendimento_pelo_widget_web.py --tb=short`
Expected: PASS. Os dois arquivos da TEC-124 entram porque esta task mexe no laço que eles exercitam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/widget.py tests/integration/test_vinculo_pelo_widget.py
git commit -m "feat(TEC-129): a fala web com um telefone vincula a sessao, e a falha do vinculo nao derruba o socket

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: a absorção

**Files:**
- Create: `src/mobia/domain/identidade/absorcao.py`
- Test: `tests/integration/test_absorcao_de_sessoes.py`

**Interfaces:**
- Consumes: `normalizar` (Task 1); `sessoes_vinculadas`, `VinculoDeSessao` (Task 2); `LeadQualification` (`mobia.domain.context.models`).
- Produces: `async def absorver_sessoes_vinculadas(session_factory: async_sessionmaker[AsyncSession], *, conversation_key: str) -> tuple[tuple[str, str], ...]` — grava no par `('whatsapp', conversation_key)` e devolve os pares web vinculados (vazio se não há vínculo ou se o `wa_id` não é brasileiro). A Task 5 passa esse retorno para `montar_contexto`.

- [ ] **Step 1: Escrever os testes que falham**

```python
"""O turno do WhatsApp absorve as sessoes web vinculadas. TEC-129, D4."""

import uuid

from sqlalchemy import select

from mobia.domain.context.models import LeadQualification
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker

WA_ID = "554899990000"  # a Meta entregando sem o 9
TELEFONE = "5548999990000"


async def _sessao_vinculada(session, **criterios) -> str:
    sessao = str(uuid.uuid4())
    evidencia = Message(
        channel=CANAL_WEB,
        conversation_key=sessao,
        sender_external_id=sessao,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.PROCESSED,
    )
    session.add(evidencia)
    if criterios:
        session.add(LeadQualification(channel=CANAL_WEB, conversation_key=sessao, **criterios))
    await session.commit()
    await vincular_sessao(
        get_sessionmaker(),
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone=TELEFONE,
        message_id=evidencia.id,
    )
    return sessao


async def _estado(session, channel: str, chave: str) -> LeadQualification | None:
    session.expire_all()
    return (
        await session.execute(
            select(LeadQualification).where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == chave,
            )
        )
    ).scalar_one_or_none()


async def test_sem_vinculo_nao_faz_nada(session) -> None:
    pares = await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    assert pares == ()
    assert await _estado(session, CANAL_WHATSAPP, WA_ID) is None


async def test_wa_id_estrangeiro_nao_absorve(session) -> None:
    await _sessao_vinculada(session, quartos=2)

    assert await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key="14155550123") == ()


async def test_preenche_o_whatsapp_vazio_e_devolve_os_pares(session) -> None:
    sessao = await _sessao_vinculada(session, quartos=2, regiao="Campeche")

    pares = await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    assert pares == ((CANAL_WEB, sessao),)
    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert estado is not None
    assert (estado.quartos, estado.regiao) == (2, "Campeche")


async def test_o_que_o_whatsapp_ja_sabe_prevalece(session) -> None:
    await _sessao_vinculada(session, quartos=2, regiao="Campeche")
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3))
    await session.commit()

    await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.quartos, estado.regiao) == (3, "Campeche")


async def test_recusas_se_somam(session) -> None:
    await _sessao_vinculada(session, campos_recusados=["faixa_preco"])
    session.add(
        LeadQualification(
            channel=CANAL_WHATSAPP, conversation_key=WA_ID, campos_recusados=["urgencia"]
        )
    )
    await session.commit()

    await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert sorted(estado.campos_recusados) == ["faixa_preco", "urgencia"]


async def test_recusa_web_nao_volta_sobre_campo_preenchido(session) -> None:
    await _sessao_vinculada(session, campos_recusados=["quartos"])
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3))
    await session.commit()

    await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert "quartos" not in (estado.campos_recusados or [])


async def test_nao_grava_no_par_web(session) -> None:
    sessao = await _sessao_vinculada(session, quartos=2)
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, regiao="Centro"))
    await session.commit()

    await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    web = await _estado(session, CANAL_WEB, sessao)
    assert (web.quartos, web.regiao) == (2, None)


async def test_e_idempotente(session) -> None:
    await _sessao_vinculada(session, quartos=2, campos_recusados=["urgencia"])
    fabrica = get_sessionmaker()

    await absorver_sessoes_vinculadas(fabrica, conversation_key=WA_ID)
    await absorver_sessoes_vinculadas(fabrica, conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.quartos, estado.campos_recusados) == (2, ["urgencia"])


async def test_com_duas_sessoes_vale_a_mais_recente(session) -> None:
    await _sessao_vinculada(session, quartos=2)
    await _sessao_vinculada(session, quartos=4)
    # `updated_at` tem `server_default=now()`, e as duas linhas podem empatar na
    # mesma transacao do Postgres. Force a ordem em vez de depender do relogio.
    await session.execute(
        LeadQualification.__table__.update()
        .where(LeadQualification.quartos == 2)
        .values(updated_at=LeadQualification.updated_at - timedelta(hours=1))
    )
    await session.commit()

    await absorver_sessoes_vinculadas(get_sessionmaker(), conversation_key=WA_ID)

    assert (await _estado(session, CANAL_WHATSAPP, WA_ID)).quartos == 4
```

O último teste usa `timedelta`: acrescente `from datetime import timedelta` ao topo do arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_absorcao_de_sessoes.py --tb=short`
Expected: FAIL na coleta, `ModuleNotFoundError: ... absorcao`.

- [ ] **Step 3: Implementar**

```python
"""O turno do WhatsApp herda o que a mesma pessoa disse no site. TEC-129, D4.

**So grava no par do WhatsApp, e isso e a card inteira.** A sessao web e
anonima e nada verifica que o telefone digitado e de quem o digitou (D1): o
que vai do site para o WhatsApp e o que a sessao disse, e nunca o contrario.
Uma absorcao que escrevesse no par web entregaria, no turno web seguinte, a
qualificacao do WhatsApp a quem digitou o numero de outra pessoa.

**O que o WhatsApp ja sabe prevalece.** Preenche so campo vazio: o numero e o
lado autenticado, e o que ele disse diretamente vale mais que o que uma sessao
anonima disse em nome dele.

**O que fica de fora, e por que** -- ver a D4 da spec por extenso:
`recomendacoes` (a linha sem reacao dispara a pergunta de reacao, e a ordem e
o ordinal), `conversation_intent` (confianca, desambiguacao e o contador de
fora de escopo sao do episodio, nao da pessoa), o resumo (um bloco a mais no
prompt a cada turno), score e temperatura (recalculados no proprio turno) e
opt-out, handoff e atendimento humano (uma sessao nao verificada nao silencia
nem escala o numero de outra pessoa).

Idempotente: roda em todo turno, e o segundo passe sobre o mesmo estado nao
muda nada. E isso que cobre a sessao web que continua viva depois de o
WhatsApp comecar.
"""

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.context.models import LeadQualification
from mobia.domain.identidade.repositorio import sessoes_vinculadas
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.messages.canais import CANAL_WHATSAPP

# Os criterios, e so eles. `intencao` entra: e a coluna de qualificacao, e nao
# a linha de `conversation_intent`. O que NAO entra e bookkeeping do turno --
# `perguntados_sem_resposta`, `perguntas_feitas` -- e o que o turno recalcula,
# `temperatura*` e `qualificado_em`.
CAMPOS_ABSORVIDOS: tuple[str, ...] = (
    "intencao",
    "faixa_preco_min_centavos",
    "faixa_preco_max_centavos",
    "regiao",
    "tipo_imovel",
    "quartos",
    "vagas",
    "urgencia",
    "forma_pagamento",
    "tem_imovel_para_vender",
    "ticket_investimento_centavos",
    "retorno_esperado_pct",
    "retorno_esperado_tipo",
    "horizonte",
    "tolerancia_reforma",
    "ja_investe_em_imoveis",
    "perfil_investidor",
)


async def absorver_sessoes_vinculadas(
    session_factory: async_sessionmaker[AsyncSession], *, conversation_key: str
) -> tuple[tuple[str, str], ...]:
    """Preenche o estado do WhatsApp com o das sessoes vinculadas; devolve os pares delas.

    Os pares vao para `montar_contexto`, que os poe na janela de literais. Sem
    vinculo -- ou com um `wa_id` que nao e brasileiro -- devolve `()` e nao
    escreve nada: o turno segue exatamente como antes desta card.
    """
    telefone = normalizar(conversation_key)
    if telefone is None:
        return ()

    async with session_factory() as session:
        pares = await sessoes_vinculadas(session, telefone)
        if not pares:
            return ()

        origens = list(
            await session.scalars(
                select(LeadQualification)
                .where(
                    tuple_(LeadQualification.channel, LeadQualification.conversation_key).in_(
                        pares
                    )
                )
                # A mais recente primeiro: e ela que vence um campo que duas
                # sessoes preencheram diferente.
                .order_by(LeadQualification.updated_at.desc())
            )
        )
        if origens:
            await _preencher(session, conversation_key, origens)
            await session.commit()
    return tuple(pares)


async def _preencher(
    session: AsyncSession, conversation_key: str, origens: list[LeadQualification]
) -> None:
    # Garante a linha antes do `FOR UPDATE`: sem ela nao ha o que travar, e dois
    # turnos simultaneos do mesmo numero criariam a linha os dois.
    await session.execute(
        pg_insert(LeadQualification)
        .values(channel=CANAL_WHATSAPP, conversation_key=conversation_key)
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    destino = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == CANAL_WHATSAPP,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
        )
    ).scalar_one()

    for campo in CAMPOS_ABSORVIDOS:
        if getattr(destino, campo) is not None:
            continue
        for origem in origens:
            valor = getattr(origem, campo)
            if valor is not None:
                setattr(destino, campo, valor)
                break

    # Uniao, menos o que o destino ja tem preenchido: a recusa no site sobre um
    # campo que o WhatsApp respondeu depois nao pode fazer o agente tratar como
    # recusado o que a pessoa ja disse.
    recusados = set(destino.campos_recusados or [])
    for origem in origens:
        recusados |= set(origem.campos_recusados or [])
    recusados = {campo for campo in recusados if getattr(destino, campo, None) is None}
    if recusados != set(destino.campos_recusados or []):
        destino.campos_recusados = sorted(recusados)
```

Atenção ao filtro de `recusados`: os nomes em `campos_recusados` são os do vocabulário de perguntas (ver `_nome_contavel` em `domain/context/repositorio.py`). Se algum deles não for nome de coluna (por exemplo `faixa_preco`, que cobre duas colunas), `getattr(destino, campo, None)` devolve `None` e a recusa fica, o que é o comportamento certo. **Leia `_nome_contavel` e `campos_a_recusar` antes de implementar.** Se houver um mapa nome → colunas ali, use-o em vez do `getattr`, e acrescente um teste com `faixa_preco` recusado e `faixa_preco_max_centavos` preenchido.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_absorcao_de_sessoes.py --tb=short`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/identidade/absorcao.py tests/integration/test_absorcao_de_sessoes.py
git commit -m "feat(TEC-129): o estado do WhatsApp herda os criterios das sessoes web vinculadas, sem escrever nelas

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: a janela lê os pares vinculados, e o turno WhatsApp chama a absorção

**Files:**
- Modify: `src/mobia/domain/context/janela.py` — `literais_apos`
- Modify: `src/mobia/domain/context/montagem.py` — `montar_contexto` (~l.552-605)
- Modify: `src/mobia/domain/agente/turno.py` — imediatamente antes de `contexto = await montar_contexto(` (~l.1739)
- Test: `tests/integration/test_janela_com_pares_vinculados.py`, `tests/features/test_historico_unificado.py`

**Interfaces:**
- Consumes: `absorver_sessoes_vinculadas` (Task 4); o vínculo pela rota (Task 3).
- Produces:
  - `literais_apos(session, channel, conversation_key, marca, *, pares_vinculados: Sequence[tuple[str, str]] = ()) -> list[Message]`
  - `montar_contexto(..., pares_vinculados: Sequence[tuple[str, str]] = ())`

- [ ] **Step 1: Teste da janela, que falha**

```python
"""A janela de literais le as sessoes vinculadas. TEC-129, D4."""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus

WA_ID = "5548999990000"


def _fala(channel: str, chave: str, quando: datetime, bloqueada: bool = False) -> Message:
    return Message(
        channel=channel,
        conversation_key=chave,
        sender_external_id=chave,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.PROCESSED,
        created_at=quando,
        bloqueada_em=quando if bloqueada else None,
    )


async def test_sem_pares_e_como_antes(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    session.add_all([_fala(CANAL_WHATSAPP, WA_ID, agora), _fala(CANAL_WEB, sessao, agora)])
    await session.commit()

    literais = await literais_apos(session, CANAL_WHATSAPP, WA_ID, None)

    assert [m.channel for m in literais] == [CANAL_WHATSAPP]


async def test_inclui_os_pares_em_ordem_cronologica(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    session.add_all(
        [
            _fala(CANAL_WEB, sessao, agora - timedelta(hours=2)),
            _fala(CANAL_WHATSAPP, WA_ID, agora - timedelta(hours=1)),
            _fala(CANAL_WEB, sessao, agora - timedelta(minutes=30), bloqueada=True),
            _fala(CANAL_WEB, str(uuid.uuid4()), agora),  # outra sessao, sem vinculo
        ]
    )
    await session.commit()

    literais = await literais_apos(
        session, CANAL_WHATSAPP, WA_ID, None, pares_vinculados=[(CANAL_WEB, sessao)]
    )

    # A bloqueada pela moderacao continua fora, venha de que par vier.
    assert [m.channel for m in literais] == [CANAL_WEB, CANAL_WHATSAPP]


async def test_a_marca_vale_para_os_pares(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    antiga = _fala(CANAL_WEB, sessao, agora - timedelta(hours=2))
    marco = _fala(CANAL_WHATSAPP, WA_ID, agora - timedelta(hours=1))
    nova = _fala(CANAL_WEB, sessao, agora)
    session.add_all([antiga, marco, nova])
    await session.commit()

    literais = await literais_apos(
        session,
        CANAL_WHATSAPP,
        WA_ID,
        Marca(created_at=marco.created_at, message_id=marco.id),
        pares_vinculados=[(CANAL_WEB, sessao)],
    )

    assert [m.id for m in literais] == [nova.id]
```

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_janela_com_pares_vinculados.py --tb=short`
Expected: os dois últimos FAIL com `TypeError: ... unexpected keyword argument 'pares_vinculados'`.

- [ ] **Step 2: Implementar em `janela.py`**

Assinatura e primeiras condições de `literais_apos`:

```python
async def literais_apos(
    session: AsyncSession,
    channel: str,
    conversation_key: str,
    marca: Marca | None,
    *,
    pares_vinculados: Sequence[tuple[str, str]] = (),
) -> list[Message]:
    """Tudo o que ainda nao foi dobrado no resumo, em ordem cronologica.

    A comparacao e de tupla e nao de timestamp sozinho: duas mensagens no mesmo
    `created_at` fariam a janela pular uma ou repetir a outra. O par casa com
    `ix_messages_timeline (channel, conversation_key, created_at DESC)`.

    `pares_vinculados` (TEC-129, D4) sao as sessoes web que o turno do WhatsApp
    herdou: as falas delas entram na mesma janela, sob a mesma marca. A marca e
    uma tupla global `(created_at, id)`, e nao por par, entao uma fala web mais
    antiga que o resumo do WhatsApp fica de fora -- o que ela trouxe de
    criterio chega pela qualificacao, que a absorcao ja preencheu. Sem pares, o
    filtro e a igualdade de sempre.
    """
    if pares_vinculados:
        filtro_do_par = tuple_(Message.channel, Message.conversation_key).in_(
            [(channel, conversation_key), *pares_vinculados]
        )
    else:
        filtro_do_par = and_(
            Message.channel == channel, Message.conversation_key == conversation_key
        )
    condicoes = [
        filtro_do_par,
```

Mantenha o resto de `condicoes` (o `bloqueada_em` com o comentário da TEC-236) e o corpo como estão. Imports: `from collections.abc import Sequence` e `and_` no import de `sqlalchemy`.

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_janela_com_pares_vinculados.py tests/integration/test_montagem.py --tb=short`
Expected: PASS.

- [ ] **Step 3: Repassar em `montar_contexto`**

Acrescente o parâmetro depois de `contador: ContadorPort,`:

```python
    # TEC-129, D4: as sessoes web que o turno do WhatsApp herdou. Entram so na
    # janela de literais; o resumo e o estado continuam sendo os do par do
    # turno -- o estado ja chega preenchido pela absorcao.
    pares_vinculados: Sequence[tuple[str, str]] = (),
```

e troque a chamada:

```python
        literais = await literais_apos(
            session,
            channel,
            conversation_key,
            marca_de(resumo_atual),
            pares_vinculados=pares_vinculados,
        )
```

Confira com a ferramenta Grep que `literais_apos` não tem outro chamador em `src/` além de `montagem.py`. Se tiver, deixe-o com o default.

- [ ] **Step 4: Os cenários da card, que falham**

`tests/features/test_historico_unificado.py`. O WhatsApp entra pela ingestão real (`IngestionService` com `channel=CANAL_WHATSAPP`), para exercitar o caminho de produção. Os dubles de `_ctx_do_worker` vêm do arquivo de features da TEC-124; copie `_ctx_do_worker`, `_abrir`, `_linha_da_sessao` e uma porta WhatsApp que **registra** em vez de falhar.

```python
"""Cenarios Gherkin de TEC-129.

Funcionalidade: Historico unificado do lead entre canais

O turno do WhatsApp roda pelo `process_message` de producao, com um
classificador que GUARDA o contexto que recebeu: e o contexto -- o estado e os
literais -- que diz se o agente reperguntaria. Afirmar sobre o texto da
resposta testaria o duble, que responde sempre a mesma coisa.
"""

import uuid
from typing import Any

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao
from mobia.domain.context.models import LeadQualification
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebOutbound
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

TELEFONE_DIGITADO = "(48) 99999-0000"
WA_ID = "5548999990000"


class ClassificadorQueGuarda(ClassificadorFake):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.contextos: list[Any] = []

    async def classificar(self, contexto, *, porta=None):
        self.contextos.append(contexto)
        return await super().classificar(contexto, porta=porta)


class WhatsAppQueRegistra:
    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


def _ctx(redis_pool: Any, classificador: Any, whatsapp: Any) -> dict[str, Any]:
    session_factory = get_sessionmaker()
    return {
        "session_factory": session_factory,
        "outbound": RoteadorPorCanal(
            session_factory,
            {CANAL_WHATSAPP: whatsapp, CANAL_WEB: WebOutbound(session_factory, redis_pool)},
        ),
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }


async def _abrir(ws_cliente, sessao: str | None = None) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    return ws, (await ws.receber())["sessao"]


async def _falar_no_site(
    ws_cliente, redis_pool, textos: list[str], classificador, sessao: str | None = None
) -> str:
    """Abre (ou retoma) uma sessao, diz cada texto e roda o turno de cada um.

    O id de cada fala e um uuid, e nao `m-0`: numa sessao retomada, `m-0`
    colidiria com a primeira fala e a UNIQUE a descartaria.
    """
    retomada = sessao is not None
    ws, sessao = await _abrir(ws_cliente, sessao)
    if retomada:
        # Na retomada o servidor manda o historico logo depois do `ola`
        # (TEC-124, D6), e ele tem de sair da frente antes do `recebido`.
        assert (await ws.receber())["tipo"] == "historico"
    fabrica = get_sessionmaker()
    try:
        for texto in textos:
            await ws.enviar({"tipo": "mensagem", "id": str(uuid.uuid4()), "texto": texto})
            assert (await ws.receber())["tipo"] == "recebido"
            async with fabrica() as sessao_db:
                linha = (
                    await sessao_db.execute(
                        select(Message)
                        .where(Message.conversation_key == sessao, Message.role == MessageRole.LEAD)
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one()
            await process_message(_ctx(redis_pool, classificador, WhatsAppQueRegistra()), str(linha.id))
            await ws.receber()  # a resposta do agente
    finally:
        await ws.__aexit__()
    return sessao


async def _falar_no_whatsapp(redis_pool, texto: str, classificador) -> WhatsAppQueRegistra:
    fabrica = get_sessionmaker()
    [message_id] = await IngestionService(fabrica, redis_pool).ingest(
        [
            ParsedMessage(
                provider_message_id=f"wamid.{uuid.uuid4()}",
                sender_external_id=WA_ID,
                recipient_external_id="phone-number-id",
                content_type=MessageContentType.TEXTO,
                text_body=texto,
                raw_payload={},
            )
        ],
        channel=CANAL_WHATSAPP,
    )
    whatsapp = WhatsAppQueRegistra()
    await process_message(_ctx(redis_pool, classificador, whatsapp), str(message_id))
    return whatsapp


async def test_mesma_pessoa_migra_do_site_para_o_whatsapp(ws_cliente, session, redis_pool) -> None:
    """Cenario: Mesma pessoa migra do site para o WhatsApp."""
    # Dado um lead que informou o telefone no widget web
    no_site = ClassificadorQueGuarda(extracao=Extracao(quartos=2, regiao="Campeche"))
    await _falar_no_site(
        ws_cliente, redis_pool, [f"quero 2 quartos no Campeche, meu whats e {TELEFONE_DIGITADO}"], no_site
    )

    # Quando ele escreve pelo WhatsApp a partir desse mesmo numero
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi, vim do site", no_whatsapp)

    # Entao o atendimento reconhece o historico da conversa web
    [contexto] = no_whatsapp.contextos
    assert CANAL_WEB in {m.channel for m in contexto.literais}
    # E nao repergunta os criterios ja informados: eles estao no estado que o
    # prompt recebe, e o que esta no estado nao e perguntado.
    assert (contexto.estado.quartos, contexto.estado.regiao) == (2, "Campeche")
```

O segundo cenário retoma a mesma sessão, pelo parâmetro `sessao` de `_falar_no_site`:

```python
async def test_sessao_anonima_e_vinculada_ao_informar_o_telefone(ws_cliente, session, redis_pool) -> None:
    """Cenario: Sessao anonima e vinculada ao informar o telefone."""
    # Dada uma sessao web anonima com 6 mensagens trocadas (3 do lead, 3 do agente)
    classificador = ClassificadorQueGuarda()
    sessao = await _falar_no_site(ws_cliente, redis_pool, ["oi", "quero comprar", "dois quartos"], classificador)
    assert (await session.execute(select(VinculoDeSessao))).first() is None

    # Quando o visitante informa o telefone
    await _falar_no_site(ws_cliente, redis_pool, [f"meu numero e {TELEFONE_DIGITADO}"], classificador, sessao=sessao)

    # Entao as 6 mensagens passam a pertencer ao lead desse telefone
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)
    [contexto] = no_whatsapp.contextos
    da_sessao = [m for m in contexto.literais if m.channel == CANAL_WEB]
    # As 6 de antes do telefone, mais as 2 da fala que o trouxe.
    assert len(da_sessao) == 8
    assert {m.conversation_key for m in da_sessao} == {sessao}
```

Confira em `tests/integration/test_widget_handshake.py::test_retomar_devolve_o_historico` que o `historico` é mesmo o frame seguinte ao `ola` na retomada, como `_falar_no_site` assume.

```python
async def test_telefones_diferentes_nao_sao_unificados(ws_cliente, session, redis_pool) -> None:
    """Cenario: Telefones diferentes nao sao unificados."""
    # Dados dois atendimentos com telefones distintos
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        ["quero 4 quartos, meu whats e (48) 98888-1111"],
        ClassificadorQueGuarda(extracao=Extracao(quartos=4)),
    )

    # Quando ambos estao ativos
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)

    # Entao cada um mantem historico e qualificacao proprios
    [contexto] = no_whatsapp.contextos
    assert {m.channel for m in contexto.literais} == {CANAL_WHATSAPP}
    assert contexto.estado is None or contexto.estado.quartos is None


async def test_a_sessao_web_nao_ve_o_whatsapp_de_quem_ela_digitou(ws_cliente, session, redis_pool) -> None:
    """D1: quem digita o telefone de outra pessoa nao recebe nada do WhatsApp dela."""
    session.add(
        LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3, regiao="Lagoa")
    )
    await session.commit()
    await _falar_no_whatsapp(redis_pool, "procuro 3 quartos na Lagoa", ClassificadorQueGuarda())

    no_site = ClassificadorQueGuarda()
    await _falar_no_site(ws_cliente, redis_pool, [f"oi, meu whats e {TELEFONE_DIGITADO}", "o que eu procurava?"], no_site)

    for contexto in no_site.contextos:
        assert {m.channel for m in contexto.literais} == {CANAL_WEB}
        assert contexto.estado is None or contexto.estado.regiao != "Lagoa"


async def test_criterios_chegam_mesmo_com_falas_web_antes_da_marca(ws_cliente, session, redis_pool) -> None:
    """Review Focus 1: a fala web mais antiga que o resumo do WhatsApp fica fora da janela,
    e o criterio chega pela qualificacao."""
    no_site = ClassificadorQueGuarda(extracao=Extracao(quartos=2))
    await _falar_no_site(ws_cliente, redis_pool, [f"2 quartos, whats {TELEFONE_DIGITADO}"], no_site)
    # Um resumo do WhatsApp cuja marca e posterior a tudo o que o site disse.
    ultimo = (
        await session.execute(select(Message).order_by(Message.created_at.desc()).limit(1))
    ).scalar_one()
    async with get_sessionmaker()() as sessao_db:
        assert await gravar_resumo(
            sessao_db,
            channel=CANAL_WHATSAPP,
            conversation_key=WA_ID,
            texto="O lead ja conversou antes.",
            watermark_created_at=ultimo.created_at,
            watermark_message_id=ultimo.id,
            mensagens_cobertas=0,
            modelo="claude-haiku-4-5",
        )
        await sessao_db.commit()

    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)
    [contexto] = no_whatsapp.contextos
    assert contexto.estado.quartos == 2
```

**Nota para o último teste:** acrescente `from mobia.domain.context.repositorio import gravar_resumo` ao topo do arquivo. `gravar_resumo` não commita (a sessão é emprestada), por isso o `commit` explícito. Ele devolve `False` quando a guarda de monotonia recusa a escrita, e o `assert` existe para o teste não passar sobre um resumo que nunca foi gravado. `mensagens_cobertas=0` é aceitável aqui: o que o teste precisa é a marca, e não a contagem.

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_historico_unificado.py --tb=short`
Expected: os cenários 1 e 2 e o teste da marca FAIL (sem literais web e sem estado no WhatsApp). Os testes do cenário 3 e do vazamento podem já passar, e devem continuar passando.

- [ ] **Step 5: O turno chama a absorção**

Em `turno.py`, imports:

```python
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
```

(`CANAL_WHATSAPP` já deve estar importado de `mobia.domain.messages.canais`; confira.) Imediatamente antes de `try:\n        contexto = await montar_contexto(`:

```python
    # TEC-129, D4. So no WhatsApp, que e o lado autenticado: a Meta garante o
    # numero, o site nao garante nada (D1). O turno web NUNCA passa por aqui --
    # se passasse, quem digitasse o telefone de outra pessoa conversaria com um
    # agente que conhece a qualificacao dela. Roda antes de `montar_contexto`
    # porque e la que o estado e lido: preenchido aqui, ele ja chega completo.
    pares_vinculados: tuple[tuple[str, str], ...] = ()
    if message.channel == CANAL_WHATSAPP:
        pares_vinculados = await absorver_sessoes_vinculadas(
            session_factory, conversation_key=message.conversation_key
        )
        if pares_vinculados:
            log.info(
                "turno.sessoes_absorvidas",
                channel=message.channel,
                message_id=str(message.id),
                sessoes=len(pares_vinculados),
            )
```

e na chamada acrescente `pares_vinculados=pares_vinculados,` depois de `contador=contador,`.

**Falha na absorção derruba o turno?** Não deveria: é um enriquecimento. Envolva a chamada em `try/except Exception` com `log.exception("turno.absorcao_falhou", ...)` e siga com `()`. Acrescente o teste em `test_historico_unificado.py`:

```python
async def test_absorcao_quebrada_nao_derruba_o_turno(session, redis_pool, monkeypatch) -> None:
    import mobia.domain.agente.turno as turno

    async def quebrada(*args: Any, **kwargs: Any) -> tuple[tuple[str, str], ...]:
        raise RuntimeError("vinculos indisponivel")

    monkeypatch.setattr(turno, "absorver_sessoes_vinculadas", quebrada)
    whatsapp = await _falar_no_whatsapp(redis_pool, "oi", ClassificadorQueGuarda())

    assert whatsapp.envios  # o lead recebeu resposta
```

- [ ] **Step 6: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_historico_unificado.py tests/integration/test_janela_com_pares_vinculados.py tests/features/test_atendimento_pelo_widget_web.py tests/features/test_janela_de_contexto.py --tb=short
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```
Expected: PASS nos dois. A margem do orçamento não pode mudar (Global Constraints).

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/janela.py src/mobia/domain/context/montagem.py src/mobia/domain/agente/turno.py tests/integration/test_janela_com_pares_vinculados.py tests/features/test_historico_unificado.py
git commit -m "feat(TEC-129): o turno do WhatsApp conhece o que a mesma pessoa disse no site, e o web continua sem ver o WhatsApp

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: SRS, comentários, suíte, PR e card

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` — abaixo da linha da RN-01.1 E-01 (~l.127)
- Modify: `src/mobia/domain/messages/models.py:39-44`

- [ ] **Step 1: Emenda ao SRS**

Logo abaixo do item `**Emenda E-01 (TEC-124, 24/09/2026):** …`, no mesmo nível de aninhamento:

```markdown
  - **Emenda E-02 (TEC-129, 24/09/2026):** a unificação é **assimétrica**: o atendimento pelo WhatsApp herda o que a mesma pessoa disse no widget web, e o widget não herda nada do WhatsApp. O vínculo nasce quando a visitante digita um telefone no chat — só número brasileiro, reconhecido por regex sobre a fala, sem o agente pedir — e o primeiro telefone de uma sessão é o que vale. O motivo da assimetria é que a sessão web é anônima e nada verifica que o número digitado é de quem o digitou: com a herança nos dois sentidos, quem soubesse o telefone de outra pessoa leria, pela boca do agente, o que ela disse no WhatsApp. O que o WhatsApp herda são os critérios de qualificação e as falas literais; opt-out, handoff, imóveis já apresentados e o resumo da conversa não atravessam.
```

- [ ] **Step 2: O comentário que ficou falso**

Em `src/mobia/domain/messages/models.py`, o parágrafo que termina em "a TEC-129 e o historico multicanal, que e quem daria a esta coluna um id proprio de conversa." Troque a última frase por:

```python
    # concerns diferentes: a TEC-130 encerra por inatividade (e estende aquela
    # entidade, ver a Emenda E-02 da RN-02.3) e a TEC-129 ligou o historico
    # multicanal SEM mexer nesta coluna -- a sessao web e o numero do WhatsApp
    # continuam pares distintos, e `vinculos_de_sessao`
    # (`domain/identidade/models.py`) e quem diz que um aponta para o outro.
```

- [ ] **Step 3: Listagem de comentários**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e `VIZINHO`. Em `turno.py`, os `VIZINHO` em volta da chamada de `montar_contexto` são os que importam: o comentário da TEC-130 logo acima (a fronteira de histórico) continua verdadeiro? Ele fala de `_fronteira_do_silencio` olhando os literais, e agora os literais podem ter falas web — o silêncio entre a última fala web e a primeira do WhatsApp pode disparar a dobra. **Se disparar, isso é comportamento novo e precisa de uma linha no comentário e de uma menção no PR**, não de silêncio.

- [ ] **Step 4: Gates e suíte**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se a suíte voltar com dezenas de `CannotConnectNowError`, é o Postgres em recovery, e não esta branch (CLAUDE.md, "Quando o `-n 8` derruba o Postgres"). Rode por blocos, com `docker compose restart postgres` entre eles:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/features --tb=short -q
```

Guarde o hash e o resultado.

- [ ] **Step 5: Commit, push e PR**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md src/mobia/domain/messages/models.py
git commit -m "docs(TEC-129): a RN-01.1 ganha a E-02, e o comentario de messages para de prometer um id de conversa

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push -u origin feat/tec-129-historico-unificado
gh pr create --base main --title "feat(TEC-129): historico unificado entre WhatsApp e web, so do lado do WhatsApp" --body-file <corpo>
```

O corpo do PR segue o formato do #153: o que passa a ser verdade, o que a revisão mudou, as emendas, a verificação com hash e números, e o que não entrega. Termine com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 6: Card**

Comentário na TEC-129 com as divergências em relação à card, os critérios exercitados e o que ficou só no protocolo, as lacunas de produto (a transcrição do dossiê sem falas web, o funil contando o lead duas vezes, imóveis do site reapresentados no WhatsApp) e a emenda E-02. Depois, mova a card para **Em análise**.
