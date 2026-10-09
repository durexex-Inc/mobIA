import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDePedidos from './page'

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
  // As acoes da linha sao componente de cliente e pedem o router ao renderizar.
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
}))

/** O que `/auth/me` devolve para cada papel, pela matriz da TEC-202. */
const PERMISSOES: Record<string, string[]> = {
  GERENTE: ['ATENDER_LEAD', 'VER_DADOS_COMPLETOS', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
  ADMIN: ['GERIR_CATALOGO', 'GERIR_CORRETORES', 'VER_DETALHE_DO_LEAD', 'VER_FUNIL', 'VER_LEADS'],
  NINGUEM: [],
}

function pedido(extra: Record<string, unknown> = {}) {
  return {
    id: 'p-1',
    criadoEm: '2026-10-08T13:00:00+00:00',
    imovel: { id: 'i-1', codigo: 'AP-101', titulo: 'Apartamento no Centro' },
    nome: 'Joana',
    telefoneMascarado: '+55 48 9****-**21',
    emailMascarado: 'j****a@e*.com',
    leadId: 'l-1',
    atendimento: {
      id: 'h-1',
      status: 'PENDENTE',
      corretor: { id: 'c-a', nome: 'Ana' },
      notificadoEm: null,
      semCorretor: false,
    },
    ...extra,
  }
}

/**
 * O `fetch` dublado, com as rotas que a pagina chama. Devolve SO as chamadas a
 * `/api/v1/interesses`, que e o que os testes inspecionam.
 */
function responde(
  corpo: unknown,
  status = 200,
  { papel = 'ADMIN', corretorId = null }: { papel?: string; corretorId?: string | null } = {},
) {
  const interesses = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(corpo), { status }),
  )
  const corretores = vi.fn(
    async () =>
      new Response(
        JSON.stringify([
          { id: 'c-a', nome: 'Ana', email: 'a@x.com' },
          { id: 'c-b', nome: 'Bia', email: 'b@x.com' },
        ]),
      ),
  )
  const me = async () =>
    new Response(JSON.stringify({ usuarioId: 'u-1', papel, corretorId, permissoes: PERMISSOES[papel] }))
  vi.stubGlobal(
    'fetch',
    vi.fn((url: URL | string, init?: RequestInit) => {
      const texto = String(url)
      if (texto.includes('/api/v1/auth/me')) return me()
      if (texto.includes('/api/v1/corretores')) return corretores()
      return interesses(url, init)
    }),
  )
  return { interesses, corretores }
}

function parametrosDe(chamadas: ReturnType<typeof responde>['interesses']) {
  return new URL(String(chamadas.mock.calls[0][0])).searchParams
}

async function abrir(parametros: Record<string, string | string[]> = {}) {
  render(await PaginaDePedidos({ searchParams: Promise.resolve(parametros) }))
}

