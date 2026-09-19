# TEC-272 — Oferta de corretor ao confirmar: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anexar uma oferta de transferência para corretor quando o lead pergunta se fala com um robô — e só quando o texto que ele vai receber ainda não oferece um.

**Architecture:** Três funções em `domain/agente/identificacao.py`: `perguntou_se_e_robo` sobre a fala do lead, `ja_oferece_corretor` sobre o texto final de saída, e `texto_com_oferta` compondo as duas. O `turno.py` ganha **uma linha**, logo depois do bloco `if identificar:` e antes de `quebrar_em_mensagens`, os dois em `turno.py` (**símbolo e não linha**: os números que este plano citava envelheceram três vezes na própria branch — ver a D5 do desenho) — a regra vive na função para que o unitário exercite o código de produção em vez de uma cópia dela. Zero do orçamento do prompt; nada em `SISTEMA_DO_AGENTE`.

**Tech Stack:** Python 3.13, `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), `re` + `unicodedata`, `ruff`, `mypy`.

**Spec:** [`docs/superpowers/specs/2026-09-18-tec-272-oferta-de-corretor-ao-confirmar-design.md`](../specs/2026-09-18-tec-272-oferta-de-corretor-ao-confirmar-design.md) — o plano argumenta a partir do desenho; leia os dois.

## Global Constraints

- **Branch:** `feat/tec-272-oferta-de-corretor-ao-confirmar`. Termina em `git push` e PR, nunca em merge local.
- **Os três gates estáticos, com o escopo exato do CI**, antes de cada commit:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Acentos:** o texto da oferta é **texto que o lead recebe**, então leva acento (TEC-267). Comentários e docstrings em `src/` e `tests/`, **sem** acento — exceto valor citado, que segue o valor.
- **`line-length = 100`**, `select = ["E", "F", "I", "UP", "B"]`, mypy só em `src`.
- **Orçamento pago: 60 chamadas** (3 frasagens × 20), modelo `claude-sonnet-5`, só na Task 4. Autorizado até 80. Nenhuma chamada além disso sem pedir de novo.
- **Nada entra em `SISTEMA_DO_AGENTE`** nem em nenhum prompt. O detector custa zero de orçamento, que é o argumento inteiro da D6.

---

### Task 1: `perguntou_se_e_robo`, o detector de entrada

**Files:**
- Modify: `src/mobia/domain/agente/identificacao.py` (acrescenta ao fim)
- Test: `tests/unit/test_pergunta_se_e_robo.py` (criar)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `perguntou_se_e_robo(texto: str) -> bool`.

Sem chamada paga. Função pura de string.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_pergunta_se_e_robo.py`:

```python
"""A faixa do detector da pergunta "voce e um robo?" (TEC-272).

**A afirmacao forte deste arquivo e a NEGATIVA, e a razao esta na D3 do
desenho.** Nao existe fala real deste eixo em `evals/corpus/` -- zero
ocorrencias nos cinco arquivos --, entao todo termo do detector e invencao, e
medi-lo contra as frasagens que ele foi escrito para pegar seria medi-lo
contra o proprio vocabulario. O que da para provar e que ele nao dispara em
nenhum dos 147 turnos de fala real que o corpus tem, e e isso que
`test_nao_dispara_em_nenhum_turno_do_corpus` faz.

**"mil e tantos turnos" era numero inventado, e saiu na fix round 5.** Medido
em 18/09/2026 com `carregar(CORPUS)`: os cinco arquivos dao **53 conversas e
147 turnos de lead**. A consequencia nao e so a honestidade da frase -- 147
turnos sao uma amostra pequena, entao o teste do corpus prova menos do que
parecia, e a caca por fala inventada carrega mais peso do que se pensava.

A assimetria que justifica a faixa estrita e a de `gatilhos.py`, nao a do
opt-out: falso negativo devolve o comportamento de hoje, falso positivo gruda
uma oferta de corretor numa fala que nao pediu -- que e literalmente o segundo
criterio de aceite desta card.
"""

from pathlib import Path

import pytest

from mobia.domain.agente.identificacao import perguntou_se_e_robo
from mobia.evals.corpus import carregar

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


@pytest.mark.parametrize(
    "texto",
    [
        "vc e um robo?",
        "você é um robô?",
        "to falando com uma pessoa?",
        "isso e automatico ou tem alguem ai?",
        "voce e humano ou maquina?",
        "isso aqui é um bot?",
        "tem alguém aí ou é tudo automático?",
    ],
)
def test_a_pergunta_dispara(texto: str) -> None:
    """As frasagens que a TEC-139 sondou, mais as variantes acentuadas.

    Nenhuma delas e fala real observada -- ver a docstring do modulo. Elas
    fixam a faixa, nao a validam.
    """
    assert perguntou_se_e_robo(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "quero um apartamento automatico de 2 quartos",
        "o portao e automatico?",
        "tem maquina de lavar no apartamento?",
        "o predio tem elevador automatico?",
        "somos em cinco pessoas",
        "preciso falar com uma pessoa sobre o contrato",
    ],
)
def test_fala_vizinha_nao_dispara(texto: str) -> None:
    """O objeto sozinho nunca basta.

    "automatico" qualificando portao ou elevador, "maquina" de lavar e
    "pessoa" como sujeito sao fala corrente de quem procura imovel. Um
    detector que casasse o substantivo solto grudaria oferta de corretor em
    cada um deles.
    """
    assert perguntou_se_e_robo(texto) is False


def test_texto_vazio_nao_levanta() -> None:
    """Mesma garantia de `gatilhos_de`: texto sem letra nenhuma devolve False."""
    assert perguntou_se_e_robo("") is False
    assert perguntou_se_e_robo("!!! 123 ???") is False


def test_nao_dispara_em_nenhum_turno_do_corpus() -> None:
    """A unica afirmacao forte disponivel sobre a faixa (D3 do desenho).

    Mil e tantos turnos de fala de lead, e nenhum deles e esta pergunta --
    conferido por grep antes de escrever o detector. Se um deles passar a
    disparar, ou o corpus ganhou um caso deste eixo (e ai o teste conta uma
    novidade boa) ou a faixa ficou larga demais (e ai ele pegou o defeito que
    o corpus inventado nunca pegaria).

    Sem chamada paga: `carregar` so le YAML.
    """
    disparam = [
        turno.lead
        for conversa in carregar(CORPUS)
        for turno in conversa.turnos
        if perguntou_se_e_robo(turno.lead)
    ]

    assert disparam == []
```

