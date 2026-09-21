# TEC-293 — traceback sem mensagem de exceção: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o traceback que vai para o log JSON carregar pilha, cadeia de causas e tipo da exceção — e nunca a mensagem dela.

**Architecture:** Um processador próprio, `_sanear_traceback`, substitui `structlog.processors.format_exc_info` na mesma posição do pipeline de `app/logging.py`. Ele monta a chave `exception` a partir de `traceback.TracebackException`, percorrendo `__cause__`/`__context__`, e emite por seção as linhas de frame mais o tipo qualificado, sem mensagem e sem linha de código-fonte. Os três sítios que só tinham `exc_info=True` recebem o texto de volta num kwarg nomeado, onde já está medido que ele não ecoa entrada externa.

**Tech Stack:** Python 3.13, structlog 26.1.0, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-293-traceback-sem-mensagem-de-excecao-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceção: valor citado que o usuário recebe segue o literal, com acento.
- **Prosa em `docs/` e `.md`: com acento.**
- **Mensagem de commit:** português sem acento no assunto, formato `tipo(TEC-293): o que passou a ser verdade`.
- **Os três gates estáticos, com o escopo exato, antes de qualquer commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter: passar num não diz nada sobre o outro.
- **`mypy` roda sem argumento** — argumento de linha de comando sobrepõe o `files` do `pyproject.toml`.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short` roda sem `docker compose` de pé. Todas as tarefas deste plano, exceto a Task 5, são cobertas por testes unitários.
- **Comentário desatualizado é defeito.** Toda tarefa que muda código descrito por um comentário muda o comentário junto.
- **Asserta de ausência sobre log é armadilha (TEC-289):** `JSONRenderer` serializa com `ensure_ascii=True`, então `assert "não" not in caplog.text` passa com o texto dentro do log. Os testes deste plano usam agulhas sem acento, o que é seguro; se alguma agulha acentuada for necessária, use o helper `log_legivel` de `tests/conftest.py:1225`.

---

### Task 1: O processador `_sanear_traceback`, testado isoladamente

Esta tarefa escreve a função e a testa como função pura. Ela ainda **não** entra no pipeline — isso é a Task 2, para que um revisor possa aprovar a função e rejeitar a troca, ou o contrário.

**Files:**
- Modify: `src/mobia/app/logging.py` (acrescenta a função; não mexe em `configure_logging`)
- Test: `tests/unit/test_sanear_traceback.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `_sanear_traceback(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict` — processador structlog. Lê e remove a chave `exc_info`; quando ela designa uma exceção, escreve a chave `exception: str`.
  - `_excecao_de(valor: object) -> BaseException | None` — normaliza as três formas que `exc_info` assume.
  - Constantes `_ELO_CAUSA: str` e `_ELO_CONTEXTO: str`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/unit/test_sanear_traceback.py`:

```python
"""O processador que poe a pilha no log e deixa a mensagem de fora.

Os testes chamam `_sanear_traceback` direto, sem o pipeline: o que se
prova aqui e a FORMA do texto produzido. O acoplamento com o resto dos
processadores e provado em `test_logging_mascara.py`.
"""

import sys

import pytest

from mobia.app.logging import _ELO_CAUSA, _ELO_CONTEXTO, _sanear_traceback


def _capturar(modo: str) -> tuple:
    """Levanta uma cadeia de duas excecoes no modo pedido e devolve o exc_info.

    A mensagem de cada uma carrega uma agulha reconhecivel, para os testes
    poderem afirmar que ela NAO sobreviveu.
    """

    def fundo() -> None:
        raise ValueError("fala do lead: quero 3 quartos, tel 5511987654321")

    try:
        try:
            fundo()
        except ValueError as causa:
            if modo == "cause":
                raise RuntimeError("DETAIL: Failing row contains (...)") from causa
            if modo == "suppress":
                raise RuntimeError("wrapper limpo") from None
            raise RuntimeError("wrapper implicito")
    except RuntimeError:
        return sys.exc_info()
    raise AssertionError("o helper tem de levantar")


def _sanear(exc_info: object) -> str:
    evento = _sanear_traceback(None, "error", {"event": "e", "exc_info": exc_info})
    return evento["exception"]


