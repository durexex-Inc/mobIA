import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import Pagina from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../test/armazem-em-memoria')).moduloDeArmazem,
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

/** O que `/auth/me` devolve para cada papel, pela matriz da TEC-202. */
const PERMISSOES: Record<string, string[]> = {
  GERENTE: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DADOS_COMPLETOS', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
  LEITURA: ['BUSCAR_IMOVEIS', 'VER_FUNIL', 'VER_LEADS'],
}

/**
 * O `fetch` dublado, com as duas rotas que a pagina chama: `/auth/me` (a
 * guarda da TEC-312) e o funil. Devolve SO as chamadas ao funil, que e o que
 * os testes inspecionam -- e o que o teste do CORRETOR afirma que nao acontece.
 *
 * Uma `Response` nova por chamada, e nao `mockResolvedValue`: o corpo de uma
 * `Response` so se le uma vez.
 */
function responde(
  corpo: unknown,
  status = 200,
  { papel = 'GERENTE', statusDoMe = 200 }: { papel?: string; statusDoMe?: number } = {},
) {
  const funil = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(
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
      String(url).includes('/api/v1/auth/me') ? me() : funil(url, init),
    ),
  )
  return funil
}

describe('Pagina', () => {
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

  it('cenario: o 403 do backend vence o menu, e vira "Sem permissao"', async () => {
    // O menu mostrou o funil (a GERENTE tem `VER_FUNIL`), e o FastAPI recusou
    // assim mesmo. A tela diz "Sem permissao" -- nao um funil vazio, nao um
    // aviso de erro generico.
    responde({ detail: 'forbidden' }, 403)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Você entrou como Gerente')
    expect(screen.queryByLabelText('Funil de leads')).not.toBeInTheDocument()
  })

  it('CORRETOR ve "Sem permissao" no inicio, e o funil NAO e buscado', async () => {
    // D6: a tela do corretor e a TEC-321. Ate ela existir, o `/` diz isso.
    const funil = responde(FUNIL, 200, { papel: 'CORRETOR' })

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Você entrou como Corretor')
    expect(screen.getByRole('alert')).toHaveTextContent('lista dos seus leads, ainda não está disponível')
    // Ja esta na pagina inicial: o link para ela so recarregaria esta tela.
    expect(screen.queryByRole('link', { name: 'Ir para a página inicial' })).not.toBeInTheDocument()
    expect(funil).not.toHaveBeenCalled()
  })

  it('LEITURA ve o funil', async () => {
    responde(FUNIL, 200, { papel: 'LEITURA' })

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByLabelText('Funil de leads')).toBeInTheDocument()
  })

  it('`/auth/me` recusando o token volta ao login, antes de buscar o funil', async () => {
    const funil = responde(FUNIL, 200, { statusDoMe: 401 })

    await expect(Pagina({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      /REDIRECT:\/login\?.*erro=sessao_expirada/,
    )
    expect(funil).not.toHaveBeenCalled()
  })

  it('pede o funil com o JWT de quem esta logado (TEC-309)', async () => {
    const chamadas = responde(FUNIL)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    const cabecalhos = chamadas.mock.calls[0][1]?.headers as Record<string, string>
    expect(cabecalhos.Authorization).toBe(`Bearer ${ACESSO_VALIDO}`)
  })

  it('sem sessao valida vai ao login com o recorte, e NAO chama o FastAPI', async () => {
    cookiesDaRequisicao.set('mobia_sessao', 'd'.repeat(43))
    const chamadas = responde(FUNIL)

    await expect(
      Pagina({ searchParams: Promise.resolve({ de: '2026-09-01', ate: '2026-09-26' }) }),
    ).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2F%3Fde%3D2026-09-01%26ate%3D2026-09-26&erro=sessao_expirada',
    )
    expect(chamadas).not.toHaveBeenCalled()
  })

  it('401 do FastAPI apaga a sessao e volta ao login dizendo isso (TEC-310, D5)', async () => {
    // Sem apagar, o login veria a sessao viva e mandaria de volta para ca, que
    // tomaria 401 de novo: o laco que a TEC-309 deixou.
    responde({ detail: 'nao autenticado' }, 401)
    const id = cookiesDaRequisicao.get('mobia_sessao')

    await expect(
      Pagina({ searchParams: Promise.resolve({ de: '2026-09-01', ate: '2026-09-26' }) }),
    ).rejects.toThrow(/REDIRECT:\/login\?returnTo=.*&erro=sessao_expirada/)
    expect(await lerSessao(id)).toBeNull()
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
