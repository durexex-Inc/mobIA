# TEC-158 — Busca híbrida de imóveis: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o catálogo passa a responder "quais imóveis atendem ao que o lead descreveu", com o filtro estruturado resolvido em SQL antes da similaridade vetorial, no máximo 10 candidatos, e cada candidato carregando o identificador e o preço lidos do banco.

**Architecture:** uma consulta só. O `WHERE` resolve preço, quartos, vagas, tipo, região e status; o `ORDER BY` combina `0,6 × similaridade + 0,4 × aderência ao teto de preço`; o `LIMIT` aplica o teto de 10. A região casa por uma coluna nova `bairro_busca` — o bairro dobrado — em união com a `zona`. O vetor da consulta vem de um embedador injetado, e a falta dele degrada para filtro puro em vez de devolver vazio.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async (Core `select()`), Postgres 16 + pgvector, Alembic, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-07-tec-158-busca-hibrida-design.md`

## Global Constraints

- **Preços em centavos, `int`, nos dois lados.** `preco_venda`/`preco_aluguel` são `BigInteger` em centavos; `faixa_preco_*_centavos` também. **Nenhuma conversão** na borda da busca.
- **`operacao` é obrigatória** no filtro. `COLUNA_DE_PRECO = {VENDA: "preco_venda", ALUGUEL: "preco_aluguel"}` — `AMBOS` **não é chave** desse dicionário.
- **O filtro de operação é `IN (operacao, 'AMBOS')`**, nunca igualdade crua.
- **`status = 'DISPONIVEL'` é literal no `WHERE`, não parâmetro.** RN-08.4.
- **Pesos:** `PESO_SIMILARIDADE = 0.6`, `PESO_ADERENCIA = 0.4`. **Teto:** `MAX_CANDIDATOS = 10`. Constantes de módulo, **não** `Settings`.
- **Aderência:** `clamp(1 - |preco - teto| / teto, 0, 1)`, e `1` quando não há teto. Existe **uma vez**, como expressão SQL montada em Python — nunca uma gêmea em Python puro.
- **Similaridade presa em [0, 1]** com `GREATEST(0, 1 - (embedding <=> vetor))`, e `COALESCE(..., 0)` **explícito** — não confie no `GREATEST` ignorar `NULL`.
- **Score:** `float` arredondado a 3 casas via `round(cast(expr, Numeric), 3)`. **Nunca `Decimal`** no domínio.
- **`dobrar` faz caixa e acento, e só isso.** Não come prefixo de referência.
- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Convenção do repo, não checada por linter nenhum.
- **Prosa em `docs/`: com acento.** Emendas ao SRS entram como item aninhado `Emenda E-nn (TEC-158, 07/09/2026)` abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026.
- **Nenhuma chamada de rede na suíte.** O embedador é sempre falso em teste (`EmbedadorFake`, já em `tests/conftest.py`).
- **Basename de teste não pode colidir** entre `tests/unit/` e `tests/integration/` — colisão aborta a coleta da suíte inteira e não aparece em execução isolada. Já custou duas cards.
- **Nenhuma tabela nova.** `imoveis` já está em `TABELAS` (`tests/conftest.py`); não acrescente nada lá.
- **Os três gates, no escopo exato do CI**, antes de **cada** commit — o formatador é gate separado do linter, e passar num não diz nada sobre o outro:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **A suíte leva ~22 minutos e lentidão aqui parece travamento.** Rode arquivo isolado durante o desenvolvimento; a suíte inteira uma vez, no fim. Se for precisar diagnosticar, peça `--tb=short` desde o início — `-q` só imprime o nome do teste que falhou.
- **Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos** com `ConnectionResetError [WinError 64]` **mesmo com o container `healthy`**. Espere e retente antes de diagnosticar.
- **Mensagem de commit:** `tipo(TEC-158): o que passou a ser verdade`, assunto em português **sem acento**.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/mobia/domain/texto.py` | **Novo.** `dobrar(texto)`. Pura, sem I/O | 1 |
| `tests/unit/test_dobra_de_texto.py` | **Novo.** A dobra, e o que ela não faz | 1 |
| `alembic/versions/0019_busca_hibrida.py` | **Nova.** `bairro_busca`, backfill em Python, dois índices | 1 |
| `src/mobia/domain/catalogo/models.py` | A coluna e os dois índices no ORM | 1 |
| `src/mobia/domain/catalogo/repositorio.py` | Grava `bairro_busca` nos dois caminhos de escrita | 1 |
| `src/mobia/domain/agente/schemas.py` | `_sem_acento` sai; `normalizar_regiao` compõe sobre `dobrar` | 1 |
| `tests/integration/test_catalogo_upsert.py` | A dobra se mantém depois de inserir e de atualizar | 1 |
| `src/mobia/domain/catalogo/schemas.py` | `FiltroDeBusca`, `Candidato`, `ResultadoDaBusca` | 2 |
| `src/mobia/domain/catalogo/busca.py` | **Novo.** `buscar`, `zonas_de`, a expressão da aderência, as constantes | 2, 3 |
| `tests/unit/test_busca_pontuacao.py` | **Novo.** `zonas_de` e o clamp do limite | 2 |
| `tests/integration/test_busca_hibrida.py` | **Novo.** Os quatro cenários do Gherkin e o que o desenho decidiu | 2, 3 |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Emendas à RN-09.1, RN-09.6 e RN-08.2 | 2, 3 |
| `src/mobia/workers/jobs/indexar_catalogo.py` | Só a docstring: a afirmação de topologia | 3 |
| `src/mobia/api/routes/imoveis.py` | `POST /api/v1/imoveis/busca` | 4 |
| `tests/integration/test_busca_endpoint.py` | **Novo.** O contrato, o 422 e o 403 | 4 |

**Ordem das tasks e por quê:** a 1 é a única com migration, e as outras dependem da coluna existir. A 2 entrega a busca **sem** vetor (todos os cenários do Gherkin já passam ali). A 3 acrescenta a fase vetorial e a degradação. A 4 expõe por HTTP. Um revisor pode rejeitar a 3 aprovando a 2.

---

## Task 1: A dobra, a coluna `bairro_busca`, e uma definição só

**Files:**
- Create: `src/mobia/domain/texto.py`
- Create: `tests/unit/test_dobra_de_texto.py`
- Create: `alembic/versions/0019_busca_hibrida.py`
- Modify: `src/mobia/domain/catalogo/models.py`
- Modify: `src/mobia/domain/catalogo/repositorio.py`
- Modify: `src/mobia/domain/agente/schemas.py`
- Test: `tests/integration/test_catalogo_upsert.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `mobia.domain.texto.dobrar(texto: str) -> str`. `Imovel.bairro_busca: Mapped[str]` (não nulável). Os índices `ix_imoveis_bairro_busca` e `ix_imoveis_filtro`.

- [ ] **Step 1: Escreva o teste da dobra que falha**

Crie `tests/unit/test_dobra_de_texto.py`:

```python
"""A dobra de texto que a busca estruturada compara.

TEC-158, D6. Basename distinto de tudo em `tests/integration/`.
"""

from mobia.domain.agente.schemas import normalizar_regiao
from mobia.domain.texto import dobrar


def test_dobra_caixa_e_acento() -> None:
    assert dobrar("Aclimação") == "aclimacao"
    assert dobrar("Vila Madalena") == "vila madalena"
    assert dobrar("SÃO PAULO") == "sao paulo"


def test_dobra_e_idempotente() -> None:
    uma_vez = dobrar("Aclimação")
    assert dobrar(uma_vez) == uma_vez


def test_dobra_colapsa_espaco_interno() -> None:
    # Um arquivo com dois espacos nao pode deixar a linha inalcancavel.
    assert dobrar("  Vila   Madalena  ") == "vila madalena"


def test_a_dobra_nao_come_prefixo_de_referencia() -> None:
    """A diferenca entre `dobrar` e `normalizar_regiao`, afirmada.

    `estacao ` e `avenida ` sao ruido de FALA. Aplicados a nome de bairro
    comeriam o nome de um bairro chamado "Estacao" -- por isso a dobra
    compartilhada nao os toca, e so `normalizar_regiao` os remove.
    """
    assert dobrar("Estação Vila Madalena") == "estacao vila madalena"
    assert normalizar_regiao("estacao vila madalena") == "vila madalena"


def test_normalizar_regiao_continua_dobrando() -> None:
    """A composicao nao pode ter perdido a dobra pelo caminho."""
    assert normalizar_regiao("perto da Aclimação") == "aclimacao"
```

- [ ] **Step 2: Rode e confirme que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_dobra_de_texto.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.texto'`.

- [ ] **Step 3: Crie `src/mobia/domain/texto.py`**

```python
"""A dobra de texto que a busca estruturada compara.

TEC-158, D6. Funcao pura: sem banco, sem rede, sem `Settings`.

**Mora fora de `catalogo/` e de `agente/` porque os dois a usam.** A
importacao do catalogo grava `bairro_busca` com ela; `normalizar_regiao`
dobra a fala do lead com ela. Qualquer das duas casas obrigaria um dominio a
importar o outro -- e a D2 desta card decidiu que `catalogo` nao importa
`agente`, sendo a seta contraria igualmente errada.

**Faz caixa e acento, e nada mais.** Os prefixos de referencia de
`normalizar_regiao` (`perto da `, `estacao `, `avenida `) sao ruido de FALA:
aplicados a nome de bairro comeriam o nome de um bairro chamado "Estacao".
"""

import unicodedata


def dobrar(texto: str) -> str:
    """A forma comparavel de um texto: sem acento, em caixa dobrada.

    NFD separa o diacritico do caractere base e `combining` identifica o que
    sobra para descartar. Pega cedilha junto: "aclimacao" com til e cedilha
    decompoe nos dois, e os dois somem. O corpo desta funcao veio do
    `_sem_acento` que morava em `agente/schemas.py`, e a medicao que o
    justifica esta na docstring de `normalizar_regiao`: a TEC-248 mediu o
    modelo devolvendo `saude` COM acento e `butanta` SEM, na mesma execucao.

    `casefold` e nao `lower`: dobra mais que minusculas, e comparacao de
    igualdade e exatamente o caso de uso dele.

    Espaco interno e colapsado: "vila  madalena" e "vila madalena" sao o
    mesmo bairro, e um arquivo com dois espacos nao pode deixar a linha
    inalcancavel pela busca.
    """
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if not unicodedata.combining(caractere)
    )
    return " ".join(sem_acento.split()).casefold()
```

