# Extração de critérios de qualificação — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o que o lead diz virar estado estruturado em `lead_qualification`, extraído no mesmo turno em que o agente responde.

**Architecture:** A extração viaja dentro do `json_schema` da chamada que o turno já faz — nenhuma chamada nova, nenhuma tool. O parse é tolerante (campo ruim é descartado, o turno segue), e a gravação entra no bloco de sessão que já grava a intenção, no mesmo commit.

**Tech Stack:** Python 3.13, SQLAlchemy async (`pg_insert` + `on_conflict_do_update`), Anthropic SDK (`output_config.format` + `transform_schema`), pytest com `asyncio_mode = "auto"`, Postgres.

**Spec:** `docs/superpowers/specs/2026-08-28-tec-145-extracao-de-qualificacao-design.md`

## Global Constraints

- **`null` não apaga.** Só campo com valor não-nulo é escrito. `null` é "o lead não falou disso neste turno", nunca "esqueça o que sabia".
- **Extração nunca levanta `RespostaInvalida`.** Valor malformado vira descarte com log. A resposta ao lead vem da mesma chamada e não pode morrer por causa de um número ruim.
- **Anulabilidade no schema é `anyOf`, nunca `type` em lista.** `transform_schema` declara `SupportedTypes` como `Literal` de tipos únicos e encerra em `assert_never`; `{"type": ["string","null"]}` quebraria no import de `classificador.py`.
- **Nenhuma tool é introduzida.** `_chamar` continua recusando todo `stop_reason` diferente de `end_turn`.
- **`intencao` nunca é extraída.** Vem do classificador, no mesmo turno.
- **`gravar_estado` não commita.** A sessão é emprestada; quem chama é dono da fronteira da transação, como `gravar_resumo` e `ler_estado`.
- **Código Python em ASCII** (identificadores, strings e comentários). A convenção não é aplicada por ferramenta neste repo — 6 arquivos `.py` pré-existentes têm acentos, nenhum em `src/`. Siga-a de todo modo; YAML de corpus é dado e pode ter acento.
- **NÃO rode `pytest evals`.** São chamadas pagas ao provedor. Autorização é do dono do repositório.
- **Sempre capture o exit code do pytest explicitamente.** `pytest -q | tail` mascara falha: o exit code passa a ser o do `tail`. Use `python -m pytest -q > saida.txt 2>&1; echo "EXIT=$?"`.
- **Postgres local:** container `mobia-postgres-1`, porta 5433. As fixtures `autouse` de `tests/conftest.py` (`migrar_banco`, `banco_limpo`) exigem banco de pé para qualquer teste sob `tests/`.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefa |
|---|---|---|
| `src/mobia/domain/agente/schemas.py` | Modificar: três `StrEnum` de vocabulário, `Extracao`, campo em `RespostaDoAgente` | 1 |
| `tests/conftest.py` | Modificar: `ClassificadorFake` passa a devolver `extracao` controlável | 1 |
| `tests/unit/test_extracao.py` | Criar: vocabulário, `Extracao`, guardas | 1, 2 |
| `src/mobia/domain/agente/classificador.py` | Modificar: `SCHEMA_DA_EXTRACAO`, `_extrair` com guardas, integração no parse | 2 |
| `tests/unit/test_classificador.py` | Modificar: schema novo, parse tolerante | 2 |
| `src/mobia/domain/context/repositorio.py` | Modificar: `gravar_estado` | 3 |
| `src/mobia/domain/agente/turno.py` | Modificar: chamada no bloco de sessão existente | 3 |
| `tests/integration/test_repositorio_contexto.py` | Modificar: upsert, `null` não apaga, `FORA_DE_ESCOPO` | 3 |
| `tests/integration/test_extracao_no_turno.py` | Criar: os cenários Gherkin e a saída bloqueada | 3 |
| `src/mobia/evals/corpus.py` | Modificar: `TurnoAnotado.campos` e validação | 4 |
| `src/mobia/evals/metricas.py` | Modificar: `faixa_de` parametrizada, `ExtracaoObservada`, `precisao_da_extracao` | 4 |
| `tests/unit/test_evals_metricas.py` | Modificar: a métrica nova pelos dois lados | 4 |
| `tests/unit/test_evals_corpus_real.py` | Modificar: piso de turnos anotados | 5 |
| `src/mobia/evals/contexto.py` | Modificar: `contexto_do_historico` aceita `estado` | 5 |
| `evals/corpus/*.yaml` | Modificar: anotar `campos` nos turnos | 5 |
| `evals/test_acuracia_de_intencao.py` | Modificar: acumular estado, medir extração e o proxy | 5 |
| `README.md` | Modificar: declarar o proxy e as lacunas | 5 |

---

### Task 1: Vocabulário e contrato de extração

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py`
- Modify: `src/mobia/domain/agente/classificador.py:187` (stub, substituido na Tarefa 2)
- Modify: `tests/conftest.py:121-157` (`ClassificadorFake`)
- Test: `tests/unit/test_extracao.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `TipoImovel`, `Urgencia`, `FormaPagamento` (`StrEnum`); `Extracao` (frozen dataclass, nove campos anuláveis com default `None`, métodos `vazia() -> bool` e `preenchidos() -> dict[str, object]`); `RespostaDoAgente.extracao: Extracao` (campo obrigatório, último da dataclass). `ClassificadorFake(extracao=...)` aceita uma `Extracao`.

**Contexto que o brief não sabe:** `RespostaDoAgente` é construída em exatamente **dois** lugares no repositório — `src/mobia/domain/agente/classificador.py:187` e `tests/conftest.py:148`. Esta tarefa atualiza **os dois**: o campo é obrigatório e sem default, então deixar o primeiro de fora faria o `mypy src` do Step 5 desta própria tarefa falhar. No de produção entra um stub `extracao=Extracao()`, que a Tarefa 2 substitui por `extrair(dados.get("extracao"))` — e é o teste de integração dela que prova a substituição, porque nenhum teste desta tarefa pega um stub esquecido.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_extracao.py`:

```python
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    TipoImovel,
    Urgencia,
)


def test_vocabulario_de_tipo_de_imovel():
    assert [membro.value for membro in TipoImovel] == [
        "APARTAMENTO",
        "CASA",
        "TERRENO",
        "COMERCIAL",
        "RURAL",
    ]


def test_vocabulario_de_urgencia():
    assert [membro.value for membro in Urgencia] == [
        "IMEDIATA",
        "ATE_3_MESES",
        "ATE_6_MESES",
        "SEM_PRESSA",
    ]


def test_vocabulario_de_forma_de_pagamento():
    assert [membro.value for membro in FormaPagamento] == [
        "A_VISTA",
        "FINANCIAMENTO",
        "CONSORCIO",
        "FGTS",
        "INDEFINIDA",
    ]


def test_extracao_sem_argumento_e_toda_none():
    vazia = Extracao()
    assert vazia.vazia() is True
    assert vazia.preenchidos() == {}


def test_preenchidos_devolve_so_os_campos_com_valor():
    extracao = Extracao(quartos=2, regiao="zona sul")
    assert extracao.vazia() is False
    assert extracao.preenchidos() == {"quartos": 2, "regiao": "zona sul"}


def test_preenchidos_nao_esconde_falso_nem_zero():
    """`if valor` descartaria `False` e `0`; a regra e `is not None`.

    Um lead que diz "nao tenho imovel pra vender" informou algo, e "sem vaga"
    e um criterio de busca tao real quanto "duas vagas".
    """
    extracao = Extracao(tem_imovel_para_vender=False, vagas=0)
    assert extracao.preenchidos() == {"tem_imovel_para_vender": False, "vagas": 0}


def test_extracao_e_imutavel():
    extracao = Extracao(quartos=2)
    with pytest.raises(FrozenInstanceError):
        extracao.quartos = 3  # type: ignore[misc]


