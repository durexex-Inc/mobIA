import { DadoRevelavel } from '@/components/DadoRevelavel'
import { EdicaoDaQualificacao } from '@/components/EdicaoDaQualificacao'
import { Vazio } from '@/components/estado/Vazio'
import {
  type AgendamentoDoLead,
  type DetalheDoLead,
  dividirResumo,
  type FollowUpDoLead,
  type ImovelRecomendado,
  linhasDaQualificacao,
  motivosDoRecalculo,
  pontosDoGrafico,
  type Qualificacao,
  reacaoLegivel,
  type RecalculoDoScore,
  type ResumoDoLead,
  resumoDoGrafico,
  statusDoAgendamento,
  tipoDoAgendamento,
  valorDoRecalculo,
} from '@/lib/detalhe'
import { canalLegivel, dataAbsoluta, temperaturaLegivel, tempoRelativo } from '@/lib/leads'

/**
 * As secoes do detalhe do lead, na ordem da card (TEC-323, D5).
 *
 * Server Components sem estado: recebem o que a rota devolveu e nao buscam
 * nada. Historico de score e recomendacoes entraram na TEC-325, nas posicoes
 * 4 e 5 da D5. A conversa (TEC-324) e a ultima secao, e fica fora daqui: ela vem
 * de outra rota, e a pagina a desenha depois destas. As excecoes ao "sem
 * estado" sao o contato, que revela por um componente de cliente (TEC-330), e
 * a qualificacao, que se corrige por outro (TEC-329).
 */
export function SecoesDoDetalhe({
  detalhe,
  agora,
  podeRevelar,
  podeEditar,
}: {
  detalhe: DetalheDoLead
  agora: Date
  podeRevelar: boolean
  podeEditar: boolean
}) {
  return (
    <>
      <SecaoResumo resumo={detalhe.resumo} />
      <SecaoContato
        leadId={detalhe.leadId}
        contato={detalhe.contato}
        canal={detalhe.channel}
        podeRevelar={podeRevelar}
      />
      <SecaoQualificacao
        leadId={detalhe.leadId}
        qualificacao={detalhe.qualificacao}
        podeEditar={podeEditar}
        encerrada={detalhe.status === 'ENCERRADA'}
      />
      <SecaoHistorico historico={detalhe.historicoScore ?? []} />
      <SecaoRecomendacoes recomendacoes={detalhe.recomendacoes ?? []} />
      <SecaoAgendamentos agendamentos={detalhe.agendamentos} />
      <SecaoFollowUps followups={detalhe.followups} agora={agora} />
    </>
  )
}

function Secao({ titulo, rotulo, children }: { titulo: string; rotulo?: string; children: React.ReactNode }) {
  return (
    <section className="detalhe-secao" aria-label={titulo}>
      <h2>
        {titulo}
        {rotulo && <span className="detalhe-rotulo">{rotulo}</span>}
      </h2>
      {children}
    </section>
  )
}

/**
 * O resumo em seis blocos (D3). O rotulo sai de `fallback`, e nunca do texto.
 *
 * Sem resumo, a secao continua sendo a primeira e diz por que esta vazia: o
 * resumo nasce no handoff, e um lead que ainda nao foi encaminhado nao tem um.
 */
function SecaoResumo({ resumo }: { resumo: ResumoDoLead | null }) {
  if (!resumo) {
    return (
      <Secao titulo="Resumo">
        <p>
          <Vazio texto="Este lead ainda não tem resumo. O resumo é gerado quando a conversa é encaminhada a um corretor." />
        </p>
      </Secao>
    )
  }

  const rotulo = resumo.fallback ? 'Resumo simplificado' : 'Gerado pelo assistente'
  const emBlocos = dividirResumo(resumo.texto, { fallback: resumo.fallback })
  return (
    <Secao titulo="Resumo" rotulo={rotulo}>
      {emBlocos ? (
        <>
          {emBlocos.preambulo && <p className="detalhe-texto">{emBlocos.preambulo}</p>}
          {emBlocos.blocos.map((bloco) => (
            <div key={bloco.titulo} className="detalhe-bloco">
              <h3>{bloco.titulo}</h3>
              <p className="detalhe-texto">{bloco.corpo}</p>
            </div>
          ))}
        </>
      ) : (
        // Texto que nao se deixa cortar sai inteiro: esconder o resumo seria
        // pior que mostra-lo sem os titulos.
        <p className="detalhe-texto">{resumo.texto}</p>
      )}
    </Secao>
  )
}

