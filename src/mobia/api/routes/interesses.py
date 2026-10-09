"""Os pedidos de interesse do portal no painel. TEC-404.

`GET` lista (D8), guardada por `VER_LEADS`; o CORRETOR ve so os pedidos cujo
atendimento (D4) e dele, pelo mesmo `RecorteDoPapel` de `/leads`.

`POST /{id}/revelar` (D5) devolve telefone ou e-mail em claro, com a trilha
comitada antes.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono, registrar_negativa
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import CAMPOS_REVELAVEIS, Acao, Entidade
from mobia.domain.leads.consulta import RecorteDoPapel
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.portal.pedidos import (
    CursorInvalido,
    Estado,
    PedidoDaLista,
    atendimento_do_pedido,
    decodificar_cursor,
    listar_pedidos,
    valor_do_pedido,
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


class PedidoDeRevelacao(BaseModel):
    """O campo que se quer ler. Vocabulario fechado, conferido pela rota."""

    campo: str


@router.post("/{solicitacao_id}/revelar")
async def revelar(
    solicitacao_id: uuid.UUID,
    pedido: PedidoDeRevelacao,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Telefone ou e-mail do pedido, em claro (D5).

    Guardada por `VER_LEADS`, e nao por `VER_DADOS_COMPLETOS`: a regra e mais
    fina que uma permissao e mora no corpo. Quem tem `VER_DADOS_COMPLETOS`
    revela qualquer pedido; o CORRETOR, so os cujo handoff (D4) e dele
    (decisao 5 da card). O resto e 403, com `ACESSO_NEGADO` na trilha.

    **A trilha e COMITADA antes de o valor sair**, molde de
    `leads.py::revelar`: se a escrita falhar, a resposta e erro e o numero nao
    vai embora sem registro. O valor revelado nao entra na trilha, so o campo.
    """
    if pedido.campo not in CAMPOS_REVELAVEIS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"campo nao revelavel: {pedido.campo}",
        )

    async with get_sessionmaker()() as session:
        encontrado = await atendimento_do_pedido(session, solicitacao_id)
        if encontrado is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pedido nao existe")
        solicitacao, handoff = encontrado

        if not identidade.pode(Permissao.VER_DADOS_COMPLETOS):
            if not identidade.e_corretor:
                await registrar_negativa(
                    request, Permissao.VER_DADOS_COMPLETOS, identidade=identidade
                )
                # Mesmo detalhe de `autorizacao.py::_negar`.
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
            await exigir_dono(
                request,
                identidade,
                permissao=Permissao.VER_LEADS,
                corretor_id=handoff.corretor_id if handoff is not None else None,
            )

        par = (solicitacao.channel, solicitacao.conversation_key)
        apelido = (await referencias_para(session, [par]))[par]
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADO_PESSOAL_ACESSADO,
            # O apelido, nunca o par: o par carrega o telefone (D4 da TEC-206).
            entidade=Entidade.LEAD,
            entidade_id=str(apelido),
            campo=pedido.campo,
            lead=par,
            origem=origem_da_requisicao(request),
        )
        await session.commit()

        valor = await valor_do_pedido(session, solicitacao, pedido.campo)

    return {"campo": pedido.campo, "valor": valor}
