# TEC-280 — A notificação ao corretor sai por SMTP: plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam caixa (`- [ ]`) para controle.

**Objetivo:** fazer a notificação de handoff chegar ao corretor por e-mail de verdade, substituindo o `EmailRegistrado`, que só escreve `notificacao.nao_entregue` no log.

**Arquitetura:** um adaptador novo em `domain/outbound/email.py` implementa a porta `CanalDeNotificacaoPort` que já existe, fala SMTP via `aiosmtplib` e levanta `FalhaDeCanal` — que o orquestrador de `domain/notificacao/envio.py` já sabe tratar. O ponto de composição é literal e único: a tupla em `workers/main.py`. Uma guarda incondicional em `startup()` recusa subir o worker sem configuração de SMTP, no molde da guarda de `WHATSAPP_ACCESS_TOKEN` que está logo acima dela.

**Tecnologias:** Python 3.13, `aiosmtplib` (dependência principal, nova), `aiosmtpd` (dependência de dev, nova, só para o servidor de teste), `pydantic-settings`, Mailpit no `docker-compose`.

**Desenho:** [`docs/superpowers/specs/2026-09-19-tec-280-email-ao-corretor-por-smtp-design.md`](../specs/2026-09-19-tec-280-email-ao-corretor-por-smtp-design.md)

## Restrições globais

- Comentários e docstrings em `src/`, `tests/`, `scripts/`: português **sem** acento (exceto valor citado). Prosa em `docs/`, `README.md` e `CLAUDE.md`: **com** acento.
- **Texto que uma pessoa recebe vai com acento.** O corpo do e-mail carrega o resumo escrito pelo modelo, que vem acentuado — nada pode normalizar ou estropiar isso.
- Os três gates, no escopo exato do CI, antes de cada commit: `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`.
- Commit: `tipo(TEC-280): o que passou a ser verdade`, assunto em português sem acento, **linha em branco** antes do trailer.
- **O `corpo` NUNCA vai para log**, em lugar nenhum, em nenhum nível. `destino` e `assunto` podem.
- Dependência nova no `pyproject.toml` entra com piso `>=` **e um comentário dizendo por que aquele piso** — é a convenção do arquivo.
- Nenhum campo de credencial vira `SecretStr`: o repo não usa em lugar nenhum e esta card não muda essa convenção.

---

### Tarefa 1: A configuração, a guarda de partida e o Mailpit

**Arquivos:**
- Modificar: `src/mobia/app/config.py` (campos novos)
- Modificar: `src/mobia/workers/main.py` (guarda em `startup`)
- Modificar: `.env.example`, `docker-compose.yml`
- Testar: `tests/integration/test_worker_startup.py`

**Interfaces:**
- Consome: `ConfiguracaoInsegura` (`src/mobia/app/config.py`), `get_settings()`.
- Produz: os campos `smtp_host`, `smtp_porta`, `smtp_usuario`, `smtp_senha`, `smtp_remetente`, `smtp_starttls` em `Settings` — a Tarefa 2 lê todos.

- [ ] **Passo 1: escrever os testes que falham**

Em `tests/integration/test_worker_startup.py`, no estilo dos dois testes que já existem ali (leia-os antes: eles mostram como o ambiente é montado e como `startup` é chamado). Dois testes:

```python
async def test_o_worker_nao_sobe_sem_host_de_smtp(monkeypatch) -> None:
    """Sem SMTP, a notificacao volta a ser descartada em silencio.

    Mesma razao da guarda de WHATSAPP_ACCESS_TOKEN logo acima dela: o defeito
    nao e a entrega falhar, e ninguem ficar sabendo que ela falhou.
    """
    # ... monte o ambiente como os testes vizinhos montam, com SMTP_HOST vazio
    with pytest.raises(ConfiguracaoInsegura, match="SMTP_HOST"):
        await startup({})


async def test_o_worker_nao_sobe_sem_remetente(monkeypatch) -> None:
    """Host sem remetente nao entrega: o provedor recusa envelope sem MAIL FROM."""
    # ... mesmo ambiente, com SMTP_HOST preenchido e SMTP_REMETENTE vazio
    with pytest.raises(ConfiguracaoInsegura, match="SMTP_REMETENTE"):
        await startup({})
```

