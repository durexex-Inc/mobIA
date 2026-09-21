"""Os returns antecipados de `executar_turno` e a moderacao de entrada.

Antes da TEC-297 a moderacao rodava num ponto so, depois de cinco saidas que
retornam antes dele. A fala que disparava qualquer uma delas nunca era
moderada: `bloqueada_em` ficava nulo e os leitores dessa coluna a tratavam
como fala legitima.

O que este arquivo prova hoje e um ramo, o do pedido de humano, e prova pela
COLUNA e pela auditoria -- `bloqueada_em` carimbada e o `ModerationEvent` de
ENTRADA --, nao pelo desfecho do turno. Desfecho nao diz nada sobre o que
entra no prompt. Nada aqui mede ainda a janela de contexto: quando houver
teste que leia `literais_apos`, e ele que autoriza esta docstring a falar em
janela.
"""

from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import Direcao

TEXTO_REPROVAVEL = "quero falar com uma pessoa agora"


async def test_o_pedido_de_humano_reprovavel_recebe_a_marca(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O ramo #5 da spec, e o cenario que originou a card.

    O cenario de origem e o lead que xinga e pede uma pessoa na mesma frase:
    o ramo cria handoff, entrega o aviso e retornava sem nunca moderar -- a
    fala entrava no contexto, no score e na ancora de follow-up. Aqui o texto
    e so `TEXTO_REPROVAVEL`, sem xingamento nenhum, e quem reprova e o duble
    (`bloqueia_entrada=True`): o que importa e disparar o ramo, e o veredito
    vem do fake, nao do conteudo.
    """
    moderador = moderador_fake(bloqueia_entrada=True)

    desfecho = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto=TEXTO_REPROVAVEL,
    )

    assert desfecho == "pedido_de_humano", "o desfecho do ramo nao muda"
    assert moderador.entradas == 1, "a fala foi moderada exatamente uma vez"

    linhas = (
        (
            await session.execute(
                select(Message).where(
                    Message.channel == CANAL_AGENTE,
                    Message.conversation_key == CONVERSA_AGENTE,
                    Message.bloqueada_em.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(linhas) == 1, "a fala do ramo recebeu `bloqueada_em`"

    eventos = (
        (
            await session.execute(
                select(ModerationEvent).where(
                    ModerationEvent.message_id == linhas[0].id,
                    ModerationEvent.direcao == Direcao.ENTRADA.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(eventos) == 1, "marca e auditoria saem juntas (TEC-142)"
