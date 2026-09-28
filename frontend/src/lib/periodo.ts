/**
 * Os ultimos 30 dias, inclusive hoje, no formato que o backend espera.
 *
 * **`-30`, e nao `-29`** (TEC-316): o cenario 2 do Gherkin daquela card e
 * explicito -- hoje 24/09/2026, o periodo vai de 25/08/2026 a 24/09/2026, que
 * sao 31 dias corridos. A prosa "ultimos 30 dias" e a aproximacao; o exemplo
 * escrito por extenso e o criterio verificavel, e e ele que este numero
 * segue. Antes da TEC-316 este calculo era `-29` (30 dias corridos) -- muda
 * o que a tela mostra para quem abre o funil sem filtro.
 *
 * A aritmetica e em UTC de proposito: quem decide a fronteira do dia e o
 * backend, que usa `settings.fuso_de_envio` (America/Sao_Paulo, o fuso unico
 * da POC). Aqui so se produz a string `YYYY-MM-DD`; interpreta-la e trabalho
 * de la, e fazer a conta em dois fusos diferentes e que produziria
 * divergencia entre o que a tela mostra e o que o funil contou.
 */
export function periodoPadrao(hoje: Date): { de: string; ate: string } {
  const ate = new Date(Date.UTC(hoje.getUTCFullYear(), hoje.getUTCMonth(), hoje.getUTCDate()))
  const de = new Date(ate)
  de.setUTCDate(de.getUTCDate() - 30)
  return { de: de.toISOString().slice(0, 10), ate: ate.toISOString().slice(0, 10) }
}
