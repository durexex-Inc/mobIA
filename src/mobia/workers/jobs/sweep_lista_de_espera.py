"""A varredura do slot liberado. TEC-169, RN-11.5.

Molde exato da `sweep_remarcacoes` (TEC-172), que por sua vez segue a
`sweep_lembretes`: a regra de QUE TEXTO e de QUE TEMPLATE esta em
`domain/agendamento/espera.py`, puro, e a consulta abaixo so estreita as
linhas que valem a pena olhar.

**Por que uma varredura e nao um job disparado no cancelamento.** A razao de
sempre: um job na fila nao se desmarca, e o horario que um cancelamento
liberou pode ter sido reservado por outro lead antes de o job rodar. A
varredura le o estado de agora.

**O pareamento e um-para-um, e mora na tabela da fila.** Cada cancelamento
dentro da janela avisa UM lead -- o primeiro por `aceita_em` --, e a coluna
`lista_de_espera.avisada_por_agendamento_id` e o que registra qual slot foi
gasto em quem. O UNIQUE sobre ela e quem impede duas passagens concorrentes de
gastarem o mesmo cancelamento em dois leads.

**Avisar a fila inteira seria a outra leitura da card, e foi recusada.** "Quem
esta na lista e avisado, na ordem de entrada" se le das duas formas; avisar
todos sobre uma vaga produz uma corrida e N-1 decepcoes, e o lock otimista da
RN-11.4 so protege depois da escolha -- ele nao impede a promessa. Ver a D7 do
desenho.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import Settings, get_settings
from mobia.domain.agendamento.espera import (
    IDIOMA_DO_TEMPLATE,
    TEXTO_DO_SLOT_LIBERADO,
    kind_do_aviso,
    template_do_aviso,
)
from mobia.domain.agendamento.models import Agendamento, ListaDeEspera, StatusDoAgendamento
from mobia.domain.messages.ancora import Ancora, ancora_em_sessao_propria
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.janela import dentro_da_janela

log = structlog.get_logger(__name__)

SWEEP_LISTA_DE_ESPERA_JOB = "sweep_lista_de_espera"

# Os dois tetos por execucao, com a mesma conta das varreduras irmas -- o custo
# por aviso e o mesmo (um POST de ate 10s, sem chamada ao modelo) e o
# `job_timeout` e o mesmo 240. Ver o comentario das constantes em
# `sweep_lembretes.py`, que guarda a aritmetica; repeti-la aqui criaria duas
# copias de um numero que se corrige medindo.
MAXIMO_DE_AVISOS_POR_EXECUCAO = 50
TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90

# Os dois status em que um horario deixou de estar ocupado. `EXPIRADO` entra
# junto com `CANCELADO` porque a reserva que venceu tambem devolve o slot a
# grade -- e o lead na fila nao tem como distinguir as duas coisas, nem
# deveria.
STATUS_QUE_LIBERAM = (StatusDoAgendamento.CANCELADO, StatusDoAgendamento.EXPIRADO)


@dataclass(frozen=True, slots=True)
class _Par:
    """Um slot liberado e o lead da fila que vai receber o aviso dele."""

    espera_id: uuid.UUID
    channel: str
    conversation_key: str
    agendamento_id: uuid.UUID


async def _pares(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agora: datetime,
    horizonte: datetime,
    limite: int,
) -> list[_Par]:
    """Casa slots liberados com os primeiros da fila, em ordem de entrada.

    Duas consultas e nao um JOIN, e a razao e que o pareamento e POSICIONAL:
    o n-esimo slot vai para o n-esimo da fila. Um JOIN produziria o produto
    cartesiano dos dois conjuntos, e ordenar aquilo de volta para pares
    distintos custaria mais codigo do que este zip.

    Sem `FOR UPDATE SKIP LOCKED`, pela razao que `sweep_lembretes._candidatos`
    escreve: o que vem depois da leitura e um POST, e quem impede duas
    varreduras de gastarem o mesmo slot e o UNIQUE
    `uq_lista_de_espera_um_aviso_por_slot`.
    """
    async with session_factory() as session:
        # Os cancelamentos ja gastos em alguem, para nao avisar duas vezes
        # pelo mesmo slot.
        gastos = set(
            (
                await session.execute(
                    select(ListaDeEspera.avisada_por_agendamento_id).where(
                        ListaDeEspera.avisada_por_agendamento_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        slots = list(
            (
                await session.execute(
                    select(Agendamento.id)
                    .where(
                        Agendamento.status.in_([s.value for s in STATUS_QUE_LIBERAM]),
                        Agendamento.inicio > agora,
                        Agendamento.inicio <= horizonte,
                    )
                    .order_by(Agendamento.inicio)
                    .limit(limite)
                )
            )
            .scalars()
            .all()
        )
        livres = [slot for slot in slots if slot not in gastos]
        if not livres:
            return []

        fila = (
            await session.execute(
                select(ListaDeEspera.id, ListaDeEspera.channel, ListaDeEspera.conversation_key)
                .where(
                    ListaDeEspera.aceita_em.is_not(None),
                    ListaDeEspera.avisada_em.is_(None),
                )
                .order_by(ListaDeEspera.aceita_em)
                .limit(len(livres))
            )
        ).all()

    return [
        _Par(
            espera_id=linha[0],
            channel=linha[1],
            conversation_key=linha[2],
            agendamento_id=slot,
        )
        for linha, slot in zip(fila, livres, strict=False)
    ]


async def _marcar(
    session_factory: async_sessionmaker[AsyncSession], par: _Par, agora: datetime
) -> None:
    """Tira o lead da fila e gasta o slot, se ele ainda estiver na fila.

    Grava as duas colunas juntas porque elas sao o mesmo fato: este slot foi
    para este lead. Separa-las abriria a janela em que a fila andou sem que o
    cancelamento tivesse sido gasto.
    """
    async with session_factory() as session:
        await session.execute(
            update(ListaDeEspera)
            .where(ListaDeEspera.id == par.espera_id, ListaDeEspera.avisada_em.is_(None))
            .values(avisada_em=agora, avisada_por_agendamento_id=par.agendamento_id)
        )
        await session.commit()


def _payload(
    par: _Par, ancora: Ancora, *, aprovados: frozenset[str], agora: datetime
) -> dict[str, Any] | None:
    """O que vai pela porta, ou `None` quando nada pode ir.

    A janela de 24h e regra do WhatsApp, e so ele a paga -- `outbound/web.py`
    registra que o canal web nao tem janela, e nele nao ha template a mandar.
    Mesma decisao e mesma razao de `sweep_remarcacoes._payload`.

    **O aviso nao leva parametro nenhum no template**, pelo mesmo motivo que o
    convite de remarcacao nao leva: ele nao descreve o horario que abriu (D7),
    entao nao ha valor a preencher.
    """
    comum = {"para": par.conversation_key, "de": ancora.de}
    paga_a_janela = par.channel == CANAL_WHATSAPP
    if not paga_a_janela or dentro_da_janela(ancora_em=ancora.criada_em, agora=agora):
        return comum | {"texto": TEXTO_DO_SLOT_LIBERADO}
    template = template_do_aviso(aprovados=aprovados)
    if template is None:
        return None
    return comum | {
        "tipo": "template",
        "template": template,
        "idioma": IDIOMA_DO_TEMPLATE,
        "parametros": [],
    }


async def _avisar(
    session_factory: async_sessionmaker[AsyncSession],
    par: _Par,
    *,
    outbound: Any,
    aprovados: frozenset[str],
    agora: datetime,
) -> bool:
    """Um aviso. Devolve se ele SAIU; a fila anda em mais casos que esse."""
    ancora = await ancora_em_sessao_propria(
        session_factory, channel=par.channel, conversation_key=par.conversation_key
    )
    if ancora is None or ancora.de is None:
        log.info("espera.sem_ancora", espera_id=str(par.espera_id))
        await _marcar(session_factory, par, agora)
        return False

    payload = _payload(par, ancora, aprovados=aprovados, agora=agora)
    if payload is None:
        # `warning` pelo criterio de `lembrete.sem_template`: funcionou como
        # desenhado, e alguem precisa saber. Com `WHATSAPP_TEMPLATES_APROVADOS`
        # vazio -- o default, e a realidade do RT-03 (TEC-373) -- este e o
        # caminho de quase todo aviso, porque quem esta na fila ha dias parou
        # de falar com o agente faz tempo.
        log.warning("espera.sem_template", espera_id=str(par.espera_id))
        await _marcar(session_factory, par, agora)
        return False

    aceito = await outbound.send(ancora.message_id, kind_do_aviso(par.espera_id), payload)
    await _marcar(session_factory, par, agora)
    if not aceito:
        # Recusa da porta (reentrega suprimida, opt-out): o slot ja foi gasto
        # e a fila andou. Devolver a linha a fila faria o proximo slot voltar
        # para quem a porta acabou de recusar.
        log.info("espera.recusado", espera_id=str(par.espera_id))
        return False
    log.info("espera.enviado", espera_id=str(par.espera_id))
    return True


async def sweep_lista_de_espera(
    ctx: dict[str, Any], limite: int = 200, *, agora: datetime | None = None
) -> int:
    """Avisa a fila quando abre horario nas proximas 72 horas. Devolve quantos SAIRAM.

    O retorno conta envio aceito, e nao lead resolvido: um sem template gasta
    o slot, anda a fila e nao entra na conta -- pela razao que
    `sweep_remarcacoes` escreve.

    **A guarda de horario roda no topo** (RN-13.3), como nas tres varreduras
    irmas e pelo mesmo argumento de fuso unico.

    **A fila anda mesmo quando o envio nao sai**, e essa e a diferenca em
    relacao as irmas: la a coluna de resolvido existe para o cron nao tentar
    de novo; aqui ela existe tambem para o PROXIMO da fila nao ficar preso
    atras de um lead que nao pode ser avisado. Ver a D7 do desenho.

    `asyncio.CancelledError` continua propagando -- nao e `Exception`.
    """
    session_factory = ctx["session_factory"]
    outbound = ctx["outbound"]
    settings: Settings = ctx.get("settings") or get_settings()
    if agora is None:
        agora = datetime.now(UTC)

    if not horario_permite_envio(
        momento=agora,
        inicio=settings.followup_horario_inicio,
        fim=settings.followup_horario_fim,
        fuso=settings.fuso_de_envio,
    ):
        log.debug("sweep.espera_fora_do_horario", agora=agora.isoformat())
        return 0

    # Importado aqui e nao no topo: `conversa.py` importa handoff, que importa
    # corretores, e o topo deste modulo ja carrega `models`. O horizonte e o
    # mesmo numero que decide a lista de espera, e le-lo de la e o que impede
    # as duas metades da RN-11.5 divergirem.
    from mobia.domain.agendamento.conversa import HORIZONTE

    comeco = time.monotonic()
    enviados = 0

    for par in await _pares(
        session_factory, agora=agora, horizonte=agora + HORIZONTE, limite=limite
    ):
        if enviados >= MAXIMO_DE_AVISOS_POR_EXECUCAO or (
            time.monotonic() - comeco > TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS
        ):
            # O que sobra continua na fila e entra na passagem seguinte: o
            # slot so e gasto quando o aviso e resolvido.
            log.info("espera.corte_por_teto", enviados=enviados)
            break
        try:
            if await _avisar(
                session_factory,
                par,
                outbound=outbound,
                aprovados=settings.templates_aprovados,
                agora=agora,
            ):
                enviados += 1
        except Exception as falha:
            # `except Exception` pelo contrato de `OutboundPort`: o adaptador
            # levanta tipos distintos e nenhum deles pode custar o aviso dos
            # outros. As colunas ficam NULAS -- falha de canal e o caso em que
            # a passagem seguinte deve tentar de novo, com o mesmo lead e o
            # mesmo slot.
            log.warning(
                "espera.envio_falhou",
                espera_id=str(par.espera_id),
                reason=type(falha).__name__,
            )

    if enviados:
        log.info("espera.varredura", enviados=enviados)
    return enviados
