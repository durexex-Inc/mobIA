"""A lista de leads do painel. TEC-192, RF-18, RN-18.1 e secao 6.2 do SRS.

**Nao existe ENTIDADE lead (D2 do desenho da TEC-192).** O SRS escreve
`"id": "uuid"`, e essa entidade nao existe neste sistema -- o lead e o par
`(channel, conversation_key)`, o mesmo que `handoffs`, `optout_events` e
`lead_qualification` ja usam. Mesma decisao da D9 da TEC-179, que recusou o
`{conversaId}` pela mesma razao. Vira a Emenda E-01 a secao 6.2.

**Nao ha `nome` na resposta**: nenhuma tabela deste sistema guarda o nome do
lead (Emenda E-02 da RN-15.1). E lacuna declarada, nao esquecimento.

**O `conversationKey` SAIU da resposta na TEC-195, e no lugar dele ha
`leadId`.** No WhatsApp aquele campo ERA o telefone do lead, e ele saia em claro
-- no item e, por base64, no `proximoCursor` -- para todo papel com
`VER_LEADS`, inclusive CORRETOR e LEITURA, que nao tem `VER_DADOS_COMPLETOS`.
O comentario da TEC-206 em `handoffs.py` ja nomeava esse furo. Desde a
TEC-203 o `conversation_key` e o HMAC do telefone (`identidade/indice.py`), e
nao o telefone; o `leadId` continua sendo o que a resposta devolve.

**Isto revisita a D2 acima**, e nao a contradiz. Continua nao existindo
ENTIDADE lead; `referencias_de_lead` e um apelido do par, sem atributo
proprio, no mesmo espirito do `lead_ref` que a trilha guarda. Ver a docstring
da migration 0056.

**`telefone` sai mascarado para TODO chamador**, inclusive para quem tem
`VER_DADOS_COMPLETOS` (D4). Nao ha ramo por papel nesta rota, e nao deve haver:
o unico lugar do sistema que devolve o numero cheio e `revelar`, abaixo, que
registra na trilha antes de responder.

**O detalhe e a transcricao sao `GET` que registram** (TEC-193, D3). Abrir a
tela e o acesso, e o registro e comitado antes de o conteudo sair -- o molde de
`revelar`, sem o `POST`. Ver `_abrir_para_leitura`.

**A excecao e o polling** (`?depois=`, TEC-327, D1): ele so registra quando
traz fala, porque poll vazio nao entrega conteudo. Decisao do Eduardo,
27/09/2026. Ver `_posteriores`.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import (
    CAMPO_DETALHE,
    CAMPO_TRANSCRICAO,
    CAMPOS_REVELAVEIS,
    Acao,
    Entidade,
)
from mobia.domain.leads.consulta import (
    LIMITE_PADRAO,
    FiltroInvalido,
    RecorteDoPapel,
    montar_filtro,
)
from mobia.domain.leads.detalhe import DetalheDoLead, ler_detalhe
from mobia.domain.leads.repositorio import (
    e_lead_do_corretor,
    listar_leads,
    par_de,
    valor_revelado,
)
from mobia.domain.leads.transcricao import (
    LIMITE_PADRAO_DA_TRANSCRICAO,
    CursorDaTranscricao,
    Fala,
    cursor_posterior,
    decodificar_cursor_da_transcricao,
    pagina_da_transcricao,
    posteriores_da_transcricao,
    validar_limite_da_transcricao,
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
    ordenar: Annotated[str | None, Query()] = None,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_LEADS)),
) -> dict[str, object]:
    """Os leads em ordem decrescente de score, paginados por cursor.

    **Ou pela ultima interacao, com `ordenar=ultima_interacao_desc`** (TEC-321,
    D4). A tela precisa das duas ordens, e ordenar no cliente reordenaria so a
    pagina recebida. Valor fora do vocabulario e 422, e nao a ordem padrao.

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
            ordenar=ordenar,
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


