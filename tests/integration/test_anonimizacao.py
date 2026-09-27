"""A anonimizacao do lead: pseudonimo sem volta, metricas intactas. TEC-207, D1.

Semeia um lead do WhatsApp em toda tabela que o guarda -- mensagens de
entrada e saida com conteudo, resumo, qualificacao, trilhas de score e
intencao, handoff com resumo, agendamento, consentimento, opt-out, midia
armazenada de verdade no disco, evento de rate limit, apelido, evento de
auditoria e duas solicitacoes abertas -- e confere o que sobra depois de
`eliminacao.anonimizar`. A varredura de texto e a de
`test_reindexacao_do_lead.py`, com a chave antiga no lugar do telefone cru
(desde a TEC-203 a coluna guarda o HMAC, e e ele que deixa de poder aparecer).
"""

import asyncio
import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import _agendar, _corretor, _falar, _handoff_aceito, _lead, eventos_de_log
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.handoff.models import aad_do_resumo_de_handoff
from mobia.domain.identidade import indice
from mobia.domain.identidade.models import aad_do_vinculo
from mobia.domain.identidade.reindexacao import TABELAS_COM_CHAVE_DE_LEAD
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import MessageTelemetry
from mobia.domain.metricas.custo import custo_do_periodo
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.politica import chave_do_objeto
from mobia.domain.titular import eliminacao
from mobia.domain.titular.anonimizacao import anonimizar_lead
from mobia.domain.titular.repositorio import registrar_solicitacao
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_engine

CANAL = "whatsapp"
TELEFONE = "5548999990000"
SESSAO = "0b6f5d8e-3c1a-4e2b-9f7d-1a2b3c4d5e6f"
PHONE_NUMBER_ID = "222222222"
NASCEU = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")

# O wamid real da Meta e base64 de um protobuf que carrega o `wa_id` em claro
# (`HBgNNTU0ODk5...` decodifica para `...5548999...`). Os tres bytes da frente
# alinham o telefone numa fronteira de base64, e entao os primeiros 12 digitos
# viram exatamente `TELEFONE_EM_BASE64` dentro do id -- e o que a varredura
# procura, alem do telefone cru.
WAMID_REAL = (
    "wamid." + base64.b64encode(b"\x1c\x18\x0d" + TELEFONE.encode() + b"\x15\x02\x00").decode()
)
TELEFONE_EM_BASE64 = base64.b64encode(TELEFONE.encode()[:12]).decode()

# As tabelas cujo texto a varredura inspeciona: as da lista, mais a que guarda
# o lead fora de `conversation_key`. `eventos_auditoria` fica de fora de
# proposito -- a trilha nao e tocada (D1, item 5), e o que ela guarda e o
# `lead_ref`, nao a chave.
TABELAS_VARRIDAS = (*TABELAS_COM_CHAVE_DE_LEAD, "rate_limit_events")


@dataclass(frozen=True)
class Semeado:
    chave: str
    eliminacao: uuid.UUID
    acesso: uuid.UUID
    blob: Path
    blob_pendente: Path


