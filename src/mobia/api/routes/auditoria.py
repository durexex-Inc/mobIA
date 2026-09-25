"""A trilha de auditoria, so para leitura. TEC-206, D8 do desenho; tela na TEC-343.

**So `GET`, e so do ADMIN** (`VER_AUDITORIA`). A rota nao tem outro metodo,
entao "nao ha opcao de editar nem de excluir" vale tambem na API -- e, por
baixo dela, o trigger da 0053 recusa as duas coisas de qualquer caminho.

**A leitura da trilha nao e auditada** nesta card: seria um registro por
registro lido. Se precisar ser, e decisao da TEC-343.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.auditoria.consulta import montar_filtro
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.repositorio import listar_eventos
from mobia.domain.leads.consulta import LIMITE_PADRAO, FiltroInvalido
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/auditoria", tags=["auditoria"])


def _item(evento: EventoAuditoria) -> dict[str, Any]:
    """Um registro para a tela. **`leadRef` nao sai**: e chave de busca, nao
    informacao para exibir."""
    return {
        "id": str(evento.id),
        "criadoEm": evento.criado_em.isoformat(),
        "atorTipo": evento.ator_tipo,
        "atorId": evento.ator_id,
        "acao": evento.acao,
        "entidade": evento.entidade,
        "entidadeId": evento.entidade_id,
        "campo": evento.campo,
        "detalhes": evento.detalhes,
        # O asyncpg devolve `ipaddress.IPv4Address`/`IPv6Address`.
        "ip": str(evento.ip) if evento.ip is not None else None,
        "correlationId": evento.correlation_id,
    }


@router.get("")
async def listar(
    ator: Annotated[str | None, Query(max_length=64)] = None,
    acao: Annotated[list[str] | None, Query()] = None,
    de: Annotated[datetime | None, Query()] = None,
    ate: Annotated[datetime | None, Query()] = None,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    conversation_key: Annotated[str | None, Query(alias="conversationKey", max_length=64)] = None,
    limite: Annotated[int, Query()] = LIMITE_PADRAO,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_AUDITORIA)),
) -> dict[str, object]:
    """A trilha do mais recente ao mais antigo, filtrada e paginada por cursor.

    Filtros opcionais e combinaveis; `de`/`ate` e o intervalo semiaberto
    `[de, ate)`. Filtro invalido e 422, na convencao da TEC-192. Trilha vazia
    e 200 com `itens` vazio.
    """
    try:
        filtro = montar_filtro(
            ator=ator,
            acoes=tuple(acao or ()),
            de=de,
            ate=ate,
            channel=channel,
            conversation_key=conversation_key,
            limite=limite,
            cursor=cursor,
            chave_do_lead=get_settings().auditoria_chave_do_lead,
        )
    except FiltroInvalido as erro:
        # `UNPROCESSABLE_CONTENT` pela mesma razao de `routes/leads.py`.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        eventos, proximo = await listar_eventos(session, filtro=filtro)

    return {
        "itens": [_item(evento) for evento in eventos],
        "proximoCursor": proximo.codificar() if proximo else None,
    }
