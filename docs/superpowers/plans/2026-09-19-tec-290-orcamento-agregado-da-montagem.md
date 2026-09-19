# TEC-290 — Orçamento agregado da montagem: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar a `montar_contexto` um deadline agregado para a fase inteira de resumir/contar, de modo que o pior turno volte a caber no `job_timeout` e pare de crescer com a configuração da montagem.

**Architecture:** Um campo novo em `Settings` (`contexto_deadline_de_montagem_segundos = 35.0`) governa um `asyncio.timeout` que envolve, dentro de `montar_contexto`, só a fase que fala com o modelo. No estouro, o contexto é reduzido por um truncamento que não fala com o provedor e cuja estimativa de tokens é pessimista. Em `infra/anthropic.py`, as duas fatias variáveis do pior turno (`count_tokens` e `resumir`) saem de `_pior_turno()` e dão lugar ao deadline, somado **fora** do multiplicador de retentativas.

**Tech Stack:** Python 3.13, pytest (+ pytest-xdist), pydantic-settings, structlog, SDK `anthropic`, ARQ.

**Spec:** `docs/superpowers/specs/2026-09-19-tec-290-orcamento-agregado-da-montagem-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/` e `.md`: com acento. Valor citado dentro de comentário segue o valor, não a convenção do comentário.
- **Mensagem de commit:** `tipo(TEC-290): o que passou a ser verdade`, assunto em português sem acento. Toda mensagem termina com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Números que não podem ser transcritos em prosa:** o teto do orçamento do prompt vive só no corpo de `test_a_margem_do_orcamento_do_prompt_e_deliberada`. Esta branch não o toca.
- **Valores de hoje que o plano usa:** `contexto_teto_de_tokens = 12000`, `contexto_headroom_de_tokens = 1060` (logo `teto_de_tokens_efetivo = 10940`), `contexto_literais_minimas = 20`, `contexto_max_iteracoes = 3`, `contexto_gatilho_de_regeneracao = 40`, `MAX_TENTATIVAS = 0`, `job_timeout = 240`.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, sem Docker). As Tasks 1 e 2 tocam `tests/integration/`, que exige `docker compose` de pé.

---

### Task 1: A estimativa pessimista e o truncamento sem modelo

Fundação das Tasks seguintes. **Não muda comportamento nenhum do caminho normal** — só acrescenta um modo que ninguém liga ainda.

**Files:**
- Modify: `src/mobia/domain/context/montagem.py` (imports; depois de `_estimar`, por volta da linha 271; `_contar_se_valer`; `_truncar_ate_caber`)
- Test: `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: `_estimar(resumo, literais, estado) -> int`, `_texto_das`, `_texto_do_estado`, `SISTEMA` — todos já existem.
- Produces:
  - `_estimar_pessimista(resumo: str | None, literais: list[Message], estado: LeadQualification | None) -> int`
  - `_contar_se_valer(contador, resumo, literais, estado, *, sem_modelo: bool = False) -> int`
  - `_truncar_ate_caber(contador, channel, texto_do_resumo, literais, estado, tokens, teto, *, sem_modelo: bool = False) -> tuple[str | None, list[Message], int]`

- [ ] **Step 1: Escrever os dois testes que falham**

Em `tests/integration/test_montagem.py`, acrescente ao bloco de import de `mobia.domain.context.montagem` os nomes `_estimar`, `_estimar_pessimista` e `SISTEMA` (se algum já estiver lá, não duplique), e ponha os dois testes logo ANTES de `test_truncar_reduz_pela_metade_em_vez_de_pular_direto_para_uma`:

```python
class ContadorProibido:
    """Um contador que falha se alguem o chamar.

    Existe para o modo sem modelo: o ponto dele e nao pagar round trip
    nenhum, e um contador que apenas devolve um numero nao distingue "nao
    chamou" de "chamou e coube".
    """

    async def contar(self, texto: str) -> int:
        raise AssertionError("o modo sem modelo nao pode falar com o provedor")


def test_a_estimativa_sem_modelo_supoe_o_piso_de_caracteres_por_token() -> None:
    """No modo sem modelo a estimativa e a palavra final, entao ela erra para cima.

    `_estimar` supoe 4 caracteres por token, e o portugues acentuado roda a
    3,2-3,7 (ver `Settings.limiar_de_contagem_efetivo`): ela SUBCONTA. No
    caminho normal isso e inofensivo, porque o limiar so a deixa responder
    onde errar nao muda a decisao. Aqui ela decide sozinha, e subcontar seria
    dizer "cabe" com um texto que estoura.

    O teste afirma a PROPRIEDADE -- a razao de caracteres por token implicita
    fica no piso documentado -- e nao a formula, que seria copiar a
    implementacao para o teste.
    """
    literais = [_mensagem_literal(corpo="x" * 4000)]
    bruto = len(SISTEMA) + len(_texto_das(literais)) + len(_texto_do_estado(None))

    pessimista = _estimar_pessimista(None, literais, None)

    assert bruto / pessimista <= 3.2
    assert pessimista > _estimar(None, literais, None)


