import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Corretor } from '@/lib/corretores'
import { ListaDeCorretores } from './ListaDeCorretores'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

function corretor(sobrescreve: Partial<Corretor> = {}): Corretor {
  return {
    id: 'c-1',
    nome: 'Ana Souza',
    email: 'ana@imobiliaria.com',
    telefone: '11999998888',
    creci: null,
    especialidades: ['COMPRA'],
    regioesAtuacao: ['Centro'],
    horarioInicio: 8,
    horarioFim: 18,
    capacidadeDiaria: 5,
    plantao: false,
    gerente: false,
    ativo: true,
    ...sobrescreve,
  }
}

function linhaDe(texto: string) {
  const celula = screen.getByText(texto)
  const linha = celula.closest('tr')
  if (!linha) {
    throw new Error(`sem linha para ${texto}`)
  }
  return linha
}

describe('ListaDeCorretores (D6 do desenho)', () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open')
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('corretor inativo mostra o rotulo de texto "Inativo"', () => {
    render(<ListaDeCorretores corretores={[corretor({ nome: 'Bia Alves', ativo: false })]} />)

    const linha = linhaDe('Bia Alves')
    expect(within(linha).getByText('Inativo')).toBeInTheDocument()
  })

  it('corretor ativo nao mostra "Inativo"', () => {
    render(<ListaDeCorretores corretores={[corretor({ nome: 'Ana Souza' })]} />)

    expect(screen.queryByText('Inativo')).toBeNull()
  })

  it('plantonista mostra o rotulo "Generalista de plantão"', () => {
    render(<ListaDeCorretores corretores={[corretor({ nome: 'Caio Reis', plantao: true })]} />)

    const linha = linhaDe('Caio Reis')
    expect(within(linha).getByText('Generalista de plantão')).toBeInTheDocument()
  })

  it('desativar so aparece na linha de corretor ativo (D5: nao ha reativar)', () => {
    render(
      <ListaDeCorretores
        corretores={[
          corretor({ id: 'c-ativo', nome: 'Ana Souza', ativo: true }),
          corretor({ id: 'c-inativo', nome: 'Bia Alves', ativo: false }),
        ]}
      />,
    )

    expect(within(linhaDe('Ana Souza')).getByRole('button', { name: 'Desativar' })).toBeInTheDocument()
    expect(within(linhaDe('Bia Alves')).queryByRole('button', { name: 'Desativar' })).toBeNull()
    // E nao ha controle de "Reativar" em lugar nenhum da tela.
    expect(screen.queryByRole('button', { name: /reativar/i })).toBeNull()
  })

  it('cada linha oferece editar', () => {
    render(<ListaDeCorretores corretores={[corretor({ nome: 'Ana Souza' })]} />)

    expect(within(linhaDe('Ana Souza')).getByRole('button', { name: 'Editar' })).toBeInTheDocument()
  })

  it('o cabecalho conta os ativos e o total (TEC-397, D7)', () => {
    render(
      <ListaDeCorretores
        corretores={[
          corretor({ id: 'c-1', nome: 'Ana Souza' }),
          corretor({ id: 'c-2', nome: 'Bia Alves', ativo: false }),
        ]}
      />,
    )

    expect(screen.getByRole('heading', { name: /Corretores cadastrados/ })).toHaveTextContent('1 ativo')
    expect(screen.getByText('Total: 2')).toBeInTheDocument()
  })

  it('lista vazia mostra o estado vazio, sem tabela', () => {
    render(<ListaDeCorretores corretores={[]} />)

    expect(screen.getByText('Nenhum corretor cadastrado.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByRole('heading', { name: /Corretores cadastrados/ })).toHaveTextContent('0 ativos')
  })
})
