# TEC-151 — Temperatura do lead: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derivar a temperatura do lead a partir do score (RN-06.2), forçar `QUENTE` por gatilho de intenção de agir (RN-06.3) de forma que o forçamento sobreviva ao recálculo, e emitir o evento da RN-06.5 na borda de esquentar.

**Architecture:** Duas funções puras novas (`temperatura.py` para a faixa, `gatilhos.py` para a detecção determinística sobre a fala do lead) e três colunas em `lead_qualification`. O gancho de recálculo que a TEC-152 já colocou em `turno.py` cresce para resolver a temperatura na mesma linha travada e no mesmo commit — não há gancho novo, não há tabela nova, não há leitura extra.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy async, Alembic, Postgres, ARQ, pytest, structlog, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-03-tec-151-temperatura-do-lead-design.md`

**Branch:** `feat/tec-151-temperatura-do-lead` (já criada).

## Global Constraints

- **Os três gates estáticos, nesta ordem, antes de cada commit.** O formatador é gate separado do linter; passar num não diz nada sobre o outro:
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m mypy`
- **Escopo do ruff é `src tests alembic evals`**, não `src tests`. O mypy segue só em `src`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento. Acento dentro de padrão regex é intencional e correto.
- **Comentário desatualizado é defeito.** Se você mudar código que um comentário descreve, o comentário muda junto ou some. A Task 7 existe inteira por causa desta regra.
- **Mensagem de commit:** português sem acento no assunto, formato `tipo(TEC-151): o que passou a ser verdade`.
- **A suíte é lenta e lentidão parece travamento.** `tests/unit` sozinho leva ~7 min; a suíte completa ~7,5 min e 857 testes. Com `-q` o pytest só imprime no fim — arquivo de saída vazio depois de dez minutos é normal. Para ver progresso: `python -u -m pytest -v`.
- **O banco demora mais que o healthcheck diz.** Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` com o container já `healthy`. Espere e retente antes de diagnosticar.
- **Testes de integração flakeiam sob carga.** Antes de atribuir uma falha a uma mudança sua, rode o arquivo sozinho.
- **Basename de teste NUNCA colide entre `tests/unit` e `tests/integration`.** Colisão aborta a coleta da suíte inteira, não aparece no arquivo isolado, e já custou duas cards (`a3d1840`, `424ed72`). Os três arquivos novos deste plano têm basenames que não existem em nenhum dos dois diretórios — confira antes de renomear qualquer um.
- **Não toque no prompt.** Nada neste plano acrescenta texto a `SISTEMA_DO_AGENTE` nem campo a `SCHEMA_DA_RESPOSTA`. A margem do orçamento é 6,2 tokens sobre o teto fixo de 655, e a D2 do desenho escolheu o detector determinístico exatamente para não gastá-la.

## File Structure

**Criados:**

| arquivo | responsabilidade |
|---|---|
| `src/mobia/domain/context/temperatura.py` | O enum `Temperatura`, os dois cortes, e `temperatura_de`. Função pura: sem I/O, sem banco, sem modelo |
| `src/mobia/domain/context/gatilhos.py` | `gatilhos_de(texto)`, o detector determinístico dos três gatilhos da RN-06.3. Função pura sobre o texto decifrado |
| `alembic/versions/0014_temperatura_do_lead.py` | Três colunas em `lead_qualification` e os dois `CHECK` |
| `tests/unit/test_temperatura.py` | A faixa, o teto `MORNO`, o curto-circuito do forçamento |
| `tests/unit/test_gatilhos_de_temperatura.py` | Os três motivos, os negativos que a estritez protege, a normalização |
| `tests/integration/test_temperatura_no_turno.py` | Os dois `CHECK`, a persistência, a sobrevivência ao recálculo, a borda do evento |

**Modificados:**

| arquivo | mudança |
|---|---|
| `src/mobia/domain/context/models.py` | Três colunas novas em `LeadQualification`, depois de `campos_recusados` |
| `src/mobia/domain/context/repositorio.py` | `Recalculo` (dataclass novo) e `registrar_recalculo` resolvendo a temperatura |
| `src/mobia/domain/agente/turno.py` | `gatilhos_de(corpo)` no topo, repassado ao gancho; `lead.esquentou` depois do commit |
| `src/mobia/domain/context/score.py` | Docstring que passará a mentir sobre a faixa (Task 7) |
| `tests/integration/test_auditoria_score.py` | 7 asserções que leem o retorno de `registrar_recalculo` |
| `tests/unit/test_regras_de_recusa.py` | Docstring que prevê a TEC-151 no futuro (Task 7) |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Emenda `E-01` à RN-06.2, mais linha na tabela do topo |
| `docs/superpowers/specs/2026-09-03-tec-151-temperatura-do-lead-design.md` | Linha de status |

---

### Task 1: A faixa, como função pura

**Files:**
- Create: `src/mobia/domain/context/temperatura.py`
- Test: `tests/unit/test_temperatura.py`

**Interfaces:**
- Consumes: `Score` de `mobia.domain.context.score` (já existe; tem `.total` como `property`).
- Produces: `Temperatura` (StrEnum com `QUENTE`/`MORNO`/`FRIO`), `CORTE_QUENTE = 70`, `CORTE_MORNO = 40`, e `temperatura_de(score: Score, *, qualificado: bool, forcada: bool) -> Temperatura`. As Tasks 5 e 6 importam os três nomes.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_temperatura.py`:

```python
"""A temperatura derivada do score, e o forcamento que ignora a faixa.

TEC-151, RN-06.2 e RN-06.3. Sem banco: a funcao e pura.
"""

import pytest

from mobia.domain.context.score import Score
from mobia.domain.context.temperatura import (
    CORTE_MORNO,
    CORTE_QUENTE,
    Temperatura,
    temperatura_de,
)


def score(total: int) -> Score:
    """Um Score com o total pedido, todo no engajamento.

    Qual fator carrega o numero nao importa para esta funcao -- ela le so
    `.total` --, e concentrar num fator deixa o teste legivel. Os pesos reais
    de cada fator sao assunto de `test_score.py`.
    """
    return Score(completude=0, urgencia=0, catalogo=0, engajamento=total, capacidade=0)


@pytest.mark.parametrize(
    ("total", "esperada"),
    [
        (85, Temperatura.QUENTE),
        (70, Temperatura.QUENTE),
        (69, Temperatura.MORNO),
        (40, Temperatura.MORNO),
        (39, Temperatura.FRIO),
    ],
)
def test_a_faixa_da_rn_06_2(total: int, esperada: Temperatura) -> None:
    """A tabela do criterio de aceite da card, literal."""
    assert temperatura_de(score(total), qualificado=True, forcada=False) is esperada


def test_o_lead_nao_qualificado_topa_em_morno() -> None:
    """A emenda E-01 a RN-06.2, e a diverencia que a TEC-150 declarou.

    Um lead com `intencao = None`, resto completo, IMEDIATA, forma de
    pagamento declarada e engajamento soma 70 com `esta_qualificado` False.
    Sem o teto ele chegaria QUENTE e faria o telefone do corretor tocar
    (RN-06.5) por um lead cuja intencao o sistema nunca determinou.
    """
    assert temperatura_de(score(70), qualificado=False, forcada=False) is Temperatura.MORNO


@pytest.mark.parametrize("total", [39, 40, 69])
def test_o_teto_so_morde_em_quente(total: int) -> None:
    """Abaixo de 70 a qualificacao nao muda nada: quem ja era MORNO ou FRIO
    continua igual. O teto impede a passagem para QUENTE, e mais nada."""
    assert temperatura_de(score(total), qualificado=False, forcada=False) is temperatura_de(
        score(total), qualificado=True, forcada=False
    )


def test_o_forcamento_ignora_o_score() -> None:
    """O cenario 2 da card: score 35, temperatura QUENTE."""
    assert temperatura_de(score(35), qualificado=False, forcada=True) is Temperatura.QUENTE


def test_o_forcamento_ignora_o_teto_de_qualificacao() -> None:
    """A RN-06.3 diz "independentemente do score", e quem pede visita esta
    pronto para agir mesmo sem os quatro obrigatorios. Um VENDER_IMOVEL que
    pede para falar com corretor chega QUENTE -- o que e exatamente o que a
    RN-03.4 ja quer para ele."""
    assert temperatura_de(score(0), qualificado=False, forcada=True) is Temperatura.QUENTE


def test_os_dois_flags_sao_keyword_only() -> None:
    """Dois `bool` adjacentes: trocar a ordem nao levanta, nao e erro de tipo,
    nao e visivel ao mypy, e devolveria temperatura errada em silencio. Mesma
    razao pela qual as duas contagens de `calcular_score` sao keyword-only."""
    with pytest.raises(TypeError):
        temperatura_de(score(0), False, True)  # type: ignore[misc]


def test_os_cortes_sao_os_do_srs() -> None:
    """A RN-06.2 corta em 70 e 40, e a decisao de 02/09/2026 foi NAO recalibrar
    para o teto real do score (75 sem catalogo). Se estes numeros mudarem, foi
    decisao de alguem -- nao deixe passar em silencio."""
    assert (CORTE_QUENTE, CORTE_MORNO) == (70, 40)
```

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_temperatura.py -v`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.context.temperatura'`.

