'use client'

import { useState } from 'react'
import Link from 'next/link'

import { contagem, type ImovelCard, type Reacao, reais, textoAlternativo } from '@/lib/imovel'

// A foto tem a caixa reservada antes de carregar (RN-FE-18.4): `width` e
// `height` dao ao navegador a proporcao, e o CSS a fixa em 4:3 -- sem isso o
// card cresce quando a imagem chega e empurra a conversa.
const LARGURA_DA_FOTO = 320
const ALTURA_DA_FOTO = 240

/**
 * O card de um imovel recomendado (TEC-349). Reutilizavel de proposito: a
 * pre-visualizacao da administracao (TEC-336) desenha o mesmo componente, e
 * por isso ele recebe o imovel e, no maximo, um callback de reacao -- nada de
 * socket nem de estado da conversa.
 *
 * **Clicar abre a pagina do imovel quando ha `url`; sem `url`, expande a
 * ficha no chat** (RN-FE-18.3). No chat, o servidor sempre manda `url` nulo
 * (L1 da TEC-364), entao ali o caminho de uso real e o de expandir. Expandir
 * tira o corte de linhas do diferencial e aumenta a foto; os dados sao os
 * mesmos, porque o card fechado ja os mostra todos (RN-FE-18.1).
 *
 * **`url` interna (comecando com `/`) e externa tem comportamento diferente**
 * (TEC-388, D5). Externa (`http(s)://...`, pagina de outro site, hoje nunca
 * emitida) abre em nova aba com `target="_blank"` e o aviso oculto "(abre o
 * site em nova aba)" -- a visitante sai do mobIA. Interna (o portal publico
 * da TEC-387 linkando para o detalhe da TEC-388, `/busca/{id}`) navega na
 * mesma aba, por `next/link`, sem o aviso: e a mesma aplicacao, so outra
 * pagina dela.
 *
 * **O card inteiro e clicavel, e o controle e um so: o do titulo.** Um
 * `<button>` nao pode conter titulo, lista e paragrafos -- so conteudo de
 * frase --, entao o botao (ou o link) fica no titulo e o CSS estica a area de
 * clique dele por cima do card (`.card-imovel__acao::after`). O leitor de tela
 * encontra um controle com o nome do imovel, e nao um botao com o card
 * inteiro lido como rotulo.
 *
 * **Sem foto, um placeholder neutro com o bairro** (RN-FE-18.2). Ele e
 * decorativo para leitor de tela (`aria-hidden`): o bairro ja esta no texto do
 * card logo abaixo, e ler duas vezes nao ajuda ninguem.
 *
 * **"Gostei" e "Não é pra mim" so aparecem com `aoReagir`** (TEC-350, D3). A
 * pre-visualizacao nao o passa e continua sem botao. `reacao` e a que a
 * visitante ja escolheu: com ela, os dois botoes ficam desabilitados e o
 * escolhido, marcado (D2). `bloqueado` os desabilita sem marcar nada -- a
 * espera de `muitas_tentativas`. Os botoes ficam num rodape acima da area de
 * clique esticada do titulo, senao o toque neles expandiria a ficha.
 */
export function CardDeImovel({
  imovel,
  aoReagir,
  reacao = null,
  bloqueado = false,
}: {
  imovel: ImovelCard
  aoReagir?: (reacao: Reacao) => void
  reacao?: Reacao | null
  bloqueado?: boolean
}) {
  const [expandido, setExpandido] = useState(false)

  return (
    <article className={`card-imovel${expandido ? ' card-imovel--expandido' : ''}`}>
      {imovel.foto ? (
        // `<img>` e nao `next/image`: a foto vem do catalogo de cada
        // imobiliaria, de host qualquer, e `next/image` exige declarar os hosts
        // remotos em `next.config.ts` -- ou passaria a otimizar, pelo servidor
        // do chat, imagem de origem arbitraria. `loading="lazy"` e as dimensoes
        // reservadas sao o que a card pede, e o `<img>` os da sozinho.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="card-imovel__foto"
          src={imovel.foto}
          alt={textoAlternativo(imovel)}
          loading="lazy"
          width={LARGURA_DA_FOTO}
          height={ALTURA_DA_FOTO}
        />
      ) : (
        <div className="card-imovel__foto card-imovel__foto--vazia" aria-hidden="true">
          <span>{imovel.bairro}</span>
        </div>
      )}
      <h3 className="card-imovel__titulo">
        {imovel.url?.startsWith('/') ? (
          <Link className="card-imovel__acao" href={imovel.url}>
            {imovel.titulo}
          </Link>
        ) : imovel.url ? (
          <a className="card-imovel__acao" href={imovel.url} target="_blank" rel="noopener noreferrer">
            {imovel.titulo}
            <span className="card-imovel__oculto"> (abre o site em nova aba)</span>
          </a>
        ) : (
          <button
            type="button"
            className="card-imovel__acao"
            aria-expanded={expandido}
            onClick={() => setExpandido((valor) => !valor)}
          >
            {imovel.titulo}
          </button>
        )}
      </h3>
      <p className="card-imovel__bairro">{imovel.bairro}</p>
      <p className="card-imovel__preco">{reais(imovel.precoCentavos)}</p>
      <ul className="card-imovel__dados">
        <li>{contagem(imovel.quartos, 'quarto', 'quartos')}</li>
        <li>{contagem(imovel.vagas, 'vaga', 'vagas')}</li>
        <li>{`${imovel.areaUtilM2} m² de área útil`}</li>
        {imovel.condominioCentavos !== null ? (
          <li>{`Condomínio ${reais(imovel.condominioCentavos)}`}</li>
        ) : null}
      </ul>
      {imovel.diferencial ? <p className="card-imovel__diferencial">{imovel.diferencial}</p> : null}
      {aoReagir ? (
        <div className="card-imovel__reacoes" role="group" aria-label={`Reagir a ${imovel.titulo}`}>
          {(
            [
              ['gostei', 'Gostei'],
              ['nao_e_pra_mim', 'Não é pra mim'],
            ] as const
          ).map(([valor, rotulo]) => (
            <button
              key={valor}
              type="button"
              aria-pressed={reacao === valor}
              disabled={reacao !== null || bloqueado}
              onClick={() => aoReagir(valor)}
            >
              {rotulo}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  )
}
