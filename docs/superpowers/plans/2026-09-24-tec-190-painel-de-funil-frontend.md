# Painel de funil — frontend (Next.js) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o painel que a gerente abre — seis etapas do funil com conversão, os indicadores da RN-17.1 e cinco filtros — consumindo `GET /api/v1/metricas/funil`.

**Architecture:** Next.js 15 (App Router) em `frontend/`, dentro deste repo. A página é um **Server Component**: ela busca o FastAPI no servidor, com o `X-Admin-Token` vindo de env do servidor, e o token nunca chega ao navegador. Os filtros são estado de URL (`searchParams`), então trocar um filtro é navegação, e a navegação re-renderiza no servidor. `fetch(..., { next: { revalidate: 60 } })` põe a resposta no Data Cache do Next, o que dá o teto de defasagem da RN-17.3 e faz N navegadores virarem uma chamada por minuto ao FastAPI.

**Tech Stack:** Next.js 15, React 19, TypeScript, Vitest + Testing Library, Node 22.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-190-painel-de-funil-design.md`

**Depende de:** `docs/superpowers/plans/2026-09-24-tec-190-painel-de-funil-endpoint.md`, que entrega o endpoint. Este plano pode ser desenvolvido contra a resposta de exemplo da spec antes de o endpoint existir, mas a Tarefa 6 exige o endpoint de pé.

## Global Constraints

- **Node 22**, fixado em `frontend/.nvmrc` e no job de CI.
- **O `X-Admin-Token` nunca aparece em código de cliente.** Só em `process.env.MOBIA_ADMIN_TOKEN`, lido em Server Component ou Route Handler. Nenhuma variável `NEXT_PUBLIC_*` carrega segredo.
- **`revalidate: 60`** em toda busca ao FastAPI — é o teto da RN-17.3 e não um número arbitrário.
- **Os três gates de Python não passam a olhar para `frontend/`.** O escopo de `ruff` e `mypy` continua `src tests alembic evals scripts`; o lado JS tem job próprio.
- **Texto de tela em português COM acento.** É texto de produto, mesma regra que o `CLAUDE.md` dá para o que o lead recebe.
- **`quantidade: null` com `disponivel: false` nunca se renderiza como `0`, nem como barra vazia.** É a D1 da spec, e é a razão de o campo existir.

## Review Focus

Classes de entrada que a spec implica e que nenhuma tarefa exercitaria por si:

1. **O FastAPI fora do ar ou devolvendo 500** — a página tem de dizer que não conseguiu carregar, não renderizar um funil de zeros que a gerente leria como "nenhum lead". Pinado na Tarefa 6.
2. **403 do FastAPI** (token errado ou ausente no env do servidor) — mensagem distinta de "sem dados": é erro de configuração do operador, e um funil vazio o esconderia. Tarefa 6.
3. **Todas as etapas em zero** (período legítimo sem lead nenhum) — é diferente do caso 1, e tem de ser visivelmente diferente na tela. Tarefa 3.
4. **`conversaoDaAnterior: null` nas três origens** — primeira etapa, etapa anterior indisponível, etapa anterior em zero. As três renderizam igual ("—"), mas o teste tem de cobrir as três, senão uma regressão no backend passa despercebida. Tarefa 3.
5. **`searchParams` com valor que o backend recusa** (`temperatura=MORNA`) — o backend devolve 422; a página mostra qual filtro está inválido, e não uma tela de erro genérica. Tarefa 5.

---

## Estrutura de arquivos

| arquivo | responsabilidade |
| --- | --- |
| `frontend/package.json`, `tsconfig.json`, `next.config.ts`, `.nvmrc` | projeto |
| `frontend/src/lib/metricas.ts` | o tipo da resposta e a busca ao FastAPI; o único lugar que lê o token |
| `frontend/src/lib/formato.ts` | formatação de percentual, duração e "—" para nulo |
| `frontend/src/components/Funil.tsx` | as seis etapas com conversão |
| `frontend/src/components/Indicadores.tsx` | os cartões da RN-17.1 |
| `frontend/src/components/Filtros.tsx` | os cinco filtros, como estado de URL |
| `frontend/src/app/page.tsx` | Server Component que compõe os três |
| `frontend/src/app/erro.tsx` | o que aparece quando a busca falha |
| `.github/workflows/ci.yml` | job novo `frontend` |

---

### Task 1: Scaffold do projeto e job de CI

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.ts`, `frontend/.nvmrc`, `frontend/.gitignore`, `frontend/vitest.config.ts`, `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nada.
- Produces: um `npm run build`, `npm run lint` e `npm test` que passam, e um job de CI que os roda.

- [ ] **Step 1: Criar o projeto**

```bash
cd C:/Projetos/mobIA
npx create-next-app@latest frontend --typescript --app --eslint --no-tailwind --no-src-dir --import-alias "@/*" --use-npm --skip-install
```

Depois mova para `src/`: o `create-next-app` com `--no-src-dir` põe `app/` na raiz; este plano usa `frontend/src/app/`. Se o gerador já tiver criado `frontend/app/`, renomeie para `frontend/src/app/` e ajuste `tsconfig.json` (`"paths": { "@/*": ["./src/*"] }`).

- [ ] **Step 2: Fixar o Node**

```bash
echo "22" > frontend/.nvmrc
```

- [ ] **Step 3: Instalar as dependências de teste**

```bash
cd frontend && npm install && npm install -D vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 4: Configurar o Vitest**

