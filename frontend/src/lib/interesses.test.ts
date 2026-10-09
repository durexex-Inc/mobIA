import { describe, expect, it } from 'vitest'

import {
  estadoDaUrl,
  podeAssumir,
  podeRevelarPedido,
  rotuloDoAtendimento,
  urlDosPedidos,
  type AtendimentoDoPedido,
} from './interesses'

const atendimento = (extra: Partial<AtendimentoDoPedido> = {}): AtendimentoDoPedido => ({
  id: 'h-1',
  status: 'PENDENTE',
  corretor: { id: 'c-a', nome: 'Ana' },
  notificadoEm: null,
  semCorretor: false,
  ...extra,
})

describe('estadoDaUrl / urlDosPedidos', () => {
  it('padrao e pendentes; valor desconhecido tambem', () => {
    expect(estadoDaUrl(undefined)).toBe('pendentes')
    expect(estadoDaUrl('qualquer')).toBe('pendentes')
    expect(estadoDaUrl(['todos'])).toBe('todos')
  })

  it('pendentes sem cursor e a URL limpa', () => {
    expect(urlDosPedidos('pendentes')).toBe('/interesses')
    expect(urlDosPedidos('todos', 'abc')).toBe('/interesses?estado=todos&cursor=abc')
  })
})

describe('rotuloDoAtendimento', () => {
  it('sem corretor vence o status', () => {
    expect(
      rotuloDoAtendimento(atendimento({ semCorretor: true, corretor: null, status: 'ESCALADO' })),
    ).toBe('Sem corretor')
  })

  it('cada status tem rotulo com acento', () => {
    expect(rotuloDoAtendimento(atendimento())).toBe('Pendente')
    expect(rotuloDoAtendimento(atendimento({ status: 'ACEITO' }))).toBe('Assumido')
    expect(rotuloDoAtendimento(atendimento({ status: 'ESCALADO' }))).toBe('Escalado')
    expect(rotuloDoAtendimento(atendimento({ status: 'CONCLUIDO' }))).toBe('Concluído')
    expect(rotuloDoAtendimento(null)).toBe('Sem atendimento')
  })
})

describe('podeAssumir', () => {
  it('so o corretor dono, e so pendente ou escalado', () => {
    expect(podeAssumir(atendimento(), 'c-a')).toBe(true)
    expect(podeAssumir(atendimento({ status: 'ESCALADO' }), 'c-a')).toBe(true)
    expect(podeAssumir(atendimento({ status: 'ACEITO' }), 'c-a')).toBe(false)
    expect(podeAssumir(atendimento(), 'c-b')).toBe(false)
    expect(podeAssumir(atendimento(), null)).toBe(false)
    expect(podeAssumir(null, 'c-a')).toBe(false)
  })
})

describe('podeRevelarPedido', () => {
  it('VER_DADOS_COMPLETOS revela qualquer um', () => {
    expect(
      podeRevelarPedido(null, { permissoes: new Set(['VER_DADOS_COMPLETOS']), corretorId: null }),
    ).toBe(true)
  })

  it('corretor so o dele', () => {
    const quem = { permissoes: new Set(['VER_LEADS']), corretorId: 'c-a' }
    expect(podeRevelarPedido(atendimento(), quem)).toBe(true)
    expect(podeRevelarPedido(atendimento({ corretor: { id: 'c-b', nome: 'Bia' } }), quem)).toBe(
      false,
    )
    expect(podeRevelarPedido(atendimento({ corretor: null }), quem)).toBe(false)
  })
})
