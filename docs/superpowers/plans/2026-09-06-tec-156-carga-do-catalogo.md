# TEC-156 — Carga do catálogo por arquivo · Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carregar o catálogo de imóveis a partir de CSV/JSON, por CLI de seed e por endpoint administrativo, devolvendo um relatório que aponta cada linha rejeitada com o motivo, sem abortar o lote.

**Architecture:** Um núcleo puro (`domain/catalogo/`) com parser, repositório e orquestração, e duas cascas finas que o chamam — a CLI processa no próprio processo, o endpoint HTTP enfileira um job ARQ. O upsert é por `codigo`, com diff campo a campo em Python, o que separa `atualizado` de `inalterado` e deixa pronto o gancho que a TEC-157 usará para decidir se regera embedding.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, ARQ, pytest + pytest-asyncio, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-06-tec-156-carga-do-catalogo-design.md` (commit `b1e6a21`). Leia a spec antes de começar — cada tarefa aponta para a decisão (D1–D11) que a justifica.

## Global Constraints

- **Branch:** `feat/tec-156-carga-do-catalogo`, criada a partir de `main` em `64535a7`. Nunca commitar em `main`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum.
- **Prosa em `docs/`: com acento.**
- **Mensagem de commit:** `tipo(TEC-156): o que passou a ser verdade`, assunto em português sem acento.
- **Os três gates estáticos, nesta ordem, antes de cada commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  O escopo é `src tests alembic evals`, não `src tests`. **`ruff format --check` é gate separado de `ruff check`** — passar num não diz nada sobre o outro.
- **A suíte é lenta:** `tests/unit` sozinho leva ~7 min; a suíte completa ~7,5 min e 857 testes. Com `-q` o pytest só imprime no fim, então saída vazia após dez minutos é normal, não deadlock. Para ver progresso: `python -u -m pytest -v`.
- **Depois de `docker compose restart`, o Postgres reprova `alembic upgrade head` por vários segundos** com `ConnectionResetError [WinError 64]`, mesmo com o container `healthy`. Espere e retente antes de diagnosticar.
- **Basename de teste não pode colidir entre `tests/unit/` e `tests/integration/`** — colisão aborta a coleta da suíte inteira e não aparece rodando o arquivo sozinho.
- **Comentário desatualizado é defeito.** Se mudar código que um comentário descreve, o comentário muda junto ou some.
- **Preço em centavos no banco; em reais decimais no arquivo.** Faixa de plausibilidade: `[R$ 1.000, R$ 500.000.000]` = `[100_000, 50_000_000_000]` centavos.
- **Lote de upsert: 500 registros.** Teto de upload HTTP: 10 MB.

## Mapa de arquivos

| arquivo | responsabilidade |
|---|---|
| `src/mobia/domain/catalogo/enums.py` | os seis domínios enumerados, `StrEnum` |
| `src/mobia/domain/catalogo/schemas.py` | `RegistroImovel`, `Rejeicao`, `Relatorio` — puros, sem I/O |
| `src/mobia/domain/catalogo/parser.py` | `bytes -> Iterator[RegistroImovel \| Rejeicao]`; `ArquivoInvalido` |
| `src/mobia/domain/catalogo/models.py` | `Imovel`, `Importacao` (SQLAlchemy) |
| `src/mobia/domain/catalogo/repositorio.py` | upsert por `codigo` + diff campo a campo |
| `src/mobia/domain/catalogo/importacao.py` | orquestra parser + repositório, grava o relatório |
| `src/mobia/admin/seed_catalogo.py` | CLI de seed |
| `src/mobia/api/deps.py` | `+ exigir_admin` |
| `src/mobia/api/routes/imoveis.py` | `POST /importar`, `GET /importacoes/{id}` |
| `src/mobia/app/config.py` | `+ catalogo_admin_token` e guarda de produção |
| `src/mobia/app/main.py` | registro condicional do router |
| `src/mobia/workers/jobs/importar_catalogo.py` | job ARQ |
| `src/mobia/workers/main.py` | `+ importar_catalogo` em `functions` |
| `alembic/versions/0016_catalogo_de_imoveis.py` | as duas tabelas |
| `data/seed/imoveis.csv` | base simulada, ≥500 imóveis |
| `tests/conftest.py` | `+ "imoveis"`, `"importacoes"` em `TABELAS` |

---

### Task 1: Enums e schemas puros

Fundação sem I/O. Tudo que vem depois importa daqui.

**Files:**
- Create: `src/mobia/domain/catalogo/__init__.py` (vazio)
- Create: `src/mobia/domain/catalogo/enums.py`
- Create: `src/mobia/domain/catalogo/schemas.py`
- Test: `tests/unit/test_catalogo_relatorio.py`

**Interfaces:**
- Consumes: nada
- Produces: `TipoImovel`, `Operacao`, `Zona`, `StatusImovel`, `StatusImportacao`, `OrigemImportacao` (todos `StrEnum`); `Rejeicao(linha: int, motivo: str)`; `RegistroImovel` (frozen dataclass, campos listados abaixo); `Relatorio` com `processados/inseridos/atualizados/inalterados/rejeitados: int` e `erros: list[Rejeicao]`, mais `Relatorio.fecha() -> bool`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_catalogo_relatorio.py`:

```python
"""Os cinco totais do relatorio, e a identidade que os fecha.

TEC-156, RN-08.5 e a emenda E-01 dela. O cenario 3 do Gherkin reimporta 500
imoveis com 10 precos alterados e exige que 10 aparecam como atualizados --
nao 500. Isso obriga `atualizados` a significar "mudou de valor", e obriga um
quinto total para as 490 que casaram e nao mudaram. Ver D3 do desenho.
"""

from mobia.domain.catalogo.schemas import Rejeicao, Relatorio


def test_relatorio_comeca_zerado():
    r = Relatorio()
    assert (r.processados, r.inseridos, r.atualizados, r.inalterados, r.rejeitados) == (
        0,
        0,
        0,
        0,
        0,
    )
    assert r.erros == []


def test_os_quatro_totais_do_srs_continuam_existindo():
    # A card e o SRS cobram estes quatro nomes. O quinto os acompanha, nao os
    # substitui -- se algum destes sumir, o contrato publicado quebrou.
    r = Relatorio()
    for nome in ("processados", "inseridos", "atualizados", "rejeitados"):
        assert hasattr(r, nome)


def test_cenario_3_do_gherkin_fecha():
    """500 reimportados, 10 precos alterados: 0 novos, 10 atualizados, 490 iguais."""
    r = Relatorio(
        processados=500, inseridos=0, atualizados=10, inalterados=490, rejeitados=0
    )
    assert r.fecha()


def test_cenario_1_do_gherkin_fecha():
    """500 linhas, 3 invalidas: 497 gravados e 3 rejeitados."""
    r = Relatorio(
        processados=500,
        inseridos=497,
        atualizados=0,
        inalterados=0,
        rejeitados=3,
        erros=[Rejeicao(linha=12, motivo="preco_venda ausente")],
    )
    assert r.fecha()


def test_total_que_nao_fecha_e_detectado():
    # Sem o quinto total, este era exatamente o estado do cenario 3: quatro
    # numeros que nao somam e 490 linhas sem explicacao.
    r = Relatorio(processados=500, inseridos=0, atualizados=10, inalterados=0, rejeitados=0)
    assert not r.fecha()


def test_registrar_rejeicao_incrementa_os_dois_contadores():
    r = Relatorio()
    r.registrar_rejeicao(Rejeicao(linha=7, motivo="tipo invalido: 'apto'"))
    assert r.rejeitados == 1
    assert r.processados == 1
    assert r.erros[0].linha == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_catalogo_relatorio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.catalogo'`

- [ ] **Step 3: Write the enums**

`src/mobia/domain/catalogo/__init__.py`: arquivo vazio.

`src/mobia/domain/catalogo/enums.py`:

```python
"""Os dominios enumerados do catalogo.

`StrEnum` sobre coluna `String(n)`, e nao `ENUM` do Postgres: nao existe um
unico tipo ENUM neste repositorio -- `MessageRole`, `MessageDirection`,
`MessageContentType` e a `temperatura` de `followups` seguem todos este molde.
O SRS diz "enum" na tabela Imovel; seguir a letra dele faria desta a unica
tabela cujo dominio so muda por ALTER TYPE em migration. Ver D10 do desenho.
"""

from enum import StrEnum


class TipoImovel(StrEnum):
    APARTAMENTO = "APARTAMENTO"
    CASA = "CASA"
    COBERTURA = "COBERTURA"
    TERRENO = "TERRENO"
    COMERCIAL = "COMERCIAL"


class Operacao(StrEnum):
    VENDA = "VENDA"
    ALUGUEL = "ALUGUEL"
    AMBOS = "AMBOS"


class Zona(StrEnum):
    NORTE = "NORTE"
    SUL = "SUL"
    LESTE = "LESTE"
    OESTE = "OESTE"
    CENTRO = "CENTRO"


class StatusImovel(StrEnum):
    DISPONIVEL = "DISPONIVEL"
    RESERVADO = "RESERVADO"
    VENDIDO = "VENDIDO"
    ALUGADO = "ALUGADO"
    INATIVO = "INATIVO"


class StatusImportacao(StrEnum):
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDO = "CONCLUIDO"
    # Reservado ao que o lote NAO absorve: arquivo ilegivel, cabecalho
    # ausente, JSON malformado. Linha ruim nunca chega aqui -- ela vira
    # Rejeicao e o lote segue, que e a RN-08.5 inteira.
    FALHOU = "FALHOU"


class OrigemImportacao(StrEnum):
    CLI = "CLI"
    HTTP = "HTTP"
```

- [ ] **Step 4: Write the schemas**

`src/mobia/domain/catalogo/schemas.py`:

```python
"""As tres formas puras da importacao: o registro, a rejeicao e o relatorio.

Sem I/O, sem banco, sem FastAPI. O parser produz `RegistroImovel | Rejeicao`
e o orquestrador acumula os dois num `Relatorio`.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona


@dataclass(frozen=True, slots=True)
class Rejeicao:
    """Uma linha recusada, com TODOS os motivos dela juntos.

    Um motivo por linha, e nao um por problema: linha com tres campos ruins
    devolve uma Rejeicao com os tres motivos separados por "; ". Um relatorio
    que revela um erro por vez faz o admin corrigir e reimportar tres vezes
    para uma linha so, e o valor desta card e a rodada unica. Ver D7.
    """

    linha: int
    motivo: str


@dataclass(frozen=True, slots=True)
class RegistroImovel:
    """Uma linha valida, ja convertida aos tipos do banco.

    `linha` viaja junto ate o fim: quando o upsert falhar, o relatorio ainda
    precisa dizer QUAL linha do arquivo era.

    Precos ja em centavos -- a conversao de reais acontece no parser, na
    borda, com Decimal. Ver D6.
    """

    linha: int
    codigo: str
    titulo: str
    descricao: str
    tipo: TipoImovel
    operacao: Operacao
    preco_venda: int | None
    preco_aluguel: int | None
    condominio: int | None
    iptu_mensal: int | None
    bairro: str
    cidade: str
    uf: str
    zona: Zona | None
    latitude: Decimal | None
    longitude: Decimal | None
    area_util_m2: int
    quartos: int
    suites: int
    banheiros: int
    vagas: int
    caracteristicas: tuple[str, ...]
    fotos: tuple[str, ...]
    status: StatusImovel


@dataclass
class Relatorio:
    """Os cinco totais e a lista de rejeicoes.

    `inalterados` e a emenda E-01 da RN-08.5. Sem ele o cenario 3 do Gherkin
    devolve 500/0/10/0 e 490 linhas ficam sem categoria -- silencio sobre 98%
    do lote, num artefato cujo proposito e "saber exatamente o que falhou".
    Ver D3.
    """

    processados: int = 0
    inseridos: int = 0
    atualizados: int = 0
    inalterados: int = 0
    rejeitados: int = 0
    erros: list[Rejeicao] = field(default_factory=list)

    def fecha(self) -> bool:
        """A identidade que o quinto total existe para tornar verdadeira."""
        return self.processados == (
            self.inseridos + self.atualizados + self.inalterados + self.rejeitados
        )

    def registrar_rejeicao(self, rejeicao: Rejeicao) -> None:
        self.rejeitados += 1
        self.processados += 1
        self.erros.append(rejeicao)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_catalogo_relatorio.py -v`
Expected: PASS, 6 passed

