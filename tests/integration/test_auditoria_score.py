"""A trilha de recalculos de score: tabela, imutabilidade e o gancho no turno.

TEC-152.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.repositorio import contar_mensagens_do_lead, registrar_recalculo
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def linha(**ajustes: object) -> LeadScoreAudit:
    """Um registro valido, com os cinco fatores somando o total."""
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "total_anterior": None,
        "total_novo": 51,
        "completude": 20,
        "urgencia": 15,
        "catalogo": 0,
        "engajamento": 10,
        "capacidade": 6,
        "causas": ["PRIMEIRO_CALCULO"],
    }
    return LeadScoreAudit(**{**base, **ajustes})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    session.add(linha())
    await session.commit()

    gravado = (await session.scalars(select(LeadScoreAudit))).one()
    assert gravado.total_novo == 51
    assert gravado.total_anterior is None
    assert gravado.causas == ["PRIMEIRO_CALCULO"]
    assert gravado.autor is None
    assert gravado.created_at is not None


async def test_o_check_recusa_um_total_que_nao_soma(session) -> None:
    """O total e denormalizado de proposito -- e por ele que se ordena --, e a
    restricao e o que impede a denormalizacao de mentir."""
    session.add(linha(total_novo=99))

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_update_e_recusado_pela_trigger(session) -> None:
    """Cenario 3 da card: "quando se tenta altera-lo, a operacao e recusada"."""
    session.add(linha())
    await session.commit()

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE lead_score_audit SET total_novo = 99"))

    # A transacao fica abortada depois da excecao do Postgres; sem isto o
    # teardown da fixture reclama em vez de fechar limpo.
    await session.rollback()


async def test_delete_continua_livre(session) -> None:
    """Imutavel e "nao se altera o que foi registrado". A RNF-18 pede retencao
    de 12 meses, ou seja, pede que apagar seja possivel."""
    session.add(linha())
    await session.commit()

    await session.execute(text("DELETE FROM lead_score_audit"))
    await session.commit()

    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def _mensagem(
    session,
    *,
    direction: MessageDirection = MessageDirection.INBOUND,
    bloqueada: bool = False,
) -> None:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD if direction is MessageDirection.INBOUND else MessageRole.AGENTE,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_a_contagem_ignora_a_fala_do_agente(session) -> None:
    """Fala do agente nao e engajamento do lead, e contar as duas direcoes
    quase dobra o numero e empurra MORNO para QUENTE de graca."""
    await _mensagem(session)
    await _mensagem(session, direction=MessageDirection.OUTBOUND)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_ignora_a_fala_bloqueada(session) -> None:
    """Um turno que o resto do produto trata como nao-dito nao pode virar ponto
    aqui: `literais_apos` ja filtra `bloqueada_em IS NULL` desde a TEC-236."""
    await _mensagem(session)
    await _mensagem(session, bloqueada=True)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_de_um_lead_sem_mensagem_e_zero(session) -> None:
    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key="ninguem") == 0


async def _qualificacao(session) -> None:
    """Os quatro obrigatorios preenchidos."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.ATE_3_MESES.value,
        )
    )
    await session.commit()


async def test_o_primeiro_recalculo_grava_com_anterior_nulo(session) -> None:
    """Quatro obrigatorios (20), ATE_3_MESES (15), uma mensagem (10), sem forma
    de pagamento (6) = 51."""
    await _qualificacao(session)
    await _mensagem(session)

    gravada = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert gravada is not None
    assert gravada.total_anterior is None
    assert gravada.total_novo == 51
    assert (gravada.completude, gravada.urgencia, gravada.catalogo) == (20, 15, 0)
    assert (gravada.engajamento, gravada.capacidade) == (10, 6)
    assert gravada.causas == ["PRIMEIRO_CALCULO"]


async def test_o_recalculo_que_nao_move_nada_nao_grava(session) -> None:
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA) is None
    await session.commit()

    assert len((await session.scalars(select(LeadScoreAudit))).all()) == 1


async def test_informar_a_vista_grava_o_delta_da_capacidade(session) -> None:
    """O cenario 1 da card, no equivalente alcancavel: 51 -> 60.

    A card diz 48 -> 63, um delta de 15. A vista move `capacidade` de 6 para
    15 -- delta de 9 --, e na escala da TEC-150 nenhum dos dois numeros e
    alcancavel hoje: 63 nao existe com `imoveis_compativeis=0`, e 48 so existe
    para quem JA paga a vista. Ver a secao correspondente do desenho.
    """
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    estado = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert estado is not None
    estado.forma_pagamento = FormaPagamento.A_VISTA.value
    await session.commit()

    gravada = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert gravada is not None
    assert (gravada.total_anterior, gravada.total_novo) == (51, 60)
    assert gravada.causas == ["FORMA_DE_PAGAMENTO"]


async def test_sem_linha_de_qualificacao_nao_ha_o_que_auditar(session) -> None:
    """Sem linha em `LeadQualification`, `registrar_recalculo` devolve `None`
    antes mesmo de calcular -- o `SELECT ... FOR UPDATE` nao acha a linha, e o
    `if estado is None: return None` sai dali. Nao ha score zerado para
    auditar: a ausencia de sujeito nao e uma nota igual a zero."""
    await _mensagem(session)

    assert await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA) is None
    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def test_populate_existing_rele_o_estado_por_baixo_da_instancia_em_maos(session) -> None:
    """Reproduz o perigo que `.execution_options(populate_existing=True)`
    existe para evitar, e nao so o afirma.

    `infra/db.py` monta a sessionmaker com `expire_on_commit=False`, entao
    nada expira esta linha por conta propria: uma vez carregada, a sessao
    devolve a MESMA instancia Python de novo para qualquer leitura futura na
    mesma sessao, com os atributos que ela tinha quando foi carregada -- a
    menos que algo peca explicitamente para os atualizar. E isso que
    `populate_existing` pede.

    O UPDATE abaixo passa por `text()`, por baixo do ORM de proposito: e o
    unico jeito de o banco mudar sem que o objeto Python que o identity map
    guarda mude junto -- exatamente a divergencia entre "o que a sessao acha
    que a linha diz" e "o que a linha diz" que a releitura de
    `registrar_recalculo` existe para fechar.
    """
    await _qualificacao(session)
    await _mensagem(session)

    # Carrega a linha no identity map desta sessao. E esta copia que ficaria
    # obsoleta sem `populate_existing`.
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.forma_pagamento is None

    # Muda o banco por baixo da instancia carregada, sem passar pelo ORM.
    await session.execute(
        text(
            "UPDATE lead_qualification SET forma_pagamento = 'A_VISTA' "
            "WHERE channel = :channel AND conversation_key = :conversa"
        ),
        {"channel": CANAL, "conversa": CONVERSA},
    )
    # A instancia em maos continua mentindo -- e o estado que a releitura tem
    # de corrigir.
    assert carregada.forma_pagamento is None

    gravada = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert gravada is not None
    # 60 e capacidade 15 (a vista), e nao 51 e capacidade 6 (sem forma de
    # pagamento): sem `populate_existing`, `registrar_recalculo` calcularia
    # sobre a instancia velha do identity map, e este teste ficaria vermelho.
    assert gravada.total_novo == 60
    assert gravada.capacidade == 15
