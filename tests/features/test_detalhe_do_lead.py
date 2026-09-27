"""Criterios de aceite da TEC-193 como testes executaveis. RF-18, RN-18.2.

Os quatro cenarios do Gherkin da card, e o que o desenho acrescentou: a
paginacao da transcricao para tras (D5), a fala retida por papel (TEC-324), o
recorte do CORRETOR e de LEITURA (D2), a trilha das duas leituras (D3) e a
trava de 60 s da regeneracao (D6).

**O setimo bloco -- a transcricao -- e lido pela rota ao lado**, e o primeiro
cenario o afirma assim: o detalhe traz seis blocos e o resumo, e
`/mensagens` traz a conversa (D1).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from conftest import _corretor
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoLead
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.corretores.models import Corretor
from mobia.domain.followup.models import FollowUp
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import gravar_resumo
from mobia.domain.handoff.vocabulario import Status as StatusDoHandoff
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.usuarios import tokens
from mobia.infra.crypto import aad_de, encrypt

ROTA = "/api/v1/leads"
CANAL = "whatsapp"
TELEFONE = "5548990000021"
# Desde a TEC-203 o par guarda o HMAC do telefone, e o numero mora cifrado em
# `identidades_de_lead` -- `_lead_completo` o registra, e e de la que o detalhe
# tira o telefone que mascara.
CHAVE = chave_de(CANAL, TELEFONE)
INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


def _fala(
    *,
    chave: str = CHAVE,
    autor: MessageRole = MessageRole.LEAD,
    texto: str | None = "oi",
    em: datetime = INICIO,
    retida: bool = False,
    tipo: MessageContentType = MessageContentType.TEXTO,
) -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        channel=CANAL,
        conversation_key=chave,
        role=autor,
        direction=(
            MessageDirection.INBOUND if autor == MessageRole.LEAD else MessageDirection.OUTBOUND
        ),
        content_type=tipo,
        sender_external_id=chave,
        text_body=encrypt(texto, aad_de(identificador, "text_body")) if texto else None,
        bloqueada_em=em if retida else None,
        created_at=em,
    )


async def _apelido(session: AsyncSession, chave: str = CHAVE) -> uuid.UUID:
    apelidos = await referencias_para(session, [(CANAL, chave)])
    await session.commit()
    return apelidos[(CANAL, chave)]


async def _handoff(
    session: AsyncSession,
    *,
    chave: str = CHAVE,
    dono: uuid.UUID | None = None,
    resumo: str | None = None,
    fallback: bool = False,
    criado_em: datetime = INICIO,
    status: StatusDoHandoff = StatusDoHandoff.PENDENTE,
) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Handoff(
            id=identificador,
            channel=CANAL,
            conversation_key=chave,
            gatilho="PEDIU_HUMANO",
            etiqueta="PEDIU_HUMANO",
            prioridade="NORMAL",
            status=status.value,
            corretor_id=dono,
            criado_em=criado_em,
            atualizado_em=criado_em,
        )
    )
    await session.flush()
    if resumo is not None:
        await gravar_resumo(
            session,
            handoff_id=identificador,
            texto=resumo,
            modelo=None if fallback else "modelo-de-teste",
            fallback=fallback,
        )
    await session.commit()
    return identificador


def _recalculo(*, novo: int, anterior: int | None, em: datetime, causa: str) -> LeadScoreAudit:
    # Tudo em `completude`: `ck_lead_score_audit_total` exige o total igual a
    # soma dos fatores, e esta e a composicao que fecha para qualquer numero.
    return LeadScoreAudit(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=CHAVE,
        total_anterior=anterior,
        total_novo=novo,
        completude=novo,
        urgencia=0,
        catalogo=0,
        engajamento=0,
        capacidade=0,
        causas=[causa],
        created_at=em,
    )


async def _lead_completo(session: AsyncSession, *, dono: uuid.UUID) -> uuid.UUID:
    """Um lead com os sete blocos preenchidos. E o `Dado` do primeiro cenario."""
    await registrar(session, CANAL, TELEFONE)
    session.add_all(
        [
            _fala(autor=MessageRole.LEAD, texto="quero um ape no Campeche", em=INICIO),
            _fala(autor=MessageRole.AGENTE, texto="tenho tres opcoes", em=INICIO + timedelta(1)),
            _fala(autor=MessageRole.CORRETOR, texto="sou o Paulo", em=INICIO + timedelta(2)),
        ]
    )
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CHAVE,
            intencao="COMPRA",
            regiao="Campeche",
            quartos=2,
            temperatura="QUENTE",
        )
    )
    session.add_all(
        [
            _recalculo(novo=30, anterior=None, em=INICIO, causa="PRIMEIRO_CALCULO"),
            _recalculo(novo=47, anterior=30, em=INICIO + timedelta(hours=1), causa="COMPLETUDE"),
            _recalculo(novo=82, anterior=47, em=INICIO + timedelta(hours=2), causa="URGENCIA"),
        ]
    )
    imovel = Imovel(
        id=uuid.uuid4(),
        codigo="AP-CAMPECHE-1",
        titulo="Apartamento no Campeche",
        descricao="Perto da praia.",
        tipo="APARTAMENTO",
        operacao="VENDA",
        preco_venda=65000000,
        bairro="Campeche",
        bairro_busca="campeche",
        cidade="Florianopolis",
        uf="SC",
        area_util_m2=70,
        quartos=2,
        suites=1,
        banheiros=2,
        vagas=1,
        caracteristicas=[],
        fotos=[],
        status="DISPONIVEL",
    )
    session.add(imovel)
    await session.flush()
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CHAVE,
            imovel_id=imovel.id,
            score_match=Decimal("0.870"),
            motivo_match="dois quartos no bairro pedido",
            reacao_lead=ReacaoLead.DESCARTE.value,
            motivo_descarte=CategoriaDescarte.DISTANCIA.value,
            apresentado_em=INICIO + timedelta(minutes=5),
        )
    )
    session.add(
        Agendamento(
            id=uuid.uuid4(),
            corretor_id=dono,
            channel=CANAL,
            conversation_key=CHAVE,
            imovel_id=imovel.id,
            tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
            inicio=INICIO + timedelta(days=2),
            fim=INICIO + timedelta(days=2, hours=1),
            status=StatusDoAgendamento.CONFIRMADO,
            reservado_ate=INICIO + timedelta(days=2),
            criado_em=INICIO,
            confirmado_em=INICIO,
            motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
        )
    )
    session.add(
        FollowUp(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CHAVE,
            tentativa_numero=1,
            temperatura="MORNO",
            ancora_em=INICIO,
            devido_em=INICIO + timedelta(hours=4),
            created_at=INICIO + timedelta(hours=4),
        )
    )
    await session.commit()
    await _handoff(session, dono=dono, resumo="Lead quer dois quartos no Campeche.")
    return await _apelido(session)


async def _acessos(session: AsyncSession) -> list[EventoAuditoria]:
    return list(
        (
            await session.execute(
                select(EventoAuditoria)
                .where(EventoAuditoria.acao == Acao.DADO_PESSOAL_ACESSADO.value)
                .order_by(EventoAuditoria.criado_em)
            )
        )
        .scalars()
        .all()
    )


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_a_tela_reune_os_sete_blocos(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1. Seis blocos e o resumo no detalhe; a transcricao ao lado."""
    paulo = await _corretor(session)
    lead_id = await _lead_completo(session, dono=paulo)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)

    detalhe = await client.get(f"{ROTA}/{lead_id}", headers=cabecalho)
    transcricao = await client.get(f"{ROTA}/{lead_id}/mensagens", headers=cabecalho)

    assert detalhe.status_code == 200, detalhe.text
    corpo = detalhe.json()
    assert corpo["contato"] == {"telefone": "+55 48 9****-**21", "email": None}
    assert corpo["qualificacao"]["regiao"] == "Campeche"
    assert corpo["qualificacao"]["temperatura"] == "QUENTE"
    assert corpo["score"] == 82
    assert len(corpo["historicoScore"]) == 3
    assert len(corpo["recomendacoes"]) == 1
    assert [a["status"] for a in corpo["agendamentos"]] == ["CONFIRMADO"]
    assert [f["tentativa"] for f in corpo["followups"]] == [1]
    assert corpo["resumo"]["texto"] == "Lead quer dois quartos no Campeche."
    assert corpo["resumo"]["fallback"] is False

    assert transcricao.status_code == 200, transcricao.text
    assert len(transcricao.json()["itens"]) == 3


