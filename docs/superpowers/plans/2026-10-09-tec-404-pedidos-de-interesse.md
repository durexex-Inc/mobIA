# TEC-404 — Pedidos de interesse no painel: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam checkbox (`- [ ]`).

**Objetivo:** os pedidos de contato do portal aparecem numa tela do painel, `/interesses`. O admin vê todos e atribui cada um a um corretor; o corretor vê e assume os dele. Telefone e e-mail aparecem mascarados e se revelam um a um, com trilha.

**Arquitetura:**

- **Backend.** Um módulo de domínio novo, `domain/portal/pedidos.py`, faz a leitura: lista, recorte e revelação. Outro, `domain/handoff/atribuicao.py`, faz a escrita da atribuição. Duas rotas novas ficam em `api/routes/interesses.py` (listar e revelar) e uma em `api/routes/handoffs.py` (atribuir).
- **Dados.** A migration `0071` cria a coluna de e-mail cifrado e recria o `CHECK` de ações da trilha.
- **Front.** Uma página Server Component, componentes de cliente para revelar, assumir e atribuir, e entradas novas na allowlist do `/bff`.

**Stack:** FastAPI, SQLAlchemy async, Alembic, Postgres, ARQ/Redis; Next 16 (App Router), Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-tec-404-pedidos-de-interesse-design.md`. Leia a spec inteira antes da primeira tarefa: cada decisão citada aqui como `Dn` está lá, com o porquê.

## Restrições globais

- **Gates do CI, nesta ordem, antes de cada commit que toca Python:**
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m mypy`

  Sem pipe: `| tail` engole o exit code.
- **Antes de cada commit que toca o front:** `npx eslint <arquivos>` e `npx tsc --noEmit`. Ignore erros de `.next/dev/`, que são artefato do `next dev`. Vitest sempre com `--pool=threads`.
- **Acentos:**
  - comentários e docstrings em `src/` e `tests/`: **sem acento**;
  - texto que o usuário do painel lê (rótulos, mensagens): **com acento**;
  - assunto do commit: sem acento, no formato `tipo(TEC-404): o que passou a ser verdade`.
- **Fim do commit:** `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Escreva a mensagem num arquivo com a ferramenta Write e use `git commit -F`: heredoc quebra no hook do rtk, e `Set-Content` do PowerShell põe BOM.
- **Citação em `.md`:** por âncora `arquivo.py::Nome`, nunca por número de linha (`comentarios_tocados.py --checar` reprova).
- **Basename de teste:** nenhum arquivo novo em `tests/integration/` pode ter o mesmo basename de um em `tests/unit/`. A colisão aborta a coleta da suíte inteira.
- **Unitários rodam sem Docker** (`pytest tests/unit`). Integração exige `docker compose` de pé.
- **Telas novas** seguem o padrão de `app/(painel)/leads/page.tsx`: `exigirPermissao` antes de qualquer busca, 401 vira `redirect` para o login, e 403 vira `SemPermissao`.

## Foco da revisão

Cinco entradas que a spec implica e que mais provavelmente mordem; cada uma tem teste na tarefa dona:

1. **Corretor sem vínculo (`corretor_id` nulo no JWT) abrindo a lista:** tem de receber lista vazia, nunca a lista inteira (Task 4).
2. **Atribuir duas vezes ao mesmo corretor um atendimento ainda `PENDENTE`:** 200 sem efeito, sem trilha nova e sem job novo (Task 6).
3. **Cursor adulterado na URL (`?cursor=lixo`):** 422 com "cursor invalido", nunca volta à primeira página em silêncio (Task 4).
4. **Revelar o e-mail de um pedido anterior à migration (coluna nula):** `{valor: null}` com trilha gravada, sem 500 (Task 5).
5. **Atribuir a um corretor inativo, ou a um id que não existe:** 422, e o atendimento fica intacto (Task 6).

---

### Task 1: migration 0071 — e-mail cifrado e ação `HANDOFF_ATRIBUIDO` na trilha

**Arquivos:**
- Criar: `alembic/versions/0071_pedidos_de_interesse_no_painel.py`
- Modificar:
  - `src/mobia/domain/portal/interesse.py`: coluna `email_cifrado` e `aad_do_email_de_interesse`
  - `src/mobia/domain/auditoria/vocabulario.py`: `Acao.HANDOFF_ATRIBUIDO`, chaves de `detalhes`, `detalhes_da_atribuicao`
  - `src/mobia/admin/recifrar.py`: entrada em `COLUNAS_CIFRADAS`
  - `tests/unit/test_auditoria_vocabulario.py`: a migration mais recente que redefine as ações passa a ser a 0071
- Testes:
  - `tests/unit/test_auditoria_vocabulario.py`
  - `tests/unit/test_email_de_interesse_cifrado.py` (novo)

**Interfaces:**
- Produz:
  - `aad_do_email_de_interesse(solicitacao_id: uuid.UUID) -> str`
  - `SolicitacaoDeInteresse.email_cifrado: Mapped[bytes | None]`
  - `Acao.HANDOFF_ATRIBUIDO`
  - `detalhes_da_atribuicao(*, anterior: uuid.UUID | None, novo: uuid.UUID, aceito_desfeito: bool) -> dict[str, str | None]`

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_auditoria_vocabulario.py`, acrescente:

```python
import uuid

from mobia.domain.auditoria.vocabulario import (
    Acao,
    detalhes_da_atribuicao,
    validar_detalhes,
)


class TestDetalhesDaAtribuicao:
    def test_leva_os_dois_corretores_e_o_aceite(self) -> None:
        anterior, novo = uuid.uuid4(), uuid.uuid4()
        detalhes = detalhes_da_atribuicao(anterior=anterior, novo=novo, aceito_desfeito=True)
        assert detalhes == {
            "corretor_anterior": str(anterior),
            "corretor_novo": str(novo),
            "aceito_desfeito": "sim",
        }
        assert validar_detalhes(detalhes) == detalhes

    def test_sem_corretor_anterior_e_nulo(self) -> None:
        detalhes = detalhes_da_atribuicao(anterior=None, novo=uuid.uuid4(), aceito_desfeito=False)
        assert detalhes["corretor_anterior"] is None
        assert detalhes["aceito_desfeito"] == "nao"
        validar_detalhes(detalhes)

    def test_texto_livre_nas_chaves_de_corretor_e_recusado(self) -> None:
        with pytest.raises(ValueError):
            validar_detalhes({"corretor_novo": "Maria Silva"})

    def test_corretor_novo_nulo_e_recusado(self) -> None:
        with pytest.raises(ValueError):
            validar_detalhes({"corretor_novo": None})

    def test_a_acao_existe(self) -> None:
        assert Acao.HANDOFF_ATRIBUIDO.value == "HANDOFF_ATRIBUIDO"
```

Os testes parametrizados que já existem (`test_texto_livre_em_cada_chave_e_recusado`, `test_toda_chave_tem_vocabulario_de_valor` e `test_nulo_so_vale_para_permissao`) iteram sobre `CHAVES_DE_DETALHES` ou `_VALORES_DE_DETALHES`. Leia cada um e ajuste para as chaves novas:

- as chaves de UUID não têm conjunto de valores, e sim uma regra;
- `corretor_anterior` aceita nulo;
- o teste de nulo passa a dizer "só `permissao` e `corretor_anterior`".

Em `test_a_tupla_vem_da_migration_mais_recente`, troque a migration esperada para as ações, de `0063` para `0071`. As entidades continuam na `0063`.

Crie `tests/unit/test_email_de_interesse_cifrado.py`:

```python
"""TEC-404, D3 e D3a: o e-mail do pedido de interesse e coluna cifrada coberta pela rotacao."""

import uuid

from mobia.admin.recifrar import COLUNAS_CIFRADAS
from mobia.domain.portal.interesse import aad_do_email_de_interesse


def test_a_aad_amarra_o_email_a_linha() -> None:
    um, outro = uuid.uuid4(), uuid.uuid4()
    assert aad_do_email_de_interesse(um) != aad_do_email_de_interesse(outro)
    assert str(um) in aad_do_email_de_interesse(um)


def test_a_coluna_esta_na_rotacao_de_chave() -> None:
    # A guarda de `test_colunas_cifradas.py` so varre modulos `models.py`, e
    # `SolicitacaoDeInteresse` mora em `portal/interesse.py` (D3a da spec).
    alvo = next(
        c
        for c in COLUNAS_CIFRADAS
        if (c.tabela, c.coluna) == ("solicitacoes_de_interesse", "email_cifrado")
    )
    linha = uuid.uuid4()
    assert alvo.aad(linha) == aad_do_email_de_interesse(linha)
```

Confira em `admin/recifrar.py::ColunaCifrada` o nome real do campo da função de AAD (o teste acima supõe `aad`) e ajuste o teste ao nome real antes de rodar.

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/unit/test_email_de_interesse_cifrado.py -q --tb=short`

Esperado: FAIL com `ImportError` (`detalhes_da_atribuicao`, `aad_do_email_de_interesse`).

- [ ] **Step 3: Implementar o vocabulário**

Em `domain/auditoria/vocabulario.py`:

```python
class Acao(StrEnum):
    ...
    TITULAR_RECUSADO = "TITULAR_RECUSADO"
    # TEC-404, D6. O admin troca o corretor de um handoff pela tela de pedidos
    # de interesse. Entidade HANDOFF; `detalhes` diz de quem para quem, e se um
    # aceite foi desfeito (decisao 4 da card).
    HANDOFF_ATRIBUIDO = "HANDOFF_ATRIBUIDO"
```

Atualize a docstring do módulo: a 0071 recria o `CHECK` de `Acao`.

Troque `CHAVES_DE_DETALHES` e a validação:

```python
CHAVES_DE_DETALHES = frozenset(
    {
        "gatilho",
        "permissao",
        "motivo",
        "papel",
        "metodo",
        "corretor_anterior",
        "corretor_novo",
        "aceito_desfeito",
    }
)

# TEC-404, D6. Id de corretor nao e vocabulario fechado, mas tambem nao e texto
# livre: a regra e "UUID", e um texto qualquer continua sendo ValueError.
_CHAVES_DE_UUID: Mapping[str, bool] = {"corretor_anterior": True, "corretor_novo": False}
```

Em `_VALORES_DE_DETALHES`, acrescente `"aceito_desfeito": frozenset({"sim", "nao"})`. Em `validar_detalhes`, antes do laço de valores:

```python
    for chave, valor in detalhes.items():
        if chave in _CHAVES_DE_UUID:
            if valor is None:
                if _CHAVES_DE_UUID[chave]:
                    continue
                raise ValueError(f"detalhes.{chave} nao pode ser nulo")
            # TypeError/AttributeError: `test_valor_que_nao_e_texto_e_recusado`
            # manda int e afins, e `uuid.UUID(123)` nao levanta ValueError.
            try:
                uuid.UUID(valor)
            except (ValueError, TypeError, AttributeError) as erro:
                raise ValueError(f"detalhes.{chave} nao e UUID: {valor!r}") from erro
            continue
        if valor not in _VALORES_DE_DETALHES[chave]:
            raise ValueError(f"detalhes.{chave} fora do vocabulario: {valor!r}")
