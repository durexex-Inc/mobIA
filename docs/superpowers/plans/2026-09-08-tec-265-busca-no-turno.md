# TEC-265 — Ligar a busca híbrida ao turno do agente: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O turno do agente passa a obter candidatos do catálogo por tool call, para que a TEC-161 tenha contra o que validar e a busca da TEC-158 deixe de ser código que só a rota HTTP chama.

**Architecture:** O laço de tool use vive em `ClassificadorAnthropic._chamar`, que já é o ponto único de toda chamada ao modelo — `tool_use` deixa de ser parada inválida e passa a ser esperada, com teto de um round-trip por turno. A busca entra por uma porta injetada (no molde do `embedador` de `indexar_catalogo`), e é a porta que traduz o input do tool call em `FiltroDeBusca` — nem `classificar` conhece `FiltroDeBusca`, nem `busca.py` conhece o formato do tool call.

**Tech Stack:** Python 3.13, `anthropic` SDK (structured outputs via `output_config` + `tools`), SQLAlchemy async, pytest com `pytest-asyncio` em modo auto.

**Spec:** [docs/superpowers/specs/2026-09-08-tec-265-busca-no-turno-design.md](../specs/2026-09-08-tec-265-busca-no-turno-design.md) — o plano argumenta a partir dele; leia os dois.

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum. Prosa em `docs/` leva acento.
- **Os três gates estáticos, nesta ordem, antes de cada commit:** `ruff check src tests alembic evals`, `ruff format --check src tests alembic evals`, `mypy` (escopo `src`). O formatador é gate separado do linter: passar num não diz nada sobre o outro.
- **Basename de arquivo de teste é único em toda a árvore.** `tests/unit/x.py` e `tests/integration/x.py` com o mesmo nome abortam a coleta da suíte inteira, e o erro não aparece rodando os arquivos isolados. Os dois nomes deste plano — `test_ferramenta_de_busca.py` e `test_busca_no_turno.py` — foram verificados como livres em 2026-09-08.
- **Nada de acento dentro de padrão regex é removido**: acento em regex neste repo é intencional.
- **Comentário desatualizado é defeito.** Se você mudar código que um comentário descreve, o comentário muda junto ou sai — a Task 6 existe só para isso.
- **Modelo do agente:** `claude-sonnet-5` (`config.py:107`). Não troque.
- **`domain/agente` e `domain/catalogo` não se importam hoje.** Este plano cria o primeiro acoplamento, e ele fica num arquivo só, nomeado: `domain/agente/ferramenta_de_busca.py`. Não espalhe.
- **Suíte inteira leva ~25 minutos.** Rode arquivo isolado durante o trabalho; a suíte completa uma vez, no fim.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/mobia/domain/agente/ferramenta_de_busca.py` (novo) | O schema da ferramenta (`FERRAMENTA_DE_BUSCA`) e a porta que traduz tool call → `FiltroDeBusca` → `tool_result`. Único ponto onde `agente` toca `catalogo` | 1 |
| `tests/unit/test_ferramenta_de_busca.py` (novo) | Tradução, D6, D7, D11 e os caminhos de erro da porta | 1 |
| `src/mobia/domain/agente/classificador.py` | `_chamar` aceita `tool_use`; teto de um round-trip; `classificar` passa `tools` e devolve candidatos | 2, 3 |
| `src/mobia/domain/agente/schemas.py` | `RespostaDoAgente` ganha `candidatos` | 3 |
| `src/mobia/domain/agente/turno.py` | Injeta a porta; trata `LacoDeBuscaExcedido` pelo texto fixo | 4 |
| `tests/conftest.py` | `ClassificadorFake` aceita e guarda o kwarg `porta` | 4 |
| `tests/unit/test_config.py` | Quinta parcela da subcontagem; teto 780 | 5 |
| `src/mobia/app/config.py` | `contexto_headroom_de_tokens` 880 → 1005, com o preço escrito | 5 |
| `src/mobia/workers/jobs/indexar_catalogo.py` | Dois comentários que esta card torna falsos | 6 |
| `tests/integration/test_busca_no_turno.py` (novo) | Turno completo com catálogo real | 7 |

---

### Task 1: A ferramenta e a porta de busca

**Files:**
- Create: `src/mobia/domain/agente/ferramenta_de_busca.py`
- Create: `tests/unit/test_ferramenta_de_busca.py`

**Interfaces:**
- Consumes: `mobia.domain.catalogo.busca.buscar`, `mobia.domain.catalogo.schemas.FiltroDeBusca`, `mobia.domain.catalogo.enums.Operacao`, `mobia.domain.catalogo.enums.TipoImovel`.
- Produces: `FERRAMENTA_DE_BUSCA: dict[str, Any]` (a definição que vai em `tools=`), `PortaDeBusca` (alias de `Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]`), e `porta_de_busca(session_factory, *, buscar=None, embedador=None) -> PortaDeBusca`. A porta devolve `{"candidatos": [...], "total_candidatos": int}` no caminho normal e `{"erro": "<motivo>"}` quando a busca não pôde acontecer — quem monta o bloco `tool_result` com `is_error` é a Task 2.

- [ ] **Step 1: Verificar `strict` com `required` parcial contra a API (lacuna 1 do spec)**

Isto é o primeiro passo porque o número do orçamento (Task 5) depende dele. Rode uma vez, num script descartável no scratchpad, e **anote o resultado no corpo do commit da Task 1**:

```python
import anthropic
FERRAMENTA = {
    "name": "buscar_imoveis",
    "description": "Busca no catalogo. Nunca cite imovel que nao veio dela.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "operacao": {"type": "string", "enum": ["VENDA", "ALUGUEL"]},
            "tipo": {"type": "string"},
            "regioes": {"type": "array", "items": {"type": "string"}},
            "preco_max_centavos": {"type": "integer"},
            "quartos_min": {"type": "integer"},
            "vagas_min": {"type": "integer"},
            "consulta_texto": {"type": "string"},
        },
        "required": ["operacao"],
        "additionalProperties": False,
    },
}
# count_tokens valida a forma da requisicao sem gerar nada -- e o jeito barato
# de saber se `strict` aceita `required` parcial.
print(anthropic.Anthropic().messages.count_tokens(
    model="claude-sonnet-5",
    messages=[{"role": "user", "content": "oi"}],
    tools=[FERRAMENTA],
).input_tokens)
```

Se der `400`: ponha **todas** as propriedades em `required` e reexecute; o schema cresce e a Task 5 usa o número novo. Se passar: o schema fica como está.

- [ ] **Step 2: Escrever os testes que falham**

```python
"""A ferramenta de busca do agente e a porta que a executa.

Basename distinto de tudo em `tests/integration/`.
"""