- [ ] **Step 6: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. Se `ruff format --check` reprovar, rode `ruff format src tests alembic evals` e confira o diff antes de seguir.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/catalogo/ tests/unit/test_catalogo_relatorio.py
git commit -m "feat(TEC-156): o relatorio de importacao tem cinco totais, e eles fecham"
```

---

### Task 2: Parser de CSV e JSON

O coração da card. Puro, testável em memória, sem banco.

**Files:**
- Create: `src/mobia/domain/catalogo/parser.py`
- Test: `tests/unit/test_catalogo_parser.py`

**Interfaces:**
- Consumes: `RegistroImovel`, `Rejeicao` (Task 1); os enums (Task 1)
- Produces: `parsear(conteudo: bytes, *, nome_arquivo: str) -> Iterator[RegistroImovel | Rejeicao]`; `ArquivoInvalido(Exception)`; constantes `PRECO_MINIMO_EM_CENTAVOS = 100_000` e `PRECO_MAXIMO_EM_CENTAVOS = 50_000_000_000`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_catalogo_parser.py`:

```python
"""O parser do arquivo de catalogo: o que vira registro e o que vira rejeicao.

TEC-156, RN-08.1 e RN-08.5. Estrito no conteudo, tolerante so na forma --
codificacao e delimitador. Ver D5, D6 e D7 do desenho.
"""

import json
from decimal import Decimal

import pytest

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona
from mobia.domain.catalogo.parser import ArquivoInvalido, parsear
from mobia.domain.catalogo.schemas import Rejeicao, RegistroImovel

CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)

LINHA_BOA = (
    "AP-1042,Apartamento com varanda,Vista para o mar e varanda gourmet,"
    "APARTAMENTO,VENDA,580000.00,,850.00,320.00,Centro,Florianopolis,SC,CENTRO,"
    "-27.595377,-48.548050,74,2,1,2,1,varanda gourmet|pet friendly,"
    "https://ex.com/1.jpg|https://ex.com/2.jpg,DISPONIVEL"
)


def _csv(*linhas: str) -> bytes:
    return ("\n".join((CABECALHO, *linhas)) + "\n").encode("utf-8")


def _so(resultado):
    itens = list(resultado)
    assert len(itens) == 1, itens
    return itens[0]


def test_linha_completa_vira_registro():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"
    assert r.tipo is TipoImovel.APARTAMENTO
    assert r.operacao is Operacao.VENDA
    assert r.zona is Zona.CENTRO
    assert r.status is StatusImovel.DISPONIVEL
    assert r.area_util_m2 == 74


def test_preco_em_reais_vira_centavos():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.preco_venda == 58_000_000
    assert r.condominio == 85_000
    assert r.iptu_mensal == 32_000
    assert r.preco_aluguel is None


def test_latitude_e_longitude_sao_decimal_e_nao_float():
    # Coordenada em float acumula erro na ida e volta ao Numeric(9,6).
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.latitude == Decimal("-27.595377")
    assert isinstance(r.longitude, Decimal)


def test_arrays_separados_por_barra_vertical():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.caracteristicas == ("varanda gourmet", "pet friendly")
    assert len(r.fotos) == 2


def test_array_vazio_vira_tupla_vazia_e_nao_none():
    linha = LINHA_BOA.replace("varanda gourmet|pet friendly", "")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert r.caracteristicas == ()


def test_a_primeira_linha_de_dados_e_a_linha_2():
    # Numeracao fisica do arquivo: o cabecalho e 1. O numero tem que bater com
    # o que o editor mostra quando o admin for corrigir.
    linha_ruim = LINHA_BOA.replace("APARTAMENTO", "apto")
    r = _so(parsear(_csv(linha_ruim), nome_arquivo="base.csv"))
    assert r.linha == 2


def test_enum_em_minuscula_e_rejeicao_e_nao_normalizacao():
    linha = LINHA_BOA.replace("APARTAMENTO", "apartamento")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "tipo" in r.motivo


def test_uma_rejeicao_por_linha_com_todos_os_motivos():
    linha = LINHA_BOA.replace("APARTAMENTO", "apto").replace(",74,2,", ",74,dois,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "tipo" in r.motivo
    assert "quartos" in r.motivo
    assert r.motivo.count(";") == 1


def test_sem_nenhum_preco_e_rejeicao():
    linha = LINHA_BOA.replace(",580000.00,,", ",,,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "preco" in r.motivo


def test_preco_abaixo_da_faixa_e_rejeitado():
    # Quem digitou "580000" achando que eram centavos grava R$ 5.800 sem
    # sintoma nenhum. A guarda existe para esse erro. Ver D6.
    linha = LINHA_BOA.replace("580000.00", "500.00")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "implausivel" in r.motivo


def test_preco_acima_da_faixa_e_rejeitado():
    linha = LINHA_BOA.replace("580000.00", "900000000.00")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "implausivel" in r.motivo


def test_bom_do_excel_nao_derruba_o_cabecalho():
    # Sem utf-8-sig a primeira coluna vira "\ufeffcodigo" (BOM colado no nome) e TODA linha e
    # rejeitada por "codigo ausente" -- 500 rejeicoes com motivo enganoso.
    conteudo = b"\xef\xbb\xbf" + _csv(LINHA_BOA)
    r = _so(parsear(conteudo, nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"


def test_delimitador_ponto_e_virgula_do_excel_pt_br():
    conteudo = (CABECALHO.replace(",", ";") + "\n" + LINHA_BOA.replace(",", ";") + "\n")
    r = _so(parsear(conteudo.encode("utf-8"), nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"


def test_codigo_repetido_no_mesmo_arquivo_e_rejeitado_na_segunda():
    itens = list(parsear(_csv(LINHA_BOA, LINHA_BOA), nome_arquivo="base.csv"))
    assert isinstance(itens[0], RegistroImovel)
    assert isinstance(itens[1], Rejeicao)
    assert "linha 2" in itens[1].motivo


def test_coluna_obrigatoria_ausente_no_cabecalho_derruba_o_arquivo():
    # Isto NAO e rejeicao de linha: sem a coluna, toda linha estaria errada
    # pelo mesmo motivo, e o admin precisa saber que o arquivo esta errado.
    cabecalho_torto = CABECALHO.replace("codigo,", "")
    with pytest.raises(ArquivoInvalido, match="codigo"):
        list(parsear((cabecalho_torto + "\n").encode("utf-8"), nome_arquivo="base.csv"))


def test_json_lista_de_objetos():
    dados = [
        {
            "codigo": "CA-7",
            "titulo": "Casa no centro",
            "descricao": "Casa com quintal",
            "tipo": "CASA",
            "operacao": "VENDA",
            "preco_venda": "750000.00",
            "bairro": "Centro",
            "cidade": "Florianopolis",
            "uf": "SC",
            "area_util_m2": "120",
            "quartos": "3",
            "suites": "1",
            "banheiros": "2",
            "vagas": "2",
            "status": "DISPONIVEL",
        }
    ]
    r = _so(parsear(json.dumps(dados).encode("utf-8"), nome_arquivo="base.json"))
    assert isinstance(r, RegistroImovel)
    assert r.preco_venda == 75_000_000
    # No JSON a "linha" e o indice 1-based do elemento: nao ha linha fisica.
    assert r.linha == 1


def test_json_malformado_derruba_o_arquivo():
    with pytest.raises(ArquivoInvalido):
        list(parsear(b"{nao e json", nome_arquivo="base.json"))


def test_extensao_desconhecida_derruba_o_arquivo():
    with pytest.raises(ArquivoInvalido, match="extensao"):
        list(parsear(b"qualquer coisa", nome_arquivo="base.xlsx"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_catalogo_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.catalogo.parser'`

- [ ] **Step 3: Write the parser**

`src/mobia/domain/catalogo/parser.py`:

```python
"""Le CSV ou JSON e devolve registro valido ou rejeicao, linha a linha.

TEC-156, RN-08.1 e RN-08.5. Puro: sem sessao, sem banco, sem ARQ, sem
Settings. E aqui que mora quase toda a densidade da card, e a pureza e o que
torna os casos testaveis sem subir Postgres -- a suite deste repo e lenta e os
testes de integracao flakeiam sob carga.

**Estrito no conteudo, tolerante so na forma.** Coluna ausente, enum em
minuscula e inteiro que nao parseia sao rejeicao; nada e normalizado. O motivo
nao e purismo: normalizar entrada num arquivo e adivinhar, e adivinhar errado
grava um imovel com dado falso sem deixar rastro. A card pede o oposto --
um relatorio que diz o que falhou. Ver D5.

As duas tolerancias sao sobre CONSEGUIR LER a celula, nunca sobre o que ha
dentro dela: `utf-8-sig` (Excel exporta BOM) e delimitador `,` ou `;` (Excel
pt-BR exporta `;`). Sem a primeira, toda linha e rejeitada por "codigo
ausente"; sem a segunda, o arquivo inteiro vira uma coluna so. Nos dois casos
o sintoma nao aponta para a causa.

**`ArquivoInvalido` e a fronteira.** Ela e levantada pelo que o lote nao
absorve -- arquivo ilegivel, cabecalho sem coluna obrigatoria, JSON
malformado, extensao desconhecida. Nenhum desses e "uma linha", entao nenhum
cabe no relatorio por linha. Linha ruim NUNCA levanta.
"""

import csv
import io
import json
from collections.abc import Iterator
from decimal import Decimal, DecimalException

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona
from mobia.domain.catalogo.schemas import Rejeicao, RegistroImovel

# R$ 1.000 e R$ 500.000.000, em centavos. A faixa e larga o bastante para nao
# recusar imovel legitimo e estreita o bastante para o erro de unidade cair
# fora dela na grande maioria dos casos: quem digita centavos num campo de
# reais produz um numero mil vezes maior. Nao e guarda perfeita -- e a
# diferenca entre um erro que grita e um erro que nao deixa rastro. Ver D6.
PRECO_MINIMO_EM_CENTAVOS = 100_000
PRECO_MAXIMO_EM_CENTAVOS = 50_000_000_000

_OBRIGATORIAS = (
    "codigo",
    "titulo",
    "descricao",
    "tipo",
    "operacao",
    "bairro",
    "cidade",
    "uf",
    "area_util_m2",
    "quartos",
    "suites",
    "banheiros",
    "vagas",
    "status",
)

_SEPARADOR_DE_ARRAY = "|"


class ArquivoInvalido(Exception):
    """O arquivo inteiro nao pode ser processado. Nao confundir com Rejeicao."""


def parsear(conteudo: bytes, *, nome_arquivo: str) -> Iterator[RegistroImovel | Rejeicao]:
    nome = nome_arquivo.lower()
    if nome.endswith(".csv"):
        yield from _parsear_csv(conteudo)
    elif nome.endswith(".json"):
        yield from _parsear_json(conteudo)
    else:
        raise ArquivoInvalido(
            f"extensao nao suportada em {nome_arquivo!r}; use .csv ou .json"
        )


def _decodificar(conteudo: bytes) -> str:
    # utf-8-sig come o BOM quando ele existe e e identico a utf-8 quando nao.
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        raise ArquivoInvalido(f"arquivo nao e UTF-8 valido: {erro}") from erro


def _delimitador(cabecalho: str) -> str:
    # Escolha entre os dois unicos candidatos, pelo que aparece mais no
    # cabecalho. Nao usamos csv.Sniffer: ele adivinha entre muitos candidatos e
    # erra com campo que contem virgula.
    return ";" if cabecalho.count(";") > cabecalho.count(",") else ","


def _parsear_csv(conteudo: bytes) -> Iterator[RegistroImovel | Rejeicao]:
    texto = _decodificar(conteudo)
    primeira = texto.split("\n", 1)[0]
    leitor = csv.DictReader(io.StringIO(texto), delimiter=_delimitador(primeira))

    colunas = set(leitor.fieldnames or ())
    faltando = [c for c in _OBRIGATORIAS if c not in colunas]
    if faltando:
        raise ArquivoInvalido(f"cabecalho sem coluna obrigatoria: {', '.join(faltando)}")

    vistos: dict[str, int] = {}
    # O cabecalho e a linha 1, entao o primeiro registro e a linha 2. O numero
    # tem que bater com o que o editor mostra para quem for corrigir.
    for numero, bruto in enumerate(leitor, start=2):
        yield _converter({k: (v or "") for k, v in bruto.items()}, numero, vistos)


def _parsear_json(conteudo: bytes) -> Iterator[RegistroImovel | Rejeicao]:
    texto = _decodificar(conteudo)
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise ArquivoInvalido(f"JSON malformado: {erro}") from erro

    if not isinstance(dados, list):
        raise ArquivoInvalido("JSON precisa ser uma lista de objetos, sem envelope")

    vistos: dict[str, int] = {}
    # Sem linha fisica correspondente: aqui "linha" e o indice 1-based do
    # elemento, e o relatorio declara qual convencao esta em uso.
    for indice, item in enumerate(dados, start=1):
        if not isinstance(item, dict):
            yield Rejeicao(linha=indice, motivo="elemento nao e um objeto")
            continue
        yield _converter({k: str(v) if v is not None else "" for k, v in item.items()}, indice, vistos)


def _converter(
    bruto: dict[str, str], linha: int, vistos: dict[str, int]
) -> RegistroImovel | Rejeicao:
    """Converte uma linha, acumulando TODOS os motivos antes de decidir.

    Acumular e nao devolver no primeiro erro: linha com tres campos ruins
    devolve um motivo com os tres, e o admin corrige tudo numa rodada. Ver D7.
    """
    motivos: list[str] = []

    def texto(campo: str, *, obrigatorio: bool = True) -> str:
        valor = bruto.get(campo, "").strip()
        if obrigatorio and not valor:
            motivos.append(f"{campo} ausente")
        return valor

    def inteiro(campo: str, *, obrigatorio: bool = True) -> int | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return None
        try:
            return int(valor)
        except ValueError:
            motivos.append(f"{campo} nao e inteiro: {valor!r}")
            return None

    def enumerado(campo: str, classe, *, obrigatorio: bool = True):
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return None
        try:
            return classe(valor)
        except ValueError:
            motivos.append(f"{campo} invalido: {valor!r}")
            return None

    def preco(campo: str) -> int | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return None
        try:
            centavos = int((Decimal(valor) * 100).to_integral_value())
        except (DecimalException, ArithmeticError, ValueError):
            motivos.append(f"{campo} nao e um valor em reais: {valor!r}")
            return None
        if not PRECO_MINIMO_EM_CENTAVOS <= centavos <= PRECO_MAXIMO_EM_CENTAVOS:
            motivos.append(
                f"{campo} implausivel: {valor!r} -- esperado entre "
                f"{PRECO_MINIMO_EM_CENTAVOS // 100} e "
                f"{PRECO_MAXIMO_EM_CENTAVOS // 100} reais"
            )
            return None
        return centavos

    def coordenada(campo: str) -> Decimal | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return None
        try:
            return Decimal(valor)
        except DecimalException:
            motivos.append(f"{campo} nao e uma coordenada: {valor!r}")
            return None

    def lista(campo: str) -> tuple[str, ...]:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return ()
        return tuple(p.strip() for p in valor.split(_SEPARADOR_DE_ARRAY) if p.strip())

    codigo = texto("codigo")
    if codigo and codigo in vistos:
        motivos.append(f"codigo {codigo!r} repetido no arquivo (ja apareceu na linha {vistos[codigo]})")

    titulo = texto("titulo")
    descricao = texto("descricao")
    tipo = enumerado("tipo", TipoImovel)
    operacao = enumerado("operacao", Operacao)
    preco_venda = preco("preco_venda")
    preco_aluguel = preco("preco_aluguel")
    condominio = preco("condominio")
    iptu_mensal = preco("iptu_mensal")
    bairro = texto("bairro")
    cidade = texto("cidade")
    uf = texto("uf")
    zona = enumerado("zona", Zona, obrigatorio=False)
    latitude = coordenada("latitude")
    longitude = coordenada("longitude")
    area = inteiro("area_util_m2")
    quartos = inteiro("quartos")
    suites = inteiro("suites")
    banheiros = inteiro("banheiros")
    vagas = inteiro("vagas")
    status = enumerado("status", StatusImovel)

    # Espelha o CHECK da tabela. So checa quando nenhum dos dois campos ja
    # gerou motivo proprio -- senao "preco implausivel" viria acompanhado de
    # "ao menos um preco" e o segundo confundiria em vez de informar.
    if (
        preco_venda is None
        and preco_aluguel is None
        and not any(m.startswith(("preco_venda", "preco_aluguel")) for m in motivos)
    ):
        motivos.append("ao menos um preco e obrigatorio (preco_venda ou preco_aluguel)")

    if motivos:
        return Rejeicao(linha=linha, motivo="; ".join(motivos))

    # Registrado so depois de a linha passar: uma linha rejeitada nao "reserva"
    # o codigo, senao a linha boa seguinte com o mesmo codigo seria recusada
    # por causa de uma linha que nem entrou.
    vistos[codigo] = linha

    assert tipo is not None and operacao is not None and status is not None
    assert area is not None and quartos is not None and suites is not None
    assert banheiros is not None and vagas is not None
    return RegistroImovel(
        linha=linha,
        codigo=codigo,
        titulo=titulo,
        descricao=descricao,
        tipo=tipo,
        operacao=operacao,
        preco_venda=preco_venda,
        preco_aluguel=preco_aluguel,
        condominio=condominio,
        iptu_mensal=iptu_mensal,
        bairro=bairro,
        cidade=cidade,
        uf=uf,
        zona=zona,
        latitude=latitude,
        longitude=longitude,
        area_util_m2=area,
        quartos=quartos,
        suites=suites,
        banheiros=banheiros,
        vagas=vagas,
        caracteristicas=lista("caracteristicas"),
        fotos=lista("fotos"),
        status=status,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_catalogo_parser.py -v`
Expected: PASS, 18 passed

Se `test_uma_rejeicao_por_linha_com_todos_os_motivos` falhar contando `;`, confira se o `replace` do teste realmente alterou o campo `quartos` e não outro — a string `",74,2,"` aparece uma vez só em `LINHA_BOA`.

- [ ] **Step 5: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

O mypy vai reclamar de `enumerado` sem anotação de retorno se `strict` estiver ligado. Se reclamar, anote como `-> TipoImovel | Operacao | Zona | StatusImovel | None` não resolve bem; use `TypeVar`:

```python
from typing import TypeVar

_E = TypeVar("_E", TipoImovel, Operacao, Zona, StatusImovel)

def enumerado(campo: str, classe: type[_E], *, obrigatorio: bool = True) -> _E | None:
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/catalogo/parser.py tests/unit/test_catalogo_parser.py
git commit -m "feat(TEC-156): linha ruim vira rejeicao com todos os motivos, e o lote segue"
```

---

### Task 3: Migration, models e limpeza entre testes

**Files:**
- Create: `alembic/versions/0016_catalogo_de_imoveis.py`
- Create: `src/mobia/domain/catalogo/models.py`
- Modify: `tests/conftest.py` — acrescentar `"imoveis"` e `"importacoes"` a `TABELAS`
- Test: `tests/integration/test_catalogo_upsert.py` (só o smoke desta tarefa; o resto entra na Task 4)

**Interfaces:**
- Consumes: `Base` de `mobia.domain.messages.models`; os enums (Task 1)
- Produces: `Imovel` (`__tablename__ = "imoveis"`), `Importacao` (`__tablename__ = "importacoes"`), revision `0016` com `down_revision = "0015"`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_catalogo_upsert.py` (só o primeiro teste por enquanto):

```python
"""O upsert do catalogo por codigo, e os cinco totais que ele produz.

TEC-156. Integracao de verdade: as migrations rodam pela fixture de sessao.
"""

from sqlalchemy import text


async def test_as_duas_tabelas_existem_depois_da_migration(session):
    for tabela in ("imoveis", "importacoes"):
        assert await session.scalar(text(f"SELECT to_regclass('public.{tabela}')"))


async def test_codigo_e_unico(session):
    from mobia.domain.catalogo.models import Imovel

    session.add(_imovel("AP-1"))
    await session.commit()
    session.add(_imovel("AP-1"))
    try:
        await session.commit()
    except Exception:
        await session.rollback()
    else:
        raise AssertionError("UNIQUE (codigo) nao impediu o duplicado")
    assert Imovel is not None


