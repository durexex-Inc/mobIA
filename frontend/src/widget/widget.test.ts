import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * O loader de verdade, lido do disco e executado no jsdom (TEC-344, D5).
 *
 * O shadow root e FECHADO em producao, e o teste o alcanca interceptando
 * `attachShadow` -- sem isso nao haveria como ver o botao sem abrir o root, e
 * abrir so para o teste seria mudar o que se testa.
 *
 * O `fetch` e duble que devolve um objeto com `status` e `json()`, e nao um
 * `Response`: o corpo de um `Response` do Node se le por stream, fora das
 * microtarefas que `assentar()` drena, e o teste ficaria dependente de tempo.
 */

const CODIGO = readFileSync(resolve(__dirname, '../../public/widget.js'), 'utf8')
const PAINEL = 'https://painel.exemplo.com'
const APARENCIA = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

let raizes: ShadowRoot[] = []
let erros: unknown[] = []
const registrarErro = (evento: Event) => erros.push(evento)

type RespostaFalsa = { status: number; json: () => Promise<unknown> }

function apiRespondendo(status: number, corpo: unknown = APARENCIA) {
  const api = vi.fn<(url: string, init?: RequestInit) => Promise<RespostaFalsa>>(async () => ({
    status,
    json: async () => corpo,
  }))
  vi.stubGlobal('fetch', api)
  return api
}

function instalar({ tenant = 'imobiliaria-x' as string | null, comoAtual = true } = {}) {
  const script = document.createElement('script')
  script.src = `${PAINEL}/widget.js`
  if (tenant !== null) script.setAttribute('data-tenant', tenant)
  document.head.appendChild(script)
  if (comoAtual) {
    Object.defineProperty(document, 'currentScript', { value: script, configurable: true })
  }
  try {
    new Function(CODIGO)()
  } finally {
    Object.defineProperty(document, 'currentScript', { value: null, configurable: true })
  }
}

async function assentar() {
  for (let i = 0; i < 20; i++) await Promise.resolve()
}

const botao = () => raizes[0]?.querySelector('button') ?? null
const quadro = () => raizes[0]?.querySelector('iframe') ?? null

beforeEach(() => {
  raizes = []
  erros = []
  const original = Element.prototype.attachShadow
  vi.spyOn(Element.prototype, 'attachShadow').mockImplementation(function (
    this: Element,
    init: ShadowRootInit,
  ) {
    const raiz = original.call(this, init)
    raizes.push(raiz)
    return raiz
  })
  window.addEventListener('error', registrarErro)
  window.addEventListener('unhandledrejection', registrarErro)
})

