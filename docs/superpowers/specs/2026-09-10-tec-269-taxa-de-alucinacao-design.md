# TEC-269 — Medir a taxa de alucinação no gate de avaliação

**Status:** desenhado em 2026-09-10 na branch `feat/tec-269-taxa-de-alucinacao`.

**Card:** [TEC-269](https://eduardodurieuxlopes.atlassian.net/browse/TEC-269) — Must (MoSCoW), prioridade Highest herdada da TEC-210. Origem: RNF-26, RN-09.4 (SRS v1.0); RT-01, seção 4.4 (E9). Épico [TEC-208](https://eduardodurieuxlopes.atlassian.net/browse/TEC-208).

**Desbloqueada pela [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161)**, mergeada em `main` como `fcafa95`. **Completa a [TEC-210](https://eduardodurieuxlopes.atlassian.net/browse/TEC-210)**, que declarou esta métrica e ficou Feito sem ela.

## Objetivo

A taxa de alucinação deixa de ser um slot vazio no relatório do gate e passa a ser um número medido, para que o RT-01 pare de ser mitigado por um mecanismo que ninguém consegue provar que funciona.

## O estado de hoje, medido

Execução manual do gate na `main` em 10/09/2026 (run `34461117126`, `success`, 0 conversas abandonadas, corpus de 53 conversas e 147 turnos):

```
- **acuracia de intencao**: VERDE -- 145/147 (98.6%), alvo 90%, piso 84%
- **acuracia efetiva**:     VERDE -- 143/147 (97.3%)
- **precisao da extracao**: AMARELO -- 90/101 (89.1%), alvo 90%, piso 85%
- **taxa de alucinacao**:   SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**:     AMARELO -- 144/147 (98.0%), alvo 98%, piso 90%
```

- A linha do `sem_mecanismo` é literal em `evals/test_acuracia_de_intencao.py:373`, e cita como bloqueadora uma card que já está em `main`.
- **O eval não roda o turno.** `evals/conftest.py` explica por quê: o conftest de `tests/` tem `migrar_banco` e `banco_limpo` como `autouse`, então qualquer arquivo sob `tests/` exigiria Postgres. O eval monta `ContextoMontado` direto e chama `await classificador.classificar(contexto)` (`test_acuracia_de_intencao.py:188`), **sem `porta=`**.
- Logo `RespostaDoAgente.candidatos` é `[]` em todo turno do corpus.
- **A faixa que a guarda vê vem do que o modelo extraiu, não da anotação do corpus.** O corpus anota `faixa_preco_max: 600000` em reais e `corpus.py:22-23` converte para `faixa_preco_*_centavos` no carregamento — mas essa anotação alimenta `esperado_acumulado`, que serve só a métrica de extração, e nunca chega a `estado_acumulado`. Quem alimenta `estado_acumulado` é `campos_a_gravar(resposta.intencao, resposta.extracao)`, a extração que o **modelo** devolveu naquele turno; é esse dicionário que vira `LeadQualification(**estado_acumulado)` e é o que `_faixa_declarada` lê em produção.
- `divergencias_de` (`domain/agente/citacao.py`) é puro e importável — sem I/O, sem banco, sem chamada ao modelo. Foi desenhado assim na TEC-161 (D1) justamente para poder ser chamado fora do turno.
- **"invenção" já está ocupado neste módulo.** `com_invencao` (`metricas.py:766`) conta campo de extração inventado em turno negativo, e entra no denominador da precisão da extração. É outro conceito.
- `faixa_de(acertos, total, ...)` é **quanto maior melhor** (`metricas.py:250`), e o relatório renderiza apenas o `detalhe`.

## Decisões

### D1 — Mede invenção sem busca, e diz isso no nome

Com `candidatos=[]` em todo turno, o que a métrica detecta é: **o agente citou cifra ou código sem ter buscado nada**. Num corpus em que nenhuma busca acontece, citar preço de imóvel é invenção por construção. É o RT-01 no estado mais puro, e é exatamente a lacuna 3 que a TEC-265 deixou aberta de propósito.

A alternativa considerada e recusada foi injetar uma **porta de busca dublê** com catálogo fixo — sem Postgres, sem embedding, sem custo — para o corpus exercitar tool use e a guarda receber candidatos de verdade. Ela mede a forma de produção ("o modelo buscou, viu três imóveis e citou um quarto"), que é mais próxima do RT-01 real. Foi recusada por escopo: exige turnos de corpus que provoquem busca e um catálogo de fixture, muda o que as outras quatro métricas medem, e transformaria uma card de instrumentação numa card de corpus. Fica registrada como lacuna, não como esquecimento.

### D2 — Reusa `divergencias_de`; o piso passa a ser versionado com o detector

Uma única definição de "alucinação" no repo. O eval importa a mesma função que a guarda usa em produção, e não uma cópia — a gramática gêmea é o defeito que a TEC-161 recusou três vezes dentro da própria branch.

**Consequência declarada, e ela é desconfortável:** alargar a gramática da guarda faz o número **subir**. Um detector melhor encontra mais alucinação, e um gate ingênuo reprovaria a card que melhorou a guarda. O piso, portanto, não é uma propriedade do modelo: é uma propriedade do par modelo-detector.

O tratamento é o mesmo que o teto do orçamento do prompt já usa neste repo: o piso é um número **fixo, escrito à mão num lugar só**, e a docstring guarda o histórico de cada vez que ele se moveu e por quê. Quem alargar a detecção da TEC-161 re-mede o piso na mesma card, e o ritual é o mesmo — a pergunta é "o número subiu porque o modelo piorou ou porque o detector melhorou?" antes de "quanto subo o piso?".

### D3 — A faixa vem depois da extração do turno, como em produção

Em produção a guarda roda depois de `gravar_estado`, e lê `_faixa_declarada(depois_do_estado or contexto.estado)` — a faixa **inclui** o que o turno corrente acabou de extrair. No eval, o equivalente é coletar a observação depois de `estado_acumulado.update(campos_do_turno)`, que já acontece antes de `respostas.append(...)` no laço.

Coletar antes inverteria o sentido do teste: um lead que diz "até R$ 600 mil" e recebe o eco na resposta do mesmo turno seria contado como invenção. É exatamente o falso positivo que a D5 da TEC-161 existe para impedir, e reintroduzi-lo aqui mediria o oposto do que a métrica promete.

### D4 — O nome carrega o escopo: `taxa de alucinacao (cifra e codigo)`

Mantém a palavra da RNF-26 e da TEC-210 — quem audita o requisito acha a linha pelo nome que procurou — e o parêntese mata o overclaim.

A guarda cobre cifra e código. **Não** cobre paráfrase: *"tenho um bem espaçoso na praia"* sobre imóvel inexistente passa, e a lacuna 1 da TEC-161 declara isso. Sem o qualificador, um VERDE nessa linha diria a quem audita o RT-01 que toda alucinação está coberta, e não está.

`turnos sem invencao` foi considerado e recusado: colide com o `com_invencao` que já existe no mesmo módulo e no mesmo relatório, com outro significado.

### D5 — Conta turnos limpos por dentro, reporta a taxa por fora

`faixa_de` é quanto-maior-melhor, então `acertos` conta **turnos sem divergência**. O relatório renderiza só o `detalhe`, que diz a taxa na direção que a RNF-26 pede:

```
- **taxa de alucinacao (cifra e codigo)**: VERDE -- 2/147 turnos com cifra
  sem base (1.4%), alvo <2%, piso <50% (andaime)
```

O `<50%` acima é ilustrativo e é **andaime**, não medida — ver a D6. O valor exato entra na implementação e é escolhido para não poder reprovar antes de existir medição.

A inversão entre o campo interno e o texto renderizado é deliberada e fica comentada no código. Sem isso, a linha exibiria "98,6%" ao lado da palavra "alucinação".

**Por turno e não por divergência**, pela mesma razão que `aderencia_ao_tom` conta por resposta: o lead vive o turno, e um turno que inventa dois preços é um turno ruim, não dois.

### D6 — Piso-andaime primeiro, piso medido depois

A RNF-26 pede `< 2%`. O `alvo` entra como 2% desde já; o **piso** entra como andaime, baixo demais para reprovar, e é substituído por um piso medido quando houver execuções.

É literalmente o que a aderência ao tom fez: o comentário em `test_acuracia_de_intencao.py` registra "piso medido pela TEC-255 (90) e alvo proprio (98), que substituiram o piso-andaime de 50 quando a aderencia foi medida". Gatear em 2% na primeira execução seria gatear em ruído — o próprio relatório avisa que duas execuções do mesmo código já diferiram 5,7 pontos noutra métrica.

**Isto não é emenda ao SRS.** A RNF-26 dá o **alvo**, e o alvo entra como 2%. `alvo` e `piso` são coisas distintas neste repo desde a TEC-210, e nenhuma regra do SRS fixa piso de bloqueio.

### D7 — Sem amostra, volta para `sem_mecanismo`

Se não houver turnos medidos, a métrica cai em `sem_mecanismo` com o motivo escrito, como `precisao da extracao` e `aderencia ao tom` já fazem. Nunca em verde: o docstring de `sem_mecanismo` já diz por quê — slot que reporta verde sem medir some do radar e finge cobertura.

### D8 — Onde o código mora

- `InvencaoObservada` e `taxa_de_alucinacao()` em `src/mobia/evals/metricas.py`, no molde de `RespostaObservada` e `aderencia_ao_tom`.
- A coleta no laço de `evals/test_acuracia_de_intencao.py`, ao lado de `respostas.append(...)`.
- A troca do `sem_mecanismo("taxa de alucinacao", ...)` na montagem da lista de métricas.

`InvencaoObservada` carrega as divergências e não só a contagem, para que uma futura seção de diagnóstico do relatório possa renderizá-las — mas essa seção **não existe** nesta card. Hoje `divergencias` só é lido por dois testes unitários; `taxa_de_alucinacao()` conta por turno e nunca repassa o campo para `render`, então descobrir qual foi a divergência de um turno específico ainda exige outra execução paga. É diferente de `ViolacaoDeFormato`, que carrega o mesmo tipo de detalhe e ele chega ao relatório de verdade.

## Fluxo

```
para cada turno do corpus:
  classificar(contexto)            # sem porta: candidatos = []
  estado_acumulado.update(...)     # a faixa do lead passa a incluir este turno
  divergencias_de(
      resposta.resposta,
      candidatos=resposta.candidatos,          # []
      faixa=(min, max de estado_acumulado),
  )
  -> InvencaoObservada(conversa, indice, divergencias)

no fim:
  taxa_de_alucinacao(invencoes)  ->  ResultadoDaMetrica
```

## Testes

Unitários, sem rede e sem banco, em `tests/unit/` (não em `evals/`, que é o gate pago):

- Turno com cifra fora da faixa conta como invenção; dentro da faixa, não.
- Turno sem cifra nenhuma conta como limpo.
- Contagem **por turno**: duas divergências no mesmo turno contam uma vez.
- Sem amostra devolve `sem_mecanismo`, nunca verde.
- A borda do piso e a do alvo, nos dois lados, em aritmética inteira.
- Um teste que trava a D3: a faixa usada é a de **depois** da extração do turno.

## Emendas ao SRS

**Nenhuma.** A RNF-26 dá o alvo (`< 2%`) e a métrica entra com ele. O piso-andaime é decisão de implementação sobre quando gatear, e o SRS não fixa piso de bloqueio.

## Lacunas declaradas

1. **Não mede o caminho com candidatos** — a forma de produção em que o modelo busca, recebe até 10 imóveis e cita um décimo primeiro. É a D1, recusada por escopo, e é a metade do RT-01 que continua sem medição.
2. **O número só é comparável dentro da mesma versão do detector** (D2).
3. **Herda as cinco lacunas da TEC-161**: paráfrase sem número passa, a tolerância de 10% é uma janela real, o formato de código é o do seed, bairro e título não são validados, e a guarda não obriga o modelo a buscar.
4. **O piso da primeira entrega é andaime, não medida** (D6). Até ele ser substituído, a métrica reporta e não protege.
5. **Só o orçamento que o modelo extraiu absolve uma cifra citada, não o que o lead declarou.** `estado_acumulado` vem de `campos_a_gravar(resposta.intencao, resposta.extracao)` — a extração do **modelo** —, e não da anotação do corpus (ver "O estado de hoje, medido", acima). A precisão de extração medida neste corpus roda em 89–92%: num turno em que o lead diz "até R$ 600 mil", o modelo ecoa o número (que `montar_contexto` instrui a fazer) e a extração falha em capturá-lo, a métrica registra uma alucinação que não é uma. **Isto não é um defeito de fidelidade contra produção** — a guarda de produção também lê o estado extraído pelo modelo, nunca o que o lead declarou —, mas infla a taxa medida neste corpus por uma quantidade desconhecida, e sem uma seção de diagnóstico que renderize `InvencaoObservada.divergencias` (que ainda não existe — ver o docstring da classe) hoje não há como distinguir, num turno específico, um acerto genuíno de um falso positivo de extração.

## Fora de escopo

- **Alterar a guarda da TEC-161.** Esta card mede; não muda o que é detectado.
- **Trazer Postgres ou Redis para o gate pago**, que é a razão de `evals/` ficar fora de `tests/`.
- **Fazer o `< 2%` virar gate duro** antes de o piso ser medido (D6).
- **A porta de busca dublê e os turnos de corpus que a exercitariam** (D1) — se virar card, é card de corpus, não de instrumentação.
