# TEC-175 — Resumo inteligente em seis blocos: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Todo handoff criado ganha, em segundos e fora da transação do turno, um resumo de seis blocos escrito pelo modelo a partir de fatos que vieram só do banco.

**Architecture:** Um dossiê determinístico é montado em Python a partir de quatro tabelas e é a **única** entrada do modelo (RN-15.3 como arquitetura, não como instrução de prompt). Um job ARQ, enfileirado depois do commit que cria o handoff, chama o redator e grava o resumo cifrado em `handoffs.resumo`. Uma rota de admin regenera sob demanda.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, ARQ, FastAPI, Anthropic SDK, pytest.

**Spec:** [`docs/superpowers/specs/2026-09-12-tec-175-resumo-em-seis-blocos-design.md`](../specs/2026-09-12-tec-175-resumo-em-seis-blocos-design.md)

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter.
- **Os três gates estáticos, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  O formatador é gate separado do linter: passar num não diz nada sobre o outro.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4 s, 1027 testes, sem Docker, sem `-n`).
- **Suíte inteira:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`. Rodar **uma** vez; a segunda execução é ferramenta de diagnóstico só quando a primeira falha.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-175): o que passou a ser verdade`. Terminar com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Limite do resumo: 1.500 caracteres** (RN-15.2). **Seis blocos, nesta ordem** (RN-15.1): quem é o lead e como chegou; o que procura; score, temperatura e justificativa; imóveis apresentados e reações; objeções e pontos de atenção; próxima ação com prazo.
- **Nada de conteúdo de lead em log.** O precedente é `tests/unit/test_resumo.py`, que usa sentinelas e reprova se elas aparecerem em `caplog.text`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/handoff/dossie.py` | **Criar.** Puro, sem I/O: os dataclasses do dossiê e a renderização dele em texto. |
| `src/mobia/domain/handoff/resumo.py` | **Criar.** Os seis marcadores, o validador, o `RedatorPort` e o `RedatorAnthropic`. |
| `src/mobia/domain/handoff/geracao.py` | **Criar.** A orquestração: carrega, renderiza, redige, valida, grava. |
| `src/mobia/domain/handoff/agendador.py` | **Criar.** O `AgendadorDeResumoPort`, o no-op e a implementação ARQ. |
| `src/mobia/domain/handoff/repositorio.py` | **Modificar.** `registrar_handoff` devolve id; entram `carregar_dossie` e `gravar_resumo`. |
| `src/mobia/domain/handoff/models.py` | **Modificar.** As três colunas novas. |
| `alembic/versions/0024_resumo_do_handoff.py` | **Criar.** A migration. |
| `src/mobia/workers/jobs/gerar_resumo.py` | **Criar.** O job ARQ. |
| `src/mobia/workers/main.py` | **Modificar.** Registrar o job e o agendador no ctx. |
| `src/mobia/domain/agente/turno.py` | **Modificar.** Recebe o agendador; enfileira nos dois pontos pós-commit. |
| `src/mobia/workers/jobs/process_message.py` | **Modificar.** Enfileira no ponto pós-commit do erro, sem levantar. |
| `src/mobia/api/routes/handoffs.py` | **Criar.** A rota de regeneração. |
| `src/mobia/app/main.py` | **Modificar.** Registrar o router. |
| `src/mobia/app/config.py` | **Modificar.** `dashboard_base_url`. |

---

### Task 1: O dossiê, puro e sem I/O

**Files:**
- Create: `src/mobia/domain/handoff/dossie.py`
- Test: `tests/unit/test_handoff_dossie.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Dossie`, `ImovelApresentado`, `renderizar(dossie: Dossie) -> str`, `reais(centavos: int | None) -> str`. **Não** há função de montagem aqui: quem lê as quatro tabelas e constrói o `Dossie` é `carregar_dossie`, na Task 6 — este módulo fica puro, como a docstring dele promete.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_handoff_dossie.py
from datetime import UTC, datetime

from mobia.domain.handoff.dossie import Dossie, ImovelApresentado, reais, renderizar

QUANDO = datetime(2026, 9, 12, 14, 30, tzinfo=UTC)


def _dossie(**trocas: object) -> Dossie:
    base: dict[str, object] = {
        "canal": "whatsapp",
        "conversa": "5511911112222",
        "primeira_mensagem_em": QUANDO,
        "mensagens_do_lead": 12,
        "intencao": "COMPRAR",
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
        "imoveis": (
            ImovelApresentado("AP-001", 58_000_000, "GOSTOU", None),
            ImovelApresentado("AP-002", 59_500_000, "DESCARTOU", "PRECO"),
            ImovelApresentado("AP-003", 55_000_000, None, None),
        ),
        "campos_recusados": ("renda",),
        "perguntados_sem_resposta": ("prazo",),
        "gatilho": "LEAD_QUENTE",
        "etiqueta": "lead-quente",
        "prioridade": "NORMAL",
        "criado_em": QUANDO,
    }
    return Dossie(**(base | trocas))  # type: ignore[arg-type]


def test_reais_formata_centavos_em_moeda_brasileira() -> None:
    assert reais(60_000_000) == "R$ 600.000"
    assert reais(0) == "R$ 0"
    assert reais(None) == "nao informado"


def test_renderizar_cita_os_numeros_do_banco() -> None:
    texto = renderizar(_dossie())

    assert "72" in texto
    assert "R$ 600.000" in texto
    assert "3 imoveis apresentados" in texto


def test_renderizar_nao_inventa_quando_o_campo_e_nulo() -> None:
    texto = renderizar(_dossie(regiao=None, quartos=None, score_total=None))

    assert "nao informado" in texto
    # O numero que nao existe nao pode aparecer inventado como zero.
    assert "score 0" not in texto


def test_renderizar_lista_os_pontos_de_atencao_estruturados() -> None:
    texto = renderizar(_dossie())

    assert "renda" in texto
    assert "prazo" in texto
    assert "PRECO" in texto


def test_renderizar_sem_pontos_de_atencao_diz_que_nao_ha() -> None:
    texto = renderizar(
        _dossie(
            campos_recusados=(),
            perguntados_sem_resposta=(),
            imoveis=(ImovelApresentado("AP-001", 58_000_000, "GOSTOU", None),),
        )
    )

    assert "nenhum ponto de atencao registrado" in texto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_dossie.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.dossie'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mobia/domain/handoff/dossie.py
"""Os fatos do lead, montados do banco e so do banco.

TEC-175, RN-15.1 e RN-15.3. Modulo sem I/O de proposito, no molde de
`vocabulario.py` e de `context/auditoria.py`: quem le do banco e o
repositorio; aqui so se decide o que vira texto.

**O modelo nunca ve o banco -- ele ve o que sai daqui.** A RN-15.3 manda todo
dado factual vir do estado estruturado, e este modulo e essa regra em forma
de arquitetura em vez de instrucao no prompt: o que nao entra no dossie o
modelo nao tem como citar. Instruir o modelo a nao inventar dependeria de ele
obedecer; isto nao depende.

O bloco (e) da RN-15.1 sai daqui mais magro que a regra promete, e e a emenda
E-01 dela que registra o porque: nao ha entidade Objecao neste sistema, entao
o bloco se monta de campos recusados, perguntas sem resposta e motivos de
descarte -- que sao pontos de atencao verdadeiros, mas nao sao a objecao que
o lead argumentou.
"""

from dataclasses import dataclass
from datetime import datetime

# O que se escreve onde o banco nao tem valor. Uma string so, e nao "" ou
# "None" espalhados: e ela que impede o modelo de ler a ausencia como zero --
# um lead sem score nunca teve score 0, do mesmo jeito que `lead_score_audit`
# guarda `total_anterior` nulo e nao zero no primeiro calculo.
AUSENTE = "nao informado"


@dataclass(frozen=True)
class ImovelApresentado:
    """Uma linha de `recomendacoes`, reduzida ao que o corretor precisa ver."""

    codigo: str
    preco_centavos: int
    reacao: str | None
    motivo_descarte: str | None


@dataclass(frozen=True)
class Dossie:
    """Tudo o que o modelo vai ver, e nada alem disso."""

    # (a) quem e o lead e como chegou. Sem nome: nenhuma tabela deste sistema
    # guarda um -- ver a emenda E-02 da RN-15.1 e a L1 do desenho.
    canal: str
    conversa: str
    primeira_mensagem_em: datetime
    mensagens_do_lead: int

    # (b) o que procura.
    intencao: str | None
    faixa_min_centavos: int | None
    faixa_max_centavos: int | None
    regiao: str | None
    tipo_imovel: str | None
    quartos: int | None
    vagas: int | None
    urgencia: str | None
    forma_pagamento: str | None
    tem_imovel_para_vender: bool | None

    # (c) score, temperatura e justificativa.
    score_total: int | None
    score_fatores: tuple[tuple[str, int], ...]
    score_causas: tuple[str, ...]
    temperatura: str | None
    temperatura_forcada_motivos: tuple[str, ...]

    # (d) imoveis apresentados e reacoes.
    imoveis: tuple[ImovelApresentado, ...]

    # (e) pontos de atencao. Ver o cabecalho do modulo.
    campos_recusados: tuple[str, ...]
    perguntados_sem_resposta: tuple[str, ...]

    # (f) proxima acao: o que o gatilho e a prioridade ja dizem.
    gatilho: str
    etiqueta: str
    prioridade: str
    criado_em: datetime


def reais(centavos: int | None) -> str:
    """Centavos em moeda brasileira, sem centavos na saida.

    O repo nao tinha formatador: `dinheiro.py` so parseia o que o lead
    escreve. Este e o caminho de volta, e vive aqui porque so o dossie
    precisa dele.

    Sem casas decimais porque preco de imovel nao as tem na pratica e elas so
    gastariam caracteres do orcamento de 1.500 da RN-15.2.
    """
    if centavos is None:
        return AUSENTE
    return f"R$ {centavos // 100:,}".replace(",", ".")


def _sim_nao(valor: bool | None) -> str:
    if valor is None:
        return AUSENTE
    return "sim" if valor else "nao"


def _ou_ausente(valor: object | None) -> str:
    return AUSENTE if valor is None else str(valor)


def _faixa(dossie: Dossie) -> str:
    """A faixa como o lead a declarou, e nao um intervalo inventado.

    Minimo ausente com maximo presente e o caso comum ("ate 600 mil"), e
    escrever "de R$ 0 ate R$ 600.000" pareceria um piso que o lead nunca deu.
    """
    minimo, maximo = dossie.faixa_min_centavos, dossie.faixa_max_centavos
    if minimo is None and maximo is None:
        return AUSENTE
    if minimo is None:
        return f"ate {reais(maximo)}"
    if maximo is None:
        return f"a partir de {reais(minimo)}"
    return f"de {reais(minimo)} ate {reais(maximo)}"


def _imoveis(dossie: Dossie) -> str:
    if not dossie.imoveis:
        return "nenhum imovel apresentado ainda"

    linhas = [f"{len(dossie.imoveis)} imoveis apresentados:"]
    for imovel in dossie.imoveis:
        reacao = imovel.reacao or "sem reacao ate agora"
        descarte = f", motivo {imovel.motivo_descarte}" if imovel.motivo_descarte else ""
        linhas.append(f"- {imovel.codigo}, {reais(imovel.preco_centavos)}: {reacao}{descarte}")
    return "\n".join(linhas)


def _pontos_de_atencao(dossie: Dossie) -> str:
    """O bloco (e), montado do que existe. Ver o cabecalho do modulo."""
    partes = []
    if dossie.campos_recusados:
        partes.append(f"recusou informar: {', '.join(dossie.campos_recusados)}")
    if dossie.perguntados_sem_resposta:
        partes.append(f"perguntado e sem resposta: {', '.join(dossie.perguntados_sem_resposta)}")

    descartes = sorted({i.motivo_descarte for i in dossie.imoveis if i.motivo_descarte})
    if descartes:
        partes.append(f"motivos de descarte de imovel: {', '.join(descartes)}")

    if not partes:
        return "nenhum ponto de atencao registrado"
    return "\n".join(f"- {parte}" for parte in partes)


def _fatores(dossie: Dossie) -> str:
    if not dossie.score_fatores:
        return AUSENTE
    return ", ".join(f"{nome} {valor}" for nome, valor in dossie.score_fatores)


def renderizar(dossie: Dossie) -> str:
    """O dossie em texto, que e tudo o que o modelo recebe.

    Rotulado campo a campo e nao em prosa: o modelo precisa distinguir um
    valor ausente de um valor zero, e prosa corrida apaga essa diferenca --
    que e exatamente o erro que a RN-15.3 existe para impedir.
    """
    forcada = (
        f" (forcada por {', '.join(dossie.temperatura_forcada_motivos)})"
        if dossie.temperatura_forcada_motivos
        else ""
    )
    return "\n".join(
        (
            "ORIGEM",
            f"canal: {dossie.canal}",
            f"chave da conversa: {dossie.conversa}",
            f"primeira mensagem: {dossie.primeira_mensagem_em.isoformat()}",
            f"mensagens do lead: {dossie.mensagens_do_lead}",
            "",
            "CRITERIOS",
            f"intencao: {_ou_ausente(dossie.intencao)}",
            f"faixa de preco: {_faixa(dossie)}",
            f"regiao: {_ou_ausente(dossie.regiao)}",
            f"tipo de imovel: {_ou_ausente(dossie.tipo_imovel)}",
            f"quartos: {_ou_ausente(dossie.quartos)}",
            f"vagas: {_ou_ausente(dossie.vagas)}",
            f"urgencia: {_ou_ausente(dossie.urgencia)}",
            f"forma de pagamento: {_ou_ausente(dossie.forma_pagamento)}",
            f"tem imovel para vender: {_sim_nao(dossie.tem_imovel_para_vender)}",
            "",
            "SCORE",
            f"total: {_ou_ausente(dossie.score_total)}",
            f"fatores: {_fatores(dossie)}",
            f"ultimo recalculo por: {', '.join(dossie.score_causas) or AUSENTE}",
            f"temperatura: {_ou_ausente(dossie.temperatura)}{forcada}",
            "",
            "IMOVEIS",
            _imoveis(dossie),
            "",
            "PONTOS DE ATENCAO",
            _pontos_de_atencao(dossie),
            "",
            "HANDOFF",
            f"gatilho: {dossie.gatilho}",
            f"etiqueta: {dossie.etiqueta}",
            f"prioridade: {dossie.prioridade}",
            f"criado em: {dossie.criado_em.isoformat()}",
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_dossie.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Run the static gates**

Run:
```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. Se o `format --check` reprovar, rode `ruff format src tests alembic evals scripts` e confira o diff antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/dossie.py tests/unit/test_handoff_dossie.py
git commit -m "feat(TEC-175): o dossie e a unica coisa que o modelo ve"
```

---

### Task 2: Os seis marcadores e o validador

**Files:**
- Create: `src/mobia/domain/handoff/resumo.py`
- Test: `tests/unit/test_handoff_resumo.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `MARCADORES: tuple[str, ...]`, `LIMITE_DE_CARACTERES: int`, `ResumoDeHandoffInvalido`, `validar(texto: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_handoff_resumo.py
import pytest

from mobia.domain.handoff.resumo import (
    LIMITE_DE_CARACTERES,
    MARCADORES,
    ResumoDeHandoffInvalido,
    validar,
)


def _resumo_valido(recheio: str = "texto do bloco") -> str:
    return "\n".join(f"{marcador}\n{recheio}" for marcador in MARCADORES)


def test_sao_seis_marcadores() -> None:
    assert len(MARCADORES) == 6


def test_validar_devolve_o_texto_quando_os_seis_blocos_estao_em_ordem() -> None:
    texto = _resumo_valido()
    assert validar(texto) == texto


def test_validar_recusa_quando_falta_um_bloco() -> None:
    texto = "\n".join(f"{m}\ntexto" for m in MARCADORES[:-1])

    with pytest.raises(ResumoDeHandoffInvalido, match="bloco ausente"):
        validar(texto)


def test_validar_recusa_quando_a_ordem_esta_trocada() -> None:
    trocados = (MARCADORES[1], MARCADORES[0], *MARCADORES[2:])
    texto = "\n".join(f"{m}\ntexto" for m in trocados)

    with pytest.raises(ResumoDeHandoffInvalido, match="fora de ordem"):
        validar(texto)


def test_validar_recusa_texto_vazio() -> None:
    with pytest.raises(ResumoDeHandoffInvalido, match="vazio"):
        validar("   \n  ")


def test_validar_recusa_acima_do_limite() -> None:
    excedente = _resumo_valido("x" * LIMITE_DE_CARACTERES)

    with pytest.raises(ResumoDeHandoffInvalido, match="acima do limite"):
        validar(excedente)


def test_o_limite_e_o_da_regra() -> None:
    # RN-15.2. Escrito aqui uma vez so; o resto do codigo importa a constante.
    assert LIMITE_DE_CARACTERES == 1500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_resumo.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.resumo'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mobia/domain/handoff/resumo.py
"""O resumo de handoff: os seis blocos, o validador e o redator.

TEC-175, RF-15.
"""

# RN-15.2. O numero mora aqui e so aqui -- quem precisa dele importa a
# constante, para nao existir uma segunda copia livre para divergir.
LIMITE_DE_CARACTERES = 1500

# Os seis blocos da RN-15.1, como marcadores LITERAIS e nao como instrucao em
# prosa. Sem marcador fixo, o primeiro cenario do Gherkin -- "contem os seis
# blocos na ordem definida" -- nao e testavel: vira opiniao sobre um texto
# corrido. O custo e um resumo com cara de formulario; o ganho e um criterio
# de aceite que e asercao, e nao leitura.
MARCADORES = (
    "## Quem e o lead",
    "## O que procura",
    "## Score e temperatura",
    "## Imoveis apresentados",
    "## Pontos de atencao",
    "## Proxima acao",
)


class ResumoDeHandoffInvalido(RuntimeError):
    """A resposta do modelo nao e um resumo utilizavel.

    Mesmo papel do `ResumoInvalido` de `context/resumo.py`: levantar aqui, em
    vez de gravar um resumo manco, e o que da ao chamador a chance de nao
    gravar nada. Um resumo truncado e pior que resumo nenhum -- ele corta o
    fim, e o fim e o bloco da proxima acao, que e o que diz ao corretor o que
    fazer. Ver a D7 do desenho.
    """


def validar(texto: str) -> str:
    """Devolve o texto quando ele e um resumo valido; levanta quando nao e.

    A ordem e conferida por posicao crescente e nao por presenca: seis blocos
    presentes fora de ordem satisfazem "contem os seis" e mesmo assim nao sao
    o que a RN-15.1 pede.
    """
    limpo = texto.strip()
    if not limpo:
        raise ResumoDeHandoffInvalido("resumo vazio ou so com espaco em branco")

    if len(limpo) > LIMITE_DE_CARACTERES:
        raise ResumoDeHandoffInvalido(
            f"resumo acima do limite: {len(limpo)} de {LIMITE_DE_CARACTERES} caracteres"
        )

    posicoes = []
    for marcador in MARCADORES:
        posicao = limpo.find(marcador)
        if posicao < 0:
            raise ResumoDeHandoffInvalido(f"bloco ausente: {marcador!r}")
        posicoes.append(posicao)

    if posicoes != sorted(posicoes):
        raise ResumoDeHandoffInvalido("blocos fora de ordem")

    return limpo
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_resumo.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/resumo.py tests/unit/test_handoff_resumo.py
git commit -m "feat(TEC-175): os seis blocos viram marcador literal, e o criterio vira asercao"
```

