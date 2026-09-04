# TEC-188 — Máximo de 4 mensagens não respondidas: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nenhuma automação envia a um lead que já acumulou 4 mensagens automáticas sem resposta, e o instante em que ele sai do alcance da automação vira um evento.

**Architecture:** Um predicado puro (`antispam_permite_envio`) em `domain/outbound/`, ao lado da janela da TEC-185, alimentado por um contador novo (`Candidato.ja_enviadas`) que é `COUNT(*)` de linhas de `followups` sob a âncora atual — o inverso do `MAX(tentativa_numero)` que a mesma consulta já calcula ao lado. A guarda entra na varredura entre `tentativa_devida` e `esta_em_optout`.

**Tech Stack:** Python 3.13, SQLAlchemy async (SQL textual), ARQ, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-tec-188-maximo-sem-resposta-design.md` — leia antes de começar. Decisões numeradas D1–D8; as tarefas citam essas siglas.

## Global Constraints

- **Os três gates estáticos, nesta ordem, antes de todo commit.** O formatador é gate separado do linter, e passar num não diz nada sobre o outro:
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m mypy`
- **Escopo do ruff é `src tests alembic evals`**, não `src tests`. O mypy segue só em `src`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento. Convenção do repo, não checada por linter nenhum.
- **Comentário não mente.** Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **Nunca use a palavra `teto` para nomear código novo.** Ela já é `_TETOS_POR_TEMPERATURA` em `followup/repositorio.py` (o teto **de tentativas da cadência**, que é exatamente a coisa sobre a qual este máximo prevalece), mais `contexto_teto_de_tokens` e o teto por chamada do cliente Anthropic. O nome deste conceito é `antispam` / `MAXIMO_SEM_RESPOSTA`. A prosa de `docs/` continua dizendo "teto", que é o termo do negócio. Ver D7.
- **`MAXIMO_SEM_RESPOSTA` é constante de módulo escrita à mão.** Não derive de `CADENCIA` e não mova para `Settings` — ver D4. Derivar a tornaria tautológica; torná-la ajustável contradiz *"máximo absoluto"* na letra.
- **Basenames de teste não colidem entre `tests/unit/` e `tests/integration/`.** Colisão aborta a coleta da suíte inteira e não aparece no arquivo isolado. `test_antispam.py` é novo em ambos.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-188): o que passou a ser verdade`.
- **A suíte é lenta (~22 minutos, ~1140 testes) e precisa do Postgres de pé** — a fixture de sessão `migrar_banco` roda `alembic upgrade head` para **todo** teste sob `tests/`, unitários inclusive. Rode arquivos-alvo durante as tarefas; a suíte inteira só na Task 4. Se você vir `subprocess.CalledProcessError` no setup ou `ConnectionResetError [WinError 64]`, é o container mais lento que o healthcheck diz: espere e retente.

---

### Task 1: O predicado puro `antispam_permite_envio`

**Files:**
- Create: `src/mobia/domain/outbound/antispam.py`
- Test: `tests/unit/test_antispam.py`

**Interfaces:**
- Consumes: nada.
- Produces: `MAXIMO_SEM_RESPOSTA: int` (valor 4) e `antispam_permite_envio(*, ja_enviadas: int) -> bool`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_antispam.py`:

```python
"""O maximo absoluto de mensagens automaticas sem resposta. TEC-188, RN-13.7."""

from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio


def test_lead_que_nao_recebeu_nada_pode_receber() -> None:
    assert antispam_permite_envio(ja_enviadas=0) is True


def test_uma_abaixo_do_maximo_ainda_pode() -> None:
    """Tres nao respondidas ainda permitem a quarta, e a quarta e a ultima."""
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA - 1) is True


def test_no_maximo_nao_pode() -> None:
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA) is False


def test_acima_do_maximo_continua_nao_podendo() -> None:
    """A defesa contra um `!=` no lugar do `<`.

    Uma contagem acima do maximo nao deveria existir hoje, mas se existir --
    um segundo produtor de automacao (TEC-171), ou uma cadencia mais longa via
    RF-19 -- ela tem de continuar barrando, e nao voltar a permitir.
    """
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA + 1) is False


def test_o_maximo_e_o_numero_da_regra() -> None:
    """RN-13.7 fixa o numero em 4 mensagens sem resposta consecutivas.

    Este teste fixa o numero na base de codigo de modo que uma mudanca nele
    seja deliberada e visivel. Mas NAO detecta se o numero foi derivado de
    `CADENCIA` -- hoje `len(CADENCIA[Temperatura.QUENTE])` tambem e 4, entao
    nenhuma asserctacao sobre valor consegue discernir um 4 escrito a mao de um
    derivado. O que protege contra derivacao e o comentario no `MAXIMO_SEM_RESPOSTA`
    e a revisao, nao este teste.
    """
    assert MAXIMO_SEM_RESPOSTA == 4
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_antispam.py -v
```

