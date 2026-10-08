import { useSyncExternalStore } from 'react'

import { type Tema, temaDoCookie } from '@/lib/tema'

const CONSULTA_ESCURO = '(prefers-color-scheme: dark)'

/** O tema que esta na tela: o escolhido no botao, ou o do sistema (TEC-393, D2). */
export function temaNaTela(): Tema {
  const escolhido = temaDoCookie(document.documentElement.dataset.tema)
  if (escolhido) {
    return escolhido
  }
  // jsdom nao tem `matchMedia`; sem ele, vale o claro, que e o padrao do CSS.
  return typeof window.matchMedia === 'function' && window.matchMedia(CONSULTA_ESCURO).matches
    ? 'escuro'
    : 'claro'
}

function inscrever(aoMudar: () => void): () => void {
  const observador = new MutationObserver(aoMudar)
  observador.observe(document.documentElement, { attributes: true, attributeFilter: ['data-tema'] })
  const consulta = typeof window.matchMedia === 'function' ? window.matchMedia(CONSULTA_ESCURO) : null
  consulta?.addEventListener('change', aoMudar)
  return () => {
    observador.disconnect()
    consulta?.removeEventListener('change', aoMudar)
  }
}

/**
 * O tema atual, para o que nao le CSS -- o Monaco pinta com cores proprias
 * (TEC-395). Acompanha o botao de tema e a troca do sistema sem recarregar.
 */
export function useTemaAtual(): Tema {
  return useSyncExternalStore(inscrever, temaNaTela, () => 'claro')
}
