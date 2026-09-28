'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import type { Corretor } from '@/lib/corretores'

/**
 * Desativar corretor, fora do formulario de cadastro/edicao (D5 e D7 do
 * desenho).
 *
 * **`PATCH { ativo: false }` pelo `/bff/*`** -- nao ha rota `DELETE`
 * (`corretores.py`, D6 da TEC-196). **A confirmacao cita o texto exigido
 * pela card**: "o histórico e os leads atribuídos são mantidos". **Nao ha
 * controle de reativar** (D5): esta acao so vai num sentido.
 */
export function DesativarCorretor({ corretor }: { corretor: Corretor }) {
  const router = useRouter()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')

  function abrir() {
    setAviso('')
    dialogRef.current?.showModal()
  }

  function fechar() {
    dialogRef.current?.close()
  }

  async function confirmar() {
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/corretores/${encodeURIComponent(corretor.id)}`, {
        method: 'PATCH',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ ativo: false }),
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    setEnviando(false)
    if (resposta.ok) {
      fechar()
      router.refresh()
      return
    }
    setAviso(
      resposta.status === 401
        ? 'Sua sessão terminou. Recarregue a página para entrar de novo.'
        : 'Não foi possível desativar. Tente de novo.',
    )
  }

  return (
    <>
      <button type="button" onClick={abrir}>
        Desativar
      </button>
      <dialog ref={dialogRef} className="desativar-corretor">
        <p>Desativar {corretor.nome}?</p>
        <p>O histórico e os leads atribuídos são mantidos; o corretor deixa de receber novas alocações.</p>
        <div>
          <button type="button" onClick={fechar} disabled={enviando}>
            Cancelar
          </button>
          <button type="button" onClick={confirmar} disabled={enviando}>
            Confirmar desativação
          </button>
        </div>
        {aviso && (
          <p role="alert" className="desativar-corretor__aviso">
            {aviso}
          </p>
        )}
      </dialog>
    </>
  )
}
