'use client'

import { useEffect, useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import { FotosDoImovel } from '@/components/FotosDoImovel'
import { CampoDeCaracteristicas, CampoDeSelecao, CampoDeTexto } from '@/components/imoveis/CamposDoImovel'
import { PreviewDoCard } from '@/components/PreviewDoCard'
import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'
import {
  type CampoDeTexto as CampoDeTextoDoFormulario,
  estaSujo,
  type Formulario,
  formularioDe,
  formularioValido,
  type Imovel,
  type Operacao,
  pedidoDeEdicao,
  type Recusa,
  recusaDe,
  SEM_RECUSA,
  STATUS_DO_IMOVEL,
  type StatusImovel,
  TIPOS_DE_IMOVEL,
  type TipoImovel,
  totalMensalEstimado,
  validarFormulario,
} from '@/lib/imoveis'
import { registrarAlteracaoNaoSalva } from '@/lib/inatividade'

const TIPOS_ORDENADOS = Object.keys(TIPOS_DE_IMOVEL) as TipoImovel[]
const STATUS_ORDENADOS = Object.keys(STATUS_DO_IMOVEL) as StatusImovel[]

const AVISO_REINDEXA =
  'O imóvel será reindexado: a busca do agente vai passar a refletir esta alteração.'
const AVISO_NAO_REINDEXA = 'Alteração salva; não é necessário reindexar.'

const REAIS = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })

/**
 * "Finalidade" da referencia (TEC-400): duas alternancias, Aluguel e Venda,
 * que se traduzem na `operacao` do backend -- as duas ligadas sao `AMBOS`,
 * nenhuma e vazio (e a validacao recusa).
 */
function operacaoDe(aluguel: boolean, venda: boolean): Operacao | '' {
  if (aluguel && venda) {
    return 'AMBOS'
  }
  if (aluguel) {
    return 'ALUGUEL'
  }
  return venda ? 'VENDA' : ''
}

/**
 * Editar um imovel numa pagina propria (TEC-400), no lugar do modal da
 * TEC-398. Mesmas regras de antes (D2, D3, D5 do desenho da TEC-333):
 * `PATCH` so do que mudou, `codigo` desabilitado, aviso de reindexacao lido
 * do `reindexa` da resposta, erro do backend mostrado inteiro.
 *
 * **Depois de salvar, a pagina fica onde esta**: a linha de base passa a ser
 * o que acabou de ser salvo, e o aviso de reindexacao aparece no topo, junto
 * do botao que o causou.
 *
 * **"Ver no portal" so aparece com o imovel disponivel *salvo*** -- o portal
 * publico (`/busca/[id]`) devolve 404 para qualquer outro status (D3 da
 * TEC-388), e o status que vale e o gravado, nao o que esta no formulario.
 */
