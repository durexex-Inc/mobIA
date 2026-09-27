import { nomeDoPapel } from '@/lib/navegacao'

/**
 * A tela "Sem permissao" (TEC-312, D4, RN-FE-03.3 e 03.4).
 *
 * Aparece em tres situacoes, e nenhuma delas pode virar tela vazia: o acesso
 * direto por URL a uma area que o papel nao tem, o 403 do backend numa tela
 * que o menu mostrou, e a pagina inicial de um papel que nao tem tela nenhuma.
 * Ate a TEC-321 o CORRETOR caia na terceira; desde ela, o `/` o manda para a
 * lista de leads, e nenhum papel da matriz de hoje cai mais nela.
 *
 * **Diz o papel**, porque a primeira pergunta de quem cai aqui e "entrei com a
 * conta certa?". E o link para a pagina inicial e omitido quando ja se esta
 * nela -- um link para a propria pagina so recarregaria esta tela.
 */
export function SemPermissao({
  papel,
  paginaInicial,
}: {
  papel: string | null
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
        {paginaInicial && <a href={paginaInicial}>Ir para a página inicial</a>}
      </div>
    </main>
  )
}
