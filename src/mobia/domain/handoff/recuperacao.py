"""A recuperacao do handoff PENDENTE que ficou sem prazo. TEC-279.

**Por que `escalar_vencidos` (TEC-178, `handoff/escalada.py`) nao pega este
caso.** Aquela varredura exige `sla_limite_em IS NOT NULL` -- de proposito,
porque nulo la significa "ainda nao notificado" ou "sem a quem cobrar", nunca
"prazo zero". Quem grava `sla_limite_em` e o job `notificar`
(`domain/notificacao/envio.py`), e ele so grava depois de RODAR. Se o
enfileiramento de `notificar` falhar -- o Redis fora do ar no momento exato
em que `gerar_resumo` tenta `enqueue_job`, por exemplo --, o handoff fica
PENDENTE, sem prazo, para sempre: a rede de `escalar_vencidos` depende
exatamente da peca que faltou. Este modulo e a segunda rede, que nao precisa
de prazo nenhum para agir.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.agendador import GERAR_RESUMO_JOB
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.notificacao.envio import NOTIFICAR_JOB

log = structlog.get_logger(__name__)

# As duas razoes do numero. Folgado o bastante para o caminho normal
# concluir mesmo com o provedor de resumo lento e uma retentativa do ARQ
# pelo meio -- dez minutos nao e o tempo de UMA chamada, e o de sobrar
# margem para ela falhar uma vez e tentar de novo. E, ao mesmo tempo, dentro
# do SLA de 15 minutos do lead QUENTE (`handoff/sla.py`, `prazo_em_minutos`):
# se a recuperacao demorasse mais que isso, o prazo que `notificar` gravaria
# ao ser reenfileirado ja nasceria vencido, e o handoff cairia direto em
# `escalar_vencidos` sem nunca ter dado ao corretor a chance de aceitar.
INTERVALO_DE_RECUPERACAO = timedelta(minutes=10)


class ReenfileiradorPort(Protocol):
    async def agendar_resumo(self, handoff_id: uuid.UUID) -> None: ...
    async def agendar_notificacao(self, handoff_id: uuid.UUID) -> None: ...


class ReenfileiradorArq:
    """Reenfileira `gerar_resumo` ou `notificar`, com os mesmos `_job_id` deles.

    **Sem noop.** `AgendadorNoop` (`agendador.py`) existe porque ~30 testes
    de turno o passam como default; nada chama a recuperacao por acidente,
    entao um noop aqui nao teria usuario nenhum -- so codigo morto.

    Reusar os dois `_job_id` -- `resumo:<id>` (`agendador.py:48`) e
    `notificar:<id>` (`workers/jobs/gerar_resumo.py:46`), verbatim -- e o que
    faz o reenfileiramento ser idempotente ENQUANTO o job original ainda
    estiver vivo: o ARQ recusa uma segunda entrada com a mesma chave. Depois
    que ele termina, a chave some (`keep_result=0`) e a idempotencia por
    `_job_id` some junto -- e por isso que o SELECT de `recuperar_sem_prazo`
    decide pelas tres colunas de estado do handoff, nunca pelo `_job_id`.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def agendar_resumo(self, handoff_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            GERAR_RESUMO_JOB, str(handoff_id), _job_id=f"resumo:{handoff_id}"
        )

    async def agendar_notificacao(self, handoff_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            NOTIFICAR_JOB, str(handoff_id), _job_id=f"notificar:{handoff_id}"
        )


async def recuperar_sem_prazo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    reenfileirador: ReenfileiradorPort,
    limite: int = 100,
) -> int:
    """Reenfileira o handoff PENDENTE ha muito tempo sem prazo. Devolve quantos.

    **A D1 tem cinco condicoes, e as tres do meio existem JUNTAS.**
    `notificar` grava `sla_limite_em` cedo -- antes de tentar qualquer canal
    -- e grava `notificado_em`/`aviso_manual_pendente` so no fim, depois de
    tentar. Nenhuma das tres preenchida e a assinatura exata de "esta funcao
    nunca chegou a rodar para este handoff": e o unico estado que o
    enfileiramento falho pode produzir. Um handoff em que `notificar` rodou
    e nenhum canal aceitou tem `aviso_manual_pendente = true` -- e esse
    handoff NAO esta perdido, e um que o sistema ja viu e cujo desfecho ja
    esta gravado (o corretor recebe o aviso manual). Reenfileira-lo aqui
    duplicaria a notificacao. `status = PENDENTE` e `sla_limite_em IS NULL`
    sozinhos nao bastam: e a combinacao das cinco que separa "nunca rodou"
    de "rodou e terminou de um jeito que nao grava prazo".

    **So reenfileira -- nunca escreve no handoff.** Quem grava `sla_limite_em`
    e `notificado_em`/`aviso_manual_pendente` e `notificar`; quem grava o
    resumo e `gerar_resumo`. Um `update(Handoff)` aqui duplicaria a escrita
    que o job reenfileirado ja faz.
    """
    agora = datetime.now(UTC)

    async with session_factory() as session:
        candidatos = (
            await session.execute(
                select(Handoff.id, Handoff.resumo)
                .where(
                    Handoff.status == Status.PENDENTE.value,
                    Handoff.sla_limite_em.is_(None),
                    Handoff.notificado_em.is_(None),
                    Handoff.aviso_manual_pendente.is_(False),
                    Handoff.criado_em < agora - INTERVALO_DE_RECUPERACAO,
                )
                # Mais velho primeiro, mesmo criterio de `escalar_vencidos`:
                # sob o teto de `limite`, quem esta perdido ha mais tempo nao
                # fica esfomeado por handoffs perdidos depois.
                .order_by(Handoff.criado_em)
                .limit(limite)
            )
        ).all()

    # Fora da sessao: `agendar_resumo`/`agendar_notificacao` sao rede (um
    # `enqueue_job` no Redis), e uma transacao aberta durante uma chamada de
    # rede e exatamente o que este desenho evita -- mesmo raciocinio de
    # `notificar` e de `_agendar_resumo`.
    for linha in candidatos:
        if linha.resumo is None:
            # Sem resumo, `gerar_resumo` ainda tem de rodar -- e ele mesmo
            # enfileira `notificar` ao terminar. Reenfileirar `notificar`
            # direto aqui perderia o resumo para sempre: o corretor
            # receberia `TEXTO_SEM_RESUMO` (caminho degradado da D2 da
            # TEC-177), legitimo quando o resumo falhou, indevido quando ele
            # nem foi tentado.
            await reenfileirador.agendar_resumo(linha.id)
        else:
            # Com resumo ja gravado, `gerar_resumo` nao tem mais o que fazer
            # -- e ele NAO checa se o resumo ja existe antes de chamar o
            # redator, entao reenfileira-lo pagaria uma segunda chamada ao
            # provedor por nada.
            await reenfileirador.agendar_notificacao(linha.id)
        log.warning(
            "handoff.recuperado_sem_prazo",
            handoff_id=str(linha.id),
            tinha_resumo=linha.resumo is not None,
        )

    return len(candidatos)
