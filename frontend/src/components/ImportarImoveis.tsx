'use client'

import { type ChangeEvent, useId, useRef, useState } from 'react'

import { AcompanharImportacao } from '@/components/AcompanharImportacao'
import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'
import { previaDoCsv, type PreviaDoCsv } from '@/lib/csv'
import {
  COLUNAS_OBRIGATORIAS_DO_CSV,
  TETO_DE_UPLOAD_EM_BYTES,
  type Importacao,
} from '@/lib/importacaoDeImoveis'

const LIMITE_EM_MB = TETO_DE_UPLOAD_EM_BYTES / (1024 * 1024)
const MENSAGEM_DE_ARQUIVO_GRANDE = `O arquivo passa de ${LIMITE_EM_MB} MB; use a CLI de seed.`

/**
 * Selecionar, pre-visualizar e enviar o CSV de importacao em lote (TEC-334).
 *
 * **A previa e so do cliente** (D1): sem round-trip, lida do proprio
 * `File` e mostrada como veio no arquivo -- sem remapear para os campos do
 * formulario da TEC-333.
 *
 * **O teto de 10 MB e checado NA SELECAO** (D2), antes de qualquer leitura
 * ou envio: o 413 do backend continua a garantia real, isto e a recusa na
 * hora certa que o Gherkin pede.
 *
 * **Este componente TAMBEM guarda qual importacao esta em curso**
 * (`importacaoAtual`), seedado por `importacaoInicial` (D4, a mais recente
 * que a pagina buscou no servidor) e substituido pelo `202` de um novo
 * envio -- e o que faz `<AcompanharImportacao>` ter sempre a importacao
 * certa para acompanhar, sem precisar de um componente 'use client' extra
 * so para guardar esse unico pedaco de estado.
 */
export function ImportarImoveis({ importacaoInicial }: { importacaoInicial: Importacao | null }) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [previa, setPrevia] = useState<PreviaDoCsv | null>(null)
  const [erroDeSelecao, setErroDeSelecao] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [erroDeEnvio, setErroDeEnvio] = useState<string | null>(null)
  const [importacaoAtual, setImportacaoAtual] = useState<Importacao | null>(importacaoInicial)

  async function selecionar(evento: ChangeEvent<HTMLInputElement>) {
    const selecionado = evento.target.files?.[0] ?? null
    setErroDeSelecao(null)
    setErroDeEnvio(null)
    setArquivo(null)
    setPrevia(null)

    if (!selecionado) {
      return
    }

    if (selecionado.size > TETO_DE_UPLOAD_EM_BYTES) {
      setErroDeSelecao(MENSAGEM_DE_ARQUIVO_GRANDE)
      return
    }

    const conteudo = await selecionado.text()
    setArquivo(selecionado)
    setPrevia(previaDoCsv(conteudo))
  }

  async function confirmar() {
    if (!arquivo) {
      return
    }
    setEnviando(true)
    setErroDeEnvio(null)

    const corpo = new FormData()
    corpo.append('arquivo', arquivo)

    let resposta: Response
    try {
      resposta = await fetch('/bff/api/v1/imoveis/importar', { method: 'POST', body: corpo })
    } catch {
      setEnviando(false)
      setErroDeEnvio('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    setEnviando(false)

    if (!resposta.ok) {
      setErroDeEnvio(
        resposta.status === 401
          ? 'Sua sessão terminou. Recarregue a página para entrar de novo.'
          : 'Não foi possível importar. Tente de novo.',
      )
      return
    }

    const dados = (await resposta.json()) as { importacaoId: string; status: 'PROCESSANDO' }
    // So o id e o status PROCESSANDO vem do 202 -- as contagens e os erros de
    // verdade so chegam no primeiro poll de `AcompanharImportacao` (D3).
    setImportacaoAtual({
      importacaoId: dados.importacaoId,
      status: dados.status,
      nomeArquivo: arquivo.name,
      processados: 0,
      inseridos: 0,
      atualizados: 0,
      inalterados: 0,
      rejeitados: 0,
      erros: [],
    })
    setArquivo(null)
    setPrevia(null)
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  return (
    <Cartao como="section" aria-labelledby={`${inputId}-titulo`} className="importar-imoveis">
      <div className="importar-imoveis__cabecalho">
        <div>
          <h2 id={`${inputId}-titulo`}>Importar imóveis</h2>
          <p className="importar-imoveis__subtitulo">Cadastro e atualização em lote por planilha CSV.</p>
        </div>
        <Selo>CSV, até {LIMITE_EM_MB} MB</Selo>
      </div>

      <div className="importar-imoveis__campo">
        <label htmlFor={inputId}>Arquivo CSV</label>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept=".csv"
          onChange={selecionar}
          disabled={enviando}
          aria-describedby={`${inputId}-colunas`}
        />
        <p id={`${inputId}-colunas`} className="importar-imoveis__colunas">
          O cabeçalho precisa ter as colunas{' '}
          {COLUNAS_OBRIGATORIAS_DO_CSV.map((coluna, indice) => (
            <span key={coluna}>
              <code>{coluna}</code>
              {indice < COLUNAS_OBRIGATORIAS_DO_CSV.length - 1 ? ', ' : '.'}
            </span>
          ))}
        </p>
      </div>

      {erroDeSelecao && (
        <p className="importar-imoveis__aviso" role="alert">
          {erroDeSelecao}
        </p>
      )}
      {erroDeEnvio && (
        <p className="importar-imoveis__aviso" role="alert">
          {erroDeEnvio}
        </p>
      )}

      {previa && previa.colunas.length > 0 && (
        <div className="importar-imoveis__previa">
          <p>Prévia das 10 primeiras linhas:</p>
          <div className="importar-imoveis__rolagem">
            <table>
              <thead>
                <tr>
                  {previa.colunas.map((coluna, indice) => (
                    <th key={`${coluna}-${indice}`}>{coluna}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previa.linhas.map((linha, indiceDaLinha) => (
                  <tr key={indiceDaLinha}>
                    {linha.map((valor, indiceDaColuna) => (
                      <td key={indiceDaColuna}>{valor}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Botao onClick={confirmar} disabled={enviando}>
            Confirmar importação
          </Botao>
        </div>
      )}

      {importacaoAtual && (
        <AcompanharImportacao key={importacaoAtual.importacaoId} importacaoInicial={importacaoAtual} />
      )}
    </Cartao>
  )
}
