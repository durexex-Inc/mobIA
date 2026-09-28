import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDeConfiguracao from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../../test/armazem-em-memoria')).moduloDeArmazem,
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
  // `FormularioDeConfiguracao` e Client Component e chama `useRouter` ao
  // montar, mesmo sem clicar em nada.
  useRouter: () => ({ refresh: () => {} }),
}))

const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['CONFIGURAR_AGENTE', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

const CONFIGURACAO = {
  nomeDoAssistente: 'Ana',
  tom: 'CORDIAL',
  tetoDePerguntas: 8,
  pesoCompletude: 20,
  pesoUrgencia: 25,
  pesoCatalogo: 20,
  pesoEngajamento: 15,
  pesoCapacidade: 15,
  cadencia: { QUENTE: [2, 24, 72, 168], MORNO: [24, 96, 240], FRIO: [72, 336] },
  orcamentoMensalUsd: '100.00',
  corPrimaria: '#1D4ED8',
  posicaoDoBotao: 'DIREITA',
  dominiosDoChat: [],
}

const LIMITES = {
  nomeDoAssistente: { maximoDeCaracteres: 30, nulavel: true },
  tom: { valores: ['CORDIAL', 'FORMAL', 'DESCONTRAIDO'] },
  tetoDePerguntas: { minimo: 1, maximo: 20 },
  pesos: { minimo: 0, maximo: 50, somaMaxima: 100 },
  cadencia: {
    tentativasPorTemperatura: { QUENTE: 4, MORNO: 3, FRIO: 2 },
    horaMinima: 1,
    horaMaxima: 2160,
  },
  orcamentoMensalUsd: { minimo: '0.01', maximo: '100000', nulavel: true },
  corPrimaria: {},
  posicaoDoBotao: {},
  dominiosDoChat: {},
}

/**
 * `/auth/me` com o papel, a configuracao vigente e o historico, roteados por
 * caminho -- historico sem sobrescrita devolve lista vazia (a maioria dos
 * testes desta pagina nao se importa com ele).
 */
function api(
  papel: string,
  configuracao: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> },
  historico: { corpo: unknown; status?: number } = { corpo: { itens: [] } },
) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    const caminho = new URL(String(url)).pathname
    if (caminho === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    if (caminho === '/api/v1/configuracao/agente/historico') {
      return new Response(JSON.stringify(historico.corpo), { status: historico.status ?? 200 })
    }
    return new Response(JSON.stringify(configuracao.corpo), {
      status: configuracao.status ?? 200,
      headers: configuracao.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('PaginaDeConfiguracao (TEC-337)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ADMIN ve o formulario com a configuracao vigente e o historico', async () => {
    api('ADMIN', {
      corpo: { configuracao: CONFIGURACAO, limites: LIMITES, versao: 'v-1' },
    })

    render(await PaginaDeConfiguracao())

    expect(screen.getByRole('heading', { name: 'Configuração do agente' })).toBeInTheDocument()
    expect(screen.getByLabelText('Nome do assistente')).toHaveValue('Ana')
    expect(screen.getByText('Nenhuma alteração registrada ainda.')).toBeInTheDocument()
  })

  it('mostra o historico quando ha entradas', async () => {
    api(
      'ADMIN',
      { corpo: { configuracao: CONFIGURACAO, limites: LIMITES, versao: 'v-1' } },
      {
        corpo: {
          itens: [
            {
              id: 'v-1',
              autor: 'u-admin-1',
              em: '2026-09-20T09:30:00+00:00',
              mudancas: [{ campo: 'pesoUrgencia', anterior: 25, novo: 30 }],
            },
          ],
        },
      },
    )

    render(await PaginaDeConfiguracao())

    expect(screen.getByText('u-admin-1')).toBeInTheDocument()
  })

  it('CORRETOR que acessa pela URL ve "Sem permissao", e nada alem de `/auth/me` e pedido', async () => {
    const chamadas = api('CORRETOR', {
      corpo: { configuracao: CONFIGURACAO, limites: LIMITES, versao: 'v-1' },
    })

    render(await PaginaDeConfiguracao())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/v1/auth/me',
    ])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDeConfiguracao())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco da configuracao', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDeConfiguracao()).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fconfiguracao&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga da configuracao mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDeConfiguracao())

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Não foi possível carregar a configuração do agente.',
    )
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('falha ao buscar o historico nao derruba a pagina (a configuracao e o essencial)', async () => {
    api(
      'ADMIN',
      { corpo: { configuracao: CONFIGURACAO, limites: LIMITES, versao: 'v-1' } },
      { corpo: { detail: 'boom' }, status: 500 },
    )

    render(await PaginaDeConfiguracao())

    expect(screen.getByRole('heading', { name: 'Configuração do agente' })).toBeInTheDocument()
    expect(screen.getByLabelText('Nome do assistente')).toHaveValue('Ana')
    expect(screen.getByText('Nenhuma alteração registrada ainda.')).toBeInTheDocument()
  })

  it('sem sessao vai ao login, com o destino', async () => {
    cookiesDaRequisicao.clear()
    api('ADMIN', { corpo: { configuracao: CONFIGURACAO, limites: LIMITES, versao: 'v-1' } })

    await expect(PaginaDeConfiguracao()).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fconfiguracao',
    )
  })
})
