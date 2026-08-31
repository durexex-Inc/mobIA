# TEC-257 — Memória do que já foi perguntado: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O modelo declara sobre quais campos perguntou; o que ele perguntou e o lead não respondeu fica marcado no estado da conversa, e o prompt instrui o agente a não reperguntar.

**Architecture:** Um campo novo no `SCHEMA_DA_RESPOSTA` (`perguntou`, lista de strings) chega em `RespostaDoAgente`. Uma função pura filtra esses nomes contra `fields(Extracao)`, subtrai o que já está preenchido, e loga o que descartou. `gravar_estado` grava o resultado numa coluna nova de `lead_qualification`, unindo com o que já havia **dentro do SQL**. `_texto_do_estado` mostra a marca no bloco de estado que já existe, e uma cláusula reescrita do `SISTEMA_DO_AGENTE` manda o agente respeitá-la. O runner do eval espelha pela mesma função.

**Tech Stack:** Python 3.13, SQLAlchemy async + Postgres, Alembic, pydantic-settings, structlog, pytest, Anthropic SDK com `output_config` de json_schema estrito.

**Spec:** [docs/superpowers/specs/2026-08-31-tec-257-memoria-do-que-ja-foi-perguntado-design.md](2026-08-31-tec-257-memoria-do-que-ja-foi-perguntado-design.md) — na pasta irmã `specs/`. Leia antes de começar: as decisões D0 a D10 são o porquê de tudo abaixo, e várias das escolhas parecem arbitrárias sem elas.

## Global Constraints

- **Orçamento de prompt.** `test_a_margem_do_orcamento_do_prompt_e_deliberada` (`tests/unit/test_config.py`) trava a subcontagem contra um teto **fixo escrito à mão**, hoje 627. Esta card o move para **655** e `contexto_headroom_de_tokens` de **850 para 880**. Nenhum outro número desta conta é escrito à mão em lugar nenhum — todos são derivados e saem impressos por `python -m pytest -q -k margem_do_orcamento -s`. **Nunca transcreva um valor derivado para um comentário** (TEC-243: envelheceu quatro vezes em dois dias).
- **Nada de texto do lead em log.** Nem em `log.*`, nem interpolado em mensagem de exceção. Vale também para a resposta do agente. A única exceção desta card está na Task 3 e é filtrada por padrão seguro.
- **`NULL` e `{}` não são sinônimos** na coluna nova: `NULL` é *"linha anterior à card"*, `{}` é *"marcava e não havia nada"*. Nenhum código pode tratar os dois como a mesma coisa.
- **Uma regra, uma casa.** `campos_a_marcar` é chamada por produção **e** pelo runner do eval, como `campos_a_gravar`. Nunca duplique a lógica.
- **Comentários e docstrings em português sem acento** (padrão do código-fonte do repo); prosa em Markdown com acento.
- **Commits:** mensagem em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Suíte completa:** `python -m pytest -q`. Os testes de integração exigem Postgres — `docker-compose up -d` antes.

---

### Task 1: O campo `perguntou` no schema, e o orçamento que paga por ele

O campo e as duas subidas de teto vão no **mesmo commit** de propósito: acrescentar o campo sozinho deixa dois testes de orçamento vermelhos, e subir os tetos sozinho cria folga que nada consome e que o próximo leitor não sabe explicar.

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py` (dataclass `RespostaDoAgente`, ~linha 269)
- Modify: `src/mobia/domain/agente/classificador.py` (`SCHEMA_DA_RESPOSTA` ~linha 108, `_ORDEM_DOS_CAMPOS` ~linha 190, o corpo de `classificar` ~linha 468)
- Modify: `src/mobia/app/config.py` (`contexto_headroom_de_tokens`, linha 176, e o comentário acima dela)
- Modify: `tests/unit/test_config.py` (o teto fixo de 627, ~linha 320)
- Test: `tests/unit/test_classificador.py`

**Interfaces:**
- Produces: `RespostaDoAgente.perguntou: tuple[str, ...]` (default `()`), consumido pelas Tasks 4 e 6. `_perguntou(bruto: Any) -> tuple[str, ...]` é privado do módulo e não sai dele.

**Onde `perguntou` entra na ordem, e por que isso não é livre.** `_ORDEM_DOS_CAMPOS` existe porque o modelo preenche o objeto na ordem declarada, e a TEC-244 mostrou que mudar essa ordem muda a geração num caminho pago. `perguntou` vai **depois** de `resposta`: assim o modelo relata o que a resposta que ele acabou de escrever pergunta. Antes de `resposta`, ele se comprometeria com uma lista e depois teria de escrever um texto que a honrasse — que é um pedido diferente, mais difícil, e que ninguém mediu.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_classificador.py`, junto dos outros testes de parse:

```python
def test_perguntou_chega_como_tupla_de_nomes():
    """O campo novo da TEC-257: o modelo diz sobre o que perguntou.

    Nao filtra nada aqui -- filtrar e a regra de `campos_a_marcar`, que
    precisa logar o que descartou. Aqui so a forma.
    """
    assert _perguntou(["regiao", "vagas"]) == ("regiao", "vagas")


def test_perguntou_tolera_forma_errada_sem_levantar():
    """Nome inventado nao e recusado aqui, e nao-string e descartado.

    Recusar a resposta inteira por causa deste campo trocaria um turno
    respondido por um turno perdido -- o campo e diagnostico do proprio
    modelo, nao dado do lead.
    """
    assert _perguntou(None) == ()
    assert _perguntou("regiao") == ()
    assert _perguntou(["regiao", 7, None, "bairro"]) == ("regiao", "bairro")


def test_a_ordem_dos_campos_poe_perguntou_depois_de_resposta():
    """TEC-244: a ordem do schema e a ordem de geracao, e ela e deliberada.

    `perguntou` relata o que a resposta ja escrita pergunta. Antes de
    `resposta`, seria um compromisso a honrar -- pedido diferente, nunca
    medido.
    """
    ordem = list(SCHEMA_DA_RESPOSTA["properties"])
    assert ordem.index("perguntou") > ordem.index("resposta")
    assert SCHEMA_DA_RESPOSTA["required"] == ordem
```

