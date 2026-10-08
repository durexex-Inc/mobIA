'use client'

import { useRouter } from 'next/navigation'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { BUSCA_MINIMA, buscaEfetiva, type FiltrosDaLista, type Ordem, urlDaLista } from '@/lib/leads'

/** O intervalo depois da ultima tecla (RN-FE-07.3). */
export const ESPERA_DA_BUSCA_MS = 300

/**
 * A caixa de busca da lista de leads (TEC-321, D5) -- o segundo componente de
 * cliente do painel, depois do aviso de inatividade, e pelo mesmo motivo: o
 * debounce nao existe sem JS.
 *
 * **Ela nao busca nada: ela troca a URL.** Quem chama o FastAPI e a pagina, no
 * servidor, com a busca que leu da URL. Por isso este componente so importa
 * `lib/leads`, que e puro -- o `server-only` reprovaria o build se algo de
 * `lib/servidor/` chegasse aqui.
 *
 * - Menos de `BUSCA_MINIMA` caracteres nao navega, e a lista fica como estava.
 * - Zero caracteres navega: apagar a busca devolve a lista inteira.
 * - Sem JS, o `<form method="get">` continua funcionando pelo Enter.
 */
export function BuscaDeLeads({
  inicial,
  ordem,
  filtros,
}: {
  inicial: string
  ordem: Ordem
  filtros?: FiltrosDaLista
}) {
  const router = useRouter()
  const [texto, setTexto] = useState(inicial)
  const espera = useRef<ReturnType<typeof setTimeout> | null>(null)
  // A busca que a URL ja tem: navegar para ela de novo seria uma ida ao
  // servidor para mostrar a mesma lista.
  const aplicada = useRef(buscaEfetiva(inicial) ?? '')

  useEffect(
    () => () => {
      if (espera.current) {
        clearTimeout(espera.current)
      }
    },
    [],
  )

  function aplicar(valor: string) {
    const limpo = valor.trim()
    if (limpo.length > 0 && limpo.length < BUSCA_MINIMA) {
      return
    }
    const alvo = buscaEfetiva(valor) ?? ''
    if (alvo === aplicada.current) {
      return
    }
    aplicada.current = alvo
    // Os filtros ficam, e a posicao nao (D1 da TEC-322).
    router.replace(urlDaLista({ busca: alvo || undefined, ordem, filtros }))
  }

  function aoDigitar(valor: string) {
    setTexto(valor)
    if (espera.current) {
      clearTimeout(espera.current)
    }
    espera.current = setTimeout(() => aplicar(valor), ESPERA_DA_BUSCA_MS)
  }

  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    // Com JS, o Enter aplica na hora, pela mesma regra; sem JS, o formulario
    // faz o GET sozinho e a pagina aplica a regra do lado dela.
    evento.preventDefault()
    if (espera.current) {
      clearTimeout(espera.current)
    }
    aplicar(texto)
  }

  return (
    <form className="leads-busca" method="get" action="/leads" role="search" onSubmit={aoEnviar}>
      <input
        type="search"
        name="busca"
        className="campo"
        aria-label="Buscar por telefone ou bairro"
        placeholder="Buscar por telefone ou bairro"
        value={texto}
        onChange={(evento) => aoDigitar(evento.target.value)}
      />
      {/* A ordem vai junto, para buscar nao desfazer a ordenacao. */}
      {ordem !== 'score_desc' && <input type="hidden" name="ordenar" value={ordem} />}
      {/* E os filtros, pelo mesmo motivo (TEC-322). */}
      {Object.entries(filtros ?? {}).map(([chave, valor]) =>
        valor ? <input key={chave} type="hidden" name={chave} value={valor} /> : null,
      )}
    </form>
  )
}
