import { NextResponse } from 'next/server'

import { chamarApi } from '@/lib/servidor/api'

/**
 * A foto publica de um imovel, servida pela origem do proprio Next (TEC-403).
 *
 * O FastAPI devolve as fotos do portal como caminho RELATIVO dele
 * (`/portal/imoveis/{id}/fotos/{fotoId}`, `portal.py::_fotos_publicas`), e o
 * `<img>` do detalhe e da vitrine usa esse caminho como veio. So que a pagina
 * e servida pelo Next, e nao pela API -- em producao sao hosts diferentes --,
 * entao o navegador pede a foto AQUI. Este handler existe no mesmo caminho para
 * que o relativo do backend funcione sem traducao nenhuma no front.
 *
 * Repassar, e nao apontar o `<img>` direto para a API: a CSP do portal e
 * `img-src 'self'` (`proxy.ts`), e abri-la para o host da API seria afrouxar a
 * politica para resolver o que um handler de mesma origem resolve.
 *
 * **Sem `acesso`**: a rota do FastAPI e publica, e quem decide se a foto pode
 * ser vista (imovel `DISPONIVEL`) e ela, nao este handler. O 404 dela passa
 * como 404.
 */

/** Os dois ids sao UUID no FastAPI; fora disso nao ha o que pedir a ele. */
const FORMA_DO_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export async function GET(
  _requisicao: Request,
  { params }: { params: Promise<{ id: string; fotoId: string }> },
) {
  const { id, fotoId } = await params
  // Antes de montar a URL: um `..` num segmento seria normalizado por `new URL`
  // e mandaria o pedido para outra rota do FastAPI.
  if (!FORMA_DO_UUID.test(id) || !FORMA_DO_UUID.test(fotoId)) {
    return new NextResponse(null, { status: 404 })
  }

  let resposta: Response
  try {
    resposta = await chamarApi(`/portal/imoveis/${id}/fotos/${fotoId}`, {})
  } catch (erro) {
    console.error('portal/foto: FastAPI inacessivel', erro)
    return new NextResponse(null, { status: 502 })
  }
  if (!resposta.ok) {
    return new NextResponse(null, { status: resposta.status })
  }
  return new NextResponse(resposta.body, {
    status: 200,
    headers: { 'Content-Type': resposta.headers.get('content-type') ?? 'application/octet-stream' },
  })
}
