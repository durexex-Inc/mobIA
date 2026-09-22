# TEC-298 — A rota de recuperação que a TEC-295 abriu deixa de morrer na retentativa

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o turno bloqueado pela moderação responder a pergunta pendente mesmo quando a passada anterior já entregou a recusa, sem repagar moderação e sem alarme falso.

**Architecture:** Cinco mudanças pequenas e independentes em quatro arquivos. A fronteira de `ha_fala_pendente_antes` ganha um teto opcional, e o teto vem do `created_at` da reserva da recusa em `outbound_dispatches` — que é commitada antes do envio e portanto anterior à fala que envenena a fronteira. O guard do turno passa a deixar `"reentrega_suprimida"` seguir. O alarme dessa supressão, no kind da recusa, vira `warning` com nome próprio. E `_ModeracaoDoTurno.resolver` reusa o veredito que `messages.bloqueada_em` já persiste.

**Tech Stack:** Python 3.13, SQLAlchemy async, pytest/pytest-asyncio, Postgres.

**Spec:** `docs/superpowers/specs/2026-09-22-tec-298-pendencia-perdida-apos-recusa-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado — uma citação de texto que o lead recebe mantém o acento do literal. Nenhum linter checa isso.
- **Prosa em `docs/` e no SRS: com acento.**
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-298): o que passou a ser verdade`. Cada commit termina com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates estáticos, nesta ordem, antes de qualquer commit** — o formatador é gate separado do linter:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  `mypy` sem argumento — argumento de linha de comando sobrepõe o `files` do `pyproject.toml`.
- **Testes de integração exigem `docker compose` de pé.** `tests/unit` não.
- **Uma execução da suíte inteira basta.** Segunda execução só quando a primeira falha, e aí é o que separa flake de regressão.
- **Comentário desatualizado é defeito.** Se o código que um comentário descreve mudar, o comentário muda junto ou some.

---

### Task 1: O teto opcional na fronteira do agente

**Files:**
- Modify: `src/mobia/domain/messages/rajada.py` — `ha_fala_pendente_antes`
- Test: `tests/integration/test_rajada.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `ha_fala_pendente_antes(session: AsyncSession, message: Message, *, teto_do_agente: datetime | None = None) -> bool`. A Task 2 passa `teto_do_agente`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_rajada.py`, no fim do arquivo. `gravar` já existe no topo do arquivo; `LEAD` e `CANAL` também.

```python
async def test_teto_do_agente_ignora_a_fala_posterior_a_ele(session) -> None:
    """TEC-298, D1. Com teto, a fala do agente posterior a ele nao fecha a pendencia.

    E o estado da retentativa: a recusa da passada anterior ja e a ultima fala
    OUTBOUND, e sem o teto ela apaga a pendencia da pergunta legitima. O teto
    reconstroi a fronteira que existia antes dela.
    """
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    recusa = await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="nao consigo seguir com essa mensagem",
    )
    carregadora = await gravar(session, created_at=agora + timedelta(seconds=2))

    # Sem teto: a recusa e a ultima fala do agente e apaga a pendencia.
    assert await ha_fala_pendente_antes(session, carregadora) is False
    # Com teto no instante da recusa: ela sai da conta e a pergunta reaparece.
    assert (
        await ha_fala_pendente_antes(session, carregadora, teto_do_agente=recusa.created_at)
        is True
    )


async def test_teto_no_futuro_nao_muda_nada(session) -> None:
    """O teto so pode ESCONDER fala do agente, nunca revelar fala que nao existe."""
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="tenho estas opcoes",
    )
    carregadora = await gravar(session, created_at=agora + timedelta(seconds=2))

    teto = agora + timedelta(hours=1)
    assert await ha_fala_pendente_antes(session, carregadora, teto_do_agente=teto) is False
```

