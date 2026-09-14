# TEC-149 — Parar de perguntar no oitavo e oferecer o corretor

**Status:** desenhado em 2026-09-14.

**Card:** [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149) — História, Should (MoSCoW), prioridade High. Origem: RF-05, RN-05.5 (SRS v1.0); gatilho de handoff da RN-16.1. Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**A história:** *"Como Marina, que já respondeu muita coisa, quero que em algum momento o atendimento pare de perguntar e me passe para alguém, para não sentir que estou num interrogatório sem fim."*

## Objetivo

A RN-05.5 limita a 8 as perguntas de qualificação, e manda oferecer o corretor quando o limite chega sem os obrigatórios da RN-05.3. Nada no sistema conta pergunta hoje, e nada emite o gatilho `LIMITE_DE_PERGUNTAS`.

## O que a exploração descobriu, e que muda o desenho

**Quase toda a fiação já existe, e foi deixada de propósito.** A docstring de `Gatilho`, em `domain/handoff/vocabulario.py`, diz com todas as letras que o enum *"nasce completo, com fiacao para tres"* e que *"TEC-143, TEC-149 e TEC-170 chegam e so chamam `registrar_handoff` com o gatilho que ja existe"*. `LIMITE_DE_PERGUNTAS`, a etiqueta `qualificacao-parcial` e a prioridade `NORMAL` estão lá desde a TEC-174, sem nenhum emissor.

**O modelo já declara o que perguntou.** `RespostaDoAgente.perguntou`, da TEC-257, é a tupla dos campos sobre os quais aquela resposta pergunta. Não é preciso inferir pergunta de texto livre.

**Já existe o único ponto do turno que sabe que a pergunta foi entregue.** `marcar_perguntados` roda no commit pós-entrega, e o comentário que a chama explica que marcar antes *"gastaria, para sempre e em silencio, a chance de perguntar aquele campo"* num 5xx da Meta. É ali que o contador tem de crescer, e em nenhum lugar antes.

**E a descoberta que muda o desenho: a entidade que o SRS manda contar não existe.** O dicionário de dados põe `perguntas_feitas smallint` na tabela **Conversa**. Não há tabela Conversa. A Emenda E-01 da RN-05.7 (TEC-148) já enfrentou exatamente isto para a recusa de campo e decidiu: *"não há fronteira de conversa no sistema: `conversation_key` é o id externo do lead"*, e introduzir a entidade *"é maior que esta card e fica deferido"*. Esta card herda a decisão em vez de reabri-la.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `Gatilho.LIMITE_DE_PERGUNTAS` | existe desde a TEC-174, **sem emissor** | D5 |
| `RespostaDoAgente.perguntou` | existe desde a TEC-257 | D3 |
| `marcar_perguntados` | roda pós-entrega, `UPDATE` de uma coluna só | D2 |
| tabela `conversa` | **não existe**; o estado por lead é `lead_qualification` | D1 |
| `registrar_handoff` | idempotente por índice parcial, acumula gatilhos | D5 |
| `PerguntaDeDesambiguacao` | **não tem** campo `perguntou` | D6 |
| `TEXTO_NEUTRO_DE_SAIDA` | precedente de **substituição** de texto em lugar, sem kind novo | D4 |
| `KIND_DO_CRITERIO_AMPLIADO` | precedente de mensagem **adicional**; não se aplica aqui | D4 |
| `marcar_perguntados` | tem duas saídas antecipadas que o contador não pode herdar | D2 |

## Decisões

### D1 — O contador mora em `lead_qualification`, e o teto é por lead

Coluna nova `perguntas_feitas smallint NOT NULL DEFAULT 0`, na chave `(channel, conversation_key)` — que é o lead, pela E-01 da RN-05.7. Não em `conversa`, que não existe.

