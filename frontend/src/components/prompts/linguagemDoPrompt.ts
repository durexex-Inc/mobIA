import type Monaco from 'monaco-editor'

import type { Tema } from '@/lib/tema'

/**
 * O tema do Monaco para cada tema do painel (TEC-395).
 *
 * **As cores repetem os tokens de `globals.css` (`--superficie`, `--primaria`)**
 * porque o Monaco pinta por JS e nao le variavel CSS. Mudou o token, muda aqui.
 */
export const TEMA_DO_MONACO: Record<Tema, string> = {
  claro: 'mobia-claro',
  escuro: 'mobia-escuro',
}

/**
 * O realce de `{assistente}`/`{tom}` (RN-FE-14.1, D4 do desenho).
 *
 * Uma linguagem Monarch minima, so para o marcador `{palavra}` -- a mesma
 * forma que `domain/prompts/modelo.py::_MARCADOR` reconhece no backend. Usada
 * tanto no editor de edicao quanto nos dois lados do `DiffEditor`, registrada
 * uma vez so (`registrada`, module-level: os dois componentes montam na mesma
 * instancia de Monaco carregada pelo `@monaco-editor/react`). Define junto os
 * dois temas de `TEMA_DO_MONACO` (TEC-395), pelo mesmo motivo.
 */
const ID_DA_LINGUAGEM = 'prompt-mobia'

let registrada = false

export function registrarLinguagemDoPrompt(monaco: typeof Monaco): string {
  if (!registrada) {
    monaco.languages.register({ id: ID_DA_LINGUAGEM })
    monaco.languages.setMonarchTokensProvider(ID_DA_LINGUAGEM, {
      tokenizer: {
        root: [[/\{[A-Za-z_]+\}/, 'keyword']],
      },
    })
    monaco.editor.defineTheme(TEMA_DO_MONACO.claro, {
      base: 'vs',
      inherit: true,
      rules: [{ token: 'keyword', foreground: '2563eb', fontStyle: 'bold' }],
      colors: { 'editor.background': '#ffffff' },
    })
    monaco.editor.defineTheme(TEMA_DO_MONACO.escuro, {
      base: 'vs-dark',
      inherit: true,
      rules: [{ token: 'keyword', foreground: '60a5fa', fontStyle: 'bold' }],
      colors: { 'editor.background': '#141518' },
    })
    registrada = true
  }
  return ID_DA_LINGUAGEM
}
