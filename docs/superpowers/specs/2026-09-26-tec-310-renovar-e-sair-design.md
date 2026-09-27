# TEC-310 — Renovar a sessão sem novo login, e sair de verdade

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-310](https://eduardodurieuxlopes.atlassian.net/browse/TEC-310) — épico TEC-301
**Branch:** `feat/tec-310-renovar-e-sair`
**Depende de:** TEC-309 (sessão do painel no Redis), TEC-201 (`/auth/refresh` e `/auth/logout`)

## D1 — A renovação acontece no servidor, quando faltam 5 minutos

A regra da card: o BFF renova o access (60 minutos) com o refresh (7 dias), de forma transparente, até 5 minutos antes de expirar.

- **Quando o painel lê a sessão, confere quanto falta para o access expirar.** Faltando 5 minutos ou menos, troca o refresh por um par novo em `POST /auth/refresh` e grava o par no mesmo registro do Redis. O id no cookie não muda, então não há cookie a reescrever — o que importa, porque Server Component não consegue escrever cookie.
- **O instante de expiração é a claim `exp` do access**, lida no servidor sem verificar a assinatura. Não é decisão de segurança — quem valida o token é o FastAPI —, é só agendamento. A RN-FE-03.2 ("o cliente não decodifica JWT") é sobre o navegador, e o navegador continua sem ver o token. Se a claim não puder ser lida, o painel trata o access como vencido e renova: o erro vai para o lado seguro.
- **Quem lê a sessão pela função nova (`obterSessaoValida`)**: a guarda das páginas (`exigirSessao`), o layout do menu (`quemSouDaRequisicao`) e o `/bff/*`. Dentro de uma mesma requisição ela fica sob o `cache` do React, e o layout e a página não renovam cada um por si.

## D2 — Renovação com lock, porque reuso de refresh derruba a sessão

O refresh da TEC-201 é **rotativo com detecção de reuso**: apresentar um refresh já trocado revoga a família inteira, inclusive a do usuário legítimo (D4 de lá). Duas requisições que decidem renovar ao mesmo tempo — duas abas, ou um prefetch junto com a navegação — mandariam o mesmo refresh duas vezes, e a segunda desligaria a pessoa, parecendo roubo.

Então a renovação toma um lock no Redis (`SET NX` com 10 segundos de validade, na chave `mobia:painel:renovando:<digest>`):

- **quem pega o lock** renova, grava o par novo e solta o lock;
- **quem não pega** relê a sessão a cada 150 ms, por até 3 segundos, até ver o access novo. Se o tempo acabar e o access antigo ainda valer, usa o antigo; se já tiver vencido, a requisição falha como indisponível.

O lock expira sozinho, então um processo que morra no meio não trava a sessão para sempre.

## D3 — Renovação recusada encerra a sessão; FastAPI fora do ar não

- **`401` do `/auth/refresh`** — refresh revogado, expirado ou reusado — apaga a sessão do Redis e leva ao login com o `returnTo` preservado. É o cenário 2 do Gherkin.
- **FastAPI fora do ar, ou 5xx**, não apaga nada: a sessão não é inválida por isso. Se o access ainda valer (a renovação começa 5 minutos antes), a requisição segue com ele. Se já tiver vencido, a página cai na tela de erro, e a próxima tentativa renova.

## D4 — A sessão dura 7 dias contados do login, e renovar não estende

O backend dá a cada refresh novo mais 7 dias a partir da troca. Se o painel acompanhasse, a sessão nunca acabaria enquanto houvesse uso. Ela não acompanha: o cookie foi emitido no login com `Max-Age` de 7 dias, e Server Component não consegue reemiti-lo. O registro no Redis também conserva a validade original (a gravação da renovação usa o tempo que resta desde o login).

O resultado é o que a card pede — "continuar logado durante o dia" — e um novo login por semana. Se a decisão de produto for uma sessão deslizante, ela é uma linha no `proxy.ts`, que pode reemitir o cookie, e uma na gravação da renovação.

## D5 — Um `401` do FastAPI apaga a sessão antes de ir ao login

**Corrige um laço que a TEC-309 deixou.** Passados os 60 minutos do access, o funil recebia `401` e mandava ao `/login`. A página de login, vendo a sessão ainda no Redis (7 dias), mandava de volta ao destino, que recebia `401` de novo — um redirecionamento sem fim.

Com a D1 esse caso deixa de acontecer, porque o access é renovado antes de vencer. Mas um `401` ainda pode vir por outro motivo: o `JWT_SEGREDO` trocado, o usuário desativado. Então, quando a página ou o `/auth/me` recebem `401` do FastAPI, **a sessão é apagada do Redis** antes do redirecionamento. Apagar do Redis funciona dentro de Server Component, e o cookie que sobra passa a apontar para nada, o que a guarda já trata como "sem sessão".

## D6 — "Sair" é um POST para `/sair`

O menu ganha um formulário `method="post"` com o botão "Sair" — sem JavaScript, como o resto do painel. O Route Handler:

1. confere o `Origin`, com a mesma regra do login: um logout forjado por outra origem é pouco perigoso, mas não há razão para aceitá-lo;
2. manda o refresh para `POST /auth/logout`, que revoga a família no banco — "revoga o refresh token no provedor";
3. apaga a sessão do Redis e o cookie;
4. responde `303` para `/login` com `Clear-Site-Data: "cache"`.

**Se o FastAPI estiver fora do ar, o logout segue assim mesmo.** A família de refresh fica viva no banco até expirar, mas o único lugar que tinha o refresh era o registro do Redis, que foi apagado. Sair não pode depender do backend responder.

`/sair` entra nas rotas que o `proxy.ts` deixa passar sem cookie: quem chega sem sessão é mandado ao login pelo próprio handler, com `303`. Sem isso, o proxy redirecionaria com `307`, que repete o POST no destino.

"Redireciona ao logout do OIDC" não se aplica: não há provedor OIDC (Emenda E-01 à RNF-11).

## D7 — O "voltar" depois de sair

O cenário 3 pede que, depois de sair, o botão "voltar" não mostre tela com dado de lead. São três camadas:

- **Cache HTTP.** Página dinâmica do Next já sai com `Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate` (guia de self-hosting do Next 16). O navegador não guarda a página para servir depois.
- **Back/forward cache.** É o que poderia restaurar a página da memória sem pedir de novo. A resposta do logout manda `Clear-Site-Data: "cache"`, que limpa o cache da origem, e o cookie da sessão muda no mesmo passo.
- **Se o navegador pedir a página de novo**, não há sessão, e ela vai ao login.

"O cache de requisições em memória é limpo" (RNF-FE-11) não tem o que limpar: o painel não tem estado de cliente nem cache de requisição no navegador.

- **Nota (TEC-311, 26/09/2026):** o painel passou a ter estado de cliente — o horário da última interação, no `localStorage`, para o aviso de inatividade. Não é cache de requisição nem dado de lead, e o logout não precisa limpá-lo.

## Lacunas declaradas

- **L1 — o "voltar" não foi verificado num navegador de verdade.** O comportamento do back/forward cache varia por navegador e por versão, e o projeto não tem teste de navegador. O que se verifica: os cabeçalhos da página e do logout, e que a página pedida de novo vai ao login. A verificação no navegador é manual, e fica no PR.
- **L2 — sessão fixa de 7 dias** (D4), e não deslizante. É decisão, mas é de produto.
- **L3 — o lock é por sessão, e não distribuído entre instâncias do Redis.** Com um Redis só, que é o deploy de hoje, basta.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| renovar o acesso expirado sem pedir login | `obterSessaoValida` (D1, D2); teste com access a menos de 5 minutos do fim e com o lock disputado |
| encerrar a sessão quando a renovação falha | D3; teste com `401` do refresh; o destino vai no `returnTo` |
| sair não deixa dado visível no histórico | D6, D7; testes dos cabeçalhos e da sessão apagada; L1 |

**Sem emenda ao SRS do agente.** O contrato desta card é o SRS do frontend. A E-03 à RNF-11 dizia que o refresh era guardado e não usado; esta card o põe em uso, e a E-03 já apontava para ela.
