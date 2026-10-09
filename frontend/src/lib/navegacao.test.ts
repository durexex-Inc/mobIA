import { describe, expect, it } from 'vitest'

import { itensDoMenu, nomeDoPapel, paginaInicialDe, podeVerAdmin } from './navegacao'

/**
 * As permissoes de cada papel, copiadas de `domain/usuarios/permissoes.py`
 * (TEC-202). **E copia de proposito**: o teste afirma o que o menu faz com o
 * que `/auth/me` devolve para cada papel hoje. Se a matriz do backend mudar,
 * este teste nao reprova -- e o menu continua certo, porque pergunta pela
 * permissao e nao pelo papel (D1).
 */
const PERMISSOES = {
  ADMIN: [
    'ATENDER_LEAD',
    'ATENDER_TITULAR',
    'BUSCAR_IMOVEIS',
    'CONFIGURAR_AGENTE',
    'GERIR_CATALOGO',
    'GERIR_CORRETORES',
    'OPERAR_FILA',
    'VER_AUDITORIA',
    'VER_DADOS_COMPLETOS',
    'VER_DETALHE_DO_LEAD',
    'VER_FUNIL',
    'VER_LEADS',
  ],
  GERENTE: [
    'ATENDER_LEAD',
    'BUSCAR_IMOVEIS',
    'VER_DADOS_COMPLETOS',
    'VER_DETALHE_DO_LEAD',
    'VER_FUNIL',
    'VER_LEADS',
  ],
  CORRETOR: ['ATENDER_LEAD', 'BUSCAR_IMOVEIS', 'VER_DETALHE_DO_LEAD', 'VER_LEADS'],
  LEITURA: ['BUSCAR_IMOVEIS', 'VER_FUNIL', 'VER_LEADS'],
}

describe('itensDoMenu', () => {
  // O "Esquema do Cenario: Menu exibido por papel" do Gherkin, linha a linha.
  it.each([
    ['ADMIN', true, true],
    ['GERENTE', false, true],
    ['CORRETOR', false, false],
    ['LEITURA', false, true],
  ] as const)('%s: administracao=%s, funil=%s', (papel, admin, funil) => {
    const rotulos = itensDoMenu(new Set(PERMISSOES[papel])).map((item) => item.rotulo)

    expect(rotulos.includes('Administração')).toBe(admin)
    expect(rotulos.includes('Funil')).toBe(funil)
  })

  it.each(['ADMIN', 'GERENTE', 'CORRETOR', 'LEITURA'] as const)(
    '%s ve "Leads": VER_LEADS e dos quatro papeis (TEC-321)',
    (papel) => {
      const rotulos = itensDoMenu(new Set(PERMISSOES[papel])).map((item) => item.rotulo)

      expect(rotulos).toContain('Leads')
    },
  )

  it('"Pedidos de interesse" vem logo depois de Leads, para quem tem VER_LEADS (TEC-404)', () => {
    const itens = itensDoMenu(new Set(['VER_LEADS']))
    const i = itens.findIndex((item) => item.rotulo === 'Leads')

    expect(itens[i + 1]).toEqual({ rotulo: 'Pedidos de interesse', href: '/interesses' })
    expect(itensDoMenu(new Set(['VER_FUNIL'])).map((item) => item.rotulo)).not.toContain(
      'Pedidos de interesse',
    )
  })

  it.each([
    ['ADMIN', true],
    ['GERENTE', true],
    ['CORRETOR', false],
    ['LEITURA', true],
  ] as const)('%s ve "Custo de IA": mesma permissao do funil (TEC-319)', (papel, ve) => {
    const rotulos = itensDoMenu(new Set(PERMISSOES[papel])).map((item) => item.rotulo)

    expect(rotulos.includes('Custo de IA')).toBe(ve)
  })

  it('sem permissao nenhuma, menu vazio', () => {
    expect(itensDoMenu(new Set())).toEqual([])
  })

  it('uma permissao de admin so ja abre a area', () => {
    expect(podeVerAdmin(new Set(['VER_AUDITORIA']))).toBe(true)
  })
})

describe('paginaInicialDe', () => {
  it.each([
    ['ADMIN', '/'],
    ['GERENTE', '/'],
    ['LEITURA', '/'],
    ['CORRETOR', '/leads'],
  ] as const)('%s comeca em %s', (papel, pagina) => {
    expect(paginaInicialDe(new Set(PERMISSOES[papel]))).toBe(pagina)
  })

  it('sem nenhuma das duas telas, `/`, que diz "Sem permissao"', () => {
    expect(paginaInicialDe(new Set())).toBe('/')
  })
})

describe('nomeDoPapel', () => {
  it('traduz o identificador para quem le', () => {
    expect(nomeDoPapel('CORRETOR')).toBe('Corretor')
    expect(nomeDoPapel('ADMIN')).toBe('Administrador')
  })

  it('papel desconhecido aparece como veio, que e a pista para investigar', () => {
    expect(nomeDoPapel('DONO')).toBe('DONO')
  })
})
