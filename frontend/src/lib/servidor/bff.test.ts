import { describe, expect, it } from 'vitest'

import { caminhoPermitido, idDeRequisicao, origemAceita } from './bff'

const FUNIL = ['api', 'v1', 'metricas', 'funil']

describe('caminhoPermitido', () => {
  it('deixa passar o par metodo+rota que esta na tabela', () => {
    expect(caminhoPermitido('GET', FUNIL)).toBe('/api/v1/metricas/funil')
  })

  it('aceita o metodo em caixa baixa, porque o valor vem da requisicao', () => {
    expect(caminhoPermitido('get', FUNIL)).toBe('/api/v1/metricas/funil')
  })

  it('recusa metodo errado na rota certa: a entrada da tabela e o PAR', () => {
    expect(caminhoPermitido('POST', FUNIL)).toBeNull()
    expect(caminhoPermitido('DELETE', FUNIL)).toBeNull()
  })

  it('recusa rota que nao esta na tabela', () => {
    expect(caminhoPermitido('GET', ['api', 'v1', 'corretores'])).toBeNull()
    expect(caminhoPermitido('GET', ['health'])).toBeNull()
  })

  it('recusa caminho vazio', () => {
    expect(caminhoPermitido('GET', [])).toBeNull()
  })

  describe('a transcricao do lead (TEC-324)', () => {
    const LEAD = '6f1c2a4e-0000-4000-8000-000000000001'

    it('deixa passar a transcricao, com o `*` casando o id', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD, 'mensagens'])).toBe(
        `/api/v1/leads/${LEAD}/mensagens`,
      )
    })

    it('o `*` nao abre as outras rotas do lead', () => {
      // O detalhe, a revelacao e a lista continuam fora do alcance do
      // navegador: so a transcricao tem consumidor de cliente.
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD])).toBeNull()
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'revelar'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads'])).toBeNull()
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'mensagens'])).toBeNull()
    })

    it('o `*` casa um segmento so, e nunca `..`', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', '..', 'mensagens'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', 'a', 'b', 'mensagens'])).toBeNull()
    })
  })

  it('nao casa por PREFIXO, que e o furo classico de allowlist', () => {
    // Se o casamento fosse `startsWith`, esta linha passaria e levaria o
    // FastAPI a `/api/v1/corretores` depois da normalizacao do caminho.
    expect(caminhoPermitido('GET', [...FUNIL, 'extra'])).toBeNull()
    expect(caminhoPermitido('GET', ['api', 'v1', 'metricas'])).toBeNull()
  })

  describe('traversal', () => {
    it('recusa `..` em qualquer posicao', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'metricas', '..'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', '..', 'v1', 'metricas', 'funil'])).toBeNull()
    })

    it('recusa `.`', () => {
      expect(caminhoPermitido('GET', ['api', '.', 'v1', 'metricas', 'funil'])).toBeNull()
    })

    it('recusa segmento vazio', () => {
      expect(caminhoPermitido('GET', ['api', '', 'v1', 'metricas', 'funil'])).toBeNull()
    })

    it('recusa `%2F` decodificado, que contrabandearia um separador', () => {
      // O `[...rota]` do Next entrega os segmentos ja decodificados: um
      // `%2F` na URL chega como `/` DENTRO de um segmento, e reapareceria
      // como separador no `join` se ninguem olhasse.
      expect(caminhoPermitido('GET', ['api/v1', 'metricas', 'funil'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'metricas', 'funil/../corretores'])).toBeNull()
    })

    it('recusa barra invertida e byte nulo', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'metricas', 'funil\\x'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'metricas', 'funil\0'])).toBeNull()
    })
  })
})

describe('origemAceita', () => {
  const propria = 'https://painel.exemplo.com'

  it('recusa origem estrangeira, em mutacao e em leitura', () => {
    for (const metodo of ['POST', 'GET', 'DELETE']) {
      expect(origemAceita({ origem: 'https://site-externo.com', propriaOrigem: propria, metodo }))
        .toBe(false)
    }
  })

  it('aceita a propria origem', () => {
    expect(origemAceita({ origem: propria, propriaOrigem: propria, metodo: 'POST' })).toBe(true)
  })

  it('aceita ausencia de `Origin` em metodo seguro', () => {
    // Navegacao, prefetch e `<img>` de mesma origem nao mandam `Origin`:
    // exigi-lo aqui quebraria o consumidor legitimo.
    expect(origemAceita({ origem: null, propriaOrigem: propria, metodo: 'GET' })).toBe(true)
    expect(origemAceita({ origem: null, propriaOrigem: propria, metodo: 'HEAD' })).toBe(true)
  })

  it('recusa ausencia de `Origin` em mutacao', () => {
    // `fetch` de mesma origem com metodo inseguro SEMPRE manda `Origin`,
    // entao a ausencia aqui nao custa nada ao cliente legitimo.
    for (const metodo of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      expect(origemAceita({ origem: null, propriaOrigem: propria, metodo })).toBe(false)
    }
  })

  it('recusa a origem opaca `"null"`, que iframe em sandbox envia', () => {
    expect(origemAceita({ origem: 'null', propriaOrigem: propria, metodo: 'GET' })).toBe(false)
  })

  it('recusa origem que so difere no esquema ou na porta', () => {
    expect(origemAceita({ origem: 'http://painel.exemplo.com', propriaOrigem: propria, metodo: 'GET' }))
      .toBe(false)
    expect(
      origemAceita({ origem: 'https://painel.exemplo.com:8443', propriaOrigem: propria, metodo: 'GET' }),
    ).toBe(false)
  })
})

describe('idDeRequisicao', () => {
  it('propaga o id de entrada quando a forma e aceitavel', () => {
    expect(idDeRequisicao('01JB2Z3K4M5N6P7Q8R9S')).toBe('01JB2Z3K4M5N6P7Q8R9S')
    expect(idDeRequisicao('3f1a2b4c-5d6e-7f80-9a1b-2c3d4e5f6071')).toBe(
      '3f1a2b4c-5d6e-7f80-9a1b-2c3d4e5f6071',
    )
  })

  it('gera um id novo quando nao ha entrada', () => {
    expect(idDeRequisicao(null)).toMatch(/^[0-9a-f-]{36}$/)
    expect(idDeRequisicao(undefined)).toMatch(/^[0-9a-f-]{36}$/)
    expect(idDeRequisicao('')).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('SUBSTITUI em vez de recusar quando a entrada e malformada', () => {
    // Substituir e nao recusar: o cliente nao deve perder a requisicao por
    // causa de um header de diagnostico. Mas propagar sem olhar seria deixar
    // entrada nao confiavel escrever no log de quem esta do outro lado.
    expect(idDeRequisicao('tem espaco')).toMatch(/^[0-9a-f-]{36}$/)
    expect(idDeRequisicao('quebra\nde\nlinha')).toMatch(/^[0-9a-f-]{36}$/)
    expect(idDeRequisicao('a'.repeat(201))).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('aceita exatamente 200 caracteres e recusa 201', () => {
    expect(idDeRequisicao('a'.repeat(200))).toBe('a'.repeat(200))
    expect(idDeRequisicao('a'.repeat(201))).not.toBe('a'.repeat(201))
  })
})