/**
 * Contato mascarado para todo papel (D4 da TEC-195), com o "Revelar" para
 * quem tem `VER_DADOS_COMPLETOS` (TEC-330).
 *
 * O e-mail le `contato.email` em vez de escrever "Não informado" fixo: hoje
 * ele vem sempre nulo, porque nenhuma tabela o guarda (D7 da TEC-195), e sem
 * mascara nao ha botao. No dia em que a fonte nascer, o botao aparece sem
 * mudar esta tela (D2 da TEC-330).
 */
function SecaoContato({
  leadId,
  contato,
  canal,
  podeRevelar,
}: {
  leadId: string
  contato: DetalheDoLead['contato']
  canal: string
  podeRevelar: boolean
}) {
  return (
    <Secao titulo="Contato">
      <dl className="detalhe-campos">
        <div className="detalhe-campo">
          <dt>Telefone</dt>
          <dd>
            <DadoRevelavel
              leadId={leadId}
              campo="telefone"
              mascarado={contato.telefone}
              podeRevelar={podeRevelar}
            />
          </dd>
        </div>
        <div className="detalhe-campo">
          <dt>E-mail</dt>
          <dd>
            <DadoRevelavel
              leadId={leadId}
              campo="email"
              mascarado={contato.email}
              podeRevelar={podeRevelar}
            />
          </dd>
        </div>
        <div className="detalhe-campo">
          <dt>Canal</dt>
          <dd>{canalLegivel(canal)}</dd>
        </div>
      </dl>
    </Secao>
  )
}

/**
 * A ficha que o agente extraiu, e a correcao para quem tem `ATENDER_LEAD`
 * (TEC-329). O formulario fica embaixo da lista, e nao no lugar dela: depois
 * de salvar, a lista e o que o detalhe relido diz, e o formulario so mostra o
 * score de antes e o de agora.
 */
function SecaoQualificacao({
  leadId,
  qualificacao,
  podeEditar,
  encerrada,
}: {
  leadId: string
  qualificacao: Qualificacao | null
  podeEditar: boolean
  encerrada: boolean
}) {
  return (
    <Secao titulo="Qualificação">
      {qualificacao ? (
        <dl className="detalhe-campos">
          {linhasDaQualificacao(qualificacao).map((linha) => (
            <div key={linha.rotulo} className="detalhe-campo">
              <dt>{linha.rotulo}</dt>
              <dd>{linha.valor}</dd>
            </div>
          ))}
        </dl>
      ) : (
        // `null` e "o agente ainda nao extraiu nada" -- um fato so, e nao uma
        // grade de "Nao informado" (D4 da TEC-193).
        <p>
          <Vazio texto="O agente ainda não extraiu nenhum dado deste lead." />
        </p>
      )}
      {podeEditar && (
        <EdicaoDaQualificacao leadId={leadId} qualificacao={qualificacao} encerrada={encerrada} />
      )}
    </Secao>
  )
}

// A caixa do grafico, em unidades do `viewBox`: o SVG estica para a largura da
// secao, e o texto fica fora dele, na lista.
const GRAFICO = { largura: 320, altura: 120, margem: 8 }

/**
 * O historico do score (TEC-325, D2): o grafico de linha e, embaixo, a lista
 * -- que e a leitura de verdade. O grafico tem `role="img"` com o resumo da
 * serie; quem nao o ve le a lista, com data, valor e motivos de cada recalculo.
 */
