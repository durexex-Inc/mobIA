import type Monaco from 'monaco-editor'

/**
 * O realce de `{assistente}`/`{tom}` (RN-FE-14.1, D4 do desenho).
 *
 * Uma linguagem Monarch minima, so para o marcador `{palavra}` -- a mesma
 * forma que `domain/prompts/modelo.py::_MARCADOR` reconhece no backend. Usada
 * tanto no editor de edicao quanto nos dois lados do `DiffEditor`, registrada
 * uma vez so (`registrada`, module-level: os dois componentes montam na mesma
 * instancia de Monaco carregada pelo `@monaco-editor/react`).
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
    registrada = true
  }
  return ID_DA_LINGUAGEM
}
