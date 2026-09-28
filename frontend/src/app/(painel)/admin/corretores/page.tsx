import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { FormularioDeCorretor } from '@/components/FormularioDeCorretor'
import { ListaDeCorretores } from '@/components/ListaDeCorretores'
import { SemPermissao } from '@/components/SemPermissao'
import type { Corretor } from '@/lib/corretores'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'
import { buscarCorretores, ErroDeCorretores } from '@/lib/servidor/corretores'

export const metadata: Metadata = {
  title: 'Corretores — mobIA',
}

const ENDERECO = '/admin/corretores'

/**
 * Cadastrar, editar e desativar corretores (TEC-332).
 *
 * **A guarda e `GERIR_CORRETORES`**, a permissao que a rota do FastAPI exige
 * (`corretores.py`), e vem antes de qualquer busca -- mesmo molde de
 * `admin/titular/page.tsx` (D3 da TEC-312).
 *
 * **A listagem inicial usa `buscarCorretores` direto do servidor** (D8 do
 * desenho): so as mutacoes que o `'use client'` dispara depois de montado
 * (`FormularioDeCorretor`, `DesativarCorretor`) passam pelo `/bff/*`.
 */
export default async function PaginaDeCorretores() {
  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('GERIR_CORRETORES'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let corretores: Corretor[] | null = null
  let erro: ErroDeCorretores | null = null
  try {
    corretores = await buscarCorretores(sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR: sem resposta nao ha status
    // nem codigo para o suporte, como na fila do titular.
    erro = falha instanceof ErroDeCorretores ? falha : new ErroDeCorretores(0, 'sem resposta', null)
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
      <h1>Corretores</h1>
      <FormularioDeCorretor corretor={null} />
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar os corretores."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : null}
      {corretores && corretores.length === 0 ? (
        <p>
          <Vazio texto="Nenhum corretor cadastrado." />
        </p>
      ) : null}
      {corretores && corretores.length > 0 ? <ListaDeCorretores corretores={corretores} /> : null}
    </main>
  )
}
