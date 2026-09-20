# TEC-292 — log sem texto de exceção de terceiro — plano de implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans`. Os passos usam checkbox (`- [ ]`).

**Goal:** Tirar do log — e de um destino servido por HTTP — o texto de exceção de terceiro nos pontos em que ele pode ecoar entrada externa, trocando-o por campos estruturados onde há o que extrair.

**Architecture:** Um extrator novo (`motivo_do_erro_de_banco`) devolve `sqlstate`, `table_name` e `constraint_name` da exceção do asyncpg embrulhada pela SQLAlchemy, e nunca a linha `DETAIL`, que é o vetor medido. Ele substitui `detail=str(exc)` nos quatro pontos de banco. Mais três edições pontuais: o ponto do parser perde o `detail`, o de `imoveis.py` para de interpolar o erro (tem destino servido por HTTP), e o `motivo_do_provedor` de `embeddings.py` passa a extrair campos como o da Anthropic em vez de repassar `str(exc)`.

**Tech Stack:** Python 3.13, SQLAlchemy async, asyncpg, structlog, OpenAI SDK, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-292-log-sem-texto-de-excecao-de-terceiro-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento** — exceto valor citado. Nenhum linter checa isto.
- `ruff` com `line-length = 100`.
- Assunto de commit em português sem acento, formato `tipo(TEC-292): o que passou a ser verdade`.
- Gates: `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy` **sem argumento** (desde a TEC-224 ele cobre `src` e `alembic`).
- Python da venv: `./.venv/Scripts/python.exe`. Nunca `python` nu.
- **17 asserções em 7 arquivos de teste tocam os campos `detail`/`reason`/`motivo`/`motivos`/`provedor`.** Mudar o que se loga pode quebrá-las; isso é esperado e cada quebra precisa de decisão consciente, não de ajuste mecânico da asserção para passar.

## Medições desta máquina que o plano usa como esperado

Com `hide_parameters=True` (`infra/db.py`), o texto de um erro de banco **não** traz parâmetros — traz `[SQL parameters hidden due to hide_parameters=True]`. O vetor é a linha `DETAIL`, gerada pelo servidor:

- violação de UNIQUE: `DETAIL: Key (channel, provider_message_id)=(whatsapp, wamid...) already exists.`
- violação de CHECK: `DETAIL: Failing row contains (5511987654321, quero 2 quartos na zona sul, -1).`

O extrator candidato, já executado contra o Postgres desta máquina:

| caso | devolve |
| --- | --- |
| CHECK | `23514 table_name=s constraint_name=ck_s` |
| UNIQUE | `23505 table_name=s constraint_name=uq_s` |
| valor longo demais | `22001` |
| exceção que não é de banco | `None` |

---

### Task 1: O extrator `motivo_do_erro_de_banco`

**Files:**
- Modify: `src/mobia/infra/db.py` (62 linhas hoje)
- Test: `tests/integration/test_motivo_do_erro_de_banco.py` (criar)

**Interfaces:**
- Produces: `motivo_do_erro_de_banco(exc: BaseException) -> str | None`, em `mobia.infra.db`. A Task 2 a importa em quatro sítios.

Mora em `infra/db.py` porque é conhecimento sobre a forma da exceção do driver — o mesmo módulo que já configura `hide_parameters=True` pela razão vizinha.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/integration/test_motivo_do_erro_de_banco.py`:

```python
"""O que se pode logar de um erro de banco sem ecoar a linha que o causou.

Teste de integracao, e nao unitario, de proposito: o que se investiga aqui e a
FORMA da excecao que o asyncpg levanta e a SQLAlchemy embrulha. Duble nenhum
reproduz isso -- um `raise IntegrityError(...)` sintetico testaria a fixture,
nao o driver.
"""

import pytest
from sqlalchemy import text

from mobia.infra.db import get_engine, motivo_do_erro_de_banco

SENTINELA = "quero 2 quartos na zona sul"