Importe `_perguntou` e `SCHEMA_DA_RESPOSTA` de `mobia.domain.agente.classificador` no topo do arquivo, junto dos imports que já existem.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_classificador.py -q -k perguntou`
Expected: FAIL — `ImportError: cannot import name '_perguntou'`

- [ ] **Step 3: Acrescentar o campo ao schema e à ordem**

Em `classificador.py`, dentro de `SCHEMA_DA_RESPOSTA["properties"]`, depois de `"resposta"`:

```python
        # TEC-257. Lista de strings livre, e nao enum dos nove campos: o
        # enum impede o modelo inventar nome, e custaria +56,0 tokens contra
        # +18,5 desta forma. Nome inventado nao casa em `campos_a_marcar`, e
        # e descartado -- marca de MENOS, que e o erro seguro quando a marca
        # e permanente. Marcar de mais mataria o campo em silencio.
        #
        # Sem `description`: nenhum campo deste schema tem, e uma aqui
        # custaria mais que o campo inteiro. O modelo infere o vocabulario de
        # `extracao`, no mesmo objeto, que carrega exatamente os nove nomes.
        "perguntou": {"type": "array", "items": {"type": "string"}},
```

E a ordem, logo abaixo de `SCHEMA_DA_EXTRACAO`:

```python
_ORDEM_DOS_CAMPOS = ("intencao", "confianca", "extracao", "resposta", "perguntou")
```

- [ ] **Step 4: Escrever o parse**

Em `classificador.py`, junto de `_numero` e `_preco`:

```python
def _perguntou(bruto: Any) -> tuple[str, ...]:
    """Os nomes de campo que o modelo diz ter perguntado neste turno.

    Nao valida os nomes de proposito: quem filtra contra `fields(Extracao)` e
    `campos_a_marcar`, que tambem loga o que descartou. Duas filtragens
    divergiriam, e a divergencia so apareceria na borda.

    Nao levanta nunca. Este campo e o modelo relatando o que ele mesmo fez --
    uma forma errada aqui nao pode custar o turno inteiro, que ja foi pago e
    ja tem resposta valida para o lead.
    """
    if not isinstance(bruto, list):
        return ()
    return tuple(item for item in bruto if isinstance(item, str))
```

- [ ] **Step 5: Levar o campo ao dataclass e ao retorno**

Em `schemas.py`, em `RespostaDoAgente`, **depois** de `extracao` e **antes** de `cache_write`:

```python
    # TEC-257. Os campos sobre os quais esta resposta pergunta, declarados
    # pelo proprio modelo. Vem depois de `resposta` no schema porque relata o
    # texto ja escrito -- ver `_ORDEM_DOS_CAMPOS`.
    #
    # Tupla e nao list: o dataclass e frozen, e uma list mutavel dentro dele
    # seria congelamento de fachada.
    perguntou: tuple[str, ...] = ()
```

Em `classificador.py`, no `RespostaDoAgente(...)` de `classificar`, junto de `extracao=extrair(...)`:

```python
                perguntou=_perguntou(dados.get("perguntou")),
```

`dados.get` e não `dados[...]`, pelo mesmo motivo que `extracao` usa `get`: chave ausente não derruba o turno.

- [ ] **Step 6: Rodar os testes do parse**

Run: `python -m pytest tests/unit/test_classificador.py -q -k perguntou`
Expected: PASS (3 testes)

- [ ] **Step 7: Medir o que o campo custou, antes de escolher os tetos**

Run: `rtk proxy python -m pytest -q -k margem_do_orcamento -s`
Expected: FAIL. A linha `= liquido` deve estar por volta de **641** (era 622,8; o campo custa ~+18,5), e a asserção reprova contra o teto de 627.

**Anote o número impresso.** Os tetos abaixo assumem ~641,3; se o seu valor divergir em mais de um token, recalcule: teto fixo ≈ líquido + 14, e headroom ≈ o menor múltiplo de 10 acima de `(líquido + 0,75) / 0,75 + 15`. Não escolha o mínimo que passa — a lição da TEC-145 está escrita no comentário de `contexto_headroom_de_tokens` e o fator 0,75 existe para haver folga.

- [ ] **Step 8: Subir os dois tetos, com o preço escrito**

Em `config.py`, o valor:

```python
    contexto_headroom_de_tokens: int = 880
```

E, no fim do bloco de comentário acima dela (depois do parágrafo da TEC-250):

```python
    # **850 -> 880 na TEC-257**, que acrescentou o campo `perguntou` ao
    # `SCHEMA_DA_RESPOSTA` -- lista de strings livre, ~18,5 tokens gastos
    # neste commit. A alternativa mais cara foi recusada com o numero na mao:
    # enum dos nove campos custava ~56,0.
    #
    # Os ~0,75 restantes da subida sao **reserva**, e ainda nao foram gastos:
    # a clausula da memoria do `SISTEMA_DO_AGENTE` sera encurtada mais
    # adiante nesta mesma card, e o encurtamento e o que paga a clausula
    # nova. Enquanto isso a clausula segue como esta.
    # Preco desta subida: **30 tokens a menos de literais e resumo por turno,
    # de 12000 -- 0,25% do contexto**. Menor que as duas anteriores (3,3% e
    # 0,4%).

**Escreva o comentário exatamente assim, no tempo verbal acima.** A versão anterior deste plano mandava afirmar, no passado, que a cláusula já tinha sido encurtada — o que é falso neste commit, porque quem encurta é a Task 5. Um comentário permanente com afirmação falsa, justamente no arquivo cuja razão de existir é não envelhecer, é a TEC-243 sendo violada em prosa em vez de em número. Isso foi pego pela revisão da Task 1 e corrigido aqui.
```

Em `tests/unit/test_config.py`, no `test_a_margem_do_orcamento_do_prompt_e_deliberada`, troque as **duas** ocorrências de `627` (a de `_linha` e a do `assert`) por `655`, e acrescente ao histórico do docstring:

```
    A TEC-257 gastou os 4,2 que restavam e mais ~15, subindo o teto para 655
    e a reserva para 880. O campo `perguntou` do schema custou ~18,5; os
    ~0,75 restantes sao reserva da clausula do prompt que a mesma card
    encurta mais adiante, e ainda nao foram gastos.
```

- [ ] **Step 9: Confirmar que a conta fecha**

Run: `rtk proxy python -m pytest -q -k "margem_do_orcamento or contado_e_o_enviado" -s`
Expected: PASS (2 testes). A `margem` impressa deve ficar por volta de **13,7** — folga visível, não empate. Se estiver abaixo de 8, suba o teto: empatar derrota o propósito do teste.

- [ ] **Step 10: Rodar a suíte de unidade inteira**

Run: `python -m pytest tests/unit -q`
Expected: PASS. Se `test_prompt_caching.py` ou `test_extracao.py` reprovarem, é porque travam a forma do schema — ajuste-os ao campo novo, não o contrário.

- [ ] **Step 11: Commit**

```bash
git add src/mobia/domain/agente/schemas.py src/mobia/domain/agente/classificador.py src/mobia/app/config.py tests/unit/test_config.py tests/unit/test_classificador.py
git commit -m "feat(TEC-257): o modelo declara o que perguntou, e o orcamento pagou