Copie do teste vizinho de `WHATSAPP_ACCESS_TOKEN` a forma exata de montar o ambiente e de chamar `startup` — **não invente uma forma nova**. O molde é `monkeypatch.setenv(...)` mais a fixture `caches_de_cliente_limpos`, que zera o `@lru_cache` de `get_settings`. Preencha `WHATSAPP_ACCESS_TOKEN` como ele preenche, senão a guarda que dispara é a dele e o teste passa pelo motivo errado.

**E consertar o que esta guarda quebra, que é parte desta tarefa.** Os dois testes de caminho feliz do mesmo arquivo — `test_startup_sobe_com_token_configurado` e o equivalente da guarda de `OPENAI_API_KEY` (as chamadas `await startup(ctx)` nas linhas 38 e 93) — passam a reprovar, porque a guarda nova dispara antes de eles chegarem à asserção.

Conserte-os com `monkeypatch.setenv` das variáveis de SMTP, e **não** confiando no `.env` da máquina:

```python
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
```

O `.env` é local e não versionado; um teste que dependesse dele passaria aqui e reprovaria no CI, que não tem arquivo nenhum. `await startup` só existe nesses quatro pontos — conferido por `grep -rn "await startup" tests/` —, então não há outro lugar para consertar.

- [ ] **Passo 2: rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_worker_startup.py -k "smtp or remetente" --tb=short
```

Esperado: FAIL — nenhuma guarda de SMTP existe ainda, então `startup` não levanta (ou levanta a guarda errada).

- [ ] **Passo 3: os campos em `Settings`**

Em `src/mobia/app/config.py`, junto dos outros campos de integração externa, no molde de `whatsapp_access_token`:

```python
    # SMTP da notificacao ao corretor (TEC-280). Provedor NENHUM esta escolhido:
    # a decisao de 19/09/2026 foi falar SMTP direto justamente para que SES,
    # Resend ou Postmark fiquem sendo configuracao e nao codigo -- a escolha de
    # vendor pode esperar a TEC-219, que decide a nuvem.
    #
    # `smtp_host` e `smtp_remetente` nascem vazios de proposito. Um default
    # como "localhost" faria o worker subir em qualquer lugar e so falhar na
    # hora de entregar, que e o descarte em silencio que esta card existe para
    # matar. Quem reprova e a guarda do `startup`.
    smtp_host: str = ""
    smtp_porta: int = 587
    smtp_usuario: str = ""
    smtp_senha: str = ""
    smtp_remetente: str = ""
    # Ligado por padrao: o caso inseguro tem de ser o escolhido a mao. O
    # Mailpit de desenvolvimento nao fala TLS, e o `.env.example` o desliga.
    smtp_starttls: bool = True
```

- [ ] **Passo 4: a guarda em `startup`**

Em `src/mobia/workers/main.py`, **logo depois** da guarda de `OPENAI_API_KEY` e **antes** de `session_factory = get_sessionmaker()`:

```python
    # TEC-280. Incondicional, como a de WHATSAPP_ACCESS_TOKEN e nao como a de
    # OPENAI_API_KEY acima, que so recusa em producao: condicionar ao ambiente
    # deixaria a maquina de quem desenvolve convivendo com o defeito que esta
    # card existe para matar. Notificacao descartada em silencio nao e menos
    # defeito por acontecer em dev -- e so menos visivel, que e pior.
    #
    # O remetente entra na mesma guarda porque host sem remetente nao entrega:
    # o servidor recusa o envelope sem MAIL FROM, e a falha apareceria so na
    # primeira notificacao, que e tarde.
    if not settings.smtp_host or not settings.smtp_remetente:
        raise ConfiguracaoInsegura(
            "SMTP_HOST ou SMTP_REMETENTE nao configurado. Sem os dois a "
            "notificacao de handoff nao chega ao corretor, e o lead fica "
            "esperando sem que ninguem saiba. Suba o Mailpit do "
            "docker-compose e defina os dois no .env antes de subir o worker."
        )
