import { describe, expect, it } from 'vitest'

import { REL_DE_LINK_EXTERNO, segmentosDe } from './autolink'

describe('segmentosDe', () => {
  it('linka http e https', () => {
    expect(segmentosDe('veja https://exemplo.com agora')).toEqual([
      { tipo: 'texto', valor: 'veja ' },
      { tipo: 'link', valor: 'https://exemplo.com', href: 'https://exemplo.com/' },
      { tipo: 'texto', valor: ' agora' },
    ])
  })

  it('nao linka javascript:, data: nem vbscript:', () => {
    // Cenario 3 do Gherkin da card. Nao ha lista de bloqueio: a expressao EXIGE
    // http(s), entao todo esquema que ninguem lembrou fica de fora por
    // construcao -- inclusive os que forem inventados depois desta card.
    for (const perigoso of [
      'javascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
    ]) {
      expect(segmentosDe(perigoso)).toEqual([{ tipo: 'texto', valor: perigoso }])
    }
  })

  it('mantem o texto inteiro quando nao ha link', () => {
    expect(segmentosDe('quero 2 quartos na zona sul')).toEqual([
      { tipo: 'texto', valor: 'quero 2 quartos na zona sul' },
    ])
  })

  it('nao engole a pontuacao da frase', () => {
    const segmentos = segmentosDe('olha https://exemplo.com.')

    expect(segmentos[1]).toEqual({
      tipo: 'link',
      valor: 'https://exemplo.com',
      href: 'https://exemplo.com/',
    })
    expect(segmentos[2]).toEqual({ tipo: 'texto', valor: '.' })
  })

  it('linka o trecho http de um texto que tenta disfarcar o esquema', () => {
    // `javascript:` continua texto; o `https://` que vem depois e link de
    // verdade e nao ha razao para esconde-lo. O que importa e que o `href`
    // gerado NUNCA carregue o esquema perigoso.
    const segmentos = segmentosDe('javascript:https://exemplo.com')
    const links = segmentos.filter((s) => s.tipo === 'link')

    expect(links).toHaveLength(1)
    expect(links[0].href.startsWith('https://')).toBe(true)
  })

  it('acha mais de um link no mesmo texto', () => {
    const links = segmentosDe('a https://um.com b http://dois.com c').filter(
      (s) => s.tipo === 'link',
    )

    expect(links).toHaveLength(2)
  })

  it('preserva o texto como o lead escreveu, e normaliza so o href', () => {
    // Quem le a transcricao precisa ver o que foi escrito; o `href` e detalhe
    // de navegacao.
    const segmentos = segmentosDe('HTTPS://Exemplo.com/Caminho')
    const link = segmentos.find((s) => s.tipo === 'link')

    expect(link?.valor).toBe('HTTPS://Exemplo.com/Caminho')
    expect(link?.href).toBe('https://exemplo.com/Caminho')
  })
})

describe('REL_DE_LINK_EXTERNO', () => {
  it('tem os tres valores que a card exige', () => {
    // A constante mora em `lib/` e nao dentro do componente de proposito: uma
    // segunda tela que renderize mensagem tem de reusa-la, nao reescreve-la.
    expect(REL_DE_LINK_EXTERNO.split(' ').sort()).toEqual([
      'nofollow',
      'noopener',
      'noreferrer',
    ])
  })
})
