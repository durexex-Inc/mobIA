import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDePrompt from './page'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../../../test/armazem-em-memoria')).moduloDeArmazem,
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
  notFound: () => {
    throw new Error('NOT_FOUND')
  },
  // `EditorDePrompt` e Client Component e chama `useRouter` ao montar.
  useRouter: () => ({ refresh: () => {} }),
}))

// O Monaco de verdade nao roda em jsdom -- ver a mesma decisao em
// `EditorDePrompt.test.tsx`/`DiffDePrompt.test.tsx`.
vi.mock('@monaco-editor/react', () => ({
  default: ({ value }: { value: string }) => <textarea aria-label="editor de prompt" readOnly value={value} />,
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => (
    <div>
      <div data-testid="original">{original}</div>
      <div data-testid="modified">{modified}</div>
    </div>
  ),
}))

const PERMISSOES: Record<string, string[]> = {
  ADMIN: ['CONFIGURAR_AGENTE'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
}

const ATIVA = {
  agente: 'AGENTE',
  versao: 7,
  padrao: false,
  publicadaPor: 'Rafael',
  publicadaEm: '2026-09-20T12:00:00+00:00',
  ativadaPor: 'Rafael',
  ativadaEm: '2026-09-20T12:00:00+00:00',
  motivo: null,
}

const VERSOES = {
  ativa: 7,
  itens: [
    { versao: 7, anterior: 6, autor: 'Rafael', em: '2026-09-20T12:00:00+00:00', diff: '--- 6\n+++ 7' },
    { versao: 6, anterior: 5, autor: 'Rafael', em: '2026-09-18T12:00:00+00:00', diff: '--- 5\n+++ 6' },
  ],
}

function api(
  papel: string,
  opcoes: {
    agente?: { corpo: unknown; status?: number; cabecalhos?: Record<string, string> }
    versoes?: { corpo: unknown; status?: number }
    versao6?: { corpo: unknown; status?: number }
  } = {},
) {
  const agenteResp = opcoes.agente ?? {
    corpo: { ativa: { ...ATIVA, texto: 'Você é {assistente}, tom {tom}. V7' }, padrao: 'texto padrão {assistente} {tom}', limites: { marcadores: ['{assistente}', '{tom}'], maximoDeCaracteres: 500 } },
  }
  const versoesResp = opcoes.versoes ?? { corpo: VERSOES }
  const versao6Resp = opcoes.versao6 ?? {
    corpo: { versao: 6, anterior: 5, autor: 'Rafael', em: '2026-09-18T12:00:00+00:00', diff: '--- 5\n+++ 6', texto: 'Você é {assistente}, tom {tom}. V6' },
  }

  const chamadas = vi.fn<(url: URL | string) => Promise<Response>>(async (url) => {
    const caminho = new URL(String(url)).pathname
    if (caminho === '/api/v1/auth/me') {
      return new Response(
        JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
      )
    }
    if (caminho === '/api/v1/prompts/AGENTE/versoes/6') {
      return new Response(JSON.stringify(versao6Resp.corpo), { status: versao6Resp.status ?? 200 })
    }
    if (caminho === '/api/v1/prompts/AGENTE/versoes') {
      return new Response(JSON.stringify(versoesResp.corpo), { status: versoesResp.status ?? 200 })
    }
    return new Response(JSON.stringify(agenteResp.corpo), {
      status: agenteResp.status ?? 200,
      headers: agenteResp.cabecalhos,
    })
  })
  vi.stubGlobal('fetch', chamadas)
  return chamadas
}

function props(agente = 'agente', busca: { de?: string; para?: string } = {}) {
  return { params: Promise.resolve({ agente }), searchParams: Promise.resolve(busca) }
}

describe('PaginaDePrompt (TEC-338)', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ADMIN ve o editor com o texto ativo e o diff da versao anterior contra a ativa (cenario: comparar duas versoes)', async () => {
    api('ADMIN')

    render(await PaginaDePrompt(props()))

    expect(screen.getByRole('heading', { name: 'Agente principal' })).toBeInTheDocument()
    expect(await screen.findByLabelText('editor de prompt')).toHaveValue('Você é {assistente}, tom {tom}. V7')
    expect(await screen.findByTestId('original')).toHaveTextContent('Você é {assistente}, tom {tom}. V6')
    expect(await screen.findByTestId('modified')).toHaveTextContent('Você é {assistente}, tom {tom}. V7')
  })

  it('comparar com o padrao (versao 0) nao busca uma versao 0 na API', async () => {
    const chamadas = api('ADMIN')

    render(await PaginaDePrompt(props('agente', { de: '0', para: '7' })))

    expect(await screen.findByTestId('original')).toHaveTextContent('texto padrão {assistente} {tom}')
    expect(await screen.findByTestId('modified')).toHaveTextContent('Você é {assistente}, tom {tom}. V7')
    expect(
      chamadas.mock.calls.some(([url]) => new URL(String(url)).pathname.endsWith('/versoes/0')),
    ).toBe(false)
  })

  it('segmento que nao e agente valido da notFound', async () => {
    api('ADMIN')

    await expect(PaginaDePrompt(props('qualificador'))).rejects.toThrow('NOT_FOUND')
  })

  it('CORRETOR que acessa pela URL ve "Sem permissao"', async () => {
    api('CORRETOR')

    render(await PaginaDePrompt(props()))

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login', async () => {
    api('ADMIN', { agente: { corpo: { detail: 'nao autenticado' }, status: 401 } })

    await expect(PaginaDePrompt(props())).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fadmin%2Fprompts%2Fagente&erro=sessao_expirada',
    )
    expect(await lerSessao(cookiesDaRequisicao.get('mobia_sessao') ?? '')).toBeNull()
  })

  it('falha ao buscar a lista de versoes nao derruba a pagina', async () => {
    api('ADMIN', { versoes: { corpo: { detail: 'boom' }, status: 500 } })

    render(await PaginaDePrompt(props()))

    expect(screen.getByRole('heading', { name: 'Agente principal' })).toBeInTheDocument()
    expect(await screen.findByLabelText('editor de prompt')).toHaveValue('Você é {assistente}, tom {tom}. V7')
  })

  describe('reverter (TEC-339)', () => {
    it('lista "Reverter para esta versão" para as versões que nao sao a ativa, e nao para a ativa', async () => {
      api('ADMIN')

      const { container } = render(await PaginaDePrompt(props()))

      const lista = within(container.querySelector('.prompts-versoes-anteriores')!)
      const botoes = lista.getAllByRole('button', { name: 'Reverter para esta versão' })
      // versao 6 (do historico) e a versao 0 (padrao do codigo) -- a ativa (7) nao ganha botao.
      expect(botoes).toHaveLength(2)
      expect(lista.getByText('Padrão do código')).toBeInTheDocument()
      expect(lista.getByText('Versão 6').closest('li')).toHaveTextContent(/Publicada por Rafael/)
      // Desde a TEC-395 a ativa aparece na lista, marcada, e sem botao.
      const ativa = lista.getByText('Versão 7').closest('li')!
      expect(ativa).toHaveTextContent('Em produção')
      expect(within(ativa).queryByRole('button')).not.toBeInTheDocument()
    })

    it('a pagina do agente so busca dado do proprio agente (cenario: outros agentes nao mudam)', async () => {
      const chamadas = api('ADMIN')

      render(await PaginaDePrompt(props()))

      const caminhos = chamadas.mock.calls.map(([url]) => new URL(String(url)).pathname)
      expect(caminhos.every((caminho) => !caminho.includes('INVESTIDOR'))).toBe(true)
      expect(caminhos.some((caminho) => caminho.includes('/prompts/AGENTE'))).toBe(true)
    })
  })
})
