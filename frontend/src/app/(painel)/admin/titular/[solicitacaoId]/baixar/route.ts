import { redirect } from 'next/navigation'
import { NextResponse } from 'next/server'

import { chamarApi } from '@/lib/servidor/api'
import { quemSou } from '@/lib/servidor/quemSou'
import { exigirSessao } from '@/lib/servidor/sessao'
import { buscarSolicitacao } from '@/lib/servidor/titular'

const FILA = '/admin/titular'

/**
 * O download da portabilidade (TEC-341): um `<a href>` para cá, que o
 * navegador trata como arquivo por causa do `Content-Disposition`. Sem
 * JavaScript, no molde de `ErroDeCarga` (D2 do desenho).
 *
 * **Guarda no molde de toda página do painel** (D3): `exigirSessao` manda ao
 * login sem sessão; sem `ATENDER_TITULAR`, redireciona à fila -- que roda a
 * mesma guarda e desenha "Sem permissão" sozinha. Um Route Handler não
 * renderiza JSX, então não duplica aquela tela.
 *
 * **"Já concluído" é a solicitação relida sem filtro de status** (D4): a
 * fila só lista `ABERTA`, então só uma corrida -- duas abas, clique duplo --
 * leva aqui com uma que já não é mais. Não encontrada ou de outro tipo voltam
 * à fila em silêncio -- L1, sem cenário na card.
 *
 * **O status vem ANTES do `leadId`, e a ordem não é gosto.** Uma vez
 * `ATENDIDA` ou `RECUSADA`, o backend zera `(channel, conversation_key)`
 * daquela linha -- é a `ck_solicitacoes_de_titular_par_com_status` que a
 * TEC-340 já documentou --, e por isso toda solicitação concluída chega
 * aqui com `leadId: null`. Checar `leadId` antes do status faria TODO
 * "já concluído" cair no redirecionamento silencioso, e o cenário da card
 * nunca disparasse. `leadId` nulo só é a lacuna L1 quando o status ainda é
 * `ABERTA` -- a `ABERTA` cujo apelido sumiu por fora (D2 da TEC-340).
 *
 * **O corpo do backend é transmitido como veio**, sem reanalisar: só os
 * cabeçalhos mudam.
 */
export async function GET(
  _requisicao: Request,
  { params }: { params: Promise<{ solicitacaoId: string }> },
) {
  const { solicitacaoId } = await params
  const sessao = await exigirSessao(FILA)
  const quem = await quemSou(sessao.acesso)
  if (!quem.permissoes.has('ATENDER_TITULAR')) {
    redirect(FILA)
  }

  const pedido = await buscarSolicitacao(solicitacaoId, sessao.acesso)
  if (pedido === null || pedido.tipo !== 'ACESSO') {
    redirect(FILA)
  }
  if (pedido.status !== 'ABERTA') {
    redirect(`${FILA}?concluido=1`)
  }
  if (pedido.leadId === null) {
    redirect(FILA)
  }

  const exportado = await chamarApi(`/api/v1/leads/${encodeURIComponent(pedido.leadId)}/dados-pessoais`, {
    acesso: sessao.acesso,
  })
  if (!exportado.ok) {
    redirect(FILA)
  }

  return new NextResponse(exportado.body, {
    headers: {
      'Content-Type': 'application/json',
      'Content-Disposition': `attachment; filename="titular-${solicitacaoId}.json"`,
      'Cache-Control': 'no-store',
    },
  })
}
