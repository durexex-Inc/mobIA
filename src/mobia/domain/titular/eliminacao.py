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
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.midia.armazem import ArmazemDeMidia
from mobia.domain.titular.anonimizacao import anonimizar_lead
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import marcar_atendida
from mobia.domain.titular.vocabulario import StatusDaSolicitacao, TipoDeSolicitacao

log = structlog.get_logger(__name__)

# Quanto a transacao da anonimizacao espera por um lock antes de desistir
# (revisao final, M1). `anonimizar_lead` desliga as triggers de
# `lead_score_audit` e `conversation_intent_audit` com ALTER TABLE, que pede
# SHARE ROW EXCLUSIVE -- conflita com o ROW EXCLUSIVE de todo INSERT, e um
# pedido na fila bloqueia todo pedido conflitante que chega DEPOIS dele,
# inclusive o INSERT de score de cada turno. Sem teto, uma transacao aberta
# que ja escreveu numa dessas tabelas (um turno lento, uma correcao manual,
# outra anonimizacao ou reindexacao) deixava a anonimizacao esperando e todo
# turno que grava score esperando atras dela. Leitor puro nao entra na
# conta: o ACCESS SHARE de um SELECT nao conflita com SHARE ROW EXCLUSIVE.
# Com o teto a anonimizacao e quem perde: desiste em 5s, a transacao volta
# inteira, e a solicitacao continua ABERTA para a proxima tentativa -- o
# `Retry` do job (`workers/jobs/eliminar_lead.py`) ou a proxima passagem do
# sweep de retencao, que isola a falha por solicitacao.
LOCK_TIMEOUT_DA_ANONIMIZACAO = "5s"

# `lock_not_available`: o `lock_timeout` estourou.
_SQLSTATE_DO_LOCK_TIMEOUT = "55P03"


class AnonimizacaoSemLock(RuntimeError):
    """A anonimizacao desistiu de esperar um lock (`LOCK_TIMEOUT_DA_ANONIMIZACAO`).

    Nada foi gravado: a transacao voltou inteira. Quem chama decide quando
    tentar de novo.
    """


def _e_lock_timeout(exc: DBAPIError) -> bool:
    causa = getattr(exc.orig, "__cause__", None)
    return getattr(causa, "sqlstate", None) == _SQLSTATE_DO_LOCK_TIMEOUT


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
    anonimizar: a primeira o zerou. **Nem a que nao e de ELIMINACAO**, com o
    mesmo log: um id de pedido de ACESSO passado por engano apagaria o lead
    que so pediu para ver os proprios dados.

    `SELECT ... FOR UPDATE` pela mesma razao de `repositorio.py::recusar`:
    sem o lock, uma recusa concorrente podia fechar a linha entre esta
    leitura e a anonimizacao, e o lead seria anonimizado sob uma solicitacao
    RECUSADA.

    `marcar_atendida` roda ANTES de `anonimizar_lead`, e nao depois: a
    anonimizacao fecha toda solicitacao ABERTA do par (ver a docstring de
    `anonimizacao.py`), e esta seria fechada ali sem passar pelo UPDATE
    condicional de `marcar_atendida`, que entao levantaria
    `SolicitacaoNaoAberta` por uma linha que a propria transacao fechou.

    **A transacao inteira tem `lock_timeout`** (`LOCK_TIMEOUT_DA_ANONIMIZACAO`,
    por `SET LOCAL`, entao vale so para ela): esperar mais que isso por um
    lock vira `AnonimizacaoSemLock`, com `titular.anonimizacao_sem_lock` no
    log, e nada fica gravado. Ver o comentario da constante.

    Falha ao apagar um blob loga `titular.midia_nao_apagada` com a chave (que
    e so o id da mensagem, `midia/politica.py::chave_do_objeto`) e segue: o
    commit ja desligou o arquivo do lead, e reprovar aqui nao desfaz nada.
    Um cancelamento no meio do laco loga `titular.midia_apagamento_cancelado`
    com as chaves restantes e repropaga.
    """
    try:
        chaves_de_midia = await _anonimizar_na_transacao(session_factory, solicitacao_id)
    except DBAPIError as exc:
        if not _e_lock_timeout(exc):
            raise
        log.warning(
            "titular.anonimizacao_sem_lock",
            solicitacao_id=str(solicitacao_id),
            lock_timeout=LOCK_TIMEOUT_DA_ANONIMIZACAO,
        )
        raise AnonimizacaoSemLock(str(solicitacao_id)) from exc
    if chaves_de_midia is None:
        return

    # Mesma forma de `retencao.py::esvaziar_transcricoes_vencidas`: um
    # cancelamento no meio do laco (job_timeout, SIGTERM) loga as chaves que
    # ainda nao foram confirmadas apagadas e repropaga -- o blob orfao que
    # sobrar fica nomeado no log, e nao some em silencio.
    restantes = list(chaves_de_midia)
    try:
        while restantes:
            chave = restantes[0]
            try:
                await armazem.apagar(chave)
            except Exception:
                log.warning("titular.midia_nao_apagada", chave=chave, exc_info=True)
            restantes.pop(0)
    except BaseException:
        log.warning("titular.midia_apagamento_cancelado", chaves_restantes=restantes)
        raise


async def _anonimizar_na_transacao(
    session_factory: async_sessionmaker[AsyncSession], solicitacao_id: uuid.UUID
) -> list[str] | None:
    """A transacao de `anonimizar`; devolve as chaves de midia, ou `None`
    quando nao havia o que fazer (o log ja saiu)."""
    async with session_factory() as session:
        # Primeiro statement da transacao: o teto vale tambem para o
        # `FOR UPDATE` logo abaixo, e `SET LOCAL` morre com o commit ou o
        # rollback, sem vazar para a proxima transacao da conexao do pool.
        await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_DA_ANONIMIZACAO}'"))
        solicitacao = (
            await session.execute(
                select(SolicitacaoDeTitular)
                .where(SolicitacaoDeTitular.id == solicitacao_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            solicitacao is None
            or solicitacao.status != StatusDaSolicitacao.ABERTA.value
            or solicitacao.tipo != TipoDeSolicitacao.ELIMINACAO.value
        ):
            log.info(
                "titular.anonimizacao_ignorada",
                solicitacao_id=str(solicitacao_id),
                status=None if solicitacao is None else solicitacao.status,
                tipo=None if solicitacao is None else solicitacao.tipo,
            )
            return None

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
    return chaves_de_midia
