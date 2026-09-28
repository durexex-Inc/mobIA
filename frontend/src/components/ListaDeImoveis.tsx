import { type Imovel, STATUS_DO_IMOVEL } from '@/lib/imoveis'
import { FormularioDeImovel } from '@/components/FormularioDeImovel'
import { RetirarImovel } from '@/components/RetirarImovel'

/**
 * A lista de imoveis, de todo status junto (D6 do desenho).
 *
 * **O status e TEXTO**, nunca so cor -- mesmo padrao do rotulo de "Inativo"
 * em `ListaDeCorretores.tsx`. Editar abre `FormularioDeImovel` na propria
 * linha; retirar so aparece em linha que nao esta `INATIVO`, porque nao ha
 * reativar por botao dedicado (D4) -- reativar e editar o Status.
 */
export function ListaDeImoveis({ imoveis }: { imoveis: Imovel[] }) {
  return (
    <table className="lista-de-imoveis">
      <thead>
        <tr>
          <th scope="col">Código</th>
          <th scope="col">Título</th>
          <th scope="col">Bairro</th>
          <th scope="col">Status</th>
          <th scope="col">Ação</th>
        </tr>
      </thead>
      <tbody>
        {imoveis.map((imovel) => (
          <tr
            key={imovel.id}
            className={imovel.status === 'INATIVO' ? 'lista-de-imoveis__inativo' : undefined}
          >
            <td>{imovel.codigo}</td>
            <td>{imovel.titulo}</td>
            <td>{imovel.bairro}</td>
            <td>
              <span className="lista-de-imoveis__rotulo">{STATUS_DO_IMOVEL[imovel.status]}</span>
            </td>
            <td>
              <FormularioDeImovel imovel={imovel} />
              {imovel.status !== 'INATIVO' && <RetirarImovel imovel={imovel} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
