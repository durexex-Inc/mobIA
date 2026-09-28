import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDeImoveis from './page'

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
  // `FormularioDeImovel`/`RetirarImovel` sao Client Component e chamam
  // `useRouter` ao montar, mesmo sem clicar em nada.
  useRouter: () => ({ refresh: () => {} }),
}))

/** O que `/auth/me` devolve, pela matriz da TEC-202: so o ADMIN geri o catalogo. */
const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['GERIR_CATALOGO', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

function imovel(sobrescreve: Record<string, unknown> = {}) {
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

/**
 * `/auth/me` com o papel, a listagem de imoveis e a listagem de importacoes,
 * roteadas por caminho -- `importacoes` sem sobrescrita devolve nenhuma
 * importacao (D4), como a maioria dos testes desta pagina nao se importa
 * com ela.
 */
function api(
  papel: string,
  listagem: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> },
  importacoes: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> } = {
    corpo: { itens: [] },
  },
) {
  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    const caminho = new URL(String(url)).pathname
    if (caminho === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    if (caminho === '/api/v1/imoveis/importacoes') {
      return new Response(JSON.stringify(importacoes.corpo), {
        status: importacoes.status ?? 200,
        headers: importacoes.cabecalhos,
      })
    }
    return new Response(JSON.stringify(listagem.corpo), {
      status: listagem.status ?? 200,
      headers: listagem.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

describe('PaginaDeImoveis (TEC-333)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca SEM `?status=` -- a listagem inicial vem do servidor, com todo status (D6, D7)', async () => {
    const chamadas = api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    await PaginaDeImoveis()

    const listagem = chamadas.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((u) => u.pathname.includes('imoveis'))
    expect(listagem?.pathname).toBe('/api/v1/imoveis')
    expect(listagem?.search).toBe('')
  })

  it('lista os imoveis, com o formulario de cadastro sempre visivel', async () => {
    api('ADMIN', { corpo: { itens: [imovel()], proximoCursor: null } })

    render(await PaginaDeImoveis())

    expect(screen.getByRole('heading', { name: 'Imóveis' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cadastrar imóvel' })).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Apartamento no Centro')).toBeInTheDocument()
  })

  it('lista vazia diz que nao ha imovel cadastrado', async () => {
    api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    render(await PaginaDeImoveis())

    expect(screen.getByText('Nenhum imóvel cadastrado.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('CORRETOR que acessa pela URL ve "Sem permissao", e nada alem de `/auth/me` e pedido', async () => {
    const chamadas = api('CORRETOR', { corpo: { itens: [imovel()], proximoCursor: null } })

    render(await PaginaDeImoveis())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)).toEqual([
      '/api/v1/auth/me',
    ])
  })

  it('403 do backend vence a permissao lida: "Sem permissao"', async () => {
    api('ADMIN', { corpo: { detail: 'proibido' }, status: 403 })

    render(await PaginaDeImoveis())

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco dos imoveis', async () => {
    api('ADMIN', { corpo: { detail: 'nao autenticado' }, status: 401 })

    await expect(PaginaDeImoveis()).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fimoveis&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('a falha de carga mostra o erro com o codigo para o suporte', async () => {
    api('ADMIN', { corpo: { detail: 'boom' }, status: 500, cabecalhos: { 'x-request-id': 'req-9' } })

    render(await PaginaDeImoveis())

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar os imóveis.')
    expect(screen.getByText('req-9')).toBeInTheDocument()
  })

  it('sem sessao vai ao login, com o destino', async () => {
    cookiesDaRequisicao.clear()
    api('ADMIN', { corpo: { itens: [], proximoCursor: null } })

    await expect(PaginaDeImoveis()).rejects.toThrow('REDIRECT:/login?returnTo=%2Fadmin%2Fimoveis')
  })

  describe('a importacao em lote (TEC-334, D4)', () => {
    it('sem nenhuma importacao anterior, a tela de importar abre sem acompanhamento', async () => {
      api('ADMIN', { corpo: { itens: [], proximoCursor: null } }, { corpo: { itens: [] } })

      render(await PaginaDeImoveis())

      expect(screen.getByRole('heading', { name: 'Importar imóveis' })).toBeInTheDocument()
      expect(screen.queryByText(/Processando|Concluído|Falhou/)).toBeNull()
    })

    it('com uma importacao recente, a tela abre ja mostrando o relatorio (D4)', async () => {
      api(
        'ADMIN',
        { corpo: { itens: [], proximoCursor: null } },
        {
          corpo: {
            itens: [
              {
                importacaoId: 'imp-1',
                status: 'CONCLUIDO',
                nomeArquivo: 'lote.csv',
                processados: 10,
                inseridos: 10,
                atualizados: 0,
                inalterados: 0,
                rejeitados: 0,
                erros: [],
              },
            ],
          },
        },
      )

      render(await PaginaDeImoveis())

      expect(screen.getByText(/lote\.csv/)).toBeInTheDocument()
      expect(screen.getByText(/Concluído/)).toBeInTheDocument()
    })

    it('falha ao buscar a importacao mais recente nao derruba a pagina (a listagem de imoveis e o essencial)', async () => {
      api(
        'ADMIN',
        { corpo: { itens: [], proximoCursor: null } },
        { corpo: { detail: 'boom' }, status: 500 },
      )

      render(await PaginaDeImoveis())

      expect(screen.getByRole('heading', { name: 'Imóveis' })).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Importar imóveis' })).toBeInTheDocument()
      expect(screen.queryByText(/Processando|Concluído|Falhou/)).toBeNull()
    })
  })
})
