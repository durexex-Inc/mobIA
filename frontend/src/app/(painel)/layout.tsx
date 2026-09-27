import { AvisoDeInatividade } from '@/components/AvisoDeInatividade'
import { Menu } from '@/components/Menu'
import { quemSouDaRequisicao } from '@/lib/servidor/quemSou'

/**
 * O layout das telas do painel: o menu por papel em cima (TEC-312).
 *
 * **Nao e a guarda.** Ele busca quem esta logado so para desenhar o menu; se
 * nao houver ninguem, desenha a pagina sem menu, e a pagina redireciona ao
 * login. Quem decide se uma tela abre e a propria tela, com `exigirPermissao`
 * -- ver a D3 do desenho, e a secao "Layouts and auth checks" do guia de
 * autenticacao do Next 16, que explica por que um layout nao consegue impedir
 * a pagina filha de rodar.
 *
 * `(painel)` e grupo de rota: nao entra na URL. Existe para o login, que fica
 * de fora, nao herdar menu nem o `loading.tsx` do funil (D7).
 */
export default async function LayoutDoPainel({ children }: LayoutProps<'/'>) {
  const quem = await quemSouDaRequisicao()
  return (
    <>
      {quem && <Menu quem={quem} />}
      {/* So para quem esta logado: sem sessao nao ha o que encerrar
          (TEC-311). E o unico componente de cliente do painel. */}
      {quem && <AvisoDeInatividade />}
      {children}
    </>
  )
}