- [ ] **Step 3: Escreva a implementação mínima**

Crie `src/mobia/domain/context/temperatura.py`:

```python
"""A temperatura do lead: derivada do score, e forcavel por gatilho.

TEC-151, RN-06.2 e RN-06.3. Pura de proposito: sem I/O, sem banco, sem
chamada ao modelo -- mesma forma de `score.py`, `auditoria.py` e
`qualificacao.py`. Quem le a coluna e quem grava e o repositorio; aqui so se
decide qual e a temperatura.

**Os cortes sao os do SRS, e nao os do teto real do score.** O score topa em
95 com catalogo e 75 sem ele (a aderencia vale 20 e contribui zero ate a
TEC-158), e a RN-06.2 corta QUENTE em 70 -- um limiar desenhado para uma
escala que ia a 100. Perguntou-se em 02/09/2026 se esta card deveria
recalibrar, e a decisao foi aceitar: so tres totais alcancam 70 hoje,
{70, 72, 75}, cada um exigindo simultaneamente os quatro obrigatorios,
`urgencia == IMEDIATA`, forma de pagamento declarada e engajamento. **QUENTE
por faixa nao e uma faixa; e uma conjuncao de quase-maximos**, e por isso os
gatilhos da RN-06.3 sao o caminho principal, e nao a excecao.
"""

from enum import StrEnum

from mobia.domain.context.score import Score

CORTE_QUENTE = 70
CORTE_MORNO = 40


class Temperatura(StrEnum):
    QUENTE = "QUENTE"
    MORNO = "MORNO"
    FRIO = "FRIO"


def temperatura_de(score: Score, *, qualificado: bool, forcada: bool) -> Temperatura:
    """A temperatura da RN-06.2, com o teto da emenda e o forcamento da RN-06.3.

    **`forcada` curto-circuita antes de olhar o score**, e e o cenario 2 da
    card: "score 35 e temperatura FRIO... a temperatura passa a QUENTE... e o
    score permanece 35". Nada nesta card toca o score.

    **`qualificado` e teto, nao piso: ele so morde em QUENTE.** Um lead nao
    qualificado com total 45 ja era MORNO, e continua. O que o teto impede e
    a passagem para QUENTE, e a razao e a RN-06.5: QUENTE faz o telefone do
    corretor tocar. A TEC-150 declarou que dois estados alcancaveis somam 70
    com `esta_qualificado` False -- um deles com `intencao = None`, cuja
    intencao o sistema nunca determinou --, e enquanto nada consumia o numero
    declarar bastava. E **emenda E-01 a RN-06.2**, nao leitura dela.

    **`Score` e nao `int`.** A funcao usa so `.total`, e receber o total seria
    mais simples -- e abriria a porta para alguem passar `total_anterior` da
    trilha ou um numero montado a mao. O tipo e a unica coisa que impede a
    temperatura de ser derivada de um total cuja procedencia ninguem garante.

    **Os dois flags sao keyword-only**, pela razao que a TEC-150 aplicou as
    duas contagens de `calcular_score`: sao dois `bool` adjacentes, e inverter
    a ordem num chamador nao levanta, nao e erro de tipo, nao e visivel ao
    mypy, e devolve temperatura errada em silencio.

    **`score is None` nao e caso.** Quem chama ja sabe que ha linha -- sem
    linha nao ha sujeito, e `registrar_recalculo` devolve antes. Aceitar
    `None` aqui exigiria escolher entre FRIO e "sem temperatura" para um lead
    que nao existe, e as duas respostas seriam invencao.
    """
    if forcada:
        return Temperatura.QUENTE
    if score.total >= CORTE_QUENTE:
        return Temperatura.QUENTE if qualificado else Temperatura.MORNO
    if score.total >= CORTE_MORNO:
        return Temperatura.MORNO
    return Temperatura.FRIO
```

- [ ] **Step 4: Rode o teste para confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_temperatura.py -v`
Expected: PASS, 12 testes (5 da parametrização da faixa + 3 do teto + 4 avulsos).

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. Se o `format --check` reclamar, rode `./.venv/Scripts/python.exe -m ruff format src tests alembic evals` e confira o diff antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/context/temperatura.py tests/unit/test_temperatura.py
git commit -m "feat(TEC-151): a faixa da RN-06.2 passa a existir, com teto MORNO para nao-qualificado"
```

---

### Task 2: Os gatilhos, como detector determinístico

**Files:**
- Create: `src/mobia/domain/context/gatilhos.py`
- Test: `tests/unit/test_gatilhos_de_temperatura.py`

**Interfaces:**
- Consumes: nada do projeto — só `re` e `unicodedata`.
- Produces: `MOTIVO_VISITA = "VISITA"`, `MOTIVO_CORRETOR = "CORRETOR"`, `MOTIVO_PROPOSTA = "PROPOSTA"`, e `gatilhos_de(texto: str) -> tuple[str, ...]`. A Task 6 importa `gatilhos_de`; a Task 5 não importa nada daqui (recebe a tupla por parâmetro).

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_gatilhos_de_temperatura.py`:

```python
"""Os tres gatilhos que forcam QUENTE, detectados na fala do lead.

TEC-151, RN-06.3. Sem banco e sem chamada paga: a funcao e pura.

**A assimetria de erro e o INVERSO do opt-out**, e e por isso que este
arquivo tem mais teste negativo que positivo. No opt-out, deixar de detectar
e violacao de LGPD e a faixa inequivoca e generosa. Aqui o falso positivo
forca QUENTE PERMANENTEMENTE (a RN-06.3 diz "ate intervencao humana") e toca
o telefone do corretor, e nao existe tela para desfazer -- a TEC-192 nao
existe. Permanente e sem desfazer vence recuperavel: faixa estrita.
"""

import pytest

from mobia.domain.context.gatilhos import (
    MOTIVO_CORRETOR,
    MOTIVO_PROPOSTA,
    MOTIVO_VISITA,
    gatilhos_de,
)


@pytest.mark.parametrize(
    "texto",
    [
        "oi bom dia, sou eu de novo. fechei financiamento e quero agendar visita no apartamento",
        "da pra remarcar uma visita pra essa semana?",
        "queria marcar uma visita",
        "podemos agendar a visita pra sabado?",
    ],
)
def test_pedido_de_visita_dispara(texto: str) -> None:
    """Os dois primeiros sao falas reais do corpus -- `compra.yaml:139` e
    `follow_up.yaml:18`."""
    assert gatilhos_de(texto) == (MOTIVO_VISITA,)


@pytest.mark.parametrize(
    "texto",
    [
        "quero falar com um corretor",
        "tem como falar com o corretor?",
        "prefiro falar com uma pessoa",
        "quero falar com atendente",
    ],
)
def test_pedido_de_corretor_dispara(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_CORRETOR,)


@pytest.mark.parametrize(
    "texto",
    [
        "quero fazer uma proposta",
        "posso enviar uma proposta hoje?",
        "quando posso assinar o contrato?",
        "vamos fechar negocio",
    ],
)
def test_mencao_a_proposta_ou_contrato_dispara(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_PROPOSTA,)


def test_plantao_de_visita_nao_dispara() -> None:
    """O caso real do corpus que a estritez existe para proteger.

    `evals/corpus/compra.yaml:318` -- "voces tem plantao de visita no fim de
    semana?". E pergunta sobre horario de funcionamento, nao pedido de visita.
    Um detector que casasse `visita` em qualquer posicao marcaria este lead
    QUENTE para sempre, e ninguem teria como desfazer.
    """
    assert gatilhos_de("voces tem plantao de visita no fim de semana?") == ()


@pytest.mark.parametrize(
    "texto",
    [
        "quanto custa uma visita?",
        "a visita foi otima, obrigado",
        "o corretor de outra imobiliaria falou 500 mil",
        "recebi uma proposta de outra empresa e queria comparar",
        "o contrato de aluguel atual vence em marco",
    ],
)
def test_o_objeto_sem_o_verbo_de_acao_nao_dispara(texto: str) -> None:
    """O criterio da faixa e o VERBO junto do objeto, e nao o objeto sozinho.

    Mesma forma que fecha a colisao no opt-out, onde e o objeto de mensageria
    que faz "pare de me mandar mensagens" nao casar com "pare de mandar
    apartamento sem vaga".
    """
    assert gatilhos_de(texto) == ()


def test_dois_motivos_no_mesmo_turno() -> None:
    """Tupla e nao motivo unico: precedencia aqui descartaria informacao real.

    A ordem de saida e a de `_TERMOS_POR_MOTIVO`, entao o teste pode comparar
    por igualdade em vez de por conjunto -- mesma escolha de
    `causas_do_recalculo`.
    """
    assert gatilhos_de("quero fazer uma proposta e agendar visita") == (
        MOTIVO_VISITA,
        MOTIVO_PROPOSTA,
    )


