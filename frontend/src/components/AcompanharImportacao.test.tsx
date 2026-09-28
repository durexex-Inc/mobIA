import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Importacao } from '@/lib/importacaoDeImoveis'
import { AcompanharImportacao } from './AcompanharImportacao'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Avanca o relogio falso e deixa o React aplicar o que os timers fizeram. */
async function passar(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const PROCESSANDO: Importacao = {
  importacaoId: 'imp-1',
  status: 'PROCESSANDO',
  nomeArquivo: 'imoveis.csv',
  processados: 0,
  inseridos: 0,
  atualizados: 0,
  inalterados: 0,
  rejeitados: 0,
  erros: [],
}

const CONCLUIDA: Importacao = {
  ...PROCESSANDO,
  status: 'CONCLUIDO',
  processados: 10,
  inseridos: 9,
  rejeitados: 1,
  erros: [{ linha: 4, motivo: 'titulo ausente' }],
}

describe('AcompanharImportacao', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  describe('cenario: acompanhar importacao em andamento, por polling (D3)', () => {
    it('nao chama a rede antes de 3s', () => {
      const api = vi.fn()
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={PROCESSANDO} />)

      expect(api).not.toHaveBeenCalled()
    })

    it('busca o relatorio pelo proxy a cada 3s enquanto PROCESSANDO', async () => {
      const api = vi.fn().mockResolvedValue(responde(PROCESSANDO))
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={PROCESSANDO} />)

      await passar(3000)

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/importacoes/imp-1',
        expect.objectContaining({ headers: expect.objectContaining({ Accept: 'application/json' }) }),
      )
    })

    it('para de perguntar assim que o status deixa de ser PROCESSANDO', async () => {
      const api = vi.fn().mockResolvedValue(responde(CONCLUIDA))
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={PROCESSANDO} />)

      await passar(3000)
      expect(api).toHaveBeenCalledTimes(1)

      await passar(6000)
      // Depois de CONCLUIDO o efeito nao reagenda: nenhuma chamada nova.
      expect(api).toHaveBeenCalledTimes(1)
    })

    it('mostra o relatorio atualizado depois do poll', async () => {
      const api = vi.fn().mockResolvedValue(responde(CONCLUIDA))
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={PROCESSANDO} />)

      await passar(3000)

      expect(screen.getByText(/Concluído/)).toBeInTheDocument()
      expect(screen.getByText('9')).toBeInTheDocument()
    })

    it('nao poll nenhum quando ja chega CONCLUIDO', async () => {
      const api = vi.fn()
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={CONCLUIDA} />)

      await passar(10_000)

      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('cenario: ver as linhas rejeitadas, com download em CSV (D5)', () => {
    it('lista numero da linha e motivo', () => {
      render(<AcompanharImportacao importacaoInicial={CONCLUIDA} />)

      expect(screen.getByText('Linha 4: titulo ausente')).toBeInTheDocument()
    })

    it('sem rejeicoes, nao mostra a lista nem o botao de download', () => {
      render(<AcompanharImportacao importacaoInicial={{ ...CONCLUIDA, erros: [] }} />)

      expect(screen.queryByRole('button', { name: 'Baixar rejeições' })).toBeNull()
    })

    it('o botao "Baixar rejeições" monta um Blob e dispara o download, sem round-trip', () => {
      const criarUrl = vi.fn(() => 'blob:fake')
      const revogarUrl = vi.fn()
      vi.stubGlobal('URL', { ...URL, createObjectURL: criarUrl, revokeObjectURL: revogarUrl })
      const cliqueSimulado = vi.fn()
      const criarElemento = document.createElement.bind(document)
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        const elemento = criarElemento(tag)
        if (tag === 'a') {
          elemento.click = cliqueSimulado
        }
        return elemento
      })
      const api = vi.fn()
      vi.stubGlobal('fetch', api)

      render(<AcompanharImportacao importacaoInicial={CONCLUIDA} />)
      act(() => {
        screen.getByRole('button', { name: 'Baixar rejeições' }).click()
      })

      expect(criarUrl).toHaveBeenCalledOnce()
      expect(cliqueSimulado).toHaveBeenCalledOnce()
      expect(revogarUrl).toHaveBeenCalledWith('blob:fake')
      expect(api).not.toHaveBeenCalled()

      vi.restoreAllMocks()
    })
  })

  describe('cenario: falha de rede no polling', () => {
    it('mostra aviso e continua tentando no proximo tique', async () => {
      const api = vi.fn().mockRejectedValue(new Error('rede fora'))
      vi.stubGlobal('fetch', api)
      render(<AcompanharImportacao importacaoInicial={PROCESSANDO} />)

      await passar(3000)

      expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível atualizar')
      expect(api).toHaveBeenCalledTimes(1)

      await passar(3000)
      expect(api).toHaveBeenCalledTimes(2)
    })
  })
})
