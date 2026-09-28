# TEC-341 — Baixar os dados do titular para atender pedido de portabilidade

**Status:** implementado (28/09/2026)
**Card:** [TEC-341](https://eduardodurieuxlopes.atlassian.net/browse/TEC-341) — épico TEC-306
**Branch:** `feat/tec-341-portabilidade-do-titular`
**Depende de:** TEC-340 (a fila), TEC-207 (a exportação no backend)

## O que existe quando a card começa

- **`GET /api/v1/leads/{lead_id}/dados-pessoais`** (`src/mobia/api/routes/titular.py::dados_pessoais`) já produz o JSON completo do titular — resumo, qualificação, consentimentos, transcrição inteira — e, na mesma transação, marca **atendida** a solicitação `ACESSO` aberta daquele par, se houver uma. Exige `ATENDER_TITULAR`. É idempotente: chamar de novo não falha, só não encontra mais solicitação aberta para marcar.
- **Não existe endpoint por `solicitacaoId`.** A fila (`GET /api/v1/titular/solicitacoes`) lista por `(id, tipo, origem, status, leadId, …)`; o backend não expõe "pegue esta solicitação e exporte", só "exporte este lead".
- **A fila da TEC-340 já existe** em `/admin/titular`, e só lista `status=ABERTA`.
- **Não há endpoint que sirva arquivo.** Toda resposta do backend é JSON puro, sem `Content-Disposition`.

A regra RN-FE-15.2 vem do texto da card: o SRS do frontend não está no repo.

## D1 — Portabilidade é a exportação do pedido `ACESSO`

A TEC-207 não tem tipo `PORTABILIDADE`. Como a L2 do desenho da TEC-340 já registrou, portabilidade é o que `ACESSO` entrega: o titular pede os próprios dados, e entregá-los num arquivo baixável **é** atender ao pedido de portabilidade. O botão "Baixar dados do titular" aparece só nas linhas `ACESSO` da fila.

## D2 — Um Route Handler próprio, não o `/bff/*` genérico

`/admin/titular/[solicitacaoId]/baixar/route.ts`, e não uma entrada nova em `ROTAS_PERMITIDAS`.

- **O `/bff/*` só repassa `Content-Type` e `Retry-After`** (`REPASSADOS`, em `lib/servidor/bff.ts`), de propósito — copiar cabeçalhos em bloco relaiaria o que o FastAPI decidir mandar um dia. `Content-Disposition: attachment` é exigência desta card, não do FastAPI, e não pertence a um proxy fino e genérico.
- **A regra "pedido já concluído" também não pertence lá.** O `/bff/*` não tem lógica de negócio nenhuma; esta card tem uma decisão inteira (D4).
- **O link é navegação, não `fetch`.** Um `<a href>` que o navegador trata como download por causa do `Content-Disposition` é o jeito sem JavaScript de servir arquivo — o mesmo motivo pelo qual `ErroDeCarga` usa `<a>` e não botão. O `/bff/*` existe para o consumidor de cliente que faz `fetch`; este download nunca faz.

## D3 — A guarda repete o molde das páginas, não duplica a UI de "Sem permissão"

`exigirSessao` (redireciona ao login sem sessão) e `quemSou` (a matriz de permissões), como toda página do painel. Sem `ATENDER_TITULAR`, o handler **redireciona a `/admin/titular`** em vez de desenhar "Sem permissão" ele mesmo — só uma página React faz isso, e a fila já sabe: ela roda a mesma guarda e mostra a tela certa. Um Route Handler não renderiza JSX.

## D4 — "Já concluído" é a solicitação buscada de novo, sem filtro de status

- O handler busca a fila **sem** `?status=`, que devolve `ABERTA`, `ATENDIDA` e `RECUSADA`, e procura o `id` da URL nela. É a única forma de saber o status atual: não há `GET` por id.
- **`status !== 'ABERTA'`** → redireciona a `/admin/titular?concluido=1`, e a página mostra "Este pedido já foi concluído." A fila só lista `ABERTA`, então isso só acontece por corrida: duas abas, um clique duplo depois que a primeira chamada já commitou.
- **A checagem de status vem ANTES da de `leadId`, e a ordem não é gosto.** Uma vez `ATENDIDA` ou `RECUSADA`, o backend zera `(channel, conversation_key)` daquela linha -- é a `ck_solicitacoes_de_titular_par_com_status` que o desenho da TEC-340 já documentou --, e por isso **toda solicitação concluída chega aqui com `leadId: null`**. A primeira versão checava `leadId` antes do status, e todo "já concluído" caía no redirecionamento silencioso de baixo -- o cenário da card nunca disparava. Descoberto na verificação no navegador (28/09/2026): o clique duplo voltava para `/admin/titular` sem `?concluido=1`.
- **Não encontrado ou tipo diferente de `ACESSO`** → redireciona a `/admin/titular`, sem aviso. Nenhum tem cenário na card.
- **`ABERTA` sem `leadId`** (a linha cujo apelido sumiu por fora, D2 da TEC-340) → mesmo redirecionamento silencioso, mas só chega aqui depois de confirmar que o status ainda é `ABERTA`. Ver a lacuna L1.
- **Achando um `ACESSO` `ABERTA` com `leadId`**, chama `GET /api/v1/leads/{leadId}/dados-pessoais` e transmite o corpo como veio — sem reanalisar — com `Content-Disposition: attachment; filename="titular-{solicitacaoId}.json"`, `Content-Type: application/json` e `Cache-Control: no-store`.
- **Falha do backend na exportação** → redireciona a `/admin/titular`, sem aviso (mesma lacuna).

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais. Semeei um pedido `ACESSO` `ABERTA` sobre um par `(channel, conversation_key)` com mensagens reais de verificações anteriores (para `ler_detalhe` resolver de verdade), como ADMIN logado por MFA.

| passo | resultado |
| --- | --- |
| `fetch` in-page do link "Baixar dados do titular" | `Content-Type: application/json`, `Content-Disposition: attachment; filename="titular-<id>.json"`, `Cache-Control: no-store`, corpo com `exportadoEm`, `telefone`, etc. |
| depois do download | a linha virou `ATENDIDA` no banco |
| navegar de novo para o mesmo link | **achou o bug da ordem D4** (abaixo) na primeira tentativa; corrigido, voltou a `/admin/titular?concluido=1` com "Este pedido já foi concluído." |
| GERENTE navegando direto para um link de download | "Sem permissão" |

**O que a verificação achou:** a primeira versão checava `leadId === null` antes de `status !== 'ABERTA'`. Como o backend zera o par de toda solicitação concluída (D4), `leadId` vem sempre nulo para `ATENDIDA`/`RECUSADA`, e todo "já concluído" caía no redirecionamento silencioso -- o cenário nunca disparava. Só apareceu navegando de verdade; os testes automatizados, escritos com a mesma suposição errada sobre a forma do dado, não pegaram.

## Testes

- `lib/servidor/titular.ts`: `buscarSolicitacao` acha por id numa lista com vários status, e devolve `null` quando não acha.
- O Route Handler (chamando `GET` diretamente, no molde de `route.test.ts` do `/bff/*`, com `next/headers` e `next/navigation` dublados como nos testes de página):
  - sem sessão, redireciona ao login;
  - sem `ATENDER_TITULAR`, redireciona a `/admin/titular`;
  - `ACESSO` `ABERTA` com `leadId`: os três cabeçalhos e o corpo exato que o backend mandou;
  - `ATENDIDA` ou `RECUSADA`: redireciona a `/admin/titular?concluido=1`, sem chamar a exportação;
  - `ELIMINACAO`, id inexistente e `leadId` nulo: redirecionam a `/admin/titular` sem tocar a exportação.
- `FilaDoTitular`: o link aparece só nas linhas `ACESSO`, com o `href` certo.
- A página `/admin/titular`: com `?concluido=1`, o aviso.
- Navegador: baixar de verdade, um pedido `ACESSO` semeado, e conferir os cabeçalhos e o conteúdo.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Baixar os dados do titular | Route Handler: os três cabeçalhos e o corpo; navegador |
| Pedido já concluído | Route Handler: `ATENDIDA`/`RECUSADA` redireciona com `?concluido=1`; página: o aviso |

## Lacunas declaradas

- **L1 — Não encontrado, tipo errado, sem `leadId` ou exportação que falha redirecionam em silêncio.** Nenhum tem cenário na card. Dar um aviso a cada um é onde a próxima card que mexer aqui deve olhar primeiro.
- **L2 — O SRS do frontend não está no repo.** A regra vem do texto da card.
- **L3 — Baixar não fecha a solicitação por conta própria.** Quem fecha é o backend, na mesma chamada de exportação (comportamento já existente da TEC-207); esta card não muda isso.
