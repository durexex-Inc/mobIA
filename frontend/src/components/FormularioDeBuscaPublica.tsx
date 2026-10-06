'use client'

import { useRouter } from 'next/navigation'
import type { FormEvent } from 'react'

import { filtrosDaUrl, type FiltrosDoPortal, urlDaBusca } from '@/lib/buscaPublica'
import { OPERACOES, TIPOS_DE_IMOVEL, type TipoImovel } from '@/lib/imoveis'

/**
 * Os filtros da vitrine publica (TEC-387, D5 do desenho). `<form method="get">`,
 * no molde de `FiltrosDeAuditoria`: sem JS, "Buscar" faz o GET direto; com JS,
 * o envio atualiza a URL por `router.push` e quem busca de novo e
 * `app/busca/page.tsx`, no servidor.
 *
 * **Preco em REAIS no campo, centavos na URL.** `filtrosDaUrl` converte na
 * fronteira, igual a `pedidoDeCadastro` em `lib/imoveis.ts` -- o usuario
 * digita o que esta acostumado a ver, e a API fala centavos.
 */
export function FormularioDeBuscaPublica({ filtros }: { filtros: FiltrosDoPortal }) {
  const router = useRouter()

  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    const dados = Object.fromEntries(
      Array.from(new FormData(evento.currentTarget).entries()).map(([chave, valor]) => [chave, String(valor)]),
    )
    router.push(urlDaBusca(filtrosDaUrl(dados)))
  }

  return (
    <form
      className="busca-publica__formulario"
      method="get"
      action="/busca"
      aria-label="Buscar imóveis"
      onSubmit={aoEnviar}
    >
      <label className="busca-publica__campo">
        Operação
        <select name="operacao" defaultValue={filtros.operacao}>
          <option value="VENDA">{OPERACOES.VENDA}</option>
          <option value="ALUGUEL">{OPERACOES.ALUGUEL}</option>
        </select>
      </label>
      <label className="busca-publica__campo">
        Preço mínimo
        <input
          type="text"
          inputMode="decimal"
          name="precoMin"
          defaultValue={filtros.precoMinCentavos !== undefined ? String(filtros.precoMinCentavos / 100) : ''}
        />
      </label>
      <label className="busca-publica__campo">
        Preço máximo
        <input
          type="text"
          inputMode="decimal"
          name="precoMax"
          defaultValue={filtros.precoMaxCentavos !== undefined ? String(filtros.precoMaxCentavos / 100) : ''}
        />
      </label>
      <label className="busca-publica__campo">
        Tipo
        <select name="tipo" defaultValue={filtros.tipo ?? ''}>
          <option value="">Qualquer tipo</option>
          {(Object.keys(TIPOS_DE_IMOVEL) as TipoImovel[]).map((tipo) => (
            <option key={tipo} value={tipo}>
              {TIPOS_DE_IMOVEL[tipo]}
            </option>
          ))}
        </select>
      </label>
      <label className="busca-publica__campo">
        Quartos (mínimo)
        <input type="number" min={0} name="quartosMin" defaultValue={filtros.quartosMin ?? ''} />
      </label>
      <label className="busca-publica__campo">
        Vagas (mínimo)
        <input type="number" min={0} name="vagasMin" defaultValue={filtros.vagasMin ?? ''} />
      </label>
      <label className="busca-publica__campo">
        Bairro ou região
        <input
          type="text"
          name="regioes"
          placeholder="ex.: Centro, Trindade"
          defaultValue={(filtros.regioes ?? []).join(', ')}
        />
      </label>
      <button type="submit">Buscar</button>
    </form>
  )
}