async def test_a_transcricao_identifica_autor_e_horario(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 2, e com os quatro autores de `ck_messages_role`."""
    session.add_all(
        [
            _fala(autor=MessageRole.LEAD, texto="oi", em=INICIO),
            _fala(autor=MessageRole.AGENTE, texto="ola", em=INICIO + timedelta(seconds=1)),
            _fala(autor=MessageRole.CORRETOR, texto="aqui e o Paulo", em=INICIO + timedelta(2)),
            _fala(autor=MessageRole.SISTEMA, texto="conversa assumida", em=INICIO + timedelta(3)),
        ]
    )
    await session.commit()
    lead_id = await _apelido(session)

    resposta = await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("GERENTE"))

    itens = resposta.json()["itens"]
    assert [(i["autor"], i["conteudo"]) for i in itens] == [
        ("LEAD", "oi"),
        ("AGENTE", "ola"),
        ("CORRETOR", "aqui e o Paulo"),
        ("SISTEMA", "conversa assumida"),
    ]
    assert all(datetime.fromisoformat(i["em"]).tzinfo is not None for i in itens)


async def test_imovel_recomendado_mostra_motivo_e_reacao(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 3: apresentado e descartado pelo lead."""
    paulo = await _corretor(session)
    lead_id = await _lead_completo(session, dono=paulo)

    resposta = await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))

    (imovel,) = resposta.json()["recomendacoes"]
    assert imovel["motivoMatch"] == "dois quartos no bairro pedido"
    assert imovel["reacao"] == "DESCARTE"
    assert imovel["motivoDescarte"] == "DISTANCIA"
    assert imovel["bairro"] == "Campeche"


