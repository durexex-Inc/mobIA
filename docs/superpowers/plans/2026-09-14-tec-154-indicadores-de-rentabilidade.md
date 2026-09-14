# TEC-154 — Indicadores de rentabilidade na ficha do investidor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acrescentar três linhas ao fim da ficha do imóvel — aluguel estimado com yield bruto anual, condomínio somado ao IPTU, e a ressalva de estimativa — apenas quando o lead está na trilha do investidor.

**Architecture:** O cálculo é puro e mora em `domain/agente/apresentacao.py`, que não importa `domain/catalogo`. A leitura das quatro colunas do catálogo fica em `fichas_do_catalogo` (`ferramenta_de_busca.py`), único ponto em que `domain/agente` toca `domain/catalogo`. `Ficha` ganha um campo opcional `rentabilidade`, e `None` significa trilha padrão. Nenhuma migration, nenhuma coluna, nenhum texto de prompt.

**Tech Stack:** Python 3.13, SQLAlchemy async, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-154-indicadores-de-rentabilidade-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, nenhum linter verifica.
- **Todo texto que sai para o lead é ASCII sem acento** (`Condominio`, `m2`, `nao`). Mesma disciplina de `TEXTO_DA_BUSCA_INCONCLUSIVA`.
- **Os três gates estáticos, com o escopo exato do CI**, antes de qualquer commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Loop de testes enquanto se escreve:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, sem Docker, sem `-n`).
- **Suíte inteira, uma vez só, no fim:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`. Exige `docker compose` de pé.
- **Mensagem de commit:** português sem acento no assunto, formato `tipo(TEC-154): o que passou a ser verdade`, terminando com a linha `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **`Ficha` é `frozen=True, slots=True`.** Campo novo entra **com default, no fim** — sem isso, toda construção existente de `Ficha` quebra. Nos testes, copie com `dataclasses.replace`, nunca `Ficha(**ficha.__dict__)`: `slots=True` não tem `__dict__`.

---

### Task 1: O cálculo puro — `Rentabilidade`, `yield_bruto_anual`, `custos_recorrentes`

**Files:**
- Modify: `src/mobia/domain/agente/apresentacao.py`
- Test: `tests/unit/test_apresentacao.py`

**Interfaces:**
- Consumes: `reais_de` (já existe neste módulo).
- Produces:
  - `Rentabilidade(aluguel_centavos: int | None, yield_pct: Decimal | None, custos_centavos: int | None)` — frozen, slots.
  - `yield_bruto_anual(aluguel_centavos: int | None, preco_venda_centavos: int | None) -> Decimal | None`
  - `custos_recorrentes(condominio_centavos: int | None, iptu_centavos: int | None) -> int | None`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/unit/test_apresentacao.py`, e ao import do módulo no topo acrescente `Rentabilidade`, `custos_recorrentes` e `yield_bruto_anual`:

```python
def test_o_yield_do_gherkin_sai_com_uma_casa_e_zero_a_direita() -> None:
    """Cenario 1 da TEC-154: R$ 500.000 com aluguel de R$ 2.500 dao 6,0% ao ano.

    O zero a direita nao e enfeite: `6%` e `6,0%` dizem coisas diferentes
    sobre precisao.
    """
    assert yield_bruto_anual(250000, 50000000) == Decimal("6.0")


def test_o_yield_trunca_para_baixo_e_nunca_arredonda() -> None:
    """D4: arredondar para cima promete retorno acima do real.

    8760,04 * 12 / 2417514,29 = 4,3479...%, e o que sai e 4,3 -- nao 4,4.
    Sao os valores da linha TE-1007 do seed.
    """
    assert yield_bruto_anual(876004, 241751429) == Decimal("4.3")


def test_sem_aluguel_nao_ha_yield() -> None:
    assert yield_bruto_anual(None, 50000000) is None


def test_sem_preco_de_venda_nao_ha_yield() -> None:
    """Imovel so de aluguel: a RN-07.3 define o yield sobre o preco de venda."""
    assert yield_bruto_anual(250000, None) is None


def test_preco_de_venda_zero_nao_levanta_divisao_por_zero() -> None:
    """Nao ha linha assim no catalogo hoje (`ck_imoveis_ao_menos_um_preco` nao
    proibe zero, so NULL), e um ZeroDivisionError aqui derrubaria a
    apresentacao inteira por causa de um imovel."""
    assert yield_bruto_anual(250000, 0) is None


def test_os_custos_recorrentes_somam_condominio_e_iptu() -> None:
    assert custos_recorrentes(184400, 77100) == 261500


def test_um_custo_ausente_nao_zera_o_outro() -> None:
    """Ausente e zero sao coisas diferentes: somar so o que existe e o que
    mantem a linha verdadeira."""
    assert custos_recorrentes(184400, None) == 184400
    assert custos_recorrentes(None, 77100) == 77100


