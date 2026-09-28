import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { EntradaDoHistorico } from '@/lib/configuracao'
import { HistoricoDaConfiguracao } from './HistoricoDaConfiguracao'

const ITENS: EntradaDoHistorico[] = [
  {
    id: 'v-2',
    autor: 'u-admin-1',
    em: '2026-09-28T12:00:00+00:00',
    mudancas: [{ campo: 'pesoUrgencia', anterior: 25, novo: 30 }],
  },
  {
    id: 'v-1',
    autor: 'u-admin-2',
    em: '2026-09-20T09:30:00+00:00',
    mudancas: [
      { campo: 'nomeDoAssistente', anterior: null, novo: 'Ana' },
      {
        campo: 'cadencia',
        anterior: { QUENTE: [2, 24, 72, 168] },
        novo: { QUENTE: [4, 24, 72, 168] },
      },
    ],
  },
]

/** Uma linha de mudanca e `<strong>rotulo:</strong> resto`, em nos separados. */
function linhaDeMudanca(container: HTMLElement, rotulo: string): HTMLElement {
  const item = Array.from(container.querySelectorAll('li')).find((li) =>
    li.textContent?.startsWith(rotulo),
  )
  if (!item) {
    throw new Error(`nenhuma linha comeca com "${rotulo}"`)
  }
  return item
}

describe('HistoricoDaConfiguracao (quarto cenario do Gherkin)', () => {
  it('mostra cada entrada na ordem recebida, sem reordenar', () => {
    render(<HistoricoDaConfiguracao itens={ITENS} />)

    const entradas = screen.getAllByText(/u-admin-/)
    expect(entradas[0]).toHaveTextContent('u-admin-1')
    expect(entradas[1]).toHaveTextContent('u-admin-2')
  })

  it('mostra autor cru e a mudanca como "rotulo: anterior -> novo"', () => {
    const { container } = render(<HistoricoDaConfiguracao itens={ITENS} />)

    expect(screen.getByText('u-admin-1')).toBeInTheDocument()
    expect(linhaDeMudanca(container, 'Peso de urgência:')).toHaveTextContent(
      'Peso de urgência: 25 → 30',
    )
  })

  it('valor anterior nulo aparece como travessao', () => {
    const { container } = render(<HistoricoDaConfiguracao itens={ITENS} />)

    expect(linhaDeMudanca(container, 'Nome do assistente:')).toHaveTextContent(
      'Nome do assistente: — → Ana',
    )
  })

  it('cadencia (objeto) aparece formatada por temperatura', () => {
    const { container } = render(<HistoricoDaConfiguracao itens={ITENS} />)

    expect(linhaDeMudanca(container, 'Cadência:')).toHaveTextContent(
      'Cadência: QUENTE: 2, 24, 72, 168 → QUENTE: 4, 24, 72, 168',
    )
  })

  it('lista vazia mostra que nao ha alteracao registrada', () => {
    render(<HistoricoDaConfiguracao itens={[]} />)

    expect(screen.getByText('Nenhuma alteração registrada ainda.')).toBeInTheDocument()
  })
})
