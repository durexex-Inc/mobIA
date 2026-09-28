'use client'

import { useEffect, useId, useState } from 'react'
import { useRouter } from 'next/navigation'

import {
  type CampoDeTexto as CampoDeTextoDoFormulario,
  CAPACIDADE_MAXIMA,
  CAPACIDADE_MINIMA,
  type Corretor,
  ESPECIALIDADES,
  type Especialidade,
  estaSujo,
  type Formulario,
  formularioDe,
  HORA_MAXIMA,
  HORA_MINIMA,
  pedidoDeCadastro,
  pedidoDeEdicao,
  type Recusa,
  recusaDe,
  SEM_RECUSA,
  validarFormulario,
} from '@/lib/corretores'
import { registrarAlteracaoNaoSalva } from '@/lib/inatividade'

const ESPECIALIDADES_ORDENADAS = Object.keys(ESPECIALIDADES) as Especialidade[]

/**
 * Cadastrar e editar corretor no mesmo formulario (D7 do desenho).
 *
 * `corretor === null` e o cadastro: `POST` completo pelo `/bff/*`. Com um
 * corretor, e a edicao: `PATCH` so do que mudou -- mesma ideia de
 * `pedidoDaEdicao`/`estaSujo` em `EdicaoDaQualificacao.tsx`, adaptada para os
 * campos do corretor. **Desativar NAO mora aqui** (D5/D7): e
 * `DesativarCorretor.tsx`, um fluxo de confirmacao separado, porque a card
 * pede um texto de confirmacao que este formulario nao tem onde encaixar.
 *
 * A validacao de capacidade 1-20 (D3) roda ANTES do `fetch`, porque o teto
 * so existe nesta tela -- o backend so garante `>= 1`.
 */
