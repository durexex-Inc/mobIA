# TEC-205 — Rate limiting por número e por IP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limitar a 20 mensagens/min por número de WhatsApp e a 100 requisições/min por IP, adiando o excedente por número em vez de recusá-lo, recusando o excedente por IP com 429, e registrando cada bloqueio numa tabela consultável.

**Architecture:** Um limitador de janela deslizante em Redis (ZSET, quatro comandos num pipeline) serve os dois escopos. O limite por número entra em `IngestionService.ingest`, imediatamente antes do enqueue, e troca a janela de debounce pelo atraso de backoff — o `_defer_by` do ARQ já é o mecanismo. O limite por IP entra como o primeiro middleware do projeto, aplicado a todas as rotas menos o webhook da Meta e o `/health`. Os bloqueios viram linhas em `rate_limit_events`, uma por chave por janela.

**Tech Stack:** Python 3.13, FastAPI/Starlette, SQLAlchemy async, Alembic, ARQ sobre `redis.asyncio` (o `ArqRedis` herda de `redis.asyncio.Redis`, então não há dependência nova), structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-tec-205-rate-limiting-por-numero-e-por-ip-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o literal citado. Nenhum linter checa isso.
- **Texto que o lead recebe: português COM acento.** Esta card não acrescenta nenhum texto ao lead — se você se vir escrevendo um, pare: não está no escopo.
- **Os três gates estáticos, nesta ordem, antes de qualquer commit:** `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy` (sem argumento). Passar no linter não é evidência sobre o formatador.
- **Comando local:** `./.venv/Scripts/python.exe -m <ferramenta>`.
- **Testes unitários enquanto se escreve:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, sem Docker). A suíte inteira, **uma vez**, no fim: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`.
- **Prefixo de chave Redis desta card:** `ratelimit:`. Nenhuma outra chave escrita à mão existe no repo; não invente um segundo prefixo.
- **Janela dos dois limites:** 60 segundos, constante `JANELA_DE_UM_MINUTO` definida na Task 1 e importada por quem precisar. Não redeclare o 60.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-205): o que passou a ser verdade`, terminando com o trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: O limitador de janela deslizante

**Files:**
- Create: `src/mobia/infra/rate_limit.py`
- Test: `tests/integration/test_rate_limit.py`

**Interfaces:**
- Consumes: nada — é a base de tudo.
- Produces:
  - `JANELA_DE_UM_MINUTO: float` (`= 60.0`)
  - `@dataclass(frozen=True) class Consumo: permitido: bool; volume: int`
  - `async def consumir(pool: Redis | None, *, chave: str, limite: int, janela_segundos: float, agora: float | None = None) -> Consumo`
  - `def chave_de_numero(channel: str, conversation_key: str) -> str`
  - `def chave_de_ip(ip: str) -> str`
  - `def chave_de_guarda(escopo: str, chave: str) -> str`

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_rate_limit.py`:

```python
"""O limitador de janela deslizante contra Redis real (TEC-205).

Integracao e nao unitario de proposito: o que este modulo afirma -- que quatro
comandos num pipeline produzem uma janela deslizante correta -- e afirmacao
sobre o Redis, nao sobre aritmetica nossa. Um duble provaria so o duble.

O relogio entra por parametro (`agora`), entao nenhum teste dorme e nenhum
depende de onde caiu a borda do minuto.
"""

import math

import pytest

from mobia.infra.rate_limit import (
    JANELA_DE_UM_MINUTO,
    chave_de_ip,
    chave_de_numero,
    consumir,
)


async def test_abaixo_do_limite_permite(redis_pool) -> None:
    for i in range(3):
        consumo = await consumir(
            redis_pool, chave="t:1", limite=3, janela_segundos=60.0, agora=1000.0 + i
        )
        assert consumo.permitido is True
    assert consumo.volume == 3


async def test_o_excedente_e_bloqueado(redis_pool) -> None:
    for i in range(3):
        await consumir(
            redis_pool, chave="t:2", limite=3, janela_segundos=60.0, agora=1000.0 + i
        )
    consumo = await consumir(
        redis_pool, chave="t:2", limite=3, janela_segundos=60.0, agora=1003.0
    )
    assert consumo.permitido is False
    assert consumo.volume == 4


async def test_a_janela_desliza(redis_pool) -> None:
    """O mais antigo sai da janela e a vaga volta -- sem esperar 60s."""
    for i in range(3):
        await consumir(
            redis_pool, chave="t:3", limite=3, janela_segundos=60.0, agora=1000.0 + i
        )
    # 1061 deixa 1000 e 1001 para tras (a remocao e por score <= agora-janela)
    # e mantem 1002. Uma vaga livre, entao permite.
    consumo = await consumir(
        redis_pool, chave="t:3", limite=3, janela_segundos=60.0, agora=1061.0
    )
    assert consumo.permitido is True
    assert consumo.volume == 2


async def test_limite_zero_desliga(redis_pool) -> None:
    """Zero desliga, como `debounce_de_rajada_segundos`. Nem toca no Redis."""
    for _ in range(50):
        consumo = await consumir(
            redis_pool, chave="t:4", limite=0, janela_segundos=60.0, agora=1000.0
        )
        assert consumo.permitido is True
    assert await redis_pool.exists("t:4") == 0


async def test_pool_ausente_permite(redis_pool) -> None:
    """Fail-open: um guarda indisponivel nao pode virar a negacao de servico
    que ele existia para evitar. Mesmo contrato de `moderar_entrada_e_marcar`.
    """
    consumo = await consumir(None, chave="t:5", limite=1, janela_segundos=60.0)
    assert consumo.permitido is True
    assert consumo.volume == 0


async def test_a_chave_expira_sozinha(redis_pool) -> None:
    await consumir(
        redis_pool, chave="t:6", limite=5, janela_segundos=60.0, agora=1000.0
    )
    assert 0 < await redis_pool.ttl("t:6") <= 60


async def test_chaves_de_escopos_diferentes_nao_se_misturam(redis_pool) -> None:
    assert chave_de_numero("whatsapp", "5511999") != chave_de_ip("5511999")
    assert chave_de_numero("whatsapp", "5511999").startswith("ratelimit:")
    assert chave_de_ip("203.0.113.7").startswith("ratelimit:")


@pytest.mark.parametrize("janela", [0.5, 60.0, 90.0])
async def test_o_ttl_cobre_a_janela_inteira(redis_pool, janela: float) -> None:
    """`EXPIRE` so aceita inteiro: arredondar para baixo apagaria a janela
    antes de ela fechar, e o limite abriria mais cedo do que devia.
    """
    await consumir(
        redis_pool, chave=f"t:7:{janela}", limite=5, janela_segundos=janela, agora=1000.0
    )
    # `- 1` porque o TTL e inteiro e ja pode ter descontado o segundo
    # corrente entre o EXPIRE e a leitura. Sem essa folga a assercao e flaky
    # por construcao, nao por ambiente.
    assert await redis_pool.ttl(f"t:7:{janela}") >= math.ceil(janela) - 1


def test_a_janela_do_card_e_de_um_minuto() -> None:
    assert JANELA_DE_UM_MINUTO == 60.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rate_limit.py --tb=short
```

Esperado: `ModuleNotFoundError: No module named 'mobia.infra.rate_limit'`. (Precisa do `docker compose` de pé. Se vierem dezenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`, espere e repita — ver CLAUDE.md, "O banco demora mais que o healthcheck diz".)

- [ ] **Step 3: Write the implementation**

Crie `src/mobia/infra/rate_limit.py`:

```python
"""Limitador de volume por janela deslizante, em Redis (TEC-205, RNF-16).

Uma funcao, dois escopos: 20 mensagens por minuto por numero e 100
requisicoes por minuto por IP saem do mesmo `consumir`, mudando limite e
chave. Quem decide o que fazer com o `Consumo` e quem chama -- a ingestao
adia, o middleware recusa com 429.

**Janela deslizante e nao janela fixa.** `INCR`/`EXPIRE` por minuto de relogio
seria mais barato e mediria a coisa errada: uma rajada que cruza a borda do
minuto passa com ate o dobro do limite, e o teste do vigesimo primeiro envio
passaria a depender de onde a borda caiu. O criterio de aceite da card fala em
"no ultimo minuto", que e literalmente o que o ZSET mede.

**O relogio entra por parametro.** Sem isso, todo teste de borda teria de
dormir. Producao nunca passa `agora`.

Este e o primeiro modulo do repo a escrever chave Redis a mao -- ate aqui so
existia o namespace `arq:`, da propria biblioteca. O prefixo e `ratelimit:`.
"""

import math
import uuid
from dataclasses import dataclass
from time import time

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PREFIXO = "ratelimit"

# A janela dos dois limites da RNF-16. Vive aqui e nao em `Settings` porque
# nao e configuracao: e a unidade em que o requisito esta escrito ("por
# minuto"). O que e configuravel e o limite, nao a janela.
JANELA_DE_UM_MINUTO = 60.0


@dataclass(frozen=True)
class Consumo:
    """O veredito e o volume que o produziu.

    `volume` inclui a requisicao recem-avaliada: com limite 20, a vigesima
    primeira devolve `volume=21`. E esse numero que a tabela de eventos grava
    como "o volume que disparou o limite".
    """

    permitido: bool
    volume: int


def chave_de_numero(channel: str, conversation_key: str) -> str:
    return f"{PREFIXO}:numero:{channel}:{conversation_key}"


def chave_de_ip(ip: str) -> str:
    return f"{PREFIXO}:ip:{ip}"


def chave_de_guarda(escopo: str, chave: str) -> str:
    """A chave que garante UMA linha de evento por chave por janela.

    Nao reaproveita a chave do zset: aquela e um zset e esta e uma string, e o
    Redis recusaria o `SET` sobre o tipo errado com WRONGTYPE.
    """
    return f"{PREFIXO}:evento:{escopo}:{chave}"


async def consumir(
    pool: Redis | None,
    *,
    chave: str,
    limite: int,
    janela_segundos: float,
    agora: float | None = None,
) -> Consumo:
    """Conta a requisicao na janela e diz se ela cabe.

    Fail-open em toda falha -- pool ausente, Redis fora do ar. O precedente e a
    moderacao (`domain/messages/bloqueio.py`), que deixa passar quando o
    provedor nao responde: um guarda indisponivel nao pode virar a negacao de
    servico que ele existia para evitar.
    """
    if limite <= 0 or pool is None:
        return Consumo(permitido=True, volume=0)

    instante = time() if agora is None else agora

    try:
        pipe = pool.pipeline(transaction=True)
        # Inclusivo no limite inferior: o evento com score exatamente
        # `instante - janela` ja completou a janela e sai.
        pipe.zremrangebyscore(chave, "-inf", instante - janela_segundos)
        # Membro unico por requisicao. Usar o timestamp como membro colapsaria
        # duas requisicoes do mesmo instante numa so -- e e exatamente na
        # rajada que isso aconteceria.
        pipe.zadd(chave, {str(uuid.uuid4()): instante})
        pipe.zcard(chave)
        # `ceil` e nao `int`: truncar 0.5 para 0 faria o EXPIRE apagar a chave
        # imediatamente e o limite nunca prenderia.
        pipe.expire(chave, math.ceil(janela_segundos))
        resultado = await pipe.execute()
    except RedisError as exc:
        log.warning("ratelimit.indisponivel", erro=type(exc).__name__)
        return Consumo(permitido=True, volume=0)

    volume = int(resultado[2])
    return Consumo(permitido=volume <= limite, volume=volume)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rate_limit.py --tb=short
```

Esperado: 10 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/infra/rate_limit.py tests/integration/test_rate_limit.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): a janela deslizante que conta volume por chave

Primeiro modulo do repo a escrever chave Redis a mao; ate aqui so existia
o namespace `arq:`. Janela deslizante em ZSET e nao INCR por minuto de
relogio: a segunda mede "neste minuto" e nao "nos ultimos 60s", deixa
passar ate o dobro na borda, e faria o teste do 21o envio depender de
onde a borda caiu.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Os quatro campos de configuração

**Files:**
- Modify: `src/mobia/app/config.py` (acrescentar campos logo abaixo de `debounce_de_rajada_segundos`, e um `model_validator` junto dos demais)
- Modify: `.env.example`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `Settings.rate_limit_mensagens_por_minuto: int`, `Settings.rate_limit_requisicoes_por_ip_por_minuto: int`, `Settings.atraso_de_backoff_segundos: float`, `Settings.confiar_em_forwarded_for: bool`.

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/unit/test_config.py`:

```python
def test_os_limites_da_rnf_16_sao_os_defaults() -> None:
    settings = Settings()
    assert settings.rate_limit_mensagens_por_minuto == 20
    assert settings.rate_limit_requisicoes_por_ip_por_minuto == 100


def test_o_backoff_tem_default_e_e_float() -> None:
    settings = Settings()
    assert settings.atraso_de_backoff_segundos == 30.0


def test_confiar_em_forwarded_for_vem_desligado() -> None:
    """O default e o inseguro-contra-proxy, nao o inseguro-contra-spoof.

    Atras de proxy sem a chave ligada o limite fica mais apertado do que se
    quer e alguem reclama; com a confianca ligada por omissao e sem proxy o
    limite simplesmente nao existe e ninguem reclama. Falha que se anuncia e
    melhor que falha silenciosa. Ver D7 do desenho.
    """
    assert Settings().confiar_em_forwarded_for is False


def test_limite_negativo_e_recusado() -> None:
    with pytest.raises(ValidationError):
        Settings(rate_limit_mensagens_por_minuto=-1)
    with pytest.raises(ValidationError):
        Settings(rate_limit_requisicoes_por_ip_por_minuto=-1)


def test_backoff_negativo_e_recusado() -> None:
    """`_defer_by` negativo agendaria para o passado, e o excedente seria
    processado ANTES da mensagem que respeitou o limite.
    """
    with pytest.raises(ValidationError):
        Settings(atraso_de_backoff_segundos=-1.0)
```

Confira o topo de `tests/unit/test_config.py`: se `pytest` ou `ValidationError` (de `pydantic`) ainda não estiverem importados, acrescente os imports.

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py --tb=short
```

Esperado: FAIL — `AttributeError` / `ValidationError` por campo extra, conforme o `extra="ignore"` do `model_config`.

- [ ] **Step 3: Write the implementation**

Em `src/mobia/app/config.py`, logo depois da linha `debounce_de_rajada_segundos: float = 6.0`:

```python
    # RNF-16 (TEC-205). Zero desliga, pela mesma convencao do vizinho acima.
    #
    # A janela dos dois e de um minuto e NAO e configuravel: ela nao e ajuste,
    # e a unidade em que o requisito esta escrito. Vive em
    # `infra/rate_limit.JANELA_DE_UM_MINUTO`.
    #
    # "Configuravel sem deploy" da card e atendido ate onde o repo alcanca
    # hoje: variavel de ambiente, que em container e restart e nao rebuild.
    # Alterar em runtime exigiria ler a configuracao de fora do processo, que e
    # subsistema do epico RF-19 -- a mesma lacuna que `followup/cadencia.py` e
    # `outbound/antispam.py` ja declaram. Nao a resolva aqui de passagem.
    rate_limit_mensagens_por_minuto: int = 20
    rate_limit_requisicoes_por_ip_por_minuto: int = 100

    # O atraso aplicado ao excedente por numero, no lugar da janela de
    # debounce. Fixo e nao "ate a janela abrir": a versao precisa chegaria a
    # 60s e estouraria a folga da invariante da TEC-128 -- ver
    # `test_job_timeout_cabe_dentro_da_janela_do_sweeper`, que e quem prende
    # este numero. Subi-lo sem olhar aquele teste reabre uma conta de tres
    # termos que mora em dois arquivos.
    #
    # `float` e nao `int` pela razao dos vizinhos: o teste precisa de
    # centesimos de segundo.
    atraso_de_backoff_segundos: float = 30.0

    # De onde sai o IP que o limitador conta. Desligado, e o socket
    # (`request.client.host`), que nao e forjavel. Ligado, e o ULTIMO salto de
    # `X-Forwarded-For` -- o ultimo, e nao o primeiro, porque e o unico que o
    # proxy imediato escreveu e portanto o unico que o cliente nao controla.
    #
    # Ligue quando a API estiver atras de proxy ou ingress. Sem isso, o limite
    # por IP la vira um limite global por proxy: todos os visitantes do widget
    # dividem as mesmas 100 requisicoes.
    confiar_em_forwarded_for: bool = False
```

E, junto dos demais validators:

```python
    @model_validator(mode="after")
    def _recusar_rate_limit_impossivel(self) -> "Settings":
        """Numero negativo aqui falha em silencio ou inverte o fluxo.

        Limite negativo cai no mesmo ramo que o zero (`limite <= 0` em
        `consumir`) e desliga o limitador -- so que parecendo configurado, que
        e a pior das duas coisas. Atraso negativo vira `_defer_by` para o
        passado e o excedente seria processado ANTES da mensagem que respeitou
        o limite.

        `ValueError` e nao `ConfiguracaoInsegura` pelo criterio ja aplicado em
        `_recusar_horario_de_envio_impossivel`: isto nao roda sem a protecao
        que devia ter, isto deixa de operar.
        """
        if self.rate_limit_mensagens_por_minuto < 0:
            raise ValueError(
                "rate_limit_mensagens_por_minuto nao pode ser negativo; recebi "
                f"{self.rate_limit_mensagens_por_minuto}. Use 0 para desligar o limite."
            )
        if self.rate_limit_requisicoes_por_ip_por_minuto < 0:
            raise ValueError(
                "rate_limit_requisicoes_por_ip_por_minuto nao pode ser negativo; recebi "
                f"{self.rate_limit_requisicoes_por_ip_por_minuto}. Use 0 para desligar."
            )
        if self.atraso_de_backoff_segundos < 0:
            raise ValueError(
                "atraso_de_backoff_segundos nao pode ser negativo; recebi "
                f"{self.atraso_de_backoff_segundos}. Um defer negativo agendaria o "
                "excedente para antes de quem respeitou o limite."
            )
        return self
```