- [ ] **Step 4: Recomponha `normalizar_regiao` sobre `dobrar`**

Em `src/mobia/domain/agente/schemas.py`: **apague** a função `_sem_acento` inteira (incluindo a docstring, que vai para `dobrar` resumida) e acrescente o import:

```python
from mobia.domain.texto import dobrar
```

Substitua as três primeiras linhas do corpo de `normalizar_regiao`:

```python
    limpo = " ".join(texto.split()).casefold()
    # Acento sai ANTES dos prefixos, e a ordem nao e detalhe: o modelo devolveu
    # "vila madalena (perto da estacao)" com acento em `estacao`, e um prefixo
    # escrito sem acento nunca casaria com ele. Dobrar depois deixaria o
    # prefixo dentro do valor.
    limpo = _sem_acento(limpo)
```

por:

```python
    # Acento sai ANTES dos prefixos, e a ordem nao e detalhe: o modelo devolveu
    # "vila madalena (perto da estacao)" com acento em `estacao`, e um prefixo
    # escrito sem acento nunca casaria com ele. Dobrar depois deixaria o
    # prefixo dentro do valor.
    #
    # A dobra vem de `domain/texto.py` desde a TEC-158: a MESMA funcao grava
    # `imoveis.bairro_busca` na importacao. Duas expressoes equivalentes em
    # arquivos diferentes divergem no dia em que uma delas muda, e a
    # divergencia aqui se manifestaria como bairro que o lead nomeia e a busca
    # nao encontra -- sem erro nenhum.
    limpo = dobrar(texto)
```

O resto da função (parênteses, vírgula, laço de prefixos) fica **intacto**.

- [ ] **Step 5: Rode os testes da dobra e os que já existiam de região**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_dobra_de_texto.py -v
./.venv/Scripts/python.exe -m pytest tests/unit -k regiao -v
```

Esperado: PASS nos dois. Os testes de `normalizar_regiao` que já existiam são o que prova que a recomposição não mudou comportamento — **se algum deles ficar vermelho, a ordem das operações foi alterada**, e o lugar para olhar é o `casefold` acontecendo depois do `unaccent` em vez de antes.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/texto.py tests/unit/test_dobra_de_texto.py src/mobia/domain/agente/schemas.py
git commit -m "refactor(TEC-158): a dobra de texto tem uma casa e dois consumidores"
```

- [ ] **Step 7: Escreva a migration `0019`**

Crie `alembic/versions/0019_busca_hibrida.py`:

```python
"""a coluna que faz o bairro do lead casar com o do banco

TEC-158, RN-09.1 e a emenda E-01 dela. O lead fala "aclimacao" (dobrado por
`normalizar_regiao`) e o banco guarda "Aclimacao" com til, como veio do
arquivo. Comparar os dois exige dobrar um dos lados.

**Por que uma coluna, e nao `unaccent()` na consulta.** `unaccent()` e STABLE
e nao IMMUTABLE, entao um indice funcional sobre ela exige um wrapper
IMMUTABLE declarado a mao -- uma mentira controlada sobre a funcao, que quebra
em silencio se alguem trocar o dicionario do unaccent. E a regra de dobra
passaria a existir em Python E em SQL: a divergencia se manifestaria como
bairro que o lead nomeia e a busca nao encontra, sem erro. Ver D5.

**Nao e coluna gerada, e a recusa e do Postgres.** `GENERATED ALWAYS AS ...
STORED` seria o desenho ideal -- derivada por construcao, impossivel de
esquecer. A expressao de coluna gerada tem de ser IMMUTABLE, e e justamente
`unaccent` que nao e.

**O backfill roda em Python, chamando a mesma `dobrar()` do caminho normal.**
Importar codigo da aplicacao numa migration nao e padrao novo: a `0004`
importa `mobia.infra.crypto`, e e por isso que `alembic` esta no escopo do
`ruff`. A alternativa era `CREATE EXTENSION unaccent` so para esta escrita
unica, o que instalaria uma extensao permanente e deixaria no schema o
convite a usa-la no caminho de LEITURA que a D5 recusou.

**O composto entra por conformidade, nao por medicao** -- mesma postura que a
`0017` assumiu com o `lists = 1` do IVFFlat. Com 520 a 2.000 imoveis o filtro
resolve em varredura sequencial em milissegundos. E ele so serve metade das
buscas: as colunas que o SRS nomeia incluem `preco_venda`, entao uma busca de
ALUGUEL usa no maximo o prefixo `(status, tipo)`. Quem mede os dois regimes e
decide se isso vira um segundo composto e a TEC-159.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op
from mobia.domain.texto import dobrar

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nulavel primeiro: nao ha valor a escrever antes do backfill, e um
    # server_default de '' faria a linha existente casar a busca por bairro
    # vazio em vez de nao casar nada.
    op.add_column("imoveis", sa.Column("bairro_busca", sa.Text(), nullable=True))

    conexao = op.get_bind()
    linhas = conexao.execute(sa.text("SELECT id, bairro FROM imoveis")).fetchall()
    for identificador, bairro in linhas:
        conexao.execute(
            sa.text("UPDATE imoveis SET bairro_busca = :dobrado WHERE id = :identificador"),
            {"dobrado": dobrar(bairro), "identificador": identificador},
        )

    op.alter_column("imoveis", "bairro_busca", nullable=False)

    op.create_index("ix_imoveis_bairro_busca", "imoveis", ["bairro_busca"])
    op.create_index(
        "ix_imoveis_filtro", "imoveis", ["status", "tipo", "preco_venda", "quartos"]
    )


def downgrade() -> None:
    op.drop_index("ix_imoveis_filtro", table_name="imoveis")
    op.drop_index("ix_imoveis_bairro_busca", table_name="imoveis")
    op.drop_column("imoveis", "bairro_busca")
```

- [ ] **Step 8: Acrescente a coluna e os índices ao ORM**

Em `src/mobia/domain/catalogo/models.py`, logo **abaixo** de `bairro`:

```python
    # TEC-158, D5. O `bairro` dobrado -- caixa e acento --, e e contra ela que
    # a `regiao` do lead compara. DERIVADA de `bairro` e escrita a mao: quem
    # gravar `bairro` tem de gravar esta na mesma instrucao.
    #
    # Nao e `GENERATED ALWAYS AS ... STORED`, e a recusa e do Postgres e nao do
    # gosto: a expressao de coluna gerada tem de ser IMMUTABLE, e dobrar acento
    # em SQL exige `unaccent()`, que e STABLE. O preco declarado dessa
    # impossibilidade e que existe um caminho em que esta coluna fica velha --
    # o escritor novo que esqueca. Hoje ha um escritor (`repositorio.py`); o
    # CRUD da TEC-197 sera o segundo. A guarda e o
    # `test_o_upsert_mantem_a_dobra_do_bairro`.
    bairro_busca: Mapped[str] = mapped_column(Text, nullable=False)
```

E em `__table_args__`, junto dos índices que já estão lá:

```python
        Index("ix_imoveis_bairro_busca", "bairro_busca"),
        # O composto que a secao de indices criticos do SRS nomeia para a
        # RN-09.1. Por conformidade, nao por medicao -- ver a `0019`.
        Index("ix_imoveis_filtro", "status", "tipo", "preco_venda", "quartos"),
```

- [ ] **Step 9: Faça o repositório gravar a dobra nos dois caminhos**

Em `src/mobia/domain/catalogo/repositorio.py`, acrescente o import:

```python
from mobia.domain.texto import dobrar
```

Logo **depois** da tupla `CAMPOS_COMPARADOS`, acrescente:

```python
# `bairro_busca` fica FORA de CAMPOS_COMPARADOS de proposito, e por dois
# motivos: ela nao vem do arquivo (`RegistroImovel` nao tem o campo, e
# `getattr` levantaria), e e derivada de `bairro`, que o diff ja compara --
# incluir as duas nao detecta nada a mais.
#
# Mas ela TEM de ser gravada nos dois caminhos de escrita. Sem isso, a linha
# vencedora da corrida documentada no header deste modulo fica com o
# `bairro` de um lote e a dobra do outro: um imovel que a busca por bairro
# nao encontra, sem erro nenhum e sem sintoma no relatorio.
def _derivados(valores: dict[str, object]) -> dict[str, object]:
    """Os campos que o banco guarda e o arquivo nao carrega. TEC-158, D5."""
    return {"bairro_busca": dobrar(str(valores["bairro"]))}
```

Nos **três** lugares de escrita:

1. No `novos.append(...)`:

```python
                novos.append(
                    {
                        "id": uuid.uuid4(),
                        "codigo": registro.codigo,
                        **valores,
                        **_derivados(valores),
                    }
                )
```

2. No laço que atualiza a linha existente, troque `valores.items()` por:

```python
            for campo, valor in {**valores, **_derivados(valores)}.items():
                setattr(existente, campo, valor)
```

3. No `set_` do `on_conflict_do_update`, acrescente antes do `updated_at`:

```python
                        # Derivada, entao nao esta em CAMPOS_COMPARADOS -- mas
                        # sem ela a linha perdedora da corrida teria o bairro
                        # sobrescrito e a dobra mantida.
                        "bairro_busca": comando.excluded["bairro_busca"],
```

- [ ] **Step 10: Escreva o teste de que a dobra se mantém**

Acrescente ao fim de `tests/integration/test_catalogo_upsert.py`:

