"""A 0058 e a rotacao: o telefone sai de toda coluna e passa a morar cifrado. TEC-203, D3.

Molde de `test_migrations.py`: o teste que parte do telefone em claro desce o
esquema para a 0057, semeia em SQL cru -- o esquema e o da 0057 e os modelos
ja sao os novos --, sobe para o head e garante o retorno ao head no fim. Os
que so exercitam a rotacao ou a descida sobre um banco ja reindexado semeiam
direto no head, sem descer. Cada chamada ao Alembic e um
processo novo (~2s aqui); os casos ficam separados mesmo assim porque cada um
afirma uma propriedade diferente da reindexacao, e um teste unico esconderia
qual delas quebrou.
"""

import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mobia.app.config import get_settings
from mobia.domain.auditoria.consulta import montar_filtro
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.repositorio import listar_eventos
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.context.repositorio import ler_resumo
from mobia.domain.identidade import indice
from mobia.domain.identidade.indice import chave_de, indice_de_telefone, revelar
from mobia.domain.identidade.models import aad_do_vinculo
from mobia.domain.identidade.reindexacao import (
    TABELAS_COM_CHAVE_DE_LEAD,
    reindexar,
    reindexar_telefones_dos_vinculos,
)
from mobia.infra.crypto import decrypt, encrypt
from mobia.infra.db import dispose_engine, get_engine, get_sessionmaker

TELEFONE = "5548999990000"
SEM_O_NOVE = "554899990000"
SESSAO = "0b6f5d8e-3c1a-4e2b-9f7d-1a2b3c4d5e6f"
TEXTO_DO_RESUMO = "o lead quer dois quartos no Campeche"
PHONE_NUMBER_ID = "phone-number-id"
# O formato real que `api/routes/widget.py::_chave_do_id` grava: a sessao (ou,
# desde a TEC-203, o HMAC dela) prefixando o id que o cliente escolheu.
ID_DO_WIDGET = "m-1"

# As tabelas cujo texto a varredura inspeciona: as da lista, mais as duas que
# guardam o lead fora de `conversation_key`.
TABELAS_VARRIDAS = (*TABELAS_COM_CHAVE_DE_LEAD, "rate_limit_events", "eventos_auditoria")


def alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True, capture_output=True)


async def _descer_para_a_0057() -> None:
    await dispose_engine()
    alembic("downgrade", "0057")


async def _subir() -> None:
    await dispose_engine()
    alembic("upgrade", "head")
    await dispose_engine()


_MENSAGEM = text(
    """
    INSERT INTO messages (
        id, channel, provider_message_id, sender_external_id, recipient_external_id,
        conversation_key, role, direction, content_type, status, attempts
    ) VALUES (
        :id, :channel, :provider, :sender, :recipient,
        :chave, :role, :direction, 'TEXTO', :status, 0
    )
    """
)


