# TEC-297 — Moderação dos ramos que retornam cedo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer com que toda fala de entrada com corpo seja moderada exatamente uma vez, qualquer que seja a saída que `executar_turno` tome — hoje cinco returns antecipados passam por fora da moderação e a fala entra no contexto, no resumo, no score e na âncora de follow-up sem nunca ter sido julgada.

**Architecture:** A operação "moderar entrada e marcar" vira uma função de domínio única (`moderar_entrada_e_marcar`), usada pelos três chamadores. `executar_turno` é partida em dois: um invólucro fino que decifra o corpo, constrói um `_ModeracaoDoTurno` e chama `_executar_turno` dentro de um `try/finally`; o `finally` garante a moderação por onde quer que o corpo tenha saído. A moderação acontece **por último**, depois da ação e da entrega de cada ramo, e por isso não encosta em nenhum prazo prometido.

**Tech Stack:** Python 3.13, SQLAlchemy async, `structlog`, `pytest` + `pytest-asyncio`, Postgres e Redis via `docker compose`.

**Spec:** `docs/superpowers/specs/2026-09-21-tec-297-moderacao-dos-ramos-que-retornam-cedo-design.md`

## Global Constraints

- **Base:** `c8b286a`. Branch `feat/tec-297-moderacao-dos-ramos-que-retornam-cedo`, já criada.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceção: valor citado que o lead recebe segue o literal, com acento.
- **Prosa em `docs/`: com acento.**
- **Os três gates, nesta ordem, com este escopo exato:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  `mypy` **sem argumento** — argumento de linha de comando sobrepõe o `files` do `pyproject.toml`.
- **Loop rápido:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, não precisa de `docker compose`).
- **Suíte inteira, UMA vez:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`. Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).
- **Nunca use `-q` sem `--tb=short`:** `-q` joga fora o traceback e a regra é uma execução só.
- **Mensagem de commit:** `tipo(TEC-297): o que passou a ser verdade`, assunto em português sem acento, terminando com:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **A moderação de entrada é fail-open.** Provedor indisponível nunca derruba o turno nem o ramo. Na saída é o oposto; não toque nisso.
- **`marcar_bloqueada` propaga exceção de propósito.** A única exceção a essa regra é o `finally` da Task 5, e ela é local e comentada.
- **Nenhum teste existente pode ser editado**, exceto os dois nomeados na Task 3. Teste que precise de edição fora desses dois é sinal de que a extração mudou comportamento — pare e investigue.

## Estrutura de arquivos

| arquivo | responsabilidade nesta card |
| --- | --- |
| `src/mobia/domain/messages/bloqueio.py` | **modificar** — ganha `moderar_entrada_e_marcar`, ao lado de `marcar_bloqueada` |
| `src/mobia/workers/jobs/process_message.py` | **modificar** — `_moderar_superada` passa a delegar; o comentário 460-469 deixa de ser verdade |
| `src/mobia/domain/agente/turno.py` | **modificar** — invólucro + `_executar_turno` + `_ModeracaoDoTurno`; o bloco 1309-1360 delega; dois comentários de guarda reescritos |
| `tests/unit/test_moderar_entrada_e_marcar.py` | **criar** — a função de domínio, isolada |
| `tests/integration/test_moderacao_dos_ramos_que_retornam.py` | **criar** — os cinco ramos, o resolve-once, a ordem, o fail-open |
| `tests/integration/test_conversa_encerrada.py` | **modificar** — os dois únicos testes que esta card tem permissão de editar |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | **modificar** — RN-04.5 E-03 e RN-02.2 E-01 |
| `docs/superpowers/specs/2026-09-16-tec-138-encerrar-fora-de-escopo-design.md` | **modificar** — adendo abaixo da D7 |

---

### Task 1: A função de domínio `moderar_entrada_e_marcar`

**Files:**
- Modify: `src/mobia/domain/messages/bloqueio.py`
- Test: `tests/unit/test_moderar_entrada_e_marcar.py` (criar)

**Interfaces:**
- Consumes: `marcar_bloqueada` (mesmo módulo), `ModeradorPort`, `Direcao`, `Veredito`, `ModeracaoIndisponivel`, `CATEGORIA_OUTRO` (de `mobia.domain.moderacao.port`).
- Produces: `moderar_entrada_e_marcar(session_factory, moderador, *, message_id: UUID, channel: str, conversation_key: str, corpo: str) -> Veredito | None`. Devolve `None` **somente** quando o provedor está indisponível. Devolve o `Veredito` nos outros dois casos, e já chamou `marcar_bloqueada` quando `veredito.bloqueado`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_moderar_entrada_e_marcar.py`:

```python
"""A funcao que modera a entrada e marca, isolada dos tres chamadores.

Unitario e nao integracao: o que se prova aqui e a sequencia de decisoes --
fail-open devolve None, liberado nao marca, bloqueado marca com a categoria
certa. Quem grava e `marcar_bloqueada`, que ja tem cobertura propria de
integracao; aqui ela e um espiao, porque o ponto e QUANDO ela e chamada.
"""

from uuid import uuid4

import pytest

from mobia.domain.messages import bloqueio
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    Veredito,
)


class _ModeradorFalso:
    def __init__(self, veredito=None, erro=None):
        self._veredito = veredito
        self._erro = erro
        self.chamadas: list = []

    async def moderar(self, texto, *, direcao):
        self.chamadas.append((texto, direcao))
        if self._erro is not None:
            raise self._erro
        return self._veredito


@pytest.fixture
def espiao_de_marca(monkeypatch):
    """Substitui `marcar_bloqueada` no modulo por um espiao que registra."""
    chamadas: list = []

    async def espiao(session_factory, message_id, *, channel, conversation_key, categoria):
        chamadas.append(
            {
                "message_id": message_id,
                "channel": channel,
                "conversation_key": conversation_key,
                "categoria": categoria,
            }
        )

    monkeypatch.setattr(bloqueio, "marcar_bloqueada", espiao)
    return chamadas


async def _chamar(moderador, corpo="qualquer coisa"):
    return await bloqueio.moderar_entrada_e_marcar(
        None,
        moderador,
        message_id=uuid4(),
        channel="whatsapp",
        conversation_key="conversa-1",
        corpo=corpo,
    )


async def test_provedor_indisponivel_devolve_none_e_nao_marca(espiao_de_marca) -> None:
    """Fail-open: `None` e o unico valor que diz "nao deu para moderar".

    Devolver um `Veredito(bloqueado=False)` aqui seria transformar um
    moderador caido num moderador que libera, que e exatamente o que o
    `ModeracaoIndisponivel` existe para impedir.
    """
    moderador = _ModeradorFalso(erro=ModeracaoIndisponivel("provedor fora"))

    assert await _chamar(moderador) is None
    assert espiao_de_marca == []


async def test_liberado_devolve_o_veredito_e_nao_marca(espiao_de_marca) -> None:
    moderador = _ModeradorFalso(Veredito(bloqueado=False, motivo="ok"))

    veredito = await _chamar(moderador)

    assert veredito is not None
    assert veredito.bloqueado is False
    assert espiao_de_marca == []


async def test_bloqueado_marca_com_a_categoria_do_veredito(espiao_de_marca) -> None:
    moderador = _ModeradorFalso(
        Veredito(bloqueado=True, motivo="discurso", categoria="DISCRIMINACAO")
    )

    veredito = await _chamar(moderador)

    assert veredito is not None and veredito.bloqueado is True
    assert len(espiao_de_marca) == 1
    assert espiao_de_marca[0]["categoria"] == "DISCRIMINACAO"
    assert espiao_de_marca[0]["channel"] == "whatsapp"
    assert espiao_de_marca[0]["conversation_key"] == "conversa-1"


async def test_bloqueado_sem_categoria_cai_no_outro(espiao_de_marca) -> None:
    """`ModeradorPort` e um Protocol: um adaptador futuro pode devolver
    bloqueado sem categoria, e a coluna e `not null`. A alternativa seria a
    marca estourar por causa de um campo de auditoria.
    """
    moderador = _ModeradorFalso(Veredito(bloqueado=True, motivo="sem categoria"))

    await _chamar(moderador)

    assert espiao_de_marca[0]["categoria"] == CATEGORIA_OUTRO


async def test_modera_com_direcao_de_entrada_e_so_o_corpo() -> None:
    """A direcao nao e parametro de quem chama: esta funcao e so de ENTRADA.

    E o moderador recebe o corpo e nada mais -- nenhum contexto, nenhum
    identificador. Um refactor que passasse a conversa inteira mudaria o que
    o provedor julga sem que nenhuma assercao de comportamento reclamasse.
    """
    moderador = _ModeradorFalso(Veredito(bloqueado=False, motivo="ok"))

    await _chamar(moderador, corpo="o texto exato")

    assert moderador.chamadas == [("o texto exato", Direcao.ENTRADA)]
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_moderar_entrada_e_marcar.py --tb=short
```