```

- [ ] **Passo 5: o Mailpit no compose**

Em `docker-compose.yml`, um serviço novo, com healthcheck no padrão dos dois que já existem:

```yaml
  mailpit:
    # So de desenvolvimento: captura o e-mail em vez de entregar, e serve uma
    # interface em 8025 para ler o que teria saido. Existe porque a guarda de
    # SMTP no worker e incondicional (TEC-280, D2) -- sem um servidor de pe,
    # o worker nao sobe nem aqui.
    image: axllent/mailpit:latest
    ports:
      - "1025:1025"
      - "8025:8025"
    healthcheck:
      test: ["CMD", "/mailpit", "readyz"]
      interval: 2s
      timeout: 3s
      retries: 20
```

- [ ] **Passo 6: o `.env.example`**

Acrescentar no fim, seguindo o estilo comentado do arquivo:

```
# SMTP da notificacao ao corretor (TEC-280). Obrigatorios: sem os dois
# primeiros o worker recusa subir, em qualquer ambiente. Estes valores apontam
# para o Mailpit do docker-compose, que captura e nao entrega.
SMTP_HOST=localhost
SMTP_PORTA=1025
SMTP_REMETENTE=mobia@localhost
SMTP_STARTTLS=false
SMTP_USUARIO=
SMTP_SENHA=
```

- [ ] **Passo 7: rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_worker_startup.py --tb=short
```

Esperado: os dois novos passam e os dois que já existiam continuam passando.

- [ ] **Passo 8: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 9: commit**

```bash
git add src/mobia/app/config.py src/mobia/workers/main.py .env.example docker-compose.yml tests/integration/test_worker_startup.py
git commit -m "feat(TEC-280): o worker recusa subir sem SMTP configurado"
```

---

### Tarefa 2: O adaptador que fala SMTP

**Arquivos:**
- Criar: `src/mobia/domain/outbound/email.py`
- Modificar: `pyproject.toml` (duas dependências novas)
- Testar: `tests/integration/test_email_smtp.py` (novo)

**Interfaces:**
- Consome: `CanalDeNotificacaoPort` e `FalhaDeCanal` (`src/mobia/domain/notificacao/canais.py`), os campos `smtp_*` da Tarefa 1, `get_settings()`.
- Produz: `class EmailSmtp` com `nome = "email"` e `async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None`. A Tarefa 3 a instancia.

- [ ] **Passo 1: as dependências**

Em `pyproject.toml`, na lista principal `dependencies`, com comentário como as vizinhas têm:

```toml
    # SMTP assincrono para a notificacao ao corretor (TEC-280). Piso em 3.0
    # porque e a serie que aceita `start_tls` como argumento de `send`; nas
    # 2.x a negociacao exigia montar o cliente a mao.
    "aiosmtplib>=3.0",
```

E em `[project.optional-dependencies] dev`:

```toml
    # Servidor SMTP em processo para os testes do adaptador (TEC-280). O repo
    # finge a BORDA DE REDE e nao a funcao -- mesmo raciocinio do
    # httpx.MockTransport usado no adaptador de WhatsApp.
    "aiosmtpd>=1.4",
```

Instalar: `./.venv/Scripts/python.exe -m pip install "aiosmtplib>=3.0" "aiosmtpd>=1.4"`

- [ ] **Passo 2: escrever os testes que falham**

`tests/integration/test_email_smtp.py`. Fica em `tests/integration/` e não em `tests/unit/` porque abre soquete — mesma escolha que pôs os testes do adaptador de WhatsApp lá.

O servidor de teste, com `aiosmtpd`, numa porta efêmera, guardando o que chegou:

```python
"""O adaptador de e-mail, contra um servidor SMTP de verdade em processo.

Servidor real e nao monkeypatch de `aiosmtplib.send`: um monkeypatch prova que
chamamos uma funcao com certos argumentos, e este teste precisa provar que a
MENSAGEM chega -- com o endereco certo e com o corpo inteiro. E' tambem a
unica forma de pegar acento estropiado no transporte, que e defeito de
codificacao e nao de chamada. Ver a D7 do desenho.
"""

import asyncio
import email
import logging
from email.message import Message

import pytest
from aiosmtpd.controller import Controller

from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.outbound.email import EmailSmtp

RESUMO = "## Quem e o lead\nPaulo procura apartamento no Condominio Acacia, orcamento ate R$ 450 mil."


class _Caixa:
    """Guarda o que o servidor recebeu, para o teste ler depois."""

    def __init__(self) -> None:
        self.recebidas: list[Message] = []
        self.destinatarios: list[str] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.destinatarios.extend(envelope.rcpt_tos)
        self.recebidas.append(email.message_from_bytes(envelope.content))
        return "250 OK"


@pytest.fixture
def servidor():
    caixa = _Caixa()
    controlador = Controller(caixa, hostname="127.0.0.1", port=0)
    controlador.start()
    yield controlador, caixa
    controlador.stop()
```

