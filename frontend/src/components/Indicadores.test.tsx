import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Indicadores } from './Indicadores'

const DADOS = {
  leadsNovos: 320,
  conversasAtivas: 87,
  taxaQualificacao: 0.44,
  distribuicaoPorTemperatura: { QUENTE: 41, MORNO: 63, FRIO: 37 },
  tempoMedioPrimeiraRespostaSeg: 4.2,
  tempoMedioQualificacaoSeg: 512,
  slaHandoffCumpridoPct: 0.87,
  agendamentosCriados: null,
  agendamentosConfirmados: null,
  agendamentosRealizados: null,
  taxaNoShow: null,
}

const INDISPONIVEIS = [
  'agendamentosCriados',
  'agendamentosConfirmados',
  'agendamentosRealizados',
  'taxaNoShow',
]

describe('Indicadores', () => {
  it('mostra os indicadores com numero', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    expect(screen.getByTestId('indicador-leadsNovos')).toHaveTextContent('320')
    expect(screen.getByTestId('indicador-taxaQualificacao')).toHaveTextContent('44,0%')
  })

  it('mostra a distribuicao por temperatura nas tres faixas', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    const temperatura = screen.getByTestId('indicador-distribuicaoPorTemperatura')
    expect(temperatura).toHaveTextContent('QUENTE')
    expect(temperatura).toHaveTextContent('41')
    expect(temperatura).toHaveTextContent('FRIO')
  })

  it('o indicador sem fonte diz por que, e nao mostra zero', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    const noShow = screen.getByTestId('indicador-taxaNoShow')
    expect(noShow).toHaveTextContent('sem fonte de dados')
    expect(noShow).not.toHaveTextContent(/\b0\b/)
  })

  it('explica uma vez que as visitas ainda nao sao registradas', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    expect(screen.getByRole('note')).toHaveTextContent(/visita/i)
  })

  it('sem indisponiveis, nao ha nota', () => {
    render(<Indicadores indicadores={{ leadsNovos: 1 }} indisponiveis={[]} />)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('distribuicao vazia diz que nao houve dados, e nao fica em branco', () => {
    // Achado na verificacao de ponta a ponta: com a coorte vazia o backend
    // devolve `{}`, e o cartao renderizava string vazia -- que na tela parece
    // painel quebrado, nao ausencia de lead.
    render(<Indicadores indicadores={{ distribuicaoPorTemperatura: {} }} indisponiveis={[]} />)

    expect(screen.getByTestId('indicador-distribuicaoPorTemperatura')).toHaveTextContent(
      'sem dados no período',
    )
  })

  it('nulo por coorte vazia NAO se confunde com nulo por falta de fonte', () => {
    // Sao duas ausencias diferentes e o texto tem de distingui-las: a taxa de
    // no-show e nula porque ninguem registra visita -- defeito do sistema --,
    // e a taxa de qualificacao e nula porque nao houve lead no periodo --
    // fato do negocio. Um texto so mandaria a gerente procurar um problema
    // que nao existe, ou ignorar um que existe.
    render(<Indicadores indicadores={{ taxaQualificacao: null }} indisponiveis={[]} />)

    const taxa = screen.getByTestId('indicador-taxaQualificacao')
    expect(taxa).toHaveTextContent('sem dados no período')
    expect(taxa).not.toHaveTextContent('sem fonte de dados')
  })
})