@pytest.mark.parametrize("modo", ["cause", "context", "suppress"])
def test_a_mensagem_da_excecao_nao_sobrevive(modo: str) -> None:
    """Nenhum dos tres modos de encadeamento deixa passar texto de mensagem."""
    saneado = _sanear(_capturar(modo))

    assert "quero 3 quartos" not in saneado
    assert "5511987654321" not in saneado
    assert "Failing row contains" not in saneado
    assert "wrapper" not in saneado


@pytest.mark.parametrize("modo", ["cause", "context", "suppress"])
def test_o_tipo_e_a_pilha_sobrevivem(modo: str) -> None:
    """O que torna o erro diagnosticavel fica: tipo qualificado e frames."""
    saneado = _sanear(_capturar(modo))

    assert "RuntimeError" in saneado
    assert "test_sanear_traceback.py" in saneado
    assert "in _capturar" in saneado


def test_a_causa_explicita_aparece_com_o_elo_do_python() -> None:
    """`raise ... from exc` produz duas secoes e o elo de causa direta."""
    saneado = _sanear(_capturar("cause"))

    assert _ELO_CAUSA in saneado
    assert _ELO_CONTEXTO not in saneado
    assert saneado.count("Traceback (most recent call last):") == 2
    assert "ValueError" in saneado


def test_o_contexto_implicito_aparece_com_o_outro_elo() -> None:
    """Excecao levantada DENTRO de um except traz a anterior, com o elo dela."""
    saneado = _sanear(_capturar("context"))

    assert _ELO_CONTEXTO in saneado
    assert _ELO_CAUSA not in saneado
    assert saneado.count("Traceback (most recent call last):") == 2


def test_from_none_esconde_a_anterior() -> None:
    """`__suppress_context__` existe para esconder, e e respeitado."""
    saneado = _sanear(_capturar("suppress"))

    assert saneado.count("Traceback (most recent call last):") == 1
    assert "ValueError" not in saneado


def test_a_linha_de_codigo_fonte_fica_de_fora() -> None:
    """Arquivo, linha e funcao localizam o frame; o fonte esta versionado."""
    saneado = _sanear(_capturar("cause"))

    assert "raise RuntimeError" not in saneado
    assert "fundo()" not in saneado


def test_cadeia_ciclica_nao_pendura() -> None:
    """Quem corta o ciclo e o `TracebackException`, nao uma guarda nossa.

    Isto e garantia de terceiro da qual passamos a depender: sem ela, o laco
    da travessia nao terminaria. O teste existe para a dependencia ficar
    fixada, e nao para provar codigo nosso.
    """
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a

    saneado = _sanear((type(a), a, None))

    assert saneado.count("Traceback (most recent call last):") <= 3


def test_excecao_passada_como_instancia() -> None:
    """`exc_info=<excecao>` e uma das tres formas que o structlog aceita."""
    try:
        raise KeyError("conversation_key")
    except KeyError as erro:
        saneado = _sanear(erro)

    assert "KeyError" in saneado
    assert "conversation_key" not in saneado


def test_sem_excecao_nao_cria_a_chave() -> None:
    """`exc_info` falso ou ausente nao inventa chave `exception` no evento."""
    evento = _sanear_traceback(None, "info", {"event": "e", "exc_info": False})

    assert "exception" not in evento
    assert "exc_info" not in evento
```

- [ ] **Step 2: Rodar e ver falhar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_sanear_traceback.py --tb=short
```

Esperado: erro de coleta — `ImportError: cannot import name '_ELO_CAUSA' from 'mobia.app.logging'`.

- [ ] **Step 3: Escrever a implementação**

Em `src/mobia/app/logging.py`, acrescentar `import traceback` ao topo (junto de `import sys`, que já existe) e inserir o bloco abaixo **logo antes** de `_renderizar_json = structlog.processors.JSONRenderer()`:

```python
# As duas frases que o proprio Python usa para ligar as secoes de uma cadeia.
# Copiadas literalmente porque quem le o log ja as reconhece; inventar frase
# nova aqui so tornaria o traceback estranho sem ganhar nada.
_ELO_CAUSA = "The above exception was the direct cause of the following exception:"
_ELO_CONTEXTO = "During handling of the above exception, another exception occurred:"


def _excecao_de(valor: object) -> BaseException | None:
    """Normaliza as tres formas que `exc_info` assume no structlog.

    `log.exception(...)` e `exc_info=True` chegam como `True`; um `except ... as
    erro` repassado chega como instancia; e o stdlib usa a tupla de tres.
    """
    if isinstance(valor, BaseException):
        return valor
    if isinstance(valor, tuple) and len(valor) == 3:
        segundo = valor[1]
        return segundo if isinstance(segundo, BaseException) else None
    if valor is True:
        return sys.exc_info()[1]
    return None


def _sanear_traceback(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Poe a pilha no log e deixa a mensagem da excecao de fora.

    Substitui `structlog.processors.format_exc_info`, que entregava o traceback
    inteiro -- terminando em `TipoDoErro: <mensagem>` em CADA secao da cadeia.
    Numa falha de gravacao, essa mensagem e a linha `DETAIL` que o Postgres
    escreve, e numa violacao de CHECK ela traz a linha inteira: medido na
    TEC-293, a fala do lead aparecia duas vezes, porque a SQLAlchemy reembala a
    excecao do asyncpg e as duas secoes repetem o texto.

    Por isso o corte e estrutural e nao textual: a mensagem nao esta so na
    ultima linha -- a da wrapper ocupa quatro, e a da causa fica no meio.

    **Nao troque isto pelo `ExceptionDictTransformer` do structlog.** Medido na
    TEC-293: ele nasce com `show_locals=True`, que despeja as variaveis locais
    de cada frame -- inclusive o objeto que estava sendo gravado --, e mesmo com
    `show_locals=False` mantem `exc_value`, que e a mensagem inteira. Adota-lo
    seria regressao, nao simplificacao.

    O que sai daqui: por secao da cadeia, uma linha por frame com arquivo,
    linha e funcao, e o tipo qualificado no lugar da mensagem. Sem a linha de
    codigo-fonte, que nao carrega valor de runtime (o argumento vem de
    variavel) e por isso e escolha de volume, nao de protecao.
    """
    excecao = _excecao_de(event_dict.pop("exc_info", None))
    if excecao is None:
        return event_dict

    # A travessia nao leva guarda de ciclo: quem corta `a.__cause__ = b;
    # b.__cause__ = a` e o proprio `TracebackException`, que guarda os nos
    # vistos ao construir. Guarda nossa por cima nunca dispararia, e
    # `test_cadeia_ciclica_nao_pendura` fixa a dependencia.
    cadeia: list[tuple[traceback.TracebackException, str | None]] = []
    atual: traceback.TracebackException | None = traceback.TracebackException(
        type(excecao), excecao, excecao.__traceback__
    )
    elo: str | None = None
    while atual is not None:
        cadeia.append((atual, elo))
        if atual.__cause__ is not None:
            atual, elo = atual.__cause__, _ELO_CAUSA
        elif atual.__context__ is not None and not atual.__suppress_context__:
            atual, elo = atual.__context__, _ELO_CONTEXTO
        else:
            atual, elo = None, None

    linhas: list[str] = []
    for item, ligacao in reversed(cadeia):
        linhas.append("Traceback (most recent call last):")
        for frame in item.stack:
            linhas.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
        linhas.append(item.exc_type_str)
        if ligacao is not None:
            linhas.extend(("", ligacao, ""))

    event_dict["exception"] = "\n".join(linhas)
    return event_dict
```

- [ ] **Step 4: Rodar e ver passar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_sanear_traceback.py --tb=short
```

Esperado: 13 passed (os dois parametrizados contam 3 cada).

