'use client'

import { useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import { ConfirmarAlteracaoDaConfiguracao } from '@/components/ConfirmarAlteracaoDaConfiguracao'
import {
  type Configuracao,
  diffDe,
  type Formulario,
  formularioDe,
  type Limites,
  type LinhaDoDiff,
  PESOS,
  pedidoDeEdicao,
  type Recusa,
  recusaDe,
  SEM_RECUSA,
  TEMPERATURAS,
  validarFormulario,
} from '@/lib/configuracao'

const ROTULOS_DO_TOM: Record<string, string> = {
  CORDIAL: 'Cordial',
  FORMAL: 'Formal',
  DESCONTRAIDO: 'Descontraído',
}

const ROTULOS_DO_PESO: Record<(typeof PESOS)[number], string> = {
  pesoCompletude: 'Peso de completude',
  pesoUrgencia: 'Peso de urgência',
  pesoCatalogo: 'Peso de catálogo',
  pesoEngajamento: 'Peso de engajamento',
  pesoCapacidade: 'Peso de capacidade',
}

const ROTULOS_DA_TEMPERATURA: Record<string, string> = {
  QUENTE: 'Quente',
  MORNO: 'Morno',
  FRIO: 'Frio',
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
 * que `RetirarImovel`/`FormularioDeImovel` tomam ao descartar em vez de
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

  return (
    <>
      <form className="formulario-de-configuracao" onSubmit={revisar} noValidate>
        {recusa.geral && (
          <p className="formulario-de-configuracao__aviso" role="alert">
            {recusa.geral}
            {conflitoDeVersao && (
              <>
                {' '}
                <button type="button" onClick={recarregar}>
                  Recarregar
                </button>
              </>
            )}
          </p>
        )}

        <CampoDeTexto
          rotulo="Nome do assistente"
          valor={atual.nomeDoAssistente}
          erro={recusa.porCampo.nomeDoAssistente}
          mudar={(valor) => mudarTexto('nomeDoAssistente', valor)}
        />

        <CampoDeSelecao
          rotulo="Tom"
          valor={atual.tom}
          opcoes={limites.tom.valores}
          rotulos={ROTULOS_DO_TOM}
          erro={recusa.porCampo.tom}
          mudar={(valor) => mudarTexto('tom', valor)}
        />

        <CampoDeTexto
          rotulo="Teto de perguntas"
          tipo="number"
          valor={atual.tetoDePerguntas}
          erro={recusa.porCampo.tetoDePerguntas}
          mudar={(valor) => mudarTexto('tetoDePerguntas', valor)}
        />

        <div className="formulario-de-configuracao__pesos">
          <p className="formulario-de-configuracao__nota">
            A soma dos pesos precisa ficar entre 1 e {limites.pesos.somaMaxima}.
          </p>
          {PESOS.map((campo) => (
            <CampoDeTexto
              key={campo}
              rotulo={ROTULOS_DO_PESO[campo]}
              tipo="number"
              valor={atual[campo]}
              erro={recusa.porCampo[campo]}
              mudar={(valor) => mudarTexto(campo, valor)}
            />
          ))}
        </div>

        <div className="formulario-de-configuracao__cadencia">
          <p>Cadência de follow-up (horas)</p>
          {recusa.porCampo.cadencia && (
            <span className="formulario-de-configuracao__erro">{recusa.porCampo.cadencia}</span>
          )}
          {TEMPERATURAS.map((temperatura) => {
            const horas = atual.cadencia[temperatura] ?? []
            return (
              <div key={temperatura} className="formulario-de-configuracao__cadencia-linha">
                <span className="formulario-de-configuracao__cadencia-rotulo">
                  {ROTULOS_DA_TEMPERATURA[temperatura] ?? temperatura}
                </span>
                {horas.map((valor, indice) => (
                  <input
                    key={indice}
                    type="number"
                    aria-label={`${ROTULOS_DA_TEMPERATURA[temperatura] ?? temperatura}, intervalo ${indice + 1}`}
                    value={valor}
                    onChange={(evento) => mudarCadencia(temperatura, indice, evento.target.value)}
                  />
                ))}
              </div>
            )
          })}
        </div>

        <CampoDeTexto
          rotulo="Orçamento mensal (USD)"
          valor={atual.orcamentoMensalUsd}
          erro={recusa.porCampo.orcamentoMensalUsd}
          mudar={(valor) => mudarTexto('orcamentoMensalUsd', valor)}
        />

        <div className="formulario-de-configuracao__acoes">
          <button type="submit" disabled={enviando}>
            Salvar
          </button>
        </div>
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

function CampoDeTexto({
  rotulo,
  valor,
  erro,
  mudar,
  tipo = 'text',
}: {
  rotulo: string
  valor: string
  erro?: string
  mudar: (valor: string) => void
  tipo?: 'text' | 'number'
}) {
  const id = useId()
  return (
    <div className="formulario-de-configuracao__campo">
      <label htmlFor={id}>{rotulo}</label>
      <input
        id={id}
        type={tipo}
        value={valor}
        onChange={(evento) => mudar(evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      {erro && (
        <span id={`${id}-erro`} className="formulario-de-configuracao__erro">
          {erro}
        </span>
      )}
    </div>
  )
}

function CampoDeSelecao({
  rotulo,
  valor,
  opcoes,
  rotulos,
  erro,
  mudar,
}: {
  rotulo: string
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
      <select
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
      </select>
      {erro && (
        <span id={`${id}-erro`} className="formulario-de-configuracao__erro">
          {erro}
        </span>
      )}
    </div>
  )
}
