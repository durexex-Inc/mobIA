# TEC-182 — Detectar e registrar opt-out imediato

**Status:** aprovado em 2026-09-01. Não implementado.

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

- **Termos inequívocos** disparam em qualquer posição da mensagem: `descadastrar`, `descadastre`, `nao quero mais receber`, `pare de me mandar`, `pare de mandar`, `me tira da lista`, `me tire da lista`, `remover meu contato`, `nao me mande mais`. Nenhum aparece em fala de quem procura imóvel.
- **Termos ambíguos** disparam **só quando são a mensagem inteira**, normalizada (minúsculas, sem acento, sem pontuação, sem espaço nas bordas): `sair`, `parar`, `pare`, `stop`, `cancelar`. Cobre o padrão real de quem quer sair — a mensagem de uma palavra só — sem pegar a frase em que a palavra é incidental.

Determinístico, sem chamada paga, e a lista mora numa constante com o motivo de cada faixa escrito ao lado. A comparação é sobre o texto normalizado, então acento e caixa não abrem buraco: `PARAR!` e `Parar` disparam.

**A assimetria aqui é o inverso da TEC-257, e por isso a decisão não pode ser copiada de lá.** Naquela card, marcar de mais era o erro perigoso e marcar de menos o seguro. Aqui, **deixar de detectar um opt-out é violação de LGPD**; detectar demais é prejuízo comercial. Os dois são ruins, mas só um é ilegal — e é por isso que os termos inequívocos são generosos e só os ambíguos são estritos.

### D3 — A guarda mora na porta de saída, não no turno

A checagem de opt-out entra em `GuardedOutbound.send`, antes da reserva em `outbound_dispatches`.

Se vivesse dentro de `executar_turno`, protegeria o caminho de hoje e nada mais. A TEC-183 vai criar um segundo caminho de envio, e nada garantiria que ela lembrasse da checagem. Na porta, **todo envio presente e futuro herda a guarda** e esquecer deixa de ser possível. É a diferença entre uma regra e um invariante — e a card diz, com todas as letras, que ligar a cadência sem a chave de desligamento é o caminho para o bloqueio do número.

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
| `created_at` | timestamptz | |

Índice `(channel, conversation_key, created_at DESC)` — a consulta quente é `ORDER BY created_at DESC LIMIT 1`.

**O registro referencia `message_id`, não copia o texto.** O corpo já está cifrado em `messages`; copiá-lo criaria uma segunda cópia em claro da fala do lead, contra a disciplina de PII que este repo mantém. A RN-14.2 pede "o conteúdo original que o disparou" — a referência **é** o conteúdo original, e é a versão que não duplica dado pessoal.

`autor` e `motivo` são nulos no opt-out por natureza: o ato é do lead, e inventar um autor sintético mentiria sobre quem agiu.

### D5 — Grava antes de entregar a confirmação

O opt-out é persistido **antes** de a mensagem de confirmação sair.

É o precedente do bloqueio de moderação, que faz `marcar_bloqueada` antes de `_entregar_texto_fixo`, e a direção do erro decide. Gravado e a entrega falha: o lead fica em silêncio sem receber confirmação — ruim, e conforme. Entregue e a gravação falha de forma terminal: temos um opt-out não registrado e continuamos mandando mensagem. **Essa é a violação**, e é a que a ordem impede.

`_entregar_texto_fixo` tem três saídas que não entregam nada — janela fechada, recusa permanente da Meta, reentrega suprimida — e duas fecham a linha em estado terminal. Gravar depois deixaria o opt-out perdido exatamente nos casos em que ninguém volta àquela linha.

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
  +-- moderacao de entrada (ja existe)
  |
  +-- o texto dispara opt-out? (D2)
  |     |
  |    sim --> grava OPT_OUT (D5) --> entrega confirmacao pelo kind dedicado
  |                                    e encerra o turno
  nao
  |
  +-- turno normal: contexto, classificacao, entrega
```

A checagem de opt-out no texto entra **junto do bloco de moderação de entrada**, antes de montar contexto — pelo mesmo motivo que a moderação está lá: economiza o turno pago inteiro, e o texto do lead ainda não passou por lugar nenhum.

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

## Fora de escopo

- Eliminação e anonimização de dados pessoais — RNF-21 e RNF-22, card própria.
- A cadência de follow-up — [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183), que esta card destrava.
- Autenticação, papéis e dashboard — TEC-201 e TEC-189.
- A entidade `Lead` do SRS. Este desenho usa o par `(channel, conversation_key)`, que é a identidade que o repo já pratica.
- `consentimento_marketing` (RNF-19). É irmão do opt-out e não é a mesma coisa: um é recusa, o outro é permissão prévia.