`frontend/vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': resolve(__dirname, './src') } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    globals: true,
  },
})
```

`frontend/vitest.setup.ts`:

```typescript
import '@testing-library/jest-dom/vitest'
```

Acrescente ao `scripts` do `frontend/package.json`:

```json
"test": "vitest run"
```

- [ ] **Step 5: Verificar que o esqueleto roda**

Run: `cd frontend && npm run build && npm run lint && npm test`
Expected: o build passa; o lint passa; o `vitest` termina com "No test files found" (é sucesso nesta etapa).

- [ ] **Step 6: Acrescentar o job de CI**

Em `.github/workflows/ci.yml`, depois do job `testes`, acrescente:

```yaml
  frontend:
    name: Frontend
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version-file: frontend/.nvmrc
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Instalar dependencias
        run: npm ci

      # Os tres gates estaticos de Python (`ruff check`, `ruff format`, `mypy`)
      # NAO olham para `frontend/`: o escopo deles e `src tests alembic evals
      # scripts`, e acrescentar um diretorio de TypeScript ali nao faria
      # sentido. O lado JS tem os gates dele aqui.
      - name: Lint
        run: npm run lint

      - name: Testes
        run: npm test

      - name: Build
        run: npm run build
```

- [ ] **Step 7: Commit**

```bash
cd C:/Projetos/mobIA
git add frontend .github/workflows/ci.yml
git commit -m "feat(TEC-190): o projeto Next.js existe e o CI o constroi"
```

---

### Task 2: A busca ao FastAPI, com o token no servidor

**Files:**
- Create: `frontend/src/lib/metricas.ts`, `frontend/src/lib/metricas.test.ts`

**Interfaces:**
- Consumes: o contrato de `GET /api/v1/metricas/funil` (spec, seção "Contrato").
- Produces:
  - `type Etapa = { nome: string; quantidade: number | null; disponivel: boolean; conversaoDaAnterior: number | null }`
  - `type Indicadores = Record<string, number | Record<string, number> | null>`
  - `type Funil = { etapas: Etapa[]; indicadores: Indicadores; indisponiveis: string[] }`
  - `type Filtros = { de: string; ate: string; canal?: string; intencao?: string; temperatura?: string; corretorId?: string }`
  - `async function buscarFunil(filtros: Filtros): Promise<Funil>` — levanta `ErroDeMetricas` com `status` numérico quando o FastAPI não responde 200.
  - `class ErroDeMetricas extends Error { status: number }`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/lib/metricas.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { buscarFunil, ErroDeMetricas } from './metricas'

const RESPOSTA = {
  etapas: [{ nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null }],
  indicadores: { leadsNovos: 320 },
  indisponiveis: [],
}

describe('buscarFunil', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ADMIN_TOKEN = 'segredo'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o token no header e devolve o corpo', async () => {
    const fetchFalso = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(RESPOSTA), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchFalso)

    const funil = await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })

    expect(funil.etapas[0].quantidade).toBe(320)
    const [url, init] = fetchFalso.mock.calls[0]
    expect(String(url)).toContain('/api/v1/metricas/funil')
    expect(String(url)).toContain('de=2026-08-01')
    expect(init.headers['X-Admin-Token']).toBe('segredo')
    expect(init.next).toEqual({ revalidate: 60 })
  })

  it('omite da query o filtro que nao foi informado', async () => {
    const fetchFalso = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(RESPOSTA), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchFalso)

    await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })

    expect(String(fetchFalso.mock.calls[0][0])).not.toContain('canal=')
  })

  it('levanta ErroDeMetricas com o status quando o backend recusa', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })))

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toMatchObject({
      status: 403,
    })
    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toBeInstanceOf(
      ErroDeMetricas,
    )
  })
})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/lib/metricas.test.ts`
Expected: FAIL — `Failed to resolve import "./metricas"`.

- [ ] **Step 3: Implementar**

`frontend/src/lib/metricas.ts`:

```typescript
export type Etapa = {
  nome: string
  quantidade: number | null
  disponivel: boolean
  conversaoDaAnterior: number | null
}

export type Indicadores = Record<string, number | Record<string, number> | null>

export type Funil = {
  etapas: Etapa[]
  indicadores: Indicadores
  indisponiveis: string[]
}

export type Filtros = {
  de: string
  ate: string
  canal?: string
  intencao?: string
  temperatura?: string
  corretorId?: string
}

export class ErroDeMetricas extends Error {
  status: number

  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.name = 'ErroDeMetricas'
    this.status = status
  }
}

/**
 * Busca o funil no FastAPI. **Roda so no servidor**: le
 * `MOBIA_ADMIN_TOKEN`, que nao e `NEXT_PUBLIC_*` de proposito -- o token e
 * de admin total, e um `NEXT_PUBLIC_` o entregaria a qualquer navegador.
 *
 * `revalidate: 60` e o teto de defasagem da RN-17.3, e nao um numero
 * escolhido a esmo. Ele tambem e o que faz N navegadores com o painel aberto
 * virarem UMA chamada por minuto ao FastAPI -- que ve o IP deste servidor,
 * nao o de cada navegador, e aplica 100 req/min por IP.
 */
export async function buscarFunil(filtros: Filtros): Promise<Funil> {
  const base = process.env.MOBIA_API_BASE ?? 'http://localhost:8000'
  const url = new URL('/api/v1/metricas/funil', base)

  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      url.searchParams.set(chave, valor)
    }
  }

  const resposta = await fetch(url, {
    headers: { 'X-Admin-Token': process.env.MOBIA_ADMIN_TOKEN ?? '' },
    next: { revalidate: 60 },
  })

  if (!resposta.ok) {
    throw new ErroDeMetricas(resposta.status, `o backend respondeu ${resposta.status}`)
  }

  return (await resposta.json()) as Funil
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/lib/metricas.test.ts`
Expected: PASS, 3 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/metricas.ts frontend/src/lib/metricas.test.ts
git commit -m "feat(TEC-190): a busca do funil manda o token do servidor e cacheia por 60s"
```

---

### Task 3: O funil, com as três origens de nulo

**Files:**
- Create: `frontend/src/lib/formato.ts`, `frontend/src/lib/formato.test.ts`, `frontend/src/components/Funil.tsx`, `frontend/src/components/Funil.test.tsx`

**Interfaces:**
- Consumes: `Etapa` da Tarefa 2.
- Produces:
  - `function percentual(valor: number | null): string` — `"—"` para nulo, `"83,8%"` para `0.8375`.
  - `function quantidadeLegivel(etapa: Etapa): string` — `"sem fonte de dados"` quando `disponivel` é falso.
  - `function Funil({ etapas }: { etapas: Etapa[] }): JSX.Element`

- [ ] **Step 1: Escrever o teste de formatação que falha**

`frontend/src/lib/formato.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { percentual, quantidadeLegivel } from './formato'

describe('percentual', () => {
  it('formata em pt-BR com uma casa', () => {
    expect(percentual(0.8375)).toBe('83,8%')
  })

  it('devolve travessao para nulo', () => {
    expect(percentual(null)).toBe('—')
  })

  it('formata zero como zero, e nao como travessao', () => {
    expect(percentual(0)).toBe('0,0%')
  })
})

describe('quantidadeLegivel', () => {
  it('diz que nao ha fonte quando a etapa e indisponivel', () => {
    expect(
      quantidadeLegivel({
        nome: 'Agendado',
        quantidade: null,
        disponivel: false,
        conversaoDaAnterior: null,
      }),
    ).toBe('sem fonte de dados')
  })

  it('mostra zero como zero quando a etapa e disponivel', () => {
    expect(
      quantidadeLegivel({
        nome: 'Novo',
        quantidade: 0,
        disponivel: true,
        conversaoDaAnterior: null,
      }),
    ).toBe('0')
  })
})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/lib/formato.test.ts`
Expected: FAIL — módulo não encontrado.

- [ ] **Step 3: Implementar a formatação**

`frontend/src/lib/formato.ts`:

```typescript
import type { Etapa } from './metricas'

const PERCENTUAL = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

/**
 * Percentual em pt-BR, ou travessao quando nao ha numero.
 *
 * **Zero nao e nulo aqui**: `0` e uma conversao medida de 0%, e `null` e a
 * ausencia de conversao calculavel. A spec distingue tres origens de `null`
 * -- primeira etapa, etapa anterior indisponivel, etapa anterior em zero --
 * e as tres se renderizam igual, mas nenhuma delas se confunde com 0%.
 */
export function percentual(valor: number | null): string {
  return valor === null ? '—' : PERCENTUAL.format(valor)
}

/**
 * O que se escreve no lugar da quantidade.
 *
 * `disponivel: false` NUNCA vira `0`: zero afirmaria que nada aconteceu no
 * periodo, quando a verdade e que nada e registrado. Ver a D1 do desenho.
 */
export function quantidadeLegivel(etapa: Etapa): string {
  if (!etapa.disponivel || etapa.quantidade === null) {
    return 'sem fonte de dados'
  }
  return new Intl.NumberFormat('pt-BR').format(etapa.quantidade)
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/lib/formato.test.ts`
Expected: PASS, 5 testes.

- [ ] **Step 5: Escrever o teste do componente que falha**

`frontend/src/components/Funil.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Funil } from './Funil'
import type { Etapa } from '@/lib/metricas'

