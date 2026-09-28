import { describe, expect, it } from 'vitest'

import {
  buscaEfetiva,
  canalLegivel,
  dataAbsoluta,
  identificacaoDoLead,
  ordemDaUrl,
  origemDoFunilDaUrl,
  statusLegivel,
  temperaturaLegivel,
  tempoRelativo,
  urlDaLista,
  filtrosDaUrl,
  numeroDaPagina,
  posicaoDaPagina,
  posicaoDaProxima,
  posicaoDaUrl,
  PRIMEIRA_PAGINA,
} from './leads'

describe('buscaEfetiva', () => {
  it('um caractere nao e busca: o terceiro cenario do Gherkin', () => {
    expect(buscaEfetiva('a')).toBeUndefined()
  })

  it('dois caracteres ja sao', () => {
    expect(buscaEfetiva('ab')).toBe('ab')
  })

  it('conta depois de tirar os espacos, que o backend tambem tira', () => {
    expect(buscaEfetiva('  a  ')).toBeUndefined()
    expect(buscaEfetiva('  centro ')).toBe('centro')
  })

  it('o telefone vai como foi digitado: quem normaliza e o backend', () => {
    expect(buscaEfetiva('(48) 99999-0021')).toBe('(48) 99999-0021')
  })

  it('ausente continua ausente', () => {
    expect(buscaEfetiva(undefined)).toBeUndefined()
  })
})

describe('ordemDaUrl', () => {
  it('sem valor, a ordem e por score', () => {
    expect(ordemDaUrl(undefined)).toBe('score_desc')
  })

  it('aceita a ordem por ultima interacao', () => {
    expect(ordemDaUrl('ultima_interacao_desc')).toBe('ultima_interacao_desc')
  })

  it('valor desconhecido volta a ordem por score', () => {
    expect(ordemDaUrl('nome_asc')).toBe('score_desc')
  })
})

describe('urlDaLista', () => {
  it('a ordem padrao nao vai na URL', () => {
    expect(urlDaLista({ ordem: 'score_desc' })).toBe('/leads')
  })

  it('busca e ordem juntas', () => {
    expect(urlDaLista({ busca: '(48) 9', ordem: 'ultima_interacao_desc' })).toBe(
      '/leads?busca=%2848%29+9&ordenar=ultima_interacao_desc',
    )
  })
})

describe('estado da lista na URL (TEC-322)', () => {
  const UUID = '6f1c2a4e-0000-4000-8000-000000000001'

  it('filtros e posicao, em ordem estavel', () => {
    expect(
      urlDaLista({
        ordem: 'score_desc',
        filtros: { temperatura: 'QUENTE', canal: 'whatsapp' },
        posicao: { cursor: 'c3', anteriores: ['c2'], acumular: true },
      }),
    ).toBe('/leads?temperatura=QUENTE&canal=whatsapp&cursor=c3&anterior=c2&acumular=1')
  })

  it('cenario: filtros compartilhaveis -- o link lido de volta da os mesmos filtros', () => {
    const url = urlDaLista({ ordem: 'score_desc', filtros: { temperatura: 'QUENTE', canal: 'whatsapp' } })
    const lido = Object.fromEntries(new URL(url, 'http://x').searchParams)

    expect(filtrosDaUrl(lido)).toEqual({ temperatura: 'QUENTE', canal: 'whatsapp' })
  })

  it('valor fora do vocabulario e "todos"', () => {
    expect(filtrosDaUrl({ status: 'QUALQUER', temperatura: 'quente', corretorId: 'nao-e-uuid' })).toEqual({})
    expect(filtrosDaUrl({ corretorId: UUID }).corretorId).toBe(UUID)
  })
})

