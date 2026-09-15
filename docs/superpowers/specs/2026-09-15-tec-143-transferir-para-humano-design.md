# TEC-143 — Transferir para humano ao pedido explícito

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-143](https://eduardodurieuxlopes.atlassian.net/browse/TEC-143) — Must (MoSCoW), épico TEC-133 (Roteamento por intenção e humanização)
**Branch:** `feat/tec-143-transferir-para-humano`
**Origem:** RF-04, RN-04.6 (SRS v1.0); RN-16.1
**Dependências:** nenhuma que ainda falte. A card declarava depender do registro de handoff (E7); aquele épico tem oito cards em Feito.

## Objetivo

Quando o lead pede para falar com uma pessoa, o atendimento para de qualificar e vai para a fila humana. Hoje isso não acontece: o pedido não é detectado de forma nenhuma, e o lead segue no loop de perguntas — que é exatamente a dor que a card descreve.

O desenho entrega **uma guarda determinística antes do classificador**, no molde exato da guarda de opt-out que já existe, mais o silêncio do agente enquanto o handoff estiver aberto.

## O que já existe, e é quase tudo

A descoberta que mais encurta esta card está na docstring de `Gatilho` (`domain/handoff/vocabulario.py`):

> **Nasce completo, com fiacao para tres.** Acrescentar valor a este enum depois custa migration [...] acrescentar um CHAMADOR nao custa nada. **TEC-143**, TEC-149 e TEC-170 chegam e so chamam `registrar_handoff` com o gatilho que ja existe.

| peça | estado |
| --- | --- |
| `Gatilho.PEDIDO_DE_HUMANO` | **existe**, e `PRIORIDADE_DE` o mapeia para `ALTA` — o único ALTA da RN-16.1 |
| `registrar_handoff(...)` | existe, com `ON CONFLICT` que arbitra corrida |
| Um handoff aberto por conversa | garantido no banco pela `0030` |
| Detecção do pedido | **não existe** |
| Silêncio do agente enquanto espera humano | **não existe** para este caso — ver D3 |
| Janela de atendimento da imobiliária | **não existe** |

## Decisões

### D1 — A detecção é determinística, e não uma oitava intenção

Medido em 15/09/2026: acrescentar `FALAR_COM_HUMANO` ao enum `Intencao` custa **5 tokens** no schema compilado (372,8 → 377,8), levando a margem do orçamento de prompt de **6,2 para 1,2 tokens**. Cabe, mas consome 80% da folga — e exigiria emenda à RN-03.1, que fala em "as sete intenções".

O custo de tokens não é o argumento principal. O principal é que **o handoff passaria a depender de uma chamada paga que pode falhar**, e ela falha pior justamente quando o lead já está irritado o bastante para pedir uma pessoa. O mesmo raciocínio já está escrito em `pediu_optout`: *"Deterministico e sem chamada paga: uma decisao de LGPD nao pode depender de um provedor estar de pe."*

A guarda também torna o critério "handoff em até 5 segundos" uma consequência da arquitetura, e não uma aposta na latência do modelo: quando ela dispara, o turno nem chama o classificador.

**Custo declarado:** quem escrever o pedido de um jeito que a lista não pega continua no loop de robô. É falha de recall, e é o risco central desta card.

### D2 — A lista segue a forma de `pediu_optout`, inclusive na armadilha que ela documenta

`domain/optout/deteccao.py` separa `_TERMOS_INEQUIVOCOS` (casam por substring) de `_TERMOS_AMBIGUOS` (só casam a mensagem inteira). O novo módulo `domain/humano/deteccao.py` expõe `pediu_humano(texto) -> bool` com a mesma estrutura e o mesmo normalizador (minúsculas, sem acento, espaços colapsados).

Aquele módulo registra uma lição cara: `"nao quero mais receber nada"` foi **removido** dos inequívocos porque "nada" aceita complemento partitivo, e cada refinamento de busca silenciava um comprador para sempre.

O análogo aqui é `"pessoa"`. Medido contra o corpus de evals (147 mensagens de lead), `"pessoa"` aparece 2 vezes — as duas dentro de **"pessoalmente"**, em perguntas sobre assinar à distância. Casar `"pessoa"` por substring transformaria pergunta sobre procuração em transferência para humano. Por isso nenhum termo da lista é uma palavra solta: todos carregam o verbo ou a preposição que os torna um pedido.

**Os 15 termos candidatos foram medidos contra o corpus: zero falsos positivos.** O corpus não contém nenhum pedido de humano, então a medição prova ausência de falso positivo, **não** cobertura — o recall continua sendo a lacuna declarada em D1.

### D3 — O silêncio vem do handoff aberto, não de `AtendimentoHumano`

A intuição natural é reusar o silêncio que a TEC-179 construiu. **Ela não serve**, e a razão é de modelagem: `assumir(session, *, channel, conversation_key, corretor_id)` exige `corretor_id`, e `AtendimentoHumano.assumido_por` é `NOT NULL`. Aquela tabela representa *"este corretor assumiu"*. No instante do pedido não há corretor: o handoff nasceu e está na fila.

Tornar `assumido_por` nullable foi recusado — faria "ninguém assumiu" e "fulano assumiu" conviverem numa coluna cujo significado é justamente o segundo, e mexeria em código testado da TEC-179 sem necessidade.

O agente passa a calar quando a conversa está assumida **ou** quando existe handoff aberto com gatilho `PEDIDO_DE_HUMANO`. A segunda condição usa a entidade que já significa "isto está com um humano, ou a caminho", e a `0030` já garante no banco que não há dois handoffs abertos por conversa — então a consulta é determinística.

Isso exige uma função de leitura nova em `handoff/repositorio.py`, que hoje só tem `registrar_handoff`, `carregar_dossie` e `gravar_resumo`.

### D4 — A guarda entra depois do opt-out e antes do classificador

A ordem não é estética. O comentário em `turno.py` registra um **Critical de revisão**: uma guarda incondicional de atendimento humano engolia o registro do opt-out, e um lead que digitasse "pare" numa conversa assumida nunca tinha o pedido gravado — defeito de LGPD.

A ordem fica: **opt-out → pedido de humano → moderação de entrada → classificador**. Opt-out é direito do lead e vence tudo, inclusive um pedido de humano na mesma mensagem.

### D5 — A janela de atendimento é fixa e da imobiliária

`atendimento_horario_inicio` e `atendimento_horario_fim` em `Settings`, no molde de `followup_horario_inicio/fim`, com o mesmo fuso único da POC (PR-04).

A alternativa — usar a jornada do corretor designado, que a TEC-196 já modelou — foi recusada porque exigiria resolver o destinatário **antes** de responder ao lead, e a alocação por especialidade e região é a TEC-166, ainda em A fazer. Uma janela da imobiliária responde "quando alguém vai te atender" sem saber quem.

**Fora do horário, o handoff é criado do mesmo jeito** — o que muda é só o texto que o lead recebe. A card é explícita: *"nunca em espera silenciosa"*.

### D6 — O texto ao lead mora no módulo do assunto

`TEXTO_DO_PEDIDO_DE_HUMANO` e `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` ficam em `domain/humano/deteccao.py`, pela razão que `TEXTO_DA_CONFIRMACAO_DE_OPTOUT` registra: *"o texto pertence ao assunto, nao ao orquestrador que o entrega"*.

Os dois levam **acento** — é texto que chega ao lead (TEC-267). O texto fora do horário nomeia a janela em horas locais.

## Lacunas declaradas

**Recall da lista é o risco central, e não tem medição possível hoje.** O corpus de evals não contém nenhum pedido de humano, então ele prova ausência de falso positivo e nada sobre cobertura. A primeira conversa real que pedir uma pessoa de um jeito não previsto continuará no loop. Mitigação sugerida para depois: registrar em log os turnos que o classificador marcou `FORA_DE_ESCOPO` logo após uma pergunta de qualificação, que é a assinatura provável de um pedido não pego.

**O corretor não é notificado — mas a esteira é percorrida, e a distinção importa.** Corrigido na revisão final (Critical 1): o bloco desta card nascia sem a chamada a `_agendar_resumo`, que os outros cinco sítios de `registrar_handoff` fazem depois do commit. Sem ela a cadeia inteira caía atrás — sem `gerar_resumo`, sem `enqueue_job(NOTIFICAR_JOB)`, sem `sla_limite_em`, e `escalar_vencidos` nunca via o handoff. Quem o pegava era a rede de recuperação da TEC-279, 10 a 15 minutos depois e logando `handoff.recuperado_sem_prazo` em *warning*: a rede de segurança virando o caminho normal do único gatilho `ALTA` da RN-16.1, e o alarme dela virando ruído permanente.

Com a chamada no lugar, o que de fato acontece é: o handoff agenda o resumo, o resumo enfileira `notificar`, o job resolve o destinatário (corretor alocado, ou generalista de plantão — Emenda E-01 da RN-16.2), grava `sla_limite_em` dentro da jornada dele (Emenda E-01 da RN-16.3) e o handoff passa a ser visível para `escalar_vencidos`. **Sem destinatário nenhum**, ele nasce `ESCALADO` e sem prazo (Emenda E-02 da RN-16.3), marcado como pendente de aviso manual. E, no fim da linha, **os dois canais registram e não entregam** (Emenda E-02 da RN-16.2): percorrer a esteira significa que o prazo e a escalada existem, não que alguém foi avisado. É exatamente por isso que o texto ao lead não pode afirmar que foi — ver a lacuna seguinte.

**O texto ao lead não promete aviso, e a proibição é antiga.** As duas constantes escreviam *"Já avisei nossa equipe"*. É a terceira aparição da mesma frase no repositório: a TEC-174 escreveu *"já avisei um corretor"* e teve de reescrever o texto inteiro, `notificacao/envio.py` registrou por escrito *"Não reintroduza a promessa"*, e o plano desta card a reintroduziu assim mesmo. As constantes passaram a falar do **encaminhamento** e do **horário**, no molde de `TEXTO_DO_LIMITE_DE_PERGUNTAS` e `TEXTO_DA_JANELA_HUMANA`, com um comentário acima delas registrando a proibição para não voltar numa quarta card.

**Dois horários diferentes podem chegar ao mesmo lead.** `TEXTO_DA_JANELA_HUMANA` (TEC-177) já diz um horário ao lead, com as horas do **corretor** (`corretores.horario_inicio`/`horario_fim`, resolvidas no job de notificação); `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` diz as horas da **imobiliária** (`Settings.atendimento_horario_*`, a D5 acima). Nada impede que a mesma conversa receba os dois, com números diferentes. Não é consertado nesta card: as duas janelas respondem perguntas diferentes — *"quando há gente na imobiliária"* contra *"a jornada de quem vai te atender"* — e unificá-las é decisão de produto, não de código. Declarado no comentário das constantes em `domain/humano/deteccao.py`.

**Nada aloca o handoff a um corretor.** É a TEC-166. O handoff nasce sem destinatário resolvido.

**A guarda não distingue quem pede de quem menciona.** "Minha esposa quer falar com uma pessoa" dispara. Aceito: errar por sobra manda o lead para um humano, que é o destino que ele teria de qualquer forma.

**A guarda não distingue o interlocutor NOSSO do de terceiro — e isto é um eixo, não um caso isolado.** Verificado rodando: `"preciso falar com uma pessoa do banco antes de fechar"`, `"tenho que falar com uma pessoa do cartorio sobre a escritura"` e `"vou falar com uma pessoa da minha familia e te retorno"` **disparam**, e a família da frase é previsível — banco, cartório, financiamento, família, prefeitura. **Decisão mantida: `"falar com uma pessoa"` não é qualificada.** É a frase literal do critério de aceite da card, e exigir que o termo fixe de quem é a pessoa mataria o caso central. O preço é este eixo inteiro, e ele é pior que o da esposa acima: ali o lead acabava num humano que ele teria de qualquer forma; aqui ele nem pediu um.

Do lado oposto, o eixo **da polaridade** foi consertado (Important 4 da revisão final): `"nao quero falar com atendente, so me manda os imoveis"` e `"nao precisa falar com um humano, resolvo por aqui"` disparavam, e ali o argumento do "errar por sobra" não vale — o lead disse o contrário, e o custo não é uma transferência a mais, é o agente calar para sempre numa conversa que ele quis seguir com o robô. Uma guarda de negação imediata (`_NEGACAO_ANTES`) cobre isso, sem matar `"nao quero falar com robo"`, onde a negação é sobre o robô.

Os dois buracos passaram por quatro rodadas de revisão porque elas geravam **casos** e não **critério**. O invariante em `deteccao.py` ganhou um **quarto eixo** justamente para isso: além dos três papéis gramaticais, o termo tem de fixar que o interlocutor é nosso e tem de ser falso sob negação, e quem acrescentar termo roda `pediu_humano("nao quero <termo>")` e `pediu_humano("<termo> do banco")` antes de commitar. `"falar com uma pessoa"` reprova a segunda e fica: é a exceção conhecida, escrita ao lado do critério.

## Testes

**Unitários, sem Docker** — `pediu_humano` é pura: os 15 termos, o normalizador, a defesa de "pessoalmente", e os ambíguos que só casam a mensagem inteira.

**Integração** — a guarda dentro de `executar_turno`: dispara e cria handoff `ALTA` com gatilho `PEDIDO_DE_HUMANO`; não chama o classificador quando dispara; opt-out na mesma mensagem vence; o agente cala nas mensagens seguintes e elas continuam sendo registradas; dentro e fora da janela mudam o texto e não a criação do handoff.

**O teste que fecha a D4** merece nome próprio: uma mensagem que é pedido de humano **e** opt-out tem de gravar o opt-out, pelo precedente do Critical.

## Fora de escopo

- Notificação ao corretor, SLA de aceite e escalonamento (E7).
- Alocação do handoff por especialidade e região (TEC-166).
- Detectar o pedido por semântica, via modelo (D1).
- Jornada por corretor no aviso ao lead (D5).
