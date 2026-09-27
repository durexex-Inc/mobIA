import { type NextRequest, NextResponse } from 'next/server'

import { chamarApi } from '@/lib/servidor/api'
import { caminhoPermitido, idDeRequisicao, origemAceita } from '@/lib/servidor/bff'
import { COOKIE_DA_SESSAO, obterSessaoValida } from '@/lib/servidor/sessao'

/**
 * O proxy `/bff/*` (TEC-302).
 *
 * Fino de proposito: le a requisicao, consulta as tres decisoes puras de
 * `lib/servidor/bff.ts` e, se passar, delega a `lib/servidor/api.ts`. Nenhuma
 * regra mora aqui -- este arquivo e o adaptador entre a `Request` do Next e
 * funcoes que se testam sem ele.
 *
 * **O primeiro consumidor de cliente chegou com a TEC-324**: o "carregar
 * anteriores" da conversa do lead. A TEC-327 trouxe as primeiras mutacoes --
 * assumir e devolver a conversa -- e o polling, a TEC-330 a revelacao de
 * telefone e e-mail, e a TEC-329 a correcao da qualificacao. Ate a TEC-324
 * ele era exercitado so por teste, e
 * de proposito -- inventar um componente de cliente so para lhe dar
 * consumidor seria inventar entidade para um criterio se auto-satisfazer. O
 * resto do painel continua sem passar por aqui: e `<form method="get">` mais
 * Server Component, o login vai a `/login/entrar` e `/login/mfa`, e o menu le
 * `/auth/me` pelo servidor (D2 da TEC-312).
 *
 * **Desde a TEC-309 ele autentica.** Sem sessao valida no Redis, responde
 * `401` e nada chega ao FastAPI; com ela, a chamada leva o JWT de quem esta
 * logado, e e o FastAPI que decide pelo papel. A checagem de `Origin` continua
 * sendo o que ela era -- defesa de CSRF, e nao autenticacao.
 */

/** Metodos que nao carregam corpo, e de que nao se deve tentar ler um. */
const SEM_CORPO: ReadonlySet<string> = new Set(['GET', 'HEAD'])

/**
 * Em TODA resposta, recusa inclusive (TEC-330, D5). O que passa por aqui e
 * dado pessoal de lead ou mutacao, e nada disso deve ficar em cache de
 * navegador nem de intermediario -- o numero revelado menos que tudo.
 */
const SEM_CACHE = 'no-store'

function recusar(status: number, motivo: string, id: string): NextResponse {
  // Corpo minimo e sem prosa: quem le isto e codigo, nao a gerente. E uma
  // mensagem detalhada num 404 de allowlist contaria a quem sonda o que existe
  // do outro lado.
  return NextResponse.json(
    { erro: motivo },
    { status, headers: { 'X-Request-Id': id, 'Cache-Control': SEM_CACHE } },
  )
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

  // A sessao e conferida DEPOIS da origem e ANTES da allowlist: quem nao esta
  // logado nao aprende pela diferenca entre 401 e 404 quais rotas existem.
  // `401`, e nao um redirecionamento ao login: quem chama o `/bff/*` e codigo
  // (`fetch`), e redirecionamento e resposta de navegacao.
  //
  // A sessao ja vem renovada se faltarem 5 minutos para o access vencer
  // (TEC-310). `503` quando o Redis ou a renovacao nao respondem: nao e falta
  // de sessao, e quem chama deve tentar de novo, e nao mandar ao login.
  let sessao: Awaited<ReturnType<typeof obterSessaoValida>>
  try {
    sessao = await obterSessaoValida(requisicao.cookies.get(COOKIE_DA_SESSAO)?.value)
  } catch {
    return recusar(503, 'sessao_indisponivel', id)
  }
  if (!sessao) {
    return recusar(401, 'sem_sessao', id)
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
      acesso: sessao.acesso,
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
  const cabecalhos = new Headers({ 'X-Request-Id': id, 'Cache-Control': SEM_CACHE })
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
