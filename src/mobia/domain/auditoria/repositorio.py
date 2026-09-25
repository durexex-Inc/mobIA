"""A consulta paginada da trilha de auditoria. TEC-206, D8.

Funcao livre com `session` posicional e o resto keyword-only, sem commit -- a
convencao dos repositorios deste repo. Nenhuma funcao aqui escreve: a unica
escrita da trilha e `registro.registrar_evento`.
"""

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.consulta import CursorDaTrilha, FiltroDaTrilha
from mobia.domain.auditoria.models import EventoAuditoria


async def listar_eventos(
    session: AsyncSession, *, filtro: FiltroDaTrilha
) -> tuple[list[EventoAuditoria], CursorDaTrilha | None]:
    """A pagina pedida, do mais recente ao mais antigo, e o cursor da proxima.

    **Pede um item a mais e o descarta**, como `listar_leads`: responde "ha
    proxima pagina?" sem `COUNT(*)`. Sem `total`, pela mesma razao.

    A ordem `(criado_em DESC, id DESC)` e servida por
    `ix_eventos_auditoria_pagina`; o `id` desempata dois eventos no mesmo
    instante, que e o que impede o cursor de repetir ou pular linha.
    """
    consulta = select(EventoAuditoria)
    if filtro.ator_id is not None:
        consulta = consulta.where(EventoAuditoria.ator_id == filtro.ator_id)
    if filtro.acoes:
        consulta = consulta.where(EventoAuditoria.acao.in_(filtro.acoes))
    if filtro.de is not None:
        consulta = consulta.where(EventoAuditoria.criado_em >= filtro.de)
    if filtro.ate is not None:
        consulta = consulta.where(EventoAuditoria.criado_em < filtro.ate)
    if filtro.lead_ref is not None:
        consulta = consulta.where(EventoAuditoria.lead_ref == filtro.lead_ref)
    if filtro.cursor is not None:
        consulta = consulta.where(
            or_(
                EventoAuditoria.criado_em < filtro.cursor.criado_em,
                and_(
                    EventoAuditoria.criado_em == filtro.cursor.criado_em,
                    EventoAuditoria.id < filtro.cursor.id,
                ),
            )
        )

    linhas = list(
        (
            await session.execute(
                consulta.order_by(
                    EventoAuditoria.criado_em.desc(), EventoAuditoria.id.desc()
                ).limit(filtro.limite + 1)
            )
        ).scalars()
    )

    pagina = linhas[: filtro.limite]
    if len(linhas) <= filtro.limite or not pagina:
        return pagina, None
    ultimo = pagina[-1]
    return pagina, CursorDaTrilha(criado_em=ultimo.criado_em, id=ultimo.id)
