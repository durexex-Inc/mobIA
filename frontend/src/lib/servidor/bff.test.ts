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
    // `corretores` entrou na tabela na TEC-332 e `imoveis` na TEC-333 -- ver
    // os describes dedicados abaixo. `importacoes` SEM id continua fora: a
    // D7 do desenho da TEC-333 recusou de proposito, e a D6 da TEC-334 (ver
    // o describe "importacao de imoveis" abaixo) so acrescenta `importacoes/*`
    // -- a listagem SEM id continua so acessivel direto do servidor (D4).
    expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis', 'importacoes'])).toBeNull()
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

    it('assumir e devolver passam como POST, e so como POST (TEC-327)', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'assumir'])).toBe(
        `/api/v1/leads/${LEAD}/assumir`,
      )
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'devolver'])).toBe(
        `/api/v1/leads/${LEAD}/devolver`,
      )
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD, 'assumir'])).toBeNull()
    })

    it('a revelacao entra so como `POST` (TEC-330)', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'revelar'])).toBe(
        `/api/v1/leads/${LEAD}/revelar`,
      )
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD, 'revelar'])).toBeNull()
    })

    it('a resposta do corretor entra como `POST` das mensagens (TEC-328)', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'mensagens'])).toBe(
        `/api/v1/leads/${LEAD}/mensagens`,
      )
      expect(caminhoPermitido('PUT', ['api', 'v1', 'leads', LEAD, 'mensagens'])).toBeNull()
    })

    it('a regeneracao do resumo entra como `POST` do handoff (TEC-326)', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'handoffs', LEAD, 'resumo'])).toBe(
        `/api/v1/handoffs/${LEAD}/resumo`,
      )
      expect(caminhoPermitido('GET', ['api', 'v1', 'handoffs', LEAD, 'resumo'])).toBeNull()
      expect(caminhoPermitido('POST', ['api', 'v1', 'handoffs', LEAD, 'aceitar'])).toBeNull()
    })

    it('a correcao da qualificacao entra so como `PATCH` (TEC-329)', () => {
      expect(caminhoPermitido('PATCH', ['api', 'v1', 'leads', LEAD, 'qualificacao'])).toBe(
        `/api/v1/leads/${LEAD}/qualificacao`,
      )
      expect(caminhoPermitido('POST', ['api', 'v1', 'leads', LEAD, 'qualificacao'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD, 'qualificacao'])).toBeNull()
    })

    it('a eliminacao dos dados do titular entra so como `DELETE` (TEC-342)', () => {
      expect(caminhoPermitido('DELETE', ['api', 'v1', 'leads', LEAD, 'dados-pessoais'])).toBe(
        `/api/v1/leads/${LEAD}/dados-pessoais`,
      )
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD, 'dados-pessoais'])).toBeNull()
    })

    it('o `*` nao abre as outras rotas do lead', () => {
      // O detalhe e a lista continuam fora do alcance do navegador: quem os
      // le e o Server Component.
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', LEAD])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads'])).toBeNull()
    })

    it('o `*` casa um segmento so, e nunca `..`', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', '..', 'mensagens'])).toBeNull()
      expect(caminhoPermitido('GET', ['api', 'v1', 'leads', 'a', 'b', 'mensagens'])).toBeNull()
    })
  })

  describe('corretores (TEC-332)', () => {
    const CORRETOR = '6f1c2a4e-0000-4000-8000-000000000002'

    it('listar e cadastrar entram no caminho sem id', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'corretores'])).toBe('/api/v1/corretores')
      expect(caminhoPermitido('POST', ['api', 'v1', 'corretores'])).toBe('/api/v1/corretores')
      expect(caminhoPermitido('PATCH', ['api', 'v1', 'corretores'])).toBeNull()
      expect(caminhoPermitido('DELETE', ['api', 'v1', 'corretores'])).toBeNull()
    })

    it('obter e editar entram no caminho com id, com o `*` casando', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'corretores', CORRETOR])).toBe(
        `/api/v1/corretores/${CORRETOR}`,
      )
      expect(caminhoPermitido('PATCH', ['api', 'v1', 'corretores', CORRETOR])).toBe(
        `/api/v1/corretores/${CORRETOR}`,
      )
    })

    it('nao ha DELETE: desativar e PATCH com `{ ativo: false }` (D6 da TEC-196)', () => {
      expect(caminhoPermitido('DELETE', ['api', 'v1', 'corretores', CORRETOR])).toBeNull()
    })

    it('POST com id e GET/PATCH sem id nao casam -- a entrada da tabela e o par', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'corretores', CORRETOR])).toBeNull()
    })
  })

  describe('imoveis (TEC-333)', () => {
    const IMOVEL = '6f1c2a4e-0000-4000-8000-000000000003'

    it('listar e cadastrar entram no caminho sem id', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis'])).toBe('/api/v1/imoveis')
      expect(caminhoPermitido('POST', ['api', 'v1', 'imoveis'])).toBe('/api/v1/imoveis')
      expect(caminhoPermitido('PATCH', ['api', 'v1', 'imoveis'])).toBeNull()
      expect(caminhoPermitido('DELETE', ['api', 'v1', 'imoveis'])).toBeNull()
    })

    it('editar e retirar entram no caminho com id, com o `*` casando', () => {
      expect(caminhoPermitido('PATCH', ['api', 'v1', 'imoveis', IMOVEL])).toBe(
        `/api/v1/imoveis/${IMOVEL}`,
      )
      expect(caminhoPermitido('DELETE', ['api', 'v1', 'imoveis', IMOVEL])).toBe(
        `/api/v1/imoveis/${IMOVEL}`,
      )
    })

    it('nao ha GET com id -- a edicao parte do que a listagem ja carregou (D7)', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis', IMOVEL])).toBeNull()
    })

    it('POST com id e GET/PATCH/DELETE sem id nao casam -- a entrada da tabela e o par', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'imoveis', IMOVEL])).toBeNull()
    })
  })

  describe('importacao de imoveis (TEC-334)', () => {
    const IMPORTACAO = '6f1c2a4e-0000-4000-8000-000000000004'

    it('o envio do arquivo entra como POST em `importar`, segmento LITERAL', () => {
      expect(caminhoPermitido('POST', ['api', 'v1', 'imoveis', 'importar'])).toBe(
        '/api/v1/imoveis/importar',
      )
    })

    it('`importar` nao casa com metodo diferente de POST', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis', 'importar'])).toBeNull()
    })

    it('o acompanhamento entra como GET em `importacoes/*`, com o `*` casando o id', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis', 'importacoes', IMPORTACAO])).toBe(
        `/api/v1/imoveis/importacoes/${IMPORTACAO}`,
      )
    })

    it('`importacoes/*` nao casa com metodo diferente de GET', () => {
      expect(
        caminhoPermitido('POST', ['api', 'v1', 'imoveis', 'importacoes', IMPORTACAO]),
      ).toBeNull()
    })

    it('a listagem sem id continua fora do alcance do navegador -- so a mais recente do servidor (D4)', () => {
      expect(caminhoPermitido('GET', ['api', 'v1', 'imoveis', 'importacoes'])).toBeNull()
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
