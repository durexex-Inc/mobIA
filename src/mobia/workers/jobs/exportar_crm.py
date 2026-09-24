"""O job que exporta o handoff para o CRM. TEC-180, RN-16.5.

**As tres tentativas se contam no BANCO, e isso nao e preferencia de estilo.**
Deixar o `max_tries` do ARQ conta-las produziria exatamente a perda silenciosa
que a RN-16.5 proibe, e a razao esta na fonte do `arq` 0.28.0, em
`Worker.run_job`:

    max_tries = self.max_tries if function.max_tries is None else function.max_tries
    if job_try > max_tries:
        logger.warning('%6.2fs ! %s max retries %d exceeded', t, ref, max_tries)
        ...
        return await asyncio.shield(self.finish_failed_job(job_id, result_data))

Estourado o teto, **o ARQ nao chama esta corrotina**: ele loga um `warning`
proprio, com texto dele e sem `handoff_id`, e encerra o job. Com `max_tries=3`
na inscricao, a terceira falha acabaria sem que uma linha daqui rodasse --
nada marcaria a linha, nada emitiria o alerta, e o rastro seria uma mensagem
de biblioteca que nenhum alerta casa. Por isso a contagem e
`handoffs.crm_tentativas`, e por isso a terceira falha **nao levanta `Retry`**:
o desfecho permanente e decisao nossa, tomada por codigo nosso. Ver a D3 do
desenho.

O `max_tries` do ARQ continua valendo como rede para o que ele deve cobrir --
o worker morrer no meio de uma tentativa --, nunca como o mecanismo da regra.

**O alerta e `crm.exportacao_falhou_permanente`, em `error`.** Nao existe regra
de alerta neste repositorio -- `domain/outbound/port.py` ja escreve isso por
extenso: ela vive no monitoramento externo, que casa por nome. Este docstring e
a D9 do desenho sao os dois lugares que dizem qual nome observar.
"""

import uuid
from typing import Any

import structlog
from arq.worker import Retry

from mobia.app.config import Settings, get_settings
from mobia.domain.crm.payload import montar
from mobia.domain.crm.port import MAX_TENTATIVAS, CrmPort, FalhaDeExportacao
from mobia.domain.crm.repositorio import (
    carregar_estado,
    marcar_sincronizado,
    registrar_falha,
)
from mobia.domain.handoff.repositorio import carregar_dossie

log = structlog.get_logger(__name__)

EXPORTAR_CRM_JOB = "exportar_crm"

ResultadoDaExportacao = str


def espera_de(tentativas: int, base: float) -> float:
    """O backoff exponencial da RN-16.5: base, base x 2, base x 4...

    `tentativas` e quantas JA falharam, entao a primeira espera usa o expoente
    zero. Com a base de 30 s: 30 s depois da primeira falha, 60 s depois da
    segunda. Nao ha terceira espera -- a terceira falha e terminal.

    Funcao separada, e nao uma expressao dentro do job, porque e a unica parte
    da regra que da para testar sem banco e sem rede.
    """
    return base * 2 ** (tentativas - 1)


async def exportar_crm(ctx: dict[str, Any], handoff_id: str) -> ResultadoDaExportacao:
    """Exporta um handoff para o CRM. Devolve um rotulo para o log do ARQ.

    A porta vem do `ctx` e nao e construida aqui, no mesmo molde de
    `gerar_resumo` e `notificar_corretor`: e o `startup` do worker que decide a
    implementacao, e o teste troca a decisao sem tocar no job.

    A ordem das saidas antecipadas importa:

    1. **Sem porta** (`CRM_WEBHOOK_URL` vazia) -- a exportacao esta desligada
       nesta maquina e nao ha o que fazer. Sai antes de tocar o banco.
    2. **Ja sincronizado** -- a guarda de idempotencia da D6. Cobre o reenqueue
       duplicado que o `_job_id` derivado so cobre enquanto o job esta vivo; e
       a mesma lacuna que a L3 do desenho da TEC-177 declarou para a
       notificacao, fechada aqui porque o outro lado e um sistema de terceiro.
    3. **Sem dossie** -- o handoff sumiu entre o enqueue e agora. Loga e sai,
       como `carregar_dossie` manda.
    """
    porta: CrmPort | None = ctx.get("crm")
    if porta is None:
        return "desligado"

    settings: Settings = ctx.get("settings") or get_settings()
    session_factory = ctx["session_factory"]
    identificador = uuid.UUID(handoff_id)

    async with session_factory() as session:
        estado = await carregar_estado(session, handoff_id=identificador)
        if estado is None:
            log.warning("crm.handoff_ausente", handoff_id=handoff_id)
            return "sem_handoff"
        if estado.ja_sincronizado:
            return "ja_sincronizado"

        dossie = await carregar_dossie(session, handoff_id=identificador)
        if dossie is None:
            # `carregar_estado` achou a linha e `carregar_dossie` nao: a linha
            # sumiu entre as duas leituras. Rotulo proprio, e nao o
            # `sem_handoff` acima, para que o log diga em qual das duas.
            log.warning("crm.dossie_ausente", handoff_id=handoff_id)
            return "sem_dossie"

    payload = montar(
        handoff_id=identificador,
        dossie=dossie,
        resumo=estado.resumo,
        resumo_fallback=estado.resumo_fallback,
    )

    try:
        await porta.exportar(handoff_id=identificador, payload=payload)
    except FalhaDeExportacao as falha:
        async with session_factory() as session:
            tentativas = await registrar_falha(
                session, handoff_id=identificador, motivo=falha.motivo
            )
            await session.commit()

        if tentativas < MAX_TENTATIVAS:
            log.warning(
                "crm.exportacao_falhou",
                handoff_id=handoff_id,
                tentativas=tentativas,
                motivo=falha.motivo,
            )
            # `Retry` e nao `asyncio.sleep`: as esperas somadas (90 s com a
            # base padrao) cabem no `job_timeout` de 240 s, mas segurariam o
            # slot do worker parado, tirando essa folga de quem precisa dela --
            # o mesmo worker roda `process_message`.
            #
            # `from None` e nao `from falha`: `Retry` nao e erro, e sinalizacao
            # de controle que o ARQ le para devolver o job a fila. Encadear a
            # falha faria o traceback do ARQ mostrar uma excecao causadora, e
            # quem lesse o log concluiria que algo escapou sem tratamento --
            # quando o tratamento e exatamente esta linha. O motivo nao se
            # perde: ele acabou de ir para `crm_ultimo_erro` e para o
            # `crm.exportacao_falhou` acima.
            raise Retry(defer=espera_de(tentativas, settings.crm_backoff_base_segundos)) from None

        # A terceira falha NAO levanta: ver o cabecalho do modulo. E aqui que a
        # RN-16.5 se cumpre -- "falha permanente vira alerta, nao perda
        # silenciosa".
        log.error(
            "crm.exportacao_falhou_permanente",
            handoff_id=handoff_id,
            tentativas=tentativas,
            motivo=falha.motivo,
        )
        return "falhou"

    async with session_factory() as session:
        await marcar_sincronizado(session, handoff_id=identificador)
        await session.commit()

    log.info("crm.exportado", handoff_id=handoff_id, tentativas=estado.tentativas)
    return "exportado"
