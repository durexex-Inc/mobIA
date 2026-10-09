import Link from 'next/link'

import { IconeDoPortal } from '@/components/IconeDoPortal'
import { contagem, reais } from '@/lib/imovel'
import { TIPOS_DE_IMOVEL, type TipoImovel } from '@/lib/imoveis'
import type { ImovelDaVitrine } from '@/lib/vitrine'

/**
 * Um imovel na vitrine do portal (visual do portal, D7). Server Component:
 * nao tem estado, e o destaque que o mapa faz ao clicar num pino e so uma
 * classe trocada pelo proprio mapa (`MapaDaVitrine`).
 *
 * **O link e um so, o do titulo**, como em `CardDeImovel`: o CSS estica a
 * area de clique dele sobre o card (`.portal-card__link::after`), e o leitor
 * de tela encontra um controle com o nome do imovel. "Ver detalhes" leva ao
 * mesmo lugar e e so visual: fica fora da tabulacao e do leitor de tela
 * (`tabIndex={-1}`, `aria-hidden`), senao cada card teria dois controles
 * para o mesmo destino e o teclado pararia duas vezes em cada um.
 *
 * `aluguel` diz qual preco veio: quem busca aluguel ve o aluguel mensal, mesmo
 * de um imovel que tambem esta a venda (`portal.py::_card_da_vitrine`).
 */
export function CardDaVitrine({ imovel, aluguel }: { imovel: ImovelDaVitrine; aluguel: boolean }) {
  const destino = `/busca/${imovel.id}`
  return (
    <article className="portal-card" id={`imovel-${imovel.id}`}>
      <div className="portal-card__foto">
        {imovel.foto ? (
          // eslint-disable-next-line @next/next/no-img-element -- mesma razao de CardDeImovel: o host nao e conhecido de antemao.
          <img src={imovel.foto} alt={`Foto de ${imovel.titulo}`} loading="lazy" />
        ) : (
          <span className="portal-card__sem-foto" aria-hidden="true">
            {imovel.bairro}
          </span>
        )}
        <span className="portal-card__selo">{TIPOS_DE_IMOVEL[imovel.tipo as TipoImovel] ?? imovel.tipo}</span>
        <p className="portal-card__preco">
          <span>{aluguel ? 'Aluguel mensal' : 'Valor de venda'}</span>
          <strong>{reais(imovel.preco)}</strong>
        </p>
      </div>
      <div className="portal-card__corpo">
        <div className="portal-card__cabecalho">
          <h2 className="portal-card__titulo">
            <Link href={destino} className="portal-card__link">
              {imovel.titulo}
            </Link>
          </h2>
          <span className="portal-selo portal-selo--codigo">Cód. {imovel.codigo}</span>
        </div>
        <p className="portal-endereco">
          <IconeDoPortal nome="pino" />
          {imovel.bairro}, {imovel.cidade} — {imovel.uf}
        </p>
        <ul className="portal-card__numeros" aria-label="Características">
          <li>
            <IconeDoPortal nome="area" />
            <strong>{imovel.areaUtilM2} m²</strong>
            <span>área útil</span>
          </li>
          <li>
            <IconeDoPortal nome="quarto" />
            <strong>{contagem(imovel.quartos, 'quarto', 'quartos')}</strong>
            {imovel.suites > 0 && <span>{contagem(imovel.suites, 'suíte', 'suítes')}</span>}
          </li>
          <li>
            <IconeDoPortal nome="banheiro" />
            <strong>{contagem(imovel.banheiros, 'banheiro', 'banheiros')}</strong>
          </li>
          <li>
            <IconeDoPortal nome="vaga" />
            <strong>{contagem(imovel.vagas, 'vaga', 'vagas')}</strong>
          </li>
        </ul>
        {imovel.caracteristicas.length > 0 && (
          <ul className="portal-card__etiquetas" aria-label="Destaques">
            {imovel.caracteristicas.map((caracteristica) => (
              <li key={caracteristica}>{caracteristica}</li>
            ))}
          </ul>
        )}
        <div className="portal-card__rodape">
          <dl className="portal-card__encargos">
            {imovel.condominio !== null && (
              <div>
                <dt>Condomínio</dt>
                <dd>{reais(imovel.condominio)}</dd>
              </div>
            )}
            {imovel.iptuMensal !== null && (
              <div>
                <dt>IPTU</dt>
                <dd>{reais(imovel.iptuMensal)}</dd>
              </div>
            )}
          </dl>
          <Link href={destino} className="portal-botao portal-botao--primario portal-card__ver" tabIndex={-1} aria-hidden="true">
            Ver detalhes
          </Link>
        </div>
      </div>
    </article>
  )
}
