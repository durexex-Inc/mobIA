import { describe, expect, it } from 'vitest'

import {
  CAPACIDADE_MAXIMA,
  type Corretor,
  estaSujo,
  formularioDe,
  formularioValido,
  pedidoDeCadastro,
  pedidoDeEdicao,
  recusaDe,
  validarFormulario,
} from './corretores'

const CORRETOR: Corretor = {
  id: 'c-1',
  nome: 'Ana Souza',
  email: 'ana@imobiliaria.com',
  telefone: '11999998888',
  creci: '12345-F',
  especialidades: ['COMPRA', 'ALUGUEL'],
  regioesAtuacao: ['Centro', 'Zona Sul'],
  horarioInicio: 8,
  horarioFim: 18,
  capacidadeDiaria: 5,
  plantao: false,
  gerente: false,
  ativo: true,
}

describe('formularioDe', () => {
  it('traz o corretor para texto', () => {
    expect(formularioDe(CORRETOR)).toEqual({
      nome: 'Ana Souza',
      email: 'ana@imobiliaria.com',
      telefone: '11999998888',
      creci: '12345-F',
      especialidades: ['COMPRA', 'ALUGUEL'],
      regioesAtuacao: ['Centro', 'Zona Sul'],
      horarioInicio: '8',
      horarioFim: '18',
      capacidadeDiaria: '5',
      plantao: false,
    })
  })

  it('sem corretor (cadastro), tudo vazio', () => {
    const formulario = formularioDe(null)
    expect(formulario.nome).toBe('')
    expect(formulario.especialidades).toEqual([])
    expect(formulario.regioesAtuacao).toEqual([])
    expect(formulario.plantao).toBe(false)
  })

  it('creci nulo vira string vazia', () => {
    expect(formularioDe({ ...CORRETOR, creci: null }).creci).toBe('')
  })
})

describe('validarFormulario / formularioValido (D3)', () => {
  const valido = formularioDe(CORRETOR)

  it('formulario completo e valido', () => {
    expect(formularioValido(valido)).toBe(true)
  })

  it('capacidade 21 e recusada -- o teto so existe aqui, nao no backend', () => {
    const recusa = validarFormulario({ ...valido, capacidadeDiaria: '21' })
    expect(recusa.porCampo.capacidadeDiaria).toMatch(new RegExp(`entre 1 e ${CAPACIDADE_MAXIMA}`))
  })

  it('capacidade 0 e recusada', () => {
    expect(validarFormulario({ ...valido, capacidadeDiaria: '0' }).porCampo.capacidadeDiaria).toBeDefined()
  })

  it('capacidade 1 e 20 sao aceitas', () => {
    expect(formularioValido({ ...valido, capacidadeDiaria: '1' })).toBe(true)
    expect(formularioValido({ ...valido, capacidadeDiaria: '20' })).toBe(true)
  })

  it('horario com fim antes do inicio e recusado', () => {
    expect(
      validarFormulario({ ...valido, horarioInicio: '18', horarioFim: '8' }).porCampo.horarioFim,
    ).toBeDefined()
  })

  it('horario com fim igual ao inicio e recusado (janela de duracao zero)', () => {
    expect(
      validarFormulario({ ...valido, horarioInicio: '8', horarioFim: '8' }).porCampo.horarioFim,
    ).toBeDefined()
  })

  it('sem nome, sem email, sem telefone: cada um recusa o proprio campo', () => {
    const recusa = validarFormulario({ ...valido, nome: '  ', email: '', telefone: '' })
    expect(recusa.porCampo.nome).toBeDefined()
    expect(recusa.porCampo.email).toBeDefined()
    expect(recusa.porCampo.telefone).toBeDefined()
  })

  it('sem especialidade e sem regiao: cada um recusa o proprio campo', () => {
    const recusa = validarFormulario({ ...valido, especialidades: [], regioesAtuacao: [] })
    expect(recusa.porCampo.especialidades).toBeDefined()
    expect(recusa.porCampo.regioesAtuacao).toBeDefined()
  })

  it('regiao so com espaco nao conta', () => {
    expect(validarFormulario({ ...valido, regioesAtuacao: ['   '] }).porCampo.regioesAtuacao).toBeDefined()
  })
})