def test_preco_guarda_precisao_de_decimal():
    extracao = Extracao(faixa_preco_max=Decimal("600000.00"))
    assert extracao.preenchidos() == {"faixa_preco_max": Decimal("600000.00")}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_extracao.py -v > /tmp/t1.txt 2>&1; echo "EXIT=$?"; tail -20 /tmp/t1.txt`

Expected: FAIL na coleta — `ImportError: cannot import name 'Extracao'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/agente/schemas.py`, troque o import do topo e acrescente depois de `Intencao`:

```python
from dataclasses import dataclass, fields
```

```python
class TipoImovel(StrEnum):
    """Vocabulario fechado porque a coluna e filtrada em SQL pela TEC-158.

    `lead_qualification.tipo_imovel` e `String(32)`: texto livre ali envenena
    o filtro estruturado. Acrescentar membro aqui muda o conjunto de valores
    que o modelo pode devolver, como no `Intencao`.
    """

    APARTAMENTO = "APARTAMENTO"
    CASA = "CASA"
    TERRENO = "TERRENO"
    COMERCIAL = "COMERCIAL"
    RURAL = "RURAL"


class Urgencia(StrEnum):
    """Faixas, nao datas. O lead diz "em janeiro"; o que importa e a pressa."""

    IMEDIATA = "IMEDIATA"
    ATE_3_MESES = "ATE_3_MESES"
    ATE_6_MESES = "ATE_6_MESES"
    SEM_PRESSA = "SEM_PRESSA"


class FormaPagamento(StrEnum):
    A_VISTA = "A_VISTA"
    FINANCIAMENTO = "FINANCIAMENTO"
    CONSORCIO = "CONSORCIO"
    FGTS = "FGTS"
    INDEFINIDA = "INDEFINIDA"


@dataclass(frozen=True)
class Extracao:
    """O que o lead disse sobre o que procura, neste turno.

    Todos os campos sao anulaveis, e `None` tem um significado exato: **o lead
    nao falou disso neste turno**. Nunca "esqueca o que sabia". `gravar_estado`
    depende dessa leitura -- ver `preenchidos`.

    Nao tem `intencao` de proposito: quem classifica intencao e o
    classificador, e duas fontes para o mesmo fato divergiriam. Nao tem
    telemetria porque a extracao viaja na chamada de `RespostaDoAgente`, que ja
    carrega a dela.
    """

    faixa_preco_min: Decimal | None = None
    faixa_preco_max: Decimal | None = None
    regiao: str | None = None
    tipo_imovel: TipoImovel | None = None
    quartos: int | None = None
    vagas: int | None = None
    urgencia: Urgencia | None = None
    forma_pagamento: FormaPagamento | None = None
    tem_imovel_para_vender: bool | None = None

    def preenchidos(self) -> dict[str, object]:
        """Os campos que o lead informou, e so eles.

        `is not None` e nao a veracidade do valor: `False`
        (`tem_imovel_para_vender`) e `0` (`vagas`) sao informacao, e um `if
        valor` os descartaria em silencio -- o lead que diz "nao tenho nada pra
        vender" respondeu a pergunta.
        """
        return {
            campo.name: valor
            for campo in fields(self)
            if (valor := getattr(self, campo.name)) is not None
        }

    def vazia(self) -> bool:
        return not self.preenchidos()
```

Em `RespostaDoAgente`, acrescente como **último** campo (os anteriores não têm default, então um campo com default não pode vir antes):

```python
    extracao: Extracao
```

E no docstring da classe, acrescente o parágrafo:

```
    `extracao` vem junto pelo mesmo motivo que `intencao` e `resposta`: sai da
    mesma chamada. O modelo enxerga a conversa inteira ao decidir as quatro
    coisas, e a resposta ja sai coerente com o que ele mesmo extraiu -- e por
    isso ele nao repergunta o que acabou de ouvir.
```

Em `src/mobia/domain/agente/classificador.py`, no `RespostaDoAgente(...)` da linha ~187, acrescente:

```python
                # Stub: a Tarefa 2 troca por `extrair(dados.get("extracao"))`.
                # O campo e obrigatorio, entao sem esta linha o modulo nao
                # tipa -- e sem o `extrair` da Tarefa 2 a extracao fica sempre
                # vazia em producao, o que nenhum teste desta tarefa pega.
                extracao=Extracao(),
```

e acrescente `Extracao` ao import de `mobia.domain.agente.schemas` que o arquivo já faz.

Em `tests/conftest.py`, no `ClassificadorFake.__init__`, acrescente o parâmetro depois de `confianca`:

```python
        extracao: "Extracao | None" = None,
```

e no corpo, junto das outras atribuições:

```python
        from mobia.domain.agente.schemas import Extracao as _Extracao

        self.extracao = extracao if extracao is not None else _Extracao()
```

e em `classificar`, no `return RespostaDoAgente(...)`, acrescente a linha:

```python
            extracao=self.extracao,
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_extracao.py -v > /tmp/t1.txt 2>&1; echo "EXIT=$?"; tail -20 /tmp/t1.txt`

Expected: PASS, 8 testes.

- [ ] **Step 5: Rodar ruff e mypy**

Run: `python -m ruff check src tests; python -m ruff format --check src tests; python -m mypy src`

Expected: sem erro. Se `mypy` reclamar de `Extracao` em `tests/conftest.py`, use o import local mostrado acima em vez de import no topo — o arquivo já usa esse padrão para `Intencao` e `RespostaDoAgente` por causa de ciclo.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/schemas.py src/mobia/domain/agente/classificador.py tests/conftest.py tests/unit/test_extracao.py
git commit -m "feat(TEC-145): vocabulario fechado e contrato da extracao"
```

---

### Task 2: Schema e parse tolerante

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py`
- Modify: `tests/unit/test_classificador.py`
- Test: `tests/unit/test_extracao.py` (acrescentar as guardas)

**Interfaces:**
- Consumes: `Extracao`, `TipoImovel`, `Urgencia`, `FormaPagamento` de `mobia.domain.agente.schemas`; `RespostaDoAgente.extracao`.
- Produces: `SCHEMA_DA_EXTRACAO: dict[str, Any]` e `extrair(bruto: Any) -> Extracao` em `mobia.domain.agente.classificador`. `SCHEMA_DA_RESPOSTA["properties"]["extracao"]` passa a existir e `"extracao"` entra em `SCHEMA_DA_RESPOSTA["required"]`.

**Contexto que o brief não sabe:** `_SCHEMA_COMPILADO = transform_schema(SCHEMA_DA_RESPOSTA)` roda **no import do módulo**. Um schema inválido não dá 400 na chamada — quebra a carga do módulo, e toda a suíte falha na coleta. Rode o teste de schema primeiro por isso.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente em `tests/unit/test_extracao.py`:

```python
from anthropic import transform_schema

from mobia.domain.agente.classificador import SCHEMA_DA_EXTRACAO, extrair


def test_schema_da_extracao_sobrevive_ao_compilador_do_sdk():
    """`transform_schema` encerra em `assert_never` para tipo desconhecido.

    `{"type": ["string", "null"]}` nao casa com nenhum ramo do dispatch e
    estoura aqui. `anyOf` e tratado por recursao. Este teste e a guarda contra
    alguem "simplificar" a anulabilidade de volta para lista.
    """
    compilado = transform_schema(SCHEMA_DA_EXTRACAO)
    assert compilado["type"] == "object"
    assert compilado["additionalProperties"] is False


def test_todos_os_nove_campos_sao_obrigatorios_e_anulaveis():
    propriedades = SCHEMA_DA_EXTRACAO["properties"]
    assert set(SCHEMA_DA_EXTRACAO["required"]) == set(propriedades)
    assert len(propriedades) == 9
    for nome, forma in propriedades.items():
        variantes = [variante.get("type") for variante in forma["anyOf"]]
        assert "null" in variantes, nome


def test_enums_do_schema_saem_dos_stre_enums():
    propriedades = SCHEMA_DA_EXTRACAO["properties"]
    for nome, enum in (
        ("tipo_imovel", TipoImovel),
        ("urgencia", Urgencia),
        ("forma_pagamento", FormaPagamento),
    ):
        nao_nulo = next(v for v in propriedades[nome]["anyOf"] if v.get("type") == "string")
        assert nao_nulo["enum"] == [membro.value for membro in enum]


def test_extrair_de_dicionario_completo():
    obtido = extrair(
        {
            "faixa_preco_min": None,
            "faixa_preco_max": 600000,
            "regiao": "zona sul",
            "tipo_imovel": "APARTAMENTO",
            "quartos": 2,
            "vagas": None,
            "urgencia": "ATE_3_MESES",
            "forma_pagamento": None,
            "tem_imovel_para_vender": False,
        }
    )
    assert obtido == Extracao(
        faixa_preco_max=Decimal("600000"),
        regiao="zona sul",
        tipo_imovel=TipoImovel.APARTAMENTO,
        quartos=2,
        urgencia=Urgencia.ATE_3_MESES,
        tem_imovel_para_vender=False,
    )


