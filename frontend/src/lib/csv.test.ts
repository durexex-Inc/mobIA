import { describe, expect, it } from 'vitest'

import { linhasParaCsv, previaDoCsv } from './csv'

describe('previaDoCsv', () => {
  it('escolhe `,` quando o cabecalho nao tem `;`', () => {
    const previa = previaDoCsv('codigo,titulo,cidade\nAP-1,Casa,POA\nAP-2,Apto,POA')

    expect(previa.colunas).toEqual(['codigo', 'titulo', 'cidade'])
    expect(previa.linhas).toEqual([
      ['AP-1', 'Casa', 'POA'],
      ['AP-2', 'Apto', 'POA'],
    ])
  })

  it('escolhe `;` quando ele aparece MAIS vezes que `,` no cabecalho (Excel pt-BR)', () => {
    const previa = previaDoCsv('codigo;titulo;cidade\nAP-1;Casa;POA')

    expect(previa.colunas).toEqual(['codigo', 'titulo', 'cidade'])
    expect(previa.linhas).toEqual([['AP-1', 'Casa', 'POA']])
  })

  it('empate entre `;` e `,` fica com `,`, igual ao parser real', () => {
    // Cabecalho sem nenhum dos dois: count(';') === count(',') === 0.
    const previa = previaDoCsv('codigo\nAP-1')
    expect(previa.colunas).toEqual(['codigo'])
  })

  it('come o BOM quando o arquivo o tem', () => {
    const comBom = '﻿codigo,titulo\nAP-1,Casa'
    const previa = previaDoCsv(comBom)

    expect(previa.colunas).toEqual(['codigo', 'titulo'])
  })

  it('sem BOM continua identico', () => {
    const previa = previaDoCsv('codigo,titulo\nAP-1,Casa')
    expect(previa.colunas).toEqual(['codigo', 'titulo'])
  })

  it('mostra so as 10 primeiras linhas de DADOS, mesmo com mais no arquivo', () => {
    const linhas = Array.from({ length: 15 }, (_, i) => `AP-${i}`).join('\n')
    const previa = previaDoCsv(`codigo\n${linhas}`)

    expect(previa.linhas).toHaveLength(10)
    expect(previa.linhas[0]).toEqual(['AP-0'])
    expect(previa.linhas[9]).toEqual(['AP-9'])
  })

  it('campo entre aspas com o delimitador dentro nao quebra a coluna', () => {
    const previa = previaDoCsv('codigo,titulo\nAP-1,"Casa, com quintal"')
    expect(previa.linhas).toEqual([['AP-1', 'Casa, com quintal']])
  })

  it('aspas duplicadas dentro de um campo entre aspas viram uma aspas so', () => {
    const previa = previaDoCsv('codigo,titulo\nAP-1,"Casa ""nova"""')
    expect(previa.linhas).toEqual([['AP-1', 'Casa "nova"']])
  })

  it('arquivo vazio devolve colunas e linhas vazias, sem lancar', () => {
    expect(previaDoCsv('')).toEqual({ colunas: [], linhas: [] })
  })

  it('so cabecalho, sem nenhuma linha de dados', () => {
    const previa = previaDoCsv('codigo,titulo')
    expect(previa.colunas).toEqual(['codigo', 'titulo'])
    expect(previa.linhas).toEqual([])
  })

  it('aceita quebra de linha `\\r\\n`', () => {
    const previa = previaDoCsv('codigo,titulo\r\nAP-1,Casa\r\n')
    expect(previa.colunas).toEqual(['codigo', 'titulo'])
    expect(previa.linhas).toEqual([['AP-1', 'Casa']])
  })
})

describe('linhasParaCsv', () => {
  it('gera o cabecalho fixo `linha,motivo` mais uma linha por erro', () => {
    const csv = linhasParaCsv([
      { linha: 3, motivo: 'codigo ausente' },
      { linha: 7, motivo: 'tipo invalido: X' },
    ])

    expect(csv).toBe('linha,motivo\n3,codigo ausente\n7,tipo invalido: X')
  })

  it('lista vazia gera so o cabecalho', () => {
    expect(linhasParaCsv([])).toBe('linha,motivo')
  })

  it('escapa motivo com virgula entre aspas', () => {
    const csv = linhasParaCsv([{ linha: 1, motivo: 'preco_venda implausivel: "1,00"' }])
    expect(csv).toBe('linha,motivo\n1,"preco_venda implausivel: ""1,00"""')
  })

  it('escapa motivo com aspas, dobrando-as', () => {
    const csv = linhasParaCsv([{ linha: 1, motivo: 'campo "titulo" ausente' }])
    expect(csv).toBe('linha,motivo\n1,"campo ""titulo"" ausente"')
  })

  it('motivo sem virgula nem aspas nao ganha aspas', () => {
    const csv = linhasParaCsv([{ linha: 1, motivo: 'titulo ausente' }])
    expect(csv).toBe('linha,motivo\n1,titulo ausente')
  })
})