async def _semear_na_0057() -> dict[str, uuid.UUID]:
    """Um lead do WhatsApp em toda tabela que o guardava em claro.

    Mais um segundo lead com o `wa_id` sem o 9 (outra conversa, outra chave) e
    uma sessao web com telefone vinculado.
    """
    ids = {nome: uuid.uuid4() for nome in ("entrada", "saida", "sem_o_nove", "web")}
    async with get_sessionmaker()() as sessao:
        for nome, channel, sender, recipient, chave, role, direction, status in (
            ("entrada", "whatsapp", TELEFONE, PHONE_NUMBER_ID, TELEFONE, "LEAD", "INBOUND",
             "PROCESSED"),
            ("saida", "whatsapp", PHONE_NUMBER_ID, TELEFONE, TELEFONE, "AGENTE", "OUTBOUND",
             None),
            ("sem_o_nove", "whatsapp", SEM_O_NOVE, PHONE_NUMBER_ID, SEM_O_NOVE, "LEAD",
             "INBOUND", "PROCESSED"),
            ("web", "web", SESSAO, "web", SESSAO, "LEAD", "INBOUND", "PROCESSED"),
        ):  # fmt: skip
            if direction == "OUTBOUND":
                provider = None
            elif nome == "web":
                # O formato real do widget: a sessao crua prefixando o id, e
                # nao o `wamid.{id}` generico das outras linhas -- e o que
                # expoe a sessao em claro se `_mover` nao a reescrever.
                provider = f"{SESSAO}:{ID_DO_WIDGET}"
            else:
                provider = f"wamid.{ids[nome]}"
            await sessao.execute(
                _MENSAGEM,
                {
                    "id": ids[nome],
                    "channel": channel,
                    "provider": provider,
                    "sender": sender,
                    "recipient": recipient,
                    "chave": chave,
                    "role": role,
                    "direction": direction,
                    "status": status,
                },
            )
        par = {"c": "whatsapp", "k": TELEFONE}
        await sessao.execute(
            text(
                "INSERT INTO lead_qualification (channel, conversation_key, regiao)"
                " VALUES (:c, :k, 'Campeche')"
            ),
            par,
        )
        await sessao.execute(
            text(
                "INSERT INTO lead_score_audit (id, channel, conversation_key, total_novo,"
                " completude, urgencia, catalogo, engajamento, capacidade, causas)"
                " VALUES (:id, :c, :k, 10, 10, 0, 0, 0, 0, ARRAY['PRIMEIRO_CALCULO'])"
            ),
            {**par, "id": uuid.uuid4()},
        )
        await sessao.execute(
            text(
                "INSERT INTO conversation_intent_audit (id, channel, conversation_key, para,"
                " faixa_descartada) VALUES (:id, :c, :k, 'COMPRA', false)"
            ),
            {**par, "id": uuid.uuid4()},
        )
        agora = datetime.now(UTC)
        await sessao.execute(
            text(
                "INSERT INTO handoffs (id, channel, conversation_key, gatilho, etiqueta,"
                " prioridade, status, criado_em, atualizado_em)"
                " VALUES (:id, :c, :k, 'PEDIU_HUMANO', 'PEDIU_HUMANO', 'NORMAL', 'PENDENTE',"
                " :agora, :agora)"
            ),
            {**par, "id": uuid.uuid4(), "agora": agora},
        )
        await sessao.execute(
            text(
                "INSERT INTO optout_events (id, channel, conversation_key, evento, message_id)"
                " VALUES (:id, :c, :k, 'OPT_OUT', :m)"
            ),
            {**par, "id": uuid.uuid4(), "m": ids["entrada"]},
        )
        await sessao.execute(
            text(
                "INSERT INTO rate_limit_events (id, escopo, chave, channel, volume, limite,"
                " message_id) VALUES (:id, 'numero', :k, :c, 21, 20, :m)"
            ),
            {**par, "id": uuid.uuid4(), "m": ids["entrada"]},
        )
        await sessao.execute(
            text(
                "INSERT INTO conversation_summaries (channel, conversation_key, resumo,"
                " watermark_created_at, watermark_message_id, mensagens_cobertas, modelo)"
                " VALUES (:c, :k, :r, :agora, :m, 1, 'modelo-de-teste')"
            ),
            {
                **par,
                "r": encrypt(TEXTO_DO_RESUMO, aad_do_resumo("whatsapp", TELEFONE)),
                "agora": agora,
                "m": ids["entrada"],
            },
        )
        await sessao.execute(
            text(
                "INSERT INTO vinculos_de_sessao (channel, conversation_key, telefone, message_id)"
                " VALUES ('web', :s, :t, :m)"
            ),
            {"s": SESSAO, "t": TELEFONE, "m": ids["web"]},
        )
        await registrar_evento(
            sessao,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REGISTRADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(uuid.uuid4()),
            lead=("whatsapp", TELEFONE),
        )
        await sessao.commit()
    await dispose_engine()
    return ids


@pytest.fixture
async def semeado_na_0057_e_subido() -> AsyncIterator[dict[str, uuid.UUID]]:
    """Desce, semeia com o telefone em claro, sobe -- e volta ao head no fim."""
    await _descer_para_a_0057()
    try:
        ids = await _semear_na_0057()
        await _subir()
        yield ids
    finally:
        await _subir()


