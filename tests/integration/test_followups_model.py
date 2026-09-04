"""A trilha de follow-ups, e as duas invariantes que o banco garante.

TEC-183. Integracao: o UNIQUE e o CHECK vivem no banco.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA
from mobia.domain.followup.models import FollowUp
from mobia.domain.followup.repositorio import (
    candidatos_a_followup,
    registrar_followup,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511955554444"
ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _linha(**campos) -> FollowUp:
    base = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "tentativa_numero": 1,
        "temperatura": "QUENTE",
        "ancora_em": ANCORA,
        "devido_em": ANCORA + timedelta(hours=2),
    }
    return FollowUp(**{**base, **campos})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    linha = _linha()
    session.add(linha)
    await session.commit()

    gravada = await session.get(FollowUp, linha.id)
    assert gravada is not None
    assert gravada.tentativa_numero == 1
    assert gravada.ancora_em == ANCORA
    # `server_default=clock_timestamp()`: o banco carimba, nao o cliente.
    assert gravada.created_at is not None


async def test_o_unique_recusa_a_mesma_tentativa_sob_a_mesma_ancora(session) -> None:
    """A defesa contra duas varredura concorrentes.

    Nao da para usar `FOR UPDATE SKIP LOCKED` sobre a agregacao que produz os
    candidatos, entao a exclusao mora aqui -- mesmo espirito dos CHECK da 0014
    e da 0012: a invariante no banco, e nao na esperanca de que so um worker
    rode.
    """
    session.add(_linha())
    await session.commit()

    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_mesma_tentativa_sob_outra_ancora_e_permitida(session) -> None:
    """O reinicio da RN-13.4: o lead respondeu, a ancora mudou, e a tentativa 1
    volta a ser legitima."""
    session.add(_linha())
    await session.commit()

    session.add(_linha(ancora_em=ANCORA + timedelta(days=1)))
    await session.commit()

    todas = (await session.scalars(select(FollowUp))).all()
    assert len(todas) == 2


async def test_o_check_recusa_tentativa_zero(session) -> None:
    """1-based e contrato, nao convencao: `ja_disparada = 0` significa "nenhuma
    disparou", e uma linha numero 0 tornaria os dois indistinguiveis."""
    session.add(_linha(tentativa_numero=0))
    with pytest.raises(IntegrityError):
        await session.commit()


AGORA = ANCORA + timedelta(days=30)


async def _qualificacao(session, *, temperatura: str | None = "QUENTE") -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    await session.commit()


async def _fala_do_lead(
    session,
    *,
    quando,
    bloqueada: bool = False,
    direcao: MessageDirection = MessageDirection.INBOUND,
) -> None:
    """Uma fala. Por padrao de ENTRADA; `direcao` permite gravar a resposta do
    agente para os testes que provam que ela nao move a ancora.

    `bloqueada` marca o que a moderacao recusou, e so faz sentido com a
    entrada -- nenhum teste passa as duas.

    Copia do helper de `test_auditoria_score.py`, com `created_at` explicito
    porque a ancora deste desenho e exatamente esse valor. As quatro colunas de
    identificacao do provedor nao sao decorativas: a tabela as exige.
    """
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD if direcao is MessageDirection.INBOUND else MessageRole.AGENTE,
            direction=direcao,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=quando,
            bloqueada_em=quando if bloqueada else None,
        )
    )
    await session.commit()


async def test_o_candidato_traz_a_ancora_e_zero_disparos(session) -> None:
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert len(candidatos) == 1
    assert candidatos[0].conversation_key == CONVERSA
    assert candidatos[0].temperatura is Temperatura.QUENTE
    assert candidatos[0].ancora_em == ANCORA
    assert candidatos[0].ja_disparada == 0


async def test_lead_sem_temperatura_nao_e_candidato(session) -> None:
    """A D3: `NULL` e "linha anterior a TEC-151" ou "lead que nunca disse nada
    qualificavel". A RN-13.1 so prescreve cadencia para as tres temperaturas."""
    await _qualificacao(session, temperatura=None)
    await _fala_do_lead(session, quando=ANCORA)

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_lead_que_falou_ha_pouco_nao_e_candidato(session) -> None:
    """O corte por `INTERVALO_MINIMO`: nada abaixo de 2h pode estar devido em
    temperatura nenhuma."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=AGORA - timedelta(hours=1))

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_lead_sem_linha_de_qualificacao_nao_e_candidato(session) -> None:
    """Sem linha nao ha temperatura, e sem temperatura nao ha regua."""
    await _fala_do_lead(session, quando=ANCORA)

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_a_ancora_ignora_a_fala_bloqueada_pela_moderacao(session) -> None:
    """Mesma definicao de fala do lead que `contar_mensagens_do_lead` fixou:
    `direction = INBOUND` e `bloqueada_em IS NULL`. Um turno que o resto do
    produto trata como nao-dito nao pode adiar o follow-up."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    await _fala_do_lead(session, quando=ANCORA + timedelta(days=1), bloqueada=True)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == ANCORA