import json
import uuid
from typing import Any

from mobia.domain.agente.ferramenta_de_busca import FERRAMENTA_DE_BUSCA, porta_de_busca
from mobia.domain.catalogo.enums import Operacao, TipoImovel
from mobia.domain.catalogo.schemas import Candidato, ResultadoDaBusca

CANDIDATO = Candidato(
    imovel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    codigo="AP-001",
    titulo="Apartamento na Vila Mariana",
    bairro="Vila Mariana",
    preco_centavos=74900000,
    quartos=3,
    vagas=2,
    area_util_m2=78,
    score=0.87,
    tem_vetor=True,
)


class _BuscaEspia:
    """Substitui `buscar`: guarda o filtro recebido e devolve um resultado fixo."""

    def __init__(self, resultado: ResultadoDaBusca | None = None) -> None:
        self.filtros: list[Any] = []
        self.consultas: list[str | None] = []
        self.resultado = resultado or ResultadoDaBusca(
            candidatos=(CANDIDATO,), total_candidatos=40, consulta_vetorizada=True
        )

    async def __call__(self, session, filtro, consulta_texto=None, **_: object):
        self.filtros.append(filtro)
        self.consultas.append(consulta_texto)
        return self.resultado


def _porta(busca: Any) -> Any:
    """A porta com a busca trocada e sem fabrica de sessao de verdade.

    `session_factory` e um callable que devolve um contexto assincrono; o falso
    aqui nunca e usado porque `_BuscaEspia` ignora a sessao.
    """
    return porta_de_busca(_FabricaFalsa(), buscar=busca)


class _FabricaFalsa:
    def __call__(self) -> "_FabricaFalsa":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_a_porta_traduz_o_tool_call_em_filtro() -> None:
    busca = _BuscaEspia()

    saida = await _porta(busca)(
        {
            "operacao": "VENDA",
            "tipo": "APARTAMENTO",
            "regioes": ["Vila Mariana"],
            "preco_max_centavos": 80000000,
            "quartos_min": 3,
            "vagas_min": 1,
            "consulta_texto": "varanda gourmet",
        }
    )

    filtro = busca.filtros[0]
    assert filtro.operacao is Operacao.VENDA
    assert filtro.tipo is TipoImovel.APARTAMENTO
    assert filtro.regioes == ("Vila Mariana",)
    assert filtro.preco_max_centavos == 80000000
    assert filtro.quartos_min == 3
    assert filtro.vagas_min == 1
    assert busca.consultas[0] == "varanda gourmet"
    assert saida["total_candidatos"] == 40


async def test_o_tool_result_leva_fato_do_imovel_e_nao_diagnostico_nosso() -> None:
    """D7: `score` e `tem_vetor` sao nossos, nao do imovel.

    Mandar `score` convida o modelo a dizer "97% de compatibilidade" ao lead --
    numero inventado com aparencia de fato.
    """
    saida = await _porta(_BuscaEspia())({"operacao": "VENDA"})

    (candidato,) = saida["candidatos"]
    assert candidato["imovel_id"] == "11111111-1111-1111-1111-111111111111"
    assert candidato["preco_centavos"] == 74900000
    assert candidato["codigo"] == "AP-001"
    assert "score" not in candidato
    assert "tem_vetor" not in candidato
    # Serializavel: o bloco `tool_result` vai como JSON.
    json.dumps(saida)


async def test_tipo_que_o_dominio_nao_le_derruba_a_dimensao_e_nao_a_busca() -> None:
    """D6: filtro ilegivel nao pode ESTREITAR em silencio.

    Alargar produz candidatos que alguem ve; estreitar produz zero resultados
    que parecem catalogo vazio.
    """
    busca = _BuscaEspia()

    saida = await _porta(busca)({"operacao": "VENDA", "tipo": "LOFT"})

    assert busca.filtros[0].tipo is None
    assert saida["candidatos"]


async def test_operacao_que_o_dominio_nao_le_e_erro_e_nao_dimensao_derrubada() -> None:
    """D11: `operacao` escolhe a coluna de preco -- sem ela nao existe busca.

    O `enum` do schema deveria impedir, mas a garantia depende de `strict`; a
    porta e o que sobra se ele sair.
    """
    busca = _BuscaEspia()

    saida = await _porta(busca)({"operacao": "COMPRA"})

    assert "erro" in saida
    assert busca.filtros == []


async def test_busca_que_levanta_vira_erro_e_nao_derruba_o_turno() -> None:
    async def explode(*_: object, **__: object) -> None:
        raise RuntimeError("banco fora")

    saida = await _porta(explode)({"operacao": "VENDA"})

    assert "erro" in saida


async def test_consulta_texto_ausente_busca_sem_vetor() -> None:
    busca = _BuscaEspia()

    await _porta(busca)({"operacao": "VENDA"})

    assert busca.consultas[0] is None


def test_a_ferramenta_declara_operacao_como_enum() -> None:
    """D11, e o `enum` custa +7,5 tokens de proposito."""
    propriedades = FERRAMENTA_DE_BUSCA["input_schema"]["properties"]
    assert propriedades["operacao"]["enum"] == ["VENDA", "ALUGUEL"]
    assert "enum" not in propriedades["tipo"]
    assert FERRAMENTA_DE_BUSCA["input_schema"]["additionalProperties"] is False
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_ferramenta_de_busca.py --tb=short`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.agente.ferramenta_de_busca'`.