`NOT NULL DEFAULT 0`, e não nulável como as colunas vizinhas: ali `NULL` distingue *"linha anterior à card"* de *"a card rodou e não havia nada"*, e para um contador essa distinção não paga. `0` numa linha antiga não afirma "ninguém perguntou" — afirma "ninguém contava". A consequência é que o lead antigo ganha orçamento cheio, o que erra na direção de **continuar atendendo como hoje** em vez de cortar alguém que nunca foi avisado. É o erro reversível dos dois.

**Consequência declarada:** o teto é permanente. Um lead que gastou oito perguntas em janeiro e volta em março nunca mais é perguntado — cai direto no corretor. É o mesmo preço que a E-01 da RN-05.7 já pagou pela recusa, e pela mesma causa. Ver a emenda abaixo.

### D2 — O incremento é função irmã de `marcar_perguntados`, no mesmo commit e em SQL

O **momento** é o do `marcar_perguntados`: o commit pós-entrega, único ponto do turno que sabe que a pergunta chegou ao lead, e o desenho da TEC-257 gastou um parágrafo explicando por quê.

**Mas não dentro dela.** `marcar_perguntados` tem duas saídas antecipadas — `if not preenchidos: return`, quando o lead não informou nada neste turno, e `if not marcados: return`, quando tudo que se perguntou já estava preenchido. Para a marca, sair cedo é deliberado: o comentário de lá declara que *"marcar de menos e o erro seguro"*. Para o contador, o mesmo atalho inverte o sinal. O turno em que o lead escreve "oi" e o agente pergunta o orçamento não extrai campo nenhum, sairia no primeiro `return`, e a pergunta **feita e entregue** não contaria. Contar de menos dá ao lead mais perguntas do que as oito — o interrogatório que a card existe para cortar.

Então: função nova `contar_perguntas`, no mesmo módulo e chamada no mesmo bloco pós-entrega, logo ao lado. É a mesma razão pela qual `marcar_perguntados` nasceu em vez de reusar `gravar_estado`: funções com guardas diferentes não compartilham corpo só porque compartilham momento.

**E cresce em SQL (`perguntas_feitas = perguntas_feitas + :n`), nunca lendo em Python para regravar.** A docstring daquela função já registra o caso: dois turnos concorrentes da mesma conversa, e um commit pós-entrega tardio que sobrescreve o valor mais novo pelo mais velho *"em silencio"*. Um read-modify-write no contador reabriria exatamente essa corrida, agora numa coluna que ninguém olharia.

### D3 — Conta campo declarado, não turno

O incremento é `len(perguntou)`, restrito aos campos de qualificação conhecidos — a mesma tradução de nome que `_NOME_DA_MARCA` já faz. A card manda contar *"perguntas de qualificação, não mensagens"*, e a Emenda E-01 da RN-05.4 permite duas perguntas por turno desde a TEC-255: contar turnos daria ao lead até dezesseis perguntas sob um teto que diz oito.

**Lacuna conhecida, não bug: `intencao` não é um nome contável.** `perguntas_contaveis` só aceita chaves de `_NOME_DA_MARCA` e nomes de campo de `Extracao`, e `Extracao` não tem campo `intencao` — ela chega por fora, do classificador (ver o comentário de `campos_a_gravar`). Uma pergunta sobre intenção, portanto, nunca consome o teto, embora a RN-05.1/RN-05.3 listem intenção entre os campos de qualificação. Ficará assim até uma card decidir se vale a pena tratar esse nome também.

### D4 — Suprime-se o turno que perguntaria, não a conversa

**Emenda desta seção após a implementação.** A versão original desta seção dizia que a substituição dispara sempre que `perguntas_feitas + len(perguntou) > 8`. O que foi entregue é mais estreito, por duas razões independentes.

Primeiro, `perguntas_feitas` cresce (D2) contando `len(perguntas_contaveis(perguntou))`, não `len(perguntou)` — a mesma tradução de nome que D3 já exige para o incremento tem de valer também para a condição que decide a substituição; usar `len(perguntou)` aqui contradiria D3 sobre a mesma pergunta.