async def test_o_truncamento_sem_modelo_corta_sem_falar_com_o_provedor() -> None:
    """O fallback do deadline nao pode pedir ao modelo justamente quando o tempo dele acabou.

    `_truncar_ate_caber` conta a cada volta, e `_contar_se_valer` paga um
    round trip acima do limiar. Chamado do estouro do deadline, isso seria
    gastar a chamada que nao ha mais tempo de fazer.
    """
    literais = [_mensagem_literal(corpo="x" * 4000) for _ in range(8)]
    teto = get_settings().teto_de_tokens_efetivo

    resumo, restantes, tokens = await _truncar_ate_caber(
        ContadorProibido(),
        CANAL,
        "resumo qualquer",
        literais,
        None,
        _estimar_pessimista("resumo qualquer", literais, None),
        teto,
        sem_modelo=True,
    )

    assert len(restantes) < 8, "a janela tinha de encolher"
    assert tokens <= teto
    assert resumo == "resumo qualquer", "coube cortando literais; o resumo nao precisou cair"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py -k "sem_modelo or piso_de_caracteres" --tb=short
```

Esperado: `ImportError`/`AttributeError` em `_estimar_pessimista`, e `TypeError: unexpected keyword argument 'sem_modelo'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/context/montagem.py`, acrescente `import math` como primeira linha do arquivo (antes de `from dataclasses import dataclass`).

Logo depois de `_estimar` (que **não muda**), acrescente:

```python
# O piso de caracteres por token que `Settings.limiar_de_contagem_efetivo`
# documenta: portugues acentuado roda a 3,2-3,7, e `_estimar` supoe 4.
#
# No caminho normal essa diferenca e coberta pelo limiar, cuja razao de ser e
# deixar a estimativa responder so onde errar nao muda a decisao. No modo sem
# modelo ela e a palavra final, e ai a mesma diferenca vira o defeito: dizer
# "cabe" sobre um texto que estoura.
#
# O que este piso NAO cobre continua sendo o que o limiar ja declara -- emoji
# (~0,3-0,5 chars/token) e blobs base64/URL (~2). Um turno dominado por
# qualquer um dos dois sai subcontado aqui como sai la. Risco aceito e
# documentado, nao defeito escondido.
_CHARS_POR_TOKEN_NO_PIOR_CASO = 3.2

# Derivado dos dois numeros acima, e nao escrito como 1.25: o fator existe
# porque `_estimar` supoe 4 e o piso e 3,2. Escrever o produto esconderia de
# onde ele vem, e mudaria de significado em silencio se um dos dois mudasse.
_FATOR_PESSIMISTA = 4 / _CHARS_POR_TOKEN_NO_PIOR_CASO


def _estimar_pessimista(
    resumo: str | None, literais: list[Message], estado: LeadQualification | None
) -> int:
    """A estimativa de `_estimar` corrigida para errar para cima.

    Usada so pelo modo sem modelo. Cortar literais a mais num caminho que ja
    e degradacao declarada e a direcao segura do erro; devolver contexto
    acima do teto nao e.
    """
    return math.ceil(_estimar(resumo, literais, estado) * _FATOR_PESSIMISTA)
```

Em `_contar_se_valer`, troque a assinatura e acrescente a saída antecipada como PRIMEIRA linha do corpo, depois da docstring:

```python
async def _contar_se_valer(
    contador: ContadorPort,
    resumo: str | None,
    literais: list[Message],
    estado: LeadQualification | None,
    *,
    sem_modelo: bool = False,
) -> int:
```

```python
    # O modo sem modelo nao consulta o limiar: ele nao esta escolhendo entre a
    # estimativa e a contagem, esta declarando que a contagem nao esta
    # disponivel. Ver `_estimar_pessimista`.
    if sem_modelo:
        return _estimar_pessimista(resumo, literais, estado)

    settings = get_settings()
```

Em `_truncar_ate_caber`, troque a assinatura e repasse o modo nas TRÊS chamadas a `_contar_se_valer` que ela faz (a do laço e as duas de fora dele):

```python
async def _truncar_ate_caber(
    contador: ContadorPort,
    channel: str,
    texto_do_resumo: str | None,
    literais: list[Message],
    estado: LeadQualification | None,
    tokens: int,
    teto: int,
    *,
    sem_modelo: bool = False,
) -> tuple[str | None, list[Message], int]:
```

```python
        tokens = await _contar_se_valer(
            contador, texto_do_resumo, literais, estado, sem_modelo=sem_modelo
        )
