import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import PaginaDeEdicaoDeImovel from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const cookiesDaRequisicao = new Map<string, string>()
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (nome: string) =>
      cookiesDaRequisicao.has(nome) ? { value: cookiesDaRequisicao.get(nome) } : undefined,
  }),
}))

vi.mock('next/navigation', () => ({
  redirect: (destino: string) => {
    throw new Error(`REDIRECT:${destino}`)
  },
  notFound: () => {
    throw new Error('NOT_FOUND')
  },
  // `EdicaoDeImovel` e Client Component e chama `useRouter` ao montar.
  useRouter: () => ({ refresh: () => {} }),
}))

const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['GERIR_CATALOGO', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

const IMOVEL = {
  id: '0f8f2b1e-5d6a-4c1a-9e1e-3b2a1c0d9e8f',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  status: 'DISPONIVEL',
  precoVenda: 35_000_000,
  precoAluguel: null,
  condominio: null,
  iptuMensal: null,
  bairro: 'Centro',
  cidade: 'Porto Alegre',
  uf: 'RS',
  zona: null,
  latitude: null,
  longitude: null,
  areaUtilM2: 70,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  caracteristicas: [],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

/** `/auth/me` com o papel; qualquer outro caminho devolve `imovel`. */
function api(papel: string, imovel: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    if (new URL(String(url)).pathname === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    return new Response(JSON.stringify(imovel.corpo), {
      status: imovel.status ?? 200,
      headers: imovel.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

const params = (id: string) => Promise.resolve({ id })

describe('PaginaDeEdicaoDeImovel (TEC-400)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca o imovel pelo id e mostra a edicao', async () => {
    const chamadas = api('ADMIN', { corpo: IMOVEL })

    render(await PaginaDeEdicaoDeImovel({ params: params(IMOVEL.id) }))

    const caminhos = chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)
    expect(caminhos).toContain(`/api/v1/imoveis/${IMOVEL.id}`)
    expect(screen.getByRole('heading', { name: 'Editar imóvel' })).toBeInTheDocument()
    expect(screen.getByLabelText('Título do anúncio')).toHaveValue('Apartamento no Centro')
  })

  it('404 e 422 do backend sao "nao encontrado"', async () => {
    api('ADMIN', { corpo: { detail: 'imovel nao existe' }, status: 404 })
    await expect(PaginaDeEdicaoDeImovel({ params: params(IMOVEL.id) })).rejects.toThrow('NOT_FOUND')

    api('ADMIN', { corpo: { detail: [] }, status: 422 })
    await expect(PaginaDeEdicaoDeImovel({ params: params('nao-e-uuid') })).rejects.toThrow('NOT_FOUND')
  })

  it('CORRETOR sem GERIR_CATALOGO ve "Sem permissao", e o imovel nao e pedido', async () => {
    const chamadas = api('CORRETOR', { corpo: IMOVEL })

    render(await PaginaDeEdicaoDeImovel({ params: params(IMOVEL.id) }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual(['/api/v1/auth/me'])
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'falhou' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDeEdicaoDeImovel({ params: params(IMOVEL.id) }))

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar o imóvel.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })
})
