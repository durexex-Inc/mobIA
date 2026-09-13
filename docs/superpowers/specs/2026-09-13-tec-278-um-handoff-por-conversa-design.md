# TEC-278 — Impedir que um handoff escalado gere um segundo handoff para o mesmo lead

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-278](https://eduardodurieuxlopes.atlassian.net/browse/TEC-278) — História, Should (MoSCoW), prioridade High. Origem: lacuna **L5** do desenho da TEC-178, aberta pela revisão final daquela branch. Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Anelise, gerente comercial, quero ser cobrada uma vez por lead esquecido, para que a fila de escalada continue significando alguma coisa quando a equipe crescer."*

## Objetivo

O índice parcial único `uq_handoffs_conversa_pendente` cobre apenas `status = 'PENDENTE'`. Era o suficiente até 13/09/2026 porque **nada tirava handoff de `PENDENTE`** — a L4 do desenho da TEC-174 dizia, com todas as letras, que o índice *"nunca libera a conversa enquanto a TEC-178 não existir — e é o comportamento certo"*.

A TEC-178 e a TEC-179 existem. Um handoff que sai de `PENDENTE` libera a chave, e o próximo gatilho insere outro.

Concretamente, com um handoff escalado: 10:15 a varredura marca `ESCALADO` e cobra a gerente; 10:17 o lead pergunta sobre outro imóvel e a intenção dispara; 10:17 nasce um **segundo** handoff, com resumo novo (uma chamada paga ao provedor) e prazo novo; 10:32 a gerente é cobrada **de novo**, pelo mesmo lead.

## O que a exploração descobriu, e que muda o desenho

**`CONCLUIDO` não tem um único escritor.** O enum existe desde a TEC-174 e nada nunca o escreveu — a busca em `src/mobia/domain/handoff/` não devolve nenhuma escrita.

Isso derruba o caminho óbvio. Alargar o índice para "tudo que não é `CONCLUIDO`" e parar por aí prenderia cada conversa ao seu primeiro handoff **para sempre**: um lead que volta em três meses com outra intenção seria mesclado num handoff obsoleto em vez de gerar um novo. O índice precisa de uma válvula de saída, e a válvula não existia.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `uq_handoffs_conversa_pendente` | cobre só `PENDENTE` | D1 |
| `Status.CONCLUIDO` | **sem escritor**, desde a TEC-174 | D2 |
| `POST /conversas/devolver` | existe (TEC-179), só devolve a voz ao agente | D2 |
| `POST /conversas/assumir` | existe (TEC-179), aceita o handoff junto (D6 de lá) | é o espelho de D2 |
| `registrar_handoff` | `ON CONFLICT DO UPDATE` já mescla gatilho e escala prioridade | D1, D4 |
| `HandoffRegistrado.criado` | já distingue INSERT de UPDATE por `xmax` | D4 |
| RN-02.3 | junta "handoff concluído" e "conversa encerrada" | D3 |
| encerramento de conversa | **não implementado** (TEC-130, A fazer) | D3, L2 |

## Decisões

### D1 — O índice cobre todo status menos `CONCLUIDO`

`postgresql_where=text("status <> 'CONCLUIDO'")`, na migration e no `index_where` de `registrar_handoff`, que têm de andar juntos.

O `ON CONFLICT DO UPDATE` que já existe passa a encontrar o handoff aberto qualquer que seja o status. Ele mescla o gatilho em `gatilhos_adicionais` (sem duplicar — a checagem de pertinência da TEC-174) e escala `prioridade` para `ALTA` quando é o caso, **exatamente como faz hoje**. A card não muda esse bloco; muda quando ele é alcançado.

**O status NÃO é tocado.** Um gatilho novo sobre um handoff `ESCALADO` não o devolve a `PENDENTE`: isso o reinscreveria na varredura e re-escalaria o mesmo lead, que é precisamente o que esta card veio impedir.

Continua sendo invariante de schema e não disciplina de consulta — o mesmo argumento da L4 da TEC-174 e da D6 da TEC-178. A corrida é real: a suíte roda com oito workers.

### D2 — `devolver` conclui o handoff

Espelho exato da D6 da TEC-179: **`assumir` → `ACEITO`, `devolver` → `CONCLUIDO`.** Na mesma transação da devolução, o handoff aberto daquela conversa passa a `CONCLUIDO`.

Duas razões. É a válvula de saída sem a qual a D1 prenderia a conversa para sempre. E é o momento semanticamente certo: o handoff existe para entregar o lead a um humano, e quando o humano devolve a conversa ao agente, essa entrega acabou.

Dá ao `CONCLUIDO` o primeiro escritor da vida dele.

**Condicionado no próprio `WHERE`, com `RETURNING`** — nunca um `SELECT` antes. Mesmo molde de `assumir`, de `aceitar` e de `escalar_vencidos`.

**Uma conversa sem handoff aberto devolve normalmente.** Nem toda conversa assumida gerou handoff; exigir um quebraria o caso comum, pelo mesmo argumento que a Task 6 da TEC-179 já aplicou a `assumir`.

Decisão do Eduardo em 13/09/2026.

### D3 — Concluir o handoff não encerra a conversa

A **RN-02.3** diz que a conversa é encerrada *"após 30 dias sem interação, ou por handoff concluído, ou por opt-out"*, e que nova mensagem depois disso abre uma conversa nova.

Ela junta dois fatos que este sistema precisa separar. O handoff acaba quando o humano termina o atendimento — e devolver a conversa ao agente é o contrário de encerrá-la: é retomar o atendimento automático. Se `devolver` encerrasse a conversa, o lead que o corretor acabou de atender voltaria a falar com um agente sem memória do que acabou de acontecer.

**Vira emenda à RN-02.3:** concluir o handoff **não** é, por si, encerramento de conversa. O encerramento segue sendo por inatividade (TEC-130) ou opt-out.

Decisão do Eduardo em 13/09/2026. **A TEC-130 tem de respeitar essa separação quando chegar**, e é por isso que a emenda existe em vez de uma lacuna: deixar o SRS dizendo uma coisa e o código fazendo outra é a classe de discrepância que este repositório trata como o defeito mais caro que tem.

### D4 — A mesclagem não renotifica nem paga o provedor, e isso já é verdade

`registrar_handoff` devolve `criado=False` quando o `ON CONFLICT` fez UPDATE — distinguido por `xmax`, não por carimbo de tempo (ver o comentário lá, que explica por que comparar carimbos daria falso positivo sob concorrência). O `AgendadorDeResumoPort` só enfileira sob `criado`.

Então um gatilho novo sobre handoff aberto **não** gera resumo novo, **não** enfileira notificação e **não** paga chamada ao modelo. Nada disso é construído aqui: a guarda já existe e está documentada em `handoff/agendador.py`.

O que a card muda é a frequência com que esse caminho é exercido — de "quase nunca" para "toda vez que um lead com handoff aberto dispara um gatilho".

**Consequência declarada:** ninguém é avisado de que o lead falou de novo. O corretor recebeu a notificação do primeiro gatilho e o `gatilhos_adicionais` acumula o resto, sem leitor. É a L1.

## Emendas ao SRS

- **RN-02.3** — concluir o handoff **não** encerra a conversa; o encerramento segue sendo por inatividade ou opt-out, e a regra juntava dois fatos que o sistema precisa separar (D3).
- **RN-16.4** — `POST /api/v1/conversas/devolver` passa a **concluir** o handoff aberto da conversa, espelhando a Emenda E-02 que fez `assumir` aceitá-lo (D2).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Lead escalado que continua conversando não gera handoff novo | exercitado, com a prova de que a gerente não é cobrada duas vezes |
| Lead aceito que continua conversando não gera handoff novo | exercitado |
| Conversa concluída aceita um handoff novo | exercitado, e é o que a D2 torna alcançável |
| A corrida continua arbitrada pelo banco | exercitado |

## Lacunas declaradas

### L1 — Ninguém sabe que o lead falou de novo

Os gatilhos acumulam em `gatilhos_adicionais` e a prioridade pode escalar para `ALTA`, mas **nada disso chega a ninguém**: a notificação saiu no primeiro gatilho, os canais da TEC-177 não entregam (emenda E-02 da RN-16.2), e não há painel (E8).

Na prática, um lead que insiste enquanto seu handoff está escalado fica mais urgente **no banco** e igualmente invisível fora dele.

### L2 — O handoff aceito pela rota de handoffs fica sem como concluir, e o contorno é desajeitado

`devolver` exige a conversa silenciada, e silenciar é o que `assumir` faz. Um handoff aceito por `POST /api/v1/handoffs/{id}/aceitar` — sem passar por `assumir` — não tem caminho direto para `CONCLUIDO`, e com a D1 essa conversa fica travada para handoff novo.

**O contorno existe:** `assumir` funciona em conversa sem handoff pendente (provado por teste na TEC-179), então dá para assumir e em seguida devolver. É desajeitado e ninguém vai adivinhá-lo sem ler isto.

É a **L5 da TEC-179 mordendo de novo** — aceitar o handoff e assumir a conversa são dois botões para o que o corretor entende como um ato só. Fechar de vez é fazer `aceitar` silenciar também.

### L3 — Um handoff escalado que ninguém jamais assume mescla gatilhos para sempre

Com a D1, a conversa fica presa a ele até alguém assumir e devolver. Não há prazo, não há varredura, não há alerta.

É o desfecho **desejado** para um handoff desatendido — a gerente é cobrada uma vez e o lead não multiplica a fila —, mas é permanente. Repare que ele soma com a L4 da TEC-179 (nada devolve uma conversa sozinho): as duas juntas significam que **um handoff pode ficar aberto indefinidamente sem que nada no sistema reclame**.

### L4 — Nada migra os handoffs abertos que já existem

A migration muda o índice; não mexe em linha. Uma conversa que hoje tenha dois handoffs abertos (um `ESCALADO` antigo e um `PENDENTE` novo, criados antes desta card) **viola o índice novo**, e a criação do índice único falha.

O desenho assume que isso não existe no ambiente de destino — o épico nunca rodou em produção. **A migration tem de falhar alto se existir**, não contornar em silêncio: dois handoffs abertos para a mesma conversa é exatamente o estado que esta card declara impossível, e descobri-lo na migration é melhor que descobri-lo depois.

## Fora de escopo

O encerramento de conversa (TEC-130). A rota de envio manual do corretor. Fazer `aceitar` silenciar (L5 da TEC-179). Identidade autenticada (TEC-201). A varredura de recuperação de handoffs sem prazo (TEC-279, a próxima).
