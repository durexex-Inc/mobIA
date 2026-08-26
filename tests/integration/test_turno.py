import logging
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text as sql

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.domain.agente.turno import KIND_DA_RESPOSTA, executar_turno
from mobia.domain.context.montagem import ContextoIrreducivel
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRetentavel
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def test_turno_classifica_entrega_e_grava(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca == Decimal("0.91")

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 1, "a fala do agente entra na linha do tempo"


async def test_a_fala_e_gravada_depois_da_entrega(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Se a entrega falha, nao pode sobrar fala fantasma no historico.

    Texto que o lead nunca viu entraria no contexto do proximo turno e depois
    seria dobrado permanentemente no resumo da TEC-127: o agente passaria a
    acreditar que disse algo que nao disse.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 0, "nada entregue, nada gravado"


async def test_fora_da_janela_termina_o_turno_sem_erro(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """Expirar nao e falhar: retentar nunca vai entregar."""
    outbound = outbound_fake(EnvioForaDaJanela("131047"))

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "expirado"
    assert "outbound.fora_da_janela" in caplog.text


async def test_contexto_irreducivel_nao_derruba_o_worker(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    rodar_turno,
    monkeypatch,
    caplog,
) -> None:
    """Mensagem grande demais faz o lead ser ignorado -- em silencio para ele,
    mas nunca em silencio no log."""
    from mobia.domain.agente import turno as turno_mod

    async def _estoura(*_args: Any, **_kwargs: Any) -> Any:
        raise ContextoIrreducivel("tokens=99999, teto=11600")

    monkeypatch.setattr(turno_mod, "montar_contexto", _estoura)
    classificador = classificador_fake()

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
        )

    assert resultado == "sem_resposta"
    assert classificador.chamadas == 0, "nem chega a pagar a chamada ao modelo"
    assert "turno.contexto_irreducivel" in caplog.text


async def test_a_intencao_e_gravada_mesmo_se_a_entrega_falhar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A classificacao aconteceu de verdade -- registra-la e honesto.

    Ela e sobre a mensagem do lead, nao sobre a resposta que nao saiu.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session,
            classificador_fake(Intencao.ALUGUEL),
            outbound,
            resumidor_fake(),
            contador_fake(),
        )

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.ALUGUEL


async def test_reentrega_suprimida_nao_grava_fala_fantasma(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, caplog
) -> None:
    """`send()` devolve False, sem levantar, quando a guarda (Task 3) suprime
    uma reentrega -- ja existe reserva em outbound_dispatches para este
    (message_id, kind) de uma tentativa anterior. O texto desta chamada nova
    ao classificador pode nao ser o que o lead recebeu (ou nada pode ter saido
    ainda). Gravar aqui e a mesma fala fantasma que a ordem grava-depois-de-
    entregar existe para evitar, so que entrando pela porta do retorno em vez
    de uma excecao.
    """
    from conftest import _entrada_do_lead

    linha = await _entrada_do_lead(session)
    # Simula a reserva que uma tentativa anterior ja commitou: a UNIQUE
    # (message_id, kind) faz a proxima reserva colidir sem tocar em `_deliver`.
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=linha.id, kind=KIND_DA_RESPOSTA))
    await session.commit()

    outbound = outbound_fake()

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
        )

    assert resultado == "reentrega_suprimida"
    assert outbound.entregues == [], "a guarda nunca chega a chamar _deliver"

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 0, "sem confirmacao do que foi entregue, nao ha texto confiavel pra gravar"

    # Nivel `error`, nao `warning`: a linha fecha em PROCESSED -- terminal, o
    # sweeper nunca reenfileira -- e o lead pode nao ter recebido nada em
    # nenhuma tentativa. A visibilidade deste desfecho vem so do nivel do log,
    # como no 4xx, e e `error` que o alerta observa.
    eventos = [
        registro
        for registro in caplog.records
        if "turno.reentrega_suprimida" in registro.getMessage()
    ]
    assert eventos, "o desfecho tem de aparecer no log"
    assert all(registro.levelno == logging.ERROR for registro in eventos)
