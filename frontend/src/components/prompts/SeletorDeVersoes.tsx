import type { VersaoResumida } from '@/lib/prompts'

/**
 * Escolher o par de versoes a comparar (TEC-338, D3 do desenho).
 *
 * **Um `<form method="get">`, nao um `<select onChange>` de cliente.** Trocar
 * `de`/`para` e so recarregar a mesma pagina com outros `searchParams` -- o
 * Server Component da pagina de detalhe busca as duas versoes de novo. Sem
 * `'use client'` nenhum aqui.
 */
export function SeletorDeVersoes({
  itens,
  de,
  para,
}: {
  itens: VersaoResumida[]
  de: number
  para: number
}) {
  return (
    <form method="get" className="seletor-de-versoes">
      <label>
        De
        <select name="de" defaultValue={de}>
          <option value={0}>0 (padrão do código)</option>
          {itens.map((versao) => (
            <option key={versao.versao} value={versao.versao}>
              {versao.versao}
            </option>
          ))}
        </select>
      </label>
      <label>
        Para
        <select name="para" defaultValue={para}>
          <option value={0}>0 (padrão do código)</option>
          {itens.map((versao) => (
            <option key={versao.versao} value={versao.versao}>
              {versao.versao}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Comparar</button>
    </form>
  )
}
