import { Filtros } from '@/components/Filtros'
import { Funil } from '@/components/Funil'
import { Indicadores } from '@/components/Indicadores'
import {
  buscarFunil,
  ErroDeMetricas,
  type Filtros as FiltrosTipo,
  type Funil as FunilTipo,
} from '@/lib/metricas'
import { periodoPadrao } from '@/lib/periodo'

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

function filtrosDaUrl(busca: Busca): FiltrosTipo {
  const padrao = periodoPadrao(new Date())
  return {
    de: um(busca.de) ?? padrao.de,
    ate: um(busca.ate) ?? padrao.ate,
    canal: um(busca.canal),
    intencao: um(busca.intencao),
    temperatura: um(busca.temperatura),
    corretorId: um(busca.corretorId),
  }
}

/**
 * O aviso depende do status, porque as causas sao diferentes e o conserto
 * tambem: 403 e configuracao do operador (token errado no env do servidor),
 * 422 e filtro invalido que a gerente pode corrigir sozinha, e o resto e o
 * backend. Um aviso unico mandaria a gerente procurar o erro dela num
 * problema que nao e dela.
 */
function avisoDe(erro: ErroDeMetricas): string {
  if (erro.status === 403) {
    return 'Não foi possível carregar: o servidor recusou o token de acesso. É configuração do ambiente, não um problema do seu filtro.'
  }
  if (erro.status === 422) {
    return `Não foi possível carregar: um filtro tem valor inválido — ${erro.message}`
  }
  return 'Não foi possível carregar os dados do painel. Os números não seriam confiáveis, então não são mostrados.'
}

export default async function Pagina({ searchParams }: { searchParams: Promise<Busca> }) {
  const busca = await searchParams
  const filtros = filtrosDaUrl(busca)

  let funil: FunilTipo | null = null
  let aviso: string | null = null

  try {
    funil = await buscarFunil(filtros)
  } catch (erro) {
    // O funil NAO e renderizado quando a busca falha. Um funil de zeros e
    // indistinguivel de um periodo sem lead, e a gerente leria a queda como
    // fato do negocio -- que e a decisao mais cara que este painel existe
    // para apoiar.
    aviso =
      erro instanceof ErroDeMetricas
        ? avisoDe(erro)
        : 'Não foi possível carregar os dados do painel.'
  }

  return (
    <main className="painel">
      <h1>Funil de leads</h1>
      <Filtros atuais={filtros} erro={aviso ?? undefined} />
      {funil ? (
        <>
          <Funil etapas={funil.etapas} />
          <Indicadores indicadores={funil.indicadores} indisponiveis={funil.indisponiveis} />
        </>
      ) : null}
    </main>
  )
}
