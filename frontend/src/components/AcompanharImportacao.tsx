'use client'

import { useEffect, useState } from 'react'

import { linhasParaCsv } from '@/lib/csv'
import { INTERVALO_DE_POLLING_MS, type Importacao } from '@/lib/importacaoDeImoveis'

const ROTULO_DO_STATUS: Record<Importacao['status'], string> = {
  PROCESSANDO: 'Processando…',
  CONCLUIDO: 'Concluído',
  FALHOU: 'Falhou',
}

/**
 * Acompanha UMA importacao especifica (D3 do desenho).
 *
 * **Poll a cada 3s enquanto `PROCESSANDO`, para sozinho no primeiro
 * `CONCLUIDO`/`FALHOU`.** Sem o cuidado de pausar com a aba oculta que
 * `AtualizacaoAutomatica.tsx` (TEC-317, RN-FE-05.4) tem: aqui a importacao
 * roda no worker de qualquer jeito, entao poupar uma chamada a cada 3s nao
 * poupa trabalho do backend, so atraso na tela de quem esta olhando. Ficar
 * simples e a escolha certa quando a otimizacao da TEC-317 nao se aplica.
 *
 * **`key={importacaoId}` no chamador (`ImportarImoveis.tsx`) e o que reseta
 * este componente a cada nova importacao** -- o estado aqui nunca precisa
 * saber que o id mudou por baixo dele; um id novo e sempre uma montagem nova.
 */
export function AcompanharImportacao({ importacaoInicial }: { importacaoInicial: Importacao }) {
  const [relatorio, setRelatorio] = useState<Importacao>(importacaoInicial)
  const [erroDePolling, setErroDePolling] = useState<string | null>(null)

  useEffect(() => {
    if (relatorio.status !== 'PROCESSANDO') {
      return
    }

    let cancelado = false

    async function consultar() {
      let resposta: Response
      try {
        resposta = await fetch(
          `/bff/api/v1/imoveis/importacoes/${encodeURIComponent(relatorio.importacaoId)}`,
          { headers: { Accept: 'application/json' } },
        )
      } catch {
        if (!cancelado) {
          setErroDePolling('Não foi possível atualizar o status agora. Tentando de novo.')
        }
        return
      }

      if (!resposta.ok) {
        if (!cancelado) {
          setErroDePolling('Não foi possível atualizar o status agora. Tentando de novo.')
        }
        return
      }

      const dados = (await resposta.json()) as Importacao
      if (!cancelado) {
        setErroDePolling(null)
        setRelatorio(dados)
      }
    }

    const relogio = window.setInterval(consultar, INTERVALO_DE_POLLING_MS)
    return () => {
      cancelado = true
      window.clearInterval(relogio)
    }
  }, [relatorio.status, relatorio.importacaoId])

  function baixarRejeicoes() {
    // Blob montado do array ja carregado, sem round-trip (D5) -- os mesmos
    // dados que a lista abaixo mostra.
    const conteudo = linhasParaCsv(relatorio.erros)
    const blob = new Blob([conteudo], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `rejeicoes-${relatorio.importacaoId}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="acompanhar-importacao" aria-live="polite">
      <p className="acompanhar-importacao__status">
        {relatorio.nomeArquivo}: {ROTULO_DO_STATUS[relatorio.status]}
      </p>

      <dl className="acompanhar-importacao__totais">
        <div>
          <dt>Processados</dt>
          <dd>{relatorio.processados}</dd>
        </div>
        <div>
          <dt>Inseridos</dt>
          <dd>{relatorio.inseridos}</dd>
        </div>
        <div>
          <dt>Atualizados</dt>
          <dd>{relatorio.atualizados}</dd>
        </div>
        <div>
          <dt>Inalterados</dt>
          <dd>{relatorio.inalterados}</dd>
        </div>
        <div>
          <dt>Rejeitados</dt>
          <dd>{relatorio.rejeitados}</dd>
        </div>
      </dl>

      {erroDePolling && (
        <p className="acompanhar-importacao__aviso" role="alert">
          {erroDePolling}
        </p>
      )}

      {relatorio.erros.length > 0 && (
        <div className="acompanhar-importacao__erros">
          <p>Linhas rejeitadas:</p>
          <ul>
            {relatorio.erros.map((erro, indice) => (
              <li key={`${erro.linha}-${indice}`}>
                Linha {erro.linha}: {erro.motivo}
              </li>
            ))}
          </ul>
          <button type="button" onClick={baixarRejeicoes}>
            Baixar rejeições
          </button>
        </div>
      )}
    </div>
  )
}
