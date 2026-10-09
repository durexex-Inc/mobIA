'use client'

import { useRouter } from 'next/navigation'
import { useId, useState } from 'react'

import { type AtendimentoDoPedido, podeAssumir } from '@/lib/interesses'

type Acao = 'aceitar' | 'atribuir'

/**
 * As acoes da linha de pedido de interesse (TEC-404, D7 e D9 do desenho):
 * "Assumir" e "Atribuir".
 *
 * **Os dois botoes so aparecem para quem a rota aceitaria**, e quem decide e
 * o backend: "Assumir" pede `podeAssumir` (o corretor dono, com o atendimento
 * pendente ou escalado), e "Atribuir" pede `podeAtribuir`, que a pagina so da
 * a quem tem `GERIR_CORRETORES` -- a mesma permissao da rota e da lista de
 * corretores que preenche o seletor. Um atendimento `CONCLUIDO` nao se
 * atribui: a rota recusaria com 409.
 *
 * **Depois do 200, `router.refresh()`**, e nao estado local: o aceite e a
 * atribuicao mudam a situacao, o corretor e quem pode revelar, que sao da
 * pagina (Server Component). Refazer a rota traz tudo da fonte, e a linha nao
 * mostra um estado que ela mesma inventou.
 */
export function AcoesDoPedido({
  atendimento,
  corretorId,
  podeAtribuir,
  corretores,
}: {
  atendimento: AtendimentoDoPedido
  corretorId: string | null
  podeAtribuir: boolean
  corretores: ReadonlyArray<{ id: string; nome: string }>
}) {
  const router = useRouter()
  const idDoSeletor = useId()
  const atual = atendimento.corretor?.id ?? ''
  const [escolhido, setEscolhido] = useState(atual)
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')

  const mostraAssumir = podeAssumir(atendimento, corretorId)
  const mostraAtribuir = podeAtribuir && atendimento.status !== 'CONCLUIDO'

  async function enviar(acao: Acao) {
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/handoffs/${encodeURIComponent(atendimento.id)}/${acao}`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: acao === 'atribuir' ? JSON.stringify({ corretorId: escolhido }) : undefined,
        cache: 'no-store',
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível concluir. Tente de novo.')
      return
    }

    setEnviando(false)
    if (!resposta.ok) {
      setAviso(motivoDaRecusa(resposta.status, acao))
      return
    }
    router.refresh()
  }

  if (!mostraAssumir && !mostraAtribuir) {
    return null
  }

  return (
    <div className="acoes-do-pedido">
      {mostraAssumir && (
        <button type="button" className="botao" onClick={() => enviar('aceitar')} disabled={enviando}>
          Assumir
        </button>
      )}
      {mostraAtribuir && (
        <span className="acoes-do-pedido__atribuir">
          <label htmlFor={idDoSeletor}>Corretor</label>
          <select
            id={idDoSeletor}
            value={escolhido}
            onChange={(evento) => setEscolhido(evento.target.value)}
            disabled={enviando}
          >
            {/* Sem corretor, o seletor comeca vazio: nenhuma opcao escolhida e
                "o atual", e o botao so habilita depois de escolher alguem. */}
            {atual === '' && <option value="">Escolha…</option>}
            {/* O dono atual pode ter sido desativado e nao vir na lista de
                ativos; sem esta opcao, o seletor mostraria outro nome com o
                valor dele, e o botao ficaria desabilitado sem razao visivel. */}
            {atendimento.corretor && !corretores.some((c) => c.id === atual) && (
              <option value={atual}>{atendimento.corretor.nome}</option>
            )}
            {corretores.map((corretor) => (
              <option key={corretor.id} value={corretor.id}>
                {corretor.nome}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="botao"
            onClick={() => enviar('atribuir')}
            disabled={enviando || escolhido === atual}
          >
            Atribuir
          </button>
        </span>
      )}
      {aviso && (
        <span className="acoes-do-pedido__aviso" role="alert">
          {aviso}
        </span>
      )}
    </div>
  )
}

function motivoDaRecusa(status: number, acao: Acao): string {
  if (status === 401) {
    return 'Sua sessão terminou. Recarregue a página para entrar de novo.'
  }
  if (status === 403) {
    return 'Você não tem permissão para esta ação.'
  }
  if (status === 404) {
    return 'Este pedido não existe mais.'
  }
  if (status === 409) {
    // O mesmo status, duas recusas: o aceite recusa o que outro ja aceitou, a
    // atribuicao recusa o atendimento concluido (D7).
    return acao === 'aceitar' ? 'Este pedido já foi assumido.' : 'Este atendimento já foi concluído.'
  }
  if (status === 422) {
    return 'Escolha um corretor ativo.'
  }
  return 'Não foi possível concluir. Tente de novo.'
}
