import { describe, expect, it } from 'vitest'

import {
  dividirResumo,
  faixaDePreco,
  humanizar,
  linhasDaQualificacao,
  motivosDoRecalculo,
  pontosDoGrafico,
  reacaoLegivel,
  resumoDoGrafico,
  statusDoAgendamento,
  tipoDoAgendamento,
  valorDoRecalculo,
} from './detalhe'

/** O texto como a TEC-175 o grava: seis marcadores literais, em ordem. */
const RESUMO_DO_ASSISTENTE = [
  '## Quem e o lead',
  'Lead do WhatsApp desde 20/09.',
  '',
  '## O que procura',
  'Apartamento de 2 quartos no Centro.',
  '## Score e temperatura',
  '82, quente.',
  '## Imoveis apresentados',
  'AP-101, gostou.',
  '## Pontos de atencao',
  'Recusou informar renda.',
  '## Proxima acao',
  'Ligar hoje.',
].join('\n')

describe('dividirResumo', () => {
  it('corta o texto nos seis marcadores, com os titulos em portugues com acento', () => {
    const resumo = dividirResumo(RESUMO_DO_ASSISTENTE, { fallback: false })

    expect(resumo?.blocos.map((bloco) => bloco.titulo)).toEqual([
      'Quem é o lead',
      'O que procura',
      'Score e temperatura',
      'Imóveis apresentados',
      'Pontos de atenção',
      'Próxima ação',
    ])
    expect(resumo?.blocos[0].corpo).toBe('Lead do WhatsApp desde 20/09.')
    expect(resumo?.blocos[5].corpo).toBe('Ligar hoje.')
  })

  it('no resumo simplificado, o preambulo entre colchetes some: a etiqueta diz o mesmo', () => {
    const texto = `[resumo automatico simplificado -- o modelo nao gerou]\n\n${RESUMO_DO_ASSISTENTE}`

    expect(dividirResumo(texto, { fallback: true })?.preambulo).toBe('')
  })

  it('no resumo do assistente, um preambulo inesperado continua visivel', () => {
    const texto = `Nota inicial.\n${RESUMO_DO_ASSISTENTE}`

    expect(dividirResumo(texto, { fallback: false })?.preambulo).toBe('Nota inicial.')
  })

  it('texto sem os marcadores nao se deixa cortar: `null`, e a tela mostra o texto inteiro', () => {
    expect(dividirResumo('um resumo qualquer', { fallback: false })).toBeNull()
  })

  it('marcadores fora de ordem tambem nao se cortam', () => {
    const trocado = RESUMO_DO_ASSISTENTE.replace('## Quem e o lead', '## X').replace(
      '## Proxima acao',
      '## Quem e o lead',
    )
    expect(dividirResumo(trocado, { fallback: false })).toBeNull()
  })
})

describe('faixaDePreco', () => {
  it('em reais, a partir dos centavos', () => {
    expect(faixaDePreco(50_000_000, 80_000_000)).toBe('R$ 500.000 a R$ 800.000')
  })

  it('aberta de um lado', () => {
    expect(faixaDePreco(50_000_000, null)).toBe('a partir de R$ 500.000')
    expect(faixaDePreco(null, 80_000_000)).toBe('até R$ 800.000')
  })

  it('sem nenhum dos dois, nula', () => {
    expect(faixaDePreco(null, null)).toBeNull()
  })
})

describe('humanizar', () => {
  it('transforma o identificador em texto', () => {
    expect(humanizar('LONGO_PRAZO')).toBe('Longo prazo')
  })
})

