/**
 * Previa de CSV so do cliente, e o CSV de rejeicoes para download (TEC-334).
 *
 * D1 do desenho: a previa espelha SO as duas escolhas do parser real
 * (`domain/catalogo/parser.py::_delimitador`/`_decodificar`) -- delimitador
 * `;` ou `,` pelo cabecalho, e BOM opcional -- e nao o `csv.DictReader`
 * inteiro. Campo entre aspas com QUEBRA DE LINHA dentro (registro que ocupa
 * mais de uma linha fisica) nao e tratado: e a degradacao aceita e declarada
 * no desenho, porque a previa e conveniencia, quem valida de verdade e o
 * backend, depois do envio. Aspas e delimitador DENTRO de uma linha sao
 * tratados, porque isso nao exige olhar alem da linha atual.
 *
 * D5: `linhasParaCsv` gera o CSV de download das linhas rejeitadas, com
 * escape RFC 4180 minimo escrito a mao -- a mesma razao de D1 para nao trazer
 * uma dependencia de CSV so para isto.
 */

export type PreviaDoCsv = {
  colunas: string[]
  linhas: string[][]
}

export type LinhaRejeitada = {
  linha: number
  motivo: string
}

const MAXIMO_DE_LINHAS_NA_PREVIA = 10

/** `TextDecoder`/manual: o caractere BOM (U+FEFF), quando o arquivo o tiver. */
function semBom(texto: string): string {
  return texto.charCodeAt(0) === 0xfeff ? texto.slice(1) : texto
}

/**
 * A mesma escolha de `_delimitador` do parser real: `;` ganha quando aparece
 * MAIS VEZES que `,` no cabecalho -- estritamente mais, empate fica com `,`.
 */
function delimitador(cabecalho: string): string {
  const pontoEVirgula = cabecalho.split(';').length - 1
  const virgula = cabecalho.split(',').length - 1
  return pontoEVirgula > virgula ? ';' : ','
}

/**
 * Uma linha fisica em campos, respeitando aspas -- mas so DENTRO da linha:
 * nao ha estado entre chamadas, entao um campo entre aspas que atravessasse
 * uma quebra de linha sairia cortado. Ver a docstring do modulo.
 */
function dividirLinha(linha: string, delim: string): string[] {
  const campos: string[] = []
  let atual = ''
  let dentroDeAspas = false

  for (let i = 0; i < linha.length; i++) {
    const caractere = linha[i]
    if (dentroDeAspas) {
      if (caractere === '"' && linha[i + 1] === '"') {
        atual += '"'
        i++
      } else if (caractere === '"') {
        dentroDeAspas = false
      } else {
        atual += caractere
      }
    } else if (caractere === '"') {
      dentroDeAspas = true
    } else if (caractere === delim) {
      campos.push(atual)
      atual = ''
    } else {
      atual += caractere
    }
  }
  campos.push(atual)
  return campos
}

/**
 * As colunas e as 10 primeiras linhas de DADOS do arquivo, como vieram --
 * sem remapear para os nomes do formulario da TEC-333 (D1): e uma previa do
 * arquivo, nao do que vai ser gravado.
 */
export function previaDoCsv(conteudo: string): PreviaDoCsv {
  const texto = semBom(conteudo)
  const todasAsLinhas = texto.split(/\r\n|\n|\r/).filter((linha) => linha.length > 0)
  if (todasAsLinhas.length === 0) {
    return { colunas: [], linhas: [] }
  }

  const delim = delimitador(todasAsLinhas[0])
  const colunas = dividirLinha(todasAsLinhas[0], delim)
  const linhas = todasAsLinhas
    .slice(1, 1 + MAXIMO_DE_LINHAS_NA_PREVIA)
    .map((linha) => dividirLinha(linha, delim))

  return { colunas, linhas }
}

/** Aspas quando o campo contem virgula, aspas ou quebra de linha -- RFC 4180 minimo. */
function escaparCampo(valor: string): string {
  if (/[",\n]/.test(valor)) {
    return `"${valor.replace(/"/g, '""')}"`
  }
  return valor
}

/** O CSV de download das linhas rejeitadas (D5): `linha,motivo`, uma por erro. */
export function linhasParaCsv(erros: readonly LinhaRejeitada[]): string {
  const linhas = erros.map((erro) => `${erro.linha},${escaparCampo(erro.motivo)}`)
  return ['linha,motivo', ...linhas].join('\n')
}
