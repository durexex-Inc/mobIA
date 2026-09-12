"""Importacao do catalogo por HTTP (TEC-156, RN-08.1, secao 6.3 do SRS).

Assincrono como o SRS descreve: o POST devolve 202 com o id e enfileira, e o
GET devolve o relatorio. Nao e fidelidade cega -- a TEC-157 acrescenta a
geracao de embedding, que sao ~500 chamadas de API por importacao, e ali o
assincrono deixa de ser escolha. Fazer sincrono agora significaria emendar o
SRS duas vezes em duas cards. Ver D2 do desenho.

**A linha e comitada antes do enqueue, e isso obriga a fechar o buraco.** O
job recebe so o `importacao_id` e le os bytes da propria linha (D9), entao a
linha precisa existir antes. Se o enqueue nao acontece -- Redis fora, app sem
pool --, ninguem mais toca nessa linha: nao ha job para roda-la e nao ha sweep
que varra importacao parada. Por isso o handler a fecha em FALHOU com motivo e
responde 503 com o id, em vez de devolver 202 sobre trabalho que nao comecou.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mobia.api.deps import exigir_admin
from mobia.domain.catalogo.busca import MAX_CANDIDATOS, buscar
from mobia.domain.catalogo.enums import Operacao, OrigemImportacao, StatusImportacao, TipoImovel
from mobia.domain.catalogo.importacao import registrar
from mobia.domain.catalogo.models import Importacao
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, FiltroDeBusca
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/imoveis", tags=["catalogo"])

# ~40 mil imoveis. Acima disso o caminho e a CLI, que nao passa por upload.
TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024


@router.post("/importar", status_code=status.HTTP_202_ACCEPTED)
async def importar(
    request: Request,
    arquivo: Annotated[UploadFile, File()],
    _: None = Depends(exigir_admin),
) -> dict[str, str]:
    conteudo = await arquivo.read()
    if len(conteudo) > TETO_DE_UPLOAD_EM_BYTES:
        # HTTP_413_CONTENT_TOO_LARGE, nao HTTP_413_REQUEST_ENTITY_TOO_LARGE: e
        # o mesmo codigo 413, mas o segundo nome esta deprecated nesta versao
        # do Starlette e emite warning a cada chamada.
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"arquivo acima de {TETO_DE_UPLOAD_EM_BYTES} bytes; use a CLI de seed",
        )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        importacao_id = await registrar(
            session,
            origem=OrigemImportacao.HTTP,
            nome_arquivo=arquivo.filename or "sem-nome",
            conteudo=conteudo,
        )
        await session.commit()

    # `motivo` continua None so quando o job foi de fato para a fila. As duas
    # falhas possiveis -- app sem pool e enqueue que levanta -- tem a mesma
    # consequencia para a linha ja comitada, e por isso o mesmo tratamento.
    pool = getattr(request.app.state, "redis_pool", None)
    motivo: str | None = None
    if pool is None:
        motivo = "sem pool do Redis no app: o job de importacao nao foi enfileirado"
    else:
        try:
            await pool.enqueue_job("importar_catalogo", str(importacao_id))
        except Exception as erro:  # ampla de proposito -- ver `_marcar_falha`
            motivo = f"falha ao enfileirar o job: {erro}"

    if motivo is not None:
        await _marcar_falha(importacao_id, motivo)
        # 503 com o id no corpo, e nao o 500 vazio de antes: a linha ja foi
        # comitada, e sem o `importacaoId` o cliente nao tem como ler o motivo
        # no GET nem como saber que existe uma importacao para descartar.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "importacaoId": str(importacao_id),
                "status": str(StatusImportacao.FALHOU),
                "mensagem": "a importacao foi registrada mas nao pode ser enfileirada",
            },
        )

    # Depois do enqueue, e nunca antes: uma linha de log que afirma um evento
    # que nao aconteceu e, nesta base, o mesmo defeito de um comentario que
    # mente. Era o que acontecia sem `redis_pool` -- 202, status PROCESSANDO e
    # "importacao_enfileirada" no log, com a fila vazia.
    log.info("catalogo.importacao_enfileirada", importacao_id=str(importacao_id))
    return {"importacaoId": str(importacao_id), "status": "PROCESSANDO"}


async def _marcar_falha(importacao_id: uuid.UUID, motivo: str) -> None:
    """Fecha em FALHOU a linha que ficaria orfa em PROCESSANDO.

    A linha e comitada antes do enqueue -- e tem de ser, porque o job recebe
    so o id e precisa achar os bytes. Quando o enqueue nao acontece, ninguem
    mais vai tocar nessa linha: nao ha job para roda-la e nao ha sweep que
    varra importacao parada. Deixa-la em PROCESSANDO faz um trabalho que nunca
    comecou parecer trabalho em andamento, e prende ate 10 MB por vez.

    A excecao de quem chama e ampla de proposito: qualquer falha do Redis
    (timeout, conexao recusada, serializacao) tem a mesma consequencia para
    esta linha, e distinguir a causa aqui nao muda o que precisa ser gravado.
    """
    log.error(
        "catalogo.importacao_nao_enfileirada",
        importacao_id=str(importacao_id),
        motivo=motivo,
    )
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)
        if importacao is None:
            return
        importacao.status = str(StatusImportacao.FALHOU)
        importacao.erros = [{"linha": 0, "motivo": motivo}]
        importacao.concluida_em = datetime.now(UTC)
        await session.commit()


@router.get("/importacoes/{importacao_id}")
async def consultar(importacao_id: uuid.UUID, _: None = Depends(exigir_admin)) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)

    if importacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrada")

    # Enquanto o job nao termina, isto devolve PROCESSANDO com os totais em
    # zero. E o status que o consumidor le, nao o codigo HTTP.
    return {
        "importacaoId": str(importacao.id),
        "status": importacao.status,
        "nomeArquivo": importacao.nome_arquivo,
        "processados": importacao.processados,
        "inseridos": importacao.inseridos,
        "atualizados": importacao.atualizados,
        "inalterados": importacao.inalterados,
        "rejeitados": importacao.rejeitados,
        "erros": importacao.erros,
    }


class FiltrosDaBusca(BaseModel):
    """As dimensoes estruturadas, no camelCase da secao 6.3.

    `alias` e nao nomes camelCase nos atributos: o corpo HTTP fala camelCase e
    o Python deste repo fala snake_case, e `populate_by_name` deixa os dois
    funcionarem sem duas classes.

    `operacao` NAO tem default: sem ela nao ha coluna de preco a comparar, e
    um default faria "ate R$ 600.000" casar todo aluguel do catalogo. Ver D2.

    `status` nao esta aqui de proposito -- a RN-08.4 o resolve no WHERE, e
    aceita-lo daria ao chamador um jeito de pedir imovel vendido (D3).
    """

    model_config = ConfigDict(populate_by_name=True)

    operacao: Operacao
    preco_min_centavos: int | None = Field(default=None, alias="precoMin")
    preco_max_centavos: int | None = Field(default=None, alias="precoMax")
    tipo: TipoImovel | None = None
    quartos_min: int | None = Field(default=None, alias="quartosMin")
    vagas_min: int | None = Field(default=None, alias="vagasMin")
    # `max_length=20`: um lead nomeia um punhado de bairros ou zonas, nunca
    # duas dezenas. O limite existe para a lista nao virar um IN gigante --
    # honesto ou nao, ninguem digita mais que isso numa conversa.
    regioes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("operacao")
    @classmethod
    def _recusar_operacao_nao_buscavel(cls, valor: Operacao) -> Operacao:
        """`AMBOS` e valor valido do enum e nao e busca valida.

        Sem esta guarda o `FiltroDeBusca` levanta `ValueError` no dominio e o
        FastAPI devolve 500 para uma requisicao sintaticamente correta. As duas
        camadas nao sao redundancia a simplificar: esta INFORMA o cliente com
        422, e a do dominio GARANTE a regra para quem chama por dentro -- mesmo
        desenho que o `limite` ja usa.

        `not in COLUNA_DE_PRECO` e nao `is AMBOS`: a guarda derivada do mapa
        nao vira uma segunda copia da regra, e a operacao que alguem acrescentar
        ao enum amanha e recusada aqui em vez de passar e quebrar no dominio.
        """
        if valor not in COLUNA_DE_PRECO:
            raise ValueError(
                f"operacao {valor} nao e buscavel: AMBOS e o que um imovel pode "
                "ser, nunca o que uma busca pede"
            )
        return valor


class PedidoDeBusca(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # `max_length=500`: a frase de busca de um lead e uma sentenca, nao um
    # texto colado. NESTE endpoint o campo continua inerte (nenhum embedador
    # injetado, ver a docstring de `busca` abaixo) -- desde a TEC-265 e o
    # turno quem injeta embedador nas buscas dele (`domain/agente/turno.py`),
    # e este endpoint HTTP nao muda. O teto existe para o dia em que este
    # endpoint tambem ligar o embedador, e cada caractere passar a custar uma
    # chamada a um provedor pago.
    consulta_texto: str | None = Field(default=None, alias="consultaTexto", max_length=500)
    filtros: FiltrosDaBusca
    # `le=MAX_CANDIDATOS` recusa com 422 em vez de devolver 10 calado: o
    # dominio faz o clamp de qualquer jeito (RN-09.2 e sobre o que a busca
    # devolve), e a borda existe para INFORMAR o cliente. Ver D10.
    limite: int = Field(default=MAX_CANDIDATOS, ge=1, le=MAX_CANDIDATOS)


@router.post("/busca")
async def busca(pedido: PedidoDeBusca, _: None = Depends(exigir_admin)) -> dict[str, object]:
    """A busca hibrida da RF-09, no contrato da secao 6.3.

    **A guarda nao e a do SRS, e isso e declarado.** A secao 6.3 pede "Bearer
    JWT ou token interno do agente"; o que existe e o `X-Admin-Token` que a D1
    da TEC-156 registra como provisorio. Este endpoint NAO e administrativo, e
    quando o JWT chegar (TEC-201) ele precisa de papel proprio.

    **O embedador nao e injetado aqui, e a consequencia esta no corpo da
    resposta.** A TEC-265 ligou a busca ao agente, e quem passa o embedador de
    verdade e o turno (`domain/agente/turno.py`), nao esta rota -- nenhum
    consumidor HTTP tem hoje um motivo para pagar a latencia de embedar a
    consulta. Aqui `consultaVetorizada` continua saindo `false` e a ordem e a
    aderencia de preco -- o que e a degradacao da D8 funcionando, e nao um
    defeito. Trocar isto e uma linha.

    **`consultaTexto` e aceito e INERTE NESTA ROTA.** O campo entra no
    pedido e e repassado, mas sem embedador `vetor_da_consulta` devolve
    `None` sempre, entao ele nao muda um resultado sequer. Relevancia ou
    latencia medidas atraves DESTE endpoint descrevem so o caminho degradado
    -- a chamada de embedding, que e a parte cara, nunca acontece. No turno,
    desde a TEC-265, o mesmo campo do tool call NAO e inerte: ver
    `domain/agente/ferramenta_de_busca.py` e `domain/agente/turno.py`.
    """
    filtro = FiltroDeBusca(
        operacao=pedido.filtros.operacao,
        preco_min_centavos=pedido.filtros.preco_min_centavos,
        preco_max_centavos=pedido.filtros.preco_max_centavos,
        tipo=pedido.filtros.tipo,
        quartos_min=pedido.filtros.quartos_min,
        vagas_min=pedido.filtros.vagas_min,
        regioes=tuple(pedido.filtros.regioes),
    )

    async with get_sessionmaker()() as session:
        resultado = await buscar(
            session, filtro, consulta_texto=pedido.consulta_texto, limite=pedido.limite
        )

    return {
        "itens": [
            {
                "id": str(candidato.imovel_id),
                "codigo": candidato.codigo,
                "titulo": candidato.titulo,
                "bairro": candidato.bairro,
                "preco": candidato.preco_centavos,
                "quartos": candidato.quartos,
                "vagas": candidato.vagas,
                "areaUtilM2": candidato.area_util_m2,
                "scoreMatch": candidato.score,
            }
            for candidato in resultado.candidatos
        ],
        "totalCandidatos": resultado.total_candidatos,
        "consultaVetorizada": resultado.consulta_vetorizada,
        "candidatosSemVetor": resultado.candidatos_sem_vetor,
    }
