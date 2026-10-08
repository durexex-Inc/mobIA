'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { FotosDoImovel } from '@/components/FotosDoImovel'
import { PreviewDoCard } from '@/components/PreviewDoCard'
import { Botao } from '@/components/ui/Botao'
import { CampoDeSelecao as Selecao } from '@/components/ui/CampoDeSelecao'
import { Cartao } from '@/components/ui/Cartao'
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
 * O `id` do campo "Código" do cadastro: "Cadastrar primeiro imovel", no
 * estado vazio da lista, leva o foco para ele (D5 da TEC-398).
 */
export const ID_DO_CODIGO_NO_CADASTRO = 'cadastro-de-imovel-codigo'

/**
 * Cadastrar e editar imovel no mesmo formulario (D1, D2, D3, D5 do desenho da
 * TEC-333).
 *
 * `imovel === null` e o cadastro: `POST` completo pelo `/bff/*`, num cartao
 * **sempre aberto** (D1 da TEC-398) -- depois de cadastrar, o formulario volta
 * vazio. Com um imovel, e a edicao: o botao "Editar" abre o formulario num
 * `<dialog>` modal (D2 da TEC-398) e manda o `PATCH` so do que mudou.
 * **`codigo` fica desabilitado na edicao** (D5) -- o backend recusa `PATCH`
 * que o mude com `422 codigo_imutavel`. **Retirar NAO mora aqui** (D4): e
 * `RetirarImovel.tsx`, um fluxo de confirmacao separado.
 *
 * **O aviso de reindexacao (D3) so aparece depois de um `PATCH` bem
 * sucedido**, e le o campo `reindexa` da resposta sem calcular nada por
 * conta propria -- o `POST` de criacao nao devolve esse campo, e por isso o
 * cadastro so volta vazio, sem aviso.
 *
 * **O erro do backend e mostrado inteiro, como veio** (D2): a resposta de
 * recusa e uma `string` so, nao um erro por campo.
 */
