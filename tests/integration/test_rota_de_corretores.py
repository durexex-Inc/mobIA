"""O CRUD de corretores, guardado por `GERIR_CORRETORES` -- so o ADMIN tem."""

import uuid

from mobia.api.routes.corretores import CorretorEditado
from mobia.domain.corretores.repositorio import CAMPOS_EDITAVEIS
from tests.conftest import cabecalho_de

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


async def test_sem_token_e_403(client) -> None:
    resposta = await client.post("/api/v1/corretores", json=CORPO)
    assert resposta.status_code == 403


async def test_cadastrar_devolve_201_com_o_id(client) -> None:
    """Primeiro cenario do Gherkin."""
    resposta = await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho_de("ADMIN"))

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert uuid.UUID(corpo["id"])
    assert corpo["especialidades"] == ["COMPRA", "INVESTIMENTO"]
    # D4: a regiao e gravada dobrada.
    assert corpo["regioesAtuacao"] == ["zona sul"]
    assert corpo["ativo"] is True


async def test_email_duplicado_e_409(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    resposta = await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    assert resposta.status_code == 409


async def test_especialidade_invalida_e_422(client) -> None:
    """O vocabulario e recusado na borda, antes de chegar ao CHECK do banco."""
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"especialidades": ["ASTROLOGIA"]},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_jornada_invertida_e_422(client) -> None:
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"horarioInicio": 18, "horarioFim": 9},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_listar_filtra_por_ativo(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    await client.post(
        "/api/v1/corretores",
        json=CORPO | {"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )
    await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    todos = (await client.get("/api/v1/corretores", headers=cabecalho)).json()
    ativos = (await client.get("/api/v1/corretores?ativos=true", headers=cabecalho)).json()

    assert len(todos) == 2
    assert len(ativos) == 1


async def test_desativar_preserva_o_corretor(client) -> None:
    """Terceiro cenario do Gherkin: desativar nao apaga."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    lido = await client.get(f"/api/v1/corretores/{criado['id']}", headers=cabecalho)
    assert lido.status_code == 200
    assert lido.json()["ativo"] is False
    assert lido.json()["nome"] == "Paulo Ribeiro"


async def test_corretor_inexistente_e_404(client) -> None:
    resposta = await client.get(f"/api/v1/corretores/{uuid.uuid4()}", headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 404


async def test_nao_existe_rota_de_delete(client) -> None:
    """D6: apagar quebraria a FK, e a RESTRICT recusaria de qualquer jeito."""
    criado = (
        await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho_de("ADMIN"))
    ).json()

    resposta = await client.delete(
        f"/api/v1/corretores/{criado['id']}", headers=cabecalho_de("ADMIN")
    )
    assert resposta.status_code == 405


async def test_editar_email_reflete_na_leitura(client) -> None:
    """Decisao vinculante 2: o PATCH tambem edita o e-mail."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"email": "paulo.novo@imobiliaria.com.br"},
        headers=cabecalho,
    )

    assert resposta.status_code == 200
    assert resposta.json()["email"] == "paulo.novo@imobiliaria.com.br"


async def test_editar_email_para_um_ja_cadastrado_e_409(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    await client.post(
        "/api/v1/corretores",
        json=CORPO | {"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )

    assert resposta.status_code == 409


async def test_editar_so_horario_inicio_e_422(client) -> None:
    """Decisao vinculante 3: a jornada se edita em par, nunca sozinha."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioInicio": 10}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_so_horario_fim_e_422(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioFim": 20}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_jornada_invertida_em_par_e_422(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": 18, "horarioFim": 9},
        headers=cabecalho,
    )

    assert resposta.status_code == 422


async def test_editar_jornada_em_par_ambos_nulos_e_422(client) -> None:
    """Os dois vem informados, mas nulos -- 422 por checagem explicita, nao por `assert`.

    `assert` some sob `python -O`, entao a guarda do model_validator tem de
    levantar `ValueError` sozinha em vez de depender da captura do Pydantic.
    """
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": None, "horarioFim": None},
        headers=cabecalho,
    )

    assert resposta.status_code == 422


async def test_editar_jornada_em_par_funciona(client) -> None:
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}",
        json={"horarioInicio": 8, "horarioFim": 12},
        headers=cabecalho,
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["horarioInicio"] == 8
    assert corpo["horarioFim"] == 12


async def test_editar_creci_para_nulo_limpa_o_campo(client) -> None:
    """`exclude_unset`, nao `exclude_none`: so assim da para limpar o creci."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    assert criado["creci"] == "SP-123456"

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"creci": None}, headers=cabecalho
    )

    assert resposta.status_code == 200
    assert resposta.json()["creci"] is None


async def test_editar_nome_para_nulo_e_422(client) -> None:
    """`creci` e a unica coluna nulavel -- nos outros campos, nulo e recusado.

    Sem isto, `PATCH {"nome": null}` respondia 200 e gravava a string
    literal "None" (`str(None)` no repositorio, sem checagem).
    """
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"nome": None}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_email_para_nulo_e_422(client) -> None:
    """Sem isto, `PATCH {"email": null}` gravava "none" na coluna que e a
    unica defesa contra corretor duplicado (D1 do desenho)."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"email": None}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_editar_especialidades_para_nulo_e_422(client) -> None:
    """Antes desta correcao, `[str(e) for e in None]` estourava TypeError e a
    rota devolvia 500 em vez de 422."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
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


async def test_campo_desconhecido_no_patch_e_422(client) -> None:
    """Erro de digitacao (`horarioIncio`) nao pode ser engolido em silencio.

    Antes de `extra="forbid"`, `model_dump(exclude_unset=True)` devolvia
    `{}` para este corpo e a rota respondia 200 sem ter mudado nada -- o
    mesmo defeito que o comentario de `CAMPOS_EDITAVEIS` diz que a lista
    existe para evitar, reintroduzido uma camada acima pela rota HTTP.
    """
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()

    resposta = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"horarioIncio": 10}, headers=cabecalho
    )

    assert resposta.status_code == 422


