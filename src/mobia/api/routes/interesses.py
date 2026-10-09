"""Os pedidos de interesse do portal no painel. TEC-404.

`GET` lista (D8), guardada por `VER_LEADS`; o CORRETOR ve so os pedidos cujo
atendimento (D4) e dele, pelo mesmo `RecorteDoPapel` de `/leads`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.domain.leads.consulta import RecorteDoPapel
from mobia.domain.portal.pedidos import (
    CursorInvalido,
    Estado,
    PedidoDaLista,
    decodificar_cursor,
    listar_pedidos,
)
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/interesses", tags=["interesses"])

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 100


def _item(pedido: PedidoDaLista) -> dict[str, object]:
    atendimento = pedido.atendimento
    return {
        "id": str(pedido.id),
        "criadoEm": pedido.criado_em.isoformat(),
        "imovel": {
            "id": str(pedido.imovel_id),
            "codigo": pedido.imovel_codigo,
            "titulo": pedido.imovel_titulo,
        },
        "nome": pedido.nome,
        "telefoneMascarado": pedido.telefone_mascarado,
        "emailMascarado": pedido.email_mascarado,
        "leadId": str(pedido.lead_id),
        "atendimento": None
        if atendimento is None
        else {
            "id": str(atendimento.id),
            "status": atendimento.status,
            "corretor": None
            if atendimento.corretor_id is None
            else {"id": str(atendimento.corretor_id), "nome": atendimento.corretor_nome},
            "notificadoEm": atendimento.notificado_em.isoformat()
            if atendimento.notificado_em
            else None,
            "semCorretor": atendimento.sem_corretor,
        },
    }


@router.get("")
async def listar(
    estado: Annotated[Estado, Query()] = Estado.PENDENTES,
    limite: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
    cursor: Annotated[str | None, Query()] = None,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Os pedidos do mais recente ao mais antigo. Sem `total`, como `/leads`.

    `estado` fora do vocabulario e `limite` fora de 1..100 sao 422 pela propria
    validacao do FastAPI; cursor adulterado e 422 com `cursor invalido`, e nao
    a primeira pagina em silencio.
    """
    try:
        posicao = decodificar_cursor(cursor) if cursor else None
    except CursorInvalido as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="cursor invalido"
        ) from erro

    async with get_sessionmaker()() as session:
        pagina, proximo = await listar_pedidos(
            session,
            estado=estado,
            limite=limite,
            cursor=posicao,
            recorte=RecorteDoPapel(
                e_corretor=identidade.e_corretor, corretor_id=identidade.corretor_id
            ),
        )
        # `referencias_para` cria apelidos que so existem depois do commit --
        # mesma razao de `leads.py::listar`: o `leadId` devolvido tem de
        # resolver na proxima requisicao.
        await session.commit()

    return {
        "itens": [_item(p) for p in pagina],
        "proximoCursor": proximo.codificar() if proximo else None,
    }
