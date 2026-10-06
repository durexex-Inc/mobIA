"""O catalogo por HTTP: importacao em lote, busca e o CRUD da administracao.

Importacao: TEC-156, RN-08.1, secao 6.3 do SRS. Busca: TEC-158. O CRUD um a um
da tela de administracao (TEC-197, RN-19.1) mora no fim do arquivo, e passa
pela mesma validacao e pelo mesmo upsert da importacao -- ver
`domain/catalogo/cadastro.py`.

**Sobre a importacao:**

Assincrono como o SRS descreve: o POST devolve 202 com o id e enfileira, e o
GET devolve o relatorio. Nao e fidelidade cega -- a TEC-157 acrescenta a
geracao de embedding, que sao ~500 chamadas de API por importacao, e ali o
assincrono deixa de ser escolha. Fazer sincrono agora significaria emendar o
SRS duas vezes em duas cards. Ver D2 do desenho.

**A linha e comitada antes do enqueue, e isso obriga a fechar o buraco.** O
job recebe so o `importacao_id` e le os bytes da propria linha (D9), entao a
linha precisa existir antes. Se o enqueue nao acontece -- Redis fora, app sem
pool --, nao ha job para rodar essa linha. A varredura da TEC-261
(`workers/jobs/sweep_importacoes_travadas.py`) a encerraria, mas so meia hora
depois e sem nada a dizer a quem esta esperando o POST. Por isso o handler a
fecha em FALHOU com motivo e responde 503 com o id, em vez de devolver 202
sobre trabalho que nao comecou.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.catalogo import cadastro
from mobia.domain.catalogo.busca import MAX_CANDIDATOS
from mobia.domain.catalogo.enums import (
    EstadoDoRelaxamento,
    Operacao,
    OrigemImportacao,
    StatusImportacao,
    TipoImovel,
)
from mobia.domain.catalogo.fotos import (
    FOTO_LIMITE_POR_IMOVEL,
    FOTO_TETO_DE_BYTES,
    chave_do_armazem,
    detectar_formato,
    mime_da_extensao,
    mime_e_extensao_de,
)
from mobia.domain.catalogo.importacao import registrar
from mobia.domain.catalogo.models import Imovel, Importacao
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, FiltroDeBusca, ResultadoDaBusca
from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/imoveis", tags=["catalogo"])

# ~40 mil imoveis. Acima disso o caminho e a CLI, que nao passa por upload.
TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024


@router.post("/importar", status_code=status.HTTP_202_ACCEPTED)
async def importar(
    request: Request,
    arquivo: Annotated[UploadFile, File()],
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.GERIR_CATALOGO)),
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
            # Sem interpolar `erro`: este valor tem DOIS destinos -- o log
            # abaixo (`catalogo.importacao_nao_enfileirada`) e a coluna
            # duravel `importacao.erros`, que o GET desta rota devolve ao
            # cliente por HTTP. Pelo argumento da TEC-222 -- destino duravel e
            # fora da mascara nao pode carregar texto de terceiro --, e aqui e
            # pior do que naquele caso porque o valor sai por HTTP. O tipo da
            # excecao basta para nomear a falha sem repassar o texto dela.
            motivo = f"falha ao enfileirar o job: {type(erro).__name__}"

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
    """Fecha em FALHOU a linha que ficaria em PROCESSANDO sem job que a rode.

    A linha e comitada antes do enqueue -- e tem de ser, porque o job recebe
    so o id e precisa achar os bytes. Quando o enqueue nao acontece, nao ha job
    para roda-la: deixa-la em PROCESSANDO faz um trabalho que nunca comecou
    parecer trabalho em andamento. Desde a TEC-261 a varredura
    (`workers/jobs/sweep_importacoes_travadas.py`) tambem alcanca essa linha,
    mas so meia hora depois -- fechar aqui e o que permite responder 503 com o
    id na hora. Os ate 10 MB de `arquivo` ficam presos de um jeito ou de outro:
    nem este caminho nem a varredura limpam a coluna.

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
async def consultar(
    importacao_id: uuid.UUID,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.GERIR_CATALOGO)),
) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        importacao = await session.get(Importacao, importacao_id)

    if importacao is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrada")

    # Enquanto o job nao termina, isto devolve PROCESSANDO com os totais em
    # zero. E o status que o consumidor le, nao o codigo HTTP.
    return _relatorio(importacao)