- [ ] **Step 5: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Se o `ruff format --check` reprovar, rode `./.venv/Scripts/python.exe -m ruff format src tests alembic evals scripts` e confira o diff antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/app/logging.py tests/unit/test_sanear_traceback.py
git commit -m "feat(TEC-293): o saneador de traceback emite pilha e tipo, nunca mensagem"
```

---

### Task 2: Ligar o saneador no pipeline e acertar os testes que ele quebra

**Files:**
- Modify: `src/mobia/app/logging.py:142-159` (a lista de processadores em `configure_logging`)
- Test: `tests/unit/test_logging_mascara.py:120-136` (reescrever o teste existente e acrescentar dois)

**Interfaces:**
- Consumes: `_sanear_traceback` da Task 1.
- Produces: o pipeline configurado emite a chave `exception` saneada. Nenhum símbolo novo.

- [ ] **Step 1: Reescrever o teste que hoje consagra o vazamento**

Em `tests/unit/test_logging_mascara.py`, substituir `test_telefone_no_traceback_tambem_sai_mascarado` (linhas 120-136) inteiro por:

```python
def test_a_mensagem_da_excecao_nao_chega_ao_log(caplog) -> None:
    """O traceback leva pilha e tipo; a mensagem fica de fora (TEC-293).

    Ate a TEC-293 este teste afirmava o contrario -- que a mensagem chegava,
    contanto que mascarada --, e por isso consagrava o vazamento que aquela
    card fechou. A corrida de digitos era a unica defesa sobre a chave
    `exception`, e ela nao alcanca texto livre em portugues.
    """
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("contato do lead: 5511987654321")
        except ValueError:
            log.exception("evento.erro")

    assert "5511987654321" not in caplog.text
    assert "*********4321" not in caplog.text
    assert "contato do lead" not in caplog.text
    assert "ValueError" in caplog.text
    assert "test_logging_mascara.py" in caplog.text


def test_a_cadeia_de_causas_nao_vaza_em_nenhuma_das_secoes(caplog) -> None:
    """O caso medido: a mensagem aparecia DUAS vezes, nao uma.

    A SQLAlchemy reembala a excecao do asyncpg, entao a linha `DETAIL` do
    servidor entra na secao da causa e de novo na da wrapper. Cortar a ultima
    linha nao resolveria nenhuma das duas.
    """
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.ERROR):
        try:
            try:
                raise ValueError("DETAIL: Failing row contains (5511987654321, oi)")
            except ValueError as causa:
                raise RuntimeError("wrapper: DETAIL: Failing row contains (...)") from causa
        except RuntimeError:
            log.exception("evento.erro")

    assert "Failing row contains" not in caplog.text
    assert "5511987654321" not in caplog.text
    assert "ValueError" in caplog.text
    assert "RuntimeError" in caplog.text


def test_o_formatter_do_stdlib_nao_reemite_o_traceback_cru(caplog) -> None:
    """`_finalizar` desarma o `exc_info` do LogRecord, e isso tem de continuar.

    `logging.Logger.exception` religa `exc_info=True` por conta propria. Sem o
    desarme, o Formatter padrao imprime o traceback ORIGINAL -- com mensagem e
    tudo -- logo depois do JSON que ja o contem saneado, e a TEC-293 inteira
    vira letra morta. Nada provava isso diretamente ate aqui.
    """
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("segredo do lead: 5511987654321")
        except ValueError:
            log.exception("evento.erro")

    assert caplog.records[0].exc_info is False
    assert "segredo do lead" not in caplog.text
```

- [ ] **Step 2: Rodar e ver falhar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_logging_mascara.py --tb=short
```

Esperado: os três novos falham, porque `configure_logging` ainda usa `format_exc_info`. `test_a_mensagem_da_excecao_nao_chega_ao_log` falha em `assert "*********4321" not in caplog.text`; os outros dois falham nas assertas de ausência.

- [ ] **Step 3: Trocar o processador no pipeline**

Em `src/mobia/app/logging.py`, dentro de `configure_logging`, substituir estas três linhas:

```python
            # sem isso o traceback so nasce depois do JSONRenderer, fora do
            # alcance do mascaramento: tem de virar chave do dict antes.
            structlog.processors.format_exc_info,
```

por:

```python
            # sem isso o traceback so nasce depois do JSONRenderer, fora do
            # alcance do mascaramento: tem de virar chave do dict antes. O
            # `format_exc_info` do structlog ocupava esta posicao ate a
            # TEC-293; ele entregava a mensagem da excecao junto, e sobre a
            # chave `exception` a unica defesa era a corrida de digitos, que
            # nao alcanca texto livre.
            _sanear_traceback,
```

- [ ] **Step 4: Rodar e ver passar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_logging_mascara.py tests/unit/test_sanear_traceback.py --tb=short
```

Esperado: tudo passa.

- [ ] **Step 5: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/app/logging.py tests/unit/test_logging_mascara.py
git commit -m "feat(TEC-293): o pipeline de log para de emitir a mensagem da excecao"
```

---

### Task 3: Os três sítios de arq/Redis recebem o texto de volta, por kwarg