Esperado: 5 falhas, `AttributeError: module 'mobia.domain.messages.bloqueio' has no attribute 'moderar_entrada_e_marcar'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/messages/bloqueio.py`, acrescente ao topo:

```python
import structlog

from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
    Veredito,
)

log = structlog.get_logger(__name__)
```

(`Direcao` já é importado — não duplique a linha; acrescente os outros nomes ao import existente.)

E, **depois** de `marcar_bloqueada` e antes de `registrar_bloqueio_de_saida`:

```python
async def moderar_entrada_e_marcar(
    session_factory: async_sessionmaker[AsyncSession],
    moderador: ModeradorPort,
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
    corpo: str,
) -> Veredito | None:
    """Modera a fala de entrada e, se reprovada, marca e audita num commit so.

    **Devolve `None` somente quando o provedor esta indisponivel.** Fail-open,
    a assimetria que `domain/moderacao/port.py` documenta: a fala do lead ja
    esta cifrada no banco, e negar atendimento a lead legitimo porque um
    servico caiu pune o inocente. `None` e nao `Veredito(bloqueado=False)`
    porque "nao deu para moderar" nao e "moderou e liberou", e quem chama
    precisa poder distinguir.

    **Nao entrega recusa nenhuma.** Quem chama decide se ha texto a mandar: o
    turno entrega a recusa de entrada, o caminho do agrupado e os cinco ramos
    que retornam cedo nao entregam nada (TEC-297, D2).

    Os tres chamadores sao `executar_turno`, o `finally` do invulucro dele e
    `_moderar_superada` no worker. Antes da TEC-297 a sequencia abaixo estava
    escrita duas vezes, e a segunda copia nasceu na TEC-295.
    """
    try:
        veredito = await moderador.moderar(corpo, direcao=Direcao.ENTRADA)
    except ModeracaoIndisponivel as exc:
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.ENTRADA.value,
            message_id=str(message_id),
            reason=str(exc),
        )
        return None

    if not veredito.bloqueado:
        return veredito

    # `error` e nao `warning`: e o nivel que o alerta observa, pelo mesmo
    # criterio de `outbound.recusado`. O texto julgado **nao** entra no log --
    # e fala do lead, coberta pela regra de PII.
    log.error(
        "moderacao.entrada_bloqueada",
        message_id=str(message_id),
        motivo=veredito.motivo,
        categoria=veredito.categoria,
    )
    # Se a marca falhar, a excecao sobe -- ver o topo deste modulo. A unica
    # excecao e o `finally` do invulucro do turno, que engole com a excecao do
    # turno em voo para nao mascarar a causa real (TEC-297, D5).
    await marcar_bloqueada(
        session_factory,
        message_id,
        channel=channel,
        conversation_key=conversation_key,
        categoria=veredito.categoria or CATEGORIA_OUTRO,
    )
    return veredito
```

- [ ] **Step 4: Rodar para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_moderar_entrada_e_marcar.py --tb=short
```

Esperado: 5 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/bloqueio.py tests/unit/test_moderar_entrada_e_marcar.py
git commit -F - <<'EOF'
feat(TEC-297): moderar entrada e marcar passa a ser uma funcao so

A sequencia moderar -> fail-open -> logar -> `marcar_bloqueada` estava
escrita duas vezes, e a segunda copia nasceu na TEC-295. Os cinco ramos
que retornam cedo precisariam de uma terceira.

Devolve `None` so quando o provedor esta indisponivel, e nao um veredito
liberado: "nao deu para moderar" nao e "moderou e liberou".

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Os dois chamadores existentes passam a delegar

Refatoração pura. **Nenhum teste muda e nenhum teste novo nasce** — o que prova esta task é a suíte existente continuar verde.

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py` (`_moderar_superada`, 306-367)
- Modify: `src/mobia/domain/agente/turno.py` (bloco 1309-1360)

**Interfaces:**
- Consumes: `moderar_entrada_e_marcar` da Task 1.
- Produces: nada novo. `_moderar_superada` mantém a assinatura e o retorno `bool`.

- [ ] **Step 1: `_moderar_superada` delega**

Em `process_message.py`, troque o corpo de `_moderar_superada` (do `try:` até o `return True`) por:

```python
    veredito = await moderar_entrada_e_marcar(
        session_factory,
        moderador,
        message_id=linha.id,
        channel=linha.channel,
        conversation_key=linha.conversation_key,
        corpo=corpo,
    )
    # `None` e indisponibilidade, `bloqueado=False` e liberado -- os dois
    # fecham "agrupado" do mesmo jeito, e a diferenca ja foi logada dentro.
    return veredito is not None and veredito.bloqueado
```

Acrescente o import: `from mobia.domain.messages.bloqueio import moderar_entrada_e_marcar`. Remova os imports que ficaram sem uso (`Direcao`, `ModeracaoIndisponivel`, `CATEGORIA_OUTRO`, `marcar_bloqueada`) **somente se** nada mais no arquivo os usa — confira com `grep -n` antes de apagar cada um.

Preserve a docstring de `_moderar_superada` (313-333), ajustando a parte que descreve a sequência agora delegada. O parágrafo sobre por que é fail-open **fica**: ele explica a decisão daquele chamador, não a mecânica.

- [ ] **Step 2: O bloco do turno delega**

Em `turno.py`, o bloco `if corpo:` (1309 em diante) passa a:

```python
    if corpo:
        veredito = await moderar_entrada_e_marcar(
            session_factory,
            moderador,
            message_id=message.id,
            channel=message.channel,
            conversation_key=message.conversation_key,
            corpo=corpo,
        )
        if veredito is not None and veredito.bloqueado:
            <o resto do bloco de hoje, do comentario da TEC-295/D4 em diante,
             sem alteracao: `ha_fala_pendente_antes`, `_entregar_texto_fixo`
             com `KIND_DA_RECUSA_DE_ENTRADA`, os dois guards de return e o
             `log.info("moderacao.recusa_com_resposta_pendente", ...)`>
```

