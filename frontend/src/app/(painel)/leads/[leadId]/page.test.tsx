import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import PaginaDoLead from './page'

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
}))

const PERMISSOES: Record<string, string[]> = {
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
  LEITURA: ['BUSCAR_IMOVEIS', 'VER_FUNIL', 'VER_LEADS'],
}

const LEAD_ID = '6f1c2a4e-0000-4000-8000-000000000001'

const RESUMO = [
  '## Quem e o lead',
  'Lead do WhatsApp desde 20/09.',
  '## O que procura',
  'Apartamento de 2 quartos no Centro.',
  '## Score e temperatura',
  '82, quente.',
  '## Imoveis apresentados',
  'AP-101, gostou.',
  '## Pontos de atencao',
  'Recusou informar renda.',
  '## Proxima acao',
  'Ligar hoje.',
].join('\n')

function detalhe(extra: Record<string, unknown> = {}) {
  return {
    leadId: LEAD_ID,
    channel: 'whatsapp',
    status: 'ATIVA',
    ultimaInteracaoEm: new Date(Date.now() - 5 * 60_000).toISOString(),
    contato: { telefone: '+55 48 9****-**21', email: null },
    score: 82,
    resumo: {
      handoffId: 'h-1',
      texto: RESUMO,
      geradoEm: '2026-09-26T12:00:00+00:00',
      modelo: 'claude',
      fallback: false,
    },
    qualificacao: { intencao: 'COMPRA', regiao: 'Centro', quartos: 2, camposRecusados: ['renda'] },
    historicoScore: [{ em: '2026-09-26T12:00:00+00:00', anterior: 47, novo: 82, fatores: {}, causas: [] }],
    recomendacoes: [],
    agendamentos: [],
    followups: [],
    ...extra,
  }
}

const SEM_FALAS = { itens: [], cursorAnterior: null }

/**
 * O `fetch` dublado, com as tres rotas que a pagina chama: `/auth/me`, o
 * detalhe e a transcricao (TEC-324). Devolve as chamadas ao detalhe e a
 * transcricao, nessa ordem de disparo.
 */
function responde(
  corpo: unknown,
  status = 200,
  {
    papel = 'CORRETOR',
    transcricao = SEM_FALAS as unknown,
    statusDaTranscricao = 200,
  }: { papel?: string; transcricao?: unknown; statusDaTranscricao?: number } = {},
) {
  const api = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(async (url) =>
    new URL(String(url)).pathname.endsWith('/mensagens')
      ? new Response(JSON.stringify(transcricao), { status: statusDaTranscricao })
      : new Response(JSON.stringify(corpo), { status }),
  )
  const me = async () =>
    new Response(
      JSON.stringify({ usuarioId: 'u-1', papel, corretorId: 'c-1', permissoes: PERMISSOES[papel] }),
    )
  vi.stubGlobal(
    'fetch',
    vi.fn((url: URL | string, init?: RequestInit) =>
      String(url).includes('/api/v1/auth/me') ? me() : api(url, init),
    ),
  )
  return api
}

async function abrir(leadId = LEAD_ID) {
  render(await PaginaDoLead({ params: Promise.resolve({ leadId }) }))
}

function titulosDasSecoes() {
  return screen.getAllByRole('heading', { level: 2 }).map((h) => h.firstChild?.textContent)
}

