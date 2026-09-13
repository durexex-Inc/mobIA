# TEC-177 — Notificar o corretor: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Todo handoff, assim que o resumo fica pronto, dispara uma notificação ao corretor de plantão pelos dois canais da RN-16.2 — e, quando nenhum aceita, o handoff fica marcado como pendente de aviso manual.

**Architecture:** O job do resumo, ao terminar, enfileira `notificar_corretor`. Esse job resolve o destinatário em cascata (corretor alocado → plantão mais antigo), monta a mensagem a partir do resumo e do link, e a oferece a cada canal isoladamente. Fora da jornada do corretor, o lead recebe um aviso da janela pelo `OutboundPort`, que traz a guarda de opt-out junto.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, ARQ, pytest.

**Spec:** [`docs/superpowers/specs/2026-09-12-tec-177-notificar-o-corretor-design.md`](../specs/2026-09-12-tec-177-notificar-o-corretor-design.md)

## Global Constraints

- **Esta branch é empilhada** sobre a TEC-175 (PR #90) e a TEC-196 (PR #91), com a colisão de migration já resolvida no merge de base: a cadeia é `0023 → 0024` (resumo) `→ 0025` (corretores). **A migration desta card é a `0026`.**
- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  **`alembic/` está no escopo do formatador.**
- **`ruff`:** `select = ["E","F","I","UP","B"]`, `line-length = 100`.
- **Suíte inteira:** `-n 8 --dist loadfile`, uma vez. **Se dezenas de testes falharem com `relation ... does not exist`, quase nunca é a sua migration** — são os bancos dos workers com o carimbo do alembic adiantado em relação ao DDL, e isso **se repete idêntico na segunda execução**, então nem a regra do "rode de novo" separa o caso. Confirme comparando `SELECT version_num FROM alembic_version` com a existência da tabela, e conserte com `alembic stamp` para trás e `upgrade` de novo, nos oito bancos. Use `docker compose exec -T postgres psql -U mobia -d mobia_gwN` — **não há `psql` no PATH desta máquina.**
- **`ConnectionResetError [WinError 64]`** é ruído desta máquina (~5% dos connects, em rajada): espere e retente.
- **Nenhum canal entrega de verdade.** Os dois adaptadores registram e retornam. Isso é decisão da spec (D4), não uma pendência a "consertar".
- **Mensagens de commit:** português sem acento no assunto, `tipo(TEC-177): ...`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/notificacao/__init__.py` | **Criar.** Vazio. |
| `src/mobia/domain/notificacao/mensagem.py` | **Criar.** Puro: monta assunto e corpo a partir do resumo, do link e da etiqueta. |
| `src/mobia/domain/notificacao/canais.py` | **Criar.** `CanalDeNotificacaoPort`, `EmailRegistrado`, `WhatsAppRegistrado`, `FalhaDeCanal`. |
| `src/mobia/domain/notificacao/destinatario.py` | **Criar.** A cascata corretor alocado → plantão. |
| `src/mobia/domain/notificacao/envio.py` | **Criar.** A orquestração, incluindo o aviso ao lead. |
| `alembic/versions/0026_notificacao_do_handoff.py` | **Criar.** `notificado_em` e `aviso_manual_pendente`. |
| `src/mobia/domain/handoff/models.py` | **Modificar.** As duas colunas. |
| `src/mobia/workers/jobs/notificar.py` | **Criar.** O job ARQ. |
| `src/mobia/workers/jobs/gerar_resumo.py` | **Modificar.** Enfileira a notificação ao terminar. |
| `src/mobia/workers/main.py` | **Modificar.** Registrar o job e os canais no ctx. |

---

### Task 1: A mensagem e os canais

**Files:**
- Create: `src/mobia/domain/notificacao/__init__.py` (vazio), `mensagem.py`, `canais.py`
- Test: `tests/unit/test_notificacao_mensagem.py`, `tests/unit/test_notificacao_canais.py`

**Interfaces:**
- Produces: `montar(*, resumo: str | None, link: str, etiqueta: str, prioridade: str) -> tuple[str, str]` (assunto, corpo); `TEXTO_SEM_RESUMO`; `CanalDeNotificacaoPort` (Protocol com `nome: str` e `async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None`); `FalhaDeCanal(RuntimeError)`; `EmailRegistrado`; `WhatsAppRegistrado`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_notificacao_mensagem.py
from mobia.domain.notificacao.mensagem import TEXTO_SEM_RESUMO, montar

LINK = "https://painel.exemplo/conversas/whatsapp/5511911112222"
RESUMO = "## Quem e o lead\nlead do whatsapp, 12 mensagens"


def test_o_corpo_carrega_o_resumo_e_o_link() -> None:
    _, corpo = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert RESUMO in corpo
    assert LINK in corpo


def test_o_assunto_carrega_etiqueta_e_prioridade() -> None:
    assunto, _ = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="ALTA")

    assert "lead-quente" in assunto
    assert "ALTA" in assunto


def test_sem_resumo_o_corpo_diz_que_faltou_e_mantem_o_link() -> None:
    """D2: silencio seria pior que resumo faltando."""
    _, corpo = montar(resumo=None, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert TEXTO_SEM_RESUMO in corpo
    assert LINK in corpo
    assert "None" not in corpo
```

```python
# tests/unit/test_notificacao_canais.py
import logging

import pytest

from mobia.domain.notificacao.canais import EmailRegistrado, WhatsAppRegistrado

SENTINELA = "SENTINELA-CORPO o lead mora na Rua das Palmeiras"


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_canal_tem_nome_e_nao_levanta(
    canal, caplog: pytest.LogCaptureFixture
) -> None:
    assert canal.nome

    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="lead quente", corpo=SENTINELA)

    assert "notificacao.nao_entregue" in caplog.text


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_log_nunca_carrega_o_corpo(
    canal, caplog: pytest.LogCaptureFixture
) -> None:
    """O corpo carrega o resumo, que e prosa sobre o que o lead escreveu."""
    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="lead quente", corpo=SENTINELA)

    assert SENTINELA not in caplog.text


@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])
async def test_o_log_diz_por_que_nao_entregou(
    canal, caplog: pytest.LogCaptureFixture
) -> None:
    """Sem o motivo, o log vira ruido que ninguem sabe interpretar."""
    with caplog.at_level(logging.INFO):
        await canal.enviar(destino="paulo@x.com", assunto="a", corpo="b")

    assert "motivo" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_notificacao_mensagem.py tests/unit/test_notificacao_canais.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.notificacao'`

- [ ] **Step 3: Write the implementation**

```python
# src/mobia/domain/notificacao/mensagem.py
"""O texto que o corretor recebe. TEC-177, RN-16.2.

Modulo sem I/O, no molde de `handoff/dossie.py` e de `handoff/vocabulario.py`.
"""

# O que entra no lugar do resumo quando ele nao existe. A geracao pode falhar
# -- a D7 da TEC-175 deixa `handoffs.resumo` nulo de proposito nesse caso, e o
# resumo de contingencia e a TEC-176, que nao existe. A notificacao sai mesmo
# assim: a card diz que "o handoff que ninguem ve nao existe", e um corretor
# com aviso magro ainda atende o lead. Ver a D2.
TEXTO_SEM_RESUMO = (
    "O resumo automatico nao pode ser gerado para este lead. "
    "Abra o link abaixo para ler a conversa inteira."
)


def montar(
    *, resumo: str | None, link: str, etiqueta: str, prioridade: str
) -> tuple[str, str]:
    """Devolve (assunto, corpo).

    Tudo keyword-only: `etiqueta` e `prioridade` sao dois `str` adjacentes, e
    troca-los nao levanta, nao da erro de tipo e o mypy nao ve -- mesma razao
    dos dois `int` de `horario_permite_envio`.

    O link fica no corpo e NAO no assunto: assunto e o que o corretor le na
    notificacao do celular, e uma URL longa ali empurra a etiqueta para fora
    da tela, que e justamente o que ele precisa ver para decidir se abre.
    """
    assunto = f"Lead pronto [{etiqueta}] prioridade {prioridade}"
    corpo = "\n\n".join((resumo or TEXTO_SEM_RESUMO, f"Conversa completa: {link}"))
    return assunto, corpo
```

```python
# src/mobia/domain/notificacao/canais.py
"""Os canais da RN-16.2 -- e a razao de nenhum deles entregar ainda.

TEC-177, D4.

**Os dois adaptadores registram e nao entregam, e isso nao e provisorio por
desleixo: e provisorio por dependencia externa.**

O e-mail nao tem infraestrutura neste projeto -- nenhuma dependencia no
`pyproject.toml`, nenhum SMTP, nenhum provedor -- e escolher um foi
deliberadamente adiado em 12/09/2026.

O WhatsApp esbarra na Meta: a Cloud API recusa mensagem livre passadas 24h da
ultima fala do destinatario (codigo 131047, que `outbound/whatsapp.py` ja
trata), e o corretor esta SEMPRE fora dessa janela porque nao conversa com o
numero da empresa. Entregar exige um template aprovado, que e cadastro
externo com prazo proprio.

**Uma forma so para os dois** porque a regra os trata igual: "falha em um dos
canais nao cancela o outro" so e escrevivel uma vez se os dois tiverem a
mesma assinatura.
"""

from typing import Protocol

import structlog

log = structlog.get_logger(__name__)


class FalhaDeCanal(RuntimeError):
    """O canal nao aceitou a mensagem.

    Existe para o orquestrador distinguir "este canal falhou" de um defeito de
    programacao, que deve subir. Sem ela, um `except Exception` no
    orquestrador engoliria TypeError e AttributeError como se fossem falha de
    entrega, e o handoff sairia marcado como pendente de aviso manual por um
    bug que ninguem veria.
    """


class CanalDeNotificacaoPort(Protocol):
    nome: str

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None: ...


class _CanalQueRegistra:
    """Base dos dois adaptadores de hoje. Nunca levanta, nunca entrega."""

    nome = ""
    motivo = ""

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        # **Nunca loga `corpo`**: ele carrega o resumo, que e prosa destilada
        # do que o lead escreveu -- a mesma razao pela qual `handoffs.resumo`
        # e cifrado em repouso. `destino` e `assunto` entram porque sao o que
        # permite saber se o roteamento esta certo.
        log.info(
            "notificacao.nao_entregue",
            canal=self.nome,
            destino=destino,
            assunto=assunto,
            motivo=self.motivo,
        )


class EmailRegistrado(_CanalQueRegistra):
    nome = "email"
    motivo = "sem provedor de e-mail configurado neste projeto"


class WhatsAppRegistrado(_CanalQueRegistra):
    nome = "whatsapp"
    motivo = "sem template aprovado pela Meta para mensagem fora da janela de 24h"
```

- [ ] **Step 4: Run to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_notificacao_mensagem.py tests/unit/test_notificacao_canais.py -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Run the static gates.** Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/notificacao/ tests/unit/test_notificacao_*.py
git commit -m "feat(TEC-177): a mensagem do corretor, e dois canais que registram sem entregar"
```

---

### Task 2: As duas colunas de estado

**Files:**
- Create: `alembic/versions/0026_notificacao_do_handoff.py`
- Modify: `src/mobia/domain/handoff/models.py`
- Test: `tests/integration/test_handoff_schema.py` (acrescentar)

**Interfaces:**
- Produces: `Handoff.notificado_em: datetime | None`, `Handoff.aviso_manual_pendente: bool`.

**Leia `alembic/versions/0024_resumo_do_handoff.py` antes** — é a migration irmã que também acrescenta colunas a `handoffs`, e o formato do docstring é o padrão.

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_handoff_schema.py`:

```python
async def test_as_colunas_da_notificacao_nascem_com_o_default_certo(
    session: AsyncSession,
) -> None:
    """`notificado_em` nulo e `aviso_manual_pendente` falso: ninguem tentou ainda.

    O default de `aviso_manual_pendente` e FALSO e nao verdadeiro, e a
    distincao importa: verdadeiro significaria que todo handoff nasce pedindo
    intervencao humana, e o dashboard da E8 mostraria a fila inteira como
    problema. O estado "ainda nao tentei" e falso com `notificado_em` nulo.
    """
    registro = await registrar_handoff(
        session, channel="whatsapp", conversation_key="5511911112222",
        gatilho=Gatilho.LEAD_QUENTE,
    )
    await session.commit()

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == registro.id))
    ).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is False
```

- [ ] **Step 2: Run to verify it fails.** Expected: `AttributeError: 'Handoff' object has no attribute 'notificado_em'`

- [ ] **Step 3: Write the migration and the columns**

```python
# alembic/versions/0026_notificacao_do_handoff.py
"""o estado da notificacao ao corretor, ao lado do handoff que ela avisa

TEC-177, RF-16 e RN-16.2.

**Duas colunas, e nenhuma tabela de historico.** Nada nesta card le tentativa
passada: o que a E8 e a TEC-178 vao querer e o estado CORRENTE, e e isso que
as duas dizem. Uma tabela append-only sem leitor seria o peso morto que a D1
da TEC-174 recusou.

**`aviso_manual_pendente` nasce FALSO.** Verdadeiro faria todo handoff nascer
pedindo intervencao humana, e o painel mostraria a fila inteira como problema.
O estado "ainda nao tentei" e este par: falso, com `notificado_em` nulo.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs", sa.Column("notificado_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "handoffs",
        sa.Column(
            "aviso_manual_pendente",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("handoffs", "aviso_manual_pendente")
    op.drop_column("handoffs", "notificado_em")
```

No modelo `Handoff`, antes de `criado_em`:

```python
    # Quando ao menos um canal aceitou a mensagem. Nulo enquanto ninguem
    # tentou -- e continua nulo quando os dois recusam, caso em que a coluna
    # ao lado e que conta a historia.
    notificado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # O "pendente de aviso manual" do terceiro cenario da TEC-177: nenhum
    # canal aceitou, ou nao havia destinatario. Nasce FALSO -- ver a migration.
    aviso_manual_pendente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
```

com `Boolean` acrescentado ao import de `sqlalchemy`.

- [ ] **Step 4: Apply and run**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -v --tb=short
```

- [ ] **Step 5: Run the static gates.** `alembic/` está no escopo do formatador.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0026_notificacao_do_handoff.py src/mobia/domain/handoff/models.py tests/integration/test_handoff_schema.py
git commit -m "feat(TEC-177): o handoff passa a dizer se alguem foi avisado"
```

---

### Task 3: O destinatário

**Files:**
- Create: `src/mobia/domain/notificacao/destinatario.py`
- Test: `tests/integration/test_notificacao_destinatario.py`

**Interfaces:**
- Consumes: `Corretor` de `mobia.domain.corretores.models`; `Handoff`.
- Produces: `destinatario_do_handoff(session, *, handoff: Handoff) -> Corretor | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_notificacao_destinatario.py
"""A cascata: corretor alocado, senao o plantao mais antigo, senao ninguem."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.notificacao.destinatario import destinatario_do_handoff

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _handoff(session: AsyncSession) -> Handoff:
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    return (
        await session.execute(select(Handoff).where(Handoff.id == registro.id))
    ).scalar_one()


async def test_sem_corretor_nenhum_devolve_none(session: AsyncSession) -> None:
    """D4: nao ha para quem mandar, e fingir que mandou seria pior."""
    assert await destinatario_do_handoff(session, handoff=await _handoff(session)) is None


async def test_sem_alocado_devolve_o_plantao(
    session: AsyncSession, semear_corretor
) -> None:
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    await semear_corretor(email="comum@x.com", plantao=False)

    escolhido = await destinatario_do_handoff(session, handoff=await _handoff(session))

    assert escolhido is not None
    assert escolhido.id == plantao.id


async def test_com_dois_plantoes_devolve_o_mais_antigo(
    session: AsyncSession, semear_corretor
) -> None:
    """D3: a card nao escreveu a regra, e esta card precisa de UMA resposta.

    O mais antigo e o que nao muda quando alguem cadastra um plantao novo.
    """
    agora = datetime.now(UTC)
    antigo = await semear_corretor(
        email="antigo@x.com", plantao=True, criado_em=agora - timedelta(days=2)
    )
    await semear_corretor(email="novo@x.com", plantao=True, criado_em=agora)

    escolhido = await destinatario_do_handoff(session, handoff=await _handoff(session))

    assert escolhido is not None
    assert escolhido.id == antigo.id


async def test_plantao_inativo_nao_recebe(
    session: AsyncSession, semear_corretor
) -> None:
    await semear_corretor(email="plantao@x.com", plantao=True, ativo=False)

    assert await destinatario_do_handoff(session, handoff=await _handoff(session)) is None


async def test_alocado_ganha_do_plantao(
    session: AsyncSession, semear_corretor
) -> None:
    """O ramo que hoje nunca roda em producao -- ver a L4 do desenho."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    alocado = await semear_corretor(email="alocado@x.com", plantao=False)

    handoff = await _handoff(session)
    handoff.corretor_id = alocado.id
    await session.commit()

    escolhido = await destinatario_do_handoff(session, handoff=handoff)

    assert escolhido is not None
    assert escolhido.id == alocado.id


async def test_alocado_inativo_cai_para_o_plantao(
    session: AsyncSession, semear_corretor
) -> None:
    """Corretor desativado nao recebe alocacao nova -- e nem notificacao velha."""
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    alocado = await semear_corretor(email="saiu@x.com", plantao=False, ativo=False)

    handoff = await _handoff(session)
    handoff.corretor_id = alocado.id
    await session.commit()

    escolhido = await destinatario_do_handoff(session, handoff=handoff)

    assert escolhido is not None
    assert escolhido.id == plantao.id
```

A fixture `semear_corretor` entra em `tests/conftest.py`, devolvendo o `Corretor` criado e aceitando sobrescritas (`email`, `plantao`, `ativo`, `criado_em`). Preencha os campos obrigatórios reusando o que `criar_corretor` já valida — mas **crie o modelo direto**, sem passar pelo repositório, para poder fixar `criado_em`.

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/mobia/domain/notificacao/destinatario.py
"""Quem recebe a notificacao do handoff. TEC-177, D3.

A RN-16.2 diz "o corretor designado". Designar e a TEC-166, e
`handoffs.corretor_id` nunca e escrito hoje -- a chave estrangeira existe
desde a TEC-196, o escritor nao. Dai a cascata.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff


async def destinatario_do_handoff(
    session: AsyncSession, *, handoff: Handoff
) -> Corretor | None:
    """O corretor alocado, senao o plantao mais antigo, senao `None`.

    **Corretor inativo nao recebe, nem quando esta alocado.** A TEC-196 diz
    que desativar "o retira das proximas alocacoes"; mandar notificacao para
    quem saiu da equipe seria manter a alocacao antiga viva pela porta dos
    fundos. Nesse caso a cascata segue para o plantao.

    **O mais antigo entre varios plantoes**, por `criado_em`: a D7 da TEC-196
    deixou a multiplicidade aberta de proposito, e esta card precisa de uma
    resposta determinista para poder enviar. O mais antigo e o que nao muda
    quando alguem cadastra um plantao novo -- `ORDER BY criado_em DESC` faria
    o destinatario trocar sozinho a cada cadastro.

    `None` significa "nao ha a quem mandar", e quem chama marca o handoff como
    pendente de aviso manual (D4). Nao levanta: a ausencia de corretor e um
    estado previsto deste sistema, nao um erro.
    """
    if handoff.corretor_id is not None:
        alocado = await _corretor_ativo(session, corretor_id=handoff.corretor_id)
        if alocado is not None:
            return alocado

    return (
        await session.execute(
            select(Corretor)
            .where(Corretor.plantao.is_(True), Corretor.ativo.is_(True))
            .order_by(Corretor.criado_em)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _corretor_ativo(
    session: AsyncSession, *, corretor_id: uuid.UUID
) -> Corretor | None:
    return (
        await session.execute(
            select(Corretor).where(Corretor.id == corretor_id, Corretor.ativo.is_(True))
        )
    ).scalar_one_or_none()
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS (6 testes)

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/notificacao/destinatario.py tests/integration/test_notificacao_destinatario.py tests/conftest.py
git commit -m "feat(TEC-177): o destinatario cai para o plantao, e corretor inativo nao recebe"
```

---

### Task 4: A orquestração e o aviso ao lead

**Files:**
- Create: `src/mobia/domain/notificacao/envio.py`
- Test: `tests/integration/test_notificacao_envio.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–3; `link_da_transcricao` de `mobia.domain.handoff.resumo`; `aad_do_resumo_de_handoff` de `mobia.domain.handoff.models`; `horario_permite_envio` de `mobia.domain.outbound.horario`; `OutboundPort`.
- Produces: `KIND_DA_JANELA_HUMANA`, `TEXTO_DA_JANELA_HUMANA`, `notificar(session_factory, *, canais, outbound, handoff_id) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_notificacao_envio.py
"""A notificacao de ponta a ponta, com canais falsos."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.models import Handoff
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.envio import KIND_DA_JANELA_HUMANA, notificar


class _CanalEspiao:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, str, str]] = []

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        self.recebidas.append((destino, assunto, corpo))


