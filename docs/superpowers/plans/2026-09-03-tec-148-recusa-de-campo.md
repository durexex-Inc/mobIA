# TEC-148 — Recusa de campo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O lead que diz "prefiro não falar disso agora" para de ser reperguntado, para de contar como qualificado naquele campo, e para de pontuar a completude dele.

**Architecture:** O modelo relata a recusa num campo novo do schema de saída; uma função pura filtra os nomes pelo vocabulário e subtrai o que o turno preencheu; a coluna acumula por união em SQL e perde o campo quando o valor chega; `esta_qualificado` e `calcular_score` leem a coluna.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, Postgres (`ARRAY`, `array_remove`), pytest + pytest-asyncio, Anthropic structured output.

**Spec:** [`docs/superpowers/specs/2026-09-03-tec-148-recusa-de-campo-design.md`](../specs/2026-09-03-tec-148-recusa-de-campo-design.md) — leia antes da Task 1. O plano argumenta a partir dela.

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Convenção do repo, não checada por linter nenhum. Prosa em `docs/` leva acento.
- **Os três gates estáticos, nesta ordem, antes de cada commit.** O formatador é um gate separado do linter:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **O escopo é `src tests alembic evals`, não `src tests`.** Ruff `line-length = 100`, `select = ["E","F","I","UP","B"]`, target py313.
- **O orçamento do prompt é apertado e tem ritual.** Teto **fixo de 655**, e esta card gasta **14,75** dos 23,8 de margem: o líquido vai de 631,2 a 645,95 e a margem fica em **9,05**. O teto **não se move**. Confira sempre com `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`, e **não** meça com `json.dumps(separators=(",", ":"))` — o teste serializa com os separadores padrão, e a forma compacta subestima em 1,5 token.
- **Comentário explica o porquê, não o quê, e comentário desatualizado é defeito.** Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **TDD, e cada teste verificado por mutação.** Depois de verde, quebre de propósito a linha que o teste cobre e confirme que ele fica vermelho — e vermelho *naquele* teste.
- **A suíte é lenta:** `tests/unit` ~7 min, inteira ~7,5 min, e imprime só no fim. Rode o arquivo ou o teste durante o ciclo; a suíte inteira só na última task.
- **Testes de integração flakeiam sob carga, não isolados.** Antes de atribuir uma falha a você, rode o arquivo sozinho.
- **Mensagens de commit:** português sem acento no assunto, `tipo(TEC-148): o que passou a ser verdade`.
- **Postgres e Redis** sobem por `docker compose`, porta 5433. Depois de um `restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` mesmo com o container `healthy` — espere e retente.

## File Structure

| arquivo | responsabilidade |
|---|---|
| `src/mobia/domain/agente/classificador.py` | **Modificar.** `recusou` no schema, `_ORDEM_DOS_CAMPOS`, o normalizador compartilhado, e a montagem da resposta. |
| `src/mobia/domain/agente/schemas.py` | **Modificar.** `recusou: tuple[str, ...]` em `RespostaDoAgente`. |
| `src/mobia/domain/context/models.py` | **Modificar.** A coluna `campos_recusados`. |
| `alembic/versions/0013_recusa_de_campo.py` | **Criar.** A coluna, nulável, sem backfill. |
| `src/mobia/domain/context/repositorio.py` | **Modificar.** `campos_a_recusar` (pura) e a gravação em `gravar_estado`. |
| `src/mobia/domain/context/qualificacao.py` | **Modificar.** `campos_obrigatorios_preenchidos` passa a receber `recusados`. |
| `src/mobia/domain/context/score.py` | **Modificar.** `calcular_score` ganha `recusados` keyword-only. |
| `src/mobia/domain/agente/turno.py` | **Modificar.** Passa `recusou` para `gravar_estado` e `recusados` para `esta_qualificado`. |
| `tests/unit/test_classificador.py` | **Modificar.** Os usos de `_perguntou` viram do nome novo, e entram os testes de `recusou`. |
| `tests/unit/test_config.py` | **Modificar.** A docstring do teste de orçamento registra o gasto. |
| `tests/unit/test_recusa.py` | **Criar.** `campos_a_recusar`, `esta_qualificado` e `calcular_score` com recusa. |
| `tests/integration/test_recusa.py` | **Criar.** Gravação, desfazimento pelo valor, concorrência, migration. |

**Uma extração deliberada.** `_perguntou` em `classificador.py` normaliza "lista de string, filtrando o que não é string", e `recusou` precisa exatamente disso. Duplicar o corpo seria duplicação; reusar `_perguntou` para os dois deixaria a docstring dele (*"os nomes de campo que o modelo diz ter perguntado neste turno"*) mentindo no segundo uso, que neste repo é defeito e não sujeira. A Task 1 extrai `_lista_de_nomes` e atualiza os usos — inclusive os seis em `tests/unit/test_classificador.py`, que importa `_perguntou` por nome.

---

### Task 1: O modelo passa a relatar recusa

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py`
- Modify: `src/mobia/domain/agente/schemas.py`
- Modify: `tests/unit/test_classificador.py`
- Modify: `tests/unit/test_config.py` (só a docstring do teste de orçamento)

**Interfaces:**
- Produces: `_lista_de_nomes(bruto: Any) -> tuple[str, ...]` em `classificador.py`; o campo `recusou` em `SCHEMA_DA_RESPOSTA`; `RespostaDoAgente.recusou: tuple[str, ...]` com default `()`.
- Consumes: nada de tasks anteriores.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_classificador.py`, **troque** as duas funções que testam `_perguntou` (por volta das linhas 280-298) pelas de baixo, e **troque o import** de `_perguntou` por `_lista_de_nomes`:

