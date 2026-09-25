import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AindaNaoMedido } from './AindaNaoMedido'
import { ErroDeCarga } from './ErroDeCarga'
import { Skeleton } from './Skeleton'
import { Vazio } from './Vazio'

describe('AindaNaoMedido', () => {
  it('renderiza o rotulo e o motivo, e nada mais', () => {
    // Primeiro cenario do Gherkin: "o numero 0 nao aparece em lugar nenhum
    // daquele cartao". A asserta e de IGUALDADE e nao de ausencia do digito,
    // e a diferenca importa duas vezes:
    //
    // - Ausencia do digito seria FRACA demais no que interessa: um motivo
    //   legitimo pode conter numero ("sem fonte ate a RF-12"), entao a regra
    //   nao pode ser "nenhum digito".
    // - Igualdade e mais FORTE: ela prova que nao ha caminho por onde um valor
    //   entre, que e a garantia que o componente existe para dar. Se alguem
    //   passar a renderizar o valor cru aqui, o texto deixa de ser exatamente
    //   estes dois pedacos e o teste fica vermelho.
    const { container } = render(<AindaNaoMedido motivo="sem fonte até a RF-12" />)

    expect(container.textContent).toBe('Ainda não medidosem fonte até a RF-12')
  })

  it('sem motivo, o cartao nao tem digito nenhum', () => {
    // Complementa a asserta acima no caso em que ela pode ser literal: sem
    // motivo, nao ha texto legitimo com numero, entao qualquer digito na tela
    // so pode ter vindo do valor.
    const { container } = render(<AindaNaoMedido />)

    expect(container.textContent).not.toMatch(/\d/)
  })

  it('leva o motivo por tooltip E por leitor de tela', () => {
    // Os dois canais da D4. `title` sozinho nao existe em toque nem e
    // confiavel em leitor; sem o `aria-describedby`, quem usa leitor recebe a
    // ausencia sem a explicacao dela.
    render(<AindaNaoMedido motivo="sem fonte até a RF-12" />)

    const rotulo = screen.getByTitle('sem fonte até a RF-12')
    const descrito = rotulo.getAttribute('aria-describedby')

    expect(descrito).toBeTruthy()
    expect(document.getElementById(descrito!)?.textContent).toBe('sem fonte até a RF-12')
  })

  it('sem motivo, nao aponta para descricao que nao existe', () => {
    // `aria-describedby` apontando para id inexistente e pior que ausente:
    // o leitor de tela anuncia o rotulo e silencia onde havia promessa de
    // explicacao.
    render(<AindaNaoMedido />)

    expect(screen.getByText('Ainda não medido')).not.toHaveAttribute('aria-describedby')
  })
})

describe('ErroDeCarga', () => {
  it('mostra o codigo para o suporte e a acao de tentar de novo', () => {
    // Segundo cenario do Gherkin.
    render(
      <ErroDeCarga
        mensagem="Não foi possível carregar."
        requestId="7f3c-91ab"
        urlParaTentarDeNovo="/?de=2026-09-01"
      />,
    )

    expect(screen.getByText('7f3c-91ab')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute(
      'href',
      '/?de=2026-09-01',
    )
  })

  it('sem request id, nao inventa codigo nem deixa rotulo orfao', () => {
    // Um 502 de proxy nunca chegou ao FastAPI e nao tem id. Mostrar
    // "desconhecido" mandaria alguem procurar no log uma linha que nao existe.
    render(<ErroDeCarga mensagem="Não foi possível carregar." urlParaTentarDeNovo="/" />)

    expect(screen.queryByText(/Código para o suporte/)).toBeNull()
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toBeInTheDocument()
  })

  it('e anunciado como alerta', () => {
    render(<ErroDeCarga mensagem="Falhou." urlParaTentarDeNovo="/" />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

describe('Vazio e Skeleton', () => {
  it('vazio diz que nao houve o que medir, sem digito', () => {
    const { container } = render(<Vazio />)

    expect(screen.getByText('sem dados no período')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/\d/)
  })

  it('o skeleton nao e anunciado por leitor de tela', () => {
    // Ele nao tem conteudo a anunciar; quem avisa e o `aria-busy` de quem o
    // contem.
    render(<Skeleton />)

    expect(screen.getByTestId('skeleton')).toHaveAttribute('aria-hidden', 'true')
  })
})
