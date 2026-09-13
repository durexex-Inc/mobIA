"""O CRUD de corretores, guardado pelo token de admin."""

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.api.routes.corretores import CorretorEditado
from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.corretores.repositorio import CAMPOS_EDITAVEIS

TOKEN = "token-de-teste-de-corretores"

CORPO = {
    "nome": "Paulo Ribeiro",
    "email": "paulo@imobiliaria.com.br",
    "telefone": "5511988887777",
    "creci": "SP-123456",
    "especialidades": ["COMPRA", "INVESTIMENTO"],
    "regioesAtuacao": ["Zona Sul"],
    "horarioInicio": 9,
    "horarioFim": 18,
    "capacidadeDiaria": 4,
    "plantao": False,
}


@pytest.fixture
async def app_com_token(monkeypatch: Any, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `app_com_token` em `test_busca_endpoint.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_sem_token_e_403(app_com_token) -> None:
    resposta = await app_com_token.post("/api/v1/corretores", json=CORPO)
    assert resposta.status_code == 403


async def test_cadastrar_devolve_201_com_o_id(app_com_token) -> None:
    """Primeiro cenario do Gherkin."""
    resposta = await app_com_token.post(
        "/api/v1/corretores", json=CORPO, headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert uuid.UUID(corpo["id"])
    assert corpo["especialidades"] == ["COMPRA", "INVESTIMENTO"]
    # D4: a regiao e gravada dobrada.
    assert corpo["regioesAtuacao"] == ["zona sul"]
    assert corpo["ativo"] is True


async def test_email_duplicado_e_409(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    resposta = await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    assert resposta.status_code == 409


async def test_especialidade_invalida_e_422(app_com_token) -> None:
    """O vocabulario e recusado na borda, antes de chegar ao CHECK do banco."""
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"especialidades": ["ASTROLOGIA"]},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_jornada_invertida_e_422(app_com_token) -> None:
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"horarioInicio": 18, "horarioFim": 9},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_listar_filtra_por_ativo(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )
    await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    todos = (await app_com_token.get("/api/v1/corretores", headers=cabecalho)).json()
    ativos = (await app_com_token.get("/api/v1/corretores?ativos=true", headers=cabecalho)).json()

    assert len(todos) == 2
    assert len(ativos) == 1


async def test_desativar_preserva_o_corretor(app_com_token) -> None:
    """Terceiro cenario do Gherkin: desativar nao apaga."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    lido = await app_com_token.get(f"/api/v1/corretores/{criado['id']}", headers=cabecalho)
    assert lido.status_code == 200
    assert lido.json()["ativo"] is False
    assert lido.json()["nome"] == "Paulo Ribeiro"


async def test_corretor_inexistente_e_404(app_com_token) -> None:
    resposta = await app_com_token.get(
        f"/api/v1/corretores/{uuid.uuid4()}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


async def test_nao_existe_rota_de_delete(app_com_token) -> None:
    """D6: apagar quebraria a FK, e a RESTRICT recusaria de qualquer jeito."""
    criado = (
        await app_com_token.post("/api/v1/corretores", json=CORPO, headers={"X-Admin-Token": TOKEN})
    ).json()

    resposta = await app_com_token.delete(
        f"/api/v1/corretores/{criado['id']}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 405


async def test_editar_email_reflete_na_leitura(app_com_token) -> None:
    """Decisao vinculante 2: o PATCH tambem edita o e-mail."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"email": "paulo.novo@imobiliaria.com.br"},
        headers=cabecalho,
    )

    assert resposta.status_code == 200
    assert resposta.json()["email"] == "paulo.novo@imobiliaria.com.br"


async def test_editar_email_para_um_ja_cadastrado_e_409(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )

    assert resposta.status_code == 409


async def test_editar_so_horario_inicio_e_422(app_com_token) -> None:
    """Decisao vinculante 3: a jornada se edita em par, nunca sozinha."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioInicio": 10}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_so_horario_fim_e_422(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioFim": 20}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_jornada_invertida_em_par_e_422(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": 18, "horarioFim": 9},
        headers=cabecalho,
    )

    assert resposta.status_code == 422


async def test_editar_jornada_em_par_ambos_nulos_e_422(app_com_token) -> None:
    """Os dois vem informados, mas nulos -- 422 por checagem explicita, nao por `assert`.

    `assert` some sob `python -O`, entao a guarda do model_validator tem de
    levantar `ValueError` sozinha em vez de depender da captura do Pydantic.
    """
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": None, "horarioFim": None},
        headers=cabecalho,
    )

    assert resposta.status_code == 422


async def test_editar_jornada_em_par_funciona(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": 8, "horarioFim": 12},
        headers=cabecalho,
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["horarioInicio"] == 8
    assert corpo["horarioFim"] == 12


async def test_editar_creci_para_nulo_limpa_o_campo(app_com_token) -> None:
    """`exclude_unset`, nao `exclude_none`: so assim da para limpar o creci."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    assert criado["creci"] == "SP-123456"

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"creci": None}, headers=cabecalho
    )

    assert resposta.status_code == 200
    assert resposta.json()["creci"] is None


async def test_editar_nome_para_nulo_e_422(app_com_token) -> None:
    """`creci` e a unica coluna nulavel -- nos outros campos, nulo e recusado.

    Sem isto, `PATCH {"nome": null}` respondia 200 e gravava a string
    literal "None" (`str(None)` no repositorio, sem checagem).
    """
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"nome": None}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_email_para_nulo_e_422(app_com_token) -> None:
    """Sem isto, `PATCH {"email": null}` gravava "none" na coluna que e a
    unica defesa contra corretor duplicado (D1 do desenho)."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"email": None}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_especialidades_para_nulo_e_422(app_com_token) -> None:
    """Antes desta correcao, `[str(e) for e in None]` estourava TypeError e a
    rota devolvia 500 em vez de 422."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"especialidades": None}, headers=cabecalho
    )

    assert resposta.status_code == 422


def test_campos_editaveis_cobre_todo_o_corretor_editado() -> None:
    """`CorretorEditado` e `CAMPOS_EDITAVEIS` tem de concordar manualmente.

    Sem esta amarra, acrescentar um campo ao modelo Pydantic sem tocar o
    frozenset do repositorio produz `ValueError` (campo nao editavel) e a
    rota devolve 500 em vez do 422/200 esperado -- mesmo genero de verdade
    duplicada que `test_check_de_especialidades_cobre_todo_o_enum` amarra
    para o vocabulario de especialidades.
    """
    assert set(CorretorEditado.model_fields) <= CAMPOS_EDITAVEIS


async def test_campo_desconhecido_no_patch_e_422(app_com_token) -> None:
    """Erro de digitacao (`horarioIncio`) nao pode ser engolido em silencio.

    Antes de `extra="forbid"`, `model_dump(exclude_unset=True)` devolvia
    `{}` para este corpo e a rota respondia 200 sem ter mudado nada -- o
    mesmo defeito que o comentario de `CAMPOS_EDITAVEIS` diz que a lista
    existe para evitar, reintroduzido uma camada acima pela rota HTTP.
    """
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioIncio": 10}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_campo_desconhecido_no_cadastro_e_422(app_com_token) -> None:
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"horarioIncio": 10},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_regiao_acima_de_120_caracteres_e_422(app_com_token) -> None:
    """O unico campo string cujo limite nao batia com a coluna (`String(120)`)."""
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["z" * 121]},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_regiao_so_espaco_e_422(app_com_token) -> None:
    """Passa o `min_length` da LISTA e o CHECK de cardinalidade; so a borda pega."""
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["   "]},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_nome_so_espaco_e_422(app_com_token) -> None:
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"nome": "   "},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_telefone_so_espaco_e_422(app_com_token) -> None:
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"telefone": "        "},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_regioes_duplicadas_apos_dobra_sao_unificadas(app_com_token) -> None:
    """A dobra existe para casar "Zona Sul" e "zona sul" como uma regiao so."""
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["Zona Sul", "zona sul"]},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 201
    assert resposta.json()["regioesAtuacao"] == ["zona sul"]