O campo `perguntou` no SCHEMA_DA_RESPOSTA, depois de `resposta`: ele
relata o texto ja escrito, e nao um compromisso a honrar antes de
escrever -- a ordem e a geracao, pela TEC-244.

Lista de strings livre e nao enum dos nove campos: +18,5 tokens contra
+56,0. Nome inventado nao casa mais adiante e e descartado, o que marca
de MENOS -- o erro seguro quando a marca e permanente.

Teto fixo 627 -> 655 e reserva 850 -> 880. Preco: 30 tokens a menos de
literais e resumo por turno, de 12000 -- 0,25% do contexto, contra 3,3%
da TEC-145 e 0,4% da TEC-250. Nenhum dos dois e o minimo que passa.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A coluna e a migração 0009

**Files:**
- Create: `alembic/versions/0009_marca_de_perguntado_sem_resposta.py`
- Modify: `src/mobia/domain/context/models.py` (`LeadQualification`, ~linha 68)
- Test: `tests/integration/test_repositorio_contexto.py`

**Interfaces:**
- Produces: `LeadQualification.perguntados_sem_resposta: list[str] | None`, lido pela Task 5 e escrito pela Task 4.

A fixture `session` vem de `tests/conftest.py` (linha 376) e é a que os testes vizinhos de `test_repositorio_contexto.py` já usam — não crie outra.

**Um teste de persistência nesta sessão precisa expirar antes de ler.** `expire_on_commit=False` faz `session.get()` devolver o objeto do identity map sem recarregar os atributos já populados — sem `expire_all()`, as asserções checam o construtor em memória e um erro de encode/decode da coluna passa batido. Confirme se `expire_all()` na `AsyncSession` deste projeto é síncrono; o precedente alternativo do arquivo é o SELECT cru de `test_resumo_vai_cifrado_para_o_banco`. E antes de fechar a task, **veja o teste falhar de propósito** — um teste de persistência que ninguém viu vermelho não provou nada.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_repositorio_contexto.py`, no fim do arquivo:

```python
async def test_marca_de_perguntado_aceita_nulo_e_vazio(session) -> None:
    """`NULL` e `{}` sao fatos diferentes, e a coluna guarda os dois.

    `NULL` e "linha anterior a TEC-257, ninguem marcava". `{}` e "marcava, e
    nao havia nada a marcar". Colidir as duas leituras na mesma coluna e o
    defeito que a TEC-231 consertou nas colunas de cache.
    """
    session.add(
        LeadQualification(channel="wa", conversation_key="antiga", intencao="COMPRA")
    )
    session.add(
        LeadQualification(
            channel="wa",
            conversation_key="nova",
            intencao="COMPRA",
            perguntados_sem_resposta=[],
        )
    )
    session.add(
        LeadQualification(
            channel="wa",
            conversation_key="marcada",
            intencao="COMPRA",
            perguntados_sem_resposta=["regiao", "vagas"],
        )
    )
    await session.commit()

    # Sem expirar, o teste nao testa nada: a sessao usa
    # `expire_on_commit=False`, entao `session.get` devolve o objeto que ja
    # esta no identity map e NAO sobrescreve os atributos ja populados com o
    # que voltou do banco. As assercoes leriam o construtor em memoria, e um
    # erro de encode/decode da coluna passaria batido.
    session.expire_all()

    antiga = await session.get(LeadQualification, ("wa", "antiga"))
    nova = await session.get(LeadQualification, ("wa", "nova"))
    marcada = await session.get(LeadQualification, ("wa", "marcada"))

    assert antiga.perguntados_sem_resposta is None
    assert nova.perguntados_sem_resposta == []
    assert marcada.perguntados_sem_resposta == ["regiao", "vagas"]
```

Use a fixture de sessão que os testes vizinhos daquele arquivo já usam, e importe `LeadQualification` de `mobia.domain.context.models`.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `docker-compose up -d && python -m pytest tests/integration/test_repositorio_contexto.py -q -k perguntado`
Expected: FAIL — `TypeError: 'perguntados_sem_resposta' is an invalid keyword argument`

- [ ] **Step 3: Escrever a migração**

Crie `alembic/versions/0009_marca_de_perguntado_sem_resposta.py`:

```python
"""marca dos campos perguntados sem resposta na qualificacao do lead

TEC-257. NULL = linha anterior a esta card, quando ninguem marcava.

Nullable e sem backfill de proposito, pela mesma razao da 0007 e da 0008: uma
linha que ja existe nunca teve marca, e nao ha como reconstruir a de ontem. O
que foi perguntado esta no texto das respostas do agente, cifrado em
`messages`, e sabe-lo exigiria rodar deteccao sobre historico -- que e
justamente o proxy que esta card recusou usar para decidir comportamento.

**O default nao e `{}`, e a diferenca importa.** `{}` significa "esta linha
marcava e nao havia nada a marcar", que e afirmacao sobre um turno que rodou
com o codigo novo. `NULL` significa "ninguem media". Um `server_default` de
`{}` apagaria a distincao em toda linha antiga.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column(
            "perguntados_sem_resposta",
            postgresql.ARRAY(sa.String(32)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "perguntados_sem_resposta")
```

- [ ] **Step 4: Acrescentar a coluna ao modelo**

Em `models.py`, no import do topo, acrescente `ARRAY` ao que já vem de `sqlalchemy.dialects.postgresql`:

```python
from sqlalchemy.dialects.postgresql import ARRAY, UUID
```

E em `LeadQualification`, depois de `tem_imovel_para_vender`:

```python
    # TEC-257. Os campos que o agente perguntou e o lead nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos: `NULL` e "linha anterior a esta card,
    # ninguem marcava", `{}` e "marcava, e nao havia nada". Quem le tem de
    # tratar os dois iguais **na leitura** (`or ()`), e nunca gravar `NULL`
    # querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    perguntados_sem_resposta: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)), nullable=True
    )
```

- [ ] **Step 5: Aplicar a migração e rodar o teste**

Run: `python -m alembic upgrade head && python -m pytest tests/integration/test_repositorio_contexto.py -q -k perguntado`
Expected: PASS

- [ ] **Step 6: Confirmar que o downgrade volta**

Run: `python -m alembic downgrade 0008 && python -m alembic upgrade head`
Expected: os dois comandos terminam sem erro.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/0009_marca_de_perguntado_sem_resposta.py src/mobia/domain/context/models.py tests/integration/test_repositorio_contexto.py
git commit -m "feat(TEC-257): a coluna da marca, com NULL e vazio separados

`lead_qualification.perguntados_sem_resposta`, ARRAY nullable sem
backfill. NULL e "linha anterior a esta card, ninguem marcava"; `{}` e
"marcava e nao havia nada". Um server_default de `{}` apagaria a
distincao em toda linha antiga -- e a mesma separacao que a TEC-231
fixou nas colunas de cache.

Reconstruir a marca de ontem exigiria rodar deteccao por palavra-chave
sobre o historico cifrado, que e o proxy que esta card recusou usar
para decidir comportamento.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `campos_a_marcar`, a regra que produção e eval compartilham

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (junto de `campos_a_gravar`, ~linha 116)
- Test: `tests/unit/test_estado_marcado.py` (criar)

**Interfaces:**
- Consumes: nada de tasks anteriores (é função pura).
- Produces: `campos_a_marcar(perguntou: Iterable[str], preenchidos: Iterable[str]) -> set[str]`, chamada pela Task 4 (produção) e pela Task 6 (eval).

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_estado_marcado.py`:

```python
"""A regra de marcacao da TEC-257, sem banco.