def _imovel(codigo: str):
    import uuid

    from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
    from mobia.domain.catalogo.models import Imovel

    return Imovel(
        id=uuid.uuid4(),
        codigo=codigo,
        titulo="Apartamento",
        descricao="Descricao",
        tipo=TipoImovel.APARTAMENTO,
        operacao=Operacao.VENDA,
        preco_venda=58_000_000,
        bairro="Centro",
        cidade="Florianopolis",
        uf="SC",
        area_util_m2=74,
        quartos=2,
        suites=1,
        banheiros=2,
        vagas=1,
        caracteristicas=[],
        fotos=[],
        status=StatusImovel.DISPONIVEL,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v`
Expected: FAIL — `to_regclass` devolve `None`, e `ModuleNotFoundError` para `models`.

Se aparecerem centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`, o Postgres ainda está subindo. Espere e retente — não é bug de código.

- [ ] **Step 3: Write the migration**

`alembic/versions/0016_catalogo_de_imoveis.py`:

```python
"""o catalogo de imoveis e a trilha de importacoes

TEC-156, RF-08. A raiz do epico do catalogo: sem estas duas tabelas nao ha
o que recomendar.

**Sem `embedding` nem `embedding_atualizado_em`.** Nao e so escopo da card: a
imagem do compose e `postgres:16-alpine`, que nao tem pgvector, entao criar a
coluna hoje exigiria trocar a imagem -- infra que pertence a TEC-157, junto
com a extensao e o indice IVFFlat. Colunas nulas agora antecipariam a troca
sem antecipar nada que a use.

**Sem tipo ENUM.** Nenhuma tabela deste banco usa ENUM do Postgres; o dominio
mora em `StrEnum` sobre `String(n)`. Seguir o SRS ao pe da letra faria desta a
unica tabela cujo dominio so muda por ALTER TYPE.

**O UNIQUE em `codigo` e a chave do upsert**, e nao decoracao. E ele que
impede o duplicado do cenario 3 do Gherkin mesmo com dois lotes correndo
juntos -- a classificacao inserido/atualizado e feita em Python, fora de
transacao unica, entao a exclusao precisa morar na restricao. Mesmo
raciocinio do UNIQUE da 0015.

**Os bytes do arquivo ficam em `importacoes.arquivo`.** Passar 10 MB pelo
payload do ARQ transformaria a fila em armazenamento; gravar em disco exigiria
volume compartilhado entre API e worker, que o compose nao tem. Reler o
arquivo exato que gerou um relatorio e o que torna o relatorio auditavel.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "imoveis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("codigo", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(160), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("operacao", sa.String(8), nullable=False),
        sa.Column("preco_venda", sa.BigInteger(), nullable=True),
        sa.Column("preco_aluguel", sa.BigInteger(), nullable=True),
        sa.Column("condominio", sa.BigInteger(), nullable=True),
        sa.Column("iptu_mensal", sa.BigInteger(), nullable=True),
        sa.Column("bairro", sa.String(120), nullable=False),
        sa.Column("cidade", sa.String(120), nullable=False),
        sa.Column("uf", sa.String(2), nullable=False),
        sa.Column("zona", sa.String(8), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("area_util_m2", sa.Integer(), nullable=False),
        sa.Column("quartos", sa.SmallInteger(), nullable=False),
        sa.Column("suites", sa.SmallInteger(), nullable=False),
        sa.Column("banheiros", sa.SmallInteger(), nullable=False),
        sa.Column("vagas", sa.SmallInteger(), nullable=False),
        sa.Column(
            "caracteristicas",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "fotos",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "preco_venda IS NOT NULL OR preco_aluguel IS NOT NULL",
            name="ck_imoveis_ao_menos_um_preco",
        ),
        sa.UniqueConstraint("codigo", name="uq_imoveis_codigo"),
    )
    # A busca da TEC-158 filtra por bairro e cidade antes da similaridade;
    # o indice existe desde ja porque o SRS marca as duas como indexadas.
    op.create_index("ix_imoveis_bairro", "imoveis", ["bairro"])
    op.create_index("ix_imoveis_cidade", "imoveis", ["cidade"])
    op.create_index("ix_imoveis_status", "imoveis", ["status"])

    op.create_table(
        "importacoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("origem", sa.String(8), nullable=False),
        sa.Column("nome_arquivo", sa.String(255), nullable=False),
        sa.Column("arquivo", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("processados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inseridos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inalterados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejeitados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "erros",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "criada_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("concluida_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("importacoes")
    op.drop_index("ix_imoveis_status", table_name="imoveis")
    op.drop_index("ix_imoveis_cidade", table_name="imoveis")
    op.drop_index("ix_imoveis_bairro", table_name="imoveis")
    op.drop_table("imoveis")
```

- [ ] **Step 4: Write the models**

`src/mobia/domain/catalogo/models.py`:

```python
"""As duas tabelas do catalogo: o imovel e a trilha de importacao.

TEC-156. `Base` vem de `messages.models` -- e o unico `DeclarativeBase` deste
projeto, e um segundo faria o Alembic enxergar dois metadados.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # A chave do upsert, e o que o corretor le e dita ao telefone. Unico por
    # restricao, e nao por convencao: a classificacao inserido/atualizado roda
    # em Python, fora de transacao unica, entao a exclusao mora aqui.
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)

    titulo: Mapped[str] = mapped_column(String(160), nullable=False)

    # Fonte do embedding na TEC-157. E por mudanca NESTE campo (e nos outros
    # textuais) que a RN-08.3 manda regerar; preco e status nao regeram.
    descricao: Mapped[str] = mapped_column(Text, nullable=False)

    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    operacao: Mapped[str] = mapped_column(String(8), nullable=False)

    # Centavos, como todo dinheiro deste banco. O arquivo carrega reais e a
    # conversao acontece no parser; ver D6 do desenho.
    preco_venda: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    preco_aluguel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    condominio: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iptu_mensal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    bairro: Mapped[str] = mapped_column(String(120), nullable=False)
    cidade: Mapped[str] = mapped_column(String(120), nullable=False)
    uf: Mapped[str] = mapped_column(String(2), nullable=False)
    zona: Mapped[str | None] = mapped_column(String(8), nullable=True)

    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    area_util_m2: Mapped[int] = mapped_column(Integer, nullable=False)
    quartos: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    suites: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    banheiros: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vagas: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Lista vazia, nunca NULL: o consumidor nao deve precisar distinguir "sem
    # caracteristicas" de "nao informado", e o parser ja normaliza para ().
    caracteristicas: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    fotos: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    status: Mapped[str] = mapped_column(String(12), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    # NAO e tocado quando a reimportacao nao muda nada. Bumpar o carimbo numa
    # linha inalterada faria a coluna mentir sobre quando o imovel mudou pela
    # ultima vez -- e e ela que um humano consulta para responder isso.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint(
            "preco_venda IS NOT NULL OR preco_aluguel IS NOT NULL",
            name="ck_imoveis_ao_menos_um_preco",
        ),
        UniqueConstraint("codigo", name="uq_imoveis_codigo"),
        Index("ix_imoveis_bairro", "bairro"),
        Index("ix_imoveis_cidade", "cidade"),
        Index("ix_imoveis_status", "status"),
    )


class Importacao(Base):
    """O relatorio duravel. E ele, e nao a tabela de imoveis, o produto da card.

    A historia pede "saber exatamente o que falhou, para corrigir as linhas
    ruins sem reimportar tudo as cegas": a tabela de imoveis nao guarda o que
    NAO entrou, e esta guarda.
    """

    __tablename__ = "importacoes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    origem: Mapped[str] = mapped_column(String(8), nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)

    # Os bytes exatos que geraram este relatorio. Sem eles, "a linha 12 foi
    # rejeitada por X" nao e verificavel depois. Ver D9 do desenho.
    arquivo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    status: Mapped[str] = mapped_column(String(12), nullable=False)

    processados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    inseridos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    atualizados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # A emenda E-01 da RN-08.5. Sem esta coluna os quatro totais nao somam no
    # cenario 3 do Gherkin, e 490 linhas ficam sem categoria.
    inalterados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rejeitados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # JSONB e nao tabela filha: a lista so e lida inteira, junto com o resto do
    # relatorio. Nao ha consulta por motivo nem por linha que justifique o JOIN.
    erros: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    concluida_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 5: Add the tables to the truncate list**

Em `tests/conftest.py`, dentro de `TABELAS`, antes de `"messages"`:

```python
    # As duas do catalogo (TEC-156). `imoveis` precisa entrar porque o UNIQUE
    # em `codigo` faz o imovel de um teste colidir com o do proximo; sem o
    # truncate a falha aparece so a partir do segundo teste do arquivo.
    "importacoes",
    "imoveis",
```

`importacoes` antes de `imoveis` não importa aqui (não há FK entre elas), mas mantém a lista lendo do mais derivado para o mais base, como o resto dela.

- [ ] **Step 6: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v
```
Expected: PASS, 2 passed

- [ ] **Step 7: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/0016_catalogo_de_imoveis.py src/mobia/domain/catalogo/models.py tests/conftest.py tests/integration/test_catalogo_upsert.py
git commit -m "feat(TEC-156): o catalogo tem tabela, e o codigo do imovel e unico"
```

---

### Task 4: Upsert por código com diff campo a campo

**Files:**
- Create: `src/mobia/domain/catalogo/repositorio.py`
- Modify: `tests/integration/test_catalogo_upsert.py` — acrescentar os testes dos cenários 1 e 3

**Interfaces:**
- Consumes: `RegistroImovel` (Task 1), `Imovel` (Task 3)
- Produces: `async def sincronizar(session: AsyncSession, registros: Sequence[RegistroImovel]) -> tuple[int, int, int]` devolvendo `(inseridos, atualizados, inalterados)`; constante `CAMPOS_COMPARADOS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_catalogo_upsert.py`:

```python
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.repositorio import sincronizar
from mobia.domain.catalogo.schemas import RegistroImovel


def _registro(codigo: str, linha: int = 2, preco: int = 58_000_000) -> RegistroImovel:
    return RegistroImovel(
        linha=linha,
        codigo=codigo,
        titulo="Apartamento com varanda",
        descricao="Vista para o mar",
        tipo=TipoImovel.APARTAMENTO,
        operacao=Operacao.VENDA,
        preco_venda=preco,
        preco_aluguel=None,
        condominio=85_000,
        iptu_mensal=32_000,
        bairro="Centro",
        cidade="Florianopolis",
        uf="SC",
        zona=None,
        latitude=Decimal("-27.595377"),
        longitude=Decimal("-48.548050"),
        area_util_m2=74,
        quartos=2,
        suites=1,
        banheiros=2,
        vagas=1,
        caracteristicas=("varanda gourmet",),
        fotos=(),
        status=StatusImovel.DISPONIVEL,
    )


async def test_primeira_carga_insere_tudo(session):
    inseridos, atualizados, inalterados = await sincronizar(
        session, [_registro(f"AP-{i}", linha=i + 2) for i in range(10)]
    )
    await session.commit()
    assert (inseridos, atualizados, inalterados) == (10, 0, 0)
    assert len((await session.scalars(select(Imovel))).all()) == 10


async def test_reimportacao_identica_nao_atualiza_nada(session):
    registros = [_registro(f"AP-{i}", linha=i + 2) for i in range(10)]
    await sincronizar(session, registros)
    await session.commit()

    inseridos, atualizados, inalterados = await sincronizar(session, registros)
    await session.commit()
    assert (inseridos, atualizados, inalterados) == (0, 0, 10)


async def test_cenario_3_do_gherkin(session):
    """500 ja importados, 10 precos alterados: 0 novos, 10 atualizados, 490 iguais."""
    registros = [_registro(f"AP-{i}", linha=i + 2) for i in range(500)]
    await sincronizar(session, registros)
    await session.commit()

    alterados = [
        replace(r, preco_venda=r.preco_venda + 1_000_00) if i < 10 else r
        for i, r in enumerate(registros)
    ]
    inseridos, atualizados, inalterados = await sincronizar(session, alterados)
    await session.commit()

    assert (inseridos, atualizados, inalterados) == (0, 10, 490)
    assert len((await session.scalars(select(Imovel))).all()) == 500


async def test_inalterado_nao_tem_updated_at_tocado(session):
    registros = [_registro("AP-1")]
    await sincronizar(session, registros)
    await session.commit()
    antes = (await session.scalars(select(Imovel))).one().updated_at

    session.expire_all()
    await sincronizar(session, registros)
    await session.commit()
    depois = (await session.scalars(select(Imovel))).one().updated_at

    assert antes == depois


async def test_atualizado_tem_updated_at_movido(session):
    await sincronizar(session, [_registro("AP-1")])
    await session.commit()
    antes = (await session.scalars(select(Imovel))).one().updated_at

    session.expire_all()
    await sincronizar(session, [_registro("AP-1", preco=59_000_000)])
    await session.commit()
    depois = (await session.scalars(select(Imovel))).one().updated_at

    assert depois > antes


async def test_lote_maior_que_500_e_processado_inteiro(session):
    inseridos, _, _ = await sincronizar(
        session, [_registro(f"AP-{i}", linha=i + 2) for i in range(1200)]
    )
    await session.commit()
    assert inseridos == 1200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.catalogo.repositorio'`

- [ ] **Step 3: Write the repository**

`src/mobia/domain/catalogo/repositorio.py`:

```python
"""Upsert do catalogo por `codigo`, com diff campo a campo.

TEC-156. Devolve os tres numeros que o relatorio precisa distinguir:
inseridos, atualizados e inalterados.

**Por que o diff e em Python e nao um ON CONFLICT esperto.** Da para resolver
tudo numa instrucao:

    INSERT ... ON CONFLICT (codigo) DO UPDATE SET ...
      WHERE imoveis IS DISTINCT FROM EXCLUDED
      RETURNING (xmax = 0) AS inserido

E mais rapido, e perde exatamente a informacao que a proxima card precisa. A
RN-08.3 manda regerar embedding quando campo TEXTUAL muda e nao quando so o
preco muda; `IS DISTINCT FROM` responde apenas SE mudou, nunca O QUE mudou.
A TEC-157 teria que reconstruir este diff do zero. Com lotes de 500 as duas
abordagens sao instantaneas; a diferenca esta em qual deixa o gancho. Ver D4.

**A corrida, dita em voz alta.** Entre o SELECT e o INSERT, outro lote pode
inserir o mesmo codigo. O INSERT leva ON CONFLICT DO UPDATE para nao levantar,
e a linha acaba contada como inserida quando de fato foi atualizada. Fica
assim de proposito: a alternativa seria SELECT ... FOR UPDATE sobre codigos
que ainda nao existem, que nao tranca nada. Duas importacoes simultaneas do
mesmo catalogo sao operacao anomala, a integridade continua garantida pelo
UNIQUE, e so a rotulagem de uma linha rara sai imprecisa.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import RegistroImovel

TAMANHO_DO_LOTE = 500

# Os campos que o arquivo carrega -- e portanto os unicos que a comparacao
# pode olhar. `id`, `created_at` e `updated_at` sao do banco e nunca vem do
# arquivo; incluir qualquer um deles faria toda linha parecer alterada.
CAMPOS_COMPARADOS: tuple[str, ...] = (
    "titulo",
    "descricao",
    "tipo",
    "operacao",
    "preco_venda",
    "preco_aluguel",
    "condominio",
    "iptu_mensal",
    "bairro",
    "cidade",
    "uf",
    "zona",
    "latitude",
    "longitude",
    "area_util_m2",
    "quartos",
    "suites",
    "banheiros",
    "vagas",
    "caracteristicas",
    "fotos",
    "status",
)


def _valores(registro: RegistroImovel) -> dict[str, object]:
    """O registro do arquivo no formato de coluna.

    Enums viram `str` (a coluna e String) e tuplas viram `list` (a coluna e
    ARRAY): sem essa normalizacao a comparacao com o que voltou do banco
    acusaria diferenca em toda linha, e tudo apareceria como atualizado.
    """
    valores: dict[str, object] = {}
    for campo in CAMPOS_COMPARADOS:
        valor = getattr(registro, campo)
        if isinstance(valor, tuple):
            valor = list(valor)
        elif valor is not None and hasattr(valor, "value"):
            valor = str(valor)
        valores[campo] = valor
    return valores


def _mudou(existente: Imovel, valores: dict[str, object]) -> bool:
    return any(getattr(existente, campo) != valores[campo] for campo in CAMPOS_COMPARADOS)


async def sincronizar(
    session: AsyncSession, registros: Sequence[RegistroImovel]
) -> tuple[int, int, int]:
    """Devolve (inseridos, atualizados, inalterados). Nao comita."""
    inseridos = atualizados = inalterados = 0

    for comeco in range(0, len(registros), TAMANHO_DO_LOTE):
        lote = registros[comeco : comeco + TAMANHO_DO_LOTE]
        codigos = [r.codigo for r in lote]

        existentes = {
            imovel.codigo: imovel
            for imovel in (
                await session.scalars(select(Imovel).where(Imovel.codigo.in_(codigos)))
            ).all()
        }

        novos: list[dict[str, object]] = []
        for registro in lote:
            valores = _valores(registro)
            existente = existentes.get(registro.codigo)

            if existente is None:
                novos.append({"id": uuid.uuid4(), "codigo": registro.codigo, **valores})
                inseridos += 1
                continue

            if not _mudou(existente, valores):
                # Nenhuma escrita, nem em `updated_at`. Ver o comentario da
                # coluna em models.py.
                inalterados += 1
                continue

            for campo, valor in valores.items():
                setattr(existente, campo, valor)
            existente.updated_at = _agora()
            atualizados += 1

        if novos:
            # ON CONFLICT DO UPDATE, e nao DO NOTHING: sob a corrida descrita
            # no docstring, DO NOTHING descartaria a linha em silencio e o
            # imovel ficaria com o conteudo do lote concorrente.
            comando = insert(Imovel).values(novos)
            await session.execute(
                comando.on_conflict_do_update(
                    index_elements=["codigo"],
                    set_={campo: comando.excluded[campo] for campo in CAMPOS_COMPARADOS},
                )
            )

        await session.flush()

    return inseridos, atualizados, inalterados


def _agora():
    from datetime import UTC, datetime

    return datetime.now(UTC)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v`
Expected: PASS, 8 passed

Se `test_reimportacao_identica_nao_atualiza_nada` acusar 10 atualizados, o culpado é quase sempre `_valores`: confira que enums viraram `str` e tuplas viraram `list`. `Decimal("-27.595377")` volta do `Numeric(9,6)` como `Decimal` com a mesma escala — se comparar diferente, normalize com `.quantize()`.

- [ ] **Step 5: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/catalogo/repositorio.py tests/integration/test_catalogo_upsert.py
git commit -m "feat(TEC-156): reimportar atualiza o que mudou e deixa o resto intocado"
```

---

### Task 5: Orquestração da importação

Junta parser e repositório, grava o relatório na tabela. É o ponto único que CLI e job chamam.

**Files:**
- Create: `src/mobia/domain/catalogo/importacao.py`
- Test: `tests/integration/test_catalogo_upsert.py` — acrescentar o cenário 1 completo

**Interfaces:**
- Consumes: `parsear`, `ArquivoInvalido` (Task 2); `sincronizar` (Task 4); `Importacao` (Task 3); `Relatorio`, `Rejeicao` (Task 1)
- Produces: `async def registrar(session, *, origem: OrigemImportacao, nome_arquivo: str, conteudo: bytes) -> uuid.UUID`; `async def executar(sessionmaker, *, importacao_id: uuid.UUID) -> Relatorio`

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_catalogo_upsert.py`:

```python
from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.importacao import executar, registrar
from mobia.domain.catalogo.models import Importacao

_CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)


def _linha(codigo: str, preco: str = "580000.00") -> str:
    return (
        f"{codigo},Apartamento,Vista para o mar,APARTAMENTO,VENDA,{preco},,850.00,"
        "320.00,Centro,Florianopolis,SC,CENTRO,-27.595377,-48.548050,74,2,1,2,1,"
        "varanda,,DISPONIVEL"
    )


def _arquivo(linhas: list[str]) -> bytes:
    return ("\n".join([_CABECALHO, *linhas]) + "\n").encode("utf-8")


async def test_cenario_1_do_gherkin(session, session_factory):
    """500 linhas, 3 invalidas: 497 gravados, 3 rejeicoes com linha e motivo."""
    linhas = [_linha(f"AP-{i}") for i in range(497)]
    linhas.insert(10, _linha("AP-X", preco=""))
    linhas.insert(200, _linha("AP-Y").replace("APARTAMENTO", "apto"))
    linhas.insert(400, _linha("AP-Z").replace(",74,", ",setenta,"))

    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=_arquivo(linhas),
    )
    await session.commit()

    relatorio = await executar(session_factory, importacao_id=importacao_id)

    assert relatorio.processados == 500
    assert relatorio.inseridos == 497
    assert relatorio.rejeitados == 3
    assert relatorio.fecha()
    assert {e.linha for e in relatorio.erros} == {12, 202, 402}
    assert all(e.motivo for e in relatorio.erros)


async def test_o_relatorio_fica_gravado_e_consultavel(session, session_factory):
    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.HTTP,
        nome_arquivo="base.csv",
        conteudo=_arquivo([_linha("AP-1")]),
    )
    await session.commit()
    await executar(session_factory, importacao_id=importacao_id)

    session.expire_all()
    gravada = await session.get(Importacao, importacao_id)
    assert gravada is not None
    assert gravada.status == StatusImportacao.CONCLUIDO
    assert gravada.inseridos == 1
    assert gravada.concluida_em is not None


async def test_arquivo_sem_cabecalho_valido_e_falhou_e_nao_rejeicao(
    session, session_factory
):
    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=b"nada,disso,serve\n1,2,3\n",
    )
    await session.commit()
    await executar(session_factory, importacao_id=importacao_id)

    session.expire_all()
    gravada = await session.get(Importacao, importacao_id)
    assert gravada is not None
    assert gravada.status == StatusImportacao.FALHOU
    assert gravada.processados == 0
    # A falha do arquivo inteiro vai para `erros` com linha 0: nao e "uma
    # linha", mas quem le o relatorio precisa do motivo em algum lugar.
    assert gravada.erros and gravada.erros[0]["linha"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -k cenario_1 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.catalogo.importacao'`

- [ ] **Step 3: Write the orchestration**

`src/mobia/domain/catalogo/importacao.py`:

```python
"""Orquestra a importacao: le o arquivo da tabela, parseia, grava, relata.

TEC-156. Este e o ponto unico que as duas entradas chamam -- a CLI direto no
proprio processo, o endpoint HTTP atraves do job ARQ. A diferenca entre elas
esta em QUEM chama e de onde, nunca no que acontece.

**Commit por lote, e nao uma transacao unica.** Se algo estourar na linha 800,
os 500 primeiros imoveis ficam gravados e a `importacoes` registra FALHOU com
os totais parciais REAIS. Um COMMIT no fim desfaria trabalho bom e
transformaria erro tardio em "nada aconteceu" -- que e exatamente o resultado
que a historia da card descarta. A importacao nao e atomica, e isso e a
premissa da RN-08.5 ("registra falhas por linha sem abortar o lote"), nao um
efeito colateral: atomicidade e sucesso parcial sao requisitos opostos.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.models import Importacao
from mobia.domain.catalogo.parser import ArquivoInvalido, parsear
from mobia.domain.catalogo.repositorio import TAMANHO_DO_LOTE, sincronizar
from mobia.domain.catalogo.schemas import Rejeicao, RegistroImovel, Relatorio

log = structlog.get_logger(__name__)


async def registrar(
    session: AsyncSession,
    *,
    origem: OrigemImportacao,
    nome_arquivo: str,
    conteudo: bytes,
) -> uuid.UUID:
    """Cria a linha PROCESSANDO com os bytes, e devolve o id.

    A linha existe desde o POST -- e por isso que consultar antes de o job
    terminar devolve 200 com status PROCESSANDO, e nao 404.
    """
    importacao = Importacao(
        id=uuid.uuid4(),
        origem=str(origem),
        nome_arquivo=nome_arquivo,
        arquivo=conteudo,
        status=str(StatusImportacao.PROCESSANDO),
    )
    session.add(importacao)
    await session.flush()
    return importacao.id


async def executar(
    sessionmaker: async_sessionmaker[AsyncSession], *, importacao_id: uuid.UUID
) -> Relatorio:
    async with sessionmaker() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            raise LookupError(f"importacao {importacao_id} nao existe")
        conteudo = importacao.arquivo
        nome_arquivo = importacao.nome_arquivo

    relatorio = Relatorio()

    try:
        itens = list(parsear(conteudo, nome_arquivo=nome_arquivo))
    except ArquivoInvalido as erro:
        # Nao e "uma linha": o arquivo inteiro nao pode ser processado. Linha 0
        # porque o relatorio precisa carregar o motivo em algum lugar, e
        # nenhuma linha real tem esse numero.
        await _concluir(
            sessionmaker,
            importacao_id,
            relatorio,
            status=StatusImportacao.FALHOU,
            falha=Rejeicao(linha=0, motivo=str(erro)),
        )
        log.warning("catalogo.importacao_falhou", importacao_id=str(importacao_id), motivo=str(erro))
        return relatorio

    validos: list[RegistroImovel] = []
    for item in itens:
        if isinstance(item, Rejeicao):
            relatorio.registrar_rejeicao(item)
        else:
            validos.append(item)

    try:
        # Este laco fatia de novo o que `sincronizar` ja fatia internamente, e
        # a redundancia e intencional -- nao simplifique. Os dois cortes tem
        # propositos diferentes: o de dentro limita o tamanho do `IN (...)` do
        # SELECT, o daqui define a FRONTEIRA DE COMMIT. Chamar `sincronizar`
        # uma vez com a lista inteira gravaria tudo numa transacao so, e uma
        # falha na linha 800 desfaria os 500 primeiros imoveis -- exatamente o
        # "nada aconteceu" que a RN-08.5 recusa.
        for comeco in range(0, len(validos), TAMANHO_DO_LOTE):
            lote = validos[comeco : comeco + TAMANHO_DO_LOTE]
            async with sessionmaker() as session:
                inseridos, atualizados, inalterados = await sincronizar(session, lote)
                await session.commit()
            relatorio.inseridos += inseridos
            relatorio.atualizados += atualizados
            relatorio.inalterados += inalterados
            relatorio.processados += len(lote)
    except Exception as erro:  # noqa: BLE001 -- ver docstring do modulo
        # Os lotes ja comitados ficam. O relatorio guarda os totais parciais
        # reais, que e mais util que "nada aconteceu".
        await _concluir(
            sessionmaker,
            importacao_id,
            relatorio,
            status=StatusImportacao.FALHOU,
            falha=Rejeicao(linha=0, motivo=f"falha durante a gravacao: {erro}"),
        )
        log.exception("catalogo.importacao_interrompida", importacao_id=str(importacao_id))
        return relatorio

    await _concluir(
        sessionmaker, importacao_id, relatorio, status=StatusImportacao.CONCLUIDO
    )
    log.info(
        "catalogo.importacao_concluida",
        importacao_id=str(importacao_id),
        processados=relatorio.processados,
        inseridos=relatorio.inseridos,
        atualizados=relatorio.atualizados,
        inalterados=relatorio.inalterados,
        rejeitados=relatorio.rejeitados,
    )
    return relatorio


async def _concluir(
    sessionmaker: async_sessionmaker[AsyncSession],
    importacao_id: uuid.UUID,
    relatorio: Relatorio,
    *,
    status: StatusImportacao,
    falha: Rejeicao | None = None,
) -> None:
    erros: Sequence[Rejeicao] = relatorio.erros if falha is None else [falha, *relatorio.erros]
    async with sessionmaker() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            return
        importacao.status = str(status)
        importacao.processados = relatorio.processados
        importacao.inseridos = relatorio.inseridos
        importacao.atualizados = relatorio.atualizados
        importacao.inalterados = relatorio.inalterados
        importacao.rejeitados = relatorio.rejeitados
        importacao.erros = [{"linha": e.linha, "motivo": e.motivo} for e in erros]
        importacao.concluida_em = datetime.now(UTC)
        await session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/catalogo/importacao.py tests/integration/test_catalogo_upsert.py
git commit -m "feat(TEC-156): a importacao grava um relatorio consultavel com os cinco totais"
```

---

### Task 6: A base simulada de 500 imóveis

**Files:**
- Create: `data/seed/imoveis.csv`
- Create: `scripts/gerar_base_simulada.py` (descartável — ver Step 1)
- Test: `tests/unit/test_base_simulada.py`

**Interfaces:**
- Consumes: `parsear` (Task 2)
- Produces: `data/seed/imoveis.csv` com ≥500 linhas de dados

- [ ] **Step 1: Write the failing test**

`tests/unit/test_base_simulada.py`:

```python
"""A base simulada que acompanha a POC atravessa o parser sem rejeicao.

TEC-156, RN-08.1 e o quarto cenario Gherkin. Puro: le o arquivo do repo e
passa pelo parser, sem banco. O ponto e que o seed exercita EXATAMENTE o mesmo
caminho da importacao real -- se o formato do arquivo divergir do parser, este
teste quebra antes de qualquer um notar em producao. Ver D8 do desenho.
"""

from collections import Counter
from pathlib import Path

from mobia.domain.catalogo.parser import parsear
from mobia.domain.catalogo.schemas import Rejeicao, RegistroImovel

ARQUIVO = Path(__file__).resolve().parents[2] / "data" / "seed" / "imoveis.csv"


def _itens():
    return list(parsear(ARQUIVO.read_bytes(), nome_arquivo=ARQUIVO.name))


def test_o_arquivo_existe():
    assert ARQUIVO.is_file(), f"seed ausente em {ARQUIVO}"


def test_tem_pelo_menos_500_imoveis():
    assert len(_itens()) >= 500


def test_nenhuma_linha_e_rejeitada():
    rejeitadas = [i for i in _itens() if isinstance(i, Rejeicao)]
    assert rejeitadas == [], [(r.linha, r.motivo) for r in rejeitadas[:5]]


def test_codigos_sao_unicos():
    registros = [i for i in _itens() if isinstance(i, RegistroImovel)]
    codigos = Counter(r.codigo for r in registros)
    assert [c for c, n in codigos.items() if n > 1] == []


def test_distribuicao_e_realista():
    """A RN-08.1 pede distribuicao realista de bairros, precos e tipologias.

    "Realista" nao e verificavel por assercao; o que da para exigir e que a
    base nao seja degenerada -- um unico bairro ou um unico tipo tornaria a
    demo de busca inutil e a TEC-158 nao teria o que filtrar.
    """
    registros = [i for i in _itens() if isinstance(i, RegistroImovel)]
    assert len({r.bairro for r in registros}) >= 8
    assert len({r.tipo for r in registros}) >= 4
    precos = [r.preco_venda for r in registros if r.preco_venda]
    assert max(precos) >= 3 * min(precos)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_base_simulada.py -v`
Expected: FAIL — `seed ausente em .../data/seed/imoveis.csv`

- [ ] **Step 3: Generate the file**

`scripts/gerar_base_simulada.py` gera o CSV **uma vez**. Ele é ferramenta de autoria, não parte do produto: fica fora de `src/`, portanto fora do mypy, e não é importado por nada.

```python
"""Gera data/seed/imoveis.csv. Rodado uma vez; o produto e o CSV, nao este script.

Determinista (`Random(20260906)`) para que regerar produza o mesmo arquivo e o
diff mostre so o que mudou de proposito.
"""

import csv
import random
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[1] / "data" / "seed" / "imoveis.csv"

BAIRROS = [
    ("Centro", "CENTRO", 1.00),
    ("Agronomica", "CENTRO", 1.10),
    ("Trindade", "CENTRO", 0.95),
    ("Itacorubi", "NORTE", 0.90),
    ("Coqueiros", "SUL", 0.85),
    ("Campeche", "SUL", 0.80),
    ("Jurere", "NORTE", 1.60),
    ("Canasvieiras", "NORTE", 0.75),
    ("Lagoa da Conceicao", "LESTE", 1.25),
    ("Santo Antonio de Lisboa", "NORTE", 1.15),
    ("Estreito", "OESTE", 0.70),
    ("Balneario", "OESTE", 0.78),
]

TIPOS = [
    ("APARTAMENTO", "AP", 0.55, (45, 180), (1, 4)),
    ("CASA", "CA", 0.25, (90, 320), (2, 5)),
    ("COBERTURA", "CO", 0.08, (120, 400), (2, 4)),
    ("TERRENO", "TE", 0.07, (200, 900), (0, 0)),
    ("COMERCIAL", "CM", 0.05, (30, 400), (0, 0)),
]

CARACTERISTICAS = [
    "varanda gourmet",
    "pet friendly",
    "piscina",
    "academia",
    "churrasqueira",
    "vista mar",
    "mobiliado",
    "portaria 24h",
    "sacada",
    "energia solar",
]

CABECALHO = [
    "codigo", "titulo", "descricao", "tipo", "operacao", "preco_venda",
    "preco_aluguel", "condominio", "iptu_mensal", "bairro", "cidade", "uf",
    "zona", "latitude", "longitude", "area_util_m2", "quartos", "suites",
    "banheiros", "vagas", "caracteristicas", "fotos", "status",
]


def gerar(quantidade: int = 520) -> list[list[str]]:
    rng = random.Random(20260906)
    linhas = []
    for n in range(1, quantidade + 1):
        tipo, prefixo, _, (area_min, area_max), (q_min, q_max) = rng.choices(
            TIPOS, weights=[t[2] for t in TIPOS]
        )[0]
        bairro, zona, fator = rng.choice(BAIRROS)
        area = rng.randint(area_min, area_max)
        quartos = rng.randint(q_min, q_max) if q_max else 0
        suites = rng.randint(0, quartos) if quartos else 0
        banheiros = max(1, quartos)
        vagas = rng.randint(0, 3)

        # Preco por m2 puxado pelo fator do bairro, com ruido de +-15%.
        por_m2 = rng.randint(7000, 14000) * fator * rng.uniform(0.85, 1.15)
        preco_venda = round(area * por_m2, 2)

        operacao = rng.choices(["VENDA", "ALUGUEL", "AMBOS"], weights=[0.72, 0.18, 0.10])[0]
        aluguel = round(preco_venda * rng.uniform(0.0035, 0.0055), 2)

        status = rng.choices(
            ["DISPONIVEL", "RESERVADO", "VENDIDO", "ALUGADO", "INATIVO"],
            weights=[0.80, 0.07, 0.07, 0.04, 0.02],
        )[0]

        caracteristicas = rng.sample(CARACTERISTICAS, rng.randint(0, 4))

        linhas.append([
            f"{prefixo}-{1000 + n}",
            f"{tipo.capitalize()} em {bairro}",
            f"{tipo.capitalize()} de {area} m2 em {bairro}, "
            f"{quartos} quarto(s) e {vagas} vaga(s). "
            + (", ".join(caracteristicas) if caracteristicas else "Sem diferenciais listados")
            + ".",
            tipo,
            operacao,
            f"{preco_venda:.2f}" if operacao in ("VENDA", "AMBOS") else "",
            f"{aluguel:.2f}" if operacao in ("ALUGUEL", "AMBOS") else "",
            f"{rng.randint(200, 2500)}.00",
            f"{rng.randint(80, 900)}.00",
            bairro,
            "Florianopolis",
            "SC",
            zona,
            f"{rng.uniform(-27.75, -27.40):.6f}",
            f"{rng.uniform(-48.60, -48.40):.6f}",
            str(area),
            str(quartos),
            str(suites),
            str(banheiros),
            str(vagas),
            "|".join(caracteristicas),
            f"https://exemplo.com/{prefixo.lower()}-{1000 + n}-1.jpg",
            status,
        ])
    return linhas


if __name__ == "__main__":
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with DESTINO.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, lineterminator="\n")
        escritor.writerow(CABECALHO)
        escritor.writerows(gerar())
    print(f"gerado: {DESTINO}")
```

Rode:

```bash
./.venv/Scripts/python.exe scripts/gerar_base_simulada.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_base_simulada.py -v`
Expected: PASS, 5 passed

Se `test_nenhuma_linha_e_rejeitada` falhar, a assertion imprime as cinco primeiras `(linha, motivo)`. As causas prováveis: preço fora da faixa de plausibilidade (ajuste os multiplicadores de `por_m2`), ou `TERRENO`/`COMERCIAL` com `quartos=0` — o parser exige o campo presente, e `0` é valor presente, então isso deve passar; se não passar, confira que o gerador escreveu `"0"` e não `""`.

- [ ] **Step 5: Run the three static gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

`scripts/` está fora do escopo dos três gates de propósito — é ferramenta de autoria, não produto. Se quiser incluí-lo, é decisão de outra card (mudaria o comando do CI).

- [ ] **Step 6: Commit**

```bash
git add data/seed/imoveis.csv scripts/gerar_base_simulada.py tests/unit/test_base_simulada.py
git commit -m "feat(TEC-156): a POC vem com 520 imoveis simulados que passam pelo parser"
```

---

### Task 7: CLI de seed

**Files:**
- Create: `src/mobia/admin/seed_catalogo.py`
- Test: `tests/unit/test_seed_catalogo_cli.py`

**Interfaces:**
- Consumes: `registrar`, `executar` (Task 5); `get_sessionmaker` de `mobia.infra.db`
- Produces: `main(argv: list[str] | None = None) -> int`; `ARQUIVO_PADRAO: Path`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_seed_catalogo_cli.py`:

```python
"""A CLI de seed: argumentos, codigo de saida e o relatorio no stdout.

TEC-156. Testa a casca, nao a importacao -- `_executar` e dublado. A logica de
verdade tem cobertura de integracao em tests/integration/test_catalogo_upsert.py.
"""

import pytest

from mobia.admin import seed_catalogo
from mobia.domain.catalogo.schemas import Rejeicao, Relatorio


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch):
    """Substitui a rotina async por uma que devolve um relatorio pronto."""
    chamadas: list[dict] = []

    def instalar(relatorio: Relatorio) -> list[dict]:
        async def falso(*, arquivo, origem):
            chamadas.append({"arquivo": arquivo, "origem": origem})
            return relatorio

        monkeypatch.setattr(seed_catalogo, "_importar", falso)
        return chamadas

    return instalar


