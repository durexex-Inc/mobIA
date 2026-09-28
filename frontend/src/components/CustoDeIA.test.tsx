import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CustoDeIA as CustoDeIATipo } from '@/lib/custo'

import { CustoDeIA } from './CustoDeIA'

const BASE: CustoDeIATipo = {
  custoTotalUsd: 0.84,
  custoPorConversaUsd: 0.084,
  custoPorLeadQualificadoUsd: 0.42,
  tokensPorModelo: {
    'claude-sonnet': { entrada: 4820000, saida: 12000, cacheLeitura: 0, cacheEscrita: 0 },
  },
  conversas: 10,
  leadsQualificados: 2,
  mensagensSemPreco: 0,
  alvoPorLeadQualificadoUsd: 0.12,
  acimaDoAlvo: true,
  orcamento: null,
}

describe('CustoDeIA', () => {
  it('mostra o custo total em US$ com 2 casas', () => {
    render(<CustoDeIA custo={BASE} />)

    expect(within(screen.getByTestId('custo-total')).getByText('US$ 0,84')).toBeInTheDocument()
  })

  it('mostra as medias em US$ com 4 casas', () => {
    render(<CustoDeIA custo={BASE} />)

    expect(within(screen.getByTestId('custo-por-conversa')).getByText('US$ 0,0840')).toBeInTheDocument()
    expect(within(screen.getByTestId('custo-por-lead')).getByText(/US\$ 0,4200/)).toBeInTheDocument()
  })

  it('periodo sem conversas: custo total e US$ 0,00, nao "Ainda não medido"', () => {
    const custo: CustoDeIATipo = {
      ...BASE,
      custoTotalUsd: 0,
      custoPorConversaUsd: null,
      custoPorLeadQualificadoUsd: null,
      conversas: 0,
      leadsQualificados: 0,
      acimaDoAlvo: null,
    }
    render(<CustoDeIA custo={custo} />)

    expect(within(screen.getByTestId('custo-total')).getByText('US$ 0,00')).toBeInTheDocument()
    expect(screen.queryByText('Ainda não medido')).not.toBeInTheDocument()
  })

  it('media nula mostra "sem dados no período", nunca "Ainda não medido"', () => {
    const custo: CustoDeIATipo = { ...BASE, custoPorConversaUsd: null }
    render(<CustoDeIA custo={custo} />)

    expect(within(screen.getByTestId('custo-por-conversa')).getByText('sem dados no período')).toBeInTheDocument()
  })

  it('alerta de orcamento aparece quando `orcamento.alerta` e true', () => {
    const custo: CustoDeIATipo = {
      ...BASE,
      orcamento: {
        mensalUsd: 100,
        doPeriodoUsd: 100,
        consumidoUsd: 80,
        consumidoPct: 80,
        alerta: true,
      },
    }
    render(<CustoDeIA custo={custo} />)

    const alerta = screen.getByRole('alert')
    expect(alerta).toHaveTextContent('80,0%')
    expect(screen.queryByText(/Configurar orçamento/)).not.toBeInTheDocument()
  })

  it('orcamento configurado mas abaixo do limiar: sem alerta', () => {
    const custo: CustoDeIATipo = {
      ...BASE,
      orcamento: {
        mensalUsd: 100,
        doPeriodoUsd: 100,
        consumidoUsd: 30,
        consumidoPct: 30,
        alerta: false,
      },
    }
    render(<CustoDeIA custo={custo} />)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('sem orcamento: nenhum alerta, e um link para configurar', () => {
    render(<CustoDeIA custo={BASE} />)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Configurar orçamento' })).toHaveAttribute(
      'href',
      '/admin',
    )
  })

  it('tokens por modelo: uma linha por modelo', () => {
    render(<CustoDeIA custo={BASE} />)

    const linha = screen.getByRole('row', { name: /claude-sonnet/ })
    expect(within(linha).getByText('4.820.000')).toBeInTheDocument()
  })

  it('sem tokens, a tabela nao aparece', () => {
    render(<CustoDeIA custo={{ ...BASE, tokensPorModelo: {} }} />)

    expect(screen.queryByText('Tokens por modelo')).not.toBeInTheDocument()
  })

  it('mensagens sem preco: nota aparece so quando ha alguma', () => {
    const { rerender } = render(<CustoDeIA custo={BASE} />)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()

    rerender(<CustoDeIA custo={{ ...BASE, mensagensSemPreco: 3 }} />)
    expect(screen.getByRole('note')).toHaveTextContent('3 mensagem(ns) sem preço')
  })

  it('acima do alvo aparece ao lado do custo por lead qualificado', () => {
    render(<CustoDeIA custo={BASE} />)

    expect(within(screen.getByTestId('custo-por-lead')).getByText(/acima do alvo/)).toBeInTheDocument()
  })

  it('dentro do alvo quando `acimaDoAlvo` e false', () => {
    render(<CustoDeIA custo={{ ...BASE, acimaDoAlvo: false }} />)

    expect(within(screen.getByTestId('custo-por-lead')).getByText(/dentro do alvo/)).toBeInTheDocument()
  })
})