```python
async def test_o_upsert_mantem_a_dobra_do_bairro(session: Any) -> None:
    """A guarda escrita da D5: `bairro_busca` acompanha `bairro`, sempre.

    Esta coluna e derivada e escrita a mao porque o Postgres nao permite
    coluna gerada com `unaccent` (STABLE, nao IMMUTABLE). O preco disso e que
    um escritor novo pode esquece-la; este teste e o que pega o esquecimento.

    Duas metades, porque sao dois caminhos de escrita diferentes: o INSERT e o
    UPDATE de linha existente.
    """
    # `_registro` (linha 72 deste arquivo) nao expoe `bairro` -- ele fixa
    # "Centro". `replace` do dataclasses ja esta importado aqui, e sobrescreve
    # sem mexer no helper que outros doze testes usam.
    await sincronizar(session, [replace(_registro("AP-7001"), bairro="Aclimação")])
    await session.commit()

    imovel = await session.scalar(select(Imovel).where(Imovel.codigo == "AP-7001"))
    assert imovel is not None
    assert imovel.bairro == "Aclimação"
    assert imovel.bairro_busca == "aclimacao"

    # Segunda metade: a linha existe, e o bairro muda. Este e o caminho do
    # `setattr`, e nao o do INSERT -- sao dois lugares diferentes no
    # repositorio, e um pode ter a dobra sem o outro.
    await sincronizar(session, [replace(_registro("AP-7001"), bairro="Vila Madalena")])
    await session.commit()

    await session.refresh(imovel)
    assert imovel.bairro == "Vila Madalena"
    assert imovel.bairro_busca == "vila madalena"
```

`replace` e `select` já estão importados nesse arquivo (linhas 15 e 19), e `_registro(codigo)` tem `linha` e `preco` com default — nada mais a importar.

- [ ] **Step 11: Aplique a migration e rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v --tb=short
```

Esperado: PASS. Se o `alembic upgrade` reprovar com `ConnectionResetError [WinError 64]`, **espere e retente** — o banco demora mais que o healthcheck diz.

- [ ] **Step 12: Rode os três gates e comite**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

```bash
git add alembic/versions/0019_busca_hibrida.py src/mobia/domain/catalogo/models.py src/mobia/domain/catalogo/repositorio.py tests/integration/test_catalogo_upsert.py
git commit -m "feat(TEC-158): o bairro dobrado vira coluna e o upsert a mantem"
```

---

## Task 2: A busca estruturada — os quatro cenários do Gherkin

Esta task entrega a busca **sem** a fase vetorial. Todo o Gherkin da card já passa aqui: o vetor muda a ordem, não o conjunto.

**Files:**
- Create: `src/mobia/domain/catalogo/busca.py`
- Modify: `src/mobia/domain/catalogo/schemas.py`
- Create: `tests/unit/test_busca_pontuacao.py`
- Create: `tests/integration/test_busca_hibrida.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

**Interfaces:**
- Consumes: `mobia.domain.texto.dobrar`, `Imovel.bairro_busca` (Task 1).
- Produces:
  - `FiltroDeBusca(operacao: Operacao, preco_min_centavos: int | None = None, preco_max_centavos: int | None = None, tipo: TipoImovel | None = None, quartos_min: int | None = None, vagas_min: int | None = None, regioes: tuple[str, ...] = ())`
  - `Candidato(imovel_id: uuid.UUID, codigo: str, titulo: str, bairro: str, preco_centavos: int, quartos: int, vagas: int, area_util_m2: int, score: float, tem_vetor: bool)`
  - `ResultadoDaBusca(candidatos: tuple[Candidato, ...], total_candidatos: int, consulta_vetorizada: bool)` com a propriedade `candidatos_sem_vetor: int`
  - `async def buscar(session: AsyncSession, filtro: FiltroDeBusca, consulta_texto: str | None = None, limite: int = MAX_CANDIDATOS, embedador: Embedador | None = None) -> ResultadoDaBusca`
  - `zonas_de(regioes: Sequence[str]) -> tuple[Zona, ...]`
  - Constantes `PESO_SIMILARIDADE = 0.6`, `PESO_ADERENCIA = 0.4`, `MAX_CANDIDATOS = 10`, `COLUNA_DE_PRECO`

- [ ] **Step 1: Escreva o teste unitário que falha**

Crie `tests/unit/test_busca_pontuacao.py`:

```python
"""As partes puras da busca hibrida.

TEC-158. Basename distinto de tudo em `tests/integration/`.

**A aderencia NAO e testada aqui, e isso e deliberado.** Ela existe uma vez,
como expressao SQL montada em Python -- o score tem de estar no ORDER BY para
o LIMIT significar algo, entao o calculo mora no banco. Uma funcao Python
gemea que devolvesse o mesmo numero seria uma segunda definicao da mesma
regra, e o unitario sobre ela testaria uma funcao que a consulta nao usa. Os
tres valores da D7 sao afirmados em `tests/integration/test_busca_hibrida.py`,
contra o que realmente roda.
"""

from mobia.domain.catalogo.busca import MAX_CANDIDATOS, zonas_de
from mobia.domain.catalogo.enums import Zona


def test_zona_pelo_nome_nu_e_pelo_prefixo() -> None:
    assert zonas_de(("sul",)) == (Zona.SUL,)
    assert zonas_de(("zona sul",)) == (Zona.SUL,)


def test_bairro_nao_deriva_zona() -> None:
    assert zonas_de(("moema",)) == ()


def test_centro_deriva_zona_e_segue_sendo_bairro() -> None:
    """O caso que fez a D4 recusar classificacao.

    "centro" e nome de zona E de bairro em quase toda cidade brasileira. A
    derivacao devolve a zona; quem NAO some e o texto, que continua sendo
    comparado contra `bairro_busca` no `OR` da consulta. A metade "e segue
    sendo bairro" e afirmada na integracao, onde ha as duas linhas.
    """
    assert zonas_de(("centro",)) == (Zona.CENTRO,)


def test_varias_regioes_derivam_varias_zonas_sem_duplicar() -> None:
    assert zonas_de(("zona sul", "sul", "norte")) == (Zona.NORTE, Zona.SUL)


def test_o_teto_de_candidatos_e_dez() -> None:
    """RN-09.2. Constante de modulo e nao `Settings` -- ver D11."""
    assert MAX_CANDIDATOS == 10
```

- [ ] **Step 2: Rode e confirme que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_busca_pontuacao.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.catalogo.busca'`.

- [ ] **Step 3: Acrescente as três formas a `catalogo/schemas.py`**

No fim de `src/mobia/domain/catalogo/schemas.py`, acrescente os imports que faltam e as três formas:

```python
import uuid
from collections.abc import Awaitable, Callable

# `Embedador` e a porta, e nao o cliente: a busca recebe a funcao e nunca
# importa `infra.embeddings`. E o que permite a suite exercitar o caminho
# inteiro sem credencial e sem rede. Ver D9.
Embedador = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True, slots=True)
class FiltroDeBusca:
    """O que o lead pediu, em dimensoes que o SQL resolve. TEC-158, RN-09.1.

    `operacao` e OBRIGATORIA e nao tem default, e e ela que escolhe a coluna
    de preco: o imovel tem `preco_venda` e `preco_aluguel`, o CHECK da tabela
    so garante que um dos dois existe, e a faixa do lead e um par de centavos
    que nao diz de qual universo e. Um default aqui faria "ate R$ 600.000"
    casar todo aluguel do catalogo, e a Marina receberia apartamento de
    R$ 3.500 por mes como se fosse a compra que ela pediu. Ver D2.

    **`status` NAO esta aqui, de proposito.** A RN-08.4 exclui da busca o que
    nao esta DISPONIVEL, e aceita-lo como filtro daria ao chamador um jeito de
    pedir imovel vendido pela mesma porta que o agente usa. Ele e literal no
    WHERE. Ver D3.

    **Nao ha filtro de cidade**, e a RN-09.1 nao o lista: "centro" casa o
    Centro de todas as cidades do catalogo. Enquanto o catalogo e de uma
    cidade so, e inocuo -- ver a lacuna 8 do desenho.

    `regioes` e tupla e nao list porque o dataclass e frozen. Vazia significa
    "sem filtro de regiao", nunca "nenhuma regiao casa".
    """

    operacao: Operacao
    preco_min_centavos: int | None = None
    preco_max_centavos: int | None = None
    tipo: TipoImovel | None = None
    quartos_min: int | None = None
    vagas_min: int | None = None
    regioes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidato:
    """Um imovel devolvido ao agente, com o id e o preco vindos do banco.

    RN-09.4, e o quarto cenario do Gherkin. O preco e o da OPERACAO buscada --
    a mesma coluna que o filtro comparou --, e por isso o campo se chama
    `preco_centavos` e nao `preco_venda`: numa busca de aluguel, devolver o
    preco de venda seria devolver o campo errado. O exemplo da secao 6.3 do
    SRS mostra `precoVenda` porque o exemplo dele e de venda.

    `tem_vetor` existe para que a degradacao da D8 seja legivel: sem ele,
    "a ordenacao esta estranha" e "o provedor esta fora" sao indistinguiveis
    para quem investiga.
    """

    imovel_id: uuid.UUID
    codigo: str
    titulo: str
    bairro: str
    preco_centavos: int
    quartos: int
    vagas: int
    area_util_m2: int
    score: float
    tem_vetor: bool


@dataclass(frozen=True, slots=True)
class ResultadoDaBusca:
    """Os candidatos e o que o chamador precisa saber sobre como eles sairam.

    `total_candidatos` e a contagem ANTES do teto de 10 -- e o
    `totalCandidatos` da secao 6.3, e e ele que diz ao agente que havia 40
    opcoes e ele esta vendo 10.
    """

    candidatos: tuple[Candidato, ...]
    total_candidatos: int
    consulta_vetorizada: bool

    @property
    def candidatos_sem_vetor(self) -> int:
        return sum(1 for candidato in self.candidatos if not candidato.tem_vetor)
```

