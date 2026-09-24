#!/usr/bin/env node
/**
 * O cenario 1 do Gherkin da TEC-302, mecanizado.
 *
 * > Quando se inspecionam o codigo estatico do build (...) entao nenhum token
 * > de API e encontrado.
 *
 * Constroi-se com `MOBIA_ADMIN_TOKEN` valendo uma sentinela e procura-se a
 * sentinela em tudo que esta sob `.next/static` -- que e exatamente o que o
 * navegador baixa.
 *
 * **Ele pega um engano que o `server-only` nao pega, e e por isso que sao
 * dois gates.** `server-only` reprova o build quando o modulo do token e
 * arrastado para um componente de cliente. Ele NAO diz nada se alguem
 * renomear a variavel para `NEXT_PUBLIC_MOBIA_ADMIN_TOKEN`, que e o caminho
 * pelo qual o valor literal vai parar no bundle. Esta varredura e o gate desse
 * caso.
 *
 * `.next/server` fica de fora de proposito: la o token pode aparecer sem que
 * nada esteja errado, e incluir aquele diretorio produziria ruido sobre a
 * unica pergunta que importa, que e o que o navegador recebe.
 */
import { readdir, readFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const RAIZ = fileURLToPath(new URL('..', import.meta.url))
const ESTATICOS = join(RAIZ, '.next', 'static')

// Sentinela curta acharia a si mesma dentro de qualquer identificador
// minificado, e falso positivo treina quem le a ignorar.
const TAMANHO_MINIMO_DA_SENTINELA = 16

function reprovar(mensagem) {
  console.error(`\nverificar-bundle: ${mensagem}\n`)
  process.exit(1)
}

async function* arquivosDe(diretorio) {
  let entradas
  try {
    entradas = await readdir(diretorio, { withFileTypes: true })
  } catch {
    reprovar(
      `nao achei ${relative(RAIZ, diretorio)}. Rode \`npm run build\` com a mesma ` +
        'MOBIA_ADMIN_TOKEN antes desta verificacao.',
    )
    return
  }
  for (const entrada of entradas) {
    const caminho = join(diretorio, entrada.name)
    if (entrada.isDirectory()) {
      yield* arquivosDe(caminho)
    } else if (entrada.isFile()) {
      yield caminho
    }
  }
}

const sentinela = process.env.MOBIA_ADMIN_TOKEN

// Reprova em vez de pular: verificacao que pula em silencio e verificacao que
// ninguem nota ter parado de rodar. E a variavel e a MESMA que o build leu --
// uma segunda variavel para manter em sincronia seria a forma de esta checagem
// passar a testar outra coisa.
if (!sentinela) {
  reprovar(
    'MOBIA_ADMIN_TOKEN nao esta setada. Ela precisa valer a mesma sentinela ' +
      'que o `npm run build` viu, senao esta verificacao nao procura nada.',
  )
}

if (sentinela.length < TAMANHO_MINIMO_DA_SENTINELA) {
  reprovar(
    `a sentinela tem ${sentinela.length} caracteres e precisa de ` +
      `${TAMANHO_MINIMO_DA_SENTINELA}. Curta demais, ela casa dentro de ` +
      'identificador minificado e o falso positivo torna a checagem inutil.',
  )
}

const vazados = []
let lidos = 0

for await (const arquivo of arquivosDe(ESTATICOS)) {
  lidos += 1
  // `latin1` e nao `utf8`: preserva byte a byte, entao a sentinela ASCII e
  // achada tambem dentro de arquivo que nao seja texto valido.
  const conteudo = await readFile(arquivo, 'latin1')
  if (conteudo.includes(sentinela)) {
    vazados.push(relative(RAIZ, arquivo))
  }
}

if (vazados.length > 0) {
  reprovar(
    `o token de API esta no bundle que o navegador baixa, em ${vazados.length} ` +
      `arquivo(s):\n  ${vazados.join('\n  ')}\n\n` +
      'Causa quase certa: alguma variavel de ambiente com segredo ganhou o ' +
      'prefixo NEXT_PUBLIC_, que faz o Next embutir o valor literal no codigo ' +
      'de cliente.',
  )
}

console.log(`verificar-bundle: ${lidos} arquivo(s) de .next/static, nenhum com o token.`)
