"""A varredura do convite de remarcacao. TEC-172, RN-12.3.

Molde exato da `sweep_lembretes` (TEC-171), que por sua vez segue a
`sweep_crm_pendentes`: a regra de QUANDO nao esta aqui -- e `convite_devido`,
puro, em `domain/agendamento/remarcacao.py` -- e a consulta abaixo so estreita
as linhas que valem a pena olhar.

**Por que uma varredura e nao um job adiado no cancelamento**, e por que ela e
separada da `sweep_lembretes`:

- Adiado nao serve pela razao de sempre: um job na fila nao se desmarca, e um
  lead que remarca por outro caminho nao pode receber o convite antigo. A
  varredura le o estado de agora.
- Separada porque o que as duas compartilham ja esta compartilhado -- a ancora
  (`domain/messages/ancora.py`), a guarda de horario, a janela da Meta -- e o
  que sobra e o par consulta/texto, que e diferente nas duas. Uma varredura so
  com um parametro de "tipo de mensagem" trocaria duas funcoes legiveis por
  uma com dois modos.

**Nenhum lead recebe convite hoje**: nenhum caminho de producao cancela
agendamento. A TEC-371 passou a CRIAR agendamento por conversa, e nao a
cancelar -- o detector dela veta `cancelar` e `desmarcar`, que sao a TEC-372.
Ver
docs/superpowers/specs/2026-09-25-tec-172-cancelar-remarcar-e-nao-comparecimento-design.md.
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
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.remarcacao import (
    ANTECEDENCIA_DO_CONVITE,
    IDIOMA_DO_TEMPLATE,
    TEXTO_DO_CONVITE_DE_REMARCACAO,
    VALIDADE_DO_CONVITE,
    convite_devido,
    kind_do_convite,
    template_do_convite,
)
from mobia.domain.messages.ancora import Ancora, ancora_em_sessao_propria
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.janela import dentro_da_janela

log = structlog.get_logger(__name__)

SWEEP_REMARCACOES_JOB = "sweep_remarcacoes"

# Os dois tetos por execucao, com a mesma conta da varredura irma -- o custo
# por convite e o mesmo (um POST de ate 10s, sem chamada ao modelo) e o
# `job_timeout` e o mesmo 240. Ver o comentario das constantes em
# `sweep_lembretes.py`, que guarda a aritmetica; repeti-la aqui criaria duas
# copias de um numero que se corrige medindo.
MAXIMO_DE_CONVITES_POR_EXECUCAO = 50
TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90

_COLUNA_RESOLVIDO = "remarcacao_convidada_em"


@dataclass(frozen=True, slots=True)
class _Candidato:
    id: uuid.UUID
    channel: str
    conversation_key: str
    cancelado_em: datetime | None


async def _candidatos(
    session_factory: async_sessionmaker[AsyncSession], *, agora: datetime, limite: int
) -> list[_Candidato]:
    """Os cancelamentos que podem ter convite devido. PRE-FILTRO, nao a regra.

    A janela grosseira e derivada das proprias constantes da regua, e nao
    escrita a mao: mexer no piso ou no teto em `remarcacao.py` alarga esta
    consulta sozinho, e quem decide de verdade continua sendo
    `convite_devido`.

    Sem `FOR UPDATE SKIP LOCKED`, pela razao que `sweep_lembretes._candidatos`
    escreve: o que vem depois da leitura e um POST, e quem impede duas
    varreduras de mandarem o mesmo convite e a UNIQUE `(message_id, kind)`.
    """
    mais_antigo = agora - ANTECEDENCIA_DO_CONVITE - VALIDADE_DO_CONVITE
    mais_recente = agora - ANTECEDENCIA_DO_CONVITE
    async with session_factory() as session:
        linhas = (
            await session.execute(
                select(
                    Agendamento.id,
                    Agendamento.channel,
                    Agendamento.conversation_key,
                    Agendamento.cancelado_em,
                )
                .where(
                    Agendamento.status == StatusDoAgendamento.CANCELADO,
                    Agendamento.cancelado_em.is_not(None),
                    Agendamento.cancelado_em > mais_antigo,
                    Agendamento.cancelado_em <= mais_recente,
                    Agendamento.remarcacao_convidada_em.is_(None),
                )
                .order_by(Agendamento.cancelado_em)
                .limit(limite)
            )
        ).all()
    return [
        _Candidato(id=linha[0], channel=linha[1], conversation_key=linha[2], cancelado_em=linha[3])
        for linha in linhas
    ]


async def _marcar(
    session_factory: async_sessionmaker[AsyncSession],
    agendamento_id: uuid.UUID,
    agora: datetime,
) -> None:
    """Grava a coluna de resolvido, se ela ainda for nula."""
    async with session_factory() as session:
        await session.execute(
            update(Agendamento)
            .where(
                Agendamento.id == agendamento_id,
                Agendamento.remarcacao_convidada_em.is_(None),
            )
            .values(**{_COLUNA_RESOLVIDO: agora})
        )
        await session.commit()


def _payload(
    candidato: _Candidato, ancora: Ancora, *, aprovados: frozenset[str], agora: datetime
) -> dict[str, Any] | None:
    """O que vai pela porta, ou `None` quando nada pode ir.

    A janela de 24h e regra do WhatsApp, e so ele a paga -- `outbound/web.py`
    registra que o canal web nao tem janela, e nele nao ha template a mandar.
    Mesma decisao e mesma razao de `sweep_lembretes._payload_do_lembrete`.

    **O convite nao leva parametro nenhum no template.** Ele nao descreve o
    compromisso -- convida a marcar outro --, entao nao ha valor a preencher;
    `outbound/whatsapp.py` so acrescenta `components` quando ha parametros, e
    uma lista vazia e exatamente o caso que ele ja trata.
    """
    comum = {"para": candidato.conversation_key, "de": ancora.de}
    paga_a_janela = candidato.channel == CANAL_WHATSAPP
    if not paga_a_janela or dentro_da_janela(ancora_em=ancora.criada_em, agora=agora):
        return comum | {"texto": TEXTO_DO_CONVITE_DE_REMARCACAO}
    template = template_do_convite(aprovados=aprovados)
    if template is None:
        return None
    return comum | {
        "tipo": "template",
        "template": template,
        "idioma": IDIOMA_DO_TEMPLATE,
        "parametros": [],
    }


async def sweep_remarcacoes(
    ctx: dict[str, Any], limite: int = 200, *, agora: datetime | None = None
) -> int:
    """Convida a remarcar quem cancelou ha 24 horas. Devolve quantos convites SAIRAM.

    O retorno conta envio aceito, e nao convite resolvido: um recusado pela
    guarda grava a coluna e nao entra na conta, pela razao que
    `sweep_lembretes` escreve.

    **A guarda de horario roda no topo** (RN-13.3), como nas duas varreduras
    irmas e pelo mesmo argumento de fuso unico. Esta e a TERCEIRA a aplica-la,
    e a docstring de `outbound/horario.py` lista as tres.

    **A coluna quer dizer "resolvido", e nao "entregue"**, e e gravada tambem
    quando a guarda recusa. O porque esta na docstring da migration 0049 e nao
    se repete: a diferenca e o cron, que sem isso tentaria de novo a cada
    cinco minutos por sete dias.

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
        log.debug("sweep.remarcacoes_fora_do_horario", agora=agora.isoformat())
        return 0

    comeco = time.monotonic()
    enviados = 0

    for candidato in await _candidatos(session_factory, agora=agora, limite=limite):
        if enviados >= MAXIMO_DE_CONVITES_POR_EXECUCAO or (
            time.monotonic() - comeco > TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS
        ):
            # O que sobra continua devido e entra na passagem seguinte: a
            # faixa e de sete dias, e nao se move.
            log.info("remarcacao.corte_por_teto", enviados=enviados)
            break
        if not convite_devido(cancelado_em=candidato.cancelado_em, agora=agora):
            continue
        try:
            if await _convidar(
                session_factory,
                candidato,
                outbound=outbound,
                aprovados=settings.templates_aprovados,
                agora=agora,
            ):
                enviados += 1
        except Exception as falha:
            # `except Exception` pelo contrato de `OutboundPort`: o adaptador
            # levanta tipos distintos e nenhum deles pode custar o convite dos
            # outros candidatos. A coluna fica NULA -- falha de canal e o caso
            # em que a passagem seguinte deve tentar de novo, e a faixa e o
            # teto dessa retentativa.
            log.warning(
                "remarcacao.envio_falhou",
                agendamento_id=str(candidato.id),
                reason=type(falha).__name__,
            )

    if enviados:
        log.info("remarcacao.varredura", enviados=enviados)
    return enviados


