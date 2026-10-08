'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
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
 * Cadastrar e editar corretor com o mesmo formulario (D7 do desenho da
 * TEC-332).
 *
 * `corretor === null` e o cadastro: `POST` completo pelo `/bff/*`, num cartao
 * **sempre aberto** (D1 da TEC-397) -- depois de cadastrar, o formulario volta
 * vazio em vez de fechar. Com um corretor, e a edicao: o botao "Editar" abre
 * o formulario num `<dialog>` modal (D2 da TEC-397) e manda o `PATCH` so do
 * que mudou -- mesma ideia de `pedidoDaEdicao`/`estaSujo` em
 * `EdicaoDaQualificacao.tsx`. **Desativar NAO mora aqui** (D5/D7 da
 * TEC-332): e `DesativarCorretor.tsx`, um fluxo de confirmacao separado.
 *
 * A validacao de capacidade 1-20 (D3) roda ANTES do `fetch`, porque o teto
 * so existe nesta tela -- o backend so garante `>= 1`.
 */
export function FormularioDeCorretor({ corretor }: { corretor: Corretor | null }) {
  const router = useRouter()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const idDoTitulo = useId()
  const [aberto, setAberto] = useState(false)
  const [inicial, setInicial] = useState<Formulario>(() => formularioDe(corretor))
  const [atual, setAtual] = useState<Formulario>(inicial)
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa>(SEM_RECUSA)
  const [regiaoNova, setRegiaoNova] = useState('')

  // O cadastro nao tem "aberto": esta sempre de pe (D1 da TEC-397).
  const emEdicao = corretor !== null
  const visivel = !emEdicao || aberto

  const chaveDoAviso = corretor ? `corretor-${corretor.id}` : 'corretor-novo'
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
    const partida = formularioDe(corretor)
    setInicial(partida)
    setAtual(partida)
    setRecusa(SEM_RECUSA)
    setRegiaoNova('')
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
      return
    }
    // No cadastro, "Cancelar" descarta o que foi digitado (D1 da TEC-397).
    recomecar()
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

    if (emEdicao) {
      dialogRef.current?.close()
      setAberto(false)
    } else {
      recomecar()
    }
    router.refresh()
  }

  const formulario = (
    <form className="formulario-de-corretor" onSubmit={salvar} noValidate>
      {recusa.geral && (
        <p className="formulario-de-corretor__aviso" role="alert">
          {recusa.geral}
        </p>
      )}
      <div className="formulario-de-corretor__grade">
        <CampoDeTexto
          rotulo="Nome"
          campo="nome"
          obrigatorio
          exemplo="Ex.: Carlos Eduardo Silveira"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoDeTexto
          rotulo="E-mail"
          campo="email"
          obrigatorio
          exemplo="nome@imobiliaria.com"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoDeTexto
          rotulo="Telefone"
          campo="telefone"
          obrigatorio
          exemplo="(11) 98765-4321"
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoDeTexto rotulo="CRECI" campo="creci" exemplo="123456-F" atual={atual} recusa={recusa} mudar={mudar} />

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
          ajuda="Hora cheia em que a jornada começa."
          sufixo="h"
          campo="horarioInicio"
          min={HORA_MINIMA}
          max={HORA_MAXIMA}
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoNumerico
          rotulo="Fim do atendimento"
          ajuda="Visitas e avisos ao corretor só dentro da jornada."
          sufixo="h"
          campo="horarioFim"
          min={HORA_MINIMA}
          max={HORA_MAXIMA}
          atual={atual}
          recusa={recusa}
          mudar={mudar}
        />
        <CampoNumerico
          rotulo="Capacidade diária"
          ajuda={`Máximo de visitas agendadas por dia (${CAPACIDADE_MINIMA} a ${CAPACIDADE_MAXIMA}).`}
          exemplo="Ex.: 5"
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
          <span>
            Generalista de plantão
            <span className="formulario-de-corretor__ajuda">Recebe os leads sem corretor compatível.</span>
          </span>
        </label>
      </div>

      <div className="formulario-de-corretor__acoes">
        <Botao type="submit" disabled={enviando}>
          {corretor ? 'Salvar' : 'Cadastrar'}
        </Botao>
        <Botao variante="contorno" onClick={fechar} disabled={enviando}>
          Cancelar
        </Botao>
      </div>
    </form>
  )

  if (!emEdicao) {
    return (
      <Cartao como="section" aria-labelledby={idDoTitulo} className="cadastro-de-corretor">
        <div className="cadastro-de-corretor__cabecalho">
          <h2 id={idDoTitulo}>
            <span className="cadastro-de-corretor__ponto" aria-hidden="true" />
            Novo cadastro
          </h2>
          <p className="cadastro-de-corretor__legenda">
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
            // Esc fecha o modal sem passar por `fechar` (D2 da TEC-397).
            setAberto(false)
            setRecusa(SEM_RECUSA)
          }}
        >
          <h2 id={idDoTitulo} className="dialogo__titulo">
            Editar corretor
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
    <span id={id} className="formulario-de-corretor__erro">
      {texto}
    </span>
  ) : null
}

