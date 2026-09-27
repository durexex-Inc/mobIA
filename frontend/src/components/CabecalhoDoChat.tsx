import type { ReactNode } from 'react'

/**
 * O topo do chat embutido, visivel durante toda a conversa (TEC-346, D5):
 * "{nome} · Assistente virtual" com nome configurado, "Assistente virtual"
 * sem ele (cenario 4). Texto que a visitante le: com acento.
 *
 * `children` sao as acoes do topo -- o menu "Opções da conversa" da TEC-347
 * (D3), que `Conversa` passa porque e ela quem sabe encerrar.
 */
export function CabecalhoDoChat({ nome, children }: { nome: string | null; children?: ReactNode }) {
  return (
    <header className="chat-embutido__cabecalho">
      <h1>{nome ? `${nome} · Assistente virtual` : 'Assistente virtual'}</h1>
      {children}
    </header>
  )
}
