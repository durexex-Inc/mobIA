# TEC-140 — Aplicar o formato humanizado de resposta: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma resposta longa do agente deixa de chegar ao lead como parede de texto, sem que nada do que o agente disse se perca.

**Architecture:** Uma função pura quebra o texto na última fronteira de frase que cabe em 600 caracteres, em no máximo duas partes. O turno entrega as partes como mensagens distintas, com `kind` próprio para cada uma — sem isso a segunda seria suprimida como reentrega pela `UNIQUE (message_id, kind)`. A apresentação e as trilhas de texto fixo ficam de fora.

**Tech Stack:** Python 3.13, SQLAlchemy async, Postgres, `pytest` com `pytest-asyncio`.

**Spec:** [`docs/superpowers/specs/2026-09-11-tec-140-formato-humanizado-design.md`](../specs/2026-09-11-tec-140-formato-humanizado-design.md)

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/` leva acento. Nenhum linter checa isso.
- **Este repo comenta o porquê, não o quê, e trata comentário desatualizado como defeito.**
- **Os três gates estáticos antes de todo commit** — o formatador é gate separado do linter:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Commit:** `tipo(TEC-140): o que passou a ser verdade`, assunto em português sem acento.
- **Rodapé obrigatório:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **A suíte inteira leva ~13-19 minutos.** Rode arquivos isolados durante as tarefas; a suíte inteira só na Task 5, e **sozinha** — nada mais pode tocar o Postgres enquanto ela roda, porque a fixture autouse `banco_limpo` dá `TRUNCATE ... CASCADE` e contamina execuções concorrentes.
- **`ConnectionResetError [WinError 64]` e `CannotConnectNowError` ocorrem em ~5% dos connects** mesmo com tudo saudável. Rode de novo antes de diagnosticar.
- **Nada em `evals/` é executado neste plano** — são chamadas pagas ao provedor. O gate mede o formato e continua medindo; esta card não o altera nem o roda.

---

### Task 1: A quebra, como função pura

**Files:**
- Create: `src/mobia/domain/agente/formato.py`
- Test: `tests/unit/test_formato_da_resposta.py`

**Interfaces:**
- Produces:
  - `MAX_CARACTERES_POR_MENSAGEM: int` (valor `600`)
  - `MAX_MENSAGENS_DE_TEXTO: int` (valor `2`)
  - `def quebrar_em_mensagens(texto: str) -> tuple[str, ...]`

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_formato_da_resposta.py`:

```python
from mobia.domain.agente.formato import (
    MAX_CARACTERES_POR_MENSAGEM,
    quebrar_em_mensagens,
)


def test_texto_curto_sai_inteiro_numa_parte_so() -> None:
    """O caminho de 99% dos turnos. Uma regressao aqui trocaria o comum pelo
    raro -- todo lead passaria a receber duas mensagens para caber o 1 em 10
    que estoura.
    """
    assert quebrar_em_mensagens("Oi! Em qual regiao voce procura?") == (
        "Oi! Em qual regiao voce procura?",
    )


def test_texto_no_limite_exato_nao_quebra() -> None:
    """O empate nao fica ao acaso: exatamente 600 ainda cabe numa mensagem.
    A TEC-229 existe porque um teste de janela se apoiou em empate exato.
    """
    texto = "a" * MAX_CARACTERES_POR_MENSAGEM
    assert quebrar_em_mensagens(texto) == (texto,)


def test_quebra_na_fronteira_de_frase() -> None:
    """Corta onde o leitor ja pararia. Quebrar no meio de uma frase entrega
    duas mensagens que so fazem sentido juntas, que e pior que uma longa.
    """
    primeira = "Encontrei tres opcoes no centro. " * 18  # ~594 chars
    segunda = "Quer que eu detalhe alguma?"
    partes = quebrar_em_mensagens(primeira + segunda)

    assert len(partes) == 2
    assert partes[0].endswith(".")
    assert partes[1] == segunda


def test_sem_fronteira_de_frase_cai_para_fronteira_de_palavra() -> None:
    """Um paragrafo unico e longo nao tem ponto final para cortar. Cortar no
    meio da palavra pareceria bug ao lead -- o mesmo argumento que
    `_prosa_que_cabe` ja usa em `apresentacao.py`.
    """
    partes = quebrar_em_mensagens("palavra " * 100)

    assert len(partes) == 2
    assert not partes[0].endswith("palavr")
    assert partes[0].endswith("palavra")


def test_nada_se_perde_nunca() -> None:
    """A invariante da D2, e a razao de nao cortarmos o excedente: o lead
    nunca perde, sem saber, conteudo que o agente tinha a dizer.
    """
    for texto in (
        "curto",
        "a" * 599,
        "a" * 600,
        "a" * 601,
        "frase. " * 200,
        "palavra " * 400,
    ):
        assert "".join(quebrar_em_mensagens(texto)).replace(" ", "") == texto.replace(
            " ", ""
        )


def test_acima_de_1200_a_segunda_parte_estoura_e_isso_e_deliberado() -> None:
    """Degradacao declarada (D2). Entre perder conteudo, estourar o teto de
    duas mensagens da emenda E-02 -- clausula da MESMA regra -- e entregar uma
    segunda mensagem longa, a terceira e a menos ruim. O gate continua
    contando o excedente.
    """
    partes = quebrar_em_mensagens("frase curta. " * 200)

    assert len(partes) == 2
    assert len(partes[1]) > MAX_CARACTERES_POR_MENSAGEM
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_formato_da_resposta.py -v
```

