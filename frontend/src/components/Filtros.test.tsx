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

  it('o filtro por corretor aparece desabilitado com o motivo (TEC-316)', () => {
    render(<Filtros atuais={PERIODO} />)
    const corretor = screen.getByLabelText('Corretor')
    expect(corretor).toBeDisabled()
    expect(screen.getByText('Disponível após a alocação de corretor.')).toBeInTheDocument()
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
    render(<Filtros atuais={{ ...PERIODO, canal: 'web' }} />)
    expect(screen.getByLabelText('Canal')).toHaveValue('web')
  })
})

describe('o 422 ao lado do campo (TEC-313)', () => {
  it('poe a mensagem do backend junto do campo recusado', () => {
    // `Filtros` em isolamento: dado um `campos` que aponta `ate`, a mensagem
    // vai para o label certo. Na pratica, o 422 de "mais de 12 meses"
    // (TEC-316) NAO chega assim -- `FiltroInvalido` manda `detail` como
    // string, sem `loc`, entao cai no ramo "acima do formulario" abaixo,
    // como o de "de > ate" ja fazia. Este teste cobre a capacidade do
    // componente, nao o pipeline real daquele erro especifico.
    render(<Filtros atuais={PERIODO} erro="periodo maior que 12 meses" campos={['ate']} />)

    // Busca pelo `name` e nao por `getByLabelText('Até')`: a mensagem entra
    // DENTRO do `<label>`, entao o texto acessivel do campo deixa de ser
    // exatamente "Até" -- e uma consulta por igualdade passaria a nao achar o
    // campo justamente quando ha erro nele, que e o unico caso que este teste
    // cobre.
    const campo = document.querySelector('[name="ate"]')?.closest('label')
    expect(campo).toHaveTextContent('periodo maior que 12 meses')
  })

  it('nao repete a mesma mensagem acima do formulario', () => {
    // Repetir faria a gerente procurar dois problemas onde ha um.
    render(<Filtros atuais={PERIODO} erro="periodo maior que 12 meses" campos={['ate']} />)

    expect(screen.getAllByText('periodo maior que 12 meses')).toHaveLength(1)
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
