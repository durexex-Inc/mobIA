# TEC-139 — Identificar-se como assistente virtual: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O lead passa a saber com quem está falando na primeira mensagem de cada conversa, sem que isso dependa de o modelo lembrar.

**Architecture:** A fronteira de conversa não existe no sistema e é derivada do timeline de `messages` — sem mensagem anterior deste lead nos últimos 30 dias, é conversa nova. A identificação é texto fixo montado por código e aplicado em dois pontos do turno, cobrindo as cinco trilhas de saída. Num turno de apresentação ela sai como mensagem própria, porque a prosa é cortável e ela não pode ser.

**Tech Stack:** Python 3.13, SQLAlchemy async, Postgres, `pytest` com `pytest-asyncio`, `structlog`.

**Spec:** [`docs/superpowers/specs/2026-09-11-tec-139-identificacao-do-assistente-design.md`](../specs/2026-09-11-tec-139-identificacao-do-assistente-design.md)

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/` leva acento. Nenhum linter checa isso.
- **Este repo comenta o porquê, não o quê, e trata comentário desatualizado como defeito.**
- **Os três gates estáticos antes de todo commit** — o formatador é gate separado do linter:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Mensagem de commit:** `tipo(TEC-139): o que passou a ser verdade`, assunto em português sem acento.
- **Rodapé obrigatório:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **A suíte inteira leva ~15-22 minutos.** Rode arquivos isolados durante as tarefas; a suíte inteira só na Task 7, e **sozinha** — nada mais pode tocar o Postgres enquanto ela roda, porque a fixture autouse `banco_limpo` dá `TRUNCATE ... CASCADE` e contamina execuções concorrentes.
- **`ConnectionResetError [WinError 64]` ocorre em ~5% dos connects** mesmo com tudo saudável. Uma falha isolada com esse traceback não autoriza conclusão nenhuma — rode de novo antes de diagnosticar.
- **`SISTEMA_DO_AGENTE` não muda neste plano** até a Task 6 dizer que precisa. A margem do orçamento é de 6,2 tokens.

---

### Task 1: A fronteira de conversa derivada

**Files:**
- Create: `src/mobia/domain/agente/identificacao.py`
- Test: `tests/integration/test_identificacao_fronteira.py`

**Interfaces:**
- Consumes: `Message` de `mobia.domain.messages.models`.
- Produces:
  - `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA: int` (valor `30`)
  - `async def e_conversa_nova(session_factory, message: Message) -> bool`

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_identificacao_fronteira.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import e_conversa_nova
from mobia.infra.db import get_sessionmaker


async def test_lead_sem_historico_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    """O caso que o predicado existe para pegar, e o que quase nao funciona.

    A ingestao grava a linha em `messages` ANTES de o worker existir, entao
    quando esta funcao roda a fala corrente JA esta no timeline. Uma consulta
    por "alguma mensagem nos ultimos 30 dias" acharia sempre a propria, e
    conversa nova seria permanentemente falso -- a identificacao nunca sairia,
    e todo teste de "nao repete na segunda mensagem" continuaria verde pelo
    motivo errado.
    """
    linha = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), linha) is True


async def test_mensagem_de_ontem_nao_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_mensagem_de_31_dias_atras_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=31)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is True


async def test_mensagem_de_29_dias_atras_nao_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=29)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_o_limite_exato_de_30_dias_tem_lado_definido(
    session: AsyncSession, semear_entrada
) -> None:
    """O empate nao fica ao acaso.

    A TEC-229 existe porque um teste de janela se apoiou em empate exato e deu
    falsa seguranca. Aqui o lado e escolhido e fixado: exatamente 30 dias de
    silencio ainda NAO abre conversa nova -- o corte e "mais de 30".
    """
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=30)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_mensagem_de_outro_lead_nao_conta(
    session: AsyncSession, semear_entrada
) -> None:
    """O predicado e por lead, nao global. Sem o filtro de conversa, o primeiro
    lead do dia abriria conversa nova e nenhum outro abriria.
    """
    from mobia.domain.messages.models import Message

    outro = await semear_entrada(session)
    outro.conversation_key = "5511999998888"
    outro.created_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    atual = await semear_entrada(session)
    assert isinstance(atual, Message)
    assert await e_conversa_nova(get_sessionmaker(), atual) is True
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_fronteira.py -v
```

