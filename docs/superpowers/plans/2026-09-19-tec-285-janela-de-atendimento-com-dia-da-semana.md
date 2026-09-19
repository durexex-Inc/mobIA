# TEC-285 — A janela de atendimento ganha dia da semana: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a janela de atendimento humano ser segunda a sábado, 9h–19h, e fazer o texto que o lead recebe dizer isso.

**Architecture:** `dentro_da_janela_de_atendimento` ganha uma guarda de domingo **depois** da delegação a `horario_permite_envio`, que continua dona da aritmética de borda de minuto. `atendimento_horario_fim` vai de 18 para 19. Dois literais ganham "de segunda a sábado"; os dias são regra em código, não configuração.

**Tech Stack:** Python 3.13, pytest (+ pytest-xdist), pydantic-settings, `zoneinfo`, FastAPI, ARQ.

**Spec:** `docs/superpowers/specs/2026-09-19-tec-285-janela-de-atendimento-com-dia-da-semana-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **`line-length = 100`** (`pyproject.toml`). Os dois literais desta branch crescem e passam disso — têm de virar concatenação implícita de strings, não uma linha longa.
- **Texto que o lead recebe: português COM acento.** **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Valor citado dentro de comentário segue o valor.
- **Mensagem de commit:** `tipo(TEC-285): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **A assinatura `dentro_da_janela_de_atendimento(agora: datetime) -> bool` NÃO muda.** Duas fixtures `janela_aberta` monkeypatcham `lambda agora: True` (`tests/integration/test_pedido_de_humano.py`, `tests/integration/test_encaminhamento_por_intencao.py`); mudar a aridade quebra as duas.
- **`horario_permite_envio` não muda** — nem assinatura, nem semântica, nem os três chamadores. É instrução escrita no docstring de `dentro_da_janela_de_atendimento`.
- **Fuso e datas de teste, conferidos rodando (não presumidos):** `America/Sao_Paulo` é UTC-3 sem horário de verão. `2026-09-15` é terça, `2026-09-19` é sábado, `2026-09-20` é domingo.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4s, sem Docker). As Tasks 1–3 são inteiramente unitárias; só a Task 5 precisa de `docker compose`.

---

### Task 1: A guarda de domingo

**Files:**
- Modify: `src/mobia/domain/humano/deteccao.py` (constante nova antes de `dentro_da_janela_de_atendimento`; corpo e docstring da função, por volta das linhas 244–281)
- Test: `tests/unit/test_deteccao_de_humano.py`

**Interfaces:**
- Consumes: `horario_permite_envio(*, momento, inicio, fim, fuso) -> bool` (`domain/outbound/horario.py`) — **não mude**. Levanta `ValueError` quando `momento.tzinfo is None`.
- Produces: `dentro_da_janela_de_atendimento(agora: datetime) -> bool` — mesma assinatura, agora recusando domingo. E o módulo passa a expor `_DOMINGO = 6`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_deteccao_de_humano.py`, logo depois de `test_um_minuto_apos_o_fechamento_ja_e_fora`:

```python
def test_domingo_dentro_do_intervalo_de_horas_recusa() -> None:
    """Domingo as 15h esta no meio do intervalo e fora do atendimento.

    E o caso que a TEC-285 existe para consertar: ate ela, o unico eixo era a
    hora, e domingo era dia util como qualquer outro. 15:00 local = 18:00 UTC
    de 2026-09-20, que e domingo -- conferido rodando, nao presumido.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 20, 18, 0, tzinfo=UTC)) is False


def test_sabado_dentro_do_intervalo_de_horas_aceita() -> None:
    """Sabado e dia de atendimento, e e a borda que separa "sem domingo" de "so dia util".

    Sem este teste, uma guarda que recusasse o fim de semana inteiro passaria
    igual -- o teste de domingo sozinho nao distingue as duas. 17:00 local =
    20:00 UTC de 2026-09-19, que e sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 20, 0, tzinfo=UTC)) is True