- [ ] **Step 4: Escrever o módulo**

```python
"""A ferramenta de busca do agente, e a porta que a executa.

TEC-265. **Este e o unico arquivo em que `domain/agente` toca
`domain/catalogo`**, e o acoplamento fica aqui de proposito: o agente consome
o catalogo, o catalogo nao sabe que existe agente. Espalhar a importacao pelos
outros modulos do agente tornaria a direcao invisivel.

A tradução do input do tool call em `FiltroDeBusca` mora aqui pelo mesmo
motivo (D3 do desenho): `classificar` nao conhece `FiltroDeBusca` e
`busca.py` nao conhece o formato do tool call. Com a traducao num lugar so,
ela tem nome nos testes.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from mobia.domain.catalogo.busca import buscar as buscar_de_verdade
from mobia.domain.catalogo.enums import Operacao, TipoImovel
from mobia.domain.catalogo.schemas import Candidato, FiltroDeBusca

log = structlog.get_logger(__name__)

PortaDeBusca = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# `operacao` e `enum` e `tipo` nao e, e a assimetria e a D11 do desenho:
# `tipo` e dimensao DESCARTAVEL (valor ilegivel sai do filtro e a busca
# acontece), `operacao` escolhe a coluna de preco e `FiltroDeBusca` recusa
# default para ela. O `enum` custa +7,5 tokens do orcamento do prompt e faz o
# modelo traduzir COMPRA -> VENDA sozinho -- o vocabulario do agente
# (`Intencao.COMPRA`) e o do catalogo (`Operacao.VENDA`) discordam, e sem isso
# `Operacao("COMPRA")` levantaria em turno normal.
#
# Alongar a `description` ou acrescentar propriedade aqui gasta reserva de
# contexto: cada caractere e enviado em toda chamada. Antes de mexer, rode
# `pytest -q -k margem_do_orcamento -s`.
FERRAMENTA_DE_BUSCA: dict[str, Any] = {
    "name": "buscar_imoveis",
    "description": "Busca no catalogo. Nunca cite imovel que nao veio dela.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "operacao": {"type": "string", "enum": ["VENDA", "ALUGUEL"]},
            "tipo": {"type": "string"},
            "regioes": {"type": "array", "items": {"type": "string"}},
            "preco_max_centavos": {"type": "integer"},
            "quartos_min": {"type": "integer"},
            "vagas_min": {"type": "integer"},
            "consulta_texto": {"type": "string"},
        },
        "required": ["operacao"],
        "additionalProperties": False,
    },
}


def _tipo_de(bruto: object) -> TipoImovel | None:
    """O tipo pedido, ou None quando o dominio nao le o valor.

    D6: derrubar a dimensao e nao a busca. Um filtro que o dominio nao entende
    nao pode ESTREITAR o resultado em silencio -- alargar produz candidatos que
    alguem ve e um evento que alguem conta; estreitar produz zero resultados
    que parecem catalogo vazio.
    """
    if bruto is None:
        return None
    try:
        return TipoImovel(str(bruto))
    except ValueError:
        log.info("catalogo.tool_call_tipo_ilegivel", valor=str(bruto))
        return None


def _candidato_serializavel(candidato: Candidato) -> dict[str, Any]:
    """O que o modelo ve de um candidato.

    D7: `score` e `tem_vetor` NAO entram. Sao diagnostico do nosso lado, e
    `score` no prompt convida o modelo a dizer "97% de compatibilidade" ao
    lead -- dado inventado com aparencia de numero. `preco_centavos` vai como
    inteiro porque formatar e apresentacao (TEC-162) e porque inteiro e o que
    a TEC-161 vai comparar.
    """
    return {
        "imovel_id": str(candidato.imovel_id),
        "codigo": candidato.codigo,
        "titulo": candidato.titulo,
        "bairro": candidato.bairro,
        "preco_centavos": candidato.preco_centavos,
        "quartos": candidato.quartos,
        "vagas": candidato.vagas,
        "area_util_m2": candidato.area_util_m2,
    }


def porta_de_busca(
    session_factory: Any,
    *,
    buscar: Any = None,
    embedador: Any = None,
) -> PortaDeBusca:
    """A porta que o classificador chama quando o modelo pede a ferramenta.

    `buscar` e `embedador` sao injetaveis para o teste unitario nao precisar de
    banco nem de chave -- o mesmo molde do `embedador` que `indexar_catalogo`
    recebe pelo `ctx`.
    """
    executar = buscar or buscar_de_verdade

    async def porta(entrada: dict[str, Any]) -> dict[str, Any]:
        try:
            operacao = Operacao(str(entrada.get("operacao")))
        except ValueError:
            # D11: sem operacao legivel nao existe busca -- ela escolhe a
            # coluna de preco. Erro, e nao dimensao derrubada.
            log.warning(
                "catalogo.tool_call_operacao_ilegivel", valor=str(entrada.get("operacao"))
            )
            return {"erro": "operacao invalida: use VENDA ou ALUGUEL"}

        regioes = tuple(str(regiao) for regiao in entrada.get("regioes") or ())
        filtro = FiltroDeBusca(
            operacao=operacao,
            preco_max_centavos=entrada.get("preco_max_centavos"),
            tipo=_tipo_de(entrada.get("tipo")),
            quartos_min=entrada.get("quartos_min"),
            vagas_min=entrada.get("vagas_min"),
            regioes=regioes,
        )

        consulta = entrada.get("consulta_texto")

        try:
            async with session_factory() as session:
                resultado = await executar(
                    session,
                    filtro,
                    consulta_texto=consulta,
                    embedador=embedador,
                )
        except Exception as erro:
            # D9: `erro` no `tool_result`, nunca excecao. Excecao aqui mataria o
            # turno inteiro por causa de uma busca, e a regra que o
            # `indexar_catalogo` documenta e a oposta.
            log.warning("catalogo.tool_call_falhou", tipo=type(erro).__name__)
            return {"erro": "a busca nao pode ser feita agora"}

        return {
            "candidatos": [_candidato_serializavel(c) for c in resultado.candidatos],
            # RN-09.2: o agente precisa saber que ve 10 de 40.
            "total_candidatos": resultado.total_candidatos,
        }

    return porta
```