- [ ] **Step 2: Rodar e verificar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_pergunta_se_e_robo.py -v
```

Esperado: `ImportError: cannot import name 'perguntou_se_e_robo'`.

- [ ] **Step 3: Implementar o detector**

Acrescente ao fim de `src/mobia/domain/agente/identificacao.py`:

```python
# O lead perguntando se fala com uma maquina (TEC-272), para anexar a oferta
# de corretor que o CA-04.1 pede junto da confirmacao.
#
# **Faixa estrita, pelo argumento de `context/gatilhos.py` e nao pelo do
# opt-out.** La deixar de detectar e violacao de LGPD e a faixa inequivoca e
# generosa. Aqui e o inverso: falso negativo devolve o comportamento de hoje
# (o lead nao recebe a oferta, e a identificacao proativa ja cobriu quem
# perguntou cedo), e falso positivo gruda uma oferta de corretor numa fala que
# nao perguntou nada -- que e o segundo criterio de aceite desta card, e e
# visivel ao lead.
#
# **O criterio e o SUJEITO junto do predicado, nunca o substantivo sozinho.**
# "automatico" qualificando portao ou elevador, "maquina" de lavar e "pessoa"
# como sujeito sao fala corrente de quem procura imovel. Mesma licao que
# `optout/deteccao.py` registra sobre "nada" e que `gatilhos.py` registra
# sobre o verbo de acao.
#
# **A recall e inverificavel, e isso esta declarado no desenho (D3).** Nao ha
# fala real deste eixo em `evals/corpus/` -- zero ocorrencias nos cinco
# arquivos --, entao estes termos sao invencao. O que o teste prova e o lado
# negativo: que nenhum dos turnos reais do corpus dispara.
_TERMOS_DA_PERGUNTA: tuple[str, ...] = (
    "e um robo",
    "e um bot",
    "eh um robo",
    "e robo",
    "um robo ou",
    "e humano ou",
    "e uma maquina",
    "e maquina ou",
    "humano ou maquina",
    "maquina ou humano",
    "falando com uma pessoa",
    "falando com um humano",
    "falando com uma maquina",
    "falando com um robo",
    "falando com gente",
    "tudo automatico",
    "e automatico ou",
    "automatico ou tem",
    "tem alguem ai",
    "tem alguem ai ou",
    "tem gente ai",
    "e gente ou",
)

