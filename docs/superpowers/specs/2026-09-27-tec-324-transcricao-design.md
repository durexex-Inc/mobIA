# TEC-324 — A transcrição do lead, com "carregar anteriores"

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-324](https://eduardodurieuxlopes.atlassian.net/browse/TEC-324) — épico TEC-304
**Branch:** `feat/tec-324-transcricao`
**Depende de:** TEC-193 (`GET /api/v1/leads/{leadId}/mensagens`), TEC-323 (a página do detalhe), TEC-302 (o proxy `/bff/*`)

## O que existe quando a card começa

A rota da transcrição devolve páginas de 100 falas, por padrão, em ordem cronológica dentro da página, com `cursorAnterior` apontando para as mais antigas. Cada fala traz `autor` (LEAD, AGENTE, CORRETOR ou SISTEMA), `tipo`, `conteudo`, `retida` e `em`. **A moderação já vem resolvida pelo backend:** para ADMIN, a fala retida sai com `retida: true` e sem conteúdo; para os outros papéis, ela nem sai. **Cada página grava um `DADO_PESSOAL_ACESSADO` com `campo=transcricao`** (D3 da TEC-193).

A página do detalhe (TEC-323) reservou a última seção para a conversa. O proxy `/bff/*` existe desde a TEC-302, autentica pela sessão desde a TEC-309 e até hoje não tem consumidor.

## D1 — A primeira página vem do servidor, junto com o detalhe

A página do detalhe busca o detalhe e as 100 falas mais recentes **em paralelo**. O primeiro cenário pede as 100 falas em até 2 s no p95, e buscar em sequência somaria as duas latências sem razão, porque uma chamada não depende da outra.

**Se a transcrição falhar e o detalhe não, a página abre assim mesmo**, com a falha dentro da seção da conversa. O resumo e a qualificação continuam úteis para quem vai ligar.

**Abrir o detalhe passa a gravar dois acessos na trilha**: `detalhe` e `transcricao`. É a D3 da TEC-193 aplicada às duas rotas que a tela consome, e não uma decisão desta card.

**O preço do paralelismo é um registro a mais na recusa.** O CORRETOR que abre, pelo endereço, o lead de outro corretor dispara as duas chamadas antes de saber a resposta, e o backend grava um `ACESSO_NEGADO` por rota: dois, e não um. Esperar o detalhe para decidir se pede a transcrição pouparia essa linha, e somaria as duas latências em toda abertura legítima. A trilha erra para o lado de registrar, como a D3 da TEC-193 já aceitou.

## D2 — "Carregar anteriores" é o terceiro componente de cliente, e usa o `/bff/*`

Manter a posição de leitura ao inserir 100 falas acima não existe sem JS: é preciso medir a altura do conteúdo antes e depois e compensar a rolagem. Uma navegação completa com `?antes=` recarregaria a página inteira e voltaria ao topo, ou ao fim.

`Transcricao` é `'use client'`. Ela recebe a primeira página como prop e busca as anteriores em `GET /bff/api/v1/leads/{leadId}/mensagens?cursor=…`.

- **O proxy ganha uma entrada na allowlist:** `GET api/v1/leads/*/mensagens`. O `*` casa exatamente um segmento, e é o caso para o qual a TEC-302 o escreveu. Nenhuma outra rota de lead fica alcançável pelo navegador.
- **O navegador continua sem ver token nenhum.** Quem põe o JWT é o proxy, a partir do cookie de sessão. O componente só importa módulos puros, como os outros dois componentes de cliente.
- **Cada clique grava um acesso na trilha.** É o que a D3 da TEC-193 escolheu: carregar as anteriores é ler um trecho que a primeira página não mostrou.

## D3 — A rolagem

- **Começa na fala mais recente**: a conversa fica numa caixa com rolagem própria, que é levada ao fim na montagem. Sem caixa própria, levar ao fim seria rolar a página inteira, e o resumo, que é a primeira seção, sumiria de vista.
- **Carregar anteriores preserva a posição**: antes de inserir, guarda-se a distância entre o ponto de leitura e o fim do conteúdo; depois de inserir, a rolagem é recolocada à mesma distância do fim.

## D4 — Quem falou, sem depender de cor

Cada fala tem o **rótulo textual** do autor e o **horário**. Cor e alinhamento vêm por cima, nunca no lugar:

| autor | rótulo | lado |
| --- | --- | --- |
| LEAD | Lead | esquerda |
| AGENTE | Assistente | direita |
| CORRETOR | Corretor | direita |
| SISTEMA | Sistema | centro |

"Assistente", e não "Agente": é o nome que o resumo já usa ("Gerado pelo assistente", TEC-323), e o corretor não precisa aprender dois nomes para a mesma coisa.

**Fala sem texto** (`conteudo` nulo) mostra o tipo: "Áudio", "Imagem", "Documento" ou "Mídia", sempre com "sem texto". A rota não entrega mídia (L3 da TEC-193), e uma bolha vazia pareceria defeito. **Fala retida** mostra "Mensagem retida pela moderação", e só chega à tela para ADMIN: o filtro é do backend.

## D5 — O `aria-live`

A card pede que "mensagens novas" sejam anunciadas com `aria-live="polite"`. **Nesta tela não chega mensagem nova com ela aberta**: não há atualização em tempo real, que é Won't (TEC-320), e a conversa só muda ao recarregar.

O que muda com a tela aberta é o carregamento das anteriores, e é isso que a região `aria-live="polite"` anuncia: "100 falas anteriores carregadas", ou a falha. A lista das falas **não** é região viva: anunciar 100 falas antigas de uma vez seria ruído, e não seria "nova".

## D6 — Os estados do "carregar anteriores"

| situação | o que acontece |
| --- | --- |
| `cursorAnterior` nulo | o botão não aparece, e a caixa diz "Início da conversa" |
| carregando | o botão fica desabilitado e diz "Carregando…" |
| 401 | "Sua sessão terminou.", com o link para entrar de novo voltando a este lead |
| outra falha | "Não foi possível carregar as falas anteriores.", e o botão continua para tentar de novo |

## Critérios de aceite

| cenário | onde |
| --- | --- |
| conversa longa dentro do SLA | **o p95 não é medido nesta card** (L1). O teste afirma que detalhe e transcrição são pedidos em paralelo, e que a caixa começa no fim |
| carregar anteriores | teste do componente: as 100 falas entram acima e a distância até o fim é preservada |
| autor sem depender de cor | teste do componente: rótulo e horário em cada fala dos quatro autores |
| fala retida (ADMIN / CORRETOR) | ADMIN: teste do componente com `retida: true`. CORRETOR: o filtro é do backend, com teste de integração na TEC-193; a tela não tem o que filtrar |

## Lacunas declaradas

- **L1 — o SLA de 2 s no p95 não é medido.** Não há medição de navegador na suíte; os testes de latência do backend ficam fora do `addopts` (`-m 'not perf'`). A TEC-357 mede Web Vitals em homologação.
- **L2 — não há "mensagem nova" com a tela aberta** (D5): a conversa atualiza ao recarregar.
- **L3 — mídia não abre**, pela L3 da TEC-193: a fala mostra o tipo e "sem texto".
- **L4 — a caixa com rolagem própria em toda a altura da tela é desenho desta card**, e não da card: é o que permite começar no fim sem esconder o resumo.

**Sem emenda ao SRS do agente**: o backend não muda.
