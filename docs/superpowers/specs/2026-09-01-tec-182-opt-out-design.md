# TEC-182 — Detectar e registrar opt-out imediato

**Status:** implementado em 2026-09-01, na branch `feat/tec-182-opt-out`.

Commits, em ordem: `9c7ad2c` (este desenho), `3c7f6f6` (o plano em seis tasks), `0c05a11` e `2b26c5c` (detecção), `68a67b3` (migração `0010`), `7ce4af8` e `5e1c546` (repositório), `ec9e5cc` e `6804cc8` (guarda na porta de saída), `7d5a9ed` e `1145a11` (turno), `6c5ec0b` (script de reativação). A onda de correção da revisão final da branch vem depois deles, e é a origem de cada marca “corrigido depois da entrega” neste documento.

**Card:** [TEC-182](https://eduardodurieuxlopes.atlassian.net/browse/TEC-182) — Must (MoSCoW). Origem: RF-14, RN-14.1 a RN-14.4 (SRS v1.0, agora em `docs/srs/`); RN-B02, RNF-19.

## Objetivo

O lead precisa poder pedir para não receber mais mensagens e ser atendido na hora. Hoje **não existe nada**: procurar por `opt.out` ou `descadastr` no código inteiro devolve zero. Um lead que escreve "não quero mais receber mensagens" recebe uma resposta de qualificação.

São três problemas ao mesmo tempo. É evidência de LGPD que não existe (RNF-19). É a defesa contra denúncia na Meta, que o Anexo B do SRS lista entre os itens que **nunca** devem ser cortados. E bloqueia a [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183): ligar cadência automática sem chave de desligamento é o caminho mais curto para o bloqueio do número.

**O que esta card entrega:** a detecção, o registro append-only, o silêncio, e um caminho auditável de reativação por ação humana.

## O que já existe, e que o desenho reusa

**A identidade do lead.** `conversation_key` é, no comentário do próprio modelo, *"id externo do lead, invariante à direção"*. O par `(channel, conversation_key)` é a chave que `lead_qualification` já usa. Não é preciso inventar uma entidade `Lead` — o SRS a modela, mas este repo já resolve identidade por esse par, e criar uma tabela `leads` agora seria escopo de outra card.

**O precedente estrutural.** O bloqueio de moderação de entrada em `turno.py` já é a forma de guarda que o opt-out precisa: roda **antes de montar contexto**, economiza o turno pago inteiro, marca a linha e entrega um texto fixo por `_entregar_texto_fixo`.

**A porta de saída.** `GuardedOutbound.send(message_id, kind, payload)` já reserva em `outbound_dispatches` antes do efeito externo, e já recebe `session_factory`. É onde a guarda de opt-out cabe sem inventar estrutura.

## Decisões

### D1 — Silêncio total, e não só parada da automação proativa

Depois do opt-out, o agente **não responde mais nada**, nem quando o lead escreve primeiro.

A RN-14.1 diz que o opt-out "para todo envio automático imediatamente", e a resposta do agente a uma mensagem recebida é envio automático — nada no SRS distingue proativo de reativo. A RN-14.3 fecha: o lead "só volta a ser contatado por ação humana explícita registrada". Responder automaticamente contradiz isso.

As mensagens do lead **continuam sendo gravadas**. O que para é a resposta, não a ingestão — o histórico é evidência, e a RN-14.4 é explícita em que opt-out não apaga histórico.

Custo aceito: um lead que pediu para parar e depois escreve uma dúvida legítima recebe silêncio. É o preço da leitura conservadora, e em LGPD a conservadora é a defensável.

### D2 — Detecção híbrida, por força do termo

O SRS lista `sair`, `parar`, `não quero mais`, `descadastrar`. Aplicar isso como substring em qualquer posição silencia lead legítimo: *"podemos parar por aqui hoje?"*, *"quero sair do aluguel e comprar"*. E o erro é **invisível e permanente** — o lead só vê o silêncio.

A regra tem duas faixas:

- **Termos inequívocos** disparam em qualquer posição da mensagem: `descadastrar`, `descadastre`, `remover meu contato`, `nao quero mais receber mensagens`, `nao quero mais receber mensagem`, `pare de me mandar mensagens`, `pare de me mandar mensagem`, `pare de mandar mensagens`, `pare de mandar mensagem`, `nao me mande mais mensagens`, `nao me mande mais mensagem`, `nao me envie mais mensagens`.
- **Termos ambíguos** disparam **só quando são a mensagem inteira**, normalizada (minúsculas, sem acento, sem pontuação, sem espaço nas bordas): `sair`, `parar`, `pare`, `stop`, `cancelar`, `cancela`, `me tira da lista`, `me tire da lista`, `nao quero mais`. Cobre o padrão real de quem quer sair — a mensagem de uma palavra só — sem pegar a frase em que a palavra é incidental.

**O que fecha a colisão na faixa inequívoca é o objeto de mensageria, e não a raridade da frase.** A versão original deste documento listava os termos **truncados** (`nao quero mais receber`, `pare de me mandar`, `pare de mandar`, `me tira da lista`, `me tire da lista`, `nao me mande mais`) e justificava a faixa dizendo *“nenhum aparece em fala de quem procura imóvel”*. **Isso era falso**, e o erro fica registrado aqui em vez de apagado: *“pare de mandar apartamento sem vaga”*, *“nao quero mais receber apartamento sem vaga”* e *“nao me mande mais casa, so apartamento”* são refinamento de busca corriqueiro, e cada um silenciava um lead comprador para sempre. A revisão da detecção (`2b26c5c`) trocou os termos truncados por termos que **carregam o objeto** — `mensagens`, `mensagem`, `meu contato` —, e `me tira da lista` / `me tire da lista` desceram para a faixa estrita, que exige a mensagem inteira. É o objeto que separa *“pare de me mandar mensagens”* de *“pare de mandar apartamento sem vaga”*; por isso a posição não importa nesta faixa.

**Corrigido depois da entrega:** `nao quero mais receber nada` ficou na faixa inequívoca até a revisão final da branch, e ainda colidia — *“nao quero mais receber nada sem vaga”*, *“nao quero mais receber nada acima de 500 mil”* e *“nao quero mais receber nada nessa regiao”* disparavam opt-out permanente. `nada` é quantificador universal e aceita complemento partitivo: não é objeto de mensageria, e por isso escapou do conserto anterior, que só exigiu o objeto nos termos que já o tinham. O termo saiu da lista e as três frases viraram teste negativo permanente. O custo é de recall, e está nas lacunas.

Determinístico, sem chamada paga, e a lista mora numa constante com o motivo de cada faixa escrito ao lado. A comparação é sobre o texto normalizado, então acento e caixa não abrem buraco: `PARAR!` e `Parar` disparam.

**A assimetria aqui é o inverso da TEC-257, e por isso a decisão não pode ser copiada de lá.** Naquela card, marcar de mais era o erro perigoso e marcar de menos o seguro. Aqui, **deixar de detectar um opt-out é violação de LGPD**; detectar demais é prejuízo comercial. Os dois são ruins, mas só um é ilegal — e é por isso que os termos inequívocos são generosos e só os ambíguos são estritos.

### D3 — A guarda mora na porta de saída, não no turno

A checagem de opt-out entra em `GuardedOutbound.send`, antes da reserva em `outbound_dispatches`.

Se vivesse dentro de `executar_turno`, protegeria o caminho de hoje e nada mais. A TEC-183 vai criar um segundo caminho de envio, e nada garantiria que ela lembrasse da checagem. Na porta, **todo envio que herda `GuardedOutbound` herda a guarda junto**, sem precisar lembrar dela — e a card diz, com todas as letras, que ligar a cadência sem a chave de desligamento é o caminho para o bloqueio do número.

**Corrigido depois da entrega:** este parágrafo dizia *“todo envio presente e futuro herda a guarda e esquecê-la deixa de ser possível”*, e isso é forte demais. `OutboundPort` é um `Protocol` **estrutural**: qualquer classe com um `async def send` de assinatura compatível satisfaz o tipo, herde ou não de `GuardedOutbound`. A guarda existe só dentro do corpo de `GuardedOutbound.send`; nada no `Protocol`, e nada no `mypy`, a força. Um adaptador novo escrito direto contra o `Protocol` tipa igual, passa em toda checagem estática e **manda mensagem para quem pediu para parar**. O aviso mora onde quem escreve esse adaptador vai lê-lo — o docstring de `OutboundPort`, em `src/mobia/domain/outbound/port.py` —, e a rota segura é herdar de `GuardedOutbound`. É invariante para quem herda, não invariante da linguagem.

`send` recebe `message_id`, não o par do lead, então a guarda resolve `(channel, conversation_key)` a partir de `messages`. A `session_factory` já está lá.

**A confirmação do próprio opt-out é o único envio permitido depois do registro**, e passa por um `kind` dedicado que a guarda deixa atravessar. A exceção é explícita e nomeada, não um furo.

Custo aceito: uma consulta a mais por envio. É indexada e cai no mesmo padrão do `ix_messages_timeline`.

**São duas camadas, e cada uma existe por um motivo diferente.** A guarda na porta é a **correção**: ela é o invariante que nenhum caminho de envio pode furar, e é ela que a TEC-183 herda de graça. A checagem no início do turno é a **economia**: sem ela, um lead com opt-out ativo pagaria a classificação inteira para o envio ser barrado no fim. É o mesmo raciocínio que põe a moderação de entrada antes de montar contexto, e está escrito lá — bloquear cedo "economiza o turno pago inteiro".

A duplicação é deliberada e assimétrica: se a checagem do turno for esquecida num caminho futuro, perde-se dinheiro. Se a guarda da porta for esquecida, manda-se mensagem para quem pediu para parar. Só uma das duas é conformidade, e é a que não depende de ninguém lembrar.

### D4 — Registro append-only, e não coluna booleana

Tabela nova `optout_events`, uma linha por evento. O estado atual de um lead é o **último evento** por `(channel, conversation_key)`.

Com booleano, a reativação **apaga** a evidência do opt-out — exatamente o que não pode acontecer num registro de conformidade que a RN-14.2 exige como prova. Com append-only, o histórico é o registro: opt-out, reativação, novo opt-out, tudo preservado e ordenado.

| coluna | tipo | observação |
| --- | --- | --- |
| `id` | uuid | PK |
| `channel` | varchar(32) | par de identidade, como em `lead_qualification` |
| `conversation_key` | varchar(64) | |
| `evento` | varchar(16) | `OPT_OUT` ou `REATIVACAO` |
| `message_id` | uuid, nulo | a mensagem que disparou o opt-out; nulo na reativação |
| `autor` | varchar(120), nulo | quem reativou; nulo no opt-out, que é ato do lead |
| `motivo` | text, nulo | justificativa da reativação; nulo no opt-out |
| `created_at` | timestamptz | `server_default=func.now()`, como nas outras cinco tabelas do repositório. **Corrigido depois da entrega:** era escrito pelo cliente, e nesta tabela a ordem **é** o estado — skew de relógio entre o worker que grava o opt-out e a máquina que roda a reativação inverteria os dois eventos. |

Índice `(channel, conversation_key, created_at DESC)` — a consulta quente é `ORDER BY created_at DESC LIMIT 1`.

**O registro referencia `message_id`, não copia o texto.** O corpo já está cifrado em `messages`; copiá-lo criaria uma segunda cópia em claro da fala do lead, contra a disciplina de PII que este repo mantém. A RN-14.2 pede "o conteúdo original que o disparou" — a referência **é** o conteúdo original, e é a versão que não duplica dado pessoal.

`autor` e `motivo` são nulos no opt-out por natureza: o ato é do lead, e inventar um autor sintético mentiria sobre quem agiu.

### D5 — Grava antes de entregar a confirmação

O opt-out é persistido **antes** de a mensagem de confirmação sair.

É o precedente do bloqueio de moderação, que faz `marcar_bloqueada` antes de `_entregar_texto_fixo`, e a direção do erro decide. Gravado e a entrega falha: o lead fica em silêncio sem receber confirmação — ruim, e conforme. Entregue e a gravação falha de forma terminal: temos um opt-out não registrado e continuamos mandando mensagem. **Essa é a violação**, e é a que a ordem impede.

`_entregar_texto_fixo` tem **quatro** saídas que não entregam nada — janela fechada (`expirado`), recusa permanente da Meta (`sem_resposta`), reentrega suprimida (`reentrega_suprimida`) e bloqueio pela própria guarda de opt-out (`bloqueado_por_optout`) —, e todas fecham a linha em estado terminal. Gravar depois deixaria o opt-out perdido exatamente nos casos em que ninguém volta àquela linha. (A versão original deste documento dizia “três”; o comentário em `turno.py` já dizia quatro.)

**Corrigido depois da entrega — a falha retentável não é nenhuma das quatro.** O que a decisão acima aceita é o lead ficar sem confirmação nas saídas **terminais**. Um `EnvioRetentavel` (5xx da Meta) não é terminal: a guarda libera a reserva, a exceção sobe, a linha vira FAILED e o sweeper reenfileira a mesma mensagem. Como entregue, o segundo turno batia no short-circuit incondicional de `esta_em_optout` no topo de `executar_turno`, devolvia `silenciado` e fechava em PROCESSED — e **a confirmação se perdia para sempre**, num custo que ninguém escolheu: ele caiu entre duas tasks. O conserto: o short-circuit não dispara quando a mensagem em mãos é ela própria um pedido de opt-out, e aí o turno segue e reentrega. A idempotência de quem já recebeu continua vindo da reserva em `outbound_dispatches` — se a confirmação saiu, a reserva ainda existe, `send` devolve `False` e o desfecho é `reentrega_suprimida`, com o alarme certo. O custo aceito, e declarado: um lead que já optou e digita “parar” de novo recebe confirmação de novo. É a exceção que a D1 já nomeia.

### D6 — Reativação por script administrativo

`python -m mobia.admin.reativar --channel wa --key <conversation_key> --autor "<nome>" --motivo "<texto>"`

O projeto **não tem camada de autenticação**: existe uma rota (`whatsapp.py`, webhook autenticado por HMAC da Meta) e nada mais. JWT, OIDC e papéis são a TEC-201, com zero linhas. Um endpoint HTTP sem autenticação que reverte proteção de LGPD é pior que não ter reativação: qualquer um que alcance a porta apaga a proteção do lead.

Quem consegue rodar o script já tem acesso ao servidor e ao banco — isso **é** a autenticação, e é mais forte que segredo compartilhado. Zero superfície HTTP nova para a operação mais perigosa do sistema.

A lógica mora numa função de domínio (`reativar`), e o script é só o ponto de entrada. Quando o dashboard existir (TEC-189), ele chama a mesma função. `--autor` e `--motivo` são obrigatórios: sem justificativa o comando falha, porque a RN-14.3 exige justificativa e um default vazio a tornaria decorativa.

## Fluxo

```
mensagem do lead chega
  |
  +-- ja ha opt-out ativo?  --sim-->  nao responde nada.
  |                                    a mensagem fica gravada.
  |                                    (a guarda de D3 barra na porta)
  nao
  |
  +-- o texto dispara opt-out? (D2)
  |     |
  |    sim --> grava OPT_OUT (D5) --> entrega confirmacao pelo kind dedicado
  |                                    e encerra o turno
  nao
  |
  +-- moderacao de entrada (ja existe)
  |
  +-- turno normal: contexto, classificacao, entrega
```

A checagem de opt-out no texto entra **antes do bloco de moderação de entrada**, e antes de montar contexto — pelo mesmo motivo que põe a moderação lá: economiza o turno pago inteiro, e o texto do lead ainda não passou por lugar nenhum.

**Corrigido depois da entrega:** o diagrama acima punha a moderação **antes** da detecção, e a prosa dizia que a checagem entrava *“junto do bloco de moderação”*. A revisão da Task 5 rejeitou essa ordem como Critical, e o código entregue faz o contrário. O bloco de moderação de entrada tem `return` próprio: uma mensagem que é **ao mesmo tempo** um pedido de opt-out e algo que a moderação reprova — *“pare de mandar mensagem”* com um xingamento junto — nunca chegaria ao registro, a moderação devolveria a recusa de entrada primeiro, e continuaríamos mandando mensagem (a própria recusa) para quem pediu para sair. Detectar primeiro também poupa a chamada paga de moderação no caminho de opt-out.

## Testes

**Detecção** (unitários, sem banco): cada termo inequívoco dispara no meio de uma frase; cada termo ambíguo dispara sozinho e **não** dispara dentro de frase — com os casos reais como prova, *"podemos parar por aqui hoje?"* e *"quero sair do aluguel e comprar"* não são opt-out. Normalização de acento, caixa e pontuação: `PARAR!` e `Parar` disparam.

**Registro** (integração): o evento grava com `message_id` e sem cópia do texto; o estado atual é o último evento; reativação seguida de novo opt-out preserva os três eventos.

**A guarda** (integração): com opt-out ativo, `GuardedOutbound.send` não entrega e não reserva; o `kind` de confirmação atravessa. Um teste demonstra que a guarda barra um envio que **não** passa por `executar_turno` — é o que prova que ela é invariante e não regra local.

**Ordem** (integração): falha na entrega da confirmação deixa o opt-out gravado.

**Script**: `--motivo` ausente falha; a reativação grava autor e motivo e devolve o lead ao estado respondível.

## Lacunas declaradas

**O cenário do debounce da card não é testável hoje.** A RN-01.6 (debounce de rajada) não está implementada — procurar por `debounce` devolve zero. O cenário *"opt-out durante rajada não espera o debounce"* é vacuamente verdadeiro. Fica registrado: **quem implementar a RN-01.6 tem que furar a janela para o opt-out**, e o teste correspondente nasce com ela.

**A reativação não tem interface.** Só o script. É decisão de D6, não esquecimento, e a TEC-189 herda a função de domínio pronta.

**A detecção é lista fixa, e vai errar por falta.** Um lead que escreve "chega" ou "me deixa em paz" não é detectado por nenhuma faixa. A lista não é estendida por antecipação: cada termo novo é risco de falso positivo, e não há dado sobre como leads deste produto pedem para sair. Quando houver conversa real, os textos dizem quais termos faltam.

**Não há métrica de opt-out.** Quantos acontecem, e se algum foi falso positivo, ninguém saberá. Cabe numa card do epic de observabilidade, não nesta.

**A moldura de cortesia não é detectada.** A faixa estrita compara a **mensagem inteira** normalizada, então *“por favor pare”*, *“obrigado, pode parar”* e *“pode parar por favor”* não disparam nada — e são exatamente a forma educada, que é comum. Não foi consertado aqui de propósito: relaxar a faixa estrita para aceitar moldura é redesenho da regra (qual moldura vale? quantas palavras a mais?) e reabre o falso positivo que ela existe para fechar. Fica declarado como lacuna de recall, junto do parágrafo acima.

**`nao quero mais receber nada` deixou de disparar.** Consequência direta do conserto da D2: quem escrever exatamente essa frase e parar por aí não é detectado. É a troca escolhida — três falsos positivos provados contra um falso negativo hipotético — e ela some quando houver conversa real para calibrar a lista.

**O que a [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) precisa fazer para não furar a guarda.** A card que esta destrava é a que mais provavelmente vai fazer o buraco, e são quatro exigências, nenhuma delas garantida pelo compilador:

  1. **Herdar `GuardedOutbound`, e nunca implementar `OutboundPort` direto.** O `Protocol` é estrutural — ver a correção da D3. Uma classe com `async def send` satisfaz o tipo sem herdar nada, e não tem guarda nenhuma.
  2. **Passar um `message_id` que exista em `messages` e pertença ao lead alvo.** A guarda resolve `(channel, conversation_key)` a partir da linha em `messages`, e é **fail-open** para id inexistente: sem lead atrás do id não há estado a consultar, e recusar o envio só esconderia o defeito do chamador. Um follow-up disparado com uuid sintético passa **sem checagem nenhuma**.
  3. **Nunca reusar `KIND_DA_CONFIRMACAO_DE_OPTOUT`.** Aquele `kind` é bypass incondicional da guarda; é o único, e existe só para a confirmação do próprio pedido.
  4. **Manter `payload["para"]` coerente com o `conversation_key` da mensagem.** A guarda decide pelo lead da mensagem, e o adaptador do WhatsApp envia para `payload["para"]`. **Nada amarra os dois hoje**: um follow-up que passe o `message_id` de um lead e o telefone de outro é aprovado pela guarda e entregue ao endereço errado.

**A evidência de LGPD se autodestrói no relógio de retenção de `messages`.** A D4 diz que o registro referencia `message_id` em vez de copiar o texto, e que *“a referência **é** o conteúdo original”*. Isso vale enquanto a linha em `messages` existir. Quando a RNF-22 (retenção de 12 meses de `messages`) for implementada, o `message_id` do evento vira ponteiro solto e a afirmação da D4 deixa de valer: sobra o evento sem o conteúdo que a RN-14.2 pede. A migração `0010` já não tem FK para `messages` justamente para a limpeza não apagar evidência por cascata — mas não ter FK preserva a **linha**, não o **conteúdo**. Quem implementar a RNF-22 precisa decidir, explicitamente, o que fazer com o corpo referenciado por um `optout_events` antes de apagá-lo.

## Fora de escopo

- Eliminação e anonimização de dados pessoais — RNF-21 e RNF-22, card própria.
- A cadência de follow-up — [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183), que esta card destrava.
- Autenticação, papéis e dashboard — TEC-201 e TEC-189.
- A entidade `Lead` do SRS. Este desenho usa o par `(channel, conversation_key)`, que é a identidade que o repo já pratica.
- `consentimento_marketing` (RNF-19). É irmão do opt-out e não é a mesma coisa: um é recusa, o outro é permissão prévia.
