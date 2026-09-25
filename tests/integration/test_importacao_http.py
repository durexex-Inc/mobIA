"""O endpoint administrativo de importacao, e a guarda que o protege.

TEC-156, RN-08.1 e a emenda E-01 da secao 6.3. Ate a TEC-201 a autenticacao e
um token compartilhado; sem token configurado a rota nem e registrada. Ver D1.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app

TOKEN = "token-de-teste-do-catalogo"

CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)
LINHA = (
    "AP-9001,Apartamento,Vista para o mar,APARTAMENTO,VENDA,580000.00,,850.00,"
    "320.00,Centro,Florianopolis,SC,CENTRO,-27.595377,-48.548050,74,2,1,2,1,"
    "varanda,,DISPONIVEL"
)
ARQUIVO = (CABECALHO + "\n" + LINHA + "\n").encode("utf-8")


@pytest.fixture
async def app_com_token(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_post_sem_token_e_403(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar", files={"arquivo": ("base.csv", ARQUIVO, "text/csv")}
    )
    assert resposta.status_code == 403


async def test_post_com_token_errado_e_403(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": "errado"},
    )
    assert resposta.status_code == 403


async def test_post_com_token_nao_ascii_e_403_e_nao_500(app_com_token):
    """Guarda de regressao: `compare_digest` recusa `str` fora do ASCII.

    Sem codificar para bytes antes de comparar, um token com acento ou emoji
    faria `exigir_admin` levantar `TypeError` em vez de recusar com 403 --
    o header e invalido, nao ausente, e a resposta certa continua sendo
    "token errado", nao um 500 de erro interno.

    O valor do header vai como `bytes` (nao `str`) porque o proprio httpx so
    aceita `str` de header quando ela e ASCII -- `encode()` aqui e um jeito de
    colocar um byte fora do ASCII na requisicao, e nao faz parte do que o
    servidor recebe (que chega decodificado como `str`, latin-1, pelo ASGI).
    """
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": "acento-nao-é-o-token-ó".encode()},
    )
    assert resposta.status_code == 403


async def test_post_com_token_devolve_202_e_id(app_com_token):
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["status"] == "PROCESSANDO"
    uuid.UUID(corpo["importacaoId"])


async def test_get_devolve_o_relatorio_com_os_cinco_totais(app_com_token):
    criada = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    importacao_id = criada.json()["importacaoId"]

    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}",
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    # Consultar antes de o job rodar devolve 200 com PROCESSANDO -- nao 404,
    # nao 202: a linha existe desde o POST.
    assert corpo["status"] == "PROCESSANDO"
    for chave in ("processados", "inseridos", "atualizados", "inalterados", "rejeitados"):
        assert chave in corpo


async def test_get_de_id_inexistente_e_404(app_com_token):
    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{uuid.uuid4()}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


async def test_sem_token_configurado_a_rota_existe_e_recusa(
    monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool
):
    """403 e nao 404 -- **este teste afirmava o contrario ate a TEC-201.**

    A D1 da TEC-156 registrava a rota so quando havia token, com o argumento de
    que "rota que nao existe nao pode ser exposta por engano de configuracao, e
    este projeto ainda nao tem camada de autenticacao". A segunda metade caiu:
    `exigir_admin` agora exige JWT de ADMIN ou o token compartilhado.

    Manter o 404 teria efeito perverso depois da TEC-201: quem configurasse so
    o JWT nao teria rota nenhuma, e precisaria manter justamente o token que a
    card veio substituir. O que protege agora e a guarda, nao a ausencia.

    O que este teste continua garantindo e o essencial: **sem credencial, nao
    passa**.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "")
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/api/v1/imoveis/importar",
            files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
            headers={"X-Admin-Token": TOKEN},
        )
    assert resposta.status_code == 403
    get_settings.cache_clear()


async def test_arquivo_acima_do_teto_e_413(app_com_token):
    grande = b"x" * (10 * 1024 * 1024 + 1)
    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", grande, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 413


async def test_o_job_conclui_a_importacao_enfileirada(app_com_token):
    from mobia.workers.jobs.importar_catalogo import importar_catalogo

    criada = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    importacao_id = criada.json()["importacaoId"]

    await importar_catalogo({}, importacao_id)

    resposta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers={"X-Admin-Token": TOKEN}
    )
    corpo = resposta.json()
    assert corpo["status"] == "CONCLUIDO"
    assert corpo["processados"] == 1
    assert corpo["inseridos"] == 1
    assert corpo["rejeitados"] == 0


@pytest.fixture
async def app_sem_pool(monkeypatch, caches_de_cliente_limpos, banco_limpo):
    """O mesmo app, mas com `redis_pool` em None -- o jeito mais direto de
    fazer o enqueue nao acontecer sem derrubar o Redis do ambiente."""
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = None
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_sem_enqueue_o_post_nao_finge_202(app_sem_pool):
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
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 503
    detalhe = resposta.json()["detail"]
    # O id vai no corpo do erro: sem ele o cliente nao teria como consultar o
    # motivo nem como saber que existe uma importacao registrada.
    assert detalhe["status"] == "FALHOU"
    uuid.UUID(detalhe["importacaoId"])


async def test_sem_enqueue_a_linha_fica_em_falhou_com_motivo(app_sem_pool):
    resposta = await app_sem_pool.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    importacao_id = resposta.json()["detail"]["importacaoId"]

    consulta = await app_sem_pool.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers={"X-Admin-Token": TOKEN}
    )
    assert consulta.status_code == 200
    corpo = consulta.json()
    assert corpo["status"] == "FALHOU"
    assert corpo["erros"] and corpo["erros"][0]["linha"] == 0
    assert "enfileirad" in corpo["erros"][0]["motivo"]


async def test_enqueue_que_levanta_tambem_marca_falhou(app_com_token, monkeypatch, redis_pool):
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

    resposta = await app_com_token.post(
        "/api/v1/imoveis/importar",
        files={"arquivo": ("base.csv", ARQUIVO, "text/csv")},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 503
    importacao_id = resposta.json()["detail"]["importacaoId"]

    consulta = await app_com_token.get(
        f"/api/v1/imoveis/importacoes/{importacao_id}", headers={"X-Admin-Token": TOKEN}
    )
    corpo = consulta.json()
    assert corpo["status"] == "FALHOU"
    motivo = corpo["erros"][0]["motivo"]
    assert "ConnectionError" in motivo
    assert "redis fora do ar" not in motivo
