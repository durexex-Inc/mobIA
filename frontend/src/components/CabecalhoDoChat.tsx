import type { ReactNode } from 'react'

/** O que o cabecalho diz da conexao (TEC-351, D3). */
export type EstadoDaConexao = 'conectado' | 'conectando' | 'reconectando' | 'offline'

const TEXTO_DA_CONEXAO: Record<EstadoDaConexao, string> = {
  conectado: 'Conectado',
  conectando: 'Conectando…',
  reconectando: 'Reconectando…',
  offline: 'Offline',
}

/**
 * O topo do chat embutido, visivel durante toda a conversa (TEC-346, D5):
 * "{nome} · Assistente virtual" com nome configurado, "Assistente virtual"
 * sem ele (cenario 4). Texto que a visitante le: com acento.
 *
 * `children` sao as acoes do topo -- o menu "Opções da conversa" da TEC-347
 * (D3), que `Conversa` passa porque e ela quem sabe encerrar.
 *
 * **`conexao` mostra o estado da conexao em texto** (TEC-351, D3), com um
 * ponto colorido ao lado que e so decoracao (`aria-hidden`): a cor nunca
 * carrega a informacao sozinha. `role="status"` anuncia a troca. Sem
 * `conexao`, o cabecalho e o de antes.
 */
export function CabecalhoDoChat({
  nome,
  conexao,
  children,
}: {
  nome: string | null
  conexao?: EstadoDaConexao
  children?: ReactNode
}) {
  return (
    <header className="chat-embutido__cabecalho">
      <div className="chat-embutido__identidade">
        <h1>{nome ? `${nome} · Assistente virtual` : 'Assistente virtual'}</h1>
        {conexao ? (
          <p className={`chat-embutido__conexao chat-embutido__conexao--${conexao}`} role="status">
            <span className="chat-embutido__marcador" aria-hidden="true" />
            {TEXTO_DA_CONEXAO[conexao]}
          </p>
        ) : null}
      </div>
      {children}
    </header>
  )
}