Segundo, a condição que de fato dispara a substituição é `teto_atingido and not desambiguando and not saida_bloqueada`, com duas guardas e uma ordem de precedência depois dela:

- **`not desambiguando`**: a RN-05.5 limita pergunta de qualificação, e no caminho de desambiguação quem sai é a pergunta do desambiguador — `gerada.perguntou` fala da chamada 1, que foi descartada. Sem esta guarda, um lead que bateu o teto nunca mais poderia ser desambiguado.
- **`not saida_bloqueada`**: `TEXTO_NEUTRO_DE_SAIDA` é a resposta declarada da política de moderação de saída, e sobrepor a nossa a ela tornaria impossível saber depois qual das duas agiu. O teto não se perde: nada foi contado nesse turno (a contagem só acontece pós-entrega, e a entrega não aconteceu), e ele dispara normalmente no turno seguinte sem bloqueio.

E mesmo passando as duas guardas, `TEXTO_DO_LIMITE_DE_PERGUNTAS` não é a última palavra sobre `texto`: `TEXTO_DA_BUSCA_INCONCLUSIVA` (citação bloqueada, TEC-161) e `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` (zero pós-relaxamento, TEC-160) reatribuem `texto` depois e vencem — política mais específica ganha, e as duas substituem por constante nossa, então a pergunta que o teto suprimiu não vaza por nenhuma delas.

Quando a condição dispara, a prosa do modelo não é entregue: `texto` passa a ser `TEXTO_DO_LIMITE_DE_PERGUNTAS`, na mesma substituição em lugar que a moderação de saída já faz com `TEXTO_NEUTRO_DE_SAIDA`, e pelo mesmo caminho de entrega.

**Sem kind próprio, e isso é correção de uma versão anterior deste desenho.** `KIND_DO_CRITERIO_AMPLIADO` e `KIND_DO_FILTRO_AJUSTADO` existem porque são mensagens **adicionais**, e `outbound_dispatches` tem `UNIQUE (message_id, kind)` — duas mensagens com o mesmo kind no mesmo `message_id` colidiriam na reserva e uma seria descartada como reprocessamento. Aqui não há segunda mensagem: há uma substituição. Criar kind para ela inventaria uma colisão que não existe. **Consequência declarada:** no log da conversa a mensagem do teto não se distingue de uma resposta normal pelo kind; quem precisa distinguir tem o handoff com gatilho `LIMITE_DE_PERGUNTAS`, que é registro próprio, datado e consultável.

Como `perguntou` é não-vazio neste turno, `apresentando` já é `False` pela regra da TEC-162 — as fichas ficam adiadas sozinhas, sem condição nova.

**Turno com `perguntou` vazio segue normal.** Depois do teto o agente continua respondendo dúvida, montando ficha e mostrando imóvel; ele só nunca mais qualifica. "Não faz mais perguntas" não é "para de conversar", e um lead que pergunta o preço de um imóvel depois do teto merece a resposta.

Determinístico em código, e não instrução no prompt, por três razões. O Gherkin exige *"ele não faz uma nona pergunta"*, e instrução é promessa probabilística. O bloco `system` é cacheado e medido contra um teto fixo — texto novo ali passa pelo ritual do orçamento. E o repo já decidiu isto duas vezes no mesmo sentido: a E-01 da RN-09.3 exige *"mensagem determinística nossa, com kind próprio, nunca prosa do modelo"*, e a E-01 da RN-09.4 (TEC-161) bloqueia a prosa e entrega o texto montado por código.

**Consequência declarada:** com duas perguntas num turno, o teto morde entre 7 e 8, não exatamente em 8. Contador em 7 e o modelo perguntando duas coisas: o turno inteiro é suprimido e a oitava pergunta nunca é feita. A alternativa seria entregar meia pergunta, e a prosa é um texto só.

### D5 — O handoff é uma chamada, no bloco transacional que já existe

