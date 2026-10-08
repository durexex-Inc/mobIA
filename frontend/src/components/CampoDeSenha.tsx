'use client'

import { useId, useState } from 'react'

/**
 * O campo de senha do login, com o alternador de mostrar/ocultar da
 * referencia visual.
 *
 * **So o `type` do input muda** -- nome, `required` e `autoComplete` ficam
 * fixos no componente, entao o teste de `PaginaDeLogin` continua achando o
 * campo por `getByLabelText('Senha')` com `type="password"` por padrao.
 */
export function CampoDeSenha({ rotulo = 'Senha' }: { rotulo?: string }) {
  const [visivel, setVisivel] = useState(false)
  const id = useId()

  return (
    <div className="login-campo">
      <label htmlFor={id}>{rotulo}</label>
      <div className="login-campo-com-icone">
        <CadeadoIcone />
        <input
          id={id}
          name="senha"
          type={visivel ? 'text' : 'password'}
          autoComplete="current-password"
          required
          className="login-campo-com-alternador"
        />
        <button
          type="button"
          className="login-alternar-senha"
          aria-label={visivel ? 'Ocultar senha' : 'Mostrar senha'}
          aria-pressed={visivel}
          onClick={() => setVisivel((atual) => !atual)}
        >
          <OlhoIcone aberto={visivel} />
        </button>
      </div>
    </div>
  )
}

function CadeadoIcone() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="login-icone-do-campo"
    >
      <rect x="4" y="11" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7.5 11V8a4.5 4.5 0 0 1 9 0v3" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function OlhoIcone({ aberto }: { aberto: boolean }) {
  if (aberto) {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    )
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 3l18 18M10.6 10.7a3 3 0 0 0 4.2 4.2M6.2 6.4C3.9 8 2 12 2 12s3.5 7 10 7c1.9 0 3.5-.5 4.8-1.3M17.9 17.9C20.1 16.2 22 12 22 12s-1-2-2.8-3.8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