async def _semear_lead_completo(session: AsyncSession, armazem_dir: Path) -> Semeado:
    chave = await indice.registrar(session, CANAL, TELEFONE)
    await session.commit()

    # Entradas (`_lead`), conversa e qualificacao; uma saida do agente.
    await _lead(
        session,
        conversa=chave,
        nasceu_em=NASCEU,
        falas=2,
        qualificado_em=NASCEU + timedelta(hours=1),
        temperatura="QUENTE",
        intencao="COMPRA",
    )
    saida = await _falar(
        session, conversa=chave, em=NASCEU + timedelta(minutes=5), direcao=MessageDirection.OUTBOUND
    )
    await session.flush()
    session.add(
        MessageTelemetry(
            message_id=saida,
            model="claude-sonnet-5",
            subagent="classificador",
            tokens_in=1000,
            tokens_out=100,
            cost_usd=Decimal("0.012000"),
            latency_ms=900,
            created_at=NASCEU + timedelta(minutes=5),
        )
    )
    await session.commit()

    # Uma entrada com payload, envelope e midia guardada no disco.
    com_midia = await _falar(session, conversa=chave, em=NASCEU + timedelta(minutes=10))
    await session.flush()
    await session.execute(
        text(
            "UPDATE messages SET raw_payload = :p, envelope_context = :e, content_type = 'IMAGEM',"
            " provider_message_id = :w WHERE id = :id"
        ),
        {
            "id": com_midia,
            "w": WAMID_REAL,
            "p": encrypt('{"from": "5548999990000"}', aad_de(com_midia, "raw_payload")),
            "e": encrypt("{}", aad_de(com_midia, "envelope_context")),
        },
    )
    chave_do_blob = chave_do_objeto(com_midia)
    await ArmazemLocal(armazem_dir).guardar(chave_do_blob, b"blob-cifrado")
    await session.execute(
        text(
            "INSERT INTO midias_recebidas (message_id, media_id_da_meta, mime_type,"
            " chave_no_armazem, status) VALUES (:m, 'media-1', 'image/jpeg', :k, 'ARMAZENADA')"
        ),
        {"m": com_midia, "k": chave_do_blob},
    )
    # O download em voo: a linha ainda PENDENTE, sem `chave_no_armazem`, mas o
    # job ja gravou o blob na chave deterministica. A anonimizacao tem de
    # apaga-lo mesmo assim -- a linha some, e o job nao tem mais onde gravar.
    em_voo = await _falar(session, conversa=chave, em=NASCEU + timedelta(minutes=11))
    await session.flush()
    await ArmazemLocal(armazem_dir).guardar(chave_do_objeto(em_voo), b"blob-em-voo")
    await session.execute(
        text(
            "INSERT INTO midias_recebidas (message_id, media_id_da_meta, mime_type, status)"
            " VALUES (:m, 'media-2', 'image/jpeg', 'PENDENTE')"
        ),
        {"m": em_voo},
    )

    par = {"c": CANAL, "k": chave}
    await session.execute(
        text(
            "INSERT INTO lead_score_audit (id, channel, conversation_key, total_novo,"
            " completude, urgencia, catalogo, engajamento, capacidade, causas)"
            " VALUES (:id, :c, :k, 10, 10, 0, 0, 0, 0, ARRAY['PRIMEIRO_CALCULO'])"
        ),
        {**par, "id": uuid.uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO conversation_intent_audit (id, channel, conversation_key, para,"
            " faixa_descartada) VALUES (:id, :c, :k, 'COMPRA', false)"
        ),
        {**par, "id": uuid.uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO conversation_summaries (channel, conversation_key, resumo,"
            " watermark_created_at, watermark_message_id, mensagens_cobertas, modelo)"
            " VALUES (:c, :k, :r, :agora, :m, 1, 'modelo-de-teste')"
        ),
        {
            **par,
            "r": encrypt("quer dois quartos", aad_do_resumo(CANAL, chave)),
            "agora": NASCEU,
            "m": saida,
        },
    )
    await session.execute(
        text(
            "INSERT INTO consentimentos (id, channel, conversation_key, marketing, texto_exibido)"
            " VALUES (:id, :c, :k, true, 'Posso te mandar novidades?')"
        ),
        {**par, "id": uuid.uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO optout_events (id, channel, conversation_key, evento, message_id)"
            " VALUES (:id, :c, :k, 'OPT_OUT', :m)"
        ),
        {**par, "id": uuid.uuid4(), "m": saida},
    )
    await session.execute(
        text(
            "INSERT INTO rate_limit_events (id, escopo, chave, channel, volume, limite,"
            " message_id) VALUES (:id, 'numero', :k, :c, 21, 20, :m)"
        ),
        {**par, "id": uuid.uuid4(), "m": com_midia},
    )
    await session.execute(
        text(
            "INSERT INTO referencias_de_lead (id, channel, conversation_key, criado_em)"
            " VALUES (:id, :c, :k, now())"
        ),
        {**par, "id": uuid.uuid4()},
    )
    await session.commit()

    corretor = await _corretor(session)
    await _handoff_aceito(
        session, conversa=chave, em=NASCEU + timedelta(hours=2), corretor_id=corretor
    )
    handoff_id = await session.scalar(
        text("SELECT id FROM handoffs WHERE conversation_key = :k"), {"k": chave}
    )
    await session.execute(
        text("UPDATE handoffs SET resumo = :r WHERE id = :id"),
        {"id": handoff_id, "r": encrypt("resumo do handoff", aad_do_resumo_de_handoff(handoff_id))},
    )
    await session.commit()
    await _agendar(session, conversa=chave, corretor_id=corretor)

    await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.OPTOUT_REGISTRADO,
        entidade=Entidade.OPTOUT_EVENT,
        entidade_id=str(uuid.uuid4()),
        lead=(CANAL, chave),
    )
    eliminacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=chave,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
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
    return Semeado(
        chave=chave,
        eliminacao=eliminacao_id,
        acesso=acesso_id,
        blob=armazem_dir / chave_do_blob,
        blob_pendente=armazem_dir / chave_do_objeto(em_voo),
    )


@pytest.fixture
async def semeado(session: AsyncSession, tmp_path: Path) -> Semeado:
    return await _semear_lead_completo(session, tmp_path)


async def _colunas_de_texto(sessao: AsyncSession, tabela: str) -> list[str]:
    linhas = await sessao.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = :t AND data_type <> 'bytea'"
        ),
        {"t": tabela},
    )
    return [coluna for (coluna,) in linhas]


