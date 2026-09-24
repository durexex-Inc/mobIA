"""O painel de funil. TEC-190, RF-17 e RN-17.1 a RN-17.3.

**Guardado pelo `exigir_admin`, e nao por papel GERENTE.** O SRS (secao 6.6)
preve Bearer JWT com papel, e ele nao existe: `corretores.gerente` e booleana
de roteamento de escalada de SLA, nao autorizacao HTTP, e JWT com papeis e a
TEC-201. Mesma divergencia que a Emenda E-01 da RN-19.5 ja declarou para o
modulo administrativo, aqui estendida a esta rota.

**Consequencia: quem tem o token le o funil inteiro da operacao.** Nao ha
dado pessoal de lead na resposta -- so contagens e medias --, o que torna
esta exposicao menos grave que a de `corretores.py`, mas ela existe.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mobia.api.deps import exigir_admin
from mobia.app.config import get_settings
from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.filtros import FiltroInvalido, montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import INDICADORES_SEM_FONTE, Etapa
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
    _: None = Depends(exigir_admin),
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
    }
    # Os quatro de visita saem SEMPRE, e sempre nulos: omiti-los faria o
    # consumidor tratar a ausencia como erro dele, e zera-los mentiria. Ver a
    # D1 do desenho.
    corpo_dos_indicadores.update(dict.fromkeys(INDICADORES_SEM_FONTE))

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
        "indisponiveis": list(INDICADORES_SEM_FONTE),
    }