def test_sem_condominio_e_sem_iptu_nao_ha_linha_de_custos() -> None:
    assert custos_recorrentes(None, None) is None
```

No topo do arquivo de teste, acrescente `from decimal import Decimal`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py -v`
Expected: FAIL na coleta, com `ImportError: cannot import name 'yield_bruto_anual'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/agente/apresentacao.py`, acrescente ao import do topo `from decimal import ROUND_DOWN, Decimal` e escreva, logo depois de `reais_de`:

```python
@dataclass(frozen=True, slots=True)
class Rentabilidade:
    """Os indicadores da RN-07.3, e so para a trilha do investidor. TEC-154.

    Objeto proprio, e nao tres campos soltos em `Ficha`: a docstring de la
    promete "os oito campos da RN-10.1", e este repo trata comentario
    desatualizado como defeito. `Ficha.rentabilidade is None` significa
    trilha PADRAO -- o que distingue "nao e investidor" de "e investidor e o
    catalogo nao tem o dado", dois estados que a mesma ficha precisa
    diferenciar porque o segundo imprime uma linha e o primeiro nao imprime
    nada.

    Os tres campos sao independentes, com UMA invariante: `yield_pct` nao
    nulo implica `aluguel_centavos` nao nulo. As combinacoes que existem:

    | aluguel | preco de venda | linha do aluguel   | ressalva |
    |---------|----------------|--------------------|----------|
    | tem     | tem            | valor E yield      | sim      |
    | tem     | nulo           | valor, sem yield   | sim      |
    | nulo    | qualquer       | `nao informado`    | nao      |

    `custos_centavos` nao entra na tabela porque nao depende de nenhum dos
    dois: condominio e IPTU sao fato do catalogo, nao estimativa, e saem
    mesmo sem aluguel.
    """

    aluguel_centavos: int | None
    yield_pct: Decimal | None
    custos_centavos: int | None


def yield_bruto_anual(
    aluguel_centavos: int | None, preco_venda_centavos: int | None
) -> Decimal | None:
    """O yield bruto anual em pontos percentuais, ou `None` sem os dois precos.

    `aluguel * 12 / preco_venda`, que e a RN-07.3 literal.

    **Trunca para BAIXO, como `reais_de` faz com centavos, e pelo argumento
    invertido:** arredondar preco para cima cota ao lead acima do real;
    arredondar yield para cima PROMETE retorno acima do real. 4,3479% sai
    como 4,3, nunca 4,4.

    **Zero entra pela mesma porta que `None`.** Preco de venda zero daria
    ZeroDivisionError e derrubaria a apresentacao inteira por causa de um
    imovel -- `ck_imoveis_ao_menos_um_preco` recusa NULL nos dois, nao zero
    num deles. Aluguel zero nao e indicador de rentabilidade, e omitir e mais
    honesto que exibir "0,0% ao ano".

    **Quem passa o preco de venda e `fichas_do_catalogo`, lendo
    `Imovel.preco_venda` -- nunca `Ficha.preco_centavos`**, que e o preco da
    operacao BUSCADA: num investidor que buscasse ALUGUEL ele e o aluguel, e
    a conta daria 1200% ao ano numa ficha que o lead le como fato.
    """
    if not aluguel_centavos or not preco_venda_centavos:
        return None
    bruto = Decimal(aluguel_centavos) * 12 * 100 / Decimal(preco_venda_centavos)
    return bruto.quantize(Decimal("0.1"), rounding=ROUND_DOWN)


def custos_recorrentes(
    condominio_centavos: int | None, iptu_centavos: int | None
) -> int | None:
    """Condominio somado ao IPTU, ou `None` quando os DOIS faltam.

    Um so ausente nao zera o outro: somar apenas o que existe e o que mantem
    a linha verdadeira. `None` nos dois omite a linha, como `condominio` ja
    faz na ficha padrao.
    """
    if condominio_centavos is None and iptu_centavos is None:
        return None
    return (condominio_centavos or 0) + (iptu_centavos or 0)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py -v`
Expected: PASS em tudo, inclusive nos testes antigos do arquivo.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/apresentacao.py tests/unit/test_apresentacao.py
git commit -m "feat(TEC-154): o yield bruto anual e os custos recorrentes viram funcao pura

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A legenda renderiza o bloco

**Files:**
- Modify: `src/mobia/domain/agente/apresentacao.py`
- Test: `tests/unit/test_apresentacao.py`

**Interfaces:**
- Consumes: `Rentabilidade`, `reais_de` (Task 1).
- Produces: `Ficha.rentabilidade: Rentabilidade | None = None` — campo novo, com default, **no fim** do dataclass. `legenda_de` passa a emitir três linhas ao fim quando ele não é `None`.