Os testes:

```python
async def test_a_mensagem_chega_com_destino_resumo_e_link(servidor, monkeypatch) -> None:
    controlador, caixa = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)

    await canal.enviar(
        destino="paulo@imobiliaria.com.br",
        assunto="Lead pronto [quente] prioridade alta",
        corpo=f"{RESUMO}\n\nConversa completa: https://exemplo/conversas/whatsapp/5511",
    )

    assert caixa.destinatarios == ["paulo@imobiliaria.com.br"]
    (mensagem,) = caixa.recebidas
    texto = mensagem.get_payload(decode=True).decode("utf-8")
    assert "Condominio Acacia" in texto
    assert "https://exemplo/conversas/whatsapp/5511" in texto


async def test_o_acento_sobrevive_ao_transporte(servidor, monkeypatch) -> None:
    """O resumo vem do modelo e vem acentuado. E' o teste que paga a D7.

    Montar cabecalho a mao em vez de usar `EmailMessage` passa neste teste so
    por acaso; quebra com assunto acentuado e com corpo longo, que o
    quoted-printable parte em linhas.
    """
    controlador, caixa = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)
    corpo = "O lead procura no Condomínio Acácia, três dormitórios, até R$ 450 mil."

    await canal.enviar(destino="p@x.com", assunto="Lead pronto [morno] prioridade média", corpo=corpo)

    (mensagem,) = caixa.recebidas
    assert mensagem.get_payload(decode=True).decode("utf-8").strip() == corpo
    assert "média" in str(email.header.make_header(email.header.decode_header(mensagem["Subject"])))


async def test_servidor_indisponivel_vira_falha_de_canal(monkeypatch) -> None:
    """Porta fechada: o adaptador traduz para a excecao que o orquestrador trata."""
    canal = _canal_em("127.0.0.1", 1, monkeypatch)  # porta 1: recusa conexao

    with pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="p@x.com", assunto="a", corpo="b")


async def test_defeito_de_programacao_sobe(servidor, monkeypatch) -> None:
    """A D5, travada: `except Exception` aqui reintroduz o problema que
    `FalhaDeCanal` existe para resolver -- o handoff sairia como pendente de
    aviso manual por causa de um bug que ninguem veria."""
    controlador, _ = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)

    async def explode(*args, **kwargs):
        raise TypeError("defeito de programacao")

    monkeypatch.setattr("mobia.domain.outbound.email.aiosmtplib.send", explode)

    with pytest.raises(TypeError):
        await canal.enviar(destino="p@x.com", assunto="a", corpo="b")


async def test_o_log_nunca_carrega_o_corpo(servidor, monkeypatch, caplog) -> None:
    controlador, _ = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)
    sentinela = "SENTINELA-CORPO o lead mora na Rua das Palmeiras"

    with caplog.at_level(logging.DEBUG):
        await canal.enviar(destino="p@x.com", assunto="a", corpo=sentinela)

    assert sentinela not in caplog.text
```

Os dois auxiliares, no mecanismo que o repo já usa para trocar configuração em teste — `monkeypatch.setenv` mais o `cache_clear()` do `@lru_cache` de `get_settings`:

```python
def _canal_em(host: str, porta: int, monkeypatch: pytest.MonkeyPatch) -> EmailSmtp:
    """Um adaptador apontado para este endereco, sem TLS e sem autenticacao.

    Via variavel de ambiente e `cache_clear()` porque `get_settings` e
    `@lru_cache`: e' assim que o resto da suite troca configuracao, e um
    caminho proprio aqui divergiria do que a aplicacao de fato le.
    """
    monkeypatch.setenv("SMTP_HOST", host)
    monkeypatch.setenv("SMTP_PORTA", str(porta))
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("SMTP_USUARIO", "")
    monkeypatch.setenv("SMTP_SENHA", "")
    get_settings.cache_clear()
    return EmailSmtp()


def _canal_apontando_para(controlador: Controller, monkeypatch: pytest.MonkeyPatch) -> EmailSmtp:
    return _canal_em(controlador.hostname, controlador.port, monkeypatch)
```

