import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDePrompts from './page'

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
}))

const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['CONFIGURAR_AGENTE'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

function api(papel: string, prompts: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    const caminho = new URL(String(url)).pathname
    if (caminho === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    return new Response(JSON.stringify(prompts.corpo), {
      status: prompts.status ?? 200,
      headers: prompts.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('PaginaDePrompts (TEC-338)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ADMIN ve os dois agentes com versao, autor e data (cenario: ver a versao ativa)', async () => {
    api('ADMIN', {
      corpo: {
        itens: [
          {
            agente: 'AGENTE',
            versao: 7,
            padrao: false,
            publicadaPor: 'Rafael',
            publicadaEm: '2026-09-20T12:00:00+00:00',
            ativadaPor: 'Rafael',
            ativadaEm: '2026-09-20T12:00:00+00:00',
            motivo: null,
          },
          {
            agente: 'INVESTIDOR',
            versao: 0,
            padrao: true,
            publicadaPor: null,
            publicadaEm: null,
            ativadaPor: null,
            ativadaEm: null,
            motivo: null,
          },
        ],
      },
    })

    render(await PaginaDePrompts())

    expect(screen.getByRole('heading', { name: 'Prompts do agente' })).toBeInTheDocument()
    const linkAgente = screen.getByRole('link', { name: 'Agente principal' })
    expect(linkAgente).toHaveAttribute('href', '/admin/prompts/agente')
    expect(screen.getByText(/versão 7/)).toBeInTheDocument()
    expect(screen.getByText(/publicada por Rafael/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Subagente investidor' })).toHaveAttribute(
      'href',
      '/admin/prompts/investidor',
    )
  })

  it('CORRETOR que acessa pela URL ve "Sem permissao", e nada alem de `/auth/me` e pedido', async () => {
    const chamadas = api('CORRETOR', { corpo: { itens: [] } })

    render(await PaginaDePrompts())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/v1/auth/me',
    ])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDePrompts())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco de prompts', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDePrompts()).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fprompts&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDePrompts())

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar os prompts dos agentes.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('sem sessao vai ao login, com o destino', async () => {
    cookiesDaRequisicao.clear()
    api('ADMIN', { corpo: { itens: [] } })

    await expect(PaginaDePrompts()).rejects.toThrow('REDIRECT:/login?returnTo=%2Fadmin%2Fprompts')
  })
})