---

### Task 3: O redator, com uma tentativa de compressão

**Files:**
- Modify: `src/mobia/domain/handoff/resumo.py`
- Test: `tests/unit/test_handoff_redator.py`

**Interfaces:**
- Consumes: `LIMITE_DE_CARACTERES`, `MARCADORES`, `ResumoDeHandoffInvalido`, `validar` (Task 2).
- Produces: `ResumoDeHandoffGerado(texto, modelo, tokens_in, tokens_out, latency_ms, comprimiu)`, `RedatorPort` (Protocol com `async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado`), `RedatorAnthropic`, `INSTRUCAO_REDIGIR`, `INSTRUCAO_COMPRIMIR`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_handoff_redator.py
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mobia.domain.handoff import resumo as resumo_mod
from mobia.domain.handoff.resumo import (
    LIMITE_DE_CARACTERES,
    MARCADORES,
    RedatorAnthropic,
    ResumoDeHandoffInvalido,
)

# Se qualquer uma destas aparecer em caplog.text, o boundary vazou conteudo
# de lead ou o dossie que o gerou. Mesmo molde de tests/unit/test_resumo.py.
SENTINELA_DOSSIE = "SENTINELA-DOSSIE lead mora na Rua das Palmeiras"
SENTINELA_SAIDA = "SENTINELA-SAIDA o lead quer 2 quartos em Pinheiros"