Importe `get_settings` de `mobia.app.config`. Use a fixture `caches_de_cliente_limpos` nos testes, como `test_worker_startup.py` usa, para o cache não vazar para o teste seguinte.

`controlador.port` é resolvido depois do `start()` — com `port=0` o sistema escolhe uma porta livre, e é por isso que a fixture só entrega o controlador já iniciado.

- [ ] **Passo 3: rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_email_smtp.py --tb=short
```

Esperado: `ModuleNotFoundError: mobia.domain.outbound.email`.

- [ ] **Passo 4: o adaptador**

`src/mobia/domain/outbound/email.py`:

```python
"""O canal de e-mail que entrega de verdade. TEC-280, RN-16.2.

SMTP direto e nao API de provedor: a escolha de 19/09/2026 foi deliberada, e a
razao esta na TEC-219, que ainda nao decidiu a nuvem. Falando SMTP, trocar
para SES, Resend ou Postmark e mexer em variavel de ambiente e nao em codigo.

Substitui o `EmailRegistrado`, que so escrevia `notificacao.nao_entregue`
desde a TEC-177. Aquele adaptador foi APAGADO junto com esta card, e nao
mantido como alternativa: deixa-lo disponivel preservaria o caminho de volta
para o descarte em silencio.
"""

import asyncio
from email.message import EmailMessage

import aiosmtplib
import structlog

from mobia.app.config import get_settings
from mobia.domain.notificacao.canais import FalhaDeCanal

log = structlog.get_logger(__name__)

# Teto por entrega. Sem ele um servidor pendurado segura o job do ARQ pelo
# tempo que quiser, e a fila para atras dele.
SEGUNDOS_DE_TIMEOUT = 15.0


class EmailSmtp:
    """Entrega a notificacao por SMTP. Uma tentativa, sem retentativa."""

    nome = "email"

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        configuracao = get_settings()

        # `EmailMessage` e nao concatenacao de cabecalho: o corpo vem do
        # modelo e vem acentuado, e e' aqui que se escolhe entre UTF-8 bem
        # declarado e mojibake na caixa do corretor.
        mensagem = EmailMessage()
        mensagem["From"] = configuracao.smtp_remetente
        mensagem["To"] = destino
        mensagem["Subject"] = assunto
        mensagem.set_content(corpo, charset="utf-8")

        try:
            await aiosmtplib.send(
                mensagem,
                hostname=configuracao.smtp_host,
                port=configuracao.smtp_porta,
                username=configuracao.smtp_usuario or None,
                password=configuracao.smtp_senha or None,
                start_tls=configuracao.smtp_starttls,
                timeout=SEGUNDOS_DE_TIMEOUT,
            )
        # NAO e `except Exception`. A docstring de `FalhaDeCanal` diz por que:
        # engolir TypeError e AttributeError faria o handoff sair marcado como
        # pendente de aviso manual por causa de um defeito de programacao, que
        # ninguem veria. Aqui a lista e explicita -- recusa do servidor, erro
        # de rede e estouro de tempo --, e o resto sobe.
        except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError) as erro:
            # **Nunca loga `corpo`**: ele carrega o resumo, pela mesma razao
            # que `handoffs.resumo` e cifrado em repouso.
            log.warning("notificacao.email_recusado", destino=destino, assunto=assunto)
            raise FalhaDeCanal(f"SMTP recusou a mensagem: {type(erro).__name__}") from erro

        log.info("notificacao.email_entregue", destino=destino, assunto=assunto)
```

Note que `asyncio.TimeoutError` é `TimeoutError` desde o 3.11 — mantenha os dois nomes fora da tupla se o `ruff` reclamar de redundância, e deixe só `TimeoutError`.

- [ ] **Passo 5: rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_email_smtp.py --tb=short
```

- [ ] **Passo 6: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 7: commit**

```bash
git add pyproject.toml src/mobia/domain/outbound/email.py tests/integration/test_email_smtp.py
git commit -m "feat(TEC-280): o adaptador de e-mail fala SMTP e levanta FalhaDeCanal"
```

