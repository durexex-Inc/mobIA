import { nomeDoPapel } from '@/lib/navegacao'

/**
 * A tela "Sem permissao" (TEC-312, D4, RN-FE-03.3 e 03.4).
 *
 * Aparece em tres situacoes, e nenhuma delas pode virar tela vazia: o acesso
 * direto por URL a uma area que o papel nao tem, o 403 do backend numa tela
 * que o menu mostrou, e a pagina inicial de um papel que ainda nao tem tela
 * nenhuma (o CORRETOR, ate a TEC-321).
 *
 * **Diz o papel**, porque a primeira pergunta de quem cai aqui e "entrei com a
 * conta certa?". E o link para a pagina inicial e omitido quando ja se esta
 * nela -- um link para a propria pagina so recarregaria esta tela.
 */
export function SemPermissao({
  papel,
  detalhe,
  paginaInicial,
}: {
  papel: string | null
  detalhe?: string
  paginaInicial?: string | null
}) {
  return (
    <main className="painel">
      <div role="alert" className="estado-sem-permissao">
        <h1>Sem permissão</h1>
        <p>
          {papel
            ? `Você entrou como ${nomeDoPapel(papel)}, e esse perfil não tem acesso a esta tela.`
            : 'O seu perfil não tem acesso a esta tela.'}
        </p>
        {detalhe && <p>{detalhe}</p>}
        {paginaInicial && <a href={paginaInicial}>Ir para a página inicial</a>}
      </div>
    </main>
  )
}
