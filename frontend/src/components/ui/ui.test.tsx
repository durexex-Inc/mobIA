import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Botao } from './Botao'
import { CampoDeSelecao } from './CampoDeSelecao'
import { Cartao } from './Cartao'

describe('CampoDeSelecao', () => {
  it('repassa tudo ao `<select>`, e o rotulo de fora continua nomeando o campo', () => {
    render(
      <label>
        Canal
        <CampoDeSelecao name="canal" defaultValue="web" disabled>
          <option value="">Todos</option>
          <option value="web">web</option>
        </CampoDeSelecao>
      </label>,
    )
    const campo = screen.getByLabelText('Canal')
    expect(campo.tagName).toBe('SELECT')
    expect(campo).toHaveValue('web')
    expect(campo).toBeDisabled()
    expect(campo.parentElement).toHaveClass('campo-selecao')
  })
})

describe('Cartao', () => {
  it('e um div por padrao, e repassa classe e atributos', () => {
    render(
      <Cartao className="indicador" data-testid="c">
        conteudo
      </Cartao>,
    )
    const cartao = screen.getByTestId('c')
    expect(cartao.tagName).toBe('DIV')
    expect(cartao).toHaveClass('cartao', 'indicador')
  })

  it('vira `section` quando pedido', () => {
    render(<Cartao como="section" aria-label="Regiao" />)
    expect(screen.getByRole('region', { name: 'Regiao' })).toHaveClass('cartao')
  })
})

describe('Botao', () => {
  it('e `type="button"` por padrao, para nao enviar formulario por engano', () => {
    render(<Botao>Ok</Botao>)
    expect(screen.getByRole('button', { name: 'Ok' })).toHaveAttribute('type', 'button')
  })

  it('aplica variante e tamanho como classes, nunca como `style` (CSP)', () => {
    render(
      <Botao type="submit" variante="contorno" tamanho="pequeno">
        Sair
      </Botao>,
    )
    const botao = screen.getByRole('button', { name: 'Sair' })
    expect(botao).toHaveAttribute('type', 'submit')
    expect(botao).toHaveClass('botao', 'botao--contorno', 'botao--pequeno')
    expect(botao).not.toHaveAttribute('style')
  })
})
