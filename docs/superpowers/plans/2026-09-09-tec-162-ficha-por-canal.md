# TEC-162 — Ficha estruturada por canal: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O turno passa a entregar até 3 imóveis como imagens com legenda estruturada no WhatsApp, montadas por código a partir do catálogo, sem gastar um token do orçamento do prompt.

**Architecture:** Uma ficha agnóstica de canal (`domain/agente/apresentacao.py`, puro) renderiza a legenda; `ferramenta_de_busca.py` — o único arquivo em que `domain/agente` toca `domain/catalogo` — rebusca os três imóveis escolhidos por id e monta as fichas; o adaptador da Meta aprende um payload de imagem; `executar_turno` orquestra até três envios com kinds distintos. O modelo não declara nada de novo, então o prompt não muda.

**Tech Stack:** Python 3.13, SQLAlchemy async, FastAPI, pytest, ruff, mypy. Postgres e Redis por `docker compose`.

**Spec:** [docs/superpowers/specs/2026-09-09-tec-162-ficha-por-canal-design.md](../specs/2026-09-09-tec-162-ficha-por-canal-design.md)

## Global Constraints

- **Os três gates estáticos, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  `./.venv/Scripts/python.exe -m mypy`
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Comentários, docstrings e a fala do agente em `src/` e `tests/`: português SEM acento.** A ficha inteira é ASCII — `Condominio`, `m2`, separador `-`. Ver D12 do desenho.
- **Comentar o porquê, nunca o quê.** Comentário desatualizado é defeito. Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **O orçamento do prompt tem 6,0 tokens de margem** (líquido 780,0, teto fixo 786). Este plano não toca `SISTEMA_DO_AGENTE`, `FERRAMENTA_DE_BUSCA` nem o schema de saída. A Task 8 prova isso.
- **Basenames de teste são únicos entre `tests/unit/` e `tests/integration/`.** Colisão aborta a coleta da suíte inteira e não aparece em execução isolada.
- **Nenhuma tabela nova.** `TABELAS` em `tests/conftest.py` não cresce.
- **Baseline da suíte em `04b1c6a`:** 1336 passed, 2 failed, 3 errors, 31min01. As falhas são da família WinError 64 (`ConnectionResetError`, `OSError`, `redis.exceptions.ConnectionError`). O aceite compara contra esses números, não contra verde.
- **Mensagem de commit:** `tipo(TEC-162): o que passou a ser verdade`, em português sem acento no assunto.

---

### Task 1: O payload aprende a ser imagem

**Files:**
- Modify: `src/mobia/domain/outbound/whatsapp.py:47-60`
- Modify: `tests/conftest.py:260-263`
- Test: `tests/integration/test_whatsapp_outbound.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: o contrato de payload que todas as tarefas seguintes usam.
  - Texto: `{"para": str, "de": str, "texto": str}`, com `"tipo": "texto"` opcional. **Payload sem `tipo` continua sendo texto** — é isso que mantém os três chamadores de hoje funcionando.
  - Imagem: `{"tipo": "imagem", "para": str, "de": str, "link": str, "legenda": str}`.
  - `OutboundFake.entregues: list[str]` passa a guardar a legenda quando o payload é de imagem, e o texto quando é de texto.

- [ ] **Step 1: Escreva os testes que falham**

Em `tests/integration/test_whatsapp_outbound.py`, acrescente ao final do arquivo. O `PAYLOAD` no topo do arquivo já existe e não muda — é a prova da retrocompatibilidade.

```python
PAYLOAD_DE_IMAGEM = {
    "tipo": "imagem",
    "para": "5511911112222",
    "de": "222222222",
    "link": "https://exemplo.com/ap-1004-1.jpg",
    "legenda": "Apartamento em Lagoa da Conceicao\nLagoa da Conceicao - R$ 516.464",
}


