# TEC-137 — Encaminhar venda de imóvel e suporte de contrato direto ao handoff

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-137](https://eduardodurieuxlopes.atlassian.net/browse/TEC-137) — Should (MoSCoW), épico TEC-133 (Roteamento por intenção e humanização)
**Branch:** `feat/tec-137-encaminhar-venda-e-suporte`
**Origem:** RF-03, RN-03.4 (SRS v1.0)
**Dependências:** TEC-134 (feita) e o registro de handoff (E7, oito cards em Feito).

## Objetivo

Um proprietário que escreve "quero colocar meu apartamento à venda" é tratado hoje como comprador: o agente responde com a prosa do modelo, que pode conter pergunta de qualificação de quem quer **comprar**. A card quer que essas conversas saiam do SDR e vão para a fila humana com confirmação ao lead.

## Metade disto já existe

A TEC-174 já criou `_GATILHO_DA_INTENCAO` em `turno.py`, e o comentário dele registra a regra desta card por antecipação:

> RN-03.4: estas duas intencoes nao sao trabalho de SDR, e o comentario de `qualificacao.py` ja dizia que elas vao "direto para handoff" -- um destino que so passou a existir na TEC-174. **O lead segue recebendo a resposta deste turno**: silenciar e a RN-16.4, que e a TEC-179.

| peça | estado |
| --- | --- |
| Handoff criado por `VENDER_IMOVEL` / `SUPORTE_CONTRATO` | **existe** |
| Etiqueta própria por gatilho (`venda-imovel`, `suporte-contrato`) | **existe** em `ETIQUETA_DE` |
| `log.info("handoff.criado")` e `_agendar_resumo` | **existem** |
| Exclusão das duas intenções da qualificação de SDR | **existe** em `qualificacao.py` |
| Confirmação de encaminhamento ao lead | **não existe** — o lead recebe a prosa do modelo |
| Aviso de horário fora da janela | **não existe** |

A card é, portanto, sobre **o que o lead recebe** — não sobre o handoff, que já nasce certo.

## Decisões

### D1 — Texto fixo substitui a prosa do modelo, no sítio que já faz isso

`executar_turno` (`turno.py`) tem o bloco `if teto_da_entrega and not desambiguando and not saida_bloqueada:`, que substitui a prosa do modelo por `TEXTO_DO_LIMITE_DE_PERGUNTAS` quando a pergunta seguinte passaria do teto. É o mecanismo exato de que esta card precisa, e o comentário dele escreve a ordem de precedência por extenso.

A alternativa — instruir o modelo no prompt de sistema — foi recusada por duas razões. A primeira é medida: a margem do orçamento de prompt está em **1,2 tokens** depois da TEC-143, e instrução nova não cabe. A segunda é mais forte: o prompt não garante comportamento. A regra de negócio diz que essas intenções **não passam pela qualificação**, e um texto fixo é o único jeito de saber que nenhuma pergunta escapou.

**Duas constantes, uma por intenção.** "Vou passar para um corretor" serve mal para quem tem dúvida de contrato vigente — essa pessoa já é cliente, não é lead. O Gherkin pede etiquetas distintas porque são filas diferentes; o texto segue a mesma lógica.

### D2 — A substituição vale em todo turno com a intenção, não só no primeiro

`_GATILHO_DA_INTENCAO` já roda em todo turno com a classificação certa, e `registrar_handoff` acumula sem duplicar. O texto segue a mesma regra.

A alternativa — substituir só quando `registrar_handoff` devolve `criado=True` — evitaria repetição, mas devolveria ao modelo a palavra nos turnos seguintes, e com ela a chance de fazer a pergunta de qualificação que a regra de negócio proíbe. **Custo aceito:** um lead que continue escrevendo recebe a mesma frase mais de uma vez.

Silenciar o agente, como a TEC-143 faz, foi recusado: a card diz que o lead *"recebe confirmação"*, não que a conversa morre — e com a TEC-280 e a TEC-281 abertas, silenciar deixaria o lead sem resposta de ninguém.

### D3 — A janela é a da TEC-143, e o Gherkin desta card diverge dela

O aviso usa `dentro_da_janela_de_atendimento` e `Settings.atendimento_horario_inicio/fim`, construídos na TEC-143 hoje. Uma fonte só para "quando há gente atendendo".

**O Gherkin desta card diz `"de segunda a sábado, das 9h às 19h"`, e a janela real é 9h–18h sem dia da semana.** Os números não batem, e isto é divergência declarada, não descuido:

- O texto **formata a partir da configuração**, então diz o que o sistema de fato faz. Citar "19h" num literal enquanto a config diz 18h seria exatamente o tipo de prosa que mente que este repo persegue.
- Acrescentar dia da semana à janela foi recusado: mexeria numa configuração que a TEC-143 acabou de criar, o Gherkin *daquela* card não pedia dias, e a TEC-177 já toca horário por outro caminho (`TEXTO_DA_JANELA_HUMANA`, com as horas do **corretor**). Três fontes de horário é problema para uma card própria, não para esta.

Fica para decisão de produto: se a janela real deve virar segunda-a-sábado 9h–19h, é mudança de configuração e vale uma card.

### D4 — A precedência entre as substituições fica escrita

O bloco de `turno.py` já tem três substituições concorrentes (`teto_da_entrega`, a citação bloqueada da TEC-161, o zero pós-relaxamento da TEC-160) e um comentário que declara a ordem: *"politica mais especifica ganha"*.

Esta entra com precedência **acima** do teto de perguntas: quem vai para a fila de venda não precisa ouvir que "já perguntei bastante". As guardas `not desambiguando` e `not saida_bloqueada` valem igual, pelas razões que aquele comentário já registra — desambiguar continua possível, e `TEXTO_NEUTRO_DE_SAIDA` continua vencendo.

### D5 — Os textos não prometem que alguém foi avisado

O comentário de `TEXTO_DO_LIMITE_DE_PERGUNTAS` e o de `notificacao/envio.py` proíbem a frase, citando o precedente da TEC-174, que escreveu "já avisei um corretor" e teve de reescrever. A TEC-143 a reintroduziu hoje e a revisão final a pegou.

Os dois textos novos falam de **encaminhamento**, nunca de aviso, e ganham comentário com essa razão. A TEC-143 deixou um teste `assert "avisei" not in texto`; o mesmo padrão vale aqui.

## Lacunas declaradas

**Ninguém é notificado.** Vale para esta card como vale para as outras do épico: o handoff entra na fila e os dois canais registram sem entregar (TEC-280, TEC-281).

**O lead que insiste recebe a mesma frase.** Consequência aceita da D2.

**Os números do aviso divergem do Gherkin.** Consequência da D3, e decisão de produto.

**A intenção pode mudar no meio da conversa.** Um lead classificado como `VENDER_IMOVEL` que depois pergunta sobre comprar volta a ser qualificado, porque a substituição segue a classificação de cada turno. É o comportamento certo — a TEC-136 é quem trata mudança de intenção —, mas significa que o encaminhamento não é terminal.

**O zero pós-relaxamento da TEC-160 ainda vence o encaminhamento.** Acrescentada pela revisão final (R5). O bloco `if resposta_do_turno.relaxou_sem_resultado and not citacao_bloqueada:` reatribui `texto` depois da substituição desta card e lê **apenas** aquele booleano — nunca a intenção nem o texto. Um lead de venda cujo turno chamou a busca, relaxou o critério e mesmo assim não achou nada recebe `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` no lugar do encaminhamento. Estimado bem abaixo de 1% dos turnos com essas intenções, mas real e silencioso. **Aceito, não corrigido:** o lead continua recebendo resposta e o handoff continua nascendo certo; o texto é que fala do catálogo em vez da fila.

A irmã dessa substituição — a citação bloqueada da TEC-161 — **não** alcança: ela roda sobre o `texto` já substituído, e `divergencias_de` devolve vazio para os dois literais, com e sem o sufixo de horário. `valores_em` exige marca de dinheiro (`R$`, "reais", palavra de magnitude), então `9h`/`18h` não são preço, e `_CODIGO` quer `[A-Z]{2,3}-\d{3,6}`. Vence por estrutura, é inalcançável na prática — verificado executando `divergencias_de` sobre as quatro combinações.

**A apresentação precisou de exclusão explícita, e a razão vale registro.** Também da revisão final (R6). `apresentando` não reatribui `texto`: ele o **reaproveita** como prefixo de legenda da primeira ficha (D16 da TEC-162). Como toda análise de precedência desta branch olhou para "quem atribui por último", ninguém viu. Com `tool_choice: auto` e `"VENDA"` no enum de `operacao` da ferramenta de busca, um proprietário podia receber até três fichas do catálogo de venda, com o texto de encaminhamento truncado — ou vazio, que é o que `prosa_que_cabe` devolve quando a ficha não deixa espaço. **Corrigido:** `and not encaminhou` entra na expressão. Consequência pretendida: `identificar` (`not apresentando and ...`) passa a valer nesses turnos, e o vendedor de primeiro contato recebe identificação e encaminhamento numa mensagem só.

## Testes

**Integração**, no padrão de `tests/integration/test_pedido_de_humano.py`:

- `VENDER_IMOVEL` entrega o texto de venda e não a prosa do modelo; o handoff existe com etiqueta `venda-imovel`.
- `SUPORTE_CONTRATO` entrega o texto próprio e a etiqueta `suporte-contrato` — os dois textos são distintos.
- Nenhuma pergunta de qualificação sai no texto entregue.
- Fora da janela, o texto nomeia o horário da configuração; dentro, não nomeia.
- O segundo turno com a mesma intenção entrega o texto de novo e não duplica handoff.
- A substituição vence o teto de perguntas quando os dois valeriam.
- `saida_bloqueada` continua vencendo, e desambiguação continua possível.

Acrescentados pela revisão final:

- Um turno de venda **com candidatos** não apresenta ficha nenhuma (R6) — o teste que provou o defeito antes do conserto.
- O **primeiro contato** de venda recebe identificação e encaminhamento como uma mensagem só, com e sem candidatos.

**Unitário:** o sufixo de fora da janela diz "pode demorar até", e não marca hora (R7).

**Unitário:** os dois textos não contêm "avisei", no molde do teste que a TEC-143 deixou.

## Fora de escopo

- Notificação ao corretor e SLA de aceite (E7).
- Mudança de intenção no meio da conversa (TEC-136).
- Alterar a janela de atendimento para bater com o Gherkin (D3).
- Silenciar o agente depois do encaminhamento (D2).
