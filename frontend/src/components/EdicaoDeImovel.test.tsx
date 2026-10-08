import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Imovel } from '@/lib/imoveis'
import { haAlteracaoNaoSalva } from '@/lib/inatividade'
import { EdicaoDeImovel } from './EdicaoDeImovel'

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

describe('EdicaoDeImovel (TEC-400)', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ ...IMOVEL, reindexa: false }))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('abre com os dados do imovel, e o codigo desabilitado (D5 da TEC-333)', () => {
    render(<EdicaoDeImovel imovel={IMOVEL} />)

    expect(screen.getByRole('heading', { name: 'Editar imóvel' })).toBeInTheDocument()
    expect(screen.getByLabelText('Título do anúncio')).toHaveValue('Apartamento no Centro')
    expect(screen.getByLabelText('Código')).toBeDisabled()
  })

  describe('alterar so o preco nao reindexa (D3, cenario 1 do Gherkin da TEC-333)', () => {
    it('manda so o preco e mostra "nao reindexa"', async () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      digitar('Preço de venda', '400000')
      await clicar('Salvar alterações')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/imoveis/i-1',
        expect.objectContaining({ method: 'PATCH', body: '{"precoVenda":40000000}' }),
      )
      expect(screen.getByRole('status')).toHaveTextContent('não é necessário reindexar')
      expect(refresh).toHaveBeenCalledOnce()
    })
  })

  describe('alterar o diferencial reindexa (D3, cenario 2 do Gherkin da TEC-333)', () => {
    it('manda so as caracteristicas e mostra "reindexa"', async () => {
      api.mockResolvedValueOnce(responde({ ...IMOVEL, caracteristicas: ['Vista para o mar'], reindexa: true }))
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      await clicar('Remover Vista para o parque')
      digitar('Diferenciais', 'Vista para o mar')
      await clicar('Adicionar diferencial')
      await clicar('Salvar alterações')

      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ caracteristicas: ['Vista para o mar'] })
      expect(screen.getByRole('status')).toHaveTextContent('será reindexado')
    })
  })

  it('sem mudanca, "Salvar alterações" nao chama a API', async () => {
    render(<EdicaoDeImovel imovel={IMOVEL} />)

    await clicar('Salvar alterações')

    expect(api).not.toHaveBeenCalled()
  })

  it('o erro do backend aparece inteiro, como um aviso so (D2 da TEC-333)', async () => {
    api.mockResolvedValueOnce(responde({ detail: 'titulo ausente; bairro ausente' }, 422))
    render(<EdicaoDeImovel imovel={IMOVEL} />)

    digitar('Preço de venda', '400000')
    await clicar('Salvar alterações')

    expect(screen.getByRole('alert')).toHaveTextContent('titulo ausente; bairro ausente')
    expect(refresh).not.toHaveBeenCalled()
  })

  describe('finalidade: as alternancias viram a `operacao`', () => {
    it('ligar Aluguel num imovel de venda vira AMBOS e mostra o preco do aluguel', async () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      expect(screen.getByRole('button', { name: 'Venda' })).toHaveAttribute('aria-pressed', 'true')
      await clicar('Aluguel')

      expect(screen.getByRole('button', { name: 'Aluguel' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByLabelText('Preço do aluguel (mensal)')).toBeInTheDocument()
      digitar('Preço do aluguel (mensal)', '3000')
      await clicar('Salvar alterações')

      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ operacao: 'AMBOS', precoAluguel: 300_000 })
    })

    it('desligar a unica finalidade e recusado na tela, sem chamar a API', async () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      await clicar('Venda')
      await clicar('Salvar alterações')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByText('Escolha a operação.')).toBeInTheDocument()
    })
  })

  it('o IPTU vai em centavos, e o total mensal soma aluguel, condominio e IPTU', async () => {
    render(<EdicaoDeImovel imovel={{ ...IMOVEL, operacao: 'ALUGUEL', precoVenda: null, precoAluguel: 450_000 }} />)

    digitar('IPTU mensal', '150')

    expect(screen.getByText('Custo mensal estimado').nextSibling).toHaveTextContent('R$ 5.500,00')
    await clicar('Salvar alterações')
    const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
    expect(corpo).toEqual({ iptuMensal: 15_000 })
  })

  describe('"Ver no portal" (TEC-400)', () => {
    it('aponta para a pagina publica quando o imovel salvo esta disponivel', () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      expect(screen.getByRole('link', { name: 'Ver no portal' })).toHaveAttribute('href', '/busca/i-1')
    })

    it('nao aparece com outro status: o portal so mostra imovel disponivel', () => {
      render(<EdicaoDeImovel imovel={{ ...IMOVEL, status: 'RESERVADO' }} />)

      expect(screen.queryByRole('link', { name: 'Ver no portal' })).toBeNull()
    })
  })

  describe('pre-visualizar card (TEC-336, D2)', () => {
    it('comeca habilitado num imovel ja valido', () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      expect(screen.getByRole('button', { name: 'Pré-visualizar card' })).toBeEnabled()
    })

    it('desabilita quando um campo obrigatorio fica vazio', () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)

      digitar('Título do anúncio', '')

      expect(screen.getByRole('button', { name: 'Pré-visualizar card' })).toBeDisabled()
    })
  })

  describe('alteracao nao salva (TEC-311)', () => {
    it('sujo registra; "Descartar" desfaz', async () => {
      render(<EdicaoDeImovel imovel={IMOVEL} />)
      expect(haAlteracaoNaoSalva()).toBe(false)

      await act(async () => digitar('Título do anúncio', 'Outro título'))
      expect(haAlteracaoNaoSalva()).toBe(true)

      await clicar('Descartar')
      expect(haAlteracaoNaoSalva()).toBe(false)
      expect(screen.getByLabelText('Título do anúncio')).toHaveValue('Apartamento no Centro')
    })
  })
})