- [ ] **Step 1: Escrever os testes que falham**

```python
COM_YIELD = replace(
    COMPLETA,
    rentabilidade=Rentabilidade(
        aluguel_centavos=876004,
        yield_pct=Decimal("4.3"),
        custos_centavos=261500,
    ),
)


def test_sem_rentabilidade_a_legenda_e_identica_a_de_hoje() -> None:
    """A trilha padrao nao paga nada por esta card -- nem um caractere."""
    assert legenda_de(COMPLETA) == (
        "Apartamento em Lagoa da Conceicao\n"
        "Lagoa da Conceicao - R$ 516.464\n"
        "4 quartos - 2 vagas - 54 m2\n"
        "Condominio R$ 550\n"
        "Destaque: churrasqueira e mobiliado"
    )


def test_o_bloco_do_investidor_sai_no_fim_com_a_ressalva_por_ultimo() -> None:
    """D6: a ficha padrao nao muda de forma e o extra e um apendice coeso.

    A linha `Condominio R$ 550` PERMANECE ao lado do somatorio: condominio e
    um dos oito campos da RN-10.1, e suprimi-lo para o investidor quebraria
    aquela regra para ganhar 20 caracteres. De quebra, as duas linhas juntas
    revelam o IPTU, que nao tem linha propria.
    """
    assert legenda_de(COM_YIELD) == (
        "Apartamento em Lagoa da Conceicao\n"
        "Lagoa da Conceicao - R$ 516.464\n"
        "4 quartos - 2 vagas - 54 m2\n"
        "Condominio R$ 550\n"
        "Destaque: churrasqueira e mobiliado\n"
        "Aluguel estimado R$ 8.760 - yield bruto 4,3% ao ano\n"
        "Condominio + IPTU R$ 2.615/mes\n"
        "Estimativa, nao e garantia de retorno."
    )


def test_sem_aluguel_a_ficha_diz_que_o_dado_nao_existe_e_nao_ressalva_nada() -> None:
    """Cenario 3 do Gherkin, que e o caminho de ~88% dos candidatos de VENDA.

    Sem numero estimado nao ha o que ressalvar: condominio e IPTU sao fato do
    catalogo, e ressalva-los ensinaria o lead a ignorar a ressalva onde ela
    importa.
    """
    sem_aluguel = replace(
        COMPLETA,
        rentabilidade=Rentabilidade(
            aluguel_centavos=None, yield_pct=None, custos_centavos=261500
        ),
    )
    assert legenda_de(sem_aluguel).endswith(
        "Aluguel estimado: nao informado\nCondominio + IPTU R$ 2.615/mes"
    )


def test_aluguel_sem_preco_de_venda_mostra_o_valor_sem_o_sufixo_do_yield() -> None:
    """D2: trocar por `nao informado` seria negar um aluguel que esta no
    catalogo -- a mentira do cenario 3 na direcao contraria. A ressalva sai,
    porque ha numero estimado."""
    so_aluguel = replace(
        COMPLETA,
        rentabilidade=Rentabilidade(
            aluguel_centavos=876004, yield_pct=None, custos_centavos=None
        ),
    )
    assert legenda_de(so_aluguel).endswith(
        "Aluguel estimado R$ 8.760\nEstimativa, nao e garantia de retorno."
    )
    assert "yield" not in legenda_de(so_aluguel)


def test_o_teto_de_600_corta_a_prosa_e_nunca_o_bloco_do_investidor() -> None:
    """O bloco entra no CORPO, entao `_prosa_que_cabe` ja o protege de graca:
    a prioridade da D14 da TEC-162 nao muda."""
    prosa = "palavra " * 200
    legenda = legenda_de(COM_YIELD, prefixo=prosa)
    assert len(legenda) <= MAX_CARACTERES_DA_LEGENDA
    assert legenda.endswith("Estimativa, nao e garantia de retorno.")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py -v`
Expected: FAIL com `TypeError: Ficha.__init__() got an unexpected keyword argument 'rentabilidade'` (via `replace`).

- [ ] **Step 3: Implementar**

Em `Ficha`, acrescente **no fim** do dataclass e acrescente o parágrafo à docstring dele:

```python
    foto: str | None
    # TEC-154. `None` e a trilha PADRAO, e nao "investidor sem dado" -- ver a
    # docstring de `Rentabilidade`. Com default e no fim de proposito: `Ficha`
    # e `slots=True` e toda construcao existente tem de seguir valida.
    rentabilidade: Rentabilidade | None = None
```

Logo antes de `legenda_de`:

```python
# RN-07.5 e RN-04.4 na mesma frase: "estimativa" cobre a ressalva de que o
# numero e estimado, e "nao e garantia" cobre a proibicao de apresentar
# rentabilidade como garantida. Texto do CODIGO, nao do modelo -- precedente
# do aviso de ampliacao (TEC-160) e do motivo de match (TEC-163): texto de
# modelo some num turno e muda de palavra no outro, e aqui o que sumiria e
# justamente a ressalva.
RESSALVA_DE_ESTIMATIVA = "Estimativa, nao e garantia de retorno."

# Cenario 3 do Gherkin. NAO e silencio: medido no seed, 467 dos 520 imoveis
# caem aqui -- inclusive todos os 375 que sao so VENDA --, e uma linha
# ausente pareceria esquecimento nosso em vez de lacuna do catalogo.
_ALUGUEL_AUSENTE = "Aluguel estimado: nao informado"


def _linhas_da_rentabilidade(rentabilidade: Rentabilidade) -> list[str]:
    """As ate tres linhas do bloco do investidor, na ordem em que saem.

    A ressalva acompanha QUALQUER numero estimado -- o aluguel sozinho ja e
    um --, e nao so o yield. Sem numero nenhum ela nao sai.
    """
    linhas: list[str] = []
    if rentabilidade.aluguel_centavos is None:
        linhas.append(_ALUGUEL_AUSENTE)
    else:
        linha = f"Aluguel estimado {reais_de(rentabilidade.aluguel_centavos)}"
        if rentabilidade.yield_pct is not None:
            # Virgula decimal porque o lead e brasileiro, e `:.1f` para o zero
            # a direita: "6%" e "6,0%" dizem coisas diferentes sobre precisao.
            percentual = f"{rentabilidade.yield_pct:.1f}".replace(".", ",")
            linha += f" - yield bruto {percentual}% ao ano"
        linhas.append(linha)
    if rentabilidade.custos_centavos is not None:
        linhas.append(f"Condominio + IPTU {reais_de(rentabilidade.custos_centavos)}/mes")
    if rentabilidade.aluguel_centavos is not None:
        linhas.append(RESSALVA_DE_ESTIMATIVA)
    return linhas
```

Dentro de `legenda_de`, **depois** do bloco do `Destaque:` e **antes** de `corpo = "\n".join(linhas)`:

```python
    if ficha.rentabilidade is not None:
        # No CORPO, e nao no prefixo: e o que faz `_prosa_que_cabe` proteger o
        # bloco de graca quando o teto de 600 aperta. A prioridade da D14
        # (corta-se a prosa, nunca a ficha) segue valendo sem mudanca.
        linhas.extend(_linhas_da_rentabilidade(ficha.rentabilidade))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`
Expected: PASS. Confirme que `test_a_legenda_traz_os_oito_campos_da_rn_10_1` continua verde — é a garantia de que a trilha padrão não mudou.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/apresentacao.py tests/unit/test_apresentacao.py
git commit -m "feat(TEC-154): a ficha do investidor ganha tres linhas no fim, com ressalva

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `fichas_do_catalogo` monta a `Rentabilidade`

**Files:**
- Modify: `src/mobia/domain/agente/ferramenta_de_busca.py`
- Test: `tests/integration/test_fichas_do_catalogo.py`

**Interfaces:**
- Consumes: `Rentabilidade`, `yield_bruto_anual`, `custos_recorrentes` (Task 1); `Ficha.rentabilidade` (Task 2).
- Produces: `fichas_do_catalogo(session_factory, *, ids, precos, com_rentabilidade: bool = False)`. Default `False` — todo chamador existente segue idêntico. O parâmetro é `com_rentabilidade`, e não `rentabilidade`, porque no corpo da função ele conviveria com o argumento `rentabilidade=` do `Ficha(...)`: dois nomes iguais e tipos diferentes na mesma expressão.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/integration/test_fichas_do_catalogo.py`. O helper `_imovel(session, codigo, **sobrescritas)` já existe ali e já tem `preco_venda=51646430`, `preco_aluguel=350000` e `condominio=55000` nos defaults; `iptu_mensal` não está nos defaults e é nulável, então passe explícito. Acrescente `from decimal import Decimal` ao topo e `Rentabilidade` não é necessário (as asserções são sobre os campos).

```python
async def test_sem_a_flag_a_ficha_nao_traz_rentabilidade(session: Any) -> None:
    """A trilha padrao nao muda de comportamento por causa desta card."""
    identificador = await _imovel(session, "AP-2001", iptu_mensal=32000)

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.rentabilidade is None


