import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../test/armazem-em-memoria'
import { criarSessao } from '@/lib/servidor/sessao'
import Pagina from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../test/armazem-em-memoria')).moduloDeArmazem,
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

/**
 * **Sem mock de `buscarFunil`: o duble e o `fetch`.**
 *
 * Mockar o modulo e faze-lo rejeitar parece mais direto, mas o vitest trata
 * a rejeicao do proprio mock como erro nao capturado e reprova o teste ainda
 * que a pagina trate o erro corretamente -- verificado, o alerta renderizava
 * certo e o teste reprovava assim mesmo. Stubar o `fetch` evita isso e
 * exercita MAIS codigo: o caminho de erro do proprio `buscarFunil`, incluindo
 * a leitura do `detail` que o FastAPI manda no 422.
 */

const FUNIL = {
  etapas: [
    { nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null },
    { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: null },
  ],
  indicadores: { leadsNovos: 320, taxaNoShow: null },
  indisponiveis: ['taxaNoShow'],
}

const VAZIO = {
  etapas: [{ nome: 'Novo', quantidade: 0, disponivel: true, conversaoDaAnterior: null }],
  indicadores: { leadsNovos: 0 },
  indisponiveis: [],
}

function responde(corpo: unknown, status = 200) {
  const chamadas = vi.fn().mockResolvedValue(new Response(JSON.stringify(corpo), { status }))
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('Pagina', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set(
      'mobia_sessao',
      await criarSessao({ acesso: 'jwt-da-anelise', refresh: 'refresh' }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('mostra o funil quando a busca da certo', async () => {
    responde(FUNIL)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByLabelText('Funil de leads')).toBeInTheDocument()
    expect(screen.getByTestId('etapa-Novo')).toHaveTextContent('320')
  })

  it('backend fora do ar vira aviso, e nao funil de zeros', async () => {
    responde({}, 500)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('alert')).toHaveTextContent(/não foi possível carregar/i)
    expect(screen.queryByLabelText('Funil de leads')).not.toBeInTheDocument()
  })

  it('403 diz que o perfil nao inclui o painel, e nao ausencia de dados', async () => {
    // Desde a TEC-309 o 403 e o papel sem `VER_FUNIL`, e nao o token do
    // ambiente -- que o frontend nem manda mais.
    responde({ detail: 'forbidden' }, 403)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('alert')).toHaveTextContent(/perfil de acesso não inclui este painel/)
  })

  it('pede o funil com o JWT de quem esta logado (TEC-309)', async () => {
    const chamadas = responde(FUNIL)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(chamadas.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-da-anelise')
  })

  it('sem sessao valida vai ao login com o recorte, e NAO chama o FastAPI', async () => {
    cookiesDaRequisicao.set('mobia_sessao', 'd'.repeat(43))
    const chamadas = responde(FUNIL)

    await expect(
      Pagina({ searchParams: Promise.resolve({ de: '2026-09-01', ate: '2026-09-26' }) }),
    ).rejects.toThrow('REDIRECT:/login?returnTo=%2F%3Fde%3D2026-09-01%26ate%3D2026-09-26')
    expect(chamadas).not.toHaveBeenCalled()
  })

  it('401 e o access que expirou: volta ao login dizendo isso', async () => {
    responde({ detail: 'nao autenticado' }, 401)

    await expect(
      Pagina({ searchParams: Promise.resolve({ de: '2026-09-01', ate: '2026-09-26' }) }),
    ).rejects.toThrow(/REDIRECT:\/login\?returnTo=.*&erro=sessao_expirada/)
  })

  it('422 nomeia o filtro recusado no proprio formulario', async () => {
    responde({ detail: "temperatura='MORNA' nao e um valor conhecido" }, 422)

    render(await Pagina({ searchParams: Promise.resolve({ temperatura: 'MORNA' }) }))

    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('periodo legitimamente vazio mostra o funil zerado, e nao o aviso de erro', async () => {
    responde(VAZIO)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByLabelText('Funil de leads')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('o filtro da URL chega ao backend', async () => {
    const chamadas = responde(FUNIL)

    render(
      await Pagina({
        searchParams: Promise.resolve({ de: '2026-08-01', ate: '2026-08-31', canal: 'web' }),
      }),
    )

    const url = String(chamadas.mock.calls[0][0])
    expect(url).toContain('de=2026-08-01')
    expect(url).toContain('ate=2026-08-31')
    expect(url).toContain('canal=web')
  })

  it('sem filtro na URL, o periodo padrao vai mesmo assim', async () => {
    const chamadas = responde(FUNIL)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    const url = String(chamadas.mock.calls[0][0])
    expect(url).toMatch(/de=\d{4}-\d{2}-\d{2}/)
    expect(url).toMatch(/ate=\d{4}-\d{2}-\d{2}/)
  })
})
