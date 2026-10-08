import { Botao } from '@/components/ui/Botao'
import { CampoDeSelecao } from '@/components/ui/CampoDeSelecao'
import { Cartao } from '@/components/ui/Cartao'
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
    <Cartao className="seletor-de-versoes-cartao">
      <form method="get" className="seletor-de-versoes">
        <label>
          De
          <CampoDeSelecao name="de" defaultValue={de}>
            <option value={0}>0 (padrão do código)</option>
            {itens.map((versao) => (
              <option key={versao.versao} value={versao.versao}>
                {versao.versao}
              </option>
            ))}
          </CampoDeSelecao>
        </label>
        <label>
          Para
          <CampoDeSelecao name="para" defaultValue={para}>
            <option value={0}>0 (padrão do código)</option>
            {itens.map((versao) => (
              <option key={versao.versao} value={versao.versao}>
                {versao.versao}
              </option>
            ))}
          </CampoDeSelecao>
        </label>
        <Botao type="submit" variante="contorno">
          Comparar
        </Botao>
      </form>
    </Cartao>
  )
}