```

Isso substitui o laço atual. Atualize a docstring de `validar_detalhes`, que hoje diz que tudo é vocabulário fechado. Acrescente `import uuid` no topo e a função:

```python
def detalhes_da_atribuicao(
    *, anterior: uuid.UUID | None, novo: uuid.UUID, aceito_desfeito: bool
) -> dict[str, str | None]:
    """O `detalhes` de um HANDOFF_ATRIBUIDO (TEC-404, D6)."""
    return {
        "corretor_anterior": str(anterior) if anterior is not None else None,
        "corretor_novo": str(novo),
        "aceito_desfeito": "sim" if aceito_desfeito else "nao",
    }
```

- [ ] **Step 4: Implementar a coluna e a AAD**

Em `domain/portal/interesse.py`, acrescente ao modelo e ao módulo:

```python
from sqlalchemy import LargeBinary

from mobia.infra.crypto import aad_de


def aad_do_email_de_interesse(solicitacao_id: uuid.UUID) -> str:
    """Amarra o e-mail cifrado a linha do pedido (TEC-404, D3). Molde de
    `handoff/models.py::aad_do_resumo_de_handoff`: a identidade da linha e um
    UUID, e `aad_de` basta."""
    return aad_de(solicitacao_id, "email_interesse")
```

No modelo, logo depois de `nome`:

```python
    # TEC-404, D3. Cifrado; nulo nos pedidos anteriores a 0071 (sem backfill) e
    # em quem nao informou. Zerado pela anonimizacao junto com `nome`.
    email_cifrado: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
```

Em `admin/recifrar.py::COLUNAS_CIFRADAS`, acrescente:

```python
    ColunaCifrada(
        "solicitacoes_de_interesse", ("id",), "email_cifrado", aad_do_email_de_interesse
    ),
```

Importe `aad_do_email_de_interesse` de `mobia.domain.portal.interesse`.

- [ ] **Step 5: Escrever a migration**

`alembic/versions/0071_pedidos_de_interesse_no_painel.py`. Copie `_ACOES` da 0063, acrescente `"HANDOFF_ATRIBUIDO"` e mantenha o padrão de recriar o `CHECK` com downgrade `NOT VALID`:

```python
"""o pedido de interesse guarda o e-mail, e a trilha aprende a atribuicao

TEC-404. Duas coisas:

- **`solicitacoes_de_interesse.email_cifrado`** (bytea, nulo). Cifrado com
  `aad_do_email_de_interesse`. Sem backfill: pedidos anteriores ficam nulos (D3).
- **`HANDOFF_ATRIBUIDO`** em `eventos_auditoria.acao`. Como a 0057, a 0059 e a
  0063, o CHECK e RECRIADO -- o Postgres nao estende CHECK. `_ACOES` parte da
  tupla da 0063, a ultima que a redefine. O downgrade recria o antigo como
  `NOT VALID`, pela razao da 0057: linha de trilha nao sai.

Copia literal de `domain/auditoria/vocabulario.py::Acao`, e nao import.

Revision ID: 0071
Revises: 0070
"""

import sqlalchemy as sa

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

_ACOES = (
    "DADO_PESSOAL_ACESSADO",
    "QUALIFICACAO_ALTERADA",
    "HANDOFF_CRIADO",
    "OPTOUT_REGISTRADO",
    "OPTOUT_REATIVADO",
    "PROMPT_PUBLICADO",
    "ACESSO_NEGADO",
    "INJECAO_DETECTADA",
    "CONFIGURACAO_ALTERADA",
    "PROMPT_REVERTIDO",
    "TITULAR_SOLICITOU",
    "DADOS_EXPORTADOS",
    "LEAD_ANONIMIZADO",
    "TITULAR_RECUSADO",
    "HANDOFF_ATRIBUIDO",
)
_ACOES_ANTERIORES = _ACOES[:-1]
_CHECK = "ck_eventos_auditoria_acao"


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.add_column(
        "solicitacoes_de_interesse", sa.Column("email_cifrado", sa.LargeBinary(), nullable=True)
    )
    op.drop_constraint(_CHECK, "eventos_auditoria", type_="check")
    op.create_check_constraint(_CHECK, "eventos_auditoria", _em("acao", _ACOES))


def downgrade() -> None:
    op.drop_constraint(_CHECK, "eventos_auditoria", type_="check")
    op.execute(
        f"ALTER TABLE eventos_auditoria ADD CONSTRAINT {_CHECK} "
        f"CHECK ({_em('acao', _ACOES_ANTERIORES)}) NOT VALID"
    )
    op.drop_column("solicitacoes_de_interesse", "email_cifrado")
```

O teste de vocabulário procura a tupla `_ACOES` na migration mais recente que a define. Confira em `_tupla_da_migracao` que ele acha a da 0071, e que `_ENTIDADES` continua vindo da 0063.

- [ ] **Step 6: Rodar os testes**

Rodar:

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_vocabulario.py tests/unit/test_email_de_interesse_cifrado.py tests/unit/test_colunas_cifradas.py tests/unit/test_uma_cabeca_de_migration.py -q --tb=short
```

Esperado: PASS.

Com os containers de pé, rode também `./.venv/Scripts/python.exe -m alembic upgrade head`, depois `downgrade -1` e `upgrade head` de novo, no banco de dev. O esperado é que os três passem sem erro.

- [ ] **Step 7: Gates e commit**

Rode os três gates. Commit com o assunto `feat(TEC-404): pedido de interesse guarda e-mail cifrado e trilha conhece a atribuicao`.

---

### Task 2: o portal grava o e-mail, e a anonimização o apaga

**Arquivos:**
- Modificar:
  - `src/mobia/domain/portal/interesse.py::registrar_interesse`: parâmetro `email`
  - `src/mobia/api/routes/portal.py::solicitar_interesse`: passa `pedido.email`
  - `src/mobia/domain/titular/anonimizacao.py`: zera `email_cifrado`
- Testes:
  - `tests/integration/test_portal_interesse_endpoint.py`: acrescentar
  - o teste de integração da anonimização que já cobre `nome` desta tabela; ache-o com Grep por `solicitacoes_de_interesse` em `tests/`

**Interfaces:**
- Consome: `aad_do_email_de_interesse` (Task 1).
- Produz: `registrar_interesse(session, *, imovel_id, channel, conversation_key, nome, email, agora) -> bool`.

- [ ] **Step 1: Teste que falha**

Em `tests/integration/test_portal_interesse_endpoint.py`:

```python
from mobia.domain.portal.interesse import aad_do_email_de_interesse
from mobia.infra.crypto import decrypt


async def test_o_email_fica_cifrado_na_coluna_propria(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse",
        json={"telefone": "11988887777", "nome": "Maria", "email": "maria@ex.com"},
    )
    assert resposta.status_code == 201, resposta.text

    linha = (
        (await session.execute(text("SELECT id, email_cifrado FROM solicitacoes_de_interesse")))
        .mappings()
        .one()
    )
    assert linha["email_cifrado"] is not None
    assert b"maria@ex.com" not in bytes(linha["email_cifrado"])
    assert (
        decrypt(bytes(linha["email_cifrado"]), aad_do_email_de_interesse(linha["id"]))
        == "maria@ex.com"
    )


async def test_sem_email_a_coluna_fica_nula(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    await client.post(f"/portal/imoveis/{identificador}/interesse", json={"telefone": "11988887777"})

    email = (
        await session.execute(text("SELECT email_cifrado FROM solicitacoes_de_interesse"))
    ).scalar_one()
    assert email is None
```

No teste de anonimização, semeie a linha com `email_cifrado` preenchido e acrescente a asserção de que ela termina nula, ao lado da de `nome`.

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_portal_interesse_endpoint.py -q --tb=short`

Esperado: FAIL (`email_cifrado` nulo).

- [ ] **Step 3: Implementar**

Em `registrar_interesse`, gere o id antes, para a AAD:

```python
async def registrar_interesse(
    session: AsyncSession,
    *,
    imovel_id: uuid.UUID,
    channel: str,
    conversation_key: str,
    nome: str | None,
    email: str | None,
    agora: datetime,
) -> bool:
    """... (docstring atual) ...

    `email` vai cifrado em `email_cifrado` (TEC-404, D3). No conflito -- o mesmo
    lead pedindo o mesmo imovel de novo -- a linha antiga fica como estava, e o
    e-mail novo se perde: e a deduplicacao da TEC-389, nao bug.
    """
    solicitacao_id = uuid.uuid4()
    resultado = cast(
        CursorResult[Any],
        await session.execute(
            pg_insert(SolicitacaoDeInteresse)
            .values(
                id=solicitacao_id,
                imovel_id=imovel_id,
                channel=channel,
                conversation_key=conversation_key,
                nome=nome,
                email_cifrado=encrypt(email, aad_do_email_de_interesse(solicitacao_id)),
                criado_em=agora,
            )
            .on_conflict_do_nothing(index_elements=["channel", "conversation_key", "imovel_id"])
        ),
    )
    return resultado.rowcount == 1
```

`encrypt(None, ...)` devolve `None` (`infra/crypto.py::encrypt`). Importe `encrypt` de `mobia.infra.crypto`.

Em `portal.py::solicitar_interesse`, passe `email=pedido.email` na chamada. Confira se algum outro chamador de `registrar_interesse` (Grep) precisa do argumento novo.

Em `titular/anonimizacao.py`, troque o `UPDATE` para `SET nome = NULL, email_cifrado = NULL` e atualize o comentário acima dele: e-mail também é dado que identifica.

- [ ] **Step 4: Rodar os testes**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_portal_interesse_endpoint.py <arquivo da anonimizacao> -q --tb=short`

Esperado: PASS.

- [ ] **Step 5: Gates e commit**

Assunto: `feat(TEC-404): portal grava o e-mail do pedido cifrado`.

---

### Task 3: `telefones_de` acha o telefone do lead do portal

**Arquivos:**
- Modificar: `src/mobia/domain/identidade/indice.py::telefones_de`
- Teste: o teste de integração que já cobre `telefones_de`; ache-o com Grep. Se não houver um com Postgres, crie `tests/integration/test_telefones_do_portal.py`.

**Interfaces:**
- Produz: `telefones_de(session, pares)` devolve o telefone também para pares com `channel == "portal"`.

- [ ] **Step 1: Teste que falha**