async def _falhar(ddl_extra: str, params: dict) -> Exception:
    """Cria tabela temporaria, forca o INSERT a falhar e devolve a excecao."""
    conexao = await get_engine().connect()
    try:
        await conexao.execute(
            text(f"CREATE TEMP TABLE s (t varchar(8), c text, s int {ddl_extra})")
        )
        await conexao.execute(text("INSERT INTO s (t,c,s) VALUES ('a','ja existe',1)"))
        with pytest.raises(Exception) as capturada:
            await conexao.execute(text("INSERT INTO s (t,c,s) VALUES (:t,:c,:s)"), params)
        return capturada.value
    finally:
        await conexao.close()


async def test_violacao_de_check_nao_leva_a_linha_para_o_motivo() -> None:
    """O pior caso: o Postgres poe a LINHA INTEIRA no DETAIL.

    `Failing row contains (5511987654321, quero 2 quartos na zona sul, -1)` --
    e isso vem do servidor, entao o `hide_parameters=True` do cliente nao
    alcanca. As duas assertas importam: a primeira prova que o texto de fato
    carrega o sentinela, e sem ela a segunda seria asserta de ausencia sempre
    satisfeita (TEC-289).
    """
    exc = await _falhar(", CONSTRAINT ck_s CHECK (s >= 0)", {"t": "a", "c": SENTINELA, "s": -1})

    assert SENTINELA in str(exc), "o Postgres deixou de ecoar a linha; o teste perdeu o alvo"

    motivo = motivo_do_erro_de_banco(exc)
    assert motivo == "23514 table_name=s constraint_name=ck_s"
    assert SENTINELA not in motivo


async def test_violacao_de_unique_nomeia_a_constraint_sem_o_valor() -> None:
    exc = await _falhar(", CONSTRAINT uq_s UNIQUE (c)", {"t": "a", "c": "ja existe", "s": 1})

    assert "ja existe" in str(exc), "o Postgres deixou de ecoar o valor; o teste perdeu o alvo"
    assert motivo_do_erro_de_banco(exc) == "23505 table_name=s constraint_name=uq_s"


async def test_erro_sem_constraint_devolve_so_o_sqlstate() -> None:
    """`22001`, valor longo demais: nao ha constraint nem tabela a nomear."""
    exc = await _falhar("", {"t": "5511987654321", "c": SENTINELA, "s": 1})

    assert motivo_do_erro_de_banco(exc) == "22001"


def test_excecao_que_nao_e_de_banco_devolve_none() -> None:
    """Sem isso, o extrator poderia cair em algum ramo de melhor esforco -- que
    seria exatamente o buraco que ele existe para nao abrir.
    """
    assert motivo_do_erro_de_banco(ValueError("quero 2 quartos")) is None
```

- [ ] **Step 2: Rodar e confirmar que falha por `ImportError`**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_motivo_do_erro_de_banco.py --tb=short
```

Esperado: falha no import de `motivo_do_erro_de_banco`.

- [ ] **Step 3: Escrever o extrator**

Acrescentar a `src/mobia/infra/db.py`:

```python
def motivo_do_erro_de_banco(exc: BaseException) -> str | None:
    """O porque de um erro do Postgres, sem a linha que o causou.

    **O vetor nao e o que parece.** `hide_parameters=True`, logo acima, cala o
    eco de parametros da SQLAlchemy -- e ele funciona: o texto do erro traz
    `[SQL parameters hidden due to hide_parameters=True]`. O que vaza e a linha
    `DETAIL`, que o SERVIDOR escreve e nenhuma configuracao de cliente alcanca:

        UNIQUE -> DETAIL:  Key (channel, provider_message_id)=(whatsapp, wamid...)
        CHECK  -> DETAIL:  Failing row contains (5511987654321, quero 2 quartos, -1)

    O segundo despeja a LINHA INTEIRA. Medido na TEC-292.

    Dai extrair campos em vez de repassar texto. `sqlstate`, `table_name` e
    `constraint_name` vivem na excecao do asyncpg, que a SQLAlchemy embrulha --
    por isso o `orig.__cause__`. `detail` fica de fora de proposito: e ele o
    vetor.

    **Isto e diagnostico melhor, nao pior.** `23514 constraint_name=ck_...` e
    estruturado e greppavel; `str(exc)` obrigava a ler prosa para chegar no
    mesmo, e trazia os dados junto.

    Devolve `None` para o que nao for erro do driver -- sem ramo de melhor
    esforco, que seria o buraco que esta funcao existe para nao abrir.
    """
    origem = getattr(exc, "orig", None)
    causa = getattr(origem, "__cause__", None)
    sqlstate = getattr(causa, "sqlstate", None)
    if not isinstance(sqlstate, str):
        return None
    partes = [sqlstate]
    for campo in ("table_name", "constraint_name"):
        valor = getattr(causa, campo, None)
        if isinstance(valor, str) and valor:
            partes.append(f"{campo}={valor}")
    return " ".join(partes)
```

