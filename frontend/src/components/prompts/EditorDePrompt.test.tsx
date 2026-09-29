import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { LimitesDoPrompt } from '@/lib/prompts'
import { EditorDePrompt } from './EditorDePrompt'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

// O Monaco de verdade nao roda em jsdom (canvas, workers). Um `<textarea>`
// basta para exercitar o contrato de `value`/`onChange` que `EditorDePrompt`
// usa -- o realce de sintaxe (`beforeMount`) e coberto pela leitura de
// `components/prompts/linguagemDoPrompt.ts`, nao por este teste.
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea aria-label="editor de prompt" value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}))

const LIMITES: LimitesDoPrompt = { marcadores: ['{assistente}', '{tom}'], maximoDeCaracteres: 500 }

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json' } })
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('EditorDePrompt', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    refresh.mockClear()
    api = vi.fn()
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('publicar chama o bff com o texto e atualiza a pagina (cenario: publicar nova versao)', async () => {
    api.mockResolvedValueOnce(responde({ publicada: true, ativa: { versao: 8 } }, 201))

    render(<EditorDePrompt agente="investidor" textoInicial="Você é {assistente}, tom {tom}." limites={LIMITES} />)

    // `next/dynamic` carrega o Editor de forma assincrona.
    fireEvent.change(await screen.findByLabelText('editor de prompt'), {
      target: { value: 'Você é {assistente}, tom {tom}. Novo texto.' },
    })
    await clicar('Publicar')

    expect(api).toHaveBeenCalledWith(
      '/bff/api/v1/prompts/INVESTIDOR/versoes',
      expect.objectContaining({ method: 'POST' }),
    )
    const corpo = JSON.parse(String(api.mock.calls[0][1]?.body))
    expect(corpo).toEqual({ texto: 'Você é {assistente}, tom {tom}. Novo texto.' })
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('texto identico ao vigente avisa e nao recarrega', async () => {
    api.mockResolvedValueOnce(responde({ publicada: false, ativa: { versao: 7 } }, 200))

    render(<EditorDePrompt agente="agente" textoInicial="Texto igual" limites={LIMITES} />)
    await clicar('Publicar')

    expect(screen.getByText('O texto é igual ao vigente; nada foi publicado.')).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('422 do backend e mostrado como veio', async () => {
    api.mockResolvedValueOnce(
      responde({ detail: 'falta o marcador {tom}: e por ele que a configuracao do agente entra no prompt' }, 422),
    )

    render(<EditorDePrompt agente="agente" textoInicial="Texto sem marcador" limites={LIMITES} />)
    await clicar('Publicar')

    expect(
      screen.getByText('falta o marcador {tom}: e por ele que a configuracao do agente entra no prompt'),
    ).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()
  })
})