def test_usa_o_arquivo_padrao_quando_nenhum_e_passado(sem_banco, capsys):
    chamadas = sem_banco(Relatorio(processados=520, inseridos=520))
    assert seed_catalogo.main([]) == 0
    assert chamadas[0]["arquivo"] == seed_catalogo.ARQUIVO_PADRAO


def test_imprime_os_cinco_totais(sem_banco, capsys):
    sem_banco(
        Relatorio(processados=500, inseridos=497, atualizados=0, inalterados=0, rejeitados=3)
    )
    seed_catalogo.main([])
    saida = capsys.readouterr().out
    for rotulo in ("processados", "inseridos", "atualizados", "inalterados", "rejeitados"):
        assert rotulo in saida


def test_imprime_linha_e_motivo_de_cada_rejeicao(sem_banco, capsys):
    sem_banco(
        Relatorio(
            processados=2,
            inseridos=1,
            rejeitados=1,
            erros=[Rejeicao(linha=12, motivo="preco_venda ausente")],
        )
    )
    seed_catalogo.main([])
    saida = capsys.readouterr().out
    assert "12" in saida
    assert "preco_venda ausente" in saida


def test_sai_com_zero_mesmo_havendo_rejeicoes(sem_banco):
    # O primeiro cenario Gherkin exige que 3 linhas ruins terminem "com
    # sucesso". Sair diferente de zero aqui reprovaria o criterio de aceite.
    sem_banco(Relatorio(processados=500, inseridos=497, rejeitados=3))
    assert seed_catalogo.main([]) == 0


