"""A lista de leads do painel. TEC-192, RF-18, RN-18.1 e secao 6.2 do SRS.

**Nao existe ENTIDADE lead (D2 do desenho da TEC-192).** O SRS escreve
`"id": "uuid"`, e essa entidade nao existe neste sistema -- o lead e o par
`(channel, conversation_key)`, o mesmo que `handoffs`, `optout_events` e
`lead_qualification` ja usam. Mesma decisao da D9 da TEC-179, que recusou o
`{conversaId}` pela mesma razao. Vira a Emenda E-01 a secao 6.2.

**Nao ha `nome` na resposta**: nenhuma tabela deste sistema guarda o nome do
lead (Emenda E-02 da RN-15.1). E lacuna declarada, nao esquecimento.

**O `conversationKey` SAIU da resposta na TEC-195, e no lugar dele ha
`leadId`.** No WhatsApp aquele campo E o telefone do lead, e ele saia em claro
-- no item e, por base64, no `proximoCursor` -- para todo papel com
`VER_LEADS`, inclusive CORRETOR e LEITURA, que nao tem `VER_DADOS_COMPLETOS`.
O comentario da TEC-206 em `handoffs.py` ja nomeava esse furo: "`GET
/api/v1/leads` devolve a mesma chave sem registro nenhum".

**Isto revisita a D2 acima**, e nao a contradiz. Continua nao existindo
ENTIDADE lead; `referencias_de_lead` e um apelido do par, sem atributo
proprio, no mesmo espirito do `lead_ref` que a trilha guarda. Ver a docstring
da migration 0056.

**`telefone` sai mascarado para TODO chamador**, inclusive para quem tem
`VER_DADOS_COMPLETOS` (D4). Nao ha ramo por papel nesta rota, e nao deve haver:
o unico lugar do sistema que devolve o numero cheio e `revelar`, abaixo, que
registra na trilha antes de responder.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import CAMPOS_REVELAVEIS, Acao, Entidade
from mobia.domain.leads.consulta import (
    LIMITE_PADRAO,
    FiltroInvalido,
    RecorteDoPapel,
    montar_filtro,
)
from mobia.domain.leads.repositorio import (
    e_lead_do_corretor,
    listar_leads,
    par_de,
    valor_revelado,
)
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
        try:
            itens, proximo = await listar_leads(
                session,
                filtro=filtro,
                recorte=RecorteDoPapel(
                    e_corretor=identidade.e_corretor, corretor_id=identidade.corretor_id
                ),
            )
        except FiltroInvalido as erro:
            # O segundo `FiltroInvalido` desta rota, e ele nao cabia no
            # `montar_filtro` acima: o cursor da TEC-195 carrega um apelido, e
            # so o banco sabe se ele existe. Mesmo 422, mesma razao -- quem
            # chamou perdeu o lugar, e a primeira pagina em silencio se leria
            # como a continuacao.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
            ) from erro
        # Os apelidos criados por `listar_leads` so existem depois do commit --
        # o cursor devolvido aponta para um deles, e a pagina seguinte nao
        # resolveria.
        await session.commit()

    return {
        "itens": [
            {
                "leadId": str(lead.lead_id),
                "channel": lead.channel,
                "telefone": lead.telefone,
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


class PedidoDeRevelacao(BaseModel):
    """O campo que se quer ler. Vocabulario fechado, conferido pela rota."""

    campo: str


@router.post("/{lead_id}/revelar")
async def revelar(
    lead_id: uuid.UUID,
    pedido: PedidoDeRevelacao,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_DADOS_COMPLETOS)),
) -> dict[str, object]:
    """O unico lugar do sistema que devolve dado pessoal de lead em claro.

    **`POST` e nao `GET`, e isto nao e gosto:** a chamada tem efeito -- ela
    grava uma linha de auditoria. Um `GET` que escreve e repetido por proxy e
    disparado por pre-fetch, e a trilha passaria a registrar acessos que
    ninguem pediu.

    **`VER_DADOS_COMPLETOS` passou a ser exigencia de ROTA aqui** (TEC-195,
    D4). Ate a TEC-202 ela era descrita como capacidade consultada dentro de um
    handler; a lista deixou de consulta-la porque mascara para todo mundo, e
    quem a exige e esta rota.

    **O CORRETOR so revela o proprio lead.** Sem isto, a revelacao seria a
    porta dos fundos do recorte que a lista aplica -- bastaria enumerar
    apelidos. Como ele nao tem a permissao pela matriz de `permissoes_de`, hoje
    o `Exige` ja o barra antes daqui; a checagem fica escrita para o dia em que
    a matriz mudar, que e quando o furo nasceria em silencio.

    **A trilha e gravada e COMITADA antes do valor sair.** Se a escrita falhar,
    a resposta e erro e o numero nao vai embora sem registro. Registra a
    TENTATIVA, de proposito: a linha entra antes de o valor ser montado. Molde
    de `handoffs.py::resumo` (TEC-206, D1 e D7).

    O valor revelado NAO vai para a trilha: ela diz qual campo foi lido, nunca
    o que ele dizia.
    """
    if pedido.campo not in CAMPOS_REVELAVEIS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"campo nao revelavel: {pedido.campo}",
        )

    async with get_sessionmaker()() as session:
        par = await par_de(session, lead_id)
        if par is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")

        if identidade.e_corretor and not await e_lead_do_corretor(
            session, par=par, corretor_id=identidade.corretor_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="lead de outro corretor"
            )

        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADO_PESSOAL_ACESSADO,
            entidade=Entidade.LEAD,
            # O apelido, e NUNCA o par: gravar o par seria gravar o telefone,
            # que e o que a D4 da TEC-206 proibiu. Quem pesquisa a trilha por
            # lead usa `lead_ref`, que o `lead=` abaixo produz.
            entidade_id=str(lead_id),
            campo=pedido.campo,
            lead=par,
            origem=origem_da_requisicao(request),
        )
        await session.commit()

        valor = await valor_revelado(session, par=par, campo=pedido.campo)

    return {"campo": pedido.campo, "valor": valor}