Sem isto, esses três eventos ficam reduzidos ao tipo da exceção — e é exatamente onde a D3 da TEC-292 disse que o texto é o diagnóstico que importa (`Error 111 connecting to localhost:6379`).

**Files:**
- Modify: `src/mobia/domain/agente/turno.py:565-566`
- Modify: `src/mobia/workers/jobs/process_message.py:191-198`
- Modify: `src/mobia/workers/jobs/gerar_resumo.py:46-48`
- Test: `tests/unit/test_motivo_de_agendamento.py` (criar)

**Interfaces:**
- Consumes: o pipeline da Task 2.
- Produces: os eventos `resumo_handoff.nao_agendado` e `notificacao.nao_agendada` passam a ter a chave `motivo: str`. Nenhum símbolo novo.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/test_motivo_de_agendamento.py`:

```python
"""O texto da falha de agendamento continua no log, agora por kwarg.

Saneado o traceback (TEC-293), estes tres sitios ficariam reduzidos a
`RedisError`. O texto e seguro aqui porque a unica coisa que estas chamadas
passam adiante e um UUID gerado por este projeto -- e a D3 da TEC-292.
"""

import logging
import uuid
from dataclasses import dataclass

from mobia.domain.agente.turno import _agendar_resumo


@dataclass
class _RegistroFalso:
    id: uuid.UUID
    criado: bool


class _AgendadorQueFalha:
    async def agendar(self, handoff_id: uuid.UUID) -> None:
        raise ConnectionError("Error 111 connecting to localhost:6379")


async def test_o_motivo_da_falha_de_agendamento_vai_para_o_log(caplog) -> None:
    registro = _RegistroFalso(id=uuid.uuid4(), criado=True)

    with caplog.at_level(logging.WARNING):
        await _agendar_resumo(_AgendadorQueFalha(), registro)

    assert "Error 111 connecting to localhost:6379" in caplog.text
    assert "resumo_handoff.nao_agendado" in caplog.text


async def test_a_falha_de_agendamento_nao_propaga(caplog) -> None:
    """O handoff ja esta commitado; derrubar o turno aqui perderia o resumo."""
    registro = _RegistroFalso(id=uuid.uuid4(), criado=True)

    with caplog.at_level(logging.WARNING):
        await _agendar_resumo(_AgendadorQueFalha(), registro)  # nao levanta
```

- [ ] **Step 2: Rodar e ver falhar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_motivo_de_agendamento.py --tb=short
```

Esperado: `test_o_motivo_da_falha_de_agendamento_vai_para_o_log` falha — o texto não está no log, porque o sítio só tem `exc_info=True` e a Task 2 já removeu a mensagem do traceback.

- [ ] **Step 3: Acrescentar o kwarg nos três sítios**

Em `src/mobia/domain/agente/turno.py`, o bloco `except` de `_agendar_resumo` passa de:

```python
    except Exception:
        log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)
```

para:

```python
    except Exception as falha:
        # `motivo` alem do traceback: desde a TEC-293 o traceback leva pilha e
        # tipo, nunca a mensagem, e aqui a mensagem e o diagnostico -- numa
        # queda do Redis o que se quer ler e `Error 111 connecting to
        # localhost:6379`. O texto e seguro neste ponto porque a unica coisa
        # que esta chamada passa adiante e `registro.id`, um UUID gerado por
        # este projeto: nao ha entrada externa para a excecao ecoar. Mesmo
        # argumento da D3 da TEC-292.
        log.warning(
            "resumo_handoff.nao_agendado",
            handoff_id=str(registro.id),
            motivo=str(falha),
            exc_info=True,
        )
```

Em `src/mobia/workers/jobs/process_message.py`, o bloco `except` passa de:

```python
        except Exception:
            # `exc_info=True`, e nao so `reason=type(falha).__name__`: este e
            # justamente o caminho de erro, onde o diagnostico mais importa.
            # O traceback aqui e da falha de AGENDAMENTO, no bloco que a
            # envolve -- nao o da excecao original do turno, que ja subiu e
            # foi tratada mais acima -- entao nao ha risco de confundir as
            # duas. Mesma fidelidade de `_agendar_resumo` em `turno.py`.
            log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)
