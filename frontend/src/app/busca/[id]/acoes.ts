'use server'

import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'

/**
 * O resultado de `solicitarInteresseAction`, para `useActionState` (TEC-389).
 *
 * `erro` carrega so a mensagem que o FastAPI devolveu -- 404 (imovel ficou
 * indisponivel entre a visualizacao e o envio, CA-03), 422 (telefone
 * invalido, CA-02) e 429 (rate limit por telefone) viram o MESMO tratamento
 * aqui: mostrar a mensagem do backend, sem a pagina precisar decidir o que
 * cada status significa -- `detalheDe` ja sabe ler os dois formatos de
 * `detail` que o FastAPI produz (string e lista de erro de validacao).
 */
export type EstadoDoInteresse = { status: 'inicial' } | { status: 'sucesso' } | { status: 'erro'; mensagem: string }

/**
 * Server Action (TEC-389): a primeira mutacao do portal publico, sem sessao
 * nenhuma -- por isso nao passa pelo proxy `/bff/*` (aquele exige login,
 * D1/TEC-309) nem pode ser `fetch` direto do navegador (`chamarApi` e
 * `server-only`, e o endereco do FastAPI nao e para o navegador conhecer).
 * A Server Action roda no servidor do Next como qualquer Server Component,
 * so que disparada por um formulario de um Client Component.
 *
 * `imovelId` vem de `.bind(null, imovelId)` no componente -- o padrao do
 * Next para Server Action com argumento fixo alem do `FormData` (ver
 * `FormularioDeInteresse.tsx`).
 */
export async function solicitarInteresseAction(
  imovelId: string,
  _estadoAnterior: EstadoDoInteresse,
  dados: FormData,
): Promise<EstadoDoInteresse> {
  const telefone = String(dados.get('telefone') ?? '').trim()
  const nome = String(dados.get('nome') ?? '').trim()
  const email = String(dados.get('email') ?? '').trim()

  const corpo: Record<string, string> = { telefone }
  if (nome) {
    corpo.nome = nome
  }
  if (email) {
    corpo.email = email
  }

  const resposta = await chamarApi(`/portal/imoveis/${encodeURIComponent(imovelId)}/interesse`, {
    metodo: 'POST',
    corpo: JSON.stringify(corpo),
    tipoDoCorpo: 'application/json',
  })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    return { status: 'erro', mensagem }
  }
  return { status: 'sucesso' }
}