```python
def test_lista_de_nomes_chega_como_tupla():
    """Serve `perguntou` e `recusou`: os dois sao o modelo relatando nomes de
    campo sobre o proprio turno, e a normalizacao e a mesma."""
    assert _lista_de_nomes(["regiao", "vagas"]) == ("regiao", "vagas")


def test_lista_de_nomes_tolera_forma_errada_sem_levantar():
    """O turno ja foi pago e ja tem resposta valida para o lead: forma errada
    num campo de relato nao pode custa-lo."""
    assert _lista_de_nomes(None) == ()
    assert _lista_de_nomes("regiao") == ()
    assert _lista_de_nomes(["regiao", 7, None, "bairro"]) == ("regiao", "bairro")
```

E **acrescente** ao mesmo arquivo:

```python
def test_recusou_esta_no_schema_como_array_de_string():
    from mobia.domain.agente.classificador import SCHEMA_DA_RESPOSTA

    assert SCHEMA_DA_RESPOSTA["properties"]["recusou"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_recusou_vem_depois_de_perguntou_na_ordem_dos_campos():
    """A TEC-240 recusou reordenar campos do schema mesmo a custo zero de
    tokens: muda a ordem de geracao do modelo num caminho pago, em todo turno
    de producao. Acrescentar no fim e a unica posicao que nao mexe no que ja
    existe.
    """
    from mobia.domain.agente.classificador import _ORDEM_DOS_CAMPOS

    assert _ORDEM_DOS_CAMPOS[-2:] == ("perguntou", "recusou")


def test_recusou_default_e_tupla_vazia_no_dataclass():
    """Turno que nao relata recusa nao e turno com recusa vazia por acidente:
    o default explicito e o que faz o chamador antigo continuar valendo."""
    from dataclasses import fields

    from mobia.domain.agente.schemas import RespostaDoAgente

    campo = next(f for f in fields(RespostaDoAgente) if f.name == "recusou")
    assert campo.default == ()
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -v -k "lista_de_nomes or recusou"
```

Esperado: `ImportError: cannot import name '_lista_de_nomes'`.

- [ ] **Step 3: Renomear o normalizador**

Em `src/mobia/domain/agente/classificador.py`, troque a definição de `_perguntou` (linha ~238) por:

```python
def _lista_de_nomes(bruto: Any) -> tuple[str, ...]:
    """Nomes de campo que o modelo declara sobre o proprio turno.

    Serve `perguntou` (o que ele perguntou) e `recusou` (o que o lead se
    negou a informar). Uma funcao para os dois porque a normalizacao e
    identica, e duas copias divergiriam -- a divergencia so apareceria na
    borda, que e onde este tipo de campo erra.

    Nao valida os nomes de proposito: quem filtra contra `fields(Extracao)`
    sao `campos_a_marcar` e `campos_a_recusar`, que tambem logam o que
    descartaram. Duas filtragens divergiriam.

    Nao levanta nunca. Estes campos sao o modelo relatando o que ele mesmo
    fez -- uma forma errada aqui nao pode custar o turno inteiro, que ja foi
    pago e ja tem resposta valida para o lead.
    """
    if not isinstance(bruto, list):
        return ()
    return tuple(item for item in bruto if isinstance(item, str))
```

- [ ] **Step 4: Acrescentar o campo ao schema e à ordem**

No mesmo arquivo, na definição de `SCHEMA_DA_RESPOSTA["properties"]`, **logo depois** da linha de `"perguntou"`:

```python
        # TEC-148. Os campos que o lead se negou a informar, declarados pelo
        # modelo. Mesma forma de `perguntou`, e no fim pela mesma razao: a
        # TEC-240 recusou reordenar campos do schema porque muda a ordem de
        # geracao num caminho pago em todo turno.
        #
        # Custou 14,75 tokens do orcamento, e o teto de 655 nao se mexeu --
        # ver a docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada`.
        "recusou": {"type": "array", "items": {"type": "string"}},
```

E a tupla de ordem:

```python
_ORDEM_DOS_CAMPOS = ("intencao", "confianca", "extracao", "resposta", "perguntou", "recusou")
```

- [ ] **Step 5: Ligar na montagem da resposta**

Na construção de `RespostaDoAgente` (linha ~496), troque a linha de `perguntou` por estas duas:

```python
                perguntou=_lista_de_nomes(dados.get("perguntou")),
                recusou=_lista_de_nomes(dados.get("recusou")),
```

- [ ] **Step 6: Acrescentar o campo ao dataclass**

Em `src/mobia/domain/agente/schemas.py`, logo depois de `perguntou`:

```python
    # TEC-148. Os campos que o lead se negou a informar neste turno,
    # declarados pelo proprio modelo. Vem depois de `perguntou` no schema --
    # ver `_ORDEM_DOS_CAMPOS`.
    #
    # Tupla e nao list, como `perguntou`: o dataclass e frozen, e uma list
    # mutavel dentro dele seria congelamento de fachada.
    recusou: tuple[str, ...] = ()
```

- [ ] **Step 7: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -v
```

Esperado: todos passam. Se algum outro teste do arquivo usava `_perguntou`, ele aparece aqui — corrija o nome.

- [ ] **Step 8: Medir o orçamento e registrar na docstring**

```
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Esperado: passa, com `liquido 645.9` e `margem 9.1` na tabela impressa. **Se o número não for esse, pare e reporte** — não ajuste o teto.

Depois acrescente ao **fim** da docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada` em `tests/unit/test_config.py`:

