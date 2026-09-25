# TEC-313 — Estados padrão de tela

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-313](https://eduardodurieuxlopes.atlassian.net/browse/TEC-313) — épico TEC-301
**Branch:** `feat/tec-313-estados-padrao-de-tela`
**Origem:** RF-FE-04, RN-FE-04.1 a 04.4 (SRS mobIA Frontend v1.0 — ver a lacuna L1)

## O que existe hoje, e o que falta

O painel de funil (TEC-190) já distingue ausências, e distingue bem — a decisão de não mostrar zero no lugar de "sem fonte" está implementada e comentada. O que falta é **vocabulário compartilhado** e três dos cinco estados:

| regra da card | hoje |
| --- | --- |
| cinco estados em todo componente com dado remoto | **não há "carregando" nenhum**; o erro não oferece "tentar de novo" |
| `disponivel: false` → "Ainda não medido" com o motivo | o texto é `"sem fonte de dados"`, e o motivo está numa nota de rodapé da seção |
| 5xx e rede → mensagem genérica + `request_id` copiável | **não há `request_id` em lugar nenhum** |
| 422 → mensagem do backend ao lado do campo | um aviso único acima do formulário |

A ausência de "carregando" não é descuido: `app/page.tsx` é Server Component e faz `await buscarFunil(...)` antes de renderizar. Não existe momento em que a tela esteja montada sem dado — o que existe é o tempo em que **nada** é mostrado.

## D1 — A fronteira com a TEC-315, dita antes de qualquer código

A [TEC-315](https://eduardodurieuxlopes.atlassian.net/browse/TEC-315) declara-se **"bloqueada pelos estados padrão de tela (TEC-313)"**, e as duas mencionam "Ainda não medido". A divisão:

- **Aqui:** o vocabulário e as peças — os cinco estados, o texto "Ainda não medido", o erro com "tentar de novo" e `request_id`, o 422 junto ao campo.
- **Na TEC-315:** o que é do funil — o aviso de "Coorte incompleta" para conversão acima de 100%, e a regra de não calcular conversão para etapa sem fonte.

**Uma exceção deliberada:** troco o texto `"sem fonte de dados"` por "Ainda não medido" **também na etapa do funil** (`quantidadeLegivel`, em `lib/formato.ts`), e não só nos indicadores. A alternativa — mudar só onde é "meu" — deixaria a mesma tela falando dois idiomas para a mesma ausência, que é pior que invadir três linhas de outra card. A TEC-315 continua dona do **comportamento** da etapa (conversão não calculada, coorte incompleta); ela herda o texto pronto em vez de escrevê-lo.

## D2 — O skeleton atrasado é CSS, não JavaScript

A card pede skeleton **"a partir de 300 ms"**. O `loading.tsx` do Next mostra a UI de carregamento **instantaneamente** — é o que a referência empacotada chama de *instant loading state*.

Atrasar com JS exigiria `'use client'`, um `useState` e um `setTimeout` — hidratação e um componente de cliente para não mostrar uma coisa. Com CSS é uma regra:

```css
.skeleton { opacity: 0; animation: aparecer-skeleton 0s linear 300ms forwards; }
```

O skeleton existe no HTML desde o primeiro byte e só fica **visível** aos 300 ms. Se a resposta chegar em 120 ms, ninguém vê flash nenhum — que é a razão de a regra existir, e não uma consequência acidental.

**Custo declarado:** quem tiver `prefers-reduced-motion` e quem inspecionar o DOM vê o elemento antes dos 300 ms. Nenhum dos dois é o problema que a regra ataca.

## D3 — O `request_id` vem da RESPOSTA, e não de mandar um na requisição

Este é o ponto onde a card colide com uma decisão existente, e a colisão é real.

A card diz "o `request_id` (header `X-Request-Id`)". O caminho do funil **deliberadamente não manda** `X-Request-Id`: header entra na chave do Data Cache, e um id novo por requisição zeraria a taxa de acerto — o que faz N navegadores com o painel aberto virarem uma chamada por minuto ao FastAPI. Está escrito em `lib/metricas.ts`, no `README.md` do frontend, e o tipo de `chamarApi` **recusa** cache e id juntos.

Então o id não pode nascer aqui. Ele nasce **no backend**: desde a TEC-368 o FastAPI gera um `correlation_id` quando a requisição não traz um, e devolve `X-Request-Id` na resposta (D6 daquele desenho). É esse que a tela mostra.

Consequências, as três ditas em voz alta:

1. **O id identifica o log do backend**, que é exatamente quem vai ser consultado num 5xx. Serve para o que a card quer.
2. **Num erro não há cache a proteger**, então ler o header da resposta de erro não custa nada — e é só no erro que a tela mostra o id.
3. **Pode não haver id.** Um 502 de proxy que nunca chegou ao FastAPI não tem `X-Request-Id`. A tela então **omite o campo**, em vez de inventar um id ou mostrar "desconhecido" — um id falso mandaria alguém procurar no log uma linha que não existe.

## D4 — "Ainda não medido" carrega o motivo, e o motivo não fica só no tooltip

A card diz "com o motivo em tooltip". Tooltip por `title` não existe em toque e é irregular em leitor de tela — e a RNF-FE-18 (citada pela TEC-315) exige que aviso não dependa de um canal só.

Então: `title` para o mouse **e** o mesmo texto ligado por `aria-describedby` a um elemento visualmente oculto, para o leitor de tela. A nota de rodapé da seção **permanece** — ela é o canal que funciona em toque, e o comentário de `Indicadores` já explica por que existe (quatro cartões marcados sem explicação parecem defeito do painel).

## D5 — O 422 vai ao lado do campo, e para isso o erro precisa carregar o campo, não a prosa

`detalheDe` (`lib/metricas.ts`) já sabe extrair os nomes de campo do `detail` do FastAPI — mas os joga numa frase (`"valor invalido em corretorId"`). Para pôr a mensagem ao lado do campo, a tela precisa do **nome do campo**, estruturado.

`ErroDeMetricas` ganha `campos: string[]`. A prosa continua existindo para o caso em que não há campo identificável (o `detail` string dos 422 que `montar_recorte` levanta), e aí o aviso continua acima do formulário — que é o lugar certo para um erro que não é de nenhum campo.

## D6 — "Tentar de novo" é um link, não um botão com JavaScript

A tela é Server Component sem nenhum JS de cliente, e a TEC-302 registra que isso é deliberado. Um botão de retry exigiria `'use client'`.

Um `<a href="<url atual>">` recarrega a rota e refaz a busca — que é exatamente o que "tentar de novo" significa aqui. A URL se remonta a partir dos `searchParams`, que a página já tem. Zero JS, funciona sem hidratação, e é navegável por teclado de graça.

## Arquivos

```
frontend/src/lib/estados.ts              # o vocabulario dos cinco estados (D1)
frontend/src/lib/estados.test.ts
frontend/src/components/estado/          # Skeleton, Vazio, ErroDeCarga, AindaNaoMedido
frontend/src/components/estado/*.test.tsx
frontend/src/app/loading.tsx             # o skeleton da rota (D2)
frontend/src/app/globals.css             # a animacao atrasada e o visually-hidden
frontend/src/lib/metricas.ts             # ErroDeMetricas ganha requestId e campos (D3, D5)
frontend/src/lib/formato.ts              # "Ainda nao medido" (D1)
frontend/src/components/Indicadores.tsx  # adota AindaNaoMedido
frontend/src/components/Filtros.tsx      # 422 ao lado do campo (D5)
frontend/src/app/page.tsx                # ErroDeCarga com id e "tentar de novo" (D3, D6)
```

## Testes

- **`estados.test.ts`** — a função que decide o estado: `disponivel: false` nunca vira "com dados"; nulo sem `disponivel: false` é vazio; zero é **com dados**, não vazio (é o coração da card).
- **`AindaNaoMedido`** — mostra o texto e o motivo, e **o dígito `0` não aparece** no cartão (é o primeiro cenário do Gherkin, escrito como asserta de ausência que pode reprovar — a regra da TEC-289).
- **`ErroDeCarga`** — com `requestId`, mostra o id e o "tentar de novo"; **sem** `requestId`, não inventa nem mostra rótulo vazio.
- **`Filtros`** — 422 com campo põe a mensagem junto do campo; 422 sem campo põe acima do formulário.
- **`metricas.test.ts`** — `ErroDeMetricas` carrega o `X-Request-Id` da resposta e os campos do `detail` nas duas formas.
- **No app de verdade** — que o skeleton não pisca numa carga rápida, e que aparece numa carga lenta. É o único jeito de verificar a D2: um teste de unidade vê o elemento no DOM nos dois casos, porque a diferença é CSS.

## Emendas ao SRS

Nenhuma. O SRS do frontend não está no repositório (lacuna L1) — não há texto a emendar.

## Lacunas declaradas

- **L1 — o SRS do frontend continua fora do repo.** Terceira card a esbarrar nisso (TEC-302 e TEC-356 declararam o mesmo). As regras vêm do texto da card, que é a fonte de requisitos; RN-FE-04.1 a 04.4 não foram lidas no original.
- **L2 — o quinto estado ("vazio") quase não tem sítio hoje.** O painel de funil trata coorte vazia dentro de `valorLegivel`, e não há lista no dashboard ainda — a lista de leads é a TEC-321. O componente nasce com um consumidor só, e o segundo chega com aquela card.
- **L3 — o 422 ao lado do campo só é exercitado nos filtros.** É o único formulário que existe. O terceiro cenário do Gherkin fala em "capacidade diária", que é o cadastro de corretores (TEC-332) e não existe.
- **L4 — o skeleton cobre a rota inteira, não cada componente.** `loading.tsx` é por segmento de rota. Skeleton por cartão exigiria `<Suspense>` em volta de cada um e uma busca por cartão, e hoje há **uma** chamada que traz tudo. Quando houver mais de uma fonte por tela, isso volta.
- **L5 — o `request_id` mostrado é o do backend, e só existe se a requisição chegou lá.** Ver a D3: num 502 de proxy não há id, e a tela omite em vez de inventar.