def _relatorio(importacao: Importacao) -> dict[str, object]:
    """O relatorio de uma importacao. O mesmo formato no `GET` por id e na
    lista das recentes (TEC-197, D6): a tela abre com a ultima e mostra o
    mesmo objeto que o acompanhamento por id mostraria."""
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
async def busca(
    pedido: PedidoDeBusca,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.BUSCAR_IMOVEIS)),
) -> dict[str, object]:
    """A busca hibrida da RF-09, no contrato da secao 6.3.

    **A guarda ganhou papel proprio na TEC-202, que e o que faltava.** A secao
    6.3 pede "Bearer JWT ou token interno do agente", e ate ali o que existia
    era o `X-Admin-Token` que a D1 da TEC-156 registrou como provisorio (e que
    a TEC-382 apagou) -- que fazia deste endpoint, que NAO e administrativo,
    um endpoint administrativo na pratica. `BUSCAR_IMOVEIS` e a unica
    permissao que os quatro papeis tem: buscar imovel no catalogo e o que
    qualquer pessoa do time faz.

    O "token interno do agente" da secao 6.3 continua sem existir -- o agente
    nao chama esta rota por HTTP, chama `busca_hibrida` direto.

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

    **Desde a TEC-160 esta rota tambem relaxa.** Zero candidatos no filtro
    duro aciona a politica de zero-resultado da RN-09.3
    (`buscar_com_relaxamento`), e o corpo devolve `relaxamentoAplicado` --
    o booleano que a secao 6.3 do SRS ja mostrava no exemplo de resposta.
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
        resultado = await buscar_com_relaxamento(
            session, filtro, consulta_texto=pedido.consulta_texto, limite=pedido.limite
        )

    return payload_da_busca(resultado)


def payload_da_busca(resultado: ResultadoDaBusca) -> dict[str, object]:
    """O corpo HTTP da secao 6.3, a partir do `ResultadoDaBusca` do dominio.

    Extraida de `busca()` na TEC-387 para que `api/routes/portal.py` devolva
    exatamente o mesmo formato -- a vitrine publica reaproveita esta mesma
    funcao de busca, e a serializacao nao deveria divergir so porque a guarda
    de permissao mudou.
    """
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
        # RN-09.3, e o campo que o exemplo da secao 6.3 ja escrevia. Booleano
        # na borda, tri-estado no dominio: `SEM_RESULTADO` sai como `false`
        # aqui porque, do ponto de vista do chamador HTTP, nao ha nada
        # relaxado para ver. Quem precisa dos tres estados e o turno (D6).
        "relaxamentoAplicado": resultado.relaxamento is EstadoDoRelaxamento.APLICADO,
    }


# --- TEC-197: o imovel um a um, pela tela de administracao --------------------
#
# Todas com `GERIR_CATALOGO`, que e so do ADMIN (RN-19.5). A lista tambem, e
# nao so as escritas: e a da administracao, com inativos e todos os campos, e
# nao a vitrine que a secao 6.3 descreve para `GET /imoveis`. Ver a D1 do
# desenho.
#
# **A ordem de registro importa aqui.** `GET /importacoes` vem antes de
# `GET /{imovel_id}`: o FastAPI casa rota por ordem, e a palavra
# "importacoes" caberia no parametro -- a validacao de UUID responderia 422 em
# vez de a rota certa responder.

_ADMIN = Depends(Exige(Permissao.GERIR_CATALOGO))

_STATUS_DO_CADASTRO = {
    cadastro.DUPLICADO: status.HTTP_409_CONFLICT,
    cadastro.INVALIDO: status.HTTP_422_UNPROCESSABLE_CONTENT,
    cadastro.NAO_EXISTE: status.HTTP_404_NOT_FOUND,
    cadastro.CODIGO_IMUTAVEL: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _recusa(erro: cadastro.CadastroRecusado) -> HTTPException:
    return HTTPException(status_code=_STATUS_DO_CADASTRO[erro.motivo], detail=erro.detalhe)


class CorpoDoImovel(BaseModel):
    """Os campos de `cadastro.CAMPOS`, todos opcionais NA BORDA.

    **A borda so confere a forma** (numero e numero, lista e lista); o que e
    obrigatorio, o teto de cada texto, o vocabulario de cada enumerado e a
    plausibilidade do preco sao conferidos por `parser.validar_um`, a mesma
    funcao das linhas do arquivo (D2). Repetir essas regras aqui seria o
    segundo validador que o desenho recusa. No `POST`, campo ausente chega la
    como ausente e volta como "titulo ausente", com o texto do relatorio de
    importacao.

    Precos em CENTAVOS, como `precoMax` da busca.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str | None = None
    titulo: str | None = None
    descricao: str | None = None
    tipo: str | None = None
    operacao: str | None = None
    status: str | None = None
    precoVenda: int | None = None  # noqa: N815
    precoAluguel: int | None = None  # noqa: N815
    condominio: int | None = None
    iptuMensal: int | None = None  # noqa: N815
    bairro: str | None = None
    cidade: str | None = None
    uf: str | None = None
    zona: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    areaUtilM2: int | None = None  # noqa: N815
    quartos: int | None = None
    suites: int | None = None
    banheiros: int | None = None
    vagas: int | None = None
    caracteristicas: list[str] | None = None
    fotos: list[str] | None = None

    def enviados(self) -> dict[str, object]:
        """So o que veio no corpo: ausente nao muda, `null` explicito limpa."""
        return {nome: getattr(self, nome) for nome in self.model_fields_set}


