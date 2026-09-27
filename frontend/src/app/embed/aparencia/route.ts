import { type NextRequest, NextResponse } from 'next/server'

import { hostDoOrigin } from '@/lib/dominios'
import { buscarAparencia } from '@/lib/servidor/aparencia'

/**
 * O que o loader do site pede antes de desenhar o botao (TEC-344, D5).
 *
 * **CORS aberto a qualquer origem**: quem pede e o site da imobiliaria, que
 * nao e esta origem, e a resposta nao tem nada que nao esteja no proprio botao.
 *
 * **Fora dos dominios cadastrados, o mesmo 404 do slug errado (TEC-345, D3).**
 * O `fetch` do loader e de outra origem, entao o navegador manda `Origin`; se
 * o host dele nao esta na lista, ou o header falta, o loader nao desenha o
 * botao. E trava de EXPERIENCIA: qualquer um pede esta rota com o `Origin` que
 * quiser. A de seguranca e o `frame-ancestors` do proxy, que o navegador
 * aplica sem perguntar a ninguem. `Vary: Origin` porque a resposta depende do
 * header.
 *
 * Toda resposta leva o CORS, inclusive 404 e 503: sem ele o navegador
 * esconderia o status do loader, que so saberia que "falhou" -- o que da no
 * mesmo para ele, mas nao para quem depura pela aba de rede.
 */
const CORS = { 'Access-Control-Allow-Origin': '*' }

export async function GET(requisicao: NextRequest) {
  const tenant = requisicao.nextUrl.searchParams.get('tenant') ?? ''
  let aparencia: Awaited<ReturnType<typeof buscarAparencia>>
  try {
    aparencia = await buscarAparencia(tenant)
  } catch (erro) {
    // Sem esta linha o 503 nao diz por que. O erro vem de `buscarAparencia`
    // (status ou corpo do FastAPI, ou a rede) e nao carrega dado de visitante.
    console.error('embed/aparencia: aparencia indisponivel', erro)
    return NextResponse.json({ erro: 'indisponivel' }, { status: 503, headers: CORS })
  }
  const host = hostDoOrigin(requisicao.headers.get('origin'))
  if (!aparencia || host === null || !aparencia.dominios.includes(host)) {
    return NextResponse.json(
      { erro: 'nao_encontrado' },
      { status: 404, headers: { ...CORS, Vary: 'Origin' } },
    )
  }
  // So os tres campos do botao: os dominios nao interessam ao loader.
  const { nomeDoAssistente, corPrimaria, posicaoDoBotao } = aparencia
  return NextResponse.json({ nomeDoAssistente, corPrimaria, posicaoDoBotao }, {
    headers: { ...CORS, 'Cache-Control': 'public, max-age=60', Vary: 'Origin' },
  })
}