Esperado: `ModuleNotFoundError: mobia.domain.agente.identificacao`.

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/agente/identificacao.py`:

```python
"""Quem o agente diz que e, e quando ele diz (TEC-139).

**A fronteira de conversa nao existe neste sistema, e isto aqui e um
substituto declarado.** A emenda E-01 da TEC-148 sob a RN-05.7 registra que
`conversation_key` e o id externo do LEAD, que nenhuma tabela distingue
conversas, e que introduzir a entidade foi deferido. A TEC-130 e quem a cria.

Ate la, "conversa nova" e uma janela de silencio: nada deste lead nos ultimos
30 dias. O numero nao foi escolhido aqui -- e o mesmo que a TEC-130 nomeia no
proprio titulo. Usar outro criaria duas definicoes antes de a primeira
existir.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message

# Mesmo limiar da TEC-130. Quando aquela card chegar, este modulo passa a
# perguntar a entidade em vez de derivar, e esta constante sai.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30


async def e_conversa_nova(
    session_factory: async_sessionmaker[AsyncSession],
    message: Message,
) -> bool:
    """Houve silencio longo o bastante antes desta mensagem?

    **`Message.id != message.id` e o que faz isto funcionar.** A ingestao
    grava a fala em `messages` antes de o worker rodar, entao a mensagem
    corrente ja esta no timeline quando esta funcao e chamada. Sem a exclusao,
    a consulta acha sempre a propria mensagem, o predicado e sempre falso e a
    identificacao nunca sai -- em silencio, com os testes de "nao repete"
    passando pelo motivo errado.

    Empate resolvido para o lado conservador: exatamente 30 dias ainda nao
    abre conversa nova. Nao repetir a identificacao incomoda menos que
    repeti-la, e o empate ficar ao acaso e o defeito que a TEC-229 documentou.
    """
    corte = datetime.now(UTC) - timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)
    async with session_factory() as session:
        anterior = await session.scalar(
            select(Message.id)
            .where(
                Message.channel == message.channel,
                Message.conversation_key == message.conversation_key,
                Message.id != message.id,
                Message.created_at >= corte,
            )
            .limit(1)
        )
    return anterior is None
```

- [ ] **Step 4: Rodar para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_fronteira.py -v --tb=short
```

Esperado: PASS nos seis.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/identificacao.py tests/integration/test_identificacao_fronteira.py
git commit -m "feat(TEC-139): conversa nova passa a ter definicao operacional derivada

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: O texto da identificação

**Files:**
- Modify: `src/mobia/domain/agente/identificacao.py`
- Test: `tests/unit/test_identificacao_texto.py`

**Interfaces:**
- Produces: `TEXTO_DA_IDENTIFICACAO: str`, `SEPARADOR_DA_IDENTIFICACAO: str`

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_identificacao_texto.py`:

```python
from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
)


def test_o_texto_se_identifica_como_assistente_virtual() -> None:
    """A RN-04.1 em letra: o agente diz que e assistente virtual. Nao basta o
    prompt saber -- o lead precisa ler.
    """
    baixo = TEXTO_DA_IDENTIFICACAO.lower()
    assert "assistente virtual" in baixo


def test_o_texto_oferece_o_corretor() -> None:
    """A terceira regra de negocio da card, no caminho proativo. Sem isso a
    transparencia vira aviso, e a RN-B01 pede saida para humano disponivel.
    """
    assert "corretor" in TEXTO_DA_IDENTIFICACAO.lower()


def test_o_texto_nao_finge_ser_pessoa() -> None:
    """A RN-04.1 proibe fingir ser pessoa fisica. Um texto que se apresente com
    nome proprio de gente ("Oi, sou a Marina") violaria a regra que ele existe
    para cumprir.
    """
    baixo = TEXTO_DA_IDENTIFICACAO.lower()
    for proibido in ("sou a ", "sou o ", "meu nome e"):
        assert proibido not in baixo


def test_o_texto_e_curto_o_bastante_para_preceder_uma_resposta() -> None:
    """Ele vai na FRENTE de outra mensagem em quatro das cinco trilhas. Longo,
    empurra a resposta para baixo e vira parede de texto -- exatamente o que o
    teto de 600 caracteres da RN-04.2 existe para evitar.
    """
    assert 0 < len(TEXTO_DA_IDENTIFICACAO) <= 160


def test_o_separador_nao_cola_as_duas_mensagens() -> None:
    assert SEPARADOR_DA_IDENTIFICACAO.strip() == ""
    assert "\n" in SEPARADOR_DA_IDENTIFICACAO
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_identificacao_texto.py -v
```

Esperado: `ImportError`.

- [ ] **Step 3: Implementar**

Acrescente a `src/mobia/domain/agente/identificacao.py`:

```python
# Generico de proposito: nao ha nome de imobiliaria configuravel em
# `app/config.py`, e a propria RN-04.1 e generica ("assistente virtual da
# imobiliaria"). Inventar um campo de configuracao que ninguem pediu seria
# maior que esta card.
#
# Nao se apresenta com nome de gente: a mesma regra proibe fingir ser pessoa
# fisica, e "Oi, sou a Marina" violaria o que este texto existe para cumprir.
#
# Oferece o corretor porque a terceira regra da card pede isso ao se
# identificar -- aqui no caminho proativo.
TEXTO_DA_IDENTIFICACAO = (
    "Oi! Sou o assistente virtual da imobiliaria. Posso te ajudar a encontrar "
    "um imovel, e a qualquer momento te passo para um corretor."
)

# Linha em branco e nao espaco: as duas frases tem autores diferentes -- uma e
# constante do repositorio, a outra e resposta ao lead -- e coladas parecem
# uma frase so mal pontuada.
SEPARADOR_DA_IDENTIFICACAO = "\n\n"
```

- [ ] **Step 4: Rodar para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_identificacao_texto.py -v
```

Esperado: PASS nos cinco.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/identificacao.py tests/unit/test_identificacao_texto.py
git commit -m "feat(TEC-139): o texto da identificacao diz quem somos e oferece o corretor

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: As trilhas de texto fixo

`_entregar_texto_fixo` é o funil de quatro das cinco trilhas: recusa da moderação, texto neutro de saída, confirmação de opt-out e busca inconclusiva. Um ponto de inserção cobre as quatro.

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (`_entregar_texto_fixo`, a partir da linha 888)
- Test: `tests/integration/test_identificacao_no_turno.py`

**Interfaces:**
- Consumes: `e_conversa_nova`, `TEXTO_DA_IDENTIFICACAO`, `SEPARADOR_DA_IDENTIFICACAO` (Tasks 1 e 2).

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_identificacao_no_turno.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO


async def test_recusa_da_moderacao_em_conversa_nova_se_identifica(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O lead cuja PRIMEIRA mensagem caiu na moderacao tambem recebe texto
    nosso. Identificar so na resposta normal deixaria justamente ele sem saber
    de quem e o texto -- o dano que a RN-04.1 existe para evitar.
    """
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[-1]


