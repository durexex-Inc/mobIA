import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
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
    <Cartao className="confirmar-configuracao" role="alertdialog" aria-label="Confirmar alterações">
      <p className="confirmar-configuracao__titulo">Confirma estas alterações?</p>
      <ul className="confirmar-configuracao__linhas">
        {linhas.map((linha, indice) => (
          <li key={`${linha.rotulo}-${indice}`}>
            <strong>{linha.rotulo}:</strong> {linha.de || '—'} → {linha.para || '—'}
          </li>
        ))}
      </ul>
      <div className="confirmar-configuracao__acoes">
        <Botao variante="contorno" onClick={onCancelar} disabled={enviando}>
          Cancelar
        </Botao>
        <Botao onClick={onConfirmar} disabled={enviando}>
          Confirmar
        </Botao>
      </div>
    </Cartao>
  )
}