- [ ] **Step 4: Crie `src/mobia/domain/catalogo/busca.py`**

```python
"""A busca hibrida do catalogo: filtro estruturado antes da similaridade.

TEC-158. RN-09.1 (as duas fases), RN-09.2 (o teto de 10), RN-09.6 (a
ordenacao) e RN-08.4 (o que nao esta DISPONIVEL fica fora).

**As duas fases sao uma instrucao, e a garantia e a semantica do SQL.** O
Postgres avalia o WHERE antes de qualquer expressao do ORDER BY, entao o
"antes" da RN-09.1 sai de graca -- nao precisa de CTE nem de duas viagens ao
banco. Duas viagens dobrariam a latencia sem mudar o resultado; trazer o
subconjunto para calcular cosseno em Python transferiria 1536 floats por
linha, que numa faixa larga de preco e o catalogo inteiro pela rede.

**A consulta e montada com o Core, e nao com `text()` cru** -- e aqui este
modulo DIVERGE do molde das varreduras (`sweep_stalled`,
`indexar_catalogo`). Aquelas tem UMA forma fixa; esta tem seis filtros
independentemente opcionais. Em `text()` isso obriga a
`(:preco_max IS NULL OR preco_venda <= :preco_max)` em cada clausula, e esse
predicado entrega ao planejador uma condicao que ele nao pode podar: o plano
generico considera a coluna filtrada mesmo quando o parametro e nulo. Isso e
ruim justamente na TEC-159, que mede p95. Com o Core, so as condicoes
presentes entram no WHERE.

**A aderencia mora AQUI e em nenhum outro lugar, como expressao SQL.** O
score tem de estar no ORDER BY para o LIMIT significar algo, entao o calculo
e do banco. Uma funcao Python gemea que devolvesse o mesmo numero seria uma
segunda definicao da mesma regra -- a divergencia entre as duas apareceria
como ordem que ninguem consegue explicar. E o mesmo criterio da D3 da
TEC-157, que recusou o hash em SQL para nao duplicar a lista de campos.
"""

from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy import Numeric, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from mobia.domain.catalogo.enums import Operacao, StatusImovel, Zona
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import (
    Candidato,
    Embedador,
    FiltroDeBusca,
    ResultadoDaBusca,
)
from mobia.domain.texto import dobrar

log = structlog.get_logger(__name__)

# RN-09.6. Constantes de modulo e nao `Settings`: pesos configuraveis sao
# RF-19, e antecipa-los aqui criaria configuracao que ninguem sabe calibrar
# sobre uma formula cuja metade a emenda E-01 acabou de definir. Ver D11.
PESO_SIMILARIDADE = 0.6
PESO_ADERENCIA = 0.4

# RN-09.2. O teto do que volta ao agente; os 3 que chegam ao lead sao a
# TEC-162.
MAX_CANDIDATOS = 10

# A coluna que a faixa do lead compara, escolhida pela operacao pedida.
#
# `Operacao.AMBOS` NAO e chave: e o que um imovel pode ser, nunca o que uma
# busca pede -- uma busca de AMBOS nao tem coluna de preco para comparar.
COLUNA_DE_PRECO = {
    Operacao.VENDA: "preco_venda",
    Operacao.ALUGUEL: "preco_aluguel",
}

# O vocabulario que faz "zona sul" virar `Zona.SUL`. Cada zona entra com o
# nome nu e com o prefixo `zona `, porque o lead diz os dois -- e
# `normalizar_regiao` deixa `zona` passar de proposito: o comentario de
# `_PREFIXOS_DE_REFERENCIA` registra que "`zona leste`, `zona sul` e `zona
# oeste` sao o nome, nao ruido".
_ZONA_POR_TEXTO: dict[str, Zona] = {
    **{dobrar(zona.value): zona for zona in Zona},
    **{f"zona {dobrar(zona.value)}": zona for zona in Zona},
}


def zonas_de(regioes: Sequence[str]) -> tuple[Zona, ...]:
    """As zonas que o vocabulario reconhece nas regioes dadas.

    **Isto NAO e classificacao.** A regiao que casa uma zona continua sendo
    comparada contra `bairro_busca` tambem -- o filtro e um OR (D4). "centro"
    e nome de zona E de bairro em quase toda cidade brasileira: perguntar "e
    zona ou e bairro?" obriga a escolher, e a escolha erra metade das vezes
    devolvendo resultados plausiveis do lado errado.

    Ordenado por valor para que a consulta gerada seja estavel entre
    execucoes -- `set` nao tem ordem, e um IN que muda de ordem muda o SQL e
    invalida plano em cache sem motivo.
    """
    encontradas = {_ZONA_POR_TEXTO[regiao] for regiao in regioes if regiao in _ZONA_POR_TEXTO}
    return tuple(sorted(encontradas, key=lambda zona: zona.value))


def _aderencia(preco: ColumnElement[Any], teto: int | None) -> ColumnElement[Any]:
    """A aderencia ao teto de preco, em [0, 1]. RN-09.6, emenda E-01.

    A regra da o peso (0,4) e **nunca diz o que se mede**. O primeiro fato e
    que aderencia nao pode ser "respeita a faixa": o filtro e DURO, entao
    todo candidato ja esta dentro dela e o termo valeria 1 para todos -- 40%
    do peso zerado, e a ordenacao sendo similaridade pura com um nome errado.

    A ancora e o TETO, e nao o centro da faixa. Tres razoes: nao precisa do
    piso, que o lead frequentemente nao diz; o teto e o que o SRS trata como
    significativo (a RN-09.3 relaxa a faixa em ate 10% e a CA-09.1 cobra so o
    teto -- o piso nao aparece em regra nenhuma da RF-09); e o relaxamento da
    TEC-160 decai sozinho, porque 10% acima do teto sai com 0,9 sem clausula
    extra. No teto da 1,0; na metade do orcamento, 0,5.

    Sem teto informado devolve a constante 1: o termo PARA de discriminar, em
    vez de discriminar por acidente.

    **Efeito colateral declarado:** favorece sistematicamente o imovel mais
    caro que cabe no orcamento. E o comportamento de um corretor competente,
    e e tambem a direcao em que um erro de calibragem viraria upsell -- quem
    for medir precisao@3 na TEC-159 tem aqui o que olhar primeiro.
    """
    if teto is None:
        return literal(1.0)
    # `func.greatest(0.0, ...)` e nao um CASE: e a mesma poda, mais curta, e
    # e a forma que o `_similaridade` usa logo abaixo pelo mesmo motivo.
    return func.greatest(0.0, 1.0 - func.abs(preco - teto) / float(teto))


def _similaridade(vetor: list[float] | None) -> ColumnElement[Any]:
    """A similaridade de cosseno com a consulta, em [0, 1]. D8.

    `<=>` do pgvector e DISTANCIA de cosseno em [0, 2], entao `1 - distancia`
    vive em [-1, 1]. Similaridade negativa e rara em texto real, e sem o
    `greatest` ela entraria com peso 0,6 e poderia empurrar um candidato para
    tras de um sem vetor nenhum -- que e ordem sem significado.

    **O `coalesce` esta explicito de proposito.** `GREATEST` do Postgres
    IGNORA NULL, entao `GREATEST(0, 1 - NULL)` ja devolve 0 e os dois casos
    degenerados (imovel sem embedding, consulta sem vetor) funcionariam
    sozinhos. A regra da D8 tem de valer por decisao, e nao por uma
    peculiaridade da funcao que o proximo leitor nao conhece.
    """
    if vetor is None:
        return literal(0.0)
    return func.coalesce(
        func.greatest(0.0, 1.0 - Imovel.embedding.cosine_distance(vetor)), 0.0
    )