Puro de proposito: e a mesma funcao que producao e o runner do eval chamam,
e o que ela decide nao depende de sessao nenhuma.

`caplog.at_level` e as assercoes por chave (`'"descartados"'`, e nao
`descartados=1`) sao obrigatorias: `configure_logging` usa
`structlog.stdlib.LoggerFactory` com JSONRenderer, entao o que chega em
`caplog.text` e JSON. Assercao sobre o formato do valor quebra a cada mudanca
de renderer -- e a forma que `test_classificar_loga_metricas_sem_conteudo` ja
usa.
"""

import logging

from mobia.domain.context.repositorio import campos_a_marcar


def test_marca_o_que_foi_perguntado_e_nao_esta_preenchido():
    assert campos_a_marcar(["regiao", "vagas"], set()) == {"regiao", "vagas"}


def test_nao_marca_o_que_ja_esta_preenchido():
    """Campo no estado e reperguntado e territorio do proxy irmao.

    `_reperguntou` (no runner do eval) mede perguntar o que o estado JA SABE.
    Aqui interessa so o que o lead nao respondeu.
    """
    assert campos_a_marcar(["regiao", "vagas"], {"regiao"}) == {"vagas"}


def test_descarta_nome_que_nao_e_campo_de_extracao():
    """Nome inventado marca de MENOS, e esse e o erro seguro.

    Com a marca permanente (D1 do spec), marcar de mais mata o campo pela
    vida da conversa e em silencio. Nao marcar so custa uma pergunta a mais.
    """
    assert campos_a_marcar(["regiao", "bairro", "intencao"], set()) == {"regiao"}


def test_logga_o_nome_descartado_para_a_deriva_ser_vista(caplog):
    """Sem este log, o modelo mudar de vocabulario e invisivel.

    E o buraco que a card acusa na opcao do proxy -- "o erro fica invisivel".
    """
    with caplog.at_level(logging.WARNING):
        campos_a_marcar(["bairro"], set())

    assert "estado.campo_perguntado_desconhecido" in caplog.text
    assert "bairro" in caplog.text


def test_o_log_nao_carrega_o_que_nao_parece_nome_de_campo(caplog):
    """O modelo pode devolver texto em vez de nome, e texto pode ser do lead.

    Um nome que nao casa `[a-z_]{1,32}` e contado, nunca escrito. A regra de
    PII vale para tudo o que vem de uma chamada ao modelo.
    """
    with caplog.at_level(logging.WARNING):
        campos_a_marcar(["Regiao: Vila Mariana, perto da USP"], set())

    assert "Vila Mariana" not in caplog.text
    assert '"descartados"' in caplog.text
    assert '"nomes": []' in caplog.text


def test_vazio_nao_logga_nada(caplog):
    with caplog.at_level(logging.WARNING):
        assert campos_a_marcar([], {"regiao"}) == set()

    assert caplog.text == ""
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_estado_marcado.py -q`
Expected: FAIL — `ImportError: cannot import name 'campos_a_marcar'`

- [ ] **Step 3: Escrever a função**

Em `repositorio.py`, acrescente aos imports do topo:

```python
import re
from collections.abc import Iterable
from dataclasses import fields

import structlog
```

E, logo abaixo dos imports:

```python
log = structlog.get_logger(__name__)

# Sai de `Extracao` e nao de uma lista escrita a mao: e a mesma fonte de onde
# `SCHEMA_DA_EXTRACAO` deriva, entao a proxima card que acrescentar campo nao
# precisa lembrar deste lugar.
_CAMPOS_DA_EXTRACAO = frozenset(campo.name for campo in fields(Extracao))

# Um nome de campo e minusculas e underscore. O que nao casa nao vai para o
# log: o modelo pode devolver o texto da pergunta em vez do nome, e texto de
# pergunta carrega o que o lead disse.
_NOME_PLAUSIVEL = re.compile(r"[a-z_]{1,32}")
```

E a função, imediatamente depois de `campos_a_gravar`:

```python
def campos_a_marcar(perguntou: Iterable[str], preenchidos: Iterable[str]) -> set[str]:
    """Os campos que o agente perguntou neste turno e o lead nao respondeu.

    A regra unica de marcacao da TEC-257, compartilhada entre `gravar_estado`
    (producao) e o runner do eval, pela mesma razao que `campos_a_gravar`:
    duas copias divergiriam, e a divergencia so apareceria na borda.

    `perguntou` vem do modelo, que declara sobre o que perguntou. **Nome que
    nao e campo de extracao e descartado**, nao corrigido nem adivinhado: com
    a marca permanente, marcar de mais mata o campo pela vida da conversa e
    sem rastro, enquanto marcar de menos custa uma pergunta a mais. O
    descarte e logado para a deriva de vocabulario do modelo ser visivel --
    era a critica que a card fazia ao proxy de palavra-chave.

    `preenchidos` sao os campos que este turno gravou. A subtracao e o que
    separa esta marca do proxy irmao: campo que o estado JA SABE e
    reperguntado e assunto de `_reperguntou`, nao daqui.

    A subtracao usa os campos **deste** turno, e nao o estado acumulado, para
    nao pagar uma consulta a mais. Uma marca sobre campo que ja estava
    preenchido de um turno anterior e possivel por esse caminho, e e inerte:
    `_texto_do_estado` mostra o valor quando ele existe, e a marca so aparece
    onde nao ha valor. Valor vence marca -- e um valor, uma vez gravado,
    nunca e apagado (`None` nao apaga).
    """
    conhecidos: set[str] = set()
    ignorados: list[str] = []
    for nome in perguntou:
        if nome in _CAMPOS_DA_EXTRACAO:
            conhecidos.add(nome)
        else:
            ignorados.append(nome)

    if ignorados:
        plausiveis = sorted({n for n in ignorados if _NOME_PLAUSIVEL.fullmatch(n)})
        log.warning(
            "estado.campo_perguntado_desconhecido",
            nomes=plausiveis,
            descartados=len(ignorados) - len(plausiveis),
        )

    return conhecidos - set(preenchidos)
```

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/unit/test_estado_marcado.py -q`
Expected: PASS (6 testes)

- [ ] **Step 5: Conferir tipos**

Run: `python -m mypy src`
Expected: sem erro novo.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/context/repositorio.py tests/unit/test_estado_marcado.py
git commit -m "feat(TEC-257): campos_a_marcar, a regra que producao e eval dividem

Filtra o que o modelo declarou contra `fields(Extracao)` -- a mesma fonte
de onde o schema deriva, para a proxima card que acrescentar campo nao
precisar lembrar deste lugar -- e subtrai o que o turno gravou.

Nome desconhecido e descartado e logado, nunca adivinhado: com a marca
permanente, marcar de mais mata o campo em silencio e marcar de menos
custa uma pergunta. O log e o que torna a deriva de vocabulario do
modelo visivel, que era a critica da card ao proxy de palavra-chave.

O que nao casa `[a-z_]{1,32}` e contado e nao escrito: o modelo pode
devolver o texto da pergunta, e texto de pergunta carrega fala do lead.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `gravar_estado` grava a marca, unindo dentro do SQL

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (`gravar_estado`, ~linha 155)
- Modify: `src/mobia/domain/agente/turno.py` (a chamada de `gravar_estado`, linha 161)
- Test: `tests/integration/test_repositorio_contexto.py`

**Interfaces:**
- Consumes: `campos_a_marcar` (Task 3), `LeadQualification.perguntados_sem_resposta` (Task 2), `RespostaDoAgente.perguntou` (Task 1).
- Produces: `gravar_estado(..., perguntou: Iterable[str] = ())` — parâmetro novo com default, então nenhum outro chamador quebra.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/integration/test_repositorio_contexto.py`, junto dos testes de `gravar_estado`:

```python
async def test_grava_a_marca_do_que_foi_perguntado(session) -> None:
    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k1",
        intencao=Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=["regiao", "vagas"],
    )
    await session.commit()

    linha = await session.get(LeadQualification, ("wa", "k1"))
    assert sorted(linha.perguntados_sem_resposta) == ["regiao", "vagas"]


async def test_gravacao_sem_nada_a_marcar_deixa_vazio_e_nao_nulo(session) -> None:
    """`NULL` esta reservado para linha anterior a esta card."""
    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k2",
        intencao=Intencao.COMPRA,
        extracao=Extracao(quartos=2),
    )
    await session.commit()

    linha = await session.get(LeadQualification, ("wa", "k2"))
    assert linha.perguntados_sem_resposta == []


async def test_a_marca_e_uniao_e_nao_substituicao(session) -> None:
    """Dois turnos, duas marcas, e as duas sobrevivem."""
    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k3",
        intencao=Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=["regiao"],
    )
    await session.commit()
    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k3",
        intencao=Intencao.COMPRA,
        extracao=Extracao(vagas=1),
        perguntou=["urgencia"],
    )
    await session.commit()

    linha = await session.get(LeadQualification, ("wa", "k3"))
    assert set(linha.perguntados_sem_resposta) == {"regiao", "urgencia"}


async def test_a_uniao_sobrevive_a_linha_antiga_com_nulo(session) -> None:
    """`coalesce` no SQL: `NULL || {'regiao'}` seria NULL sem ele."""
    session.add(
        LeadQualification(channel="wa", conversation_key="k4", intencao="COMPRA")
    )
    await session.commit()

    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k4",
        intencao=Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=["regiao"],
    )
    await session.commit()

    linha = await session.get(LeadQualification, ("wa", "k4"))
    assert linha.perguntados_sem_resposta == ["regiao"]


async def test_fora_de_escopo_nao_marca(session) -> None:
    """A guarda de `campos_a_gravar` vale para a marca tambem.

    O buraco e declarado no spec (D8): um agente que pergunte num turno
    FORA_DE_ESCOPO nao marca. Fica assim porque marcar de menos e o erro
    seguro.
    """
    await gravar_estado(
        session,
        channel="wa",
        conversation_key="k5",
        intencao=Intencao.FORA_DE_ESCOPO,
        extracao=Extracao(),
        perguntou=["regiao"],
    )
    await session.commit()

    assert await session.get(LeadQualification, ("wa", "k5")) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_repositorio_contexto.py -q -k "marca or marcar or uniao"`
Expected: FAIL — `gravar_estado() got an unexpected keyword argument 'perguntou'`

- [ ] **Step 3: Escrever a gravação**

Em `repositorio.py`, acrescente ao import de `sqlalchemy`:

```python
from sqlalchemy import func, literal_column, select
```

E troque `gravar_estado` por:

```python
async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
    perguntou: Iterable[str] = (),
) -> None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia.

    Nao commita -- a sessao e emprestada, como em `ler_resumo`, `ler_estado` e
    `gravar_resumo`, e quem chama e dono da fronteira da transacao.

    A regra dos campos mora em `campos_a_gravar` e a da marca em
    `campos_a_marcar`, e nao aqui, porque o runner do eval precisa das duas
    para acumular o estado sintetico entre turnos. Ver os docstrings de la.

    `perguntou` tem default de proposito: nenhum chamador antigo precisa saber
    da TEC-257 para continuar funcionando, e nao marcar e o comportamento
    seguro.
    """
    campos = campos_a_gravar(intencao, extracao)
    if not campos:
        # A guarda de FORA_DE_ESCOPO vale para a marca tambem, e o buraco esta
        # declarado no spec: um agente que pergunte num turno fora de escopo
        # nao marca e pode perguntar de novo. Com a marca permanente, marcar
        # de menos e o erro mais seguro dos dois.
        return

    marcados = sorted(campos_a_marcar(perguntou, campos))

    valores: dict[str, Any] = {
        "channel": channel,
        "conversation_key": conversation_key,
        "updated_at": datetime.now(UTC),
        # Sempre presente, mesmo vazio: `NULL` esta reservado para "linha
        # anterior a TEC-257, ninguem marcava", e um insert que omitisse a
        # coluna criaria uma linha nova com a semantica de linha antiga.
        "perguntados_sem_resposta": marcados,
        **campos,
    }
    statement = pg_insert(LeadQualification).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                **{chave: statement.excluded[chave] for chave in (*campos, "updated_at")},
                # A uniao mora no SQL, e nao numa leitura previa em Python.
                #
                # Ler o array antigo, unir em memoria e gravar abriria a
                # janela que a guarda de monotonia de `gravar_resumo` ja
                # fechou para o resumo: dois turnos concorrentes da mesma
                # conversa leem o mesmo valor, cada um une o seu, e o mais
                # lento sobrescreve a marca do mais rapido -- perda
                # silenciosa, e a marca e o que impede reperguntar.
                #
                # `coalesce` porque `NULL || {'regiao'}` e NULL em Postgres, e
                # toda linha anterior a esta card tem NULL aqui.
                #
                # Duplicata e possivel por este caminho e nao incomoda: quem
                # le testa pertinencia, nao conta.
                "perguntados_sem_resposta": func.coalesce(
                    LeadQualification.perguntados_sem_resposta,
                    literal_column("'{}'::varchar[]"),
                ).op("||")(statement.excluded.perguntados_sem_resposta),
            },
        )
    )
