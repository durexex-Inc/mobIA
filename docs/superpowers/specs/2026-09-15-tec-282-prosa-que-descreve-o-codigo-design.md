# TEC-282 — Estender a listagem de comentários à prosa que descreve o código

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-282](https://eduardodurieuxlopes.atlassian.net/browse/TEC-282) — Should (MoSCoW), sem épico (ferramenta de desenvolvimento)
**Branch:** `feat/tec-282-prosa-que-descreve-o-codigo`
**Dependências:** nenhuma. Constrói sobre a TEC-277, já mergeada.

## Objetivo

`scripts/comentarios_tocados.py` filtra o diff com o pathspec `"*.py"`. Nenhum `.md` é examinado, nunca. A regra do repo — "se você mudar código que um comentário descreve, o comentário muda junto ou some" — vale para a prosa tanto quanto para o comentário inline, e a ferramenta que a faz cumprir é cega à metade dela.

O desenho entrega **uma seção nova na listagem, agrupada por documento, que aponta a prosa cuja citação de linha recai sobre arquivo que a branch mexeu**. Ela nasce das mesmas premissas da TEC-277: suspeita e não veredito, teto de leitura, e nenhuma reprovação.

## O que a medição descobriu, e que muda o desenho

Medido em 15/09/2026 sobre a árvore da `main` em `76258da`, e sobre os 11 merges mais recentes (PRs #100 a #111), resolvendo cada citação contra os arquivos versionados.

### A exposição cresceu em um dia, e o caso "comprovadamente falso" dobrou

| | card (14/09) | medido (15/09) |
| --- | --- | --- |
| Citações `arquivo.py:linha` em `.md` versionados | 128 | **155** |
| Documentos que as contêm | 36 | **38** |
| Já apontando além do fim do arquivo | 3 | **6** |

As 6 falsas são todas da TEC-267, mergeada em 14/09 — a branch que veio depois da medição da card. É a demonstração mais direta possível de que o defeito é corrente, e não um passivo estático.

### A ambiguidade de nome, que parecia o problema central, é 5%

55 das 155 citações usam só o nome do arquivo, sem caminho — e `repositorio.py` bate **9 arquivos** no repo, o que sugeria que casar por nome seria inviável. Medido, não é: **145 das 155 resolvem para exatamente 1 arquivo**, porque quase todo nome citado é único no repo. Restam 8 ambíguas na varredura inteira, 6 no escopo que este desenho adota.

A razão é que a ambiguidade não se mede contra o repo: mede-se contra o conjunto pequeno de arquivos que a branch alterou. Uma citação ambígua só produz achado extra se a branch mexer em dois arquivos homônimos ao mesmo tempo.

### 70% do volume vem de planos de implementação

| escopo | citações | por branch |
| --- | --- | --- |
| Todos os `.md` versionados | 155 em 38 documentos | mediana **39**, máximo 69 |
| Sem `docs/superpowers/plans/` | 62 em 13 documentos | mediana **9**, máximo 25 |

### A regra de nome de script, aplicada crua, é 90% ruído

A regra de negócio nº 4 da card pede que uma mudança sob `scripts/` aponte a prosa que nomeia aquele script. Aplicada a todos os `.md`, ela devolve **21 documentos** para `comentarios_tocados.py`. Destes, 19 são planos de branches já fechadas, e a menção é o comando de checklist, não descrição de comportamento:

```
8 ×  Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`
7 ×  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
3 ×  - [ ] **Step 2: Comentários tocados.** ...
```

### E o filtro que parecia óbvio para isso não funciona

A saída acima sugere filtrar menções dentro de bloco de código cercado, deixando só a prosa. Medido, isso **exclui exatamente o documento que a card existe para pegar**: no `CLAUDE.md`, as duas menções ao script estão dentro de fences, e fora deles há zero. O `CLAUDE.md` descreve o comportamento do script em prosa que não repete o nome do arquivo — ela vive ao redor do bloco, não dentro dele.

O filtro de fence está descartado por medição, e o corte de `plans/` resolve o mesmo problema melhor: sozinho, ele leva os 21 documentos a **2** — `CLAUDE.md` e o desenho da TEC-277, que são precisamente os dois que descrevem o que o script faz.

## Decisões

### D1 — O escopo da varredura exclui `docs/superpowers/plans/`

Um plano registra o que se fez numa branch num dia. Ele não afirma o que o código é hoje: afirma o que se pretendia mexer naquela ocasião. Envelhecer é o comportamento esperado dele, e "corrigir" um plano fechado seria reescrever histórico — o mesmo raciocínio que já mantém as emendas do SRS como itens aninhados em vez de reescrita do texto de 22/08/2026.

O corte é o que torna a card viável: leva a mediana por branch de 39 para 9, e resolve de quebra o ruído da regra de nome de script.

**Custo declarado, que é real:** 3 das 6 citações comprovadamente falsas de hoje estão em `plans/` e deixarão de ser apontadas. A dívida em planos fechados permanece invisível para a ferramenta, por decisão.

Entram: `CLAUDE.md`, `README.md`, `docs/srs/`, `docs/superpowers/specs/` e qualquer outro `.md` versionado — 75 dos 133 arquivos.

### D2 — A suspeita nasce da citação de linha, resolvida em três degraus

Um regex varre os documentos no escopo procurando `arquivo.py:N` e `arquivo.py:N-M`. Cada alvo é resolvido contra os `.py` versionados, na ordem:

1. caminho exato versionado — `src/mobia/domain/agente/turno.py`
2. sufixo de caminho — `agente/turno.py`
3. nome do arquivo — `turno.py`

Resolvendo para um arquivo só, a citação é **inequívoca**; para mais de um, **ambígua**; para nenhum, é ignorada. Se qualquer arquivo resolvido está entre os que a branch alterou, nasce o achado.

O conteúdo dos documentos é lido **do disco**, não do git, pelo mesmo motivo que os `.py` já são: um conserto ainda não commitado deve contar como conserto. O conjunto de documentos, esse sim, vem de `git ls-files` — prosa não versionada não é prosa do repo.

### D3 — Três marcas, e só uma delas entra no teto

| marca | quando | cortada pelo teto? |
| --- | --- | --- |
| `PROSA` | a citação aponta arquivo que a branch mexeu | sim |
| `FALSO` | a faixa citada passa do fim do arquivo, com resolução inequívoca | não |
| `NOMEIA` | a branch mexeu sob `scripts/` e o documento nomeia aquele script | não |

`FALSO` exige resolução inequívoca porque é a única marca que afirma algo, em vez de suspeitar: declarar falsa uma citação que talvez aponte outro arquivo seria a ferramenta errando na direção em que ela não pode errar. Citação ambígua que passa do fim de um dos candidatos sai como `PROSA`.

`FALSO` e `NOMEIA` escapam do teto pela mesma razão que `ALTERADO` escapa na TEC-277: o teto existe contra ruído de vizinhança, e nenhuma das duas é vizinhança.

### D4 — `FALSO` é condicionado à branch, divergindo da leitura literal da card

O cenário Gherkin da citação além do fim do arquivo não menciona branch alguma. Implementado assim, ele reportaria as citações falsas do repo inteiro em **toda** execução — hoje 3 no escopo adotado, sempre as mesmas, independentemente do que a branch fez. Ruído fixo é exatamente o que a TEC-277 mediu e cortou, e treinar quem lê a ignorar a seção nova mataria a card no primeiro mês.

`FALSO` sai, portanto, apenas entre as citações que já entraram por apontar arquivo alterado. O caso que a card quer pegar continua coberto: quando a branch empurra uma citação para além do fim do arquivo, esse arquivo está no diff por construção.

A limpeza das citações já falsas fica onde a própria card a pôs — fora de escopo.

### D5 — A saída ganha seção própria, agrupada por documento

A prosa vem depois dos arquivos `.py`, agrupada pelo `.md` que a contém, e não sob o arquivo de que fala. Quem revisa abre um documento e reconfere tudo dele de uma vez; a alternativa espalharia um documento com citações a cinco arquivos por cinco seções, e quem fosse corrigi-lo abriria o mesmo `.md` cinco vezes.

```
src/mobia/domain/followup/repositorio.py
  ALTERADO src/mobia/domain/followup/repositorio.py:222  # o corte de candidatura
  VIZINHO  src/mobia/domain/followup/repositorio.py:154  # as duas CTEs

docs/superpowers/specs/2026-09-14-tec-187-encerrar-cadencia-em-dormente-design.md
  PROSA  :112  repositorio.py:209  -> src/mobia/domain/followup/repositorio.py
  PROSA  :140  repositorio.py:154-181
  ... +3 citação(ões) omitida(s) -- use --tudo

docs/superpowers/specs/2026-09-14-tec-267-acento-na-fala-ao-lead-design.md
  FALSO  :134  test_mensagem_do_followup.py:113  (o arquivo tem 103 linhas)

CLAUDE.md
  NOMEIA :318  descreve scripts/comentarios_tocados.py
```

Os três documentos do exemplo são reais e as citações também; a branch que os produziria junta é hipotética.

O rodapé passa a contar a prosa junto, separando o que é comprovadamente falso do que é suspeita.

### D6 — Teto próprio, com constante própria

`MAXIMO_DE_CITACOES_POR_DOCUMENTO = 5`, valor herdado do teto da TEC-277.

Reutilizar `MAXIMO_DE_VIZINHOS_POR_BLOCO` faria o nome mentir sobre o que ele limita, e este repo trata nome e comentário que mentem como defeito. São duas constantes porque são dois cortes, ainda que hoje com o mesmo valor.

**O valor não foi calibrado como o da TEC-277, e isso fica escrito:** medido, ele quase nunca morde — mediana de 9 citações espalhadas por até 8 documentos dá 1 a 3 por documento, e o máximo observado (25 em 8 documentos) também passa longe. Ele existe como rede contra o documento que venha a concentrar citações, não como corte rotineiro. Se algum dia a seção ficar longa, a calibração é dele, e a medição de hoje é o ponto de partida.

`--tudo` desliga os dois tetos pelo mesmo caminho que `limitar` já usa: teto 0 devolve tudo, sem caminho separado que possa divergir.

## Lacunas declaradas

**Saída de ferramenta colada em bloco de código vira suspeita.** `src/x.py:12:5: E501` do ruff casa com o regex e produz um `PROSA`. Custa uma linha e some quando o revisor olha; distinguir citação de saída de ferramenta exigiria heurística que erraria nos dois sentidos, e errar por sobra é o lado barato.

**A prosa que descreve código sem citar linha continua invisível.** Casar por nome de símbolo foi medido e reprovado na TEC-277 — 83,8% de homonímia — e nada aqui muda esse número. Este desenho cobre a prosa que se ancora em linha e, por exceção estreita, a que nomeia um script.

**Citação em documento fora de `plans/` que aponte arquivo não alterado não é conferida.** A ferramenta continua sendo sobre o que a branch tocou.

**A ambiguidade produz suspeita a mais, nunca a menos.** Uma citação a `repositorio.py:209` numa branch que altera dois `repositorio.py` diferentes aparece uma vez, sem dizer qual dos dois motivou. São 6 citações ambíguas no escopo inteiro, e o custo é uma linha que o revisor descarta em segundos.

## Testes

**Unitários, sem Docker** (`tests/unit/test_comentarios_tocados.py`, acrescenta), no padrão puro que a TEC-277 deixou: as funções que decidem recebem texto e conjuntos, não tocam git nem rede.

- O regex reconhece linha única e faixa, e ignora o que não é citação.
- Os três degraus de resolução, cada um isolado, mais o caso ambíguo e o que não resolve.
- `PROSA` nasce quando o arquivo resolvido está entre os alterados, e não nasce quando não está.
- `FALSO` sai quando a faixa passa do fim do arquivo e a resolução é inequívoca; a mesma citação ambígua sai como `PROSA`.
- `NOMEIA` sai para mudança sob `scripts/` e não sai para mudança fora dele.
- O escopo exclui `docs/superpowers/plans/` e inclui `CLAUDE.md`.
- O teto corta `PROSA`, poupa `FALSO` e `NOMEIA`, e `--tudo` devolve tudo.

## Fora de escopo

- Virar gate de CI. A ferramenta continua informando e devolvendo 0.
- Decidir automaticamente se uma afirmação em prosa está correta.
- Reescrever as citações já existentes, incluindo as 6 comprovadamente falsas.
- Cobrir prosa em `docs/superpowers/plans/` (D1).
