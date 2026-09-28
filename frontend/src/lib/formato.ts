import { TEXTO_SEM_FONTE } from './estados'
import type { Etapa } from './metricas'

const PERCENTUAL = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const INTEIRO = new Intl.NumberFormat('pt-BR')

/**
 * Percentual em pt-BR, ou travessao quando nao ha numero.
 *
 * **Zero nao e nulo aqui**: `0` e uma conversao medida de 0%, e `null` e a
 * ausencia de conversao calculavel. A spec distingue tres origens de `null`
 * -- primeira etapa, etapa anterior indisponivel, etapa anterior em zero --
 * e as tres se renderizam igual, mas nenhuma delas se confunde com 0%.
 */
export function percentual(valor: number | null): string {
  return valor === null ? '—' : PERCENTUAL.format(valor)
}

/**
 * O que se escreve no lugar da quantidade.
 *
 * `disponivel: false` NUNCA vira `0`: zero afirmaria que nada aconteceu no
 * periodo, quando a verdade e que nada e registrado. Ver a D1 do desenho.
 */
export function quantidadeLegivel(etapa: Etapa): string {
  if (!etapa.disponivel || etapa.quantidade === null) {
    // TEC-313: o texto mudou de "sem fonte de dados" para o vocabulario unico
    // da RN-FE-04.2. A etapa do funil entra junto com os indicadores de
    // proposito -- deixar so os indicadores mudarem poria dois idiomas para a
    // mesma ausencia na MESMA tela, que e pior que tocar tres linhas de uma
    // card vizinha. O comportamento da etapa (nao calcular conversao para quem
    // nao tem fonte) e o de `Funil.tsx::conversaoConfiavel` (TEC-315).
    return TEXTO_SEM_FONTE
  }
  return INTEIRO.format(etapa.quantidade)
}

/**
 * Acima de 100% e "coorte incompleta" (TEC-315, RT-FE-02): nao e erro de
 * consulta, e etapas medidas por periodos diferentes -- ver a D10 do desenho
 * da TEC-190. So `Funil.tsx` chama isto: `Indicadores.tsx` tambem usa
 * `percentual` para fracoes sem essa semantica (taxa de qualificacao, SLA), e
 * nao devem ganhar este aviso.
 */
export function coorteIncompleta(valor: number | null): boolean {
  return valor !== null && valor > 1
}
