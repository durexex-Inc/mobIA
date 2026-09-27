import { describe, expect, it } from 'vitest'

import {
  buscaEfetiva,
  canalLegivel,
  dataAbsoluta,
  identificacaoDoLead,
  ordemDaUrl,
  statusLegivel,
  temperaturaLegivel,
  tempoRelativo,
  urlDaLista,
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
