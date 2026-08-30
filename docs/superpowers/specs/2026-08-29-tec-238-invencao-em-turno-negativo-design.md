# TEC-238 — Medir invenção de campo nos turnos que o corpus não anota

**Status:** aprovado em 2026-08-29. Não implementado.

**Card:** [TEC-238](https://eduardodurieuxlopes.atlassian.net/browse/TEC-238) — origem: lacuna declarada no README pela TEC-145 e mantida aberta pela TEC-239.

## Objetivo

O README afirma que `precisao_da_extracao` pune os dois lados — campo esperado que
não veio conta erro, e campo que veio sem o lead ter dito também. A afirmação é
verdadeira **apenas nos 38 turnos anotados**, de 138. Nos outros 100, invenção não
é medida por ninguém.

O exploit concreto: um modelo que extrai perfeitamente nos 38 turnos anotados e
emite `regiao` e `tipo_imovel` em **todos** os outros 100 tira 100%, faixa VERDE.
E essas invenções não são inertes — são gravadas em `lead_qualification` para toda
intenção menos `FORA_DE_ESCOPO`, e com a sobrescrita pelo mais novo (D4 da TEC-145)
mais a regra de que `null` não apaga, ficam permanentes e sem rastro.

É o furo de corpus só-positivo que a TEC-233 encontrou no corpus de moderação — onde
um moderador que bloqueia tudo passava num corpus com só casos positivos — na mesma
forma.

## O que já existe

Levantado no código antes do desenho, não presumido:

- `TurnoAnotado.campos` (`src/mobia/evals/corpus.py`) é `dict | None`. `_turno_de`
  **recusa** `campos` vazio hoje: a mensagem manda omitir a chave, o que remove o
  turno da medição. O único formato de turno em que invenção poderia ser pega é
  justamente o que o corpus não consegue expressar.
- `_rodar_conversa` (`evals/test_acuracia_de_intencao.py:182`) filtra com
  `if turno.campos is not None`, e passa `turno.campos` direto como
  `ExtracaoObservada.esperado`.
- `campos_a_gravar` (`src/mobia/domain/context/repositorio.py:116`) é a regra única
  compartilhada entre produção e o runner. **`FORA_DE_ESCOPO` devolve dict vazio.**
- `precisao_da_extracao` usa como denominador a união do esperado com o obtido, por
  turno. `faixa_de` levanta `ValueError` quando o total é zero.
- `discrepancias_da_extracao` decompõe o erro em `extra` / `faltou` / `divergiu`, com
  a invariante `acertos + len(discrepancias) == total` guardada por teste.
- 100 turnos sem anotação, assim distribuídos por intenção: COMPRA 30,
  INVESTIMENTO 22, ALUGUEL 19, FORA_DE_ESCOPO 9, INDEFINIDA 9, SUPORTE_CONTRATO 7,
  VENDER_IMOVEL 4.

## Duas premissas do card que a leitura do código derrubou

Estão aqui porque mudam o desenho, e porque quem ler o card depois vai encontrar o
texto antigo.

### O item 3 do escopo não tem trabalho

O card pede *"ajustar `precisao_da_extracao` para que turno negativo entre na conta
com denominador igual ao número de campos inventados"*. A fórmula de união **já faz
isso**: com `esperado = {}`, `set(esperado) | set(obtido)` é `set(obtido)`, então o
denominador é exatamente o número de campos que vieram e os acertos são zero.

Verificado por execução, não por leitura:

| caso | resultado |
|---|---|
| negativo, modelo inventou 2 campos | `0/2`, VERMELHO, duas discrepâncias `extra` |
| negativo, positivo certo ao lado | `1/2`, uma discrepância `extra` |
| invariante `acertos + len(disc) == total` | vale nos dois |

Nenhuma linha de `precisao_da_extracao` muda nesta card. O que impede tudo hoje é só
`carregar` recusar `{}`.

### `borda.yaml` não é onde a invenção é mais perigosa

O card diz para anotar turnos negativos *"incluindo os de `borda.yaml`, onde invenção
é mais provável e mais perigosa"*. São 9 turnos `FORA_DE_ESCOPO` ali — não 12, como
o card afirma — e `campos_a_gravar` devolve dict vazio para `FORA_DE_ESCOPO`.
**Invenção nesses turnos nunca chega a `lead_qualification`.**

O dano que o próprio card descreve — invenção permanente e sem rastro — vem dos
turnos cuja intenção *grava*: 91 dos 100 sem anotação. A seleção desta card inverte a
prioridade do card: os turnos que gravam primeiro, `borda.yaml` como complemento
barato que mede disciplina do modelo sob injeção.

## Decisões

### D1 — `campos: {}` é a superfície, com as bordas fechadas

O card deixa aberto entre `campos: {}` e uma chave própria. Fica `campos: {}`, porque
reusa o campo que já existe e o runner não muda — `if turno.campos is not None` já faz
a coisa certa. Uma chave própria (`nada_afirmado: true`) exigiria recusar combinações
inválidas (`nada_afirmado` junto de `campos` preenchido; `nada_afirmado: false`, que
não significaria nada) e impediria o runner de passar `turno.campos` direto.

Três estados, distinguidos por **presença da chave** e nunca por veracidade do valor:

| YAML | significado |
|---|---|
| chave ausente | fora da medição de extração |
| `campos: {}` | nada afirmado — tudo que vier é invenção |
| `campos: {…}` | anotação completa do que a fala afirma |

Duas proteções, sem as quais a decisão é perigosa:

**`campos:` com valor nulo explícito passa a ser recusado.** Hoje `bruto.get("campos")`
devolve `None` tanto para chave ausente quanto para `campos:` sem valor. Com `{}`
significando o oposto de "não medido", a diferença entre `campos:` e `campos: {}` são
dois caracteres num arquivo editado à mão. `carregar` passa a distinguir com
`"campos" in bruto` e a recusar o nulo explícito, dizendo o que escrever no lugar.

**`TurnoAnotado` ganha `anotado` e `negativo` como propriedades**, e todo chamador
passa a usá-las. Isto não é açúcar: hoje existem quatro testes de verdade diferentes
sobre o mesmo campo, e eles são inócuos só porque `{}` é impossível.

### D2 — Piso próprio para negativos, e não um piso só

`PISO_DE_TURNOS_ANOTADOS` continua contando **só turnos com afirmação**. O valor 30 e
o comentário dele não mudam de sentido.

Nasce `PISO_DE_TURNOS_NEGATIVOS` ao lado, seguindo o padrão que o repo já usa entre
`PISO_DE_TURNOS` e `PISO_DE_TURNOS_ANOTADOS` ("irmão na outra direção"): cada piso
responde uma pergunta distinta — *"sobrou amostra para medir acerto?"* e *"sobrou
amostra para pegar invenção?"* — e cada um falha com a sua própria mensagem.

Contar negativo no mesmo piso o esvaziaria: 30 turnos negativos sem invenção
satisfariam `PISO_DE_TURNOS_ANOTADOS` com denominador zero, e `faixa_de` levantaria
`ValueError` em vez de reportar. É a mesma classe de furo que o piso existe para
fechar, entrando por outra porta.

O número sai do pior caso de abandono, como manda o comentário de
`TETO_DE_CONVERSAS_ABANDONADAS`: **39 negativos**, e as cinco conversas com mais
negativos somam 12, deixando 27 no pior caso. O piso fica em **25**, com folga de
dois. O número é conferido por execução na implementação, e não copiado daqui.

### D3 — Os três pontos de vigilância passam a olhar os dois pisos

Hoje eles usam predicados diferentes sobre o mesmo campo, e isso é inócuo só porque
`{}` é impossível:

| ponto | predicado hoje | com `{}` |
|---|---|---|
| pré-voo, `evals/conftest.py:50` | `if turno.campos` (veracidade) | `{}` não conta |
| CI, `tests/unit/test_evals_corpus_real.py:92` | `if t.campos is not None` | `{}` conta |
| amostra sobrevivente, `_metricas_de` | `len(observadas)`, que usa `is not None` | `{}` conta |

Os três passam a usar `TurnoAnotado.anotado` / `.negativo` e a vigiar os dois pisos.

`_metricas_de` é o que mais muda de sentido: `len(observadas) >= PISO_DE_TURNOS_ANOTADOS`
passaria a se auto-satisfazer com negativos, porque `observadas` agora os inclui. A
guarda tem de contar positivos.

### D4 — Um número no gate, o diagnóstico carregando a separação

Com negativos na conta, `precisao_da_extracao` deixa de responder só *"extraiu certo?"*
e passa a responder *"extraiu certo **e** se absteve de inventar?"*. Fundir causas num
número é exatamente o que o README critica noutro lugar: *"vermelho por 429 e vermelho
por regressão pedem ações opostas, e um relatório que funde os dois faz o leitor
escolher errado."*

Uma métrica `taxa_de_invencao` separada foi considerada e recusada: exigiria um piso
novo **não calibrado**, e o README já tem posição sobre isso — o piso de 50% da
acurácia efetiva foi chamado de andaime e removido assim que houve medição. Criar um
piso de gosto agora repete o que a TEC-210 desfez. E colidiria de nome com o slot
"taxa de alucinação" que o relatório reserva para a TEC-161.

Fica um número só, com o diagnóstico que já existe carregando a separação. O que torna
isso suficiente, e não uma concessão: hoje `extra` é ambíguo — pode ser invenção ou
anotação faltante, e o docstring diz isso. **Num turno negativo, `extra` é invenção sem
ambiguidade**, porque o turno está anotado por completo como vazio. Os negativos não só
entram na conta: eles tornam o diagnóstico capaz de **afirmar** invenção em vez de
suspeitar dela.

`_secao_de_extracao` (`src/mobia/evals/relatorio.py`) passa a informar quantos turnos
negativos entraram e quantas invenções houve neles.

### D5 — 39 turnos, e a regra de seleção é estreita

A regra: **pergunta sobre processo, custo ou serviço da imobiliária não afirma nada
sobre o que o lead procura.**

- **24 em intenções que gravam** — ALUGUEL 7, INVESTIMENTO 6, COMPRA 5,
  SUPORTE_CONTRATO 4, VENDER_IMOVEL 2. São os que medem o dano real:
  *"quanto tempo leva pra aprovar o cadastro?"*, *"precisa de advogado por nossa
  conta?"*, *"qual o yield medio desse tipo de imovel ja alugado?"*
- **6 INDEFINIDA evasivos** — *"oi"*, *"so dando uma olhada"*, *"eae, tudo certo?"*
- **9 FORA_DE_ESCOPO de `borda.yaml`** — os do card, como complemento.

Três turnos ficam de fora **de propósito**, e cada exclusão é uma armadilha real:

- `compra-11` t2 — *"o **sobrado** tem escritura ja regularizada?"*. `sobrado` não está
  em `TipoImovel`, e um modelo que devolve `CASA` está lendo a fala com razão. Anotar
  como negativo puniria isso com força de gate.
- `follow-up-03` t2 — *"documentacao pra baixa do **financiamento**"*. O financiamento
  é o que o lead já tem, não a forma de pagamento que ele pretende usar. A distinção é
  fina de mais para virar negativo.
- `borda-evasivo-02` t1/t2 — *"depois eu vejo com calma"*. A TEC-239 decidiu que isso
  não afirma `SEM_PRESSA`; anotá-lo como negativo afirma o contrário, e com força de
  gate em vez de omissão.

Sobram **61 turnos** fora da medição. Isso fica declarado no README, não escondido: a
card fecha o exploit, não o buraco inteiro.

> **Emenda (TEC-242, 2026-08-29):** a exclusão de `compra-11` t2 acima estava certa
> quando foi tomada — não havia regra que traduzisse `sobrado` para o vocabulário de
> `TipoImovel`, e marcar o turno como negativo teria punido com força de gate um
> modelo que estava lendo a fala com razão. A TEC-242 criou essa regra: `sobrado` se
> anota `CASA` (junto de `kitnet`, `studio`, `flat` e `cobertura`, que se anotam
> `APARTAMENTO`), registrada como regra de anotação no docstring de `TurnoAnotado`
> (`src/mobia/evals/corpus.py`), não em código de tradução — o schema da chamada ao
> modelo é estrito e o modelo já devolve o valor do enum sozinho. Com a regra em
> vigor, `compra-11` t2 saiu da lista de exclusões acima: hoje é anotado
> `campos: {tipo_imovel: CASA}` e conta como acerto, não mais como turno fora da
> medição. O argumento original — *"um modelo que devolve `CASA` para 'sobrado' está
> lendo a fala com razão"* — não foi derrubado; é exatamente o que a nova regra
> formaliza. Este parágrafo original não foi reescrito: a decisão estava certa quando
> foi tomada, e a emenda é para que a história continue legível.

> **Emenda (TEC-245, 2026-08-29):** as duas exclusões que sobraram aqui depois
> da emenda acima — `follow-up-03` índice 2 e `borda-evasivo-02` índices 1 e 2,
> três turnos — **continuam valendo**. A TEC-245 as confirmou em vez de
> substituí-las: ela passou as 56 falas que ainda estavam fora da medição pelo
> critério que essas próprias exclusões já traziam implícito — o que exclui não
> é ser pergunta, é a fala **pressupor** um campo sem afirmá-lo, ou sugerir um
> valor sem nomeá-lo —, e as três chegaram do outro lado intactas. O que mudou
> é o entorno delas. Este parágrafo dizia que sobravam 61 turnos fora da
> medição e que isso ficaria declarado no README em vez de escondido; ficou,
> mas o README ia além e chamava os turnos sem exclusão escrita de *"trabalho
> de anotação que ainda não foi feito, não decisão tomada"*. Ler as 51 falas
> sem exclusão uma a uma derrubou essa frase: a maioria era pergunta de
> processo dirigida ao corretor, a mesma forma que o corpus já anotava `campos:
> {}` em turnos irmãos das mesmas conversas. Faltava o critério escrito, e não
> o trabalho. Depois da triagem são **17 turnos fora da medição** — as três
> exclusões acima, mais `aluguel-09` índice 2 e `follow-up-03` índice 1 de uma
> revisão posterior a esta card, mais as doze da TEC-245 —, cada um com o
> motivo em uma linha, e o conjunto deixou de ser aberto: `_FORA_DA_MEDICAO`
> (`tests/unit/test_evals_corpus_real.py`) o declara por inteiro, e turno novo
> sem `campos` quebra o CI até alguém decidir. A conta do "Contrato depois da
> card" logo abaixo — 38 positivos, 39 negativos, 61 fora — não foi reescrita:
> é o registro do que **esta** card entregou. O corpus de hoje está em 55
> positivos, 66 negativos e 17 fora, e quem quiser o número atual lê o README,
> não este spec.

## Contrato depois da card

- 138 turnos: **38 positivos + 39 negativos = 77 medidos**, 61 fora.
- `precisao_da_extracao` inalterada; passa a receber os negativos via runner.
- Dois pisos, vigiados nos mesmos três pontos.
- Invariante `acertos + len(discrepancias) == total` preservada — vem de graça, porque
  as duas funções derivam da mesma união.

## Testes

Em ordem de TDD:

1. `carregar` aceita `campos: {}`; recusa `campos:` nulo explícito com mensagem que diz
   o que escrever no lugar.
2. `TurnoAnotado.anotado` e `.negativo` nos três estados.
3. Os dois pisos, nos três pontos de vigilância.
4. **O teste que o card pede por nome:** um modelo que inventa campos em turnos
   negativos **não** tira 100%. Hoje ele tiraria.
5. O corpus commitado tem os negativos, e um piso deles.
6. `_secao_de_extracao` reporta negativos e invenções neles.
7. `precisao_da_extracao` com total zero levanta — quem protege contra o corpus
   só-negativo é `PISO_DE_TURNOS_ANOTADOS`, e isso vale um teste em vez de ficar
   implícito.

## Fora de escopo

- Os 61 turnos restantes sem anotação.
- A decisão D4 da TEC-145 (sobrescrita sem histórico).
- O piso de 85% e a fórmula de `precisao_da_extracao`.
- Cobertura por valor de vocabulário, lacuna que a TEC-239 declarou e não fechou.
