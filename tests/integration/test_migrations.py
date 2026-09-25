"""A migration 0003 tem de sobreviver a um banco que ja carrega duplicatas.

O esquema ate a 0002 permitia duas linhas com o mesmo `provider_message_id` de
proposito -- a dedup era o TEC-125. Reentrega da Meta e exatamente o que produz
essas linhas, entao qualquer banco com trafego real chega na 0003 violando a
constraint que ela cria. O resto da suite nao pegaria isso: o conftest migra um
banco recem-truncado, onde nunca ha o que colidir.

A partir da 0004 este teste tambem prova o backfill de cifra: as linhas sao
inseridas em texto claro no esquema da 0002 e tem de voltar cifradas no head.
"""

import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, decrypt, encrypt, encrypt_json
from mobia.infra.db import dispose_engine, get_sessionmaker

INSERIR_LINHA = text(
    """
    INSERT INTO messages (
        id, channel, provider_message_id, sender_external_id,
        recipient_external_id, content_type, text_body, raw_payload,
        status, attempts, received_at
    ) VALUES (
        :id, :channel, :provider_message_id, '5511911112222',
        '222222222', 'text', :text_body, '{}'::jsonb,
        'RECEIVED', 0, now() - make_interval(secs => :idade)
    )
    """
)


def alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def esquema_na_0002():
    """Volta o esquema para antes da dedup e garante o retorno ao head."""
    await dispose_engine()
    alembic("downgrade", "0002")
    try:
        yield
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()


async def test_upgrade_sobre_banco_com_duplicatas(esquema_na_0002) -> None:
    """Um unico ciclo downgrade/upgrade cobrindo os tres casos que importam.

    Cada chamada ao alembic e um processo Python novo e custa dezenas de
    segundos aqui, entao os casos moram num teste so de proposito.
    """
    antiga, recente = uuid.uuid4(), uuid.uuid4()

    linhas = [
        # Duplicata real: a Meta reentregou o mesmo wamid.
        (antiga, "whatsapp", "wamid.REENTREGUE", "primeira entrega", 600),
        (recente, "whatsapp", "wamid.REENTREGUE", "reentrega da Meta", 60),
        # Mensagem sem duplicata: nao pode ser tocada.
        (uuid.uuid4(), "whatsapp", "wamid.INTOCADA", "mensagem distinta", 300),
        # Mesmo id em canais diferentes: legitimo, a constraint e composta.
        (uuid.uuid4(), "whatsapp", "id.COMPARTILHADO", "via whatsapp", 120),
        (uuid.uuid4(), "web", "id.COMPARTILHADO", "via web", 120),
    ]

    async with get_sessionmaker()() as sessao:
        for identificador, canal, provider_message_id, corpo, idade in linhas:
            await sessao.execute(
                INSERIR_LINHA,
                {
                    "id": identificador,
                    "channel": canal,
                    "provider_message_id": provider_message_id,
                    "text_body": corpo,
                    "idade": idade,
                },
            )
        await sessao.commit()

    await dispose_engine()
    alembic("upgrade", "head")

    async with get_sessionmaker()() as sessao:
        sobreviventes = (
            await sessao.execute(
                text(
                    "SELECT id, text_body FROM messages"
                    " WHERE provider_message_id = 'wamid.REENTREGUE'"
                )
            )
        ).all()
        intocada = await sessao.scalar(
            text("SELECT count(*) FROM messages WHERE provider_message_id = 'wamid.INTOCADA'")
        )
        canais = (
            await sessao.execute(
                text(
                    "SELECT channel FROM messages"
                    " WHERE provider_message_id = 'id.COMPARTILHADO' ORDER BY channel"
                )
            )
        ).all()

    assert len(sobreviventes) == 1, "a migration tem de resolver a duplicata, nao abortar"
    assert sobreviventes[0].id == antiga, "sobrevive a primeira entrega, que foi a processada"
    assert (
        decrypt(sobreviventes[0].text_body, aad_de(sobreviventes[0].id, "text_body"))
        == "primeira entrega"
    ), "a 0004 tem de cifrar as linhas que ja existiam, nao so as novas"
    assert intocada == 1, "mensagem sem duplicata nao pode ser afetada"
    assert [linha.channel for linha in canais] == ["web", "whatsapp"], (
        "id igual em canais diferentes e legitimo"
    )