> **Correção pós-execução (2026-09-08).** O snippet acima tem um defeito que a revisão pegou: `Operacao("AMBOS")` é membro válido do enum, então passa pelo `except ValueError` — e `FiltroDeBusca.__post_init__` levanta depois, fora dos dois `try`, violando a D9. A guarda tem de cobrir também a operação que existe no enum e não tem coluna de preço, reusando `COLUNA_DE_PRECO` como definição única. O código entregue (`973f9b1`) já faz isso, com o teste `test_operacao_ambos_e_erro_e_nao_levanta`.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_ferramenta_de_busca.py --tb=short`
Expected: PASS, 8 testes (7 do snippet mais o do `AMBOS`).

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ferramenta_de_busca.py tests/unit/test_ferramenta_de_busca.py
git commit -m "feat(TEC-265): a ferramenta de busca e a porta que a traduz"
```

No corpo do commit, escreva o resultado do Step 1 (`strict` com `required` parcial: aceito ou 400).

---

### Task 2: `_chamar` aceita `tool_use`, com teto de um round-trip

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` (`_chamar`, e a nova exceção junto de `RespostaInvalida`)
- Modify: `tests/unit/test_classificador.py`

**Interfaces:**
- Consumes: `FERRAMENTA_DE_BUSCA` e `PortaDeBusca` da Task 1.
- Produces: `LacoDeBuscaExcedido(RuntimeError)`; `_chamar` ganha os parâmetros `tools: list[dict[str, Any]] | None = None` e `porta: PortaDeBusca | None = None`, e passa a devolver `tuple[str, Message, int, list[dict[str, Any]]]` — o quarto item são os candidatos que a ferramenta devolveu (lista vazia quando não houve tool call). A Task 3 consome esse quarto item.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/unit/test_classificador.py`. O falso de cliente de hoje devolve **uma** resposta (`AsyncMock(return_value=...)`); o laço precisa de uma sequência, então o helper novo usa `side_effect`:

```python
def _bloco_tool_use(entrada: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use", id="toolu_01", name="buscar_imoveis", input=entrada
    )


def _resposta_tool_use(entrada: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[_bloco_tool_use(entrada)],
        usage=SimpleNamespace(input_tokens=4000, output_tokens=200),
        stop_reason="tool_use",
    )


def _instalar_sequencia(
    monkeypatch: pytest.MonkeyPatch, respostas: list[SimpleNamespace]
) -> _ClienteFalso:
    """Um dublê que devolve uma resposta por chamada, na ordem dada.

    O `_ClienteFalso` de hoje tem `return_value` e serviria para uma chamada
    so; o laco de tool use faz duas.
    """
    cliente = _ClienteFalso(respostas[0])
    cliente.messages = SimpleNamespace(create=AsyncMock(side_effect=respostas))
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)
    return cliente


async def test_classificar_executa_a_ferramenta_e_chama_de_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "VENDA"}), _resposta_json()]
    )
    chamadas: list[dict[str, object]] = []

    async def porta(entrada: dict[str, object]) -> dict[str, object]:
        chamadas.append(entrada)
        return {"candidatos": [{"imovel_id": "abc", "preco_centavos": 100}], "total_candidatos": 1}

    resposta = await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    assert chamadas == [{"operacao": "VENDA"}]
    assert cliente.messages.create.await_count == 2
    assert resposta.candidatos == [{"imovel_id": "abc", "preco_centavos": 100}]


async def test_a_segunda_chamada_leva_o_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "VENDA"}), _resposta_json()]
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"candidatos": [], "total_candidatos": 0}

    await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    segunda = cliente.messages.create.await_args_list[1].kwargs
    blocos = segunda["messages"][-1]["content"]
    assert blocos[0]["type"] == "tool_result"
    assert blocos[0]["tool_use_id"] == "toolu_01"
    assert blocos[0].get("is_error") is not True


async def test_erro_da_porta_vira_tool_result_com_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9: o turno nao cai por causa de uma busca."""
    cliente = _instalar_sequencia(
        monkeypatch, [_resposta_tool_use({"operacao": "COMPRA"}), _resposta_json()]
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"erro": "operacao invalida: use VENDA ou ALUGUEL"}

    resposta = await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    blocos = cliente.messages.create.await_args_list[1].kwargs["messages"][-1]["content"]
    assert blocos[0]["is_error"] is True
    assert resposta.candidatos == []


async def test_um_segundo_tool_use_nao_e_atendido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4: o teto e um round-trip por turno.

    Sem ele, quantas chamadas o turno faz e decisao do modelo -- e a RNF-02
    (p95 <= 6 s) e a RNF-06 (US$ 0,12 por conversa) ficam a merce dela.
    """
    cliente = _instalar_sequencia(
        monkeypatch,
        [_resposta_tool_use({"operacao": "VENDA"}), _resposta_tool_use({"operacao": "VENDA"})],
    )

    async def porta(_: dict[str, object]) -> dict[str, object]:
        return {"candidatos": [], "total_candidatos": 0}

    with pytest.raises(classificador_mod.LacoDeBuscaExcedido):
        await ClassificadorAnthropic().classificar(_contexto(), porta=porta)

    assert cliente.messages.create.await_count == 2


async def test_sem_porta_a_ferramenta_nao_e_declarada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turno sem porta injetada continua sendo uma chamada so, sem `tools`."""
    cliente = _instalar_sequencia(monkeypatch, [_resposta_json()])

    await ClassificadorAnthropic().classificar(_contexto())

    assert "tools" not in cliente.messages.create.await_args.kwargs
    assert cliente.messages.create.await_count == 1
```