@router.get("")
async def listar(
    status_do_imovel: Annotated[str | None, Query(alias="status")] = None,
    tipo: Annotated[str | None, Query()] = None,
    busca: Annotated[str | None, Query()] = None,
    bairro: Annotated[str | None, Query()] = None,
    limite: Annotated[int, Query(ge=1, le=cadastro.LIMITE_MAXIMO)] = cadastro.LIMITE_PADRAO,
    cursor: Annotated[str | None, Query()] = None,
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Os imoveis por `codigo`, paginados por keyset. D5. Sem `total`."""
    async with get_sessionmaker()() as session:
        itens, proximo = await cadastro.listar(
            session,
            status=status_do_imovel,
            tipo=tipo,
            busca=busca.strip() if busca else None,
            bairro=bairro.strip() if bairro else None,
            limite=limite,
            depois_de=cursor,
        )
    return {"itens": [cadastro.como_api(i) for i in itens], "proximoCursor": proximo}


@router.get("/importacoes")
async def recentes(
    limite: Annotated[int, Query(ge=1, le=50)] = 5,
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """As importacoes mais recentes, com as linhas rejeitadas de cada uma. D6."""
    async with get_sessionmaker()() as session:
        importacoes = await cadastro.importacoes_recentes(session, limite=limite)
    return {"itens": [_relatorio(i) for i in importacoes]}


@router.get("/{imovel_id}")
async def ler(imovel_id: uuid.UUID, _: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        imovel = await session.get(Imovel, imovel_id)
    if imovel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="imovel nao existe")
    return cadastro.como_api(imovel)


@router.post("", status_code=status.HTTP_201_CREATED)
async def criar(corpo: CorpoDoImovel, _: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    """Um imovel novo. A reindexacao e da varredura, como na importacao."""
    async with get_sessionmaker()() as session:
        try:
            imovel = await cadastro.criar(session, campos=corpo.enviados())
        except cadastro.CadastroRecusado as erro:
            raise _recusa(erro) from erro
        await session.commit()
        return cadastro.como_api(imovel)


@router.patch("/{imovel_id}")
async def editar(
    imovel_id: uuid.UUID, corpo: CorpoDoImovel, _: IdentidadeDaRequisicao = _ADMIN
) -> dict[str, object]:
    """Edicao parcial, validada sobre o registro inteiro. D2 e D3.

    `reindexa` antecipa a tela o que a varredura vai fazer: verdadeiro quando
    um campo do documento mudou, falso para preco e status. Nao dispara nada.
    """
    async with get_sessionmaker()() as session:
        try:
            edicao = await cadastro.editar(session, imovel_id=imovel_id, campos=corpo.enviados())
        except cadastro.CadastroRecusado as erro:
            raise _recusa(erro) from erro
        await session.commit()
        return {**cadastro.como_api(edicao.imovel), "reindexa": edicao.reindexa}


@router.delete("/{imovel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluir(imovel_id: uuid.UUID, _: IdentidadeDaRequisicao = _ADMIN) -> None:
    """Exclusao logica: `status=INATIVO` (secao 6.3). D4."""
    async with get_sessionmaker()() as session:
        try:
            await cadastro.excluir(session, imovel_id=imovel_id)
        except cadastro.CadastroRecusado as erro:
            raise _recusa(erro) from erro
        await session.commit()


# --- TEC-335: upload e leitura da foto do imovel -------------------------------
#
# `GERIR_CATALOGO` nas duas, D2 do desenho: o unico consumidor de verdade hoje
# e a propria tela de administracao, e o widget do chat web ainda nao desenha
# o card com foto (`frontend/src/widget` nao le `foto` do payload) -- expor a
# leitura sem guarda seria decisao de exposicao publica tomada cedo demais.
# Reordenar/remover fotos NAO ganham rota nova: e o `PATCH` acima, com
# `fotos: list[str]` numa ordem ou tamanho diferente (D4/D5).


@router.post("/{imovel_id}/fotos", status_code=status.HTTP_201_CREATED)
async def enviar_foto(
    imovel_id: uuid.UUID,
    arquivo: Annotated[UploadFile, File()],
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Sobe uma foto do imovel. Validada por assinatura de bytes, nunca por
    `Content-Type` declarado nem pela extensao do nome (D3)."""
    async with get_sessionmaker()() as session:
        imovel = await session.get(Imovel, imovel_id)
        if imovel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="imovel nao existe")

        if len(imovel.fotos) >= FOTO_LIMITE_POR_IMOVEL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"o imovel ja tem o limite de {FOTO_LIMITE_POR_IMOVEL} fotos",
            )

        dados = await arquivo.read()
        if len(dados) > FOTO_TETO_DE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"foto acima de {FOTO_TETO_DE_BYTES} bytes",
            )

        formato = detectar_formato(dados)
        if formato is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="formato nao reconhecido: aceita apenas JPEG, PNG ou WebP",
            )

        _mime_ignorado, extensao = mime_e_extensao_de(formato)
        foto_id = uuid.uuid4()
        chave = chave_do_armazem(str(imovel_id), str(foto_id), extensao)
        await armazem_da_config(get_settings()).guardar(chave, dados)

        # URL relativa, como as outras entradas de `fotos` (D3 do desenho):
        # `armazem_da_config` grava sob um `foto_id` de `uuid4()`, entao nunca
        # contem `|` -- o separador que `cadastro._bruto` recusa em listas.
        nova_url = f"/api/v1/imoveis/{imovel_id}/fotos/{foto_id}"
        try:
            edicao = await cadastro.editar(
                session, imovel_id=imovel_id, campos={"fotos": [*imovel.fotos, nova_url]}
            )
        except cadastro.CadastroRecusado as erro:
            raise _recusa(erro) from erro
        await session.commit()
        return cadastro.como_api(edicao.imovel)


@router.get("/{imovel_id}/fotos/{foto_id}")
async def ler_foto(
    imovel_id: uuid.UUID, foto_id: uuid.UUID, _: IdentidadeDaRequisicao = _ADMIN
) -> Response:
    """Serve a foto de volta. O `Content-Type` vem da extensao gravada na
    chave do armazem -- a mesma que a validacao do upload (D3) escolheu, nunca
    o que o navegador declarou (D2)."""
    settings = get_settings()
    armazem = armazem_da_config(settings)
    for extensao in ("jpg", "png", "webp"):
        chave = chave_do_armazem(str(imovel_id), str(foto_id), extensao)
        try:
            dados = await armazem.ler(chave)
        except FileNotFoundError:
            continue
        mime = mime_da_extensao(extensao)
        return Response(content=dados, media_type=mime)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="foto nao existe")
