'use client'

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

import { urlDoLogin } from '@/lib/destino'
import {
  type Fase,
  faseDaInatividade,
  haAlteracaoNaoSalva,
  MS_ENTRE_BATIMENTOS,
  ouvirAlteracoes,
} from '@/lib/inatividade'

/**
 * O aviso de sessao ociosa (TEC-311) -- o primeiro componente de cliente do
 * painel, e por uma razao so: "30 minutos sem interacao" nao se observa no
 * servidor.
 *
 * **So importa modulos puros** (`lib/destino`, `lib/inatividade`). Nada de
 * `lib/servidor/` pode chegar aqui, e o `server-only` reprovaria o build se
 * chegasse. O componente nao conhece token nenhum: ele fala com o servidor
 * por duas rotas do proprio painel, `POST /sessao/atividade` e `POST /sair`.
 *
 * O servidor tambem encerra a sessao ociosa, com folga (D3 do desenho) --
 * este aviso e a parte que da a pessoa a chance de continuar.
 */

/**
 * A ultima interacao, compartilhada entre abas (D2). Guarda um horario e nada
 * mais -- nenhum token, nenhum id de sessao.
 */
const CHAVE_COMPARTILHADA = 'mobia:ultima-interacao'

const EVENTOS_DE_INTERACAO = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'mousemove'] as const

function lerCompartilhada(): number {
  try {
    const valor = Number(window.localStorage.getItem(CHAVE_COMPARTILHADA))
    return Number.isFinite(valor) ? valor : 0
  } catch {
    // Sem `localStorage` (modo privado, bloqueio): cada aba conta sozinha.
    return 0
  }
}

function gravarCompartilhada(horario: number): void {
  try {
    window.localStorage.setItem(CHAVE_COMPARTILHADA, String(horario))
  } catch {
    // Ver `lerCompartilhada`.
  }
}

function telaAtual(): string {
  return `${window.location.pathname}${window.location.search}`
}

export function AvisoDeInatividade({
  navegar = (url: string) => window.location.assign(url),
}: {
  /** Para onde ir quando a sessao acaba. Existe para o teste; o padrao e navegar de verdade. */
  navegar?: (url: string) => void
}) {
  const ultimaInteracao = useRef(0)
  const ultimoBatimento = useRef(0)
  const ultimoMovimento = useRef(0)
  const encerrando = useRef(false)
  const [fase, setFase] = useState<Fase>({ fase: 'ativo' })
  const alteracaoPendente = useSyncExternalStore(ouvirAlteracoes, haAlteracaoNaoSalva, () => false)

  const encerrar = useCallback(async () => {
    if (encerrando.current) {
      return
    }
    encerrando.current = true
    // `/sair` revoga o refresh e apaga a sessao (TEC-310). Se falhar, o
    // servidor encerra sozinho em 32 minutos de ociosidade (D3): o login vem
    // de qualquer jeito.
    await fetch('/sair', { method: 'POST' }).catch(() => undefined)
    navegar(urlDoLogin({ returnTo: telaAtual(), erro: 'inatividade' }))
  }, [navegar])

  const bater = useCallback(async () => {
    ultimoBatimento.current = Date.now()
    const resposta = await fetch('/sessao/atividade', { method: 'POST' }).catch(() => null)
    if (resposta?.status === 401 && !encerrando.current) {
      // A sessao ja acabou do lado do servidor -- por outra aba, pelo limite
      // do servidor, por um "Sair" em outro lugar.
      encerrando.current = true
      navegar(urlDoLogin({ returnTo: telaAtual(), erro: 'sessao_expirada' }))
    }
  }, [navegar])

  const interagiu = useCallback(
    (forcarBatimento = false) => {
      if (encerrando.current) {
        return
      }
      const agora = Date.now()
      ultimaInteracao.current = agora
      gravarCompartilhada(agora)
      setFase((atual) => (atual.fase === 'ativo' ? atual : { fase: 'ativo' }))
      if (forcarBatimento || agora - ultimoBatimento.current >= MS_ENTRE_BATIMENTOS) {
        void bater()
      }
    },
    [bater],
  )

  useEffect(() => {
    // A aba que abre agora e uma interacao; e se outra aba interagiu depois,
    // vale a outra.
    ultimaInteracao.current = Math.max(Date.now(), lerCompartilhada())
    gravarCompartilhada(ultimaInteracao.current)
    ultimoBatimento.current = Date.now()

    function aoInteragir(evento: Event) {
      if (evento.type === 'mousemove') {
        const agora = Date.now()
        if (agora - ultimoMovimento.current < 1000) {
          return
        }
        ultimoMovimento.current = agora
      }
      interagiu()
    }

    function aoMudarOutraAba(evento: StorageEvent) {
      if (evento.key !== CHAVE_COMPARTILHADA || !evento.newValue) {
        return
      }
      const horario = Number(evento.newValue)
      if (horario > ultimaInteracao.current) {
        ultimaInteracao.current = horario
        setFase((atual) => (atual.fase === 'ativo' ? atual : { fase: 'ativo' }))
      }
    }

    // Uma checagem por segundo, comparando HORARIOS (D1): a aba que o
    // navegador pos para dormir acorda sabendo quanto tempo passou.
    function verificar() {
      ultimaInteracao.current = Math.max(ultimaInteracao.current, lerCompartilhada())
      const nova = faseDaInatividade(Date.now(), ultimaInteracao.current)
      if (nova.fase === 'encerrar') {
        void encerrar()
        return
      }
      setFase((atual) =>
        atual.fase === nova.fase &&
        (atual.fase !== 'aviso' || nova.fase !== 'aviso' || atual.segundosRestantes === nova.segundosRestantes)
          ? atual
          : nova,
      )
    }

    EVENTOS_DE_INTERACAO.forEach((nome) =>
      window.addEventListener(nome, aoInteragir, { passive: true }),
    )
    window.addEventListener('storage', aoMudarOutraAba)
    const relogio = window.setInterval(verificar, 1000)
    return () => {
      EVENTOS_DE_INTERACAO.forEach((nome) => window.removeEventListener(nome, aoInteragir))
      window.removeEventListener('storage', aoMudarOutraAba)
      window.clearInterval(relogio)
    }
  }, [encerrar, interagiu])

  if (fase.fase !== 'aviso') {
    return null
  }

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="aviso-inatividade-titulo"
      aria-describedby="aviso-inatividade-texto"
      className="aviso-inatividade"
    >
      <h2 id="aviso-inatividade-titulo">Sua sessão vai ser encerrada</h2>
      <p id="aviso-inatividade-texto">
        Você está há 30 minutos sem usar o painel. A sessão será encerrada em{' '}
        {fase.segundosRestantes} segundos.
      </p>
      {alteracaoPendente && (
        <p className="aviso-inatividade-alteracao">
          <strong>Você tem alterações que não foram salvas e serão perdidas.</strong>
        </p>
      )}
      {/* O clique ja e uma interacao; o `true` garante o batimento mesmo que
          o ultimo tenha saido ha menos de um minuto. */}
      <button type="button" autoFocus onClick={() => interagiu(true)}>
        Continuar conectado
      </button>
    </div>
  )
}
