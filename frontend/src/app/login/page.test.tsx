import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import PaginaDeLogin from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const cookiesDaRequisicao = new Map<string, string>()
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (nome: string) =>
      cookiesDaRequisicao.has(nome) ? { value: cookiesDaRequisicao.get(nome) } : undefined,
  }),
}))

// `redirect` do Next lanca para interromper o render; o duble lanca tambem, e
// o teste le o destino da mensagem.
vi.mock('next/navigation', () => ({
  redirect: (destino: string) => {
    throw new Error(`REDIRECT:${destino}`)
  },
}))

function renderizar(busca: Record<string, string>) {
  return PaginaDeLogin({ searchParams: Promise.resolve(busca) }).then(render)
}

function campoEscondido(nome: string): string | null {
  return document.querySelector<HTMLInputElement>(`input[type=hidden][name=${nome}]`)?.value ?? null
}

describe('PaginaDeLogin', () => {
  beforeEach(() => {
    cookiesDaRequisicao.clear()
    limparArmazem()
  })

  it('pede e-mail e senha, e manda para `/login/entrar`', async () => {
    await renderizar({})

    expect(screen.getByLabelText('E-mail')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Senha')).toHaveAttribute('type', 'password')
    const formulario = screen.getByRole('button', { name: 'Entrar' }).closest('form')
    expect(formulario).toHaveAttribute('method', 'post')
    expect(formulario).toHaveAttribute('action', '/login/entrar')
  })

  it('leva o destino adiante no campo escondido', async () => {
    await renderizar({ returnTo: '/leads?q=ana' })

    expect(campoEscondido('returnTo')).toBe('/leads?q=ana')
  })

  it('filtra o destino externo ANTES de o por no formulario', async () => {
    await renderizar({ returnTo: 'https://site-externo.com' })

    expect(campoEscondido('returnTo')).toBe('/')
  })

  it('na etapa do codigo, pede os 6 digitos e manda para `/login/mfa`', async () => {
    await renderizar({ etapa: 'mfa', returnTo: '/leads' })

    const codigo = screen.getByLabelText('Código')
    expect(codigo).toHaveAttribute('autocomplete', 'one-time-code')
    expect(codigo).toHaveAttribute('pattern', '[0-9]{6}')
    expect(screen.getByRole('button', { name: 'Confirmar' }).closest('form')).toHaveAttribute(
      'action',
      '/login/mfa',
    )
    expect(screen.queryByLabelText('Senha')).not.toBeInTheDocument()
  })

  it('cenario: a mensagem explica que administradores precisam de MFA', async () => {
    await renderizar({ erro: 'mfa_obrigatorio' })

    expect(screen.getByRole('alert')).toHaveTextContent(
      /Administradores só entram com a verificação em duas etapas configurada/,
    )
  })

  it('credencial errada tem uma mensagem so, sem dizer qual dos dois errou', async () => {
    await renderizar({ erro: 'credencial' })

    expect(screen.getByRole('alert')).toHaveTextContent('E-mail ou senha incorretos.')
  })

  it('motivo desconhecido nao mostra alerta nenhum', async () => {
    await renderizar({ erro: '<script>alert(1)</script>' })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('quem ja tem sessao valida vai direto ao destino', async () => {
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))

    await expect(renderizar({ returnTo: '/leads' })).rejects.toThrow('REDIRECT:/leads')
  })

  it('cookie de sessao que o Redis nao conhece nao pula o login', async () => {
    cookiesDaRequisicao.set('mobia_sessao', 'c'.repeat(43))

    await renderizar({})

    expect(screen.getByLabelText('E-mail')).toBeInTheDocument()
  })
})
