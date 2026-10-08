'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { Botao } from '@/components/ui/Botao'
import type { Imovel } from '@/lib/imoveis'

const TEXTO_DA_CONFIRMACAO =
  'O imóvel deixa de ser recomendado pelo agente. Continua visível aqui, marcado como retirado.'

/**
 * Retirar imovel das buscas, fora do formulario de cadastro/edicao (D4 do
 * desenho).
 *
 * **`DELETE /api/v1/imoveis/{id}` pelo `/bff/*`** -- exclusao logica,
 * `status = INATIVO` (`cadastro.excluir`). Confirmacao de duas etapas, sem
 * digitar identificador: a card nao pede a friccao forte que a TEC-342 usou
 * para dado pessoal, e imovel nao e dado pessoal.
 *
 * **Nao ha controle de reativar** (D4): reativar e editar o Status de volta
 * para "Disponível" no `FormularioDeImovel`, porque Status ja e um campo
 * editavel comum.
 */
export function RetirarImovel({ imovel }: { imovel: Imovel }) {
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
      resposta = await fetch(`/bff/api/v1/imoveis/${encodeURIComponent(imovel.id)}`, {
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
      fechar()
      router.refresh()
      return
    }
    setAviso(
      resposta.status === 401
        ? 'Sua sessão terminou. Recarregue a página para entrar de novo.'
        : 'Não foi possível retirar. Tente de novo.',
    )
  }

  return (
    <>
      <Botao variante="fantasma" tamanho="pequeno" onClick={abrir}>
        Retirar das buscas
      </Botao>
      <dialog ref={dialogRef} className="dialogo">
        <p className="dialogo__titulo">Retirar {imovel.titulo} das buscas?</p>
        <p>{TEXTO_DA_CONFIRMACAO}</p>
        <div className="dialogo__acoes">
          <Botao variante="contorno" onClick={fechar} disabled={enviando}>
            Cancelar
          </Botao>
          <Botao className="botao--perigo" onClick={confirmar} disabled={enviando}>
            Confirmar retirada
          </Botao>
        </div>
        {aviso && (
          <p role="alert" className="dialogo__aviso">
            {aviso}
          </p>
        )}
      </dialog>
    </>
  )
}
