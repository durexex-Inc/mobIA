'use client'

import { useEffect, useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import { CampoDeCaracteristicas, CampoDeSelecao, CampoDeTexto } from '@/components/imoveis/CamposDoImovel'
import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
import {
  type CampoDeTexto as CampoDeTextoDoFormulario,
  estaSujo,
  type Formulario,
  formularioDe,
  OPERACOES,
  type Operacao,
  pedidoDeCadastro,
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

/**
 * O `id` do campo "Código" do cadastro: "Cadastrar primeiro imovel", no
 * estado vazio da lista, leva o foco para ele (D5 da TEC-398).
 */
export const ID_DO_CODIGO_NO_CADASTRO = 'cadastro-de-imovel-codigo'

/**
 * Cadastrar imovel (D1, D2 do desenho da TEC-333): `POST` completo pelo
 * `/bff/*`, num cartao **sempre aberto** (D1 da TEC-398) -- depois de
 * cadastrar, o formulario volta vazio, e "Cancelar" limpa o que foi digitado.
 *
 * **A edicao NAO mora mais aqui** (TEC-400): e a pagina
 * `admin/imoveis/[id]`, com `EdicaoDeImovel`. Os campos sao os mesmos,
 * em `components/imoveis/CamposDoImovel.tsx`.
 *
 * **O erro do backend e mostrado inteiro, como veio** (D2): a resposta de
 * recusa e uma `string` so, nao um erro por campo. O `POST` nao devolve
 * `reindexa`, entao nao ha aviso de reindexacao aqui.
 */
export function FormularioDeImovel() {
  const router = useRouter()
  const idDoTitulo = useId()
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(null))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [caracteristicaNova, setCaracteristicaNova] = useState('')

  const sujo = estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva('imovel-novo', sujo)
  }, [sujo])
  // Sair com o formulario sujo descarta a alteracao: o aviso nao pode
  // continuar dizendo que ha algo a perder.
  useEffect(() => () => registrarAlteracaoNaoSalva('imovel-novo', false), [])

  function recomecar() {
    const partida = formularioDe(null)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setCaracteristicaNova('')
  }

  function mudar(campo: CampoDeTextoDoFormulario, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
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

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault()

    const validacao = validarFormulario(atual)
    if (Object.keys(validacao.porCampo).length > 0) {
      setRecusa(validacao)
      return
    }

    setEnviando(true)
    setRecusa(SEM_RECUSA)

    let resposta: Response
    try {
      resposta = await fetch('/bff/api/v1/imoveis', {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(pedidoDeCadastro(atual)),
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
    // O cadastro volta vazio, pronto para o proximo (D1 da TEC-398).
    recomecar()
  }

  const vendaVisivel = atual.operacao === 'VENDA' || atual.operacao === 'AMBOS'
  const aluguelVisivel = atual.operacao === 'ALUGUEL' || atual.operacao === 'AMBOS'

  return (
    <Cartao como="section" aria-labelledby={idDoTitulo} className="cadastro-de-imovel">
      <div className="cadastro-de-imovel__cabecalho">
        <h2 id={idDoTitulo}>Cadastrar novo imóvel</h2>
        <p className="cadastro-de-imovel__legenda">
          <span aria-hidden="true">*</span> obrigatório
        </p>
      </div>
      <form className="formulario-de-imovel" onSubmit={salvar} noValidate>
        {recusa.geral && (
          <p className="formulario-de-imovel__aviso" role="alert">
            {recusa.geral}
          </p>
        )}

        <div className="formulario-de-imovel__grade">
          <CampoDeTexto
            rotulo="Código"
            campo="codigo"
            obrigatorio
            exemplo="Ex.: AP-1042"
            id={ID_DO_CODIGO_NO_CADASTRO}
            atual={atual}
            recusa={recusa}
            mudar={mudar}
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
            mudar={(valor) => setAtual((anterior) => ({ ...anterior, operacao: valor as Operacao }))}
          />
          <CampoDeSelecao
            rotulo="Status"
            valor={atual.status}
            opcoes={STATUS_ORDENADOS}
            rotulos={STATUS_DO_IMOVEL}
            erro={recusa.porCampo.status}
            mudar={(valor) => setAtual((anterior) => ({ ...anterior, status: valor as StatusImovel }))}
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

        <div className="formulario-de-imovel__acoes">
          <Botao type="submit" disabled={enviando}>
            Cadastrar
          </Botao>
          <Botao variante="contorno" onClick={recomecar} disabled={enviando}>
            Cancelar
          </Botao>
        </div>
      </form>
    </Cartao>
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