Os comentários que saem junto com o código que saiu — o de fail-open (1313-1317), o de `error` e não `warning` (1326-1328), o da marca antes da entrega (1334-1353) — **vão para a docstring e para os comentários da função da Task 1**, onde o código deles agora mora. Não os apague: eles são o porquê, e o porquê não mudou de verdade, mudou de arquivo.

O comentário da TEC-142 sobre `categoria or CATEGORIA_OUTRO` também vai para a função da Task 1 (já está no código da Task 1, Step 3).

- [ ] **Step 3: Rodar os testes que cobrem os dois caminhos**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py tests/integration/test_moderacao_na_rajada.py tests/integration/test_rajada.py --tb=short
```

Esperado: todos passam, **sem editar nenhum**. Se algum falhar, a refatoração mudou comportamento — pare e compare com `git stash`.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/workers/jobs/process_message.py src/mobia/domain/agente/turno.py
git commit -F - <<'EOF'
refactor(TEC-297): os dois chamadores da moderacao de entrada delegam

Sem mudanca de comportamento: o que prova esta mudanca e a suite existente
continuar verde sem nenhuma edicao de teste.

Os comentarios que justificavam fail-open, o nivel do log e a marca antes
da entrega foram para `moderar_entrada_e_marcar`, onde o codigo deles
passou a morar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: O invólucro, o `_ModeracaoDoTurno` e a reversão da TEC-138

Esta task muda comportamento nos cinco ramos de uma vez — não há como fazer um ramo por vez, porque o `finally` cobre todos. Por isso ela inclui a edição dos dois testes da TEC-138, sem a qual a suíte fica vermelha entre tasks.

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Modify: `tests/integration/test_conversa_encerrada.py` (linhas 283-294, 512, 960 — **os dois únicos testes que esta card pode editar**)
- Test: `tests/integration/test_moderacao_dos_ramos_que_retornam.py` (criar)

**Interfaces:**
- Consumes: `moderar_entrada_e_marcar` da Task 1.
- Produces: `_ModeracaoDoTurno` com `async def resolver() -> Veredito | None` e `async def resolver_no_fim() -> None`, ambas idempotentes entre si (a segunda chamada de qualquer das duas é no-op). `_executar_turno` com a assinatura de hoje mais `corpo: str | None` e `moderacao: _ModeracaoDoTurno`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/integration/test_moderacao_dos_ramos_que_retornam.py`:

```python
"""Os cinco returns antecipados de `executar_turno` e a moderacao de entrada.

Antes da TEC-297 a moderacao rodava num ponto so, depois de cinco saidas que
retornam antes dele. A fala que disparava qualquer uma delas nunca era
moderada: `bloqueada_em` ficava nulo e os quatro leitores dessa coluna a
tratavam como fala legitima.

Os testes provam pela COLUNA e pela janela real, nao pelo desfecho do turno.
Desfecho nao diz nada sobre o que entra no prompt.
"""

import uuid
from datetime import UTC, datetime

from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import Direcao
from mobia.infra.db import get_sessionmaker

TEXTO_REPROVAVEL = "quero falar com uma pessoa agora"


async def _linha_bloqueada(session: AsyncSession, message_id) -> Message | None:
    return (
        await session.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()


async def test_o_pedido_de_humano_reprovavel_recebe_a_marca(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O ramo #5 da spec, e o cenario que originou a card.

    "vai se f****, quero falar com uma pessoa" cria handoff, entrega o aviso
    e retornava sem nunca moderar -- a fala entrava no contexto, no score e
    na ancora de follow-up.
    """
    moderador = moderador_fake(bloqueia_entrada=True)

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=TEXTO_REPROVAVEL,
    )

    assert desfecho == "pedido_de_humano", "o desfecho do ramo nao muda"
    assert moderador.entradas == 1, "a fala foi moderada exatamente uma vez"

    linha = (
        await session.execute(
            select(Message).where(
                Message.channel == CANAL_AGENTE,
                Message.conversation_key == CONVERSA_AGENTE,
                Message.bloqueada_em.is_not(None),
            )
        )
    ).scalars().all()
    assert len(linha) == 1, "a fala do ramo recebeu `bloqueada_em`"

    eventos = (
        await session.execute(
            select(ModerationEvent).where(
                ModerationEvent.message_id == linha[0].id,
                ModerationEvent.direcao == Direcao.ENTRADA.value,
            )
        )
    ).scalars().all()
    assert len(eventos) == 1, "marca e auditoria saem juntas (TEC-142)"
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_dos_ramos_que_retornam.py --tb=short
```

Esperado: 1 falha. `moderador.entradas == 1` reprova com `0`, e a asserção da marca reprova com `len == 0` — o ramo retorna antes da moderação.

- [ ] **Step 3: Implementar `_ModeracaoDoTurno`**

Em `turno.py`, **antes** de `executar_turno` (depois de `_continuar_entrega`, que termina na 820):

```python
class _ModeracaoDoTurno:
    """Garante que a fala de entrada seja moderada UMA vez, por onde quer que
    o turno saia.

    Privada de `turno.py` e nao de `domain/messages/`: ela carrega estado de um
    turno -- o veredito memorizado e o `_resolvida` --, e nao tem sentido fora
    dele. A operacao compartilhada e `moderar_entrada_e_marcar`; aqui mora so a
    memoria de ja ter chamado.

    **O problema que ela resolve** (TEC-297): `executar_turno` tem cinco
    returns antes da linha da moderacao, e a fala que dispara qualquer um
    deles nunca era moderada. Chamar a moderacao antes de cada um dos cinco
    seria cinco sitios a lembrar -- a forma que ja apodreceu duas vezes neste
    arquivo (a TEC-128 enumerou tres excecoes e faltou a quarta; a TEC-295
    enumerou dois ramos e havia cinco). Um sexto ramo futuro nasce coberto
    pelo `finally` do invulucro e nasceria furado por uma lista.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        moderador: ModeradorPort,
        message: Message,
        corpo: str | None,
    ) -> None:
        self._session_factory = session_factory
        self._moderador = moderador
        self._message = message
        self._corpo = corpo
        self._resolvida = False
        self._veredito: Veredito | None = None

    async def resolver(self) -> Veredito | None:
        """Modera e marca, na primeira chamada. Depois, devolve o memorizado.

        Sem corpo nao ha o que moderar -- audio, imagem e documento passam por
        aqui e nao pagam nada --, e a fala fica resolvida como se tivesse sido
        liberada: `None`. O `if corpo` que o turno sempre teve continua
        valendo, so mudou de lugar.
        """
        if self._resolvida:
            return self._veredito
        self._resolvida = True
        if not self._corpo:
            return None
        self._veredito = await moderar_entrada_e_marcar(
            self._session_factory,
            self._moderador,
            message_id=self._message.id,
            channel=self._message.channel,
            conversation_key=self._message.conversation_key,
            corpo=self._corpo,
        )
        return self._veredito

    async def resolver_no_fim(self) -> None:
        """O que o `finally` do invulucro chama. Ver a D5 da spec.

        Com excecao do turno em voo, engole a falha da marca e loga: propagar
        daqui substituiria a excecao real pela da marca, e `last_error`
        guardaria a classe errada. Sem excecao em voo, propaga -- preserva o
        contrato de `messages/bloqueio.py`, o turno vira FAILED e o sweeper
        retenta.
        """
        if self._resolvida:
            return
        if sys.exc_info()[0] is None:
            await self.resolver()
            return
        try:
            await self.resolver()
        except Exception as exc:
            log.error(
                "moderacao.marca_falhou",
                message_id=str(self._message.id),
                reason=type(exc).__name__,
            )
```

