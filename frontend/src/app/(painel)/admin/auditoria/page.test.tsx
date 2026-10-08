import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDaAuditoria from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../../test/armazem-em-memoria')).moduloDeArmazem,
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
  // `FiltrosDeAuditoria` (TEC-343) e Client Component e chama `useRouter` ao
  // montar, mesmo sem interagir.
  useRouter: () => ({ push: () => {} }),
}))

/** Pela matriz da TEC-202: so o ADMIN tem VER_AUDITORIA. */
const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['VER_AUDITORIA', 'VER_FUNIL'],
  GERENTE: ['VER_DADOS_COMPLETOS', 'VER_FUNIL'],
}

function evento(extra: Record<string, unknown> = {}) {
  return {
    id: 'e-1',
    criadoEm: '2026-09-15T14:03:00+00:00',
    atorTipo: 'USUARIO',
    atorId: 'u-1',
    acao: 'DADO_PESSOAL_ACESSADO',
    entidade: 'lead',
    entidadeId: 'ref-1',
    campo: 'telefone',
    detalhes: null,
    ip: null,
    correlationId: null,
    ...extra,
  }
}

/** `/auth/me` com o papel, e a trilha com o corpo e o status pedidos. */
function api(papel: string, trilha: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    if (new URL(String(url)).pathname === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    return new Response(JSON.stringify(trilha.corpo), {
      status: trilha.status ?? 200,
      headers: trilha.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

function sp(params: Record<string, string> = {}) {
  return Promise.resolve(params)
}

describe('PaginaDaAuditoria (TEC-343)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ADMIN ve a trilha, do mais recente ao mais antigo', async () => {
    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: null } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.getByRole('heading', { name: 'Trilha de auditoria' })).toBeInTheDocument()
    const tabela = screen.getByRole('table')
    expect(within(tabela).getByText('Dado pessoal acessado')).toBeInTheDocument()
    expect(within(tabela).getByText('telefone')).toBeInTheDocument()
  })

  it('"Limpar filtros" so aparece com filtro ativo, e volta a trilha sem parametro (TEC-399, D6)', async () => {
    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: null } })
    const { unmount } = render(await PaginaDaAuditoria({ searchParams: sp() }))
    expect(screen.queryByRole('link', { name: 'Limpar filtros' })).toBeNull()
    unmount()

    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: null } })
    render(await PaginaDaAuditoria({ searchParams: sp({ ator: 'u-anelise' }) }))
    expect(screen.getByRole('link', { name: 'Limpar filtros' })).toHaveAttribute('href', '/admin/auditoria')
  })

  it('filtra por autor: o parametro chega ao FastAPI', async () => {
    const chamadas = api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    await PaginaDaAuditoria({ searchParams: sp({ ator: 'u-anelise' }) })

    const trilha = chamadas.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((u) => u.pathname === '/api/v1/auditoria')
    expect(trilha?.searchParams.get('ator')).toBe('u-anelise')
  })

  it('filtra por tipo "acesso negado" e mostra a tentativa (cenario 3 da card)', async () => {
    api('ADMIN', {
      corpo: {
        itens: [
          evento({
            id: 'e-negado',
            acao: 'ACESSO_NEGADO',
            atorId: 'u-paulo',
            entidade: 'rota',
            entidadeId: '/api/v1/prompts',
            campo: null,
            detalhes: { permissao: 'CONFIGURAR_AGENTE', motivo: 'sem_permissao', papel: 'CORRETOR', metodo: 'GET' },
          }),
        ],
        proximoCursor: null,
      },
    })

    render(await PaginaDaAuditoria({ searchParams: sp({ acao: 'ACESSO_NEGADO' }) }))

    const tabela = screen.getByRole('table')
    expect(within(tabela).getByText('Acesso negado')).toBeInTheDocument()
    expect(within(tabela).getByText(/u-paulo/)).toBeInTheDocument()
    expect(within(tabela).getByText(/motivo: sem_permissao/)).toBeInTheDocument()
  })

  it('nenhuma linha tem botao de editar ou excluir (cenario 2 da card)', async () => {
    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: null } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    const tabela = screen.getByRole('table')
    expect(within(tabela).queryByRole('button')).toBeNull()
    expect(within(tabela).queryByRole('link', { name: /editar/i })).toBeNull()
    expect(within(tabela).queryByRole('link', { name: /excluir/i })).toBeNull()
  })

  it('"Carregar mais" aparece so quando ha proximoCursor', async () => {
    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: 'cursor-2' } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    const link = screen.getByRole('link', { name: 'Carregar mais' })
    expect(new URL(link.getAttribute('href') ?? '', 'http://x').searchParams.get('cursor')).toBe('cursor-2')
  })

  it('sem proximoCursor, "Carregar mais" nao aparece', async () => {
    api('ADMIN', { corpo: { itens: [evento()], proximoCursor: null } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.queryByRole('link', { name: 'Carregar mais' })).toBeNull()
  })

  it('GERENTE sem VER_AUDITORIA ve "Sem permissao", e a trilha nao e pedida', async () => {
    const chamadas = api('GERENTE', { corpo: { itens: [evento()], proximoCursor: null } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual(['/api/v1/auth/me'])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco da trilha', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDaAuditoria({ searchParams: sp() })).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fauditoria&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar a trilha de auditoria.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('trilha vazia diz que nao ha evento', async () => {
    api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    render(await PaginaDaAuditoria({ searchParams: sp() }))

    expect(screen.getByText('Nenhum evento ainda.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('de/ate viram limites com fuso, ate exclusivo do dia seguinte', async () => {
    const chamadas = api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    await PaginaDaAuditoria({ searchParams: sp({ de: '2026-09-01', ate: '2026-09-30' }) })

    const trilha = chamadas.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((u) => u.pathname === '/api/v1/auditoria')
    expect(trilha?.searchParams.get('de')).toBe('2026-09-01T00:00:00-03:00')
    expect(trilha?.searchParams.get('ate')).toBe('2026-10-01T00:00:00-03:00')
  })

  it('acumula ao carregar mais: busca a primeira pagina e a atual', async () => {
    const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
      const u = new URL(String(url))
      if (u.pathname === '/api/v1/auth/me') {
        return new Response(
          JSON.stringify({ usuarioId: 'u-1', papel: 'ADMIN', corretorId: null, permissoes: PERMISSOES.ADMIN }),
        )
      }
      const cursor = u.searchParams.get('cursor')
      if (cursor === 'c1') {
        return new Response(JSON.stringify({ itens: [evento({ id: 'e-2' })], proximoCursor: null }))
      }
      return new Response(JSON.stringify({ itens: [evento({ id: 'e-1' })], proximoCursor: 'c1' }))
    })
    vi.stubGlobal('fetch', chamadas)

    render(await PaginaDaAuditoria({ searchParams: sp({ cursor: 'c1' }) }))

    const linhas = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(linhas).toHaveLength(2)
  })
})
