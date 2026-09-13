# TEC-273 — Liberar as reservas irmãs: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma falha retentável numa das partes da resposta libera as reservas de **todas** as partes daquela resposta, para que a retentativa entregue uma geração inteira em vez de colar metade de um texto na metade de outro.

**Architecture:** Um módulo novo (`domain/outbound/kinds.py`) passa a possuir o vocabulário de kinds de saída e os grupos — conjuntos de kinds que carregam uma mesma resposta regenerável. `GuardedOutbound._liberar` passa a apagar o grupo inteiro em vez de um kind só. As fichas ficam deliberadamente fora de qualquer grupo, porque a retentativa delas repete estado persistido (TEC-275) em vez de regenerar.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-273-liberar-reservas-irmas-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, nesta ordem, antes de cada commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- Testes de integração exigem `docker compose` de pé. `tests/unit` não.
- Commit: `tipo(TEC-273): o que passou a ser verdade`, português sem acento no assunto.
- **Nenhuma migration.** Esta card não toca schema.
- Branch já existe: `feat/tec-273-liberar-reservas-irmas`, a partir de `65e10d8`.

## Estado de partida

Suíte inteira: **1893 passed / 0 failed**. Os três gates verdes.

## Duas armadilhas que este plano já mapeou

**1. NÃO renomeie `_liberar`.** `tests/integration/test_reserva_liberada.py:54` tem um dublê (`OutboundLiberacaoFalha`) que **sobrescreve `_liberar`** para simular o delete explodindo. Renomear o método faria o override deixar de ser chamado — o teste passaria a exercitar o código real em silêncio e continuaria verde, afirmando algo que não testa mais. O nome fica; o corpo muda.

**2. `test_liberar_so_apaga_a_reserva_do_kind_que_falhou` (mesmo arquivo, ~linha 168) sobrevive à mudança, e é de propósito.** Ele libera `reply` e afirma que a reserva de `ack` fica de pé. Como `ack` não pertence ao grupo de `reply`, a asserta continua valendo — **e ele vira o teste de fronteira mais importante desta card.** O que precisa mudar nele é só o docstring, que hoje diz `AND kind = :k`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/outbound/kinds.py` | **Criar.** O vocabulário de kinds e quais formam uma resposta só. |
| `src/mobia/domain/outbound/port.py` | `_liberar` apaga o grupo; docstring do Protocol. |
| `src/mobia/domain/agente/turno.py` | importa os kinds do módulo novo; o ramo da D4; a guarda da D5. |
| `tests/integration/test_reserva_liberada.py` | o mecanismo e a fronteira. |
| `tests/integration/` (arquivo da resposta em duas partes) | os dois cenários Gherkin. |

---

### Task 1: O módulo que possui os kinds

**Files:**
- Create: `src/mobia/domain/outbound/kinds.py`
- Modify: `src/mobia/domain/agente/turno.py:88-111` (as duas constantes saem) e o bloco de imports
- Test: `tests/unit/test_kinds_de_saida.py` (criar)

**Interfaces:**
- Consumes: nada.
- Produces:
  - `KIND_DA_RESPOSTA: str` e `KINDS_DA_RESPOSTA: tuple[str, ...]` em `mobia.domain.outbound.kinds`
  - `grupo_de(kind: str) -> tuple[str, ...]` — os kinds que saem e voltam juntos com `kind`; devolve `(kind,)` quando ele não pertence a grupo nenhum.

**Por que `grupo_de` devolve `(kind,)` e não `()` para kind sem grupo:** o chamador fica uniforme — sempre libera `grupo_de(kind)`, sem um `if` para o caso comum. Um `()` obrigaria o port a lembrar de incluir o próprio kind, e esquecer disso deixaria a reserva que falhou presa.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_kinds_de_saida.py`:

```python
"""O vocabulario de kinds de saida e os grupos. TEC-273."""

from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA, grupo_de


def test_as_duas_partes_da_resposta_sao_um_grupo() -> None:
    """Qualquer parte da resposta devolve as DUAS, e nao so ela.

    E o que faz uma falha retentavel na parte 2 liberar tambem a reserva da
    parte 1: sem isso, a retentativa reentrega so a parte 2, com o texto de
    uma geracao nova, colada a parte 1 da geracao velha.
    """
    assert grupo_de(KIND_DA_RESPOSTA) == KINDS_DA_RESPOSTA
    assert grupo_de(KINDS_DA_RESPOSTA[1]) == KINDS_DA_RESPOSTA


def test_kind_sem_grupo_devolve_so_ele_mesmo() -> None:
    """O chamador libera `grupo_de(kind)` sempre, sem ramo para o caso comum.

    Devolver `()` obrigaria o port a lembrar de somar o proprio kind, e
    esquecer disso deixaria presa justamente a reserva que falhou.
    """
    assert grupo_de("ack") == ("ack",)


def test_as_fichas_nao_formam_grupo() -> None:
    """Decisao D1, e nao omissao.

    A retentativa de uma apresentacao REPETE o lote persistido (TEC-275), sem
    chamar o modelo -- nao ha duas geracoes para misturar. A reserva de uma
    ficha e o que impede o lead de receber a mesma ficha duas vezes, e
    liberar em grupo esvaziaria o sinal de que `_continuar_entrega` depende.
    """
    for kind in ("ficha_1", "ficha_2", "ficha_3"):
        assert grupo_de(kind) == (kind,)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_kinds_de_saida.py --tb=short
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.outbound.kinds'`.

