/**
 * O topo do chat embutido, visivel durante toda a conversa (TEC-346, D5):
 * "{nome} · Assistente virtual" com nome configurado, "Assistente virtual"
 * sem ele (cenario 4). Texto que a visitante le: com acento.
 */
export function CabecalhoDoChat({ nome }: { nome: string | null }) {
  return (
    <header className="chat-embutido__cabecalho">
      <h1>{nome ? `${nome} · Assistente virtual` : 'Assistente virtual'}</h1>
    </header>
  )
}
