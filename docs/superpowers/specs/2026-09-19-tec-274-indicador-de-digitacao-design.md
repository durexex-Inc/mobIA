# TEC-274 — Enviar indicador de digitação quando a resposta passa de 4 segundos

**Status:** desenhado em 2026-09-19 na branch `feat/tec-274-indicador-de-digitacao`.

**Card:** [TEC-274](https://eduardodurieuxlopes.atlassian.net/browse/TEC-274) — História, prioridade Medium. Origem: RF-04, RN-04.7 (SRS v1.0); RN-B01. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

## O que a API da Meta obriga, e que a card supõe diferente

A card escreve que *"a API do WhatsApp tem endpoint próprio para isso"*. Não tem. O indicador de digitação sai pelo **mesmo** `POST /{phone_number_id}/messages` que `WhatsAppOutbound._deliver` já usa, com um corpo de outra forma:

```json
{
  "messaging_product": "whatsapp",
  "status": "read",
  "message_id": "<wamid da mensagem do lead>",
  "typing_indicator": {"type": "text"}
}
```

Três consequências, e nenhuma delas é detalhe de implementação.

**O indicador não existe sem recibo de leitura.** O `"status": "read"` não é opcional e não há variante sem ele: a Meta não oferece "digitando..." isolado. Este sistema nunca marcou mensagem como lida; a partir desta card, todo turno que passar de 4 s dá tique azul na fala do lead, e os turnos rápidos não. **A assimetria foi aceita** (ver L4): ela é invisível para quem não compara turnos, e os dois sinais dizem a mesma coisa — "vi sua mensagem e estou respondendo".

**O indicador exige o `wamid` da mensagem de ENTRADA.** Não é um envio para um número, é uma anotação sobre uma mensagem recebida. O insumo já existe: `Message.provider_message_id` (`domain/messages/models.py`) guarda o `wamid`, preenchido na ingestão por `parse_meta_envelope` (`domain/messages/schemas.py`), que descarta o item do envelope quando ele falta. `Message.recipient_external_id` guarda o `phone_number_id` que a URL precisa. Nada de novo precisa ser gravado.

**O indicador expira em 25 segundos** e some sozinho, ou antes se a resposta sair. Esta card não o renova — ver L1.

## Estado de hoje

A card afirma, e a exploração confirmou: não existe nada. Nem código nem métrica. As duas únicas menções à RN-04.7 na árvore estão em `evals/metricas.py:388-390`, e existem para dizer que a regra **não** é o assunto daquele comentário.

A card também avisa que a RN-04.7 **não tem emenda**, apesar do título da TEC-258 dizer que emendou. Confirmado: o SRS tem a regra exatamente como foi escrita em 22/08/2026, sem item aninhado nenhum. Este desenho cria a primeira — ver a seção Emendas ao SRS.

Não existe, em `src/mobia/`, nenhuma tarefa concorrente dentro de um turno para copiar. `asyncio.create_task` não aparece na árvore; os únicos usos de `asyncio.timeout` são o do registro de cancelamento em `process_message.py` e o que o ARQ aplica de fora.

## As decisões

### D1 — Os 4 segundos medem o turno inteiro, não a chamada ao modelo

A card pergunta "onde o relógio vive" supondo que o alvo é a geração — a chamada ao classificador em `turno.py`. **Não é.** O relógio mede o silêncio que o lead sente: da fala dele até a primeira mensagem que sai.

Hoje, entre uma coisa e outra, o turno faz moderação de entrada, monta contexto (que pode chamar o resumidor), chama o classificador com laço de tool use e embeddings, e modera a saída. Um turno com 3 s de montagem de contexto e 3,5 s de modelo não passaria de 4 s em nenhuma das partes e deixaria o lead 6,5 s no vazio — que é exatamente o abandono que a RN-04.7 existe para evitar. Medir só a chamada ao modelo mede o nosso custo, não a experiência dele.

**Consequência:** o callback no classificador que a card sugere como alternativa está descartado. Ele não enxergaria nem a montagem de contexto nem as moderações.

### D2 — O relógio mora em `process_message`, não dentro de `executar_turno`

`executar_turno` **não muda em nenhuma linha**. O gerente de contexto envolve a chamada a ela, em `workers/jobs/process_message.py`:

```python
async with indicador_de_digitacao(session_factory, message=linha, indicador=ctx["indicador"]):
    resultado = await executar_turno(...)
```

A alternativa fiel à D1 — abrir o `async with` dentro de `executar_turno`, logo depois das guardas baratas de opt-out e atendimento humano — foi rejeitada pelo custo de revisão. Aquelas guardas ficam no topo da função e a primeira entrega está cerca de 1.300 linhas abaixo; o `async with` reindentaria cerca de 2.000 linhas. É diff mecânico, mas afoga a revisão de uma feature de oitenta linhas, e o CLAUDE.md já registra que partir `executar_turno` não é trabalho desta card.

**O que se perde:** o relógio passa a incluir o claim da mensagem e a leitura da linha (L3) — dezenas de milissegundos contra um limiar de 4.000. **O que se ganha além do diff:** a D3.

**Efeito colateral bom:** os 37 call sites de `executar_turno` e o `rodar_turno` de `tests/conftest.py` ficam intocados. A porta nova é injetada por `ctx`, e só os quatro construtores de `ctx` dos testes que rodam `process_message` mudam.

`ctx["indicador"]` por acesso direto, e não `ctx.get("indicador") or IndicadorNoop()`, pelo mesmo argumento que o comentário de `ctx["agendador"]` já faz naquele arquivo: um fallback silencioso trocaria a porta real por um dublê dentro de produção, e o sintoma de um `startup` que deixasse de popular a chave seria nenhum indicador, nunca, sem log e sem erro.

### D3 — As guardas são conferidas no instante do disparo, não pela posição no código

Antes de chamar a Meta, a tarefa roda as **mesmas duas consultas** que `GuardedOutbound.send` roda: `esta_em_optout_por_mensagem` e `esta_silenciada_por_mensagem`. Ambas negativas, dispara.

Isto é mais do que reproduzir a proteção que a D2 tirou do caminho — é uma proteção que a posição no código não daria. Um `async with` aberto depois das guardas do turno cobre o opt-out **já gravado** quando o turno começou. A conferência no disparo cobre também o lead que digita "parar" **durante** os quatro segundos, que é precisamente a janela em que isso acontece: ele mandou a mensagem, se arrependeu, e manda o "parar" enquanto o agente ainda pensa. Nesse caso o posicionamento deixaria o indicador sair.

**As guardas moram no agendador, não no adaptador.** O agendador é domínio agnóstico de canal; o adaptador sabe de HTTP e da Meta. É a mesma fronteira que `GuardedOutbound`/`WhatsAppOutbound` já desenha, só que sem a reserva no meio — ver D4.

A rota até `IndicadorDePresencaPort` é uma só (o agendador), e é ela que guarda. Um chamador futuro que instancie o adaptador direto não tem guarda nenhuma — o mesmo risco que o docstring de `OutboundPort` já escreve para si, e que o docstring da porta nova vai escrever também.

### D4 — Porta própria, e não um método a mais em `OutboundPort`

Módulo novo, `src/mobia/domain/outbound/presenca.py`:

```python
class IndicadorDePresencaPort(Protocol):
    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None: ...
```

Primitivos e não o objeto `Message`, seguindo a forma de `OutboundPort.send`.

**Por que não um método a mais em `OutboundPort`.** O docstring daquele Protocol é inteiro sobre reserva, `kind`, grupos de kind e as três exceções cujo **tipo** decide o desfecho do turno. Nada disso vale aqui: não há mensagem, não há `kind`, não há linha em `outbound_dispatches`, e nenhuma exceção deste método pode mudar coisa alguma. Somar um segundo método faria o Protocol carregar duas semânticas opostas — uma onde o tipo da exceção é o contrato, outra onde exceção nenhuma escapa — e passaria a dever os dois a todo adaptador futuro, inclusive o canal web da TEC-124, que não tem indicador de digitação nenhum para oferecer.

`IndicadorNoop` mora no mesmo módulo, pela mesma razão que `NoopOutbound` existe: é o que um ambiente sem token usa, e é o dublê natural quando um teste não é sobre o indicador.

O adaptador `WhatsAppIndicador` vai em `domain/outbound/whatsapp.py`, ao lado de `WhatsAppOutbound` — mesma base de URL, mesmo token, mesmo `TIMEOUT_SEGUNDOS`. Ele **não herda de `GuardedOutbound`**: não há o que reservar, e herdar arrastaria a UNIQUE `(message_id, kind)` para um envio que não tem kind. Herdar por hábito criaria a necessidade de inventar um `kind` sintético, e um `kind` sintético numa tabela cuja UNIQUE existe para dedup de **mensagem** é exatamente o tipo de coisa que ninguém desfaz depois.

### D5 — A tarefa é cancelada, e não awaitada

Na saída do gerente de contexto, `tarefa.cancel()` — **sem `await tarefa` depois**.

Awaitar dentro do `finally` cria um risco que custa mais do que o que resolve: quando o escopo de fora está sendo cancelado (o `job_timeout` do ARQ estourando), qualquer `await` ali dentro pode devolver o `CancelledError` do escopo de fora, e um `suppress(CancelledError)` em volta o engoliria. Esse é precisamente o cancelamento que o `except asyncio.CancelledError` de `process_message.py` existe para ver chegar — sem ele a linha fica em PROCESSING para sempre, `attempts` não sobe, e o sweeper paga o turno inteiro a cada volta.

O custo de não awaitar é nenhum: uma tarefa cancelada não guarda exceção para ninguém recolher, e o "Task exception was never retrieved" do asyncio só aparece quando há exceção. A referência forte que impede a coleta prematura é a variável local do gerente de contexto, viva até o `cancel()`.

### D6 — Falhar no indicador nunca custa a resposta

O corpo inteiro da tarefa fica sob `except Exception`, que vira `log.warning("presenca.indicador_falhou", reason=type(exc).__name__)` — só o nome da classe, como o resto do projeto, porque o texto de uma exceção de terceiro não é garantia que este repositório possa dar.

`warning` e não `error`: o indicador falhar degrada a experiência e não quebra nada, e o desfecho que a card exige — a resposta sai normalmente — é o que de fato acontece, porque a tarefa é concorrente e o turno nunca a espera.

`asyncio.CancelledError` é `BaseException` e passa reto por esse `except`, que é o comportamento certo no `cancel()` da D5.

O adaptador também não distingue 4xx de 5xx: não há retentativa a decidir, não há reserva a liberar, e um indicador que chega tarde não vale nada. Toda falha é a mesma falha.

### D7 — O limiar é configuração, com o valor da regra por padrão

`indicador_de_digitacao_apos_segundos: float = 4.0` em `app/config.py`.

Configuração e não constante porque os testes precisam injetar centésimos de segundo: três cenários do Gherkin a 4 s reais custariam mais de doze segundos por execução da suíte, num repositório cujo CLAUDE.md conta a duração da suíte em segundos e mede regressões nela.

`float` e não `int`, ao contrário dos `sweep_*_after_seconds` vizinhos, por essa mesma razão — o teste precisa de `0.05`, não de `0`.

`IndicadorNoop` é o desligamento, se algum dia for preciso: trocar a porta em `workers/main.py` desliga a feature inteira sem tocar no limiar nem no domínio. Nenhuma flag booleana entra agora, porque não há pedido para desligar e uma flag sem chamador é uma condição a mais em todo teste.

## Arquivos

| Arquivo | O quê |
|---|---|
| `src/mobia/domain/outbound/presenca.py` | **novo** — `IndicadorDePresencaPort`, `IndicadorNoop`, `indicador_de_digitacao` (o agendador e as guardas) |
| `src/mobia/domain/outbound/whatsapp.py` | `WhatsAppIndicador` ao lado de `WhatsAppOutbound` |
| `src/mobia/workers/jobs/process_message.py` | o `async with` em volta de `executar_turno`; `ctx["indicador"]` |
| `src/mobia/workers/main.py` | `ctx["indicador"] = WhatsAppIndicador(...)` no startup |
| `src/mobia/app/config.py` | `indicador_de_digitacao_apos_segundos` |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Emenda E-01 da RN-04.7 |

Nenhuma migration: o `wamid` e o `phone_number_id` já estão gravados.

`src/mobia/domain/agente/turno.py` **não aparece nesta tabela**, e é o resultado que a D2 comprou.

## Testes

Os três cenários do Gherkin viram testes do agendador, com limiar injetado em centésimos de segundo, contra um espião de `IndicadorDePresencaPort`:

- geração que passa do limiar dispara o indicador, **uma vez** — o espião conta chamadas, e a asserção é `== 1`, não `>= 1`;
- geração abaixo do limiar não dispara nada;
- falha na chamada do indicador não impede a resposta de sair.

Mais dois que a card não pede e o desenho decide:

- lead que entra em opt-out **durante** a espera não recebe indicador (a D3, que é a razão de ela existir);
- conversa em atendimento humano não recebe indicador.

E um do adaptador, contra um `httpx.AsyncClient` dublado: o corpo montado é o da Meta — `status: "read"`, o `wamid` da entrada em `message_id`, e `typing_indicator.type == "text"` — e a URL usa o `phone_number_id` da linha. Ele existe porque o corpo é a única parte do desenho que nenhum outro teste exercita, e errar uma chave ali é uma feature que não funciona em produção e passa em tudo.

Os quatro construtores de `ctx` dos testes que chamam `process_message` ganham a chave `indicador`: `_ctx` em `tests/features/test_reprocessamento_apos_falha.py`, `tests/integration/test_cancelamento_do_worker.py` e `tests/integration/test_handoff_por_erro.py`, e `_ctx_do_turno` em `tests/integration/test_sweep_stalled.py`.

## Lacunas conhecidas

> **Emenda (TEC-362, 24/09/2026): os 25 s deixaram de ser só um fato da Meta e passaram a ser escolha nossa no canal web.** O `WebIndicador` manda `ate = agora + 25 s` no frame, igualando os dois canais de propósito — um valor diferente faria o mesmo turno parecer diferente em cada um. A L1 abaixo passa a valer nos dois, e a card que renovar terá de renovar nos dois.

**L1 — O indicador expira em 25 s e esta card não o renova.** Um turno de 40 s deixa o lead vendo "digitando..." dos 4 s aos 29 s, e silêncio nos 11 s finais. A Gherkin da card pede explicitamente **uma** vez e não a cada segundo, e é o que este desenho entrega. Renovar exigiria um laço com seu próprio critério de parada e uma segunda decisão sobre o que fazer quando a renovação falha — outra card, se a medição mostrar que o pior caso do turno passa de 25 s com frequência que importe.

**L2 — Um turno pode disparar o indicador e não responder.** As guardas da D3 cobrem opt-out e atendimento humano. Não cobrem `reentrega_suprimida`: se o turno terminar suprimido depois dos 4 s, o indicador já saiu e nenhuma resposta vem atrás dele. A documentação da Meta desaconselha exatamente isso. Nada neste desenho previne — prever exigiria saber, aos 4 s, o que o turno vai decidir aos 8 s.

**L3 — O escopo do relógio é alguns milissegundos mais largo que "a geração".** Consequência aceita da D2: o claim e o `session.get` da linha entram na conta. Registrado para que ninguém leia o limiar de 4,0 como uma medida exata da geração.

**L4 — O tique azul passa a depender da latência.** Consequência da natureza da API (ver o topo). Um lead atento notaria que só algumas das falas dele são marcadas como lidas. É decisão de produto e está aceita, não escondida.

## Emendas ao SRS

A RN-04.7 não tinha emenda — a card avisa disso por extenso, e a exploração confirmou. Esta é a primeira:

> **Emenda E-01 (TEC-274, 19/09/2026):** o indicador desta regra **não existe isolado na Cloud API da Meta**. Ele sai no mesmo `POST /{phone_number_id}/messages` do envio de mensagem, num corpo que exige `"status": "read"` e o `wamid` da mensagem de entrada — ou seja, **enviar o indicador marca a fala do lead como lida**, e não há variante sem esse efeito. A regra passa a valer com ele: um turno que ultrapassa os 4 s dá tique azul; um turno rápido não dá. A regra também ganha a duração que o canal impõe — o indicador desaparece após 25 s, e a TEC-274 não o renova (L1 do desenho). E os "4 s" passam a ser medidos do início do processamento da mensagem até a primeira entrega, e não da chamada ao modelo: é o silêncio que o lead percebe, e um turno com três segundos de montagem de contexto e três e meio de modelo deixa o lead seis segundos e meio no vazio sem que nenhuma parte isolada ultrapasse o limiar. Ver as D1, D2 e a L1 do desenho em `docs/superpowers/specs/2026-09-19-tec-274-indicador-de-digitacao-design.md`.
