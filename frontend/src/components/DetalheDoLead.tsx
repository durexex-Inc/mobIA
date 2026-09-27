import { Vazio } from '@/components/estado/Vazio'
import {
  type AgendamentoDoLead,
  type DetalheDoLead,
  dividirResumo,
  type FollowUpDoLead,
  linhasDaQualificacao,
  NAO_INFORMADO,
  type Qualificacao,
  type ResumoDoLead,
  statusDoAgendamento,
  tipoDoAgendamento,
} from '@/lib/detalhe'
import { canalLegivel, dataAbsoluta, temperaturaLegivel, tempoRelativo } from '@/lib/leads'

/**
 * As secoes do detalhe do lead, na ordem da card (TEC-323, D5).
 *
 * Server Components sem estado: recebem o que a rota devolveu e nao buscam
 * nada. Historico de score, recomendacoes e transcricao entram entre elas
 * quando as cards deles chegarem (TEC-325 e TEC-324).
 */
export function SecoesDoDetalhe({ detalhe, agora }: { detalhe: DetalheDoLead; agora: Date }) {
  return (
    <>
      <SecaoResumo resumo={detalhe.resumo} />
      <SecaoContato telefone={detalhe.contato.telefone} canal={detalhe.channel} />
      <SecaoQualificacao qualificacao={detalhe.qualificacao} />
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
 * Contato so mascarado (D4 da TEC-195). Revelar o numero e a TEC-330.
 * E-mail nao tem fonte em tabela nenhuma (D7 da TEC-195).
 */
function SecaoContato({ telefone, canal }: { telefone: string | null; canal: string }) {
  return (
    <Secao titulo="Contato">
      <dl className="detalhe-campos">
        <div className="detalhe-campo">
          <dt>Telefone</dt>
          <dd>{telefone ?? NAO_INFORMADO}</dd>
        </div>
        <div className="detalhe-campo">
          <dt>E-mail</dt>
          <dd>{NAO_INFORMADO}</dd>
        </div>
        <div className="detalhe-campo">
          <dt>Canal</dt>
          <dd>{canalLegivel(canal)}</dd>
        </div>
      </dl>
    </Secao>
  )
}

function SecaoQualificacao({ qualificacao }: { qualificacao: Qualificacao | null }) {
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
