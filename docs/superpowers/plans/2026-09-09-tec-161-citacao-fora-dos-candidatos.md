# TEC-161 — Bloquear citação fora dos candidatos: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nenhuma cifra e nenhum código de imóvel chegam ao lead sem corresponder ao que o banco devolveu naquele turno, e o bloqueio acontece antes de qualquer reserva em `outbound_dispatches`.

**Architecture:** Um módulo puro novo (`domain/agente/citacao.py`) recebe a prosa do modelo, os candidatos do turno e a faixa declarada pelo lead, e devolve as divergências. `executar_turno` chama esse módulo depois da moderação de saída e, havendo divergência, descarta a prosa — **não regenera**. A gramática monetária é a que já existe em `domain/agente/dinheiro.py`, estendida com um varredor de parágrafo.

**Tech Stack:** Python 3.13, dataclasses `frozen=True/slots=True`, `re`, `structlog`, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-09-tec-161-citacao-fora-dos-candidatos-design.md` — o plano argumenta a partir dele; leia os dois.

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates estáticos, nesta ordem, com este escopo exato**, antes de qualquer commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é um gate separado do linter. Passar num não diz nada sobre o outro. Se o `--check` reprovar, rode `./.venv/Scripts/python.exe -m ruff format src tests alembic evals` e commite o resultado — **o código deste plano foi escrito à mão e não passou pelo formatador**, então espere que ele reescreva quebras de linha.
- **Mensagem de commit:** `tipo(TEC-161): o que passou a ser verdade`, em português sem acento no assunto.
- **Basename de arquivo de teste é único no repo inteiro.** `tests/unit/test_citacao.py` e `tests/integration/test_citacao_no_turno.py` não colidem com nada hoje — confira antes de criar. Basename repetido entre `unit/` e `integration/` **aborta a coleta da suíte inteira** e não aparece quando se roda o arquivo isolado; já custou duas cards.
- **Orçamento do prompt: esta card gasta zero.** Nenhum campo novo no schema, nenhuma frase nova em `SISTEMA_DO_AGENTE`, nada novo em `FERRAMENTA_DE_BUSCA`. A margem medida em 09/09/2026 é de 6,0 tokens (líquido 780,0 contra teto fixo de 786). Se algum passo aqui mexer nisso, você saiu do plano.
- **Nenhum teste desta card gasta crédito da Anthropic.** Todo cliente de modelo é dublê.
- **A suíte é lenta** (~22 min, 1376 testes coletados em 09/09/2026) e lentidão parece travamento. Rode arquivo isolado durante o trabalho; a suíte inteira só na Task 5.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/mobia/domain/agente/dinheiro.py` | **Modificar.** Ganha `valores_em`, o varredor de parágrafo. A gramática continua sendo uma só. | 1 |
| `src/mobia/domain/agente/citacao.py` | **Criar.** Puro. Recebe prosa + candidatos + faixa, devolve divergências. Sem I/O. | 2 |
| `src/mobia/domain/agente/turno.py` | **Modificar.** O enxerto: uma chamada, um `if`, um log, e o helper da faixa. | 3 |
| `tests/unit/test_dinheiro.py` | **Modificar.** Tabela de `valores_em`. | 1 |
| `tests/unit/test_citacao.py` | **Criar.** As tabelas da D2/D4/D5/D6/D7 e os cenários da card. | 2 |
| `tests/integration/test_citacao_no_turno.py` | **Criar.** Os dois caminhos de bloqueio dentro do turno, e a ordem contra a reserva. | 3 |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | **Modificar.** Duas emendas aninhadas. | 4 |

---

### Task 1: O varredor monetário, dentro da gramática que já existe

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py`
- Test: `tests/unit/test_dinheiro.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `valores_em(texto: str) -> tuple[int, ...]` — todos os valores monetários do texto, em centavos, na ordem em que aparecem. **Só conta como valor o número que tem marcador** (`R$` antes, `reais` depois, ou sufixo de grandeza). Não levanta nunca.