---

### Tarefa 3: Plugar no worker e apagar o `EmailRegistrado`

**Arquivos:**
- Modificar: `src/mobia/workers/main.py` (a tupla de composição e o import)
- Modificar: `src/mobia/domain/notificacao/canais.py` (remover `EmailRegistrado`)
- Modificar: `tests/unit/test_notificacao_canais.py`

**Interfaces:**
- Consome: `EmailSmtp` da Tarefa 2.
- Produz: nada que tarefa seguinte consuma.

- [ ] **Passo 1: trocar a composição**

Em `src/mobia/workers/main.py`, a linha `ctx["canais_de_notificacao"] = (EmailRegistrado(), WhatsAppRegistrado())` passa a `(EmailSmtp(), WhatsAppRegistrado())`, com o import ajustado.

O comentário logo acima dela hoje diz **"Os dois adaptadores de `canais.py` REGISTRAM e nao entregam"** — isso passa a ser falso. Texto novo:

```python
    # O de e-mail entrega (TEC-280); o de WhatsApp ainda REGISTRA e nao
    # entrega, porque depende de template aprovado pela Meta -- ver o docstring
    # de `canais.py`. E' o `startup` que decide a implementacao, no mesmo
    # raciocinio de `outbound`/`redator`/etc acima; o teste troca a chave sem
    # tocar no job.
```

- [ ] **Passo 2: apagar o `EmailRegistrado`**

Em `src/mobia/domain/notificacao/canais.py`, remover a classe `EmailRegistrado` inteira. `_CanalQueRegistra` e `WhatsAppRegistrado` ficam — aquele canal continua sem entregar, e a base segue justificada por ele.

- [ ] **Passo 3: ajustar os testes que parametrizavam os dois**

`tests/unit/test_notificacao_canais.py` tem três testes que fazem `@pytest.mark.parametrize("canal", [EmailRegistrado(), WhatsAppRegistrado()])`. Passam a parametrizar só `WhatsAppRegistrado()`, e o import de `EmailRegistrado` sai.

**Não apague nenhum dos três testes:** o que eles provam sobre o canal que sobrou continua valendo, e o de `test_o_log_nunca_carrega_o_corpo` é justamente a garantia que não pode enfraquecer.

