import { REL_DE_LINK_EXTERNO, segmentosDe } from '@/lib/autolink'

/**
 * Renderiza texto de mensagem com os links autolinkados (TEC-356).
 *
 * **Sem `dangerouslySetInnerHTML`, e e esse o ponto.** O componente consome os
 * segmentos de `lib/autolink.ts` e deixa o React escapar cada trecho de texto.
 * Uma mensagem contendo `<script>` ou `javascript:alert(1)` sai como texto
 * visivel, porque nao existe caminho neste arquivo pelo qual ela vire
 * marcacao.
 *
 * **Nada o usa ainda.** A tela de transcricao e a TEC-324. Ele existe agora, em
 * vez de junto com aquela card, para que a regra de `rel` e de esquema seja uma
 * so e ja testada -- ver a D8 do desenho. Nao foi inventada nenhuma tela para
 * lhe dar consumidor: isso seria inventar entidade para um criterio se
 * auto-satisfazer, que e o que a TEC-302 recusou fazer com o `/bff/*`.
 */
export function TextoComLinks({ texto }: { texto: string }) {
  return (
    <>
      {segmentosDe(texto).map((segmento, indice) =>
        segmento.tipo === 'link' ? (
          <a
            // `key` pelo indice: a lista e derivada do texto e so muda quando o
            // texto inteiro muda, entao nao ha reordenacao a preservar.
            key={indice}
            href={segmento.href}
            rel={REL_DE_LINK_EXTERNO}
            target="_blank"
          >
            {segmento.valor}
          </a>
        ) : (
          <span key={indice}>{segmento.valor}</span>
        ),
      )}
    </>
  )
}