async def test_historico_de_score_em_ordem_cronologica(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 4, com os quatro recalculos da card. Gravados fora de ordem, de
    proposito: a ordem da resposta tem de vir do carimbo, nao da insercao."""
    session.add(_fala())
    session.add_all(
        [
            _recalculo(novo=70, anterior=55, em=INICIO + timedelta(hours=3), causa="URGENCIA"),
            _recalculo(novo=30, anterior=None, em=INICIO, causa="PRIMEIRO_CALCULO"),
            _recalculo(novo=55, anterior=47, em=INICIO + timedelta(hours=2), causa="CATALOGO"),
            _recalculo(novo=47, anterior=30, em=INICIO + timedelta(hours=1), causa="COMPLETUDE"),
        ]
    )
    await session.commit()
    lead_id = await _apelido(session)

    resposta = await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))

    historico = resposta.json()["historicoScore"]
    assert [(r["anterior"], r["novo"]) for r in historico] == [
        (None, 30),
        (30, 47),
        (47, 55),
        (55, 70),
    ]
    assert [r["causas"] for r in historico] == [
        ["PRIMEIRO_CALCULO"],
        ["COMPLETUDE"],
        ["CATALOGO"],
        ["URGENCIA"],
    ]
    assert historico[0]["fatores"]["completude"] == 30


# --- a transcricao (D5) --------------------------------------------------------


async def _paginas(client: AsyncClient, lead_id: uuid.UUID, papel: str) -> list[list[Any]]:
    paginas: list[list[Any]] = []
    cursor: str | None = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        resposta = await client.get(
            f"{ROTA}/{lead_id}/mensagens", params=params, headers=_bearer(papel)
        )
        assert resposta.status_code == 200, resposta.text
        paginas.append(resposta.json()["itens"])
        cursor = resposta.json()["cursorAnterior"]
        if cursor is None:
            return paginas


async def test_trezentas_falas_em_tres_paginas_para_tras(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A TEC-324: as 100 mais recentes primeiro, depois as anteriores.

    As tres assertas pegam tres defeitos diferentes: a primeira pagina ser a
    do COMECO da conversa, uma pagina fora de ordem cronologica, e uma fala
    repetida ou perdida na fronteira.
    """
    session.add_all(
        [_fala(texto=f"fala {n}", em=INICIO + timedelta(seconds=n)) for n in range(300)]
    )
    await session.commit()
    lead_id = await _apelido(session)

    paginas = await _paginas(client, lead_id, "GERENTE")

    assert [len(p) for p in paginas] == [100, 100, 100]
    assert paginas[0][-1]["conteudo"] == "fala 299"
    for pagina in paginas:
        instantes = [i["em"] for i in pagina]
        assert instantes == sorted(instantes)
    todas = [i["conteudo"] for pagina in reversed(paginas) for i in pagina]
    assert todas == [f"fala {n}" for n in range(300)]


async def test_lote_com_o_mesmo_instante_nao_perde_fala(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O desempate por `id` (D5). `_persist` grava o lote de um envelope com o
    mesmo `created_at`, e um cursor so pelo instante pularia o resto do lote
    na fronteira da pagina."""
    session.add_all([_fala(texto=f"lote {n}", em=INICIO) for n in range(5)])
    await session.commit()
    lead_id = await _apelido(session)

    vistas = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limite": 2}
        if cursor:
            params["cursor"] = cursor
        resposta = await client.get(
            f"{ROTA}/{lead_id}/mensagens", params=params, headers=_bearer("GERENTE")
        )
        vistas.extend(i["id"] for i in resposta.json()["itens"])
        cursor = resposta.json()["cursorAnterior"]
        if cursor is None:
            break

    assert len(vistas) == 5
    assert len(set(vistas)) == 5


async def test_cursor_de_outro_lead_e_recusado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    session.add_all([_fala(em=INICIO + timedelta(seconds=n)) for n in range(3)])
    session.add_all(
        [_fala(chave="5548990000099", em=INICIO + timedelta(seconds=n)) for n in range(3)]
    )
    await session.commit()
    meu = await _apelido(session)
    outro = await _apelido(session, "5548990000099")
    cursor_do_outro = (
        await client.get(
            f"{ROTA}/{outro}/mensagens", params={"limite": 1}, headers=_bearer("GERENTE")
        )
    ).json()["cursorAnterior"]

    resposta = await client.get(
        f"{ROTA}/{meu}/mensagens", params={"cursor": cursor_do_outro}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 422


async def test_fala_retida_so_aparece_para_admin_e_sem_conteudo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A tabela da TEC-324: ADMIN ve o aviso sem o conteudo; os outros nao veem
    a fala. E a pagina continua com o numero pedido de falas VISIVEIS."""
    session.add_all(
        [
            _fala(texto="antes", em=INICIO),
            _fala(texto="ofensa", em=INICIO + timedelta(seconds=1), retida=True),
            _fala(texto="depois", em=INICIO + timedelta(seconds=2)),
        ]
    )
    await session.commit()
    lead_id = await _apelido(session)

    do_admin = await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("ADMIN"))
    do_gerente = await client.get(
        f"{ROTA}/{lead_id}/mensagens", params={"limite": 2}, headers=_bearer("GERENTE")
    )

    assert [(i["conteudo"], i["retida"]) for i in do_admin.json()["itens"]] == [
        ("antes", False),
        (None, True),
        ("depois", False),
    ]
    assert "ofensa" not in do_admin.text
    assert [i["conteudo"] for i in do_gerente.json()["itens"]] == ["antes", "depois"]


async def test_midia_sai_com_o_tipo_e_sem_conteudo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """L3: nao ha download de midia por aqui. `tipo` diz o que era."""
    session.add(_fala(texto=None, tipo=MessageContentType.AUDIO))
    await session.commit()
    lead_id = await _apelido(session)

    resposta = await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("GERENTE"))

    ((fala),) = resposta.json()["itens"]
    assert (fala["tipo"], fala["conteudo"]) == ("AUDIO", None)


