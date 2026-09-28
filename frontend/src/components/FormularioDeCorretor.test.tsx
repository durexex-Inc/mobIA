import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Corretor } from '@/lib/corretores'
import { haAlteracaoNaoSalva } from '@/lib/inatividade'
import { FormularioDeCorretor } from './FormularioDeCorretor'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const CORRETOR: Corretor = {
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

async function marcar(rotulo: string) {
  await act(async () => {
    fireEvent.click(screen.getByLabelText(rotulo))
  })
}

describe('FormularioDeCorretor', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ ...CORRETOR, id: 'c-novo' }, 201))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: cadastrar corretor valido', () => {
    it('manda o POST completo pelo proxy, sem `gerente` (D4)', async () => {
      render(<FormularioDeCorretor corretor={null} />)

      await clicar('Cadastrar corretor')
      digitar('Nome', 'Bruno Lima')
      digitar('E-mail', 'bruno@imobiliaria.com')
      digitar('Telefone', '11988887777')
      await marcar('Compra')
      digitar('Regiões de atuação', 'Centro')
      await clicar('Adicionar região')
      digitar('Início do atendimento', '8')
      digitar('Fim do atendimento', '18')
      digitar('Capacidade diária', '5')
      await clicar('Cadastrar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/corretores',
        expect.objectContaining({ method: 'POST' }),
      )
      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({
        nome: 'Bruno Lima',
        email: 'bruno@imobiliaria.com',
        telefone: '11988887777',
        creci: null,
        especialidades: ['COMPRA'],
        regioesAtuacao: ['Centro'],
        horarioInicio: 8,
        horarioFim: 18,
        capacidadeDiaria: 5,
        plantao: false,
      })
      expect(corpo).not.toHaveProperty('gerente')
      expect(refresh).toHaveBeenCalledOnce()
      expect(screen.queryByRole('button', { name: 'Cadastrar' })).toBeNull()
    })
  })

  describe('cenario: capacidade fora da faixa (D3)', () => {
    it('capacidade 21 e recusada na tela, sem chamar a API', async () => {
      render(<FormularioDeCorretor corretor={null} />)

      await clicar('Cadastrar corretor')
      digitar('Nome', 'Bruno Lima')
      digitar('E-mail', 'bruno@imobiliaria.com')
      digitar('Telefone', '11988887777')
      await marcar('Compra')
      digitar('Regiões de atuação', 'Centro')
      await clicar('Adicionar região')
      digitar('Início do atendimento', '8')
      digitar('Fim do atendimento', '18')
      digitar('Capacidade diária', '21')
      await clicar('Cadastrar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByLabelText('Capacidade diária')).toHaveAccessibleDescription(
        /entre 1 e 20/,
      )
    })

    it('capacidade 0 tambem e recusada', async () => {
      render(<FormularioDeCorretor corretor={null} />)

      await clicar('Cadastrar corretor')
      digitar('Nome', 'Bruno Lima')
      digitar('E-mail', 'bruno@imobiliaria.com')
      digitar('Telefone', '11988887777')
      await marcar('Compra')
      digitar('Regiões de atuação', 'Centro')
      await clicar('Adicionar região')
      digitar('Início do atendimento', '8')
      digitar('Fim do atendimento', '18')
      digitar('Capacidade diária', '0')
      await clicar('Cadastrar')

      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('cenario: editar so o que mudou', () => {
    it('manda o PATCH parcial pelo proxy do id', async () => {
      render(<FormularioDeCorretor corretor={CORRETOR} />)

      await clicar('Editar')
      digitar('Capacidade diária', '10')
      await clicar('Salvar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/corretores/c-1',
        expect.objectContaining({ method: 'PATCH', body: '{"capacidadeDiaria":10}' }),
      )
      expect(refresh).toHaveBeenCalledOnce()
    })

    it('sem mudanca, fecha sem chamar a API', async () => {
      render(<FormularioDeCorretor corretor={CORRETOR} />)

      await clicar('Editar')
      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Editar' })).toBeInTheDocument()
    })
  })

  describe('cenario: 409 de e-mail duplicado (D9)', () => {
    it('a mensagem aparece ao lado do campo e-mail, nao no topo', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'e-mail ja cadastrado' }, 409))
      render(<FormularioDeCorretor corretor={CORRETOR} />)

      await clicar('Editar')
      digitar('E-mail', 'outro@imobiliaria.com')
      await clicar('Salvar')

      expect(screen.getByLabelText('E-mail')).toHaveAccessibleDescription(
        'Este e-mail já está cadastrado.',
      )
      expect(screen.queryByRole('alert')).toBeNull()
      expect(refresh).not.toHaveBeenCalled()
    })
  })

  describe('remover regiao', () => {
    it('remove a regiao da lista antes de salvar', async () => {
      render(<FormularioDeCorretor corretor={CORRETOR} />)

      await clicar('Editar')
      expect(screen.getByText('Centro')).toBeInTheDocument()

      await clicar('Remover Centro')

      expect(screen.queryByText('Centro')).toBeNull()
    })
  })

  describe('alteracao nao salva (TEC-311)', () => {
    it('sujo registra; cancelar desfaz', async () => {
      render(<FormularioDeCorretor corretor={CORRETOR} />)
      await clicar('Editar')
      expect(haAlteracaoNaoSalva()).toBe(false)

      await act(async () => digitar('Nome', 'Outro nome'))
      expect(haAlteracaoNaoSalva()).toBe(true)

      await clicar('Cancelar')
      expect(haAlteracaoNaoSalva()).toBe(false)
    })
  })
})