Esperado: `ModuleNotFoundError: mobia.domain.agente.formato`.

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/agente/formato.py`. Puro: sem I/O, sem banco, sem chamada ao modelo — mesma forma de `dinheiro.py` e `apresentacao.py`.

O docstring do módulo precisa registrar **por que a segunda parte pode estourar**: a RN-04.2 carrega três cláusulas e duas delas competem acima de ~1.200 caracteres (600 por mensagem, máximo 2 mensagens). Cortar o excedente perderia conteúdo; uma terceira mensagem violaria a outra cláusula da mesma regra. A escolha é deixar a segunda passar, e está na D2 do desenho.

A função procura a última fronteira de frase (`.`, `!`, `?`, quebra de linha) em ou antes de `MAX_CARACTERES_POR_MENSAGEM`; não havendo nenhuma, cai para a última fronteira de palavra. Devolve **sempre** uma tupla, com uma ou duas partes, e nunca mais que `MAX_MENSAGENS_DE_TEXTO`.

- [ ] **Step 4: Rodar para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_formato_da_resposta.py -v
```

Esperado: PASS nos seis.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/formato.py tests/unit/test_formato_da_resposta.py
git commit -m "feat(TEC-140): a resposta longa passa a ter onde quebrar

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Os kinds, e a guarda sobre as constantes de texto fixo

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (constantes, por volta da linha 62)
- Test: `tests/unit/test_formato_da_resposta.py`

**Interfaces:**
- Consumes: `MAX_CARACTERES_POR_MENSAGEM` (Task 1).
- Produces: `KINDS_DA_RESPOSTA: tuple[str, str]` (valor `("reply", "reply_2")`), com `KIND_DA_RESPOSTA` preservado.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/unit/test_formato_da_resposta.py`:

```python
def test_o_primeiro_kind_continua_sendo_reply() -> None:
    """`outbound_dispatches` ja tem linhas gravadas com "reply", e varios
    testes afirmam `_kinds_reservados() == ["reply"]`. Renomear o primeiro
    kind invalidaria as duas coisas para ganhar nada.
    """
    from mobia.domain.agente.turno import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA

    assert KINDS_DA_RESPOSTA[0] == KIND_DA_RESPOSTA == "reply"


def test_os_dois_kinds_sao_distintos_e_nao_colidem_com_os_vizinhos() -> None:
    """A UNIQUE (message_id, kind) e o que torna o reprocessamento seguro. Dois
    kinds iguais no mesmo turno fariam a SEGUNDA mensagem ser suprimida como
    reentrega -- o lead receberia metade da resposta, em silencio, e o log
    diria que estava tudo certo.
    """
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, KINDS_DAS_FICHAS
    from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT

    assert len(set(KINDS_DA_RESPOSTA)) == len(KINDS_DA_RESPOSTA)
    assert not set(KINDS_DA_RESPOSTA) & set(KINDS_DAS_FICHAS)
    assert KIND_DA_CONFIRMACAO_DE_OPTOUT not in KINDS_DA_RESPOSTA


