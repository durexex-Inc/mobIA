# TEC-139 — Identificar-se como assistente virtual

**Status:** desenhado em 2026-09-11 na branch `feat/tec-139-identificacao-do-assistente`.

**Card:** [TEC-139](https://eduardodurieuxlopes.atlassian.net/browse/TEC-139) — Must (MoSCoW), prioridade Highest. Origem: RF-04, RN-04.1 (SRS v1.0); RN-B01. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

## Objetivo

O lead passa a saber com quem está falando desde a primeira mensagem, sem que isso dependa de o modelo lembrar.

## O estado de hoje

**O prompt dá o papel, não a obrigação de revelá-lo.** `SISTEMA_DO_AGENTE` abre com *"Voce e o assistente virtual de uma imobiliaria brasileira"* — isso instrui o modelo sobre **quem ele é**, e não sobre **dizer quem é**. Nada no sistema identifica o agente ao lead, e nada obriga a confirmar quando perguntado. As quatro regras da card estão todas por fazer.

**A fronteira de conversa não existe, e o SRS já diz isso em letras.** A emenda E-01 da TEC-148 sob a RN-05.7:

> *"Não há fronteira de conversa no sistema: `conversation_key` é o id externo do lead, e `messages`, `lead_qualification`, `conversation_summaries` e `optout_events` todos o usam com esse sentido; introduzir a entidade de conversa é maior que esta card e fica deferido."*

Duas das quatro regras desta card — identificar-se *"na primeira mensagem de cada conversa"* e *"conversa nova do mesmo lead se identifica de novo"* — pressupõem exatamente essa fronteira. A entidade de verdade é a [TEC-130](https://eduardodurieuxlopes.atlassian.net/browse/TEC-130) (*"Encerrar por inatividade de 30 dias e reabrir com histórico"*), no épico TEC-123, aberto.

**A margem do orçamento do prompt é de 6,2 tokens**, medida em 2026-09-11 por `pytest -k margem_do_orcamento -s` (líquido 786,8 contra teto fixo de 793,0). É a mesma folga estreita que a TEC-141 encontrou e gastou. Qualquer instrução nova em `SISTEMA_DO_AGENTE` estoura, e o ritual do `CLAUDE.md` se aplica: *"o que sai para o novo texto entrar?"* antes de *"quanto subo o número?"*.

## Decisões

### D1 — A fronteira de conversa é derivada, e declarada provisória

```
conversa_nova  ⟺  não há mensagem deste lead nos últimos 30 dias,
                  EXCLUÍDA a mensagem que está sendo processada
```

Lida do timeline de `messages`, que já tem o índice `(channel, conversation_key, created_at DESC)` — a mesma consulta quente que `optout_events` e a janela de contexto já fazem. Custa uma consulta indexada por turno.

**A exclusão da mensagem corrente não é detalhe de implementação, é a diferença entre funcionar e nunca disparar.** A ingestão grava a linha em `messages` **antes** de o worker existir — quando `executar_turno` roda, a fala que ele está processando já está no timeline. Uma consulta ingênua por "alguma mensagem nos últimos 30 dias" encontraria sempre a própria, `conversa_nova` seria permanentemente falso, e a identificação nunca sairia. O predicado é sobre a mensagem **anterior**: `WHERE id != message.id`, ou equivalentemente o `created_at` mais recente abaixo do da corrente. O teste que prova isso é o de uma conversa realmente nova — sem ele, a regressão passa verde, porque todo teste de "não repete na segunda mensagem" continuaria passando por um motivo errado.

**O número não é inventado.** Trinta dias é o limiar que a TEC-130 nomeia no próprio título. Usar outro valor aqui criaria duas definições de "conversa nova" antes mesmo de a primeira existir; usar o mesmo antecipa a definição dela em vez de competir com ela. A constante vive num lugar só, com o comentário registrando que a TEC-130 a substitui pela entidade real.

**Consequência declarada:** até a TEC-130, "conversa" é uma janela de silêncio e não um objeto. Um lead que responde no 31º dia começa conversa nova; um que responde no 29º continua na mesma. A fronteira é uma escolha de corte, não um fato do domínio — e é por isso que ela é provisória.

**A interação com a cadência de reengajamento foi verificada, e é benigna.** `CADENCIA` (`domain/followup/cadencia.py`) termina em **14 dias** no pior caso (`FRIO`), e a TEC-187 marca o lead como `DORMENTE` ao fim dela. Nenhum follow-up alcança 30 dias de silêncio, então a fronteira nunca dispara no meio de uma cadência. Um lead que volta depois disso é conversa nova e se identifica — que é o comportamento certo, obtido sem código extra.

### D2 — A identificação é determinística e prefixa a primeira saída da conversa

Texto fixo, montado por código, prefixado à primeira mensagem que enviamos numa conversa nova.

**Por que não no prompt.** Três razões, na ordem de peso. O orçamento tem 6,2 tokens e a instrução custaria ~25-30, então ela exigiria subir o teto para entregar o que código entrega de graça. Um critério de aceite **Must** passaria a depender de o modelo lembrar num turno qualquer — e a RN-B01 classifica a rejeição ao atendimento automatizado como risco de impacto **Alto**, com a transparência como mitigação central. E a verificação sairia de uma igualdade exata em teste unitário para uma execução paga com amostragem.

**Vale para toda trilha de saída** — resposta normal do agente, recusa da moderação (`TEXTO_DA_RECUSA_DE_ENTRADA`), texto neutro de saída, confirmação de opt-out. Uma regra só, sem exceção para decorar: se é a primeira mensagem que mandamos nesta conversa, ela diz quem somos. A alternativa — identificar só na resposta normal — deixaria o lead cuja primeira mensagem caiu na moderação receber texto nosso sem saber de quem é, que é exatamente o dano que a RN-04.1 existe para evitar.

**O prefixo entra depois da moderação de saída**, pelo mesmo argumento que a TEC-162 já escreveu para as fichas de imóvel: *"moderar dado nosso seria gastar chamada sobre texto que nao inventamos"*. O texto é uma constante do repositório, não saída de modelo.

**O texto é genérico e não nomeia a imobiliária**, porque não existe nome configurável em `app/config.py`. A RN-04.1 também é genérica (*"assistente virtual da imobiliária"*), então o texto segue a regra em vez de inventar um campo de configuração que ninguém pediu. Introduzir esse campo é card própria.

O texto também **oferece o corretor**, que é a regra 3 da card no caminho proativo.

### D3 — As regras 2 e 3 são medidas antes de custar orçamento

As regras reativas — *"perguntado diretamente se é pessoa ou robô, confirma ser assistente virtual"* e *"ao confirmar, oferece transferência"* — podem já estar satisfeitas: o modelo recebe o papel no system prompt, e confirmar-se como assistente é o comportamento natural dali. **Ou podem não estar.** Ninguém mediu.

Então mede-se antes: turnos de sondagem (*"vc é um robô?"*, *"tô falando com uma pessoa?"*, *"isso é automático?"*, e a formulação hostil *"você é humano ou máquina? não quero falar com robô"*) rodados contra o modelo real, olhando duas coisas por turno — confirma, e oferece corretor.

* **Se confirma e oferece:** `SISTEMA_DO_AGENTE` não muda, e o desenho registra o número medido.
* **Se falha:** aí a instrução entra, e só aí a pergunta *"o que sai para ela entrar?"* se abre — antes de qualquer discussão sobre subir o teto. E o teto derivado (`subcontagem < contexto_headroom_de_tokens × 0,75`) é calculado antes, porque passar o fixo do derivado torna o fixo decorativo.

Este é o mesmo desenho que a D4 da TEC-142 usou uma card atrás. Lá a aposta se pagou: a medição mostrou que os dois casos de composição familiar **liberavam**, um defeito real que a suposição teria escondido. O custo de medir é uma execução pequena; o custo de não medir é gastar orçamento apertado num problema que talvez não exista, sem evidência de que resolveu.

## Fluxo

```
executar_turno
  │
  ├─ (moderação de entrada, opt-out, contexto, modelo, moderação de saída — inalterados)
  │
  └─ ANTES DE QUALQUER ENTREGA
       conversa_nova? ──não──> entrega o texto como está
              │
             sim
              │
              └─> texto = IDENTIFICACAO + separador + texto
                  e entrega

Vale para: resposta normal · recusa da moderação · texto neutro · confirmação de opt-out
```

## Testes

**Unitários, a derivação da fronteira** — sem mensagem anterior é conversa nova; mensagem de 31 dias atrás é conversa nova; de 29 dias não é; o limite exato de 30 dias tem lado definido e testado (o empate não fica ao acaso — a TEC-229 existe porque um teste de janela se apoiou em empate exato).

**Unitários, o texto** — identifica como assistente virtual, oferece corretor, e não excede o teto de tamanho de mensagem.

**Integração, as quatro trilhas** — primeira resposta de conversa nova carrega a identificação; segunda resposta da mesma conversa **não** a repete; recusa da moderação em conversa nova carrega; confirmação de opt-out em conversa nova carrega.

**Integração, a regra 4** — dois turnos separados por mais de 30 dias no mesmo lead produzem **duas** identificações; separados por menos, uma só.

**Ordem** — a identificação entra depois da moderação de saída e antes da entrega, e o recorder grava o texto entregue (com a identificação), não o texto anterior a ela.

## Emendas ao SRS

Uma, aninhada sob a RN-04.1:

> **Emenda E-01 (TEC-139, 11/09/2026):** "conversa", na expressão *"primeira mensagem de cada conversa"*, passa a ter definição operacional: **não há mensagem do lead nos últimos 30 dias**, derivada do timeline de `messages`. A definição é **provisória** e existe porque a entidade de conversa não existe — a emenda E-01 da TEC-148 sob a RN-05.7 registra que ela foi deferida, e a TEC-130 é quem a cria. O limiar de 30 dias é o mesmo que a TEC-130 nomeia, e não um segundo número: quando aquela card chegar, esta definição é substituída pela entidade, não reconciliada com ela. A identificação vale para a **primeira mensagem de saída** da conversa em qualquer trilha — resposta do agente, recusa da moderação (RN-04.5), texto neutro de saída ou confirmação de opt-out (RN-14.2) —, porque a regra protege o lead de receber texto nosso sem saber de quem é, e a trilha que produziu o texto não muda isso. Ver as D1 e D2 do desenho.

## Lacunas declaradas

- **A fronteira é uma janela de silêncio, não um objeto.** Nada no sistema registra "esta conversa começou aqui"; a resposta é recalculada a cada turno a partir do timeline. Duas consequências: um teste que congele o relógio muda a resposta, e a TEC-130 vai ter de decidir o que fazer com as conversas que esta definição já delimitou retroativamente.
- **O texto não nomeia a imobiliária**, porque não há nome configurável. Um lead atendido por duas imobiliárias diferentes recebe a mesma frase das duas.
- **Nada mede a identificação em produção.** O gate de avaliação ganha, no máximo, os turnos de sondagem da D3 — que são uma medição pontual desta card, não uma métrica permanente. Criar a métrica é card própria, e o `Faixa.SEM_MECANISMO` do gate é onde ela seria declarada.

## O que esta card não faz

- **A execução da transferência para o corretor** — a própria card exclui, e é a TEC-143. Aqui apenas se oferece.
- **Criar a entidade de conversa** — é a TEC-130.
- **Criar métrica permanente de identificação** no gate de avaliação.
- **Introduzir nome configurável da imobiliária** em `app/config.py`.