def _resumo(recheio: str = "curto") -> str:
    return "\n".join(f"{marcador}\n{recheio}" for marcador in MARCADORES)


def _resposta(texto: str | None, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)] if texto else [],
        usage=SimpleNamespace(input_tokens=900, output_tokens=400),
        stop_reason=stop_reason,
    )


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic: so o que `redigir` toca."""

    def __init__(self, *respostas: SimpleNamespace) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(side_effect=list(respostas)))


def _instalar(monkeypatch: pytest.MonkeyPatch, *respostas: SimpleNamespace) -> _ClienteFalso:
    cliente = _ClienteFalso(*respostas)
    monkeypatch.setattr(resumo_mod, "get_client", lambda: cliente)
    return cliente


async def test_redigir_devolve_o_resumo_validado(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta(_resumo()))

    gerado = await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    assert MARCADORES[0] in gerado.texto
    assert gerado.comprimiu is False
    assert gerado.tokens_in == 900


async def test_estouro_do_limite_tenta_comprimir_uma_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    longo = _resumo("x" * LIMITE_DE_CARACTERES)
    cliente = _instalar(monkeypatch, _resposta(longo), _resposta(_resumo()))

    gerado = await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    assert gerado.comprimiu is True
    assert cliente.messages.create.await_count == 2


async def test_estouro_na_compressao_levanta_em_vez_de_truncar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    longo = _resumo("x" * LIMITE_DE_CARACTERES)
    cliente = _instalar(monkeypatch, _resposta(longo), _resposta(longo))

    with pytest.raises(ResumoDeHandoffInvalido, match="acima do limite"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    # Uma tentativa de compressao, nao um laco: duas chamadas ja estouram o
    # orcamento de 8s da RNF-05 no caso ruim.
    assert cliente.messages.create.await_count == 2


async def test_bloco_faltando_nao_e_recuperado_por_compressao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manco = "\n".join(f"{m}\ntexto" for m in MARCADORES[:-1])
    cliente = _instalar(monkeypatch, _resposta(manco))

    with pytest.raises(ResumoDeHandoffInvalido, match="bloco ausente"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    # Comprimir um resumo que ja perdeu um bloco nao o traz de volta.
    assert cliente.messages.create.await_count == 1


async def test_parada_anormal_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta(_resumo(), stop_reason="max_tokens"))

    with pytest.raises(ResumoDeHandoffInvalido, match="stop_reason"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")


async def test_log_carrega_metrica_e_nunca_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _instalar(monkeypatch, _resposta(_resumo(SENTINELA_SAIDA)))

    with caplog.at_level(logging.INFO):
        await RedatorAnthropic().redigir(SENTINELA_DOSSIE)

    assert "resumo_handoff.gerado" in caplog.text
    assert SENTINELA_DOSSIE not in caplog.text
    assert SENTINELA_SAIDA not in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_redator.py -v`
Expected: FAIL com `ImportError: cannot import name 'RedatorAnthropic'`

- [ ] **Step 3: Write minimal implementation**

Acrescentar ao topo de `src/mobia/domain/handoff/resumo.py`:

```python
import time
from dataclasses import dataclass
from typing import Protocol

import structlog

from mobia.app.config import get_settings
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)
```

E, depois de `validar`:

```python
# Folga sobre os 1.500 caracteres da RN-15.2: o modelo precisa de espaco para
# errar para cima e ainda ser corrigido pela compressao, mas nao tanto que uma
# resposta desgovernada custe uma eternidade antes de ser recusada.
MAX_TOKENS_DO_RESUMO = 1200

INSTRUCAO_REDIGIR = (
    "Voce escreve o resumo de um lead imobiliario para o corretor que vai assumir "
    "a conversa. Use EXATAMENTE os seis titulos abaixo, nesta ordem, cada um em "
    "sua propria linha:\n"
    + "\n".join(MARCADORES)
    + "\n\nEscreva em portugues, em terceira pessoa, direto ao ponto. "
    f"O texto inteiro deve caber em {LIMITE_DE_CARACTERES} caracteres.\n\n"
    "**Use apenas os dados do dossie abaixo.** Nao estime, nao arredonde, nao "
    "complete o que estiver como 'nao informado' -- escreva que nao foi "
    "informado. Todo numero que voce citar tem de aparecer literalmente no "
    "dossie."
)

INSTRUCAO_COMPRIMIR = (
    "O resumo abaixo passou do limite. Reescreva-o em no maximo "
    f"{LIMITE_DE_CARACTERES} caracteres, mantendo os seis titulos na mesma ordem "
    "e todo dado factual. Corte narrativa e transicao, nunca numero nem titulo."
)


@dataclass(frozen=True)
class ResumoDeHandoffGerado:
    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    comprimiu: bool


class RedatorPort(Protocol):
    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado: ...


class RedatorAnthropic:
    """Redige os seis blocos a partir do dossie, e so do dossie.

    Nao rebaixa o modelo, pelo mesmo argumento de `context/resumo.py`: e a
    partir deste texto que o corretor decide como entrar na conversa, e um
    resumo pobre custa o lead inteiro.
    """

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        comeco = time.monotonic()
        bruto, uso = await self._chamar(INSTRUCAO_REDIGIR, dossie_em_texto)

        comprimiu = False
        try:
            texto = validar(bruto)
        except ResumoDeHandoffInvalido as falha:
            # SO o estouro de tamanho tem segunda chance. Bloco ausente ou
            # fora de ordem nao e problema de tamanho, e comprimir um resumo
            # que ja perdeu um bloco nao o traz de volta -- so gastaria a
            # segunda chamada para falhar igual.
            if "acima do limite" not in str(falha):
                raise
            comprimiu = True
            bruto, uso_da_compressao = await self._chamar(INSTRUCAO_COMPRIMIR, bruto)
            uso = (uso[0] + uso_da_compressao[0], uso[1] + uso_da_compressao[1])
            texto = validar(bruto)

        gerado = ResumoDeHandoffGerado(
            texto=texto,
            modelo=get_settings().modelo_resumo,
            tokens_in=uso[0],
            tokens_out=uso[1],
            latency_ms=int((time.monotonic() - comeco) * 1000),
            comprimiu=comprimiu,
        )

        # `latency_ms` esta aqui porque e a UNICA medicao do p95 de 8s da
        # RNF-05 que este sistema produz: o terceiro cenario do Gherkin pede
        # 100 geracoes medidas em homologacao, e a suite exclui `-m perf` de
        # proposito. Ver a L2 do desenho. Nunca loga o dossie nem o texto.
        log.info(
            "resumo_handoff.gerado",
            modelo=gerado.modelo,
            tokens_in=gerado.tokens_in,
            tokens_out=gerado.tokens_out,
            latency_ms=gerado.latency_ms,
            comprimiu=gerado.comprimiu,
            caracteres=len(gerado.texto),
            custo_usd=str(custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)),
        )
        return gerado

    async def _chamar(self, instrucao: str, conteudo: str) -> tuple[str, tuple[int, int]]:
        resposta = await get_client().messages.create(
            model=get_settings().modelo_resumo,
            max_tokens=MAX_TOKENS_DO_RESUMO,
            system=instrucao,
            messages=[{"role": "user", "content": conteudo}],
        )
        # Mesma guarda de `context/resumo.py`, e pela mesma razao: `max_tokens`
        # corta a resposta no meio de uma frase e ela sai parecendo completa.
        # Checar antes de olhar o texto.
        if resposta.stop_reason != "end_turn":
            raise ResumoDeHandoffInvalido(
                f"resumo interrompido antes do fim: stop_reason={resposta.stop_reason!r}"
            )
        texto = "".join(b.text for b in resposta.content if b.type == "text")
        return texto, (resposta.usage.input_tokens, resposta.usage.output_tokens)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_redator.py tests/unit/test_handoff_resumo.py -v`
Expected: PASS (13 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/resumo.py tests/unit/test_handoff_redator.py
git commit -m "feat(TEC-175): o redator comprime uma vez e recusa em vez de truncar"
```

---

### Task 4: A migration e as três colunas

**Files:**
- Create: `alembic/versions/0024_resumo_do_handoff.py`
- Modify: `src/mobia/domain/handoff/models.py`
- Test: `tests/integration/test_handoff_schema.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Handoff.resumo: bytes | None`, `Handoff.resumo_gerado_em: datetime | None`, `Handoff.resumo_modelo: str | None`.

**Este task precisa dos containers de pé** (`docker compose up -d`). Depois de um `restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` **mesmo com o container marcado `healthy`** — espere e retente antes de diagnosticar qualquer coisa.

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_handoff_schema.py`:

```python
async def test_a_coluna_do_resumo_nasce_nulavel_e_binaria(session: AsyncSession) -> None:
    """Nulavel por construcao: a geracao e assincrona (D1 do desenho).

    Todo handoff existe por alguns segundos sem resumo, e NULL e o nome desse
    intervalo -- e tambem o estado em que ele fica quando a geracao falha, que
    e o que a TEC-176 vai ler.
    """
    linhas = (
        await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'handoffs' "
                "AND column_name IN ('resumo', 'resumo_gerado_em', 'resumo_modelo')"
            )
        )
    ).all()

    por_nome = {linha[0]: (linha[1], linha[2]) for linha in linhas}
    assert por_nome["resumo"] == ("bytea", "YES")
    assert por_nome["resumo_gerado_em"] == ("timestamp with time zone", "YES")
    assert por_nome["resumo_modelo"] == ("character varying", "YES")


async def test_o_resumo_recusa_texto_claro(session: AsyncSession) -> None:
    """Mesma guarda de `Message` e de `ConversationSummary`.

    O driver embute o argumento recusado na propria mensagem de excecao, antes
    de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
    """
    with pytest.raises(TypeError, match="apenas bytes cifrados"):
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            resumo="texto em claro",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -v --tb=short`
Expected: FAIL — `KeyError: 'resumo'` no primeiro teste.

- [ ] **Step 3: Write the migration**

```python
# alembic/versions/0024_resumo_do_handoff.py
"""o resumo em seis blocos, cifrado, ao lado do handoff que ele descreve