**Por que aqui e não num módulo novo:** `dinheiro.py` já resolve "quinhentos mil", "1,2 milhão" e "R$ 516.464,30". Um segundo parser de expressão monetária em português seriam duas gramáticas divergindo em silêncio. Ver D3 do desenho.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/unit/test_dinheiro.py`:

```python
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # Com marcador: contam.
        ("custa R$ 500 mil", (50_000_000,)),
        ("sai por 500 mil", (50_000_000,)),
        ("R$ 516.464,30 fechado", (51_646_430,)),
        ("500 reais de condominio", (50_000,)),
        ("de 400 mil a 600 mil", (40_000_000, 60_000_000)),
        ("meio milhao nao entra, mas 1,2 milhao sim", (120_000_000,)),
        # Sem marcador: nao contam. Esta metade e a que impede a guarda de
        # bloquear turno correto -- ver D2 do desenho.
        ("2 quartos e 1 vaga", ()),
        ("80 m2 no andar 12", ()),
        ("achei 3 opcoes", ()),
        ("esse ai sai por 750", ()),
        # Malformado: erra por falta, nao inventa valor.
        ("1.5 milhao", ()),
        ("", ()),
    ],
)
def test_valores_em_exige_marcador(texto: str, esperado: tuple[int, ...]) -> None:
    """D2: numero nu nao e dinheiro.

    Sem esta regra, "2 quartos" vira R$ 2,00 e a guarda da TEC-161 bloqueia
    turno correto -- que e o unico jeito de uma guarda anti-alucinacao perder
    a confianca de quem opera.
    """
    assert valores_em(texto) == esperado


def test_valores_em_nunca_levanta() -> None:
    """Mesmo contrato do resto do modulo: a entrada vem do modelo repetindo a
    fala do lead, entao qualquer sequencia de caracteres e valida."""
    for texto in ("34191790010104351004791020150008291070026000", "R$", "-500 mil", "mil"):
        assert isinstance(valores_em(texto), tuple)
```

Acrescente `valores_em` ao import de `mobia.domain.agente.dinheiro` no topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -k valores_em -v`
Expected: FAIL com `ImportError: cannot import name 'valores_em'`

- [ ] **Step 3: Implementar**

Acrescente em `src/mobia/domain/agente/dinheiro.py`, logo depois de `_valor_de`:

```python
# `reais` DEPOIS do numero e marcador de moeda tanto quanto `R$` antes dele.
# Precisa de padrao proprio porque `_RUIDO` apaga a palavra antes de qualquer
# parsing -- para `parsear` ela e ruido mesmo, mas para `valores_em` ela e
# metade da evidencia de que aquele numero e dinheiro.
_MARCADOR_DE_REAIS = re.compile(r"\A\s*reais?\b")

# Quantos caracteres antes do numero ainda contam como lugar do `R$`. Tres
# bastam para "r$ " e nao alcancam o numero anterior.
_ALCANCE_DO_CIFRAO = 3


def valores_em(texto: str) -> tuple[int, ...]:
    """Todos os valores monetarios do texto, em centavos, na ordem.

    Diferente de `parsear`, que resolve UMA expressao ja isolada pelo modelo,
    este varre prosa livre. A diferenca de contrato que importa: aqui um
    numero so conta se vier com marcador -- `R$` antes, `reais` depois, ou
    sufixo de grandeza. Sem isso "2 quartos" e "80 m2" viram dinheiro, e a
    guarda da TEC-161 passa a bloquear turno correto (D2 do desenho).

    **Erra por falta, de proposito.** "esse ai sai por 750" nao e detectado.
    E a mesma politica que o docstring deste modulo ja declara para a
    gramatica inteira, e a alternativa -- aceitar numero nu -- troca um falso
    negativo por uma enxurrada de falso positivo.

    Nao levanta, pelo mesmo motivo que `parsear` nao levanta.
    """
    limpo = texto.casefold()
    achados = list(_NUMERO.finditer(limpo))
    valores: list[int] = []
    for indice, achado in enumerate(achados):
        if _negativo(limpo, achado.start()):
            continue
        # O escopo do marcador termina no proximo numero. E a mesma delimitacao
        # que `_faixa_de` faz para impedir o "mil" de um lado da faixa de
        # multiplicar o numero do outro lado -- ver o docstring de `_resolver`.
        fim = achados[indice + 1].start() if indice + 1 < len(achados) else len(limpo)
        sufixo = limpo[achado.end() : fim]
        antes = limpo[max(0, achado.start() - _ALCANCE_DO_CIFRAO) : achado.start()]

        valor = _resolver(achado.group().rstrip(".,"), sufixo)
        if valor is None:
            continue
        tem_marcador = (
            valor.tinha_marcador
            or _MARCADOR_DE_MOEDA.search(antes) is not None
            or _MARCADOR_DE_REAIS.match(sufixo) is not None
        )
        if tem_marcador:
            valores.append(valor.centavos)
    return tuple(valores)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v --tb=short`
