"""A vitrine publica do catalogo. TEC-387 (busca) e TEC-388 (detalhe e fotos).

**Publica, e reaproveita a busca interna sem mudar uma linha dela.** O
cliente que abre o portal sem se identificar filtra o mesmo catalogo que
`POST /api/v1/imoveis/busca` ja resolve -- a unica diferenca e a guarda: esta
rota nao pendura `Depends(Exige(...))`, porque buscar imovel num portal publico
e tarefa de visitante anonimo, nao de equipe interna.

**`operacao` continua obrigatoria**, exatamente como no endpoint interno: e
ela que escolhe qual coluna de preco comparar (`preco_venda` ou
`preco_aluguel`), e `FiltroDeBusca.__post_init__` recusa `AMBOS` com
`ValueError` porque nao ha coluna de preco para esse valor. O estado "sem
filtro nenhum" que o CA-01 da card descreve e da TELA, nao da requisicao: o
Next pre-seleciona uma operacao antes da primeira chamada (ver
`frontend/src/app/busca/page.tsx`).

**Fora de `/api/v1`, de proposito.**
`test_as_rotas_de_auth_sao_as_unicas_publicas_da_api_v1`
(`tests/unit/test_autorizacao_em_toda_rota.py`) tranca esse prefixo para so as
quatro rotas de `auth` -- e essa trava e o ponto, nao um acidente a contornar.
O molde desta rota e `api/routes/aparencia_do_widget.py`: publica, modulo
proprio, path completo no decorator.

**O detalhe e a foto (TEC-388) NAO reaproveitam as rotas administrativas.**
`GET /api/v1/imoveis/{id}` e a leitura de foto (`GERIR_CATALOGO`) nao filtram
por status -- sao a visao de quem administra o catalogo, que precisa ver e
servir foto de qualquer imovel, vendido ou nao. Tirar a guarda dali abriria
exatamente isso ao publico. As duas rotas novas aqui sao o lugar onde "so
DISPONIVEL" mora, sem arriscar o caminho administrativo. Ver D1 e D3 do
desenho.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from mobia.api.routes.imoveis import payload_da_busca
from mobia.app.config import get_settings
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.fotos import ler_bytes
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, FiltroDeBusca
from mobia.domain.catalogo.vitrine import IMOVEIS_POR_PAGINA, OrdemDaVitrine, listar_vitrine
from mobia.domain.handoff.repositorio import gravar_resumo, registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.identidade.indice import chave_de
from mobia.domain.identidade.indice import registrar as registrar_identidade
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_NUMERO
from mobia.domain.messages.canais import CANAL_PORTAL
from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.notificacao.envio import NOTIFICAR_JOB
from mobia.domain.portal.interesse import registrar_interesse
from mobia.infra.db import get_sessionmaker
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_numero, consumir

log = structlog.get_logger(__name__)

router = APIRouter(tags=["portal"])


# O 404 unico de D3: "nao existe" e "existe mas indisponivel" tem de parecer
# exatamente o mesmo erro, ou um UUID qualquer vira ferramenta de descoberta
# do catalogo. Nunca 403 -- a rota e publica, 403 sugeriria um problema de
# permissao que nao existe aqui.
def _recusar_indisponivel() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="imovel nao disponivel")


# Os campos que o cliente ve no detalhe (D2 do desenho). Lista escrita a mao,
# e NAO o dict `CAMPOS` de `domain/catalogo/cadastro.py`: aquele e mantido
# pensando em quem administra o catalogo, e um campo novo acrescentado la
# amanha vazaria ao publico sem ninguem decidir isso. Ficam de fora: `status`
# (a RN ja garante DISPONIVEL), `zona` (taxonomia de busca),
# `created_at`/`updated_at`, `embedding*`, `documento_hash`, `bairro_busca`.
# `codigo` entrou com o visual do portal (D1 daquele desenho, revertendo a
# D2 da TEC-388); `latitude`/`longitude` tambem, mas arredondadas, e por isso
# fora desta lista -- ver `_coordenada_publica`.
_CAMPOS_DO_DETALHE = (
    "codigo",
    "titulo",
    "descricao",
    "tipo",
    "operacao",
    "bairro",
    "cidade",
    "uf",
    "area_util_m2",
    "quartos",
    "suites",
    "banheiros",
    "vagas",
)


@router.get("/portal/imoveis")
async def imoveis_do_portal(
    operacao: Annotated[Operacao, Query()],
    preco_min_centavos: Annotated[int | None, Query(alias="precoMin", ge=0)] = None,
    preco_max_centavos: Annotated[int | None, Query(alias="precoMax", ge=0)] = None,
    tipo: Annotated[TipoImovel | None, Query()] = None,
    quartos_min: Annotated[int | None, Query(alias="quartosMin", ge=0)] = None,
    vagas_min: Annotated[int | None, Query(alias="vagasMin", ge=0)] = None,
    regioes: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    """A mesma busca de `POST /api/v1/imoveis/busca`, sem credencial nenhuma.

    `consultaTexto` nao existe aqui -- o portal nao tem campo de busca livre
    (D3 do desenho); so os seis filtros estruturados.
    """
    _recusar_operacao_nao_buscavel(operacao)

    filtro = FiltroDeBusca(
        operacao=operacao,
        preco_min_centavos=preco_min_centavos,
        preco_max_centavos=preco_max_centavos,
        tipo=tipo,
        quartos_min=quartos_min,
        vagas_min=vagas_min,
        regioes=tuple(regioes or []),
    )

    async with get_sessionmaker()() as session:
        resultado = await buscar_com_relaxamento(session, filtro, consulta_texto=None)

    return payload_da_busca(resultado)


def _recusar_operacao_nao_buscavel(operacao: Operacao) -> None:
    """Mesma guarda que `FiltrosDaBusca._recusar_operacao_nao_buscavel` faz na
    borda do endpoint interno: `AMBOS` e valor valido do enum e nao e busca
    valida, e sem isto o `FiltroDeBusca` levantaria `ValueError` e o FastAPI
    devolveria 500 para uma requisicao sintaticamente correta.
    """
    if operacao not in COLUNA_DE_PRECO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"operacao {operacao} nao e buscavel: AMBOS e o que um imovel pode "
                "ser, nunca o que uma busca pede"
            ),
        )


# Quantas caracteristicas o card da vitrine leva. O card mostra duas ou tres
# etiquetas; mandar a lista inteira so engordaria uma resposta de doze itens.
_CARACTERISTICAS_NO_CARD = 3


@router.get("/portal/vitrine")
async def vitrine_do_portal(
    operacao: Annotated[Operacao, Query()],
    preco_min_centavos: Annotated[int | None, Query(alias="precoMin", ge=0)] = None,
    preco_max_centavos: Annotated[int | None, Query(alias="precoMax", ge=0)] = None,
    tipo: Annotated[TipoImovel | None, Query()] = None,
    quartos_min: Annotated[int | None, Query(alias="quartosMin", ge=0)] = None,
    vagas_min: Annotated[int | None, Query(alias="vagasMin", ge=0)] = None,
    regioes: Annotated[list[str] | None, Query()] = None,
    ordem: Annotated[OrdemDaVitrine, Query()] = OrdemDaVitrine.RECENTES,
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> dict[str, object]:
    """A vitrine paginada do portal (visual do portal, D7): todos os imoveis
    disponiveis que casam com os filtros, e nao os dez mais relevantes de
    `/portal/imoveis`. Mesmos seis filtros, mesma regra de quem casa
    (`busca.py::condicoes_do_filtro`), mais ordem e pagina.
    """
    _recusar_operacao_nao_buscavel(operacao)
    filtro = FiltroDeBusca(
        operacao=operacao,
        preco_min_centavos=preco_min_centavos,
        preco_max_centavos=preco_max_centavos,
        tipo=tipo,
        quartos_min=quartos_min,
        vagas_min=vagas_min,
        regioes=tuple(regioes or []),
    )

    async with get_sessionmaker()() as session:
        pagina_da_vitrine = await listar_vitrine(session, filtro, ordem, pagina)

    return {
        "itens": [_card_da_vitrine(imovel, operacao) for imovel in pagina_da_vitrine.imoveis],
        "total": pagina_da_vitrine.total,
        "pagina": pagina,
        "porPagina": IMOVEIS_POR_PAGINA,
    }


def _card_da_vitrine(imovel: Imovel, operacao: Operacao) -> dict[str, object]:
    """Um imovel da vitrine: o bastante para o card e para o pino do mapa.

    `preco` e o da operacao buscada -- quem procura aluguel ve o aluguel de
    um imovel que tambem esta a venda. A primeira foto ja vem na rota publica
    (`_fotos_publicas`), e a coordenada, arredondada como no detalhe (D2).
    """
    fotos = _fotos_publicas(imovel.id, list(imovel.fotos))
    return {
        "id": str(imovel.id),
        "codigo": imovel.codigo,
        "titulo": imovel.titulo,
        "tipo": imovel.tipo,
        "operacao": imovel.operacao,
        "bairro": imovel.bairro,
        "cidade": imovel.cidade,
        "uf": imovel.uf,
        "areaUtilM2": imovel.area_util_m2,
        "quartos": imovel.quartos,
        "suites": imovel.suites,
        "banheiros": imovel.banheiros,
        "vagas": imovel.vagas,
        "preco": getattr(imovel, COLUNA_DE_PRECO[operacao]),
        "condominio": imovel.condominio,
        "iptuMensal": imovel.iptu_mensal,
        "caracteristicas": list(imovel.caracteristicas)[:_CARACTERISTICAS_NO_CARD],
        "foto": fotos[0] if fotos else None,
        "latitude": _coordenada_publica(imovel.latitude),
        "longitude": _coordenada_publica(imovel.longitude),
    }


def _fotos_publicas(imovel_id: uuid.UUID, fotos: list[str]) -> list[str]:
    """As URLs administrativas de `Imovel.fotos` reescritas para a rota publica.

    Cada entrada guardada e `/api/v1/imoveis/{id}/fotos/{fotoId}` (exige
    sessao); o cliente anonimo nunca ve nem usa essa URL -- so o `fotoId`, no
    final do caminho, sobrevive para montar o endereco publico (D4).
    """
    return [f"/portal/imoveis/{imovel_id}/fotos/{foto.rsplit('/', 1)[-1]}" for foto in fotos]


def payload_do_detalhe(imovel: Imovel) -> dict[str, object]:
    """O detalhe publico de um imovel (TEC-388, D2 do desenho).

    So os campos de `_CAMPOS_DO_DETALHE`, mais precos/condominio/IPTU (que
    precisam de centavos->como-estao, sem conversao), `fotos` (que precisa
    da reescrita de `_fotos_publicas`) e a coordenada (que precisa do
    arredondamento de `_coordenada_publica`). Nao reaproveita `cadastro.como_api`:
    aquele dict e mantido para a administracao, e um campo novo la amanha nao
    deve vazar aqui sem alguem decidir.
    """
    corpo: dict[str, object] = {"id": str(imovel.id)}
    for nome in _CAMPOS_DO_DETALHE:
        corpo[_camel(nome)] = getattr(imovel, nome)
    corpo["precoVenda"] = imovel.preco_venda
    corpo["precoAluguel"] = imovel.preco_aluguel
    corpo["condominio"] = imovel.condominio
    corpo["iptuMensal"] = imovel.iptu_mensal
    corpo["caracteristicas"] = list(imovel.caracteristicas)
    corpo["fotos"] = _fotos_publicas(imovel.id, list(imovel.fotos))
    corpo["latitude"] = _coordenada_publica(imovel.latitude)
    corpo["longitude"] = _coordenada_publica(imovel.longitude)
    return corpo


_CASAS_DA_COORDENADA_PUBLICA = 3


def _coordenada_publica(valor: Decimal | None) -> float | None:
    """A coordenada com 3 casas (~110 m), ou `None` sem coordenada.

    D2 do desenho do visual do portal: a pagina abre sem login, e o pino no
    predio exato entregaria o endereco a qualquer visitante. Tres casas
    mostram a quadra, que e o que a secao de localizacao precisa.
    """
    if valor is None:
        return None
    return float(round(valor, _CASAS_DA_COORDENADA_PUBLICA))


def _camel(nome_em_snake_case: str) -> str:
    """`area_util_m2` -> `areaUtilM2`. So para os nomes de `_CAMPOS_DO_DETALHE`."""
    primeira, *resto = nome_em_snake_case.split("_")
    return primeira + "".join(parte.capitalize() for parte in resto)


async def _imovel_disponivel(imovel_id: uuid.UUID) -> Imovel:
    """O imovel, se existir e estiver DISPONIVEL -- ou o 404 unico de D3."""
    async with get_sessionmaker()() as session:
        imovel = await session.get(Imovel, imovel_id)
    if imovel is None or imovel.status != StatusImovel.DISPONIVEL.value:
        raise _recusar_indisponivel()
    return imovel


@router.get("/portal/imoveis/{imovel_id}")
async def detalhe_do_imovel(imovel_id: uuid.UUID) -> dict[str, object]:
    """O detalhe publico (TEC-388): descricao, caracteristicas e fotos.

    Um `imovel_id` que nao e UUID valido ja leva 422 do proprio FastAPI, antes
    de chegar aqui -- o frontend trata 404 e 422 como o mesmo caso (D3).
    """
    imovel = await _imovel_disponivel(imovel_id)
    return payload_do_detalhe(imovel)


@router.get("/portal/imoveis/{imovel_id}/fotos/{foto_id}")
async def foto_do_imovel(imovel_id: uuid.UUID, foto_id: uuid.UUID) -> Response:
    """Os bytes da foto, so se o imovel estiver DISPONIVEL (D1, D3 e D4)."""
    await _imovel_disponivel(imovel_id)
    armazem = armazem_da_config(get_settings())
    encontrada = await ler_bytes(armazem, imovel_id=str(imovel_id), foto_id=str(foto_id))
    if encontrada is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="foto nao existe")
    dados, mime = encontrada
    return Response(content=dados, media_type=mime)


# TEC-389. `extra="forbid"`, no molde de `CorpoDoImovel`: um campo a mais no
# corpo e sintoma de integracao errada, nao algo a ignorar em silencio.
class PedidoDeInteresse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telefone: str = Field(min_length=1, max_length=20)
    nome: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)


def _resumo_do_interesse(
    imovel: Imovel, *, telefone: str, nome: str | None, email: str | None
) -> str:
    """Texto fixo do resumo do handoff (D3 do desenho).

    Nunca passa por `handoff/geracao.py`: aquele pipeline le um `Dossie`
    montado de qualificacao de CONVERSA, que um pedido de formulario nao tem
    -- e, sem essa mudanca, o corretor leria "sem dossie" no lugar exato onde
    precisa do telefone e do imovel. `gravar_resumo` cifra este texto do
    mesmo jeito que cifraria um resumo de LLM; nao ha diferenca de tratamento
    de dado sensivel entre os dois caminhos.
    """
    return "\n".join(
        (
            "PEDIDO DE INTERESSE (portal, sem conversa)",
            f"imovel: {imovel.titulo} (codigo {imovel.codigo})",
            f"nome: {nome or 'nao informado'}",
            f"telefone: {telefone}",
            f"e-mail: {email or 'nao informado'}",
        )
    )


@router.post("/portal/imoveis/{imovel_id}/interesse", status_code=status.HTTP_201_CREATED)
async def solicitar_interesse(
    imovel_id: uuid.UUID, pedido: PedidoDeInteresse, request: Request
) -> dict[str, object]:
    """Registra o interesse e notifica o corretor responsavel (TEC-389).

    Reaproveita o MESMO handoff/notificacao do fluxo conversacional (D3/B2 do
    desenho) -- so que com um gatilho proprio (`Gatilho.INTERESSE_PORTAL`) e
    um resumo escrito na hora, sem LLM. CA-01/02/03/04 vivem aqui: contato
    invalido e 422, imovel indisponivel e o mesmo 404 da TEC-388, e um pedido
    repetido do mesmo telefone para o mesmo imovel nao duplica nada (D2/L3).
    """
    telefone = normalizar(pedido.telefone)
    if telefone is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="telefone invalido",
        )

    imovel = await _imovel_disponivel(imovel_id)

    conversation_key = chave_de(CANAL_PORTAL, telefone)
    pool = getattr(request.app.state, "redis_pool", None)
    settings = get_settings()

    consumo = await consumir(
        pool,
        chave=chave_de_numero(CANAL_PORTAL, conversation_key),
        limite=settings.rate_limit_interesse_por_minuto,
        janela_segundos=JANELA_DE_UM_MINUTO,
    )
    if not consumo.permitido:
        log.warning(
            "ratelimit.blocked",
            escopo=ESCOPO_NUMERO,
            conversation_key=conversation_key,
            channel=CANAL_PORTAL,
            volume=consumo.volume,
            limite=settings.rate_limit_interesse_por_minuto,
        )
        await registrar_bloqueio(
            get_sessionmaker(),
            pool,
            escopo=ESCOPO_NUMERO,
            chave=conversation_key,
            channel=CANAL_PORTAL,
            volume=consumo.volume,
            limite=settings.rate_limit_interesse_por_minuto,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="muitos pedidos em pouco tempo -- tente de novo em instantes",
        )

    async with get_sessionmaker()() as session:
        await registrar_identidade(session, CANAL_PORTAL, telefone)
        registro = await registrar_handoff(
            session,
            channel=CANAL_PORTAL,
            conversation_key=conversation_key,
            gatilho=Gatilho.INTERESSE_PORTAL,
            ator=ATOR_SISTEMA,
        )
        await registrar_interesse(
            session,
            imovel_id=imovel.id,
            channel=CANAL_PORTAL,
            conversation_key=conversation_key,
            nome=pedido.nome,
            agora=datetime.now(UTC),
        )
        if registro.criado:
            # So escreve o resumo quando o handoff NASCE aqui -- D4: um
            # telefone que ja tem handoff aberto (de qualquer gatilho) so
            # acumula em `gatilhos_adicionais`; reescrever o resumo apagaria
            # o que ja levou o corretor a esse lead.
            texto = _resumo_do_interesse(
                imovel, telefone=telefone, nome=pedido.nome, email=pedido.email
            )
            await gravar_resumo(
                session, handoff_id=registro.id, texto=texto, modelo=None, fallback=True
            )
        await session.commit()

    if registro.criado:
        if pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sem pool do Redis no app: a notificacao nao foi enfileirada",
            )
        try:
            await pool.enqueue_job(
                NOTIFICAR_JOB, str(registro.id), _job_id=f"notificar:{registro.id}"
            )
        except Exception as erro:  # ampla de proposito -- mesmo argumento de `titular.py`
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"falha ao enfileirar o job: {type(erro).__name__}",
            ) from erro

    return {"recebido": True}