async def test_o_yield_sai_do_preco_de_venda_e_nao_do_preco_apresentado(
    session: Any,
) -> None:
    """D2: NUNCA de `Ficha.preco_centavos`.

    O `precos` passado aqui e o ALUGUEL, que e o que um investidor buscando
    ALUGUEL produziria. Se o yield saisse dele, a conta seria 1200% ao ano.
    Saindo de `preco_venda`, e 6,0% -- e 5,8% se alguem trocar a fonte pelo
    `preco_centavos` do default do helper, entao o numero desta asserta
    distingue as tres possibilidades.
    """
    identificador = await _imovel(
        session,
        "AP-2002",
        preco_venda=50_000_000,
        preco_aluguel=250_000,
        iptu_mensal=32000,
    )

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[identificador],
        precos={identificador: 250_000},
        com_rentabilidade=True,
    )

    assert ficha.rentabilidade is not None
    assert ficha.rentabilidade.aluguel_centavos == 250_000
    assert ficha.rentabilidade.yield_pct == Decimal("6.0")
    assert ficha.rentabilidade.custos_centavos == 55000 + 32000


async def test_imovel_sem_aluguel_ganha_rentabilidade_sem_numero(session: Any) -> None:
    """O objeto EXISTE (e investidor) e o aluguel e None (o catalogo nao tem).

    Devolver `None` no lugar do objeto colapsaria os dois estados, e a ficha
    nao teria como imprimir `Aluguel estimado: nao informado`.
    """
    identificador = await _imovel(
        session, "AP-2003", preco_aluguel=None, iptu_mensal=32000
    )

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[identificador],
        precos={identificador: 51646430},
        com_rentabilidade=True,
    )

    assert ficha.rentabilidade is not None
    assert ficha.rentabilidade.aluguel_centavos is None
    assert ficha.rentabilidade.yield_pct is None
    assert ficha.rentabilidade.custos_centavos == 55000 + 32000
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_fichas_do_catalogo.py -v --tb=short`
Expected: FAIL com `TypeError: fichas_do_catalogo() got an unexpected keyword argument 'com_rentabilidade'`.

Se aparecer `ConnectionResetError [WinError 64]` no setup, não é o seu código: espere e rode de novo antes de diagnosticar qualquer coisa.

- [ ] **Step 3: Implementar**

Acrescente ao import de `apresentacao` no topo do arquivo: `Rentabilidade`, `custos_recorrentes`, `yield_bruto_anual`. Depois:

```python
async def fichas_do_catalogo(
    session_factory: Any,
    *,
    ids: Sequence[uuid.UUID],
    precos: Mapping[uuid.UUID, int],
    com_rentabilidade: bool = False,
) -> tuple[Ficha, ...]:
```

E no corpo do `Ficha(...)`, como último argumento:

```python
            # TEC-154. Default `False`, entao a trilha padrao nao paga nada.
            # O yield sai de `imovel.preco_venda` e NUNCA de `precos[...]`:
            # aquele e o preco da operacao BUSCADA, e num investidor que
            # buscasse ALUGUEL ele seria o aluguel -- yield de 1200% ao ano
            # numa ficha que o lead le como fato. E a D7 desta funcao ao
            # contrario: la a coluna nao podia ser lida, aqui ela e a unica
            # fonte correta.
            rentabilidade=(
                Rentabilidade(
                    aluguel_centavos=imovel.preco_aluguel,
                    yield_pct=yield_bruto_anual(imovel.preco_aluguel, imovel.preco_venda),
                    custos_centavos=custos_recorrentes(imovel.condominio, imovel.iptu_mensal),
                )
                if com_rentabilidade
                else None
            ),
