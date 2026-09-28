# TEC-318 — Abrir a lista de leads a partir de uma etapa do funil

**Card:** [TEC-318](https://eduardodurieuxlopes.atlassian.net/browse/TEC-318) — épico TEC-303
**Branch:** `feat/tec-318-abrir-leads-da-etapa`
**Relaciona-se a:** TEC-190/367/376 (as seis etapas e a acumulação), TEC-192/195/321/322 (a lista de leads)

## A dependência `[CONFIRMAR]` da card, resolvida

A card, escrita em 24/09/2026, marcava como bloqueio: "o contrato atual de `GET /api/v1/leads` não tem filtro por período nem por etapa do funil; é preciso estender o contrato antes desta história." Investigado em 28/09/2026: **continua verdadeiro**. `GET /api/v1/leads` aceita `busca`, `status`, `temperatura`, `canal`, `corretorId`, `limite`, `cursor`, `ordenar` — sem `de`/`ate` nem `etapa`. E a etapa do funil (`domain/metricas/repositorio.py::contar_etapas`) é **contagem pura**: um `UNION` que só produz um `COUNT`, nunca lista as linhas. Esta card entrega os dois: o contrato novo e a lógica que faltava.

## D1 — A "lista de leads da etapa X" é a MESMA acumulação de `contar_etapas`, só que devolvendo linhas

`contar_etapas` já monta, para cada etapa, o conjunto acumulado ("esta etapa OU uma posterior", TEC-367 D4) como uma lista de `Select` — os `cruas` — e faz `UNION` delas para contar. Duplicar essa lógica numa consulta nova seria o defeito que este repo evita sistematicamente: duas cópias da mesma regra de negócio que podem divergir.

Em vez disso, `metricas/repositorio.py` extrai as seis condições cruas para uma função própria (`_condicoes_das_etapas`), que tanto `contar_etapas` quanto duas funções novas passam a chamar:

- `selecionar_coorte(recorte)` — os pares `(channel, conversation_key)` da coorte, sem etapa nenhuma (o `_coorte` que já existia, exposto).
- `selecionar_etapa(recorte, etapa)` — os pares que alcançaram esta etapa OU uma posterior (a mesma acumulação, devolvendo o `UNION` em vez do `COUNT`).

As duas devolvem um `Select` sem executar — quem as chama decide se conta, lista, ou junta com outra coisa.

## D2 — `GET /api/v1/leads` ganha `de`, `ate`, `intencao` e `etapa`, e não um dataclass novo

Diferente da lista de leads em si (que tem seu próprio `Filtro`/`montar_filtro` em `domain/leads/consulta.py`), o recorte do funil já tem forma própria e testada: `Recorte`/`montar_recorte` (`domain/metricas/filtros.py`). A rota `GET /api/v1/metricas/funil` já os usa direto, sem passar por um dataclass de leads. `GET /api/v1/leads` faz o mesmo: quando `etapa`, `intencao`, `de` ou `ate` vêm na query, a rota chama o MESMO `montar_recorte` (mesma validação de período de 12 meses, mesmo vocabulário de intenção/temperatura) e, com o resultado, chama `selecionar_etapa` (se `etapa` veio) ou `selecionar_coorte` (só período/filtros, sem etapa). O resultado (`Select | None`) vira `coorte_do_funil`, um parâmetro novo e opcional de `listar_leads`/`_consulta`, que faz um INNER JOIN contra `base` quando presente.

**Isto reaproveita a validação inteira do funil de graça**: o mesmo teto de 12 meses (TEC-316), o mesmo vocabulário de intenção/temperatura, a mesma mensagem de erro. Duplicar essa validação em `leads/consulta.py` teria sido a segunda cópia que a D1 evita.

**`etapa`/`intencao` exigem `de`+`ate` junto — 422 se faltar.** "Quem alcançou a etapa" só faz sentido dentro de uma coorte com período; um `etapa=Recomendado` solto não tem o que responder.

**`canal`/`temperatura` continuam filtrando `base` diretamente, como já faziam** — redundante com o que `selecionar_etapa`/`selecionar_coorte` já embutem via `Recorte`, mas inofensivo (mesmo predicado, duas vezes) e sem mudança de comportamento para quem já usa esses dois filtros hoje sem período nenhum.

## D3 — A etapa sem fonte não é navegável, mesmo sendo inatingível hoje

`disponivel` é `True` nas seis etapas desde a TEC-376 (`calculo.py::montar_funil`, D8 daquele desenho) — não há caminho de produção que produza `disponivel: false` hoje. O segundo cenário do Gherkin ("etapa sem fonte não é navegável") é, portanto, **não exercitável em produção agora**, no mesmo sentido que a Emenda E-01 da RN-17.1 já declarou para outro critério. A checagem entra mesmo assim (`etapa.disponivel` decide se a etapa vira link) porque é barata, está no Gherkin, e volta a valer no dia em que uma etapa nova nascer sem fonte.

## D4 — `Funil.tsx`: o `<li>` inteiro vira link, com `display: contents` no wrapper

O layout de `.funil-etapa` é CSS Grid, com `grid-area` nos filhos DIRETOS do `<li>`. Envolver esses filhos num `<a>` comum quebraria o grid — o `<a>` viraria o único item de grid, e os `grid-area` dos `<span>`/`<div>` internos parariam de valer. `display: contents` no `<a>` (`.funil-etapa-link`) resolve isso: o wrapper não gera caixa própria, e os filhos continuam participando do grid do `<li>` como se o `<a>` não existisse — só que cliques em qualquer um deles ainda navegam, porque eles continuam DENTRO do `<a>` no DOM.

**Sem `aria-label` no `<a>`**, pela mesma razão que o comentário de `Funil.tsx` já registra para o `<span>` de conversão: um `aria-label` fixo apagaria "Coorte incompleta" para quem usa leitor de tela. Em vez disso, um `<span className="visually-hidden">Ver leads da etapa {nome}. </span>` como primeiro filho do link dá o contexto sem esconder o resto.

## D5 — `urlDaEtapa` não traduz nomes: os filtros do funil e os da rota de leads são os MESMOS

`Funil` recebe a prop `filtros: Filtros` (o mesmo tipo de `lib/metricas.ts`, já usado por `page.tsx`) e monta `/leads?de=...&ate=...&canal=...&intencao=...&temperatura=...&etapa=<nome>` — os nomes dos parâmetros são idênticos aos que a D2 acrescentou a `GET /api/v1/leads`, então não há mapa de tradução para manter sincronizado.

## D6 — Dentro de `/leads`, a origem do funil sobrevive à paginação e à ordenação, não à busca nem aos filtros manuais

Um novo tipo, `OrigemDoFunil` (`lib/leads.ts`), guarda `de`/`ate`/`intencao`/`etapa` lidos da URL (`origemDoFunilDaUrl`). `urlDaLista` passa a incluí-los quando presentes. Isso é **obrigatório para paginação e ordenação**: sem isso, clicar "Próxima página" ou reordenar por score enquanto se vê a etapa "Recomendado" devolveria silenciosamente a lista INTEIRA reordenada/paginada — não é preferência de UX, é uma consulta diferente da que a tela diz estar mostrando. `PaginacaoDeLeads` já herda isso de graça (spread do `estado`); `TabelaDeLeads`/`CabecalhoOrdenavel` ganham a prop e a repassam.

**`BuscaDeLeads` e `FiltrosDeLeads` NÃO preservam a origem do funil, de propósito.** Digitar uma busca ou trocar um filtro manual é uma pergunta nova, e as duas continuam levando à lista geral — declarado aqui como limite da entrega, não esquecimento. Estender isso exigiria campos ocultos nos dois formulários e a decisão de produto de "o que significa buscar dentro de uma etapa", que a card não pede.

Quando `etapa` está na URL, a tela mostra um aviso curto ("Etapa: Recomendado — 29/08 a 28/09") com um link para `/leads` limpo, para que a gerente saiba por que a lista está menor e tenha como sair dali.

## Testes

- **Backend, unitário** (`tests/unit/test_selecao_de_etapa.py`): `selecionar_etapa`/`selecionar_coorte` devolvem os `Select` esperados por construção, com `_condicoes_das_etapas` compartilhada; `contar_etapas` continua com o mesmo resultado depois do refactor (regressão).
- **Backend, integração** (`tests/integration/test_lista_de_leads.py`): `etapa=Recomendado&de=...&ate=...` devolve só os leads daquela etapa acumulada; `etapa` sem `de`/`ate` é 422; `etapa` desconhecida é 422; `de`/`ate` sem `etapa` filtra pela coorte inteira; canal/temperatura/intenção continuam restringindo dentro da etapa.
- **Frontend** (`Funil.test.tsx`): etapa disponível vira link para `/leads?...&etapa=Nome`; etapa indisponível não é link; os filtros do funil chegam ao `href`.
- **Frontend** (`lib/leads.test.ts`): `origemDoFunilDaUrl` lê os quatro campos; `urlDaLista` os inclui quando presentes.
- **Frontend** (`app/(painel)/leads/page.test.tsx`): `?etapa=...` chega ao backend; o aviso da etapa aparece e some sem o parâmetro.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais, sessão GERENTE, leads semeados diretamente no banco nas etapas Novo/Em conversa/Qualificado.

| passo | resultado |
| --- | --- |
| Funil com `?de=2026-09-01&ate=2026-09-30` | as seis etapas têm `href` para `/leads?de=...&ate=...&etapa=<nome>` — inclusive Agendado, com quantidade zero (D3: `disponivel` é quem decide, não a quantidade) |
| Abrir `/leads?...&etapa=Qualificado` | 3 linhas, batendo com a quantidade que o funil mostrava para aquela etapa |
| A tela | mostra "Etapa do funil: Qualificado — período de 2026-09-01 a 2026-09-30 · Ver todos os leads" |
| Cabeçalhos de ordenação ("Score", "Última interação") | ambos com `de`/`ate`/`etapa` no `href` — reordenar não perde a etapa (D6) |

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Abrir os leads de uma etapa | integração de `test_lista_de_leads.py` + `page.test.tsx` |
| Etapa sem fonte não é navegável | `Funil.test.tsx` (não exercitável em produção hoje — D3) |

## Lacunas declaradas

- **L1 — Busca e filtros manuais dentro de `/leads` descartam a origem do funil** (D6). Decisão de produto sobre o que "buscar dentro de uma etapa" significa, fora do escopo desta card.
- **L2 — Sem teste de carga/desempenho da nova consulta.** `selecionar_etapa` faz o mesmo `UNION` que `contar_etapas` já fazia (mesmo custo), mais um `JOIN` com a base da lista de leads — não medido isoladamente.
