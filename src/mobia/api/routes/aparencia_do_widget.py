"""A aparencia do chat web, para o loader do site. TEC-344, D3 do desenho.

**Publica, e so com o que o botao precisa**: nome do assistente, cor primaria
e posicao. O resto da configuracao do agente e do administrador e nao sai por
uma rota anonima.

**Responde sempre 200, e devolve o slug configurado em `tenant`** (nulo sem
`TENANT_SLUG`). Quem compara com o `data-tenant` do snippet e o Next, e nao
esta rota: o Data Cache do Next so guarda resposta 200, e um 404 daqui nunca
entraria nele -- cada visita de um slug errado, ou de qualquer slug com
`TENANT_SLUG` vazio, chegaria ao FastAPI no mesmo balde de rate limit do
painel (emenda da TEC-344 ao D3). Sem slug no caminho, o URL e um so, e o
cache tambem. O 404 igual para slug errado e slug nao configurado continua
existindo, so que no Next (`/embed/aparencia`).

O slug configurado nao e segredo: ele esta no snippet de todo site que
embute o chat. O que esta rota diz a mais que o 404 do Next -- se ha ou nao
algum slug configurado -- so e visivel a quem fala com a API direto, e o
navegador nao fala (TEC-302).

Em modulo proprio, e nao em `widget.py`: aquele arquivo e o ciclo do
WebSocket, e esta e uma leitura HTTP sem nada em comum com ele.

Quem chama e o servidor do Next (`/embed/aparencia`), e nao o navegador: o
`RateLimitPorIP` ve o IP dele, e e o cache de 60 s de la que impede todos os
visitantes de caberem num balde so (D4).
"""

from fastapi import APIRouter

from mobia.app.config import get_settings
from mobia.domain.configuracao.repositorio import configuracao_vigente
from mobia.domain.configuracao.vigente import PosicaoDoBotao
from mobia.infra.db import get_sessionmaker

router = APIRouter(tags=["widget"])


@router.get("/widget/aparencia")
async def aparencia() -> dict[str, object]:
    async with get_sessionmaker()() as session:
        config = await configuracao_vigente(session)
    return {
        # `Settings` ja fez do `TENANT_SLUG=` vazio um nulo.
        "tenant": get_settings().tenant_slug,
        "nomeDoAssistente": config.nome_do_assistente,
        "corPrimaria": config.cor_primaria,
        "posicaoDoBotao": PosicaoDoBotao(config.posicao_do_botao).value,
    }