Expected: PASS, inclusive os testes que já existiam — `valores_em` não muda `parsear`.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/dinheiro.py tests/unit/test_dinheiro.py
git commit -m "feat(TEC-161): a gramatica de dinheiro passa a varrer prosa livre"
```

---

### Task 2: O validador puro

**Files:**
- Create: `src/mobia/domain/agente/citacao.py`
- Test: `tests/unit/test_citacao.py`

**Interfaces:**
- Consumes: `valores_em(texto) -> tuple[int, ...]` (Task 1); `reais_de(centavos) -> str` de `domain/agente/apresentacao.py`.
- Produces:
  - `Divergencia` — dataclass `frozen=True, slots=True` com `tipo: Literal["preco", "codigo"]` e `citado: str`.
  - `divergencias_de(prosa, *, candidatos, faixa) -> tuple[Divergencia, ...]`, onde `candidatos: Sequence[Mapping[str, Any]]` e `faixa: tuple[int | None, int | None]`. Tupla vazia significa que a prosa passa.
  - `TOLERANCIA_EM_DECIMOS = 1` — a tolerância de 10%, expressa para aritmética inteira.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_citacao.py`:

```python
"""A guarda anti-alucinacao sobre a prosa do modelo. TEC-161.

Basename distinto de tudo em `tests/integration/` -- o par de integracao
chama-se `test_citacao_no_turno.py`.
"""

from typing import Any

import pytest

from mobia.domain.agente.citacao import Divergencia, divergencias_de

SEM_FAIXA: tuple[int | None, int | None] = (None, None)


def _candidato(codigo: str, preco: int) -> dict[str, Any]:
    """O que `_candidato_serializavel` devolve hoje, reduzido ao que importa."""
    return {
        "imovel_id": "0f9d1a1e-0000-4000-8000-000000000001",
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


def test_prosa_sem_cifra_nem_codigo_passa() -> None:
    assert divergencias_de(
        "Achei tres opcoes que encaixam no que voce falou.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    ) == ()


@pytest.mark.parametrize("citado", ["R$ 516.464", "516 mil", "500 mil", "R$ 470 mil"])
def test_preco_dentro_da_tolerancia_passa(citado: str) -> None:
    """D4: o modelo le 51646430 e escreve o numero arredondado do jeito dele.

    Igualdade exata reprovaria prosa correta em quase todo turno. 470 mil e o
    limite inferior dos 10% de 516.464 -- 464.817 -- por pouco.
    """
    assert divergencias_de(
        f"Tenho um por {citado}.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    ) == ()


def test_preco_fora_da_tolerancia_bloqueia() -> None:
    divergencias = divergencias_de(
        "Tenho um por R$ 700 mil.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    )
    assert divergencias == (Divergencia(tipo="preco", citado="R$ 700.000"),)


def test_o_limite_da_tolerancia_e_fechado_dos_dois_lados() -> None:
    """Exatamente 10% passa; um centavo alem nao.

    Sem este teste, trocar `<=` por `<` na comparacao passa nos outros.
    """
    candidatos = [_candidato("AP-1004", 100_000_000)]
    assert divergencias_de("R$ 1.100.000", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de("R$ 900.000", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de("R$ 1.100.001", candidatos=candidatos, faixa=SEM_FAIXA) != ()


def test_basta_um_candidato_casar() -> None:
    """A prosa fala de um imovel entre varios; nao ha como saber qual."""
    assert divergencias_de(
        "Tenho um por R$ 700 mil.",
        candidatos=[_candidato("AP-1", 51_646_430), _candidato("AP-2", 70_000_000)],
        faixa=SEM_FAIXA,
    ) == ()


def test_a_faixa_declarada_pelo_lead_e_valor_legitimo() -> None:
    """D5: o modelo ecoando o orcamento do lead nao e alucinacao.

    Sem esta valvula, "entendi, ate R$ 600 mil" bloqueia num turno de
    qualificacao pura -- que e o turno mais comum da conversa.
    """
    assert divergencias_de(
        "Entendi, ate R$ 600 mil.",
        candidatos=[],
        faixa=(None, 60_000_000),
    ) == ()


def test_sem_candidato_e_sem_faixa_qualquer_cifra_bloqueia() -> None:
    """D7: o caso RT-01 mais puro -- o modelo nao buscou e citou preco."""
    assert divergencias_de(
        "Tenho um otimo por R$ 600 mil.",
        candidatos=[],
        faixa=SEM_FAIXA,
    ) == (Divergencia(tipo="preco", citado="R$ 600.000"),)


def test_codigo_de_candidato_passa_e_codigo_inventado_bloqueia() -> None:
    candidatos = [_candidato("AP-1004", 51_646_430)]
    assert divergencias_de("O AP-1004 te atende.", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de(
        "O AP-9999 te atende.", candidatos=candidatos, faixa=SEM_FAIXA
    ) == (Divergencia(tipo="codigo", citado="AP-9999"),)


def test_codigo_de_outro_formato_nao_e_detectado() -> None:
    """D6, a lacuna travada como teste.

    A coluna e String(20) sem constraint de formato. Este teste existe para
    que quem mudar o formato do codigo do catalogo veja aqui, e nao em
    producao, que a guarda deixou de enxerga-lo.
    """
    assert divergencias_de(
        "O imovel 1004/AP te atende.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    ) == ()


def test_preco_e_codigo_divergentes_saem_juntos() -> None:
    """Uma passada, todas as divergencias -- quem investiga quer as duas."""
    divergencias = divergencias_de(
        "O AP-9999 sai por R$ 900 mil.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    )
    assert set(divergencias) == {
        Divergencia(tipo="preco", citado="R$ 900.000"),
        Divergencia(tipo="codigo", citado="AP-9999"),
    }


def test_candidato_com_preco_zero_nao_quebra_a_conta() -> None:
    """Divisao por zero seria excecao dentro da guarda, e guarda que levanta
    derruba o turno inteiro -- o oposto do que ela existe para fazer."""
    assert divergencias_de(
        "Sai por R$ 600 mil.", candidatos=[_candidato("AP-1", 0)], faixa=SEM_FAIXA
    ) != ()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_citacao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.agente.citacao'`

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/agente/citacao.py`:

```python
"""A guarda anti-alucinacao sobre a prosa do modelo. TEC-161.

Puro de proposito: nenhum I/O, nenhum banco, nenhuma chamada ao modelo -- no
molde de `apresentacao.py` e `dinheiro.py`. Guarda que depende de rede e
guarda que falha quando mais precisa funcionar.

**O que esta em jogo.** Depois da TEC-162 a ficha inteira vem do banco, entao
a unica superficie invencavel que sobrou e a prosa: o prefixo da legenda da
ficha 1 nos turnos de apresentacao, e a mensagem inteira nos outros. Este
modulo olha so para ela, e so para duas coisas dentro dela -- cifra e codigo.

**Erra por falta, nao por excesso.** Parafrase sem numero ("tenho um bem
espacoso na praia") passa. Bloquear turno correto e o unico jeito de uma
guarda anti-alucinacao perder a confianca de quem opera, e um falso positivo
custa uma resposta boa que o lead nao recebe.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mobia.domain.agente.apresentacao import reais_de
from mobia.domain.agente.dinheiro import valores_em

# 10%, em decimos, para a comparacao ficar em inteiro. `abs(d) * 10 <= preco`
# e exatamente "d esta dentro de 10% de preco", sem float e sem Decimal.
#
# O numero NAO e derivado: e emprestado da RN-09.3, que relaxa a faixa de
# preco em ate 10%. As duas coisas sao semanticamente diferentes -- relaxar
# busca nao e tolerar citacao --, e a escolha e deliberada: inventar uma
# segunda constante de tolerancia obrigaria a defender um numero novo sem
# dado para calibra-lo. Ver D4 do desenho.
#
# A janela e real: num imovel de R$ 500 mil, 50 mil reais de erro na prosa
# passam. O que a torna aceitavel e que a ficha logo abaixo, na MESMA
# mensagem, mostra o preco do banco.
TOLERANCIA_EM_DECIMOS = 1

# O formato do catalogo: AP-1004, CA-1005, TE-1001. Maiusculas de proposito --
# a prosa em minusculas nao carrega codigo. A coluna e String(20) sem
# constraint de formato, entao codigo de outra forma nao e detectado; a lacuna
# esta travada por `test_codigo_de_outro_formato_nao_e_detectado`.
_CODIGO = re.compile(r"\b[A-Z]{2,3}-\d{3,6}\b")


@dataclass(frozen=True, slots=True)
class Divergencia:
    """Uma coisa que a prosa afirmou e o banco nao sustenta.

    `citado` ja vem formatado para o log -- preco via `reais_de`, e nao em
    centavos. Nao e cosmetica: `_mascarar_digitos` (app/logging.py) come
    corridas de 10 a 15 digitos, e um imovel de R$ 10 milhoes em centavos sao
    exatamente 10 digitos. O valor sairia mascarado do log justamente no caso
    caro. Com pontos de milhar nao ha corrida.

    Nao carrega a prosa. Registra-la criaria no log exatamente aquilo que a
    guarda impediu de sair -- a mesma regra da moderacao de saida.
    """

    tipo: Literal["preco", "codigo"]
    citado: str


def _cabe_em_algum(citado: int, precos: Sequence[int]) -> bool:
    """O valor esta a menos de 10% de algum candidato.

    "Algum" e nao "o certo": a prosa fala de um imovel entre ate dez, e nao ha
    como saber qual. Exigir o candidato correto pediria uma ligacao que a
    prosa nao tem.
    """
    for preco in precos:
        if preco <= 0:
            # Preco zero ou negativo nao sustenta citacao nenhuma, e dividir
            # por ele levantaria dentro da guarda.
            continue
        if abs(citado - preco) * 10 <= preco * TOLERANCIA_EM_DECIMOS:
            return True
    return False


def _na_faixa(citado: int, faixa: tuple[int | None, int | None]) -> bool:
    """O valor esta dentro do que o lead declarou.

    Faixa toda `None` nao e faixa aberta: e ausencia de declaracao, e devolve
    False. Tratar ausencia como "qualquer valor serve" desligaria a guarda
    para todo lead que ainda nao falou de dinheiro.
    """
    minimo, maximo = faixa
    if minimo is None and maximo is None:
        return False
    if minimo is not None and citado < minimo:
        return False
    if maximo is not None and citado > maximo:
        return False
    return True


def divergencias_de(
    prosa: str,
    *,
    candidatos: Sequence[Mapping[str, Any]],
    faixa: tuple[int | None, int | None],
) -> tuple[Divergencia, ...]:
    """O que a prosa afirmou e o turno nao sustenta. Vazio significa que passa.

    `candidatos` vazio nao e caso especial: nenhum valor casa, e so a faixa do
    lead passa. E o que a TEC-265 previu ao deixar o campo nao-opcional -- "nao
    buscou" e "buscou e nao achou" tomam a mesma decisao aqui.

    Devolve TODAS as divergencias numa passada, e nao a primeira: quem
    investiga um bloqueio quer saber se o modelo errou o preco, o codigo, ou
    os dois.
    """
    precos = [int(c["preco_centavos"]) for c in candidatos if "preco_centavos" in c]
    codigos = {str(c["codigo"]) for c in candidatos if c.get("codigo")}

    divergencias: list[Divergencia] = []
    for citado in valores_em(prosa):
        if _cabe_em_algum(citado, precos) or _na_faixa(citado, faixa):
            continue
        divergencias.append(Divergencia(tipo="preco", citado=reais_de(citado)))
    for codigo in _CODIGO.findall(prosa):
        if codigo not in codigos:
            divergencias.append(Divergencia(tipo="codigo", citado=codigo))
    return tuple(divergencias)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_citacao.py -v --tb=short`
Expected: PASS, 11 testes.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/citacao.py tests/unit/test_citacao.py
git commit -m "feat(TEC-161): a prosa do modelo passa a ser conferivel contra o banco"
```

---

### Task 3: O enxerto no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (o bloco em torno da linha 566, e um helper novo perto de `_recusados_de` na linha 102)
- Test: `tests/integration/test_citacao_no_turno.py`

**Interfaces:**
- Consumes: `divergencias_de` e `Divergencia` (Task 2).
- Produces: nenhum símbolo novo exportado. O comportamento observável é: `outbound.send` nunca recebe prosa divergente, e o evento `citacao.bloqueada` sai.

**A ordem é a invariante da card.** O bloqueio acontece à esquerda da primeira reserva em `outbound_dispatches`. Bloquear depois deixaria reserva gravada e mensagem entregue.

> **Refinamento do desenho:** o diagrama da spec põe a validação antes do cálculo de `apresentando`. Na implementação ela vem **logo depois**, porque o desfecho do bloqueio depende de `apresentando`. A invariante que a card cobra — antes de `_apresentar` e de qualquer `outbound.send` — continua valendo, e é ela que o teste trava.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_citacao_no_turno.py`:

```python
"""O bloqueio de citacao dentro do turno. TEC-161.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_apresentacao_no_turno.py`, de onde o harness abaixo foi copiado. Os
arquivos de integracao deste repo sao autocontidos de proposito.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.domain.agente.turno import KINDS_DAS_FICHAS, TEXTO_DA_BUSCA_INCONCLUSIVA
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.db import get_sessionmaker

PROSA_LIMPA = "Achei tres opcoes que encaixam no que voce falou."
PROSA_INVENTADA = "Achei um otimo por R$ 900 mil."
PRECO = 51_646_430


async def _imovel(session: Any, codigo: str, preco: int) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo=codigo,
            titulo=f"Apartamento {codigo}",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=preco,
            condominio=55000,
            bairro="Lagoa da Conceicao",
            bairro_busca="lagoa da conceicao",
            cidade="Florianopolis",
            uf="SC",
            area_util_m2=54,
            quartos=4,
            suites=1,
            banheiros=2,
            vagas=2,
            caracteristicas=["churrasqueira", "mobiliado"],
            fotos=[f"https://exemplo.com/{codigo}.jpg"],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


def _candidato(identificador: uuid.UUID, codigo: str, preco: int) -> dict[str, Any]:
    return {
        "imovel_id": str(identificador),
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


class _ClassificadorComProsa:
    """Prosa fixa e candidatos fixos: o assunto aqui e a guarda, nao a busca."""

    def __init__(
        self,
        prosa: str,
        candidatos: list[dict[str, Any]],
        perguntou: tuple[str, ...] = (),
    ) -> None:
        self.prosa = prosa
        self.candidatos = candidatos
        self.perguntou = perguntou

    async def classificar(self, contexto: ContextoMontado, *, porta: Any = None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            resposta=self.prosa,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
        )

    async def desambiguar(self, contexto: ContextoMontado) -> Any:
        raise AssertionError("confianca alta o bastante para nao desambiguar")


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


async def test_prosa_consistente_segue_como_prefixo(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """O caminho feliz nao muda. Sem este teste, uma guarda quebrada que
    bloqueia SEMPRE passaria nos outros dois."""
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_LIMPA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues[0].startswith(f"{PROSA_LIMPA}\n\n")


async def test_prosa_inventada_vira_ficha_pura(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D8: descarta a prosa, nao o turno.

    O lead recebe o imovel -- que veio do banco e esta certo -- sem a frase
    que inventou um preco. A ficha e o conteudo da RN-10.1; a prosa e
    ornamento, e e ela que cede sob pressao de confianca.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 1
    assert "900" not in outbound.entregues[0]
    assert not outbound.entregues[0].startswith(PROSA_INVENTADA)
    # A ficha continua inteira: bloquear a prosa nao pode calar o imovel.
    assert "Apartamento AP-1004" in outbound.entregues[0]
    assert await _kinds_reservados() == [KINDS_DAS_FICHAS[0]]


async def test_prosa_inventada_sem_ficha_vira_verificacao_humana(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D8/D9: sem ficha para entregar, o lead recebe o corretor.

    `perguntou` faz o turno NAO apresentar, entao a prosa e a mensagem
    inteira. Descarta-la sozinha deixaria o lead em silencio.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA,
        [_candidato(identificador, "AP-1004", PRECO)],
        perguntou=("regiao",),
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [TEXTO_DA_BUSCA_INCONCLUSIVA]
    assert await _kinds_reservados() == ["reply"]


async def test_sem_busca_a_cifra_inventada_bloqueia(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D7: o caso RT-01 mais puro -- o modelo nao chamou a ferramenta e mesmo
    assim citou preco. E a lacuna 3 que a TEC-265 deixou aberta."""
    classificador = _ClassificadorComProsa(PROSA_INVENTADA, [])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [TEXTO_DA_BUSCA_INCONCLUSIVA]


async def test_nenhuma_reserva_e_gravada_antes_da_validacao(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """A invariante que a card cobra, travada como teste.

    Bloquear DEPOIS da reserva deixaria linha gravada em `outbound_dispatches`
    e mensagem entregue -- o dano exato que esta card existe para impedir.
    Um unico kind reservado, e nenhum dele carrega a prosa inventada.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert await _kinds_reservados() == [KINDS_DAS_FICHAS[0]]
    assert all("900" not in entregue for entregue in outbound.entregues)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_citacao_no_turno.py -v --tb=short`
