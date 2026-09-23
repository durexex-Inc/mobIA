# TEC-130 — Encerramento por inatividade e fronteira de histórico: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A conversa passa a ser encerrada por inatividade de 30 dias e por opt-out, e a primeira mensagem depois de um encerramento entrega ao agente o resumo da conversa anterior em vez da transcrição dela.

**Architecture:** Dois mecanismos que compartilham uma constante e não dependem um do outro. Um job diário escreve o encerramento em `conversas` (data e motivo). Independentemente dele, o turno detecta pelo relógio que esta mensagem abre conversa nova e força a dobra do histórico no resumo antes de montar o contexto — a marca do resumo passa a cobrir a conversa anterior inteira, e `literais_apos` devolve só o que é novo.

**Tech Stack:** Python 3.13, SQLAlchemy async, ARQ (cron), Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-tec-130-encerrar-por-inatividade-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o literal citado. Nenhum linter checa isto.
- **Texto que o lead recebe: português COM acento.** Esta card não acrescenta nenhum texto novo para o lead.
- **Prosa em `docs/`: com acento.**
- **Os três gates, nesta ordem, antes de qualquer commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter — passar num não diz nada sobre o outro.
- **Testes unitários durante o loop:** `./.venv/Scripts/python.exe -m pytest tests/unit` (sem `-n`, sem docker). Integração e features exigem `docker compose` de pé.
- **Nenhuma migration nesta card.** `motivo_do_encerramento` é `String(16)`; `INATIVIDADE` tem 11 caracteres e `OPTOUT` tem 6. Não há coluna nova, tabela nova nem alteração de tipo. Se você se pegar escrevendo uma migration, pare — o desenho decidiu o contrário (D2, D7).
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-130): o que passou a ser verdade`.

---

## Estrutura de arquivos

**Modificados:**
- `src/mobia/domain/conversa/regras.py` — passa a guardar a janela de silêncio, além do teto de fora de escopo. É o módulo puro do ciclo de vida da conversa.
- `src/mobia/domain/conversa/vocabulario.py` — dois membros novos em `MotivoDoEncerramento`, e a docstring que prometia um só.
- `src/mobia/domain/conversa/repositorio.py` — ganha `encerrar_inativas`; passa a importar a constante de `regras.py` em vez de `agente/identificacao.py`.
- `src/mobia/domain/agente/identificacao.py` — perde a constante, importa de `regras.py`, e o comentário que prometia perguntar a entidade muda.
- `src/mobia/domain/context/montagem.py` — `montar_contexto` e `_dobrar` ganham o parâmetro da dobra forçada.
- `src/mobia/domain/agente/turno.py` — liga a dobra forçada; encerra por opt-out; o comentário da reabertura deixa de dizer que não há job varrendo.
- `src/mobia/workers/main.py` — registra o job e o cron.
- `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` — Emenda E-03 à RN-02.3.
- `tests/integration/test_turno_optout.py` — ganha os dois testes do encerramento por opt-out, em vez de um arquivo novo: o helper e as cinco fixtures de dublê já vivem lá.

**Criados:**
- `src/mobia/workers/jobs/sweep_conversas_inativas.py` — o job, fino, no molde de `sweep_sla.py`.
- `tests/unit/test_conversa_vocabulario_tec130.py`
- `tests/integration/test_encerrar_inativas.py`
- `tests/integration/test_dobra_na_reabertura.py`

> **Atenção ao basename dos arquivos de teste.** Basename repetido entre `tests/unit/` e `tests/integration/` aborta a coleta da suíte inteira e não aparece quando se roda um diretório só. Os nomes acima já são únicos no repo — confira com `ls tests/*/ | sort | uniq -d` se inventar outro.

---

### Task 1: A constante muda de casa e o vocabulário ganha dois motivos

**Files:**
- Modify: `src/mobia/domain/conversa/regras.py`
- Modify: `src/mobia/domain/conversa/vocabulario.py`
- Modify: `src/mobia/domain/agente/identificacao.py:30-32`
- Modify: `src/mobia/domain/conversa/repositorio.py` (a linha do `import`)
- Test: `tests/unit/test_conversa_vocabulario_tec130.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `mobia.domain.conversa.regras.DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA: int` (valor `30`), e `MotivoDoEncerramento.INATIVIDADE` / `MotivoDoEncerramento.OPTOUT` (valores `"INATIVIDADE"` e `"OPTOUT"`). As tarefas 2, 3, 4 e 6 dependem dos dois.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_conversa_vocabulario_tec130.py`:

```python
"""Os dois motivos que a TEC-130 acrescenta, e o silencio que eles NAO herdam."""

from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.conversa.repositorio import SituacaoDaConversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento


def test_a_janela_de_silencio_mora_nas_regras_da_conversa() -> None:
    """A constante saiu de `agente/identificacao.py` e vive no modulo puro.

    Ela e compartilhada por tres leitores -- a identificacao de conversa nova,
    a janela de `situacao_da_conversa` e a varredura de inativas -- e morar no
    modulo de um deles fazia os outros dois importarem de `agente/`.
    """
    assert DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA == 30


def test_identificacao_reexporta_a_mesma_constante() -> None:
    """Nao ha duas definicoes de silencio no sistema, so um reexport."""
    from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA as da_ident

    assert da_ident is DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA


def test_os_dois_motivos_novos_existem() -> None:
    assert MotivoDoEncerramento.INATIVIDADE == "INATIVIDADE"
    assert MotivoDoEncerramento.OPTOUT == "OPTOUT"


def test_nenhum_motivo_novo_cala_o_agente() -> None:
    """**O ponto inteiro da RN-02.3.**

    Calar por 30 dias e politica do FORA_DE_ESCOPO (RN-03.5). Um motivo novo
    que herdasse o silencio destruiria o reengajamento que esta card existe
    para ter: o lead que volta depois de 30 dias parados ficaria mais 30 sem
    resposta.
    """
    for motivo in (MotivoDoEncerramento.INATIVIDADE, MotivoDoEncerramento.OPTOUT):
        situacao = SituacaoDaConversa(
            marcada_como_encerrada=True,
            dentro_da_janela=True,
            motivo_do_encerramento=str(motivo),
        )
        assert situacao.silencia_o_agente is False


def test_fora_de_escopo_continua_calando() -> None:
    """A contraprova do teste acima: a propriedade nao foi neutralizada."""
    situacao = SituacaoDaConversa(
        marcada_como_encerrada=True,
        dentro_da_janela=True,
        motivo_do_encerramento=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
    )
    assert situacao.silencia_o_agente is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_conversa_vocabulario_tec130.py -v --tb=short
```

Esperado: FAIL com `ImportError: cannot import name 'DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA' from 'mobia.domain.conversa.regras'`.

- [ ] **Step 3: Mover a constante para `regras.py`**

Acrescente ao fim de `src/mobia/domain/conversa/regras.py`:

```python
# RN-02.3 e RN-03.5. **Tres leitores compartilham este numero de proposito**:
# `e_conversa_nova` (`agente/identificacao.py`) mede o silencio que abre
# conversa nova, `situacao_da_conversa` (`repositorio.py`) mede a janela do
# encerramento, e `encerrar_inativas` (`repositorio.py`) varre o que passou
# dela. Dois numeros iguais escritos em lugares diferentes divergem na
# primeira vez que alguem mexe em um -- e divergir aqui significa o turno
# tratar como conversa nova o que a varredura ainda considera ativa, ou o
# contrario.
#
# Estava em `agente/identificacao.py` ate a TEC-130. Saiu de la porque dois
# dos tres leitores nao sao do modulo do agente, e um deles e uma varredura
# de worker.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30
```

- [ ] **Step 4: `identificacao.py` importa em vez de definir**

Em `src/mobia/domain/agente/identificacao.py`, **remova** as três linhas:

```python
# Mesmo limiar da TEC-130. Quando aquela card chegar, este modulo passa a
# perguntar a entidade em vez de derivar, e esta constante sai.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30
```

e ponha, junto dos outros imports:

```python
from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
```

Acrescente, logo abaixo do bloco de imports, o comentário que substitui a promessa desfeita:

```python
# **A TEC-130 chegou e este modulo continua derivando, de proposito.** O
# comentario que morava aqui prometia que, quando aquela card chegasse, o
# modulo passaria a "perguntar a entidade em vez de derivar". A D3 do desenho
# dela declinou: perguntar a entidade poe a varredura diaria no caminho
# critico de uma correcao de contexto -- com ela parada, ou apenas ainda nao
# executada no dia, a conversa continuaria ATIVA, `e_conversa_nova` devolveria
# False, e o turno montaria o prompt com a transcricao velha E sem
# apresentacao, em silencio. Derivar e o que torna a correcao verdadeira
# independentemente do cron. O que saiu daqui foi so a constante, para
# `conversa/regras.py`, que e onde os outros dois leitores dela vivem.
```

- [ ] **Step 5: `conversa/repositorio.py` importa da casa nova**

Troque, no bloco de imports:

```python
from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
```

por:

```python
from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
```

- [ ] **Step 6: Acrescentar os dois motivos**

Em `src/mobia/domain/conversa/vocabulario.py`, dentro de `MotivoDoEncerramento`, substitua o parágrafo que diz **"Um unico membro por enquanto"** por:

```python
    """Vocabulario e nao booleano de proposito.

    A regra da card pede que o motivo seja "proprio, separado do encerramento
    por inatividade", e uma booleana `encerrada` obrigaria quem precisasse de
    um segundo motivo a inventar onde guarda-lo.

    **Tres membros desde a TEC-130**, e foi essa extensao -- membros novos em
    vez de uma segunda tabela ou uma segunda coluna -- que justificou isto ser
    enum desde a TEC-138.

    **Nenhum dos dois motivos novos herda a janela de silencio dos 30 dias.**
    Ela e politica da RN-03.5 e `SituacaoDaConversa.silencia_o_agente`
    (`repositorio.py`) a condiciona a `FORA_DE_ESCOPO`. Para `INATIVIDADE` e o
    ponto inteiro da RN-02.3: a conversa fechada por silencio tem de ser
    respondida na mensagem seguinte, senao o reengajamento morre. Para
    `OPTOUT` o silencio ja existe e vem de `esta_em_optout`, cujo portao roda
    antes da reabertura em `turno.py` -- duplica-lo aqui criaria duas fontes
    para o mesmo fato.

    **`FORA_DE_ESCOPO` e igual, byte a byte, a `Intencao.FORA_DE_ESCOPO`
    (`domain/agente/schemas.py`), e isso e coincidencia, nao a mesma coisa.**
    Um e motivo de encerramento de conversa; o outro e classificacao de turno.
    Ja divergiram: `INATIVIDADE` e `OPTOUT` nao tem equivalente em `Intencao`.
    """

    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"
    INATIVIDADE = "INATIVIDADE"
    OPTOUT = "OPTOUT"
```

- [ ] **Step 7: Atualizar a docstring de `conversa/models.py`**

Ela diz que a TEC-130 "acrescenta INATIVIDADE ao vocabulario" no futuro, e que o encerramento por inatividade "e uma regra do SRS sem implementacao, reservada para a TEC-130". Passou a ser falso. Substitua o parágrafo que começa em **"Consequencia para quem pegar a TEC-130"** por:

```python
**A TEC-130 estendeu isto, e nao criou nada.** Ela acrescentou `INATIVIDADE` e
`OPTOUT` ao vocabulario de `vocabulario.py`, mais dois escritores -- a
varredura diaria (`encerrar_inativas`, em `repositorio.py`) e o bloco de
opt-out do turno. Nenhuma tabela nova, nenhuma segunda nocao de encerrado, e
nenhuma migration: a coluna ja comportava os literais. A Emenda E-02 da RN-02.3
previa exatamente isso, e a E-03 registra o que mudou.

**O que ela NAO trouxe e a janela de silencio.** Os 30 dias em que o agente
nao responde continuam sendo politica da RN-03.5, e
`SituacaoDaConversa.silencia_o_agente` (`repositorio.py`) continua exigindo
`FORA_DE_ESCOPO`. Uma conversa fechada por inatividade e respondida na
mensagem seguinte -- que e o que a RN-02.3 pede.
```

- [ ] **Step 8: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_conversa_vocabulario_tec130.py -v --tb=short
```

Esperado: 5 passed.

- [ ] **Step 9: Verificar que nada mais importava a constante do lugar velho**

```bash
grep -rn "identificacao import.*DIAS_DE_SILENCIO\|from mobia.domain.agente.identificacao import" src tests --include=*.py | grep -v __pycache__
```

Qualquer linha que ainda importe `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` de `identificacao` continua funcionando (o reexport existe), mas se for código de produção, troque para `conversa.regras`.

- [ ] **Step 10: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
```

```bash
git add src/mobia/domain/conversa/regras.py src/mobia/domain/conversa/vocabulario.py \
        src/mobia/domain/conversa/models.py src/mobia/domain/conversa/repositorio.py \
        src/mobia/domain/agente/identificacao.py tests/unit/test_conversa_vocabulario_tec130.py
git commit -m "feat(TEC-130): a janela de silencio vira regra da conversa, e o vocabulario ganha dois motivos"
```

---

### Task 2: `encerrar_inativas` — a varredura, no repositório

**Files:**
- Modify: `src/mobia/domain/conversa/repositorio.py`
- Test: `tests/integration/test_encerrar_inativas.py`

**Interfaces:**
- Consumes: `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` e `MotivoDoEncerramento.INATIVIDADE` (Task 1).
- Produces: `async def encerrar_inativas(session_factory: async_sessionmaker[AsyncSession], *, agora: datetime, limite: int = 500) -> int` — devolve quantas conversas fechou. A Task 3 chama exatamente esta assinatura.

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_encerrar_inativas.py`:

```python
"""A varredura que fecha conversa parada. TEC-130, RN-02.3.

**O relogio conta da ultima fala do LEAD**, nao da ultima mensagem de
qualquer direcao: o follow-up automatico da RN-13.1 dispara ate 14 dias
depois do lead sumir, e contar OUTBOUND deixaria o proprio sistema adiando o
encerramento de quem ja tinha ido embora.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.repositorio import encerrar_conversa, encerrar_inativas
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker

AGORA = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


async def _semear(
    session: AsyncSession,
    *,
    chave: str,
    dias_atras: float,
    direction: MessageDirection = MessageDirection.INBOUND,
) -> None:
    """Uma linha em `messages`, so com o que a varredura le e o que a tabela exige.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL; `text_body` fica nulo de proposito -- nada nesta varredura
    decifra texto, e cifrar aqui so acrescentaria uma chave ao teste.
    """
    session.add(
        Message(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key=chave,
            role=(
                MessageRole.LEAD
                if direction is MessageDirection.INBOUND
                else MessageRole.AGENTE
            ),
            direction=direction,
            content_type=MessageContentType.TEXTO,
            created_at=AGORA - timedelta(days=dias_atras),
        )
    )
    await session.commit()


async def _status_de(session: AsyncSession, chave: str) -> tuple[str, str | None] | None:
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.motivo_do_encerramento).where(
                Conversa.conversation_key == chave
            )
        )
    ).one_or_none()
    return None if linha is None else (linha.status, linha.motivo_do_encerramento)


@pytest.mark.usefixtures("banco_limpo")
async def test_trinta_dias_encerra(session: AsyncSession) -> None:
    await _semear(session, chave="lead-30", dias_atras=30)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 1
    assert await _status_de(session, "lead-30") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_vinte_e_nove_dias_nao_encerra(session: AsyncSession) -> None:
    """O empate resolve para o lado fechado, como `situacao_da_conversa` ja
    resolve o dela -- exatamente 30 encerra, 29 nao."""
    await _semear(session, chave="lead-29", dias_atras=29)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-29") is None


@pytest.mark.usefixtures("banco_limpo")
async def test_o_followup_nao_adia_o_encerramento(session: AsyncSession) -> None:
    """Lead sumiu no dia 30; o follow-up saiu no dia 14. Encerra assim mesmo."""
    await _semear(session, chave="lead-fup", dias_atras=30)
    await _semear(
        session, chave="lead-fup", dias_atras=14, direction=MessageDirection.OUTBOUND
    )

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 1
    assert await _status_de(session, "lead-fup") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_nao_sobrescreve_motivo_de_encerramento_anterior(session: AsyncSession) -> None:
    """**Sem isto, toda conversa do sistema converge para INATIVIDADE.**

    `encerrar_conversa` e upsert idempotente de proposito, entao a varredura
    apagaria o motivo real 30 dias depois de ele ter sido escrito -- e o
    motivo e vocabulario justamente para nao perder essa distincao.
    """
    await _semear(session, chave="lead-fe", dias_atras=40)
    await encerrar_conversa(
        session,
        channel="whatsapp",
        conversation_key="lead-fe",
        motivo=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
        agora=AGORA - timedelta(days=35),
    )
    await session.commit()

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-fe") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.FORA_DE_ESCOPO,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_conversa_sem_nenhuma_fala_do_lead_nao_encerra(session: AsyncSession) -> None:
    """So OUTBOUND: nao ha fala do lead para medir o silencio a partir de.

    Encerrar aqui seria fechar a conversa de alguem que nunca falou, contando
    o relogio de uma mensagem nossa -- exatamente o que o `INBOUND` evita.
    """
    await _semear(
        session, chave="lead-mudo", dias_atras=45, direction=MessageDirection.OUTBOUND
    )

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-mudo") is None


@pytest.mark.usefixtures("banco_limpo")
async def test_o_limite_corta_a_passagem(session: AsyncSession) -> None:
    for n in range(3):
        await _semear(session, chave=f"lead-{n}", dias_atras=40)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA, limite=2)

    assert fechadas == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_encerrar_inativas.py -v --tb=short
```

Esperado: FAIL com `ImportError: cannot import name 'encerrar_inativas'`.

> Se em vez disso vier uma enxurrada de `ERROR` de setup com `ConnectionResetError [WinError 64]`, o banco ainda está negociando SSL — espere e rode de novo. Não é o seu código. Se vier `relation ... does not exist`, veja a seção dos bancos de worker no `CLAUDE.md`.

- [ ] **Step 3: Implementar `encerrar_inativas`**

Acrescente a `src/mobia/domain/conversa/repositorio.py`. O bloco de imports precisa ganhar quatro coisas que ele ainda não tem:

```python
from sqlalchemy import func, select, update          # `func` e novo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # `async_sessionmaker` e novo

from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
```

Depois, a função:

```python
async def encerrar_inativas(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agora: datetime,
    limite: int = 500,
) -> int:
    """Fecha por INATIVIDADE toda conversa cuja ultima fala do LEAD passou da
    janela. Devolve quantas fechou.

    **Esta funcao e a escrituracao, e nao a correcao do contexto.** A D3 do
    desenho separou as duas de proposito: quem decide que o contexto da
    conversa anterior nao entra no prompt e o turno, pelo relogio, e nao esta
    varredura. Ela pode ficar um dia para tras sem que nada de errado chegue
    ao lead -- o turno ja tratou a conversa como nova antes de ela passar.

    **O relogio e o INBOUND.** "Sem interacao" e o lead sem interagir; o agente
    falando sozinho e a evidencia de que nao ha interacao, nao o contrario.
    Contar OUTBOUND faria o follow-up da RN-13.1 -- que dispara ate 14 dias
    depois do sumico -- empurrar o encerramento para o dia 44.

    **Nao sobrescreve motivo.** O `LEFT JOIN` recusa quem ja esta ENCERRADA:
    `encerrar_conversa` e upsert idempotente, entao sem esse filtro a
    varredura apagaria `FORA_DE_ESCOPO` e `OPTOUT` 30 dias depois de eles
    terem sido escritos, e todo encerramento do sistema convergiria para
    INATIVIDADE.

    Abre a propria sessao e commita -- diferente das outras escritoras deste
    modulo, que recebem a sessao emprestada. Aqui nao ha transacao de
    chamador: quem chama e um job de cron, e o dono da transacao e esta
    funcao.
    """
    corte = agora - timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)

    async with session_factory() as session:
        ultima_fala = (
            select(
                Message.channel,
                Message.conversation_key,
                func.max(Message.created_at).label("ultima"),
            )
            .where(Message.direction == MessageDirection.INBOUND)
            .group_by(Message.channel, Message.conversation_key)
            .having(func.max(Message.created_at) <= corte)
            .subquery()
        )

        candidatas = (
            await session.execute(
                select(ultima_fala.c.channel, ultima_fala.c.conversation_key)
                .outerjoin(
                    Conversa,
                    (Conversa.channel == ultima_fala.c.channel)
                    & (Conversa.conversation_key == ultima_fala.c.conversation_key),
                )
                .where(Conversa.status.is_(None) | (Conversa.status != Status.ENCERRADA))
                .order_by(ultima_fala.c.ultima)
                .limit(limite)
            )
        ).all()

        for candidata in candidatas:
            await encerrar_conversa(
                session,
                channel=candidata.channel,
                conversation_key=candidata.conversation_key,
                motivo=str(MotivoDoEncerramento.INATIVIDADE),
                agora=agora,
            )
        await session.commit()

    return len(candidatas)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_encerrar_inativas.py -v --tb=short
```

Esperado: 6 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/conversa/repositorio.py tests/integration/test_encerrar_inativas.py
git commit -m "feat(TEC-130): a varredura fecha conversa parada contando da ultima fala do lead"
```

---

### Task 3: O job e o cron diário

**Files:**
- Create: `src/mobia/workers/jobs/sweep_conversas_inativas.py`
- Modify: `src/mobia/workers/main.py`
- Test: `tests/integration/test_encerrar_inativas.py` (acrescenta um teste ao arquivo da Task 2)

**Interfaces:**
- Consumes: `encerrar_inativas` (Task 2).
- Produces: `SWEEP_CONVERSAS_INATIVAS_JOB: str = "sweep_conversas_inativas"` e `async def sweep_conversas_inativas(ctx: dict[str, Any], limite: int = 500) -> int`.

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/integration/test_encerrar_inativas.py`:

```python
@pytest.mark.usefixtures("banco_limpo")
async def test_o_job_fecha_e_devolve_a_contagem(session: AsyncSession) -> None:
    """O job e fino: pega a `session_factory` do `ctx` e devolve o numero.

    Mesmo molde de `sweep_sla` -- e o `startup` do worker que decide a
    implementacao, e o teste troca a decisao sem tocar no job.
    """
    from mobia.workers.jobs.sweep_conversas_inativas import sweep_conversas_inativas

    await _semear(session, chave="lead-job", dias_atras=40)

    fechadas = await sweep_conversas_inativas({"session_factory": get_sessionmaker()})

    assert fechadas == 1
    assert await _status_de(session, "lead-job") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )
```

> O job usa `datetime.now(UTC)` internamente, e a fixação de `AGORA` em 22/09/2026 é passado — uma mensagem de 40 dias antes de `AGORA` está ainda mais longe de agora, então continua vencida. Não congele relógio aqui.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_encerrar_inativas.py::test_o_job_fecha_e_devolve_a_contagem -v --tb=short
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'mobia.workers.jobs.sweep_conversas_inativas'`.

- [ ] **Step 3: Criar o job**

`src/mobia/workers/jobs/sweep_conversas_inativas.py`:

```python
"""O job que fecha por inatividade a conversa parada ha 30 dias. TEC-130, RN-02.3."""

from datetime import UTC, datetime
from typing import Any

from mobia.domain.conversa.repositorio import encerrar_inativas

SWEEP_CONVERSAS_INATIVAS_JOB = "sweep_conversas_inativas"


async def sweep_conversas_inativas(ctx: dict[str, Any], limite: int = 500) -> int:
    """Fecha as vencidas e devolve quantas. Fino de proposito, como `sweep_sla`.

    **Este job nao e o que faz a conversa nova comecar limpa.** Quem decide
    que a transcricao anterior nao entra no prompt e o turno, pelo relogio
    (D3 do desenho) -- aqui e so a escrituracao que a RN-02.3 pede: data e
    motivo. Uma passagem perdida atrasa o registro e nao muda uma linha do
    que o lead recebe.

    `datetime.now(UTC)` aqui, e nao no repositorio, pelo mesmo motivo que
    `situacao_da_conversa` recebe `agora` por parametro: e o que torna a
    janela testavel sem congelar relogio.
    """
    return await encerrar_inativas(ctx["session_factory"], agora=datetime.now(UTC), limite=limite)
```

- [ ] **Step 4: Registrar no worker**

Em `src/mobia/workers/main.py`, acrescente o import junto dos outros sweeps:

```python
from mobia.workers.jobs.sweep_conversas_inativas import sweep_conversas_inativas
```

Na lista `functions`, depois de `sweep_importacoes_travadas`:

```python
        # `keep_result=0` pela mesma razao do `sweep_sla`: o resultado (um
        # `int`) nao serve para nada depois que o log saiu. Entra em
        # `cron_jobs` tambem -- e o relogio que dispara este job, nunca um
        # enqueue manual.
        func(sweep_conversas_inativas, keep_result=0),
```

Na lista `cron_jobs`, ao fim:

```python
        # **Uma vez por dia**, e nao de cinco em cinco minutos como os
        # irmaos acima. A janela desta regra e de TRINTA DIAS: a diferenca
        # entre fechar as 3h e fechar as 3h30 nao existe para ninguem, e a
        # consulta agrega `messages` INTEIRA -- nao uma fila curta como a da
        # `sweep_stalled` --, entao cada passagem e cara. Rodar de hora em
        # hora multiplicaria esse custo por 24 para antecipar um registro que
        # ninguem le em tempo real.
        #
        # **E o atraso e inofensivo por construcao** (D3 do desenho): quem
        # impede a transcricao velha de entrar no prompt e o turno, pelo
        # relogio, nao este cron. Uma passagem perdida atrasa a escrituracao,
        # nunca o comportamento.
        #
        # As 3h da manha, horario do runner: e quando a fila de
        # `process_message` esta mais vazia, e esta varredura toma locks em
        # `conversas`.
        cron(sweep_conversas_inativas, hour={3}, minute={0}, run_at_startup=False),
```

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_encerrar_inativas.py -v --tb=short
```

Esperado: 7 passed.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/workers/jobs/sweep_conversas_inativas.py src/mobia/workers/main.py \
        tests/integration/test_encerrar_inativas.py
git commit -m "feat(TEC-130): a varredura de conversas inativas entra no worker, uma vez por dia"
```

---

### Task 4: Opt-out encerra a conversa

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (bloco `if pedido_de_optout:`, hoje em `turno.py:1325`)
- Test: `tests/integration/test_turno_optout.py` (acrescenta dois testes ao arquivo que já existe)

**Interfaces:**
- Consumes: `MotivoDoEncerramento.OPTOUT` (Task 1), `encerrar_conversa` (já existe).
- Produces: nada que outra tarefa consuma.

> **Os testes vão no arquivo existente, e não num arquivo novo.** `test_turno_optout.py` já tem `_mensagem_gravada`, as constantes `CANAL`/`CONVERSA` e as cinco fixtures de dublê que um turno de opt-out precisa. Um arquivo novo duplicaria tudo isso para afirmar uma coluna.

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/integration/test_turno_optout.py`:

```python
async def test_pedido_de_optout_encerra_a_conversa_com_motivo_proprio(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """TEC-130: o opt-out passa a fechar a conversa, com data e motivo.

    **So escrituracao.** Quem cala o agente e `esta_em_optout`, cujo portao
    roda antes do bloco da reabertura -- `MotivoDoEncerramento.OPTOUT` nao
    entra em `silencia_o_agente`, de proposito. Isto existe para a conversa
    ter registro, que e o que a RN-02.3 pede.
    """
    mensagem = await _mensagem_gravada(session, texto="parar")

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=moderador_fake(),
        agendador=AgendadorNoop(),
    )

    assert resultado == "opt_out"
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.motivo_do_encerramento, Conversa.encerrada_em).where(
                Conversa.channel == CANAL,
                Conversa.conversation_key == CONVERSA,
            )
        )
    ).one()
    assert linha.status == Status.ENCERRADA
    assert linha.motivo_do_encerramento == MotivoDoEncerramento.OPTOUT
    assert linha.encerrada_em is not None


async def test_lead_em_optout_que_volta_nao_reabre_a_conversa(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """**A ordem dos portoes em `turno.py`, afirmada.**

    `esta_em_optout` devolve cedo, la em cima, ANTES do bloco que reabre. Se
    algum dia a reabertura subir para antes dele, este teste reprova -- e o
    defeito seria grave: a conversa de quem pediu para sair voltaria a ATIVA
    e sumiria de qualquer relatorio de opt-out.
    """
    primeira = await _mensagem_gravada(session, texto="parar")
    await executar_turno(
        get_sessionmaker(),
        message=primeira,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=moderador_fake(),
        agendador=AgendadorNoop(),
    )

    segunda = await _mensagem_gravada(session, texto="mudei de ideia, quero ver apartamento")
    await executar_turno(
        get_sessionmaker(),
        message=segunda,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=moderador_fake(),
        agendador=AgendadorNoop(),
    )

    linha = (
        await session.execute(
            select(Conversa.status, Conversa.motivo_do_encerramento).where(
                Conversa.channel == CANAL,
                Conversa.conversation_key == CONVERSA,
            )
        )
    ).one()
    assert linha.status == Status.ENCERRADA
    assert linha.motivo_do_encerramento == MotivoDoEncerramento.OPTOUT
```

Acrescente ao topo do arquivo, junto dos imports que já existem lá:

```python
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
```

`select`, `executar_turno`, `get_sessionmaker` e `AgendadorNoop` o arquivo já importa.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_optout.py -v --tb=short
```

Esperado: os dois testes novos falham com `sqlalchemy.exc.NoResultFound`, porque não existe linha em `conversas`. Os que já existiam continuam passando.

- [ ] **Step 3: Encerrar no bloco de opt-out**

Em `src/mobia/domain/agente/turno.py`, logo **depois** da chamada de `registrar_optout` e **antes** de `desfecho_da_confirmacao = await _entregar_texto_fixo(...)`:

```python
        # **Escrituracao, nao silencio** (TEC-130, D6). Quem cala e
        # `esta_em_optout`, no portao la em cima; `MotivoDoEncerramento.OPTOUT`
        # nao entra em `silencia_o_agente`, de proposito. Isto aqui existe
        # para a conversa ter data e motivo, que e o que a RN-02.3 pede.
        #
        # **Sao duas transacoes, e a ordem importa.** `registrar_optout` abre
        # e commita a propria sessao; `encerrar_conversa` recebe a sessao e
        # deixa o commit para quem chama -- nao ha como junta-las sem mudar a
        # assinatura de uma das duas. O opt-out vai primeiro pelo mesmo
        # argumento que o comentario acima usa para grava-lo antes da
        # entrega: morrer entre as duas deixa o lead em opt-out com a conversa
        # ainda ATIVA -- registro de menos, nunca mensagem a mais. A varredura
        # diaria fecha essa conversa por INATIVIDADE 30 dias depois, com o
        # motivo menos preciso; e o custo aceito.
        async with session_factory() as sessao_do_encerramento:
            await encerrar_conversa(
                sessao_do_encerramento,
                channel=message.channel,
                conversation_key=message.conversation_key,
                motivo=str(MotivoDoEncerramento.OPTOUT),
                agora=datetime.now(UTC),
            )
            await sessao_do_encerramento.commit()
```

Acrescente `MotivoDoEncerramento` ao import que já traz `encerrar_conversa` de `mobia.domain.conversa`.

- [ ] **Step 4: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_optout.py -v --tb=short
```

Esperado: tudo passa, os antigos junto com os dois novos. **Os antigos importam tanto quanto os novos** — são eles que afirmam que o turno de opt-out continua não pagando o classificador e moderando exatamente uma vez.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/agente/turno.py tests/integration/test_turno_optout.py
git commit -m "feat(TEC-130): o pedido de opt-out passa a encerrar a conversa com motivo proprio"
```

---

### Task 5: A dobra forçada em `montar_contexto`

> **Emenda P-01 (revisão final, 23/09/2026) — dois trechos desta task não valem mais, e um terceiro mudou de lugar.** Este plano é versionado e o cabeçalho instrui um worker agêntico a implementá-lo passo a passo; o que segue abaixo continua registrando o que se fez no dia 22, mas não pode ser seguido ao pé da letra.
>
> 1. **O piso da dobra forçada é 1, não 0.** O Step 3 manda escrever `minimas = 0 if dobrar_tudo else ...`, com um comentário afirmando que "a fala deste turno não está nesta lista". **É falso**: a ingestão commita a linha em `messages` antes de enfileirar o job — o job recebe o `message_id` —, então a fala do turno está sempre em `literais`. Com `minimas=0` ela ia para o resumo junto com a conversa velha e o modelo respondia a uma paráfrase da própria pergunta. Escreva `minimas = 1 if dobrar_tudo else settings.contexto_literais_minimas`. A razão por extenso está na **D4 do desenho**, que foi emendada para refutar a premissa que autorizou o piso zero.
> 2. **`assert montado.literais == []`, no Step 1, não vale.** Decorre do mesmo erro: com o piso correto sobra exatamente a fala do turno. O teste afirma `[m.id for m in montado.literais] == [id_da_fala_do_turno]`.
> 3. **O gatilho mudou de lugar, e o parâmetro `forcar_dobra` não existe mais.** O Step 4 e toda a Task 6 punham a decisão no turno, ligada por `e_conversa_nova(message)` — que numa rajada de volta devolve `False` justamente na reabertura, porque quem carrega o turno é a mensagem mais nova do lote e ela enxerga a irmã de segundos atrás. `montar_contexto` decide sozinha, pelos próprios literais (`_reabriu_depois_do_silencio`). Ver a **Emenda D4-a do desenho**.

**Files:**
- Modify: `src/mobia/domain/context/montagem.py` (`montar_contexto` em `:468`, `_dobrar` em `:694`)
- Test: `tests/integration/test_dobra_na_reabertura.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `montar_contexto(..., forcar_dobra: bool = False)` — parâmetro keyword-only, default `False`. A Task 6 o liga.

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_dobra_na_reabertura.py`:

```python
"""A dobra forcada: a conversa nova ve o resumo, nunca a transcricao. TEC-130, D4.

**A fronteira e a marca do resumo**, e nao uma coluna nova nem um filtro por
`encerrada_em`: dobrando tudo o que ficou para tras, a marca passa a cobrir a
conversa anterior inteira e `literais_apos` devolve so o que e novo.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker


class _ResumidorFalso:
    """Devolve um texto fixo e registra o que lhe pediram para dobrar."""

    def __init__(self) -> None:
        self.conteudos: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.conteudos.append(conteudo)
        return ResumoGerado(
            texto="Lead procurava apartamento de dois quartos na zona sul.",
            modelo="falso",
            tokens_in=10,
            tokens_out=10,
            latency_ms=1,
        )


class _ResumidorQuebrado:
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        raise RuntimeError("provedor fora do ar")


class _ContadorFalso:
    async def contar(self, texto: str) -> int:
        return 10


async def _semear_conversa(session: AsyncSession, chave: str, quantas: int) -> None:
    """Uma conversa velha, alternando lead e agente.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL. `text_body` fica nulo: `_texto_das` (em `montagem.py`) lida com
    isso, e o que este teste afirma e sobre QUANTAS mensagens sobram, nao
    sobre o que elas diziam.
    """
    base = datetime.now(UTC) - timedelta(days=60)
    for n in range(quantas):
        do_lead = n % 2 == 0
        session.add(
            Message(
                id=uuid.uuid4(),
                channel="whatsapp",
                conversation_key=chave,
                role=MessageRole.LEAD if do_lead else MessageRole.AGENTE,
                direction=(
                    MessageDirection.INBOUND if do_lead else MessageDirection.OUTBOUND
                ),
                content_type=MessageContentType.TEXTO,
                created_at=base + timedelta(minutes=n),
            )
        )
    await session.commit()


@pytest.mark.usefixtures("banco_limpo")
async def test_a_dobra_forcada_nao_deixa_literal_nenhum(session: AsyncSession) -> None:
    """**O criterio da card ao pe da letra**: por meio do resumo, nao pela
    transcricao inteira.

    Cinco mensagens ficam MUITO abaixo do gatilho de regeneracao (40) e do
    piso de literais (20) -- sem a dobra forcada, as cinco iriam inteiras
    para o prompt da conversa nova.
    """
    await _semear_conversa(session, "lead-reabre", quantas=5)
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-reabre",
        resumidor=resumidor,
        contador=_ContadorFalso(),
        forcar_dobra=True,
    )

    assert montado.literais == []
    assert montado.resumo is not None
    assert len(resumidor.conteudos) == 1


@pytest.mark.usefixtures("banco_limpo")
async def test_sem_a_flag_o_piso_preserva_os_literais(session: AsyncSession) -> None:
    """A contraprova: o comportamento de sempre nao mudou."""
    await _semear_conversa(session, "lead-normal", quantas=5)
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-normal",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert len(montado.literais) == 5
    assert resumidor.conteudos == []


@pytest.mark.usefixtures("banco_limpo")
async def test_resumo_falho_degrada_e_nao_mata_o_turno(session: AsyncSession) -> None:
    """**A degradacao declarada da D4.**

    Perder resumo E literais deixaria o agente cego diante de um lead que ele
    ja atendeu. Ver demais e menos ruim que nao ver nada -- entao os literais
    voltam, e o warning denuncia.
    """
    await _semear_conversa(session, "lead-quebrado", quantas=5)

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-quebrado",
        resumidor=_ResumidorQuebrado(),
        contador=_ContadorFalso(),
        forcar_dobra=True,
    )

    assert len(montado.literais) == 5
```

> Os campos de `ContextoMontado` são `sistema`, `resumo`, `literais` e `estado` — conferidos em `843481f`. Se algum tiver mudado de nome, ajuste o teste, nunca o dataclass.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_dobra_na_reabertura.py -v --tb=short
```

Esperado: FAIL com `TypeError: montar_contexto() got an unexpected keyword argument 'forcar_dobra'`.

- [ ] **Step 3: `_dobrar` aprende a dobrar tudo**

Em `_dobrar`, troque a assinatura do keyword-only para incluir `dobrar_tudo`:

```python
    *,
    piso_pode_ceder: bool = False,
    dobrar_tudo: bool = False,
```

e, no ramo que chama `dividir`, troque:

```python
        a_dobrar, a_manter = dividir(
            literais, settings.contexto_literais_minimas, piso_pode_ceder=piso_pode_ceder
        )
```

por:

```python
        # `minimas=0` faz `dividir` devolver tudo para dobrar e nada para
        # manter -- e o que apaga a transcricao da conversa anterior sem
        # perde-la, porque ela vai inteira para o resumo. Ver a D4 da TEC-130.
        #
        # **`dobrar_tudo` nao e `piso_pode_ceder`.** Aquele cede o piso para
        # UMA mensagem, por causa do estouro de teto, e a mais recente tem de
        # sobrar porque e a fala a que o modelo responde. Aqui nenhuma tem de
        # sobrar: a fala deste turno nao esta nesta lista (o turno a grava e
        # `montar_contexto` nao a inclui), entao dobrar tudo nao deixa o turno
        # sem pergunta.
        minimas = 0 if dobrar_tudo else settings.contexto_literais_minimas
        a_dobrar, a_manter = dividir(literais, minimas, piso_pode_ceder=piso_pode_ceder)
```

- [ ] **Step 4: `montar_contexto` ganha o parâmetro**

Acrescente à assinatura, no bloco keyword-only:

```python
    forcar_dobra: bool = False,
```

e troque o gatilho:

```python
            if deve_regenerar(len(literais), settings.contexto_gatilho_de_regeneracao):
```

por:

```python
            # `forcar_dobra` passa por cima do gatilho de acumulo: a conversa
            # que reabre pode ter cinco mensagens, muito abaixo das 40, e e
            # justamente essas cinco que nao podem chegar ao prompt da
            # conversa nova (TEC-130, D4).
            if forcar_dobra or deve_regenerar(
                len(literais), settings.contexto_gatilho_de_regeneracao
            ):
                texto_do_resumo, literais, cobertas, marca_atual, falhou = await _dobrar(
                    session_factory,
                    channel,
                    conversation_key,
                    resumidor,
                    texto_do_resumo,
                    literais,
                    cobertas,
                    marca_atual,
                    INSTRUCAO_DOBRAR,
                    dobrar_tudo=forcar_dobra,
                )
                degradado = degradado or falhou
                if forcar_dobra and falhou:
                    # Alarme proprio, e nao so o `contexto.degradado` que
                    # `_dobrar` ja emite: aqui a degradacao tem consequencia
                    # que ela nao tem no caso normal -- a transcricao da
                    # conversa ANTERIOR volta ao prompt, que e exatamente o
                    # que esta card impede. Quem investiga precisa separar os
                    # dois casos pelo nome, nao pela correlacao de horario.
                    log.warning(
                        "contexto.dobra_forcada_falhou",
                        channel=channel,
                        literais=len(literais),
                    )
```

Substitua o comentário `# Gatilho por acumulo: ...` que fica logo acima, pois ele passou a descrever só metade da condição.

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_dobra_na_reabertura.py -v --tb=short
```

Esperado: 3 passed.

- [ ] **Step 6: Rodar a vizinhança inteira do contexto**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py tests/unit -k "contexto or montagem or janela or resumo" --tb=short -q
```

`test_montagem.py` é um dos arquivos que flakeiam sob carga com `ConnectionResetError`. Se falhar, rode o arquivo sozinho antes de concluir qualquer coisa.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/context/montagem.py tests/integration/test_dobra_na_reabertura.py
git commit -m "feat(TEC-130): a montagem aprende a dobrar o historico inteiro, sem piso"
```

---

### Task 6: O turno liga a dobra quando a conversa é nova

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (a chamada de `montar_contexto`, hoje em `:1690`; o comentário da reabertura em `:1288-1292`)
- Test: `tests/integration/test_dobra_na_reabertura.py` (acrescenta ao arquivo da Task 5)

**Interfaces:**
- Consumes: `montar_contexto(..., forcar_dobra=...)` (Task 5), `e_conversa_nova` (já existe).
- Produces: nada.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_dobra_na_reabertura.py`. Este usa a fixture `rodar_turno` de `tests/conftest.py`, que semeia a entrada e executa `executar_turno` inteiro — e as constantes `CANAL_AGENTE` / `CONVERSA_AGENTE` de lá, que são o par que aquela fixture usa:

```python
async def test_o_turno_de_uma_conversa_velha_nao_leva_a_transcricao_dela(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    contador_fake,
    rodar_turno,
) -> None:
    """**O cenario Gherkin da card, ponta a ponta.**

    "Dada uma conversa encerrada por inatividade de um lead que buscava
    apartamento na zona sul, quando esse lead envia uma nova mensagem, entao
    uma nova conversa e criada para o mesmo lead e o resumo da conversa
    anterior esta disponivel para o agente."

    Cinco mensagens de 60 dias atras ficam MUITO abaixo do gatilho de
    regeneracao (40) e do piso de literais (20): sem a dobra forcada elas
    iriam inteiras para o prompt deste turno.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]

    from mobia.domain.context.janela import literais_apos, marca_de
    from mobia.domain.context.repositorio import ler_resumo

    await _semear_conversa(session, CONVERSA_AGENTE, quantas=5)
    resumidor = _ResumidorFalso()

    resultado = await rodar_turno(
        session, classificador_fake(), outbound_fake(), resumidor, contador_fake()
    )

    assert resultado == "respondido"
    # A dobra rodou, e uma vez so.
    assert len(resumidor.conteudos) == 1

    async with get_sessionmaker()() as leitura:
        resumo = await ler_resumo(leitura, CANAL_AGENTE, CONVERSA_AGENTE)
        assert resumo is not None
        sobraram = await literais_apos(
            leitura, CANAL_AGENTE, CONVERSA_AGENTE, marca_de(resumo)
        )

    # **O criterio da card**: nenhuma das cinco falas velhas esta atras da
    # marca. O que sobrou e deste turno -- a fala do lead e a resposta do
    # agente --, nunca da conversa anterior.
    velhas = {m.id for m in sobraram if m.created_at < resumo.watermark_created_at}
    assert velhas == set()
```

> `_semear_conversa` recebia o `chave` como parâmetro nos testes da Task 5; aqui ele tem de ser `CONVERSA_AGENTE`, porque é o par que `rodar_turno` usa para gravar a entrada. Semear em outra chave faria o turno montar contexto de uma conversa vazia e o teste passaria por engano.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_dobra_na_reabertura.py -v --tb=short
```

Esperado: FAIL — as 5 mensagens antigas continuam literais, porque o turno ainda não liga a flag.

- [ ] **Step 3: Ligar a flag antes de montar**

Imediatamente antes da chamada de `montar_contexto` (`turno.py:1690`), calcule:

```python
    # **O relogio, e nao o `status`** (TEC-130, D3). Esta e a conversa nova
    # da RN-02.3, e ela tem de ser reconhecida mesmo que a varredura diaria
    # ainda nao tenha passado -- senao um cron atrasado poe a transcricao da
    # conversa anterior no prompt, em silencio.
    #
    # **Custo declarado: uma consulta a mais por turno.** `e_conversa_nova` ja
    # e chamada mais abaixo, para decidir a apresentacao, e o resultado NAO e
    # reaproveitado. Os dois pontos estao na mesma funcao -- entao a barreira
    # nao e assinatura --, mas esta chamada mora dentro de um bloco aninhado
    # que nao domina aquelas: hoistar um unico valor exigiria provar que este
    # bloco roda em TODO caminho que chega la, sob pena de `UnboundLocalError`
    # num ramo raro. Essa prova, dentro de uma funcao de 2800 linhas, e um
    # refactor que esta card nao faz. A consulta usa `ix_messages_timeline`, e
    # o preco de uma leitura indexada e menor que o de errar essa analise.
    # Quando `_executar_turno` for partida, os pontos viram um.
    conversa_nova = await e_conversa_nova(session_factory, message, agora=datetime.now(UTC))
```

e passe `forcar_dobra=conversa_nova` na chamada de `montar_contexto`.

- [ ] **Step 4: Consertar o comentário que a card tornou falso**

Em `turno.py:1288-1292`, o comentário da reabertura afirma **"nao ha job varrendo conversas vencidas"**. Passou a haver. Troque esse trecho por:

```python
            # A REABERTURA mora aqui, e o gatilho dela e a mensagem do lead.
            # **Desde a TEC-130 existe uma varredura diaria**
            # (`sweep_conversas_inativas`) que fecha por INATIVIDADE, mas ela
            # so ESCREVE o encerramento -- nao reabre nada e nao decide
            # contexto. Entre a passagem dela e a mensagem do lead a linha
            # fica dizendo ENCERRADA, e `situacao_da_conversa` ja conta a
            # verdade nesse meio tempo. Chegando aqui o turno SEGUE, e nao
            # devolve.
```

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_dobra_na_reabertura.py -v --tb=short
```

- [ ] **Step 6: Rodar tudo o que toca o turno**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration -k "turno or conversa or apresentacao or contexto" --tb=short -q
```

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/agente/turno.py tests/integration/test_dobra_na_reabertura.py
git commit -m "feat(TEC-130): a conversa nova comeca com o resumo da anterior, nunca com a transcricao"
```

---

### Task 7: A Emenda E-03 ao SRS, e a listagem de comentários

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (RN-02.3, por volta de `:148`)
- Modify: `src/mobia/domain/conversa/models.py` (docstring de módulo)

**Interfaces:** nenhuma.

> **Por que a docstring de `models.py` está aqui e não na Task 1.** Ela afirma que a card acrescentou dois motivos, dois escritores e a Emenda E-03. As três coisas só passam a ser verdade ao mesmo tempo **neste passo** — a emenda nasce aqui. Escrevê-la na Task 1 punha no repo, por seis commits, uma docstring que nomeava uma função, um bloco de código e uma emenda de SRS inexistentes. Foi o que a revisão da Task 1 pegou.

- [ ] **Step 1: Escrever a emenda**

Acrescente como item aninhado **abaixo** da Emenda E-02 da RN-02.3 — **nunca reescrevendo** o texto de 22/08/2026 nem o das emendas anteriores:

```markdown
  - **Emenda E-03 (TEC-130, 22/09/2026):** esta regra ganhou implementação, e em três pontos ela diverge do que a card pedia. **(1) Concluir o handoff não encerra a conversa**, e o cenário Gherkin da TEC-130 que pedia isso foi descartado — a Emenda E-01 acima já havia decidido a separação, e sob esta card ela passou a ter uma consequência que não tinha em 13/09: o encerramento agora dobra o histórico no resumo, então encerrar ao concluir faria o lead que o corretor acabou de atender voltar a um agente sem a transcrição daquele atendimento. **(2) Os motivos de encerramento passam a ser três:** `FORA_DE_ESCOPO` (RN-03.5), `INATIVIDADE` e `OPTOUT` — nenhum dos dois novos herda a janela de 30 dias de silêncio, que continua sendo política do primeiro. **(3) O encerramento por inatividade conta a partir da última fala do lead** (`INBOUND`), não da última mensagem de qualquer direção: o follow-up automático da RN-13.1 dispara até 14 dias depois do sumiço, e contar OUTBOUND faria o próprio sistema adiar o encerramento de quem já tinha ido embora. A promessa *"com acesso ao histórico anterior via resumo"* passou a ser verdade por construção — a primeira mensagem depois do encerramento dobra o histórico no resumo antes de montar o contexto, então a conversa nova recebe o resumo da anterior e nenhuma linha da transcrição dela. **Lacuna declarada:** não nasceu identidade por conversa; `Lead 1:N Conversa`, no modelo de dados da seção 8, continua sendo o diagrama e não o esquema — não há como listar nem contar as conversas anteriores de um lead. Ver `docs/superpowers/specs/2026-09-22-tec-130-encerrar-por-inatividade-design.md`.
```

- [ ] **Step 2: Atualizar a docstring de `conversa/models.py`**

Ela ainda diz que o encerramento por inatividade é "uma regra do SRS sem implementacao, reservada para a TEC-130", e que a card "ESTENDE isto, nao cria" no futuro. Com a emenda do Step 1 escrita, as duas frases passaram a ser passado. Substitua os **dois** parágrafos — o que começa em `**Esta tabela e a entidade que este sistema nao tinha.**` mantém-se; os que começam em `**Consequencia para quem pegar a TEC-130:**` e `**E o que se ganha com o motivo novo...**` saem — por:

```python
**A TEC-130 estendeu isto, e nao criou nada.** Ela acrescentou `INATIVIDADE` e
`OPTOUT` ao vocabulario de `vocabulario.py`, mais dois escritores -- a varredura
diaria (`encerrar_inativas`, neste modulo) e o bloco de opt-out do turno.
Nenhuma tabela nova, nenhuma segunda nocao de encerrado, e nenhuma migration: a
coluna ja comportava os dois literais. A Emenda E-02 da RN-02.3 previa a
extensao e nomeava `INATIVIDADE`; `OPTOUT` foi decisao desta card, e a Emenda
E-03 registra as duas.

**O que ela NAO trouxe e a janela de silencio.** Os 30 dias em que o agente nao
responde continuam sendo politica da RN-03.5, e
`SituacaoDaConversa.silencia_o_agente` continua exigindo `FORA_DE_ESCOPO`. Uma
conversa fechada por inatividade e respondida na mensagem seguinte -- que e o
que a RN-02.3 pede, e o motivo de o reengajamento existir.
```

> A frase sobre a E-02 diz **qual** dos dois motivos ela previa. A E-02 nomeia só `INATIVIDADE`; dizer que ela "previa exatamente isso" sobre os dois seria impreciso, e foi um achado Minor da revisão da Task 1.

- [ ] **Step 3: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`, e **resolva todo `FALSO`** — `FALSO` é a única marca que afirma em vez de suspeitar. Esta branch mexeu em prosa que cita arquivo e linha (`identificacao.py`, `conversa/models.py`, `vocabulario.py`, o `CLAUDE.md` não), então espere achados.

- [ ] **Step 4: Conferir que o `CLAUDE.md` não ficou falso**

```bash
grep -n "TEC-130\|encerr" CLAUDE.md
```

Se alguma frase do `CLAUDE.md` afirmar algo que esta card mudou, corrija junto — o arquivo é lido por todo agente que abrir o repo.

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md src/mobia/domain/conversa/models.py
git commit -m "docs(TEC-130): a E-03 da RN-02.3 registra o handoff descartado e os tres motivos"
```

---

## Verificação final

- [ ] **Os três gates, nesta ordem:**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **A suíte inteira, UMA vez.** Guarde o hash junto com o resultado.

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — o `-n 8` derruba o Postgres desta máquina em alguns dias. Rode por blocos:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/features --tb=short -q
```

A segunda execução só existe se a primeira **falhar** — é o que separa flake de regressão.

- [ ] **A listagem de comentários, com zero `FALSO`:**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

- [ ] **Push e PR contra `main`.** Não há opção de merge local nem de deixar a branch parada.

- [ ] **Comentar na card e movê-la para "Em análise"** (não para "Feito" — quem mergeia é que fecha). O comentário registra, no mínimo: o cenário de handoff descartado e por quê; a Emenda E-03; a lacuna de identidade por conversa (D7), que é decisão de produto; o custo declarado da consulta extra por turno (Task 6); e a degradação da dobra forçada (D4), que é um critério de aceite cumprido em espírito e não ao pé da letra.
