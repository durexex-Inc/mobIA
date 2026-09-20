# TEC-222 — `last_error` só com o nome da exceção — plano de implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans` para executar tarefa a tarefa. Os passos usam checkbox (`- [ ]`).

**Goal:** Fazer `messages.last_error` guardar apenas `type(exc).__name__`, para que conteúdo de lead não possa ficar legível nessa coluna por construção, mantendo o texto da exceção no log estruturado.

**Architecture:** A função `_detalhe_do_erro` de `src/mobia/workers/jobs/process_message.py` serve hoje dois destinos com garantias diferentes — a coluna durável e o log — com o mesmo valor. Ela se parte em duas: `_detalhe_para_a_coluna`, que devolve só o nome da classe, sempre; e `_detalhe_para_o_log`, que é o corpo de hoje, intacto. Os dois `except` de `process_message` passam a chamar as duas.

**Tech Stack:** Python 3.13, SQLAlchemy async, asyncpg, structlog, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-222-last-error-so-com-o-nome-da-excecao-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento** — exceto valor citado, que segue o valor. Nenhum linter checa isto.
- **Texto que o lead recebe: português COM acento.** Esta branch não toca em nenhum literal desses.
- `ruff` com `line-length = 100`.
- Mensagem de commit em português sem acento no assunto, formato `tipo(TEC-222): o que passou a ser verdade`.
- Os três gates estáticos, no escopo exato do CI: `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`.
- **O eco do asyncpg é truncado em 38 caracteres.** Qualquer sentinela que precise aparecer inteiro em `str(exc)` tem de caber nisso.

---

### Task 1: Partir `_detalhe_do_erro` em dois destinos

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py:45-65` (a função), `:291-296` e `:305-333` (os dois `except`)
- Test: `tests/features/test_reprocessamento_apos_falha.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `_detalhe_para_a_coluna(exc: BaseException) -> str` e `_detalhe_para_o_log(exc: BaseException) -> str`, ambas módulo-privadas em `src/mobia/workers/jobs/process_message.py`. A Task 2 importa `_detalhe_para_a_coluna`.

- [ ] **Step 1: Escrever o teste que falha — o caminho da moderação (T2 do desenho)**

Acrescentar ao fim de `tests/features/test_reprocessamento_apos_falha.py`. Note que `MOTIVO_DO_PROVEDOR` tem menos de 38 caracteres para poder aparecer inteiro tanto na exceção quanto no log.

```python
# Prosa que o SERVIDOR da Anthropic escreve, nao texto que este projeto montou.
# `motivo_do_provedor` (infra/anthropic.py) devolve ate 300 caracteres dela, e
# `ModeracaoIndisponivel` a carrega ate `last_error` -- ver o desenho da
# TEC-222. O valor aqui imita um 400 de validacao que cite o payload recusado.
MOTIVO_DO_PROVEDOR = "400 invalid_request: 'quero 2 quartos'"


async def test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna(session, caplog) -> None:
    """A excecao e de `mobia`, mas a mensagem dela nao foi escrita aqui dentro.

    `ModeracaoIndisponivel` vem de `domain/moderacao/port.py`, entao o criterio
    da TEC-134 -- dono do tipo -- deixava o texto inteiro entrar na coluna. Mas
    `infra/moderacao.py` a levanta com `motivo_do_provedor(exc)`, que e o corpo
    de erro do servidor da Anthropic, em resposta a uma requisicao cujo corpo e
    o texto moderado. Dono do tipo nao e dono da mensagem.

    A moderacao de SAIDA nao falha aberta de proposito (ver `turno.py`), entao
    a excecao propaga ate `process_message` e chega a coluna.
    """
    from mobia.domain.moderacao.port import ModeracaoIndisponivel

    message_id = await enfileirada(session)
    ctx = _ctx(get_sessionmaker(), OutboundEspiao(get_sessionmaker()))
    ctx["moderador"] = ModeradorFake(erro_na_saida=ModeracaoIndisponivel(MOTIVO_DO_PROVEDOR))

    with caplog.at_level("INFO"), pytest.raises(ModeracaoIndisponivel):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.last_error == "ModeracaoIndisponivel"
    assert MOTIVO_DO_PROVEDOR not in (linha.last_error or "")

    # A outra metade da divisao do desenho, e ela precisa ser afirmada: uma
    # implementacao que emudecesse o log junto passaria na asserta de cima e
    # seria regressao de diagnostico. O log MANTEM o texto, pela regra da
    # TEC-134, onde o raciocinio da TEC-237 se aplica ao destino para o qual
    # foi escrito.
    ((_, corpo),) = eventos_de_log(caplog, "message.failed")
    assert corpo["error"] == f"ModeracaoIndisponivel: {MOTIVO_DO_PROVEDOR}"
```