async def test_a_resposta_do_agente_nao_move_a_ancora(session) -> None:
    """A outra metade da definicao de `contar_mensagens_do_lead`:
    `direction = 'INBOUND'`. A ancora e a ULTIMA FALA DO LEAD, e nao a ultima
    mensagem da conversa -- uma resposta do agente e quase sempre mais recente
    que a fala do lead que a gerou, e se ela movesse a ancora a cadencia
    nunca fecharia num lead que so o agente atendeu."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    await _fala_do_lead(
        session, quando=ANCORA + timedelta(hours=1), direcao=MessageDirection.OUTBOUND
    )

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == ANCORA


async def test_ja_disparada_e_o_maximo_sob_a_ancora(session) -> None:
    """MAX e nao COUNT -- ver a docstring de `tentativa_devida`."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=3))
    await session.commit()

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ja_disparada == 3


async def test_a_resposta_do_lead_zera_a_regua(session) -> None:
    """O reinicio da RN-13.4, e o teste que morre se `ja_disparada` olhar a
    vida inteira em vez de por ancora."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=4))
    await session.commit()

    nova_ancora = ANCORA + timedelta(days=5)
    await _fala_do_lead(session, quando=nova_ancora)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == nova_ancora
    assert candidatos[0].ja_disparada == 0


async def test_lead_exaurido_nao_e_candidato_ate_falar_de_novo(session) -> None:
    """Um lead com o teto de tentativas da PROPRIA temperatura sob a ancora
    atual nao pode mais estar devido naquela temperatura. Sem o excluir da
    consulta, ele travaria no topo da fila para sempre -- candidatura nao olha
    quantos disparos ja houve, so a idade da ancora, e a dele e a mais antiga
    do lote. So uma fala nova (ancora nova) o traz de volta."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=len(CADENCIA[Temperatura.QUENTE])))
    await session.commit()

    assert await candidatos_a_followup(session, agora=AGORA) == []

    nova_ancora = ANCORA + timedelta(days=1)
    await _fala_do_lead(session, quando=nova_ancora)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == nova_ancora
    assert candidatos[0].ja_disparada == 0


async def test_lead_esgotado_no_morno_nao_bloqueia_a_fila_para_quem_esta_devido(session) -> None:
    """A regressao do bug critico: o corte de esgotamento tinha de ser POR
    TEMPERATURA, nao um teto global.

    Um MORNO com as 3 tentativas da propria tabela ja disparadas nunca mais
    fica devido -- nada mais muda a candidatura dele, e a ancora dele so fica
    mais velha. Ordenado por `ancora ASC`, ele ocupa o topo da fila para
    sempre. Com um teto GLOBAL (o antigo `MAX_TENTATIVAS`, o maior das tres
    tabelas -- 4, do QUENTE), esse lead com 3 disparos seguia candidato e
    continuava no topo; um lote de leads assim maior que `limite` fazia a
    varredura nunca mais alcancar quem estava genuinamente devido. Usando um
    `limite` de 2, dois MORNO esgotados bastam para saturar a pagina -- e o
    lead QUENTE, devido de verdade e com a ancora mais recente, tem de
    aparecer mesmo assim."""
    for numero in range(2):
        canal_exaurido = f"exaurido-{numero}"
        session.add(
            LeadQualification(
                channel=canal_exaurido,
                conversation_key=canal_exaurido,
                intencao=Intencao.COMPRA.value,
                faixa_preco_max_centavos=50_000_000,
                regiao="vila mariana",
                urgencia=Urgencia.IMEDIATA.value,
                temperatura=Temperatura.MORNO.value,
            )
        )
        await session.commit()
        identificador = uuid.uuid4()
        session.add(
            Message(
                id=identificador,
                channel=canal_exaurido,
                provider_message_id=f"wamid.{identificador.hex[:10]}",
                sender_external_id=canal_exaurido,
                recipient_external_id="222222222",
                conversation_key=canal_exaurido,
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("oi", aad_de(identificador, "text_body")),
                raw_payload=None,
                status=MessageStatus.PROCESSED,
                created_at=ANCORA,
            )
        )
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=canal_exaurido,
                conversation_key=canal_exaurido,
                tentativa_numero=len(CADENCIA[Temperatura.MORNO]),
                temperatura=Temperatura.MORNO.value,
                ancora_em=ANCORA,
                devido_em=ANCORA + timedelta(days=1),
            )
        )
        await session.commit()

    # O devido de verdade: QUENTE, sem disparo, ancora mais recente que os
    # dois exauridos -- entao, sem o corte por temperatura, ele fica atras
    # deles na fila e um `limite` de 2 nunca o alcanca.
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA + timedelta(hours=1))

    candidatos = await candidatos_a_followup(session, agora=AGORA, limite=2)

    assert [c.conversation_key for c in candidatos] == [CONVERSA]


async def test_registrar_devolve_none_na_corrida(session) -> None:
    """A segunda varredura nao levanta: o `ON CONFLICT DO NOTHING` absorve, e o
    `None` diz ao chamador que outra passagem chegou primeiro."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    candidato = (await candidatos_a_followup(session, agora=AGORA))[0]

    primeira = await registrar_followup(
        session, candidato=candidato, tentativa=1, devido_em=ANCORA + timedelta(hours=2)
    )
    await session.commit()
    segunda = await registrar_followup(
        session, candidato=candidato, tentativa=1, devido_em=ANCORA + timedelta(hours=2)
    )
    await session.commit()

    assert primeira is not None
    assert segunda is None