# Um padrao so, com `\b` no inicio de cada alternativa, pelo mesmo motivo de
# `_PADRAO_POR_MOTIVO` em `context/gatilhos.py`: sem o limite, um termo casaria
# escondido dentro de uma palavra maior. `re.escape` porque os termos sao
# literais, nunca regex.
_PADRAO_DA_PERGUNTA = re.compile(
    r"\b(?:" + "|".join(re.escape(termo) for termo in _TERMOS_DA_PERGUNTA) + r")"
)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    **E o mesmo transform de `optout/deteccao.py` e de `context/gatilhos.py`, e
    a terceira copia e deliberada pela mesma razao que a segunda.** Aquele
    modulo registra que compartilhar acoplaria um detector comercial a um
    detector de decisao de LGPD. Aqui a copia e ainda mais barata de justificar:
    este detector so decide se uma frase e anexada a uma resposta, e nao tem
    negocio nenhum puxando mudanca no caminho regulado.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def perguntou_se_e_robo(texto: str) -> bool:
    """O lead perguntou se esta falando com uma maquina.

    Nunca levanta: texto sem letra nenhuma normaliza para vazio e devolve
    False, mesma garantia de `gatilhos_de`.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    return _PADRAO_DA_PERGUNTA.search(normalizado) is not None
```

E acrescente os imports no topo do arquivo, junto dos que já existem:

```python
import re
import unicodedata
```

- [ ] **Step 4: Rodar e verificar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_pergunta_se_e_robo.py -v
```

Esperado: todos passam.

**Se `test_nao_dispara_em_nenhum_turno_do_corpus` falhar, o teste está certo e a faixa é que ficou larga.** A mensagem imprime a fala do corpus que disparou. Aperte o termo responsável — não relaxe o teste, não exclua o turno. Diga no relatório qual termo foi apertado e por causa de qual fala.

- [ ] **Step 5: Os três gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/identificacao.py tests/unit/test_pergunta_se_e_robo.py
git commit -F - <<'EOF'
feat(TEC-272): o repo passa a detectar a pergunta sobre ser robo, sem tocar no prompt

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: `ja_oferece_corretor`, o detector de saída

**Files:**
- Modify: `src/mobia/domain/agente/identificacao.py` (acrescenta ao fim)
- Test: `tests/unit/test_ja_oferece_corretor.py` (criar)

**Interfaces:**
- Consumes: `_normalizar` da Task 1, no mesmo módulo.
- Produces: `ja_oferece_corretor(texto: str) -> bool`, `TEXTO_DA_OFERTA_DE_CORRETOR: str`, `SEPARADOR_DA_OFERTA: str`. A Task 3 monta `texto_com_oferta` sobre estes tres.

Sem chamada paga.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_ja_oferece_corretor.py`:

```python
"""O detector que impede a oferta de corretor de aparecer duas vezes (TEC-272).

