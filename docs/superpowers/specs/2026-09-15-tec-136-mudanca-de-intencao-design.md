# TEC-136 — Tratar mudança de intenção preservando os campos válidos

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-136](https://eduardodurieuxlopes.atlassian.net/browse/TEC-136) — Should (MoSCoW), épico TEC-133 (Roteamento por intenção e humanização)
**Branch:** `feat/tec-136-mudanca-de-intencao`
**Origem:** RF-03, RN-03.3 (SRS v1.0)
**Dependências:** TEC-134 (feita) classifica; TEC-145 (feita) escreve o estado; TEC-152 (feita) trouxe a trilha de score.

## Objetivo

Marina começou procurando aluguel, disse "zona sul, 2 quartos, até 2.500" e no meio da conversa percebeu que dá para comprar. Hoje ela troca de intenção e **o orçamento de aluguel continua lá**, virando filtro de uma busca de compra: `campos_a_gravar` nunca apaga, e turno nenhum revalida o que já está gravado.

A card quer que os campos ainda válidos sobrevivam, que os que perderam sentido sejam descartados **explicitamente**, e que a mudança fique registrada.

## O defeito já está escrito no código, por outra porta

`domain/agente/dinheiro.py`, no comentário de `piso_do_numero_nu`, descreve exatamente este modo de falha — só que para a transição INDEFINIDA→COMPRA, que o Gherkin da card não menciona:

> *"`campos_a_gravar` nunca APAGA e turno nenhum revalida o que ja esta gravado, entao o valor admitido enquanto a intencao era INDEFINIDA sobrevive para dentro de uma conversa depois classificada COMPRA e vira o filtro da busca la."*

São duas portas para o mesmo defeito. Esta card fecha as duas — ver a D1.

## O que existe hoje, e o que não existe

| peça | estado |
| --- | --- |
| Classificação por turno (`conversation_intent`) | **existe**, sobrescrita a cada turno, sem histórico |
| Intenção acumulada (`lead_qualification.intencao`) | **existe** |
| Recálculo de score a cada turno (`registrar_recalculo`) | **existe**, roda incondicionalmente |
| Trilha append-only de score (`lead_score_audit`) | **existe** |
| Detecção genérica de "a intenção mudou" | **não existe** — só `virou_investidor`, gatilho de uma vez só para INVESTIMENTO |
| Qualquer caminho que apague um campo de qualificação | **não existe** |
| Histórico de mudança de intenção | **não existe** |

A invariante **"`None` no campo não apaga"** está escrita em três docstrings de `domain/context/repositorio.py` e fixada por `test_null_nao_apaga`. Esta card precisa abrir uma exceção a ela para um campo — por um caminho novo e distinto, **sem afrouxar a garantia atual**.

## Decisões

### D1 — Descarta quem troca de banda de valor, e isso é mais amplo que o Gherkin

O Gherkin da card só fala de ALUGUEL→COMPRA. A regra implementada é mais ampla: **descarta o orçamento acumulado sempre que a intenção nova pertence a uma banda de valor diferente da anterior.**

As bandas já existem, em `dinheiro.py`, e hoje servem só para validar a extração:

```python
_BANDA_DE_COMPRA = (3_000_000, 100_000_000_000)
_BANDA_DE_ALUGUEL = (30_000, 20_000_000)
_BANDAS = {COMPRA: _BANDA_DE_COMPRA, INVESTIMENTO: _BANDA_DE_COMPRA,
           VENDER_IMOVEL: _BANDA_DE_COMPRA, ALUGUEL: _BANDA_DE_ALUGUEL}
```

Consequências, e as duas últimas é que justificam a amplitude:

- ALUGUEL↔COMPRA descarta. É o cenário da card.
- COMPRA↔INVESTIMENTO **não** descarta: mesma banda, o número continua significando a mesma coisa.
- Intenção acumulada **nula** (o lead falou um número enquanto a conversa ainda era INDEFINIDA) descarta. É a porta que a `dinheiro.py` documenta, e ela fecha de graça pela mesma regra.

**A alternativa recusada foi revalidar em vez de descartar** — perguntar "o valor guardado ainda cabe na banda nova?" e só apagar se não couber. Ela preservaria um "600 mil" dito sob INDEFINIDA, o que é melhor. Mas as duas bandas se sobrepõem entre R$ 30 mil e R$ 200 mil, e nessa faixa ela faz exatamente o que a regra de negócio da card proíbe por escrito: um aluguel de R$ 50 mil/mês sobreviveria como orçamento de compra de R$ 50 mil. Perguntar de novo custa uma pergunta; buscar errado custa a conversa.

### D2 — Só o orçamento é descartado

`forma_pagamento`, `tem_imovel_para_vender` e os seis campos do bloco de investidor **sobrevivem** à troca, ainda que percam sentido. A card só nomeia a faixa, e ampliar teria um custo desproporcional: descartar o bloco de investidor exigiria rearmar `virou_investidor` (em `turno.py`), que é gatilho de uma vez só — um lead que saísse e voltasse a INVESTIMENTO ficaria sem perfil e sem quem o reconstruísse. Isso é a TEC-153, não esta card.

Ver as lacunas declaradas: os campos que sobrevivem inflam a completude de quem mudou de rumo.

### D3 — O descarte mora no `ON CONFLICT DO UPDATE` que já existe

O `SET` de hoje é `{chave: excluded[chave] for chave in (*campos, "updated_at")}`. **É assim que o "None não apaga" funciona:** `campos_a_gravar` só devolve as chaves que têm valor, e a coluna que o turno não extraiu simplesmente não entra no `SET`, então a linha antiga sobrevive intocada.

Isso simplifica o desenho. Quando o turno **extraiu** orçamento novo (*"na verdade quero comprar, até 800 mil"*), a coluna já está no `SET` com o valor novo e o comportamento atual já é o certo — nada a fazer. O `CASE` só é necessário para a coluna que o turno **não** extraiu:

```
faixa_preco_<x>_centavos = CASE
  WHEN lead_qualification.intencao IS NULL
    OR lead_qualification.intencao <> ALL(:mesma_banda)
  THEN NULL
  ELSE lead_qualification.faixa_preco_<x>_centavos
END
```

Injetado só quando a intenção nova é conhecida — isto é, quando `"intencao" in campos`, que é a mesma condição sob a qual `campos_a_gravar` grava a intenção (INDEFINIDA nunca sobrescreve a intenção gravada, e por isso nunca dispara descarte).

`:mesma_banda` é o conjunto de intenções que compartilham a banda da intenção nova, calculado em Python a partir de `_BANDAS`. **A regra continua morando na `dinheiro.py`**; o SQL só faz teste de pertinência. Uma tabela de bandas transcrita para dentro do SQL seria a segunda fonte de verdade que o repo já evitou noutros lugares.

`intencao IS NULL` cai no ramo do descarte de propósito: se há faixa gravada e intenção nula, a faixa foi admitida sob a banda frouxa.

### D4 — A marca de "já perguntei" sai junto com o campo

Descartar a faixa sem tirar a marca quebraria o cenário 2 do próprio Gherkin (*"E o agente pergunta o orçamento de compra"*): `perguntados_sem_resposta` ainda diria o orçamento perguntado, e o agente não reperguntaria.

A remoção usa `_sem_os_respondidos`, o helper que `campos_recusados` já usa, com `_MARCA_DO_ORCAMENTO` — a constante cujo comentário termina em "Nao apague". **Nenhum literal novo**: o nome da marca tem três grafias diferentes no repo (o modelo diz `faixa_preco_expressao`, o banco guarda `faixa_preco_min_centavos`, o prompt exibe `faixa_preco_max`) e escrever qualquer uma delas à mão aqui reintroduziria a divergência que aquela constante existe para fechar.

A remoção entra **depois** da união que já acontece no mesmo `SET`, não antes.

### D5 — Histórico em tabela própria

`conversation_intent_audit`, migration `0035`, encadeando da `0034`. Append-only, uma linha por mudança da intenção **acumulada**, com origem, destino, se a faixa foi descartada, e carimbo por `clock_timestamp()` — pela mesma razão que o comentário de `lead_score_audit` registra para si.

As duas alternativas foram recusadas por motivo escrito:

- **`conversation_intent` não serve.** É upsert-in-place de propósito — a saída crua do classificador a cada turno. Virar histórico ali escreveria uma linha por turno da conversa inteira, para responder uma pergunta que muda meia dúzia de vezes.
- **`lead_score_audit` não serve.** Só grava quando o resultado **muda** (a tupla vazia de `causas_do_recalculo` é o sinal de "não grave"). Uma troca de intenção que não mexesse em nenhum dos cinco fatores sumiria, e o Gherkin pede que a mudança fique registrada.

A tabela grava **toda** mudança da intenção acumulada; o descarte só acontece nas que trocam de banda. São perguntas diferentes, e cada coluna responde a sua.

### D6 — A escrita toma o lock antes do upsert

`SELECT ... FOR UPDATE` na linha de `lead_qualification` antes do upsert, na mesma transação.

Não é cinto-e-suspensório. Sem o lock, dois turnos concorrentes da mesma conversa leem a mesma intenção anterior e **ambos** gravam linha de histórico para a mesma transição — a corrida que `registrar_recalculo` já fechou com o mesmo cadeado, e cujo comentário diz *"dois recalculos concorrentes leem o mesmo ultimo registro, ambos veem mudanca e ambos gravam -- dois registros com o mesmo `total_anterior`"*.

**O lock já é tomado nessa mesma transação**, mais adiante, pelo próprio `registrar_recalculo`. Antecipá-lo preserva a ordem de aquisição e não cria risco novo de deadlock.

O descarte em si **não** depende do lock — ele é atômico dentro do `ON CONFLICT`, que é o idioma que este arquivo já usa duas vezes, para a união de `perguntados_sem_resposta` e a de `campos_recusados`, com o comentário *"dois turnos concorrentes da mesma conversa leem o mesmo valor, cada um une o seu, e o mais lento sobrescreve a marca do mais rapido -- perda silenciosa"*. O lock existe pelo histórico, que precisa do valor **anterior**.

### D7 — O recálculo já dispara; falta vocabulário

O terceiro cenário do Gherkin (*"Então a qualificação é reavaliada / E um novo registro de score é gravado com o motivo da mudança"*) está metade pronto: `registrar_recalculo` roda incondicionalmente a cada turno e já grava quando algo se move.

O que falta é o **motivo**. `auditoria.py` tem cinco causas derivadas de diff de fator e duas sem produtor; nenhuma diz "a intenção mudou". Entra `CAUSA_MUDANCA_DE_INTENCAO`, e ela é da mesma natureza das duas sem produtor de hoje: um fato sobre a **origem** do gatilho, não sobre o que se moveu — então é informada pelo chamador, e não derivada de `causas_do_recalculo`.

Isso tem uma consequência que o comentário da tupla vazia torna explícita: hoje **"nenhuma causa" significa "não grave"**. Uma troca de intenção que não mova nenhum fator precisa gravar mesmo assim, porque a card pede o registro do motivo. A causa informada pelo chamador tem de contar como causa para efeito de gravar.

## Lacunas declaradas

**Campos que perdem sentido e sobrevivem.** `forma_pagamento` e `tem_imovel_para_vender` continuam preenchidos depois de uma troca para ALUGUEL, e os dois entram no score — o fator `capacidade` lê forma de pagamento. Um lead que mudou de rumo tem a completude inflada por respostas de uma qualificação que não é mais a dele. Consequência aceita da D2.

**O bloco de investidor sobrevive inteiro.** Quem sai de INVESTIMENTO mantém ticket, retorno esperado, horizonte, tolerância a reforma e perfil. Mesma razão, e com o agravante de que rearmar `virou_investidor` é trabalho da TEC-153.

**O teto de perguntas não devolve nada.** `perguntas_feitas` continua monotônico: reperguntar o orçamento depois da troca custa uma pergunta das oito. Um lead que troque de intenção lá pelo sexto turno pode bater o teto e ouvir "Já perguntei bastante" sem nunca ter completado uma qualificação inteira. Decisão de produto tomada nesta card, e o contorno — descontar do contador — foi recusado por quebrar a monotonia da coluna.

**O descarte vale para o estado acumulado, não para o passado.** Buscas de turnos anteriores que já filtraram pelo número velho não são refeitas, e as fichas que o lead já recebeu continuam entregues. O descarte muda o que acontece **daqui para frente**.

**A intenção oscilante grava uma linha por oscilação.** Um lead que vai e volta entre ALUGUEL e COMPRA gera uma linha de histórico por troca e perde o orçamento em cada uma. É o comportamento correto — cada troca de banda de fato invalida o número —, mas vale saber que a tabela não deduplica.

## Testes

**Unitário**, sobre a decisão pura de qual conjunto de intenções compartilha a banda: as quatro intenções com banda conhecida, a ausência de banda para as três restantes, e que COMPRA e INVESTIMENTO caem no mesmo conjunto.

**Integração**, no padrão de `tests/integration/test_repositorio_contexto.py`:

- ALUGUEL com faixa e região gravadas → COMPRA sem número novo: faixa vira `NULL`, região e quartos sobrevivem, marca do orçamento sai do array.
- ALUGUEL → COMPRA **com** número novo no mesmo turno: a faixa nova é gravada, e não descartada.
- COMPRA → INVESTIMENTO: a faixa **sobrevive**. É a contraprova sem a qual um descarte incondicional passaria.
- Intenção acumulada nula com faixa gravada → COMPRA: descarta. É a porta da `dinheiro.py`.
- Turno INDEFINIDA sobre uma conversa já classificada: **não** descarta, porque a intenção gravada não muda.
- Uma linha de `conversation_intent_audit` por troca, com origem e destino certos, e nenhuma linha quando a intenção não muda.
- `test_null_nao_apaga` continua passando: o descarte é caminho distinto, não afrouxamento da garantia.

**A cobrir explicitamente:** que a marca removida permite reperguntar. O teste tem de afirmar o efeito (o orçamento volta a ser perguntável), e não só o conteúdo do array — é o que liga a D4 ao cenário 2 do Gherkin.

## Fora de escopo

- O cálculo do score em si (E3) — aqui só se dispara o recálculo e se nomeia a causa.
- Descartar o bloco de investidor e rearmar `virou_investidor` (TEC-153).
- Descartar `forma_pagamento` e `tem_imovel_para_vender`.
- Devolver perguntas ao teto da RN-05.5.
- Refazer buscas anteriores à troca.
