import { type Corretor, ESPECIALIDADES } from '@/lib/corretores'
import { DesativarCorretor } from '@/components/DesativarCorretor'
import { FormularioDeCorretor } from '@/components/FormularioDeCorretor'

/**
 * A lista de corretores, ativos e inativos juntos (D6 do desenho).
 *
 * **O rotulo de inativo e de plantonista e TEXTO**, nunca so cor -- mesmo
 * padrao de `Vazio`/`ErroDeCarga` e do "Prazo curto" de `FilaDoTitular.tsx`.
 * Editar abre `FormularioDeCorretor` na propria linha; desativar so aparece
 * em linha ativa, porque nao ha reativar (D5).
 */
export function ListaDeCorretores({ corretores }: { corretores: Corretor[] }) {
  return (
    <table className="lista-de-corretores">
      <thead>
        <tr>
          <th scope="col">Nome</th>
          <th scope="col">E-mail</th>
          <th scope="col">Especialidades</th>
          <th scope="col">Regiões</th>
          <th scope="col">Capacidade</th>
          <th scope="col">Status</th>
          <th scope="col">Ação</th>
        </tr>
      </thead>
      <tbody>
        {corretores.map((corretor) => (
          <tr key={corretor.id} className={corretor.ativo ? undefined : 'lista-de-corretores__inativo'}>
            <td>{corretor.nome}</td>
            <td>{corretor.email}</td>
            <td>{corretor.especialidades.map((especialidade) => ESPECIALIDADES[especialidade]).join(', ')}</td>
            <td>{corretor.regioesAtuacao.join(', ')}</td>
            <td>{corretor.capacidadeDiaria}</td>
            <td>
              {!corretor.ativo && <span className="lista-de-corretores__rotulo">Inativo</span>}
              {corretor.plantao && (
                <span className="lista-de-corretores__rotulo">Generalista de plantão</span>
              )}
            </td>
            <td>
              <FormularioDeCorretor corretor={corretor} />
              {corretor.ativo && <DesativarCorretor corretor={corretor} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
