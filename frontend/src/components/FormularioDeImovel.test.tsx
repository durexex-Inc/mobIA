import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Imovel } from '@/lib/imoveis'
import { haAlteracaoNaoSalva } from '@/lib/inatividade'
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
  await clicar('Cadastrar imóvel')
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
    it('manda o POST completo pelo proxy e fecha o formulario', async () => {
      render(<FormularioDeImovel imovel={null} />)

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
      expect(screen.queryByRole('button', { name: 'Cadastrar' })).toBeNull()
    })
  })

  describe('cenario: campo obrigatorio vazio (D1, D2)', () => {
    it('sem titulo, a tela recusa antes do fetch', async () => {
      render(<FormularioDeImovel imovel={null} />)

      await preencherCadastroValido()
      digitar('Título', '')
      await clicar('Cadastrar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByLabelText('Título')).toHaveAccessibleDescription(/título/)
    })
  })

  describe('cenario: operacao decide o campo de preco (D1)', () => {
    it('Aluguel mostra so o preco de aluguel', async () => {
      render(<FormularioDeImovel imovel={null} />)
      await clicar('Cadastrar imóvel')
      digitar('Operação', 'ALUGUEL')

      expect(screen.queryByLabelText('Preço de venda (R$)')).toBeNull()
      expect(screen.getByLabelText('Preço de aluguel (R$)')).toBeInTheDocument()
    })

    it('Ambos mostra os dois precos', async () => {
      render(<FormularioDeImovel imovel={null} />)
      await clicar('Cadastrar imóvel')
      digitar('Operação', 'AMBOS')

      expect(screen.getByLabelText('Preço de venda (R$)')).toBeInTheDocument()
      expect(screen.getByLabelText('Preço de aluguel (R$)')).toBeInTheDocument()
    })
  })

  describe('cenario: codigo desabilitado na edicao (D5)', () => {
    it('o campo codigo esta desabilitado quando ha imovel', async () => {
      render(<FormularioDeImovel imovel={IMOVEL} />)
      await clicar('Editar')

      expect(screen.getByLabelText('Código')).toBeDisabled()
    })
  })

  describe('cenario: alterar so o preco nao reindexa (D3, cenario 1 do Gherkin)', () => {
    it('mostra a mensagem de "nao reindexa" apos o PATCH', async () => {
      api.mockResolvedValueOnce(responde({ ...IMOVEL, precoVenda: 40_000_000, reindexa: false }))
      render(<FormularioDeImovel imovel={IMOVEL} />)

      await clicar('Editar')
      digitar('Preço de venda (R$)', '400000')
      await clicar('Salvar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/i-1',
        expect.objectContaining({ method: 'PATCH', body: '{"precoVenda":40000000}' }),
      )
      expect(screen.getByRole('status')).toHaveTextContent('não é necessário reindexar')
      expect(refresh).toHaveBeenCalledOnce()
    })
  })

  describe('cenario: alterar o diferencial reindexa (D3, cenario 2 do Gherkin)', () => {
    it('mostra a mensagem de "reindexa" apos o PATCH', async () => {
      api.mockResolvedValueOnce(
        responde({ ...IMOVEL, caracteristicas: ['Vista para o mar'], reindexa: true }),
      )
      render(<FormularioDeImovel imovel={IMOVEL} />)

      await clicar('Editar')
      await clicar('Remover Vista para o parque')
      digitar('Diferenciais', 'Vista para o mar')
      await clicar('Adicionar diferencial')
      await clicar('Salvar')

      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ caracteristicas: ['Vista para o mar'] })
      expect(screen.getByRole('status')).toHaveTextContent('será reindexado')
    })
  })

  describe('cenario: sem mudanca, fecha sem chamar a API', () => {
    it('editar e salvar sem alterar nada nao chama o fetch', async () => {
      render(<FormularioDeImovel imovel={IMOVEL} />)

      await clicar('Editar')
      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Editar' })).toBeInTheDocument()
    })
  })

  describe('cenario: erro do backend e uma string unica, mostrada inteira (D2)', () => {
    it('422 com "titulo ausente; bairro ausente" aparece como um aviso geral so', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'titulo ausente; bairro ausente' }, 422))
      render(<FormularioDeImovel imovel={IMOVEL} />)

      await clicar('Editar')
      digitar('Preço de venda (R$)', '400000')
      await clicar('Salvar')

      expect(screen.getByRole('alert')).toHaveTextContent('titulo ausente; bairro ausente')
      expect(refresh).not.toHaveBeenCalled()
    })
  })

  describe('pre-visualizar card (TEC-336, D2)', () => {
    it('nao existe no cadastro -- so ha imovel salvo na edicao', async () => {
      render(<FormularioDeImovel imovel={null} />)
      await clicar('Cadastrar imóvel')

      expect(screen.queryByRole('button', { name: 'Pré-visualizar card' })).toBeNull()
    })

    it('comeca habilitado na edicao de um imovel ja valido', async () => {
      render(<FormularioDeImovel imovel={IMOVEL} />)
      await clicar('Editar')

      expect(screen.getByRole('button', { name: 'Pré-visualizar card' })).toBeEnabled()
    })

    it('desabilita quando um campo obrigatorio fica vazio', async () => {
      render(<FormularioDeImovel imovel={IMOVEL} />)
      await clicar('Editar')

      digitar('Título', '')

      expect(screen.getByRole('button', { name: 'Pré-visualizar card' })).toBeDisabled()
    })
  })

  describe('alteracao nao salva (TEC-311)', () => {
    it('sujo registra; cancelar desfaz', async () => {
      render(<FormularioDeImovel imovel={IMOVEL} />)
      await clicar('Editar')
      expect(haAlteracaoNaoSalva()).toBe(false)

      await act(async () => digitar('Título', 'Outro título'))
      expect(haAlteracaoNaoSalva()).toBe(true)

      await clicar('Cancelar')
      expect(haAlteracaoNaoSalva()).toBe(false)
    })
  })
})