@pytest.mark.parametrize(
    "bruto",
    [None, "texto", 42, [], {"quartos": {"aninhado": 1}}],
)
def test_extrair_nunca_levanta(bruto):
    """Extracao e enriquecimento; a resposta ao lead vem da mesma chamada."""
    assert isinstance(extrair(bruto), Extracao)


def test_chave_ausente_nao_e_erro():
    assert extrair({"quartos": 2}) == Extracao(quartos=2)


@pytest.mark.parametrize(
    "valor",
    [-1, 0, 10**9 + 1, "seiscentos mil", float("nan"), float("inf"), True],
)
def test_preco_fora_da_faixa_e_descartado(valor):
    assert extrair({"faixa_preco_max": valor, "quartos": 2}) == Extracao(quartos=2)


def test_faixa_invertida_descarta_os_dois_precos():
    obtido = extrair({"faixa_preco_min": 900000, "faixa_preco_max": 600000, "quartos": 2})
    assert obtido == Extracao(quartos=2)


def test_faixa_igual_nos_dois_lados_e_valida():
    """"exatamente 600 mil" nao e faixa invertida."""
    obtido = extrair({"faixa_preco_min": 600000, "faixa_preco_max": 600000})
    assert obtido.faixa_preco_min == Decimal("600000")
    assert obtido.faixa_preco_max == Decimal("600000")


@pytest.mark.parametrize("campo", ["quartos", "vagas"])
@pytest.mark.parametrize("valor", [-1, 21, 2.5, "dois", True])
def test_inteiro_fora_da_faixa_e_descartado(campo, valor):
    assert extrair({campo: valor, "regiao": "centro"}) == Extracao(regiao="centro")


@pytest.mark.parametrize("campo", ["quartos", "vagas"])
def test_zero_e_valido(campo):
    """Kitnet tem 0 quarto e imovel sem garagem tem 0 vaga."""
    assert extrair({campo: 0}).preenchidos() == {campo: 0}


def test_valor_de_enum_desconhecido_e_descartado():
    obtido = extrair({"tipo_imovel": "IATE", "quartos": 2})
    assert obtido == Extracao(quartos=2)


def test_regiao_vazia_ou_so_espaco_e_descartada():
    assert extrair({"regiao": "   "}) == Extracao()


def test_regiao_e_truncada_no_limite_da_coluna():
    """`lead_qualification.regiao` e `String(120)`: 121 caracteres seria
    DataError no commit, derrubando o turno inteiro por um campo opcional."""
    obtido = extrair({"regiao": "a" * 200})
    assert obtido.regiao is not None
    assert len(obtido.regiao) == 120


def test_booleano_so_aceita_booleano():
    assert extrair({"tem_imovel_para_vender": "sim"}) == Extracao()
```

E em `tests/unit/test_classificador.py`, acrescente:

```python
def test_extracao_entra_na_resposta_do_agente(monkeypatch):
    dados = dict(_DADOS_VALIDOS, extracao={"quartos": 3, "regiao": "moema"})
    resposta = _resposta_falsa(texto=json.dumps(dados))
    cliente = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resposta)))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    resultado = asyncio.run(ClassificadorAnthropic().classificar(_contexto()))

    assert resultado.extracao.quartos == 3
    assert resultado.extracao.regiao == "moema"


def test_extracao_malformada_nao_derruba_o_turno(monkeypatch):
    """O contrato central desta card: a resposta ao lead sobrevive."""
    dados = dict(_DADOS_VALIDOS, extracao="isto nao e um objeto")
    resposta = _resposta_falsa(texto=json.dumps(dados))
    cliente = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resposta)))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    resultado = asyncio.run(ClassificadorAnthropic().classificar(_contexto()))

    assert resultado.resposta == TEXTO_DA_RESPOSTA
    assert resultado.extracao.vazia() is True


def test_resposta_sem_extracao_continua_valida(monkeypatch):
    """`_DADOS_VALIDOS` nao tem `extracao`. Se isto falhar, o parse ficou
    rigido onde deveria ser tolerante."""
    resposta = _resposta_falsa(texto=json.dumps(_DADOS_VALIDOS))
    cliente = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resposta)))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    resultado = asyncio.run(ClassificadorAnthropic().classificar(_contexto()))

    assert resultado.extracao.vazia() is True


def test_extracao_nao_vaza_no_log(monkeypatch, caplog):
    """`regiao` e fala do lead. O log deste modulo carrega so numeros e modelo."""
    dados = dict(_DADOS_VALIDOS, extracao={"regiao": "SENTINELA-REGIAO Rua das Palmeiras"})
    resposta = _resposta_falsa(texto=json.dumps(dados))
    cliente = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resposta)))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    with caplog.at_level(logging.INFO):
        asyncio.run(ClassificadorAnthropic().classificar(_contexto()))

    assert "SENTINELA-REGIAO" not in caplog.text
```

Se `asyncio` e `logging` já estiverem importados no arquivo, não duplique o import. O arquivo já importa `logging`; confira `asyncio` e, se os testes existentes usarem outro mecanismo para rodar corrotina (o `asyncio_mode = "auto"` do pyproject permite `async def` direto), **siga o padrão dos testes vizinhos** em vez do `asyncio.run` acima.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_extracao.py tests/unit/test_classificador.py -v > /tmp/t2.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t2.txt`

Expected: FAIL — `ImportError: cannot import name 'SCHEMA_DA_EXTRACAO'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/agente/classificador.py`, no import de `schemas`:

```python
from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    Intencao,
    PerguntaDeDesambiguacao,
    RespostaDoAgente,
    TipoImovel,
    Urgencia,
)
```

Depois de `SCHEMA_DA_RESPOSTA`, antes de `_SCHEMA_COMPILADO`:

```python
# Limites das guardas. Nao vao para o schema: `minimum`/`maximum` nao estao na
# lista que o compilador do servidor aceita (mesma razao documentada em
# `_SCHEMA_COMPILADO`), entao a faixa e checada aqui, em codigo.
PRECO_MINIMO = Decimal("1")
# `lead_qualification.faixa_preco_*` e `numeric(12,2)`: dez digitos antes da
# virgula. 10^9 cabe com folga; um valor maior seria DataError no commit e
# derrubaria o turno inteiro por causa de um campo opcional.
PRECO_MAXIMO = Decimal("1000000000")
MAX_AMBIENTES = 20
# `lead_qualification.regiao` e `String(120)`.
MAX_CARACTERES_DA_REGIAO = 120


def _anulavel(tipo: dict[str, Any]) -> dict[str, Any]:
    """Anulabilidade em `anyOf`, nunca em `type` como lista.

    `transform_schema` (anthropic/lib/_parse/_transform.py) declara
    `SupportedTypes` como `Literal` de tipos **unicos** e encerra o dispatch em
    `assert_never(type_)`. Um `{"type": ["string", "null"]}` nao casa com ramo
    nenhum e estoura ali -- e como `_SCHEMA_COMPILADO` e calculado no import
    deste modulo, a falha seria na carga, nao numa chamada. `anyOf` e tratado
    por recursao, e `"null"` esta entre os tipos suportados.
    """
    return {"anyOf": [tipo, {"type": "null"}]}


def _enum_anulavel(enum: type[StrEnum]) -> dict[str, Any]:
    return _anulavel({"type": "string", "enum": [membro.value for membro in enum]})


SCHEMA_DA_EXTRACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faixa_preco_min": _anulavel({"type": "number"}),
        "faixa_preco_max": _anulavel({"type": "number"}),
        "regiao": _anulavel({"type": "string"}),
        "tipo_imovel": _enum_anulavel(TipoImovel),
        "quartos": _anulavel({"type": "integer"}),
        "vagas": _anulavel({"type": "integer"}),
        "urgencia": _enum_anulavel(Urgencia),
        "forma_pagamento": _enum_anulavel(FormaPagamento),
        "tem_imovel_para_vender": _anulavel({"type": "boolean"}),
    },
    # Todos obrigatorios, todos anulaveis: forcar o modelo a dizer `null`
    # explicitamente e mais confiavel que aceitar chave ausente. O parse
    # tolera a ausencia de todo modo -- ver `extrair`.
    "required": [
        "faixa_preco_min",
        "faixa_preco_max",
        "regiao",
        "tipo_imovel",
        "quartos",
        "vagas",
        "urgencia",
        "forma_pagamento",
        "tem_imovel_para_vender",
    ],
    "additionalProperties": False,
}
```

