import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Importacao } from '@/lib/importacaoDeImoveis'
import { ImportarImoveis } from './ImportarImoveis'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function arquivoCsv(conteudo: string, nome = 'imoveis.csv') {
  return new File([conteudo], nome, { type: 'text/csv' })
}

async function selecionarArquivo(arquivo: File) {
  const input = screen.getByLabelText('Arquivo CSV') as HTMLInputElement
  await act(async () => {
    fireEvent.change(input, { target: { files: [arquivo] } })
  })
}

const IMPORTACAO_CONCLUIDA: Importacao = {
  importacaoId: 'imp-1',
  status: 'CONCLUIDO',
  nomeArquivo: 'anterior.csv',
  processados: 5,
  inseridos: 5,
  atualizados: 0,
  inalterados: 0,
  rejeitados: 0,
  erros: [],
}

describe('ImportarImoveis', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ importacaoId: 'imp-novo', status: 'PROCESSANDO' }, 202))
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: pre-visualizar antes de enviar (D1)', () => {
    it('mostra as colunas e linhas do CSV selecionado, sem chamar a rede', async () => {
      render(<ImportarImoveis importacaoInicial={null} />)

      await selecionarArquivo(arquivoCsv('codigo,titulo\nAP-1,Casa\nAP-2,Apto'))

      expect(screen.getByText('Prévia das 10 primeiras linhas:')).toBeInTheDocument()
      expect(screen.getByRole('columnheader', { name: 'codigo' })).toBeInTheDocument()
      expect(screen.getByText('AP-1')).toBeInTheDocument()
      expect(screen.getByText('AP-2')).toBeInTheDocument()
      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('cenario: recusar arquivo acima do limite (D2)', () => {
    it('recusa na selecao, sem ler o conteudo nem mostrar previa', async () => {
      render(<ImportarImoveis importacaoInicial={null} />)

      const grande = new File(['x'], 'grande.csv', { type: 'text/csv' })
      Object.defineProperty(grande, 'size', { value: 10 * 1024 * 1024 + 1 })

      await selecionarArquivo(grande)

      expect(screen.getByRole('alert')).toHaveTextContent('10 MB')
      expect(screen.queryByText('Prévia das 10 primeiras linhas:')).toBeNull()
      expect(api).not.toHaveBeenCalled()
    })

    it('arquivo exatamente no limite passa', async () => {
      render(<ImportarImoveis importacaoInicial={null} />)

      const noLimite = new File(['codigo\nAP-1'], 'ok.csv', { type: 'text/csv' })
      Object.defineProperty(noLimite, 'size', { value: 10 * 1024 * 1024 })

      await selecionarArquivo(noLimite)

      expect(screen.queryByRole('alert')).toBeNull()
      expect(screen.getByText('Prévia das 10 primeiras linhas:')).toBeInTheDocument()
    })
  })

  describe('cenario: confirmar o envio', () => {
    it('manda o POST com FormData pelo proxy e passa a acompanhar a nova importacao', async () => {
      render(<ImportarImoveis importacaoInicial={null} />)
      await selecionarArquivo(arquivoCsv('codigo,titulo\nAP-1,Casa'))

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirmar importação' }))
      })

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/importar',
        expect.objectContaining({ method: 'POST' }),
      )
      const corpo = (api.mock.calls[0][1] as RequestInit).body as FormData
      expect(corpo).toBeInstanceOf(FormData)
      expect(corpo.get('arquivo')).toBeInstanceOf(File)

      // Some a previa, e o acompanhamento da nova importacao aparece.
      expect(screen.queryByText('Prévia das 10 primeiras linhas:')).toBeNull()
      expect(screen.getByText(/imoveis\.csv/)).toBeInTheDocument()
      expect(screen.getByText(/Processando/)).toBeInTheDocument()
    })

    it('erro do backend mostra aviso e nao troca a importacao em curso', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'boom' }, 500))
      render(<ImportarImoveis importacaoInicial={IMPORTACAO_CONCLUIDA} />)
      await selecionarArquivo(arquivoCsv('codigo,titulo\nAP-1,Casa'))

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirmar importação' }))
      })

      expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível importar')
      expect(screen.getByText(/anterior\.csv/)).toBeInTheDocument()
    })

    it('401 mostra a mensagem de sessao expirada', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'nao autenticado' }, 401))
      render(<ImportarImoveis importacaoInicial={null} />)
      await selecionarArquivo(arquivoCsv('codigo,titulo\nAP-1,Casa'))

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirmar importação' }))
      })

      expect(screen.getByRole('alert')).toHaveTextContent('sessão terminou')
    })

    it('falha de rede mostra aviso generico', async () => {
      api.mockRejectedValueOnce(new Error('rede fora'))
      render(<ImportarImoveis importacaoInicial={null} />)
      await selecionarArquivo(arquivoCsv('codigo,titulo\nAP-1,Casa'))

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirmar importação' }))
      })

      expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível falar com o servidor')
    })
  })

  describe('cenario: acompanhar importacao em andamento ao abrir a pagina (D4)', () => {
    it('mostra a importacao mais recente pre-carregada, sem POST nenhum', () => {
      render(<ImportarImoveis importacaoInicial={IMPORTACAO_CONCLUIDA} />)

      expect(screen.getByText(/anterior\.csv/)).toBeInTheDocument()
      expect(screen.getByText(/Concluído/)).toBeInTheDocument()
      expect(api).not.toHaveBeenCalled()
    })

    it('sem nenhuma importacao anterior, nao mostra acompanhamento nenhum', () => {
      render(<ImportarImoveis importacaoInicial={null} />)

      expect(screen.queryByText(/Processando|Concluído|Falhou/)).toBeNull()
    })
  })
})
