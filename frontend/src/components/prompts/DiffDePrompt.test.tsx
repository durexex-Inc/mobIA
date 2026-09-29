import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DiffDePrompt } from './DiffDePrompt'

// Mesma razao do mock em `EditorDePrompt.test.tsx`: o `DiffEditor` de
// verdade nao roda em jsdom. Aqui so importa que os dois textos cheguem.
vi.mock('@monaco-editor/react', () => ({
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => (
    <div>
      <div data-testid="original">{original}</div>
      <div data-testid="modified">{modified}</div>
    </div>
  ),
}))

describe('DiffDePrompt', () => {
  it('mostra os rotulos e os dois textos das versoes comparadas (cenario: comparar duas versoes)', async () => {
    render(
      <DiffDePrompt
        textoDe="texto da versao 6"
        textoPara="texto da versao 7"
        rotuloDe="Versão 6"
        rotuloPara="Versão 7"
      />,
    )

    expect(screen.getByText('Versão 6')).toBeInTheDocument()
    expect(screen.getByText('Versão 7')).toBeInTheDocument()
    // `next/dynamic` carrega o `DiffEditor` de forma assincrona -- `findBy`
    // espera a promessa do import (mockado) resolver.
    expect(await screen.findByTestId('original')).toHaveTextContent('texto da versao 6')
    expect(await screen.findByTestId('modified')).toHaveTextContent('texto da versao 7')
  })
})