describe('PaginaDoLead', () => {
  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: resumo no topo da tela', () => {
    it('o resumo de seis blocos e a primeira secao, rotulado "Gerado pelo assistente"', async () => {
      responde(detalhe())

      await abrir()

      expect(titulosDasSecoes()[0]).toBe('Resumo')
      const resumo = screen.getByRole('region', { name: 'Resumo' })
      expect(resumo).toHaveTextContent('Gerado pelo assistente')
      expect(within(resumo).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
        'Quem é o lead',
        'O que procura',
        'Score e temperatura',
        'Imóveis apresentados',
        'Pontos de atenção',
        'Próxima ação',
      ])
      expect(resumo).toHaveTextContent('Ligar hoje.')
    })

    it('as secoes seguem a ordem da card', async () => {
      responde(detalhe())

      await abrir()

      expect(titulosDasSecoes()).toEqual([
        'Resumo',
        'Contato',
        'Qualificação',
        'Agendamentos',
        'Follow-ups',
        'Conversa',
      ])
    })
  })

  it('cenario: resumo deterministico sinalizado, sem o preambulo entre colchetes', async () => {
    responde(
      detalhe({
        resumo: {
          handoffId: 'h-1',
          texto: `[resumo automatico simplificado -- o modelo nao gerou]\n\n${RESUMO}`,
          geradoEm: null,
          modelo: null,
          fallback: true,
        },
      }),
    )

    await abrir()

    const resumo = screen.getByRole('region', { name: 'Resumo' })
    expect(resumo).toHaveTextContent('Resumo simplificado')
    expect(resumo).not.toHaveTextContent('Gerado pelo assistente')
    expect(resumo).not.toHaveTextContent('resumo automatico simplificado')
  })

  it('sem resumo, a secao continua primeira e diz por que', async () => {
    responde(detalhe({ resumo: null }))

    await abrir()

    expect(titulosDasSecoes()[0]).toBe('Resumo')
    expect(screen.getByRole('region', { name: 'Resumo' })).toHaveTextContent(
      'ainda não tem resumo',
    )
  })

  describe('agendamentos: a fonte existe, e a tela nao diz "Ainda nao medido" (D4)', () => {
    it('lista os que existem', async () => {
      responde(
        detalhe({
          agendamentos: [
            {
              id: 'a-1',
              tipo: 'VISITA_PRESENCIAL',
              inicio: '2026-09-28T17:00:00+00:00',
              fim: '2026-09-28T18:00:00+00:00',
              status: 'CONFIRMADO',
              imovelId: null,
            },
          ],
        }),
      )

      await abrir()

      const secao = screen.getByRole('region', { name: 'Agendamentos' })
      expect(secao).toHaveTextContent('Visita presencial')
      expect(secao).toHaveTextContent('28/09/2026, 14:00')
      expect(secao).toHaveTextContent('Confirmado')
      expect(secao).not.toHaveTextContent('Ainda não medido')
    })

    it('sem nenhum, e o estado vazio', async () => {
      responde(detalhe())

      await abrir()

      const secao = screen.getByRole('region', { name: 'Agendamentos' })
      expect(secao).toHaveTextContent('Nenhum agendamento.')
      expect(secao).not.toHaveTextContent('Ainda não medido')
    })
  })

  it('cenario: lead de outro corretor pelo endereco direto -- "Sem permissao"', async () => {
    responde({ detail: 'lead de outro corretor' }, 403)

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Resumo' })).not.toBeInTheDocument()
  })

  it('contato so mascarado, e-mail sem fonte', async () => {
    responde(detalhe())

    await abrir()

    const contato = screen.getByRole('region', { name: 'Contato' })
    expect(contato).toHaveTextContent('+55 48 9****-**21')
    expect(contato).toHaveTextContent('E-mailNão informado')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('+55 48 9****-**21')
  })

  it('qualificacao com o que falta e o que foi recusado', async () => {
    responde(detalhe())

    await abrir()

    const secao = screen.getByRole('region', { name: 'Qualificação' })
    expect(secao).toHaveTextContent('IntençãoCompra')
    expect(secao).toHaveTextContent('Quartos2')
    expect(secao).toHaveTextContent('VagasNão informado')
    expect(secao).toHaveTextContent('Recusou informarrenda')
  })

  it('qualificacao nula e um fato so, e nao uma grade de "Nao informado"', async () => {
    responde(detalhe({ qualificacao: null }))

    await abrir()

    const secao = screen.getByRole('region', { name: 'Qualificação' })
    expect(secao).toHaveTextContent('ainda não extraiu nenhum dado')
    expect(secao).not.toHaveTextContent('Não informado')
  })

  it('follow-ups enviados, com a temperatura e quando', async () => {
    responde(
      detalhe({
        followups: [
          { tentativa: 1, temperatura: 'MORNO', disparadoEm: new Date(Date.now() - 2 * 86_400_000).toISOString() },
        ],
      }),
    )

    await abrir()

    expect(screen.getByRole('region', { name: 'Follow-ups' })).toHaveTextContent(
      'Tentativa 1 · Morno · anteontem',
    )
  })

  describe('a conversa (TEC-324)', () => {
    it('e a ultima secao, com as falas da primeira pagina', async () => {
      responde(detalhe(), 200, {
        transcricao: {
          itens: [{ id: 'f-1', autor: 'LEAD', tipo: 'TEXTO', conteudo: 'Oi, vi o anúncio', retida: false, em: '2026-09-26T17:03:00+00:00' }],
          cursorAnterior: 'c1',
        },
      })

      await abrir()

      expect(titulosDasSecoes().at(-1)).toBe('Conversa')
      const conversa = screen.getByRole('region', { name: 'Conversa' })
      expect(conversa).toHaveTextContent('Oi, vi o anúncio')
      expect(within(conversa).getByRole('button', { name: 'Carregar anteriores' })).toBeInTheDocument()
    })

    it('detalhe e transcricao sao pedidos juntos, antes de qualquer resposta', async () => {
      // Se a pagina esperasse o detalhe para pedir a transcricao, o segundo
      // pedido so sairia depois de o primeiro resolver. Aqui o detalhe nunca
      // resolve sozinho, e a transcricao tem de ter saido assim mesmo.
      const pedidos: string[] = []
      let liberar: () => void = () => {}
      const detalheSegurado = new Promise<void>((resolver) => {
        liberar = resolver
      })
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: URL | string) => {
          const caminho = new URL(String(url)).pathname
          if (caminho.endsWith('/auth/me')) {
            return new Response(
              JSON.stringify({ usuarioId: 'u', papel: 'CORRETOR', corretorId: 'c', permissoes: PERMISSOES.CORRETOR }),
            )
          }
          pedidos.push(caminho)
          if (caminho.endsWith('/mensagens')) {
            return new Response(JSON.stringify(SEM_FALAS))
          }
          await detalheSegurado
          return new Response(JSON.stringify(detalhe()))
        }),
      )

      const pagina = PaginaDoLead({ params: Promise.resolve({ leadId: LEAD_ID }) })
      await vi.waitFor(() => expect(pedidos).toHaveLength(2))
      liberar()
      render(await pagina)

      expect(pedidos).toEqual([`/api/v1/leads/${LEAD_ID}`, `/api/v1/leads/${LEAD_ID}/mensagens`])
    })

    it('se so a transcricao falha, o resto da tela abre, e a secao diz que falhou', async () => {
      responde(detalhe(), 200, { transcricao: { detail: 'boom' }, statusDaTranscricao: 500 })

      await abrir()

      expect(screen.getByRole('region', { name: 'Resumo' })).toBeInTheDocument()
      expect(screen.getByRole('region', { name: 'Conversa' })).toHaveTextContent(
        'Não foi possível carregar a conversa.',
      )
    })
  })

  it('historico de score e recomendacoes nao aparecem: sao da TEC-325', async () => {
    responde(detalhe())

    await abrir()

    expect(screen.queryByRole('region', { name: /score/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /recomend/i })).not.toBeInTheDocument()
  })

  it('pede o lead pelo id, codificado, com o JWT de quem esta logado', async () => {
    const api = responde(detalhe())

    await abrir()

    const [url, init] = api.mock.calls[0]
    expect(new URL(String(url)).pathname).toBe(`/api/v1/leads/${LEAD_ID}`)
    expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACESSO_VALIDO}`)
  })

  it('um id com barra nao vira outro caminho da API', async () => {
    const api = responde({ detail: 'lead nao existe' }, 404)

    await abrir('x/revelar')

    expect(new URL(String(api.mock.calls[0][0])).pathname).toBe('/api/v1/leads/x%2Frevelar')
    expect(screen.getByRole('heading', { name: 'Lead não encontrado' })).toBeInTheDocument()
  })

  it('LEITURA ve "Sem permissao", e o lead NAO e pedido -- nada vai para a trilha', async () => {
    const api = responde(detalhe(), 200, { papel: 'LEITURA' })

    await abrir()

    expect(screen.getByRole('heading', { name: 'Sem permissão' })).toBeInTheDocument()
    expect(api).not.toHaveBeenCalled()
  })

  it.each([404, 422])('%i vira "Lead nao encontrado", com o caminho de volta', async (status) => {
    responde({ detail: 'lead nao existe' }, status)

    await abrir()

    expect(screen.getByRole('heading', { name: 'Lead não encontrado' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Voltar para a lista' })).toHaveAttribute('href', '/leads')
  })

  it('5xx mostra o erro com "tentar de novo" no mesmo endereco', async () => {
    responde({ detail: 'boom' }, 500)

    await abrir()

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível carregar o lead.')
    expect(screen.getByRole('link', { name: 'Tentar de novo' })).toHaveAttribute(
      'href',
      `/leads/${LEAD_ID}`,
    )
  })

  it('401 apaga a sessao e volta ao login com o endereco do lead', async () => {
    responde({ detail: 'nao autenticado' }, 401)
    const id = cookiesDaRequisicao.get('mobia_sessao')

    await expect(PaginaDoLead({ params: Promise.resolve({ leadId: LEAD_ID }) })).rejects.toThrow(
      `REDIRECT:/login?returnTo=%2Fleads%2F${LEAD_ID}&erro=sessao_expirada`,
    )
    expect(await lerSessao(id)).toBeNull()
  })
})
