# TEC-147 — Determinar quando o lead está qualificado: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decidir, a partir dos campos que já existem, se um lead atingiu o mínimo obrigatório da RN-05.3 — e registrar o momento em que ele atinge.

**Architecture:** Uma função pura sobre `LeadQualification`, sem coluna nova e sem migração. `gravar_estado` passa a devolver a linha que gravou, via `RETURNING` no upsert que já executa, para que o turno possa comparar o antes e o depois sem consulta extra e sem duplicar a regra de acumulação. A travessia de não-qualificado para qualificado vira uma linha de log.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (asyncio) + asyncpg, Alembic (não usado nesta card — não há migração), pytest (`asyncio_mode = "auto"`), ruff, mypy, structlog.

**Spec:** [`docs/superpowers/specs/2026-09-02-tec-147-lead-qualificado-design.md`](../specs/2026-09-02-tec-147-lead-qualificado-design.md)

## Global Constraints

- **Python ≥3.13.** `X | None`, nunca `typing.Optional`.
- **Os três gates estáticos que o CI roda**, e são três, não um. Rode todos antes de cada commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  O escopo é `src tests alembic evals`, não `src tests`. **`ruff check` passar não diz nada sobre `ruff format`** — na TEC-146 o formatador nunca rodou em 17 commits e a `main` ficou vermelha depois do merge.
- **Comentários e docstrings em português sem acento**, como todo o `src/`. Prosa em `docs/` leva acento; código não. Acento dentro de padrão regex é correto e intencional.
- **Comentário explica o *porquê*, não o quê**, e comentário desatualizado é defeito. Na TEC-146 um comentário falso escondeu um bug por duas rodadas de revisão.
- **`esta_qualificado` é pura**: sem I/O, sem banco, sem chamada ao modelo. Recebe o estado, devolve `bool`.
- **Não há migração nesta card.** Se você se pegar escrevendo uma, pare e releia a D1 — a decisão de não gravar `status` é o centro do desenho.
- **A suíte é lenta:** `tests/unit` sozinho leva ~7 minutos, a completa ~7,5. Com `-q` o pytest só imprime no fim, então saída vazia não é travamento. Use `python -u -m pytest -v` para ver progresso.
- **O Postgres demora depois de `docker compose restart`**: `alembic upgrade head` reprova por vários segundos com `ConnectionResetError` mesmo com o container marcado `healthy`. Espere e retente.
- **Cada teste verificado por mutação.** Reverter a regra que ele cobre tem de deixá-lo vermelho. Na TEC-146, *todas* as rodadas de revisão perdidas foram testes que passavam com o código certo ou errado — nunca implementação errada.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/context/qualificacao.py` *(criar)* | A regra da RN-05.3, pura. Único lugar que sabe quais campos são obrigatórios e o que conta como preenchido. |
| `src/mobia/domain/context/repositorio.py` *(modificar)* | `gravar_estado` passa a devolver a linha gravada. |
| `src/mobia/domain/agente/turno.py` *(modificar)* | Compara antes e depois, loga a travessia. |

Três tasks, uma por arquivo. A ordem é de dependência: a Task 2 precisa da função da Task 1 para nada, mas a Task 3 precisa das duas.

---

## Task 1: A regra, pura

**Files:**
- Create: `src/mobia/domain/context/qualificacao.py`
- Test: `tests/unit/test_qualificacao.py`

**Interfaces:**
- Consumes: `LeadQualification` de `mobia.domain.context.models`, `Intencao` de `mobia.domain.agente.schemas`.
- Produces: `esta_qualificado(estado: LeadQualification | None, recusados: frozenset[str] = frozenset()) -> bool` e a constante `CAMPOS_OBRIGATORIOS: tuple[str, ...]`. A Task 3 consome a função.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_qualificacao.py`:

