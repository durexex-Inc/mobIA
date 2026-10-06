"""A vitrine publica do catalogo. TEC-387, D1 do desenho.

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
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from mobia.api.routes.imoveis import payload_da_busca
from mobia.domain.catalogo.enums import Operacao, TipoImovel
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, FiltroDeBusca
from mobia.infra.db import get_sessionmaker

router = APIRouter(tags=["portal"])


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
