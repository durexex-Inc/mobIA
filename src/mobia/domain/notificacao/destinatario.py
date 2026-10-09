"""Quem recebe a notificacao do handoff. TEC-177, D3.

A RN-16.2 diz "o corretor designado". A alocacao da TEC-166 escolhe
corretor para o agendamento, nao para o handoff. Quando esta cascata nasceu,
`handoffs.corretor_id` nao tinha escritor -- a chave estrangeira existia desde
a TEC-196, o escritor nao. Hoje ele tem dois: a propria notificacao grava o
destinatario escolhido aqui (TEC-192), e a atribuicao do admin
(`domain/handoff/atribuicao.py::atribuir`, TEC-404) o sobrescreve. A cascata
continua sendo o que decide quando a coluna esta nula ou aponta um inativo.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff


async def destinatario_do_handoff(session: AsyncSession, *, handoff: Handoff) -> Corretor | None:
    """O corretor alocado, senao o plantao mais antigo, senao `None`.

    **Corretor inativo nao recebe, nem quando esta alocado.** A TEC-196 diz
    que desativar "o retira das proximas alocacoes"; mandar notificacao para
    quem saiu da equipe seria manter a alocacao antiga viva pela porta dos
    fundos. Nesse caso a cascata segue para o plantao.

    **O mais antigo entre varios plantoes**, por `criado_em`: a D7 da TEC-196
    deixou a multiplicidade aberta de proposito, e esta card precisa de uma
    resposta determinista para poder enviar. O mais antigo e o que nao muda
    quando alguem cadastra um plantao novo -- `ORDER BY criado_em DESC` faria
    o destinatario trocar sozinho a cada cadastro.

    `None` significa "nao ha a quem mandar", e quem chama marca o handoff como
    pendente de aviso manual (D4). Nao levanta: a ausencia de corretor e um
    estado previsto deste sistema, nao um erro.
    """
    if handoff.corretor_id is not None:
        alocado = await _corretor_ativo(session, corretor_id=handoff.corretor_id)
        if alocado is not None:
            return alocado

    return (
        await session.execute(
            select(Corretor)
            .where(Corretor.plantao.is_(True), Corretor.ativo.is_(True))
            .order_by(Corretor.criado_em)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _corretor_ativo(session: AsyncSession, *, corretor_id: uuid.UUID) -> Corretor | None:
    return (
        await session.execute(
            select(Corretor).where(Corretor.id == corretor_id, Corretor.ativo.is_(True))
        )
    ).scalar_one_or_none()


async def gerente_ativo(session: AsyncSession) -> Corretor | None:
    """O gerente que recebe a escalada de um handoff sem aceite, ou `None`.

    Espelha `destinatario_do_handoff`: mesma cascata de decisao, aplicada a
    `gerente` em vez de `plantao`.

    **O mais antigo entre varios gerentes**, por `criado_em` ascendente: e o
    que nao muda quando alguem cadastra outro gerente. `ORDER BY criado_em
    DESC` faria a escalada trocar de destinatario sozinha a cada cadastro, e
    um lead cobrado hoje seria cobrado de outra pessoa amanha sem ninguem ter
    decidido nada.

    **Gerente inativo nao conta.** `None` significa "nao ha gerente
    cadastrado" -- estado previsto deste sistema, nao erro -- e quem chama
    decide o que fazer.
    """
    return (
        await session.execute(
            select(Corretor)
            .where(Corretor.gerente.is_(True), Corretor.ativo.is_(True))
            .order_by(Corretor.criado_em)
            .limit(1)
        )
    ).scalar_one_or_none()
