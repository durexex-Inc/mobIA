import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { GaleriaDoImovel } from './GaleriaDoImovel'

const FOTOS = ['/f/1', '/f/2', '/f/3']

describe('GaleriaDoImovel', () => {
  it('abre na primeira foto, com o contador', () => {
    render(<GaleriaDoImovel fotos={FOTOS} titulo="Casa" />)

    expect(screen.getByRole('img', { name: 'Foto de Casa' })).toHaveAttribute('src', '/f/1')
    expect(screen.getByText('1 / 3 fotos')).toBeInTheDocument()
  })

  it('a miniatura troca a foto grande e o contador', () => {
    render(<GaleriaDoImovel fotos={FOTOS} titulo="Casa" />)

    fireEvent.click(screen.getByRole('button', { name: 'Ver foto 3 de 3' }))

    expect(screen.getByRole('img', { name: 'Foto de Casa' })).toHaveAttribute('src', '/f/3')
    expect(screen.getByText('3 / 3 fotos')).toBeInTheDocument()
  })

  it('o ultimo ladrilho do mosaico abre a ampliacao, que percorre todas as fotos', () => {
    render(<GaleriaDoImovel fotos={FOTOS} titulo="Casa" />)

    fireEvent.click(screen.getByRole('button', { name: 'Ver as 3 fotos' }))

    const ampliacao = screen.getByRole('dialog', { name: 'Fotos de Casa' })
    expect(within(ampliacao).getByRole('img')).toHaveAttribute('src', '/f/3')
    fireEvent.click(within(ampliacao).getByRole('button', { name: 'Próxima foto' }))
    expect(within(ampliacao).getByRole('img')).toHaveAttribute('src', '/f/1')
    fireEvent.keyDown(ampliacao, { key: 'ArrowLeft' })
    expect(within(ampliacao).getByRole('img')).toHaveAttribute('src', '/f/3')
  })

  it('Esc fecha a ampliacao', () => {
    render(<GaleriaDoImovel fotos={FOTOS} titulo="Casa" />)
    fireEvent.click(screen.getByRole('button', { name: 'Ampliar foto 1 de 3' }))

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })

    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('com uma foto so, nao ha miniaturas', () => {
    render(<GaleriaDoImovel fotos={['/f/1']} titulo="Casa" />)

    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByText('1 / 1 foto')).toBeInTheDocument()
  })
})