- [ ] **Step 4: Rodar o teste**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_motivo_do_erro_de_banco.py --tb=short
```

Esperado: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/infra/db.py tests/integration/test_motivo_do_erro_de_banco.py
git commit -m "feat(TEC-292): extrator de erro de banco que nao ecoa a linha"
```

---

### Task 2: Aplicar nos sete pontos

**Files:**
- Modify: `src/mobia/api/routes/whatsapp.py` (`:86` e `:113`)
- Modify: `src/mobia/domain/messages/recorder.py` (`:136` e `:203`)
- Modify: `src/mobia/domain/messages/service.py` (`:164`; o `:128` só ganha comentário)
- Modify: `src/mobia/workers/jobs/sweep_stalled.py` (`:105`, só comentário)
- Modify: `src/mobia/api/routes/imoveis.py` (`:87`)

**Interfaces:**
- Consumes: `motivo_do_erro_de_banco` de `mobia.infra.db` (Task 1).

- [ ] **Step 1: Os quatro pontos de banco**

Em `api/routes/whatsapp.py:113`, `domain/messages/recorder.py:136`, `domain/messages/recorder.py:203` e `domain/messages/service.py:164`, o padrão hoje é:

```python
            log.warning(
                "<evento>",
                ...,
                reason=type(exc).__name__,
                detail=str(exc),
            )
```

Trocar `detail=str(exc)` por `detail=motivo_do_erro_de_banco(exc)`, importando de `mobia.infra.db`.

`reason=type(exc).__name__` **fica** em todos: quando o extrator devolve `None` (erro de conexão, por exemplo), o nome da classe é tudo o que resta, e é o que já estava lá.

- [ ] **Step 2: O ponto do parser perde o `detail`**

Em `api/routes/whatsapp.py:86`, remover a linha `detail=str(exc),`. O `reason=type(exc).__name__` fica.

Acrescentar comentário explicando: o envelope da Meta é entrada externa por definição, e o eco do texto de uma exceção sobre ele não tem garantia de formato. **E registre, no mesmo comentário, que o `log.exception` desta chamada continua emitindo o traceback** — é classe D, fora desta card, e portanto o ponto não fica fechado por ela.

- [ ] **Step 3: `imoveis.py` para de interpolar o erro**

Em `api/routes/imoveis.py:87`, hoje:

```python
            motivo = f"falha ao enfileirar o job: {erro}"
```

Este valor vai para **dois** destinos: o log (`:130`) e `importacao.erros` (`:137`), coluna durável que o GET da rota devolve ao cliente. Pelo argumento da TEC-222 — destino durável e fora da máscara —, ele não pode carregar texto de terceiro; e aqui é pior, porque sai por HTTP.

Trocar por uma forma que nomeie a falha sem interpolar: o tipo da exceção basta (`type(erro).__name__`). Escreva o literal você mesmo e **comente por que**, citando os dois destinos.

- [ ] **Step 4: Os dois pontos de Redis ganham comentário, e só**

`domain/messages/service.py:128` (`enqueue.failed`) e `workers/jobs/sweep_stalled.py:105` (`sweep.enqueue_failed`) **mantêm** `detail=str(exc)`.

