import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { DadoRevelavel, PRAZO_DA_REVELACAO_MS } from './DadoRevelavel'

const MASCARA = '+55 48 9****-**21'
const NUMERO = '+5548999990021'

function revelou(valor: string | null) {
  return new Response(JSON.stringify({ campo: 'telefone', valor }), {
    headers: { 'Content-Type': 'application/json' },
  })
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('DadoRevelavel', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => revelou(NUMERO))
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  describe('cenario: sem permissao', () => {
    it('mostra a mascara e nao oferece revelar', () => {
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar={false} />)

      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.queryByRole('button')).toBeNull()
    })
  })

  describe('cenario: revelacao registra auditoria antes de exibir o numero', () => {
    it('faz o POST do campo pelo proxy, sem cache, e so mostra o numero com a resposta', async () => {
      let responder: (r: Response) => void = () => {}
      api.mockImplementationOnce(() => new Promise((r) => (responder = r)))
      render(<DadoRevelavel leadId="l 1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      await clicar('Revelar telefone')

      // A resposta ainda nao chegou -- e o backend so responde depois de
      // comitar a trilha. Ate la, so a mascara.
      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/leads/l%201/revelar',
        expect.objectContaining({ method: 'POST', body: '{"campo":"telefone"}', cache: 'no-store' }),
      )
      expect(screen.queryByText(NUMERO)).toBeNull()
      expect(screen.getByText(MASCARA)).toBeInTheDocument()

      await act(async () => responder(revelou(NUMERO)))

      expect(screen.getByText(NUMERO)).toBeInTheDocument()
      expect(screen.queryByText(MASCARA)).toBeNull()
    })

    it('recusado, a mascara fica e a tela diz por que', async () => {
      api.mockResolvedValueOnce(new Response('{}', { status: 403 }))
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      await clicar('Revelar telefone')

      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.getByRole('alert')).toHaveTextContent('Você não tem permissão para ver este dado.')
    })

    it('sem rede, a mascara fica', async () => {
      api.mockRejectedValueOnce(new TypeError('failed to fetch'))
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      await clicar('Revelar telefone')

      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível revelar. Tente de novo.')
    })

    it('revelado sem valor diz "Não informado", e nao volta a mascara', async () => {
      api.mockResolvedValueOnce(revelou(null))
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      await clicar('Revelar telefone')

      expect(screen.getByText('Não informado')).toBeInTheDocument()
      expect(screen.queryByText(MASCARA)).toBeNull()
    })
  })

  describe('cenario: valor revelado expira em 5 minutos', () => {
    it('volta a mascara no prazo, e nao antes', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)
      await clicar('Revelar telefone')
      expect(screen.getByText(NUMERO)).toBeInTheDocument()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(PRAZO_DA_REVELACAO_MS - 1)
      })
      expect(screen.getByText(NUMERO)).toBeInTheDocument()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1)
      })
      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.queryByText(NUMERO)).toBeNull()
    })

    it('"Ocultar" apaga antes do prazo', async () => {
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)
      await clicar('Revelar telefone')

      await clicar('Ocultar telefone')

      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.queryByText(NUMERO)).toBeNull()
    })
  })

  describe('cenario: valor revelado nao e guardado no cliente', () => {
    it('sair e voltar comeca mascarado, sem URL, armazenamento nem console', async () => {
      const console_ = vi.spyOn(console, 'log')
      const aviso = vi.spyOn(console, 'warn')
      const erro = vi.spyOn(console, 'error')
      const { unmount } = render(
        <DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />,
      )
      await clicar('Revelar telefone')
      expect(screen.getByText(NUMERO)).toBeInTheDocument()

      unmount()
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      expect(screen.getByText(MASCARA)).toBeInTheDocument()
      expect(screen.queryByText(NUMERO)).toBeNull()
      const digitos = NUMERO.slice(1)
      expect(window.location.href).not.toContain(digitos)
      expect(JSON.stringify({ ...window.localStorage })).not.toContain(digitos)
      expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(digitos)
      for (const espiao of [console_, aviso, erro]) {
        expect(JSON.stringify(espiao.mock.calls)).not.toContain(digitos)
      }
    })
  })

  describe('sem mascara', () => {
    it('diz "Não informado" e nao oferece revelar um campo vazio', () => {
      render(<DadoRevelavel leadId="l-1" campo="email" mascarado={null} podeRevelar />)

      expect(screen.getByText('Não informado')).toBeInTheDocument()
      expect(screen.queryByRole('button')).toBeNull()
    })
  })

  describe('pedidos de interesse (TEC-404)', () => {
    it('com `url`, pede a revelacao nela, e nao na rota do lead', async () => {
      render(
        <DadoRevelavel
          leadId="l-1"
          campo="email"
          mascarado="j****z@e*.com"
          podeRevelar
          url="/bff/api/v1/interesses/p-1/revelar"
        />,
      )

      await clicar('Revelar e-mail')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/interesses/p-1/revelar',
        expect.objectContaining({ method: 'POST', body: '{"campo":"email"}' }),
      )
    })

    it('com `url`, o 404 fala do registro, e nao do lead', async () => {
      api.mockResolvedValueOnce(new Response('{}', { status: 404 }))
      render(
        <DadoRevelavel
          leadId="l-1"
          campo="telefone"
          mascarado={MASCARA}
          podeRevelar
          url="/bff/api/v1/interesses/p-1/revelar"
        />,
      )

      await clicar('Revelar telefone')

      expect(screen.getByRole('alert')).toHaveTextContent('Este registro não existe mais.')
    })

    it('sem `url`, o 404 continua falando do lead', async () => {
      api.mockResolvedValueOnce(new Response('{}', { status: 404 }))
      render(<DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar />)

      await clicar('Revelar telefone')

      expect(screen.getByRole('alert')).toHaveTextContent('Este lead não existe mais.')
    })
  })

  describe('na lista', () => {
    it('o texto e o link, e o botao fica fora dele', async () => {
      render(
        <DadoRevelavel leadId="l-1" campo="telefone" mascarado={MASCARA} podeRevelar href="/leads/l-1" />,
      )

      const link = screen.getByRole('link', { name: MASCARA })
      expect(link).toHaveAttribute('href', '/leads/l-1')
      expect(link.querySelector('button')).toBeNull()

      await clicar('Revelar telefone')

      expect(screen.getByRole('link', { name: NUMERO })).toHaveAttribute('href', '/leads/l-1')
    })
  })
})