`_contexto()` é o helper que já existe no arquivo (o que monta `ContextoMontado`); use o nome real que estiver lá.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -k "ferramenta or tool_result or segundo_tool_use or sem_porta" --tb=short`
Expected: FAIL — `AttributeError: module has no attribute 'LacoDeBuscaExcedido'` e `TypeError: classificar() got an unexpected keyword argument 'porta'`.

- [ ] **Step 3: Implementar**

Em `classificador.py`, junto de `RespostaInvalida`:

```python
class LacoDeBuscaExcedido(RuntimeError):
    """O modelo pediu a ferramenta duas vezes no mesmo turno.

    D4 do desenho: o teto e um round-trip. Nao e falha do modelo nem do
    provedor -- e o teto funcionando --, e por isso tem tipo proprio: o turno
    a trata pelo texto fixo (`turno.py`), e nao pelo caminho de excecao que
    marca a mensagem como FAILED e reenfileira.
    """
```

Em `_chamar`, a política de parada passa a distinguir três casos, e o comentário antigo (*"nenhuma declara tools"*) **sai**:

```python
        kwargs: dict[str, Any] = {...}  # como hoje
        if tools is not None:
            # Ordem de renderizacao do cache e `tools` -> `system` ->
            # `messages`: com o breakpoint no `system`, uma lista de
            # ferramentas byte-estavel entra DENTRO do prefixo cacheado, e o
            # `test_o_prefixo_cacheavel_passa_o_minimo_do_modelo` continua
            # valendo porque o prefixo so cresce.
            kwargs["tools"] = tools
            # `auto`, e nao forcado: o `claude-sonnet-5` aceita `any`/`tool`,
            # mas forcar gastaria uma busca em TODO turno, inclusive nos que
            # nao pedem imovel.
            kwargs["tool_choice"] = {"type": "auto"}

        candidatos: list[dict[str, Any]] = []
        for tentativa in (1, 2):
            resposta = cast(Message, await get_client().messages.create(**kwargs))

            if resposta.stop_reason == "tool_use":
                if porta is None or tentativa == 2:
                    # Segunda vez: o teto da D4. Primeira vez sem porta: o
                    # modelo pediu ferramenta que nao declaramos.
                    raise LacoDeBuscaExcedido(f"tool_use na tentativa {tentativa}")
                blocos = [b for b in resposta.content if b.type == "tool_use"]
                kwargs["messages"] = [
                    *kwargs["messages"],
                    {"role": "assistant", "content": resposta.content},
                    {"role": "user", "content": [await _tool_result(porta, b) for b in blocos]},
                ]
                candidatos = _candidatos_de(kwargs["messages"][-1]["content"])
                continue

            # `end_turn` e a unica parada aproveitavel: `max_tokens` e
            # `refusal` nao produzem JSON que valha decodificar.
            if resposta.stop_reason != "end_turn":
                raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

            texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
            if not texto:
                raise RespostaInvalida(mensagem_se_vazia)
            return texto, resposta, latency_ms, candidatos

        raise LacoDeBuscaExcedido("laco de tool use nao convergiu")
```

E os dois auxiliares, ao lado de `_chamar`:

```python
async def _tool_result(porta: PortaDeBusca, bloco: Any) -> dict[str, Any]:
    """O bloco `tool_result` de um `tool_use`, com `is_error` quando a porta errou."""
    saida = await porta(dict(bloco.input))
    return {
        "type": "tool_result",
        "tool_use_id": bloco.id,
        "content": json.dumps(saida, ensure_ascii=False),
        **({"is_error": True} if "erro" in saida else {}),
    }


def _candidatos_de(blocos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Os candidatos que sairam dos `tool_result` deste turno.

    D8: eles saem do laco junto com a resposta. Se morressem aqui, a TEC-161
    teria de refazer a busca para validar -- e validar contra uma segunda busca
    e validar contra outra coisa, nao contra o que o modelo viu.
    """
    encontrados: list[dict[str, Any]] = []
    for bloco in blocos:
        if bloco.get("is_error"):
            continue
        encontrados.extend(json.loads(bloco["content"]).get("candidatos", []))
    return encontrados
```

A medição de latência (`comeco`/`latency_ms`) fica **fora** do laço: o que ela mede é o turno inteiro, e é isso que a RNF-02 cobra. Mova o `latency_ms = ...` para depois do laço, antes do `return`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py --tb=short`
Expected: PASS — os testes novos e **todos** os antigos. O `_chamar` mudou de assinatura de retorno, então `desambiguar` também precisa desempacotar quatro itens; se algum teste antigo falhar por isso, é aí.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/classificador.py tests/unit/test_classificador.py
git commit -m "feat(TEC-265): tool_use deixa de ser parada invalida, com teto de um round-trip"
```

---

### Task 3: `classificar` devolve os candidatos

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py` (`RespostaDoAgente`)
- Modify: `src/mobia/domain/agente/classificador.py` (`classificar` monta o novo campo)
- Modify: `tests/unit/test_classificador.py`

**Interfaces:**
- Consumes: o quarto item do retorno de `_chamar` (Task 2).
- Produces: `RespostaDoAgente.candidatos: list[dict[str, Any]]`, default `[]`. A TEC-161 vai ler exatamente este campo.

- [ ] **Step 1: Escrever o teste que falha**

```python
async def test_turno_sem_ferramenta_tem_candidatos_vazio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O campo existe sempre, e vazio significa "nao houve busca".

    None significaria a mesma coisa com um tipo a mais para a TEC-161 tratar.
    """
    _instalar_sequencia(monkeypatch, [_resposta_json()])

    resposta = await ClassificadorAnthropic().classificar(_contexto())

    assert resposta.candidatos == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -k candidatos_vazio --tb=short`
Expected: FAIL com `AttributeError: 'RespostaDoAgente' object has no attribute 'candidatos'`.

- [ ] **Step 3: Implementar**

Em `schemas.py`, no fim de `RespostaDoAgente` (campo com default vai depois dos sem default):

```python
    # TEC-265. Os candidatos que a ferramenta de busca devolveu neste turno,
    # ja no formato que o modelo viu -- e nao o `Candidato` do catalogo.
    #
    # Vazio significa "nao houve busca neste turno", e e por isso que o campo
    # nao e `None`: a TEC-161 vai validar a resposta contra esta lista, e um
    # tipo opcional a obrigaria a distinguir "nao buscou" de "buscou e nao
    # achou" para tomar a MESMA decisao nos dois casos.
    candidatos: list[dict[str, Any]] = field(default_factory=list)
```

Em `classificar`, desempacote o quarto item e passe adiante:

```python
        texto, resposta, latency_ms, candidatos = await self._chamar(
            contexto,
            modelo=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_RESPOSTA,
            system=SISTEMA_DO_AGENTE,
            mensagem_se_vazia="resposta veio vazia",
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA_COMPILADO}},
            tools=[FERRAMENTA_DE_BUSCA] if porta is not None else None,
            porta=porta,
        )