```python
"""TEC-404, D8: o lead do portal guarda o telefone em IdentidadeDeLead, como o WhatsApp."""

from mobia.domain.identidade.indice import registrar, telefones_de
from mobia.domain.messages.canais import CANAL_PORTAL


async def test_telefone_do_lead_do_portal(session) -> None:
    chave = await registrar(session, CANAL_PORTAL, "5511988887777")
    await session.commit()

    telefones = await telefones_de(session, [(CANAL_PORTAL, chave)])

    assert telefones[(CANAL_PORTAL, chave)] == "5511988887777"
```

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest <arquivo> -q --tb=short`

Esperado: FAIL, com `None` no lugar do número.

- [ ] **Step 3: Implementar**

Em `telefones_de`, os canais que guardam em `IdentidadeDeLead` passam a ser WhatsApp **e** portal:

```python
# Os canais cujo telefone mora em `IdentidadeDeLead`: o WhatsApp (o `wa_id`) e,
# desde a TEC-404, o portal -- `portal.py::solicitar_interesse` registra o
# telefone digitado no formulario la, e nao em `VinculoDeSessao`.
_CANAIS_COM_IDENTIDADE = frozenset({CANAL_WHATSAPP, CANAL_PORTAL})
```

Troque `channel == CANAL_WHATSAPP` por `channel in _CANAIS_COM_IDENTIDADE` nas duas filtragens de `pares`. Na consulta, troque `IdentidadeDeLead.channel == CANAL_WHATSAPP, IdentidadeDeLead.conversation_key.in_(...)` por `tuple_(IdentidadeDeLead.channel, IdentidadeDeLead.conversation_key).in_(dos_com_identidade)`, com a lista de pares em vez da de chaves.

Atualize a docstring: ela fala de "duas origens", e o portal entra na primeira.

- [ ] **Step 4: Rodar este teste e os testes de `indice`/leads que já existem**

Rodar: `./.venv/Scripts/python.exe -m pytest <arquivo> tests/unit -q --tb=short -k "telefone or indice"`

Esperado: PASS.

- [ ] **Step 5: Gates e commit**

Assunto: `fix(TEC-404): telefones_de acha o telefone do lead do portal`.

---

### Task 4: listagem de pedidos — domínio e `GET /api/v1/interesses`

**Arquivos:**
- Criar:
  - `src/mobia/domain/portal/pedidos.py`: consulta, cursor, montagem do item
  - `src/mobia/api/routes/interesses.py`: router `/api/v1/interesses`
- Modificar:
  - `src/mobia/app/main.py`: `include_router`
  - `src/mobia/domain/leads/mascara.py::mascarar_email`: a docstring deixa de dizer "sem chamador"
- Testes:
  - `tests/unit/test_cursor_de_pedidos.py` (novo)
  - `tests/integration/test_lista_de_pedidos_de_interesse.py` (novo)

**Interfaces:**
- Consome: `telefones_de` (Task 3), `aad_do_email_de_interesse` (Task 1), `referencias_para` (`domain/leads/repositorio.py`), `RecorteDoPapel` (`domain/leads/consulta.py`).
- Produz, em `domain/portal/pedidos.py`:
  - `class Estado(StrEnum): PENDENTES = "pendentes"; TODOS = "todos"`
  - `@dataclass(frozen=True) class CursorDePedidos: criado_em: datetime; id: uuid.UUID`, com `codificar() -> str`
  - `decodificar_cursor(texto: str) -> CursorDePedidos`, que levanta `CursorInvalido(ValueError)`
  - `@dataclass(frozen=True) class Atendimento: id, status, corretor_id, corretor_nome, notificado_em, sem_corretor`
  - `@dataclass(frozen=True) class PedidoDaLista: id, criado_em, imovel_id, imovel_codigo, imovel_titulo, nome, telefone_mascarado, email_mascarado, lead_id, channel, conversation_key, atendimento: Atendimento | None`
  - `async def listar_pedidos(session, *, estado: Estado, limite: int, cursor: CursorDePedidos | None, recorte: RecorteDoPapel) -> tuple[list[PedidoDaLista], CursorDePedidos | None]`
  - `async def atendimento_do_pedido(session, solicitacao_id: uuid.UUID) -> tuple[SolicitacaoDeInteresse, Handoff | None] | None`, usada pela Task 5
- A rota devolve:

```
{ itens: [{ id, criadoEm, imovel: {id, codigo, titulo}, nome, telefoneMascarado,
            emailMascarado, leadId,
            atendimento: {id, status, corretor: {id, nome}|null, notificadoEm, semCorretor}|null }],
  proximoCursor }
```

- [ ] **Step 1: Teste unitário do cursor, que falha**

`tests/unit/test_cursor_de_pedidos.py`:

```python
"""TEC-404, D8: o cursor da lista de pedidos e opaco e recusa lixo."""

import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.portal.pedidos import CursorDePedidos, CursorInvalido, decodificar_cursor


def test_ida_e_volta() -> None:
    cursor = CursorDePedidos(criado_em=datetime(2026, 10, 9, 16, 48, tzinfo=UTC), id=uuid.uuid4())
    assert decodificar_cursor(cursor.codificar()) == cursor


@pytest.mark.parametrize("texto", ["lixo", "", "eyJ4IjoxfQ=="])
def test_lixo_e_cursor_invalido(texto: str) -> None:
    with pytest.raises(CursorInvalido):
        decodificar_cursor(texto)
```

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/unit/test_cursor_de_pedidos.py -q --tb=short`

Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Testes de integração da listagem, que falham**

`tests/integration/test_lista_de_pedidos_de_interesse.py`. Semeie pela rota do portal (`POST /portal/imoveis/{id}/interesse`), que cria o pedido, o handoff e a identidade. Grave o `corretor_id` direto no handoff para simular a notificação:

```python
"""TEC-404: GET /api/v1/interesses -- quem ve o que, mascarado, paginado."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text, update

from mobia.domain.handoff.models import Handoff
from tests.conftest import cabecalho_de
from tests.integration.test_portal_interesse_endpoint import _semear as _semear_imovel


async def _pedir(client: AsyncClient, imovel_id: uuid.UUID, telefone: str, **extra: str) -> None:
    resposta = await client.post(
        f"/portal/imoveis/{imovel_id}/interesse", json={"telefone": telefone, **extra}
    )
    assert resposta.status_code == 201, resposta.text


async def _vincular(session: Any, corretor_id: uuid.UUID | None) -> None:
    await session.execute(update(Handoff).values(corretor_id=corretor_id))
    await session.commit()


async def test_admin_ve_o_pedido_mascarado(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777", nome="Juarez", email="juarez@ex.com")

    resposta = await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))

    assert resposta.status_code == 200, resposta.text
    [item] = resposta.json()["itens"]
    assert item["nome"] == "Juarez"
    assert item["telefoneMascarado"] == "+55 11 9****-**77"
    assert item["emailMascarado"] == "j****z@e*.com"
    assert item["imovel"]["id"] == str(imovel)
    assert item["atendimento"]["status"] == "PENDENTE"
    assert item["atendimento"]["corretor"] is None
    assert "11988887777" not in resposta.text
    assert "juarez@ex.com" not in resposta.text


async def test_corretor_so_ve_os_dele(
    client: AsyncClient, session: Any, semear_corretor
) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")
    await _vincular(session, a.id)

    do_a = await client.get("/api/v1/interesses", headers=cabecalho_de("CORRETOR", corretor_id=a.id))
    do_b = await client.get("/api/v1/interesses", headers=cabecalho_de("CORRETOR", corretor_id=b.id))

    assert len(do_a.json()["itens"]) == 1
    assert do_b.json()["itens"] == []


async def test_corretor_sem_vinculo_recebe_lista_vazia(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")

    resposta = await client.get("/api/v1/interesses", headers=cabecalho_de("CORRETOR"))

    assert resposta.status_code == 200
    assert resposta.json()["itens"] == []


async def test_segundo_imovel_do_mesmo_telefone_aponta_o_mesmo_atendimento(
    client: AsyncClient, session: Any
) -> None:
    primeiro = await _semear_imovel(session)
    segundo = await _semear_imovel(session)
    await _pedir(client, primeiro, "11988887777")
    await _pedir(client, segundo, "11988887777")

    itens = (await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))).json()["itens"]

    assert len(itens) == 2
    assert itens[0]["atendimento"]["id"] == itens[1]["atendimento"]["id"]


async def test_filtro_pendentes_esconde_aceito(client: AsyncClient, session: Any) -> None:
    imovel = await _semear_imovel(session)
    await _pedir(client, imovel, "11988887777")
    await session.execute(text("UPDATE handoffs SET status = 'ACEITO', aceito_em = now()"))
    await session.commit()

    pendentes = await client.get("/api/v1/interesses", headers=cabecalho_de("ADMIN"))
    todos = await client.get("/api/v1/interesses?estado=todos", headers=cabecalho_de("ADMIN"))

    assert pendentes.json()["itens"] == []
    assert len(todos.json()["itens"]) == 1


async def test_paginacao_sem_repetir(client: AsyncClient, session: Any) -> None:
    for telefone in ("11988880001", "11988880002", "11988880003"):
        await _pedir(client, await _semear_imovel(session), telefone)

    primeira = (
        await client.get("/api/v1/interesses?limite=2", headers=cabecalho_de("ADMIN"))
    ).json()
    segunda = (
        await client.get(
            f"/api/v1/interesses?limite=2&cursor={primeira['proximoCursor']}",
            headers=cabecalho_de("ADMIN"),
        )
    ).json()

    ids = [i["id"] for i in primeira["itens"]] + [i["id"] for i in segunda["itens"]]
    assert len(ids) == 3 == len(set(ids))
    assert segunda["proximoCursor"] is None


async def test_cursor_adulterado_e_422(client: AsyncClient) -> None:
    resposta = await client.get("/api/v1/interesses?cursor=lixo", headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 422
    assert resposta.json()["detail"] == "cursor invalido"


async def test_estado_desconhecido_e_422(client: AsyncClient) -> None:
    resposta = await client.get("/api/v1/interesses?estado=x", headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 422


async def test_sem_token_e_403(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/interesses")).status_code == 403
```

Antes de fixar as máscaras esperadas, rode `mascarar_telefone("5511988887777")` e `mascarar_email("juarez@ex.com")` uma vez no REPL. Os literais acima seguem as docstrings de `domain/leads/mascara.py`, e o teste tem de bater com a função, não com a minha conta.

Se importar `_semear` de outro arquivo de teste violar uma regra de lint do repo, copie a função para este arquivo em vez de importar.

- [ ] **Step 4: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_lista_de_pedidos_de_interesse.py -q --tb=short`

Esperado: FAIL com 404, porque a rota não existe.

- [ ] **Step 5: Implementar `domain/portal/pedidos.py`**

```python
"""Os pedidos de interesse do portal, como o painel os le. TEC-404.

D4 da spec: cada pedido aponta para o handoff mais recente do mesmo lead
criado ate o momento do pedido -- o que nasceu junto com ele ou o que ja estava
aberto. D8: lista mascarada, por `criado_em` decrescente, keyset por
(`criado_em`, `id`), sem total. O recorte do CORRETOR vem da claim do JWT
(`RecorteDoPapel`), nunca da query.
"""

import base64
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Select, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.identidade.indice import telefones_de
from mobia.domain.leads.consulta import RecorteDoPapel
from mobia.domain.leads.mascara import mascarar_email, mascarar_telefone
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.portal.interesse import SolicitacaoDeInteresse, aad_do_email_de_interesse
from mobia.infra.crypto import decrypt


