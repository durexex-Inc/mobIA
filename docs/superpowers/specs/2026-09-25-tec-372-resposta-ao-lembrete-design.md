# TEC-372 — Ler a resposta do lead ao lembrete: confirmar, remarcar ou cancelar

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-372](https://eduardodurieuxlopes.atlassian.net/browse/TEC-372) — épico TEC-164
**Branch:** `feat/tec-372-resposta-ao-lembrete`
**Origem:** RF-12, RN-12.2, RN-12.3, CA-12.2 (SRS v1.0). Depende de TEC-171, TEC-172 e TEC-371 — todas mergeadas.

## Objetivo

O lembrete de 24 horas pergunta "sim / remarcar / cancelar" e nada lê a resposta. Esta card põe um leitor ali, e é isso que torna a pergunta honesta — hoje ela é pior que não perguntar.

## O que esta card não entrega, dito antes

- **`REALIZADO` e `NO_SHOW`.** São ação do corretor, e a interface dele é a E8. A card os põe fora.
- **Cancelar e remarcar fora da janela do lembrete.** O leitor desta card vale **enquanto o lembrete está de pé** (ver a D1). Um lead que escreve "quero desmarcar" três dias antes da visita continua caindo no turno normal — o que muda é que, a partir do lembrete, ele é ouvido.
- **Lista de espera sem disponibilidade em 72 horas (TEC-169).** A remarcação reusa o caminho de oferta da TEC-371 e herda a lacuna dela: sem janela, o turno cai fora e não promete nada. **O lead não fica sem nada**, e é a D4 que garante isso — o original só vira `REAGENDADO` na escolha, então sem escolha ele continua `CONFIRMADO` e a visita antiga fica de pé. O que se perde é a resposta: ele pediu para remarcar e recebeu texto genérico.

## D1 — "Lembrete pendente" é um predicado sobre o banco, e não um estado novo

A card exige que a resposta seja lida **no contexto do lembrete**: fora dele, "cancelar" é palavra comum e não pode derrubar agendamento nenhum (o quarto cenário do Gherkin). Não é preciso inventar estado para isso — o que define o contexto já está gravado:

```
status = CONFIRMADO  e  lembrete_24h_em IS NOT NULL  e  inicio > agora
```

As três juntas: existe um agendamento vivo, o lembrete que oferece as três opções **já saiu** (é `sweep_lembretes` quem carimba a coluna), e a visita ainda não começou.

**A janela vai do lembrete de 24 h até o início da visita, e não até o de 2 h.** Cancelar noventa minutos antes é legítimo e é justamente quando mais importa que alguém ouça; fechar a janela no marco de 2 horas devolveria silêncio ao lead na hora de maior custo. O lembrete de 2 h não oferece opção nenhuma ("Sua visita é daqui a pouco"), então ele não abre uma segunda janela — ele acontece dentro da mesma.

`inicio > agora` é o fecho, e é o que impede a resposta de mexer em visita que já começou.

## D2 — Um detector novo, e a assimetria é a terceira do repo

`agendamento/deteccao.py` ganha `respondeu_ao_lembrete(texto) -> Resposta`, com três valores (`CONFIRMA`, `REMARCAR`, `CANCELAR`) e `None` para o resto. **Não reusa `confirmou`/`recusou` da TEC-371**, e a razão é que as perguntas são diferentes: lá `recusou` significa "este horário não serve, me dê outro"; aqui "não" sozinho é ambíguo entre *não vou* (cancelar) e *não nesse horário* (remarcar), e as duas leituras têm desfechos opostos.

A assimetria de erro é a mais dura das três que o repo tem:

- **Falso positivo de CANCELAR:** derruba uma visita marcada, libera o slot e manda e-mail ao corretor. O lead aparece no dia e não há ninguém. **Não há tela para desfazer** — a E8 não existe.
- **Falso negativo:** o lead não é ouvido, que é exatamente o estado de hoje. Ruim, e recuperável: ele repete, ou o corretor descobre no lembrete de 2 horas.

Por isso, e ao contrário da TEC-371, **aqui a faixa é estrita e o silêncio é o default**. `CANCELAR` exige forma inequívoca (`cancelar`, `desmarcar`, `não vou poder ir`, `não vou conseguir ir`); `"nao"` sozinho **não** é cancelamento — é `None`, e o turno normal responde. É o inverso da escolha que a TEC-371 fez para `recusou`, e a diferença é que lá o custo do erro era oferecer horário de novo.

**Resposta ambígua pergunta em vez de adivinhar** (regra da card). Quando o texto casa cancelar **e** remarcar ("não vou poder, remarca?"), o desfecho é `REMARCAR` — não por desempate arbitrário, mas porque remarcar é o caminho reversível: ele oferece janelas e o lead ainda pode não escolher nenhuma. Cancelar não volta.

## D3 — A confirmação de presença ganha coluna (migration 0052)

`agendamentos.presenca_confirmada_em`, `timestamptz` nula. É a coluna que a RN-12.2 pede e que a TEC-171 deliberadamente não criou, porque nada a escreveria.

**Nulo é "o lead não respondeu", e não "não vai".** A distinção é a mesma das colunas de aviso da TEC-170: ausência de fato, não fato negativo. Quem contar no-show pelo painel precisa dos dois valores separados — quem confirmou e faltou é outra história que quem nunca respondeu.

**Não muda `status`.** `CONFIRMADO` já é o estado do agendamento; presença confirmada é um fato **sobre o lead**, não sobre o compromisso. Colapsá-los exigiria um status `PRESENCA_CONFIRMADA` que toda consulta teria de lembrar de incluir — a mesma entrada morta de vocabulário que a TEC-172 recusou para `PROPOSTO`.

## D4 — Remarcar reusa a oferta da TEC-371, com uma coluna a mais nas propostas

"Remarcar" **não** remarca nada na hora: ele oferece janelas, pelo mesmo caminho que a TEC-371 construiu (`conversa.py::_oferecer`), e o original só vira `REAGENDADO` quando o lead escolhe. É o terceiro cenário do Gherkin, literal.

O que falta para isso é saber, no turno da escolha, que aquela rodada de propostas é de **remarcação** e não de agendamento novo. Isso vai numa coluna de `janelas_propostas`: **`remarcando_id`**, FK nula para `agendamentos`.

- Nula → a escolha vira `reservar_ou_alternativas`, como na TEC-371.
- Preenchida → a escolha vira `ciclo.py::remarcar(agendamento_id=remarcando_id, janela=...)`.

Uma coluna na tabela que já existe, e não uma tabela nova: as propostas de remarcação são as mesmas propostas, com um destino diferente. Duas tabelas com as mesmas seis colunas divergiriam na primeira mudança de grade.

**A remarcação tem dois turnos e não três, e a diferença é deliberada.** No agendamento novo, a reserva de 5 minutos existe porque a RN-11.4 a exige *durante a confirmação* — o slot precisa ser segurado enquanto o lead confirma. Aqui o lead já tem um compromisso e está movendo-o; `remarcar` é atômico (original e sucessor no mesmo commit) e não há nada a segurar no meio. Pedir uma confirmação extra acrescentaria um turno e uma janela de expiração para proteger o que já está protegido pela transação.

## D5 — `remarcar` levanta, e quem chama tem de decidir

A docstring de `ciclo.py::remarcar` diz por escrito que ela **não** passa por `reservar` e que a sobreposição sobe como `IntegrityError` em vez de virar `Conflito` — "engoli-la faria a remarcação falhar em silêncio com o original já REAGENDADO".

Esta é a card que chega como chamadora, então a decisão é dela: `conversa.py` captura `IntegrityError`, faz rollback do savepoint e **oferece de novo**, com o texto de conflito que a TEC-371 já escreveu. O lead perdeu a corrida pelo horário novo, e o agendamento original continua `CONFIRMADO` — o que é o desfecho certo: melhor manter a visita antiga que perder as duas.

O `begin_nested` é o mesmo mecanismo de `repositorio.py::reservar`, e pelo mesmo motivo que aquela docstring registra: um `rollback` de sessão inteira expira todo objeto carregado e explode com `MissingGreenlet` no acesso seguinte.

## D6 — Cancelar avisa o corretor, e isso exige a terceira porta

`cancelamento.py::avisar_cancelamento` existe desde a TEC-172 e **nada a chama** — é o terceiro órfão do épico. Ela abre a própria sessão, só age sobre `CANCELADO` e precisa de um `CanalDeNotificacaoPort` (e-mail), que o turno não tem e não deve ter: manter uma chamada SMTP dentro do turno poria a latência do lead na mão do servidor de e-mail.

Então ela vira **job**, no molde exato de `avisar_confirmacao` (TEC-170): `workers/jobs/avisar_cancelamento.py`, enfileirado **depois do commit** de `cancelar`.

**A porta ganha um método em vez de nascer uma terceira.** `AgendadorDeConfirmacaoPort` passa a ser `AgendadorDeAvisosPort`, com `confirmacao(id)` e `cancelamento(id)`. As alternativas foram consideradas e recusadas:

- **Um terceiro parâmetro em `executar_turno`** — a assinatura já cresceu na TEC-371, e um parâmetro por tipo de aviso não tem fim: a próxima card do épico traria o quarto.
- **Manter o nome `AgendadorDeConfirmacaoPort` e acrescentar `cancelamento`** — o nome passaria a mentir sobre o que a porta faz, que é o defeito que este repo trata como bug.

O custo do rename é mecânico e está confinado: a Protocol, as duas implementações, o `startup` do worker e os sítios de teste que constroem o Noop.

## D7 — A ordem dentro do turno, e por que ela vem antes da TEC-371

O bloco de agendamento de `_executar_turno` já existe (TEC-371, D9) e **não ganha um segundo bloco**: o que muda é `conversa.py::atender`, que passa a perguntar primeiro se há lembrete pendente.

A ordem nova, dentro de `atender`:

1. **lembrete pendente + resposta reconhecida** → confirma presença, cancela, ou oferece janelas de remarcação
2. reserva viva → confirmação do agendamento novo (TEC-371)
3. propostas vivas → escolha (agora com dois destinos, D4)
4. `quer_agendar` → oferta

O lembrete vem **primeiro** porque é o contexto mais específico: um lead com visita marcada para amanhã que escreve "cancelar" está falando dela, e não pedindo horário novo. Nas etapas 2 e 3 o estado é de uma conversa de agendamento em curso, que só existe se o lead acabou de pedir.

E o veto que a TEC-371 pôs em `quer_agendar` (`cancelar`, `desmarcar`, `remarcar`, `reagendar`) **fica onde está**: ele protege a etapa 4, que continua sendo sobre marcar visita nova. É a etapa 1 que passa a ler essas palavras, e só dentro da janela do lembrete.

## Testes

**Unitários** (`tests/unit/`):

- `test_deteccao_de_agendamento.py` cresce: as três faixas de `respondeu_ao_lembrete`, o `"nao"` sozinho que **não** cancela, e o texto que casa as duas e resolve como `REMARCAR`.
- Os literais novos entram em `literais_ao_lead.py` e o teste de tamanho sobe.

**Integração** (`tests/integration/`):

- `test_conversa_de_agendamento.py` cresce: os quatro desfechos da etapa 1, e a escolha com `remarcando_id` preenchido chamando `remarcar` em vez de `reservar`.
- Conflito na remarcação: `IntegrityError` vira oferta nova, e o original continua `CONFIRMADO`.
- `test_janelas_propostas.py`: `remarcando_id` sobrevive à ida e volta.

**Features** (`tests/features/test_resposta_ao_lembrete.py`), um por cenário do Gherkin:

1. Confirmação de presença fica registrada — a coluna, não o status.
2. Cancelamento libera o slot **e o corretor é notificado** — a asserção do slot é uma reserva nova no mesmo horário, contra a constraint real; a do corretor é o enfileiramento depois do commit.
3. Remarcação oferece janelas, e o original **só** vira `REAGENDADO` na escolha — duas asserções em dois turnos, e a primeira é sobre o que **não** mudou.
4. "cancela aquele outro assunto" sem lembrete pendente não muda status nenhum.

O cenário 4 é o que protege a assimetria da D2, e merece mais de um caso: sem agendamento, com agendamento mas sem lembrete enviado, e depois do início da visita.

## Emendas ao SRS

- **RN-12.2 — Emenda E-03 (TEC-372):** a resposta ao lembrete passa a ser lida. A Emenda E-01 dizia que nada a lia e a E-02 que os lembretes ganharam linhas; esta fecha a lacuna. A confirmação de presença vira coluna, e nula continua significando "não respondeu".
- **RN-12.3 — Emenda E-02 (TEC-372):** o cancelamento pelo lead passa a ter caminho de conversa, dentro da janela do lembrete. O e-mail ao corretor deixa de ser órfão: vira job enfileirado depois do commit.
- **CA-12.2 — Emenda E-01 (TEC-372):** exercitado ponta a ponta pela conversa. O "menos de 10 s" continua sendo o tempo de um `UPDATE`, como a Emenda E-01 da RN-12.3 já registrava.
