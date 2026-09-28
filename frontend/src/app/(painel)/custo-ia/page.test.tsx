import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import Pagina from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../test/armazem-em-memoria')).moduloDeArmazem,
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

const RESPOSTA = {
  custoTotalUsd: 0.84,
  custoPorConversaUsd: 0.084,
  custoPorLeadQualificadoUsd: 0.42,
  tokensPorModelo: {},
  conversas: 10,
  leadsQualificados: 2,
  mensagensSemPreco: 0,
  alvoPorLeadQualificadoUsd: 0.12,
  acimaDoAlvo: true,
  orcamento: null,
}

const PERMISSOES: Record<string, string[]> = {
  GERENTE: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

/** Duble de `fetch`, no molde de `app/(painel)/page.test.tsx` (funil). */
function responde(
  corpo: unknown,
  status = 200,
  { papel = 'GERENTE', statusDoMe = 200 }: { papel?: string; statusDoMe?: number } = {},
) {
  const custo = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(corpo), { status }),
  )
  const me = vi.fn(
    async () =>
      new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
        { status: statusDoMe },
      ),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn((url: URL | string, init?: RequestInit) =>
      String(url).includes('/api/v1/auth/me') ? me() : custo(url, init),
    ),
  )
  return custo
}

describe('Pagina de custo de IA', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set(
      'mobia_sessao',
      await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'refresh' }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('mostra o custo total do periodo (cenario 1 do Gherkin)', async () => {
    responde(RESPOSTA)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByLabelText('Custo de IA')).toBeInTheDocument()
    expect(screen.getByTestId('custo-total')).toHaveTextContent('US$ 0,84')
  })

  it('alerta de orcamento aparece com o icone e o texto (cenario 2)', async () => {
    responde({
      ...RESPOSTA,
      orcamento: { mensalUsd: 100, doPeriodoUsd: 100, consumidoUsd: 80, consumidoPct: 80, alerta: true },
    })

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('alert')).toHaveTextContent('⚠')
  })

  it('sem orcamento configurado, nenhum alerta e um link para configurar (cenario 3)', async () => {
    responde(RESPOSTA)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Configurar orçamento' })).toHaveAttribute(
      'href',
      '/admin',
    )
  })

  it('periodo sem conversas mostra US$ 0,00 (cenario 4)', async () => {
    responde({
      ...RESPOSTA,
      custoTotalUsd: 0,
      custoPorConversaUsd: null,
      custoPorLeadQualificadoUsd: null,
      conversas: 0,
      leadsQualificados: 0,
      acimaDoAlvo: null,
    })

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByTestId('custo-total')).toHaveTextContent('US$ 0,00')
    expect(screen.queryByText('Ainda não medido')).not.toBeInTheDocument()
  })

  it('backend fora do ar vira aviso, e nao painel de zeros', async () => {
    responde({}, 500)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('alert')).toHaveTextContent(/não foi possível carregar/i)
    expect(screen.queryByLabelText('Custo de IA')).not.toBeInTheDocument()
  })

  it('422 nomeia o filtro recusado no proprio formulario', async () => {
    responde({ detail: "temperatura='MORNA' nao e um valor conhecido" }, 422)

    render(await Pagina({ searchParams: Promise.resolve({ temperatura: 'MORNA' }) }))

    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('CORRETOR sem VER_FUNIL e redirecionado', async () => {
    const custo = responde(RESPOSTA, 200, { papel: 'CORRETOR' })

    await expect(Pagina({ searchParams: Promise.resolve({}) })).rejects.toThrow('REDIRECT:/leads')
    expect(custo).not.toHaveBeenCalled()
  })

  it('pede o custo com os filtros da URL', async () => {
    const custo = responde(RESPOSTA)

    render(
      await Pagina({
        searchParams: Promise.resolve({ de: '2026-08-01', ate: '2026-08-31', canal: 'web' }),
      }),
    )

    const url = String(custo.mock.calls[0][0])
    expect(url).toContain('de=2026-08-01')
    expect(url).toContain('ate=2026-08-31')
    expect(url).toContain('canal=web')
  })
})
