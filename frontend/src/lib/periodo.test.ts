import { describe, expect, it } from 'vitest'

import { periodoPadrao } from './periodo'

describe('periodoPadrao', () => {
  it('sao os ultimos 30 dias, inclusive hoje', () => {
    expect(periodoPadrao(new Date('2026-09-24T12:00:00Z'))).toEqual({
      de: '2026-08-26',
      ate: '2026-09-24',
    })
  })

  it('atravessa a virada de ano sem quebrar', () => {
    expect(periodoPadrao(new Date('2026-01-10T12:00:00Z'))).toEqual({
      de: '2025-12-12',
      ate: '2026-01-10',
    })
  })
})