Acrescentar `eventos_de_log` ao import de `conftest` no topo do arquivo, que passa a ser:

```python
from conftest import (
    ClassificadorFake,
    ContadorFake,
    ModeradorFake,
    ResumidorFake,
    eventos_de_log,
)
```

- [ ] **Step 2: Rodar e confirmar que falha pela razão certa**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_reprocessamento_apos_falha.py::test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna --tb=short
```

Esperado: FAIL na asserta `linha.last_error == "ModeracaoIndisponivel"`, porque o valor gravado hoje é `"ModeracaoIndisponivel: 400 invalid_request: 'quero 2 quartos'"`.

**Se falhar em outro ponto, pare e diagnostique** — em especial, se falhar com `ConnectionResetError [WinError 64]`, é o falso-alarme conhecido do `CLAUDE.md`: espere e repita antes de concluir qualquer coisa.

- [ ] **Step 3: Partir a função**

Substituir o bloco `src/mobia/workers/jobs/process_message.py:45-65` inteiro por:

```python
def _detalhe_para_a_coluna(exc: BaseException) -> str:
    """O que vai para `messages.last_error`: o nome da classe, e so.

    A coluna e `Text` em claro, durvel, sem cifra e fora da mascara de PII do
    log. Ate a TEC-222 aqui valia o criterio da TEC-134 -- excecao definida em
    `mobia` mantinha a mensagem inteira, porque "ela foi escrita aqui dentro e
    sabe-se o que ela carrega".

    **O criterio caiu porque confunde dono do TIPO com dono da MENSAGEM.**
    `ModeracaoIndisponivel` e definida em `domain/moderacao/port.py`, mas
    `infra/moderacao.py` a levanta com `motivo_do_provedor(exc)`: prosa que o
    servidor da Anthropic escreveu respondendo a uma requisicao cujo corpo e o
    texto moderado. O docstring de `motivo_do_provedor` aceita esse risco por
    escrito, e o limita com tres coisas -- o teto de caracteres, o mascaramento
    de digitos e o formato da chamada. **Duas delas sao propriedades do log.**
    Nesta coluna so o teto sobrevive.

    Datas, porque elas sao o argumento: o criterio entrou em 26/08/2026
    (TEC-134, `d069f3e`) e foi violado em 30/08/2026 (TEC-237, `d79e2d7`),
    quatro dias depois, sem que nenhuma revisao notasse. Nao e o caso
    hipotetico do autor futuro desatento -- e o caso medido de duas cards da
    mesma semana, cada uma correta sozinha.

    Dai nao haver ramo nenhum: uma garantia que dependa de toda excecao futura
    ter sido escrita com cuidado nao e uma garantia. O texto continua no log,
    via `_detalhe_para_o_log`.
    """
    return type(exc).__name__


def _detalhe_para_o_log(exc: BaseException) -> str:
    """O que vai para o log estruturado, que e mais do que vai para a coluna.

    Este e o criterio da TEC-134, intacto, aplicado ao destino para o qual ele
    faz sentido: aqui a mascara de PII de `app/logging.py` alcanca o valor, e o
    raciocinio da TEC-237 sobre o corpo de erro do provedor foi escrito
    pensando neste destino.

    Manter a divisao importa nos dois sentidos. Emudecer o log junto com a
    coluna seria regressao de diagnostico sem ganho de seguranca -- e
    `test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna` reprova
    se alguem fizer isso.
    """
    modulo = type(exc).__module__
    if modulo == "mobia" or modulo.startswith("mobia."):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__