Acrescente `import sys` ao topo e `from mobia.domain.messages.bloqueio import moderar_entrada_e_marcar` aos imports (o `Veredito` já vem de `domain.moderacao.port`; confirme com `grep -n "Veredito" src/mobia/domain/agente/turno.py`).

- [ ] **Step 4: Partir `executar_turno`**

1. Renomeie a `def` da 821 de `executar_turno` para `_executar_turno` e acrescente dois parâmetros keyword-only ao fim da assinatura: `corpo: str | None` e `moderacao: _ModeracaoDoTurno`.
2. **Mova** a docstring de contrato (832-880) para o invólucro novo. Dê a `_executar_turno` uma docstring curta:
   ```python
   """O corpo do turno. Contrato e desfechos: ver `executar_turno`.

   Existe separada so para que o `try/finally` do invulucro nao reindente
   2700 linhas (TEC-297, D9). Nao chame direto: sem o `finally` a fala dos
   cinco returns antecipados volta a nao ser moderada.
   """
   ```
3. **Apague** do corpo extraído a linha `corpo = decrypt(...)` (884) e o comentário dela (881-883) — os dois sobem para o invólucro.
4. Crie o invólucro imediatamente antes de `_executar_turno`:

```python
async def executar_turno(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    classificador: ClassificadorPort,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    outbound: OutboundPort,
    moderador: ModeradorPort,
    agendador: AgendadorDeResumoPort,
) -> ResultadoDoTurno:
    """<a docstring de contrato movida da 832-880 vem inteira para ca>"""
    # Antes de montar contexto de proposito: bloquear ali economiza o turno
    # inteiro, inclusive as chamadas pagas ao modelo. E o texto do lead ainda
    # nao passou por lugar nenhum.
    corpo = decrypt(message.text_body, aad_de(message.id, "text_body"))
    # TEC-297: a moderacao de entrada nasce aqui e e garantida pelo `finally`,
    # nao pela linha em que o corpo do turno a chama. Cinco returns saem antes
    # dessa linha, e a fala que os dispara nunca era moderada.
    moderacao = _ModeracaoDoTurno(session_factory, moderador, message, corpo)
    try:
        return await _executar_turno(
            session_factory,
            message=message,
            classificador=classificador,
            resumidor=resumidor,
            contador=contador,
            outbound=outbound,
            moderador=moderador,
            agendador=agendador,
            corpo=corpo,
            moderacao=moderacao,
        )
    finally:
        await moderacao.resolver_no_fim()
```

5. No corpo extraído, o bloco da Task 2 passa a usar a memória em vez de chamar direto:

```python
    if corpo:
        veredito = await moderacao.resolver()
        if veredito is not None and veredito.bloqueado:
            <sem alteracao daqui para baixo>
```

- [ ] **Step 5: Rodar o teste novo**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_dos_ramos_que_retornam.py --tb=short
```

Esperado: 1 passed.

- [ ] **Step 6: Reverter os dois testes da TEC-138**

Os dois vão falhar agora, e é o esperado. Em `tests/integration/test_conversa_encerrada.py`, troque a classe da 283:

```python
class ModeradorQueRegistra:
    """Registra as direcoes moderadas em vez de levantar.

    **Era `ModeradorQueNaoPodeSerChamado`, e levantava.** A TEC-138 (D7)
    contava a moderacao de entrada entre as economias da guarda de fora de
    escopo, e este duble travava essa contagem. A TEC-297 reverteu a decisao
    de proposito: a fala que dispara a guarda passa a ser moderada, porque
    sem marca ela entra no contexto, no resumo, no score e na ancora de
    follow-up quando a conversa reabre depois dos 30 dias.

    O que a TEC-138 queria provar continua provado, e por este duble: a guarda
    nao paga o CLASSIFICADOR nem a montagem de contexto, que sao as duas
    caras. Ela passou a pagar uma moderacao, US$ 0,00057 -- e a asserta agora
    e "exatamente uma de ENTRADA e zero de SAIDA", que e mais forte que
    "nenhuma", porque pega tanto a guarda que desceu quanto a que virou um
    turno inteiro.

    Ver a D8 do desenho da TEC-297: a reversao encolhe a reducao de superficie
    que a TEC-138 tinha oferecido a TEC-204, e isso esta registrado la.
    """

    def __init__(self) -> None:
        self.direcoes: list = []

    async def moderar(self, texto, *, direcao):
        from mobia.domain.moderacao.port import Direcao, Veredito

        self.direcoes.append(direcao)
        return Veredito(bloqueado=False, motivo="fake", categoria=None)
```

Nos dois usos (512 e 960), troque `ModeradorQueNaoPodeSerChamado()` por uma instância nomeada e acrescente a asserção. No primeiro (o teste da linha 487):

```python
    moderador = ModeradorQueRegistra()

    desfecho = await rodar_turno(
        session,
        ClassificadorQueNaoPodeSerChamado(),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto="e agora, vai chover?",
    )

    assert desfecho == "fora_de_escopo"
    # TEC-297: uma de ENTRADA, zero de SAIDA. A guarda continua nao pagando o
    # turno; passou a pagar a moderacao.
    assert moderador.direcoes == [Direcao.ENTRADA]
```

Faça o mesmo no segundo uso. Ajuste a docstring do teste da 487 — ela diz *"os dois dubles que levantam"* e *"a D7 a conta entre as economias"*, e as duas frases deixam de ser verdade. Importe `Direcao` no arquivo se ainda não estiver.

- [ ] **Step 7: Rodar `tests/integration` inteiro**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
```

Esperado: tudo verde. **Qualquer outro teste que falhe é sinal**, não ruído — a extração não deveria mudar comportamento nenhum. Investigue antes de editar.

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_conversa_encerrada.py tests/integration/test_moderacao_dos_ramos_que_retornam.py
git commit -F - <<'EOF'
feat(TEC-297): a fala dos cinco returns antecipados passa a ser moderada

`executar_turno` vira um involucro que decifra o corpo, constroi a
moderacao e chama `_executar_turno` num `try/finally`. O corpo extraido
fica no mesmo nivel de indentacao -- a alternativa reindentava 2700
linhas sem uma mudanca de comportamento dentro.

Reverte a decisao da D7 da TEC-138 com ela a vista:
`ModeradorQueNaoPodeSerChamado` existia para travar exatamente esta
mudanca e virou `ModeradorQueRegistra`, que afirma uma chamada de ENTRADA
e zero de SAIDA. A guarda continua nao pagando classificador nem
contexto, que sao as duas caras.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Os outros quatro ramos, o resolve-once, a ordem e o fail-open