```

Acrescente ao fim da docstring de `_truncar_ate_caber`:

```
    `sem_modelo` existe para o estouro do deadline de `montar_contexto`:
    contar aqui pagaria um round trip ao provedor no unico momento em que
    ja se sabe que nao ha tempo para ele.
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py --tb=short
```

Esperado: tudo verde, incluindo os dezesseis testes que usam `sempre_contar` — o default `sem_modelo=False` preserva o caminho antigo.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/context/montagem.py tests/integration/test_montagem.py
git commit -m "feat(TEC-290): a montagem sabe truncar sem falar com o provedor

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: O deadline agregado em `montar_contexto`

**Files:**
- Modify: `src/mobia/app/config.py` (perto de `contexto_max_iteracoes`, linha ~267)
- Modify: `src/mobia/domain/context/montagem.py` (`montar_contexto`, corpo a partir de `if deve_regenerar(...)`)
- Test: `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: `_estimar_pessimista`, `_truncar_ate_caber(..., sem_modelo=True)` e a classe de teste `ContadorProibido`, todos da Task 1.
- Produces: `Settings.contexto_deadline_de_montagem_segundos: float` (env `CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS`), consumido pela Task 3.

**Já importado em `tests/integration/test_montagem.py`, não reimporte:** `ResumoGerado`, `get_sessionmaker`, `CANAL`, `CONVERSA`, e `semear` (que vem de `conftest` como função, não como fixture — chame `await semear(session, 45)` sem recebê-la por parâmetro). **Falta** `import asyncio`.

- [ ] **Step 1: Escrever os dois testes que falham**

No fim de `tests/integration/test_montagem.py`. Acrescente `import asyncio` ao topo do arquivo se não houver:

```python
class ResumidorQueTrava:
    """Um resumidor que nunca devolve, e que avisa quando entrou.

    O aviso (`entrou`) e o que torna o teste de cancelamento deterministico:
    sem ele, `tarefa.cancel()` pode chegar antes de a corrotina alcancar o
    await do provedor, e o teste passaria sem exercitar nada.
    """

    def __init__(self) -> None:
        self.entrou = asyncio.Event()
        self.chamadas: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.chamadas.append(instrucao)
        self.entrou.set()
        await asyncio.Event().wait()
        raise AssertionError("inalcancavel")


async def test_deadline_estourado_degrada_em_vez_de_esperar(
    session, caplog, sempre_contar, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fase inteira tem relogio proprio, e estourar nao pode devolver contexto acima do teto.

    E o ponto da TEC-290: teto por requisicao nao limita uma fase que faz N
    requisicoes. Com o resumidor travado, so o deadline termina o turno.

    O contador e o `ContadorProibido`: depois do estouro nao pode haver
    round trip nenhum, e um contador que responde nao distinguiria
    "nao chamou" de "chamou e coube".
    """
    monkeypatch.setenv("CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS", "0.05")
    get_settings.cache_clear()
    await semear(session, 45)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorQueTrava(),
        contador=ContadorProibido(),
    )

    assert contexto.degradado is True
    assert contexto.tokens <= get_settings().teto_de_tokens_efetivo
    assert "contexto.deadline_estourado" in caplog.text


async def test_cancelamento_de_fora_nao_vira_degradacao(
    session, sempre_contar, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `CancelledError` do `job_timeout` atravessa a fase inteira.

    E o contrato que a TEC-227 construiu: quem tem de receber o cancelamento
    e a clausula de `process_message`, que marca FAILED, incrementa
    `attempts` e loga `message.cancelled`. Engoli-lo aqui devolveria a
    mensagem perdida em silencio que aquela card veio acabar.

    O deadline e folgado de proposito: se ele disparasse antes do
    `cancel()`, o teste passaria pela razao errada.
    """
    monkeypatch.setenv("CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS", "30")
    get_settings.cache_clear()
    await semear(session, 45)
    resumidor = ResumidorQueTrava()

    tarefa = asyncio.create_task(
        montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=ContadorProibido(),
        )
    )
    await resumidor.entrou.wait()
    tarefa.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarefa
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py -k "deadline or cancelamento_de_fora" --tb=short
```

Esperado: o primeiro trava até o timeout do pytest ou falha por `ContadorProibido`; o segundo falha porque nada segura o cancelamento. **Se o primeiro travar sem retorno, é sinal correto** — não há deadline nenhum ainda.

- [ ] **Step 3: Implementar a configuração**

Em `src/mobia/app/config.py`, logo depois de `contexto_max_iteracoes`:

```python
    # TEC-290. O relogio da fase inteira de resumir/contar, e nao o teto de
    # uma chamada: os tetos por chamada vivem em `infra/anthropic.py` e nao
    # limitam um laco que faz N chamadas. Enquanto o pior caso era somado
    # requisicao a requisicao, ele crescia com `contexto_max_iteracoes` acima
    # -- e foi assim que a soma do turno chegou a 327s contra um
    # `job_timeout` de 240.
    #
    # 35s nao e medida da montagem: e o que sobra do `job_timeout` depois das
    # outras fatias do turno e da reserva de 30s do banco. O teto duro e 38s.
    # A conta inteira mora em `tests/unit/test_orcamento_do_turno.py`, que e o
    # unico lugar que enxerga os quatro clientes externos juntos.
    #
    # Estourar aqui NAO e falha: o turno segue com o contexto truncado sem
    # falar com o provedor (`_estimar_pessimista`), o lead recebe resposta, e
    # `contexto.deadline_estourado` registra. E a diferenca em relacao a um
    # teto por chamada, que vira erro tipado.
    contexto_deadline_de_montagem_segundos: float = 35.0
```

