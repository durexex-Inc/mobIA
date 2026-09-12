"""A geracao do resumo, de ponta a ponta.

TEC-175. Roda FORA da transacao do turno -- ver a D1 do desenho: o handoff
nasce dentro dela, e uma chamada de LLM de 8s no p95 ali dentro seguraria o
`SELECT ... FOR UPDATE` do recalculo por esses 8s, cobrando do tempo de
resposta do LEAD um resumo que e para o CORRETOR.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.dossie import renderizar
from mobia.domain.handoff.repositorio import carregar_dossie, gravar_resumo
from mobia.domain.handoff.resumo import RedatorPort, ResumoDeHandoffInvalido

log = structlog.get_logger(__name__)


async def gerar_resumo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    redator: RedatorPort,
    handoff_id: uuid.UUID,
) -> bool:
    """Gera e grava. `True` quando gravou; `False` em toda falha esperada.

    **Recebe factory e nao sessao**, ao contrario de `registrar_handoff`. A
    inversao e deliberada: a leitura do dossie e a escrita do resumo sao DUAS
    transacoes, e a chamada ao modelo fica entre elas, fora de qualquer uma.
    Uma sessao unica manteria a transacao aberta durante os 8s da chamada, que
    e exatamente o que a D1 existe para evitar -- so que no worker em vez de
    no turno.

    Nao levanta em falha esperada porque quem chama e um job: um handoff sem
    resumo e um estado previsto (a TEC-176 o atende), e transformar isso em
    retentativa do ARQ so repetiria a mesma chamada cara.
    """
    async with session_factory() as session:
        dossie = await carregar_dossie(session, handoff_id=handoff_id)

    if dossie is None:
        # Nao e erro: o job pode chegar depois de a linha sumir.
        log.warning("resumo_handoff.handoff_sumiu", handoff_id=str(handoff_id))
        return False

    try:
        gerado = await redator.redigir(renderizar(dossie))
    except ResumoDeHandoffInvalido as falha:
        # O handoff FICA sem resumo, e de proposito -- resumo truncado corta o
        # bloco da proxima acao e parece completo. Ver a D7 do desenho. Nunca
        # loga o dossie nem a resposta: so o motivo.
        log.warning("resumo_handoff.invalido", handoff_id=str(handoff_id), motivo=str(falha))
        return False

    async with session_factory() as session:
        await gravar_resumo(
            session, handoff_id=handoff_id, texto=gerado.texto, modelo=gerado.modelo
        )
        await session.commit()

    log.info(
        "resumo_handoff.gravado",
        handoff_id=str(handoff_id),
        caracteres=len(gerado.texto),
        comprimiu=gerado.comprimiu,
    )
    return True