afterEach(() => {
  window.removeEventListener('error', registrarErro)
  window.removeEventListener('unhandledrejection', registrarErro)
  document.head.innerHTML = ''
  document.body.innerHTML = ''
  delete (window as unknown as Record<string, unknown>).__mobiaWidget
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('o botao', () => {
  it('pede a aparencia a origem do proprio script, sem cookie', async () => {
    const api = apiRespondendo(200)

    instalar()
    await assentar()

    expect(api.mock.calls[0][0]).toBe(`${PAINEL}/embed/aparencia?tenant=imobiliaria-x`)
    expect(api.mock.calls[0][1]).toMatchObject({ credentials: 'omit' })
  })

  it('cenario 3: canto inferior esquerdo, na cor do tenant, com o nome no rotulo', async () => {
    apiRespondendo(200)

    instalar()
    await assentar()

    const b = botao()!
    expect(b.style.left).toBe('20px')
    expect(b.style.right).toBe('')
    expect(b.style.bottom).toBe('20px')
    expect(b.style.backgroundColor).toBe('rgb(10, 127, 90)')
    expect(b.getAttribute('aria-label')).toBe('Abrir o chat com Lia')
  })

  it('a direita, e sem nome o rotulo nao inventa um', async () => {
    apiRespondendo(200, { ...APARENCIA, nomeDoAssistente: null, posicaoDoBotao: 'DIREITA' })

    instalar()
    await assentar()

    expect(botao()!.style.right).toBe('20px')
    expect(botao()!.getAttribute('aria-label')).toBe('Abrir o chat')
  })

  it('acha o proprio script mesmo sem `currentScript`', async () => {
    apiRespondendo(200)

    instalar({ comoAtual: false })
    await assentar()

    expect(botao()).not.toBeNull()
  })

  it('snippet colado duas vezes desenha um botao so', async () => {
    const api = apiRespondendo(200)

    instalar()
    instalar()
    await assentar()

    expect(api).toHaveBeenCalledTimes(1)
    expect(raizes).toHaveLength(1)
  })

  it('sem `data-tenant` nao pede nada e nao desenha nada', async () => {
    const api = apiRespondendo(200)

    instalar({ tenant: null })
    await assentar()

    expect(api).not.toHaveBeenCalled()
    expect(raizes).toHaveLength(0)
  })
})

describe('cenario 4: o servidor do chat fora do ar nao quebra o site', () => {
  it.each([
    ['404', () => apiRespondendo(404, { erro: 'nao_encontrado' })],
    ['503', () => apiRespondendo(503, { erro: 'indisponivel' })],
    [
      'rede fora',
      () =>
        vi.stubGlobal(
          'fetch',
          vi.fn(async () => {
            throw new TypeError('fetch failed')
          }),
        ),
    ],
    [
      'JSON torto',
      () =>
        vi.stubGlobal(
          'fetch',
          vi.fn(async () => ({
            status: 200,
            json: async () => {
              throw new SyntaxError('x')
            },
          })),
        ),
    ],
    ['corpo nulo', () => apiRespondendo(200, null)],
    ['cor invalida', () => apiRespondendo(200, { ...APARENCIA, corPrimaria: 'red' })],
    ['cor com alfa', () => apiRespondendo(200, { ...APARENCIA, corPrimaria: '#0A7F5AFF' })],
    ['posicao desconhecida', () => apiRespondendo(200, { ...APARENCIA, posicaoDoBotao: 'CIMA' })],
    [
      'posicao herdada',
      () => apiRespondendo(200, { ...APARENCIA, posicaoDoBotao: 'constructor' }),
    ],
  ])('%s: sem botao e sem erro', async (_, preparar) => {
    preparar()

    instalar()
    await assentar()

    expect(raizes).toHaveLength(0)
    expect(erros).toEqual([])
  })

  it('aparencia que nao responde em 5 s: sem botao e sem erro', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_, rejeitar) =>
            init.signal!.addEventListener('abort', () =>
              rejeitar(new DOMException('abortado', 'AbortError')),
            ),
          ),
      ),
    )

    instalar()
    await vi.advanceTimersByTimeAsync(5000)
    await assentar()

    expect(raizes).toHaveLength(0)
    expect(erros).toEqual([])
  })
})

describe('o painel', () => {
  it('cenario 1: nenhum iframe antes do clique', async () => {
    apiRespondendo(200)

    instalar()
    await assentar()

    expect(quadro()).toBeNull()
  })

  it('o primeiro clique cria o iframe do chat; os seguintes so abrem e fecham', async () => {
    apiRespondendo(200)
    instalar()
    await assentar()

    botao()!.click()
    const primeiro = quadro()!
    expect(primeiro.src).toBe(`${PAINEL}/embed/chat?tenant=imobiliaria-x`)
    expect(botao()!.getAttribute('aria-expanded')).toBe('true')

    botao()!.click()
    expect(botao()!.getAttribute('aria-expanded')).toBe('false')
    expect((primeiro.parentElement as HTMLElement).style.display).toBe('none')

    botao()!.click()
    expect(quadro()).toBe(primeiro)
    expect(raizes[0].querySelectorAll('iframe')).toHaveLength(1)
  })

  it('sem `mobia:pronto` em 10 s, painel e botao somem', async () => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(false)
    expect(erros).toEqual([])
  })

  it('com `mobia:pronto` do proprio iframe, o painel fica', async () => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { tipo: 'mobia:pronto' },
        origin: PAINEL,
        source: quadro()!.contentWindow,
      }),
    )
    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(true)
  })

  it.each([
    ['de outra origem', () => ({ origin: 'https://intruso.exemplo.com', source: quadro()!.contentWindow })],
    ['de outra janela', () => ({ origin: PAINEL, source: window })],
  ])('`mobia:pronto` %s e ignorado', async (_, remetente) => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    window.dispatchEvent(
      new MessageEvent('message', { data: { tipo: 'mobia:pronto' }, ...remetente() }),
    )
    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(false)
  })
})
