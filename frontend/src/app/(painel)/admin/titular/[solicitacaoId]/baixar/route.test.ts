import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import { GET } from './route'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../../../../test/armazem-em-memoria')).moduloDeArmazem,
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
  ADMIN: ['ATENDER_TITULAR'],
  GERENTE: ['VER_LEADS'],
}

function pedido(overrides: Record<string, unknown> = {}) {
  return {
    id: 'sol-1',
    tipo: 'ACESSO',
    origem: 'ADMIN',
    status: 'ABERTA',
    recebidaEm: '2026-09-01T00:00:00Z',
    prazoEm: '2026-09-16T00:00:00Z',
    atendidaEm: null,
    motivoDaRecusa: null,
    leadId: 'lead-1',
    ...overrides,
  }
}

/**
 * `/auth/me`, a fila (sem filtro de status) e a exportacao do lead, todas
 * dubladas por um `fetch` so, no molde do teste da pagina.
 */
function api({
  papel = 'ADMIN',
  itens = [pedido()],
  exportacao = { corpo: { canal: 'web', transcricao: [] }, status: 200 },
}: {
  papel?: string
  itens?: unknown[]
  exportacao?: { corpo: unknown; status?: number }
} = {}) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    const caminho = new URL(String(url)).pathname
    if (caminho === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    if (caminho === '/api/v1/titular/solicitacoes') {
      return new Response(JSON.stringify({ itens }))
    }
    return new Response(JSON.stringify(exportacao.corpo), { status: exportacao.status ?? 200 })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

function contexto(solicitacaoId: string) {
  return { params: Promise.resolve({ solicitacaoId }) }
}

function requisicao() {
  return new Request('https://painel.exemplo/admin/titular/sol-1/baixar')
}

describe('GET /admin/titular/[solicitacaoId]/baixar (TEC-341)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sem sessao, manda ao login com o retorno para a fila', async () => {
    cookiesDaRequisicao.clear()
    api()

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Ftitular',
    )
  })

  it('sem ATENDER_TITULAR, volta a fila -- que mostra "Sem permissao" sozinha', async () => {
    api({ papel: 'GERENTE' })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow('REDIRECT:/admin/titular')
  })

  it('cenario 1: ACESSO aberta com lead -- os tres cabecalhos e o corpo do backend, sem reanalisar', async () => {
    api({ exportacao: { corpo: { canal: 'web', telefone: '+5548999990021' } } })

    const resposta = await GET(requisicao(), contexto('sol-1'))

    expect(resposta.headers.get('Content-Type')).toBe('application/json')
    expect(resposta.headers.get('Content-Disposition')).toBe('attachment; filename="titular-sol-1.json"')
    expect(resposta.headers.get('Cache-Control')).toBe('no-store')
    await expect(resposta.json()).resolves.toEqual({ canal: 'web', telefone: '+5548999990021' })
  })

  it('cenario 2: ATENDIDA -- volta a fila com ?concluido=1, sem chamar a exportacao', async () => {
    // O backend zera o par de toda solicitacao concluida (D4 do desenho): leadId
    // vem nulo. E exatamente o caso que fez o bug de ordem escapar antes.
    const chamadas = api({ itens: [pedido({ status: 'ATENDIDA', leadId: null })] })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow(
      'REDIRECT:/admin/titular?concluido=1',
    )
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).not.toContain(
      '/api/v1/leads/lead-1/dados-pessoais',
    )
  })

  it('RECUSADA tambem conta como concluida, mesmo com leadId nulo', async () => {
    api({ itens: [pedido({ status: 'RECUSADA', leadId: null })] })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow(
      'REDIRECT:/admin/titular?concluido=1',
    )
  })

  it('ELIMINACAO nao e portabilidade: volta a fila sem aviso, sem chamar a exportacao', async () => {
    const chamadas = api({ itens: [pedido({ tipo: 'ELIMINACAO' })] })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow('REDIRECT:/admin/titular')
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).not.toContain(
      '/api/v1/leads/lead-1/dados-pessoais',
    )
  })

  it('id inexistente volta a fila sem aviso', async () => {
    api({ itens: [] })

    await expect(GET(requisicao(), contexto('sol-inexistente'))).rejects.toThrow('REDIRECT:/admin/titular')
  })

  it('ABERTA sem leadId (apelido sumiu) volta a fila sem aviso', async () => {
    api({ itens: [pedido({ leadId: null })] })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow('REDIRECT:/admin/titular')
  })

  it('exportacao que falha no backend volta a fila sem aviso', async () => {
    api({ exportacao: { corpo: { detail: 'boom' }, status: 500 } })

    await expect(GET(requisicao(), contexto('sol-1'))).rejects.toThrow('REDIRECT:/admin/titular')
  })
})