def test_toda_constante_de_texto_fixo_cabe_numa_mensagem() -> None:
    """As tres trilhas de `_entregar_texto_fixo` NAO passam pela quebra (D1):
    aqueles textos sao constantes deste repositorio, escolhidas curtas de
    proposito. Este teste existe para que uma constante longa escrita no futuro
    reprove aqui, e nao chegue ao lead sem guarda nenhuma -- quem a escrevesse
    nao teria motivo para saber que aquele caminho e desguarnecido.
    """
    from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
    from mobia.domain.agente.turno import TEXTO_DA_BUSCA_INCONCLUSIVA
    from mobia.domain.moderacao.port import (
        TEXTO_DA_RECUSA_DE_ENTRADA,
        TEXTO_NEUTRO_DE_SAIDA,
    )
    from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT

    for constante in (
        TEXTO_DA_IDENTIFICACAO,
        TEXTO_DA_BUSCA_INCONCLUSIVA,
        TEXTO_DA_RECUSA_DE_ENTRADA,
        TEXTO_NEUTRO_DE_SAIDA,
        TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    ):
        assert 0 < len(constante) <= MAX_CARACTERES_POR_MENSAGEM
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_formato_da_resposta.py -v
```

Esperado: `ImportError` em `KINDS_DA_RESPOSTA`. O teste das constantes deve **passar já** — se ele falhar, alguma constante já está acima de 600 hoje, o que é um achado a reportar, não a contornar.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/agente/turno.py`, junto de `KIND_DA_RESPOSTA` e `KINDS_DAS_FICHAS`:

```python
# Dois kinds e nao um repetido, pelo mesmo motivo de `KINDS_DAS_FICHAS`: a
# `UNIQUE (message_id, kind)` de `outbound_dispatches` e o que torna o
# reprocessamento seguro, e duas mensagens com o mesmo kind fariam a segunda
# ser suprimida como reentrega -- o lead receberia metade da resposta em
# silencio.
#
# O primeiro continua sendo `KIND_DA_RESPOSTA` e nao um nome novo: ha linhas
# gravadas com "reply" e testes que afirmam `_kinds_reservados() == ["reply"]`.
#
# Efeito colateral util da reserva por kind: se a segunda mensagem falhar no
# envio, a retentativa do sweeper reentrega SO ela -- a primeira ja tem reserva
# e e suprimida.
KINDS_DA_RESPOSTA = (KIND_DA_RESPOSTA, "reply_2")
```

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_formato_da_resposta.py -v
```

Esperado: PASS nos nove.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/unit/test_formato_da_resposta.py
git commit -m "feat(TEC-140): a segunda mensagem de texto ganha kind proprio

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A fiação no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (bloco de entrega, `else:` por volta da linha 739)
- Test: `tests/integration/test_formato_no_turno.py`

**Interfaces:**
- Consumes: `quebrar_em_mensagens` (Task 1), `KINDS_DA_RESPOSTA` (Task 2).

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_formato_no_turno.py`:

```python
from typing import Any

from sqlalchemy import select

from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.db import get_sessionmaker


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


async def test_resposta_curta_continua_saindo_numa_mensagem_so(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, moderador_fake: Any, rodar_turno: Any,
) -> None:
    """O caminho de 99% dos turnos, e o que esta card nao pode quebrar. Uma
    regressao aqui faria todo lead receber duas mensagens para atender ao 1 em
    10 que estoura os 600.
    """
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    assert len(outbound.entregues) == 1
    assert await _kinds_reservados() == ["reply"]


async def test_resposta_longa_sai_em_duas_mensagens_com_kinds_distintos(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, moderador_fake: Any, rodar_turno: Any,
) -> None:
    """E o texto entregue, concatenado, e o texto que o modelo gerou -- nada se
    perde entre a geracao e o WhatsApp do lead.
    """
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(resposta=longa), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    assert len(outbound.entregues) == 2
    assert await _kinds_reservados() == ["reply", "reply_2"]
    assert "".join(outbound.entregues).replace(" ", "") == longa.replace(" ", "")


async def test_o_recorder_grava_o_texto_inteiro_numa_linha_so(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, moderador_fake: Any, rodar_turno: Any,
) -> None:
    """A transcricao carrega o conteudo completo, e nao a fronteira entre as
    duas mensagens. Declarado na secao de testes do desenho: o corretor que ler
    o handoff ve o texto inteiro, mas nao ve que o lead o recebeu em duas
    partes. Este teste existe para que essa diferenca seja uma escolha
    registrada, e nao uma surpresa em auditoria.
    """
    from mobia.domain.messages.models import Message, MessageRole
    from mobia.infra.crypto import aad_de, decrypt

    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(resposta=longa), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    faladas = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()
    assert len(faladas) == 1
    gravado = decrypt(faladas[0].text_body, aad_de(faladas[0].id, "text_body"))
    assert gravado == longa
```

Se o import de `decrypt`/`aad_de` não bater, siga o que `_texto_gravado` em `tests/integration/test_apresentacao_no_turno.py` já faz — ele já lê exatamente isso.