async def _varrer(sessao: AsyncSession, procurados: tuple[str, ...]) -> list[str]:
    achados = []
    for tabela in TABELAS_VARRIDAS:
        for coluna in await _colunas_de_texto(sessao, tabela):
            for procurado in procurados:
                quantos = await sessao.scalar(
                    text(f'SELECT count(*) FROM {tabela} WHERE "{coluna}"::text LIKE :n'),
                    {"n": f"%{procurado}%"},
                )
                if quantos:
                    achados.append(f"{tabela}.{coluna} guarda {procurado}")
    return achados


async def _anonimizar(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, solicitacao: uuid.UUID
) -> None:
    await eliminacao.anonimizar(session_factory, ArmazemLocal(tmp_path), solicitacao_id=solicitacao)


async def test_nenhuma_coluna_guarda_a_chave_antiga_nem_o_telefone(
    semeado: Semeado,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # A varredura acha o que semeamos antes -- sem isso, lista vazia depois
    # nao provaria nada.
    assert await _varrer(session, (semeado.chave,)) != []
    assert TELEFONE_EM_BASE64 in WAMID_REAL
    assert await _varrer(session, (TELEFONE_EM_BASE64,)) == [
        f"messages.provider_message_id guarda {TELEFONE_EM_BASE64}"
    ]

    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        assert await _varrer(sessao, (semeado.chave, TELEFONE, TELEFONE_EM_BASE64)) == []


async def test_identidade_vinculo_resumo_e_apelido_somem(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        for tabela in (
            "identidades_de_lead",
            "vinculos_de_sessao",
            "conversation_summaries",
            "referencias_de_lead",
            "midias_recebidas",
        ):
            assert await sessao.scalar(text(f"SELECT count(*) FROM {tabela}")) == 0, tabela


async def test_conteudo_some_e_as_linhas_ficam(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    assert semeado.blob.exists()
    assert semeado.blob_pendente.exists()

    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        mensagens = (
            await sessao.execute(
                text("SELECT text_body, raw_payload, envelope_context, created_at FROM messages")
            )
        ).all()
        assert len(mensagens) == 5, "as linhas ficam: sao elas que a coorte conta"
        assert all(m[:3] == (None, None, None) for m in mensagens)
        assert await sessao.scalar(text("SELECT count(*) FROM message_telemetry")) == 1
        assert await sessao.scalar(text("SELECT resumo FROM handoffs")) is None
    assert not semeado.blob.exists()
    assert not semeado.blob_pendente.exists(), "o download em voo nao deixa orfao"


async def _metricas(sessao: AsyncSession) -> tuple[Any, ...]:
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)
    etapas = await contar_etapas(sessao, recorte=recorte)
    indicadores = await calcular_indicadores(sessao, recorte=recorte, novos=etapas[Etapa.NOVO])
    custo = await custo_do_periodo(sessao, recorte=recorte)
    quentes = montar_recorte(
        de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, temperatura="QUENTE"
    )
    return (
        etapas,
        indicadores,
        custo,
        await contar_etapas(sessao, recorte=quentes),
        await custo_do_periodo(sessao, recorte=quentes),
    )


async def test_metricas_iguais_antes_e_depois(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with session_factory() as sessao:
        antes = await _metricas(sessao)
    # O lead semeado conta: sem isso, "iguais" valeria para um funil vazio.
    assert antes[0][Etapa.NOVO] == 1
    assert antes[2].total_usd > 0

    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        assert await _metricas(sessao) == antes


@pytest.mark.parametrize(
    ("tabela", "coluna"),
    [("lead_score_audit", "total_novo"), ("conversation_intent_audit", "para")],
)
async def test_trigger_de_imutabilidade_volta_ligada(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    tabela: str,
    coluna: str,
) -> None:
    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        with pytest.raises(DBAPIError, match="imutavel"):
            await sessao.execute(text(f"UPDATE {tabela} SET {coluna} = {coluna}"))
        await sessao.rollback()


async def _trilha(sessao: AsyncSession) -> list[tuple[Any, ...]]:
    return [
        tuple(linha)
        for linha in (
            await sessao.execute(text("SELECT * FROM eventos_auditoria ORDER BY id"))
        ).all()
    ]


async def test_trilha_so_ganha_o_lead_anonimizado(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with session_factory() as sessao:
        antes = await _trilha(sessao)
        ref_antigo = await sessao.scalar(
            text("SELECT lead_ref FROM eventos_auditoria WHERE acao = 'OPTOUT_REGISTRADO'")
        )

    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        depois = await _trilha(sessao)
        novo = (
            await sessao.execute(
                text(
                    "SELECT acao, entidade, entidade_id, lead_ref FROM eventos_auditoria"
                    " WHERE acao = 'LEAD_ANONIMIZADO'"
                )
            )
        ).one()
    assert len(depois) == len(antes) + 1
    assert all(linha in depois for linha in antes), "nenhum evento antigo mudou"
    assert tuple(novo) == (
        Acao.LEAD_ANONIMIZADO.value,
        Entidade.SOLICITACAO_DE_TITULAR.value,
        str(semeado.eliminacao),
        ref_antigo,
    ), "registrado sobre a solicitacao, com o lead_ref do par antigo"


async def _solicitacoes(sessao: AsyncSession) -> dict[str, tuple[Any, ...]]:
    linhas = await sessao.execute(
        text(
            "SELECT tipo, status, channel, conversation_key, atendida_em"
            " FROM solicitacoes_de_titular"
        )
    )
    return {linha.tipo: tuple(linha)[1:] for linha in linhas}


async def test_solicitacoes_viram_atendidas_sem_par_e_repetir_nao_faz_nada(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: Any,
) -> None:
    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        depois = await _solicitacoes(sessao)
        trilha = await _trilha(sessao)
    # A ELIMINACAO executada e tambem a ACESSO aberta do mesmo par: depois da
    # anonimizacao nao ha dado a entregar, e uma ABERTA seria arrastada para
    # o pseudonimo pela troca de chave.
    for tipo in ("ELIMINACAO", "ACESSO"):
        status, channel, conversation_key, atendida_em = depois[tipo]
        assert (status, channel, conversation_key) == ("ATENDIDA", None, None), tipo
        assert atendida_em is not None, tipo

    with caplog.at_level("INFO"):
        await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        assert await _solicitacoes(sessao) == depois
        assert await _trilha(sessao) == trilha
    ((_, evento),) = eventos_de_log(caplog, "titular.anonimizacao_ignorada")
    assert evento["status"] == StatusDaSolicitacao.ATENDIDA.value


async def test_blob_que_nao_apaga_loga_e_a_anonimizacao_fica(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: Any,
) -> None:
    class _ArmazemQueFalha(ArmazemLocal):
        async def apagar(self, chave: str) -> None:
            raise OSError("disco indisponivel")

    with caplog.at_level("WARNING"):
        await eliminacao.anonimizar(
            session_factory, _ArmazemQueFalha(tmp_path), solicitacao_id=semeado.eliminacao
        )

    chaves = sorted(e["chave"] for _, e in eventos_de_log(caplog, "titular.midia_nao_apagada"))
    assert chaves == sorted(
        b.relative_to(tmp_path).as_posix() for b in (semeado.blob, semeado.blob_pendente)
    )
    async with session_factory() as sessao:
        assert await sessao.scalar(text("SELECT count(*) FROM identidades_de_lead")) == 0
        assert (await _solicitacoes(sessao))["ELIMINACAO"][0] == "ATENDIDA"


async def _semear_web(session: AsyncSession) -> str:
    chave = await indice.registrar(session, "web", SESSAO)
    for numero in range(2):
        identificador = await _falar(
            session, conversa=chave, em=NASCEU + timedelta(minutes=numero), canal="web"
        )
        await session.flush()
        # O formato real de `api/routes/widget.py::_chave_do_id`: a chave da
        # sessao prefixando o id que o cliente escolheu.
        await session.execute(
            text("UPDATE messages SET provider_message_id = :p WHERE id = :id"),
            {"id": identificador, "p": f"{chave}:m-{numero}"},
        )
    await session.execute(
        text(
            "INSERT INTO vinculos_de_sessao (channel, conversation_key, message_id,"
            " telefone_cifrado, telefone_indice) VALUES ('web', :k, :m, :t, :i)"
        ),
        {
            "k": chave,
            "m": identificador,
            "t": encrypt(TELEFONE, aad_do_vinculo("web", chave)),
            "i": indice.indice_de_telefone(TELEFONE),
        },
    )
    await session.commit()
    return chave


async def test_web_a_chave_da_sessao_some_tambem_do_provider_message_id(
    session: AsyncSession,
) -> None:
    chave = await _semear_web(session)
    assert await _varrer(session, (chave,)) != []

    def _anonimizar_web(conn: Connection) -> list[str]:
        return anonimizar_lead(conn, channel="web", conversation_key=chave)

    async with get_engine().begin() as conexao:
        assert await conexao.run_sync(_anonimizar_web) == []

    assert await _varrer(session, (chave, SESSAO, TELEFONE)) == []
    linhas = (await session.execute(text("SELECT id, provider_message_id FROM messages"))).all()
    assert all(provider == f"anon:{id_}" for id_, provider in linhas)
    assert await session.scalar(text("SELECT count(*) FROM vinculos_de_sessao")) == 0


async def test_so_executa_solicitacao_de_eliminacao(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: Any,
) -> None:
    """Um pedido de ACESSO nao autoriza apagar nada, mesmo ABERTO."""
    with caplog.at_level("INFO"):
        await _anonimizar(session_factory, tmp_path, semeado.acesso)

    async with session_factory() as sessao:
        assert await sessao.scalar(text("SELECT count(*) FROM identidades_de_lead")) == 1
        solicitacoes = await _solicitacoes(sessao)
    assert solicitacoes["ACESSO"][:3] == ("ABERTA", CANAL, semeado.chave)
    assert solicitacoes["ELIMINACAO"][0] == "ABERTA"
    assert semeado.blob.exists()
    ((_, evento),) = eventos_de_log(caplog, "titular.anonimizacao_ignorada")
    assert (evento["status"], evento["tipo"]) == ("ABERTA", "ACESSO")


async def test_eliminar_o_whatsapp_apaga_o_vinculo_do_mesmo_telefone_no_widget(
    semeado: Semeado,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A sessao web onde a pessoa digitou o mesmo telefone (TEC-129) guarda o
    numero no vinculo -- a unica linha fora do par do WhatsApp que o guarda.
    Sai o vinculo; a conversa web, que e outro par, fica."""
    chave_web = await _semear_web(session)
    indice_do_telefone = indice.indice_de_telefone(TELEFONE)
    assert await _varrer(session, (indice_do_telefone,)) != []

    await _anonimizar(session_factory, tmp_path, semeado.eliminacao)

    async with session_factory() as sessao:
        assert await sessao.scalar(text("SELECT count(*) FROM vinculos_de_sessao")) == 0
        assert await _varrer(sessao, (TELEFONE, indice_do_telefone)) == []
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM messages WHERE conversation_key = :k"),
                {"k": chave_web},
            )
            == 2
        )


async def test_cancelamento_no_meio_do_apagar_loga_as_chaves_restantes_e_repropaga(
    semeado: Semeado,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: Any,
) -> None:
    """O worker pode cancelar o job no meio do laco de blobs (job_timeout,
    SIGTERM). O commit ja aconteceu; o que falta e dizer quais blobs podem ter
    ficado orfaos -- e o cancelamento tem de continuar sendo cancelamento."""

    class _ArmazemCancelado(ArmazemLocal):
        async def apagar(self, chave: str) -> None:
            raise asyncio.CancelledError

    with caplog.at_level("WARNING"), pytest.raises(asyncio.CancelledError):
        await eliminacao.anonimizar(
            session_factory, _ArmazemCancelado(tmp_path), solicitacao_id=semeado.eliminacao
        )

    ((_, evento),) = eventos_de_log(caplog, "titular.midia_apagamento_cancelado")
    assert sorted(evento["chaves_restantes"]) == sorted(
        b.relative_to(tmp_path).as_posix() for b in (semeado.blob, semeado.blob_pendente)
    )
    assert semeado.blob.exists() and semeado.blob_pendente.exists()
    async with session_factory() as sessao:
        assert await sessao.scalar(text("SELECT count(*) FROM identidades_de_lead")) == 0
