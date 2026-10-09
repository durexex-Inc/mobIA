import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DetalheDoImovel from './page'

/**
 * Duble o `fetch`, e nao `buscarDetalheDoImovel` (`vi.mock` + `mockRejectedValue`).
 *
 * A funcao servidor roda de verdade e produz o `ErroDoPortal` pelo caminho
 * real -- mesmo padrao de `leads/[leadId]/page.test.tsx`. Mockar a funcao
 * servidor diretamente com `mockRejectedValue`/`mockImplementation(() =>
 * Promise.reject(...))` cria uma promessa rejeitada fora do fluxo normal de
 * chamada, e o Node as vezes marca essa promessa como "sem tratamento" antes
 * do `Promise.allSettled` da pagina conseguir anexar o handler dele --
 * mesmo com o erro sendo tratado corretamente depois. Dublar o `fetch` evita
 * isso de raiz: o `throw` acontece dentro da chamada real, no mesmo fluxo
 * que o `await` da pagina ja acompanha.
 */
function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status })
}

function detalhe(sobrescreve: Record<string, unknown> = {}) {
  return {
    id: 'i-1',
    codigo: 'IT-9821',
    titulo: 'Apartamento com vista',
    descricao: 'Sala ampla com varanda e vista para o mar.',
    tipo: 'APARTAMENTO',
    operacao: 'VENDA',
    bairro: 'Centro',
    cidade: 'Florianópolis',
    uf: 'SC',
    areaUtilM2: 74,
    quartos: 2,
    suites: 1,
    banheiros: 2,
    vagas: 1,
    precoVenda: 58000000,
    precoAluguel: null,
    condominio: 65000,
    iptuMensal: null,
    caracteristicas: ['varanda', 'vista para o mar'],
    fotos: ['/portal/imoveis/i-1/fotos/f-1'],
    latitude: -27.584,
    longitude: -48.505,
    ...sobrescreve,
  }
}

async function paginaCom(id: string) {
  return DetalheDoImovel({ params: Promise.resolve({ id }), searchParams: Promise.resolve({}) })
}

describe('DetalheDoImovel', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('CA-01: mostra fotos, descricao e caracteristicas', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde(detalhe())))

    render(await paginaCom('i-1'))

    expect(screen.getByRole('heading', { name: 'Apartamento com vista' })).toBeInTheDocument()
    expect(screen.getByText(/Sala ampla com varanda/)).toBeInTheDocument()
    expect(screen.getByText('varanda')).toBeInTheDocument()
    expect(screen.getByText('vista para o mar')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Apartamento com vista/ })).toHaveAttribute(
      'src',
      '/portal/imoveis/i-1/fotos/f-1',
    )
  })

  it('CA-02: sem foto, mostra o estado vazio em vez de uma galeria vazia', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde(detalhe({ fotos: [] }))))

    render(await paginaCom('i-1'))

    expect(screen.getByText('Este imóvel ainda não tem foto cadastrada.')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('mostra o codigo, a operacao e o tipo como selos', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde(detalhe({ operacao: 'AMBOS' }))))

    render(await paginaCom('i-1'))

    expect(screen.getByText('Cód. IT-9821')).toBeInTheDocument()
    expect(screen.getByText('Venda e locação')).toBeInTheDocument()
    expect(screen.getByText('Apartamento')).toBeInTheDocument()
  })

  it('com coordenada, mostra o mapa do OpenStreetMap no ponto do imovel', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde(detalhe())))

    render(await paginaCom('i-1'))

    const mapa = screen.getByTitle('Mapa de Centro, Florianópolis')
    expect(mapa.getAttribute('src')).toContain('https://www.openstreetmap.org/export/embed.html?')
    expect(mapa.getAttribute('src')).toContain('marker=-27.584%2C-48.505')
  })

  it('sem coordenada, a secao de localizacao nao aparece', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde(detalhe({ latitude: null, longitude: null }))),
    )

    render(await paginaCom('i-1'))

    expect(screen.queryByRole('heading', { name: 'Localização' })).toBeNull()
  })

  it('CA-03: 404 vira "Imóvel não encontrado"', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'imovel nao disponivel' }, 404)),
    )

    render(await paginaCom('i-1'))

    expect(screen.getByRole('heading', { name: 'Imóvel não encontrado' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Voltar para a busca' })).toBeInTheDocument()
  })

  it('CA-03: 422 (id malformado) vira a mesma tela que 404', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde({ detail: 'nao e um uuid' }, 422)))

    render(await paginaCom('nao-e-um-uuid'))

    expect(screen.getByRole('heading', { name: 'Imóvel não encontrado' })).toBeInTheDocument()
  })

  it('outro erro mostra a tela de erro de carga, com "tentar de novo"', async () => {
    // `X-Request-Id` so existe se a resposta chegou -- a mesma logica de
    // `ErroDeCarga`/`detalheDe` em `lib/metricas.ts`.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'falha interna' }), {
          status: 500,
          headers: { 'X-Request-Id': 'req-1' },
        }),
      ),
    )

    render(await paginaCom('i-1'))

    expect(screen.getByText('Não foi possível carregar o imóvel.')).toBeInTheDocument()
    expect(screen.getByText('req-1')).toBeInTheDocument()
  })
})
