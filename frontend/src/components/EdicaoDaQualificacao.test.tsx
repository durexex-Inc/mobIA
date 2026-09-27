import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { haAlteracaoNaoSalva } from '@/lib/inatividade'
import { EdicaoDaQualificacao } from './EdicaoDaQualificacao'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const FICHA = {
  regiao: 'centro',
  tipoImovel: 'APARTAMENTO',
  quartos: 2,
  faixaPrecoMinCentavos: null,
  faixaPrecoMaxCentavos: 50_000_000,
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

describe('EdicaoDaQualificacao', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ alterados: ['regiao'], scoreAnterior: 47, scoreAtual: 62, temperatura: 'MORNO' }))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: corrigir a regiao e ver o novo score', () => {
    it('manda so a regiao pelo proxy, mostra 47 → 62 e recarrega do servidor', async () => {
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')
      digitar('Região', 'Campeche')
      await clicar('Salvar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/leads/l-1/qualificacao',
        expect.objectContaining({ method: 'PATCH', body: '{"regiao":"Campeche"}' }),
      )
      expect(screen.getByRole('status')).toHaveTextContent('Score 47 → 62')
      expect(refresh).toHaveBeenCalledOnce()
      expect(screen.queryByRole('button', { name: 'Salvar' })).toBeNull()
    })

    it('lead nunca pontuado mostra travessao no anterior', async () => {
      api.mockResolvedValueOnce(responde({ alterados: ['quartos'], scoreAnterior: null, scoreAtual: 20 }))
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={null} encerrada={false} />)

      await clicar('Editar qualificação')
      digitar('Quartos', '3')
      await clicar('Salvar')

      expect(api.mock.calls[0][1]?.body).toBe('{"quartos":3}')
      expect(screen.getByRole('status')).toHaveTextContent('Score — → 20')
    })

    it('sem mudanca, fecha sem chamar a API', async () => {
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')
      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Editar qualificação' })).toBeInTheDocument()
    })
  })

  describe('cenario: campo de vocabulario fechado nao aceita texto livre', () => {
    it('o tipo de imovel e uma lista com os valores do backend', async () => {
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')

      const lista = screen.getByLabelText('Tipo de imóvel')
      expect(lista.tagName).toBe('SELECT')
      const valores = Array.from((lista as HTMLSelectElement).options).map((o) => o.value)
      expect(valores).toEqual(['', 'APARTAMENTO', 'CASA', 'TERRENO', 'COMERCIAL', 'RURAL'])
      expect(screen.getByLabelText('Urgência').tagName).toBe('SELECT')
      expect(screen.getByLabelText('Forma de pagamento').tagName).toBe('SELECT')
    })
  })

  describe('cenario: recusa de validacao do backend', () => {
    it('a mensagem aparece ao lado do campo, o score nao muda e o formulario fica', async () => {
      api.mockResolvedValueOnce(
        responde(
          { detail: [{ type: 'less_than_equal', loc: ['body', 'quartos'], msg: 'x', ctx: { le: 50 } }] },
          422,
        ),
      )
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')
      digitar('Quartos', '99')
      await clicar('Salvar')

      const campo = screen.getByLabelText('Quartos')
      expect(campo).toHaveAttribute('aria-invalid', 'true')
      expect(campo).toHaveAccessibleDescription('Deve ser no máximo 50.')
      expect(campo).toHaveValue(99)
      expect(screen.queryByRole('status')).toBeNull()
      expect(refresh).not.toHaveBeenCalled()
    })

    it('`faixa_invertida` aparece na faixa de preco', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'faixa_invertida' }, 422))
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')
      digitar('Preço mínimo (R$)', '900000')
      await clicar('Salvar')

      expect(screen.getByLabelText('Preço mínimo (R$)')).toHaveAccessibleDescription(
        'O valor mínimo não pode passar do máximo.',
      )
    })

    it('409 de conversa encerrada vai para o topo', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'conversa_encerrada' }, 409))
      render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />)

      await clicar('Editar qualificação')
      digitar('Região', 'sul')
      await clicar('Salvar')

      expect(screen.getByRole('alert')).toHaveTextContent('A conversa foi encerrada')
    })
  })

  it('conversa encerrada nao oferece editar', () => {
    render(<EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada />)

    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByText(/não pode mais ser editada/)).toBeInTheDocument()
  })

  describe('alteracao nao salva (TEC-311)', () => {
    it('sujo registra; cancelar e desmontar desfazem', async () => {
      const { unmount } = render(
        <EdicaoDaQualificacao leadId="l-1" qualificacao={FICHA} encerrada={false} />,
      )
      await clicar('Editar qualificação')
      expect(haAlteracaoNaoSalva()).toBe(false)

      await act(async () => digitar('Região', 'sul'))
      expect(haAlteracaoNaoSalva()).toBe(true)

      await clicar('Cancelar')
      expect(haAlteracaoNaoSalva()).toBe(false)

      await clicar('Editar qualificação')
      await act(async () => digitar('Região', 'norte'))
      expect(haAlteracaoNaoSalva()).toBe(true)
      unmount()
      expect(haAlteracaoNaoSalva()).toBe(false)
    })
  })
})