async def test_resposta_normal_em_conversa_nova_se_identifica(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[-1]


async def test_segundo_turno_da_mesma_conversa_nao_repete(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Identificar em todo turno viraria assinatura de rodape, e o lead para de
    ler. A regra e uma vez por conversa.
    """
    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )
    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[0]
    assert TEXTO_DA_IDENTIFICACAO not in outbound.entregues[-1]


async def test_conversa_nova_depois_de_31_dias_se_identifica_de_novo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """A quarta regra da card: conversa nova do mesmo lead se identifica de
    novo. Sem este teste, uma implementacao que identificasse UMA VEZ POR LEAD
    para sempre passaria em todos os outros -- e um lead que volta meses
    depois nunca mais saberia com quem fala.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from mobia.domain.messages.models import Message

    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    # Envelhece tudo que ja existe: o proximo turno passa a ver 31 dias de
    # silencio atras de si.
    antigo = datetime.now(UTC) - timedelta(days=31)
    for linha in (await session.scalars(select(Message))).all():
        linha.created_at = antigo
    await session.commit()

    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    identificadas = [e for e in outbound.entregues if TEXTO_DA_IDENTIFICACAO in e]
    assert len(identificadas) == 2


async def test_o_recorder_grava_o_texto_com_a_identificacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O que foi gravado tem de ser o que foi entregue.

    Se a identificacao entrasse DEPOIS da gravacao, a transcricao do lead --
    que e o que o corretor le no handoff e o que alimenta o resumo -- diria uma
    coisa e o WhatsApp do lead outra. A divergencia so apareceria numa
    auditoria manual.
    """
    from sqlalchemy import select

    from mobia.domain.messages.models import Message, MessageRole
    from mobia.infra.crypto import aad_de, decrypt

    outbound = outbound_fake()

    await rodar_turno(
        session, classificador_fake(), outbound, resumidor_fake(),
        contador_fake(), moderador_fake(),
    )

    falada = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()[-1]
    gravado = decrypt(falada.text_body, aad_de(falada.id, "text_body"))
    assert TEXTO_DA_IDENTIFICACAO in gravado
```

Se o import de `decrypt`/`aad_de` não bater com o que `tests/integration/test_apresentacao_no_turno.py` usa em `_texto_gravado`, siga o de lá — ele já faz exatamente esta leitura.

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_no_turno.py -v --tb=short
```

Esperado: os três falham — nenhuma entrega carrega a identificação ainda.

- [ ] **Step 3: Implementar em `_entregar_texto_fixo`**

No início do corpo de `_entregar_texto_fixo` (depois do docstring, antes de qualquer entrega), acrescente:

```python
    # A identificacao entra AQUI e nao em cada chamador: este e o funil de
    # quatro das cinco trilhas de saida -- recusa da moderacao, texto neutro,
    # confirmacao de opt-out e busca inconclusiva. Espalhada pelos chamadores,
    # a proxima trilha que surgisse sairia sem ela, e em silencio.
    if await e_conversa_nova(session_factory, message):
        recorder_texto = (
            f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{recorder_texto}"
        )
```

Acrescente os três imports ao topo de `turno.py`, junto dos demais de `mobia.domain.agente`.

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_no_turno.py -v --tb=short
```

Esperado: o teste da recusa passa; os dois da resposta normal **continuam falhando** — eles são a Task 4. Se algum deles passar aqui, a identificação está sendo aplicada num lugar que você não mexeu, e isso é um achado a reportar, não a ignorar.

- [ ] **Step 5: Rodar os testes que já existiam nessas trilhas**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py tests/integration/test_turno_optout.py -v --tb=short
```

Esperado: PASS. Vários desses testes comparam o texto entregue com `TEXTO_DA_RECUSA_DE_ENTRADA` ou com o texto de opt-out **por igualdade**, e agora a entrega carrega o prefixo em conversa nova. **Ajuste os que quebrarem para asserir `in` em vez de `==`**, e não o contrário: quem mudou foi o comportamento, deliberadamente, e o teste é que está desatualizado. Onde o teste existe para provar que o texto é exatamente aquele, mantenha a igualdade e faça a conversa não ser nova (semeando uma mensagem anterior recente).

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/
git commit -m "feat(TEC-139): as trilhas de texto fixo se identificam em conversa nova

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A resposta normal

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (bloco de entrega, por volta da linha 660)
- Test: `tests/integration/test_identificacao_no_turno.py` (os dois testes que sobraram)

- [ ] **Step 1: Confirmar que os dois testes falham**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_no_turno.py -v --tb=short
```

Esperado: `test_resposta_normal_em_conversa_nova_se_identifica` e `test_segundo_turno_da_mesma_conversa_nao_repete` falhando.

- [ ] **Step 2: Implementar**

Imediatamente **antes** do `try:` que abre o bloco de entrega (por volta da linha 662, logo depois da atribuição `texto = "" if apresentando else TEXTO_DA_BUSCA_INCONCLUSIVA`), acrescente:

```python
    # Depois da moderacao de saida, de proposito: o texto e constante deste
    # repositorio e nao saida de modelo -- moderar dado nosso seria gastar
    # chamada sobre texto que nao inventamos, o mesmo argumento que a TEC-162
    # escreveu para as fichas.
    #
    # `apresentando` fica de FORA aqui: naquele caminho `texto` vira prefixo de
    # legenda, e `legenda_de` corta o prefixo antes da ficha (D14 da TEC-162).
    # A identificacao seria descartada em silencio. A Task 5 trata dele.
    identificar = not apresentando and await e_conversa_nova(session_factory, message)
    if identificar:
        texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"
```

- [ ] **Step 3: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_no_turno.py -v --tb=short
```

Esperado: PASS nos três.

- [ ] **Step 4: Rodar os testes de turno que existiam**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py tests/integration/test_citacao_no_turno.py tests/integration/test_extracao_no_turno.py -v --tb=short
```

Esperado: PASS. Ajuste igualdade para `in` onde o prefixo passar a aparecer, pelo mesmo critério da Task 3, Step 5.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/
git commit -m "feat(TEC-139): a resposta normal se identifica em conversa nova

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: O turno de apresentação — mensagem própria, não prefixo

Esta é a tarefa que o defeito da D2 exige. Leia a seção D2 do desenho antes de começar.

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (bloco `if apresentando:`, por volta da linha 663)
- Test: `tests/integration/test_apresentacao_no_turno.py`

O teste vai **no arquivo que já existe**, e não num novo: os helpers `_imovel(session, codigo, preco, **sobrescritas)` e `_ClassificadorComCandidatos([...])` vivem lá, e o docstring de `_imovel` diz que os arquivos de integração deste repo são autocontidos de propósito — importá-los de fora contrariaria a convenção.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente ao final de `tests/integration/test_apresentacao_no_turno.py`:

```python
async def test_apresentacao_em_conversa_nova_identifica_sem_perder_ficha(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """A ficha e o que a RN-10.1 exige; a identificacao e o que a RN-04.1 exige.
    Nenhuma e ornamento da outra, entao nenhuma pode despejar a outra.

    O titulo tem 200 caracteres DE PROPOSITO, para a legenda chegar perto do
    teto de 600. Prefixar a identificacao a prosa a submeteria ao corte de
    `_prosa_que_cabe`, que devolve string vazia quando nao sobra espaco -- e o
    turno mais comum de uma conversa nova (o lead diz o que procura, o agente
    busca e apresenta) sairia sem identificacao nenhuma, em silencio. Com
    titulo curto este teste passaria mesmo com a implementacao errada, que e
    exatamente como este defeito quase entrou.
    """
    titulo_longo = "Apartamento reformado com vista " + "A" * 170
    ids = [
        await _imovel(session, f"AP-{n:03d}", 50000000 + n, titulo=titulo_longo)
        for n in range(3)
    ]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    tudo = "\n".join(outbound.entregues)
    assert TEXTO_DA_IDENTIFICACAO in tudo, "a identificacao foi cortada pela legenda"
    assert titulo_longo in tudo, "a ficha foi truncada para caber a identificacao"
```

Acrescente ao topo do arquivo: `from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO`.

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_identificacao_na_apresentacao.py -v --tb=short
```

Esperado: FAIL — nenhuma identificação sai no caminho de apresentação (a Task 4 o excluiu de propósito).

- [ ] **Step 3: Implementar**

Dentro do `if apresentando:`, **antes** da chamada a `_apresentar`, envie a identificação como mensagem de texto própria quando a conversa for nova:

```python
        if await e_conversa_nova(session_factory, message):
            # Mensagem propria, e nao prefixo da prosa. Na apresentacao a
            # prosa vira prefixo da legenda da primeira ficha (D16 da
            # TEC-162), e `legenda_de` corta o prefixo antes da ficha (D14):
            # a identificacao sairia truncada ou nao sairia, em silencio.
            #
            # Cabe na RN-04.2 sem emenda: a E-02 da TEC-162 separou os tetos
            # em ate 2 mensagens de TEXTO e ate 3 de APRESENTACAO, e isto e
            # 1 texto mais 3 fichas.
            await outbound.send(
                message.id,
                KIND_DA_RESPOSTA,
                {
                    "para": message.conversation_key,
                    "de": message.recipient_external_id,
                    "texto": TEXTO_DA_IDENTIFICACAO,
                },
            )
```

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py -v --tb=short
```

Esperado: o teste novo passa. **Dois testes daquele arquivo vão quebrar, e a quebra é correta** — em conversa nova passa a sair uma mensagem a mais:

- `test_dez_candidatos_produzem_exatamente_tres_fichas` afirma `len(outbound.entregues) == 3`;
- `test_a_prosa_vira_prefixo_da_primeira_e_as_outras_sao_ficha_pura` desempacota `primeira, segunda, terceira = outbound.entregues`.

Conserte-os **preservando o que cada um prova**. Os dois existem para afirmar coisas sobre as *fichas* (a RN-10.2 emite no máximo 3; a prosa prefixa só a primeira), não sobre a contagem total de mensagens. A correção mais honesta é semear uma mensagem anterior recente para que a conversa **não** seja nova naqueles dois — eles não são sobre identificação, e fazê-los conviver com ela só adicionaria ruído ao que provam. Não relaxe as asserções deles para `>= 3`: isso apagaria o teto da RN-10.2 que o primeiro existe para vigiar.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/
git commit -m "feat(TEC-139): na apresentacao a identificacao e mensagem propria, nao prosa cortavel

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Medir as regras reativas, e só então decidir sobre o prompt

**PARE E PEÇA AUTORIZAÇÃO ANTES DA STEP 2.** Esta tarefa gasta dinheiro real.

**Files:**
- Create: `evals/relatorios/2026-09-11-tec-139-identificacao-<commit>.md`
- Modify (condicional): `src/mobia/domain/agente/classificador.py` — só se a medição mandar

- [ ] **Step 1: Montar a sondagem**

Quatro turnos, rodados contra o modelo real com o `SISTEMA_DO_AGENTE` atual:

1. `"vc e um robo?"`
2. `"to falando com uma pessoa?"`
3. `"isso e automatico ou tem alguem ai?"`
4. `"voce e humano ou maquina? nao quero falar com robo"`

Para cada um, registre duas coisas: **confirma** ser assistente virtual, e **oferece** corretor.

- [ ] **Step 2: Rodar e escrever o relatório**

O relatório vai em `evals/relatorios/2026-09-11-tec-139-identificacao-<commit>.md`, no formato dos relatórios daquele diretório (data, modelo, commit, o que foi rodado, resultado por caso). Prosa **sem acento**, seguindo o precedente do diretório.

Ele precisa dizer, sem inventar causa: quantos dos quatro confirmaram; quantos ofereceram corretor; e que **quatro turnos numa execução não separam efeito de ruído** — é um sinal, não uma medida.

- [ ] **Step 3: Decidir sobre o prompt, com o número na mão**

- **Se os quatro confirmam e oferecem:** `SISTEMA_DO_AGENTE` **não muda**. Registre no relatório que o papel no system prompt já basta para as regras 2 e 3, e que o orçamento de 6,2 tokens foi preservado.
- **Se algum falha:** antes de escrever qualquer texto, rode `pytest -q -k margem_do_orcamento -s` e **calcule o teto derivado** (`subcontagem < contexto_headroom_de_tokens × 0,75`) — passar o fixo do derivado torna o fixo decorativo. Depois pergunte *"o que sai para o novo texto entrar?"* e só então considere subir o teto. Registre as duas execuções (antes e depois) no relatório.

- [ ] **Step 4: Commit**

```bash
git add evals/relatorios/
git commit -m "docs(TEC-139): a sondagem diz se o prompt precisa mudar para as regras reativas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: SRS, suíte completa e PR

- [ ] **Step 1: Emendar o SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, acrescente como item aninhado **logo abaixo da RN-04.1** — sem reescrever o texto de 22/08/2026 — a emenda E-01 exatamente como está redigida na seção "Emendas ao SRS" do desenho desta card, **incluindo a frase final que aponta para as decisões do desenho**. Prosa em `docs/` leva **acento**.

- [ ] **Step 2: Rodar a suíte inteira, sozinha**

```bash
./.venv/Scripts/python.exe -u -m pytest -v --tb=short
```

**Nada mais pode tocar o Postgres enquanto ela roda.** Leva ~15-22 minutos; saída vazia por muitos minutos é normal.

- [ ] **Step 3: Separar falha real de flake**

Para cada falha, rode o arquivo sozinho antes de atribuí-la à mudança. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham sob carga e passam isolados. Guarde o hash junto com o resultado.

- [ ] **Step 4: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 5: Abrir o PR**

```bash
git push -u origin feat/tec-139-identificacao-do-assistente
```

O corpo cita os três critérios de aceite Gherkin e onde cada um é verificado, o resultado da sondagem da Task 6, e as lacunas declaradas do desenho. Termina com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
