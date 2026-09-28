import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { FormularioDeConfiguracao } from '@/components/FormularioDeConfiguracao'
import { HistoricoDaConfiguracao } from '@/components/HistoricoDaConfiguracao'
import { SemPermissao } from '@/components/SemPermissao'
import type { EntradaDoHistorico } from '@/lib/configuracao'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarConfiguracao, buscarHistorico, ErroDeConfiguracao } from '@/lib/servidor/configuracao'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Configuração do agente — mobIA',
}

const ENDERECO = '/admin/configuracao'

/**
 * Ajustar nome, tom, teto de perguntas, pesos do score, cadencia de follow-up
 * e orcamento mensal, com diff de confirmacao e recuperacao de conflito de
 * versao (TEC-337).
 *
 * **A guarda e `CONFIGURAR_AGENTE`**, a permissao que `api/routes/configuracao.py`
 * exige -- mesmo molde de `admin/imoveis/page.tsx`.
 *
 * **A configuracao e a listagem inicial vem do servidor** (`buscarConfiguracao`),
 * como `buscarImoveis` -- so o `PATCH` que `FormularioDeConfiguracao` dispara
 * depois de montado passa pelo `/bff/*`.
 *
 * **O historico e um extra, como a importacao mais recente em `admin/imoveis`:**
 * uma falha nele NAO derruba a pagina -- a configuracao, que e o proposito
 * central desta tela, e o que importa. `HistoricoDaConfiguracao` recebe lista
 * vazia quando a busca falha.
 */
export default async function PaginaDeConfiguracao() {
  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('CONFIGURAR_AGENTE'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let dados: Awaited<ReturnType<typeof buscarConfiguracao>> | null = null
  let erro: ErroDeConfiguracao | null = null
  try {
    dados = await buscarConfiguracao(sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR: sem resposta nao ha status nem
    // codigo para o suporte, como na listagem de imoveis.
    erro = falha instanceof ErroDeConfiguracao ? falha : new ErroDeConfiguracao(0, 'sem resposta', null)
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

  let historico: EntradaDoHistorico[] = []
  try {
    const resultado = await buscarHistorico(sessao.acesso)
    historico = resultado.itens
  } catch {
    // Ver a docstring acima: o historico e um extra, sem pagina de erro
    // propria -- lista vazia faz `HistoricoDaConfiguracao` mostrar "nenhuma
    // alteracao registrada" em vez de derrubar a tela.
    historico = []
  }

  return (
    <main className="painel">
      <h1>Configuração do agente</h1>
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar a configuração do agente."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : null}
      {dados ? (
        <>
          {/* `key={dados.versao}`: quando o `router.refresh()` trouxer uma
              versao nova (apos salvar ou apos "Recarregar" num 409), o React
              desmonta a instancia antiga e monta outra do zero -- e assim
              que `FormularioDeConfiguracao` descarta a edicao em curso, sem
              um `useEffect` copiando prop para estado. Ver a docstring do
              componente. */}
          <FormularioDeConfiguracao
            key={dados.versao ?? 'sem-versao'}
            configuracaoInicial={dados.configuracao}
            limitesIniciais={dados.limites}
            versaoInicial={dados.versao}
          />
          <h2>Histórico de alterações</h2>
          <HistoricoDaConfiguracao itens={historico} />
        </>
      ) : null}
    </main>
  )
}