```

e inclua `candidatos=candidatos` na construção de `RespostaDoAgente`.

`ClassificadorPort` (o `Protocol`) ganha o parâmetro na assinatura de `classificar`:

```python
class ClassificadorPort(Protocol):
    async def classificar(
        self, contexto: ContextoMontado, *, porta: PortaDeBusca | None = None
    ) -> RespostaDoAgente: ...
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py --tb=short`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/schemas.py src/mobia/domain/agente/classificador.py tests/unit/test_classificador.py
git commit -m "feat(TEC-265): os candidatos saem do laco junto com a resposta"
```

---

### Task 4: O turno injeta a porta e trata o laço excedido

**Files:**
- Modify: `tests/conftest.py:171` (`ClassificadorFake.classificar` aceita e guarda `porta`) — **faça isto primeiro, ver Step 1**
- Modify: `src/mobia/domain/agente/turno.py:295` (a chamada a `classificar`) e o bloco de texto fixo
- Test: `tests/integration/test_turno.py` (os testes do turno são de integração neste repo; **não** existe `tests/unit/test_turno.py`)

**Interfaces:**
- Consumes: `porta_de_busca` (Task 1), `LacoDeBuscaExcedido` (Task 2), `RespostaDoAgente.candidatos` (Task 3).
- Produces: nada que tarefas seguintes consumam. `executar_turno` passa a montar a porta sobre a sua própria `session_factory`.

**`process_message.py` não muda.** A porta é montada dentro de `executar_turno`, que já recebe `session_factory` — nada novo precisa atravessar o `ctx` do ARQ.

- [ ] **Step 1: O dublê compartilhado aceita o kwarg novo (antes de qualquer teste)**

`ClassificadorFake.classificar` tem a assinatura `(self, contexto)`. No instante em que o turno passar `porta=`, **todos** os testes de turno quebram com `TypeError: classificar() got an unexpected keyword argument`. Então isto vem primeiro, em `tests/conftest.py`:

```python
    async def classificar(self, contexto, *, porta=None):
        from mobia.domain.agente.schemas import RespostaDoAgente

        self.chamadas += 1
        # Guardado, e nao ignorado: e o que o teste da TEC-265 afirma -- que o
        # turno monta a porta e a entrega pronta ao classificador (D3).
        self.portas.append(porta)
        if self.erro is not None:
            raise self.erro
        return RespostaDoAgente(
            ...  # como hoje
            candidatos=self.candidatos,
        )
```

e no `__init__`, dois campos novos:

```python
        self.candidatos: list[dict[str, object]] = []
        self.portas: list[object] = []
```

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_extracao_no_turno.py --tb=short`
Expected: PASS — a mudança é retrocompatível (`porta` tem default), e este arquivo é o mais rápido dos que constroem `RespostaDoAgente`.

- [ ] **Step 2: Escrever os testes que falham**

Em `tests/integration/test_turno.py`, com os dublês que o arquivo já usa (`ClassificadorFake` e `OutboundFake`, ambos do `conftest.py`):

A fixture `rodar_turno` (em `tests/conftest.py`) semeia a entrada e roda o turno inteiro — use ela, como `test_extracao_no_turno.py` faz, em vez de montar `executar_turno` à mão:

```python
from mobia.domain.agente.classificador import LacoDeBuscaExcedido
from mobia.domain.agente.turno import TEXTO_DA_BUSCA_INCONCLUSIVA