class Estado(StrEnum):
    PENDENTES = "pendentes"
    TODOS = "todos"


# "Pendente" para a tela e o que ainda espera alguem: PENDENTE ou ESCALADO --
# os mesmos `ACEITAVEIS` do aceite.
_PENDENTES = (Status.PENDENTE.value, Status.ESCALADO.value)


class CursorInvalido(ValueError):
    pass


@dataclass(frozen=True)
class CursorDePedidos:
    criado_em: datetime
    id: uuid.UUID

    def codificar(self) -> str:
        """base64 de um JSON, opaco como o cursor de `leads/consulta.py`."""
        corpo = json.dumps({"c": self.criado_em.isoformat(), "i": str(self.id)})
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor(texto: str) -> CursorDePedidos:
    """Recusa, e nao volta para a primeira pagina -- mesma regra de
    `leads/consulta.py::decodificar_cursor`."""
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        return CursorDePedidos(
            criado_em=datetime.fromisoformat(corpo["c"]), id=uuid.UUID(corpo["i"])
        )
    except (ValueError, KeyError, TypeError) as erro:
        raise CursorInvalido("cursor invalido") from erro


@dataclass(frozen=True)
class Atendimento:
    id: uuid.UUID
    status: str
    corretor_id: uuid.UUID | None
    corretor_nome: str | None
    notificado_em: datetime | None
    sem_corretor: bool


@dataclass(frozen=True)
class PedidoDaLista:
    id: uuid.UUID
    criado_em: datetime
    imovel_id: uuid.UUID
    imovel_codigo: str
    imovel_titulo: str
    nome: str | None
    telefone_mascarado: str | None
    email_mascarado: str | None
    lead_id: uuid.UUID
    channel: str
    conversation_key: str
    atendimento: Atendimento | None


def _handoff_do_pedido() -> Select[tuple[Handoff]]:
    """O handoff mais recente do mesmo lead, criado ate o pedido (D4). LATERAL."""
    return (
        select(Handoff)
        .where(
            Handoff.channel == SolicitacaoDeInteresse.channel,
            Handoff.conversation_key == SolicitacaoDeInteresse.conversation_key,
            Handoff.criado_em <= SolicitacaoDeInteresse.criado_em,
        )
        .order_by(Handoff.criado_em.desc())
        .limit(1)
    )


async def listar_pedidos(
    session: AsyncSession,
    *,
    estado: Estado,
    limite: int,
    cursor: CursorDePedidos | None,
    recorte: RecorteDoPapel,
) -> tuple[list[PedidoDaLista], CursorDePedidos | None]:
    """A pagina pedida e o cursor da proxima. Pede `limite + 1` para saber se ha mais."""
    if recorte.nao_ve_nada:
        return [], None

    handoff = _handoff_do_pedido().lateral("h")
    consulta = (
        select(SolicitacaoDeInteresse, Imovel.codigo, Imovel.titulo, handoff, Corretor.nome)
        .join(Imovel, Imovel.id == SolicitacaoDeInteresse.imovel_id)
        .outerjoin(handoff, true())
        .outerjoin(Corretor, Corretor.id == handoff.c.corretor_id)
        .order_by(SolicitacaoDeInteresse.criado_em.desc(), SolicitacaoDeInteresse.id.desc())
        .limit(limite + 1)
    )
    if estado is Estado.PENDENTES:
        consulta = consulta.where(handoff.c.status.in_(_PENDENTES))
    if recorte.e_corretor:
        consulta = consulta.where(handoff.c.corretor_id == recorte.corretor_id)
    if cursor is not None:
        consulta = consulta.where(
            or_(
                SolicitacaoDeInteresse.criado_em < cursor.criado_em,
                and_(
                    SolicitacaoDeInteresse.criado_em == cursor.criado_em,
                    SolicitacaoDeInteresse.id < cursor.id,
                ),
            )
        )

    linhas = (await session.execute(consulta)).all()
    visiveis = linhas[:limite]
    pares = [(linha[0].channel, linha[0].conversation_key) for linha in visiveis]
    apelidos = await referencias_para(session, pares)
    telefones = await telefones_de(session, pares)

    pagina = [_montar(linha, apelidos, telefones) for linha in visiveis]
    proximo = (
        CursorDePedidos(criado_em=pagina[-1].criado_em, id=pagina[-1].id)
        if len(linhas) > limite and pagina
        else None
    )
    return pagina, proximo
```

`_montar(linha, apelidos, telefones) -> PedidoDaLista` faz o seguinte:

- decifra `email_cifrado` com `aad_do_email_de_interesse(pedido.id)`;
- mascara o e-mail com `mascarar_email`, e o telefone com `mascarar_telefone` quando `telefones[par]` não é `None`;
- monta `Atendimento` só se as colunas do lateral vierem preenchidas (`handoff.c.id` não nulo), com `sem_corretor=aviso_manual_pendente`.

Leia as colunas do lateral pela linha mapeada: `linha._mapping[handoff.c.status]` e assim por diante. Ajuste `select(...)` para listar as colunas do lateral que o item usa (`handoff.c.id`, `status`, `corretor_id`, `notificado_em`, `aviso_manual_pendente`) em vez de `handoff` inteiro, se o SQLAlchemy reclamar. O mypy dirá se a tipagem do `Row` precisa de `cast`.

`atendimento_do_pedido(session, solicitacao_id)` roda a mesma consulta lateral filtrada por `SolicitacaoDeInteresse.id == solicitacao_id`. Devolve `(solicitacao, handoff_ou_none)`, ou `None` se o pedido não existe. Para devolver o `Handoff` como entidade, faça um segundo `session.get(Handoff, id)` a partir do id do lateral.

- [ ] **Step 6: Implementar a rota**

`src/mobia/api/routes/interesses.py`:

```python
"""Os pedidos de interesse do portal no painel. TEC-404.

`GET` lista (D8) e `POST /{id}/revelar` (D5, Task 5). Guardadas por `VER_LEADS`
e, para revelar, pela regra propria da D5 -- o CORRETOR revela so os dele.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.domain.leads.consulta import RecorteDoPapel
from mobia.domain.portal.pedidos import (
    CursorInvalido,
    Estado,
    PedidoDaLista,
    decodificar_cursor,
    listar_pedidos,
)
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/interesses", tags=["interesses"])

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 100


def _item(pedido: PedidoDaLista) -> dict[str, object]:
    atendimento = pedido.atendimento
    return {
        "id": str(pedido.id),
        "criadoEm": pedido.criado_em.isoformat(),
        "imovel": {
            "id": str(pedido.imovel_id),
            "codigo": pedido.imovel_codigo,
            "titulo": pedido.imovel_titulo,
        },
        "nome": pedido.nome,
        "telefoneMascarado": pedido.telefone_mascarado,
        "emailMascarado": pedido.email_mascarado,
        "leadId": str(pedido.lead_id),
        "atendimento": None
        if atendimento is None
        else {
            "id": str(atendimento.id),
            "status": atendimento.status,
            "corretor": None
            if atendimento.corretor_id is None
            else {"id": str(atendimento.corretor_id), "nome": atendimento.corretor_nome},
            "notificadoEm": atendimento.notificado_em.isoformat()
            if atendimento.notificado_em
            else None,
            "semCorretor": atendimento.sem_corretor,
        },
    }


@router.get("")
async def listar(
    estado: Annotated[Estado, Query()] = Estado.PENDENTES,
    limite: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
    cursor: Annotated[str | None, Query()] = None,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Os pedidos do mais recente ao mais antigo. Sem `total`, como `/leads`."""
    try:
        posicao = decodificar_cursor(cursor) if cursor else None
    except CursorInvalido as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="cursor invalido"
        ) from erro

    async with get_sessionmaker()() as session:
        pagina, proximo = await listar_pedidos(
            session,
            estado=estado,
            limite=limite,
            cursor=posicao,
            recorte=RecorteDoPapel(
                e_corretor=identidade.e_corretor, corretor_id=identidade.corretor_id
            ),
        )
        # `referencias_para` cria apelidos que so existem depois do commit --
        # mesma razao de `leads.py::listar`.
        await session.commit()

    return {"itens": [_item(p) for p in pagina], "proximoCursor": proximo.codificar() if proximo else None}
```

Em `app/main.py`, importe e registre `interesses_router` junto dos outros routers autenticados, depois de `leads_router`. Rode `test_toda_rota_declara_autorizacao`: a rota tem `Exige`, então deve passar sem entrar em `ROTAS_PUBLICAS`.

Atualize a docstring de `mascarar_email`: ela diz "Esta funcao NAO TEM CHAMADOR"; desde a TEC-404 o chamador é `domain/portal/pedidos.py`, com o e-mail do pedido de interesse.

- [ ] **Step 7: Rodar os testes**

Rodar:

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_cursor_de_pedidos.py tests/integration/test_lista_de_pedidos_de_interesse.py tests/unit/test_autorizacao_em_toda_rota.py -q --tb=short
```

Esperado: PASS.

- [ ] **Step 8: Gates e commit**

Assunto: `feat(TEC-404): GET /api/v1/interesses lista os pedidos do portal`.

---

### Task 5: revelar telefone e e-mail do pedido

**Arquivos:**
- Modificar:
  - `src/mobia/domain/portal/pedidos.py`: `valor_do_pedido`
  - `src/mobia/api/routes/interesses.py`: `POST /{solicitacao_id}/revelar`
- Teste: `tests/integration/test_revelar_pedido_de_interesse.py` (novo)

**Interfaces:**
- Consome: `atendimento_do_pedido` (Task 4), `identidade/indice.py::revelar`, `registrar_evento`, `exigir_dono`.
- Produz:
  - `async def valor_do_pedido(session, solicitacao: SolicitacaoDeInteresse, campo: str) -> str | None`
  - rota `POST /api/v1/interesses/{id}/revelar` com `{campo}`, que devolve `{campo, valor}`.

- [ ] **Step 1: Testes que falham**

Mesmo arquivo de apoio da Task 4 (`_pedir`, `_vincular`, `_semear_imovel`). Copie as duas funções auxiliares para este arquivo.