- [ ] **Step 3: Criar o módulo**

`src/mobia/domain/outbound/kinds.py`:

```python
"""O vocabulario de kinds de saida, e quais deles formam uma resposta so.

TEC-273. Mora aqui, e nao dentro de `port.py`, pelo padrao que
`KIND_DA_CONFIRMACAO_DE_OPTOUT` ja estabelece: o kind vive no modulo que
possui o comportamento, e o port importa de la.

E nao pode continuar em `domain/agente/turno.py`, de onde veio: `port.py`
precisa dele agora, e `domain/outbound` nao pode importar de `domain/agente`
-- a dependencia ja corre no sentido contrario.
"""

KIND_DA_RESPOSTA = "reply"

# Dois kinds e nao um repetido, pelo mesmo motivo de `KINDS_DAS_FICHAS`: a
# `UNIQUE (message_id, kind)` de `outbound_dispatches` e o que torna o
# reprocessamento seguro, e duas mensagens com o mesmo kind fariam a segunda
# ser suprimida como reentrega -- o lead receberia metade da resposta em
# silencio.
#
# O primeiro continua sendo `KIND_DA_RESPOSTA` e nao um nome novo: ha linhas
# em `outbound_dispatches` gravadas com "reply" desde antes da quebra em duas
# mensagens existir, e trocar o nome faria a guarda deixar de reconhece-las.
KINDS_DA_RESPOSTA = (KIND_DA_RESPOSTA, "reply_2")

# Os grupos: conjuntos de kinds que carregam UMA resposta regeneravel.
#
# **As fichas nao estao aqui, e e decisao.** A retentativa de uma apresentacao
# repete o lote persistido (TEC-275, D1) em vez de chamar o modelo de novo,
# entao nao ha duas geracoes para misturar -- e a reserva de cada ficha e
# justamente o sinal que diz "esta ja saiu, nao reenvie". Poe-las num grupo
# esvaziaria esse sinal e faria `_continuar_entrega` nunca ser tomada.
_GRUPOS: tuple[tuple[str, ...], ...] = (KINDS_DA_RESPOSTA,)


def grupo_de(kind: str) -> tuple[str, ...]:
    """Os kinds que saem e voltam JUNTOS com `kind`. TEC-273.

    Devolve `(kind,)` quando ele nao pertence a grupo nenhum, e nao `()`: o
    chamador fica uniforme, liberando sempre `grupo_de(kind)`. Com `()` o
    port teria de lembrar de somar o proprio kind, e esquecer disso deixaria
    presa exatamente a reserva que acabou de falhar.
    """
    for grupo in _GRUPOS:
        if kind in grupo:
            return grupo
    return (kind,)
```

- [ ] **Step 4: Tirar as constantes de `turno.py`**

Remova `KIND_DA_RESPOSTA` e `KINDS_DA_RESPOSTA` de `turno.py` (linhas ~88-111, incluindo o comentário longo, que vai junto para o módulo novo) e acrescente ao bloco de imports:

```python
from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA
```

Ponha um comentário curto no lugar de onde as constantes saíram, no mesmo espírito do que `turno.py` já escreve para o kind de opt-out:

```python
# `KIND_DA_RESPOSTA` e `KINDS_DA_RESPOSTA` mudaram para
# `domain/outbound/kinds.py` na TEC-273: `port.py` passou a precisar deles
# para liberar as reservas irmas, e `domain/outbound` nao pode importar de
# `domain/agente`. Quem importava daqui continua funcionando -- o nome fica no
# namespace deste modulo por causa do import acima.
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_kinds_de_saida.py --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_formato_no_turno.py tests/integration/test_optout_guarda.py --tb=short
```