def test_falhar_se_rejeitar_inverte_o_codigo_de_saida(sem_banco):
    sem_banco(Relatorio(processados=500, inseridos=497, rejeitados=3))
    assert seed_catalogo.main(["--falhar-se-rejeitar"]) == 1


def test_falhar_se_rejeitar_sai_zero_quando_nao_ha_rejeicao(sem_banco):
    sem_banco(Relatorio(processados=500, inseridos=500))
    assert seed_catalogo.main(["--falhar-se-rejeitar"]) == 0


def test_arquivo_inexistente_sai_com_erro(sem_banco, capsys):
    sem_banco(Relatorio())
    assert seed_catalogo.main(["--arquivo", "nao/existe.csv"]) == 2
    assert "nao/existe.csv" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_seed_catalogo_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'seed_catalogo'`

- [ ] **Step 3: Write the CLI**

`src/mobia/admin/seed_catalogo.py`:

```python
"""Carrega o catalogo de imoveis a partir de um arquivo CSV ou JSON.

TEC-156, RN-08.1. Mesmo molde de `admin/reativar.py`: `main` sincrono chamando
`asyncio.run`, e a logica async num `_importar` separado -- um teste async nao
pode chamar `main` de dentro de um loop ja rodando ("cannot be called from a
running event loop").

**Nao enfileira.** Processa no proprio processo, ao contrario do endpoint
HTTP. O quarto cenario Gherkin diz "executado em base vazia", e um seed que
exige Redis e worker no ar nao serve a esse cenario -- nem a quem acabou de
clonar o repositorio. As duas entradas chamam a mesma `importacao.executar`.

**Sai com 0 mesmo havendo rejeicoes.** O primeiro cenario Gherkin exige que
3 linhas ruins terminem "com sucesso": rejeicao e resultado esperado da
RN-08.5, nao falha do processo. `--falhar-se-rejeitar` inverte isso para quem
quiser o seed dentro de um pipeline que deva parar.

Uso:
    python -m mobia.admin.seed_catalogo
    python -m mobia.admin.seed_catalogo --arquivo /caminho/base.csv
    python -m mobia.admin.seed_catalogo --arquivo base.csv --falhar-se-rejeitar
"""

