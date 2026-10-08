import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Imovel } from '@/lib/imoveis'
import { FormularioDeImovel } from './FormularioDeImovel'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const IMOVEL: Imovel = {
  id: 'i-1',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos, reformado',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  status: 'DISPONIVEL',
  precoVenda: 35_000_000,
  precoAluguel: null,
  condominio: 85_000,
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
  caracteristicas: ['Vista para o parque'],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json' } })
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

function digitar(rotulo: string, valor: string) {
  fireEvent.change(screen.getByLabelText(rotulo), { target: { value: valor } })
}

async function preencherCadastroValido() {
  digitar('Código', 'AP-002')
  digitar('Título', 'Casa no bairro Bela Vista')
  digitar('Descrição', 'Casa térrea com quintal')
  digitar('Tipo', 'CASA')
  digitar('Operação', 'VENDA')
  digitar('Status', 'DISPONIVEL')
  digitar('Preço de venda (R$)', '500000')
  digitar('Bairro', 'Bela Vista')
  digitar('Cidade', 'Porto Alegre')
  digitar('UF', 'RS')
  digitar('Área útil (m²)', '120')
  digitar('Quartos', '3')
  digitar('Suítes', '1')
  digitar('Banheiros', '2')
  digitar('Vagas', '2')
}

describe('FormularioDeImovel', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ ...IMOVEL, id: 'i-novo' }, 201))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: cadastrar imovel valido, com todos os obrigatorios (D1)', () => {
    it('manda o POST completo pelo proxy e volta o formulario vazio', async () => {
      render(<FormularioDeImovel />)

      await preencherCadastroValido()
      await clicar('Cadastrar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis',
        expect.objectContaining({ method: 'POST' }),
      )
      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({
        codigo: 'AP-002',
        titulo: 'Casa no bairro Bela Vista',
        descricao: 'Casa térrea com quintal',
        tipo: 'CASA',
        operacao: 'VENDA',
        status: 'DISPONIVEL',
        precoVenda: 50_000_000,
        precoAluguel: null,
        condominio: null,
        iptuMensal: null,
        bairro: 'Bela Vista',
        cidade: 'Porto Alegre',
        uf: 'RS',
        areaUtilM2: 120,
        quartos: 3,
        suites: 1,
        banheiros: 2,
        vagas: 2,
        caracteristicas: [],
      })
      expect(refresh).toHaveBeenCalledOnce()
      // O cadastro fica de pe e volta vazio (D1 da TEC-398).
      expect(screen.getByRole('button', { name: 'Cadastrar' })).toBeInTheDocument()
      expect(screen.getByLabelText('Código')).toHaveValue('')
    })
  })

  describe('cenario: campo obrigatorio vazio (D1, D2)', () => {
    it('sem titulo, a tela recusa antes do fetch', async () => {
      render(<FormularioDeImovel />)

      await preencherCadastroValido()
      digitar('Título', '')
      await clicar('Cadastrar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByLabelText('Título')).toHaveAccessibleDescription(/título/)
    })
  })

  describe('cenario: operacao decide o campo de preco (D1)', () => {
    it('Aluguel mostra so o preco de aluguel', async () => {
      render(<FormularioDeImovel />)
          digitar('Operação', 'ALUGUEL')

      expect(screen.queryByLabelText('Preço de venda (R$)')).toBeNull()
      expect(screen.getByLabelText('Preço de aluguel (R$)')).toBeInTheDocument()
    })

    it('Ambos mostra os dois precos', async () => {
      render(<FormularioDeImovel />)
          digitar('Operação', 'AMBOS')

      expect(screen.getByLabelText('Preço de venda (R$)')).toBeInTheDocument()
      expect(screen.getByLabelText('Preço de aluguel (R$)')).toBeInTheDocument()
    })
  })

  describe('o cadastro sempre aberto (TEC-398, D1)', () => {
    it('o cadastro aparece sem clique, no cartao "Cadastrar novo imóvel"', () => {
      render(<FormularioDeImovel />)

      expect(screen.getByRole('region', { name: 'Cadastrar novo imóvel' })).toBeInTheDocument()
      expect(screen.getByRole('textbox', { name: 'Código' })).toHaveAttribute('aria-required', 'true')
      expect(screen.getByRole('textbox', { name: 'Condomínio (R$)' })).not.toHaveAttribute('aria-required')
    })

    it('"Cancelar" no cadastro limpa o que foi digitado, sem chamar a API', async () => {
      render(<FormularioDeImovel />)

      digitar('Título', 'Casa no bairro Bela Vista')
      await clicar('Cancelar')

      expect(screen.getByLabelText('Título')).toHaveValue('')
      expect(api).not.toHaveBeenCalled()
    })
  })
})