Esperado: erro de coleta — `ModuleNotFoundError: No module named 'mobia.domain.outbound.antispam'`.

- [ ] **Step 3: Implementar o módulo**

Crie `src/mobia/domain/outbound/antispam.py`:

```python
"""O maximo absoluto de mensagens automaticas sem resposta. TEC-188, RN-13.7.

Pura de proposito, no molde de `horario.py`, `cadencia.py` e `score.py`: sem
I/O, sem banco, sem chamada ao modelo. Quem conta e o repositorio; aqui so se
compara.

**Mora em `outbound/` e nao em `followup/`**, ao lado de `horario.py` e pela
mesma razao: a RN-13.7 diz que, atingido o maximo, "nenhuma automacao envia
mais nada a esse lead -- nem follow-up, nem lembrete, nem reengajamento". Sob
`followup/` a TEC-171 nao acharia esta funcao e escreveria a segunda, que e a
forma do defeito que a TEC-146 gastou uma card inteira consertando.

**E NAO mora em `GuardedOutbound.send`**, pela mesma razao que a janela da
TEC-185 nao mora: aquele caminho carrega a resposta ao lead, e o maximo e
sobre mensagem AUTOMATICA. Um lead no maximo que escreve continua sendo
respondido -- e essa resposta dele, por mover a ancora, e justamente o que
zera o contador.
"""

# A RN-13.7, literal. **Escrito a mao, e nao derivado de `CADENCIA`** -- ao
# contrario de `INTERVALO_MINIMO` e dos tetos por temperatura da consulta, que
# sao derivados de proposito para nao virarem segunda fonte.
#
# Aqui derivar seria o erro: o maximo ficaria igual ao teto da cadencia por
# construcao, e a regra "o teto prevalece sobre a configuracao de cadencia --
# mesmo que alguem configure 6 tentativas, o envio para na quarta" viraria
# tautologia. O sentido da RN-13.7 e ser um numero INDEPENDENTE que sobrevive
# a alguem alongar a cadencia.
#
# E nao vai para `Settings`, ao contrario da janela da TEC-185: a card daquela
# pedia janela ajustavel sem deploy, e esta pede o contrario na letra --
# "maximo absoluto". Um maximo ajustavel por variavel de ambiente e um maximo
# que a proxima pessoa com pressa aumenta, e o bloqueio do numero na Meta nao
# volta atras.
MAXIMO_SEM_RESPOSTA = 4


def antispam_permite_envio(*, ja_enviadas: int) -> bool:
    """Se ainda cabe uma mensagem automatica para este lead. RN-13.7.

    `ja_enviadas` e a CONTAGEM de mensagens automaticas que sairam desde a
    ultima fala do lead -- e nao o numero da ultima tentativa. A diferenca e o
    centro desta card: a regua da cadencia devolve a MAIOR tentativa vencida e
    pula as intermediarias, entao um lead calado ha dez dias tem uma linha so,
    com `tentativa_numero = 4`. Contar pela posicao cortaria da automacao um
    lead que recebeu uma unica mensagem, e nada denunciaria o corte -- ele
    simplesmente pararia de receber follow-up.

    A comparacao e `<` e nao `!=`: com igualdade estrita, uma contagem que
    passasse do maximo por qualquer motivo voltaria a permitir envio.

    Keyword-only por consistencia com `horario_permite_envio` e com o resto do
    dominio puro. Aqui o argumento da troca silenciosa nao se aplica (ha um
    parametro so), mas a simetria e o que faz a lista de guardas da varredura
    se ler como uma lista.
    """
    return ja_enviadas < MAXIMO_SEM_RESPOSTA
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_antispam.py -v
```

