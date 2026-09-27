import { afterEach, describe, expect, it } from 'vitest'

import { enderecoDoChat, origemDoChat } from './enderecoDoChat'

describe('enderecoDoChat', () => {
  afterEach(() => {
    delete process.env.MOBIA_WIDGET_WS_URL
    delete process.env.MOBIA_API_BASE
  })

  it('usa MOBIA_WIDGET_WS_URL quando existe', () => {
    process.env.MOBIA_WIDGET_WS_URL = 'wss://api.exemplo.com/widget/chat'
    expect(enderecoDoChat()).toBe('wss://api.exemplo.com/widget/chat')
    expect(origemDoChat()).toBe('wss://api.exemplo.com')
  })

  it('sem ela, deriva de MOBIA_API_BASE trocando http por ws', () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    expect(enderecoDoChat()).toBe('ws://backend:8000/widget/chat')
  })

  it('https vira wss', () => {
    process.env.MOBIA_API_BASE = 'https://api.exemplo.com'
    expect(enderecoDoChat()).toBe('wss://api.exemplo.com/widget/chat')
  })

  it('sem nenhuma, o padrao local', () => {
    expect(enderecoDoChat()).toBe('ws://localhost:8000/widget/chat')
  })
})
