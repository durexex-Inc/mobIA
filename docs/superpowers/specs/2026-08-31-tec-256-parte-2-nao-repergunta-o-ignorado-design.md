# TEC-256 (parte 2) — Não repergunta o que o lead ignorou

**Status:** aprovado em 2026-08-31. Não implementado.

**Card:** [TEC-256](https://eduardodurieuxlopes.atlassian.net/browse/TEC-256) — a parte 2 da mesma card. A parte 1 mediu; esta trata. Nenhum número de card novo foi inventado: a TEC-256 escreveu as duas saídas possíveis antes de medir, e a medição escolheu uma delas.

## Objetivo

A quarta execução de 31/08 mediu insistência sobre os 147 turnos: **18 conversas de 42 — 43% — têm ao menos um campo perguntado mais de uma vez sem o lead ter respondido**, e em **14 delas** o campo foi perguntado em **três turnos**.

A TEC-256 tinha escrito o critério antes de medir: *"se for raro, é registro e não conserto; se for sistemático, as saídas são regra no prompt (não cabe) ou marcar no estado o que já foi perguntado e não respondido"*.

**43% é sistemático.** Esta card entrega a segunda saída.

## As quatro decisões de produto, tomadas antes do desenho

Registradas porque cada uma fechou um leque, e quem ler o código depois vai encontrar o resultado sem o leque.

### D0 — O comportamento é "não repergunta", não "repergunta com cadência"

O leque era: não reperguntar nunca (A), reperguntar com cadência mínima (B), reformulação obrigatória (C), ou rebaixar prioridade (D). A recomendação escrita era **B**, porque é o que os dados descrevem — 14 conversas com o campo em três turnos **seguidos**, não campos perguntados duas vezes com distância. A decisão foi **A**.

A consequência boa é que a marca só precisa carregar presença: nem contagem, nem índice de turno, nem distância. O estado fica menor e a regra do prompt fica mais curta — e isso importa, porque a margem de prompt é de 4,2 tokens (ver D9).

### D1 — A marca é permanente

Perguntou, o lead ignorou, o campo sai da fila pela vida da conversa. Não expira por distância — isso seria B com outro nome.

A expiração "quando o lead responde" não é uma opção separada: se o lead responde, o campo entra no estado e a leitura mostra o valor. É consequência do desenho, não escolha.

### D2 — A detecção continua sendo o proxy de palavra-chave, apertado antes de ser promovido

O leque era: usar o proxy como está (1), fazer o modelo declarar o que perguntou num campo novo do schema (2), ou apertar o proxy antes de promovê-lo (3). A recomendação escrita era **2**. A decisão foi **3**.

O motivo de a recomendação ter sido 2 fica registrado, porque ele não desaparece com a escolha: **D1 é uma decisão permanente e silenciosa, e o projeto já chama `campos_perguntados` de "pista, não prova"**. A opção 2 dava detecção exata, e o preço era subir o teto de orçamento do prompt de forma substancial — o schema compilado já custa 356 dos 622,8 tokens, e um array com enum dos oito campos custa mais de cem sobre uma margem de 4,2.

A escolha 3 compra a maior parte da segurança sem gastar orçamento. O que ela não compra está em "Lacunas conhecidas".

### D3 — A marca é persistida, não derivada da janela

A alternativa sem migração: rodar a detecção sobre as respostas anteriores do agente que já estão em `contexto.literais`. Custo de trabalho muito menor, e a marca some quando a janela dobra no resumo.

Recusada, e o argumento tentador a favor dela é o que a condena: essa evaporação *suavizaria* a permanência de D1, mas **a suavização não seria uma decisão** — a marca valeria o que o resumo deixasse, mudaria sozinha quando alguém mexesse em `contexto_literais_minimas`, e ninguém teria escolhido "a marca vale doze turnos". Se D1 doer, a resposta é medir e escolher uma expiração, não herdar uma do tamanho da janela.

## O que já existe

Levantado na `main` mergeada (`e4ce03e`), não presumido.

- `campos_perguntados` e `MARCADORES_DE_REPERGUNTA` moram em `src/mobia/evals/metricas.py` desde a parte 1, com `_reperguntou` (runner do eval) e `insistencias` delegando para a mesma tabela. Um teste amarra os dois.
- `campos_a_gravar` (`src/mobia/domain/context/repositorio.py`) é o precedente de forma: uma regra de acumulação, uma casa, produção e eval chamando a mesma função. Foi escrita porque o eval tinha uma cópia divergente.
- `_texto_do_estado` (`src/mobia/domain/context/montagem.py`) emite `campo: valor` e pula os `None`. É usada pela estimativa de tokens **e** por `montar_prompt`.
- `SISTEMA_DO_AGENTE` já diz *"não repergunte o que já está preenchido"*. Cobre "não pergunte o que você já sabe"; nada cobre "não repita o que o lead ignorou".
- **Nenhum dos dois proxies bloqueia.** Quem bloqueia é acurácia efetiva, precisão da extração e aderência ao tom. Conferido em `relatorio.py`, não suposto.

### A margem do orçamento, medida e não transcrita

```
-montagem.SISTEMA (contado, nao enviado)             -42,0
+classificador.SISTEMA_DO_AGENTE (campo system=)     289,5
+schema compilado (output_config.format)             356,0
+rotulos de montar_prompt                             19,2
= liquido                                            622,8
teto fixo                                            627,0
margem                                                 4,2
```

**Dezessete caracteres.** É por isso que a card escreveu *"regra no prompt (não cabe)"* — não cabia literalmente. Todo o desenho abaixo é restrito por este número.

## Decisões de implementação

### D4 — O aperto: só o segmento interrogativo conta

`campos_perguntados` deixa de procurar o marcador no texto inteiro e passa a procurá-lo apenas nos segmentos que terminam em `?`, partindo em `[.!?]`. A guarda antiga (`if "?" not in texto`) sai por redundância: sem segmento interrogativo não há onde procurar.

O que isso conserta, medido contra o proxy atual:

```
"Temos um apartamento de 3 quartos com vaga na Vila Mariana. Quer ver as fotos?"
  hoje     -> ['quartos', 'tipo_imovel', 'vagas']
  apertado -> []

"Achei uma casa com 2 vagas de garagem no seu orcamento. Posso te mandar?"
  hoje     -> ['faixa_preco_max', 'vagas']
  apertado -> []
```

O que ele preserva — os dois casos que motivaram a card, nas duas formulações que `compra-14` de fato produziu:

```
"Voce tem alguma regiao ou bairro de preferencia? E precisa de vaga de garagem?"
  -> ['regiao', 'vagas']
"Para eu montar boas opcoes, voce tem alguma regiao ou bairro de preferencia?"
  -> ['regiao']
```

**Não parto em vírgula, de propósito.** Partiria *"você tem alguma região ou bairro de preferência, ou tanto faz?"* num pedaço sem `?`, e o marcador escaparia — trocaria um falso positivo por um falso negativo em cima do caso que a card existe para pegar.

O preço fica escrito: `"Temos um apartamento de 3 quartos, quer ver?"` continua devolvendo `['quartos', 'tipo_imovel']`. Descrição colada por vírgula à pergunta é o falso positivo que sobrevive.

**Consequência de régua.** Os dois diagnósticos mudam de instrumento. O **43% da execução de 31/08 deixa de ser comparável** com o que sair daqui em diante — mesma situação da TEC-248 e da TEC-254, e pelo mesmo motivo. A direção esperada é para baixo; quanto, só a próxima execução paga diz. Nenhuma métrica que bloqueia é afetada.

### D5 — A camada: a detecção sai de `evals` para o domínio

Produção não importa de `mobia.evals`. `campos_perguntados` e `MARCADORES_DE_REPERGUNTA` vão para o domínio; `metricas.py` passa a reexportar, e `insistencias` e `_reperguntou` seguem lendo de lá sem mudança.

É a forma exata do `campos_a_gravar`, e pelo mesmo motivo: duas cópias divergiriam, e a divergência só apareceria na borda.

### D6 — A coluna

`lead_qualification.perguntados_sem_resposta`, `ARRAY(String(32))`, nullable. Migração `0009`.

**`NULL` e `{}` significam coisas diferentes.** `NULL` é *"linha anterior a esta card, ninguém marcava"*; `{}` é *"marcava, e não havia nada a marcar"*. É a mesma distinção que a TEC-231 fixou nas colunas de cache, e colidir as duas leituras na mesma coluna é o defeito que ela consertou.

**Acumulação por união, sem remoção.** Se o lead responde, o campo entra no estado e a leitura passa a mostrar o valor. Remover da coluna exigiria uma segunda regra, que pode divergir da primeira; a leitura já decide (D8).

**A união mora no SQL, não numa leitura prévia.** No `ON CONFLICT DO UPDATE`:

```
perguntados_sem_resposta =
    coalesce(lead_qualification.perguntados_sem_resposta, '{}') || excluded.perguntados_sem_resposta
```

Ler o valor antigo em Python para unir em memória abriria a janela que a guarda de monotonia de `gravar_resumo` já fechou para o resumo: dois turnos concorrentes da mesma conversa leem o mesmo array, cada um une o seu, e o mais lento sobrescreve a marca do mais rápido. No SQL a união acontece dentro do `UPDATE`, e as duas marcas sobrevivem. Duplicatas no array são possíveis por esse caminho e não incomodam — a leitura testa pertinência, não conta.

**A coluna é escrita em toda gravação, mesmo vazia.** Sem isso, uma linha criada por esta card com nada a marcar sairia `NULL`, e `NULL` está reservado para *"linha anterior à card"*. Quando não há o que marcar, grava `{}`.

### D7 — A regra compartilhada, e onde ela é chamada

Uma função irmã de `campos_a_gravar`, na mesma casa (`context/repositorio.py`):

```
campos_a_marcar(texto_da_resposta, preenchidos) -> set[str]
    return campos_perguntados(texto_da_resposta) - preenchidos
```

`preenchidos` é o estado **depois** da gravação deste turno. A subtração é o que separa esta marca do proxy irmão: campo que já está no estado e foi reperguntado é território de `_reperguntou`, e não entra aqui.

`gravar_estado` a chama na mesma transação — os dois fatos vêm da mesma chamada ao modelo, como já vale para intenção e extração. Isso exige passar o texto da resposta para `gravar_estado`.

**`FORA_DE_ESCOPO` não marca.** `campos_a_gravar` devolve `{}` e `gravar_estado` retorna cedo; a marca segue o mesmo caminho. O buraco é real e declarado: um agente que pergunte "qual região?" num turno classificado `FORA_DE_ESCOPO` não marca, e pode perguntar de novo. Fica assim porque, com D1 permanente, **marcar de menos é o erro mais seguro dos dois**.

### D8 — A leitura: valor vence marca, e o rótulo custa zero

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

**A marca nunca aparece ao lado de um valor**, e a ordem não muda. Nenhuma seção nova em `montar_prompt`: o rótulo `Estado de qualificacao:` já existe e é reusado, então a subcontagem fixa não cresce. O texto por turno cresce, e esse é contado por `montar_contexto` — que é o comportamento correto, porque ele é de fato enviado.

### D9 — A regra do prompt é reescrita, não acrescentada

```
- nao repergunte o que ja esta preenchido
+ nao repergunte o preenchido nem o ignorado
```

Custo medido pelo proxy `len/4`, sobre a margem de 4,2:

| texto | delta | cabe? |
| --- | --- | --- |
| `...o que ja esta preenchido nem o que o lead ignorou` | +6,25 | **não** |
| `...o preenchido nem o que o lead ignorou` | +3,25 | sim, folga 0,95 |
| `...o preenchido nem o ignorado` | **+0,75** | sim, folga 3,45 |

Encurtar a cláusula existente paga a cláusula nova. **O teto de 627 não sobe** — que é a resposta que o docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada` manda procurar antes de mexer no número.

A forma escolhida é a de +0,75. A de +3,25 é mais explícita e deixaria 0,95 de folga para o projeto inteiro, o que é folga nenhuma.

### D10 — O espelho no eval, e a armadilha nomeada

O runner monta `LeadQualification(**estado_acumulado)`. Para o eval medir o conserto, `estado_acumulado` precisa carregar a marca, acumulada por `campos_a_marcar` — a mesma função de produção.

**A armadilha:** o runner faz `conhecidos_antes = set(estado_acumulado)`. Com a marca virando mais uma chave do dict, a string `perguntados_sem_resposta` entraria como se fosse um campo conhecido, e contaminaria os dois proxies — `_reperguntou` e o `- conhecidos_antes` de `campos_perguntados`. `conhecidos_antes` tem de excluir a chave da marca explicitamente, e um teste trava isso.

## Testes

- As duas formulações de `compra-14` continuam detectadas depois do aperto.
- Os dois falsos positivos de descrição de imóvel deixam de ser detectados.
- O falso positivo residual (vírgula) **continua** detectado, travado de propósito: se alguém o consertar, que seja deliberado.
- `_reperguntou` e `insistencias` seguem lendo a mesma tabela — o teste que já existe cobre, e não pode passar a existir uma segunda cópia.
- `NULL` e `{}` não colidem: linha antiga continua legível, linha nova sem marca grava `{}`.
- A marca some da leitura quando o campo é preenchido, e a ordem dos campos não muda.
- `FORA_DE_ESCOPO` não marca.
- `conhecidos_antes` não contém a chave da marca.
- `test_a_margem_do_orcamento_do_prompt_e_deliberada` continua passando, com o teto em 627.

## Contrato depois da card

- Um campo perguntado e não respondido é marcado no estado da conversa, e o prompt o carrega.
- O agente é instruído a não reperguntar campo marcado, pela vida da conversa.
- A detecção é uma só, no domínio, e produção e eval chamam a mesma função.
- Nenhuma métrica que bloqueia o gate muda de valor por esta card.

## O que esta card não entrega

- **Nenhuma garantia de que o modelo obedece.** A regra é texto no prompt; a marca é dado no prompt. Se o modelo reperguntar assim mesmo, esta card não impede — ela mede na execução seguinte.
- **Nenhum log de "deixei de perguntar".** Não há como observar, em produção, um campo que morreu por marca.

## Lacunas conhecidas

- **A permanência de D1 nunca foi medida.** Ninguém sabe quantos campos ela mata em conversa longa, e não há instrumento para saber. Se doer, a resposta é medir e escolher uma expiração — não herdar uma da janela (D3).
- **O falso positivo residual mata campo para sempre, e em silêncio.** É a combinação de D1 com a opção 3 de D2, e era exatamente o risco que a opção 2 comprava. Fica registrado que o preço foi visto antes de ser pago.
- **O 43% publicado em 31/08 vira número de outra régua.** A comparação de insistência fica cortada aqui.
- **A regra em +0,75 é mais curta que a mais precisa.** *"o ignorado"* depende de o modelo ligar a palavra à linha `(perguntado, sem resposta)` do estado. A forma explícita existia e custava 3,25 sobre 4,2 — recusada por não deixar folga para ninguém depois.
- **`follow-up-06` não é resolvido por esta card.** O pior caso do relatório é `VENDER_IMOVEL` recebendo roteiro de comprador — território da TEC-137. Um caso entre 16, e apontar para cá seria diagnóstico errado.

## Fora de escopo

- Cadência, reformulação e prioridade (opções B, C, D de D0).
- Fazer o modelo declarar o que perguntou (opção 2 de D2).
- Qualquer mudança nas métricas que bloqueiam o gate.
