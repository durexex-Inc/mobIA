"""A aparencia do chat web, para o loader do site. TEC-344, D3 do desenho.

**Publica, e so com o que o botao precisa**: nome do assistente, cor primaria
e posicao. O resto da configuracao do agente e do administrador e nao sai por
uma rota anonima.

**Slug errado e slug nao configurado dao o mesmo 404**, com o mesmo corpo.
Distinguir os dois diria a quem sonda se existe algum tenant.

Em modulo proprio, e nao em `widget.py`: aquele arquivo e o ciclo do
WebSocket, e esta e uma leitura HTTP sem nada em comum com ele.

Quem chama e o servidor do Next (`/embed/aparencia`), e nao o navegador: o
`RateLimitPorIP` ve o IP dele, e e o cache de 60 s de la que impede todos os
visitantes de caberem num balde so (D4).
"""

from fastapi import APIRouter, HTTPException, status

from mobia.app.config import get_settings
from mobia.domain.configuracao.repositorio import configuracao_vigente
from mobia.domain.configuracao.vigente import PosicaoDoBotao
from mobia.infra.db import get_sessionmaker

router = APIRouter(tags=["widget"])


@router.get("/widget/aparencia/{slug}")
async def aparencia(slug: str) -> dict[str, object]:
    configurado = get_settings().tenant_slug
    # `not configurado` e nao `is None`: `TENANT_SLUG=` vazio no `.env` chega
    # como "", e "" nao e um slug.
    if not configurado or slug != configurado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrado")
    async with get_sessionmaker()() as session:
        config = await configuracao_vigente(session)
    return {
        "nomeDoAssistente": config.nome_do_assistente,
        "corPrimaria": config.cor_primaria,
        "posicaoDoBotao": PosicaoDoBotao(config.posicao_do_botao).value,
    }
