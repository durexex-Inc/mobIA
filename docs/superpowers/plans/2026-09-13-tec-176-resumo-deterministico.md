# TEC-176 — Resumo determinístico de contingência: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um handoff nunca mais fica sem resumo. Quando o provedor falha ou o modelo devolve algo malformado, um resumo determinístico montado do dossiê toma o lugar — identificado como tal, e substituível pela regeneração.

**Architecture:** Uma função pura monta os seis blocos a partir do `Dossie` que a TEC-175 já produz, reusando os mesmos marcadores e os mesmos formatadores de valor. `gerar_resumo` passa a capturar as falhas que hoje deixam o resumo nulo e grava o template, marcando `handoffs.resumo_fallback`.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, pytest.

**Spec:** [`docs/superpowers/specs/2026-09-13-tec-176-resumo-deterministico-design.md`](../specs/2026-09-13-tec-176-resumo-deterministico-design.md)

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  **`alembic/` está no escopo do formatador.**
- **`ruff`:** `select = ["E","F","I","UP","B"]`, `line-length = 100`.
- **A cadeia de migration na `main` termina em `0026`. A desta card é a `0027`.** Confira com `ls alembic/versions/` antes de escrever.
- **Suíte inteira:** `-n 8 --dist loadfile`, uma vez. **Se dezenas de testes falharem com `relation ... does not exist`, não é a sua migration** — são os bancos dos workers com o carimbo do alembic adiantado, e o sintoma **se repete idêntico na segunda execução**. Confira com `docker compose exec -T postgres psql -U mobia -d mobia_gwN` — **não há `psql` no PATH desta máquina**. O CLAUDE.md tem o parágrafo inteiro.
- **`ConnectionResetError [WinError 64]`** é ruído desta máquina (~5% dos connects): espere e retente.
- **O limite de 1.500 caracteres (`LIMITE_DE_CARACTERES`) vale para o template também.** A RN-15.2 não distingue os dois modos.
- **Mensagens de commit:** português sem acento no assunto, `tipo(TEC-176): ...`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/handoff/dossie.py` | **Modificar.** Promover a público os formatadores de valor que o template também precisa. |
| `src/mobia/domain/handoff/contingencia.py` | **Criar.** Puro: monta os seis blocos determinísticos a partir do `Dossie`. |
| `alembic/versions/0027_resumo_de_contingencia.py` | **Criar.** A coluna `resumo_fallback`. |
| `src/mobia/domain/handoff/models.py` | **Modificar.** A coluna. |
| `src/mobia/domain/handoff/repositorio.py` | **Modificar.** `gravar_resumo` ganha `fallback` e aceita `modelo` nulo. |
| `src/mobia/domain/handoff/geracao.py` | **Modificar.** Captura as falhas e grava o template. |

---

### Task 1: O template determinístico

**Files:**
- Modify: `src/mobia/domain/handoff/dossie.py`
- Create: `src/mobia/domain/handoff/contingencia.py`
- Test: `tests/unit/test_handoff_contingencia.py`

**Interfaces:**
- Consumes: `Dossie`, `ImovelApresentado`, `AUSENTE`, `reais` de `dossie`; `MARCADORES`, `LIMITE_DE_CARACTERES`, `validar` de `resumo`.
- Produces: `TEXTO_DE_CONTINGENCIA`, `TETO_DE_IMOVEIS`, `montar(dossie: Dossie) -> str`.

**O ponto de desenho que esta task resolve, e que você deve respeitar:** `dossie.renderizar` (a entrada do modelo) e o template produzem conteúdo parecido com títulos diferentes. **Os dois não podem formatar valor por conta própria** — se cada um escrever a sua versão de "ate R$ 600.000", viram duas fontes para o mesmo fato, que é o defeito que a TEC-146 gastou uma card inteira consertando.

**A correção:** promova a público, em `dossie.py`, os helpers de formatação que os dois usam — hoje eles são privados (`_faixa`, `_ou_ausente`, `_sim_nao`, `_fatores`, `_pontos_de_atencao`, `_imoveis`). Renomeie sem o sublinhado os que o template precisar e ajuste `renderizar` para usar os nomes novos. **Não copie nenhum deles para `contingencia.py`.**

`contingencia.py` importa de `dossie` e de `resumo`; **não faça o caminho contrário** — `resumo.py` já importa `AUSENTE` de `dossie.py`, então `dossie → resumo` seria ciclo.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_handoff_contingencia.py
from datetime import UTC, datetime

from mobia.domain.handoff.contingencia import TETO_DE_IMOVEIS, TEXTO_DE_CONTINGENCIA, montar
from mobia.domain.handoff.dossie import Dossie, ImovelApresentado
from mobia.domain.handoff.resumo import LIMITE_DE_CARACTERES, MARCADORES, validar

QUANDO = datetime(2026, 9, 12, 14, 30, tzinfo=UTC)


def _dossie(**trocas: object) -> Dossie:
    base: dict[str, object] = {
        "canal": "whatsapp",
        "conversa": "5511911112222",
        "primeira_mensagem_em": QUANDO,
        "mensagens_do_lead": 12,
        "intencao": "COMPRA",
        "faixa_min_centavos": None,
        "faixa_max_centavos": 60_000_000,
        "regiao": "Pinheiros",
        "tipo_imovel": "APARTAMENTO",
        "quartos": 2,
        "vagas": 1,
        "urgencia": "ATE_3_MESES",
        "forma_pagamento": "FINANCIAMENTO",
        "tem_imovel_para_vender": False,
        "score_total": 72,
        "score_fatores": (("completude", 25), ("urgencia", 20)),
        "score_causas": ("CAMPOS_OBRIGATORIOS",),
        "temperatura": "QUENTE",
        "temperatura_forcada_motivos": (),
        "imoveis": (ImovelApresentado("AP-001", 58_000_000, "venda", "GOSTOU", None),),
        "campos_recusados": ("renda",),
        "perguntados_sem_resposta": ("prazo",),
        "gatilho": "LEAD_QUENTE",
        "etiqueta": "lead-quente",
        "prioridade": "NORMAL",
        "criado_em": QUANDO,
    }
    return Dossie(**(base | trocas))  # type: ignore[arg-type]


def _vazio() -> Dossie:
    """O quarto cenario: um lead de quem nao se sabe nada."""
    return _dossie(
        primeira_mensagem_em=None,
        mensagens_do_lead=0,
        intencao=None,
        faixa_max_centavos=None,
        regiao=None,
        tipo_imovel=None,
        quartos=None,
        vagas=None,
        urgencia=None,
        forma_pagamento=None,
        tem_imovel_para_vender=None,
        score_total=None,
        score_fatores=(),
        score_causas=(),
        temperatura=None,
        imoveis=(),
        campos_recusados=(),
        perguntados_sem_resposta=(),
    )


def test_o_template_passa_no_validador_dos_seis_blocos() -> None:
    """D3: a mesma estrutura dos dois modos, e o mesmo validador."""
    assert validar(montar(_dossie())) == montar(_dossie()).strip()


def test_o_template_se_identifica_como_tal() -> None:
    assert TEXTO_DE_CONTINGENCIA in montar(_dossie())


def test_o_template_cita_os_numeros_do_dossie() -> None:
    texto = montar(_dossie())

    assert "72" in texto
    assert "R$ 600.000" in texto
    assert "Pinheiros" in texto


def test_dossie_vazio_nao_inventa_objecao_nem_proxima_acao() -> None:
    """Quarto cenario do Gherkin, e a razao de existir da D4."""
    texto = montar(_vazio())

    assert validar(texto)
    assert "nenhum ponto de atencao registrado" in texto
    # O bloco da proxima acao apresenta FATOS -- gatilho, etiqueta, prioridade
    # --, nunca uma recomendacao. Recomendar e julgamento, e e o que o modelo
    # fazia.
    assert "LEAD_QUENTE" in texto
    assert "recomend" not in texto.lower()


def test_dossie_vazio_nao_escreve_None_em_lugar_nenhum() -> None:
    assert "None" not in montar(_vazio())


def test_a_lista_de_imoveis_tem_teto_e_diz_o_total() -> None:
    """D6: o template cabe nos 1.500 por construcao, nao por truncamento."""
    muitos = tuple(
        ImovelApresentado(f"AP-{i:03d}", 50_000_000 + i, "venda", None, None)
        for i in range(TETO_DE_IMOVEIS + 7)
    )
    texto = montar(_dossie(imoveis=muitos))

    assert str(TETO_DE_IMOVEIS + 7) in texto
    assert texto.count("AP-") == TETO_DE_IMOVEIS
    assert len(texto) <= LIMITE_DE_CARACTERES


def test_um_dossie_grande_ainda_cabe_no_limite() -> None:
    """O caso ruim inteiro: todo campo preenchido e a lista estourada."""
    muitos = tuple(
        ImovelApresentado(f"AP-{i:03d}", 50_000_000 + i, "aluguel", "DESCARTOU", "PRECO")
        for i in range(40)
    )
    texto = montar(
        _dossie(
            imoveis=muitos,
            regiao="Vila Madalena, Pinheiros, Perdizes e adjacencias",
            campos_recusados=("renda", "profissao", "estado civil"),
            perguntados_sem_resposta=("prazo", "entrada", "financiamento aprovado"),
            score_fatores=(
                ("completude", 25), ("urgencia", 20), ("catalogo", 12),
                ("engajamento", 10), ("capacidade", 5),
            ),
            temperatura_forcada_motivos=("PEDIU_VISITA", "FALOU_EM_PROPOSTA"),
        )
    )

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)


def test_os_seis_marcadores_estao_na_ordem() -> None:
    texto = montar(_dossie())
    posicoes = [texto.find(m) for m in MARCADORES]

    assert all(p >= 0 for p in posicoes)
    assert posicoes == sorted(posicoes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_contingencia.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.contingencia'`

