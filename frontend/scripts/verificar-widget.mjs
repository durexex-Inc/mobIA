#!/usr/bin/env node
/**
 * O loader do chat cabe em 5 KB gzip (TEC-344, segunda regra da card).
 *
 * Comprime `public/widget.js` com o nivel padrao do zlib -- o que um servidor
 * comum aplica --, e nao com o maximo: medir com `level: 9` aprovaria um
 * arquivo que chega maior ao visitante.
 *
 * O arquivo e o que o navegador baixa, byte a byte, porque nao ha build (D5):
 * medir a fonte e medir a entrega.
 */
import { readFile } from 'node:fs/promises'
import { gzipSync } from 'node:zlib'

const LIMITE = 5 * 1024
const bytes = gzipSync(await readFile(new URL('../public/widget.js', import.meta.url))).length

if (bytes > LIMITE) {
  console.error(`\nverificar-widget: widget.js tem ${bytes} bytes gzip; o teto e ${LIMITE}.\n`)
  process.exit(1)
}
console.log(`verificar-widget: widget.js tem ${bytes} bytes gzip (teto ${LIMITE}).`)
