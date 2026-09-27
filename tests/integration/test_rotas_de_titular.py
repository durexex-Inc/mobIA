"""As rotas ADMIN do titular: fila, exportacao, eliminacao e recusa. TEC-207, D4.

So `ATENDER_TITULAR`, que so o ADMIN tem por construcao -- os outros tres
papeis levam 403 nas quatro rotas, e o teste de permissao usa um UUID
qualquer: a guarda (`Depends(Exige(...))`) roda antes de qualquer consulta ao
lead ou a solicitacao, entao nao ha necessidade de semear nada para provar o
403.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.consentimento.models import Consentimento
from mobia.domain.context.models import LeadQualification
from mobia.domain.identidade import indice
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.identidade.reindexacao import TABELAS_COM_CHAVE_DE_LEAD, reindexar
from mobia.domain.leads.models import ReferenciaDeLead
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import marcar_atendida, registrar_solicitacao
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.domain.usuarios import tokens
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_engine, get_sessionmaker
from mobia.workers.jobs.eliminar_lead import eliminar_lead

CANAL = "whatsapp"
INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _bearer(papel: str) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


def _fala(*, chave: str, em: datetime, retida: bool = False) -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        channel=CANAL,
        conversation_key=chave,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        sender_external_id=chave,
        text_body=encrypt("oi", aad_de(identificador, "text_body")) if not retida else None,
        bloqueada_em=em if retida else None,
        created_at=em,
    )


async def _lead(
    session: AsyncSession, *, telefone: str, mensagens: int = 1
) -> tuple[str, uuid.UUID]:
    """Registra a identidade, semeia `mensagens` falas e devolve `(chave, leadId)`."""
    chave = chave_de(CANAL, telefone)
    await registrar(session, CANAL, telefone)
    session.add_all(
        [_fala(chave=chave, em=INICIO + timedelta(minutes=i)) for i in range(mensagens)]
    )
    apelidos = await referencias_para(session, [(CANAL, chave)])
    await session.commit()
    return chave, apelidos[(CANAL, chave)]


# --- Permissao: so ATENDER_TITULAR passa -------------------------------------


@pytest.mark.parametrize("papel", ["GERENTE", "CORRETOR", "LEITURA"])
async def test_quem_nao_tem_atender_titular_recebe_403(
    client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    lead_qualquer = uuid.uuid4()
    solicitacao_qualquer = uuid.uuid4()

    assert (
        await client.get("/api/v1/titular/solicitacoes", headers=_bearer(papel))
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/leads/{lead_qualquer}/dados-pessoais", headers=_bearer(papel))
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/leads/{lead_qualquer}/dados-pessoais", headers=_bearer(papel))
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/titular/solicitacoes/{solicitacao_qualquer}/recusa",
            json={"motivo": "motivo qualquer"},
            headers=_bearer(papel),
        )
    ).status_code == 403


async def test_admin_acessa_a_fila_vazia(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.get("/api/v1/titular/solicitacoes", headers=_bearer("ADMIN"))
    assert resposta.status_code == 200
    assert resposta.json() == {"itens": []}


async def test_status_invalido_e_422(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.get(
        "/api/v1/titular/solicitacoes", params={"status": "LIXO"}, headers=_bearer("ADMIN")
    )
    assert resposta.status_code == 422


# --- GET .../dados-pessoais: a exportacao -------------------------------------


async def test_dados_pessoais_de_lead_inexistente_e_404(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.get(
        f"/api/v1/leads/{uuid.uuid4()}/dados-pessoais", headers=_bearer("ADMIN")
    )
    assert resposta.status_code == 404


async def test_exportacao_traz_telefone_qualificacao_consentimento_e_transcricao_paginada(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    telefone = "5548999990001"
    chave, lead_id = await _lead(session, telefone=telefone, mensagens=250)

    session.add(
        LeadQualification(channel=CANAL, conversation_key=chave, intencao="COMPRA", regiao="Centro")
    )
    session.add(
        Consentimento(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=chave,
            marketing=True,
            texto_exibido="Aceito receber novidades por WhatsApp",
            exibido_em=INICIO,
        )
    )
    acesso_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    resposta = await client.get(f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN"))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["canal"] == CANAL
    assert corpo["telefone"] == f"+{telefone}"
    assert corpo["qualificacao"]["intencao"] == "COMPRA"
    # As 250 falas semeadas, a paginacao (limite de 200) as juntou de volta.
    assert len(corpo["transcricao"]) == 250
    assert [fala["em"] for fala in corpo["transcricao"]] == sorted(
        fala["em"] for fala in corpo["transcricao"]
    )
    assert corpo["consentimentos"] == [
        {
            "marketing": True,
            "textoExibido": "Aceito receber novidades por WhatsApp",
            "registradoEm": corpo["consentimentos"][0]["registradoEm"],
        }
    ]

    evento = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == "DADOS_EXPORTADOS")
        )
    ).scalar_one()
    assert evento.entidade == "lead"
    assert evento.entidade_id == str(lead_id)

    linha_acesso = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == acesso_id)
        )
    ).scalar_one()
    assert linha_acesso.status == StatusDaSolicitacao.ATENDIDA.value


async def test_depois_da_rotacao_a_aberta_continua_achada_pelo_pedido_e_pela_exportacao(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revisao final da TEC-207, I2. A rotacao da chave de indice (TEC-203)
    move `conversation_key` em toda tabela da lista -- esta inclusive --, mas
    so recalcula `lead_ref` em `eventos_auditoria`. Com a unicidade e a busca
    por `lead_ref`, o pedido repetido depois da rotacao abria uma SEGUNDA
    solicitacao, e a exportacao nao achava a aberta para fechar. Pelo par,
    que a rotacao arrasta, as duas acham a mesma linha."""
    telefone = "5548999990010"
    chave_a, lead_id = await _lead(session, telefone=telefone)
    acesso_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave_a,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    configuracao_b = get_settings().model_copy(
        update={"lead_indice_chave": "chave-de-indice-B-" + "x" * 40}
    )
    monkeypatch.setattr(indice, "get_settings", lambda: configuracao_b)
    chave_b = chave_de(CANAL, telefone)
    assert chave_b != chave_a
    chave_do_lead = get_settings().auditoria_chave_do_lead
    async with get_engine().begin() as conexao:
        await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga=chave_do_lead,
                chave_do_lead_nova=chave_do_lead,
            )
        )

    de_novo = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave_b,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    assert de_novo == acesso_id

    resposta = await client.get(f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN"))

    assert resposta.status_code == 200
    session.expire_all()
    linhas = (await session.execute(select(SolicitacaoDeTitular))).scalars().all()
    assert [(linha.id, linha.status) for linha in linhas] == [
        (acesso_id, StatusDaSolicitacao.ATENDIDA.value)
    ]


async def test_exportacao_sem_acesso_aberta_nao_estoura(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    _, lead_id = await _lead(session, telefone="5548999990008")

    resposta = await client.get(f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN"))
    assert resposta.status_code == 200


# --- DELETE .../dados-pessoais: a eliminacao ----------------------------------


async def test_delete_de_lead_inexistente_e_404(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.delete(
        f"/api/v1/leads/{uuid.uuid4()}/dados-pessoais", headers=_bearer("ADMIN")
    )
    assert resposta.status_code == 404


async def test_delete_reaproveita_a_eliminacao_aberta_e_enfileira(
    session: AsyncSession, client: AsyncClient, redis_pool, banco_limpo: None
) -> None:
    telefone = "5548999990002"
    chave, lead_id = await _lead(session, telefone=telefone)

    whatsapp_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    resposta = await client.delete(
        f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN")
    )

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["solicitacaoId"] == str(whatsapp_id)
    assert corpo["status"] == "ABERTA"

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1
    assert jobs[0].function == "eliminar_lead"
    assert jobs[0].args == (str(whatsapp_id),)
    # `_job_id` fixo por solicitacao: um segundo DELETE da mesma solicitacao,
    # com o primeiro job ainda na fila, nao enfileira outro.
    assert jobs[0].job_id == f"titular:{whatsapp_id}"

    # Reaproveitada, e nao recriada: a origem continua WHATSAPP.
    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == whatsapp_id)
        )
    ).scalar_one()
    assert linha.origem == OrigemDaSolicitacao.WHATSAPP.value
    total = (
        await session.execute(
            select(SolicitacaoDeTitular).where(
                SolicitacaoDeTitular.tipo == TipoDeSolicitacao.ELIMINACAO.value
            )
        )
    ).scalars()
    assert len(list(total)) == 1

    # Roda o job a mao (D4 do teste): GET e DELETE de novo dao 404 -- a
    # anonimizacao apaga `referencias_de_lead`, e `par_de` deixa de resolver.
    await eliminar_lead(
        {"session_factory": get_sessionmaker(), "armazem": armazem_da_config(get_settings())},
        str(whatsapp_id),
    )

    resposta_get = await client.get(
        f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN")
    )
    assert resposta_get.status_code == 404

    resposta_delete = await client.delete(
        f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN")
    )
    assert resposta_delete.status_code == 404


async def test_delete_sem_pool_do_redis_e_503(session: AsyncSession, banco_limpo: None) -> None:
    _, lead_id = await _lead(session, telefone="5548999990009")

    app = create_app()
    app.state.redis_pool = None
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.delete(
            f"/api/v1/leads/{lead_id}/dados-pessoais", headers=_bearer("ADMIN")
        )
    assert resposta.status_code == 503


# --- POST .../recusa -----------------------------------------------------------


async def test_recusa_com_motivo_vazio_ou_acima_de_2000_e_422(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    chave, _ = await _lead(session, telefone="5548999990003")
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/titular/solicitacoes/{solicitacao_id}/recusa",
        json={"motivo": "   "},
        headers=_bearer("ADMIN"),
    )
    assert resposta.status_code == 422

    # O teto de 2000 caracteres: 2001 e 422, e a solicitacao continua ABERTA.
    resposta = await client.post(
        f"/api/v1/titular/solicitacoes/{solicitacao_id}/recusa",
        json={"motivo": "x" * 2001},
        headers=_bearer("ADMIN"),
    )
    assert resposta.status_code == 422
    session.expire_all()
    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ABERTA.value


async def test_recusa_ok_devolve_200_com_recusada_e_recusar_de_novo_e_409(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    chave, _ = await _lead(session, telefone="5548999990004")
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/titular/solicitacoes/{solicitacao_id}/recusa",
        json={"motivo": "retencao legal"},
        headers=_bearer("ADMIN"),
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "RECUSADA"
    assert corpo["motivoDaRecusa"] == "retencao legal"
    assert corpo["leadId"] is None

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.channel is None
    assert linha.conversation_key is None

    resposta_de_novo = await client.post(
        f"/api/v1/titular/solicitacoes/{solicitacao_id}/recusa",
        json={"motivo": "outra vez"},
        headers=_bearer("ADMIN"),
    )
    assert resposta_de_novo.status_code == 409


async def test_recusa_de_id_inexistente_e_404(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.post(
        f"/api/v1/titular/solicitacoes/{uuid.uuid4()}/recusa",
        json={"motivo": "motivo qualquer"},
        headers=_bearer("ADMIN"),
    )
    assert resposta.status_code == 404


# --- GET /titular/solicitacoes: a fila ordenada por prazo ---------------------


async def test_fila_ordena_por_prazo_com_leadid_nulo_nas_atendidas(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    chave_a, _ = await _lead(session, telefone="5548999990005")
    chave_b, lead_b = await _lead(session, telefone="5548999990006")

    id_a = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave_a,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    id_b = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave_b,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    # Empurra o prazo de `b` para antes do de `a`, e fecha `a` como atendida --
    # `marcar_atendida` nao mexe no prazo, so no status e no par.
    linha_b = (
        await session.execute(select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == id_b))
    ).scalar_one()
    linha_b.prazo_em = linha_b.prazo_em - timedelta(days=5)
    await session.commit()
    await marcar_atendida(session, id_a, agora=datetime.now(UTC))
    await session.commit()

    resposta = await client.get("/api/v1/titular/solicitacoes", headers=_bearer("ADMIN"))
    assert resposta.status_code == 200
    itens = resposta.json()["itens"]

    assert [item["id"] for item in itens] == [str(id_b), str(id_a)]

    item_a = next(item for item in itens if item["id"] == str(id_a))
    assert item_a["status"] == "ATENDIDA"
    assert item_a["leadId"] is None

    item_b = next(item for item in itens if item["id"] == str(id_b))
    assert item_b["status"] == "ABERTA"
    assert item_b["leadId"] == str(lead_b)


async def test_o_registro_cria_o_apelido_e_a_fila_nao_cria_nenhum(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Segunda revisao, sobre o M2. A fila so LE apelidos: criando
    (`referencias_para`, get-or-create), uma listagem que leu a solicitacao
    ABERTA logo antes de uma anonimizacao commitar recriava a linha de
    `referencias_de_lead` sob a chave antiga. Mas o apelido tem de existir,
    senao o ADMIN nao tem `leadId` para exportar ou apagar -- entao quem o
    cria e `registrar_solicitacao`, na mesma transacao do INSERT.

    Apagar o apelido a mao e o estado que a anonimizacao deixa (ela apaga o
    apelido e fecha a solicitacao juntos); aqui a solicitacao continua ABERTA
    de proposito, para provar que a fila, sozinha, nao o recria."""
    chave = chave_de(CANAL, "5548999990011")
    await registrar(session, CANAL, "5548999990011")
    await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    [apelido] = (await session.execute(select(ReferenciaDeLead))).scalars().all()
    assert (apelido.channel, apelido.conversation_key) == (CANAL, chave)

    await session.execute(ReferenciaDeLead.__table__.delete())
    await session.commit()

    resposta = await client.get("/api/v1/titular/solicitacoes", headers=_bearer("ADMIN"))

    assert resposta.status_code == 200
    [item] = resposta.json()["itens"]
    assert item["leadId"] is None
    session.expire_all()
    assert (await session.execute(select(ReferenciaDeLead))).scalars().all() == []


async def test_pedido_pelo_whatsapp_sai_na_fila_com_leadid_que_a_exportacao_aceita(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O lead que so falou pelo WhatsApp e nunca apareceu no painel de leads:
    o registro do pedido lhe da apelido, a fila o mostra, e o ADMIN exporta
    por ele -- o que fecha o ACESSO dentro do prazo."""
    telefone = "5548999990012"
    chave = chave_de(CANAL, telefone)
    await registrar(session, CANAL, telefone)
    session.add(_fala(chave=chave, em=INICIO))
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    fila = await client.get("/api/v1/titular/solicitacoes", headers=_bearer("ADMIN"))
    [item] = fila.json()["itens"]
    assert item["id"] == str(solicitacao_id)
    assert item["leadId"] is not None

    exportacao = await client.get(
        f"/api/v1/leads/{item['leadId']}/dados-pessoais", headers=_bearer("ADMIN")
    )

    assert exportacao.status_code == 200
    assert exportacao.json()["telefone"] == f"+{telefone}"
    session.expire_all()
    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ATENDIDA.value
