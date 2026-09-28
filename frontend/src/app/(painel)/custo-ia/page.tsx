import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { CustoDeIA } from '@/components/CustoDeIA'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Filtros } from '@/components/Filtros'
import { SemPermissao } from '@/components/SemPermissao'
import { buscarCusto, type CustoDeIA as CustoDeIATipo } from '@/lib/custo'
import { urlDoLogin } from '@/lib/destino'
import { ErroDeMetricas, type Filtros as FiltrosTipo } from '@/lib/metricas'
import { paginaInicialDe } from '@/lib/navegacao'
import { periodoPadrao } from '@/lib/periodo'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Custo de IA — mobIA',
}

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

/**
 * Os mesmos filtros do funil (`app/(painel)/page.tsx::filtrosDaUrl`), na
 * mesma forma -- a rota de custo aceita exatamente os mesmos parâmetros
 * (`de`, `ate`, `canal`, `intencao`, `temperatura`), embora o período
 * signifique coisa diferente por baixo (D1 do desenho: quando o gasto
 * aconteceu, não a coorte).
 */
function filtrosDaUrl(busca: Busca): FiltrosTipo {
  const padrao = periodoPadrao(new Date())
  return {
    de: um(busca.de) ?? padrao.de,
    ate: um(busca.ate) ?? padrao.ate,
    canal: um(busca.canal),
    intencao: um(busca.intencao),
    temperatura: um(busca.temperatura),
  }
}

/** Mesma decisão do funil: 422 é filtro inválido, o resto é o backend. */
function avisoDe(erro: ErroDeMetricas): string {
  if (erro.status === 422) {
    return `Não foi possível carregar: um filtro tem valor inválido — ${erro.message}`
  }
  return 'Não foi possível carregar os dados do painel. Os números não seriam confiáveis, então não são mostrados.'
}

function urlDoRecorte(filtros: FiltrosTipo): string {
  const busca = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      busca.set(chave, valor)
    }
  }
  return `/custo-ia?${busca.toString()}`
}

/**
 * O painel de custo de IA (TEC-319, RF-FE-06). Molde idêntico ao do funil
 * (`app/(painel)/page.tsx`): mesma guarda, mesmos filtros, mesmo tratamento
 * de erro -- só o dado buscado e a rota mudam.
 */
export default async function Pagina({ searchParams }: { searchParams: Promise<Busca> }) {
  const busca = await searchParams
  const filtros = filtrosDaUrl(busca)
  const recorte = urlDoRecorte(filtros)

  const { sessao, quem, permitido } = await exigirPermissao(recorte, (p) => p.has('VER_FUNIL'))
  if (!permitido) {
    // Esta tela nunca é a página inicial de ninguém (`paginaInicialDe` só
    // devolve `/` ou `/leads`), então quem chegar aqui sem `VER_FUNIL` sempre
    // é redirecionado -- mesma regra do funil (TEC-321, D2).
    redirect(paginaInicialDe(quem.permissoes))
  }

  let custo: CustoDeIATipo | null = null
  let erroDeCarga: ErroDeMetricas | null = null
  let aviso: string | null = null

  try {
    custo = await buscarCusto(filtros, sessao.acesso)
  } catch (erro) {
    erroDeCarga = erro instanceof ErroDeMetricas ? erro : null
    aviso = erroDeCarga
      ? avisoDe(erroDeCarga)
      : 'Não foi possível carregar os dados do painel.'
  }

  if (erroDeCarga?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: recorte, erro: 'sessao_expirada' }))
  }

  if (erroDeCarga?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  const erroDeFiltro = erroDeCarga?.status === 422 ? erroDeCarga : null

  return (
    <main className="painel">
      <h1>Custo de IA</h1>
      <Filtros
        atuais={filtros}
        erro={erroDeFiltro ? (aviso ?? undefined) : undefined}
        campos={erroDeFiltro ? erroDeFiltro.campos : []}
      />
      {aviso && !erroDeFiltro && (
        <ErroDeCarga
          mensagem={aviso}
          requestId={erroDeCarga?.requestId}
          urlParaTentarDeNovo={recorte}
        />
      )}
      {custo ? <CustoDeIA custo={custo} /> : null}
    </main>
  )
}
