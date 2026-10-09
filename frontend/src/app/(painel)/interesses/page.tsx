import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { SemPermissao } from '@/components/SemPermissao'
import { TabelaDePedidos } from '@/components/TabelaDePedidos'
import { urlDoLogin } from '@/lib/destino'
import { type EstadoDosPedidos, estadoDaUrl, type PaginaDePedidos, urlDosPedidos } from '@/lib/interesses'
import { paginaInicialDe } from '@/lib/navegacao'
import { ErroDeInteresses, buscarInteresses } from '@/lib/servidor/interesses'
import { buscarCorretores, type CorretorDoFiltro } from '@/lib/servidor/leads'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Pedidos de interesse — mobIA',
}

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

/**
 * Os pedidos de interesse do portal (TEC-404, D9 do desenho): quem pediu
 * contato sobre qual imovel, e quem esta atendendo. Filtro e cursor na URL.
 *
 * **O recorte do CORRETOR e do backend** (D7), como em `/leads`: o FastAPI so
 * devolve os pedidos dele, e a pagina nao filtra nada por papel.
 */
export default async function PaginaDePedidos({ searchParams }: { searchParams: Promise<Busca> }) {
  const parametros = await searchParams
  const estado = estadoDaUrl(parametros.estado)
  const cursor = um(parametros.cursor) || undefined
  const endereco = urlDosPedidos(estado, cursor)

  // Antes de qualquer busca, como toda pagina do painel (D3 da TEC-312).
  const { sessao, quem, permitido } = await exigirPermissao(endereco, (p) => p.has('VER_LEADS'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  // O seletor de "Atribuir" so para quem pode atribuir (D7): a rota de
  // corretores pede a mesma permissao. Falhar aqui nao derruba a lista.
  let corretores: CorretorDoFiltro[] = []
  if (quem.permissoes.has('GERIR_CORRETORES')) {
    corretores = await buscarCorretores(sessao.acesso).catch(() => [])
  }

  let pagina: PaginaDePedidos | null = null
  let erro: ErroDeInteresses | null = null
  try {
    pagina = await buscarInteresses({ estado, cursor }, sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR; sem resposta nao ha status nem
    // codigo para o suporte, como em `/leads`.
    erro = falha instanceof ErroDeInteresses ? falha : new ErroDeInteresses(0, 'sem resposta', null)
  }

  // O `redirect` fica FORA do `try`: ele lanca para interromper o render, e o
  // `catch` o engoliria.
  if (erro?.status === 401) {
    // Apagar antes de redirecionar, ou o login devolveria a esta pagina num
    // laco (TEC-310, D5).
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: endereco, erro: 'sessao_expirada' }))
  }

  // A recusa do backend vence o menu (TEC-312, D4).
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  return (
    <main className="painel">
      <h1>Pedidos de interesse</h1>
      <FiltroDeEstado estado={estado} />
      {erro && <Falha erro={erro} endereco={endereco} estado={estado} />}
      {pagina && pagina.itens.length === 0 && (
        <p className="leads-vazio">
          <Vazio
            texto={
              estado === 'pendentes' ? 'Nenhum pedido de interesse pendente.' : 'Nenhum pedido de interesse.'
            }
          />
        </p>
      )}
      {pagina && pagina.itens.length > 0 && (
        <>
          <TabelaDePedidos itens={pagina.itens} quem={quem} corretores={corretores} />
          {pagina.proximoCursor && (
            <p className="pedidos-proxima">
              <a href={urlDosPedidos(estado, pagina.proximoCursor)}>Próxima página</a>
            </p>
          )}
        </>
      )}
    </main>
  )
}

/**
 * Pendentes ou todos, por LINK: trocar o filtro e trocar de endereco, e volta
 * a primeira pagina -- o cursor e do filtro anterior.
 */
function FiltroDeEstado({ estado }: { estado: EstadoDosPedidos }) {
  const opcoes: Array<{ valor: EstadoDosPedidos; rotulo: string }> = [
    { valor: 'pendentes', rotulo: 'Pendentes' },
    { valor: 'todos', rotulo: 'Todos' },
  ]
  return (
    <nav className="pedidos-filtro" aria-label="Filtro dos pedidos">
      {opcoes.map(({ valor, rotulo }) => (
        <a key={valor} href={urlDosPedidos(valor)} aria-current={estado === valor ? 'page' : undefined}>
          {rotulo}
        </a>
      ))}
    </nav>
  )
}

/**
 * A falha de carga. **Num 422 o recusado e o cursor**, e repetir o endereco
 * reproduziria o erro: "tentar de novo" volta a primeira pagina do mesmo
 * filtro. No resto, repete o endereco, com o codigo para o suporte.
 */
function Falha({
  erro,
  endereco,
  estado,
}: {
  erro: ErroDeInteresses
  endereco: string
  estado: EstadoDosPedidos
}) {
  if (erro.status === 422) {
    return (
      <ErroDeCarga
        mensagem={`Não foi possível carregar os pedidos: ${erro.message}`}
        urlParaTentarDeNovo={urlDosPedidos(estado)}
      />
    )
  }
  return (
    <ErroDeCarga
      mensagem="Não foi possível carregar os pedidos de interesse."
      requestId={erro.requestId}
      urlParaTentarDeNovo={endereco}
    />
  )
}
