import type { Metadata } from 'next'
import Link from 'next/link'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { FormularioDeInteresse } from '@/components/FormularioDeInteresse'
import { GaleriaDoImovel } from '@/components/GaleriaDoImovel'
import { IconeDoPortal } from '@/components/IconeDoPortal'
import { contagem, reais } from '@/lib/imovel'
import { TIPOS_DE_IMOVEL, type TipoImovel } from '@/lib/imoveis'
import { mapaEmbutido, mapaGrande } from '@/lib/mapa'
import { buscarDetalheDoImovel, ErroDoPortal } from '@/lib/servidor/vitrinePublica'

// "Ambos" e o vocabulario da administracao (`lib/imoveis.ts::OPERACOES`); para
// quem visita, o que importa e que o imovel esta a venda E para alugar.
const OPERACAO_NO_PORTAL: Record<string, string> = {
  VENDA: 'Venda',
  ALUGUEL: 'Locação',
  AMBOS: 'Venda e locação',
}

export const metadata: Metadata = {
  title: 'Detalhe do imóvel',
  description: 'Fotos, descrição e características completas do imóvel.',
}

/**
 * O detalhe publico de um imovel (TEC-388): fotos, descricao e
 * caracteristicas completas, aberto a partir de `/busca` (TEC-387).
 *
 * **404 e 422 viram a mesma tela** ("Imóvel não encontrado"), no molde de
 * `leads/[leadId]/page.tsx`: 422 e o `id` que nao e UUID valido -- o FastAPI
 * recusa o caminho antes de procurar, e para quem digitou o endereco errado
 * e o mesmo que o imovel nao existir. A mesma tela tambem cobre o imovel que
 * existe mas nao esta `DISPONIVEL` (D3 do desenho): o backend ja devolve o
 * mesmo 404 para os dois casos, entao a pagina nao precisa (nem consegue)
 * distinguir "nunca existiu" de "nao esta mais a venda".
 *
 * **`Promise.allSettled`, e nao `try/catch` em volta do `await`** -- mesmo
 * padrao de `leads/[leadId]/page.tsx`. Com uma unica chamada isso parece
 * supersticao, mas nao e: o `.then` que o `await` anexa a promessa de
 * `buscarDetalheDoImovel` passa por uma volta a mais de microtask (o
 * `Promise.resolve(...).then(...)` que o runtime insere ao normalizar o
 * retorno de uma funcao async), e o Node pode marcar a rejeicao como "sem
 * tratamento" ANTES dessa volta acontecer -- mesmo o `catch` process TRATANDO
 * o erro depois, correto. `Promise.allSettled` anexa o handler no mesmo
 * tick em que a chamada e feita, e nao sofre disso.
 */
