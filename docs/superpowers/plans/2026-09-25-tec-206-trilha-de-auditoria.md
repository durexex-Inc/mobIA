# TEC-206 — Registrar trilha de auditoria imutável: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma tabela `eventos_auditoria` só de acréscimo, protegida por trigger contra `UPDATE` e contra `DELETE` antes de 12 meses, gravada explicitamente na mesma transação por handoff, opt-out, reativação, acesso ao resumo e acesso negado com identidade, apagada depois de 12 meses por um cron, e lida por `GET /api/v1/auditoria` só pelo `ADMIN`.

**Architecture:** `domain/auditoria/` com vocabulário puro (`vocabulario.py`, `referencia.py`), o modelo, `registrar_evento` (acrescenta à sessão de quem chama e dá `flush`, nunca commit), a retenção e a consulta paginada; a garantia mora em dois triggers da migration 0048; os escritores existentes (`registrar_handoff`, `registrar_optout`, `reativar`, `regenerar`, `registrar_negativa`) chamam `registrar_evento`; a rota de leitura segue a convenção de filtro, 422 e cursor da TEC-192.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), PL/pgSQL, ARQ, FastAPI, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-tec-206-trilha-de-auditoria-design.md`

## Spec vs code

O desenho está certo no que decide; estes são os pontos em que ele descreve o código de forma incompleta ou imprecisa, e o plano segue o código:

1. **`resolver_ip` não devolve sempre um IP.** O desenho (D7) manda gravar o `ip` de `api/middleware.py::resolver_ip` numa coluna `inet`. Ela devolve o que o socket ou o `X-Forwarded-For` disserem, truncado a 64 caracteres — pode ser `1.2.3.4:5678`, `testclient` (host do `TestClient` do Starlette) ou lixo. Medido nesta máquina: o asyncpg recusa `'abc'` para `inet` com `DataError`, o que viraria 500 num 403. O plano valida com `ipaddress` e grava nulo quando não é IP (`ip_valido_ou_nulo`, Task 5).
2. **"Toda rota que chama `exigir_dono`" inclui um intermediário síncrono.** `api/routes/conversas.py::_exigir_que_seja_ele_mesmo` é `def` e embrulha `exigir_dono`; ele passa a `async` e os dois chamadores (`assumir`, `devolver`) passam a `await`. `api/routes/handoffs.py::_exigir_dono_do` já é `async`.
3. **"O teste de autorização por rota a cobre sozinho" vale só para metade.** `tests/unit/test_autorizacao_em_toda_rota.py::test_toda_rota_declara_autorizacao` cobre a rota nova sozinho; `test_a_permissao_de_cada_rota` compara contra o mapa escrito à mão `PERMISSAO_ESPERADA` e reprova até ganhar a linha `("GET", "/api/v1/auditoria"): "VER_AUDITORIA"` (Task 6).
4. **`registrar_handoff` tem muito mais chamadores que os seis de produção.** Cinco em `domain/agente/turno.py`, um em `workers/jobs/process_message.py`, **e cerca de quarenta em testes** (duas fixtures de `tests/conftest.py` e oito arquivos de `tests/integration/`). Tornar `ator` obrigatório obriga a editar todos, e o `mypy` não os pega — `[tool.mypy].files` é `src` e `alembic`, não `tests`. A Task 4 traz uma varredura por `ast` para isso.
5. **A nova guarda de configuração quebra testes que já existem.** Três testes sobem `Settings` em produção esperando sucesso ou outra guarda: `tests/unit/test_config.py::test_producao_com_chave_propria_sobe`, `::test_producao_com_token_de_catalogo_proprio_sobe` e o helper `tests/integration/test_worker_startup.py::_producao`. Os três ganham `AUDITORIA_CHAVE_DO_LEAD` (Task 1).

## Global Constraints

- Comentários e docstrings em `src/`, `tests/` e `alembic/`: português **sem acento**. Prosa em `docs/`: **com acento**. Nenhum texto desta card chega ao lead.
- `registrar_evento` **nunca commita**; nas duas leituras (resumo e negativa) quem chama abre uma sessão curta própria e commita **antes** de a resposta sair.
- `detalhes` só leva metadado fechado (permissão, motivo, papel, método, gatilho); **nunca** texto digitado por pessoa, nunca o `motivo` da reativação, nunca o texto do resumo. `leadRef` nunca sai na API.
- Vocabulário fechado com `CHECK`: `ator_tipo` ∈ {`USUARIO`, `AGENTE`, `SISTEMA`}; `acao` ∈ {`DADO_PESSOAL_ACESSADO`, `QUALIFICACAO_ALTERADA`, `HANDOFF_CRIADO`, `OPTOUT_REGISTRADO`, `OPTOUT_REATIVADO`, `PROMPT_PUBLICADO`, `ACESSO_NEGADO`}.
- "12 meses" é `interval '12 months'` sobre o relógio do banco (`clock_timestamp()`), uma definição só para o trigger e para o job.
- **O relógio do Postgres local não é o do host.** Medido em 25/09/2026: `SELECT clock_timestamp()` no container devolveu `2025-09-25`, enquanto o Python do host devolveu `2026-09-25`. Todo teste que compara tempo usa valores lidos do banco (`criado_em` gravado, `clock_timestamp()`), **nunca** `datetime.now()` do Python.
- Migration à mão, `0048`, `down_revision = "0047"`; `tests/unit/test_uma_cabeca_de_migration.py` tem de continuar verde.
- Vários blocos de código deste plano passam de 100 colunas ou quebram chamadas à mão: rode `./.venv/Scripts/python.exe -m ruff format src tests alembic` antes dos gates e aceite o que ele reescrever.
- Os três gates antes de todo commit: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Commit: `tipo(TEC-206): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. `git add` com caminhos explícitos; `.superpowers/` nunca entra.
- Citação de código em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.
- Número de card só se copiado do desenho ou do código; nunca inventado.

## Decisions

Pontos que o desenho deixa abertos, decididos aqui:

- **Decision:** sete tasks e não seis — o vocabulário puro (Task 1, só `tests/unit`) separado da migration e da garantia no banco (Task 2), porque um revisor pode aprovar o HMAC e a guarda de configuração e recusar os triggers, ou o contrário.
- **Decision:** `registrar_evento` faz `session.add` + `await session.flush()`, como `registrar_recalculo`: um `CHECK` violado estoura no ponto da chamada, e não num commit distante.
- **Decision:** `entidade` também tem `CHECK`, com `handoff`, `optout_event`, `rota` e as duas das ações sem chamador (`lead_qualification`, `configuracao_agente`) — o desenho pede o teste "vocabulário de entidade bate com a migration", e sem `CHECK` não haveria o que bater.
- **Decision:** `campo` fica sem `CHECK`: ele nomeia uma coluna, é escrito por código e não por pessoa, e os campos da TEC-194/195 ainda não têm nome.
- **Decision:** `CHECK (ator_tipo = 'USUARIO') = (ator_id IS NOT NULL)`, espelhado em `Ator.__post_init__`: registro de pessoa sem identidade, ou de agente com identidade, é a mentira que a trilha não pode conter.
- **Decision:** o ator é um `Ator(tipo, id)` com as constantes `ATOR_AGENTE` e `ATOR_SISTEMA`, e o `ator` novo de `registrar_handoff` tem esse tipo — um tipo só para os cinco escritores.
- **Decision:** `ip` passa por `ipaddress.ip_address`; o que não for IP vira nulo (ver "Spec vs code" 1).
- **Decision:** o `entidade_id` da negativa é `request.scope["route"].path` (verificado: com FastAPI 0.141.1 dá `/api/v1/x/{a}/b` num router com prefixo); sem rota no escopo, cai para `request.url.path[:200]`.
- **Decision:** índices `(criado_em DESC, id DESC)`, `(ator_id, criado_em DESC)`, `(acao, criado_em DESC)`, `(lead_ref, criado_em DESC)` — o `id` também descendente para que `ORDER BY criado_em DESC, id DESC` e o cursor sejam servidos por uma varredura só; o desenho escreve `(criado_em desc, id)`.
- **Decision:** `lead_ref` segue a fórmula do desenho, `f"{channel}:{conversation_key}"`, sem prefixo de tamanho: a colisão exigiria um `channel` com `:`, e os canais são constantes internas (`whatsapp`, `web`).
- **Decision:** a guarda de `AUDITORIA_CHAVE_DO_LEAD` recusa só o default, sem piso de tamanho — é o que o desenho pede, e o piso do JWT existe por causa da RFC 7518, que aqui não se aplica.
- **Decision:** o filtro `ator` é string exata de até 64 caracteres, não UUID, porque `token-compartilhado` é um `ator_id` legítimo e precisa ser pesquisável.
- **Decision:** `de`/`ate` sem fuso são 422, e `de >= ate` é 422 — uma data sem offset seria interpretada no fuso da sessão do banco, e um intervalo vazio se leria como "ninguém fez nada".
- **Decision:** a consulta reaproveita `FiltroInvalido`, `LIMITE_PADRAO` e `LIMITE_MAXIMO` de `domain/leads/consulta.py`: uma convenção de 422 e de página para as duas listas do painel. O cursor é próprio, porque a forma é outra.
- **Decision:** retenção em lotes de 1000, commit por lote, `ORDER BY criado_em`; `lote < 1` levanta `ValueError` (com `LIMIT 0` o laço nunca terminaria).
- **Decision:** o registro do resumo entra na mesma sessão curta que já lê a linha do handoff em `regenerar`, com commit antes do `return`.

## Review Focus

1. **Endereço que não é IP** (`X-Forwarded-For: 1.2.3.4:80`, `testclient`, lixo) — o `ip` fica nulo e a resposta sai (403 ou 200), nunca 500 por `DataError` do `inet`. Teste em Task 5 (`test_ip_valido_ou_nulo`).
2. **Dois turnos criam o handoff da mesma conversa ao mesmo tempo** — exatamente um `HANDOFF_CRIADO`, o do vencedor do `ON CONFLICT`. Teste em Task 4.
3. **Mais linhas vencidas que um lote** — todas saem, a de 11 meses fica, o laço termina. Teste em Task 3.
4. **A escrita da trilha falha no acesso ao resumo** — o resumo não sai. Teste em Task 5.
5. **Filtro de lead pela metade** (`channel` sem `conversationKey`, ou o contrário) — 422, e não a trilha inteira de todos os leads. Teste em Task 6.

---

### Task 1: O vocabulário, o `lead_ref` e a guarda da chave

**Files:**
- Create: `src/mobia/domain/auditoria/__init__.py` (vazio)
- Create: `src/mobia/domain/auditoria/vocabulario.py`
- Create: `src/mobia/domain/auditoria/referencia.py`
- Modify: `src/mobia/app/config.py` (constante, campo `auditoria_chave_do_lead`, validator novo)
- Modify: `.env.example`
- Modify: `tests/unit/test_config.py` (três testes novos; dois existentes ganham a variável)
- Modify: `tests/integration/test_worker_startup.py` (`_producao` ganha a variável)
- Test: `tests/unit/test_auditoria_vocabulario.py`

**Interfaces:**
- Produces:
  - `AtorTipo`, `Acao`, `Entidade` (`StrEnum`); `CAMPO_RESUMO = "resumo"`; `MOTIVOS_DE_NEGATIVA: frozenset[str]`; `CHAVES_DE_DETALHES: frozenset[str]`; `PAPEL_DESCONHECIDO = "DESCONHECIDO"`; `METODO_DESCONHECIDO = "OUTRO"`
  - `Ator(tipo: AtorTipo, id: str | None = None)` (frozen dataclass, valida o par); `ATOR_AGENTE`, `ATOR_SISTEMA`
  - `detalhes_da_negativa(*, permissao: str | None, motivo: str, papel: str, metodo: str) -> dict[str, str | None]`
  - `detalhes_do_handoff(gatilho: Gatilho) -> dict[str, str | None]`
  - `validar_detalhes(detalhes: Mapping[str, str | None]) -> dict[str, str | None]`
  - `referencia.lead_ref(channel: str, conversation_key: str, *, chave: str) -> str` (64 hex)
  - `Settings.auditoria_chave_do_lead: str`; `config.CHAVE_DO_LEAD_DE_DESENVOLVIMENTO`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_auditoria_vocabulario.py`:

```python
"""O vocabulario da trilha de auditoria e o `lead_ref`. TEC-206, D2, D4 e D5.

Sem banco: o que se verifica aqui e a forma do que vai para a linha -- o par
ator/id, o `detalhes` so com metadado fechado, e a referencia ao lead que nao
contem o telefone. A garantia no banco esta em
`tests/integration/test_trilha_de_auditoria.py`.
"""

import pytest

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import (
    ATOR_AGENTE,
    ATOR_SISTEMA,
    CHAVES_DE_DETALHES,
    METODO_DESCONHECIDO,
    MOTIVOS_DE_NEGATIVA,
    PAPEL_DESCONHECIDO,
    Ator,
    AtorTipo,
    detalhes_da_negativa,
    detalhes_do_handoff,
    validar_detalhes,
)
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.usuarios.models import PAPEIS
from mobia.domain.usuarios.permissoes import Permissao

CHAVE = "chave-de-teste"
TELEFONE = "5511911112222"


class TestLeadRef:
    def test_e_estavel(self) -> None:
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) == lead_ref(
            "whatsapp", TELEFONE, chave=CHAVE
        )

    def test_tem_64_caracteres_hexadecimais(self) -> None:
        ref = lead_ref("whatsapp", TELEFONE, chave=CHAVE)
        assert len(ref) == 64
        int(ref, 16)

    def test_muda_com_o_canal(self) -> None:
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) != lead_ref("web", TELEFONE, chave=CHAVE)

    def test_nao_contem_o_telefone(self) -> None:
        ref = lead_ref("whatsapp", TELEFONE, chave=CHAVE)
        assert TELEFONE not in ref
        assert TELEFONE[-8:] not in ref

    def test_depende_da_chave(self) -> None:
        """Sem a chave nao se recalcula -- e por isso ela nao pode ser o default em producao."""
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) != lead_ref(
            "whatsapp", TELEFONE, chave="outra-chave"
        )


class TestAtor:
    def test_usuario_exige_id(self) -> None:
        with pytest.raises(ValueError, match="USUARIO"):
            Ator(AtorTipo.USUARIO)

    def test_agente_e_sistema_nao_tem_id(self) -> None:
        with pytest.raises(ValueError):
            Ator(AtorTipo.AGENTE, "alguem")
        assert ATOR_AGENTE.id is None
        assert ATOR_SISTEMA.id is None

    def test_usuario_com_id_passa(self) -> None:
        assert Ator(AtorTipo.USUARIO, "token-compartilhado").id == "token-compartilhado"


