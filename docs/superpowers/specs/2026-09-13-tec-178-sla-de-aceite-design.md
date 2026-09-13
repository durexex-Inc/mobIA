# TEC-178 — Aplicar SLA de aceite e escalar ao gerente

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-178](https://eduardodurieuxlopes.atlassian.net/browse/TEC-178) — História, Should (MoSCoW), prioridade High. Origem: RF-16, RN-16.3 (SRS v1.0). Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Anelise, gerente comercial, quero saber quando um lead quente ficou sem resposta, para agir antes de perder a venda por esquecimento do time."*

**Desbloqueada.** A TEC-177 está em Feito.

## Objetivo

Dar leitor às duas colunas que a TEC-177 criou e a ninguém entregou. Hoje `notificado_em` e `aviso_manual_pendente` são escritos e **nunca lidos**: um handoff que ninguém viu fica parado, e nada o levanta.

Esta card também cumpre uma reserva antiga. O comentário de `handoffs.status`, escrito na TEC-174, diz: *"Nasce e permanece PENDENTE nesta card. ACEITO/ESCALADO vem da TEC-178"*. Os dois valores existem no enum desde então e ninguém os escreve — a L4 daquele desenho declarou exatamente isso.

**O que ela entrega:** as colunas `sla_limite_em` e `aceito_em`, o cálculo do prazo, a rota de aceite que o SRS especifica e nada implementa, a varredura que escala, e a flag que diz quem é o gerente.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `Status.ACEITO` / `Status.ESCALADO` | no enum desde a TEC-174, **sem escritor** | esta card os escreve |
| `POST /api/v1/handoffs/{id}/aceitar` | **especificado na seção 6.5 do SRS, não implementado** | sem ele, três dos cinco cenários não acontecem (D6) |
| gerente comercial | **não existe** — nem tabela, nem papel, nem flag | D7 |
| `lead_qualification.temperatura` | existe (TEC-151) | é a fonte do prazo (D2) |
| `corretores.horario_inicio/fim` | existe (TEC-196) | é a janela do relógio (D3) |
| `notificado_em`, `aviso_manual_pendente` | escritos pela TEC-177, **sem leitor** | esta card é o leitor |
| canais de notificação | **não entregam** (TEC-177, emenda E-02 da RN-16.2) | L2 |

## Decisões

### D1 — O prazo é gravado uma vez e não recalculado

`sla_limite_em` é computado no momento em que o destinatário é resolvido, e não muda depois.

Recalcular faria um lead que esfria ganhar mais prazo — e o SLA existe justamente para pressionar o atendimento do que estava quente **quando chegou**. Um lead que virou `QUENTE` às 9h e esfriou às 9h10 não deve, por isso, ganhar quatro horas.

### D2 — A temperatura vem de `lead_qualification`, e não do gatilho do handoff

O prazo da RN-16.3 é por temperatura: 15 minutos para `QUENTE`, 4 horas para os demais. `handoffs` guarda `gatilho`, `etiqueta` e `prioridade` — **não guarda temperatura**.

Seria tentador derivar do gatilho, porque `LEAD_QUENTE` existe. Mas ele significa *"acabou de atravessar a borda"*, e um handoff criado por `PEDIDO_DE_HUMANO` sobre um lead que já estava quente merece os mesmos 15 minutos. A temperatura do lead mora em `lead_qualification.temperatura`, e é de lá que o prazo sai.

**Temperatura ausente conta como não-quente.** `NULL` ali significa "linha anterior à TEC-151, nunca recalculada" — e dar 15 minutos a um lead cuja temperatura ninguém calculou seria inventar urgência.

### D3 — O relógio usa a jornada do corretor destinatário, e por isso o prazo é calculado na notificação

O primeiro desenho usava a janela da imobiliária (`config.py`), para poder calcular o prazo na criação do handoff. **Decisão do Eduardo em 13/09/2026: respeitar a TEC-196** — a jornada é a do corretor que vai receber, que é o dado que aquela card criou.

A consequência é que o prazo **não pode ser calculado na criação**: a jornada só é conhecida depois que o destinatário é resolvido, e isso acontece no job de notificação. Então `sla_limite_em` é gravado lá, alguns segundos depois — inofensivo diante de um SLA mínimo de quinze minutos.

**Vira emenda à RN-16.3 e ao modelo da seção 5**, porque aquele modelo declara `sla_limite_em` obrigatório e ele passa a ser nulável.

### D4 — Sem destinatário, o handoff escala na hora em vez de ficar sem prazo

Se não há corretor — nenhum alocado e nenhum plantão ativo —, não há jornada, e dar a ele um prazo genérico inventaria um dono que não existe.

**"Ninguém sequer foi avisado" é a versão mais forte do que esta card leva ao gerente.** O handoff nasce `ESCALADO`, ao lado do `aviso_manual_pendente` que a TEC-177 já marca, e `sla_limite_em` fica nulo — não houve prazo porque não houve a quem cobrar.

**Vira emenda à RN-16.3.**

### D5 — A escalada é uma varredura de cinco em cinco minutos

No molde do `sweep_followups`, e pelo argumento que o comentário dele já faz: o menor intervalo em jogo é de quinze minutos, então precisão de segundos não compra nada e custa uma varredura a cada passagem. O erro máximo de disparo fica em cinco minutos sobre uma janela de quinze.

**Não é agendamento por handoff.** Agendar um job para cada handoff no instante do prazo multiplicaria trabalho por lead e exigiria cancelar o agendamento a cada aceite — a varredura não precisa saber de nada que aconteceu antes.

### D6 — "Escalonamento não se repete" é garantia de schema, não disciplina de consulta

A varredura só olha `status = 'PENDENTE'`. Escalar muda o status para `ESCALADO`, e a linha sai do conjunto **sozinha** — nenhuma coluna de "já escalei", nenhum `if` no código.

É o mesmo raciocínio do `UNIQUE` parcial da TEC-174: a regra vira invariante do banco em vez de disciplina de quem consulta.

### D7 — O gerente é uma flag em `corretores`, espelhando o plantão

Decisão do Eduardo em 13/09/2026, entre três alternativas. Não existe gerente neste sistema: nem tabela, nem papel, nem flag.

`corretores.gerente`, boolean, default falso — mesma tabela, mesmo padrão e mesma cascata determinística do `plantao` que a TEC-196 criou: **com mais de um gerente ativo, o mais antigo por `criado_em`**, pela mesma razão de lá (é o que não muda quando alguém cadastra outro).

**Custo declarado:** mistura "papel" numa tabela que a TEC-201 e a TEC-202 vão querer governar depois, quando houver `usuarios` e papéis de verdade. É dívida consciente, e a alternativa — inventar a entidade Gerente agora — seria inventar duas vezes.

**Vira emenda à RN-16.3.**

### D8 — Entra a rota de aceite que o SRS especifica e nada implementa

`POST /api/v1/handoffs/{id}/aceitar` está na seção 6.5 do SRS desde 22/08/2026. Sem ela, três dos cinco cenários do Gherkin — o estouro, o aceite no prazo e a não-repetição — não têm como acontecer, porque nada consegue sair de `PENDENTE`.

Guardada por `exigir_admin`, a única guarda que existe, com a mesma exposição que a emenda E-01 da RN-19.5 já declarou.

**Aceitar é idempotente até o primeiro aceite e recusado depois dele.** Um segundo aceite sobre um handoff já aceito devolve conflito em vez de sobrescrever `aceito_em` — o carimbo existe para alimentar a taxa de aceite no prazo (RN-17.1), e um carimbo que se move para frente faria um aceite atrasado parecer pontual.

## Emendas ao SRS

- **RN-16.3** — o relógio do SLA usa a jornada do **corretor destinatário** (TEC-196), e por isso `sla_limite_em` é gravado na notificação e não na criação (D3).
- **RN-16.3** — handoff sem destinatário **escala imediatamente** e fica sem prazo, porque não há a quem cobrar (D4).
- **RN-16.3** — o gerente comercial é uma flag em `corretores`, espelhando o plantão, até a TEC-201/202 trazerem papéis (D7).
- **Seção 5, modelo Handoff** — `sla_limite_em` passa a ser **nulável** (D3, D4).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Prazo por prioridade do lead (QUENTE/MORNO/FRIO) | exercitado nos três |
| Estouro do SLA escala para o gerente | exercitado — a marcação; a notificação, ver L2 |
| Relógio só conta em horário de atendimento | exercitado **de terça para quarta**; ver L3 |
| Aceite dentro do prazo registra o momento | exercitado |
| Escalonamento não se repete | exercitado |

## Lacunas declaradas

### L1 — O sistema não sabe QUAL corretor aceitou

A rota registra `aceito_em`, mas não há identidade autenticada — quem chama apresenta um token compartilhado, não uma pessoa. `handoffs.corretor_id` continua nulo mesmo depois do aceite.

Consequência prática: a taxa de aceite no prazo da RN-17.1 poderá ser calculada **para a equipe**, nunca por corretor. Fechar isso é a TEC-201, e é mais um argumento para antecipá-la.

### L2 — A escalada notifica por canais que não entregam

O segundo cenário diz *"o gerente comercial é notificado"*. A notificação reusa os canais da TEC-177, e a emenda E-02 da RN-16.2 declara que **nenhum entrega** — falta provedor de e-mail e template aprovado pela Meta.

Então o gerente é resolvido, a mensagem é montada, o handoff é marcado `ESCALADO`, e **ninguém recebe nada**. O que existe de fato é o log e o estado no banco.

### L3 — O relógio não sabe dia da semana

O terceiro cenário — *"handoff criado às 22h de uma terça começa a contar às 9h da quarta"* — é exercitado e passa. Mas **"sábado 22h → segunda 9h" não funciona**: a jornada do corretor é uma janela de horas sem dia, pela emenda E-02 do modelo Corretor (TEC-196), e a contagem só sabe pular para a próxima abertura do relógio.

O PR-06 do SRS diz que o corretor atende *"de segunda a sábado"*. Corrigir exige a agenda por dia, que é a TEC-170.

### L4 — Nada mostra a escalada a ninguém

O handoff fica `ESCALADO` no banco e o evento sai no log. **Não há painel** — é a E8 —, e a notificação não entrega (L2). Na prática, hoje a escalada é visível para quem consultar o banco.

## Fora de escopo

Exibição da taxa de aceite no dashboard (E8, exclusão da própria card). Papéis e identidade autenticada (TEC-201, TEC-202). A agenda por dia da semana (TEC-170). Os adaptadores reais de notificação.
