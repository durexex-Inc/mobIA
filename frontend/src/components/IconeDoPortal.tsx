/**
 * Os icones do detalhe publico do imovel. SVG inline e nao uma biblioteca:
 * sao oito tracos, e o portal nao carrega nada de fora da propria origem
 * alem do mapa (D3 do desenho do visual do portal).
 *
 * Sempre decorativos (`aria-hidden`): o texto ao lado ja diz o que o icone
 * mostra.
 */
const TRACOS = {
  voltar: 'M15 18l-6-6 6-6',
  pino: 'M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  area: 'M4 4h16v16H4zM4 9h5V4M20 15h-5v5',
  quarto: 'M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 15h18M6 10V7a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3',
  banheiro: 'M4 12h16v3a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4zM6 12V6a2 2 0 0 1 4 0M7 19l-1 2M17 19l1 2',
  vaga: 'M5 16V11l2-5h10l2 5v5M5 16h14M5 16v2M19 16v2M8 13h.01M16 13h.01',
  confere: 'M5 12.5l4.5 4.5L19 7.5',
  documento: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
} as const

export type NomeDoIcone = keyof typeof TRACOS

export function IconeDoPortal({ nome }: { nome: NomeDoIcone }) {
  return (
    <svg
      className="portal-icone"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={TRACOS[nome]} />
    </svg>
  )
}