**Files:**
- Modify: `tests/integration/test_moderacao_dos_ramos_que_retornam.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-3. Nenhum código de produção muda nesta task — se algum teste aqui reprovar, o defeito está na Task 3.

- [ ] **Step 1: Escrever os testes dos cinco ramos, parametrizados**

Acrescente ao arquivo da Task 3. Cada entrada monta o estado que dispara o ramo:

```python
async def _preparar_silenciado(session, **_):
    """Ramo #1: lead ja em opt-out. Fala anterior registra o opt-out."""
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.optout.repositorio import registrar_optout

    anterior = await _entrada_do_lead(session, texto="parar")
    await registrar_optout(
        get_sessionmaker(),
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        message_id=anterior.id,
    )
    return "qualquer coisa"


async def _preparar_atendimento_humano(session, *, semear_corretor, **_):
    """Ramo #2: handoff ja assumido. O de maior volume dos cinco."""
    from mobia.domain.atendimento.repositorio import assumir

    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()
    return "qualquer coisa"


async def _preparar_fora_de_escopo(session, **_):
    """Ramo #3: conversa encerrada por fora de escopo, dentro da janela."""
    from mobia.domain.conversa.repositorio import encerrar_conversa
    from mobia.domain.conversa.vocabulario import MotivoDoEncerramento

    await encerrar_conversa(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        motivo=MotivoDoEncerramento.FORA_DE_ESCOPO,
        agora=datetime.now(UTC),
    )
    await session.commit()
    return "qualquer coisa"


async def _preparar_opt_out(session, **_):
    """Ramo #4: a propria fala pede opt-out."""
    return "parar"


async def _preparar_pedido_de_humano(session, **_):
    """Ramo #5: a propria fala pede humano."""
    return TEXTO_REPROVAVEL


OS_CINCO_RAMOS = [
    ("silenciado", _preparar_silenciado),
    ("atendimento_humano", _preparar_atendimento_humano),
    ("fora_de_escopo", _preparar_fora_de_escopo),
    ("opt_out", _preparar_opt_out),
    ("pedido_de_humano", _preparar_pedido_de_humano),
]
```

Os quatro caminhos de import acima foram conferidos em `c8b286a` contra os imports de `tests/integration/test_conversa_encerrada.py:34-41`. Dois deles não estão onde o nome sugere: `assumir` mora em **`mobia.domain.atendimento.repositorio`** (não em `handoff`), e `MotivoDoEncerramento` mora em **`mobia.domain.conversa.vocabulario`** (não em `conversa.repositorio`, de onde vem `encerrar_conversa`).

- [ ] **Step 2: O teste parametrizado da marca e da janela**

```python
@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_fala_reprovavel_e_marcada_e_sai_da_janela_nos_cinco_ramos(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """A garantia da TEC-236, provada pela janela real e nao pelo desfecho.

    `literais_apos` e a funcao de producao por onde TODO contexto e TODO
    resumo passam -- `dividir` recebe o que ela devolve, entao o que nao sai
    dela nunca chega a dobra dos ~40 turnos. Asserir pelo desfecho do turno
    provaria so que o ramo retornou, que e o que ja acontecia quando o
    defeito existia.
    """
    from mobia.domain.context.janela import literais_apos

    texto = await preparar(session, semear_corretor=semear_corretor)
    moderador = moderador_fake(bloqueia_entrada=True)

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=texto,
    )

    assert desfecho == desfecho_esperado
    assert moderador.entradas == 1

    marcadas = (
        await session.execute(
            select(Message).where(
                Message.channel == CANAL_AGENTE,
                Message.conversation_key == CONVERSA_AGENTE,
                Message.bloqueada_em.is_not(None),
            )
        )
    ).scalars().all()
    assert len(marcadas) == 1

    eventos = (
        await session.execute(
            select(ModerationEvent).where(ModerationEvent.message_id == marcadas[0].id)
        )
    ).scalars().all()
    assert len(eventos) == 1, "marca e auditoria no mesmo commit (TEC-142)"

    na_janela = await literais_apos(session, CANAL_AGENTE, CONVERSA_AGENTE, None)
    assert marcadas[0].id not in {linha.id for linha in na_janela}, (
        "a fala bloqueada nao pode entrar no contexto nem, por consequencia, no resumo"
    )
```

Se `literais_apos` exigir uma marca d'água diferente de `None`, copie a forma usada em `tests/integration/test_moderacao_na_rajada.py` — ela já chama essa função.

- [ ] **Step 3: Nenhuma recusa nos cinco**

```python
@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_nenhum_dos_cinco_ramos_entrega_recusa(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """A D2: marca e auditoria, sem recusa.

    Nos ramos silenciosos a recusa quebraria o silencio que a guarda existe
    para manter. No ramo do opt-out seria mandar uma segunda mensagem a quem
    acabou de pedir para sair -- a violacao que a RN-14.1 existe para impedir.
    """
    from mobia.domain.moderacao.port import (
        KIND_DA_RECUSA_DE_ENTRADA,
        TEXTO_DA_RECUSA_DE_ENTRADA,
    )
    from mobia.domain.outbound.repositorio import kinds_reservados

    texto = await preparar(session, semear_corretor=semear_corretor)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
        texto=texto,
    )

    assert not any(TEXTO_DA_RECUSA_DE_ENTRADA in entregue for entregue in entregador.entregues)

    # A asserta sobre `entregues` sozinha e fraca: ela nao pega uma recusa que
    # RESERVOU o kind e falhou na entrega. `kinds_reservados` responde
    # "encerrado", nao "entregue", e e por isso que ela e a asserta forte aqui.
    marcada = (
        await session.execute(
            select(Message).where(
                Message.channel == CANAL_AGENTE,
                Message.conversation_key == CONVERSA_AGENTE,
                Message.bloqueada_em.is_not(None),
            )
        )
    ).scalar_one()
    reservados = await kinds_reservados(get_sessionmaker(), message_id=marcada.id)
    assert KIND_DA_RECUSA_DE_ENTRADA not in reservados
```

`kinds_reservados(session_factory, *, message_id) -> frozenset[str]` recebe a **factory**, não a sessão — conferido em `src/mobia/domain/outbound/repositorio.py:16`.

- [ ] **Step 4: A ordem — o handoff existe antes de o moderador ser chamado**

```python
async def test_o_handoff_existe_antes_de_a_moderacao_ser_chamada(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    rodar_turno,
) -> None:
    """Trava a CA-04.3: "um handoff e criado em ate 5 s".

    O prazo mede ate a LINHA existir, e a moderacao tem teto de 5s sozinha.
    Se alguem mover a moderacao para antes de `registrar_handoff`, o pior caso
    do prazo dobra -- e o teste que pega isso nao pode ser sobre latencia
    (flake em runner compartilhado), tem de ser sobre ORDEM. Dai o duble que
    consulta o banco no momento em que e chamado.
    """
    from mobia.domain.handoff.models import Handoff
    from mobia.domain.moderacao.port import Veredito

    handoffs_no_momento_da_moderacao: list = []

    class _ModeradorQueOlhaOBanco:
        def __init__(self) -> None:
            self.entradas = 0

        async def moderar(self, texto, *, direcao):
            self.entradas += 1
            async with get_sessionmaker()() as sessao:
                linhas = (
                    await sessao.execute(
                        select(Handoff).where(
                            Handoff.channel == CANAL_AGENTE,
                            Handoff.conversation_key == CONVERSA_AGENTE,
                        )
                    )
                ).scalars().all()
                handoffs_no_momento_da_moderacao.extend(linhas)
            return Veredito(bloqueado=True, motivo="fake", categoria="DISCRIMINACAO")

    moderador = _ModeradorQueOlhaOBanco()

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=TEXTO_REPROVAVEL,
    )

    assert desfecho == "pedido_de_humano"
    assert moderador.entradas == 1
    assert len(handoffs_no_momento_da_moderacao) == 1, (
        "o handoff tem de estar gravado ANTES de a chamada paga acontecer (CA-04.3)"
    )
