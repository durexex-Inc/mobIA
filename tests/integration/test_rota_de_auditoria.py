"""A leitura da trilha: `GET /api/v1/auditoria`. TEC-206, D8 do desenho.

Os eventos sao semeados por `registrar_evento`, e os instantes que os testes
de `de`/`ate` usam sao LIDOS do banco: medido em 25/09/2026, o relogio do
Postgres local estava um ano atras do host, e o trigger da 0052 carimba pelo
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
    "id",
    "criadoEm",
    "atorTipo",
    "atorId",
    "acao",
    "entidade",
    "entidadeId",
    "campo",
    "detalhes",
    "ip",
    "correlationId",
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
        session,
        ator=ator,
        acao=acao,
        entidade=Entidade.HANDOFF,
        entidade_id=str(uuid.uuid4()),
        lead=lead,
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


async def test_filtro_por_ator(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
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