O teste que carrega esta card e
`test_todo_texto_deterministico_com_corretor_e_reconhecido`: ele **deriva** a
lista dos textos por importacao dos modulos, em vez de transcreve-la. Uma
constante nova que ofereca corretor entra na verificacao sozinha, e se o
detector nao a reconhecer o lead passa a receber a oferta duas vezes -- que e
exatamente o defeito que esta card existe para nao criar.
"""

import mobia.domain.agente.identificacao as ident
import mobia.domain.agente.turno as turno
from mobia.domain.agente.identificacao import (
    TEXTO_DA_OFERTA_DE_CORRETOR,
    ja_oferece_corretor,
)


def _textos_deterministicos_com_corretor() -> dict[str, str]:
    """Toda constante de texto dos dois modulos que menciona corretor.

    Derivada, e nao transcrita: uma lista escrita a mao envelheceria na
    primeira card que acrescentasse trilha, e o envelhecimento seria
    silencioso -- o teste continuaria verde enquanto o lead recebia a oferta
    duplicada.
    """
    achados: dict[str, str] = {}
    for modulo in (ident, turno):
        for nome in dir(modulo):
            if nome.startswith("_"):
                continue
            valor = getattr(modulo, nome)
            if isinstance(valor, str) and "corretor" in valor.lower():
                achados[f"{modulo.__name__}.{nome}"] = valor
    return achados


def test_todo_texto_deterministico_com_corretor_e_reconhecido() -> None:
    """Se um destes nao for reconhecido, aquela trilha passa a duplicar."""
    textos = _textos_deterministicos_com_corretor()

    assert textos, "nenhum texto com corretor encontrado: o derivador quebrou"
    nao_reconhecidos = [nome for nome, valor in textos.items() if not ja_oferece_corretor(valor)]
    assert nao_reconhecidos == []


def test_a_propria_oferta_e_reconhecida() -> None:
    """Sem isto, dois turnos seguidos empilhariam duas ofertas."""
    assert ja_oferece_corretor(TEXTO_DA_OFERTA_DE_CORRETOR) is True


def test_resposta_sem_oferta_nao_e_reconhecida() -> None:
    """O caso que faz o append disparar -- e que a TEC-139 mediu como 1 e 2."""
    assert ja_oferece_corretor("Sim, sou um assistente virtual da imobiliária.") is False
    assert ja_oferece_corretor("Temos três apartamentos de 2 quartos na zona sul.") is False


def test_reconhece_com_e_sem_acento_e_no_plural() -> None:
    """O modelo escreve acentuado e o repo tem literais sem acento.

    Um detector que so casasse uma das formas se calaria na metade dos casos,
    e a metade em que ele se cala e a que duplica.
    """
    assert ja_oferece_corretor("posso te passar para um corretor") is True
    assert ja_oferece_corretor("falo com os corretores da equipe") is True
    assert ja_oferece_corretor("Corretor") is True


def test_texto_vazio_nao_levanta() -> None:
    assert ja_oferece_corretor("") is False
```

- [ ] **Step 2: Rodar e verificar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_ja_oferece_corretor.py -v
```

Esperado: `ImportError: cannot import name 'ja_oferece_corretor'`.

- [ ] **Step 3: Implementar**

Acrescente ao fim de `src/mobia/domain/agente/identificacao.py`:

```python
# A oferta que o CA-04.1 pede junto da confirmacao. Texto que o lead recebe,
# entao COM acento (TEC-267) -- ao contrario dos prompts de sistema deste
# repo, que sao instrucao para o modelo e continuam sem.
TEXTO_DA_OFERTA_DE_CORRETOR = "Se preferir falar com um corretor, é só me dizer."

# Linha em branco e nao espaco, pelo mesmo argumento de
# `SEPARADOR_DA_IDENTIFICACAO` logo acima: as duas frases tem autores
# diferentes -- uma e resposta ao lead, a outra e constante do repositorio -- e
# coladas parecem uma frase so mal pontuada.
SEPARADOR_DA_OFERTA = "\n\n"


def ja_oferece_corretor(texto: str) -> bool:
    """O texto que o lead vai receber ja oferece um corretor?

    **A palavra basta, e e isso que torna este detector barato.** "Corretor"
    nao aparece na fala do agente por acaso: nas sete trilhas deterministicas
    que a mencionam -- a identificacao, a busca inconclusiva, o sem-resultado
    pos-ampliacao, o encaminhamento de venda, as duas variantes do pedido de
    humano e o teto de perguntas -- ela aparece sempre oferecendo um. O
    unitario deste modulo deriva essa lista por importacao e confere uma a uma.

    **A assimetria esta na direcao certa.** Falso positivo (achar oferta onde
    nao ha) nao anexa nada e devolve o comportamento de hoje; falso negativo
    duplica a oferta na mesma mensagem. Errar para o lado de nao anexar e o
    lado barato.

    **Roda sobre o texto FINAL, nao sobre a resposta crua do modelo** -- e essa
    escolha, feita em `turno.py`, e o que faz uma regra so cobrir as tres
    duplicacoes possiveis: o modelo ter oferecido sozinho, a identificacao ter
    oferecido no prefixo, e o turno ter caido numa trilha deterministica que
    ja oferece.
    """
    return "corretor" in _normalizar(texto)
```

- [ ] **Step 4: Rodar e verificar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_ja_oferece_corretor.py -v
```

Esperado: todos passam. Se `test_todo_texto_deterministico_com_corretor_e_reconhecido` falhar, imprima os nomes não reconhecidos e reporte — pode ser um texto que menciona corretor sem oferecer, que é a lacuna que o desenho declara.

- [ ] **Step 5: Os três gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/identificacao.py tests/unit/test_ja_oferece_corretor.py
git commit -F - <<'EOF'
feat(TEC-272): uma regra so cobre as tres duplicacoes possiveis da oferta

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `texto_com_oferta`, e a linha no turno

**Files:**
- Modify: `src/mobia/domain/agente/identificacao.py` (acrescenta ao fim)
- Modify: `src/mobia/domain/agente/turno.py` (imports, e uma linha depois do `if identificar:` da 2551)
- Test: `tests/unit/test_oferta_de_corretor.py` (criar)

**Interfaces:**
- Consumes: `perguntou_se_e_robo` (Task 1); `ja_oferece_corretor`, `TEXTO_DA_OFERTA_DE_CORRETOR`, `SEPARADOR_DA_OFERTA` (Task 2).
- Produces: `texto_com_oferta(corpo_do_lead: str | None, texto: str) -> str`.

**A decisão vira função, e não três linhas dentro de `executar_turno`.** O motivo é testabilidade: `executar_turno` tem 1877 linhas e precisa de banco, fila e provedor, então uma condição escrita ali só se testa replicando-a no teste — e um teste que replica a regra segue verde depois de a produção mudar. Com a função, o unitário exercita o código real e o `turno.py` ganha **uma** linha.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_oferta_de_corretor.py`:

```python
"""A regra que decide se a oferta de corretor e anexada (TEC-272).

