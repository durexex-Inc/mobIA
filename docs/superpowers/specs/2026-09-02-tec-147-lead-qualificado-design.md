# TEC-147 — Determinar quando o lead está qualificado

**Status:** desenhado em 2026-09-02. Não implementado.

**Card:** [TEC-147](https://eduardodurieuxlopes.atlassian.net/browse/TEC-147) — Must (MoSCoW). Origem: RF-05, RN-05.3 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Destravada pela [TEC-146](https://eduardodurieuxlopes.atlassian.net/browse/TEC-146)**, que era sua única bloqueadora e está Feito. Bloqueia a [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150) (lead score), que por sua vez bloqueia TEC-151 e TEC-183.

## Objetivo

O produto promete que *"o corretor só recebe o lead depois de qualificado"*. Hoje não existe a noção de qualificado: `lead_qualification` acumula campos e ninguém pergunta se já bastam.

**O que esta card entrega:** a regra que decide, os campos que ela olha, e o evento de transição. Nada mais.

## O que já existe, e que o desenho reusa

**Os quatro campos obrigatórios da RN-05.3 já existem e já são preenchidos.** `intencao`, `faixa_preco_min_centavos`/`faixa_preco_max_centavos`, `regiao` e `urgencia` são colunas de `lead_qualification`, alimentadas por `campos_a_gravar` desde a TEC-145 e normalizadas em centavos desde a TEC-146.

**`perguntados_sem_resposta` é o irmão próximo da recusa.** A TEC-257 construiu a marca *"perguntei, não respondeu"* como `text[]` em `lead_qualification`. Recusa (RN-05.7) é *"perguntei, disse que não quer dizer"* — mesma forma, outro significado, e é a [TEC-148](https://eduardodurieuxlopes.atlassian.net/browse/TEC-148) que a grava.

## Decisões

### D1 — Função derivada, sem coluna de status

`esta_qualificado` é função pura sobre os campos, em `src/mobia/domain/context/qualificacao.py`:

```python
def esta_qualificado(
    estado: LeadQualification | None,
    recusados: frozenset[str] = frozenset(),
) -> bool
```

Sem I/O, sem banco, sem migração. Vizinha de `montagem.py` e `repositorio.py`, que já operam sobre `LeadQualification`.

**A alternativa era gravar `status`**, alinhando desde já com o funil de seis etapas da RN-17.2 (Novo → Em conversa → Qualificado → Recomendado → Agendado → Handoff aceito). Foi recusada porque, das seis, "Qualificado" é a única que é **função pura de dados que já temos** — as outras cinco são dirigidas por evento e não têm nada que as escreva ainda. Uma coluna com um valor em uso e cinco esperando cards futuras é uma segunda fonte para um fato que já tem uma, e fonte duplicada diverge.

Isso não é preocupação teórica neste repo: a TEC-146 gastou uma card inteira num bug silencioso — `MARCADORES_DE_REPERGUNTA` guardando `"faixa_preco_max"` enquanto `Extracao` produzia `faixa_preco_max_centavos` — causado exatamente por dois lugares guardando o mesmo fato sem nada amarrando os dois.

**Quando a coluna vier, ela virá por um estado que não deriva de campo nenhum:** o `DORMENTE` da RN-13.5 ([TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187)), que nasce de tentativas de contato esgotadas. Essa card paga a migração e reconcilia; esta não precisa antecipá-la.

### D2 — Quais intenções podem qualificar, e por que a card sozinha não responde

Só `COMPRA`, `ALUGUEL` e `INVESTIMENTO`.

A RN-05.3 diz apenas *"intenção + faixa de preço (ou ticket) + região + urgência"*. Lida ao pé da letra, qualquer intenção com os quatro campos preenchidos qualifica. **A RN-03.4 do mesmo SRS diz o contrário para dois casos:** *"`VENDER_IMOVEL` e `SUPORTE_CONTRATO` não são qualificados pelo SDR — vão direto para a fila de handoff com a etiqueta correspondente."* Os quatro campos podem perfeitamente estar preenchidos numa conversa de venda.

As duas regras convivem se a RN-05.3 for lida como *"o mínimo para um lead qualificável"*, não como *"o suficiente para qualquer lead"*. É a leitura adotada, e está declarada aqui porque a card não a contém.

**`INDEFINIDA` e `FORA_DE_ESCOPO` também ficam fora, e a razão é outra.** Depois do primeiro turno `intencao` raramente é nula — o classificador sempre devolve um dos sete valores. Então *"intenção preenchida"* não pode significar *"não é nulo"*, ou a coluna estaria sempre preenchida. `INDEFINIDA` significa, no comentário do próprio enum, *"ainda não dá para saber"*; é ausência de intenção utilizável, não intenção.

**Consequência que o desenho original não tirou, e que a revisão final cobrou:** se `INDEFINIDA` não é intenção utilizável para *ler*, ela também não pode ser intenção utilizável para *escrever*. `campos_a_gravar` gravava `intencao` incondicionalmente em todo turno que não fosse `FORA_DE_ESCOPO`, e `intencao` era a única coluna de `lead_qualification` que não honrava o *"None não apaga"* que todas as outras honram. O efeito: um lead com os quatro campos completos que mandasse um "obrigado" — turno que o classificador rotula `INDEFINIDA` com extração vazia — deixava de estar qualificado, e voltava a estar quando retomasse o assunto, emitindo `lead.qualificado` uma segunda vez. A taxa de qualificação da RN-17.1 contaria travessias, e um lead tagarela produz várias.

`campos_a_gravar` passou a omitir a chave `intencao` quando a intenção do turno é `INDEFINIDA`. Os campos de extração do mesmo turno continuam gravando normalmente: *"zona sul, até 600 mil"* dito sem deixar claro se é compra ou aluguel é fato sobre a fala do lead, e não depende de sabermos a intenção. A alternativa — deixar `esta_qualificado` tolerante à regressão — foi recusada: a função pura só vê a linha atual e não tem como saber que houve intenção melhor antes.

**O preço, aceito:** um turno `INDEFINIDA` *sem extração nenhuma* passa a devolver dict vazio, e portanto não grava linha e não grava a marca de "perguntado, sem resposta" da TEC-257. Um primeiro turno que só diz "oi" deixa de criar uma linha com `intencao: INDEFINIDA` — linha que não afirmava nada e que o prompt renderizava assim mesmo. É "marcar de menos", que a própria `campos_a_marcar` declara como o erro seguro dos dois: custa uma pergunta a mais, e não mata um campo para o resto da conversa.

### D3 — O que conta como preenchido, campo a campo

| Campo | Conta quando |
|---|---|
| `intencao` | é `COMPRA`, `ALUGUEL` ou `INVESTIMENTO` (D2) |
| `faixa_preco` | **qualquer um** dos dois extremos é não-nulo |
| `regiao` | não-nulo |
| `urgencia` | não-nulo |

**A linha do preço é a única não-óbvia, e errá-la quebraria a RN-05.6.** São duas colunas, e exigir as duas contradiz a regra que diz que *"até 500 mil"* vira `max=50000000, min=null`. Faixa aberta é faixa válida — pedir os dois extremos deixaria todo lead que fala em teto preso em conversa para sempre, o que é o oposto do que a card quer.

`regiao` é `String(120)` e `normalizar_regiao` já descarta o que sobra vazio, então não-nulo basta: não há string vazia gravável nessa coluna.

### D4 — Recusado vence o valor gravado

Campo em `recusados` não conta como preenchido, mesmo que a coluna tenha valor. É o que a card determina, literalmente: *"campo marcado como recusado não conta como preenchido"*.

**A borda estranha fica registrada de propósito.** Se o lead disse *"500 mil"* e depois recusou falar de orçamento, o valor continua na coluna e o lead deixa de ser qualificado. É contra-intuitivo lendo o código, e quem passar por ali vai suspeitar de bug. Não foi suavizado: a regra é da card, e inverter a precedência seria decidir por conta própria que uma recusa posterior não revoga o que já foi dito — o que é uma decisão de produto, não de implementação.

### D5 — A informação de recusa entra por parâmetro, não por coluna

`recusados: frozenset[str] = frozenset()`.

Quem grava recusa é a [TEC-148](https://eduardodurieuxlopes.atlassian.net/browse/TEC-148) (RN-05.7), que está A fazer e que o Jira **não** lista como bloqueadora desta. Criar aqui uma coluna `campos_recusados` que nada escreve deixaria o cenário de aceite verde por um teste que grava na mão — verdadeiro e vazio.

Com o conjunto entrando por parâmetro, a regra fica completa e testável hoje, e a assinatura documenta a dependência em vez de escondê-la. A TEC-148 cria a coluna e passa o valor real; nenhuma linha desta card precisa mudar para isso acontecer.

O default vazio é deliberado: até a TEC-148, todo chamador de produção passa o conjunto vazio, e o comportamento é o da regra sem recusas.

**Os nomes que entram em `recusados` são canonicalizados**, e isso não é defensividade decorativa. `CAMPOS_OBRIGATORIOS` chama o orçamento de `faixa_preco`, que não é nome de coluna (`faixa_preco_min_centavos`/`faixa_preco_max_centavos`), nem campo de `Extracao` (`faixa_preco_expressao`), nem chave que o prompt renderiza (`faixa_preco_min`/`faixa_preco_max`) — e é sob a última que a marca da TEC-257 é gravada, via `_MARCA_DO_ORCAMENTO`. A TEC-148, ao reusar o vocabulário da marca (a escolha óbvia, e a única que ele oferece), passaria `recusados={"faixa_preco_max"}`: string que não está em `CAMPOS_OBRIGATORIOS`, laço que nunca a vê, e um lead que se recusou a falar de orçamento qualificando assim mesmo sobre um preço velho — com teste verde nas duas cards. É a mesma classe de divergência em que a TEC-146 queimou uma card inteira. A tradução é por prefixo (`faixa_preco`), e não por tabela, porque tabela precisa ser lembrada e prefixo não.

### D6 — A transição é o que esta card entrega de observável

Com função derivada, *"o status passa a QUALIFICADO"* não escreve nada. Sem mais nada, esta card entrega uma função que ninguém chama.

O turno calcula antes e depois da gravação do estado e loga a travessia:

```python
if not esta_qualificado(antes) and esta_qualificado(depois):
    log.info("lead.qualificado", ...)
```

O **antes** é grátis: `montar_contexto` já leu o estado para montar o prompt, e ele está em `contexto.estado`.

O **depois** não existe em memória hoje — `gravar_estado` devolve `None`. As três saídas, e por que só uma serve:

- **Reler depois de gravar** custa uma consulta a mais em todo turno, inclusive nos que não mudam nada de qualificação.
- **Recompor o merge em Python**, a partir do estado anterior mais `campos_a_gravar`, seria uma **terceira cópia da regra de acumulação**. A docstring de `campos_a_gravar` existe justamente porque duas cópias já haviam divergido em silêncio entre produção e o runner do eval; acrescentar uma terceira, aqui, para um log, é o pior negócio possível.
- **`gravar_estado` passa a devolver a linha resultante**, via `RETURNING` no `ON CONFLICT DO UPDATE` que ela já executa. Sem consulta a mais, sem duplicar regra nenhuma, e o valor é o que o banco de fato gravou — não o que o Python achou que ia gravar.

Fica a terceira. A assinatura vira `LeadQualification | None`, e o `None` não é descuido: `gravar_estado` já retorna cedo, antes de qualquer `execute`, quando `campos_a_gravar` devolve dict vazio — o caso `FORA_DE_ESCOPO`. Nada foi gravado, então não há linha a devolver e não há transição a avaliar. O único chamador de produção é `turno.py`; o runner do eval **não** chama `gravar_estado` — ele acumula estado sintético com `campos_a_gravar` direto, e por isso não é afetado. Os outros chamadores são três arquivos de teste.

**Isto é acréscimo do desenho, não pedido da card**, e está marcado como tal — inclusive a mudança em `gravar_estado`, que a card não pede e que existe só para tornar a transição observável sem pagar por ela.

## Fluxo

1. `montar_contexto` lê o estado para montar o prompt, como hoje. Esse é o **antes**.
2. O turno grava o estado; `gravar_estado` devolve a linha resultante (D6). Esse é o **depois**.
3. Cruzou de `False` para `True`, loga `lead.qualificado`.
4. Nada mais acontece. Não há coluna a escrever, e o recálculo de score é da TEC-150.

Turno que não grava estado — `FORA_DE_ESCOPO`, em que `campos_a_gravar` devolve dict vazio — não avalia transição nenhuma: sem gravação não há depois, e o antes não mudou.

## Testes

- **`tests/unit/test_qualificacao.py`**, novo. Os quatro cenários Gherkin da card, mais a tabela da D3 campo a campo, mais as intenções da D2 — incluindo `VENDER_IMOVEL` com os quatro campos preenchidos, que é o caso onde a RN-03.4 e a RN-05.3 divergem.
- **Faixa aberta nos dois sentidos:** só `min`, só `max`, e nenhum dos dois. É a D3 e o ponto mais fácil de quebrar sem ninguém notar.
- **`recusados`:** cada um dos quatro campos recusado isoladamente, e o caso da D4 (coluna preenchida e campo recusado ao mesmo tempo).
- **`estado is None`** — lead sem nenhuma linha ainda. Não qualificado, sem levantar.
- **Integração:** a transição da D6 dispara uma vez e só uma, no turno que completa o quarto campo, e não volta a disparar nos turnos seguintes.
- **Integração, o caso com a forma da produção:** o lead entrega os campos aos poucos — três obrigatórios no turno 1, o quarto no turno 2 — e o evento sai no turno 2 e só nele. Um lead que qualifica do estado vazio num turno só nunca exercita o `antes`: nele `antes` é sempre `esta_qualificado(None)`, e trocar a regra inteira por `estado is not None` deixa o teste verde. Foi o que a revisão final demonstrou por mutação.
- **Integração, a sequência de três turnos da D2:** qualifica, manda um "obrigado" (`INDEFINIDA`), volta ao assunto. A intenção sobrevive na coluna, e o evento não sai uma segunda vez.
- **Integração, o `RETURNING` sob identity map:** a mesma sessão lê com `ler_estado` e grava logo depois; o objeto devolvido reflete a gravação. Sem `populate_existing`, ele reflete a leitura.
- TDD, e cada teste verificado por mutação — reverter a regra que ele cobre tem de deixá-lo vermelho. Na TEC-146, todas as rodadas de revisão perdidas foram testes que passavam com o código certo ou errado.

## Lacunas declaradas

**"E o score é recalculado" não tem implementação.** É a segunda metade do primeiro cenário de aceite. O cálculo é a [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150), que esta card destrava e que a própria card põe fora de escopo. O cenário fecha na primeira metade.

**Nenhuma consulta filtra por qualificado.** Sendo derivada, a regra não é indexável: perguntar *"quantos leads qualificados?"* hoje exige varrer `lead_qualification` e avaliar quatro campos por linha. Aceitável enquanto o volume for de PoC; a card do dashboard ([TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192)) precisa decidir se materializa.

**O ticket de investidor não existe.** A RN-05.3 diz *"faixa de preço (ou ticket)"*, e a RN-05.2 lista campos próprios de `INVESTIMENTO` — ticket disponível, horizonte, tolerância a reforma — que são a [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153). Até lá, um investidor qualifica pela faixa de preço, como comprador. É a única leitura possível com os campos que existem.

**A transição da D6 depende do estado anterior estar em memória, e o caminho perigoso é o que *lê*.** Não há guarda contra nada disso — a marca de "já qualificado" não existe em lugar nenhum, justamente por causa da D1.

O risco óbvio é um caminho futuro que grave estado sem ter lido o anterior: `antes` seria `esta_qualificado(None)`, e o evento dispararia para um lead que já estava qualificado há turnos. O mais provável, porém, é o inverso, e ele custou um achado na revisão final: um caminho que **lê e grava na mesma sessão**. O `RETURNING` da D6 devolve uma instância ORM, e o *identity map* do SQLAlchemy entrega a instância que a sessão já carregou em vez de atualizá-la com a linha do banco — o `depois` viria idêntico ao `antes`, e o evento simplesmente não sairia. `turno.py` escapa por acidente, porque lê em `montar_contexto` (uma sessão) e grava em outra; a TEC-150 vai querer as duas na mesma sessão para recalcular o score. `gravar_estado` passa `populate_existing=True` no statement por causa disso, e um teste de integração fixa o cenário — mas é uma opção de execução que alguém pode remover sem entender, não uma garantia estrutural.

**Recusa não é detectada por nada.** A D5 deixa a regra pronta e o parâmetro vazio. Até a TEC-148, o cenário de aceite do campo recusado fecha apenas no teste unitário; em produção nenhum campo é recusado porque nada marca recusa.

**A regra qualifica sobre o palpite bruto do classificador, e não sobre a intenção efetiva.** Este repo tem uma resposta canônica para "em qual intenção posso rotear": `IntencaoDaConversa.efetiva` (`src/mobia/domain/agente/repositorio.py`), cuja docstring diz *"Leia por aqui"* e que rebaixa para `INDEFINIDA` qualquer classificação abaixo do limiar de 0,6 — *"'COMPRA com 0,45' é operacionalmente INDEFINIDA"*. A coluna `lead_qualification.intencao` guarda o palpite bruto, sem a confiança ao lado.

O cenário concreto, num turno só: o classificador devolve `COMPRA` com confiança 0,45 e uma extração confiante (faixa de preço, região e urgência). `esta_qualificado` vê `intencao = "COMPRA"`, declara o lead qualificado e o turno emite `lead.qualificado`. Quatro linhas depois, no mesmo turno, `deve_desambiguar` olha a mesma confiança de 0,45, decide que ela não sustenta o palpite, descarta a resposta gerada e pergunta ao lead *"você quer comprar ou alugar?"*. O evento afirma que sabemos o que ele quer no exato turno em que perguntamos o que ele quer.

Não foi consertado aqui porque a coluna não guarda confiança: uma função pura sobre a linha não tem como aplicar o limiar, e mudar o que a coluna guarda é escopo de outra card. A TEC-150, que já vai mexer no que a linha carrega para calcular score, é o lugar natural.

**Dois turnos concorrentes da mesma conversa emitem o evento os dois.** O `antes` é fotografado antes da chamada ao modelo, então a janela entre a foto e a gravação é uma ida e volta inteira ao LLM — centenas de milissegundos. Concorrência na mesma conversa não é hipótese neste repo: a união da marca de `perguntados_sem_resposta` foi para dentro do SQL exatamente por causa dela, e a guarda de monotonia de `gravar_resumo` também.

Consertar de verdade exige uma marca durável de "já qualificado" — isto é, a coluna que a D1 recusa, e recusá-la é o centro do desenho. O requisito de teste declarado acima (*"a transição dispara uma vez e só uma"*) vale para turnos sequenciais, e **não** vale sob concorrência: dois turnos simultâneos produzem dois `lead.qualificado` para o mesmo lead. O efeito é imprecisão de métrica na taxa da RN-17.1, e não erro no que chega ao corretor — nada roteia por este log. Se a RN-17.1 vier a precisar de contagem exata, ela paga a coluna.

## Fora de escopo

- O cálculo do score — [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150), que esta card destrava.
- O teto de 8 perguntas — RN-05.5, [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149).
- Detectar e gravar recusa de campo — RN-05.7, [TEC-148](https://eduardodurieuxlopes.atlassian.net/browse/TEC-148).
- Campos próprios da trilha de investidor — RN-05.2, [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153).
- A coluna de status e o funil de seis etapas — RN-17.2, e a card que precisar de um estado não-derivável.
- A entidade `Lead` do SRS. Este desenho segue o par `(channel, conversation_key)`, que é a identidade que o repo pratica desde a TEC-122 e que a TEC-182 reafirmou.