```

para:

```python
        except Exception as falha:
            # `exc_info=True`, e nao so `reason=type(falha).__name__`: este e
            # justamente o caminho de erro, onde o diagnostico mais importa.
            # O traceback aqui e da falha de AGENDAMENTO, no bloco que a
            # envolve -- nao o da excecao original do turno, que ja subiu e
            # foi tratada mais acima -- entao nao ha risco de confundir as
            # duas. Mesma fidelidade de `_agendar_resumo` em `turno.py`.
            #
            # Desde a TEC-293 o traceback leva pilha e tipo, nunca a mensagem,
            # entao `motivo` carrega o texto -- que aqui e seguro, porque a
            # unica coisa que esta chamada passa adiante e `registro.id`, um
            # UUID gerado por este projeto. Mesmo argumento da D3 da TEC-292.
            log.warning(
                "resumo_handoff.nao_agendado",
                handoff_id=str(registro.id),
                motivo=str(falha),
                exc_info=True,
            )
```

Em `src/mobia/workers/jobs/gerar_resumo.py`, o bloco `except` passa de:

```python
    except Exception:
        log.warning("notificacao.nao_agendada", handoff_id=handoff_id, exc_info=True)
```

para:

```python
    except Exception as falha:
        # `motivo` alem do traceback, que desde a TEC-293 nao leva mensagem: o
        # texto de uma falha de `enqueue_job` e de conexao com o Redis, e e ele
        # que se le as tres da manha. Seguro aqui porque esta chamada so passa
        # `handoff_id` e o `_job_id` derivado dele -- UUID gerado por este
        # projeto. Mesmo argumento da D3 da TEC-292.
        log.warning(
            "notificacao.nao_agendada",
            handoff_id=handoff_id,
            motivo=str(falha),
            exc_info=True,
        )
```

- [ ] **Step 4: Rodar e ver passar**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_motivo_de_agendamento.py --tb=short
```

Esperado: 2 passed.

- [ ] **Step 5: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/turno.py src/mobia/workers/jobs/process_message.py src/mobia/workers/jobs/gerar_resumo.py tests/unit/test_motivo_de_agendamento.py
git commit -m "feat(TEC-293): o texto da falha de agendamento vai por kwarg, nao por traceback"
```

---

### Task 4: Os comentários que apontam a classe D como pendência deixam de apontar

Três comentários e uma docstring afirmam hoje que o traceback continua despejando o texto da exceção. A Task 2 os tornou falsos. Neste repo, comentário desatualizado é defeito — e estes descrevem justamente uma garantia de segurança, que é a pior classe de comentário para se mentir.

**Files:**
- Modify: `src/mobia/api/routes/whatsapp.py:84-89` (comentário de `webhook.error`)
- Modify: `src/mobia/api/routes/whatsapp.py:116-121` (comentário de `webhook.persist_failed`)
- Modify: `src/mobia/domain/catalogo/importacao.py:115-127` (comentário do `except` de `sincronizar`)
- Modify: `src/mobia/domain/messages/models.py:117-137` (docstring de `_exigir_bytes`)

**Interfaces:**
- Consumes: o pipeline da Task 2.
- Produces: nada. Esta tarefa não muda comportamento — só prosa dentro do código.

- [ ] **Step 1: `webhook.error`**

Em `src/mobia/api/routes/whatsapp.py`, as duas últimas frases do comentário passam de:

```python
        # `reason` (o nome da classe) basta para saber ONDE olhar. O
        # `log.exception` continua emitindo o traceback completo, e isso fica
        # de fora desta card -- e classe D no desenho, nao classe A.
```

para:

```python
        # `reason` (o nome da classe) basta para saber ONDE olhar. O
        # `log.exception` emite o traceback, que desde a TEC-293 leva pilha,
        # cadeia e tipo -- e nunca a mensagem, que era por onde o texto do
        # parser sobre o envelope de terceiro chegava ao log.
```

- [ ] **Step 2: `webhook.persist_failed`**

No mesmo arquivo, o comentário do `except` passa de:

```python
        # `detail` vem curado por `motivo_do_erro_de_banco`, mas o
        # `log.exception` abaixo continua despejando o traceback completo --
        # que termina no `IntegrityError: ... DETAIL: ...` do asyncpg do jeito
        # que `hide_parameters` nao alcanca. A curadoria do `detail` convive
        # com esse traceback; fecha-lo e classe D no desenho e ficou fora
        # desta card, mesma ressalva do `webhook.error` acima.