```

`.op("||")` e não `+`: o operador de concatenação de array do Postgres é `||`, e depender da inferência de tipo do SQLAlchemy sobre o retorno de `coalesce` para escolher entre soma e concatenação é frágil.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/integration/test_repositorio_contexto.py -q -k "marca or marcar or uniao"`
Expected: PASS (5 testes)

**O que estes testes não provam, e fica declarado:** a união é testada em turnos **sequenciais**, não concorrentes. A segurança sob concorrência vem de a união acontecer dentro do `UPDATE` — não há leitura para ficar velha —, e não de um teste. Testar duas transações concorrentes de verdade exigiria duas sessões e controle de ordem de commit, e o que isso mediria seria o Postgres, não este código.

- [ ] **Step 5: Ligar o turno — e a marca vem DEPOIS da entrega**

**A primeira chamada de `gravar_estado` (linha ~161) não muda.** Intenção e extração continuam sendo commitadas antes da entrega, e a justificativa escrita em `turno.py:147-150` continua valendo para elas: são *"fato sobre a fala dele, nao sobre a nossa resposta"*.

**`perguntou` não pode viajar nesse commit**, e essa é a correção mais importante deste plano. Três caminhos depois dele descartam a resposta do `gerada`: `desambiguando` (a resposta da chamada 1 é descartada — *"paga e nao entregue"*, diz o comentário do arquivo — e o lead recebe outra pergunta), saída bloqueada pela moderação, e envio fora da janela. Como a união nunca remove, marcar antes deixaria o campo marcado como já perguntado **sem nunca ter sido perguntado, para sempre e em silêncio** — marcar de mais, a direção que o desenho chama de insegura.