class TestDetalhes:
    def test_negativa_so_leva_valores_de_vocabulario_fechado(self) -> None:
        detalhes = detalhes_da_negativa(
            permissao=Permissao.VER_AUDITORIA.value,
            motivo="sem_permissao",
            papel="GERENTE",
            metodo="GET",
        )
        assert set(detalhes) <= CHAVES_DE_DETALHES
        assert detalhes["permissao"] in {p.value for p in Permissao}
        assert detalhes["motivo"] in MOTIVOS_DE_NEGATIVA
        assert detalhes["papel"] in PAPEIS
        assert detalhes["metodo"] == "GET"

    def test_papel_fora_da_lista_nao_e_copiado(self) -> None:
        """O papel vem do JWT; um valor fora de PAPEIS nao entra como texto."""
        detalhes = detalhes_da_negativa(
            permissao=None, motivo="sem_sessao", papel="SUPERVISOR do Paulo", metodo="GET"
        )
        assert detalhes["papel"] == PAPEL_DESCONHECIDO

    def test_metodo_fora_da_lista_nao_e_copiado(self) -> None:
        detalhes = detalhes_da_negativa(
            permissao=None, motivo="sem_sessao", papel="ADMIN", metodo="PROPFIND"
        )
        assert detalhes["metodo"] == METODO_DESCONHECIDO

    def test_motivo_desconhecido_e_erro_de_programacao(self) -> None:
        with pytest.raises(ValueError, match="motivo"):
            detalhes_da_negativa(
                permissao=None, motivo="o usuario xingou", papel="ADMIN", metodo="GET"
            )

    def test_permissao_desconhecida_e_erro_de_programacao(self) -> None:
        with pytest.raises(ValueError, match="permissao"):
            detalhes_da_negativa(
                permissao="QUALQUER", motivo="sem_permissao", papel="ADMIN", metodo="GET"
            )

    def test_handoff_leva_so_o_gatilho(self) -> None:
        assert detalhes_do_handoff(Gatilho.LEAD_QUENTE) == {"gatilho": "LEAD_QUENTE"}

    def test_chave_fora_do_vocabulario_e_recusada(self) -> None:
        with pytest.raises(ValueError, match="motivo_livre"):
            validar_detalhes({"motivo_livre": "lead pediu por telefone"})

    def test_valor_que_nao_e_texto_e_recusado(self) -> None:
        with pytest.raises(ValueError):
            validar_detalhes({"gatilho": 3})
```

Append to `tests/unit/test_config.py` (and add `CHAVE_DO_LEAD_DE_DESENVOLVIMENTO` to the import from `mobia.app.config`):

```python
def test_producao_com_a_chave_do_lead_de_desenvolvimento_nao_sobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEC-206, D4. Quem conhece a chave calcula o `lead_ref` de qualquer telefone.

    E o mesmo modo de falha silencioso das outras guardas deste arquivo: a
    trilha grava normalmente, so que qualquer um descobre se um numero aparece
    nela. As tres guardas anteriores recebem valor proprio para nao dispararem
    primeiro.
    """
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("JWT_SEGREDO", "segredo-de-jwt-proprio-com-32-bytes-ou-mais")
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "token-de-catalogo-proprio")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AUDITORIA_CHAVE_DO_LEAD", raising=False)

    with pytest.raises(ConfiguracaoInsegura) as erro:
        Settings(_env_file=None)

    assert "AUDITORIA_CHAVE_DO_LEAD" in str(erro.value)
    assert CHAVE_DO_LEAD_DE_DESENVOLVIMENTO not in str(erro.value)


def test_producao_com_chave_do_lead_propria_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("JWT_SEGREDO", "segredo-de-jwt-proprio-com-32-bytes-ou-mais")
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "token-de-catalogo-proprio")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUDITORIA_CHAVE_DO_LEAD", "chave-do-lead-propria")

    assert Settings(_env_file=None).auditoria_chave_do_lead == "chave-do-lead-propria"


def test_desenvolvimento_segue_com_a_chave_do_lead_de_desenvolvimento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guarda nao pode travar a maquina de ninguem nem o CI."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("AUDITORIA_CHAVE_DO_LEAD", raising=False)

    assert Settings(_env_file=None).auditoria_chave_do_lead == CHAVE_DO_LEAD_DE_DESENVOLVIMENTO
```

In the two existing tests that expect production to start — `test_producao_com_chave_propria_sobe` and `test_producao_com_token_de_catalogo_proprio_sobe` — add, before `Settings(_env_file=None)`:

```python
    # TEC-206: a quarta guarda do mesmo tipo. Sem isto ela dispara e o teste
    # morre por ela, nao pelo que afirma.
    monkeypatch.setenv("AUDITORIA_CHAVE_DO_LEAD", "chave-do-lead-propria")
```

In `tests/integration/test_worker_startup.py::_producao`, after the `JWT_SEGREDO` line:

```python
    # TEC-206: a quarta guarda do mesmo tipo, pelo mesmo motivo das tres acima.
    monkeypatch.setenv("AUDITORIA_CHAVE_DO_LEAD", "chave-do-lead-propria")
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/unit/test_config.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.auditoria'` and `ImportError: cannot import name 'CHAVE_DO_LEAD_DE_DESENVOLVIMENTO'`.

- [ ] **Step 3: Implement**

`src/mobia/domain/auditoria/__init__.py`: empty file.

`src/mobia/domain/auditoria/vocabulario.py`:

```python
"""O vocabulario fechado da trilha de auditoria. TEC-206, D2 e D5 do desenho.

Modulo sem I/O, no molde de `handoff/vocabulario.py`. Os tres enums tem copia
literal nos CHECKs da migration 0048 -- a migration nao importa daqui, porque
migration aplicada nao muda quando o codigo muda --, e quem prende as duas
copias juntas e `tests/unit/test_auditoria_vocabulario.py`.

**`detalhes` so e montado pelas funcoes deste modulo** (D5): cada valor sai de
um vocabulario fechado, e texto digitado por uma pessoa nunca entra. Texto
livre pode carregar dado pessoal, e nenhum teste garante que nao carrega.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.usuarios.models import PAPEIS
from mobia.domain.usuarios.permissoes import Permissao


class AtorTipo(StrEnum):
    USUARIO = "USUARIO"
    AGENTE = "AGENTE"
    SISTEMA = "SISTEMA"


class Acao(StrEnum):
    DADO_PESSOAL_ACESSADO = "DADO_PESSOAL_ACESSADO"
    # Sem chamador: a edicao de qualificacao pelo dashboard e a TEC-194, e so a
    # feita por pessoa sera auditada -- a do agente se reconstroi pela
    # transcricao.
    QUALIFICACAO_ALTERADA = "QUALIFICACAO_ALTERADA"
    HANDOFF_CRIADO = "HANDOFF_CRIADO"
    OPTOUT_REGISTRADO = "OPTOUT_REGISTRADO"
    OPTOUT_REATIVADO = "OPTOUT_REATIVADO"
    # Sem chamador: `ConfiguracaoAgente` nao existe (TEC-198/199).
    PROMPT_PUBLICADO = "PROMPT_PUBLICADO"
    ACESSO_NEGADO = "ACESSO_NEGADO"


class Entidade(StrEnum):
    HANDOFF = "handoff"
    OPTOUT_EVENT = "optout_event"
    # A negativa: `entidade_id` e o template da rota, e nao o caminho com o id.
    ROTA = "rota"
    # As entidades das duas acoes sem chamador. Entram agora porque o CHECK da
    # 0048 e o que custaria migration depois, e o chamador nao custa nada.
    LEAD_QUALIFICATION = "lead_qualification"
    CONFIGURACAO_AGENTE = "configuracao_agente"


# O unico `campo` com chamador hoje: o resumo do handoff, em
# `POST /api/v1/handoffs/{handoff_id}/resumo`.
CAMPO_RESUMO = "resumo"

# Os tres motivos que `api/autorizacao.py` produz. Um quarto, sem entrar aqui,
# e erro de programacao -- e nao texto que passe para a trilha.
MOTIVOS_DE_NEGATIVA = frozenset({"sem_permissao", "sem_sessao", "corretor_nao_e_o_dono"})

_METODOS_HTTP = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# O que `detalhes` pode ter como chave. `validar_detalhes` recusa o resto.
CHAVES_DE_DETALHES = frozenset({"gatilho", "permissao", "motivo", "papel", "metodo"})

# O papel vem do JWT, assinado com o nosso segredo -- mas um valor fora de
# PAPEIS e anomalia, e anomalia nao vira texto na trilha.
PAPEL_DESCONHECIDO = "DESCONHECIDO"
METODO_DESCONHECIDO = "OUTRO"


@dataclass(frozen=True)
class Ator:
    """Quem fez. Pessoa tem id; agente e sistema nao tem.

    O par e conferido aqui e pelo `ck_eventos_auditoria_ator_id` da 0048: um
    registro de pessoa sem identidade, ou de agente com identidade, e a
    mentira que a trilha nao pode conter.
    """

    tipo: AtorTipo
    id: str | None = None

    def __post_init__(self) -> None:
        if (self.tipo == AtorTipo.USUARIO) != (self.id is not None):
            raise ValueError(f"so USUARIO tem id; recebido tipo={self.tipo}, id={self.id!r}")


ATOR_AGENTE = Ator(AtorTipo.AGENTE)
ATOR_SISTEMA = Ator(AtorTipo.SISTEMA)


def validar_detalhes(detalhes: Mapping[str, str | None]) -> dict[str, str | None]:
    """Recusa chave fora de `CHAVES_DE_DETALHES` e valor que nao seja texto ou nulo.

    E a ultima barreira antes do INSERT: quem monta `detalhes` sao as funcoes
    abaixo, e esta funcao garante que um sitio de chamada novo nao contorne as
    duas com um dict escrito a mao.
    """
    fora = sorted(set(detalhes) - CHAVES_DE_DETALHES)
    if fora:
        raise ValueError(f"detalhes com chave fora do vocabulario: {', '.join(fora)}")
    for chave, valor in detalhes.items():
        if valor is not None and not isinstance(valor, str):
            raise ValueError(f"detalhes.{chave} tem de ser texto ou nulo")
    return dict(detalhes)


def detalhes_da_negativa(
    *, permissao: str | None, motivo: str, papel: str, metodo: str
) -> dict[str, str | None]:
    """O `detalhes` de um ACESSO_NEGADO. Cada valor sai de um vocabulario fechado."""
    if motivo not in MOTIVOS_DE_NEGATIVA:
        raise ValueError(f"motivo de negativa desconhecido: {motivo}")
    if permissao is not None and permissao not in {p.value for p in Permissao}:
        raise ValueError(f"permissao desconhecida: {permissao}")
    return {
        "permissao": permissao,
        "motivo": motivo,
        "papel": papel if papel in PAPEIS else PAPEL_DESCONHECIDO,
        "metodo": metodo if metodo in _METODOS_HTTP else METODO_DESCONHECIDO,
    }


def detalhes_do_handoff(gatilho: Gatilho) -> dict[str, str | None]:
    """O `detalhes` de um HANDOFF_CRIADO: o gatilho que o criou, e nada mais."""
    return {"gatilho": gatilho.value}
```

`src/mobia/domain/auditoria/referencia.py`:

```python
"""A referencia ao lead que a trilha guarda no lugar do telefone. TEC-206, D4.

No WhatsApp, `conversation_key` E o telefone do lead, e o lead nao tem outro
identificador. Gravar o par na trilha seria gravar o dado pessoal que a card
proibe; gravar o HMAC dele permite achar os eventos de um lead sem guarda-lo.

**A chave e propria** (`AUDITORIA_CHAVE_DO_LEAD`), e nao a de
`infra/crypto.py`: chaves com funcoes diferentes nao se reaproveitam, e esta
nao pode rodar sem tornar a trilha inteira impesquisavel -- todo `lead_ref`
antigo deixaria de bater com o recalculado.
"""

import hashlib
import hmac


def lead_ref(channel: str, conversation_key: str, *, chave: str) -> str:
    """HMAC-SHA256 de `channel:conversation_key`, em hex (64 caracteres).

    Estavel, nao reversivel sem a chave, e sobrevive a eliminacao do lead
    (RNF-21) sem guardar nada que o identifique.
    """
    mensagem = f"{channel}:{conversation_key}".encode()
    return hmac.new(chave.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()
```

In `src/mobia/app/config.py`, after `SEGREDO_DE_JWT_DE_DESENVOLVIMENTO`:

```python
# A chave do `lead_ref` da trilha de auditoria em desenvolvimento (TEC-206,
# D4). Mesmo molde da CHAVE_DE_DESENVOLVIMENTO: commitada de proposito, e
# recusada em producao pelo validator. Quem a tiver calcula o `lead_ref` de
# qualquer telefone e descobre se ele aparece na trilha.
CHAVE_DO_LEAD_DE_DESENVOLVIMENTO = "dev-auditoria-chave-do-lead-nao-use-em-producao"
```

In `Settings`, right after `content_encryption_key`:

```python
    # A chave do HMAC que produz `eventos_auditoria.lead_ref` (TEC-206, D4).
    # Mesma guarda de producao da chave de cifra, e pela mesma razao: chave
    # conhecida nao produz erro nenhum, ela so deixa de proteger. E nao pode
    # rodar sem tornar a trilha impesquisavel -- ver `auditoria/referencia.py`.
    auditoria_chave_do_lead: str = CHAVE_DO_LEAD_DE_DESENVOLVIMENTO
```

In `Settings`, right after `_recusar_token_de_catalogo_de_desenvolvimento_em_producao` (depois das tres guardas de segredo, para que os testes delas continuem reprovando por elas):

```python
    @model_validator(mode="after")
    def _recusar_chave_do_lead_de_desenvolvimento_em_producao(self) -> "Settings":
        """TEC-206, D4. Mesmo molde da chave de cifra e do segredo de JWT.

        Uma chave de HMAC publicamente conhecida nao falha: a trilha grava
        normalmente, e quem souber a chave recalcula o `lead_ref` de qualquer
        telefone. No validator, e nao no `create_app`, para valer em API,
        worker, alembic e qualquer script que construa `Settings`.
        """
        if self.em_producao and self.auditoria_chave_do_lead == CHAVE_DO_LEAD_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "AUDITORIA_CHAVE_DO_LEAD esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Quem a conhece descobre se um "
                "telefone aparece na trilha de auditoria. Gere uma: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return self
```

In `.env.example`, after the `CONTENT_ENCRYPTION_KEY` line:

```bash
# Chave do HMAC que referencia o lead na trilha de auditoria (TEC-206). Em
# production nao pode ficar no default: a aplicacao recusa subir. Nao gire sem
# plano: todo lead_ref ja gravado deixa de bater.
# python -c "import secrets;print(secrets.token_urlsafe(48))"
AUDITORIA_CHAVE_DO_LEAD=dev-auditoria-chave-do-lead-nao-use-em-producao
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/unit/test_config.py -v --tb=short`
Expected: PASS.

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_worker_startup.py --tb=short -q`
Expected: PASS (needs `docker compose` up).

- [ ] **Step 5: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/auditoria/__init__.py src/mobia/domain/auditoria/vocabulario.py src/mobia/domain/auditoria/referencia.py src/mobia/app/config.py .env.example tests/unit/test_auditoria_vocabulario.py tests/unit/test_config.py tests/integration/test_worker_startup.py
git commit -m "feat(TEC-206): o vocabulario da trilha e o lead_ref, com chave recusada em producao se for a de dev

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A tabela, os dois triggers e `registrar_evento`

**Files:**
- Create: `alembic/versions/0048_eventos_auditoria.py`
- Create: `src/mobia/domain/auditoria/models.py`
- Create: `src/mobia/domain/auditoria/registro.py`
- Modify: `tests/conftest.py` (`TABELAS` ganha `eventos_auditoria`; docstring de `banco_limpo` deixa de dizer "19 tabelas")
- Modify: `tests/unit/test_auditoria_vocabulario.py` (vocabulário contra os `CHECK`)
- Modify: `tests/integration/test_migrations.py` (a 0048 desce e sobe)
- Test: `tests/integration/test_trilha_de_auditoria.py`

**Interfaces:**
- Consumes: `AtorTipo`, `Acao`, `Entidade`, `Ator`, `validar_detalhes` (Task 1); `lead_ref` (Task 1); `Settings.auditoria_chave_do_lead` (Task 1).
- Produces:
  - tabela `eventos_auditoria`; triggers `eventos_auditoria_carimbo` (BEFORE INSERT, função `eventos_auditoria_carimba()`) e `eventos_auditoria_imutavel` (BEFORE UPDATE OR DELETE, função `eventos_auditoria_protege()`)
  - `models.EventoAuditoria` (ORM; `ip` volta do asyncpg como `ipaddress.IPv4Address`/`IPv6Address`)
  - `registro.Origem(ip: str | None, correlation_id: str | None)` (frozen dataclass)
  - `async def registro.registrar_evento(session: AsyncSession, *, ator: Ator, acao: Acao, entidade: Entidade, entidade_id: str, campo: str | None = None, lead: tuple[str, str] | None = None, detalhes: Mapping[str, str | None] | None = None, origem: Origem | None = None) -> uuid.UUID` — `add` + `flush`, **nunca commit**

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_auditoria_vocabulario.py` (imports go to the top of the file: `import ast`, `import pathlib`, and `Acao`, `Entidade` added to the `vocabulario` import):

```python
MIGRACAO = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0048_eventos_auditoria.py"
)