async def test_o_turno_monta_a_porta_e_a_entrega_ao_classificador(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """D3: quem tem `session_factory` e o turno, e e ele que passa a porta pronta.

    O classificador nao ganha `AsyncSession` -- se ganhasse, o dominio do agente
    passaria a fazer I/O de banco e o teste unitario do laco de tool use
    precisaria de container.
    """
    classificador = classificador_fake()

    resultado = await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert callable(classificador.portas[0])


async def test_laco_de_busca_excedido_entrega_texto_conservador(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """D4 mais D9: o teto do laco nao pode virar silencio nem falha retentavel.

    `LacoDeBuscaExcedido` tem tipo proprio justamente para NAO cair no caminho
    de excecao do `process_message`: la a mensagem viraria FAILED e o sweeper
    reenfileiraria o mesmo turno, que pediria a ferramenta duas vezes de novo
    -- duas chamadas ao modelo por tentativa para chegar ao mesmo lugar.
    """
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador_fake(erro=LacoDeBuscaExcedido("tool_use na tentativa 2")),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "respondido"
```

**O desfecho e "respondido"** e nao um valor novo: `ResultadoDoTurno` (`turno.py:56`) tem `respondido`, `sem_resposta`, `expirado`, `reentrega_suprimida` e os tres do opt-out, e o caminho de moderacao bloqueada -- que tambem passa por `_entregar_texto_fixo` -- devolve `respondido`. Nao acrescente membro ao `Literal`: o lead recebeu texto, e e isso que o desfecho relata.

Para afirmar **qual** texto saiu, leia o `message_telemetry` gravado, como os outros testes do arquivo fazem. Não acrescente atributo ao `OutboundFake` só para este teste — ele é compartilhado por toda a suíte.

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py -k "monta_a_porta or laco_de_busca" --tb=short`
Expected: FAIL — `classificador.portas == [None]` (o turno ainda não passa a porta) e `NameError: TEXTO_DA_BUSCA_INCONCLUSIVA`.

- [ ] **Step 4: Implementar**

Em `turno.py`, junto das outras constantes de texto:

```python
# TEC-265, D4. O lead nunca fica em silencio porque o teto do laco funcionou.
TEXTO_DA_BUSCA_INCONCLUSIVA = (
    "Deixa eu confirmar algumas coisas com um corretor para nao te passar "
    "informacao errada. Ja te retorno com as opcoes."
)
```

E na chamada de hoje (linha 295):

```python
    try:
        gerada = await classificador.classificar(
            contexto,
            # A porta e montada aqui porque e aqui que existe `session_factory`.
            # O classificador recebe um callable pronto e nao sabe o que e uma
            # sessao -- D3 do desenho.
            porta=porta_de_busca(session_factory),
        )
    except LacoDeBuscaExcedido:
        # Nao propaga: `process_message` marcaria FAILED e o sweeper
        # reenfileiraria o mesmo turno, que pediria a ferramenta duas vezes de
        # novo -- gastando duas chamadas ao modelo por tentativa para chegar
        # ao mesmo lugar. O lead recebe texto conservador e o corretor entra.
        log.warning("turno.laco_de_busca_excedido", channel=message.channel)
        return await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=TEXTO_DA_BUSCA_INCONCLUSIVA,
        )
```

`kind` e `subagent` ficam nos defaults (`KIND_DA_RESPOSTA` e `SUBAGENTE_MODERACAO`)? **Não**: passe `subagent=SUBAGENTE_CLASSIFICADOR`. Quem falhou foi o classificador, e rotular como moderação mentiria na telemetria — foi exatamente o defeito que a TEC-182 corrigiu ao acrescentar o parâmetro.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py tests/integration/test_extracao_no_turno.py tests/integration/test_turno_optout.py --tb=short`
Expected: PASS. Os três arquivos: todos passam por `classificar` e o Step 1 mexeu no dublê que os três usam.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/conftest.py tests/integration/test_turno.py
git commit -m "feat(TEC-265): o turno injeta a porta e o teto do laco nao vira silencio"
```

---

### Task 5: O gate de orçamento sobe, com o preço escrito

**Files:**
- Modify: `tests/unit/test_config.py` (`_decomposicao`, e o teto na asserção)
- Modify: `src/mobia/app/config.py:199` (`contexto_headroom_de_tokens`)

**Interfaces:**
- Consumes: `FERRAMENTA_DE_BUSCA` (Task 1).
- Produces: nada.

- [ ] **Step 1: Rodar o teste ANTES de mexer, para ver o número de hoje**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: PASS, com `= liquido 648.8` e `margem 6.2`. Anote os dois.

- [ ] **Step 2: Acrescentar a quinta parcela e ver o teste reprovar**

Em `_decomposicao`, depois do schema compilado:

```python
        # TEC-265: enviada em toda chamada do classificador e nunca contada por
        # `montar_contexto`, exatamente como o schema de saida.
        "+ferramenta de busca (tools=)": em_tokens(json.dumps(FERRAMENTA_DE_BUSCA)),
```

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: **FAIL**, com `liquido 780.0` contra o teto de 655. É esse número que a Task 5 existe para registrar — confirme que ele bate com o do spec antes de seguir; se o Step 1 da Task 1 obrigou `required` completo, ele será maior e o resto desta task usa o valor medido, não o do spec.

- [ ] **Step 3: Subir o teto e a reserva, com o histórico**

Na asserção e nas duas chamadas a `_linha`, troque `655` por `780`. E acrescente ao fim da docstring do teste, no formato das três subidas anteriores:

```
    A TEC-265 gastou os 6,2 que restavam e mais ~125, subindo o teto para 780
    e a reserva para 1005: a definicao da ferramenta de busca custou 131,2, e
    a alternativa mais barata foi recusada por defeito e nao por preco -- um
    schema com so `consulta_texto` (73,8) buscaria com o estado do turno
    anterior, porque a extracao do turno atual so volta no JSON final. Dentro
    da propria ferramenta houve corte: `tipo` como string livre em vez de
    `enum` economizou ~40, e `operacao` ficou `enum` (+7,5) porque e a unica
    dimensao que nao pode ser descartada -- ver a D5 e a D11 do desenho.
```

Em `config.py`, `contexto_headroom_de_tokens: int = 880` vira `1005`, e o comentário ganha o parágrafo com o preço:

```python
    # **880 -> 1005 na TEC-265**, que declarou a ferramenta de busca em
    # `tools=` (131,2 tokens). A alternativa sem `enum` em `operacao` custava
    # 123,8, e os 7,5 de diferenca compram o modelo traduzindo COMPRA -> VENDA
    # sozinho: os dois vocabularios discordam e `Operacao("COMPRA")`
    # levantaria em turno normal. Preco desta subida: **125 tokens a menos de
    # literais e resumo por turno, de 12000 -- 1,04% do contexto**. E a
    # segunda maior da historia do projeto, atras dos 3,3% da primeira.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -s --tb=short`
Expected: PASS. Confira na saída que `margem` voltou a ser um número pequeno e positivo — e que `test_diferenca_entre_o_contado_e_o_enviado`, que mede a mesma subcontagem contra outro teto, também passou.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/unit/test_config.py src/mobia/app/config.py
git commit -m "feat(TEC-265): o teto do orcamento sobe para 780, com o preco escrito"
```

---

### Task 6: Os dois comentários que esta card torna falsos

**Files:**
- Modify: `src/mobia/workers/jobs/indexar_catalogo.py` (o docstring do módulo)

**Interfaces:** nenhuma.

- [ ] **Step 1: Corrigir a atribuição de card**

O docstring diz que a busca *"ainda nao esta ligada ao turno, que e a TEC-161"*. É a TEC-265. Troque o número e a frase que o segue.

- [ ] **Step 2: Corrigir a frase que deixou de ser verdade**

O mesmo docstring afirma que `process_message` *"nao chama o provedor de embedding nenhum"*. Depois desta card ele chama, pela ferramenta de busca. O argumento de capacidade do lock consultivo **fica mais forte** e não mais fraco — reescreva dizendo isso, em vez de apagar o parágrafo:

```
Desde a TEC-265 o `process_message` CHAMA o provedor de embedding -- a busca
hibrida embeda a consulta do lead dentro do turno, por tool call. O que o
lock consultivo cobre fica mais forte, e nao mais fraco: os dois jobs
dividem o pool do worker ARQ, e agora os dois falam com o provedor.
```

- [ ] **Step 3: Verificar que nenhum outro comentário ficou velho**

Run: `grep -rn "TEC-161" src/ | grep -v "^src/mobia/domain/agente/ferramenta_de_busca.py"`
Expected: nenhuma linha afirmando que a TEC-161 liga a busca ao turno.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
git add src/mobia/workers/jobs/indexar_catalogo.py
git commit -m "docs(TEC-265): o docstring da indexacao para de atribuir a ligacao a TEC-161"
```

---

### Task 7: Integração — o turno com catálogo real

**Files:**
- Create: `tests/integration/test_busca_no_turno.py`

**Interfaces:**
- Consumes: tudo das tasks 1 a 4.
- Produces: nada.

- [ ] **Step 1: Escrever os testes que falham**

Três testes. Os dois primeiros são o que a Task 1 **não** cobre: lá `buscar` é falso, aqui ela roda contra o Postgres.

```python
"""A busca hibrida chegando ao turno. TEC-265.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from conftest import EmbedadorFake

from mobia.domain.agente.ferramenta_de_busca import porta_de_busca
from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    """Um imovel disponivel para venda. Copiado e nao importado de proposito:
    os arquivos de integracao deste repo sao autocontidos."""
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
        "bairro_busca": "vila mariana",
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


async def test_a_porta_busca_no_catalogo_de_verdade(session: Any) -> None:
    """Cenario 1 da card: o candidato chega com id e preco vindos do banco.

    E a RN-09.4 primeira metade, que a TEC-161 vai precisar: sem `imovel_id` e
    `preco_centavos` reais nao ha o que validar.
    """
    identificador = await _imovel(session)

    saida = await porta_de_busca(get_sessionmaker(), embedador=EmbedadorFake())(
        {"operacao": "VENDA", "consulta_texto": "apartamento com varanda"}
    )

    (candidato,) = saida["candidatos"]
    assert candidato["imovel_id"] == str(identificador)
    assert candidato["preco_centavos"] == 74900000
    assert saida["total_candidatos"] == 1


async def test_catalogo_sem_resultado_nao_vira_invencao(session: Any) -> None:
    """Cenario 2 da card: nenhum candidato, e nada falha.

    Zero resultado nao e erro -- relaxar o critorio e a TEC-160.
    """
    saida = await porta_de_busca(get_sessionmaker(), embedador=EmbedadorFake())(
        {"operacao": "VENDA", "quartos_min": 9}
    )

    assert saida["candidatos"] == []
    assert saida["total_candidatos"] == 0
    assert "erro" not in saida


async def test_turno_que_nao_pede_imovel_nao_apresenta_imovel(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, rodar_turno: Any,
) -> None:
    """Cenario 4 da card, e o mais fraco dos quatro -- de proposito.

    Com `tool_choice: auto` e o classificador FALSO, quem decide nao chamar a
    ferramenta e o dublê, nao o modelo: o teste afirma que o turno nao FORCA
    busca, e nao que o modelo se comporta. A outra metade -- o modelo deixando
    de buscar quando devia -- e a lacuna 3 do desenho, aceita como risco, e
    nenhum teste desta suite a cobre.
    """
    await _imovel(session)
    classificador = classificador_fake()

    resultado = await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    # A assercao e sobre o TEXTO entregue, e nao sobre `classificador.candidatos`
    # -- esse campo e o valor que o proprio dublê foi configurado para
    # devolver, e afirmar sobre ele seria afirmar sobre o teste. O imovel
    # existe no catalogo e nao aparece na resposta: e o que o cenario promete.
    async with get_sessionmaker()() as leitura:
        entregue = await _texto_entregue(leitura)
    assert "AP-001" not in entregue
```

`_texto_entregue` lê o `message_telemetry`/`messages` da resposta gravada — copie a leitura que `tests/integration/test_turno.py` já usa para afirmar sobre o texto que saiu, em vez de inventar uma consulta nova.

- [ ] **Step 2: Rodar e confirmar que falha, depois que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_no_turno.py --tb=short`

Se der `ConnectionResetError [WinError 64]`, **não diagnostique nada**: é o flake de negociação SSL que o `CLAUDE.md` descreve, e ele acontece em ~5% dos connects mesmo com o banco de pé há horas. Rode de novo.

- [ ] **Step 3: Gates, suíte inteira e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -u -m pytest --tb=short
```

A suíte leva ~25 minutos. Guarde o hash do commit junto com o resultado: falha isolada com `[WinError 64]` em arquivo que você não tocou é ambiente, não regressão — e a evidência que fecha o argumento é a mesma árvore duas vezes.

```bash
git add tests/integration/test_busca_no_turno.py
git commit -m "test(TEC-265): o turno traz candidatos do catalogo de verdade"
```

---

## Verificação final

- [ ] Os três gates limpos no escopo `src tests alembic evals`.
- [ ] Suíte completa verde (ou com falhas só de `[WinError 64]` em arquivos não tocados, confirmadas passando isoladas).
- [ ] `pytest -q -k margem_do_orcamento -s` imprimindo margem positiva com o teto novo.
- [ ] `grep -rn "nenhuma declara tools" src/` sem resultado — o comentário da Task 2 saiu.
- [ ] Nenhum `TEC-161` em `src/` afirmando que ela liga a busca ao turno.

## O que este plano NÃO faz

A lacuna 3 do desenho continua aberta e foi aceita como risco: com `tool_choice: auto`, um turno em que o lead pede imóvel e o modelo responde sem buscar é possível, e nada aqui impede. A TEC-161 não cobre — ela valida imóvel citado fora da lista, não ausência de busca. Se isso virar problema em produção, o sintoma é resposta genérica sem imóvel, e o lugar de olhar é a taxa de `tool_use` por turno, que ninguém mede hoje (a instrumentação é a TEC-211).