`perguntou` é fato sobre a **nossa resposta**, não sobre a fala do lead, e por isso segue a regra da outra marca desta função: `marcar_desambiguacao` só é gravado depois da entrega confirmada, porque *"marca-lo antes queimaria a unica chance de perguntar num 5xx da Meta"*. A marca da TEC-257 queima exatamente a mesma chance.

Grave-a depois da entrega confirmada, e só quando o texto entregue foi de fato a resposta do `gerada` — entregue, **e** não `desambiguando`, **e** saída não bloqueada. Reuse `gravar_estado`, passando `intencao=gerada.intencao`, `extracao=gerada.extracao` e `perguntou=gerada.perguntou`: reescrever os mesmos valores é idempotente (mais novo vence, mesmos valores) e mantém a subtração correta.

Se o processo morrer entre a entrega e a marcação, a marca se perde e o agente pode reperguntar — que é marcar de **menos**, o erro seguro.

**Testes obrigatórios deste step:** um provando que a marca **não** é gravada quando `desambiguando` é verdadeiro (o caminho de rotina, não de erro), e um provando que **é** gravada no caminho normal. Cada um tem de falhar contra a implementação que marca antes da entrega — se passar nas duas, não está testando isto.

- [ ] **Step 6: Rodar os testes do turno**

Run: `python -m pytest tests/integration/test_turno.py tests/integration/test_extracao_no_turno.py -q`
Expected: PASS. Se um dublê de `RespostaDoAgente` reprovar por falta de `perguntou`, o default `()` da Task 1 cobre — o erro será outro, investigue-o.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/context/repositorio.py src/mobia/domain/agente/turno.py tests/integration/test_repositorio_contexto.py
git commit -m "feat(TEC-257): a marca gravada, e a uniao mora no SQL

`gravar_estado` grava `perguntados_sem_resposta` em toda gravacao,
vazio inclusive -- NULL esta reservado para linha anterior a card, e um
insert que omitisse a coluna criaria linha nova com semantica de linha
velha.

A uniao e `coalesce(coluna, '{}') || excluded`, dentro do UPDATE. Ler o
array antigo em Python para unir em memoria abriria a mesma janela que
a guarda de monotonia de `gravar_resumo` fechou para o resumo: dois
turnos concorrentes leem o mesmo valor e o mais lento apaga a marca do
mais rapido. Perda silenciosa, e a marca e o que impede reperguntar.

FORA_DE_ESCOPO nao marca, pela guarda que `campos_a_gravar` ja tem. O
buraco esta declarado: marcar de menos e o erro seguro.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A marca no prompt, e a cláusula reescrita

**Files:**
- Modify: `src/mobia/domain/context/montagem.py` (`_texto_do_estado`, linha 123)
- Modify: `src/mobia/domain/agente/classificador.py` (`SISTEMA_DO_AGENTE`, ~linha 80)
- Test: `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: `LeadQualification.perguntados_sem_resposta` (Task 2).
- Produces: nada novo — muda o texto que `montar_prompt` já devolve.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/integration/test_montagem.py`, junto dos testes de `_texto_do_estado`:

```python
def test_campo_marcado_aparece_no_estado():
    estado = LeadQualification(
        channel="wa",
        conversation_key="k",
        intencao="COMPRA",
        quartos=3,
        perguntados_sem_resposta=["regiao"],
    )
    texto = _texto_do_estado(estado)

    assert "quartos: 3" in texto
    assert "regiao: (perguntado, sem resposta)" in texto


def test_valor_vence_marca():
    """A marca nunca aparece ao lado de um valor.

    Marca sobre campo ja preenchido e possivel -- `campos_a_marcar` subtrai
    os campos DESTE turno, nao o estado acumulado -- e e inerte por causa
    desta regra.
    """
    estado = LeadQualification(
        channel="wa",
        conversation_key="k",
        intencao="COMPRA",
        regiao="pinheiros",
        perguntados_sem_resposta=["regiao"],
    )
    texto = _texto_do_estado(estado)

    assert "regiao: pinheiros" in texto
    assert "perguntado" not in texto


def test_valor_falso_tambem_vence_marca():
    """`0` e `False` sao informacao, e a marca nao pode engoli-los.

    `Extracao.preenchidos` ja documenta isso: o lead que diz "nao tenho nada
    pra vender" respondeu a pergunta, e quem precisa de zero vaga informou
    zero. Um `if valor` em vez de `is not None` mostraria a marca por cima
    dos dois -- o agente reperguntaria o que o lead ja respondeu, e a
    seguranca que `campos_a_marcar` afirma (marca sobre campo preenchido e
    inerte) seria falsa justamente nos dois casos que o projeto ja sabe que
    enganam.
    """
    estado = LeadQualification(
        channel="wa",
        conversation_key="k",
        intencao="COMPRA",
        vagas=0,
        tem_imovel_para_vender=False,
        perguntados_sem_resposta=["vagas", "tem_imovel_para_vender"],
    )
    texto = _texto_do_estado(estado)

    assert "vagas: 0" in texto
    assert "tem_imovel_para_vender: False" in texto
    assert "perguntado" not in texto


def test_a_ordem_dos_campos_nao_muda_por_causa_da_marca():
    """A ordem e estavel: o campo marcado sai no lugar dele, nao no fim.

    Ordem instavel no fim do prompt e mudanca de cache e de geracao a cada
    turno, de graca.
    """
    estado = LeadQualification(
        channel="wa",
        conversation_key="k",
        intencao="COMPRA",
        vagas=1,
        perguntados_sem_resposta=["regiao"],
    )
    linhas = _texto_do_estado(estado).splitlines()

    assert linhas == [
        "intencao: COMPRA",
        "regiao: (perguntado, sem resposta)",
        "vagas: 1",
    ]


def test_marca_nula_e_marca_vazia_leem_igual():
    """`NULL` e `{}` sao fatos diferentes no banco e a mesma coisa na leitura."""
    nula = LeadQualification(channel="wa", conversation_key="k", intencao="COMPRA")
    vazia = LeadQualification(
        channel="wa", conversation_key="k", intencao="COMPRA", perguntados_sem_resposta=[]
    )

    assert _texto_do_estado(nula) == _texto_do_estado(vazia) == "intencao: COMPRA"


def test_a_regra_do_prompt_cobre_o_ignorado():
    assert "nao repergunte o preenchido nem o ignorado" in SISTEMA_DO_AGENTE
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_montagem.py -q -k "marca or vence or ignorado"`
Expected: FAIL — a marca não aparece no texto.

- [ ] **Step 3: Escrever a leitura**

Em `montagem.py`, acima de `_texto_do_estado`:

```python
# TEC-257. Fica no bloco de estado que ja existe, e nao numa secao nova de
# `montar_prompt`: um rotulo novo sairia da subcontagem fixa do orcamento, que
# tinha 4,2 tokens de margem. Reusar o rotulo custa zero ali -- o texto por
# turno cresce, e esse `montar_contexto` conta, que e o correto porque ele e
# de fato enviado.
_MARCA_SEM_RESPOSTA = "(perguntado, sem resposta)"
```

E troque o corpo de `_texto_do_estado` (mantendo o docstring, com o parágrafo novo abaixo):

```python
def _texto_do_estado(estado: LeadQualification | None) -> str:
    """Representa o estado de qualificacao para fins de medicao.

    Nao e o renderizador do prompt -- isso e da TEC-134 -- mas a contagem tem
    de medir algo perto do que sera de fato enviado. Ignorar o estado aqui
    faria a medida ficar sistematicamente menor que a real.

    A partir da TEC-257 carrega tambem os campos perguntados sem resposta.
    **Valor vence marca**, e a ordem dos campos nao muda: o campo marcado sai
    no lugar dele, nao no fim. Ordem instavel no fim do prompt seria mudanca
    de cache e de geracao a cada turno, de graca.

    `NULL` e `{}` na coluna significam coisas diferentes (ver o modelo) e a
    **leitura** trata os dois igual: `or ()`.
    """
    if estado is None:
        return ""
    marcados = set(estado.perguntados_sem_resposta or ())
    campos = {
        "intencao": estado.intencao,
        "faixa_preco_min": estado.faixa_preco_min,
        "faixa_preco_max": estado.faixa_preco_max,
        "regiao": estado.regiao,
        "tipo_imovel": estado.tipo_imovel,
        "quartos": estado.quartos,
        "vagas": estado.vagas,
        "urgencia": estado.urgencia,
        "forma_pagamento": estado.forma_pagamento,
        "tem_imovel_para_vender": estado.tem_imovel_para_vender,
    }
    linhas = []
    for chave, valor in campos.items():
        if valor is not None:
            linhas.append(f"{chave}: {valor}")
        elif chave in marcados:
            linhas.append(f"{chave}: {_MARCA_SEM_RESPOSTA}")
    return "\n".join(linhas)
```

- [ ] **Step 4: Reescrever a cláusula do prompt**

Em `classificador.py`, em `SISTEMA_DO_AGENTE`, troque

```python
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o que ja esta "
    "preenchido. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto."
```

por

```python
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o preenchido nem o "
    "ignorado. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto."
```

E acrescente ao bloco de comentário de orçamento acima de `SISTEMA_DO_AGENTE`:

```python
# A clausula da memoria foi **reescrita** e nao acrescentada, na TEC-257.
# "nao repergunte o que ja esta preenchido nem o que o lead ignorou" custava
# +6,25 tokens sobre uma margem de 4,2; encurtar a clausula existente para
# "nao repergunte o preenchido nem o ignorado" cobre os dois casos por +0,75.
# "o ignorado" depende de o modelo ligar a palavra a linha
# "(perguntado, sem resposta)" que `_texto_do_estado` poe no estado -- a forma
# explicita existia e custava 3,25, recusada por nao deixar folga para
# ninguem depois.
```

- [ ] **Step 5: Rodar os testes**

Run: `python -m pytest tests/integration/test_montagem.py -q -k "marca or vence or ignorado"`
Expected: PASS (5 testes)

- [ ] **Step 6: Confirmar que o orçamento ainda fecha**

Run: `rtk proxy python -m pytest -q -k "margem_do_orcamento or contado_e_o_enviado" -s`
Expected: PASS. A `margem` cai ~0,75 em relação à Task 1 (de ~13,7 para ~12,9). Se reprovar, a cláusula ficou mais longa do que o planejado — encurte-a, não suba o teto de novo.

- [ ] **Step 7: Commit**

