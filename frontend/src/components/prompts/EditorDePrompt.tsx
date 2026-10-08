'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'

import type { AgenteDaRota, LimitesDoPrompt } from '@/lib/prompts'
import { marcadoresNoTexto, nomeDoAgenteNaApi } from '@/lib/prompts'
import { registrarLinguagemDoPrompt, TEMA_DO_MONACO } from '@/components/prompts/linguagemDoPrompt'
import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'
import { useTemaAtual } from '@/lib/useTemaAtual'

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
  versao,
  textoInicial,
  limites,
}: {
  agente: AgenteDaRota
  versao: number
  textoInicial: string
  limites: LimitesDoPrompt
}) {
  const router = useRouter()
  const tema = useTemaAtual()
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

  // Indicador, e nao trava (D5): quem recusa o tamanho e o backend, com 422.
  const dentroDoLimite = texto.length <= limites.maximoDeCaracteres
  const detectados = marcadoresNoTexto(texto)

  return (
    <div className="editor-de-prompt">
      <div className="editor-de-prompt__resumo">
        <p className="editor-de-prompt__limites">
          Marcadores obrigatórios:{' '}
          {limites.marcadores.map((marcador, indice) => (
            <span key={marcador}>
              {indice > 0 && ', '}
              <code className="marcador">{marcador}</code>
            </span>
          ))}
          . Até {limites.maximoDeCaracteres} caracteres no pior caso. Caracteres agora:{' '}
          <strong>{texto.length}</strong>.
        </p>
        <Selo variante={dentroDoLimite ? 'sucesso' : 'perigo'}>
          {dentroDoLimite ? 'Dentro do limite' : 'Acima do limite'}
        </Selo>
      </div>
      <Cartao className="janela">
        <div className="janela__barra">
          <span className="janela__luzes" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="janela__titulo">
            {agente} · versão {versao}
          </span>
          <span className="janela__meta">Linhas: {texto.split('\n').length}</span>
        </div>
        <Editor
          height="400px"
          value={texto}
          onChange={(valor) => setTexto(valor ?? '')}
          beforeMount={(monaco) => registrarLinguagemDoPrompt(monaco)}
          defaultLanguage="prompt-mobia"
          theme={TEMA_DO_MONACO[tema]}
          options={{ minimap: { enabled: false }, wordWrap: 'on' }}
        />
        <div className="janela__rodape">
          <p className="janela__meta">
            Variáveis detectadas:{' '}
            {detectados.length > 0 ? (
              detectados.map((marcador, indice) => (
                <span key={marcador}>
                  {indice > 0 && ' • '}
                  <code className="marcador">{marcador}</code>
                </span>
              ))
            ) : (
              <em>nenhuma</em>
            )}
          </p>
          <Botao onClick={publicar} disabled={enviando}>
            Publicar
          </Botao>
        </div>
      </Cartao>
      {erro && (
        <p className="editor-de-prompt__erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="editor-de-prompt__aviso">{aviso}</p>}
    </div>
  )
}