# --- o recorte (D2) ------------------------------------------------------------


async def test_corretor_de_outro_lead_leva_403_e_a_negativa_fica_na_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O cenario "Lead de outro corretor" da TEC-323, pelo lado da API."""
    paulo = await _corretor(session)
    marcia = await _corretor(session)
    session.add(_fala())
    await session.commit()
    await _handoff(session, dono=marcia)
    lead_id = await _apelido(session)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)

    detalhe = await client.get(f"{ROTA}/{lead_id}", headers=cabecalho)
    transcricao = await client.get(f"{ROTA}/{lead_id}/mensagens", headers=cabecalho)

    assert (detalhe.status_code, transcricao.status_code) == (403, 403)
    negativas = (
        (
            await session.execute(
                select(EventoAuditoria).where(EventoAuditoria.acao == Acao.ACESSO_NEGADO.value)
            )
        )
        .scalars()
        .all()
    )
    assert [n.detalhes["motivo"] for n in negativas] == ["corretor_nao_e_o_dono"] * 2
    assert await _acessos(session) == []


async def test_corretor_sem_handoff_nenhum_nao_abre(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Lead sem dono nao e de quem pedir -- o argumento de `exigir_dono`."""
    paulo = await _corretor(session)
    session.add(_fala())
    await session.commit()
    lead_id = await _apelido(session)

    resposta = await client.get(f"{ROTA}/{lead_id}", headers=_bearer("CORRETOR", corretor_id=paulo))

    assert resposta.status_code == 403


