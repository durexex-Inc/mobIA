"""O indicador de digitacao, e o relogio que decide quando envia-lo.

TEC-274, RN-04.7 (Emenda E-01). O contrato e proprio e nao um metodo a mais em
`OutboundPort` porque as duas semanticas sao opostas: la o TIPO da excecao
decide o desfecho do turno, e aqui excecao nenhuma decide coisa alguma. Ver a
D4 do desenho.

**A guarda mora aqui, no agendador, e nao no adaptador** -- e nao ha
equivalente de `GuardedOutbound` para herdar. A rota ate
`IndicadorDePresencaPort` e uma so, e e esta: quem instanciar um adaptador
direto e chama-lo por fora nao tem guarda nenhuma, o mesmo risco que o
docstring de `OutboundPort` ja escreve para si.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.repositorio import esta_silenciada_por_mensagem
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout_por_mensagem

log = structlog.get_logger(__name__)


class IndicadorDePresencaPort(Protocol):
    """Mostrar ao lead que estamos respondendo. Nada mais.

    **Nenhuma excecao deste metodo muda o desfecho do turno**, e e a
    diferenca central para `OutboundPort.send`. Nao ha retorno a interpretar,
    nao ha `kind`, nao ha reserva em `outbound_dispatches` e nao ha
    retentativa a decidir: um indicador que chega tarde nao vale nada, e a
    regra existe contra a percepcao de abandono -- falhar nela nao pode
    custar a resposta. Quem implementar isto pode levantar o que quiser; o
    agendador engole tudo e loga.

    `provider_message_id` e o id da mensagem de ENTRADA no provedor (o
    `wamid`, no WhatsApp), e nao um id nosso: o indicador da Meta e uma
    anotacao sobre uma mensagem recebida, nao um envio para um numero.
    """

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None: ...


class IndicadorNoop:
    """Nao indica nada -- o ambiente sem canal, e o duble natural nos testes."""

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        log.info("presenca.noop")


async def _esperar_e_indicar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: uuid.UUID,
    provider_message_id: str,
    de: str,
    indicador: IndicadorDePresencaPort,
    apos_segundos: float,
) -> None:
    """Dorme o limiar, confere as guardas, e dispara uma vez.

    **As guardas rodam aqui, depois do sono, e nao antes dele.** Conferi-las
    no agendamento cobriria so o opt-out ja gravado quando o turno comecou;
    conferi-las no disparo cobre tambem o lead que digita "parar" DURANTE a
    espera, que e precisamente a janela em que isso acontece. Sao as mesmas
    duas consultas de `GuardedOutbound.send` -- ver a D3 do desenho.

    O `except Exception` envolve as guardas junto com o disparo de proposito:
    um banco indisponivel nao pode virar excecao numa tarefa que ninguem
    aguarda. `asyncio.CancelledError` e `BaseException` e passa reto, que e o
    desfecho certo quando o gerente de contexto cancela.
    """
    await asyncio.sleep(apos_segundos)
    try:
        async with session_factory() as session:
            if await esta_em_optout_por_mensagem(session, message_id):
                log.info("presenca.indicador_barrado", motivo="optout")
                return
            if await esta_silenciada_por_mensagem(session, message_id):
                log.info("presenca.indicador_barrado", motivo="atendimento_humano")
                return
        await indicador.indicar_digitacao(provider_message_id=provider_message_id, de=de)
        log.info("presenca.indicador_enviado")
    except Exception as exc:
        # `warning` e nao `error`: o indicador falhar degrada a experiencia e
        # nao quebra nada -- a resposta sai pelo caminho de sempre. So o nome
        # da classe, como no resto do projeto: o texto de uma excecao de
        # terceiro nao e garantia que este repositorio possa dar.
        log.warning("presenca.indicador_falhou", reason=type(exc).__name__)


@asynccontextmanager
async def indicador_de_digitacao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    indicador: IndicadorDePresencaPort,
    apos_segundos: float,
) -> AsyncIterator[None]:
    """Envolve a geracao da resposta: passou de `apos_segundos`, indica.

    `apos_segundos` e parametro obrigatorio e nao lido de `Settings` aqui
    dentro: quem monta o turno e quem conhece a configuracao, e um default
    opcional so para o teste encurtar a espera seria producao carregando um
    parametro que producao nunca passa.

    **Na saida, `cancel()` sem `await`.** Awaitar dentro do `finally` devolve
    o `CancelledError` do escopo de FORA quando o `job_timeout` do ARQ estoura,
    e um `suppress` em volta o engoliria -- justamente o cancelamento que o
    `except asyncio.CancelledError` de `process_message` existe para ver
    chegar, e sem o qual a linha fica em PROCESSING para sempre. Nao awaitar
    nao custa nada: uma tarefa cancelada nao guarda excecao para ninguem
    recolher. A variavel local e a referencia forte que impede a coleta
    prematura ate la.
    """
    provider_message_id = message.provider_message_id
    de = message.recipient_external_id
    if provider_message_id is None or de is None:
        # Sem o wamid da entrada ou sem o numero do canal nao ha requisicao a
        # montar. Sair aqui, e nao descobrir isso depois do sono, evita uma
        # tarefa inteira para nada.
        log.info("presenca.sem_insumo", message_id=str(message.id))
        yield
        return

    tarefa = asyncio.create_task(
        _esperar_e_indicar(
            session_factory,
            message_id=message.id,
            provider_message_id=provider_message_id,
            de=de,
            indicador=indicador,
            apos_segundos=apos_segundos,
        )
    )
    try:
        yield
    finally:
        tarefa.cancel()