import argparse
import asyncio
import sys
from pathlib import Path

from mobia.domain.catalogo.enums import OrigemImportacao
from mobia.domain.catalogo.importacao import executar, registrar
from mobia.domain.catalogo.schemas import Relatorio
from mobia.infra.db import get_sessionmaker

ARQUIVO_PADRAO = Path(__file__).resolve().parents[3] / "data" / "seed" / "imoveis.csv"


async def _importar(*, arquivo: Path, origem: OrigemImportacao) -> Relatorio:
    """A logica async, separada de `main` para o teste chamar direto."""
    sessionmaker = get_sessionmaker()
    conteudo = arquivo.read_bytes()
    async with sessionmaker() as session:
        importacao_id = await registrar(
            session, origem=origem, nome_arquivo=arquivo.name, conteudo=conteudo
        )
        await session.commit()
    return await executar(sessionmaker, importacao_id=importacao_id)


def _imprimir(relatorio: Relatorio) -> None:
    print(f"processados : {relatorio.processados}")
    print(f"inseridos   : {relatorio.inseridos}")
    print(f"atualizados : {relatorio.atualizados}")
    print(f"inalterados : {relatorio.inalterados}")
    print(f"rejeitados  : {relatorio.rejeitados}")
    if relatorio.erros:
        print("\nrejeicoes:")
        for erro in relatorio.erros:
            print(f"  linha {erro.linha}: {erro.motivo}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carrega o catalogo de imoveis a partir de um arquivo."
    )
    parser.add_argument(
        "--arquivo",
        type=Path,
        default=ARQUIVO_PADRAO,
        help=f"CSV ou JSON a importar (padrao: {ARQUIVO_PADRAO})",
    )
    parser.add_argument(
        "--falhar-se-rejeitar",
        action="store_true",
        help="sai com 1 se houver qualquer rejeicao (para uso em pipeline)",
    )
    args = parser.parse_args(argv)

    if not args.arquivo.is_file():
        print(f"arquivo nao encontrado: {args.arquivo}", file=sys.stderr)
        return 2

    relatorio = asyncio.run(_importar(arquivo=args.arquivo, origem=OrigemImportacao.CLI))
    _imprimir(relatorio)

    if args.falhar_se_rejeitar and relatorio.rejeitados:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_seed_catalogo_cli.py -v`
Expected: PASS, 7 passed

Confira também que `ARQUIVO_PADRAO` aponta para o lugar certo — `parents[3]` a partir de `src/mobia/admin/seed_catalogo.py` é a raiz do repo. Se `test_arquivo_inexistente_sai_com_erro` passar mas `test_usa_o_arquivo_padrao...` falhar, ajuste o índice.

- [ ] **Step 5: Run it for real**

```bash
./.venv/Scripts/python.exe -m mobia.admin.seed_catalogo
```
Expected: `processados : 520`, `inseridos : 520`, `rejeitados : 0`. Rodar de novo deve dar `inalterados : 520`.

- [ ] **Step 6: Run the three static gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/admin/seed_catalogo.py tests/unit/test_seed_catalogo_cli.py
git commit -m "feat(TEC-156): o seed carrega o catalogo sem exigir Redis nem worker"
```

---

### Task 8: Token administrativo, endpoint e registro condicional do router

**Files:**
- Modify: `src/mobia/app/config.py` — `catalogo_admin_token`, `TOKEN_DE_DESENVOLVIMENTO`, guarda de produção
- Modify: `src/mobia/api/deps.py` — `exigir_admin`
- Create: `src/mobia/api/routes/imoveis.py`
- Modify: `src/mobia/app/main.py` — registro condicional
- Modify: `.env.example`
- Test: `tests/integration/test_importacao_http.py`

**Interfaces:**
- Consumes: `registrar` (Task 5); `Importacao` (Task 3)
- Produces: `Settings.catalogo_admin_token: str`; `exigir_admin(x_admin_token: str = Header(...))`; router com `POST /api/v1/imoveis/importar` e `GET /api/v1/imoveis/importacoes/{id}`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_importacao_http.py`:

```python
"""O endpoint administrativo de importacao, e a guarda que o protege.

TEC-156, RN-08.1 e a emenda E-01 da secao 6.3. Ate a TEC-201 a autenticacao e
um token compartilhado; sem token configurado a rota nem e registrada. Ver D1.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app

TOKEN = "token-de-teste-do-catalogo"

CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)
LINHA = (
    "AP-9001,Apartamento,Vista para o mar,APARTAMENTO,VENDA,580000.00,,850.00,"
    "320.00,Centro,Florianopolis,SC,CENTRO,-27.595377,-48.548050,74,2,1,2,1,"
    "varanda,,DISPONIVEL"
)
ARQUIVO = (CABECALHO + "\n" + LINHA + "\n").encode("utf-8")


@pytest.fixture
async def app_com_token(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_post_sem_token_e_403(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar", files={"arquivo": ("base.csv", ARQUIVO, "text/csv")}
    )
    assert resposta.status_code == 403


async def test_post_com_token_errado_e_403(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": "errado"},
    )
    assert resposta.status_code == 403


async def test_post_com_token_devolve_202_e_id(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["status"] == "PROCESSANDO"
    uuid.UUID(corpo["importacaoId"])


async def test_get_devolve_o_relatorio_com_os_cinco_totais(app_com_token):
    criada = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    importacao_id = criada.json()["importacaoId"]

    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}",
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    # Consultar antes de o job rodar devolve 200 com PROCESSANDO -- nao 404,
    # nao 202: a linha existe desde o POST.
    assert corpo["status"] == "PROCESSANDO"
    for chave in ("processados", "inseridos", "atualizados", "inalterados", "rejeitados"):
        assert chave in corpo


async def test_get_de_id_inexistente_e_404(app_com_token):
    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{uuid.uuid4()}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


async def test_sem_token_configurado_a_rota_nao_existe(
    monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool
):
    """404 e nao 403: rota que nao existe nao pode ser exposta por engano.

    Uma rota que responde 401/403 esta registrada e depende de o codigo de
    verificacao estar certo. Esta nao esta la. Ver D1 do desenho.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "")
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/api/v1/imoveis/importar",
            files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
            headers={"X-Admin-Token": TOKEN},
        )
    assert resposta.status_code == 404
    get_settings.cache_clear()


async def test_arquivo_acima_do_teto_e_413(app_com_token):
    grande = b"x" * (10 * 1024 * 1024 + 1)
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", grande, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_importacao_http.py -v`
Expected: FAIL — todas com 404, porque a rota não existe.

- [ ] **Step 3: Add the setting and the production guard**

Em `src/mobia/app/config.py`, junto às outras constantes do topo:

```python
# O default de desenvolvimento, recusado em producao pelo validator abaixo.
# Mesmo molde da CHAVE_DE_DESENVOLVIMENTO.
TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO = "dev-catalogo-token"  # noqa: S105
```

Dentro de `Settings`, perto de `whatsapp_verify_token`:

```python
    # Vazio DESLIGA o endpoint de importacao: o router nem e registrado. Nao e
    # 401 -- rota que nao existe nao pode ser exposta por engano de
    # configuracao, e este projeto ainda nao tem camada de autenticacao (JWT,
    # OIDC e papeis sao a TEC-201). Ver D1 do desenho da TEC-156.
    catalogo_admin_token: str = ""
```

E um validator novo, ao lado dos existentes:

```python
    @model_validator(mode="after")
    def _recusar_token_de_catalogo_de_desenvolvimento_em_producao(self) -> "Settings":
        """O token de dev em producao deixa o catalogo gravavel por quem o leu.

        Ele esta no `.env.example`, versionado: qualquer um que clonou o repo o
        conhece. Diferente da chave de cifra, aqui o estrago nao e silencioso
        -- e por isso a guarda nao precisa existir para o token VAZIO, que
        apenas desliga a rota.
        """
        if (
            self.environment.strip().lower() in _AMBIENTES_DE_PRODUCAO
            and self.catalogo_admin_token == TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO
        ):
            raise ConfiguracaoInsegura(
                "CATALOGO_ADMIN_TOKEN esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere um token: "
                'python -c "import secrets;print(secrets.token_urlsafe(32))"'
            )
        return self
```

Em `.env.example`, acrescentar:

```
# Habilita POST /api/v1/imoveis/importar. Vazio desliga a rota inteira.
CATALOGO_ADMIN_TOKEN=dev-catalogo-token
```

- [ ] **Step 4: Add the dependency**

Em `src/mobia/api/deps.py`:

```python
import secrets

from fastapi import Header, HTTPException, Request, status

from mobia.app.config import get_settings
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker


def get_ingestion_service(request: Request) -> IngestionService:
    return IngestionService(get_sessionmaker(), getattr(request.app.state, "redis_pool", None))


def exigir_admin(x_admin_token: str = Header(default="")) -> None:
    """A autenticacao provisoria do endpoint administrativo (TEC-156, D1).

    `compare_digest` e nao `==`: comparacao de string curto-circuita no
    primeiro byte diferente, e o tempo da resposta revela o prefixo correto.

    Quando a TEC-201 chegar, o corpo desta funcao vira validacao de JWT mais
    papel ADMIN e nenhum handler muda -- e esse o ponto de ter uma funcao aqui
    em vez de um `if` dentro da rota.
    """
    esperado = get_settings().catalogo_admin_token
    if not esperado or not secrets.compare_digest(x_admin_token, esperado):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

- [ ] **Step 5: Write the route**

`src/mobia/api/routes/imoveis.py`:

```python
"""Importacao do catalogo por HTTP (TEC-156, RN-08.1, secao 6.3 do SRS).

Assincrono como o SRS descreve: o POST devolve 202 com o id e enfileira, e o
GET devolve o relatorio. Nao e fidelidade cega -- a TEC-157 acrescenta a
geracao de embedding, que sao ~500 chamadas de API por importacao, e ali o
assincrono deixa de ser escolha. Fazer sincrono agora significaria emendar o
SRS duas vezes em duas cards. Ver D2 do desenho.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from mobia.api.deps import exigir_admin
from mobia.domain.catalogo.enums import OrigemImportacao
from mobia.domain.catalogo.importacao import registrar
from mobia.domain.catalogo.models import Importacao
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/imoveis", tags=["catalogo"])

# ~40 mil imoveis. Acima disso o caminho e a CLI, que nao passa por upload.
TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024


@router.post("/importar", status_code=status.HTTP_202_ACCEPTED)
async def importar(
    request: Request,
    arquivo: UploadFile = File(...),
    _: None = Depends(exigir_admin),
) -> dict[str, str]:
    conteudo = await arquivo.read()
    if len(conteudo) > TETO_DE_UPLOAD_EM_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"arquivo acima de {TETO_DE_UPLOAD_EM_BYTES} bytes; use a CLI de seed",
        )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        importacao_id = await registrar(
            session,
            origem=OrigemImportacao.HTTP,
            nome_arquivo=arquivo.filename or "sem-nome",
            conteudo=conteudo,
        )
        await session.commit()

    pool = getattr(request.app.state, "redis_pool", None)
    if pool is not None:
        await pool.enqueue_job("importar_catalogo", str(importacao_id))

    log.info("catalogo.importacao_enfileirada", importacao_id=str(importacao_id))
    return {"importacaoId": str(importacao_id), "status": "PROCESSANDO"}


@router.get("/importacoes/{importacao_id}")
async def consultar(
    importacao_id: uuid.UUID, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)

    if importacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrada")

    # Enquanto o job nao termina, isto devolve PROCESSANDO com os totais em
    # zero. E o status que o consumidor le, nao o codigo HTTP.
    return {
        "importacaoId": str(importacao.id),
        "status": importacao.status,
        "nomeArquivo": importacao.nome_arquivo,
        "processados": importacao.processados,
        "inseridos": importacao.inseridos,
        "atualizados": importacao.atualizados,
        "inalterados": importacao.inalterados,
        "rejeitados": importacao.rejeitados,
        "erros": importacao.erros,
    }
```

- [ ] **Step 6: Register the router conditionally**

Em `src/mobia/app/main.py`, dentro de `create_app`, depois de `app.include_router(whatsapp_router)`:

```python
    # Sem token configurado o router NAO entra no app. Nao e 401: rota que nao
    # existe nao pode ser exposta por engano de configuracao, e este projeto
    # ainda nao tem camada de autenticacao. Ver D1 do desenho da TEC-156.
    if settings.catalogo_admin_token:
        from mobia.api.routes.imoveis import router as imoveis_router

        app.include_router(imoveis_router)
    else:
        log.warning("catalogo.rota_de_importacao_desligada", motivo="sem CATALOGO_ADMIN_TOKEN")
```

Isso exige um logger no módulo. No topo de `main.py`:

```python
import structlog

log = structlog.get_logger(__name__)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_importacao_http.py -v`
Expected: PASS, 7 passed

Se `test_arquivo_acima_do_teto_e_413` estourar memória ou demorar, reduza `TETO_DE_UPLOAD_EM_BYTES` para um valor configurável e teste com ele menor — mas não mude o teto de produção sem anotar o porquê.

- [ ] **Step 8: Run the three static gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/app/config.py src/mobia/api/deps.py src/mobia/api/routes/imoveis.py src/mobia/app/main.py .env.example tests/integration/test_importacao_http.py
git commit -m "feat(TEC-156): a importacao por HTTP existe, e sem token a rota nao existe"
```

---

### Task 9: Job ARQ

**Files:**
- Create: `src/mobia/workers/jobs/importar_catalogo.py`
- Modify: `src/mobia/workers/main.py` — acrescentar a função à lista `functions`
- Modify: `tests/integration/test_importacao_http.py` — teste de ponta a ponta

**Interfaces:**
- Consumes: `executar` (Task 5)
- Produces: `async def importar_catalogo(ctx: dict, importacao_id: str) -> None`

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_importacao_http.py`:

```python
async def test_o_job_conclui_a_importacao_enfileirada(app_com_token):
    from mobia.workers.jobs.importar_catalogo import importar_catalogo

    criada = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    importacao_id = criada.json()["importacaoId"]

    await importar_catalogo({}, importacao_id)

    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers={"X-Admin-Token": TOKEN}
    )
    corpo = resposta.json()
    assert corpo["status"] == "CONCLUIDO"
    assert corpo["processados"] == 1
    assert corpo["inseridos"] == 1
    assert corpo["rejeitados"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_importacao_http.py -k job -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.workers.jobs.importar_catalogo'`

- [ ] **Step 3: Write the job**

`src/mobia/workers/jobs/importar_catalogo.py`:

```python
"""Job ARQ que processa uma importacao de catalogo ja registrada.

