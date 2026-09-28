'use client'

import { useId, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

/**
 * Eliminar os dados do titular com confirmacao forte (TEC-342, D1 e D3).
 *
 * **Nao ha apelido curto para o lead** -- a confirmacao e o `leadId` (UUID)
 * por extenso, mostrado no proprio dialogo. O botao "Confirmar eliminacao"
 * fica desabilitado ate o texto digitado bater com ele: nao ha caminho de UI
 * para disparar a chamada com o identificador errado, e por isso o texto
 * digitado nunca viaja na requisicao -- so o `leadId` do path, como toda
 * outra mutacao de lead do painel.
 *
 * **A chamada e `DELETE` pelo `/bff/*`**, no mesmo molde de
 * `ControleDaConversa` (assumir/devolver): o backend so registra a
 * eliminacao e enfileira o job que a executa (TEC-207), entao sucesso aqui
 * quer dizer "solicitada", nao "concluida" -- a linha da fila pode continuar
 * ABERTA ate o worker terminar.
 */
export function EliminarDadosDoTitular({ leadId }: { leadId: string }) {
  const router = useRouter()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const idDoCampo = useId()
  const [digitado, setDigitado] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')
  const [solicitado, setSolicitado] = useState(false)

  function abrir() {
    setDigitado('')
    setAviso('')
    setSolicitado(false)
    dialogRef.current?.showModal()
  }

  function fechar() {
    dialogRef.current?.close()
  }

  async function confirmar() {
    if (digitado !== leadId) {
      return
    }
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/leads/${encodeURIComponent(leadId)}/dados-pessoais`, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    setEnviando(false)
    if (resposta.ok) {
      setSolicitado(true)
      router.refresh()
      return
    }
    setAviso(
      resposta.status === 401
        ? 'Sua sessão terminou. Recarregue a página para entrar de novo.'
        : 'Não foi possível concluir. Tente de novo.',
    )
  }

  return (
    <>
      <button type="button" onClick={abrir}>
        Eliminar dados do titular
      </button>
      <dialog ref={dialogRef} className="eliminar-do-titular">
        {solicitado ? (
          <>
            <p role="status">Eliminação solicitada. Pode levar alguns minutos para sair da fila.</p>
            <button type="button" onClick={fechar}>
              Fechar
            </button>
          </>
        ) : (
          <>
            <p>
              Esta ação elimina os dados pessoais deste lead. Só as métricas agregadas
              anonimizadas são mantidas.
            </p>
            <p>
              Para confirmar, digite o identificador do lead: <code>{leadId}</code>
            </p>
            <label htmlFor={idDoCampo}>Identificador do lead</label>
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
              <button type="button" onClick={confirmar} disabled={enviando || digitado !== leadId}>
                Confirmar eliminação
              </button>
            </div>
            {aviso && (
              <p role="alert" className="eliminar-do-titular__aviso">
                {aviso}
              </p>
            )}
          </>
        )}
      </dialog>
    </>
  )
}