async def test_downgrade_decifra_text_body_e_raw_payload(session) -> None:
    """A metade irreversivel da 0004 nao tinha cobertura com dado real nenhum.

    `esquema_na_0002` baixa o esquema antes de qualquer INSERT -- prova so o
    backfill do upgrade. Aqui o ciclo e o inverso: sobe para o head, grava pelo
    ORM (cifrado de verdade), desce para a 0003 e confere o que o downgrade da
    migration promete: `text_body` decifrado de volta para texto claro,
    `raw_payload` decifrado de volta para jsonb consultavel com a estrutura
    aninhada intacta (nao so nao-nulo), `raw_payload` NULL virando `'{}'` em vez
    de violar o NOT NULL restaurado, e a linha OUTBOUND apagada (ver a
    docstring do modulo da migration). Volta para o head no fim, como o
    fixture `esquema_na_0002` ja faz.
    """
    com_payload, sem_payload, de_saida = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = {"id": "wamid.NESTED", "envelope": {"tipo": "text"}}

    session.add_all(
        [
            Message(
                id=com_payload,
                channel="whatsapp",
                provider_message_id="wamid.DOWNGRADE_COM_PAYLOAD",
                sender_external_id="5511911112222",
                recipient_external_id="222222222",
                conversation_key="5511911112222",
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("mensagem com payload", aad_de(com_payload, "text_body")),
                raw_payload=encrypt_json(payload, aad_de(com_payload, "raw_payload")),
                status=MessageStatus.RECEIVED,
            ),
            Message(
                id=sem_payload,
                channel="whatsapp",
                provider_message_id="wamid.DOWNGRADE_SEM_PAYLOAD",
                sender_external_id="5511911112222",
                recipient_external_id="222222222",
                conversation_key="5511911112222",
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("mensagem sem payload", aad_de(sem_payload, "text_body")),
                raw_payload=None,
                status=MessageStatus.RECEIVED,
            ),
            Message(
                id=de_saida,
                channel="whatsapp",
                provider_message_id=None,
                conversation_key="5511911112222",
                role=MessageRole.AGENTE,
                direction=MessageDirection.OUTBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("fala do agente", aad_de(de_saida, "text_body")),
                raw_payload=None,
                status=None,
            ),
        ]
    )
    await session.commit()

    await dispose_engine()
    alembic("downgrade", "0003")
    try:
        async with get_sessionmaker()() as sessao:
            texto_com_payload = await sessao.scalar(
                text("SELECT text_body FROM messages WHERE id = :id"), {"id": com_payload}
            )
            tipo_aninhado = await sessao.scalar(
                text("SELECT raw_payload -> 'envelope' ->> 'tipo' FROM messages WHERE id = :id"),
                {"id": com_payload},
            )
            raw_payload_vazio = await sessao.scalar(
                text("SELECT raw_payload::text FROM messages WHERE id = :id"),
                {"id": sem_payload},
            )
            restantes = (await sessao.execute(text("SELECT id FROM messages"))).scalars().all()
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    assert texto_com_payload == "mensagem com payload", (
        "o downgrade tem de decifrar text_body de volta para texto claro"
    )
    assert tipo_aninhado == "text", (
        "raw_payload tem de voltar jsonb consultavel, com a estrutura interna intacta"
    )
    assert raw_payload_vazio == "{}", "raw_payload NULL tem de virar '{}' antes do NOT NULL"
    assert com_payload in restantes and sem_payload in restantes, (
        "as linhas INBOUND sobrevivem ao downgrade"
    )
    assert de_saida not in restantes, "a linha OUTBOUND nao cabe no esquema anterior e e apagada"


async def test_a_0012_desce_e_sobe_de_novo() -> None:
    """A trilha some no downgrade e a trigger volta no upgrade.

    A trigger e a funcao sao criadas com `op.execute` e nao pelo autogenerate,
    entao nada garante que o downgrade as derrube -- uma funcao orfa faria o
    upgrade seguinte reprovar com "function already exists".
    """
    await dispose_engine()
    alembic("downgrade", "0011")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(text("SELECT to_regclass('public.lead_score_audit')")) is None
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(text("SELECT to_regclass('public.lead_score_audit')")) is not None
        )
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM pg_trigger WHERE tgname = 'lead_score_audit_imutavel'")
            )
            == 1
        )


async def test_a_0013_desce_e_sobe_de_novo() -> None:
    """A coluna some no downgrade e volta no upgrade, sem backfill."""
    await dispose_engine()
    alembic("downgrade", "0012")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'lead_qualification' "
                        "AND column_name = 'campos_recusados'"
                    )
                )
                == 0
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'lead_qualification' "
                    "AND column_name = 'campos_recusados'"
                )
            )
            == 1
        )