Acrescentar comentário curto registrando a razão: o único argumento do job é um UUID que este projeto gerou (`str(message_id)`), então não há entrada externa para a exceção ecoar; o texto que sobra é de nível de conexão (`Error 111 connecting to ...`), que é o que se quer ler quando a fila cai. Sem o comentário, a próxima varredura trata isto como esquecimento.

- [ ] **Step 5: Rodar os testes que tocam esses campos**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_recepcao_de_mensagem.py tests/integration/test_importacao_http.py --tb=short
```

**Quebra aqui é esperada e cada uma precisa de decisão.** Se uma asserção esperava `detail` com o texto da exceção, a pergunta é o que aquele teste queria provar — não "como faço passar". Relate cada quebra e o que decidiu.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/api/routes/whatsapp.py src/mobia/api/routes/imoveis.py src/mobia/domain/messages/recorder.py src/mobia/domain/messages/service.py src/mobia/workers/jobs/sweep_stalled.py tests/
git commit -m "fix(TEC-292): o log de erro de banco nomeia a constraint, nao a linha"
```

---

### Task 3: Alinhar o `motivo_do_provedor` de `embeddings.py`

**Files:**
- Modify: `src/mobia/infra/embeddings.py:115-127`
- Test: o arquivo de teste que já cobrir `embeddings` (procure `tests/unit/test_embeddings*.py`); se não houver, criar.

- [ ] **Step 1: Ler os dois lados**

`src/mobia/infra/anthropic.py:173` extrai `status_code`, `error.type` e `error.message` do `body`, com teto de `MAX_CARACTERES_DO_MOTIVO`. `src/mobia/infra/embeddings.py:115` faz `f"{exc.status_code}: {str(exc)[:MAX_CARACTERES_DO_MOTIVO]}"` — `str(exc)` cru.

O SDK da OpenAI renderiza `str()` de `APIStatusError` como `Error code: 400 - {'error': {'message': ..., 'param': ...}}`, e o `input` daquela chamada é o documento do imóvel montado a partir do arquivo importado.

- [ ] **Step 2: Escrever o teste que falha**

O duble segue o padrão que `tests/unit/test_motivo_do_provedor.py:23-32` já estabeleceu para a Anthropic — `httpx.Request` + `httpx.Response` + a classe de erro do SDK. **Já verifiquei que o SDK da OpenAI aceita a mesma forma.**

Criar `tests/unit/test_motivo_do_provedor_de_embeddings.py`:

```python
"""O `motivo_do_provedor` de embeddings tinha o nome do outro e garantia menor.

`infra/anthropic.py` extrai `status_code`, `error.type` e `error.message` do
corpo. `infra/embeddings.py` repassava `str(exc)[:300]` -- e o SDK da OpenAI
renderiza `str()` como `Error code: 400 - <corpo inteiro>`. O `input` daquela
chamada e o documento do imovel, montado a partir do arquivo importado.

Medido antes da TEC-292: o retorno era
`400: Error code: 400 - apartamento na Rua das Palmeiras com 3 quartos`.
"""

import httpx
from openai import APIConnectionError, BadRequestError

from mobia.infra.embeddings import motivo_do_provedor

SENTINELA = "apartamento na Rua das Palmeiras com 3 quartos"


def _erro_do_provedor(corpo: object) -> BadRequestError:
    """Um 400 do SDK cujo `str()` carrega o sentinela e cujo `body` nao."""
    requisicao = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    resposta = httpx.Response(400, request=requisicao)
    return BadRequestError(f"Error code: 400 - {SENTINELA}", response=resposta, body=corpo)


def test_o_texto_cru_do_sdk_nao_atravessa() -> None:
    """As duas assertas importam: a primeira prova que o `str()` do SDK de fato
    carrega o sentinela, e sem ela a segunda passaria mesmo que o SDK mudasse.
    """
    exc = _erro_do_provedor(
        {"error": {"type": "invalid_request_error", "message": "input is too long"}}
    )

    assert SENTINELA in str(exc), "o SDK mudou o render; o teste perdeu o alvo"

    motivo = motivo_do_provedor(exc)

    assert motivo == "400 invalid_request_error: input is too long"
    assert SENTINELA not in motivo


def test_sem_corpo_sobra_o_codigo_de_status() -> None:
    """Degradar para `400` e o comportamento certo: o codigo sozinho ja separa
    erro de conta de erro de contrato, que e o que a TEC-237 comprou.
    """
    exc = _erro_do_provedor(None)

    assert motivo_do_provedor(exc) == "400"
    assert SENTINELA not in motivo_do_provedor(exc)


def test_excecao_que_nao_e_de_status_nao_passa_nada() -> None:
    requisicao = httpx.Request("POST", "https://api.openai.com/v1/embeddings")

    assert motivo_do_provedor(APIConnectionError(request=requisicao)) is None
```