export function FormularioDeCorretor({ corretor }: { corretor: Corretor | null }) {
  const router = useRouter()
  const [aberto, setAberto] = useState(false)
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(corretor))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [regiaoNova, setRegiaoNova] = useState('')

  const chaveDoAviso = corretor ? `corretor-${corretor.id}` : 'corretor-novo'
  const sujo = aberto && estaSujo(inicial, atual)
  useEffect(() => {
    registrarAlteracaoNaoSalva(chaveDoAviso, sujo)
  }, [chaveDoAviso, sujo])
  // Sair com o formulario sujo descarta a alteracao: o aviso nao pode
  // continuar dizendo que ha algo a perder.
  useEffect(() => () => registrarAlteracaoNaoSalva(chaveDoAviso, false), [chaveDoAviso])

  function abrir() {
    const partida = formularioDe(corretor)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setRegiaoNova('')
    setAberto(true)
  }

  function fechar() {
    setAberto(false)
    setRecusa(SEM_RECUSA)
  }

  function mudar(campo: CampoDeTextoDoFormulario, valor: string) {
    setAtual((anterior) => ({ ...anterior, [campo]: valor }))
  }

  function alternarEspecialidade(especialidade: Especialidade) {
    setAtual((anterior) => ({
      ...anterior,
      especialidades: anterior.especialidades.includes(especialidade)
        ? anterior.especialidades.filter((item) => item !== especialidade)
        : [...anterior.especialidades, especialidade],
    }))
  }

  function adicionarRegiao() {
    const texto = regiaoNova.trim()
    if (!texto) {
      return
    }
    setAtual((anterior) => ({ ...anterior, regioesAtuacao: [...anterior.regioesAtuacao, texto] }))
    setRegiaoNova('')
  }

  function removerRegiao(indice: number) {
    setAtual((anterior) => ({
      ...anterior,
      regioesAtuacao: anterior.regioesAtuacao.filter((_, i) => i !== indice),
    }))
  }

  async function salvar(evento: React.FormEvent) {
    evento.preventDefault()

    const validacao = validarFormulario(atual)
    if (Object.keys(validacao.porCampo).length > 0) {
      setRecusa(validacao)
      return
    }

    if (corretor && !estaSujo(inicial, atual)) {
      fechar()
      return
    }

    setEnviando(true)
    setRecusa(SEM_RECUSA)

    const url = corretor
      ? `/bff/api/v1/corretores/${encodeURIComponent(corretor.id)}`
      : '/bff/api/v1/corretores'
    const corpo = corretor ? pedidoDeEdicao(inicial, atual) : pedidoDeCadastro(atual)

    let resposta: Response
    try {
      resposta = await fetch(url, {
        method: corretor ? 'PATCH' : 'POST',
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

    setAberto(false)
    router.refresh()
  }

  if (!aberto) {
    return (
      <button type="button" onClick={abrir}>
        {corretor ? 'Editar' : 'Cadastrar corretor'}
      </button>
    )
  }

  return (
    <form className="formulario-de-corretor" onSubmit={salvar} noValidate>
      {recusa.geral && (
        <p className="formulario-de-corretor__aviso" role="alert">
          {recusa.geral}
        </p>
      )}
      <CampoDeTexto rotulo="Nome" campo="nome" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto rotulo="E-mail" campo="email" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto rotulo="Telefone" campo="telefone" atual={atual} recusa={recusa} mudar={mudar} />
      <CampoDeTexto rotulo="CRECI" campo="creci" atual={atual} recusa={recusa} mudar={mudar} />

      <CampoDeEspecialidades
        atual={atual.especialidades}
        alternar={alternarEspecialidade}
        erro={recusa.porCampo.especialidades}
      />

      <CampoDeRegioes
        regioes={atual.regioesAtuacao}
        novo={regiaoNova}
        mudarNovo={setRegiaoNova}
        adicionar={adicionarRegiao}
        remover={removerRegiao}
        erro={recusa.porCampo.regioesAtuacao}
      />

      <CampoNumerico
        rotulo="Início do atendimento"
        campo="horarioInicio"
        min={HORA_MINIMA}
        max={HORA_MAXIMA}
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />
      <CampoNumerico
        rotulo="Fim do atendimento"
        campo="horarioFim"
        min={HORA_MINIMA}
        max={HORA_MAXIMA}
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />
      <CampoNumerico
        rotulo="Capacidade diária"
        campo="capacidadeDiaria"
        min={CAPACIDADE_MINIMA}
        max={CAPACIDADE_MAXIMA}
        atual={atual}
        recusa={recusa}
        mudar={mudar}
      />

      <label className="formulario-de-corretor__plantao">
        <input
          type="checkbox"
          checked={atual.plantao}
          onChange={(evento) =>
            setAtual((anterior) => ({ ...anterior, plantao: evento.target.checked }))
          }
        />
        Generalista de plantão
      </label>

      <div className="formulario-de-corretor__acoes">
        <button type="submit" disabled={enviando}>
          {corretor ? 'Salvar' : 'Cadastrar'}
        </button>
        <button type="button" onClick={fechar} disabled={enviando}>
          Cancelar
        </button>
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
    <span id={id} className="formulario-de-corretor__erro">
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
}: PropsDoCampo & { campo: 'nome' | 'email' | 'telefone' | 'creci' }) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-corretor__campo">
      <label htmlFor={id}>{rotulo}</label>
      <input
        id={id}
        type="text"
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

function CampoDeEspecialidades({
  atual,
  alternar,
  erro,
}: {
  atual: Especialidade[]
  alternar: (especialidade: Especialidade) => void
  erro?: string
}) {
  const id = useId()
  return (
    <fieldset className="formulario-de-corretor__especialidades">
      <legend>Especialidades</legend>
      {ESPECIALIDADES_ORDENADAS.map((especialidade) => (
        <label key={especialidade}>
          <input
            type="checkbox"
            checked={atual.includes(especialidade)}
            onChange={() => alternar(especialidade)}
          />
          {ESPECIALIDADES[especialidade]}
        </label>
      ))}
      <Erro id={`${id}-erro`} texto={erro} />
    </fieldset>
  )
}

/**
 * Regiao e texto livre, uma por linha/chip (D2 do desenho) -- nao ha
 * `<select>` porque nao existe vocabulario de backend para popular as
 * opcoes. `useId` evita colisao quando varios formularios estao na pagina
 * (a criacao mais uma edicao por linha da lista).
 */
function CampoDeRegioes({
  regioes,
  novo,
  mudarNovo,
  adicionar,
  remover,
  erro,
}: {
  regioes: string[]
  novo: string
  mudarNovo: (valor: string) => void
  adicionar: () => void
  remover: (indice: number) => void
  erro?: string
}) {
  const id = useId()
  return (
    <div className="formulario-de-corretor__regioes">
      <label htmlFor={id}>Regiões de atuação</label>
      {regioes.length > 0 && (
        <ul>
          {regioes.map((regiao, indice) => (
            <li key={`${regiao}-${indice}`}>
              {regiao}{' '}
              <button type="button" onClick={() => remover(indice)} aria-label={`Remover ${regiao}`}>
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
        Adicionar região
      </button>
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}

function CampoNumerico({
  rotulo,
  campo,
  min,
  max,
  atual,
  recusa,
  mudar,
}: PropsDoCampo & {
  campo: 'horarioInicio' | 'horarioFim' | 'capacidadeDiaria'
  min: number
  max: number
}) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-corretor__campo">
      <label htmlFor={id}>{rotulo}</label>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        step={1}
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      <Erro id={`${id}-erro`} texto={erro} />
    </div>
  )
}