Acrescente `StrEnum` ao import de `enum` no topo (`from enum import StrEnum`) e `"extracao": SCHEMA_DA_EXTRACAO` em `SCHEMA_DA_RESPOSTA["properties"]`, com `"extracao"` acrescentado a `SCHEMA_DA_RESPOSTA["required"]`.

Agora a função de parse, depois de `SCHEMA_DA_EXTRACAO`:

```python
def _numero(bruto: Any) -> Decimal | None:
    """Converte sem nunca levantar, e recusa bool antes de tudo.

    `isinstance(True, int)` e verdadeiro em Python: sem a recusa explicita,
    `"quartos": true` viraria 1 quarto silenciosamente.
    """
    if isinstance(bruto, bool) or not isinstance(bruto, int | float | str):
        return None
    try:
        valor = Decimal(str(bruto))
    except InvalidOperation:
        return None
    # NaN e infinito passam pelo Decimal. `is_finite` os pega antes de qualquer
    # comparacao -- toda comparacao com NaN e falsa, e um NaN que escapasse
    # seria gravado no banco como campo valido.
    return valor if valor.is_finite() else None


def _preco(bruto: Any) -> Decimal | None:
    valor = _numero(bruto)
    if valor is None or not (PRECO_MINIMO <= valor <= PRECO_MAXIMO):
        return None
    return valor


def _ambientes(bruto: Any) -> int | None:
    if isinstance(bruto, bool) or not isinstance(bruto, int):
        return None
    return bruto if 0 <= bruto <= MAX_AMBIENTES else None


def _membro(enum: type[StrEnum], bruto: Any) -> Any:
    if not isinstance(bruto, str):
        return None
    try:
        return enum(bruto)
    except ValueError:
        return None


def _regiao(bruto: Any) -> str | None:
    if not isinstance(bruto, str):
        return None
    limpa = bruto.strip()
    return limpa[:MAX_CARACTERES_DA_REGIAO] if limpa else None


def extrair(bruto: Any) -> Extracao:
    """Converte o objeto `extracao` do modelo, descartando o que nao serve.

    **Nunca levanta.** A extracao viaja na mesma chamada que a resposta ao
    lead, e um numero malformado nao pode matar uma resposta entregavel:
    extracao e enriquecimento, a resposta e o produto. Campo que falha na
    guarda e descartado; os outros campos do mesmo turno seguem.

    Nenhuma guarda e cosmetica -- cada uma existe porque o valor recusado
    seria `DataError` no commit (`regiao` acima de 120 caracteres, preco acima
    de `numeric(12,2)`) ou dado errado gravado em silencio (`true` virando 1
    quarto, NaN virando preco).
    """
    if not isinstance(bruto, dict):
        return Extracao()

    minimo = _preco(bruto.get("faixa_preco_min"))
    maximo = _preco(bruto.get("faixa_preco_max"))
    # Faixa invertida descarta os dois lados: nao ha como saber qual dos dois o
    # modelo errou, e gravar um deles produziria um filtro pior que nenhum.
    # `>` e nao `>=`: "exatamente 600 mil" e faixa valida com os dois iguais.
    if minimo is not None and maximo is not None and minimo > maximo:
        log.info("extracao.faixa_invertida_descartada")
        minimo = maximo = None

    return Extracao(
        faixa_preco_min=minimo,
        faixa_preco_max=maximo,
        regiao=_regiao(bruto.get("regiao")),
        tipo_imovel=_membro(TipoImovel, bruto.get("tipo_imovel")),
        quartos=_ambientes(bruto.get("quartos")),
        vagas=_ambientes(bruto.get("vagas")),
        urgencia=_membro(Urgencia, bruto.get("urgencia")),
        forma_pagamento=_membro(FormaPagamento, bruto.get("forma_pagamento")),
        tem_imovel_para_vender=(
            valor if isinstance(valor := bruto.get("tem_imovel_para_vender"), bool) else None
        ),
    )
```

Em `classificar`, no `RespostaDoAgente(...)` da linha ~187, acrescente:

```python
                extracao=extrair(dados.get("extracao")),
```

**Onde exatamente:** dentro do `try` que já existe, junto dos outros campos. `extrair` não levanta, então não amplia a superfície do `except` — mas `dados.get` precisa que `dados` exista, e ele só existe depois do `json.loads`.

Não acrescente nada ao `log.info("agente.turno_gerado")`. `regiao` é fala do lead, e a regra deste módulo é log só de números e id de modelo.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_extracao.py tests/unit/test_classificador.py -v > /tmp/t2.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t2.txt`

Expected: PASS. Se falhar na **coleta** com `AssertionError` vindo de `assert_never`, a anulabilidade foi escrita como `type` em lista — volte para `anyOf`.

- [ ] **Step 5: Suíte completa, ruff e mypy**

Run: `python -m pytest -q > /tmp/suite2.txt 2>&1; echo "EXIT=$?"; tail -5 /tmp/suite2.txt`

Expected: EXIT=0. A suíte tinha 415 testes passando antes desta card.

Run: `python -m ruff check src tests; python -m ruff format --check src tests; python -m mypy src`

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/classificador.py tests/unit/test_extracao.py tests/unit/test_classificador.py
git commit -m "feat(TEC-145): schema da extracao em anyOf e parse que nao derruba o turno"
```

---

### Task 3: Gravação no estado

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py`
- Modify: `src/mobia/domain/agente/turno.py:132-142`
- Modify: `tests/integration/test_repositorio_contexto.py`
- Test: `tests/integration/test_extracao_no_turno.py` (criar)

**Interfaces:**
- Consumes: `Extracao.preenchidos() -> dict[str, object]`; `RespostaDoAgente.extracao`; `Intencao`.
- Produces: `gravar_estado(session, *, channel, conversation_key, intencao, extracao) -> None` em `mobia.domain.context.repositorio`.

**Contexto que o brief não sabe:**
- O padrão de upsert do repo é `pg_insert(Modelo).values(valores).on_conflict_do_update(index_elements=[...], set_={...})`. Veja `gravar_resumo` no mesmo arquivo.
- `gravar_estado` **não commita**. O docstring de `gravar_resumo` já antecipa esta card: *"Isso importa a partir da TEC-145: gravar o resumo junto com outro estado na mesma transacao exige que nada aqui a feche antes da hora."*
- O import de `Intencao` em `context/repositorio.py` não cria ciclo: `domain/agente/schemas.py` não importa nada de `domain/context`.
- O bloco de sessão de `turno.py:132-142` lê `ler_intencao` **antes** de `gravar_intencao` por um motivo documentado ali; não reordene nada.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente em `tests/integration/test_repositorio_contexto.py` (siga o padrão de fixtures dos testes vizinhos do arquivo para obter `session`):

```python
async def test_gravar_estado_insere_e_depois_atualiza(session):
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="zona sul", quartos=2),
    )
    await session.commit()

    estado = await ler_estado(session, "whatsapp", "5511999")
    assert estado is not None
    assert estado.regiao == "zona sul"
    assert estado.quartos == 2
    assert estado.intencao == "COMPRA"


async def test_o_mais_novo_vence(session):
    for regiao in ("zona sul", "zona norte"):
        await gravar_estado(
            session,
            channel="whatsapp",
            conversation_key="5511999",
            intencao=Intencao.COMPRA,
            extracao=Extracao(regiao=regiao),
        )
        await session.commit()

    estado = await ler_estado(session, "whatsapp", "5511999")
    assert estado is not None
    assert estado.regiao == "zona norte"


async def test_null_nao_apaga(session):
    """A regra que faz "o mais novo vence" funcionar em vez de destruir tudo."""
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="zona sul", quartos=2),
    )
    await session.commit()

    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.COMPRA,
        extracao=Extracao(vagas=1),
    )
    await session.commit()

    estado = await ler_estado(session, "whatsapp", "5511999")
    assert estado is not None
    assert estado.regiao == "zona sul"
    assert estado.quartos == 2
    assert estado.vagas == 1


