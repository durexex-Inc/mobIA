import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDeLeads from './page'

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
  // A caixa de busca e componente de cliente e pede o router ao renderizar.
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

/** O que `/auth/me` devolve para cada papel, pela matriz da TEC-202. */
const PERMISSOES: Record<string, string[]> = {
  GERENTE: ['ATENDER_LEAD', 'VER_DADOS_COMPLETOS', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
  LEITURA: ['BUSCAR_IMOVEIS', 'VER_FUNIL', 'VER_LEADS'],
  ADMIN: ['GERIR_CORRETORES', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  NINGUEM: [],
}

function lead(score: number | null, extra: Record<string, unknown> = {}) {
  return {
    leadId: `lead-${score}`,
    channel: 'whatsapp',
    telefone: '+55 48 9****-**21',
    score,
    temperatura: 'QUENTE',
    status: 'ATIVA',
    regiao: 'Centro',
    intencao: 'COMPRA',
    qualificadoEm: null,
    ultimaInteracaoEm: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...extra,
  }
}

/**
 * O `fetch` dublado, com as duas rotas que a pagina chama. Devolve SO as
 * chamadas a `/api/v1/leads`, que e o que os testes inspecionam.
 */
function responde(
  corpo: unknown,
  status = 200,
  { papel = 'GERENTE', cabecalhos = {} }: { papel?: string; cabecalhos?: Record<string, string> } = {},
) {
  const leads = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(corpo), { status, headers: cabecalhos }),
  )
  const me = async () =>
    new Response(
      JSON.stringify({ usuarioId: 'u-1', papel, corretorId: null, permissoes: PERMISSOES[papel] }),
    )
  vi.stubGlobal(
    'fetch',
    vi.fn((url: URL | string, init?: RequestInit) =>
      String(url).includes('/api/v1/auth/me') ? me() : leads(url, init),
    ),
  )
  return leads
}

function parametrosDe(chamadas: ReturnType<typeof responde>) {
  return new URL(String(chamadas.mock.calls[0][0])).searchParams
}

async function abrir(parametros: Record<string, string | string[]> = {}) {
  render(await PaginaDeLeads({ searchParams: Promise.resolve(parametros) }))
}