export function EdicaoDeImovel({ imovel }: { imovel: Imovel }) {
  const router = useRouter()
  const idDoFormulario = useId()
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(imovel))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [caracteristicaNova, setCaracteristicaNova] = useState('')
  const [avisoDeReindexacao, setAvisoDeReindexacao] = useState<string | null>(null)
  // TEC-335: as fotos vivem fora de `Formulario` (D1 daquele desenho) --
  // `onFotosMudaram` atualiza aqui direto, sem esperar o `router.refresh()`.
  const [fotos, setFotos] = useState<string[]>(() => imovel.fotos)

  const chaveDoAviso = `imovel-${imovel.id}`
  const sujo = estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva(chaveDoAviso, sujo)
  }, [chaveDoAviso, sujo])
  useEffect(() => () => registrarAlteracaoNaoSalva(chaveDoAviso, false), [chaveDoAviso])

  function mudar(campo: CampoDeTextoDoFormulario, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
  }

  const aluguel = atual.operacao === 'ALUGUEL' || atual.operacao === 'AMBOS'
  const venda = atual.operacao === 'VENDA' || atual.operacao === 'AMBOS'

  function alternarFinalidade(qual: 'aluguel' | 'venda') {
    setAtual((anterior) => {
      const temAluguel = anterior.operacao === 'ALUGUEL' || anterior.operacao === 'AMBOS'
      const temVenda = anterior.operacao === 'VENDA' || anterior.operacao === 'AMBOS'
      return {
        ...anterior,
        operacao:
          qual === 'aluguel' ? operacaoDe(!temAluguel, temVenda) : operacaoDe(temAluguel, !temVenda),
      }
    })
  }

  function adicionarCaracteristica() {
    const texto = caracteristicaNova.trim()
    if (!texto) {
      return
    }
    setAtual((anterior) => ({ ...anterior, caracteristicas: [...anterior.caracteristicas, texto] }))
    setCaracteristicaNova('')
  }

  function removerCaracteristica(indice: number) {
    setAtual((anterior) => ({
      ...anterior,
      caracteristicas: anterior.caracteristicas.filter((_, i) => i !== indice),
    }))
  }

  function descartar() {
    setAtual(inicial)
    setRecusa(SEM_RECUSA)
    setCaracteristicaNova('')
  }

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault()

    const validacao = validarFormulario(atual)
    if (Object.keys(validacao.porCampo).length > 0) {
      setRecusa(validacao)
      setAvisoDeReindexacao(null)
      return
    }
    if (!estaSujo(inicial, atual)) {
      return
    }

    setEnviando(true)
    setRecusa(SEM_RECUSA)
    setAvisoDeReindexacao(null)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/imoveis/${encodeURIComponent(imovel.id)}`, {
        method: 'PATCH',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(pedidoDeEdicao(inicial, atual)),
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

    router.refresh()
    setInicial(atual)
    setAvisoDeReindexacao(dados.reindexa ? AVISO_REINDEXA : AVISO_NAO_REINDEXA)
  }

  const total = totalMensalEstimado(atual)
  const statusSalvo = inicial.status as StatusImovel

  return (
    <>
      <div className="edicao-de-imovel__cabecalho">
        <div>
          <h1>Editar imóvel</h1>
          <p className="edicao-de-imovel__identificacao">
            <span className="edicao-de-imovel__codigo">{imovel.codigo}</span>
            <Selo variante={statusSalvo === 'DISPONIVEL' ? 'sucesso' : 'neutro'}>
              {STATUS_DO_IMOVEL[statusSalvo]}
            </Selo>
          </p>
        </div>
        <div className="edicao-de-imovel__acoes">
          {statusSalvo === 'DISPONIVEL' && (
            <a
              href={`/busca/${encodeURIComponent(imovel.id)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="botao botao--fantasma botao--padrao"
            >
              Ver no portal
            </a>
          )}
          <PreviewDoCard
            imovel={imovel}
            formulario={atual}
            fotos={fotos}
            desabilitado={!formularioValido(atual)}
          />
          <Botao variante="contorno" onClick={descartar} disabled={enviando || !sujo}>
            Descartar
          </Botao>
          <Botao type="submit" form={idDoFormulario} disabled={enviando}>
            Salvar alterações
          </Botao>
        </div>
      </div>

      {recusa.geral && (
        <p className="formulario-de-imovel__aviso" role="alert">
          {recusa.geral}
        </p>
      )}
      {avisoDeReindexacao && (
        <p className="formulario-de-imovel__reindexacao" role="status">
          {avisoDeReindexacao}
        </p>
      )}

      <form id={idDoFormulario} className="formulario-de-imovel edicao-de-imovel" onSubmit={salvar} noValidate>
        <Secao titulo="Informações gerais" descricao="Identificação e proposta do anúncio." classe="edicao-de-imovel__gerais">
          <div className="edicao-de-imovel__grade edicao-de-imovel__grade--3">
            <CampoDeTexto
              rotulo="Código"
              campo="codigo"
              ajuda="Não muda depois do cadastro."
              atual={atual}
              recusa={recusa}
              mudar={mudar}
              disabled
            />
            <CampoDeSelecao
              rotulo="Tipo"
              valor={atual.tipo}
              opcoes={TIPOS_ORDENADOS}
              rotulos={TIPOS_DE_IMOVEL}
              erro={recusa.porCampo.tipo}
              mudar={(valor) => setAtual((anterior) => ({ ...anterior, tipo: valor as TipoImovel }))}
            />
            <CampoDeSelecao
              rotulo="Status"
              valor={atual.status}
              opcoes={STATUS_ORDENADOS}
              rotulos={STATUS_DO_IMOVEL}
              erro={recusa.porCampo.status}
              mudar={(valor) => setAtual((anterior) => ({ ...anterior, status: valor as StatusImovel }))}
            />
          </div>
          <fieldset className="finalidade">
            <legend className="rotulo--obrigatorio">Finalidade</legend>
            <div className="finalidade__opcoes">
              <button
                type="button"
                className="finalidade__opcao"
                aria-pressed={aluguel}
                onClick={() => alternarFinalidade('aluguel')}
              >
                Aluguel
              </button>
              <button
                type="button"
                className="finalidade__opcao"
                aria-pressed={venda}
                onClick={() => alternarFinalidade('venda')}
              >
                Venda
              </button>
            </div>
            {recusa.porCampo.operacao && (
              <span className="formulario-de-imovel__erro">{recusa.porCampo.operacao}</span>
            )}
          </fieldset>
          <CampoDeTexto
            rotulo="Título do anúncio"
            campo="titulo"
            obrigatorio
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
          <CampoDeDescricao atual={atual} erro={recusa.porCampo.descricao} mudar={mudar} />
        </Secao>

        <Secao titulo="Valores e encargos" descricao="Preços e custos mensais, em reais." classe="edicao-de-imovel__valores">
          {venda && (
            <CampoDeTexto
              rotulo="Preço de venda"
              campo="precoVenda"
              obrigatorio={atual.operacao === 'VENDA'}
              prefixo="R$"
              atual={atual}
              recusa={recusa}
              mudar={mudar}
            />
          )}
          {aluguel && (
            <CampoDeTexto
              rotulo="Preço do aluguel (mensal)"
              campo="precoAluguel"
              obrigatorio={atual.operacao === 'ALUGUEL'}
              prefixo="R$"
              atual={atual}
              recusa={recusa}
              mudar={mudar}
            />
          )}
          <div className="edicao-de-imovel__grade edicao-de-imovel__grade--2">
            <CampoDeTexto rotulo="Condomínio" campo="condominio" prefixo="R$" atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="IPTU mensal" campo="iptuMensal" prefixo="R$" atual={atual} recusa={recusa} mudar={mudar} />
          </div>
          {total !== null && (
            <div className="total-mensal" aria-live="polite">
              <p className="total-mensal__rotulo">Custo mensal estimado</p>
              <p className="total-mensal__valor">{REAIS.format(total)}</p>
              <p className="total-mensal__nota">Aluguel + condomínio + IPTU, somados na tela.</p>
            </div>
          )}
        </Secao>

        <Secao titulo="Localização" descricao="Onde o imóvel fica." classe="edicao-de-imovel__local">
          <div className="edicao-de-imovel__grade edicao-de-imovel__grade--local">
            <CampoDeTexto rotulo="Bairro" campo="bairro" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="Cidade" campo="cidade" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="UF" campo="uf" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
          </div>
        </Secao>

        <Secao titulo="Características e metragem" descricao="Dimensões e cômodos." classe="edicao-de-imovel__caracteristicas">
          <div className="edicao-de-imovel__grade edicao-de-imovel__grade--2">
            <CampoDeTexto rotulo="Área útil" campo="areaUtilM2" obrigatorio sufixo="m²" atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="Quartos" campo="quartos" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="Suítes" campo="suites" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="Banheiros" campo="banheiros" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
            <CampoDeTexto rotulo="Vagas de garagem" campo="vagas" obrigatorio atual={atual} recusa={recusa} mudar={mudar} />
          </div>
        </Secao>

        <Secao
          titulo="Diferenciais e comodidades"
          descricao="Entram no texto que a busca do agente indexa: mudar um diferencial reindexa o imóvel."
          classe="edicao-de-imovel__diferenciais"
        >
          <CampoDeCaracteristicas
            caracteristicas={atual.caracteristicas}
            novo={caracteristicaNova}
            mudarNovo={setCaracteristicaNova}
            adicionar={adicionarCaracteristica}
            remover={removerCaracteristica}
          />
        </Secao>
      </form>

      {/* Fora do `<form>`: as fotos gravam na hora, com `PATCH` proprio
          (TEC-335), e nao esperam "Salvar alterações". */}
      <Cartao como="section" aria-label="Galeria de fotos" className="edicao-de-imovel__secao edicao-de-imovel__galeria">
        <FotosDoImovel imovelId={imovel.id} fotos={fotos} onFotosMudaram={setFotos} />
      </Cartao>
    </>
  )
}

