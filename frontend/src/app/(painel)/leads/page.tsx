import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { BuscaDeLeads } from '@/components/BuscaDeLeads'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { type FiltroPorCorretor, FiltrosDeLeads } from '@/components/FiltrosDeLeads'
import { PaginacaoDeLeads } from '@/components/PaginacaoDeLeads'
import { SemPermissao } from '@/components/SemPermissao'
import { TabelaDeLeads } from '@/components/TabelaDeLeads'
import { urlDoLogin } from '@/lib/destino'
import {
  buscaEfetiva,
  filtrosDaUrl,
  ordemDaUrl,
  origemDoFunilDaUrl,
  type PaginaDeLeads,
  posicaoDaUrl,
  urlDaLista,
} from '@/lib/leads'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarCorretores, buscarPaginas, ErroDeLeads } from '@/lib/servidor/leads'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Leads — mobIA',
}

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

/**
 * A lista de leads (TEC-321, RF-FE-07): por score, com busca por telefone ou
 * bairro. A tela de entrada do CORRETOR (D2 do desenho). Desde a TEC-322,
 * com filtros e paginacao, todos na URL.
 *
 * **O recorte do CORRETOR e do backend**, pela claim do JWT (D7 da TEC-192). A
 * pagina nao filtra nada por papel e nao deve filtrar: um filtro aqui seria
 * uma segunda copia da regra, e o FastAPI ja devolve so os leads dele.
 */
export default async function PaginaDeLeads({ searchParams }: { searchParams: Promise<Busca> }) {
  const parametros = await searchParams
  const textoDaBusca = um(parametros.busca) ?? ''
  // A regra dos 2 caracteres vale tambem aqui, e nao so na caixa (D5): uma
  // `?busca=a` digitada na URL nao chega ao FastAPI.
  const busca = buscaEfetiva(textoDaBusca)
  const ordem = ordemDaUrl(um(parametros.ordenar))
  const filtros = filtrosDaUrl(parametros)
  const origemDoFunil = origemDoFunilDaUrl(parametros)
  const posicao = posicaoDaUrl(parametros)
  const endereco = urlDaLista({ busca, ordem, filtros, posicao, origemDoFunil })

  // Antes de qualquer busca, como toda pagina do painel (D3 da TEC-312).
  const { sessao, quem, permitido } = await exigirPermissao(endereco, (p) => p.has('VER_LEADS'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  // O filtro por corretor por papel (D5 da TEC-322): so quem pode listar os
  // corretores escolhe entre eles.
  let corretor: FiltroPorCorretor = { modo: 'indisponivel' }
  if (quem.papel === 'CORRETOR') {
    corretor = { modo: 'oculto' }
  } else if (quem.permissoes.has('GERIR_CORRETORES')) {
    // Falhar aqui nao derruba a lista: o filtro fica sem opcoes.
    corretor = { modo: 'lista', opcoes: await buscarCorretores(sessao.acesso).catch(() => []) }
  }

  let paginas: Array<PaginaDeLeads & { numero: number }> | null = null
  let erro: ErroDeLeads | null = null
  try {
    paginas = await buscarPaginas({ busca, ordem, filtros, origemDoFunil }, posicao, sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR, e nao responder: sem resposta
    // nao ha status nem codigo para o suporte, e a tela diz so que falhou --
    // como o funil faz.
    erro = falha instanceof ErroDeLeads ? falha : new ErroDeLeads(0, 'sem resposta', null)
  }

  // O `redirect` fica FORA do `try` pela razao do funil: ele lanca para
  // interromper o render, e o `catch` o engoliria.
  if (erro?.status === 401) {
    // Apagar antes de redirecionar: sem isto, o login veria a sessao viva e
    // devolveria a esta pagina, num laco (TEC-310, D5).
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: endereco, erro: 'sessao_expirada' }))
  }

  // A recusa do backend vence o menu (TEC-312, D4).
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  const itens = paginas?.flatMap((p) => p.itens) ?? []
  const ultima = paginas?.at(-1) ?? null
  // Com "carregar mais", as linhas das paginas anteriores a atual (D3).
  const quantasAnteriores = paginas ? itens.length - (ultima?.itens.length ?? 0) : 0
  const primeiraComFiltros = urlDaLista({ busca, ordem, filtros, origemDoFunil })

  return (
    <main className="painel">
      <h1>Leads</h1>
      {origemDoFunil?.etapa && (
        // A origem do funil (TEC-318): sem isto, a lista parece menor do que
        // a gerente esperava, sem dizer por que. `BuscaDeLeads` e
        // `FiltrosDeLeads` NAO preservam isto ao mudar busca/filtro (D6) --
        // por isso o link volta para `/leads` limpo, e nao so remove a etapa.
        <p className="leads-origem-do-funil">
          Etapa do funil: <strong>{origemDoFunil.etapa}</strong>
          {origemDoFunil.de && origemDoFunil.ate && (
            <> — período de {origemDoFunil.de} a {origemDoFunil.ate}</>
          )}
          {' · '}
          <a href={urlDaLista({ busca, ordem, filtros })}>Ver todos os leads</a>
        </p>
      )}
      <BuscaDeLeads inicial={textoDaBusca} ordem={ordem} filtros={filtros} />
      <FiltrosDeLeads busca={busca} ordem={ordem} filtros={filtros} corretor={corretor} />
      {erro && <Falha erro={erro} endereco={endereco} primeiraPagina={primeiraComFiltros} />}
      {paginas && itens.length === 0 && (
        <p className="leads-vazio">
          <Vazio
            texto={
              busca
                ? `Nenhum lead encontrado para “${busca}”.`
                : Object.values(filtros).some(Boolean)
                  ? 'Nenhum lead com estes filtros.'
                  : 'Nenhum lead ainda.'
            }
          />
        </p>
      )}
      {paginas && itens.length > 0 && (
        <>
          <TabelaDeLeads
            itens={itens}
            ordem={ordem}
            busca={busca}
            filtros={filtros}
            origemDoFunil={origemDoFunil}
            agora={new Date()}
            abreDetalhe={quem.permissoes.has('VER_DETALHE_DO_LEAD')}
            podeRevelar={quem.permissoes.has('VER_DADOS_COMPLETOS')}
            quantasAnteriores={quantasAnteriores}
          />
          <PaginacaoDeLeads
            estado={{ busca, ordem, filtros, origemDoFunil }}
            posicao={posicao}
            proximoCursor={ultima?.proximoCursor ?? null}
          />
        </>
      )}
    </main>
  )
}

/**
 * A falha de carga (D8 do desenho).
 *
 * **Num 422, "tentar de novo" volta a primeira pagina com os mesmos
 * filtros** (TEC-322): o que o backend recusa e o cursor -- os filtros a
 * tela ja validou em `filtrosDaUrl` --, e um cursor que deixou de valer
 * (o lead sumiu) reproduziria o erro. No resto -- o backend fora, um 5xx --,
 * tentar de novo e recarregar o mesmo endereco, e o codigo para o suporte e o
 * da resposta.
 */
function Falha({
  erro,
  endereco,
  primeiraPagina,
}: {
  erro: ErroDeLeads
  endereco: string
  primeiraPagina: string
}) {
  if (erro.status === 422) {
    return (
      <ErroDeCarga
        mensagem={`Não foi possível carregar a lista: ${erro.message}`}
        urlParaTentarDeNovo={primeiraPagina}
      />
    )
  }
  return (
    <ErroDeCarga
      mensagem="Não foi possível carregar a lista de leads."
      requestId={erro.requestId}
      urlParaTentarDeNovo={endereco}
    />
  )
}
