import { urlSegura } from '@/lib/imovel'

/**
 * O aviso de privacidade e o contato do encarregado que a faixa do chat
 * mostra (TEC-352, D1). Vem da aparencia, que o FastAPI serve a partir de
 * `AVISO_DE_PRIVACIDADE_URL` e `ENCARREGADO_EMAIL`.
 */
export type Privacidade = { avisoUrl: string; encarregadoEmail: string }

// A mesma forma que `_FORMATO_DO_EMAIL` confere no backend (`app/config.py`).
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/**
 * Os dois campos do corpo da aparencia, ou `null` se falta qualquer um --
 * e `null` fecha o chat (D2): sem o aviso, nenhum dado e coletado. O endereco
 * passa por `urlSegura`, porque vira `href`; o backend ja recusa subir com
 * outro esquema, e esta checagem e o que garante que nunca chega um.
 */
export function lerPrivacidade(corpo: unknown): Privacidade | null {
  if (typeof corpo !== 'object' || corpo === null) {
    return null
  }
  const { avisoDePrivacidadeUrl, encarregadoEmail } = corpo as Record<string, unknown>
  const avisoUrl = urlSegura(avisoDePrivacidadeUrl)
  if (!avisoUrl || typeof encarregadoEmail !== 'string' || !EMAIL.test(encarregadoEmail)) {
    return null
  }
  return { avisoUrl, encarregadoEmail }
}
