import type { Metadata } from 'next'
import Link from 'next/link'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { contagem, reais } from '@/lib/imovel'
import { buscarDetalheDoImovel, ErroDoPortal } from '@/lib/servidor/vitrinePublica'

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

  return (
    <main className="busca-publica busca-publica__detalhe">
      <p>
        <Link href="/busca">← Voltar para a busca</Link>
      </p>
      <h1>{detalhe.titulo}</h1>
      <p className="busca-publica__bairro">
        {detalhe.bairro}, {detalhe.cidade} - {detalhe.uf}
      </p>
      <p className="busca-publica__preco">
        {detalhe.precoVenda !== null && <span>Venda: {reais(detalhe.precoVenda)}</span>}
        {detalhe.precoAluguel !== null && <span>Aluguel: {reais(detalhe.precoAluguel)}</span>}
      </p>
      {detalhe.fotos.length === 0 ? (
        <p className="busca-publica__sem_foto" role="status">
          Este imóvel ainda não tem foto cadastrada.
        </p>
      ) : (
        <div className="busca-publica__galeria">
          {detalhe.fotos.map((foto) => (
            // eslint-disable-next-line @next/next/no-img-element -- mesma razao de CardDeImovel: o host nao e conhecido de antemao.
            <img key={foto} src={foto} alt={`Foto de ${detalhe.titulo}`} loading="lazy" />
          ))}
        </div>
      )}
      <ul className="busca-publica__dados">
        <li>{contagem(detalhe.quartos, 'quarto', 'quartos')}</li>
        <li>{contagem(detalhe.suites, 'suíte', 'suítes')}</li>
        <li>{contagem(detalhe.banheiros, 'banheiro', 'banheiros')}</li>
        <li>{contagem(detalhe.vagas, 'vaga', 'vagas')}</li>
        <li>{`${detalhe.areaUtilM2} m² de área útil`}</li>
        {detalhe.condominio !== null && <li>{`Condomínio ${reais(detalhe.condominio)}`}</li>}
        {detalhe.iptuMensal !== null && <li>{`IPTU ${reais(detalhe.iptuMensal)}`}</li>}
      </ul>
      <p className="busca-publica__descricao">{detalhe.descricao}</p>
      {detalhe.caracteristicas.length > 0 && (
        <ul className="busca-publica__caracteristicas">
          {detalhe.caracteristicas.map((caracteristica) => (
            <li key={caracteristica}>{caracteristica}</li>
          ))}
        </ul>
      )}
    </main>
  )
}
