# TEC-184 — Follow-up com informação nova

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o `sweep_followups` — que hoje só registra a tentativa e emite um log — escolher uma informação nova, montar a mensagem e entregá-la ao lead.

**Architecture:** A informação nova é escolhida por código, em ordem fixa (queda de preço, imóvel novo compatível, convite para agendar), a partir de duas consultas novas em `domain/followup/repositorio.py`. A composição do texto é pura e mora num módulo próprio, reusando `legenda_de`/`reais_de` da apresentação. O modelo escreve apenas a abertura, que entra como prefixo e é a primeira coisa cortada pelo teto de 600. A entrega usa a porta de saída existente, ancorada na última mensagem do lead.

**Tech Stack:** Python 3.13, SQLAlchemy async, ARQ, pytest. Sem dependência nova, sem migration.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-184-followup-com-informacao-nova-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, nenhum linter verifica.
- **Todo texto que sai para o lead é ASCII sem acento** (`Condominio`, `m2`, `nao`, `De R$ X por R$ Y`).
- **Nenhum número de preço passa pelo modelo.** D4 do desenho, e a terceira vez que o repo firma isso (TEC-265 D7, TEC-154 D8). O modelo escreve a abertura; os números saem de `reais_de`.
- **Os três gates, com o escopo exato do CI**, antes de qualquer commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter.
- **Loop rápido:** `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short` (~4s, sem Docker, sem `-n`).
- **Suíte inteira, uma vez, no fim:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`.
- **`ConnectionResetError [WinError 64]` em fixture é flake conhecido desta máquina** (~5% dos connects, em rajada). Espere e rode de novo antes de diagnosticar. **`relation ... does not exist` em muitos testes** são os bancos dos workers com o carimbo do Alembic adiantado — reporte, não conserte.
- **Mensagem de commit:** assunto em português sem acento, `tipo(TEC-184): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: O candidato carrega o id da mensagem-âncora

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py` (`Candidato`, `candidatos_a_followup`)
- Test: `tests/integration/test_sweep_followups.py`

**O que já existe nesse arquivo, e que você vai usar:** `CANAL = "whatsapp"`, `CONVERSA = "5511944443333"`, `DENTRO_DA_JANELA` (um `datetime` fixo — todo teste do arquivo fixa o relógio, e o comentário explica por quê), `_ctx()` (o contexto do job com `Settings` pinado nas três pontas) e:

```python
async def _lead(session, *, temperatura="QUENTE", calado_ha: timedelta, agora=DENTRO_DA_JANELA) -> None
```

`_lead` semeia a `LeadQualification` e **uma** mensagem de entrada com a idade pedida, e hoje **não devolve nada**. Faça-a devolver o `identificador` da mensagem que ela cria (`-> uuid.UUID`) — é o id da âncora, e sem ele o teste abaixo não tem contra o que comparar. Nenhum teste existente usa o retorno, então acrescentá-lo não quebra nada.

**Interfaces:**
- Produces: `Candidato.ancora_message_id: uuid.UUID` — campo novo, **obrigatório**, ao lado de `ancora_em`.

A âncora da cadência é o `created_at` da última fala do lead. Essa fala é uma linha de `messages`, e a D1 do desenho precisa do **id** dela para ancorar a reserva de saída. O valor sai da mesma agregação que já produz `ancora_em` — não de uma segunda consulta.

- [ ] **Step 1: Escrever o teste que falha**

```python
async def test_o_candidato_traz_o_id_da_mensagem_ancora(session) -> None:
    """D1: e este id que ancora a reserva de saida do follow-up.

    Sem ele, `outbound_dispatches` (que tem FK para `messages`) nao teria a
    que se prender, e as guardas de opt-out e silencio -- que resolvem o lead
    PELA mensagem -- ficariam sem sujeito.
    """
    antiga = await _lead(session, calado_ha=timedelta(days=2))
    recente = await _lead(session, calado_ha=timedelta(hours=3))

    (candidato,) = await candidatos_a_followup(session, agora=DENTRO_DA_JANELA)

    assert candidato.ancora_message_id == recente, (
        "a ancora e a ULTIMA fala do lead, nao a primeira -- com uma fala so "
        "este teste nao distinguiria as duas"
    )
    assert candidato.ancora_message_id != antiga
```

**Duas falas, e não uma**, de propósito: a âncora é a **última**, e um teste com uma única mensagem passaria mesmo numa implementação que pegasse a primeira. Note que `_lead` semeia a `LeadQualification` também — chamá-la duas vezes para a mesma conversa viola a PK. Extraia a semeadura da mensagem para um helper próprio, ou dê a `_lead` um parâmetro que pule a qualificação na segunda chamada; escolha e diga qual no relatório.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k candidatos_a_followup -v --tb=short`
Expected: FAIL com `AttributeError: 'Candidato' object has no attribute 'ancora_message_id'`.

- [ ] **Step 3: Implementar**

Em `Candidato`, ao lado de `ancora_em`:

```python
    # TEC-184, D1. O id da mesma fala cujo `created_at` e `ancora_em` -- sai da
    # MESMA agregacao, e nao de uma segunda consulta. E ele que ancora a
    # reserva de `outbound_dispatches` (FK para `messages`), o que da
    # idempotencia por tentativa de graca: a UNIQUE (message_id, kind) de la
    # espelha a UNIQUE (channel, conversation_key, ancora_em, tentativa) daqui.
    ancora_message_id: uuid.UUID
```

Na CTE de `candidatos_a_followup`, acrescente a coluna que carrega o id da linha de `messages` cujo `created_at` é o máximo do grupo. **Use a mesma linha que já produz `ancora_em`** — não faça um segundo `MAX` sobre outra coluna, que empataria diferente.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k followup -v --tb=short`
Expected: PASS, inclusive nos testes da TEC-183 que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/followup/repositorio.py tests/integration/
git commit -m "feat(TEC-184): o candidato a followup carrega o id da mensagem ancora

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A consulta de queda de preço

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py`
- Test: `tests/integration/test_novidade_do_followup.py` (criar — basename distinto de tudo em `tests/unit/`, senão a coleta da suíte inteira aborta)

**Interfaces:**
- Consumes: `Recomendacao` (`mobia.domain.agente.models`), `Imovel` (`mobia.domain.catalogo.models`).
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class QuedaDePreco:
      imovel_id: uuid.UUID
      preco_antes_centavos: int
      preco_agora_centavos: int

  async def queda_de_preco(
      session: AsyncSession, *, channel: str, conversation_key: str
  ) -> QuedaDePreco | None
  ```
  Devolve a **maior** queda desta conversa, ou `None`.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_detecta_a_queda_contra_o_preco_APRESENTADO(session) -> None:
    """D2: a referencia e `recomendacoes.preco_centavos` -- o numero que o lead
    VIU --, e nao o `preco_venda` de hoje dos dois lados.

    O comentario daquela coluna (TEC-275, D3) ja diz que ela e fato historico
    e continua certa depois de o preco do imovel mudar. E por isso que esta
    card nao precisa de tabela de historico.
    """
    ...  # imovel com preco_venda=59_000_000 hoje
    ...  # recomendacao para esta conversa com preco_centavos=62_000_000

    queda = await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA)

    assert queda is not None
    assert queda.preco_antes_centavos == 62_000_000
    assert queda.preco_agora_centavos == 59_000_000


async def test_aumento_de_preco_nao_e_queda(session) -> None:
    """O Gherkin da card diz "reducao"; a regra de negocio diz "mudanca". Vale
    o Gherkin: aumento nao reengaja -- e um motivo a mais para o lead sumir."""
    ...  # apresentado por 59_000_000, hoje 62_000_000
    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_preco_igual_nao_e_queda(session) -> None:
    ...  # apresentado por 59_000_000, hoje 59_000_000
    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_a_maior_queda_vence(session) -> None:
    """Uma informacao nova por mensagem (D2): com duas quedas, a maior ganha."""
    ...  # imovel A: de 62_000_000 para 59_000_000 (queda de 3.000.000)
    ...  # imovel B: de 80_000_000 para 70_000_000 (queda de 10.000.000)
    queda = await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA)
    assert queda is not None
    assert queda.preco_agora_centavos == 70_000_000


async def test_sem_recomendacao_nao_ha_referencia(session) -> None:
    """L3 do desenho: lead que nunca recebeu ficha nao tem esta fonte."""
    ...  # imovel no catalogo, nenhuma recomendacao para esta conversa
    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_recomendacao_sem_preco_e_ignorada(session) -> None:
    """`Recomendacao.preco_centavos` e nulavel: linha anterior a TEC-275 nao
    tem o numero. Sem referencia, nao ha queda -- e nao um erro."""
    ...  # recomendacao com preco_centavos=None
    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None
```

Para semear, copie o molde de `_imovel` de `tests/integration/test_fichas_do_catalogo.py` (dict de campos + `**sobrescritas`) — os arquivos de integração deste repo são autocontidos de propósito.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_novidade_do_followup.py -v --tb=short`
Expected: FAIL na coleta, com `ImportError: cannot import name 'queda_de_preco'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/followup/repositorio.py`:

```python
@dataclass(frozen=True, slots=True)
class QuedaDePreco:
    """Um imovel que o lead VIU e que hoje custa menos. TEC-184, D2.

    `preco_antes_centavos` sai de `recomendacoes.preco_centavos`, que e o
    numero que saiu na ficha -- fato historico, nao copia do preco do imovel
    (ver o comentario daquela coluna, TEC-275 D3). E e por isso que esta card
    nao precisa de tabela de historico de preco.
    """

    imovel_id: uuid.UUID
    preco_antes_centavos: int
    preco_agora_centavos: int