Confira que `MessageRole` está importado no topo de `test_rajada.py`; `gravar` já o usa como default, então o import existe.

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py -k teto --tb=short
```

Esperado: `TypeError: ha_fala_pendente_antes() got an unexpected keyword argument 'teto_do_agente'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/messages/rajada.py`. Acrescente `datetime` ao import do topo:

```python
from datetime import datetime
```

Troque a assinatura e a subconsulta da fronteira:

```python
async def ha_fala_pendente_antes(
    session: AsyncSession,
    message: Message,
    *,
    teto_do_agente: datetime | None = None,
) -> bool:
```

E, dentro, substitua a construção de `ultima_do_agente` por:

```python
    fronteira = [
        Message.channel == message.channel,
        Message.conversation_key == message.conversation_key,
        Message.direction == MessageDirection.OUTBOUND,
    ]
    if teto_do_agente is not None:
        fronteira.append(Message.created_at < teto_do_agente)
    ultima_do_agente = select(func.max(Message.created_at)).where(*fronteira).scalar_subquery()
```

Acrescente ao fim da docstring dela (sem acento, é docstring de `src/`):

```
    **`teto_do_agente` existe porque a propria recusa apaga a pendencia
    (TEC-298, D1).** Numa retentativa, a recusa que a passada anterior
    entregou ja esta em `messages` como OUTBOUND e vira a ultima fala do
    agente -- mesmo nao tendo respondido nada. Com o teto no instante da
    RESERVA da recusa (`outbound_dispatches.created_at`, que e commitado
    antes do envio e portanto anterior a linha dela), a fronteira volta a ser
    a que existia antes da recusa.

    **Quem chama tem de saber que precisa passar isto, e hoje ha um chamador
    so.** A funcao nao descobre o teto sozinha de proposito: descobri-lo
    exigiria conhecer `outbound_dispatches` e o kind da recusa, e este modulo
    nao pode depender de `domain/outbound` -- a dependencia so corre no outro
    sentido. A D2 do desenho registra o risco: um chamador futuro que
    esquecer o teto cai no defeito de hoje, em silencio.

    O default `None` mantem todo chamador antigo correto: sem teto, a
    fronteira e exatamente a de antes desta card.
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py --tb=short
```

Esperado: todos passam, inclusive os que já existiam — o default `None` não muda nenhum deles.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/rajada.py tests/integration/test_rajada.py
git commit -m "$(cat <<'EOF'
feat(TEC-298): a fronteira do agente aceita um teto, e a recusa para de se esconder atras dele

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: A retentativa responde a pergunta pendente

**Files:**
- Modify: `src/mobia/domain/outbound/repositorio.py` — nova `reservado_em`
- Modify: `src/mobia/domain/agente/turno.py` — o chamador (perto de `tem_pendencia = await ha_fala_pendente_antes`) e o guard (`if desfecho_da_recusa != "respondido"`)
- Test: `tests/integration/test_moderacao_de_entrada.py`

**Interfaces:**
- Consumes: `ha_fala_pendente_antes(..., teto_do_agente=...)` da Task 1.
- Produces: `reservado_em(session_factory: Any, *, message_id: uuid.UUID, kind: str) -> datetime | None`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_moderacao_de_entrada.py`, logo depois de `test_bloqueada_com_pergunta_pendente_recusa_e_responde`, que é o molde.

Precisa de dois imports novos no topo do arquivo:

`KIND_DA_RECUSA_DE_ENTRADA` mora em `mobia.domain.moderacao.port` (não em `outbound/kinds.py`) e já é importado no bloco `from mobia.domain.moderacao.port import (...)` do topo do arquivo, junto de `TEXTO_DA_RECUSA_DE_ENTRADA` — confira antes de duplicar. `EnvioRetentavel` entra ao lado de `EnvioForaDaJanela`, que já está no import de `mobia.domain.outbound.port`.

O dublê e o teste:

```python
class _OutboundQueFalhaDepoisDaRecusa(OutboundFake):
    """Entrega a recusa e falha na resposta -- a janela exata da TEC-298.

    `EnvioRetentavel` e nao uma excecao qualquer: e a que `GuardedOutbound.send`
    intercepta para liberar as reservas do GRUPO. O kind da recusa nao esta em
    `_GRUPOS`, entao a reserva dela sobrevive -- que e justamente o estado que
    a retentativa vai encontrar.
    """

    async def _deliver(self, message_id, kind, payload) -> None:
        if kind == KIND_DA_RECUSA_DE_ENTRADA:
            await super()._deliver(message_id, kind, payload)
            return
        raise EnvioRetentavel("a resposta nao saiu")


async def test_retentativa_apos_recusa_entregue_responde_a_pendente(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D1 e D3. A rota de recuperacao da TEC-295 sobrevive ao reprocessamento.

    Nao usa `rodar_turno` porque ele semeia uma entrada NOVA a cada chamada, e
    aqui as duas passadas tem de rodar sobre a MESMA linha -- e o que o sweeper
    faz.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    # Primeira passada: a recusa sai, a resposta falha.
    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )
    assert falha.entregues == [TEXTO_DA_RECUSA_DE_ENTRADA]

    # Segunda passada: mesma linha, outbound sao. E o que o sweeper faz.
    segundo_outbound = OutboundFake(get_sessionmaker())
    classificador = classificador_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=segundo_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )

    assert resultado == "respondido"
    # O turno continuou: chamou o classificador e entregou a resposta.
    assert classificador.chamadas == 1
    # A recusa NAO sai de novo -- a reserva dela sobreviveu e a suprime.
    assert TEXTO_DA_RECUSA_DE_ENTRADA not in segundo_outbound.entregues
    assert len(segundo_outbound.entregues) == 1
    # Os dois kinds reservados: a recusa da primeira passada, a resposta desta.
    reservados = await kinds_reservados(get_sessionmaker(), message_id=carregadora.id)
    assert reservados == {KIND_DA_RECUSA_DE_ENTRADA, KIND_DA_RESPOSTA}


async def test_retentativa_sem_pendencia_continua_so_recusando(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D7. A garantia da TEC-233 vale na retentativa tambem.

    Sem pergunta pendente, a retentativa nao pode virar desculpa para o agente
    responder ao historico -- que e o engajamento que a TEC-233 recusou.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    # Sem pendencia a primeira passada ja retorna na recusa, sem chegar na
    # entrega da resposta -- entao nao ha excecao a capturar aqui.
    primeiro = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=falha,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )
    assert primeiro == "respondido"

    segundo_outbound = OutboundFake(get_sessionmaker())
    classificador = classificador_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=segundo_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )

    assert resultado == "reentrega_suprimida"
    assert classificador.chamadas == 0, "sem pendencia, o modelo nao e chamado"
    assert segundo_outbound.entregues == []
```

`OutboundFake` vem de `conftest` — acrescente ao import de `conftest` no topo do arquivo, junto de `CANAL_AGENTE` e `CONVERSA_AGENTE`. `pytest` também precisa estar importado.

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py -k retentativa --tb=short
```

Esperado: `test_retentativa_apos_recusa_entregue_responde_a_pendente` falha com `assert resultado == "respondido"` recebendo `"reentrega_suprimida"`, e `classificador.chamadas == 0`. É exatamente o defeito da card.

`test_retentativa_sem_pendencia_continua_so_recusando` deve **passar** desde já — ele trava o comportamento que não pode mudar.

- [ ] **Step 3: Implementar `reservado_em`**

Em `src/mobia/domain/outbound/repositorio.py`, depois de `kinds_reservados`:

```python
async def reservado_em(session_factory: Any, *, message_id: uuid.UUID, kind: str) -> datetime | None:
    """Quando a reserva deste (message_id, kind) foi commitada -- None se nao ha.

    **O instante importa, e nao so a existencia** (TEC-298, D1). A reserva e
    commitada ANTES do `_deliver` e a fala do agente so e gravada DEPOIS, entao
    este carimbo e estritamente anterior a linha OUTBOUND que a entrega produz.
    E o que permite reconstruir a fronteira que existia antes de uma recusa ja
    entregue -- ver `ha_fala_pendente_antes` em `messages/rajada.py`.

    Os dois carimbos sao `func.now()` do Postgres, entao a desigualdade nao
    depende de relogio de cliente nem de sincronia entre processos.

    **Presenca continua significando "encerrado", nao "entregue"** -- a mesma
    ressalva que `kinds_reservados` ja documenta por extenso. Quem usa este
    instante como teto esta perguntando "o que o agente ja tinha dito ANTES
    desta tentativa?", e para essa pergunta a distincao nao muda a resposta.
    """
    async with session_factory() as session:
        return await session.scalar(
            select(OutboundDispatch.created_at).where(
                OutboundDispatch.message_id == message_id,
                OutboundDispatch.kind == kind,
            )
        )
