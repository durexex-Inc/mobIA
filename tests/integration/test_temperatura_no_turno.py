"""A temperatura persistida, os dois CHECK, e a borda que notifica.

TEC-151. Integracao: os CHECK vivem no banco, e o forcamento so significa
algo se sobreviver a uma transacao.
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.gatilhos import MOTIVO_PROPOSTA, MOTIVO_VISITA
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque a Task 6 roda `rodar_turno`, que semeia a fala nessa conversa -- os
# testes de turno leem a linha por esta chave. `test_turno.py` redefine os dois
# localmente do mesmo jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(**campos) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste sobrescrever."""
    base = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    return LeadQualification(**{**base, **campos})


async def test_as_tres_colunas_nascem_nulas(session) -> None:
    """`NULL` em `temperatura` significa "nunca recalculada", e e contra esse
    `NULL` que a borda da notificacao compara. Nao ha backfill: um backfill
    para FRIO apagaria a distincao entre "nunca calculei" e "ja era FRIO"."""
    session.add(_linha())
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura is None
    assert carregada.temperatura_forcada_em is None
    assert carregada.temperatura_forcada_motivos is None


async def test_o_check_recusa_forcamento_que_nao_seja_quente(session) -> None:
    """Forcado implica QUENTE. Sem o CHECK, uma linha pode afirmar as duas
    coisas contrarias e nada reclama."""
    session.add(
        _linha(
            temperatura="MORNO",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=["VISITA"],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_o_check_recusa_forcamento_sem_motivo(session) -> None:
    """Molde do `CHECK (cardinality(causas) > 0)` da 0012, e pela mesma razao:
    uma linha que afirma que o lead foi forcado a QUENTE sem nomear o que o
    forcou e a mesma forma de mentira. `NOT NULL` cobriria metade -- o array
    vazio passaria."""
    session.add(
        _linha(
            temperatura="QUENTE",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=[],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_temperatura_sem_forcamento_e_livre(session) -> None:
    """Os dois CHECK sao condicionais a `temperatura_forcada_em`: uma
    temperatura derivada, sem forcamento, aceita qualquer das tres."""
    session.add(_linha(temperatura="FRIO"))
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "FRIO"
    assert carregada.temperatura_forcada_em is None


async def _mensagem(session) -> None:
    """Uma fala de ENTRADA nao bloqueada, que e o que o engajamento conta.

    Copia exata do helper de mesmo nome em `test_auditoria_score.py`, menos os
    parametros que este arquivo nao usa. As quatro colunas de identificacao do
    provedor (`provider_message_id`, `sender_external_id`,
    `recipient_external_id`, `raw_payload`) nao sao decorativas -- a tabela as
    exige, e omiti-las quebra o INSERT.

    `MessageContentType.TEXTO`, com O: o enum e em portugues.
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
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()


async def test_o_primeiro_recalculo_grava_a_temperatura_derivada(session) -> None:
    """Quatro obrigatorios (20), IMEDIATA (25), uma mensagem (10), sem forma de
    pagamento (6) = 61, faixa MORNO. `anterior` e None porque a coluna era."""
    session.add(_linha())
    await session.commit()
    await _mensagem(session)

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.total == 61
    assert obtido.anterior is None
    assert obtido.temperatura is Temperatura.MORNO

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "MORNO"
    assert carregada.temperatura_forcada_em is None


async def test_o_gatilho_forca_quente_e_nao_toca_o_score(session) -> None:
    """O cenario 2 da card. O score continua sendo o que era."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()
    await _mensagem(session)

    obtido = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    assert obtido is not None
    assert obtido.temperatura is Temperatura.QUENTE
    assert obtido.total < 70

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
    assert carregada.temperatura_forcada_em is not None
    assert carregada.temperatura_forcada_motivos == [MOTIVO_VISITA]


async def test_o_forcamento_sobrevive_a_um_recalculo_sem_gatilho(session) -> None:
    """O cenario 3 da card, e o teste que morre se `forcada` deixar de ler a
    coluna: o turno que rebaixaria e justamente um turno SEM gatilho."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.temperatura is Temperatura.QUENTE
    assert obtido.anterior is Temperatura.QUENTE


async def test_o_carimbo_e_o_do_primeiro_forcamento(session) -> None:
    """`COALESCE` e nao sobrescrita: "permanece ate intervencao humana" torna
    interessante QUANDO esquentou, e ha quanto tempo ninguem interveio."""
    session.add(_linha())
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()
    primeira = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert primeira is not None
    carimbo = primeira.temperatura_forcada_em

    await _mensagem(session)
    await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_PROPOSTA,)
    )
    await session.commit()

    session.expire_all()
    segunda = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert segunda is not None
    assert segunda.temperatura_forcada_em == carimbo
    assert segunda.temperatura_forcada_motivos == [MOTIVO_VISITA, MOTIVO_PROPOSTA]


async def test_o_teto_morno_vale_no_banco(session) -> None:
    """A linha 2 da tabela da D6: `intencao = None`, resto completo, IMEDIATA,
    a vista, engajamento -- 70 com `esta_qualificado` False. Sem o teto ele
    gravaria QUENTE e faria o telefone do corretor tocar."""
    session.add(_linha(intencao=None, forma_pagamento=FormaPagamento.A_VISTA.value))
    await session.commit()
    for _ in range(6):
        await _mensagem(session)

    obtido = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert obtido is not None
    assert obtido.total >= 70
    assert obtido.temperatura is Temperatura.MORNO


async def test_o_turno_sem_mudanca_de_score_ainda_resolve_a_temperatura(session) -> None:
    """A guarda contra a regressao que a Task 5 inverte.

    Se alguem restaurar o `return None` antecipado do `if not causas`, este
    teste morre: e um turno em que nenhum dos cinco fatores se move e o
    gatilho e a unica coisa que aconteceu.
    """
    session.add(_linha())
    await session.commit()
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    obtido = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA, gatilhos=(MOTIVO_VISITA,)
    )
    await session.commit()

    assert obtido is not None
    assert obtido.trilha is None
    assert obtido.temperatura is Temperatura.QUENTE

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"


async def test_o_pedido_de_visita_no_turno_forca_quente_e_emite(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """A card ponta a ponta: o lead pede visita, a temperatura vira QUENTE
    apesar do score baixo, e o evento da RN-06.5 sai uma vez."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    with caplog.at_level(logging.INFO):
        resultado = await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            texto="quero agendar visita",
        )

    assert resultado == "respondido"

    # `expire_all` porque o turno gravou por OUTRA sessao (`get_sessionmaker()`
    # dentro de `executar_turno`), e o identity map desta ainda tem a instancia
    # que este teste adicionou -- sem isto, `get` devolve o objeto velho e o
    # teste passa ou falha por acidente.
    session.expire_all()
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
    assert carregada.temperatura_forcada_motivos == [MOTIVO_VISITA]
    assert carregada.temperatura_forcada_em is not None
    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 1


async def test_a_borda_nao_reemite_no_turno_seguinte(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """O evento e da travessia, nao do estado: um lead que continua QUENTE nao
    reemite. E a razao pela qual `Recalculo.anterior` existe -- sem ele a
    RN-06.5 viraria um ping por mensagem."""
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    caplog.clear()

    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            texto="quero agendar visita de novo",
        )

    # Ancora o proprio precondicionamento: sem isto, um forcamento
    # inteiramente quebrado (turno 1 deixa a linha em FRIO) tambem passaria
    # aqui -- zero emissoes nos dois turnos, e o teste ficaria verde
    # dependendo do vizinho para pegar a regressao, nao de si mesmo.
    session.expire_all()
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "QUENTE"
    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 0


async def test_a_fala_bloqueada_pela_moderacao_nao_forca_quente(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """Nao ha guarda para isto no codigo, e o teste existe justamente por isso.

    `executar_turno` retorna por `_entregar_texto_fixo` quando a moderacao
    bloqueia a entrada, antes do bloco transacional -- entao a fala bloqueada
    nunca chega ao gancho, e a propriedade sai de graca. O teste a fixa para
    que uma reordenacao futura nao a perca em silencio.

    E coerente com o contrato de `mensagens_do_lead`, que exclui
    `bloqueada_em IS NOT NULL` da contagem de engajamento pela mesma razao: um
    turno que o resto do produto trata como nao-dito nao pode virar sinal aqui.
    """
    session.add(_linha(urgencia=None, faixa_preco_max_centavos=None))
    await session.commit()

    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            moderador_fake(bloqueia_entrada=True),
            texto="quero agendar visita",
        )

    session.expire_all()
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura is None, "a fala bloqueada nao chega ao gancho"
    assert carregada.temperatura_forcada_em is None
    assert sum(1 for r in caplog.records if "lead.esquentou" in r.getMessage()) == 0