async def buscar(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    consulta_texto: str | None = None,
    limite: int = MAX_CANDIDATOS,
    embedador: Embedador | None = None,
) -> ResultadoDaBusca:
    """Os candidatos que atendem ao filtro, ordenados pela relevancia da RN-09.6.

    `limite` e preso em `MAX_CANDIDATOS` mesmo quando o chamador pede mais: a
    RN-09.2 e sobre o que a busca DEVOLVE, e nao sobre o que o endpoint
    aceita. O endpoint recusa `limite > 10` com 422 para informar o cliente;
    este clamp garante a regra para quem chama por dentro. Ver D10.
    """
    teto_de_candidatos = min(limite, MAX_CANDIDATOS)

    # Dobra o que recebeu: o chamador pode passar "Zona Sul" ou "zona sul" e o
    # resultado e o mesmo, porque `dobrar` e idempotente. O lead chega pela
    # `normalizar_regiao`, que ja dobrou -- dobrar de novo nao custa nada e
    # tira do chamador HTTP a obrigacao de saber disso.
    regioes = tuple(dobrar(regiao) for regiao in filtro.regioes if regiao.strip())
    zonas = zonas_de(regioes)

    vetor = await _vetor_da_consulta(consulta_texto, embedador)

    preco = getattr(Imovel, COLUNA_DE_PRECO[filtro.operacao])

    condicoes: list[ColumnElement[Any]] = [
        # Literal, e nao parametro: ver D3.
        Imovel.status == StatusImovel.DISPONIVEL.value,
        # `in_` e nao `==`: igualdade crua excluiria todo imovel anunciado
        # para venda E locacao, que e caso comum de catalogo real e sairia da
        # busca em silencio.
        Imovel.operacao.in_([filtro.operacao.value, Operacao.AMBOS.value]),
        # O CHECK da tabela so garante que UM dos dois precos existe.
        preco.is_not(None),
    ]

    if filtro.preco_max_centavos is not None:
        condicoes.append(preco <= filtro.preco_max_centavos)
    if filtro.preco_min_centavos is not None:
        condicoes.append(preco >= filtro.preco_min_centavos)
    if filtro.tipo is not None:
        condicoes.append(Imovel.tipo == filtro.tipo.value)
    if filtro.quartos_min is not None:
        # `>=`, porque a card diz "nenhum resultado tem menos de 2 quartos" e
        # o contrato do SRS chama o campo de `quartosMin`.
        condicoes.append(Imovel.quartos >= filtro.quartos_min)
    if filtro.vagas_min is not None:
        condicoes.append(Imovel.vagas >= filtro.vagas_min)
    if regioes:
        # O OR da D4. `zonas` vazia gera `zona IN ()`, que o Postgres avalia
        # como falso mesmo para `zona` NULL -- imovel sem zona cadastrada so
        # nao casa por esse lado, e nao envenena o OR.
        condicoes.append(
            or_(
                Imovel.bairro_busca.in_(regioes),
                Imovel.zona.in_([zona.value for zona in zonas]),
            )
        )

    # `round` do Postgres com duas casas exige `numeric`: sobre `double
    # precision` ele so aceita um argumento. As tres casas vem do
    # `score_match numeric(4,3)` da tabela Recomendacao do SRS; o TIPO nao --
    # a entrada e uma distancia de cosseno em ponto flutuante, e `Decimal`
    # afirmaria uma exatidao que o vetor nao tem. Ver D11.
    score = func.round(
        cast(
            PESO_SIMILARIDADE * _similaridade(vetor)
            + PESO_ADERENCIA * _aderencia(preco, filtro.preco_max_centavos),
            Numeric,
        ),
        3,
    )

    consulta = (
        select(
            Imovel.id,
            Imovel.codigo,
            Imovel.titulo,
            Imovel.bairro,
            preco.label("preco"),
            Imovel.quartos,
            Imovel.vagas,
            Imovel.area_util_m2,
            Imovel.embedding.is_not(None).label("tem_vetor"),
            score.label("score"),
            # A contagem ANTES do teto, na mesma passagem: funcao de janela e
            # avaliada depois do WHERE e antes do LIMIT. Um COUNT separado
            # pagaria o filtro duas vezes para devolver um inteiro.
            func.count().over().label("total_candidatos"),
        )
        .where(*condicoes)
        # O desempate por `id` e OBRIGATORIO: sem ele a ordem entre scores
        # empatados e a que o executor entregar, e ela varia entre execucoes.
        # Numa suite cujos testes de integracao ja flakeiam sob carga, isso
        # seria flake plantado a mao.
        .order_by(score.desc(), Imovel.id)
        .limit(teto_de_candidatos)
    )

    linhas = list(await session.execute(consulta))

    candidatos = tuple(
        Candidato(
            imovel_id=linha.id,
            codigo=linha.codigo,
            titulo=linha.titulo,
            bairro=linha.bairro,
            preco_centavos=linha.preco,
            quartos=linha.quartos,
            vagas=linha.vagas,
            area_util_m2=linha.area_util_m2,
            # `float` na borda: o `round` devolveu `Decimal` porque o cast
            # pediu `numeric`, e o dominio expoe `float` (D11).
            score=float(linha.score),
            tem_vetor=linha.tem_vetor,
        )
        for linha in linhas
    )

    return ResultadoDaBusca(
        candidatos=candidatos,
        total_candidatos=linhas[0].total_candidatos if linhas else 0,
        consulta_vetorizada=vetor is not None,
    )


async def _vetor_da_consulta(
    consulta_texto: str | None, embedador: Embedador | None
) -> list[float] | None:
    """O vetor da consulta, ou None -- e None nunca e erro. D8 e D9.

    Tres caminhos levam a None, e nenhum deles bloqueia a busca: nao ha texto
    de consulta (o lead so deu criterios estruturados), nao ha embedador
    injetado, ou o provedor falhou. Em todos, a similaridade vale 0 para todo
    candidato e a ordem passa a ser a aderencia de preco.

    **Isto e o que substitui a garantia de topologia da TEC-157.** A docstring
    de `indexar_catalogo` dizia que nenhum caminho chama o provedor de
    embedding dentro do turno, e derivava DISSO a regra de que falha de
    embedding nao bloqueia o atendimento. A metade que sobrevive e a que
    importa -- o embedding do CATALOGO continua nascendo so no cron --, e a
    metade nova precisa deste `except` e do teste que o cobre.

    `Exception` ampla de proposito: timeout, conexao recusada, 429 e resposta
    malformada tem todos a mesma consequencia aqui, e distinguir a causa nao
    muda o que a busca faz. `motivo_do_provedor` nao e usado para nao
    importar `infra.embeddings` neste modulo de dominio -- o tipo da excecao e
    o sinal, e o motivo detalhado do provedor ja e logado pela varredura.
    """
    if not consulta_texto or not consulta_texto.strip():
        return None
    if embedador is None:
        return None

    try:
        vetores = await embedador([consulta_texto])
    except Exception as erro:
        log.warning(
            "busca.consulta_nao_vetorizada",
            tipo=type(erro).__name__,
            detalhe="a busca segue com filtro estruturado e ordem por aderencia de preco",
        )
        return None

    return vetores[0] if vetores else None
```

- [ ] **Step 5: Rode o unitário e confirme que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_busca_pontuacao.py -v
```

Esperado: PASS, os cinco.

- [ ] **Step 6: Escreva o arquivo de integração com os quatro cenários do Gherkin**

Crie `tests/integration/test_busca_hibrida.py`:

```python
"""A busca hibrida: filtro estruturado antes da similaridade.

TEC-158. Os quatro cenarios do Gherkin da card, mais o que o desenho
decidiu. Basename distinto de tudo em `tests/unit/`.

**A aderencia e afirmada AQUI, e nao em unitario.** Ela existe uma vez, como
expressao SQL -- estes testes medem o `score` que a consulta devolve, que e o
numero que de fato ordena.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.texto import dobrar

TETO = 60000000  # R$ 600.000,00 em centavos


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `test_indexacao_do_catalogo.py`, mais
    `bairro_busca`, que a `0019` tornou NOT NULL.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 50000000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    # Derivada, como no repositorio: o teste nao pode inventar uma dobra
    # diferente da que o codigo de producao grava.
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_o_filtro_estruturado_e_respeitado_a_risca(session: Any) -> None:
    """Cenario 1 do Gherkin, e a CA-09.1.

    Tres imoveis que NAO deveriam voltar, um por dimensao: preco acima do
    teto, quartos abaixo do minimo, zona errada.
    """
    dentro = await _imovel(session, "AP-001", preco_venda=55000000, quartos=2, zona="SUL")
    await _imovel(session, "AP-002", preco_venda=70000000, quartos=2, zona="SUL")
    await _imovel(session, "AP-003", preco_venda=55000000, quartos=1, zona="SUL")
    await _imovel(session, "AP-004", preco_venda=55000000, quartos=2, zona="NORTE",
                  bairro="Santana")

    resultado = await buscar(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            quartos_min=2,
            regioes=("zona sul",),
        ),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]
    for candidato in resultado.candidatos:
        assert candidato.preco_centavos <= TETO
        assert candidato.quartos >= 2


async def test_imovel_vendido_nao_aparece_e_continua_no_banco(session: Any) -> None:
    """Cenario 2 do Gherkin, RN-08.4 e CA-08.2.

    As DUAS assercoes, porque a regra tem duas metades e um DELETE passaria
    na primeira: "excluido dos resultados de busca, mas mantido no banco para
    historico".
    """
    vendido = await _imovel(session, "AP-010", status=StatusImovel.VENDIDO.value)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert resultado.candidatos == ()
    assert await session.get(Imovel, vendido) is not None


async def test_no_maximo_dez_candidatos_e_o_total_conta_antes_do_teto(session: Any) -> None:
    """Cenario 3 do Gherkin e RN-09.2.

    Quarenta imoveis que casam. O `total_candidatos` dizer 40 e o que prova
    que a contagem e antes do LIMIT -- com um COUNT depois do teto ele diria
    10, e o agente nunca saberia que havia mais.
    """
    for numero in range(40):
        await _imovel(session, f"AP-{numero:03d}")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert len(resultado.candidatos) == 10
    assert resultado.total_candidatos == 40


async def test_o_candidato_traz_identificador_e_preco_do_banco(session: Any) -> None:
    """Cenario 4 do Gherkin e RN-09.4."""
    identificador = await _imovel(session, "AP-020", preco_venda=58000000)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert len(resultado.candidatos) == 1
    candidato = resultado.candidatos[0]
    assert candidato.imovel_id == identificador
    assert candidato.preco_centavos == 58000000
    assert candidato.codigo == "AP-020"


async def test_imovel_de_ambas_as_operacoes_entra_na_busca_de_venda(session: Any) -> None:
    """`IN (operacao, 'AMBOS')`, e nao igualdade crua. D2."""
    ambos = await _imovel(session, "AP-030", operacao=Operacao.AMBOS.value,
                          preco_aluguel=300000)
    await _imovel(session, "AP-031", operacao=Operacao.ALUGUEL.value,
                  preco_venda=None, preco_aluguel=300000)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [ambos]


async def test_a_busca_de_aluguel_compara_o_preco_de_aluguel(session: Any) -> None:
    """A falha que a D2 recusou, virada teste.

    O mesmo imovel: R$ 580.000 de venda e R$ 3.000 de aluguel. Numa faixa de
    "ate R$ 4.000" de aluguel ele entra; numa de "ate R$ 600.000" de aluguel
    ele tambem entraria por acidente se a comparacao fosse contra o preco de
    venda -- por isso a assercao de baixo usa um teto de aluguel APERTADO, que
    so o preco certo satisfaz.
    """
    await _imovel(session, "AP-040", operacao=Operacao.AMBOS.value,
                  preco_venda=58000000, preco_aluguel=300000)

    cabe = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.ALUGUEL, preco_max_centavos=400000),
    )
    assert len(cabe.candidatos) == 1
    assert cabe.candidatos[0].preco_centavos == 300000

    nao_cabe = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.ALUGUEL, preco_max_centavos=200000),
    )
    assert nao_cabe.candidatos == ()


async def test_centro_casa_a_zona_e_o_bairro(session: Any) -> None:
    """O caso que fez a D4 recusar classificacao.

    Duas linhas: uma na zona CENTRO com outro bairro, outra no bairro
    "Centro" com outra zona. O OR devolve as duas -- classificar o texto
    devolveria uma e erraria a outra, em silencio.
    """
    por_zona = await _imovel(session, "AP-050", zona="CENTRO", bairro="Se")
    por_bairro = await _imovel(session, "AP-051", zona="OESTE", bairro="Centro")

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, regioes=("centro",))
    )

    assert {candidato.imovel_id for candidato in resultado.candidatos} == {
        por_zona,
        por_bairro,
    }


async def test_bairro_acentuado_casa_a_fala_dobrada_do_lead(session: Any) -> None:
    """D5. O lead digita "aclimacao"; o arquivo trouxe "Aclimacao" com til."""
    identificador = await _imovel(session, "AP-060", bairro="Aclimação", zona=None)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, regioes=("aclimacao",))
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [identificador]


async def test_a_aderencia_vale_um_no_teto_e_meio_na_metade(session: Any) -> None:
    """Os valores da D7, medidos no `score` que a consulta devolve.

    Sem vetor de consulta a similaridade vale 0 para todos, entao o score e
    exatamente `0,4 x aderencia` -- o que torna a aderencia observavel sem
    uma funcao Python gemea que a duplicasse.
    """
    no_teto = await _imovel(session, "AP-070", preco_venda=TETO)
    na_metade = await _imovel(session, "AP-071", preco_venda=TETO // 2)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO)
    )

    por_id = {candidato.imovel_id: candidato.score for candidato in resultado.candidatos}
    assert por_id[no_teto] == 0.4
    assert por_id[na_metade] == 0.2
    # E a ordem que a D7 declara: o mais caro que cabe vem primeiro.
    assert resultado.candidatos[0].imovel_id == no_teto


async def test_sem_teto_de_preco_a_aderencia_para_de_discriminar(session: Any) -> None:
    """D7. O termo vira a constante 1, e o score de todos e o mesmo."""
    await _imovel(session, "AP-080", preco_venda=10000000)
    await _imovel(session, "AP-081", preco_venda=90000000)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert {candidato.score for candidato in resultado.candidatos} == {0.4}


async def test_a_ordem_entre_scores_empatados_e_estavel(session: Any) -> None:
    """D1. Sem o desempate por `id` isto seria flake plantado a mao."""
    for numero in range(5):
        await _imovel(session, f"AP-09{numero}", preco_venda=50000000)

    primeira = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))
    segunda = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert [candidato.imovel_id for candidato in primeira.candidatos] == [
        candidato.imovel_id for candidato in segunda.candidatos
    ]


async def test_o_filtro_de_tipo_e_o_de_vagas(session: Any) -> None:
    """As duas dimensoes da RN-09.1 que os cenarios do Gherkin nao exercitam."""
    casa_com_duas = await _imovel(session, "CA-001", tipo=TipoImovel.CASA.value, vagas=2)
    await _imovel(session, "CA-002", tipo=TipoImovel.CASA.value, vagas=1)
    await _imovel(session, "AP-100", tipo=TipoImovel.APARTAMENTO.value, vagas=2)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, tipo=TipoImovel.CASA, vagas_min=2),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [casa_com_duas]


async def test_limite_acima_do_teto_e_preso_em_dez(session: Any) -> None:
    """RN-09.2 e D10: quem chama por dentro nao escapa do teto."""
    for numero in range(12):
        await _imovel(session, f"AP-11{numero}")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA), limite=50)

    assert len(resultado.candidatos) == 10


async def test_zero_resultados_devolve_vazio_e_nao_levanta(session: Any) -> None:
    """A porta que a TEC-160 vai abrir. Vazio nao e erro."""
    await _imovel(session, "AP-120", preco_venda=90000000)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=1000000)
    )

    assert resultado.candidatos == ()
    assert resultado.total_candidatos == 0
```

