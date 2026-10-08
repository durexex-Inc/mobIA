import { type Corretor, ESPECIALIDADES } from '@/lib/corretores'
import { DesativarCorretor } from '@/components/DesativarCorretor'
import { FormularioDeCorretor } from '@/components/FormularioDeCorretor'
import { Cartao } from '@/components/ui/Cartao'
import { Selo } from '@/components/ui/Selo'

/**
 * A lista de corretores, ativos e inativos juntos (D6 do desenho da TEC-332),
 * com a contagem de ativos e o estado vazio (D7 da TEC-397).
 *
 * **O rotulo de inativo e de plantonista e TEXTO**, nunca so cor -- mesmo
 * padrao de `Vazio`/`ErroDeCarga` e do "Prazo curto" de `FilaDoTitular.tsx`.
 * Editar abre `FormularioDeCorretor` num `<dialog>`; desativar so aparece em
 * linha ativa, porque nao ha reativar (D5).
 */
export function ListaDeCorretores({ corretores }: { corretores: Corretor[] }) {
  const ativos = corretores.filter((corretor) => corretor.ativo).length

  return (
    <section aria-labelledby="corretores-cadastrados" className="secao">
      <div className="secao__cabecalho">
        <h2 id="corretores-cadastrados" className="corretores__titulo">
          Corretores cadastrados
          <Selo>
            {ativos} {ativos === 1 ? 'ativo' : 'ativos'}
          </Selo>
        </h2>
        <p className="secao__total">Total: {corretores.length}</p>
      </div>
      <Cartao className="corretores__cartao">
        {corretores.length === 0 ? (
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
              <circle cx="9" cy="8" r="3" />
              <path d="M3 20a6 6 0 0 1 12 0" />
              <circle cx="17" cy="9" r="2.5" />
              <path d="M16 14.5a5 5 0 0 1 5 5.5" />
            </svg>
            <p className="estado-vazio-do-painel__titulo">Nenhum corretor cadastrado.</p>
            <p>Preencha o cadastro acima para que o agente possa encaminhar leads e agendar visitas.</p>
          </div>
        ) : (
          <div className="corretores__rolagem">
            <table className="lista-de-corretores">
              <thead>
                <tr>
                  <th scope="col">Nome</th>
                  <th scope="col">Especialidades</th>
                  <th scope="col">Regiões</th>
                  <th scope="col">Jornada</th>
                  <th scope="col">Capacidade</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="so-leitor">Ação</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {corretores.map((corretor) => (
                  <tr key={corretor.id} className={corretor.ativo ? undefined : 'lista-de-corretores__inativo'}>
                    <td>
                      <span className="lista-de-corretores__nome">{corretor.nome}</span>
                      <span className="lista-de-corretores__email">{corretor.email}</span>
                    </td>
                    <td>
                      {corretor.especialidades.map((especialidade) => ESPECIALIDADES[especialidade]).join(', ')}
                    </td>
                    <td>{corretor.regioesAtuacao.join(', ')}</td>
                    <td>
                      {corretor.horarioInicio}h–{corretor.horarioFim}h
                    </td>
                    <td>{corretor.capacidadeDiaria} / dia</td>
                    <td>
                      <span className="lista-de-corretores__selos">
                        {corretor.ativo ? <Selo variante="sucesso">Ativo</Selo> : <Selo>Inativo</Selo>}
                        {corretor.plantao && <Selo variante="info">Generalista de plantão</Selo>}
                      </span>
                    </td>
                    <td>
                      <span className="lista-de-corretores__acoes">
                        <FormularioDeCorretor corretor={corretor} />
                        {corretor.ativo && <DesativarCorretor corretor={corretor} />}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Cartao>
    </section>
  )
}
