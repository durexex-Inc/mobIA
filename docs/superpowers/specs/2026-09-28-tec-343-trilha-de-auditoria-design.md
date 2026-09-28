# TEC-343 — Consultar a trilha de auditoria com filtros por autor, tipo e período

**Status:** implementado (28/09/2026)
**Card:** [TEC-343](https://eduardodurieuxlopes.atlassian.net/browse/TEC-343) — épico TEC-306
**Branch:** `feat/tec-343-trilha-de-auditoria`
**Depende de:** TEC-206 (a API da trilha), TEC-312 (menu por papel e área de administração)

## O que existe quando a card começa

- **`GET /api/v1/auditoria`** (`src/mobia/api/routes/auditoria.py::listar`) já existe inteiro: filtros por `ator` (igualdade exata de texto), `acao` (repetível, `IN`), `de`/`ate` (intervalo semiaberto `[de, ate)`, exige fuso), `channel`+`conversationKey` (os dois juntos), `limite` (1–100, padrão 25) e `cursor`. Exige `VER_AUDITORIA`, que só o ADMIN tem. Resposta: `{itens: [...], proximoCursor}`. Só `GET` — os outros métodos são 405, o que já satisfaz "a trilha não pode ser alterada" no nível da API.
- **Cada item** (`_item`, `auditoria.py:28-44`): `id`, `criadoEm`, `atorTipo`, `atorId`, `acao`, `entidade`, `entidadeId`, `campo`, `detalhes` (dict fechado), `ip`, `correlationId`. `leadRef` nunca sai — é chave de busca interna, não dado para a tela.
- **"Acesso negado" já é gravado automaticamente**, por toda rota que usa `Depends(Exige(...))` (`src/mobia/api/autorizacao.py::registrar_negativa`) — não é algo que esta card precise instrumentar. `detalhes` de um `ACESSO_NEGADO` tem `permissao`, `motivo`, `papel`, `metodo`.
- **`atorId` é sempre o `usuario_id` (UUID)**, nunca um nome (`autorizacao.py::como_ator`). Não existe, em nenhuma rota, uma listagem de usuários (ADMIN/GERENTE/LEITURA) com nome — `/api/v1/corretores` é outra tabela, só de `CORRETOR`.
- **`/admin` (TEC-312, D5)** já lista "Trilha de auditoria" como seção "ainda não disponível" (`admin/page.tsx:25`).
- **O padrão de página com filtro + cursor** já existe na lista de leads (TEC-321/322): `lib/leads.ts` (módulo puro com `filtrosDaUrl`/`urlDaLista`/posição), `components/FiltrosDeLeads.tsx` (form GET, client component, aplica no `onChange`), `components/PaginacaoDeLeads.tsx` (paginação numerada ≥1024px + "Carregar mais" abaixo disso), `lib/servidor/leads.ts` (`buscarLeads`/`buscarPaginas`, paralelo quando acumula).

A regra RN-FE-15.4 vem do texto da card: o SRS do frontend não está no repo.

## D1 — "Filtrar por autor" é colar um `usuario_id`, não digitar um nome

O Gherkin da card fala em "filtra revelações... feitas por Anelise", mas o sistema não tem, em lugar nenhum, uma tabela que ligue nome a `usuario_id` fora dos que já são `CORRETOR`. O campo "Autor" do filtro é um texto livre que vai direto para `?ator=`, com o rótulo dizendo que é o identificador (UUID) do usuário — o mesmo tipo de decisão da TEC-341/342 (não inventar um identificador que a card não define). Ver a lacuna L1.

## D2 — Só "Carregar mais", sem paginação numerada

A lista de leads (TEC-322) tem duas navegações (numerada ≥1024px e "Carregar mais" abaixo) porque uma tabela de leads é algo que se folheia e se retoma. Uma trilha de auditoria se lê como um log: de trás para frente, sem pulo para uma página específica. Por isso `lib/auditoria.ts` simplifica o modelo de posição da TEC-322 (`cursor` + `anteriores`, sem a flag `acumular`): toda "próxima página" pedida ACUMULA, e a tela só desenha "Carregar mais". Menos um mecanismo, menos um teste, sem perder nada que a card peça.

## D3 — O filtro de tipo é de um valor por vez, não multi-seleção

O backend aceita `?acao=X&acao=Y` (`IN`), mas nenhum cenário da card pede "dois tipos ao mesmo tempo" — cada exemplo do Gherkin filtra um tipo (`DADO_PESSOAL_ACESSADO` ou `ACESSO_NEGADO`) por vez. O `<select>` do filtro devolve um valor só; a chamada ao backend manda `acao=<valor>` como filtro de um elemento. Se uma card futura pedir multi-seleção, o backend já aceita — é troca de UI, não de contrato.

## D4 — Período é dois `<input type="date">`, convertidos no servidor

A URL da tela guarda `de=2026-09-01` e `ate=2026-09-30` (datas, sem hora — o que a pessoa realmente escolhe). Quem converte para o `datetime` com fuso que o backend exige é `lib/servidor/auditoria.ts`, no fuso único da POC (`America/Sao_Paulo`, `-03:00` fixo, sem DST desde 2019 — o mesmo fuso de `lib/titular.ts`): `de` vira início do dia (`00:00:00-03:00`), e `ate` vira início do dia SEGUINTE, porque o intervalo do backend é semiaberto `[de, ate)` — sem isso, filtrar "até 30/09" excluiria o próprio dia 30.

## D5 — A tabela não tem nenhuma ação por linha

Nenhuma opção de editar ou excluir aparece nunca — nem escondida atrás de permissão, porque a permissão para isso não existe na matriz. É o cenário 2 do Gherkin ("não há opção de editar nem de excluir") garantido por não existir o botão, não por ele estar desabilitado.

## D6 — `detalhes` aparece como pares chave: valor, sem tradução

`detalhes` é um dict pequeno e fechado (no máximo `gatilho`/`permissao`/`motivo`/`papel`/`metodo`), já validado pelo backend contra um vocabulário fechado. A tela imprime `chave: valor` para cada entrada presente (pulando `null`), sem mapear para outro texto — são identificadores de sistema (papel, permissão, motivo), e o público desta tela é quem já lê `ACESSO_NEGADO`/`VER_AUDITORIA` como são.

## `/admin`

A seção "Trilha de auditoria" (`admin/page.tsx:25`) ganha `href: '/admin/auditoria'`.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais, reaproveitando a sessão ADMIN (por MFA) e o histórico real de eventos das verificações da TEC-341/342 (exportação, eliminação, tentativas negadas).

| passo | resultado |
| --- | --- |
| `/admin/auditoria` | a trilha real, do mais recente ao mais antigo: `LEAD_ANONIMIZADO`, `TITULAR_SOLICITOU`, `DADOS_EXPORTADOS` |
| gerar um 403 de verdade (GERENTE chamando `/api/v1/auditoria`) e filtrar por `acao=ACESSO_NEGADO` | a tentativa aparece, com `atorId`, papel, método e a permissão negada nos detalhes |
| filtrar por `ator=<o usuario_id do GERENTE>` | o mesmo evento, e só ele |
| `/admin` | o link "Trilha de auditoria" aponta para `/admin/auditoria` |

## Testes

- `lib/auditoria.ts`: `filtrosDaUrl`/`urlDaLista` (ida e volta pela URL), `inicioDoDia`/`fimDoDia` (a virada de mês/ano), `posicaoDaUrl`/`posicaoDaProxima` (acumula sem pular).
- `lib/servidor/auditoria.ts`: `buscarTrilha` monta os query params certos (incluindo a conversão de `de`/`ate`); `buscarPaginas` acumula em paralelo.
- `FiltrosDeAuditoria`: aplica no `onChange`, preserva os outros filtros ao mudar um.
- A página: guarda `VER_AUDITORIA` (403 vira "Sem permissão", nenhum dado é pedido); a lista filtrada por ator; o filtro por `ACESSO_NEGADO` mostrando a tentativa; nenhum botão de editar/excluir na tabela; "Carregar mais" quando há `proximoCursor`; 401 e erro de carga.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Encontrar as revelações de um usuário | página: filtro por `ator` (D1) e por `acao=DADO_PESSOAL_ACESSADO` mostrando os eventos com `entidadeId`/`campo`/`criadoEm` |
| Trilha não pode ser alterada | tabela: nenhum controle de editar/excluir (D5); API: 405 nos outros métodos (já coberto pela TEC-206) |
| Acesso negado também aparece | página: filtro por `acao=ACESSO_NEGADO` mostrando a tentativa |

## Lacunas declaradas

- **L1 — Não há como resolver nome → `usuario_id`.** O ADMIN precisa já saber ou copiar o UUID de outro evento para filtrar "por Anelise". Resolver isso é uma tela de usuários que não existe ainda.
- **L2 — O SRS do frontend não está no repo.** A regra vem do texto da card.