```

Acrescente também ao docstring da função o parágrafo que explica o parâmetro novo e por que o yield não usa `precos`.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_fichas_do_catalogo.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ferramenta_de_busca.py tests/integration/test_fichas_do_catalogo.py
git commit -m "feat(TEC-154): fichas_do_catalogo monta a rentabilidade a partir das colunas do catalogo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: O turno liga o bloco na trilha do investidor

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (`_apresentar`, e a chamada dela em `executar_turno`)
- Test: `tests/integration/test_turno_investidor.py`

**Interfaces:**
- Consumes: `fichas_do_catalogo(..., com_rentabilidade=...)` (Task 3).
- Produces: `_apresentar(..., investidor: bool)` — parâmetro **obrigatório**, keyword-only como os vizinhos. Obrigatório de propósito: há um único chamador, e um default silenciaria a trilha do investidor se alguém acrescentasse um segundo.

- [ ] **Step 1: Preparar o helper local e escrever os testes que falham**

O `_imovel` local de `tests/integration/test_turno_investidor.py` (linha ~397) hoje não aceita sobrescritas e não semeia `preco_aluguel`. Dê a ele a mesma forma do irmão em `test_fichas_do_catalogo.py`: acrescente `**sobrescritas: object` à assinatura e aplique-as sobre um dict de campos, em vez de passar tudo literal ao `Imovel(...)`. Mantenha os defaults atuais intactos — outros testes do arquivo dependem deles.

Depois, acrescente ao fim do arquivo:

```python
async def test_a_ficha_do_investidor_traz_os_indicadores(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-07.3: quem esta na trilha do investidor recebe os numeros na ficha.

    O yield afirmado aqui vale por uma asserta da D2 tambem: `_candidato_de`
    manda `preco_centavos=51_646_430` e a linha tem `preco_venda=50_000_000`.
    6,0% so sai se a conta usar a COLUNA; usar o preco apresentado daria 5,8%.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    imovel = await _imovel(
        session, "AP-1004", preco_venda=50_000_000, preco_aluguel=250_000, iptu_mensal=32_000
    )
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    classificador.candidatos_do_investidor = [_candidato_de("AP-1004", imovel)]
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    fichas = [texto for texto in outbound.entregues if "Apartamento AP-1004" in texto]
    assert fichas, "nenhuma ficha foi entregue -- o teste nao afirmaria nada"
    assert "Aluguel estimado R$ 2.500 - yield bruto 6,0% ao ano" in fichas[0]
    assert "Condominio + IPTU R$ 870/mes" in fichas[0]
    assert fichas[0].endswith("Estimativa, nao e garantia de retorno.")


async def test_a_ficha_de_comprador_nao_traz_indicador_nenhum(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A trilha padrao nao mudou: o MESMO imovel, sem numero de rentabilidade.

    Sem este par, um bug que ligasse o bloco para todo mundo passaria -- o
    teste irmao continuaria verde.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.COMPRA.value)
    imovel = await _imovel(
        session, "AP-1005", preco_venda=50_000_000, preco_aluguel=250_000, iptu_mensal=32_000
    )
    classificador = classificador_fake(Intencao.COMPRA)
    classificador.candidatos = [_candidato_de("AP-1005", imovel)]
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    fichas = [texto for texto in outbound.entregues if "Apartamento AP-1005" in texto]
    assert fichas, "nenhuma ficha foi entregue -- o teste nao afirmaria nada"
    assert "yield" not in fichas[0]
    assert "Estimativa" not in fichas[0]
```

`R$ 870` é `55000 + 32000` centavos truncados por `reais_de`; `R$ 2.500` é `250_000`. Se o default de `condominio` no helper local for outro, refaça as duas contas em vez de ajustar o código.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_investidor.py -v --tb=short`
Expected: FAIL — o primeiro teste não acha `yield bruto` na legenda.

- [ ] **Step 3: Implementar**

Em `_apresentar`, acrescente o parâmetro keyword-only `investidor: bool` junto dos outros e repasse:

```python
    fichas = await fichas_do_catalogo(
        session_factory, ids=ids, precos=precos, com_rentabilidade=investidor
    )
```

Acrescente ao docstring de `_apresentar`:

```
    **`investidor` liga o bloco da RN-07.3 e nada mais.** Ele decide a forma
    da ficha, nunca quais imoveis entram nela: a busca e a escolha sao as
    mesmas das duas trilhas.
```

Na chamada em `executar_turno` (o bloco `texto, quantas, suprimidas = await _apresentar(...)`), acrescente:

```python
                # TEC-154, D9. O gatilho e a TRILHA, nunca `perfil_investidor`:
                # a Emenda E-01 da RN-07.2 fixa que perfil ausente e NULL e nao
                # MISTO, e proibiu esta card de tratar os dois como um so. Um
                # Ricardo que ainda nao respondeu horizonte e investidor do
                # mesmo jeito, e a ficha dele leva os numeros.
                #
                # As duas variaveis, e nao so `ja_e_investidor`: no turno da
                # VIRADA a intencao ainda nao esta no estado que
                # `montar_contexto` leu, e sem `virou_investidor` a primeira
                # apresentacao do investidor sairia sem bloco -- justo a que
                # ele esperava.
                investidor=ja_e_investidor or virou_investidor,
```

Antes de editar, confirme por leitura que `virou_investidor` está atribuída **acima** deste ponto e no mesmo escopo. Se não estiver, pare e reporte em vez de mover a atribuição.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_investidor.py tests/integration/test_turno.py -v --tb=short`
Expected: PASS nos dois arquivos.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_turno_investidor.py
git commit -m "feat(TEC-154): a trilha do investidor apresenta a ficha com os indicadores

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A continuação de entrega parcial não perde o bloco

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (`_continuar_entrega`)
- Test: `tests/integration/test_turno_investidor.py`

**Interfaces:**
- Consumes: `ler_estado(session, channel, conversation_key) -> LeadQualification | None` de `mobia.domain.context.repositorio` — recebe **session**, não `session_factory`.
- Produces: nada novo; `_continuar_entrega` mantém a assinatura.

- [ ] **Step 1: Escrever o teste que falha**

`_continuar_entrega` é chamada direto, sem passar por `executar_turno`: o que está sob teste é ela escolher a forma da ficha, não o desvio que a aciona (que a TEC-275 já cobre). Ela precisa de um `Message` de verdade, porque grava `record_agent_message` e concilia a apresentação.

Acrescente ao topo do arquivo — **no topo, não dentro da função**: `Message` é usada como anotação de retorno, e o Python 3.13 avalia anotações no `def`, então um import local levantaria `NameError` antes de qualquer teste rodar.

```python
from mobia.domain.agente.repositorio import LinhaDaApresentacao
from mobia.domain.agente.turno import _continuar_entrega
from mobia.domain.messages.models import (
    Message,
    MessageContentType,
    MessageDirection,
    MessageRole,
    MessageStatus,
)
from mobia.infra.db import get_sessionmaker
```

O arquivo já importa `Imovel` e `LeadQualification` dos seus módulos; siga a ordem que o `ruff` impõe (ele reclama no gate se ficar fora). Ao lado de `_imovel`, este helper — copiado de `test_reserva_liberada.py`, como manda a convenção de arquivos autocontidos, e devolvendo o objeto e não só o id:

```python
async def _mensagem_do_lead(session: Any) -> Message:
    """Uma mensagem ja processada, para a continuacao ter o que continuar."""
    identificador = uuid.uuid4()
    mensagem = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        conversation_key=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        status=MessageStatus.PROCESSED,
    )
    session.add(mensagem)
    await session.commit()
    return mensagem