Esperado: 5 PASS.

- [ ] **Step 5: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/outbound/antispam.py tests/unit/test_antispam.py
git commit -F - <<'EOF'
feat(TEC-188): o maximo absoluto de mensagens sem resposta passa a existir

`antispam_permite_envio` e pura e mora em outbound/, ao lado da janela, porque
a RN-13.7 cobre follow-up, lembrete e reengajamento -- sob followup/ a TEC-171
nao a acharia.

`MAXIMO_SEM_RESPOSTA` e escrito a mao e nao derivado de CADENCIA: derivado, o
maximo acompanharia a tabela de intervalos em vez de prevalecer sobre ela, e a
regra "mesmo que alguem configure 6 tentativas, o envio para na quarta" nao
significaria nada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: O contador `ja_enviadas` na consulta de candidatos

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py` (a dataclass `Candidato`, a SQL `_SELECIONAR_CANDIDATOS`, e a construção do `Candidato` no fim de `candidatos_a_followup`)
- Test: `tests/integration/test_followups_model.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `Candidato.ja_enviadas: int` — a contagem de linhas de `followups` sob `ancora_em`. `candidatos_a_followup` passa a preenchê-lo.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/integration/test_followups_model.py`. O arquivo já tem tudo o que estes testes precisam: `_linha(**campos)` monta uma linha de `followups` com defaults, `_qualificacao(session, temperatura=...)` cria o lead, `_fala_do_lead(session, quando=...)` cria a mensagem de entrada que define a âncora, e as constantes `ANCORA` e `AGORA` (que é `ANCORA + 30 dias`) já existem no módulo.

```python
async def test_o_contador_conta_linhas_e_nao_a_maior_tentativa(session) -> None:
    """A inversao da D1, que e o centro desta card.

    Um lead cuja UNICA linha sob a ancora e a tentativa 3 -- o caso do lead
    atrasado, que recebeu so a maior tentativa vencida -- tem `ja_disparada=3`
    e `ja_enviadas=1`. Os dois agregados saem da mesma consulta, sobre as
    mesmas linhas, com respostas diferentes e ambas corretas.

    E o teste que morre se alguem escrever o contador como MAX.

    **O numero 3 e escolhido, e 4 nao serviria:** com `tentativa_numero=4` o
    lead teria `ja_disparada=4`, o corte de esgotamento do QUENTE o excluiria
    da candidatura, e a consulta nao devolveria linha nenhuma para comparar --
    o teste ficaria vazio sem parecer vazio.
    """
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=3, devido_em=ANCORA + timedelta(days=3)))
    await session.commit()

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert len(candidatos) == 1
    assert candidatos[0].ja_disparada == 3
    assert candidatos[0].ja_enviadas == 1


async def test_a_resposta_do_lead_zera_o_contador(session) -> None:
    """A RN-13.7 pede que "qualquer resposta do lead zere o contador", e no
    modelo derivado isso nao tem codigo: a resposta move a ancora, e a
    contagem sob a ancora nova comeca em zero.

    A ultima assertiva existe porque apagar as linhas antigas TAMBEM zeraria o
    contador, e seria errado -- a trilha e append-only, e as duas series ficam
    lado a lado sob ancoras diferentes.

    Tres linhas e nao quatro: com quatro, `ja_disparada` chegaria a 4 e o corte
    de esgotamento excluiria o lead da candidatura ja na primeira consulta.
    """
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    for numero in (1, 2, 3):
        session.add(_linha(tentativa_numero=numero, devido_em=ANCORA + timedelta(days=numero)))
    await session.commit()

    antes = await candidatos_a_followup(session, agora=AGORA)
    assert antes[0].ja_enviadas == 3

    nova_fala = ANCORA + timedelta(days=1)
    await _fala_do_lead(session, quando=nova_fala)

    depois = await candidatos_a_followup(session, agora=AGORA)
    assert depois[0].ancora_em == nova_fala
    assert depois[0].ja_enviadas == 0
    assert depois[0].ja_disparada == 0
    assert len((await session.scalars(select(FollowUp))).all()) == 3
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py -k "contador or zera" -v
```

Esperado: FALHAM com `AttributeError: 'Candidato' object has no attribute 'ja_enviadas'`.

- [ ] **Step 3: Acrescentar o campo à dataclass**

Em `src/mobia/domain/followup/repositorio.py`, na dataclass `Candidato`, depois de `ja_disparada: int`:

```python
    ja_enviadas: int