- [ ] **Step 3: Write the implementation**

Comece promovendo os helpers em `dossie.py` (ver a nota acima), depois escreva:

```python
# src/mobia/domain/handoff/contingencia.py
"""O resumo que o corretor recebe quando o modelo nao entrega. TEC-176.

Modulo sem I/O, como `dossie.py` e `vocabulario.py`: monta texto a partir de
fatos que ja vieram do banco.

**Reusa os MARCADORES do resumo redigido, de proposito.** O corretor le a
mesma estrutura nos dois modos e nao precisa perceber que mudou de formato
para achar o que procura; e um leitor futuro -- o painel da E8, a exportacao
para CRM da TEC-180 -- nao precisa de dois parsers para um campo so. Ver a D3
do desenho.

**Os formatadores de valor vem de `dossie.py`, nao sao reescritos aqui.**
Duas versoes de "ate R$ 600.000" seriam duas fontes para o mesmo fato.
"""
```

- `TEXTO_DE_CONTINGENCIA`: a linha que identifica o modo, no topo. Ela é o *"fica indicado que se trata de resumo automático simplificado"* do segundo cenário — e a coluna `resumo_fallback` da Task 2 é a versão legível por máquina da mesma informação.
- `TETO_DE_IMOVEIS`: o limite da lista. Escolha um número que faça o pior caso caber, e **escreva no comentário como você chegou nele** — o teste do dossiê grande é quem prova.
- `montar(dossie)`: os seis blocos, na ordem de `MARCADORES`, com a linha de contingência.