Se `classificador_fake` não aceitar `resposta=`, use a forma que `tests/integration/test_turno.py` já usa para fixar o texto da resposta, e siga o padrão de lá em vez de inventar fixture nova.

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py -v --tb=short
```

Esperado: o primeiro passa (comportamento atual), o segundo falha — uma mensagem só, texto inteiro.

- [ ] **Step 3: Implementar**

No `else:` do bloco de entrega (por volta da linha 739), troque o `outbound.send` único por um laço sobre as partes:

```python
        else:
            # `entregue` fica True se QUALQUER parte entrou. A alternativa --
            # exigir todas -- trataria "a segunda caiu na janela fechada" como
            # turno sem resposta, quando o lead ja recebeu a primeira.
            #
            # Se a segunda falhar, a excecao sobe e o tratamento existente
            # decide o desfecho. A retentativa do sweeper reentrega so ela: a
            # primeira ja tem reserva por kind e e suprimida.
            entregue = False
            for kind, parte in zip(KINDS_DA_RESPOSTA, quebrar_em_mensagens(texto)):
                entregue = await outbound.send(
                    message.id,
                    kind,
                    {
                        "para": message.conversation_key,
                        "de": message.recipient_external_id,
                        "texto": parte,
                    },
                ) or entregue
```

O `zip` trunca pela menor sequência, o que é a garantia que queremos: `quebrar_em_mensagens` nunca devolve mais que `MAX_MENSAGENS_DE_TEXTO` partes, e ainda que devolvesse, não haveria kind para a terceira.

Acrescente o import de `quebrar_em_mensagens` no topo.

**E acrescente, logo acima desse bloco, o motivo pelo qual só o tamanho ganhou guarda** — é a D4 do desenho, e o lugar onde alguém vai procurar é aqui, não no spec:

```python
        # So o TAMANHO ganha guarda aqui. As outras duas clausulas da RN-04.2
        # continuam vigiadas so pelo gate (`aderencia_ao_tom`, piso de 90%), e
        # o motivo e que fecha-las em runtime custaria mais do que resolvem:
        #
        # - Perguntas: exigiria regenerar a resposta, que a TEC-161 ja recusou
        #   com emenda no SRS -- a segunda chamada reexecuta o laco de tool use
        #   dentro de um `job_timeout` que o pior caso ja estoura. Descartar
        #   perguntas do texto muda o que o agente quis dizer, e a regra existe
        #   contra questionario, nao contra a segunda pergunta (emenda E-01,
        #   medida sobre 294 turnos).
        # - Emoji: a RNF-42 fala de COMPREENSAO ("a informacao essencial nunca
        #   depende de emoji"), e o comentario de `evals/metricas.py` registra
        #   que por isso a metrica reporta presenca e quantidade como
        #   diagnostico, sem reprovar. Uma guarda deterministica contaria
        #   figurinhas em vez de checar se a frase sobrevive sem elas.
```

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py -v --tb=short
```

Esperado: PASS nos dois.

- [ ] **Step 5: Rodar os testes de turno que existiam**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py tests/integration/test_citacao_no_turno.py tests/integration/test_moderacao_de_saida.py tests/integration/test_identificacao_no_turno.py tests/features/ -v --tb=short
```

Esperado: PASS. Respostas curtas continuam saindo numa mensagem só, então nada deveria quebrar. **Se algo quebrar, leia antes de consertar:** a card anterior (TEC-139) deixou testes vermelhos em três arquivos por não os ter rodado, e o conserto correto preserva o que cada teste prova.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/
git commit -m "feat(TEC-140): a resposta longa chega ao lead em duas mensagens, sem perder nada

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: As três interações que ninguém lembraria de conferir

**Files:**
- Test: `tests/integration/test_formato_no_turno.py`

- [ ] **Step 1: Escrever os testes**

```python
async def test_o_prefixo_da_identificacao_conta_para_os_600(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, moderador_fake: Any, rodar_turno: Any,
) -> None:
    """A identificacao da TEC-139 e prefixada ANTES da quebra, entao ela empurra
    o texto para cima dos 600. Uma resposta que caberia sozinha pode passar a
    quebrar por causa dela -- e a interacao que ninguem conferiria, porque cada
    card sozinha esta certa.
    """
    quase = "Uma frase de tamanho medio para encher a resposta. " * 10  # ~510
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(resposta=quase), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    assert len(outbound.entregues) == 2, (
        "em conversa nova a identificacao soma ~131 chars e deveria empurrar "
        "este texto para duas mensagens"
    )