```

Acrescente `from datetime import datetime` ao topo do arquivo.

- [ ] **Step 4: Implementar o chamador e o guard em `turno.py`**

Importe `reservado_em` junto de onde `kinds_reservados` já é importado em `turno.py`.

No bloco da recusa, troque a chamada de `ha_fala_pendente_antes` por:

```python
            # TEC-298, D1. O teto vem da reserva da recusa, e so existe numa
            # RETENTATIVA: se a reserva ja esta la, uma passada anterior ja
            # entregou a recusa e a linha OUTBOUND dela ja esta em `messages`,
            # envenenando a fronteira. Na primeira passada isto e `None` e a
            # conta e exatamente a de antes desta card.
            teto_da_recusa = await reservado_em(
                session_factory, message_id=message.id, kind=KIND_DA_RECUSA_DE_ENTRADA
            )
            async with session_factory() as sessao_da_pendencia:
                tem_pendencia = await ha_fala_pendente_antes(
                    sessao_da_pendencia, message, teto_do_agente=teto_da_recusa
                )
```

E o guard:

```python
            if desfecho_da_recusa not in ("respondido", "reentrega_suprimida"):
                return desfecho_da_recusa
```

- [ ] **Step 5: Reescrever os dois comentários que a mudança deixou falsos**

Não é opcional — o CLAUDE.md trata comentário desatualizado como defeito, e estes dois descrevem exatamente o que mudou.

**(a)** O parágrafo do comentário do guard que hoje termina dizendo que a continuação não acontece para `"reentrega_suprimida"` e que "a pergunta pendente se perde nesta retentativa". Substitua esse parágrafo por:

```python
            # Ja `"reentrega_suprimida"` quer dizer o CONTRARIO de "nao
            # chegou": a reserva em `outbound_dispatches` ja existe porque
            # uma tentativa ANTERIOR entregou a recusa. Desde a TEC-298 ele
            # SEGUE para a continuacao, e e isso que faz a rota de
            # recuperacao da D4 sobreviver ao reprocessamento -- ate ela, o
            # turno fechava aqui e a pergunta pendente se perdia, porque
            # `PROCESSED` e terminal e nada reenfileira so a resposta que
            # ficou faltando.
```

**(b)** O comentário `TEC-295, D4, ruling R5` logo acima do cálculo de `tem_pendencia`. A frase final dele — *"resistir a 'simplificar' isto de volta para perto do uso e o ponto deste comentario"* — continua valendo; o que ele não diz é que a ordem sozinha não basta. Acrescente ao fim dele:

```python
            # **A ordem esta certa e nao era suficiente (TEC-298).** Ela
            # protege a PRIMEIRA passada. A seguinte encontra a recusa ja
            # gravada antes mesmo de o turno comecar, e para essa nenhuma
            # ordem de codigo ajuda -- quem resolve e o teto logo abaixo.
```

- [ ] **Step 6: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py tests/integration/test_rajada.py --tb=short
```

Esperado: todos passam. Se `test_bloqueada_com_pergunta_pendente_recusa_e_responde` quebrar, o teto está sendo aplicado na primeira passada — `reservado_em` deve devolver `None` ali, porque a reserva ainda não existe quando o cálculo roda.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/outbound/repositorio.py src/mobia/domain/agente/turno.py tests/integration/test_moderacao_de_entrada.py
git commit -m "$(cat <<'EOF'
feat(TEC-298): a retentativa depois da recusa entregue responde a pergunta pendente

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: O alarme da recusa para de dizer que algo sumiu

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — `_entregar_texto_fixo`, o `log.error("turno.reentrega_suprimida")` do fim
- Test: `tests/integration/test_moderacao_de_entrada.py`

**Interfaces:**
- Consumes: o dublê `_OutboundQueFalhaDepoisDaRecusa` da Task 2.
- Produces: o evento de log `turno.recusa_ja_reservada`, nível `warning`.

- [ ] **Step 1: Escrever o teste que falha**

No mesmo arquivo, depois dos testes da Task 2. `logging` já está importado no topo.

