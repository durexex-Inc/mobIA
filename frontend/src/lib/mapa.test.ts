import { describe, expect, it } from 'vitest'

import { mapaEmbutido, mapaGrande } from './mapa'

describe('mapa', () => {
  it('o mapa embutido e do host que a CSP libera, com o pino no centro da caixa', () => {
    const url = new URL(mapaEmbutido(-27.584, -48.505))

    expect(url.origin).toBe('https://www.openstreetmap.org')
    expect(url.pathname).toBe('/export/embed.html')
    expect(url.searchParams.get('marker')).toBe('-27.584,-48.505')
    expect(url.searchParams.get('bbox')).toBe('-48.511000,-27.588000,-48.499000,-27.580000')
  })

  it('o mapa grande abre no mesmo ponto', () => {
    expect(mapaGrande(-27.584, -48.505)).toBe(
      'https://www.openstreetmap.org/?mlat=-27.584&mlon=-48.505#map=16/-27.584/-48.505',
    )
  })
})
