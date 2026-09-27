import { type NextRequest, NextResponse } from 'next/server'

import { buscarAparencia } from '@/lib/servidor/aparencia'

/**
 * O que o loader do site pede antes de desenhar o botao (TEC-344, D5).
 *
 * **CORS aberto a qualquer origem**: quem pede e o site da imobiliaria, que
 * nao e esta origem, e a resposta nao tem nada que nao esteja no proprio botao.
 * A TEC-345 e quem restringe aos dominios cadastrados.
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
  } catch {
    return NextResponse.json({ erro: 'indisponivel' }, { status: 503, headers: CORS })
  }
  if (!aparencia) {
    return NextResponse.json({ erro: 'nao_encontrado' }, { status: 404, headers: CORS })
  }
  return NextResponse.json(aparencia, {
    headers: { ...CORS, 'Cache-Control': 'public, max-age=60' },
  })
}
