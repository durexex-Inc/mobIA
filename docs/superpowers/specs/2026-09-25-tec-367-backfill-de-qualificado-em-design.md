# TEC-367 — Backfill de `qualificado_em`, e o funil que deixa de passar de 100%

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-367](https://eduardodurieuxlopes.atlassian.net/browse/TEC-367) — épico TEC-189
**Branch:** `feat/tec-367-backfill-de-qualificado-em`
**Origem:** SRS mobIA Frontend v1.0 — RT-FE-02, RN-FE-05.2 · TEC-190

## Objetivo

O painel de funil mostra `Qualificado → Recomendado` em 4000%. A card pede duas coisas, e elas são as **duas causas** que a docstring de `domain/metricas/repositorio.py` já nomeia por extenso:

1. **Lacuna L1** — `Qualificado` conta só quem ganhou `qualificado_em` depois da migration `0040`; `Recomendado` conta todos. Período antigo com 40 recomendados e 1 qualificado dá 4000%.
2. **O lead que qualifica no primeiro turno** — despeja intenção, orçamento, região e urgência numa mensagem só, fica **fora** de `Em conversa` (que exige mais de uma fala) e **dentro** de `Qualificado`.

Consertar só a primeira não cumpre o critério de aceite, que é *"nenhuma conversão entre etapas consecutivas passa de 100%"*.

## D1 — A fonte do backfill existe, e a migration `0040` afirma que não

A `0040` diz, na própria docstring:

> Coluna nulável e sem backfill: **o instante nunca foi gravado em lugar nenhum, então não há de onde o backfill sair.**

**Isso é falso, e é o achado central desta card.** O instante está em `lead_score_audit`, que existe desde a migration `0012` — vinte e oito revisões **antes** da `0040`.

A cadeia que prova:

- `qualificacao.py::esta_qualificado` devolve verdadeiro quando os quatro de `CAMPOS_OBRIGATORIOS` passam por `_preenchido` e nenhum está recusado.
- `qualificacao.py::campos_obrigatorios_preenchidos` **conta** os mesmos quatro, com `_preenchido` e a mesma regra de recusa. São a mesma condição computada pela mesma função.
- `score.py::calcular_score` grava `completude = campos_obrigatorios_preenchidos(...) * PONTOS_POR_CAMPO_OBRIGATORIO`.
- `lead_score_audit.completude` guarda esse valor **por linha**, com `created_at`, e a tabela é append-only.

Com `PONTOS_POR_CAMPO_OBRIGATORIO = 5` e quatro campos: **`completude = 20` ⟺ `esta_qualificado`**. O instante procurado é

```sql
MIN(created_at) FROM lead_score_audit WHERE completude = 20
```

por `(channel, conversation_key)`.

**O comentário da `0040` muda junto**, porque hoje ele mente sobre o que existe no banco — e foi ele que fez esta lacuna parecer irrecuperável por vinte e oito revisões.

## D2 — O que se grava é o primeiro instante PROVADO, e a diferença importa

O backfill não recupera o instante real da qualificação: recupera **o primeiro instante em que a trilha registra que ela já tinha acontecido**. Os dois coincidem na prática, e a razão é a própria RN-06.4 emendada — a trilha grava quando o resultado muda, e a passagem de três para quatro campos move `completude`, o que produz a linha com `CAUSA_CAMPOS_OBRIGATORIOS`. Um lead que já chega qualificado no primeiro turno ganha a linha por `CAUSA_PRIMEIRO_CALCULO`.

Onde eles podem divergir, dito antes de alguém descobrir depois:

- **Lead qualificado antes da migration `0012`.** Não tem trilha, continua `NULL`, e continua fora da etapa. É o resíduo irredutível da L1, e agora ele é *pequeno e datável* em vez de indefinido.
- **Retenção da trilha.** A RNF-18 apaga registro com mais de 12 meses (`sweep_retencao_auditoria`), então o backfill tem prazo de validade. **Rodá-lo é urgente por essa razão, e não só pelo painel.**

## D3 — O backfill é migration, e o `20` é cópia literal com guarda

Migration, e não script avulso: roda uma vez, é versionada, e vai junto com o deploy que corrige o painel. Um script exige alguém lembrar de executá-lo — e o `CLAUDE.md` já registra o estrago de banco carimbado sem o DDL correspondente.

**SQL puro, sem importar `mobia.*`.** É a regra que a `0053` escreve por extenso sobre os vocabulários da auditoria: *"migration aplicada nao muda quando o codigo muda"*. Se amanhã `PONTOS_POR_CAMPO_OBRIGATORIO` virar 6, a migration já aplicada continua tendo feito o que fez.

O preço é uma segunda cópia do `20`, e ela ganha a mesma proteção que a `0053` deu às dela: **um teste unitário que lê a migration com `ast` e confere contra o produto de `len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO`**. Sem ele, a cópia envelhece em silêncio — e este é o repo em que 51 commits existem só para corrigir afirmação que ele próprio escreveu errado.

**`WHERE qualificado_em IS NULL`**, pela mesma disciplina de `carimbar_qualificacao`: o backfill não sobrescreve o que a aplicação já carimbou. Isso também o torna idempotente.

## D4 — A segunda causa: o funil passa a ser monótono por construção

`Em conversa` exige `count(mensagens do lead) > 1`, e o piso não é enfeite — sem ele, `Novo` e `Em conversa` dariam sempre o mesmo número e a conversão entre as duas seria 100% fixo, o que não informa nada.

O problema não é o piso: é que **as cinco contagens são consultas independentes**, e nada impõe `Qualificado ⊆ Em conversa`. A docstring atual admite isso e trata como fato sobre os dados:

> Nenhuma das duas é erro de consulta: são fatos sobre os dados. Quem ler o painel precisa saber que o funil pode não decrescer.

**Esta card reverte essa decisão**, e o argumento é o que a RN-17.2 pede: uma *taxa de conversão*. Uma taxa acima de 100% não é uma taxa — é um sinal de que as etapas não estão aninhadas. Num funil, "chegou à etapa N" implica "passou pelas anteriores", e é isso que torna a divisão significativa.

Cada etapa passa a contar **quem a alcançou ou alcançou qualquer etapa posterior**. Em SQL, a união dos conjuntos das etapas a partir dela.

**O custo, declarado:** `Em conversa` passa a incluir o lead que falou uma vez só e qualificou. Isso é defensável — ele escreveu, o agente respondeu, houve conversa —, e o piso de "mais de uma fala" continua valendo para quem **não** avançou, que é exatamente o caso que ele existe para separar de `Novo`.

**O que isso NÃO faz:** não mascara a L1. Depois do backfill, `Qualificado` sobe porque os leads existem; a monotonia só garante que o denominador nunca seja menor que o numerador.

**`AGENDADO` fica fora da acumulação**, porque não tem fonte (`SEM_FONTE`): incluí-lo faria `Recomendado` herdar um conjunto vazio e nada mudaria, mas escreveria no código uma dependência que some quando a TEC-376 der número àquela etapa.

## D5 — Um comentário vizinho que já mentia

`_coorte` justifica a recusa do filtro por corretor assim:

> `montar_recorte` RECUSA o filtro por corretor com 422 porque `handoffs.corretor_id` **nunca é escrito** (Emenda E-01 da RN-16.2)

A premissa caiu: desde a TEC-192, `notificacao/envio.py` é o escritor de `handoffs.corretor_id` — a própria docstring dele diz isso, e a Emenda **E-06** da RN-16.2 registra a mudança. A recusa com 422 continua de pé, porque virá-la é decisão da TEC-316; o que mudou é **por quê** ela ainda está lá.

Entra nesta card porque é o mesmo arquivo que ela altera, e é literalmente a categoria `VIZINHO` de `comentarios_tocados.py`: comentário que ninguém editou, dentro de código que mudou, e que por isso ninguém relê.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| Funil sem conversão impossível após o backfill | `tests/integration/test_funil_monotono.py` |
| Lead qualificado antigo ganha a data pelo critério documentado | `tests/integration/test_migrations.py` |
| O `20` da migration não diverge do código | `tests/unit/test_backfill_de_qualificacao.py` |

## Emendas ao SRS

- **RN-17.2** — o funil passa a ser monótono por construção, e a conversão deixa de poder passar de 100%. Registra também o resíduo da L1 (lead anterior à `0012`) e o prazo de validade do backfill imposto pela retenção de 12 meses da RNF-18.
