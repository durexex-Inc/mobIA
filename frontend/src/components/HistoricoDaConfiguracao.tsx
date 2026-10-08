import { Cartao } from '@/components/ui/Cartao'
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
  return (
    <section aria-labelledby="historico-da-configuracao" className="secao">
      <div className="secao__cabecalho">
        <h2 id="historico-da-configuracao">
          <span className="modulo__numero">Auditoria</span> Histórico de alterações
        </h2>
        <p className="secao__total">
          {itens.length} {itens.length === 1 ? 'alteração' : 'alterações'}
        </p>
      </div>
      <Cartao>
        {itens.length === 0 ? (
          <div className="historico-da-configuracao__vazio">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              width="22"
              height="22"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
              <path d="M3 3v5h5" />
              <path d="M12 7v5l3 2" />
            </svg>
            <p className="historico-da-configuracao__vazio-titulo">Nenhuma alteração registrada ainda.</p>
            <p>Cada vez que alguém salvar a configuração, o que mudou aparece aqui, do mais recente para o mais antigo.</p>
          </div>
        ) : (
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
        )}
      </Cartao>
    </section>
  )
}