```python
async def test_recusa_ja_reservada_nao_alarma_como_dado_sumido(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
    caplog,
) -> None:
    """TEC-298, D4. A supressao da recusa nao e perda, e o log para de dizer que e.

    `error` e o nivel que o alerta observa -- o "alarme de dado sumido". Dispara-lo
    sobre uma recusa que a passada anterior entregou acorda alguem a toa, e ainda
    por cima no meio de um caso em que o que se perdeu foi OUTRA coisa.

    `warning` e nao `info` de proposito: a reserva sobrevivente e evidencia forte
    de entrega, nao prova. Ela tambem sobrevive se o worker morreu entre o commit
    da reserva e o `_deliver`, ou se o proprio `_liberar` falhou.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )

    with caplog.at_level(logging.INFO):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=OutboundFake(get_sessionmaker()),
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )

    erros = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not [r for r in erros if "turno.reentrega_suprimida" in r.getMessage()], (
        "a recusa suprimida nao pode acordar o alarme de dado sumido"
    )
    avisos = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "turno.recusa_ja_reservada" in r.getMessage()
    ]
    assert len(avisos) == 1
```

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py -k recusa_ja_reservada --tb=short
```

Esperado: falha na primeira asserta — hoje o `error` sai.

- [ ] **Step 3: Implementar**

Em `_entregar_texto_fixo`, substitua o bloco final que hoje é `log.error("turno.reentrega_suprimida", ...)` seguido de `return "reentrega_suprimida"` por:

```python
        # Mesmo raciocinio do bloco principal (ver `turno.reentrega_suprimida`
        # la embaixo): `send()` devolve False sem levantar quando a guarda ja
        # tem uma reserva para este (message_id, kind) de uma tentativa
        # anterior. Gravar aqui seria a mesma fala fantasma que aquele bloco
        # existe para evitar -- so que para o texto fixo do bloqueio.
        #
        # **A recusa de entrada e a excecao, e ela e o caminho ESPERADO desde a
        # TEC-298 (D4).** Quando a reserva dela sobrevive, o turno continua para
        # responder a pergunta pendente -- a supressao aqui e o mecanismo que
        # impede a recusa de sair duas vezes, nao um acidente. `error` e o
        # alarme de dado sumido, e dispara-lo sobre algo que a passada anterior
        # entregou e alarme falso.
        #
        # `warning` e nao `info`: a reserva sobrevivente e evidencia forte de
        # entrega, NAO e prova. Ela tambem sobrevive se o worker morreu entre o
        # commit da reserva e o `_deliver`, ou se o proprio `_liberar` falhou
        # (que tem alarme proprio, `outbound.liberacao_falhou`). Nessas duas
        # rotas a recusa de fato nao chegou, e `info` as esconderia. E a mesma
        # ressalva que `kinds_reservados` ja documenta: presenca significa
        # "encerrado", nao "entregue".
        if kind == KIND_DA_RECUSA_DE_ENTRADA:
            log.warning(
                "turno.recusa_ja_reservada",
                channel=message.channel,
                message_id=str(message.id),
            )
        else:
            log.error(
                "turno.reentrega_suprimida",
                channel=message.channel,
                message_id=str(message.id),
            )
        return "reentrega_suprimida"
```

O desfecho devolvido **não muda** — nenhum valor novo no `Literal` de `ResultadoDoTurno`, nenhum chamador a atualizar.

- [ ] **Step 4: Confirmar que as doze asserções existentes continuam valendo**

O desenho manda verificar uma a uma, e não assumir.

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py tests/integration/test_turno.py tests/integration/test_turno_atendimento_humano.py tests/integration/test_turno_optout.py tests/features/test_reprocessamento_apos_falha.py --tb=short
```

Esperado: todos passam. Elas exercitam a resposta, a confirmação de opt-out e a janela humana — nenhuma passa pelo kind da recusa. Se alguma falhar, ela **passa** pelo kind da recusa: atualize-a e anote a razão, que entra no comentário da card.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_moderacao_de_entrada.py
git commit -m "$(cat <<'EOF'
fix(TEC-298): a recusa ja reservada vira warning proprio, e nao o alarme de dado sumido

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: A fala já julgada não é remoderada

**Files:**
- Modify: `src/mobia/domain/messages/bloqueio.py` — nova `veredito_ja_registrado`, e a docstring de `marcar_bloqueada`
- Modify: `src/mobia/domain/agente/turno.py` — `_ModeracaoDoTurno.resolver`
- Test: `tests/integration/test_moderacao_de_entrada.py`

**Interfaces:**
- Consumes: os dublês e o molde das Tasks 2 e 3.
- Produces: `veredito_ja_registrado(session_factory, *, message_id: UUID) -> Veredito | None`.

