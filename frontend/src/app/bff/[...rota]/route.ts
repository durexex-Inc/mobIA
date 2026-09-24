import { type NextRequest, NextResponse } from 'next/server'

import { chamarApi } from '@/lib/servidor/api'
import { caminhoPermitido, idDeRequisicao, origemAceita } from '@/lib/servidor/bff'

/**
 * O proxy `/bff/*` (TEC-302).
 *
 * Fino de proposito: le a requisicao, consulta as tres decisoes puras de
 * `lib/servidor/bff.ts` e, se passar, delega a `lib/servidor/api.ts`. Nenhuma
 * regra mora aqui -- este arquivo e o adaptador entre a `Request` do Next e
 * funcoes que se testam sem ele.
 *
 * **Ele nao tem consumidor de cliente nesta card, e isso e esperado.** O painel
 * e `<form method="get">` mais Server Component: nenhuma linha de codigo de
 * cliente chama `/bff/*`. O proxy e a fundacao que a card diz destravar -- o
 * login (TEC-309) e a navegacao por papel (TEC-312) -- e nasce exercitado por
 * teste, nao pelo painel. Inventar um componente de cliente so para lhe dar
 * consumidor seria inventar entidade para um criterio se auto-satisfazer.
 *
 * **Ele tambem nao autentica ninguem.** A checagem de `Origin` e defesa de
 * CSRF: vale porque quem escreve aquele header e o navegador. Ver a L1 do
 * desenho.
 */

/** Metodos que nao carregam corpo, e de que nao se deve tentar ler um. */
const SEM_CORPO: ReadonlySet<string> = new Set(['GET', 'HEAD'])

function recusar(status: number, motivo: string, id: string): NextResponse {
  // Corpo minimo e sem prosa: quem le isto e codigo, nao a gerente. E uma
  // mensagem detalhada num 404 de allowlist contaria a quem sonda o que existe
  // do outro lado.
  return NextResponse.json({ erro: motivo }, { status, headers: { 'X-Request-Id': id } })
}

async function repassar(
  requisicao: NextRequest,
  contexto: RouteContext<'/bff/[...rota]'>,
): Promise<NextResponse> {
  const { rota } = await contexto.params
  const metodo = requisicao.method.toUpperCase()
  const id = idDeRequisicao(requisicao.headers.get('x-request-id'))

  // `MOBIA_ORIGEM_DO_PAINEL` ganha da origem da requisicao porque atras de
  // proxy o `Host` que o Next ve pode ser `localhost:3000` enquanto o navegador
  // manda o dominio publico -- e ai a comparacao recusaria toda mutacao
  // legitima. Sem proxy nao ha o que configurar: a origem da requisicao e o
  // valor certo.
  const propriaOrigem = process.env.MOBIA_ORIGEM_DO_PAINEL ?? requisicao.nextUrl.origin

  // A origem e checada ANTES da allowlist: e a checagem mais barata, e quem vem
  // de origem estrangeira nao deve aprender pela diferenca de status quais
  // rotas existem aqui.
  if (!origemAceita({ origem: requisicao.headers.get('origin'), propriaOrigem, metodo })) {
    return recusar(403, 'origem_nao_permitida', id)
  }

  const caminho = caminhoPermitido(metodo, rota)
  if (caminho === null) {
    // 404 e nao 403: 403 afirma "existe e voce nao pode", 404 afirma "aqui nao
    // ha essa rota" -- que e a verdade, e que nao confirma a quem sonda quais
    // rotas o FastAPI tem.
    return recusar(404, 'rota_nao_permitida', id)
  }

  let resposta: Response
  try {
    resposta = await chamarApi(caminho, {
      metodo,
      busca: requisicao.nextUrl.searchParams,
      corpo: SEM_CORPO.has(metodo) ? null : await requisicao.arrayBuffer(),
      tipoDoCorpo: requisicao.headers.get('content-type'),
      idDeRequisicao: id,
    })
  } catch {
    // Sem detalhe da excecao no corpo: o texto de um erro de rede nomeia host e
    // porta internos, e quem o recebe aqui e o navegador.
    return recusar(502, 'api_inacessivel', id)
  }

  // So o `Content-Type` e repassado. Copiar os cabecalhos de resposta em bloco
  // relaiaria o que o FastAPI decidir mandar um dia -- `Set-Cookie` inclusive --
  // para um dominio que nao e o dele.
  const cabecalhos = new Headers({ 'X-Request-Id': id })
  const tipo = resposta.headers.get('content-type')
  if (tipo) {
    cabecalhos.set('Content-Type', tipo)
  }

  return new NextResponse(resposta.body, { status: resposta.status, headers: cabecalhos })
}

/**
 * Os seis metodos sao exportados, e o `POST` nao e enfeite.
 *
 * Metodo nao exportado faz o Next responder 405 sozinho, ANTES deste arquivo
 * rodar -- e ai uma mutacao vinda de outra origem levaria 405, nao o 403 que o
 * cenario 2 do Gherkin da card exige. Exportar e o que traz a recusa para
 * dentro das nossas regras.
 */
export const GET = repassar
export const HEAD = repassar
export const POST = repassar
export const PUT = repassar
export const PATCH = repassar
export const DELETE = repassar