def test_o_dia_e_lido_no_fuso_local_e_nao_em_utc(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O mesmo instante e sabado em UTC e domingo no fuso -- e o fuso e que manda.

    Com `America/Sao_Paulo` (UTC-3) esta distincao e inalcancavel: dentro da
    janela de 9h-19h local o dia coincide com o de UTC, entao uma
    implementacao que lesse `agora.weekday()` passaria por todos os outros
    testes deste arquivo. `Pacific/Tarawa` e UTC+12 fixo, sem horario de verao
    nunca, e faz 22:00 UTC de sabado virar 10:00 de DOMINGO local -- dentro do
    intervalo de horas, e portanto recusavel so pelo dia.

    Conferido rodando: `datetime(2026, 9, 19, 22, 0, tzinfo=UTC)` e sabado em
    UTC e domingo 10:00 em Tarawa.

    `caches_de_cliente_limpos` nao e enfeite: o docstring daquela fixture manda
    que todo teste que mexa em `Settings` dependa dela em vez de chamar
    `cache_clear()` na mao, senao um fuso do Pacifico vaza para o `Settings`
    cacheado de todo teste seguinte deste worker.
    """
    monkeypatch.setenv("FOLLOWUP_FUSO", "Pacific/Tarawa")
    get_settings.cache_clear()

    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 22, 0, tzinfo=UTC)) is False


def test_o_momento_ingenuo_continua_levantando() -> None:
    """A guarda de domingo nao pode engolir a excecao de `tzinfo` ausente.

    A ordem do corpo e que garante isso: `horario_permite_envio` roda PRIMEIRO
    e incondicionalmente, e e de la que a excecao vem. Uma implementacao que
    convertesse o fuso antes, para olhar o dia, faria um naive ser interpretado
    como hora do SISTEMA -- que difere entre esta maquina (UTC-3) e o runner do
    CI (UTC) -- e a excecao so apareceria em alguns dias da semana.
    """
    with pytest.raises(ValueError, match="tzinfo"):
        dentro_da_janela_de_atendimento(datetime(2026, 9, 20, 18, 0))
```

Acrescente ao topo do arquivo, se ainda não estiverem: `from mobia.app.config import get_settings`. `pytest`, `datetime` e `UTC` já estão importados.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py -k "domingo or sabado or fuso_local or ingenuo" -v --tb=short
```

Esperado: `test_domingo_dentro_do_intervalo_de_horas_recusa` e `test_o_dia_e_lido_no_fuso_local_e_nao_em_utc` FALHAM (devolvem `True`); os outros dois já passam. **Os dois que já passam não são decoração** — eles são o que impede a correção de ir longe demais (recusar o sábado) ou de quebrar a exceção do naive.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/humano/deteccao.py`, **imediatamente antes** de `def dentro_da_janela_de_atendimento`:

```python
# `datetime.weekday()` conta a partir de segunda como 0, entao domingo e 6.
# Constante nomeada porque `6` sozinho nao diz qual das duas convencoes do
# Python esta em uso: `isoweekday()` chamaria domingo de 7, e as duas formas
# convivem no ecossistema.
#
# **O dia e regra em codigo, e nao configuracao (TEC-285).** As horas vem de
# `Settings` e os dias nao, e a assimetria e deliberada: um campo cujo unico
# valor legal mantem um literal verdadeiro seria a armadilha que esta card
# existe para fechar -- liga-lo faria o texto mentir em silencio. Mudar os
# dias e mudanca de CODIGO E DE TEXTO, juntos.
_DOMINGO = 6
```

Substitua o corpo da função (as sete linhas a partir de `settings = get_settings()`) por:

```python
    settings = get_settings()
    fuso = ZoneInfo(settings.followup_fuso)

    # A ordem importa por duas razoes, e nenhuma e estilo.
    #
    # **A excecao do naive vem daqui.** `horario_permite_envio` levanta quando
    # `momento.tzinfo is None`, e roda primeiro e incondicionalmente para que
    # continue levantando. Converter o fuso antes, para olhar o dia, faria um
    # naive ser lido como hora do SISTEMA -- que difere entre esta maquina e o
    # runner do CI -- e a excecao passaria a depender do dia da semana.
    #
    # **E o dia e lido no fuso, nunca em UTC.** Com o `followup_fuso` default a
    # distincao nao aparece (UTC-3 mantem o mesmo dia dentro da janela), mas o
    # campo e configuravel: um fuso com offset grande o bastante faz o mesmo
    # instante ser sabado em UTC e domingo localmente.
    if not horario_permite_envio(
        momento=agora,
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
        fuso=fuso,
    ):
        return False

    return agora.astimezone(fuso).weekday() != _DOMINGO
```

Agora o docstring. Substitua o parágrafo que começa em `**Isto NAO funde as duas perguntas.**` — **preservando os dois parágrafos anteriores e o último, que continuam verdadeiros** — por:

```
    **Isto NAO funde as duas perguntas.** `horario_permite_envio` decide se um
    envio AUTOMATICO pode comecar; esta funcao decide se existe gente para
    ATENDER um pedido explicito do lead -- e as duas leem configuracao
    separada de proposito (`atendimento_horario_*` contra `followup_horario_*`).

    **As duas divergiram na TEC-285, e a divergencia foi resolvida sem
    duplicar a conta de borda.** O paragrafo acima prescrevia que, no dia em
    que isso acontecesse, esta funcao pararia de delegar e ganharia aritmetica
    propria. A instrucao foi seguida na intencao e nao na letra: a aritmetica
    que `horario_permite_envio` possui e a **borda de minuto**, a mesma conta
    que a TEC-146 gastou uma card inteira para ter num lugar so, e reescreve-la
    aqui para acrescentar um `weekday()` reabriria aquele defeito. O eixo novo
    -- o dia da semana -- e separavel do antigo, entao ele entra AQUI, fora da
    delegacao, e `horario_permite_envio` segue intacta para os seus tres
    chamadores. Se um dia a BORDA divergir, ai sim a instrucao original vale
    pela letra.

    `agora` precisa ser aware pela mesma razao que `horario_permite_envio`
    exige -- ver o docstring dela; a excecao de `tzinfo` ausente vem de la, e
    o comentario do corpo explica por que a ordem das duas checagens a
    preserva.
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py -v --tb=short
```

Esperado: tudo PASS, incluindo os quatro testes de janela que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/humano/deteccao.py tests/unit/test_deteccao_de_humano.py
git commit -m "feat(TEC-285): domingo deixa de ser dia de atendimento

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A janela fecha às 19h

**Files:**
- Modify: `src/mobia/app/config.py` (`atendimento_horario_fim`, por volta da linha 395)
- Test: `tests/unit/test_deteccao_de_humano.py`

**Interfaces:**
- Consumes: `dentro_da_janela_de_atendimento` com a guarda de domingo da Task 1.
- Produces: `Settings.atendimento_horario_fim = 19`, lido por `dentro_da_janela_de_atendimento` e pelos dois literais das Tasks 3.

- [ ] **Step 1: Mover os testes de borda que já existem**

Em `tests/unit/test_deteccao_de_humano.py`, os dois testes de fechamento afirmam a borda antiga. **Eles não são apagados — as horas mudam, e o docstring diz por quê.**

Substitua `test_a_janela_inclui_a_hora_de_fechamento` e `test_um_minuto_apos_o_fechamento_ja_e_fora` por:

```python
def test_a_janela_inclui_a_hora_de_fechamento() -> None:
    """19h em ponto ainda e atendimento -- fim e o ultimo MINUTO valido, nao a ultima hora.

    Mesma convencao de `followup_horario_fim`/`horario_permite_envio`: a borda
    de fim e inclusiva. 19:00 local = 22:00 UTC. O numero saiu de 18 para 19 na
    TEC-285; a convencao de borda nao mudou.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 22, 0, tzinfo=UTC)) is True


