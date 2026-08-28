import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.models import ConversationSummary, LeadQualification, aad_do_resumo
from mobia.infra.crypto import decrypt, encrypt


@dataclass(frozen=True)
class ResumoDaConversa:
    """O resumo ja decifrado, com a marca do que ele cobre."""

    texto: str
    watermark_created_at: datetime
    watermark_message_id: uuid.UUID
    mensagens_cobertas: int
    modelo: str


async def ler_resumo(
    session: AsyncSession, channel: str, conversation_key: str
) -> ResumoDaConversa | None:
    linha = await session.get(ConversationSummary, (channel, conversation_key))
    if linha is None:
        return None
    texto = decrypt(bytes(linha.resumo), aad_do_resumo(channel, conversation_key))
    if texto is None:
        # `assert` some sob `python -O` e o dataclass sairia com `texto=None`
        # contra a propria anotacao, para o prompt e para a contagem. A coluna
        # e NOT NULL, entao chegar aqui e garantia quebrada -- falhar alto.
        raise ValueError("resumo decifrou como nulo, mas a coluna e NOT NULL")
    return ResumoDaConversa(
        texto=texto,
        watermark_created_at=linha.watermark_created_at,
        watermark_message_id=linha.watermark_message_id,
        mensagens_cobertas=linha.mensagens_cobertas,
        modelo=linha.modelo,
    )


async def gravar_resumo(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    texto: str,
    watermark_created_at: datetime,
    watermark_message_id: uuid.UUID,
    mensagens_cobertas: int,
    modelo: str,
) -> None:
    """Upsert: uma conversa tem um resumo, nao um historico deles.

    Nao commita -- a sessao e emprestada, como em `ler_resumo` e `ler_estado`,
    e quem chama e dono da fronteira da transacao. Isso importa a partir da
    TEC-145: gravar o resumo junto com outro estado na mesma transacao exige
    que nada aqui a feche antes da hora.
    """
    cifrado = encrypt(texto, aad_do_resumo(channel, conversation_key))
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "resumo": cifrado,
        "watermark_created_at": watermark_created_at,
        "watermark_message_id": watermark_message_id,
        "mensagens_cobertas": mensagens_cobertas,
        "modelo": modelo,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationSummary).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in (
                    "resumo",
                    "watermark_created_at",
                    "watermark_message_id",
                    "mensagens_cobertas",
                    "modelo",
                    "updated_at",
                )
            },
            # Guarda de monotonia: a marca so anda para frente. Dois turnos
            # concorrentes da mesma conversa leem o mesmo estado, dobram e
            # gravam; sem esta condicao o mais lento sobrescreve o mais rapido,
            # a marca recua e as mensagens entre as duas marcas sao dobradas
            # duas vezes -- conteudo duplicado no resumo, para sempre. `<=` e
            # nao `<` porque a compressao regrava a mesma marca de proposito:
            # ela so encurta o texto, nao cobre mensagem nova.
            where=ConversationSummary.watermark_created_at
            <= statement.excluded.watermark_created_at,
        )
    )


async def ler_estado(
    session: AsyncSession, channel: str, conversation_key: str
) -> LeadQualification | None:
    resultado = await session.execute(
        select(LeadQualification).where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
    )
    return resultado.scalar_one_or_none()


async def gravar_estado(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    extracao: Extracao,
) -> None:
    """Upsert do estado de qualificacao. `None` no campo nao apaga o que havia.

    Nao commita -- a sessao e emprestada, como em `ler_resumo`, `ler_estado` e
    `gravar_resumo`, e quem chama e dono da fronteira da transacao. Nesta card
    quem chama e `executar_turno`, que grava intencao e estado no **mesmo**
    commit: os dois fatos vem da mesma chamada ao modelo.

    `FORA_DE_ESCOPO` nao grava nada, e a guarda vive aqui e nao em quem chama
    para que nao haja como esquece-la. Repare que ela tambem nao **apaga**: o
    lead que qualificou e depois mandou uma piada continua com o que disse.

    `intencao` vem de fora, do classificador, e nunca da extracao: a tabela
    `conversation_intent` e esta coluna guardam o mesmo fato, e duas fontes
    para ele divergiriam -- a divergencia apareceria como bug de score na
    TEC-150.
    """
    if intencao is Intencao.FORA_DE_ESCOPO:
        return

    # A regra de "null nao apaga" mora aqui: so os campos informados entram no
    # INSERT e no SET. Um dicionario completo com `None` nos campos calados
    # sobrescreveria com NULL a cada turno, e o estado nunca acumularia nada.
    preenchidos = extracao.preenchidos()
    valores: dict[str, Any] = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": intencao.value,
        "updated_at": datetime.now(UTC),
        **preenchidos,
    }
    statement = pg_insert(LeadQualification).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in (*preenchidos, "intencao", "updated_at")
            },
        )
    )