describe('linhasDaQualificacao', () => {
  const rotulos = (linhas: { rotulo: string }[]) => linhas.map((linha) => linha.rotulo)

  it('os campos-base aparecem sempre, com "Não informado" no que falta', () => {
    const linhas = linhasDaQualificacao({ intencao: 'COMPRA', regiao: 'Centro' })

    expect(linhas.find((l) => l.rotulo === 'Intenção')?.valor).toBe('Compra')
    expect(linhas.find((l) => l.rotulo === 'Região')?.valor).toBe('Centro')
    expect(linhas.find((l) => l.rotulo === 'Quartos')?.valor).toBe('Não informado')
  })

  it('traduz o vocabulario do agente', () => {
    const linhas = linhasDaQualificacao({
      tipoImovel: 'APARTAMENTO',
      urgencia: 'ATE_3_MESES',
      formaPagamento: 'A_VISTA',
      temImovelParaVender: false,
    })

    expect(linhas.find((l) => l.rotulo === 'Tipo de imóvel')?.valor).toBe('Apartamento')
    expect(linhas.find((l) => l.rotulo === 'Urgência')?.valor).toBe('Até 3 meses')
    expect(linhas.find((l) => l.rotulo === 'Forma de pagamento')?.valor).toBe('À vista')
    expect(linhas.find((l) => l.rotulo === 'Tem imóvel para vender')?.valor).toBe('Não')
  })

  it('os campos de investidor so aparecem quando algum esta preenchido', () => {
    expect(rotulos(linhasDaQualificacao({ intencao: 'COMPRA' }))).not.toContain('Horizonte')

    const investidor = linhasDaQualificacao({ horizonte: 'LONGO_PRAZO' })
    expect(investidor.find((l) => l.rotulo === 'Horizonte')?.valor).toBe('Longo prazo')
    expect(rotulos(investidor)).toContain('Ticket de investimento')
  })

  it('o que o lead recusou informar vira uma linha propria', () => {
    const linhas = linhasDaQualificacao({ camposRecusados: ['renda', 'prazo'] })

    expect(linhas.find((l) => l.rotulo === 'Recusou informar')?.valor).toBe('renda, prazo')
  })

  it('sem recusa, a linha nao aparece', () => {
    expect(rotulos(linhasDaQualificacao({ camposRecusados: [] }))).not.toContain(
      'Recusou informar',
    )
  })
})

describe('agendamentos', () => {
  it('traduz tipo e status', () => {
    expect(tipoDoAgendamento('VISITA_PRESENCIAL')).toBe('Visita presencial')
    expect(statusDoAgendamento('NO_SHOW')).toBe('Não compareceu')
  })
})

describe('historico de score (TEC-325)', () => {
  it('o valor mostra de onde veio, e o primeiro calculo so o numero', () => {
    expect(valorDoRecalculo({ anterior: null, novo: 30 })).toBe('30')
    expect(valorDoRecalculo({ anterior: 30, novo: 47 })).toBe('30 → 47')
  })

  it('os motivos saem em portugues; causa desconhecida, humanizada', () => {
    expect(motivosDoRecalculo(['CAMPOS_OBRIGATORIOS', 'URGENCIA'])).toBe('Campos da qualificação, Urgência')
    expect(motivosDoRecalculo(['CAUSA_NOVA'])).toBe('Causa nova')
  })

  it('os pontos vao de 0 a 100 no Y, espacados por igual no X', () => {
    const caixa = { largura: 120, altura: 120, margem: 10 }
    expect(pontosDoGrafico([0, 50, 100], caixa)).toEqual([
      { x: 10, y: 110 },
      { x: 60, y: 60 },
      { x: 110, y: 10 },
    ])
    expect(pontosDoGrafico([40], caixa)).toEqual([{ x: 60, y: 70 }])
  })

  it('o resumo do grafico e o que o leitor de tela ouve', () => {
    expect(resumoDoGrafico([30, 47, 82])).toBe('Score de 30 a 82 em 3 recálculos')
    expect(resumoDoGrafico([30])).toBe('Score 30 no único cálculo')
  })
})

describe('reacao ao imovel (TEC-325)', () => {
  it('os rotulos do chat web, com a categoria do descarte', () => {
    expect(reacaoLegivel('INTERESSE', null)).toBe('Gostei')
    expect(reacaoLegivel('DESCARTE', 'DISTANCIA')).toBe('Não é pra mim · distância')
    expect(reacaoLegivel('DESCARTE', null)).toBe('Não é pra mim')
    expect(reacaoLegivel(null, null)).toBe('Aguardando reação')
  })
})