async def _colunas_de_texto(sessao: Any, tabela: str) -> list[str]:
    linhas = await sessao.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = :t AND data_type <> 'bytea'"
        ),
        {"t": tabela},
    )
    return [coluna for (coluna,) in linhas]


async def test_nenhuma_coluna_guarda_o_telefone_depois_da_subida(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    achados = []
    async with get_sessionmaker()() as sessao:
        for tabela in TABELAS_VARRIDAS:
            for coluna in await _colunas_de_texto(sessao, tabela):
                for numero in (TELEFONE, SEM_O_NOVE, SESSAO):
                    quantos = await sessao.scalar(
                        text(f'SELECT count(*) FROM {tabela} WHERE "{coluna}"::text LIKE :n'),
                        {"n": f"%{numero}%"},
                    )
                    if quantos:
                        achados.append(f"{tabela}.{coluna} guarda {numero}")
    assert achados == []


async def test_o_par_vira_chave_de_e_a_identidade_revela_o_cru(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    ids = semeado_na_0057_e_subido
    chave = chave_de("whatsapp", TELEFONE)
    async with get_sessionmaker()() as sessao:
        for tabela in (
            "lead_qualification",
            "lead_score_audit",
            "conversation_intent_audit",
            "handoffs",
            "optout_events",
            "conversation_summaries",
        ):
            chaves = (
                await sessao.scalars(
                    text(f"SELECT conversation_key FROM {tabela} WHERE channel = 'whatsapp'")
                )
            ).all()
            assert chaves == [chave], tabela

        mensagens = {}
        for nome in ("entrada", "saida", "sem_o_nove"):
            mensagens[nome] = (
                await sessao.execute(
                    text(
                        "SELECT conversation_key, sender_external_id, recipient_external_id"
                        " FROM messages WHERE id = :id"
                    ),
                    {"id": ids[nome]},
                )
            ).one()
        entrada, saida, sem_o_nove = (mensagens[n] for n in ("entrada", "saida", "sem_o_nove"))
        assert tuple(entrada) == (chave, chave, PHONE_NUMBER_ID)
        assert tuple(saida) == (chave, PHONE_NUMBER_ID, chave)
        chave_sem_o_nove = chave_de("whatsapp", SEM_O_NOVE)
        assert chave_sem_o_nove != chave, "com e sem o 9 continuam duas conversas"
        assert sem_o_nove.conversation_key == chave_sem_o_nove

        assert await sessao.scalar(text("SELECT chave FROM rate_limit_events")) == chave
        assert await revelar(sessao, "whatsapp", chave) == TELEFONE
        assert await revelar(sessao, "whatsapp", chave_sem_o_nove) == SEM_O_NOVE

        chave_da_sessao = chave_de("web", SESSAO)
        assert await revelar(sessao, "web", chave_da_sessao) == SESSAO
        vinculo = (
            await sessao.execute(
                text(
                    "SELECT conversation_key, telefone_cifrado, telefone_indice"
                    " FROM vinculos_de_sessao"
                )
            )
        ).one()
        assert vinculo.conversation_key == chave_da_sessao
        assert vinculo.telefone_indice == indice_de_telefone(TELEFONE)
        assert (
            decrypt(bytes(vinculo.telefone_cifrado), aad_do_vinculo("web", chave_da_sessao))
            == TELEFONE
        )

        # O id do widget troca o prefixo (a sessao crua) pela chave, e nao so
        # some -- ver `_mover`. O `test_nenhuma_coluna_guarda_o_telefone_...`
        # ja prova que a sessao crua sumiu; isto prova para onde ela foi.
        provider_do_widget = await sessao.scalar(
            text("SELECT provider_message_id FROM messages WHERE id = :id"), {"id": ids["web"]}
        )
        assert provider_do_widget == f"{chave_da_sessao}:{ID_DO_WIDGET}"


async def test_resumo_de_antes_continua_legivel(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    async with get_sessionmaker()() as sessao:
        resumo = await ler_resumo(sessao, "whatsapp", chave_de("whatsapp", TELEFONE))
    assert resumo is not None
    assert resumo.texto == TEXTO_DO_RESUMO


async def test_evento_de_auditoria_de_antes_e_achado_pelo_lead(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    filtro = montar_filtro(
        channel="whatsapp",
        conversation_key=chave_de("whatsapp", TELEFONE),
        chave_do_lead=get_settings().auditoria_chave_do_lead,
    )
    async with get_sessionmaker()() as sessao:
        eventos, _ = await listar_eventos(sessao, filtro=filtro)
    assert [evento.acao for evento in eventos] == [Acao.OPTOUT_REGISTRADO.value]


@pytest.mark.parametrize(
    ("tabela", "coluna"),
    [
        ("lead_score_audit", "total_novo"),
        ("conversation_intent_audit", "para"),
        ("eventos_auditoria", "campo"),
    ],
)
async def test_trigger_de_imutabilidade_volta_ligada(
    semeado_na_0057_e_subido: dict[str, uuid.UUID], tabela: str, coluna: str
) -> None:
    async with get_sessionmaker()() as sessao:
        with pytest.raises(DBAPIError, match="imutavel"):
            await sessao.execute(text(f"UPDATE {tabela} SET {coluna} = {coluna}"))
        await sessao.rollback()


async def _retrato() -> dict[str, list[tuple[Any, ...]]]:
    """Tudo o que a reindexacao pode mexer, em ordem estavel."""
    consultas = {
        tabela: f"SELECT channel, conversation_key FROM {tabela} ORDER BY 1, 2"
        for tabela in TABELAS_COM_CHAVE_DE_LEAD
    }
    consultas["identidades"] = (
        "SELECT channel, conversation_key, valor_cifrado FROM identidades_de_lead ORDER BY 1, 2"
    )
    consultas["remetentes"] = (
        "SELECT id, sender_external_id, recipient_external_id FROM messages ORDER BY 1"
    )
    consultas["rate_limit"] = "SELECT chave FROM rate_limit_events ORDER BY 1"
    consultas["lead_ref"] = "SELECT lead_ref FROM eventos_auditoria ORDER BY 1"
    consultas["resumo"] = "SELECT resumo FROM conversation_summaries ORDER BY 1"
    consultas["vinculo"] = (
        "SELECT telefone_cifrado, telefone_indice FROM vinculos_de_sessao ORDER BY 1"
    )
    async with get_sessionmaker()() as sessao:
        return {
            nome: [tuple(linha) for linha in (await sessao.execute(text(sql))).all()]
            for nome, sql in consultas.items()
        }


async def test_rodar_a_reindexacao_de_novo_nao_muda_nada(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    """A idempotencia que deixa retomar uma subida interrompida (D3)."""
    antes = await _retrato()
    chave_do_lead = get_settings().auditoria_chave_do_lead

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="migracao",
                chave_do_lead_antiga=chave_do_lead,
                chave_do_lead_nova=chave_do_lead,
            )
        )

    assert resultado.mudados == 0
    assert await _retrato() == antes


async def test_descida_devolve_os_valores_originais(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    ids = semeado_na_0057_e_subido
    await _descer_para_a_0057()
    async with get_sessionmaker()() as sessao:
        entrada = (
            await sessao.execute(
                text("SELECT conversation_key, sender_external_id FROM messages WHERE id = :id"),
                {"id": ids["entrada"]},
            )
        ).one()
        saida = await sessao.scalar(
            text("SELECT recipient_external_id FROM messages WHERE id = :id"),
            {"id": ids["saida"]},
        )
        auditoria = await sessao.scalar(text("SELECT conversation_key FROM lead_score_audit"))
        vinculo = (
            await sessao.execute(text("SELECT conversation_key, telefone FROM vinculos_de_sessao"))
        ).one()
        rate_limit = await sessao.scalar(text("SELECT chave FROM rate_limit_events"))
        referencia = await sessao.scalar(text("SELECT lead_ref FROM eventos_auditoria"))
        resumo = await sessao.scalar(text("SELECT resumo FROM conversation_summaries"))
        identidades = await sessao.scalar(text("SELECT to_regclass('identidades_de_lead')"))
        provider_do_widget = await sessao.scalar(
            text("SELECT provider_message_id FROM messages WHERE id = :id"), {"id": ids["web"]}
        )
    await dispose_engine()

    assert tuple(entrada) == (TELEFONE, TELEFONE)
    assert saida == TELEFONE
    assert auditoria == TELEFONE
    assert tuple(vinculo) == (SESSAO, TELEFONE)
    assert rate_limit == TELEFONE
    # A descida devolve a sessao crua na frente do id do widget -- o mesmo
    # formato que `_chave_do_id` gravava antes da TEC-203.
    assert provider_do_widget == f"{SESSAO}:{ID_DO_WIDGET}"
    assert referencia == lead_ref(
        "whatsapp", TELEFONE, chave=get_settings().auditoria_chave_do_lead
    )
    assert decrypt(bytes(resumo), aad_do_resumo("whatsapp", TELEFONE)) == TEXTO_DO_RESUMO
    assert identidades is None


async def test_rotacao_da_chave_de_indice_leva_tudo_para_a_chave_nova(
    semeado_na_0057_e_subido: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O que `scripts/reindexar_leads.py` roda, com a chave de indice trocada."""
    ids = semeado_na_0057_e_subido
    chave_a = chave_de("whatsapp", TELEFONE)
    configuracao_b = get_settings().model_copy(
        update={"lead_indice_chave": "chave-de-indice-B-" + "x" * 40}
    )
    monkeypatch.setattr(indice, "get_settings", lambda: configuracao_b)
    chave_b = chave_de("whatsapp", TELEFONE)
    assert chave_b != chave_a
    chave_do_lead = get_settings().auditoria_chave_do_lead

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga=chave_do_lead,
                chave_do_lead_nova=chave_do_lead,
            )
        )
        await conexao.run_sync(
            lambda conn: reindexar_telefones_dos_vinculos(conn, indice_de_telefone)
        )

    assert resultado.mudados == 3, "o lead, o lead sem o 9 e a sessao web"
    async with get_sessionmaker()() as sessao:
        chaves = (
            await sessao.scalars(
                text("SELECT DISTINCT conversation_key FROM messages WHERE channel = 'whatsapp'")
            )
        ).all()
        assert set(chaves) == {chave_b, chave_de("whatsapp", SEM_O_NOVE)}
        assert await revelar(sessao, "whatsapp", chave_b) == TELEFONE
        resumo = await ler_resumo(sessao, "whatsapp", chave_b)
        assert resumo is not None and resumo.texto == TEXTO_DO_RESUMO
        vinculo = (
            await sessao.execute(
                text(
                    "SELECT conversation_key, telefone_cifrado, telefone_indice"
                    " FROM vinculos_de_sessao"
                )
            )
        ).one()
        assert vinculo.conversation_key == chave_de("web", SESSAO)
        assert vinculo.telefone_indice == indice_de_telefone(TELEFONE)
        assert (
            decrypt(
                bytes(vinculo.telefone_cifrado), aad_do_vinculo("web", vinculo.conversation_key)
            )
            == TELEFONE
        )
        referencia = await sessao.scalar(text("SELECT lead_ref FROM eventos_auditoria"))
        provider_do_widget = await sessao.scalar(
            text("SELECT provider_message_id FROM messages WHERE id = :id"), {"id": ids["web"]}
        )
    assert referencia == lead_ref("whatsapp", chave_b, chave=chave_do_lead)
    # A rotacao troca a chave de indice, e o prefixo do id do widget acompanha.
    assert provider_do_widget == f"{vinculo.conversation_key}:{ID_DO_WIDGET}"


async def test_rotacao_da_chave_do_lead_ref_mantem_a_trilha_achavel(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    """A chave de indice fica; so a do `lead_ref` troca. O par nao se move,
    mas o evento gravado sob a chave A tem de ser achado pela B."""
    chave_a = get_settings().auditoria_chave_do_lead
    configuracao_b = get_settings().model_copy(
        update={"auditoria_chave_do_lead": "chave-do-lead-B-" + "y" * 40}
    )
    chave_b = configuracao_b.auditoria_chave_do_lead
    assert chave_b != chave_a

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga=chave_a,
                chave_do_lead_nova=chave_b,
            )
        )

    # O unico evento semeado; e a contagem que o script usa para avisar que a
    # chave anterior informada nao era a que gravou a trilha.
    assert resultado.lead_refs_recalculados == 1
    chave = chave_de("whatsapp", TELEFONE)
    async with get_sessionmaker()() as sessao:
        pela_b, _ = await listar_eventos(
            sessao,
            filtro=montar_filtro(channel="whatsapp", conversation_key=chave, chave_do_lead=chave_b),
        )
        pela_a, _ = await listar_eventos(
            sessao,
            filtro=montar_filtro(channel="whatsapp", conversation_key=chave, chave_do_lead=chave_a),
        )
    assert [evento.acao for evento in pela_b] == [Acao.OPTOUT_REGISTRADO.value]
    assert pela_a == []


ORFAO = "5548988887777"


async def test_evento_de_rate_limit_orfao_tambem_perde_o_telefone() -> None:
    """Um numero que so aparece em `rate_limit_events` -- a mensagem ja saiu
    pela retencao, o evento fica -- nao pode sobrar em claro depois da 0058."""
    await _descer_para_a_0057()
    try:
        async with get_sessionmaker()() as sessao:
            await sessao.execute(
                text(
                    "INSERT INTO rate_limit_events (id, escopo, chave, channel, volume, limite)"
                    " VALUES (:id, 'numero', :k, 'whatsapp', 21, 20)"
                ),
                {"id": uuid.uuid4(), "k": ORFAO},
            )
            await sessao.commit()
        await _subir()

        chave = chave_de("whatsapp", ORFAO)
        async with get_sessionmaker()() as sessao:
            assert await sessao.scalar(text("SELECT chave FROM rate_limit_events")) == chave
            assert await revelar(sessao, "whatsapp", chave) == ORFAO

        # E a descida tem de onde tirar o valor cru: a subida gravou a identidade.
        await _descer_para_a_0057()
        async with get_sessionmaker()() as sessao:
            assert await sessao.scalar(text("SELECT chave FROM rate_limit_events")) == ORFAO
        await dispose_engine()
    finally:
        await _subir()


async def test_rotacao_leva_a_identidade_orfa_para_a_chave_nova(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identidade sem linha em tabela nenhuma (o lead so deixou a trilha) ainda
    tem de trocar de chave, e o `lead_ref` dela junto."""
    chave_do_lead = get_settings().auditoria_chave_do_lead
    async with get_sessionmaker()() as sessao:
        chave_a = await indice.registrar(sessao, "whatsapp", ORFAO)
        await registrar_evento(
            sessao,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REGISTRADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(uuid.uuid4()),
            lead=("whatsapp", chave_a),
        )
        await sessao.commit()

    configuracao_b = get_settings().model_copy(
        update={"lead_indice_chave": "chave-de-indice-B-" + "x" * 40}
    )
    monkeypatch.setattr(indice, "get_settings", lambda: configuracao_b)
    chave_b = chave_de("whatsapp", ORFAO)
    assert chave_b != chave_a

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga=chave_do_lead,
                chave_do_lead_nova=chave_do_lead,
            )
        )

    assert resultado.mudados == 1
    async with get_sessionmaker()() as sessao:
        assert await revelar(sessao, "whatsapp", chave_b) == ORFAO
        with pytest.raises(indice.IdentidadeAusente):
            await revelar(sessao, "whatsapp", chave_a)
        referencia = await sessao.scalar(text("SELECT lead_ref FROM eventos_auditoria"))
    assert referencia == lead_ref("whatsapp", chave_b, chave=chave_do_lead)


async def test_falha_no_meio_propaga_o_erro_original_e_nao_o_da_trigger() -> None:
    """Com a transacao abortada, religar a trigger reprovaria com
    `InFailedSqlTransaction` e esconderia a causa. A causa tem de subir."""
    async with get_sessionmaker()() as sessao:
        await indice.registrar(sessao, "whatsapp", ORFAO)
        await sessao.execute(
            text(
                "INSERT INTO lead_qualification (channel, conversation_key, regiao)"
                " VALUES ('whatsapp', :k, 'Campeche')"
            ),
            {"k": chave_de("whatsapp", ORFAO)},
        )
        await sessao.commit()
    chave_do_lead = get_settings().auditoria_chave_do_lead

    # 65 caracteres nao cabem no String(64) de `conversation_key`: o UPDATE do
    # primeiro par reprova dentro do loop.
    with pytest.raises(DBAPIError, match="value too long") as erro:
        async with get_engine().begin() as conexao:
            await conexao.run_sync(
                lambda conn: reindexar(
                    conn,
                    tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                    nova_chave=lambda _channel, _valor: "x" * 65,
                    modo="rotacao",
                    chave_do_lead_antiga=chave_do_lead,
                    chave_do_lead_nova=chave_do_lead,
                )
            )
    assert "InFailedSqlTransaction" not in str(erro.value)


SEM_IDENTIDADE = "5548977776666"


@pytest.mark.parametrize("modo", ["rotacao", "reversao"])
async def test_par_sem_identidade_e_pulado_e_contado_e_os_outros_seguem(
    modo: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Par orfao -- chave gravada sem identidade, por bug antigo ou por erro de
    operador -- nao derruba a rotacao nem a descida de todo mundo. Fica onde
    esta, e o resultado diz quantos ficaram."""
    chave_do_lead = get_settings().auditoria_chave_do_lead
    orfa = chave_de("whatsapp", SEM_IDENTIDADE)
    async with get_sessionmaker()() as sessao:
        chave_a = await indice.registrar(sessao, "whatsapp", ORFAO)
        for chave in (chave_a, orfa):
            await sessao.execute(
                text(
                    "INSERT INTO lead_qualification (channel, conversation_key, regiao)"
                    " VALUES ('whatsapp', :k, 'Campeche')"
                ),
                {"k": chave},
            )
        await sessao.commit()

    configuracao_b = get_settings().model_copy(
        update={"lead_indice_chave": "chave-de-indice-B-" + "x" * 40}
    )
    monkeypatch.setattr(indice, "get_settings", lambda: configuracao_b)
    esperada = chave_de("whatsapp", ORFAO) if modo == "rotacao" else ORFAO

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de if modo == "rotacao" else (lambda _c, valor: valor),
                modo=modo,  # type: ignore[arg-type]
                chave_do_lead_antiga=chave_do_lead,
                chave_do_lead_nova=chave_do_lead,
            )
        )

    assert resultado.mudados == 1
    assert resultado.sem_identidade == 1
    async with get_sessionmaker()() as sessao:
        chaves = (
            await sessao.scalars(text("SELECT conversation_key FROM lead_qualification"))
        ).all()
    assert set(chaves) == {esperada, orfa}


async def test_chave_anterior_errada_nao_recalcula_lead_ref_nenhum(
    semeado_na_0057_e_subido: dict[str, uuid.UUID],
) -> None:
    """Com a chave ANTERIOR errada nenhum `lead_ref` casa, e o resultado diz
    zero -- e o sinal que `scripts/reindexar_leads.py` transforma em aviso."""
    chave_b = "chave-do-lead-B-" + "y" * 40

    async with get_engine().begin() as conexao:
        resultado = await conexao.run_sync(
            lambda conn: reindexar(
                conn,
                tabelas=TABELAS_COM_CHAVE_DE_LEAD,
                nova_chave=chave_de,
                modo="rotacao",
                chave_do_lead_antiga="chave-que-nunca-gravou-nada-" + "z" * 30,
                chave_do_lead_nova=chave_b,
            )
        )

    assert resultado.lead_refs_recalculados == 0
