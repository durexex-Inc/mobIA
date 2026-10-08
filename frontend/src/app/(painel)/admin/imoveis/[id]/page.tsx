import type { Metadata } from 'next'
import { notFound, redirect } from 'next/navigation'

import { EdicaoDeImovel } from '@/components/EdicaoDeImovel'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { SemPermissao } from '@/components/SemPermissao'
import { Trilha } from '@/components/ui/Trilha'
import { urlDoLogin } from '@/lib/destino'
import type { Imovel } from '@/lib/imoveis'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarImovel, ErroDeImoveis } from '@/lib/servidor/imoveis'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Editar imóvel — mobIA',
}

/**
 * Editar um imovel numa pagina propria (TEC-400), no lugar do modal da
 * TEC-398.
 *
 * **A guarda e `GERIR_CATALOGO`**, a mesma da listagem (`admin/imoveis/page.tsx`).
 *
 * **404 e 422 sao o mesmo "nao encontrado"**: um id que nao e UUID leva 422
 * do proprio FastAPI antes da rota -- o mesmo par que o portal trata junto
 * (D3 da TEC-388).
 */
export default async function PaginaDeEdicaoDeImovel({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const endereco = `/admin/imoveis/${encodeURIComponent(id)}`

  const { sessao, quem, permitido } = await exigirPermissao(endereco, (p) => p.has('GERIR_CATALOGO'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let imovel: Imovel | null = null
  let erro: ErroDeImoveis | null = null
  try {
    imovel = await buscarImovel(sessao.acesso, id)
  } catch (falha) {
    erro = falha instanceof ErroDeImoveis ? falha : new ErroDeImoveis(0, 'sem resposta', null)
  }

  // Fora do `try`: `redirect` e `notFound` lancam para interromper o render.
  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: endereco, erro: 'sessao_expirada' }))
  }
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }
  if (erro?.status === 404 || erro?.status === 422) {
    notFound()
  }

  return (
    <main className="painel">
      <Trilha
        itens={[
          { rotulo: 'Administração', href: '/admin' },
          { rotulo: 'Imóveis', href: '/admin/imoveis' },
          { rotulo: 'Editar imóvel' },
        ]}
      />
      {imovel ? (
        // Sem `key` por `atualizadoEm` de proposito: remontar depois de salvar
        // apagaria o aviso de reindexacao. `EdicaoDeImovel` adota o que salvou
        // como nova linha de base (D3 da TEC-333).
        <EdicaoDeImovel imovel={imovel} />
      ) : (
        <>
          <h1>Editar imóvel</h1>
          <ErroDeCarga
            mensagem="Não foi possível carregar o imóvel."
            requestId={erro?.requestId ?? null}
            urlParaTentarDeNovo={endereco}
          />
        </>
      )}
    </main>
  )
}