export function FormularioDeImovel({ imovel }: { imovel: Imovel | null }) {
  const router = useRouter()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const idDoTitulo = useId()
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

  // O cadastro nao tem "aberto": esta sempre de pe (D1 da TEC-398).
  const emEdicao = imovel !== null
  const visivel = !emEdicao || aberto

  const chaveDoAviso = imovel ? `imovel-${imovel.id}` : 'imovel-novo'
  const sujo = visivel && estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva(chaveDoAviso, sujo)
  }, [chaveDoAviso, sujo])
  // Sair com o formulario sujo descarta a alteracao: o aviso nao pode
  // continuar dizendo que ha algo a perder.
  useEffect(() => () => registrarAlteracaoNaoSalva(chaveDoAviso, false), [chaveDoAviso])

  // O `<dialog>` so existe enquanto `aberto`; abrir o modal precisa do
  // elemento ja montado, por isso o efeito e nao o clique.
  useEffect(() => {
    if (aberto && dialogRef.current && !dialogRef.current.open) {
      dialogRef.current.showModal()
    }
  }, [aberto])

  function recomecar() {
    const partida = formularioDe(imovel)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setCaracteristicaNova('')
    setAvisoDeReindexacao(null)
    setFotos(imovel?.fotos ?? [])
  }

  function abrir() {
    recomecar()
    setAberto(true)
  }

  function fechar() {
    if (emEdicao) {
      dialogRef.current?.close()
      setAberto(false)
      setRecusa(SEM_RECUSA)
      setAvisoDeReindexacao(null)
      return
    }
    // No cadastro, "Cancelar" descarta o que foi digitado (D1 da TEC-398).
    recomecar()
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
      // Criacao: sem `reindexa` na resposta (D3), nada a avisar -- o cadastro
      // volta vazio, pronto para o proximo (D1 da TEC-398).
      recomecar()
      return
    }

    // Edicao: o modal permanece aberto so para mostrar o aviso fixo (D3), e a
    // linha de base passa a ser o que acabou de ser salvo.
    setInicial(atual)
    setAvisoDeReindexacao(dados.reindexa ? AVISO_REINDEXA : AVISO_NAO_REINDEXA)
  }

  const vendaVisivel = atual.operacao === 'VENDA' || atual.operacao === 'AMBOS'
  const aluguelVisivel = atual.operacao === 'ALUGUEL' || atual.operacao === 'AMBOS'

  const formulario = (
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

      <div className="formulario-de-imovel__grade">
        <CampoDeTexto
          rotulo="Código"
          campo="codigo"
          obrigatorio
          exemplo="Ex.: AP-1042"
          id={emEdicao ? undefined : ID_DO_CODIGO_NO_CADASTRO}
          atual={atual}
          recusa={recusa}
          mudar={mudar}
          disabled={emEdicao}
        />
        <CampoDeTexto
          rotulo="Título"
          campo="titulo"
          obrigatorio
          exemplo="Ex.: Apartamento alto padrão nos Jardins"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoDeTexto
          rotulo="Descrição"
          campo="descricao"
          obrigatorio
          exemplo="Breve descrição da unidade"
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
        {vendaVisivel && (
          <CampoDeTexto
            rotulo="Preço de venda (R$)"
            campo="precoVenda"
            obrigatorio={atual.operacao === 'VENDA'}
            prefixo="R$"
            exemplo="850.000,00"
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
        )}
        {aluguelVisivel && (
          <CampoDeTexto
            rotulo="Preço de aluguel (R$)"
            campo="precoAluguel"
            obrigatorio={atual.operacao === 'ALUGUEL'}
            prefixo="R$"
            exemplo="4.500,00"
            atual={atual}
            recusa={recusa}
            mudar={mudar}
          />
        )}
        <CampoDeTexto
          rotulo="Condomínio (R$)"
          campo="condominio"
          prefixo="R$"
          exemplo="1.250,00"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />

        <CampoDeTexto rotulo="Bairro" campo="bairro" obrigatorio exemplo="Ex.: Jardins" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto rotulo="Cidade" campo="cidade" obrigatorio exemplo="Ex.: São Paulo" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto rotulo="UF" campo="uf" obrigatorio exemplo="Ex.: SP" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto
          rotulo="Área útil (m²)"
          campo="areaUtilM2"
          obrigatorio
          exemplo="Ex.: 145"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />

        <CampoDeTexto rotulo="Quartos" campo="quartos" obrigatorio exemplo="Ex.: 3" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto rotulo="Suítes" campo="suites" obrigatorio exemplo="Ex.: 2" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto rotulo="Banheiros" campo="banheiros" obrigatorio exemplo="Ex.: 4" atual={atual} recusa={recusa} mudar={mudar} />
        <CampoDeTexto rotulo="Vagas" campo="vagas" obrigatorio exemplo="Ex.: 2" atual={atual} recusa={recusa} mudar={mudar} />

        <CampoDeCaracteristicas
          caracteristicas={atual.caracteristicas}
          novo={caracteristicaNova}
          mudarNovo={setCaracteristicaNova}
          adicionar={adicionarCaracteristica}
          remover={removerCaracteristica}
        />
      </div>

      {/* So na edicao: o upload exige um `imovel_id` que o cadastro ainda
          nao tem (TEC-335). */}
      {imovel && (
        <FotosDoImovel imovelId={imovel.id} fotos={fotos} onFotosMudaram={setFotos} />
      )}

      <div className="formulario-de-imovel__acoes">
        <Botao type="submit" disabled={enviando}>
          {imovel ? 'Salvar' : 'Cadastrar'}
        </Botao>
        <Botao variante="contorno" onClick={fechar} disabled={enviando}>
          {avisoDeReindexacao ? 'Fechar' : 'Cancelar'}
        </Botao>
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

  if (!emEdicao) {
    return (
      <Cartao como="section" aria-labelledby={idDoTitulo} className="cadastro-de-imovel">
        <div className="cadastro-de-imovel__cabecalho">
          <h2 id={idDoTitulo}>Cadastrar novo imóvel</h2>
          <p className="cadastro-de-imovel__legenda">
            <span aria-hidden="true">*</span> obrigatório
          </p>
        </div>
        {formulario}
      </Cartao>
    )
  }

  return (
    <>
      <Botao variante="contorno" tamanho="pequeno" onClick={abrir}>
        Editar
      </Botao>
      {aberto && (
        <dialog
          ref={dialogRef}
          className="dialogo dialogo--largo"
          aria-labelledby={idDoTitulo}
          onClose={() => {
            // Esc fecha o modal sem passar por `fechar` (D2 da TEC-398).
            setAberto(false)
            setRecusa(SEM_RECUSA)
            setAvisoDeReindexacao(null)
          }}
        >
          <h2 id={idDoTitulo} className="dialogo__titulo">
            Editar imóvel
          </h2>
          {formulario}
        </dialog>
      )}
    </>
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

/**
 * O asterisco de obrigatorio sai do CSS (`.rotulo--obrigatorio::after`, D4 da
 * TEC-397), para nao entrar no nome acessivel: o campo leva `aria-required`.
 */
function CampoDeTexto({
  rotulo,
  campo,
  obrigatorio,
  exemplo,
  prefixo,
  id: idFixo,
  atual,
  recusa,
  mudar,
  disabled,
}: PropsDoCampo & {
  campo: CampoDeTextoDoFormulario
  obrigatorio?: boolean
  exemplo?: string
  prefixo?: string
  id?: string
  disabled?: boolean
}) {
  const idGerado = useId()
  const id = idFixo ?? idGerado
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-imovel__campo">
      <label htmlFor={id} className={obrigatorio ? 'rotulo--obrigatorio' : undefined}>
        {rotulo}
      </label>
      <span className={prefixo ? 'campo-com-unidade campo-com-unidade--prefixo' : 'campo-com-unidade'}>
        {prefixo && (
          <span className="campo-com-unidade__prefixo" aria-hidden="true">
            {prefixo}
          </span>
        )}
        <input
          id={id}
          className="campo"
          type="text"
          placeholder={exemplo}
          value={atual[campo]}
          onChange={(evento) => mudar(campo, evento.target.value)}
          disabled={disabled}
          aria-required={obrigatorio ? true : undefined}
          aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? `${id}-erro` : undefined}
        />
      </span>
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
      <label htmlFor={id} className="rotulo--obrigatorio">
        {rotulo}
      </label>
      <Selecao
        id={id}
        value={valor}
        onChange={(evento) => mudar(evento.target.value)}
        aria-required
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      >
        <option value="">Selecione</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {rotulos[opcao]}
          </option>
        ))}
      </Selecao>
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

