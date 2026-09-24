"""O ciclo de status da midia recebida. TEC-132, D2 e D3."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia

# O vocabulario cru da Meta que carrega midia, por tipo. So estas duas chaves:
# audio e a TEC-131, e o resto continua DESCONHECIDO (D2).
_CHAVE_DO_ENVELOPE = {MessageContentType.IMAGEM: "image", MessageContentType.DOCUMENTO: "document"}


def linha_pendente(
    message_id: uuid.UUID, raw_payload: dict[str, Any], content_type: MessageContentType
) -> dict[str, Any] | None:
    """Monta o `values` do INSERT em `midias_recebidas` a partir do envelope.

    Devolve None quando nao ha o que gravar: tipo que nao carrega midia, ou
    envelope sem `id` -- a Meta manda isso quando so a legenda chegou sem o
    anexo, e sem `id` nao ha `media_id` para o job baixar depois.
    """
    chave = _CHAVE_DO_ENVELOPE.get(content_type)
    if chave is None:
        return None
    midia = raw_payload.get(chave) or {}
    media_id = midia.get("id")
    if not media_id:
        # Envelope sem id nao tem o que baixar. A mensagem existe e o turno
        # confirma do mesmo jeito; so nao ha ponteiro a guardar.
        return None
    return {
        "message_id": message_id,
        "media_id_da_meta": str(media_id),
        "mime_type": str(midia.get("mime_type") or ""),
        "sha256": midia.get("sha256"),
        "status": StatusDaMidia.PENDENTE,
    }


async def ler_midia(session: AsyncSession, message_id: uuid.UUID) -> MidiaRecebida | None:
    return await session.get(MidiaRecebida, message_id)


async def marcar(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: uuid.UUID,
    *,
    status: StatusDaMidia,
    motivo: MotivoDaMidia | None = None,
    chave: str | None = None,
    tamanho: int | None = None,
) -> None:
    """Muda o status (e o que mais o job souber) e carimba `atualizado_em`.

    `motivo`, `chave` e `tamanho` sempre sobrescrevem, mesmo com None: cada
    transicao desta tabela e terminal ou para PENDENTE nunca mais (D2), entao
    nao ha caso em que um campo gravado antes precise sobreviver a um `marcar`
    seguinte.
    """
    async with session_factory() as session:
        await session.execute(
            update(MidiaRecebida)
            .where(MidiaRecebida.message_id == message_id)
            .values(
                status=status,
                motivo=motivo,
                chave_no_armazem=chave,
                bytes=tamanho,
                atualizado_em=datetime.now(UTC),
            )
        )
        await session.commit()


async def pendentes_para_reenfileirar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    mais_velhas_que: timedelta,
    mais_novas_que: timedelta,
    limite: int,
) -> list[uuid.UUID]:
    """As PENDENTE na janela de reenfileiramento (D3): velhas o bastante para
    supor que o enfileiramento original se perdeu, novas o bastante para a
    midia da Meta ainda existir. Fora da janela pelos dois lados fica de fora
    -- as mais novas porque o job pode so estar em voo, as mais velhas porque
    `expirar_pendentes` e quem trata essas.
    """
    agora = datetime.now(UTC)
    async with session_factory() as session:
        linhas = await session.execute(
            select(MidiaRecebida.message_id)
            .where(MidiaRecebida.status == StatusDaMidia.PENDENTE)
            .where(MidiaRecebida.criado_em <= agora - mais_velhas_que)
            .where(MidiaRecebida.criado_em >= agora - mais_novas_que)
            .order_by(MidiaRecebida.criado_em)
            .limit(limite)
        )
        return list(linhas.scalars().all())


async def expirar_pendentes(
    session_factory: async_sessionmaker[AsyncSession], *, mais_velhas_que: timedelta
) -> int:
    """Fecha como FALHOU/EXPIRADA as PENDENTE velhas demais para reenfileirar.

    Devolve quantas linhas fechou. Depois disso elas nao aparecem mais em
    `pendentes_para_reenfileirar`, porque deixam de estar PENDENTE.
    """
    agora = datetime.now(UTC)
    async with session_factory() as session:
        resultado = cast(
            CursorResult[Any],
            await session.execute(
                update(MidiaRecebida)
                .where(MidiaRecebida.status == StatusDaMidia.PENDENTE)
                .where(MidiaRecebida.criado_em < agora - mais_velhas_que)
                .values(
                    status=StatusDaMidia.FALHOU,
                    motivo=MotivoDaMidia.EXPIRADA,
                    atualizado_em=agora,
                )
            ),
        )
        await session.commit()
        return resultado.rowcount