```

E o teste:

```python
async def test_a_continuacao_de_um_investidor_mantem_os_indicadores(
    session, outbound_fake
) -> None:
    """D7: sem isto a ficha 1 sai com yield e a 2, minutos depois, sem -- a
    mesma apresentacao em dois formatos, e quem ve a diferenca e o LEAD.

    `_continuar_entrega` roda ANTES de `montar_contexto` e por isso nao tem
    `contexto.estado` nem `ja_e_investidor`; quem responde "que trilha e
    esta?" e `ler_estado`.
    """
    from datetime import UTC, datetime

    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    mensagem = await _mensagem_do_lead(session)
    imovel = await _imovel(
        session, "AP-1006", preco_venda=50_000_000, preco_aluguel=250_000, iptu_mensal=32_000
    )
    lote = [
        LinhaDaApresentacao(
            imovel_id=imovel,
            preco_centavos=50_000_000,
            kind="ficha_2",
            apresentado_em=datetime.now(UTC),
        )
    ]
    outbound = outbound_fake()

    await _continuar_entrega(
        get_sessionmaker(),
        message=mensagem,
        outbound=outbound,
        lote=lote,
        ja_reservados=frozenset(),
    )

    assert outbound.entregues, "nada foi entregue -- o teste nao afirmaria nada"
    assert "yield bruto 6,0% ao ano" in outbound.entregues[0]
    assert outbound.entregues[0].endswith("Estimativa, nao e garantia de retorno.")
```


- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_investidor.py -k continuacao -v --tb=short`
Expected: FAIL na asserção do `yield bruto` — a legenda sai sem o bloco.

Se falhar antes disso, com erro de construção do `Message` ou de `LinhaDaApresentacao`, é o helper e não a card: confira os campos contra `mobia/domain/messages/models.py` e `repositorio.py:533` antes de mexer em `turno.py`.

- [ ] **Step 3: Implementar**

Acrescente `ler_estado` ao import existente de `mobia.domain.context.repositorio` no topo de `turno.py` (mantendo a ordem alfabética do bloco). Em `_continuar_entrega`, logo antes da chamada a `fichas_do_catalogo`:

```python
    # TEC-154, D7. Esta funcao roda ANTES de `montar_contexto` e por isso nao
    # tem `contexto.estado` nem `ja_e_investidor` -- e a mesma cegueira que o
    # comentario de `record_agent_message`, mais abaixo, declara para a
    # telemetria. Ali a consequencia so aparece para quem opera; aqui
    # apareceria para o LEAD, que receberia a ficha 1 com yield e as fichas 2
    # e 3 sem. Uma consulta fecha isso.
    #
    # **Custo declarado: o estado lido e o de AGORA, nao o do instante da
    # apresentacao original.** Coincidem em praticamente todo caso, porque a
    # continuacao reprocessa a MESMA mensagem e o turno que moveria a intencao
    # e justamente o que esta sendo continuado. A alternativa exata -- gravar a
    # trilha na linha de `recomendacoes` -- custa coluna, migration e mais uma
    # tabela no TRUNCATE de todo teste que toca banco.
    async with session_factory() as session:
        estado = await ler_estado(session, message.channel, message.conversation_key)
    # Contra `.value` porque a coluna e str, e nao o enum -- mesma comparacao
    # que `ja_e_investidor` faz em `executar_turno`.
    investidor = estado is not None and estado.intencao == Intencao.INVESTIMENTO.value

    fichas = await fichas_do_catalogo(
        session_factory, ids=ids, precos=precos, com_rentabilidade=investidor
    )
```

