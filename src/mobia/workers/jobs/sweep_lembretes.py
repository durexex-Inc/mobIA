"""A varredura dos lembretes de agendamento. TEC-171, RN-12.2, CA-12.1.

Molde do `sweep_crm_pendentes`: um job `cron` que consulta trabalho vencido e
age. A regra de QUANDO um lembrete e devido nao esta aqui -- ela e a funcao
pura `lembrete_devido` (`domain/agendamento/lembretes.py`), e a consulta
abaixo so estreita as linhas que valem a pena olhar. Duas copias da mesma
regra, uma em SQL e outra em Python, sao o defeito de duas fontes que a
TEC-146 gastou uma card inteira consertando.

**Varredura, e nao dois jobs diferidos na hora da confirmacao.** O ARQ sabe
adiar (`_defer_until`), mas um job na fila nao se desmarca: a card manda que
agendamento cancelado ou remarcado nao receba os lembretes antigos, e quem
enfileirasse teria de lembrar de cancelar em cada caminho que mexe no
agendamento. A varredura le o estado de AGORA -- o que deixou de ser
CONFIRMADO simplesmente nao aparece na consulta, e foi assim que a TEC-172
ganhou a regra: ela acrescentou CANCELADO e REAGENDADO ao vocabulario sem
tocar uma linha deste arquivo.

**Desde a TEC-371 ha lead recebendo lembrete**: a conversa cria agendamento
CONFIRMADO, e a regua desta card passou a ter linha para varrer. E desde a
TEC-372 a resposta a ele e lida -- e `lembrete_24h_em`, carimbada aqui, que
abre a janela em que "cancelar" conta como cancelamento. Uma consequencia
pratica: esta coluna deixou de ser so uma marca de idempotencia. Ver
docs/superpowers/specs/2026-09-25-tec-171-lembretes-de-agendamento-design.md.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import Settings, get_settings
from mobia.domain.agendamento.lembretes import (
    LEMBRETES,
    Lembrete,
    escolher_template_do_lembrete,
    kind_do_lembrete,
    lembrete_devido,
    parametros_do_template_do_lembrete,
    texto_do_lembrete,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.messages.ancora import Ancora, ancora_em_sessao_propria
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.janela import dentro_da_janela

log = structlog.get_logger(__name__)

SWEEP_LEMBRETES_JOB = "sweep_lembretes"

# O teto de VOLUME por passagem. Com 50 a cada cinco minutos a vazao e de 600
# lembretes por hora, muito acima de qualquer acumulo plausivel -- e o
# excedente continua devido, porque a faixa da D2 nao se move quando um
# lembrete fica para tras.
MAXIMO_DE_LEMBRETES_POR_EXECUCAO = 50

# O teto de TEMPO, que e o que de fato fecha a conta -- o de cima, sozinho,
# nao limita o que diz limitar.
#
# **O custo de um lembrete aqui e MENOR que o de um follow-up, e a diferenca e
# o modelo.** `sweep_followups` paga `redigir_abertura`, que cai no
# `TIMEOUT_SEGUNDOS = 60.0` de `infra/anthropic.py`; esta varredura nao chama
# o modelo em lugar nenhum. O unico cliente externo por lembrete e o POST para
# a Meta, no maximo os `TIMEOUT_SEGUNDOS = 10.0` de `outbound/whatsapp.py`,
# que nao retenta.
#
# Cinquenta vezes 10 s sao 500 s contra um `job_timeout` de 240: o teto de
# contagem seria decorativo no unico cenario em que um teto importa. A conta
# que fecha e a mesma do irmao: 240 (`job_timeout`) - 10 (o cliente externo de
# um lembrete) - 20 (reserva declarada, NAO medida, para o custo de banco do
# candidato: a leitura da ancora, o `send` com as tres sessoes proprias de
# `GuardedOutbound`, e a gravacao da coluna) = 210. O numero abaixo e 90, bem
# menos do que a formula permite, e continua 90 pela mesma razao que o do
# irmao: reclamar o espaco mudaria quantos lembretes uma passagem entrega, que
# e efeito visivel para o lead e nao cabe a uma card que fala de timeout.
#
# A checagem roda no TOPO do laco, entao o pior caso e o teto MAIS um
# lembrete. O que muda esta conta: o `TIMEOUT_SEGUNDOS` de
# `outbound/whatsapp.py` e o `job_timeout` do worker.
TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90

# A janela grosseira da consulta, derivada dos proprios lembretes e nao
# escrita a mao: acrescentar um terceiro lembrete com antecedencia maior
# alarga a consulta sozinho. Quem decide de verdade e `lembrete_devido`.
_MAIOR_ANTECEDENCIA = max(lembrete.antecedencia for lembrete in LEMBRETES)


@dataclass(frozen=True, slots=True)
class _Candidato:
    """O agendamento e o que o texto precisa, lido uma vez e fora de sessao.

    Os passos seguintes -- ler a ancora, enviar, marcar -- abrem sessoes
    proprias e curtas, sem transacao aberta durante chamada de rede. E o molde
    de `_Retrato` em `confirmacao.py` e de `notificar` em
    `notificacao/envio.py`, e aqui ele vale duas vezes: segurar lock de linha
    durante um POST e a contencao que este repo ja pagou caro (ver a secao
    "Quando o `-n 8` derruba o Postgres", no CLAUDE.md).
    """

    id: uuid.UUID
    channel: str
    conversation_key: str
    tipo: str
    inicio: datetime
    confirmado_em: datetime | None
    corretor_nome: str
    imovel: Imovel | None
    resolvidos: frozenset[str]


async def _candidatos(
    session_factory: async_sessionmaker[AsyncSession], *, agora: datetime, limite: int
) -> list[_Candidato]:
    """Os agendamentos que podem ter lembrete devido. PRE-FILTRO, nao a regra.

    **Sem `FOR UPDATE SKIP LOCKED`, ao contrario de `sweep_crm_pendentes`.**
    La o claim e uma escrita na mesma linha que o SELECT trava, e o lock morre
    no commit antes do enqueue. Aqui o que vem depois da leitura e um POST
    para a Meta: manter a linha travada durante ele poria contencao de lock no
    caminho de uma chamada de rede. Quem impede duas varreduras concorrentes
    de mandarem o mesmo lembrete e a UNIQUE `(message_id, kind)` de
    `outbound_dispatches` -- a segunda recebe `False` de `send`, o mesmo
    desfecho de uma guarda que recusou, e grava a coluna sem mandar nada.

    `inicio > agora` sai de graca da faixa: a do lembrete de 2h termina em
    `inicio`, entao compromisso que ja comecou nao tem lembrete a dar.
    """
    async with session_factory() as session:
        linhas = (
            await session.execute(
                select(Agendamento, Corretor.nome)
                .join(Corretor, Corretor.id == Agendamento.corretor_id)
                .where(
                    Agendamento.status == StatusDoAgendamento.CONFIRMADO,
                    Agendamento.confirmado_em.is_not(None),
                    Agendamento.inicio > agora,
                    Agendamento.inicio <= agora + _MAIOR_ANTECEDENCIA,
                    or_(
                        Agendamento.lembrete_24h_em.is_(None),
                        Agendamento.lembrete_2h_em.is_(None),
                    ),
                )
                .order_by(Agendamento.inicio)
                .limit(limite)
            )
        ).all()

        candidatos = []
        for agendamento, corretor_nome in linhas:
            imovel = (
                await session.get(Imovel, agendamento.imovel_id) if agendamento.imovel_id else None
            )
            if imovel is not None:
                # Solto da sessao: os passos seguintes rodam com sessoes
                # proprias, e um objeto do ORM preso a uma ja fechada
                # convidaria atributo expirado.
                session.expunge(imovel)
            candidatos.append(
                _Candidato(
                    id=agendamento.id,
                    channel=agendamento.channel,
                    conversation_key=agendamento.conversation_key,
                    tipo=agendamento.tipo,
                    inicio=agendamento.inicio,
                    confirmado_em=agendamento.confirmado_em,
                    corretor_nome=corretor_nome,
                    imovel=imovel,
                    resolvidos=frozenset(
                        coluna
                        for coluna in _COLUNA_DE.values()
                        if getattr(agendamento, coluna) is not None
                    ),
                )
            )
        return candidatos


# A coluna que marca cada lembrete como resolvido. Mora aqui, e nao no
# `Lembrete`, porque o vocabulario do lembrete e de dominio e o nome da coluna
# e do schema -- `domain/agendamento/lembretes.py` nao importa o modelo.
_COLUNA_DE: dict[str, str] = {
    "24h": "lembrete_24h_em",
    "2h": "lembrete_2h_em",
}


async def _marcar(
    session_factory: async_sessionmaker[AsyncSession],
    agendamento_id: uuid.UUID,
    lembrete: Lembrete,
    agora: datetime,
) -> None:
    """Grava a coluna deste lembrete, se ela ainda for nula.

    `is_(None)` no WHERE pela mesma razao de `_marcar` em `confirmacao.py`:
    uma passagem concorrente que marcou primeiro -- durante a chamada de rede
    desta -- fica com a marca dela, em vez de ser sobrescrita.
    """
    coluna = _COLUNA_DE[lembrete.chave]
    async with session_factory() as session:
        await session.execute(
            update(Agendamento)
            .where(Agendamento.id == agendamento_id, getattr(Agendamento, coluna).is_(None))
            .values(**{coluna: agora})
        )
        await session.commit()


def _payload_do_lembrete(
    lembrete: Lembrete,
    candidato: _Candidato,
    ancora: Ancora,
    *,
    aprovados: frozenset[str],
    agora: datetime,
) -> dict[str, Any] | None:
    """O que vai pela porta, ou `None` quando nada pode ir.

    **A janela de 24h e uma regra do WhatsApp, e so o WhatsApp a paga.** Quem
    o diz e `outbound/web.py`: o canal web nao tem janela, e nele nao existe
    template a mandar. Aplicar a regra de um canal ao outro faria o lembrete
    de um lead do site virar um template que aquele adaptador nao sabe
    renderizar.

    `None` e o desfecho de "fora da janela e sem template aprovado", que com
    `aprovados` vazio -- o default do RT-03 -- e o caminho de quase todo
    lembrete: um lead que marcou visita ontem provavelmente nao escreveu
    desde entao, e vinte e quatro horas e exatamente a antecedencia do
    primeiro lembrete. Declarado na D4 do desenho.
    """
    comum = {"para": candidato.conversation_key, "de": ancora.de}
    se_aplica_a_janela = candidato.channel == CANAL_WHATSAPP
    if not se_aplica_a_janela or dentro_da_janela(ancora_em=ancora.criada_em, agora=agora):
        return comum | {
            "texto": texto_do_lembrete(
                lembrete,
                tipo=candidato.tipo,
                inicio=candidato.inicio,
                corretor=candidato.corretor_nome,
                imovel=candidato.imovel,
            )
        }
    template = escolher_template_do_lembrete(lembrete, aprovados=aprovados)
    if template is None:
        return None
    return comum | {
        "tipo": "template",
        "template": template,
        "idioma": lembrete.idioma,
        "parametros": parametros_do_template_do_lembrete(
            tipo=candidato.tipo,
            inicio=candidato.inicio,
            corretor=candidato.corretor_nome,
            imovel=candidato.imovel,
        ),
    }


async def sweep_lembretes(
    ctx: dict[str, Any], limite: int = 200, *, agora: datetime | None = None
) -> int:
    """Manda os lembretes devidos agora. Devolve quantos SAIRAM.

    O retorno conta envio aceito, e nao lembrete resolvido: um recusado pela
    guarda grava a coluna e nao entra na conta, porque somar os dois faria o
    numero mentir para quem mede a varredura.

    **A guarda de horario roda no topo, antes da consulta** (RN-13.3), como em
    `sweep_followups` e pela mesma razao: sob fuso unico (PR-04) a janela e
    propriedade de `agora` e nao do agendamento, entao nada do que a consulta
    trouxesse mudaria a resposta. A docstring de `outbound/horario.py` nomeia
    esta card como um dos sitios que deviam aplica-la; e o que esta linha faz.

    **A consequencia e declarada, e nao contornada:** com
    `followup_horario_inicio = 9`, uma visita as 9h ou as 10h tem a faixa
    inteira do lembrete de 2 horas fora do horario de contato, e esse lembrete
    nao sai. Nao ha excecao para esta card -- a RN-13.3 fala de envio
    automatico, e o lembrete e um. O registro do que nao saiu e a coluna nula
    com a faixa fechada, que se consulta:

        SELECT id, inicio FROM agendamentos
         WHERE status = 'CONFIRMADO' AND inicio < now() AND lembrete_2h_em IS NULL;

    **Os dois lembretes nunca sao devidos na mesma passagem**, e isso nao e
    sorte: as faixas sao `[inicio-24h, inicio-2h)` e `[inicio-2h, inicio)`,
    disjuntas por construcao. O laco de dentro continua iterando os dois
    porque e ele que escolhe QUAL, nao porque os dois possam sair juntos.

    **Nenhuma falha derruba o lote**, como em `sweep_followups`: cada
    candidato em seu `try`. `asyncio.CancelledError` continua propagando --
    nao e `Exception`.

    **`agora` entra por parametro** porque sem isso nenhum teste posiciona o
    relogio -- e, com a guarda de horario, a suite inteira desta varredura
    passaria ou reprovaria conforme a hora do dia em que o CI rodasse.
    Producao nao passa o argumento.
    """
    session_factory = ctx["session_factory"]
    # A mesma chave que `process_message` e `sweep_followups` leem: `startup`
    # grava ali o `RoteadorPorCanal`, que escolhe o adaptador pelo canal da
    # linha. E ele que carrega as guardas de opt-out (TEC-182) e de
    # atendimento humano (TEC-179), herdadas de `GuardedOutbound` -- por isso
    # nao ha checagem duplicada nenhuma neste arquivo.
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
        # `debug` e nao `info`, pelo mesmo criterio de `sweep_followups`: a
        # cadencia de cinco minutos faz isto disparar por treze das vinte e
        # quatro horas. Sem a linha, uma janela VALIDA mas ERRADA produz
        # ausencia de lembrete indistinguivel de "nenhum agendamento devido".
        log.debug(
            "sweep.lembretes_fora_do_horario",
            agora=agora.isoformat(),
            inicio=settings.followup_horario_inicio,
            fim=settings.followup_horario_fim,
            fuso=settings.followup_fuso,
        )
        return 0

    # `monotonic` e nao `agora`: `agora` e o relogio da REGUA, que os testes
    # posicionam no futuro ou no passado. O teto de tempo e de parede.
    comeco = time.monotonic()
    enviados = 0
    cortou = False

    for candidato in await _candidatos(session_factory, agora=agora, limite=limite):
        if cortou:
            break
        for lembrete in LEMBRETES:
            if _COLUNA_DE[lembrete.chave] in candidato.resolvidos:
                continue
            if not lembrete_devido(
                lembrete,
                inicio=candidato.inicio,
                confirmado_em=candidato.confirmado_em,
                agora=agora,
            ):
                continue
            if enviados >= MAXIMO_DE_LEMBRETES_POR_EXECUCAO or (
                time.monotonic() - comeco > TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS
            ):
                # O que sobra continua devido e entra na passagem seguinte,
                # cinco minutos depois: a faixa da D2 nao se move.
                log.info("lembrete.corte_por_teto", enviados=enviados)
                cortou = True
                break
            try:
                if await _mandar(
                    session_factory,
                    candidato,
                    lembrete,
                    outbound=outbound,
                    aprovados=settings.templates_aprovados,
                    agora=agora,
                ):
                    enviados += 1
            except Exception as falha:
                # `except Exception` e nao a lista curta, pelo mesmo contrato
                # de `_avisar_lead` (`confirmacao.py`): o `outbound` levanta
                # tipos distintos por adaptador, e nenhum deles pode custar o
                # lembrete dos outros candidatos. A coluna fica NULA -- falha
                # de canal e o caso em que a passagem seguinte deve tentar de
                # novo, e a faixa e o teto dessa retentativa.
                log.warning(
                    "lembrete.envio_falhou",
                    agendamento_id=str(candidato.id),
                    lembrete=lembrete.chave,
                    reason=type(falha).__name__,
                )

    if enviados:
        log.info("lembrete.varredura", enviados=enviados)
    return enviados


async def _mandar(
    session_factory: async_sessionmaker[AsyncSession],
    candidato: _Candidato,
    lembrete: Lembrete,
    *,
    outbound: Any,
    aprovados: frozenset[str],
    agora: datetime,
) -> bool:
    """Um lembrete. Devolve se ele SAIU; a coluna e gravada em mais casos.

    Os tres desfechos da D3, e a coluna em cada um:

    - aceito: gravada, e devolve `True`.
    - recusado pela guarda (`send` devolve `False`) ou sem template: gravada,
      e devolve `False`. **E aqui que esta card diverge da TEC-170**, que
      deixa nulo na recusa. La o job roda uma vez por enfileiramento; aqui
      quem chama e um `cron` de cinco em cinco minutos, e deixar nulo
      produziria uma tentativa barrada a cada cinco minutos por ate vinte e
      duas horas -- centenas de `outbound.optout_bloqueou` em `warning` por um
      lembrete que nunca vai sair. A guarda ja respondeu.
    - excecao: propaga para o `except` do laco, e a coluna fica NULA.
    """
    ancora = await ancora_em_sessao_propria(
        session_factory, channel=candidato.channel, conversation_key=candidato.conversation_key
    )
    if ancora is None or ancora.de is None:
        # Sem fala do lead nao ha `recipient_external_id`, que e o "de" do
        # canal -- mesmo desfecho e mesmo motivo que `_avisar_lead` da TEC-170
        # documenta. Marcada porque isto nao se resolve sozinho nas passagens
        # seguintes.
        log.info("lembrete.sem_ancora", agendamento_id=str(candidato.id))
        await _marcar(session_factory, candidato.id, lembrete, agora)
        return False

    payload = _payload_do_lembrete(lembrete, candidato, ancora, aprovados=aprovados, agora=agora)
    if payload is None:
        # `warning` e o nivel de `followup.tarefa_de_corretor`, e pela mesma
        # razao: funcionou como desenhado, e alguem precisa saber. **E nao
        # vira tarefa para o corretor**, como o follow-up vira: o corretor ja
        # recebeu o e-mail da TEC-170 com os dados da visita e ja tem o evento
        # na agenda, entao a tarefa seria a terceira copia do mesmo fato.
        log.warning(
            "lembrete.sem_template",
            agendamento_id=str(candidato.id),
            lembrete=lembrete.chave,
            template=lembrete.template,
        )
        await _marcar(session_factory, candidato.id, lembrete, agora)
        return False

    aceito = await outbound.send(
        ancora.message_id, kind_do_lembrete(lembrete, candidato.id), payload
    )
    await _marcar(session_factory, candidato.id, lembrete, agora)
    if not aceito:
        # A guarda recusou (opt-out, atendimento humano) ou uma passagem
        # concorrente ja tinha reservado esta chave. Nao e falha.
        log.info("lembrete.recusado", agendamento_id=str(candidato.id), lembrete=lembrete.chave)
        return False
    log.info("lembrete.enviado", agendamento_id=str(candidato.id), lembrete=lembrete.chave)
    return True