async def test_apresentacao_com_prosa_longa_nao_ganha_mensagem_de_texto_extra(
    session: Any, outbound_fake: Any, resumidor_fake: Any,
    contador_fake: Any, rodar_turno: Any,
) -> None:
    """Na apresentacao a prosa vira prefixo da legenda e `legenda_de` tem teto e
    regra de corte proprios (D14 da TEC-162). A quebra desta card nao pode
    alcancar aquele caminho, senao duas regras de tamanho disputariam o mesmo
    texto.
    """
    # Ver Step 1b: este teste vai em test_apresentacao_no_turno.py.


async def test_o_teto_de_duas_mensagens_de_texto_vale_no_pior_caso(
    session: Any, classificador_fake: Any, outbound_fake: Any,
    resumidor_fake: Any, contador_fake: Any, moderador_fake: Any, rodar_turno: Any,
) -> None:
    """A terceira clausula da RN-04.2, que ate agora era verdade por construcao
    e nao tinha nada travando. O pior caso soma identificacao e quebra: se
    alguem acrescentar uma terceira mensagem de texto no futuro, reprova aqui.
    """
    longa = "Uma frase bem longa para forcar a quebra da resposta. " * 30
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(resposta=longa), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    assert len(outbound.entregues) <= 2
```

- [ ] **Step 1b: O teste da apresentação, no arquivo dele**

Ele precisa dos helpers privados de `test_apresentacao_no_turno.py`, e os arquivos de integração deste repo são autocontidos por convenção — então vai **naquele** arquivo, e não no novo:

```python
async def test_prosa_longa_na_apresentacao_nao_vira_mensagem_de_texto_extra(
    session: Any, outbound_fake: Any, resumidor_fake: Any,
    contador_fake: Any, rodar_turno: Any,
) -> None:
    """Na apresentacao a prosa vira prefixo da legenda, e `legenda_de` tem teto
    e regra de corte proprios (D14 da TEC-162). A quebra da TEC-140 nao pode
    alcancar este caminho: duas regras de tamanho disputando o mesmo texto
    discordariam na primeira vez que alguem mexesse numa delas.
    """
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA

    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)],
        prosa="Uma prosa bem longa para forcar o corte da legenda. " * 15,
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert len(outbound.entregues) == 3
    reservados = await _kinds_reservados()
    assert not set(reservados) & set(KINDS_DA_RESPOSTA)
```

Se `_ClassificadorComCandidatos` não aceitar `prosa=`, use a forma que `test_a_prosa_vira_prefixo_da_primeira_e_as_outras_sao_ficha_pura` já usa para fixar a prosa naquele arquivo. `_conversa_ja_existe` já existe lá desde a TEC-139 — sem ele a identificação somaria uma quarta mensagem e o teste mediria outra coisa.

- [ ] **Step 2: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_formato_no_turno.py tests/integration/test_apresentacao_no_turno.py -v --tb=short
```

Esperado: PASS. Se o teste da identificação falhar por o texto não ter passado de 600, ajuste o **tamanho do texto do teste**, não o código — o ponto é exercitar a soma.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/integration/
git commit -m "test(TEC-140): as tres interacoes do formato ficam travadas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Suíte completa e PR

- [ ] **Step 1: Rodar a suíte inteira, sozinha**

```bash
./.venv/Scripts/python.exe -u -m pytest -q --tb=short
```

**Nada mais pode tocar o Postgres enquanto ela roda.** Leva ~13-19 minutos.

- [ ] **Step 2: Separar falha real de flake**

Para cada falha, rode o arquivo sozinho antes de atribuí-la à mudança. Guarde o hash junto com o resultado.

- [ ] **Step 3: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 4: Abrir o PR**

```bash
git push -u origin feat/tec-140-formato-humanizado
```

O corpo cita os cinco critérios de aceite Gherkin da card e onde cada um é verificado — incluindo os dois que esta card **não** fecha (indicador de digitação e emoji), com o motivo. Traz as lacunas declaradas do desenho. Termina com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 5: Abrir a card do indicador de digitação**

A RN-04.7 saiu do escopo desta card e precisa de card própria, no épico TEC-133. Ela deve registrar, para quem pegar: que **não existe nada** hoje, nem código nem métrica; que a RN-04.7 **não tem emenda**, apesar do título da TEC-258 dizer que emendou (o comentário em `evals/metricas.py:388` explica que aquele número era citação errada); e que a regra exige saber que a geração passou de 4 s e chamar a API do WhatsApp **no meio do turno**, o que é comportamento de canal e não formato de texto.
