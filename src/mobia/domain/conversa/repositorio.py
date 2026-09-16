"""Leitura e escrita do ciclo de vida da conversa. TEC-138.

Nenhuma das tres commita -- a sessao e emprestada e o dono da transacao e quem
chama, como em `gravar_estado` e `registrar_recalculo`.
"""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status


async def encerrar_conversa(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    motivo: str,
    agora: datetime,
) -> None:
    """Marca a conversa como encerrada, com o motivo e o carimbo.

    Upsert e nao INSERT: a conversa pode ja ter linha de um encerramento
    anterior que a janela dos 30 dias ja reabriu. Encerrar de novo e
    idempotente de proposito -- `deve_encerrar` usa `>=` pela mesma razao.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        # `Status` e StrEnum e esta funcao grava `str(...)`, entao a coluna
        # guarda o literal, no mesmo molde de `gravar_intencao`
        # (`agente/repositorio.py`) com `Intencao`.
        "status": str(Status.ENCERRADA),
        "motivo_do_encerramento": motivo,
        "encerrada_em": agora,
    }
    statement = pg_insert(Conversa).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                "status": statement.excluded.status,
                "motivo_do_encerramento": statement.excluded.motivo_do_encerramento,
                "encerrada_em": statement.excluded.encerrada_em,
            },
        )
    )


async def esta_encerrada(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    agora: datetime,
) -> bool:
    """A conversa esta encerrada AGORA?

    Sem linha, nao esta -- o estado default e "pode receber", igual ao de
    `esta_em_optout`.

    **A resposta e do tempo, e nao so do status.** Um encerramento mais velho
    que a janela devolve False com a coluna ainda dizendo ENCERRADA: quem
    reabre e o turno, e ele so roda quando chega mensagem. Ate la a linha fica
    como estava, e esta funcao ja conta a verdade.

    `agora` entra por parametro, e nao de `datetime.now()` aqui dentro, pelo
    mesmo motivo que `e_conversa_nova` o recebe: e o que torna a janela
    testavel sem congelar relogio.

    **Empate em exatamente 30 dias resolvido para o lado fechado**, com `<=`
    e nao `<`: exatamente 30 dias ainda esta encerrada, e reabre so depois
    disso. E o mesmo lado que `e_conversa_nova` escolhe para o empate dela --
    "exatamente 30 dias ainda nao abre conversa nova" -- e tem de ser, porque
    as duas funcoes compartilham `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`: se
    esta reabrisse no instante exato em que `e_conversa_nova` ainda considera
    silencio, a reabertura e a identificacao de conversa nova deixariam de
    coincidir, que e o motivo de as duas usarem a mesma constante. Deixar o
    empate ao acaso e o defeito que a TEC-229 documentou.
    """
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.encerrada_em).where(
                Conversa.channel == channel,
                Conversa.conversation_key == conversation_key,
            )
        )
    ).one_or_none()
    if linha is None or linha.status != Status.ENCERRADA or linha.encerrada_em is None:
        return False
    return agora - linha.encerrada_em <= timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)


async def reabrir_conversa(session: AsyncSession, *, channel: str, conversation_key: str) -> None:
    """Volta a conversa para ATIVA e limpa motivo e carimbo.

    Nao zera o contador de fora de escopo: ele ja esta em zero desde o
    encerramento, e essa e a razao de o encerramento o zerar. Ver o comentario
    da coluna em `agente/models.py`.
    """
    await session.execute(
        update(Conversa)
        .where(Conversa.channel == channel, Conversa.conversation_key == conversation_key)
        # `str(...)` pela mesma razao do `valores` de `encerrar_conversa`
        # acima: `Status` e StrEnum, e gravar o literal mantem a coluna no
        # mesmo formato dos dois lados.
        .values(status=str(Status.ATIVA), motivo_do_encerramento=None, encerrada_em=None)
    )