function SecaoHistorico({ historico }: { historico: RecalculoDoScore[] }) {
  if (historico.length === 0) {
    return (
      <Secao titulo="Histórico de score">
        <p>
          <Vazio texto="O score deste lead ainda não foi calculado." />
        </p>
      </Secao>
    )
  }
  const valores = historico.map((recalculo) => recalculo.novo)
  const pontos = pontosDoGrafico(valores, GRAFICO)
  return (
    <Secao titulo="Histórico de score">
      <svg
        className="historico-grafico"
        viewBox={`0 0 ${GRAFICO.largura} ${GRAFICO.altura}`}
        role="img"
        aria-label={resumoDoGrafico(valores)}
      >
        {pontos.length > 1 && (
          <polyline
            points={pontos.map((p) => `${p.x},${p.y}`).join(' ')}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          />
        )}
        {pontos.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={3} fill="currentColor" />
        ))}
      </svg>
      <ol className="detalhe-lista historico-lista">
        {historico.map((recalculo, i) => (
          <li key={`${recalculo.em}-${i}`}>
            <time dateTime={recalculo.em}>{dataAbsoluta(recalculo.em)}</time> ·{' '}
            <strong>{valorDoRecalculo(recalculo)}</strong>
            {recalculo.causas.length > 0 && <> · {motivosDoRecalculo(recalculo.causas)}</>}
          </li>
        ))}
      </ol>
    </Secao>
  )
}

/**
 * Os imoveis que o agente apresentou (TEC-325, D3), na ordem em que foram
 * apresentados, com o motivo do match e a reacao do lead. Sem nenhum, e o
 * estado vazio -- e nao "Ainda nao medido": o lead ainda nao ter recebido
 * imovel e fato, e nao falta de fonte.
 */
function SecaoRecomendacoes({ recomendacoes }: { recomendacoes: ImovelRecomendado[] }) {
  return (
    <Secao titulo="Imóveis recomendados">
      {recomendacoes.length === 0 ? (
        <p>
          <Vazio texto="Nenhum imóvel recomendado ainda." />
        </p>
      ) : (
        <ul className="detalhe-lista recomendacoes-lista">
          {recomendacoes.map((imovel) => (
            <li key={`${imovel.imovelId}-${imovel.apresentadoEm}`} className="recomendacao">
              <h3>
                {imovel.titulo} <span className="recomendacao-codigo">{imovel.codigo}</span>
              </h3>
              <p>
                {imovel.bairro} · match de {Math.round(imovel.scoreMatch * 100)}% · apresentado em{' '}
                <time dateTime={imovel.apresentadoEm}>{dataAbsoluta(imovel.apresentadoEm)}</time>
              </p>
              <p className="detalhe-texto">{imovel.motivoMatch}</p>
              <p className="recomendacao-reacao">
                Reação: <strong>{reacaoLegivel(imovel.reacao, imovel.motivoDescarte)}</strong>
              </p>
            </li>
          ))}
        </ul>
      )}
    </Secao>
  )
}

/**
 * Os agendamentos que existem (D4 do desenho). A card pedia "Ainda nao
 * medido", mas a fonte chegou na TEC-371: dizer que falta um dado que o
 * sistema tem seria o oposto do que aquele texto existe para dizer.
 */
function SecaoAgendamentos({ agendamentos }: { agendamentos: AgendamentoDoLead[] }) {
  return (
    <Secao titulo="Agendamentos">
      {agendamentos.length === 0 ? (
        <p>
          <Vazio texto="Nenhum agendamento." />
        </p>
      ) : (
        <ul className="detalhe-lista">
          {agendamentos.map((agendamento) => (
            <li key={agendamento.id}>
              {tipoDoAgendamento(agendamento.tipo)} ·{' '}
              <time dateTime={agendamento.inicio}>{dataAbsoluta(agendamento.inicio)}</time> ·{' '}
              {statusDoAgendamento(agendamento.status)}
            </li>
          ))}
        </ul>
      )}
    </Secao>
  )
}

function SecaoFollowUps({ followups, agora }: { followups: FollowUpDoLead[]; agora: Date }) {
  return (
    <Secao titulo="Follow-ups">
      {followups.length === 0 ? (
        <p>
          <Vazio texto="Nenhum follow-up enviado." />
        </p>
      ) : (
        <ul className="detalhe-lista">
          {followups.map((followup) => (
            <li key={followup.tentativa}>
              Tentativa {followup.tentativa} · {temperaturaLegivel(followup.temperatura)} ·{' '}
              <time dateTime={followup.disparadoEm} title={dataAbsoluta(followup.disparadoEm)}>
                {tempoRelativo(followup.disparadoEm, agora)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </Secao>
  )
}