```

O modelo e `mobia.domain.handoff.models.Handoff`, conferido em `c8b286a` contra o import de `tests/integration/test_pedido_de_humano.py:14`.

- [ ] **Step 5: Fail-open e mensagem sem corpo**

```python
@pytest.mark.parametrize("desfecho_esperado,preparar", OS_CINCO_RAMOS)
async def test_moderacao_indisponivel_nao_impede_a_acao_do_ramo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    semear_corretor,
    desfecho_esperado: str,
    preparar,
) -> None:
    """Fail-open: provedor caido nao pode custar o opt-out nem o handoff.

    A consequencia e honesta e esta declarada: provedor fora do ar significa
    fala nao moderada entrando no contexto, como ja acontece no turno normal.
    """
    from mobia.domain.moderacao.port import ModeracaoIndisponivel

    texto = await preparar(session, semear_corretor=semear_corretor)
    moderador = moderador_fake(erro_na_entrada=ModeracaoIndisponivel("provedor fora"))

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=texto,
    )

    assert desfecho == desfecho_esperado, "o ramo acontece igual"
    marcadas = (
        await session.execute(
            select(Message).where(Message.bloqueada_em.is_not(None))
        )
    ).scalars().all()
    assert marcadas == [], "indisponivel nao marca nada"


async def test_mensagem_sem_corpo_nao_paga_moderacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """O `if corpo` mudou de lugar e continua valendo.

    Audio, imagem e documento chegam com `text_body` nulo. Moderar ali
    mandaria string vazia ao provedor e pagaria por nada.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    linha = await _entrada_do_lead(session, texto=None)
    moderador = moderador_fake()

    await executar_turno(
        get_sessionmaker(),
        message=linha,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=moderador,
        agendador=AgendadorNoop(),
    )

    assert moderador.entradas == 0
```

Se `_entrada_do_lead` não aceitar `texto=None`, semeie a linha direto com `gravar` de `tests/integration/test_rajada.py`, que é o helper que grava `Message` cru.

- [ ] **Step 6: Rodar o arquivo inteiro**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_dos_ramos_que_retornam.py --tb=short
```

Esperado: tudo verde. **Se um ramo específico reprovar, não conserte o teste** — o defeito está no invólucro da Task 3.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_moderacao_dos_ramos_que_retornam.py
git commit -F - <<'EOF'
test(TEC-297): os cinco ramos provados pela janela, nao pelo desfecho

Parametrizado nos cinco desfechos: marca, auditoria no mesmo commit, e
ausencia em `literais_apos` -- a funcao de producao por onde todo contexto
e todo resumo passam.

O teste da ordem e sobre ORDEM e nao sobre latencia: um duble consulta o
banco no momento em que e chamado e afirma que o handoff ja existe. Um
teste de tempo seria flake em runner compartilhado.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: A exceção do turno não é mascarada pela marca

**Files:**
- Modify: `tests/integration/test_moderacao_dos_ramos_que_retornam.py`

**Interfaces:**
- Consumes: `_ModeracaoDoTurno.resolver_no_fim` da Task 3. Nenhum código de produção muda — o comportamento foi implementado na Task 3, Step 3.

- [ ] **Step 1: Escrever o teste**

```python
async def test_excecao_do_turno_sobrevive_a_falha_da_marca(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    monkeypatch: object,
) -> None:
    """A D5: com excecao do turno em voo, a falha da marca e engolida e logada.

    Propagar do `finally` substituiria a excecao real pela da marca, e
    `last_error` guardaria a classe errada -- uma investigacao inteira
    perseguindo o sintoma. O preco e declarado: nesse caso a fala fica sem
    marca, com so uma linha de log.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente import turno as modulo_do_turno
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    class _FalhaDoTurno(RuntimeError):
        pass

    async def marca_que_falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a marca falhou")

    async def turno_que_levanta(*args: object, **kwargs: object) -> str:
        raise _FalhaDoTurno("a causa real")

    monkeypatch.setattr(modulo_do_turno, "moderar_entrada_e_marcar", marca_que_falha)
    monkeypatch.setattr(modulo_do_turno, "_executar_turno", turno_que_levanta)

    linha = await _entrada_do_lead(session, texto=TEXTO_REPROVAVEL)

    with pytest.raises(_FalhaDoTurno, match="a causa real"):
        await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound_fake(),
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )


async def test_sem_excecao_em_voo_a_falha_da_marca_propaga(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    monkeypatch: object,
) -> None:
    """O outro lado da D5, e o que preserva o contrato de `messages/bloqueio.py`.

    Turno que terminou bem mais marca que falhou tem de virar FAILED: sem
    marca, a fala bloqueada volta a ser elegivel para o contexto do proximo
    turno e para o resumo permanente.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente import turno as modulo_do_turno
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    async def marca_que_falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a marca falhou")

    monkeypatch.setattr(modulo_do_turno, "moderar_entrada_e_marcar", marca_que_falha)

    linha = await _entrada_do_lead(session, texto="parar")

    with pytest.raises(RuntimeError, match="a marca falhou"):
        await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound_fake(),
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )
```

O segundo teste usa o ramo do opt-out (`texto="parar"`) de propósito: ele sai por um dos cinco returns, então a marca só acontece no `finally`, sem exceção em voo. Confirme que `monkeypatch.setattr` no módulo pega a referência — `_ModeracaoDoTurno.resolver` chama `moderar_entrada_e_marcar` pelo nome do módulo, então pega.

- [ ] **Step 2: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_dos_ramos_que_retornam.py -k excecao_do_turno or marca_propaga --tb=short
```

Esperado: 2 passed. Se o primeiro reprovar com `RuntimeError: a marca falhou` em vez de `_FalhaDoTurno`, o `sys.exc_info()` da Task 3 está invertido.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_moderacao_dos_ramos_que_retornam.py
git commit -F - <<'EOF'
test(TEC-297): a marca que falha nao rouba o last_error do turno

Os dois lados da D5. Com excecao do turno em voo, a falha da marca e
engolida e logada -- propagar substituiria a causa real e mandaria a
investigacao perseguir o sintoma. Sem excecao em voo, propaga, e o turno
vira FAILED para o sweeper retentar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: A prosa que ficou falsa

Sem teste: nenhum gate olha para comentário, e é por isso que ~51 commits deste repo existem só para corrigir afirmação que ele mesmo escreveu errado.

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (comentários das guardas, ~906-912 e ~1044-1056)
- Modify: `src/mobia/workers/jobs/process_message.py` (comentário ~460-469)
- Modify: `docs/superpowers/specs/2026-09-16-tec-138-encerrar-fora-de-escopo-design.md` (adendo abaixo da D7)
- Modify: `docs/superpowers/specs/2026-09-21-tec-297-moderacao-dos-ramos-que-retornam-cedo-design.md` (status)

- [ ] **Step 1: Rodar a listagem para ver o que a branch precisa reconferir**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

A saída é truncada por desenho. Use `--tudo` se a contagem do rodapé for maior que o que apareceu.

- [ ] **Step 2: O comentário da guarda de opt-out**

O trecho *"quem ja pediu silencio nao paga moderacao nem recebe resposta"* passa a:

```
# Antes de tudo: quem ja pediu silencio nao recebe resposta. **Paga a
# moderacao, desde a TEC-297** -- este `return` e um dos cinco que saiam
# antes dela, e a fala que o dispara entrava no contexto, no resumo, no
# score e na ancora de follow-up sem nunca ter sido julgada. A chamada
# acontece no `finally` do involucro, depois deste return, entao ela nao
# atrasa o silencio.
```

Mantenha o resto do comentário (a parte sobre ficar fora do `if corpo:`, que continua verdadeira).

- [ ] **Step 3: O comentário da guarda de fora de escopo**

O trecho que diz que economizar as chamadas pagas *"e a unica coisa que esta guarda faz"* e que descer um degrau a tornaria *"silencio CARO"* passa a:

```
# **Ganha de tudo o que vem abaixo pelo motivo oposto**: daqui para baixo
# leva a montagem de contexto e ao classificador, e economiza-las e o que
# esta guarda faz. Descer um degrau que seja a transformaria em silencio
# CARO.
#
# **A moderacao de entrada saiu dessa conta na TEC-297**, e a saida foi
# deliberada: a guarda passou a pagar uma moderacao (US$ 0,00057 medidos)
# porque sem a marca a fala entra no contexto e no resumo quando a conversa
# reabre depois dos 30 dias. As duas caras continuam economizadas. A D8 do
# desenho da TEC-297 registra o que isso encolhe da reducao de superficie
# que a D7 da TEC-138 tinha oferecido a TEC-204.
```

- [ ] **Step 4: O comentário do worker**

Em `process_message.py`, o comentário que diz que opt-out e pedido de humano *"retornam antes da moderacao de entrada"* e que a fala *"segue sem ser moderada -- buraco pre-existente, que esta card nao fecha"* passa a:

```
# TEC-295: a superada e moderada neste ramo, o do agrupado. Os outros
# ramos -- opt-out, pedido de humano e a entrega parcial -- caem na
# moderacao do turno, e **desde a TEC-297 isso vale mesmo para os que
# retornam antes da linha da moderacao**: o `finally` do involucro de
# `executar_turno` resolve a moderacao por onde quer que o turno saia. O
# buraco que este comentario descrevia esta fechado.
```

- [ ] **Step 5: O adendo ao desenho da TEC-138**

Abaixo da D7 de `docs/superpowers/specs/2026-09-16-tec-138-encerrar-fora-de-escopo-design.md`, no idioma de nota de revisão que o arquivo já usa:

```markdown
**Adendo (TEC-297, 21/09/2026).** A frase acima — *"esta card limita um sondador a três chamadas pagas por conversa a cada 30 dias, contra ilimitado hoje"* — passou a ser verdadeira pela metade. O classificador e a montagem de contexto continuam limitados a três; a **moderação de entrada voltou a ser ilimitada**, porque a TEC-297 fez a guarda desta card moderar a fala que ela silencia. A razão: sem a marca, a fala entra na janela de contexto, no resumo permanente, no lead score e na âncora de follow-up quando a conversa reabre depois dos 30 dias — e a TEC-297 decidiu que uma chamada de US$ 0,00057 é preço mais baixo que essa contaminação.

A consequência para quem for desenhar a **TEC-204**: a redução de superfície que esta D7 ofereceu encolheu. Um sondador com dez mil mensagens numa conversa encerrada gera dez mil moderações, ~US$ 5,70. O teto por número é a TEC-205, não uma exceção nesta guarda. Ver a D8 de `2026-09-21-tec-297-moderacao-dos-ramos-que-retornam-cedo-design.md`.

O texto da D7 **não** foi reescrito: o que ele afirmou era verdade quando foi escrito, e `ModeradorQueNaoPodeSerChamado` existia para travá-lo. A TEC-297 reverteu com isso à vista.
```

- [ ] **Step 6: O status da spec desta card**

Em `docs/superpowers/specs/2026-09-21-tec-297-...-design.md`, troque `**Status:** desenhado, não implementado.` por `**Status:** implementado.`

- [ ] **Step 7: Reler a listagem e conferir cada `VIZINHO`**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --tudo
```

Para cada `ALTERADO`, `VIZINHO`, `PROSA`, `FALSO` e `NOMEIA`: leia o comentário e decida se ele continua verdadeiro. A docstring de contrato que mudou de função na Task 3 vai aparecer, e a de módulo de `bloqueio.py` também — ela hoje fala só da marca e agora o módulo também modera.

**Atenção especial a `FALSO`:** é a única marca que afirma em vez de suspeitar, e a Task 3 moveu centenas de linhas — qualquer prosa que cite `turno.py:<linha>` pode ter passado a apontar para outro lugar. A própria spec desta card cita linhas, e o cabeçalho dela já avisa que são de `c8b286a`; confirme se o aviso basta ou se vale reapontar.

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A src/ docs/
git commit -F - <<'EOF'
docs(TEC-297): os comentarios das guardas param de negar a moderacao

Tres afirmacoes ficaram falsas com esta card. A guarda de opt-out dizia
"nao paga moderacao"; a de fora de escopo dizia que economizar as
chamadas pagas era "a unica coisa" que ela faz; e o comentario do worker
dizia que o buraco dos ramos que retornam cedo "esta card nao fecha".

O adendo a D7 da TEC-138 registra que a reducao de superficie oferecida a
TEC-204 encolheu, e nao reescreve o texto dela: o que ela afirmou era
verdade quando foi escrito.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 7: As duas emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (RN-04.5 na linha ~191, RN-02.2 na linha ~144)

**Interfaces:** nenhuma. Emendas entram como item aninhado, **nunca** reescrevendo o texto de 22/08/2026. A numeração é por regra: RN-04.5 já tem E-01 e E-02, logo **E-03**; RN-02.2 não tem nenhuma, logo **E-01**.

- [ ] **Step 1: A emenda da RN-04.5**

Abaixo da Emenda E-02 da RN-04.5, no mesmo nível de aninhamento:

```markdown
  - **Emenda E-03 (TEC-297, 21/09/2026):** a regra base junta *"recebe recusa educada"* e *"é registrado como evento de auditoria"* como se fossem inseparáveis, e há cinco caminhos em que a segunda metade acontece sem a primeira. `executar_turno` tem cinco saídas que retornam antes da moderação — lead já em opt-out, conversa com handoff aberto ou silenciada, conversa encerrada por fora de escopo dentro da janela, pedido de opt-out e pedido explícito de humano. **A moderação passa a rodar em todas as cinco, e nenhuma entrega a recusa.** Nas três silenciosas, entregá-la quebraria o silêncio que a guarda existe para manter; no pedido de opt-out, seria mandar mensagem a quem acabou de pedir para sair, que é o que a RN-14.1 impede; e durante atendimento humano a Emenda E-03 da RN-16.4 já barra qualquer saída que não seja a confirmação de opt-out. O que essas falas recebem é a marca e a linha de auditoria, e é o suficiente para o efeito que a moderação de entrada existe para produzir — manter a fala fora do contexto e do resumo, conforme a Emenda E-01 da RN-02.2. A moderação acontece depois da ação e depois da entrega de cada ramo, e por isso não afeta o prazo da CA-04.3 nem o da Emenda E-01 da RN-04.7.
```

- [ ] **Step 2: A emenda da RN-02.2**

Abaixo da RN-02.2 (linha ~144), aninhada:

```markdown
  - **Emenda E-01 (TEC-297, 21/09/2026):** a composição descrita acima exclui a fala que a moderação de entrada bloqueou, e essa exclusão nunca foi escrita nesta especificação — existia só no código desde a TEC-236 (agosto de 2026). O item (a) lê `messages` filtrando a marca de bloqueio, e o item (b) **herda a exclusão por construção**: a dobra que forma o resumo opera sobre a lista que a leitura do item (a) devolve e nunca relê a tabela, então o que não sai de lá nunca chega ao resumo permanente. Desde a TEC-295 a mesma definição de fala do lead governa o lead score (RF-13) e a âncora da cadência de reengajamento, para que as três leituras não divirjam em silêncio. A TEC-297 estendeu a marca aos cinco caminhos que retornavam antes da moderação — ver a Emenda E-03 da RN-04.5. **Consequência aceita:** a fala bloqueada também deixa de contar para o gatilho de regeneração do resumo descrito na segunda frase desta regra.
```

- [ ] **Step 3: Conferir que nenhuma regra foi reescrita**

```bash
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md --stat
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md | grep "^-" | grep -v "^---"
```

Esperado: a segunda saída é **vazia**. Emenda só acrescenta; nenhuma linha removida.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -F - <<'EOF'
docs(TEC-297): o SRS registra a moderacao dos cinco ramos e a garantia de agosto

A E-03 da RN-04.5 desacopla as duas metades da regra base: nos cinco
ramos sai a auditoria sem a recusa, e diz por que cada um deles nao pode
receber a recusa.

A E-01 da RN-02.2 escreve a garantia da TEC-236, que vivia so em
`context/janela.py` desde agosto. Sem ela o SRS nao sabia que a fala
bloqueada fica fora do contexto, e esta card se justificava por uma
regra que nenhuma regra enunciava.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 8: Suíte inteira, PR e card

**Files:** nenhum. Esta task é verificação e entrega.

- [ ] **Step 1: Os três gates, uma última vez**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

O formatador é gate separado do linter: passar num não diz nada sobre o outro.

- [ ] **Step 2: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Interpretação das falhas, nesta ordem:

1. **Centenas de `ERROR` de setup** → não é a sua mudança. Baixe o paralelismo e rode por blocos; não repita o mesmo `-n`.
2. **`relation ... does not exist` em dezenas de testes** → bancos dos workers com `alembic_version` adiantado. Confirme conectando num banco de worker antes de mexer em código.
3. **`RuntimeError: o TRUNCATE de banco_limpo esperou mais de 10s por lock`** → o diagnóstico já está feito, leia a consulta do bloqueador. Não rode de novo.
4. **Uma falha isolada com `ConnectionResetError [WinError 64]`** → não autoriza conclusão nenhuma. ~5% dos connects.
5. **Qualquer outra falha** → repita a suíte **uma** vez sobre a mesma árvore antes de culpar a sua mudança. Se repetir idêntica, é regressão.

- [ ] **Step 3: A listagem de comentários, uma última vez**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --tudo
```

- [ ] **Step 4: Push e PR**

```bash
git push -u origin feat/tec-297-moderacao-dos-ramos-que-retornam-cedo
gh pr create --base main --title "TEC-297: a moderacao de entrada deixa de depender de por onde o turno sai" --body-file -
```

O corpo do PR termina com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Se o push devolver 403, o credential helper do manager respondeu antes do `gh` — limpe a lista de helpers na mesma invocação.

- [ ] **Step 5: Comentar na card e mover para "Em análise"**

**Não** para "Feito": quem mergeia é que fecha. O comentário registra o que some se ficar só no PR:

- **A divergência de escopo, que é grande:** a card descreve dois ramos e a implementação cobriu cinco. Nomeie os três que a card não viu e diga que o `atendimento_humano` é provavelmente o de maior volume.
- **A reversão da TEC-138**, com o nome do dublê que travava a decisão, e o adendo que ficou no desenho dela.
- **A D8:** a redução de superfície oferecida à TEC-204 encolheu, e rate limiting continua sendo a TEC-205.
- **As duas emendas ao SRS**, nomeadas — RN-04.5 E-03 e RN-02.2 E-01 —, e que a segunda escreve uma garantia de agosto que nunca tinha sido registrada.
- **O que esta card não entrega:** os 5 s da Emenda E-04 da RN-16.1 continuam sem âncora no SRS, e os itens 3, 4 e 6 do comentário de fechamento da TEC-295 continuam sem card.

---

## Autorrevisão deste plano

**Cobertura da spec, decisão por decisão:**

| decisão | task |
| --- | --- |
| D1 — moderação por último | Task 3 (Step 3-4), provada na Task 4 (Step 4) |
| D2 — marca sem recusa | Task 4 (Step 3) |
| D3 — função de domínio única | Task 1, adotada na Task 2 |
| D4 — uma resolução, não cinco | Task 3 (Step 3), provada na Task 4 (Step 2, `moderador.entradas == 1`) |
| D5 — `finally` sob exceção | Task 3 (Step 3, `resolver_no_fim`), provada na Task 5 |
| D6 — o custo | sem task: é declaração, não código |
| D7 — comentários falsos | Task 6 (Steps 2-4), o teste da TEC-138 na Task 3 (Step 6) |
| D8 — a oferta à TEC-204 encolhe | Task 6 (Step 5), adendo ao desenho da TEC-138 |
| D9 — o invólucro em vez do `try` literal | Task 3 (Step 4) |
| D10 — o que não muda | sem task, por construção |
| Emendas ao SRS | Task 7 |
| Testes da spec | Tasks 1, 3, 4, 5 — todas as nove linhas da tabela da spec têm task |

**Consistência de tipos:** `moderar_entrada_e_marcar` devolve `Veredito | None` na Task 1, e os três chamadores tratam `None` como indisponibilidade nas Tasks 2 e 3. `_ModeracaoDoTurno.resolver` devolve o mesmo tipo; `resolver_no_fim` devolve `None` e nunca levanta com exceção em voo.

**Riscos que o plano não elimina:**

- **A Task 3 é a única grande, e é indivisível.** O `finally` cobre os cinco ramos de uma vez; não há como entregar um ramo por vez. Quem revisar deve olhar o diff da assinatura e do invólucro, não a movimentação.
- **`monkeypatch.setattr(modulo_do_turno, "_executar_turno", ...)`** na Task 5 depende de o invólucro resolver o nome pelo módulo. Se a Task 3 fizer o invólucro chamar uma referência capturada, o teste não pega — nesse caso o teste está certo e a implementação precisa chamar pelo nome.
- **Os caminhos de import foram conferidos, e dois estavam errados na primeira escrita deste plano.** `assumir` mora em `atendimento.repositorio` e não em `handoff.repositorio`; `MotivoDoEncerramento` mora em `conversa.vocabulario` e não em `conversa.repositorio`. Os dois "erros" eram o palpite óbvio pelo nome, e e a razao de o plano citar a linha do import de onde cada um veio em vez de afirmar de cor.
