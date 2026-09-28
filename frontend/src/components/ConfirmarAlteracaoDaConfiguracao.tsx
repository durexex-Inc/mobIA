import type { LinhaDoDiff } from '@/lib/configuracao'

/**
 * O diff de confirmacao (D4 do desenho): so a apresentacao, sem rede -- quem
 * chama `PATCH` e `FormularioDeConfiguracao.tsx`. Mesmo papel de
 * `RetirarImovel.tsx` no fluxo de confirmacao, com uma lista de linhas no
 * lugar de um texto fixo.
 */
export function ConfirmarAlteracaoDaConfiguracao({
  linhas,
  enviando,
  onConfirmar,
  onCancelar,
}: {
  linhas: LinhaDoDiff[]
  enviando: boolean
  onConfirmar: () => void
  onCancelar: () => void
}) {
  return (
    <div className="confirmar-configuracao" role="alertdialog" aria-label="Confirmar alterações">
      <p>Confirma estas alterações?</p>
      <ul className="confirmar-configuracao__linhas">
        {linhas.map((linha, indice) => (
          <li key={`${linha.rotulo}-${indice}`}>
            <strong>{linha.rotulo}:</strong> {linha.de || '—'} → {linha.para || '—'}
          </li>
        ))}
      </ul>
      <div className="confirmar-configuracao__acoes">
        <button type="button" onClick={onCancelar} disabled={enviando}>
          Cancelar
        </button>
        <button type="button" onClick={onConfirmar} disabled={enviando}>
          Confirmar
        </button>
      </div>
    </div>
  )
}