- [ ] **Passo 4: rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_notificacao_canais.py tests/integration/test_worker_startup.py tests/integration/test_email_smtp.py --tb=short
```

Rode também uma busca por referências órfãs, que reprovaria o import:

```bash
grep -rn "EmailRegistrado" src tests scripts
```

Esperado: nenhuma ocorrência em `src/` nem em `tests/`. Ocorrência em `docs/` é registro histórico e fica.

- [ ] **Passo 5: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 6: commit**

```bash
git add src/mobia/workers/main.py src/mobia/domain/notificacao/canais.py tests/unit/test_notificacao_canais.py
git commit -m "feat(TEC-280): o worker passa a compor o canal de e-mail que entrega"
```

---

### Tarefa 4: A prosa para de dizer que nada chega a ninguém

**Arquivos:**
- Modificar: `src/mobia/domain/notificacao/canais.py` (docstring de módulo)
- Modificar: `src/mobia/domain/notificacao/mensagem.py` (comentário de `TEXTO_SEM_RESUMO`)
- Modificar: `src/mobia/domain/notificacao/envio.py` (o bloco que descreve o estado)

**Interfaces:** nenhuma. Esta tarefa é só prosa; **não mude uma linha de código executável.**

- [ ] **Passo 1: `canais.py`**

A docstring de módulo hoje abre com *"Os canais da RN-16.2 -- e a razao de nenhum deles entregar ainda"* e afirma em negrito que **os dois** adaptadores registram e não entregam, com um parágrafo explicando que o e-mail não tem infraestrutura e que escolher provedor foi adiado em 12/09/2026.

Reescreva para o que é verdade hoje, sem acento:

- O título deixa de dizer que nenhum entrega.
- O parágrafo do e-mail sai e é substituído por uma frase dizendo que desde a TEC-280 o e-mail entrega, por SMTP, e que o adaptador vive em `domain/outbound/email.py`.
- **O parágrafo do WhatsApp fica intacto** — a Meta, o código 131047 e a janela de 24h continuam sendo verdade, e a TEC-281 é a card aberta disso.
- A frase final sobre "uma forma so para os dois" continua valendo e fica: a porta ainda é uma só, e é por isso que o orquestrador trata os dois igual.

- [ ] **Passo 2: `mensagem.py`**

O comentário de `TEXTO_SEM_RESUMO` termina hoje com:

```
# O link que este texto manda abrir nao resolve ainda: `link_da_transcricao`
# (`handoff/resumo.py`) documenta em negrito que o destino e a E8, que nao
# existe. Sem dano hoje -- nenhum canal entrega nada a corretor nenhum (D4) --
# mas o dia em que um adaptador real existir, a E8 tem de existir junto.
```

**"Sem dano hoje" virou falso, e o "dia" chegou.** Texto novo (sem acento):

```
# O link que este texto manda abrir nao resolve: `link_da_transcricao`
# (`handoff/resumo.py`) documenta em negrito que o destino e a E8, que nao
# existe. Desde a TEC-280 o e-mail CHEGA ao corretor, entao o dano deixou de
# ser hipotetico: ele recebe "Conversa completa: <link>" e o link nao abre
# nada. A card decidiu entregar assim mesmo -- corretor avisado com link
# quebrado ainda atende o lead, corretor nao avisado nao --, e registrou a
# lacuna. Ela fecha quando a E8 existir.
```

- [ ] **Passo 3: `envio.py`**

Leia o bloco de comentário perto do topo do módulo (o levantamento apontou as linhas 44-53) e confira se ele afirma que nenhum canal entrega. Se afirmar, corrija pela mesma régua dos dois acima: o de e-mail entrega, o de WhatsApp não.

Se ele **não** afirmar isso, não invente mudança — registre no relatório que o bloco já estava correto e siga.

- [ ] **Passo 4: rodar a listagem de comentários**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Leia cada achado e confirme que a prosa bate com o código — inclusive as docstrings de módulo, que desde a TEC-283 aparecem como `VIZINHO`. Se algum achado revelar prosa errada que este plano não previu, conserte e registre no relatório.

- [ ] **Passo 5: os três gates e os testes tocados**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
```

- [ ] **Passo 6: commit**

```bash
git add src/mobia/domain/notificacao/
git commit -m "docs(TEC-280): a prosa para de dizer que nenhum canal entrega"
```

---

### Tarefa 5: A suíte inteira, uma vez, e o PR

**Arquivos:** nenhum.

- [ ] **Passo 1: subir o Mailpit**

```bash
docker compose up -d mailpit
docker compose ps
```

Os testes de `tests/integration/test_email_smtp.py` sobem servidor próprio e **não** dependem do Mailpit; ele é para o worker de desenvolvimento. Mas confira que o serviço novo sobe, porque o `docker-compose.yml` faz parte da entrega.

- [ ] **Passo 2: a suíte inteira, uma execução**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando**: é o Postgres sob paralelismo, e a cura é rodar por blocos (`tests/unit`, `tests/integration`, `tests/features`).

Se falhar num teste, repita **uma** vez sobre a mesma árvore antes de culpar esta branch.

- [ ] **Passo 3: push e PR**

```bash
git push -u origin feat/tec-280-email-ao-corretor-por-smtp
```

Se o push voltar 403, é o credential manager respondendo antes do `gh`; refaça com `git -c credential.helper= -c credential.helper='!gh auth git-credential' push ...`.

- [ ] **Passo 4: a card**

Comentar na TEC-280 e mover para "Em análise". O comentário registra:

- **A decisão de produto que destravou a card**, e o argumento que não estava nela: a TEC-219 continua aberta, então SMTP mantém a escolha de vendor como configuração.
- **A lacuna de produto:** o corretor recebe um e-mail cujo link não resolve, porque a E8 não existe. Melhor que o estado de hoje, pior que a RN-16.2 promete.
- **O que a card não entrega:** a TEC-281 (WhatsApp ao corretor) segue aberta, e o `WhatsAppRegistrado` continua registrando sem entregar.
- **O custo assumido da D2:** a guarda incondicional significa que ninguém sobe o worker sem Mailpit ou SMTP real — inclusive em desenvolvimento.
