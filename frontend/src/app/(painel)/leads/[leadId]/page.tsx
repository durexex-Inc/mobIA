import type { Metadata } from 'next'
import Link from 'next/link'
import { redirect } from 'next/navigation'

import { SecoesDoDetalhe } from '@/components/DetalheDoLead'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { SemPermissao } from '@/components/SemPermissao'
import { urlDoLogin } from '@/lib/destino'
import type { DetalheDoLead } from '@/lib/detalhe'
import {
  canalLegivel,
  dataAbsoluta,
  identificacaoDoLead,
  statusLegivel,
  tempoRelativo,
} from '@/lib/leads'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarDetalhe, ErroDeLeads } from '@/lib/servidor/leads'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Lead — mobIA',
}

/**
 * O detalhe do lead (TEC-323, RF-FE-08): o resumo no topo, depois contato,
 * qualificacao, agendamentos e follow-ups.
 *
 * **Abrir esta pagina grava um acesso na trilha** (D3 da TEC-193). Por isso a
 * lista linka para ela com `<a>`, e nao com `next/link` (D2 do desenho): o
 * prefetch padrao para no `loading.tsx` ao lado e nao roda esta pagina, mas um
 * `prefetch={true}`, ou este `loading.tsx` apagado, passaria a rodar -- e a
 * gravar um acesso por linha visivel. O `<a>` nao depende de nenhum dos dois.
 *
 * Os links DAQUI para a lista sao `<Link>`: a lista nao grava nada.
 */
export default async function PaginaDoLead({ params }: { params: Promise<{ leadId: string }> }) {
  const { leadId } = await params
  const endereco = `/leads/${encodeURIComponent(leadId)}`

  // Antes de qualquer busca (D3 da TEC-312). LEITURA ve a lista e nao o
  // detalhe: a lista e um indice sem dado pessoal, e esta tela nao.
  const { sessao, quem, permitido } = await exigirPermissao(endereco, (p) =>
    p.has('VER_DETALHE_DO_LEAD'),
  )
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let detalhe: DetalheDoLead | null = null
  let erro: ErroDeLeads | null = null
  try {
    detalhe = await buscarDetalhe(leadId, sessao.acesso)
  } catch (falha) {
    erro = falha instanceof ErroDeLeads ? falha : new ErroDeLeads(0, 'sem resposta', null)
  }

  // Fora do `try`: o `redirect` lanca para interromper o render.
  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: endereco, erro: 'sessao_expirada' }))
  }

  // O quarto cenario do Gherkin: o CORRETOR que abre o lead de outro pelo
  // endereco direto. Quem recusa e o backend, pelo vinculo do handoff; a tela
  // so diz isso.
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial="/leads" />
  }

  // 422 aqui e o `leadId` que nao e UUID -- o FastAPI recusa o caminho antes
  // de procurar. Para quem digitou o endereco, e o mesmo que nao existir.
  if (erro?.status === 404 || erro?.status === 422) {
    return (
      <main className="painel">
        <div role="alert" className="estado-sem-permissao">
          <h1>Lead não encontrado</h1>
          <p>Este endereço não corresponde a nenhum lead.</p>
          <Link href="/leads">Voltar para a lista</Link>
        </div>
      </main>
    )
  }

  if (erro || !detalhe) {
    return (
      <main className="painel">
        <p>
          <Link href="/leads">← Voltar para a lista</Link>
        </p>
        <ErroDeCarga
          mensagem="Não foi possível carregar o lead."
          requestId={erro?.requestId}
          urlParaTentarDeNovo={endereco}
        />
      </main>
    )
  }

  const agora = new Date()
  return (
    <main className="painel detalhe">
      <p>
        <Link href="/leads">← Voltar para a lista</Link>
      </p>
      {/* Sem nome: nenhuma tabela o guarda (L3). O titulo e o telefone
          mascarado, como a primeira coluna da lista. */}
      <h1>{identificacaoDoLead({ telefone: detalhe.contato.telefone, channel: detalhe.channel })}</h1>
      <p className="detalhe-cabecalho">
        Score {detalhe.score ?? '—'} · {statusLegivel(detalhe.status)} ·{' '}
        {canalLegivel(detalhe.channel)} · última interação{' '}
        <time dateTime={detalhe.ultimaInteracaoEm} title={dataAbsoluta(detalhe.ultimaInteracaoEm)}>
          {tempoRelativo(detalhe.ultimaInteracaoEm, agora)}
        </time>
      </p>
      <SecoesDoDetalhe detalhe={detalhe} agora={agora} />
    </main>
  )
}