- [ ] **Step 7: Rode a integração**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_hibrida.py -v --tb=short
```

Esperado: PASS, os catorze. Se `test_a_aderencia_vale_um_no_teto_e_meio_na_metade` falhar por meio milésimo, o lugar para olhar é o `cast(..., Numeric)` do `round` — sem ele o Postgres recusa o segundo argumento.

- [ ] **Step 8: Escreva as duas emendas ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, **aninhadas** sob as regras que alteram, no formato dos exemplos que já estão lá — **sem tocar o texto de 22/08/2026**.

Sob a **RN-09.1**:

```markdown
  - **Emenda E-01 (TEC-158, 07/09/2026):** a regra lista "bairro" entre as dimensões estruturadas. O filtro de região é a **união** de bairro e zona (`bairro_busca = ANY(...) OR zona = ANY(...)`), e não uma escolha entre os dois: "centro" é nome de zona **e** de bairro em quase toda cidade brasileira, e classificar o texto do lead como um ou outro erra metade das vezes devolvendo resultados plausíveis do lado errado. A comparação é contra a coluna `bairro_busca` — o bairro dobrado em caixa e acento, gravado pela mesma função que dobra a fala do lead —, e não contra `bairro`: o lead digita "aclimacao" e o arquivo trouxe "Aclimação". A dimensão `cidade` **não** entra, porque a regra não a lista: num catálogo multicidade, "centro" casa o Centro de todas elas. Ver a D4 e a D5 do desenho.
```

Sob a **RN-09.6**:

```markdown
  - **Emenda E-01 (TEC-158, 07/09/2026):** a regra dá o peso (`0,4`) e nunca define *aderência ao filtro de preço*. Como o filtro estruturado é **duro**, "respeita a faixa" valeria 1 para todo candidato e zeraria o termo — 40% do peso sem efeito, e a ordenação sendo similaridade pura com um nome errado. A emenda fixa `aderencia = clamp(1 - |preco - teto| / teto, 0, 1)`, e `1` quando o lead não informou teto. A âncora é o teto e não o centro da faixa porque o piso não aparece em regra nenhuma da RF-09 — a RN-09.3 relaxa a faixa em até 10% e a CA-09.1 cobra só o teto — e porque o relaxamento da RN-09.3 decai sozinho: 10% acima do teto sai com 0,9, sem cláusula extra. **Consequência declarada:** a ordenação favorece sistematicamente o imóvel mais caro que cabe no orçamento. É o comportamento de um corretor competente, e é também a direção em que um erro de calibragem viraria upsell. A definição vive uma única vez, como expressão SQL em `domain/catalogo/busca.py`, e não tem gêmea em Python. Ver a D7 do desenho.
```

- [ ] **Step 9: Rode os três gates e comite**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/catalogo/busca.py src/mobia/domain/catalogo/schemas.py tests/unit/test_busca_pontuacao.py tests/integration/test_busca_hibrida.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "feat(TEC-158): o filtro estruturado devolve dez candidatos ordenados por aderencia"
```

---

## Task 3: A fase vetorial e a degradação declarada

**Files:**
- Modify: `tests/integration/test_busca_hibrida.py`
- Modify: `src/mobia/workers/jobs/indexar_catalogo.py` (só a docstring)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

**Interfaces:**
- Consumes: `buscar(..., embedador=...)` e `_similaridade` (Task 2 — já escritos; esta task é o teste que os cobre e a documentação que a decisão obriga).
- Produces: nada novo de código.

**Nota ao implementador:** a Task 2 já escreveu `_similaridade` e `_vetor_da_consulta`. Esta task **não** os reescreve — ela fecha o que a Task 2 deixou sem cobertura, e paga a dívida de documentação que a D9 criou. Se você está executando as tasks em ordem, o código desta task já roda; o trabalho é provar que ele roda e corrigir a docstring que passou a mentir.

- [ ] **Step 1: Escreva os testes da fase vetorial**

Acrescente a `tests/integration/test_busca_hibrida.py` — e ao bloco de imports, `from conftest import EmbedadorFake`.

**Duas propriedades do `EmbedadorFake` que estes testes exploram, e que você precisa saber antes de escrever qualquer coisa** (`tests/conftest.py`, o `__call__`):

1. **O vetor é constante em todas as 1536 componentes:** `[float(len(texto) % 7 + indice) / 10.0] * dimensoes`. Para um texto só, `indice = 0`. Isso torna o cosseno **exato e previsível**: qualquer `embedding` que também seja um vetor constante positivo tem similaridade **1,0** com ele, e um vetor de soma zero (`[0.1, -0.1] * 768`) tem similaridade **0,0**. É assim que estes testes fixam números em vez de comparar aproximações.
2. **Texto com `len % 7 == 0` produz o vetor ZERO**, e distância de cosseno com vetor zero é `NaN` no pgvector — o teste falharia de um jeito confuso. `"apartamento com varanda"` tem 23 caracteres (`23 % 7 == 2`), e é o texto usado em todos os testes abaixo de propósito. **Se você trocar o texto, conte os caracteres.**

