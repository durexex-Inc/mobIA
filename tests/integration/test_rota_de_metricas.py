"""O endpoint do painel de funil. TEC-190, RF-17."""

from tests.conftest import cabecalho_de

ROTA = "/api/v1/metricas/funil"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-31"}

# LEITURA, e nao ADMIN: `VER_FUNIL` e do ADMIN, da GERENTE e da LEITURA (o
# CORRETOR fica de fora, RN-FE-03.1) -- LEITURA e o menos privilegiado dos tres.


async def test_sem_token_e_403(client) -> None:
    resposta = await client.get(ROTA, params=PERIODO)

    assert resposta.status_code == 403


async def test_periodo_sem_lead_devolve_200_com_as_seis_etapas(client) -> None:
    """Item 5 do Review Focus: vazio e 200, nunca 404."""
    resposta = await client.get(ROTA, params=PERIODO, headers=cabecalho_de("LEITURA"))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["nome"] for e in corpo["etapas"]] == [
        "Novo",
        "Em conversa",
        "Qualificado",
        "Recomendado",
        "Agendado",
        "Handoff aceito",
    ]
    assert corpo["indicadores"]["taxaQualificacao"] is None


async def test_a_etapa_agendado_sai_disponivel_como_as_outras_cinco(client) -> None:
    """Coorte vazia, entao zero -- e zero MEDIDO, nao ausencia de fonte.

    Ate a TEC-376 esta etapa saia `quantidade: None` e `disponivel: False`.
    """
    resposta = await client.get(ROTA, params=PERIODO, headers=cabecalho_de("LEITURA"))

    agendado = next(e for e in resposta.json()["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] == 0
    assert agendado["disponivel"] is True


async def test_os_quatro_indicadores_de_visita_saem_no_corpo_e_a_lista_fica_vazia(
    client,
) -> None:
    """A chave `indisponiveis` FICA, e vazia -- omiti-la e mudanca de contrato.

    `taxaNoShow` continua nula aqui por nao haver desfecho DECIDIDO no
    periodo, e nao por falta de fonte: 0/0 nao e 0%.
    """
    corpo = (await client.get(ROTA, params=PERIODO, headers=cabecalho_de("LEITURA"))).json()

    assert corpo["indisponiveis"] == []
    assert corpo["indicadores"]["agendamentosCriados"] == 0
    assert corpo["indicadores"]["agendamentosConfirmados"] == 0
    assert corpo["indicadores"]["agendamentosRealizados"] == 0
    assert corpo["indicadores"]["taxaNoShow"] is None


async def test_de_depois_de_ate_e_422_nomeando_o_campo(client) -> None:
    resposta = await client.get(
        ROTA,
        params={"de": "2026-08-31", "ate": "2026-08-01"},
        headers=cabecalho_de("LEITURA"),
    )

    assert resposta.status_code == 422
    assert "de" in resposta.json()["detail"]


async def test_temperatura_invalida_e_422_e_nao_funil_vazio(client) -> None:
    resposta = await client.get(
        ROTA,
        params={**PERIODO, "temperatura": "MORNA"},
        headers=cabecalho_de("LEITURA"),
    )

    assert resposta.status_code == 422
    assert "MORNA" in resposta.json()["detail"]


async def test_data_malformada_e_422(client) -> None:
    resposta = await client.get(
        ROTA, params={"de": "ontem", "ate": "2026-08-31"}, headers=cabecalho_de("LEITURA")
    )

    assert resposta.status_code == 422


async def test_periodo_e_obrigatorio(client) -> None:
    resposta = await client.get(ROTA, headers=cabecalho_de("LEITURA"))

    assert resposta.status_code == 422
