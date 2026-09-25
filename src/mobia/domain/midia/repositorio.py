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
) -> bool:
    """Muda o status (e o que mais o job souber) e carimba `atualizado_em`.

    Devolve se a linha de fato mudou. `motivo`, `chave` e `tamanho` sempre
    sobrescrevem, mesmo com None: toda transicao desta tabela sai de PENDENTE
    para um estado terminal (D2), entao nao ha caso em que um campo gravado
    antes precise sobreviver a um `marcar` que de fato aconteceu.

    **O UPDATE repete `status = PENDENTE` no proprio WHERE, e nao confia em
    quem chama ja ter checado isso antes.** E a mesma razao de
    `escalar_vencidos` (`domain/handoff/escalada.py`) repetir a condicao do
    SELECT no UPDATE: sem ela, um job de download que so termina (sucesso ou
    falha) depois que `expirar_pendentes` ja fechou a linha como
    FALHOU/EXPIRADA reabriria um estado terminal em silencio -- a mesma
    corrida, so que contra o sweep em vez de contra outra rota. Quem arbitra
    e o banco: o `rowcount` do UPDATE e que diz se esta chamada venceu a
    corrida, e o `False` devolvido e o sinal para quem chama logar a corrida
    perdida em vez de seguir como se tivesse gravado.
    """
    async with session_factory() as session:
        resultado = cast(
            CursorResult[Any],
            await session.execute(
                update(MidiaRecebida)
                .where(
                    MidiaRecebida.message_id == message_id,
                    MidiaRecebida.status == StatusDaMidia.PENDENTE,
                )
                .values(
                    status=status,
                    motivo=motivo,
                    chave_no_armazem=chave,
                    bytes=tamanho,
                    atualizado_em=datetime.now(UTC),
                )
            ),
        )
        await session.commit()
        return resultado.rowcount > 0


async def pendentes_para_reenfileirar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    mais_velhas_que: timedelta,
    mais_novas_que: timedelta,
    teto: int,
    limite: int,
) -> list[uuid.UUID]:
    """Reivindica as PENDENTE na janela de reenfileiramento (D3), contando a
    tentativa de cada uma, e devolve quais.

    A janela: velhas o bastante para supor que o enfileiramento original se
    perdeu, novas o bastante para a midia da Meta ainda existir. Fora da
    janela pelos dois lados fica de fora -- as mais novas porque o job pode so
    estar em voo, as mais velhas porque `expirar_pendentes` e quem trata
    essas. E so as abaixo do `teto` de `tentativas`: as que chegaram nele sao
    de `esgotar_pendentes`.

    **Conta ao reivindicar, num UPDATE so, e nao depois do enqueue.** O
    `tentativas + 1` e expressao SQL com `RETURNING`, entao duas passadas
    concorrentes nunca leem o mesmo valor e somam um so. O preco e contar
    tambem a passada em que o enqueue nao criou job novo (o `_job_id` ainda
    estava na fila, ou o Redis falhou) -- o contador mede passadas que
    tentaram, e nao jobs que rodaram. E o lado certo do erro para um teto que
    existe para limitar chamadas a Graph API: ele nunca deixa passar mais do
    que promete.
    """
    agora = datetime.now(UTC)
    reivindicaveis = (
        select(MidiaRecebida.message_id)
        .where(MidiaRecebida.status == StatusDaMidia.PENDENTE)
        .where(MidiaRecebida.tentativas < teto)
        .where(MidiaRecebida.criado_em <= agora - mais_velhas_que)
        .where(MidiaRecebida.criado_em >= agora - mais_novas_que)
        # `message_id` como desempate: linhas gravadas na mesma transacao
        # (mesmo lote de ingestao) podem cair no mesmo `criado_em`, e sem
        # um segundo criterio a ordem entre elas fica ao sabor do plano de
        # execucao -- o `limite` cortaria um subconjunto nao determinista.
        .order_by(MidiaRecebida.criado_em, MidiaRecebida.message_id)
        .limit(limite)
    )
    async with session_factory() as session:
        linhas = await session.execute(
            update(MidiaRecebida)
            .where(MidiaRecebida.message_id.in_(reivindicaveis.scalar_subquery()))
            # Repetido do subselect pela mesma razao de `marcar`: quem arbitra
            # e o WHERE do proprio UPDATE, e nao a leitura que o precedeu.
            .where(MidiaRecebida.status == StatusDaMidia.PENDENTE)
            .where(MidiaRecebida.tentativas < teto)
            .values(tentativas=MidiaRecebida.tentativas + 1)
            .returning(MidiaRecebida.criado_em, MidiaRecebida.message_id)
        )
        reivindicadas = linhas.all()
        await session.commit()
    # `RETURNING` nao preserva a ordem do subselect; a ordem de enfileirar e
    # a mesma do corte do `limite`, as mais velhas primeiro.
    return [message_id for _, message_id in sorted(reivindicadas)]


async def esgotar_pendentes(session_factory: async_sessionmaker[AsyncSession], *, teto: int) -> int:
    """Fecha como FALHOU/TENTATIVAS_ESGOTADAS as PENDENTE que ja foram
    re-enfileiradas `teto` vezes. Devolve quantas fechou.

    Mesmo motivo que o job usa para o `Retry` esgotado, de proposito: para
    quem le a linha, "tentou e nao conseguiu" e a mesma historia, venha o
    limite do ARQ ou da varredura. Um job da ultima reivindicacao que so
    termine depois disto perde a corrida em `marcar`, como perde contra
    `expirar_pendentes`.
    """
    async with session_factory() as session:
        resultado = cast(
            CursorResult[Any],
            await session.execute(
                update(MidiaRecebida)
                .where(MidiaRecebida.status == StatusDaMidia.PENDENTE)
                .where(MidiaRecebida.tentativas >= teto)
                .values(
                    status=StatusDaMidia.FALHOU,
                    motivo=MotivoDaMidia.TENTATIVAS_ESGOTADAS,
                    atualizado_em=datetime.now(UTC),
                )
            ),
        )
        await session.commit()
        return resultado.rowcount


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
