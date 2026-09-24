/**
 * O `server-only` de verdade LANCA fora do bundler do Next.
 *
 * O `exports` do pacote manda a condicao `react-server` para um arquivo vazio
 * e todo o resto para um `index.js` cujo corpo inteiro e um `throw`. O vitest
 * nao roda sob aquela condicao, entao `import 'server-only'` derrubaria todo
 * teste que toque `lib/servidor/`. O alias para este stub esta em
 * `vitest.config.ts`.
 *
 * Isto NAO enfraquece o gate: o gate nunca foi o vitest, e sim o
 * `npm run build`, que roda no job `Frontend` do CI e e quem de fato reprova
 * quando um modulo de servidor e importado do cliente.
 */
export {}