```
    A TEC-148 gastou 14,75 dos 23,8 que a TEC-257 havia deixado, e o teto
    NAO se mexeu: o liquido foi de 631,2 para 645,95 e a margem ficou em
    9,05. Todo o custo foi o campo `recusou` no schema -- o prompt nao ganhou
    texto, porque a clausula "nao repergunte o preenchido nem o ignorado" da
    TEC-257 ja cobre recusa, e o campo recusado ja vem marcado
    "(perguntado, sem resposta)" do turno em que foi perguntado.

    Cuidado ao remedir: a conta acima serializa o schema com `json.dumps`
    sem `separators`, entao cada `,` e `:` carrega um espaco. Medir com
    `separators=(",", ":")` subestima -- neste campo, 13,25 em vez de 14,75.
```

- [ ] **Step 9: Verificar por mutação**

Remova `"recusou"` de `_ORDEM_DOS_CAMPOS` e rode `tests/unit/test_classificador.py`: esperado, o import do módulo levanta `RuntimeError` da guarda — que é o comportamento correto e prova que a guarda pega o esquecimento. Desfaça. Depois troque `_lista_de_nomes(dados.get("recusou"))` por `()` e rode: esperado, nenhum teste desta task fica vermelho, porque nenhum exercita a montagem ainda. **Registre isso no relatório** — a cobertura desse fio vem na Task 5.

- [ ] **Step 10: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/classificador.py src/mobia/domain/agente/schemas.py tests/unit/test_classificador.py tests/unit/test_config.py
git commit -m "feat(TEC-148): o modelo passa a relatar o campo que o lead recusou"
```

---

### Task 2: A coluna `campos_recusados`

**Files:**
- Create: `alembic/versions/0013_recusa_de_campo.py`
- Modify: `src/mobia/domain/context/models.py`
- Create: `tests/integration/test_recusa.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `LeadQualification.campos_recusados: Mapped[list[str] | None]`. Migration `0013`, `down_revision = "0012"`.
- Consumes: nada de tasks anteriores.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_recusa.py`:

```python
"""A recusa de campo: coluna, gravacao e as duas leituras.

TEC-148.
"""

from sqlalchemy import select

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linha(session, **ajustes: object) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste mudar."""
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.ATE_3_MESES.value,
    }
    linha = LeadQualification(**{**base, **ajustes})
    session.add(linha)
    await session.commit()
    return linha


async def test_a_coluna_aceita_lista_e_devolve_lista(session) -> None:
    await _linha(session, campos_recusados=["faixa_preco_max"])

    gravada = (await session.scalars(select(LeadQualification))).one()
    assert gravada.campos_recusados == ["faixa_preco_max"]


async def test_null_e_vazio_sao_estados_diferentes_na_coluna(session) -> None:
    """`NULL` e "linha anterior a esta card, ninguem registrava"; `{}` e
    "registrava, e nao havia recusa". Quem le trata os dois igual, mas a
    coluna guarda a diferenca."""
    await _linha(session, campos_recusados=None)
    nula = (await session.scalars(select(LeadQualification))).one()
    assert nula.campos_recusados is None

    nula.campos_recusados = []
    await session.commit()
    vazia = (await session.scalars(select(LeadQualification))).one()
    assert vazia.campos_recusados == []
```

E acrescente a `tests/integration/test_migrations.py` (junte os imports aos que já existem):

```python
async def test_a_0013_desce_e_sobe_de_novo() -> None:
    """A coluna some no downgrade e volta no upgrade, sem backfill."""
    await dispose_engine()
    alembic("downgrade", "0012")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'lead_qualification' "
                        "AND column_name = 'campos_recusados'"
                    )
                )
                == 0
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'lead_qualification' "
                    "AND column_name = 'campos_recusados'"
                )
            )
            == 1
        )
```

> **Nunca faça `downgrade` abaixo de `0012`.** A migration `0004` não pode ser ciclada neste banco de desenvolvimento — a tabela `messages` acumula tombstones de coluna derrubada a cada ciclo, e o teto do Postgres é 1600. Descer até lá quebra o ambiente e exige reconstruir o banco.

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v
```

Esperado: `TypeError` sobre `campos_recusados` não ser argumento válido de `LeadQualification`.

- [ ] **Step 3: Acrescentar a coluna ao modelo**

Em `src/mobia/domain/context/models.py`, em `LeadQualification`, logo depois de `perguntados_sem_resposta`:

```python
    # TEC-148, RN-05.7. Os campos que o lead se negou a informar.
    #
    # O nome vem do modelo de dados do SRS (`campos_recusados text[]`), e nao
    # de `recusados`, que e o nome do PARAMETRO que `esta_qualificado` expoe
    # desde a TEC-147. Coluna e parametro nao precisam coincidir.
    #
    # Coluna propria e nao reuso de `perguntados_sem_resposta`: silencio e
    # recusa sao fatos diferentes. Silencio e "pode ser que ele responda
    # depois"; recusa e "ele disse que nao". Colapsa-los tornaria
    # inqualificavel para sempre todo lead que apenas ainda nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos, como na coluna vizinha: `NULL` e
    # "linha anterior a esta card, ninguem registrava", `{}` e "registrava, e
    # nao havia recusa". Quem le trata os dois iguais (`or ()`), e nunca grava
    # `NULL` querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    campos_recusados: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)), nullable=True
    )
```

- [ ] **Step 4: Escrever a migration**

Crie `alembic/versions/0013_recusa_de_campo.py`:

```python
"""os campos que o lead se negou a informar

