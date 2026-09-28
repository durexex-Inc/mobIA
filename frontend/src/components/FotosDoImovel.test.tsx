import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { FotosDoImovel } from './FotosDoImovel'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function jpeg(nome = 'foto.jpg', tamanho = 1024): File {
  const f = new File(['x'], nome, { type: 'image/jpeg' })
  Object.defineProperty(f, 'size', { value: tamanho })
  return f
}

describe('FotosDoImovel', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn()
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: enviar uma foto valida', () => {
    it('faz POST de FormData e mostra a miniatura nova', async () => {
      api.mockResolvedValueOnce(
        responde({ fotos: ['/api/v1/imoveis/im-1/fotos/f-1'] }, 201),
      )
      const onFotosMudaram = vi.fn()
      render(<FotosDoImovel imovelId="im-1" fotos={[]} onFotosMudaram={onFotosMudaram} />)

      const input = screen.getByLabelText('Adicionar foto') as HTMLInputElement
      await act(async () => {
        fireEvent.change(input, { target: { files: [jpeg()] } })
      })

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/im-1/fotos',
        expect.objectContaining({ method: 'POST' }),
      )
      const corpo = (api.mock.calls[0][1] as RequestInit).body as FormData
      expect(corpo).toBeInstanceOf(FormData)
      expect(corpo.get('arquivo')).toBeInstanceOf(File)
      expect(onFotosMudaram).toHaveBeenCalledWith(['/api/v1/imoveis/im-1/fotos/f-1'])
    })
  })

  describe('cenario: recusa client-side antes de qualquer POST (D6)', () => {
    it('arquivo grande demais nao chama a rede', async () => {
      const grande = jpeg('grande.jpg', 5 * 1024 * 1024 + 1)
      render(<FotosDoImovel imovelId="im-1" fotos={[]} onFotosMudaram={vi.fn()} />)

      const input = screen.getByLabelText('Adicionar foto') as HTMLInputElement
      await act(async () => {
        fireEvent.change(input, { target: { files: [grande] } })
      })

      expect(screen.getByRole('alert')).toHaveTextContent('5')
      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('cenario: o backend recusa por assinatura de bytes (D3)', () => {
    it('mostra o 422 do backend como veio', async () => {
      api.mockResolvedValueOnce(
        responde({ detail: 'formato nao reconhecido: aceita apenas JPEG, PNG ou WebP' }, 422),
      )
      render(<FotosDoImovel imovelId="im-1" fotos={[]} onFotosMudaram={vi.fn()} />)

      const input = screen.getByLabelText('Adicionar foto') as HTMLInputElement
      await act(async () => {
        // Nome/extensao de jpeg engana a checagem do cliente; so o backend recusa.
        fireEvent.change(input, { target: { files: [jpeg('disfarcado.jpg')] } })
      })

      expect(screen.getByRole('alert')).toHaveTextContent('formato nao reconhecido')
    })
  })

  describe('cenario: reordenar por botao, com o teclado (Gherkin)', () => {
    it('"mover para cima" na segunda foto manda o PATCH com a nova ordem', async () => {
      api.mockResolvedValueOnce(responde({ fotos: ['b', 'a'] }, 200))
      const onFotosMudaram = vi.fn()
      render(<FotosDoImovel imovelId="im-1" fotos={['a', 'b']} onFotosMudaram={onFotosMudaram} />)

      const botao = screen.getByRole('button', { name: 'Mover foto 2 para cima' })
      botao.focus()
      expect(botao).toHaveFocus()
      await act(async () => {
        fireEvent.keyDown(botao, { key: 'Enter' })
        fireEvent.click(botao)
      })

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/im-1',
        expect.objectContaining({ method: 'PATCH' }),
      )
      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ fotos: ['b', 'a'] })
      expect(onFotosMudaram).toHaveBeenCalledWith(['b', 'a'])
    })

    it('a primeira foto nao tem botao "mover para cima" acionavel', () => {
      render(<FotosDoImovel imovelId="im-1" fotos={['a', 'b']} onFotosMudaram={vi.fn()} />)

      expect(screen.getByRole('button', { name: 'Mover foto 1 para cima' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Mover foto 2 para baixo' })).toBeDisabled()
    })

    it('"mover para baixo" na primeira foto tambem manda o PATCH com a nova ordem', async () => {
      api.mockResolvedValueOnce(responde({ fotos: ['b', 'a', 'c'] }, 200))
      const onFotosMudaram = vi.fn()
      render(
        <FotosDoImovel imovelId="im-1" fotos={['a', 'b', 'c']} onFotosMudaram={onFotosMudaram} />,
      )

      const botao = screen.getByRole('button', { name: 'Mover foto 1 para baixo' })
      botao.focus()
      await act(async () => {
        fireEvent.click(botao)
      })

      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ fotos: ['b', 'a', 'c'] })
      expect(onFotosMudaram).toHaveBeenCalledWith(['b', 'a', 'c'])
    })
  })

  describe('cenario: remover', () => {
    it('manda o PATCH sem aquela foto', async () => {
      api.mockResolvedValueOnce(responde({ fotos: ['a'] }, 200))
      const onFotosMudaram = vi.fn()
      render(<FotosDoImovel imovelId="im-1" fotos={['a', 'b']} onFotosMudaram={onFotosMudaram} />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Remover foto 2' }))
      })

      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ fotos: ['a'] })
      expect(onFotosMudaram).toHaveBeenCalledWith(['a'])
    })
  })

  describe('cenario: limite de 15 fotos', () => {
    it('esconde o campo de upload e avisa o limite', () => {
      const quinze = Array.from({ length: 15 }, (_, i) => `foto-${i}`)
      render(<FotosDoImovel imovelId="im-1" fotos={quinze} onFotosMudaram={vi.fn()} />)

      expect(screen.queryByLabelText('Adicionar foto')).toBeNull()
      expect(screen.getByRole('status')).toHaveTextContent('15')
    })
  })

  describe('drag and drop nativo (D5, belt-and-suspenders)', () => {
    it('os handlers de arraste estao ligados no item da lista', () => {
      render(<FotosDoImovel imovelId="im-1" fotos={['a', 'b']} onFotosMudaram={vi.fn()} />)

      const item = screen.getByAltText('Foto 1 do imóvel').closest('li')
      expect(item).toHaveAttribute('draggable', 'true')
    })
  })

  describe('a miniatura atravessa o proxy (D7)', () => {
    it('o `src` do `<img>` tem o prefixo `/bff`, e nao a URL crua que o backend guarda', () => {
      render(
        <FotosDoImovel
          imovelId="im-1"
          fotos={['/api/v1/imoveis/im-1/fotos/f-1']}
          onFotosMudaram={vi.fn()}
        />,
      )

      const img = screen.getByAltText('Foto 1 do imóvel') as HTMLImageElement
      expect(img.getAttribute('src')).toBe('/bff/api/v1/imoveis/im-1/fotos/f-1')
    })
  })
})