`registrar_handoff(..., gatilho=Gatilho.LIMITE_DE_PERGUNTAS)`, no mesmo bloco em que a TEC-174 registra `VENDA_IMOVEL` e `SUPORTE_CONTRATO`, com o log **depois** do commit — o comentário de lá explica que `registrar_handoff` não loga mais, e que quem loga é o turno.

Nada de deduplicação nova: `registrar_handoff` é um statement só, arbitrado pelo índice parcial `uq_handoffs_conversa_pendente`, e acumula o gatilho num handoff já aberto em vez de criar outro **enquanto esse handoff continuar pendente**. O índice é parcial, não total — o mesmo precedente já vale para `VENDA_IMOVEL` — então a garantia é só "não duplica enquanto pendente": assim que um corretor fechar o handoff, o próximo turno em que o teto disparar de novo abre um handoff novo, não reabre o antigo.

**O handoff e o contador ficam em lados opostos da entrega, e é deliberado.** O handoff entra no bloco transacional que roda *antes* da entrega; o contador cresce *depois* dela. Numa falha de entrega, portanto, existe handoff e o contador não subiu — o corretor é avisado de um lead que continuará sendo perguntado no próximo turno. É o erro na direção certa, e o inverso seria o caro: contador gasto numa pergunta que o lead nunca viu. É a mesma assimetria que a TEC-174 aceitou para `VENDA_IMOVEL`, e a mesma que o comentário de `marcar_perguntados` defende para a marca.

### D6 — Desambiguação não conta, e isso é uma garantia estrutural mais uma guarda de código; a versão original desta seção só via a primeira

**Emenda desta seção após a implementação.** A frase original dizia *"o cenário 2 do Gherkin não pede código: pede um teste que trave a garantia estrutural"*. Isso vale só para metade do cenário — a metade da **contagem** — e é falso para a outra metade, a da **substituição de texto**, que precisou de guarda em `turno.py` mais um teste de integração.

**A garantia estrutural cobre só a contagem.** `PerguntaDeDesambiguacao` não tem campo `perguntou` — aquela chamada não classifica nem declara pergunta —, e `marcar_perguntados`/`contar_perguntas` só recebem `gerada.perguntou`, nunca o retorno do desambiguador. Por isso o contador nunca sobe no caminho de desambiguação, sem precisar de `if` nenhum: a estrutura do schema já fecha o caso. `tests/unit/test_desambiguacao_nao_conta_no_teto.py` trava essa garantia, para que reintroduzir `perguntou` naquele schema um dia não a desfaça em silêncio.

**A substituição de texto exigiu código, porque `gerada.perguntou` da chamada 1 descartada ainda influencia `teto_atingido`.** `teto_atingido` (D2) é calculado a partir de `gerada.perguntou` **antes** de o turno saber se vai desambiguar — e no caminho de desambiguação, `gerada` é a resposta da chamada 1, que é descartada e substituída pela chamada a `classificador.desambiguar`. Um lead que já bateu o teto e manda uma mensagem vaga o suficiente para desambiguar teria `teto_atingido = True` vindo de uma chamada descartada, e sem guarda `TEXTO_DO_LIMITE_DE_PERGUNTAS` pisaria na pergunta do desambiguador — o lead nunca mais seria desambiguado depois do teto. A guarda `not desambiguando` na condição de substituição (D4) existe exatamente para isso, e `tests/integration/test_turno_teto_de_perguntas.py::test_turno_de_desambiguacao_no_teto_entrega_a_pergunta_do_desambiguador` é o teste que a trava — ele não podia viver em `tests/unit/` porque precisa do turno inteiro em volta para exercitar a precedência entre as duas trilhas de texto.

## Emendas ao SRS

