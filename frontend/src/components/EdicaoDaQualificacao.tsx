'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useId, useState } from 'react'

import { FORMAS_DE_PAGAMENTO, type Qualificacao, TIPOS_DE_IMOVEL, URGENCIAS } from '@/lib/detalhe'
import { registrarAlteracaoNaoSalva } from '@/lib/inatividade'
import {
  type CampoDoFormulario,
  estaSujo,
  type Formulario,
  formularioDe,
  pedidoDaEdicao,
  type Recusa,
  recusaDe,
} from '@/lib/qualificacao'

type Resultado = { anterior: number | null; atual: number | null }

const SEM_RECUSA: Recusa = { porCampo: {}, geral: null }

/**
 * Corrigir a qualificacao do lead (TEC-329, D3 a D5).
 *
 * **Depois de salvar, a tela recarrega do servidor** (`router.refresh()`), como
 * no controle da conversa (D4 da TEC-327): a ficha e o score do cabecalho vem
 * do detalhe relido, e nada aqui os monta. O "Score 47 → 62" e estado deste
 * componente, e por isso sobrevive ao `refresh` -- que preserva o estado de
 * cliente -- e some ao sair da tela.
 *
 * **Em toda recusa o formulario fica aberto com o que foi digitado**, e sem
 * `refresh`: o score na tela continua o anterior, que e o que a card pede.
 *
 * Formulario sujo avisa o aviso de inatividade (D4 da TEC-311): se a sessao
 * for encerrar, ele diz que a alteracao vai se perder.
 */
export function EdicaoDaQualificacao({
  leadId,
  qualificacao,
  encerrada,
}: {
  leadId: string
  qualificacao: Qualificacao | null
  encerrada: boolean
}) {
  const router = useRouter()
  const [aberto, setAberto] = useState(false)
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(qualificacao))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [resultado, setResultado] = useState<Resultado | null>(null)

  const sujo = aberto && estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva('qualificacao', sujo)
  }, [sujo])
  // Sair da tela com o formulario sujo descarta a alteracao: o aviso nao pode
  // continuar dizendo que ha algo a perder.
  useEffect(() => () => registrarAlteracaoNaoSalva('qualificacao', false), [])

  if (encerrada) {
    return (
      <p className="edicao-nota">A conversa foi encerrada: a qualificação não pode mais ser editada.</p>
    )
  }

  function abrir() {
    // A partir da ficha de agora -- depois de um `refresh`, a prop ja e a nova.
    const partida = formularioDe(qualificacao)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setAberto(true)
  }

  function fechar() {
    setAberto(false)
    setRecusa(SEM_RECUSA)
  }

  function mudar(campo: CampoDoFormulario, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
  }

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault()
    const corpo = pedidoDaEdicao(inicial, atual)
    if (Object.keys(corpo).length === 0) {
      fechar()
      return
    }
    setEnviando(true)
    setRecusa(SEM_RECUSA)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/leads/${encodeURIComponent(leadId)}/qualificacao`, {
        method: 'PATCH',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
      })
    } catch {
      setEnviando(false)
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

    if (!resposta.ok) {
      setRecusa(recusaDe(resposta.status, dados.detail))
      return
    }

    setResultado({
      anterior: typeof dados.scoreAnterior === 'number' ? dados.scoreAnterior : null,
      atual: typeof dados.scoreAtual === 'number' ? dados.scoreAtual : null,
    })
    setAberto(false)
    router.refresh()
  }

  return (
    <div className="edicao-da-qualificacao">
      {resultado && (
        <p className="edicao-resultado" role="status">
          Score {resultado.anterior ?? '—'} → {resultado.atual ?? '—'}
        </p>
      )}
      {!aberto && (
        <button type="button" onClick={abrir}>
          Editar qualificação
        </button>
      )}
      {aberto && (
        <form className="edicao-formulario" onSubmit={salvar} noValidate>
          {recusa.geral && (
            <p className="edicao-aviso" role="alert">
              {recusa.geral}
            </p>
          )}
          <CampoDeTexto rotulo="Região" campo="regiao" atual={atual} recusa={recusa} mudar={mudar} />
          <CampoDeLista
            rotulo="Tipo de imóvel"
            campo="tipoImovel"
            opcoes={TIPOS_DE_IMOVEL}
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeTexto rotulo="Quartos" campo="quartos" numerico atual={atual} recusa={recusa} mudar={mudar} />
          <CampoDeTexto rotulo="Vagas" campo="vagas" numerico atual={atual} recusa={recusa} mudar={mudar} />
          <CampoDeTexto
            rotulo="Preço mínimo (R$)"
            campo="precoMinReais"
            numerico
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeTexto
            rotulo="Preço máximo (R$)"
            campo="precoMaxReais"
            numerico
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeLista
            rotulo="Urgência"
            campo="urgencia"
            opcoes={URGENCIAS}
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeLista
            rotulo="Forma de pagamento"
            campo="formaPagamento"
            opcoes={FORMAS_DE_PAGAMENTO}
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeLista
            rotulo="Tem imóvel para vender"
            campo="temImovelParaVender"
            opcoes={{ true: 'Sim', false: 'Não' }}
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <div className="edicao-acoes">
            <button type="submit" disabled={enviando}>
              Salvar
            </button>
            <button type="button" onClick={fechar} disabled={enviando}>
              Cancelar
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

type PropsDoCampo = {
  rotulo: string
  campo: CampoDoFormulario
  atual: Formulario
  recusa: Recusa
  mudar: (campo: CampoDoFormulario, valor: string) => void
}

function Erro({ id, texto }: { id: string; texto?: string }) {
  return texto ? (
    <span id={id} className="edicao-erro">
      {texto}
    </span>
  ) : null
}

function CampoDeTexto({ rotulo, campo, numerico, atual, recusa, mudar }: PropsDoCampo & { numerico?: boolean }) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="edicao-campo">
      <label htmlFor={id}>{rotulo}</label>
      <input
        id={id}
        type={numerico ? 'number' : 'text'}
        inputMode={numerico ? 'numeric' : undefined}
        min={numerico ? 0 : undefined}
        step={numerico ? 1 : undefined}
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

/**
 * Lista de selecao com o vocabulario do backend (D2) -- nunca texto livre. A
 * opcao vazia e "Não informado", que no `PATCH` vira `null` e limpa o campo.
 */
function CampoDeLista({ rotulo, campo, opcoes, atual, recusa, mudar }: PropsDoCampo & { opcoes: Record<string, string> }) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="edicao-campo">
      <label htmlFor={id}>{rotulo}</label>
      <select
        id={id}
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      >
        <option value="">Não informado</option>
        {Object.entries(opcoes).map(([valor, texto]) => (
          <option key={valor} value={valor}>
            {texto}
          </option>
        ))}
      </select>
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}