Acrescente ao docstring de `_continuar_entrega` um parágrafo dizendo que ela lê o estado só para escolher a forma da ficha, nunca para mudar o que é entregue.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_investidor.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_turno_investidor.py
git commit -m "feat(TEC-154): a continuacao de entrega le o estado e mantem a ficha coerente

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: O cenário 4, as emendas ao SRS e o fecho

**Files:**
- Test: `tests/unit/test_classificador_investidor.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

**Interfaces:**
- Consumes: `SISTEMA_DO_INVESTIDOR` (TEC-153, já existe).
- Produces: nada de código.

- [ ] **Step 1: Escrever o teste do cenário 4**

O cenário 4 do Gherkin já é atendido pelo prompt da TEC-153 (L3 do desenho). Esta card prende a frase:

```python
def test_o_prompt_do_investidor_proibe_projetar_valorizacao() -> None:
    """Cenario 4 da TEC-154, atendido pela TEC-153 e sem teste ate agora.

    Sem esta assercao, alguem que encurtasse o prompt por orcamento levaria a
    proibicao junto e nenhum teste reclamaria -- e a RN-04.4 proibe afirmar
    rentabilidade futura como certa.
    """
    baixo = SISTEMA_DO_INVESTIDOR.lower()
    assert "nao prometa rentabilidade nem projete valorizacao" in baixo
```

Confira o texto exato da constante antes de escrever a asserção; se a frase estiver grafada de outro jeito, use a grafia real em vez de mudar o prompt.

- [ ] **Step 2: Rodar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador_investidor.py -v`
Expected: PASS de primeira — o comportamento já existe. Um FAIL aqui significa que a frase mudou de forma e que a asserção precisa da grafia real.

- [ ] **Step 3: Escrever as três emendas ao SRS**

Cada uma entra como item **aninhado** abaixo da regra que altera, **sem reescrever** o texto de 22/08/2026. As regras estão em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` nas linhas da RN-07.3, RN-07.5 e RN-10.1. O texto das três está pronto na seção "Emendas ao SRS" do desenho — copie de lá, no formato `**Emenda E-nn (TEC-154, 14/09/2026):**`, conferindo o `nn` disponível em cada regra.

- [ ] **Step 4: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`. `VIZINHO` é a categoria que importa: comentário que ninguém editou, dentro de `def`/`class` cujo código mudou — é ele que esconde o defeito da TEC-146. Confira em particular a docstring de `Ficha` ("os oito campos da RN-10.1"), a de `fichas_do_catalogo` (a D7 sobre `precos`) e o comentário de `record_agent_message` em `_continuar_entrega`, que declara a cegueira de trilha que a Task 5 acabou de fechar **para as fichas** e que **continua valendo para a telemetria**.

- [ ] **Step 5: Os três gates e a suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta; guarde o hash junto com o resultado. Se ela **falhar**, repita sobre a mesma árvore antes de culpar a mudança — e leia o traceback antes de decidir: `relation ... does not exist` em dezenas de testes são os bancos dos workers com o carimbo adiantado, não a sua alteração.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_classificador_investidor.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-154): tres emendas ao SRS e o teste que prende a proibicao de projetar valorizacao

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite

| Cenário do Gherkin | Onde é exercitado |
|---|---|
| 1 — calcular e exibir o yield (6,0%) | Task 1, `test_o_yield_do_gherkin_sai_com_uma_casa_e_zero_a_direita`; Task 2, o bloco inteiro |
| 1 — a ressalva acompanha | Task 2, `test_o_bloco_do_investidor_sai_no_fim_com_a_ressalva_por_ultimo` |
| 2 — condomínio + IPTU na apresentação | Task 1, `test_os_custos_recorrentes_somam_condominio_e_iptu`; Task 2 |
| 3 — sem aluguel, nenhum yield e o agente informa | Task 2, `test_sem_aluguel_a_ficha_diz_que_o_dado_nao_existe_e_nao_ressalva_nada` |
| 4 — não projetar valorização | Task 6, `test_o_prompt_do_investidor_proibe_projetar_valorizacao` (comportamento da TEC-153) |

**Decisão sem task, de propósito:** a D8 do desenho manda `_candidato_serializavel` **não** ganhar campo — o yield fora do `tool_result`. É uma decisão de não fazer, então não há passo a executar; o que a guarda é o comentário daquela função, que já explica por que número nenhum de diagnóstico entra ali (D7 da TEC-265). Se alguma task acabar acrescentando o campo, ela contradiz o desenho.

**Sem exercício, e declarado:** `yieldBrutoAnual` do `POST /api/v1/imoveis/busca` (SRS §6.3) — o agente chama o domínio direto e nunca consome aquela rota; o campo nasceria sem consumidor. Ver a L2 do desenho.