@pytest.mark.parametrize(
    "texto",
    ["QUERO AGENDAR VISITA", "Quero agendar visita!!!", "  quero   agendar  visita  "],
)
def test_a_normalizacao_cobre_caixa_pontuacao_e_espaco(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_VISITA,)


def test_o_acento_nao_impede_a_deteccao() -> None:
    """Lead digita acento, e a normalizacao dobra antes de comparar."""
    assert gatilhos_de("vamos fechar negócio então") == (MOTIVO_PROPOSTA,)


@pytest.mark.parametrize("texto", ["", "   ", "!!!", "123"])
def test_texto_sem_letra_devolve_vazio(texto: str) -> None:
    assert gatilhos_de(texto) == ()
```

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_gatilhos_de_temperatura.py -v`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.context.gatilhos'`.

- [ ] **Step 3: Escreva a implementação mínima**

Crie `src/mobia/domain/context/gatilhos.py`:

```python
"""Os gatilhos que forcam QUENTE, detectados na fala do lead.

TEC-151, RN-06.3: "pedido explicito de visita, pedido de falar com corretor,
mencao a proposta ou contrato". Pura de proposito: sem I/O, sem banco, sem
chamada paga.

**Deterministico, e nao campo novo no schema do classificador.** O campo
pegaria parafrase que regex nenhum pega, e teria sido a escolha melhor num
orcamento folgado. O orcamento nao e folgado:
`test_a_margem_do_orcamento_do_prompt_e_deliberada` fixa o teto em 655, o
liquido e 648,8 e a margem e **6,2**. O campo `recusou` da TEC-148 custou
17,6 -- tres vezes a margem inteira --, e o ritual manda perguntar "o que sai
do prompt para o novo texto entrar?" antes de subir o numero. Esta card nao
tem resposta para essa pergunta. O detector custa zero de orcamento.

**A assimetria de erro e o INVERSO do opt-out, e por isso a faixa e estrita.**
Em `optout/deteccao.py`, deixar de detectar e violacao de LGPD e detectar
demais e prejuizo comercial, entao a faixa inequivoca e generosa. Aqui:

  - Falso negativo: um lead pronto para agir nao chega ao topo da fila.
    Ruim, e recuperavel -- ele continua na conversa, o score continua
    subindo, e o proximo turno pode disparar.
  - Falso positivo: forca QUENTE PERMANENTEMENTE (a RN-06.3 diz "ate
    intervencao humana") e toca o telefone do corretor. **Nao existe tela
    para desfazer** -- a TEC-192 e a dona da intervencao humana e nao existe.
    O erro e invisivel, permanente, e custa a confianca do corretor na fila,
    que e o unico produto que a RF-06 entrega.

Permanente e sem desfazer vence recuperavel.

**O custo aceito e de recall, e esta declarado:** quem escrever "posso ver o
apartamento amanha?" nao dispara. O detector tambem nao ve o historico --
recebe o texto de um turno so --, entao "e a visita?" referindo-se a um
pedido de dois turnos atras tambem nao dispara.
"""

import re
import unicodedata

MOTIVO_VISITA = "VISITA"
MOTIVO_CORRETOR = "CORRETOR"
MOTIVO_PROPOSTA = "PROPOSTA"

# **O criterio e o VERBO DE ACAO junto do objeto, e nunca o objeto sozinho.**
# E o que faz "quero agendar visita" casar e "voces tem plantao de visita no
# fim de semana?" nao -- o segundo e fala real do corpus
# (`evals/corpus/compra.yaml:318`), e pergunta sobre horario de funcionamento.
# Mesma forma que fecha a colisao no opt-out, onde e o objeto de mensageria
# que faz "pare de me mandar mensagens" nao casar com "pare de mandar
# apartamento sem vaga".
#
# Casam em qualquer posicao da mensagem: com o verbo exigido, a posicao nao
# acrescenta risco, e exigir inicio de frase perderia "bom dia, queria
# agendar visita".
#
# A ordem desta tupla e a ordem da saida de `gatilhos_de`: duas execucoes com
# o mesmo texto devolvem a mesma tupla, e o teste pode comparar por igualdade
# em vez de por conjunto. Mesma escolha de `_CAUSA_POR_FATOR` em
# `auditoria.py`.
_TERMOS_POR_MOTIVO: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        MOTIVO_VISITA,
        (
            "agendar visita",
            "agendar uma visita",
            "agendar a visita",
            "marcar visita",
            "marcar uma visita",
            "marcar a visita",
            "remarcar visita",
            "remarcar uma visita",
            "remarcar a visita",
        ),
    ),
    (
        MOTIVO_CORRETOR,
        (
            "falar com corretor",
            "falar com um corretor",
            "falar com o corretor",
            "falar com um humano",
            "falar com uma pessoa",
            "falar com atendente",
            "falar com um atendente",
        ),
    ),
    (
        MOTIVO_PROPOSTA,
        (
            "fazer proposta",
            "fazer uma proposta",
            "enviar proposta",
            "enviar uma proposta",
            "assinar contrato",
            "assinar o contrato",
            "fechar negocio",
            "fechar o negocio",
        ),
    ),
)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    **E o mesmo transform de `_normalizar` em `optout/deteccao.py`, e as duas
    copias sao deliberadas.** Compartilhar acoplaria um detector comercial a
    um detector de decisao de LGPD: toda mudanca aqui -- um termo novo pedindo
    tolerancia a digito, digamos -- viraria mudanca no caminho regulado, que
    e o ultimo lugar onde se quer efeito colateral. A casa ja tem
    normalizadores por proposito e nao um compartilhado: `_normalizar_regiao`
    em `schemas.py` e `_RUIDO` em `dinheiro.py` sao outros dois.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def gatilhos_de(texto: str) -> tuple[str, ...]:
    """Os motivos da RN-06.3 que esta fala dispara. Vazio quando nenhum.

    **Tupla e nao motivo unico.** "quero fazer uma proposta e agendar visita"
    casa dois, e motivo unico exigiria regra de precedencia -- que aqui
    descarta informacao real, pelo mesmo argumento da D4 da TEC-152 contra
    uma coluna unica de causa.

    Nunca levanta. Texto sem letra nenhuma normaliza para vazio e devolve
    tupla vazia.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return ()
    return tuple(
        motivo
        for motivo, termos in _TERMOS_POR_MOTIVO
        if any(termo in normalizado for termo in termos)
    )
```

- [ ] **Step 4: Rode o teste para confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_gatilhos_de_temperatura.py -v`
Expected: PASS. Se `test_o_objeto_sem_o_verbo_de_acao_nao_dispara` falhar em algum caso, **não relaxe o teste** — o termo que casou é largo demais e sai da lista. Esse teste é o guardião da decisão, não um detalhe.

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/context/gatilhos.py tests/unit/test_gatilhos_de_temperatura.py
git commit -m "feat(TEC-151): a fala do lead passa a nomear o gatilho que forca QUENTE"
```

---

### Task 3: As três colunas e os dois CHECK

**Files:**
- Create: `alembic/versions/0014_temperatura_do_lead.py`
- Modify: `src/mobia/domain/context/models.py` (depois de `campos_recusados`, que termina na linha 138)
- Test: `tests/integration/test_temperatura_no_turno.py`

**Interfaces:**
- Consumes: a tabela `lead_qualification` e o modelo `LeadQualification` (já existem). A migration `0013` é a `head` atual.
- Produces: `LeadQualification.temperatura` (`str | None`), `.temperatura_forcada_em` (`datetime | None`), `.temperatura_forcada_motivos` (`list[str] | None`). As Tasks 5 e 6 leem e gravam as três.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_temperatura_no_turno.py`. Este arquivo cresce nas Tasks 5 e 6; nesta task ele só verifica as invariantes do banco.

```python
"""A temperatura persistida, os dois CHECK, e a borda que notifica.

TEC-151. Integracao: os CHECK vivem no banco, e o forcamento so significa
algo se sobreviver a uma transacao.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque a Task 6 roda `rodar_turno`, que semeia a fala nessa conversa -- os
# testes de turno leem a linha por esta chave. `test_turno.py` redefine os dois
# localmente do mesmo jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(**campos) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste sobrescrever."""
    base = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    return LeadQualification(**{**base, **campos})


async def test_as_tres_colunas_nascem_nulas(session) -> None:
    """`NULL` em `temperatura` significa "nunca recalculada", e e contra esse
    `NULL` que a borda da notificacao compara. Nao ha backfill: um backfill
    para FRIO apagaria a distincao entre "nunca calculei" e "ja era FRIO"."""
    session.add(_linha())
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura is None
    assert carregada.temperatura_forcada_em is None
    assert carregada.temperatura_forcada_motivos is None


