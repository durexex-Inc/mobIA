"""A escrita do handoff, com a deduplicacao que a RN-16.1 exige."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import case, func, literal, literal_column, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade, Status

log = structlog.get_logger(__name__)


async def registrar_handoff(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    gatilho: Gatilho,
) -> bool:
    """Cria o handoff da conversa, ou acumula o gatilho no que ja esta aberto.

    Devolve `True` quando criou linha nova e `False` quando atualizou uma
    aberta. **Nao commita** -- o commit e de quem chama, como em
    `registrar_recalculo`. E isso que poe o handoff na MESMA transacao do
    recalculo no gatilho QUENTE: ou o lead vira QUENTE e tem handoff, ou nem
    uma coisa nem outra. O estado intermediario -- lead quente, ninguem
    avisado -- e exatamente o que a card existe para impedir.

    **Um statement, e nao um SELECT seguido de INSERT.** A corrida e prevista:
    `turno.py` declara que `lead.esquentou` reemite para o MESMO lead desde a
    TEC-148, e a suite roda com oito workers. Quem arbitra e o indice parcial
    `uq_handoffs_conversa_pendente`, nao a ordem do codigo.
    """
    agora = datetime.now(UTC)
    prioridade = PRIORIDADE_DE[gatilho]

    statement = pg_insert(Handoff).values(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        gatilho=gatilho.value,
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=prioridade.value,
        status=Status.PENDENTE.value,
        gatilhos_adicionais=[],
        criado_em=agora,
        atualizado_em=agora,
    )

    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            index_where=text("status = 'PENDENTE'"),
            set_={
                "gatilhos_adicionais": func.array_append(
                    Handoff.gatilhos_adicionais, literal(gatilho.value)
                ),
                # A escalada de `vocabulario.escalada`, em SQL: o Python nao ve
                # a linha existente neste caminho, e ler antes para decidir
                # devolveria a corrida que este statement existe para evitar.
                "prioridade": case(
                    (
                        literal(prioridade.value) == Prioridade.ALTA.value,
                        literal(Prioridade.ALTA.value),
                    ),
                    else_=Handoff.prioridade,
                ),
                "atualizado_em": agora,
            },
        ).returning(
            # xmax e o sinal nativo do Postgres para distinguir INSERT de
            # UPDATE num ON CONFLICT: vale 0 na linha recem-inserida e
            # diferente de zero na que foi atualizada. NAO comparar carimbos
            # de tempo aqui -- `agora` e calculado em Python antes do
            # statement, e duas escritas concorrentes para a mesma conversa
            # podem calcular o MESMO valor. Nesse caso a chamada que fez
            # UPDATE bateria com o `criado_em` que a vencedora gravou e
            # devolveria True por coincidencia de relogio, nao por sinal do
            # banco -- exatamente a corrida que este statement existe para
            # arbitrar, so que agora no booleano de retorno em vez de na
            # linha.
            (literal_column("xmax") == 0).label("inseriu")
        )
    )

    criou = resultado.scalar_one()
    log.info(
        "handoff.criado" if criou else "handoff.gatilho_adicional",
        channel=channel,
        gatilho=gatilho.value,
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=prioridade.value,
    )
    return criou
