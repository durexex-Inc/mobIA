import { ReverterVersao } from '@/components/prompts/ReverterVersao'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'
import type { AgenteDaRota, VersaoResumida } from '@/lib/prompts'

type Linha = { versao: number; autor: string | null; em: string | null }

/**
 * As versoes do agente, a ativa primeiro (TEC-395), com o "Reverter" das
 * outras (TEC-339).
 *
 * **A ativa aparece, marcada "Em producao", e nao ganha botao**: reverter
 * para a versao vigente nao muda nada. A versao 0 e o texto do codigo e nao
 * vem do historico; entra sempre, por ultimo quando nao e a ativa.
 */
export function ListaDeVersoes({
  agente,
  ativa,
  versoes,
}: {
  agente: AgenteDaRota
  ativa: number
  versoes: VersaoResumida[]
}) {
  const padrao: Linha = { versao: 0, autor: null, em: null }
  const doHistorico: Linha[] = versoes
    .filter((v) => v.versao !== 0)
    .map((v) => ({ versao: v.versao, autor: v.autor, em: v.em }))
  // Sem historico (a busca dele falhou), a ativa entra mesmo assim, sem autor.
  const daAtiva =
    ativa === 0
      ? padrao
      : (doHistorico.find((v) => v.versao === ativa) ?? { versao: ativa, autor: null, em: null })
  const outras = doHistorico.filter((v) => v.versao !== ativa).sort((a, b) => b.versao - a.versao)
  const linhas: Linha[] = [daAtiva, ...outras, ...(ativa === 0 ? [] : [padrao])]

  return (
    <section aria-labelledby="versoes-anteriores" className="secao">
      <div className="secao__cabecalho">
        <h2 id="versoes-anteriores">Versões anteriores</h2>
        <p className="secao__total">
          Total: {linhas.length} {linhas.length === 1 ? 'versão' : 'versões'}
        </p>
      </div>
      <Cartao>
        <ul className="prompts-versoes-anteriores">
          {linhas.map((linha) => {
            const eAtiva = linha.versao === ativa
            return (
              <li key={linha.versao} className="versao">
                <span className="versao__icone" aria-hidden="true">
                  v{linha.versao}
                </span>
                <div className="versao__corpo">
                  <p className="versao__titulo">
                    {linha.versao === 0 ? 'Padrão do código' : `Versão ${linha.versao}`}
                    {eAtiva && <Selo variante="info">Em produção</Selo>}
                  </p>
                  {linha.versao === 0 ? (
                    <p className="versao__meta">O texto que vem no código do agente.</p>
                  ) : (
                    linha.autor &&
                    linha.em && (
                      <p className="versao__meta">
                        Publicada por {linha.autor} em {new Date(linha.em).toLocaleString('pt-BR')}
                      </p>
                    )
                  )}
                </div>
                {!eAtiva && <ReverterVersao agente={agente} versao={linha.versao} />}
              </li>
            )
          })}
        </ul>
      </Cartao>
    </section>
  )
}