```

E no docstring da dataclass, depois do parágrafo que explica `ja_disparada`:

```
    `ja_enviadas` e a CONTAGEM de linhas sob a mesma ancora, e nao o maximo --
    a inversa exata do campo acima, sobre exatamente as mesmas linhas. A regua
    pula tentativas intermediarias, entao um lead com uma unica linha de
    `tentativa_numero=3` tem `ja_disparada=3` e `ja_enviadas=1`. O maximo
    anti-spam da RN-13.7 conta mensagens que sairam, nao posicoes na regua.
```

- [ ] **Step 4: Acrescentar o subselect à consulta**

Na CTE `candidatos` de `_SELECIONAR_CANDIDATOS`, logo depois do bloco `COALESCE(...) AS ja_disparada`, acrescente a vírgula e o segundo subselect:

```sql
               (SELECT COUNT(*)
                  FROM followups f
                 WHERE f.channel = lq.channel
                   AND f.conversation_key = lq.conversation_key
                   AND f.ancora_em = u.ancora) AS ja_enviadas
```

E acrescente `ja_enviadas` à lista do `SELECT` externo, que hoje é:

```sql
    SELECT channel, conversation_key, temperatura, ancora, ja_disparada
```

Acrescente um comentário Python ao bloco de comentários que precede `_SELECIONAR_CANDIDATOS`:

```
# **Os dois subselects sao a MESMA leitura com agregados opostos, e isso e
# proposital.** `ja_disparada` e o MAX porque a regua precisa saber ate onde a
# cadencia foi; `ja_enviadas` e o COUNT porque o maximo da RN-13.7 conta
# mensagens que sairam. A regua pula tentativas intermediarias, entao os dois
# divergem sempre que houve salto -- uma unica linha de `tentativa_numero=3`
# da MAX=3 e COUNT=1.
#
# O COUNT nao leva COALESCE e o MAX leva: `COUNT` de zero linhas e 0, enquanto
# `MAX` de zero linhas e NULL. Nao "corrija" a assimetria.
#
# Os dois rodam por linha ja filtrada e sao servidos pelo mesmo
# `ix_followups_lead`. O alias `f` se repete porque os escopos sao
# independentes.
```

- [ ] **Step 5: Preencher o campo na construção do `Candidato`**

No fim de `candidatos_a_followup`, na list comprehension, depois de `ja_disparada=linha.ja_disparada,`:

```python
            ja_enviadas=linha.ja_enviadas,
```

- [ ] **Step 6: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py -v
```

Esperado: PASS, incluindo todos os testes que já existiam no arquivo. Se algum falhar com `ConnectionResetError` ou erro de Redis, rode o arquivo sozinho de novo antes de concluir que sua mudança quebrou algo.

- [ ] **Step 7: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 8: Commit**

```bash
git add src/mobia/domain/followup/repositorio.py tests/integration/test_followups_model.py
git commit -F - <<'EOF'
feat(TEC-188): a consulta passa a dizer quantas mensagens sairam, e nao so ate onde a regua foi

`ja_enviadas` e COUNT(*) sob a ancora, ao lado do MAX que ja existia. Os dois
agregados leem as mesmas linhas e divergem sempre que houve salto: uma unica
linha de tentativa_numero=3 da MAX=3 e COUNT=1.

O maximo da RN-13.7 conta mensagens que sairam, nao posicoes na regua -- com o
MAX, um lead que recebeu uma unica mensagem seria cortado da automacao sem
nenhum sintoma.

A resposta do lead zerar o contador nao precisou de codigo: ela move a ancora.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: A guarda e o evento na varredura

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py`
- Test: `tests/integration/test_sweep_followups.py`