```

para:

```python
        # `detail` vem curado por `motivo_do_erro_de_banco`, e desde a TEC-293
        # o `log.exception` abaixo nao contradiz mais essa curadoria: o
        # traceback leva pilha, cadeia e tipo, nunca a mensagem. Ate entao ele
        # despejava o `IntegrityError: ... DETAIL: ...` do asyncpg -- que
        # `hide_parameters` nao alcanca, porque a linha `DETAIL` e escrita pelo
        # servidor -- ao lado do `detail` curado, e o vazamento liquido deste
        # ponto era o mesmo de antes da curadoria.
```

- [ ] **Step 3: O `except` de `sincronizar`**

Em `src/mobia/domain/catalogo/importacao.py`, acrescentar ao fim do comentário existente (depois de `# vazio.`, antes da linha `motivo_do_banco = motivo_do_erro_de_banco(erro)`):

```python
        #
        # O `log.exception` mais abaixo tambem nao repassa texto: desde a
        # TEC-293 o traceback leva pilha, cadeia e tipo, e nao a mensagem que
        # carregaria a mesma linha do arquivo importado.
```

- [ ] **Step 4: A docstring da guarda**

Em `src/mobia/domain/messages/models.py`, o parágrafo do meio da docstring de `_exigir_bytes` passa de:

```python
        **A guarda continua necessaria, por outro caminho.** Dos quatro, um --
        `webhook.persist_failed`, em `api/routes/whatsapp.py` -- loga com
        `log.exception`, e o traceback vai inteiro para a chave `exception`
        independente do que `detail=` carrega. O texto da excecao do asyncpg
        vive nesse traceback. Os outros tres usam `log.warning` e nao emitem
        traceback nenhum.
```

para:

```python
        **O canal do log fechou; a guarda continua necessaria por outra razao.**
        Ate a TEC-293, `webhook.persist_failed` logava com `log.exception` e o
        traceback levava o texto do asyncpg para a chave `exception`
        independente do que `detail=` carregava. Desde ela o traceback leva
        pilha, cadeia e tipo, e nenhum dos quatro sitios repassa mensagem.

        O que sustenta a guarda agora e a premissa da propria tabela, do
        TEC-126: conteudo pessoal nao fica em claro aqui. Escrever
        `Message(text_body="oi")` e o engano natural, e nenhuma decisao sobre
        log protege contra ele.
```

E o parágrafo final da mesma docstring, que passou a repetir o que o novo texto já diz, passa de:

```python
        Escrever `Message(text_body="oi")` e o engano natural, e e o que abre
        esse canal. Aqui a falha vira erro de aplicacao com mensagem que nos
        controlamos, e ela nunca cita o valor.
```

para:

```python
        Aqui a falha vira erro de aplicacao com mensagem que nos controlamos, e
        ela nunca cita o valor.
```

- [ ] **Step 5: Rodar a suíte unitária e os gates**

```
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Esperado: nada muda de comportamento, então a suíte unitária fecha verde.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/api/routes/whatsapp.py src/mobia/domain/catalogo/importacao.py src/mobia/domain/messages/models.py
git commit -m "docs(TEC-293): os comentarios param de dizer que o traceback despeja a mensagem"
```

---

### Task 5: Verificação final — suíte inteira, prosa e a listagem de comentários

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-tec-293-traceback-sem-mensagem-de-excecao-design.md` (só o campo **Status**)
- Nenhum arquivo de código.

**Interfaces:**
- Consumes: tudo das Tasks 1 a 4.
- Produces: a evidência que o PR precisa.

- [ ] **Step 1: Rodar a suíte inteira, UMA vez**

```
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash do commit junto com o resultado. Regras deste repo que valem aqui:

- Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — ver "Quando o `-n 8` derruba o Postgres" no `CLAUDE.md` e rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).
- Uma falha isolada com `ConnectionResetError [WinError 64]` não autoriza conclusão nenhuma; ~5% dos connects falham assim nesta máquina.
- Se a primeira execução falhar, repita sobre a mesma árvore antes de culpar a mudança — é a única coisa que separa flake de regressão.

- [ ] **Step 2: Conferir as assertas de log que a mudança pode ter quebrado**

