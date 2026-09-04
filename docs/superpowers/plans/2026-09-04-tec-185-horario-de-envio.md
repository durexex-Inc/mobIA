# TEC-185 — Janela de horário de envio automático: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nenhum envio automático sai fora de 9h–20h no fuso configurado, e o disparo recusado é adiado para a próxima abertura sem consumir a tentativa da cadência.

**Architecture:** Um predicado puro (`horario_permite_envio`) em `domain/outbound/`, aplicado como porteiro no topo de `sweep_followups` antes de qualquer consulta. O adiamento não é código: fora da janela nada é gravado, `ja_disparada` não se move, e a próxima varredura reencontra a mesma tentativa devida pela aritmética da cadência derivada da TEC-183. A janela vive em `Settings`, com validação que falha na construção.

**Tech Stack:** Python 3.13, `zoneinfo` + `tzdata`, pydantic-settings, SQLAlchemy async, ARQ, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-tec-185-horario-de-envio-design.md` — leia antes de começar. As decisões são numeradas D1–D10 e as tarefas abaixo citam essas siglas.

## Global Constraints

- **Os três gates estáticos, nesta ordem, antes de todo commit.** O formatador é gate separado do linter, e passar num não diz nada sobre o outro:
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m mypy`
- **Escopo do ruff é `src tests alembic evals`**, não `src tests`. O mypy segue só em `src`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento. Convenção do repo, não checada por linter nenhum.
- **Comentário não mente.** Se você mudar código que um comentário descreve, o comentário muda junto ou some. A Task 4 existe por causa dessa regra.
- **Nunca use a palavra "janela" para nomear código novo.** O repo já a usa para a janela de contexto (`domain/context/janela.py`), a de 24h da Meta (`EnvioForaDaJanela`) e a de drenagem do worker (`job_completion_wait`). Código novo usa `horario`. A prosa de `docs/` continua dizendo "janela", que é o termo do negócio. Ver D3.
- **Basenames de teste não colidem entre `tests/unit/` e `tests/integration/`.** Colisão aborta a coleta da suíte inteira, não aparece no arquivo isolado, e já custou duas cards (`a3d1840`, `424ed72`). `test_janela.py` já existe em `unit` — o nome novo é `test_horario_de_envio.py`.
- **Piso da dependência:** `tzdata>=2026.1` em `[project] dependencies` (não no extra `dev`). Ver D7.
- **A janela é inclusiva nas duas pontas, na granularidade do minuto.** `fim=20` autoriza 20:00 e recusa 20:01. Ver D5.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-185): o que passou a ser verdade`.
- **A suíte é lenta (~7,5 min).** Rode arquivos-alvo durante as tarefas; a suíte inteira só na verificação final da Task 4.

---

### Task 1: A janela em `Settings`, e a configuração que falha alto

Primeira porque as Tasks 2 e 3 importam `ZoneInfo("America/Sao_Paulo")` nos testes, e **sem `tzdata` isso levanta `ZoneInfoNotFoundError` no Windows** (medido: `zoneinfo` usa a base do sistema operacional, e o Windows não tem uma).

**Files:**
- Modify: `pyproject.toml` (lista `dependencies`)
- Modify: `src/mobia/app/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Settings.followup_horario_inicio: int` (default 9), `Settings.followup_horario_fim: int` (default 20), `Settings.followup_fuso: str` (default `"America/Sao_Paulo"`), `Settings.fuso_de_envio -> ZoneInfo`.

- [ ] **Step 1: Instalar `tzdata` e provar que o fuso resolve**

Acrescente a linha em `pyproject.toml`, na lista `dependencies` (logo depois de `"httpx>=0.28",`):

```toml
    "tzdata>=2026.1",
```

Instale e confirme:

```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/Sao_Paulo'))"
```

Esperado: imprime `ZoneInfo(key='America/Sao_Paulo')`. Antes desta instalação o mesmo comando levanta `ZoneInfoNotFoundError`.

- [ ] **Step 2: Escrever os testes que falham**

Em `tests/unit/test_config.py`, acrescente `from pydantic import ValidationError` aos imports e estes quatro testes ao fim do arquivo:

```python
def test_o_horario_de_envio_invertido_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Horario invertido desligaria a cadencia sem nenhum sintoma.

    A varredura devolveria 0 para sempre, e a ausencia de `followup.devido` e
    indistinguivel de "nenhum lead devido" -- exatamente a falha silenciosa que
    este repo trata como pior que a alta.
    """
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "20")
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "9")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_horario_de_envio_vazio_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """9-9 nao e um horario de um instante: e a cadencia desligada."""
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "9")
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "9")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_fuso_de_envio_invalido_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem esta guarda, o typo explodiria dentro da varredura a cada 5 minutos
    em vez de na subida do worker."""
    monkeypatch.setenv("FOLLOWUP_FUSO", "America/Sao_Paolo")

    with pytest.raises(ValidationError, match="followup_fuso"):
        Settings(_env_file=None)