describe('PaginaDeLeads', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: ordenar por score', () => {
    it('a ordem exibida e 82, 47, 30 -- a da resposta', async () => {
      responde({ itens: [lead(82), lead(47), lead(30)], proximoCursor: null })

      await abrir()

      const scores = screen
        .getAllByTestId('lead')
        .map((linha) => within(linha).getAllByRole('cell')[2].textContent)
      expect(scores).toEqual(['82', '47', '30'])
    })

    it('sem ordem na URL, pede `score_desc`, e o cabecalho "Score" esta marcado', async () => {
      const chamadas = responde({ itens: [lead(82)], proximoCursor: null })

      await abrir()

      expect(parametrosDe(chamadas).get('ordenar')).toBe('score_desc')
      expect(screen.getByRole('columnheader', { name: /Score/ })).toHaveAttribute(
        'aria-sort',
        'descending',
      )
    })
  })

  it('ordenar por ultima interacao pede a ordem ao backend, e nao reordena no cliente', async () => {
    const chamadas = responde({ itens: [lead(10), lead(90)], proximoCursor: null })

    await abrir({ ordenar: 'ultima_interacao_desc' })

    expect(parametrosDe(chamadas).get('ordenar')).toBe('ultima_interacao_desc')
    expect(
      screen.getAllByTestId('lead').map((linha) => within(linha).getAllByRole('cell')[2].textContent),
    ).toEqual(['10', '90'])
    expect(screen.getByRole('columnheader', { name: /Última interação/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
  })

  it('os cabecalhos ordenaveis sao links que preservam a busca', async () => {
    responde({ itens: [lead(82)], proximoCursor: null })

    await abrir({ busca: 'centro' })

    expect(screen.getByRole('link', { name: 'Última interação' })).toHaveAttribute(
      'href',
      '/leads?busca=centro&ordenar=ultima_interacao_desc',
    )
  })

  it('cenario: buscar por telefone com qualquer formatacao -- vai ao backend como foi digitado', async () => {
    const chamadas = responde({ itens: [lead(82)], proximoCursor: null })

    await abrir({ busca: '(48) 99999-0021' })

    expect(parametrosDe(chamadas).get('busca')).toBe('(48) 99999-0021')
    expect(screen.getAllByTestId('lead')).toHaveLength(1)
  })

  it('cenario: busca curta nao chega ao FastAPI, nem digitada na URL', async () => {
    const chamadas = responde({ itens: [lead(82)], proximoCursor: null })

    await abrir({ busca: 'a' })

    expect(parametrosDe(chamadas).has('busca')).toBe(false)
    // A caixa mostra o que a pessoa digitou, mesmo sem ter buscado.
    expect(screen.getByRole('searchbox')).toHaveValue('a')
  })

  describe('cenario: corretor ve so os proprios leads', () => {
    it('a lista e a que o backend devolve, sem filtro por corretor', async () => {
      const doze = Array.from({ length: 12 }, (_, i) => lead(90 - i, { leadId: `l-${i}` }))
      const chamadas = responde({ itens: doze, proximoCursor: null }, 200, { papel: 'CORRETOR' })

      await abrir()

      expect(screen.getAllByTestId('lead')).toHaveLength(12)
      // O recorte e da claim do JWT, no backend (D7 da TEC-192): a pagina nao
      // manda `corretorId`, e nao desenha filtro por corretor (L2).
      expect(parametrosDe(chamadas).has('corretorId')).toBe(false)
      expect(screen.queryByLabelText(/corretor/i)).not.toBeInTheDocument()
    })
  })

  describe('a linha abre o detalhe (TEC-323)', () => {
    it('para quem tem VER_DETALHE_DO_LEAD, com `<a>` comum', async () => {
      responde({ itens: [lead(82)], proximoCursor: null }, 200, { papel: 'CORRETOR' })

      await abrir()

      expect(screen.getByRole('link', { name: '+55 48 9****-**21' })).toHaveAttribute(
        'href',
        '/leads/lead-82',
      )
    })

    it('para LEITURA nao: o link terminaria sempre em "Sem permissao"', async () => {
      responde({ itens: [lead(82)], proximoCursor: null }, 200, { papel: 'LEITURA' })

      await abrir()

      expect(screen.queryByRole('link', { name: '+55 48 9****-**21' })).not.toBeInTheDocument()
      expect(screen.getByTestId('lead')).toHaveTextContent('+55 48 9****-**21')
    })
  })

  describe('revelar o telefone na lista (TEC-330)', () => {
    it('GERENTE ve o "Revelar" ao lado do link, e so na linha com mascara', async () => {
      responde({
        itens: [lead(82), lead(null, { leadId: 'web', channel: 'web', telefone: null })],
        proximoCursor: null,
      })

      await abrir()

      const [comTelefone, semTelefone] = screen.getAllByTestId('lead')
      const botao = within(comTelefone).getByRole('button', { name: 'Revelar telefone' })
      expect(botao.closest('a')).toBeNull()
      expect(within(semTelefone).queryByRole('button')).toBeNull()
    })

    it('CORRETOR nao ve o botao, e a pagina nao traz o numero', async () => {
      responde({ itens: [lead(82)], proximoCursor: null }, 200, { papel: 'CORRETOR' })

      await abrir()

      expect(screen.queryByRole('button', { name: 'Revelar telefone' })).not.toBeInTheDocument()
      expect(document.body.innerHTML).not.toContain('99999')
    })
  })

  it('a linha mostra o telefone mascarado, e o visitante sem telefone e dito', async () => {
    responde({
      itens: [lead(82), lead(null, { leadId: 'web', channel: 'web', telefone: null, temperatura: null })],
      proximoCursor: null,
    })

    await abrir()

    const [primeira, segunda] = screen.getAllByTestId('lead')
    expect(primeira).toHaveTextContent('+55 48 9****-**21')
    expect(primeira).toHaveTextContent('Quente')
    expect(primeira).toHaveTextContent('WhatsApp')
    expect(primeira).toHaveTextContent('há 5 minutos')
    expect(segunda).toHaveTextContent('Visitante do site')
    expect(segunda).toHaveTextContent('Site')
    // Sem score e sem temperatura sao travessao, e nao zero nem "Frio".
    expect(within(segunda).getAllByRole('cell')[2]).toHaveTextContent('—')
    expect(within(segunda).getAllByRole('cell')[1]).toHaveTextContent('—')
  })

  it('a ultima interacao tem a data absoluta no titulo', async () => {
    responde({
      itens: [lead(82, { ultimaInteracaoEm: '2026-09-26T17:03:00+00:00' })],
      proximoCursor: null,
    })

    await abrir()

    const tempo = screen.getByTestId('lead').querySelector('time')
    expect(tempo).toHaveAttribute('title', '26/09/2026, 14:03')
    expect(tempo).toHaveAttribute('dateTime', '2026-09-26T17:03:00+00:00')
  })

  describe('paginacao (TEC-322)', () => {
    it('com proxima pagina, oferece "Próxima" numerada e "Carregar mais" acumulado', async () => {
      responde({ itens: [lead(82)], proximoCursor: 'c2' })

      await abrir({ temperatura: 'QUENTE' })

      const paginas = screen.getByRole('navigation', { name: 'Páginas' })
      expect(within(paginas).getByText('1')).toHaveAttribute('aria-current', 'page')
      expect(within(paginas).getByRole('link', { name: 'Próxima' })).toHaveAttribute(
        'href',
        '/leads?temperatura=QUENTE&cursor=c2',
      )
      expect(screen.getByRole('link', { name: 'Carregar mais' })).toHaveAttribute(
        'href',
        '/leads?temperatura=QUENTE&cursor=c2&acumular=1',
      )
    })

    it('cenario: ordem mantida ao avancar -- a pagina 2 e o cursor da 1, e volta-se a 1 por link', async () => {
      const chamadas = responde({ itens: [lead(47)], proximoCursor: 'c3' })

      await abrir({ cursor: 'c2' })

      expect(parametrosDe(chamadas).get('cursor')).toBe('c2')
      expect(parametrosDe(chamadas).get('ordenar')).toBe('score_desc')
      const paginas = screen.getByRole('navigation', { name: 'Páginas' })
      expect(within(paginas).getByRole('link', { name: '1' })).toHaveAttribute('href', '/leads')
      expect(within(paginas).getByText('2')).toHaveAttribute('aria-current', 'page')
      expect(within(paginas).getByRole('link', { name: 'Próxima' })).toHaveAttribute(
        'href',
        '/leads?cursor=c3&anterior=c2',
      )
    })

    it('"carregar mais" pede as paginas vistas em paralelo e marca as anteriores', async () => {
      const chamadas = vi.fn(async (url: URL | string) => {
        const cursor = new URL(String(url)).searchParams.get('cursor') ?? 'c1'
        return new Response(JSON.stringify({ itens: [lead(Number(cursor.slice(1)))], proximoCursor: null }))
      })
      vi.stubGlobal(
        'fetch',
        vi.fn((url: URL | string) =>
          String(url).includes('/api/v1/auth/me')
            ? Promise.resolve(
                new Response(
                  JSON.stringify({ usuarioId: 'u', papel: 'GERENTE', corretorId: null, permissoes: PERMISSOES.GERENTE }),
                ),
              )
            : chamadas(url),
        ),
      )

      await abrir({ cursor: 'c3', anterior: 'c2', acumular: '1' })

      expect(chamadas.mock.calls.map(([url]) => new URL(String(url)).searchParams.get('cursor'))).toEqual([
        null,
        'c2',
        'c3',
      ])
      const linhas = screen.getAllByTestId('lead')
      expect(linhas).toHaveLength(3)
      expect(linhas.map((l) => l.className)).toEqual(['leads-pagina-anterior', 'leads-pagina-anterior', ''])
    })

    it('sem proxima e na primeira pagina, nao ha navegacao', async () => {
      responde({ itens: [lead(82)], proximoCursor: null })

      await abrir()

      expect(screen.queryByRole('navigation', { name: 'Páginas' })).toBeNull()
      expect(screen.queryByRole('link', { name: 'Carregar mais' })).toBeNull()
    })

    it('as celulas levam o rotulo da coluna, que o CSS usa nos cartoes', async () => {
      responde({ itens: [lead(82)], proximoCursor: null })

      await abrir()

      const celulas = Array.from(screen.getByTestId('lead').querySelectorAll('td')).map((td) => td.dataset.rotulo)
      expect(celulas).toEqual(['Lead', 'Temperatura', 'Score', 'Status', 'Canal', 'Última interação'])
    })
  })

  describe('filtros (TEC-322)', () => {
    it('cenario: filtros compartilhaveis -- a URL vira a consulta e as listas mostram os valores', async () => {
      const chamadas = responde({ itens: [lead(82)], proximoCursor: null })

      await abrir({ temperatura: 'QUENTE', canal: 'whatsapp', status: 'INVENTADO' })

      const enviados = parametrosDe(chamadas)
      expect(enviados.get('temperatura')).toBe('QUENTE')
      expect(enviados.get('canal')).toBe('whatsapp')
      expect(enviados.has('status')).toBe(false)
      expect(screen.getByLabelText('Temperatura')).toHaveValue('QUENTE')
      expect(screen.getByLabelText('Canal')).toHaveValue('whatsapp')
    })

    it('trocar a ordem mantem os filtros e volta a primeira pagina', async () => {
      responde({ itens: [lead(82)], proximoCursor: null })

      await abrir({ temperatura: 'QUENTE', cursor: 'c2' })

      expect(screen.getByRole('link', { name: 'Última interação' })).toHaveAttribute(
        'href',
        '/leads?ordenar=ultima_interacao_desc&temperatura=QUENTE',
      )
    })

    it('GERENTE ve o filtro por corretor desabilitado', async () => {
      responde({ itens: [lead(82)], proximoCursor: null })

      await abrir()

      expect(screen.getByText('Filtro por corretor indisponível para o seu papel.')).toBeInTheDocument()
    })

    it('para o CORRETOR o filtro por corretor nao existe', async () => {
      responde({ itens: [lead(82)], proximoCursor: null }, 200, { papel: 'CORRETOR' })

      await abrir()

      expect(within(screen.getByRole('form', { name: 'Filtros' })).queryByText(/Corretor/)).toBeNull()
    })

    it('ADMIN escolhe entre os corretores ativos', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: URL | string) => {
          const texto = String(url)
          if (texto.includes('/api/v1/auth/me')) {
            return new Response(
              JSON.stringify({ usuarioId: 'u', papel: 'ADMIN', corretorId: null, permissoes: PERMISSOES.ADMIN }),
            )
          }
          if (texto.includes('/api/v1/corretores')) {
            return new Response(JSON.stringify([{ id: 'c-paulo', nome: 'Paulo', email: 'p@x.com' }]))
          }
          return new Response(JSON.stringify({ itens: [lead(82)], proximoCursor: null }))
        }),
      )

      await abrir()

      const lista = screen.getByLabelText('Corretor') as HTMLSelectElement
      expect(Array.from(lista.options).map((o) => o.text)).toEqual(['Todos', 'Paulo'])
    })

    it('link filtrado por corretor aberto pela GERENTE continua filtrado e pode ser removido', async () => {
      const id = '6f1c2a4e-0000-4000-8000-000000000001'
      const chamadas = responde({ itens: [lead(82)], proximoCursor: null })

      await abrir({ corretorId: id, canal: 'web' })

      expect(parametrosDe(chamadas).get('corretorId')).toBe(id)
      expect(screen.getByText(/Filtrada por um corretor/)).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Remover filtro' })).toHaveAttribute('href', '/leads?canal=web')
    })

    it('filtro sem resultado diz isso, e nao que a base esta vazia', async () => {
      responde({ itens: [], proximoCursor: null })

      await abrir({ temperatura: 'FRIO' })

      expect(screen.getByText('Nenhum lead com estes filtros.')).toBeInTheDocument()
    })
  })

  it('base vazia e busca vazia dizem coisas diferentes', async () => {
    responde({ itens: [], proximoCursor: null })
    await abrir()
    expect(screen.getByText('Nenhum lead ainda.')).toBeInTheDocument()
  })

  it('busca sem resultado nomeia o termo', async () => {
    responde({ itens: [], proximoCursor: null })
    await abrir({ busca: 'Trindade' })
    expect(screen.getByText('Nenhum lead encontrado para “Trindade”.')).toBeInTheDocument()
  })

  it('pede a lista com o JWT de quem esta logado', async () => {
    const chamadas = responde({ itens: [], proximoCursor: null })

    await abrir()

    const cabecalhos = chamadas.mock.calls[0][1]?.headers as Record<string, string>
    expect(cabecalhos.Authorization).toBe(`Bearer ${ACESSO_VALIDO}`)
  })

  it('sem VER_LEADS, "Sem permissao", e a lista NAO e pedida', async () => {
    const chamadas = responde({ itens: [], proximoCursor: null }, 200, { papel: 'NINGUEM' })

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(chamadas).not.toHaveBeenCalled()
  })

  it('o 403 do backend vence o menu', async () => {
    responde({ detail: 'forbidden' }, 403)

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco da lista (TEC-310, D5)', async () => {
    responde({ detail: 'nao autenticado' }, 401)
    const id = cookiesDaRequisicao.get('mobia_sessao')

    await expect(
      PaginaDeLeads({ searchParams: Promise.resolve({ busca: 'centro' }) }),
    ).rejects.toThrow('REDIRECT:/login?returnTo=%2Fleads%3Fbusca%3Dcentro&erro=sessao_expirada')
    expect(await lerSessao(id)).toBeNull()
  })

  it('sem sessao vai ao login, e o FastAPI nao e chamado', async () => {
    cookiesDaRequisicao.clear()
    const chamadas = responde({ itens: [], proximoCursor: null })

    await expect(PaginaDeLeads({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      'REDIRECT:/login?returnTo=%2Fleads',
    )
    expect(chamadas).not.toHaveBeenCalled()
  })

  it('5xx mostra o erro com o codigo da resposta, e tentar de novo repete o endereco', async () => {
    responde({ detail: 'boom' }, 500, { cabecalhos: { 'x-request-id': 'req-123' } })

    await abrir({ busca: 'centro' })

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar a lista de leads.')
    expect(screen.getByText('req-123')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute(
      'href',
      '/leads?busca=centro',
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('422 diz a razao, e tentar de novo volta a primeira pagina com a mesma busca e filtros', async () => {
    responde({ detail: 'cursor invalido' }, 422)

    await abrir({ busca: 'centro', temperatura: 'QUENTE', cursor: 'velho' })

    expect(screen.getByRole('alert')).toHaveTextContent('cursor invalido')
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute(
      'href',
      '/leads?busca=centro&temperatura=QUENTE',
    )
  })

  it('backend fora do ar vira aviso, e nao tela quebrada', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: URL | string) =>
        String(url).includes('/api/v1/auth/me')
          ? Promise.resolve(
              new Response(
                JSON.stringify({ usuarioId: 'u', papel: 'GERENTE', corretorId: null, permissoes: PERMISSOES.GERENTE }),
              ),
            )
          : Promise.reject(new TypeError('fetch failed')),
      ),
    )

    await abrir()

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar a lista de leads.')
  })
})
