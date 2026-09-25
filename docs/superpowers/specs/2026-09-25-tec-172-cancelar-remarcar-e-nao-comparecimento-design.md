# TEC-172 — Cancelar, remarcar e registrar não comparecimento

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-172](https://eduardodurieuxlopes.atlassian.net/browse/TEC-172) — épico TEC-164
**Branch:** `feat/tec-172-cancelar-remarcar-e-nao-comparecimento`
**Origem:** RF-12, RN-12.3, RN-12.4, RN-12.5, CA-12.2 (SRS v1.0). Bloqueada por TEC-170 (mergeada em 25/09) e TEC-150 (o motor de score, que existe).

## Objetivo

Um agendamento que não vai acontecer para de travar a agenda e para de mentir sobre o lead: cancelamento libera o slot e avisa o corretor, remarcação preserva o vínculo com o original, e não comparecimento custa 15 pontos de score com trilha.

## O que esta card não entrega, dito antes

**Nenhum caminho de produção chama nada disto.** Como na TEC-170 e na TEC-171: não há conversa que cancele (`domain/agente/turno.py` não importa nada de `domain/agendamento/`) e não há rota administrativa pela qual o corretor marque `NO_SHOW` — o dashboard é a E8, que não existe. Esta card entrega as **transições**, a trilha e o convite de remarcação; quem as ligar à conversa e à interface chama as funções depois.

Consequência direta: **o lembrete de 24 horas da TEC-171 continua oferecendo "remarcar" e "cancelar" sem que nada leia a resposta.** Esta card constrói o que a resposta acionaria, e não o leitor dela. A lacuna encolhe pela metade e não fecha.

**Fora, e continuam esperando:**

- A cadência de reengajamento em si (RF-13, já construída) e a taxa de no-show no dashboard (E8), que a própria card põe fora.
- Lista de espera sem disponibilidade em 72 horas (TEC-169), a última card do épico.
- Os indicadores de agendamento do painel de funil, `null` desde a Emenda E-01 da RN-17.1. Esta card ainda não cria agendamento nenhum por caminho de lead.

## D1 — O vocabulário de status, e os dois desvios em relação à RN-12.5

`StatusDoAgendamento` ganha **`CANCELADO`**, **`REAGENDADO`**, **`REALIZADO`** e **`NO_SHOW`**, e o `CHECK` de `agendamentos.status` cresce junto (migration). Dois desvios, os dois declarados:

**`PROPOSTO` não entra.** `RESERVADO` é o nome que a TEC-168 deu exatamente a esse fato — a reserva com lock otimista de 5 minutos da RN-11.4 —, e a RN-12.5 nomeia o mesmo estado de outro jeito. Acrescentar `PROPOSTO` criaria um valor que nenhum caminho escreve e que toda consulta teria de lembrar de incluir: entrada morta de vocabulário, e a segunda grafia do mesmo estado que o `CHECK` passaria a aceitar em silêncio.

**`EXPIRADO` fica, e a RN-12.5 não o tem.** Ele é a reserva atropelada por outra (TEC-168, D3) — um fato que a lista da RN-12.5 não modela. Apagá-lo exigiria decidir para onde vão as linhas que já o têm.

## D2 — "Libera o slot" não precisa de código: já é a constraint

A exclusão por intervalo (migration 0044) é:

```sql
EXCLUDE USING gist (corretor_id WITH =, tstzrange(inicio, fim, '[)') WITH &&)
  WHERE (status IN ('RESERVADO', 'CONFIRMADO'))
```

O `WHERE` já exclui **tudo** o que não é um desses dois. Um `UPDATE` que põe `CANCELADO` ou `REAGENDADO` tira a linha do índice no mesmo statement, e o slot fica livre para a próxima reserva **no commit** — sem job, sem varredura, sem espera. A CA-12.2 pede "menos de 10 segundos"; o que existe é o tempo de um `UPDATE`.

**A constraint não muda nesta card**, e é isso que precisa ser dito: parece que ela precisaria crescer junto com o vocabulário, e o contrário é que é verdade — ela já está escrita como allowlist, e por isso cada status novo nasce fora dela sem que ninguém decida nada. `REALIZADO` e `NO_SHOW` também ficam de fora, o que é certo: são fatos do passado, e um compromisso passado não disputa horário com ninguém.

## D3 — As transições, num lugar só

Quatro funções em `domain/agendamento/ciclo.py`, todas no molde de `repositorio.py::confirmar` — **um `UPDATE` com a condição inteira no `WHERE`**, sem janela entre ler "ainda vale" e gravar "mudou":

| função | de | para |
| --- | --- | --- |
| `cancelar` | `RESERVADO`, `CONFIRMADO` | `CANCELADO` |
| `remarcar` | `CONFIRMADO` | `REAGENDADO` (e cria o novo) |
| `marcar_realizado` | `CONFIRMADO` | `REALIZADO` |
| `marcar_nao_comparecimento` | `CONFIRMADO` | `NO_SHOW` |

As origens legais moram **numa tabela só** (`_ORIGENS_DE`), e não espalhadas em quatro `WHERE` escritos à mão: quatro cópias da máquina de estados divergem, e o sintoma é uma transição que passa por um caminho e é recusada por outro.

Cada função devolve um resultado tipado (`Transicionado` / `Recusado`), como `confirmar` devolve `Confirmado | Expirado` — nunca `bool`, porque quem chama precisa saber se a recusa foi "já estava assim" ou "não existe".

**Nenhuma commita**: a sessão é emprestada, como em `confirmar` e em `registrar_handoff`.

Colunas novas: `cancelado_em`, `realizado_em` e `nao_compareceu_em`, `timestamptz` nulos. São o carimbo de quando, e o que a D6 lê para saber que o convite de remarcação venceu. Um `status` sozinho não diz quando mudou.

## D4 — A remarcação preserva o vínculo

`agendamentos.origem_id`, FK nula para `agendamentos.id`. `remarcar` põe o original em `REAGENDADO` e cria o novo apontando para ele — **os dois na mesma transação**, porque um original `REAGENDADO` sem sucessor é um agendamento que sumiu da agenda sem nada no lugar.

É isso que torna a métrica de remarcação possível, que é o porquê que a card dá. Não há teto de cadeia: A → B → C encadeia por `origem_id`, e quem quiser a origem primeira sobe a cadeia.

## D5 — O sexto fator do score

O problema estrutural desta card, e o que decidiu a forma dela: **o score não é guardado, é derivado.** `calcular_score` é função pura dos cinco fatores de `LeadQualification`, e `Score.total` é a soma deles. Um `-15` gravado só na trilha evaporaria no recálculo seguinte — a trilha diria 53 e o lead valeria 68.

Decidido em conversa em 25/09/2026: **`penalidade` vira o sexto fator.**

- `lead_qualification.penalidade_pontos`, `int NOT NULL DEFAULT 0`, **acumulada** — dois no-shows custam 30.
- `Score` ganha o campo, e `total` passa a ser `soma dos cinco − penalidade`, **com piso em zero**. Um total negativo não significa nada na escala da RN-06.1 e ninguém sabe lê-lo; `temperatura_de` já trata tudo abaixo de 40 como FRIO, então o piso não esconde distinção nenhuma.
- `lead_score_audit.penalidade`, `int NOT NULL DEFAULT 0`. A premissa que a TEC-152 escreveu — *"toda linha carrega os fatores COMPLETOS do instante dela"* — continua verdadeira, e é por isso que a coluna entra na trilha em vez de ficar só na qualificação.

**Duas causas, e não uma.** `CAUSA_PENALIDADE` entra no vocabulário e é **derivada** do diff (`penalidade` no `_CAUSA_POR_FATOR`), como os outros cinco fatores; `CAUSA_NAO_COMPARECIMENTO` — que já existe desde a TEC-152, sem produtor, nomeando esta card — é informada pelo chamador como **causa externa**. As duas juntas dizem o que a trilha precisa: *o que* se moveu e *por quê* se moveu. É exatamente a distinção que `context/auditoria.py` já faz entre derivada e externa, e usar só uma delas apagaria metade da resposta.

O valor sai de `PONTOS_POR_NAO_COMPARECIMENTO = 15`, constante de módulo em `agendamento/ciclo.py` e não configuração — a RN-12.4 escreve o número, é regra do SRS, o mesmo argumento da D4 da TEC-285.

## D6 — O convite de remarcação: outra varredura, o molde da TEC-171

Decidido em conversa em 25/09/2026. A RN-12.3 diz "agenda tentativa de remarcação em 24 horas", e uma tentativa agendada que nada executa é a entidade morta que este repo recusa.

`sweep_remarcacoes`, `cron` de 5 em 5 minutos, no molde exato de `sweep_lembretes`:

- **A faixa**: devido de `cancelado_em + 24h` até `cancelado_em + 24h + 7 dias`. O piso é a RN-12.3. **O teto existe pela mesma razão que o da TEC-171** — e aqui ele resolve um segundo problema de graça: sem teto, um cancelamento de três meses atrás seria convidado na primeira passagem depois do deploy, perguntando se o lead quer remarcar algo que ele nem lembra.
- **A marca**: `agendamentos.remarcacao_convidada_em`. Mesma semântica da TEC-171 — **"resolvido", e não "entregue"** —, gravada também quando a guarda recusa, nula só na falha de canal. O motivo é o mesmo e não se repete aqui: está na docstring da migration 0049.
- **O `kind`**: `remarcacao__` mais os vinte primeiros do hex do id, fechando os trinta e dois. Mesmo raciocínio de `kind_da_confirmacao`.
- **As guardas**: `horario_permite_envio` no topo (RN-13.3, terceiro sítio a aplicá-la) e a janela de 24h da Meta com template aprovado fora dela, só no WhatsApp. `outbound` do `ctx`, então opt-out e atendimento humano vêm de `GuardedOutbound`.

O texto é um só (não há três formas — o convite não descreve o compromisso, convida a marcar outro) e **não promete que alguém remarca**: nada lê a resposta, como na TEC-171.

## D7 — "Entra na cadência de reengajamento" já é verdade, e a regra empurra contra si mesma

A cadência é **derivada** (TEC-183, Emenda E-01 da RN-13.4): `candidatos_a_followup` seleciona por temperatura viva e pela âncora — a última fala do lead — e nada é "posto" nela. Um lead com no-show **já está** na cadência assim que calar o intervalo mínimo, sem que esta card escreva uma linha. O terceiro cenário do Gherkin é exercitável assim, e é como será exercitado.

**E aqui há uma tensão que a card não resolve, e que é decisão de produto.** As duas regras da RN-12.4 puxam em direções opostas:

- `-15` de score esfria o lead;
- esfriar reduz o número de tentativas, porque a régua é por temperatura — QUENTE tem 4, MORNO 3, FRIO 2 (RN-13.1).

Ou seja: **punir o no-show com score faz o sistema insistir menos com quem faltou**, que é o oposto do que "entra na cadência de reengajamento" sugere. As duas regras são do SRS e esta card cumpre as duas como escritas; corrigir a tensão é mexer na RN-12.4 ou na RN-13.1, e não cabe aqui.

## D8 — O aviso ao corretor no cancelamento

E-mail pelo `EmailSmtp`, ao `corretor.email`, no molde de `_avisar_corretor` da TEC-170 — **e sem abrir handoff**, pela mesma razão que aquela card registrou: o aviso do handoff leva resumo, etiqueta, prioridade e link, e não os dados do compromisso.

**`Gatilho` não ganha valor novo.** A docstring dele diz que nasceu completo e que acrescentar custa migration (o `CHECK` de `handoffs.status` é irmão do problema) — e este aviso não é handoff nenhum. A etiqueta e a prioridade do `Aviso` saem de literais próprios (`agendamento-cancelado`, `NORMAL`) em vez de `ETIQUETA_DE[AGENDAMENTO_CONFIRMADO]`: reusar aquele mandaria um e-mail de cancelamento etiquetado "agendamento-confirmado", que é a citação que não bate com o produto.

Idempotência: `agendamentos.corretor_avisado_do_cancelamento_em`, coluna própria. Reusar `corretor_avisado_em` (da TEC-170) faria um cancelamento ser suprimido porque a confirmação já tinha sido avisada.

Sem retentativa automática: falha de canal vira `agendamento.aviso_de_cancelamento_falhou` em `error` e coluna nula, o mesmo contrato da TEC-170.

## D9 — Migration 0050

Uma só, porque as colunas nascem juntas e a metade delas sem a outra não descreve estado nenhum:

| tabela | coluna | tipo |
| --- | --- | --- |
| `agendamentos` | `origem_id` | `uuid NULL`, FK para `agendamentos.id` |
| `agendamentos` | `cancelado_em`, `realizado_em`, `nao_compareceu_em` | `timestamptz NULL` |
| `agendamentos` | `remarcacao_convidada_em` | `timestamptz NULL` |
| `agendamentos` | `corretor_avisado_do_cancelamento_em` | `timestamptz NULL` |
| `lead_qualification` | `penalidade_pontos` | `int NOT NULL DEFAULT 0` |
| `lead_score_audit` | `penalidade` | `int NOT NULL DEFAULT 0` |

Mais o `CHECK` de `agendamentos.status`, que é `DROP` e `ADD` (Postgres não altera `CHECK` no lugar).

`DEFAULT 0` nas duas colunas de penalidade porque a linha antiga significa "nunca foi penalizado", que é zero — aqui o default não inventa fato nenhum, ao contrário das colunas nuláveis da 0047 e da 0049, em que nulo é o registro de que o passo não aconteceu.

## Testes

**Unitários** (sem banco):

- `Score` com penalidade: o total subtrai, o piso é zero, o sexto fator aparece em `causas_do_recalculo` como `CAUSA_PENALIDADE`.
- A máquina de estados: cada transição legal e cada ilegal, lidas da mesma tabela que o código usa.
- Os textos: o e-mail de cancelamento ao corretor (data, hora, imóvel, lead, link) e o convite de remarcação ao lead — este registrado em `tests/unit/literais_ao_lead.py`.
- A faixa do convite: devido no piso, devido no meio, **não** devido no teto de 7 dias.
- O `kind` do convite: 32 caracteres, um por agendamento.

**Integração** (Postgres):

- **CA-12.2**: agendamento `CONFIRMADO` → `cancelar` → o slot aceita nova reserva no mesmo horário e para o mesmo corretor (prova a D2 contra a constraint real, não contra o modelo), e o corretor recebe o e-mail.
- `remarcar` → original `REAGENDADO`, novo com `origem_id` apontando para ele, os dois no mesmo commit.
- **Cenário 2 do Gherkin**: lead com score 68 → `marcar_nao_comparecimento` → score 53, linha em `lead_score_audit` com `NAO_COMPARECIMENTO` **e** `PENALIDADE`, e `penalidade = 15` na linha.
- O recálculo seguinte do mesmo lead **continua** 53 — é o que a D5 existe para garantir, e o que a opção descartada não daria.
- Dois no-shows acumulam 30.
- Piso: lead com score 8 e no-show → 0, e não `-7`.
- **Cenário 3 do Gherkin**: lead com `NO_SHOW` aparece em `candidatos_a_followup` depois de calar o intervalo mínimo.
- Transições ilegais recusam sem gravar (`RESERVADO` → `REALIZADO`, `CANCELADO` → `NO_SHOW`).
- A varredura do convite: sai uma vez às 24h, não sai na segunda passagem, não sai depois de 7 dias, não sai fora do horário de contato, vira template fora da janela de 24h, e nada sai sem template aprovado.

## Emendas ao SRS

- **RN-12.3** — o slot é liberado pela própria constraint de exclusão, no `UPDATE` do status, e não por job; a tentativa de remarcação é uma varredura que manda um convite ao lead, com faixa de 24 h a 7 dias, e **nada lê a resposta**.
- **RN-12.4** — os 15 pontos são uma **penalidade acumulada e persistida**, sexto fator do score, porque o score é derivado e um desconto só na trilha evaporaria. "Entrar na cadência" é verdade por construção, e as duas regras da RN-12.4 empurram em direções opostas (D7).
- **RN-12.5** — `PROPOSTO` não existe (é `RESERVADO`) e `EXPIRADO` existe sem estar na lista.
- **CA-12.2** — exercitada contra a constraint real.
