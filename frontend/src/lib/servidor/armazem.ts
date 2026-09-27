import 'server-only'

import { createClient } from 'redis'

/**
 * Onde a sessao do painel mora (TEC-309, D2): o Redis, atras de quatro operacoes.
 *
 * **A interface existe para os testes, e so para eles.** Com ela, `sessao.ts`
 * e as rotas de login se testam trocando este modulo por um mapa em memoria
 * (`vi.mock`), sem Redis de pe -- o mesmo contrato que a TEC-302 fixou para
 * `lib/servidor/`, de testar sem ambiente e sem rede.
 */
export type Armazem = {
  obter(chave: string): Promise<string | null>
  gravar(chave: string, valor: string, segundos: number): Promise<void>
  /**
   * Grava so se a chave nao existir, e diz se gravou (`SET NX EX`). E o lock
   * da renovacao da TEC-310 (D2): duas requisicoes renovando juntas mandariam
   * o mesmo refresh duas vezes, e o FastAPI leria a segunda como roubo.
   */
  gravarSeAusente(chave: string, valor: string, segundos: number): Promise<boolean>
  apagar(chave: string): Promise<void>
}

/**
 * Onde o Redis atende. O default e o do `docker compose` deste repo, que
 * publica o Redis na 6380 e nao na 6379.
 *
 * **E o unico segredo que o servidor Next le do ambiente** depois da TEC-309 --
 * a URL pode levar senha --, e por isso e a sentinela de
 * `scripts/verificar-bundle.mjs` (D9).
 */
function urlDoRedis(): string {
  return process.env.MOBIA_REDIS_URL ?? 'redis://localhost:6380'
}

let conexao: Promise<Armazem> | null = null

async function conectar(): Promise<Armazem> {
  const cliente = createClient({ url: urlDoRedis() })
  // Sem este ouvinte, um erro de conexao do node-redis vira `uncaughtException`
  // e derruba o processo do Next inteiro. Com ele, o erro aparece em cada
  // operacao, que e onde quem chama sabe o que fazer: a rota de login diz
  // "tente de novo" e a pagina cai na tela de erro.
  cliente.on('error', (erro: unknown) => {
    console.error('armazem.redis_erro', erro instanceof Error ? erro.message : erro)
  })
  await cliente.connect()

  return {
    obter: (chave) => cliente.get(chave),
    gravar: async (chave, valor, segundos) => {
      await cliente.set(chave, valor, { expiration: { type: 'EX', value: segundos } })
    },
    gravarSeAusente: async (chave, valor, segundos) =>
      (await cliente.set(chave, valor, {
        condition: 'NX',
        expiration: { type: 'EX', value: segundos },
      })) === 'OK',
    apagar: async (chave) => {
      await cliente.del(chave)
    },
  }
}

/**
 * O armazem do processo, conectado na primeira vez em que alguem pede.
 *
 * Uma conexao por processo, e nao uma por requisicao: abrir e fechar socket a
 * cada pagina custaria mais que a propria consulta. Uma falha ao conectar
 * ESQUECE a promessa, para que a requisicao seguinte tente de novo em vez de
 * herdar a rejeicao para sempre.
 */
export function armazem(): Promise<Armazem> {
  if (!conexao) {
    conexao = conectar().catch((erro: unknown) => {
      conexao = null
      throw erro
    })
  }
  return conexao
}
