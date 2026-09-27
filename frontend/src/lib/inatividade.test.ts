import { describe, expect, it } from 'vitest'

import {
  faseDaInatividade,
  haAlteracaoNaoSalva,
  MINUTOS_ATE_O_AVISO,
  MINUTOS_OCIOSO_NO_SERVIDOR,
  registrarAlteracaoNaoSalva,
  SEGUNDOS_DE_CONTAGEM,
} from './inatividade'

const MINUTO = 60_000

describe('faseDaInatividade', () => {
  it('ativo antes dos 30 minutos', () => {
    expect(faseDaInatividade(29 * MINUTO, 0)).toEqual({ fase: 'ativo' })
  })

  it('aviso aos 30 minutos, com os 60 segundos inteiros', () => {
    expect(faseDaInatividade(30 * MINUTO, 0)).toEqual({ fase: 'aviso', segundosRestantes: 60 })
  })

  it('a contagem desce com o tempo', () => {
    expect(faseDaInatividade(30 * MINUTO + 45_000, 0)).toEqual({
      fase: 'aviso',
      segundosRestantes: 15,
    })
  })

  it('encerrar ao fim da contagem', () => {
    expect(faseDaInatividade(31 * MINUTO, 0)).toEqual({ fase: 'encerrar' })
  })

  it('a aba que acorda muito depois vai direto a encerrar', () => {
    // O motivo de comparar horarios em vez de contar com timer (D1).
    expect(faseDaInatividade(3 * 60 * MINUTO, 0)).toEqual({ fase: 'encerrar' })
  })
})

describe('o limite do servidor', () => {
  it('e maior que o do cliente mais um batimento de atraso (D3)', () => {
    // Se o servidor encerrasse antes, a pessoa perderia a sessao sem ver o
    // aviso. Este teste e o que impede alguem de baixar o 32 sem pensar.
    const clienteEncerraEm = MINUTOS_ATE_O_AVISO + SEGUNDOS_DE_CONTAGEM / 60
    expect(MINUTOS_OCIOSO_NO_SERVIDOR).toBeGreaterThanOrEqual(clienteEncerraEm + 1)
  })
})

describe('alteracoes nao salvas', () => {
  it('registra, e sai quando o formulario salva', () => {
    registrarAlteracaoNaoSalva('qualificacao', true)
    expect(haAlteracaoNaoSalva()).toBe(true)

    registrarAlteracaoNaoSalva('qualificacao', false)
    expect(haAlteracaoNaoSalva()).toBe(false)
  })
})
