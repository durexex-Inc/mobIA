import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { FormularioDeImovel } from '@/components/FormularioDeImovel'
import { ImportarImoveis } from '@/components/ImportarImoveis'
import { ListaDeImoveis } from '@/components/ListaDeImoveis'
import { SemPermissao } from '@/components/SemPermissao'
import { Trilha } from '@/components/ui/Trilha'
import type { Imovel } from '@/lib/imoveis'
import type { Importacao } from '@/lib/importacaoDeImoveis'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'
import { buscarImportacaoMaisRecente } from '@/lib/servidor/importacaoDeImoveis'
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
 *
 * **A importacao em lote (TEC-334) busca a mais recente do mesmo jeito**
 * (D4) -- `buscarImportacaoMaisRecente`, direto do servidor. Uma falha nessa
 * busca NAO derruba a pagina: ao contrario da listagem de imoveis, que e o
 * proposito central desta tela, a importacao e um extra -- `ImportarImoveis`
 * recebe `null` e a tela funciona igual, so sem a importacao mais recente
 * pre-carregada.
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

  let importacaoRecente: Importacao | null = null
  try {
    importacaoRecente = await buscarImportacaoMaisRecente(sessao.acesso)
  } catch {
    // Ver a docstring acima: a importacao e um extra, sem pagina de erro
    // propria -- `null` faz `ImportarImoveis` abrir sem nenhuma em curso.
    importacaoRecente = null
  }

  return (
    <main className="painel">
      <Trilha
        itens={[
          { rotulo: 'Administração', href: '/admin' },
          { rotulo: 'Imóveis' },
        ]}
      />
      <h1>Imóveis</h1>
      <p className="painel__descricao">
        O catálogo que o agente busca e recomenda: cadastro de unidades e importação em lote por CSV.
      </p>
      <FormularioDeImovel />
      <ImportarImoveis importacaoInicial={importacaoRecente} />
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar os imóveis."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : null}
      {imoveis ? <ListaDeImoveis imoveis={imoveis} /> : null}
    </main>
  )
}
