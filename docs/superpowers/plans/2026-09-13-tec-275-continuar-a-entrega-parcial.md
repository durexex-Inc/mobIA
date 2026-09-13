# TEC-275 — Continuar a entrega parcial: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a varredura reprocessa uma mensagem cuja entrega de fichas falhou no meio, a segunda passada termina a entrega em vez de refazer o turno — e a lista de pendentes continua sendo o que o lead viu.

**Architecture:** `Recomendacao` ganha três colunas (`message_id`, `preco_centavos`, `kind`) que tornam a apresentação um fato da mensagem e reconstruível sem rebuscar. No topo de `executar_turno`, antes de montar contexto, um desvio de três ramos decide entre turno normal, recomeço (nada saiu) e continuação. O laço de entrega é extraído para ser usado pelos dois caminhos, e a conciliação da continuação usa o carimbo ORIGINAL do lote.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-275-continuar-a-entrega-parcial-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, nesta ordem, antes de cada commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Testes de integração exigem `docker compose` de pé.** `tests/unit` não.
- Mensagem de commit: `tipo(TEC-275): o que passou a ser verdade`, português sem acento no assunto.
- Toda tabela nova em `TABELAS` (`tests/conftest.py`) entra no `TRUNCATE`. Este plano **não** cria tabela.
- Branch já existe: `feat/tec-275-retentativa-apaga-pendentes`, a partir de `0529c0f`.

## Estado de partida

Dois testes de integração já existem e estão **vermelhos de propósito** (commit `a4e1a2d`), em `tests/integration/test_recomendacao_e_reacao.py`:

- `test_retentativa_de_apresentacao_parcial_deixa_o_lead_sem_lista`
- `test_retentativa_com_reagir_falhando_fecha_as_mesmas_linhas_pelo_outro_caminho`

Eles são o critério de aceite. Ficam verdes na Task 6. **Não os altere antes disso** — se precisar mudá-los, a mudança é sinal de que o desenho mudou, e isso é conversa, não edição.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `alembic/versions/0031_apresentacao_com_dono.py` | **Criar.** As três colunas. |
| `src/mobia/domain/outbound/repositorio.py` | **Criar.** Uma função: quais kinds já têm reserva para uma mensagem. |
| `src/mobia/domain/agente/models.py` | As três colunas em `Recomendacao`. |
| `src/mobia/domain/agente/repositorio.py` | `gravar_recomendacoes` grava as três; leitor do lote por mensagem; deleção de uma linha. |
| `src/mobia/domain/agente/turno.py` | Laço de entrega extraído; o desvio de três ramos; a continuação. |
| `tests/integration/test_recomendacao_e_reacao.py` | Os dois vermelhos + os novos casos. |

---

### Task 1: As três colunas

**Files:**
- Create: `alembic/versions/0031_apresentacao_com_dono.py`
- Modify: `src/mobia/domain/agente/models.py:96` (depois de `apresentado_em`)
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Recomendacao.message_id: uuid.UUID | None`, `Recomendacao.preco_centavos: int | None`, `Recomendacao.kind: str | None`.

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/integration/test_recomendacao_e_reacao.py`:

```python
async def test_a_recomendacao_guarda_dono_preco_e_kind(session: Any) -> None:
    """TEC-275, D2. As tres colunas que tornam a apresentacao continuavel.

    Nullable as tres: linha anterior a esta card nao tem dono, e inventar um
    seria mentira (L2 do desenho).
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    imovel = await _imovel(session, "AP-910")

    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=imovel,
            score_match=Decimal("0.900"),
            motivo_match="3 quartos",
            apresentado_em=datetime.now(UTC),
            message_id=linha_da_mensagem.id,
            preco_centavos=30000000,
            kind="ficha_1",
        )
    )
    await session.commit()

    gravada = (await session.execute(select(Recomendacao))).scalars().one()
    assert gravada.message_id == linha_da_mensagem.id
    assert gravada.preco_centavos == 30000000
    assert gravada.kind == "ficha_1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k guarda_dono_preco_e_kind --tb=short
```

Esperado: FAIL com `TypeError: 'message_id' is an invalid keyword argument for Recomendacao`.

- [ ] **Step 3: Criar a migration**

`alembic/versions/0031_apresentacao_com_dono.py`:

```python
"""a apresentacao passa a ter dono, preco e kind

TEC-275, D2/D3/D9.

**As tres sao nullable, e nao e frouxidao.** Linha gravada antes desta card
nao tem mensagem dona, preco apresentado nem kind -- e nenhum dos tres e
derivavel depois do fato. `preco_centavos` em especial NAO pode ser
preenchido a partir de `imoveis`: a linha tem `preco_venda` e `preco_aluguel`
e nao diz qual foi mostrado, porque a operacao buscada so existe dentro de
`porta_de_busca` (D7 da TEC-162). Backfill aqui inventaria numero.

A consequencia esta na L2 do desenho: apresentacao anterior ao deploy nao e
continuavel, cai no ramo de turno normal, e o conjunto some sozinho conforme
as conversas avancam.

**`ondelete="SET NULL"` e nao CASCADE.** `outbound_dispatches` usa CASCADE
porque uma reserva sem mensagem nao significa nada. Aqui e o oposto: a linha
e a medida de conversao que a RN-10.3 existe para dar, e ela continua
verdadeira ("este imovel foi apresentado nesta conversa") depois de a
mensagem sumir. Perder o dono custa a continuacao; perder a linha custa o
historico.

O indice e parcial porque so o ramo da continuacao consulta por
`message_id`, e ele so alcanca linha que TEM dono.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recomendacoes", sa.Column("message_id", PgUUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_recomendacoes_message",
        "recomendacoes",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("recomendacoes", sa.Column("preco_centavos", sa.BigInteger(), nullable=True))
    op.add_column("recomendacoes", sa.Column("kind", sa.String(32), nullable=True))
    op.create_index(
        "ix_recomendacoes_message",
        "recomendacoes",
        ["message_id"],
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_recomendacoes_message", table_name="recomendacoes")
    op.drop_column("recomendacoes", "kind")
    op.drop_column("recomendacoes", "preco_centavos")
    op.drop_constraint("fk_recomendacoes_message", "recomendacoes", type_="foreignkey")
    op.drop_column("recomendacoes", "message_id")
```

