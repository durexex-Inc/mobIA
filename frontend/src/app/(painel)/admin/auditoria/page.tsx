import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { FiltrosDeAuditoria } from '@/components/FiltrosDeAuditoria'
import { PaginacaoDaAuditoria } from '@/components/PaginacaoDaAuditoria'
import { SemPermissao } from '@/components/SemPermissao'
import { TabelaDeAuditoria } from '@/components/TabelaDeAuditoria'
import { filtrosDaUrl, posicaoDaUrl, urlDaLista } from '@/lib/auditoria'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarPaginas, ErroDaTrilha } from '@/lib/servidor/auditoria'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Trilha de auditoria — mobIA',
}

const ENDERECO = '/admin/auditoria'

type Busca = Record<string, string | string[] | undefined>

/**
 * A trilha de auditoria (TEC-343, RF-FE-15.4): quem viu ou alterou o quê e
 * quando, com filtros por autor, tipo e período, e paginação por cursor.
 *
 * **A guarda é `VER_AUDITORIA`**, a mesma permissão que a rota do FastAPI
 * exige (D3 da TEC-312, como toda página do painel).
 */
export default async function PaginaDaAuditoria({ searchParams }: { searchParams: Promise<Busca> }) {
  const parametros = await searchParams
  const filtros = filtrosDaUrl(parametros)
  const posicao = posicaoDaUrl(parametros)
  const endereco = urlDaLista({ filtros, posicao })

  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('VER_AUDITORIA'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let paginas: Awaited<ReturnType<typeof buscarPaginas>> | null = null
  let erro: ErroDaTrilha | null = null
  try {
    paginas = await buscarPaginas(filtros, posicao, sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR: sem resposta nao ha status nem
    // codigo para o suporte, como na lista de leads.
    erro = falha instanceof ErroDaTrilha ? falha : new ErroDaTrilha(0, 'sem resposta', null)
  }

  // Fora do `try`: `redirect` lanca para interromper o render, e o `catch` o
  // engoliria.
  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: endereco, erro: 'sessao_expirada' }))
  }

  // A recusa do backend vence o menu (TEC-312, D4).
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  const itens = paginas?.flatMap((p) => p.itens) ?? []
  const ultima = paginas?.at(-1) ?? null

  return (
    <main className="painel">
      <h1>Trilha de auditoria</h1>
      <p>Quem viu ou alterou o quê e quando. Somente leitura.</p>
      <FiltrosDeAuditoria filtros={filtros} />
      {erro && (
        <ErroDeCarga
          mensagem="Não foi possível carregar a trilha de auditoria."
          requestId={erro.requestId}
          urlParaTentarDeNovo={endereco}
        />
      )}
      {paginas && itens.length === 0 && (
        <p>
          <Vazio
            texto={
              Object.values(filtros).some(Boolean)
                ? 'Nenhum evento com estes filtros.'
                : 'Nenhum evento ainda.'
            }
          />
        </p>
      )}
      {paginas && itens.length > 0 && (
        <>
          <TabelaDeAuditoria itens={itens} />
          <PaginacaoDaAuditoria
            filtros={filtros}
            posicao={posicao}
            proximoCursor={ultima?.proximoCursor ?? null}
          />
        </>
      )}
    </main>
  )
}