Expected: FAIL. `test_prosa_consistente_segue_como_prefixo` passa (comportamento de hoje); os outros quatro falham porque a prosa inventada ainda sai.

> Se der `ConnectionResetError [WinError 64]` na negociação SSL, **não é o seu código**. Espere e retente — o banco demora mais que o healthcheck diz, e há ~5% de falha de connect nesta máquina mesmo com tudo de pé.

- [ ] **Step 3: Implementar o helper da faixa**

Em `src/mobia/domain/agente/turno.py`, logo depois de `_recusados_de` (linha 102):

```python
def _faixa_declarada(estado: LeadQualification | None) -> tuple[int | None, int | None]:
    """O orcamento que o lead ja declarou, na forma que `divergencias_de` recebe.

    Existe para a guarda da TEC-161 nao bloquear o modelo ecoando o proprio
    lead: "entendi, ate R$ 600 mil" nao e imovel inventado. Linha ausente vira
    faixa vazia, que `_na_faixa` trata como ausencia de declaracao -- e nao
    como faixa aberta.
    """
    if estado is None:
        return (None, None)
    return (estado.faixa_preco_min_centavos, estado.faixa_preco_max_centavos)
```

E o import, junto dos outros de `domain.agente`:

```python
from mobia.domain.agente.citacao import divergencias_de
```