E em `.env.example`, ao fim:

```bash
# Rate limiting da RNF-16 (TEC-205). Zero desliga qualquer um dos dois.
# `ATRASO_DE_BACKOFF_SEGUNDOS` e quanto o excedente por numero espera a mais
# antes de virar turno; subi-lo esbarra na invariante do sweeper, ver
# test_job_timeout_cabe_dentro_da_janela_do_sweeper.
RATE_LIMIT_MENSAGENS_POR_MINUTO=20
RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO=100
ATRASO_DE_BACKOFF_SEGUNDOS=30.0
# Ligue quando a API estiver atras de proxy/ingress; sem proxy, ligar isso
# deixa qualquer cliente escapar do limite forjando X-Forwarded-For.
CONFIAR_EM_FORWARDED_FOR=false
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py --tb=short
```

Esperado: todos passam, incluindo os que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/app/config.py .env.example tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): os limites da RNF-16 viram configuracao

Quatro campos, com zero desligando cada limite pela convencao de
`debounce_de_rajada_segundos`. O validator recusa negativo porque limite
negativo cai no mesmo ramo do zero e desliga o limitador parecendo
configurado, e atraso negativo agendaria o excedente para antes de quem
respeitou o limite.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: A tabela `rate_limit_events`

**Files:**
- Create: `src/mobia/domain/limites/__init__.py` (vazio)
- Create: `src/mobia/domain/limites/models.py`
- Create: `alembic/versions/0038_rate_limit_events.py`
- Modify: `tests/conftest.py` (a tupla `TABELAS`)
- Test: `tests/integration/test_rate_limit_events.py`

**Interfaces:**
- Consumes: nada da Task 1 ou 2.
- Produces: `RateLimitEvent` (SQLAlchemy model, `__tablename__ = "rate_limit_events"`), e as constantes `ESCOPO_NUMERO = "numero"`, `ESCOPO_IP = "ip"`, `CHANNEL_HTTP = "http"`.

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_rate_limit_events.py`:

```python
"""A tabela append-only de bloqueio por rate limit (TEC-205)."""

import uuid

from sqlalchemy import select

from mobia.domain.limites.models import (
    CHANNEL_HTTP,
    ESCOPO_IP,
    ESCOPO_NUMERO,
    RateLimitEvent,
)


async def test_grava_o_bloqueio_por_numero(session) -> None:
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_NUMERO,
            chave="5511999999999",
            channel="whatsapp",
            volume=21,
            limite=20,
            message_id=uuid.uuid4(),
        )
    )
    await session.commit()

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.escopo == ESCOPO_NUMERO
    assert linha.volume == 21
    assert linha.limite == 20
    # `created_at` e do relogio do Postgres, como em `optout_events`: a ORDEM
    # dos eventos e o estado, e relogios de processo divergem.
    assert linha.created_at is not None


async def test_o_escopo_ip_nao_tem_message_id(session) -> None:
    """No escopo IP nao ha mensagem: o bloqueio acontece antes da rota."""
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_IP,
            chave="203.0.113.7",
            channel=CHANNEL_HTTP,
            volume=101,
            limite=100,
            message_id=None,
        )
    )
    await session.commit()

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.message_id is None
    assert linha.channel == CHANNEL_HTTP


async def test_o_limite_vigente_fica_na_linha(session) -> None:
    """Sem o limite ao lado, "volume 21" nao diz se houve abuso -- e o limite
    e configuravel, entao o de hoje nao explica o evento de ontem.
    """
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_NUMERO,
            chave="5511888888888",
            channel="whatsapp",
            volume=6,
            limite=5,
            message_id=uuid.uuid4(),
        )
    )
    await session.commit()
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.volume > linha.limite
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rate_limit_events.py --tb=short
```

Esperado: `ModuleNotFoundError: No module named 'mobia.domain.limites'`.

- [ ] **Step 3: Write the model**

Crie `src/mobia/domain/limites/__init__.py` vazio e `src/mobia/domain/limites/models.py`:

```python
"""O registro de bloqueio por rate limit, append-only (TEC-205, RNF-16).

Uma linha por chave por janela, nao por requisicao bloqueada. Escrever uma
linha por requisicao transformaria o registro de abuso no proprio vetor de
abuso: no widget, o atacante escreveria uma linha de banco por requisicao e a
defesa custaria mais que o ataque. Quem garante a unicidade e a chave
`ratelimit:evento:*` em Redis (`domain/limites/eventos.py`), nao um UNIQUE --
o banco nao tem como saber onde uma janela deslizante comeca.

**`limite` fica na linha porque o limite e configuravel.** Um evento que guarda
so o volume vira ilegivel no dia em que alguem mudar a configuracao: "volume
21" nao diz se houve abuso sem o 20 ao lado.

**Nunca o conteudo da mensagem.** Mesma regra de `moderation_events`: a card
pede o registro do evento -- numero, momento, volume --, nao do que foi dito.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base

ESCOPO_NUMERO = "numero"
ESCOPO_IP = "ip"

# O canal do escopo IP. Nao e "web": o middleware cobre toda rota HTTP, e o
# bloqueio ali e de uma requisicao a API, nao de mensagem de canal nenhum.
CHANNEL_HTTP = "http"


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    escopo: Mapped[str] = mapped_column(String(8), nullable=False)

    # O numero do lead no escopo `numero`, o IP no escopo `ip`. Inteiro, e nao
    # mascarado: esta tabela e a evidencia que responde "quem foi" numa
    # investigacao. Quem sai mascarado e o LOG, que vai para agregador e fica
    # muito mais exposto -- `ip` esta em `_CHAVES_MASCARADAS`
    # (`app/logging.py`) pelo mesmo motivo que `conversation_key` ja estava.
    chave: Mapped[str] = mapped_column(String(64), nullable=False)

    channel: Mapped[str] = mapped_column(String(32), nullable=False)

    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    limite: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nulo no escopo `ip`: la o bloqueio acontece antes de a rota rodar e nao
    # ha mensagem nenhuma. SEM FK, pelo motivo das migrations 0010 e 0020: a
    # retencao de `messages` (12 meses, RNF-22) e mais curta que a do registro
    # de conformidade, e uma FK apagaria evidencia por cascata.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_rate_limit_events_chave",
            "escopo",
            "chave",
            text("created_at DESC"),
        ),
    )
```

- [ ] **Step 4: Write the migration**

Crie `alembic/versions/0038_rate_limit_events.py`:

```python
"""registro append-only de bloqueio por rate limit

TEC-205, RNF-16. Uma linha por chave por janela -- a unicidade e garantida
por chave em Redis e nao por UNIQUE, porque o banco nao tem como saber onde
uma janela deslizante comeca.

`limite` fica na linha porque o limite e configuravel: sem ele ao lado, o
volume nao diz se houve abuso depois que alguem mudar a configuracao.