/**
 * "Diferencial" da card (D1) -- texto livre, um chip por item, no mesmo
 * molde de `CampoDeRegioes` em `FormularioDeCorretor.tsx`. Os chips ficam
 * numa linha propria, embaixo da grade (TEC-398).
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
    <>
      <div className="formulario-de-imovel__campo">
        <label htmlFor={id}>Diferenciais</label>
        <input
          id={id}
          className="campo"
          type="text"
          placeholder="Ex.: Piscina, varanda gourmet"
          value={novo}
          onChange={(evento) => mudarNovo(evento.target.value)}
          onKeyDown={(evento) => {
            if (evento.key === 'Enter') {
              evento.preventDefault()
              adicionar()
            }
          }}
        />
        <Botao variante="contorno" onClick={adicionar}>
          <span aria-hidden="true">+</span> Adicionar diferencial
        </Botao>
      </div>
      {caracteristicas.length > 0 && (
        <div className="formulario-de-imovel__diferenciais">
          <p>Diferenciais selecionados:</p>
          <ul className="chips">
            {caracteristicas.map((item, indice) => (
              <li key={`${item}-${indice}`} className="chip">
                {item}
                <button
                  type="button"
                  className="chip__remover"
                  onClick={() => remover(indice)}
                  aria-label={`Remover ${item}`}
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

/**
 * "Cadastrar primeiro imovel", no estado vazio da lista (D5 da TEC-398): o
 * cadastro ja esta aberto na mesma tela, entao o botao so leva o foco (e a
 * rolagem) ao campo "Codigo".
 */
export function IrParaCadastroDeImovel() {
  return (
    <Botao
      variante="contorno"
      tamanho="pequeno"
      onClick={() => document.getElementById(ID_DO_CODIGO_NO_CADASTRO)?.focus()}
    >
      <span aria-hidden="true">+</span> Cadastrar primeiro imóvel
    </Botao>
  )
}