def test_o_fuso_de_envio_default_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guarda do tzdata: sem a dependencia isto levanta no Windows, onde o
    `zoneinfo` nao tem base de fusos do sistema. Passaria no Linux do CI e
    falharia na maquina de quem desenvolve."""
    monkeypatch.delenv("FOLLOWUP_HORARIO_INICIO", raising=False)
    monkeypatch.delenv("FOLLOWUP_HORARIO_FIM", raising=False)
    monkeypatch.delenv("FOLLOWUP_FUSO", raising=False)

    settings = Settings(_env_file=None)

    assert settings.fuso_de_envio.key == "America/Sao_Paulo"
    assert settings.followup_horario_inicio == 9
    assert settings.followup_horario_fim == 20
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -k "janela_de_envio or fuso_de_envio" -v
```

Esperado: os quatro FALHAM. Os três primeiros porque `Settings` aceita qualquer valor (nenhum `ValidationError` é levantado), o quarto com `AttributeError: 'Settings' object has no attribute 'fuso_de_envio'`.

- [ ] **Step 4: Implementar os campos, o validator e a property**

Em `src/mobia/app/config.py`, acrescente ao topo do arquivo:

```python
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
```

Acrescente os campos logo depois de `sweep_max_attempts: int = 5`:

```python
    # RN-13.3 (TEC-185): o horario de envio automatico, em horas locais do
    # `followup_fuso`. `fim` nomeia o ultimo MINUTO em que um envio pode
    # comecar -- `fim=20` autoriza 20:00 e recusa 20:01 --, e nao a ultima hora
    # inteira. A borda inclusiva nao e escolha estetica: os dois primeiros
    # criterios de aceite da card caem exatamente em 20:00, porque um lead que
    # parou de falar as 18h vence a primeira tentativa do QUENTE (+2h) as 20h
    # em ponto.
    followup_horario_inicio: int = 9
    followup_horario_fim: int = 20

    # Fuso UNICO da POC (PR-04), e nao o fuso do lead: a deteccao pelo numero
    # esta declarada fora do escopo da TEC-185. Nome e nao offset de proposito
    # -- o Brasil aboliu o horario de verao em 2019, e gravar `-3` faria a
    # volta dele virar um erro silencioso de uma hora em todo disparo.
    followup_fuso: str = "America/Sao_Paulo"
```

Acrescente o validator logo depois de `_recusar_chave_de_desenvolvimento_em_producao`:

```python
    @model_validator(mode="after")
    def _recusar_horario_de_envio_impossivel(self) -> "Settings":
        """Horario invertido ou vazio desligaria a cadencia em silencio.

        A varredura devolveria 0 para sempre, e o unico sintoma seria a
        ausencia de `followup.devido` -- indistinguivel de "nenhum lead
        devido". Um `followup_fuso` invalido, sem esta guarda, explodiria
        dentro da varredura a cada 5 minutos em vez de aqui.

        `ValueError` e nao `ConfiguracaoInsegura`: o docstring daquela excecao
        fala de configuracao que roda "sem a protecao que devia ter", e o caso
        dela e a chave de cifra de desenvolvimento em producao. Um horario
        invertido nao perde protecao -- ele deixa de operar. O pydantic
        embrulha este ValueError em ValidationError, que falha igualmente alto
        e em todo processo.
        """
        if not 0 <= self.followup_horario_inicio < self.followup_horario_fim <= 23:
            raise ValueError(
                "followup_horario_inicio e followup_horario_fim precisam satisfazer "
                f"0 <= inicio < fim <= 23; recebi inicio={self.followup_horario_inicio} "
                f"e fim={self.followup_horario_fim}. Horario invertido ou vazio desliga "
                "a cadencia de follow-up sem nenhum sintoma."
            )
        try:
            ZoneInfo(self.followup_fuso)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"followup_fuso={self.followup_fuso!r} nao e um fuso conhecido. "
                "Se o nome estiver certo, confira a dependencia `tzdata` no "
                "pyproject.toml -- o Windows nao tem base de fusos do sistema."
            ) from exc
        return self
```

Acrescente a property logo antes de `teto_de_tokens_efetivo`:

```python
    @property
    def fuso_de_envio(self) -> ZoneInfo:
        """O fuso do horario da RN-13.3, ja validado na construcao.

        Construido a cada acesso em vez de guardado: o `ZoneInfo` e cacheado
        pelo proprio modulo `zoneinfo`, e um atributo aqui teria de ser
        excluido do modelo do pydantic.
        """
        return ZoneInfo(self.followup_fuso)
```

- [ ] **Step 5: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -v
```

Esperado: PASS, incluindo os testes que já existiam no arquivo.

- [ ] **Step 6: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

Esperado: os três limpos. Se o `format --check` reclamar, rode `./.venv/Scripts/python.exe -m ruff format src tests alembic evals` e confira o diff antes de commitar.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/mobia/app/config.py tests/unit/test_config.py
git commit -F - <<'EOF'
feat(TEC-185): a janela de envio passa a ser configuravel e a recusar o impossivel

`followup_horario_inicio`, `followup_horario_fim` e `followup_fuso` em
Settings, com validator que recusa janela invertida ou vazia e fuso
desconhecido na construcao -- em vez de a varredura devolver 0 para
sempre e a ausencia de `followup.devido` parecer "nenhum lead devido".

`tzdata` entra em dependencies e nao no extra dev: o `zoneinfo` usa a base
do sistema operacional, o Windows nao tem uma, e sem a dependencia o fuso
resolveria no Linux do CI e levantaria na maquina de quem desenvolve.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: O predicado puro `horario_permite_envio`

**Files:**
- Create: `src/mobia/domain/outbound/horario.py`
- Test: `tests/unit/test_horario_de_envio.py`

**Interfaces:**
- Consumes: nada de Task 1 em código; depende de `tzdata` estar instalado (Step 1 da Task 1) para os testes rodarem.
- Produces: `horario_permite_envio(*, momento: datetime, inicio: int, fim: int, fuso: ZoneInfo) -> bool`. Levanta `ValueError` se `momento.tzinfo is None`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_horario_de_envio.py`:

```python
"""A janela de horario de envio automatico. TEC-185, RN-13.3.