async def test_leitura_ve_a_lista_e_nao_o_detalhe(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    session.add(_fala())
    await session.commit()
    lead_id = await _apelido(session)

    assert (await client.get(ROTA, headers=_bearer("LEITURA"))).status_code == 200
    assert (await client.get(f"{ROTA}/{lead_id}", headers=_bearer("LEITURA"))).status_code == 403
    assert (
        await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("LEITURA"))
    ).status_code == 403


async def test_apelido_inexistente_e_404(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.get(f"{ROTA}/{uuid.uuid4()}", headers=_bearer("GERENTE"))

    assert resposta.status_code == 404


# --- a trilha (D3) -------------------------------------------------------------


async def test_as_duas_leituras_ficam_na_trilha_sem_o_par(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Uma linha para o detalhe e uma por PAGINA da transcricao. O par nunca
    entra: ele e o pseudonimo do lead (TEC-203), e a trilha guarda `lead_ref`."""
    session.add_all([_fala(em=INICIO + timedelta(seconds=n)) for n in range(3)])
    await session.commit()
    lead_id = await _apelido(session)

    await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))
    await _paginas_de_um(client, lead_id)

    acessos = await _acessos(session)
    assert [a.campo for a in acessos] == ["detalhe", "transcricao", "transcricao", "transcricao"]
    assert {a.entidade_id for a in acessos} == {str(lead_id)}
    assert {a.lead_ref for a in acessos} == {
        lead_ref(CANAL, CHAVE, chave=get_settings().auditoria_chave_do_lead)
    }
    for acesso in acessos:
        assert TELEFONE not in json.dumps(
            {c.name: str(getattr(acesso, c.name)) for c in EventoAuditoria.__table__.columns}
        )


async def _paginas_de_um(client: AsyncClient, lead_id: uuid.UUID) -> None:
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limite": 1}
        if cursor:
            params["cursor"] = cursor
        resposta = await client.get(
            f"{ROTA}/{lead_id}/mensagens", params=params, headers=_bearer("GERENTE")
        )
        cursor = resposta.json()["cursorAnterior"]
        if cursor is None:
            return


async def test_limite_invalido_nao_grava_acesso(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    session.add(_fala())
    await session.commit()
    lead_id = await _apelido(session)

    resposta = await client.get(
        f"{ROTA}/{lead_id}/mensagens", params={"limite": 0}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 422
    assert await _acessos(session) == []


# --- o resumo e a regeneracao (D4, D6) -----------------------------------------


async def test_lead_sem_handoff_tem_resumo_nulo_e_listas_vazias(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """L2, e o estado vazio da TEC-325: listas `[]`, nunca nulas."""
    session.add(_fala())
    await session.commit()
    lead_id = await _apelido(session)

    corpo = (await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))).json()

    assert corpo["resumo"] is None
    assert corpo["qualificacao"] is None
    assert corpo["score"] is None
    for bloco in ("historicoScore", "recomendacoes", "agendamentos", "followups"):
        assert corpo[bloco] == []


async def test_resumo_do_fallback_vem_sinalizado(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A TEC-323 escolhe "Resumo simplificado" por este campo."""
    session.add(_fala())
    await session.commit()
    await _handoff(session, resumo="Resumo do template.", fallback=True)
    lead_id = await _apelido(session)

    resumo = (await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))).json()["resumo"]

    assert resumo["fallback"] is True
    assert resumo["modelo"] is None


