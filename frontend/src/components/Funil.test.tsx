import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Etapa, Filtros } from '@/lib/metricas'

import { Funil } from './Funil'

const ETAPAS: Etapa[] = [
  { nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Em conversa', quantidade: 268, disponivel: true, conversaoDaAnterior: 0.8375 },
  { nome: 'Qualificado', quantidade: 0, disponivel: true, conversaoDaAnterior: 0 },
  { nome: 'Recomendado', quantidade: 118, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: null },
  { nome: 'Handoff aceito', quantidade: 39, disponivel: true, conversaoDaAnterior: null },
]

const FILTROS: Filtros = { de: '2026-08-01', ate: '2026-08-31' }

describe('Funil', () => {
  it('mostra as seis etapas', () => {
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
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
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
    expect(screen.getByText('83,8%')).toBeInTheDocument()
  })

  it('a etapa sem fonte nao mostra zero', () => {
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
    const agendado = screen.getByTestId('etapa-Agendado')
    expect(agendado).toHaveTextContent('Ainda não medido')
    expect(agendado).not.toHaveTextContent(/\b0\b/)
  })

  it('a etapa com zero real mostra zero, e nao "sem fonte"', () => {
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
    const qualificado = screen.getByTestId('etapa-Qualificado')
    expect(qualificado).toHaveTextContent('0')
    expect(qualificado).not.toHaveTextContent('Ainda não medido')
  })

  it('renderiza travessao nas quatro etapas sem conversao calculavel', () => {
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
    // Novo (primeira etapa), Recomendado (anterior em zero), Agendado (sem
    // fonte propria) e Handoff aceito (anterior indisponivel).
    expect(screen.getAllByText('—')).toHaveLength(4)
  })

  it('nenhuma linha carrega atributo `style`, que a CSP de producao bloqueia (TEC-393)', () => {
    const { container } = render(<Funil etapas={ETAPAS} filtros={FILTROS} />)
    expect(container.querySelector('[style]')).toBeNull()
  })

  it('cada etapa conhecida tem o marcador da sua cor, e a desconhecida o neutro', () => {
    const { container } = render(
      <Funil
        etapas={[
          { nome: 'Novo', quantidade: 1, disponivel: true, conversaoDaAnterior: null },
          { nome: 'Etapa futura', quantidade: 1, disponivel: true, conversaoDaAnterior: 100 },
        ]}
        filtros={FILTROS}
      />,
    )
    const marcadores = container.querySelectorAll('.funil-marcador')
    expect(marcadores[0]).toHaveClass('funil-marcador--novo')
    expect(marcadores[1]).toHaveAttribute('class', 'funil-marcador')
  })
})

describe('Funil -- coorte incompleta (TEC-315)', () => {
  it('conversao acima de 100% mostra o valor real com o aviso, anunciado ao leitor de tela', () => {
    const etapas: Etapa[] = [
      { nome: 'Qualificado', quantidade: 1, disponivel: true, conversaoDaAnterior: null },
      { nome: 'Recomendado', quantidade: 40, disponivel: true, conversaoDaAnterior: 40.0 },
    ]
    render(<Funil etapas={etapas} filtros={FILTROS} />)

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
    render(<Funil etapas={etapas} filtros={FILTROS} />)

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
    render(<Funil etapas={etapas} filtros={FILTROS} />)

    expect(within(screen.getByTestId('etapa-Agendado')).getByText('—')).toBeInTheDocument()
    expect(within(screen.getByTestId('etapa-Handoff aceito')).getByText('—')).toBeInTheDocument()
  })
})

describe('Funil -- abrir os leads da etapa (TEC-318)', () => {
  it('etapa disponivel vira link para a lista de leads, com os filtros do funil', () => {
    const filtros: Filtros = { de: '2026-08-01', ate: '2026-08-31', canal: 'web', temperatura: 'QUENTE' }
    render(<Funil etapas={ETAPAS} filtros={filtros} />)

    const link = within(screen.getByTestId('etapa-Recomendado')).getByRole('link')
    const url = new URL(link.getAttribute('href')!, 'http://localhost')
    expect(url.pathname).toBe('/leads')
    expect(url.searchParams.get('de')).toBe('2026-08-01')
    expect(url.searchParams.get('ate')).toBe('2026-08-31')
    expect(url.searchParams.get('canal')).toBe('web')
    expect(url.searchParams.get('temperatura')).toBe('QUENTE')
    expect(url.searchParams.get('etapa')).toBe('Recomendado')
  })

  it('etapa sem fonte nao e um link', () => {
    render(<Funil etapas={ETAPAS} filtros={FILTROS} />)

    expect(within(screen.getByTestId('etapa-Agendado')).queryByRole('link')).toBeNull()
  })

  it('o link nao esconde "Coorte incompleta" do leitor de tela', () => {
    const etapas: Etapa[] = [
      { nome: 'Qualificado', quantidade: 1, disponivel: true, conversaoDaAnterior: null },
      { nome: 'Recomendado', quantidade: 40, disponivel: true, conversaoDaAnterior: 40.0 },
    ]
    render(<Funil etapas={etapas} filtros={FILTROS} />)

    const link = within(screen.getByTestId('etapa-Recomendado')).getByRole('link')
    expect(link).toHaveTextContent('Coorte incompleta')
  })
})