async def queda_de_preco(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> QuedaDePreco | None:
    """A MAIOR queda de preco entre os imoveis ja apresentados a esta conversa.

    **So queda.** O Gherkin da card diz "reducao" onde a regra de negocio diz
    "mudanca", e a divergencia foi decidida a favor do Gherkin: aumento nao
    reengaja, e a historia pede que a mensagem traga algo util.

    `None` quando nao ha nenhuma -- inclusive quando o lead nunca recebeu
    ficha (L3) ou quando a linha e anterior a TEC-275 e nao tem preco gravado.

    A maior, e nao qualquer uma: a D2 manda uma informacao nova por mensagem,
    e entre duas quedas a que mais reengaja e a maior.
    """
    resultado = await session.execute(
        select(
            Recomendacao.imovel_id,
            Recomendacao.preco_centavos,
            Imovel.preco_venda,
        )
        .join(Imovel, Imovel.id == Recomendacao.imovel_id)
        .where(
            Recomendacao.channel == channel,
            Recomendacao.conversation_key == conversation_key,
            Recomendacao.preco_centavos.is_not(None),
            Imovel.preco_venda.is_not(None),
            Imovel.preco_venda < Recomendacao.preco_centavos,
        )
        .order_by((Recomendacao.preco_centavos - Imovel.preco_venda).desc())
        .limit(1)
    )
    linha = resultado.first()
    if linha is None:
        return None
    return QuedaDePreco(
        imovel_id=linha.imovel_id,
        preco_antes_centavos=linha.preco_centavos,
        preco_agora_centavos=linha.preco_venda,
    )
```

Acrescente os imports de `Recomendacao` e `Imovel` no topo do arquivo.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_novidade_do_followup.py -v --tb=short`
Expected: PASS nos seis.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/followup/repositorio.py tests/integration/test_novidade_do_followup.py
git commit -m "feat(TEC-184): a queda de preco sai do preco apresentado, sem tabela de historico

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A consulta de imóvel novo compatível

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py`
- Test: `tests/integration/test_novidade_do_followup.py`

**Interfaces:**
- Consumes: `LeadQualification` (`mobia.domain.context.models`), `Imovel`, `Recomendacao`.
- Produces:
  ```python
  async def imovel_novo_compativel(
      session: AsyncSession, *, channel: str, conversation_key: str, desde: datetime
  ) -> uuid.UUID | None
  ```

Os critérios do lead estão em `lead_qualification`: `regiao`, `tipo_imovel`, `faixa_preco_min_centavos`, `faixa_preco_max_centavos`, `quartos`, `vagas` — todos nuláveis, porque qualificação é progressiva.

**Não reuse `buscar` / `buscar_com_relaxamento`.** Aquela busca é híbrida (vetorial + filtro), relaxa critério (RN-09.3) e ordena por relevância — três comportamentos que aqui seriam errados: o follow-up não pode relaxar o que o lead pediu e apresentar como se atendesse, e não há consulta em texto livre para vetorizar. O filtro aqui é literal e a ordem é por chegada.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_imovel_criado_depois_da_ancora_e_novidade(session) -> None:
    ...  # lead_qualification com regiao="Centro", quartos=3
    ...  # imovel no Centro com 3 quartos, created_at DEPOIS da ancora
    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ancora
    )
    assert achado == id_do_imovel


async def test_imovel_anterior_a_ancora_nao_e_novidade(session) -> None:
    """"Novo" e relativo a ultima fala do lead: o que ja existia quando ele
    falou nao e novidade para ele."""
    ...  # mesmo imovel compativel, created_at ANTES da ancora
    assert await imovel_novo_compativel(...) is None


async def test_imovel_ja_apresentado_nao_e_novidade(session) -> None:
    """Reapresentar o que o lead ja viu e exatamente o "robo carente" que a
    historia da card quer evitar."""
    ...  # imovel compativel e novo, MAS com Recomendacao para esta conversa
    assert await imovel_novo_compativel(...) is None


async def test_imovel_fora_dos_criterios_nao_e_novidade(session) -> None:
    ...  # lead quer 3 quartos no Centro; imovel novo tem 1 quarto
    assert await imovel_novo_compativel(...) is None


async def test_lead_sem_criterio_nenhum_aceita_qualquer_imovel_novo(session) -> None:
    """Todo criterio e nulavel, e nulo significa "o lead nao disse" -- nao
    "nenhum imovel serve". Filtrar por campo ausente devolveria sempre vazio e
    mataria a fonte para quem mal comecou a conversar."""
    ...  # lead_qualification com todos os criterios None
    assert await imovel_novo_compativel(...) == id_do_imovel_novo


async def test_imovel_indisponivel_nao_e_novidade(session) -> None:
    ...  # imovel novo e compativel, status="VENDIDO"
    assert await imovel_novo_compativel(...) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_novidade_do_followup.py -k novo -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'imovel_novo_compativel'`.

- [ ] **Step 3: Implementar**

```python
async def imovel_novo_compativel(
    session: AsyncSession, *, channel: str, conversation_key: str, desde: datetime
) -> uuid.UUID | None:
    """Um imovel que entrou no catalogo depois da ultima fala do lead, que
    casa os criterios que ele declarou, e que ele ainda nao viu. TEC-184, D2.

    **Filtro literal, e nao `buscar`.** A busca do agente e hibrida, relaxa
    criterio (RN-09.3) e ordena por relevancia; nenhum dos tres serve aqui. Um
    follow-up que relaxasse apresentaria como novidade um imovel que o lead
    justamente NAO pediu, e nao ha consulta em texto livre para vetorizar.

    **Criterio nulo nao filtra.** Nulo significa "o lead nao disse", nunca
    "nenhum imovel serve": filtrar por campo ausente devolveria sempre vazio e
    mataria esta fonte para quem mal comecou a conversar.

    **O ja apresentado sai pela UNIQUE de `recomendacoes`.** Reapresentar o
    que o lead ja viu e o "robo carente" que a historia da card nomeia.
    """
    estado = await session.get(LeadQualification, (channel, conversation_key))

    ja_vistos = select(Recomendacao.imovel_id).where(
        Recomendacao.channel == channel,
        Recomendacao.conversation_key == conversation_key,
    )

    consulta = select(Imovel.id).where(
        Imovel.created_at > desde,
        Imovel.status == StatusImovel.DISPONIVEL.value,
        Imovel.id.not_in(ja_vistos),
    )

    if estado is not None:
        if estado.regiao is not None:
            consulta = consulta.where(Imovel.bairro_busca == dobrar(estado.regiao))
        if estado.tipo_imovel is not None:
            consulta = consulta.where(Imovel.tipo == estado.tipo_imovel)
        if estado.quartos is not None:
            consulta = consulta.where(Imovel.quartos >= estado.quartos)
        if estado.vagas is not None:
            consulta = consulta.where(Imovel.vagas >= estado.vagas)
        if estado.faixa_preco_max_centavos is not None:
            consulta = consulta.where(Imovel.preco_venda <= estado.faixa_preco_max_centavos)
        if estado.faixa_preco_min_centavos is not None:
            consulta = consulta.where(Imovel.preco_venda >= estado.faixa_preco_min_centavos)

    # O mais recente primeiro: entre dois novos, a novidade e o que chegou
    # depois. `LIMIT 1` porque a D2 manda uma informacao nova por mensagem.
    return await session.scalar(consulta.order_by(Imovel.created_at.desc()).limit(1))
```

`dobrar` vem de `mobia.domain.texto` — é a mesma dobra (caixa e acento) que `Imovel.bairro_busca` guarda, e comparar um lado dobrado contra o outro cru é o defeito que a TEC-160 pagou com um Critical. Acrescente os imports de `LeadQualification`, `StatusImovel` e `dobrar`.

**Atenção ao `tipo_imovel`:** o vocabulário do agente e o do catálogo são dois `StrEnum` distintos (ver a docstring de `TipoImovel` em `domain/catalogo/enums.py`). Confira se os valores coincidem para os membros que interessam; se houver divergência, converta por nome e **escreva o porquê num comentário**, em vez de comparar as strings cruas e torcer.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_novidade_do_followup.py -v --tb=short`
Expected: PASS nos doze (seis da Task 2 e seis desta).

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/followup/repositorio.py tests/integration/test_novidade_do_followup.py
git commit -m "feat(TEC-184): o imovel novo compativel sai de filtro literal, sem relaxamento

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A escolha da novidade e a montagem do texto

**Files:**
- Create: `src/mobia/domain/followup/mensagem.py`
- Test: `tests/unit/test_mensagem_do_followup.py`

**Interfaces:**
- Consumes: `Ficha`, `legenda_de`, `reais_de` (`mobia.domain.agente.apresentacao`); `QuedaDePreco` (Task 2).
- Produces:
  ```python
  CONVITE_PARA_AGENDAR: str
  def linha_da_queda(queda: QuedaDePreco) -> str
  def texto_do_followup(
      *, ficha: Ficha | None, queda: QuedaDePreco | None, prefixo: str | None = None
  ) -> str
  ```

**Módulo puro, sem I/O** — como `cadencia.py`, `apresentacao.py` e `qualificacao.py`. É o que deixa a regra ser testada em `tests/unit/`, sem Postgres de pé. Quem consulta o banco e decide é o job (Task 6).

A ordem de precedência (queda > imóvel novo > convite) mora **aqui**, e não no job: é regra, não orquestração.

- [ ] **Step 1: Escrever os testes que falham**

```python
import uuid

from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.followup.mensagem import (
    CONVITE_PARA_AGENDAR,
    linha_da_queda,
    texto_do_followup,
)
from mobia.domain.followup.repositorio import QuedaDePreco

FICHA = Ficha(
    id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=51646430,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial="churrasqueira e mobiliado",
    foto=None,
)

QUEDA = QuedaDePreco(
    imovel_id=FICHA.id,
    preco_antes_centavos=62_000_000,
    preco_agora_centavos=59_000_000,
)


def test_a_linha_da_queda_traz_os_dois_precos_truncados_para_baixo() -> None:
    """`reais_de` trunca dos dois lados, pela razao que ela ja documenta:
    arredondar para cima cota ao lead um preco acima do real."""
    assert linha_da_queda(QUEDA) == "De R$ 620.000 por R$ 590.000"


def test_a_queda_vence_o_imovel_novo() -> None:
    """D2: a queda e sobre algo em que o lead JA demonstrou interesse; um
    anuncio que ele nunca viu e aposta mais fraca."""
    texto = texto_do_followup(ficha=FICHA, queda=QUEDA)
    assert "De R$ 620.000 por R$ 590.000" in texto
    assert CONVITE_PARA_AGENDAR not in texto


def test_o_imovel_novo_vence_o_convite() -> None:
    texto = texto_do_followup(ficha=FICHA, queda=None)
    assert "Apartamento em Lagoa da Conceicao" in texto
    assert CONVITE_PARA_AGENDAR not in texto


def test_sem_novidade_sobra_o_convite() -> None:
    """Cenario 3 do Gherkin, e a razao de a mensagem vazia ser IMPOSSIVEL e
    nao bloqueada (D6): o convite sempre existe."""
    assert texto_do_followup(ficha=None, queda=None) == CONVITE_PARA_AGENDAR


def test_o_convite_nao_e_uma_saudacao_sem_conteudo() -> None:
    """A card proibe "oi, tudo bem?" solto. O convite tem de PEDIR algo."""
    assert "?" in CONVITE_PARA_AGENDAR
    assert "visita" in CONVITE_PARA_AGENDAR.lower()


def test_o_prefixo_do_modelo_entra_antes_e_cede_primeiro() -> None:
    """Mesma prioridade da apresentacao (D14 da TEC-162): corta-se a prosa,
    nunca o fato."""
    texto = texto_do_followup(ficha=FICHA, queda=None, prefixo="palavra " * 200)
    assert len(texto) <= 600
    assert "Apartamento em Lagoa da Conceicao" in texto
    assert "Condominio R$ 550" in texto


def test_a_ficha_da_queda_e_a_do_imovel_que_caiu() -> None:
    """Passar uma ficha de OUTRO imovel junto com a queda seria mostrar o
    preco de um e a ficha de outro -- o lead nao tem como perceber."""
    outra = Ficha(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        titulo="Casa no Centro",
        bairro="Centro",
        preco_centavos=59_000_000,
        quartos=3,
        vagas=1,
        area_util_m2=90,
        condominio_centavos=None,
        diferencial=None,
        foto=None,
    )
    with pytest.raises(ValueError):
        texto_do_followup(ficha=outra, queda=QUEDA)


def test_tudo_que_sai_para_o_lead_e_ascii() -> None:
    """Acento aqui chega ao WhatsApp do lead."""
    for texto in (
        CONVITE_PARA_AGENDAR,
        linha_da_queda(QUEDA),
        texto_do_followup(ficha=FICHA, queda=None),
    ):
        assert texto.isascii(), texto
```

Acrescente `import pytest` ao topo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_mensagem_do_followup.py -v`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.followup.mensagem'`.

- [ ] **Step 3: Implementar**

```python
"""O texto do follow-up: qual novidade entra, e como ela e escrita.

TEC-184, RN-13.2. Puro de proposito -- sem I/O, sem banco, sem chamada ao
modelo --, como `cadencia.py` e `apresentacao.py`. Quem consulta e decide
gravar e o job; aqui so se monta o texto.

**A ordem de precedencia mora aqui, e nao no job**: queda de preco vence
imovel novo, que vence o convite. E regra da card, nao orquestracao, e no job
ela ficaria misturada com guardas, laco e entrega.

Todo texto daqui sai para o lead e e ASCII sem acento, como em
`apresentacao.py`.
"""

from mobia.domain.agente.apresentacao import Ficha, legenda_de, reais_de
from mobia.domain.followup.repositorio import QuedaDePreco

# O fallback da card quando nao ha novidade nenhuma. **Nao e saudacao**: a
# RN-13.2 proibe "oi, tudo bem?" solto, e o que separa um do outro e pedir
# algo concreto. A regra de negocio oferece "ou tarefa para o corretor" como
# alternativa, mas quem notifica corretor e a TEC-280/281, ainda abertas --
# entao este e o unico caminho vivo (L2 do desenho).
CONVITE_PARA_AGENDAR = (
    "Quer agendar uma visita para conhecer algum dos imoveis que vimos?"
)


def linha_da_queda(queda: QuedaDePreco) -> str:
    """`De R$ 620.000 por R$ 590.000`.

    Os dois lados por `reais_de`, que trunca para BAIXO -- a mesma razao que
    ela ja documenta, e que aqui vale duas vezes: arredondar o preco NOVO para
    cima cota ao lead acima do real, e arredondar o ANTIGO para baixo encolhe
    a queda que a mensagem existe para anunciar.
    """
    return (
        f"De {reais_de(queda.preco_antes_centavos)} "
        f"por {reais_de(queda.preco_agora_centavos)}"
    )


def texto_do_followup(
    *, ficha: Ficha | None, queda: QuedaDePreco | None, prefixo: str | None = None
) -> str:
    """A mensagem inteira: a novidade de maior precedencia, com a prosa na frente.

    **Nunca devolve string vazia.** Sem ficha e sem queda sobra o convite, e e
    isso que torna a "mensagem vazia" da card IMPOSSIVEL em vez de bloqueada
    (D6). Nao ha envio a barrar porque nao ha como produzir mensagem sem
    conteudo.

    **Com `queda`, a `ficha` tem de ser a do imovel que caiu.** Mostrar o
    preco de um imovel com a ficha de outro e um erro que o lead nao tem como
    perceber, entao ele levanta aqui em vez de sair pelo WhatsApp.
    """
    if queda is not None:
        if ficha is None or ficha.id != queda.imovel_id:
            raise ValueError("a ficha da queda tem de ser a do imovel que caiu")
        corpo = legenda_de(ficha)
        return _com_prefixo(f"{corpo}\n{linha_da_queda(queda)}", prefixo)
    if ficha is not None:
        return _com_prefixo(legenda_de(ficha), prefixo)
    return _com_prefixo(CONVITE_PARA_AGENDAR, prefixo)
```

**`_com_prefixo` não é escrita do zero.** `apresentacao.legenda_de` já resolve exatamente este problema — prefixo opcional, separador, teto de 600, corte na última fronteira de palavra — em `_prosa_que_cabe`. Leia aquela função e **reuse-a** em vez de escrever uma segunda cópia da mesma aritmética; se ela for privada do módulo, promova-a a pública no mesmo commit, com um comentário dizendo que agora tem dois consumidores. Duas cópias da regra dos 600 é exatamente a segunda fonte que a TEC-146 gastou uma card consertando.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`
Expected: PASS, incluindo os testes de `test_apresentacao.py` se você tocou `_prosa_que_cabe`.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/followup/mensagem.py tests/unit/test_mensagem_do_followup.py src/mobia/domain/agente/apresentacao.py
git commit -m "feat(TEC-184): a novidade do followup e escolhida e escrita num modulo puro

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A abertura escrita pelo modelo

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` **ou** criar `src/mobia/domain/followup/prosa.py` — **a decisão é sua, e o Step 1 é tomá-la**
- Test: `tests/unit/test_prosa_do_followup.py`

**Interfaces:**
- Consumes: `divergencias_de` (`mobia.domain.agente.citacao`); `ler_resumo` (`mobia.domain.context.repositorio`).
- Produces:
  ```python
  SISTEMA_DO_FOLLOWUP: str
  MAX_TOKENS_DA_ABERTURA: int
  async def redigir_abertura(<assinatura que a Step 1 fixar>) -> str | None
  ```
  Devolve `None` quando a prosa não deve ser usada (saudação vazia, citação divergente, falha da chamada). O chamador trata `None` como "sem prefixo" — **nunca** como erro.

- [ ] **Step 1: Decidir onde a chamada mora, e registrar a decisão**

Leia `_chamar` em `classificador.py` (por volta da linha 859) e o tipo `ContextoMontado` que ele recebe. Depois escolha:

- **Reusar `_chamar`** — se ele puder receber o que o follow-up tem (um resumo de conversa e um texto curto) sem que você precise **fabricar um `ContextoMontado` falso** só para satisfazer a assinatura.
- **Chamada própria, mais enxuta** — se reusar exigir inventar um contexto de turno que não existe.

**O critério é esse, e não o gosto:** fabricar uma estrutura vazia para caber numa assinatura cria um objeto que mente sobre o que aconteceu, e é a próxima pessoa que paga. Escreva a decisão e a razão no seu relatório e num comentário no código.

Seja qual for o lugar, o prompt não é medido contra o teto fixo do orçamento (aquele teste mede `SISTEMA_DO_AGENTE`), mas **custa contexto por follow-up enviado** — mantenha-o curto.

- [ ] **Step 2: Escrever os testes que falham**

Todos com dublê do provedor; **nenhum toca a rede**.

```python
def test_o_prompt_proibe_numero_e_saudacao_vazia() -> None:
    """Os dois riscos desta chamada, e os dois estao no prompt de proposito:
    numero inventado com cara de fato, e "oi, tudo bem?" que a RN-13.2 proibe.
    """
    baixo = SISTEMA_DO_FOLLOWUP.lower()
    assert "preco" in baixo or "numero" in baixo
    assert "saudacao" in baixo or "oi, tudo bem" in baixo


async def test_prosa_que_e_so_saudacao_vira_none() -> None:
    """D6: o que a validacao descarta e a PROSA, nunca o envio -- o fato sai
    sozinho e a mensagem nunca fica vazia."""
    assert await redigir_abertura(...) is None  # dble devolve "Oi, tudo bem?"


async def test_prosa_que_cita_imovel_de_fora_vira_none() -> None:
    """D5: a guarda de citacao da TEC-161 passa a valer aqui. O imovel da
    novidade existe por construcao; o que sobra e o modelo inventar um
    segundo na abertura."""
    assert await redigir_abertura(...) is None  # dble cita um imovel inexistente


async def test_falha_da_chamada_vira_none_e_nao_excecao() -> None:
    """A prosa e ornamento: uma falha nela nao pode custar ao lead o follow-up
    inteiro. E a mesma postura da porta de busca, que devolve `erro` no
    tool_result em vez de derrubar o turno."""
    assert await redigir_abertura(...) is None  # dble levanta


async def test_prosa_boa_volta_inteira() -> None:
    ...  # dble devolve "Vi que voce procurava 3 quartos no Centro."
    assert await redigir_abertura(...) == "Vi que voce procurava 3 quartos no Centro."
```

Complete as chamadas com a assinatura que a Step 1 fixou.

- [ ] **Step 3: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_prosa_do_followup.py -v`
Expected: FAIL na coleta (`ImportError`/`ModuleNotFoundError`).

- [ ] **Step 4: Implementar**

O prompt, curto e sem acento:

```python
SISTEMA_DO_FOLLOWUP = (
    "Voce e o assistente virtual de uma imobiliaria brasileira. Um lead parou "
    "de responder e vamos retomar o contato com uma novidade que JA foi "
    "escolhida -- ela vem pronta depois da sua frase, e voce nao a escreve.\n\n"
    "Escreva UMA frase curta, em portugues do Brasil, em tom de conversa, "
    "ligando o que o lead procurava a essa novidade. Nada de saudacao sem "
    "conteudo: 'oi, tudo bem?' e variacoes estao proibidas.\n\n"
    "Nao escreva preco, porcentagem nem qualquer numero: eles saem prontos "
    "abaixo da sua frase. Nao cite imovel que nao esteja no contexto. Nao "
    "prometa nada e nao negocie valor."
)

# Uma frase. O teto existe para que uma resposta longa nao pague tokens que a
# regra dos 600 caracteres vai cortar de qualquer jeito.
MAX_TOKENS_DA_ABERTURA = 120
```

A função devolve `None` em quatro casos, e o chamador trata todos como "sem prefixo": chamada falhou, texto vazio, texto que é só saudação, ou `divergencias_de` acusou citação de imóvel que não está no contexto.

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`
Expected: PASS.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/ tests/unit/test_prosa_do_followup.py
git commit -m "feat(TEC-184): o modelo escreve so a abertura, e a prosa ruim vira ausencia de prosa

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: O sweep monta e entrega

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py`
- Modify: `src/mobia/domain/outbound/kinds.py`
- Test: `tests/integration/test_sweep_followups.py` — use `_lead`, `_ctx()`, `DENTRO_DA_JANELA`, `CANAL` e `CONVERSA`, que já existem ali, e o `outbound_fake` de `tests/conftest.py` (`outbound.entregues` é `list[str]` com o texto de cada mensagem entregue). Os testes deste arquivo hoje não passam porta de saída ao job: acrescentar uma exige dar ao `_ctx()` a chave que o job vai ler — decida o nome, mantenha o default de produção intacto, e diga no relatório o que escolheu.

**Interfaces:**
- Consumes: tudo das Tasks 1-5.
- Produces: `KIND_DO_FOLLOWUP(n: int) -> str` em `kinds.py`, devolvendo `followup_1`..`followup_4`.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_o_followup_sai_pela_porta_ancorado_na_ultima_fala(session, ...) -> None:
    """D1: `message_id` e o da mensagem-ancora, `kind` e `followup_<n>`."""
    ...
    assert outbound.entregues, "nada saiu -- o teste nao afirmaria nada"


async def test_a_segunda_varredura_nao_reenvia_a_mesma_tentativa(session, ...) -> None:
    """A UNIQUE (message_id, kind) absorve. E o mesmo mecanismo que ja protege
    a resposta normal, herdado sem codigo novo."""
    ...  # roda o sweep duas vezes com o mesmo `agora`
    assert len(outbound.entregues) == 1


async def test_fora_da_janela_de_24h_vira_log_e_nao_derruba_o_lote(session, ...) -> None:
    """L1: hoje so a tentativa de 2h do QUENTE chega. As outras oito posicoes
    batem em `EnvioForaDaJanela`, e a varredura tem de seguir para o proximo
    candidato -- um lead fora da janela nao pode custar o follow-up dos
    outros."""
    ...  # dble que levanta EnvioForaDaJanela para o primeiro candidato
    assert len(outbound.entregues) == 1  # o segundo candidato saiu


async def test_a_linha_de_followups_permanece_quando_o_envio_e_recusado(
    session, ...
) -> None:
    """L1, a parte que custa: a tentativa e CONSUMIDA. `followups` e
    append-only e a linha e gravada antes do envio, entao ela nao volta
    quando a TEC-186 entrar. Este teste existe para que isso seja uma decisao
    visivel e nao um efeito colateral."""
    ...
    assert await _linhas_de_followup(session) == 1


async def test_o_teto_de_envios_por_execucao_corta_o_excedente(session, ...) -> None:
    """D7: com 26 candidatos devidos, 25 saem e 1 fica -- e ele continua
    devido na varredura seguinte, porque a cadencia e ancorada e nao
    encadeada."""
    ...
    assert len(outbound.entregues) == MAXIMO_DE_ENVIOS_POR_EXECUCAO
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k sweep_followup -v --tb=short`
Expected: FAIL — nada é entregue hoje.

- [ ] **Step 3: Implementar**

Em `kinds.py`:

```python
# TEC-184. Um kind por tentativa, e nao um so repetido: a UNIQUE
# (message_id, kind) de `outbound_dispatches` e o que impede duas varreduras
# concorrentes de mandarem a mesma tentativa duas vezes, e com um kind unico
# a SEGUNDA tentativa do mesmo lead seria absorvida como se fosse repeticao
# da primeira. O teto e quatro porque a cadencia mais longa (QUENTE) tem
# quatro posicoes -- ver `CADENCIA` em `domain/followup/cadencia.py`.
def KIND_DO_FOLLOWUP(tentativa: int) -> str:
    return f"followup_{tentativa}"
```

No job, dentro do laço e **depois** de todas as guardas existentes (a ordem delas é proposital e está documentada no docstring — não a reordene), acrescente: consultar a novidade, redigir a abertura, montar o texto e enviar. O teto:

```python
# TEC-184, D7. Nao e medicao -- a chamada que ele limita nao existia quando o
# numero foi escolhido. E um limite derivado do `job_timeout = 240 s`: supondo
# ~4 s de pior caso por follow-up (uma chamada de prosa com `max_tokens`
# pequeno, mais o POST para a Meta), 25 envios sao ~100 s, menos da metade do
# orcamento. Quem medir o custo real deve corrigir este numero -- e a direcao
# certa e medir, nao subir por intuicao quando a varredura parecer lenta.
# Com 25 por execucao e uma varredura a cada 5 minutos, a vazao e de 300
# follow-ups por hora, muito acima de qualquer acumulo plausivel.
MAXIMO_DE_ENVIOS_POR_EXECUCAO = 25
```

O `EnvioForaDaJanela` é capturado **por candidato**, vira `log.info` e o laço segue: um lead fora da janela não pode custar o follow-up dos outros. A linha de `followups` **permanece** — não a desfaça, e escreva no comentário que a tentativa é consumida (é a L1, e é decisão, não descuido).

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k followup -v --tb=short`
Expected: PASS, inclusive nos testes da TEC-183 que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/workers/jobs/sweep_followups.py src/mobia/domain/outbound/kinds.py tests/integration/
git commit -m "feat(TEC-184): a varredura monta o followup e entrega pela porta de saida

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: A emenda ao SRS e o fecho

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: Escrever a emenda**

A RN-13.2 está na **linha 368** e **não tem emenda nenhuma** — a desta card é a **E-01**. Entra como item aninhado abaixo dela, sem reescrever o texto de 22/08/2026; o padrão está na RN-13.3 (linha 370). O texto está pronto na seção "Emendas ao SRS" do desenho — copie de lá.

Se houver uma tabela-índice de emendas no topo do SRS, acrescente a linha correspondente, no mesmo formato das vizinhas.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`. `VIZINHO` é a categoria que pega o defeito: comentário que ninguém editou, dentro de um `def`/`class` cujo código mudou. Confira em especial o docstring de `sweep_followups`, que hoje afirma **"Nada é enviado ao lead"** e aponta esta card como quem fecha isso — essa frase tem de deixar de existir. Confira também o docstring de `FollowUp` (`domain/followup/models.py`) e o de `_prosa_que_cabe`, se você o promoveu na Task 4. Relate o que conferiu e o que decidiu sobre cada um.

- [ ] **Step 3: Os três gates e a suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta; guarde o hash junto com o resultado. Se **falhar**, repita sobre a mesma árvore antes de culpar a mudança.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-184): a emenda E-01 da RN-13.2 fixa a ordem da novidade e a mensagem vazia impossivel

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite

| Cenário do Gherkin | Onde é exercitado |
|---|---|
| 1 — novo imóvel compatível vira a informação nova | Task 3 (`test_imovel_criado_depois_da_ancora_e_novidade`); Task 4 (`test_o_imovel_novo_vence_o_convite`) |
| 1 — o imóvel citado existe no catálogo | Por construção (o código o escolhe do banco) + Task 5 (guarda de citação na prosa) |
| 2 — mudança de preço com o valor do banco | Task 2 (`test_detecta_a_queda_contra_o_preco_APRESENTADO`); Task 4 (`test_a_linha_da_queda_...`) |
| 3 — sem novidade, convida para agendar | Task 4 (`test_sem_novidade_sobra_o_convite`, `test_o_convite_nao_e_uma_saudacao_sem_conteudo`) |
| 4 — mensagem vazia é bloqueada | **Divergência declarada.** A mensagem vazia é impossível, não bloqueada (D6): o convite sempre existe. O que a validação descarta é a prosa — Task 5, `test_prosa_que_e_so_saudacao_vira_none` |

**Limite de 600 caracteres:** Task 4, `test_o_prefixo_do_modelo_entra_antes_e_cede_primeiro`.

**Sem exercício, e declarado:** "tarefa para o corretor" como alternativa ao convite (L2 — quem notifica corretor é a TEC-280/281, abertas).