```python
import pytest

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import esta_qualificado


def _estado(**campos) -> LeadQualification:
    """Um estado com os quatro obrigatorios preenchidos, menos o que o teste tirar.

    Construir o objeto sem sessao e proposital: a regra e pura e nao deve
    precisar de banco para ser exercitada.
    """
    base = {
        "channel": "whatsapp",
        "conversation_key": "5511999999999",
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 60_000_000,
        "regiao": "zona sul",
        "urgencia": "ATE_3_MESES",
    }
    return LeadQualification(**{**base, **campos})


def test_quatro_obrigatorios_preenchidos_qualificam():
    assert esta_qualificado(_estado()) is True


def test_estado_inexistente_nao_qualifica():
    """Lead que ainda nao tem linha nenhuma. Nao levanta."""
    assert esta_qualificado(None) is False


@pytest.mark.parametrize(
    "faltando",
    ["intencao", "regiao", "urgencia"],
)
def test_falta_de_obrigatorio_impede(faltando):
    assert esta_qualificado(_estado(**{faltando: None})) is False


def test_faixa_aberta_para_cima_qualifica():
    """RN-05.6: "ate 500 mil" grava max e deixa min nulo. Faixa aberta e faixa
    valida -- exigir os dois extremos prenderia em conversa todo lead que fala
    em teto, que e a forma mais comum de dizer orcamento."""
    obtido = esta_qualificado(
        _estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=50_000_000)
    )
    assert obtido is True


def test_faixa_aberta_para_baixo_qualifica():
    obtido = esta_qualificado(
        _estado(faixa_preco_min_centavos=30_000_000, faixa_preco_max_centavos=None)
    )
    assert obtido is True


def test_sem_nenhum_extremo_de_preco_nao_qualifica():
    obtido = esta_qualificado(
        _estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=None)
    )
    assert obtido is False


@pytest.mark.parametrize(
    "intencao",
    [Intencao.COMPRA, Intencao.ALUGUEL, Intencao.INVESTIMENTO],
)
def test_intencoes_qualificaveis(intencao):
    assert esta_qualificado(_estado(intencao=intencao.value)) is True


@pytest.mark.parametrize(
    "intencao",
    [Intencao.VENDER_IMOVEL, Intencao.SUPORTE_CONTRATO],
)
def test_intencao_de_handoff_nao_qualifica_mesmo_completa(intencao):
    """RN-03.4: VENDER_IMOVEL e SUPORTE_CONTRATO vao direto para handoff, nao
    para qualificacao. Os quatro campos podem estar preenchidos numa conversa
    dessas, e a RN-05.3 lida sozinha diria que qualifica. E o ponto onde as
    duas regras do SRS divergem, e a D2 escolheu esta leitura."""
    assert esta_qualificado(_estado(intencao=intencao.value)) is False


@pytest.mark.parametrize(
    "intencao",
    [Intencao.INDEFINIDA, Intencao.FORA_DE_ESCOPO],
)
def test_ausencia_de_intencao_nao_conta_como_intencao(intencao):
    """Depois do primeiro turno `intencao` nunca e nula -- o classificador
    sempre devolve um dos sete valores. Entao "intencao preenchida" nao pode
    ser "nao e nulo", ou a coluna estaria sempre preenchida."""
    assert esta_qualificado(_estado(intencao=intencao.value)) is False


@pytest.mark.parametrize(
    "campo",
    ["intencao", "faixa_preco", "regiao", "urgencia"],
)
def test_campo_recusado_nao_conta(campo):
    assert esta_qualificado(_estado(), recusados=frozenset({campo})) is False


def test_recusado_vence_o_valor_gravado():
    """D4, e a borda estranha declarada no desenho: o lead disse 500 mil e
    depois recusou falar de orcamento. O valor continua na coluna e o lead
    deixa de ser qualificado. E a regra da card, nao invencao do codigo."""
    obtido = esta_qualificado(
        _estado(faixa_preco_max_centavos=50_000_000), recusados=frozenset({"faixa_preco"})
    )
    assert obtido is False


def test_recusa_de_campo_desejavel_nao_atrapalha():
    """Recusar `vagas` nao e recusar obrigatorio nenhum."""
    assert esta_qualificado(_estado(), recusados=frozenset({"vagas"})) is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.context.qualificacao'`

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/context/qualificacao.py`:

```python
"""A regra que decide se o lead atingiu o minimo de qualificacao.

TEC-147, RN-05.3. Pura de proposito: sem I/O, sem banco, sem chamada ao
modelo. Nao ha coluna `status` -- "qualificado" e funcao dos campos, e uma
segunda fonte para o mesmo fato divergiria da primeira. Ver D1 do desenho.
"""

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification

# Os quatro da RN-05.3. `faixa_preco` e um nome logico, nao uma coluna: sao
# duas colunas (`_min_centavos` e `_max_centavos`) e qualquer uma delas basta.
CAMPOS_OBRIGATORIOS: tuple[str, ...] = ("intencao", "faixa_preco", "regiao", "urgencia")

# RN-03.4: VENDER_IMOVEL e SUPORTE_CONTRATO vao direto para handoff, e o SDR
# nao os qualifica. INDEFINIDA e FORA_DE_ESCOPO ficam de fora por outro
# motivo: significam ausencia de intencao utilizavel, e a coluna nunca e nula
# depois do primeiro turno, entao "preenchida" precisa desta lista para
# significar alguma coisa.
INTENCOES_QUALIFICAVEIS = frozenset(
    {Intencao.COMPRA.value, Intencao.ALUGUEL.value, Intencao.INVESTIMENTO.value}
)


def esta_qualificado(
    estado: LeadQualification | None,
    recusados: frozenset[str] = frozenset(),
) -> bool:
    """O lead atingiu o minimo obrigatorio da RN-05.3.

    `recusados` entra por parametro e nao por coluna: quem grava recusa e a
    TEC-148, que ainda nao existe. O default vazio e o comportamento de hoje,
    e a assinatura documenta a dependencia em vez de esconde-la (D5).

    Campo recusado nao conta, mesmo com valor na coluna (D4).
    """
    if estado is None:
        return False

    return all(
        _preenchido(estado, campo) for campo in CAMPOS_OBRIGATORIOS if campo not in recusados
    ) and not (recusados & set(CAMPOS_OBRIGATORIOS))


def _preenchido(estado: LeadQualification, campo: str) -> bool:
    if campo == "intencao":
        return estado.intencao in INTENCOES_QUALIFICAVEIS
    if campo == "faixa_preco":
        # Qualquer um dos extremos basta. Exigir os dois contradiz a RN-05.6,
        # que manda "ate 500 mil" virar max preenchido e min nulo.
        return (
            estado.faixa_preco_min_centavos is not None
            or estado.faixa_preco_max_centavos is not None
        )
    return getattr(estado, campo) is not None
```

> **Nota para quem implementa:** o `return` acima está escrito de forma redundante de propósito para você **não** copiá-lo assim. Um campo recusado deve reprovar direto; filtrar os recusados do `all` e depois testar a interseção é dizer a mesma coisa duas vezes, e a segunda esconde a primeira. Escreva a forma direta: se algum obrigatório está em `recusados`, devolva `False`; senão, exija `_preenchido` para todos. Faça o teste `test_campo_recusado_nao_conta` passar com a forma simples.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py -v`
Expected: PASS, 20 testes.

- [ ] **Step 5: Verificar por mutação**

Troque `INTENCOES_QUALIFICAVEIS` para incluir `VENDER_IMOVEL` e confirme que `test_intencao_de_handoff_nao_qualifica_mesmo_completa` fica vermelho. Troque o `or` da faixa por `and` e confirme que os dois testes de faixa aberta ficam vermelhos. Reverta as duas. Registre as saídas no relatório — sem isso, não há evidência de que os testes distinguem o código certo do errado.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/qualificacao.py tests/unit/test_qualificacao.py
git commit -m "feat(TEC-147): a regra do minimo de qualificacao, derivada e sem coluna"
```

---

## Task 2: `gravar_estado` devolve o que gravou

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` — `gravar_estado`
- Test: `tests/integration/test_repositorio_contexto.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `gravar_estado(...) -> LeadQualification | None`. A Task 3 consome o valor devolvido.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_repositorio_contexto.py`:

```python
async def test_gravar_estado_devolve_a_linha_gravada(session):
    """O valor vem do RETURNING, entao e o que o banco gravou -- nao o que o
    Python achou que ia gravar. E o que permite ao turno comparar antes e
    depois sem uma consulta a mais e sem recompor a regra de acumulacao."""
    devolvido = await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511988887777",
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="zona sul", faixa_preco_max_centavos=60_000_000),
    )
    assert devolvido is not None
    assert devolvido.regiao == "zona sul"
    assert devolvido.faixa_preco_max_centavos == 60_000_000
    assert devolvido.intencao == Intencao.COMPRA.value


async def test_gravar_estado_devolve_none_quando_nao_grava(session):
    """FORA_DE_ESCOPO nao grava nada -- `campos_a_gravar` devolve dict vazio e
    a funcao retorna antes de qualquer execute. Nao havendo linha gravada, nao
    ha linha a devolver, e o turno nao tem transicao a avaliar."""
    devolvido = await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511977776666",
        intencao=Intencao.FORA_DE_ESCOPO,
        extracao=Extracao(regiao="zona sul"),
    )
    assert devolvido is None


async def test_o_devolvido_traz_a_acumulacao_e_nao_so_o_turno(session):
    """Dois turnos: o segundo devolve o estado ACUMULADO, com o campo do
    primeiro ainda la. Se devolvesse so os campos deste turno, o turno leria
    "regiao ausente" e a transicao dispararia na hora errada."""
    chave = "5511966665555"
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key=chave,
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="zona sul"),
    )
    devolvido = await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key=chave,
        intencao=Intencao.COMPRA,
        extracao=Extracao(urgencia=Urgencia.ATE_3_MESES),
    )
    assert devolvido is not None
    assert devolvido.regiao == "zona sul"
    assert devolvido.urgencia == Urgencia.ATE_3_MESES.value
```

Importe `Urgencia` de `mobia.domain.agente.schemas` se ainda não estiver importado no arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_contexto.py -k devolve -v`
Expected: FAIL — `gravar_estado` devolve `None` em todos os casos, então o primeiro teste quebra em `assert devolvido is not None`.

- [ ] **Step 3: Implementar**

Em `gravar_estado`, troque a anotação de retorno para `LeadQualification | None`, acrescente `.returning(LeadQualification)` ao statement e devolva a linha. O `return` do caminho vazio (`if not campos`) passa a ser `return None`, explícito.

O `await session.execute(...)` que já existe passa a capturar o resultado:

```python
    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={...},  # inalterado
        ).returning(LeadQualification)
    )
    return resultado.scalar_one()
```

Atualize a docstring: ela hoje diz apenas *"Upsert do estado de qualificacao"*. Acrescente por que ela devolve a linha — que o valor vem do `RETURNING` e é o que o banco gravou, e que a alternativa (recompor a acumulação em Python) seria uma terceira cópia da regra que `campos_a_gravar` existe para centralizar. **Não** escreva que ela "retorna o estado atualizado" e pare aí; isso é o quê, e este repo comenta o porquê.

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_contexto.py -v
./.venv/Scripts/python.exe -m pytest tests/unit/test_estado_marcado.py tests/integration/test_turno.py -v
```
Expected: PASS. Os outros chamadores ignoram o valor devolvido e não precisam mudar — confirme que é verdade em vez de assumir.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/integration/test_repositorio_contexto.py
git commit -m "feat(TEC-147): gravar_estado devolve a linha, para o turno comparar antes e depois"
```

---

## Task 3: O turno registra a travessia

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — em torno da chamada a `gravar_estado`
- Test: `tests/integration/test_turno.py`

**Interfaces:**
- Consumes: `esta_qualificado` (Task 1), o retorno de `gravar_estado` (Task 2), e `contexto.estado`, que `montar_contexto` já produz.
- Produces: a linha de log `lead.qualificado`. Nada de código.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_turno.py`, com o capturador de log que o arquivo já usa:

```python
async def test_a_travessia_para_qualificado_e_registrada(...):
    """O evento que a RN-17.1 (taxa de qualificacao) vai precisar contar. Sem
    ele esta card entrega uma funcao que ninguem chama."""
    # Turno que completa o quarto campo obrigatorio.
    ...
    assert any(registro["event"] == "lead.qualificado" for registro in registros)


async def test_a_travessia_nao_se_repete_nos_turnos_seguintes(...):
    """Dispara na borda, nao no estado. Um lead ja qualificado que continua
    conversando nao gera o evento de novo -- senao a taxa de qualificacao
    contaria conversas, nao leads."""
    # Primeiro turno completa a qualificacao; segundo turno acrescenta `vagas`.
    ...
    assert [r["event"] for r in registros_do_segundo_turno].count("lead.qualificado") == 0


async def test_turno_que_nao_grava_estado_nao_avalia_transicao(...):
    """FORA_DE_ESCOPO: `gravar_estado` devolve None, e nao ha depois."""
    ...
    assert not any(registro["event"] == "lead.qualificado" for registro in registros)
```