function Secao({
  titulo,
  descricao,
  classe,
  children,
}: {
  titulo: string
  descricao: string
  classe: string
  children: React.ReactNode
}) {
  const id = useId()
  return (
    <Cartao como="section" aria-labelledby={id} className={`edicao-de-imovel__secao ${classe}`}>
      <div className="edicao-de-imovel__secao-cabecalho">
        <h2 id={id}>{titulo}</h2>
        <p>{descricao}</p>
      </div>
      {children}
    </Cartao>
  )
}

/** A descricao, num `<textarea>` com a contagem de caracteres (TEC-400). */
function CampoDeDescricao({
  atual,
  erro,
  mudar,
}: {
  atual: Formulario
  erro?: string
  mudar: (campo: CampoDeTextoDoFormulario, valor: string) => void
}) {
  const id = useId()
  return (
    <div className="formulario-de-imovel__campo">
      <div className="edicao-de-imovel__rotulo-com-contagem">
        <label htmlFor={id} className="rotulo--obrigatorio">
          Descrição completa
        </label>
        <span className="edicao-de-imovel__contagem">
          {atual.descricao.length.toLocaleString('pt-BR')} caracteres
        </span>
      </div>
      <textarea
        id={id}
        className="campo campo--area"
        rows={5}
        value={atual.descricao}
        onChange={(evento) => mudar('descricao', evento.target.value)}
        aria-required
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      {erro && (
        <span id={`${id}-erro`} className="formulario-de-imovel__erro">
          {erro}
        </span>
      )}
    </div>
  )
}
