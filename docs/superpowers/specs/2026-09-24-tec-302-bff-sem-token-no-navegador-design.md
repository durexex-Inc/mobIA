# TEC-302 — Tirar o token de API do navegador com a camada BFF

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-302](https://eduardodurieuxlopes.atlassian.net/browse/TEC-302) — épico TEC-301
**Branch:** `feat/tec-302-bff-sem-token-no-navegador`
**Origem:** RT-FE-01, RNF-FE-08, RNF-FE-10, §6.1 (SRS mobIA Frontend v1.0)

## A auditoria da TEC-190 vem primeiro, porque ela muda o que a card entrega

A card manda auditar o código da TEC-190 e o resultado da auditoria é o eixo deste desenho.

**O token já não chega ao navegador hoje.** `src/app/page.tsx` é Server Component; `buscarFunil` lê `process.env.MOBIA_ADMIN_TOKEN` em código de servidor; o `<form method="get">` de `Filtros.tsx` navega em vez de chamar `fetch`, então não existe uma linha de código de cliente que fale com a API. Não há nenhuma `NEXT_PUBLIC_*` no projeto. **O primeiro cenário do Gherkin da card já passa antes desta branch** — e isso precisa ser dito, porque o título da card ("Tirar o token de API do navegador") afirma que ele está lá.

**O que falta não é a propriedade: é o que a sustenta.** Ela vale por acidente de onde o código está importado. Pôr `'use client'` no topo de `page.tsx`, ou importar `metricas.ts` de um componente de cliente, ou renomear a variável para `NEXT_PUBLIC_MOBIA_ADMIN_TOKEN` — nenhum dos três reprova em gate nenhum hoje. `npm run lint`, `npm test` e `npm run build` passam com o token no bundle.

O que de fato não existe:

| a card pede | estado antes desta branch |
| --- | --- |
| token só no servidor | **vale**, sem nada que o mantenha |
| nenhuma `NEXT_PUBLIC_*` com segredo | **vale**, sem nada que o mantenha |
| proxy `/bff/*` com allowlist | **não existe** |
| recusa por `Origin` | **não existe** |
| propagação de `X-Request-Id` | **não existe**, nem no front nem no backend |

Então a card compra três coisas: um **gate** que transforma a propriedade acidental em propriedade verificada, o **proxy** que os cenários 2 e 3 exercitam, e um **ponto único** por onde as duas metades passam.

## D1 — "migrar o painel para esse caminho" é migrar para o ponto único, não ganhar um salto de HTTP

A regra de negócio da card diz, por extenso: *"Toda chamada autenticada sai de Server Components **ou** de Route Handlers `/bff/*`"*. Server Component é caminho permitido pela própria card. A leitura alternativa — o Server Component passa a chamar `/bff/*`, que chama o FastAPI — foi pesada e **recusada**, por três razões:

1. **Perde o cache que a TEC-190 documentou.** `fetch(..., { next: { revalidate: 60 } })` põe a resposta no Data Cache, e é isso que faz N navegadores com o painel aberto virarem **uma** chamada por minuto ao FastAPI — o argumento inteiro da D9 da TEC-190 contra o limite de 100 req/min por IP, que vê o IP do servidor Next e não o de cada navegador. Route Handler não é cacheado por padrão, e a chamada do SC para o próprio handler seria outra unidade de cache.
2. **Custa um round-trip HTTP do processo para ele mesmo** em toda renderização de página.
3. **É auto-fetch durante SSR**, que é frágil por natureza.

**O que a migração então entrega.** Hoje `metricas.ts` é uma porta privada para o FastAPI: monta a URL, lê o token e escreve o header por conta própria. Depois desta card existe **uma** porta (`lib/servidor/api.ts`), e tanto `metricas.ts` quanto o handler `/bff/*` passam por ela. Migrar é o painel deixar de ter caminho próprio, não o painel ganhar um salto.

**Isto diverge da leitura literal da card** e vai no comentário dela.

## D2 — `server-only` é o gate, e ele é de build

`import 'server-only'` no módulo que lê o token faz o **build reprovar** se aquele módulo for arrastado para um componente de cliente. É o que converte "vale hoje" em "não dá para quebrar sem o CI perceber".

Duas consequências mecânicas, as duas medidas na implementação:

- **O pacote é instalado, apesar de o Next resolvê-lo internamente.** A documentação do Next 16 (`02-guides/data-security.md`) diz que o conteúdo do pacote npm não é usado no bundle — mas o TypeScript do passo `Running TypeScript` do `next build` precisa da declaração do módulo, e sem o pacote instalado o build reprova com `Cannot find module 'server-only'`.
- **O `vitest` precisa de alias para ele.** O `exports` do pacote manda a condição `react-server` para um arquivo vazio e **todo o resto para um arquivo que lança**. Fora do bundler do Next — que é onde o vitest roda — importar `server-only` lança. O alias para um stub vazio fica em `vitest.config.ts`, com a razão escrita lá.

**O alias não enfraquece o gate, porque o gate nunca foi o vitest: é o `npm run build`**, que já roda no job `Frontend` do CI.

## D3 — o cenário 1 do Gherkin vira uma varredura do bundle, e ela pega um erro que o `server-only` não pega

Os dois gates cobrem enganos **diferentes**, e é por isso que são dois:

| engano | o que acontece | quem pega |
| --- | --- | --- |
| importar o módulo do token de um componente de cliente | build reprova | `server-only` |
| renomear para `NEXT_PUBLIC_MOBIA_ADMIN_TOKEN` | valor **literal** embutido no bundle de cliente | varredura |
| passar o token como prop de Server para Client Component | vai no payload RSC do HTML | **nenhum dos dois** — ver L2 |

A varredura é `frontend/scripts/verificar-bundle.mjs`: o CI constrói com `MOBIA_ADMIN_TOKEN` valendo uma sentinela, e o script procura a sentinela em tudo que está sob `.next/static` — que é exatamente "o código estático do build" do Gherkin, e exatamente o que o navegador baixa.

Três decisões pequenas dentro dela, cada uma contra um modo de a checagem apodrecer:

- **Ela lê a mesma `MOBIA_ADMIN_TOKEN` que o build leu**, e não uma segunda variável. Duas variáveis para manter em sincronia é a forma de a checagem passar a testar outra coisa.
- **Sem a variável, ela reprova** em vez de pular. Checagem que pula em silêncio é checagem que ninguém nota ter parado de rodar.
- **A sentinela precisa de 16 caracteres no mínimo.** Uma sentinela curta acharia a si mesma dentro de qualquer identificador minificado, e o falso positivo treina quem lê a ignorar.

**`.next/server` fica fora da varredura de propósito.** Aquilo é código de servidor, onde o token pode aparecer sem que nada esteja errado; incluí-lo produziria ruído sobre a única pergunta que importa, que é o que o navegador recebe.

## D4 — a allowlist casa por SEGMENTO, e é isso que mata o traversal

A tabela é `{ metodo, padrao }`, e o padrão é uma lista de segmentos onde `*` casa **exatamente um** segmento. Hoje ela tem **uma** entrada: `GET /api/v1/metricas/funil`. É tudo de que o épico precisa, e uma allowlist de uma linha é honesta.

**Casar por segmento e não por string não é estilo.** O `[...rota]` do Next entrega os segmentos já separados e já decodificados, e é daí que saem os ataques:

- `..` e `.` como segmento subiriam de diretório assim que a lista fosse unida com `/`;
- `%2F` dentro de um segmento chega decodificado como `/` e contrabandearia um separador na hora da junção;
- barra invertida e byte nulo pela mesma razão.

Então o caminho que vai para o FastAPI é **remontado a partir dos segmentos validados**, nunca copiado da URL de entrada. Segmento vazio, `.`, `..`, ou contendo `/`, `\` ou `\0`, recusa antes de qualquer casamento.

**A alternativa tentadora é `startsWith`, e ela é o furo clássico**: `/api/v1/metricas/funil` como prefixo libera `/api/v1/metricas/funil/../../corretores`. Fica escrito no módulo para ninguém "simplificar" de volta.

**`*` existe apesar de nenhuma rota de hoje precisar dele.** Não é generalidade especulativa: sem ele, a próxima rota parametrizada do épico (TEC-309, TEC-312) chega com a tentação do `startsWith`, e a defesa acima se perde na primeira pressa. O custo é uma linha de casamento e dois testes.

**Rota fora da allowlist responde 404, e não 403.** O Gherkin não fixa o status deste cenário (fixa o do `Origin`), então a escolha é nossa: 403 afirma "existe e você não pode", 404 afirma "aqui não há essa rota" — que é a verdade, e que não confirma a quem sonda quais rotas o FastAPI tem.

## D5 — a regra de `Origin` é assimétrica entre método seguro e mutação, e tem de ser

| `Origin` | método | decisão |
| --- | --- | --- |
| presente e diferente do próprio | qualquer | **403** |
| ausente | `POST`/`PUT`/`PATCH`/`DELETE` | **403** |
| ausente | `GET`/`HEAD` | passa |
| presente e igual ao próprio | qualquer | passa |

**A assimetria não é frouxidão, é como o navegador se comporta.** Em requisição de mesma origem com método seguro o navegador **não manda `Origin`** — navegação simples, prefetch e `<img>` chegariam sem ele. Exigir `Origin` no `GET` quebraria o consumidor legítimo. Em `fetch` de mesma origem com método inseguro o navegador **manda**, e é por isso que ausência em mutação pode ser recusada sem custo.

E a letra da card fecha com isso: ela diz "requisições com `Origin` **diferente** do próprio domínio", e ausente não é diferente.

**Qual é "o próprio domínio".** `MOBIA_ORIGEM_DO_PAINEL` quando configurada, senão a origem da própria requisição. A variável existe porque atrás de proxy o `Host` que o Next vê pode ser `localhost:3000` enquanto o navegador manda `Origin: https://painel.exemplo.com` — e aí a comparação recusaria toda mutação legítima. Sem proxy, a origem da requisição é o valor certo e não há o que configurar.

**Isto é defesa de CSRF, não autenticação, e a diferença importa** — ver a L1.

## D6 — o `X-Request-Id` NÃO viaja no fetch cacheado, e essa é a decisão menos óbvia daqui

A documentação do Next 16 (`03-api-reference/04-functions/fetch.md`) diz, sobre o cache de dados:

> A request matches on its URL, method, **headers**, and body, so requests that differ in any of these are cached separately.

**Header entra na chave.** Um `X-Request-Id` novo por requisição no fetch do Server Component daria **uma entrada de cache por acesso** — taxa de acerto zero, e cada navegador com o painel aberto voltando a ser uma chamada ao FastAPI por carregamento. Some a propriedade que a D9 da TEC-190 usou para justificar que o limite de 100 req/min por IP não derruba o painel.

E o modo de falhar é o pior que existe: **nada reprova**. Nenhum teste fica vermelho, nenhum log reclama; o painel continua correto e o FastAPI leva uma enxurrada que só aparece quando cem gerentes abrirem a tela.

Então:

- **caminho `/bff/*` (sem cache):** carrega o `X-Request-Id`, propagado quando o de entrada tem forma aceitável e gerado com `crypto.randomUUID()` quando não tem. Devolvido também na resposta, para quem estiver diagnosticando poder citá-lo.
- **caminho do Server Component (com `revalidate: 60`):** **não** carrega. A chamada do painel ao FastAPI é, por construção, não correlacionável por id de requisição.

Aceitar um `X-Request-Id` de entrada sem olhar seria envenenar log alheio com um valor de entrada não confiável: a forma aceita é de 1 a 200 caracteres em `[A-Za-z0-9._:-]`, e qualquer outra coisa é substituída por um id novo em vez de recusada — o cliente não perde a requisição por causa do header de diagnóstico dele.

## D7 — o proxy nunca cacheia, e isso é sobre a card seguinte

`cache: 'no-store'` na chamada de saída do handler. Route Handler já não cacheia por padrão; a declaração é explícita porque o motivo não é performance: **no dia em que o OIDC existir (TEC-309), um cache compartilhado indexado só pela URL serviria a resposta de um usuário para outro.** Escrever isso agora é mais barato que descobrir depois.

## D8 — o proxy não tem consumidor de cliente nesta card, e isso fica escrito

O painel é `<form method="get">` mais Server Component: **nenhuma linha de código de cliente chama `/bff/*` depois desta branch.** O proxy nasce exercitado por teste, não pelo painel.

Inventar um componente de cliente só para dar consumidor a ele foi recusado — é a mesma classe de defeito que o `CLAUDE.md` nomeia sobre critério de aceite que inventa a entidade que falta para se auto-satisfazer. O que a card diz sobre isto ela já diz: *"destrava o login (OIDC) deste épico"*. O proxy é fundação, e fundação sem consumidor no dia em que é feita é o normal dela.

## Arquivos

```
frontend/src/lib/servidor/api.ts          # 'server-only': env, token, chamada ao FastAPI
frontend/src/lib/servidor/bff.ts          # decisao PURA: allowlist, origem, request-id
frontend/src/app/bff/[...rota]/route.ts   # adaptador fino: Request -> decidir -> chamar
frontend/scripts/verificar-bundle.mjs     # varredura da sentinela em .next/static
```

`bff.ts` não lê ambiente e não faz rede: recebe o que precisa e devolve a decisão. É o que permite testar allowlist, `Origin` e traversal sem subir o runtime do Next — e espelha a separação que o lado Python já faz entre `domain/metricas/filtros.py` e `api/routes/metricas.py`.

`metricas.ts` perde a leitura de env e a montagem de header, e passa a chamar `api.ts`. O contrato dele — `buscarFunil`, `ErroDeMetricas`, o tratamento das duas formas de `detail` do FastAPI — não muda, e os testes existentes continuam valendo.

## Testes

- **`bff.test.ts`** — a allowlist (rota conhecida passa; método errado na rota certa recusa; rota desconhecida recusa); o traversal (`..`, `.`, segmento vazio, `%2F` decodificado, `\`, byte nulo); `*` casando um segmento e **não** casando dois; as quatro linhas da tabela de `Origin`; a forma do `X-Request-Id` (aceito, substituído quando malformado, substituído quando longo demais).
- **`route.test.ts`** — o handler de ponta a ponta com `fetch` dublado: 403 de origem estrangeira **sem chamar o FastAPI** (que é a segunda metade do cenário 2 do Gherkin, e a que de fato importa), 404 fora da allowlist idem, e o caminho feliz repassando corpo, status e `X-Request-Id`.
- **`api.test.ts`** — o token vai no header, a base vem do env, e a chamada do painel **não** leva `X-Request-Id` (a D6 vira asserção, senão ela se perde na primeira refatoração).
- **`metricas.test.ts`** — continua como está. Se ele quebrar, a migração da D1 mudou contrato, que é o que ele existe para detectar.
- **Varredura do bundle** — passo novo no job `Frontend` do CI, depois do `Build`.

## Emendas ao SRS

Nenhuma. A `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` é o SRS do agente; o contrato que esta card toca é o do **SRS mobIA Frontend v1.0**, que a card cita e que **não está versionado neste repo** — ver a L3.

## Lacunas declaradas

- **L1 — o `/bff/*` não autentica ninguém, e o painel também não.** A checagem de `Origin` é defesa de CSRF: ela vale porque o navegador é quem escreve o header. `curl` não manda `Origin`, e pela D5 um `GET` sem `Origin` passa — então quem alcança o servidor Next lê o funil em JSON. **Não é regressão**: hoje esse mesmo alguém já lê o funil pedindo o HTML do painel, que também não autentica. O que muda é a conveniência, de raspar HTML para receber JSON. O que contém o estrago é a allowlist de uma entrada: uma rota de leitura agregada, cujo próprio router no backend registra que *"não há dado pessoal de lead na resposta — só contagens e médias"*. **Fecha na TEC-309.** Até lá o servidor Next não pode ficar exposto na internet.
  - **Nota (TEC-309, 26/09/2026):** fechada. O painel e o `/bff/*` passaram a exigir sessão (`exigirSessao` e `401` sem ela), e cada chamada leva o JWT de quem está logado. Ver `docs/superpowers/specs/2026-09-26-tec-309-login-do-painel-design.md`.
- **L2 — nenhum gate pega o token passado como prop para componente de cliente.** Ele iria no payload RSC do HTML, que não é arquivo estático e por isso escapa da varredura da D3, e não dispara o `server-only`, porque o módulo continua sendo importado só do servidor. Pegá-lo exige renderizar a página e varrer a saída, que é infraestrutura de teste que este projeto ainda não tem.
- **L3 — o SRS do frontend não está no repo.** A card cita RT-FE-01, RNF-FE-08, RNF-FE-10 e §6.1 do "SRS mobIA Frontend v1.0", e `docs/srs/` só tem o do agente. As regras foram lidas do texto da card, que é a fonte de requisitos; se aquele documento existir noutro lugar, este desenho não foi conferido contra ele.
- **L4 — propagar o `X-Request-Id` não correlaciona nada ainda.** O FastAPI **não lê** esse header em lugar nenhum: `correlation_id`, em `app/logging.py`, é um `ContextVar` que o webhook do WhatsApp e o widget preenchem com um UUID próprio, e a rota de métricas nem isso faz. O header sai do BFF e é descartado na entrada. A obrigação que a card escreve é a de propagar, e ela é cumprida; **o que não existe é a ponta que recebe** — e é card de backend, pequena.
