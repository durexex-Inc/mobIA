# TEC-321 — A lista de leads no painel, por score, com busca

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-321](https://eduardodurieuxlopes.atlassian.net/browse/TEC-321) — épico TEC-304
**Branch:** `feat/tec-321-lista-de-leads`
**Depende de:** TEC-192 (`GET /api/v1/leads`), TEC-195 (máscara e `leadId`), TEC-312 (menu e guarda por permissão)

## O que existe quando a card começa

`GET /api/v1/leads` existe desde a TEC-192: ordena por score decrescente, com os leads sem score no fim, pagina por keyset, busca num campo só (`busca`) por bairro ou telefone completo. O telefone é normalizado pelo backend, então `(48) 99999-0021` acha `+55 48 99999-0021`. Desde a TEC-195, `telefone` já sai mascarado para todo chamador, e cada item traz o apelido opaco `leadId`. O recorte do `CORRETOR` é aplicado pelo repositório, a partir da claim do JWT.

No painel, o CORRETOR cai em "Sem permissão" na página inicial, porque não tem `VER_FUNIL`. A D6 da TEC-312 deixou isso escrito como o estado provisório até esta card existir.

## D1 — A tela é `/leads`, guardada por `VER_LEADS`

A página chama `exigirPermissao('/leads', p => p.has('VER_LEADS'))` antes de buscar qualquer coisa. É o molde da D3 da TEC-312. `VER_LEADS` é concedida aos quatro papéis pela D7 da TEC-192; a diferença entre eles está no que o backend devolve, e não em quem abre a tela.

O menu ganha "Leads" com `VER_LEADS`, pela mesma regra da D1 da TEC-312: o item pergunta pela permissão, e nunca pelo papel.

## D2 — A página inicial deixa de ser `/` para todo mundo

`paginaInicialDe` passa a receber as permissões. Quem tem `VER_FUNIL` continua em `/`. Quem tem só `VER_LEADS` vai para `/leads`: hoje, só o CORRETOR.

O login continua mandando todo mundo para `/` (`PAGINA_INICIAL`, em `lib/destino.ts`), porque na hora do redirecionamento ele ainda não leu `/auth/me`. **Quem resolve é a página do funil**: sem `VER_FUNIL` e com `VER_LEADS`, ela redireciona para `/leads` antes de buscar qualquer dado. O CORRETOR que entra chega à lista dele, e não à tela "Sem permissão" que a D6 da TEC-312 registrou como provisória.

## D3 — Não há coluna "nome", porque não há nome

A card pede a coluna nome e a busca por nome. **Nenhuma tabela do sistema guarda o nome do lead** (Emenda E-02 da RN-15.1; L1 da TEC-192), e a rota não devolve esse campo.

A primeira coluna é **"Lead"** e mostra o telefone mascarado que a rota devolve (`+55 48 9****-**21`), porque é o identificador que o corretor reconhece. Para o visitante do site que nunca digitou o número, `telefone` é nulo, e a célula diz "Visitante do site". Uma célula vazia seria lida como defeito.

**Telefone nulo fora do site diz "Telefone indisponível".** Achado na verificação de ponta a ponta: um lead do WhatsApp gravado antes da TEC-203 volta sem telefone, porque o backend não resolve a chave dele. A primeira versão o chamava de "Visitante do site", e a coluna "Canal" ao lado dizia WhatsApp.

A caixa de busca diz "Buscar por telefone ou bairro". Escrever "nome" ali prometeria uma busca que devolve vazio para toda pessoa procurada.

## D4 — Ordenar por última interação exige o backend, e ele ganha `ordenar`

A card pede a lista "ordenável por score e última interação". A rota só ordena por score, e a L7 da TEC-192 recusou o parâmetro "para não fingir que há escolha". Agora a escolha existe e tem consumidor.

**Ordenar no cliente não serve.** Ele reordenaria os 25 itens da página, e o corretor que clica em "última interação" leria a lista como "os mais recentes da base". Na verdade seriam os 25 de score mais alto, embaralhados. O erro fica invisível numa base pequena e aparece na primeira base que passar de uma página.

A rota ganha `ordenar`, com os valores `score_desc` (padrão) e `ultima_interacao_desc`. São os nomes que o SRS já escreve na seção 6.2 (`?ordenar=score_desc`). A segunda ordem é `ultima_interacao_em DESC, channel, conversation_key`, com o mesmo desempate do par que a D5 da TEC-192 exige, pela mesma razão.

**O cursor carrega a ordem em que nasceu.** O cursor de score continua com a forma `{"s","l"}` de hoje, então nenhum cursor em uso passa a ser recusado. O cursor da nova ordem tem a forma `{"o":"u","u":<instante>,"l":<leadId>}`. Um cursor de uma ordem usado com a outra leva 422: continuar a lista de score a partir de um instante produziria uma página plausível e errada.

Valor de `ordenar` fora do vocabulário também leva 422, e não a ordem padrão. Mesma regra do `status` na TEC-192: a resposta errada em silêncio seria lida como a pedida.

Na tela, os cabeçalhos "Score" e "Última interação" são **links** (`?ordenar=...`), e não botões. A página é Server Component, e o link funciona sem JS.

## D5 — A busca é o segundo componente de cliente do painel

O debounce de 300 ms não existe sem JS. `BuscaDeLeads` é `'use client'`, espera 300 ms depois da última tecla e troca a URL com `router.replace`. A busca fica na URL, que é onde o estado da tela já mora no funil. Quem recebe a busca é a página, no servidor.

- **Menos de 2 caracteres não navega**, e a lista continua como estava: é o terceiro cenário do Gherkin. **Zero caracteres navega**: apagar a busca devolve a lista inteira. Sem essa exceção, a única forma de voltar à lista completa seria recarregar a página sem a busca.
- **A página aplica a mesma regra.** Uma `?busca=a` digitada à mão na URL não chega ao FastAPI. O componente de cliente é conveniência; a regra fica no servidor.
- **Sem JS, a busca ainda funciona.** O componente é um `<form method="get">`: Enter envia. A ordem atual vai num campo escondido, para buscar não desfazer a ordenação.
- **Só importa módulos puros**, como o aviso de inatividade da TEC-311. O `server-only` reprova o build se algo de `lib/servidor/` chegar nele.

## D6 — A chamada é `no-store`

A lista muda a cada turno do agente, porque o score é recalculado. Além disso, a resposta é por usuário, e a busca multiplica as URLs. O `revalidate: 60` do funil faria o corretor ver um lead "esquentar" com até um minuto de atraso, sem ganho de cache que compense: cada combinação de busca e ordem teria a própria entrada. Sem cache, `chamarApi` aceita `X-Request-Id`; ele não é mandado, porque o FastAPI não lê esse cabeçalho (README do frontend).

## D7 — "Última interação" é relativa, com a data absoluta no título

`<time dateTime={iso} title="26/09/2026, 14:03">há 5 minutos</time>`, com `Intl.RelativeTimeFormat('pt-BR')` e o fuso `America/Sao_Paulo`. O texto relativo é calculado no servidor, no momento da requisição. Ele não se atualiza sozinho com a página aberta, e não deveria: um relógio vivo exigiria mais um componente de cliente para uma informação que recarregar a tela já dá.

## D8 — Os estados da tela

| situação | tela |
| --- | --- |
| sem lead, sem busca | "Nenhum lead ainda." |
| sem lead, com busca | "Nenhum lead encontrado para “termo”." |
| 401 | apaga a sessão e vai ao login, como o funil (TEC-310, D5) |
| 403 | `SemPermissao`: a recusa do backend vence o menu (TEC-312, D4) |
| 422 | `ErroDeCarga` com a razão, e "tentar de novo" volta para a lista sem busca nem ordem: o parâmetro recusado estava na URL, e repeti-la reproduziria o erro |
| outros | `ErroDeCarga` com o `X-Request-Id` da resposta |

Os dois vazios são textos diferentes pela mesma razão da TEC-313: "não há lead" e "não há lead com este termo" são fatos diferentes.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| ordenar por score | teste da página: a tabela renderiza na ordem que a rota devolve (82, 47, 30), e sem `ordenar` a chamada vai como `score_desc`. A ordem em si é do backend, com teste de integração desde a TEC-192 |
| buscar por telefone com qualquer formatação | teste da página: `?busca=(48) 99999-0021` chega ao FastAPI sem alteração. A normalização já tem teste de integração desde a TEC-192 (`test_busca_por_telefone_aceita_pontuacao`) |
| busca curta não dispara consulta | teste do componente: "a" não navega, depois de 300 ms nem nunca. Teste da página: `?busca=a` não chega ao FastAPI |
| corretor vê só os próprios leads | o recorte é do backend e tem teste de integração desde a TEC-192. Teste da página: a página não tem filtro por corretor nenhum (ver L2) |

Mais: a ordenação por última interação tem testes de integração próprios (ordem, paginação sem repetir linha, cursor de uma ordem recusado na outra) e unitários do cursor.

## Lacunas declaradas

- **L1 — não há nome, nem coluna, nem busca** (D3). É a mesma lacuna da TEC-192, e só se fecha quando algo passar a guardar o nome.
- **L2 — o "filtro por corretor não é exibido" vale porque não há filtro nenhum.** Os filtros são a TEC-322. Quando o filtro por corretor entrar lá, ele precisa ficar escondido para o CORRETOR, e o teste desta card não pega isso: hoje ele não tem o que verificar.
  - **Nota (TEC-322, 27/09/2026):** o filtro entrou escondido para o CORRETOR, e o teste da página da TEC-322 o verifica. Para a GERENTE e a LEITURA ele aparece desabilitado: só o ADMIN pode listar corretores.
- **L3 — a tela mostra só a primeira página, com 25 leads.** Paginação é a TEC-322. O CORRETOR com mais de 25 leads vê os 25 primeiros da ordem escolhida e não tem como chegar ao 26º. A tela diz isso quando há próxima página.
  - **Nota (TEC-322, 27/09/2026):** a paginação entrou: páginas numeradas a partir de 1024 px e "Carregar mais" abaixo disso. Ver `docs/superpowers/specs/2026-09-27-tec-322-filtrar-e-paginar-design.md`.
- **L4 — a linha não abre o detalhe.** O detalhe é a TEC-323. As linhas não são links, porque um link para uma tela que não existe daria 404.
  - **Nota (TEC-323, 27/09/2026):** fechada. A primeira célula abre o detalhe para quem tem `VER_DETALHE_DO_LEAD`, com `<a>`, e não com `next/link`: o prefetch gravaria um acesso na trilha por linha visível.
- **L5 — o texto relativo não se atualiza com a página aberta** (D7).

## Emenda ao SRS do agente

**Emenda E-02 à seção 6.2 / `GET /api/v1/leads` (TEC-321, 26/09/2026)** — `ordenar` passa a existir, com `score_desc` (padrão) e `ultima_interacao_desc`; valor fora disso é 422. O cursor carrega a ordem em que nasceu, e o cursor de uma ordem é recusado na outra com 422. Revoga a L7 da TEC-192, que recusou o parâmetro enquanto só havia uma ordem.