**Interfaces:**
- Consumes: `antispam_permite_envio` e `MAXIMO_SEM_RESPOSTA` (Task 1); `Candidato.ja_enviadas` (Task 2).
- Produces: o evento de log `followup.antispam_atingido`. O retorno de `sweep_followups` **não** muda: continua sendo o número de linhas gravadas.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/integration/test_sweep_followups.py`. O arquivo já tem `_lead`, `_ctx`, `DENTRO_DA_JANELA` e `FUSO`; use-os.

```python
async def test_o_evento_de_maximo_sai_quando_a_quarta_e_gravada(session, caplog) -> None:
    """O criterio de aceite: "um evento registra que o teto foi atingido".

    Lead QUENTE calado ha mais de sete dias, com as tentativas 1, 2 e 3 ja
    gravadas sob a ancora. A quarta vence, e gravar ela fecha o maximo.
    """
    parou_ha = timedelta(days=8)
    await _lead(session, calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    for numero in (1, 2, 3):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                tentativa_numero=numero,
                temperatura="QUENTE",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
            )
        )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 1


async def test_o_evento_de_maximo_nao_sai_na_terceira(session, caplog) -> None:
    """A outra metade da mesma assertiva: emitir cedo e emitir sempre sao
    defeitos diferentes, e um teste so nao separa os dois.

    Mesmo lead, duas tentativas gravadas em vez de tres, e silencio de quatro
    dias -- bastante para a tentativa 3 (+3d) e nao para a 4 (+7d).
    """
    parou_ha = timedelta(days=4)
    await _lead(session, calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    for numero in (1, 2):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                tentativa_numero=numero,
                temperatura="QUENTE",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
            )
        )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 0


