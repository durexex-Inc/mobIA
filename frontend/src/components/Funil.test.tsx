import { render, screen } from '@testing-library/react'
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
