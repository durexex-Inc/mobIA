import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { FormularioDeImovel } from '@/components/FormularioDeImovel'
import { ListaDeImoveis } from '@/components/ListaDeImoveis'
import { SemPermissao } from '@/components/SemPermissao'
import type { Imovel } from '@/lib/imoveis'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'
import { buscarImoveis, ErroDeImoveis } from '@/lib/servidor/imoveis'

export const metadata: Metadata = {
  title: 'Imóveis — mobIA',
}

const ENDERECO = '/admin/imoveis'

/**
 * Cadastrar, editar e retirar imoveis, com aviso de reindexacao (TEC-333).
 *
 * **A guarda e `GERIR_CATALOGO`**, a permissao que a rota do FastAPI exige
 * (`imoveis.py`), e vem antes de qualquer busca -- mesmo molde de
 * `admin/corretores/page.tsx` (TEC-332).
 *
 * **A listagem inicial usa `buscarImoveis` direto do servidor** (D7 do
 * desenho): so as mutacoes que o `'use client'` dispara depois de montado
 * (`FormularioDeImovel`, `RetirarImovel`) passam pelo `/bff/*`.
 */
export default async function PaginaDeImoveis() {
  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('GERIR_CATALOGO'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let imoveis: Imovel[] | null = null
  let erro: ErroDeImoveis | null = null
  try {
    imoveis = await buscarImoveis(sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR: sem resposta nao ha status
    // nem codigo para o suporte, como na fila do titular e em corretores.
    erro = falha instanceof ErroDeImoveis ? falha : new ErroDeImoveis(0, 'sem resposta', null)
  }

  // Fora do `try`: `redirect` lanca para interromper o render, e o `catch` o
  // engoliria.
  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: ENDERECO, erro: 'sessao_expirada' }))
  }

  // A recusa do backend vence a permissao que o painel leu (TEC-312, D4).
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  return (
    <main className="painel">
      <h1>Imóveis</h1>
      <FormularioDeImovel imovel={null} />
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar os imóveis."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : null}
      {imoveis && imoveis.length === 0 ? (
        <p>
          <Vazio texto="Nenhum imóvel cadastrado." />
        </p>
      ) : null}
      {imoveis && imoveis.length > 0 ? <ListaDeImoveis imoveis={imoveis} /> : null}
    </main>
  )
}