def _tupla_da_migracao(nome: str) -> tuple[str, ...]:
    """O valor literal de `nome = ("...", ...)` no topo da 0048.

    Le o ARQUIVO com `ast`, como `test_uma_cabeca_de_migration.py`: nao
    precisa de banco, e nao importa a migration -- importa-la rodaria o
    `from alembic import op` fora de um contexto de migracao.
    """
    arvore = ast.parse(MIGRACAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(
            isinstance(alvo, ast.Name) and alvo.id == nome for alvo in no.targets
        ):
            valor = ast.literal_eval(no.value)
            assert isinstance(valor, tuple)
            return valor
    raise AssertionError(f"{nome} nao encontrado na 0048")


@pytest.mark.parametrize(
    ("constante", "enum"),
    [("_ATORES", AtorTipo), ("_ACOES", Acao), ("_ENTIDADES", Entidade)],
)
def test_o_vocabulario_bate_com_o_check_da_migration(constante: str, enum: type) -> None:
    """Valor novo no enum sem migration seria recusado pelo banco no primeiro INSERT."""
    assert set(_tupla_da_migracao(constante)) == {membro.value for membro in enum}
```

`tests/integration/test_trilha_de_auditoria.py`:

```python
"""A garantia da trilha no banco. TEC-206, D1, D2 e D3 do desenho.

**SQL cru de proposito** nos testes de UPDATE e DELETE: a regra mora no
trigger, e o que se prova e que ela vale fora do ORM -- para um script, para
uma migration errada, para qualquer caminho da aplicacao.

Tempo comparado sempre pelo relogio do BANCO: medido em 25/09/2026, o
Postgres local estava um ano atras do host.
"""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.registro import Origem, registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Ator, AtorTipo, Entidade

CANAL = "whatsapp"
TELEFONE = "5511911112222"

_INSERIR_CRU = text(
    "INSERT INTO eventos_auditoria (id, criado_em, ator_tipo, ator_id, acao, entidade, "
    "entidade_id) VALUES (:id, clock_timestamp() - interval '2 years', :ator_tipo, :ator_id, "
    ":acao, 'handoff', 'h')"
)


async def _um_evento(session: AsyncSession) -> uuid.UUID:
    evento_id = await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.HANDOFF_CRIADO,
        entidade=Entidade.HANDOFF,
        entidade_id=str(uuid.uuid4()),
        lead=(CANAL, TELEFONE),
        detalhes={"gatilho": "LEAD_QUENTE"},
    )
    await session.commit()
    return evento_id


async def _total(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(EventoAuditoria)) or 0