O plano da TEC-292 registrou que 17 assertas em 7 arquivos tocam `detail`/`reason`/`motivo`/`motivos`/`provedor`. Esta card acrescenta `motivo` a dois eventos e muda o conteúdo da chave `exception`. Se alguma quebrar, **decida conscientemente** — não ajuste a asserta para passar. Em especial, confira:

```
./.venv/Scripts/python.exe -m pytest tests/features/test_recepcao_de_mensagem.py tests/integration/test_notificacao_job.py --tb=short
```

Esses três eventos têm asserta hoje: `webhook.error` (`reason`), `webhook.persist_failed` (`reason`, `payload_sha256`, `remote_ip`) e `notificacao.nao_agendada` (presença do evento). Nenhuma toca a chave `exception`, então a expectativa é que passem sem alteração — se alguma falhar, leia o motivo antes de mexer.

- [ ] **Step 3: Rodar a listagem de comentários tocados**

```
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reconferir cada `ALTERADO` e `VIZINHO`, e tratar `FALSO` como afirmação, não suspeita. Atenção especial às marcas `PROSA` e `NOMEIA`: esta branch cita `app/logging.py` em prosa versionada, e os números de linha mudaram.

- [ ] **Step 4: Virar o status do desenho**

Em `docs/superpowers/specs/2026-09-20-tec-293-traceback-sem-mensagem-de-excecao-design.md`, trocar `**Status:** aprovado, não implementado` por `**Status:** implementado`.

- [ ] **Step 5: Rodar os três gates uma última vez**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit e push**

```bash
git add docs/superpowers/specs/2026-09-20-tec-293-traceback-sem-mensagem-de-excecao-design.md
git commit -m "docs(TEC-293): o desenho passa a implementado"
git push -u origin feat/tec-293-traceback-sem-mensagem-de-excecao
```

Depois: abrir o PR contra `main`, comentar na card e movê-la para **Em análise** (não para Feito — quem mergeia é que fecha). O comentário da card precisa registrar o que some se ficar só no PR:

- que a card supunha que os trechos de código-fonte faziam parte do vazamento, e a medição mostrou que não — a decisão de omiti-los é de volume, não de proteção;
- que a mensagem vazava duas vezes numa cadeia SQLAlchemy/asyncpg, o que descarta qualquer saneador textual;
- que a mensagem livre some de **todo** traceback do sistema, não só dos seis sítios — um `KeyError('conversation_key')` passa a aparecer como `KeyError` e a pilha;
- que a opção 3 da card (regra de conteúdo no mascarador) foi remedida e continua recusada;
- que a ressalva da D4 da TEC-292 sobre `webhook.persist_failed` fica fechada por esta card.

---

## Autoavaliação do plano

**Cobertura do desenho:** D1 → Tasks 1 e 2. D2 → Task 1 (`test_a_linha_de_codigo_fonte_fica_de_fora`). D3 → Task 1 (os quatro testes de cadeia). D4 → Task 3. D5 → Task 2. A seção "O que se perde" não pede código; vira item do comentário da card, na Task 5.

**Consistência de nomes:** `_sanear_traceback`, `_excecao_de`, `_ELO_CAUSA` e `_ELO_CONTEXTO` são definidos na Task 1 e usados com a mesma grafia nas Tasks 2 e 3. O kwarg novo chama-se `motivo` nos três sítios da Task 3, seguindo o nome que `montagem.py` e `moderacao.py` já usam desde a TEC-237.

**Verificado antes da entrega:** `asyncio_mode = "auto"` no `pyproject.toml`, então os testes async da Task 3 não levam marcador — é a convenção dominante do repo. `record.exc_info` vale literalmente `False` quando o stdlib recebe `exc_info=False`, então a asserta da Task 2 está certa. E `[tool.mypy].files` lista só `src` e `alembic`, então passar `None` como logger nos testes não reprova o gate de tipos.

**Risco conhecido que a execução pode encontrar:** `_agendar_resumo` em `turno.py` é privada, e o teste da Task 3 a importa direto. Se a convenção do repo for testar por fora, o teste equivalente pode ser escrito sobre `executar_turno` — mas `executar_turno` tem 1877 linhas e montar o estado dela custaria muito mais que o que este teste prova. A importação direta é deliberada.
