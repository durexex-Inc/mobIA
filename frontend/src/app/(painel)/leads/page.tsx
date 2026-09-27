import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { BuscaDeLeads } from '@/components/BuscaDeLeads'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { SemPermissao } from '@/components/SemPermissao'
import { TabelaDeLeads } from '@/components/TabelaDeLeads'
import { urlDoLogin } from '@/lib/destino'
import { buscaEfetiva, ordemDaUrl, type PaginaDeLeads, urlDaLista } from '@/lib/leads'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarLeads, ErroDeLeads } from '@/lib/servidor/leads'
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
 * bairro. A tela de entrada do CORRETOR (D2 do desenho).
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
  const endereco = urlDaLista({ busca, ordem })

  // Antes de qualquer busca, como toda pagina do painel (D3 da TEC-312).
  const { sessao, quem, permitido } = await exigirPermissao(endereco, (p) => p.has('VER_LEADS'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let pagina: PaginaDeLeads | null = null
  let erro: ErroDeLeads | null = null
  try {
    pagina = await buscarLeads({ busca, ordem }, sessao.acesso)
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

  return (
    <main className="painel">
      <h1>Leads</h1>
      <BuscaDeLeads inicial={textoDaBusca} ordem={ordem} />
      {erro && <Falha erro={erro} endereco={endereco} />}
      {pagina && pagina.itens.length === 0 && (
        <p>
          <Vazio
            texto={busca ? `Nenhum lead encontrado para “${busca}”.` : 'Nenhum lead ainda.'}
          />
        </p>
      )}
      {pagina && pagina.itens.length > 0 && (
        <>
          <TabelaDeLeads itens={pagina.itens} ordem={ordem} busca={busca} agora={new Date()} />
          {/* A paginacao e a TEC-322 (L3 do desenho). Ate la, a tela diz que
              ha mais, em vez de deixar a pessoa achar que a lista acabou. */}
          {pagina.proximoCursor && (
            <p className="leads-mais">
              Mostrando os {pagina.itens.length} primeiros. Ver os demais ainda não está disponível.
            </p>
          )}
        </>
      )}
    </main>
  )
}

/**
 * A falha de carga (D8 do desenho).
 *
 * **Num 422, "tentar de novo" volta para a lista sem busca nem ordem**: o
 * parametro recusado estava na URL, e repeti-la reproduziria o erro. No resto
 * -- o backend fora, um 5xx --, tentar de novo e recarregar o mesmo endereco,
 * e o codigo para o suporte e o da resposta.
 */
function Falha({ erro, endereco }: { erro: ErroDeLeads; endereco: string }) {
  if (erro.status === 422) {
    return (
      <ErroDeCarga
        mensagem={`Não foi possível carregar a lista: ${erro.message}`}
        urlParaTentarDeNovo="/leads"
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
