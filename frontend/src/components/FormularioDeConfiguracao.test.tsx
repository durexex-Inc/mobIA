import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Configuracao, Limites } from '@/lib/configuracao'
import { FormularioDeConfiguracao } from './FormularioDeConfiguracao'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const CONFIGURACAO: Configuracao = {
  nomeDoAssistente: 'Ana',
  tom: 'CORDIAL',
  tetoDePerguntas: 8,
  pesoCompletude: 20,
  pesoUrgencia: 25,
  pesoCatalogo: 20,
  pesoEngajamento: 15,
  pesoCapacidade: 15,
  cadencia: { QUENTE: [2, 24, 72, 168], MORNO: [24, 96, 240], FRIO: [72, 336] },
  orcamentoMensalUsd: '100.00',
  corPrimaria: '#1D4ED8',
  posicaoDoBotao: 'DIREITA',
  dominiosDoChat: [],
}

const LIMITES: Limites = {
  nomeDoAssistente: { maximoDeCaracteres: 30, nulavel: true },
  tom: { valores: ['CORDIAL', 'FORMAL', 'DESCONTRAIDO'] },
  tetoDePerguntas: { minimo: 1, maximo: 20 },
  pesos: { minimo: 0, maximo: 50, somaMaxima: 100 },
  cadencia: {
    tentativasPorTemperatura: { QUENTE: 4, MORNO: 3, FRIO: 2 },
    horaMinima: 1,
    horaMaxima: 2160,
  },
  orcamentoMensalUsd: { minimo: '0.01', maximo: '100000', nulavel: true },
  corPrimaria: {},
  posicaoDoBotao: {},
  dominiosDoChat: {},
}

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

function digitar(rotulo: string, valor: string) {
  fireEvent.change(screen.getByLabelText(rotulo), { target: { value: valor } })
}

