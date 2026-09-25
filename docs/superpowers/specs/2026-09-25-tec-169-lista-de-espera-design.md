# TEC-169 — Oferecer lista de espera sem disponibilidade em 72 horas

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-169](https://eduardodurieuxlopes.atlassian.net/browse/TEC-169) — épico TEC-164
**Branch:** `feat/tec-169-lista-de-espera`
**Origem:** RF-11, RN-11.5 (SRS v1.0). Depende de TEC-165, TEC-174 e TEC-371 — todas mergeadas. Sai de cima da TEC-377, que desfaz a colisão de revisão do Alembic.

## Objetivo

A RN-11.5 é a única regra da RF-11 que continua sem código, e a Emenda E-01 dela (TEC-371) diz o que acontece hoje: *"um lead que pede visita numa semana lotada recebe uma resposta genérica e nada registra que ele pediu."*

Esta card fecha isso. O lead passa a receber uma oferta em vez de silêncio, e o pedido dele passa a existir numa fila que alguém pode ler.

## O que esta card não entrega, dito antes

- **A entrega do aviso de slot liberado.** O texto e a varredura existem, mas o envio fora da janela de 24 horas da Meta exige template aprovado, e `WHATSAPP_TEMPLATES_APROVADOS` é vazio por padrão — é a TEC-373. **Consequência prática: o terceiro cenário do Gherkin funciona e não chega ao lead** enquanto aquela card não sair. É a mesma lacuna que a TEC-171 e a TEC-172 já declararam, e o aviso registra em `outbound_dispatches` do mesmo jeito.
- **A interface do corretor para ver a fila.** A lista de espera vira handoff, e o handoff já aparece na fila do dashboard (TEC-192) pela etiqueta. Uma tela que mostre a fila *como fila* — com ordem e tempo de espera — é a E8.
- **Priorização por score ou temperatura.** A card põe fora explicitamente: a ordem é de chegada.
- **Reunião remota.** `TIPO` na conversa é `VISITA_PRESENCIAL` e continua sendo, pela razão que a Emenda E-01 da RN-11.1 registra — o detector não tem vocabulário para reunião.

## D1 — A condição já existe, e tem um ponto só

Não há consulta nova a escrever. `agendamento/conversa.py::_oferecer` já calcula exatamente a pergunta da RN-11.5, e a própria docstring dela aponta para esta card:

```python
janelas = da_data or await janelas_alocadas(..., ate=agora + HORIZONTE, tipo=TIPO)
if not janelas:
    await apagar_propostas(...)
    return NadaAFazer()          # <- aqui
```

`HORIZONTE` é `timedelta(hours=72)` e já está no módulo. `propor_janelas` até documenta a divisão de trabalho: *"`ate` vem de quem chama: a TEC-169 usa 72h para decidir a lista de espera (RN-11.5), e este modulo nao escolhe por ela."*

Então `NadaAFazer()` vira a oferta. **Um ponto, e não uma checagem espalhada** — é o que garante que os seis chamadores de `_oferecer` herdem o comportamento sem cada um lembrar dele.

## D2 — Quem está remarcando não entra na fila

`_oferecer` recebe `remarcando_id`, e **quando ele não é nulo a lista de espera não é oferecida**: o turno cai fora como hoje.

A razão é o que a D4 da TEC-372 construiu: na remarcação o agendamento original só vira `REAGENDADO` quando o lead escolhe uma janela nova, então sem janela **ele continua `CONFIRMADO` e a visita antiga fica de pé**. Pôr esse lead numa fila de espera afirmaria que ele está sem horário, quando ele tem um. O que ele perde é a remarcação, não a visita — e é a mensagem de quem não tem nada marcado que seria falsa aqui.

## D3 — A tabela, e o que ordena a fila

`lista_de_espera`, migration `0054`, no molde de marcas nulas que a TEC-170, a TEC-171 e a TEC-372 estabeleceram — **nula é "não aconteceu", nunca um fato negativo**.

| coluna | por quê |
| --- | --- |
| `channel`, `conversation_key` | o par que identifica o lead, o mesmo de `lead_qualification` |
| `imovel_id` | nulável; o interesse quando há um, por `_imovel_de_interesse` |
| `oferecida_em` | quando o agente ofereceu. Não ordena nada — ver abaixo |
| `aceita_em` | **é o que ordena a fila** |
| `recusada_em` | o lead preferiu data mais distante (D6) |
| `avisada_em` | o aviso de slot liberado saiu (D7) |
| `handoff_id` | FK nulável para `handoffs.id`; preenchida no aceite |

**A fila ordena por `aceita_em`, e não por `oferecida_em`.** A card diz "ele entra na lista com o momento de entrada registrado", e entrar é aceitar: um lead que recebeu a oferta e não respondeu não está na fila. Ordenar pela oferta poria na frente quem nunca disse sim.

**Uma linha viva por conversa**, por índice parcial `uq_lista_de_espera_conversa_viva` sobre `(channel, conversation_key)` com `recusada_em IS NULL AND avisada_em IS NULL` — o mesmo padrão de `uq_handoffs_conversa_pendente`. Sem ele, um lead que pede visita três vezes numa semana lotada ocupa três posições da mesma fila.

## D4 — O gatilho é novo, e ele NÃO custa migration

`Gatilho.SEM_DISPONIBILIDADE`, etiqueta `sem-disponibilidade`, prioridade `NORMAL`.

**O docstring de `handoff/vocabulario.py::Gatilho` diz que acrescentar valor ao enum "custa migration", e isso é falso** — e o comentário é o que esta card conserta junto. A verificação: em `0023_handoffs.py` há `CheckConstraint` para `prioridade` e para `status`, **nenhum para `gatilho`**, que é `String(32)` cru. O receio do comentário é verdadeiro sobre `status`, e ele próprio nomeia esse parentesco ("o `IN` do CHECK em `handoffs.status` e irmao deste problema") — mas generaliza para o enum inteiro, e quem lê conclui que um gatilho novo é caro quando não é.

**Por que não reusar um gatilho existente.** `PEDIDO_DE_HUMANO` é o único `ALTA` da RN-16.1 e significa que o lead pediu uma pessoa — ele não pediu. `LEAD_QUENTE` é sobre score. A etiqueta é o filtro do corretor no dashboard (TEC-192) e não muda depois de criada: enfiar esta fila dentro de outra etiqueta tornaria o filtro dela mentiroso para sempre.

`registrar_handoff` é reusada como está — ela não commita, acumula gatilho em handoff já aberto e grava `HANDOFF_CRIADO` na trilha. O aceite da lista e o handoff entram na mesma transação, pela mesma razão que o gatilho quente: lead na fila sem handoff é o estado que a card existe para impedir.

## D5 — O texto pode dizer que existe fila, e não pode dizer que alguém liga

`tests/unit/test_promessa_ao_lead.py` é explícito sobre a fronteira, na docstring do próprio teste: *"O texto PODE dizer que a conversa foi para a fila de um corretor: isso e verdade, o handoff e criado. O que ele nao pode e afirmar que alguem viu o aviso ou que vai procurar o lead."*

A oferta e o aceite ficam assim — acentuados, porque é texto que o lead recebe (TEC-267):

```
TEXTO_DA_LISTA_DE_ESPERA = (
    "Não tenho horário livre nos próximos três dias. Posso te colocar na fila "
    "de um corretor para propor um horário, ou te mostrar datas mais para frente. "
    "O que prefere?"
)
TEXTO_DA_ESPERA_ACEITA = "Pronto, você está na fila desde agora. Se abrir um horário antes, eu te mostro aqui."
```

Nenhuma das duas casa com as dez formas de `PROMESSAS_BANIDAS`, e a segunda foi escrita para não precisar: "eu te mostro aqui" é sobre **esta conversa**, que é o que a D7 de fato faz, e não sobre uma pessoa que ligaria.

**A oferta nomeia as duas saídas na mesma frase**, e isso é o quarto cenário do Gherkin virando texto em vez de virar detector adivinhador: o lead que não quer a fila não precisa descobrir sozinho que pode pedir outra data.

## D6 — Recusar a lista abre o horizonte para 14 dias

Quarto cenário: *"prefere ver horários da semana seguinte"* → janelas além das 72 horas.

`HORIZONTE_ESTENDIDO = timedelta(days=14)`, usado só quando há oferta de espera pendente e o lead recusa. Catorze dias, e não um número medido: é o intervalo em que a agenda do corretor ainda é informação — mais longe que isso, a grade muda antes da visita. Mesmo argumento e mesma honestidade do `VALIDADE_DO_CONVITE` de `agendamento/remarcacao.py`, que declara "sete dias, e nao um numero medido". Quem medir corrige.

**Não muda `HORIZONTE`.** Os 72 horas continuam sendo o que decide a lista de espera, que é a regra do SRS; o horizonte estendido é a resposta a um pedido explícito do lead, e só existe depois dele.

`_janelas_da_data_falada` continua na frente quando o lead nomeia um dia — "semana que vem" resolve para `Semana`, que ela devolve como `None` de propósito, e aí a grade estendida é a resposta certa.

## D7 — Slot liberado avisa UM, e não a fila inteira

Terceiro cenário. `workers/jobs/sweep_lista_de_espera.py`, molde exato da `sweep_remarcacoes` (TEC-172), que por sua vez segue a `sweep_lembretes`: a regra de quando é pura, em `domain/agendamento/espera.py`, e o job só estreita as linhas.

**A varredura acha cancelamento recente que liberou horário dentro de 72 horas** — `status` em (`CANCELADO`, `EXPIRADO`) com `inicio` entre agora e `agora + HORIZONTE` — e avisa **o primeiro da fila por `aceita_em` que ainda tem `avisada_em` nula**.

Três decisões dentro disto:

- **Um por slot, e não a fila toda.** "Quem está na lista é avisado, na ordem de entrada" se lê das duas formas. Avisar todos sobre uma vaga produz uma corrida e N−1 decepções, e o lock otimista da RN-11.4 só protege depois da escolha — ele não impede a promessa.
- **O aviso não reserva o slot e não o nomeia.** Ele diz que abriu horário e convida a pedir; quem responder cai em `_oferecer`, que recalcula a grade de agora. Prometer *aquele* horário criaria uma reserva que ninguém segura, e a fila não é por slot — é por "quero visitar".
- **`avisada_em` tira o lead da fila, tenha ele respondido ou não.** É o que impede o primeiro da fila de travá-la: o slot seguinte vai para o próximo. Um lead avisado que não respondeu e ainda quer visita pede de novo, e aí entra na fila com `aceita_em` de agora — atrás de quem esperou mais, que é o certo.

## D8 — A etapa nova entra depois da reserva e antes das propostas

`conversa.py::atender` é uma cascata, e a ordem é decisão em cada degrau. A etapa nova — *há oferta de espera pendente?* — entra **depois** de `_reserva_pendente` e **antes** de `ler_propostas`.

Depois da reserva, porque um lead com reserva viva está respondendo àquele horário concreto. Antes das propostas porque as duas são mutuamente exclusivas por construção: só se oferece espera quando não houve janela, e sem janela não há proposta gravada — pôr a etapa depois seria ordenar duas coisas que nunca coexistem, e sugerir ao próximo leitor que coexistem.

O detector reusa `deteccao.py::confirmou` e `deteccao.py::recusou`, e **aqui isso é seguro**, ao contrário do que a D2 da TEC-372 decidiu para o lembrete. A assimetria é o oposto: lá "não" ambíguo escolhia entre cancelar uma visita marcada e remarcá-la, sem tela para desfazer. Aqui os dois desfechos são baratos e reversíveis — entrar numa fila, ou ver mais horários —, e o lead que caiu no lado errado corrige na fala seguinte.

## Critérios de aceite, e onde cada um é exercitado

| cenário do Gherkin | onde |
| --- | --- |
| Oferecer lista quando não há vaga em 72 horas | `tests/features/test_lista_de_espera.py` |
| Aceitar a lista cria handoff | idem, conferindo `handoffs.gatilho` e a trilha |
| Slot liberado avisa a fila em ordem | `tests/integration/test_sweep_lista_de_espera.py`, dois leads |
| Lead pode preferir data mais distante | `tests/features/test_lista_de_espera.py`, e sem linha na fila |

## Emendas ao SRS

- **RN-11.5, Emenda E-02** — a regra passa a ter código; a fila ordena por aceite e não por oferta; quem remarca não entra; o aviso de slot liberado é para um lead por slot e não promete o horário; e a entrega do aviso continua presa ao template da Meta (TEC-373).
- **RN-16.1** — `SEM_DISPONIBILIDADE` entra como gatilho de handoff, com etiqueta própria e prioridade `NORMAL`.