```python
"""TEC-404, D5: quem revela telefone e e-mail do pedido, e a trilha."""

async def _id_do_pedido(session: Any) -> uuid.UUID:
    return (await session.execute(text("SELECT id FROM solicitacoes_de_interesse"))).scalar_one()


async def _eventos(session: Any) -> list[Any]:
    return (
        (await session.execute(text("SELECT acao, campo, entidade FROM eventos_auditoria")))
        .mappings()
        .all()
    )


async def test_admin_revela_telefone_e_a_trilha_registra(client, session) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777", email="j@ex.com")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"campo": "telefone", "valor": "+5511988887777"}
    [evento] = [e for e in await _eventos(session) if e["acao"] == "DADO_PESSOAL_ACESSADO"]
    assert evento["campo"] == "telefone"
    assert evento["entidade"] == "lead"


async def test_admin_revela_email(client, session) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777", email="j@ex.com")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar", json={"campo": "email"}, headers=cabecalho_de("ADMIN")
    )

    assert resposta.json()["valor"] == "j@ex.com"


async def test_email_ausente_e_nulo_com_trilha(client, session) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar", json={"campo": "email"}, headers=cabecalho_de("ADMIN")
    )

    assert resposta.status_code == 200
    assert resposta.json()["valor"] is None
    assert any(e["campo"] == "email" for e in await _eventos(session))


async def test_corretor_dono_revela(client, session, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await _vincular(session, a.id)
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("CORRETOR", corretor_id=a.id),
    )

    assert resposta.status_code == 200


async def test_corretor_alheio_e_403_e_negativa_na_trilha(client, session, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    await _pedir(client, await _semear_imovel(session), "11988887777")
    await _vincular(session, a.id)
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar",
        json={"campo": "telefone"},
        headers=cabecalho_de("CORRETOR", corretor_id=b.id),
    )

    assert resposta.status_code == 403
    acoes = [e["acao"] for e in await _eventos(session)]
    assert "ACESSO_NEGADO" in acoes
    assert "DADO_PESSOAL_ACESSADO" not in acoes


async def test_leitura_sem_ver_dados_completos_e_403(client, session) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar", json={"campo": "telefone"}, headers=cabecalho_de("LEITURA")
    )

    assert resposta.status_code == 403


async def test_campo_desconhecido_e_422(client, session) -> None:
    await _pedir(client, await _semear_imovel(session), "11988887777")
    pedido = await _id_do_pedido(session)

    resposta = await client.post(
        f"/api/v1/interesses/{pedido}/revelar", json={"campo": "cpf"}, headers=cabecalho_de("ADMIN")
    )

    assert resposta.status_code == 422


async def test_pedido_inexistente_e_404(client) -> None:
    resposta = await client.post(
        f"/api/v1/interesses/{uuid.uuid4()}/revelar", json={"campo": "telefone"}, headers=cabecalho_de("ADMIN")
    )
    assert resposta.status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_revelar_pedido_de_interesse.py -q --tb=short`

Esperado: FAIL com 404/405.

- [ ] **Step 3: Implementar**

Em `domain/portal/pedidos.py`:

```python
async def valor_do_pedido(
    session: AsyncSession, solicitacao: SolicitacaoDeInteresse, campo: str
) -> str | None:
    """O valor em claro. So chamada DEPOIS de a trilha ter sido comitada (D5)."""
    if campo == CAMPO_EMAIL:
        return decrypt(solicitacao.email_cifrado, aad_do_email_de_interesse(solicitacao.id))
    try:
        telefone = await revelar_identidade(
            session, solicitacao.channel, solicitacao.conversation_key
        )
    except IdentidadeAusente:
        return None
    return f"+{telefone}"
```

Importe `CAMPO_EMAIL` de `domain/auditoria/vocabulario.py`, e `revelar as revelar_identidade` e `IdentidadeAusente` de `domain/identidade/indice.py`.

Na rota, guardada por **`Exige(Permissao.VER_LEADS)`**, e não por `VER_DADOS_COMPLETOS`: a regra da D5 é mais fina que uma permissão e mora no corpo.

```python
class PedidoDeRevelacao(BaseModel):
    campo: str


@router.post("/{solicitacao_id}/revelar")
async def revelar(
    solicitacao_id: uuid.UUID,
    pedido: PedidoDeRevelacao,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Telefone ou e-mail do pedido, em claro (D5).

    Quem tem `VER_DADOS_COMPLETOS` revela qualquer pedido; o CORRETOR, so os
    cujo handoff (D4) e dele (decisao 5 da card). O resto e 403, com
    `ACESSO_NEGADO` na trilha. A trilha e COMITADA antes do valor sair, molde de
    `leads.py::revelar`.
    """
    if pedido.campo not in CAMPOS_REVELAVEIS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"campo nao revelavel: {pedido.campo}",
        )

    async with get_sessionmaker()() as session:
        encontrado = await atendimento_do_pedido(session, solicitacao_id)
        if encontrado is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pedido nao existe")
        solicitacao, handoff = encontrado

        if not identidade.pode(Permissao.VER_DADOS_COMPLETOS):
            if not identidade.e_corretor:
                await registrar_negativa(
                    request, Permissao.VER_DADOS_COMPLETOS, identidade=identidade
                )
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
            await exigir_dono(
                request,
                identidade,
                permissao=Permissao.VER_LEADS,
                corretor_id=handoff.corretor_id if handoff is not None else None,
            )

        par = (solicitacao.channel, solicitacao.conversation_key)
        apelido = (await referencias_para(session, [par]))[par]
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADO_PESSOAL_ACESSADO,
            entidade=Entidade.LEAD,
            entidade_id=str(apelido),
            campo=pedido.campo,
            lead=par,
            origem=origem_da_requisicao(request),
        )
        await session.commit()

        valor = await valor_do_pedido(session, solicitacao, pedido.campo)

    return {"campo": pedido.campo, "valor": valor}
```

`registrar_negativa` e `exigir_dono` vêm de `mobia.api.autorizacao`. O 403 tem de ter o detalhe `"forbidden"`, que é o que `_negar` produz; confira a mensagem que os outros 403 desta API devolvem e use a mesma.

- [ ] **Step 4: Rodar os testes**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_revelar_pedido_de_interesse.py -q --tb=short`

Esperado: PASS.

- [ ] **Step 5: Gates e commit**

Assunto: `feat(TEC-404): revelar telefone e e-mail do pedido, com trilha`.

---

### Task 6: atribuir o atendimento a um corretor

**Arquivos:**
- Criar: `src/mobia/domain/handoff/atribuicao.py`
- Modificar: `src/mobia/api/routes/handoffs.py`, que ganha a rota `atribuir`. Corrija também o comentário obsoleto em `aceitar` ("`corretor_id` e gravado no nascimento do handoff"): ele é gravado pela notificação (E-06) e, desde a TEC-404, pela atribuição.
- Teste: `tests/integration/test_atribuir_handoff.py` (novo)

**Interfaces:**
- Consome:
  - `detalhes_da_atribuicao`, `Acao.HANDOFF_ATRIBUIDO` (Task 1);
  - `NOTIFICAR_JOB` (`domain/notificacao/envio.py`);
  - `notificar` (`domain/notificacao/envio.py`), só no teste do prazo.
- Produz:
  - `class AtribuicaoRecusada(Exception)`, com `motivo: str` em `{"corretor_invalido", "nao_existe", "concluido"}`
  - `@dataclass(frozen=True) class Atribuicao: mudou: bool; aceito_desfeito: bool`
  - `async def atribuir(session, *, handoff_id: uuid.UUID, corretor_id: uuid.UUID, ator: Ator, origem: Origem | None) -> Atribuicao`. Não commita.
  - `def id_do_job_de_atribuicao(handoff_id: uuid.UUID) -> str`, que devolve `f"notificar:{handoff_id}:atribuicao:{uuid4()}"`
  - rota `POST /api/v1/handoffs/{id}/atribuir` com `{corretorId}`, que devolve `{status, corretorId, aceitoDesfeito}`.

- [ ] **Step 1: Testes que falham**

`tests/integration/test_atribuir_handoff.py`:

```python
"""TEC-404, D1, D6 e D7: o admin troca o corretor, e o prazo recomeca."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from tests.conftest import cabecalho_de


async def _handoff(session: Any, semear_handoff_com_resumo) -> uuid.UUID:
    return await semear_handoff_com_resumo(resumo="texto")


async def _linha(session: Any, handoff_id: uuid.UUID) -> Handoff:
    session.expire_all()
    return (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()


async def _jobs(redis_pool) -> list[bytes]:
    return [k for k in await redis_pool.keys("arq:job:notificar:*")]


async def test_atribui_handoff_sem_corretor(
    client, session, semear_corretor, semear_handoff_com_resumo, redis_pool
) -> None:
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(corretor_id=None, aviso_manual_pendente=True, status=Status.ESCALADO.value)
    )
    await session.commit()
    a = await semear_corretor(email="a@ex.com")

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    linha = await _linha(session, handoff_id)
    assert linha.corretor_id == a.id
    assert linha.status == Status.PENDENTE
    assert linha.aviso_manual_pendente is False
    assert linha.sla_limite_em is None
    assert linha.notificado_em is None
    assert any(b":atribuicao:" in k for k in await _jobs(redis_pool))


async def test_aceito_por_a_passa_para_b_e_a_trilha_registra(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    agora = datetime.now(UTC)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(
            corretor_id=a.id,
            status=Status.ACEITO.value,
            aceito_em=agora,
            notificado_em=agora,
            sla_limite_em=agora + timedelta(hours=4),
        )
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(b.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.json()["aceitoDesfeito"] is True
    linha = await _linha(session, handoff_id)
    assert (linha.corretor_id, linha.status, linha.aceito_em) == (b.id, Status.PENDENTE, None)
    evento = (
        (
            await session.execute(
                text("SELECT detalhes FROM eventos_auditoria WHERE acao = 'HANDOFF_ATRIBUIDO'")
            )
        )
        .mappings()
        .one()
    )
    assert evento["detalhes"] == {
        "corretor_anterior": str(a.id),
        "corretor_novo": str(b.id),
        "aceito_desfeito": "sim",
    }


async def test_mesmo_corretor_em_pendente_nao_faz_nada(
    client, session, semear_corretor, semear_handoff_com_resumo, redis_pool
) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()
    antes = await _jobs(redis_pool)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200
    assert await _jobs(redis_pool) == antes
    assert (
        await session.execute(
            text("SELECT count(*) FROM eventos_auditoria WHERE acao = 'HANDOFF_ATRIBUIDO'")
        )
    ).scalar_one() == 0


async def test_corretor_inativo_e_422_e_nada_muda(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    inativo = await semear_corretor(email="i@ex.com", ativo=False)
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    antes = (await _linha(session, handoff_id)).corretor_id

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(inativo.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 422
    assert (await _linha(session, handoff_id)).corretor_id == antes


async def test_corretor_inexistente_e_422(client, session, semear_handoff_com_resumo) -> None:
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(uuid.uuid4())},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_concluido_e_409(client, session, semear_corretor, semear_handoff_com_resumo) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    await session.execute(
        update(Handoff).where(Handoff.id == handoff_id).values(status=Status.CONCLUIDO.value)
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 409


async def test_inexistente_e_404(client, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    resposta = await client.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 404


async def test_corretor_e_gerente_nao_atribuem(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    for papel in ("CORRETOR", "GERENTE"):
        resposta = await client.post(
            f"/api/v1/handoffs/{handoff_id}/atribuir",
            json={"corretorId": str(a.id)},
            headers=cabecalho_de(papel, corretor_id=a.id if papel == "CORRETOR" else None),
        )
        assert resposta.status_code == 403


class _CanalEspiao:
    """Copia do duble de `test_notificacao_envio.py` -- sem importar de outro teste."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[str] = []

    async def enviar(self, *, destino: str, aviso: Any) -> None:
        self.recebidas.append(destino)