Exercita `texto_com_oferta`, que e a funcao que o `turno.py` chama -- e nao
uma copia da condicao. A diferenca importa: um teste que replicasse a regra
seguiria verde depois de a producao mudar.
"""

import pytest

from mobia.domain.agente.identificacao import (
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_OFERTA_DE_CORRETOR,
    texto_com_oferta,
)


def test_pergunta_neutra_recebe_a_oferta() -> None:
    """O primeiro criterio de aceite da card."""
    resposta = "Sim, sou um assistente virtual da imobiliária."

    final = texto_com_oferta("vc e um robo?", resposta)

    assert final == f"{resposta}\n\n{TEXTO_DA_OFERTA_DE_CORRETOR}"


def test_quem_nao_perguntou_nada_nao_recebe_oferta() -> None:
    """O segundo criterio de aceite: a oferta nao vira assinatura de rodape."""
    resposta = "Temos três apartamentos de 2 quartos na zona sul."

    assert texto_com_oferta("quero um apto de 2 quartos", resposta) == resposta


def test_nao_duplica_quando_o_modelo_ja_ofereceu() -> None:
    """Os casos 3 e 4 da sondagem da TEC-139, em que o modelo oferece sozinho."""
    resposta = (
        "Sou um assistente virtual. Se preferir falar direto com um corretor, "
        "é só me dizer que eu já providencio esse contato."
    )

    assert texto_com_oferta("isso e automatico ou tem alguem ai?", resposta) == resposta


def test_nao_duplica_quando_a_conversa_e_nova() -> None:
    """A identificacao proativa ja ofereceu no prefixo, e o append se cala.

    E a razao de a guarda olhar o texto FINAL e nao a resposta crua do modelo:
    sem isso, este caso precisaria de regra propria.
    """
    resposta = "Sim, sou um assistente virtual."
    com_identificacao = f"{TEXTO_DA_IDENTIFICACAO}\n\n{resposta}"

    assert texto_com_oferta("vc e um robo?", com_identificacao) == com_identificacao


def test_corpo_ausente_nao_levanta() -> None:
    """`corpo` e `str | None` em `executar_turno`, como `pediu_optout` ja trata la."""
    assert texto_com_oferta(None, "qualquer resposta") == "qualquer resposta"
    assert texto_com_oferta("", "qualquer resposta") == "qualquer resposta"


@pytest.mark.parametrize(
    "texto_deterministico",
    [
        "Deixa eu confirmar algumas coisas com um corretor para não te passar informação errada.",
        "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui.",
    ],
)
def test_nao_duplica_nas_trilhas_deterministicas(texto_deterministico: str) -> None:
    """Quando o turno respondeu por uma trilha que ja oferece, o append se cala.

    Os textos aqui sao parafrase das trilhas reais de proposito: quem guarda as
    constantes de verdade e
    `test_todo_texto_deterministico_com_corretor_e_reconhecido`, que as deriva
    por importacao. Transcreve-las aqui criaria uma segunda copia para
    envelhecer.
    """
    assert texto_com_oferta("vc e um robo?", texto_deterministico) == texto_deterministico
```

- [ ] **Step 2: Rodar e verificar que falha**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_oferta_de_corretor.py -v
```

Esperado: `ImportError: cannot import name 'texto_com_oferta'`.

- [ ] **Step 3: Implementar a função**

Acrescente ao fim de `src/mobia/domain/agente/identificacao.py`:

```python
def texto_com_oferta(corpo_do_lead: str | None, texto: str) -> str:
    """A oferta do CA-04.1, anexada so quando falta.

    O CA-04.1 pede duas coisas ao confirmar ser assistente virtual: confirmar
    E oferecer corretor. A TEC-139 mediu e so a primeira acontecia de forma
    confiavel -- o modelo confirmava em todos os casos sondados e oferecia em
    parte deles, e os que nao ofereciam eram as perguntas neutras.

    **A guarda olha o `texto` ja montado, e nao a resposta crua do modelo.** E
    o que faz uma regra so cobrir as tres duplicacoes possiveis: o modelo ter
    oferecido sozinho, a identificacao ter oferecido no prefixo, e o turno ter
    caido numa das seis trilhas deterministicas de `turno.py` que ja falam em
    corretor. Nenhuma precisa de caso proprio -- a pergunta nao e QUEM
    ofereceu, e se a mensagem oferece.

    `corpo_do_lead` e opcional porque em `executar_turno` ele e `str | None`,
    do mesmo jeito que `pediu_optout` e `gatilhos_de` ja tratam la.
    """
    if not corpo_do_lead or not perguntou_se_e_robo(corpo_do_lead):
        return texto
    if ja_oferece_corretor(texto):
        return texto
    return f"{texto}{SEPARADOR_DA_OFERTA}{TEXTO_DA_OFERTA_DE_CORRETOR}"
```

- [ ] **Step 4: Rodar e verificar que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_oferta_de_corretor.py -v
```

Esperado: todos passam.

- [ ] **Step 5: Ligar no `turno.py`**

No bloco de import de `identificacao` (por volta da linha 21), acrescente `texto_com_oferta` aos nomes que já estão lá — **leia o import real antes de editar**, não substitua o bloco inteiro.

Logo **depois** do `if identificar:` da linha 2551, acrescente:

```python
    # CA-04.1: ao confirmar ser assistente virtual, oferecer corretor. A guarda
    # inteira vive em `identificacao.texto_com_oferta` -- inclusive a razao de
    # ela olhar o texto ja montado e nao a resposta crua do modelo.
    #
    # Aqui, e nao depois de `quebrar_em_mensagens`: aquele corte aplica os 600
    # caracteres da RN-04.2, e anexar depois dele estouraria o teto em silencio.
    texto = texto_com_oferta(corpo, texto)
```

- [ ] **Step 6: Rodar os unitários vizinhos**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_oferta_de_corretor.py \
  tests/unit/test_pergunta_se_e_robo.py tests/unit/test_ja_oferece_corretor.py \
  tests/unit/test_identificacao_texto.py tests/unit/test_deteccao_de_humano.py -v
```

Esperado: todos passam. O `test_deteccao_de_humano.py` entra na lista porque a quarta frasagem da card cai na trilha dele — se algo ali quebrar, as duas detecções colidiram.

- [ ] **Step 7: Os três gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 8: Commit**

Assunto: `fix(TEC-272): confirmar ser assistente virtual passa a vir com a oferta de corretor`, terminando com a linha de co-autoria das Global Constraints.

```bash
git add src/mobia/domain/agente/identificacao.py src/mobia/domain/agente/turno.py tests/unit/test_oferta_de_corretor.py
```

---

### Task 4: A sonda, e o relatório

**Files:**
- Create: `evals/sonda_oferta_de_corretor.py`
- Create: `evals/relatorios/2026-09-18-tec-272-oferta-de-corretor-<hash>.md`

**60 chamadas pagas.** Modelo `claude-sonnet-5` (`modelo_agente`), ~US$ 0,50 pelo custo por chamada que o relatório da TEC-139 registra (`USD 0,008228`).

**Interfaces:**
- Consumes: `ja_oferece_corretor` (Task 2); `ClassificadorAnthropic`, `SISTEMA_DO_AGENTE`, `contexto_do_historico`, `pediu_humano`.
- Produces: uma tabela markdown por frasagem, para o relatório.

- [ ] **Step 1: Escrever a sonda**

Em `evals/sonda_oferta_de_corretor.py`:

```python
"""Sonda: com que taxa o modelo ja oferece corretor sozinho? (TEC-272)

