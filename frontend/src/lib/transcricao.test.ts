import { describe, expect, it } from 'vitest'

import { ladoDoAutor, rotuloDoAutor, textoDaFala, urlDasAnteriores } from './transcricao'

function fala(extra: Record<string, unknown> = {}) {
  return {
    id: 'f-1',
    autor: 'LEAD',
    tipo: 'TEXTO',
    conteudo: 'Oi',
    retida: false,
    em: '2026-09-26T17:03:00+00:00',
    ...extra,
  }
}

describe('autor', () => {
  it.each([
    ['LEAD', 'Lead', 'lead'],
    ['AGENTE', 'Assistente', 'equipe'],
    ['CORRETOR', 'Corretor', 'equipe'],
    ['SISTEMA', 'Sistema', 'sistema'],
  ] as const)('%s: rotulo "%s", lado %s', (autor, rotulo, lado) => {
    expect(rotuloDoAutor(autor)).toBe(rotulo)
    expect(ladoDoAutor(autor)).toBe(lado)
  })

  it('autor desconhecido aparece como veio, no centro', () => {
    expect(rotuloDoAutor('BOT')).toBe('BOT')
    expect(ladoDoAutor('BOT')).toBe('sistema')
  })
})

describe('textoDaFala', () => {
  it('o conteudo, quando ha', () => {
    expect(textoDaFala(fala())).toBe('Oi')
  })

  it('a fala retida nunca mostra conteudo, nem se viesse', () => {
    expect(textoDaFala(fala({ retida: true, conteudo: 'segredo' }))).toBe(
      'Mensagem retida pela moderação',
    )
  })

  it.each([
    ['AUDIO', 'Áudio sem texto'],
    ['IMAGEM', 'Imagem sem texto'],
    ['DOCUMENTO', 'Documento sem texto'],
    ['DESCONHECIDO', 'Mídia sem texto'],
    ['TEXTO', 'Mensagem sem texto'],
  ])('sem conteudo, %s diz o tipo', (tipo, texto) => {
    expect(textoDaFala(fala({ tipo, conteudo: null }))).toBe(texto)
  })
})

describe('urlDasAnteriores', () => {
  it('vai pelo proxy, com o id e o cursor codificados', () => {
    expect(urlDasAnteriores('a/b', 'c+d=')).toBe('/bff/api/v1/leads/a%2Fb/mensagens?cursor=c%2Bd%3D')
  })
})
