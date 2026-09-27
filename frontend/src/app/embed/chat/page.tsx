import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { notFound } from 'next/navigation'

import { AvisoDePronto } from '@/components/AvisoDePronto'
import { CabecalhoDoChat } from '@/components/CabecalhoDoChat'
import { nomeExibido } from '@/lib/aparencia'
import { buscarAparencia } from '@/lib/servidor/aparencia'

export const metadata: Metadata = {
  title: 'Chat',
  robots: { index: false, follow: false },
}

/**
 * O chat que o site da imobiliaria enquadra (TEC-344, D6). Nesta card, so o
 * cabecalho; a conversa e da TEC-346 (L3).
 *
 * **A cor entra por `<style nonce>`, e nao pelo atributo `style`.** A CSP do
 * proxy nao tem `'unsafe-inline'` em `style-src` fora de desenvolvimento, e
 * atributo `style` e estilo inline -- em producao a cor sumiria sem erro. A
 * interpolacao e segura porque `buscarAparencia` so devolve cor que casa com
 * `#RRGGBB`.
 *
 * Tenant inexistente e 404, e a pagina nao manda `mobia:pronto`: o loader so
 * chega aqui depois de a aparencia responder 200, entao isto e a configuracao
 * mudando entre um pedido e outro, e o botao sumir e o desfecho certo.
 */
export default async function ChatEmbutido({ searchParams }: PageProps<'/embed/chat'>) {
  const { tenant } = await searchParams
  const aparencia = typeof tenant === 'string' ? await buscarAparencia(tenant) : null
  if (!aparencia) {
    notFound()
  }
  const nonce = (await headers()).get('x-nonce') ?? undefined

  return (
    <main className="chat-embutido">
      <style nonce={nonce}>{`.chat-embutido { --cor-primaria: ${aparencia.corPrimaria}; }`}</style>
      <CabecalhoDoChat nome={nomeExibido(aparencia)} />
      <AvisoDePronto />
    </main>
  )
}