async def test_o_resumo_e_o_do_handoff_mais_recente_que_ja_tem_texto(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A geracao e assincrona: o handoff de dois segundos atras ainda nao tem
    texto, e o do anterior e o unico resumo que existe."""
    session.add(_fala())
    await session.commit()
    # CONCLUIDO porque `uq_handoffs_conversa_pendente` admite um so pendente
    # por conversa -- e o antigo, na vida real, ja teria sido devolvido.
    antigo = await _handoff(
        session, resumo="O antigo.", criado_em=INICIO, status=StatusDoHandoff.CONCLUIDO
    )
    await _handoff(session, resumo=None, criado_em=INICIO + timedelta(days=1))
    lead_id = await _apelido(session)

    resumo = (await client.get(f"{ROTA}/{lead_id}", headers=_bearer("GERENTE"))).json()["resumo"]

    assert (resumo["handoffId"], resumo["texto"]) == (str(antigo), "O antigo.")


async def test_regenerar_antes_de_60_segundos_e_429_sem_chamar_o_modelo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, monkeypatch: Any
) -> None:
    """D6, para a TEC-326. O resumo acabou de ser gravado, e o redator nao
    pode ser chamado -- a trava existe para poupar a chamada paga."""
    session.add(_fala())
    await session.commit()
    handoff_id = await _handoff(session, resumo="Recem gerado.")

    async def _nao_pode_ser_chamado(*_: object, **__: object) -> bool:
        raise AssertionError("gerar_resumo chamado dentro da trava")

    monkeypatch.setattr("mobia.api.routes.handoffs.gerar_resumo", _nao_pode_ser_chamado)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 429
    assert 1 <= int(resposta.headers["Retry-After"]) <= 60


async def test_regenerar_depois_de_60_segundos_passa_pela_trava(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, monkeypatch: Any
) -> None:
    """O outro lado da trava: com o carimbo velho, a rota chama o redator."""
    session.add(_fala())
    await session.commit()
    handoff_id = await _handoff(session, resumo="Velho.")
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(resumo_gerado_em=datetime.now(UTC) - timedelta(seconds=61))
    )
    await session.commit()
    chamadas: list[uuid.UUID] = []

    async def _gerar(*_: object, handoff_id: uuid.UUID, **__: object) -> bool:
        chamadas.append(handoff_id)
        return True

    monkeypatch.setattr("mobia.api.routes.handoffs.gerar_resumo", _gerar)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 200, resposta.text
    assert chamadas == [handoff_id]


# --- TEC-327: o polling da conversa assumida, e quem tem a conversa -------------


async def test_depois_devolve_so_as_falas_posteriores(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D1 da TEC-327: a tela pede so o que ainda nao tem, em ordem cronologica,
    e recebe o cursor para o proximo poll."""
    session.add_all([_fala(texto=f"fala {n}", em=INICIO + timedelta(seconds=n)) for n in range(5)])
    await session.commit()
    lead_id = await _apelido(session)
    primeira = (await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("GERENTE"))).json()
    session.add_all(
        [_fala(texto=f"nova {n}", em=INICIO + timedelta(minutes=1, seconds=n)) for n in range(2)]
    )
    await session.commit()

    resposta = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": primeira["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )

    assert resposta.status_code == 200, resposta.text
    assert [i["conteudo"] for i in resposta.json()["itens"]] == ["nova 0", "nova 1"]
    seguinte = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": resposta.json()["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )
    assert seguinte.json()["itens"] == []


