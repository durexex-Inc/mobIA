"""A lista de leads do painel. TEC-192, RF-18, RN-18.1 e secao 6.2 do SRS.

**Nao existe `leadId` (D2 do desenho).** O SRS escreve `"id": "uuid"`, e essa
entidade nao existe neste sistema -- o lead e o par `(channel,
conversation_key)`, o mesmo que `handoffs`, `optout_events` e
`lead_qualification` ja usam. Mesma decisao da D9 da TEC-179, que recusou o
`{conversaId}` pela mesma razao. Vira a Emenda E-01 a secao 6.2.

**E nao ha `nome` nem `telefone` na resposta**, os dois por motivos diferentes:
nenhuma tabela deste sistema guarda o nome do lead (Emenda E-02 da RN-15.1), e
o telefone so poderia sair mascarado, o que e a TEC-195. Sao lacunas
declaradas, nao esquecimento.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.domain.leads.consulta import (
    LIMITE_PADRAO,
    FiltroInvalido,
    RecorteDoPapel,
    montar_filtro,
)
from mobia.domain.leads.repositorio import listar_leads
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])


@router.get("")
async def listar(
    busca: Annotated[str | None, Query()] = None,
    status_da_conversa: Annotated[str | None, Query(alias="status")] = None,
    temperatura: Annotated[str | None, Query()] = None,
    canal: Annotated[str | None, Query()] = None,
    corretor_id: Annotated[uuid.UUID | None, Query(alias="corretorId")] = None,
    limite: Annotated[int, Query()] = LIMITE_PADRAO,
    cursor: Annotated[str | None, Query()] = None,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Os leads em ordem decrescente de score, paginados por cursor.

    **O papel CORRETOR recebe a consulta ja recortada pelo proprio vinculo**, e
    o recorte vem da claim do JWT, nunca da query (D7). Mandar
    `corretorId=<outro>` nao alarga nada: os dois viram `AND`. Nao e 403
    porque a tela legitimamente manda o filtro que o usuario escolheu, e
    recusa-lo faria a combinacao "sou corretor e filtrei por mim" quebrar.

    **`CORRETOR` sem vinculo recebe lista vazia**, pelo mesmo argumento da D4
    da TEC-202: cadastro incompleto nao e passe livre.

    **Sem `total`**, que o exemplo do SRS traz. Conta-lo exigiria repetir a
    agregacao de `messages` inteira numa segunda consulta por requisicao, para
    produzir um numero que a tela usa so para dizer "de 143" -- e o cursor ja
    responde a unica pergunta que muda comportamento, que e "ha proxima
    pagina?". Se alguem precisar do total, ele merece medicao propria.

    Base sem lead nenhum devolve 200 com `itens` vazio, nunca 404: ausencia de
    lead e fato sobre o negocio, nao sobre a rota. Mesma decisao do funil.
    """
    try:
        filtro = montar_filtro(
            busca=busca,
            status=status_da_conversa,
            temperatura=temperatura,
            canal=canal,
            corretor_id=corretor_id,
            limite=limite,
            cursor=cursor,
        )
    except FiltroInvalido as erro:
        # `UNPROCESSABLE_CONTENT` e nao `UNPROCESSABLE_ENTITY`: o segundo esta
        # deprecado nesta versao do Starlette e emite warning a cada chamada.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        itens, proximo = await listar_leads(
            session,
            filtro=filtro,
            recorte=RecorteDoPapel(
                e_corretor=identidade.e_corretor, corretor_id=identidade.corretor_id
            ),
        )

    return {
        "itens": [
            {
                "channel": lead.channel,
                "conversationKey": lead.conversation_key,
                "score": lead.score,
                "temperatura": lead.temperatura,
                "status": lead.status,
                "regiao": lead.regiao,
                "intencao": lead.intencao,
                "qualificadoEm": lead.qualificado_em.isoformat() if lead.qualificado_em else None,
                "ultimaInteracaoEm": lead.ultima_interacao_em.isoformat(),
            }
            for lead in itens
        ],
        "proximoCursor": proximo.codificar() if proximo else None,
    }
