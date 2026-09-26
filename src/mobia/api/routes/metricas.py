"""Os paineis gerenciais: o funil (TEC-190, RN-17.1 a RN-17.3) e o custo de IA
(TEC-191, RN-17.4).

**Os dois guardados por `VER_FUNIL`, que ADMIN, GERENTE e LEITURA tem e CORRETOR nao**
(TEC-202). Ate aqui era o `exigir_admin`: o SRS (secao 6.6) previa Bearer JWT
com papel, e papel nao existia -- `corretores.gerente` e booleana de roteamento
de escalada de SLA, nao autorizacao HTTP. A divergencia que a Emenda E-01 da
RN-19.5 declarou, e que esta rota herdou, fecha aqui para quem entra por JWT.

**O CORRETOR fica de fora de proposito**, e nao por esquecimento: e a matriz de
navegacao da RN-FE-03.1 (TEC-312). O funil e da operacao inteira, e o corretor
trabalha a propria carteira.

**Consequencia que permanece: quem tem o `X-Admin-Token` le os dois paineis**,
porque ele resolve para um ADMIN sintetico (D2 da TEC-202). Nao ha dado pessoal
de lead na resposta -- so contagens e medias --, o que torna esta exposicao
menos grave que a de `corretores.py`, mas ela existe.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.configuracao.repositorio import configuracao_vigente
from mobia.domain.metricas import custo
from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.filtros import FiltroInvalido, montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/metricas", tags=["metricas"])


@router.get("/funil")
async def funil(
    de: Annotated[date, Query()],
    ate: Annotated[date, Query()],
    canal: Annotated[str | None, Query()] = None,
    intencao: Annotated[str | None, Query()] = None,
    temperatura: Annotated[str | None, Query()] = None,
    corretor_id: Annotated[uuid.UUID | None, Query(alias="corretorId")] = None,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_FUNIL)),
) -> dict[str, object]:
    """O funil da coorte e os indicadores do periodo.

    Periodo sem lead nenhum devolve 200 com tudo zerado e as taxas nulas --
    nao 404. Ausencia de lead e um fato sobre o negocio, nao sobre a rota.
    """
    try:
        recorte = montar_recorte(
            de=de,
            ate=ate,
            fuso=get_settings().fuso_de_envio,
            canal=canal,
            intencao=intencao,
            temperatura=temperatura,
            corretor_id=corretor_id,
        )
    except FiltroInvalido as erro:
        # 422 com o nome do campo e o valor recusado. Um funil vazio aqui se
        # leria como "nenhum lead no periodo", que e afirmacao sobre o
        # negocio -- e o erro e de quem chamou.
        # `UNPROCESSABLE_CONTENT` e nao `UNPROCESSABLE_ENTITY`: o segundo esta
        # deprecado nesta versao do Starlette e emite warning a cada chamada.
        # Os dois valem 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        etapas = await contar_etapas(session, recorte=recorte)
        indicadores = await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])

    corpo_dos_indicadores: dict[str, object] = {
        "leadsNovos": etapas[Etapa.NOVO],
        "conversasAtivas": indicadores.conversas_ativas,
        "taxaQualificacao": indicadores.taxa_qualificacao,
        "distribuicaoPorTemperatura": indicadores.distribuicao_por_temperatura,
        "tempoMedioPrimeiraRespostaSeg": indicadores.tempo_medio_primeira_resposta_seg,
        "tempoMedioQualificacaoSeg": indicadores.tempo_medio_qualificacao_seg,
        "slaHandoffCumpridoPct": indicadores.sla_handoff_cumprido_pct,
        "agendamentosCriados": indicadores.agendamentos_criados,
        "agendamentosConfirmados": indicadores.agendamentos_confirmados,
        "agendamentosRealizados": indicadores.agendamentos_realizados,
        "taxaNoShow": indicadores.taxa_no_show,
    }

    return {
        "etapas": [
            {
                "nome": etapa.nome,
                "quantidade": etapa.quantidade,
                "disponivel": etapa.disponivel,
                "conversaoDaAnterior": etapa.conversao_da_anterior,
            }
            for etapa in montar_funil(etapas)
        ],
        "indicadores": corpo_dos_indicadores,
        # Vazia desde a TEC-376, e a chave FICA -- mesmo argumento de
        # `etapas[].disponivel` em `calculo.py`. Ela nomeava os quatro de
        # agendamento enquanto nenhum caminho de producao criasse linha; a
        # TEC-371 acabou com isso. Omiti-la agora faria o consumidor tratar a
        # ausencia como erro dele.
        "indisponiveis": [],
    }


def _dolares(valor: Decimal | None) -> float | None:
    return float(valor) if valor is not None else None


@router.get("/custo-ia")
async def custo_de_ia(
    de: Annotated[date, Query()],
    ate: Annotated[date, Query()],
    canal: Annotated[str | None, Query()] = None,
    intencao: Annotated[str | None, Query()] = None,
    temperatura: Annotated[str | None, Query()] = None,
    corretor_id: Annotated[uuid.UUID | None, Query(alias="corretorId")] = None,
    _: IdentidadeDaRequisicao = Depends(Exige(Permissao.VER_FUNIL)),
) -> dict[str, object]:
    """O painel de custo de IA. TEC-191, RN-17.4.

    **Os filtros sao os do funil, pelo mesmo `montar_recorte`** -- inclusive a
    recusa de `corretorId`. Mas o periodo conta quando o gasto aconteceu, e
    nao a coorte (D1 do desenho): ver `domain/metricas/custo.py`.

    **A mesma permissao do funil.** A historia e da gerente comercial, e aqui
    nao ha dado pessoal -- so somas.

    Periodo sem gasto devolve 200 com o total zerado e as medias nulas: media
    zero afirmaria que a conversa custou zero, e nao houve conversa.
    """
    try:
        recorte = montar_recorte(
            de=de,
            ate=ate,
            fuso=get_settings().fuso_de_envio,
            canal=canal,
            intencao=intencao,
            temperatura=temperatura,
            corretor_id=corretor_id,
        )
    except FiltroInvalido as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    async with get_sessionmaker()() as session:
        periodo = await custo.custo_do_periodo(session, recorte=recorte)
        mensal = (await configuracao_vigente(session)).orcamento_mensal_usd
        orcamento = (
            custo.avaliar_orcamento(
                mensal,
                dias=(ate - de).days + 1,
                # D3: o orcamento e da operacao, e o consumo dele ignora os
                # filtros -- filtrar para investigar nao pode apagar o alerta.
                consumido=await custo.total_sem_filtros(session, recorte=recorte),
            )
            if mensal is not None
            else None
        )

    por_lead = custo.media(periodo.total_usd, periodo.leads_qualificados)
    return {
        "custoTotalUsd": _dolares(periodo.total_usd),
        "custoPorConversaUsd": _dolares(custo.media(periodo.total_usd, periodo.conversas)),
        "custoPorLeadQualificadoUsd": _dolares(por_lead),
        "tokensPorModelo": {
            modelo: {
                "entrada": t.entrada,
                "saida": t.saida,
                "cacheLeitura": t.cache_leitura,
                "cacheEscrita": t.cache_escrita,
            }
            for modelo, t in periodo.tokens_por_modelo.items()
        },
        "conversas": periodo.conversas,
        "leadsQualificados": periodo.leads_qualificados,
        "mensagensSemPreco": periodo.mensagens_sem_preco,
        "alvoPorLeadQualificadoUsd": _dolares(custo.ALVO_POR_LEAD_QUALIFICADO_USD),
        "acimaDoAlvo": (
            por_lead > custo.ALVO_POR_LEAD_QUALIFICADO_USD if por_lead is not None else None
        ),
        "orcamento": (
            {
                "mensalUsd": _dolares(orcamento.mensal_usd),
                "doPeriodoUsd": _dolares(orcamento.do_periodo_usd),
                "consumidoUsd": _dolares(orcamento.consumido_usd),
                "consumidoPct": _dolares(orcamento.consumido_pct),
                "alerta": orcamento.alerta,
            }
            if orcamento is not None
            else None
        ),
    }
