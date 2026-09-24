import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Pagina from './page'

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
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ADMIN_TOKEN = 'segredo'
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

  it('403 diz que e configuracao, e nao ausencia de dados', async () => {
    responde({ detail: 'forbidden' }, 403)

    render(await Pagina({ searchParams: Promise.resolve({}) }))

    expect(screen.getByRole('alert')).toHaveTextContent(/token/i)
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
