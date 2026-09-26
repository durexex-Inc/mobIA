# TEC-312 — Menu por papel e a tela "Sem permissão"

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-312](https://eduardodurieuxlopes.atlassian.net/browse/TEC-312) — épico TEC-301
**Branch:** `feat/tec-312-menu-por-papel`
**Depende de:** TEC-309 (sessão do painel), TEC-202 (matriz de permissões)

## O que existe quando a card começa

O painel tem uma tela só, o funil, em `/`. A área de administração, a gestão de prompts (TEC-338) e a lista de leads (TEC-321) ainda não existem. A matriz de permissões mora no backend, em `domain/usuarios/permissoes.py`, e `GET /api/v1/auth/me` a devolve já resolvida para o papel de quem pergunta (D7 da TEC-202, que existe justamente por causa desta card).

## D1 — O menu sai das permissões, e não do nome do papel

Cada item do menu declara a permissão que o torna visível:

| item | aparece para quem tem |
| --- | --- |
| Funil | `VER_FUNIL` |
| Administração | qualquer uma de `CONFIGURAR_AGENTE`, `GERIR_CATALOGO`, `GERIR_CORRETORES`, `VER_AUDITORIA`, `OPERAR_FILA` |

Isso reproduz a tabela do Gherkin — ADMIN vê os dois, GERENTE e LEITURA só o funil, CORRETOR nenhum dos dois — **sem repetir a matriz no frontend**. Um `if papel === 'ADMIN'` no menu seria uma segunda cópia da regra, livre para divergir da primeira; perguntando pela permissão, o dia em que a matriz mudar, o menu muda junto.

"Administração" usa "qualquer uma de" porque a área agrupa telas de permissões diferentes. Hoje todas são só do ADMIN, e ninguém ganha o item por acidente.

## D2 — `/auth/me` é lido pelo servidor, e não por `/bff/me`

A card diz que papéis e permissões vêm de `GET /bff/me`. O que ela protege é a outra metade da frase: **o cliente não decodifica JWT**. O menu é Server Component — não há código de cliente no painel, pela mesma razão que a TEC-302 manteve o funil fora do `/bff/*` —, então quem lê `/auth/me` é o servidor, pela mesma porta (`lib/servidor/api.ts`) e com o JWT da sessão. Acrescentar `/bff/me` sem consumidor seria o proxy ganhar uma rota que nenhum código chama.

`quemSou` fica embrulhado no `cache` do React: o layout (para o menu) e a página (para a guarda) pedem a mesma coisa na mesma requisição, e ela vai ao FastAPI uma vez só.

## D3 — A guarda fica na página, e o layout só monta o menu

A tentação é pôr a checagem de permissão no layout de `/admin` e esquecer as páginas. A documentação do Next 16 diz por que isso não funciona, em `authentication.md`, na seção "Layouts and auth checks":

> A layout also does not control whether the rest of the route renders. Route segments (...) are rendered by the router, so a layout that hides or swaps them does not stop them from running or from appearing in the RSC Payload.

Uma página filha de um layout que devolve "Sem permissão" continua **rodando** — e, se ela buscar dado, o dado vai no payload. Então:

- o layout do grupo `(painel)` busca `quemSou` e desenha o menu, e nada mais;
- **cada página confere a própria permissão** com `exigirPermissao`, antes de buscar qualquer coisa, e mostra "Sem permissão" se faltar.

O preço é uma linha por página. O que ela compra é o cenário 2 do Gherkin — "nenhum dado administrativo é carregado com sucesso" — valendo por construção, e não por sorte de onde a busca foi escrita.

## D4 — A tela "Sem permissão"

Um componente (`SemPermissao`), usado em três situações:

1. **Acesso direto por URL a uma área que o papel não tem** — a página confere antes de buscar (D3).
2. **O backend respondeu 403 a uma tela que o menu mostrou** — o cenário 3. O funil hoje trata o 403 como aviso; passa a mostrar esta tela. A recusa do backend vence o menu, sempre: o menu é conveniência, a regra é do FastAPI.
3. **A página inicial de um papel que não tem nenhuma tela ainda** — o CORRETOR, ver D6.

Ela mostra o nome do papel ("Você entrou como Corretor") e um link para a página inicial. **O nome do papel é em português**: `CORRETOR` é identificador de sistema, e a pessoa se reconhece em "Corretor".

## D5 — A área de administração começa como um índice

Decisão do Eduardo em 26/09/2026. `/admin` é uma página **só de navegação**: lista as seções previstas (prompts, configuração do agente, corretores, imóveis, auditoria), cada uma marcada como ainda não disponível, e não busca dado nenhum. Ela confere a permissão como qualquer outra página (D3).

**O cenário 2 do Gherkin é exercitado em `/admin`, e não em `/admin/prompts`**, que não existe: para qualquer papel, aquele endereço hoje dá 404. Quando a TEC-338 criar a página, ela chama `exigirPermissao` com `CONFIGURAR_AGENTE`, e o cenário passa a valer lá também. O que esta card entrega é o mecanismo e a primeira página que o usa.

## D6 — A página inicial do CORRETOR é a tela "Sem permissão"

Decisão do Eduardo em 26/09/2026. `/` continua sendo o funil. O CORRETOR não tem `VER_FUNIL`, e a tela dele — a lista de leads — é a TEC-321, que ainda não existe. Então, para ele, `/` mostra "Sem permissão" com uma frase dizendo que a tela do corretor ainda não está disponível. É o estado real, dito como é; uma página de boas-vindas vazia seria inventar tela.

**"Página inicial do papel" continua sendo `/` para todos** (`paginaInicialDe`). Quando a TEC-321 existir, é ali que o CORRETOR passa a ir, e a função muda num lugar só.

## D7 — O `loading.tsx` muda de lugar

`app/loading.tsx` estava na raiz e valia para todas as rotas — inclusive `/login`, que mostrava o esqueleto do funil enquanto carregava. Com as páginas do painel dentro do grupo `(painel)`, o `loading.tsx` vai junto, e o login deixa de pegar emprestado o esqueleto de outra tela. Grupo de rota não muda URL: `/` continua `/`.

## Lacunas declaradas

- **L1 — `/admin/prompts` dá 404, e não "Sem permissão".** A página não existe (D5). Não é vazamento: 404 não diz nada a ninguém.
- **L2 — "ações conforme o papel" (o título da card) não tem ação nenhuma para esconder.** A única tela é o funil, que é só leitura. O mecanismo (`permissoes` no `quemSou`) é o mesmo que os botões das próximas telas vão usar.
- **L3 — o menu reflete o papel com até 60 minutos de atraso.** `/auth/me` lê as claims do JWT, e não o banco (D7 da TEC-202). Mudar o papel de alguém só aparece no menu depois do próximo login — ou da próxima renovação, quando a TEC-310 existir.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| menu por papel (quatro linhas) | `itensDoMenu` (D1), com um teste por linha da tabela, e o layout que o desenha |
| corretor acessa a área administrativa pela URL | `/admin` com `exigirPermissao` (D3, D5); o teste afirma que nada além de `/auth/me` é chamado |
| recusa do backend prevalece sobre o menu | o 403 do funil vira `SemPermissao` (D4) |

**Sem emenda ao SRS do agente.** O contrato desta card é o SRS do frontend (RN-FE-03.1 a 03.4), que não está versionado no repo.
