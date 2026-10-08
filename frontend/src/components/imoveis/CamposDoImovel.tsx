'use client'

import { useId } from 'react'

import { Botao } from '@/components/ui/Botao'
import { CampoDeSelecao as Selecao } from '@/components/ui/CampoDeSelecao'
import type { CampoDeTexto as CampoDeTextoDoFormulario, Formulario, Recusa } from '@/lib/imoveis'

/**
 * Os campos do imovel, comuns ao cadastro (`FormularioDeImovel`) e a pagina
 * de edicao (`EdicaoDeImovel`, TEC-400).
 *
 * O asterisco de obrigatorio sai do CSS (`.rotulo--obrigatorio::after`, D4 da
 * TEC-397), para nao entrar no nome acessivel: o campo leva `aria-required`.
 */

type PropsDoCampo = {
  rotulo: string
  atual: Formulario
  recusa: Recusa
  mudar: (campo: CampoDeTextoDoFormulario, valor: string) => void
}

function Erro({ id, texto }: { id: string; texto?: string }) {
  return texto ? (
    <span id={id} className="formulario-de-imovel__erro">
      {texto}
    </span>
  ) : null
}

export function CampoDeTexto({
  rotulo,
  campo,
  obrigatorio,
  exemplo,
  prefixo,
  sufixo,
  ajuda,
  id: idFixo,
  atual,
  recusa,
  mudar,
  disabled,
}: PropsDoCampo & {
  campo: CampoDeTextoDoFormulario
  obrigatorio?: boolean
  exemplo?: string
  prefixo?: string
  sufixo?: string
  ajuda?: string
  id?: string
  disabled?: boolean
}) {
  const idGerado = useId()
  const id = idFixo ?? idGerado
  const erro = recusa.porCampo[campo]
  const classes = [
    'campo-com-unidade',
    prefixo && 'campo-com-unidade--prefixo',
    sufixo && 'campo-com-unidade--sufixo',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div className="formulario-de-imovel__campo">
      <label htmlFor={id} className={obrigatorio ? 'rotulo--obrigatorio' : undefined}>
        {rotulo}
      </label>
      <span className={classes}>
        {prefixo && (
          <span className="campo-com-unidade__prefixo" aria-hidden="true">
            {prefixo}
          </span>
        )}
        <input
          id={id}
          className="campo"
          type="text"
          placeholder={exemplo}
          value={atual[campo]}
          onChange={(evento) => mudar(campo, evento.target.value)}
          disabled={disabled}
          aria-required={obrigatorio ? true : undefined}
          aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? `${id}-erro` : undefined}
        />
        {sufixo && (
          <span className="campo-com-unidade__sufixo" aria-hidden="true">
            {sufixo}
          </span>
        )}
      </span>
      <Erro id={`${id}-erro`} texto={erro} />
      {ajuda && <span className="formulario-de-imovel__ajuda">{ajuda}</span>}
    </div>
  )
}

export function CampoDeSelecao<T extends string>({
  rotulo,
  valor,
  opcoes,
  rotulos,
  erro,
  mudar,
}: {
  rotulo: string
  valor: T | ''
  opcoes: readonly T[]
  rotulos: Record<T, string>
  erro?: string
  mudar: (valor: string) => void
}) {
  const id = useId()
  return (
    <div className="formulario-de-imovel__campo">
      <label htmlFor={id} className="rotulo--obrigatorio">
        {rotulo}
      </label>
      <Selecao
        id={id}
        value={valor}
        onChange={(evento) => mudar(evento.target.value)}
        aria-required
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      >
        <option value="">Selecione</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {rotulos[opcao]}
          </option>
        ))}
      </Selecao>
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

/**
 * "Diferencial" da card (D1 da TEC-333) -- texto livre, um chip por item, no
 * mesmo molde de `CampoDeRegioes` em `FormularioDeCorretor.tsx`. Os chips
 * ficam numa linha propria, embaixo do campo (TEC-398).
 */
export function CampoDeCaracteristicas({
  caracteristicas,
  novo,
  mudarNovo,
  adicionar,
  remover,
}: {
  caracteristicas: string[]
  novo: string
  mudarNovo: (valor: string) => void
  adicionar: () => void
  remover: (indice: number) => void
}) {
  const id = useId()
  return (
    <>
      <div className="formulario-de-imovel__campo">
        <label htmlFor={id}>Diferenciais</label>
        <input
          id={id}
          className="campo"
          type="text"
          placeholder="Ex.: Piscina, varanda gourmet"
          value={novo}
          onChange={(evento) => mudarNovo(evento.target.value)}
          onKeyDown={(evento) => {
            if (evento.key === 'Enter') {
              evento.preventDefault()
              adicionar()
            }
          }}
        />
        <Botao variante="contorno" onClick={adicionar}>
          <span aria-hidden="true">+</span> Adicionar diferencial
        </Botao>
      </div>
      {caracteristicas.length > 0 && (
        <div className="formulario-de-imovel__diferenciais">
          <p>Diferenciais selecionados:</p>
          <ul className="chips">
            {caracteristicas.map((item, indice) => (
              <li key={`${item}-${indice}`} className="chip">
                {item}
                <button
                  type="button"
                  className="chip__remover"
                  onClick={() => remover(indice)}
                  aria-label={`Remover ${item}`}
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