- [ ] **Step 1: Escrever o teste que falha**

```python
async def test_retentativa_nao_repaga_a_moderacao_nem_duplica_a_auditoria(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D5. `bloqueada_em` ja e o veredito persistido do caso bloqueado.

    A retentativa nao pode pagar de novo por uma fala que ja foi julgada, nem
    gravar uma segunda linha de auditoria para a mesma recusa -- ver a Emenda
    E-04 da RN-04.5.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    moderador = moderador_fake(bloqueia_entrada=True)
    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador,
            agendador=AgendadorNoop(),
        )
    assert moderador.entradas == 1

    segundo_moderador = moderador_fake(bloqueia_entrada=True)
    await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=OutboundFake(get_sessionmaker()),
        moderador=segundo_moderador,
        agendador=AgendadorNoop(),
    )

    assert segundo_moderador.entradas == 0, "a fala ja estava carimbada; nao se paga de novo"
    await session.commit()
    eventos = await session.scalar(
        select(func.count())
        .select_from(ModerationEvent)
        .where(ModerationEvent.message_id == carregadora.id)
    )
    assert eventos == 1, "uma fala recusada, uma linha -- Emenda E-04 da RN-04.5"
```

Precisa de `from sqlalchemy import func, select` e `from mobia.domain.moderacao.models import ModerationEvent` no topo. Confira o que já está importado antes de acrescentar.

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py -k repaga --tb=short
```

Esperado: `assert segundo_moderador.entradas == 0` recebe `1`, e `eventos == 1` recebe `2`.

- [ ] **Step 3: Implementar `veredito_ja_registrado`**

Em `src/mobia/domain/messages/bloqueio.py`, depois de `moderar_entrada_e_marcar`:

```python
async def veredito_ja_registrado(
    session_factory: async_sessionmaker[AsyncSession], *, message_id: UUID
) -> Veredito | None:
    """O veredito que uma passada anterior ja gravou, ou None (TEC-298, D5).

    `bloqueada_em` nao-nulo e o veredito persistido do caso BLOQUEADO: so
    `marcar_bloqueada` escreve essa coluna, e ela escreve junto com o
    `ModerationEvent`, no mesmo commit. Uma retentativa que encontra o carimbo
    nao precisa pagar a moderacao de novo nem gravar uma segunda linha de
    auditoria para a mesma fala -- ver a Emenda E-04 da RN-04.5.

    **Devolve None para o caso LIBERADO, e isso nao e lacuna de implementacao.**
    "Moderou e liberou" nao e persistido em lugar nenhum: `bloqueada_em` nulo
    nao distingue "julgado e liberado" de "nunca julgado". A assimetria vem do
    desenho da TEC-236 e nao desta card. A consequencia e real e aceita: um
    turno que morre DEPOIS de uma moderacao limpa paga duas vezes.

    **O `motivo` volta vazio.** Ele nao e persistido -- so alimenta o log
    `moderacao.entrada_bloqueada`, que a passada anterior ja emitiu. Inventar
    um motivo aqui seria pior que a lacuna: quem lesse o log acreditaria nele.
    """
    async with session_factory() as session:
        bloqueada_em = await session.scalar(
            select(Message.bloqueada_em).where(Message.id == message_id)
        )
        if bloqueada_em is None:
            return None
        categoria = await session.scalar(
            select(ModerationEvent.categoria)
            .where(
                ModerationEvent.message_id == message_id,
                ModerationEvent.direcao == Direcao.ENTRADA.value,
            )
            .order_by(ModerationEvent.created_at.desc())
            .limit(1)
        )
        # `or CATEGORIA_OUTRO` pelo mesmo motivo de `moderar_entrada_e_marcar`:
        # a linha de auditoria pode nao existir se a retencao a levou (ela nao
        # tem FK para `messages`, de proposito -- ver o comentario de
        # `ModerationEvent.message_id`), e o veredito nao pode sair sem
        # categoria por causa de um registro que expirou.
        return Veredito(bloqueado=True, motivo="", categoria=categoria or CATEGORIA_OUTRO)