TEC-175, RF-15 e RN-15.1.

**Cifrada, ao contrario de `lead_qualification`.** O argumento e o do
`conversation_summaries` e vale palavra por palavra: um resumo destila as
mesmas frases que `messages.text_body` guarda, e deixa-lo em claro ao lado de
uma coluna cifrada seria manter a fechadura e tirar a porta. A assimetria com
`lead_qualification` -- que fica legivel -- se sustenta: aquela tabela e o que
o SISTEMA concluiu, e TEC-150 e TEC-158 a filtram em SQL. Ninguem filtra por
este texto.

**Nulavel, e isso nao contradiz a D1 da TEC-174.** O que aquela card recusou
foi coluna nulavel SEM escritor nenhum; esta tem o seu. A nulabilidade e
consequencia de a geracao ser assincrona: todo handoff existe por alguns
segundos sem resumo, e NULL e o nome desse intervalo. E tambem o estado em que
um handoff fica quando a geracao falha, que e o que a TEC-176 vai ler para
decidir o que entregar no lugar.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handoffs", sa.Column("resumo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "handoffs", sa.Column("resumo_gerado_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("handoffs", sa.Column("resumo_modelo", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("handoffs", "resumo_modelo")
    op.drop_column("handoffs", "resumo_gerado_em")
    op.drop_column("handoffs", "resumo")
```

- [ ] **Step 4: Add the columns to the model**

Em `src/mobia/domain/handoff/models.py`, acrescentar os imports `LargeBinary` e `validates`, e dentro de `Handoff`, antes de `criado_em`:

```python
    # Cifrado com AES-GCM, AAD de `aad_do_resumo_de_handoff`. Nulavel por
    # construcao: a geracao e assincrona (ver a D1 do desenho), entao todo
    # handoff existe por alguns segundos sem resumo -- e permanece sem quando
    # a geracao falha, que e o caso que a TEC-176 vai atender.
    resumo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    resumo_gerado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Qual modelo escreveu. Mesmo papel do `modelo` de `conversation_summaries`:
    # quando a saida piorar, e por ele que se descobre o que mudou.
    resumo_modelo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message` e de `ConversationSummary`.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor
```

E no topo do arquivo, a função de AAD:

```python
def aad_do_resumo_de_handoff(handoff_id: uuid.UUID) -> str:
    """Amarra o resumo ao handoff que ele descreve.

    Diferente do `aad_do_resumo` de `context/models.py`, que precisa compor o
    par `(channel, conversation_key)` e por isso prefixa cada parte pelo
    tamanho: aqui a identidade da linha e um UUID, que nao tem como colidir
    com outro por concatenacao ambigua. `aad_de` basta.
    """
    return aad_de(handoff_id, "resumo")
```

com `from mobia.infra.crypto import aad_de` no topo.

- [ ] **Step 5: Run the migration and the test**

Run:
```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -v --tb=short
```
Expected: PASS. Se o `upgrade` reprovar com `ConnectionResetError [WinError 64]`, espere e retente — ver a nota no topo do task.

- [ ] **Step 6: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos. **Atenção:** `alembic` está no escopo do `ruff format --check` — a migration nova passa pelo formatador.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/0024_resumo_do_handoff.py src/mobia/domain/handoff/models.py tests/integration/test_handoff_schema.py
git commit -m "feat(TEC-175): a coluna do resumo nasce cifrada e nulavel, com escritor a caminho"
```

---

### Task 5: `registrar_handoff` devolve o id

**Files:**
- Modify: `src/mobia/domain/handoff/repositorio.py`
- Modify: `src/mobia/domain/agente/turno.py:736-737,785-799,909`
- Modify: `src/mobia/workers/jobs/process_message.py:121`
- Test: `tests/integration/test_handoff_repositorio.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `HandoffRegistrado(id: uuid.UUID, criado: bool)`; `registrar_handoff(...) -> HandoffRegistrado`.

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/integration/test_handoff_repositorio.py`:

```python
async def test_registrar_devolve_o_id_da_linha_criada(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session, channel="whatsapp", conversation_key="5511911112222", gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()

    assert registro.criado is True
    gravado = (await session.execute(select(Handoff.id))).scalar_one()
    assert registro.id == gravado


async def test_o_gatilho_adicional_devolve_o_id_do_handoff_ABERTO(
    session: AsyncSession,
) -> None:
    """O id e o da linha que sobreviveu, nao o do INSERT que perdeu.

    O `ON CONFLICT DO UPDATE` gera um id novo no `values()` a cada chamada e o
    descarta quando cai no UPDATE. Devolver o descartado daria ao chamador um
    id que nao existe no banco -- e o job de resumo procuraria um handoff
    fantasma.
    """
    primeiro = await registrar_handoff(
        session, channel="whatsapp", conversation_key="5511911112222", gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()

    segundo = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911112222",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    assert segundo.criado is False
    assert segundo.id == primeiro.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_repositorio.py -v --tb=short`
Expected: FAIL com `AttributeError: 'bool' object has no attribute 'criado'`

- [ ] **Step 3: Change the return type**

Em `src/mobia/domain/handoff/repositorio.py`, acrescentar o dataclass e trocar o `.returning(...)` e o retorno:

```python
@dataclass(frozen=True)
class HandoffRegistrado:
    """O que `registrar_handoff` devolve.

    Dataclass e nao tupla porque os tres chamadores leem pelo nome, e porque
    `ResumoGerado` e `Score` ja estabeleceram a forma neste repo.

    `id` e sempre o da linha que EXISTE no banco depois do statement -- a
    recem-inserida quando `criado`, a que ja estava aberta quando nao. O
    `values()` calcula um uuid novo a cada chamada e o descarta no caminho do
    UPDATE; devolver aquele daria um id fantasma a quem chama.
    """

    id: uuid.UUID
    criado: bool
```

e, no `.returning(...)`:

```python
        ).returning(
            Handoff.id,
            # xmax e o sinal nativo do Postgres para distinguir INSERT de
            # UPDATE num ON CONFLICT: vale 0 na linha recem-inserida e
            # diferente de zero na que foi atualizada. NAO comparar carimbos
            # de tempo aqui -- `agora` e calculado em Python antes do
            # statement, e duas escritas concorrentes para a mesma conversa
            # podem calcular o MESMO valor. Nesse caso a chamada que fez
            # UPDATE bateria com o `criado_em` que a vencedora gravou e
            # devolveria True por coincidencia de relogio, nao por sinal do
            # banco -- exatamente a corrida que este statement existe para
            # arbitrar, so que agora no booleano de retorno em vez de na
            # linha.
            (literal_column("xmax") == 0).label("inseriu"),
        )
    )

    linha = resultado.one()
    return HandoffRegistrado(id=linha.id, criado=linha.inseriu)
```

com `from dataclasses import dataclass` no topo.

- [ ] **Step 4: Update the three call sites**

Em `src/mobia/domain/agente/turno.py`, trocar o tipo das duas variáveis (linhas ~736-737):

```python
    handoff_do_quente: HandoffRegistrado | None = None
    handoff_da_intencao: HandoffRegistrado | None = None
```

e os dois usos no log, de `if handoff_da_intencao` para `if handoff_da_intencao.criado` — atenção: a condição externa `is not None` permanece, só o booleano interno muda:

```python
            "handoff.criado" if handoff_da_intencao.criado else "handoff.gatilho_adicional",
```

```python
                "handoff.criado" if handoff_do_quente.criado else "handoff.gatilho_adicional",
```

com `from mobia.domain.handoff.repositorio import HandoffRegistrado, registrar_handoff`.

Em `src/mobia/workers/jobs/process_message.py`, a variável `criou` vira o registro:

```python
            registro = await registrar_handoff(
```

e o log:

```python
        "handoff.criado" if registro.criado else "handoff.gatilho_adicional",
```

- [ ] **Step 5: Run the affected tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_repositorio.py tests/integration/test_handoff_no_turno.py tests/integration/test_handoff_por_erro.py -v --tb=short`
Expected: PASS.

- [ ] **Step 6: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/handoff/repositorio.py src/mobia/domain/agente/turno.py src/mobia/workers/jobs/process_message.py tests/integration/test_handoff_repositorio.py
git commit -m "feat(TEC-175): registrar_handoff devolve o id da linha que existe, nao so o booleano"
```

---

### Task 6: Carregar o dossiê do banco e gravar o resumo

**Files:**
- Modify: `src/mobia/domain/handoff/repositorio.py`
- Test: `tests/integration/test_handoff_dossie_do_banco.py`

**Interfaces:**
- Consumes: `Dossie`, `ImovelApresentado` (Task 1); `Handoff.resumo*` (Task 4).
- Produces: `carregar_dossie(session, *, handoff_id: uuid.UUID) -> Dossie | None`, `gravar_resumo(session, *, handoff_id: uuid.UUID, texto: str, modelo: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_handoff_dossie_do_banco.py
"""O dossie montado a partir das quatro tabelas, e o resumo de volta cifrado."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.repositorio import (
    carregar_dossie,
    gravar_resumo,
    registrar_handoff,
)
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.infra.crypto import decrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def test_dossie_de_handoff_inexistente_e_none(session: AsyncSession) -> None:
    assert await carregar_dossie(session, handoff_id=uuid.uuid4()) is None


async def test_dossie_traz_os_numeros_das_quatro_tabelas(
    session: AsyncSession, semear_lead_completo
) -> None:
    """Este e o segundo cenario do Gherkin, afirmado no dossie.

    Afirmar sobre a prosa exigiria o modelo real no CI. Como o modelo so ve o
    dossie (D5), um numero certo aqui e a unica maneira de um numero certo
    sair do outro lado -- ver a L3 do desenho.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    dossie = await carregar_dossie(session, handoff_id=handoff_id)

    assert dossie is not None
    assert dossie.score_total == 72
    assert dossie.faixa_max_centavos == 60_000_000
    assert len(dossie.imoveis) == 3


async def test_gravar_resumo_cifra_em_repouso(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()

    await gravar_resumo(
        session, handoff_id=registro.id, texto="## Quem e o lead\nfulano", modelo="claude-sonnet-5"
    )
    await session.commit()

    bruto = (
        await session.execute(select(Handoff.resumo).where(Handoff.id == registro.id))
    ).scalar_one()
    assert bruto is not None
    assert b"Quem e o lead" not in bruto
    assert decrypt(bruto, aad_do_resumo_de_handoff(registro.id)) == "## Quem e o lead\nfulano"


async def test_o_aad_amarra_o_resumo_ao_proprio_handoff(session: AsyncSession) -> None:
    """Mover o ciphertext para outra linha tem de falhar a decifra."""
    registro = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    await gravar_resumo(session, handoff_id=registro.id, texto="segredo", modelo="m")
    await session.commit()

    bruto = (
        await session.execute(select(Handoff.resumo).where(Handoff.id == registro.id))
    ).scalar_one()

    from mobia.infra.crypto import DecryptionError

    with pytest.raises(DecryptionError):
        decrypt(bruto, aad_do_resumo_de_handoff(uuid.uuid4()))
```

A fixture `semear_lead_completo` entra em `tests/conftest.py`:

```python
@pytest.fixture
def semear_lead_completo(session: AsyncSession):
    """Um lead com qualificacao, score, recomendacoes e handoff aberto.

    Existe porque o dossie cruza quatro tabelas e montar isso a mao em cada
    teste seria quatro copias do mesmo setup, livres para divergir.
    """

    async def _semear(*, score: int, faixa_max_centavos: int, imoveis: int) -> uuid.UUID:
        agora = datetime.now(UTC)
        session.add(
            LeadQualification(
                channel=CANAL_AGENTE,
                conversation_key=CONVERSA_AGENTE,
                intencao="COMPRAR",
                faixa_preco_max_centavos=faixa_max_centavos,
                regiao="Pinheiros",
                temperatura="QUENTE",
                campos_recusados=["renda"],
                perguntados_sem_resposta=["prazo"],
            )
        )
        session.add(
            LeadScoreAudit(
                id=uuid.uuid4(),
                channel=CANAL_AGENTE,
                conversation_key=CONVERSA_AGENTE,
                total_anterior=None,
                total_novo=score,
                completude=25,
                urgencia=20,
                catalogo=12,
                engajamento=10,
                capacidade=5,
                causas=["PRIMEIRO_CALCULO"],
            )
        )
        for indice in range(imoveis):
            imovel_id = uuid.uuid4()
            session.add(
                Imovel(
                    id=imovel_id,
                    codigo=f"AP-{indice:03d}",
                    preco_centavos=58_000_000 + indice,
                )
            )
            session.add(
                Recomendacao(
                    id=uuid.uuid4(),
                    channel=CANAL_AGENTE,
                    conversation_key=CONVERSA_AGENTE,
                    imovel_id=imovel_id,
                    score_match=Decimal("0.900"),
                    motivo_match="faixa e regiao",
                    apresentado_em=agora,
                )
            )
        await session.commit()

        registro = await registrar_handoff(
            session,
            channel=CANAL_AGENTE,
            conversation_key=CONVERSA_AGENTE,
            gatilho=Gatilho.LEAD_QUENTE,
        )
        await session.commit()
        return registro.id

    return _semear
```

> **Defeitos deste esboço, encontrados na execução (12/09/2026):** `Imovel` não tem `preco_centavos` — tem `preco_venda` e `preco_aluguel`, e o dossiê rotula qual dos dois usou (Ruling R5); `MessageRole` vive em `mobia.domain.messages.enums`, não em `.models`; e a fixture precisa de `await session.flush()` após cada `Imovel`, antes do `Recomendacao` correspondente, porque a FK é crua e o unit-of-work não ordena os INSERTs sozinho. **Ao criar `Imovel`, confira os campos obrigatórios em `src/mobia/domain/catalogo/models.py` antes de rodar** — a tabela tem mais colunas `nullable=False` do que as três acima, e o teste vai reprovar com `IntegrityError` se faltar alguma. Preencha-as com valores mínimos plausíveis.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_dossie_do_banco.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'carregar_dossie'`

- [ ] **Step 3: Write the implementation**

Acrescentar a `src/mobia/domain/handoff/repositorio.py`:

```python
async def carregar_dossie(session: AsyncSession, *, handoff_id: uuid.UUID) -> Dossie | None:
    """Monta o dossie das quatro tabelas. `None` quando o handoff nao existe.

    `None` e nao excecao: o job pode chegar depois de a linha sumir (um
    TRUNCATE de teste, uma limpeza futura), e isso nao e erro do job -- e
    trabalho que perdeu o objeto. Quem chama loga e sai.

    Le em quatro consultas e nao num JOIN so: `recomendacoes` e um-para-muitos
    e o JOIN multiplicaria as linhas das outras tres, obrigando a desduplicar
    em Python o que quatro SELECTs simples ja entregam prontos.
    """
    handoff = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one_or_none()
    if handoff is None:
        return None

    chave = (Handoff.channel == handoff.channel, Handoff.conversation_key)
    qualificacao = (
        await session.execute(
            select(LeadQualification).where(
                LeadQualification.channel == handoff.channel,
                LeadQualification.conversation_key == handoff.conversation_key,
            )
        )
    ).scalar_one_or_none()

    # O ultimo recalculo, que e o score corrente: a trilha e append-only e so
    # grava quando o resultado muda, entao a linha mais nova E o estado de
    # hoje. Mesmo ORDER BY do `registrar_recalculo`, e servido pelo mesmo
    # indice `ix_lead_score_audit_lead`.
    auditoria = (
        await session.execute(
            select(LeadScoreAudit)
            .where(
                LeadScoreAudit.channel == handoff.channel,
                LeadScoreAudit.conversation_key == handoff.conversation_key,
            )
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recomendacoes = (
        (
            await session.execute(
                select(Recomendacao, Imovel)
                .join(Imovel, Imovel.id == Recomendacao.imovel_id)
                .where(
                    Recomendacao.channel == handoff.channel,
                    Recomendacao.conversation_key == handoff.conversation_key,
                )
                .order_by(Recomendacao.apresentado_em)
            )
        )
        .tuples()
        .all()
    )

    origem = (
        await session.execute(
            select(func.min(Message.created_at), func.count())
            .where(
                Message.channel == handoff.channel,
                Message.conversation_key == handoff.conversation_key,
                Message.role == MessageRole.LEAD,
            )
        )
    ).one()

    return Dossie(
        canal=handoff.channel,
        conversa=handoff.conversation_key,
        primeira_mensagem_em=origem[0] or handoff.criado_em,
        mensagens_do_lead=origem[1],
        intencao=qualificacao.intencao if qualificacao else None,
        faixa_min_centavos=qualificacao.faixa_preco_min_centavos if qualificacao else None,
        faixa_max_centavos=qualificacao.faixa_preco_max_centavos if qualificacao else None,
        regiao=qualificacao.regiao if qualificacao else None,
        tipo_imovel=qualificacao.tipo_imovel if qualificacao else None,
        quartos=qualificacao.quartos if qualificacao else None,
        vagas=qualificacao.vagas if qualificacao else None,
        urgencia=qualificacao.urgencia if qualificacao else None,
        forma_pagamento=qualificacao.forma_pagamento if qualificacao else None,
        tem_imovel_para_vender=qualificacao.tem_imovel_para_vender if qualificacao else None,
        score_total=auditoria.total_novo if auditoria else None,
        score_fatores=(
            (
                ("completude", auditoria.completude),
                ("urgencia", auditoria.urgencia),
                ("catalogo", auditoria.catalogo),
                ("engajamento", auditoria.engajamento),
                ("capacidade", auditoria.capacidade),
            )
            if auditoria
            else ()
        ),
        score_causas=tuple(auditoria.causas) if auditoria else (),
        temperatura=qualificacao.temperatura if qualificacao else None,
        # `or ()` nas duas: NULL e vazio nao sao sinonimos na gravacao, mas na
        # LEITURA sao -- e o que os comentarios das colunas em
        # `context/models.py` mandam fazer.
        temperatura_forcada_motivos=tuple(
            (qualificacao.temperatura_forcada_motivos if qualificacao else None) or ()
        ),
        imoveis=tuple(
            ImovelApresentado(
                codigo=imovel.codigo,
                preco_centavos=imovel.preco_centavos,
                reacao=recomendacao.reacao_lead,
                motivo_descarte=recomendacao.motivo_descarte,
            )
            for recomendacao, imovel in recomendacoes
        ),
        campos_recusados=tuple((qualificacao.campos_recusados if qualificacao else None) or ()),
        perguntados_sem_resposta=tuple(
            (qualificacao.perguntados_sem_resposta if qualificacao else None) or ()
        ),
        gatilho=handoff.gatilho,
        etiqueta=handoff.etiqueta,
        prioridade=handoff.prioridade,
        criado_em=handoff.criado_em,
    )


async def gravar_resumo(
    session: AsyncSession, *, handoff_id: uuid.UUID, texto: str, modelo: str
) -> None:
    """Grava o resumo cifrado. **Nao commita** -- o commit e de quem chama.

    Mesma disciplina de `registrar_handoff`, e pela mesma razao: e o chamador
    que sabe o que mais precisa entrar na transacao.
    """
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(
            resumo=encrypt(texto, aad_do_resumo_de_handoff(handoff_id)),
            resumo_gerado_em=datetime.now(UTC),
            resumo_modelo=modelo,
        )
    )
```

> Remova a linha `chave = (...)` do esboço acima — ela ficou de um rascunho e não é usada. Os imports novos: `select`, `update`, `func` de `sqlalchemy`; `Dossie`, `ImovelApresentado` de `.dossie`; `LeadQualification`, `LeadScoreAudit` de `mobia.domain.context.models`; `Recomendacao` de `mobia.domain.agente.models`; `Imovel` de `mobia.domain.catalogo.models`; `Message`, `MessageRole` de `mobia.domain.messages.models`; `encrypt` de `mobia.infra.crypto`; `aad_do_resumo_de_handoff` de `.models`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_dossie_do_banco.py -v --tb=short`
Expected: PASS (4 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/handoff/repositorio.py tests/integration/test_handoff_dossie_do_banco.py tests/conftest.py
git commit -m "feat(TEC-175): o dossie sai de quatro tabelas e o resumo volta cifrado"
```

---

### Task 7: A orquestração e o job ARQ

**Files:**
- Create: `src/mobia/domain/handoff/geracao.py`
- Create: `src/mobia/domain/handoff/agendador.py`
- Create: `src/mobia/workers/jobs/gerar_resumo.py`
- Modify: `src/mobia/workers/main.py`
- Test: `tests/integration/test_geracao_de_resumo.py`

**Interfaces:**
- Consumes: `carregar_dossie`, `gravar_resumo` (Task 6); `renderizar` (Task 1); `RedatorPort`, `ResumoDeHandoffInvalido` (Task 3).
- Produces: `gerar_resumo(session_factory, *, redator: RedatorPort, handoff_id: uuid.UUID) -> bool`; `AgendadorDeResumoPort` (Protocol com `async def agendar(self, handoff_id: uuid.UUID) -> None`); `AgendadorNoop`; `AgendadorArq(pool)`; `GERAR_RESUMO_JOB = "gerar_resumo"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_geracao_de_resumo.py
"""A geracao de ponta a ponta, com redator falso."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import MARCADORES, ResumoDeHandoffGerado, ResumoDeHandoffInvalido
from mobia.infra.crypto import decrypt


class _RedatorFalso:
    """Ecoa o dossie que recebeu, dentro dos seis marcadores.

    Ecoar e o ponto: e o que deixa o teste afirmar que o numero do banco
    chegou ate o modelo, que e o mais longe que se pode ir sem o modelo real.
    """

    def __init__(self) -> None:
        self.recebeu: str | None = None

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        self.recebeu = dossie_em_texto
        return ResumoDeHandoffGerado(
            texto="\n".join(f"{m}\nconteudo" for m in MARCADORES),
            modelo="claude-sonnet-5",
            tokens_in=900,
            tokens_out=400,
            latency_ms=120,
            comprimiu=False,
        )


class _RedatorQueFalha:
    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        raise ResumoDeHandoffInvalido("bloco ausente: '## Proxima acao'")


async def test_gera_e_grava_o_resumo(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], semear_lead_completo
) -> None:
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)
    redator = _RedatorFalso()

    assert await gerar_resumo(session_factory, redator=redator, handoff_id=handoff_id) is True

    # Os numeros do banco chegaram ao modelo -- segundo cenario do Gherkin.
    assert redator.recebeu is not None
    assert "72" in redator.recebeu
    assert "R$ 600.000" in redator.recebeu
    assert "3 imoveis apresentados" in redator.recebeu

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id)) is not None
    assert linha.resumo_modelo == "claude-sonnet-5"
    assert linha.resumo_gerado_em is not None


async def test_handoff_que_sumiu_nao_e_erro(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert (
        await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=uuid.uuid4())
        is False
    )


async def test_falha_do_redator_deixa_o_resumo_nulo(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], semear_lead_completo
) -> None:
    """Resumo nulo, e nao resumo truncado. Ver a D7 do desenho."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    assert (
        await gerar_resumo(session_factory, redator=_RedatorQueFalha(), handoff_id=handoff_id)
        is False
    )

    linha = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert linha.resumo is None


async def test_regenerar_substitui_o_resumo_anterior(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], semear_lead_completo
) -> None:
    """Quarto cenario do Gherkin, no nivel da funcao."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=handoff_id)

    primeiro = (
        await session.execute(select(Handoff.resumo_gerado_em).where(Handoff.id == handoff_id))
    ).scalar_one()

    assert await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=handoff_id)

    segundo = (
        await session.execute(select(Handoff.resumo_gerado_em).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert segundo >= primeiro
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_geracao_de_resumo.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.handoff.geracao'`

- [ ] **Step 3: Write the orchestration**

```python
# src/mobia/domain/handoff/geracao.py
"""A geracao do resumo, de ponta a ponta.

TEC-175. Roda FORA da transacao do turno -- ver a D1 do desenho: o handoff
nasce dentro dela, e uma chamada de LLM de 8s no p95 ali dentro seguraria o
`SELECT ... FOR UPDATE` do recalculo por esses 8s, cobrando do tempo de
resposta do LEAD um resumo que e para o CORRETOR.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.dossie import renderizar
from mobia.domain.handoff.repositorio import carregar_dossie, gravar_resumo
from mobia.domain.handoff.resumo import RedatorPort, ResumoDeHandoffInvalido

log = structlog.get_logger(__name__)


async def gerar_resumo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    redator: RedatorPort,
    handoff_id: uuid.UUID,
) -> bool:
    """Gera e grava. `True` quando gravou; `False` em toda falha esperada.

    **Recebe factory e nao sessao**, ao contrario de `registrar_handoff`. A
    inversao e deliberada: a leitura do dossie e a escrita do resumo sao DUAS
    transacoes, e a chamada ao modelo fica entre elas, fora de qualquer uma.
    Uma sessao unica manteria a transacao aberta durante os 8s da chamada, que
    e exatamente o que a D1 existe para evitar -- so que no worker em vez de
    no turno.

    Nao levanta em falha esperada porque quem chama e um job: um handoff sem
    resumo e um estado previsto (a TEC-176 o atende), e transformar isso em
    retentativa do ARQ so repetiria a mesma chamada cara.
    """
    async with session_factory() as session:
        dossie = await carregar_dossie(session, handoff_id=handoff_id)

    if dossie is None:
        # Nao e erro: o job pode chegar depois de a linha sumir.
        log.warning("resumo_handoff.handoff_sumiu", handoff_id=str(handoff_id))
        return False

    try:
        gerado = await redator.redigir(renderizar(dossie))
    except ResumoDeHandoffInvalido as falha:
        # O handoff FICA sem resumo, e de proposito -- resumo truncado corta o
        # bloco da proxima acao e parece completo. Ver a D7 do desenho. Nunca
        # loga o dossie nem a resposta: so o motivo.
        log.warning(
            "resumo_handoff.invalido", handoff_id=str(handoff_id), motivo=str(falha)
        )
        return False

    async with session_factory() as session:
        await gravar_resumo(
            session, handoff_id=handoff_id, texto=gerado.texto, modelo=gerado.modelo
        )
        await session.commit()

    log.info(
        "resumo_handoff.gravado",
        handoff_id=str(handoff_id),
        caracteres=len(gerado.texto),
        comprimiu=gerado.comprimiu,
    )
    return True
```

```python
# src/mobia/domain/handoff/agendador.py
"""Quem pede a geracao do resumo, sem que o dominio saiba o que e ARQ.

TEC-175, D11. Mesmo padrao dos cinco ports que `executar_turno` ja recebe, e
mesmo padrao do `outbound/noop.py` para o duble de teste.
"""

import uuid
from typing import Protocol

import structlog
from arq.connections import ArqRedis

log = structlog.get_logger(__name__)

GERAR_RESUMO_JOB = "gerar_resumo"


class AgendadorDeResumoPort(Protocol):
    async def agendar(self, handoff_id: uuid.UUID) -> None: ...


class AgendadorNoop:
    """Nao agenda nada. O default de todo teste que nao e sobre o resumo."""

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        return None


class AgendadorArq:
    """Enfileira o job de geracao.

    `_job_id` derivado do handoff: dois gatilhos que criem o handoff em
    corrida produziriam dois enqueues, e o ARQ recusa o segundo enquanto o
    primeiro estiver pendente. Como `gerar_resumo` e registrado com
    `keep_result=0` -- mesma razao escrita em `WorkerSettings` para o
    `process_message` --, a chave de resultado nao sobrevive para bloquear uma
    regeneracao legitima depois.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            GERAR_RESUMO_JOB, str(handoff_id), _job_id=f"resumo:{handoff_id}"
        )
```

```python
# src/mobia/workers/jobs/gerar_resumo.py
"""O job que redige o resumo do handoff. TEC-175."""

import uuid
from typing import Any

from mobia.domain.handoff.geracao import gerar_resumo as _gerar
from mobia.infra.db import get_sessionmaker


async def gerar_resumo(ctx: dict[str, Any], handoff_id: str) -> str:
    """Gera o resumo de um handoff. Devolve um rotulo para o log do ARQ.

    O redator vem do `ctx` e nao e construido aqui, pelo mesmo motivo que o
    `classificador` e o `resumidor` do `process_message` vem de la: e o
    `startup` do worker que decide qual implementacao roda, e o teste troca a
    decisao sem tocar no job.
    """
    gravou = await _gerar(
        get_sessionmaker(), redator=ctx["redator"], handoff_id=uuid.UUID(handoff_id)
    )
    return "gravado" if gravou else "sem_resumo"
```

- [ ] **Step 4: Wire the worker**

Em `src/mobia/workers/main.py`: importar `gerar_resumo` e `RedatorAnthropic`, pôr `ctx["redator"] = RedatorAnthropic()` no `startup` (ao lado dos outros ports) e acrescentar à lista `functions`:

```python
        # `keep_result=0` pela mesma razao do `process_message`: o `_job_id` e
        # fixo por handoff, e uma chave de resultado sobrevivente recusaria em
        # silencio a regeneracao pedida pela rota da D8.
        func(gerar_resumo, keep_result=0),
```

**Não** entra em `cron_jobs`: a geração é disparada por quem cria o handoff, nunca por relógio.

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_geracao_de_resumo.py -v --tb=short`
Expected: PASS (4 testes)

- [ ] **Step 6: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/handoff/geracao.py src/mobia/domain/handoff/agendador.py src/mobia/workers/jobs/gerar_resumo.py src/mobia/workers/main.py tests/integration/test_geracao_de_resumo.py
git commit -m "feat(TEC-175): a geracao roda em job proprio, com a chamada ao modelo fora de toda transacao"
```

---

### Task 8: Enfileirar nos três pontos pós-commit

**Files:**
- Modify: `src/mobia/domain/agente/turno.py:319-328,805-812,909-916`
- Modify: `src/mobia/workers/jobs/process_message.py:136-142,222-230`
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_handoff_agenda_resumo.py`

**Interfaces:**
- Consumes: `AgendadorDeResumoPort`, `AgendadorNoop` (Task 7); `HandoffRegistrado` (Task 5).
- Produces: `executar_turno(..., agendador: AgendadorDeResumoPort)` — parâmetro novo, obrigatório e por palavra-chave.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_handoff_agenda_resumo.py
"""O enfileiramento da geracao nos tres pontos que criam handoff."""

import uuid


class _AgendadorEspiao:
    def __init__(self) -> None:
        self.pedidos: list[uuid.UUID] = []

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        self.pedidos.append(handoff_id)


class _AgendadorQueExplode:
    async def agendar(self, handoff_id: uuid.UUID) -> None:
        raise RuntimeError("redis caiu")


async def test_handoff_novo_agenda_a_geracao(session, rodar_turno) -> None:
    espiao = _AgendadorEspiao()
    await rodar_turno(agendador=espiao, forcar_quente=True)

    assert len(espiao.pedidos) == 1


async def test_gatilho_adicional_nao_reagenda(session, rodar_turno) -> None:
    """O gatilho da intencao dispara em TODO turno -- ver a D3 do desenho.

    Reagendar aqui seria uma chamada de LLM por turno para um resumo que
    ninguem pediu.
    """
    espiao = _AgendadorEspiao()
    await rodar_turno(agendador=espiao, forcar_quente=True)
    await rodar_turno(agendador=espiao, forcar_quente=True)

    assert len(espiao.pedidos) == 1


async def test_falha_ao_agendar_nao_derruba_o_turno(session, rodar_turno) -> None:
    """O handoff ja esta commitado: perde-se o resumo, nao o handoff."""
    resultado = await rodar_turno(agendador=_AgendadorQueExplode(), forcar_quente=True)

    assert resultado is not None
```

> Adapte as chamadas de `rodar_turno` à assinatura real da fixture em `tests/conftest.py:471` — `forcar_quente` é ilustrativo; use o mecanismo que `tests/integration/test_handoff_no_turno.py` já usa para levar o lead a `QUENTE`.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_agenda_resumo.py -v --tb=short`
Expected: FAIL — `executar_turno() got an unexpected keyword argument 'agendador'`

- [ ] **Step 3: Add the parameter and the three enqueues**

Em `turno.py`, o parâmetro novo na assinatura (linha ~327):

```python
    agendador: AgendadorDeResumoPort,
```

E, nos dois blocos de log pós-commit, logo depois do `log.info`:

```python
        await _agendar_resumo(agendador, handoff_da_intencao)
```

```python
            await _agendar_resumo(agendador, handoff_do_quente)
```

com a função auxiliar, acima de `executar_turno`:

```python
async def _agendar_resumo(
    agendador: AgendadorDeResumoPort, registro: HandoffRegistrado
) -> None:
    """Pede o resumo, mas so quando o handoff e NOVO.

    Gatilho adicional nao reagenda: a intencao dispara em TODO turno com a
    classificacao certa -- e o que o `CASE` do `ON CONFLICT` em
    `repositorio.py` ja documenta --, entao reagendar seria uma chamada de
    LLM por turno. Ver a D3 do desenho.

    **Nao propaga excecao.** O handoff ja esta commitado neste ponto; uma
    falha do Redis aqui derrubaria o turno DEPOIS de o lead ter sido
    atendido, e o que se perde e o resumo, que a rota de regeneracao
    recupera.
    """
    if not registro.criado:
        return
    try:
        await agendador.agendar(registro.id)
    except Exception:
        log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)
```

Em `process_message.py`, depois do `log.info("handoff.criado" ...)`:

```python
    # Mesma guarda de nao-propagacao da D10 da TEC-174, aplicada a chamada
    # nova: uma excecao aqui SUBSTITUIRIA a excecao original do turno e
    # apagaria a causa real da falha. Falha ao agendar vira log e segue -- o
    # handoff permanece, e fica sem resumo ate alguem pedir a regeneracao.
    if registro.criado:
        try:
            await ctx["agendador"].agendar(registro.id)
        except Exception:
            log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)
```

e, na chamada a `executar_turno` (linha ~222), passar `agendador=ctx["agendador"]`.

Em `workers/main.py`, no `startup`: `ctx["agendador"] = AgendadorArq(ctx["redis"])`.

Em `tests/conftest.py`, a fixture `rodar_turno` passa a aceitar `agendador` com default `AgendadorNoop()`.

- [ ] **Step 4: Run the affected tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_agenda_resumo.py tests/integration/test_handoff_no_turno.py tests/integration/test_handoff_por_erro.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/turno.py src/mobia/workers/jobs/process_message.py src/mobia/workers/main.py tests/conftest.py tests/integration/test_handoff_agenda_resumo.py
git commit -m "feat(TEC-175): os tres pontos que criam handoff pedem o resumo depois do commit"
```

---

### Task 9: A rota de regeneração e o link

**Files:**
- Create: `src/mobia/api/routes/handoffs.py`
- Modify: `src/mobia/app/main.py:30-40`
- Modify: `src/mobia/app/config.py`
- Test: `tests/integration/test_rota_de_resumo.py`

**Interfaces:**
- Consumes: `gerar_resumo` (Task 7); `exigir_admin` (`mobia.api.deps`).
- Produces: `POST /api/v1/handoffs/{handoff_id}/resumo`; `Settings.dashboard_base_url`; `link_da_transcricao(channel, conversation_key) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_rota_de_resumo.py
"""A porta de entrada da regeneracao (D8) e o link da RN-15.5."""

import uuid

from mobia.domain.handoff.dossie import link_da_transcricao

TOKEN = "token-de-teste"


async def test_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(f"/api/v1/handoffs/{uuid.uuid4()}/resumo")
    assert resposta.status_code == 403


async def test_handoff_inexistente_e_404(cliente_http) -> None:
    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/resumo", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


async def test_regenera_e_devolve_o_resumo_com_o_link(
    cliente_http, semear_lead_completo
) -> None:
    """Primeiro cenario do Gherkin: os seis blocos, o limite e o link."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resumo"]) <= 1500
    # O link e campo separado, e nao conteudo do resumo -- ver a D10.
    assert corpo["link"].endswith("/conversas/whatsapp/5511911112222")
    assert corpo["link"] not in corpo["resumo"]


def test_o_link_nao_e_composto_pelo_modelo() -> None:
    assert link_da_transcricao("whatsapp", "5511911112222").endswith(
        "/conversas/whatsapp/5511911112222"
    )
```

> A fixture `cliente_http` precisa montar o app com `catalogo_admin_token=TOKEN` e um redator falso. Se o repo ainda não tiver um cliente HTTP de teste, espelhe o que `tests/integration/` já faz para as rotas de `imoveis.py` — procure por `AsyncClient` ou `TestClient` lá antes de escrever a sua.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_resumo.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'link_da_transcricao'`

- [ ] **Step 3: Add the config and the link**

Em `src/mobia/app/config.py`, ao lado dos outros campos de URL:

```python
    # A base do dashboard (E8), para o link da RN-15.5 e para o da RN-16.2.
    # Vazia em desenvolvimento: o dashboard nao existe ainda, e o link
    # composto sobre uma base vazia continua sendo um caminho valido -- ver a
    # L4 do desenho.
    dashboard_base_url: str = ""
```

Em `dossie.py`:

```python
def link_da_transcricao(canal: str, conversa: str) -> str:
    """O link da RN-15.5, composto aqui e nunca pelo modelo.

    Campo separado e nao conteudo do resumo (D10): se entrasse no texto,
    gastaria orcamento dos 1.500 caracteres da RN-15.2 e passaria a depender
    de o modelo transcrever uma URL sem errar um caractere.

    **O destino ainda nao existe** -- e a E8. Ver a L4 do desenho.
    """
    return f"{get_settings().dashboard_base_url}/conversas/{canal}/{conversa}"
```

> `dossie.py` deixa de ser puro ao importar `get_settings`. Se preferir mantê-lo puro — e é uma preferência defensável, dado o cabeçalho do módulo —, ponha `link_da_transcricao` em `resumo.py` e ajuste o import do teste.

- [ ] **Step 4: Write the route**

```python
# src/mobia/api/routes/handoffs.py
"""A regeneracao do resumo sob demanda. TEC-175, RN-15.2 e D8 do desenho.

O Gherkin diz "pelo dashboard", e o dashboard (E8) esta fora do escopo da
card. Esta rota e o mecanismo que ele vai chamar; ate la, e por ela que o
criterio de aceite da regeneracao e exercitado.

Guardada por `exigir_admin` como as rotas de catalogo: o resumo carrega dado
pessoal do lead, e rota aberta nao e opcao.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from mobia.api.deps import exigir_admin
from mobia.domain.handoff.dossie import link_da_transcricao
from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import RedatorAnthropic
from mobia.infra.crypto import decrypt
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])


@router.post("/{handoff_id}/resumo")
async def regenerar(
    handoff_id: uuid.UUID, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    session_factory = get_sessionmaker()

    gravou = await gerar_resumo(
        session_factory, redator=RedatorAnthropic(), handoff_id=handoff_id
    )
    if not gravou:
        # 404 cobre o handoff que nao existe; 502 seria mais preciso para a
        # falha do provedor, mas `gerar_resumo` devolve o mesmo False para os
        # dois de proposito (ver a docstring de la). Distingui-los aqui
        # exigiria que ela levantasse, e ela nao levanta porque o chamador
        # normal e um job.
        async with session_factory() as session:
            existe = (
                await session.execute(select(Handoff.id).where(Handoff.id == handoff_id))
            ).scalar_one_or_none()
        if existe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handoff nao existe")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="resumo nao pode ser gerado"
        )

    async with session_factory() as session:
        linha = (
            await session.execute(select(Handoff).where(Handoff.id == handoff_id))
        ).scalar_one()

    return {
        "resumo": decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id)),
        "link": link_da_transcricao(linha.channel, linha.conversation_key),
        "geradoEm": linha.resumo_gerado_em.isoformat() if linha.resumo_gerado_em else None,
        "modelo": linha.resumo_modelo,
    }
```

Em `src/mobia/app/main.py`, registrar dentro do mesmo `if settings.catalogo_admin_token:` que já guarda o router de imóveis — o guard é o mesmo token.

- [ ] **Step 5: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_resumo.py -v --tb=short`
Expected: PASS (4 testes)

- [ ] **Step 6: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/api/routes/handoffs.py src/mobia/app/main.py src/mobia/app/config.py src/mobia/domain/handoff/dossie.py tests/integration/test_rota_de_resumo.py
git commit -m "feat(TEC-175): a regeneracao ganha porta de entrada, e o link nao passa pelo modelo"
```

---

### Task 10: Fechamento — suíte inteira e comentários tocados

**Files:** nenhum arquivo novo; correções onde a suíte apontar.

- [ ] **Step 1: Run the whole suite, once**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: verde. Guarde o hash junto com o resultado.

Se falhar: **rode de novo sobre a mesma árvore antes de culpar a sua mudança.** É o único jeito de separar flake de regressão — o precedente é a TEC-156, em que o mesmo commit deu 1236/1236 e depois 1235/1236. Uma falha isolada com `ConnectionResetError [WinError 64]` no traceback **não autoriza conclusão nenhuma**: são ~5% dos connects nesta máquina, sempre na negociação SSL dentro da fixture. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam 100% isolados.

- [ ] **Step 2: Check the touched comments**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

Reconfira cada `ALTERADO` e cada `VIZINHO`. **`VIZINHO` é a categoria que importa:** é o comentário que ninguém editou, dentro de um `def` cujo código mudou — foi assim que a TEC-146 deixou passar um comentário que mentia e escondia um bug de orçamento por duas revisões.

Os dois candidatos previsíveis desta branch:
- O comentário do `.returning(...)` em `repositorio.py`, que descreve só o `xmax` e agora tem `Handoff.id` ao lado.
- Os comentários de `handoff_do_quente`/`handoff_da_intencao` em `turno.py` (linhas ~733-737), que dizem "viram o booleano de `registrar_handoff`" e agora viram um dataclass.

> A ferramenta marcou 723 `VIZINHO` na branch da TEC-174 porque trata um `def` inteiro como bloco e `executar_turno` é enorme. Espere ruído parecido aqui e leia mesmo assim.

- [ ] **Step 3: Verify the prompt budget was not touched**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: PASS. Esta card não mexe em `SISTEMA_DO_AGENTE`, então o teto não deve se mover — se ele reprovar, alguma coisa entrou no prompt do agente por engano.

- [ ] **Step 4: Commit any fixes and push**

```bash
git push -u origin feat/tec-175-resumo-em-seis-blocos
```

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 7 e 8. D2 → Task 5. D3 → Task 8 (`_agendar_resumo`). D4 → Task 1 (`_pontos_de_atencao`). D5 → Task 1 e 6. D6 → Task 2. D7 → Task 3. D8 → Task 9. D9 → Task 4 e 6. D10 → Task 9. D11 → Task 7 e 8. L1 → Task 1 (dossiê sem nome). L2 → Task 3 (`latency_ms` no log). L3 → Task 6 e 7. L4 → Task 9.

**Consistência de tipos:** `registrar_handoff` devolve `HandoffRegistrado` da Task 5 em diante; `gerar_resumo` recebe `session_factory` e devolve `bool` nas Tasks 7 e 9; `redigir` devolve `ResumoDeHandoffGerado` nas Tasks 3 e 7.

**Três pontos que o executor precisa resolver contra o repo, e que estão marcados em citação no corpo do plano:** os campos obrigatórios de `Imovel` na fixture da Task 6; a assinatura real de `rodar_turno` na Task 8; e a existência (ou não) de um cliente HTTP de teste na Task 9.
