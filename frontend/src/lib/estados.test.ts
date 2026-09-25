import { describe, expect, it } from 'vitest'

import { estadoDe, TEXTO_SEM_FONTE, TEXTO_VAZIO } from './estados'

describe('estadoDe', () => {
  it('trata zero como dado medido, e nao como ausencia', () => {
    // O coracao da card. Zero lead qualificado no periodo e uma MEDICAO; se
    // virasse "vazio" ou "sem fonte", o painel esconderia um numero verdadeiro.
    expect(estadoDe({ valor: 0, disponivel: true })).toBe('com_dados')
  })

  it('sem fonte decide sozinho, mesmo com valor presente', () => {
    // A ordem dos testes dentro de `estadoDe` e a regra. Um indicador sem
    // fonte que chegasse com `valor: 0` -- por default de serializacao, por um
    // COALESCE que alguem acrescente -- continua sendo "sem fonte". Este teste
    // reprova se alguem inverter as duas primeiras checagens.
    expect(estadoDe({ valor: 0, disponivel: false })).toBe('sem_fonte')
    expect(estadoDe({ valor: 42, disponivel: false })).toBe('sem_fonte')
    expect(estadoDe({ valor: null, disponivel: false })).toBe('sem_fonte')
  })

  it('nulo com fonte e coorte vazia', () => {
    expect(estadoDe({ valor: null, disponivel: true })).toBe('vazio')
  })

  it('objeto vazio e coorte vazia, e nao distribuicao de zero faixas', () => {
    // Sem isto o cartao sai em branco, e branco na tela parece painel
    // quebrado -- nao ausencia de lead.
    expect(estadoDe({ valor: {}, disponivel: true })).toBe('vazio')
  })

  it('distribuicao com faixas e dado', () => {
    expect(estadoDe({ valor: { QUENTE: 3 }, disponivel: true })).toBe('com_dados')
  })
})

describe('os textos das duas ausencias', () => {
  it('sao diferentes, porque as causas e os consertos sao diferentes', () => {
    // "Ainda nao medido" e defeito do sistema (RF-12 conserta); "sem dados no
    // periodo" e fato do negocio. Um texto so mandaria a gerente procurar um
    // problema que nao existe, ou ignorar um que existe.
    expect(TEXTO_SEM_FONTE).not.toBe(TEXTO_VAZIO)
  })

  it('nenhum dos dois contem um digito', () => {
    // Asserta de ausencia que PODE reprovar (a regra da TEC-289): se alguem
    // trocar o texto por algo como "0 medidos", o primeiro cenario do Gherkin
    // -- "o numero 0 nao aparece em lugar nenhum daquele cartao" -- passaria a
    // ser violado pelo proprio rotulo.
    expect(TEXTO_SEM_FONTE).not.toMatch(/\d/)
    expect(TEXTO_VAZIO).not.toMatch(/\d/)
  })
})
