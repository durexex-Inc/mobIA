import type { Filtros as FiltrosTipo } from '@/lib/metricas'

// Espelham os enums do backend: `Temperatura` em `context/temperatura.py` e
// `Intencao` em `agente/schemas.py`. Uma lista errada aqui produz 422 do
// backend, e nao filtro silenciosamente vazio -- e por isso que a validacao
// mora la e nao aqui: um <select> impede o erro de digitacao, nao a
// divergencia de vocabulario.
const TEMPERATURAS = ['QUENTE', 'MORNO', 'FRIO']
const INTENCOES = [
  'COMPRA',
  'ALUGUEL',
  'INVESTIMENTO',
  'VENDER_IMOVEL',
  'SUPORTE_CONTRATO',
  'INDEFINIDA',
  'FORA_DE_ESCOPO',
]
// Os dois canais existem de verdade: `whatsapp` desde a TEC-122 e `web`
// desde a TEC-124, que trouxe o widget. Os valores espelham
// `messages/canais.py`, onde estao em MINUSCULO de proposito -- a
// coluna ja estava povoada com `whatsapp`, e um `WEB` maiusculo ao
// lado faria todo filtro por canal depender de caixa.
const CANAIS = ['whatsapp', 'web']

function Selecao({
  nome,
  rotulo,
  opcoes,
  valor,
  vazio,
}: {
  nome: string
  rotulo: string
  opcoes: string[]
  valor?: string
  vazio: string
}) {
  return (
    <label>
      {rotulo}
      <select name={nome} defaultValue={valor ?? ''}>
        <option value="">{vazio}</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {opcao}
          </option>
        ))}
      </select>
    </label>
  )
}

/**
 * Os filtros da RN-17.3, como estado de URL.
 *
 * `<form method="get">` e nao `onChange` com `router.push`: a navegacao e o
 * que faz o Server Component re-renderizar e re-buscar, e um form GET
 * funciona com o JavaScript desligado. O estado do painel fica na URL, entao
 * a gerente pode mandar o link do recorte que encontrou.
 */
export function Filtros({ atuais, erro }: { atuais: FiltrosTipo; erro?: string }) {
  return (
    <form method="get" aria-label="Filtros do painel" className="filtros">
      {erro && (
        <p role="alert" className="filtros-erro">
          {erro}
        </p>
      )}
      <label>
        De
        <input type="date" name="de" defaultValue={atuais.de} required />
      </label>
      <label>
        Até
        <input type="date" name="ate" defaultValue={atuais.ate} required />
      </label>
      <Selecao nome="canal" rotulo="Canal" opcoes={CANAIS} valor={atuais.canal} vazio="Todos" />
      <Selecao
        nome="intencao"
        rotulo="Intenção"
        opcoes={INTENCOES}
        valor={atuais.intencao}
        vazio="Todas"
      />
      <Selecao
        nome="temperatura"
        rotulo="Temperatura"
        opcoes={TEMPERATURAS}
        valor={atuais.temperatura}
        vazio="Todas"
      />
      <label>
        Corretor
        <input type="text" name="corretorId" defaultValue={atuais.corretorId ?? ''} />
      </label>
      <button type="submit">Aplicar</button>
    </form>
  )
}