def test_um_minuto_apos_o_fechamento_ja_e_fora() -> None:
    """19:01 local = 22:01 UTC recusa, e e essa recusa que a borda inclusiva de fim admite."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 22, 1, tzinfo=UTC)) is False
```

E acrescente o teste que pega o efeito colateral que a card não menciona:

```python
def test_sabado_as_dezoito_e_meia_passou_a_ser_atendimento() -> None:
    """A mudanca de horas alcanca os seis dias, e nao so o domingo.

    18:30 de sabado ficava FORA da janela ate a TEC-285 (o fim era 18) e passa
    a ficar dentro. Esta escrito como teste porque e o tipo de consequencia que
    se descobre por acidente: a card fala de dia da semana, e o numero das
    horas mudou junto. 18:30 local = 21:30 UTC de 2026-09-19, sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 21, 30, tzinfo=UTC)) is True


def test_a_borda_de_minuto_vale_no_sabado_tambem() -> None:
    """O ultimo dia da janela nao ganha regra propria: 19:01 recusa no sabado como na terca.

    Existe porque a guarda de domingo e a checagem de hora sao dois eixos, e
    um deles roda antes do outro -- um corpo que devolvesse cedo por dia
    poderia, escrito errado, pular a borda no unico dia que faz fronteira com
    domingo. 19:01 local = 22:01 UTC de 2026-09-19, sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 22, 1, tzinfo=UTC)) is False
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py -k "fechamento or dezoito_e_meia" -v --tb=short
```

Esperado: `test_a_janela_inclui_a_hora_de_fechamento` e `test_sabado_as_dezoito_e_meia_passou_a_ser_atendimento` FALHAM (o fim ainda é 18); `test_um_minuto_apos_o_fechamento_ja_e_fora` passa por acaso, porque 22:01 UTC já está fora com o fim antigo também.

- [ ] **Step 3: Implementar**

Em `src/mobia/app/config.py`:

```python
    atendimento_horario_fim: int = 19
```

E, no comentário logo acima dos dois campos, substitua o parágrafo final (o que começa em `# Mesma convencao de borda`) por:

```python
    # Mesma convencao de borda que `followup_horario_fim` documenta acima --
    # `fim` e o ultimo MINUTO em que a janela ainda vale, nao a ultima hora
    # inteira: `atendimento_horario_fim=19` inclui 19:00 e recusa 19:01. Ver
    # `dentro_da_janela_de_atendimento` para a comparacao.
    #
    # **Estas horas nao dizem a janela inteira (TEC-285).** Domingo nao e dia
    # de atendimento, e isso NAO esta aqui: e regra em codigo, na constante
    # `_DOMINGO` de `domain/humano/deteccao.py`, que explica por que os dias
    # ficaram fora da configuracao. Quem ler so estes dois campos conclui que a
    # janela e todo dia, e e por isso que esta frase existe.
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_deteccao_de_humano.py tests/unit/test_config.py -v --tb=short
```

Esperado: tudo PASS. `test_a_janela_de_atendimento_no_limite_das_bordas_sobe` e `test_a_janela_de_atendimento_invertida_nao_sobe` (`tests/unit/test_config.py`) continuam verdes — o validator aceita `0 <= 9 < 19 <= 23` sem mudança.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/app/config.py tests/unit/test_deteccao_de_humano.py
git commit -m "feat(TEC-285): a janela de atendimento fecha as 19h

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Os dois literais dizem os dias

**Files:**
- Modify: `src/mobia/domain/humano/deteccao.py` (`TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`, por volta da linha 319)
- Modify: `src/mobia/domain/agente/turno.py` (`SUFIXO_FORA_DA_JANELA`, por volta da linha 237, e o comentário acima dele)
- Test: `tests/unit/test_textos_do_encaminhamento.py`, `tests/unit/test_deteccao_de_humano.py`

**Interfaces:**
- Consumes: `Settings.atendimento_horario_inicio` (9) e `atendimento_horario_fim` (19, da Task 2).
- Produces: os dois literais com `{inicio}`/`{fim}` preservados e a frase de dias acrescentada. Nenhuma assinatura muda.

**`TEXTO_DA_JANELA_HUMANA` (`domain/notificacao/envio.py`) NÃO é tocado** — ele já diz "de segunda a sábado".

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_textos_do_encaminhamento.py`, substitua `test_o_sufixo_de_fora_da_janela_nomeia_o_horario` por:

```python
def test_o_sufixo_de_fora_da_janela_nomeia_o_horario_e_os_dias() -> None:
    """O sufixo formata as HORAS a partir da configuracao e escreve os DIAS por extenso.

    As horas vem de `Settings` porque ate a TEC-285 o Gherkin da TEC-137 dizia
    "das 9h as 19h" enquanto a janela real era 9h-18h, e citar o numero da card
    faria o texto mentir. A TEC-285 fechou essa divergencia subindo a janela --
    o numero passou a bater --, mas a regra de formatar em vez de literalizar
    fica: ela nao existia por causa daquela divergencia especifica.

    Os dias sao literais porque eles nao vem de `Settings`: sao regra em
    codigo, em `_DOMINGO` (`domain/humano/deteccao.py`), e o comentario de la
    registra que mudar os dias e mudanca de codigo E de texto.
    """
    settings = get_settings()
    formatado = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio, fim=settings.atendimento_horario_fim
    )

    assert str(settings.atendimento_horario_inicio) in formatado
    assert str(settings.atendimento_horario_fim) in formatado
    assert "{inicio}" not in formatado
    assert "de segunda a sábado" in formatado
```

E substitua o corpo de `test_o_sufixo_nao_promete_quando_a_resposta_chega` (mantendo o docstring inteiro, que continua verdadeiro) por:

```python
    settings = get_settings()
    formatado = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio, fim=settings.atendimento_horario_fim
    )
    assert "pode demorar" in formatado
    assert "vem no próximo" not in formatado
```

Acrescente `from mobia.app.config import get_settings` ao topo do arquivo, se ainda não estiver.

Em `tests/unit/test_deteccao_de_humano.py`, acrescente:

```python
def test_o_texto_de_fora_do_horario_nomeia_os_dias_e_formata_as_horas() -> None:
    """O irmao do sufixo de `turno.py`, e a mesma regra: horas da config, dias literais.

    As duas redacoes sao mantidas em sincronia de proposito -- o comentario de
    `SUFIXO_FORA_DA_JANELA` registra que duas redacoes para o mesmo fato seriam
    duas coisas para manter alinhadas.
    """
    settings = get_settings()
    formatado = TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
        inicio=settings.atendimento_horario_inicio, fim=settings.atendimento_horario_fim
    )

    assert str(settings.atendimento_horario_inicio) in formatado
    assert str(settings.atendimento_horario_fim) in formatado
    assert "{inicio}" not in formatado
    assert "de segunda a sábado" in formatado
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_textos_do_encaminhamento.py tests/unit/test_deteccao_de_humano.py -k "dias" -v --tb=short
```

Esperado: os dois novos FALHAM em `assert "de segunda a sábado" in formatado`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/humano/deteccao.py`, substitua o comentário e o literal:

```python
# `{inicio}` e `{fim}` sao preenchidos com as horas locais da janela. Os DIAS
# sao literais, e nao vem de `Settings`: ver `_DOMINGO`, acima, para a razao.
TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO = (
    "Claro! Já estou passando esta conversa para um corretor da nossa equipe. "
    "Nosso atendimento é de segunda a sábado, das {inicio}h às {fim}h, "
    "então a resposta pode demorar até o próximo horário. "
    "Pode continuar escrevendo que fica tudo registrado."
)
```

Em `src/mobia/domain/agente/turno.py`, substitua o **primeiro** parágrafo do comentário (o que começa em `# Acrescentado aos dois textos acima`) — **preservando o parágrafo de `"pode demorar até"`, que continua verdadeiro** — e o literal:

```python
# Acrescentado aos dois textos acima quando o pedido chega fora da janela de
# atendimento. As horas vem de `Settings`, e nao de um literal: a regra e do
# repo e nao depende de nenhuma divergencia especifica.
#
# **A divergencia que este comentario registrava foi fechada (TEC-285).** Ate
# ela, o Gherkin da TEC-137 dizia "das 9h as 19h" e a janela real era 9h-18h --
# citar o numero da card faria o texto mentir. A TEC-285 subiu a janela para
# segunda-a-sabado 9h-19h, e os dois numeros passaram a bater.
#
# **Os dias sao literais, e as horas nao.** Ver `_DOMINGO` em
# `domain/humano/deteccao.py`: os dias sao regra em codigo, e mudar a regra e
# mudar este texto junto.
```

```python
SUFIXO_FORA_DA_JANELA = (
    " O atendimento é de segunda a sábado, das {inicio}h às {fim}h, "
    "então a resposta pode demorar até o próximo horário."
)
```

**Atenção ao `line-length = 100`:** o literal antigo era uma linha só e o novo não cabe. A concatenação implícita acima já resolve; confira o espaço final de `"{fim}h, "`, que é o que separa as duas metades.

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit -v --tb=short -k "texto or janela or deteccao or acento"
```

Esperado: tudo PASS, **incluindo `tests/unit/test_acento_no_texto_ao_lead.py`** — os dois literais tocados continuam na lista daquele arquivo, e `test_a_lista_de_literais_nao_encolheu_sem_querer` reprova se um sumir.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/humano/deteccao.py src/mobia/domain/agente/turno.py tests/unit/
git commit -m "feat(TEC-285): o texto ao lead diz de segunda a sabado

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A prosa que passou a mentir

Sem código novo. **Três** dos seis sítios já saíram nas Tasks 1–3, porque eram do arquivo que aquelas tasks já editavam: o docstring de `dentro_da_janela_de_atendimento` (Task 1), o comentário dos campos de `Settings` (Task 2) e o comentário de `SUFIXO_FORA_DA_JANELA` (Task 3). Sobram três.

**Files:**
- Modify: `src/mobia/app/config.py` (docstring de `_recusar_janela_de_atendimento_impossivel`, por volta da linha 480)
- Modify: `src/mobia/domain/notificacao/envio.py` (comentário de `TEXTO_DA_JANELA_HUMANA`, por volta da linha 55)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (abaixo da Emenda E-01 da RN-03.4, por volta da linha 164)

- [ ] **Step 1: O docstring do validator**

Em `src/mobia/app/config.py`, no docstring de `_recusar_janela_de_atendimento_impossivel`, substitua a frase final (a que começa em `Nada quebra, nada loga erro`) por:

```
        Nada quebra, nada loga erro -- so a imobiliaria aparenta nunca ter
        ninguem disponivel, e e essa mentira silenciosa que a guarda existe
        para recusar na subida do processo.

        **Esta guarda nao cobre o dia da semana (TEC-285).** Domingo fecha a
        janela por regra de codigo (`_DOMINGO`, em `domain/humano/deteccao.py`)
        e nao por configuracao, entao nao ha o que validar aqui -- e tambem
        nao ha como uma configuracao errada apagar um dia. O que mudou e o
        alcance da frase acima: "aparenta nunca ter ninguem disponivel" deixou
        de ser exclusividade da janela invertida, porque existe um dia inteiro
        da semana em que todo lead recebe o texto de fora do horario.
```

- [ ] **Step 2: O comentário de `TEXTO_DA_JANELA_HUMANA`**

Em `src/mobia/domain/notificacao/envio.py`, o comentário declara que "o sistema trata domingo como dia util enquanto esta frase promete que nao". **Metade disso deixou de ser verdade.** Substitua essa frase por:

```python
# ela vai divergir em silencio quando a agenda por dia (TEC-170) chegar, e
# tera de mudar junto.
#
# **A divergencia encolheu pela metade na TEC-285, e a metade que sobrou e
# esta.** Aquela card fez a janela da IMOBILIARIA ser segunda-a-sabado, entao
# do lado dela a frase deixou de ser promessa vazia. Mas este texto e guardado
# pelas horas do CORRETOR, cuja jornada continua sem dia da semana: um corretor
# com jornada 9-19 e alcancavel por esta checagem no domingo, e a frase continua
# prometendo que nao. Consertar exige dia na jornada do corretor, que e a
# TEC-170 -- a TEC-285 declarou isso como lacuna em vez de esticar o escopo.
```

- [ ] **Step 3: A emenda ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, logo **abaixo** da linha da `Emenda E-01 (TEC-137, 15/09/2026)` sob a RN-03.4, acrescente (mesma indentação de dois espaços, prosa **COM acento**):

```markdown
  - **Emenda E-02 (TEC-285, 19/09/2026):** a divergência que a Emenda E-01 declarou está **fechada**, e no sentido do Gherkin: a janela de atendimento da imobiliária passa a ser **de segunda a sábado, das 9h às 19h**, alinhando-se ao PR-06. O que muda no sistema são duas coisas, e só a primeira estava na E-01: `atendimento_horario_fim` vai de 18 para 19, e **domingo deixa de ser dia de atendimento** — um eixo que a configuração não tinha. Os dias são **regra em código** e não configuração (`_DOMINGO`, em `domain/humano/deteccao.py`), enquanto as horas continuam vindo de `Settings` e sendo formatadas no texto, que era o argumento da E-01 e não cai. **Consequências declaradas:** sábado às 18h30 passava a fora da janela e passa a dentro, porque a mudança de horas alcança os seis dias; e o aviso de janela humana da TEC-177 continua prometendo "de segunda a sábado" com as horas do **corretor**, cuja jornada ainda não tem dia da semana — a divergência encolhe pela metade e só fecha com a agenda real (TEC-170). Ver `docs/superpowers/specs/2026-09-19-tec-285-janela-de-atendimento-com-dia-da-semana-design.md`.
```

- [ ] **Step 4: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reconfira cada `ALTERADO` e cada `VIZINHO` dentro de `dentro_da_janela_de_atendimento`, dos dois blocos de literais e do comentário dos campos de `Settings`. **`VIZINHO` é a categoria que importa** — comentário que ninguém editou não aparece no diff, e é assim que ele sobrevive errado. Qualquer `FALSO` **afirma** em vez de suspeitar: conserte antes de seguir.

Se a saída resumir com `... +N omitida(s)`, rode `--tudo`.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add -A
git commit -m "docs(TEC-285): a prosa da janela acompanha o dia da semana

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A suíte inteira, uma vez

- [ ] **Step 1: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

**Peça `--tb=short` desde o início.** A regra é uma execução só; jogar fora o traceback da única que você fez é o desperdício caro.

**Dois arquivos de integração merecem atenção particular nesta branch**, porque monkeypatcham a função que a Task 1 mudou: `tests/integration/test_pedido_de_humano.py` e `tests/integration/test_encaminhamento_por_intencao.py`. As fixtures `janela_aberta` deles fazem `lambda agora: True` — se a assinatura tivesse mudado, é aqui que apareceria.

- [ ] **Step 2: Ler o resultado pelas regras da casa**

- **Centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`:** não é a branch. Espere e retente, ou baixe o `-n`.
- **Compose `unhealthy` e `CannotConnectNowError` aos montes:** o Postgres caiu sob o paralelismo. `docker compose restart postgres` e rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).
- **`relation ... does not exist` em dezenas de testes:** são os bancos dos workers com `alembic_version` adiantado, quase nunca a migration.
- **Falha isolada em `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` ou `test_optout_repositorio.py`:** rode o arquivo sozinho antes de culpar a mudança.
- **Falha que não é nenhum dos acima:** repita sobre a mesma árvore antes de concluir.

- [ ] **Step 3: Guardar o hash junto com o resultado**

```bash
git rev-parse --short HEAD
```

---

### Task 6: Push, PR e a card

- [ ] **Step 1: Push**

```bash
git push -u origin feat/tec-285-janela-de-atendimento-com-dia-da-semana
```

**Se voltar `403 Write access to repository not granted`**, não é falta de permissão: o Git Credential Manager responde antes do `gh` e entrega uma credencial sem escrita. A lista de helpers é aditiva, então limpá-la primeiro é o que resolve:

```bash
git -c credential.helper= -c credential.helper='!gh auth git-credential' push -u origin feat/tec-285-janela-de-atendimento-com-dia-da-semana
```

- [ ] **Step 2: Abrir o PR**

Escreva o corpo num arquivo do scratchpad e passe-o com `--body-file`:

```bash
gh pr create --base main \n  --title "feat(TEC-285): a janela de atendimento passa a ser segunda-a-sabado 9h-19h" \n  --body-file <caminho do arquivo que voce acabou de escrever>
```

O corpo cobre: a decisão de produto e onde ela foi registrada; a escolha de dias-em-código contra as duas alternativas; a leitura por intenção do docstring que mandava "parar de delegar"; o efeito colateral de sábado às 18h30; e as duas lacunas declaradas (o texto do corretor e o SLA). Termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 3: Comentar na card e mover para "Em análise"**

O comentário registra o que some se ficar só no PR:

- **Divergências em relação à card:** ela conta três sítios de texto; são dois literais, porque venda e suporte compartilham o mesmo sufixo e o mesmo `if`. E existe um terceiro literal com horário que a card não lista.
- **Critério de aceite e o que ficou de fora:** o terceiro cenário Gherkin ("o horário do corretor continua distinto") é satisfeito por não fazer nada — a jornada do corretor não foi tocada. Vale dizer que foi verificado, não esquecido.
- **Lacuna que é decisão de produto:** depois desta card o agente **afirma** ao lead que o atendimento é de segunda a sábado. Antes ele só dizia horas. Se o expediente real for outro, a mentira ficou mais específica.
- **O que a card não entrega:** `TEXTO_DA_JANELA_HUMANA` continua prometendo dias com as horas do corretor; e `limite_de_aceite` continua contando domingo como jornada para o SLA.
- **A emenda ao SRS**, nomeada: `Emenda E-02 (TEC-285)` sob a RN-03.4.

Transição: "Em análise", **não** "Feito".

- [ ] **Step 4: Depois do merge**

```bash
git merge-base --is-ancestor <hash> origin/main
```

Confirmado, volte para a `main`, `pull`, e apague a branch local.