- [ ] **Step 4: Acrescentar as colunas ao modelo**

Em `src/mobia/domain/agente/models.py`, logo depois de `apresentado_em` e antes de `__table_args__`:

```python
    # TEC-275, D2. Quem apresentou esta linha. Sem isto, "a apresentacao desta
    # mensagem" nao e consultavel -- so inferivel pelo `apresentado_em` mais
    # recente da conversa, que e inferencia e nao fato. Nullable: linha
    # anterior a TEC-275 nao tem dono (L2 do desenho).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # TEC-275, D3. O unico dos dez campos de `Ficha` que NAO sai da linha de
    # `imoveis`: a linha tem `preco_venda` e `preco_aluguel` e nao diz qual foi
    # mostrado, porque a operacao so existe dentro de `porta_de_busca`. Guarda
    # o preco JA RESOLVIDO -- o numero que o lead viu --, que e o que uma
    # continuacao precisa reproduzir.
    #
    # Isto NAO e uma segunda copia do preco do imovel: e um fato historico
    # sobre o que foi apresentado, e continua certo depois de o preco do
    # imovel mudar.
    preco_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # TEC-275, D9. O kind com que esta linha saiu. NAO reconstrua pela posicao:
    # quando a linha de uma ficha recusada e apagada (D8), ou quando um imovel
    # some do catalogo (D7), as linhas restantes re-indexam e toda posicao
    # depois do buraco desloca -- a continuacao leria a reserva errada.
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

Acrescente `BigInteger` aos imports de `sqlalchemy` no topo do arquivo.

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k guarda_dono_preco_e_kind --tb=short
```

