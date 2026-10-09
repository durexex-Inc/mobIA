'use client'

import { useRouter } from 'next/navigation'
import type { FormEvent } from 'react'

import { IconeDoPortal } from '@/components/IconeDoPortal'
import { filtrosDaUrl, type FiltrosDoPortal, urlDaBusca } from '@/lib/buscaPublica'
import { TIPOS_DE_IMOVEL, type TipoImovel } from '@/lib/imoveis'

/** Os minimos que os botoes de quartos e o seletor de vagas oferecem. */
const MINIMOS = [1, 2, 3, 4] as const

/**
 * Os filtros da vitrine publica (TEC-387, D5 do desenho; barra no visual do
 * portal, D7). `<form method="get">`, no molde de `FiltrosDeAuditoria`: sem
 * JS, "Buscar" faz o GET direto; com JS, o envio atualiza a URL por
 * `router.push` e quem busca de novo e `app/busca/page.tsx`, no servidor.
 *
 * **Buscar volta para a primeira pagina**: `pagina` nao e campo do
 * formulario, entao some da URL. A ordem escolhida vai num campo oculto e
 * sobrevive -- quem pediu "menor preco" nao quer perder isso ao trocar o
 * bairro.
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
    <form className="portal-filtros" method="get" action="/busca" aria-label="Buscar imóveis" onSubmit={aoEnviar}>
      <fieldset className="portal-alternancia">
        <legend className="visually-hidden">Operação</legend>
        <label>
          <input type="radio" name="operacao" value="VENDA" defaultChecked={filtros.operacao === 'VENDA'} />
          <span>Comprar</span>
        </label>
        <label>
          <input type="radio" name="operacao" value="ALUGUEL" defaultChecked={filtros.operacao === 'ALUGUEL'} />
          <span>Alugar</span>
        </label>
      </fieldset>

      <label className="portal-filtro portal-filtro--largo">
        <span className="portal-filtro__rotulo">Bairro ou região</span>
        <span className="portal-filtro__campo">
          <IconeDoPortal nome="pino" />
          <input
            type="text"
            name="regioes"
            placeholder="Centro, Trindade"
            defaultValue={(filtros.regioes ?? []).join(', ')}
          />
        </span>
      </label>

      <label className="portal-filtro">
        <span className="portal-filtro__rotulo">Tipo</span>
        <select name="tipo" defaultValue={filtros.tipo ?? ''}>
          <option value="">Qualquer tipo</option>
          {(Object.keys(TIPOS_DE_IMOVEL) as TipoImovel[]).map((tipo) => (
            <option key={tipo} value={tipo}>
              {TIPOS_DE_IMOVEL[tipo]}
            </option>
          ))}
        </select>
      </label>

      <div className="portal-filtro portal-filtro--preco">
        <label>
          <span className="portal-filtro__rotulo">Preço mínimo</span>
          <input
            type="text"
            inputMode="decimal"
            name="precoMin"
            placeholder="R$"
            defaultValue={filtros.precoMinCentavos !== undefined ? String(filtros.precoMinCentavos / 100) : ''}
          />
        </label>
        <label>
          <span className="portal-filtro__rotulo">Preço máximo</span>
          <input
            type="text"
            inputMode="decimal"
            name="precoMax"
            placeholder="R$"
            defaultValue={filtros.precoMaxCentavos !== undefined ? String(filtros.precoMaxCentavos / 100) : ''}
          />
        </label>
      </div>

      <fieldset className="portal-filtro portal-botoes-de-minimo">
        <legend className="portal-filtro__rotulo">Quartos</legend>
        <div>
          <label>
            <input type="radio" name="quartosMin" value="" defaultChecked={filtros.quartosMin === undefined} />
            <span>Todos</span>
          </label>
          {MINIMOS.map((minimo) => (
            <label key={minimo}>
              <input
                type="radio"
                name="quartosMin"
                value={minimo}
                defaultChecked={filtros.quartosMin === minimo}
                aria-label={`${minimo} ou mais quartos`}
              />
              <span aria-hidden="true">{minimo}+</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="portal-filtro">
        <span className="portal-filtro__rotulo">Vagas</span>
        <select name="vagasMin" defaultValue={filtros.vagasMin !== undefined ? String(filtros.vagasMin) : ''}>
          <option value="">Qualquer</option>
          {MINIMOS.map((minimo) => (
            <option key={minimo} value={minimo}>
              {minimo}+
            </option>
          ))}
        </select>
      </label>

      {filtros.ordem && <input type="hidden" name="ordem" value={filtros.ordem} />}

      <button type="submit" className="portal-botao portal-botao--primario portal-filtros__buscar">
        Buscar
      </button>
    </form>
  )
}