```

- [ ] **Step 4: Trocar os dois chamadores**

Em `src/mobia/workers/jobs/process_message.py`, no `except Exception as exc:`, substituir

```python
        detalhe = _detalhe_do_erro(exc)
        tentativas = await _marcar_falha(session_factory, identifier, detalhe)
        # Mesmo valor da coluna, e pelo mesmo motivo: o log estruturado nao
        # mascara `error`, e a chave nao esta na lista de campos redigidos.
        log.warning("message.failed", message_id=message_id, error=detalhe)
```

por

```python
        tentativas = await _marcar_falha(session_factory, identifier, _detalhe_para_a_coluna(exc))
        # Valor MAIOR que o da coluna, desde a TEC-222: a coluna e durvel e
        # fora da mascara, o log nao. Ver os dois docstrings acima.
        log.warning("message.failed", message_id=message_id, error=_detalhe_para_o_log(exc))
```

**Note que o comentário muda junto com o código** — ele afirmava "mesmo valor da coluna", que deixa de ser verdade. Deixá-lo de pé é o defeito que a seção "Comentário não mente" do `CLAUDE.md` descreve.

E no `except asyncio.CancelledError as exc:`, substituir

```python
        detalhe = _detalhe_do_erro(exc)
        try:
            async with asyncio.timeout(SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO):
                await _marcar_falha(session_factory, identifier, detalhe)
```

por

```python
        try:
            async with asyncio.timeout(SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO):
                await _marcar_falha(session_factory, identifier, _detalhe_para_a_coluna(exc))
```

e, mais abaixo no mesmo bloco, substituir

```python
        log.warning("message.cancelled", message_id=message_id, error=detalhe)
```

por

```python
        log.warning("message.cancelled", message_id=message_id, error=_detalhe_para_o_log(exc))
```

**Aqui o valor nao muda de fato**: `CancelledError` tem `__module__ == "asyncio.exceptions"`, entao as duas funções devolvem `"CancelledError"`. A troca é por coerência — quem ler o bloco não deve precisar descobrir sozinho que aquele caminho é um caso particular.

- [ ] **Step 5: Rodar o teste novo e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_reprocessamento_apos_falha.py::test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna --tb=short
```

Esperado: PASS.

- [ ] **Step 6: Inverter o teste que afirmava a premissa derrubada (T3 do desenho)**

Em `tests/features/test_reprocessamento_apos_falha.py`, substituir `test_erro_do_proprio_projeto_mantem_a_mensagem` (hoje em `:255`) inteiro por:

```python
async def test_erro_do_proprio_projeto_tambem_so_deixa_o_nome_na_coluna(session, caplog) -> None:
    """Ate a TEC-222 este teste afirmava o contrario, e a premissa dele caiu.

    O docstring antigo dizia: "excecao de `mobia` teve a mensagem escrita aqui
    dentro -- sabe-se o que ela carrega". Nao se sabe.
    `ModeracaoIndisponivel` desmente a frase, e o teste ao lado prova. Como a
    garantia nao pode depender de cada autor futuro de excecao, a coluna deixou
    de guardar texto de qualquer origem -- inclusive quando ele e, de fato,
    inofensivo, como aqui.

    O diagnostico nao se perde: o log de `message.failed` continua com o texto.
    """
    from mobia.domain.agente.classificador import RespostaInvalida

    message_id = await enfileirada(session)
    ctx = _ctx(get_sessionmaker(), OutboundEspiao(get_sessionmaker()))
    ctx["classificador"] = ClassificadorFake(erro=RespostaInvalida("JSONDecodeError"))

    with caplog.at_level("INFO"), pytest.raises(RespostaInvalida):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.last_error == "RespostaInvalida"

    ((_, corpo),) = eventos_de_log(caplog, "message.failed")
    assert corpo["error"] == "RespostaInvalida: JSONDecodeError"
```

- [ ] **Step 7: Rodar o arquivo inteiro**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_reprocessamento_apos_falha.py --tb=short
```

Esperado: todos passam. `test_erro_de_terceiro_nao_leva_a_mensagem_para_last_error` continua valendo palavra por palavra e não foi tocado.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/workers/jobs/process_message.py tests/features/test_reprocessamento_apos_falha.py
git commit -m "fix(TEC-222): last_error guarda so o nome da excecao, o log guarda o texto"
```