```bash
git add src/mobia/domain/context/montagem.py src/mobia/domain/agente/classificador.py tests/integration/test_montagem.py
git commit -m "feat(TEC-257): a marca no prompt, sem rotulo novo e sem subir o teto

A marca entra no bloco `Estado de qualificacao:` que ja existe. Uma
secao nova em `montar_prompt` sairia da subcontagem fixa, que tinha 4,2
tokens de margem; reusar o rotulo custa zero ali.

Valor vence marca, e a ordem nao muda: o campo marcado sai no lugar
dele. Ordem instavel no fim do prompt seria mudanca de cache e de
geracao a cada turno, de graca.

A clausula da memoria foi reescrita, nao acrescentada: "nao repergunte o
preenchido nem o ignorado" cobre os dois casos por +0,75, onde o
acrescimo ingenuo custava +6,25 sobre margem de 4,2.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: O espelho no eval, e a armadilha do `conhecidos_antes`

Sem esta task o eval não mede o conserto: o estado sintético do runner não carregaria a marca, e o modelo receberia no eval um prompt diferente do de produção — que é exatamente o defeito que fez `campos_a_gravar` existir.

**Files:**
- Modify: `evals/test_acuracia_de_intencao.py` (`_rodar_conversa`, ~linhas 160-240)
- Test: `tests/unit/test_evals_reperguntas.py`

**Interfaces:**
- Consumes: `campos_a_marcar` (Task 3), `RespostaDoAgente.perguntou` (Task 1).
- Produces: `estado_acumulado` passa a carregar a chave `perguntados_sem_resposta`.

- [ ] **Step 1: Escrever o teste da armadilha**

Em `tests/unit/test_evals_reperguntas.py`:

```python
def test_conhecidos_antes_nao_conta_a_chave_da_marca():
    """A armadilha nomeada no spec (D10).

    `conhecidos_antes` e `set(estado_acumulado)`. Com a marca virando mais
    uma chave do dict, a string "perguntados_sem_resposta" entraria como se
    fosse um campo conhecido e contaminaria os dois proxies -- `_reperguntou`
    e o `- conhecidos_antes` de `campos_perguntados`.
    """
    from evals.test_acuracia_de_intencao import _campos_conhecidos

    estado = {
        "intencao": "COMPRA",
        "quartos": 2,
        "perguntados_sem_resposta": ["regiao"],
    }
    assert _campos_conhecidos(estado) == {"intencao", "quartos"}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_evals_reperguntas.py -q -k conhecidos_antes`
Expected: FAIL — `ImportError: cannot import name '_campos_conhecidos'`

- [ ] **Step 3: Extrair o filtro e usá-lo**

Em `evals/test_acuracia_de_intencao.py`, acrescente ao import de `mobia.domain.context.repositorio` a função `campos_a_marcar`, e escreva, junto de `_reperguntou`:

```python
# A chave que `campos_a_marcar` acumula no estado sintetico. Nao e campo de
# extracao, e por isso nao pode entrar em `conhecidos_antes`.
CHAVE_DA_MARCA = "perguntados_sem_resposta"


def _campos_conhecidos(estado: dict[str, Any]) -> set[str]:
    """Os campos que o estado sintetico ja sabe, sem a chave da marca.

    A armadilha que isto fecha: `set(estado_acumulado)` cru poria a string
    "perguntados_sem_resposta" na lista de campos conhecidos, e os dois
    proxies passariam a tratar a marca como um campo que o lead respondeu.
    `intencao` fica -- ela sempre esteve aqui, vem de `campos_a_gravar`, e
    nenhum marcador de repergunta casa com ela.
    """
    return set(estado) - {CHAVE_DA_MARCA}
```

- [ ] **Step 4: Rodar o teste da armadilha**

Run: `python -m pytest tests/unit/test_evals_reperguntas.py -q -k conhecidos_antes`
Expected: PASS

- [ ] **Step 5: Ligar o runner**

Em `_rodar_conversa`, troque a captura:

```python
        conhecidos_antes = _campos_conhecidos(estado_acumulado)
```

E troque a linha de acumulação (`estado_acumulado.update(campos_a_gravar(...))`) por:

```python
        # Acumula com a MESMA regra de producao -- `campos_a_gravar`, a
        # funcao que `gravar_estado` tambem usa: guarda de `FORA_DE_ESCOPO`
        # (nao acumula nada neste turno), mais novo vence (o `update` por
        # cima do que ja havia), `None` nao apaga, e `intencao` sempre entra
        # quando ha gravacao.
        #
        # A marca da TEC-257 segue o mesmo caminho e a mesma guarda, por
        # `campos_a_marcar`: sem isto o prompt sintetico do eval nao carrega
        # a linha "(perguntado, sem resposta)" que producao carrega, e o eval
        # nao consegue medir o conserto. E o mesmo defeito que fez
        # `campos_a_gravar` existir, um andar acima.
        campos_do_turno = campos_a_gravar(resposta.intencao, resposta.extracao)
        if campos_do_turno:
            marcados = set(estado_acumulado.get(CHAVE_DA_MARCA) or ())
            marcados |= campos_a_marcar(resposta.perguntou, set(campos_do_turno))
            estado_acumulado.update(campos_do_turno)
            estado_acumulado[CHAVE_DA_MARCA] = sorted(marcados)
```

- [ ] **Step 6: Rodar o que exercita o runner sem pagar chamada**

Run: `python -m pytest tests/unit -q -k "evals or reperguntas"`
Expected: PASS

- [ ] **Step 7: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: PASS. Nada em `campos_perguntados` nem em `insistencias` mudou de comportamento — esta card não os toca, e as 18 conversas continuam sendo linha de base válida.

- [ ] **Step 8: Commit**

```bash
git add evals/test_acuracia_de_intencao.py tests/unit/test_evals_reperguntas.py
git commit -m "feat(TEC-257): o eval espelha a marca, pela mesma funcao

Sem isto o prompt sintetico do runner nao carrega a linha
"(perguntado, sem resposta)" que producao carrega, e o eval nao mede o
conserto -- o mesmo defeito que fez `campos_a_gravar` existir.

E fecha a armadilha: `conhecidos_antes` era `set(estado_acumulado)`, e
com a marca virando chave do dict a string "perguntados_sem_resposta"
entraria como campo conhecido, contaminando os dois proxies.
`_campos_conhecidos` a remove, com um teste travando.

`campos_perguntados` e `insistencias` nao mudam: as 18 conversas
continuam sendo linha de base valida.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Depois das seis tasks

O que **não** está nestas tasks e precisa acontecer antes de fechar a card:

1. **A execução paga do gate.** É o que revela se o modelo entende o campo `perguntou` sem `description` — a lacuna principal do spec. Se ele devolver o texto das perguntas em vez dos nomes, nada casa, nada é marcado, e o log de `estado.campo_perguntado_desconhecido` enche. **Falha benigna e observável**, e o próximo passo já tem preço: 2b, enum dos nove campos, +56,0 tokens (teto 695, headroom 950).
2. **A comparação segue o protocolo da TEC-253:** comparar a **contagem de insistências**, que é categórica, e não o percentual de aderência ao tom, que oscila 5,7 pontos. Linha de base: as 18 conversas de 42.
3. **A seção do README**, com o que a execução mostrou — não antes dela, e sem prever o resultado.