Sem FK para `messages`, pelo mesmo motivo da 0010 e da 0020: a retencao de
mensagens (12 meses, RNF-22) e mais curta que a do registro de conformidade.
`message_id` e nulo no escopo `ip`, onde o bloqueio antecede a rota e nao ha
mensagem nenhuma.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("escopo", sa.String(8), nullable=False),
        sa.Column("chave", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("limite", sa.Integer(), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_rate_limit_events_chave",
        "rate_limit_events",
        ["escopo", "chave", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_chave", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
```

Confirme que `0037` é mesmo a cabeça antes de gravar o `down_revision`:

```bash
ls alembic/versions/ | sort | tail -3
```

- [ ] **Step 5: Acrescentar a tabela ao `TRUNCATE`**

Em `tests/conftest.py`, dentro da tupla `TABELAS`, imediatamente antes do `)` que a fecha:

```python
    # TEC-205. Append-only como `moderation_events`: sem o truncate, o
    # bloqueio registrado por um teste vira evidencia do proximo, e a asserta
    # de "uma linha so por janela" passaria a contar linha alheia.
    "rate_limit_events",
```

Cada tabela nova entra no mesmo `TRUNCATE a, b, c CASCADE` que roda antes de todo teste que toca banco — é mais uma tabela no mesmo statement e mais um lock tomado junto, não mais um statement por teste.

- [ ] **Step 6: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rate_limit_events.py --tb=short
```

Esperado: 3 passed. Se vier `relation "rate_limit_events" does not exist` em vários testes, leia a seção de CLAUDE.md sobre bancos de worker com o carimbo adiantado antes de mexer na migration — o sintoma imita exatamente uma migration errada.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/limites/ alembic/versions/0038_rate_limit_events.py tests/conftest.py tests/integration/test_rate_limit_events.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): o bloqueio por rate limit tem tabela consultavel

O criterio de aceite pede o evento CONSULTADO -- numero, momento e
volume --, entao e tabela e nao linha de log. `limite` fica na linha
junto do volume porque o limite e configuravel: sem ele, "volume 21" nao
diz se houve abuso depois que alguem mudar a configuracao.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: O registro do evento, uma linha por janela

**Files:**
- Create: `src/mobia/domain/limites/eventos.py`
- Test: `tests/integration/test_registro_de_bloqueio.py`

**Interfaces:**
- Consumes: `chave_de_guarda`, `JANELA_DE_UM_MINUTO` (Task 1); `RateLimitEvent`, `ESCOPO_NUMERO`, `ESCOPO_IP`, `CHANNEL_HTTP` (Task 3).
- Produces: `async def registrar_bloqueio(session_factory: async_sessionmaker[AsyncSession], pool: Redis | None, *, escopo: str, chave: str, channel: str, volume: int, limite: int, message_id: uuid.UUID | None = None, janela_segundos: float = JANELA_DE_UM_MINUTO) -> bool` — devolve `True` quando gravou.

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_registro_de_bloqueio.py`:

```python
"""A guarda que faz UMA linha de evento por chave por janela (TEC-205)."""

import uuid

from sqlalchemy import func, select

from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_IP, ESCOPO_NUMERO, RateLimitEvent


async def _quantas(session) -> int:
    return (await session.execute(select(func.count()).select_from(RateLimitEvent))).scalar_one()


async def test_o_primeiro_bloqueio_grava(session_factory, redis_pool, session) -> None:
    gravou = await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_NUMERO,
        chave="5511999999999",
        channel="whatsapp",
        volume=21,
        limite=20,
        message_id=uuid.uuid4(),
    )
    assert gravou is True
    assert await _quantas(session) == 1


async def test_os_bloqueios_seguintes_da_mesma_janela_nao_gravam(
    session_factory, redis_pool, session
) -> None:
    """Sem esta guarda, o registro de abuso e o proprio vetor de abuso: uma
    linha de banco por requisicao bloqueada.
    """
    for volume in range(21, 121):
        await registrar_bloqueio(
            session_factory,
            redis_pool,
            escopo=ESCOPO_NUMERO,
            chave="5511999999999",
            channel="whatsapp",
            volume=volume,
            limite=20,
            message_id=uuid.uuid4(),
        )
    assert await _quantas(session) == 1

    # E o que ficou gravado e o volume do PRIMEIRO disparo -- "o volume que
    # disparou o limite", na letra do criterio de aceite.
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.volume == 21


async def test_chaves_diferentes_gravam_cada_uma(
    session_factory, redis_pool, session
) -> None:
    await registrar_bloqueio(
        session_factory, redis_pool, escopo=ESCOPO_NUMERO, chave="5511111111111",
        channel="whatsapp", volume=21, limite=20, message_id=uuid.uuid4(),
    )
    await registrar_bloqueio(
        session_factory, redis_pool, escopo=ESCOPO_NUMERO, chave="5522222222222",
        channel="whatsapp", volume=21, limite=20, message_id=uuid.uuid4(),
    )
    assert await _quantas(session) == 2


async def test_escopos_diferentes_com_a_mesma_chave_nao_se_calam(
    session_factory, redis_pool, session
) -> None:
    """A guarda e por (escopo, chave). Um numero e um IP textualmente iguais
    sao dois assuntos distintos.
    """
    await registrar_bloqueio(
        session_factory, redis_pool, escopo=ESCOPO_NUMERO, chave="123456789",
        channel="whatsapp", volume=21, limite=20, message_id=uuid.uuid4(),
    )
    await registrar_bloqueio(
        session_factory, redis_pool, escopo=ESCOPO_IP, chave="123456789",
        channel="http", volume=101, limite=100,
    )
    assert await _quantas(session) == 2


async def test_sem_redis_grava_e_nao_explode(session_factory, session) -> None:
    """Fail-open da guarda: sem Redis nao ha como deduplicar, e perder o
    registro do abuso e pior que registra-lo de mais.
    """
    gravou = await registrar_bloqueio(
        session_factory, None, escopo=ESCOPO_IP, chave="203.0.113.9",
        channel="http", volume=101, limite=100,
    )
    assert gravou is True
    assert await _quantas(session) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_registro_de_bloqueio.py --tb=short
```

Esperado: `ModuleNotFoundError: No module named 'mobia.domain.limites.eventos'`.

- [ ] **Step 3: Write the implementation**

Crie `src/mobia/domain/limites/eventos.py`:

```python
"""A gravacao do bloqueio por rate limit, com guarda de janela (TEC-205).

Uma linha por (escopo, chave) por janela. A guarda e um `SET NX EX` em Redis:
quem cria a chave grava a linha, os demais bloqueios da mesma janela so
aparecem no log. Ver o docstring de `models.py` para por que a alternativa --
uma linha por requisicao bloqueada -- transforma a defesa em vetor de ataque.

Este modulo NAO propaga excecao de banco. O bloqueio ja aconteceu e ja foi
logado quando ele e chamado; perder o registro nao pode derrubar a rota nem a
ingestao, que e o mesmo contrato de `MessageRecorder` e o oposto do de
`bloqueio.py`, onde a excecao sobe porque a marca de moderacao faz parte da
decisao. Aqui nao ha decisao pendurada na linha: ela e evidencia posterior.
"""

import uuid

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.limites.models import RateLimitEvent
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_guarda

log = structlog.get_logger(__name__)


async def _ganhou_a_guarda(
    pool: Redis | None, escopo: str, chave: str, janela_segundos: float
) -> bool:
    """Fail-open: sem Redis nao ha como deduplicar, e perder o registro do
    abuso e pior que registra-lo de mais.
    """
    if pool is None:
        return True
    try:
        criou = await pool.set(
            chave_de_guarda(escopo, chave),
            "1",
            nx=True,
            ex=max(1, int(janela_segundos)),
        )
    except RedisError as exc:
        log.warning("ratelimit.guarda_indisponivel", erro=type(exc).__name__)
        return True
    return bool(criou)