async def test_poll_vazio_nao_grava_acesso_e_poll_com_fala_grava(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A decisao do Eduardo (D1 da TEC-327): a trilha registra o conteudo que
    saiu, e um poll sem fala nova nao entregou conteudo nenhum."""
    session.add(_fala(texto="oi", em=INICIO))
    await session.commit()
    lead_id = await _apelido(session)
    primeira = (await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("GERENTE"))).json()
    antes = len(await _acessos(session))

    vazio = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": primeira["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )
    assert vazio.json()["itens"] == []
    # O cursor volta o mesmo: a tela continua pedindo a partir dali.
    assert vazio.json()["cursorPosterior"] == primeira["cursorPosterior"]
    assert len(await _acessos(session)) == antes

    session.add(_fala(texto="Pode ser amanhã às 10h?", em=INICIO + timedelta(minutes=1)))
    await session.commit()
    com_fala = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": primeira["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )

    assert [i["conteudo"] for i in com_fala.json()["itens"]] == ["Pode ser amanhã às 10h?"]
    acessos = await _acessos(session)
    assert len(acessos) == antes + 1
    assert acessos[-1].campo == "transcricao"


async def test_cursor_e_depois_juntos_e_422_sem_gravar(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    session.add(_fala(texto="oi", em=INICIO))
    await session.commit()
    lead_id = await _apelido(session)
    primeira = (await client.get(f"{ROTA}/{lead_id}/mensagens", headers=_bearer("GERENTE"))).json()
    antes = len(await _acessos(session))

    resposta = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": primeira["cursorPosterior"], "cursor": primeira["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )

    assert resposta.status_code == 422
    assert len(await _acessos(session)) == antes


async def test_depois_de_outro_lead_e_422(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    outra = chave_de(CANAL, "5548990000099")
    session.add_all([_fala(texto="daqui", em=INICIO), _fala(chave=outra, texto="de la", em=INICIO)])
    await session.commit()
    lead_id = await _apelido(session)
    outro_id = await _apelido(session, outra)
    de_la = (await client.get(f"{ROTA}/{outro_id}/mensagens", headers=_bearer("GERENTE"))).json()

    resposta = await client.get(
        f"{ROTA}/{lead_id}/mensagens",
        params={"depois": de_la["cursorPosterior"]},
        headers=_bearer("GERENTE"),
    )

    assert resposta.status_code == 422


async def test_o_detalhe_diz_quem_tem_a_conversa(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D2 da TEC-327: sem isto, a faixa "Voce esta no controle" some ao
    recarregar a pagina."""
    paulo = await _corretor(session)
    await session.execute(update(Corretor).where(Corretor.id == paulo).values(nome="Paulo"))
    session.add(_fala(texto="oi", em=INICIO))
    await session.commit()
    await _handoff(session, dono=paulo)
    lead_id = await _apelido(session)
    como_paulo = _bearer("CORRETOR", corretor_id=paulo)

    livre = (await client.get(f"{ROTA}/{lead_id}", headers=como_paulo)).json()
    await client.post(f"{ROTA}/{lead_id}/assumir", headers=como_paulo)
    assumida = (await client.get(f"{ROTA}/{lead_id}", headers=como_paulo)).json()
    await client.post(f"{ROTA}/{lead_id}/devolver", headers=como_paulo)
    devolvida = (await client.get(f"{ROTA}/{lead_id}", headers=como_paulo)).json()

    assert livre["atendimento"] is None
    assert assumida["atendimento"]["assumidoPor"] == {"corretorId": str(paulo), "nome": "Paulo"}
    assert assumida["atendimento"]["assumidoEm"]
    assert devolvida["atendimento"] is None