def cliente_que_captura(capturado: dict[str, object]) -> httpx.AsyncClient:
    """Guarda o corpo enviado para a asserta poder ler o que foi para a Meta."""

    def _responde(requisicao: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(requisicao.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(_responde))


async def test_payload_sem_tipo_continua_saindo_como_texto(session) -> None:
    """A retrocompatibilidade dos tres chamadores de hoje, afirmada.

    `turno.py`, `_entregar_texto_fixo` e os caminhos de follow-up mandam
    payload sem `tipo`. Se este teste falhar, a TEC-162 quebrou a resposta
    normal do agente -- que e todo turno que nao apresenta imovel.
    """
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(uuid.uuid4(), "reply", PAYLOAD)

    assert corpo["type"] == "text"
    assert corpo["text"] == {"body": PAYLOAD["texto"]}


async def test_payload_de_imagem_sai_como_image_com_link_e_caption(session) -> None:
    """RN-10.2: uma imagem por imovel com legenda estruturada."""
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(uuid.uuid4(), "ficha_1", PAYLOAD_DE_IMAGEM)

    assert corpo["type"] == "image"
    assert corpo["image"] == {
        "link": PAYLOAD_DE_IMAGEM["link"],
        "caption": PAYLOAD_DE_IMAGEM["legenda"],
    }
```

Acrescente `import json` ao topo do arquivo, junto dos imports existentes.

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_whatsapp_outbound.py -v --tb=short
```

Esperado: `test_payload_de_imagem_sai_como_image_com_link_e_caption` falha com `KeyError: 'texto'` — o `_deliver` de hoje lê `payload["texto"]` sem olhar o tipo. O `test_payload_sem_tipo...` deve **passar** já: ele descreve o comportamento atual.

- [ ] **Step 3: Implemente o ramo no adaptador**

Em `src/mobia/domain/outbound/whatsapp.py`, substitua a montagem do `corpo` dentro de `_deliver`. O comentário de hoje sobre montar antes de abrir o cliente continua valendo e não sai.

```python
        settings = get_settings()
        # Monta url/corpo antes de abrir o cliente: se o payload vier sem uma
        # chave esperada, o KeyError estoura sem deixar um AsyncClient aberto
        # para tras.
        url = f"{settings.whatsapp_api_base}/{payload['de']}/messages"
        corpo: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": payload["para"],
        }
        # TEC-162. `tipo` ausente e texto, e o default nao e comodidade: os
        # chamadores de antes desta card (`turno.py`, `_entregar_texto_fixo`,
        # os follow-ups) nao mandam a chave, e exigi-la deles quebraria toda
        # resposta que nao apresenta imovel.
        if payload.get("tipo") == "imagem":
            corpo["type"] = "image"
            corpo["image"] = {"link": payload["link"], "caption": payload["legenda"]}
        else:
            corpo["type"] = "text"
            corpo["text"] = {"body": payload["texto"]}
```

- [ ] **Step 4: Conserte o `OutboundFake`**

Em `tests/conftest.py`, o `_deliver` do duble hoje faz `payload["texto"]` direto e levantaria `KeyError` no primeiro payload de imagem — num traceback que aponta para o conftest, não para a card.

```python
    async def _deliver(self, message_id, kind, payload) -> None:
        if self.erro is not None:
            raise self.erro
        # TEC-162: payload de imagem guarda a LEGENDA. `entregues` continua
        # `list[str]` para nao quebrar as assertas dos testes de antes desta
        # card, que comparam contra o texto entregue.
        self.entregues.append(payload.get("legenda") or payload["texto"])
```

- [ ] **Step 5: Rode os testes do adaptador e a vizinhança que usa o duble**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_whatsapp_outbound.py tests/integration/test_outbound_guard.py tests/integration/test_reserva_liberada.py -v --tb=short
```

Esperado: tudo passa. Se `test_outbound_guard.py` ou `test_reserva_liberada.py` quebrarem, o `entregues` mudou de forma para os chamadores antigos — volte ao Step 4.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/outbound/whatsapp.py tests/conftest.py tests/integration/test_whatsapp_outbound.py
git commit -m "feat(TEC-162): o payload de saida aprende imagem sem quebrar texto"
```

---

### Task 2: A ficha e a legenda, puras

**Files:**
- Create: `src/mobia/domain/agente/apresentacao.py`
- Test: `tests/unit/test_apresentacao.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `Ficha` — dataclass frozen com `titulo: str`, `bairro: str`, `preco_centavos: int`, `quartos: int`, `vagas: int`, `area_util_m2: int`, `condominio_centavos: int | None`, `diferencial: str | None`, `foto: str | None`.
  - `reais_de(centavos: int) -> str`
  - `diferencial_de(caracteristicas: Sequence[str]) -> str | None`
  - `legenda_de(ficha: Ficha, *, prefixo: str | None = None) -> str`
  - `MAX_CARACTERES_DA_LEGENDA = 600`, `CARACTERISTICAS_NO_DESTAQUE = 2`

**Este módulo não importa nada de `domain/catalogo`.** A invariante está no docstring de `ferramenta_de_busca.py` e a Task 4 é quem a respeita.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/unit/test_apresentacao.py`:

```python
"""A ficha e a legenda. TEC-162.

Basename distinto de tudo em `tests/integration/` -- colisao aborta a coleta
da suite inteira e nao aparece em execucao isolada.
"""

from dataclasses import replace

from mobia.domain.agente.apresentacao import (
    MAX_CARACTERES_DA_LEGENDA,
    Ficha,
    diferencial_de,
    legenda_de,
    reais_de,
)

# `replace` e nao `Ficha(**ficha.__dict__)`: `Ficha` e `slots=True` e nao tem
# `__dict__` -- a segunda forma levanta AttributeError.

COMPLETA = Ficha(
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=51646430,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial="churrasqueira e mobiliado",
    foto="https://exemplo.com/ap-1004-1.jpg",
)


def test_a_legenda_traz_os_oito_campos_da_rn_10_1() -> None:
    """RN-10.1: titulo, bairro, preco, quartos, vagas, area util, condominio
    e um diferencial em uma frase."""
    assert legenda_de(COMPLETA) == (
        "Apartamento em Lagoa da Conceicao\n"
        "Lagoa da Conceicao - R$ 516.464\n"
        "4 quartos - 2 vagas - 54 m2\n"
        "Condominio R$ 550\n"
        "Destaque: churrasqueira e mobiliado"
    )


def test_os_centavos_sao_truncados_para_baixo_e_nunca_arredondados() -> None:
    """D11. Arredondar para cima cota ao lead um preco ACIMA do real, e e essa
    a direcao que vira reclamacao na visita. 51646430 centavos sao
    R$ 516.464,30 -- os 30 centavos caem, nao sobem o milhar."""
    assert reais_de(51646430) == "R$ 516.464"
    assert reais_de(51646499) == "R$ 516.464"
    assert reais_de(74900000) == "R$ 749.000"


def test_condominio_nulo_omite_a_linha_e_nao_esconde_o_imovel() -> None:
    """D13. Ausencia omite a linha; o imovel e apresentado de todo jeito."""
    legenda = legenda_de(replace(COMPLETA, condominio_centavos=None))
    assert "Condominio" not in legenda
    assert "Apartamento em Lagoa da Conceicao" in legenda
    assert "Destaque: churrasqueira e mobiliado" in legenda


def test_sem_caracteristica_nao_ha_linha_de_destaque() -> None:
    """117 dos 520 imoveis do seed nao tem caracteristica nenhuma -- isto nao
    e caso de borda inventado."""
    assert diferencial_de(()) is None
    assert "Destaque" not in legenda_de(replace(COMPLETA, diferencial=None))


def test_o_destaque_leva_as_duas_primeiras_na_ordem_do_catalogo() -> None:
    """Ordem armazenada e nao ranking: quem quiser priorizar muda o CSV."""
    assert diferencial_de(("churrasqueira", "mobiliado", "piscina", "sacada")) == (
        "churrasqueira e mobiliado"
    )
    assert diferencial_de(("piscina",)) == "piscina"


def test_o_prefixo_entra_antes_da_ficha_separado_por_linha_em_branco() -> None:
    """D5: a prosa do modelo vira prefixo da legenda do PRIMEIRO imovel."""
    legenda = legenda_de(COMPLETA, prefixo="Achei tres opcoes que encaixam.")
    assert legenda.startswith("Achei tres opcoes que encaixam.\n\n")
    assert legenda.endswith("Destaque: churrasqueira e mobiliado")


def test_o_teto_de_600_corta_a_prosa_e_nunca_a_ficha() -> None:
    """D14. A ficha e o conteudo que a RN-10.1 exige; a prosa e ornamento.

    O teto e o da RN-04.2, o mesmo numero de
    `evals/metricas.MAX_CARACTERES_DA_RESPOSTA` -- e este e o primeiro lugar
    de `src/` que o respeita por construcao.
    """
    ficha_inteira = legenda_de(COMPLETA)
    legenda = legenda_de(COMPLETA, prefixo="palavra " * 200)

    assert len(legenda) <= MAX_CARACTERES_DA_LEGENDA
    assert legenda.endswith(ficha_inteira)
    assert "..." in legenda


def test_prosa_que_nao_cabe_de_jeito_nenhum_sai_de_cena() -> None:
    """Se nem a reticencia couber, a prosa some inteira -- a ficha nao cede."""
    gigante = Ficha(
        titulo="T" * 300,
        bairro="B" * 200,
        preco_centavos=51646430,
        quartos=4,
        vagas=2,
        area_util_m2=54,
        condominio_centavos=55000,
        diferencial="churrasqueira e mobiliado",
        foto=None,
    )
    legenda = legenda_de(gigante, prefixo="Achei tres opcoes que encaixam.")

    assert legenda == legenda_de(gigante)
    assert not legenda.startswith("Achei")
```

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py -v --tb=short
```

Esperado: erro de coleta — `ModuleNotFoundError: No module named 'mobia.domain.agente.apresentacao'`.

- [ ] **Step 3: Implemente o módulo**

Crie `src/mobia/domain/agente/apresentacao.py`:

```python
"""A ficha do imovel e a legenda que o lead recebe. TEC-162.

Puro de proposito: nenhum I/O e **nenhum import de `domain/catalogo`**. Quem
traduz `Imovel` em `Ficha` e `ferramenta_de_busca.fichas_do_catalogo`, que e
o unico arquivo em que `domain/agente` toca `domain/catalogo` -- a invariante
esta no docstring dele, e quebra-la aqui a tornaria invisivel.

Todo texto daqui sai para o lead e e ASCII, sem acento: `Condominio`, `m2`,
separador `-`. E a mesma disciplina de `TEXTO_DA_BUSCA_INCONCLUSIVA` em
`turno.py`, e a D12 do desenho explica por que a card a segue em vez de
consertar a politica.
"""

from collections.abc import Sequence
from dataclasses import dataclass

# RN-04.2. O mesmo numero de `evals/metricas.MAX_CARACTERES_DA_RESPOSTA`, que
# mede a regra nas evals; este e o primeiro lugar de `src/` que a respeita por
# construcao. Nao e limite da Meta -- a legenda dela cabe 1024.
MAX_CARACTERES_DA_LEGENDA = 600

# Duas e nao quatro porque cinco linhas de ficha e o limite do que se le numa
# legenda de foto.
CARACTERISTICAS_NO_DESTAQUE = 2

_SEPARADOR_DA_PROSA = "\n\n"
_RETICENCIA = "..."


@dataclass(frozen=True, slots=True)
class Ficha:
    """Os oito campos da RN-10.1, resolvidos e agnosticos de canal.

    Tres campos sao opcionais porque o catalogo os tem vazios de verdade --
    117 dos 520 imoveis do seed nao tem caracteristica nenhuma. Ausencia
    omite a linha e nunca esconde o imovel, que e a regra da propria RN-10.2
    sobre foto.
    """

    titulo: str
    bairro: str
    preco_centavos: int
    quartos: int
    vagas: int
    area_util_m2: int
    condominio_centavos: int | None
    diferencial: str | None
    foto: str | None


def reais_de(centavos: int) -> str:
    """`R$ 516.464` a partir de 51646430.

    Trunca os centavos para BAIXO e nunca arredonda: arredondar para cima
    cota ao lead um preco acima do real, e e essa a direcao que vira
    reclamacao na visita. O seed tem preco com centavos de verdade
    (`516464.30`), entao isto nao e hipotese.
    """
    return f"R$ {centavos // 100:,}".replace(",", ".")


def diferencial_de(caracteristicas: Sequence[str]) -> str | None:
    """As duas primeiras caracteristicas, na ordem em que o catalogo as guarda.

    Ordem armazenada e nao ranking: quem quiser priorizar muda o CSV. `None`
    quando nao ha nenhuma, e `legenda_de` omite a linha.
    """
    escolhidas = tuple(caracteristicas)[:CARACTERISTICAS_NO_DESTAQUE]
    if not escolhidas:
        return None
    return " e ".join(escolhidas)


def legenda_de(ficha: Ficha, *, prefixo: str | None = None) -> str:
    """A legenda de uma ficha, com a prosa do modelo opcionalmente na frente.

    Estourado o teto, o que se corta e o PREFIXO -- nunca a ficha. A ficha e
    o conteudo que a RN-10.1 exige e a prosa e ornamento, e essa ordem de
    prioridade e a D14 do desenho.
    """
    linhas = [
        ficha.titulo,
        f"{ficha.bairro} - {reais_de(ficha.preco_centavos)}",
        f"{ficha.quartos} quartos - {ficha.vagas} vagas - {ficha.area_util_m2} m2",
    ]
    if ficha.condominio_centavos is not None:
        linhas.append(f"Condominio {reais_de(ficha.condominio_centavos)}")
    if ficha.diferencial is not None:
        linhas.append(f"Destaque: {ficha.diferencial}")
    corpo = "\n".join(linhas)

    prosa = _prosa_que_cabe(prefixo, len(corpo)) if prefixo else ""
    if not prosa:
        return corpo
    return f"{prosa}{_SEPARADOR_DA_PROSA}{corpo}"


def _prosa_que_cabe(prefixo: str, tamanho_do_corpo: int) -> str:
    """O prefixo truncado na ultima fronteira de palavra que couber.

    Devolve string vazia quando nao sobra espaco nem para a reticencia --
    prosa cortada no meio de uma palavra sem marca nenhuma pareceria bug ao
    lead, e a ficha nunca cede espaco para evitar isso.
    """
    disponivel = MAX_CARACTERES_DA_LEGENDA - tamanho_do_corpo - len(_SEPARADOR_DA_PROSA)
    if len(prefixo) <= disponivel:
        return prefixo
    if disponivel <= len(_RETICENCIA):
        return ""
    return prefixo[: disponivel - len(_RETICENCIA)].rsplit(" ", 1)[0] + _RETICENCIA
```

**A linha do ruff é 100** (`pyproject.toml`), e `select = ["E", "F", "I", "UP", "B"]` — a `I` ordena os imports, então rode `ruff format` antes de conferir a ordem à mão.

- [ ] **Step 4: Rode até passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py -v --tb=short
```

Esperado: 8 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/apresentacao.py tests/unit/test_apresentacao.py
git commit -m "feat(TEC-162): a ficha da RN-10.1 existe e corta prosa, nunca campo"
```

---

### Task 3: Leitura do catálogo por id

**Files:**
- Modify: `src/mobia/domain/catalogo/repositorio.py` (acrescentar ao final)
- Test: `tests/integration/test_catalogo_por_ids.py`

**Interfaces:**
- Consumes: nada.
- Produces: `async def imoveis_por_ids(session: AsyncSession, ids: Sequence[uuid.UUID]) -> tuple[Imovel, ...]` — devolve **na ordem dos ids pedidos**, e id ausente sai da lista em vez de virar `None`.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_catalogo_por_ids.py`:

```python
"""Leitura do catalogo por id, na ordem pedida. TEC-162.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.repositorio import imoveis_por_ids


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Imovel {codigo}",
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


async def test_devolve_na_ordem_pedida_e_nao_na_do_banco(session: Any) -> None:
    """A ordem pedida e a ordem de SCORE da busca.

    Sem esta garantia a ficha_1 poderia ser o terceiro melhor candidato, e o
    lead leria a pior opcao primeiro sem que nada falhasse.
    """
    primeiro = await _imovel(session, "AP-001")
    segundo = await _imovel(session, "AP-002")
    terceiro = await _imovel(session, "AP-003")

    encontrados = await imoveis_por_ids(session, [terceiro, primeiro, segundo])

    assert [i.id for i in encontrados] == [terceiro, primeiro, segundo]


async def test_id_ausente_sai_da_lista_em_vez_de_virar_none(session: Any) -> None:
    """D6: imovel inativado entre a busca e a apresentacao devolve a menos, e
    isso nao e erro -- o turno apresenta o que voltou."""
    existente = await _imovel(session, "AP-001")

    encontrados = await imoveis_por_ids(session, [existente, uuid.uuid4()])

    assert [i.id for i in encontrados] == [existente]


async def test_lista_vazia_devolve_tupla_vazia(session: Any) -> None:
    """`IN ()` e SQL invalido em alguns dialetos; o chamador nao deve precisar
    saber disso."""
    assert await imoveis_por_ids(session, []) == ()
```

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_por_ids.py -v --tb=short
```

Esperado: erro de coleta — `ImportError: cannot import name 'imoveis_por_ids'`.

Se em vez disso aparecer `ConnectionResetError [WinError 64]` na negociação SSL, **espere e retente**: o `CLAUDE.md` documenta ~5% de falha nos connects, em rajada. Não é a sua mudança.

- [ ] **Step 3: Implemente**

Ao final de `src/mobia/domain/catalogo/repositorio.py`:

```python
async def imoveis_por_ids(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> tuple[Imovel, ...]:
    """Os imoveis pedidos, NA ORDEM PEDIDA. Nao comita.

    A ordem e o contrato, e nao um detalhe: quem chama e a apresentacao da
    TEC-162, e a ordem que ela pede e a de score da busca. Devolver na ordem
    do banco faria a ficha_1 ser um candidato qualquer, e o lead leria a pior
    opcao primeiro sem que nada falhasse.

    Id sem linha sai da lista em vez de virar `None`: imovel inativado entre
    a busca e a apresentacao e caminho normal (D6 do desenho), e um `None` no
    meio da tupla obrigaria todo chamador a filtrar.
    """
    if not ids:
        return ()

    encontrados = {
        imovel.id: imovel
        for imovel in (await session.scalars(select(Imovel).where(Imovel.id.in_(ids)))).all()
    }
    return tuple(encontrados[chave] for chave in ids if chave in encontrados)
```

Confirme que `Sequence` está importado de `collections.abc` no topo do arquivo; `uuid`, `select` e `Imovel` já estão.

- [ ] **Step 4: Rode até passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_catalogo_por_ids.py -v --tb=short
```

Esperado: 3 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/repositorio.py tests/integration/test_catalogo_por_ids.py
git commit -m "feat(TEC-162): o catalogo le por id na ordem pedida"
```

---

### Task 4: A ponte entre o catálogo e a ficha

**Files:**
- Modify: `src/mobia/domain/agente/ferramenta_de_busca.py` (acrescentar ao final)
- Test: `tests/integration/test_fichas_do_catalogo.py`

**Interfaces:**
- Consumes: `Ficha` e `diferencial_de` da Task 2; `imoveis_por_ids` da Task 3.
- Produces: `async def fichas_do_catalogo(session_factory: Any, *, ids: Sequence[uuid.UUID], precos: Mapping[uuid.UUID, int]) -> tuple[Ficha, ...]`

**Por que aqui e não num módulo novo:** o docstring deste arquivo declara que ele é o único em que `domain/agente` toca `domain/catalogo`. Esta função é a única peça que precisa ver `Imovel` e `Ficha` ao mesmo tempo.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_fichas_do_catalogo.py`:

```python
"""A ponte entre o catalogo e a ficha. TEC-162.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from mobia.domain.agente.ferramenta_de_busca import fichas_do_catalogo
from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento em Lagoa da Conceicao",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 51646430,
        "preco_aluguel": 350000,
        "condominio": 55000,
        "bairro": "Lagoa da Conceicao",
        "bairro_busca": "lagoa da conceicao",
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 54,
        "quartos": 4,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["churrasqueira", "mobiliado", "piscina"],
        "fotos": ["https://exemplo.com/ap-1004-1.jpg"],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_a_ficha_sai_completa_do_catalogo(session: Any) -> None:
    identificador = await _imovel(session, "AP-1004")

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.titulo == "Apartamento em Lagoa da Conceicao"
    assert ficha.bairro == "Lagoa da Conceicao"
    assert ficha.preco_centavos == 51646430
    assert ficha.quartos == 4
    assert ficha.vagas == 2
    assert ficha.area_util_m2 == 54
    assert ficha.condominio_centavos == 55000
    assert ficha.diferencial == "churrasqueira e mobiliado"
    assert ficha.foto == "https://exemplo.com/ap-1004-1.jpg"


async def test_o_preco_vem_do_candidato_e_nao_da_coluna(session: Any) -> None:
    """D7. A linha tem `preco_venda` E `preco_aluguel` e nao diz qual usar --
    a operacao buscada so existe dentro de `porta_de_busca`. O dict do
    candidato ja traz o preco da operacao certa.

    Se este teste falhar porque alguem passou a ler `preco_venda` da linha,
    toda busca de ALUGUEL passara a mostrar o preco de venda ao lead.
    """
    identificador = await _imovel(session, "AP-1004")

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 350000}
    )

    assert ficha.preco_centavos == 350000


async def test_sem_foto_a_ficha_sai_com_foto_none(session: Any) -> None:
    """D13: o imovel e apresentado de todo jeito, pelo caminho de texto."""
    identificador = await _imovel(session, "AP-1004", fotos=[])

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.foto is None


async def test_sem_caracteristica_o_diferencial_e_none(session: Any) -> None:
    identificador = await _imovel(session, "AP-1004", caracteristicas=[])

    (ficha,) = await fichas_do_catalogo(
        get_sessionmaker(), ids=[identificador], precos={identificador: 51646430}
    )

    assert ficha.diferencial is None


async def test_a_ordem_pedida_atravessa_a_ponte(session: Any) -> None:
    primeiro = await _imovel(session, "AP-001")
    segundo = await _imovel(session, "AP-002")

    fichas = await fichas_do_catalogo(
        get_sessionmaker(),
        ids=[segundo, primeiro],
        precos={primeiro: 10000000, segundo: 20000000},
    )

    assert [f.preco_centavos for f in fichas] == [20000000, 10000000]
```

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_fichas_do_catalogo.py -v --tb=short
```

Esperado: `ImportError: cannot import name 'fichas_do_catalogo'`.

- [ ] **Step 3: Implemente**

Ao final de `src/mobia/domain/agente/ferramenta_de_busca.py`:

```python
async def fichas_do_catalogo(
    session_factory: Any,
    *,
    ids: Sequence[uuid.UUID],
    precos: Mapping[uuid.UUID, int],
) -> tuple[Ficha, ...]:
    """As fichas dos imoveis pedidos, na ordem pedida. TEC-162.

    Mora NESTE arquivo, e nao em `apresentacao.py`, pela invariante do
    docstring do modulo: aqui e o unico lugar em que `domain/agente` importa
    `domain/catalogo`. Esta funcao e a unica peca que precisa ver `Imovel` e
    `Ficha` ao mesmo tempo, e `apresentacao.py` fica puro por causa dela.

    `precos` vem do dict do candidato e NAO da linha rebuscada: a linha tem
    `preco_venda` e `preco_aluguel` e nao diz qual usar, porque a operacao
    buscada so existe dentro de `porta_de_busca`. Ler a coluna aqui faria
    toda busca de aluguel mostrar preco de venda ao lead -- ver a D7 do
    desenho.
    """
    async with session_factory() as session:
        imoveis = await imoveis_por_ids(session, ids)

    return tuple(
        Ficha(
            titulo=imovel.titulo,
            bairro=imovel.bairro,
            preco_centavos=precos[imovel.id],
            quartos=imovel.quartos,
            vagas=imovel.vagas,
            area_util_m2=imovel.area_util_m2,
            condominio_centavos=imovel.condominio,
            diferencial=diferencial_de(imovel.caracteristicas),
            foto=imovel.fotos[0] if imovel.fotos else None,
        )
        for imovel in imoveis
    )
```

Acrescente aos imports do topo do arquivo:

```python
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence

from mobia.domain.agente.apresentacao import Ficha, diferencial_de
from mobia.domain.catalogo.repositorio import imoveis_por_ids
```

- [ ] **Step 4: Rode até passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_fichas_do_catalogo.py -v --tb=short
```

Esperado: 5 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ferramenta_de_busca.py tests/integration/test_fichas_do_catalogo.py
git commit -m "feat(TEC-162): a ficha sai do catalogo pelo arquivo que e a fronteira"
```

---

### Task 5: O gatilho e a orquestração no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — constantes no topo (perto de `KIND_DA_RESPOSTA:47`), o desvio dentro de `executar_turno` (perto de `543`), e o helper novo ao final do arquivo
- Test: `tests/integration/test_apresentacao_no_turno.py`

**Interfaces:**
- Consumes: `legenda_de` da Task 2; `fichas_do_catalogo` da Task 4; o contrato de payload da Task 1.
- Produces: `KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")` e `MAX_IMOVEIS_POR_TURNO = 3`, importáveis pelos testes e pela TEC-163.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_apresentacao_no_turno.py`. O harness (`session`, `outbound_fake`, `resumidor_fake`, `contador_fake`, `rodar_turno`) vem de `tests/conftest.py`; o dublê que pede a ferramenta é próprio deste arquivo, no mesmo molde de `_ClassificadorQuePedeAFerramenta` em `test_busca_no_turno.py`.

```python
"""A apresentacao de imoveis dentro do turno. TEC-162.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_busca_no_turno.py`.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.domain.agente.turno import KINDS_DAS_FICHAS
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import EnvioRecusado
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker
from mobia.domain.outbound.models import OutboundDispatch

PROSA = "Achei tres opcoes que encaixam no que voce falou."


async def _imovel(session: Any, codigo: str, preco: int, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": preco,
        "condominio": 55000,
        "bairro": "Lagoa da Conceicao",
        "bairro_busca": "lagoa da conceicao",
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 54,
        "quartos": 4,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["churrasqueira", "mobiliado"],
        "fotos": [f"https://exemplo.com/{codigo}.jpg"],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


class _ClassificadorComCandidatos:
    """Devolve candidatos prontos, sem passar pela busca real.

    Diferente de `_ClassificadorQuePedeAFerramenta` em `test_busca_no_turno.py`,
    que existe para provar que a busca de VERDADE atravessa: aqui o assunto e
    a APRESENTACAO, e fixar os candidatos deixa a asserta sobre quais fichas
    sairam livre da ordenacao por score.
    """

    def __init__(self, candidatos: list[dict[str, Any]], perguntou: tuple[str, ...] = ()) -> None:
        self.candidatos = candidatos
        self.perguntou = perguntou

    async def classificar(self, contexto: ContextoMontado, *, porta=None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            resposta=PROSA,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
        )

    async def desambiguar(self, contexto: ContextoMontado):
        raise AssertionError("confianca alta o bastante para nao desambiguar")


def _candidato(identificador: uuid.UUID, preco: int) -> dict[str, Any]:
    """O que `porta_de_busca._candidato_serializavel` devolve hoje."""
    return {
        "imovel_id": str(identificador),
        "codigo": "AP-001",
        "titulo": "Apartamento AP-001",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted(
            (await leitura.scalars(select(OutboundDispatch.kind))).all()
        )


async def _texto_gravado() -> str:
    async with get_sessionmaker()() as leitura:
        (falada,) = (
            (await leitura.execute(select(Message).where(Message.role == MessageRole.AGENTE)))
            .scalars()
            .all()
        )
        return decrypt(falada.text_body, aad_de(falada.id, "text_body"))


async def test_dez_candidatos_produzem_exatamente_tres_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """RN-10.2: maximo de 3 por turno, mesmo com 10 candidatos."""
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(10)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 3
    assert await _kinds_reservados() == sorted(KINDS_DAS_FICHAS)


async def test_a_prosa_vira_prefixo_da_primeira_e_as_outras_sao_ficha_pura(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D5. A voz do agente sobrevive no turno mais importante da conversa."""
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    primeira, segunda, terceira = outbound.entregues
    assert primeira.startswith(f"{PROSA}\n\n")
    assert PROSA not in segunda
    assert PROSA not in terceira


async def test_pergunta_no_turno_adia_as_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D4. Candidatos nao-vazios NAO significam que o agente quis apresentar.

    Com `perguntou` preenchido, a prosa sai como texto e as fichas esperam o
    proximo turno -- senao o lead recebe tres fotos e uma pergunta sobre zona
    no mesmo turno, que e a parede que a RN-04.2 existe para evitar.
    """
    identificador = await _imovel(session, "AP-001", 50000000)
    classificador = _ClassificadorComCandidatos(
        [_candidato(identificador, 50000000)], perguntou=("regiao",)
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [PROSA]
    assert await _kinds_reservados() == ["reply"]


async def test_ficha_ja_reservada_nao_reentrega_e_as_outras_entram(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D9. A idempotencia por posicao: a retentativa nao duplica a ficha_1.

    Sem os kinds fixos por posicao, a segunda tentativa mandaria a primeira
    imagem de novo -- e o criterio de aceite da TEC-134 proibe resposta
    duplicada.
    """
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    # Reserva a ficha_1 a mao, simulando a tentativa anterior que ja entregou.
    linha = (
        await session.execute(select(Message).where(Message.role == MessageRole.LEAD))
    ).scalars().first()
    if linha is None:
        # `rodar_turno` semeia a entrada; aqui precisamos dela ANTES do turno,
        # entao o teste roda o turno uma vez e inspeciona a segunda.
        pass

    primeiro = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )
    assert primeiro == "respondido"
    assert len(outbound.entregues) == 3


async def test_recusa_permanente_numa_ficha_nao_cala_as_outras(
    session: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D10. A recusa mais provavel aqui e a Meta rejeitando a URL da midia, e
    as URLs do catalogo sao o campo mais fragil que temos. Uma foto ruim nao
    pode apagar dois imoveis bons.
    """
    # `from conftest import ...` e nao `from tests.conftest import ...`: o
    # conftest da raiz e importavel direto, e e assim que
    # `test_busca_no_turno.py` importa o `EmbedadorFake`.
    from conftest import OutboundFake  # type: ignore[import-not-found]

    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )

    class _RecusaASegunda(OutboundFake):
        async def _deliver(self, message_id, kind, payload) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            await super()._deliver(message_id, kind, payload)

    outbound = _RecusaASegunda(get_sessionmaker())

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 2


async def test_a_linha_do_tempo_grava_as_tres_legendas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D16. O que se grava e o que o lead recebeu.

    Gravar so a prosa faria o turno seguinte reapresentar os mesmos tres
    imoveis por nao saber que ja os mostrou.
    """
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    gravado = await _texto_gravado()
    for legenda in outbound.entregues:
        assert legenda in gravado


async def test_imovel_sem_foto_sai_como_texto(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D13, quarto cenario do Gherkin: a ausencia de imagem nao esconde o
    imovel."""
    identificador = await _imovel(session, "AP-001", 50000000, fotos=[])
    classificador = _ClassificadorComCandidatos([_candidato(identificador, 50000000)])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    (entregue,) = outbound.entregues
    assert "Apartamento AP-001" in entregue
```

O teste `test_ficha_ja_reservada_nao_reentrega_e_as_outras_entram` está escrito com um bloco morto de propósito: **descubra na Step 2 se `rodar_turno` deixa a linha do lead acessível antes do turno.** Se não deixar, reescreva o teste para rodar `executar_turno` duas vezes sobre a MESMA `Message` (chamando `executar_turno` direto em vez de `rodar_turno`, com a linha semeada por `_entrada_do_lead`) e afirmar que a segunda execução entrega zero e mantém os três kinds. Não deixe o bloco morto no commit.

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py -v --tb=short
```

Esperado: `ImportError: cannot import name 'KINDS_DAS_FICHAS'`. Resolva o pendente do teste de reentrega antes de seguir.

- [ ] **Step 3: Acrescente as constantes no topo de `turno.py`**

Logo abaixo de `KIND_DA_RESPOSTA = "reply"` (linha 47):

```python
# TEC-162. Kinds fixos POR POSICAO, e nao derivados do id do imovel: o
# UNIQUE (message_id, kind) de `outbound_dispatches` precisa de um valor que
# a retentativa reproduza. Um kind com o id dentro deixaria de colidir assim
# que a retentativa escolhesse outro imovel, e a idempotencia sumiria
# justamente no caso em que ela importa -- ver a D9 e a L1 do desenho.
KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")

# RN-10.2: maximo de 3 por turno, mesmo quando a busca devolveu 10.
MAX_IMOVEIS_POR_TURNO = len(KINDS_DAS_FICHAS)
```

E aos imports:

```python
from mobia.domain.agente.apresentacao import legenda_de
from mobia.domain.agente.ferramenta_de_busca import fichas_do_catalogo
```

- [ ] **Step 4: Escreva o helper ao final de `turno.py`**

```python
async def _apresentar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    candidatos: list[dict[str, Any]],
    prosa: str,
) -> tuple[str, int, int]:
    """Entrega ate 3 fichas e devolve (texto para gravar, entregues, suprimidas).

    O texto devolvido sao as legendas concatenadas -- o que o lead recebeu, e
    nao a prosa sozinha. Gravar so a prosa faria o turno seguinte reapresentar
    os mesmos imoveis por nao saber que ja os mostrou (D16).

    **Recusa permanente numa ficha nao interrompe as outras**, e a divergencia
    do caminho de texto unico e deliberada: a recusa provavel aqui e a Meta
    rejeitando a URL da midia, e uma foto ruim nao pode apagar dois imoveis
    bons (D10). `EnvioForaDaJanela` propaga, porque nesse caso a apresentacao
    inteira e impossivel e o desfecho e o mesmo de hoje.
    """
    escolhidos = candidatos[:MAX_IMOVEIS_POR_TURNO]
    ids = [uuid.UUID(c["imovel_id"]) for c in escolhidos]
    precos = {uuid.UUID(c["imovel_id"]): int(c["preco_centavos"]) for c in escolhidos}
    fichas = await fichas_do_catalogo(session_factory, ids=ids, precos=precos)

    legendas: list[str] = []
    entregues = suprimidas = 0
    for posicao, ficha in enumerate(fichas):
        # So a primeira leva a prosa (D5); as outras sao ficha pura.
        legenda = legenda_de(ficha, prefixo=prosa if posicao == 0 else None)
        payload: dict[str, Any] = {
            "para": message.conversation_key,
            "de": message.recipient_external_id,
        }
        if ficha.foto is None:
            # D13: sem foto, cai no caminho de texto que ja existe em vez de
            # ganhar um ramo proprio.
            payload["texto"] = legenda
        else:
            payload["tipo"] = "imagem"
            payload["link"] = ficha.foto
            payload["legenda"] = legenda

        try:
            entrou = await outbound.send(message.id, KINDS_DAS_FICHAS[posicao], payload)
        except EnvioRecusado as exc:
            # `error` pelo mesmo criterio do caminho de texto: o estado da
            # linha sera terminal e a visibilidade vem do nivel do log.
            log.error(
                "apresentacao.ficha_recusada",
                channel=message.channel,
                message_id=str(message.id),
                kind=KINDS_DAS_FICHAS[posicao],
                reason=str(exc),
            )
            continue

        if not entrou:
            suprimidas += 1
            continue

        entregues += 1
        legendas.append(legenda)

    return "\n\n".join(legendas), entregues, suprimidas
```

- [ ] **Step 5: Ligue o desvio dentro de `executar_turno`**

Substitua o bloco que hoje começa em `try:` / `entregue = await outbound.send(` (linha 542) pelo desvio. A moderação de saída acima **não muda**: ela roda sobre `texto`, que é a prosa, e a ficha é dado do banco montado por código.

```python
    # TEC-162, D4. Candidatos sem pergunta e turno de apresentacao. As tres
    # condicoes sao a mesma regra: pergunta adia as fichas. `desambiguando`
    # entra porque `gerada.perguntou` fala da chamada 1, que foi DESCARTADA
    # nesse caminho -- o texto entregue e a pergunta do desambiguador.
    apresentando = bool(gerada.candidatos) and not gerada.perguntou and not desambiguando

    try:
        if apresentando:
            # `prosa=texto` le o valor ANTES da atribuicao: a chamada e
            # avaliada primeiro, e o `texto` que sai sao as legendas
            # concatenadas (D16).
            texto, quantas, suprimidas = await _apresentar(
                session_factory,
                message=message,
                outbound=outbound,
                candidatos=gerada.candidatos,
                prosa=texto,
            )
            entregue = quantas > 0
            # Nenhuma ficha entrou e TODAS foram suprimidas pela reserva: e o
            # mesmo caso do `not entregue` do caminho de texto -- reentrega de
            # uma tentativa anterior --, e o desfecho tem de ser o mesmo.
            if not entregue and suprimidas == 0:
                # Todas foram recusadas permanentemente. Cada uma ja logou
                # `error` em `_apresentar`.
                return "sem_resposta"
        else:
            entregue = await outbound.send(
                message.id,
                KIND_DA_RESPOSTA,
                {
                    "para": message.conversation_key,
                    "de": message.recipient_external_id,
                    "texto": texto,
                },
            )
    except EnvioForaDaJanela as exc:
```

O resto do `try/except` e o bloco `if not entregue:` continuam como estão — o caminho de reentrega suprimida e o de opt-out concorrente passam a servir os dois casos, e é isso que se quer.

- [ ] **Step 6: Rode os testes novos e os do turno**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_busca_no_turno.py -v --tb=short
```

Esperado: tudo passa. Depois, a vizinhança que o desvio pode ter quebrado — são os arquivos que exercitam `executar_turno`:

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py tests/integration/test_turno_optout.py tests/integration/test_moderacao_de_saida.py tests/integration/test_extracao_no_turno.py tests/integration/test_temperatura_no_turno.py -v --tb=short
```

Se algum falhar com `ConnectionResetError` ou erro de Redis, **rode o arquivo sozinho antes de culpar a mudança** — `CLAUDE.md` documenta esse flake sob carga.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_apresentacao_no_turno.py
git commit -m "feat(TEC-162): o turno apresenta tres fichas quando nao perguntou nada"
```

---

### Task 6: O seed exercita o imóvel sem foto

**Files:**
- Modify: `data/seed/imoveis.csv`
- Test: `tests/unit/test_base_simulada.py`

**Interfaces:**
- Consumes: nada.
- Produces: nada em código. Produz observabilidade: o caminho de texto da D13 passa a existir na base simulada.

- [ ] **Step 1: Escreva o teste que falha**

Em `tests/unit/test_base_simulada.py`, acrescente ao final. O molde é `test_os_seis_tipos_aparecem_na_base`, que a TEC-262 escreveu pelo mesmo motivo — a correção precisava ser observável na base.

```python
def test_ha_imovel_sem_foto_na_base():
    """TEC-162, D15. A RN-10.2 manda apresentar o imovel sem foto de todo
    jeito, com os dados textuais -- e nas 520 linhas de antes desta card
    TODAS tinham foto, entao esse caminho era invisivel fora do teste
    unitario. Uma demonstracao manual nunca o exercitaria.
    """
    sem_foto = [r for r in _itens() if not r.fotos]
    assert sem_foto, "nenhum imovel sem foto: o caminho de texto da RN-10.2 fica invisivel"
```

Confirme o nome do atributo lendo `RegistroImovel` em `src/mobia/domain/catalogo/schemas.py` — é `fotos: tuple[str, ...]`.

- [ ] **Step 2: Rode para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_base_simulada.py -v --tb=short
```

Esperado: `test_ha_imovel_sem_foto_na_base` falha — todas as 520 linhas têm foto.

- [ ] **Step 3: Esvazie a coluna `fotos` de duas linhas**

Não acrescente linhas novas: esvaziar a coluna de duas existentes mantém a contagem, os códigos únicos e a distribuição que os outros testes do arquivo verificam. Escolha duas linhas de tipos diferentes, para o caminho não ficar amarrado a um tipo só.

```bash
./.venv/Scripts/python.exe - <<'PY'
import csv, io

CAMINHO = "data/seed/imoveis.csv"
with io.open(CAMINHO, encoding="utf-8", newline="") as f:
    leitor = csv.DictReader(f)
    campos = leitor.fieldnames
    linhas = list(leitor)

# Duas de tipos diferentes, para o caminho de texto nao ficar amarrado a um
# tipo so. TEC-162 D15.
alvos = []
tipos_vistos = set()
for linha in linhas:
    if linha["tipo"] not in tipos_vistos and linha["fotos"]:
        alvos.append(linha["codigo"])
        tipos_vistos.add(linha["tipo"])
    if len(alvos) == 2:
        break

for linha in linhas:
    if linha["codigo"] in alvos:
        linha["fotos"] = ""

with io.open(CAMINHO, "w", encoding="utf-8", newline="") as f:
    escritor = csv.DictWriter(f, fieldnames=campos)
    escritor.writeheader()
    escritor.writerows(linhas)

print("sem foto agora:", alvos)
PY
```

Anote os dois códigos impressos — eles entram na mensagem do commit.

- [ ] **Step 4: Rode o arquivo inteiro, não só o teste novo**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_base_simulada.py tests/unit/test_catalogo_parser.py -v --tb=short
```

Esperado: tudo passa, incluindo `test_nenhuma_linha_e_rejeitada` e `test_distribuicao_e_realista`. Se `test_nenhuma_linha_e_rejeitada` falhar, o script reescreveu o CSV com quoting diferente do original — verifique com `git diff --stat data/seed/imoveis.csv` que só duas células mudaram.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add data/seed/imoveis.csv tests/unit/test_base_simulada.py
git commit -m "test(TEC-162): a base simulada tem imovel sem foto para o caminho de texto existir"
```

---

### Task 7: As duas emendas no SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` — RN-04.2 (perto da linha 155) e RN-10.2 (perto da linha 283)

**Interfaces:** nenhuma; é documentação normativa.

- [ ] **Step 1: Emende a RN-04.2**

Como item aninhado **abaixo** da regra, sem reescrever o texto de 22/08/2026 e depois da E-01 que já existe ali. Prosa em `docs/` leva acento.

```markdown
  - **Emenda E-02 (TEC-162, 09/09/2026):** o teto de *"no máximo 2 mensagens consecutivas"* passa a valer para mensagens de **texto**. A apresentação de imóveis da RN-10.2 pode emitir até 3 mensagens de **mídia** por turno. A emenda E-01 acima declarou esta cláusula inalterada oito dias antes; o que mudou é que a RN-10.2 e a RN-04.2 se contradizem na prática, e a CA-10.1 desempata — ela pressupõe três imóveis apresentados (*"quando o lead responde 'gostei do segundo'"*), então baixar o teto de imóveis para 2 invalidaria um critério de aceite em vez de resolver o conflito. O teto existe contra parede de texto, e três fichas com foto não são isso. A cláusula dos 600 caracteres por mensagem continua inalterada e passa a ser respeitada por construção em `domain/agente/apresentacao.py`.
```

- [ ] **Step 2: Emende a RN-10.2**

```markdown
  - **Emenda E-01 (TEC-162, 09/09/2026):** o *"card clicável"* no widget web fica com a TEC-124, que é quem traz o canal. Na data desta emenda o widget não existe — `channel` conhece `wa` e `eval` — e desenhar o formato do card sem widget contra o qual validá-lo seria palpite sem consumidor. A TEC-162 entrega a ficha agnóstica de canal e o renderizador do WhatsApp; a TEC-124 escreve o renderizador de card contra a ficha que já existirá. A cláusula do *"máximo de 3 por turno"* continua inalterada.
```

- [ ] **Step 3: Confirme que nada foi reescrito**

```bash
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md
```

Esperado: **apenas linhas acrescentadas**, nenhuma modificada. Se o diff mostrar `-` numa linha que não seja você reindentando sua própria adição, você reescreveu a spec — desfaça.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-162): a RN-04.2 tira midia do teto e a RN-10.2 manda o card web para a TEC-124"
```

---

### Task 8: A prova de que o prompt não mudou, e a suíte contra o baseline

**Files:** nenhum. Esta tarefa produz evidência, e o desenho inteiro se apoia nela.

- [ ] **Step 1: A margem do orçamento continua 6,0**

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Esperado: PASS, com a subcontagem impressa mostrando **líquido 780,0 e margem 6,0** — os mesmos números da TEC-265.

Se o número tiver mudado, alguma tarefa tocou `SISTEMA_DO_AGENTE`, `FERRAMENTA_DE_BUSCA` ou o schema de saída, e o desenho da D3 foi violado. **Não suba o teto.** Ache o que entrou e tire.

- [ ] **Step 2: Os três gates, no escopo exato do CI**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 3: A suíte inteira, comparada contra o baseline**

```bash
git rev-parse --short HEAD
./.venv/Scripts/python.exe -u -m pytest --tb=short 2>&1 | tee /tmp/suite-tec-162.txt | tail -40
```

São ~22 a 31 minutos numa máquina ociosa, e mais sob carga. Saída vazia por dez minutos é normal; não é deadlock.

**Baseline em `04b1c6a`:** 1336 passed, 2 failed, 3 errors. Os testes que falharam foram `test_dedup_por_message_id.py` (2 failed, 1 error) e `test_classificador.py` (2 errors de setup), todos com `ConnectionResetError` / `OSError` / `redis.exceptions.ConnectionError`.

Critério: os `passed` sobem pelos ~22 testes novos, e nenhuma falha nova aparece **fora** da família WinError 64. Guarde o hash junto com o resultado.

- [ ] **Step 4: Rode isolado qualquer arquivo que falhar**

```bash
./.venv/Scripts/python.exe -m pytest <arquivo que falhou> --tb=short
```

Passar isolado ajuda mas **não prova** — um teste pode passar sozinho e falhar junto por defeito real de isolamento. O que descarta regressão é a mesma árvore dando dois resultados: se o arquivo falhar isolado com traceback de rede, rode a versão anterior (`git stash`) o mesmo número de vezes antes de culpar a card.

- [ ] **Step 5: Registre o escopo no Jira**

Comentário na [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162), sem editar a descrição da card:

> O terceiro cenário do Gherkin (card clicável no widget web) fica fora de escopo desta card: o widget é a TEC-124 e não existe na data da implementação. Emenda E-01 registrada na RN-10.2 do SRS. Os outros três cenários foram entregues.

- [ ] **Step 6: Abra o PR**

```bash
git push -u origin feat/tec-162-ficha-por-canal
gh pr create --base main --title "feat(TEC-162): ficha estruturada por canal" --body "<resumo com os numeros da suite e a margem do orcamento>"
```

---

## Auto-revisão deste plano

**Cobertura do desenho, decisão por decisão:** D1 → Task 2 (ficha agnóstica, um renderizador) e Task 7. D2 → Task 7. D3 → Task 2 e Task 8 Step 1. D4 → Task 5 Steps 1 e 5. D5 → Task 2 e Task 5. D6 → Task 3 e Task 4. D7 → Task 4 Step 1 (`test_o_preco_vem_do_candidato_e_nao_da_coluna`). D8 → Task 1. D9 → Task 5 Step 3. D10 → Task 5 Step 4. D11 → Task 2. D12 → Global Constraints e Task 2. D13 → Task 2, Task 4, Task 5 e Task 6. D14 → Task 2. D15 → Task 6. D16 → Task 5 Steps 4 e 1.

**Lacunas do desenho, cobertas ou declaradas:** L1 (conjunto misturado) fica declarada no comentário de `KINDS_DAS_FICHAS`, sem código. L2, L3 e L4 não geram tarefa — são consequências aceitas. L5 gera o critério de aceite da Task 8 Step 3.

**Uma pendência conhecida, deliberada:** o `test_ficha_ja_reservada_nao_reentrega_e_as_outras_entram` da Task 5 depende de o `rodar_turno` do conftest expor a linha do lead antes do turno, e o plano manda descobrir isso na Step 2 e reescrever o teste em vez de fingir que já sabe. É a única coisa no plano que o implementador tem de resolver lendo o código.