- [ ] **Step 4: Implementar o deadline**

Em `src/mobia/domain/context/montagem.py`, acrescente `import asyncio` no topo (antes de `import math`).

Em `montar_contexto`, **mova** a atribuição de `teto` (com o comentário dela) para antes da fase, e envolva da dobra por acúmulo até o fim do `while`. O corpo fica assim, do `marca_atual = marca_de(resumo_atual)` até o `return`:

```python
    marca_atual = marca_de(resumo_atual)

    # Teto ja com a reserva descontada: o contador mede um proxy menor que a
    # requisicao real da TEC-134 -- ver `Settings.teto_de_tokens_efetivo`.
    #
    # Fica ANTES do deadline porque o caminho degradado tambem precisa dele, e
    # calcula-lo la dentro o deixaria indisponivel no unico ramo que nao
    # chegou ao fim.
    teto = settings.teto_de_tokens_efetivo

    # O relogio da fase inteira (TEC-290). As leituras de banco acima ficam de
    # FORA de proposito: elas pertencem a reserva de banco do orcamento, e
    # inclui-las faria uma lentidao de Postgres consumir tempo de modelo.
    #
    # `asyncio.timeout` aqui e o segundo do repo, e o primeiro fora do
    # pos-cancelamento (o outro e `SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO`, em
    # `workers/jobs/process_message.py`). O padrao da casa para prazo normal e
    # o `timeout=` do SDK por chamada -- que e exatamente o que nao resolve
    # este caso, porque a fase faz N chamadas.
    try:
        async with asyncio.timeout(settings.contexto_deadline_de_montagem_segundos):
            # Gatilho por acumulo: quarenta literais dobram as vinte mais antigas e
            # deixam vinte. Por proximidade, a marca colaria no presente.
            if deve_regenerar(len(literais), settings.contexto_gatilho_de_regeneracao):
                texto_do_resumo, literais, cobertas, marca_atual, falhou = await _dobrar(
                    session_factory,
                    channel,
                    conversation_key,
                    resumidor,
                    texto_do_resumo,
                    literais,
                    cobertas,
                    marca_atual,
                    INSTRUCAO_DOBRAR,
                )
                degradado = degradado or falhou

            tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)

            iteracao = 0
            ja_comprimiu = False
            while tokens > teto:
                ...  # o corpo do laco nao muda, so a indentacao
    except TimeoutError:
        # So `TimeoutError`. O `CancelledError` do `job_timeout` do ARQ e
        # `BaseException` e continua propagando: quem tem de recebe-lo e a
        # clausula de `process_message` da TEC-227, que marca FAILED e conta a
        # tentativa. Engoli-lo aqui devolveria a perda silenciosa que aquela
        # card acabou.
        degradado = True
        log.warning(
            "contexto.deadline_estourado",
            channel=channel,
            deadline_s=settings.contexto_deadline_de_montagem_segundos,
            literais=len(literais),
        )
        # Recontado aqui, e nao herdado do laco: o estouro pode cair antes de
        # `tokens` receber valor algum, e um `tokens` zerado faria o
        # truncamento decidir que ja cabe.
        tokens = _estimar_pessimista(texto_do_resumo, literais, estado)
        texto_do_resumo, literais, tokens = await _truncar_ate_caber(
            contador, channel, texto_do_resumo, literais, estado, tokens, teto, sem_modelo=True
        )

    return ContextoMontado(
        sistema=SISTEMA,
        resumo=texto_do_resumo,
        literais=literais,
        estado=estado,
        tokens=tokens,
        degradado=degradado,
    )
```

O corpo do `while` é reaproveitado **sem mudança de conteúdo** — só recebe um nível a mais de indentação. Os quatro `break` e as quatro chamadas a `_truncar_ate_caber` de dentro dele continuam como estão, **sem** `sem_modelo`: lá dentro ainda há tempo.

