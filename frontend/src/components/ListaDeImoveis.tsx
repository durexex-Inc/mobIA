import { type Imovel, STATUS_DO_IMOVEL, TIPOS_DE_IMOVEL, urlDaListaDeImoveis } from '@/lib/imoveis'
import Link from 'next/link'

import { IrParaCadastroDeImovel } from '@/components/FormularioDeImovel'
import { RetirarImovel } from '@/components/RetirarImovel'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'

/**
 * A lista de imoveis, de todo status junto (D6 do desenho da TEC-333), com o
 * estado vazio dentro do cartao (TEC-398).
 *
 * **O status e TEXTO**, nunca so cor -- mesmo padrao do rotulo de "Inativo"
 * em `ListaDeCorretores.tsx`. Editar leva a pagina do imovel
 * (`admin/imoveis/[id]`, TEC-400); retirar so aparece em linha que nao esta `INATIVO`, porque nao
 * ha reativar por botao dedicado (D4) -- reativar e editar o Status.
 *
 * **"Carregar mais" e um link para `paginas + 1`** (TEC-401): quem busca as
 * paginas e o Server Component, e a tela so diz quantos imoveis estao
 * carregados -- a API nao devolve total (D4).
 */
export function ListaDeImoveis({
  imoveis,
  paginas = 1,
  haMais = false,
}: {
  imoveis: Imovel[]
  paginas?: number
  haMais?: boolean
}) {
  return (
    <section aria-labelledby="imoveis-cadastrados" className="secao">
      <div className="secao__cabecalho">
        <h2 id="imoveis-cadastrados">Imóveis cadastrados</h2>
        <p className="secao__total">
          {imoveis.length} {imoveis.length === 1 ? 'imóvel carregado' : 'imóveis carregados'}
        </p>
      </div>
      <Cartao>
        {imoveis.length === 0 ? (
          <div className="estado-vazio-do-painel">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              width="22"
              height="22"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V21h14V9.5" />
              <path d="M10 21v-6h4v6" />
            </svg>
            <p className="estado-vazio-do-painel__titulo">Nenhum imóvel cadastrado.</p>
            <p>Cadastre o primeiro imóvel acima ou importe uma planilha CSV com o catálogo inteiro.</p>
            <IrParaCadastroDeImovel />
          </div>
        ) : (
          <div className="corretores__rolagem">
            <table className="lista-de-imoveis">
              <thead>
                <tr>
                  <th scope="col">Código</th>
                  <th scope="col">Título</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Bairro</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="so-leitor">Ação</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {imoveis.map((imovel) => (
                  <tr
                    key={imovel.id}
                    className={imovel.status === 'INATIVO' ? 'lista-de-imoveis__inativo' : undefined}
                  >
                    <td className="lista-de-imoveis__codigo">{imovel.codigo}</td>
                    <td className="lista-de-imoveis__titulo">{imovel.titulo}</td>
                    <td>{TIPOS_DE_IMOVEL[imovel.tipo]}</td>
                    <td>{imovel.bairro}</td>
                    <td>
                      <Selo variante={imovel.status === 'DISPONIVEL' ? 'sucesso' : 'neutro'}>
                        {STATUS_DO_IMOVEL[imovel.status]}
                      </Selo>
                    </td>
                    <td>
                      <span className="lista-de-corretores__acoes">
                        <Link
                          href={`/admin/imoveis/${encodeURIComponent(imovel.id)}`}
                          className="botao botao--contorno botao--pequeno"
                        >
                          Editar
                        </Link>
                        {imovel.status !== 'INATIVO' && <RetirarImovel imovel={imovel} />}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Cartao>
      {haMais && (
        <p className="lista-de-imoveis__mais">
          <Link
            href={urlDaListaDeImoveis(paginas + 1)}
            scroll={false}
            className="botao botao--contorno botao--pequeno"
          >
            Carregar mais
          </Link>
        </p>
      )}
    </section>
  )
}