Esperado: PASS em tudo. Os três arquivos de integração importam os kinds **de `turno.py`** e são a prova de que a reexportação funciona — se algum falhar com `ImportError`, o Step 4 apagou demais.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "refactor(TEC-273): o vocabulario de kinds de saida ganha modulo proprio"
```

---

### Task 2: A liberação apaga o grupo

**Files:**
- Modify: `src/mobia/domain/outbound/port.py` (`_liberar`, ~linha 317)
- Test: `tests/integration/test_reserva_liberada.py`

**Interfaces:**
- Consumes: `grupo_de` da Task 1.
- Produces: `GuardedOutbound._liberar(message_id, kind)` passa a apagar toda reserva de `grupo_de(kind)`. **O nome do método não muda** — ver a armadilha 1 no topo deste plano.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_reserva_liberada.py`:

```python
async def test_liberar_apaga_a_reserva_da_parte_irma(session) -> None:
    """TEC-273. A parte 1 entregue perde a reserva quando a parte 2 falha.

    Sem isto, a retentativa do sweeper reentrega so a parte 2 -- com o texto
    de uma chamada NOVA ao modelo --, e o lead le a primeira metade de um
    texto colada na segunda metade de outro. Corrupcao silenciosa: ele nao
    tem como saber que leu duas fontes, e nada no sistema diz.
    """
    from mobia.domain.outbound.kinds import KINDS_DA_RESPOSTA

    message_id = await uma_mensagem(session)

    parte_1 = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await parte_1.send(message_id, KINDS_DA_RESPOSTA[0], {}) is True
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 1

    parte_2 = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("http 429"))
    try:
        await parte_2.send(message_id, KINDS_DA_RESPOSTA[1], {})
    except EnvioRetentavel:
        pass

    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[1]) == 0
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 0, (
        "a reserva da parte JA ENTREGUE tem de cair junto -- e ela que faria a "
        "retentativa suprimir a parte 1 da geracao nova"
    )


async def test_liberar_uma_ficha_nao_arrasta_as_outras(session) -> None:
    """TEC-273, fronteira com a TEC-275. As fichas NAO formam grupo.

    A retentativa de uma apresentacao repete o lote persistido em vez de
    chamar o modelo, entao nao ha geracoes para misturar -- e a reserva de
    cada ficha e o sinal de que `_continuar_entrega` depende para saber o que
    ja saiu. Se alguem "simplificar" a liberacao para o `message_id` inteiro,
    este teste cai, e a continuacao da TEC-275 deixaria de ser tomada em
    silencio.
    """
    message_id = await uma_mensagem(session)

    entregue = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await entregue.send(message_id, "ficha_1", {}) is True

    falha = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("http 503"))
    try:
        await falha.send(message_id, "ficha_2", {})
    except EnvioRetentavel:
        pass

    assert await reservas_por_kind(session, message_id, "ficha_1") == 1, (
        "a reserva da ficha entregue tem de SOBREVIVER -- e ela que diz a "
        "continuacao da TEC-275 que aquela ficha ja chegou ao lead"
    )
    assert await reservas_por_kind(session, message_id, "ficha_2") == 0
```

- [ ] **Step 2: Run tests to verify the first fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_reserva_liberada.py --tb=short
```

Esperado: `test_liberar_apaga_a_reserva_da_parte_irma` FALHA (a reserva da parte 1 sobrevive, `1 != 0`). `test_liberar_uma_ficha_nao_arrasta_as_outras` **já passa** — ele descreve o comportamento atual e existe para travá-lo.

- [ ] **Step 3: Mudar o corpo de `_liberar`**

Em `src/mobia/domain/outbound/port.py`, acrescente ao import:

```python
from mobia.domain.outbound.kinds import grupo_de
```

E troque o corpo de `_liberar` (o nome fica):

```python
    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        """Apaga a reserva de `kind` e as dos kinds do mesmo grupo. TEC-273.

        **Por que o grupo, e nao so o kind que falhou.** Uma resposta longa sai
        em duas mensagens, com kind proprio para cada (TEC-140). Liberando so
        a que falhou, a retentativa do sweeper -- que roda o turno inteiro, com
        uma chamada NOVA ao modelo -- encontra a reserva da parte 1 viva, tem
        essa parte suprimida, e entrega a parte 2 do texto NOVO. O lead le a
        primeira metade de um texto colada na segunda metade de outro.

        Este repo ja decidiu que duplicata e melhor que perda ("a duplicata e
        visivel e recuperavel e o silencio nao", TEC-134/TEC-227). O caso acima
        nao e nenhum dos dois: e corrupcao silenciosa de conteudo, e o lead nao
        tem como saber que leu duas fontes. Liberando o grupo, a retentativa
        reentrega a parte 1 da geracao nova -- uma duplicata visivel, que e o
        lado que aquele precedente ja escolheu.

        **Grupo, e nao `message_id`.** As fichas compartilham a mensagem com a
        resposta e NAO formam grupo (ver `kinds.py`): a retentativa delas
        repete o lote persistido em vez de regenerar, e a reserva de cada uma
        e o sinal que `_continuar_entrega` (TEC-275) le para saber o que ja
        saiu. Apagar por `message_id` esvaziaria esse sinal e faria a
        continuacao nunca ser tomada.
        """
        irmaos = grupo_de(kind)
        async with self._session_factory() as session:
            await session.execute(
                delete(OutboundDispatch).where(
                    OutboundDispatch.message_id == message_id,
                    OutboundDispatch.kind.in_(irmaos),
                )
            )
            await session.commit()
        log.warning(
            "outbound.reserva_liberada",
            message_id=str(message_id),
            kind=kind,
            kinds_liberados=list(irmaos),
        )