TEC-148, RN-05.7. Coluna nulavel e sem backfill: `NULL` significa "linha
anterior a esta card, ninguem registrava recusa", e isso e informacao que um
backfill para `{}` apagaria. Ver o comentario da coluna no modelo.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("campos_recusados", postgresql.ARRAY(sa.String(32)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "campos_recusados")
```

- [ ] **Step 5: Aplicar e rodar**

```
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py -v
```

Esperado: 2 passed no primeiro, todos no segundo. `ConnectionResetError [WinError 64]` é flake conhecido — retente.

- [ ] **Step 6: Verificar por mutação**

Troque `nullable=True` por `nullable=False` na migration, cicle (`downgrade 0012` e `upgrade head`) e rode `tests/integration/test_recusa.py`: esperado, `test_null_e_vazio_sao_estados_diferentes_na_coluna` fica vermelho. Desfaça e cicle de volta.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0013_recusa_de_campo.py src/mobia/domain/context/models.py tests/integration/test_recusa.py tests/integration/test_migrations.py
git commit -m "feat(TEC-148): a recusa ganha coluna, e NULL continua diferente de vazio"
```

---

### Task 3: A regra da recusa, e a gravação que a desfaz

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py`
- Create: `tests/unit/test_recusa.py`
- Modify: `tests/integration/test_recusa.py`

**Interfaces:**
- Consumes: `LeadQualification.campos_recusados` (Task 2).
- Produces: `campos_a_recusar(recusou: Iterable[str], preenchidos: Iterable[str]) -> set[str]`; `gravar_estado` ganha o parâmetro `recusou: Iterable[str] = ()`.

- [ ] **Step 1: Escrever os testes unitários que falham**

Crie `tests/unit/test_recusa.py`:

```python
"""A regra da recusa de campo, sem banco.

TEC-148.
"""

from mobia.domain.context.repositorio import campos_a_recusar


def test_o_nome_do_orcamento_e_traduzido_para_a_forma_canonica():
    """O orcamento tem varios nomes neste repo, e o unico que o modelo pode
    dizer nao e coluna. `_marca_de` traduz, e e a mesma traducao que
    `campos_a_marcar` usa -- duas divergiriam."""
    assert campos_a_recusar(["faixa_preco_expressao"], []) == {"faixa_preco_max"}


def test_nome_fora_do_vocabulario_e_descartado_e_nao_adivinhado():
    """Recusa inventada faz o agente parar de perguntar um obrigatorio e
    `esta_qualificado` devolver False para sempre, em silencio. Descartar e o
    erro barato."""
    assert campos_a_recusar(["bairro_favorito"], []) == set()


def test_campo_preenchido_neste_turno_nao_entra_como_recusado():
    """Cenario 2 da card: valor vence recusa. Se o lead informou o campo, ele
    nao esta recusando o campo."""
    assert campos_a_recusar(["regiao"], ["regiao"]) == set()


def test_o_orcamento_preenchido_por_qualquer_extremo_cancela_a_recusa_dele():
    """"a partir de 300 mil" preenche so o minimo, e responde a pergunta sobre
    orcamento. Sem a traducao dos DOIS lados, a recusa ficaria de pe sobre um
    campo que o lead acabou de responder."""
    assert campos_a_recusar(["faixa_preco_expressao"], ["faixa_preco_min_centavos"]) == set()


def test_nomes_repetidos_nao_duplicam():
    assert campos_a_recusar(["regiao", "regiao"], []) == {"regiao"}


def test_sem_recusa_devolve_vazio():
    assert campos_a_recusar([], ["regiao"]) == set()
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_recusa.py -v
```

Esperado: `ImportError: cannot import name 'campos_a_recusar'`.

- [ ] **Step 3: Escrever a função pura**

Em `src/mobia/domain/context/repositorio.py`, logo depois de `campos_a_marcar`:

```python
def campos_a_recusar(recusou: Iterable[str], preenchidos: Iterable[str]) -> set[str]:
    """Os campos que o lead se negou a informar neste turno.

    Mesma forma de `campos_a_marcar` e pelos mesmos motivos: e regra unica,
    compartilhada entre producao e o runner do eval, e os nomes passam por
    `_marca_de` antes de qualquer coisa porque o orcamento tem varios nomes
    neste repo e o unico que o modelo pode dizer nao e coluna.

    **Nome fora do vocabulario e descartado, nao adivinhado.** Aqui isso pesa
    mais que na marca: recusa inventada faz o agente parar de perguntar um
    campo obrigatorio e `esta_qualificado` devolver False para sempre, sem
    alarme e sem o lead perceber. Descartar custa uma pergunta a mais.

    **`preenchidos` subtrai, e e o cenario 2 da card:** se o lead informou o
    campo neste turno, ele nao esta recusando o campo. Vale para os dois
    extremos do orcamento -- "a partir de 300 mil" preenche so o minimo e
    responde a pergunta sobre orcamento.

    A subtracao aqui cobre o turno corrente. Desfazer uma recusa ANTERIOR
    quando o valor chega e feito no SQL de `gravar_estado`, que e o unico
    lugar que ve o array acumulado.
    """
    conhecidos: set[str] = set()
    ignorados: list[str] = []
    for nome in dict.fromkeys(recusou):
        marca = _marca_de(nome)
        if marca is None:
            ignorados.append(nome)
        else:
            conhecidos.add(marca)

    if ignorados:
        plausiveis = sorted({n for n in ignorados if _NOME_PLAUSIVEL.fullmatch(n)})
        log.warning(
            "estado.campo_recusado_desconhecido",
            nomes=plausiveis,
            descartados=len(ignorados) - len(plausiveis),
        )

    return conhecidos - {_marca_de(nome) or nome for nome in preenchidos}
```

- [ ] **Step 4: Rodar os unitários**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_recusa.py -v
```

Esperado: 6 passed.

- [ ] **Step 5: Escrever os testes de integração da gravação**

Acrescente a `tests/integration/test_recusa.py` (junte os imports):

```python
from mobia.domain.agente.schemas import Extracao
from mobia.domain.context.repositorio import gravar_estado


async def test_gravar_estado_acumula_a_recusa(session) -> None:
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="vila mariana"),
        recusou=["faixa_preco_expressao"],
    )
    await session.commit()

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == ["faixa_preco_max"]


async def test_o_valor_posterior_desfaz_a_recusa(session) -> None:
    """Cenario 2 da card, atravessando turnos: a recusa de um turno anterior
    sai quando o valor chega, e isso e feito no SQL porque so ele ve o array
    acumulado."""
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="vila mariana"),
        recusou=["faixa_preco_expressao"],
    )
    await session.commit()

    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(faixa_preco_max_centavos=60_000_000),
    )
    await session.commit()

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == []
    assert linha.faixa_preco_max_centavos == 60_000_000


async def test_recusas_de_turnos_diferentes_se_acumulam(session_factory) -> None:
    """Uniao e `array_remove` compoem entre turnos, em sessoes diferentes.

    **O que este teste NAO prova:** que a uniao precisa morar no SQL. As
    operacoes abaixo sao sequenciais, e sob READ COMMITTED a segunda leitura
    ja ve o commit da primeira -- uma uniao feita em Python passaria
    identicamente. A perda concorrente (duas sessoes que leem o mesmo array
    antes de qualquer uma gravar) nao tem teste direto aqui: forcar o
    interleaving exigiria `asyncio.gather` sem garantia de ordem, e teste
    flaky e pior que teste ausente.

    A uniao em SQL segue justificada pela mesma razao que a da coluna irma
    `perguntados_sem_resposta` (TEC-257), cuja corrida tambem nunca foi
    testada. Lacuna declarada no desenho.
    """
    async with session_factory() as a, session_factory() as b:
        await gravar_estado(
            a,
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA,
            extracao=Extracao(regiao="vila mariana"),
            recusou=["faixa_preco_expressao"],
        )
        await a.commit()

        await gravar_estado(
            b,
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA,
            extracao=Extracao(quartos=2),
            recusou=["urgencia"],
        )
        await b.commit()

    async with session_factory() as c:
        linha = (await c.scalars(select(LeadQualification))).one()
        assert sorted(linha.campos_recusados or []) == ["faixa_preco_max", "urgencia"]
```

> **Por que `session_factory` e não `session`:** a fixture `session` entrega **uma** sessão, e duas recusas na mesma sessão não exercitam nada de concorrência. `session_factory` já existe em `tests/conftest.py` e devolve o sessionmaker.

- [ ] **Step 6: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v
```

Esperado: `TypeError` — `gravar_estado` não aceita `recusou`.

- [ ] **Step 7: Ligar na gravação**

Em `gravar_estado`, acrescente o parâmetro depois de `perguntou`:

```python
    perguntou: Iterable[str] = (),
    recusou: Iterable[str] = (),
```

Acrescente à docstring, ao final:

```
    `recusou` tem default de proposito, como `perguntou`: nenhum chamador
    antigo precisa saber da TEC-148 para continuar funcionando, e nao
    registrar recusa e o comportamento seguro.
```

Depois de `marcados = sorted(campos_a_marcar(perguntou, campos))`, acrescente:

```python
    recusados = sorted(campos_a_recusar(recusou, campos))
    # Os nomes que este turno preencheu, na forma canonica da marca -- e o que
    # sai do array acumulado no SQL abaixo.
    respondidos = sorted({_marca_de(nome) or nome for nome in campos})
```

E em `valores`, ao lado de `perguntados_sem_resposta`:

```python
        # Sempre presente, mesmo vazio, pela mesma razao da coluna vizinha:
        # `NULL` esta reservado para "linha anterior a esta card".
        "campos_recusados": recusados,
```

E no `set_` do `on_conflict_do_update`, acrescente a expressão abaixo. **Ela une e subtrai numa passagem**, e a subtração é o que desfaz uma recusa anterior quando o valor chega:

```python
                # Uniao em SQL pela razao da coluna vizinha: dois turnos
                # concorrentes da mesma conversa leriam o mesmo array, cada um
                # uniria o seu, e o mais lento sobrescreveria em silencio.
                #
                # `array_remove` encadeado tira o que este turno respondeu --
                # o cenario 2 da card, atravessando turnos. Ele remove TODAS
                # as ocorrencias, entao duplicata no array nao sobrevive; e
                # sao no maximo os campos de `Extracao`, entao a cadeia e
                # curta e conhecida.
                "campos_recusados": _sem_os_respondidos(
                    func.coalesce(
                        LeadQualification.campos_recusados,
                        literal_column("'{}'::varchar[]"),
                    ).op("||")(statement.excluded.campos_recusados),
                    respondidos,
                ),
```

E, acima de `gravar_estado`, o auxiliar:

```python
def _sem_os_respondidos(expressao: Any, respondidos: list[str]) -> Any:
    """Encadeia `array_remove` para tirar do array cada campo respondido.

    Existe como funcao para o laco nao poluir o dicionario do `set_`, que ja
    e o trecho mais denso de `gravar_estado`. Postgres nao tem operador de
    subtracao de array; `array_remove` e o built-in, e remove todas as
    ocorrencias do elemento.
    """
    for nome in respondidos:
        expressao = func.array_remove(expressao, nome)
    return expressao
```

- [ ] **Step 8: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v
./.venv/Scripts/python.exe -m pytest tests/unit/test_recusa.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_contexto.py -v
```

Esperado: todos passam. O terceiro é a regressão de `gravar_estado`, que muitos testes exercitam.

- [ ] **Step 9: Verificar por mutação**

Troque `conhecidos - {...}` por `conhecidos` em `campos_a_recusar`: esperado, `test_campo_preenchido_neste_turno_nao_entra_como_recusado` e o do orçamento ficam vermelhos. Desfaça. Depois faça `_sem_os_respondidos` devolver `expressao` sem o laço: esperado, `test_o_valor_posterior_desfaz_a_recusa` fica vermelho e os outros dois de integração seguem verdes. Desfaça.

- [ ] **Step 10: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/unit/test_recusa.py tests/integration/test_recusa.py
git commit -m "feat(TEC-148): a recusa acumula em SQL, e o valor que chega a desfaz"
```

---

### Task 4: A qualificação e o score param de contar campo recusado

**Files:**
- Modify: `src/mobia/domain/context/qualificacao.py`
- Modify: `src/mobia/domain/context/score.py`
- Modify: `tests/unit/test_recusa.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (as duas funções são puras).
- Produces: `campos_obrigatorios_preenchidos(estado, recusados: frozenset[str] = frozenset()) -> int`; `calcular_score(..., *, recusados: frozenset[str] = frozenset())`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/unit/test_recusa.py`:

```python
from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import (
    campos_obrigatorios_preenchidos,
    esta_qualificado,
)
from mobia.domain.context.score import calcular_score


def _estado(**ajustes: object) -> LeadQualification:
    base: dict[str, object] = {
        "channel": "whatsapp",
        "conversation_key": "5511911112222",
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.ATE_3_MESES.value,
    }
    return LeadQualification(**{**base, **ajustes})


def test_campo_recusado_com_valor_na_coluna_nao_conta_como_preenchido():
    """E o caso que distingue esta card do marcador da TEC-257: la
    "valor vence marca", entao um campo com valor antigo renderiza o valor e a
    marca fica invisivel. Aqui a recusa tem de vencer o valor."""
    estado = _estado()
    assert campos_obrigatorios_preenchidos(estado) == 4
    assert campos_obrigatorios_preenchidos(estado, frozenset({"faixa_preco_max"})) == 3


def test_lead_com_obrigatorio_recusado_nao_esta_qualificado():
    estado = _estado()
    assert esta_qualificado(estado) is True
    assert esta_qualificado(estado, frozenset({"faixa_preco_max"})) is False


def test_o_score_para_de_pontuar_a_completude_do_campo_recusado():
    """A divergencia que a TEC-150 declarou e esta card fecha: sem isto,
    `esta_qualificado` e o score contam historias contrarias sobre o mesmo
    lead, e a TEC-151 ordena a fila por um numero que a qualificacao
    contradiz."""
    estado = _estado()
    cheio = calcular_score(estado, mensagens_do_lead=1)
    recusado = calcular_score(
        estado, mensagens_do_lead=1, recusados=frozenset({"faixa_preco_max"})
    )

    assert cheio.completude - recusado.completude == 5
    assert cheio.total - recusado.total == 5


def test_recusar_campo_que_nao_e_obrigatorio_nao_muda_score_nem_qualificacao():
    """`forma_pagamento` nao esta na RN-05.3, e a completude conta so os
    quatro obrigatorios. Recusa-la nao mexe na completude -- e o fator de
    capacidade nao consulta recusa, o que fica declarado no desenho."""
    estado = _estado(forma_pagamento=FormaPagamento.A_VISTA.value)
    recusados = frozenset({"forma_pagamento"})

    assert campos_obrigatorios_preenchidos(estado, recusados) == 4
    assert esta_qualificado(estado, recusados) is True
    assert (
        calcular_score(estado, mensagens_do_lead=1, recusados=recusados).completude
        == calcular_score(estado, mensagens_do_lead=1).completude
    )
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_recusa.py -v -k "recusado or score or qualificado"
```

Esperado: `TypeError` — `campos_obrigatorios_preenchidos` aceita só um argumento.

- [ ] **Step 3: `campos_obrigatorios_preenchidos` passa a receber a recusa**

Em `src/mobia/domain/context/qualificacao.py`:

```python
def campos_obrigatorios_preenchidos(
    estado: LeadQualification | None, recusados: frozenset[str] = frozenset()
) -> int:
    """Quantos dos obrigatorios da RN-05.3 este lead ja informou.

    Existe para o score da TEC-150, que pontua completude a 5 pontos por
    campo. Devolve a contagem, e nao expoe `_preenchido`: o score precisa da
    resposta inteira, e publicar o passo a passo convidaria o proximo modulo
    a iterar `CAMPOS_OBRIGATORIOS` por conta propria -- meio caminho para uma
    segunda copia da lista, que e o defeito que a TEC-146 gastou uma card
    inteira para consertar.

    `recusados` entra na TEC-148 e usa a mesma regra de `esta_qualificado`:
    campo recusado nao conta, mesmo com valor na coluna. Sem isto, o score e
    a qualificacao contariam historias contrarias sobre o mesmo lead.

    O default vazio e o comportamento anterior a TEC-148, e mantem valendo o
    chamador que nao passa nada.
    """
    if estado is None:
        return 0
    negados = {_canonico(nome) for nome in recusados}
    return sum(
        1
        for campo in CAMPOS_OBRIGATORIOS
        if campo not in negados and _preenchido(estado, campo)
    )
```

- [ ] **Step 4: `calcular_score` passa a receber a recusa**

Em `src/mobia/domain/context/score.py`, na assinatura:

```python
def calcular_score(
    estado: LeadQualification | None,
    *,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
    recusados: frozenset[str] = frozenset(),
) -> Score:
```

Acrescente ao **final** da docstring de `calcular_score`. (Ela não tem parágrafo sobre recusa para substituir — a divergência ficou declarada no desenho da TEC-150, não no código; a única menção aqui é a linha do topo do módulo, que diz *"Mesma forma que `recusados` tem em `esta_qualificado`"* e continua verdadeira.)

```
    **`recusados` fecha a divergencia que esta card declarou.** Ate a
    TEC-148, campo recusado ainda pontuava a completude sobre um valor de um
    turno anterior, porque `calcular_score` nao recebia o conjunto. Recebe
    agora, e a regra e a mesma de `esta_qualificado`: recusado nao conta,
    mesmo com valor na coluna.

    **Apenas a completude consulta a recusa.** Nenhum outro dos cinco fatores
    o faz -- em particular, recusar `forma_pagamento` nao mexe na capacidade,
    que continua pontuando "a avaliar" pela coluna. Fica declarado.

    Keyword-only como os dois vizinhos, por consistencia da assinatura.
```

E na construção do `Score`:

```python
        completude=campos_obrigatorios_preenchidos(estado, recusados)
        * PONTOS_POR_CAMPO_OBRIGATORIO,
```

- [ ] **Step 5: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_recusa.py -v
./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py tests/unit/test_score.py -v
```

Esperado: todos passam. Os dois últimos são a regressão das cards anteriores.

- [ ] **Step 6: Verificar por mutação**

Remova `campo not in negados` de `campos_obrigatorios_preenchidos`: esperado, `test_campo_recusado_com_valor_na_coluna_nao_conta_como_preenchido` e `test_o_score_para_de_pontuar_a_completude_do_campo_recusado` ficam vermelhos. Desfaça. Depois remova `_canonico` da compreensão de `negados` e rode: esperado, o teste que passa `faixa_preco_max` fica vermelho, porque `CAMPOS_OBRIGATORIOS` usa `faixa_preco`. Desfaça.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/qualificacao.py src/mobia/domain/context/score.py tests/unit/test_recusa.py
git commit -m "feat(TEC-148): campo recusado para de contar na qualificacao e na completude do score"
```

---

### Task 5: O turno liga tudo

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Modify: `src/mobia/domain/context/repositorio.py` (só `registrar_recalculo`)
- Modify: `tests/integration/test_recusa.py`

**Interfaces:**
- Consumes: `RespostaDoAgente.recusou` (Task 1); `gravar_estado(..., recusou=...)` (Task 3); `esta_qualificado(estado, recusados)` e `calcular_score(..., recusados=...)` (Task 4).
- Produces: nada de novo — o comportamento passa a existir em produção.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/integration/test_recusa.py`:

```python
from decimal import Decimal

from mobia.domain.context.models import LeadScoreAudit


async def test_o_turno_grava_a_recusa_que_o_modelo_relatou(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake,
    contador_fake,
) -> None:
    await rodar_turno(
        session,
        classificador_fake(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            extracao=Extracao(regiao="vila mariana"),
            recusou=("faixa_preco_expressao",),
        ),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == ["faixa_preco_max"]


async def test_a_trilha_de_score_registra_a_recusa_como_queda_de_completude(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake,
    contador_fake,
) -> None:
    """A consequencia declarada da D5: o score de quem recusa CAI, e a
    auditoria da TEC-152 registra a queda com causa CAMPOS_OBRIGATORIOS.
    Isso e a auditoria funcionando, nao regressao."""
    def turno(extracao, recusou=()):
        return rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA,
                confianca=Decimal("0.95"),
                extracao=extracao,
                recusou=recusou,
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    await turno(
        Extracao(
            regiao="vila mariana",
            urgencia=Urgencia.ATE_3_MESES,
            faixa_preco_max_centavos=50_000_000,
        )
    )
    await turno(Extracao(), recusou=("faixa_preco_expressao",))

    registros = (
        await session.scalars(select(LeadScoreAudit).order_by(LeadScoreAudit.created_at))
    ).all()
    assert len(registros) == 2
    assert registros[-1].causas == ["CAMPOS_OBRIGATORIOS"]
    assert registros[-1].total_anterior - registros[-1].total_novo == 5
```

**O `ClassificadorFake` precisa aceitar `recusou`.** Abra `tests/conftest.py`, ache `class ClassificadorFake` e acrescente o parâmetro ao `__init__` e ao `RespostaDoAgente` que ele devolve, no mesmo molde de `extracao`.

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v -k turno
```

Esperado: `TypeError` no `ClassificadorFake` antes de você editar o conftest; depois, `assert None == ['faixa_preco_max']`.

- [ ] **Step 3: Passar a recusa na gravação do turno**

Em `src/mobia/domain/agente/turno.py`, na chamada a `gravar_estado` do bloco transacional, acrescente:

```python
            recusou=gerada.recusou,
```

E acrescente ao comentário que já explica por que `perguntou` fica fora desse `gravar_estado`:

```python
    # `recusou` entra AQUI, ao contrario de `perguntou`: e fato sobre a fala
    # do lead, nao sobre a nossa resposta. Saida bloqueada e envio fora da
    # janela nao descartam uma recusa que o lead de fato disse.
```

- [ ] **Step 4: Passar a recusa nas duas leituras**

No mesmo arquivo, as duas comparações de qualificação passam a levar a recusa. Extraia o `frozenset` para uma função de módulo, em vez de repetir a expressão ternária nos dois pontos — ela é longa, aparece duas vezes e a segunda ocorrência é dentro de um `if` que já é denso:

```python
def _recusados_de(estado: LeadQualification | None) -> frozenset[str]:
    """A recusa da linha, na forma que `esta_qualificado` recebe.

    `or ()` porque `NULL` e `{}` na coluna significam coisas diferentes e a
    leitura trata as duas iguais -- ver o comentario da coluna. `frozenset` e
    nao `set` porque e o que a assinatura da TEC-147 pede.
    """
    if estado is None:
        return frozenset()
    return frozenset(estado.campos_recusados or ())
```

Depois troque as duas chamadas:

```python
    antes = esta_qualificado(contexto.estado, _recusados_de(contexto.estado))
```

```python
    if not antes and esta_qualificado(depois_do_estado, _recusados_de(depois_do_estado)):
```

`LeadQualification` já está importado em `turno.py`? Confira; se não estiver, acrescente `from mobia.domain.context.models import LeadQualification` ao bloco de imports existente.

Em `src/mobia/domain/context/repositorio.py`, dentro de `registrar_recalculo`, passe a recusa ao score:

```python
    novo = calcular_score(
        estado,
        mensagens_do_lead=await contar_mensagens_do_lead(
            session, channel=channel, conversation_key=conversation_key
        ),
        imoveis_compativeis=0,
        # TEC-148: a recusa sai da mesma linha que o lock acabou de reler,
        # entao nao ha consulta extra e nao ha risco de ler estado velho.
        recusados=frozenset(estado.campos_recusados or ()),
    )
```

- [ ] **Step 5: Rodar e confirmar que passa**

Um arquivo por vez — integração aqui flakeia sob carga:

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_recusa.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_extracao_no_turno.py -v
```

Esperado: todos passam.

- [ ] **Step 6: Verificar por mutação**

Remova `recusou=gerada.recusou` da chamada a `gravar_estado`: esperado, os dois testes de turno desta task ficam vermelhos e os das tasks 1-4 seguem verdes. Desfaça. Depois remova `recusados=...` de `registrar_recalculo`: esperado, só `test_a_trilha_de_score_registra_a_recusa_como_queda_de_completude` fica vermelho. Desfaça.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py src/mobia/domain/context/repositorio.py tests/conftest.py tests/integration/test_recusa.py
git commit -m "feat(TEC-148): a recusa do lead passa a valer em producao"
```

---

### Task 6: A emenda ao SRS, e a suíte inteira

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (a linha da `RN-05.7`)

**Interfaces:** nenhuma. É documentação, e o repo trata emenda como parte da entrega.

- [ ] **Step 1: Acrescentar a emenda**

A **RN-05.7** diz que o campo *"não é reperguntado na mesma conversa"*, e esta card entrega escopo de lead — desvio, não interpretação. Emendas entram como item **aninhado** abaixo da regra, **nunca** reescrevendo o texto de 22/08/2026. A numeração é por regra e a RN-05.7 não tem emenda, logo é `E-01`. Veja a emenda da RN-05.4, três linhas acima, para o formato exato.

Abaixo da linha da `RN-05.7`, acrescente:

```markdown
  - **Emenda E-01 (TEC-148, 03/09/2026):** a recusa vale para o **lead**, e não para a conversa. Não há fronteira de conversa no sistema: `conversation_key` é o id externo do lead, e `messages`, `lead_qualification`, `conversation_summaries` e `optout_events` todos o usam com esse sentido; introduzir a entidade de conversa é maior que esta card e fica deferido. A consequência é que o campo recusado não é reperguntado **nunca**, e não só na conversa corrente — erro na direção de não incomodar o lead. A recusa também deixa de contar na qualificação (RN-05.3) e na completude do score (RN-06.1), fechando a divergência que a TEC-150 declarou.
```

- [ ] **Step 2: Conferir que emendou e não reescreveu**

```
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md
```

Esperado: só linhas acrescentadas (`+`). Um `-` significa que você substituiu texto que tem de ser preservado.

- [ ] **Step 3: Rodar a suíte inteira**

Agora, e não antes — leva ~8 minutos e imprime só no fim, o que parece travamento e não é:

```
./.venv/Scripts/python.exe -u -m pytest -q
```

Esperado: todos passam. Falha isolada em `test_montagem.py`, `test_sweep_stalled.py` ou `test_dedup_por_message_id.py` sob carga não é regressão desta card — rode o arquivo sozinho para confirmar. Falha que reproduz em isolamento é real e você tem de reportá-la.

- [ ] **Step 4: Os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-148): a RN-05.7 passa a valer para o lead, e nao para a conversa"
```

---

## Checklist de fechamento

- [ ] Os três gates passam com o escopo `src tests alembic evals`.
- [ ] A suíte inteira passa.
- [ ] `pytest -q -k margem_do_orcamento -s` imprime margem 9,1 e o teto continua 655.
- [ ] `alembic downgrade 0012 && alembic upgrade head` funciona duas vezes seguidas. **Nunca desça abaixo de 0012.**
- [ ] Nenhum comentário descreve código que mudou.
- [ ] A emenda no SRS só acrescentou linhas.
- [ ] Abrir PR contra `main` a partir de `feat/tec-148-recusa-de-campo`.