const ETAPAS: Etapa[] = [
  { nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Em conversa', quantidade: 268, disponivel: true, conversaoDaAnterior: 0.8375 },
  { nome: 'Qualificado', quantidade: 0, disponivel: true, conversaoDaAnterior: 0 },
  { nome: 'Recomendado', quantidade: 118, disponivel: true, conversaoDaAnterior: null },
  { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: null },
  { nome: 'Handoff aceito', quantidade: 39, disponivel: true, conversaoDaAnterior: null },
]

describe('Funil', () => {
  it('mostra as seis etapas', () => {
    render(<Funil etapas={ETAPAS} />)
    for (const nome of ['Novo', 'Em conversa', 'Qualificado', 'Recomendado', 'Agendado', 'Handoff aceito']) {
      expect(screen.getByText(nome)).toBeInTheDocument()
    }
  })

  it('escreve a conversao entre etapas consecutivas', () => {
    render(<Funil etapas={ETAPAS} />)
    expect(screen.getByText('83,8%')).toBeInTheDocument()
  })

  it('a etapa sem fonte nao mostra zero', () => {
    render(<Funil etapas={ETAPAS} />)
    const agendado = screen.getByTestId('etapa-Agendado')
    expect(agendado).toHaveTextContent('sem fonte de dados')
    expect(agendado).not.toHaveTextContent(/\b0\b/)
  })

  it('a etapa com zero real mostra zero, e nao "sem fonte"', () => {
    render(<Funil etapas={ETAPAS} />)
    const qualificado = screen.getByTestId('etapa-Qualificado')
    expect(qualificado).toHaveTextContent('0')
    expect(qualificado).not.toHaveTextContent('sem fonte de dados')
  })

  it('renderiza travessao nas tres origens de conversao nula', () => {
    render(<Funil etapas={ETAPAS} />)
    // Novo (primeira etapa), Recomendado (anterior em zero) e
    // Handoff aceito (anterior indisponivel) -- mais Agendado, cuja anterior
    // tem numero mas que nao tem quantidade propria.
    expect(screen.getAllByText('—')).toHaveLength(4)
  })
})
```

- [ ] **Step 6: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/components/Funil.test.tsx`
Expected: FAIL — módulo `./Funil` não encontrado.

- [ ] **Step 7: Implementar o componente**

`frontend/src/components/Funil.tsx`:

```tsx
import type { Etapa } from '@/lib/metricas'
import { percentual, quantidadeLegivel } from '@/lib/formato'

/**
 * As seis etapas da RN-17.2, com a conversao entre consecutivas.
 *
 * A largura da barra sai da MAIOR etapa disponivel, e nao da primeira: a
 * primeira pode ser a que nao tem fonte, e dividir por ela daria NaN.
 */
export function Funil({ etapas }: { etapas: Etapa[] }) {
  const maior = Math.max(
    1,
    ...etapas.filter((e) => e.disponivel && e.quantidade !== null).map((e) => e.quantidade ?? 0),
  )

  return (
    <ol aria-label="Funil de leads">
      {etapas.map((etapa) => (
        <li key={etapa.nome} data-testid={`etapa-${etapa.nome}`}>
          <span>{etapa.nome}</span>
          <span>{quantidadeLegivel(etapa)}</span>
          <span aria-label={`conversao da etapa anterior para ${etapa.nome}`}>
            {percentual(etapa.conversaoDaAnterior)}
          </span>
          <div
            role="presentation"
            style={{
              width: etapa.disponivel && etapa.quantidade !== null
                ? `${(etapa.quantidade / maior) * 100}%`
                : 0,
            }}
          />
        </li>
      ))}
    </ol>
  )
}
```

- [ ] **Step 8: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/components/Funil.test.tsx`
Expected: PASS, 5 testes.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/formato.ts frontend/src/lib/formato.test.ts frontend/src/components/Funil.tsx frontend/src/components/Funil.test.tsx
git commit -m "feat(TEC-190): o funil distingue zero medido de etapa sem fonte"
```

---

### Task 4: Os indicadores da RN-17.1

**Files:**
- Create: `frontend/src/components/Indicadores.tsx`, `frontend/src/components/Indicadores.test.tsx`

**Interfaces:**
- Consumes: `Indicadores` e `Funil` da Tarefa 2; `percentual` da Tarefa 3.
- Produces: `function Indicadores({ indicadores, indisponiveis }: { indicadores: IndicadoresTipo; indisponiveis: string[] }): JSX.Element`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/components/Indicadores.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Indicadores } from './Indicadores'

const DADOS = {
  leadsNovos: 320,
  conversasAtivas: 87,
  taxaQualificacao: 0.44,
  distribuicaoPorTemperatura: { QUENTE: 41, MORNO: 63, FRIO: 37 },
  tempoMedioPrimeiraRespostaSeg: 4.2,
  tempoMedioQualificacaoSeg: 512,
  slaHandoffCumpridoPct: 0.87,
  agendamentosCriados: null,
  agendamentosConfirmados: null,
  agendamentosRealizados: null,
  taxaNoShow: null,
}

const INDISPONIVEIS = [
  'agendamentosCriados',
  'agendamentosConfirmados',
  'agendamentosRealizados',
  'taxaNoShow',
]

