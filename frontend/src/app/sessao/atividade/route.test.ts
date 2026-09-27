import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { conteudoDoArmazem, limparArmazem } from '../../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../../test/token'
import { criarSessao } from '@/lib/servidor/sessao'
import { POST } from './route'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const PAINEL = 'https://painel.exemplo.com'

function batimento({ sessao, origem = PAINEL }: { sessao?: string; origem?: string } = {}) {
  const cabecalhos = new Headers({ origin: origem })
  if (sessao) {
    cabecalhos.set('cookie', `mobia_sessao=${sessao}`)
  }
  return new NextRequest(new URL('/sessao/atividade', PAINEL), { method: 'POST', headers: cabecalhos })
}

describe('POST /sessao/atividade (TEC-311, D3)', () => {
  beforeEach(() => {
    process.env.MOBIA_ORIGEM_DO_PAINEL = PAINEL
    limparArmazem()
  })
  afterEach(() => {
    delete process.env.MOBIA_ORIGEM_DO_PAINEL
  })

  it('com sessao, 204 -- e a marca de atividade renovada', async () => {
    const id = await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' })
    const marca = () => conteudoDoArmazem().find((i) => i.chave.startsWith('mobia:painel:atividade:'))

    const resposta = await POST(batimento({ sessao: id }))

    expect(resposta.status).toBe(204)
    expect(marca()?.segundos).toBe(32 * 60)
  })

  it('sem sessao, 401 e nunca redirecionamento: quem chama e um fetch', async () => {
    const resposta = await POST(batimento())

    expect(resposta.status).toBe(401)
    expect(resposta.headers.get('location')).toBeNull()
  })

  it('de outra origem, 403', async () => {
    const id = await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' })

    const resposta = await POST(batimento({ sessao: id, origem: 'https://site-externo.com' }))

    expect(resposta.status).toBe(403)
  })
})
