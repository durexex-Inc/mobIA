import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDaFilaDoTitular from './page'

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
  // `EliminarDadosDoTitular` (TEC-342) e Client Component e chama `useRouter`
  // ao montar, mesmo sem clicar em nada.
  useRouter: () => ({ refresh: () => {} }),
}))

/** O que `/auth/me` devolve, pela matriz da TEC-202: so o ADMIN atende o titular. */
const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['ATENDER_TITULAR', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  GERENTE: ['ATENDER_LEAD', 'VER_DADOS_COMPLETOS', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
}

const DIA_MS = 86_400_000

// Relativo ao relogio real, e nao a uma data fixa: o token de teste e emitido
// contra ele. A conta por dia de calendario da `15 - dias` a qualquer hora,
// porque abertura e agora andam juntos.
function pedido(diasAbertos: number, extra: Record<string, unknown> = {}) {
  const recebidaEm = new Date(Date.now() - diasAbertos * DIA_MS)
  return {
    id: `p-${diasAbertos}`,
    tipo: 'ACESSO',
    origem: 'ADMIN',
    status: 'ABERTA',
    recebidaEm: recebidaEm.toISOString(),
    prazoEm: new Date(recebidaEm.getTime() + 15 * DIA_MS).toISOString(),
    atendidaEm: null,
    motivoDaRecusa: null,
    leadId: `lead-${diasAbertos}`,
    ...extra,
  }
}

/** `/auth/me` com o papel, e a fila com o corpo e o status pedidos. */
function api(papel: string, fila: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    if (new URL(String(url)).pathname === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    return new Response(JSON.stringify(fila.corpo), { status: fila.status ?? 200, headers: fila.cabecalhos })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

function sp(params: Record<string, string> = {}) {
  return Promise.resolve(params)
}

function linhaDe(texto: string) {
  const celula = screen.getAllByText(texto)[0]
  const linha = celula.closest('tr')
  if (!linha) {
    throw new Error(`sem linha para ${texto}`)
  }
  return linha
}

describe('PaginaDaFilaDoTitular (TEC-340)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('pede so os pedidos abertos', async () => {
    const chamadas = api('ADMIN', { corpo: { itens: [] } })

    await PaginaDaFilaDoTitular({ searchParams: sp() })

    const fila = chamadas.mock.calls.map(([url]) => new URL(String(url))).find((u) => u.pathname.includes('titular'))
    expect(fila?.pathname).toBe('/api/v1/titular/solicitacoes')
    expect(fila?.searchParams.get('status')).toBe('ABERTA')
  })

  it('esquema do cenario: o prazo restante e o destaque (2/13 sem, 12/3 e 14/1 com)', async () => {
    api('ADMIN', { corpo: { itens: [pedido(14), pedido(12), pedido(2)] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    const linhas = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(linhas.map((linha) => within(linha).getAllByRole('cell')[3].textContent)).toEqual([
      '1 dia ⚠ Prazo curto',
      '3 dias ⚠ Prazo curto',
      '13 dias',
    ])
    expect(linhas[0]).toHaveClass('fila-do-titular__urgente')
    expect(linhas[1]).toHaveClass('fila-do-titular__urgente')
    expect(linhas[2]).not.toHaveClass('fila-do-titular__urgente')
  })

  it('cenario 2: o pedido de eliminacao feito pelo WhatsApp aparece com origem "WhatsApp"', async () => {
    api('ADMIN', { corpo: { itens: [pedido(1, { tipo: 'ELIMINACAO', origem: 'WHATSAPP' })] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    const linha = linhaDe('Eliminação dos dados')
    expect(within(linha).getByText('WhatsApp')).toBeInTheDocument()
    const ontem = new Date(Date.now() - DIA_MS).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' })
    expect(within(linha).getByText(ontem)).toBeInTheDocument()
    expect(within(linha).getByRole('link', { name: 'Ver lead' })).toHaveAttribute('href', '/leads/lead-1')
  })

  it('pedido vencido e destacado como vencido', async () => {
    api('ADMIN', { corpo: { itens: [pedido(17)] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.getByText(/Vencido há 2 dias/)).toBeInTheDocument()
    expect(screen.getByText(/Prazo vencido/)).toBeInTheDocument()
  })

  it('cenario 3: o GERENTE que abre o endereco direto ve "Sem permissao", e a fila nao e pedida', async () => {
    const chamadas = api('GERENTE', { corpo: { itens: [pedido(2)] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Você entrou como Gerente')
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual(['/api/v1/auth/me'])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco da fila', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDaFilaDoTitular({ searchParams: sp() })).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Ftitular&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar a fila de pedidos.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('fila vazia diz que nao ha pedido em aberto', async () => {
    api('ADMIN', { corpo: { itens: [] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.getByText('Nenhum pedido em aberto.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('?concluido=1 avisa que o pedido ja foi concluido (TEC-341, D4)', async () => {
    api('ADMIN', { corpo: { itens: [] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp({ concluido: '1' }) }))

    expect(screen.getByRole('status')).toHaveTextContent('Este pedido já foi concluído.')
  })

  it('sem ?concluido, nao ha aviso', async () => {
    api('ADMIN', { corpo: { itens: [] } })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    expect(screen.queryByRole('status')).toBeNull()
  })

  it('"Baixar dados do titular" so aparece na linha ACESSO (TEC-341, D1)', async () => {
    api('ADMIN', {
      corpo: { itens: [pedido(1, { id: 'acesso-1' }), pedido(2, { id: 'elim-1', tipo: 'ELIMINACAO' })] },
    })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    const linhaDoAcesso = linhaDe('Acesso aos dados')
    expect(within(linhaDoAcesso).getByRole('link', { name: 'Baixar dados do titular' })).toHaveAttribute(
      'href',
      '/admin/titular/acesso-1/baixar',
    )
    const linhaDaEliminacao = linhaDe('Eliminação dos dados')
    expect(within(linhaDaEliminacao).queryByRole('link', { name: 'Baixar dados do titular' })).toBeNull()
  })

  it('"Eliminar dados do titular" so aparece na linha ELIMINACAO com leadId (TEC-342, D4)', async () => {
    api('ADMIN', {
      corpo: {
        itens: [
          pedido(1, { id: 'acesso-1' }),
          pedido(2, { id: 'elim-1', tipo: 'ELIMINACAO' }),
          pedido(3, { id: 'elim-2', tipo: 'ELIMINACAO', leadId: null }),
        ],
      },
    })

    render(await PaginaDaFilaDoTitular({ searchParams: sp() }))

    const linhaDoAcesso = linhaDe('Acesso aos dados')
    expect(within(linhaDoAcesso).queryByRole('button', { name: 'Eliminar dados do titular' })).toBeNull()

    const [linhaComLead, linhaSemLead] = screen
      .getAllByText('Eliminação dos dados')
      .map((celula) => celula.closest('tr'))
    if (!linhaComLead || !linhaSemLead) {
      throw new Error('linhas de eliminacao nao encontradas')
    }
    expect(within(linhaComLead).getByRole('button', { name: 'Eliminar dados do titular' })).toBeInTheDocument()
    expect(within(linhaSemLead).queryByRole('button', { name: 'Eliminar dados do titular' })).toBeNull()
  })
})