```python
async def test_imovel_sem_vetor_entra_e_ordena_atras(session: Any) -> None:
    """D8. Falta de vetor nunca exclui ninguem.

    A alternativa literal -- so imovel com vetor e candidato -- foi recusada
    porque o proprio aviso da TEC-157 descreve o desfecho: "o catalogo fica
    sem vetor e a busca semantica devolve vazio". Um ambiente sem chave
    responderia "nao ha imoveis" para um catalogo de 500.

    Os dois imoveis tem o MESMO preco, entao a aderencia empata e a ordem sai
    inteira da similaridade.
    """
    com_vetor = await _imovel(session, "AP-200", embedding=[0.1] * 1536)
    sem_vetor = await _imovel(session, "AP-201")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [
        com_vetor,
        sem_vetor,
    ]
    assert resultado.consulta_vetorizada is True
    assert resultado.candidatos_sem_vetor == 1


async def test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro(session: Any) -> None:
    """A assercao que a D9 tornou necessaria.

    A TEC-157 derivava de TOPOLOGIA a regra "falha de embedding nao bloqueia
    o atendimento" -- nao havia caminho em que o turno chamasse o provedor.
    Esta card criou o caminho, entao a regra passou a precisar de teste. Sem
    esta assercao, um `raise` no lugar do `except` de `_vetor_da_consulta`
    deixaria a suite verde e o atendimento parado.
    """
    identificador = await _imovel(session, "AP-210")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(falhar=True),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [identificador]
    assert resultado.consulta_vetorizada is False


async def test_busca_sem_texto_nao_chama_o_provedor(session: Any) -> None:
    """D8. Criterio estruturado sozinho nao paga uma requisicao.

    A assercao e sobre a CHAMADA e nao sobre o desfecho: um embedador chamado
    e descartado devolveria os mesmos candidatos, gastando dinheiro e
    latencia em todo turno.
    """
    await _imovel(session, "AP-220")
    embedador = EmbedadorFake()

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA), embedador=embedador
    )

    assert embedador.chamadas == []
    assert resultado.consulta_vetorizada is False
    assert len(resultado.candidatos) == 1


async def test_sem_embedador_injetado_a_busca_segue(session: Any) -> None:
    """O default do parametro nao pode ser um caminho que levanta."""
    await _imovel(session, "AP-230")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
    )

    assert len(resultado.candidatos) == 1
    assert resultado.consulta_vetorizada is False


async def test_sem_teto_a_ordem_e_a_similaridade_pura(session: Any) -> None:
    """D7, a outra metade: sem teto o termo de aderencia empata em 1.

    Os dois imoveis tem precos muito diferentes -- R$ 100 mil e R$ 900 mil --,
    e a ordem NAO os segue: o barato vem primeiro porque o vetor dele casa a
    consulta. E o que prova que 0,6 da ordenacao e da similaridade, e nao um
    termo decorativo ao lado do preco.

    O vetor de soma zero da similaridade exatamente 0 contra o vetor constante
    do falso; o constante da exatamente 1. Ver a nota do Step 1.
    """
    parecido = await _imovel(session, "AP-240", preco_venda=10000000,
                             embedding=[0.1] * 1536)
    diferente = await _imovel(session, "AP-241", preco_venda=90000000,
                              embedding=[0.1, -0.1] * 768)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [
        parecido,
        diferente,
    ]
    por_id = {candidato.imovel_id: candidato.score for candidato in resultado.candidatos}
    assert por_id[parecido] == 1.0
    assert por_id[diferente] == 0.4
```

**Sobre o clamp em 0 da aderência, que o desenho lista e este plano não testa.** Enquanto o filtro é duro, `preco <= teto` sempre vale, então `|preco - teto| / teto <= 1` e a aderência nunca chega a ser negativa — o `greatest(0.0, ...)` só se torna alcançável quando a TEC-160 admitir candidatos acima do teto. Ele fica no código porque é lá que a expressão vive, e o teste dele pertence à card que abre o caminho. Escrever agora um teste que exercita um estado inalcançável seria testar a implementação em vez do comportamento.

- [ ] **Step 2: Rode e confirme**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_hibrida.py -v --tb=short
```

Esperado: PASS, os dezenove. Se algum score vier `NaN`, o texto de consulta tem comprimento múltiplo de 7 e o falso devolveu o vetor zero — ver a nota do Step 1.

- [ ] **Step 3: Corrija a docstring que passou a mentir**

Em `src/mobia/workers/jobs/indexar_catalogo.py`, o parágrafo que começa com `**A regra "falha de embedding nao bloqueia o atendimento" sai da topologia, nao de um `try/except`.**` afirma uma garantia que esta card revogou pela metade. Substitua-o por:

```python
"""
**A regra "falha de embedding nao bloqueia o atendimento" tem duas metades, e
a TEC-158 mudou uma delas.** Ate a TEC-157, a regra saia inteira da
topologia: nao existia caminho em que `process_message` chamasse o provedor
de embedding, e isso e mais forte que capturar excecao. A TEC-158 abriu o
caminho -- a busca hibrida embeda a CONSULTA do lead dentro do turno -- e o
que sobrevive e isto:

- o embedding do CATALOGO continua nascendo so aqui. Este job e um cron
  separado, e nenhum caminho de atendimento gera vetor de imovel;
- o embedding da CONSULTA e gerado no turno, e falha dele nao bloqueia por
  DECISAO e nao por topologia: `domain/catalogo/busca.py` degrada para o
  filtro estruturado ordenado por aderencia de preco, e
  `test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro` e o que
  impede um `raise` de voltar para la sem sintoma.

A metade que este arquivo garante e a primeira, e ela continua valendo por
construcao. Um refactor que chame o embedding de IMOVEL de dentro do turno
seguiria violando a RN da card sem que teste nenhum reclamasse -- e e por
isso que a frase fica escrita aqui.
"""
```

**Cuidado:** esse texto entra no docstring de módulo que já existe, mantendo o resto dele intacto. Sem acento, como todo `src/`.

- [ ] **Step 4: Escreva a emenda E-02 ao SRS**

Sob a **RN-08.2**, **depois** da Emenda E-01 da TEC-157 que já está lá:

```markdown
  - **Emenda E-02 (TEC-158, 07/09/2026):** a E-01 estabeleceu que o embedding do catálogo nasce numa varredura em cron, e a TEC-157 derivou daquela topologia a garantia de que falha de embedding não bloqueia o atendimento. A emenda distingue os **dois** embeddings do sistema: o do **catálogo** continua nunca sendo gerado no turno — o cron segue sendo o único caminho —; o da **consulta** do lead é gerado no turno pela busca híbrida da RN-09.1, e a não-obstrução passa a vir de **degradação declarada** em vez de topologia: sem vetor de consulta (por falta de texto, de chave ou por falha do provedor), a busca devolve o subconjunto filtrado ordenado por aderência de preço, e nunca vazio nem erro. **Consequência declarada:** o que antes era garantido por construção agora depende de um teste, e o teste é `test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro`. Ver a D9 do desenho.
```

- [ ] **Step 5: Rode os três gates e comite**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

```bash
git add tests/integration/test_busca_hibrida.py src/mobia/workers/jobs/indexar_catalogo.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "feat(TEC-158): a consulta vetoriza no turno e provedor caido nao bloqueia a busca"
```

---

## Task 4: O endpoint `POST /api/v1/imoveis/busca`

**Files:**
- Modify: `src/mobia/api/routes/imoveis.py`
- Create: `tests/integration/test_busca_endpoint.py`

**Interfaces:**
- Consumes: `buscar`, `FiltroDeBusca`, `MAX_CANDIDATOS` (Task 2).
- Produces: `POST /api/v1/imoveis/busca` com o contrato da seção 6.3.

- [ ] **Step 1: Escreva o teste do endpoint**

Crie `tests/integration/test_busca_endpoint.py`:

```python
"""O endpoint da busca hibrida, e a guarda que o protege.

TEC-158, secao 6.3 do SRS. Ate a TEC-201 a autenticacao e o token
compartilhado do administrativo -- ver D10. Basename distinto de tudo em
`tests/unit/`.
"""

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar

TOKEN = "token-de-teste-do-catalogo"