class _OutboundFalso:
    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        return True


# Dois pares de jornada ~12h opostos, como `_CANDIDATOS_DE_JANELA` de
# `test_notificacao_envio.py`: o de B e escolhido de modo que AGORA esteja fora
# dele. Assim o prazo de B so pode cair dentro da janela de B -- e o de A, que
# esta dentro da propria jornada agora, cairia no mesmo dia, fora dela.
_JANELAS: tuple[tuple[int, int], ...] = ((2, 9), (14, 21))


async def test_a_notificacao_seguinte_conta_o_prazo_pela_jornada_do_novo(
    client, session, session_factory, semear_corretor, semear_handoff_com_resumo, settings
) -> None:
    """D1: o prazo recomeca pela jornada de B, e nao pela de A."""
    fuso = ZoneInfo(settings.fuso_de_envio)
    hora = datetime.now(fuso).hour
    dentro, fora = (
        _JANELAS if _JANELAS[0][0] <= hora < _JANELAS[0][1] else (_JANELAS[1], _JANELAS[0])
    )
    a = await semear_corretor(email="a@ex.com", horario_inicio=dentro[0], horario_fim=dentro[1])
    b = await semear_corretor(email="b@ex.com", horario_inicio=fora[0], horario_fim=fora[1])
    handoff_id = await _handoff(session, semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(b.id)},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 200, resposta.text

    # O que o worker faria com o job enfileirado.
    email = _CanalEspiao("email")
    await notificar(session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id)

    linha = await _linha(session, handoff_id)
    assert linha.corretor_id == b.id
    assert email.recebidas == [b.email]
    assert linha.sla_limite_em is not None
    limite = linha.sla_limite_em.astimezone(fuso)
    assert fora[0] <= limite.hour <= fora[1]
