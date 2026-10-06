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
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from mobia.api.routes.imoveis import payload_da_busca
from mobia.app.config import get_settings
from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.fotos import ler_bytes
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, FiltroDeBusca
from mobia.domain.midia.armazem import armazem_da_config
from mobia.infra.db import get_sessionmaker

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
# amanha vazaria ao publico sem ninguem decidir isso. Ficam de fora: `codigo`
# (referencia interna), `status` (a RN ja garante DISPONIVEL), `zona`
# (taxonomia de busca), `latitude`/`longitude` (a card nao pede mapa, L1),
# `created_at`/`updated_at`, `embedding*`, `documento_hash`, `bairro_busca`.
_CAMPOS_DO_DETALHE = (
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
    # Mesma guarda que `FiltrosDaBusca._recusar_operacao_nao_buscavel` faz na
    # borda do endpoint interno: `AMBOS` e valor valido do enum e nao e busca
    # valida, e sem isto o `FiltroDeBusca` abaixo levantaria `ValueError` e o
    # FastAPI devolveria 500 para uma requisicao sintaticamente correta.
    if operacao not in COLUNA_DE_PRECO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"operacao {operacao} nao e buscavel: AMBOS e o que um imovel pode "
                "ser, nunca o que uma busca pede"
            ),
        )

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
    precisam de centavos->como-estao, sem conversao) e `fotos` (que precisa
    da reescrita de `_fotos_publicas`). Nao reaproveita `cadastro.como_api`:
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
    return corpo


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