- [ ] **Step 4: Implementar o enxerto**

Em `executar_turno`, logo **depois** da linha que calcula `apresentando` (~566) e **antes** do `try:` que chama `_apresentar`:

```python
    # TEC-161. A ultima coisa que acontece antes de a entrega comecar, e a
    # ordem e a invariante da card: `_apresentar` grava reserva em
    # `outbound_dispatches`, e bloquear depois dela deixaria linha gravada e
    # mensagem entregue.
    #
    # **Nao regenera**, contra a letra da RN-09.4 e com emenda no SRS. Tres
    # razoes, na ordem de peso: a moderacao de saida logo acima ja barra sem
    # regerar e duas politicas para o mesmo problema no mesmo turno seriam uma
    # a mais; uma segunda chamada reexecuta o laco de tool use da TEC-265, ou
    # seja uma busca nova, dentro de um `job_timeout` que o pior caso ja
    # estoura; e depois da TEC-162 descartar a prosa ainda entrega ate tres
    # fichas corretas, porque nenhum campo delas passou pelo modelo.
    divergencias = divergencias_de(
        texto,
        candidatos=gerada.candidatos,
        faixa=_faixa_declarada(depois_do_estado),
    )
    if divergencias:
        # A prosa barrada **nao** entra no log, pela mesma razao que o texto
        # barrado pela moderacao nao entra: registra-la criaria no log
        # exatamente aquilo que a guarda impediu de sair. Os valores
        # divergentes entram -- sao o que o modelo inventou, e sao o unico
        # dado que torna a linha investigavel.
        log.error(
            "citacao.bloqueada",
            channel=message.channel,
            message_id=str(message.id),
            tipos=[d.tipo for d in divergencias],
            citados=[d.citado for d in divergencias],
            candidatos=len(gerada.candidatos),
            apresentando=apresentando,
        )
        # Apresentando, a prosa vira prefixo vazio e `legenda_de` a omite: o
        # lead recebe a ficha do banco, que e o conteudo que a RN-10.1 exige.
        # Sem ficha para entregar, a prosa era a mensagem inteira, e o
        # substituto e o mesmo texto que o `LacoDeBuscaExcedido` ja usa --
        # ele E a proposta de verificacao com o corretor que a card pede.
        texto = "" if apresentando else TEXTO_DA_BUSCA_INCONCLUSIVA
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_citacao_no_turno.py -v --tb=short`
Expected: PASS, 5 testes.

