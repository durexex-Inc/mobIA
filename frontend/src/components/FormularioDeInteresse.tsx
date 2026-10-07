'use client'

import { useActionState } from 'react'

import { solicitarInteresseAction, type EstadoDoInteresse } from '@/app/busca/[id]/acoes'

const ESTADO_INICIAL: EstadoDoInteresse = { status: 'inicial' }

/**
 * "Tenho interesse" no detalhe de um imovel (TEC-389), sem WhatsApp nem
 * widget. So telefone e obrigatorio (B1 do desenho) -- nome e e-mail ajudam
 * o corretor mas nao bloqueiam o envio.
 */
export function FormularioDeInteresse({ imovelId }: { imovelId: string }) {
  const acao = solicitarInteresseAction.bind(null, imovelId)
  const [estado, enviar, pendente] = useActionState(acao, ESTADO_INICIAL)

  if (estado.status === 'sucesso') {
    return (
      <p role="status" className="busca-publica__interesse_sucesso">
        Recebemos seu pedido! Um corretor vai entrar em contato em breve.
      </p>
    )
  }

  return (
    <form action={enviar} className="busca-publica__interesse">
      <h2>Tenho interesse</h2>
      <label>
        Telefone
        <input name="telefone" type="tel" inputMode="tel" required disabled={pendente} />
      </label>
      <label>
        Nome (opcional)
        <input name="nome" type="text" disabled={pendente} />
      </label>
      <label>
        E-mail (opcional)
        <input name="email" type="email" disabled={pendente} />
      </label>
      {estado.status === 'erro' && (
        <p role="alert" className="busca-publica__interesse_erro">
          {estado.mensagem}
        </p>
      )}
      <button type="submit" disabled={pendente}>
        {pendente ? 'Enviando...' : 'Quero ser contatado'}
      </button>
    </form>
  )
}