TEC-156. Recebe so o id: os bytes do arquivo moram em `importacoes.arquivo`,
e nao no payload do job. Passar 10 MB pelo Redis a cada importacao
transformaria a fila em armazenamento de arquivo. Ver D9 do desenho.

Casca fina de proposito -- toda a logica esta em `catalogo.importacao.executar`,
que a CLI tambem chama.
"""

import uuid
from typing import Any

import structlog

from mobia.domain.catalogo.importacao import executar
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)


async def importar_catalogo(ctx: dict[str, Any], importacao_id: str) -> None:
    try:
        identificador = uuid.UUID(importacao_id)
    except ValueError:
        log.error("catalogo.job_id_invalido", importacao_id=importacao_id)
        return

    try:
        await executar(get_sessionmaker(), importacao_id=identificador)
    except LookupError:
        # A linha sumiu entre o enqueue e o job. Nao ha o que retentar: sem a
        # linha nao ha nem arquivo nem lugar para gravar o relatorio.
        log.error("catalogo.job_importacao_ausente", importacao_id=importacao_id)
```

- [ ] **Step 4: Register it in the worker**

Em `src/mobia/workers/main.py`, junto dos outros imports de job (linhas 13-15):

```python
from mobia.workers.jobs.importar_catalogo import importar_catalogo
```

E na linha 79, dentro de `class WorkerSettings`, a lista passa de:

```python
    functions = [func(process_message, keep_result=0), sweep_stalled, sweep_followups]
```

para:

```python
    # `importar_catalogo` entra sem `func(..., keep_result=0)`: o resultado do
    # job nao carrega nada -- o relatorio mora em `importacoes`, e e de la que
    # o GET o le. Nao entra em `cron_jobs` tambem: importacao e disparada por
    # quem envia o arquivo, nunca por relogio.
    functions = [
        func(process_message, keep_result=0),
        sweep_stalled,
        sweep_followups,
        importar_catalogo,
    ]
```

Não mexa em `cron_jobs`.

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_importacao_http.py -v`
Expected: PASS, 8 passed

- [ ] **Step 6: Run the three static gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/workers/jobs/importar_catalogo.py src/mobia/workers/main.py tests/integration/test_importacao_http.py
git commit -m "feat(TEC-156): o worker processa a importacao enfileirada pelo endpoint"
```

---

### Task 10: Emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

Sem teste — é documentação. **Prosa em `docs/` leva acento.**

- [ ] **Step 1: Emenda à RN-08.5**

Localize a linha da RN-08.5 (perto da linha 241) e acrescente **logo abaixo dela**, como item aninhado, sem tocar no texto original:

```markdown
  - **Emenda E-01 (TEC-156, 06/09/2026):** o relatório traz **cinco** totais, e não quatro: `processados`, `inseridos`, `atualizados`, `inalterados` e `rejeitados`, com `processados = inseridos + atualizados + inalterados + rejeitados`. O quinto existe porque o critério de aceite CA-08.1 da própria história fixa o significado de `atualizados`: reimportar 500 imóveis com 10 preços alterados deve reportar **10** atualizados, não 500. Isso obriga `atualizados` a contar linhas cujo conteúdo mudou de fato, e não linhas que casaram com um código já existente — e deixa as 490 restantes sem categoria nos quatro totais originais. **Consequência declarada:** um relatório de reimportação sem alterações mostra `processados` igual a `inalterados` e zeros no resto, o que antes era indistinguível de "nada foi processado". A detecção campo a campo que o quinto total exige é a mesma que a RN-08.3 usa para decidir se regera o embedding.
```

- [ ] **Step 2: Emenda à RN-08.1**

Logo abaixo da RN-08.1 (perto da linha 237):

```markdown
  - **Emenda E-01 (TEC-156, 06/09/2026):** o contrato do arquivo, que a regra chama apenas de "CSV/JSON", é: colunas nomeadas em `snake_case` com cabeçalho obrigatório e ordem livre; preços em **reais com decimais** (`580000.00`), convertidos a centavos na borda com `Decimal`, e recusados fora da faixa `[R$ 1.000, R$ 500.000.000]`; `|` como separador de `caracteristicas` e `fotos`; enums em maiúscula exata, sem normalização; leitura em `utf-8-sig`; delimitador `,` ou `;` detectado pelo cabeçalho. JSON é lista de objetos com as mesmas chaves, sem envelope. **Consequência declarada:** valor que não parseia vira rejeição visível, nunca campo vazio — o oposto do módulo de valores monetários da RN-05, que erra por falta porque a entrada dele é fala de lead. As duas tolerâncias (BOM e delimitador) são sobre conseguir ler a célula, nunca sobre o que há dentro dela.
```

- [ ] **Step 3: Emenda à seção 6.3**

Logo abaixo da linha de `POST /api/v1/imoveis/importar` (perto da linha 1034):

```markdown
  - **Emenda E-01 (TEC-156, 06/09/2026):** enquanto a TEC-201 não existir, a autenticação deste endpoint é o header `X-Admin-Token`, comparado em tempo constante com `CATALOGO_ADMIN_TOKEN`; token ausente ou errado devolve `403`. **Com a variável vazia o router não é registrado**, e a rota devolve `404` — rota que não existe não pode ser exposta por engano de configuração, o que uma rota respondendo `401` não garante. `Bearer JWT | Papel: ADMIN` continua sendo o alvo: a TEC-201 troca o corpo da dependência `exigir_admin` e nenhum handler muda. **Consequência declarada:** um segredo compartilhado não tem expiração, rotação nem papel — quem o tem pode reimportar o catálogo inteiro. Aceito porque o objeto é o catálogo de imóveis e não dado pessoal, ao contrário da reativação de opt-out da TEC-182, que por isso ficou sem rota HTTP.
```

- [ ] **Step 4: Verify nothing above was rewritten**

```bash
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md
```
Expected: **apenas linhas adicionadas** (`+`), nenhuma removida ou modificada. Se aparecer qualquer `-`, você reescreveu texto de 22/08/2026 — desfaça.

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-156): a RN-08.5 passa a ter cinco totais, e a RN-08.1 ganha o contrato do arquivo"
```

---

### Task 11: Verificação final

- [ ] **Step 1: Run the full suite**

```bash
./.venv/Scripts/python.exe -m pytest
```

Leva ~7,5 minutos. Saída silenciosa não é deadlock — para ver progresso, use `./.venv/Scripts/python.exe -u -m pytest -v`.

Expected: os 857 testes anteriores mais os novos, todos passando.

- [ ] **Step 2: Isolate any integration failure before diagnosing it**

Se `test_catalogo_upsert.py`, `test_importacao_http.py`, `test_montagem.py`, `test_sweep_stalled.py` ou `test_dedup_por_message_id.py` falharem com `ConnectionResetError` ou erro de Redis, rode o arquivo sozinho antes de atribuir a falha ao seu código:

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_upsert.py -v
```

Passar isolado e falhar junto é flake conhecido de carga neste repo, não regressão.

- [ ] **Step 3: Confirm the collection is not broken**

```bash
./.venv/Scripts/python.exe -m pytest --collect-only -q | tail -5
```

Se a coleta abortar, o suspeito número um é colisão de basename entre `tests/unit/` e `tests/integration/`. Os nomes deste plano são distintos, mas confira se você criou algum arquivo fora dele.

- [ ] **Step 4: Run the three gates one last time**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 5: Verify the prompt budget did not move**

Esta card não toca no prompt, então o teto de 655 não deve ter se mexido. Confirme:

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```
Expected: PASS. Se reprovar, você mexeu em algo que não devia — investigue antes de seguir.

- [ ] **Step 6: Open the PR**

```bash
git push -u origin feat/tec-156-carga-do-catalogo
gh pr create --base main \
  --title "feat(TEC-156): carga do catalogo por arquivo com relatorio de falhas" \
  --body-file - <<'CORPO'
Raiz do épico TEC-155. Entrega as tabelas `imoveis` e `importacoes`, o parser
estrito de CSV/JSON, o upsert por `codigo` e as duas entradas de carga.

Desenho: `docs/superpowers/specs/2026-09-06-tec-156-carga-do-catalogo-design.md`

## Critérios de aceite

| cenário Gherkin | onde é testado |
|---|---|
| Importar lote com linhas inválidas sem abortar | `tests/integration/test_catalogo_upsert.py::test_cenario_1_do_gherkin` |
| Relatório traz os totais | `tests/unit/test_catalogo_relatorio.py` |
| Reimportação atualiza em vez de duplicar | `tests/integration/test_catalogo_upsert.py::test_cenario_3_do_gherkin` |
| Base simulada atende o volume mínimo | `tests/unit/test_base_simulada.py` |

## Emendas ao SRS

- RN-08.5 → E-01: quinto total `inalterados`, porque o CA-08.1 exige que
  "atualizado" signifique mudou-de-valor.
- RN-08.1 → E-01: o contrato do arquivo (colunas, preço em reais, `|`,
  `utf-8-sig`, delimitador).
- Seção 6.3 → E-01: `X-Admin-Token` até a TEC-201; sem token a rota não é
  registrada.

## Lacunas declaradas

Seis, na seção "Lacunas declaradas" do desenho. As duas que mais pesam:
a autenticação é mais fraca que a especificada até a TEC-201, e a rotulagem
inserido/atualizado sai imprecisa sob importação concorrente (a integridade
não sai — o `UNIQUE` a garante).

## Fora de escopo

Embedding e pgvector (TEC-157), CRUD de imóvel (TEC-197), busca (TEC-158).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
CORPO
```