async def _abrir_para_leitura(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    campo: str,
    request: Request,
    identidade: IdentidadeDaRequisicao,
) -> tuple[str, str]:
    """404, depois o recorte do CORRETOR, depois o registro COMITADO. TEC-193.

    **A ordem e a D2 e a D3 do desenho.** O apelido inexistente e 404 para
    todo papel; o CORRETOR que pede o lead de outro leva 403 e `ACESSO_NEGADO`
    antes de qualquer consulta ao conteudo; e so entao `DADO_PESSOAL_ACESSADO`
    e gravado e comitado -- se a escrita falhar, a resposta e erro e o conteudo
    nao sai. Registra a TENTATIVA, como `revelar`.

    **`exigir_dono` recebe o proprio `corretor_id` de quem chama, ou nulo**,
    porque o dono de um lead nao e uma coluna: e "existe handoff para ele", e
    um lead pode ter varios. `e_lead_do_corretor` responde isso, e a funcao
    compartilhada cuida do 403 e da trilha da negativa, que sao o que nao pode
    divergir entre as rotas.

    **Por que `GET` que escreve, se `revelar` recusou isso** (D3): la o
    registro e a razao da chamada; aqui, abrir a tela e o acesso, e modela-lo
    como `POST` faria a rota mentir sobre o que faz. As duas rotas exigem
    `Authorization: Bearer`, que o pre-fetch do navegador nao manda -- sem
    credencial e 401 e nada e escrito. Uma repeticao por proxy produz um
    registro a mais, e a trilha erra para o lado de registrar.
    """
    par = await _conferir_acesso(session, lead_id=lead_id, request=request, identidade=identidade)
    await _registrar_leitura(
        session, lead_id=lead_id, campo=campo, par=par, request=request, identidade=identidade
    )
    return par


async def _conferir_acesso(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao,
) -> tuple[str, str]:
    """404, depois o recorte do CORRETOR. A primeira metade de `_abrir_para_leitura`.

    Separada desde a TEC-327: o polling (`depois`) confere o acesso em todo
    poll, e so registra a leitura quando ha fala para entregar (D1 de la).
    """
    par = await par_de(session, lead_id)
    if par is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")

    if identidade.e_corretor:
        dono = await e_lead_do_corretor(session, par=par, corretor_id=identidade.corretor_id)
        await exigir_dono(
            request,
            identidade,
            permissao=Permissao.VER_DETALHE_DO_LEAD,
            corretor_id=identidade.corretor_id if dono else None,
        )
    return par


async def _registrar_leitura(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    campo: str,
    par: tuple[str, str],
    request: Request,
    identidade: IdentidadeDaRequisicao,
) -> None:
    """O `DADO_PESSOAL_ACESSADO`, COMITADO. A segunda metade de `_abrir_para_leitura`."""
    await registrar_evento(
        session,
        ator=identidade.como_ator(),
        acao=Acao.DADO_PESSOAL_ACESSADO,
        entidade=Entidade.LEAD,
        # O apelido, e NUNCA o par -- a mesma regra de `revelar`.
        entidade_id=str(lead_id),
        campo=campo,
        lead=par,
        origem=origem_da_requisicao(request),
    )
    await session.commit()


@router.get("/{lead_id}")
async def detalhe(
    lead_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_DETALHE_DO_LEAD)),
) -> dict[str, object]:
    """Os seis blocos da RN-18.2 e o resumo. A transcricao e a rota ao lado.

    TEC-193, D1 e D4. Os papeis sao os da secao 6.2 do SRS -- "`CORRETOR`
    (proprio), `GERENTE`, `ADMIN`" --, e LEITURA fica de fora: a lista e um
    indice sem dado pessoal, e esta resposta traz o resumo em claro.
    """
    async with get_sessionmaker()() as session:
        par = await _abrir_para_leitura(
            session, lead_id=lead_id, campo=CAMPO_DETALHE, request=request, identidade=identidade
        )
        lido = await ler_detalhe(session, lead_id=lead_id, par=par)

    if lido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead nao existe")
    return _detalhe_como_json(lido)


