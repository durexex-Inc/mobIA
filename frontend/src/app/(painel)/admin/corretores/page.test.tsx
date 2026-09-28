import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDeCorretores from './page'

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
  // `FormularioDeCorretor`/`DesativarCorretor` sao Client Component e chamam
  // `useRouter` ao montar, mesmo sem clicar em nada.
  useRouter: () => ({ refresh: () => {} }),
}))

/** O que `/auth/me` devolve, pela matriz da TEC-202: so o ADMIN geri corretores. */
const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['GERIR_CORRETORES', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

function corretor(sobrescreve: Record<string, unknown> = {}) {
  return {
    id: 'c-1',
    nome: 'Ana Souza',
    email: 'ana@imobiliaria.com',
    telefone: '11999998888',
    creci: null,
    especialidades: ['COMPRA'],
    regioesAtuacao: ['Centro'],
    horarioInicio: 8,
    horarioFim: 18,
    capacidadeDiaria: 5,
    plantao: false,
    gerente: false,
    ativo: true,
    ...sobrescreve,
  }
}

/** `/auth/me` com o papel, e a listagem com o corpo e o status pedidos. */
function api(papel: string, listagem: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    if (new URL(String(url)).pathname === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    return new Response(JSON.stringify(listagem.corpo), {
      status: listagem.status ?? 200,
      headers: listagem.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('PaginaDeCorretores (TEC-332)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca SEM `?ativos=` -- a listagem inicial vem do servidor (D6, D8)', async () => {
    const chamadas = api('ADMIN', { corpo: [] })

    await PaginaDeCorretores()

    const listagem = chamadas.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((u) => u.pathname.includes('corretores'))
    expect(listagem?.pathname).toBe('/api/v1/corretores')
    expect(listagem?.search).toBe('')
  })

  it('lista os corretores, com o formulario de cadastro sempre visivel', async () => {
    api('ADMIN', { corpo: [corretor()] })

    render(await PaginaDeCorretores())

    expect(screen.getByRole('heading', { name: 'Corretores' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cadastrar corretor' })).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Ana Souza')).toBeInTheDocument()
  })

  it('lista vazia diz que nao ha corretor cadastrado', async () => {
    api('ADMIN', { corpo: [] })

    render(await PaginaDeCorretores())

    expect(screen.getByText('Nenhum corretor cadastrado.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('CORRETOR que acessa pela URL ve "Sem permissao", e nada alem de `/auth/me` e pedido', async () => {
    const chamadas = api('CORRETOR', { corpo: [corretor()] })

    render(await PaginaDeCorretores())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/v1/auth/me',
    ])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDeCorretores())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco dos corretores', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDeCorretores()).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fcorretores&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDeCorretores())

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar os corretores.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('sem sessao vai ao login, com o destino', async () => {
    cookiesDaRequisicao.clear()
    api('ADMIN', { corpo: [] })

    await expect(PaginaDeCorretores()).rejects.toThrow('REDIRECT:/login?returnTo=%2Fadmin%2Fcorretores')
  })
})