```

Acrescente `select` ao import do SQLAlchemy no topo do arquivo (hoje só `update`).

- [ ] **Step 4: Implementar o uso em `_ModeracaoDoTurno.resolver`**

Importe `veredito_ja_registrado` junto de `moderar_entrada_e_marcar` em `turno.py`. Dentro de `resolver`, entre o `if not self._corpo: return None` e a chamada a `moderar_entrada_e_marcar`:

```python
        # TEC-298, D5. Uma passada anterior pode ja ter julgado esta fala: o
        # carimbo de `bloqueada_em` e o veredito persistido do caso bloqueado.
        # Sem esta consulta, toda retentativa de turno bloqueado paga a
        # moderacao de novo e grava uma segunda linha de auditoria para a
        # MESMA recusa. Custa um SELECT por chave primaria contra uma chamada
        # de rede paga.
        ja_registrado = await veredito_ja_registrado(
            self._session_factory, message_id=self._message.id
        )
        if ja_registrado is not None:
            self._veredito = ja_registrado
            return self._veredito
```

- [ ] **Step 5: Reescrever a docstring de `marcar_bloqueada` (D6)**

O parágrafo final dela afirma hoje que a linha duplicada da segunda passada não é problema. Com a Task 4 a segunda passada não grava. Substitua esse parágrafo por:

```
    **A segunda passada do sweeper nao chega mais aqui (TEC-298, D5).** Ate
    aquela card, uma retentativa remoderava e esta funcao gravava uma segunda
    linha para a mesma fala -- e o argumento escrito aqui era que "duas
    tentativas de recusar a mesma fala foram duas recusas". Ele deixou de
    valer: `_ModeracaoDoTurno.resolver` consulta `veredito_ja_registrado`
    antes de chamar o moderador, e a linha de `moderation_events` passou a
    significar uma FALA recusada em vez de uma TENTATIVA de recusa. Quem
    audita conta falas -- ver a Emenda E-04 da RN-04.5.

    O `UPDATE` continua sendo idempotente de proposito: se uma rota futura
    voltar a passar por aqui duas vezes, reescrever o carimbo com a hora nova
    e inofensivo -- o que importa e a coluna deixar de ser NULL.
```

- [ ] **Step 6: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py tests/integration/test_moderacao_na_rajada.py tests/integration/test_bloqueio_e_auditoria.py tests/integration/test_registro_de_bloqueio.py tests/integration/test_moderacao_dos_ramos_que_retornam.py --tb=short
```

Esperado: todos passam. Atenção a `test_superada_reprovavel_recebe_marca_e_auditoria` em `test_moderacao_na_rajada.py`: ela roda `process_message` uma vez só, então não passa pelo caminho novo. E `test_moderacao_dos_ramos_que_retornam.py` é o arquivo da TEC-297 — os cinco ramos que retornam cedo também marcam `bloqueada_em`, então ele é o que pega uma regressão em `veredito_ja_registrado` que afete o primeiro julgamento.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/bloqueio.py src/mobia/domain/agente/turno.py tests/integration/test_moderacao_de_entrada.py
git commit -m "$(cat <<'EOF'
feat(TEC-298): a fala ja carimbada nao e remoderada, e a auditoria para de duplicar

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: A emenda ao SRS e a varredura de comentários

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` — RN-04.5
- Modify: `docs/superpowers/specs/2026-09-22-tec-298-pendencia-perdida-apos-recusa-design.md` — o `Status`

- [ ] **Step 1: Acrescentar a Emenda E-04 à RN-04.5**

Como item aninhado abaixo da regra, depois da Emenda E-03. **Nunca reescrevendo o texto de 22/08/2026**, e com acento (é prosa de `docs/`).

```markdown
  - **Emenda E-04 (TEC-298, 22/09/2026):** a linha de `moderation_events` que a Emenda E-01 definiu passa a significar **uma fala recusada**, e não uma tentativa de recusa. Até esta card, um turno que falhasse depois da moderação era reprocessado, a fala era julgada de novo e uma segunda linha era gravada para a mesma recusa — comportamento que a docstring de `marcar_bloqueada` registrava como aceito ("duas tentativas de recusar a mesma fala foram duas recusas"). A retentativa agora reconhece o carimbo de `bloqueada_em`, que só `marcar_bloqueada` escreve e que já é o veredito persistido do caso bloqueado, e não regrava. **Consequência para quem audita:** a contagem de recusas passa a ser de falas e não de tentativas — mais próxima do que a regra base diz, e diferente do que a tabela vinha registrando. **O caso liberado não mudou:** "moderou e liberou" continua sem ser persistido, então um turno que falha depois de uma moderação limpa continua sendo remoderado no reprocessamento. Ver a D5 e a D6 do desenho em `docs/superpowers/specs/2026-09-22-tec-298-pendencia-perdida-apos-recusa-design.md`.
