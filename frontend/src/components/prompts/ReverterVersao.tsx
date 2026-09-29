'use client'

import { useId, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import type { AgenteDaRota } from '@/lib/prompts'
import { nomeDoAgenteNaApi } from '@/lib/prompts'

/**
 * Reverter um agente para uma versao anterior, com confirmacao forte
 * (TEC-339, D2/D4 do desenho).
 *
 * **Mesmo molde de `EliminarDadosDoTitular.tsx` (TEC-342):** o botao
 * "Confirmar reversao" fica desabilitado ate o texto digitado bater com o
 * NUMERO da versao (comparacao de string -- "06" nao e "6"). O numero nunca
 * viaja no corpo da requisicao alem do que o proprio botao ja fixou; nao ha
 * caminho de UI para reverter com o numero errado (segundo cenario do
 * Gherkin), entao esse cenario e sobre o DOM, nao sobre uma resposta HTTP.
 *
 * **O sucesso mostra `tempoDeAtivacaoMs`** (D1/D4) antes de fechar -- o
 * unico "tempo ate ativacao" que existe, porque a reversao e sincrona e sem
 * cache a invalidar.
 */
export function ReverterVersao({ agente, versao }: { agente: AgenteDaRota; versao: number }) {
  const router = useRouter()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const idDoCampo = useId()
  const numeroDaVersao = String(versao)
  const [digitado, setDigitado] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')
  const [tempoDeAtivacaoMs, setTempoDeAtivacaoMs] = useState<number | null>(null)

  function abrir() {
    setDigitado('')
    setAviso('')
    setTempoDeAtivacaoMs(null)
    dialogRef.current?.showModal()
  }

  function fechar() {
    dialogRef.current?.close()
  }

  function fecharEAtualizar() {
    fechar()
    router.refresh()
  }

  async function confirmar() {
    if (digitado !== numeroDaVersao) {
      return
    }
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/prompts/${nomeDoAgenteNaApi(agente)}/rollback`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ versao }),
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    let dados: Record<string, unknown> = {}
    try {
      dados = (await resposta.json()) as Record<string, unknown>
    } catch {
      dados = {}
    }
    setEnviando(false)

    if (!resposta.ok) {
      setAviso(typeof dados.detail === 'string' ? dados.detail : 'Não foi possível reverter. Tente de novo.')
      return
    }

    setTempoDeAtivacaoMs(typeof dados.tempoDeAtivacaoMs === 'number' ? dados.tempoDeAtivacaoMs : null)
  }

  return (
    <>
      <button type="button" onClick={abrir}>
        Reverter para esta versão
      </button>
      <dialog ref={dialogRef} className="reverter-versao">
        {tempoDeAtivacaoMs !== null ? (
          <>
            <p role="status">
              Revertido para a versão {numeroDaVersao} em {tempoDeAtivacaoMs} ms.
            </p>
            <button type="button" onClick={fecharEAtualizar}>
              Fechar
            </button>
          </>
        ) : (
          <>
            <p>
              Para confirmar, digite o número da versão: <code>{numeroDaVersao}</code>
            </p>
            <label htmlFor={idDoCampo}>Número da versão</label>
            <input
              id={idDoCampo}
              type="text"
              value={digitado}
              onChange={(evento) => setDigitado(evento.target.value)}
              autoComplete="off"
            />
            <div>
              <button type="button" onClick={fechar} disabled={enviando}>
                Cancelar
              </button>
              <button type="button" onClick={confirmar} disabled={enviando || digitado !== numeroDaVersao}>
                Confirmar reversão
              </button>
            </div>
            {aviso && (
              <p role="alert" className="reverter-versao__aviso">
                {aviso}
              </p>
            )}
          </>
        )}
      </dialog>
    </>
  )
}