async def test_extracao_vazia_ainda_grava_a_intencao(session):
    """Turno em que o lead nao informou criterio nenhum. A intencao vale."""
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.ALUGUEL,
        extracao=Extracao(),
    )
    await session.commit()

    estado = await ler_estado(session, "whatsapp", "5511999")
    assert estado is not None
    assert estado.intencao == "ALUGUEL"
    assert estado.regiao is None


async def test_fora_de_escopo_nao_grava_nada(session):
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.FORA_DE_ESCOPO,
        extracao=Extracao(regiao="zona sul"),
    )
    await session.commit()

    assert await ler_estado(session, "whatsapp", "5511999") is None


async def test_fora_de_escopo_nao_apaga_estado_que_ja_existia(session):
    """O lead qualifica, depois manda uma piada. O que ele disse continua."""
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="zona sul"),
    )
    await session.commit()

    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999",
        intencao=Intencao.FORA_DE_ESCOPO,
        extracao=Extracao(),
    )
    await session.commit()

    estado = await ler_estado(session, "whatsapp", "5511999")
    assert estado is not None
    assert estado.regiao == "zona sul"
    assert estado.intencao == "COMPRA"
```

Crie `tests/integration/test_extracao_no_turno.py`. **Copie a montagem de `ctx` e as fixtures de um teste vizinho de `tests/integration/test_turno.py`** — `executar_turno` exige `moderador` como kwarg obrigatório, e um `ctx` montado à mão sem ele dá `KeyError` que, em teste com evento de sincronização, vira travamento em vez de falha:

```python
async def test_quatro_campos_de_uma_frase_so(...):
    """Gherkin 1 do card."""
    classificador = classificador_fake(
        Intencao.COMPRA,
        extracao=Extracao(
            tipo_imovel=TipoImovel.APARTAMENTO,
            quartos=2,
            regiao="zona sul",
            faixa_preco_max=Decimal("600000"),
            urgencia=Urgencia.ATE_3_MESES,
        ),
    )
    # ... executar_turno com o ctx do padrao vizinho ...

    estado = await ler_estado(session, message.channel, message.conversation_key)
    assert estado is not None
    assert (estado.tipo_imovel, estado.quartos, estado.regiao) == (
        "APARTAMENTO",
        2,
        "zona sul",
    )
    assert estado.faixa_preco_max == Decimal("600000.00")
    assert estado.urgencia == "ATE_3_MESES"


async def test_saida_bloqueada_ainda_grava_a_extracao(...):
    """O oposto deliberado da correcao da TEC-233, e a razao esta no spec: la o
    fato era sobre o que **nos** dissemos (a pergunta nunca foi feita); aqui e
    sobre o que **o lead** disse, e ele disse independentemente de a nossa
    resposta ter sido entregue. O comentario de `turno.py` ja fazia esse
    argumento para a intencao: "a classificacao e sobre a mensagem do lead, que
    existe, e nao sobre a resposta que pode nao sair"."""
    moderador = moderador_fake(bloqueia_saida=True)
    classificador = classificador_fake(Intencao.COMPRA, extracao=Extracao(quartos=3))
    # ... executar_turno ...

    estado = await ler_estado(session, message.channel, message.conversation_key)
    assert estado is not None
    assert estado.quartos == 3
```

**Sobre `moderador_fake(bloqueia_saida=True)`:** use a assinatura real da fixture em `tests/conftest.py`. Se ela não tiver esse parâmetro, use o mecanismo que `tests/integration/test_moderacao_de_saida.py` usa para bloquear a saída.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_repositorio_contexto.py tests/integration/test_extracao_no_turno.py -v > /tmp/t3.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t3.txt`

Expected: FAIL — `ImportError: cannot import name 'gravar_estado'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/context/repositorio.py`, depois de `ler_estado`:

```python
async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
) -> None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia.

    Nao commita -- a sessao e emprestada, como em `ler_resumo`, `ler_estado` e
    `gravar_resumo`, e quem chama e dono da fronteira da transacao. Nesta card
    quem chama e `executar_turno`, que grava intencao e estado no **mesmo**
    commit: os dois fatos vem da mesma chamada ao modelo.

    `FORA_DE_ESCOPO` nao grava nada, e a guarda vive aqui e nao em quem chama
    para que nao haja como esquece-la. Repare que ela tambem nao **apaga**: o
    lead que qualificou e depois mandou uma piada continua com o que disse.

    `intencao` vem de fora, do classificador, e nunca da extracao: a tabela
    `conversation_intent` e esta coluna guardam o mesmo fato, e duas fontes
    para ele divergiriam -- a divergencia apareceria como bug de score na
    TEC-150.
    """
    if intencao is Intencao.FORA_DE_ESCOPO:
        return

    # A regra de "null nao apaga" mora aqui: so os campos informados entram no
    # INSERT e no SET. Um dicionario completo com `None` nos campos calados
    # sobrescreveria com NULL a cada turno, e o estado nunca acumularia nada.
    preenchidos = extracao.preenchidos()
    valores: dict[str, Any] = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": intencao.value,
        "updated_at": datetime.now(UTC),
        **preenchidos,
    }
    statement = pg_insert(LeadQualification).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in (*preenchidos, "intencao", "updated_at")
            },
        )
    )
```

Acrescente aos imports do arquivo:

```python
from typing import Any

from mobia.domain.agente.schemas import Extracao, Intencao
```

O import de `mobia.domain.agente.schemas` aqui **não** cria ciclo: aquele módulo importa só `dataclasses`, `decimal` e `enum`.

Em `src/mobia/domain/agente/turno.py`, no bloco de sessão que já existe, depois de `gravar_intencao(...)` e **antes** de `await session.commit()`:

```python
        await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
        )
```

E acrescente `gravar_estado` ao import de `mobia.domain.context.repositorio` que o arquivo já faz (ou crie o import seguindo o padrão dos vizinhos).

No comentário que já explica o bloco (*"Gravada antes da entrega de proposito..."*), acrescente uma linha:

```
    # O estado de qualificacao entra no mesmo commit pela mesma razao, e ela
    # vale mais forte aqui: o que o lead disse que procura e fato sobre a fala
    # dele, nao sobre a nossa resposta. Saida bloqueada e envio fora da janela
    # nao descartam a extracao.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/integration/test_repositorio_contexto.py tests/integration/test_extracao_no_turno.py -v > /tmp/t3.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t3.txt`

Expected: PASS.

- [ ] **Step 5: Suíte completa, ruff e mypy**

Run: `python -m pytest -q > /tmp/suite3.txt 2>&1; echo "EXIT=$?"; tail -5 /tmp/suite3.txt`

Expected: EXIT=0.

Run: `python -m ruff check src tests; python -m ruff format --check src tests; python -m mypy src`

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/context/repositorio.py src/mobia/domain/agente/turno.py tests/integration/test_repositorio_contexto.py tests/integration/test_extracao_no_turno.py
git commit -m "feat(TEC-145): gravar o estado no commit da intencao, sem apagar com null"
```

---

### Task 4: Métrica de precisão da extração

**Files:**
- Modify: `src/mobia/evals/corpus.py`
- Modify: `src/mobia/evals/metricas.py`
- Modify: `tests/unit/test_evals_metricas.py`
- Modify: `tests/unit/test_evals_corpus.py`

**Interfaces:**
- Consumes: `Extracao.preenchidos()`.
- Produces: `TurnoAnotado.campos: dict[str, Any] | None`; `PISO_DE_PRECISAO_DA_EXTRACAO_PCT = 85`; `ExtracaoObservada(conversa_id, indice, esperado, obtido)`; `precisao_da_extracao(observadas) -> ResultadoDaMetrica`; `faixa_de(acertos, total, *, alvo=ALVO_PCT, piso=PISO_DE_BLOQUEIO_PCT)`.

**Contexto que o brief não sabe:** na TEC-210 foram criados um piso próprio (`PISO_DE_CATASTROFE_EFETIVA_PCT`) e uma segunda função de faixa (`faixa_de_catastrofe`), e **os dois foram deletados no PR #10** em favor de reusar `faixa_de`. Não recrie esse padrão: parametrize `faixa_de` com defaults, mantendo uma única função de faixa e todas as chamadas existentes intocadas.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente em `tests/unit/test_evals_metricas.py`:

```python
def _observada(esperado, obtido, *, indice=0):
    return ExtracaoObservada(
        conversa_id="compra-01", indice=indice, esperado=esperado, obtido=obtido
    )