async def test_a_0035_desce_e_sobe_de_novo() -> None:
    """A trilha de intencao some no downgrade e a trigger volta no upgrade.

    Mesma forma e mesma razao do teste da 0012 logo acima: a funcao e a trigger
    nascem de `op.execute`, e nao do autogenerate, entao nada garante que o
    downgrade as derrube. Uma funcao orfa faz o upgrade SEGUINTE reprovar com
    "function already exists" -- num banco de desenvolvimento que ja subiu e
    desceu esta revisao uma vez, e nao no CI, que sempre parte do zero.
    """
    await dispose_engine()
    alembic("downgrade", "0034")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(text("SELECT to_regclass('public.conversation_intent_audit')"))
                is None
            )
            # A funcao tambem, e ela e o ponto: a tabela sumiria mesmo sem o
            # `DROP FUNCTION`, porque `drop_table` leva a trigger junto.
            assert (
                await sessao.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc "
                        "WHERE proname = 'conversation_intent_audit_recusa_update'"
                    )
                )
                == 0
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(text("SELECT to_regclass('public.conversation_intent_audit')"))
            is not None
        )
        assert (
            await sessao.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'conversation_intent_audit_imutavel'"
                )
            )
            == 1
        )


_CONSTRAINTS_DA_0037 = (
    "ck_messages_role",
    "ck_messages_direction",
    "ck_messages_content_type",
    "ck_messages_status",
)

_LISTAR_CONSTRAINTS = text(
    "SELECT coalesce(array_agg(conname), '{}') FROM pg_constraint"
    " WHERE conname = ANY(:nomes) AND contype = 'c' AND conrelid = 'messages'::regclass"
)


async def test_a_0037_desce_e_sobe_de_novo() -> None:
    """As quatro constraints somem no downgrade e voltam no upgrade.

    Mesma razao do teste da 0035 acima: elas nascem de `op.create_check_
    constraint`, nao do autogenerate, entao nada garante que o downgrade as
    derrube. Uma constraint orfa faz o upgrade SEGUINTE reprovar com "already
    exists" -- num banco de desenvolvimento que ja subiu e desceu esta
    revisao, e nao no CI, que sempre parte do zero.

    Compara conjuntos (`array_agg`), nao `count(*)`: se um numero nao fechar,
    a assercao ja diz qual nome sumiu, em vez de mandar quem le para o banco
    descobrir.
    """
    await dispose_engine()
    alembic("downgrade", "0036")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                set(await sessao.scalar(_LISTAR_CONSTRAINTS, {"nomes": list(_CONSTRAINTS_DA_0037)}))
                == set()
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert set(
            await sessao.scalar(_LISTAR_CONSTRAINTS, {"nomes": list(_CONSTRAINTS_DA_0037)})
        ) == set(_CONSTRAINTS_DA_0037)


async def test_a_0044_desce_e_sobe_de_novo() -> None:
    """A tabela some no downgrade, mas a `btree_gist` fica -- de proposito.

    Mesma razao das duas acima: `agendamentos` e a exclusao nascem de
    `op.execute`/`op.create_table`, nao do autogenerate, entao nada garante o
    downgrade sozinho. A extensao e o caso diferente: como o `vector` da 0017,
    o downgrade nao a remove porque outra coisa pode ja depender dela, entao
    a asserta e que ela CONTINUA la, nao que sumiu.
    """
    await dispose_engine()
    alembic("downgrade", "0043")
    try:
        async with get_sessionmaker()() as sessao:
            assert await sessao.scalar(text("SELECT to_regclass('public.agendamentos')")) is None
            assert (
                await sessao.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'"))
                == 1
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert await sessao.scalar(text("SELECT to_regclass('public.agendamentos')")) is not None
        # No molde de `_LISTAR_CONSTRAINTS` acima, mas para uma exclusion
        # constraint (`contype = 'x'`): confirma que o upgrade recria
        # `ex_agendamentos_sem_sobreposicao`, e nao so a tabela.
        assert (
            await sessao.scalar(
                text(
                    "SELECT 1 FROM pg_constraint WHERE conname = 'ex_agendamentos_sem_sobreposicao'"
                    " AND contype = 'x' AND conrelid = 'agendamentos'::regclass"
                )
            )
            == 1
        )


async def test_a_0048_desce_e_sobe_de_novo() -> None:
    """A tabela e as duas funcoes somem no downgrade e voltam no upgrade.

    Mesma razao da 0012: triggers e funcoes nascem de `op.execute`, entao nada
    garante que o downgrade as derrube -- uma funcao orfa faria o upgrade
    seguinte reprovar com "function already exists".
    """
    await dispose_engine()
    alembic("downgrade", "0047")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(text("SELECT to_regclass('public.eventos_auditoria')")) is None
            )
            assert (
                await sessao.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE proname IN "
                        "('eventos_auditoria_carimba', 'eventos_auditoria_protege')"
                    )
                )
                == 0
            )
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                    "('eventos_auditoria_carimbo', 'eventos_auditoria_imutavel')"
                )
            )
            == 2
        )