async def test_o_check_recusa_forcamento_que_nao_seja_quente(session) -> None:
    """Forcado implica QUENTE. Sem o CHECK, uma linha pode afirmar as duas
    coisas contrarias e nada reclama."""
    session.add(
        _linha(
            temperatura="MORNO",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=["VISITA"],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_o_check_recusa_forcamento_sem_motivo(session) -> None:
    """Molde do `CHECK (cardinality(causas) > 0)` da 0012, e pela mesma razao:
    uma linha que afirma que o lead foi forcado a QUENTE sem nomear o que o
    forcou e a mesma forma de mentira. `NOT NULL` cobriria metade -- o array
    vazio passaria."""
    session.add(
        _linha(
            temperatura="QUENTE",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=[],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_temperatura_sem_forcamento_e_livre(session) -> None:
    """Os dois CHECK sao condicionais a `temperatura_forcada_em`: uma
    temperatura derivada, sem forcamento, aceita qualquer das tres."""
    session.add(_linha(temperatura="FRIO"))
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "FRIO"
    assert carregada.temperatura_forcada_em is None
```

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py -v`
Expected: FAIL. `test_as_tres_colunas_nascem_nulas` falha com `AttributeError` (o modelo não tem `temperatura`), e os dois de `CHECK` falham porque as colunas não existem.

Se em vez disso você vir centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`, **o banco ainda está subindo** — espere e retente. Não é defeito de código.

- [ ] **Step 3: Escreva a migration**

Crie `alembic/versions/0014_temperatura_do_lead.py`:

```python
"""a temperatura do lead, e o forcamento que sobrevive ao recalculo

TEC-151, RN-06.2 e RN-06.3. Tres colunas nulaveis e sem backfill: `NULL` em
`temperatura` significa "linha anterior a esta card, nunca recalculada", e e
contra esse `NULL` que a borda da notificacao da RN-06.5 compara. Um backfill
para FRIO apagaria a distincao entre "nunca calculei" e "ja era FRIO", e o
lead cuja primeira travessia caisse em QUENTE perderia a unica que tem.

**Aqui e nao em `lead_score_audit`.** Duas razoes, e a segunda e a grave: a
trilha grava so quando o score muda (D3 da TEC-152), e um gatilho dispara em
turno em que nenhum dos cinco fatores se move -- nao haveria linha onde
guardar o forcamento; e a trilha tem retencao de 12 meses (RNF-18) e e
expurgavel, entao um lead cujo ultimo registro fosse expurgado voltaria a
parecer nunca-calculado e reemitiria a notificacao de esquentou como se
tivesse acabado de esquentar. E o "carga viva do produto" que a propria
TEC-152 nomeou ao deferir esta decisao.

**Os dois CHECK sao as duas metades da mesma invariante**, no molde dos dois
da 0012: forcado implica QUENTE, e forcado sem motivo nomeado e a mesma forma
de mentira que uma linha da trilha sem causa. Os dois sao condicionais ao
carimbo, entao toda linha anterior a esta card passa com os tres NULL.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura", sa.String(8), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura_forcada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura_forcada_motivos", postgresql.ARRAY(sa.String(16)), nullable=True),
    )
    op.create_check_constraint(
        "ck_lead_qualification_forcada_quente",
        "lead_qualification",
        "temperatura_forcada_em IS NULL OR temperatura = 'QUENTE'",
    )
    op.create_check_constraint(
        "ck_lead_qualification_forcada_motivos",
        "lead_qualification",
        "temperatura_forcada_em IS NULL OR cardinality(temperatura_forcada_motivos) > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_lead_qualification_forcada_motivos", "lead_qualification")
    op.drop_constraint("ck_lead_qualification_forcada_quente", "lead_qualification")
    op.drop_column("lead_qualification", "temperatura_forcada_motivos")
    op.drop_column("lead_qualification", "temperatura_forcada_em")
    op.drop_column("lead_qualification", "temperatura")
```

- [ ] **Step 4: Acrescente as colunas ao modelo**

Em `src/mobia/domain/context/models.py`, logo **depois** do bloco de `campos_recusados` (que termina na linha 138), acrescente:

```python
    # TEC-151, RN-06.2. A temperatura corrente do lead.
    #
    # Materializada, e nao derivada na leitura: e contra ela que a borda da
    # RN-06.5 compara para saber se o lead ACABOU de esquentar. Derivar na
    # leitura daria a temperatura de agora e nao a de antes, e a notificacao
    # dispararia em todo turno quente em vez de na travessia.
    #
    # `NULL` significa "linha anterior a esta card, nunca recalculada", e nao
    # "FRIO": um lead cuja primeira travessia cai em QUENTE tem de emitir, e
    # com NULL colapsado em FRIO ele emitiria igual -- mas um lead que JA era
    # quente antes desta card reemitiria, e a distincao existe para isso.
    #
    # Denormalizacao declarada: ao contrario do `total_novo` da 0012, que a
    # soma dos cinco fatores prende num CHECK, esta coluna guarda uma
    # conclusao que ninguem pode reconferir contra o banco. Se os pesos
    # virarem configuracao (RF-19), ela passa a guardar uma conclusao
    # calculada com os pesos de ontem.
    temperatura: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # TEC-151, RN-06.3. Quando o lead foi forcado a QUENTE por gatilho.
    #
    # `NULL` = nao forcada. Nao nulo = QUENTE ate intervencao humana, e
    # nenhum recalculo de score rebaixa -- e a leitura desta coluna que
    # alimenta o `forcada` de `temperatura_de`, entao a regra de "nao
    # rebaixa" mora no mesmo lugar que a regra de "qual e a temperatura".
    #
    # O carimbo e o do PRIMEIRO forcamento, nao do ultimo: quem grava usa
    # `COALESCE`. E o que "permanece ate intervencao humana" torna
    # interessante -- quando esquentou, e ha quanto tempo ninguem interveio.
    temperatura_forcada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # TEC-151, RN-06.3. Quais gatilhos forcaram, acumulados.
    #
    # Uniao entre turnos e nao sobrescrita, no molde de `campos_recusados`:
    # "primeiro vence" esconde o que veio depois, "ultimo vence" perde
    # justamente o motivo que forcou, e a uniao nao tem esse lado. Duplicata
    # e possivel (o lead pede visita duas vezes) e nao incomoda, mesma razao
    # das duas colunas de array acima: quem le testa pertinencia, nao conta.
    #
    # `NULL` = nao forcada, e e o unico estado que o CHECK admite junto de
    # carimbo nulo. Array vazio com carimbo nao nulo e inalcancavel pelos
    # dois CHECK juntos. Quem le trata NULL e vazio iguais (`or ()`).
    temperatura_forcada_motivos: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(16)), nullable=True
    )
```

**Confira os imports do topo de `models.py` antes de rodar.** `DateTime` e `datetime` podem já estar importados (`LeadScoreAudit` tem `created_at` `timestamptz`); `ARRAY` e `String` certamente estão, por causa de `campos_recusados`. Acrescente só o que faltar — um import duplicado é erro de `ruff check`.

- [ ] **Step 5: Aplique a migration**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: `Running upgrade 0013 -> 0014`. Se der `ConnectionResetError [WinError 64]`, espere e retente — o banco demora mais que o healthcheck diz.

- [ ] **Step 6: Rode os testes para confirmar que passam**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py tests/integration/test_migrations.py -v`
Expected: PASS nos quatro novos e em `test_migrations.py` (que verifica a cadeia de revisões e pode ter uma asserção sobre a `head`).

- [ ] **Step 7: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. Lembre que `alembic` está no escopo do ruff — a migration nova é checada e formatada.

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/0014_temperatura_do_lead.py src/mobia/domain/context/models.py tests/integration/test_temperatura_no_turno.py
git commit -m "feat(TEC-151): a temperatura ganha coluna, e o banco recusa forcamento sem motivo"
```

---

### Task 4: `registrar_recalculo` passa a devolver `Recalculo`

Esta task **não muda comportamento nenhum**. Ela isola a mudança de 7 chamadas de teste da lógica de temperatura, para que um revisor possa aprovar a mecânica sem julgar a regra, e vice-versa.

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py:694-799` (a função `registrar_recalculo`)
- Modify: `tests/integration/test_auditoria_score.py` (7 asserções, listadas abaixo)

**Interfaces:**
- Consumes: `LeadScoreAudit` (já importado em `repositorio.py`).
- Produces: `Recalculo` (dataclass frozen, exportado de `mobia.domain.context.repositorio`) com um campo, `trilha: LeadScoreAudit | None`. `registrar_recalculo` passa a devolver `Recalculo | None`. A Task 5 acrescenta campos a este dataclass; a Task 6 lê `Recalculo` em `turno.py`.

- [ ] **Step 1: Escreva o teste que falha**

Acrescente ao fim de `tests/integration/test_auditoria_score.py`:

```python
async def test_o_none_significa_ausencia_de_sujeito_e_nunca_ausencia_de_mudanca(
    session,
) -> None:
    """As duas respostas negativas de `registrar_recalculo` deixam de ser a
    mesma coisa, e a distincao e a que `score.py` ja faz entre ausencia de
    sujeito e nota igual a zero.

    Sem linha de qualificacao: `None`, e nao ha temperatura a resolver.
    Com linha e sem mudanca: um `Recalculo` cujo `trilha` e `None` -- porque
    a temperatura pode ter se movido num turno em que nenhum fator se moveu.
    """
    await _mensagem(session)
    assert await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA) is None

    await _qualificacao(session)
    primeiro = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert primeiro is not None and primeiro.trilha is not None

    segundo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert segundo is not None
    assert segundo.trilha is None
```

Acrescente `Recalculo` ao import de `mobia.domain.context.repositorio` no topo do arquivo (linha 17).

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py::test_o_none_significa_ausencia_de_sujeito_e_nunca_ausencia_de_mudanca -v`
Expected: FAIL na coleta, com `ImportError: cannot import name 'Recalculo'`.

- [ ] **Step 3: Escreva a implementação**

Em `src/mobia/domain/context/repositorio.py`, **antes** de `registrar_recalculo` (logo depois de `_score_do_registro`, que termina na linha 691), acrescente:

```python
@dataclass(frozen=True)
class Recalculo:
    """O que o passo de recalculo do turno produziu.

    Existe porque o turno precisa de mais de uma resposta do mesmo passo, e
    todas saem da mesma linha travada. Devolver so a trilha obrigaria uma
    segunda leitura -- e nao confiar em leitura de fora e exatamente o motivo
    pelo qual esta funcao rele sob lock.

    `trilha is None` significa "o resultado nao mudou, e nada foi gravado".
    **Nao confunda com o `None` que a funcao devolve**, que significa "nao
    havia sujeito": sem linha de qualificacao nao ha lead a pontuar, e
    `score.py` ja distingue a ausencia de sujeito de uma nota igual a zero.
    """

    trilha: LeadScoreAudit | None
```

`dataclass` já está importado no topo do arquivo (linha 4: `from dataclasses import dataclass, fields`).

Depois troque a assinatura e os dois `return` de `registrar_recalculo`:

```python
async def registrar_recalculo(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> Recalculo | None:
```

- O `return None` do `if estado is None` (linha 745) **fica como está** — é a ausência de sujeito.
- O `return None` do `if not causas` (linha 778) vira `return Recalculo(trilha=None)`.
- O `return linha` do fim (linha 799) vira `return Recalculo(trilha=linha)`.

Acrescente à docstring da função, depois do primeiro parágrafo:

```
    Devolve `None` quando **nao havia estado a pontuar**, e um `Recalculo`
    com `trilha is None` quando havia estado e o resultado foi identico ao
    ultimo registrado. Os dois casos eram o mesmo `None` ate a TEC-151, e ela
    os separou porque a temperatura pode mudar num turno em que nenhum dos
    cinco fatores se move -- um gatilho da RN-06.3 e exatamente isso.
```

- [ ] **Step 4: Atualize as 7 asserções de teste**

Em `tests/integration/test_auditoria_score.py`, **exatamente estas sete** — as outras cinco chamadas (linhas 193, 212, 235, 475, 560) ignoram o retorno ou testam a ausência de sujeito, e **não mudam**:

| linha | de | para |
|---|---|---|
| 179 | `gravada = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)` | `recalculo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)` e, na asserção seguinte, `gravada = recalculo.trilha` após `assert recalculo is not None` |
| 196 | `assert await registrar_recalculo(...) is None` | `segundo = await registrar_recalculo(...)` + `assert segundo is not None and segundo.trilha is None` |
| 220 | `gravada = await registrar_recalculo(...)` | mesmo padrão da 179 |
| 277 | `gravada = await registrar_recalculo(...)` | mesmo padrão da 179 |
| 490 | `escrita_antes = await registrar_recalculo(recente, ...)` | `escrita_antes = (await registrar_recalculo(recente, ...)).trilha` — a asserção da linha 502 (`escrita_antes is not None and escrita_depois is not None`) continua valendo |
| 500 | `escrita_depois = await registrar_recalculo(antiga, ...)` | mesmo padrão da 490 |
| 519 | `terceira = await registrar_recalculo(seguinte, ...)` | `terceira = (await registrar_recalculo(seguinte, ...)).trilha` |

**Atenção na linha 235.** `test_sem_linha_de_qualificacao_nao_ha_o_que_auditar` assere `is None` **e continua correta sem tocar em nada** — não há linha de qualificação, e a função devolve `None`. Esse teste passa a ser o que prova que o sentinel `None` ainda significa "não havia sujeito". Se você "consertá-lo" para `.trilha is None`, ele passa a testar outra coisa e a distinção fica sem guarda.

**Nas linhas 490 e 500, o `.trilha` direto sem checar `None` é seguro** porque o teste acabou de criar a linha de qualificação — mas o mypy só cobre `src`, então nenhum gate reclama. Se preferir, use a forma de duas linhas.

- [ ] **Step 5: Rode os testes para confirmar que passam**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v`
Expected: PASS em todos. Se algum falhar com `AttributeError: 'Recalculo' object has no attribute 'total_novo'`, você deixou um `.trilha` para trás.

- [ ] **Step 6: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. O mypy é quem pega o chamador de `turno.py:338`, que ignora o retorno — ele continua válido, porque ignorar um retorno novo não é erro de tipo.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/context/repositorio.py tests/integration/test_auditoria_score.py
git commit -m "refactor(TEC-151): o recalculo passa a distinguir sem sujeito de sem mudanca"
```

---

### Task 5: O gancho resolve a temperatura

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (o `Recalculo` da Task 4 e o corpo de `registrar_recalculo`)
- Test: `tests/integration/test_temperatura_no_turno.py` (acrescenta)

**Interfaces:**
- Consumes: `temperatura_de`, `Temperatura` da Task 1; `esta_qualificado` de `mobia.domain.context.qualificacao`; as três colunas da Task 3; o `Recalculo` da Task 4.
- Produces: `registrar_recalculo(session, *, channel, conversation_key, gatilhos: tuple[str, ...] = ()) -> Recalculo | None`, e o `Recalculo` cresce para `trilha`, `temperatura: Temperatura`, `anterior: Temperatura | None`, `gatilhos: tuple[str, ...]`, `total: int`. A Task 6 consome os quatro últimos.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/integration/test_temperatura_no_turno.py`:

```python
import uuid

from mobia.domain.context.gatilhos import MOTIVO_PROPOSTA, MOTIVO_VISITA
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt


async def _mensagem(session, *, texto: str = "oi") -> None:
    """Uma fala de ENTRADA nao bloqueada, que e o que o engajamento conta."""
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            conversation_key=CONVERSA,
            direction=MessageDirection.INBOUND,
            role=MessageRole.LEAD,
            content_type=MessageContentType.TEXT,
            text_body=encrypt(texto, aad_de(identificador, "text_body")),
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()


async def test_o_primeiro_recalculo_grava_a_temperatura_derivada(session) -> None:
    """Quatro obrigatorios (20), IMEDIATA (25), uma mensagem (10), sem forma de
    pagamento (6) = 61, faixa MORNO. `anterior` e None porque a coluna era."""
    session.add(_linha())
    await session.commit()
    await _mensagem(session)

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.total == 61
    assert obtido.anterior is None
    assert obtido.temperatura is Temperatura.MORNO

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "MORNO"
    assert carregada.temperatura_forcada_em is None


async def test_o_gatilho_forca_quente_e_nao_toca_o_score(session) -> None:
    """O cenario 2 da card. O score continua sendo o que era."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()
    await _mensagem(session)

    obtido = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    assert obtido is not None
    assert obtido.temperatura is Temperatura.QUENTE
    assert obtido.total < 70

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
    assert carregada.temperatura_forcada_em is not None
    assert carregada.temperatura_forcada_motivos == [MOTIVO_VISITA]


async def test_o_forcamento_sobrevive_a_um_recalculo_sem_gatilho(session) -> None:
    """O cenario 3 da card, e o teste que morre se `forcada` deixar de ler a
    coluna: o turno que rebaixaria e justamente um turno SEM gatilho."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.temperatura is Temperatura.QUENTE
    assert obtido.anterior is Temperatura.QUENTE


async def test_o_carimbo_e_o_do_primeiro_forcamento(session) -> None:
    """`COALESCE` e nao sobrescrita: "permanece ate intervencao humana" torna
    interessante QUANDO esquentou, e ha quanto tempo ninguem interveio."""
    session.add(_linha())
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()
    primeira = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert primeira is not None
    carimbo = primeira.temperatura_forcada_em

    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_PROPOSTA,)
    )
    await session.commit()

    session.expire_all()
    segunda = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert segunda is not None
    assert segunda.temperatura_forcada_em == carimbo
    assert segunda.temperatura_forcada_motivos == [MOTIVO_VISITA, MOTIVO_PROPOSTA]


async def test_o_teto_morno_vale_no_banco(session) -> None:
    """A linha 2 da tabela da D6: `intencao = None`, resto completo, IMEDIATA,
    a vista, engajamento -- 70 com `esta_qualificado` False. Sem o teto ele
    gravaria QUENTE e faria o telefone do corretor tocar."""
    session.add(_linha(intencao=None, forma_pagamento=FormaPagamento.A_VISTA.value))
    await session.commit()
    for _ in range(6):
        await _mensagem(session)

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.total >= 70
    assert obtido.temperatura is Temperatura.MORNO


async def test_o_turno_sem_mudanca_de_score_ainda_resolve_a_temperatura(session) -> None:
    """A guarda contra a regressao que a Task 5 inverte.

    Se alguem restaurar o `return None` antecipado do `if not causas`, este
    teste morre: e um turno em que nenhum dos cinco fatores se move e o
    gatilho e a unica coisa que aconteceu.
    """
    session.add(_linha())
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    obtido = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    assert obtido is not None
    assert obtido.trilha is None
    assert obtido.temperatura is Temperatura.QUENTE

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
```

- [ ] **Step 2: Rode os testes para confirmar que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py -v`
Expected: os quatro da Task 3 passam; os seis novos falham — `TypeError: registrar_recalculo() got an unexpected keyword argument 'gatilhos'` nos que passam gatilho, e `AttributeError: 'Recalculo' object has no attribute 'total'` nos outros.

- [ ] **Step 3: Escreva a implementação**

Em `src/mobia/domain/context/repositorio.py`:

**3a. Imports.** Acrescente ao import de `sqlalchemy` (linha 9) o `String` e o `cast`; acrescente `ARRAY` ao import de `sqlalchemy.dialects.postgresql` (linha 10); e acrescente os dois imports de domínio:

```python
from sqlalchemy import String, cast, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
...
from mobia.domain.context.qualificacao import esta_qualificado
from mobia.domain.context.temperatura import Temperatura, temperatura_de
```

Não há ciclo: `qualificacao.py` importa só `schemas` e `models`, e `temperatura.py` importa só `score`.

**3b. `Recalculo` cresce.** Acrescente os quatro campos, com a docstring explicando cada um:

```python
@dataclass(frozen=True)
class Recalculo:
    """O que o passo de recalculo do turno produziu.

    Existe porque o turno precisa de mais de uma resposta do mesmo passo, e
    todas saem da mesma linha travada. Devolver so a trilha obrigaria uma
    segunda leitura -- e nao confiar em leitura de fora e exatamente o motivo
    pelo qual esta funcao rele sob lock.

    `trilha is None` significa "o resultado nao mudou, e nada foi gravado".
    **Nao confunda com o `None` que a funcao devolve**, que significa "nao
    havia sujeito": sem linha de qualificacao nao ha lead a pontuar, e
    `score.py` ja distingue a ausencia de sujeito de uma nota igual a zero.

    `anterior is None` e a coluna `temperatura` nula -- lead nunca
    recalculado, ou linha anterior a TEC-151. **Nao e sinonimo de FRIO**: a
    borda da RN-06.5 dispara quando `anterior` nao era QUENTE e agora e, e um
    lead cujo primeiro recalculo cai em QUENTE de fato esquentou.

    `gatilhos` sao os desta fala, e nao os acumulados na coluna: e o que o
    evento do log precisa dizer sobre POR QUE esquentou agora. Vazio quando a
    temperatura veio da faixa.

    `total` acompanha para o log poder distinguir um QUENTE de faixa (70+) de
    um QUENTE forcado sobre score baixo, que sao fatos operacionais bem
    diferentes para quem le.
    """

    trilha: LeadScoreAudit | None
    temperatura: Temperatura
    anterior: Temperatura | None
    gatilhos: tuple[str, ...]
    total: int
```

**3c. A assinatura ganha os gatilhos:**

```python
async def registrar_recalculo(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    gatilhos: tuple[str, ...] = (),
) -> Recalculo | None:
```

**3d. A resolução da temperatura**, inserida **depois** do bloco `novo = calcular_score(...)` (que termina na linha 762) e **antes** da leitura de `ultimo` (linha 764):

```python
    # A temperatura sai da MESMA linha travada que o score, e o `qualificado`
    # tambem. Nao vem do `antes` de `turno.py`: aquele foi lido por
    # `montar_contexto` numa OUTRA sessao, antes do bloco transacional, e um
    # turno concorrente da mesma conversa pode ter commitado no intervalo --
    # o teto seria aplicado sobre qualificacao velha. Mesma razao pela qual o
    # estado vem do `FOR UPDATE` daqui, e nao de `depois_do_estado`.
    #
    # `recusados` da mesma linha, `or ()` pela razao de sempre: NULL (linha
    # anterior a TEC-148) e {} (registrou, sem recusa) sao estados diferentes
    # na coluna, e esta leitura trata os dois iguais.
    qualificado = esta_qualificado(estado, frozenset(estado.campos_recusados or ()))

    # As duas metades do forcamento, e a persistida e a que o cenario 3 da
    # card exige. O segundo termo forca AGORA (o pedido de visita chegando
    # neste turno); o primeiro MANTEM forcado depois -- e e o unico que
    # responde ao cenario 3, porque o turno que rebaixaria e justamente um
    # turno SEM gatilho: o lead pediu visita ha tres turnos, agora so
    # respondeu "ok", e `gatilhos` esta vazio. Sem o termo persistido,
    # `temperatura_de` voltaria a olhar o score e devolveria FRIO.
    forcada = estado.temperatura_forcada_em is not None or bool(gatilhos)

    anterior = Temperatura(estado.temperatura) if estado.temperatura else None
    temperatura = temperatura_de(novo, qualificado=qualificado, forcada=forcada)

    # `or gatilhos` no teste, e nao so a mudanca de temperatura: um lead que
    # JA era QUENTE forcado e menciona proposta nao muda de temperatura, mas o
    # motivo novo tem de entrar na coluna. Duplicata e possivel por este
    # caminho (o lead pede visita duas vezes) e nao incomoda: quem le testa
    # pertinencia, nao conta -- mesma aceitacao das duas colunas de array
    # vizinhas.
    if temperatura is not anterior or gatilhos:
        valores: dict[str, Any] = {"temperatura": temperatura.value}
        if gatilhos:
            valores["temperatura_forcada_em"] = func.coalesce(
                LeadQualification.temperatura_forcada_em, func.clock_timestamp()
            )
            # A uniao mora no SQL e nao numa leitura previa em Python, pela
            # razao que `gravar_estado` ja documentou para `campos_recusados`:
            # dois turnos concorrentes leriam o mesmo array, cada um uniria o
            # seu, e o mais lento sobrescreveria em silencio.
            #
            # `coalesce` porque `NULL || {'VISITA'}` e NULL em Postgres, e
            # toda linha anterior a esta card tem NULL aqui.
            valores["temperatura_forcada_motivos"] = func.coalesce(
                LeadQualification.temperatura_forcada_motivos,
                literal_column("'{}'::varchar[]"),
            ).op("||")(cast(list(gatilhos), ARRAY(String(16))))
        await session.execute(
            update(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .values(**valores)
        )
```

`Any` já está importado (linha 6: `from typing import Any`).

**3e. Os três `return` passam a carregar a temperatura.** O `if estado is None: return None` fica; os outros dois viram:

```python
    if not causas:
        return Recalculo(
            trilha=None,
            temperatura=temperatura,
            anterior=anterior,
            gatilhos=gatilhos,
            total=novo.total,
        )
```

e, no fim:

```python
    await session.flush()
    return Recalculo(
        trilha=linha,
        temperatura=temperatura,
        anterior=anterior,
        gatilhos=gatilhos,
        total=novo.total,
    )
```

**3f. A docstring da função ganha o parágrafo da temperatura:**

```
    **A temperatura e resolvida ANTES da trilha, e a ordem e o ponto
    (TEC-151).** Ate esta card a funcao retornava cedo quando `causas` estava
    vazio; nao pode mais, porque um gatilho da RN-06.3 dispara em turno em que
    nenhum dos cinco fatores se move -- o lead pede visita, e o `return None`
    antecipado engoliria o forcamento. Ha teste de guarda para isso:
    `test_o_turno_sem_mudanca_de_score_ainda_resolve_a_temperatura`.
```

- [ ] **Step 4: Rode os testes para confirmar que passam**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py tests/integration/test_auditoria_score.py -v`
Expected: PASS em todos os dez do arquivo novo e em todos os de `test_auditoria_score.py`. Este último é a rede: nenhuma das asserções da TEC-152 pode ter mudado de resultado.

Se `test_o_carimbo_e_o_do_primeiro_forcamento` falhar comparando carimbos, confira se o `session.expire_all()` está lá — sem ele o identity map devolve a instância que a sessão já tem, com o valor anterior ao `UPDATE`, e o teste passa por acidente ou falha por outro motivo.

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/context/repositorio.py tests/integration/test_temperatura_no_turno.py
git commit -m "feat(TEC-151): o recalculo passa a resolver a temperatura na linha que ja travou"
```

---

### Task 6: O turno lê a fala e emite a borda

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (imports; linha ~135, ao lado do `pedido_de_optout`; linha 338, a chamada do gancho; depois do bloco `lead.qualificado`, na linha ~377)
- Modify: `tests/conftest.py:93-119` e `:254-271` (o harness precisa deixar o teste escolher o texto da fala — ver Step 1)
- Test: `tests/integration/test_temperatura_no_turno.py` (acrescenta)

**Interfaces:**
- Consumes: `gatilhos_de` da Task 2; `Temperatura` da Task 1; `Recalculo` e a assinatura nova de `registrar_recalculo` da Task 5.
- Produces: o evento de log `lead.esquentou`, com as chaves `channel`, `message_id`, `motivos`, `total`. Nada de código depende dele — o consumidor é E7, que não existe.

- [ ] **Step 1a: Deixe o harness escolher o texto da fala**

`rodar_turno` semeia a entrada por `_entrada_do_lead`, que **fixa o texto** em `"quero saber mais sobre apartamentos"`. Nenhum teste de turno consegue hoje fazer o lead pedir visita, e sem isso a Task 6 não é testável ponta a ponta.

Em `tests/conftest.py`, dê um parâmetro com default às duas funções. **O default é o texto de hoje**, então nenhum dos testes existentes muda de comportamento:

```python
async def _entrada_do_lead(
    session: AsyncSession, *, texto: str = "quero saber mais sobre apartamentos"
) -> Message:
```

e, no corpo, troque o literal pelo parâmetro:

```python
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
```

Em `rodar_turno`, repasse:

```python
    async def _rodar(
        session,
        classificador,
        outbound,
        resumidor,
        contador,
        moderador=None,
        *,
        texto: str = "quero saber mais sobre apartamentos",
    ) -> str:
        from mobia.domain.agente.turno import executar_turno

        linha = await _entrada_do_lead(session, texto=texto)
```

**`texto` é keyword-only em `_rodar`**, depois do `moderador` posicional: os testes de moderação passam o moderador na sexta posição (`test_moderacao_de_entrada.py:67`), e um sétimo posicional convidaria a confundir os dois.

Acrescente à docstring de `_entrada_do_lead`:

```
    O `texto` e parametro desde a TEC-151, cujos gatilhos da RN-06.3 sao
    detectados na fala do lead -- um turno que precisa que o lead peca visita
    nao tem outro jeito de dizer isso. O default e o texto de sempre, entao
    nenhum teste anterior muda.
```

- [ ] **Step 1b: Escreva os testes que falham**

Acrescente a `tests/integration/test_temperatura_no_turno.py`. As fixtures são as mesmas que `tests/integration/test_turno.py` usa, e a captura de log é a mesma que ele usa para `lead.qualificado` (`caplog.at_level(logging.INFO)` + contagem sobre `caplog.records`) — **não introduza um segundo jeito de capturar log neste repo**.

Acrescente `import logging` ao topo do arquivo. Os três nomes de `schemas` já estão importados desde a Task 3.

```python
async def test_o_pedido_de_visita_no_turno_forca_quente_e_emite(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """A card ponta a ponta: o lead pede visita, a temperatura vira QUENTE
    apesar do score baixo, e o evento da RN-06.5 sai uma vez."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    with caplog.at_level(logging.INFO):
        resultado = await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            texto="quero agendar visita",
        )

    assert resultado == "respondido"

    # `expire_all` porque o turno gravou por OUTRA sessao (`get_sessionmaker()`
    # dentro de `executar_turno`), e o identity map desta ainda tem a instancia
    # que este teste adicionou -- sem isto, `get` devolve o objeto velho e o
    # teste passa ou falha por acidente.
    session.expire_all()
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
    assert carregada.temperatura_forcada_motivos == [MOTIVO_VISITA]
    assert carregada.temperatura_forcada_em is not None
    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 1


async def test_a_borda_nao_reemite_no_turno_seguinte(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """O evento e da travessia, nao do estado: um lead que continua QUENTE nao
    reemite. E a razao pela qual `Recalculo.anterior` existe -- sem ele a
    RN-06.5 viraria um ping por mensagem."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    caplog.clear()

    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            texto="quero agendar visita de novo",
        )

    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 0


async def test_a_fala_bloqueada_pela_moderacao_nao_forca_quente(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """Nao ha guarda para isto no codigo, e o teste existe justamente por isso.

    `executar_turno` retorna por `_entregar_texto_fixo` quando a moderacao
    bloqueia a entrada, antes do bloco transacional -- entao a fala bloqueada
    nunca chega ao gancho, e a propriedade sai de graca. O teste a fixa para
    que uma reordenacao futura nao a perca em silencio.

    E coerente com o contrato de `mensagens_do_lead`, que exclui
    `bloqueada_em IS NOT NULL` da contagem de engajamento pela mesma razao: um
    turno que o resto do produto trata como nao-dito nao pode virar sinal aqui.
    """
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            moderador_fake(bloqueia_entrada=True),
            texto="quero agendar visita",
        )

    session.expire_all()
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura is None, "a fala bloqueada nao chega ao gancho"
    assert carregada.temperatura_forcada_em is None
    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 0
```

- [ ] **Step 2: Rode os testes para confirmar que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py -v -k "turno or borda or bloqueada"`
Expected: FAIL — a coluna `temperatura` fica `NULL` porque o turno não passa gatilho nenhum, e `lead.esquentou` não existe.

- [ ] **Step 3: Escreva a implementação**

Em `src/mobia/domain/agente/turno.py`:

**3a. Imports.** Acrescente:

```python
from mobia.domain.context.gatilhos import gatilhos_de
from mobia.domain.context.temperatura import Temperatura
```

**3b. A detecção**, logo depois do `pedido_de_optout` (linha 135):

```python
    # Ao lado do opt-out de proposito: mesmo insumo (o texto decifrado), mesmo
    # ponto do fluxo, e nenhuma consulta. A fala bloqueada pela moderacao nunca
    # chega ao gancho -- `executar_turno` retorna por `_entregar_texto_fixo`
    # antes do bloco transacional --, entao um turno que o resto do produto
    # trata como nao-dito nao forca QUENTE, e isso sai de graca.
    #
    # `if corpo else ()` e nao `bool(corpo) and ...` porque a saida e uma
    # tupla, nao um bool: so a forma condicional estreita `corpo` de
    # `str | None` para `str` E preserva o tipo de retorno.
    gatilhos = gatilhos_de(corpo) if corpo else ()
```

**3c. A chamada do gancho** (linha 338) passa a capturar o retorno e a repassar os gatilhos:

```python
        recalculo = await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            gatilhos=gatilhos,
        )
```

**3d. O evento**, depois do bloco de `lead.qualificado` (que termina na linha 377):

```python
    # A borda, e nao o estado: um lead que continua QUENTE nao reemite, senao
    # a RN-06.5 viraria um ping por mensagem. `anterior` sai da coluna
    # `temperatura`, e nao da trilha de auditoria -- a trilha grava so quando
    # o score muda e tem retencao de 12 meses (RNF-18), entao um lead cujo
    # ultimo registro fosse expurgado voltaria a parecer nunca-calculado e
    # reemitiria como se tivesse acabado de esquentar.
    #
    # `anterior is None` (coluna nula) com QUENTE emite: um lead cujo primeiro
    # recalculo ja cai em QUENTE de fato esquentou, e tratar NULL como "ja era
    # quente" perderia a unica travessia que ele tem.
    #
    # Depois do commit, como `lead.qualificado`: logar uma transicao que o
    # rollback desfez e mentir para quem le o log.
    #
    # **Isto NAO e a notificacao da RN-06.5, e a lacuna esta declarada no
    # desenho.** A entrega depende do handoff (E7), que nao existe -- nao ha
    # epico, nao ha consumidor, e o conteudo da mensagem esta fora do escopo
    # da card. Os 60 segundos da regra sao triviais porque o evento e sincrono
    # no turno; o que nao existe e alguem do outro lado.
    #
    # O texto do lead nao entra: `motivos` e vocabulario nosso, nao fala dele.
    # Mesma regra de PII que `moderacao.entrada_bloqueada` respeita.
    #
    # Este evento herda o defeito de reemissao de `lead.qualificado`, pela
    # mesma causa: o total nao e monotono desde a TEC-148, entao a borda por
    # faixa e atravessavel nos dois sentidos para o MESMO lead. O forcado nao
    # volta; o derivado volta. Declarado, nao corrigido -- corrigir exige
    # estado persistido de "ja emiti uma vez".
    if (
        recalculo is not None
        and recalculo.anterior is not Temperatura.QUENTE
        and recalculo.temperatura is Temperatura.QUENTE
    ):
        log.info(
            "lead.esquentou",
            channel=message.channel,
            message_id=str(message.id),
            motivos=list(recalculo.gatilhos),
            total=recalculo.total,
        )
```

- [ ] **Step 4: Rode os testes para confirmar que passam**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_temperatura_no_turno.py -v`
Expected: PASS em todos os treze.

- [ ] **Step 5: Rode a suíte de turno inteira, que é a que este passo pode quebrar**

Run: `./.venv/Scripts/python.exe -u -m pytest tests/integration/test_turno.py tests/integration/test_turno_optout.py tests/integration/test_moderacao_de_entrada.py -v`
Expected: PASS. Se algum falhar com `ConnectionResetError` ou erro de Redis, **rode o arquivo sozinho antes de culpar sua mudança** — esses três flakeiam sob carga.

- [ ] **Step 6: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/agente/turno.py tests/conftest.py tests/integration/test_temperatura_no_turno.py
git commit -m "feat(TEC-151): o pedido do lead passa a esquentar o lead em producao"
```

---

### Task 7: Os comentários que passaram a mentir, e a emenda ao SRS

Esta task existe porque `CLAUDE.md` trata comentário desatualizado como defeito, e o teto `MORNO` **torna falsa uma afirmação existente**. Não é limpeza: na TEC-146, um comentário que justificava a ordem de duas checagens com um perigo inexistente escondeu um bug que gravava orçamento 40% abaixo do que o lead dissera, e sobreviveu a duas revisões porque quem lia acreditava nele.

**Files:**
- Modify: `src/mobia/domain/context/score.py:118-126` (docstring de `calcular_score`)
- Modify: `tests/unit/test_regras_de_recusa.py:169-172` (docstring de `test_o_score_para_de_pontuar_a_completude_do_campo_recusado`)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (linha ~15, a tabela; linha ~199, a RN-06.2)
- Modify: `docs/superpowers/specs/2026-09-03-tec-151-temperatura-do-lead-design.md` (linha 3, o status)

**Interfaces:** nenhuma. Esta task não muda comportamento e não tem teste novo.

- [ ] **Step 1: Conserte a docstring de `calcular_score`, que passou a mentir**

O texto atual afirma que o lead `VENDER_IMOVEL` com total 70 fica em *"faixa QUENTE"*. **Com o teto da emenda E-01, fica `MORNO`.** Em `src/mobia/domain/context/score.py`, substitua o parágrafo das linhas 118-126 por:

```
    **Este score nao sabe se o lead esta qualificado.** Nenhum dos cinco
    fatores consulta `esta_qualificado`, e completude conta campos, nao a
    decisao. Um lead com `intencao=VENDER_IMOVEL` -- que a RN-03.4 manda
    direto para handoff e o SDR nao qualifica --, resto preenchido, urgencia
    `IMEDIATA`, pagamento a vista e seis mensagens soma **70**, com
    `esta_qualificado` False; um lead qualificado que so nao disse como
    pagaria soma **66**.

    **A TEC-151 fechou a consequencia disso, e nao aqui.** Este score continua
    sem saber da qualificacao -- e deliberado, e nada nesta funcao mudou --,
    mas quem deriva a temperatura combina os dois: `temperatura_de`
    (`context/temperatura.py`) recebe `qualificado` e aplica teto `MORNO`, de
    forma que o primeiro exemplo acima NAO chega a QUENTE. E emenda E-01 a
    RN-06.2, e o motivo foi a RN-06.5: QUENTE faz o telefone do corretor
    tocar. **Quem for ordenar a fila continua tendo de combinar o total com
    `esta_qualificado`, e nunca usar o total sozinho** -- a temperatura ja o
    faz, o total cru nao.
```

- [ ] **Step 2: Conserte a docstring do teste que prevê a TEC-151 no futuro**

Em `tests/unit/test_regras_de_recusa.py`, a docstring de `test_o_score_para_de_pontuar_a_completude_do_campo_recusado` diz *"a TEC-151 ordena a fila por um numero que a qualificacao contradiz"* — previsão que deixou de ser verdade. Substitua por:

```python
    """A divergencia que a TEC-150 declarou e esta card fecha: sem isto,
    `esta_qualificado` e o score contam historias contrarias sobre o mesmo
    lead. A TEC-151 fechou a outra metade -- `temperatura_de` aplica teto
    MORNO a lead nao-qualificado --, mas o total cru continua nao sabendo da
    qualificacao, e e por isso que este teste segue valendo."""
```

- [ ] **Step 3: Escreva a emenda ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`:

**3a.** Acrescente a linha à tabela do topo, depois da linha da TEC-148 (linha ~15). A numeração é **por regra**, e a RN-06.2 nunca foi emendada — há três `E-01` na tabela hoje:

```
> | E-01 | RN-06.2 | [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) | 03/09/2026 |
```

**3b.** Acrescente o item aninhado **logo abaixo** da RN-06.2 (linha 199), **sem tocar no texto de 22/08**:

```
  - **Emenda E-01 (TEC-151, 03/09/2026):** `QUENTE` por faixa passa a exigir também `esta_qualificado` (RN-05.3); um lead não-qualificado com score ≥ 70 fica em `MORNO`. Os gatilhos da RN-06.3 ignoram o teto — quem pede visita está pronto para agir mesmo sem os quatro campos obrigatórios. O motivo é a RN-06.5: a TEC-150 declarou dois estados alcançáveis que somam 70 com `esta_qualificado` False — um deles com `intencao = None`, cuja intenção o sistema nunca determinou —, e enquanto nada consumia o número declarar bastava. Com a notificação ao corretor, o número passou a fazer um telefone tocar. Os cortes de 70 e 40 **não** se mexeram: perguntou-se em 02/09/2026 se deveriam recalibrar para o teto real do score (75 sem catálogo) e a decisão foi aceitar a consequência — só três totais alcançam 70 hoje, `{70, 72, 75}`, então `QUENTE` por faixa é uma conjunção de quase-máximos e não uma faixa.
```

- [ ] **Step 4: Atualize o status do desenho**

Em `docs/superpowers/specs/2026-09-03-tec-151-temperatura-do-lead-design.md`, linha 3:

```
**Status:** desenhado em 2026-09-03, implementado em 2026-09-03 na branch `feat/tec-151-temperatura-do-lead`.
```

- [ ] **Step 5: Rode a suíte inteira**

Run: `./.venv/Scripts/python.exe -u -m pytest -v`
Expected: PASS. **Leva ~7,5 minutos e 857 testes** (mais os ~23 deste plano) — saída silenciosa por vários minutos com `-q` é normal, e é por isso que este passo usa `-u -m pytest -v`. Se um teste de integração falhar com `ConnectionResetError` ou erro de Redis, rode o arquivo sozinho antes de concluir qualquer coisa.

- [ ] **Step 6: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/context/score.py tests/unit/test_regras_de_recusa.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-03-tec-151-temperatura-do-lead-design.md
git commit -m "docs(TEC-151): a RN-06.2 passa a exigir qualificacao para QUENTE por faixa"
```

---

## Cobertura da spec

| item da spec | task |
|---|---|
| D1 — a faixa como função pura, `Temperatura`, cortes, keyword-only, `Score` e não `int` | 1 |
| D2 — detector determinístico, tupla de motivos, assimetria invertida, `plantao de visita` | 2 |
| D2 — sobreposição com a RN-04.6 (lacuna 6) | 2 (docstring do módulo) |
| D3 — três colunas, os dois `CHECK`, `COALESCE` no carimbo, união dos motivos | 3, 5 |
| D3 — por que aqui e não em `lead_score_audit` | 3 (docstring da migration) |
| D4 — o forçamento não é rebaixado, as duas metades de `forcada` | 5 |
| D5 — o gancho cresce, `Recalculo`, `None` só para ausência de sujeito, ordem invertida | 4, 5 |
| D5 — `qualificado` da linha travada e não do `antes` | 5 |
| D6 — o teto `MORNO`, a borda, `lead.esquentou`, PII, depois do commit | 1 (teto), 6 (borda) |
| Fluxo — `gatilhos_de(corpo)` no topo, fala bloqueada não força | 6 |
| Testes — basenames distintos, os quatro cenários, os três extras, o de guarda | 1, 2, 5, 6 |
| Emenda `E-01` à RN-06.2 + tabela | 7 |
| Lacuna 1 — nada limpa o forçamento | 3 (comentário do modelo), 7 (nada a fazer no código) |
| Lacuna 2 — notificação não entregue | 6 (comentário do evento) |
| Lacuna 3 — `temperatura` denormalizada | 3 (comentário do modelo) |
| Lacuna 4 — `QUENTE` é conjunção de quase-máximos | 1 (docstring do módulo), 7 (emenda) |
| Lacuna 5 — esquentar, esfriar, reesquentar | 6 (comentário do evento) |
| Lacuna 7 — o detector não vê o histórico | 2 (docstring do módulo) |
