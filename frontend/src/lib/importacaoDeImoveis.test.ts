import { describe, expect, it } from 'vitest'

import { INTERVALO_DE_POLLING_MS, TETO_DE_UPLOAD_EM_BYTES } from './importacaoDeImoveis'

describe('constantes da importacao (D2, D3)', () => {
  it('TETO_DE_UPLOAD_EM_BYTES e 10 MB -- o mesmo valor do backend (api/routes/imoveis.py)', () => {
    expect(TETO_DE_UPLOAD_EM_BYTES).toBe(10 * 1024 * 1024)
  })

  it('INTERVALO_DE_POLLING_MS e 3 segundos', () => {
    expect(INTERVALO_DE_POLLING_MS).toBe(3000)
  })
})