async def test_campo_desconhecido_no_cadastro_e_422(client) -> None:
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"horarioIncio": 10},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_regiao_acima_de_120_caracteres_e_422(client) -> None:
    """O unico campo string cujo limite nao batia com a coluna (`String(120)`)."""
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["z" * 121]},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_regiao_so_espaco_e_422(client) -> None:
    """Passa o `min_length` da LISTA e o CHECK de cardinalidade; so a borda pega."""
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["   "]},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_nome_so_espaco_e_422(client) -> None:
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"nome": "   "},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_telefone_so_espaco_e_422(client) -> None:
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"telefone": "        "},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_cadastrar_com_gerente_true_cria_um_gerente(client) -> None:
    """I3/Ruling R4 da revisao final: `gerente` vira cadastravel pela rota,
    espelhando `plantao` (D7 do desenho)."""
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"gerente": True},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 201
    assert resposta.json()["gerente"] is True


async def test_cadastrar_sem_gerente_nasce_falso(client) -> None:
    resposta = await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho_de("ADMIN"))

    assert resposta.status_code == 201
    assert resposta.json()["gerente"] is False


async def test_editar_liga_e_desliga_gerente(client) -> None:
    """D7: `gerente` e `plantao` nao sao exclusivos -- o PATCH liga e desliga
    a flag como qualquer outro booleano do cadastro."""
    cabecalho = cabecalho_de("ADMIN")
    criado = (await client.post("/api/v1/corretores", json=CORPO, headers=cabecalho)).json()
    assert criado["gerente"] is False

    ligado = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"gerente": True}, headers=cabecalho
    )
    assert ligado.status_code == 200
    assert ligado.json()["gerente"] is True

    desligado = await client.patch(
        f"/api/v1/corretores/{criado['id']}", json={"gerente": False}, headers=cabecalho
    )
    assert desligado.status_code == 200
    assert desligado.json()["gerente"] is False


async def test_regioes_duplicadas_apos_dobra_sao_unificadas(client) -> None:
    """A dobra existe para casar "Zona Sul" e "zona sul" como uma regiao so."""
    resposta = await client.post(
        "/api/v1/corretores",
        json=CORPO | {"regioesAtuacao": ["Zona Sul", "zona sul"]},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 201
    assert resposta.json()["regioesAtuacao"] == ["zona sul"]
