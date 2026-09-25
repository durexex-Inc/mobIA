import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Filtros } from './Filtros'

const PERIODO = { de: '2026-08-01', ate: '2026-08-22' }

describe('Filtros', () => {
  it('tem os cinco filtros da RN-17.3 mais o periodo', () => {
    render(<Filtros atuais={PERIODO} />)
    expect(screen.getByLabelText('De')).toHaveValue('2026-08-01')
    expect(screen.getByLabelText('Até')).toHaveValue('2026-08-22')
    expect(screen.getByLabelText('Canal')).toBeInTheDocument()
    expect(screen.getByLabelText('Intenção')).toBeInTheDocument()
    expect(screen.getByLabelText('Temperatura')).toBeInTheDocument()
    expect(screen.getByLabelText('Corretor')).toBeInTheDocument()
  })

  it('e um form GET, para funcionar sem JavaScript', () => {
    const { container } = render(<Filtros atuais={PERIODO} />)
    expect(container.querySelector('form')).toHaveAttribute('method', 'get')
  })

  it('mostra qual filtro o backend recusou', () => {
    render(
      <Filtros
        atuais={{ ...PERIODO, temperatura: 'MORNA' }}
        erro="temperatura='MORNA' nao e um valor conhecido"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('sem erro, nao ha alerta', () => {
    render(<Filtros atuais={PERIODO} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('so oferece as temperaturas que existem', () => {
    render(<Filtros atuais={PERIODO} />)
    const opcoes = Array.from(
      screen.getByLabelText('Temperatura').querySelectorAll('option'),
    ).map((o) => o.textContent)
    expect(opcoes).toEqual(['Todas', 'QUENTE', 'MORNO', 'FRIO'])
  })

  it('preserva o filtro ja aplicado ao redesenhar', () => {
    render(<Filtros atuais={{ ...PERIODO, canal: 'web', corretorId: 'abc-123' }} />)
    expect(screen.getByLabelText('Canal')).toHaveValue('web')
    expect(screen.getByLabelText('Corretor')).toHaveValue('abc-123')
  })
})

describe('o 422 ao lado do campo (TEC-313)', () => {
  it('poe a mensagem do backend junto do campo recusado', () => {
    // Terceiro cenario do Gherkin, na forma que o painel permite exercitar: o
    // campo citado e `corretorId`, e a mensagem tem de aparecer ali e nao numa
    // frase solta que obrigue a gerente a descobrir qual campo esta errado.
    render(
      <Filtros atuais={PERIODO} erro="valor invalido em corretorId" campos={['corretorId']} />,
    )

    // Busca pelo `name` e nao por `getByLabelText('Corretor')`: a mensagem
    // entra DENTRO do `<label>`, entao o texto acessivel do campo deixa de ser
    // exatamente "Corretor" -- e uma consulta por igualdade passaria a nao
    // achar o campo justamente quando ha erro nele, que e o unico caso que
    // este teste cobre.
    const campo = document.querySelector('[name="corretorId"]')?.closest('label')
    expect(campo).toHaveTextContent('valor invalido em corretorId')
  })

  it('nao repete a mesma mensagem acima do formulario', () => {
    // Repetir faria a gerente procurar dois problemas onde ha um.
    render(
      <Filtros atuais={PERIODO} erro="valor invalido em corretorId" campos={['corretorId']} />,
    )

    expect(screen.getAllByText('valor invalido em corretorId')).toHaveLength(1)
  })

  it('erro sem campo identificavel fica acima do formulario', () => {
    // Os 422 cujo `detail` e prosa, e todo 403 ou 5xx que chegue por aqui: nao
    // ha campo a apontar, e o topo do formulario e o lugar certo.
    render(<Filtros atuais={PERIODO} erro="o periodo nao pode passar de 90 dias" />)

    expect(screen.getByRole('alert')).toHaveTextContent('o periodo nao pode passar de 90 dias')
  })

  it('campo que o formulario nao desenha nao some com a mensagem', () => {
    // Um `loc` do FastAPI pode apontar para algo que a UI nao tem. Se a
    // mensagem so pudesse aparecer ao lado do campo, ela sumiria da tela e a
    // gerente veria o painel vazio sem explicacao nenhuma.
    render(<Filtros atuais={PERIODO} erro="valor invalido em limite" campos={['limite']} />)

    expect(screen.getByRole('alert')).toHaveTextContent('valor invalido em limite')
  })
})
