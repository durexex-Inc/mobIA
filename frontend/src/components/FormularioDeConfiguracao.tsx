'use client'

import { useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import { ConfirmarAlteracaoDaConfiguracao } from '@/components/ConfirmarAlteracaoDaConfiguracao'
import { Botao } from '@/components/ui/Botao'
import { CampoDeSelecao as Selecao } from '@/components/ui/CampoDeSelecao'
import { Cartao } from '@/components/ui/Cartao'
import {
  type Configuracao,
  diffDe,
  estaSujo,
  type Formulario,
  formularioDe,
  type Limites,
  type LinhaDoDiff,
  PESOS,
  pedidoDeEdicao,
  type Recusa,
  recusaDe,
  SEM_RECUSA,
  somaDosPesos,
  TEMPERATURAS,
  validarFormulario,
} from '@/lib/configuracao'

const ROTULOS_DO_TOM: Record<string, string> = {
  CORDIAL: 'Cordial',
  FORMAL: 'Formal',
  DESCONTRAIDO: 'Descontraído',
}

// O rotulo visivel e o nome do criterio; o "Peso de" fica so para o leitor de
// tela (D6 do desenho da TEC-396), para o nome acessivel continuar igual ao do
// diff de confirmacao e do historico.
const ROTULOS_DO_PESO: Record<(typeof PESOS)[number], { nome: string; ajuda: string }> = {
  pesoCompletude: { nome: 'completude', ajuda: 'Campos obrigatórios preenchidos' },
  pesoUrgencia: { nome: 'urgência', ajuda: 'Prazo que o lead declarou' },
  pesoCatalogo: { nome: 'catálogo', ajuda: 'Imóveis compatíveis no catálogo' },
  pesoEngajamento: { nome: 'engajamento', ajuda: 'Mensagens enviadas pelo lead' },
  pesoCapacidade: { nome: 'capacidade', ajuda: 'Forma de pagamento declarada' },
}

const ROTULOS_DA_TEMPERATURA: Record<string, string> = {
  QUENTE: 'Quente',
  MORNO: 'Morno',
  FRIO: 'Frio',
}

const DESCRICOES_DA_TEMPERATURA: Record<string, string> = {
  QUENTE: 'Lead prioritário',
  MORNO: 'Em avaliação',
  FRIO: 'Nutrição longa',
}

/**
 * Editar tom, pesos, cadencia e orcamento, com diff de confirmacao antes de
 * salvar e recuperacao de conflito de versao (TEC-337, D1/D4/D5 do desenho).
 *
 * **`corPrimaria`, `posicaoDoBotao` e `dominiosDoChat` nao aparecem aqui** --
 * decisao previa do desenho: pertencem a tela de aparencia do widget
 * (TEC-344/345), e o `PATCH` desta tela nunca os inclui.
 *
 * **A confirmacao (D4) e obrigatoria antes de QUALQUER `PATCH`.** `salvar`
 * valida com `limites` primeiro -- fora da faixa nao chega a montar diff nem a
 * chamar `fetch` -- e so abre a confirmacao quando ha mudanca real
 * (`diffDe` nao vazio). O `PATCH` em si so sai do `confirmar`.
 *
 * **409 (D5) mostra "Recarregar", que so chama `router.refresh()`.** Nao
 * tenta mesclar a edicao com o que a outra pessoa gravou -- a mesma decisao
 * que `RetirarImovel`/`EdicaoDeImovel` tomam ao descartar em vez de
 * adivinhar. **Quem descarta a edicao em curso e o `key={versao}` que
 * `admin/configuracao/page.tsx` passa a este componente** -- e nao um
 * `useEffect` que copia prop para estado: essa forma cascateia renders e o
 * lint do proprio repo (`react-hooks/set-state-in-effect`) a recusa. Uma
 * `versao` nova (o Server Component buscou de novo) muda a `key`, o React
 * desmonta a instancia antiga e monta uma do zero com `useState(() =>
 * formularioDe(configuracaoInicial))` -- "nada e sobrescrito" por construcao,
 * sem precisar de efeito nenhum.
 *
 * **O `PATCH` bem-sucedido NAO traz `versao` nova** (contrato do backend): a
 * linha de base local vira o que acabou de ser salvo na hora (`confirmar`
 * abaixo), mas `versaoAtual` so se atualiza quando o `router.refresh()`
 * completar e a `key` mudar. Ate la, um segundo salvamento levaria 409 --
 * seguro, nao um bug (D5).
 */
export function FormularioDeConfiguracao({
  configuracaoInicial,
  limitesIniciais,
  versaoInicial,
}: {
  configuracaoInicial: Configuracao
  limitesIniciais: Limites
  versaoInicial: string | null
}) {
  const router = useRouter()
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(configuracaoInicial))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [conflitoDeVersao, setConflitoDeVersao] = useState(false)
  const [diff, setDiff] = useState<LinhaDoDiff[] | null>(null)
  const [enviando, setEnviando] = useState(false)
  // Nem `limites` nem a versao mudam por acao do proprio formulario -- so
  // quando o Server Component busca de novo, e ai a `key={versao}` de
  // `admin/configuracao/page.tsx` remonta esta instancia com props novas
  // (ver a docstring acima). Nenhum dos dois precisa de estado propria.
  const limites = limitesIniciais
  const versaoAtual = versaoInicial

  function mudarTexto(campo: Exclude<keyof Formulario, 'cadencia'>, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
  }

  function mudarCadencia(temperatura: string, indice: number, valor: string) {
    setAtual((anterior) => ({
      ...anterior,
      cadencia: {
        ...anterior.cadencia,
        [temperatura]: anterior.cadencia[temperatura].map((hora, i) => (i === indice ? valor : hora)),
      },
    }))
  }

  function revisar(evento: React.FormEvent) {
    evento.preventDefault()

    // A validacao do cliente vem ANTES de qualquer diff/fetch (cenario 2 do
    // Gherkin): valor fora da faixa nunca chega a montar a confirmacao.
    const validacao = validarFormulario(atual, limites)
    if (Object.keys(validacao.porCampo).length > 0) {
      setRecusa(validacao)
      setDiff(null)
      return
    }
    setRecusa(SEM_RECUSA)

    const linhas = diffDe(inicial, atual)
    if (linhas.length === 0) {
      // Sem mudanca, nao ha o que confirmar nem o que salvar.
      return
    }
    setDiff(linhas)
  }

  function cancelarConfirmacao() {
    setDiff(null)
  }

  async function confirmar() {
    setEnviando(true)
    setRecusa(SEM_RECUSA)
    setConflitoDeVersao(false)

    const corpo = { ...pedidoDeEdicao(inicial, atual), seVersao: versaoAtual }

    let resposta: Response
    try {
      resposta = await fetch('/bff/api/v1/configuracao/agente', {
        method: 'PATCH',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      })
    } catch {
      setEnviando(false)
      setDiff(null)
      setRecusa({ porCampo: {}, geral: 'Não foi possível falar com o servidor. Tente de novo.' })
      return
    }

    let dados: Record<string, unknown> = {}
    try {
      dados = (await resposta.json()) as Record<string, unknown>
    } catch {
      dados = {}
    }
    setEnviando(false)
    setDiff(null)

    if (!resposta.ok) {
      const recusaDaResposta = recusaDe(resposta.status, dados.detail)
      setRecusa(recusaDaResposta)
      setConflitoDeVersao(Boolean(recusaDaResposta.conflitoDeVersao))
      return
    }

    router.refresh()

    // A resposta nao traz `versao` (ver a docstring acima): a linha de base
    // local vira o que acabou de ser salvo, e `versaoAtual` fica como esta
    // ate o `useEffect` rodar de novo com props frescas.
    const nova = (dados.configuracao ?? {}) as Partial<Configuracao>
    const partida = formularioDe({ ...configuracaoInicial, ...nova })
    setInicial(partida)
    setAtual(partida)
  }

  function recarregar() {
    router.refresh()
  }

  // "Redefinir" (TEC-396, D4): volta a linha de base local, sem rede.
  function redefinir() {
    setAtual(inicial)
    setRecusa(SEM_RECUSA)
    setDiff(null)
  }

  const soma = somaDosPesos(atual)
  const somaValida = soma >= 1 && soma <= limites.pesos.somaMaxima

  return (
    <>
      <form className="formulario-de-configuracao" onSubmit={revisar} noValidate>
        {recusa.geral && (
          <p className="formulario-de-configuracao__aviso" role="alert">
            {recusa.geral}
            {conflitoDeVersao && (
              <>
                {' '}
                <Botao variante="contorno" tamanho="pequeno" onClick={recarregar}>
                  Recarregar
                </Botao>
              </>
            )}
          </p>
        )}

        <Modulo
          numero="01"
          titulo="Identidade e limites do assistente"
          descricao="Como o assistente se apresenta e quantas perguntas faz antes de passar o lead a um corretor."
        >
          <div className="formulario-de-configuracao__grade formulario-de-configuracao__grade--tres">
            <CampoDeTexto
              rotulo="Nome do assistente"
              ajuda="O nome com que o assistente se apresenta ao lead."
              valor={atual.nomeDoAssistente}
              erro={recusa.porCampo.nomeDoAssistente}
              mudar={(valor) => mudarTexto('nomeDoAssistente', valor)}
            />

            <CampoDeSelecao
              rotulo="Tom"
              ajuda="O registro das respostas que o agente escreve."
              valor={atual.tom}
              opcoes={limites.tom.valores}
              rotulos={ROTULOS_DO_TOM}
              erro={recusa.porCampo.tom}
              mudar={(valor) => mudarTexto('tom', valor)}
            />

            <CampoDeTexto
              rotulo="Teto de perguntas"
              ajuda="Perguntas ao lead antes de passar a conversa a um corretor."
              sufixo="perguntas"
              tipo="number"
              valor={atual.tetoDePerguntas}
              erro={recusa.porCampo.tetoDePerguntas}
              mudar={(valor) => mudarTexto('tetoDePerguntas', valor)}
            />
          </div>
        </Modulo>

        <Modulo
          numero="02"
          titulo="Pesos de qualificação"
          descricao={`A soma dos pesos precisa ficar entre 1 e ${limites.pesos.somaMaxima}.`}
          extra={
            <div className={somaValida ? 'soma-dos-pesos' : 'soma-dos-pesos soma-dos-pesos--fora'}>
              <span className="soma-dos-pesos__circulo" aria-hidden="true">
                {soma}
              </span>
              <span className="soma-dos-pesos__texto" aria-live="polite">
                <span>
                  Soma dos pesos: <strong>{soma}</strong> / {limites.pesos.somaMaxima}
                </span>
                <span className="soma-dos-pesos__estado">
                  {somaValida ? 'Configuração válida' : 'Fora da faixa'}
                </span>
              </span>
            </div>
          }
        >
          <div className="formulario-de-configuracao__grade formulario-de-configuracao__grade--pesos">
            {PESOS.map((campo) => (
              <CampoDeTexto
                key={campo}
                rotulo={
                  <>
                    <span className="so-leitor">Peso de </span>
                    <span className="formulario-de-configuracao__rotulo-peso">
                      {ROTULOS_DO_PESO[campo].nome}
                    </span>
                  </>
                }
                ajuda={ROTULOS_DO_PESO[campo].ajuda}
                tipo="number"
                valor={atual[campo]}
                erro={recusa.porCampo[campo]}
                mudar={(valor) => mudarTexto(campo, valor)}
              />
            ))}
          </div>
        </Modulo>

        <Modulo
          numero="03"
          titulo="Cadência de follow-up (horas)"
          descricao="Em que hora, contada do silêncio do lead, sai cada tentativa de retomar a conversa, por temperatura."
        >
          {recusa.porCampo.cadencia && (
            <span className="formulario-de-configuracao__erro">{recusa.porCampo.cadencia}</span>
          )}
          <div className="cadencia">
            {TEMPERATURAS.map((temperatura) => {
              const horas = atual.cadencia[temperatura] ?? []
              const rotulo = ROTULOS_DA_TEMPERATURA[temperatura] ?? temperatura
              return (
                <div key={temperatura} className="cadencia__linha">
                  <p className="cadencia__temperatura">
                    <strong>{rotulo}</strong>
                    <span>{DESCRICOES_DA_TEMPERATURA[temperatura]}</span>
                  </p>
                  <div className="cadencia__disparos">
                    {horas.map((valor, indice) => (
                      <CampoDeHoras
                        key={indice}
                        rotulo={`${indice + 1}º disparo`}
                        nomeAcessivel={`${rotulo}, ${indice + 1}º disparo`}
                        valor={valor}
                        mudar={(novo) => mudarCadencia(temperatura, indice, novo)}
                      />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </Modulo>

        <Cartao className="formulario-de-configuracao__rodape">
          <div className="formulario-de-configuracao__orcamento">
            <CampoDeTexto
              rotulo="Orçamento mensal (USD)"
              ajuda="Referência do alerta no painel de custo de IA. Não interrompe o agente; vazio é sem orçamento."
              prefixo="$"
              sufixo="USD / mês"
              valor={atual.orcamentoMensalUsd}
              erro={recusa.porCampo.orcamentoMensalUsd}
              mudar={(valor) => mudarTexto('orcamentoMensalUsd', valor)}
            />
          </div>
          <div className="formulario-de-configuracao__acoes">
            <Botao variante="fantasma" onClick={redefinir} disabled={enviando || !estaSujo(inicial, atual)}>
              Redefinir
            </Botao>
            <Botao type="submit" disabled={enviando}>
              Salvar configurações
            </Botao>
          </div>
        </Cartao>
      </form>

      {diff && (
        <ConfirmarAlteracaoDaConfiguracao
          linhas={diff}
          enviando={enviando}
          onConfirmar={confirmar}
          onCancelar={cancelarConfirmacao}
        />
      )}
    </>
  )
}

/** Um modulo da tela (TEC-396, D1): sobretitulo, titulo, descricao e conteudo num cartao. */
function Modulo({
  numero,
  titulo,
  descricao,
  extra,
  children,
}: {
  numero: string
  titulo: string
  descricao: string
  extra?: React.ReactNode
  children: React.ReactNode
}) {
  const id = useId()
  return (
    <Cartao como="section" aria-labelledby={id} className="modulo">
      <div className="modulo__cabecalho">
        <div>
          <p className="modulo__numero">Módulo {numero}</p>
          <h2 id={id} className="modulo__titulo">
            {titulo}
          </h2>
          <p className="modulo__descricao">{descricao}</p>
        </div>
        {extra}
      </div>
      {children}
    </Cartao>
  )
}

function CampoDeTexto({
  rotulo,
  ajuda,
  valor,
  erro,
  mudar,
  prefixo,
  sufixo,
  tipo = 'text',
}: {
  rotulo: React.ReactNode
  ajuda?: string
  valor: string
  erro?: string
  mudar: (valor: string) => void
  prefixo?: string
  sufixo?: string
  tipo?: 'text' | 'number'
}) {
  const id = useId()
  const classes = ['campo-com-unidade', prefixo && 'campo-com-unidade--prefixo', sufixo && 'campo-com-unidade--sufixo']
    .filter(Boolean)
    .join(' ')
  return (
    <div className="formulario-de-configuracao__campo">
      <label htmlFor={id}>{rotulo}</label>
      <span className={classes}>
        {prefixo && (
          <span className="campo-com-unidade__prefixo" aria-hidden="true">
            {prefixo}
          </span>
        )}
        <input
          id={id}
          className="campo"
          type={tipo}
          value={valor}
          onChange={(evento) => mudar(evento.target.value)}
          aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? `${id}-erro` : undefined}
        />
        {sufixo && (
          <span className="campo-com-unidade__sufixo" aria-hidden="true">
            {sufixo}
          </span>
        )}
      </span>
      {erro && (
        <span id={`${id}-erro`} className="formulario-de-configuracao__erro">
          {erro}
        </span>
      )}
      {ajuda && <span className="formulario-de-configuracao__ajuda">{ajuda}</span>}
    </div>
  )
}

/**
 * Um intervalo da cadencia (TEC-396, D5). O nome acessivel leva a temperatura
 * ("Quente, 1º disparo"), porque o rotulo visivel sozinho se repete em cada
 * linha.
 */
function CampoDeHoras({
  rotulo,
  nomeAcessivel,
  valor,
  mudar,
}: {
  rotulo: string
  nomeAcessivel: string
  valor: string
  mudar: (valor: string) => void
}) {
  return (
    <label className="cadencia__disparo">
      <span aria-hidden="true">{rotulo}</span>
      <span className="campo-com-unidade campo-com-unidade--sufixo">
        <input
          className="campo"
          type="number"
          aria-label={nomeAcessivel}
          value={valor}
          onChange={(evento) => mudar(evento.target.value)}
        />
        <span className="campo-com-unidade__sufixo" aria-hidden="true">
          h
        </span>
      </span>
    </label>
  )
}

function CampoDeSelecao({
  rotulo,
  ajuda,
  valor,
  opcoes,
  rotulos,
  erro,
  mudar,
}: {
  rotulo: string
  ajuda?: string
  valor: string
  opcoes: readonly string[]
  rotulos: Record<string, string>
  erro?: string
  mudar: (valor: string) => void
}) {
  const id = useId()
  return (
    <div className="formulario-de-configuracao__campo">
      <label htmlFor={id}>{rotulo}</label>
      <Selecao
        id={id}
        value={valor}
        onChange={(evento) => mudar(evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      >
        <option value="">Selecione</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {rotulos[opcao] ?? opcao}
          </option>
        ))}
      </Selecao>
      {erro && (
        <span id={`${id}-erro`} className="formulario-de-configuracao__erro">
          {erro}
        </span>
      )}
      {ajuda && <span className="formulario-de-configuracao__ajuda">{ajuda}</span>}
    </div>
  )
}
