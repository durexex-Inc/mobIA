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
      <p role="status" className="portal-interesse__sucesso">
        Recebemos seu pedido! Um corretor vai entrar em contato em breve.
      </p>
    )
  }

  return (
    <form action={enviar} className="portal-interesse">
      <h2 className="portal-subtitulo">Tenho interesse neste imóvel</h2>
      <p className="portal-nota">Deixe seu telefone e um corretor entra em contato.</p>
      <label className="portal-campo">
        Telefone
        <input
          name="telefone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          placeholder="Com DDD"
          required
          disabled={pendente}
        />
      </label>
      <label className="portal-campo">
        Nome (opcional)
        <input name="nome" type="text" autoComplete="name" disabled={pendente} />
      </label>
      <label className="portal-campo">
        E-mail (opcional)
        <input name="email" type="email" autoComplete="email" disabled={pendente} />
      </label>
      {estado.status === 'erro' && (
        <p role="alert" className="portal-interesse__erro">
          {estado.mensagem}
        </p>
      )}
      <button type="submit" className="portal-botao portal-botao--primario" disabled={pendente}>
        {pendente ? 'Enviando...' : 'Quero ser contatado'}
      </button>
    </form>
  )
}
