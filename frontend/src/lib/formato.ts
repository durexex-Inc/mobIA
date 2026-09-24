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
    return 'sem fonte de dados'
  }
  return INTEIRO.format(etapa.quantidade)
}