describe('pedidoDeCadastro', () => {
  it('monta o corpo completo do POST, sem `gerente` (D4)', () => {
    const corpo = pedidoDeCadastro(formularioDe(CORRETOR))
    expect(corpo).toEqual({
      nome: 'Ana Souza',
      email: 'ana@imobiliaria.com',
      telefone: '11999998888',
      creci: '12345-F',
      especialidades: ['COMPRA', 'ALUGUEL'],
      regioesAtuacao: ['Centro', 'Zona Sul'],
      horarioInicio: 8,
      horarioFim: 18,
      capacidadeDiaria: 5,
      plantao: false,
    })
    expect(corpo).not.toHaveProperty('gerente')
  })

  it('creci vazio vira null', () => {
    expect(pedidoDeCadastro({ ...formularioDe(CORRETOR), creci: '  ' }).creci).toBeNull()
  })
})

describe('pedidoDeEdicao / estaSujo', () => {
  const inicial = formularioDe(CORRETOR)

  it('so o que mudou vai', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, nome: 'Ana Paula Souza' })).toEqual({
      nome: 'Ana Paula Souza',
    })
  })

  it('sem mudanca, corpo vazio e nao esta sujo', () => {
    expect(pedidoDeEdicao(inicial, inicial)).toEqual({})
    expect(estaSujo(inicial, inicial)).toBe(false)
  })

  it('espaco a mais nao e mudanca', () => {
    expect(estaSujo(inicial, { ...inicial, nome: ' Ana Souza ' })).toBe(false)
  })

  it('reordenar especialidades sem mudar o conjunto nao e mudanca', () => {
    expect(
      estaSujo(inicial, { ...inicial, especialidades: ['ALUGUEL', 'COMPRA'] }),
    ).toBe(false)
  })

  it('mudar o conjunto de especialidades entra no corpo', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, especialidades: ['COMPRA'] })).toEqual({
      especialidades: ['COMPRA'],
    })
  })

  it('mudar so o horarioInicio manda os dois campos, porque a jornada se edita em par', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, horarioInicio: '9' })).toEqual({
      horarioInicio: 9,
      horarioFim: 18,
    })
  })

  it('capacidade muda como numero', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, capacidadeDiaria: '10' })).toEqual({
      capacidadeDiaria: 10,
    })
  })

  it('`gerente` nunca entra no corpo (D4), mesmo sem campo correspondente no formulario', () => {
    const corpo = pedidoDeEdicao(inicial, { ...inicial, nome: 'Outra' })
    expect(corpo).not.toHaveProperty('gerente')
  })

  it('esvaziar o creci vai como null', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, creci: '' })).toEqual({ creci: null })
  })

  it('regiao nova entra na lista', () => {
    expect(
      pedidoDeEdicao(inicial, { ...inicial, regioesAtuacao: [...inicial.regioesAtuacao, 'Norte'] }),
    ).toEqual({ regioesAtuacao: ['Centro', 'Zona Sul', 'Norte'] })
  })

  it('plantao muda como booleano', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, plantao: true })).toEqual({ plantao: true })
  })
})

describe('recusaDe', () => {
  it('409 de e-mail duplicado vira erro do campo email (D9)', () => {
    expect(recusaDe(409, 'e-mail ja cadastrado')).toEqual({
      porCampo: { email: 'Este e-mail já está cadastrado.' },
      geral: null,
    })
  })

  it('422 do pydantic vai para o campo do loc', () => {
    const recusa = recusaDe(422, [
      { type: 'greater_than_equal', loc: ['body', 'capacidadeDiaria'], msg: 'x', ctx: { ge: 1 } },
    ])
    expect(recusa.porCampo.capacidadeDiaria).toBe('Deve ser no mínimo 1.')
  })

  it('422 com loc fora do formulario vai para o topo', () => {
    expect(recusaDe(422, [{ type: 'extra_forbidden', loc: ['body', 'gerente'], msg: 'Extra' }])).toEqual({
      porCampo: {},
      geral: 'Extra',
    })
  })

  it('401, 403, 404 e generico', () => {
    expect(recusaDe(401, null).geral).toMatch(/sessão terminou/)
    expect(recusaDe(403, null).geral).toMatch(/permissão/)
    expect(recusaDe(404, null).geral).toMatch(/não existe mais/)
    expect(recusaDe(500, null).geral).toBe('Não foi possível salvar. Tente de novo.')
  })
})