def _detalhe_como_json(lido: DetalheDoLead) -> dict[str, object]:
    resumo = lido.resumo
    return {
        "leadId": str(lido.lead_id),
        "channel": lido.channel,
        "status": lido.status,
        "ultimaInteracaoEm": lido.ultima_interacao_em.isoformat(),
        # So mascarado, e `email` nulo: nao ha fonte (D7 da TEC-195).
        "contato": {"telefone": lido.telefone, "email": None},
        "score": lido.score,
        "resumo": (
            {
                "handoffId": str(resumo.handoff_id),
                "texto": resumo.texto,
                "geradoEm": resumo.gerado_em.isoformat() if resumo.gerado_em else None,
                "modelo": resumo.modelo,
                "fallback": resumo.fallback,
            }
            if resumo is not None
            else None
        ),
        "qualificacao": (
            {chave: _escalar(valor) for chave, valor in lido.qualificacao.items()}
            if lido.qualificacao is not None
            else None
        ),
        "historicoScore": [
            {
                "em": r.em.isoformat(),
                "anterior": r.anterior,
                "novo": r.novo,
                "fatores": r.fatores,
                "causas": r.causas,
            }
            for r in lido.historico_score
        ],
        "recomendacoes": [
            {
                "imovelId": str(r.imovel_id),
                "codigo": r.codigo,
                "titulo": r.titulo,
                "bairro": r.bairro,
                "scoreMatch": float(r.score_match),
                "motivoMatch": r.motivo_match,
                "reacao": r.reacao,
                "motivoDescarte": r.motivo_descarte,
                "apresentadoEm": r.apresentado_em.isoformat(),
            }
            for r in lido.recomendacoes
        ],
        "agendamentos": [
            {
                "id": str(a.id),
                "tipo": a.tipo,
                "inicio": a.inicio.isoformat(),
                "fim": a.fim.isoformat(),
                "status": a.status,
                "imovelId": str(a.imovel_id) if a.imovel_id else None,
            }
            for a in lido.agendamentos
        ],
        "followups": [
            {
                "tentativa": f.tentativa,
                "temperatura": f.temperatura,
                "disparadoEm": f.disparado_em.isoformat(),
            }
            for f in lido.followups
        ],
        # TEC-327, D2. O mesmo formato de `assumidoPor` no 409 de `assumir`.
        "atendimento": (
            {
                "assumidoPor": {
                    "corretorId": str(lido.atendimento.corretor_id),
                    "nome": lido.atendimento.nome,
                },
                "assumidoEm": lido.atendimento.assumido_em.isoformat(),
            }
            if lido.atendimento is not None
            else None
        ),
    }


def _escalar(valor: object) -> object:
    """O valor de uma coluna da qualificacao, na forma que o JSON aceita.

    `qualificadoEm` e o unico instante, e `retornoEsperadoPct` o unico
    `Decimal` -- que o encoder do FastAPI serializaria como texto, e a tela
    faria conta com uma string.
    """
    if isinstance(valor, Decimal):
        return float(valor)
    isoformat = getattr(valor, "isoformat", None)
    return isoformat() if isoformat is not None else valor


