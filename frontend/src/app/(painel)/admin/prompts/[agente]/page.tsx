import type { Metadata } from 'next'
import { notFound, redirect } from 'next/navigation'

import { DiffDePrompt } from '@/components/prompts/DiffDePrompt'
import { EditorDePrompt } from '@/components/prompts/EditorDePrompt'
import { ReverterVersao } from '@/components/prompts/ReverterVersao'
import { SeletorDeVersoes } from '@/components/prompts/SeletorDeVersoes'
import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { SemPermissao } from '@/components/SemPermissao'
import { agenteDaRota, ROTULO_DO_AGENTE, type AgenteDaRota } from '@/lib/prompts'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { buscarAgente, buscarVersao, buscarVersoes, ErroDePrompt } from '@/lib/servidor/prompts'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'

export const metadata: Metadata = {
  title: 'Prompt do agente — mobIA',
}

function rotuloDaVersao(numero: number): string {
  return numero === 0 ? '0 (padrão do código)' : String(numero)
}

/**
 * Editar o prompt de um agente e comparar duas versões lado a lado
 * (TEC-338).
 *
 * **A guarda é `CONFIGURAR_AGENTE`**, a mesma da listagem e de
 * `admin/configuracao/page.tsx`.
 *
 * **Comparar é navegação por `searchParams`, não fetch de cliente** (D3 do
 * desenho): `de`/`para` vêm da URL, e esta página busca as DUAS versões
 * direto do servidor -- sem nenhuma rota nova em `lib/servidor/bff.ts` para
 * leitura, só a publicação (`EditorDePrompt`) é mutação de cliente.
 */
export default async function PaginaDePrompt({
  params,
  searchParams,
}: {
  params: Promise<{ agente: string }>
  searchParams: Promise<{ de?: string; para?: string }>
}) {
  const { agente: segmento } = await params
  const agenteResolvido = agenteDaRota(segmento)
  if (!agenteResolvido) {
    notFound()
  }
  // `notFound()` e `never`, mas closures nao herdam a estreita do escopo
  // externo -- `textoDaVersao`, abaixo, precisa de uma referencia ja tipada.
  const agente: AgenteDaRota = agenteResolvido

  const enderecoDaPagina = `/admin/prompts/${agente}`
  const { sessao, quem, permitido } = await exigirPermissao(
    enderecoDaPagina,
    (p) => p.has('CONFIGURAR_AGENTE'),
  )
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let dados: Awaited<ReturnType<typeof buscarAgente>> | null = null
  let erro: ErroDePrompt | null = null
  try {
    dados = await buscarAgente(sessao.acesso, agente)
  } catch (falha) {
    erro = falha instanceof ErroDePrompt ? falha : new ErroDePrompt(0, 'sem resposta', null)
  }

  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: enderecoDaPagina, erro: 'sessao_expirada' }))
  }

  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  if (!dados) {
    return (
      <main className="painel">
        <h1>{ROTULO_DO_AGENTE[agente]}</h1>
        <ErroDeCarga
          mensagem="Não foi possível carregar o prompt deste agente."
          requestId={erro?.requestId ?? null}
          urlParaTentarDeNovo={enderecoDaPagina}
        />
      </main>
    )
  }

  let versoes: Awaited<ReturnType<typeof buscarVersoes>>['itens'] = []
  try {
    const resultado = await buscarVersoes(sessao.acesso, agente)
    versoes = resultado.itens
  } catch {
    // Extra, como o historico da TEC-337: o seletor fica sem opcoes alem da
    // ativa, mas o editor (o proposito central da tela) continua funcionando.
    versoes = []
  }

  const { de: deBusca, para: paraBusca } = await searchParams
  const ativa = dados.ativa.versao
  const anterior = versoes.find((v) => v.versao !== ativa)?.versao ?? Math.max(ativa - 1, 0)
  const numeroDe = Number.isInteger(Number(deBusca)) && deBusca !== undefined ? Number(deBusca) : anterior
  const numeroPara = Number.isInteger(Number(paraBusca)) && paraBusca !== undefined ? Number(paraBusca) : ativa

  async function textoDaVersao(numero: number): Promise<string> {
    if (numero === ativa) {
      return dados!.ativa.texto
    }
    if (numero === 0) {
      return dados!.padrao
    }
    const versao = await buscarVersao(sessao.acesso, agente, numero)
    return versao.texto
  }

  let textoDe: string
  let textoPara: string
  try {
    ;[textoDe, textoPara] = await Promise.all([textoDaVersao(numeroDe), textoDaVersao(numeroPara)])
  } catch {
    textoDe = ''
    textoPara = ''
  }

  return (
    <main className="painel">
      <h1>{ROTULO_DO_AGENTE[agente]}</h1>

      <h2>Editar e publicar</h2>
      <EditorDePrompt
        key={ativa}
        agente={agente}
        textoInicial={dados.ativa.texto}
        limites={dados.limites}
      />

      <h2>Comparar versões</h2>
      <SeletorDeVersoes itens={versoes} de={numeroDe} para={numeroPara} />
      <DiffDePrompt
        textoDe={textoDe}
        textoPara={textoPara}
        rotuloDe={`Versão ${rotuloDaVersao(numeroDe)}`}
        rotuloPara={`Versão ${rotuloDaVersao(numeroPara)}`}
      />

      <h2>Versões anteriores</h2>
      <ul className="prompts-versoes-anteriores">
        {ativa !== 0 && (
          <li>
            <span>0 (padrão do código)</span>
            <ReverterVersao agente={agente} versao={0} />
          </li>
        )}
        {versoes
          .filter((versao) => versao.versao !== ativa)
          .map((versao) => (
            <li key={versao.versao}>
              <span>
                Versão {versao.versao} — publicada por {versao.autor} em{' '}
                {new Date(versao.em).toLocaleString('pt-BR')}
              </span>
              <ReverterVersao agente={agente} versao={versao.versao} />
            </li>
          ))}
      </ul>
    </main>
  )
}
