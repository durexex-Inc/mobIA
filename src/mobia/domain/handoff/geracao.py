"""A geracao do resumo, de ponta a ponta.

TEC-175. Roda FORA da transacao do turno -- ver a D1 do desenho: o handoff
nasce dentro dela, e uma chamada de LLM de 8s no p95 ali dentro seguraria o
`SELECT ... FOR UPDATE` do recalculo por esses 8s, cobrando do tempo de
resposta do LEAD um resumo que e para o CORRETOR.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.contingencia import montar
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
    """Gera e grava. `False` passa a significar uma coisa so: nao havia dossie.

    RN-15.4: o corretor nunca fica sem resumo. Antes da TEC-176, um resumo
    invalido (`ResumoDeHandoffInvalido`) ou uma excecao do provedor deixavam o
    handoff sem nada gravado -- a promessa da regra valia so pela metade. Os
    dois caminhos agora caem no template deterministico de `contingencia.py`
    (Emenda E-01) e SEM retentativa: o template e gravado na primeira falha,
    porque a degradacao e do conteudo, nao do fluxo (Emenda E-02). A UNICA
    excecao que continua devolvendo `False` sem gravar nada e a declarada:
    dossie ausente, porque sem fatos nao ha template possivel.

    **Recebe factory e nao sessao**, ao contrario de `registrar_handoff`. A
    inversao e deliberada: a leitura do dossie e a escrita do resumo sao DUAS
    transacoes, e a chamada ao modelo fica entre elas, fora de qualquer uma.
    Uma sessao unica manteria a transacao aberta durante os 8s da chamada, que
    e exatamente o que a D1 existe para evitar -- so que no worker em vez de
    no turno.

    Nao levanta quando o dossie esta ausente porque quem chama e um job: um
    handoff sem dossie e um estado previsto (a TEC-176 atende o resto -- um
    handoff sem RESUMO deixa de ser possivel), e transformar isso em
    retentativa do ARQ so repetiria a mesma chamada cara.
    """
    async with session_factory() as session:
        dossie = await carregar_dossie(session, handoff_id=handoff_id)

    if dossie is None:
        # Nao e erro: o job pode chegar depois de a linha sumir. Esta e a
        # UNICA excecao que ainda devolve False -- ver a docstring acima.
        log.warning("resumo_handoff.handoff_sumiu", handoff_id=str(handoff_id))
        return False

    try:
        gerado = await redator.redigir(renderizar(dossie))
    except ResumoDeHandoffInvalido as falha:
        # Resposta malformada (bloco ausente, fora de ordem, ou acima do
        # limite mesmo depois da compressao). Emenda E-01: cai no template em
        # vez de deixar o resumo nulo. Nunca loga o dossie nem a resposta: so
        # o motivo, que e a forma do erro de validacao, nunca conteudo do lead.
        log.warning("resumo_handoff.invalido", handoff_id=str(handoff_id), motivo=str(falha))
        texto = montar(dossie)
        modelo = None
        fallback = True
    except Exception as falha:
        # O provedor caiu -- timeout, conexao, 5xx. Sem este except a excecao
        # ESCAPARIA e o ARQ retentaria, o que a Emenda E-02 proibe: a
        # degradacao e do conteudo, nao do fluxo, entao o template e gravado
        # na hora, sem segunda tentativa. Largura deliberada -- ver a decisao
        # (a) do relatorio da Task 3 (TEC-176) para o motivo e o risco aceito.
        # So o TIPO da excecao vai ao log, nunca `str(falha)`: o SDK nao
        # garante que a mensagem de uma excecao generica esteja livre de
        # conteudo do lead, ao contrario do corpo tratado de
        # `infra/anthropic.motivo_do_provedor`.
        log.error(
            "resumo_handoff.provedor_falhou",
            handoff_id=str(handoff_id),
            tipo=type(falha).__name__,
        )
        texto = montar(dossie)
        modelo = None
        fallback = True
    else:
        texto = gerado.texto
        modelo = gerado.modelo
        fallback = False

    async with session_factory() as session:
        await gravar_resumo(
            session,
            handoff_id=handoff_id,
            texto=texto,
            modelo=modelo,
            fallback=fallback,
        )
        await session.commit()

    log.info(
        "resumo_handoff.gravado",
        handoff_id=str(handoff_id),
        caracteres=len(texto),
        fallback=fallback,
    )
    return True
