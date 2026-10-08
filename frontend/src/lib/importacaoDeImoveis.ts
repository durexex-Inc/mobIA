/**
 * Os tipos e constantes da importacao de imoveis em lote (TEC-334), sem I/O.
 *
 * `Importacao` e `Erro` espelham `_relatorio` (`api/routes/imoveis.py`):
 * mesmo formato no `POST` inicial (so `importacaoId`/`status`), no `GET` por
 * id e na lista das recentes (D6 do desenho da TEC-197) -- a tela trata os
 * tres como o mesmo objeto.
 */

export type StatusDaImportacao = 'PROCESSANDO' | 'CONCLUIDO' | 'FALHOU'

export type Erro = {
  linha: number
  motivo: string
}

export type Importacao = {
  importacaoId: string
  status: StatusDaImportacao
  nomeArquivo: string
  processados: number
  inseridos: number
  atualizados: number
  inalterados: number
  rejeitados: number
  erros: Erro[]
}

/**
 * D2 do desenho: o mesmo valor de `TETO_DE_UPLOAD_EM_BYTES`
 * (`api/routes/imoveis.py`) -- duplicacao deliberada, sem como uma rota HTTP
 * compartilhar uma constante de modulo com o cliente sem inventar um
 * endpoint so para isso. O teto do backend (413) continua a garantia real;
 * este e a recusa na hora certa que o Gherkin pede, na selecao do arquivo.
 */
export const TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024

/**
 * As colunas que o cabecalho do CSV tem de trazer -- copia de
 * `domain/catalogo/parser.py::_OBRIGATORIAS`, na mesma ordem e pela mesma
 * razao da duplicacao acima. So vira texto de ajuda na tela (D3 da TEC-398):
 * quem recusa o cabecalho incompleto continua sendo o backend.
 */
export const COLUNAS_OBRIGATORIAS_DO_CSV = [
  'codigo',
  'titulo',
  'descricao',
  'tipo',
  'operacao',
  'bairro',
  'cidade',
  'uf',
  'area_util_m2',
  'quartos',
  'suites',
  'banheiros',
  'vagas',
  'status',
] as const

/** D3 do desenho: o intervalo de polling de `AcompanharImportacao.tsx`. */
export const INTERVALO_DE_POLLING_MS = 3000