---

### Task 2: O teste com exceção real do banco

**Files:**
- Test: `tests/integration/test_last_error_com_excecao_real.py` (criar)

**Interfaces:**
- Consumes: `_detalhe_para_a_coluna` de `mobia.workers.jobs.process_message` (Task 1).
- Produces: nada.

Arquivo próprio, e não mais um caso em `test_reprocessamento_apos_falha.py`, por duas razões: ele é `integration` e não `features` — não exercita cenário Gherkin nenhum, exercita o formato da mensagem de um driver —, e o `--dist loadfile` da suíte mantém arquivo inteiro num worker só, então um arquivo curto e independente é o que melhor isola um teste que abre conexão própria.

- [ ] **Step 1: Escrever o teste**

Criar `tests/integration/test_last_error_com_excecao_real.py`:

```python
"""O que uma excecao REAL do driver carrega, e o que dela chega a coluna.

A TEC-222 pede este teste por escrito: "o teste forca uma excecao real do
banco, nao um `raise ValueError(...)` sintetico -- o formato da mensagem do
driver e justamente o que importa". Duble nenhum reproduz esse formato, porque
o que se investiga aqui e uma decisao do asyncpg, nao deste projeto.
"""

import uuid

from sqlalchemy import insert

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.db import get_engine
from mobia.workers.jobs.process_message import _detalhe_para_a_coluna

# Cabe nos 38 caracteres que o asyncpg ecoa antes de truncar -- medido na
# TEC-222. Um sentinela mais longo nunca apareceria inteiro em `str(exc)`, e a
# primeira asserta abaixo reprovaria por uma razao que nao e a investigada.
SENTINELA = "SENTINELA rua das palmeiras 2 quartos"


async def test_excecao_real_do_driver_ecoa_o_valor_e_a_coluna_nao() -> None:
    """O eco do driver existe; o que vai para `last_error` nao o carrega.

    O `insert()` de Core passa ao largo do `@validates("text_body", ...)` do
    ORM, que rejeitaria o `str` antes de qualquer viagem ao banco. E e esse
    desvio que reproduz o caso: o asyncpg monta a mensagem de erro dele com o
    valor ofensivo dentro, ANTES de a SQLAlchemy ver qualquer coisa -- entao o
    `hide_parameters=True` de `infra/db.py`, que aparece na mesma string logo
    abaixo, nao o alcanca.

    **As duas assertas sao necessarias.** Sem a primeira, este teste
    continuaria verde no dia em que o driver parasse de ecoar o valor, e seria
    uma asserta de ausencia sempre satisfeita -- a classe de defeito que a
    TEC-289 tratou.
    """
    async with get_engine().begin() as conn:
        try:
            await conn.execute(
                insert(Message).values(
                    id=uuid.uuid4(),
                    channel="whatsapp",
                    conversation_key="5511911112222",
                    role=MessageRole.LEAD,
                    direction=MessageDirection.INBOUND,
                    content_type=MessageContentType.TEXTO,
                    # `str` numa coluna `bytea`: e o descasamento de tipo que a
                    # card reproduziu na review da TEC-126.
                    text_body=SENTINELA,
                )
            )
        except Exception as exc:
            assert SENTINELA in str(exc), "o driver deixou de ecoar o valor; o teste perdeu o alvo"
            assert type(exc).__module__ == "sqlalchemy.exc"
            assert SENTINELA not in _detalhe_para_a_coluna(exc)
            assert _detalhe_para_a_coluna(exc) == "DBAPIError"
        else:
            raise AssertionError("o INSERT deveria ter falhado com erro de tipo do driver")
```

