# TEC-323 — O detalhe do lead no painel: resumo, contato e qualificação

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-323](https://eduardodurieuxlopes.atlassian.net/browse/TEC-323) — épico TEC-304
**Branch:** `feat/tec-323-detalhe-do-lead`
**Depende de:** TEC-193 (`GET /api/v1/leads/{leadId}`), TEC-175 e TEC-176 (o resumo), TEC-321 (a lista), TEC-312 (guarda por permissão), TEC-313 (estados)

## O que existe quando a card começa

`GET /api/v1/leads/{leadId}` devolve contato (telefone só mascarado, `email` sempre nulo), status, score, o resumo do handoff mais recente com `fallback`, a qualificação, o histórico de score, as recomendações, os agendamentos e os follow-ups. A rota exige `VER_DETALHE_DO_LEAD` (ADMIN, GERENTE e CORRETOR; LEITURA não) e responde 403 ao CORRETOR que abre o lead de outro. **Cada abertura grava `DADO_PESSOAL_ACESSADO` na trilha**, e o registro é comitado antes de o conteúdo sair (D3 da TEC-193).

A lista da TEC-321 existe, e as linhas não abrem nada (L4 de lá).

## D1 — A tela é `/leads/[leadId]`, guardada por `VER_DETALHE_DO_LEAD`

A página confere a permissão antes de buscar, no molde da D3 da TEC-312. O recorte "só os próprios leads" é do backend. A página transforma o 403 dele em "Sem permissão", e esse é o quarto cenário do Gherkin.

**A linha da lista vira link só para quem tem a permissão.** LEITURA vê a lista (`VER_LEADS`) e não o detalhe; um link para ela seria um clique que sempre termina em "Sem permissão".

## D2 — Links comuns, e nunca `next/link`

**Abrir o detalhe escreve na trilha de auditoria.** O `<Link>` do Next faz prefetch das rotas que aparecem na tela. Numa rota dinâmica, o prefetch padrão vai só até o `loading.tsx` mais próximo (referência de `link`, Next 16: *"the partial route down to the nearest segment with a loading.js boundary"*). Como o detalhe tem `loading.tsx`, a página não roda, e nada é gravado.

**A linha é um `<a>` assim mesmo**, porque essa proteção depende de duas coisas que ninguém lê como regra de auditoria: o `loading.tsx` continuar existindo e ninguém escrever `prefetch={true}`. Qualquer uma das duas faria o prefetch rodar a página no servidor com o cookie da sessão, e o servidor chamar o FastAPI. Uma lista de 25 linhas gravaria até 25 acessos a dado pessoal que ninguém abriu, e a trilha deixaria de distinguir leitura de rolagem. Com `<a>`, a garantia não depende de nenhuma das duas.

- **Os links do detalhe de volta para a lista são `<Link>`**, como o lint do Next exige: a lista não grava nada.
- **Correção desta seção durante a implementação.** A primeira versão dizia que o prefetch padrão rodaria a página, e a documentação do Next 16 desmentiu. A decisão ficou; o motivo mudou de "evita um defeito" para "não depende de duas condições frágeis".

## D3 — O resumo é dividido nos seis blocos pelos marcadores

O texto do resumo traz os seis títulos literais da TEC-175 (`## Quem e o lead` … `## Proxima acao`), e o validador de lá garante que os seis existem, em ordem, antes de o texto ser gravado. O resumo de contingência da TEC-176 reusa os mesmos marcadores. A tela corta o texto neles e desenha seis seções com os títulos em português com acento ("Quem é o lead", "Imóveis apresentados", "Próxima ação"). É texto de tela, e a regra de acento da TEC-267 vale para o que alguém lê.

- **O rótulo sai de `fallback`**: "Gerado pelo assistente" ou "Resumo simplificado", ao lado do título da seção.
- **No resumo simplificado, o preâmbulo entre colchetes some.** A TEC-176 abre o texto com `[resumo automatico simplificado -- o modelo de linguagem nao gerou...]`, uma nota escrita para quem recebe o texto cru, na notificação. Na tela, a etiqueta diz o mesmo, e as duas juntas seriam repetição.
- **Texto que não se deixa cortar sai inteiro**, como veio. Não deveria acontecer, porque o validador garante os marcadores. Se acontecer, mostrar o texto é melhor que esconder o resumo.
- **Sem resumo** (lead que nunca teve handoff, ou handoff cujo resumo ainda não foi gravado), a seção diz isso, e continua sendo a primeira.

## D4 — Agendamentos mostram o que existe, e não "Ainda não medido"

O terceiro cenário do Gherkin parte de *"a fonte de agendamentos ainda não existe"*. **Ela existe desde a TEC-371**, e a TEC-193 já registrou isso no levantamento dela, e a rota devolve os agendamentos do lead. Escrever "Ainda não medido" sobre um dado que o sistema tem seria afirmar uma falta que não é verdadeira, o oposto do que a TEC-313 construiu esse texto para dizer.

A seção lista tipo, horário e status de cada agendamento. Lista vazia diz "Nenhum agendamento", o estado vazio da TEC-313: há fonte, e não havia nada.

## D5 — O que entra, e na ordem da card

| ordem | seção | nesta card |
| --- | --- | --- |
| 1 | resumo inteligente | sim (D3) |
| 2 | contato | sim: telefone mascarado e canal; e-mail "Não informado", sem fonte (D7 da TEC-195) |
| 3 | qualificação | sim (D6) |
| 4 | histórico de score | não: TEC-325 |
| 5 | imóveis recomendados | não: TEC-325 |
| 6 | agendamentos | sim (D4) |
| 7 | follow-ups | sim: tentativa, temperatura e quando |
| 8 | transcrição | não: TEC-324 |

- **Nota (TEC-324, 27/09/2026):** a transcrição entrou, como "Conversa", na última posição. As falas vêm de outra rota, pedida em paralelo com o detalhe.
- **Nota (TEC-325, 27/09/2026):** histórico de score e imóveis recomendados entraram nas posições 4 e 5. Ver `docs/superpowers/specs/2026-09-27-tec-325-historico-e-recomendacoes-design.md`.

**As seções de outras cards não aparecem**, nem como "em breve". Cada uma entra na posição dela quando a card chegar. A resposta já traz os dados do histórico e das recomendações; a página só não os desenha.

**Revelar o telefone também não é desta card**: é a TEC-330. O contato mostra o mascarado e mais nada.

## D6 — A qualificação

Os campos-base aparecem sempre, com "Não informado" no que o agente ainda não extraiu: intenção, região, tipo, quartos, vagas, faixa de preço, urgência, forma de pagamento e se tem imóvel para vender. É o que o corretor quer saber antes de ligar, inclusive o que falta perguntar. Os campos de investidor (ticket, retorno, horizonte, tolerância a reforma, perfil) só aparecem quando algum deles está preenchido. Para quem compra para morar, seriam sete linhas de "Não informado".

- Faixa de preço em reais, a partir dos centavos. Faixa aberta dos dois lados aparece como "a partir de" ou "até".
- `camposRecusados` vira uma linha "Recusou informar", porque recusa não é o mesmo que "ainda não perguntado" (TEC-148).
- `qualificacao` nula diz "O agente ainda não extraiu nenhum dado deste lead", e não mostra uma grade de "Não informado". A D4 da TEC-193 faz dessa distinção um fato só.
- Valor fora do vocabulário conhecido aparece humanizado (`LONGO_PRAZO` vira "Longo prazo"). Os campos de investidor não têm vocabulário fechado no backend, e fixar um aqui obrigaria a tela a acompanhar o agente a cada valor novo.

## D7 — Os estados

| situação | tela |
| --- | --- |
| 401 | apaga a sessão e vai ao login (TEC-310, D5) |
| 403 | `SemPermissao`, com o link para a lista (quarto cenário) |
| 404, ou 422 de `leadId` que não é UUID | "Lead não encontrado", com o link para a lista |
| outros, ou backend fora | `ErroDeCarga` com o código da resposta |

**`no-store`**, como a lista. A resposta é por usuário, e o score muda a cada turno. Além disso, uma resposta cacheada seria uma leitura que não passou pela trilha.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| resumo no topo, "Gerado pelo assistente" | teste da página: a primeira seção é o resumo, com os seis títulos e o rótulo |
| resumo determinístico sinalizado | teste da página: `fallback: true` mostra "Resumo simplificado" e esconde o preâmbulo |
| agendamentos ainda sem fonte | **não exercitado como escrito**: a fonte existe (D4). O teste afirma a lista e o vazio |
| lead de outro corretor | teste da página: 403 do backend vira "Sem permissão". O recorte em si é teste de integração da TEC-193 |

## Lacunas declaradas

- **L1 — o terceiro cenário do Gherkin não vale mais** (D4). Quem escreveu a card não sabia que a fonte chegaria antes da tela.
- **L2 — histórico de score, recomendações e transcrição não aparecem** (D5): TEC-325 e TEC-324.
- **L3 — não há nome**, pela mesma razão da lista: o título da tela é o telefone mascarado.
- **L4 — cada abertura da tela é um registro na trilha**, recarregar inclusive. É a D3 da TEC-193 funcionando, e não defeito desta tela, mas quem ler a trilha precisa saber que "abriu três vezes" pode ser um F5.

**Sem emenda ao SRS do agente.** Nada no backend muda, e o contrato desta card é o SRS do frontend (RN-FE-08.x), que não está versionado no repo.