describe('Indicadores', () => {
  it('mostra os indicadores com numero', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    expect(screen.getByTestId('indicador-leadsNovos')).toHaveTextContent('320')
    expect(screen.getByTestId('indicador-taxaQualificacao')).toHaveTextContent('44,0%')
  })

  it('mostra a distribuicao por temperatura nas tres faixas', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    const temperatura = screen.getByTestId('indicador-distribuicaoPorTemperatura')
    expect(temperatura).toHaveTextContent('QUENTE')
    expect(temperatura).toHaveTextContent('41')
    expect(temperatura).toHaveTextContent('FRIO')
  })

  it('o indicador sem fonte diz por que, e nao mostra zero', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    const noShow = screen.getByTestId('indicador-taxaNoShow')
    expect(noShow).toHaveTextContent('sem fonte de dados')
    expect(noShow).not.toHaveTextContent('0')
  })

  it('explica uma vez que as visitas ainda nao sao registradas', () => {
    render(<Indicadores indicadores={DADOS} indisponiveis={INDISPONIVEIS} />)
    expect(screen.getByRole('note')).toHaveTextContent(/visita/i)
  })
})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/components/Indicadores.test.tsx`
Expected: FAIL — módulo não encontrado.

- [ ] **Step 3: Implementar**

`frontend/src/components/Indicadores.tsx`:

```tsx
import type { Indicadores as IndicadoresTipo } from '@/lib/metricas'
import { percentual } from '@/lib/formato'

const ROTULOS: Record<string, string> = {
  leadsNovos: 'Leads novos',
  conversasAtivas: 'Conversas ativas',
  taxaQualificacao: 'Taxa de qualificação',
  distribuicaoPorTemperatura: 'Distribuição por temperatura',
  tempoMedioPrimeiraRespostaSeg: 'Tempo médio de primeira resposta',
  tempoMedioQualificacaoSeg: 'Tempo médio de qualificação',
  slaHandoffCumpridoPct: 'Handoff aceito no SLA',
  agendamentosCriados: 'Agendamentos criados',
  agendamentosConfirmados: 'Agendamentos confirmados',
  agendamentosRealizados: 'Agendamentos realizados',
  taxaNoShow: 'Taxa de no-show',
}

const COMO_PERCENTUAL = new Set(['taxaQualificacao', 'slaHandoffCumpridoPct', 'taxaNoShow'])
const COMO_DURACAO = new Set(['tempoMedioPrimeiraRespostaSeg', 'tempoMedioQualificacaoSeg'])

function duracao(segundos: number): string {
  if (segundos < 60) {
    return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(segundos)} s`
  }
  return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(segundos / 60)} min`
}

function valorLegivel(chave: string, valor: number | Record<string, number> | null): string {
  if (valor === null) {
    return 'sem fonte de dados'
  }
  if (typeof valor === 'object') {
    return Object.entries(valor)
      .map(([faixa, quantos]) => `${faixa}: ${quantos}`)
      .join('  ')
  }
  if (COMO_PERCENTUAL.has(chave)) {
    return percentual(valor)
  }
  if (COMO_DURACAO.has(chave)) {
    return duracao(valor)
  }
  return new Intl.NumberFormat('pt-BR').format(valor)
}

/**
 * Os indicadores da RN-17.1.
 *
 * Os quatro de agendamento saem nulos enquanto RF-11 e RF-12 nao existirem,
 * e a nota no rodape diz isso uma vez -- sem ela, quatro cartoes escritos
 * "sem fonte de dados" parecem defeito do painel, e nao ausencia declarada.
 */
export function Indicadores({
  indicadores,
  indisponiveis,
}: {
  indicadores: IndicadoresTipo
  indisponiveis: string[]
}) {
  return (
    <section aria-label="Indicadores do periodo">
      <dl>
        {Object.entries(indicadores).map(([chave, valor]) => (
          <div key={chave} data-testid={`indicador-${chave}`}>
            <dt>{ROTULOS[chave] ?? chave}</dt>
            <dd>{valorLegivel(chave, valor)}</dd>
          </div>
        ))}
      </dl>
      {indisponiveis.length > 0 && (
        <p role="note">
          Os indicadores de visita ainda não têm fonte: nenhuma visita é registrada no sistema
          hoje. Eles voltam quando o agendamento existir.
        </p>
      )}
    </section>
  )
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/components/Indicadores.test.tsx`
Expected: PASS, 4 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Indicadores.tsx frontend/src/components/Indicadores.test.tsx
git commit -m "feat(TEC-190): os indicadores da RN-17.1, com a nota das visitas sem fonte"
```

---

### Task 5: Os cinco filtros como estado de URL

**Files:**
- Create: `frontend/src/components/Filtros.tsx`, `frontend/src/components/Filtros.test.tsx`

**Interfaces:**
- Consumes: `Filtros` da Tarefa 2.
- Produces: `function Filtros({ atuais, erro }: { atuais: FiltrosTipo; erro?: string }): JSX.Element` — um `<form method="get">`, que navega sem JavaScript.

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/components/Filtros.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Filtros } from './Filtros'

