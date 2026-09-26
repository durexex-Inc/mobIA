"""Executar uma solicitacao de eliminacao: anonimizar, registrar, fechar. TEC-207, D1 e D3.

Orquestra `anonimizacao.anonimizar_lead` numa transacao so, com o evento
`LEAD_ANONIMIZADO` na trilha e a solicitacao fechada como ATENDIDA -- os tres
commitam juntos ou nenhum. Os arquivos de midia sao apagados **depois** do
commit: antes, um rollback deixaria linha apontando para blob apagado; depois,
o pior caso e um blob orfao, que ja nao se liga a lead nenhum.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.midia.armazem import ArmazemDeMidia
from mobia.domain.titular.anonimizacao import anonimizar_lead
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import marcar_atendida
from mobia.domain.titular.vocabulario import StatusDaSolicitacao

log = structlog.get_logger(__name__)


async def anonimizar(
    session_factory: async_sessionmaker[AsyncSession],
    armazem: ArmazemDeMidia,
    *,
    solicitacao_id: uuid.UUID,
) -> None:
    """Anonimiza o lead da solicitacao e a fecha como ATENDIDA.

    **Solicitacao que nao esta ABERTA nao faz nada** e loga
    `titular.anonimizacao_ignorada` -- o job pode rodar de novo (retry do
    ARQ, clique duplo no painel), e a segunda execucao ja nao tem par a
    anonimizar: a primeira o zerou.

    `SELECT ... FOR UPDATE` pela mesma razao de `repositorio.py::recusar`:
    sem o lock, uma recusa concorrente podia fechar a linha entre esta
    leitura e a anonimizacao, e o lead seria anonimizado sob uma solicitacao
    RECUSADA.

    `marcar_atendida` roda ANTES de `anonimizar_lead`, e nao depois: a
    anonimizacao fecha toda solicitacao ABERTA do par (ver a docstring de
    `anonimizacao.py`), e esta seria fechada ali sem passar pelo UPDATE
    condicional de `marcar_atendida`, que entao levantaria
    `SolicitacaoNaoAberta` por uma linha que a propria transacao fechou.

    Falha ao apagar um blob loga `titular.midia_nao_apagada` com a chave (que
    e so o id da mensagem, `midia/politica.py::chave_do_objeto`) e segue: o
    commit ja desligou o arquivo do lead, e reprovar aqui nao desfaz nada.
    """
    async with session_factory() as session:
        solicitacao = (
            await session.execute(
                select(SolicitacaoDeTitular)
                .where(SolicitacaoDeTitular.id == solicitacao_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if solicitacao is None or solicitacao.status != StatusDaSolicitacao.ABERTA.value:
            log.info(
                "titular.anonimizacao_ignorada",
                solicitacao_id=str(solicitacao_id),
                status=None if solicitacao is None else solicitacao.status,
            )
            return

        # Capturados antes de `marcar_atendida`, que os zera: o par antigo e o
        # que localiza o lead para a anonimizacao e o `lead_ref` do evento.
        channel = solicitacao.channel
        conversation_key = solicitacao.conversation_key
        if channel is None or conversation_key is None:
            raise RuntimeError(
                f"solicitacao {solicitacao_id} estava ABERTA sem o par -- "
                "ck_solicitacoes_de_titular_par_com_status deveria ter impedido isso"
            )

        await marcar_atendida(session, solicitacao_id, agora=datetime.now(UTC))
        chaves_de_midia = await session.run_sync(
            lambda s: anonimizar_lead(
                s.connection(), channel=channel, conversation_key=conversation_key
            )
        )
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.LEAD_ANONIMIZADO,
            entidade=Entidade.SOLICITACAO_DE_TITULAR,
            entidade_id=str(solicitacao_id),
            lead=(channel, conversation_key),
        )
        await session.commit()

    for chave in chaves_de_midia:
        try:
            await armazem.apagar(chave)
        except Exception:
            log.warning("titular.midia_nao_apagada", chave=chave, exc_info=True)
