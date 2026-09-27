"""O endpoint administrativo de importacao, e a guarda que o protege.

TEC-156, RN-08.1 e a emenda E-01 da secao 6.3. `GERIR_CATALOGO` e so do ADMIN
(TEC-202); ate a TEC-201 a autenticacao era um token compartilhado, e sem ele
configurado a rota nem era registrada -- a TEC-382 apagou o token de vez. Ver
D1.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.main import create_app
from tests.conftest import cabecalho_de

CSV_CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)
LINHA = (
    "AP-9001,Apartamento,Vista para o mar,APARTAMENTO,VENDA,580000.00,,850.00,"
    "320.00,Centro,Florianopolis,SC,CENTRO,-27.595377,-48.548050,74,2,1,2,1,"
    "varanda,,DISPONIVEL"
)
ARQUIVO = (CSV_CABECALHO + "\n" + LINHA + "\n").encode("utf-8")


async def test_post_sem_token_e_403(client: AsyncClient) -> None:
    resposta = await client.post(
        "/api/v1/imoveis/importar", files={"arquivo": ("base.csv", ARQUIVO, "text/csv")}
    )
    assert resposta.status_code == 403


async def test_post_com_bearer_invalido_e_403_e_nao_500(client: AsyncClient) -> None:
    """Guarda de regressao: um JWT malformado recusa, e nao estoura 500.

    Ate a TEC-382 este caso exercitava `compare_digest` contra o
    `X-Admin-Token`; hoje quem decide e `_do_jwt`, que devolve `None` para
    qualquer coisa que `jwt.decode` nao reconheça (`TokenInvalido`) -- o
    mesmo desfecho de "sem credencial", nunca um erro do servidor.
    """
    resposta = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"Authorization": "Bearer nao-e-um-jwt"},
    )
    assert resposta.status_code == 403


async def test_post_com_token_devolve_202_e_id(client: AsyncClient) -> None:
    resposta = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["status"] == "PROCESSANDO"
    uuid.UUID(corpo["importacaoId"])


async def test_get_devolve_o_relatorio_com_os_cinco_totais(client: AsyncClient) -> None:
    criada = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    importacao_id = criada.json()["importacaoId"]

    resposta = await client.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}",
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    # Consultar antes de o job rodar devolve 200 com PROCESSANDO -- nao 404,
    # nao 202: a linha existe desde o POST.
    assert corpo["status"] == "PROCESSANDO"
    for chave in ("processados", "inseridos", "atualizados", "inalterados", "rejeitados"):
        assert chave in corpo


async def test_get_de_id_inexistente_e_404(client: AsyncClient) -> None:
    resposta = await client.get(
        f"/api/v1/imoveis/importacoes/{uuid.uuid4()}", headers=cabecalho_de("ADMIN")
    )
    assert resposta.status_code == 404


async def test_arquivo_acima_do_teto_e_413(client: AsyncClient) -> None:
    grande = b"x" * (10 * 1024 * 1024 + 1)
    resposta = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", grande, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 413


async def test_o_job_conclui_a_importacao_enfileirada(client: AsyncClient) -> None:
    from mobia.workers.jobs.importar_catalogo import importar_catalogo

    criada = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    importacao_id = criada.json()["importacaoId"]

    await importar_catalogo({}, importacao_id)

    resposta = await client.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers=cabecalho_de("ADMIN")
    )
    corpo = resposta.json()
    assert corpo["status"] == "CONCLUIDO"
    assert corpo["processados"] == 1
    assert corpo["inseridos"] == 1
    assert corpo["rejeitados"] == 0


@pytest.fixture
async def app_sem_pool(caches_de_cliente_limpos, banco_limpo):
    """O mesmo app, mas com `redis_pool` em None -- o jeito mais direto de
    fazer o enqueue nao acontecer sem derrubar o Redis do ambiente."""
    app = create_app()
    app.state.redis_pool = None
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


async def test_sem_enqueue_o_post_nao_finge_202(app_sem_pool: AsyncClient) -> None:
    """Sem pool, o POST devolvia 202 PROCESSANDO e logava "enfileirada".

    Nada tinha sido enfileirado. A linha ficava em PROCESSANDO para sempre --
    nao havia job para roda-la, e a varredura de importacoes travadas so nasceu
    na TEC-261 --, guardando ate 10 MB e indistinguivel de "ainda trabalhando".
    Hoje a varredura encerraria a linha, mas so meia hora depois e sem
    desmentir o 202 que ja teria sido devolvido. E o log afirmava um evento que
    nao aconteceu, que nesta base e o mesmo defeito de um comentario que
    mente.
    """
    resposta = await app_sem_pool.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 503
    detalhe = resposta.json()["detail"]
    # O id vai no corpo do erro: sem ele o cliente nao teria como consultar o
    # motivo nem como saber que existe uma importacao registrada.
    assert detalhe["status"] == "FALHOU"
    uuid.UUID(detalhe["importacaoId"])


async def test_sem_enqueue_a_linha_fica_em_falhou_com_motivo(app_sem_pool: AsyncClient) -> None:
    resposta = await app_sem_pool.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    importacao_id = resposta.json()["detail"]["importacaoId"]

    consulta = await app_sem_pool.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers=cabecalho_de("ADMIN")
    )
    assert consulta.status_code == 200
    corpo = consulta.json()
    assert corpo["status"] == "FALHOU"
    assert corpo["erros"] and corpo["erros"][0]["linha"] == 0
    assert "enfileirad" in corpo["erros"][0]["motivo"]


async def test_enqueue_que_levanta_tambem_marca_falhou(
    client: AsyncClient, monkeypatch, redis_pool
) -> None:
    """Redis no ar mas `enqueue_job` levantando: mesma consequencia, mesmo desfecho.

    Ate a TEC-292 esta assercao conferia que o texto da excecao ("redis fora
    do ar") chegava ao `motivo`. Isso e exatamente o vetor que a TEC-292
    fecha: `importacao.erros` e coluna duravel que o GET devolve por HTTP, e
    texto de terceiro (aqui, um `ConnectionError` que um teste escreveu, mas
    em producao seria o driver do Redis) nao pode sair por esse caminho. O
    teste agora prova o oposto do que provava antes: o tipo da excecao chega,
    o texto dela nao.
    """

    async def explode(*args, **kwargs):
        raise ConnectionError("redis fora do ar")

    monkeypatch.setattr(type(redis_pool), "enqueue_job", explode)

    resposta = await client.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 503
    importacao_id = resposta.json()["detail"]["importacaoId"]

    consulta = await client.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers=cabecalho_de("ADMIN")
    )
    corpo = consulta.json()
    assert corpo["status"] == "FALHOU"
    motivo = corpo["erros"][0]["motivo"]
    assert "ConnectionError" in motivo
    assert "redis fora do ar" not in motivo
