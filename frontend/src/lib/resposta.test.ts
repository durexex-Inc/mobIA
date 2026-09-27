import { describe, expect, it } from 'vitest'

import {
  contador,
  EXPLICACAO_DA_JANELA,
  janelaFechada,
  LIMITE_DA_RESPOSTA,
  podeEnviar,
  recusaDaResposta,
} from './resposta'

describe('contador', () => {
  it('diz quanto passou do limite', () => {
    expect(contador('a'.repeat(LIMITE_DA_RESPOSTA))).toEqual({ usados: 1000, excesso: 0 })
    expect(contador('a'.repeat(1001))).toEqual({ usados: 1001, excesso: 1 })
  })

  it('bloqueia o envio vazio e o que passa do limite', () => {
    expect(podeEnviar('   ')).toBe(false)
    expect(podeEnviar('a'.repeat(1001))).toBe(false)
    expect(podeEnviar('Oi, sou o Paulo')).toBe(true)
  })
})

describe('janelaFechada', () => {
  const FECHA = '2026-09-28T12:00:00.000Z'

  it('a borda e estrita: no instante do fechamento ja fechou', () => {
    expect(janelaFechada({ fechaEm: FECHA, ultimaFalaDoLeadEm: null, agora: new Date('2026-09-28T11:59:59.999Z') })).toBe(false)
    expect(janelaFechada({ fechaEm: FECHA, ultimaFalaDoLeadEm: null, agora: new Date(FECHA) })).toBe(true)
  })

  it('sem janela (site, ou quem nunca falou), nunca fecha', () => {
    expect(janelaFechada({ fechaEm: null, ultimaFalaDoLeadEm: null, agora: new Date('2030-01-01') })).toBe(false)
  })

  it('a fala nova do lead reabre, e a antiga nao encurta', () => {
    const agora = new Date('2026-09-28T13:00:00.000Z')
    expect(janelaFechada({ fechaEm: FECHA, ultimaFalaDoLeadEm: '2026-09-28T12:30:00.000Z', agora })).toBe(false)
    expect(janelaFechada({ fechaEm: FECHA, ultimaFalaDoLeadEm: '2026-09-26T00:00:00.000Z', agora })).toBe(true)
  })
})

describe('recusaDaResposta', () => {
  it('janela e opt-out desabilitam o campo', () => {
    expect(recusaDaResposta(409, 'janela_fechada')).toEqual({ mensagem: EXPLICACAO_DA_JANELA, bloqueia: 'janela' })
    expect(recusaDaResposta(409, 'lead_em_optout').bloqueia).toBe('optout')
    expect(recusaDaResposta(409, 'conversa_de_outro').bloqueia).toBe('outro')
  })

  it('o que pode dar certo tentando de novo nao desabilita', () => {
    expect(recusaDaResposta(502, 'canal_falhou')).toEqual({
      mensagem: 'Não foi possível entregar a mensagem. Tente de novo.',
      bloqueia: null,
    })
    expect(recusaDaResposta(409, 'fala_em_envio').bloqueia).toBeNull()
    expect(recusaDaResposta(500, null).bloqueia).toBeNull()
  })
})