**O bloco da próxima ação apresenta gatilho, etiqueta e prioridade como FATOS.** Não escreva "recomenda-se", "sugere-se" nem prazo derivado — recomendar é julgamento, é o que o modelo fazia, e o quarto cenário proíbe.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_contingencia.py tests/unit/test_handoff_dossie.py -v`
Expected: PASS. `test_handoff_dossie.py` não pode quebrar com a promoção dos helpers.

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/contingencia.py src/mobia/domain/handoff/dossie.py tests/unit/test_handoff_contingencia.py
git commit -m "feat(TEC-176): o resumo de contingencia sai do dossie, com os mesmos seis blocos"
```

---

### Task 2: A coluna que identifica o modo

**Files:**
- Create: `alembic/versions/0027_resumo_de_contingencia.py`
- Modify: `src/mobia/domain/handoff/models.py`, `src/mobia/domain/handoff/repositorio.py`
- Test: `tests/integration/test_handoff_schema.py`, `tests/integration/test_handoff_dossie_do_banco.py`

**Interfaces:**
- Produces: `Handoff.resumo_fallback: bool`; `gravar_resumo(session, *, handoff_id, texto, modelo: str | None, fallback: bool)`.

**Leia `alembic/versions/0026_notificacao_do_handoff.py` antes** — é a migration irmã mais recente sobre `handoffs`, e o formato do docstring é o padrão.

**A coluna já está especificada no SRS:** o modelo Handoff da seção 5 lista `resumo_fallback boolean — "Indica geração determinística (RN-15.4)"`. Você a está implementando, não inventando.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_handoff_schema.py`:

```python
async def test_resumo_fallback_nasce_falso(session: AsyncSession) -> None:
    """Falso e nao verdadeiro: o estado "ainda nao gerei" nao e contingencia.

    Com default verdadeiro, todo handoff nasceria marcado como simplificado, e
    o painel da E8 mostraria a fila inteira como degradada.
    """
    registro = await registrar_handoff(
        session, channel="whatsapp", conversation_key="5511911112222",
        gatilho=Gatilho.LEAD_QUENTE,
    )
    await session.commit()

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == registro.id))
    ).scalar_one()
    assert linha.resumo_fallback is False