async def registrar_bloqueio(
    session_factory: async_sessionmaker[AsyncSession],
    pool: Redis | None,
    *,
    escopo: str,
    chave: str,
    channel: str,
    volume: int,
    limite: int,
    message_id: uuid.UUID | None = None,
    janela_segundos: float = JANELA_DE_UM_MINUTO,
) -> bool:
    """Grava o bloqueio se esta for a primeira vez nesta janela.

    Devolve se gravou. O `volume` que acaba na linha e, por consequencia, o do
    PRIMEIRO disparo da janela -- `limite + 1` no caso comum, que e
    literalmente "o volume que disparou o limite" do criterio de aceite. O
    volume total de cada janela continua visivel no log `ratelimit.blocked`,
    que sai a cada bloqueio.
    """
    if not await _ganhou_a_guarda(pool, escopo, chave, janela_segundos):
        return False

    try:
        async with session_factory() as session:
            session.add(
                RateLimitEvent(
                    id=uuid.uuid4(),
                    escopo=escopo,
                    chave=chave,
                    channel=channel,
                    volume=volume,
                    limite=limite,
                    message_id=message_id,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("ratelimit.evento_nao_gravado", erro=type(exc).__name__)
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_registro_de_bloqueio.py --tb=short
```

Esperado: 5 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/limites/eventos.py tests/integration/test_registro_de_bloqueio.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): uma linha de evento por chave por janela

A guarda e um SET NX EX: sem ela, um atacante no widget escreve uma linha
de banco por requisicao bloqueada e o registro de abuso vira o proprio
vetor de abuso. O volume total de cada janela continua no log; a tabela
guarda o volume do primeiro disparo, que e o que o criterio de aceite
chama de "o volume que disparou o limite".

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: O limite por número na ingestão

**Files:**
- Modify: `src/mobia/domain/messages/service.py` (o laço de `ingest`)
- Modify: `tests/integration/test_worker_startup.py` (a invariante ganha um termo)
- Test: `tests/integration/test_ingestao_sob_rate_limit.py`

**Interfaces:**
- Consumes: `consumir`, `chave_de_numero`, `JANELA_DE_UM_MINUTO` (Task 1); `Settings.rate_limit_mensagens_por_minuto`, `Settings.atraso_de_backoff_segundos` (Task 2); `registrar_bloqueio` (Task 4); `ESCOPO_NUMERO` (Task 3).
- Produces: nenhuma assinatura nova — `IngestionService.ingest` mantém a de hoje.

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_ingestao_sob_rate_limit.py`:

```python
"""O excedente por numero e adiado, nao recusado (TEC-205)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.limites.models import RateLimitEvent
from mobia.domain.messages.models import Message, MessageStatus
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.queue import PROCESS_MESSAGE_JOB


def _parsed(indice: int, remetente: str = "5511999999999") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=f"wamid.rl{indice}",
        sender_external_id=remetente,
        recipient_external_id="5511000000000",
        content_type="text",
        text_body=f"mensagem {indice}",
        raw_payload={},
    )


async def _defers(redis_pool) -> list[float]:
    """Quantos milissegundos no futuro cada job foi agendado."""
    agora_ms = datetime.now(UTC).timestamp() * 1000
    jobs = await redis_pool.zrange("arq:queue", 0, -1, withscores=True)
    return sorted(score - agora_ms for _, score in jobs)


async def test_dentro_do_limite_nada_muda(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "5")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(5)])

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0
    # Todas esperam a janela de debounce, nenhuma o backoff.
    janela_ms = get_settings().debounce_de_rajada_segundos * 1000
    for defer in await _defers(redis_pool):
        assert defer <= janela_ms + 500


async def test_o_excedente_espera_o_backoff(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    """Cenario do card: o vigesimo primeiro entra em backoff."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "1")
    monkeypatch.setenv("ATRASO_DE_BACKOFF_SEGUNDOS", "20")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(4)])

    defers = await _defers(redis_pool)
    assert len(defers) == 4
    # Tres em ~1s (a janela) e uma em ~20s (o backoff).
    assert sum(1 for d in defers if d > 10_000) == 1


async def test_o_excedente_nao_e_recusado(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    """Adiada, nao descartada: a linha existe e chega a QUEUED."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    ids = await service.ingest([_parsed(i) for i in range(4)])

    assert len(ids) == 4
    status = (await session.execute(select(Message.status))).scalars().all()
    assert all(s == MessageStatus.QUEUED for s in status)


async def test_o_bloqueio_vira_evento(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(6)])

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.chave == "5511999999999"
    assert linha.channel == "whatsapp"
    assert linha.limite == 3
    assert linha.volume == 4


async def test_numeros_diferentes_nao_compartilham_cota(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "2")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest(
        [_parsed(0, "5511111111111"), _parsed(1, "5522222222222")]
    )

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0


async def test_limite_zero_nao_conta_nada(
    session_factory, redis_pool, session, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "0")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(30)])

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0
```

Confira a fixture `caches_de_cliente_limpos` em `tests/conftest.py` antes de escrever o `monkeypatch.setenv` + `get_settings.cache_clear()`: se ela já limpar o cache no teardown, não repita a limpeza no fim dos testes.

Confira também a assinatura real de `ParsedMessage` (`src/mobia/domain/messages/schemas.py`) e de `MessageStatus` antes de rodar — se os campos divergirem do helper acima, ajuste o helper, não o dataclass.

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_ingestao_sob_rate_limit.py --tb=short
```

Esperado: FAIL — nenhum evento gravado, nenhum defer de backoff. O limitador ainda não está no caminho.

- [ ] **Step 3: Write the implementation**

Em `src/mobia/domain/messages/service.py`, acrescente aos imports:

```python
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_NUMERO
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_numero, consumir
```

E substitua o corpo do laço em `ingest`. Onde hoje está:

```python
        janela = get_settings().debounce_de_rajada_segundos
```

passa a ser:

```python
        settings = get_settings()
        janela = settings.debounce_de_rajada_segundos
        limite = settings.rate_limit_mensagens_por_minuto
        backoff = settings.atraso_de_backoff_segundos
```

Acrescente, junto de `texto_de`:

```python
        # O numero do lead por `provider_message_id`, pelo mesmo motivo e com a
        # mesma ressalva de `texto_de` acima: `gravadas` traz id interno e id
        # do provedor, nao o remetente.
        remetente_de = {item.provider_message_id: item.sender_external_id for item in parsed}
```

E o corpo do laço passa a ser:

```python
        for message_id, provider_message_id in gravadas:
            texto = texto_de.get(provider_message_id) or ""
            pediu = pediu_optout(texto) or pediu_humano(texto)

            # A cota e consumida por TODA mensagem, inclusive a que pede
            # opt-out ou humano. Contar so as demais deixaria quem inunda o
            # canal com "pare" fora de qualquer registro -- e a contagem aqui
            # e o que a tabela de eventos publica. O que o opt-out fura e o
            # ATRASO, nao a contagem: um limite de volume atrasar justamente o
            # pedido de parar de receber mensagens seria o contrario do que a
            # RN-14 promete.
            consumo = await consumir(
                self._queue,
                chave=chave_de_numero(channel, remetente_de.get(provider_message_id, "")),
                limite=limite,
                janela_segundos=JANELA_DE_UM_MINUTO,
            )

            if consumo.permitido:
                atraso = 0.0 if pediu else janela
            else:
                atraso = 0.0 if pediu else backoff
                log.warning(
                    "ratelimit.blocked",
                    escopo=ESCOPO_NUMERO,
                    conversation_key=remetente_de.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                )
                await registrar_bloqueio(
                    self._session_factory,
                    self._queue,
                    escopo=ESCOPO_NUMERO,
                    chave=remetente_de.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                    message_id=message_id,
                )

            await self._try_enqueue(message_id, atraso_segundos=atraso)
```

O comentário que hoje explica por que o opt-out não espera a janela continua válido e deve ser mantido acima do `pediu` — ele explica `pediu`, não a decisão de atraso. Releia-o depois da mudança: se ele afirmar algo que deixou de ser verdade (por exemplo, que o atraso só tem dois valores possíveis), corrija-o. Comentário desatualizado é defeito neste repo, não sujeira.

- [ ] **Step 4: Estender a invariante do sweeper**

Em `tests/integration/test_worker_startup.py`, no `test_job_timeout_cabe_dentro_da_janela_do_sweeper`, a asserção passa a ser:

```python
    settings = get_settings()
    # Desde a TEC-205 o atraso que antecede o job nem sempre e a janela de
    # debounce: o excedente do rate limit por numero e enfileirado com
    # `atraso_de_backoff_segundos` no lugar dela. Quem precisa caber e o MAIOR
    # dos dois, porque e ele que define o pior caso entre o carimbo de
    # `queued_at` (feito na ingestao, antes de qualquer espera) e o fim do
    # turno.
    espera_maxima_antes_do_job = max(
        settings.debounce_de_rajada_segundos,
        settings.atraso_de_backoff_segundos,
    )
    assert (
        espera_maxima_antes_do_job + WorkerSettings.job_timeout
        < settings.sweep_inflight_after_seconds
    )
```

E acrescente ao docstring do teste, ao fim:

```
    A TEC-205 acrescentou o terceiro candidato a espera: `atraso_de_backoff_segundos`
    (30s por default) substitui a janela de debounce no caminho do excedente do
    rate limit. Com os defaults de hoje a folga cai de 54s para 30s --
    max(6, 30) + 240 = 270 < 300. Subir o backoff sem olhar este teste reabre a
    conta.
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_ingestao_sob_rate_limit.py tests/integration/test_worker_startup.py tests/integration/test_ingestion_service.py tests/features/test_debounce_de_rajada.py --tb=short
```

Esperado: tudo verde. Os dois últimos arquivos entram porque tocam o mesmo laço — se algum reprovar, foi esta task que quebrou, não flake.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/service.py tests/integration/test_ingestao_sob_rate_limit.py tests/integration/test_worker_startup.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): o excedente por numero espera o backoff

A mensagem acima do limite e enfileirada com `atraso_de_backoff_segundos`
no lugar da janela de debounce -- persistida, QUEUED, sem LLM na hora e
sem erro para o lead. A cota e consumida por toda mensagem, inclusive a
que pede opt-out: o que o opt-out fura e o atraso, nao a contagem, senao
quem inunda o canal com "pare" fica fora de todo registro.

A invariante do sweeper ganha um terceiro candidato a espera e passa a
afirmar sobre o maior dos dois atrasos.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: De onde vem o IP, e como ele sai no log

**Files:**
- Create: `src/mobia/api/middleware.py` (só a função pura nesta task; o middleware vem na Task 7)
- Modify: `src/mobia/app/logging.py` (`_CHAVES_MASCARADAS`)
- Test: `tests/unit/test_resolucao_de_ip.py`
- Test: `tests/unit/test_logging_mascara.py` (acrescentar um caso)

**Interfaces:**
- Consumes: `Settings.confiar_em_forwarded_for` (Task 2).
- Produces: `def resolver_ip(*, socket_host: str | None, forwarded_for: str | None, confiar_em_forwarded_for: bool) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Crie `tests/unit/test_resolucao_de_ip.py`:

```python
"""De qual valor sai o IP que o limitador conta (TEC-205, D7)."""

from mobia.api.middleware import resolver_ip


def test_sem_confiar_usa_o_socket() -> None:
    assert (
        resolver_ip(
            socket_host="10.0.0.1",
            forwarded_for="203.0.113.7",
            confiar_em_forwarded_for=False,
        )
        == "10.0.0.1"
    )


def test_confiando_usa_o_ultimo_salto() -> None:
    """O ULTIMO, nao o primeiro: e o unico que o proxy imediato escreveu, e
    portanto o unico que o cliente nao controla. Confiar no primeiro deixaria
    qualquer um escapar do limite mandando um X-Forwarded-For forjado.
    """
    assert (
        resolver_ip(
            socket_host="10.0.0.1",
            forwarded_for="1.2.3.4, 5.6.7.8, 203.0.113.7",
            confiar_em_forwarded_for=True,
        )
        == "203.0.113.7"
    )


def test_confiando_sem_header_cai_no_socket() -> None:
    assert (
        resolver_ip(
            socket_host="10.0.0.1", forwarded_for=None, confiar_em_forwarded_for=True
        )
        == "10.0.0.1"
    )


def test_confiando_com_header_vazio_cai_no_socket() -> None:
    assert (
        resolver_ip(
            socket_host="10.0.0.1", forwarded_for="  ,  ", confiar_em_forwarded_for=True
        )
        == "10.0.0.1"
    )


def test_sem_socket_e_sem_header_devolve_none() -> None:
    """Cliente sem endereco existe -- ASGI de teste, socket unix. Quem chama
    trata None deixando passar (fail-open).
    """
    assert (
        resolver_ip(
            socket_host=None, forwarded_for=None, confiar_em_forwarded_for=False
        )
        is None
    )


def test_o_valor_e_truncado_para_caber_na_coluna() -> None:
    """`rate_limit_events.chave` e String(64), e o header e entrada externa:
    sem teto, um X-Forwarded-For longo viraria erro de INSERT na hora de
    registrar justamente o abuso.
    """
    longo = "x" * 500
    assert len(resolver_ip(
        socket_host=None, forwarded_for=longo, confiar_em_forwarded_for=True
    ) or "") <= 64
```

E acrescente a `tests/unit/test_logging_mascara.py`:

```python
def test_o_ip_sai_mascarado() -> None:
    """A corrida de digitos (`\\d{10,15}`) nao pega um IPv4 -- os pontos
    quebram a corrida --, entao sem a chave em `_CHAVES_MASCARADAS` o IP sairia
    em claro no log. A tabela de eventos guarda o valor inteiro; o log, que vai
    para agregador, nao.
    """
    assert "203.0.113.7" not in _mascarar_pii(None, "", {"ip": "203.0.113.7"})["ip"]
```

Confira como os testes vizinhos de `test_logging_mascara.py` chamam o processor — se eles usam um helper do próprio arquivo em vez de `_mascarar_pii` direto, use o helper.

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_resolucao_de_ip.py tests/unit/test_logging_mascara.py --tb=short
```

Esperado: `ModuleNotFoundError: No module named 'mobia.api.middleware'` e a asserção do IP falhando.

- [ ] **Step 3: Write the implementation**

Crie `src/mobia/api/middleware.py`:

```python
"""O limite de requisicoes por IP (TEC-205, RNF-16).

Primeiro middleware do projeto. Ate a TEC-205 `create_app` so fazia
`include_router`, e ate o `correlation_id` era setado dentro do handler.
"""

# `chave` em `rate_limit_events` e String(64). O header e entrada externa: sem
# teto, um `X-Forwarded-For` longo viraria erro de INSERT na hora de registrar
# justamente o abuso que a coluna existe para guardar.
_TAMANHO_MAXIMO_DA_CHAVE = 64


def resolver_ip(
    *,
    socket_host: str | None,
    forwarded_for: str | None,
    confiar_em_forwarded_for: bool,
) -> str | None:
    """O endereco que o limitador conta.

    Sem confiar (o default), e o socket: nao forjavel, correto no deploy de
    hoje, que nao tem proxy. Confiando, e o ULTIMO salto de `X-Forwarded-For`
    -- o ultimo, e nao o primeiro, porque e o unico que o proxy imediato
    escreveu e portanto o unico que o cliente nao controla. Confiar no
    primeiro deixaria qualquer cliente escapar do limite com um header
    forjado, que e exatamente o abuso que esta card existe para conter.

    Devolve None quando nao ha endereco nenhum. Quem chama deixa passar: e o
    mesmo fail-open do limitador.
    """
    if confiar_em_forwarded_for and forwarded_for:
        saltos = [salto.strip() for salto in forwarded_for.split(",")]
        ultimo = next((salto for salto in reversed(saltos) if salto), None)
        if ultimo:
            return ultimo[:_TAMANHO_MAXIMO_DA_CHAVE]
    if socket_host:
        return socket_host[:_TAMANHO_MAXIMO_DA_CHAVE]
    return None
```

Em `src/mobia/app/logging.py`, acrescente `"ip"` ao frozenset e explique no comentário que já está acima dele:

```python
# Identificador do interlocutor. Hoje e sempre telefone brasileiro e a corrida
# de digitos pega por acidente; o widget web do TEC-124 vai trazer id de sessao
# ou e-mail, que nao sao digitos. Mascarar pela chave torna a garantia
# estrutural em vez de dependente do formato do canal.
#
# `ip` (TEC-205) entra pelo mesmo argumento, e de forma ainda mais clara: a
# corrida de digitos NAO pega um IPv4, porque os pontos a quebram. A tabela
# `rate_limit_events` guarda o endereco inteiro, porque e ela que responde
# "quem foi" numa investigacao; o log, que vai para agregador e fica muito
# mais exposto, sai mascarado.
_CHAVES_MASCARADAS = frozenset(
    {"sender_external_id", "recipient_external_id", "conversation_key", "ip"}
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
```

Esperado: tudo verde, em ~5s, sem Docker.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/middleware.py src/mobia/app/logging.py tests/unit/test_resolucao_de_ip.py tests/unit/test_logging_mascara.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): o IP tem origem configuravel e sai mascarado no log

Sem confiar em X-Forwarded-For (o default), o IP e o do socket. Ligando a
confianca, e o ULTIMO salto: o primeiro e escrito pelo cliente e deixaria
qualquer um escapar do limite. A mascara de PII ganha `ip` porque a
corrida de digitos nao pega IPv4 -- os pontos a quebram.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: O middleware por IP

**Files:**
- Modify: `src/mobia/api/middleware.py` (a classe, abaixo da função da Task 6)
- Modify: `src/mobia/app/main.py` (`create_app`)
- Test: `tests/integration/test_middleware_de_rate_limit.py`

**Interfaces:**
- Consumes: `resolver_ip` (Task 6); `consumir`, `chave_de_ip`, `JANELA_DE_UM_MINUTO` (Task 1); `registrar_bloqueio` (Task 4); `ESCOPO_IP`, `CHANNEL_HTTP` (Task 3).
- Produces: `class RateLimitPorIP(BaseHTTPMiddleware)` e `ROTAS_ISENTAS: frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_middleware_de_rate_limit.py`:

```python
"""O limite de 100 req/min por IP, e de quem ele nao vale (TEC-205)."""

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.limites.models import ESCOPO_IP, RateLimitEvent


async def test_dentro_do_limite_passa(client, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "5")
    get_settings.cache_clear()

    for _ in range(5):
        assert (await client.get("/health")).status_code == 200


async def test_o_excedente_recebe_429_com_retry_after(client, monkeypatch) -> None:
    """429 aqui e seguro justamente porque o webhook da Meta esta isento."""
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "3")
    get_settings.cache_clear()

    for _ in range(3):
        await client.get("/docs")
    resposta = await client.get("/docs")

    assert resposta.status_code == 429
    assert resposta.headers["Retry-After"] == "60"


async def test_o_webhook_da_meta_nao_e_limitado(client, monkeypatch) -> None:
    """O trafego dali chega todo do IP da Meta: 100/min nao conteria abuso,
    derrubaria operacao -- e derrubaria com 429, que e nao-2xx e faria a Meta
    re-entregar, exatamente o retry que o desenho da TEC-122 evita.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(20):
        resposta = await client.post("/webhooks/whatsapp", content=b"{}")
        assert resposta.status_code != 429


async def test_health_nao_e_limitado(client, monkeypatch) -> None:
    """Probe de liveness batendo acima do limite receberia 429 e o orquestrador
    reiniciaria o processo -- o limitador derrubando o que devia proteger.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    for _ in range(10):
        assert (await client.get("/health")).status_code == 200


async def test_o_bloqueio_por_ip_vira_evento(client, session, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(6):
        await client.get("/docs")

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.escopo == ESCOPO_IP
    assert linha.limite == 2
    assert linha.volume == 3
    assert linha.message_id is None


async def test_limite_zero_desliga_o_middleware(client, session, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "0")
    get_settings.cache_clear()

    for _ in range(50):
        assert (await client.get("/docs")).status_code == 200
    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0
```

Dois avisos sobre estes testes, que valem antes de você os rodar:

O `test_health_nao_e_limitado` afirma a isenção do `/health`. Se você resolver **não** isentá-lo, apague o teste e registre a decisão — não o deixe passar mudando a asserção para `in (200, 429)`, que é uma asserção que não reprova nada.

A fixture `client` monta o app via `ASGITransport`, e **isso já basta**: o httpx usa `client=("127.0.0.1", 123)` por default, então `request.client.host` vale `"127.0.0.1"` e o limitador conta. **Não mexa na fixture `client`** — ela é compartilhada por todo o repo. Se os testes de 429 passarem com 200, procure o motivo no middleware, não na fixture.

Todos os testes dividem o mesmo IP `127.0.0.1`, e isso é inofensivo porque a fixture `redis_pool` faz `flushdb()` antes e depois de cada teste: cada um começa com a cota zerada.

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_middleware_de_rate_limit.py --tb=short
```

Esperado: FAIL nos de 429 (tudo devolve 200) — o middleware não existe.

- [ ] **Step 3: Write the middleware**

Acrescente a `src/mobia/api/middleware.py`:

```python
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mobia.app.config import get_settings
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import CHANNEL_HTTP, ESCOPO_IP
from mobia.infra.db import get_sessionmaker
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir

log = structlog.get_logger(__name__)

# Isentas, e cada uma por uma razao propria.
#
# `/webhooks/whatsapp`: o trafego chega todo do IP da Meta. Cem requisicoes por
# minuto ali nao conteria abuso, derrubaria operacao -- e derrubaria da pior
# forma, porque o handler responde 200 em todo caminho de rejeicao justamente
# para a Meta nao re-entregar. Um 429 e nao-2xx e provocaria o retry que o
# desenho da TEC-122 existe para evitar.
#
# `/health`: um probe de liveness que batesse acima do limite receberia 429 e
# o orquestrador reiniciaria o processo. O limitador derrubando exatamente o
# que ele deveria proteger.
ROTAS_ISENTAS = frozenset({"/webhooks/whatsapp", "/health"})


class RateLimitPorIP(BaseHTTPMiddleware):
    """Cem requisicoes por minuto por IP, fora as rotas isentas.

    Recusa com 429 em vez de adiar, ao contrario do limite por numero: aqui a
    requisicao e sincrona e nao ha o que adiar sem deixar o cliente pendurado.
    A assimetria esta registrada na emenda E-01 a RNF-16.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = get_settings()
        limite = settings.rate_limit_requisicoes_por_ip_por_minuto

        if limite <= 0 or request.url.path in ROTAS_ISENTAS:
            return await call_next(request)

        ip = resolver_ip(
            socket_host=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            confiar_em_forwarded_for=settings.confiar_em_forwarded_for,
        )
        if ip is None:
            return await call_next(request)

        pool = getattr(request.app.state, "redis_pool", None)
        consumo = await consumir(
            pool, chave=chave_de_ip(ip), limite=limite, janela_segundos=JANELA_DE_UM_MINUTO
        )
        if consumo.permitido:
            return await call_next(request)

        log.warning(
            "ratelimit.blocked",
            escopo=ESCOPO_IP,
            ip=ip,
            rota=request.url.path,
            volume=consumo.volume,
            limite=limite,
        )
        await registrar_bloqueio(
            get_sessionmaker(),
            pool,
            escopo=ESCOPO_IP,
            chave=ip,
            channel=CHANNEL_HTTP,
            volume=consumo.volume,
            limite=limite,
        )
        return Response(status_code=429, headers={"Retry-After": "60"})
```

Junte os imports novos aos que a Task 6 já pôs no topo do arquivo — não deixe dois blocos de import.

Em `src/mobia/app/main.py`, dentro de `create_app`, logo depois de `app = FastAPI(...)` e **antes** dos `include_router`:

```python
    # Primeiro middleware do projeto (TEC-205). Aplica-se por omissao e nao por
    # opt-in: uma lista de rotas incluidas erraria para o lado de esquecer o
    # widget do TEC-124, que e o erro caro. Quem precisa ficar de fora esta em
    # `ROTAS_ISENTAS`, com a razao de cada uma escrita la.
    app.add_middleware(RateLimitPorIP)
```

com o import correspondente no topo:

```python
from mobia.api.middleware import RateLimitPorIP
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_middleware_de_rate_limit.py tests/features/ --tb=short
```

Esperado: tudo verde. `tests/features/` entra porque todo cenário ali passa pela fixture `client` e agora atravessa o middleware — se algum arquivo de feature reprovar com 429, o limite está pegando um teste legítimo e a correção é o teste declarar o limite que quer, não o middleware abrir exceção.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/middleware.py src/mobia/app/main.py tests/integration/test_middleware_de_rate_limit.py
git commit -m "$(cat <<'EOF'
feat(TEC-205): cem requisicoes por minuto por IP, com duas isencoes

Primeiro middleware do projeto. Aplica-se por omissao e nao por opt-in,
para o widget do TEC-124 ja nascer coberto. Fora ficam o webhook da Meta,
cujo IP e compartilhado por todo o trafego de entrada e onde um 429
provocaria o retry que a TEC-122 evita, e o /health, onde um 429 faria o
orquestrador reiniciar o processo que o limitador deveria proteger.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Os quatro cenários do card

**Files:**
- Test: `tests/features/test_rate_limiting.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-7. Nada novo é produzido.

- [ ] **Step 1: Write the scenarios**

O padrão do diretório é pytest async puro com docstring Gherkin — não há `pytest-bdd` nem arquivo `.feature` no repo. Leia `tests/features/test_debounce_de_rajada.py` antes de escrever: é o vizinho mais próximo, e dele vem a forma de medir atraso por `score` do zset.

Crie `tests/features/test_rate_limiting.py`:

```python
"""Cenarios Gherkin de TEC-205.

Funcionalidade: Rate limiting e protecao contra abuso
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.limites.models import RateLimitEvent

NUMERO = "5511999999999"


def envelope(*wamids: str, texto: str = "oi") -> dict[str, Any]:
    """O envelope da Meta com uma mensagem por wamid.

    Copiado da forma usada em `tests/features/test_dedup_por_message_id.py`;
    confira la se o formato divergir.
    """
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "5511000000000"},
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": NUMERO,
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                                for wamid in wamids
                            ],
                        }
                    }
                ]
            }
        ]
    }


def assinado(payload: dict[str, Any], secret: str) -> tuple[bytes, dict[str, str]]:
    corpo = json.dumps(payload).encode()
    assinatura = hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()
    return corpo, {"X-Hub-Signature-256": f"sha256={assinatura}"}


async def _defers_ms(redis_pool) -> list[float]:
    agora_ms = datetime.now(UTC).timestamp() * 1000
    jobs = await redis_pool.zrange("arq:queue", 0, -1, withscores=True)
    return sorted(score - agora_ms for _, score in jobs)


async def test_numero_que_excede_o_limite_entra_em_backoff(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Numero que excede o limite entra em backoff."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "1")
    monkeypatch.setenv("ATRASO_DE_BACKOFF_SEGUNDOS", "25")
    get_settings.cache_clear()

    # Dado um numero que enviou 20 mensagens no ultimo minuto
    corpo, cabecalhos = assinado(
        envelope(*[f"wamid.b{i}" for i in range(20)]),
        get_settings().whatsapp_app_secret,
    )
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Quando ele envia a vigesima primeira
    corpo, cabecalhos = assinado(
        envelope("wamid.b20"), get_settings().whatsapp_app_secret
    )
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Entao a mensagem entra em backoff
    # E nenhum processamento de LLM e disparado por ela imediatamente
    defers = await _defers_ms(redis_pool)
    assert len(defers) == 21
    assert max(defers) > 20_000


async def test_ip_que_excede_o_limite_no_widget(client, monkeypatch) -> None:
    """Cenario: IP que excede o limite no widget.

    O widget web e o TEC-124 e ainda nao existe; o limite por IP vale para
    toda rota HTTP menos as de `ROTAS_ISENTAS`, entao o cenario e exercitado
    contra uma rota real. Quando o widget existir, ele ja nasce coberto pelo
    mesmo middleware -- ver D1 do desenho.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "100")
    get_settings.cache_clear()

    # Dado um IP com 100 requisicoes no ultimo minuto
    for _ in range(100):
        assert (await client.get("/docs")).status_code == 200

    # Quando ele faz a centesima primeira / Entao a requisicao e limitada
    assert (await client.get("/docs")).status_code == 429


async def test_lead_legitimo_nao_e_punido_com_erro(
    client, session, redis_pool, monkeypatch
) -> None:
    """Cenario: Lead legitimo nao e punido com erro.

    **Este cenario passa sem exercitar o limitador**, e isso esta registrado
    no comentario da card em vez de disfarcado: cinco mensagens estao muito
    abaixo de vinte, entao ele passaria identico se o rate limiting nao
    existisse. Quem exercita o backoff e o primeiro cenario deste arquivo.
    Mantido porque e o criterio de aceite escrito na card, e porque ele de
    fato prende uma regressao possivel -- a de alguem trocar o adiamento por
    recusa e o lead legitimo comecar a receber erro.
    """
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    get_settings.cache_clear()

    # Dado um lead que envia 5 mensagens rapidas em sequencia
    # Quando elas sao processadas
    for i in range(5):
        corpo, cabecalhos = assinado(
            envelope(f"wamid.l{i}"), get_settings().whatsapp_app_secret
        )
        resposta = await client.post(
            "/webhooks/whatsapp", content=corpo, headers=cabecalhos
        )
        # Entao nenhuma e rejeitada com erro
        assert resposta.status_code == 200

    assert (await session.execute(select(RateLimitEvent))).first() is None


async def test_bloqueio_vira_evento(client, session, redis_pool, monkeypatch) -> None:
    """Cenario: Bloqueio vira evento."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    get_settings.cache_clear()

    # Dado um numero bloqueado por rate limit
    corpo, cabecalhos = assinado(
        envelope(*[f"wamid.e{i}" for i in range(21)]),
        get_settings().whatsapp_app_secret,
    )
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Quando o evento e consultado
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()

    # Entao constam o numero, o momento e o volume que disparou o limite
    assert linha.chave == NUMERO
    assert linha.created_at is not None
    assert linha.volume == 21
    assert linha.limite == 20
```

- [ ] **Step 2: Run the scenarios**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_rate_limiting.py --tb=short
```

Esperado: 4 passed. Se `test_ip_que_excede_o_limite_no_widget` reprovar porque `/docs` não existe (o FastAPI pode ter a documentação desligada), troque a rota por `/openapi.json` ou por uma rota administrativa — mas **não** troque por `/health` nem pelo webhook, que estão isentos e fariam o cenário passar sem testar nada.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/features/test_rate_limiting.py
git commit -m "$(cat <<'EOF'
test(TEC-205): os quatro cenarios do card, ponta a ponta

O cenario do lead legitimo passa sem exercitar o limitador -- cinco
mensagens estao muito abaixo de vinte -- e o docstring dele diz isso em
vez de disfarcar. Inflar o teste ate fingir cobertura seria pior que a
lacuna registrada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: A emenda ao SRS e o fecho

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (item aninhado sob a RNF-16)
- Modify: `docs/superpowers/specs/2026-09-21-tec-205-rate-limiting-por-numero-e-por-ip-design.md` (`**Status:** implementado`)

**Interfaces:**
- Consumes: nada. Nada é produzido em código.

- [ ] **Step 1: Escrever a emenda**

Emendas ao SRS entram como item **aninhado** abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026. Localize a RNF-16 (busque por `Rate limiting e abuso`) e acrescente abaixo dela:

> **Emenda E-01 (TEC-205, 21/09/2026)** — o backoff é do excedente **por número**, que é adiado por `atraso_de_backoff_segundos` e processado depois. O excedente **por IP** recebe `429` com `Retry-After`, não backoff: ali a requisição é síncrona e não há o que adiar sem deixar o cliente pendurado. O webhook do WhatsApp fica **isento** do limite por IP — o IP da Meta é compartilhado por todo o tráfego de entrada, e limitá-lo não distingue abuso de operação; o `/health` fica isento pela mesma classe de razão, já que um 429 num probe de liveness derrubaria o processo. O limite por IP se aplica a toda rota HTTP restante, inclusive antes de o widget do TEC-124 existir.

- [ ] **Step 2: Marcar a spec como implementada**

Troque `**Status:** desenhado` por `**Status:** implementado` no cabeçalho da spec.

- [ ] **Step 3: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Ela não é gate e não reprova nada — devolve a uma pessoa o julgamento de se cada comentário continua verdadeiro. Preste atenção especial a `VIZINHO` em `src/mobia/domain/messages/service.py` (o laço de `ingest` mudou por baixo de comentários que ninguém editou) e em `src/mobia/app/main.py`, e a `PROSA`/`FALSO` em documentos que citem `service.py:linha` ou `main.py:linha` — a Task 5 e a Task 7 deslocaram as linhas dos dois. Corrija o que ficou falso no mesmo commit.

- [ ] **Step 4: A suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta; guarde o hash junto com o resultado. Se ela **falhar**, a segunda execução sobre a mesma árvore é o que separa flake de regressão — rode-a antes de culpar a sua mudança. Se voltar com centenas de `ERROR` de setup, não repita o mesmo `-n`: rode por blocos (`tests/unit`, `tests/integration`, `tests/features`), como descrito em CLAUDE.md.

- [ ] **Step 5: Commit e push**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add docs/
git commit -m "$(cat <<'EOF'
docs(TEC-205): a RNF-16 diz de quem e o backoff e quem fica isento

A regra original dizia "excedente entra em backoff" sem dizer de quem. A
emenda E-01 separa: por numero e adiamento, por IP e 429, e nomeia as
duas rotas isentas com a razao de cada uma.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin feat/tec-205-rate-limiting-por-numero-e-por-ip
```

- [ ] **Step 6: Abrir o PR e fechar o ciclo da card**

Trabalho de card termina em `git push` e PR — não em merge local, e não numa pergunta sobre o que fazer com a branch.

```bash
gh pr create --base main --title "TEC-205: rate limiting por numero e por IP" --body "..."
```

O corpo do PR termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

Depois, comente na card e mova-a para **Em análise** (não para "Feito" — quem mergeia é que fecha). O comentário precisa registrar o que some se ficar só no PR:

- **Divergências em relação ao texto da card:** o limite por IP não pôde ser aplicado "no widget web", porque o widget é o TEC-124 e não existe; foi aplicado a toda rota HTTP menos o webhook da Meta e o `/health`, e o widget nasce coberto.
- **Critério de aceite não exercitado:** "Lead legítimo não é punido com erro" passa sem tocar o limitador — 5 mensagens contra um limite de 20.
- **Lacuna que é decisão de produto:** "configurável sem deploy" foi entregue como variável de ambiente; alterar em runtime é o épico RF-19. E a cota é consumida também pela mensagem de opt-out, que fura o atraso mas não a contagem.
- **O que a card não entrega:** nada notifica ninguém quando um bloqueio acontece — a linha em `rate_limit_events` é consultável, e só. Não há alerta, dashboard nem varredura sobre ela.
- **A emenda E-01 à RNF-16**, nomeada.

---

## Self-Review

**Cobertura da spec, seção por seção:**

| Seção da spec | Task |
| --- | --- |
| D1 — middleware por IP, webhook isento | 7 |
| D2 — backoff fixo, invariante com quarto termo | 5 (o laço) e 5 Step 4 (a invariante) |
| D3 — ZSET, relógio por parâmetro | 1 |
| D4 — fail-open | 1 (`consumir`), 4 (`_ganhou_a_guarda`), 7 (`ip is None`) |
| D5 — tabela e guarda de janela | 3 (tabela) e 4 (guarda) |
| D6 — quatro campos, lacuna do RF-19 | 2 |
| D7 — origem do IP | 6 |
| D8 — máscara no log | 6 |
| Fluxo por número | 5 |
| Fluxo por IP | 7 |
| Testes | 1, 3, 4, 5, 6, 7, 8 |
| Emenda ao SRS | 9 |

**Consistência de tipos entre tasks:** `Consumo.volume` é `int` em todas as chamadas; `chave_de_numero(channel, conversation_key)` recebe dois argumentos na Task 1 e é chamada com dois na Task 5; `registrar_bloqueio` tem `message_id` opcional na Task 4 e é chamada sem ele na Task 7; `resolver_ip` devolve `str | None` na Task 6 e a Task 7 trata o `None`.

**O que este plano deliberadamente não tem:** teste unitário do `consumir` com dublê de Redis (provaria o dublê), aplicação do limite por IP a uma rota do widget (não existe), e qualquer leitura de configuração fora do processo (RF-19).
