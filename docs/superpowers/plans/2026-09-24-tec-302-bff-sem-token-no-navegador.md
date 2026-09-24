# TEC-302 — plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-24-tec-302-bff-sem-token-no-navegador-design.md`
**Branch:** `feat/tec-302-bff-sem-token-no-navegador`

Tudo acontece em `frontend/`. Nenhum arquivo Python é tocado, então os três gates estáticos de Python não têm o que dizer sobre esta branch — os gates que importam aqui são os três do job `Frontend` (`npm run lint`, `npm test`, `npm run build`), mais a varredura nova.

## Nota de ambiente: o Node desta máquina é velho demais para a suíte

`.nvmrc` pede Node 24; a máquina tem 20.19.6. Com o 20 o `vitest` **não roda um teste sequer** — morre com `TypeError: webidl.util.markAsUncloneable is not a function`, que é o `jsdom` novo exigindo Node ≥ 22. Não é defeito da suíte e não adianta reexecutar.

Para verificar local sem mexer na máquina, um Node 24 portátil resolve:

```bash
export PATH="<scratchpad>/node/node-v24.21.0-win-x64:$PATH"
node --version   # v24.21.0
```

Medido em 24/09/2026, antes de qualquer mudança desta branch: **7 arquivos, 39 testes, ~59 s**; `npm run lint` e `npm run build` limpos. É o baseline contra o qual as fases abaixo se comparam.

## Fase 1 — o ponto único e o gate de build

1. `npm install server-only` — dependência de produção. A razão de instalar um pacote cujo conteúdo o Next não usa está na D2: sem ele o passo `Running TypeScript` do `next build` reprova com `Cannot find module 'server-only'`.
2. `frontend/src/lib/servidor/api.ts`, com `import 'server-only'` na primeira linha: lê `MOBIA_API_BASE` e `MOBIA_ADMIN_TOKEN`, monta a URL e a chamada ao FastAPI. É o único lugar do projeto que lê o token.
3. Alias de `server-only` para um stub vazio em `vitest.config.ts`, com o porquê escrito lá (fora do bundler do Next o pacote lança).
4. `metricas.ts` passa a chamar `api.ts` e perde a leitura de env e a montagem de header. **`buscarFunil` e `ErroDeMetricas` não mudam de assinatura nem de comportamento.**

**Verificação:** `npm test` — os 39 de antes continuam passando, `metricas.test.ts` incluído e sem edição. Ele é o detector de a migração ter mudado contrato; se precisar mudá-lo para passar, a migração está errada, não o teste.

## Fase 2 — a decisão pura

`frontend/src/lib/servidor/bff.ts`, sem env e sem rede. Três decisões independentes e testáveis isoladamente:

- **`rotaPermitida(metodo, segmentos)`** — valida cada segmento antes de qualquer casamento (vazio, `.`, `..`, ou contendo `/`, `\`, `\0` → recusa), casa contra a tabela por segmento com `*` valendo um segmento, e devolve o caminho **remontado a partir dos segmentos validados**. Nunca a string da URL de entrada.
- **`origemAceita(origin, proprioOrigin, metodo)`** — as quatro linhas da tabela da D5.
- **`idDeRequisicao(entrada)`** — devolve a entrada quando ela casa `^[A-Za-z0-9._:-]{1,200}$`, senão um `crypto.randomUUID()`.

**Verificação:** `bff.test.ts` cobre o que a seção de testes do desenho lista. Estes são testes de função pura — rodam em milissegundos e não precisam do runtime do Next.

## Fase 3 — o handler

`frontend/src/app/bff/[...rota]/route.ts`. Fino de propósito: lê a requisição, chama as três funções da fase 2, e em caso de aprovação delega a `api.ts` com `cache: 'no-store'` (D7). Exporta `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE` — os métodos que não exporta o Next responde 405 sozinho, mas exportá-los é o que faz a recusa de allowlist e a de `Origin` valerem para eles em vez de o Next responder antes.

O contexto é tipado com `RouteContext<'/bff/[...rota]'>` e `params` é aguardado — os dois são o convencionado no Next 16, e os tipos saem do `next typegen` que o `next build` roda.

**Verificação:** `route.test.ts`, com `fetch` dublado. A asserção que mais importa nos cenários 2 e 3 do Gherkin não é o status: é **`expect(fetchFalso).not.toHaveBeenCalled()`** — "e nada é repassado à API".

## Fase 4 — a varredura do bundle

`frontend/scripts/verificar-bundle.mjs` e o script npm `verificar:bundle`. Anda `.next/static` inteiro procurando o valor de `MOBIA_ADMIN_TOKEN`; reprova nomeando o arquivo. Reprova também quando a variável não está setada, ou quando tem menos de 16 caracteres — as duas razões estão na D3.

No CI, o passo `Build` ganha `MOBIA_ADMIN_TOKEN` com a sentinela, e um passo novo logo depois roda a varredura.

**Verificação, e ela tem duas metades:**

1. `npm run build && npm run verificar:bundle` com a sentinela → passa.
2. **A varredura precisa ser vista reprovando.** Uma checagem que nunca se viu falhar não é evidência de nada: trocar temporariamente a variável para `NEXT_PUBLIC_MOBIA_ADMIN_TOKEN`, reconstruir, confirmar que o script acha a sentinela e nomeia o arquivo, desfazer. O resultado das duas metades vai no comentário da card.

## Fase 5 — a prosa que a branch tornou falsa

`frontend/README.md` descreve as duas variáveis e afirma que a página "é um Server Component justamente por isso". Continua verdade, mas fica incompleto: agora há um segundo caminho, um gate de build e uma variável nova (`MOBIA_ORIGEM_DO_PAINEL`). Atualizar junto, pela regra de que comentário não mente.

E rodar a listagem, que é gate de leitura e não de CI:

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Ela aponta `PROSA` e `NOMEIA` sobre `.md` versionados — e o `README.md` do frontend e o desenho da TEC-190 citam decisões que esta branch emenda (a D9 e a emenda dela).

## Ordem de verificação, no fim

Do mais barato para o mais caro, com o Node 24 no `PATH`:

```bash
cd frontend
npm run lint
npm test
npm run build
MOBIA_ADMIN_TOKEN=<sentinela> npm run build && MOBIA_ADMIN_TOKEN=<sentinela> npm run verificar:bundle
```

A suíte Python não é rodada nesta branch, e a razão é que nenhum arquivo sob `src`, `tests`, `alembic`, `evals` ou `scripts` é tocado. Se algum for, a regra do `CLAUDE.md` volta a valer inteira: uma execução de `pytest -n 8 --dist loadfile`, com o hash guardado junto do resultado.
