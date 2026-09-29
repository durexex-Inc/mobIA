# TEC-338 — Listar, editar e comparar versões de prompt por agente

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-338](https://eduardodurieuxlopes.atlassian.net/browse/TEC-338) — História, Should (MoSCoW), prioridade High. Origem: RN-FE-14.1, RN-FE-14.2, RT-FE-10 (SRS mobIA Frontend v1.0) · TEC-199.

**A história:** *"Como Rafael, administrador da imobiliária, quero editar o prompt de cada agente e comparar versões lado a lado, para entender o que mudou antes de publicar."*

**Só frontend.** Ao contrário da TEC-337 (que descobriu e construiu uma peça de backend faltando), a TEC-199 já cobre tudo que esta tela precisa: listar agentes com a ativa, ler uma versão com texto, listar o histórico paginado, publicar e reverter — todos atrás de `CONFIGURAR_AGENTE` (`src/mobia/api/routes/prompts.py`). Nenhuma rota nova no backend.

## Dependências, conferidas antes de desenhar

TEC-199 (API de prompts) e TEC-312 (visibilidade por papel) — ambas **Feito**. `admin/page.tsx` já tem a linha `{ nome: 'Prompts do agente', card: 'TEC-338' }` sem `href` (D5 do desenho da TEC-340/TEC-312): esta card é quem preenche esse `href`.

## D1 — Dois agentes fixos (`AgenteDoPrompt`), não uma lista arbitrária

`AGENTE` e `INVESTIDOR` são os dois únicos valores do enum do backend (`domain/prompts/modelo.py:19-29`) — não existe cadastro de agente, e não vai existir um nesta tela. A lista da card ("qualificador, consultor etc.") é a partir do enum, sem paginação nem busca: `GET /api/v1/prompts` já devolve os dois de uma vez, cada um com `versao`, `publicadaPor`, `publicadaEm` — exatamente os três dados do primeiro cenário do Gherkin, sem cálculo nenhum do frontend.

## D2 — Rota do agente é o segmento minúsculo do enum, sem tabela de tradução

`/admin/prompts` lista os dois; `/admin/prompts/agente` e `/admin/prompts/investidor` são o detalhe de cada um — minúsculo para bater com o padrão de URL do resto do painel (`/admin/imoveis`, `/admin/corretores`), maiúsculo só na chamada ao backend (`AgenteDoPrompt` são strings maiúsculas). A tradução é um `.toUpperCase()` guardado por um `Set` dos dois valores válidos — segmento fora disso (`/admin/prompts/qualquercoisa`) é `notFound()`, não uma rota nova por agente.

## D3 — Comparar versões é navegação por `searchParams`, não fetch do cliente

A card pede diff "entre quaisquer duas versões", mas o `diff` que a TEC-199 grava em cada `VersaoDePrompt` é só contra a versão imediatamente anterior (`domain/prompts/modelo.py::diff_entre`, chamado na publicação) — não serve para comparar a 3 com a 7 direto.

Em vez de buscar o texto das duas versões escolhidas com um fetch de cliente (que exigiria abrir `GET /prompts/{agente}/versoes/{numero}` no `/bff/*`), a página de detalhe é um Server Component que lê `de`/`para` de `searchParams` (default: a ativa e a anterior a ela, ou só a ativa quando não há segunda), busca as DUAS versões com `chamarApi` direto do servidor — mesmo padrão de `buscarConfiguracao`/`buscarImoveis` — e passa os dois textos como prop para um Client Component de comparação. Trocar qual par comparar é um `<Link href="?de=6&para=7">`, recarregando a página no servidor; não é estado de cliente. **Não precisa de nenhuma rota nova no `/bff/*` para leitura** — só a publicação (D5) é mutação de cliente.

## D4 — O diff lado a lado é o `DiffEditor` do próprio Monaco, sem segunda biblioteca

`@monaco-editor/react` expõe `<DiffEditor original={...} modified={...} />`, que já renderiza lado a lado com o mesmo realce de sintaxe do editor de edição — usar esse componente para a comparação evita instalar uma biblioteca de diff separada (`jsdiff`, `react-diff-viewer`) só para recalcular o que o Monaco já sabe fazer. O realce de `{assistente}`/`{tom}` (RN-FE-14.1) é uma linguagem Monarch mínima registrada uma vez (`monaco.languages.register` + `setMonarchTokensProvider`, regex `\{[A-Za-z_]+\}`) e usada tanto no editor de edição quanto nos dois lados do diff.

## D5 — Publicar é a única mutação, e vai pelo `/bff/*` como as outras telas

`POST /api/v1/prompts/{agente}/versoes` com `{texto}` é a única escrita desta tela — sem `rollback` (fora de escopo, D7) e sem checagem de concorrência tipo `seVersao` da TEC-337 (o Gherkin desta card não tem cenário de edição concorrente; a TEC-337 tinha o terceiro cenário exigindo isso, esta não pede). Entrada nova em `ROTAS_PERMITIDAS` (`lib/servidor/bff.ts`): `{ metodo: 'POST', padrao: ['api', 'v1', 'prompts', '*', 'versoes'] }`. Erro 422 (`ModeloInvalido`) é mostrado como veio do backend, mesmo padrão D3 da TEC-337/TEC-333/TEC-334 — sem duplicar a validação de marcador/tamanho em TypeScript, só o contador de caracteres usa `limites.maximoDeCaracteres` (de `GET /agente`) para um indicador visual, não para bloquear o envio.

Publicar com sucesso não precisa de `key={...}` para descartar edição em curso (como a TEC-337): o editor está numa rota de DETALHE que se recarrega inteira (`router.refresh()`) após o `201`, trazendo a nova `ativa` — o mesmo efeito, por já ser uma página cujo conteúdo inicial é sempre a versão vigente no momento do carregamento.

## D6 — Monaco carrega só nesta rota, via `next/dynamic` com `ssr: false`

RT-FE-10, e o quarto cenário do Gherkin: "quando a lista de leads é carregada, o código do editor de prompts não é baixado." Nenhum componente fora de `app/(painel)/admin/prompts/**` importa `@monaco-editor/react` — o Next.js só inclui o pacote no chunk de uma rota quando algo *naquela* árvore de módulos o importa, então isolar o import a `EditorDePrompt.tsx`/`DiffDePrompt.tsx` (ambos só usados pela página de detalhe, ambos com `dynamic(() => import(...), { ssr: false })` porque o Monaco não roda em servidor) já é suficiente — sem lazy-loading adicional além do que o bundler faz por padrão a partir disso.

**Verificação, não teste automatizado novo:** depois do `npm run build`, o relatório de rotas do Next (`First Load JS` por rota) mostra o tamanho de `/admin/prompts/[agente]` bem acima das rotas vizinhas e o de `/leads` inalterado em relação ao commit anterior — é essa comparação, manual, que fecha o quarto cenário; não existe hoje um script que meça bundle por rota (o `verificar-bundle.mjs` procura segredo vazado, não tamanho) e escrever um para uma tela só seria complexidade que o Gherkin não pede.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Ver a versão ativa de cada agente | exercitado — `GET /api/v1/prompts` (D1), sem cálculo do frontend |
| Comparar duas versões | exercitado — `searchParams` + `DiffEditor` (D3, D4) |
| Publicar nova versão | exercitado — `POST /versoes` pelo `/bff/*` (D5) |
| Editor não pesa nas outras telas | exercitado — import isolado à rota, `next/dynamic` (D6) |

## D7 — Fora de escopo

- **Reverter (`POST /rollback`) e o histórico de ativações (`GET /historico`)**: a API já os tem, mas a lista de regras de negócio da própria card fala só em "versão ativa, autor, data" (que `GET /prompts` e `GET /agente` já trazem) e "editor com diff" — nenhum cenário do Gherkin exercita reverter. Adicionar um botão "reverter" sem um cenário que peça é a mesma armadilha que a TEC-337 evitou com os domínios do widget.
- **Checagem de concorrência (`seVersao`, padrão D1 da TEC-337)**: sem cenário no Gherkin desta card. Duas publicações verdadeiramente simultâneas ainda colidem no `409` que a TEC-199 já responde (choque de número de versão) — só não há aviso "alguém editou antes de você" no meio da digitação.
- **Traduzir `{assistente}`/`{tom}` para nomes amigáveis na tela**: a card fala em "realce", não em ocultar a sintaxe; o texto continua sendo o modelo cru que o backend valida.
