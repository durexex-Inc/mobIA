import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { Transcricao } from './Transcricao'

const LEAD = 'lead-1'

function fala(n: number, extra: Record<string, unknown> = {}) {
  return {
    id: `f-${n}`,
    autor: 'LEAD',
    tipo: 'TEXTO',
    conteudo: `fala ${n}`,
    retida: false,
    em: '2026-09-26T17:03:00+00:00',
    ...extra,
  }
}

function pagina(de: number, ate: number, cursorAnterior: string | null) {
  const itens = []
  for (let n = de; n <= ate; n++) {
    itens.push(fala(n))
  }
  return { itens, cursorAnterior }
}

function caixa() {
  return screen.getByLabelText('Falas da conversa')
}

describe('Transcricao', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn()
    vi.stubGlobal('fetch', api)
    // O jsdom nao faz layout: `scrollHeight` e sempre 0. Aqui ele cresce 10px
    // por fala, que e o que basta para verificar a conta da D3. No prototipo,
    // e nao no elemento, porque o efeito que leva a caixa ao fim roda na
    // montagem, antes de o teste conseguir pegar o elemento.
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.querySelectorAll('[data-testid="fala"]').length * 10
      },
    })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight
  })

  it('cenario: a rolagem comeca na fala mais recente', () => {
    render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)

    expect(caixa().scrollTop).toBe(1000)
  })

  it('cenario: autor identificado sem depender de cor -- rotulo e horario em cada fala', () => {
    render(
      <Transcricao
        leadId={LEAD}
        inicial={{
          itens: [
            fala(1, { autor: 'LEAD' }),
            fala(2, { autor: 'AGENTE' }),
            fala(3, { autor: 'CORRETOR' }),
            fala(4, { autor: 'SISTEMA' }),
          ],
          cursorAnterior: null,
        }}
      />,
    )

    const falas = screen.getAllByTestId('fala')
    expect(falas.map((f) => f.querySelector('strong')?.textContent)).toEqual([
      'Lead',
      'Assistente',
      'Corretor',
      'Sistema',
    ])
    for (const f of falas) {
      expect(f.querySelector('time')).toHaveTextContent('26/09/2026, 14:03')
    }
    expect(falas[0]).toHaveClass('fala-lead')
    expect(falas[1]).toHaveClass('fala-equipe')
  })

  it('cenario: ADMIN ve "Mensagem retida pela moderacao" sem o conteudo', () => {
    render(
      <Transcricao
        leadId={LEAD}
        inicial={{ itens: [fala(1, { retida: true, conteudo: null })], cursorAnterior: null }}
      />,
    )

    expect(screen.getByTestId('fala')).toHaveTextContent('Mensagem retida pela moderação')
  })

  describe('cenario: carregar falas anteriores', () => {
    it('as 100 anteriores entram acima, sem perder a posicao de leitura', async () => {
      api.mockResolvedValue(new Response(JSON.stringify(pagina(101, 200, 'c2'))))
      render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)
      // A pessoa subiu um pouco: esta 300px acima do fim.
      caixa().scrollTop = 700

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Carregar anteriores' }))
      })

      const textos = screen.getAllByTestId('fala').map((f) => f.querySelector('p')?.textContent)
      expect(textos[0]).toBe('fala 101')
      expect(textos[99]).toBe('fala 200')
      expect(textos[100]).toBe('fala 201')
      // 200 falas = 2000px; a mesma distancia de 300px ate o fim.
      expect(caixa().scrollTop).toBe(1700)
    })

    it('pede pelo proxy, com o cursor da pagina atual', async () => {
      api.mockResolvedValue(new Response(JSON.stringify(pagina(101, 200, null))))
      render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Carregar anteriores' }))
      })

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/leads/lead-1/mensagens?cursor=c1',
        expect.anything(),
      )
    })

    it('anuncia o carregamento, e sem cursor diz que e o inicio da conversa', async () => {
      api.mockResolvedValue(new Response(JSON.stringify(pagina(101, 200, null))))
      render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Carregar anteriores' }))
      })

      expect(screen.getByRole('status')).toHaveTextContent('100 falas anteriores carregadas.')
      expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
      expect(screen.queryByRole('button', { name: 'Carregar anteriores' })).not.toBeInTheDocument()
      expect(screen.getByText('Início da conversa')).toBeInTheDocument()
    })

    it('falha deixa as falas como estavam e o botao para tentar de novo', async () => {
      api.mockResolvedValue(new Response('{}', { status: 500 }))
      render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Carregar anteriores' }))
      })

      expect(screen.getByRole('status')).toHaveTextContent('Não foi possível carregar as falas anteriores.')
      expect(screen.getAllByTestId('fala')).toHaveLength(100)
      expect(screen.getByRole('button', { name: 'Carregar anteriores' })).toBeEnabled()
    })

    it('401 diz que a sessao terminou, com o caminho de volta a este lead', async () => {
      api.mockResolvedValue(new Response('{}', { status: 401 }))
      render(<Transcricao leadId={LEAD} inicial={pagina(201, 300, 'c1')} />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Carregar anteriores' }))
      })

      expect(screen.getByRole('status')).toHaveTextContent('Sua sessão terminou.')
      expect(screen.getByRole('link', { name: 'Entrar de novo' })).toHaveAttribute(
        'href',
        '/login?returnTo=%2Fleads%2Flead-1&erro=sessao_expirada',
      )
    })
  })

  describe('cenario: mensagem nova do lead chega sem recarregar (TEC-327)', () => {
    const visibilidade = { valor: 'visible' as DocumentVisibilityState }

    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout'] })
      visibilidade.valor = 'visible'
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => visibilidade.valor,
      })
    })
    afterEach(() => {
      vi.useRealTimers()
      delete (document as { visibilityState?: string }).visibilityState
    })

    async function passar(ms: number) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
      })
    }

    const INICIAL = { ...pagina(1, 3, null), cursorPosterior: 'p3' }

    it('a fala nova aparece no fim em ate 10 s, pelo proxy, com o cursor do servidor', async () => {
      api.mockResolvedValueOnce(
        new Response(JSON.stringify({ itens: [fala(4, { conteudo: 'Pode ser amanhã às 10h?' })], cursorAnterior: null, cursorPosterior: 'p4' })),
      )
      api.mockResolvedValue(new Response(JSON.stringify({ itens: [], cursorAnterior: null, cursorPosterior: 'p4' })))
      render(<Transcricao leadId={LEAD} inicial={INICIAL} acompanhar />)

      await passar(5_000)

      const textos = screen.getAllByTestId('fala').map((f) => f.querySelector('p')?.textContent)
      expect(textos.at(-1)).toBe('Pode ser amanhã às 10h?')
      expect(api.mock.calls[0][0]).toBe('/bff/api/v1/leads/lead-1/mensagens?depois=p3')
      expect(screen.getByRole('status')).toHaveTextContent('1 mensagem nova.')

      await passar(5_000)
      expect(api.mock.calls[1][0]).toBe('/bff/api/v1/leads/lead-1/mensagens?depois=p4')
    })

    it('sem acompanhar, nao ha polling', async () => {
      render(<Transcricao leadId={LEAD} inicial={INICIAL} />)

      await passar(30_000)

      expect(api).not.toHaveBeenCalled()
    })

    it('com a aba escondida nao pergunta; ao voltar, pergunta na hora', async () => {
      api.mockResolvedValue(new Response(JSON.stringify({ itens: [], cursorAnterior: null, cursorPosterior: 'p3' })))
      visibilidade.valor = 'hidden'
      render(<Transcricao leadId={LEAD} inicial={INICIAL} acompanhar />)

      await passar(20_000)
      expect(api).not.toHaveBeenCalled()

      visibilidade.valor = 'visible'
      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'))
      })
      expect(api).toHaveBeenCalledOnce()
    })

    it('quem estava no fim acompanha a fala nova; quem subiu para ler nao e arrastado', async () => {
      api.mockImplementation(
        async () =>
          new Response(JSON.stringify({ itens: [fala(Math.random())], cursorAnterior: null, cursorPosterior: 'px' })),
      )
      // 20 falas = 200px: longe o bastante do fim para subir alem da folga.
      render(
        <Transcricao leadId={LEAD} inicial={{ ...pagina(1, 20, null), cursorPosterior: 'p20' }} acompanhar />,
      )
      expect(caixa().scrollTop).toBe(200)

      await passar(5_000)
      expect(caixa().scrollTop).toBe(210)

      caixa().scrollTop = 0
      await passar(5_000)
      expect(caixa().scrollTop).toBe(0)
    })

    it('401 para o polling e diz que a sessao terminou', async () => {
      api.mockResolvedValue(new Response('{}', { status: 401 }))
      render(<Transcricao leadId={LEAD} inicial={INICIAL} acompanhar />)

      await passar(5_000)
      await passar(20_000)

      expect(api).toHaveBeenCalledOnce()
      expect(screen.getByRole('status')).toHaveTextContent('Sua sessão terminou.')
    })

    it('falha comum nao avisa e tenta de novo no proximo ciclo', async () => {
      api.mockResolvedValue(new Response('{}', { status: 502 }))
      render(<Transcricao leadId={LEAD} inicial={INICIAL} acompanhar />)

      await passar(10_000)

      expect(api).toHaveBeenCalledTimes(2)
      expect(screen.getByRole('status')).toHaveTextContent('')
    })
  })

  it('sem cursor na primeira pagina, nao ha o que carregar', () => {
    render(<Transcricao leadId={LEAD} inicial={pagina(1, 3, null)} />)

    expect(screen.queryByRole('button', { name: 'Carregar anteriores' })).not.toBeInTheDocument()
    expect(screen.getByText('Início da conversa')).toBeInTheDocument()
  })

  describe('a resposta do corretor (TEC-328)', () => {
    it('a fala enviada entra no fim com o rotulo "Corretor", e o polling nao a duplica', async () => {
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout'] })
      try {
        const enviada = fala(9, { id: 'f-enviada', autor: 'CORRETOR', conteudo: 'Oi, sou o Paulo' })
        api.mockImplementation(async (_url, init) =>
          init?.method === 'POST'
            ? new Response(JSON.stringify({ id: 'f-enviada', em: enviada.em }), { status: 201 })
            : new Response(JSON.stringify({ itens: [enviada], cursorAnterior: null, cursorPosterior: 'p9' })),
        )
        render(
          <Transcricao
            leadId={LEAD}
            inicial={{ ...pagina(1, 2, null), cursorPosterior: 'p2' }}
            acompanhar
            resposta={{ janelaFechaEm: null }}
          />,
        )

        fireEvent.change(screen.getByLabelText('Responder ao lead'), { target: { value: 'Oi, sou o Paulo' } })
        await act(async () => {
          fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
        })
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5_000)
        })

        const falas = screen.getAllByTestId('fala')
        expect(falas).toHaveLength(3)
        expect(falas.at(-1)).toHaveTextContent('Corretor')
        expect(falas.at(-1)).toHaveTextContent('Oi, sou o Paulo')
      } finally {
        vi.useRealTimers()
      }
    })

    it('sem `resposta` nao ha campo; sem a conversa, ele esta desabilitado', () => {
      const { unmount } = render(<Transcricao leadId={LEAD} inicial={pagina(1, 2, null)} />)
      expect(screen.queryByLabelText('Responder ao lead')).toBeNull()
      unmount()

      render(<Transcricao leadId={LEAD} inicial={pagina(1, 2, null)} resposta={{ janelaFechaEm: null }} />)
      expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
    })
  })
})