@pytest.fixture
async def app_com_token(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde do `app_com_token` de `test_importacao_http.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def _semear(session: Any) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo="AP-1042",
            titulo="Apartamento com vista",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=58000000,
            bairro="Vila Mariana",
            bairro_busca=dobrar("Vila Mariana"),
            cidade="Sao Paulo",
            uf="SP",
            zona="SUL",
            area_util_m2=74,
            quartos=2,
            suites=1,
            banheiros=2,
            vagas=1,
            caracteristicas=["varanda"],
            fotos=[],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


async def test_a_busca_devolve_o_contrato_da_secao_6_3(
    app_com_token: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await app_com_token.post(
        "/api/v1/imoveis/busca",
        headers={"X-Admin-Token": TOKEN},
        json={
            "filtros": {"operacao": "VENDA", "precoMax": 60000000, "quartosMin": 2,
                        "regioes": ["Zona Sul"]},
            "limite": 10,
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["totalCandidatos"] == 1
    assert corpo["consultaVetorizada"] is False
    assert corpo["candidatosSemVetor"] == 1
    item = corpo["itens"][0]
    assert item["id"] == str(identificador)
    assert item["codigo"] == "AP-1042"
    # `preco`, e nao `precoVenda`: o exemplo do SRS e de uma busca de venda, e
    # copia-lo ao pe da letra faria a busca de aluguel devolver o campo
    # errado. Ver o contrato do endpoint no desenho.
    assert item["preco"] == 58000000
    # 0,387 e nao 0,4: sem vetor a similaridade vale 0, entao o score e
    # `0,4 x aderencia`, e a aderencia de R$ 580.000 contra um teto de
    # R$ 600.000 e `1 - 2/60 = 0,9667`. Conferido no Postgres:
    # `round((0.4 * (1 - abs(58000000-60000000)::float8/60000000))::numeric, 3)`
    # da 0.387. O imovel no teto exato e que daria 0,4 -- ver
    # `test_a_aderencia_vale_um_no_teto_e_meio_na_metade`.
    assert item["scoreMatch"] == 0.387


async def test_regiao_em_caixa_alta_casa_igual(
    app_com_token: AsyncClient, session: Any
) -> None:
    """O chamador HTTP nao precisa saber que a comparacao e dobrada. D4."""
    await _semear(session)

    resposta = await app_com_token.post(
        "/api/v1/imoveis/busca",
        headers={"X-Admin-Token": TOKEN},
        json={"filtros": {"operacao": "VENDA", "regioes": ["VILA MARIANA"]}},
    )

    assert resposta.status_code == 200
    assert resposta.json()["totalCandidatos"] == 1


async def test_limite_acima_de_dez_e_recusado(app_com_token: AsyncClient) -> None:
    """RN-09.2 na borda: o cliente e informado, em vez de receber 10 calado."""
    resposta = await app_com_token.post(
        "/api/v1/imoveis/busca",
        headers={"X-Admin-Token": TOKEN},
        json={"filtros": {"operacao": "VENDA"}, "limite": 50},
    )

    assert resposta.status_code == 422


async def test_filtro_sem_operacao_e_recusado(app_com_token: AsyncClient) -> None:
    """D2. Sem operacao nao ha coluna de preco a comparar."""
    resposta = await app_com_token.post(
        "/api/v1/imoveis/busca",
        headers={"X-Admin-Token": TOKEN},
        json={"filtros": {"precoMax": 60000000}},
    )

    assert resposta.status_code == 422


async def test_sem_token_e_proibido(app_com_token: AsyncClient) -> None:
    resposta = await app_com_token.post(
        "/api/v1/imoveis/busca",
        json={"filtros": {"operacao": "VENDA"}},
    )

    assert resposta.status_code == 403
```

- [ ] **Step 2: Rode e confirme que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_endpoint.py -v --tb=short
```

Esperado: FAIL com `404` nos que esperam `200`/`422`, porque a rota não existe.

- [ ] **Step 3: Acrescente a rota**

Em `src/mobia/api/routes/imoveis.py`, acrescente aos imports:

```python
from pydantic import BaseModel, ConfigDict, Field

from mobia.domain.catalogo.busca import MAX_CANDIDATOS, buscar
from mobia.domain.catalogo.enums import Operacao, TipoImovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
```

E, no fim do arquivo:

```python
class FiltrosDaBusca(BaseModel):
    """As dimensoes estruturadas, no camelCase da secao 6.3.

    `alias` e nao nomes camelCase nos atributos: o corpo HTTP fala camelCase e
    o Python deste repo fala snake_case, e `populate_by_name` deixa os dois
    funcionarem sem duas classes.

    `operacao` NAO tem default: sem ela nao ha coluna de preco a comparar, e
    um default faria "ate R$ 600.000" casar todo aluguel do catalogo. Ver D2.

    `status` nao esta aqui de proposito -- a RN-08.4 o resolve no WHERE, e
    aceita-lo daria ao chamador um jeito de pedir imovel vendido (D3).
    """

    model_config = ConfigDict(populate_by_name=True)

    operacao: Operacao
    preco_min_centavos: int | None = Field(default=None, alias="precoMin")
    preco_max_centavos: int | None = Field(default=None, alias="precoMax")
    tipo: TipoImovel | None = None
    quartos_min: int | None = Field(default=None, alias="quartosMin")
    vagas_min: int | None = Field(default=None, alias="vagasMin")
    regioes: list[str] = Field(default_factory=list)


class PedidoDeBusca(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    consulta_texto: str | None = Field(default=None, alias="consultaTexto")
    filtros: FiltrosDaBusca
    # `le=MAX_CANDIDATOS` recusa com 422 em vez de devolver 10 calado: o
    # dominio faz o clamp de qualquer jeito (RN-09.2 e sobre o que a busca
    # devolve), e a borda existe para INFORMAR o cliente. Ver D10.
    limite: int = Field(default=MAX_CANDIDATOS, ge=1, le=MAX_CANDIDATOS)


@router.post("/busca")
async def busca(pedido: PedidoDeBusca, _: None = Depends(exigir_admin)) -> dict[str, object]:
    """A busca hibrida da RF-09, no contrato da secao 6.3.

    **A guarda nao e a do SRS, e isso e declarado.** A secao 6.3 pede "Bearer
    JWT ou token interno do agente"; o que existe e o `X-Admin-Token` que a D1
    da TEC-156 registra como provisorio. Este endpoint NAO e administrativo, e
    quando o JWT chegar (TEC-201) ele precisa de papel proprio.

    **O embedador nao e injetado aqui, e a consequencia esta no corpo da
    resposta.** Nenhum consumidor HTTP tem hoje um motivo para pagar a
    latencia de embedar a consulta: quem vai passar o embedador e o turno,
    quando a TEC-161 ligar a busca ao agente. Ate la `consultaVetorizada` sai
    `false` e a ordem e a aderencia de preco -- o que e a degradacao da D8
    funcionando, e nao um defeito. Trocar isto e uma linha.
    """
    filtro = FiltroDeBusca(
        operacao=pedido.filtros.operacao,
        preco_min_centavos=pedido.filtros.preco_min_centavos,
        preco_max_centavos=pedido.filtros.preco_max_centavos,
        tipo=pedido.filtros.tipo,
        quartos_min=pedido.filtros.quartos_min,
        vagas_min=pedido.filtros.vagas_min,
        regioes=tuple(pedido.filtros.regioes),
    )

    async with get_sessionmaker()() as session:
        resultado = await buscar(
            session, filtro, consulta_texto=pedido.consulta_texto, limite=pedido.limite
        )

    return {
        "itens": [
            {
                "id": str(candidato.imovel_id),
                "codigo": candidato.codigo,
                "titulo": candidato.titulo,
                "bairro": candidato.bairro,
                "preco": candidato.preco_centavos,
                "quartos": candidato.quartos,
                "vagas": candidato.vagas,
                "areaUtilM2": candidato.area_util_m2,
                "scoreMatch": candidato.score,
            }
            for candidato in resultado.candidatos
        ],
        "totalCandidatos": resultado.total_candidatos,
        "consultaVetorizada": resultado.consulta_vetorizada,
        "candidatosSemVetor": resultado.candidatos_sem_vetor,
    }
```

- [ ] **Step 4: Rode e confirme que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_endpoint.py -v --tb=short
```

Esperado: PASS, os cinco.

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Rode a suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -u -m pytest -v --tb=short
```

Espere **~22 minutos em máquina ociosa** — e muito mais se houver outra coisa rodando. Saída vazia por dez minutos é normal, não deadlock.

Se algum de `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` ou `test_optout_repositorio.py` falhar com `ConnectionResetError` ou erro de Redis, **rode o arquivo sozinho antes de atribuir a falha a esta branch** — os quatro flakeiam sob carga e passam isolados. Guarde o hash do commit junto com o resultado de cada execução.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/api/routes/imoveis.py tests/integration/test_busca_endpoint.py
git commit -m "feat(TEC-158): o endpoint da busca hibrida entra no router do catalogo"
```

---

## Cobertura do desenho

| Decisão | Onde é implementada | Onde é testada |
|---|---|---|
| D1 — uma consulta, score no `ORDER BY` | `busca.py`, `buscar` | `test_a_ordem_entre_scores_empatados_e_estavel` |
| D2 — coluna de preço por dicionário, `operacao` obrigatória | `COLUNA_DE_PRECO`, `FiltroDeBusca.operacao` | `test_a_busca_de_aluguel_compara_o_preco_de_aluguel`, `test_imovel_de_ambas_as_operacoes_entra_na_busca_de_venda`, `test_filtro_sem_operacao_e_recusado` |
| D3 — `status` não é parâmetro | `condicoes[0]` em `buscar` | `test_imovel_vendido_nao_aparece_e_continua_no_banco` |
| D4 — região é `OR`, não classificação | `zonas_de` + `or_(...)` | `test_centro_casa_a_zona_e_o_bairro`, `test_bairro_nao_deriva_zona` |
| D5 — `bairro_busca` materializada | `0019`, `models.py`, `_derivados` | `test_o_upsert_mantem_a_dobra_do_bairro`, `test_bairro_acentuado_casa_a_fala_dobrada_do_lead` |
| D6 — a dobra em `domain/texto.py` | `texto.py`, `normalizar_regiao` | `test_a_dobra_nao_come_prefixo_de_referencia`, `test_normalizar_regiao_continua_dobrando` |
| D7 — aderência é distância ao teto | `_aderencia` | `test_a_aderencia_vale_um_no_teto_e_meio_na_metade`, `test_sem_teto_de_preco_a_aderencia_para_de_discriminar`, `test_sem_teto_a_ordem_e_a_similaridade_pura`. **O clamp em 0 é inalcançável enquanto o filtro é duro** — o teste dele é da TEC-160 |
| D8 — falta de vetor nunca exclui | `_similaridade`, `_vetor_da_consulta` | `test_imovel_sem_vetor_entra_e_ordena_atras`, `test_busca_sem_texto_nao_chama_o_provedor`, `test_sem_embedador_injetado_a_busca_segue` |
| D9 — embedador injetado, emenda à topologia | `buscar(embedador=...)`, docstring da varredura, E-02 | `test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro` |
| D10 — endpoint sob guarda provisória, teto em duas camadas | `routes/imoveis.py` | `test_limite_acima_de_dez_e_recusado`, `test_limite_acima_do_teto_e_preso_em_dez`, `test_sem_token_e_proibido` |
| D11 — pesos constantes, score `float` | constantes de `busca.py`, `cast(..., Numeric)` | `test_o_teto_de_candidatos_e_dez`, e o valor `0.4` afirmado nos testes de aderência |

**Gherkin da card:** cenário 1 → `test_o_filtro_estruturado_e_respeitado_a_risca`; cenário 2 → `test_imovel_vendido_nao_aparece_e_continua_no_banco`; cenário 3 → `test_no_maximo_dez_candidatos_e_o_total_conta_antes_do_teto`; cenário 4 → `test_o_candidato_traz_identificador_e_preco_do_banco`.

**As três emendas ao SRS:** RN-09.1 E-01 e RN-09.6 E-01 na Task 2, Step 8; RN-08.2 E-02 na Task 3, Step 4.

**O que este plano deliberadamente não faz:** relaxamento (TEC-160), guardrail de citação (TEC-161), apresentação e `motivoMatch` (TEC-162), medição do SLA (TEC-159), ligação no turno, JWT, e a conciliação dos dois `TipoImovel` — que é a lacuna 2 do desenho e provavelmente merece card antes da TEC-160.