async def test_a_guarda_do_maximo_barra_o_candidato(
    session, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A guarda da D5, testada pela fronteira porque a consulta real nao a
    alcanca.

    O `UNIQUE` limita a quatro linhas por ancora e a cadencia do QUENTE para em
    quatro, entao `ja_enviadas=4` implica `ja_disparada=4`, que o corte de
    esgotamento ja exclui da candidatura. O ramo da guarda so tem cobertura se
    o `Candidato` vier construido a mao -- e mockar `candidatos_a_followup` e
    legitimo pelo mesmo motivo que no teste da corrida: a consulta e a
    fronteira, e o que se testa aqui e o tratamento do job.

    `ja_disparada=0` de proposito: sem isso `tentativa_devida` devolveria None e
    o teste passaria pela guarda errada, verde e vazio.
    """
    ancora = DENTRO_DA_JANELA - timedelta(hours=2, minutes=5)
    candidato = Candidato(
        channel=CANAL,
        conversation_key=CONVERSA,
        temperatura=Temperatura.QUENTE,
        ancora_em=ancora,
        ja_disparada=0,
        ja_enviadas=4,
    )

    async def _candidatos_a_followup_stub(session, *, agora, limite=500):
        return [candidato]

    monkeypatch.setattr(
        sweep_followups_module, "candidatos_a_followup", _candidatos_a_followup_stub
    )

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -k "maximo" -v
```

Esperado: os dois primeiros falham na assertiva do evento (nenhum `followup.antispam_atingido` é emitido); o terceiro falha com `TypeError` na construção do `Candidato`, se a Task 2 ainda não estiver no lugar, ou grava a linha e reprova o `gravadas == 0`, se estiver.

- [ ] **Step 3: Implementar a guarda e o evento**

Em `src/mobia/workers/jobs/sweep_followups.py`, acrescente ao import de `outbound`:

```python
from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio
```

Acrescente a segunda lista de eventos, ao lado de `eventos`:

```python
    eventos_de_maximo: list[dict[str, Any]] = []
```

Dentro do laço, **entre** o `if tentativa is None: continue` e a checagem de opt-out:

```python
            # A terceira guarda, e ela entra ANTES do opt-out porque e pura: a
            # premissa que justifica consultar o opt-out por candidato e que o
            # conjunto que sobra depois dos cortes baratos e pequeno.
            #
            # **Esta guarda nao pode disparar pela consulta real hoje**, e isso
            # e declarado, nao esquecido: o UNIQUE limita a quatro linhas por
            # ancora e a cadencia do QUENTE para em quatro, entao
            # `ja_enviadas=4` implica `ja_disparada=4`, que o corte de
            # esgotamento ja excluiu. Ela existe para a TEC-184 (envio de
            # verdade) e a TEC-171 (lembretes) herdarem em vez de precisarem
            # lembrar -- o mesmo motivo pelo qual a guarda de opt-out foi
            # escrita em `GuardedOutbound` antes de existir consumidor.
            if not antispam_permite_envio(ja_enviadas=candidato.ja_enviadas):
                continue
```

Depois do bloco que monta o evento `followup.devido` (ou seja, depois do `eventos.append({...})`), ainda dentro do laço:

```python
            # `==` e nao `>=` porque a guarda acima ja garante
            # `ja_enviadas < MAXIMO_SEM_RESPOSTA`, entao a soma nunca passa do
            # maximo -- e o evento e sobre o INSTANTE em que a contagem fecha.
            #
            # Emitir a cada supressao, em vez de uma vez aqui, repetiria a
            # mesma linha a cada cinco minutos para sempre, porque um lead que
            # nunca responde nunca sai do estado. "Atingir o teto" e um
            # instante; o estado e derivavel da tabela a qualquer momento.
            if candidato.ja_enviadas + 1 == MAXIMO_SEM_RESPOSTA:
                eventos_de_maximo.append(
                    {
                        "channel": candidato.channel,
                        "conversation_key": candidato.conversation_key,
                        "ancora_em": candidato.ancora_em.isoformat(),
                        "ja_enviadas": MAXIMO_SEM_RESPOSTA,
                    }
                )
```

Depois do `await session.commit()`, junto do laço que emite `followup.devido`:

```python
    for evento in eventos_de_maximo:
        # `warning` e nao `info`: nao e erro, mas e um lead saindo do alcance
        # da automacao, que a RN-13.7 quer visivel para a gerente. Mesmo nivel
        # de `followup.candidatos_saturados` e `outbound.optout_bloqueou`, que
        # tambem sao "funcionou como desenhado, e alguem precisa saber".
        log.warning("followup.antispam_atingido", **evento)
```

Acrescente ao docstring da função, antes do fechamento:

```
    **A guarda do maximo (TEC-188, RN-13.7) e a terceira, e entra antes do
    opt-out por ser pura.** Ela conta mensagens que sairam -- `ja_enviadas`, o
    COUNT sob a ancora --, e nao a posicao da regua. Hoje ela nao pode
    disparar pela consulta real: o UNIQUE limita a quatro linhas por ancora e
    o QUENTE para em quatro, entao o maximo coincide com o esgotamento. Ela
    existe para ser herdada pela TEC-184 e pela TEC-171.

    O retorno continua sendo o numero de linhas GRAVADAS. O evento de maximo
    sai numa lista propria e nao entra nessa contagem: gravar e atingir o
    maximo sao fatos diferentes, e somar os dois faria o retorno mentir para
    quem mede a varredura.
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v
```

Esperado: PASS, os novos e os treze que já existiam.

- [ ] **Step 5: Rodar os vizinhos**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py tests/unit/test_antispam.py tests/unit/test_cadencia.py -v
```

- [ ] **Step 6: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 7: Commit**

```bash
git add src/mobia/workers/jobs/sweep_followups.py tests/integration/test_sweep_followups.py
git commit -F - <<'EOF'
feat(TEC-188): o lead que sai do alcance da automacao passa a ter um evento

A guarda do maximo entra como terceira, antes do opt-out por ser pura. Ela
nao pode disparar pela consulta real hoje -- o maximo coincide com o
esgotamento do QUENTE -- e isso esta escrito no comentario dela, nao
escondido: ela existe para a TEC-184 e a TEC-171 herdarem, pelo precedente da
guarda de opt-out.

O evento `followup.antispam_atingido` sai UMA vez, no instante em que a linha
gravada fecha a contagem. A cada supressao, repetiria a mesma linha a cada
cinco minutos para sempre.

O retorno da varredura continua contando linhas gravadas: gravar e atingir o
maximo sao fatos diferentes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: A emenda ao SRS e a verificação final

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (a tabela de emendas no topo; a RN-13.7, hoje na linha 330)

**Interfaces:**
- Consumes: nada.
- Produces: nada em código.

- [ ] **Step 1: A linha na tabela de emendas**

A tabela está ordenada **por data**, e a linha nova é a mais recente, então vai no fim. **Localize a tabela por conteúdo** (procure a linha `| E-01 | RN-13.3 |`), não pelo número de linha — o Step 2 depende de posições que este step desloca.

```markdown
> | E-01 | RN-13.7 | [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188) | 04/09/2026 |
```

- [ ] **Step 2: A emenda aninhada sob a RN-13.7**

Localize a RN-13.7 **por conteúdo** (`Máximo absoluto de 4 mensagens não respondidas`) e insira imediatamente depois dela. A numeração é por regra — há várias `E-01` no documento, uma por regra, e esta não colide com nenhuma.

```markdown
  - **Emenda E-01 (TEC-188, 04/09/2026):** o contador é o **número de linhas de `followups` sob a âncora atual** — a última fala não bloqueada do lead —, e não a posição da última tentativa. A régua da cadência devolve a maior tentativa vencida e pula as intermediárias, então um lead calado há dez dias tem uma única linha com `tentativa_numero = 4`: contar pela posição cortaria da automação um lead que recebeu **uma** mensagem. Duas regras da card caem dessa forma sem código próprio: *"qualquer resposta do lead zera o contador"*, porque a resposta move a âncora e a contagem sob a âncora nova começa em zero; e *"tentativas de ciclos diferentes somam"*, porque o que separa dois ciclos sem o lead falar é a mudança de temperatura, que **não** move a âncora — as tentativas dos dois ciclos ficam sob a mesma âncora e a contagem já as soma. **Consequência declarada:** enquanto o follow-up for a única automação, o máximo de 4 coincide com o teto de tentativas do `QUENTE`, porque a restrição `UNIQUE` admite no máximo quatro linhas por âncora; a guarda não altera envio nenhum hoje e existe para ser herdada pela TEC-184 e pela TEC-171. O efeito observável desta card é o evento `followup.antispam_atingido`, emitido uma vez, no instante em que a contagem fecha. Uma resposta do lead **bloqueada pela moderação** não zera o contador, pela mesma razão que não move a âncora (ver a lacuna 8 do desenho da TEC-183).
```

- [ ] **Step 3: Conferir que nada mais ficou mentindo**

```bash
grep -rn "RN-13.7\|anti-spam\|antispam" docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md src/mobia/domain/followup/ src/mobia/workers/jobs/sweep_followups.py
```

Leia cada acerto e confirme que nenhum afirma que o máximo não existe. A **lacuna 4** do desenho da TEC-183 diz que *"o teto anti-spam da RN-13.7 não é aplicado (TEC-188)"* — isso passou a ser parcialmente falso e precisa ser corrigido, não removido: a guarda existe e não altera comportamento hoje. Corrija-a no mesmo espírito da lacuna 3 daquele documento, que a TEC-185 já corrigiu:

```markdown
4. **O teto anti-spam da RN-13.7** foi implementado pela [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188) (04/09/2026) como guarda e evento, mas **não altera envio nenhum enquanto o follow-up for a única automação** — o máximo de 4 coincide com o teto de tentativas do `QUENTE`. E **`DORMENTE` não é marcado** (RN-13.5, TEC-187): a cadência simplesmente para de disparar quando esgota, sem registrar que esgotou.
```

Se encontrar outra prosa que esta card tornou falsa e que este plano não nomeou, **reporte em vez de reescrever meio repositório**.

- [ ] **Step 4: A verificação final**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -u -m pytest -v
```

A suíte leva cerca de 22 minutos e ~1140 testes. **Não anuncie a card pronta sem os quatro verdes** — evidência antes de afirmação. Se a suíte exceder o seu timeout de foreground, diga isso no relatório em vez de encerrar o turno esperando: quem despachou você roda a suíte e devolve o resultado.

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md
git commit -F - <<'EOF'
docs(TEC-188): a RN-13.7 passa a dizer que o contador e por ancora, e o que ele ainda nao protege

Emenda E-01 a RN-13.7, sem tocar no texto de 22/08: o contador conta linhas
sob a ancora, e nao a posicao da regua. "Resposta zera o contador" e "ciclos
diferentes somam" caem as duas da forma derivada, sem codigo.

Fica declarado no SRS que o maximo coincide hoje com o teto do QUENTE e que a
guarda nao altera envio nenhum -- ela existe para ser herdada.

A lacuna 4 do desenho da TEC-183 e corrigida e nao removida, como a 3 foi na
TEC-185: dizer "nao e aplicado" passou a ser falso, e dizer "esta pronto"
seria pior.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Auto-revisão do plano contra o spec

**Cobertura das oito decisões:**

| Decisão | Onde é implementada |
|---|---|
| D1 — `COUNT`, não `MAX` | Task 2 (Steps 1, 4 e 5) |
| D2 — resposta zera sem código | Task 2, `test_a_resposta_do_lead_zera_o_contador`; Task 4, a emenda |
| D3 — "ciclos somam" é o mesmo `COUNT` | Task 4, a emenda (não precisa de código, que é o ponto) |
| D4 — constante de módulo | Task 1, Step 3, e `test_o_maximo_e_o_numero_da_regra` |
| D5 — a guarda não dispara hoje | Task 3 (comentário e `test_a_guarda_do_maximo_barra_o_candidato`); Task 4 (emenda e lacuna 4) |
| D6 — evento uma vez | Task 3, os dois testes do evento |
| D7 — nome `antispam` | Global Constraints; Tasks 1 e 3 |
| D8 — predicado espelha a janela | Task 1, Step 3 |

**Cobertura dos critérios de aceite da card:**

| Cenário | Onde |
|---|---|
| Quarta mensagem encerra a automação, com evento | Task 3, `test_o_evento_de_maximo_sai_quando_a_quarta_e_gravada` (o evento) e `test_a_guarda_do_maximo_barra_o_candidato` (o barramento) |
| Resposta zera o contador | Task 2, `test_a_resposta_do_lead_zera_o_contador` |
| Soma tentativas de ciclos diferentes | Coberto pela forma: a mudança de temperatura não move a âncora, então o `COUNT` já soma. Registrado na emenda |
| O teto prevalece sobre a configuração | Task 1, `test_o_maximo_e_o_numero_da_regra_e_nao_o_da_cadencia` — é o que impede o número de virar derivado |
| Lembrete de visita respeita o teto | **Não coberto, e declarado**: TEC-171 não existe, nem o lembrete nem a tarefa para o corretor |

**Consistência de nomes e tipos:** `antispam_permite_envio(*, ja_enviadas: int) -> bool` e `MAXIMO_SEM_RESPOSTA` são idênticos entre a Task 1 (definição) e a Task 3 (uso). `Candidato.ja_enviadas: int` é idêntico entre a Task 2 (definição), a Task 3 (uso no laço e no teste que constrói o `Candidato` à mão) e o SQL (`AS ja_enviadas` → `linha.ja_enviadas`). O evento `followup.antispam_atingido` tem o mesmo nome no código da Task 3, nos dois testes e na emenda da Task 4.

**Placeholders:** nenhum. A primeira versão deste plano deixava dois blocos `...` na Task 2 com uma justificativa ("os helpers já existem, copiá-los seria duplicação"). Era racionalização: os helpers de `test_followups_model.py` — `_linha`, `_qualificacao`, `_fala_do_lead`, `ANCORA`, `AGORA` — bastavam para escrever os dois testes por extenso, e agora estão. Nenhum "similar à Task N", nenhum step de código sem bloco de código.
