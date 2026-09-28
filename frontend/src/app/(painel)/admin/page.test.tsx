import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import PaginaDeAdministracao from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const cookiesDaRequisicao = new Map<string, string>()
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (nome: string) =>
      cookiesDaRequisicao.has(nome) ? { value: cookiesDaRequisicao.get(nome) } : undefined,
  }),
}))

vi.mock('next/navigation', () => ({
  redirect: (destino: string) => {
    throw new Error(`REDIRECT:${destino}`)
  },
}))

const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['CONFIGURAR_AGENTE', 'GERIR_CATALOGO', 'GERIR_CORRETORES', 'OPERAR_FILA', 'VER_AUDITORIA', 'VER_FUNIL'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

/** Todo `fetch` que a pagina fizer, para o teste afirmar que so `/auth/me` saiu. */
function apiComPapel(papel: string) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(
    async () =>
      new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      ),
  )
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('PaginaDeAdministracao', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ADMIN ve o indice das secoes, marcadas como ainda nao disponiveis', async () => {
    apiComPapel('ADMIN')

    render(await PaginaDeAdministracao())

    expect(screen.getByRole('heading', { name: 'Administração' })).toBeInTheDocument()
    expect(screen.getByText('Prompts do agente')).toBeInTheDocument()
    expect(screen.getAllByText('ainda não disponível')).toHaveLength(5)
    // A primeira secao com tela (TEC-340).
    expect(screen.getByRole('link', { name: 'Pedidos do titular' })).toHaveAttribute('href', '/admin/titular')
  })

  describe('cenario: corretor acessa a area administrativa pela URL', () => {
    it('ve "Sem permissao" com o nome do seu papel e o link para o inicio', async () => {
      apiComPapel('CORRETOR')

      render(await PaginaDeAdministracao())

      expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
      expect(screen.getByRole('alert')).toHaveTextContent('Você entrou como Corretor')
      // O inicio do CORRETOR e a lista de leads desde a TEC-321 (D2).
      expect(screen.getByRole('link', { name: 'Ir para a página inicial' })).toHaveAttribute(
        'href',
        '/leads',
      )
      expect(screen.queryByText('Prompts do agente')).not.toBeInTheDocument()
    })

    it('e nenhum dado administrativo e pedido: a unica chamada e `/auth/me`', async () => {
      const chamadas = apiComPapel('CORRETOR')

      await PaginaDeAdministracao()

      expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
        '/api/v1/auth/me',
      ])
    })
  })

  it('sem sessao vai ao login, com o destino', async () => {
    cookiesDaRequisicao.clear()
    apiComPapel('ADMIN')

    await expect(PaginaDeAdministracao()).rejects.toThrow('REDIRECT:/login?returnTo=%2Fadmin')
  })
})
