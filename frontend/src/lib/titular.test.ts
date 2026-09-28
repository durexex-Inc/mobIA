import { describe, expect, it } from 'vitest'

import { dataLegivel, destacado, diasRestantes, origemLegivel, textoDoPrazo, tipoLegivel } from './titular'

const DIA_MS = 86_400_000

// Meio-dia em Sao Paulo (15h UTC), para a hora nao mexer na conta.
const AGORA = new Date('2026-09-28T15:00:00Z')

function abertoHa(dias: number): string {
  return new Date(AGORA.getTime() - dias * DIA_MS + 15 * DIA_MS).toISOString()
}

describe('prazo do pedido do titular (TEC-340, D3)', () => {
  it.each([
    [2, 13, false],
    [12, 3, true],
    [14, 1, true],
  ])('aberto ha %i dias: restam %i, destacado=%s (tabela da card)', (dias, restante, comDestaque) => {
    expect(diasRestantes(abertoHa(dias), AGORA)).toBe(restante)
    expect(destacado(restante)).toBe(comDestaque)
  })

  it('a conta e por dia de calendario em Sao Paulo, e nao por horas', () => {
    // Prazo as 23h30 de 30/09 em Sao Paulo (02h30 UTC de 01/10); agora, 00h10
    // de 28/09 em Sao Paulo. Por horas seriam quase 3 dias inteiros; por data, 2.
    expect(diasRestantes('2026-10-01T02:30:00Z', new Date('2026-09-28T03:10:00Z'))).toBe(2)
    // A mesma data de prazo, perto da meia-noite do outro lado.
    expect(diasRestantes('2026-10-01T02:30:00Z', new Date('2026-09-29T02:50:00Z'))).toBe(2)
  })

  it('a borda do destaque: 4 nao, 3 sim, vencido sim', () => {
    expect(destacado(4)).toBe(false)
    expect(destacado(3)).toBe(true)
    expect(destacado(0)).toBe(true)
    expect(destacado(-2)).toBe(true)
  })

  it.each([
    [13, '13 dias'],
    [1, '1 dia'],
    [0, 'Vence hoje'],
    [-1, 'Vencido há 1 dia'],
    [-3, 'Vencido há 3 dias'],
  ])('textoDoPrazo(%i) = %s', (restante, texto) => {
    expect(textoDoPrazo(restante)).toBe(texto)
  })

  it('a data de abertura sai em Sao Paulo', () => {
    // 02h de 28/09 em UTC ainda e 27/09 em Sao Paulo.
    expect(dataLegivel('2026-09-28T02:00:00Z')).toBe('27/09/2026')
  })

  it('rotulos de tipo e origem, e o desconhecido como veio', () => {
    expect(tipoLegivel('ELIMINACAO')).toBe('Eliminação dos dados')
    expect(tipoLegivel('ACESSO')).toBe('Acesso aos dados')
    expect(origemLegivel('WHATSAPP')).toBe('WhatsApp')
    expect(origemLegivel('ADMIN')).toBe('Administrativo')
    expect(tipoLegivel('PORTABILIDADE')).toBe('PORTABILIDADE')
  })
})