O nome do arquivo e `horario` e nao `janela` de proposito: `test_janela.py`
ja existe neste diretorio e pertence a janela de CONTEXTO. Colisao de
basename entre unit e integration aborta a coleta da suite inteira.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.outbound.horario import horario_permite_envio

FUSO = ZoneInfo("America/Sao_Paulo")


def _local(hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Um instante aware de 04/09/2026, dado em hora LOCAL de Sao Paulo."""
    return datetime(2026, 9, 4, hora, minuto, segundo, tzinfo=FUSO)


def _permite(momento: datetime) -> bool:
    """A janela default da card: 9h as 20h."""
    return horario_permite_envio(momento=momento, inicio=9, fim=20, fuso=FUSO)


def test_o_meio_da_tarde_permite() -> None:
    assert _permite(_local(14, 30)) is True


def test_antes_das_nove_recusa() -> None:
    assert _permite(_local(8, 59)) is False


def test_a_madrugada_recusa() -> None:
    """A historia da card, literal: "nao quero receber mensagem da imobiliaria
    as tres da manha"."""
    assert _permite(_local(3)) is False


def test_as_nove_em_ponto_permite() -> None:
    """A borda de baixo e inclusiva: o criterio de aceite do adiamento manda o
    follow-up "as 9h do dia seguinte"."""
    assert _permite(_local(9, 0)) is True


def test_as_vinte_em_ponto_permite() -> None:
    """Os dois primeiros criterios de aceite da card sao esta mesma borda: um
    lead QUENTE que parou de falar as 18h vence a primeira tentativa (+2h) as
    20h em ponto, e "um disparo agendado para exatamente 20h" e enviado."""
    assert _permite(_local(20, 0)) is True


def test_as_vinte_com_tres_segundos_permite() -> None:
    """A regressao que separa "passa no teste" de "funciona no cron".

    O cron dispara em `minute={0, 5, ...}`, mas `agora` e lido DENTRO do job --
    na pratica 20:00:00,04. Com uma comparacao de `time` cheio esse sweep
    ficaria FORA da janela, e este teste seria o unico a notar: o da borda
    exata passaria, e producao falharia o criterio de aceite.
    """
    assert _permite(_local(20, 0, 3)) is True


def test_as_vinte_e_cinco_recusa() -> None:
    """O outro lado da mesma truncagem: os segundos morrem, o minuto nao."""
    assert _permite(_local(20, 5)) is False


def test_o_momento_ingenuo_levanta() -> None:
    """Um naive faz `astimezone` assumir o fuso do SISTEMA -- UTC-3 nesta
    maquina, UTC no runner do CI --, e o erro seria invisivel em um dos dois."""
    with pytest.raises(ValueError, match="tzinfo"):
        horario_permite_envio(
            momento=datetime(2026, 9, 4, 14, 0), inicio=9, fim=20, fuso=FUSO
        )


def test_a_conversao_de_fuso_acontece_de_verdade() -> None:
    """23h UTC e 20h em Sao Paulo (dentro); 00h UTC e 21h (fora).

    E o teste que morre se alguem ler `momento.hour` direto em vez de
    converter -- pelo relogio UTC as duas respostas se invertem.
    """
    assert _permite(datetime(2026, 9, 4, 23, 0, tzinfo=UTC)) is True
    assert _permite(datetime(2026, 9, 5, 0, 0, tzinfo=UTC)) is False


def test_a_janela_configurada_e_lida() -> None:
    """Os parametros nao sao decorativos: uma janela de madrugada permite as 3h
    e recusa as 14h, invertendo as duas respostas do default."""
    assert horario_permite_envio(momento=_local(3), inicio=0, fim=5, fuso=FUSO) is True
    assert horario_permite_envio(momento=_local(14), inicio=0, fim=5, fuso=FUSO) is False
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_horario_de_envio.py -v
```

Esperado: erro de coleta — `ModuleNotFoundError: No module named 'mobia.domain.outbound.horario'`.

- [ ] **Step 3: Implementar o módulo**

Crie `src/mobia/domain/outbound/horario.py`:

```python
"""O horario em que um envio automatico pode sair. TEC-185, RN-13.3.

Pura de proposito, no molde de `cadencia.py`, `score.py` e `temperatura.py`:
sem I/O, sem banco, sem chamada ao modelo. Quem decide disparar e a
varredura; aqui so se responde "o relogio permite agora?".

**Mora em `outbound/` e nao em `followup/`** porque a regra da card cobre todo
envio automatico -- follow-up, lembrete de agendamento (TEC-171) e
reengajamento (TEC-172). Sob `followup/` a proxima card nao acharia esta
funcao e escreveria a segunda, que e a forma exata do defeito de duas fontes
que a TEC-146 gastou uma card inteira consertando.

**E NAO mora em `GuardedOutbound.send`**, que seria a escolha tentadora: e la
que a guarda de opt-out vive, e o comentario dela diz que quem HERDA daquela
classe "ganha a guarda de graca". Mas aquele caminho carrega a resposta ao
lead -- `executar_turno` envia por ali --, e um lead que escreve as 3h da
manha tem de ser respondido as 3h da manha. A card fala de envio AUTOMATICO,
nao de todo envio; a janela na porta compartilhada silenciaria o produto
treze horas por dia. A guarda pertence aos sitios que ORIGINAM automacao.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def horario_permite_envio(*, momento: datetime, inicio: int, fim: int, fuso: ZoneInfo) -> bool:
    """Se um envio automatico pode comecar em `momento`. RN-13.3.

    `inicio` e `fim` sao horas locais no `fuso`, e a janela e inclusiva nas
    duas pontas: `fim=20` autoriza 20:00 e recusa 20:01.

    **A borda inclusiva vem dos criterios de aceite, e os dois primeiros sao a
    mesma borda.** "Um lead QUENTE que parou de responder as 18h ... o
    follow-up e enviado as 20h" cai exatamente em 20:00, porque a primeira
    tentativa do QUENTE e +2h; e "um disparo agendado para exatamente 20h ... a
    mensagem e enviada" diz o mesmo em outras palavras. Uma comparacao
    exclusiva quebraria os dois.

    **Os segundos sao descartados, e isso e o oposto de desleixo.** O cron
    dispara em `minute={0, 5, 10, ...}`, mas `agora` e lido DENTRO do job -- na
    pratica 20:00:00,04. Comparando `time` cheio, esse sweep ficaria FORA da
    janela, e um teste unitario com um `datetime` exato passaria enquanto
    producao falhava o criterio de aceite. Truncando ao minuto, a varredura das
    20:00 entra e a das 20:05 nao.

    **`momento` ingenuo levanta, e a razao e o CI.** `astimezone()` num naive
    nao erra: ele assume o fuso do SISTEMA. A maquina de desenvolvimento deste
    projeto esta em UTC-3 e o runner do GitHub Actions esta em UTC, entao um
    naive daria resultados divergentes nos dois -- e como o `followup_fuso`
    default coincide com o da maquina local, o bug seria invisivel ali e
    apareceria so no CI. Mesma classe de armadilha que o `pythonpath` do
    pyproject.toml documenta, com os papeis trocados.

    Tudo keyword-only: `inicio` e `fim` sao dois `int` adjacentes, e troca-los
    inverte a janela sem levantar, sem erro de tipo e sem o mypy ver. Mesma
    razao dos dois `datetime` de `tentativa_devida` e dos dois flags de
    `temperatura_de`.
    """
    if momento.tzinfo is None:
        raise ValueError(
            "momento sem tzinfo: `astimezone` assumiria o fuso do sistema, que "
            "difere entre esta maquina (UTC-3) e o runner do CI (UTC), e o erro "
            "ficaria invisivel em um dos dois. Passe um datetime aware."
        )
    local = momento.astimezone(fuso)
    minuto_do_dia = local.hour * 60 + local.minute
    return inicio * 60 <= minuto_do_dia <= fim * 60
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_horario_de_envio.py -v
```

Esperado: 10 PASS.

- [ ] **Step 5: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/outbound/horario.py tests/unit/test_horario_de_envio.py
git commit -F - <<'EOF'
feat(TEC-185): o relogio passa a poder recusar um envio automatico

`horario_permite_envio` e pura e mora em outbound/, porque a regra cobre
follow-up, lembrete e reengajamento -- sob followup/ a TEC-171 nao a
acharia e escreveria a segunda.

A borda das 20h e inclusiva no MINUTO, nao no instante: o cron dispara em
minute={0,5,...} mas `agora` e lido dentro do job, entao 20:00:00,04
ficaria fora de uma comparacao exata e os dois primeiros criterios de
aceite falhariam em producao com o teste da borda passando.

Momento ingenuo levanta: `astimezone` num naive assume o fuso do sistema,
UTC-3 aqui e UTC no runner, e a divergencia seria invisivel em um dos dois.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: O porteiro na varredura, e a suíte que para de depender do relógio

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py`
- Test: `tests/integration/test_sweep_followups.py`

**Interfaces:**
- Consumes: `horario_permite_envio` (Task 2); `Settings.followup_horario_inicio`, `Settings.followup_horario_fim`, `Settings.fuso_de_envio` (Task 1).
- Produces: `sweep_followups(ctx: dict[str, Any], limite: int = 500, *, agora: datetime | None = None) -> int`. `agora=None` significa `datetime.now(UTC)`; produção não passa o parâmetro.

- [ ] **Step 1: Tornar os testes existentes determinísticos**

Isto vem antes dos testes novos, e é a D10. Os sete testes do arquivo chamam `sweep_followups(_ctx())` e assumem que a varredura roda; com o porteiro, um CI que rodasse às 23h de São Paulo reprovaria os sete. Configurar uma janela "sempre aberta" não resolve: com a borda da D5, `inicio=0, fim=23` recusa 23:01–23:59, e uma suíte que reprova cinquenta e nove minutos por dia parece flake.

Em `tests/integration/test_sweep_followups.py`, acrescente aos imports:

```python
from zoneinfo import ZoneInfo

from mobia.app.config import Settings
```

Acrescente logo depois de `CONVERSA = "5511944443333"`:

```python
FUSO = ZoneInfo("America/Sao_Paulo")

# Todo teste deste arquivo fixa `agora`. Com a guarda de horario da TEC-185 a
# varredura depende da hora do dia, e sem fixar o momento a suite inteira desta
# card passaria ou reprovaria conforme a hora em que o CI rodasse. Nao da para
# resolver com uma janela "sempre aberta": a borda e inclusiva no minuto, entao
# `inicio=0, fim=23` recusa 23:01-23:59.
DENTRO_DA_JANELA = datetime(2026, 9, 4, 14, 0, tzinfo=FUSO).astimezone(UTC)
FORA_DA_JANELA = datetime(2026, 9, 4, 3, 0, tzinfo=FUSO).astimezone(UTC)
```

Troque as duas funções auxiliares por estas:

```python
async def _lead(
    session,
    *,
    temperatura: str | None = "QUENTE",
    calado_ha: timedelta,
    agora: datetime = DENTRO_DA_JANELA,
) -> None:
    """Um lead com temperatura e uma fala de entrada com a idade pedida.

    `agora` e a referencia da idade, e nao `datetime.now()`: a varredura
    tambem recebe um momento fixo, e os dois tem de concordar.
    """
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=agora - calado_ha,
        )
    )
    await session.commit()


def _ctx() -> dict:
    """A janela default da card (9h-20h) explicita, e nao herdada do ambiente.

    Sem o `Settings` aqui, o job cairia em `get_settings()`, que le o `.env` da
    maquina -- e um `.env` com a janela mexida faria a suite mentir.
    """
    return {
        "session_factory": get_sessionmaker(),
        "settings": Settings(_env_file=None, followup_horario_inicio=9, followup_horario_fim=20),
    }
```

Agora acrescente `agora=DENTRO_DA_JANELA` a **todas** as chamadas de `sweep_followups` dos sete testes existentes. Exemplo do primeiro:

```python
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)
```

E no `test_a_varredura_absorve_a_corrida_entre_duas_passagens`, troque a linha da âncora e a do stub para usarem o momento fixo:

```python
    ancora = DENTRO_DA_JANELA - timedelta(hours=2, minutes=5)
```

```python
    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0
```

- [ ] **Step 2: Escrever os três testes novos**

Ao fim de `tests/integration/test_sweep_followups.py`:

```python
async def test_a_madrugada_nao_dispara_nada(session, caplog) -> None:
    """A guarda da TEC-185, ponta a ponta: mesmo lead, mesma divida, outra hora.

    As duas assertivas existem porque devolver 0 sem gravar e gravar sem contar
    sao falhas diferentes, e um `return 0` no lugar errado passaria com uma so.
    """
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5), agora=FORA_DA_JANELA)

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=FORA_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_o_adiamento_nao_consome_a_tentativa(session) -> None:
    """O criterio de aceite inteiro do adiamento, em tres momentos.

    "Parou de responder as 19h30 ... nada e enviado as 21h30 ... o follow-up e
    enviado as 9h do dia seguinte ... ele conta como a primeira tentativa."

    Nao existe codigo de adiamento: fora da janela nada e gravado,
    `ja_disparada` continua zero, e a varredura das 9h reencontra a MESMA
    tentativa 1 pela aritmetica. E o teste que morre se alguem tentar
    implementar o adiamento com estado -- uma linha PENDENTE, uma coluna
    `adiado_para` -- em vez de deixar a ancora responder.
    """
    parou = datetime(2026, 9, 4, 19, 30, tzinfo=FUSO)
    await _lead(session, calado_ha=timedelta(0), agora=parou.astimezone(UTC))

    tarde_da_noite = (parou + timedelta(hours=2)).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=tarde_da_noite) == 0
    assert (await session.scalars(select(FollowUp))).all() == []

    manha_seguinte = datetime(2026, 9, 5, 9, 0, tzinfo=FUSO).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=manha_seguinte) == 1

    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [1]


async def test_as_vinte_em_ponto_ainda_disparam(session) -> None:
    """A CA-13.1 e a borda das 20h no mesmo teste: um lead QUENTE que parou de
    falar as 18h vence a primeira tentativa (+2h) exatamente as 20h.

    A borda sobrevive nas duas pontas do caminho, e as duas sao inclusivas de
    proposito: o corte da consulta e `HAVING MAX(created_at) <= :corte` e a
    regua compara com `>=`. Trocar qualquer uma por estrita faz este teste
    reprovar por um instante.
    """
    parou = datetime(2026, 9, 4, 18, 0, tzinfo=FUSO)
    await _lead(session, calado_ha=timedelta(0), agora=parou.astimezone(UTC))

    vinte_em_ponto = (parou + timedelta(hours=2)).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=vinte_em_ponto) == 1
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v
```

Esperado: os sete existentes FALHAM com `TypeError: sweep_followups() got an unexpected keyword argument 'agora'`, e os três novos também. Se o banco reprovar com `ConnectionResetError [WinError 64]`, **espere e retente** — o container demora mais que o healthcheck diz, e isso não é defeito de código.

- [ ] **Step 4: Implementar o porteiro e o parâmetro**

Em `src/mobia/workers/jobs/sweep_followups.py`, troque os imports:

```python
from mobia.app.config import Settings, get_settings
from mobia.domain.followup.cadencia import CADENCIA, tentativa_devida
from mobia.domain.followup.repositorio import candidatos_a_followup, registrar_followup
from mobia.domain.optout.repositorio import esta_em_optout
from mobia.domain.outbound.horario import horario_permite_envio
```

Troque a assinatura:

```python
async def sweep_followups(
    ctx: dict[str, Any], limite: int = 500, *, agora: datetime | None = None
) -> int:
```

Acrescente ao fim do docstring da função, antes do fechamento:

```
    **A guarda de horario (TEC-185, RN-13.3) roda antes da consulta, e e a
    unica das tres que roda antes.** Sob fuso unico (PR-04) a janela e
    propriedade de `agora` e nao do candidato, entao nada do que a consulta
    trouxesse mudaria a resposta -- e o `GROUP BY` sobre `messages` e a parte
    cara desta varredura. Por treze das vinte e quatro horas o job nao toca o
    banco.

    **Quando o fuso virar por lead, esta chamada desce para dentro do laco**,
    ao lado de `esta_em_optout`, e a funcao pura nao muda: ela ja recebe o
    fuso por parametro. Nao reescreva o predicado achando que ele e global por
    natureza.

    **Nao ha codigo de adiamento, e nao falta nenhum.** A card pede que o
    disparo fora da janela seja "adiado para a proxima abertura, nao
    descartado" e que "o adiamento nao consuma a tentativa". Como nada e
    gravado quando a janela recusa, `ja_disparada` -- que e o MAX sob a ancora
    -- nao se move, e a proxima varredura dentro da janela reencontra a mesma
    tentativa devida. As duas regras sao consequencia da cadencia derivada, e
    nao implementacao.

    **`agora` entra por parametro pela razao que `candidatos_a_followup` ja
    escreveu para a consulta**: sem isso nenhum teste consegue posicionar o
    relogio. Com a guarda de horario isso deixou de ser conveniencia -- sem o
    parametro, a suite inteira desta varredura passaria ou reprovaria conforme
    a hora do dia em que o CI rodasse. Producao nao passa o argumento.
```

Troque o começo do corpo:

```python
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    if agora is None:
        agora = datetime.now(UTC)
    eventos: list[dict[str, Any]] = []

    if not horario_permite_envio(
        momento=agora,
        inicio=settings.followup_horario_inicio,
        fim=settings.followup_horario_fim,
        fuso=settings.fuso_de_envio,
    ):
        return 0
```

- [ ] **Step 5: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v
```

Esperado: 10 PASS. Se algum falhar com `ConnectionResetError` ou erro de Redis, **rode o arquivo sozinho de novo** antes de atribuir a falha a esta mudança — estes testes flakeiam sob carga e passam 100% isolados.

- [ ] **Step 6: Rodar os vizinhos que tocam a mesma varredura**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py tests/integration/test_worker_startup.py tests/unit/test_cadencia.py -v
```

Esperado: PASS. Nenhum deles chama `sweep_followups`, mas os três cobrem a cadência e a subida do worker, que é onde uma regressão desta task apareceria.

- [ ] **Step 7: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 8: Commit**

```bash
git add src/mobia/workers/jobs/sweep_followups.py tests/integration/test_sweep_followups.py
git commit -F - <<'EOF'
feat(TEC-185): a varredura passa a calar fora da janela, sem perder a tentativa

O porteiro roda antes da consulta, e nao por candidato: sob fuso unico a
janela e propriedade de `agora`, e o GROUP BY sobre messages e a parte cara
da varredura. Treze das vinte e quatro horas o job nao toca o banco.

O adiamento nao tem codigo: fora da janela nada e gravado, `ja_disparada`
nao se move, e a varredura seguinte reencontra a mesma tentativa. As duas
regras da card caem da cadencia derivada.

`sweep_followups` passa a receber `agora`, pela razao que
`candidatos_a_followup` ja escreveu para a consulta -- e agora obrigatoria:
sem o parametro, os sete testes desta varredura passariam ou reprovariam
conforme a hora do dia em que o CI rodasse.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: A emenda ao SRS, e os comentários que pararam de valer

Esta task não é housekeeping: a regra do repo é que comentário desatualizado é defeito, e a TEC-183 deixou três afirmações que esta card torna falsas ou incompletas.

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (linha 18 da tabela de emendas; linha 323, a RN-13.3)
- Modify: `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md` (a lacuna 3)

**Interfaces:**
- Consumes: nada.
- Produces: nada em código.

- [ ] **Step 1: A linha na tabela de emendas do SRS**

A tabela está ordenada por **data**, então a linha nova vai depois da da TEC-183 (linha 18). Acrescente:

```markdown
> | E-01 | RN-13.3 | [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) | 04/09/2026 |
```

- [ ] **Step 2: A emenda aninhada sob a RN-13.3**

A RN-13.3 está na linha 323. Insira **imediatamente depois dela** (a numeração é por regra — há várias `E-01` no documento, uma por regra):

```markdown
  - **Emenda E-01 (TEC-185, 04/09/2026):** a janela é **guarda de disparo, e não ajuste de agendamento**. `devido_em` continua sendo a hora da aritmética da RN-13.1 — `ancora_em` mais o intervalo da tentativa — e pode cair fora da janela, inclusive de madrugada; o que a janela impede é o disparo naquele instante. O efeito observável da regra é o descrito: nenhum envio automático fora de 9h–20h, e o disparo recusado é adiado para a próxima abertura sem consumir a tentativa, porque na cadência derivada nada é gravado quando a janela recusa e `ja_disparada` não se move. **Consequência declarada:** a afirmação do modelo de dados da seção 5 de que `agendado_para` está *"já ajustado à janela da RN-13.3"* não vale para `devido_em` — a Emenda E-01 da RN-13.4 já havia renomeado a coluna e apontado para esta card, e esta fecha o ponto escolhendo **não** ajustar, porque `created_at` já registra a hora do disparo real e ajustar `devido_em` gravaria a mesma informação duas vezes, apagando o atraso. A janela vale para todo envio automático, mas hoje só existe um sítio de automação (a varredura da cadência); lembrete de visita e reengajamento a herdarão quando existirem (TEC-171, TEC-172).
```

- [ ] **Step 3: Corrigir a lacuna 3 do desenho da TEC-183**

Em `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md`, o item 3 das "Lacunas declaradas" diz hoje:

> 3. **O `devido_em` não respeita a janela de 9h–20h**, ao contrário do que o modelo de dados do SRS afirma sobre `agendado_para` (*"já ajustado à janela da RN-13.3"*). É a TEC-185, e até lá o horário calculado pode cair de madrugada.

Troque por:

```markdown
3. **O `devido_em` não respeita a janela de 9h–20h**, ao contrário do que o modelo de dados do SRS afirma sobre `agendado_para` (*"já ajustado à janela da RN-13.3"*). **Fechada em parte pela [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) (04/09/2026), e de propósito só em parte:** a janela passou a barrar o disparo fora de 9h–20h, mas `devido_em` continua sendo a hora da aritmética e ainda pode cair de madrugada — ajustá-lo duplicaria o que `created_at` já registra e apagaria o atraso. Ver a Emenda E-01 da RN-13.3 e a D2 do desenho da TEC-185.
```

A lacuna é **corrigida, não removida**: prosa que descreve estado antigo é defeito, e apagar o item esconderia que a decisão foi deliberada.

- [ ] **Step 4: Conferir que nada mais ficou mentindo**

```bash
grep -rn "madrugada\|9h-20h\|9h–20h\|RN-13.3" docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md src/mobia/domain/followup/ src/mobia/workers/jobs/sweep_followups.py
```

Leia cada acerto e confirme que nenhum afirma que a janela não existe. O docstring de `cadencia.py` **não** deve mudar: a régua continua respondendo "quem está devido", e não "quem pode receber agora" — a separação é a razão de o predicado morar em outro pacote.

- [ ] **Step 5: A verificação final, com a suíte inteira**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -u -m pytest -v
```

A suíte leva ~7,5 minutos e 857 testes (mais os 13 desta card). Com `-u -m pytest -v` há progresso na tela; um arquivo de saída vazio depois de dez minutos com `-q` é normal, não deadlock. **Não anuncie a card pronta sem os quatro comandos verdes** — evidência antes de afirmação.

- [ ] **Step 6: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md
git commit -F - <<'EOF'
docs(TEC-185): a RN-13.3 passa a dizer que a janela barra o disparo, e nao move o devido_em

Emenda E-01 a RN-13.3, sem tocar no texto de 22/08: `devido_em` continua
sendo a hora da RN-13.1 e pode cair de madrugada, e o que a janela impede
e o disparo. A afirmacao da secao 5 sobre `agendado_para` estar "ja
ajustado a janela" nao vale para a coluna que a substituiu.

A lacuna 3 do desenho da TEC-183 e corrigida e nao removida: ela passa a
dizer que a janela existe e que `devido_em` segue sem ajuste de proposito.
Apagar o item esconderia que a decisao foi deliberada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Auto-revisão do plano contra o spec

**Cobertura das dez decisões:**

| Decisão | Onde é implementada |
|---|---|
| D1 — adiamento é aritmética | Task 3, Steps 2 e 4 (o teste do adiamento e o parágrafo do docstring) |
| D2 — `devido_em` intacto | Nenhum código muda; Task 4 registra a escolha no SRS e na lacuna |
| D3 — o nome é `horario` | Global Constraints; Tasks 2 e 3 (nomes de módulo e de arquivo de teste) |
| D4 — mora em `outbound/` | Task 2, Step 3 (caminho do arquivo e docstring do módulo) |
| D5 — borda no minuto | Task 2, Steps 1 e 3 (os testes de 20:00, 20:00:03 e 20:05) |
| D6 — naive levanta | Task 2, Steps 1 e 3 |
| D7 — `tzdata` em `dependencies` | Task 1, Step 1 |
| D8 — janela em `Settings` | Task 1, Steps 2 e 4 |
| D9 — porteiro no topo | Task 3, Step 4 |
| D10 — `agora` no job | Task 3, Steps 1 e 4 |

**Cobertura dos critérios de aceite da card:**

| Cenário | Onde |
|---|---|
| Disparo dentro da janela sai na hora | Task 3, `test_as_vinte_em_ponto_ainda_disparam` |
| Disparo fora da janela é adiado | Task 3, `test_o_adiamento_nao_consome_a_tentativa` (primeiro momento) |
| Adiamento não consome a tentativa | Task 3, mesmo teste (terceiro momento, assertiva `== [1]`) |
| Limite exato da janela | Task 2, `test_as_vinte_em_ponto_permite`; Task 3, ponta a ponta |
| A regra vale também para lembretes | **Não coberto, e declarado**: a TEC-171 não existe. Lacuna 2 do spec |

**Consistência de tipos e nomes:** `horario_permite_envio(*, momento, inicio, fim, fuso)` tem a mesma assinatura nas Tasks 2 e 3. `followup_horario_inicio`, `followup_horario_fim`, `followup_fuso` e `fuso_de_envio` são idênticos entre Task 1 (definição) e Task 3 (uso). `sweep_followups(ctx, limite=500, *, agora=None)` é a mesma nos Steps 1, 2 e 4 da Task 3.

**Placeholders:** nenhum "TBD", nenhum "similar à Task N", nenhum passo de código sem bloco de código. O único item declarado como não feito é o cenário do lembrete, que é lacuna do produto e não do plano.
