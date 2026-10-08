'use client'

import dynamic from 'next/dynamic'

import { registrarLinguagemDoPrompt, TEMA_DO_MONACO } from '@/components/prompts/linguagemDoPrompt'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'
import { useTemaAtual } from '@/lib/useTemaAtual'

// Mesmo `ssr: false` e mesmo pacote de `EditorDePrompt` -- os dois so
// aparecem na arvore de modulos da rota de detalhe de prompts (D6 do
// desenho).
const DiffEditor = dynamic(() => import('@monaco-editor/react').then((m) => m.DiffEditor), {
  ssr: false,
})

/**
 * O diff lado a lado entre duas versoes (TEC-338, D3/D4 do desenho).
 *
 * **Recebe os dois textos como prop, sem fetch proprio.** Trocar qual par
 * comparar e a pagina de detalhe navegando para `?de=X&para=Y` -- um Server
 * Component novo busca as duas versoes com `chamarApi` e re-renderiza esta
 * arvore com props novas, o mesmo jeito que o resto do painel evita estado de
 * cliente para dado que da para buscar de novo.
 *
 * **O `DiffEditor` do proprio Monaco faz o lado a lado** -- nao ha segunda
 * biblioteca de diff (`jsdiff`, `react-diff-viewer`) neste repo so para
 * recalcular o que o Monaco ja sabe fazer.
 */
export function DiffDePrompt({
  textoDe,
  textoPara,
  rotuloDe,
  rotuloPara,
}: {
  textoDe: string
  textoPara: string
  rotuloDe: string
  rotuloPara: string
}) {
  const tema = useTemaAtual()
  return (
    <Cartao className="diff-de-prompt">
      <div className="diff-de-prompt__rotulos">
        <p className="diff-de-prompt__rotulo">
          <span className="diff-de-prompt__ponto diff-de-prompt__ponto--de" aria-hidden="true" />
          <span>{rotuloDe}</span>
          <Selo>Origem</Selo>
        </p>
        <p className="diff-de-prompt__rotulo">
          <span className="diff-de-prompt__ponto diff-de-prompt__ponto--para" aria-hidden="true" />
          <span>{rotuloPara}</span>
          <Selo>Destino</Selo>
        </p>
      </div>
      <DiffEditor
        height="400px"
        original={textoDe}
        modified={textoPara}
        beforeMount={(monaco) => registrarLinguagemDoPrompt(monaco)}
        originalLanguage="prompt-mobia"
        modifiedLanguage="prompt-mobia"
        theme={TEMA_DO_MONACO[tema]}
        options={{ readOnly: true, minimap: { enabled: false }, wordWrap: 'on' }}
      />
    </Cartao>
  )
}
