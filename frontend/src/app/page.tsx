import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
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

/**
 * A URL do recorte atual, para o "tentar de novo" do `ErroDeCarga`.
 *
 * Remontada dos filtros e nao lida de `headers()`: os filtros JA sao o estado
 * da tela (a D do painel poe tudo na URL), e ler o header obrigaria a pagina a
 * ser dinamica por mais um motivo. Recarregar esta URL refaz exatamente a
 * busca que falhou -- que e o que "tentar de novo" significa aqui. Ver a D6.
 */
function urlDoRecorte(filtros: FiltrosTipo): string {
  const busca = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      busca.set(chave, valor)
    }
  }
  return `/?${busca.toString()}`
}

export default async function Pagina({ searchParams }: { searchParams: Promise<Busca> }) {
  const busca = await searchParams
  const filtros = filtrosDaUrl(busca)

  let funil: FunilTipo | null = null
  let erroDeCarga: ErroDeMetricas | null = null
  let aviso: string | null = null

  try {
    funil = await buscarFunil(filtros)
  } catch (erro) {
    // O funil NAO e renderizado quando a busca falha. Um funil de zeros e
    // indistinguivel de um periodo sem lead, e a gerente leria a queda como
    // fato do negocio -- que e a decisao mais cara que este painel existe
    // para apoiar.
    erroDeCarga = erro instanceof ErroDeMetricas ? erro : null
    aviso = erroDeCarga
      ? avisoDe(erroDeCarga)
      : 'Não foi possível carregar os dados do painel.'
  }

  // **O 422 vai para o formulario; o resto vai para o `ErroDeCarga`.** Um
  // filtro invalido e algo que a gerente corrige sozinha, ao lado do campo
  // (TEC-313, D5); um 5xx nao e problema dela, e o que ela precisa e do codigo
  // para o suporte e de um jeito de tentar de novo. Mandar os dois para o
  // mesmo lugar apagaria essa diferenca.
  //
  // A variavel guarda o ERRO e nao um booleano para que o TypeScript estreite
  // o tipo: com `ehDeFiltro: boolean`, `erroDeCarga.campos` abaixo seria
  // "possibly null" e pediria um `!` -- que e justamente o operador que
  // desliga a checagem no unico ponto onde ela protege alguma coisa.
  const erroDeFiltro = erroDeCarga?.status === 422 ? erroDeCarga : null

  return (
    <main className="painel">
      <h1>Funil de leads</h1>
      <Filtros
        atuais={filtros}
        erro={erroDeFiltro ? (aviso ?? undefined) : undefined}
        campos={erroDeFiltro ? erroDeFiltro.campos : []}
      />
      {aviso && !erroDeFiltro && (
        <ErroDeCarga
          mensagem={aviso}
          requestId={erroDeCarga?.requestId}
          urlParaTentarDeNovo={urlDoRecorte(filtros)}
        />
      )}
      {funil ? (
        <>
          <Funil etapas={funil.etapas} />
          <Indicadores indicadores={funil.indicadores} indisponiveis={funil.indisponiveis} />
        </>
      ) : null}
    </main>
  )
}