- [ ] **Step 6: Confirmar que os vizinhos não quebraram**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py tests/integration/test_moderacao_de_saida.py tests/integration/test_busca_no_turno.py -v --tb=short`
Expected: PASS. `PROSA` em `test_apresentacao_no_turno.py` não tem cifra nem código, então a guarda não a toca — se algum ali falhar, a guarda está bloqueando prosa limpa.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_citacao_no_turno.py
git commit -m "feat(TEC-161): prosa que cita fora dos candidatos nao chega ao lead"
```

---

### Task 4: As duas emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (RN-09.4 na linha 268, CA-09.2 na linha 275)

**Interfaces:** nenhuma. É documento.

**A regra do repo:** emenda entra como item **aninhado** abaixo da regra que altera, e **nunca** reescreve o texto de 22/08/2026. Nenhuma das duas regras tem emenda ainda, então as duas são `E-01` — a numeração é por regra, como a `E-01 (TEC-158)` da RN-09.6 mostra.

- [ ] **Step 1: Emendar a RN-09.4**

Abaixo da linha da RN-09.4, com dois espaços de indentação:

```markdown
  - **Emenda E-01 (TEC-161, 09/09/2026):** a regra manda que citação fora da lista *"bloqueia o envio e força regeneração"*. A regeneração sai. O que passa a valer: a citação divergente **bloqueia a prosa do modelo** e o lead recebe as fichas montadas do banco, sem prefixo; num turno sem ficha a entregar, recebe o texto de verificação com o corretor. Nenhuma segunda geração é tentada. Três razões. A moderação de saída, dez linhas acima no mesmo `executar_turno`, já barra e substitui sem regerar — duas políticas para o mesmo problema no mesmo turno seriam uma a mais. Uma segunda chamada reexecuta o laço de tool use da TEC-265, isto é, uma busca nova com embedding, dentro de um `job_timeout` de 240 s que o pior caso das chamadas atuais já estoura. E o fato novo que a regra de 22/08 não podia conhecer: depois da TEC-162 a ficha é montada por código a partir do banco, então descartar a prosa ainda entrega até três imóveis corretos — quando a regra foi escrita, a resposta inteira vinha do modelo e descartá-la deixava o lead sem nada. **Consequência declarada:** a voz do agente some no turno bloqueado, e o lead recebe ficha sem frase de abertura. Ver a D8 de `docs/superpowers/specs/2026-09-09-tec-161-citacao-fora-dos-candidatos-design.md`.
```

