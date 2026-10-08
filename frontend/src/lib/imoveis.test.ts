import { describe, expect, it } from 'vitest'

import {
  estaSujo,
  formularioDe,
  formularioValido,
  type Imovel,
  pedidoDeCadastro,
  pedidoDeEdicao,
  recusaDe,
  totalMensalEstimado,
  validarFormulario,
} from './imoveis'

const IMOVEL: Imovel = {
  id: 'i-1',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos, reformado',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  status: 'DISPONIVEL',
  precoVenda: 35_000_000,
  precoAluguel: null,
  condominio: 85_000,
  iptuMensal: null,
  bairro: 'Centro',
  cidade: 'Porto Alegre',
  uf: 'RS',
  zona: null,
  latitude: null,
  longitude: null,
  areaUtilM2: 70,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  caracteristicas: ['Vista para o parque'],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

describe('formularioDe', () => {
  it('traz o imovel para texto, precos em reais', () => {
    expect(formularioDe(IMOVEL)).toEqual({
      codigo: 'AP-001',
      titulo: 'Apartamento no Centro',
      descricao: 'Dois quartos, reformado',
      tipo: 'APARTAMENTO',
      operacao: 'VENDA',
      status: 'DISPONIVEL',
      precoVenda: '350000',
      precoAluguel: '',
      condominio: '850',
      iptuMensal: '',
      bairro: 'Centro',
      cidade: 'Porto Alegre',
      uf: 'RS',
      areaUtilM2: '70',
      quartos: '2',
      suites: '1',
      banheiros: '2',
      vagas: '1',
      caracteristicas: ['Vista para o parque'],
    })
  })

  it('sem imovel (cadastro), tudo vazio', () => {
    const formulario = formularioDe(null)
    expect(formulario.codigo).toBe('')
    expect(formulario.tipo).toBe('')
    expect(formulario.caracteristicas).toEqual([])
  })
})

describe('validarFormulario / formularioValido (D2)', () => {
  const valido = formularioDe(IMOVEL)

  it('formulario completo e valido', () => {
    expect(formularioValido(valido)).toBe(true)
  })

  it('so checa campo vazio, sem faixa nem plausibilidade -- essas sao do backend', () => {
    // Um valor absurdo passa na validacao do cliente: e o backend quem
    // recusaria com a mensagem de faixa (D2 do desenho).
    expect(formularioValido({ ...valido, areaUtilM2: '99999999' })).toBe(true)
  })

  it('cada obrigatorio ausente recusa o proprio campo', () => {
    const recusa = validarFormulario({
      ...valido,
      codigo: '',
      titulo: '',
      descricao: '',
      bairro: '',
      cidade: '',
      uf: '',
      areaUtilM2: '',
      quartos: '',
      suites: '',
      banheiros: '',
      vagas: '',
      tipo: '',
      operacao: '',
      status: '',
    })
    expect(recusa.porCampo.codigo).toBeDefined()
    expect(recusa.porCampo.titulo).toBeDefined()
    expect(recusa.porCampo.descricao).toBeDefined()
    expect(recusa.porCampo.bairro).toBeDefined()
    expect(recusa.porCampo.cidade).toBeDefined()
    expect(recusa.porCampo.uf).toBeDefined()
    expect(recusa.porCampo.areaUtilM2).toBeDefined()
    expect(recusa.porCampo.quartos).toBeDefined()
    expect(recusa.porCampo.suites).toBeDefined()
    expect(recusa.porCampo.banheiros).toBeDefined()
    expect(recusa.porCampo.vagas).toBeDefined()
    expect(recusa.porCampo.tipo).toBeDefined()
    expect(recusa.porCampo.operacao).toBeDefined()
    expect(recusa.porCampo.status).toBeDefined()
  })

  it('operacao VENDA exige precoVenda, nao precoAluguel', () => {
    const recusa = validarFormulario({ ...valido, operacao: 'VENDA', precoVenda: '' })
    expect(recusa.porCampo.precoVenda).toBeDefined()
    expect(recusa.porCampo.precoAluguel).toBeUndefined()
  })

  it('operacao ALUGUEL exige precoAluguel, nao precoVenda', () => {
    const recusa = validarFormulario({
      ...valido,
      operacao: 'ALUGUEL',
      precoVenda: '',
      precoAluguel: '',
    })
    expect(recusa.porCampo.precoAluguel).toBeDefined()
  })

  it('operacao AMBOS exige ao menos um dos dois precos', () => {
    const semNenhum = validarFormulario({
      ...valido,
      operacao: 'AMBOS',
      precoVenda: '',
      precoAluguel: '',
    })
    expect(semNenhum.porCampo.precoVenda).toBeDefined()

    const soAluguel = validarFormulario({
      ...valido,
      operacao: 'AMBOS',
      precoVenda: '',
      precoAluguel: '2000',
    })
    expect(soAluguel.porCampo.precoVenda).toBeUndefined()
  })

  it('caracteristicas vazio nao recusa -- diferencial e opcional', () => {
    expect(formularioValido({ ...valido, caracteristicas: [] })).toBe(true)
  })
})

describe('pedidoDeCadastro', () => {
  it('monta o corpo completo do POST, precos em centavos', () => {
    const corpo = pedidoDeCadastro(formularioDe(IMOVEL))
    expect(corpo).toEqual({
      codigo: 'AP-001',
      titulo: 'Apartamento no Centro',
      descricao: 'Dois quartos, reformado',
      tipo: 'APARTAMENTO',
      operacao: 'VENDA',
      status: 'DISPONIVEL',
      precoVenda: 35_000_000,
      precoAluguel: null,
      condominio: 85_000,
      iptuMensal: null,
      bairro: 'Centro',
      cidade: 'Porto Alegre',
      uf: 'RS',
      areaUtilM2: 70,
      quartos: 2,
      suites: 1,
      banheiros: 2,
      vagas: 1,
      caracteristicas: ['Vista para o parque'],
    })
  })

  it('sem zona, latitude, longitude ou fotos (D1)', () => {
    const corpo = pedidoDeCadastro(formularioDe(IMOVEL))
    expect(corpo).not.toHaveProperty('zona')
    expect(corpo).not.toHaveProperty('latitude')
    expect(corpo).not.toHaveProperty('longitude')
    expect(corpo).not.toHaveProperty('fotos')
  })

  it('leva o IPTU em centavos quando preenchido (TEC-400)', () => {
    const corpo = pedidoDeCadastro({ ...formularioDe(IMOVEL), iptuMensal: '320.50' })
    expect(corpo.iptuMensal).toBe(32_050)
  })
})

describe('totalMensalEstimado (TEC-400)', () => {
  const base = formularioDe(IMOVEL)

  it('soma aluguel, condominio e IPTU, em reais', () => {
    expect(totalMensalEstimado({ ...base, precoAluguel: '4500', condominio: '850', iptuMensal: '320.5' })).toBe(5670.5)
  })

  it('sem preco de aluguel nao ha total', () => {
    expect(totalMensalEstimado({ ...base, precoAluguel: '' })).toBeNull()
  })

  it('campo vazio ou nao numerico conta zero', () => {
    expect(totalMensalEstimado({ ...base, precoAluguel: '4500', condominio: '', iptuMensal: 'abc' })).toBe(4500)
  })
})

describe('pedidoDeEdicao / estaSujo', () => {
  const inicial = formularioDe(IMOVEL)

  it('IPTU mudado vai em centavos (TEC-400)', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, iptuMensal: '210' })).toEqual({ iptuMensal: 21_000 })
  })

  it('so o que mudou vai', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, titulo: 'Novo título' })).toEqual({
      titulo: 'Novo título',
    })
  })

  it('sem mudanca, corpo vazio e nao esta sujo', () => {
    expect(pedidoDeEdicao(inicial, inicial)).toEqual({})
    expect(estaSujo(inicial, inicial)).toBe(false)
  })

  it('alterar so o preco (D3, cenario 1) manda so o preco', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, precoVenda: '400000' })).toEqual({
      precoVenda: 40_000_000,
    })
  })

  it('alterar so o diferencial (D3, cenario 2) manda so caracteristicas', () => {
    expect(
      pedidoDeEdicao(inicial, { ...inicial, caracteristicas: ['Vista para o mar'] }),
    ).toEqual({ caracteristicas: ['Vista para o mar'] })
  })

  it('codigo nunca entra no corpo, mesmo quando o valor "muda" na chamada (D5)', () => {
    const corpo = pedidoDeEdicao(inicial, { ...inicial, codigo: 'OUTRO-CODIGO' })
    expect(corpo).not.toHaveProperty('codigo')
  })

  it('alterar status manda o novo status', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, status: 'RESERVADO' })).toEqual({
      status: 'RESERVADO',
    })
  })
})

describe('recusaDe (D2)', () => {
  it('422 com string do backend vai inteira para o aviso geral, sem por campo', () => {
    const recusa = recusaDe(422, 'titulo ausente; bairro ausente')
    expect(recusa).toEqual({ porCampo: {}, geral: 'titulo ausente; bairro ausente' })
  })

  it('409 de codigo duplicado tambem vai inteiro para o aviso geral', () => {
    expect(recusaDe(409, "codigo 'AP-001' ja cadastrado")).toEqual({
      porCampo: {},
      geral: "codigo 'AP-001' ja cadastrado",
    })
  })

  it('401, 403, 404 e generico', () => {
    expect(recusaDe(401, null).geral).toMatch(/sessão terminou/)
    expect(recusaDe(403, null).geral).toMatch(/permissão/)
    expect(recusaDe(404, null).geral).toMatch(/não existe mais/)
    expect(recusaDe(500, null).geral).toBe('Não foi possível salvar. Tente de novo.')
  })
})
