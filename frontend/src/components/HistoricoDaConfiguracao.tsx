import { formatarValorDoHistorico, rotuloDeCampo, type EntradaDoHistorico } from '@/lib/configuracao'

const FORMATADOR = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short',
  timeStyle: 'short',
})

/**
 * O historico de alteracoes, mais recente primeiro -- ja ordenado pelo
 * backend (o quarto cenario do Gherkin da TEC-337). `itens` NAO e reordenado
 * aqui.
 *
 * O autor e o `uuid` cru: nao existe consulta de nome de usuario nesta card
 * (o backend so devolve o id).
 */
export function HistoricoDaConfiguracao({ itens }: { itens: EntradaDoHistorico[] }) {
  if (itens.length === 0) {
    return <p className="historico-da-configuracao__vazio">Nenhuma alteração registrada ainda.</p>
  }

  return (
    <ul className="historico-da-configuracao">
      {itens.map((entrada) => (
        <li key={entrada.id} className="historico-da-configuracao__entrada">
          <p className="historico-da-configuracao__cabecalho">
            <span>{FORMATADOR.format(new Date(entrada.em))}</span> — <span>{entrada.autor}</span>
          </p>
          <ul className="historico-da-configuracao__mudancas">
            {entrada.mudancas.map((mudanca, indice) => (
              <li key={`${mudanca.campo}-${indice}`}>
                <strong>{rotuloDeCampo(mudanca.campo)}:</strong>{' '}
                {formatarValorDoHistorico(mudanca.anterior)} → {formatarValorDoHistorico(mudanca.novo)}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}