- [ ] **Step 2: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_last_error_com_excecao_real.py --tb=short
```

Esperado: PASS.

**Se reprovar em `type(exc).__module__ == "sqlalchemy.exc"`**, o driver ou a SQLAlchemy mudaram a classe que envolve o erro — corrija a asserta para o que o ambiente devolve e **registre a mudança no docstring**, porque ela é justamente o fato que o teste existe para fixar. Não relaxe a asserta para `in ("sqlalchemy.exc", ...)`: isso a torna decorativa.

- [ ] **Step 3: Confirmar que a primeira asserta pode reprovar**

Este teste **não** teria ficado vermelho antes da branch, e isso é esperado: `DBAPIError` já era cortada pelo critério da TEC-134, então a propriedade que ele tranca já valia. Ele existe porque a card a exige com o formato real do driver, e porque nada a fixava. O teste que teria ficado vermelho antes é o da Task 1.

O que precisa de conferência é outra coisa: que a asserta de presença — a que impede o teste de virar uma asserta de ausência sempre satisfeita — de fato reprova quando deveria. Confira invertendo o sentinela para algo que o driver não vai ecoar:

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_last_error_com_excecao_real.py --tb=line \
  -k test_excecao_real -q -p no:cacheprovider \
  --override-ini="addopts=-m 'not perf'" 2>&1 | tail -5
```

Depois, temporariamente, troque `SENTINELA` por uma string de mais de 38 caracteres e rode de novo: deve reprovar em `"o driver deixou de ecoar o valor; o teste perdeu o alvo"`. **Desfaça a troca.** Se ela NÃO reprovar, a primeira asserta está decorativa e o teste inteiro perde o valor.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_last_error_com_excecao_real.py
git commit -m "test(TEC-222): o formato real do driver, e nao um ValueError sintetico"
```

---

### Task 3: Gates, listagem de comentários e suíte

**Files:**
- Nenhum arquivo novo; correções pontuais se algum gate reprovar.

**Interfaces:**
- Consumes: as Tasks 1 e 2 commitadas.
- Produces: árvore pronta para PR.

- [ ] **Step 1: Os três gates estáticos, no escopo do CI**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Esperado: os três limpos. **O formatador é gate separado do linter** — passar num não diz nada sobre o outro.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reler cada `ALTERADO` e `VIZINHO` que ela apontar dentro de `process_message.py`. Dois em particular, que o diff **não** mostra e por isso ninguém releria:

- O comentário de `_marcar_falha` sobre o `returning` e o `attempts` — conferir que nada nele fala do conteúdo de `last_error`.
- Qualquer `PROSA`/`FALSO` que cite `process_message.py:<linha>`: as linhas se moveram, então uma citação por número pode ter passado a apontar outra coisa.

- [ ] **Step 3: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guardar o hash junto com o resultado. Se reprovar, **repetir sobre a mesma árvore antes de culpar a mudança** — é o único jeito de separar flake de regressão. Se voltarem centenas de `ERROR` de setup, não repita o mesmo comando: é a queda do Postgres sob o `-n 8`, e a saída é rodar por blocos (`tests/unit`, `tests/integration`, `tests/features`).

- [ ] **Step 4: Commit do desenho e do plano, se ainda não estiverem na branch**

```bash
git add docs/superpowers/specs/2026-09-20-tec-222-last-error-so-com-o-nome-da-excecao-design.md docs/superpowers/plans/2026-09-20-tec-222-last-error-so-com-o-nome-da-excecao.md
git commit -m "docs(TEC-222): o desenho e o plano do last_error sem texto de excecao"
```

- [ ] **Step 5: Push e PR contra `main`**

O trabalho termina em PR, nunca em merge local. Depois do PR: comentar na card TEC-222 e movê-la para **Em análise** — não para "Feito", que é de quem mergeia.

O comentário da card registra, no mínimo:

- **A divergência em relação ao texto da card:** o vazamento que ela descreve já estava fechado desde a TEC-134; o defeito real é o critério, e o único caminho aberto era `ModeracaoIndisponivel`.
- **A correção do número:** são 7 ocorrências do literal `detail=str(exc)`, mas 25 pontos do mesmo padrão sob outros kwargs, nove deles em `turno.py`.
- **O que a card não entrega:** os 25 pontos de log, que viram card de seguimento.
- **O achado lateral:** `EmailJaCadastrado(dados.email)` e `ArquivoInvalido(f"... {erro}")` carregam PII no texto da exceção, mas não alcançam `process_message` por caminho nenhum.
