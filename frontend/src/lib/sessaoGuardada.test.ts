import { describe, expect, it } from 'vitest'

import {
  type Armazem,
  CHAVE_DA_SESSAO,
  VALIDADE_DA_SESSAO_MS,
  apagarSessao,
  armazemDoNavegador,
  gravarSessao,
  lerSessao,
} from './sessaoGuardada'

// Armazem em memoria, para testar sem localStorage real.
function armazemDeMapa(): Armazem {
  const mapa = new Map<string, string>()
  return {
    getItem: (chave) => mapa.get(chave) ?? null,
    setItem: (chave, valor) => {
      mapa.set(chave, valor)
    },
    removeItem: (chave) => {
      mapa.delete(chave)
    },
  }
}

// Armazem que lanca em toda operacao, como Safari ITP ou modo privado bloqueado.
function armazemQueLanca(): Armazem {
  return {
    getItem: () => {
      throw new Error('storage bloqueado')
    },
    setItem: () => {
      throw new Error('storage bloqueado')
    },
    removeItem: () => {
      throw new Error('storage bloqueado')
    },
  }
}

const UUID = '415b23dc-823d-4926-9442-964169fdb758'
const OUTRO_UUID = 'a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6'
const DIA_MS = 24 * 60 * 60 * 1000
const AGORA = Date.UTC(2026, 8, 27)

function guardar(armazem: Armazem, sessao: string, criadaEm: number): void {
  armazem.setItem(CHAVE_DA_SESSAO, JSON.stringify({ sessao, criadaEm }))
}

describe('lerSessao', () => {
  it('le de volta dentro do prazo -- 29 dias e 23h depois', () => {
    const armazem = armazemDeMapa()
    const criadaEm = AGORA - (29 * DIA_MS + 23 * 60 * 60 * 1000)
    guardar(armazem, UUID, criadaEm)

    expect(lerSessao(armazem, AGORA)).toBe(UUID)
  })

  it('31 dias depois volta null e apaga a chave', () => {
    const armazem = armazemDeMapa()
    guardar(armazem, UUID, AGORA - 31 * DIA_MS)

    expect(lerSessao(armazem, AGORA)).toBeNull()
    expect(armazem.getItem(CHAVE_DA_SESSAO)).toBeNull()
  })

  it('exatamente 30 dias volta null -- a validade e "< 30 dias"', () => {
    const armazem = armazemDeMapa()
    guardar(armazem, UUID, AGORA - VALIDADE_DA_SESSAO_MS)

    expect(lerSessao(armazem, AGORA)).toBeNull()
  })

  it('criadaEm no futuro volta null e apaga a chave', () => {
    const armazem = armazemDeMapa()
    guardar(armazem, UUID, AGORA + 1000)

    expect(lerSessao(armazem, AGORA)).toBeNull()
    expect(armazem.getItem(CHAVE_DA_SESSAO)).toBeNull()
  })

  const casosInvalidos: Array<[string, string]> = [
    ['JSON torto', '{sessao:'],
    ['texto puro, o formato da TEC-346', UUID],
    ['objeto sem sessao', JSON.stringify({ criadaEm: AGORA })],
    ['sessao que nao e UUID', JSON.stringify({ sessao: 'nao-e-um-uuid', criadaEm: AGORA })],
    ['criadaEm nao numerico', JSON.stringify({ sessao: UUID, criadaEm: 'ontem' })],
  ]

  it.each(casosInvalidos)('%s volta null e apaga a chave', (_nome, bruto) => {
    const armazem = armazemDeMapa()
    armazem.setItem(CHAVE_DA_SESSAO, bruto)

    expect(lerSessao(armazem, AGORA)).toBeNull()
    expect(armazem.getItem(CHAVE_DA_SESSAO)).toBeNull()
  })

  it('armazem que lanca volta null e nao lanca', () => {
    const armazem = armazemQueLanca()

    let resultado: string | null = UUID
    expect(() => {
      resultado = lerSessao(armazem, AGORA)
    }).not.toThrow()
    expect(resultado).toBeNull()
  })

  it('armazem null volta null e nao lanca', () => {
    expect(() => lerSessao(null, AGORA)).not.toThrow()
    expect(lerSessao(null, AGORA)).toBeNull()
  })
})

describe('gravarSessao', () => {
  it('mesma sessao ja guardada nao muda criadaEm -- prazo desde a criacao, D1', () => {
    const armazem = armazemDeMapa()
    const criadaEmOriginal = AGORA - 10 * DIA_MS
    guardar(armazem, UUID, criadaEmOriginal)

    gravarSessao(armazem, UUID, AGORA)

    expect(JSON.parse(armazem.getItem(CHAVE_DA_SESSAO) as string)).toEqual({
      sessao: UUID,
      criadaEm: criadaEmOriginal,
    })
  })

  it('sessao diferente substitui, com criadaEm = agora', () => {
    const armazem = armazemDeMapa()
    guardar(armazem, UUID, AGORA - 10 * DIA_MS)

    gravarSessao(armazem, OUTRO_UUID, AGORA)

    expect(JSON.parse(armazem.getItem(CHAVE_DA_SESSAO) as string)).toEqual({
      sessao: OUTRO_UUID,
      criadaEm: AGORA,
    })
  })

  it('grava pela primeira vez com criadaEm = agora', () => {
    const armazem = armazemDeMapa()

    gravarSessao(armazem, UUID, AGORA)

    expect(JSON.parse(armazem.getItem(CHAVE_DA_SESSAO) as string)).toEqual({
      sessao: UUID,
      criadaEm: AGORA,
    })
  })

  it('armazem que lanca nao lanca', () => {
    expect(() => gravarSessao(armazemQueLanca(), UUID, AGORA)).not.toThrow()
  })

  it('armazem null nao lanca', () => {
    expect(() => gravarSessao(null, UUID, AGORA)).not.toThrow()
  })
})

describe('apagarSessao', () => {
  it('apaga a chave guardada', () => {
    const armazem = armazemDeMapa()
    guardar(armazem, UUID, AGORA)

    apagarSessao(armazem)

    expect(armazem.getItem(CHAVE_DA_SESSAO)).toBeNull()
  })

  it('armazem que lanca nao lanca', () => {
    expect(() => apagarSessao(armazemQueLanca())).not.toThrow()
  })

  it('armazem null nao lanca', () => {
    expect(() => apagarSessao(null)).not.toThrow()
  })
})

describe('armazemDoNavegador', () => {
  it('retorna o localStorage do navegador', () => {
    expect(armazemDoNavegador()).toBe(window.localStorage)
  })

  it('retorna null se acessar localStorage lancar', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('bloqueado')
      },
    })

    try {
      expect(armazemDoNavegador()).toBeNull()
    } finally {
      if (original) {
        Object.defineProperty(window, 'localStorage', original)
      }
    }
  })
})