def test_extracao_perfeita_e_cem_por_cento():
    resultado = precisao_da_extracao(
        [_observada({"quartos": 2, "regiao": "zona sul"}, {"quartos": 2, "regiao": "zona sul"})]
    )
    assert (resultado.acertos, resultado.total) == (2, 2)
    assert resultado.faixa is Faixa.VERDE


def test_campo_esperado_que_nao_veio_conta_erro():
    resultado = precisao_da_extracao([_observada({"quartos": 2, "vagas": 1}, {"quartos": 2})])
    assert (resultado.acertos, resultado.total) == (1, 2)


def test_campo_inventado_conta_erro():
    """Sem isto, extrair o certo mais quatro campos inventados daria 100%."""
    resultado = precisao_da_extracao(
        [_observada({"quartos": 2}, {"quartos": 2, "vagas": 3, "regiao": "moema"})]
    )
    assert (resultado.acertos, resultado.total) == (1, 3)


def test_nao_extrair_nada_nao_da_cem_por_cento():
    """Sem isto, um modelo que nunca extrai passaria no piso."""
    resultado = precisao_da_extracao([_observada({"quartos": 2, "regiao": "zona sul"}, {})])
    assert (resultado.acertos, resultado.total) == (0, 2)
    assert resultado.faixa is Faixa.VERMELHO


def test_valor_errado_no_campo_certo_conta_erro():
    resultado = precisao_da_extracao([_observada({"quartos": 2}, {"quartos": 3})])
    assert (resultado.acertos, resultado.total) == (0, 1)


def test_regiao_compara_sem_ligar_para_caixa_nem_espaco():
    resultado = precisao_da_extracao([_observada({"regiao": "Zona Sul"}, {"regiao": " zona sul "})])
    assert (resultado.acertos, resultado.total) == (1, 1)


def test_preco_compara_por_valor_e_nao_por_texto():
    """600000 e Decimal("600000.00") sao o mesmo preco."""
    resultado = precisao_da_extracao(
        [_observada({"faixa_preco_max": 600000}, {"faixa_preco_max": Decimal("600000.00")})]
    )
    assert (resultado.acertos, resultado.total) == (1, 1)


def test_piso_da_extracao_e_oitenta_e_cinco():
    assert PISO_DE_PRECISAO_DA_EXTRACAO_PCT == 85


def test_faixa_da_extracao_usa_o_piso_proprio():
    """84 de 100 e o unico ponto que discrimina os dois pisos.

    Com o piso geral (84) seria AMARELO; com o piso da extracao (85) e
    VERMELHO. Testar 85/100 nao provaria nada: 85 passa nos dois pisos, e o
    teste continuaria verde se alguem esquecesse de passar `piso=`.
    """
    observadas = [_observada({"quartos": 2}, {"quartos": 2}, indice=i) for i in range(84)]
    observadas += [_observada({"quartos": 2}, {"quartos": 3}, indice=84 + i) for i in range(16)]
    resultado = precisao_da_extracao(observadas)
    assert (resultado.acertos, resultado.total) == (84, 100)
    assert resultado.faixa is Faixa.VERMELHO
    # A prova de que o piso e a unica diferenca: o mesmo par no piso geral sobe.
    assert faixa_de(84, 100) is Faixa.AMARELO


def test_nada_medido_nao_e_sucesso():
    with pytest.raises(ValueError):
        precisao_da_extracao([])


def test_faixa_de_continua_com_os_defaults_de_antes():
    """A parametrizacao nao pode mudar nenhuma chamada existente."""
    assert faixa_de(90, 100) is Faixa.VERDE
    assert faixa_de(84, 100) is Faixa.AMARELO
    assert faixa_de(83, 100) is Faixa.VERMELHO
```

E em `tests/unit/test_evals_corpus.py`:

```python
def test_turno_sem_campos_tem_campos_none():
    """Turno nao anotado nao entra na medicao de extracao."""
    conversas = carregar(DIRETORIO_DE_EXEMPLO)
    assert any(turno.campos is None for conversa in conversas for turno in conversa.turnos)


def test_campo_desconhecido_no_corpus_e_erro():
    with pytest.raises(CorpusInvalido):
        _turno_de(
            {"lead": "oi", "intencao": "COMPRA", "campos": {"piscina": True}},
            "compra-99",
            "compra.yaml",
        )


def test_valor_fora_do_vocabulario_e_erro():
    with pytest.raises(CorpusInvalido):
        _turno_de(
            {"lead": "oi", "intencao": "COMPRA", "campos": {"tipo_imovel": "IATE"}},
            "compra-99",
            "compra.yaml",
        )
```

Adapte os nomes de fixture/constante aos que o arquivo já usa.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_evals_metricas.py -v > /tmp/t4.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t4.txt`

Expected: FAIL — `ImportError: cannot import name 'precisao_da_extracao'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/evals/corpus.py`, acrescente a `TurnoAnotado`:

```python
    campos: dict[str, Any] | None = None
```

E em `_turno_de`, depois da validação de `intencao`:

```python
    campos_brutos = bruto.get("campos")
    if campos_brutos is None:
        campos = None
    elif not isinstance(campos_brutos, dict) or not campos_brutos:
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} tem `campos` que nao e objeto ou esta vazio. "
            f"Omita a chave para deixar o turno fora da medicao de extracao."
        )
    else:
        # Anotacao e contrato: `campos` presente significa "este turno esta
        # anotado por completo". A metrica conta campo extraido que nao esta
        # aqui como erro, entao uma anotacao parcial nao vira nota mais baixa
        # do modelo -- vira medicao errada.
        for nome, valor in campos_brutos.items():
            if nome not in _CAMPOS_ANOTAVEIS:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota campo desconhecido {nome!r}. "
                    f"Conhecidos: {sorted(_CAMPOS_ANOTAVEIS)}."
                )
            enum = _VOCABULARIO.get(nome)
            if enum is not None and valor not in [membro.value for membro in enum]:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota {nome}={valor!r}, fora do "
                    f"vocabulario {[membro.value for membro in enum]}."
                )
        campos = campos_brutos
```

com, no topo do módulo:

```python
from mobia.domain.agente.schemas import Extracao, FormaPagamento, TipoImovel, Urgencia

_CAMPOS_ANOTAVEIS = frozenset(campo.name for campo in fields(Extracao))
_VOCABULARIO = {
    "tipo_imovel": TipoImovel,
    "urgencia": Urgencia,
    "forma_pagamento": FormaPagamento,
}
```

(`fields` vem de `dataclasses`, que o módulo já importa para o `@dataclass`.)

Em `src/mobia/evals/metricas.py`:

```python
# O piso da extracao vem do card (RF-05, secao 4.4 do SRS): 85%. Diferente do
# `PISO_DE_BLOQUEIO_PCT` de intencao, que e 84.
PISO_DE_PRECISAO_DA_EXTRACAO_PCT = 85
```

Parametrize `faixa_de` sem mudar comportamento de chamada existente:

```python
def faixa_de(
    acertos: int,
    total: int,
    *,
    alvo: int = ALVO_PCT,
    piso: int = PISO_DE_BLOQUEIO_PCT,
) -> Faixa:
```

trocando as duas comparações do corpo por `alvo` e `piso`. **Mantenha o docstring como está** — o argumento de aritmética inteira continua valendo palavra por palavra. Acrescente só:

```
    `alvo` e `piso` sao parametros com default porque a extracao (TEC-145) tem
    piso proprio de 85. Uma segunda funcao de faixa foi tentada na TEC-210
    (`faixa_de_catastrofe`) e deletada no PR #10: duas funcoes de faixa
    divergem, e a divergencia so aparece na borda.
```

E a métrica:

```python
@dataclass(frozen=True)
class ExtracaoObservada:
    """Um turno anotado, com o que se esperava e o que veio.

    `esperado` sao os campos que o corpus anotou para este turno; `obtido` e o
    `Extracao.preenchidos()` do que o modelo devolveu. Os dois sao dicionarios
    de nome de campo para valor.
    """

    conversa_id: str
    indice: int
    esperado: dict[str, Any]
    obtido: dict[str, Any]


def _comparavel(valor: Any) -> Any:
    """Normaliza para comparar anotacao de YAML com valor vindo do parse.

    `regiao` e texto livre escrito a mao no corpus: caixa e espaco nao sao erro
    do modelo. Preco vem do YAML como `int` e do parse como `Decimal`, e
    600000 e Decimal("600000.00") sao o mesmo preco.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().casefold()
    if isinstance(valor, int | float | Decimal):
        return Decimal(str(valor))
    return valor


def precisao_da_extracao(observadas: Sequence[ExtracaoObservada]) -> ResultadoDaMetrica:
    """Precisao de campo, punindo os dois lados da conta.

    O denominador e a **uniao** dos campos esperados com os obtidos, por turno.
    Isso e o que torna a metrica honesta nas duas direcoes:

    - So o esperado no denominador daria 100% a um modelo que acerta os campos
      anotados e inventa outros quatro.
    - So o obtido daria 100% a um modelo que nunca extrai nada -- o mesmo furo
      que a TEC-233 encontrou em corpus so-positivo, onde um moderador que
      bloqueia tudo passa.

    Turno sem anotacao (`campos` ausente no corpus) nao chega aqui: quem filtra
    e o runner, porque um turno nao anotado nao tem verdade contra a qual
    comparar.
    """
    acertos = 0
    total = 0
    for observada in observadas:
        nomes = set(observada.esperado) | set(observada.obtido)
        total += len(nomes)
        acertos += sum(
            1
            for nome in nomes
            if nome in observada.esperado
            and nome in observada.obtido
            and _comparavel(observada.esperado[nome]) == _comparavel(observada.obtido[nome])
        )
    faixa = faixa_de(acertos, total, piso=PISO_DE_PRECISAO_DA_EXTRACAO_PCT)
    return ResultadoDaMetrica(
        nome="precisao da extracao",
        faixa=faixa,
        acertos=acertos,
        total=total,
        detalhe=_detalhe(
            acertos, total, f"alvo {ALVO_PCT}%, piso {PISO_DE_PRECISAO_DA_EXTRACAO_PCT}%"
        ),
    )
```

Acrescente `Decimal` e `Any` aos imports do módulo se ainda não estiverem lá.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/ -v -k "metrica or corpus" > /tmp/t4.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t4.txt`

Expected: PASS.

- [ ] **Step 5: Suíte completa, ruff e mypy**

Run: `python -m pytest -q > /tmp/suite4.txt 2>&1; echo "EXIT=$?"; tail -5 /tmp/suite4.txt`

Expected: EXIT=0.

Run: `python -m ruff check src tests; python -m ruff format --check src tests; python -m mypy src`

- [ ] **Step 6: Commit**

```bash
git add src/mobia/evals/corpus.py src/mobia/evals/metricas.py tests/unit/
git commit -m "feat(TEC-145): precisao da extracao punindo campo faltante e campo inventado"
```

---

### Task 5: Corpus anotado, runner do eval e README

**Files:**
- Modify: `src/mobia/evals/contexto.py`
- Modify: `evals/corpus/compra.yaml`, `evals/corpus/aluguel.yaml`, `evals/corpus/investimento.yaml`
- Modify: `evals/test_acuracia_de_intencao.py`
- Modify: `tests/unit/test_evals_corpus_real.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `TurnoAnotado.campos`; `ExtracaoObservada`; `precisao_da_extracao`; `Extracao.preenchidos()`; `contexto_do_historico`.
- Produces: `PISO_DE_TURNOS_ANOTADOS = 30` em `mobia.evals.metricas`; `contexto_do_historico(historico, *, sistema, estado=None)`.

**Contexto que o brief não sabe:**
- O docstring de `contexto_do_historico` diz hoje *"Sem estado porque a extracao de campos (TEC-145) nao existe, entao nao ha o que preencher."* Esta tarefa torna essa frase falsa; reescreva-a.
- O runner acumula histórico com as **duas** falas: `historico.append((MessageRole.LEAD, turno.lead))` na linha 78 e `historico.append((MessageRole.AGENTE, resposta.resposta))` na linha 105.
- `_rodar_conversa` levanta `InfraestruturaFalhou` na primeira falha e **descarta os turnos que já deram certo naquela conversa**, de propósito. Não mude isso.
- **NÃO rode `pytest evals`.** Verifique o runner novo por leitura e pelos testes unitários.

- [ ] **Step 1: Anotar o corpus**

Escolha **no mínimo 30 turnos** distribuídos entre `compra.yaml`, `aluguel.yaml` e `investimento.yaml` e acrescente a chave `campos`. Anote **só o que a fala daquele turno afirma**, e anote **tudo** o que ela afirma — anotação parcial vira medição errada, não nota mais baixa.

Exemplo, no formato exato do corpus (o YAML é dado e pode ter acento):

```yaml
    - lead: "boa tarde, procuro um 2 quartos pra alugar na regiao do brooklin"
      intencao: ALUGUEL
      campos:
        tipo_imovel: APARTAMENTO
        quartos: 2
        regiao: brooklin
```

Regras de anotação, para a medição significar algo:
- Não anote o que a fala não diz. *"procuro um 2 quartos"* não afirma `tipo_imovel` se não disser "apto" ou "casa" — no exemplo acima, anote `tipo_imovel` **apenas** se a fala sustentar.
- `regiao` como o lead escreveu, em minúscula e sem pontuação; a comparação já ignora caixa e espaço.
- Preço em número inteiro de reais: `600000`, nunca `"600 mil"`.
- Turno cuja fala não afirma campo nenhum: **omita** a chave `campos`. Ele fica fora da medição, e é isso que se quer.
- Inclua ao menos um turno de correção (o lead troca a região que já tinha dado), porque é o caso de sobrescrita que a D4 do spec aceitou com risco.

- [ ] **Step 2: Escrever os testes que falham**

Em `tests/unit/test_evals_corpus_real.py`:

```python
def test_corpus_tem_turnos_anotados_suficientes():
    """Piso proprio: sem ele, anotar tres turnos faceis daria 100% de precisao
    num corpus que nao mede nada."""
    conversas = carregar(CORPUS)
    anotados = sum(1 for c in conversas for t in c.turnos if t.campos is not None)
    assert anotados >= PISO_DE_TURNOS_ANOTADOS


def test_anotacao_nunca_usa_valor_fora_do_vocabulario():
    """`carregar` ja levanta nesse caso; este teste guarda o corpus commitado."""
    conversas = carregar(CORPUS)
    for conversa in conversas:
        for turno in conversa.turnos:
            for nome, enum in _VOCABULARIO.items():
                if turno.campos and nome in turno.campos:
                    assert turno.campos[nome] in [membro.value for membro in enum]


def test_ha_turno_de_correcao_anotado():
    """A sobrescrita pelo mais novo (D4 do spec) precisa de caso no corpus."""
    conversas = carregar(CORPUS)
    for conversa in conversas:
        regioes = [
            turno.campos["regiao"]
            for turno in conversa.turnos
            if turno.campos and "regiao" in turno.campos
        ]
        if len(regioes) >= 2 and len(set(regioes)) >= 2:
            return
    pytest.fail("nenhuma conversa anotada troca de regiao: a sobrescrita nao e medida")
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_evals_corpus_real.py -v > /tmp/t5.txt 2>&1; echo "EXIT=$?"; tail -30 /tmp/t5.txt`

Expected: FAIL — `ImportError` de `PISO_DE_TURNOS_ANOTADOS`, ou falha do piso se o Step 1 anotou menos de 30.

- [ ] **Step 4: Implementar**

Em `src/mobia/evals/metricas.py`:

```python
# Piso de anotacao, irmao do PISO_DE_TURNOS. Sem ele, anotar tres turnos
# faceis daria precisao alta num corpus que nao mede nada -- o mesmo furo do
# corpus so-positivo, na outra direcao.
PISO_DE_TURNOS_ANOTADOS = 30
```

Em `src/mobia/evals/contexto.py`, troque a assinatura e o docstring:

```python
def contexto_do_historico(
    historico: Sequence[tuple[MessageRole, str]],
    *,
    sistema: str,
    estado: LeadQualification | None = None,
) -> ContextoMontado:
    """Monta o contexto direto, sem resumo.

    Sem resumo porque as conversas do corpus sao curtas -- a regeneracao so
    dispara a cada ~40 mensagens.

    `estado` existe a partir da TEC-145: o runner acumula a extracao dos turnos
    anteriores e passa aqui, porque medir "nao repergunta campo preenchido" com
    estado sempre vazio nao mediria nada -- o modelo nunca teria visto o campo.
    """
```

passando `estado=estado` no `ContextoMontado(...)` e importando `LeadQualification` de `mobia.domain.context.models`.

Em `evals/test_acuracia_de_intencao.py`, dentro de `_rodar_conversa`, acumule o estado e colecione as observações. `LeadQualification` é um modelo SQLAlchemy, mas aqui nunca vai ao banco — é o mesmo padrão transiente que `mensagem_transiente` já usa:

```python
    estado_acumulado: dict[str, Any] = {}
    observadas: list[ExtracaoObservada] = []
```

antes do laço; dentro dele, depois de `classificador.classificar`:

```python
        obtido = resposta.extracao.preenchidos()
        if turno.campos is not None:
            observadas.append(
                ExtracaoObservada(
                    conversa_id=conversa.id,
                    indice=indice,
                    esperado=turno.campos,
                    obtido=obtido,
                )
            )
        # Acumula como producao acumula: o mais novo vence, `None` nao apaga.
        # Sem isto o estado do turno seguinte estaria vazio e o modelo nunca
        # teria visto o campo que nao deveria reperguntar.
        estado_acumulado.update(obtido)
```

e o `contexto_do_historico` da iteração seguinte passa a receber:

```python
        contexto = contexto_do_historico(
            historico,
            sistema=SISTEMA_DO_AGENTE,
            estado=LeadQualification(**estado_acumulado) if estado_acumulado else None,
        )
```

Para o proxy de repergunta, acrescente ao módulo:

```python
# Marcadores por campo para o proxy de repergunta. Sao pistas, nao gramatica:
# a heuristica tem falso negativo por construcao -- um "e onde voce quer?" com
# outra palavra escapa. Mede uma cota inferior de reperguntas, nunca uma
# garantia. Esta limitacao esta declarada no README de proposito.
MARCADORES_DE_REPERGUNTA = {
    "regiao": ("regiao", "bairro", "onde", "localiza"),
    "quartos": ("quarto", "dormitorio"),
    "vagas": ("vaga", "garagem"),
    "tipo_imovel": ("apartamento", "casa", "tipo de imovel"),
    "faixa_preco_max": ("orcamento", "faixa de preco", "quanto pretende", "valor"),
    "urgencia": ("prazo", "quando pretende", "pressa"),
    "forma_pagamento": ("pagamento", "financiamento", "a vista"),
    "tem_imovel_para_vender": ("imovel para vender", "tem imovel"),
}


def _reperguntou(texto: str, campos_conhecidos: Iterable[str]) -> list[str]:
    baixo = texto.casefold()
    return [
        campo
        for campo in campos_conhecidos
        if any(marcador in baixo for marcador in MARCADORES_DE_REPERGUNTA.get(campo, ()))
    ]
```

e no laço, **antes** de atualizar `estado_acumulado` (a pergunta é sobre o que já era conhecido *antes* deste turno):

```python
        reperguntados.extend(
            (conversa.id, indice, campo)
            for campo in _reperguntou(resposta.resposta, conhecidos_antes)
        )
```

com `conhecidos_antes = set(estado_acumulado)` capturado no início da iteração.

Faça `_rodar_conversa` devolver as três listas (classificações, observações, reperguntas) em vez de só a primeira, ajuste o chamador em `test_acuracia_de_intencao_no_corpus`, acrescente `precisao_da_extracao(observadas)` à lista de métricas que `_metricas_de` monta, e imprima a contagem de reperguntas no relatório como **diagnóstico, não gate** — siga o que `ResumoDeConfianca` já faz, que é diagnóstico pelo mesmo motivo.

- [ ] **Step 5: Declarar no README**

Na seção da TEC-145 do README (crie-a seguindo o formato das seções TEC-134/TEC-233 que já existem), inclua estas lacunas, sem eufemismo:

```markdown
- **A medição de "não repergunta" é um proxy com falso negativo.** Detectar em
  texto livre que o agente perguntou a região exigiria um juiz-modelo pago.
  `MARCADORES_DE_REPERGUNTA` em `evals/test_acuracia_de_intencao.py` é lista de
  palavra-chave: uma repergunta com outras palavras não é contada. O número
  medido é uma **cota inferior** de reperguntas, não garantia de que não houve.
- **Nada impede o agente de reperguntar.** A escolha da próxima pergunta é do
  modelo, guiada pelo prompt; não há seletor em código. O spec (D5) explica por
  quê — TEC-148 e TEC-149 mexem no mesmo seletor e o reescreveriam.
- **Uma extração ruim apaga dado bom em definitivo.** A sobrescrita é pelo mais
  novo e a tabela guarda só o valor atual, sem histórico: não há como saber que
  houve troca nem voltar atrás. Aceito conscientemente no spec (D4); a
  alternativa sobrepunha desenho com a TEC-152.
- **O corpus anota um subconjunto dos turnos.** A precisão de extração é medida
  sobre os turnos com `campos` anotado, não sobre os 136. `PISO_DE_TURNOS_ANOTADOS`
  guarda o tamanho mínimo desse subconjunto.
- **A precisão de extração nunca foi executada.** O eval é pago e roda sob demanda
  ou em PR que toque `src/mobia/domain/agente/`.
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `python -m pytest -q > /tmp/suite5.txt 2>&1; echo "EXIT=$?"; tail -5 /tmp/suite5.txt`

Expected: EXIT=0.

Run: `python -m ruff check src tests evals; python -m ruff format --check src tests evals; python -m mypy src`

Confira também que o eval **importa** sem rodar:

Run: `python -c "import evals.test_acuracia_de_intencao as m; print('import ok')"`

Expected: `import ok`.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/evals/ evals/ tests/unit/test_evals_corpus_real.py README.md
git commit -m "feat(TEC-145): corpus anotado, precisao no gate e o proxy declarado no README"
```

---

## Auto-revisão deste plano

**Cobertura do spec:**

| Requisito do spec | Tarefa |
|---|---|
| D1 — extração no schema da chamada existente, sem tool | 2 |
| D1 — o modelo propõe, o código grava | 2 (guardas) + 3 (`gravar_estado`) |
| D2 — preço extraído aqui, tipado como número | 2 |
| D3 — `intencao` não é extraída, vem do classificador | 1 (ausente de `Extracao`) + 3 (parâmetro de `gravar_estado`) |
| D4 — mais novo vence, sem histórico | 3 |
| D5 — sem seletor de perguntas, com medição | 5 |
| Vocabulário controlado; `regiao` livre | 1 |
| `anyOf`, não `type` em lista | 2 |
| Guardas de código | 2 |
| Extração inválida não derruba o turno | 2 |
| `gravar_estado` não commita, no bloco existente | 3 |
| `null` não apaga | 1 (`preenchidos`) + 3 |
| Saída bloqueada não descarta | 3 |
| Só `FORA_DE_ESCOPO` não escreve | 3 |
| Retentativa idempotente | 3 |
| Eval sem chamada nova; corpus estendido | 5 |
| Precisão punindo os dois lados; piso 85 | 4 |
| Proxy de repergunta declarado | 5 |

Sem lacuna.

**Consistência de tipos:** `Extracao.preenchidos() -> dict[str, object]` é consumido por `gravar_estado` (Tarefa 3) e pelo runner (Tarefa 5); `ExtracaoObservada.esperado/obtido` são `dict[str, Any]` e recebem `turno.campos` e `preenchidos()`. `faixa_de` mantém a assinatura posicional antiga; só ganha dois keyword-only com default.

**Sem armadilhas:** o plano nao planta erro nenhum de proposito. Uma versao anterior plantava um membro extra em `FormaPagamento` para o implementador remover; foi retirada, porque uma armadilha gasta o tempo de quem implementa e pode sobreviver no codigo.