- [ ] **Step 5: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py tests/features/test_janela_de_contexto.py --tb=short
```

Esperado: verde. Se algum dos dezessete testes de `sempre_contar` ficar vermelho, é indentação mal aplicada no `while`, não o deadline.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/app/config.py src/mobia/domain/context/montagem.py tests/integration/test_montagem.py
git commit -m "feat(TEC-290): a fase de montagem tem relogio proprio

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: O pior turno passa a contar o deadline, e a conta fecha

É aqui que os dois `xfail(strict=True)` viram XPASS e saem.

**Files:**
- Modify: `src/mobia/infra/anthropic.py` (`import math`, `_pior_turno`, `segundos_do_modelo_no_pior_turno`)
- Test: `tests/unit/test_orcamento_do_turno.py`

**Interfaces:**
- Consumes: `Settings.contexto_deadline_de_montagem_segundos` da Task 2.
- Produces: `segundos_do_modelo_no_pior_turno() -> float`, agora 167.0 com os valores de hoje.

- [ ] **Step 1: Reescrever os testes do orçamento**

Em `tests/unit/test_orcamento_do_turno.py`:

1. **Remova** os dois decoradores `@pytest.mark.xfail(...)` de `test_o_pior_turno_cabe_no_job_timeout` e `test_a_folga_paga_o_banco`, e os parágrafos das docstrings deles que falam do `xfail` (o resto das docstrings fica).
2. **Remova** o bloco de comentário sobre o orçamento congelado, as constantes `SOMA_DE_HOJE_SEGUNDOS` e `JOB_TIMEOUT_DE_HOJE`, e o teste `test_o_orcamento_estourado_nao_piora` inteiro. A razão está escrita no próprio comentário: eles saem "quando a TEC-290 devolver a guarda ao derivado".
3. **Substitua** `test_o_pior_turno_segue_contexto_max_iteracoes` e `test_o_pior_turno_segue_o_gatilho_de_regeneracao` pelos três testes abaixo.
4. **Ajuste os imports:** `TETO_DO_COUNT_TOKENS` e `TETO_DO_RESUMO` deixam de ser usados neste arquivo e saem do bloco de import. Acrescente `import mobia.infra.anthropic as anthropic` — o `monkeypatch.setattr` precisa do módulo, porque `segundos_do_modelo_no_pior_turno` lê o global e não a ligação importada. **`MAX_TENTATIVAS` importado por nome provavelmente fica sem uso** depois da remoção dos dois testes de derivação: deixe o `ruff check` decidir e tire-o se ele apontar `F401`. Não invente um uso para salvar o import.

```python
def test_o_pior_turno_nao_cresce_mais_com_contexto_max_iteracoes(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Este teste afirmava o CONTRARIO ate a TEC-290, e a inversao e o entregavel.

    Ate aqui, `_pior_turno` somava uma dobra e uma contagem por volta do laco
    de `montar_contexto`, entao subir o teto de iteracoes movia o pior caso --
    e era isso que impedia a conta de fechar, porque ela crescia com uma
    configuracao que ninguem lia pensando em orcamento.

    Com o deadline agregado, a fase inteira custa o relogio dela, quantas
    voltas der. Apagar este teste em vez de inverte-lo deixaria a
    propriedade que a card comprou sem nada guardando.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv("CONTEXTO_MAX_ITERACOES", str(get_settings().contexto_max_iteracoes + 1))
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() == antes


def test_o_pior_turno_nao_cresce_mais_com_o_gatilho_de_regeneracao(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Mesma inversao, pelo outro caminho.

    O gatilho governava o termo `log2` das contagens de `_truncar_ate_caber`.
    O truncamento continua existindo e continua contando -- so que agora
    dentro do relogio da fase, e nao somado por fora dele.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_GATILHO_DE_REGENERACAO",
        str(get_settings().contexto_gatilho_de_regeneracao * 2),
    )
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() == antes


def test_o_deadline_da_montagem_entra_uma_vez_e_nao_por_tentativa(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O deadline e relogio de fase; as outras fatias sao teto por requisicao.

    Uma retentativa repete uma REQUISICAO dentro da fase, e a fase ja esta
    limitada pelo relogio -- multiplicar o deadline por tentativa contaria
    duas vezes o que o relogio conta uma.

    Com `MAX_TENTATIVAS = 0` a diferenca e invisivel, e e por isso que este
    teste mexe na constante: sem isso ele passaria com a implementacao errada.
    """
    deadline = get_settings().contexto_deadline_de_montagem_segundos
    sem_retentativa = segundos_do_modelo_no_pior_turno()

    monkeypatch.setattr(anthropic, "MAX_TENTATIVAS", 1)

    assert segundos_do_modelo_no_pior_turno() == (sem_retentativa - deadline) * 2 + deadline


def test_o_pior_turno_segue_o_deadline_da_montagem(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """A derivacao nao sumiu, mudou de dono: quem move o pior caso agora e o deadline.

    Sem este teste, a inversao dos dois acima deixaria `_pior_turno` livre
    para voltar a ser constante -- que e exatamente o que a TEC-229 tinha
    acabado de impedir.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS",
        str(get_settings().contexto_deadline_de_montagem_segundos + 10),
    )
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() - antes == 10
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_orcamento_do_turno.py --tb=short
```

Esperado: os quatro novos falham (o pior caso ainda cresce com as iterações), e `test_o_pior_turno_cabe_no_job_timeout`/`test_a_folga_paga_o_banco` falham de verdade agora que o `xfail` saiu — 327s contra 240s.

- [ ] **Step 3: Implementar**

Em `src/mobia/infra/anthropic.py`:

1. **Remova** `import math` (linha 1) — depois desta mudança não há mais uso de `math` no arquivo, e o ruff reprova import não usado.
2. Substitua o bloco de comentário acima de `_pior_turno` a partir do parágrafo `# **E duas fatias custam N requisicoes, derivadas da configuracao (TEC-229).**` por:

```python
# **E a montagem nao custa requisicoes: custa o relogio dela (TEC-290).** A
# versao anterior contava `resumir` e `count_tokens` volta a volta do laco de
# `montar_contexto`, o que estava certo sobre o grafo de chamadas e errado
# sobre o que limita a fase: o pior caso crescia com `contexto_max_iteracoes`,
# e a soma do turno chegou a 327s contra um `job_timeout` de 240.
#
# Agora `montar_contexto` tem um deadline agregado
# (`Settings.contexto_deadline_de_montagem_segundos`), e as duas fatias saem
# desta tupla -- que passa a listar so o que e limitado por requisicao. O
# deadline entra em `segundos_do_modelo_no_pior_turno`, fora do multiplicador
# de tentativas, pela razao escrita la.
```

3. Substitua `_pior_turno` e `segundos_do_modelo_no_pior_turno` por:

```python
def _pior_turno() -> tuple[tuple[float, int], ...]:
    """As fatias do turno limitadas POR REQUISICAO, e quantas cada uma faz.

    Constante de novo desde a TEC-290, e desta vez sem esconder nada: a fatia
    que dependia de `Settings` saiu daqui para virar o deadline agregado da
    montagem. O que sobrou nao depende de configuracao nenhuma.
    """
    return (
        (TETO_DA_REACAO, 1),
        (TETO_DA_CLASSIFICACAO, 2),
        (TETO_DO_INVESTIDOR, 2),
    )


def segundos_do_modelo_no_pior_turno() -> float:
    """O teto de tempo que um turno pode gastar falando com ESTE provedor.

    Existe para entrar na soma de `tests/unit/test_orcamento_do_turno.py`, que
    a compara com o `job_timeout` do worker.

    **Sao duas parcelas com naturezas diferentes, e por isso a conta nao e uma
    soma so.** As requisicoes de `_pior_turno()` tem teto POR REQUISICAO, e
    uma retentativa as repete -- por isso o multiplicador. A montagem tem um
    relogio de FASE, e uma retentativa dentro dela ja esta limitada por esse
    relogio: multiplica-lo contaria duas vezes o que ele conta uma.

    **E so a parcela da Anthropic, e o nome diz isso de proposito.** O turno
    paga outros tres clientes externos -- o embed da busca (`infra/embeddings.py`),
    a moderacao das duas pontas e o POST para a Meta --, alem do banco. Quem
    somar so esta funcao contra os 240s conclui que ha folga de sobra, que foi
    exatamente o erro do comentario que a TEC-228 encontrou. A soma inteira
    mora no teste.
    """
    por_requisicao = sum(teto * requisicoes for teto, requisicoes in _pior_turno())
    return por_requisicao * (MAX_TENTATIVAS + 1) + (
        get_settings().contexto_deadline_de_montagem_segundos
    )
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_orcamento_do_turno.py -v --tb=short
```

Esperado: tudo PASS, **nenhum XPASS e nenhum XFAIL**. Confira o número:

```bash
./.venv/Scripts/python.exe -c "from mobia.infra.anthropic import segundos_do_modelo_no_pior_turno as s; print(s())"
```

Esperado: `167.0`. Com os outros três clientes (40s), a soma é 207s e a folga sobre os 240s é 33s.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/infra/anthropic.py tests/unit/test_orcamento_do_turno.py
git commit -m "feat(TEC-290): o orcamento do turno fecha, com 33s de folga

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A prosa que passou a mentir

Sem código novo. É o gate que este repo não tem: nenhum dos três estáticos olha para comentário.

**Files:**
- Modify: `src/mobia/workers/main.py` (comentário de `job_timeout`, linhas ~211-278)
- Modify: `src/mobia/infra/anthropic.py` (comentário de `MAX_TENTATIVAS`, linhas ~23-41)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (abaixo da Emenda E-01 da RN-09.4, linha ~306)

- [ ] **Step 1: A tabela do `job_timeout`**

Em `src/mobia/workers/main.py`, substitua o bloco que começa em `# **Hoje a conta NAO fecha, e este numero e o que nao cabe.**` e termina antes de `# Estourar aqui nao e so custo:` por:

```python
    # **A conta fecha desde a TEC-290, e com reserva de banco de pe.** A
    # TEC-229 corrigiu o grafo e a soma foi a 327s: `montar_contexto` chama
    # `resumir` e `count_tokens` dentro de um laco que roda ate
    # `contexto_max_iteracoes`, e o pior caso crescia junto com essa
    # configuracao. A TEC-290 deu a fase um deadline agregado
    # (`Settings.contexto_deadline_de_montagem_segundos`), e ela parou de
    # crescer. Com os valores de hoje:
    #
    #   167s  Anthropic (`segundos_do_modelo_no_pior_turno`), dos quais
    #          35s sao o deadline da fase de montagem, uma vez so
    #    20s  embed da busca, 2 buscas x 10s, sem retentativa
    #    10s  moderacao das duas pontas
    #    10s  POST para a Meta
    #   ----
    #   207s  contra estes 240 -- folga de 33s, acima dos 30 reservados ao banco
    #
    # `test_o_pior_turno_cabe_no_job_timeout` e `test_a_folga_paga_o_banco`
    # montam essa soma importando cada termo do modulo dele; e onde a conta
    # INTEIRA esta escrita -- cada modulo so conhece a propria parcela, e foi
    # somar uma parcela achando que era o todo que produziu o 360s de tres
    # versoes atras deste comentario.
    #
    # **A folga e de 33s contra um minimo de 30, e isso e apertado de
    # proposito.** Subir qualquer teto por chamada reabre a conta. A TEC-290
    # escolheu o deadline agregado entre tres caminhos justamente para nao
    # mexer neste numero: subi-lo exigiria subir
    # `sweep_inflight_after_seconds` junto, e com ele a carencia
    # SIGTERM->SIGKILL exigida do deploy, que nao mora neste repo. Ver
    # `docs/superpowers/specs/2026-09-19-tec-290-orcamento-agregado-da-montagem-design.md`.
```

- [ ] **Step 2: O comentário de `MAX_TENTATIVAS`**

Em `src/mobia/infra/anthropic.py`, no comentário de `MAX_TENTATIVAS`, troque o segundo parágrafo por:

```python
# Zero, e a razao esta na aritmetica logo abaixo: a parcela da Anthropic no
# pior turno e 167s (`segundos_do_modelo_no_pior_turno`) contra um
# `job_timeout` de 240s, e a folga inteira do turno e de 33s. Com uma
# retentativa, as fatias por requisicao dobrariam -- 132s viram 264s -- e
# sozinhas ja estourariam o `job_timeout`.
```

O resto do comentário (a medição, o que se perde, o 429) **não muda**: o argumento nunca foi o número, foi a forma da conta.

- [ ] **Step 3: (removido)**

A docstring de cabeçalho de `tests/unit/test_orcamento_do_turno.py` saiu do escopo desta task e foi para a Task 3, junto com a docstring de `test_o_pior_turno_cabe_no_job_timeout`. **Ruling do controlador, durante a execução:** quem falsifica a prosa de um arquivo conserta a prosa daquele arquivo, na mesma task. A Task 4 fica com os arquivos que só ela toca. Não edite `tests/unit/test_orcamento_do_turno.py` aqui.

- [ ] **Step 4: A emenda ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, logo **abaixo** da linha da `Emenda E-01 (TEC-161, 09/09/2026)` sob a RN-09.4, acrescente (mesma indentação de dois espaços, prosa COM acento):

```markdown
  - **Emenda E-02 (TEC-290, 19/09/2026):** a Emenda E-01 acima descarta a segunda geração com três argumentos, e o segundo deles — *"dentro de um `job_timeout` de 240 s que o pior caso das chamadas atuais já estoura"* — **deixou de ser verdade**. O pior caso do turno voltou a caber: são 207 s contra 240 s, com 33 s de folga, desde que a fase de montagem passou a ter um deadline agregado em vez de somar teto por requisição. **A E-01 não cai junto:** a segunda geração continua descartada, agora porque gasta uma folga que voltou a ser escassa — 33 s sobre um mínimo de 30 — e não porque estoura. Os outros dois argumentos da E-01 (a moderação de saída já barra e substitui sem regerar; a ficha montada por código entrega imóveis corretos sem a prosa) seguem intactos e são os que sustentam a regra. Ver `docs/superpowers/specs/2026-09-19-tec-290-orcamento-agregado-da-montagem-design.md`.
```

- [ ] **Step 5: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reconfira cada `ALTERADO` e cada `VIZINHO` dentro de `montar_contexto`, `_truncar_ate_caber`, `_contar_se_valer`, `_pior_turno` e `segundos_do_modelo_no_pior_turno`. Atenção especial aos `VIZINHO`: são os que ninguém editou e que por isso não aparecem no diff — é a categoria que pegou o defeito da TEC-146. Se a saída resumir com `... +N omitida(s)`, rode `--tudo`.

Qualquer `FALSO` **afirma**, não suspeita: conserte antes de seguir.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add -A
git commit -m "docs(TEC-290): a prosa do orcamento volta a dizer que a conta fecha

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A suíte inteira, uma vez

- [ ] **Step 1: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

**Peça `--tb=short` desde o início.** A regra é uma execução só; jogar fora o traceback da única que você fez é o desperdício caro.

- [ ] **Step 2: Ler o resultado pelas regras da casa**

- **Centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`:** não é a branch. Espere e retente, ou baixe o `-n`.
- **Compose reportando `unhealthy` e `CannotConnectNowError` aos montes:** o Postgres caiu sob o paralelismo. `docker compose restart postgres` e rode **por blocos** (`tests/unit`, `tests/integration`, `tests/features`), não repita o `-n 8`.
- **`relation ... does not exist` em dezenas de testes:** quase nunca é migration. São os bancos dos workers com `alembic_version` adiantado. Confirme conectando num deles antes de mexer em código.
- **Falha isolada em `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` ou `test_optout_repositorio.py`:** rode o arquivo sozinho antes de culpar a mudança.
- **Falha que não é nenhum dos acima:** repita sobre a mesma árvore. A segunda execução é ferramenta de diagnóstico, e é o que separa flake de regressão.

- [ ] **Step 3: Guardar o hash junto com o resultado**

```bash
git rev-parse --short HEAD
```

---

### Task 6: Push, PR e a card

- [ ] **Step 1: Push e PR**

```bash
git push -u origin feat/tec-290-orcamento-agregado-da-montagem
```

Corpo do PR (`gh pr create --base main --title "feat(TEC-290): o orcamento do turno fecha por deadline agregado na montagem" --body-file`):

```markdown
A TEC-229 corrigiu o grafo de chamadas do turno e a conta deixou de fechar: 327 s contra um `job_timeout` de 240. Este PR fecha, em 207 s, com 33 s de folga sobre os 30 reservados ao banco.

## A escolha, com os três caminhos medidos

A card lista três sem recomendar. Medidos:

| variante | soma | folga | fecha? |
| --- | --- | --- | --- |
| hoje | 327s | −87s | não |
| **2** — `contexto_max_iteracoes` 3→0 (desliga o laço) | 237s | 3s | não |
| **2** — o acima + cortes em `classificar` e `investidor` | 164s | 76s | sim |
| **3** — deadline agregado de 35s (**escolhido**) | 207s | 33s | sim |
| **1** — `job_timeout` 360, sweep 420 | 327s | 33s | sim |

O caminho 2 sozinho não fecha: desligar o laço inteiro deixa 3 s. O caminho 1 sobe a carência SIGTERM→SIGKILL exigida do deploy de ~265 s para ~395 s — configuração que não mora neste repo e que nenhum teste cobre.

## O que muda

- `Settings.contexto_deadline_de_montagem_segundos = 35.0` governa um `asyncio.timeout` sobre a fase de `montar_contexto` que fala com o modelo. As leituras de banco ficam fora.
- No estouro, o contexto é truncado **sem falar com o provedor** — `_truncar_ate_caber(..., sem_modelo=True)`, com estimativa pessimista derivada do piso de 3,2 chars/token que o config já documenta. `_estimar` não muda: a pessimização vive só nesse ramo.
- Em `_pior_turno()`, as fatias `count_tokens` e `resumir` saem. O deadline entra **fora** do multiplicador de retentativas — uma retentativa repete uma requisição, e a fase já está limitada pelo relógio.

## O que revisar com atenção

**Dois testes verdes foram invertidos.** `test_o_pior_turno_segue_contexto_max_iteracoes` e `..._segue_o_gatilho_de_regeneracao` afirmavam que subir a iteração move o pior caso. Agora afirmam que não move — é o ganho do caminho 3, mas é contrato que a card não pediu para mudar. Um terceiro teste novo afirma que quem move é o deadline, para a derivação não ficar sem guarda.

**`job_timeout`, `sweep_inflight_after_seconds` e `job_completion_wait` não são tocados.** É o que separa este PR de um que precisaria de mudança coordenada fora do repo.

**Emenda E-02 (TEC-290) à RN-09.4** no SRS: o segundo argumento da E-01 citava o orçamento estourado e deixou de ser verdade. A regra continua de pé pelos outros dois argumentos.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Não há opção de merge local e não há opção de deixar a branch parada: trabalho de card termina em push e PR. Quem mergeia é o Eduardo.

- [ ] **Step 2: Comentar na card e mover para "Em análise"**

O comentário registra o que some se ficar só no PR:

- **A divergência em relação à card:** ela lista três caminhos "sem recomendação"; a implementação escolheu o 3 e mediu os outros dois para justificar — o caminho 2 sozinho não fecha (zerar `contexto_max_iteracoes` deixa 3 s de folga) e o caminho 1 sobe a carência de deploy de ~265 s para ~395 s.
- **O critério de pronto que mudou de forma:** a card pede que os dois `xfail` saiam. Saíram — mas junto saiu `test_o_orcamento_estourado_nao_piora` e os dois testes de derivação foram **invertidos**, o que a card não previu e é mudança de contrato.
- **A lacuna que é decisão de produto:** a folga de 33 s sobre um mínimo de 30 significa que o próximo teto por chamada a subir reabre esta card. Deixar folga larga exigiria mexer na janela do sweeper, que é a decisão que esta card evitou.
- **O que a card não entrega:** nada mede a fase de montagem em produção. O deadline de 35 s é derivado do que sobrou, não do que a montagem leva. O sinal, se ele estourar, virá de `contexto.deadline_estourado` no log.
- **A emenda ao SRS:** `Emenda E-02 (TEC-290)` sob a RN-09.4.

Transição: "Em análise", **não** "Feito" — quem mergeia é que fecha.

- [ ] **Step 3: Depois do merge (quando acontecer)**

```bash
git merge-base --is-ancestor <hash> origin/main
```

Confirmado, volte para `main`, `pull`, e apague a branch local.
