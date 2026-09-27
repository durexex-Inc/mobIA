import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { registrarAlteracaoNaoSalva } from '@/lib/inatividade'

import { AvisoDeInatividade } from './AvisoDeInatividade'

const MINUTO = 60_000

/** Avanca o relogio falso e deixa o React aplicar o que os timers fizeram. */
async function passar(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

type Fetch = (url: string, init?: RequestInit) => Promise<Response>

function chamadasA(api: Mock<Fetch>, caminho: string) {
  return api.mock.calls.filter(([url]) => url === caminho)
}

describe('AvisoDeInatividade', () => {
  let api: Mock<Fetch>
  let navegar: Mock<(url: string) => void>

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'Date'] })
    window.localStorage.clear()
    api = vi.fn<Fetch>(
      async (url) => new Response(null, { status: url === '/sair' ? 200 : 204 }),
    )
    vi.stubGlobal('fetch', api)
    navegar = vi.fn<(url: string) => void>()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    registrarAlteracaoNaoSalva('qualificacao', false)
  })

  it('nao mostra nada enquanto ha menos de 30 minutos sem interacao', async () => {
    render(<AvisoDeInatividade navegar={navegar} />)

    await passar(29 * MINUTO)

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('aos 30 minutos, abre o aviso com a contagem de 60 segundos', async () => {
    render(<AvisoDeInatividade navegar={navegar} />)

    await passar(30 * MINUTO)

    expect(screen.getByRole('alertdialog')).toHaveTextContent('encerrada em 60 segundos')
    await passar(15_000)
    expect(screen.getByRole('alertdialog')).toHaveTextContent('encerrada em 45 segundos')
  })

  describe('cenario: continuar a sessao a partir do aviso', () => {
    it('"Continuar conectado" fecha o aviso e manda o batimento ao servidor', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)
      await passar(30 * MINUTO + 20_000)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Continuar conectado' }))
      })

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
      expect(chamadasA(api, '/sessao/atividade')).toHaveLength(1)
      // E a sessao continua: mais 29 minutos sem nada, e o aviso nao volta.
      await passar(29 * MINUTO)
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
      expect(navegar).not.toHaveBeenCalled()
    })

    it('qualquer interacao tambem responde ao aviso', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)
      await passar(30 * MINUTO)

      await act(async () => {
        fireEvent.keyDown(window, { key: 'a' })
      })

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    })
  })

  describe('cenario: encerrar a sessao apos a contagem', () => {
    it('chama `/sair` e leva ao login com `erro=inatividade` e a tela atual', async () => {
      window.history.pushState({}, '', '/?de=2026-09-01')
      render(<AvisoDeInatividade navegar={navegar} />)

      await passar(31 * MINUTO + 1000)

      expect(chamadasA(api, '/sair')).toHaveLength(1)
      expect(api.mock.calls.find(([url]) => url === '/sair')?.[1]).toMatchObject({ method: 'POST' })
      expect(navegar).toHaveBeenCalledWith(
        '/login?returnTo=%2F%3Fde%3D2026-09-01&erro=inatividade',
      )
    })

    it('encerra uma vez so, mesmo com o relogio seguindo', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)

      await passar(35 * MINUTO)

      expect(chamadasA(api, '/sair')).toHaveLength(1)
      expect(navegar).toHaveBeenCalledTimes(1)
    })
  })

  describe('cenario: avisar sobre alteracao nao salva', () => {
    it('o aviso diz que a alteracao vai se perder', async () => {
      registrarAlteracaoNaoSalva('qualificacao', true)
      render(<AvisoDeInatividade navegar={navegar} />)

      await passar(30 * MINUTO)

      expect(screen.getByRole('alertdialog')).toHaveTextContent(
        'Você tem alterações que não foram salvas e serão perdidas.',
      )
    })

    it('sem alteracao pendente, o aviso nao fala nisso', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)

      await passar(30 * MINUTO)

      expect(screen.getByRole('alertdialog')).not.toHaveTextContent('não foram salvas')
    })
  })

  describe('batimento (D3)', () => {
    it('interagir manda no maximo um batimento por minuto', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)
      await passar(MINUTO)

      await act(async () => {
        fireEvent.keyDown(window, { key: 'a' })
        fireEvent.keyDown(window, { key: 'b' })
        fireEvent.pointerDown(window)
      })

      expect(chamadasA(api, '/sessao/atividade')).toHaveLength(1)
    })

    it('batimento com 401 quer dizer sessao ja encerrada: vai ao login', async () => {
      api.mockImplementation(async () => new Response(null, { status: 401 }))
      render(<AvisoDeInatividade navegar={navegar} />)
      await passar(MINUTO)

      await act(async () => {
        fireEvent.keyDown(window, { key: 'a' })
      })

      expect(navegar).toHaveBeenCalledWith(expect.stringContaining('erro=sessao_expirada'))
    })
  })

  describe('varias abas (D2)', () => {
    it('interacao em outra aba adia o aviso desta', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)
      await passar(20 * MINUTO)

      // Outra aba grava a interacao dela; o navegador avisa as demais pelo
      // evento `storage`.
      const agora = String(Date.now())
      window.localStorage.setItem('mobia:ultima-interacao', agora)
      await act(async () => {
        window.dispatchEvent(new StorageEvent('storage', { key: 'mobia:ultima-interacao', newValue: agora }))
      })
      await passar(15 * MINUTO)

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    })

    it('o `localStorage` guarda so um horario', async () => {
      render(<AvisoDeInatividade navegar={navegar} />)

      expect(Object.keys(window.localStorage)).toEqual(['mobia:ultima-interacao'])
      expect(window.localStorage.getItem('mobia:ultima-interacao')).toMatch(/^\d+$/)
    })
  })
})