async def test_registrar_nao_commita(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O molde de `registrar_recalculo`: a sessao e emprestada, o commit e de quem chama."""
    await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.HANDOFF_CRIADO,
        entidade=Entidade.HANDOFF,
        entidade_id="h",
    )
    async with session_factory() as outra:
        assert await _total(outra) == 0

    await session.rollback()
    assert await _total(session) == 0


async def test_a_linha_guarda_o_lead_ref_e_nao_o_telefone(session: AsyncSession) -> None:
    evento_id = await _um_evento(session)

    linha = (
        (
            await session.execute(
                text("SELECT * FROM eventos_auditoria WHERE id = :id"), {"id": evento_id}
            )
        )
        .mappings()
        .one()
    )

    assert linha["lead_ref"] == lead_ref(
        CANAL, TELEFONE, chave=get_settings().auditoria_chave_do_lead
    )
    assert all(TELEFONE not in str(valor) for valor in linha.values())
    assert linha["detalhes"] == {"gatilho": "LEAD_QUENTE"}
    assert linha["ip"] is None
    assert linha["correlation_id"] is None


async def test_a_origem_vai_para_ip_e_correlation_id(session: AsyncSession) -> None:
    evento_id = await registrar_evento(
        session,
        ator=Ator(AtorTipo.USUARIO, "usuario-1"),
        acao=Acao.ACESSO_NEGADO,
        entidade=Entidade.ROTA,
        entidade_id="/api/v1/corretores",
        origem=Origem(ip="10.0.0.1", correlation_id="req-1"),
    )
    await session.commit()

    linha = (
        await session.execute(
            select(EventoAuditoria.ip, EventoAuditoria.correlation_id, EventoAuditoria.ator_id)
            .where(EventoAuditoria.id == evento_id)
        )
    ).one()
    assert str(linha.ip) == "10.0.0.1"
    assert linha.correlation_id == "req-1"
    assert linha.ator_id == "usuario-1"


async def test_update_e_recusado(session: AsyncSession) -> None:
    await _um_evento(session)

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE eventos_auditoria SET campo = 'resumo'"))
    await session.rollback()


async def test_delete_de_linha_recente_e_recusado_mesmo_por_sql_cru(session: AsyncSession) -> None:
    await _um_evento(session)

    with pytest.raises(DBAPIError, match="12 meses"):
        await session.execute(text("DELETE FROM eventos_auditoria"))
    await session.rollback()

    assert await _total(session) == 1


async def test_criado_em_antedatado_e_sobrescrito_pelo_relogio_do_banco(
    session: AsyncSession,
) -> None:
    """Sem o trigger de insercao, antedatar e apagar em seguida furaria os 12 meses."""
    await session.execute(
        _INSERIR_CRU,
        {"id": uuid.uuid4(), "ator_tipo": "SISTEMA", "ator_id": None, "acao": "HANDOFF_CRIADO"},
    )
    await session.commit()

    recente = await session.scalar(
        text("SELECT criado_em > clock_timestamp() - interval '1 minute' FROM eventos_auditoria")
    )
    assert recente is True


async def test_acao_fora_do_vocabulario_e_recusada(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="ck_eventos_auditoria_acao"):
        await session.execute(
            _INSERIR_CRU,
            {"id": uuid.uuid4(), "ator_tipo": "SISTEMA", "ator_id": None, "acao": "APAGOU_TUDO"},
        )
    await session.rollback()


async def test_usuario_sem_id_e_recusado_pelo_banco(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="ck_eventos_auditoria_ator_id"):
        await session.execute(
            _INSERIR_CRU,
            {"id": uuid.uuid4(), "ator_tipo": "USUARIO", "ator_id": None, "acao": "ACESSO_NEGADO"},
        )
    await session.rollback()


async def test_detalhes_com_chave_livre_nao_chega_ao_banco(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="motivo_livre"):
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REATIVADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id="x",
            detalhes={"motivo_livre": "lead pediu por telefone"},
        )
    assert await _total(session) == 0
```

Append to `tests/integration/test_migrations.py`:

```python
async def test_a_0048_desce_e_sobe_de_novo() -> None:
    """A tabela e as duas funcoes somem no downgrade e voltam no upgrade.

    Mesma razao da 0012: triggers e funcoes nascem de `op.execute`, entao nada
    garante que o downgrade as derrube -- uma funcao orfa faria o upgrade
    seguinte reprovar com "function already exists".
    """
    await dispose_engine()
    alembic("downgrade", "0047")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(text("SELECT to_regclass('public.eventos_auditoria')")) is None
            )
            assert (
                await sessao.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE proname IN "
                        "('eventos_auditoria_carimba', 'eventos_auditoria_protege')"
                    )
                )
                == 0
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                    "('eventos_auditoria_carimbo', 'eventos_auditoria_imutavel')"
                )
            )
            == 2
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/integration/test_trilha_de_auditoria.py -v --tb=short`
Expected: FAIL — `FileNotFoundError` for `0048_eventos_auditoria.py` and `ModuleNotFoundError: No module named 'mobia.domain.auditoria.models'`.

- [ ] **Step 3: The migration**

`alembic/versions/0048_eventos_auditoria.py`:

```python
"""a trilha de auditoria imutavel

TEC-206, RNF-18. Uma tabela so de acrescimo para "quem acessou ou alterou o
que, quando e de onde", sem o dado pessoal em claro.

**Dois triggers, e o segundo vai alem dos da 0012 e da 0035.** Aqueles recusam
so UPDATE; este recusa UPDATE sempre e DELETE de linha com menos de 12 meses,
porque a exclusao legitima passou a ter regra (D6 do desenho): 12 meses e o
maximo, e o job `sweep_retencao_auditoria` apaga o que passou. O job nao
decide o que pode ser apagado -- este trigger confere linha por linha.

**O de insercao carimba `criado_em` com `clock_timestamp()`, qualquer que seja
o valor enviado.** Sem ele a regra dos 12 meses tem um furo: inserir uma linha
datada de dois anos atras e apaga-la em seguida. `clock_timestamp()` e nao
`now()` pelo argumento que a 0012 escreve por extenso.

**Limites, declarados.** TRUNCATE nao e bloqueado -- `banco_limpo` trunca
todas as tabelas antes de cada teste de integracao. E o dono da tabela pode
remover o trigger: a aplicacao conecta como dono, e a garantia e contra a
aplicacao, nao contra o operador do banco.

Sem FK para as entidades: o registro sobrevive a exclusao do que descreve, que
e o motivo de ele existir.

Os vocabularios abaixo sao COPIA literal dos enums de
`domain/auditoria/vocabulario.py`, e nao import: migration aplicada nao muda
quando o codigo muda. `tests/unit/test_auditoria_vocabulario.py` prende as
duas copias.

Revision ID: 0048
Revises: 0047
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

_ATORES = ("USUARIO", "AGENTE", "SISTEMA")
_ACOES = (
    "DADO_PESSOAL_ACESSADO",
    "QUALIFICACAO_ALTERADA",
    "HANDOFF_CRIADO",
    "OPTOUT_REGISTRADO",
    "OPTOUT_REATIVADO",
    "PROMPT_PUBLICADO",
    "ACESSO_NEGADO",
)
_ENTIDADES = ("handoff", "optout_event", "rota", "lead_qualification", "configuracao_agente")

_FUNCAO_DO_CARIMBO = """
CREATE FUNCTION eventos_auditoria_carimba() RETURNS trigger AS $$
BEGIN
    NEW.criado_em := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER_DO_CARIMBO = """
CREATE TRIGGER eventos_auditoria_carimbo
    BEFORE INSERT ON eventos_auditoria
    FOR EACH ROW EXECUTE FUNCTION eventos_auditoria_carimba()
"""

_FUNCAO_DA_PROTECAO = """
CREATE FUNCTION eventos_auditoria_protege() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'eventos_auditoria e imutavel: UPDATE recusado (RNF-18)';
    END IF;
    IF OLD.criado_em >= clock_timestamp() - interval '12 months' THEN
        RAISE EXCEPTION
            'eventos_auditoria: DELETE recusado, o registro tem menos de 12 meses (RNF-18)';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER_DA_PROTECAO = """
CREATE TRIGGER eventos_auditoria_imutavel
    BEFORE UPDATE OR DELETE ON eventos_auditoria
    FOR EACH ROW EXECUTE FUNCTION eventos_auditoria_protege()
"""


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.create_table(
        "eventos_auditoria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("ator_tipo", sa.String(16), nullable=False),
        sa.Column("ator_id", sa.String(64), nullable=True),
        sa.Column("acao", sa.String(32), nullable=False),
        sa.Column("entidade", sa.String(32), nullable=False),
        sa.Column("entidade_id", sa.String(200), nullable=False),
        sa.Column("campo", sa.String(32), nullable=True),
        sa.Column("lead_ref", sa.CHAR(64), nullable=True),
        sa.Column("detalhes", postgresql.JSONB(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("correlation_id", sa.String(200), nullable=True),
        sa.CheckConstraint(_em("ator_tipo", _ATORES), name="ck_eventos_auditoria_ator_tipo"),
        sa.CheckConstraint(_em("acao", _ACOES), name="ck_eventos_auditoria_acao"),
        sa.CheckConstraint(_em("entidade", _ENTIDADES), name="ck_eventos_auditoria_entidade"),
        sa.CheckConstraint(
            "(ator_tipo = 'USUARIO') = (ator_id IS NOT NULL)",
            name="ck_eventos_auditoria_ator_id",
        ),
    )
    # A paginacao da TEC-343 e a retencao. `id DESC` tambem, para que
    # `ORDER BY criado_em DESC, id DESC` e o cursor usem este indice inteiro.
    op.create_index(
        "ix_eventos_auditoria_pagina",
        "eventos_auditoria",
        [sa.text("criado_em DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_eventos_auditoria_ator", "eventos_auditoria", ["ator_id", sa.text("criado_em DESC")]
    )
    op.create_index(
        "ix_eventos_auditoria_acao", "eventos_auditoria", ["acao", sa.text("criado_em DESC")]
    )
    op.create_index(
        "ix_eventos_auditoria_lead", "eventos_auditoria", ["lead_ref", sa.text("criado_em DESC")]
    )
    op.execute(_FUNCAO_DO_CARIMBO)
    op.execute(_TRIGGER_DO_CARIMBO)
    op.execute(_FUNCAO_DA_PROTECAO)
    op.execute(_TRIGGER_DA_PROTECAO)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS eventos_auditoria_imutavel ON eventos_auditoria")
    op.execute("DROP TRIGGER IF EXISTS eventos_auditoria_carimbo ON eventos_auditoria")
    op.execute("DROP FUNCTION IF EXISTS eventos_auditoria_protege()")
    op.execute("DROP FUNCTION IF EXISTS eventos_auditoria_carimba()")
    op.drop_index("ix_eventos_auditoria_lead", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_acao", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_ator", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_pagina", table_name="eventos_auditoria")
    op.drop_table("eventos_auditoria")
```

- [ ] **Step 4: The model and `registrar_evento`**

`src/mobia/domain/auditoria/models.py`:

```python
"""A linha da trilha de auditoria. TEC-206, D2 do desenho.

O `EventoAuditoria` da secao 5.1 do SRS com tres diferencas: entram `campo`,
`lead_ref` e `correlation_id`; saem `dados_antes` e `dados_depois` -- para
qualificacao e dado pessoal, o antes e o depois SAO o dado pessoal que a card
proibe guardar em claro. Ver a Emenda E-01 ao `EventoAuditoria`.

CHECKs, indices e os dois triggers moram na migration 0048, escrita a mao, e
nao aqui: o modelo so serve ao ORM.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class EventoAuditoria(Base):
    __tablename__ = "eventos_auditoria"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O valor enviado e sempre descartado: o trigger `eventos_auditoria_carimbo`
    # o sobrescreve com `clock_timestamp()`. O `server_default` so poupa o ORM
    # de mandar um valor que nao vale nada.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    ator_tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    # `usuario_id` de pessoa, `token-compartilhado` pelo `X-Admin-Token`, nulo
    # para agente e sistema -- o par e conferido por `ck_eventos_auditoria_ator_id`.
    ator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    acao: Mapped[str] = mapped_column(String(32), nullable=False)
    entidade: Mapped[str] = mapped_column(String(32), nullable=False)
    # O uuid da entidade, ou o template da rota numa negativa.
    entidade_id: Mapped[str] = mapped_column(String(200), nullable=False)
    campo: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # HMAC do par do lead -- ver `auditoria/referencia.py`. Nunca o telefone.
    lead_ref: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    # So metadado fechado, montado por `auditoria/vocabulario.py` (D5).
    detalhes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Na escrita vai texto; na leitura o asyncpg devolve `ipaddress.IPv4Address`
    # ou `IPv6Address`, e quem serializa faz `str()`.
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    # O id da requisicao (TEC-368), que liga o registro ao log de aplicacao.
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

`src/mobia/domain/auditoria/registro.py`:

```python
"""A escrita da trilha de auditoria. TEC-206, D1 do desenho.

**Escrita explicita, e nao trigger nas tabelas de origem.** O banco nao
conhece o usuario, o IP nem o `correlation_id`, e trigger nao ve leitura --
que e metade do que se audita. O custo: todo caminho auditado precisa de uma
linha de codigo, e um caminho novo que a esqueca nao e auditado. A defesa e um
teste por evento, nao um mecanismo implicito.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade, validar_detalhes


@dataclass(frozen=True)
class Origem:
    """De onde veio uma requisicao HTTP. Agente e sistema nao tem origem.

    Montada por `api/middleware.py::origem_da_requisicao`. O opt-out chega
    pelo webhook, e o IP ali e o da Meta, nao o do lead -- grava-lo seria
    afirmar uma origem falsa, e por isso os escritores do dominio nao passam
    origem nenhuma.
    """

    ip: str | None
    correlation_id: str | None


async def registrar_evento(
    session: AsyncSession,
    *,
    ator: Ator,
    acao: Acao,
    entidade: Entidade,
    entidade_id: str,
    campo: str | None = None,
    lead: tuple[str, str] | None = None,
    detalhes: Mapping[str, str | None] | None = None,
    origem: Origem | None = None,
) -> uuid.UUID:
    """Acrescenta o evento a sessao de quem chama. **Nao commita.**

    O molde de `registrar_recalculo`: numa operacao de escrita, o evento e a
    operacao commitam juntos ou nenhum dos dois -- nao ha handoff sem
    registro, nem registro de handoff desfeito. Nas leituras, quem chama abre
    uma sessao curta e commita antes de a resposta sair.

    Flush e nao so `add`: um CHECK violado estoura aqui, no ponto da chamada,
    e nao num commit distante que ja nao diz de onde veio a linha.

    `lead` e o par `(channel, conversation_key)`; o que vai para a linha e o
    `lead_ref`, e nenhum chamador lida com o HMAC.
    """
    evento_id = uuid.uuid4()
    session.add(
        EventoAuditoria(
            id=evento_id,
            ator_tipo=ator.tipo.value,
            ator_id=ator.id,
            acao=acao.value,
            entidade=entidade.value,
            entidade_id=entidade_id,
            campo=campo,
            lead_ref=(
                lead_ref(lead[0], lead[1], chave=get_settings().auditoria_chave_do_lead)
                if lead is not None
                else None
            ),
            detalhes=validar_detalhes(detalhes) if detalhes is not None else None,
            ip=origem.ip if origem is not None else None,
            correlation_id=origem.correlation_id if origem is not None else None,
        )
    )
    await session.flush()
    return evento_id
```

In `tests/conftest.py`, append to `TABELAS` (after `"agendamentos"`):

```python
    # TEC-206. Append-only como `lead_score_audit`, e nada a apaga em producao
    # antes de 12 meses: sem o truncate, o registro de um teste vira trilha do
    # proximo. TRUNCATE nao dispara os triggers de linha da 0048 -- e por isso
    # a D3 do desenho nao o bloqueia.
    "eventos_auditoria",
```

In the `banco_limpo` docstring, replace `(\`ACCESS EXCLUSIVE\` em 19 tabelas)` with `(\`ACCESS EXCLUSIVE\` em toda tabela de \`TABELAS\`)` — the number was already stale (23 before this card).

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/unit/test_uma_cabeca_de_migration.py tests/integration/test_trilha_de_auditoria.py -v --tb=short`
Expected: PASS.

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py::test_a_0048_desce_e_sobe_de_novo -v --tb=short`
Expected: PASS (slow: each alembic call is a new process).

If dozens of tests fail with `relation "eventos_auditoria" does not exist` under `-n`, read CLAUDE.md "`relation ... does not exist` em dezenas de testes" before touching code.

- [ ] **Step 6: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0048_eventos_auditoria.py src/mobia/domain/auditoria/models.py src/mobia/domain/auditoria/registro.py tests/conftest.py tests/unit/test_auditoria_vocabulario.py tests/integration/test_trilha_de_auditoria.py tests/integration/test_migrations.py
git commit -m "feat(TEC-206): a trilha de auditoria recusa UPDATE e DELETE antes de 12 meses no banco

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A retenção de 12 meses e o cron

**Files:**
- Create: `src/mobia/domain/auditoria/retencao.py`
- Create: `src/mobia/workers/jobs/sweep_retencao_auditoria.py`
- Modify: `src/mobia/workers/main.py` (`functions` e `cron_jobs`)
- Modify: `tests/integration/test_worker_startup.py` (registro do cron)
- Test: `tests/integration/test_retencao_da_auditoria.py`

**Interfaces:**
- Consumes: tabela `eventos_auditoria` e o trigger `eventos_auditoria_imutavel` (Task 2); `ctx["session_factory"]` (já preenchido por `workers/main.py::startup`, como o `sweep_conversas_inativas` usa).
- Produces:
  - `async def retencao.apagar_vencidos(session_factory: async_sessionmaker[AsyncSession], *, lote: int = LOTE_PADRAO) -> int`; `LOTE_PADRAO = 1000`; log `auditoria.retencao_executada` com `apagadas`
  - `SWEEP_RETENCAO_AUDITORIA_JOB = "sweep_retencao_auditoria"`; `async def sweep_retencao_auditoria(ctx: dict[str, Any], lote: int = LOTE_PADRAO) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_retencao_da_auditoria.py`:

```python
"""A retencao da trilha: 11 meses fica, 13 meses sai. TEC-206, D6.

**Para antedatar, o teste desliga SO o trigger de insercao**, e so dentro da
propria transacao -- o DDL do Postgres e transacional, entao nenhuma outra
sessao ve o trigger desligado. O de UPDATE/DELETE continua ligado o tempo
todo, e e ele que estes testes exercitam: a retencao so passa porque as
linhas tem mais de 12 meses pelo relogio do BANCO.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.retencao import apagar_vencidos
from mobia.workers.jobs.sweep_retencao_auditoria import sweep_retencao_auditoria
from tests.conftest import eventos_de_log


async def _semear(session: AsyncSession, *, meses: int) -> uuid.UUID:
    evento_id = uuid.uuid4()
    await session.execute(
        text("ALTER TABLE eventos_auditoria DISABLE TRIGGER eventos_auditoria_carimbo")
    )
    await session.execute(
        text(
            "INSERT INTO eventos_auditoria (id, criado_em, ator_tipo, acao, entidade, "
            "entidade_id) VALUES (:id, clock_timestamp() - make_interval(months => :meses), "
            "'SISTEMA', 'HANDOFF_CRIADO', 'handoff', 'h')"
        ),
        {"id": evento_id, "meses": meses},
    )
    await session.execute(
        text("ALTER TABLE eventos_auditoria ENABLE TRIGGER eventos_auditoria_carimbo")
    )
    await session.commit()
    return evento_id


async def _ids(session: AsyncSession) -> set[uuid.UUID]:
    return set((await session.execute(select(EventoAuditoria.id))).scalars())


async def test_onze_meses_fica_e_treze_meses_sai(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    onze = await _semear(session, meses=11)
    await _semear(session, meses=13)

    apagadas = await apagar_vencidos(session_factory)

    assert apagadas == 1
    assert await _ids(session) == {onze}


async def test_o_trigger_continua_recusando_a_linha_de_onze_meses(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Prova que a retencao acima nao passou por o trigger estar desligado."""
    onze = await _semear(session, meses=11)

    with pytest.raises(DBAPIError, match="12 meses"):
        await session.execute(text("DELETE FROM eventos_auditoria WHERE id = :id"), {"id": onze})
    await session.rollback()


async def test_mais_vencidas_que_um_lote_saem_todas(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Review Focus 3: o laco de lotes termina e nao deixa vencida para tras."""
    onze = await _semear(session, meses=11)
    for _ in range(3):
        await _semear(session, meses=13)

    apagadas = await apagar_vencidos(session_factory, lote=1)

    assert apagadas == 3
    assert await _ids(session) == {onze}


async def test_lote_menor_que_um_e_recusado(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Com LIMIT 0 o laco nunca terminaria."""
    with pytest.raises(ValueError, match="lote"):
        await apagar_vencidos(session_factory, lote=0)


async def test_o_job_apaga_e_emite_a_contagem(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], caplog: Any
) -> None:
    await _semear(session, meses=13)

    with caplog.at_level("INFO"):
        apagadas = await sweep_retencao_auditoria({"session_factory": session_factory})

    assert apagadas == 1
    ((_, evento),) = eventos_de_log(caplog, "auditoria.retencao_executada")
    assert evento["apagadas"] == 1


async def test_sem_nada_vencido_nao_apaga_nada(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    onze = await _semear(session, meses=11)

    assert await apagar_vencidos(session_factory) == 0
    assert await _ids(session) == {onze}
```

Append to `tests/integration/test_worker_startup.py`:

```python
def test_sweep_retencao_auditoria_esta_registrado_no_cron_das_quatro() -> None:
    """TEC-206, D6. Sem este teste, apagar a entrada `cron(...)` nao quebra nada:
    os testes de `test_retencao_da_auditoria.py` chamam a funcao direto, e a
    trilha passaria a crescer para sempre -- que e o contrario do maximo de 12
    meses. Uma hora depois do `sweep_conversas_inativas`."""
    from mobia.workers.jobs.sweep_retencao_auditoria import (
        SWEEP_RETENCAO_AUDITORIA_JOB,
        sweep_retencao_auditoria,
    )
    from mobia.workers.main import WorkerSettings

    registrada = next(
        f
        for f in WorkerSettings.functions
        if getattr(f, "name", None) == SWEEP_RETENCAO_AUDITORIA_JOB
    )
    assert registrada.keep_result_s == 0

    candidatos = [
        job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_retencao_auditoria
    ]
    assert len(candidatos) == 1
    assert candidatos[0].hour == {4}
    assert candidatos[0].minute == {0}
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_retencao_da_auditoria.py "tests/integration/test_worker_startup.py::test_sweep_retencao_auditoria_esta_registrado_no_cron_das_quatro" -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.auditoria.retencao'`.

- [ ] **Step 3: Implement**

`src/mobia/domain/auditoria/retencao.py`:

```python
"""A retencao da trilha de auditoria: 12 meses e o maximo. TEC-206, D6.

Decidido em conversa em 25/09/2026: como os prazos da RNF-22, e nao como
piso. Uma trilha que sobrevive a transcricao que ela referencia guarda
referencia a um dado que ja nao existe.

**Esta funcao nao decide o que pode ser apagado.** Ela pede as linhas com mais
de 12 meses, e o trigger `eventos_auditoria_imutavel` (migration 0048) confere
linha por linha: um erro no corte daqui esbarra nele e reprova, em vez de
apagar historico recente. "12 meses" e `interval '12 months'` sobre o relogio
do banco -- a mesma definicao do trigger, e nao o `datetime.now()` do worker.
Como o relogio do banco so anda para frente, o corte do trigger, calculado
depois, e sempre mais novo que o desta consulta.
"""

import typing
from typing import Any

import structlog
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

LOTE_PADRAO = 1000

_APAGAR_UM_LOTE = text(
    """
    DELETE FROM eventos_auditoria
    WHERE id IN (
        SELECT id FROM eventos_auditoria
        WHERE criado_em < clock_timestamp() - interval '12 months'
        ORDER BY criado_em
        LIMIT :lote
    )
    """
)


async def apagar_vencidos(
    session_factory: async_sessionmaker[AsyncSession], *, lote: int = LOTE_PADRAO
) -> int:
    """Apaga, lote a lote, o que passou de 12 meses. Devolve quantas linhas.

    Commit por lote: a primeira passagem numa base antiga pode ter milhoes de
    linhas, e um DELETE unico seguraria lock sobre todas ate o fim. O laco
    para no primeiro lote incompleto.
    """
    if lote < 1:
        raise ValueError(f"lote tem de ser positivo: {lote}")
    total = 0
    while True:
        async with session_factory() as session:
            # `CursorResult` porque a tipagem do SQLAlchemy declara o Result
            # generico, sem `rowcount` -- mesmo `cast` de `context/repositorio.py`.
            resultado = typing.cast(
                CursorResult[Any], await session.execute(_APAGAR_UM_LOTE, {"lote": lote})
            )
            await session.commit()
        total += resultado.rowcount
        if resultado.rowcount < lote:
            break
    log.info("auditoria.retencao_executada", apagadas=total)
    return total
```

`src/mobia/workers/jobs/sweep_retencao_auditoria.py`:

```python
"""O job que apaga a trilha de auditoria com mais de 12 meses. TEC-206, D6."""

from typing import Any

from mobia.domain.auditoria.retencao import LOTE_PADRAO, apagar_vencidos

SWEEP_RETENCAO_AUDITORIA_JOB = "sweep_retencao_auditoria"


async def sweep_retencao_auditoria(ctx: dict[str, Any], lote: int = LOTE_PADRAO) -> int:
    """Fino de proposito, como `sweep_conversas_inativas`.

    O rastro da passagem e a linha `auditoria.retencao_executada`, emitida por
    `apagar_vencidos` com a contagem -- e nao este numero de retorno, que o
    ARQ descarta (`keep_result=0`).
    """
    return await apagar_vencidos(ctx["session_factory"], lote=lote)
```

In `src/mobia/workers/main.py`:

1. Import next to the other jobs: `from mobia.workers.jobs.sweep_retencao_auditoria import sweep_retencao_auditoria`.
2. In `WorkerSettings.functions`, right after `func(sweep_conversas_inativas, keep_result=0),`:

```python
        # TEC-206. `keep_result=0` pela mesma razao do `sweep_sla`: o resultado
        # (um `int`) nao serve para nada depois que o log saiu. Entra em
        # `cron_jobs` tambem -- e o relogio que dispara este job.
        func(sweep_retencao_auditoria, keep_result=0),
```

3. In `WorkerSettings.cron_jobs`, right after the `sweep_conversas_inativas` entry:

```python
        # TEC-206, D6. **Uma vez por dia, as 4h** -- uma hora depois do
        # `sweep_conversas_inativas`, para as duas varreduras diarias nao
        # disputarem a mesma janela ociosa. A regra e de DOZE MESES: uma
        # passagem perdida deixa uma linha viva um dia a mais, e quem impede
        # apagar historico recente e o trigger da 0048, nao este horario.
        cron(sweep_retencao_auditoria, hour={4}, minute={0}, run_at_startup=False),
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_retencao_da_auditoria.py tests/integration/test_worker_startup.py tests/integration/test_queue.py -v --tb=short`
Expected: PASS.

- [ ] **Step 5: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/auditoria/retencao.py src/mobia/workers/jobs/sweep_retencao_auditoria.py src/mobia/workers/main.py tests/integration/test_retencao_da_auditoria.py tests/integration/test_worker_startup.py
git commit -m "feat(TEC-206): a trilha de auditoria e apagada depois de 12 meses por um cron diario

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Handoff, opt-out e reativação gravam o seu registro

**Files:**
- Modify: `src/mobia/domain/handoff/repositorio.py` (`registrar_handoff` ganha `ator`)
- Modify: `src/mobia/domain/agente/turno.py` (os cinco sítios de `registrar_handoff`: `ator=ATOR_AGENTE`)
- Modify: `src/mobia/workers/jobs/process_message.py` (`_encaminhar_por_erro`: `ator=ATOR_SISTEMA`)
- Modify: `src/mobia/domain/optout/repositorio.py` (`registrar_optout`, `reativar` e a docstring do módulo)
- Modify (test call sites of `registrar_handoff`, `ator=ATOR_AGENTE`): `tests/conftest.py` (fixtures `semear_lead_completo` e `semear_handoff_com_resumo`), `tests/integration/test_handoff_dossie_do_banco.py`, `tests/integration/test_handoff_schema.py`, `tests/integration/test_handoff_repositorio.py`, `tests/integration/test_exportacao_para_crm.py`, `tests/integration/test_notificacao_destinatario.py`, `tests/integration/test_pedido_de_humano.py`, `tests/integration/test_recuperacao_sem_prazo.py`, `tests/integration/test_um_handoff_por_conversa.py`
- Modify: `tests/integration/test_handoff_no_turno.py`, `tests/integration/test_handoff_por_erro.py` (o ator de cada sítio)
- Test: `tests/integration/test_auditoria_dos_eventos.py`

**Interfaces:**
- Consumes: `registrar_evento`, `Origem` (Task 2); `ATOR_AGENTE`, `ATOR_SISTEMA`, `Ator`, `Acao`, `Entidade`, `detalhes_do_handoff` (Task 1).
- Produces: `async def registrar_handoff(session: AsyncSession, *, channel: str, conversation_key: str, gatilho: Gatilho, ator: Ator) -> HandoffRegistrado` — grava `HANDOFF_CRIADO` só quando `criado`. `registrar_optout` e `reativar` mantêm a assinatura e passam a gravar `OPTOUT_REGISTRADO` / `OPTOUT_REATIVADO` com `entidade_id` = id da linha de `optout_events`.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_auditoria_dos_eventos.py`:

```python
"""Um teste por evento auditado do dominio. TEC-206, D7 do desenho.

A escrita e explicita (D1), e um caminho novo que a esqueca nao e auditado --
e por isso cada escritor tem o seu teste aqui. O acesso ao resumo e a negativa
estao em `test_rota_de_resumo.py` e `test_autorizacao_por_papel.py`.
"""

import asyncio
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.admin.reativar import _executar
from mobia.domain.auditoria.vocabulario import ATOR_AGENTE, ATOR_SISTEMA
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.optout.models import EVENTO_REATIVACAO, OptoutEvent
from mobia.domain.optout.repositorio import reativar, registrar_optout

CANAL = "whatsapp"
TELEFONE = "5511911112222"
MOTIVO = "lead pediu por telefone ao Paulo"


async def _eventos(session: AsyncSession, acao: str) -> list[dict]:
    resultado = await session.execute(
        text("SELECT * FROM eventos_auditoria WHERE acao = :acao ORDER BY criado_em"),
        {"acao": acao},
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_handoff_criado_grava_um_registro(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=TELEFONE,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    (evento,) = await _eventos(session, "HANDOFF_CRIADO")
    assert evento["ator_tipo"] == "AGENTE"
    assert evento["ator_id"] is None
    assert evento["entidade"] == "handoff"
    assert evento["entidade_id"] == str(registro.id)
    assert evento["detalhes"] == {"gatilho": "LEAD_QUENTE"}
    assert evento["lead_ref"] is not None
    assert evento["ip"] is None
    assert evento["correlation_id"] is None


async def test_acumular_gatilho_num_handoff_aberto_nao_grava(session: AsyncSession) -> None:
    await registrar_handoff(
        session, channel=CANAL, conversation_key=TELEFONE, gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    segundo = await registrar_handoff(
        session, channel=CANAL, conversation_key=TELEFONE, gatilho=Gatilho.VENDA_IMOVEL,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert segundo.criado is False
    assert len(await _eventos(session, "HANDOFF_CRIADO")) == 1


async def test_rollback_do_handoff_leva_o_registro_junto(session: AsyncSession) -> None:
    """Nao ha registro de handoff desfeito."""
    await registrar_handoff(
        session, channel=CANAL, conversation_key=TELEFONE, gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.rollback()

    assert await session.scalar(text("SELECT count(*) FROM handoffs")) == 0
    assert await _eventos(session, "HANDOFF_CRIADO") == []


async def test_corrida_de_dois_turnos_grava_um_registro_so(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Review Focus 2: quem arbitra e o `ON CONFLICT`, e so o vencedor e criacao."""

    async def escrever(gatilho: Gatilho) -> None:
        async with session_factory() as propria:
            await registrar_handoff(
                propria, channel=CANAL, conversation_key=TELEFONE, gatilho=gatilho,
                ator=ATOR_AGENTE,
            )
            await propria.commit()

    await asyncio.gather(escrever(Gatilho.LEAD_QUENTE), escrever(Gatilho.VENDA_IMOVEL))

    assert len(await _eventos(session, "HANDOFF_CRIADO")) == 1


async def test_optout_grava_o_seu(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=TELEFONE, message_id=uuid.uuid4()
    )

    (evento,) = await _eventos(session, "OPTOUT_REGISTRADO")
    linha = (await session.execute(select(OptoutEvent))).scalar_one()
    assert evento["ator_tipo"] == ATOR_SISTEMA.tipo.value
    assert evento["entidade"] == "optout_event"
    assert evento["entidade_id"] == str(linha.id)
    assert evento["ip"] is None


async def test_reativacao_grava_o_seu_e_nao_copia_o_motivo(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """D5: o motivo digitado fica em `optout_events`, e o registro aponta para ele."""
    await reativar(
        session_factory, channel=CANAL, conversation_key=TELEFONE, autor="Paulo M.", motivo=MOTIVO
    )

    (evento,) = await _eventos(session, "OPTOUT_REATIVADO")
    linha = (
        await session.execute(select(OptoutEvent).where(OptoutEvent.evento == EVENTO_REATIVACAO))
    ).scalar_one()
    assert evento["entidade_id"] == str(linha.id)
    assert evento["ator_tipo"] == "SISTEMA"
    assert all(MOTIVO not in str(valor) and "Paulo" not in str(valor) for valor in evento.values())


async def test_a_reativacao_pela_cli_tambem_grava(session: AsyncSession) -> None:
    await _executar(channel=CANAL, key=TELEFONE, autor="Paulo M.", motivo=MOTIVO)

    assert len(await _eventos(session, "OPTOUT_REATIVADO")) == 1
```

(`ruff format` will reflow the multi-argument calls above; accept its output.)

Append to `tests/integration/test_handoff_no_turno.py`:

```python
async def test_o_handoff_do_turno_e_registrado_como_do_agente(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """TEC-206, D7: cada sitio de `registrar_handoff` declara o seu ator; no turno, AGENTE."""
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    resultado = await session.execute(
        text(
            "SELECT ator_tipo, ator_id, detalhes FROM eventos_auditoria "
            "WHERE acao = 'HANDOFF_CRIADO'"
        )
    )
    assert [dict(linha) for linha in resultado.mappings()] == [
        {"ator_tipo": "AGENTE", "ator_id": None, "detalhes": {"gatilho": "VENDA_IMOVEL"}}
    ]
```

In `tests/integration/test_handoff_por_erro.py::test_falha_que_atinge_o_teto_cria_handoff`, append after the last assertion:

```python
    # TEC-206, D7: o handoff por erro nasce fora do turno, em `process_message`,
    # e o ator declarado ali e SISTEMA.
    ator = await session.scalar(
        text("SELECT ator_tipo FROM eventos_auditoria WHERE acao = 'HANDOFF_CRIADO'")
    )
    assert ator == "SISTEMA"
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_dos_eventos.py -v --tb=short`
Expected: FAIL with `TypeError: registrar_handoff() got an unexpected keyword argument 'ator'` and, on the opt-out tests, `ValueError: not enough values to unpack` (no audit row yet).

- [ ] **Step 3: `registrar_handoff`**

In `src/mobia/domain/handoff/repositorio.py`, add imports:

```python
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade, detalhes_do_handoff
```

Change the signature to add `ator: Ator` after `gatilho: Gatilho`, and add to the docstring, after the paragraph that ends "...que a card existe para impedir.":

```
    **E grava `HANDOFF_CRIADO` na trilha de auditoria, na mesma sessao, so
    quando `criado`** (TEC-206, D7). Acumular gatilho num handoff aberto nao
    e criacao. Como a funcao nao commita, o registro e o handoff entram ou
    saem juntos -- nao ha handoff sem registro, nem registro de handoff
    desfeito. `ator` e obrigatorio e sem default: cada sitio de chamada
    declara o seu (AGENTE no turno, SISTEMA em `process_message`), e um
    default faria o sitio novo herdar um ator que nao e o dele.
```

Replace the last two lines of the function (`linha = resultado.one()` / `return HandoffRegistrado(...)`) with:

```python
    linha = resultado.one()
    if linha.inseriu:
        await registrar_evento(
            session,
            ator=ator,
            acao=Acao.HANDOFF_CRIADO,
            entidade=Entidade.HANDOFF,
            entidade_id=str(linha.id),
            lead=(channel, conversation_key),
            detalhes=detalhes_do_handoff(gatilho),
        )
    return HandoffRegistrado(id=linha.id, criado=linha.inseriu)
```

The existing comment above `linha = resultado.one()` ("Nao loga aqui: esta funcao nao commita...") stays true: the audit row is inside the caller's transaction, which is exactly what the log cannot be.

- [ ] **Step 4: Every caller declares its ator**

`src/mobia/domain/agente/turno.py`: add `from mobia.domain.auditoria.vocabulario import ATOR_AGENTE` (alphabetical position among the `mobia.domain` imports) and add `ator=ATOR_AGENTE,` as the last keyword of each of the five `registrar_handoff(` calls (`handoff_do_pedido`, `handoff_do_quente`, `handoff_da_intencao`, `handoff_do_teto`, `handoff_da_entrega`).

`src/mobia/workers/jobs/process_message.py`: add `from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA` and, in `_encaminhar_por_erro`, `ator=ATOR_SISTEMA,` after `gatilho=Gatilho.ERRO_DO_AGENTE,`.

Every test call site in the files listed above: add `ator=ATOR_AGENTE` as the last keyword, and `from mobia.domain.auditoria.vocabulario import ATOR_AGENTE` to the file's imports. For one-line calls such as the one in `semear_handoff_com_resumo`, append `, ator=ATOR_AGENTE` before the closing parenthesis and let `ruff format` reflow.

Then run the sweep — `mypy` does **not** see `tests/`, so this is the check that nothing was missed:

```bash
./.venv/Scripts/python.exe - <<'EOF'
import ast, pathlib
faltando = []
for caminho in [*pathlib.Path("src").rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and getattr(no.func, "id", None) == "registrar_handoff":
            if not any(k.arg == "ator" for k in no.keywords):
                faltando.append(f"{caminho}:{no.lineno}")
print("\n".join(faltando) or "ok")
EOF
```

Expected: `ok`.

- [ ] **Step 5: Opt-out and reactivation**

In `src/mobia/domain/optout/repositorio.py`, add imports:

```python
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
```

Append to the module docstring:

```
Desde a TEC-206 cada escrita grava tambem o seu registro na trilha de
auditoria, na MESMA sessao da linha de `optout_events` e antes do commit: ou
os dois existem, ou nenhum. O ator e SISTEMA nas duas -- no opt-out o lead
pediu e o sistema registrou; na reativacao o operador da CLI e um `autor` em
texto livre, nao um `usuario_id`. O `motivo` nao vai para a trilha (D5): ele
fica aqui, e o registro aponta para esta linha pelo id.
```

`registrar_optout` body:

```python
    evento_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=evento_id,
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_OPT_OUT,
                message_id=message_id,
            )
        )
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REGISTRADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(evento_id),
            lead=(channel, conversation_key),
        )
        await session.commit()
```

`reativar` body:

```python
    evento_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=evento_id,
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_REATIVACAO,
                autor=autor,
                motivo=motivo,
            )
        )
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REATIVADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(evento_id),
            lead=(channel, conversation_key),
        )
        await session.commit()
```

`src/mobia/admin/reativar.py` needs no change: `_executar` calls `reativar`, and `test_a_reativacao_pela_cli_tambem_grava` proves the CLI path records.

- [ ] **Step 6: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_dos_eventos.py tests/integration/test_handoff_repositorio.py tests/integration/test_handoff_no_turno.py tests/integration/test_handoff_por_erro.py tests/integration/test_optout_repositorio.py tests/integration/test_admin_reativar.py tests/integration/test_pedido_de_humano.py tests/integration/test_turno_optout.py --tb=short -q`
Expected: PASS.

Then every other file edited in Step 4: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_dossie_do_banco.py tests/integration/test_handoff_schema.py tests/integration/test_exportacao_para_crm.py tests/integration/test_notificacao_destinatario.py tests/integration/test_recuperacao_sem_prazo.py tests/integration/test_um_handoff_por_conversa.py tests/integration/test_rota_de_resumo.py --tb=short -q`
Expected: PASS.

- [ ] **Step 7: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/handoff/repositorio.py src/mobia/domain/agente/turno.py src/mobia/workers/jobs/process_message.py src/mobia/domain/optout/repositorio.py tests/conftest.py tests/integration/test_auditoria_dos_eventos.py tests/integration/test_handoff_no_turno.py tests/integration/test_handoff_por_erro.py tests/integration/test_handoff_dossie_do_banco.py tests/integration/test_handoff_schema.py tests/integration/test_handoff_repositorio.py tests/integration/test_exportacao_para_crm.py tests/integration/test_notificacao_destinatario.py tests/integration/test_pedido_de_humano.py tests/integration/test_recuperacao_sem_prazo.py tests/integration/test_um_handoff_por_conversa.py
git commit -m "feat(TEC-206): handoff criado, opt-out e reativacao gravam registro na mesma transacao

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: O acesso ao resumo e a negativa com identidade

**Files:**
- Modify: `src/mobia/api/middleware.py` (`ip_valido_ou_nulo`, `origem_da_requisicao`)
- Modify: `src/mobia/api/autorizacao.py` (`registrar_negativa` e `exigir_dono` passam a `async`; `_template_da_rota`; `IdentidadeDaRequisicao.como_ator`; os quatro sítios com `await`)
- Modify: `src/mobia/api/routes/conversas.py` (`_exigir_que_seja_ele_mesmo` passa a `async`; `assumir` e `devolver` com `await`)
- Modify: `src/mobia/api/routes/handoffs.py` (`await exigir_dono`; `regenerar` grava `DADO_PESSOAL_ACESSADO`)
- Modify: `tests/integration/test_autorizacao_por_papel.py` (testes novos; docstring que citava a TEC-206 como futura)
- Modify: `tests/integration/test_rota_de_resumo.py` (testes novos)
- Test: `tests/unit/test_origem_da_requisicao.py`

**Interfaces:**
- Consumes: `registrar_evento`, `Origem`, `EventoAuditoria` (Task 2); `Ator`, `AtorTipo`, `Acao`, `Entidade`, `CAMPO_RESUMO`, `detalhes_da_negativa` (Task 1).
- Produces:
  - `middleware.ip_valido_ou_nulo(texto: str | None) -> str | None`
  - `middleware.origem_da_requisicao(request: Request) -> Origem`
  - `IdentidadeDaRequisicao.como_ator(self) -> Ator`
  - `async def registrar_negativa(request: Request, permissao: Permissao | None, *, identidade: IdentidadeDaRequisicao | None, motivo: str = "sem_permissao") -> None`
  - `async def exigir_dono(request: Request, identidade: IdentidadeDaRequisicao, *, permissao: Permissao, corretor_id: uuid.UUID | None) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_origem_da_requisicao.py`:

```python
"""O `ip` que a trilha grava tem de ser IP. TEC-206, Review Focus 1.

`resolver_ip` devolve o que o socket ou o `X-Forwarded-For` disserem, e a
coluna e `inet`: um valor que nao e endereco viraria `DataError` no INSERT --
e um 403 viraria 500.
"""

import pytest

from mobia.api.middleware import ip_valido_ou_nulo


@pytest.mark.parametrize("texto", ["127.0.0.1", "::1", "2001:db8::1"])
def test_ip_valido_passa(texto: str) -> None:
    assert ip_valido_ou_nulo(texto) == texto


@pytest.mark.parametrize("texto", [None, "", "testclient", "1.2.3.4:5678", "abc", "999.1.1.1"])
def test_o_que_nao_e_ip_vira_nulo(texto: str | None) -> None:
    assert ip_valido_ou_nulo(texto) is None
```

Append to `tests/integration/test_autorizacao_por_papel.py` (imports: `from sqlalchemy import select`, `from mobia.domain.auditoria.models import EventoAuditoria`):

```python
async def _negativas(session: AsyncSession) -> list[EventoAuditoria]:
    return list(
        (
            await session.execute(
                select(EventoAuditoria).where(EventoAuditoria.acao == "ACESSO_NEGADO")
            )
        ).scalars()
    )


async def test_a_negativa_com_identidade_vai_para_a_trilha(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """TEC-206, D7: com identidade resolvida, a negativa tem destino persistente.

    O `entidade_id` e o TEMPLATE da rota, e nao o caminho com o id: o que se
    audita e qual rota foi negada.
    """
    dono = await _corretor(semear_corretor, "paulo")
    intruso = await _corretor(semear_corretor, "marcia")
    handoff_id = await _handoff_de(session, dono)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=_bearer("CORRETOR", corretor_id=intruso),
    )

    assert resposta.status_code == 403
    (evento,) = await _negativas(session)
    assert evento.ator_tipo == "USUARIO"
    assert evento.ator_id is not None
    assert evento.entidade == "rota"
    assert evento.entidade_id == "/api/v1/handoffs/{handoff_id}/aceitar"
    assert evento.detalhes == {
        "permissao": "ATENDER_LEAD",
        "motivo": "corretor_nao_e_o_dono",
        "papel": "CORRETOR",
        "metodo": "POST",
    }
    assert str(evento.ip) == "127.0.0.1"
    assert evento.correlation_id == resposta.headers["X-Request-Id"]


async def test_a_negativa_por_papel_tambem_vai_para_a_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await client.get(ROTA_ADMINISTRATIVA, headers=_bearer("LEITURA"))

    (evento,) = await _negativas(session)
    assert evento.entidade_id == ROTA_ADMINISTRATIVA
    assert evento.detalhes is not None
    assert evento.detalhes["motivo"] == "sem_permissao"
    assert evento.detalhes["permissao"] == Permissao.GERIR_CORRETORES.value


async def test_a_negativa_sem_credencial_fica_so_no_log(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, caplog: Any
) -> None:
    """O argumento da TEC-202 vale inteiro: sem credencial, e o varredor em rajada."""
    with caplog.at_level("WARNING"):
        resposta = await client.get(ROTA_ADMINISTRATIVA)

    assert resposta.status_code == 403
    assert len(eventos_de_log(caplog, "autorizacao.negada")) == 1
    assert await _negativas(session) == []


async def test_o_token_compartilhado_sem_sessao_vai_para_a_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Identidade resolvida, mas sem usuario: `ator_id` e o `para_log` dela."""
    resposta = await client.get(
        "/api/v1/auth/me", headers={"X-Admin-Token": get_settings().catalogo_admin_token}
    )

    assert resposta.status_code == 403
    (evento,) = await _negativas(session)
    assert evento.ator_id == "token-compartilhado"
    assert evento.detalhes is not None
    assert evento.detalhes["motivo"] == "sem_sessao"
    assert evento.detalhes["permissao"] is None
```

Also in this file, the docstring of `test_a_negativa_por_papel_registra_quem_tentou` ends with "...e o unico registro que existe, porque a trilha imutavel da RNF-18 e a TEC-206 (L5)." — that became false. Replace that sentence with:

```
    investigacao. O log e metade do registro; a outra, desde a TEC-206, e a
    linha em `eventos_auditoria` -- ver
    `test_a_negativa_por_papel_tambem_vai_para_a_trilha`.
```

Append to `tests/integration/test_rota_de_resumo.py` (imports: `from sqlalchemy import select`, `from mobia.api.routes import handoffs as rota_de_handoffs`, `from mobia.domain.auditoria.models import EventoAuditoria`, `from mobia.infra.db import get_sessionmaker`):

```python
async def _acessos() -> list[EventoAuditoria]:
    async with get_sessionmaker()() as sessao:
        return list(
            (
                await sessao.execute(
                    select(EventoAuditoria).where(EventoAuditoria.acao == "DADO_PESSOAL_ACESSADO")
                )
            ).scalars()
        )


async def test_o_acesso_ao_resumo_vai_para_a_trilha_sem_o_resumo(
    cliente_http, semear_lead_completo
) -> None:
    """TEC-206, D7: `campo = resumo`, e o texto nao aparece em coluna nenhuma."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    (evento,) = await _acessos()
    assert evento.campo == "resumo"
    assert evento.entidade == "handoff"
    assert evento.entidade_id == str(handoff_id)
    assert evento.ator_tipo == "USUARIO"
    assert evento.ator_id == "token-compartilhado"
    assert evento.correlation_id == resposta.headers["X-Request-Id"]
    colunas = [
        evento.entidade_id, evento.campo, evento.lead_ref, str(evento.detalhes),
        evento.correlation_id, str(evento.ip),
    ]
    assert all(resposta.json()["resumo"] not in (valor or "") for valor in colunas)
    assert all("5511911112222" not in (valor or "") for valor in colunas)


async def test_sem_registro_o_resumo_nao_sai(
    cliente_http, semear_lead_completo, monkeypatch
) -> None:
    """Review Focus 4: se a escrita da trilha falha, a resposta e erro."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    async def _falha(*_: object, **__: object) -> None:
        raise RuntimeError("trilha fora do ar")

    monkeypatch.setattr(rota_de_handoffs, "registrar_evento", _falha)

    with pytest.raises(RuntimeError, match="trilha fora do ar"):
        await cliente_http.post(
            f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_origem_da_requisicao.py tests/integration/test_autorizacao_por_papel.py tests/integration/test_rota_de_resumo.py -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'ip_valido_ou_nulo'`, and the new integration tests fail on the empty trail.

- [ ] **Step 3: The origin of a request**

In `src/mobia/api/middleware.py`, add `import ipaddress` and `from mobia.domain.auditoria.registro import Origem`, and after `resolver_ip`:

```python
def ip_valido_ou_nulo(texto: str | None) -> str | None:
    """O endereco, se for um IP; nulo, se nao for. TEC-206.

    `resolver_ip` devolve o que o socket ou o `X-Forwarded-For` disserem -- um
    `1.2.3.4:5678`, o `testclient` do Starlette, lixo. Para o limitador tanto
    faz: e so uma chave. Para a trilha nao: a coluna e `inet`, e um valor que
    nao e endereco viraria `DataError` no INSERT, transformando um 403 em 500.
    Melhor um `ip` nulo e verdadeiro que um registro que nao existe.
    """
    if not texto:
        return None
    try:
        return str(ipaddress.ip_address(texto))
    except ValueError:
        return None


def origem_da_requisicao(request: Request) -> Origem:
    """De onde veio a requisicao, para a trilha de auditoria. TEC-206, D7.

    O IP pela MESMA regra do limitador (`resolver_ip`), e o `correlation_id`
    pelo contextvar que `CorrelacaoDeRequisicao` preencheu -- o vazio do
    default vira nulo, e nao uma string vazia gravada.
    """
    ip = resolver_ip(
        socket_host=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        confiar_em_forwarded_for=get_settings().confiar_em_forwarded_for,
    )
    return Origem(ip=ip_valido_ou_nulo(ip), correlation_id=correlation_id.get() or None)
```

Note: `str(ipaddress.ip_address("2001:db8::1"))` returns the same compressed text, so the unit test's `== texto` holds for the three valid inputs.

- [ ] **Step 4: `autorizacao.py`**

Imports to add:

```python
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import (
    Acao,
    Ator,
    AtorTipo,
    Entidade,
    detalhes_da_negativa,
)
from mobia.infra.db import get_sessionmaker
```

In `IdentidadeDaRequisicao`, after `para_log`:

```python
    def como_ator(self) -> Ator:
        """Quem chamou, como ator da trilha de auditoria (TEC-206).

        Sempre USUARIO, com o mesmo identificador do log: o `usuario_id`, ou
        `token-compartilhado` para quem entrou pelo `X-Admin-Token`.
        """
        return Ator(AtorTipo.USUARIO, self.para_log())
```

In `Exige.__call__`, the two calls become `await registrar_negativa(...)`. Extend the comment above the first one:

```python
            # Sem identidade nenhuma nao ha papel a registrar, e o evento sai
            # com `papel=None` em vez de com um papel inventado: "ninguem
            # provou quem e" e um fato diferente de "provou e nao pode". E nao
            # vai para a trilha (TEC-206, D7): ver `registrar_negativa`.
```

In `ExigeSessao.__call__`: `await registrar_negativa(request, None, identidade=identidade, motivo="sem_sessao")`.

Before `registrar_negativa`, add:

```python
def _template_da_rota(request: Request) -> str:
    """A rota como foi declarada (`/api/v1/handoffs/{handoff_id}/aceitar`).

    O FastAPI poe a rota resolvida em `request.scope["route"]` antes de rodar
    as dependencias. Sem ela -- nao acontece nas rotas guardadas, mas o custo
    de nao quebrar e uma linha --, cai para o caminho cru, no teto da coluna.
    """
    caminho = getattr(request.scope.get("route"), "path", None)
    if isinstance(caminho, str):
        return caminho
    return request.url.path[:200]
```

Replace `registrar_negativa` entirely:

```python
async def registrar_negativa(
    request: Request,
    permissao: Permissao | None,
    *,
    identidade: IdentidadeDaRequisicao | None,
    motivo: str = "sem_permissao",
) -> None:
    """A tentativa negada, registrada. TEC-202, D6; TEC-206, D7.

    **Sempre no log; na trilha, so quando ha identidade.** O log
    `autorizacao.negada` sai em toda negativa, com o formato da TEC-202. A
    linha em `eventos_auditoria` sai so quando `identidade` foi resolvida.
    A negativa sem credencial continua so em log, e o argumento e o que o
    docstring de `RateLimitEvent` escreve: "escrever uma linha por requisicao
    transformaria o registro de abuso no proprio vetor de abuso". Negacao sem
    credencial e o que um varredor de endpoints produz EM RAJADA, e cada 403
    viraria uma escrita no Postgres do defensor. Com identidade, quem produz a
    negativa e alguem identificavel -- e e esse o registro que a TEC-343 pede.

    **A escrita commita antes de o 403 sair**, numa sessao curta propria: nao
    ha transacao de negocio a que ela se juntar. Se o banco falhar, a resposta
    e erro, e nao um 403 sem registro.

    **Nunca o token e nunca o corpo** -- so quem, o que foi exigido e onde. Na
    trilha, "onde" e o template da rota, e nao o caminho com o id.

    `permissao` e nula quando o que faltou nao foi permissao, e sim sessao de
    usuario -- e o caso do `ExigeSessao`.
    """
    log.warning(
        "autorizacao.negada",
        motivo=motivo,
        permissao=permissao.value if permissao is not None else None,
        papel=identidade.papel if identidade else None,
        usuario_id=identidade.para_log() if identidade else None,
        metodo=request.method,
        rota=request.url.path,
    )
    if identidade is None:
        return
    async with get_sessionmaker()() as session:
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.ACESSO_NEGADO,
            entidade=Entidade.ROTA,
            entidade_id=_template_da_rota(request),
            detalhes=detalhes_da_negativa(
                permissao=permissao.value if permissao is not None else None,
                motivo=motivo,
                papel=identidade.papel,
                metodo=request.method,
            ),
            origem=origem_da_requisicao(request),
        )
        await session.commit()
```

`exigir_dono` becomes `async def exigir_dono(...)`, body unchanged except `await registrar_negativa(request, permissao, identidade=identidade, motivo="corretor_nao_e_o_dono")`.

- [ ] **Step 5: The routes**

`src/mobia/api/routes/conversas.py`: `_exigir_que_seja_ele_mesmo` becomes `async def`, its body `await exigir_dono(...)`, and both call sites (`assumir`, `devolver`) become `await _exigir_que_seja_ele_mesmo(request, identidade, pedido.corretor_id)`.

`src/mobia/api/routes/handoffs.py`:

1. In `_exigir_dono_do`: `await exigir_dono(...)`.
2. Imports: `from mobia.api.middleware import origem_da_requisicao`, `from mobia.domain.auditoria.registro import registrar_evento`, `from mobia.domain.auditoria.vocabulario import CAMPO_RESUMO, Acao, Entidade`.
3. In `regenerar`, replace the final `async with session_factory() as session:` block with:

```python
    async with session_factory() as session:
        linha = (
            await session.execute(select(Handoff).where(Handoff.id == handoff_id))
        ).scalar_one()
        # TEC-206, D1 e D7. O resumo carrega dado pessoal do lead, e esta rota
        # e hoje o unico caminho que o revela. O registro commita AQUI, antes
        # do `return`: se a escrita falhar, a resposta e erro, e o resumo nao
        # sai sem o registro. O texto do resumo nao vai para a trilha -- ela
        # diz qual campo foi lido, nao o que ele dizia.
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADO_PESSOAL_ACESSADO,
            entidade=Entidade.HANDOFF,
            entidade_id=str(handoff_id),
            campo=CAMPO_RESUMO,
            lead=(linha.channel, linha.conversation_key),
            origem=origem_da_requisicao(request),
        )
        await session.commit()
```

The `return {...}` that follows is unchanged. `get_sessionmaker` uses `expire_on_commit=False`, so reading `linha` after the commit does not reload it.

- [ ] **Step 6: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_origem_da_requisicao.py tests/integration/test_autorizacao_por_papel.py tests/integration/test_rota_de_resumo.py tests/integration/test_rota_de_aceite.py tests/integration/test_rota_de_conversas.py tests/integration/test_autenticacao.py -v --tb=short`
Expected: PASS.

- [ ] **Step 7: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/middleware.py src/mobia/api/autorizacao.py src/mobia/api/routes/conversas.py src/mobia/api/routes/handoffs.py tests/unit/test_origem_da_requisicao.py tests/integration/test_autorizacao_por_papel.py tests/integration/test_rota_de_resumo.py
git commit -m "feat(TEC-206): o acesso ao resumo e a negativa com identidade gravam registro antes da resposta

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `GET /api/v1/auditoria`, só do `ADMIN`

**Files:**
- Modify: `src/mobia/domain/usuarios/permissoes.py` (`VER_AUDITORIA`; comentário que conta as linhas do ADMIN)
- Create: `src/mobia/domain/auditoria/consulta.py`
- Create: `src/mobia/domain/auditoria/repositorio.py`
- Create: `src/mobia/api/routes/auditoria.py`
- Modify: `src/mobia/app/main.py` (import tardio e `include_router`)
- Modify: `tests/unit/test_matriz_de_permissoes.py`
- Modify: `tests/unit/test_autorizacao_em_toda_rota.py` (`PERMISSAO_ESPERADA` e o comentário que conta "dez")
- Test: `tests/unit/test_consulta_da_trilha.py`, `tests/integration/test_rota_de_auditoria.py`

**Interfaces:**
- Consumes: `EventoAuditoria` (Task 2); `Acao` (Task 1); `lead_ref` (Task 1); `FiltroInvalido`, `LIMITE_PADRAO`, `LIMITE_MAXIMO` from `mobia.domain.leads.consulta`; `Exige`, `IdentidadeDaRequisicao`.
- Produces:
  - `Permissao.VER_AUDITORIA`
  - `consulta.CursorDaTrilha(criado_em: datetime, id: uuid.UUID)` com `codificar() -> str`; `consulta.decodificar_cursor(texto: str) -> CursorDaTrilha`
  - `consulta.FiltroDaTrilha(ator_id, acoes, de, ate, lead_ref, limite, cursor)`
  - `consulta.montar_filtro(*, ator: str | None = None, acoes: tuple[str, ...] = (), de: datetime | None = None, ate: datetime | None = None, channel: str | None = None, conversation_key: str | None = None, limite: int = LIMITE_PADRAO, cursor: str | None = None, chave_do_lead: str) -> FiltroDaTrilha`
  - `async def repositorio.listar_eventos(session: AsyncSession, *, filtro: FiltroDaTrilha) -> tuple[list[EventoAuditoria], CursorDaTrilha | None]`
  - `GET /api/v1/auditoria` → `{"itens": [...], "proximoCursor": str | None}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_matriz_de_permissoes.py`:

```python
def test_ver_auditoria_e_so_do_admin() -> None:
    """TEC-206, D8, e a TEC-343: "Somente leitura; somente ADMIN".

    So o ADMIN, por construcao: a permissao nao aparece em `_CONCEDIDAS`. E
    leitura -- fora de `DE_ESCRITA`, e por isso o terceiro cenario da TEC-202
    nao a toca.
    """
    assert papeis_com(Permissao.VER_AUDITORIA) == frozenset({"ADMIN"})
    assert Permissao.VER_AUDITORIA not in DE_ESCRITA
```

In `tests/unit/test_autorizacao_em_toda_rota.py`, add to `PERMISSAO_ESPERADA`:

```python
    ("GET", "/api/v1/auditoria"): "VER_AUDITORIA",
```

and, in the comment above it, replace "ele exige que cada uma das dez esteja la" with "ele exige que cada uma delas esteja la" (the map already had 13 entries; this makes 14).

`tests/unit/test_consulta_da_trilha.py`:

```python
"""O cursor e a validacao do filtro da trilha de auditoria. TEC-206, D8.

Sem banco, no molde de `test_cursor_da_lista_de_leads.py`. Os cenarios contra
banco estao em `tests/integration/test_rota_de_auditoria.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.auditoria.consulta import CursorDaTrilha, decodificar_cursor, montar_filtro
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.leads.consulta import LIMITE_MAXIMO, FiltroInvalido

CHAVE = "chave-de-teste"
AGORA = datetime(2026, 9, 25, 12, 0, 0, 123456, tzinfo=UTC)


class TestCursor:
    def test_ida_e_volta_preserva_os_microssegundos(self) -> None:
        cursor = CursorDaTrilha(criado_em=AGORA, id=uuid.uuid4())

        assert decodificar_cursor(cursor.codificar()) == cursor

    @pytest.mark.parametrize(
        "texto",
        [
            "nao-e-base64!!",
            "",
            # {"x":1}: base64 e JSON validos, chaves erradas
            "eyJ4IjoxfQ==",
            # {"t": "...+00:00", "i": "x"}: data boa, uuid invalido
            "eyJ0IjoiMjAyNi0wOS0yNVQxMjowMDowMCswMDowMCIsImkiOiJ4In0=",
            # [1,2]: JSON que nao e objeto
            "WzEsMl0=",
            # {"t": "2026-09-25T12:00:00", "i": uuid valido}: sem fuso
            "eyJ0IjoiMjAyNi0wOS0yNVQxMjowMDowMCIsImkiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAifQ==",
            # nao-ASCII: `encode("ascii")` levanta antes do base64
            "cursor-com-acentuação",
        ],
    )
    def test_cursor_invalido_e_recusado(self, texto: str) -> None:
        with pytest.raises(FiltroInvalido, match="cursor"):
            decodificar_cursor(texto)


class TestFiltro:
    def test_o_lead_vira_lead_ref_e_o_telefone_nao_fica(self) -> None:
        filtro = montar_filtro(channel="whatsapp", conversation_key="5511911112222", chave_do_lead=CHAVE)

        assert filtro.lead_ref == lead_ref("whatsapp", "5511911112222", chave=CHAVE)
        assert "5511911112222" not in repr(filtro)

    @pytest.mark.parametrize(
        ("channel", "conversation_key"), [("whatsapp", None), (None, "5511911112222")]
    )
    def test_lead_pela_metade_e_recusado(
        self, channel: str | None, conversation_key: str | None
    ) -> None:
        """Review Focus 5: metade do par nao pode virar "sem filtro"."""
        with pytest.raises(FiltroInvalido, match="juntos"):
            montar_filtro(channel=channel, conversation_key=conversation_key, chave_do_lead=CHAVE)

    def test_acao_fora_do_vocabulario_e_recusada(self) -> None:
        with pytest.raises(FiltroInvalido, match="APAGOU"):
            montar_filtro(acoes=("HANDOFF_CRIADO", "APAGOU"), chave_do_lead=CHAVE)

    @pytest.mark.parametrize("limite", [0, LIMITE_MAXIMO + 1])
    def test_limite_fora_da_faixa(self, limite: int) -> None:
        with pytest.raises(FiltroInvalido, match="limite"):
            montar_filtro(limite=limite, chave_do_lead=CHAVE)

    def test_data_sem_fuso_e_recusada(self) -> None:
        with pytest.raises(FiltroInvalido, match="fuso"):
            montar_filtro(de=datetime(2026, 9, 1), chave_do_lead=CHAVE)

    def test_intervalo_vazio_ou_invertido_e_recusado(self) -> None:
        with pytest.raises(FiltroInvalido, match="anterior"):
            montar_filtro(de=AGORA, ate=AGORA, chave_do_lead=CHAVE)

    def test_sem_filtro_nenhum_passa(self) -> None:
        filtro = montar_filtro(chave_do_lead=CHAVE)

        assert filtro.lead_ref is None
        assert filtro.acoes == ()
```

The base64 literals above were generated with `json.dumps(..., separators=(",", ":"))` and `base64.urlsafe_b64encode` and checked on 25/09/2026; the long one sits alone on its line, which is what keeps E501 quiet.

`tests/integration/test_rota_de_auditoria.py`:

```python
"""A leitura da trilha: `GET /api/v1/auditoria`. TEC-206, D8 do desenho.

Os eventos sao semeados por `registrar_evento`, e os instantes que os testes
de `de`/`ate` usam sao LIDOS do banco: medido em 25/09/2026, o relogio do
Postgres local estava um ano atras do host, e o trigger da 0048 carimba pelo
relogio do banco.
"""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Ator, AtorTipo, Entidade
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/auditoria"
CHAVES_DO_ITEM = {
    "id", "criadoEm", "atorTipo", "atorId", "acao", "entidade", "entidadeId", "campo",
    "detalhes", "ip", "correlationId",
}


def _bearer(papel: str) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _evento(
    session: AsyncSession,
    *,
    acao: Acao = Acao.HANDOFF_CRIADO,
    ator: Ator = ATOR_SISTEMA,
    lead: tuple[str, str] | None = None,
) -> uuid.UUID:
    evento_id = await registrar_evento(
        session, ator=ator, acao=acao, entidade=Entidade.HANDOFF,
        entidade_id=str(uuid.uuid4()), lead=lead,
    )
    await session.commit()
    return evento_id


async def _criado_em(session: AsyncSession, evento_id: uuid.UUID) -> datetime:
    return (
        await session.execute(
            select(EventoAuditoria.criado_em).where(EventoAuditoria.id == evento_id)
        )
    ).scalar_one()


async def _ids(client: AsyncClient, **params: object) -> list[str]:
    resposta = await client.get(ROTA, params=params, headers=_bearer("ADMIN"))
    assert resposta.status_code == 200, resposta.text
    return [item["id"] for item in resposta.json()["itens"]]


async def test_admin_le_a_trilha_do_mais_recente_ao_mais_antigo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    primeiro = await _evento(session)
    segundo = await _evento(session, lead=("whatsapp", "5511911112222"))

    resposta = await client.get(ROTA, headers=_bearer("ADMIN"))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [item["id"] for item in corpo["itens"]] == [str(segundo), str(primeiro)]
    assert corpo["proximoCursor"] is None
    # `leadRef` e chave de busca, nao informacao para exibir.
    assert set(corpo["itens"][0]) == CHAVES_DO_ITEM
    assert "5511911112222" not in resposta.text


@pytest.mark.parametrize("papel", ["GERENTE", "CORRETOR", "LEITURA"])
async def test_quem_nao_e_admin_recebe_403_e_vira_acesso_negado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    resposta = await client.get(ROTA, headers=_bearer(papel))

    assert resposta.status_code == 403
    (negativa,) = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == "ACESSO_NEGADO")
        )
    ).scalars()
    assert negativa.entidade_id == ROTA
    assert negativa.detalhes is not None
    assert negativa.detalhes["permissao"] == "VER_AUDITORIA"
    assert negativa.detalhes["papel"] == papel


async def test_a_rota_nao_tem_como_editar_nem_excluir(
    client: AsyncClient, banco_limpo: None
) -> None:
    """D8: "nao ha opcao de editar nem de excluir" vale tambem na API."""
    for metodo in ("POST", "PUT", "PATCH", "DELETE"):
        resposta = await client.request(metodo, ROTA, headers=_bearer("ADMIN"))
        assert resposta.status_code == 405, metodo


async def test_filtro_por_ator(session: AsyncSession, client: AsyncClient, banco_limpo: None) -> None:
    do_paulo = await _evento(session, ator=Ator(AtorTipo.USUARIO, "paulo"))
    await _evento(session, ator=Ator(AtorTipo.USUARIO, "marcia"))
    await _evento(session)

    assert await _ids(client, ator="paulo") == [str(do_paulo)]


async def test_filtro_por_acao_aceita_mais_de_uma(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    optout = await _evento(session, acao=Acao.OPTOUT_REGISTRADO)
    reativado = await _evento(session, acao=Acao.OPTOUT_REATIVADO)
    await _evento(session, acao=Acao.HANDOFF_CRIADO)

    ids = await _ids(client, acao=["OPTOUT_REGISTRADO", "OPTOUT_REATIVADO"])

    assert ids == [str(reativado), str(optout)]


async def test_de_e_ate_sao_semiabertos(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _evento(session)
    meio = await _evento(session)
    ultimo = await _evento(session)

    ids = await _ids(
        client,
        de=(await _criado_em(session, meio)).isoformat(),
        ate=(await _criado_em(session, ultimo)).isoformat(),
    )

    assert ids == [str(meio)]


async def test_filtro_por_lead_nao_devolve_outro_lead(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    do_lead = await _evento(session, lead=("whatsapp", "5511911112222"))
    await _evento(session, lead=("whatsapp", "5511933334444"))
    await _evento(session, lead=("web", "5511911112222"))

    ids = await _ids(client, channel="whatsapp", conversationKey="5511911112222")

    assert ids == [str(do_lead)]


@pytest.mark.parametrize(
    "params",
    [
        {"channel": "whatsapp"},
        {"conversationKey": "5511911112222"},
        {"acao": "APAGOU_TUDO"},
        {"limite": 0},
        {"limite": 101},
        {"cursor": "lixo"},
        {"de": "2026-09-01T00:00:00"},
        {"de": "2026-09-02T00:00:00+00:00", "ate": "2026-09-01T00:00:00+00:00"},
    ],
)
async def test_pedido_invalido_e_422_e_nao_trilha_inteira(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, params: dict[str, object]
) -> None:
    """Review Focus 5 nas duas primeiras linhas: filtro pela metade nao e "sem filtro"."""
    await _evento(session)

    resposta = await client.get(ROTA, params=params, headers=_bearer("ADMIN"))

    assert resposta.status_code == 422


async def test_o_cursor_percorre_sem_repetir_nem_pular(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    semeados = [await _evento(session) for _ in range(5)]

    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        params: dict[str, object] = {"limite": 2}
        if cursor is not None:
            params["cursor"] = cursor
        corpo = (await client.get(ROTA, params=params, headers=_bearer("ADMIN"))).json()
        vistos.extend(item["id"] for item in corpo["itens"])
        cursor = corpo["proximoCursor"]
        if cursor is None:
            break

    assert vistos == [str(evento_id) for evento_id in reversed(semeados)]
    assert cursor is None
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_matriz_de_permissoes.py tests/unit/test_autorizacao_em_toda_rota.py tests/unit/test_consulta_da_trilha.py tests/integration/test_rota_de_auditoria.py -v --tb=short`
Expected: FAIL — `AttributeError: VER_AUDITORIA`, `ModuleNotFoundError: mobia.domain.auditoria.consulta`, and 404 on the route.

- [ ] **Step 3: The permission**

In `src/mobia/domain/usuarios/permissoes.py`, after `VER_DADOS_COMPLETOS`:

```python
    # TEC-206, D8, para a tela da TEC-343: "Somente leitura; somente ADMIN".
    # Nao aparece em `_CONCEDIDAS` -- o ADMIN a recebe por construcao, e
    # nenhum outro papel a tem. Leitura, e por isso fora de `DE_ESCRITA`.
    VER_AUDITORIA = "VER_AUDITORIA"
```

In the comment above `_CONCEDIDAS`, replace "Repetir as seis linhas dele seria criar" with "Repetir as linhas dele seria criar" (there were already seven permissions; now eight).

- [ ] **Step 4: Consulta and repositorio**

`src/mobia/domain/auditoria/consulta.py`:

```python
"""O que se pede a trilha de auditoria, e onde a pagina seguinte comeca. TEC-206, D8.

Modulo sem I/O, no molde de `leads/consulta.py`, de quem reaproveita
`FiltroInvalido` e os limites de pagina: a convencao de 422 e de pagina e uma
so para as duas listas do painel. O cursor e proprio, porque a ordem aqui e
`(criado_em DESC, id DESC)`, e nao score. Quem toca o banco e `repositorio.py`.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.leads.consulta import LIMITE_MAXIMO, LIMITE_PADRAO, FiltroInvalido


@dataclass(frozen=True)
class CursorDaTrilha:
    """O ULTIMO item da pagina atual. `id` desempata dois eventos no mesmo instante."""

    criado_em: datetime
    id: uuid.UUID

    def codificar(self) -> str:
        """base64 de um JSON, opaco pelo mesmo contrato do cursor da TEC-192."""
        corpo = json.dumps(
            {"t": self.criado_em.isoformat(), "i": str(self.id)}, separators=(",", ":")
        )
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor(texto: str) -> CursorDaTrilha:
    """O cursor que `codificar` produziu. Levanta `FiltroInvalido` para o resto.

    `ValueError` cobre base64, UTF-8, JSON, data e uuid malformados (todos
    herdam dele); `KeyError`, `TypeError` e `AttributeError` cobrem o JSON bem
    formado com a forma errada. Cursor sem fuso tambem e recusado: comparar
    `timestamptz` com instante ingenuo o leria no fuso da sessao do banco.
    """
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        criado_em = datetime.fromisoformat(corpo["t"])
        evento_id = uuid.UUID(corpo["i"])
    except (ValueError, KeyError, TypeError, AttributeError) as erro:
        raise FiltroInvalido("cursor invalido") from erro
    if criado_em.tzinfo is None:
        raise FiltroInvalido("cursor invalido")
    return CursorDaTrilha(criado_em=criado_em, id=evento_id)


@dataclass(frozen=True)
class FiltroDaTrilha:
    """O recorte pedido. O lead ja chega como `lead_ref` -- o telefone nao fica."""

    ator_id: str | None = None
    acoes: tuple[str, ...] = ()
    de: datetime | None = None
    ate: datetime | None = None
    lead_ref: str | None = None
    limite: int = LIMITE_PADRAO
    cursor: CursorDaTrilha | None = None


def montar_filtro(
    *,
    ator: str | None = None,
    acoes: tuple[str, ...] = (),
    de: datetime | None = None,
    ate: datetime | None = None,
    channel: str | None = None,
    conversation_key: str | None = None,
    limite: int = LIMITE_PADRAO,
    cursor: str | None = None,
    chave_do_lead: str,
) -> FiltroDaTrilha:
    """Valida na borda o que o SQL nao valida sozinho.

    **O par do lead vai junto ou nao vai.** Metade dele ignorada viraria a
    trilha de todos os leads para quem pediu a de um so. O servidor
    transforma o par em `lead_ref` e nao guarda o telefone que recebeu.

    `ator` e texto exato, e nao UUID: `token-compartilhado` e um `ator_id`
    legitimo e precisa ser pesquisavel.
    """
    if not 1 <= limite <= LIMITE_MAXIMO:
        raise FiltroInvalido(f"limite fora da faixa 1..{LIMITE_MAXIMO}: {limite}")

    desconhecidas = sorted(set(acoes) - {acao.value for acao in Acao})
    if desconhecidas:
        raise FiltroInvalido(f"acao desconhecida: {', '.join(desconhecidas)}")

    for nome, instante in (("de", de), ("ate", ate)):
        if instante is not None and instante.tzinfo is None:
            raise FiltroInvalido(f"{nome} precisa de fuso (ISO-8601 com offset)")
    if de is not None and ate is not None and de >= ate:
        raise FiltroInvalido("de precisa ser anterior a ate")

    if (channel is None) != (conversation_key is None):
        raise FiltroInvalido("channel e conversationKey vao juntos")
    referencia = (
        lead_ref(channel, conversation_key, chave=chave_do_lead)
        if channel is not None and conversation_key is not None
        else None
    )

    return FiltroDaTrilha(
        ator_id=ator,
        acoes=tuple(acoes),
        de=de,
        ate=ate,
        lead_ref=referencia,
        limite=limite,
        cursor=decodificar_cursor(cursor) if cursor else None,
    )
```

`src/mobia/domain/auditoria/repositorio.py`:

```python
"""A consulta paginada da trilha de auditoria. TEC-206, D8.

Funcao livre com `session` posicional e o resto keyword-only, sem commit -- a
convencao dos repositorios deste repo. Nenhuma funcao aqui escreve: a unica
escrita da trilha e `registro.registrar_evento`.
"""

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.consulta import CursorDaTrilha, FiltroDaTrilha
from mobia.domain.auditoria.models import EventoAuditoria


async def listar_eventos(
    session: AsyncSession, *, filtro: FiltroDaTrilha
) -> tuple[list[EventoAuditoria], CursorDaTrilha | None]:
    """A pagina pedida, do mais recente ao mais antigo, e o cursor da proxima.

    **Pede um item a mais e o descarta**, como `listar_leads`: responde "ha
    proxima pagina?" sem `COUNT(*)`. Sem `total`, pela mesma razao.

    A ordem `(criado_em DESC, id DESC)` e servida por
    `ix_eventos_auditoria_pagina`; o `id` desempata dois eventos no mesmo
    instante, que e o que impede o cursor de repetir ou pular linha.
    """
    consulta = select(EventoAuditoria)
    if filtro.ator_id is not None:
        consulta = consulta.where(EventoAuditoria.ator_id == filtro.ator_id)
    if filtro.acoes:
        consulta = consulta.where(EventoAuditoria.acao.in_(filtro.acoes))
    if filtro.de is not None:
        consulta = consulta.where(EventoAuditoria.criado_em >= filtro.de)
    if filtro.ate is not None:
        consulta = consulta.where(EventoAuditoria.criado_em < filtro.ate)
    if filtro.lead_ref is not None:
        consulta = consulta.where(EventoAuditoria.lead_ref == filtro.lead_ref)
    if filtro.cursor is not None:
        consulta = consulta.where(
            or_(
                EventoAuditoria.criado_em < filtro.cursor.criado_em,
                and_(
                    EventoAuditoria.criado_em == filtro.cursor.criado_em,
                    EventoAuditoria.id < filtro.cursor.id,
                ),
            )
        )

    linhas = list(
        (
            await session.execute(
                consulta.order_by(EventoAuditoria.criado_em.desc(), EventoAuditoria.id.desc())
                .limit(filtro.limite + 1)
            )
        ).scalars()
    )

    pagina = linhas[: filtro.limite]
    if len(linhas) <= filtro.limite or not pagina:
        return pagina, None
    ultimo = pagina[-1]
    return pagina, CursorDaTrilha(criado_em=ultimo.criado_em, id=ultimo.id)
```

- [ ] **Step 5: The route and its registration**

`src/mobia/api/routes/auditoria.py`:

```python
"""A trilha de auditoria, so para leitura. TEC-206, D8 do desenho; tela na TEC-343.

**So `GET`, e so do ADMIN** (`VER_AUDITORIA`). A rota nao tem outro metodo,
entao "nao ha opcao de editar nem de excluir" vale tambem na API -- e, por
baixo dela, o trigger da 0048 recusa as duas coisas de qualquer caminho.

**A leitura da trilha nao e auditada** nesta card: seria um registro por
registro lido. Se precisar ser, e decisao da TEC-343.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.auditoria.consulta import montar_filtro
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.repositorio import listar_eventos
from mobia.domain.leads.consulta import LIMITE_PADRAO, FiltroInvalido
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/auditoria", tags=["auditoria"])


def _item(evento: EventoAuditoria) -> dict[str, Any]:
    """Um registro para a tela. **`leadRef` nao sai**: e chave de busca, nao
    informacao para exibir."""
    return {
        "id": str(evento.id),
        "criadoEm": evento.criado_em.isoformat(),
        "atorTipo": evento.ator_tipo,
        "atorId": evento.ator_id,
        "acao": evento.acao,
        "entidade": evento.entidade,
        "entidadeId": evento.entidade_id,
        "campo": evento.campo,
        "detalhes": evento.detalhes,
        # O asyncpg devolve `ipaddress.IPv4Address`/`IPv6Address`.
        "ip": str(evento.ip) if evento.ip is not None else None,
        "correlationId": evento.correlation_id,
    }


@router.get("")
async def listar(
    ator: Annotated[str | None, Query(max_length=64)] = None,
    acao: Annotated[list[str] | None, Query()] = None,
    de: Annotated[datetime | None, Query()] = None,
    ate: Annotated[datetime | None, Query()] = None,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    conversation_key: Annotated[str | None, Query(alias="conversationKey", max_length=64)] = None,
    limite: Annotated[int, Query()] = LIMITE_PADRAO,
    cursor: Annotated[str | None, Query()] = None,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_AUDITORIA)),
) -> dict[str, object]:
    """A trilha do mais recente ao mais antigo, filtrada e paginada por cursor.

    Filtros opcionais e combinaveis; `de`/`ate` e o intervalo semiaberto
    `[de, ate)`. Filtro invalido e 422, na convencao da TEC-192. Trilha vazia
    e 200 com `itens` vazio.
    """
    try:
        filtro = montar_filtro(
            ator=ator,
            acoes=tuple(acao or ()),
            de=de,
            ate=ate,
            channel=channel,
            conversation_key=conversation_key,
            limite=limite,
            cursor=cursor,
            chave_do_lead=get_settings().auditoria_chave_do_lead,
        )
    except FiltroInvalido as erro:
        # `UNPROCESSABLE_CONTENT` pela mesma razao de `routes/leads.py`.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        eventos, proximo = await listar_eventos(session, filtro=filtro)

    return {
        "itens": [_item(evento) for evento in eventos],
        "proximoCursor": proximo.codificar() if proximo else None,
    }
```

In `src/mobia/app/main.py`, in the late-import block, add `from mobia.api.routes.auditoria import router as auditoria_router` (alphabetical: first) and `app.include_router(auditoria_router)` after `app.include_router(leads_router)`. Append to the comment that starts "**`leads` entra neste bloco sem ser administrativa**":

```python
    # `auditoria` (TEC-206) entra pelo mesmo motivo de import tardio, e esta e
    # administrativa de fato: quem a protege e `VER_AUDITORIA`, so do ADMIN.
```

- [ ] **Step 6: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_matriz_de_permissoes.py tests/unit/test_autorizacao_em_toda_rota.py tests/unit/test_consulta_da_trilha.py tests/integration/test_rota_de_auditoria.py tests/integration/test_autorizacao_por_papel.py -v --tb=short`
Expected: PASS.

- [ ] **Step 7: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/usuarios/permissoes.py src/mobia/domain/auditoria/consulta.py src/mobia/domain/auditoria/repositorio.py src/mobia/api/routes/auditoria.py src/mobia/app/main.py tests/unit/test_matriz_de_permissoes.py tests/unit/test_autorizacao_em_toda_rota.py tests/unit/test_consulta_da_trilha.py tests/integration/test_rota_de_auditoria.py
git commit -m "feat(TEC-206): o ADMIN le a trilha de auditoria filtrada e paginada, e ninguem a edita pela API

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Emendas ao SRS, comentários e status

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (três emendas)
- Modify: `docs/superpowers/specs/2026-09-25-tec-206-trilha-de-auditoria-design.md` (`**Status:**` → `implementado`)
- Modify: `src/mobia/domain/atendimento/models.py` (docstring do módulo)
- Modify: any comment/docstring the listing flags as made false by Tasks 1–6

- [ ] **Step 1: The amendments**

**Never rewrite** the existing text; each amendment is a new list item in the format of its siblings, accented, code cited by anchor.

In §3.3, the RNF amendments are a list right below the table (`- **Emenda E-01 (TEC-205, …)** — …`, `- **Emenda E-02 (TEC-124, …)** — …`, `- **Emenda E-01 à RNF-12 (TEC-202, 24/09/2026)** — …`). Right after the `E-01 à RNF-12` item, add these two, in this order:

```markdown
- **Emenda E-02 à RNF-12 (TEC-206, 25/09/2026)** — a Emenda E-01 acima registrou que a tentativa negada vai para log estruturado, e não para a trilha imutável da RNF-18, porque *"essa é a TEC-206"*. A partir dela, **a negativa com identidade resolvida** — JWT válido sem a permissão, token compartilhado numa rota que exige sessão de usuário, ou corretor agindo sobre o que não é dele — grava também um `ACESSO_NEGADO` em `eventos_auditoria`, com o template da rota, a permissão, o motivo, o papel e o método, **antes** de o `403` sair; se a escrita falhar, a resposta é erro. **A negativa sem credencial continua só em log**, pelo argumento da TEC-202: um varredor de endpoints a produz em rajada, e cada `403` viraria uma escrita no banco. O log `autorizacao.negada` continua saindo nos dois casos, com o mesmo formato. Ver `api/autorizacao.py::registrar_negativa`.
- **Emenda E-01 à RNF-18 (TEC-206, 25/09/2026)** — a trilha é a tabela `eventos_auditoria`, só de acréscimo. Gravam registro hoje: a criação de handoff, o registro e a reativação de opt-out, o acesso ao resumo do handoff (`POST /api/v1/handoffs/{id}/resumo`, o único caminho que hoje revela dado pessoal do lead) e o acesso negado com identidade (Emenda E-02 à RNF-12). **Alteração de qualificação e mudança de prompt estão no vocabulário e não têm chamador:** a edição de qualificação pelo dashboard é a TEC-194 — e só a feita por pessoa será auditada, porque a do agente se reconstrói pela transcrição —, e `ConfiguracaoAgente` não existe (TEC-198/199); o acesso a telefone e e-mail não tem rota que o revele (TEC-195). **Os 12 meses são máximo**, como os prazos da RNF-22: o job diário `sweep_retencao_auditoria` apaga o que passou disso, e o banco recusa `UPDATE` sempre e `DELETE` de registro mais novo que 12 meses, por qualquer caminho da aplicação — ORM, SQL cru, script ou migration. **Limite declarado:** a garantia vale contra a aplicação e não contra quem opera o banco como dono — a aplicação conecta como dono da tabela, e o dono pode remover o trigger; separar um papel sem DDL é a TEC-219. `TRUNCATE` também não é bloqueado. Ver o desenho da TEC-206.
```

In §5.1, right after the `**EventoAuditoria** — …` paragraph, add:

```markdown
- **Emenda E-01 (TEC-206, 25/09/2026):** entram três colunas e saem duas. Entram `campo` (o campo acessado ou alterado, como `resumo`), `lead_ref` (HMAC-SHA256 de `channel:conversation_key` com a chave `AUDITORIA_CHAVE_DO_LEAD`, para achar os eventos de um lead sem gravar o telefone — no WhatsApp a `conversation_key` **é** o telefone) e `correlation_id` (o id da requisição, que liga o registro ao log de aplicação); entra também `detalhes` jsonb, só com metadado fechado e nunca texto digitado por pessoa. **Saem `dados_antes` e `dados_depois`:** para qualificação e dado pessoal, o antes e o depois **são** o dado pessoal que não pode ficar em claro, e cifrá-los faria da trilha uma segunda cópia do dado, que a retenção e a eliminação (RNF-21) teriam de perseguir — o registro diz qual campo mudou, não para quê. Sem chave estrangeira para as entidades, para o registro sobreviver à exclusão do que descreve. *"Sem update nem delete"* passa a ser *sem update, e sem delete antes de 12 meses* — ver a Emenda E-01 à RNF-18.
```

- [ ] **Step 2: Comments**

Fix the one already known to be false: `src/mobia/domain/atendimento/models.py`, module docstring, last sentence "O historico de todos os ciclos, que o append-only daria de graca, e a trilha de auditoria da TEC-206." — TEC-206 does **not** record `assumir`/`devolver` (D7 lists its callers). Replace with:

```
achando vencedores. O historico de todos os ciclos, que o append-only daria
de graca, nao fica em lugar nenhum: a trilha de auditoria da TEC-206 nao
registra assumir nem devolver.
```

Then run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` and read every `ALTERADO`/`VIZINHO`/`PROSA`/`NOMEIA` entry. Fix any sentence Tasks 1–6 made false. In particular:
- `grep -rn "TEC-206" src tests --include=*.py` — every hit that still speaks of TEC-206 as future work (the old `registrar_negativa` docstring, the old `test_a_negativa_por_papel_registra_quem_tentou` docstring) must already be rewritten by Task 5; confirm, and fix any other.
- `src/mobia/domain/usuarios/permissoes.py`: the module docstring and the `DE_ESCRITA` comment mention TEC-195 auditing `VER_DADOS_COMPLETOS` — still true (TEC-195 is not delivered); leave.
- `src/mobia/domain/handoff/repositorio.py::HandoffRegistrado` says "os seis chamadores" — still six in `src/`; leave.
- Do not edit migrations' docstrings, `docs/superpowers/plans/*` or `CLAUDE.md`.

Never invent a card number: cite only those in the spec or already in the code.

- [ ] **Step 3: Status and checks**

Set the spec's `**Status:**` line to `implementado`. Run:

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Expected: `--checar` exits 0 (no `ANCORA`, no new `LINHA`), unit suite and gates green.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-25-tec-206-trilha-de-auditoria-design.md src/mobia/domain/atendimento/models.py <every other src/tests file you edited in Step 2>
git commit -m "docs(TEC-206): o SRS registra a trilha, os eventos sem chamador e a negativa persistida

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Final: suíte inteira, uma vez

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q`

If it comes back with hundreds of setup `ERROR`s or `CannotConnectNowError`, follow CLAUDE.md "Quando o `-n 8` derruba o Postgres" and run by blocks (`tests/unit`, `tests/integration`, `tests/features`). If dozens fail with `relation "eventos_auditoria" does not exist`, it is the worker databases with a stamp ahead of their DDL — see the same CLAUDE.md section before touching code. Record the commit hash with the result.
