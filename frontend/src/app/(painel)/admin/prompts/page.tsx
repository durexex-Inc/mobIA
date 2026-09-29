import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { SemPermissao } from '@/components/SemPermissao'
import { ROTULO_DO_AGENTE, rotaDoAgente } from '@/lib/prompts'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarAgentes, ErroDePrompt } from '@/lib/servidor/prompts'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Prompts do agente — mobIA',
}

const ENDERECO = '/admin/prompts'

/**
 * Os dois agentes versionados, cada um com a versao ativa, autor e data
 * (TEC-338, D1 do desenho: `GET /api/v1/prompts` ja devolve os dois de uma
 * vez, sem calculo do frontend). Primeiro cenario do Gherkin.
 */
export default async function PaginaDePrompts() {
  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('CONFIGURAR_AGENTE'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let itens: Awaited<ReturnType<typeof buscarAgentes>>['itens'] = []
  let erro: ErroDePrompt | null = null
  try {
    const resultado = await buscarAgentes(sessao.acesso)
    itens = resultado.itens
  } catch (falha) {
    erro = falha instanceof ErroDePrompt ? falha : new ErroDePrompt(0, 'sem resposta', null)
  }

  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: ENDERECO, erro: 'sessao_expirada' }))
  }

  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  return (
    <main className="painel">
      <h1>Prompts do agente</h1>
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar os prompts dos agentes."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : (
        <ul className="prompts-lista">
          {itens.map((item) => {
            const agente = rotaDoAgente(item.agente)
            return (
              <li key={item.agente}>
                <a href={`/admin/prompts/${agente}`}>{ROTULO_DO_AGENTE[agente]}</a>
                <span> — versão {item.versao}</span>
                {item.publicadaPor && <span>, publicada por {item.publicadaPor}</span>}
                {item.publicadaEm && <span> em {new Date(item.publicadaEm).toLocaleString('pt-BR')}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </main>
  )
}
