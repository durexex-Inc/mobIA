# TEC-257 — Como o agente lembra do que já perguntou e não foi respondido

**Status:** aprovado em 2026-08-31. Não implementado.

**Card:** [TEC-257](https://eduardodurieuxlopes.atlassian.net/browse/TEC-257) — origem: a medição da [TEC-256](https://eduardodurieuxlopes.atlassian.net/browse/TEC-256), na quarta execução paga de 31/08/2026.

## Objetivo

A TEC-256 mediu sobre os 147 turnos: **18 conversas de 42 — 43% — têm ao menos um campo perguntado mais de uma vez sem o lead ter respondido**, e em **14 delas** o campo foi perguntado em **três turnos**. Não é raro, é sistemático.

**A causa é lacuna de memória, e o agente está agindo certo com o que tem.** A cada turno ele recebe `_texto_do_estado` com o que já se sabe, e o prompt manda *"não repergunte o que já está preenchido"*. Ele sabe o que foi **respondido**; não sabe o que já foi **perguntado sem retorno**. Olha o estado, vê `regiao` vazia, e conclui corretamente que precisa perguntar.

Esta card fecha essa lacuna.

## As decisões de produto

Registradas porque cada uma fechou um leque, e quem ler o código depois vai encontrar o resultado sem o leque.

### D0 — O comportamento é "não repergunta", não "repergunta com cadência"

O leque era: não reperguntar nunca (A), reperguntar com cadência mínima (B), reformulação obrigatória (C), ou rebaixar prioridade (D). A recomendação escrita era **B**, porque é o que os dados descrevem — 14 conversas com o campo em três turnos **seguidos**, não campos perguntados duas vezes com distância. A decisão foi **A**.

A consequência boa é que a marca só precisa carregar presença: nem contagem, nem índice de turno, nem distância. O estado fica menor e a regra do prompt fica mais curta.

### D1 — A marca é permanente

Perguntou, o lead ignorou, o campo sai da fila pela vida da conversa. Não expira por distância — isso seria B com outro nome.

A expiração "quando o lead responde" não é opção separada: se o lead responde, o campo entra no estado e a leitura mostra o valor. É consequência do desenho, não escolha.

### D2 — O modelo declara o que perguntou, na forma de lista de strings filtrada

O leque da card era: proxy de palavra-chave (1), o modelo declara (2), ou contar turnos com o campo vazio (3). A decisão foi **2**, na forma **2a** — lista de strings livre, filtrada contra os nomes de campo conhecidos — e não **2b**, a lista de enums que a card preferia.

**O caminho até aqui fica registrado, porque ele passou por uma escolha errada.** A decisão inicial foi a opção 1 com uma guarda: apertar `campos_perguntados` para só contar o segmento que termina em `?`, o que matava os dois falsos positivos perigosos (o agente descrevendo um imóvel e terminando com *"quer ver?"* marcava `quartos`, `tipo_imovel` e `vagas`). Ela foi revista quando a card apareceu com o custo da opção 2 **medido** — +18,5 tokens para a forma livre, contra a estimativa de "mais de cem" que eu tinha usado para descartá-la.

**Por que 2a e não 2b.** A card prefere 2b porque o enum impede o modelo inventar nome de campo. Mas o que acontece quando ele inventa é que o nome não casa com nenhum dos conhecidos, é descartado, e o campo **não é marcado** — o agente pergunta de novo. Isso é marcar de menos, que é o erro seguro; marcar de mais é o que mata campo em silêncio (D1 é permanente). Um `log.warning` no nome que não casou torna a deriva observável, que é exatamente o buraco que a card acusa na opção 1 — *"o erro fica invisível"*. 2b custa três vezes mais para comprar proteção contra a falha benigna, e não protege melhor contra a maligna.

**O que a escolha 2 desmontou do desenho anterior, e é o argumento mais forte a favor dela:** o proxy **para de sustentar produção**. Fica puramente diagnóstico e intocado. Com isso:

- as 18 conversas continuam sendo linha de base válida, e o critério de aceitação da card sobre `insistencias` sobrevive;
- o aperto de `campos_perguntados` sai de escopo;
- mover a detecção de `mobia.evals` para o domínio fica desnecessário — produção não a importa;
- a ideia de manter duas rigorosidades sobre a mesma tabela some.

A opção que parecia a mais cara é a que remove três decisões.

### D3 — A marca é persistida, não derivada da janela

A alternativa sem migração: rodar a detecção sobre as respostas anteriores do agente que já estão em `contexto.literais`. Custo de trabalho muito menor, e a marca some quando a janela dobra no resumo.

Recusada, e o argumento tentador a favor dela é o que a condena: a evaporação *suavizaria* a permanência de D1, mas **a suavização não seria uma decisão** — a marca valeria o que o resumo deixasse, mudaria sozinha quando alguém mexesse em `contexto_literais_minimas`, e ninguém teria escolhido "a marca vale doze turnos". Se D1 doer, a resposta é medir e escolher uma expiração, não herdar uma do tamanho da janela.

## O que já existe

Levantado na `main` mergeada (`e4ce03e`), não presumido.

- `campos_a_gravar` (`src/mobia/domain/context/repositorio.py`) é o precedente de forma: uma regra de acumulação, uma casa, produção e eval chamando a mesma função. Foi escrita porque o eval tinha uma cópia divergente.
- `_texto_do_estado` (`src/mobia/domain/context/montagem.py`) emite `campo: valor` e pula os `None`. É usada pela estimativa de tokens **e** por `montar_prompt`.
- `SISTEMA_DO_AGENTE` já diz *"não repergunte o que já está preenchido"*. Cobre "não pergunte o que você já sabe"; nada cobre "não repita o que o lead ignorou".
- `desambiguado_em` em `conversation_intent` é o precedente de comportamento: uma marca que diz *"já perguntamos isso neste episódio, não pergunte de novo"*. Falta o equivalente por campo.
- `campos_perguntados` e `insistencias` (`src/mobia/evals/metricas.py`) são diagnóstico e **não bloqueiam**. Conferido em `relatorio.py`, não suposto. Esta card não os toca.

## Decisões de implementação

### D4 — O orçamento: as duas subidas, com o preço por turno

Estado de hoje, medido por `python -m pytest -q -k margem_do_orcamento -s`:

```
-montagem.SISTEMA (contado, nao enviado)             -42,0
+classificador.SISTEMA_DO_AGENTE (campo system=)     289,5
+schema compilado (output_config.format)             356,0
+rotulos de montar_prompt                             19,2
= liquido                                            622,8
teto fixo                                            627,0
margem                                                 4,2
```

Esta card gasta em dois lugares: **+18,5** no schema (o campo novo) e **+0,75** no prompt (a cláusula reescrita de D6). Subcontagem projetada: **642,05**.

| | hoje | depois | folga resultante |
| --- | --- | --- | --- |
| teto fixo do `test_a_margem_do_orcamento_do_prompt_e_deliberada` | 627 | **655** | 12,95 |
| `contexto_headroom_de_tokens` | 850 | **880** | 17,95 sobre `headroom × 0,75` |

**Preço da subida do headroom: 30 tokens a menos de literais e resumo por turno, de um teto de 12000 — 0,25% do contexto.** Vai escrito no comentário de `contexto_headroom_de_tokens`, ao lado das duas subidas anteriores, como a card exige. Para comparação, registrada lá: a TEC-145 pagou 3,3% por extração estruturada, a TEC-250 pagou 0,4% por três regras de prompt.

**Nenhum dos dois números é o mínimo que passa**, e isso é a lição escrita na TEC-145: o mínimo passava por meio token e por isso não foi adotado — o fator 0,75 existe para haver folga, e empatar com o teto o derrota. Escolher o mínimo é escolher que a próxima card estoure.

### D5 — O campo no schema, e como o modelo sabe o que pôr nele

`SCHEMA_DA_RESPOSTA` ganha `perguntou: {"type": "array", "items": {"type": "string"}}`. Sem `description` — nenhum campo do schema tem, e uma aqui custaria mais que o campo inteiro.

**O modelo infere o vocabulário do próprio schema:** `extracao`, no mesmo objeto, tem exatamente os nove nomes (`faixa_preco_min`, `faixa_preco_max`, `regiao`, `tipo_imovel`, `quartos`, `vagas`, `urgencia`, `forma_pagamento`, `tem_imovel_para_vender`). É inferência razoável, e **não é garantia** — ver as lacunas.

O que chega é filtrado contra `fields(Extracao)`, e não contra uma lista escrita à mão. É a mesma fonte que o schema deriva, então a próxima card que acrescentar campo não precisa lembrar deste lugar — e o teste que já existe sobre `fields(Extracao)` quebra se alguém tentar. Nome que não casa é descartado e **logado** (`log.warning`, sem o texto da resposta — é fala do agente sobre a fala do lead, e a regra de PII vale). O descarte marca de menos, que é a direção segura de D1.

### D6 — A regra do prompt é reescrita, não acrescentada

```
- nao repergunte o que ja esta preenchido
+ nao repergunte o preenchido nem o ignorado
```

Custo medido pelo proxy `len/4`:

| texto | delta |
| --- | --- |
| `...o que ja esta preenchido nem o que o lead ignorou` | +6,25 |
| `...o preenchido nem o que o lead ignorou` | +3,25 |
| `...o preenchido nem o ignorado` | **+0,75** |

Encurtar a cláusula existente paga quase toda a cláusula nova. A forma escolhida é a de +0,75; a de +3,25 é mais explícita e custa 2,5 tokens a mais do orçamento que a subida do teto acabou de comprar.

**Declarar não é o mesmo que obedecer.** O campo `perguntou` faz o sistema saber; esta cláusula é o que faz o agente parar. As duas são necessárias.

### D7 — A coluna

`lead_qualification.perguntados_sem_resposta`, `ARRAY(String(32))`, nullable. Migração `0009`.

**`NULL` e `{}` significam coisas diferentes.** `NULL` é *"linha anterior a esta card, ninguém marcava"*; `{}` é *"marcava, e não havia nada a marcar"*. É a mesma distinção que a TEC-231 fixou nas colunas de cache, e colidir as duas leituras na mesma coluna é o defeito que ela consertou. **A coluna é escrita em toda gravação, mesmo vazia** — sem isso uma linha criada por esta card sem nada a marcar sairia `NULL`, que está reservado.

**Acumulação por união, sem remoção.** Se o lead responde, o campo entra no estado e a leitura passa a mostrar o valor (D9). Remover da coluna exigiria uma segunda regra, que pode divergir da primeira.

**A união mora no SQL, não numa leitura prévia.** No `ON CONFLICT DO UPDATE`:

```
perguntados_sem_resposta =
    coalesce(lead_qualification.perguntados_sem_resposta, '{}') || excluded.perguntados_sem_resposta
```

Ler o valor antigo em Python para unir em memória abriria a janela que a guarda de monotonia de `gravar_resumo` já fechou para o resumo: dois turnos concorrentes da mesma conversa leem o mesmo array, cada um une o seu, e o mais lento sobrescreve a marca do mais rápido. No SQL a união acontece dentro do `UPDATE`, e as duas marcas sobrevivem. Duplicatas são possíveis por esse caminho e não incomodam — a leitura testa pertinência, não conta.

### D8 — A regra compartilhada, e onde ela é chamada

Uma função irmã de `campos_a_gravar`, na mesma casa (`context/repositorio.py`):

```
campos_a_marcar(declarados, preenchidos) -> set[str]
    conhecidos = {nomes de campo de Extracao}
    validos, ignorados = particiona(declarados, conhecidos)
    loga(ignorados)
    return validos - preenchidos
```

`preenchidos` é o estado **depois** da gravação deste turno. A subtração é o que separa esta marca do proxy diagnóstico irmão: campo que já está no estado e foi reperguntado é território de `_reperguntou`, e não entra aqui.

**A gravação acontece em duas fases, e a marca não é uma delas via `gravar_estado`.** Pré-entrega, no primeiro bloco de sessão de `turno.py`, `gravar_estado` grava `intencao` e `extracao` — e só isso; ele já não recebe `perguntou` de `turno.py`. Pós-entrega, só quando o texto entregue foi de fato a resposta do agente (`not desambiguando and not saida_bloqueada`, depois dos retornos antecipados que cobrem fora da janela, recusa e reentrega suprimida), uma função irmã — `marcar_perguntados` — faz um `UPDATE` visado que toca **só** `perguntados_sem_resposta` (mais `updated_at`), com a mesma união `coalesce(coluna, '{}') || ...` em SQL. `gravar_estado` mantém o parâmetro `perguntou`, mas só o espelho do runner do eval e os testes dele exercitam esse caminho agora — produção não passa mais por ali para a marca.

**A assimetria é o ponto, e a primeira versão deste spec a errou.** `turno.py` justifica o commit antecipado dizendo que a extração é *"fato sobre a fala dele, nao sobre a nossa resposta"* — e por isso saída bloqueada e envio fora da janela não a descartam. `perguntou` é o outro tipo de fato: é sobre a **nossa** resposta. Três caminhos depois daquele commit descartam a resposta do modelo — `desambiguando` (a resposta da chamada 1 é descartada, *"paga e nao entregue"*, e o lead recebe outra pergunta), saída bloqueada, e envio fora da janela. Como a união nunca remove, marcar antes deixaria o campo marcado como já perguntado **sem nunca ter sido perguntado, para sempre e em silêncio** — marcar de mais, a direção que D8 chama de insegura, entrando pela porta dos fundos.

**Por que a marca não viaja de volta em `gravar_estado`, e não só num `UPDATE` qualquer.** A tentação óbvia é reusar `gravar_estado` inteiro no commit pós-entrega, passando de novo `intencao=gerada.intencao` e `extracao=gerada.extracao` — parece idempotente, porque regravar os mesmos valores não muda nada, num turno isolado. Contra a concorrência real entre dois turnos da mesma conversa, que é a própria razão pela qual a união da marca foi para o SQL, essa reescrita inverte "mais novo vence" em silêncio: turno A commita `extracao_A` em t1, turno B commita `extracao_B` em t2 > t1, e o commit pós-entrega de A — se regravasse `extracao` — aconteceria em t3 > t2 e sobrescreveria `extracao_B` com `extracao_A`, mais velha. É a mesma perda que a marca foi desenhada para não sofrer, só que nas colunas de valor em vez da coluna da marca. `marcar_perguntados` evita o problema por não ter coluna de valor no `SET`: não há nada ali para inverter.

O precedente já existia na mesma função: `marcar_desambiguacao` só é gravado depois da entrega confirmada, porque *"marca-lo antes queimaria a unica chance de perguntar num 5xx da Meta"*. Esta marca queima exatamente a mesma chance, e obedece à mesma regra.

Se o processo morrer entre a entrega e a marcação, a marca se perde e o agente pode reperguntar — marcar de **menos**, o erro seguro.

**`FORA_DE_ESCOPO` não marca.** `campos_a_gravar` devolve `{}` e `gravar_estado` retorna cedo; a marca segue o mesmo caminho. O buraco é real e declarado: um agente que pergunte "qual região?" num turno classificado `FORA_DE_ESCOPO` não marca, e pode perguntar de novo. Fica assim porque, com D1 permanente, **marcar de menos é o erro mais seguro dos dois**.

### D9 — A leitura: valor vence marca, e o rótulo custa zero

`_texto_do_estado` mantém a ordem fixa de campos que já tem, e para cada um:

- valor não-`None` → `campo: valor` (como hoje)
- valor `None` e campo marcado → `campo: (perguntado, sem resposta)`
- nem um nem outro → a linha não sai

```
Estado de qualificacao:
intencao: COMPRA
quartos: 3
regiao: (perguntado, sem resposta)
```

**A marca nunca aparece ao lado de um valor**, e a ordem não muda. Nenhuma seção nova em `montar_prompt`: o rótulo `Estado de qualificacao:` já existe e é reusado, então a subcontagem fixa não cresce por causa dela. O texto por turno cresce, e esse é contado por `montar_contexto` — o comportamento correto, porque ele é de fato enviado.

### D10 — O espelho no eval, e a armadilha nomeada

O runner monta `LeadQualification(**estado_acumulado)`. Para o eval medir o conserto, `estado_acumulado` precisa carregar a marca, acumulada por `campos_a_marcar` — a mesma função de produção, pelo mesmo motivo que `campos_a_gravar` existe.

**A armadilha:** o runner faz `conhecidos_antes = set(estado_acumulado)`. Com a marca virando mais uma chave do dict, a string `perguntados_sem_resposta` entraria como se fosse um campo conhecido, e contaminaria os dois proxies — `_reperguntou` e o `- conhecidos_antes` de `campos_perguntados`. `conhecidos_antes` tem de excluir a chave da marca explicitamente, e um teste trava isso.

## Testes

- `campos_a_marcar` descarta nome desconhecido, e o descarte é logado.
- `campos_a_marcar` subtrai o que já está preenchido.
- `FORA_DE_ESCOPO` não marca.
- `NULL` e `{}` não colidem: linha antiga continua legível, linha nova sem marca grava `{}`.
- A união preserva a marca de dois turnos concorrentes (o caso que a leitura-em-Python perderia).
- A marca some da leitura quando o campo é preenchido, e a ordem dos campos não muda.
- A marca nunca aparece ao lado de um valor.
- `conhecidos_antes` não contém a chave da marca.
- `test_a_margem_do_orcamento_do_prompt_e_deliberada` passa com o teto em 655, e `test_diferenca_entre_o_contado_e_o_enviado` com o headroom em 880.
- `campos_perguntados` e `insistencias` não mudam de comportamento — esta card não os toca.

## Contrato depois da card

- O modelo declara, por turno, sobre quais campos perguntou.
- Um campo perguntado e não respondido é marcado no estado da conversa, e o prompt o carrega.
- O agente é instruído a não reperguntar campo marcado, pela vida da conversa.
- O instrumento de medição da TEC-256 continua o mesmo, e as 18 conversas continuam sendo linha de base.
- Nenhuma métrica que bloqueia o gate muda de valor por esta card.

## O que esta card não entrega

- **Nenhuma garantia de que o modelo obedece.** A regra é texto no prompt e a marca é dado no prompt. Se o modelo reperguntar assim mesmo, esta card não impede — ela mede na execução seguinte, pelo protocolo da TEC-253: comparar a contagem de insistências, que é categórica, e não percentual que oscila.
- **Nenhum log de "deixei de perguntar".** Um campo que morreu por marca não deixa rastro. O log de D5 cobre o nome que não casou, não o silêncio.

## Lacunas conhecidas

- **O modelo pode não entender o campo `perguntou` sem `description`.** Ele pode devolver o texto das perguntas em vez dos nomes de campo. A falha é benigna e observável: nada casa, nada é marcado, e o log enche de nomes ignorados. **A primeira execução paga revela**, e o eval a exercita antes de produção. Se acontecer, o próximo passo já tem preço: 2b, a lista de enums, +56,0 tokens em vez de +18,5 — teto para 695 e headroom para 950, 0,83% do contexto.
- **A permanência de D1 nunca foi medida.** Ninguém sabe quantos campos ela mata em conversa longa, e não há instrumento para saber. Se doer, a resposta é medir e escolher uma expiração — não herdar uma da janela (D3).
- **`follow-up-06` não é resolvido por esta card.** O pior caso do relatório é `VENDER_IMOVEL` recebendo roteiro de comprador — território da TEC-137. Um caso entre 16, e apontar para cá seria diagnóstico errado.
- **O filtro de PII do log de D5 (`_NOME_PLAUSIVEL`) tem um risco residual aceito, não eliminado.** O regex barra frase — tem espaço, maiúscula, acento, pontuação — mas não barra um token isolado, minúsculo, sem acento e sem dígito. Se o modelo puser um valor do lead nessa forma (um bairro como `"pinheiros"`, uma resposta de uma palavra como `"sim"`) onde deveria pôr um nome de campo, esse valor passa no filtro e vai literal para o log. Não existe filtro estrutural que separe esse caso de um nome de campo inventado como `"bairro"` — os dois são a mesma forma sintática, e distinguir os dois é justamente o que este log existe para mostrar. Trocar o nome por só uma contagem fecharia o buraco e destruiria o diagnóstico que justificou `perguntou` ser lista de string em vez de enum (opção 2b): seria pagar o preço da forma cara sem comprar o benefício dela. A exposição só ocorre quando a declaração do modelo já quebrou — caso em que o log servir de sinal de alarme é o efeito desejado, não um efeito colateral.
- **O modelo pode super-declarar nomes válidos.** A argumentação de segurança da D2 cobre só nomes inventados: eles não casam, são descartados, e marca-se de menos. A falha simétrica é o modelo listar campos que ele **quer** em vez de campos sobre os quais **perguntou**. `perguntou` é obrigatório num schema estrito, não tem `description`, e vem logo depois de `resposta` — um modelo pressionado a preencher um array obrigatório sem semântica declarada é exatamente o cenário de excesso. Um turno assim marca até nove campos, permanentemente e em silêncio. Nenhuma guarda existe, e o limiar que a evitaria seria um número que ninguém mediu — a primeira execução paga mostra se acontece, e é ela que decide.
- **Resposta que os guards de parse rejeitam mata o campo.** O agente pergunta `faixa_preco_max`, o modelo declara, a marca é escrita. O lead responde *"uns 500k"*, `_preco` devolve `None`, o campo não entra no estado, e a marca fica. O prompt passa a dizer para nunca mais perguntar. **O lead respondeu, o sistema não ouviu, e o campo morreu.** Antes desta card o agente perguntaria de novo no turno seguinte e poderia receber uma forma parseável. Vale igual para `_ambientes` recusando *"umas duas ou três"*. É uma instância mais estreita e mais acionável de "a permanência de D1 nunca foi medida".

## Fora de escopo

- Cadência, reformulação e prioridade (opções B, C, D de D0).
- O proxy de palavra-chave: nem promovê-lo a produção, nem apertá-lo. Ele continua diagnóstico e intocado.
- Contar turnos com o campo vazio (opção 3 da card).
- O limiar de perguntas por turno — é a [TEC-255](https://eduardodurieuxlopes.atlassian.net/browse/TEC-255).
- As outras sub-cards da [TEC-140](https://eduardodurieuxlopes.atlassian.net/browse/TEC-140).