class _CanalQueFalha:
    def __init__(self, nome: str) -> None:
        self.nome = nome

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        raise FalhaDeCanal(f"{self.nome} recusou")


async def test_notifica_os_dois_canais_com_resumo_e_link(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Primeiro cenario do Gherkin, com dubles -- ver a L1 do desenho."""
    corretor = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="## Quem e o lead\nfulano")
    email, whats = _CanalEspiao("email"), _CanalEspiao("whatsapp")

    assert await notificar(
        session_factory, canais=(email, whats), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    for canal in (email, whats):
        assert len(canal.recebidas) == 1
        _, _, corpo = canal.recebidas[0]
        assert "## Quem e o lead" in corpo
        assert "/conversas/whatsapp/" in corpo

    assert email.recebidas[0][0] == corretor.email
    assert whats.recebidas[0][0] == corretor.telefone


async def test_falha_de_um_canal_nao_cancela_o_outro(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Segundo cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory,
        canais=(_CanalQueFalha("whatsapp"), email),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    assert len(email.recebidas) == 1
    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.notificado_em is not None
    assert linha.aviso_manual_pendente is False


async def test_falha_dos_dois_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Terceiro cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalQueFalha("email"), _CanalQueFalha("whatsapp")),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is True


async def test_sem_destinatario_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo
) -> None:
    """D4: nenhum corretor cadastrado."""
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory, canais=(_CanalEspiao("email"),), outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.aviso_manual_pendente is True


async def test_handoff_sem_resumo_notifica_mesmo_assim(
    session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """D2: silencio seria pior que resumo faltando."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo=None)
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    _, _, corpo = email.recebidas[0]
    assert "nao pode ser gerado" in corpo
```

> **O quarto cenário — fora do horário — precisa de um teste próprio**, que você escreve nesta task: com a jornada do corretor fechada no momento do envio, o corretor recebe **na mesma** e o `outbound` recebe uma chamada com `KIND_DA_JANELA_HUMANA`. Use um corretor com `horario_inicio`/`horario_fim` que não contenham o momento atual, e um `_OutboundFalso` que registre as chamadas. **Cuidado para não escrever um teste que dependa da hora em que a suíte roda** — parametrize o momento, ou escolha a jornada em função do relógio do teste.

> As fixtures `semear_handoff_com_resumo` e `semear_corretor` entram em `tests/conftest.py`. A segunda pode já existir da Task 3.

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

O esqueleto, com as decisões que importam comentadas:

```python
# src/mobia/domain/notificacao/envio.py
"""A notificacao do handoff, de ponta a ponta. TEC-177, RN-16.2."""

# O `kind` do aviso ao lead. Chaveado na ULTIMA mensagem da conversa, e nao no
# handoff: a UNIQUE (message_id, kind) de `outbound_dispatches` da a
# deduplicacao, e a guarda de opt-out de `GuardedOutbound` vem junto -- um lead
# que pediu para nao ser contatado nao recebe, e nao foi preciso escrever nada
# para isso. Ver a D5.
KIND_DA_JANELA_HUMANA = "janela_humana"

TEXTO_DA_JANELA_HUMANA = (
    "Ja avisei um corretor sobre a sua conversa. "
    "O atendimento humano funciona de segunda a sabado, das {inicio}h as {fim}h, "
    "entao a resposta deve vir na proxima janela."
)
```

`notificar` faz, nesta ordem:

1. Carrega o handoff. Sumiu → log e `False`.
2. Resolve o destinatário (Task 3). `None` → marca `aviso_manual_pendente`, log em `error`, `False`.
3. Decifra o resumo com `aad_do_resumo_de_handoff`, se houver; compõe o link com `link_da_transcricao`; monta assunto e corpo (Task 1).
4. Para cada canal, num `try` próprio: `enviar`, capturando **só** `FalhaDeCanal` — defeito de programação sobe.
5. Ao menos um aceitou → grava `notificado_em`. Nenhum → `aviso_manual_pendente = True` e log em `error` com o motivo de cada canal.
6. Se `horario_permite_envio` disser que a jornada do corretor está fechada, envia o aviso ao lead pelo `OutboundPort`, com `KIND_DA_JANELA_HUMANA`. **Essa chamada não pode derrubar a notificação**: o corretor já foi avisado, e o aviso ao lead é secundário — falha ali vira log e segue, no mesmo molde do `_agendar_resumo` da TEC-175.

> **Duas coisas que você decide ao escrever, e deve registrar no relatório:** de qual mensagem da conversa sai o `message_id` do aviso ao lead (sugestão: a mais recente, por `created_at`), e o que fazer quando não houver mensagem nenhuma. E confirme que `notificar` recebe **factory** e não sessão, pela mesma razão da TEC-175: a chamada aos canais fica fora de qualquer transação.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/notificacao/envio.py tests/integration/test_notificacao_envio.py tests/conftest.py
git commit -m "feat(TEC-177): a notificacao isola falha por canal e avisa o lead da janela"
```

---

### Task 5: O job e o encadeamento

**Files:**
- Create: `src/mobia/workers/jobs/notificar.py`
- Modify: `src/mobia/workers/jobs/gerar_resumo.py`, `src/mobia/workers/main.py`
- Test: `tests/integration/test_notificacao_job.py`, `tests/integration/test_queue.py` (acrescentar)

**Interfaces:**
- Consumes: `notificar` (Task 4).
- Produces: `NOTIFICAR_JOB = "notificar_corretor"`; a função de job `notificar_corretor(ctx, handoff_id)`.

- [ ] **Step 1: Write the failing test**

Testes que esta task precisa provar:
- O job do resumo **enfileira a notificação ao terminar**, e enfileira **mesmo quando a geração falhou** (D2). Use um espião no lugar do enfileirador.
- O job de notificação resolve os canais do `ctx` e chama `notificar`.
- `NOTIFICAR_JOB` está amarrado ao nome registrado em `WorkerSettings.functions` — **copie o molde de `test_gerar_resumo_registrado_com_o_nome_esperado` em `tests/integration/test_queue.py`**, que a TEC-175 criou exatamente para isso.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write the job and the chaining**

O job novo espelha `workers/jobs/gerar_resumo.py`: pega os canais e o `outbound` do `ctx`, chama `notificar`, devolve um rótulo.

Em `gerar_resumo.py`, depois do `_gerar`, enfileirar a notificação. **Duas exigências:**
- **Enfileira independentemente do resultado** — a D2 manda notificar mesmo sem resumo.
- **Não pode propagar exceção**: o resumo já está gravado, e uma falha do Redis aqui perderia a notificação mas não deve desfazer o trabalho feito. Log e segue, no molde de `_agendar_resumo`.

Em `main.py`: registrar o job com `keep_result=0` (mesma razão dos outros dois), pôr os canais no `ctx` no `startup`, e **não** entrar em `cron_jobs`.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/workers/jobs/notificar.py src/mobia/workers/jobs/gerar_resumo.py src/mobia/workers/main.py tests/integration/test_notificacao_job.py tests/integration/test_queue.py
git commit -m "feat(TEC-177): o resumo pronto enfileira a notificacao, com resumo ou sem"
```

---

### Task 6: Fechamento

- [ ] **Step 1: Suíte inteira, uma vez.** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`

Se dezenas de testes falharem com `relation ... does not exist`, leia a nota das Global Constraints sobre os bancos dos workers **antes** de mexer em código.

- [ ] **Step 2: Comentários tocados.** `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

Candidato previsível: o docstring de `workers/jobs/gerar_resumo.py`, que descreve um job que agora faz mais uma coisa.

- [ ] **Step 3: Orçamento do prompt.** `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s` — inalterado.

- [ ] **Step 4: Os três gates, e push.**

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 5. D2 → Tasks 1, 4 e 5. D3 → Task 3. D4 → Tasks 1 e 4. D5 → Task 4. D6 → Tasks 2 e 4. D7 → Task 4. L1–L4 → declaradas; sem task, por construção.

**Consistência de tipos:** `CanalDeNotificacaoPort` é produzido na Task 1 e consumido nas 4 e 5; `destinatario_do_handoff` na 3 e usado na 4; `notificar` na 4 e usado na 5.

**Três pontos que o executor resolve contra o repo,** marcados em citação: o teste do quarto cenário que não pode depender da hora do relógio; de qual mensagem sai o `message_id` do aviso ao lead, e o que fazer sem mensagem nenhuma; e as fixtures novas em `conftest.py`.
