# TEC-148 — Respeitar recusa de campo sem reperguntar

**Status:** desenhado em 2026-09-03. Não implementado.

**Card:** [TEC-148](https://eduardodurieuxlopes.atlassian.net/browse/TEC-148) — Should (MoSCoW). Origem: RF-05, RN-05.7 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Destravada pela [TEC-145](https://eduardodurieuxlopes.atlassian.net/browse/TEC-145)**, que está Feito. Vizinha da [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149), que mexe no mesmo território de escolha de pergunta.

## Objetivo

A história é da Marina, que não quer falar de dinheiro logo na primeira conversa: *"quero que o atendimento aceite meu 'prefiro não dizer agora', para não ser pressionada a cada mensagem"*.

**O que esta card entrega:** o estado `recusado`, distinto de vazio, e as três consequências dele — o agente não repergunta, o lead não conta como qualificado sobre um campo que recusou, e o score para de pontuar esse campo.

## O que já existe, e que o desenho reusa

**O consumidor está pronto e vazio.** `esta_qualificado(estado, recusados)` recebe o conjunto por parâmetro desde a TEC-147, com a docstring dizendo *"quem grava recusa e a TEC-148, que ainda nao existe"*. Esta card é quem preenche.

**A maquinaria de marca da TEC-257**, que é o molde exato: `perguntados_sem_resposta` é `ARRAY(String(32))` nulável em `lead_qualification`, gravado por união em SQL, com `NULL` e `{}` significando coisas diferentes. A coluna nova copia essa forma linha por linha.

**A tradução de nome do orçamento.** `_canonico` em `qualificacao.py` resolve por prefixo os seis nomes que `faixa_preco` tem neste repo, e existe porque a TEC-146 gastou uma card inteira num bug silencioso causado por dois lugares guardando o mesmo fato sob nomes diferentes.

**O relato do modelo sobre o próprio turno.** `perguntou` já é um array de string em `SCHEMA_DA_RESPOSTA` que o modelo preenche dizendo o que perguntou, com `_perguntou` que **nunca levanta** — é o modelo relatando o que ele mesmo fez, e uma forma errada não pode custar um turno já pago que já tem resposta válida para o lead. `recusou` copia essa postura.

**A cláusula do prompt que já cobre o caso.** `SISTEMA_DO_AGENTE` diz *"nao repergunte o preenchido nem o ignorado"*. A TEC-257 chegou nessa forma encurtando a cláusula anterior por +0,75 token, depois de a forma explícita — que custava 3,25 — ser recusada por não deixar folga para ninguém depois.

## Decisões

### D1 — A recusa mora numa coluna nova, no molde da marca

Migration `0013`, em `lead_qualification`:

```python
campos_recusados: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), nullable=True)
```

**O nome vem do SRS**, que já o fixou no modelo de dados: `campos_recusados | text[] | Não | RN-05.7`. O repo divergiu daquela tabela em vários pontos — `regiao` é `String(120)` e não `regioes text[]`, a urgência é faixa e não `urgencia_dias`, e `completude_pct` nunca existiu porque a TEC-147 decidiu derivar em vez de gravar —, mas cada uma dessas divergências foi decisão desenhada. Aqui não há razão para divergir, e o nome do SRS é mais descritivo que um `recusados` pelado. **O parâmetro que `esta_qualificado` já expõe continua sendo `recusados`**, que a TEC-147 escolheu; coluna e parâmetro não precisam ter o mesmo nome, e renomear a assinatura dela seria mexer em card entregue.

**`NULL` e `{}` não são sinônimos**, pela razão que a TEC-257 documentou para a coluna vizinha: `NULL` é *"linha anterior a esta card, ninguém registrava"* e `{}` é *"registrava, e não havia recusa"*. Quem lê trata os dois igual (`or ()`); quem grava nunca escreve `NULL` querendo dizer vazio. Sem essa distinção, uma linha antiga e uma linha nova sem recusa ficariam indistinguíveis, e a próxima card que precisar saber "este lead já foi avaliado para recusa?" não teria como.

**Em claro, como o resto da tabela.** É o que o sistema concluiu, não o que o lead escreveu — a mesma assimetria que a TEC-126 estabeleceu ao cifrar o resumo e deixar `lead_qualification` legível.

**Coluna nova e não reuso de `perguntados_sem_resposta`.** Recusa e silêncio são fatos diferentes com consequências diferentes: silêncio significa *"pode ser que ele responda depois"* e recusa significa *"ele disse que não"*. Colapsá-los tornaria permanentemente inqualificável todo lead que apenas ainda não respondeu — e `_texto_do_estado` faz *"valor vence marca"*, então um campo recusado com valor de um turno anterior renderizaria o valor e a recusa ficaria invisível para quem lê o estado.

### D2 — O escopo é o lead, e o cenário 4 fica para depois

A card diz *"conversa nova do mesmo lead pode perguntar de novo — a recusa vale para a conversa, não para sempre"*. **Não há fronteira de conversa neste repo:** `conversation_key` é o id externo do lead, invariante à direção — está escrito no comentário de `optout/models.py` —, e `messages`, `lead_qualification`, `conversation_summaries` e `optout_events` todos o usam com esse sentido.

**A recusa vale para o lead**, e o cenário 4 fica **deferido, não recusado** — decisão do usuário em 03/09/2026. Implementá-lo exige introduzir uma entidade de conversa e reinterpretar `conversation_key` em cinco tabelas que meia dezena de cards já entregues assume, o que é maior que esta card inteira. Quem for pegar isso encontra aqui o que custa.

**A direção do erro é deliberada.** Recusa que vale para sempre erra para "nunca mais perguntar", que incomoda menos o lead do que reperguntar — e a própria card avalia o contorno de não detectar como *"incomoda e aumenta abandono, mas não trava o atendimento"*.

### D3 — O modelo relata a recusa, e o campo novo vai no fim do schema

`recusou`, array de string em `SCHEMA_DA_RESPOSTA`, mesma forma de `perguntou`.

**Por que o modelo e não um detector determinístico.** O precedente barato existe e é bom — `optout/deteccao.py` detecta opt-out em duas faixas de termos, sem custo de prompt — mas resolve um problema mais fácil: opt-out tem objeto fixo (*"mensagens"*), e é o objeto que fecha a colisão. Recusa não tem objeto próprio: ela se refere ao que acabou de ser perguntado, e a distinção que importa não é lexical — *"prefiro não dizer"* é recusa, *"não sei ainda"* não é.

**E a direção do erro caro é o inverso do opt-out.** A docstring de `optout/deteccao.py` explica que lá deixar de detectar é violação de LGPD e detectar demais é prejuízo comercial, e por isso a faixa inequívoca é generosa. Aqui: detectar recusa que não houve faz o agente parar de perguntar um campo obrigatório, `esta_qualificado` devolve False para sempre e o lead nunca chega ao corretor — **em silêncio**. Deixar de detectar apenas repergunta. Uma lista de palavra-chave erra exatamente no lado caro, e o repo já tem o registro de um proxy lexical mal-comportado: `MARCADORES_DE_REPERGUNTA`, nos evals, é documentado como *"proxy ininterpretável"* com falso positivo e falso negativo por construção.

**Custa 13,25 tokens, e o teto de 655 não se move.** O líquido medido em 03/09 é 631,2; com o campo novo vai a 644,45, e `test_a_margem_do_orcamento_do_prompt_e_deliberada` continua com o mesmo teto. **A margem cai de 23,8 para 10,55**, e é isso que a próxima card que tocar o prompt herda.

Dois detalhes que os comentários do classificador tornam obrigatórios:

- **`_ORDEM_DOS_CAMPOS` tem de acompanhar.** A verificação que compara os dois é guarda de import que levanta `RuntimeError`, e não `assert`, precisamente porque `python -O` removeria o assert e a reordenação descartaria o campo novo em silêncio.
- **`recusou` entra no fim, depois de `perguntou`.** A TEC-240 recusou reordenar campos do schema mesmo a custo zero de tokens, porque muda a ordem de geração do modelo num caminho pago em todo turno de produção, numa card sem instrumento para medir o efeito. Acrescentar no fim é a única posição que não mexe na ordem do que já existe.

**`_recusou` nunca levanta e não valida os nomes**, como `_perguntou`. Quem filtra contra `fields(Extracao)` é uma função só — duas filtragens divergiriam, e a divergência só apareceria na borda.

### D4 — O prompt não ganha texto novo, e não é sorte

A cláusula *"nao repergunte o preenchido nem o ignorado"* já cobre recusa, porque **o campo recusado já vem marcado por outro caminho.** A sequência é: no turno N o agente pergunta o orçamento e `perguntou` marca `faixa_preco_max`; no turno N+1 o lead recusa. Quando a recusa é relatada, `(perguntado, sem resposta)` já está no estado desde o turno anterior.

Então `_texto_do_estado` não muda e o custo em tokens é zero além dos 13,25 da D3.

**Consequência declarada: "valor vence marca" continua valendo.** Um campo recusado que tenha valor de um turno anterior renderiza o valor, e o modelo pode usá-lo na conversa. A consequência de qualificação é resolvida em código (D5), não no prompt. Isso é aceito: o lead recusou *dizer* o valor agora, e usar um que ele já disse antes não é pressioná-lo.

### D5 — O score fecha a divergência que a TEC-150 declarou

`calcular_score` passa a receber `recusados`, **keyword-only**, depois do `*` que já existe, e `campos_obrigatorios_preenchidos` para de contar campo recusado. Keyword-only por consistência com os dois parâmetros vizinhos, cuja docstring explica que a posição deles é keyword-only porque dois `int` adjacentes com o mesmo default trocariam de lugar sem o mypy ver — `recusados` não corre esse risco por ser de outro tipo, mas misturar as duas convenções na mesma assinatura convida ao erro na próxima.

A TEC-150 deixou isso escrito de propósito: *"a card não menciona recusa em nenhuma das cinco regras nem em nenhum critério de aceite, e acrescentar o parâmetro seria estender o contrato por simetria em vez de por pedido. Mas a divergência é real e quem for reconciliar precisa achá-la escrita."* Enquanto ninguém preenchia `recusados`, a divergência era teórica. A partir desta card deixa de ser, e é esta card que reconcilia — decisão do usuário em 03/09/2026.

Sem isso, `esta_qualificado` e o score contariam histórias contrárias sobre o mesmo lead: não-qualificado e pontuando os 5 pontos de completude do campo que recusou, com a TEC-151 ordenando a fila por um número que a qualificação contradiz.

**Consequência que aparecerá como regressão e não é.** O score de todo lead que já tenha recusado campo **cai** quando isso entrar, e a trilha da TEC-152 registra a queda com causa `CAMPOS_OBRIGATORIOS`. É a auditoria funcionando — o fator mudou porque a regra mudou —, mas quem olhar a fila verá leads descendo sem mudança de fala. Tem de estar no PR.

## Fluxo

1. O modelo devolve `recusou` junto de `perguntou`, `intencao`, `confianca`, `extracao` e `resposta`.
2. `_recusou` normaliza a forma sem levantar e sem validar nomes.
3. `campos_a_recusar(recusou, preenchidos)` decide o que acrescentar: os nomes canônicos que o modelo relatou, **menos** os que este turno preencheu. É a regra do cenário 2 da card, e mora ao lado de `campos_a_gravar` e `campos_a_marcar` porque o runner do eval precisa das três.
4. `gravar_estado` acrescenta por **união em SQL** e remove o que chegou com valor. A união mora no SQL pela mesma razão que a de `perguntados_sem_resposta`: dois turnos concorrentes da mesma conversa leriam o mesmo array, cada um uniria o seu, e o mais lento sobrescreveria em silêncio — perda que não aparece em teste nenhum.
5. `esta_qualificado(estado, frozenset(estado.campos_recusados or ()))` e `calcular_score(..., recusados=frozenset(estado.campos_recusados or ()))` leem a coluna. **`frozenset` e não `set`:** a assinatura que a TEC-147 escreveu é `recusados: frozenset[str] = frozenset()`, e passar `set` reprova no mypy. E `or ()` porque `NULL` e `{}` são lidos igual (D1).

**Sobre os três nomes, que não são inconsistência para "consertar".** `recusou` é o campo do schema — o modelo relatando o que fez neste turno. `campos_recusados` é a coluna, que acumula, e o nome vem do SRS. `recusados` é o parâmetro que `esta_qualificado` já expõe desde a TEC-147. O par evento/estado espelha `perguntou` / `perguntados_sem_resposta`, que já existe pelas mesmas razões.

**Os nomes passam por `_canonico` antes de qualquer comparação**, e é a parte que já custou uma card a este projeto. O orçamento tem seis nomes; a coluna grava sob o mesmo que `CAMPOS_OBRIGATORIOS` usa, e um teste pina os dois lados.

## Testes

**Unitários:**

- `campos_a_recusar` isolado: acréscimo, subtração pelo valor deste turno (cenário 2), nome do orçamento em qualquer das seis formas.
- `_recusou` com forma inválida — string em vez de lista, número, `None` — não levanta e devolve tupla vazia.
- `esta_qualificado` com campo recusado que **tem** valor na coluna devolve False. É o caso que distingue esta card do marcador da TEC-257.
- `calcular_score` com campo recusado não pontua a completude dele, e o total cai exatamente 5.
- **O orçamento do prompt:** `test_a_margem_do_orcamento_do_prompt_e_deliberada` continua com teto 655, e a docstring dele registra a passagem de 631,2 para 644,45 e a margem de 10,55 — o ritual do repo é que a docstring guarde o histórico de cada vez que o número se mexeu, mesmo quando o teto não muda.
- `_ORDEM_DOS_CAMPOS` cobre exatamente as chaves de `SCHEMA_DA_RESPOSTA`, que a guarda de import já verifica — o teste garante que a guarda é alcançada.

**Integração:**

- O turno grava a recusa relatada pelo modelo.
- Valor posterior desfaz a recusa e o campo volta a contar (cenário 2).
- Dois turnos concorrentes da mesma conversa não perdem recusa — a união em SQL.
- `NULL` e `{}` lidos igual.
- `upgrade` e `downgrade` da `0013`.

TDD, e cada teste verificado por mutação: trocar a subtração por união em `campos_a_recusar` tem de deixar vermelho exatamente o teste do cenário 2. Nas cards anteriores, toda rodada de revisão perdida foi teste que passava com o código certo ou errado.

## Emenda ao SRS

A **RN-05.7** diz, literalmente, que o campo recusado *"não é reperguntado na mesma conversa"*. A D2 entrega recusa com escopo de lead, então isto é desvio da regra e não interpretação dela. Entra em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` como item aninhado sob a RN-05.7, sem tocar o texto de 22/08. A regra não tem emenda hoje, logo é `E-01`:

> **Emenda E-01 (TEC-148, 03/09/2026)** — a recusa vale para o **lead**, e não para a conversa. Não há fronteira de conversa no sistema: `conversation_key` é o id externo do lead, e `messages`, `lead_qualification`, `conversation_summaries` e `optout_events` todos o usam com esse sentido. Introduzir a entidade de conversa é maior que esta card, e fica deferido. A consequência é que o campo recusado não é reperguntado **nunca**, e não só na conversa corrente — erro na direção de não incomodar o lead.

## Lacunas declaradas

**O cenário 4 fica para depois.** Ver D2 e a emenda acima. Recusa vale para o lead, não para a conversa, porque não há conversa no schema. Deferido pelo usuário, não recusado.

**Quem decide recusa é o modelo, e não há guarda em código contra recusa inventada.** É o erro caro desta card: um falso positivo faz o agente parar de perguntar um obrigatório e `esta_qualificado` devolver False para sempre, sem log de alarme e sem o lead perceber. Ao contrário do opt-out, cuja detecção é determinística e testável sem modelo, aqui a única defesa é a medição de acurácia dos evals — e nenhum turno do corpus anota recusa hoje.

**O corpus não tem caso de recusa.** A medição de extração dos evals não cobre este campo, então a acurácia do `recusou` não é medida por nada. Anotar recusa no corpus é trabalho de outra card, e sem isso o falso positivo acima não tem instrumento.

**A margem do prompt cai para 10,55 tokens.** Quem for alongar o prompt ou mexer no schema depois desta card herda isso, e a pergunta continua sendo *"o que sai para o novo texto entrar?"*.

**A TEC-149 mexe no mesmo território.** Não há seletor de próxima pergunta em código — a escolha é do modelo, guiada pelo prompt, e o desenho da TEC-145 registra que TEC-148 e TEC-149 reescreveriam o mesmo seletor. Esta card não cria seletor; ela subtrai do que o modelo pode perguntar.

**Recusa não é opt-out.** Recusar um campo não silencia o contato, e a card diz isso explicitamente. As duas maquinarias não se falam.

## Fora de escopo

- Fronteira de conversa e o cenário 4 — ver D2.
- O teto de 8 perguntas e a oferta do corretor — [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149).
- Opt-out de comunicação — épico E6, já entregue pela [TEC-182](https://eduardodurieuxlopes.atlassian.net/browse/TEC-182). A card diz explicitamente que é recusa do contato inteiro, não de um campo.
- Anotar recusa no corpus de avaliação — ver lacunas.