async def _convidar(
    session_factory: async_sessionmaker[AsyncSession],
    candidato: _Candidato,
    *,
    outbound: Any,
    aprovados: frozenset[str],
    agora: datetime,
) -> bool:
    """Um convite. Devolve se ele SAIU; a coluna e gravada em mais casos."""
    ancora = await ancora_em_sessao_propria(
        session_factory, channel=candidato.channel, conversation_key=candidato.conversation_key
    )
    if ancora is None or ancora.de is None:
        log.info("remarcacao.sem_ancora", agendamento_id=str(candidato.id))
        await _marcar(session_factory, candidato.id, agora)
        return False

    payload = _payload(candidato, ancora, aprovados=aprovados, agora=agora)
    if payload is None:
        # `warning` pelo criterio de `lembrete.sem_template`: funcionou como
        # desenhado, e alguem precisa saber. Com `WHATSAPP_TEMPLATES_APROVADOS`
        # vazio este e o caminho de quase todo convite -- quem cancelou e, por
        # definicao, alguem que parou de falar com o agente.
        log.warning("remarcacao.sem_template", agendamento_id=str(candidato.id))
        await _marcar(session_factory, candidato.id, agora)
        return False

    aceito = await outbound.send(ancora.message_id, kind_do_convite(candidato.id), payload)
    await _marcar(session_factory, candidato.id, agora)
    if not aceito:
        log.info("remarcacao.recusado", agendamento_id=str(candidato.id))
        return False
    log.info("remarcacao.enviado", agendamento_id=str(candidato.id))
    return True
