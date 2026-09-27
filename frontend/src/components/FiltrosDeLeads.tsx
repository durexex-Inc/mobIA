'use client'

import { useRouter } from 'next/navigation'
import type { FormEvent } from 'react'

import {
  CANAIS,
  type FiltrosDaLista,
  filtrosDaUrl,
  type Ordem,
  STATUS,
  TEMPERATURAS,
  urlDaLista,
} from '@/lib/leads'

/**
 * Como o filtro por corretor aparece, por papel (TEC-322, D5). So o ADMIN tem
 * de onde tirar os nomes (`GERIR_CORRETORES`); para a GERENTE e a LEITURA ele
 * fica desabilitado, como o do funil na TEC-316; para o CORRETOR, que o
 * backend ja recorta pela carteira, ele nem aparece.
 */
export type FiltroPorCorretor =
  | { modo: 'lista'; opcoes: Array<{ id: string; nome: string }> }
  | { modo: 'indisponivel' }
  | { modo: 'oculto' }

/**
 * Os filtros da lista de leads (TEC-322, D5). Um `<form method="get">`: sem
 * JS, "Filtrar" faz o GET; com JS, mudar uma lista ja aplica, e a URL sai
 * limpa, sem os `status=` vazios que o navegador poria.
 *
 * **Mudar filtro volta a primeira pagina** (D1): a URL montada aqui nao leva
 * posicao, e a busca e a ordem vao junto.
 */
export function FiltrosDeLeads({
  busca,
  ordem,
  filtros,
  corretor,
}: {
  busca?: string
  ordem: Ordem
  filtros: FiltrosDaLista
  corretor: FiltroPorCorretor
}) {
  const router = useRouter()

  function aplicar(formulario: HTMLFormElement) {
    const dados = Object.fromEntries(
      Array.from(new FormData(formulario).entries()).map(([chave, valor]) => [chave, String(valor)]),
    )
    router.push(urlDaLista({ busca, ordem, filtros: filtrosDaUrl(dados) }))
  }

  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    aplicar(evento.currentTarget)
  }

  // O `corretorId` que a URL trouxe continua valendo quando a lista nao pode
  // ser escolhida: um link filtrado pela ADMIN abre filtrado para a GERENTE.
  const corretorPreservado = corretor.modo !== 'lista' && filtros.corretorId

  return (
    <form
      className="leads-filtros"
      method="get"
      action="/leads"
      aria-label="Filtros"
      onSubmit={aoEnviar}
      onChange={(evento) => aplicar(evento.currentTarget)}
    >
      {busca && <input type="hidden" name="busca" value={busca} />}
      {ordem !== 'score_desc' && <input type="hidden" name="ordenar" value={ordem} />}
      <Lista rotulo="Status" nome="status" opcoes={STATUS} valor={filtros.status} />
      <Lista rotulo="Temperatura" nome="temperatura" opcoes={TEMPERATURAS} valor={filtros.temperatura} />
      <Lista rotulo="Canal" nome="canal" opcoes={CANAIS} valor={filtros.canal} />
      {corretor.modo === 'lista' && (
        <Lista
          rotulo="Corretor"
          nome="corretorId"
          opcoes={Object.fromEntries(corretor.opcoes.map((c) => [c.id, c.nome]))}
          valor={filtros.corretorId}
        />
      )}
      {corretor.modo === 'indisponivel' && (
        <label className="leads-filtro">
          Corretor
          <select disabled aria-describedby="filtro-corretor-motivo">
            <option>Todos</option>
          </select>
          <span id="filtro-corretor-motivo" className="leads-filtro-motivo">
            Filtro por corretor indisponível para o seu papel.
          </span>
        </label>
      )}
      {corretorPreservado && (
        <>
          <input type="hidden" name="corretorId" value={filtros.corretorId} />
          <p className="leads-filtro-corretor">
            Filtrada por um corretor.{' '}
            <a href={urlDaLista({ busca, ordem, filtros: { ...filtros, corretorId: undefined } })}>
              Remover filtro
            </a>
          </p>
        </>
      )}
      <button type="submit">Filtrar</button>
    </form>
  )
}

function Lista({
  rotulo,
  nome,
  opcoes,
  valor,
}: {
  rotulo: string
  nome: string
  opcoes: Record<string, string>
  valor?: string
}) {
  return (
    <label className="leads-filtro">
      {rotulo}
      <select name={nome} defaultValue={valor ?? ''}>
        <option value="">Todos</option>
        {Object.entries(opcoes).map(([chave, texto]) => (
          <option key={chave} value={chave}>
            {texto}
          </option>
        ))}
      </select>
    </label>
  )
}