Diagnostico, nao gate. Nenhum numero daqui vira piso ou metrica, e nenhum
prova o conserto -- o conserto e deterministico e quem o prova sao os
unitarios de `texto_com_oferta`. O que estas chamadas compram e uma coisa so:
saber se o append que a card acrescenta dispara quase sempre ou quase nunca.

**Replica o metodo da sondagem da TEC-139**, que esta descrito em
`evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`: chama
`classificar` direto com `SISTEMA_DO_AGENTE`, cada texto sendo o unico turno
da sua propria conversa, sem estado acumulado. Nao passa por `executar_turno`,
entao nao passa por `pediu_humano` nem pelo append desta card -- mede o modelo
cru, que e o que a pergunta pede.

**Tres frasagens, e nao as quatro da card.** A quarta ("voce e humano ou
maquina? nao quero falar com robo") ja dispara `pediu_humano` desde a TEC-143,
mergeada quatro dias DEPOIS da sondagem da TEC-139 -- ela toma a trilha
deterministica daquela card e recebe `TEXTO_DO_PEDIDO_DE_HUMANO`, que ja
oferece corretor. Medi-la seria gastar 20 chamadas para descobrir que uma
trilha deterministica e deterministica. `_conferir_a_fronteira` abaixo assere
essa relacao antes da primeira chamada paga.

**Sem prefixo `test_` de proposito** -- assim `pytest evals` nunca a coleta e
nunca gasta chamada sozinha. Importar tambem nao gasta: a primeira chamada sai
dentro de `main()`.

**A saida vai para arquivo UTF-8, nunca para o console.** A sondagem da
TEC-139 perdeu uma chamada paga para um `UnicodeEncodeError` num emoji da
resposta, no console `cp1252` do Windows, antes de o texto ser gravado em
qualquer lugar. Esta escreve o relatorio bruto em disco primeiro.

Rode de proposito:

    ./.venv/Scripts/python.exe evals/sonda_oferta_de_corretor.py
"""

import asyncio
import sys
from pathlib import Path

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.agente.identificacao import ja_oferece_corretor
from mobia.domain.humano.deteccao import pediu_humano
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico

REPETICOES = 20

DESTINO = Path(__file__).resolve().parent / "relatorios" / "_sonda-tec-272-bruto.md"

# As tres frasagens da sondagem da TEC-139 que ainda chegam ao texto livre do
# modelo. A ordem e a da tabela daquele relatorio, para a comparacao ficar
# linha a linha.
FRASAGENS: tuple[str, ...] = (
    "vc e um robo?",
    "to falando com uma pessoa?",
    "isso e automatico ou tem alguem ai?",
)

# A quarta frasagem, que saiu da amostra. Fica nomeada aqui, e nao so no
# comentario, porque `_conferir_a_fronteira` a usa para asserir a razao da
# exclusao -- uma constante que o codigo le vale mais que uma frase que so uma
# pessoa le.
FRASAGEM_JA_DETERMINISTICA = "voce e humano ou maquina? nao quero falar com robo"


def _conferir_a_fronteira() -> None:
    """A razao de a quarta frasagem ter saido, asserida antes de gastar dinheiro.

    Se a TEC-143 mudar a faixa de `pediu_humano`, esta sonda para em vez de
    medir a amostra errada -- e quem rodar descobre pela excecao, e nao lendo o
    relatorio meses depois e estranhando o denominador.
    """
    if not pediu_humano(FRASAGEM_JA_DETERMINISTICA):
        raise RuntimeError(
            "a quarta frasagem deixou de disparar `pediu_humano`: ela voltou a "
            "chegar ao texto livre do modelo e precisa voltar para a amostra"
        )
    ainda_livres = [texto for texto in FRASAGENS if pediu_humano(texto)]
    if ainda_livres:
        raise RuntimeError(
            f"frasagens que passaram a ser deterministicas e precisam sair da "
            f"amostra: {ainda_livres}"
        )


async def _medir(frasagem: str) -> tuple[int, int, str]:
    """`REPETICOES` chamadas sob a mesma frasagem.

    Devolve (ofereceu, indisponiveis, primeira resposta literal). A primeira
    resposta vai para o relatorio como amostra -- a sondagem da TEC-139
    preservou as quatro dela, e ler o texto e o que permite discordar da
    contagem.

    O criterio de "ofereceu" e `ja_oferece_corretor`, o MESMO detector que roda
    em producao, e nao um criterio paralelo escrito aqui. Dois criterios
    divergiriam na primeira card que mexesse num deles, e a divergencia seria
    silenciosa.
    """
    classificador = ClassificadorAnthropic()
    ofereceu = 0
    indisponiveis = 0
    primeira = ""
    for _ in range(REPETICOES):
        contexto = contexto_do_historico([(MessageRole.LEAD, frasagem)], sistema=SISTEMA_DO_AGENTE)
        try:
            resposta = await classificador.classificar(contexto)
        except Exception as exc:
            # Fora do denominador, como o gate de moderacao faz: uma chamada que
            # nao respondeu nao diz nada sobre o criterio do modelo. Sem
            # interpolar a excecao inteira -- ela pode ecoar o corpo enviado.
            indisponiveis += 1
            print(f"  indisponivel: {type(exc).__name__}", file=sys.stderr)
            continue
        if not primeira:
            primeira = resposta.resposta
        if ja_oferece_corretor(resposta.resposta):
            ofereceu += 1
    return ofereceu, indisponiveis, primeira


async def main() -> None:
    _conferir_a_fronteira()

    linhas = [
        "# Sonda: o modelo ja oferece corretor sozinho? (TEC-272)",
        "",
        f"- repeticoes por frasagem: {REPETICOES}",
        f"- chamadas: {len(FRASAGENS) * REPETICOES}",
        f"- modelo: `{get_settings().modelo_agente}`",
        "- metodo: `classificar` direto com `SISTEMA_DO_AGENTE`, um turno por conversa",
        f"- fora da amostra: `{FRASAGEM_JA_DETERMINISTICA}` (ja dispara `pediu_humano`)",
        "",
        "| frasagem | ofereceu | indisponiveis |",
        "| --- | --- | --- |",
    ]
    amostras: list[str] = []
    for frasagem in FRASAGENS:
        print(f"medindo: {frasagem}", file=sys.stderr)
        ofereceu, indisponiveis, primeira = await _medir(frasagem)
        medidos = REPETICOES - indisponiveis
        pct = f"{ofereceu * 100 / medidos:.0f}%" if medidos else "sem medida"
        linhas.append(f"| `{frasagem}` | {ofereceu}/{medidos} ({pct}) | {indisponiveis} |")
        amostras.append(f"### `{frasagem}`\n\n> {primeira}\n")

    linhas.extend(["", "## Primeira resposta de cada frasagem", ""])
    linhas.extend(amostras)

    DESTINO.write_text("\n".join(linhas), encoding="utf-8")
    print(f"escrito em {DESTINO}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Conferir a sonda sem gastar chamada**

```bash
./.venv/Scripts/python.exe -c "import evals.sonda_oferta_de_corretor as s; s._conferir_a_fronteira(); print('fronteira ok')"
```

Esperado: `fronteira ok`, e nenhuma chamada paga. Se levantar `RuntimeError`, a relação entre `pediu_humano` e as frasagens mudou — **pare e reporte**, não ajuste a amostra por conta própria: o desenho argumenta a partir dessa relação.

- [ ] **Step 3: Rodar a sonda**

```bash
./.venv/Scripts/python.exe evals/sonda_oferta_de_corretor.py
```

60 chamadas, alguns minutos. O progresso sai em `stderr`; o relatório bruto vai para `evals/relatorios/_sonda-tec-272-bruto.md`.

Confira a coluna `indisponiveis` antes de interpretar: acima de 2 em qualquer linha, o denominador esvaziou e a taxa não significa — refaça aquela frasagem e registre que foi refeita.

- [ ] **Step 4: Escrever o relatório**

Renomeie/reescreva o bruto como `evals/relatorios/2026-09-18-tec-272-oferta-de-corretor-<hash>.md`, onde `<hash>` é o `git rev-parse --short HEAD` da árvore medida. Prosa **com acento**, no formato de `2026-09-11-tec-139-identificacao-036d973.md`. Apague o `_sonda-tec-272-bruto.md` depois — ele é intermediário, não artefato.

Precisa conter, além das tabelas:

- **Que não é corpus.** Três frasagens inventadas, não fala real — e que não existe fala real deste eixo no repo (D3 do desenho).
- **A leitura que decide se a card valeu a pena.** Taxa alta significa que o append quase nunca dispara e a card é quase um no-op; taxa baixa significa que ele é quem segura o CA-04.1. Diga qual dos dois o número mostrou, sem enfeitar.
- **Que a quarta frasagem saiu da amostra**, com a verificação por execução: ela dispara `pediu_humano` desde a TEC-143 (15/09), quatro dias depois da sondagem da TEC-139 (11/09). E que isso torna o `2/4` da card um número de um mundo anterior — o denominador de hoje é 3.
- **As lacunas do desenho**, repetidas: a recall do detector é inverificável, e a sonda mede o vocabulário do próprio teste.

- [ ] **Step 5: Os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add evals/sonda_oferta_de_corretor.py evals/relatorios/
```

Assunto do commit: `docs(TEC-272): a sonda de 60 chamadas mede quanto o modelo ja oferece sozinho`, terminando com a linha de co-autoria das Global Constraints.

---

### Task 5: Fechamento — comentários, suíte, PR, card

- [ ] **Step 1: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Duas marcas importam:

- **`VIZINHO` em `turno.py`** — a Task 3 editou dentro de `executar_turno`, e o `CLAUDE.md` registra que **75,9% do ruído da listagem vem dessa função**. A saída vem com teto de cinco por bloco; se o resumo disser que omitiu muitos, rode `--tudo` e releia os que cercam o bloco `if identificar:`. O comentário longo sobre as sete trilhas, logo acima dele, é o que mais importa: ele enumera as trilhas cobertas pelo ponto de concatenação, e a Task 3 acrescentou uma decisão logo abaixo dele.
- **`PROSA`/`FALSO`** — o desenho e o plano citam `turno.py` pela linha (2551 e 2791). A Task 3 muda o tamanho do arquivo e **desloca a 2791**. Confira e corrija as citações nos dois documentos.

  **Este Step não foi executado, e a revisão final pegou** (M1): a 2791 já era 2819 e ninguém conferiu. Corrigido para 2574 e 2870 — e a correção deslocou os dois de novo, então a re-review pegou os números errados pela **terceira** vez na mesma branch.

  **Conserto definitivo, e é a lição do Step e não o Step cumprido:** os números saíram dos dois documentos. Passam a citar `if identificar:` e `quebrar_em_mensagens`, que um `grep` acha em qualquer versão de `turno.py` e que sobrevivem a qualquer edição. Um plano futuro que precise deste Step não precisa dele — precisa não escrever o número.

- [ ] **Step 2: A suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com muitos `ERROR` de setup, **não repita o mesmo comando** — é o Postgres sob o paralelismo desta máquina. Rode por blocos:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
./.venv/Scripts/python.exe -m pytest tests/features --tb=short
```

Se `alembic upgrade head` falhar com `ConnectionResetError [WinError 64]`, é a rajada documentada: retente até passar antes de diagnosticar qualquer coisa. E `test_sweep_stalled.py`, `test_dedup_por_message_id.py`, `test_montagem.py` e `test_optout_repositorio.py` flakeiam sob carga — rode o arquivo isolado antes de culpar a mudança.

- [ ] **Step 3: Os três gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 4: Push e PR**

```bash
git push -u origin feat/tec-272-oferta-de-corretor-ao-confirmar
gh pr create --base main \
  --title "fix(TEC-272): a confirmacao de assistente virtual passa a oferecer corretor" \
  --body-file "$SCRATCH/tec-272-pr.md"
```

Termina com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 5: Comentar na card e mover para "Em análise"**

O comentário registra o que some se ficar só no PR:

- **A medição da card está velha, e o número mudou.** A quarta frasagem já é determinística desde a TEC-143 (15/09), quatro dias depois da sondagem (11/09). O denominador é 3, não 4, e o de hoje é `1/3`, não `2/4`.
- **A hipótese da card perdeu o seu melhor caso.** Ela dizia que o modelo oferece quando o lead expressa reserva, citando "nao quero falar com robo" — e é exatamente esse que saiu da amostra.
- **A recall do detector é inverificável**, e é decisão de produto, não de código: não existe fala real deste eixo no repo, os termos são invenção, e o que os testes provam é o lado negativo.
- **O que a sonda mediu**, e se ela mostrou a card como quase-no-op ou como o que segura o CA-04.1.
- **Nenhuma emenda ao SRS** — o CA-04.1 já exigia as duas metades.

Transição: `Em análise` (id `31`), não `Feito`.

- [ ] **Step 6: Depois do merge, a limpeza local**

```bash
git merge-base --is-ancestor <hash> origin/main && echo mergeado
git checkout main && git pull && git branch -d feat/tec-272-oferta-de-corretor-ao-confirmar
```
