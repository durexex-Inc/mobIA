# TEC-340 — Acompanhar a fila de pedidos do titular com prazo de 15 dias

**Status:** implementado (28/09/2026)
**Card:** [TEC-340](https://eduardodurieuxlopes.atlassian.net/browse/TEC-340) — épico TEC-306
**Branch:** `feat/tec-340-fila-do-titular`
**Depende de:** TEC-207 (a API da fila), TEC-312 (menu por papel e "Sem permissão")

## O que existe quando a card começa

- **`GET /api/v1/titular/solicitacoes`** (`src/mobia/api/routes/titular.py::solicitacoes`):
  - devolve `{itens: [{id, tipo, origem, status, recebidaEm, prazoEm, atendidaEm, motivoDaRecusa, leadId}]}`, por prazo, quem vence primeiro no topo;
  - aceita `?status=ABERTA|ATENDIDA|RECUSADA`;
  - exige `ATENDER_TITULAR`, que só o ADMIN tem.
- **`prazoEm` é `recebidaEm + 15 dias`** (`PRAZO_DO_TITULAR`), calculado pelo servidor na abertura.
- **O vocabulário do servidor é menor que o da card:**
  - tipos só `ACESSO` e `ELIMINACAO` — não há correção nem portabilidade;
  - origens `WHATSAPP`, `ADMIN` e `RETENCAO`, esta última para o registro da anonimização automática, que já nasce atendida.
- **O painel não tem tela nenhuma para isso.** A área de administração (TEC-312) é só navegação, com as seções ainda sem tela.

A regra RN-FE-15.1 vem do texto da card: o SRS do frontend não está no repo.

## D1 — A tela é `/admin/titular`, e a guarda é a permissão da API

- **Página nova em `/admin/titular`**, listada na área de administração como "Pedidos do titular".
- **A guarda é `ATENDER_TITULAR`**, a mesma permissão que a rota exige, e não o papel. A card diz "somente ADMIN", e é a matriz de permissões que faz isso ser verdade. O GERENTE que abre o endereço direto vê "Sem permissão" (terceiro cenário).
- `ATENDER_TITULAR` entra em `PERMISSOES_DE_ADMIN`: a área de administração agrupa as telas pelas permissões que elas exercem.
- **O backend continua sendo quem recusa**: 403 dele vira "Sem permissão", e 401 leva ao login, como nas outras páginas do painel.

## D2 — A fila mostra os pedidos abertos

- **A página pede `?status=ABERTA`.** A fila é o que ainda precisa de resposta, e é para isso que a card existe ("para não perder o prazo legal").
- Atendidos e recusados não têm prazo a perder e ficam de fora. O histórico de cada pedido está na trilha de auditoria (TEC-343).
- Os registros da retenção nascem atendidos, e por isso nunca aparecem.

## D3 — O prazo restante é em dias de calendário, no fuso de São Paulo

- **Restante = data do prazo − data de hoje**, as duas em `America/Sao_Paulo`, o fuso único da POC.
  - Aberto há 2 dias mostra 13; há 12 mostra 3; há 14 mostra 1. É a tabela da card, e não depende da hora do dia.
  - Uma conta por horas daria 12 ou 13 conforme a hora, e o prazo que a pessoa lê é uma data.
- **Os textos:**
  - "13 dias", "1 dia";
  - "Vence hoje" com 0;
  - "Vencido há 2 dias" (ou "há 1 dia") com o prazo já passado.
- **Destaque com 3 dias ou menos, inclusive vencido.** A linha ganha um marcador ⚠ decorativo (`aria-hidden`) e o texto "Prazo curto" — "Prazo vencido" quando passou. A informação está no texto, e não só na cor ou no ícone.
- A data de abertura aparece como `dd/mm/aaaa`, no mesmo fuso.

## D4 — As colunas

| coluna | conteúdo |
| --- | --- |
| Pedido | "Acesso aos dados" / "Eliminação dos dados" |
| Origem | "WhatsApp" / "Administrativo" / "Retenção" |
| Aberto em | a data |
| Prazo | o restante, com o destaque |
| Lead | link "Ver lead" para `/leads/{leadId}`, quando há `leadId` e quem vê tem `VER_DETALHE_DO_LEAD` |

- Valor desconhecido de tipo ou origem aparece como veio, pela regra de `nomeDoPapel`: é anomalia, e o valor cru é a pista.
- **Exportar e eliminar a partir da fila são as cards seguintes** (TEC-341 e TEC-342). Até lá, o ADMIN age pela API da TEC-207, e a fila mostra o que está pendente.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais. A base de dev foi semeada com um ADMIN (com MFA), um GERENTE e dois pedidos abertos: uma eliminação pelo WhatsApp, aberta agora, e um acesso administrativo retroagido 12 dias. É dado descartável, e some com a próxima suíte serial.

| passo | resultado |
| --- | --- |
| GERENTE, login e `/admin/titular` pelo endereço | "Sem permissão", com "Você entrou como Gerente" |
| ADMIN, login com o código TOTP, `/admin/titular` | o acesso: "Administrativo", 16/09/2026, "3 dias ⚠ Prazo curto", linha destacada; a eliminação: "WhatsApp", 28/09/2026, "15 dias" |
| "Ver lead" | chegou a `/leads/{id}` e mostrou "Lead não encontrado". A semente criou o pedido sem nenhuma mensagem da conversa. Um pedido real nasce de uma mensagem do lead (WhatsApp) ou de um lead que já existe (administrativo) |

## Testes

- `lib/titular`:
  - os dias restantes nos três exemplos da card, e a virada de dia no fuso de São Paulo;
  - o texto de cada caso (plural, hoje, vencido);
  - o destaque nas bordas 4 e 3;
  - os rótulos, inclusive o desconhecido.
- Página (fetch dublado, no molde de `admin/page.test.tsx`):
  - o esquema do cenário, com o destaque;
  - a origem "WhatsApp";
  - GERENTE vê "Sem permissão" sem chamar a fila;
  - 403 do backend vira "Sem permissão", 401 leva ao login;
  - a falha de carga mostra o erro;
  - a fila vazia.
- Área de administração: a seção com o link.
- Navegador: a fila com um pedido registrado pelo WhatsApp.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Destaque por prazo (2/13, 12/3, 14/1) | `lib/titular` e página |
| Pedido vindo do WhatsApp | página; navegador |
| Gerente não acessa a fila | página: GERENTE sem `ATENDER_TITULAR` vê "Sem permissão" |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — Correção e portabilidade não existem como tipo no servidor** (TEC-207). A fila mostra os dois tipos que ele registra. A portabilidade é a exportação do `ACESSO` (TEC-341).
- **L3 — A fila não atende nada.** Exportar e eliminar são a TEC-341 e a TEC-342.
- **L4 — Sem paginação.** A API devolve a fila inteira. É uma fila de pedidos abertos de uma imobiliária, e não uma lista de leads.
