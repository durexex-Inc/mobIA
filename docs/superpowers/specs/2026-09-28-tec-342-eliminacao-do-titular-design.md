# TEC-342 — Eliminar os dados do titular com confirmação forte

**Status:** implementado (28/09/2026)
**Card:** [TEC-342](https://eduardodurieuxlopes.atlassian.net/browse/TEC-342) — épico TEC-306
**Branch:** `feat/tec-342-eliminacao-do-titular`
**Depende de:** TEC-340 (a fila), TEC-207 (o backend da eliminação)

## O que existe quando a card começa

- **`DELETE /api/v1/leads/{lead_id}/dados-pessoais`** (`src/mobia/api/routes/titular.py::eliminar`) já existe e é **assíncrono**: a chamada só registra (ou reaproveita) a solicitação `ELIMINACAO`, deixa-a **ABERTA** e enfileira o job `ELIMINAR_LEAD_JOB` — 202 com `{solicitacaoId, status: "ABERTA"}`. Quem apaga de fato e fecha a solicitação como `ATENDIDA` é o worker, via `domain/titular/eliminacao.py::anonimizar` → `domain/titular/anonimizacao.py::anonimizar_lead`, fora do request. Diferente de `dados_pessoais` (GET, da TEC-341), que é síncrono e fecha a solicitação na mesma chamada.
- Sem corpo de request: só `lead_id` no path. `_par_ou_404` devolve 404 se o par `(channel, conversation_key)` já não existir — cobre por construção o lead já anonimizado antes (o par some da tabela de apelidos na mesma transação que fecha a solicitação).
- **A fila da TEC-340** já lista as linhas `ELIMINACAO` `ABERTA`, e a coluna "Portabilidade" da TEC-341 já mostra `'—'` para elas — o ponto de entrada foi deixado como placeholder (`page.tsx`, comentário "Eliminar é a TEC-342").
- **Não existe, no repo, nenhum componente de confirmação por texto digitado.** O único padrão de confirmação é `window.confirm` binário (`ControleDaConversa.tsx`) e um painel inline sem digitação (`Conversa.tsx`). Este componente é o primeiro do tipo.
- **Não há "apelido curto" nem outro identificador do lead** além do `leadId` (UUID) que a fila já expõe pelo link "Ver lead". "Digitar o identificador do lead" (a letra da card) só pode significar o UUID inteiro.

A regra RN-FE-15.3 vem do texto da card: o SRS do frontend não está no repo.

## D1 — A confirmação é o `leadId`, mostrado por extenso no próprio diálogo

Não há apelido, e não há como abreviar sem inventar uma forma que a card não pede. O diálogo exibe o `leadId` completo (`<code>`, selecionável) e mantém o botão "Eliminar" desabilitado até o texto digitado bater exatamente com ele. Cenário da card ("identificador digitado errado" → não executa) fica garantido pelo próprio desabilitado: não há caminho de UI para disparar a chamada com o texto errado, e por isso não há revalidação do texto no servidor — ele nunca viaja na requisição, só o `leadId` do path, como toda outra mutação de lead do painel.

## D2 — `DELETE .../dados-pessoais` entra no `/bff/*`, não ganha Route Handler próprio

Ao contrário do download da TEC-341 (D2 daquele desenho), aqui:

- **Não há corpo de arquivo a retransmitir.** A resposta é um JSON pequeno (`{solicitacaoId, status}`) que o próprio `/bff/*` já repassa sem tocar (`Content-Type` está em `REPASSADOS`).
- **Não há lógica de "já concluído" a resolver no meio do caminho.** Ao contrário de "baixar", que precisa reler a solicitação pelo `id` da URL para decidir o redirecionamento, aqui a chamada já sabe o `leadId` (a linha da fila o carrega) e não depende de reler nada antes de agir — o próprio backend responde 404 se o par já não existir.
- **A chamada não navega, é `fetch` de um Client Component** — o mesmo formato de `assumir`/`devolver` em `ControleDaConversa.tsx`.

Por isso a rota entra em `ROTAS_PERMITIDAS` (`lib/servidor/bff.ts`):

```
{ metodo: 'DELETE', padrao: ['api', 'v1', 'leads', '*', 'dados-pessoais'] }
```

`origemAceita` já recusa a mutação sem `Origin` da própria origem — nenhuma regra nova de CSRF.

## D3 — Componente de cliente novo, não uma extensão de `ControleDaConversa`

`EliminarDadosDoTitular.tsx`: botão "Eliminar dados do titular" que abre um diálogo (`<dialog>` nativo, como não há outro modal no repo para copiar — ver a lacuna L1) com:

- o aviso do que a eliminação faz e o que preserva (RN-FE-15.3: "só as métricas agregadas anonimizadas são mantidas");
- o `leadId` por extenso;
- um campo de texto e o botão "Confirmar eliminação", desabilitado até o texto bater com o `leadId`;
- "Cancelar", que fecha sem chamar nada.

Ao confirmar: `DELETE /bff/api/v1/leads/{leadId}/dados-pessoais`. Sucesso (202) → fecha o diálogo, mostra um aviso de status ("Eliminação solicitada. Pode levar alguns minutos para sair da fila.") e `router.refresh()` — a linha **pode continuar `ABERTA`** depois do refresh, porque o job ainda não rodou; isso é esperado e é por isso que o aviso fala em "solicitada", não em "concluída". Falha reusa o molde de `motivoDaRecusa` de `ControleDaConversa.tsx` (401 vira aviso de sessão; qualquer outro erro vira "Não foi possível concluir. Tente de novo.").

Não é uma prop nova em `ControleDaConversa`: aquele componente é sobre a conversa (assumir/devolver), este é sobre o titular (eliminar), com um fluxo de confirmação totalmente diferente (diálogo com texto, não `window.confirm`). Componentes deep e de responsabilidade única, não uma ramificação por `acao` dentro do mesmo componente.

## D4 — A coluna da tabela vira "Ação", não fica uma segunda coluna "Eliminação"

`FilaDoTitular.tsx` já tem uma coluna para a portabilidade (TEC-341), condicionada a `tipo === 'ACESSO'`. Como `ACESSO` e `ELIMINACAO` são mutuamente exclusivos por linha, a mesma célula passa a decidir por tipo:

- `ACESSO` → o link "Baixar dados do titular" (inalterado);
- `ELIMINACAO` **com `leadId`** → `<EliminarDadosDoTitular leadId={pedido.id do lead} />`;
- `ELIMINACAO` **sem `leadId`** (a lacuna L1 da TEC-340: apelido sumiu por fora) → `'—'`, sem botão — não há como montar a URL de eliminação sem o `leadId`;
- qualquer outro tipo → `'—'`.

O cabeçalho muda de "Portabilidade" para "Ação", porque a partir desta card a coluna não é mais só sobre portabilidade. `FilaDoTitular` continua Server Component: só a célula de eliminação é que aninha um Client Component, do mesmo jeito que páginas do painel aninham `ControleDaConversa` dentro de Server Components.

## Verificação no navegador

Repetir o roteiro da TEC-340/341: Edge headless por CDP, `next dev` e API locais, um pedido `ELIMINACAO` `ABERTA` semeado sobre um par real. Confirmar: o diálogo abre, o botão fica desabilitado até o texto bater, a chamada `DELETE` sai pelo `/bff/*`, o aviso de "solicitação enviada" aparece, e GERENTE sem `ATENDER_TITULAR` não vê a fila (guarda já coberta pela TEC-340).

## Testes

- `bff.ts` / `bff.test.ts`: a nova entrada de `ROTAS_PERMITIDAS` (`DELETE .../dados-pessoais`), no molde das entradas existentes.
- `EliminarDadosDoTitular.test.tsx`: botão desabilitado até o texto bater; digitar errado não habilita; confirmar com o texto certo faz o `DELETE` e mostra o aviso; cancelar não chama nada; 401 e erro genérico.
- `FilaDoTitular`: a coluna "Ação" com o botão só nas linhas `ELIMINACAO` com `leadId`, `'—'` sem `leadId` e nas outras linhas; a portabilidade continua só em `ACESSO`.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Eliminar com o identificador correto | `EliminarDadosDoTitular`: `DELETE` disparado e aviso de solicitado |
| Identificador digitado errado | `EliminarDadosDoTitular`: botão permanece desabilitado, nada é chamado |
| Informar o que é preservado | `EliminarDadosDoTitular`: o texto do diálogo |

## Lacunas declaradas

- **L1 — Não há `<dialog>`/modal reutilizável no repo.** Este é o primeiro; se uma próxima card precisar de outro, vale extrair um componente genérico em vez de copiar este.
- **L2 — Linha sem `leadId` (apelido sumiu por fora) não tem ação nenhuma**, nem aviso do motivo — mesma lacuna L1 já declarada na TEC-340/341, agora também do lado da eliminação.
- **L3 — O aviso de "solicitação enviada" não acompanha o job.** Não há como saber, da tela, quando a eliminação de fato terminou; só refazer a fila mais tarde mostra a linha sumir.
- **L4 — O SRS do frontend não está no repo.** A regra vem do texto da card.
