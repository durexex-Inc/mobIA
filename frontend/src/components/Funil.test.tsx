import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Etapa } from '@/lib/metricas'

import { Funil } from './Funil'

const ETAPAS: Etapa[] = [
  { nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Em conversa', quantidade: 268, disponivel: true, conversaoDaAnterior: 0.8375 },
  { nome: 'Qualificado', quantidade: 0, disponivel: true, conversaoDaAnterior: 0 },
  { nome: 'Recomendado', quantidade: 118, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: null },
  { nome: 'Handoff aceito', quantidade: 39, disponivel: true, conversaoDaAnterior: null },
]

describe('Funil', () => {
  it('mostra as seis etapas', () => {
    render(<Funil etapas={ETAPAS} />)
    for (const nome of [
      'Novo',
      'Em conversa',
      'Qualificado',
      'Recomendado',
      'Agendado',
      'Handoff aceito',
    ]) {
      expect(screen.getByText(nome)).toBeInTheDocument()
    }
  })

  it('escreve a conversao entre etapas consecutivas', () => {
    render(<Funil etapas={ETAPAS} />)
    expect(screen.getByText('83,8%')).toBeInTheDocument()
  })

  it('a etapa sem fonte nao mostra zero', () => {
    render(<Funil etapas={ETAPAS} />)
    const agendado = screen.getByTestId('etapa-Agendado')
    expect(agendado).toHaveTextContent('Ainda não medido')
    expect(agendado).not.toHaveTextContent(/\b0\b/)
  })

  it('a etapa com zero real mostra zero, e nao "sem fonte"', () => {
    render(<Funil etapas={ETAPAS} />)
    const qualificado = screen.getByTestId('etapa-Qualificado')
    expect(qualificado).toHaveTextContent('0')
    expect(qualificado).not.toHaveTextContent('Ainda não medido')
  })

  it('renderiza travessao nas quatro etapas sem conversao calculavel', () => {
    render(<Funil etapas={ETAPAS} />)
    // Novo (primeira etapa), Recomendado (anterior em zero), Agendado (sem
    // fonte propria) e Handoff aceito (anterior indisponivel).
    expect(screen.getAllByText('—')).toHaveLength(4)
  })

  it('a barra da etapa sem fonte tem largura zero, e nao NaN', () => {
    render(<Funil etapas={ETAPAS} />)
    const barra = screen.getByTestId('barra-Agendado')
    expect(barra.getAttribute('style')).not.toContain('NaN')
  })
})

describe('Funil -- coorte incompleta (TEC-315)', () => {
  it('conversao acima de 100% mostra o valor real com o aviso, anunciado ao leitor de tela', () => {
    const etapas: Etapa[] = [
      { nome: 'Qualificado', quantidade: 1, disponivel: true, conversaoDaAnterior: null },
      { nome: 'Recomendado', quantidade: 40, disponivel: true, conversaoDaAnterior: 40.0 },
    ]
    render(<Funil etapas={etapas} />)

    const recomendado = screen.getByTestId('etapa-Recomendado')
    expect(recomendado).toHaveTextContent('4.000,0%')
    expect(recomendado).toHaveTextContent('Coorte incompleta')
    // O aviso nao pode estar dentro do `aria-label` fixo do percentual --
    // isso o apagaria para quem usa leitor de tela.
    const aviso = within(recomendado).getByText('Coorte incompleta', { exact: false })
    expect(aviso.closest('[aria-label^="conversão"]')).toBeNull()
  })

  it('conversao normal (<=100%) nao mostra o aviso', () => {
    const etapas: Etapa[] = [
      { nome: 'Qualificado', quantidade: 100, disponivel: true, conversaoDaAnterior: null },
      { nome: 'Recomendado', quantidade: 40, disponivel: true, conversaoDaAnterior: 0.4 },
    ]
    render(<Funil etapas={etapas} />)

    expect(screen.queryByText('Coorte incompleta')).toBeNull()
  })

  it('etapa sem fonte nao propaga conversao, mesmo que o backend mande um numero ali', () => {
    // Hipotese defensiva (D1 do desenho): o Funil nao confia cegamente no
    // `conversaoDaAnterior` do backend quando ele mesmo, ou o anterior, esta
    // sem fonte.
    const etapas: Etapa[] = [
      { nome: 'Recomendado', quantidade: 10, disponivel: true, conversaoDaAnterior: null },
      { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: 0.5 },
      { nome: 'Handoff aceito', quantidade: 3, disponivel: true, conversaoDaAnterior: 0.3 },
    ]
    render(<Funil etapas={etapas} />)

    expect(within(screen.getByTestId('etapa-Agendado')).getByText('—')).toBeInTheDocument()
    expect(within(screen.getByTestId('etapa-Handoff aceito')).getByText('—')).toBeInTheDocument()
  })
})
