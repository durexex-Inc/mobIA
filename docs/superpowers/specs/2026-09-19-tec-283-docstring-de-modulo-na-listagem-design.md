# TEC-283 — A docstring de módulo entra na listagem

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-283](https://eduardodurieuxlopes.atlassian.net/browse/TEC-283)
**Branch:** `feat/tec-283-docstring-de-modulo-na-listagem`
**Origem:** lacuna declarada no desenho da TEC-282 e demonstrada contra a própria branch dela.

## Objetivo

Fazer a docstring de módulo entrar na listagem de `scripts/comentarios_tocados.py` como `VIZINHO` — a marca que a TEC-146 provou ser a perigosa, porque prosa que ninguém editou não aparece no diff e por isso ninguém a relê.

Hoje ela só aparece se for literalmente editada. `_docstrings` já anda por `ast.Module`, então `ALTERADO` já funciona; o que falta é `VIZINHO`, porque `dentro_de_bloco_mexido` pergunta a `_blocos`, que só conhece `ClassDef`, `FunctionDef` e `AsyncFunctionDef` — e a docstring de módulo não está dentro de nenhum deles.

## O que foi medido antes de desenhar

### A regra teria pego o caso que originou a card

A card afirma que, durante a TEC-282, a docstring de módulo de `tests/unit/test_comentarios_tocados.py` continuou dizendo "as partes que decidem o que e ALTERADO e o que e VIZINHO" — duas marcas de cinco —, num arquivo que aquela branch cresceu em mais de 400 linhas, e que foi preciso uma pessoa para pegar.

Medir isso contra a branch mergeada não mostra nada: a correção humana entrou **dentro** da branch (`514122b`), e a partir dali a docstring conta como `ALTERADO`. O estado que a card descreve é o commit anterior, `6398d7c`:

| | |
| --- | --- |
| Linhas alteradas em `tests/unit/test_comentarios_tocados.py` | 410 |
| Faixa da docstring de módulo | linhas 1-6 |
| A docstring mudou na branch? | não |
| Marca hoje | nenhuma |
| Marca com esta card | `VIZINHO` |

### O acréscimo de volume é quatro vezes menor do que a card supôs

A card diz: "todo arquivo tocado passaria a render pelo menos um achado", e pede a medição antes de escolher a regra. Medido em 19/09/2026 sobre os 20 merges mais recentes da `main` (PRs #109 a #128), comparando cada branch com o seu `merge-base`:

| | |
| --- | --- |
| Arquivos `.py` tocados nas 20 branches | 131 |
| — sem docstring de módulo | 58 |
| — com docstring de módulo | 73 |
| —— que já sai `ALTERADO` hoje | 41 |
| —— **que viraria `VIZINHO` novo** | **32** |

Por branch: mediana de **0** achados novos, máximo de **11**. São 32 em 131 porque 44% dos arquivos tocados não têm docstring de módulo nenhuma e, entre os que têm, 56% a editam na mesma branch — quem mexe no arquivo com frequência já mexe na prosa do topo.

O acréscimo é desprezível perto da mediana de 188 linhas de saída que a TEC-277 mediu. **A premissa de volume da card estava errada, e é por isso que a regra abaixo não precisa de limiar.**

### A alternativa do limiar, descartada com número

A card manda considerar e descartar com número a alternativa "incluir a docstring de módulo só quando a mudança no arquivo passar de N linhas". Com N = 30, os 32 achados caem para **9**: perde-se 72% do que a regra existe para achar, para poupar uma mediana de zero. Descartada.

O caso `6398d7c` sobreviveria ao limiar (410 linhas alteradas), mas isso não o salva: a docstring de uma linha que envelhece num arquivo de mudança pequena é exatamente o caso que a listagem existe para pôr na frente de quem revisa, e a medição diz que ele não custa nada.

## Decisões

### D1 — A regra

A docstring de módulo entra como `VIZINHO` quando **qualquer** linha do arquivo muda e ela própria não muda. Sem limiar, pela medição acima.

Quando ela própria muda, continua saindo como `ALTERADO`, que é o comportamento de hoje e não se mexe.

### D2 — Caso próprio em `examinar`, e não uma faixa nova em `_blocos`

A implementação óbvia — acrescentar o módulo a `_blocos` como faixa `1..fim` — está errada, e é o único risco real desta card.

`dentro_de_bloco_mexido` passaria a ser verdadeiro para **todo** comentário do arquivo, porque a faixa do módulo contém todas as outras. Cada `#` solto de um arquivo tocado viraria `VIZINHO`, e aí sim haveria a explosão de volume que a card temia — só que por um motivo diferente do que ela imaginava, e muito maior: não um achado por arquivo, mas todos os comentários fora de `def` de cada arquivo tocado.

A docstring de módulo entra como caso próprio em `examinar`: se o módulo tem docstring, ela não foi alterada e o arquivo tem alguma linha alterada, sai um achado. Nada mais no arquivo muda de classificação.

Não há duplicação com o laço de `_docstrings`, porque os dois ramos são mutuamente exclusivos: o laço só emite a docstring de módulo quando ela mudou, o caso novo só quando ela não mudou.

### D3 — Balde próprio no teto, chamado `<modulo>`

`limitar` agrupa os `VIZINHO` pelo **nome** do bloco, para a linha de resumo poder dizer onde ficou o que foi omitido. A docstring de módulo não pertence a bloco nenhum.

Ela ganha um balde próprio, chamado `<modulo>`. Os delimitadores não são caracteres válidos em identificador Python, então o nome nunca colide com um `def` ou `class` homônimo — que é a ambiguidade que a própria docstring de `limitar` já declara tolerar para os outros baldes.

Consequência declarada: como é no máximo **um** achado por arquivo, esse balde nunca bate o teto de 5 e portanto nunca é cortado. O nome existe para o caso em que a linha de resumo saísse com balde vazio, não porque o corte vá acontecer.

### D4 — Distância medida da borda mais próxima

Reusa a `distancia(inicio, fim)` que já existe em `examinar`, que mede da borda mais próxima da faixa e não da primeira linha. Para a maior docstring de módulo de `src/` (44 linhas, `domain/followup/prosa.py`) isso é o que impede uma alteração colada no fim dela de parecer distante.

A distância não muda o que aparece — um achado só nunca é cortado —, mas alimenta a ordenação de `limitar` e precisa ser coerente com o resto.

### D5 — A prosa deste repo muda junto

A docstring de módulo do próprio `scripts/comentarios_tocados.py` afirma hoje:

> Duas cegueiras conhecidas, nenhuma nova desta card. […] E docstring de nivel de MODULO nunca vira VIZINHO, porque `_blocos` so anda por ClassDef e FunctionDef

Essa frase passa a ser falsa com esta card. Vira **uma** cegueira conhecida — a da TEC-284, que segue aberta e continua descrita.

O CLAUDE.md descreve as cinco marcas e o que `VIZINHO` alcança ("está dentro de um `def`/`class` cujo código mudou"); a frase passa a valer para a docstring de módulo também e precisa acompanhar.

A docstring de módulo de `tests/unit/test_comentarios_tocados.py` nomeia as partes puras do script e cresce com esta card: entra no mesmo cuidado.

A própria ferramenta aponta os três, o que é a validação mais barata que esta card tem à disposição.

## Testes

Unitários puros, no estilo que o arquivo de teste já mantém: recebem fonte e conjunto de linhas alteradas, sem tocar git nem disco.

1. Docstring de módulo intocada num arquivo cujo corpo de função mudou → sai `VIZINHO`.
2. Arquivo sem docstring de módulo → nenhum achado a mais por esta regra.
3. Docstring de módulo que mudou → continua `ALTERADO`, uma vez só.
4. **O teste que fixa a D2:** um comentário solto fora de qualquer `def`, num arquivo tocado, continua **não** rendendo `VIZINHO`. É o teste que reprova se alguém "simplificar" a implementação acrescentando o módulo a `_blocos`.
5. O achado cai no balde `<modulo>` e a saída respeita o teto, com `--tudo` continuando a devolver tudo.

## Fora de escopo

- Virar gate de CI. A ferramenta continua não reprovando nada, e a razão está escrita no `return 0` de `main`.
- Decidir automaticamente se uma docstring está correta — é o julgamento que a ferramenta existe para devolver a uma pessoa.
- A TEC-284 (apagar ou renomear um arquivo aponta a prosa que o cita). Continua aberta e continua descrita na docstring do script.