describe('FormularioDeConfiguracao', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => responde({ configuracao: CONFIGURACAO, alterados: [] }))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  function montar(props: Partial<React.ComponentProps<typeof FormularioDeConfiguracao>> = {}) {
    return render(
      <FormularioDeConfiguracao
        configuracaoInicial={CONFIGURACAO}
        limitesIniciais={LIMITES}
        versaoInicial="v-1"
        {...props}
      />,
    )
  }

  describe('cenario: revisar a mudanca antes de salvar (D4)', () => {
    it('mostra o diff "rotulo: de -> para" e NAO chama o fetch antes de confirmar', async () => {
      montar()

      digitar('Peso de urgência', '30')
      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.getByRole('alertdialog')).toHaveTextContent('Peso de urgência: 25 → 30')

      await clicar('Confirmar')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/configuracao/agente',
        expect.objectContaining({ method: 'PATCH' }),
      )
      const corpo = JSON.parse((api.mock.calls[0][1] as RequestInit).body as string)
      expect(corpo).toEqual({ pesoUrgencia: 30, seVersao: 'v-1' })
    })

    it('cancelar a confirmacao fecha o diff sem chamar o fetch', async () => {
      montar()

      digitar('Peso de urgência', '30')
      await clicar('Salvar')
      await clicar('Cancelar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.queryByRole('alertdialog')).toBeNull()
    })

    it('sem mudanca, Salvar nao abre confirmacao nem chama o fetch', async () => {
      montar()

      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.queryByRole('alertdialog')).toBeNull()
    })
  })

  describe('cenario: recusar valor fora da faixa (D2, cenario 2 do Gherkin)', () => {
    it('peso negativo e recusado ANTES de qualquer fetch, com a mensagem lendo os limites', async () => {
      montar()

      digitar('Peso de urgência', '-1')
      await clicar('Salvar')

      expect(api).not.toHaveBeenCalled()
      expect(screen.queryByRole('alertdialog')).toBeNull()
      expect(screen.getByLabelText('Peso de urgência')).toHaveAccessibleDescription(
        `Entre ${LIMITES.pesos.minimo} e ${LIMITES.pesos.maximo}.`,
      )
    })

    it('a mesma recusa usa os limites passados por prop, nao um numero fixo', async () => {
      montar({ limitesIniciais: { ...LIMITES, pesos: { minimo: 0, maximo: 90, somaMaxima: 100 } } })

      digitar('Peso de urgência', '80')
      await clicar('Salvar')

      // 80 estaria fora do teto de 50 do LIMITES padrao, mas passa com o teto de 90.
      expect(api).not.toHaveBeenCalled()
      expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    })
  })

  describe('cenario: configuracao alterada por outra pessoa (D1/D5, cenario 3 do Gherkin)', () => {
    it('409 mostra o aviso inline com "Recarregar", que so chama router.refresh (nao reenvia a edicao)', async () => {
      api.mockResolvedValueOnce(
        responde(
          { detail: 'a configuracao foi alterada por outra pessoa desde que a tela foi carregada; recarregue' },
          409,
        ),
      )
      montar()

      digitar('Peso de urgência', '30')
      await clicar('Salvar')
      await clicar('Confirmar')

      expect(screen.getByRole('alert')).toHaveTextContent('alterada por outra pessoa')
      const botaoRecarregar = screen.getByRole('button', { name: 'Recarregar' })

      await act(async () => {
        fireEvent.click(botaoRecarregar)
      })

      expect(refresh).toHaveBeenCalledOnce()
      // Nao ha um segundo PATCH: o unico fetch foi o que levou o 409.
      expect(api).toHaveBeenCalledOnce()
    })
  })

  describe('cenario: apos salvar com sucesso', () => {
    it('atualiza a linha de base localmente e chama router.refresh (D1)', async () => {
      const configuracaoSalva = { ...CONFIGURACAO, pesoUrgencia: 30 }
      api.mockResolvedValueOnce(responde({ configuracao: configuracaoSalva, alterados: ['pesoUrgencia'] }))
      montar()

      digitar('Peso de urgência', '30')
      await clicar('Salvar')
      await clicar('Confirmar')

      expect(refresh).toHaveBeenCalledOnce()
      // A tela ja nao esta suja: salvar de novo sem mudar nada nao abre diff.
      await clicar('Salvar')
      expect(screen.queryByRole('alertdialog')).toBeNull()
      expect(screen.getByLabelText('Peso de urgência')).toHaveValue(30)
    })

    // `router.refresh()` de verdade (o Server Component buscando de novo do
    // FastAPI) e coberto pelos testes de feature do backend, nao aqui -- o
    // que se testa em isolamento e a reacao do componente a uma `key` nova,
    // que e como `admin/configuracao/page.tsx` o remonta quando a `versao`
    // muda (ver a docstring do componente: nao ha `useEffect` copiando prop
    // para estado).
    it('uma `key` nova (versao nova) remonta o formulario do zero, com props frescas', () => {
      const configuracaoSalva = { ...CONFIGURACAO, pesoUrgencia: 30 }
      const { rerender } = render(
        <FormularioDeConfiguracao
          key="v-1"
          configuracaoInicial={CONFIGURACAO}
          limitesIniciais={LIMITES}
          versaoInicial="v-1"
        />,
      )
      digitar('Peso de urgência', '99')

      rerender(
        <FormularioDeConfiguracao
          key="v-2"
          configuracaoInicial={configuracaoSalva}
          limitesIniciais={LIMITES}
          versaoInicial="v-2"
        />,
      )

      // A edicao em curso ('99') some -- a instancia antiga foi desmontada.
      expect(screen.getByLabelText('Peso de urgência')).toHaveValue(30)
    })
  })

  it('renderiza a grade de cadencia com a quantidade de campos de `limites`, nao um numero fixo', () => {
    montar()

    expect(screen.getByLabelText('Quente, intervalo 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Quente, intervalo 4')).toBeInTheDocument()
    expect(screen.queryByLabelText('Quente, intervalo 5')).toBeNull()
    expect(screen.getByLabelText('Morno, intervalo 3')).toBeInTheDocument()
    expect(screen.getByLabelText('Frio, intervalo 2')).toBeInTheDocument()
  })

  it('a nota sobre a soma dos pesos le `limites.pesos.somaMaxima`, sem "100" escrito no componente', () => {
    montar({ limitesIniciais: { ...LIMITES, pesos: { minimo: 0, maximo: 50, somaMaxima: 77 } } })

    expect(screen.getByText(/entre 1 e 77/)).toBeInTheDocument()
  })
})