- [ ] **Step 2: Emendar a CA-09.2**

Abaixo da linha da CA-09.2, com dois espaços de indentação:

```markdown
  - **Emenda E-01 (TEC-161, 09/09/2026):** o critério passa a ser *"o envio da prosa é bloqueado e o lead recebe as fichas do banco, sem prefixo"*. A cláusula "e a resposta é regerada" sai pelo mesmo argumento da Emenda E-01 da RN-09.4, acima.
```

- [ ] **Step 3: Conferir que o texto original ficou intacto**

Run: `git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md`
Expected: só linhas **acrescentadas**. Nenhuma linha da RN-09.4 ou da CA-09.2 modificada ou removida. Se aparecer `-` em alguma das duas, você reescreveu o original — desfaça.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-161): a RN-09.4 troca regeneracao por descarte da prosa"
```

---

### Task 5: Verificação final e PR

**Files:** nenhum. É a hora de provar.

- [ ] **Step 1: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 2: A margem do orçamento não se moveu**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: PASS, e a linha `margem` continua em **6,0**. Se mudou, algo desta card entrou no prompt — e nada dela deveria.

- [ ] **Step 3: A suíte inteira**

```bash
./.venv/Scripts/python.exe -u -m pytest -v --tb=short
```

**Leia isto antes de interpretar o resultado.** A suíte leva ~22 min em máquina ociosa e muito mais sob carga. Uma falha isolada com `ConnectionResetError [WinError 64]` na fixture **não autoriza conclusão nenhuma** — nem a favor nem contra a mudança. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados. Antes de atribuir qualquer falha a esta card, rode o arquivo sozinho; e guarde o hash do commit junto com o resultado.

- [ ] **Step 4: Abrir o PR**

```bash
git push -u origin feat/tec-161-citacao-fora-dos-candidatos
```

**O gate pago vai disparar.** O diff toca `src/mobia/domain/agente/`, que é um dos caminhos do filtro em `.github/workflows/evals.yml`. São 146 chamadas pagas com `secrets.ANTHROPIC_API_KEY`. **Sem saldo na conta, a Anthropic devolve 400 `Your credit balance is too low`**, toda conversa vira `FalhaDeInfraestrutura`, o teto de `TETO_DE_CONVERSAS_ABANDONADAS = 5` estoura contra 50 conversas, e o check obrigatório "Avaliacoes de IA" abre vermelho. Isso **não** é sinal sobre esta card. Confirme o saldo antes de abrir, ou abra sabendo que o merge espera.

---

## Cobertura do desenho

| Decisão | Onde |
|---|---|
| D1 — módulo puro | Task 2 |
| D2 — número só é dinheiro com marcador | Task 1, `valores_em` + tabela |
| D3 — gramática do `dinheiro.py`, não gêmea | Task 1 |
| D4 — tolerância de 10% | Task 2, `TOLERANCIA_EM_DECIMOS` + `test_o_limite_da_tolerancia_e_fechado_dos_dois_lados` |
| D5 — faixa do lead é valor legítimo | Task 2 (`_na_faixa`) + Task 3 (`_faixa_declarada`) |
| D6 — código pelo formato do catálogo | Task 2, `_CODIGO` + o teste da lacuna |
| D7 — valida sempre, inclusive sem candidatos | Task 2 e Task 3, `test_sem_busca_a_cifra_inventada_bloqueia` |
| D8 — não regenera, descarta a prosa | Task 3 |
| D9 — um texto conservador só | Task 3, `test_prosa_inventada_sem_ficha_vira_verificacao_humana` |
| D10 — evento e formatação por `reais_de` | Task 2 (`Divergencia.citado`) + Task 3 (o `log.error`) |
| D11 — orçamento zero | Task 5, Step 2 |
| Emendas ao SRS | Task 4 |