```

E a `tests/integration/test_handoff_dossie_do_banco.py`:

```python
async def test_gravar_resumo_marca_e_desmarca_a_contingencia(
    session: AsyncSession,
) -> None:
    """D5: o sucesso posterior LIMPA a marca.

    Um handoff que caiu no template e depois foi regenerado com sucesso nao
    pode ficar marcado como simplificado sobre um texto redigido -- quem lesse
    o painel veria "simplificado" sobre algo que nao e. E a mesma classe de
    defeito que a revisao final da TEC-177 encontrou nas colunas de
    notificacao, prevista desta vez.
    """
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()

    await gravar_resumo(
        session, handoff_id=registro.id, texto="template", modelo=None, fallback=True
    )
    await session.commit()
    session.expire_all()
    linha = (
        await session.execute(select(Handoff).where(Handoff.id == registro.id))
    ).scalar_one()
    assert linha.resumo_fallback is True
    assert linha.resumo_modelo is None

    await gravar_resumo(
        session, handoff_id=registro.id, texto="redigido", modelo="claude-sonnet-5",
        fallback=False,
    )
    await session.commit()
    session.expire_all()
    linha = (
        await session.execute(select(Handoff).where(Handoff.id == registro.id))
    ).scalar_one()
    assert linha.resumo_fallback is False
    assert linha.resumo_modelo == "claude-sonnet-5"
```

- [ ] **Step 2: Run to verify it fails.** Expected: `AttributeError: ... 'resumo_fallback'` / `TypeError` no `fallback=`

- [ ] **Step 3: Write the migration, the column and the parameter**

A migration acrescenta `resumo_fallback` (Boolean, `nullable=False`, `server_default=false`), com docstring explicando **por que falso**.

No modelo, a coluna com o comentário do porquê.

Em `gravar_resumo`: `modelo` passa a ser `str | None` e entra `fallback: bool`, **os dois obrigatórios e keyword-only**. Sem default em `fallback` de propósito: um default faria o chamador esquecer de dizer qual modo é, e o esquecimento silencioso é justamente o defeito que a D5 previne. Escreva isso no comentário.

`modelo=None` no template porque **nenhum modelo o escreveu** — a coluna diz qual modelo, e não há um. `resumo_fallback` é a autoridade sobre o modo; `resumo_modelo` nulo é a consequência.

- [ ] **Step 4: Apply and run**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py tests/integration/test_handoff_dossie_do_banco.py tests/integration/test_geracao_de_resumo.py -v --tb=short
```

- [ ] **Step 5: Run the static gates.** `alembic/` está no escopo do formatador.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0027_resumo_de_contingencia.py src/mobia/domain/handoff/models.py src/mobia/domain/handoff/repositorio.py tests/integration/
git commit -m "feat(TEC-176): o handoff passa a dizer se o resumo foi redigido ou montado"
```

---

### Task 3: A queda para o template

**Files:**
- Modify: `src/mobia/domain/handoff/geracao.py`
- Test: `tests/integration/test_geracao_de_resumo.py`

**Interfaces:**
- Consumes: `montar` (Task 1); `gravar_resumo(..., fallback=)` (Task 2).
- Produces: `gerar_resumo` com o comportamento novo — continua devolvendo `bool`.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_geracao_de_resumo.py`:

