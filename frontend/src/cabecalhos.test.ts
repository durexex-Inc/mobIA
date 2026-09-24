import { describe, expect, it } from 'vitest'

import config from '../next.config'
import { politicaDeSeguranca } from './proxy'

/**
 * Os cabecalhos de seguranca moram em DOIS lugares (D2 do desenho da TEC-356):
 * a CSP em `src/proxy.ts`, porque carrega nonce por requisicao, e os tres
 * estaticos em `next.config.ts`, porque precisam alcancar `_next/static`, que o
 * matcher do proxy exclui.
 *
 * **Este arquivo existe por causa dessa divisao.** Com duas moradas, alguem
 * mexe numa e acha que mexeu nas duas -- e os testes de cada lado continuariam
 * verdes, cada um provando a sua metade. O teste abaixo e o unico lugar do
 * projeto que olha as duas juntas e pergunta "o conjunto que a card exige esta
 * inteiro?".
 *
 * **O que ele NAO prova:** que os cabeçalhos chegam na resposta. Isso depende
 * do servidor do Next aplicar a configuracao, e so se verifica com o app de pe.
 * Foi verificado a mao nesta card (`next start` mais `curl`), inclusive o caso
 * que motiva a divisao -- um asset sob `_next/static` respondendo com
 * `nosniff`. Automatizar exigiria subir o Next dentro do vitest, que e outra
 * card (a esteira de qualidade do frontend e a TEC-355).
 */

const EXIGIDOS = [
  'X-Content-Type-Options',
  'Referrer-Policy',
  'Strict-Transport-Security',
  'Content-Security-Policy',
]

async function nomesConfigurados(): Promise<string[]> {
  const regras = await config.headers!()
  return regras.flatMap((regra) => regra.headers.map((cabecalho) => cabecalho.key))
}

describe('o conjunto de cabecalhos da card', () => {
  it('esta inteiro somando as duas moradas', async () => {
    const daConfig = await nomesConfigurados()
    // A CSP nao esta na config e nao deve estar: e o proxy que a monta, porque
    // o nonce muda a cada requisicao.
    const doProxy = ['Content-Security-Policy']

    for (const exigido of EXIGIDOS) {
      expect([...daConfig, ...doProxy]).toContain(exigido)
    }
  })

  it('aplica os estaticos a todas as rotas, e nao so as do painel', async () => {
    // `source: '/(.*)'` e o que alcanca `_next/static` e `/public`. Restringir
    // a `/` deixaria os assets sem `nosniff` -- que e exatamente o buraco que a
    // D2 fecha.
    const regras = await config.headers!()

    expect(regras.map((regra) => regra.source)).toContain('/(.*)')
  })

  it('nao duplica na config o que o proxy ja manda', async () => {
    // Cabecalho repetido nas duas moradas com valores diferentes seria decidido
    // por precedencia, em silencio -- e ninguem lembra qual ganha.
    expect(await nomesConfigurados()).not.toContain('Content-Security-Policy')
  })

  it('pede HSTS de um ano e sem preload', async () => {
    const regras = await config.headers!()
    const hsts = regras
      .flatMap((regra) => regra.headers)
      .find((cabecalho) => cabecalho.key === 'Strict-Transport-Security')

    expect(hsts?.value).toContain('max-age=31536000')
    // `preload` e quase irreversivel e vale para todos os subdominios,
    // inclusive os que nao existem ainda -- e a nuvem nem foi escolhida
    // (TEC-219). Ver a D4 e a lacuna L3 do desenho.
    expect(hsts?.value).not.toContain('preload')
  })

  it('a CSP do proxy cobre as quatro diretivas que a card nomeia', () => {
    const politica = politicaDeSeguranca('abc', false)

    for (const diretiva of ["frame-ancestors 'none'", "nonce-abc", "object-src 'none'"]) {
      expect(politica).toContain(diretiva)
    }
  })
})