Preencha os corpos seguindo a forma dos testes de turno que já existem no arquivo — eles montam a mensagem, chamam `executar_turno` e inspecionam log e banco. **Não invente uma forma nova de exercitar o turno**; use a que está lá.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py -k qualificad -v`
Expected: FAIL — nenhum `lead.qualificado` é emitido.

- [ ] **Step 3: Implementar**

Em `turno.py`, junto à chamada a `gravar_estado` (hoje por volta da linha 298):

```python
        antes = esta_qualificado(contexto.estado)
        depois_do_estado = await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
        )
        # A borda, nao o estado: um lead ja qualificado que segue conversando
        # nao gera o evento de novo, senao a taxa de qualificacao da RN-17.1
        # contaria conversas em vez de leads.
        if not antes and esta_qualificado(depois_do_estado):
            log.info(
                "lead.qualificado",
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
```

`antes` sai de `contexto.estado`, que `montar_contexto` já leu para montar o prompt — nenhuma consulta a mais. `esta_qualificado(None)` devolve `False`, então o caso `FORA_DE_ESCOPO` (em que `gravar_estado` devolve `None`) não dispara nada.

Confira o vocabulário de log que o módulo já usa antes de escolher os campos do evento: `turno.py` tem convenção própria para `channel`/`conversation_key` e ela vale mais que a forma acima.

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py -v
```
Expected: PASS

- [ ] **Step 5: Verificar por mutação**

Troque `if not antes and ...` por `if esta_qualificado(depois_do_estado)` e confirme que `test_a_travessia_nao_se_repete_nos_turnos_seguintes` fica vermelho. Reverta. É a única mutação que distingue "borda" de "estado", e é o ponto inteiro deste teste.

- [ ] **Step 6: Suíte completa, gates e commit**

```bash
./.venv/Scripts/python.exe -m pytest
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_turno.py
git commit -m "feat(TEC-147): o turno registra a travessia para qualificado"
```

Falhas intermitentes conhecidas sob carga (`ConnectionResetError`, Redis) em `test_montagem.py`, `test_sweep_stalled.py` e `test_dedup_por_message_id.py` passam isoladas e não são desta card — rode o arquivo sozinho antes de investigar.

---

## Auto-revisão

**Cobertura da spec.** D1 → Task 1. D2 → Task 1 (`test_intencoes_qualificaveis`, `test_intencao_de_handoff_nao_qualifica_mesmo_completa`, `test_ausencia_de_intencao_nao_conta_como_intencao`). D3 → Task 1 (os três testes de faixa e os de campo faltando). D4 → Task 1 (`test_recusado_vence_o_valor_gravado`). D5 → Task 1 (parâmetro com default). D6 → Tasks 2 e 3. O fluxo da spec está distribuído entre as três. As cinco lacunas declaradas continuam lacunas — nenhuma task tenta fechá-las, o que é o pretendido.

**Consistência de tipos.** `esta_qualificado(estado: LeadQualification | None, recusados: frozenset[str]) -> bool` nasce na Task 1 e é chamada com essa assinatura na Task 3, inclusive com `None` (o retorno da Task 2). `gravar_estado(...) -> LeadQualification | None` nasce na Task 2 e é consumida na Task 3. `CAMPOS_OBRIGATORIOS` usa `"faixa_preco"` como nome lógico, e é o mesmo string que os testes de recusa passam — as duas pontas batem.

**Risco declarado.** O Step 3 da Task 1 traz uma implementação deliberadamente redundante do tratamento de `recusados`, com nota mandando escrever a forma direta. É o mesmo padrão que a TEC-146 usou e que gerou uma ruling de pre-flight; aqui a nota já vem no plano para que o implementador não commite a versão redundante.

**Lacuna do plano, declarada.** Os corpos dos três testes da Task 3 não estão escritos — só suas asserções e docstrings. É deliberado: `test_turno.py` tem uma forma própria de montar mensagem e chamar `executar_turno`, e transcrevê-la de memória aqui produziria um teste que não roda. O implementador copia a forma que está no arquivo. É a única parte deste plano que não é literal, e está marcada.