describe('PaginaDePedidos', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('o admin ve a linha com imovel, nome e telefone mascarado', async () => {
    responde({ itens: [pedido()], proximoCursor: null })

    await abrir()

    const linha = screen.getByTestId('pedido')
    expect(linha).toHaveTextContent('AP-101')
    expect(linha).toHaveTextContent('Apartamento no Centro')
    expect(linha).toHaveTextContent('Joana')
    expect(linha).toHaveTextContent('+55 48 9****-**21')
    expect(linha).toHaveTextContent('j****a@e*.com')
    expect(linha).toHaveTextContent('Pendente')
    expect(linha).toHaveTextContent('Ana')
    expect(linha).not.toHaveClass('pedido--sem-corretor')
    expect(within(linha).getByRole('link', { name: /AP-101/ })).toHaveAttribute('href', '/busca/i-1')
    // GERIR_CATALOGO abre o imovel no admin tambem.
    expect(within(linha).getByRole('link', { name: 'Editar imóvel' })).toHaveAttribute(
      'href',
      '/admin/imoveis/i-1',
    )
  })

  it('"Sem corretor" fica em destaque', async () => {
    responde({
      itens: [
        pedido({
          atendimento: { id: 'h-1', status: 'PENDENTE', corretor: null, notificadoEm: null, semCorretor: true },
        }),
      ],
      proximoCursor: null,
    })

    await abrir()

    const linha = screen.getByTestId('pedido')
    expect(linha).toHaveClass('pedido--sem-corretor')
    expect(linha).toHaveTextContent('Sem corretor')
  })

  it('sem nome, diz que nao foi informado', async () => {
    responde({ itens: [pedido({ nome: null })], proximoCursor: null })

    await abrir()

    expect(within(screen.getByTestId('pedido')).getAllByRole('cell')[2]).toHaveTextContent(/não informado/i)
  })

  it('pede `estado=pendentes` por padrao, com o JWT de quem esta logado', async () => {
    const { interesses } = responde({ itens: [pedido()], proximoCursor: null })

    await abrir()

    expect(parametrosDe(interesses).get('estado')).toBe('pendentes')
    const cabecalhos = interesses.mock.calls[0][1]?.headers as Record<string, string>
    expect(cabecalhos.Authorization).toBe(`Bearer ${ACESSO_VALIDO}`)
  })

  it('pede `estado=todos` e o cursor quando a URL pede', async () => {
    const { interesses } = responde({ itens: [pedido()], proximoCursor: null })

    await abrir({ estado: 'todos', cursor: 'c2' })

    expect(parametrosDe(interesses).get('estado')).toBe('todos')
    expect(parametrosDe(interesses).get('cursor')).toBe('c2')
  })

  it('o filtro tem "Pendentes" e "Todos", com o ativo marcado', async () => {
    responde({ itens: [pedido()], proximoCursor: null })

    await abrir({ estado: 'todos' })

    expect(screen.getByRole('link', { name: 'Pendentes' })).toHaveAttribute('href', '/interesses')
    expect(screen.getByRole('link', { name: 'Pendentes' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Todos' })).toHaveAttribute('href', '/interesses?estado=todos')
    expect(screen.getByRole('link', { name: 'Todos' })).toHaveAttribute('aria-current', 'page')
  })

  it('sem VER_LEADS, "Sem permissão", e a lista NAO e pedida', async () => {
    const { interesses } = responde({ itens: [], proximoCursor: null }, 200, { papel: 'NINGUEM' })

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(interesses).not.toHaveBeenCalled()
  })

  it('o 403 do backend vence o menu', async () => {
    responde({ detail: 'forbidden' }, 403)

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('401 apaga a sessao e volta ao login com o endereco da lista', async () => {
    responde({ detail: 'nao autenticado' }, 401)
    const id = cookiesDaRequisicao.get('mobia_sessao')

    await expect(
      PaginaDePedidos({ searchParams: Promise.resolve({ estado: 'todos' }) }),
    ).rejects.toThrow('REDIRECT:/login?returnTo=%2Finteresses%3Festado%3Dtodos&erro=sessao_expirada')
    expect(await lerSessao(id)).toBeNull()
  })

  it('5xx mostra o erro, e tentar de novo repete o endereco', async () => {
    responde({ detail: 'boom' }, 500)

    await abrir({ estado: 'todos' })

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar os pedidos de interesse.')
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute(
      'href',
      '/interesses?estado=todos',
    )
  })

  it('lista vazia em pendentes', async () => {
    responde({ itens: [], proximoCursor: null })
    await abrir()
    expect(screen.getByText('Nenhum pedido de interesse pendente.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lista vazia em todos', async () => {
    responde({ itens: [], proximoCursor: null })
    await abrir({ estado: 'todos' })
    expect(screen.getByText('Nenhum pedido de interesse.')).toBeInTheDocument()
  })

  it('com proximoCursor, ha o link "Próxima página"', async () => {
    responde({ itens: [pedido()], proximoCursor: 'c2' })

    await abrir({ estado: 'todos' })

    expect(screen.getByRole('link', { name: 'Próxima página' })).toHaveAttribute(
      'href',
      '/interesses?estado=todos&cursor=c2',
    )
  })

  it('sem proximoCursor, nao ha "Próxima página"', async () => {
    responde({ itens: [pedido()], proximoCursor: null })
    await abrir()
    expect(screen.queryByRole('link', { name: 'Próxima página' })).toBeNull()
  })

  it('o admin recebe o seletor de corretores', async () => {
    const { corretores } = responde({ itens: [pedido()], proximoCursor: null })

    await abrir()

    expect(corretores).toHaveBeenCalled()
    const lista = screen.getByRole('combobox', { name: 'Corretor' }) as HTMLSelectElement
    expect(Array.from(lista.options).map((o) => o.text)).toEqual(['Ana', 'Bia'])
  })

  it('o CORRETOR nao recebe o seletor, e a lista de corretores nao e pedida', async () => {
    const { corretores } = responde({ itens: [pedido()], proximoCursor: null }, 200, {
      papel: 'CORRETOR',
      corretorId: 'c-a',
    })

    await abrir()

    expect(corretores).not.toHaveBeenCalled()
    expect(screen.queryByRole('combobox')).toBeNull()
    // O dono assume e revela o proprio pedido.
    expect(screen.getByRole('button', { name: 'Assumir' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revelar telefone' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Editar imóvel' })).toBeNull()
  })

  it('o CORRETOR alheio nao ve Revelar nem Assumir', async () => {
    responde({ itens: [pedido()], proximoCursor: null }, 200, { papel: 'CORRETOR', corretorId: 'c-b' })

    await abrir()

    expect(screen.queryByRole('button', { name: 'Revelar telefone' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Assumir' })).toBeNull()
  })

  it('a GERENTE revela pela rota do pedido', async () => {
    responde({ itens: [pedido()], proximoCursor: null }, 200, { papel: 'GERENTE' })

    await abrir()

    expect(screen.getByRole('button', { name: 'Revelar telefone' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revelar e-mail' })).toBeInTheDocument()
  })
})
