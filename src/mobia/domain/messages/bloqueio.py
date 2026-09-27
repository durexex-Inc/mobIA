"""A marca de bloqueio na linha da mensagem (TEC-236).

Mora fora de `MessageRecorder` de proposito. O contrato daquele e explicito --
*"nenhum metodo propaga excecao. Quem chama esta no meio de responder ao
lead"* -- e ele esta certo para telemetria: perder uma linha de custo nao pode
derrubar a resposta.

**Aqui a escolha e a oposta, e a inversao e o ponto.** Se a marca falhar em
silencio, a fala bloqueada continua elegivel para o contexto do proximo turno e
para o resumo permanente. O desfecho seguro nao e "responda assim mesmo": e
falhar o turno, deixar a linha em FAILED e o sweeper retentar -- pagando de
novo a moderacao, que e barata perto de vazar a fala para dentro do prompt.

**A TEC-142 estende o mesmo argumento a auditoria.** `marcar_bloqueada` agora
grava a marca e o `ModerationEvent` no mesmo commit, e
`registrar_bloqueio_de_saida` grava so o evento (a saida nao tem linha propria
para carimbar). As duas propagam pelo motivo do paragrafo acima: sem a
transacao unica existiria o estado duravel "mensagem marcada como bloqueada,
recusa nao auditada" -- o estado em que o controle de risco da RN-B04 falha
em silencio.

**A TEC-297 trouxe para ca uma terceira funcao publica, e ela e a excecao:**
`moderar_entrada_e_marcar` engole `ModeracaoIndisponivel` e devolve `None`.
E fail-open deliberado, e nao contradiz os paragrafos acima porque trata de
outra falha: provedor fora do ar nao e marca perdida em silencio -- nao ha
fala julgada para carimbar, e negar atendimento a lead legitimo porque um
servico caiu pune o inocente (ver a docstring dela e
`domain/moderacao/port.py`). A falha da MARCA dentro dela continua subindo,
pelo motivo dos paragrafos acima: ela chama `marcar_bloqueada` e nao captura
nada dali para baixo.

**A TEC-204 acrescenta o evento da tentativa de injecao.** `INJECAO` nao
bloqueia (D3 do desenho): sozinha, `moderar_entrada_e_marcar` grava so o
`INJECAO_DETECTADA` em `eventos_auditoria`, numa sessao curta propria, e
devolve o veredito liberado -- sem marca e sem `ModerationEvent`, que continua
sendo uma linha por bloqueio. Junto de uma categoria que bloqueia, o evento
entra no mesmo commit de `marcar_bloqueada`. Nos dois casos a falha da
escrita sobe, pelo motivo dos paragrafos acima, e uma segunda passada sobre a
mesma mensagem nao grava um segundo evento.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.messages.models import Message
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
    Veredito,
)
from mobia.domain.privacidade.pseudonimo import pseudonimizar

log = structlog.get_logger(__name__)


async def _registrar_injecao(
    session: AsyncSession, *, message_id: UUID, channel: str, conversation_key: str
) -> None:
    """Acrescenta o `INJECAO_DETECTADA` a sessao de quem chama, uma vez por mensagem.

    A consulta antes e o que torna a escrita idempotente: o veredito liberado
    nao e persistido (ver `veredito_ja_registrado`), entao a retentativa de um
    turno remodera, acha a injecao de novo e, sem ela, gravaria um segundo
    evento para a mesma fala. Sem `detalhes`: o texto da tentativa fica na
    mensagem, cifrado, e nunca na trilha (D5 da TEC-206).
    """
    ja_registrado = await session.scalar(
        select(EventoAuditoria.id)
        .where(
            EventoAuditoria.acao == Acao.INJECAO_DETECTADA.value,
            EventoAuditoria.entidade == Entidade.MENSAGEM.value,
            EventoAuditoria.entidade_id == str(message_id),
        )
        .limit(1)
    )
    if ja_registrado is not None:
        return
    await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.INJECAO_DETECTADA,
        entidade=Entidade.MENSAGEM,
        entidade_id=str(message_id),
        lead=(channel, conversation_key),
    )


async def registrar_injecao_detectada(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
) -> None:
    """O evento da injecao que nao bloqueou, num commit proprio (TEC-204, D6).

    Sessao curta porque o caminho liberado nao tem outra: nao ha marca a
    carimbar nem recusa a auditar. Propaga como as irmas deste modulo.
    """
    async with session_factory() as session:
        await _registrar_injecao(
            session, message_id=message_id, channel=channel, conversation_key=conversation_key
        )
        await session.commit()


async def marcar_bloqueada(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: UUID,
    *,
    channel: str,
    conversation_key: str,
    categoria: str,
    injecao: bool = False,
) -> None:
    """Carimba `bloqueada_em` e grava a auditoria, num commit so.

    `UPDATE` direto e nao leitura-e-grava: a linha ja existe (a ingestao a
    gravou antes de o worker existir) e nao ha nada nela para ler antes de
    decidir. Uma segunda passada do sweeper sobre a mesma mensagem reescreve o
    carimbo com a hora nova, e isso e inofensivo -- o que importa e a coluna
    deixar de ser NULL, nao o instante exato.

    **As duas escritas sao uma so (TEC-142).** Duas transacoes deixariam
    existir o estado duravel "marcada, nao auditada": a marca protege o
    contexto do agente e nao diz nada sobre a auditoria, e esse e o estado em
    que o controle de risco da RN-B04 falha em silencio. Se qualquer uma
    falhar, nenhuma vale e a excecao sobe, pelo motivo no topo deste modulo.

    **A segunda passada NAO chega mais aqui pelo caminho do turno (TEC-298,
    D5) -- e so por ele.** Ate aquela card, uma retentativa remoderava e esta
    funcao gravava uma segunda linha para a mesma fala -- e o argumento
    escrito aqui era que "duas tentativas de recusar a mesma fala foram duas
    recusas". Ele deixou de valer NESSE caminho: `_ModeracaoDoTurno.resolver`
    (`domain/agente/turno.py`) consulta `veredito_ja_registrado` antes de
    chamar o moderador, e a linha de `moderation_events` que ele grava passou
    a significar uma FALA recusada em vez de uma TENTATIVA de recusa. Quem
    audita conta falas nesse caminho -- ver a Emenda E-04 da RN-04.5.

    **`moderar_entrada_e_marcar` tem um SEGUNDO chamador, e este continua sem
    a blindagem.** `_moderar_superada` (`workers/jobs/process_message.py`)
    chama esta funcao direto, sem consultar `veredito_ja_registrado` nem nada
    equivalente -- porque a mensagem SUPERADA nunca passa por
    `_ModeracaoDoTurno` (ela fecha "agrupado" antes de `executar_turno`
    rodar). Uma mensagem superada bloqueada, num turno que falhe depois e
    seja reprocessado pelo ramo do agrupado, ainda repaga a moderacao e ainda
    grava uma segunda linha de auditoria para a mesma fala -- exatamente o
    comportamento antigo, so que neste ramo. Escopo, nao descuido: a D5 desta
    card tratava da retentativa do TURNO bloqueado, que e onde a card
    nasceu -- o ramo do agrupado nao estava no recorte.

    O `UPDATE` continua sendo idempotente de proposito: se uma rota futura
    voltar a passar por aqui duas vezes, reescrever o carimbo com a hora nova
    e inofensivo -- o que importa e a coluna deixar de ser NULL.

    **Com `injecao`, o evento da TEC-204 entra no mesmo commit** -- nem
    recusa sem o registro da tentativa, nem registro sem a recusa.
    """
    async with session_factory() as session:
        await session.execute(
            update(Message).where(Message.id == message_id).values(bloqueada_em=datetime.now(UTC))
        )
        if injecao:
            await _registrar_injecao(
                session,
                message_id=message_id,
                channel=channel,
                conversation_key=conversation_key,
            )
        session.add(
            ModerationEvent(
                id=uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                direcao=Direcao.ENTRADA.value,
                categoria=categoria,
                message_id=message_id,
            )
        )
        await session.commit()


async def moderar_entrada_e_marcar(
    session_factory: async_sessionmaker[AsyncSession],
    moderador: ModeradorPort,
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
    corpo: str,
) -> Veredito | None:
    """Modera a fala de entrada e, se reprovada, marca e audita num commit so.

    **Devolve `None` somente quando o provedor esta indisponivel.** Fail-open,
    a assimetria que `domain/moderacao/port.py` documenta: a fala do lead ja
    esta cifrada no banco, e negar atendimento a lead legitimo porque um
    servico caiu pune o inocente. `None` e nao `Veredito(bloqueado=False)`
    porque "nao deu para moderar" nao e "moderou e liberou", e quem chama
    precisa poder distinguir.

    **Nao entrega recusa nenhuma.** Quem chama decide se ha texto a mandar: o
    turno entrega a recusa de entrada, o caminho do agrupado e os cinco ramos
    que retornam cedo nao entregam nada (TEC-297, D2).

    **`INJECAO` sozinha nao marca** (TEC-204): grava so o evento de auditoria
    e devolve o veredito liberado.

    Existe para ter um sitio so. Antes da TEC-297 esta sequencia estava
    escrita duas vezes -- no turno e em `_moderar_superada`, que a TEC-295
    criou --, e os cinco ramos que retornam antes da moderacao precisariam
    de uma terceira copia.

    **O provedor recebe a fala pseudonimizada (TEC-381, RNF-23).** A moderacao
    e o segundo caminho por onde o texto do lead sai do processo -- o outro e
    `context/montagem.py::_texto_da` --, e nome e telefone nao mudam veredito
    de toxicidade nem de injecao.
    """
    try:
        veredito = await moderador.moderar(pseudonimizar(corpo), direcao=Direcao.ENTRADA)
    except ModeracaoIndisponivel as exc:
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.ENTRADA.value,
            message_id=str(message_id),
            reason=str(exc),
        )
        return None

    if not veredito.bloqueado:
        if veredito.injecao:
            # `warning` e nao `error`: o atendimento segue, e quem acompanha a
            # tentativa le a trilha. Sem o texto -- e fala do lead.
            log.warning("moderacao.injecao_detectada", message_id=str(message_id))
            await registrar_injecao_detectada(
                session_factory,
                message_id=message_id,
                channel=channel,
                conversation_key=conversation_key,
            )
        return veredito

    # `error` e nao `warning`: e o nivel que o alerta observa, pelo mesmo
    # criterio de `outbound.recusado`. O texto julgado **nao** entra no log --
    # e fala do lead, coberta pela regra de PII.
    log.error(
        "moderacao.entrada_bloqueada",
        message_id=str(message_id),
        motivo=veredito.motivo,
        categoria=veredito.categoria,
    )
    # Se a marca falhar, a excecao sobe -- ver o topo deste modulo.
    #
    # `categoria or CATEGORIA_OUTRO`: `ModeradorPort` e um `Protocol`, um
    # adaptador futuro pode devolver `Veredito(bloqueado=True)` sem categoria,
    # e a coluna e `not null`. A alternativa seria esta chamada estourar por
    # causa de um campo de auditoria.
    await marcar_bloqueada(
        session_factory,
        message_id,
        channel=channel,
        conversation_key=conversation_key,
        categoria=veredito.categoria or CATEGORIA_OUTRO,
        injecao=veredito.injecao,
    )
    return veredito


async def veredito_ja_registrado(
    session_factory: async_sessionmaker[AsyncSession], *, message_id: UUID
) -> Veredito | None:
    """O veredito que uma passada anterior ja gravou, ou None (TEC-298, D5).

    `bloqueada_em` nao-nulo e o veredito persistido do caso BLOQUEADO: so
    `marcar_bloqueada` escreve essa coluna, e ela escreve junto com o
    `ModerationEvent`, no mesmo commit. Uma retentativa que encontra o carimbo
    nao precisa pagar a moderacao de novo nem gravar uma segunda linha de
    auditoria para a mesma fala -- ver a Emenda E-04 da RN-04.5.

    **Devolve None para o caso LIBERADO, e isso nao e lacuna de implementacao.**
    "Moderou e liberou" nao e persistido em lugar nenhum: `bloqueada_em` nulo
    nao distingue "julgado e liberado" de "nunca julgado". A assimetria vem do
    desenho da TEC-236 e nao desta card. A consequencia e real e aceita: um
    turno que morre DEPOIS de uma moderacao limpa paga duas vezes.

    **O `motivo` volta vazio.** Ele nao e persistido -- so alimenta o log
    `moderacao.entrada_bloqueada`, que a passada anterior ja emitiu. Inventar
    um motivo aqui seria pior que a lacuna: quem lesse o log acreditaria nele.
    """
    async with session_factory() as session:
        bloqueada_em = await session.scalar(
            select(Message.bloqueada_em).where(Message.id == message_id)
        )
        if bloqueada_em is None:
            return None
        categoria = await session.scalar(
            select(ModerationEvent.categoria)
            .where(
                ModerationEvent.message_id == message_id,
                ModerationEvent.direcao == Direcao.ENTRADA.value,
            )
            .order_by(ModerationEvent.created_at.desc())
            .limit(1)
        )
        # `or CATEGORIA_OUTRO` pelo mesmo motivo de `moderar_entrada_e_marcar`:
        # a linha de auditoria pode nao existir se a retencao a levou (ela nao
        # tem FK para `messages`, de proposito -- ver o comentario de
        # `ModerationEvent.message_id`), e o veredito nao pode sair sem
        # categoria por causa de um registro que expirou.
        return Veredito(bloqueado=True, motivo="", categoria=categoria or CATEGORIA_OUTRO)


async def registrar_bloqueio_de_saida(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
    categoria: str,
) -> None:
    """A auditoria do que a empresa nao disse.

    Sem marca a carimbar: o texto barrado nunca chegou a `messages` e nao vai
    chegar -- persisti-lo criaria em claro exatamente o que a moderacao
    impediu de sair. O `message_id` e o da mensagem de ENTRADA que originou o
    turno, que e a ancora que existe.

    Propaga como a irma acima: um bloqueio de saida nao auditado e o caso em
    que o risco reputacional da RN-B04 aconteceu e nao ficou registrado.
    """
    async with session_factory() as session:
        session.add(
            ModerationEvent(
                id=uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                direcao=Direcao.SAIDA.value,
                categoria=categoria,
                message_id=message_id,
            )
        )
        await session.commit()