describe('origem do funil na URL (TEC-318)', () => {
  it('sem nenhum dos quatro campos, e undefined', () => {
    expect(origemDoFunilDaUrl({})).toBeUndefined()
    expect(origemDoFunilDaUrl({ busca: 'x' })).toBeUndefined()
  })

  it('le os quatro campos quando algum deles vem', () => {
    expect(origemDoFunilDaUrl({ de: '2026-08-01', ate: '2026-08-31', etapa: 'Recomendado' })).toEqual({
      de: '2026-08-01',
      ate: '2026-08-31',
      intencao: undefined,
      etapa: 'Recomendado',
    })
  })

  it('urlDaLista inclui a origem do funil, e a preserva na paginacao/ordenacao', () => {
    const url = urlDaLista({
      ordem: 'score_desc',
      origemDoFunil: { de: '2026-08-01', ate: '2026-08-31', etapa: 'Recomendado' },
    })
    expect(url).toBe('/leads?de=2026-08-01&ate=2026-08-31&etapa=Recomendado')
  })

  it('cenario: o link lido de volta da a mesma origem do funil', () => {
    const url = urlDaLista({
      ordem: 'score_desc',
      origemDoFunil: { de: '2026-08-01', ate: '2026-08-31', intencao: 'COMPRA', etapa: 'Qualificado' },
    })
    const lido = Object.fromEntries(new URL(url, 'http://x').searchParams)

    expect(origemDoFunilDaUrl(lido)).toEqual({
      de: '2026-08-01',
      ate: '2026-08-31',
      intencao: 'COMPRA',
      etapa: 'Qualificado',
    })
  })

  it('sem cursor e a primeira pagina, e `anterior` repetido vira a lista', () => {
    expect(posicaoDaUrl({ anterior: 'x' })).toBe(PRIMEIRA_PAGINA)
    expect(posicaoDaUrl({ cursor: 'c4', anterior: ['c2', 'c3'], acumular: '1' })).toEqual({
      cursor: 'c4',
      anteriores: ['c2', 'c3'],
      acumular: true,
    })
  })

  it('a numeracao vem dos cursores vistos, e voltar remonta a URL da pagina', () => {
    const terceira = { cursor: 'c3', anteriores: ['c2'], acumular: false }
    expect(numeroDaPagina(PRIMEIRA_PAGINA)).toBe(1)
    expect(numeroDaPagina(terceira)).toBe(3)

    expect(posicaoDaProxima(PRIMEIRA_PAGINA, 'c2', false)).toEqual({ cursor: 'c2', anteriores: [], acumular: false })
    expect(posicaoDaProxima(terceira, 'c4', true)).toEqual({ cursor: 'c4', anteriores: ['c2', 'c3'], acumular: true })

    expect(posicaoDaPagina(terceira, 1)).toBe(PRIMEIRA_PAGINA)
    expect(posicaoDaPagina(terceira, 2)).toEqual({ cursor: 'c2', anteriores: [], acumular: false })
    expect(posicaoDaPagina(terceira, 3)).toEqual({ cursor: 'c3', anteriores: ['c2'], acumular: false })
  })
})

describe('identificacaoDoLead', () => {
  it('e o telefone mascarado que a rota devolve', () => {
    expect(identificacaoDoLead({ telefone: '+55 48 9****-**21', channel: 'whatsapp' })).toBe(
      '+55 48 9****-**21',
    )
  })

  it('sem telefone no site, e o visitante que nao digitou o numero', () => {
    expect(identificacaoDoLead({ telefone: null, channel: 'web' })).toBe('Visitante do site')
  })

  it('sem telefone fora do site, nao e visitante do site', () => {
    expect(identificacaoDoLead({ telefone: null, channel: 'whatsapp' })).toBe(
      'Telefone indisponível',
    )
  })
})

describe('rotulos', () => {
  it('traduz o vocabulario do backend', () => {
    expect(temperaturaLegivel('QUENTE')).toBe('Quente')
    expect(statusLegivel('ENCERRADA')).toBe('Encerrada')
    expect(canalLegivel('whatsapp')).toBe('WhatsApp')
    expect(canalLegivel('web')).toBe('Site')
  })

  it('temperatura nula e "sem temperatura", e nao "Frio"', () => {
    expect(temperaturaLegivel(null)).toBe('—')
  })

  it('valor desconhecido aparece como veio', () => {
    expect(canalLegivel('instagram')).toBe('instagram')
  })
})

describe('tempo', () => {
  const agora = new Date('2026-09-26T17:00:00Z')

  it('relativo, em pt-BR', () => {
    expect(tempoRelativo('2026-09-26T16:55:00Z', agora)).toBe('há 5 minutos')
    expect(tempoRelativo('2026-09-26T14:00:00Z', agora)).toBe('há 3 horas')
    expect(tempoRelativo('2026-09-23T17:00:00Z', agora)).toBe('há 3 dias')
  })

  it('menos de um minuto e "agora"', () => {
    expect(tempoRelativo('2026-09-26T16:59:40Z', agora)).toBe('agora')
  })

  it('a data absoluta e no fuso de Sao Paulo', () => {
    expect(dataAbsoluta('2026-09-26T17:03:00Z')).toBe('26/09/2026, 14:03')
  })
})
