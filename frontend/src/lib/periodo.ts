/**
 * Os ultimos 30 dias, inclusive hoje, no formato que o backend espera.
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
  de.setUTCDate(de.getUTCDate() - 29)
  return { de: de.toISOString().slice(0, 10), ate: ate.toISOString().slice(0, 10) }
}
