'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'

import type { AgenteDaRota, LimitesDoPrompt } from '@/lib/prompts'
import { nomeDoAgenteNaApi } from '@/lib/prompts'
import { registrarLinguagemDoPrompt } from '@/components/prompts/linguagemDoPrompt'

// `ssr: false`: o Monaco fala com o DOM e o `window` direto, e nao roda no
// servidor. Este e o UNICO lugar do editor de edicao que importa
// `@monaco-editor/react` -- e o que garante que so a rota de detalhe de
// prompts baixa o pacote (D6 do desenho, quarto cenario do Gherkin).
const Editor = dynamic(() => import('@monaco-editor/react'), { ssr: false })

type Resposta =
  | { publicada: true; ativa: { versao: number } }
  | { publicada: false; ativa: { versao: number } }

/**
 * Editar o texto de um agente e publicar uma nova versao (TEC-338, D4/D5/D6
 * do desenho).
 *
 * **Nao tem checagem de concorrencia (`seVersao`)** -- ao contrario de
 * `FormularioDeConfiguracao` (TEC-337): o Gherkin desta card nao tem cenario
 * de edicao simultanea, e duas publicacoes de verdade ao mesmo tempo ainda
 * colidem no `409` que a TEC-199 ja responde por conta do numero de versao.
 *
 * **A validacao de marcador/tamanho e so do backend** (D5): o contador de
 * caracteres contra `limites.maximoDeCaracteres` e um indicador, e o `422`
 * (`ModeloInvalido`) e mostrado como veio, mesma regra de
 * `lib/configuracao.ts::recusaDe` para o 422.
 */
export function EditorDePrompt({
  agente,
  textoInicial,
  limites,
}: {
  agente: AgenteDaRota
  textoInicial: string
  limites: LimitesDoPrompt
}) {
  const router = useRouter()
  const [texto, setTexto] = useState(textoInicial)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  async function publicar() {
    setEnviando(true)
    setErro(null)
    setAviso(null)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/prompts/${nomeDoAgenteNaApi(agente)}/versoes`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ texto }),
      })
    } catch {
      setEnviando(false)
      setErro('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    let dados: Record<string, unknown> = {}
    try {
      dados = (await resposta.json()) as Record<string, unknown>
    } catch {
      dados = {}
    }
    setEnviando(false)

    if (!resposta.ok) {
      setErro(typeof dados.detail === 'string' ? dados.detail : 'Não foi possível publicar. Tente de novo.')
      return
    }

    const corpo = dados as Resposta
    if (!corpo.publicada) {
      setAviso('O texto é igual ao vigente; nada foi publicado.')
      return
    }

    // Traz a nova versao ativa e o historico atualizado -- mesmo `router.refresh()`
    // que `FormularioDeConfiguracao` usa apos salvar (TEC-337).
    router.refresh()
  }

  return (
    <div className="editor-de-prompt">
      <p className="editor-de-prompt__limites">
        Marcadores obrigatórios: {limites.marcadores.join(', ')}. Até {limites.maximoDeCaracteres}{' '}
        caracteres no pior caso. Caracteres agora: {texto.length}.
      </p>
      <Editor
        height="400px"
        value={texto}
        onChange={(valor) => setTexto(valor ?? '')}
        beforeMount={(monaco) => registrarLinguagemDoPrompt(monaco)}
        defaultLanguage="prompt-mobia"
        options={{ minimap: { enabled: false }, wordWrap: 'on' }}
      />
      {erro && (
        <p className="editor-de-prompt__erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="editor-de-prompt__aviso">{aviso}</p>}
      <div className="editor-de-prompt__acoes">
        <button type="button" onClick={publicar} disabled={enviando}>
          Publicar
        </button>
      </div>
    </div>
  )
}
