import type { Metadata } from 'next'
import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { destinoSeguro, type MotivoDoLogin, urlDoLogin } from '@/lib/destino'
import { COOKIE_DA_SESSAO, obterSessaoValida } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Entrar — mobIA',
}

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

/**
 * O que a tela diz para cada motivo (TEC-309).
 *
 * **Credencial errada tem uma mensagem so, para e-mail e senha.** O FastAPI
 * responde igual aos dois de proposito -- distingui-los contaria a quem sonda
 * que o e-mail existe --, e a tela nao desfaz isso.
 *
 * O `mfa_obrigatorio` e o quarto cenario do Gherkin da card: "a mensagem
 * explica que administradores precisam de MFA". Ele diz tambem o que fazer,
 * porque quem le isso nao tem como resolver sozinho.
 */
const MENSAGENS: Record<MotivoDoLogin, string> = {
  credencial: 'E-mail ou senha incorretos.',
  mfa_obrigatorio:
    'Administradores só entram com a verificação em duas etapas configurada, e ela não está configurada na sua conta. Peça a quem administra o sistema para configurá-la.',
  codigo:
    'Código inválido ou expirado. Confira o código atual no aplicativo autenticador e tente de novo.',
  expirado: 'A verificação expirou. Entre com e-mail e senha de novo.',
  muitas_tentativas: 'Muitas tentativas em pouco tempo. Espere um minuto e tente de novo.',
  indisponivel: 'Não foi possível entrar agora. Tente de novo em instantes.',
  sessao_expirada: 'Sua sessão expirou. Entre de novo para continuar.',
  // TEC-311, D5: distinto de `sessao_expirada` porque quem estava lendo e foi
  // derrubado precisa saber que foi o tempo, e nao um erro.
  inatividade: 'Sua sessão foi encerrada depois de 30 minutos sem uso. Entre de novo para continuar.',
}

function mensagemDe(bruto: string | undefined): string | null {
  return bruto && bruto in MENSAGENS ? MENSAGENS[bruto as MotivoDoLogin] : null
}

/**
 * A tela de login, nas duas etapas: e-mail e senha, e o codigo TOTP de quem e
 * ADMIN.
 *
 * **Sem JavaScript de cliente.** Os dois formularios sao `method="post"` para
 * Route Handlers (`/login/entrar` e `/login/mfa`), que respondem com `303`. A
 * D4 do desenho diz por que nao sao Server Actions.
 *
 * O `returnTo` e filtrado AQUI, antes de ir para o campo escondido: a rota de
 * POST filtra de novo na chegada, e as duas checagens sao a mesma funcao.
 */
export default async function PaginaDeLogin({ searchParams }: { searchParams: Promise<Busca> }) {
  const busca = await searchParams
  const destino = destinoSeguro(um(busca.returnTo))

  // Quem ja tem sessao valida nao tem o que fazer aqui. `obterSessaoValida`, e
  // nao so ler o Redis: uma sessao ociosa (TEC-311) ou de refresh revogado
  // (TEC-310) ainda esta la, e mandar a pessoa ao painel so a faria voltar.
  // Falha ao renovar conta como "sem sessao" -- a tela de login e o lugar de
  // tentar de novo.
  const sessao = await obterSessaoValida((await cookies()).get(COOKIE_DA_SESSAO)?.value).catch(
    () => null,
  )
  if (sessao) {
    redirect(destino)
  }

  const etapaDoCodigo = um(busca.etapa) === 'mfa'
  const mensagem = mensagemDe(um(busca.erro))

  return (
    <main className="login">
      <h1>Entrar no painel</h1>

      {mensagem && (
        <p className="login-erro" role="alert">
          {mensagem}
        </p>
      )}

      {etapaDoCodigo ? (
        <form method="post" action="/login/mfa" className="login-formulario">
          <input type="hidden" name="returnTo" value={destino} />
          <p>Digite o código de 6 dígitos do seu aplicativo autenticador.</p>
          <label>
            Código
            <input
              name="codigo"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              autoComplete="one-time-code"
              required
              autoFocus
            />
          </label>
          <button type="submit">Confirmar</button>
          <a href={urlDoLogin({ returnTo: destino })}>Voltar e entrar com outra conta</a>
        </form>
      ) : (
        <form method="post" action="/login/entrar" className="login-formulario">
          <input type="hidden" name="returnTo" value={destino} />
          <label>
            E-mail
            <input name="email" type="email" autoComplete="username" required autoFocus />
          </label>
          <label>
            Senha
            <input name="senha" type="password" autoComplete="current-password" required />
          </label>
          <button type="submit">Entrar</button>
        </form>
      )}
    </main>
  )
}
