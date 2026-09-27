/**
 * O topo do chat embutido: o nome com que o assistente se apresenta
 * (TEC-344, cenario 3). A conversa em si e da TEC-346.
 */
export function CabecalhoDoChat({ nome }: { nome: string }) {
  return (
    <header className="chat-embutido__cabecalho">
      <h1>{nome}</h1>
    </header>
  )
}