- [ ] **Step 3: Reescrever a função**

Em `src/mobia/infra/embeddings.py`, o corpo passa a espelhar o da Anthropic — **este código foi executado contra os três casos do teste acima**:

```python
    if not isinstance(exc, APIStatusError):
        return None

    corpo = exc.body if isinstance(exc.body, dict) else {}
    erro = corpo.get("error")
    erro = erro if isinstance(erro, dict) else {}

    tipo = erro.get("type")
    mensagem = erro.get("message")

    partes = [str(exc.status_code)]
    if isinstance(tipo, str) and tipo:
        partes.append(tipo)
    resumo = " ".join(partes)
    if isinstance(mensagem, str) and mensagem:
        cortada = mensagem[:MAX_CARACTERES_DO_MOTIVO]
        sufixo = "..." if len(mensagem) > MAX_CARACTERES_DO_MOTIVO else ""
        resumo = f"{resumo}: {cortada}{sufixo}"
    return resumo
```

**Corrija o docstring junto.** Ele afirma seguir "a mesma exceção deliberada" do `anthropic.py` — e hoje não segue, porque aquele extrai campos e este repassava `str(exc)`. Depois desta mudança passa a seguir; o docstring deve dizer o que a função faz, e registrar que a divergência existiu e o que ela vazava.

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit -k "embedding or provedor" --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add src/mobia/infra/embeddings.py tests/
git commit -m "fix(TEC-292): o motivo do provedor de embeddings extrai campos, nao str(exc)"
```

---

### Task 4: Gates, suíte, PR e o aviso à TEC-223

- [ ] **Step 1: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Atenção especial ao `VIZINHO`: esta branch mexe em blocos `except` que têm comentário ao lado explicando a escolha de logar (ou não) o texto.

- [ ] **Step 3: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q
```

Guardar o hash com o resultado. Se reprovar, repetir sobre a mesma árvore antes de culpar a mudança.

- [ ] **Step 4: Push e PR contra `main`**

Depois: comentar na TEC-292 e movê-la para **Em análise**.

- [ ] **Step 5: Comentar na TEC-223 com a medição**

Aquela card quer pôr `CHECK` em `role`, `direction` e `content_type` de `messages`. Hoje `messages` não tem CHECK, então `Failing row contains` é impossível ali; depois dela, passa a ser possível.

O comentário registra: a medição do `Failing row contains`, que em `messages` o estrago é contido (colunas sensíveis são `bytea` cifrado, e o telefone cai no regex de dígitos do mascarador), e que a TEC-292 fechou o caminho pelos quatro pontos de log de banco — então a TEC-223 pode seguir sabendo, não às cegas.

- [ ] **Step 6: Abrir a card de seguimento da classe D**

Os 4 a 6 pontos de `exc_info`/`log.exception`, com os arquivos nomeados (`turno.py:566`, `process_message.py:198`, `gerar_resumo.py:48`, `importacao.py:111`, mais `whatsapp.py:83` e `:110` que são duplos) e a razão de terem ficado fora: traceback é o que torna erro diagnosticável, e removê-lo é decisão de outra natureza.
