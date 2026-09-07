# TEC-157 — Indexação vetorial do catálogo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cada imóvel do catálogo passa a ter um vetor de 1536 dimensões que se mantém atualizado sozinho, sem que nenhum caminho de escrita precise avisar que o texto mudou.

**Architecture:** três colunas novas em `imoveis` (`embedding`, `embedding_atualizado_em`, `documento_hash`) tornam "precisa reindexar" uma pergunta que o banco responde. Um cron no molde da `sweep_stalled` seleciona candidatos por pré-filtro barato em SQL, recalcula o documento e o hash em Python, e só chama o provedor quando o hash de fato mudou. A definição do documento mora em exatamente um lugar, em função pura.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, ARQ, Postgres 16 + pgvector, OpenAI `text-embedding-3-small`.

**Spec:** `docs/superpowers/specs/2026-09-07-tec-157-indexacao-vetorial-design.md`

## Global Constraints

- **Provedor:** OpenAI `text-embedding-3-small`, **1536** dimensões. A Anthropic não tem endpoint de embeddings; este é um segundo provedor, e o `infra/anthropic.py` continua servindo o agente.
- **Imagem do Postgres:** `pgvector/pgvector:pg16`, em **`docker-compose.yml` E `.github/workflows/ci.yml`**. Trocar só um deixa a `main` vermelha com os gates verdes na máquina de quem mexeu.
- **Hash:** `sha256` em hexadecimal, 64 caracteres, sobre o texto do documento pronto. **Nunca** `md5` de colunas concatenadas em SQL.
- **Campos DENTRO do documento:** `titulo`, `descricao`, `tipo`, `bairro`, `cidade`, `caracteristicas`. E nada mais.
- **Campos FORA:** todos os numéricos (`preco_venda`, `preco_aluguel`, `condominio`, `iptu_mensal`, `area_util_m2`, `quartos`, `suites`, `banheiros`, `vagas`, `latitude`, `longitude`) mais `operacao`, `status`, `zona`, `uf`, `fotos`.
- **Teto por passagem:** 100 candidatos. **Lote por chamada:** 50. O lote é menor que o teto de propósito.
- **Cadência:** `second={0, 30}`, como a `sweep_stalled`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter.
- **Nenhuma chamada de rede na suíte.** O cliente de embedding é sempre falso em teste.
- **Basename de teste não pode colidir** entre `tests/unit/` e `tests/integration/` — colisão aborta a coleta da suíte inteira e não aparece em execução isolada.
- **Os três gates, no escopo exato do CI**, antes de cada commit:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Mensagem de commit:** `tipo(TEC-157): o que passou a ser verdade`, assunto em português sem acento. Passe por `-m`, nunca por arquivo salvo com BOM.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `docker-compose.yml` | Imagem com pgvector | 1 |
| `.github/workflows/ci.yml` | Imagem com pgvector | 1 |
| `pyproject.toml` | Dependências `openai` e `pgvector` | 1 |
| `alembic/versions/0017_indexacao_vetorial.py` | Extensão, três colunas, índice IVFFlat | 1 |
| `src/mobia/domain/catalogo/models.py` | As três colunas no ORM | 1 |
| `tests/integration/test_migracao_vetorial.py` | A migration criou o que promete | 1 |
| `src/mobia/domain/catalogo/documento.py` | **Função pura.** O documento e o hash | 2 |
| `tests/unit/test_documento_do_imovel.py` | Quais campos entram, e o hash | 2 |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Emenda E-01 à RN-08.2 | 2 |
| `src/mobia/app/config.py` | Chave, modelo, dimensão, teto, lote | 3 |
| `src/mobia/infra/embeddings.py` | Cliente do provedor, no molde do `anthropic.py` | 3 |
| `tests/unit/test_cliente_de_embedding.py` | A guarda da chave ausente | 3 |
| `src/mobia/workers/jobs/indexar_catalogo.py` | A varredura | 4, 5, 6 |
| `tests/conftest.py` | `EmbedadorFake` | 4 |
| `tests/integration/test_indexacao_do_catalogo.py` | A varredura, de ponta a ponta | 4, 5, 6 |
| `src/mobia/workers/main.py` | Registro em `functions` e `cron_jobs` | 7 |
| `tests/integration/test_registro_do_cron_vetorial.py` | O job está registrado nos dois lugares | 7 |

---

## Task 1: Infra vetorial — imagem, extensão, colunas e índice

**Files:**
- Modify: `docker-compose.yml:3`
- Modify: `.github/workflows/ci.yml:57`
- Modify: `pyproject.toml` (bloco `dependencies`)
- Create: `alembic/versions/0017_indexacao_vetorial.py`
- Modify: `src/mobia/domain/catalogo/models.py` (classe `Imovel`)
- Test: `tests/integration/test_migracao_vetorial.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: as colunas `Imovel.embedding` (`Vector(1536)`, `list[float] | None`), `Imovel.embedding_atualizado_em` (`datetime | None`), `Imovel.documento_hash` (`str | None`). As tasks 4, 5 e 6 leem e escrevem as três.

- [ ] **Step 1: Adicionar as duas dependências**

Em `pyproject.toml`, dentro de `dependencies`, junto das existentes:

```toml
    # Embeddings do catalogo (TEC-157). A Anthropic nao tem endpoint de
    # embeddings -- este e o segundo provedor do projeto, e serve so a
    # indexacao; o agente continua no `infra/anthropic.py`.
    "openai>=1.0",
    # O tipo `Vector` do SQLAlchemy. Sem ele a coluna `embedding` teria de
    # ficar fora do ORM e ser escrita por SQL cru, e a TEC-158 precisaria
    # dela mapeada para a busca.
    "pgvector>=0.3.6",
```

- [ ] **Step 2: Trocar a imagem nos dois lugares**

Em `docker-compose.yml`, no serviço `postgres`:

```yaml
    # pgvector nao publica imagem Alpine. A troca muda a distro base de musl
    # para glibc, e por isso o volume local e recriado e nao reaproveitado:
    # collation de texto difere entre as duas bibliotecas.
    image: pgvector/pgvector:pg16
```

Em `.github/workflows/ci.yml`, no serviço `postgres` do job de testes, a mesma linha:

```yaml
        image: pgvector/pgvector:pg16