describe('Filtros', () => {
  it('tem os cinco filtros da RN-17.3 mais o periodo', () => {
    render(<Filtros atuais={{ de: '2026-08-01', ate: '2026-08-22' }} />)
    expect(screen.getByLabelText('De')).toHaveValue('2026-08-01')
    expect(screen.getByLabelText('Até')).toHaveValue('2026-08-22')
    expect(screen.getByLabelText('Canal')).toBeInTheDocument()
    expect(screen.getByLabelText('Intenção')).toBeInTheDocument()
    expect(screen.getByLabelText('Temperatura')).toBeInTheDocument()
    expect(screen.getByLabelText('Corretor')).toBeInTheDocument()
  })

  it('e um form GET, para funcionar sem JavaScript', () => {
    const { container } = render(<Filtros atuais={{ de: '2026-08-01', ate: '2026-08-22' }} />)
    expect(container.querySelector('form')).toHaveAttribute('method', 'get')
  })

  it('mostra qual filtro o backend recusou', () => {
    render(
      <Filtros
        atuais={{ de: '2026-08-01', ate: '2026-08-22', temperatura: 'MORNA' }}
        erro="temperatura: MORNA nao e um valor conhecido"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('so oferece as temperaturas que existem', () => {
    render(<Filtros atuais={{ de: '2026-08-01', ate: '2026-08-22' }} />)
    const opcoes = Array.from(
      screen.getByLabelText('Temperatura').querySelectorAll('option'),
    ).map((o) => o.textContent)
    expect(opcoes).toEqual(['Todas', 'QUENTE', 'MORNO', 'FRIO'])
  })
})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/components/Filtros.test.tsx`
Expected: FAIL — módulo não encontrado.

- [ ] **Step 3: Implementar**

`frontend/src/components/Filtros.tsx`:

```tsx
import type { Filtros as FiltrosTipo } from '@/lib/metricas'

// Espelham os enums do backend: `Temperatura` em `context/temperatura.py` e
// `Intencao` em `agente/schemas.py`. Uma lista errada aqui produz 422 do
// backend, e nao filtro silenciosamente vazio -- e por isso que a validacao
// mora la e nao aqui.
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
// So `whatsapp` e produzido pelo ingresso real hoje; o canal web e a TEC-124.
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
    <form method="get" aria-label="Filtros do painel">
      {erro && <p role="alert">{erro}</p>}
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
```

- [ ] **Step 4: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/components/Filtros.test.tsx`
Expected: PASS, 4 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Filtros.tsx frontend/src/components/Filtros.test.tsx
git commit -m "feat(TEC-190): os filtros sao estado de URL e funcionam sem JavaScript"
```

---

### Task 6: A página, e o que ela mostra quando a busca falha

**Files:**
- Modify: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/page.test.tsx`, `frontend/src/lib/periodo.ts`, `frontend/src/lib/periodo.test.ts`

**Interfaces:**
- Consumes: tudo das Tarefas 2 a 5.
- Produces: `function periodoPadrao(hoje: Date): { de: string; ate: string }` — os últimos 30 dias; e a página em `/`.

- [ ] **Step 1: Escrever o teste do período que falha**

`frontend/src/lib/periodo.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { periodoPadrao } from './periodo'

describe('periodoPadrao', () => {
  it('sao os ultimos 30 dias, inclusive hoje', () => {
    expect(periodoPadrao(new Date('2026-09-24T12:00:00Z'))).toEqual({
      de: '2026-08-26',
      ate: '2026-09-24',
    })
  })

  it('atravessa a virada de ano sem quebrar', () => {
    expect(periodoPadrao(new Date('2026-01-10T12:00:00Z'))).toEqual({
      de: '2025-12-12',
      ate: '2026-01-10',
    })
  })
})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/lib/periodo.test.ts`
Expected: FAIL — módulo não encontrado.

- [ ] **Step 3: Implementar o período**

`frontend/src/lib/periodo.ts`:

```typescript
/**
 * Os ultimos 30 dias, inclusive hoje, no formato que o backend espera.
 *
 * A aritmetica e em UTC de proposito: quem decide a fronteira do dia e o
 * backend, que usa `settings.fuso_de_envio` (America/Sao_Paulo, o fuso unico
 * da POC). Aqui so se produz a string `YYYY-MM-DD`; interpreta-la e trabalho
 * de la, e fazer a conta em dois fusos diferentes e que produziria divergencia.
 */
export function periodoPadrao(hoje: Date): { de: string; ate: string } {
  const ate = new Date(Date.UTC(hoje.getUTCFullYear(), hoje.getUTCMonth(), hoje.getUTCDate()))
  const de = new Date(ate)
  de.setUTCDate(de.getUTCDate() - 29)
  return { de: de.toISOString().slice(0, 10), ate: ate.toISOString().slice(0, 10) }
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/lib/periodo.test.ts`
Expected: PASS, 2 testes.

- [ ] **Step 5: Escrever o teste da página que falha**

`frontend/src/app/page.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import Pagina from './page'
import { ErroDeMetricas } from '@/lib/metricas'

vi.mock('@/lib/metricas', async () => {
  const real = await vi.importActual<typeof import('@/lib/metricas')>('@/lib/metricas')
  return { ...real, buscarFunil: vi.fn() }
})

const { buscarFunil } = await import('@/lib/metricas')

const FUNIL = {
  etapas: [
    { nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null },
    { nome: 'Agendado', quantidade: null, disponivel: false, conversaoDaAnterior: null },
  ],
  indicadores: { leadsNovos: 320, taxaNoShow: null },
  indisponiveis: ['taxaNoShow'],
}

const VAZIO = {
  etapas: [{ nome: 'Novo', quantidade: 0, disponivel: true, conversaoDaAnterior: null }],
  indicadores: { leadsNovos: 0 },
  indisponiveis: [],
}

describe('Pagina', () => {
  beforeEach(() => vi.mocked(buscarFunil).mockReset())

  it('mostra o funil quando a busca da certo', async () => {
    vi.mocked(buscarFunil).mockResolvedValue(FUNIL)
    render(await Pagina({ searchParams: Promise.resolve({}) }))
    expect(screen.getByText('320')).toBeInTheDocument()
  })

  it('backend fora do ar vira aviso, e nao funil de zeros', async () => {
    vi.mocked(buscarFunil).mockRejectedValue(new ErroDeMetricas(500, 'caiu'))
    render(await Pagina({ searchParams: Promise.resolve({}) }))
    expect(screen.getByRole('alert')).toHaveTextContent(/não foi possível carregar/i)
    expect(screen.queryByLabelText('Funil de leads')).not.toBeInTheDocument()
  })

  it('403 diz que e configuracao, e nao ausencia de dados', async () => {
    vi.mocked(buscarFunil).mockRejectedValue(new ErroDeMetricas(403, 'forbidden'))
    render(await Pagina({ searchParams: Promise.resolve({}) }))
    expect(screen.getByRole('alert')).toHaveTextContent(/token/i)
  })

  it('422 nomeia o filtro recusado no proprio formulario', async () => {
    vi.mocked(buscarFunil).mockRejectedValue(new ErroDeMetricas(422, 'temperatura: MORNA'))
    render(await Pagina({ searchParams: Promise.resolve({ temperatura: 'MORNA' }) }))
    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('periodo legitimamente vazio mostra o funil zerado, e nao o aviso de erro', async () => {
    vi.mocked(buscarFunil).mockResolvedValue(VAZIO)
    render(await Pagina({ searchParams: Promise.resolve({}) }))
    expect(screen.getByLabelText('Funil de leads')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/app/page.test.tsx`
Expected: FAIL — a página ainda é o esqueleto do `create-next-app`.

- [ ] **Step 7: Implementar a página**

`frontend/src/app/page.tsx`:

```tsx
import { buscarFunil, ErroDeMetricas, type Filtros as FiltrosTipo, type Funil as FunilTipo } from '@/lib/metricas'
import { periodoPadrao } from '@/lib/periodo'
import { Funil } from '@/components/Funil'
import { Indicadores } from '@/components/Indicadores'
import { Filtros } from '@/components/Filtros'

type Busca = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

function filtrosDaUrl(busca: Busca): FiltrosTipo {
  const padrao = periodoPadrao(new Date())
  return {
    de: um(busca.de) ?? padrao.de,
    ate: um(busca.ate) ?? padrao.ate,
    canal: um(busca.canal),
    intencao: um(busca.intencao),
    temperatura: um(busca.temperatura),
    corretorId: um(busca.corretorId),
  }
}

/**
 * O aviso depende do status, porque as causas sao diferentes e o conserto
 * tambem: 403 e configuracao do operador (token errado no env do servidor),
 * 422 e filtro invalido que a gerente pode corrigir, e o resto e o backend.
 * Um aviso unico mandaria a gerente procurar o erro dela num problema que
 * nao e dela.
 */
function avisoDe(erro: ErroDeMetricas): string {
  if (erro.status === 403) {
    return 'Não foi possível carregar: o servidor recusou o token de acesso. É configuração do ambiente, não um problema do seu filtro.'
  }
  if (erro.status === 422) {
    return `Não foi possível carregar: um filtro tem valor inválido — ${erro.message}`
  }
  return 'Não foi possível carregar os dados do painel. Os números abaixo não seriam confiáveis, então não são mostrados.'
}

export default async function Pagina({ searchParams }: { searchParams: Promise<Busca> }) {
  const busca = await searchParams
  const filtros = filtrosDaUrl(busca)

  let funil: FunilTipo | null = null
  let aviso: string | null = null

  try {
    funil = await buscarFunil(filtros)
  } catch (erro) {
    // O funil NAO e renderizado quando a busca falha. Um funil de zeros e
    // indistinguivel de um periodo sem lead, e a gerente leria a queda como
    // fato do negocio. Ver o item 1 do Review Focus.
    aviso = erro instanceof ErroDeMetricas ? avisoDe(erro) : 'Não foi possível carregar os dados do painel.'
  }

  return (
    <main>
      <h1>Funil de leads</h1>
      <Filtros atuais={filtros} erro={aviso ?? undefined} />
      {funil ? (
        <>
          <Funil etapas={funil.etapas} />
          <Indicadores indicadores={funil.indicadores} indisponiveis={funil.indisponiveis} />
        </>
      ) : null}
    </main>
  )
}
```

Note que `Filtros` já renderiza `role="alert"` quando recebe `erro`, então a página não precisa de um segundo elemento de alerta.

- [ ] **Step 8: Rodar para ver passar**

Run: `cd frontend && npx vitest run src/app/page.test.tsx`
Expected: PASS, 5 testes.

- [ ] **Step 9: Documentar as variáveis de ambiente**

`frontend/.env.example`:

```
# A base do FastAPI, vista do servidor Next -- nao do navegador.
MOBIA_API_BASE=http://localhost:8000

# O mesmo valor de CATALOGO_ADMIN_TOKEN do backend. NAO e NEXT_PUBLIC_:
# e token de admin total, e prefixa-lo com NEXT_PUBLIC_ o entregaria a
# qualquer navegador que abrisse o painel.
MOBIA_ADMIN_TOKEN=
```

- [ ] **Step 10: Rodar a suíte inteira do front e commitar**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: todos os testes passam; lint limpo; build conclui.

```bash
git add frontend/src/app/page.tsx frontend/src/app/page.test.tsx frontend/src/lib/periodo.ts frontend/src/lib/periodo.test.ts frontend/.env.example
git commit -m "feat(TEC-190): a pagina do painel, que cala em vez de mostrar zeros quando a busca falha"
```

---

### Task 7: Verificação de ponta a ponta contra o backend de verdade

**Files:**
- Create: `frontend/README.md`

**Interfaces:**
- Consumes: o endpoint entregue pelo plano do backend.
- Produces: nada em código — é a verificação manual de que as duas metades se falam.

- [ ] **Step 1: Subir os dois lados**

```bash
cd C:/Projetos/mobIA && docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
CATALOGO_ADMIN_TOKEN=local ./.venv/Scripts/python.exe -m uvicorn mobia.app.main:app --port 8000
```

Noutro terminal:

```bash
cd C:/Projetos/mobIA/frontend
MOBIA_API_BASE=http://localhost:8000 MOBIA_ADMIN_TOKEN=local npm run dev
```

- [ ] **Step 2: Conferir na tela**

Abra `http://localhost:3000`. Confirme, com os olhos:

1. As seis etapas aparecem, e `Agendado` diz "sem fonte de dados" — não `0`.
2. A nota sobre visitas aparece uma vez.
3. Trocar um filtro muda a URL e recarrega os números.
4. `?temperatura=MORNA` produz o aviso que nomeia `MORNA`, e não uma tela de erro genérica.
5. Parar o uvicorn e recarregar produz o aviso de falha — **e nenhum funil**.

- [ ] **Step 3: Escrever o README**

`frontend/README.md` com: como rodar em desenvolvimento, as duas variáveis de ambiente e por que `MOBIA_ADMIN_TOKEN` não é `NEXT_PUBLIC_`, e a nota de que os indicadores de visita ficam nulos até RF-11/RF-12 existirem.

- [ ] **Step 4: Commit**

```bash
git add frontend/README.md
git commit -m "docs(TEC-190): como rodar o painel e por que o token nao e NEXT_PUBLIC"
```

---

## Self-review

**Cobertura da spec.** D9 (front em `frontend/`, token no servidor, `revalidate: 60`, argumento do rate limit) → Tarefas 1, 2 e 6. D1 (`null` nunca vira `0`) → Tarefas 3 e 4, com teste dedicado em cada. Contrato e as duas origens de `conversaoDaAnterior` nula → Tarefa 3, mais a terceira (anterior em zero) que o Review Focus acrescentou. Filtros da RN-17.3 → Tarefa 5. RNF-04/SSR → Tarefa 6 (Server Component). O job de CI → Tarefa 1.

**Refinamento da D9 registrado.** A spec diz "Route Handler como proxy"; este plano usa Server Component com busca no servidor. A propriedade aprovada — token nunca no navegador — é idêntica, e o argumento do rate limit também vale, porque o Data Cache do Next colapsa N navegadores numa chamada por minuto. O que some é um hop e um arquivo. **A spec precisa da emenda correspondente na D9.**

**Consistência de tipos.** `Etapa`, `Funil`, `Filtros`, `Indicadores` e `ErroDeMetricas` são definidos na Tarefa 2 e usados com os mesmos nomes nas Tarefas 3 a 6. `percentual` e `quantidadeLegivel` nascem na Tarefa 3 e são consumidos na 4. `periodoPadrao` nasce e é consumido na 6.

**Review Focus.** Os cinco itens têm teste: 1 e 2 na Tarefa 6 (`page.test.tsx`), 3 na Tarefa 6 (o caso `VAZIO`) e na Tarefa 3 (zero medido contra sem fonte), 4 na Tarefa 3, 5 na Tarefa 5 e na 6.
