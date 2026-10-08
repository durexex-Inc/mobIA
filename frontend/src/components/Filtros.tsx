import { Botao } from '@/components/ui/Botao'
import { Cartao } from '@/components/ui/Cartao'
import { CampoDeSelecao } from '@/components/ui/CampoDeSelecao'
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
      <CampoDeSelecao name={nome} defaultValue={valor ?? ''}>
        <option value="">{vazio}</option>
        {opcoes.map((opcao) => (
          <option key={opcao} value={opcao}>
            {opcao}
          </option>
        ))}
      </CampoDeSelecao>
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
/**
 * Os campos que sabem exibir a mensagem ao lado (TEC-313, D5).
 *
 * **Os tres `<select>` ficam de fora de proposito, e nao por esquecimento.**
 * Eles nao aceitam valor digitado: as opcoes sao fixas, entao um 422 sobre
 * `canal` ou `temperatura` nao e um engano que a gerente cometeu no campo --
 * e URL montada a mao ou divergencia entre o vocabulario da tela e o do
 * backend. Mensagem ao lado de um `<select>` correto nao a ajudaria a
 * consertar nada; o aviso acima do formulario, sim, porque diz que o recorte
 * pedido nao existe.
 *
 * Testar contra esta lista, e nao contra as chaves presentes em `atuais`:
 * filtro opcional nao preenchido nao existe como chave, e a mensagem sumiria
 * exatamente no caso em que o valor veio errado.
 *
 * `corretorId` saiu desta lista na TEC-316: o campo agora e desabilitado (D2
 * do desenho) e ninguem mais envia esse parametro, entao ele nao pode mais
 * levar 422 nenhum.
 */
const CAMPOS_COM_MENSAGEM: ReadonlySet<string> = new Set(['de', 'ate'])

/**
 * A mensagem do backend ao lado do campo que ela recusa (RN-FE-04.4).
 *
 * `role="alert"` em cada um, e nao um so no formulario: o leitor de tela
 * precisa anunciar a mensagem no contexto do campo, e nao uma frase solta que
 * obrigue a procurar qual campo ela descreve.
 */
function ErroDoCampo({
  nome,
  campos,
  mensagem,
}: {
  nome: string
  campos: Set<string>
  mensagem?: string
}) {
  if (!campos.has(nome) || !mensagem) {
    return null
  }
  return (
    <span role="alert" className="filtros-erro-campo">
      {mensagem}
    </span>
  )
}

export function Filtros({
  atuais,
  erro,
  campos = [],
}: {
  atuais: FiltrosTipo
  erro?: string
  campos?: string[]
}) {
  /**
   * Um 422 que aponta campo vira mensagem AO LADO do campo; um que nao aponta
   * fica acima do formulario (TEC-313, D5).
   *
   * **O erro nao aparece nos dois lugares.** Repetir o mesmo texto acima e ao
   * lado faria a gerente procurar dois problemas onde ha um. E o aviso acima
   * continua sendo o certo para o que nao e de campo nenhum -- 403, 5xx, e os
   * 422 cujo `detail` e prosa.
   */
  const comCampo = new Set(campos.filter((campo) => CAMPOS_COM_MENSAGEM.has(campo)))
  const erroSolto = erro && comCampo.size === 0 ? erro : undefined

  return (
    <Cartao className="filtros-cartao">
      <form method="get" aria-label="Filtros do painel" className="filtros">
        {erroSolto && (
          <p role="alert" className="filtros-erro">
            {erroSolto}
          </p>
        )}
        <label>
          De
          <input type="date" name="de" defaultValue={atuais.de} required className="campo" />
          <ErroDoCampo nome="de" campos={comCampo} mensagem={erro} />
        </label>
        <label>
          Até
          <input type="date" name="ate" defaultValue={atuais.ate} required className="campo" />
          <ErroDoCampo nome="ate" campos={comCampo} mensagem={erro} />
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
        {/* TEC-316, D2: desabilitado ate existir alocacao de corretor no
            handoff (a TEC-166 aloca ao agendamento, nao ao handoff -- ver a
            descoberta do desenho). Nao envia `corretorId` nenhum: o backend
            continua recusando esse filtro com 422, e ninguem mais digita um
            valor para mandar. Molde identico ao `modo: 'indisponivel'` de
            `FiltrosDeLeads` (TEC-322, D5). */}
        <label>
          Corretor
          <CampoDeSelecao disabled aria-describedby="filtros-corretor-motivo">
            <option>Todos</option>
          </CampoDeSelecao>
        </label>
        <div className="filtros-rodape">
          <Botao type="submit">Aplicar</Botao>
          <span id="filtros-corretor-motivo" className="filtros-corretor-motivo">
            Disponível após a alocação de corretor.
          </span>
        </div>
      </form>
    </Cartao>
  )
}