export default async function DetalheDoImovel({ params }: PageProps<'/busca/[id]'>) {
  const { id } = await params

  const [resultado] = await Promise.allSettled([buscarDetalheDoImovel(id)])
  if (resultado.status === 'rejected') {
    const erro = resultado.reason
    if (erro instanceof ErroDoPortal && (erro.status === 404 || erro.status === 422)) {
      return (
        <main className="busca-publica">
          <div role="alert" className="busca-publica__nao_encontrado">
            <h1>Imóvel não encontrado</h1>
            <p>Este imóvel não está mais disponível.</p>
            <Link href="/busca">Voltar para a busca</Link>
          </div>
        </main>
      )
    }
    return (
      <main className="busca-publica">
        <p>
          <Link href="/busca">← Voltar para a busca</Link>
        </p>
        <ErroDeCarga
          mensagem="Não foi possível carregar o imóvel."
          requestId={erro instanceof ErroDoPortal ? erro.requestId : null}
          urlParaTentarDeNovo={`/busca/${encodeURIComponent(id)}`}
        />
      </main>
    )
  }
  const detalhe = resultado.value
  const coordenada =
    detalhe.latitude !== null && detalhe.longitude !== null
      ? { latitude: detalhe.latitude, longitude: detalhe.longitude }
      : null

  return (
    <main className="portal">
      <header className="portal-topo">
        <Link href="/busca" className="portal-topo__voltar" aria-label="Voltar para a busca">
          <IconeDoPortal nome="voltar" />
        </Link>
        <span className="portal-topo__titulo">Detalhes do imóvel</span>
      </header>

      <div className="portal-corpo">
        <div className="portal-principal">
          {detalhe.fotos.length === 0 ? (
            <p className="portal-galeria portal-galeria--vazia" role="status">
              Este imóvel ainda não tem foto cadastrada.
            </p>
          ) : (
            <GaleriaDoImovel fotos={detalhe.fotos} titulo={detalhe.titulo} />
          )}

          <section className="portal-apresentacao" aria-labelledby="titulo-do-imovel">
            <ul className="portal-selos">
              <li className="portal-selo portal-selo--operacao">{OPERACAO_NO_PORTAL[detalhe.operacao] ?? detalhe.operacao}</li>
              <li className="portal-selo portal-selo--tipo">
                {TIPOS_DE_IMOVEL[detalhe.tipo as TipoImovel] ?? detalhe.tipo}
              </li>
              <li className="portal-selo portal-selo--codigo">Cód. {detalhe.codigo}</li>
            </ul>
            <h1 id="titulo-do-imovel" className="portal-titulo">
              {detalhe.titulo}
            </h1>
            <p className="portal-endereco">
              <IconeDoPortal nome="pino" />
              {detalhe.bairro}, {detalhe.cidade} — {detalhe.uf}
            </p>
          </section>

          <section className="portal-cartao portal-precos" aria-label="Valores">
            <dl className="portal-precos__principais">
              {detalhe.precoVenda !== null && (
                <div>
                  <dt>Valor de venda</dt>
                  <dd className="portal-precos__valor">{reais(detalhe.precoVenda)}</dd>
                </div>
              )}
              {detalhe.precoAluguel !== null && (
                <div>
                  <dt>Locação mensal</dt>
                  <dd className="portal-precos__valor">
                    {reais(detalhe.precoAluguel)}
                    <span className="portal-precos__periodo">/mês</span>
                  </dd>
                </div>
              )}
            </dl>
            {(detalhe.condominio !== null || detalhe.iptuMensal !== null) && (
              <dl className="portal-precos__encargos">
                {detalhe.condominio !== null && (
                  <div>
                    <dt>Condomínio</dt>
                    <dd>
                      {reais(detalhe.condominio)}
                      <span className="portal-precos__periodo">/mês</span>
                    </dd>
                  </div>
                )}
                {detalhe.iptuMensal !== null && (
                  <div>
                    <dt>IPTU</dt>
                    <dd>
                      {reais(detalhe.iptuMensal)}
                      <span className="portal-precos__periodo">/mês</span>
                    </dd>
                  </div>
                )}
              </dl>
            )}
          </section>

          <ul className="portal-numeros" aria-label="Características">
            <li>
              <IconeDoPortal nome="area" />
              <strong>{detalhe.areaUtilM2} m²</strong>
              <span>área útil</span>
            </li>
            <li>
              <IconeDoPortal nome="quarto" />
              <strong>{detalhe.quartos}</strong>
              <span>{detalhe.quartos === 1 ? 'quarto' : 'quartos'}</span>
              {detalhe.suites > 0 && <span>{contagem(detalhe.suites, 'suíte', 'suítes')}</span>}
            </li>
            <li>
              <IconeDoPortal nome="banheiro" />
              <strong>{detalhe.banheiros}</strong>
              <span>{detalhe.banheiros === 1 ? 'banheiro' : 'banheiros'}</span>
            </li>
            <li>
              <IconeDoPortal nome="vaga" />
              <strong>{detalhe.vagas}</strong>
              <span>{detalhe.vagas === 1 ? 'vaga' : 'vagas'}</span>
            </li>
          </ul>

          <section className="portal-cartao" aria-labelledby="sobre-o-imovel">
            <h2 id="sobre-o-imovel" className="portal-subtitulo">
              Sobre o imóvel
            </h2>
            <p className="portal-descricao">{detalhe.descricao}</p>
          </section>

          {detalhe.caracteristicas.length > 0 && (
            <section className="portal-cartao" aria-labelledby="comodidades">
              <h2 id="comodidades" className="portal-subtitulo">
                Comodidades e diferenciais
              </h2>
              <ul className="portal-comodidades">
                {detalhe.caracteristicas.map((caracteristica) => (
                  <li key={caracteristica}>
                    <span className="portal-comodidades__nome">{caracteristica}</span>
                    <IconeDoPortal nome="confere" />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {coordenada && (
            <section className="portal-cartao" aria-labelledby="localizacao">
              <h2 id="localizacao" className="portal-subtitulo">
                Localização
              </h2>
              <p className="portal-nota">A posição no mapa é aproximada, para indicar a vizinhança.</p>
              <iframe
                className="portal-mapa"
                title={`Mapa de ${detalhe.bairro}, ${detalhe.cidade}`}
                src={mapaEmbutido(coordenada.latitude, coordenada.longitude)}
                loading="lazy"
                referrerPolicy="no-referrer"
              />
              <a
                className="portal-link"
                href={mapaGrande(coordenada.latitude, coordenada.longitude)}
                target="_blank"
                rel="noopener noreferrer"
              >
                Abrir o mapa em tela cheia
              </a>
            </section>
          )}
        </div>

        <aside className="portal-lateral" id="interesse">
          <FormularioDeInteresse imovelId={detalhe.id} />
        </aside>
      </div>

      <nav className="portal-barra" aria-label="Contato">
        <a href="#interesse" className="portal-botao portal-botao--primario">
          Tenho interesse
        </a>
      </nav>
    </main>
  )
}