```

- [ ] **Step 3: Recriar o volume local e subir**

```bash
docker compose down -v
docker compose up -d
```

Espere o healthcheck e **retente o passo seguinte por alguns segundos**: depois de subir, o `alembic` reprova por vários segundos com `ConnectionResetError [WinError 64]` mesmo com o container marcado `healthy`. Isso é conhecido e não é defeito.

- [ ] **Step 4: Escrever o teste que falha**

Crie `tests/integration/test_migracao_vetorial.py`:

```python
"""A `0017` criou a extensao, as tres colunas e o indice.

Basename distinto de qualquer arquivo em `tests/unit/`: basename repetido
entre unit e integration aborta a coleta da suite inteira.
"""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker


async def test_a_extensao_vector_existe() -> None:
    async with get_sessionmaker()() as session:
        presente = await session.scalar(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
    assert presente == 1


async def test_as_tres_colunas_existem_e_sao_nulaveis() -> None:
    esperadas = {
        "embedding": "USER-DEFINED",
        "embedding_atualizado_em": "timestamp with time zone",
        "documento_hash": "text",
    }
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "  FROM information_schema.columns "
                " WHERE table_name = 'imoveis' "
                "   AND column_name = ANY(:nomes)"
            ),
            {"nomes": list(esperadas)},
        )
        colunas = {linha.column_name: linha for linha in resultado}

    assert set(colunas) == set(esperadas)
    for nome, tipo in esperadas.items():
        assert colunas[nome].data_type == tipo
        # Nulaveis e o que faz os 520 imoveis ja importados entrarem como
        # pendentes sem backfill nenhum.
        assert colunas[nome].is_nullable == "YES"


async def test_o_indice_ivfflat_existe_com_cosseno() -> None:
    async with get_sessionmaker()() as session:
        definicao = await session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_imoveis_embedding'")
        )
    assert definicao is not None
    assert "ivfflat" in definicao
    assert "vector_cosine_ops" in definicao
```

- [ ] **Step 5: Rodar e confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_vetorial.py -v --tb=short
```

Esperado: as três FALHAM. A primeira porque a extensão não existe; as outras porque as colunas e o índice não existem.

- [ ] **Step 6: Escrever a migration**

Crie `alembic/versions/0017_indexacao_vetorial.py`:

```python
"""a indexacao vetorial do catalogo

TEC-157, RN-08.2 e RN-08.3. Fecha a divida que a `0016` declarou: ela deixou
`embedding` de fora porque a imagem do compose nao tinha pgvector, e a troca
de imagem pertence a esta card.

**O indice IVFFlat entra com `lists = 1`, e isso e deliberado.** IVFFlat e um
indice treinado: `lists` particiona o espaco, e a busca varre apenas as
particoes mais proximas. Com 520 a 2.000 imoveis, `lists = 100` colocaria ~5
vetores por particao e o recall despencaria; `lists = 1` degenera para
varredura da lista unica -- recall perfeito, custo de scan sequencial, que
nesta escala resolve em milissegundos e fica muito abaixo dos 400 ms da
RNF-03. **O indice esta aqui por conformidade com o SRS, nao porque a busca
dependa dele hoje.** Quem revisita `lists`, cobra o SLA ou migra para HNSW e
a TEC-159.

As tres colunas sao nulaveis porque hash nulo E a definicao de pendencia: e
o que faz o catalogo ja importado entrar na fila sem caminho de backfill.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

DIMENSOES = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("imoveis", sa.Column("embedding", Vector(DIMENSOES), nullable=True))
    op.add_column(
        "imoveis",
        sa.Column("embedding_atualizado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("imoveis", sa.Column("documento_hash", sa.Text(), nullable=True))

    op.execute(
        "CREATE INDEX ix_imoveis_embedding ON imoveis "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
    )


def downgrade() -> None:
    op.drop_index("ix_imoveis_embedding", table_name="imoveis")
    op.drop_column("imoveis", "documento_hash")
    op.drop_column("imoveis", "embedding_atualizado_em")
    op.drop_column("imoveis", "embedding")
    # A extensao NAO cai no downgrade: outra coisa pode ter passado a
    # depender dela, e `DROP EXTENSION` derrubaria em cascata.
```

- [ ] **Step 7: Mapear as colunas no ORM**

Em `src/mobia/domain/catalogo/models.py`, na classe `Imovel`, depois de `updated_at`, e com o import `from pgvector.sqlalchemy import Vector` no topo:

```python
    # TEC-157. As tres juntas respondem "este vetor ainda vale?" sem que
    # nenhum caminho de escrita precise avisar que o texto mudou.
    #
    # `documento_hash` e o portao preciso: sha256 do documento que gerou o
    # vetor. Se ele difere do hash do documento de hoje, o vetor esta velho.
    # `embedding_atualizado_em` e o pre-filtro barato -- comparado contra
    # `updated_at`, evita recalcular hash de linha que ninguem tocou.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_atualizado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    documento_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 8: Aplicar e rodar os testes**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_vetorial.py -v --tb=short
```

Esperado: as três PASSAM.

- [ ] **Step 9: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

Esperado: os três em 0. Se o `ruff format --check` reclamar, rode `ruff format src tests alembic evals` e refaça o `check`.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml docker-compose.yml .github/workflows/ci.yml \
        alembic/versions/0017_indexacao_vetorial.py \
        src/mobia/domain/catalogo/models.py \
        tests/integration/test_migracao_vetorial.py
git commit -m "feat(TEC-157): o catalogo tem coluna de vetor, e o banco tem pgvector"
```

---

## Task 2: O documento textual e o hash

**Files:**
- Create: `src/mobia/domain/catalogo/documento.py`
- Test: `tests/unit/test_documento_do_imovel.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emenda à RN-08.2)

**Interfaces:**
- Consumes: `Imovel` (Task 1, com as três colunas).
- Produces: `documento_de(imovel: Imovel) -> str` e `hash_do_documento(texto: str) -> str`. A Task 4 chama as duas; a Task 5 depende do comportamento do hash.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/unit/test_documento_do_imovel.py`:

```python
"""O documento embeddado: quais campos entram, e quando o hash muda.

Funcao pura, sem banco. O criterio de aceite da card -- "o texto embeddado
nao contem preco nem numero de quartos" -- virou os dois primeiros testes.
"""

import uuid

from mobia.domain.catalogo.documento import documento_de, hash_do_documento
from mobia.domain.catalogo.models import Imovel