```

- [ ] **Step 4: Atualizar o docstring do teste que já existia**

`test_liberar_so_apaga_a_reserva_do_kind_que_falhou` continua passando — `ack` não pertence ao grupo de `reply`. Só o docstring ficou falso (`AND kind = :k`). Troque por:

```python
    """O `IN (grupo)` e o que impede um reply liberado de arrastar o ack junto.

    Era `AND kind = :k` ate a TEC-273. O que mudou foi o recorte, nao a
    garantia: `ack` nao pertence a grupo nenhum, entao continua de pe.
    """
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_reserva_liberada.py tests/integration/test_cancelamento_do_worker.py --tb=short
```

Esperado: tudo PASSA. `test_cancelamento_do_worker.py` entra porque o cancelamento divide a mesma cláusula (D3) e este é o momento em que ele começa a liberar o grupo também.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "fix(TEC-273): a falha retentavel libera as reservas de toda a resposta"
```

---

### Task 3: O primeiro cenário Gherkin, ponta a ponta

**Files:**
- Test: `tests/integration/test_formato_no_turno.py` (acrescentar; é onde a resposta em duas partes já é exercitada)

**Interfaces:**
- Consumes: a liberação em grupo da Task 2.
- Produces: nada — é teste.

**O que este teste prova que o da Task 2 não prova:** a Task 2 mede o mecanismo de reserva isoladamente. Este mede o que o **lead recebe** depois de o turno inteiro rodar duas vezes, com o classificador devolvendo textos diferentes em cada passada. É o critério de aceite da card.

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/integration/test_formato_no_turno.py`:

```python
async def test_retentativa_da_parte_2_nao_mistura_geracoes(
    session: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-273, cenario 1 do Gherkin. As duas partes vem da MESMA geracao.

    Passada 1: a parte 1 sai, a parte 2 toma um 429. Antes desta card a
    reserva de `reply` sobrevivia, e na passada 2 -- que roda o turno inteiro
    com uma chamada NOVA ao modelo -- a parte 1 do texto B era suprimida e so
    a parte 2 de B saia. O lead lia a primeira metade de A colada a segunda
    metade de B, sem nada no sistema dizer.

    Com a liberacao em grupo, a passada 2 reentrega as DUAS partes de B. O
    lead ve uma duplicata da primeira metade -- visivel e recuperavel, que e o
    lado que o precedente TEC-134/TEC-227 escolheu.
    """
    from conftest import ClassificadorFake, OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    texto_a = "A" * 400 + " " + "a" * 400
    texto_b = "B" * 400 + " " + "b" * 400

    class _ClassificadorComRoteiro(ClassificadorFake):  # type: ignore[misc, valid-type]
        """Um texto diferente por passada -- e o que torna a mistura visivel.

        Molde de `ResumidorFake(roteiro=...)`, que este repo ja usa para o
        mesmo fim: sem textos distintos, "veio da mesma geracao" nao e uma
        afirmacao que qualquer asserta consiga fazer.
        """

        def __init__(self, roteiro: list[str]) -> None:
            super().__init__(resposta=roteiro[0])
            self.roteiro = roteiro

        async def classificar(self, contexto: Any, *, porta: Any = None) -> Any:
            self.resposta = self.roteiro[min(self.chamadas, len(self.roteiro) - 1)]
            return await super().classificar(contexto, porta=porta)

    linha = await semear_entrada(session)

    class _RetentavelNaParte2(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRetentavel("http 429")
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

    primeira = _RetentavelNaParte2(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await _rodar(primeira, _ClassificadorComRoteiro([texto_a, texto_b]))

    assert len(primeira.entregues) == 1, (
        "o teste so vale se a passada 1 entregou UMA parte e parou na segunda"
    )

    segunda = OutboundFake(get_sessionmaker())
    assert await _rodar(segunda, _ClassificadorComRoteiro([texto_b, texto_b])) == "respondido"

    assert len(segunda.entregues) == 2, (
        "a passada 2 tem de reentregar as DUAS partes -- se so uma saiu, a "
        "reserva da parte 1 sobreviveu e a mistura continua"
    )
    entregue = "".join(segunda.entregues)
    assert "A" not in entregue, (
        f"nenhuma parte da geracao anterior pode sobrar colada a esta. Entregue: {entregue[:120]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py -k nao_mistura_geracoes --tb=short
```

**Se ele já passar**, pare e reporte: significa que a Task 2 cobriu o caminho inteiro e este teste não está exercitando o que descreve — provavelmente o texto não quebrou em duas partes. Confira que `quebrar_em_mensagens(texto_a)` devolve dois itens antes de concluir qualquer coisa.

- [ ] **Step 3: Nenhuma implementação**

Este teste deve passar com o código da Task 2. Se falhar, o defeito está lá, não aqui.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "test(TEC-273): a retentativa entrega uma geracao inteira, nao duas metades"
```

---

### Task 4: A fronteira com a TEC-275, ponta a ponta

**Files:**
- Test: `tests/integration/test_recomendacao_e_reacao.py` (acrescentar)

**O que este teste protege:** que a liberação em grupo **não** regrediu o caminho vizinho. A continuação da TEC-275 depende de `kinds_reservados` devolver os kinds das fichas já entregues; se alguém alargar o grupo para o `message_id` inteiro, ela deixa de ser tomada e o turno volta a rodar inteiro — em silêncio, porque o lead ainda recebe fichas.

- [ ] **Step 1: Write the failing test**

```python
async def test_a_continuacao_sobrevive_a_liberacao_em_grupo_da_tec_273(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-273, fronteira. A liberacao de irmas nao alcanca as fichas.

    A TEC-275 le as reservas de ficha para saber o que ja saiu. Se a TEC-273
    liberasse por `message_id`, elas sumiriam numa falha retentavel, a
    intersecao ficaria vazia, e `_continuar_entrega` nunca seria tomada -- o
    turno inteiro rodaria de novo, com chamada paga ao modelo, e o lead
    receberia fichas de qualquer jeito. A regressao seria invisivel sem esta
    asserta.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-8A{n}", quartos=3, preco_venda=30000000 + n)

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

    classificador_1 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador_1)

    assert classificador_1.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador_1.resultado.candidatos]

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "a continuacao nao chama o classificador -- ver `resultado` preenchido significa "
        "que o desvio nao foi tomado, e a liberacao em grupo alcancou as fichas"
    )
    assert len(segunda.entregues) == 2, "so as fichas 2 e 3 faltavam sair"
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados)
```

- [ ] **Step 2: Run it**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_recomendacao_e_reacao.py -k sobrevive_a_liberacao --tb=short
```

Esperado: PASS com o código atual. Este teste trava comportamento existente; ele não deve ficar vermelho primeiro.

- [ ] **Step 3: Provar que ele morde**

Sonda temporária: em `src/mobia/domain/outbound/kinds.py`, troque `_GRUPOS` por `(KINDS_DA_RESPOSTA, ("ficha_1", "ficha_2", "ficha_3"))` e rode de novo. O teste tem de FALHAR na asserta de `classificador_2.resultado`. **Reverta a sonda** e confirme `git diff --stat src/` vazio.

Registre a saída da sonda no report: um teste de fronteira que não morde não protege nada.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "test(TEC-273): a liberacao em grupo nao alcanca as fichas da TEC-275"
```

---

### Task 5: Parte suprimida antes de uma entregue deixa de ser caminho normal

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (o ramo `if not entrou:` / `continue`, ~linha 1656-1686)
- Test: `tests/integration/test_formato_no_turno.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: nada — comportamento interno de `executar_turno`.

**O contexto (D4):** hoje, quando `send` devolve `False` e nada saiu ainda, o laço faz `continue` e tenta a próxima parte. O comentário chama isso de *"o caso legitimo da retentativa do sweeper"*. Com a Task 2 aquela retentativa não produz mais esse estado — as reservas do grupo caem juntas. O que ainda produz é uma **reserva presa**: a liberação que falha por deadlock ou conexão caída, que `port.py` já antecipa e loga como `outbound.liberacao_falhou`. Isso é anomalia, e a transcrição não pode gravar o texto inteiro por causa dela.

- [ ] **Step 1: Write the failing test**

```python
async def test_parte_suprimida_antes_de_uma_entregue_nao_e_gravada_como_entregue(
    session: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TEC-273, cenario 2 do Gherkin. A transcricao carrega so o que saiu.

    Uma reserva presa (a liberacao que falha por deadlock, que `port.py` ja
    antecipa) faz a parte 1 ser suprimida e a parte 2 sair. Antes desta card o
    laco fazia `continue`, `entrega_parcial` nunca era marcada, e o recorder
    gravava o texto INTEIRO -- a transcricao que o corretor le no handoff
    afirmava que o texto novo saiu completo.
    """
    from conftest import ClassificadorFake, OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.models import OutboundDispatch
    from mobia.infra.db import get_sessionmaker

    texto = "P" * 400 + " " + "q" * 400
    linha = await semear_entrada(session)

    # A reserva PRESA, plantada a mao: e exatamente o estado que sobra quando
    # o delete da liberacao falha por deadlock ou conexao caida -- o caso que
    # `port.py` ja antecipa e loga como `outbound.liberacao_falhou`.
    session.add(
        OutboundDispatch(id=uuid.uuid4(), message_id=linha.id, kind=KINDS_DA_RESPOSTA[0])
    )
    await session.commit()

    with caplog.at_level("ERROR"):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=ClassificadorFake(resposta=texto),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=OutboundFake(get_sessionmaker()),
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    gravado = "".join(texto for texto, _, _ in await _falas_do_agente(session))
    assert "q" * 400 in gravado, "premissa: a parte 2 saiu e tem de estar na transcricao"
    assert "P" * 400 not in gravado, (
        "a parte que a reserva suprimiu nao pode entrar na transcricao -- e ela "
        "que o corretor le no handoff"
    )
    assert "turno.entrega_parcial_da_resposta" in caplog.text
    assert resultado != "respondido", (
        "um turno cuja primeira parte nunca saiu nao respondeu por inteiro"
    )
```

**Dois detalhes de setup que este step precisa:** `import uuid` e `from mobia.domain.outbound.models import OutboundDispatch` no topo do arquivo (o padrão de plantar reserva à mão está em `test_kinds_reservados_devolve_o_que_ja_tem_reserva`, em `tests/integration/test_recomendacao_e_reacao.py`), e um `_falas_do_agente` local.

`_falas_do_agente` **existe em `tests/integration/test_recomendacao_e_reacao.py:1692`** e devolve `list[tuple[str, str | None, str | None]]` — `(texto, model, subagent)`, com `text_body` decifrado e `outerjoin` com `message_telemetry`. Arquivos de integração deste repo são autocontidos, então **copie a função**, não a importe; o docstring dela explica por que o `outerjoin` e não `join`.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py -k nao_e_gravada_como_entregue --tb=short
```

Esperado: FAIL — a transcrição contém as duas partes.

- [ ] **Step 3: Trocar o `continue` por entrega parcial**

No ramo `if not entrou:` de `executar_turno`, o bloco `else` (o que hoje faz `continue`) passa a espelhar o ramo `if entregue:`:

```python
                    # Ate a TEC-273 isto fazia `continue`, e o comentario
                    # chamava o caso de "a retentativa legitima do sweeper": a
                    # parte com reserva de uma tentativa anterior devolvia
                    # False aqui e a parte sem reserva ainda tinha a vez.
                    #
                    # Aquela retentativa deixou de existir. A TEC-273 libera as
                    # reservas do GRUPO inteiro numa falha retentavel, entao a
                    # passada seguinte nao encontra reserva de parte nenhuma.
                    # O que ainda chega aqui e anomalia: uma reserva PRESA -- o
                    # delete da liberacao falhando por deadlock ou conexao
                    # caida, que `port.py` antecipa e loga como
                    # `outbound.liberacao_falhou`.
                    #
                    # Seguir adiante gravaria o texto INTEIRO na transcricao,
                    # incluindo a parte que nunca saiu, e o corretor leria no
                    # handoff que o agente disse algo que o lead nunca recebeu.
                    entrega_parcial = True
                    suprimida_apos_entrega = False
                    log.error(
                        "turno.entrega_parcial_da_resposta",
                        channel=message.channel,
                        message_id=str(message.id),
                        kind=kind,
                        reason="reserva presa: a parte anterior nao saiu nesta passada",
                    )
                    break
```

**Confira o nome exato da variável `suprimida_apos_entrega` no arquivo antes de escrever** — ela governa o desfecho mais abaixo, e o valor certo aqui é `False`, porque nada foi entregue antes desta parte.

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py tests/integration/test_apresentacao_no_turno.py --tb=short
```

Esperado: tudo PASSA. Se algum teste antigo quebrar, leia-o antes de mexer: ele pode estar afirmando o `continue` como comportamento desejado, e nesse caso o desenho mudou debaixo dele — reporte em vez de ajustar.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "fix(TEC-273): a transcricao para de afirmar a parte que a reserva suprimiu"
```

---

### Task 6: A guarda que falta no `marcar_desambiguacao`

**Files:**
- Modify: `src/mobia/domain/agente/turno.py:1813`
- Test: `tests/integration/` (o arquivo que já cobre desambiguação)

**O contexto (D5):** a guarda de `marcar_perguntados` tem quatro condições; a de `marcar_desambiguacao` tem três — falta `not entrega_parcial`. O argumento que a TEC-140 escreveu para a primeira vale palavra por palavra aqui: `entrega_parcial` não diz **onde** a quebra caiu, então a pergunta pode ter saído inteira, pela metade, ou nem ter existido na parte entregue. Marcar quando ela ficou na parte suprimida queima, para sempre e em silêncio, a única pergunta do episódio.

- [ ] **Step 1: Write the failing test**

O irmão deste teste já existe: `test_saida_bloqueada_nao_marca_a_desambiguacao`, em `tests/integration/test_moderacao_de_saida.py:~183`. Ele cobre a mesma guarda pelo ramo `saida_bloqueada`. **Escreva o novo ao lado dele, no mesmo arquivo**, espelhando o setup:

```python
async def test_entrega_parcial_nao_marca_a_desambiguacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """TEC-273, D5. A marca so entra quando a pergunta chegou inteira.

    Irmao de `test_saida_bloqueada_nao_marca_a_desambiguacao`, pelo quarto
    ramo da mesma guarda. `entrega_parcial` nao diz ONDE dentro do texto a
    quebra caiu: a pergunta do desambiguador pode ter saido inteira, pela
    metade, ou nem ter existido na parte que o lead recebeu. Marcar aqui
    gastaria a unica pergunta do episodio numa entrega que talvez nunca a
    tenha feito, e o lead ficaria em INDEFINIDA sem ninguem ter perguntado --
    o MESMO dano que `saida_bloqueada` e `citacao_bloqueada` ja evitam.

    E o argumento que a TEC-140 escreveu para `marcar_perguntados`, que tem
    as quatro condicoes. Esta guarda tinha tres ate a TEC-273.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA
    from mobia.domain.outbound.port import EnvioRecusado

    await _conversa_ja_existe(session)

    # `confianca=0.5` e o que leva o turno ao caminho ambiguo -- com o padrao
    # do duble (0,91) nada passa por `desambiguar`, e era esse ponto cego que
    # mantinha o defeito irmao vivo (ver o docstring do teste ao lado).
    # A pergunta longa e o que a faz quebrar em duas partes.
    classificador = classificador_fake(
        confianca=Decimal("0.5"),
        pergunta="Me conta: " + "x" * 400 + " ou " + "y" * 400 + "?",
    )

    class _RecusaAParte2(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id, kind, payload) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRecusado("http 400")
            await super()._deliver(message_id, kind, payload)

    resultado = await rodar_turno(
        session,
        classificador,
        _RecusaAParte2(get_sessionmaker()),
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert classificador.desambiguacoes == 1, "o caminho ambiguo tem de ter sido exercitado"
    assert resultado != "respondido"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL_AGENTE, CONVERSA_AGENTE)
    assert gravada is not None
    assert gravada.desambiguado_em is None, (
        "a pergunta pode ter ficado na parte que nao saiu -- o episodio ainda "
        "tem direito a ela"
    )
```

**Confirme antes de escrever** que a pergunta do desambiguador passa pelo mesmo laço de `KINDS_DA_RESPOSTA` que a resposta normal. Se ela sair por um caminho próprio com kind único, este teste não reproduz nada e o cenário certo é outro — reporte em vez de forçar.

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest <arquivo> -k nao_queima_o_episodio --tb=short
```

Esperado: FAIL — a marca foi gravada.

- [ ] **Step 3: Acrescentar a condição**

`turno.py:1813`:

```python
    if desambiguando and not saida_bloqueada and not citacao_bloqueada:
```

vira

```python
    if (
        desambiguando
        and not saida_bloqueada
        and not citacao_bloqueada
        and not entrega_parcial
    ):
```

E acrescente ao comentário do bloco um parágrafo dizendo por que a quarta condição entrou — reusando o argumento que `marcar_perguntados` já escreve, e nomeando a TEC-273.

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest <arquivo> tests/integration/test_formato_no_turno.py --tb=short
```

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "fix(TEC-273): entrega parcial deixa de queimar a pergunta do episodio"
```

---

### Task 7: O contrato volta a ser verdade, e o PR

**Files:**
- Modify: `src/mobia/domain/outbound/port.py` (docstring do `OutboundPort`, ~linha 51)

- [ ] **Step 1: Corrigir o bullet de `EnvioRetentavel`**

Ele diz hoje:

> `EnvioRetentavel` -- rede, 5xx, 408, 429. A guarda libera a reserva e propaga: a mensagem vira FAILED e o sweeper retenta. O lead recebe eventualmente.

Isso deixou de ser verdade na TEC-140 para o caminho de texto em duas partes, e volta a ser com esta card. Reescreva para dizer **"as reservas do grupo"**, e acrescente uma frase sobre o que grupo significa e por que as fichas não formam um.

- [ ] **Step 2: A listagem obrigatória**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`. Atenção especial a estes, que este plano já sabe estarem em risco:

- o comentário de `KINDS_DA_RESPOSTA` que foi para `kinds.py` — ele fala de "o comentario no topo do modulo" e o módulo mudou;
- `turno.py:1625`, que aponta para *"o comentario no topo do modulo (perto de `KINDS_DA_RESPOSTA`)"* — aquele comentário não está mais neste módulo;
- `turno.py:2161`, no docstring de `_entregar_fichas`, que cita *"o comentario de `KINDS_DA_RESPOSTA`, neste arquivo"* — deixou de estar neste arquivo;
- o parágrafo do `except EnvioRetentavel` do laço de texto (~1610-1635), que descreve em detalhe a mistura de gerações **como algo que este log só torna visível, não evita**. Agora é evitado.

- [ ] **Step 3: Emenda ao SRS, se houver**

Se o contrato de entrega da RN-04.2 mudar, entre com item aninhado `Emenda E-nn (TEC-273, 2026-09-13)` **abaixo** da regra, sem reescrever o texto de 22/08/2026. Se concluir que nenhuma regra mudou, diga isso com o raciocínio — não invente emenda.

- [ ] **Step 4: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Se falhar, repita sobre a mesma árvore antes de culpar a mudança.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "docs(TEC-273): o contrato do OutboundPort volta a descrever o que a guarda faz"
```

- [ ] **Step 6: PR e card — PARAR e pedir autorização**

Push, abertura de PR e comentário na card são efeito fora da árvore. **Pare aqui e peça autorização.** O comentário da card precisa registrar:

- a divergência: a card propunha liberar por `message_id`; o desenho liberou por **grupo**, porque as fichas compartilham a mensagem e a TEC-275 depende das reservas delas;
- a **L1**: a fresta equivalente no caminho das fichas continua aberta, e é a L4 da TEC-275 — o conserto dela não é liberar irmãs;
- a **L3**: o lead vai ler dois textos parecidos em sequência quando isso acontecer, e é deliberado;
- a resposta à pergunta que a card deixou aberta (`_apresentar` tem a mesma exposição?): **não mais**, desde a TEC-275 — exceto pela fresta da L4.

---

## Auto-revisão deste plano

**Cobertura da spec:** D1 → Tasks 1-2. D2 → Task 1. D3 → Task 2 (Step 5 roda o arquivo de cancelamento). D4 → Task 5. D5 → Task 6. D6 → Task 7. Testes 1-2 da spec → Tasks 3 e 5. Testes 3-4 (fronteira) → Tasks 2 e 4. Teste 5 → Task 6. Teste 6 (cancelamento) → Task 2, Step 5. L1/L2/L3 → Task 7, no comentário da card.

**Consistência de tipos:** `grupo_de(kind: str) -> tuple[str, ...]` é criada na Task 1 e consumida na Task 2 com a mesma assinatura. `_liberar` mantém a assinatura `(message_id: uuid.UUID, kind: str) -> None` — só o corpo muda, e a armadilha 1 explica por quê.

**Placeholders:** a primeira versão deste plano deixou um placeholder literal no teste da Task 5. Foi substituído por código real, depois de eu ler `_falas_do_agente` (`test_recomendacao_e_reacao.py:1692`, devolve `(texto, model, subagent)`) e o padrão de plantar reserva à mão. A Task 6 também ganhou código real, espelhando `test_saida_bloqueada_nao_marca_a_desambiguacao` (`test_moderacao_de_saida.py:~183`), que é o irmão exato do teste novo.

**Uma premissa que este plano NÃO conseguiu verificar, e diz onde:** a Task 6 assume que a pergunta do desambiguador atravessa o mesmo laço de `KINDS_DA_RESPOSTA` que a resposta normal. O Step 1 daquela task manda confirmar isso antes de escrever, e reportar em vez de forçar se não for verdade. É a única suposição carregada do plano.