```

- [ ] **Step 2: Marcar o desenho como implementado**

No cabeçalho do desenho, troque `**Status:** desenho` por `**Status:** implementado`.

- [ ] **Step 3: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Ela não é gate e não reprova nada — devolve a uma pessoa o julgamento sobre cada comentário. Reconfira cada `ALTERADO` e cada `VIZINHO` dentro de `_entregar_texto_fixo`, `_ModeracaoDoTurno`, `ha_fala_pendente_antes` e `marcar_bloqueada`. Os quatro comentários que este plano manda reescrever (Task 2 Step 5, Task 3 Step 3, Task 4 Step 5) já estão cobertos; o que a listagem pega é o que **não** mudou e ficou perto do que mudou.

Preste atenção especial em `PROSA` e `FALSO`: este plano e o desenho citam `arquivo.py` sem número na maioria dos casos, mas o desenho tem citações com linha na seção "O estado antes desta card".

- [ ] **Step 4: Rodar a suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — é o Postgres caindo sob o paralelismo. Rode por blocos:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
./.venv/Scripts/python.exe -m pytest tests/features --tb=short
```

Uma execução verde basta. Guarde o hash junto com o resultado. Se a primeira **falhar**, repita sobre a mesma árvore antes de culpar a mudança — é o que separa flake de regressão.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add docs/
git commit -m "$(cat <<'EOF'
docs(TEC-298): a E-04 da RN-04.5 diz que a linha de auditoria conta falas, nao tentativas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push e PR**

```bash
git push -u origin feat/tec-298-pendencia-perdida-apos-recusa
gh pr create --base main --title "TEC-298: a rota de recuperacao da TEC-295 sobrevive a retentativa" --body "..."
```

O corpo do PR termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 7: Comentar na card e mover para "Em análise"**

Não para "Feito" — quem mergeia é que fecha. O comentário registra o que some se ficar só no PR:

- **Divergência da card:** a decisão 1 dela (mexer na semântica de `ha_fala_pendente_antes`) foi descartada por falta de discriminador, e a decisão 2 (coluna nova) foi trocada pelo `created_at` da reserva — sem migration. A razão de cada uma está na D1 do desenho.
- **Critério de aceite não cumprido ao pé da letra:** "o alarme não dispara em falso quando a recusa já havia chegado". Daqui não há como saber que chegou, só que foi reservada; o alarme virou `warning` com nome próprio em vez de sumir. D4.
- **Lacuna que é decisão de produto:** turno que falha depois de uma moderação que **liberou** continua repagando a moderação no reprocessamento. Não é regressão nem defeito novo — é o escopo que a D5 declara fora.
- **A emenda E-04 à RN-04.5**, nomeada: a contagem de recusas na auditoria mudou de significado.

---

## Self-review

**Cobertura do desenho:** D1 → Task 1 e Task 2 Step 4. D2 → Task 1 Step 3 (a razão na docstring). D3 → Task 2 Step 4. D4 → Task 3. D5 → Task 4. D6 → Task 4 Step 5. D7 → travado por `test_retentativa_sem_pendencia_continua_so_recusando` (Task 2) e pelos testes existentes que a Task 3 Step 4 reconfere. Emenda E-04 → Task 5. Os cinco testes da seção "Testes" do desenho: (1) e (2) na Task 2, (3) na Task 4, (4) na Task 2, (5) na Task 1.

**Consistência de tipos:** `ha_fala_pendente_antes(..., *, teto_do_agente: datetime | None = None) -> bool` (Task 1) é consumida com esse nome exato na Task 2. `reservado_em(session_factory, *, message_id, kind) -> datetime | None` (Task 2 Step 3) é chamada com esses nomes no Step 4. `veredito_ja_registrado(session_factory, *, message_id) -> Veredito | None` (Task 4 Step 3) idem no Step 4.
