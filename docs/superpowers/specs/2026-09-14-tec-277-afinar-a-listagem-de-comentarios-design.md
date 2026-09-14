# TEC-277 — Afinar a listagem de comentários a reconferir antes do PR

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-277](https://eduardodurieuxlopes.atlassian.net/browse/TEC-277) — Should (MoSCoW), sem épico (ferramenta de desenvolvimento)
**Branch:** `feat/tec-277-afinar-a-listagem-de-comentarios`
**Dependências:** nenhuma

## Objetivo

`scripts/comentarios_tocados.py` marca volume demais, e volume assim treina quem lê a ignorar — que é o oposto do que a ferramenta existe para fazer.

O desenho entrega **uma saída padrão limitada e ranqueada, com a listagem completa atrás de uma flag**. E declara, com medição, que duas das quatro regras de negócio da card não sobrevivem ao contato com os dados.

## O que a medição descobriu, e que muda o desenho

Medido em 14/09/2026 sobre **19 branches já mergeadas** (merges dos PRs #87 a #108), rodando o script real e não modificado, com um `git worktree` descartável por branch.

### O tamanho do problema é maior do que a card diz

| | |
| --- | --- |
| `VIZINHO` por branch | mediana **722**, média 591,5, máximo **1257** (TEC-154) |
| Branches com saída acima de 100 linhas | **16 de 19** |
| Pior saída | TEC-153, **1928 linhas** |

A card cita 723 `VIZINHO` e 1435 linhas. Os dois números batem com branches reais do dataset (TEC-174 tem 722; TEC-175 tem 1453), mas **não são os piores casos** — a card subestima.

### O ruído tem três donos, e o maior é uma função só

**83,9% de todo o `VIZINHO` medido vem de três blocos:**

| bloco | itens | fração | branches em que aparece |
| --- | ---: | ---: | --- |
| `turno.py::executar_turno` | 8530 | **75,9%** | 10 de 19 |
| `workers/main.py::WorkerSettings` | 469 | 4,2% | 5 de 19 |
| `app/config.py::Settings` | 430 | 3,8% | 2 de 19 |

`executar_turno` tem **1877 linhas**. É o defeito de verdade, e esta card não o conserta — ver `L1`.

### A regra que a card pede foi medida, e não funciona

A card manda que *"a vizinhança seja medida por distância ao que mudou, não pelo corpo do `def`"*. Sobre os 11.239 achados `VIZINHO`, a distância até a linha alterada mais próxima tem mediana de **110 linhas**:

| raio | ainda marcado |
| ---: | ---: |
| 5 | 94,8% |
| 20 | 81,6% |
| 50 | **65,9%** |
| 200 | 35,9% |

Um raio de 50 linhas deixaria dois terços do ruído de pé. É preciso chegar a 200 para cortar metade — e um raio de 200 linhas não é "vizinhança", é o arquivo. **A causa é estrutural:** dentro de uma função de 1877 linhas, todo comentário está longe de toda edição, por mais próximo que esteja semanticamente.

### E "menor bloco que contém a linha" rende 0,036%

Antes de medir, a hipótese era que o amplificador fosse o aninhamento: como `_blocos` devolve toda `class` e todo `def`, e a faixa de uma classe contém seus métodos, mexer num método marcaria os comentários de todos os outros. Trocar por "o **menor** bloco que contém a linha alterada" pareceu valer ~10%.

Medido: **4 itens em 11.239** — 0,036%, e **exatamente zero em 15 das 19 branches**. Dos 4, nenhum veio de `class`; todos de `def` dentro de `def` (fixtures que devolvem closure).

A hipótese estava errada pela razão que a tabela acima já mostrava e que não foi lida: `Settings` e `WorkerSettings` são classes **só de atributos**. Não têm método aninhado, então o menor bloco que contém um campo alterado **continua sendo a classe inteira**. E `executar_turno` é grande e plana. A granularidade `def`/`class` não tem o que cortar em nenhum dos três donos do ruído.

### A evidência nº 2 da card é factualmente falsa

A card afirma, como segunda das três evidências:

> A TEC-176 mudou um **contrato** [...] Dois comentários que descreviam esse contrato ficaram falsos — em `handoff/models.py` e `handoff/resumo.py` — e a ferramenta **não os viu**, porque o raio dela são os arquivos do diff e a branch não abriu nenhum dos dois.

**Os dois arquivos estão no diff da TEC-176.** Verificado no merge `3ced517`: `git diff --name-only $(git merge-base 3ced517^1 3ced517^2)..3ced517^2 -- '*.py'` lista `src/mobia/domain/handoff/models.py` e `src/mobia/domain/handoff/resumo.py`.

A ferramenta **viu** os dois comentários e os marcou. Quem não os leu foi uma pessoa — porque a saída daquela branch tinha centenas de linhas. **A evidência nº 2 não é um caso de cegueira: é a evidência nº 1 outra vez.** É o argumento mais forte do dataset a favor de cortar o volume, e o mais forte contra construir a detecção de contrato (`D3`).

## Decisões

### D1 — A saída padrão é limitada e ranqueada; a completa fica atrás de `--tudo`

O padrão passa a mostrar, por bloco, os **5** achados `VIZINHO` mais próximos de uma linha alterada, e substitui o resto por uma linha de resumo que nomeia o bloco e conta o que omitiu:

```
  ... +703 vizinhos em executar_turno (1877 linhas), os mais distantes omitidos -- use --tudo
```

`--tudo` imprime a listagem de hoje, sem teto.

**Por que teto, e não uma regra melhor:** porque não existe regra melhor. As duas alternativas estruturais foram medidas acima e rendem 0,036% e 34%. O volume não vem de uma regra mal calibrada; vem de uma função de 1877 linhas, e nenhuma regra de vizinhança conserta isso de fora.

**Por que a flag, e não só o teto:** a ferramenta existe justamente para os casos em que o julgamento automático não basta. Um teto sem escape é a ferramenta decidindo sozinha o que você não precisa ler — e foi um item isolado, num arquivo com poucos achados, que pegou o defeito da TEC-187. Com `--tudo`, quem desconfia do ranqueamento tem para onde ir, e **nada se perde**.

**Efeito medido (N=5), sobre as mesmas 19 branches:** mediana da saída cai de **890 para 188 linhas**, máximo de 1928 para 749.

**Consequência declarada, e é o limite honesto desta card:** o teto morde apenas `VIZINHO`. `ALTERADO` continua inteiro, porque é o comentário que você mesmo acabou de tocar — a obrigação ali é de outra natureza. Nas branches que reescrevem muito, é `ALTERADO` que domina o que resta: a TEC-153 tem 623 e a TEC-184, 525. Para essas, a saída continua longa mesmo com o teto, e o número medido de 188 é a mediana, não uma garantia.

**`N = 5`, e de onde vem:** medido para N ∈ {3, 5, 10, 20}, a diferença de volume entre N=3 e N=20 é de ~9% dos itens omitidos — o volume não vem de poucos blocos com muitos achados, vem de muitos blocos batendo o teto. Como o custo é praticamente o mesmo, 5 é o maior valor que não paga nada a mais e dá uma linha de contexto além do mínimo. Não é um ótimo; é o joelho de uma curva plana, e trocá-lo por 3 ou 10 muda pouco.

**O ranqueamento é por distância à linha alterada mais próxima do mesmo arquivo**, crescente. É o único sinal que a ferramenta tem hoje sem inventar heurística de conteúdo, e `D3` explica por que não inventamos uma.

### D2 — Comentário de nível de módulo continua fora do alcance, e isso fica escrito

`_blocos` só devolve `class` e `def`, e `dentro_de_bloco_mexido` exige contenção total. Logo **um comentário fora de qualquer bloco nunca pode ser `VIZINHO`** — só `ALTERADO`, e só se a linha dele mesma mudar.

Esta card **não conserta isso**, mas para de deixar o buraco implícito: o repo já o descobriu na marra e registrou por escrito em `src/mobia/domain/agente/investidor.py:90`, num comentário que diz que `scripts/comentarios_tocados.py` "nao tem como ver isso daqui". Um buraco que uma pessoa precisou anotar no código é um buraco que a ferramenta devia anotar sozinha — ver `L2`.

### D3 — A detecção de contrato fora do diff sai do escopo, e o motivo é o que vale

A terceira regra de negócio da card pede que, quando o diff altera assinatura ou significado de retorno, a ferramenta aponte quem descreve esse contrato **fora dos arquivos do diff**. O cenário 2 do Gherkin é esse.

**Não é entregue, por três razões, em ordem de peso.**

**A premissa caiu.** O único caso concreto que a card oferece — os dois comentários de `gerar_resumo` na TEC-176 — não é um caso de cegueira: os dois arquivos estavam no diff. Construir um mecanismo para um problema cuja única evidência se dissolveu é construir no escuro.

**O gatilho, medido, é quase todo ruído.** Um protótipo que dispara em "assinatura ou `return` alterado" marca **93,7% de funções NOVAS** (698 de 745) — um `def` recém-criado tem, tecnicamente, a linha da assinatura entre as adicionadas. Restringindo a funções pré-existentes, a mediana cai de 13 itens por branch para **1**.

**E o que sobra é homonímia.** Dos 561 itens brutos, 470 (83,8%) batem em nomes genéricos do vocabulário do repo: `campo` 121×, `faixa` 55×, `upgrade` 40×, `porta` 18×, mais `get`, `send`, `__init__`. Filtrar função nova não resolve: dos 27 hits "reais" da pior branch, a maioria é `porta`.

Sobra sinal — o protótipo achou 6 referências legítimas a `gerar_resumo` fora do diff, em `workers/main.py` e nos testes. Mas 1 item por branch de mediana não paga o código, e **a card ganha mais com o achado registrado do que ganharia com o mecanismo**: quem reabrir o assunto começa sabendo que a premissa original era falsa e que o gatilho óbvio é 94% ruído.

### D4 — A ferramenta passa a ter teste

Hoje não tem nenhum, e o script irmão `scripts/gerar_base_simulada.py` tem (`tests/unit/test_base_simulada.py`), então o precedente existe e a ausência é só omissão.

As partes puras são testáveis sem git e sem banco: `linhas_alteradas` é um parser de texto de diff (dá para alimentar com saída sintética), e `_comentarios`, `_docstrings`, `_blocos` e `examinar` são funções sobre fonte mais um conjunto de linhas. Só `_rodar`, `_pendentes_fora_do_commit` e `main` tocam o mundo externo.

Sem isso, esta card muda o classificador de uma ferramenta que ninguém verifica — e a única evidência de que ela ainda funciona seria rodá-la à mão.

## Lacunas declaradas

**L1 — `executar_turno` continua com 1877 linhas, e é ela o defeito.** 75,9% do ruído medido sai de uma única função, e esta card a contorna com um teto em vez de resolvê-la. Partir `executar_turno` cortaria o problema pela raiz e melhoraria tudo o mais que toca aquele arquivo — mas é refatoração grande no coração do agente, com cobertura de integração pesada, e é card própria. **Enquanto ela existir, a saída desta ferramenta vive de teto.**

**L2 — Comentário de módulo continua invisível como `VIZINHO`** (`D2`), e o caso pior — um comentário que descreve uma constante consumida noutro arquivo, como o de `investidor.py:90` — continua fora do alcance das duas categorias.

**L3 — Hunk só de remoção não gera nada.** O parser de `linhas_alteradas` lê apenas o lado `+`; um hunk com `,0` produz `range()` vazio. Então **apagar o código que um comentário descrevia e deixar o comentário não dispara `ALTERADO`** — só `VIZINHO`, e só se houver alguma linha adicionada no mesmo bloco. Não é tocado aqui.

**L4 — O ranqueamento é por distância, e distância não é relevância.** Um comentário a 400 linhas que cita o nome da função alterada é mais suspeito que um a 3 linhas que descreve outra coisa, e a ferramenta não sabe disso. Qualquer heurística de conteúdo cairia no mesmo problema de homonímia que enterrou a `D3`, então o desenho fica com o sinal burro e honesto em vez de um esperto e não medido.

**L5 — Os números são desta máquina e destas 19 branches.** A mediana de 188 linhas é medida sobre os PRs #87 a #108. Uma card que reescreva muito arquivo terá `ALTERADO` alto e saída longa apesar do teto, como a TEC-153 e a TEC-184 teriam.

## Testes

**Unitários, sem Docker** (`tests/unit/test_comentarios_tocados.py`, novo):

- `linhas_alteradas` sobre saída de diff sintética: hunk com contagem implícita (`+12` sem vírgula) devolve uma linha; `+12,3` devolve três; `+12,0` devolve nenhuma; `+++ /dev/null` é ignorado.
- `_comentarios` não confunde `#` dentro de string com comentário — é a razão de o script usar `tokenize` e não regex, e hoje nada prova isso.
- `_docstrings` pega docstring de módulo, de classe, de função e de função async, e **não** pega string solta no meio do corpo.
- `examinar` marca `ALTERADO` quando a linha do comentário mudou, e `VIZINHO` quando só o bloco mudou; `ALTERADO` ganha de `VIZINHO` quando os dois se aplicam.
- **O teto:** um bloco com mais de 5 vizinhos devolve os 5 mais próximos e uma contagem do resto; com 5 ou menos, devolve todos e nenhuma linha de resumo.
- **A ordem:** os 5 escolhidos são os de menor distância, e a distância é medida contra a linha alterada mais próxima do mesmo arquivo.
- `ALTERADO` **não** é limitado pelo teto, mesmo quando há muitos no mesmo bloco.
- `--tudo` desliga o teto: a mesma entrada devolve todos os vizinhos e nenhuma linha de resumo.

**Não coberto, e por quê:** `_rodar`, `_pendentes_fora_do_commit` e `main` tocam git e o sistema de arquivos; testá-los exigiria um repo de mentira por teste, e o que eles fazem é I/O fino sobre lógica que os testes acima já cobrem. Fica declarado em vez de simulado.

## Fora de escopo

- Virar gate de CI. O script continua devolvendo `0` sempre, e a decisão sobre cada comentário continua sendo de quem abre o PR — é o que ele existe para devolver a uma pessoa.
- Decidir automaticamente se um comentário está correto.
- Partir `executar_turno` (`L1`).
- A detecção de contrato fora do diff (`D3`), e com ela o cenário 2 do Gherkin.
