/**
 * A falha de carga: mensagem, codigo para o suporte e "tentar de novo"
 * (TEC-313, RN-FE-04.3).
 *
 * **"Tentar de novo" e um link, nao um botao.** Este componente e Server
 * Component, e o painel so tem JS de cliente onde nao ha alternativa -- o
 * aviso de inatividade da TEC-311; a TEC-302 registra que isso e deliberado. Um botao
 * exigiria `'use client'` e hidratacao para fazer o que um `<a>` para a URL
 * atual ja faz: recarregar a rota e refazer a busca. De quebra, funciona sem
 * JS e e navegavel por teclado de graca. Ver a D6 do desenho.
 *
 * **O `requestId` e OPCIONAL, e a ausencia dele nao vira texto.** Ele vem do
 * header `X-Request-Id` da RESPOSTA -- o id que o FastAPI gera desde a TEC-368
 * -- e portanto so existe se a requisicao chegou la. Um 502 de proxy nao tem
 * nenhum. Mostrar "desconhecido" ou um id inventado mandaria alguem procurar
 * no log uma linha que nao existe, entao o campo simplesmente some. Ver a D3.
 */
export function ErroDeCarga({
  mensagem,
  requestId,
  urlParaTentarDeNovo,
}: {
  mensagem: string
  requestId?: string | null
  urlParaTentarDeNovo: string
}) {
  return (
    <div role="alert" className="estado-erro">
      <p className="estado-erro-mensagem">{mensagem}</p>
      {requestId && (
        <p className="estado-erro-codigo">
          Código para o suporte:{' '}
          {/* `<code>` e nao texto solto: o id e para ser selecionado e colado,
              e a fonte monoespacada e o que torna `0`/`O` e `1`/`l`
              distinguiveis por quem le em voz alta no telefone. */}
          <code>{requestId}</code>
        </p>
      )}
      <a className="estado-erro-acao" href={urlParaTentarDeNovo}>
        Tentar de novo
      </a>
    </div>
  )
}
