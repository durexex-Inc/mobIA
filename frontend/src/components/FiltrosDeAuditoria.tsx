'use client'

import { useRouter } from 'next/navigation'
import type { FormEvent } from 'react'

import { ACOES, type FiltrosDaTrilha, filtrosDaUrl, urlDaLista } from '@/lib/auditoria'

/**
 * Os filtros da trilha (D1, D3 e D4 do desenho): autor (texto livre --
 * `usuario_id`, sem apelido, ver a lacuna L1), tipo (um por vez, D3) e
 * período (duas datas, D4). `<form method="get">`, no molde de
 * `FiltrosDeLeads`: sem JS, "Filtrar" faz o GET; com JS, mudar um campo já
 * aplica.
 *
 * **Mudar filtro volta à primeira página**: a URL montada aqui não leva
 * posição.
 */
export function FiltrosDeAuditoria({ filtros }: { filtros: FiltrosDaTrilha }) {
  const router = useRouter()

  function aplicar(formulario: HTMLFormElement) {
    const dados = Object.fromEntries(
      Array.from(new FormData(formulario).entries()).map(([chave, valor]) => [chave, String(valor)]),
    )
    router.push(urlDaLista({ filtros: filtrosDaUrl(dados) }))
  }

  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    aplicar(evento.currentTarget)
  }

  return (
    <form
      className="auditoria-filtros"
      method="get"
      action="/admin/auditoria"
      aria-label="Filtros"
      onSubmit={aoEnviar}
      onChange={(evento) => aplicar(evento.currentTarget)}
    >
      <label className="auditoria-filtro">
        Autor
        <input type="text" name="ator" defaultValue={filtros.ator ?? ''} placeholder="Identificador do usuário" />
      </label>
      <label className="auditoria-filtro">
        Tipo
        <select name="acao" defaultValue={filtros.acao ?? ''}>
          <option value="">Todos</option>
          {Object.entries(ACOES).map(([chave, texto]) => (
            <option key={chave} value={chave}>
              {texto}
            </option>
          ))}
        </select>
      </label>
      <label className="auditoria-filtro">
        De
        <input type="date" name="de" defaultValue={filtros.de ?? ''} />
      </label>
      <label className="auditoria-filtro">
        Até
        <input type="date" name="ate" defaultValue={filtros.ate ?? ''} />
      </label>
      <button type="submit">Filtrar</button>
    </form>
  )
}
