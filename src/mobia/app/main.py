from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mobia.api.middleware import CorrelacaoDeRequisicao, RateLimitPorIP
from mobia.api.routes.aparencia_do_widget import router as aparencia_do_widget_router
from mobia.api.routes.auth import router as auth_router
from mobia.api.routes.portal import router as portal_router
from mobia.api.routes.simulador import router as simulador_router
from mobia.api.routes.whatsapp import router as whatsapp_router
from mobia.api.routes.widget import router as widget_router
from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.infra.db import dispose_engine
from mobia.infra.queue import create_redis_pool
from mobia.infra.rotacao import avisar_rotacao_vencida


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    avisar_rotacao_vencida(get_settings())
    if not hasattr(app.state, "redis_pool"):
        app.state.redis_pool = await create_redis_pool()
        app.state.owns_redis_pool = True
    yield
    # Antes do pool: a escuta da central usa uma conexao dele (TEC-124).
    central = getattr(app.state, "central_do_widget", None)
    if central is not None:
        await central.encerrar()
    if getattr(app.state, "owns_redis_pool", False):
        await app.state.redis_pool.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="mobIA", version="0.1.0", lifespan=lifespan)

    # Primeiro middleware do projeto (TEC-205). Aplica-se por omissao e nao por
    # opt-in: uma lista de rotas incluidas erraria para o lado de esquecer uma
    # rota nova, que e o erro caro. Quem precisa ficar de fora esta em
    # `ROTAS_ISENTAS`, com a razao de cada uma escrita la.
    #
    # **Ele nao cobre o widget, e ate a TEC-124 este comentario dizia que
    # sim.** `BaseHTTPMiddleware` devolve cedo para todo escopo que nao seja
    # `http`, entao o handshake de `/widget/chat` nunca passa por aqui. O
    # limite por IP daquela rota e aplicado dentro dela -- ver
    # `_cabe_no_limite_por_ip` em `api/routes/widget.py`.
    app.add_middleware(RateLimitPorIP)

    # **A ORDEM DESTAS DUAS LINHAS E DELIBERADA, e o efeito e o inverso do que
    # a leitura de cima para baixo sugere** (TEC-368).
    #
    # `add_middleware` insere no INDICE 0 (`starlette/applications.py:107`) e a
    # pilha e construida em `reversed` (`:81`), entao o ULTIMO adicionado fica
    # por FORA e roda PRIMEIRO. A correlacao vem depois no codigo justamente
    # para ficar por fora do limitador.
    #
    # Por que ela precisa ficar por fora: o `RateLimitPorIP` emite
    # `ratelimit.blocked` e devolve 429 SEM chamar `call_next`. Com a
    # correlacao por dentro, ela nao rodaria nesse caminho -- e o evento de
    # bloqueio, que e exatamente o que alguem vai depurar, sairia sem
    # `correlation_id`, com a resposta 429 sem o cabecalho. A requisicao que
    # mais interessa correlacionar seria a unica sem correlacao.
    #
    # Trocar as duas de lugar nao reprova em nenhum dos tres gates estaticos.
    # Quem reprova e `test_correlacao_envolve_o_limitador`.
    app.add_middleware(CorrelacaoDeRequisicao)

    # TEC-201. Import cedo e nao tardio como os administrativos abaixo: `auth`
    # produz a credencial que a guarda das outras rotas valida, e amarrar o
    # registro dela a alguma condicao faria a autenticacao nova depender de
    # configuracao para sequer existir.
    app.include_router(auth_router)
    app.include_router(whatsapp_router)
    # Publico por natureza: e o chat do site, e quem o abre e visitante anonima.
    app.include_router(widget_router)
    # TEC-344. Publica pelo mesmo motivo: e o que o loader do site le antes de
    # desenhar o botao.
    app.include_router(aparencia_do_widget_router)
    # TEC-387. Publica pelo mesmo motivo: e a vitrine do portal, e quem busca
    # e visitante anonima, antes de qualquer login.
    app.include_router(portal_router)
    # Ferramenta de desenvolvimento (simulador de WhatsApp). Publica porque
    # nao ha credencial nenhuma para exigir aqui -- a guarda de verdade e
    # `settings.em_producao`, conferida dentro da propria rota.
    app.include_router(simulador_router)

    # **A condicional da TEC-156 caiu na TEC-201, porque a premissa dela caiu.**
    #
    # O comentario que estava aqui dizia: "rota que nao existe nao pode ser
    # exposta por engano de configuracao, e este projeto ainda nao tem camada
    # de autenticacao". A segunda metade deixou de ser verdade -- `exigir_admin`
    # passou a exigir JWT de ADMIN (ou, ate a TEC-382, o token compartilhado), e
    # recusar com 403 e o que uma camada de autenticacao faz.
    #
    # **Manter a condicional teria efeito pior que o problema original:** com
    # JWT configurado e sem o token que a TEC-156 introduziu, as rotas
    # administrativas nao existiriam, e a autenticacao que a TEC-201 acabou de
    # construir seria inutil sozinha. Quem quisesse usa-la precisaria manter
    # configurado justamente o token que ela veio substituir -- e a TEC-382
    # apagou esse token de vez, o que faria a condicional ficar sempre
    # verdadeira e a mensagem abaixo, permanente.
    #
    # O que protege agora e a guarda, nao a ausencia da rota. Ver a D2 do
    # desenho da TEC-201 e a D1 da TEC-156, cujo argumento fica registrado como
    # historico de uma fase em que nao havia alternativa.
    # **`leads` entra neste bloco sem ser administrativa**, e a distincao
    # vale a linha: as cinco de cima nasceram condicionadas ao token
    # compartilhado e o bloco descreve a queda daquela condicional (TEC-201). A
    # de leads (TEC-192) nunca esteve condicionada -- ela esta aqui por ser
    # import tardio como as outras, e quem a protege e `VER_LEADS`, que os
    # quatro papeis tem, e `VER_DETALHE_DO_LEAD` no detalhe (TEC-193).
    # `configuracao` (TEC-198) e administrativa de fato: `CONFIGURAR_AGENTE`,
    # so do ADMIN, como `auditoria`. `prompts` (TEC-199) tambem, com a mesma
    # permissao. `mensagens` (TEC-209) e a dead-letter queue, com `OPERAR_FILA`,
    # tambem so do ADMIN.
    # `intervencao` (TEC-194) e o mesmo prefixo de `leads`, em arquivo proprio
    # porque muda estado; quem a protege e `ATENDER_LEAD` mais a checagem de
    # dono dentro do handler.
    # `auditoria` (TEC-206) entra pelo mesmo motivo de import tardio, e esta e
    # administrativa de fato: quem a protege e `VER_AUDITORIA`, so do ADMIN.
    # `agendamentos` (TEC-374) tambem e so import tardio, e tambem nao e
    # administrativa: quem a protege e `ATENDER_LEAD` mais a checagem de dono
    # dentro do handler, como em `handoffs`.
    # `titular` (TEC-207) e a fila de solicitacoes e o `GET`/`DELETE` de
    # `dados-pessoais` em cima do prefixo de `leads`; quem a protege e
    # `ATENDER_TITULAR`, so do ADMIN, como `auditoria`.
    # `interesses` (TEC-404) e a lista de pedidos do portal; nao e
    # administrativa: quem a protege e `VER_LEADS`, com o recorte do CORRETOR.
    from mobia.api.routes.agendamentos import router as agendamentos_router
    from mobia.api.routes.auditoria import router as auditoria_router
    from mobia.api.routes.configuracao import router as configuracao_router
    from mobia.api.routes.conversas import router as conversas_router
    from mobia.api.routes.corretores import router as corretores_router
    from mobia.api.routes.handoffs import router as handoffs_router
    from mobia.api.routes.imoveis import router as imoveis_router
    from mobia.api.routes.interesses import router as interesses_router
    from mobia.api.routes.intervencao import router as intervencao_router
    from mobia.api.routes.leads import router as leads_router
    from mobia.api.routes.mensagens import router as mensagens_router
    from mobia.api.routes.metricas import router as metricas_router
    from mobia.api.routes.prompts import router as prompts_router
    from mobia.api.routes.titular import router as titular_router

    app.include_router(imoveis_router)
    app.include_router(corretores_router)
    app.include_router(handoffs_router)
    app.include_router(conversas_router)
    app.include_router(metricas_router)
    app.include_router(leads_router)
    app.include_router(interesses_router)
    app.include_router(intervencao_router)
    app.include_router(auditoria_router)
    app.include_router(agendamentos_router)
    app.include_router(configuracao_router)
    app.include_router(prompts_router)
    app.include_router(mensagens_router)
    app.include_router(titular_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
