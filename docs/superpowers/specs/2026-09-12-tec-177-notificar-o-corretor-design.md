# TEC-177 — Notificar o corretor em até 60 segundos

**Status:** desenhado em 2026-09-12.

**Card:** [TEC-177](https://eduardodurieuxlopes.atlassian.net/browse/TEC-177) — História, Must (MoSCoW), prioridade Highest. Origem: RF-16, RN-16.2 (SRS v1.0); RN-06.5, RN-B03. Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Paulo, corretor, quero ser avisado no canal que já uso quando um lead está pronto, para não perder o timing enquanto o dashboard fica fechado."*

**Branch empilhada.** Esta card precisa de `handoffs.resumo` (TEC-175, PR #90) e da tabela `corretores` (TEC-196, PR #91), e nenhuma das duas está na `main`. A branch sai da TEC-175 com a TEC-196 mesclada dentro, e é nesse merge que a colisão de migration das duas se resolve: `0024_corretores` vira `0025_corretores`, seguindo a ordem dos PRs. **O PR desta card só pode entrar depois dos dois.**

## O que esta card entrega, dito sem rodeio

**Nenhum corretor recebe nada ao fim dela.** Os dois canais que a RN-16.2 exige nascem como porta com adaptador que registra e não envia:

- **E-mail** — não há nenhuma infraestrutura de e-mail neste projeto: nenhuma dependência no `pyproject.toml`, nenhum SMTP, nenhum provedor. Escolher um é decisão que foi tomada em 12/09/2026 como *"só a porta, sem adaptador real"*.
- **WhatsApp** — a Cloud API da Meta recusa mensagem livre passadas 24h da última fala do destinatário, e `outbound/whatsapp.py` já trata esse código (`131047`). **O corretor está sempre fora dessa janela**, porque ele não conversa com o número da empresa. Entregar exige um **template aprovado pela Meta**, que é cadastro externo com prazo próprio e que nenhum PR produz.

O que ela entrega, e que é o trabalho de verdade: o destinatário resolvido, o encadeamento dentro do orçamento de 60 segundos, o conteúdo da mensagem, o isolamento de falha entre canais, a marcação de "pendente de aviso manual" e o aviso ao lead sobre a janela de atendimento humano.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `handoffs.resumo` | existe (TEC-175), **pode ser nulo** | D2 |
| `corretores` com `plantao` e `ativo` | existe (TEC-196) | D3 |
| `handoffs.corretor_id` | tem FK, e é **sempre nulo** | D3 — alocar é a TEC-166 |
| `horario_permite_envio` (`outbound/horario.py`) | existe, puro, parametrizado por hora | D5 |
| `OutboundPort` | existe, com guarda de opt-out por `message_id` | D5 |
| infraestrutura de e-mail | **não existe** | D4 |
| template de WhatsApp aprovado | **não existe** | D4 |
| sistema de alerta | **não existe** | D7 |

## Decisões

### D1 — A notificação é enfileirada pelo job do resumo, depois de ele gravar

O resumo é a carga da notificação — a RN-16.2 diz *"com resumo e link"* —, então a notificação não pode sair antes de ele existir. O job do resumo já roda fora da transação do turno (D1 da TEC-175) e conhece o `handoff_id`; ao terminar, ele enfileira `notificar_corretor`.

**O orçamento fecha com folga de ordem de grandeza.** A RN-16.2 dá 60 segundos; o resumo tem 8 no p95 (RNF-05) e a notificação é uma chamada por canal. Encadear não é o caminho mais curto possível, mas é o único que garante a ordem que a regra exige.

A alternativa — notificar em paralelo com a geração e mandar o resumo depois — foi descartada: produziria duas mensagens por handoff, e a segunda chegaria a um corretor que já abriu a primeira.

### D2 — Handoff sem resumo notifica assim mesmo

A geração pode falhar, e o resumo de contingência é a TEC-176, que não existe. A D7 da TEC-175 deixa o handoff com `resumo` nulo nesse caso, de propósito.

**A notificação sai mesmo assim**, com o link e uma linha dizendo que o resumo não pôde ser gerado. O argumento é o da própria card: *"o handoff que ninguém vê não existe"*, e a prioridade Must dela se justifica por ser a mitigação declarada do risco RN-B03 — o corretor que não adota a ferramenta. Um corretor que recebe um aviso magro ainda atende o lead; um corretor que não recebe nada, não.

### D3 — O destinatário é o corretor alocado quando houver, e o plantão quando não houver

A RN-16.2 diz *"o corretor **designado**"*. Designar é a TEC-166, e `handoffs.corretor_id` é sempre nulo hoje.

A resolução é em cascata: `corretor_id` do handoff, se houver; senão, o plantão — o corretor com `plantao = true` e `ativo = true`, que é exatamente o *"generalista de plantão, que recebe o que não tem match"* da TEC-196.

**Com mais de um plantão ativo, escolhe-se o mais antigo**, por `criado_em`. A D7 da TEC-196 deixou a multiplicidade aberta de propósito, porque a card de lá não escreveu a regra; esta card precisa de **uma** resposta determinística para poder mandar a mensagem, e a mais antiga é a que não muda quando alguém cadastra um plantão novo. **Declarado: qual plantão deve receber é decisão da TEC-166**, e quando ela chegar esta escolha sai daqui.

**Vira emenda à RN-16.2.**

### D4 — Dois canais, uma forma de porta, e nenhum adaptador que entrega

`CanalDeNotificacaoPort` com um `nome` e um `enviar`. Duas implementações, as duas registrando sem entregar, pelas razões do topo deste documento.

Uma forma só para os dois, e não duas interfaces, porque a regra os trata igual: *"falha em um dos canais não cancela o outro"* só é escrevível uma vez se os dois tiverem a mesma assinatura. E porta, e não função solta, porque é ela que deixa o adaptador real entrar depois sem o domínio saber — o mesmo argumento que o SRS faz para a `CrmPort` na RN-16.5.

**Vira emenda à RN-16.2.** A regra promete entrega por dois canais, e esta card entrega a fiação dos dois e a entrega de nenhum.

### D5 — Fora da jornada do corretor, o lead é avisado da janela, e a guarda de opt-out vem junto

A regra diz: *"fora do horário de atendimento humano, a notificação é enviada assim mesmo e o lead é avisado da janela — o corretor decide se responde."* São duas coisas: o corretor recebe sempre, e o **lead** ganha um aviso.

O "fora do horário" usa `horario_permite_envio` com a jornada do corretor destinatário, que a TEC-196 acabou de criar. Reusar aquela função, e não escrever a segunda, é o que a docstring dela pede em letras maiúsculas — ela existe em `outbound/` e não em `followup/` justamente para a próxima card não escrever uma cópia.

O aviso ao lead sai pelo `OutboundPort`, chaveado na **última mensagem da conversa** com um `kind` próprio. Isso não é detalhe de implementação: a `UNIQUE (message_id, kind)` daquela porta dá a deduplicação — um aviso por mensagem, não um por handoff reaberto —, e **a guarda de opt-out vem junto**. Um lead que pediu para não ser contatado não recebe o aviso, e não foi preciso escrever nada para isso.

### D6 — Duas colunas novas, e nenhuma tabela nova

`handoffs.notificado_em` — quando ao menos um canal aceitou. `handoffs.aviso_manual_pendente` — verdadeiro quando nenhum aceitou, que é o *"o handoff fica marcado como pendente de aviso manual"* do terceiro cenário.

Não há tabela de notificações porque nada nesta card lê histórico de tentativa: o que o dashboard (E8) e o SLA (TEC-178) vão querer é o estado corrente, e é isso que as duas colunas dizem. Uma tabela append-only sem leitor seria o peso morto que a D1 da TEC-174 recusou.

**Sem plantão ativo e sem corretor alocado, o handoff nasce `aviso_manual_pendente`.** Não há para quem mandar, e registrar sucesso seria mentir.

### D7 — O "alerta" da card é log estruturado

*"Falha nos dois canais vira alerta e tarefa manual."* A tarefa manual é a coluna da D6. O alerta não tem onde morar: não existe sistema de alerta neste projeto, e a RNF-34 define log estruturado em JSON como o que existe. Fica um evento de log em nível `error`, com o `handoff_id` e o motivo de cada canal.

Declarado, e é dívida real: log de erro só vira alerta quando alguém o observa.

## Emendas ao SRS

- **RN-16.2** — o destinatário é o corretor alocado quando houver e o **plantão** quando não houver; com mais de um plantão ativo, o mais antigo. Designar é a TEC-166 (D3).
- **RN-16.2** — os dois canais nascem como **porta sem adaptador que entrega**: não há infraestrutura de e-mail no projeto, e o WhatsApp ao corretor exige template aprovado pela Meta, que é cadastro externo. **Nada chega a corretor nenhum até que os dois existam** (D4).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Lead quente notifica em menos de um minuto | exercitado **com dublês** — ver L1 |
| Falha de um canal não cancela o outro | exercitado com dublês |
| Falha nos dois canais vira alerta | exercitado com dublês; o "alerta" é log (D7) |
| Notificação fora do horário comercial | exercitado, inclusive o aviso ao lead |

## Lacunas declaradas

### L1 — Os três primeiros cenários são exercitados com dublês, e nenhum mede o minuto

Nenhum canal real existe, então o que os testes provam é a lógica: que o destinatário é resolvido, que a mensagem carrega resumo e link, que a falha de um canal não cancela o outro, e que a falha dos dois marca o handoff. **A entrega em si não é exercitada, porque não existe.**

E o "em até 60 segundos" não é medido, pela mesma razão que o p95 da TEC-175 não foi: o `addopts` exclui `-m perf` de propósito. O que existe é a latência no log estruturado.

### L2 — A jornada do corretor não tem dia da semana, então domingo parece horário útil

A emenda E-02 do modelo Corretor (TEC-196) trocou o `jsonb` por dia da semana por uma janela única de horas. A consequência aparece **aqui**: a checagem da D5 compara só a hora, então um handoff criado às 10h de domingo é tratado como dentro da jornada, e o lead não recebe o aviso da janela.

O PR-06 do SRS diz que o corretor atende *"de segunda a sábado, 9h–19h"*. Corrigir exige a agenda por dia, que é migration e é da TEC-170.

### L3 — Um handoff pode ser notificado duas vezes se o resumo for regenerado

A rota de regeneração da TEC-175 chama `gerar_resumo` em processo, e não pela fila — então ela **não** dispara notificação hoje. Mas o dia em que alguém enfileirar o job de resumo de novo para o mesmo handoff, a notificação sai outra vez. Não há coluna de "já notifiquei" guardando isso além de `notificado_em`, e nada a consulta antes de enviar.

Fica assim de propósito: bloquear a renotificação impediria o caso legítimo — um handoff que ficou horas sem aceite e precisa ser lembrado, que é justamente o que a TEC-178 vai construir. Quem decidir a regra de relembrar decide também a de não duplicar.

### L4 — O `corretor_id` do handoff continua nunca sendo escrito

A D3 lê `handoffs.corretor_id` primeiro, e ele é sempre nulo — a FK existe desde a TEC-196, mas escrever ali é a TEC-166. Na prática, **todo handoff hoje vai para o plantão**, e o ramo do corretor alocado é código sem exercício em produção. Está testado, porque um teste pode gravar o `corretor_id` à mão.

## Fora de escopo

SLA de aceite e escalada ao gerente (TEC-178, exclusão da própria card). Alocação do corretor (TEC-166). Resumo de contingência (TEC-176). Silenciamento do agente ao assumir (TEC-179). O adaptador real de e-mail e o template de WhatsApp — os dois dependem de decisão e cadastro fora deste repositório.