```python
class _RedatorQueOProvedorDerrubou:
    """O provedor fora do ar: uma excecao que NAO e ResumoDeHandoffInvalido."""

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        raise RuntimeError("connection reset by peer")


async def test_provedor_fora_do_ar_grava_o_template(
    session, session_factory, semear_lead_completo
) -> None:
    """Primeiro cenario do Gherkin. D2: sem retentativa, template na hora."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    assert await gerar_resumo(
        session_factory, redator=_RedatorQueOProvedorDerrubou(), handoff_id=handoff_id
    )

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.resumo_fallback is True
    assert linha.resumo_modelo is None
    assert TEXTO_DE_CONTINGENCIA in decrypt(
        linha.resumo, aad_do_resumo_de_handoff(handoff_id)
    )


async def test_resumo_malformado_tambem_grava_o_template(
    session, session_factory, semear_lead_completo
) -> None:
    """D1: a emenda E-01 alarga o fallback para alem da falha do provedor.

    Antes desta card este caminho terminava com `resumo` nulo, e a RN-15.4
    seguia violada pela metade.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    assert await gerar_resumo(
        session_factory, redator=_RedatorQueFalha(), handoff_id=handoff_id
    )

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.resumo_fallback is True


async def test_regenerar_com_o_provedor_de_volta_limpa_a_marca(
    session, session_factory, semear_lead_completo
) -> None:
    """Terceiro cenario do Gherkin, com a limpeza da D5."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    await gerar_resumo(session_factory, redator=_RedatorQueFalha(), handoff_id=handoff_id)

    assert await gerar_resumo(
        session_factory, redator=_RedatorFalso(), handoff_id=handoff_id
    )

    session.expire_all()
    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.resumo_fallback is False
    assert linha.resumo_modelo == "claude-sonnet-5"


async def test_dossie_ausente_continua_sem_resumo(session_factory) -> None:
    """A excecao declarada da D1: sem fatos nao ha template possivel."""
    assert not await gerar_resumo(
        session_factory, redator=_RedatorFalso(), handoff_id=uuid.uuid4()
    )
```

> **O teste do sucesso normal já existe** (`test_gera_e_grava_o_resumo`). Confira que ele continua passando **e** que ele agora afirma `resumo_fallback is False` — se não afirmar, acrescente. Um caminho feliz que não prova a ausência da marca deixa a D5 meio testada.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write the implementation**

Em `gerar_resumo`, a forma passa a ser:

1. Carrega o dossiê. `None` → log e `False` (**inalterado** — é a exceção declarada da D1).
2. Tenta redigir. **Captura `ResumoDeHandoffInvalido` e também qualquer exceção do provedor**, e nos dois casos monta o template.
3. Grava, com `fallback` dizendo qual caminho foi.

**Duas coisas que você decide e deve registrar no relatório:**

- **Qual exceção capturar no ramo do provedor.** `except Exception` é largo demais — engoliria `TypeError` de um defeito de programação e produziria um template silencioso onde deveria haver um erro barulhento. Mas o SDK da Anthropic levanta tipos próprios, e `geracao.py` hoje não os importa. Decida e justifique: ou importa os tipos do SDK, ou captura `Exception` **com log em `error` e o tipo no campo**, aceitando a largura. **Se escolher `Exception`, diga no relatório por quê e qual o risco.**
- **Se o log distingue os dois motivos.** Provedor fora do ar e resposta malformada são causas diferentes com o mesmo efeito; quem investiga precisa saber qual foi.

**O `False` passa a significar só uma coisa:** "não havia dossiê". Todo o resto grava. Atualize a docstring — hoje ela diz *"`False` em toda falha esperada"*, e isso deixa de ser verdade.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Run the static gates.**

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/geracao.py tests/integration/test_geracao_de_resumo.py
git commit -m "feat(TEC-176): nenhuma falha de geracao deixa mais o handoff sem resumo"
```

---

### Task 4: Fechamento

- [ ] **Step 1: Suíte inteira, uma vez.** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`

- [ ] **Step 2: Comentários tocados.** `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

**Candidatos previsíveis, e você precisa conferir os três:**
- A docstring de `gerar_resumo`, que diz *"`False` em toda falha esperada"* e *"um handoff sem resumo e um estado previsto (a TEC-176 o atende)"* — as duas mudaram de estado com esta card.
- O comentário da D7 em `resumo.py` sobre o handoff ficar sem resumo quando a validação falha.
- `TEXTO_SEM_RESUMO` em `notificacao/mensagem.py` — ele existe para o caso que esta card acabou de tornar raro. **Não o apague:** o dossiê ausente ainda produz handoff sem resumo. Mas confira se o comentário dele ainda descreve a realidade.

- [ ] **Step 3: Orçamento do prompt.** `-k margem_do_orcamento` — esta card não toca `SISTEMA_DO_AGENTE`.

- [ ] **Step 4: Os três gates, e push.**

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 3. D2 → Task 3. D3 → Task 1. D4 → Task 1. D5 → Tasks 2 e 3. D6 → Task 1. L1, L2, L3 → declaradas; sem task, por construção.

**Consistência de tipos:** `montar(Dossie) -> str` produzida na Task 1 e consumida na 3; `gravar_resumo(..., modelo: str | None, fallback: bool)` na Task 2 e usada na 3.

**Dois pontos que o executor resolve contra o repo,** marcados em citação: quais exceções capturar no ramo do provedor, e a promoção dos helpers privados de `dossie.py` sem duplicá-los.