```

Imports adicionais do arquivo: `from zoneinfo import ZoneInfo` e `from mobia.domain.notificacao.envio import notificar`.

Se o `hora` da máquina cair fora das duas janelas (de 21h a 2h, ou de 9h a 14h), `dentro` fica sendo a segunda e o teste continua válido: B é a janela que não contém agora, e o prazo dele tem de cair nela. Confira em `test_notificacao_envio.py` como aquele arquivo escolhe o candidato e, se a regra lá for outra, copie a de lá.

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `./.venv/Scripts/python.exe -m pytest tests/integration/test_atribuir_handoff.py -q --tb=short`

Esperado: FAIL com 404/405.

- [ ] **Step 3: Implementar `domain/handoff/atribuicao.py`**

```python
"""A atribuicao manual do handoff pelo admin. TEC-404, D1.

**Segundo escritor de `handoffs.corretor_id`** (Emenda E-07 da RN-16.2): ate a
TEC-404 so `notificacao/envio.py::notificar` o gravava, e so quando nulo. Aqui
ele e SOBRESCRITO de proposito -- e o admin trocando o dono. A regra "so quando
nulo" continua valendo para a notificacao, que e o que protege o dono contra
uma retentativa do ARQ.

**Atribuir desfaz o aceite e reinicia o prazo** (decisao 4 da card; Emenda E-08
da RN-16.3). O handoff volta a PENDENTE sem `aceito_em`, sem `sla_limite_em` e
sem `notificado_em`; a notificacao enfileirada pela rota calcula o prazo pela
jornada do NOVO corretor, porque `notificar` so calcula prazo quando ele e
nulo e o status e PENDENTE. `sweep_sla` nao precisa mudar: `escalar_vencidos`
olha PENDENTE com prazo vencido, e `recuperar_sem_prazo` cobre o intervalo ate
a notificacao rodar.

Nao commita: a trilha e a escrita commitam juntas, ou nenhuma das duas.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.registro import Origem, registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade, detalhes_da_atribuicao
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status


class AtribuicaoRecusada(Exception):
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Atribuicao:
    mudou: bool
    aceito_desfeito: bool


def id_do_job_de_atribuicao(handoff_id: uuid.UUID) -> str:
    """Id NOVO a cada atribuicao: o `notificar:{id}` da primeira notificacao pode
    estar retido no Redis como resultado, e o ARQ descartaria um job com o mesmo
    id (D1)."""
    return f"notificar:{handoff_id}:atribuicao:{uuid.uuid4()}"


async def atribuir(
    session: AsyncSession,
    *,
    handoff_id: uuid.UUID,
    corretor_id: uuid.UUID,
    ator: Ator,
    origem: Origem | None,
) -> Atribuicao:
    corretor = await session.get(Corretor, corretor_id)
    if corretor is None or not corretor.ativo:
        raise AtribuicaoRecusada("corretor_invalido")

    # FOR UPDATE: a mesma linha que `aceitar` e `escalar_vencidos` disputam; a
    # leitura e a escrita abaixo nao podem ver estados diferentes dela.
    handoff = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
    ).scalar_one_or_none()
    if handoff is None:
        raise AtribuicaoRecusada("nao_existe")
    if handoff.status == Status.CONCLUIDO:
        raise AtribuicaoRecusada("concluido")

    if handoff.corretor_id == corretor_id and handoff.status == Status.PENDENTE:
        # D7: atribuir de novo ao mesmo dono de um handoff ainda pendente nao
        # reenvia aviso nem escreve trilha.
        return Atribuicao(mudou=False, aceito_desfeito=False)

    anterior = handoff.corretor_id
    aceito_desfeito = handoff.status == Status.ACEITO
    agora = datetime.now(UTC)
    handoff.corretor_id = corretor_id
    handoff.status = Status.PENDENTE.value
    handoff.aceito_em = None
    handoff.sla_limite_em = None
    handoff.notificado_em = None
    handoff.aviso_manual_pendente = False
    handoff.atualizado_em = agora

    await registrar_evento(
        session,
        ator=ator,
        acao=Acao.HANDOFF_ATRIBUIDO,
        entidade=Entidade.HANDOFF,
        entidade_id=str(handoff_id),
        lead=(handoff.channel, handoff.conversation_key),
        detalhes=detalhes_da_atribuicao(
            anterior=anterior, novo=corretor_id, aceito_desfeito=aceito_desfeito
        ),
        origem=origem,
    )
    return Atribuicao(mudou=True, aceito_desfeito=aceito_desfeito)
```

Confira como `Handoff.status` é tipado no modelo (`str` ou `Status`): se a comparação `== Status.CONCLUIDO` não bater com `str`, compare com `.value`. O mypy aponta.

- [ ] **Step 4: Implementar a rota**

Em `api/routes/handoffs.py`:

```python
class PedidoDeAtribuicao(BaseModel):
    corretorId: uuid.UUID  # noqa: N815


_STATUS_DA_RECUSA = {
    "corretor_invalido": (status.HTTP_422_UNPROCESSABLE_CONTENT, "corretor inexistente ou inativo"),
    "nao_existe": (status.HTTP_404_NOT_FOUND, "handoff nao existe"),
    "concluido": (status.HTTP_409_CONFLICT, "handoff concluido"),
}


@router.post("/{handoff_id}/atribuir")
async def atribuir_handoff(
    handoff_id: uuid.UUID,
    pedido: PedidoDeAtribuicao,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.GERIR_CORRETORES)),
) -> dict[str, object]:
    """O admin troca o corretor do handoff -- TEC-404, D1 e D7.

    `GERIR_CORRETORES`, que so o ADMIN tem: e a mesma permissao de
    `GET /api/v1/corretores`, que preenche o seletor da tela. A notificacao e
    enfileirada DEPOIS do commit: um job que rodasse antes leria o handoff
    ainda com o corretor antigo.
    """
    async with get_sessionmaker()() as session:
        try:
            resultado = await atribuir(
                session,
                handoff_id=handoff_id,
                corretor_id=pedido.corretorId,
                ator=identidade.como_ator(),
                origem=origem_da_requisicao(request),
            )
        except AtribuicaoRecusada as recusa:
            codigo, detalhe = _STATUS_DA_RECUSA[recusa.motivo]
            raise HTTPException(status_code=codigo, detail=detalhe) from recusa
        await session.commit()

    if resultado.mudou:
        pool = getattr(request.app.state, "redis_pool", None)
        if pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sem pool do Redis no app: a notificacao nao foi enfileirada",
            )
        await pool.enqueue_job(
            NOTIFICAR_JOB, str(handoff_id), _job_id=id_do_job_de_atribuicao(handoff_id)
        )

    return {
        "status": Status.PENDENTE.value if resultado.mudou else None,
        "corretorId": str(pedido.corretorId),
        "aceitoDesfeito": resultado.aceito_desfeito,
    }
```

Para um job que falhar ao ser enfileirado depois do commit, não trate como erro de negócio. `recuperar_sem_prazo` o reenfileira, porque o handoff ficou PENDENTE sem prazo e sem `notificado_em`. Deixe isso dito num comentário na rota.

Atualize a docstring do módulo `handoffs.py`: ele passa a ter três rotas, e a terceira é do ADMIN.

- [ ] **Step 5: Rodar os testes**

Rodar:

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_atribuir_handoff.py tests/integration/test_rota_de_aceite.py tests/unit/test_autorizacao_em_toda_rota.py -q --tb=short
```

Esperado: PASS.

- [ ] **Step 6: Gates e commit**

Assunto: `feat(TEC-404): admin atribui o atendimento a um corretor e o prazo recomeca`.

---

### Task 7: emendas ao SRS e comentários que a branch tornou falsos

**Arquivos:**
- Modificar:
  - `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`: E-07 abaixo de RN-16.2 e E-08 abaixo de RN-16.3
  - `src/mobia/domain/notificacao/envio.py`: a docstring do módulo diz "E o unico escritor de `handoffs.corretor_id`"
  - `src/mobia/domain/auditoria/vocabulario.py`: o comentário de `CAMPO_EMAIL` diz "Sem fonte: nenhuma tabela deste sistema guarda e-mail de lead"

- [ ] **Step 1: As emendas**

Abaixo do último item aninhado de **RN-16.2** (a Emenda E-06), acrescente, com a mesma indentação:

```markdown
  - **Emenda E-07 (TEC-404, 09/10/2026):** `handoffs.corretor_id` ganha um **segundo escritor**: a atribuição manual do admin pela tela de pedidos de interesse (`src/mobia/domain/handoff/atribuicao.py::atribuir`). Ao contrário da notificação, ela **sobrescreve** de propósito — é o admin trocando o dono. A regra da Emenda E-06 de gravar apenas quando a coluna está nula continua valendo para a notificação, que é o que protege o dono contra uma retentativa do ARQ. Ver a D1 do desenho da TEC-404.
```

Abaixo do último item aninhado de **RN-16.3** (a Emenda E-07 dela), acrescente:

```markdown
  - **Emenda E-08 (TEC-404, 09/10/2026):** a atribuição manual **reinicia o SLA**. O handoff volta a `PENDENTE`, sem `aceito_em`, sem `sla_limite_em` e sem `notificado_em`, e a notificação ao novo corretor calcula o prazo pela jornada dele (Emenda E-01). Um handoff `ESCALADO` atribuído volta a `PENDENTE` pelo mesmo caminho. Um aceite desfeito assim sai de `aceito_em`, e por isso não entra na taxa de aceite no prazo da RN-17.1.
```

Antes de escrever, confira com Grep que a última emenda de RN-16.3 é mesmo a E-07; se não for, use o número seguinte ao último.

- [ ] **Step 2: Os comentários**

- Em `notificacao/envio.py`, a docstring do módulo passa a dizer que esta função é o escritor de `corretor_id` **na notificação**, e que desde a TEC-404 (E-07) há um segundo, a atribuição manual, que sobrescreve.
- Em `auditoria/vocabulario.py`, o comentário de `CAMPO_EMAIL` passa a dizer que a fonte, desde a TEC-404, é `solicitacoes_de_interesse.email_cifrado`. A rota de leads continua devolvendo nulo para e-mail; só a revelação do pedido o lê.

- [ ] **Step 3: Listagem de comentários e checagem de citações**

Rodar: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`. Releia cada `VIZINHO` e `ALTERADO` dos arquivos da branch e corrija o que mentir.

Rodar: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`

Esperado: "Nenhuma ancora quebrada".

- [ ] **Step 4: Commit**

Assunto: `docs(TEC-404): emendas E-07 da RN-16.2 e E-08 da RN-16.3`.

---

### Task 8: front — tipos, busca no servidor, menu e allowlist

**Arquivos:**
- Criar:
  - `frontend/src/lib/interesses.ts`: tipos e funções puras (estado da URL, rótulo do estado)
  - `frontend/src/lib/servidor/interesses.ts`: `buscarInteresses`
- Modificar:
  - `frontend/src/lib/navegacao.ts`: item "Pedidos de interesse"
  - `frontend/src/lib/servidor/bff.ts`: três entradas na allowlist
- Testes:
  - `frontend/src/lib/interesses.test.ts`
  - `frontend/src/lib/navegacao.test.ts`
  - `frontend/src/lib/servidor/bff.test.ts`

**Interfaces:**
- Produz, em `lib/interesses.ts`:

```ts
export type EstadoDosPedidos = 'pendentes' | 'todos'
export type AtendimentoDoPedido = {
  id: string
  status: 'PENDENTE' | 'ACEITO' | 'ESCALADO' | 'CONCLUIDO'
  corretor: { id: string; nome: string } | null
  notificadoEm: string | null
  semCorretor: boolean
}
export type PedidoDeInteresse = {
  id: string
  criadoEm: string
  imovel: { id: string; codigo: string; titulo: string }
  nome: string | null
  telefoneMascarado: string | null
  emailMascarado: string | null
  leadId: string
  atendimento: AtendimentoDoPedido | null
}
export type PaginaDePedidos = { itens: PedidoDeInteresse[]; proximoCursor: string | null }
export function estadoDaUrl(valor: string | string[] | undefined): EstadoDosPedidos
export function urlDosPedidos(estado: EstadoDosPedidos, cursor?: string): string
export function rotuloDoAtendimento(atendimento: AtendimentoDoPedido | null): string
export function podeAssumir(atendimento: AtendimentoDoPedido | null, corretorId: string | null): boolean
export function podeRevelarPedido(
  atendimento: AtendimentoDoPedido | null,
  quem: { permissoes: ReadonlySet<string>; corretorId: string | null },
): boolean
```

- Produz, em `lib/servidor/interesses.ts`: `buscarInteresses({ estado, cursor }, acesso): Promise<PaginaDePedidos>`, que lança `ErroDeInteresses(status, mensagem, requestId)`.

- [ ] **Step 1: Testes que falham**

`frontend/src/lib/interesses.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import {
  estadoDaUrl,
  podeAssumir,
  podeRevelarPedido,
  rotuloDoAtendimento,
  urlDosPedidos,
  type AtendimentoDoPedido,
} from './interesses'

const atendimento = (extra: Partial<AtendimentoDoPedido> = {}): AtendimentoDoPedido => ({
  id: 'h-1',
  status: 'PENDENTE',
  corretor: { id: 'c-a', nome: 'Ana' },
  notificadoEm: null,
  semCorretor: false,
  ...extra,
})

describe('estadoDaUrl / urlDosPedidos', () => {
  it('padrao e pendentes; valor desconhecido tambem', () => {
    expect(estadoDaUrl(undefined)).toBe('pendentes')
    expect(estadoDaUrl('qualquer')).toBe('pendentes')
    expect(estadoDaUrl(['todos'])).toBe('todos')
  })

  it('pendentes sem cursor e a URL limpa', () => {
    expect(urlDosPedidos('pendentes')).toBe('/interesses')
    expect(urlDosPedidos('todos', 'abc')).toBe('/interesses?estado=todos&cursor=abc')
  })
})

describe('rotuloDoAtendimento', () => {
  it('sem corretor vence o status', () => {
    expect(rotuloDoAtendimento(atendimento({ semCorretor: true, corretor: null, status: 'ESCALADO' }))).toBe(
      'Sem corretor',
    )
  })

  it('cada status tem rotulo com acento', () => {
    expect(rotuloDoAtendimento(atendimento())).toBe('Pendente')
    expect(rotuloDoAtendimento(atendimento({ status: 'ACEITO' }))).toBe('Assumido')
    expect(rotuloDoAtendimento(atendimento({ status: 'ESCALADO' }))).toBe('Escalado')
    expect(rotuloDoAtendimento(atendimento({ status: 'CONCLUIDO' }))).toBe('Concluído')
    expect(rotuloDoAtendimento(null)).toBe('Sem atendimento')
  })
})

describe('podeAssumir', () => {
  it('so o corretor dono, e so pendente ou escalado', () => {
    expect(podeAssumir(atendimento(), 'c-a')).toBe(true)
    expect(podeAssumir(atendimento({ status: 'ESCALADO' }), 'c-a')).toBe(true)
    expect(podeAssumir(atendimento({ status: 'ACEITO' }), 'c-a')).toBe(false)
    expect(podeAssumir(atendimento(), 'c-b')).toBe(false)
    expect(podeAssumir(atendimento(), null)).toBe(false)
    expect(podeAssumir(null, 'c-a')).toBe(false)
  })
})

describe('podeRevelarPedido', () => {
  it('VER_DADOS_COMPLETOS revela qualquer um', () => {
    expect(podeRevelarPedido(null, { permissoes: new Set(['VER_DADOS_COMPLETOS']), corretorId: null })).toBe(true)
  })

  it('corretor so o dele', () => {
    const quem = { permissoes: new Set(['VER_LEADS']), corretorId: 'c-a' }
    expect(podeRevelarPedido(atendimento(), quem)).toBe(true)
    expect(podeRevelarPedido(atendimento({ corretor: { id: 'c-b', nome: 'Bia' } }), quem)).toBe(false)
    expect(podeRevelarPedido(atendimento({ corretor: null }), quem)).toBe(false)
  })
})
```

Em `navegacao.test.ts`, acrescente: quem tem `VER_LEADS` vê `{ rotulo: 'Pedidos de interesse', href: '/interesses' }`, logo depois de Leads; quem não tem, não vê.

Em `bff.test.ts`, acrescente que `caminhoPermitido` libera:

- `('POST', ['api','v1','handoffs','h-1','aceitar'])`;
- `('POST', ['api','v1','handoffs','h-1','atribuir'])`;
- `('POST', ['api','v1','interesses','p-1','revelar'])`;

e recusa `('GET', ['api','v1','interesses'])`, porque a lista é lida pelo Server Component, não pelo navegador.

- [ ] **Step 2: Rodar e ver falhar**

Rodar: `cd frontend; npx vitest run --pool=threads src/lib/interesses.test.ts src/lib/navegacao.test.ts src/lib/servidor/bff.test.ts`

Esperado: FAIL.

- [ ] **Step 3: Implementar**

`lib/interesses.ts`: as funções acima.

- `rotuloDoAtendimento`: `semCorretor` → "Sem corretor"; `null` → "Sem atendimento"; o resto, um mapa `{PENDENTE:'Pendente', ACEITO:'Assumido', ESCALADO:'Escalado', CONCLUIDO:'Concluído'}`.
- `podeRevelarPedido`: `permissoes.has('VER_DADOS_COMPLETOS') || (corretorId !== null && atendimento?.corretor?.id === corretorId)`.

Cabeçalho do módulo, sem acento, citando a TEC-404 e a D5/D9 da spec. Diga que a regra de revelação aqui é só para **mostrar o botão**: quem decide é o backend (`interesses.py::revelar`).

`lib/servidor/interesses.ts`, no molde de `lib/servidor/leads.ts::buscarLeads`: `import 'server-only'`, `chamarApi('/api/v1/interesses', { acesso, busca })` com `estado` e `cursor` quando houver, sem cache, e `ErroDeInteresses` com `detalheDe` (de `@/lib/metricas`).

`lib/navegacao.ts`: depois de Leads, `{ rotulo: 'Pedidos de interesse', href: '/interesses', visivel: (p) => p.has('VER_LEADS') }`. Mesma permissão da rota.

`lib/servidor/bff.ts::ROTAS_PERMITIDAS`, antes das rotas de configuração, com um comentário que explica:

- o aceite é a primeira vez que o navegador chama `handoffs/*/aceitar` direto (até aqui ele só aceitava via `assumir`);
- atribuir é do ADMIN, e quem decide é o FastAPI;
- revelar o pedido grava na trilha.

```ts
  { metodo: 'POST', padrao: ['api', 'v1', 'handoffs', '*', 'aceitar'] },
  { metodo: 'POST', padrao: ['api', 'v1', 'handoffs', '*', 'atribuir'] },
  { metodo: 'POST', padrao: ['api', 'v1', 'interesses', '*', 'revelar'] },
```

Atualize a contagem "desde a TEC-326 sao sete" do docstring de `ROTAS_PERMITIDAS` se ela falar das rotas de lead; a revelação de pedido é uma rota de dado pessoal a mais.

- [ ] **Step 4: Rodar os testes, eslint e tsc**

Rodar: `npx vitest run --pool=threads src/lib/interesses.test.ts src/lib/navegacao.test.ts src/lib/servidor/bff.test.ts`, depois `npx eslint` nos arquivos e `npx tsc --noEmit`.

Esperado: PASS e nenhum erro em `src/`.

- [ ] **Step 5: Commit**

Assunto: `feat(TEC-404): tipos, busca, menu e allowlist dos pedidos de interesse`.

---

### Task 9: front — página `/interesses` e ações de linha

**Arquivos:**
- Criar:
  - `frontend/src/app/(painel)/interesses/page.tsx`
  - `frontend/src/components/TabelaDePedidos.tsx`: Server Component, a tabela
  - `frontend/src/components/AcoesDoPedido.tsx`: `'use client'`, Assumir e Atribuir
- Modificar: `frontend/src/components/DadoRevelavel.tsx`, que ganha a prop opcional `url`
- Testes:
  - `frontend/src/app/(painel)/interesses/page.test.tsx`
  - `frontend/src/components/AcoesDoPedido.test.tsx`
  - `frontend/src/components/DadoRevelavel.test.tsx`: acrescentar

**Interfaces:**
- Consome: tudo da Task 8; `buscarCorretores` (`lib/servidor/leads.ts`); `exigirPermissao` (`lib/servidor/quemSou.ts`).
- Produz:
  - `DadoRevelavel` com a prop opcional `url?: string`. O padrão continua sendo `/bff/api/v1/leads/${leadId}/revelar`.
  - `<AcoesDoPedido atendimento corretorId podeAtribuir corretores />`.

- [ ] **Step 1: Testes que falham**

Em `DadoRevelavel.test.tsx`:

```tsx
  it('com `url`, pede a revelacao nela, e nao na rota do lead', async () => {
    render(
      <DadoRevelavel
        leadId="l-1"
        campo="email"
        mascarado="j****z@e*.com"
        podeRevelar
        url="/bff/api/v1/interesses/p-1/revelar"
      />,
    )

    await clicar('Revelar e-mail')

    expect(api).toHaveBeenCalledExactlyOnceWith(
      '/bff/api/v1/interesses/p-1/revelar',
      expect.objectContaining({ method: 'POST', body: '{"campo":"email"}' }),
    )
  })
```

`AcoesDoPedido.test.tsx`. Use o molde de stubs de `DadoRevelavel.test.tsx` e mocke `next/navigation` com `useRouter: () => ({ refresh })`:

```tsx
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

import { AcoesDoPedido } from './AcoesDoPedido'

const PENDENTE_DA_ANA = {
  id: 'h-1',
  status: 'PENDENTE' as const,
  corretor: { id: 'c-a', nome: 'Ana' },
  notificadoEm: null,
  semCorretor: false,
}
const CORRETORES = [
  { id: 'c-a', nome: 'Ana' },
  { id: 'c-b', nome: 'Bia' },
]

describe('AcoesDoPedido', () => {
  let api: ReturnType<typeof vi.fn>
  beforeEach(() => {
    refresh.mockReset()
    api = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('o corretor dono assume pelo aceite e a tela recarrega', async () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={[]} />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Assumir' })))

    expect(api).toHaveBeenCalledWith('/bff/api/v1/handoffs/h-1/aceitar', expect.objectContaining({ method: 'POST' }))
    expect(refresh).toHaveBeenCalled()
  })

  it('quem nao e o dono nao ve Assumir', () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-b" podeAtribuir={false} corretores={[]} />)
    expect(screen.queryByRole('button', { name: 'Assumir' })).toBeNull()
  })

  it('o admin atribui a outro corretor', async () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId={null} podeAtribuir corretores={CORRETORES} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Corretor' }), { target: { value: 'c-b' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Atribuir' })))

    expect(api).toHaveBeenCalledWith(
      '/bff/api/v1/handoffs/h-1/atribuir',
      expect.objectContaining({ method: 'POST', body: '{"corretorId":"c-b"}' }),
    )
    expect(refresh).toHaveBeenCalled()
  })

  it('sem podeAtribuir nao ha seletor', () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={CORRETORES} />)
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('recusa mostra o motivo e nao recarrega', async () => {
    api.mockResolvedValueOnce(new Response('{"detail":"handoff ja aceito"}', { status: 409 }))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={[]} />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Assumir' })))

    expect(screen.getByRole('alert')).toHaveTextContent('Este pedido já foi assumido.')
    expect(refresh).not.toHaveBeenCalled()
  })
})
```

`app/(painel)/interesses/page.test.tsx`. Copie o cabeçalho de mocks de `app/(painel)/leads/page.test.tsx` (armazém em memória, cookies, `next/navigation` com `redirect` e `useRouter`, e o `fetch` que responde `/auth/me` e a lista). Casos:

1. Admin vê a linha com imóvel, nome, telefone mascarado e "Sem corretor" destacado quando `semCorretor`.
2. O pedido sai para `/api/v1/interesses` com `estado=pendentes` por padrão, e com `estado=todos` quando a URL pede.
3. Sem `VER_LEADS`, "Sem permissão".
4. Lista vazia: "Nenhum pedido de interesse pendente." (ou "Nenhum pedido de interesse." em `todos`).
5. Com `proximoCursor`, há o link "Próxima página" para `urlDosPedidos(estado, cursor)`.
6. O admin (`GERIR_CORRETORES`) recebe o seletor de corretores; um CORRETOR não.

- [ ] **Step 2: Rodar e ver falhar**

Rodar:

```
npx vitest run --pool=threads src/components/DadoRevelavel.test.tsx src/components/AcoesDoPedido.test.tsx "src/app/(painel)/interesses"
```

Esperado: FAIL.

- [ ] **Step 3: Implementar `DadoRevelavel`**

Acrescente `url?: string` às props. No `fetch`, use `url ?? \`/bff/api/v1/leads/${encodeURIComponent(leadId)}/revelar\``. A mensagem de 404 ("Este lead não existe mais.") vira "Este registro não existe mais." quando `url` foi passada. Atualize a docstring: o componente agora serve leads e pedidos de interesse.

- [ ] **Step 4: Implementar `AcoesDoPedido`**

`'use client'`.

- **Botão "Assumir"** quando `podeAssumir(atendimento, corretorId)`. Faz `POST /bff/api/v1/handoffs/${id}/aceitar`.
- **Com `podeAtribuir` e um atendimento não `CONCLUIDO`:**
  - um `<label>` "Corretor" e um `<select>` com os `corretores`, que começa no corretor atual;
  - o botão "Atribuir", desabilitado enquanto o selecionado for o atual;
  - o botão faz `POST /bff/api/v1/handoffs/${id}/atribuir` com `{corretorId}`.
- **Em 200:** `router.refresh()`.
- **Fora disso**, uma mensagem em `role="alert"`:
  - 401: "Sua sessão terminou. Recarregue a página para entrar de novo."
  - 403: "Você não tem permissão para esta ação."
  - 404: "Este pedido não existe mais."
  - 409 no aceite: "Este pedido já foi assumido."
  - 409 na atribuição: "Este atendimento já foi concluído."
  - 422: "Escolha um corretor ativo."
  - o resto: "Não foi possível concluir. Tente de novo."
- Botões desabilitados enquanto envia.

- [ ] **Step 5: Implementar `TabelaDePedidos` e a página**

`TabelaDePedidos({ itens, quem, corretores })`, Server Component. Colunas:

| coluna | conteúdo |
| --- | --- |
| Pedido em | data em `pt-BR` |
| Imóvel | código e título, com link para `/busca/{id}` (portal) e para `/admin/imoveis/{id}` quando `GERIR_CATALOGO` |
| Nome | o nome, ou "não informado" |
| Telefone | `DadoRevelavel` com `url=/bff/api/v1/interesses/{id}/revelar` e `podeRevelar=podeRevelarPedido(...)` |
| E-mail | `DadoRevelavel`, idem |
| Situação | `rotuloDoAtendimento`, e o nome do corretor quando houver |
| Ações | `AcoesDoPedido` |

A linha recebe a classe `pedido--sem-corretor` quando `atendimento?.semCorretor`. Acrescente o estilo em `globals.css`, no molde dos estados de destaque que já existem: Grep por `--alerta` ou pela cor de aviso usada no painel.

`page.tsx`, no molde de `leads/page.tsx`:

- `exigirPermissao(endereco, (p) => p.has('VER_LEADS'))`;
- `estadoDaUrl` e o `cursor` da URL;
- `buscarInteresses`, com 401 → apagar sessão e redirecionar, e 403 → `SemPermissao`;
- `buscarCorretores` só com `GERIR_CORRETORES`;
- um filtro com dois links, "Pendentes" e "Todos", com `aria-current` no ativo;
- a tabela, ou o `Vazio`;
- o link "Próxima página" quando houver `proximoCursor`;
- `metadata.title = 'Pedidos de interesse — mobIA'`.

- [ ] **Step 6: Rodar os testes, eslint e tsc**

Rodar:

```
npx vitest run --pool=threads src/components src/app/(painel)
```

Depois `npx eslint` nos arquivos novos e alterados, e `npx tsc --noEmit`.

Esperado: PASS.

- [ ] **Step 7: Commit**

Assunto: `feat(TEC-404): tela de pedidos de interesse no painel`.

---

### Task 10: verificação de ponta a ponta e fechamento

- [ ] **Step 1: Gates completos**

Os três gates Python. Depois `ruff format` nos arquivos se o `--check` reclamar, e rode de novo. `npx tsc --noEmit` no front.

- [ ] **Step 2: Suítes**

- Backend, por blocos (ver "Quando o `-n 8` derruba o Postgres" no CLAUDE.md):

  ```
  ./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
  ./.venv/Scripts/python.exe -m pytest tests/integration --tb=short -q
  ./.venv/Scripts/python.exe -m pytest tests/features --tb=short -q
  ```

  Dezenas de `CannotConnectNowError` de uma vez é o banco caído, não a branch. Confira `docker logs mobia-postgres-1` antes de investigar código.
- Front: `npx vitest run --pool=threads`.

Guarde o hash junto com o resultado.

- [ ] **Step 3: Ver funcionando**

1. Com a API, o worker (`python -m arq mobia.workers.main.WorkerSettings`) e o `next dev` de pé, cadastre um corretor ativo.
2. Peça contato pelo portal num imóvel disponível.
3. Abra `/interesses` como admin. O pedido aparece; se o worker já rodou e havia corretor, com o nome dele; senão, "Sem corretor".
4. Revele telefone e e-mail.
5. Atribua a outro corretor e confira a situação "Pendente" com o nome novo.
6. Entre como o corretor e assuma.

Registre o que viu: é critério de aceite da card.

- [ ] **Step 4: Listagem de comentários**

Rode `scripts/comentarios_tocados.py` e `--checar` de novo e trate o que aparecer.

- [ ] **Step 5: Push e PR**

1. `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push -u origin feat/tec-404-pedidos-de-interesse`
2. `gh pr create --base main` com corpo em português: o que muda, decisões, emendas ao SRS, verificação, e o rodapé `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 6: Card**

Comente na TEC-404 com:

- o link do PR;
- as divergências em relação ao texto da card, pelo menos estas:
  - a revelação pelo corretor (decisão 5, desta conversa);
  - a correção de `telefones_de`;
  - o aceite continua sem trilha;
  - o e-mail novo de um pedido repetido se perde;
  - um atendimento de WhatsApp do mesmo telefone não se liga ao pedido;
- as emendas E-07 e E-08, nomeadas;
- o critério de aceite que não tiver sido exercitado no navegador.

Depois mova a card para **Em análise** (transição 31).