/**
 * O asterisco de obrigatorio sai do CSS (`.rotulo--obrigatorio::after`, D4 da
 * TEC-397), para nao entrar no nome acessivel: o leitor de tela ouve "Nome"
 * e o campo leva `aria-required`.
 */
function classeDoRotulo(obrigatorio?: boolean) {
  return obrigatorio ? 'rotulo--obrigatorio' : undefined
}

function CampoDeTexto({
  rotulo,
  campo,
  obrigatorio,
  exemplo,
  atual,
  recusa,
  mudar,
}: PropsDoCampo & {
  campo: 'nome' | 'email' | 'telefone' | 'creci'
  obrigatorio?: boolean
  exemplo?: string
}) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-corretor__campo">
      <label htmlFor={id} className={classeDoRotulo(obrigatorio)}>
        {rotulo}
      </label>
      <input
        id={id}
        className="campo"
        type="text"
        placeholder={exemplo}
        value={atual[campo]}
        onChange={(evento) => mudar(campo, evento.target.value)}
        aria-required={obrigatorio ? true : undefined}
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
    <fieldset className="formulario-de-corretor__especialidades" aria-describedby={erro ? `${id}-erro` : undefined}>
      <legend className="rotulo--obrigatorio">Especialidades</legend>
      <div className="formulario-de-corretor__caixa">
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
      </div>
      <Erro id={`${id}-erro`} texto={erro} />
    </fieldset>
  )
}

/**
 * Regiao e texto livre, um chip por regiao (D2 do desenho da TEC-332) -- nao
 * ha `<select>` porque nao existe vocabulario de backend para popular as
 * opcoes. `useId` evita colisao quando varios formularios estao na pagina
 * (o cadastro mais uma edicao aberta).
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
    <div className="formulario-de-corretor__campo formulario-de-corretor__regioes">
      <label htmlFor={id} className="rotulo--obrigatorio">
        Regiões de atuação
      </label>
      <input
        id={id}
        className="campo"
        type="text"
        placeholder="Ex.: Pinheiros, Itaim Bibi"
        value={novo}
        onChange={(evento) => mudarNovo(evento.target.value)}
        onKeyDown={(evento) => {
          if (evento.key === 'Enter') {
            evento.preventDefault()
            adicionar()
          }
        }}
        aria-invalid={erro ? true : undefined}
        aria-describedby={erro ? `${id}-erro` : undefined}
      />
      <Botao variante="contorno" onClick={adicionar}>
        <span aria-hidden="true">+</span> Adicionar região
      </Botao>
      <Erro id={`${id}-erro`} texto={erro} />
      {regioes.length > 0 && (
        <ul className="chips">
          {regioes.map((regiao, indice) => (
            <li key={`${regiao}-${indice}`} className="chip">
              {regiao}
              <button
                type="button"
                className="chip__remover"
                onClick={() => remover(indice)}
                aria-label={`Remover ${regiao}`}
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CampoNumerico({
  rotulo,
  ajuda,
  sufixo,
  exemplo,
  campo,
  min,
  max,
  atual,
  recusa,
  mudar,
}: PropsDoCampo & {
  ajuda?: string
  sufixo?: string
  exemplo?: string
  campo: 'horarioInicio' | 'horarioFim' | 'capacidadeDiaria'
  min: number
  max: number
}) {
  const id = useId()
  const erro = recusa.porCampo[campo]
  return (
    <div className="formulario-de-corretor__campo">
      <label htmlFor={id} className="rotulo--obrigatorio">
        {rotulo}
      </label>
      <span className={sufixo ? 'campo-com-unidade campo-com-unidade--sufixo' : 'campo-com-unidade'}>
        <input
          id={id}
          className="campo"
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          step={1}
          placeholder={exemplo}
          value={atual[campo]}
          onChange={(evento) => mudar(campo, evento.target.value)}
          aria-required
          aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? `${id}-erro` : undefined}
        />
        {sufixo && (
          <span className="campo-com-unidade__sufixo" aria-hidden="true">
            {sufixo}
          </span>
        )}
      </span>
      <Erro id={`${id}-erro`} texto={erro} />
      {ajuda && <span className="formulario-de-corretor__ajuda">{ajuda}</span>}
    </div>
  )
}