**Emenda E-01 à RN-05.5 (TEC-149, 14/09/2026).** A regra fala em *"8 perguntas de qualificação em uma conversa"*, e o dicionário de dados põe o contador em `conversa.perguntas_feitas`. Não há entidade de conversa: a Emenda E-01 da RN-05.7 já estabeleceu que `conversation_key` é o id externo do lead e deferiu a criação da entidade. O contador vive em `lead_qualification`, na mesma chave, e o teto passa a valer **por lead, sem fronteira de conversa e sem expirar**. **Consequência declarada:** um lead que esgotou as oito perguntas nunca mais é qualificado pelo agente, mesmo voltando meses depois com outra intenção — ele é oferecido ao corretor. Erra na direção de não incomodar, como a E-01 da RN-05.7. Fica também declarado que a contagem é por **campo perguntado**, e não por turno, porque a E-01 da RN-05.4 permite duas perguntas por turno desde a TEC-255; e que o teto morde entre a sétima e a oitava pergunta quando o último turno pergunta dois campos, porque a prosa é entregue inteira ou não é entregue.

## Os cenários do Gherkin

| Cenário | Onde é exercitado | Nota |
|---|---|---|
| Oferecer o corretor ao atingir o limite sem os obrigatórios | integração, turno completo | Assere texto determinístico **e** handoff criado |
| Pergunta de desambiguação não conta no teto | unitário | Trava a garantia de D6 |
| Lead qualificado antes do teto segue o fluxo normal | integração | O teto não dispara com 4 perguntas |
| Contador sobrevive à retomada da conversa | integração | É o que D1 e D2 compram: a coluna, não a memória do turno |

Mais dois que o Gherkin não pede e o desenho exige: um proxy estrutural de que a coluna nova tem `DEFAULT 0` — não, como esta seção dizia antes, um teste que releia uma linha gravada antes da migration e a veja voltar como 0, cenário que os testes desta card não constroem — e a concorrência de dois turnos incrementando (D2).

## Lacunas declaradas

### L1 — Nada avisa o corretor

O handoff é criado, e criar handoff não notifica ninguém: as cards de notificação por e-mail e WhatsApp (TEC-280 e TEC-281) estão abertas no épico TEC-173. O texto entregue ao lead não pode prometer que alguém já foi avisado — é a mesma armadilha que a TEC-174 teve de corrigir depois de escrever *"já avisei um corretor"*.

### L2 — O teto não tem como ser reaberto

Não há caminho — nem rota, nem painel — para zerar `perguntas_feitas` de um lead. Se a consequência permanente da D1 se mostrar errada em produção, o conserto é card nova. A coluna existir já é metade do caminho.

### L3 — O contador não distingue pergunta útil de pergunta repetida

Se o modelo perguntar duas vezes o mesmo campo em turnos diferentes, o contador cresce duas vezes. `perguntados_sem_resposta` existe justamente para o prompt não repetir, mas ele não é garantia, e o teto pune o lead por um defeito nosso.

### L4 — `contar_perguntas` não conta enquanto o lead não tem linha

O `UPDATE` de `contar_perguntas` é no-op quando `lead_qualification` ainda não tem linha para o par `(channel, conversation_key)`. O único gravador dessa linha é o upsert dentro de `gravar_estado`, e ele recusa de propósito criar linha — "Deliberadamente NÃO cria linha" — quando `campos_a_gravar` devolve vazio, o que vale sempre para `FORA_DE_ESCOPO` e para `INDEFINIDA` sem extração nenhuma. No primeiro turno em que o lead só diz "oi", nada é extraído, o agente pode perguntar mesmo assim, e essa pergunta feita e entregue não é contada.

Criar a linha dentro de `contar_perguntas` foi cogitado e rejeitado: geraria um efeito colateral maior que a subcontagem, porque uma linha nova move o score do lead de 0 para o piso documentado e grava uma entrada na trilha de score — consequência que esta card nunca decidiu, por causa de um lead que não disse nada. A subcontagem fica documentada e contida: assim que qualquer linha existir para o lead, toda pergunta seguinte é contada normalmente.

## Fora de escopo

O conteúdo do resumo entregue ao corretor (épico TEC-173). A trilha de investidor (TEC-153) e os indicadores de rentabilidade (TEC-154), que são as outras duas cards abertas do épico. A criação da entidade de conversa, deferida pela E-01 da RN-05.7.
