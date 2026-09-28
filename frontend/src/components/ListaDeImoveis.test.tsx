import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Imovel } from '@/lib/imoveis'
import { ListaDeImoveis } from './ListaDeImoveis'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

function imovel(sobrescreve: Partial<Imovel> = {}): Imovel {
  return {
    id: 'i-1',
    codigo: 'AP-001',
    titulo: 'Apartamento no Centro',
    descricao: 'Dois quartos',
    tipo: 'APARTAMENTO',
    operacao: 'VENDA',
    status: 'DISPONIVEL',
    precoVenda: 35_000_000,
    precoAluguel: null,
    condominio: null,
    iptuMensal: null,
    bairro: 'Centro',
    cidade: 'Porto Alegre',
    uf: 'RS',
    zona: null,
    latitude: null,
    longitude: null,
    areaUtilM2: 70,
    quartos: 2,
    suites: 1,
    banheiros: 2,
    vagas: 1,
    caracteristicas: [],
    fotos: [],
    atualizadoEm: '2026-09-28T12:00:00Z',
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

describe('ListaDeImoveis (D6 do desenho)', () => {
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

  it('imovel retirado mostra o status "Inativo" por texto (cenario 3 do Gherkin)', () => {
    render(
      <ListaDeImoveis imoveis={[imovel({ codigo: 'AP-002', titulo: 'Casa retirada', status: 'INATIVO' })]} />,
    )

    const linha = linhaDe('Casa retirada')
    expect(within(linha).getByText('Inativo')).toBeInTheDocument()
  })

  it('imovel disponivel mostra o status "Disponível"', () => {
    render(<ListaDeImoveis imoveis={[imovel({ titulo: 'Apartamento disponível' })]} />)

    const linha = linhaDe('Apartamento disponível')
    expect(within(linha).getByText('Disponível')).toBeInTheDocument()
  })

  it('retirar so aparece na linha de imovel que nao esta INATIVO (D4: nao ha reativar)', () => {
    render(
      <ListaDeImoveis
        imoveis={[
          imovel({ id: 'i-disponivel', titulo: 'Disponível aqui', status: 'DISPONIVEL' }),
          imovel({ id: 'i-inativo', titulo: 'Retirado aqui', status: 'INATIVO' }),
        ]}
      />,
    )

    expect(
      within(linhaDe('Disponível aqui')).getByRole('button', { name: 'Retirar das buscas' }),
    ).toBeInTheDocument()
    expect(
      within(linhaDe('Retirado aqui')).queryByRole('button', { name: 'Retirar das buscas' }),
    ).toBeNull()
    // E nao ha controle de "Reativar" em lugar nenhum da tela.
    expect(screen.queryByRole('button', { name: /reativar/i })).toBeNull()
  })

  it('cada linha oferece editar, mesmo a retirada -- reativar e editar o Status', () => {
    render(<ListaDeImoveis imoveis={[imovel({ status: 'INATIVO', titulo: 'Retirado' })]} />)

    expect(within(linhaDe('Retirado')).getByRole('button', { name: 'Editar' })).toBeInTheDocument()
  })
})