def _imovel(**sobrescritas: object) -> Imovel:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "codigo": "AP-001",
        "titulo": "Apartamento reformado na Vila Mariana",
        "descricao": "Sala ampla com varanda gourmet e sol da manha.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "preco_aluguel": None,
        "condominio": 89000,
        "iptu_mensal": 31000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        # Texto sem digito de proposito: o teste abaixo afirma a ausencia dos
        # VALORES numericos, e digito solto dentro de texto livre legitimo
        # tornaria a assercao insustentavel.
        "caracteristicas": ["varanda gourmet", "portaria full time"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    return Imovel(**campos)


def test_nenhum_valor_numerico_do_imovel_aparece_no_documento() -> None:
    documento = documento_de(_imovel())

    # Os valores como o banco os guarda, e como um humano os leria.
    for proibido in ("74900000", "749000", "89000", "890", "31000", "310"):
        assert proibido not in documento, f"{proibido!r} vazou para o documento"

    # Nenhum algarismo, o que so vale porque o fixture usa texto sem digito:
    # e a forma mais forte de afirmar que area, quartos, suites, banheiros e
    # vagas nao entraram.
    assert not any(caractere.isdigit() for caractere in documento)


def test_o_documento_e_exatamente_os_seis_campos_nesta_ordem() -> None:
    # Igualdade exata, e nao `in`: e o que pega um campo novo entrando no
    # documento sem que ninguem decida que ele deve entrar.
    assert documento_de(_imovel()) == "\n".join(
        [
            "Apartamento reformado na Vila Mariana",
            "Sala ampla com varanda gourmet e sol da manha.",
            "APARTAMENTO",
            "Vila Mariana",
            "Sao Paulo",
            "varanda gourmet",
            "portaria full time",
        ]
    )


def test_os_quatro_textuais_de_filtro_ficam_fora() -> None:
    documento = documento_de(_imovel())

    # Dimensoes de filtro por igualdade, resolvidas no WHERE da RN-09.1.
    # Pedir ao vetor que entenda "para alugar" e o mesmo erro que pedir que
    # entenda "ate 600 mil".
    assert "VENDA" not in documento
    assert "DISPONIVEL" not in documento
    assert "SUL" not in documento
    assert "SP" not in documento


def test_os_seis_campos_que_entram_estao_no_documento() -> None:
    documento = documento_de(_imovel())

    assert "Apartamento reformado na Vila Mariana" in documento
    assert "Sala ampla com varanda gourmet" in documento
    assert "APARTAMENTO" in documento
    assert "Vila Mariana" in documento
    assert "Sao Paulo" in documento
    assert "portaria full time" in documento


def test_o_hash_nao_muda_quando_so_o_preco_muda() -> None:
    antes = hash_do_documento(documento_de(_imovel(preco_venda=74900000)))
    depois = hash_do_documento(documento_de(_imovel(preco_venda=69900000)))

    assert antes == depois


def test_o_hash_muda_quando_a_descricao_muda() -> None:
    antes = hash_do_documento(documento_de(_imovel()))
    depois = hash_do_documento(documento_de(_imovel(descricao="Reformado em 2026.")))

    assert antes != depois


def test_o_hash_e_sha256_em_hexadecimal() -> None:
    valor = hash_do_documento("qualquer texto")

    assert len(valor) == 64
    assert set(valor) <= set("0123456789abcdef")
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_documento_do_imovel.py -v --tb=short
```

Esperado: erro de coleta, `ModuleNotFoundError: No module named 'mobia.domain.catalogo.documento'`.

- [ ] **Step 3: Escrever a implementação**

Crie `src/mobia/domain/catalogo/documento.py`:

```python
"""O documento textual que vira embedding, e sua impressao digital.

TEC-157, RN-08.2. Funcao pura: sem banco, sem rede, sem `Settings`.

**A definicao do documento mora AQUI e em nenhum outro lugar.** A alternativa
era calcular o hash em SQL -- `md5(titulo || descricao || ...)` -- para que a
varredura resolvesse tudo numa consulta. Foi recusada: a lista de campos
passaria a existir em dois lugares, e o dia em que divergissem o sintoma
seria embedding silenciosamente velho, sem erro nenhum. A varredura paga um
pre-filtro barato em SQL e a comparacao exata aqui.

**Por que estes seis campos, e por que quatro textuais ficam fora.** A secao
4.4 do SRS manda embedar descricao, bairro, tipologia e diferenciais, e
manter os numericos fora, "evitando o erro classico de pedir ao vetor que
entenda 'ate 600 mil'". `operacao`, `status`, `zona` e `uf` saem pelo mesmo
principio: sao dimensoes de filtro por igualdade, resolvidas no WHERE da
RN-09.1. `titulo` e `cidade` entram alem dos quatro do SRS -- o titulo por
ser texto livre descritivo, a cidade porque bairro homonimo em cidades
diferentes colide. Ver a Emenda E-01 a RN-08.2.
"""

import hashlib

from mobia.domain.catalogo.models import Imovel


def documento_de(imovel: Imovel) -> str:
    """O texto normalizado de um imovel, um documento por imovel.

    Nao fragmenta em chunks: o registro ja e curto e coeso, e fragmentar
    destruiria a associacao entre caracteristica e imovel (secao 4.4).
    """
    partes = [
        imovel.titulo,
        imovel.descricao,
        imovel.tipo,
        imovel.bairro,
        imovel.cidade,
        *imovel.caracteristicas,
    ]
    return "\n".join(parte.strip() for parte in partes if parte and parte.strip())


def hash_do_documento(texto: str) -> str:
    """Impressao digital do documento, para detectar mudanca.

    Nao e escolha criptografica: e deteccao de mudanca. `sha256` custa o
    mesmo que `md5` nesta escala e nao deixa ninguem ler a escolha como
    decisao de seguranca que ela nao e.
    """
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_documento_do_imovel.py -v --tb=short
```

Esperado: as sete PASSAM.

Se `test_o_documento_e_exatamente_os_seis_campos_nesta_ordem` falhar, compare o esperado com o obtido antes de mexer no teste: a igualdade exata existe para pegar campo entrando no documento sem decisão, e mudar o esperado sem decidir é justamente o que ela impede. **Não** afrouxe para `in`.

- [ ] **Step 5: Escrever a emenda ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, como item **aninhado** logo abaixo da linha da RN-08.2, sem reescrever o texto de 22/08:

```markdown
  - **Emenda E-01 (TEC-157, 07/09/2026):** o documento embeddado inclui `titulo` e `cidade` além dos quatro itens que a seção 4.4 lista — o título porque é texto livre descritivo do imóvel, a cidade porque bairro homônimo em cidades diferentes colide e o filtro estruturado da RN-09.1 filtra por bairro. Ficam **fora** todos os numéricos e também quatro textuais: `operacao`, `status`, `zona` e `uf`, por serem dimensões de filtro por igualdade resolvidas no `WHERE` — o mesmo princípio que a seção 4.4 aplica ao preço. `fotos` fica fora por não ser texto descritivo. A definição vive em `domain/catalogo/documento.py` e em nenhum outro lugar; ver a D3 do desenho.
```

E acrescente a linha correspondente à tabela de emendas no topo do arquivo:

```markdown
> | E-01 | RN-08.2 | [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157) | 07/09/2026 |
```

- [ ] **Step 6: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/catalogo/documento.py \
        tests/unit/test_documento_do_imovel.py \
        docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "feat(TEC-157): o imovel tem um documento textual, e o preco nao entra nele"
```

---

## Task 3: Settings e o cliente de embedding

**Files:**
- Modify: `src/mobia/app/config.py` (classe `Settings`, junto dos `sweep_*`)
- Create: `src/mobia/infra/embeddings.py`
- Test: `tests/unit/test_cliente_de_embedding.py`

**Interfaces:**
- Consumes: `ConfiguracaoInsegura` e `get_settings` de `mobia.app.config`.
- Produces: `get_client() -> AsyncOpenAI`, `async def embedar(textos: list[str]) -> list[list[float]]`, `motivo_do_provedor(exc: BaseException) -> str | None`, e as constantes `TIMEOUT_SEGUNDOS` e `MAX_TENTATIVAS`. A Task 4 chama `embedar`.

- [ ] **Step 1: Acrescentar os cinco campos a `Settings`**

Em `src/mobia/app/config.py`, logo depois de `sweep_max_attempts`:

```python
    # TEC-157. A chave do provedor de embedding, que NAO e a da Anthropic: a
    # API da Anthropic nao tem endpoint de embeddings, entao a indexacao usa
    # um segundo provedor e o agente segue no `infra/anthropic.py`.
    openai_api_key: str | None = None

    # 1536 nao e ajustavel a gosto: e a dimensao da coluna `vector(1536)` da
    # `0017` e a do modelo escolhido. Mudar aqui sem migration deixa o
    # provedor devolvendo vetor que a coluna recusa.
    embedding_modelo: str = "text-embedding-3-small"
    embedding_dimensoes: int = 1536

    # Teto de candidatos por passagem e tamanho do lote por chamada. O lote e
    # MENOR que o teto de proposito: com um lote so, "comita por lote" nao
    # significaria nada -- uma falha desfaria a passagem inteira. Com dois,
    # uma falha na segunda chamada preserva os 50 primeiros.
    indexacao_limite_por_passagem: int = 100
    indexacao_tamanho_do_lote: int = 50
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/unit/test_cliente_de_embedding.py`:

```python
"""A guarda da chave ausente, e o lote vazio.

Nenhuma chamada de rede: os testes que exercitam o cliente de verdade nao
existem, de proposito. Uma suite de 22 minutos nao pode passar a depender de
provedor externo -- seria flake por rede, nao sinal.
"""

import pytest

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.infra import embeddings


def test_sem_chave_o_cliente_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    # `setenv` com string vazia, e nao `delenv`: variavel de ambiente vence o
    # `.env` no pydantic-settings, e string vazia e falsy. Com `delenv`, uma
    # chave presente no `.env` de quem executa faria o teste falhar por
    # ambiente.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    embeddings.get_client.cache_clear()

    with pytest.raises(ConfiguracaoInsegura) as erro:
        embeddings.get_client()

    assert "OPENAI_API_KEY" in str(erro.value)


async def test_lote_vazio_nao_chama_o_provedor(monkeypatch: pytest.MonkeyPatch) -> None:
    # Se `embedar([])` chamasse o provedor, a guarda da chave levantaria --
    # entao passar sem chave configurada E a assercao.
    # `setenv` com string vazia, e nao `delenv`: variavel de ambiente vence o
    # `.env` no pydantic-settings, e string vazia e falsy. Com `delenv`, uma
    # chave presente no `.env` de quem executa faria o teste falhar por
    # ambiente.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    embeddings.get_client.cache_clear()

    assert await embeddings.embedar([]) == []


def test_o_timeout_do_cliente_cabe_no_job_timeout() -> None:
    # Mesmo raciocinio do comentario em `infra/anthropic.py`: o teto por
    # chamada tem de ser estritamente menor que o `job_timeout` do worker,
    # senao uma chamada lenta nao falha -- e cancelada pelo ARQ.
    pior_caso = embeddings.TIMEOUT_SEGUNDOS * (embeddings.MAX_TENTATIVAS + 1)
    lotes_por_passagem = 2

    assert pior_caso * lotes_por_passagem < 240
```

- [ ] **Step 3: Rodar e confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_cliente_de_embedding.py -v --tb=short
```

Esperado: erro de coleta, `ImportError: cannot import name 'embeddings'`.

- [ ] **Step 4: Escrever a implementação**

Crie `src/mobia/infra/embeddings.py`:

```python
"""Cliente do provedor de embedding, no molde do `infra/anthropic.py`.

TEC-157. **Este NAO e o cliente da Anthropic**, e a razao e simples: a API da
Anthropic tem Messages, Batches, Files, Token Counting e Models, e nao tem
endpoint de embeddings. Esta card introduz necessariamente um segundo
provedor. O agente continua no `infra/anthropic.py`.

O teto por chamada segue o mesmo raciocinio do vizinho: o default do SDK e
alto demais para o `job_timeout` de 240s do worker, e uma chamada lenta sem
teto proprio nao falha -- e cancelada pelo ARQ, que e o desfecho pior. Com
50s e uma retentativa, o pior caso e 100s por lote; a varredura faz no maximo
dois lotes por passagem, o que fecha em 200s e cabe nos 240s. Ver o
comentario de `job_timeout` em `workers/main.py`.
"""

from functools import lru_cache

from openai import APIStatusError, AsyncOpenAI

from mobia.app.config import ConfiguracaoInsegura, get_settings

TIMEOUT_SEGUNDOS = 50.0
MAX_TENTATIVAS = 1

MAX_CARACTERES_DO_MOTIVO = 300


@lru_cache
def get_client() -> AsyncOpenAI:
    """Cliente unico do processo.

    Construido sob demanda e nao no import, pelo mesmo motivo do
    `infra/anthropic.py`: importar o modulo nao pode exigir credencial, senao
    a suite inteira passa a precisar de chave para colecionar testes que
    nunca chamam o provedor.
    """
    chave = get_settings().openai_api_key
    if not chave:
        raise ConfiguracaoInsegura(
            "OPENAI_API_KEY nao configurada. A indexacao vetorial do TEC-157 "
            "precisa dela; defina no .env ou no ambiente antes de subir o worker."
        )
    return AsyncOpenAI(api_key=chave, timeout=TIMEOUT_SEGUNDOS, max_retries=MAX_TENTATIVAS)


async def embedar(textos: list[str]) -> list[list[float]]:
    """Os vetores dos textos, na mesma ordem.

    Lote vazio nao chama o provedor: a varredura pode terminar uma passagem
    sem candidato pendente, e pagar uma requisicao por isso seria absurdo.

    A chamada com array e tudo-ou-nada: falha inteira ou volta inteira. Isso
    e o que permite a varredura retentar um lote na integra, sem estado
    parcial para conciliar.
    """
    if not textos:
        return []

    settings = get_settings()
    resposta = await get_client().embeddings.create(
        model=settings.embedding_modelo,
        input=textos,
        dimensions=settings.embedding_dimensoes,
    )
    # A API nao garante a ordem de `data`; `index` e o que amarra cada vetor
    # ao texto que o gerou.
    return [item.embedding for item in sorted(resposta.data, key=lambda item: item.index)]


def motivo_do_provedor(exc: BaseException) -> str | None:
    """O porque de um erro de protocolo do provedor, sem conteudo do lead.

    Mesma excecao deliberada que o `infra/anthropic.py` abre e pelo mesmo
    motivo: o corpo de erro de um `APIStatusError` e gerado pelo servidor, e
    nao carrega texto do lead. Para qualquer outra excecao, devolve None --
    `str(exc)` de excecao arbitraria pode carregar o que nao deve ir para log.
    """
    if not isinstance(exc, APIStatusError):
        return None
    return f"{exc.status_code}: {str(exc)[:MAX_CARACTERES_DO_MOTIVO]}"
```

- [ ] **Step 5: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_cliente_de_embedding.py -v --tb=short
```

Esperado: as três PASSAM.

- [ ] **Step 6: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 7: Commit**

```bash
git add src/mobia/app/config.py src/mobia/infra/embeddings.py \
        tests/unit/test_cliente_de_embedding.py
git commit -m "feat(TEC-157): o projeto passa a ter um cliente de embedding, com teto que cabe no job"
```

---

## Task 4: A varredura indexa o que está pendente

**Files:**
- Create: `src/mobia/workers/jobs/indexar_catalogo.py`
- Modify: `tests/conftest.py` (acrescentar `EmbedadorFake`)
- Test: `tests/integration/test_indexacao_do_catalogo.py`

**Interfaces:**
- Consumes: `documento_de` e `hash_do_documento` (Task 2); `embedar` (Task 3); as três colunas (Task 1).
- Produces: `async def indexar_catalogo(ctx: dict[str, Any], limite: int | None = None) -> int`, devolvendo quantos imóveis foram embeddados nesta passagem. `EmbedadorFake` com atributo `.chamadas: list[list[str]]`. As tasks 5, 6 e 7 usam as duas.

- [ ] **Step 1: Acrescentar o `EmbedadorFake` ao conftest**

Em `tests/conftest.py`, junto das outras classes falsas:

```python
class EmbedadorFake:
    """Substitui `infra.embeddings.embedar` na suite.

    Guarda os lotes recebidos em `chamadas`, que e o que permite afirmar
    ZERO chamadas -- a assercao central do criterio "alteracao de preco nao
    regera embedding". Afirmar "o vetor parece igual" nao provaria nada: com
    uma implementacao por posicao o vetor tambem sairia igual.
    """

    def __init__(self, dimensoes: int = 1536, falhar: bool = False) -> None:
        self.dimensoes = dimensoes
        self.falhar = falhar
        self.chamadas: list[list[str]] = []

    async def __call__(self, textos: list[str]) -> list[list[float]]:
        if not textos:
            return []
        self.chamadas.append(list(textos))
        if self.falhar:
            raise RuntimeError("provedor de embedding indisponivel")
        # Vetor deterministico e distinto por texto: o teste precisa
        # distinguir "reindexou" de "manteve o vetor antigo".
        return [[float(len(texto) % 7 + indice) / 10.0] * self.dimensoes
                for indice, texto in enumerate(textos)]
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/integration/test_indexacao_do_catalogo.py`:

```python
"""A varredura da indexacao vetorial.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from conftest import EmbedadorFake
from sqlalchemy import select

from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
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
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


def _ctx(embedador: EmbedadorFake) -> dict[str, Any]:
    return {"session_factory": get_sessionmaker(), "embedador": embedador}


async def test_imovel_novo_e_indexado(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None


async def test_a_segunda_passagem_nao_reindexa_nada(session: Any) -> None:
    await _imovel(session)
    embedador = EmbedadorFake()

    await indexar_catalogo(_ctx(embedador))
    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 0
    # Uma chamada na primeira passagem, nenhuma na segunda.
    assert len(embedador.chamadas) == 1


async def test_o_teto_por_passagem_limita(session: Any) -> None:
    for numero in range(5):
        await _imovel(session, codigo=f"AP-{numero:03d}")
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador), limite=3)

    assert indexados == 3
```

- [ ] **Step 3: Rodar e confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indexacao_do_catalogo.py -v --tb=short
```

Esperado: erro de coleta, `ModuleNotFoundError: No module named 'mobia.workers.jobs.indexar_catalogo'`.

- [ ] **Step 4: Escrever a implementação**

Crie `src/mobia/workers/jobs/indexar_catalogo.py`:

```python
"""A varredura que mantem o vetor do catalogo atualizado.

TEC-157, RN-08.2 e RN-08.3. Molde da `sweep_stalled`: SQL cru para a
selecao, teto por passagem, `FOR UPDATE SKIP LOCKED`.

**A pendencia e derivada do estado da linha, e nao avisada por quem escreve.**
Esta e a decisao central da card (D2 do desenho), e a alternativa recusada
era usar o gancho que a TEC-156 preservou -- a importacao sabe quais campos
mudaram, logo ela enfileira. Foi recusada por tres motivos, todos ja pagos
por este repo: o caminho de corrida do `ON CONFLICT` nao passa por `_mudou`,
entao uma linha atualizada por ali nunca seria reindexada e nao haveria
sintoma; os imoveis ja importados exigiriam backfill proprio; e
enfileiramento que falha nao retoma -- o bug que a TEC-156 corrigiu no
endpoint e a lacuna que a TEC-261 existe para fechar.

**A regra "falha de embedding nao bloqueia o atendimento" sai da topologia,
nao de um `try/except`.** Este job e um cron separado: nao existe caminho em
que `process_message` chame o provedor de embedding. Isso e mais forte que
capturar excecao -- e e por isso que esta escrito aqui. Um refactor futuro
que chame o embedding de dentro do turno violaria a RN da card sem que teste
nenhum reclamasse.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text, update

from mobia.app.config import Settings, get_settings
from mobia.domain.catalogo.documento import documento_de, hash_do_documento
from mobia.domain.catalogo.models import Imovel
from mobia.infra.embeddings import embedar as embedar_de_verdade
from mobia.infra.embeddings import motivo_do_provedor

log = structlog.get_logger(__name__)

# O `embedding_atualizado_em IS NULL` esta explicito de proposito: sem ele,
# `updated_at > NULL` da NULL e imovel recem-inserido nunca seria candidato.
#
# Nenhum nome de campo do documento aparece aqui, e isso e o ponto da D3: a
# definicao do documento mora em `documento.py` e a comparacao exata e feita
# em Python. Um `md5` de colunas concatenadas nesta consulta duplicaria a
# lista de campos, e a divergencia se manifestaria como vetor velho e mudo.
_SELECIONAR_PENDENTES = text(
    """
    SELECT id
      FROM imoveis
     WHERE embedding IS NULL
        OR documento_hash IS NULL
        OR embedding_atualizado_em IS NULL
        OR updated_at > embedding_atualizado_em
     ORDER BY updated_at
     LIMIT :limite
       FOR UPDATE SKIP LOCKED
    """
)


async def indexar_catalogo(ctx: dict[str, Any], limite: int | None = None) -> int:
    """Indexa uma passagem de candidatos. Devolve quantos foram embeddados.

    O retorno conta EMBEDDADOS, nao candidatos: uma linha cujo hash bate e
    candidata, e carimbada, e nao entra na conta -- porque nada foi gerado
    para ela.
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    embedar = ctx.get("embedador") or embedar_de_verdade

    teto = limite if limite is not None else settings.indexacao_limite_por_passagem
    lote_maximo = settings.indexacao_tamanho_do_lote

    async with session_factory() as session:
        resultado = await session.execute(_SELECIONAR_PENDENTES, {"limite": teto})
        identificadores = [linha.id for linha in resultado]

        if not identificadores:
            # A passagem ociosa e barata de proposito: nesta cadencia, a
            # consulta que nao devolve nada e o caso comum.
            await session.rollback()
            return 0

        # Carregados pelo ORM, e nao por `SELECT *` cru: `embedding` e uma
        # coluna `Vector`, e reconstruir `Imovel(**linha)` de um mapping
        # entregaria texto onde o tipo espera lista.
        imoveis = list(
            (await session.scalars(select(Imovel).where(Imovel.id.in_(identificadores)))).all()
        )

        pendentes: list[tuple[uuid.UUID, str, str]] = []
        carimbar_apenas: list[uuid.UUID] = []

        # Os atributos sao lidos AQUI, antes do rollback: depois dele os
        # objetos ficam expirados e tocar um campo dispararia I/O de novo.
        for imovel in imoveis:
            texto_do_documento = documento_de(imovel)
            digest = hash_do_documento(texto_do_documento)

            if imovel.embedding is not None and imovel.documento_hash == digest:
                # O hash bate: o vetor ainda vale. Este e o ramo que cumpre
                # "alteracao de preco nao regera embedding" -- o preco bumpou
                # `updated_at`, a linha virou candidata, e nada e chamado. O
                # carimbo e o que impede a linha de ficar candidata para
                # sempre.
                carimbar_apenas.append(imovel.id)
            else:
                pendentes.append((imovel.id, texto_do_documento, digest))

        candidatos = len(imoveis)

        # Os locks da selecao sao soltos antes de qualquer I/O de rede, pelo
        # mesmo motivo que a `sweep_stalled` documenta: segurar lock de linha
        # no Postgres enquanto se fala com um provedor externo e ruim por si
        # so. A exclusao entre varreduras concorrentes nao depende de manter
        # o lock -- ver o `SKIP LOCKED` acima e o teste de concorrencia.
        await session.rollback()

    embeddados = 0
    agora = datetime.now(UTC)

    for inicio in range(0, len(pendentes), lote_maximo):
        lote = pendentes[inicio : inicio + lote_maximo]

        try:
            vetores = await embedar([texto for _, texto, _ in lote])
        except Exception as erro:
            # Loga o porque e RELEVANTA. Nao engolir e deliberado: a linha
            # continua pendente e a proxima passagem a pega, entao a falha
            # nao precisa de tratamento -- precisa de registro. O motivo vem
            # de `motivo_do_provedor`, que so devolve texto para erro de
            # protocolo do provedor; para qualquer outra excecao devolve None,
            # porque `str(exc)` arbitrario pode carregar o que nao deve ir
            # para log.
            log.warning(
                "indexacao_do_catalogo_falhou",
                lote=len(lote),
                embeddados_antes=embeddados,
                motivo=motivo_do_provedor(erro),
            )
            raise

        async with session_factory() as escrita:
            for (identificador, _, digest), vetor in zip(lote, vetores, strict=True):
                await escrita.execute(
                    update(Imovel)
                    .where(Imovel.id == identificador)
                    .values(
                        embedding=vetor,
                        documento_hash=digest,
                        embedding_atualizado_em=agora,
                    )
                )
            # Commit por lote: uma falha no lote seguinte preserva este.
            await escrita.commit()
        embeddados += len(lote)

    if carimbar_apenas:
        async with session_factory() as escrita:
            await escrita.execute(
                update(Imovel)
                .where(Imovel.id.in_(carimbar_apenas))
                .values(embedding_atualizado_em=agora)
            )
            await escrita.commit()

    log.info(
        "indexacao_do_catalogo",
        candidatos=candidatos,
        embeddados=embeddados,
        carimbados=len(carimbar_apenas),
    )
    return embeddados
```

- [ ] **Step 5: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indexacao_do_catalogo.py -v --tb=short
```

Esperado: as três PASSAM.

- [ ] **Step 6: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 7: Commit**

```bash
git add src/mobia/workers/jobs/indexar_catalogo.py tests/conftest.py \
        tests/integration/test_indexacao_do_catalogo.py
git commit -m "feat(TEC-157): a varredura indexa o imovel pendente, e a pendencia sai do estado da linha"
```

---

## Task 5: O portão do hash — preço não regera, descrição regera

**Files:**
- Test: `tests/integration/test_indexacao_do_catalogo.py` (acrescentar)
- Modify: `src/mobia/workers/jobs/indexar_catalogo.py` (só se um teste reprovar)

**Interfaces:**
- Consumes: `indexar_catalogo` e `EmbedadorFake` (Task 4).
- Produces: nada novo.

Esta task existe separada porque é **o critério de aceite mais fácil de fingir que passa**. Os dois testes abaixo passariam com uma implementação errada se fossem escritos como "o vetor parece igual" — a asserção tem de ser sobre o número de chamadas.

- [ ] **Step 1: Escrever os dois testes que devem passar**

Acrescente a `tests/integration/test_indexacao_do_catalogo.py`:

```python
async def test_mudanca_de_preco_nao_faz_chamada_nenhuma(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET preco_venda = 69900000, updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    # A assercao e sobre CHAMADAS, e nao sobre o vetor: um vetor igual nao
    # provaria nada, porque uma implementacao errada tambem o devolveria.
    assert indexados == 0
    assert len(embedador.chamadas) == 1


async def test_mudanca_de_descricao_gera_vetor_e_hash_novos(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))

    async with get_sessionmaker()() as leitura:
        antes = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert antes is not None
    hash_antigo = antes.documento_hash

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET descricao = 'Reformado em 2026.', "
                "       updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 2

    async with get_sessionmaker()() as leitura:
        depois = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert depois is not None
    assert depois.documento_hash != hash_antigo
```

Acrescente `text` ao import do `sqlalchemy` no topo do arquivo:

```python
from sqlalchemy import select, text
```

O `import pytest` **não** entra ainda: nada nesta task o usa, e import sem uso é `F401` no `ruff check`. Ele entra na Task 6, junto do `pytest.raises`.

- [ ] **Step 2: Rodar os dois**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indexacao_do_catalogo.py -v --tb=short
```

Esperado: as cinco PASSAM, sem tocar a implementação. Se `test_mudanca_de_preco_nao_faz_chamada_nenhuma` reprovar com `len(chamadas) == 2`, o ramo do hash igual na Task 4 está errado — corrija-o ali, não afrouxe o teste.

- [ ] **Step 3: Provar que o teste separa as duas implementações**

Este passo não muda código em definitivo. Troque temporariamente a condição do ramo do hash em `indexar_catalogo.py`:

```python
        if linha["embedding"] is not None:  # ERRADO de proposito: ignora o hash
```

Rode os cinco testes. Esperado: `test_mudanca_de_descricao_gera_vetor_e_hash_novos` FALHA. **Desfaça a troca** e confirme que os cinco voltam a passar.

Isso é o que a TEC-188 aprendeu do jeito difícil: dois testes que passam com as duas implementações não testam a distinção que a card existe para fazer.

- [ ] **Step 4: Os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_indexacao_do_catalogo.py
git commit -m "test(TEC-157): mudanca de preco nao gera chamada, e o teste separa as duas implementacoes"
```

---

## Task 6: Falha do provedor e varreduras concorrentes

**Files:**
- Test: `tests/integration/test_indexacao_do_catalogo.py` (acrescentar)

**Interfaces:**
- Consumes: `indexar_catalogo`, `EmbedadorFake(falhar=True)` (Task 4).
- Produces: nada novo.

- [ ] **Step 1: Escrever os três testes**

Primeiro acrescente ao topo do arquivo o import que esta task passa a usar:

```python
import asyncio
```

`import pytest` **não** entra: depois da correção da Task 4 o job não relevanta mais, então não há `pytest.raises` aqui, e import sem uso é `F401`.

Então os testes:

```python
async def test_imovel_vendido_tambem_e_indexado(session: Any) -> None:
    # D9: a RN-08.4 tira o nao disponivel dos RESULTADOS da busca, mas o
    # corte por status e da busca, nao da indexacao. Filtrar aqui criaria o
    # caso em que reativar um imovel o deixa sem vetor.
    identificador = await _imovel(session, status="VENDIDO")
    embedador = EmbedadorFake()

    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None


async def test_falha_do_provedor_deixa_a_linha_pendente(session: Any) -> None:
    identificador = await _imovel(session)

    # NAO levanta, e isso e deliberado. Relevantar faria um documento que o
    # provedor rejeita de forma permanente abortar a passagem inteira -- e com
    # `ORDER BY updated_at` ele cai no lote 1 de TODA passagem, entao nada mais
    # no catalogo seria indexado nunca, com um warning por tick como unico
    # sintoma. O job loga e segue, no molde do `sweep_stalled`.
    assert await indexar_catalogo(_ctx(EmbedadorFake(falhar=True))) == 0

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    # A linha so e gravada em caso de sucesso: falha deixa o candidato como
    # estava, e a retomada nao depende do retry do ARQ -- o cron roda de novo.
    assert imovel.embedding is None
    assert imovel.documento_hash is None

    embedador = EmbedadorFake()
    assert await indexar_catalogo(_ctx(embedador)) == 1


async def test_varreduras_concorrentes_deixam_a_linha_indexada_uma_vez(
    session: Any,
) -> None:
    identificador = await _imovel(session)
    primeiro = EmbedadorFake()
    segundo = EmbedadorFake()

    await asyncio.gather(
        indexar_catalogo(_ctx(primeiro)),
        indexar_catalogo(_ctx(segundo)),
    )

    # A assercao e sobre o DESFECHO, e nao sobre o numero de chamadas.
    #
    # `FOR UPDATE SKIP LOCKED` impede duas varreduras de selecionar a mesma
    # linha no mesmo instante, mas o lock e solto antes do I/O de rede -- de
    # proposito, herdado da `sweep_stalled`: segurar lock de linha atravessando
    # chamada a provedor externo e pior. Entao uma varredura que comece depois
    # do rollback da outra pode gastar uma chamada em duplicidade. Isso e
    # desperdicio idempotente, nao incorrecao: mesmo texto gera mesmo vetor, e
    # a ultima escrita tem o mesmo conteudo da primeira.
    #
    # Afirmar `len(chamadas) == 1` aqui seria afirmar mais do que o desenho
    # garante, e o teste flakearia sob carga por um motivo que nao e defeito.
    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None

    # E a linha nao fica candidata depois: a proxima passagem nao chama nada.
    terceiro = EmbedadorFake()
    assert await indexar_catalogo(_ctx(terceiro)) == 0
    assert terceiro.chamadas == []
```

- [ ] **Step 2: Rodar todos os oito**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indexacao_do_catalogo.py -v --tb=short
```

Esperado: os oito PASSAM — três da Task 4, dois da Task 5, três desta.

Este arquivo é de integração e está na família que flakeia sob carga (`ConnectionResetError`, erro de Redis). **Rode o arquivo isolado antes de concluir que é defeito seu**, conforme o CLAUDE.md.

- [ ] **Step 3: Os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_indexacao_do_catalogo.py
git commit -m "test(TEC-157): imovel vendido tambem indexa, e falha do provedor deixa a linha pendente"
```

---

## Task 7: Registro no worker

**Files:**
- Modify: `src/mobia/workers/main.py:84-101`
- Test: `tests/integration/test_registro_do_cron_vetorial.py`

**Interfaces:**
- Consumes: `indexar_catalogo` (Task 4).
- Produces: o job registrado em `WorkerSettings.functions` e em `WorkerSettings.cron_jobs`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/integration/test_registro_do_cron_vetorial.py`:

```python
"""O job da indexacao esta registrado nos DOIS lugares.

Registrar so em `functions` deixa o job chamavel e nunca chamado; so em
`cron_jobs`, o ARQ nao acha a funcao. O par e o que faz o cron existir.
"""

from mobia.workers.jobs.indexar_catalogo import indexar_catalogo
from mobia.workers.main import WorkerSettings


def test_o_job_esta_em_functions() -> None:
    nomes = {
        getattr(funcao, "name", None) or getattr(funcao, "__name__", None)
        for funcao in WorkerSettings.functions
    }
    assert "indexar_catalogo" in nomes


def test_o_job_esta_em_cron_jobs_a_cada_30_segundos() -> None:
    agendados = [
        job for job in WorkerSettings.cron_jobs
        if getattr(job.coroutine, "__name__", None) == indexar_catalogo.__name__
    ]
    assert len(agendados) == 1
    assert agendados[0].second == {0, 30}
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_registro_do_cron_vetorial.py -v --tb=short
```

Esperado: os dois FALHAM — `assert 'indexar_catalogo' in nomes` e `assert 0 == 1`.

- [ ] **Step 3: Registrar nos dois lugares**

Em `src/mobia/workers/main.py`, acrescente o import no topo:

```python
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo
```

Em `functions`, junto dos existentes:

```python
        indexar_catalogo,
```

Em `cron_jobs`, junto dos existentes:

```python
        # De 30 em 30 segundos, como a `sweep_stalled` e nao como a
        # `sweep_followups`: o pre-filtro nao devolve nada quando nao ha
        # pendencia, entao a passagem ociosa e barata -- e a janela entre
        # importar e poder buscar e exatamente o que a indexacao eventual
        # custou. Encurta-la e o uso mais obvio de um cron barato.
        cron(indexar_catalogo, second={0, 30}, run_at_startup=False),
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_registro_do_cron_vetorial.py -v --tb=short
```

Esperado: os dois PASSAM.

- [ ] **Step 5: A suíte inteira**

```bash
./.venv/Scripts/python.exe -u -m pytest -v --tb=short
```

Isto leva **~22 minutos e roda ~1240 testes** em máquina ociosa, e mais sob carga. Saída vazia por dez minutos é normal, não deadlock. `--tb=short` está aí de propósito: com `-q` você descobriria só o nome do teste que falhou e teria de rodar tudo de novo para diagnosticar.

Se algum de `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` ou `test_optout_repositorio.py` falhar, **rode o arquivo isolado antes** de atribuir a falha a esta card.

- [ ] **Step 6: Os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/workers/main.py tests/integration/test_registro_do_cron_vetorial.py
git commit -m "feat(TEC-157): o cron da indexacao roda de 30 em 30 segundos"
```

- [ ] **Step 7: Registrar o resultado da suíte**

Guarde o hash do commit junto com o resultado da execução. Na TEC-156, `b35069d` passou 1236/1236 e a execução seguinte, sobre árvore idêntica e limpa, falhou 1 — o que descarta regressão é a mesma árvore dando dois resultados, e sem o hash anotado esse argumento não existe.

---

## Cobertura do desenho

| Seção do desenho | Task |
|---|---|
| D1 — provedor OpenAI, 1536d | 1 (dependência), 3 (cliente) |
| D2 — pendência derivada do estado | 4 |
| D3 — documento em Python, hash `sha256` do texto | 2 |
| D4 — seis campos dentro, quatro textuais fora | 2 |
| D5 — eventual em cron; regra pela topologia | 4 (docstring), 7 (cron) |
| D6 — imagem nos dois lugares, volume recriado | 1 |
| D7 — IVFFlat por conformidade, `lists = 1` | 1 |
| D8 — cadência de 30 segundos | 7 |
| D9 — indexa em qualquer `status` | 4 (nenhum filtro na consulta), 6 (teste do `VENDIDO`) |
| D10 — chave ausente recusa em produção | 3 |
| Modelo de dados (`0017`) | 1 |
| Fluxo — pré-filtro, portão do hash, carimbo | 4, 5 |
| Fluxo — falha do provedor, lote, teto | 3, 4, 6 |
| Testes — zero rede, basename sem colisão | 1-7 |
| Emenda à RN-08.2 | 2 |