@router.get("/{lead_id}/mensagens")
async def mensagens(
    lead_id: uuid.UUID,
    request: Request,
    limite: Annotated[int, Query()] = LIMITE_PADRAO_DA_TRANSCRICAO,
    cursor: Annotated[str | None, Query()] = None,
    depois: Annotated[str | None, Query()] = None,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_DETALHE_DO_LEAD)),
) -> dict[str, object]:
    """A transcricao, da mais recente para tras. TEC-193, D5, para a TEC-324.

    **Cada pagina e um registro na trilha** (D3): carregar as anteriores e
    outro acesso, a um trecho que a primeira pagina nao mostrou.

    **A fala retida pela moderacao so aparece para ADMIN, e sem conteudo** --
    e a tabela da TEC-324. Para os outros papeis ela nao existe.

    O filtro e validado ANTES de abrir o lead, para que um `?limite=0` nao
    grave um acesso na trilha por uma resposta que nao devolveu nada.

    **`depois` e o polling da conversa assumida** (TEC-327, D1): so as falas
    posteriores, em ordem cronologica. **Com ele, o acesso so e gravado se a
    resposta trouxer fala** -- poll vazio nao entrega dado pessoal, e
    registra-lo encheria a trilha de leituras que nao leram nada. Decisao do
    Eduardo, 27/09/2026. As duas formas devolvem `cursorPosterior`, o ponto de
    partida do proximo poll.
    """
    if cursor and depois:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="cursor e depois sao direcoes opostas: mande um so",
        )
    try:
        validar_limite_da_transcricao(limite)
        posicao = decodificar_cursor_da_transcricao(cursor) if cursor else None
        a_partir = decodificar_cursor_da_transcricao(depois) if depois else None
    except FiltroInvalido as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    if a_partir is not None and depois is not None:
        return await _posteriores(
            lead_id=lead_id,
            limite=limite,
            depois=a_partir,
            depois_cru=depois,
            request=request,
            identidade=identidade,
        )

    async with get_sessionmaker()() as session:
        par = await _abrir_para_leitura(
            session,
            lead_id=lead_id,
            campo=CAMPO_TRANSCRICAO,
            request=request,
            identidade=identidade,
        )
        try:
            falas, anterior = await pagina_da_transcricao(
                session,
                par=par,
                limite=limite,
                cursor=posicao,
                ve_retidas=identidade.papel == "ADMIN",
            )
        except FiltroInvalido as erro:
            # O cursor de uma mensagem de OUTRO lead so o banco reconhece. O
            # acesso ja foi registrado, e foi tentado -- que e o que a trilha
            # registra.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
            ) from erro

    proximo = cursor_posterior(falas)
    return {
        "itens": [_fala_como_json(f) for f in falas],
        "cursorAnterior": anterior.codificar() if anterior else None,
        "cursorPosterior": proximo.codificar() if proximo else None,
    }


async def _posteriores(
    *,
    lead_id: uuid.UUID,
    limite: int,
    depois: CursorDaTranscricao,
    depois_cru: str,
    request: Request,
    identidade: IdentidadeDaRequisicao,
) -> dict[str, object]:
    """O poll da conversa assumida (TEC-327, D1). Registra so se veio fala.

    Acesso conferido em todo poll -- a negacao do CORRETOR continua na trilha,
    pelo `exigir_dono` --, e o registro de leitura so quando ha conteudo,
    COMITADO antes de a resposta sair, como na D3 da TEC-193. Poll vazio
    devolve o mesmo cursor que recebeu: a tela continua pedindo dali.
    """
    async with get_sessionmaker()() as session:
        par = await _conferir_acesso(
            session, lead_id=lead_id, request=request, identidade=identidade
        )
        try:
            falas = await posteriores_da_transcricao(
                session,
                par=par,
                limite=limite,
                depois=depois,
                ve_retidas=identidade.papel == "ADMIN",
            )
        except FiltroInvalido as erro:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
            ) from erro
        if falas:
            await _registrar_leitura(
                session,
                lead_id=lead_id,
                campo=CAMPO_TRANSCRICAO,
                par=par,
                request=request,
                identidade=identidade,
            )

    proximo = cursor_posterior(falas)
    return {
        "itens": [_fala_como_json(f) for f in falas],
        "cursorAnterior": None,
        "cursorPosterior": proximo.codificar() if proximo else depois_cru,
    }


def _fala_como_json(fala: Fala) -> dict[str, object]:
    return {
        "id": str(fala.id),
        "autor": fala.autor,
        "tipo": fala.tipo,
        "conteudo": fala.conteudo,
        "retida": fala.retida,
        "em": fala.em.isoformat(),
    }