Esperado: PASS. Se vier `relation ... does not exist` ou erro de coluna, a fixture `migrar_banco` não aplicou a 0031 nos bancos dos workers — ver a seção sobre carimbo adiantado no CLAUDE.md.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0031_apresentacao_com_dono.py src/mobia/domain/agente/models.py tests/integration/test_recomendacao_e_reacao.py
git commit -m "feat(TEC-275): a recomendacao guarda dono, preco apresentado e kind"
```

---

### Task 2: `gravar_recomendacoes` preenche as três

**Files:**
- Modify: `src/mobia/domain/agente/repositorio.py:132-230` (`gravar_recomendacoes`)
- Modify: `src/mobia/domain/agente/turno.py:2028-2038` (a chamada)
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Consumes: as colunas da Task 1.
- Produces: `gravar_recomendacoes(..., message_id: uuid.UUID, kinds: Sequence[str], ...)`. A partir daqui toda linha nova tem dono, preço e kind.

**O alinhamento que esta task tem de preservar:** `gravar_recomendacoes` recebe `candidatos=[c for c in escolhidos if uuid.UUID(c["imovel_id"]) in encontrados]`, e `fichas` vem de `fichas_do_catalogo(ids=ids)`, que devolve "na ordem pedida" derrubando quem não tem linha. As duas listas têm a **mesma ordem e o mesmo comprimento**, então o índice `i` de uma é o índice `i` da outra — e é por isso que `KINDS_DAS_FICHAS[i]` serve para as duas. O teste do Step 1 trava isso.

- [ ] **Step 1: Write the failing test**

```python
async def test_cada_linha_apresentada_guarda_o_kind_com_que_saiu(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """TEC-275, D9. O kind da linha e o kind com que a ficha saiu, na ordem.

    Trava o alinhamento entre a lista que `gravar_recomendacoes` recebe e a
    que o laco de entrega enumera: as duas saem de `escolhidos` filtrado por
    `encontrados`, na mesma ordem, entao o indice de uma e o da outra. Se
    alguem inserir um filtro ou uma reordenacao em so uma delas, o kind passa
    a apontar para a ficha errada e este teste cai.
    """
    from mobia.domain.agente.turno import KINDS_DAS_FICHAS

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-91{n}", quartos=3, preco_venda=30000000 + n)

    classificador = _ClassificadorQueBuscaSemFiltroExtra({"operacao": "VENDA", "quartos_min": 3})
    outbound = outbound_fake()
    assert (
        await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
        == "respondido"
    )

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]
    linhas = {
        registro.imovel_id: registro
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert len(linhas) == 3
    for posicao, imovel_id in enumerate(apresentados):
        assert linhas[imovel_id].kind == KINDS_DAS_FICHAS[posicao]
        assert linhas[imovel_id].message_id is not None
        assert linhas[imovel_id].preco_centavos == 30000000 + posicao
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k guarda_o_kind_com_que_saiu --tb=short
```

Esperado: FAIL — `kind` é `None`.

- [ ] **Step 3: Acrescentar os parâmetros a `gravar_recomendacoes`**

Na assinatura, depois de `criterios`:

```python
    message_id: uuid.UUID,
    kinds: Sequence[str],
```

No docstring, acrescente um parágrafo antes de `**Toda apresentacao vira linha**`:

```
    **`kinds` vem do chamador, e nao e derivado aqui.** O kind e posicional
    (`KINDS_DAS_FICHAS[posicao]`) e quem enumera as posicoes e o laco de
    entrega. Esta funcao recebe `candidatos` com a MESMA ordem e o MESMO
    filtro que aquele laco usa, entao o indice bate -- mas depender disso em
    silencio seria frageis: quem passa os kinds e quem sabe deles. Ver a D9
    do desenho da TEC-275 para por que reconstruir a posicao depois nao
    funciona.
```

No corpo, dentro do `for`, troque o `enumerate`:

```python
    for posicao, candidato in enumerate(candidatos):
```

e acrescente ao dict de `linhas.append`:

```python
                "message_id": message_id,
                "preco_centavos": int(candidato["preco_centavos"]),
                "kind": kinds[posicao],
```

- [ ] **Step 4: Passar os novos argumentos na chamada**

Em `src/mobia/domain/agente/turno.py`, na chamada a `gravar_recomendacoes`, acrescente depois de `criterios=criterios,`:

```python
        message_id=message.id,
        kinds=KINDS_DAS_FICHAS[: len(fichas)],
```

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py --tb=short
```

Esperado: o novo PASSA; os dois da TEC-275 continuam FAILED (é cedo); o resto PASSA.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "feat(TEC-275): toda linha apresentada nasce com dono, preco e kind"
```

---

### Task 3: A linha da ficha recusada é apagada no instante da recusa

**Files:**
- Modify: `src/mobia/domain/agente/repositorio.py` (nova função)
- Modify: `src/mobia/domain/agente/turno.py` (o `except EnvioRecusado` do laço)
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Produces: `apagar_recomendacao_nao_entregue(session_factory, *, channel: str, conversation_key: str, imovel_id: uuid.UUID, apresentado_em: datetime) -> None`

**Por quê (D8):** a conciliação apaga a linha da ficha recusada **depois** do laço. Se o turno morre no meio, essa limpeza nunca acontece, e "existe reserva" deixa de significar "o lead recebeu" — porque falha permanente **mantém** a reserva de propósito. A continuação (Task 6) leria essa reserva como entrega feita e a linha de um imóvel que o lead nunca viu sobreviveria como pendente.

- [ ] **Step 1: Write the failing test**

```python
async def test_ficha_recusada_some_mesmo_quando_o_turno_morre_depois(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D8. A delecao da linha recusada nao pode depender do fim do laco.

    Ficha 1 recusada (permanente, a reserva FICA), ficha 3 retentavel -- o
    turno morre antes da conciliacao. Sem a delecao antecipada a linha da
    ficha 1 sobrevive, e ela e um imovel que o lead nunca viu ocupando um
    ordinal.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9A{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RecusaAPrimeiraEFalhaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioRecusado("http 400 codigo 131053")
            if kind == KINDS_DAS_FICHAS[2]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=_RecusaAPrimeiraEFalhaNaTerceira(get_sessionmaker()),
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    assert classificador.resultado is not None
    recusado = uuid.UUID(classificador.resultado.candidatos[0]["imovel_id"])
    gravados = {
        registro.imovel_id
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert recusado not in gravados, (
        "a linha da ficha recusada tem de sumir na hora da recusa -- esperar o fim "
        "do laco perde a limpeza quando o turno morre no meio"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k morre_depois --tb=short
```

Esperado: FAIL — o imóvel recusado ainda está gravado.

- [ ] **Step 3: A função de deleção**

Em `src/mobia/domain/agente/repositorio.py`, logo depois de `conciliar_apresentacao`:

```python
async def apagar_recomendacao_nao_entregue(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    imovel_id: uuid.UUID,
    apresentado_em: datetime,
) -> None:
    """A linha de uma ficha que NAO chegou ao lead, apagada na hora. TEC-275, D8.

    Mesmo recorte de `conciliar_apresentacao` no ramo `nao_entregues`, e pelas
    mesmas razoes: apaga em vez de fechar (o UNIQUE por conversa e para
    sempre, e linha fechada tornaria o imovel inalcancavel pelo resto da
    conversa), e exige `reacao_lead IS NULL` mais o carimbo deste lote, para
    nunca tocar a linha de uma apresentacao anterior em que o lead de fato viu
    o imovel.

    **Por que existe separada da conciliacao.** La a delecao roda DEPOIS do
    laco, junto com o fechamento -- que precisa de `houve_entrega`, e
    `houve_entrega` so se conhece no fim. A delecao nao precisa: ela depende
    so do que acabou de acontecer com esta ficha. Enquanto as duas andavam
    juntas, um turno que morria no meio do laco levava a limpeza junto, e a
    linha de um imovel que o lead nunca viu sobrevivia como pendente.

    Isso deixou de ser um detalhe quando a continuacao (D4) passou a ler as
    reservas de `outbound_dispatches` para saber o que ja saiu: falha
    permanente MANTEM a reserva de proposito, entao sem esta delecao a
    continuacao leria a recusa como entrega feita.
    """
    async with session_factory() as session:
        await session.execute(
            delete(Recomendacao).where(
                Recomendacao.channel == channel,
                Recomendacao.conversation_key == conversation_key,
                Recomendacao.imovel_id == imovel_id,
                Recomendacao.apresentado_em == apresentado_em,
                Recomendacao.reacao_lead.is_(None),
            )
        )
        await session.commit()
```

- [ ] **Step 4: Chamar no `except EnvioRecusado`**

Em `turno.py`, dentro do `except EnvioRecusado as exc:` do laço de `_apresentar`, depois do `log.error` e antes do `nao_entregues.append(ficha.id)`:

```python
            # D8 da TEC-275: apaga AGORA, e nao no fim do laco. A conciliacao
            # la embaixo nao roda se o laco morrer numa ficha seguinte -- e
            # falha permanente MANTEM a reserva, entao a continuacao leria
            # esta recusa como entrega feita.
            await apagar_recomendacao_nao_entregue(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
                imovel_id=ficha.id,
                apresentado_em=agora,
            )
```

Mantenha o `nao_entregues.append(ficha.id)`: a conciliação do caminho feliz continua recebendo a lista, e o `delete` dela vira no-op para esta linha (já não existe). Isso é de propósito — a lista também alimenta o `houve_entrega` e a leitura de quem opera.

Acrescente `apagar_recomendacao_nao_entregue` ao import de `repositorio` no topo de `turno.py`.

- [ ] **Step 5: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py tests/integration/test_apresentacao_no_turno.py --tb=short
```

Esperado: o novo PASSA; `test_ficha_recusada_nao_deixa_linha_de_imovel_que_o_lead_nunca_viu` continua PASSANDO (agora por outra porta); os dois da TEC-275 seguem FAILED.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "fix(TEC-275): a linha da ficha recusada some na recusa, nao no fim do laco"
```

---

### Task 4: Os dois leitores

**Files:**
- Create: `src/mobia/domain/outbound/repositorio.py`
- Modify: `src/mobia/domain/agente/repositorio.py`
- Test: `tests/integration/test_recomendacao_e_reacao.py`

**Interfaces:**
- Produces:
  - `kinds_reservados(session_factory, *, message_id: uuid.UUID) -> frozenset[str]`
  - `LinhaDaApresentacao` (dataclass: `imovel_id: uuid.UUID`, `preco_centavos: int`, `kind: str`, `apresentado_em: datetime`)
  - `ler_apresentacao_da_mensagem(session_factory, *, message_id: uuid.UUID) -> tuple[LinhaDaApresentacao, ...]`

- [ ] **Step 1: Write the failing test**

```python
async def test_ler_apresentacao_da_mensagem_devolve_o_lote_na_ordem_apresentada(
    session: Any, session_factory: Any
) -> None:
    """TEC-275, D5. Mesma ordenacao de `ler_pendentes`, escopo por mensagem.

    A ordem e o ordinal, e reusar a regra de `ler_pendentes` em vez de
    escrever uma segunda e o ponto: duas copias podem divergir, e o preco da
    divergencia e a reacao do lead grudando no imovel errado.

    Ao contrario de `ler_pendentes`, NAO filtra por `reacao_lead IS NULL`: a
    continuacao precisa do lote inteiro para mapear kind, inclusive linha que
    ja tenha reacao.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente.repositorio import ler_apresentacao_da_mensagem

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    agora = datetime.now(UTC)
    esperados = []
    for posicao, (codigo, score) in enumerate(
        (("AP-9B0", "0.900"), ("AP-9B1", "0.800"), ("AP-9B2", "0.700"))
    ):
        imovel = await _imovel(session, codigo)
        esperados.append(imovel)
        session.add(
            Recomendacao(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                imovel_id=imovel,
                score_match=Decimal(score),
                motivo_match="3 quartos",
                apresentado_em=agora,
                message_id=linha_da_mensagem.id,
                preco_centavos=30000000 + posicao,
                kind=f"ficha_{posicao + 1}",
            )
        )
    # Linha de OUTRA mensagem, na mesma conversa: nao pode entrar no lote.
    outra = await _imovel(session, "AP-9B9")
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=outra,
            score_match=Decimal("0.950"),
            motivo_match="3 quartos",
            apresentado_em=agora - timedelta(hours=1),
            message_id=None,
            preco_centavos=1,
            kind="ficha_1",
        )
    )
    await session.commit()

    lote = await ler_apresentacao_da_mensagem(
        session_factory, message_id=linha_da_mensagem.id
    )
    assert [linha.imovel_id for linha in lote] == esperados
    assert [linha.kind for linha in lote] == ["ficha_1", "ficha_2", "ficha_3"]
    assert [linha.preco_centavos for linha in lote] == [30000000, 30000001, 30000002]
    assert all(linha.apresentado_em == agora for linha in lote)


async def test_kinds_reservados_devolve_o_que_ja_tem_reserva(session: Any) -> None:
    """TEC-275, D4. A reserva e o que diz se aquela ficha ja saiu.

    Reserva committada ANTES do efeito externo, liberada so em
    `EnvioRetentavel`/cancelamento -- entao presenca significa "esta posicao
    esta encerrada, nao reenviamos", que e o contrato que a continuacao usa.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.outbound.models import OutboundDispatch
    from mobia.domain.outbound.repositorio import kinds_reservados
    from mobia.infra.db import get_sessionmaker

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    session.add(
        OutboundDispatch(id=uuid.uuid4(), message_id=linha_da_mensagem.id, kind="ficha_1")
    )
    await session.commit()

    assert await kinds_reservados(
        get_sessionmaker(), message_id=linha_da_mensagem.id
    ) == frozenset({"ficha_1"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k "ler_apresentacao_da_mensagem or kinds_reservados" --tb=short
```

Esperado: FAIL com `ImportError` / `ModuleNotFoundError`.

- [ ] **Step 3: Criar `src/mobia/domain/outbound/repositorio.py`**

```python
"""Leitura das reservas de envio. TEC-275.

Arquivo proprio, e nao uma consulta dentro de `domain/agente`: a reserva e
fato do dominio de saida, e quem pergunta por ela (a continuacao da entrega)
nao devia precisar conhecer o schema de `outbound_dispatches`.
"""

import uuid
from typing import Any

from sqlalchemy import select

from mobia.domain.outbound.models import OutboundDispatch


async def kinds_reservados(session_factory: Any, *, message_id: uuid.UUID) -> frozenset[str]:
    """Os kinds que esta mensagem ja reservou.

    **Presenca significa "encerrado", nao "entregue".** A reserva e committada
    ANTES do efeito externo e so e liberada em `EnvioRetentavel` ou
    cancelamento (ver `GuardedOutbound.send`): falha permanente a MANTEM, de
    proposito, porque nao havera outra tentativa. Quem le isto para decidir o
    que reenviar esta perguntando "esta posicao ainda vai sair?", e a resposta
    certa para uma recusa permanente e nao.

    A linha que a recusa deixa em `recomendacoes` e apagada na hora da recusa
    (`apagar_recomendacao_nao_entregue`, D8 da TEC-275), entao a assimetria
    entre "reservado" e "entregue" nao vaza para a lista de pendentes.
    """
    async with session_factory() as session:
        linhas = await session.execute(
            select(OutboundDispatch.kind).where(OutboundDispatch.message_id == message_id)
        )
    return frozenset(linhas.scalars().all())
```

- [ ] **Step 4: O leitor do lote**

Em `src/mobia/domain/agente/repositorio.py`, depois de `ler_pendentes`:

```python
@dataclass(frozen=True, slots=True)
class LinhaDaApresentacao:
    """Uma linha do lote que uma mensagem apresentou. TEC-275.

    Distinta de `RecomendacaoPendente`, que e o que o MODELO le (titulo e
    bairro, sem preco -- ver o docstring dela). Esta e o que a continuacao
    precisa para remontar a ficha: o preco apresentado e o kind com que ela
    saiu. Duas leituras diferentes da mesma tabela, com dois consumidores
    diferentes; fundi-las obrigaria uma das duas a carregar campo que nao usa.
    """

    imovel_id: uuid.UUID
    preco_centavos: int
    kind: str
    apresentado_em: datetime


async def ler_apresentacao_da_mensagem(
    session_factory: Any, *, message_id: uuid.UUID
) -> tuple[LinhaDaApresentacao, ...]:
    """O lote que ESTA mensagem apresentou, na ordem em que apresentou. TEC-275.

    **Mesma ordenacao de `ler_pendentes`** (`apresentado_em`, `score_match`
    DESC, `imovel_id`), e a mesma razao: aquela ordem reproduz a ordem de
    apresentacao real, porque e a ordem que `buscar` usa e nada entre a busca
    e a gravacao reordena. Escrever uma segunda regra aqui criaria duas copias
    que podem divergir, e o preco da divergencia e o ordinal do lead apontando
    para outro imovel.

    **NAO filtra `reacao_lead IS NULL`, e essa e a diferenca para
    `ler_pendentes`.** A continuacao precisa do lote inteiro para saber qual
    kind pertence a qual imovel; uma linha que ja ganhou reacao continua sendo
    parte do que aquela mensagem apresentou.

    **Linha sem `message_id` nunca entra**, e o filtro por igualdade ja
    garante isso: apresentacao anterior a TEC-275 nao tem dono e nao e
    continuavel (L2 do desenho).

    Devolve so linha completa -- as tres colunas da D2 preenchidas. Uma linha
    com dono mas sem kind seria de uma gravacao pela metade, que nenhum
    caminho de hoje produz; se aparecer, ficar de fora e mais seguro que
    entrar e deslocar posicao.
    """
    consulta = (
        select(
            Recomendacao.imovel_id,
            Recomendacao.preco_centavos,
            Recomendacao.kind,
            Recomendacao.apresentado_em,
        )
        .where(
            Recomendacao.message_id == message_id,
            Recomendacao.preco_centavos.is_not(None),
            Recomendacao.kind.is_not(None),
        )
        .order_by(
            Recomendacao.apresentado_em,
            Recomendacao.score_match.desc(),
            Recomendacao.imovel_id,
        )
    )
    async with session_factory() as session:
        linhas = (await session.execute(consulta)).all()

    return tuple(
        LinhaDaApresentacao(
            imovel_id=linha.imovel_id,
            preco_centavos=linha.preco_centavos,
            kind=linha.kind,
            apresentado_em=linha.apresentado_em,
        )
        for linha in linhas
    )
```

Confirme que `dataclass` e `datetime` já estão importados no topo do arquivo; se não, acrescente.

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k "ler_apresentacao_da_mensagem or kinds_reservados" --tb=short
```

Esperado: PASS nos dois.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "feat(TEC-275): o lote de uma mensagem e as reservas dela viram consulta"
```

---

### Task 5: Extrair o laço de entrega (refactor puro)

**Files:**
- Modify: `src/mobia/domain/agente/turno.py:2040-2130`
- Test: os que já existem.

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class ResultadoDaEntrega:
      legendas: tuple[str, ...]
      entregues: int
      suprimidas: int
      nao_entregues: tuple[uuid.UUID, ...]

  async def _entregar_fichas(
      session_factory: async_sessionmaker[AsyncSession],
      *,
      message: Message,
      outbound: OutboundPort,
      fichas: Sequence[Ficha],
      kinds: Sequence[str],
      apresentado_em: datetime,
      prosa: str | None,
      pular: frozenset[str] = frozenset(),
  ) -> ResultadoDaEntrega
  ```

**Nada de comportamento muda nesta task.** É o passo que evita duas cópias do laço que fala com a Meta — e este repo já registra, no comentário de `KINDS_DA_RESPOSTA`, o que custa ter dois caminhos de entrega que divergem.

- [ ] **Step 1: Rodar a suíte dos arquivos afetados e guardar o resultado**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_recomendacao_e_reacao.py --tb=short
```

Anote quantos passam e quantos falham. Este número é o critério: depois do refactor tem de ser **idêntico**.

- [ ] **Step 2: Extrair**

Mova o laço `for posicao, ficha in enumerate(fichas):` de `_apresentar` para uma função nova, logo acima de `_apresentar`:

```python
@dataclass(frozen=True, slots=True)
class ResultadoDaEntrega:
    """O que o laco de entrega de fato conseguiu. TEC-275."""

    legendas: tuple[str, ...]
    entregues: int
    suprimidas: int
    nao_entregues: tuple[uuid.UUID, ...]


async def _entregar_fichas(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    fichas: Sequence[Ficha],
    kinds: Sequence[str],
    apresentado_em: datetime,
    prosa: str | None,
    pular: frozenset[str] = frozenset(),
) -> ResultadoDaEntrega:
    """O laco que fala com a Meta, um por ficha. TEC-275.

    Extraido de `_apresentar` para ter UM laco, e nao dois: a continuacao
    (D4) entrega pelo mesmo caminho. Duas copias de um laco de entrega
    divergem -- o comentario de `KINDS_DA_RESPOSTA`, neste arquivo, registra o
    que isso ja custou.

    **`kinds` e paralelo a `fichas`**, e vem de quem chama porque e quem chama
    que sabe de onde ele veio: na apresentacao e `KINDS_DAS_FICHAS[:n]`; na
    continuacao e o kind PERSISTIDO de cada linha, que nao e reconstruivel
    pela posicao (D9).

    **`prosa` e `None` na continuacao.** A prosa viaja na primeira ficha (D5
    da TEC-162), e uma continuacao so existe se alguma ficha ja saiu -- entao
    a primeira ja saiu, e com ela a prosa.

    **`pular` sao os kinds que ja tem reserva.** A guarda de `send` suprimiria
    esses envios de qualquer jeito, mas pular explicitamente evita usar a
    reserva como controle de fluxo e evita contar como `suprimidas` algo que
    nem foi tentado.
    """
    legendas: list[str] = []
    nao_entregues: list[uuid.UUID] = []
    entregues = suprimidas = 0

    for posicao, ficha in enumerate(fichas):
        kind = kinds[posicao]
        if kind in pular:
            continue

        # So a primeira leva a prosa (D5); as outras sao ficha pura.
        legenda = legenda_de(ficha, prefixo=prosa if posicao == 0 else None)
        payload: dict[str, Any] = {
            "para": message.conversation_key,
            "de": message.recipient_external_id,
        }
        if ficha.foto is None:
            # D13: sem foto, cai no caminho de texto que ja existe em vez de
            # ganhar um ramo proprio.
            payload["texto"] = legenda
        else:
            payload["tipo"] = "imagem"
            payload["link"] = ficha.foto
            payload["legenda"] = legenda

        try:
            entrou = await outbound.send(message.id, kind, payload)
        except EnvioForaDaJanela:
            raise
        except EnvioRetentavel:
            log.error(
                "apresentacao.entrega_parcial_antes_de_falha_retentavel",
                channel=message.channel,
                message_id=str(message.id),
                kind=kind,
                entregues=entregues,
            )
            raise
        except EnvioRecusado as exc:
            log.error(
                "apresentacao.ficha_recusada",
                channel=message.channel,
                message_id=str(message.id),
                kind=kind,
                reason=str(exc),
            )
            await apagar_recomendacao_nao_entregue(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
                imovel_id=ficha.id,
                apresentado_em=apresentado_em,
            )
            nao_entregues.append(ficha.id)
            continue

        if not entrou:
            suprimidas += 1
            nao_entregues.append(ficha.id)
            continue

        entregues += 1
        legendas.append(legenda)

    return ResultadoDaEntrega(
        legendas=tuple(legendas),
        entregues=entregues,
        suprimidas=suprimidas,
        nao_entregues=tuple(nao_entregues),
    )
```

**Preserve os comentários longos** que hoje moram dentro do laço em `_apresentar` — os do `except EnvioForaDaJanela` (por que vem antes) e do `except EnvioRetentavel` (por que não disputa MRO). Eles explicam a ordem das cláusulas e a ordem continua sendo a mesma.

- [ ] **Step 3: `_apresentar` passa a chamar a função**

Substitua o laço removido por:

```python
    entrega = await _entregar_fichas(
        session_factory,
        message=message,
        outbound=outbound,
        fichas=fichas,
        kinds=KINDS_DAS_FICHAS[: len(fichas)],
        apresentado_em=agora,
        prosa=prosa,
    )
```

e o fim de `_apresentar`:

```python
    await conciliar_apresentacao(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        agora=agora,
        nao_entregues=entrega.nao_entregues,
        houve_entrega=entrega.entregues > 0,
    )

    return "\n\n".join(entrega.legendas), entrega.entregues, entrega.suprimidas
```

- [ ] **Step 4: Verificar que nada mudou**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_recomendacao_e_reacao.py --tb=short
```

Esperado: **exatamente** o mesmo resultado do Step 1. Qualquer diferença é regressão do refactor, não progresso.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "refactor(TEC-275): o laco de entrega de fichas vira funcao propria"
```

---

### Task 6: O desvio de três ramos e a continuação

**Files:**
- Modify: `src/mobia/domain/agente/turno.py:593` (o desvio) e uma função nova
- Test: os dois vermelhos ficam verdes.

**Interfaces:**
- Consumes: `ler_apresentacao_da_mensagem`, `kinds_reservados`, `_entregar_fichas`, `apagar_recomendacao_nao_entregue`, `conciliar_apresentacao`.
- Produces: `_continuar_entrega(...) -> ResultadoDoTurno`.

- [ ] **Step 1: Confirmar o estado vermelho**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k retentativa --tb=line
```

Esperado: 2 failed. São eles que esta task vira.

- [ ] **Step 2: Escrever a continuação**

Em `turno.py`, acima de `executar_turno`:

```python
async def _continuar_entrega(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    lote: Sequence[LinhaDaApresentacao],
    ja_reservados: frozenset[str],
) -> ResultadoDoTurno:
    """Termina a entrega que a passada anterior comecou. TEC-275, D1.

    **Nao rebusca, nao chama o classificador, nao chama `reagir`.** E isso que
    fecha os DOIS caminhos pelos quais a retentativa apagava a lista de
    pendentes: nenhum dos dois chega a rodar. Fechar cada um com uma guarda
    propria seria frageis -- a terceira rota que aparecesse ficaria de fora.

    **Concilia com o carimbo ORIGINAL do lote, e nao com um `now()` novo.**
    E a outra metade do conserto: com o carimbo do lote, as linhas dele
    deixam de ser `apresentado_em < agora` e a conciliacao nao tem o que
    fechar. Com um carimbo novo, fechava as tres -- que era o defeito.

    **Imovel que sumiu do catalogo entre as passadas entra em
    `nao_entregues`** (D7): a conciliacao apaga a linha dele e o lead recebe o
    que restou, sem aviso. A lista de pendentes fica com o que ele de fato
    viu, que e a invariante que esta card existe para proteger.
    """
    apresentado_em = lote[0].apresentado_em
    ids = [linha.imovel_id for linha in lote]
    precos = {linha.imovel_id: linha.preco_centavos for linha in lote}
    kind_de = {linha.imovel_id: linha.kind for linha in lote}

    fichas = await fichas_do_catalogo(session_factory, ids=ids, precos=precos)
    encontrados = {ficha.id for ficha in fichas}
    sumiram = [imovel_id for imovel_id in ids if imovel_id not in encontrados]
    if sumiram:
        # Mesmo criterio de nivel do `fichas_sumiram_do_catalogo` de
        # `_apresentar`: quem opera precisa saber QUAL imovel sumiu.
        log.warning(
            "continuacao.fichas_sumiram_do_catalogo",
            channel=message.channel,
            message_id=str(message.id),
            imovel_ids_faltantes=[str(i) for i in sumiram],
        )

    entrega = await _entregar_fichas(
        session_factory,
        message=message,
        outbound=outbound,
        fichas=fichas,
        kinds=[kind_de[ficha.id] for ficha in fichas],
        apresentado_em=apresentado_em,
        prosa=None,
        pular=ja_reservados,
    )

    await conciliar_apresentacao(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        agora=apresentado_em,
        nao_entregues=tuple(entrega.nao_entregues) + tuple(sumiram),
        houve_entrega=True,
    )

    log.info(
        "turno.entrega_continuada",
        channel=message.channel,
        message_id=str(message.id),
        entregues=entrega.entregues,
        ja_estavam_fora=len(ja_reservados),
    )
    return "respondido" if entrega.entregues else "reentrega_suprimida"
```

**`houve_entrega=True` é fixo, e não `entrega.entregues > 0`:** uma continuação só existe porque alguma ficha já saiu numa passada anterior. A pergunta que `houve_entrega` responde é "esta apresentação chegou ao lead?", e a resposta é sim mesmo quando esta passada não enviou nada novo.

- [ ] **Step 3: O desvio de três ramos**

Em `executar_turno`, imediatamente antes do `try:` que monta contexto (hoje `turno.py:593`):

```python
    # TEC-275, D4. Antes de montar contexto de proposito: a continuacao nao
    # precisa de contexto, nao chama o classificador e nao chama `reagir` --
    # e e justamente por nao chamar `reagir` que ela nao fecha como NEUTRO as
    # pendentes da passada anterior.
    #
    # Tres ramos, e o do meio existe por um caso limite real: se a ficha que
    # falhou foi a PRIMEIRA, nada chegou ao lead -- nem as fichas, nem a prosa,
    # que viaja junto com a ficha 1 e nao esta persistida em lugar nenhum se
    # nao chegou a sair. Continuar uma entrega em que nada saiu nao e
    # continuar; e recomecar. E as linhas orfas tem de ser APAGADAS, nao
    # ignoradas: o `ON CONFLICT DO NOTHING` da passada nova preservaria o
    # carimbo velho, e o UNIQUE por conversa impediria a linha nova de nascer.
    lote = await ler_apresentacao_da_mensagem(session_factory, message_id=message.id)
    if lote:
        ja_reservados = await kinds_reservados(session_factory, message_id=message.id)
        if ja_reservados & {linha.kind for linha in lote}:
            return await _continuar_entrega(
                session_factory,
                message=message,
                outbound=outbound,
                lote=lote,
                ja_reservados=ja_reservados,
            )
        log.warning(
            "turno.apresentacao_sem_entrega_descartada",
            channel=message.channel,
            message_id=str(message.id),
            linhas=len(lote),
        )
        await apagar_apresentacao_da_mensagem(session_factory, message_id=message.id)
```

- [ ] **Step 4: A deleção das órfãs**

Em `repositorio.py`, depois de `apagar_recomendacao_nao_entregue`:

```python
async def apagar_apresentacao_da_mensagem(session_factory: Any, *, message_id: uuid.UUID) -> None:
    """Apaga o lote de uma apresentacao que nao chegou ao lead. TEC-275, D4.

    So e chamada quando NENHUMA ficha daquele lote saiu -- nao ha reserva
    nenhuma dos kinds dele. As linhas existem porque `gravar_recomendacoes`
    roda ANTES do laco de entrega (a L1 da TEC-162), e o turno morreu antes de
    qualquer envio.

    **Apagar, e nao deixar para a passada nova.** O `ON CONFLICT DO NOTHING`
    preservaria o `apresentado_em` velho, e o UNIQUE por conversa impediria a
    linha da apresentacao nova de nascer -- o imovel ficaria com carimbo de
    uma apresentacao que nunca aconteceu.

    `reacao_lead IS NULL` na clausula porque uma linha que ganhou reacao veio
    de apresentacao que o lead VIU; se ela carrega este `message_id`, algo
    fora deste caminho a escreveu, e apagar destruiria opiniao do lead.
    """
    async with session_factory() as session:
        await session.execute(
            delete(Recomendacao).where(
                Recomendacao.message_id == message_id,
                Recomendacao.reacao_lead.is_(None),
            )
        )
        await session.commit()
```

Acrescente aos imports de `turno.py`: `LinhaDaApresentacao`, `apagar_apresentacao_da_mensagem`, `ler_apresentacao_da_mensagem` (de `repositorio`) e `kinds_reservados` (de `mobia.domain.outbound.repositorio`).

- [ ] **Step 5: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py tests/integration/test_apresentacao_no_turno.py --tb=short
```

Esperado: **os dois da TEC-275 PASSAM** e nada mais quebra.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "fix(TEC-275): a retentativa continua a entrega em vez de refazer o turno"
```

---

### Task 7: Os casos de borda

**Files:**
- Test: `tests/integration/test_recomendacao_e_reacao.py`

Nenhum código novo. Se algum destes reprovar, o defeito está nas Tasks 1-6.

- [ ] **Step 1: Escrever os três testes**

```python
async def test_continuacao_entrega_o_que_restou_quando_um_imovel_sumiu(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D7. Imovel fora do catalogo entre as passadas nao vira pendente.

    A ficha 2 falha de forma retentavel; antes da retentativa o imovel 3 sai
    do catalogo. O lead recebe 1 e 2, e a lista de pendentes tem so esses
    dois -- se o 3 sobrevivesse, "o segundo" do proximo turno ja estaria
    deslocado.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9C{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaSegunda(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    # O terceiro sai do catalogo entre as passadas. `delete` direto porque a
    # Recomendacao tem FK para `imoveis` -- apaga a linha dela junto, que e
    # exatamente o estado que a D7 descreve.
    await session.execute(delete(Recomendacao).where(Recomendacao.imovel_id == apresentados[2]))
    await session.execute(delete(Imovel).where(Imovel.id == apresentados[2]))
    await session.commit()

    assert await _rodar(OutboundFake(get_sessionmaker()), _ClassificadorQueBuscaESemReacao({})) in (
        "respondido",
        "reentrega_suprimida",
    )
    assert await _pendentes_da_conversa(session_factory) == (apresentados[0], apresentados[1])


async def test_quando_nada_saiu_a_retentativa_roda_o_turno_inteiro(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D4. Ficha 1 falha retentavel: nada chegou, entao recomeca.

    Nao ha o que continuar -- nem fichas, nem a prosa, que viaja com a ficha 1
    e nao esta persistida. A retentativa roda o turno inteiro, e as linhas
    orfas da primeira passada nao sobrevivem para deslocar ordinal.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9D{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaPrimeira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    primeiro = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaPrimeira(get_sessionmaker()), primeiro)

    segunda = OutboundFake(get_sessionmaker())
    segundo = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, segundo) == "respondido"

    assert len(segunda.entregues) == 3, (
        "nada tinha saido, entao a retentativa apresenta as tres do zero -- com a prosa"
    )
    assert segundo.apresentados_recebidos is None, (
        "as linhas orfas da passada 1 foram apagadas, entao nao havia pendente "
        "para `reagir` receber"
    )
    assert len(await _pendentes_da_conversa(session_factory)) == 3


async def test_continuacao_usa_o_kind_persistido_e_nao_a_posicao(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D9. O caso que a reconstrucao posicional erra.

    Ficha 1 recusada (a linha dela some na hora, D8) e ficha 3 retentavel. Na
    continuacao o lote tem DUAS linhas, e a que falta e a de kind `ficha_3`.
    Reconstruindo pela posicao, ela viraria `ficha_2` -- que ja tem reserva --
    e a continuacao nao enviaria nada, deixando o lead sem a terceira ficha e
    com uma pendente que ele nunca viu.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9E{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RecusaAPrimeiraEFalhaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioRecusado("http 400 codigo 131053")
            if kind == KINDS_DAS_FICHAS[2]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RecusaAPrimeiraEFalhaNaTerceira(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    segunda = OutboundFake(get_sessionmaker())
    assert await _rodar(segunda, _ClassificadorQueBuscaESemReacao({})) == "respondido"

    assert len(segunda.entregues) == 1, "so a ficha 3 faltava sair"
    assert await _pendentes_da_conversa(session_factory) == (apresentados[1], apresentados[2]), (
        "a recusada nao pode estar na lista, e a terceira tem de estar -- se a "
        "continuacao reconstruiu o kind pela posicao, a terceira nunca saiu"
    )
```

Acrescente `Imovel` e `delete` aos imports do arquivo de teste se ainda não estiverem.

- [ ] **Step 2: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py --tb=short
```

Esperado: tudo PASSA. Se o terceiro reprovar, a Task 6 está reconstruindo o kind em vez de ler a coluna.

- [ ] **Step 3: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Se falhar, repita **sobre a mesma árvore** antes de culpar a mudança — e lembre que `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "test(TEC-275): catalogo mudado, nada entregue e kind deslocado"
```

---

### Task 8: Comentários tocados e o PR

- [ ] **Step 1: A listagem obrigatória**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia **cada** `ALTERADO` e **cada** `VIZINHO`. Atenção especial a estes, que este plano sabe estarem desatualizados:

- o docstring de `gravar_recomendacoes` sobre gravar antes da entrega — continua certo, mas agora tem uma contraparte a mais;
- o docstring de `conciliar_apresentacao`, que descreve o recorte `apresentado_em == agora` como "as linhas que ESTA chamada inseriu" — na continuação não é esta chamada que inseriu; o texto precisa dizer "as linhas DESTE lote";
- o comentário `# `< agora` e nao `!=`` dentro de `conciliar_apresentacao`, que argumenta sobre o lote de hoje ser o mais novo — na continuação o lote **não** é o mais novo, e o que o protege é o carimbo passado pelo chamador;
- o comentário de `KINDS_DAS_FICHAS`, que explica por que o kind é posicional — continua verdadeiro e agora tem um segundo consumidor.

- [ ] **Step 2: Emenda ao SRS, se houver**

Se a continuação mudar o que a RN-10.3 afirma sobre "toda apresentação é registrada", entre com item aninhado `Emenda E-nn (TEC-275, 2026-09-13)` **abaixo** da regra, sem reescrever o texto de 22/08/2026.

- [ ] **Step 3: Abrir o PR**

```bash
git push -u origin feat/tec-275-retentativa-apaga-pendentes
gh pr create --base main --title "TEC-275: a retentativa continua a entrega em vez de refazer o turno" --body "..."
```

- [ ] **Step 4: Comentar na card e mover para "Em análise"**

O comentário precisa registrar o que some se ficar só no PR:

- **A divergência em relação ao texto original da card:** ela propunha distinguir apresentações dentro de `conciliar_apresentacao`. Isso fecharia só um dos dois caminhos. O desenho foi por outro lado.
- **O que não foi exercitado:** o percurso por `sweep_stalled` → `process_message` (L1 do desenho).
- **A lacuna que é decisão de produto:** quando um imóvel some do catálogo entre as passadas, o lead recebe duas fichas de três e **não é avisado** (D7).
- **O que a card não entrega:** duas mensagens da mesma conversa processadas concorrentemente continuam sem cobertura (L3).
- **`message_id` nullable** deixa apresentações anteriores ao deploy não continuáveis (L2).

---

## Auto-revisão deste plano

**Cobertura da spec:** D1 → Task 6. D2 → Task 1. D3 → Tasks 1-2. D4 → Task 6 (os três ramos) + Task 7 (o ramo "nada saiu"). D5 → Task 4. D6 → Task 6. D7 → Tasks 6-7. D8 → Task 3. D9 → Tasks 2, 4 e 7. L1/L2/L3 → Task 8, no comentário da card.

**Consistência de tipos:** `LinhaDaApresentacao` é criada na Task 4 e consumida na Task 6 com os mesmos quatro campos. `ResultadoDaEntrega` é criada na Task 5 e consumida nas Tasks 5 e 6. `_entregar_fichas` tem a mesma assinatura nos dois usos. `kinds_reservados` devolve `frozenset[str]`, e é assim que a Task 6 a usa (`&` com um set de kinds).

**Ponto de atenção para quem executar:** a Task 5 é refactor puro e o critério dela é *o mesmo resultado de antes*, não *mais testes passando*. Se os dois vermelhos ficarem verdes na Task 5, algo mudou de comportamento onde não devia.
