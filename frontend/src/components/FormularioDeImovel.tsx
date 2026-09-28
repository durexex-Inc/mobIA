'use client'

import { useEffect, useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import { FotosDoImovel } from '@/components/FotosDoImovel'
import { PreviewDoCard } from '@/components/PreviewDoCard'
import {
  type CampoDeTexto as CampoDeTextoDoFormulario,
  estaSujo,
  type Formulario,
  formularioDe,
  formularioValido,
  type Imovel,
  OPERACOES,
  type Operacao,
  pedidoDeCadastro,
  pedidoDeEdicao,
  type Recusa,
  recusaDe,
  SEM_RECUSA,
  STATUS_DO_IMOVEL,
  type StatusImovel,
  TIPOS_DE_IMOVEL,
  type TipoImovel,
  validarFormulario,
} from '@/lib/imoveis'
import { registrarAlteracaoNaoSalva } from '@/lib/inatividade'

const TIPOS_ORDENADOS = Object.keys(TIPOS_DE_IMOVEL) as TipoImovel[]
const OPERACOES_ORDENADAS = Object.keys(OPERACOES) as Operacao[]
const STATUS_ORDENADOS = Object.keys(STATUS_DO_IMOVEL) as StatusImovel[]

const AVISO_REINDEXA =
  'O imóvel será reindexado: a busca do agente vai passar a refletir esta alteração.'
const AVISO_NAO_REINDEXA = 'Alteração salva; não é necessário reindexar.'

/**
 * Cadastrar e editar imovel no mesmo formulario (D1, D2, D3, D5 do desenho).
 *
 * `imovel === null` e o cadastro: `POST` completo pelo `/bff/*`. Com um
 * imovel, e a edicao: `PATCH` so do que mudou. **`codigo` fica desabilitado
 * na edicao** (D5) -- o backend recusa `PATCH` que o mude com
 * `422 codigo_imutavel`. **Retirar NAO mora aqui** (D4): e
 * `RetirarImovel.tsx`, um fluxo de confirmacao separado.
 *
 * **O aviso de reindexacao (D3) so aparece depois de um `PATCH` bem
 * sucedido**, e le o campo `reindexa` da resposta sem calcular nada por
 * conta propria -- o `POST` de criacao nao devolve esse campo, e por isso a
 * criacao fecha o formulario como sempre, sem aviso.
 *
 * **O erro do backend e mostrado inteiro, como veio** (D2): a resposta de
 * recusa e uma `string` so, nao um erro por campo.
 */
export function FormularioDeImovel({ imovel }: { imovel: Imovel | null }) {
  const router = useRouter()
  const [aberto, setAberto] = useState(false)
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(imovel))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [caracteristicaNova, setCaracteristicaNova] = useState('')
  const [avisoDeReindexacao, setAvisoDeReindexacao] = useState<string | null>(null)
  // TEC-335: as fotos vivem fora de `Formulario` (D1 daquele desenho) --
  // `onFotosMudaram` atualiza aqui direto, sem esperar o `router.refresh()`.
  const [fotos, setFotos] = useState<string[]>(() => imovel?.fotos ?? [])

  const chaveDoAviso = imovel ? `imovel-${imovel.id}` : 'imovel-novo'
  const sujo = aberto && estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva(chaveDoAviso, sujo)
  }, [chaveDoAviso, sujo])
  // Sair com o formulario sujo descarta a alteracao: o aviso nao pode
  // continuar dizendo que ha algo a perder.
  useEffect(() => () => registrarAlteracaoNaoSalva(chaveDoAviso, false), [chaveDoAviso])

  function abrir() {
    const partida = formularioDe(imovel)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setCaracteristicaNova('')
    setAvisoDeReindexacao(null)
    setFotos(imovel?.fotos ?? [])
    setAberto(true)
  }

  function fechar() {
    setAberto(false)
    setRecusa(SEM_RECUSA)
    setAvisoDeReindexacao(null)
  }

  function mudar(campo: CampoDeTextoDoFormulario, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
  }

  function adicionarCaracteristica() {
    const texto = caracteristicaNova.trim()
    if (!texto) {
      return
    }
    setAtual((anterior) => ({
      ...anterior,
      caracteristicas: [...anterior.caracteristicas, texto],
    }))
    setCaracteristicaNova('')
  }

  function removerCaracteristica(indice: number) {
    setAtual((anterior) => ({
      ...anterior,
      caracteristicas: anterior.caracteristicas.filter((_, i) => i !== indice),
    }))
  }

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault()

    const validacao = validarFormulario(atual)
    if (Object.keys(validacao.porCampo).length > 0) {
      setRecusa(validacao)
      return
    }

    if (imovel && !estaSujo(inicial, atual)) {
      fechar()
      return
    }

    setEnviando(true)
    setRecusa(SEM_RECUSA)
    setAvisoDeReindexacao(null)

    const url = imovel
      ? `/bff/api/v1/imoveis/${encodeURIComponent(imovel.id)}`
      : '/bff/api/v1/imoveis'
    const corpo = imovel ? pedidoDeEdicao(inicial, atual) : pedidoDeCadastro(atual)

    let resposta: Response
    try {
      resposta = await fetch(url, {
        method: imovel ? 'PATCH' : 'POST',
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

    router.refresh()

    if (!imovel) {
      // Criacao: sem `reindexa` na resposta (D3), nada a avisar -- fecha como
      // o cadastro de corretor fecha.
      setAberto(false)
      return
    }

    // Edicao: o formulario permanece aberto so para mostrar o aviso fixo
    // (D3), e a linha de base passa a ser o que acabou de ser salvo.
    setInicial(atual)
    setAvisoDeReindexacao(dados.reindexa ? AVISO_REINDEXA : AVISO_NAO_REINDEXA)
  }

  if (!aberto) {
    return (
      <button type="button" onClick={abrir}>
        {imovel ? 'Editar' : 'Cadastrar imóvel'}
      </button>
    )
  }

  return (
    <form className="formulario-de-imovel" onSubmit={salvar} noValidate>
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

      <CampoDeTexto
        rotulo="Código"
        campo="codigo"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
        disabled={imovel !== null}
      />
      <CampoDeTexto rotulo="Título" campo="titulo" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto
        rotulo="Descrição"
        campo="descricao"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
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
        rotulo="Operação"
        valor={atual.operacao}
        opcoes={OPERACOES_ORDENADAS}
        rotulos={OPERACOES}
        erro={recusa.porCampo.operacao}
        mudar={(valor) =>
          setAtual((anterior) => ({ ...anterior, operacao: valor as Operacao }))
        }
      />
      <CampoDeSelecao
        rotulo="Status"
        valor={atual.status}
        opcoes={STATUS_ORDENADOS}
        rotulos={STATUS_DO_IMOVEL}
        erro={recusa.porCampo.status}
        mudar={(valor) =>
          setAtual((anterior) => ({ ...anterior, status: valor as StatusImovel }))
        }
      />

      {(atual.operacao === 'VENDA' || atual.operacao === 'AMBOS') && (
        <CampoDeTexto
          rotulo="Preço de venda (R$)"
          campo="precoVenda"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
      )}
      {(atual.operacao === 'ALUGUEL' || atual.operacao === 'AMBOS') && (
        <CampoDeTexto
          rotulo="Preço de aluguel (R$)"
          campo="precoAluguel"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
      )}
      <CampoDeTexto
        rotulo="Condomínio (R$)"
        campo="condominio"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />

      <CampoDeTexto rotulo="Bairro" campo="bairro" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto rotulo="Cidade" campo="cidade" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto rotulo="UF" campo="uf" atual={atual} recusa={recusa} mudar={mudar} />

      <CampoDeTexto
        rotulo="Área útil (m²)"
        campo="areaUtilM2"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />
      <CampoDeTexto
        rotulo="Quartos"
        campo="quartos"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />
      <CampoDeTexto rotulo="Suítes" campo="suites" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto
        rotulo="Banheiros"
        campo="banheiros"
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />
      <CampoDeTexto rotulo="Vagas" campo="vagas" atual={atual} recusa={recusa} mudar={mudar} />

      <CampoDeCaracteristicas
        caracteristicas={atual.caracteristicas}
        novo={caracteristicaNova}
        mudarNovo={setCaracteristicaNova}
        adicionar={adicionarCaracteristica}
        remover={removerCaracteristica}
      />

      {/* So na edicao: o upload exige um `imovel_id` que o cadastro ainda
          nao tem (TEC-335). */}
      {imovel && (
        <FotosDoImovel imovelId={imovel.id} fotos={fotos} onFotosMudaram={setFotos} />
      )}

      <div className="formulario-de-imovel__acoes">
        <button type="submit" disabled={enviando}>
          {imovel ? 'Salvar' : 'Cadastrar'}
        </button>
        <button type="button" onClick={fechar} disabled={enviando}>
          {avisoDeReindexacao ? 'Fechar' : 'Cancelar'}
        </button>
        {/* So na edicao (D2 do desenho da TEC-336): sem imovel salvo nao ha
            o que pre-visualizar, e o botao so ativa com o formulario ja
            valido -- assim a pre-visualizacao nunca precisa decidir o que
            mostrar para um formulario incompleto. */}
        {imovel && (
          <PreviewDoCard
            imovel={imovel}
            formulario={atual}
            fotos={fotos}
            desabilitado={!formularioValido(atual)}
          />
        )}
      </div>
    </form>
  )
}

type PropsDoCampo = {
  rotulo: string
  atual: Formulario
  recusa: Recusa
  mudar: (campo: CampoDeTextoDoFormulario, valor: string) => void
}

function Erro({ id, texto }: { id: string; texto?: string }) {
  return texto ? (
    <span id={id} className="formulario-de-imovel__erro">
      {texto}
    </span>
  ) : null
}

function CampoDeTexto({
  rotulo,
  campo,
  atual,
  recusa,
  mudar,
  disabled,
}: PropsDoCampo & { campo: CampoDeTextoDoFormulario; disabled?: boolean }) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-imovel__campo">
      <label htmlFor={id}>{rotulo}</label>
      <input
        id={id}
        type="text"
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        disabled={disabled}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

function CampoDeSelecao<T extends string>({
  rotulo,
  valor,
  opcoes,
  rotulos,
  erro,
  mudar,
}: {
  rotulo: string
  valor: T | ''
  opcoes: readonly T[]
  rotulos: Record<T, string>
  erro?: string
  mudar: (valor: string) => void
}) {
  const id = useId()
  return (
    <div className="formulario-de-imovel__campo">
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
            {rotulos[opcao]}
          </option>
        ))}
      </select>
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

/**
 * "Diferencial" da card (D1) -- texto livre, um por linha/chip, no mesmo
 * molde de `CampoDeRegioes` em `FormularioDeCorretor.tsx`.
 */
function CampoDeCaracteristicas({
  caracteristicas,
  novo,
  mudarNovo,
  adicionar,
  remover,
}: {
  caracteristicas: string[]
  novo: string
  mudarNovo: (valor: string) => void
  adicionar: () => void
  remover: (indice: number) => void
}) {
  const id = useId()
  return (
    <div className="formulario-de-imovel__caracteristicas">
      <label htmlFor={id}>Diferenciais</label>
      {caracteristicas.length > 0 && (
        <ul>
          {caracteristicas.map((item, indice) => (
            <li key={`${item}-${indice}`}>
              {item}{' '}
              <button type="button" onClick={() => remover(indice)} aria-label={`Remover ${item}`}>
                Remover
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={id}
        type="text"
        value={novo}
        onChange={(evento) => mudarNovo(evento.target.value)}
        onKeyDown={(evento) => {
          if (evento.key === 'Enter') {
            evento.preventDefault()
            adicionar()
          }
        }}
      />
      <button type="button" onClick={adicionar}>
        Adicionar diferencial
      </button>
    </div>
  )
}
