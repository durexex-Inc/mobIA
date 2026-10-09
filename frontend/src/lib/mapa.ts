/**
 * Os enderecos do mapa do detalhe publico (D3 do desenho do visual do
 * portal).
 *
 * `ORIGEM_DO_MAPA` e tambem o que `proxy.ts` libera em `frame-src` -- uma
 * constante so, para que trocar o host do mapa troque a CSP junto. Mora aqui,
 * e nao no proxy, porque a pagina importa este modulo e nao deve arrastar o
 * proxy (e o Redis do embed) para a renderizacao.
 *
 * A margem em volta do pino mostra umas cinco quadras para cada lado -- o
 * bastante para reconhecer o bairro, ja que a coordenada chega arredondada
 * (`portal.py::_coordenada_publica`) e nao aponta o predio.
 */
export const ORIGEM_DO_MAPA = 'https://www.openstreetmap.org'

const MARGEM_DE_LATITUDE = 0.004
const MARGEM_DE_LONGITUDE = 0.006
const ZOOM_DO_MAPA_GRANDE = 16

export function mapaEmbutido(latitude: number, longitude: number): string {
  const caixa = [
    longitude - MARGEM_DE_LONGITUDE,
    latitude - MARGEM_DE_LATITUDE,
    longitude + MARGEM_DE_LONGITUDE,
    latitude + MARGEM_DE_LATITUDE,
  ]
    .map((valor) => valor.toFixed(6))
    .join(',')
  const parametros = new URLSearchParams({ bbox: caixa, layer: 'mapnik', marker: `${latitude},${longitude}` })
  return `${ORIGEM_DO_MAPA}/export/embed.html?${parametros}`
}

export function mapaGrande(latitude: number, longitude: number): string {
  const parametros = new URLSearchParams({ mlat: String(latitude), mlon: String(longitude) })
  return `${ORIGEM_DO_MAPA}/?${parametros}#map=${ZOOM_DO_MAPA_GRANDE}/${latitude}/${longitude}`
}
