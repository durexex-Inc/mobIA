# mobIA

Agente de IA para qualificação de leads imobiliários.

## Ambiente local

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env
docker compose up -d
```

**Se você já tinha o volume do Postgres de antes da TEC-157, recrie-o.** A
imagem passou de `postgres:16-alpine` para `pgvector/pgvector:pg16`, e não
existe imagem pgvector oficial em Alpine — a troca muda a base de musl para
glibc. Reaproveitar o data dir arrisca ordenação incorreta de índice de texto,
porque o collation difere entre as duas. A base local é reproduzível, então o
custo é baixo e a alternativa é um risco silencioso:

```bash
docker compose down -v
docker compose up -d
python -m alembic upgrade head
```

**A migration 0044 cria a extensão `btree_gist`** (confiável desde o PG13; o
dono do banco a cria). Um Postgres gerenciado com lista de extensões
permitidas precisa liberá-la antes do `alembic upgrade head`, senão a
migration falha.

## Comandos

| O quê | Comando |
|---|---|
| Testes | `python -m pytest` |
| Teste de latência | `python -m pytest -m perf` |
| Orçamento de contexto do prompt | `python -m pytest -q -k margem_do_orcamento -s` |
| Lint | `python -m ruff check src tests alembic` |
| Formatação | `python -m ruff format src tests alembic` |
| Migrations | `python -m alembic upgrade head` |
| API | `python -m uvicorn mobia.app.main:app --reload` |
| Worker | `python -m arq mobia.workers.main.WorkerSettings` |

## TEC-122 — Ingestão do WhatsApp

Os critérios de aceite da história vivem como testes executáveis:

| Cenário Gherkin | Teste |
|---|---|
| Confirmar recebimento antes de processar | `tests/features/test_recepcao_de_mensagem.py::test_confirmar_recebimento_antes_de_processar` |
| Descartar payload com assinatura inválida | `tests/features/test_recepcao_de_mensagem.py::test_descartar_payload_com_assinatura_invalida` |
| Não perder mensagem em falha do worker | `tests/features/test_reprocessamento_apos_falha.py::test_nao_perder_mensagem_em_falha_do_worker` |
| 200 OK em até 300 ms no p95 | `tests/perf/test_ingest_latency.py` (roda com `-m perf`) |

### Garantias

- A mensagem é commitada no Postgres **antes** de ir para o Redis. Se o processo
  morrer no meio, o cron `sweep_stalled` reenfileira.
- Efeito externo passa por `outbound_dispatches` com `UNIQUE (message_id, kind)`:
  a reentrega vira no-op, então o reprocessamento nunca duplica resposta.
- Assinatura inválida responde 200 e só gera log. Devolver erro faria a própria
  Meta re-tentar o payload de um forjador.

## TEC-126 — Telemetria de mensagens

| Cenário Gherkin | Teste |
|---|---|
| Registrar mensagem de entrada do lead | `tests/features/test_telemetria_de_mensagens.py::test_registrar_mensagem_de_entrada_do_lead` |
| Registrar resposta do agente com custo | `tests/features/test_telemetria_de_mensagens.py::test_registrar_resposta_do_agente_com_custo` |
| Conteúdo pessoal não vaza para o log | `tests/features/test_telemetria_de_mensagens.py::test_conteudo_pessoal_nao_vaza_para_o_log` |
| Falha de telemetria não derruba o atendimento | `tests/features/test_telemetria_de_mensagens.py::test_falha_de_telemetria_nao_derruba_o_atendimento` |

### Garantias

- `messages` é a linha do tempo da conversa: entrada e saída, agrupadas por
  `conversation_key` e ordenadas por `created_at`. `sender` e `recipient` se
  invertem entre as direções; `conversation_key` não.
- `text_body` e `raw_payload` são cifrados com AES-GCM antes do `INSERT`, com
  AAD `{message_id}:{coluna}` — ciphertext movido para outra linha não decifra.
  Em troca, `raw_payload` deixou de ser consultável por operador JSONB.
- Telemetria é gravada num segundo passo: falha nela perde o custo, nunca o
  registro da fala do agente.
- Modelo sem preço cadastrado grava `cost_usd` NULL, não zero.
- A chave de cifra vem de `CONTENT_ENCRYPTION_KEY` (32 bytes em base64). Rotação
  de chave não está implementada, mas o formato gravado carrega um byte de
  versão (`version(1) || nonce(12) || ciphertext || tag(16)`) para que ela não
  exija reescrever a tabela offline no dia em que for feita.
- `ENVIRONMENT=production` com `CONTENT_ENCRYPTION_KEY` no default commitado
  **impede a aplicação de subir**. Assinatura errada falha na primeira
  requisição; chave de cifra errada não falha — grava tudo com uma chave
  pública e ninguém percebe. A guarda vive no validator de `Settings`, então
  vale também para o Alembic, que cifra a tabela no backfill da 0004.
- `message_telemetry` tem `cache_read_tokens` e `cache_write_tokens` nullable.
  Eles são gravados desde já para que o dado exista; o cálculo de custo ainda
  ignora cache e fica com a história que liga o agente (TEC-134).

## TEC-127 — Janela de contexto do modelo

| Cenário Gherkin | Teste |
|---|---|
| Conversa longa cabe no limite de tokens | `tests/features/test_janela_de_contexto.py::test_conversa_longa_cabe_no_limite_de_tokens` |
| Estado estruturado não é reconstruído | `tests/features/test_janela_de_contexto.py::test_estado_estruturado_nao_e_reconstruido_pelo_modelo` |
| Resumo é comprimido ao estourar | `tests/features/test_janela_de_contexto.py::test_resumo_e_comprimido_ao_estourar_o_limite` |
| Resumo é regerado na cadência | `tests/features/test_janela_de_contexto.py::test_resumo_e_regerado_na_cadencia_definida` |

### Garantias

- O contexto é `resumo + tudo o que veio depois da marca d'água, na íntegra` —
  não existe lacuna entre o que foi resumido e o que está literal.
- **A marca nunca avança além de deixar vinte mensagens literais**, com a única
  exceção do estouro do teto, abaixo. As vinte mais recentes são um piso, não um
  teto: entre regenerações o prompt carrega de vinte a quarenta na íntegra.
- Estouro do teto de 12.000 tokens desce a cascata sempre na mesma ordem, e o
  laço é limitado a três iterações: (1) avança a marca dobrando as mensagens
  mais antigas, com o piso de pé; (2) re-resume o próprio resumo, uma vez por
  turno; (3) dobra **abaixo** do piso, deixando só a mensagem mais recente
  literal; (4) só então descarta literais. Dobrar é perda normal, re-resumir é
  perda em cascata, e descartar é perda total — por isso o descarte é o último.
- Quando o piso e o teto se contradizem (vinte mensagens que somam mais de
  12.000 tokens), o teto vence: ele é o limite físico da chamada, o piso é
  preferência de qualidade. O piso cede **dobrando**, não descartando — o
  conteúdo vai para o resumo e a marca avança junto, então continua não
  existindo lacuna. `contexto.piso_violado` registra nos dois lugares em que o
  piso de fato cede: nessa dobra e no truncamento de emergência.
- Falha do provedor não derruba o turno: usa o resumo antigo, corta literais até
  caber, e loga `contexto.degradado`.
- Resumo que não decifra (rotação de chave, escrita parcial, restore de um
  ambiente com outra chave) vale como resumo inexistente: tudo volta literal,
  `contexto.resumo_ilegivel` registra, e a próxima dobra sobrescreve a linha.
  Uma linha corrompida não pode brickar a conversa para sempre.
- Quando nem uma única mensagem sem resumo cabe no teto, `montar_contexto`
  levanta `ContextoIrreducivel` em vez de devolver um contexto acima do limite.
  É exceção visível ao chamador — a TEC-134 tem de tratá-la — e acontecer
  significa que uma mensagem sozinha excede o limite físico da chamada, que o
  provedor recusaria de qualquer jeito.
- **A fase de montagem tem relógio próprio de 35s**
  (`Settings.contexto_deadline_de_montagem_segundos`), agregado sobre toda a
  fase que fala com o provedor (TEC-290). Estourá-lo não é falha, é
  degradação: o turno segue e o lead recebe resposta. O contexto é truncado
  **sem round trip ao provedor**, com uma estimativa local deliberadamente
  pessimista, e `contexto.deadline_estourado` registra o evento.
- O teto comparado é o nominal **menos** `CONTEXTO_HEADROOM_DE_TOKENS`. A
  contagem mede uma mensagem plana, sem `system` e sem os rótulos, o schema e a
  ferramenta que a requisição real carrega; a reserva cobre essa diferença. São
  cinco as parcelas em que a contagem difere do que se envia: `SISTEMA` de
  `montagem.py` é contado e **não** enviado (o classificador chama
  `montar_prompt(omitir_sistema=True)`); `SISTEMA_DO_AGENTE`, o schema de saída
  compilado, os rótulos de seção que `montar_prompt` intercala e a definição da
  ferramenta de busca em `tools=` (TEC-265) são enviados e **nunca** contados.

  **Quanto isso dá hoje não está escrito aqui, de propósito** (TEC-243). É
  valor derivado — muda a cada mudança de prompt, de campo do schema ou de
  rótulo — e transcrito à mão ele envelheceu quatro vezes em dois dias, sempre
  pego tarde e por revisão humana. Ele vive em
  `test_diferenca_entre_o_contado_e_o_enviado`, que quebra se alguma das
  parcelas crescer, e sai impresso por:

  ```
  python -m pytest -q -k margem_do_orcamento -s
  ```

  A conta usa um proxy `len/4` próprio do orçamento — não mais o mesmo de
  `montagem.py`, que a TEC-225 trocou por uma fórmula ciente de densidade —, e
  não uma chamada paga de `count_tokens`. A reserva já subiu cinco vezes: 400
  → 800 na TEC-145, 800 → 850 na TEC-250, 850 → 880 na TEC-257, 880 → 1.060 na
  TEC-265 e 1.060 → 1.700 na TEC-225 — esta última medida contra o contador
  real (`ContadorAnthropic`), não mais por aritmética sobre o proxy. O porquê
  de cada subida e o preço por turno estão no comentário de
  `contexto_headroom_de_tokens` em `src/mobia/app/config.py`, que é o registro
  dessa decisão. Ver também a seção TEC-145 abaixo.
- Mensagem sem texto (áudio, imagem, documento) entra marcada pelo tipo, nunca
  como turno em branco — o modelo tem de poder distinguir "mandou um áudio que
  ainda não transcrevemos" de "não disse nada", e é esse texto que a dobra
  grava no resumo para sempre.
- O resumo é cifrado em repouso como o conteúdo das mensagens; o estado de
  qualificação fica em claro de propósito, porque TEC-147, TEC-150 e TEC-158
  filtram por ele em SQL.
- A chave `ANTHROPIC_API_KEY` é obrigatória a partir desta história.

## TEC-134 — Classificação de intenção e o primeiro turno

| Cenário Gherkin | Teste |
|---|---|
| Classificação de investimento persiste no turno | `tests/features/test_classificacao_de_intencao.py::test_intencao_de_investimento_persiste_no_turno` |
| Classificação de aluguel persiste no turno | `tests/features/test_classificacao_de_intencao.py::test_intencao_de_aluguel_persiste_no_turno` |
| Intenção e confiança ficam registradas | `tests/features/test_classificacao_de_intencao.py::test_intencao_e_confianca_ficam_registradas_na_conversa` |

O quarto cenário do ticket — suíte de 50 conversas com 90% de acurácia no CI —
é a TEC-210, palavra por palavra, e não está aqui.

### Garantias

- **Este é o primeiro turno que responde ao lead.** Até aqui o `_deliver` do
  `GuardedOutbound` levantava `NotImplementedError` e o `NoopOutbound` só logava.
- Uma única chamada devolve intenção, confiança e resposta por saída estruturada
  com schema estrito derivado do enum `Intencao`.
- **A reserva de envio é liberada em falha retentável.** A TEC-122 escolheu o
  contrário quando o que se perdia era um ACK; agora o que se perde é a resposta
  ao lead, e perdê-la em silêncio é pior que entregá-la duas vezes.
- **A fala do agente é gravada depois da entrega.** Uma queda no meio deixa o
  lead com a resposta e a linha do tempo sem ela — o agente pode se repetir. O
  contrário deixaria fala fantasma no histórico, que o resumo da TEC-127 dobraria
  permanentemente.
- Fora da janela de 24h da Meta não é falha: o turno termina `PROCESSED` com
  aviso, porque retentar nunca vai entregar.
- 4xx da Meta também termina `PROCESSED`, com log em nível `error` — marcar
  `FAILED` faria o sweeper pagar cinco chamadas ao modelo por um payload que
  nunca será aceito.
- `ANTHROPIC_API_KEY` e `WHATSAPP_ACCESS_TOKEN` são obrigatórias.

### Lacunas conhecidas

- **`ContextoIrreducivel` faz o lead ser ignorado em silêncio.** Uma mensagem
  grande demais para o teto de tokens termina o turno sem resposta. Fica visível
  no log; o dono natural é a TEC-135.
- **Reentrega suprimida pode terminar o turno sem o lead receber nada.** Se uma
  tentativa anterior commitou a reserva e morreu antes de gravar a fala, o
  reprocessamento cai na guarda: `send()` devolve `False`, nada é gravado (o
  texto desta chamada nova pode não ser o que saiu antes) e a mensagem fecha em
  `PROCESSED`, que é terminal. Não dá para saber se o lead recebeu o texto da
  primeira tentativa. `turno.reentrega_suprimida` loga em `error` — mesmo nível
  do 4xx, e pelo mesmo motivo: é o nível que o alerta observa.
- **Não há moderação de entrada nem de saída.** A TEC-210 exige em 100% dos
  turnos. Este é o primeiro turno que existe, e ele vai ao ar sem nenhuma.
- A confiança é autoavaliação do modelo, não probabilidade calibrada. Os limiares
  de 0,8 e 0,6 são provisórios até a TEC-210 medi-los.
- **O reconhecimento de intenção em si não é verificado.** Os testes de aceite
  provam que a classificação atravessa um turno real e chega ao banco intacta —
  não que o modelo classifica certo: o classificador é sempre um dublê, porque
  nenhum teste desta suíte toca a rede, e a intenção entra por argumento. Medir
  acurácia é a TEC-210, com o corpus anotado.

## TEC-135 — Desambiguação abaixo de 0,6

| Cenário Gherkin | Teste |
|---|---|
| Mensagem vaga gera pergunta aberta | `tests/features/test_desambiguacao_de_intencao.py::test_mensagem_vaga_gera_pergunta_aberta` |
| Confiança exatamente no limite não desambigua | `tests/features/test_desambiguacao_de_intencao.py::test_confianca_exatamente_no_limite_nao_desambigua` |
| Resposta à desambiguação reclassifica a intenção | `tests/features/test_desambiguacao_de_intencao.py::test_resposta_a_desambiguacao_reclassifica_a_intencao` |
| Ambiguidade persistente não vira insistência | `tests/features/test_desambiguacao_de_intencao.py::test_ambiguidade_persistente_nao_vira_insistencia` |

### Garantias

- Abaixo de `LIMIAR_DE_DESAMBIGUACAO` (0,6) o lead recebe uma pergunta do desambiguador
  em vez de uma resposta que assume a intenção. O limiar é fechado por cima:
  exatamente 0,6 segue sem perguntar.
- Uma pergunta por **episódio** de ambiguidade, não por conversa, para uma
  sequência de turnos processada em série. Uma classificação com confiança no
  limiar ou acima limpa o marcador e abre um episódio novo. Ver a lacuna sobre
  concorrência abaixo — a garantia não vale entre turnos que rodam em paralelo.
- `desambiguado_em` só é gravado depois de a entrega ser confirmada. Falha de
  entrega — expirada, recusada ou reentrega suprimida — não queima a pergunta.
- `conversation_intent.intencao` continua guardando o palpite cru do
  classificador. **Não roteie por essa coluna**: `IntencaoDaConversa.efetiva`
  devolve `INDEFINIDA` abaixo do limiar, e é por ela que TEC-136 e TEC-137 leem.
- O turno ambíguo custa **duas** chamadas ao modelo, cada uma pagando o
  contexto de entrada inteiro (não há `cache_control` neste projeto): a
  resposta da primeira é descartada, mas o desperdício não é só ela — entrada
  domina a contagem de tokens, e a segunda chamada paga o mesmo contexto de
  novo. A fala gravada leva a telemetria da segunda; o custo da primeira fica
  só no log `agente.turno_gerado`.

### Lacunas conhecidas

- Nada no código garante que a segunda chamada devolva uma pergunta aberta em vez
  de um menu numerado. A regra vive inteira no `SISTEMA_DA_DESAMBIGUACAO`, e
  medir a saída é a TEC-210.
- **A garantia de uma pergunta por episódio não vale sob concorrência.** Não há
  serialização por conversa (`claim_message` tranca por mensagem, o sweeper
  usa `FOR UPDATE SKIP LOCKED` por linha, não há lock consultivo, e o arq roda
  até 10 jobs em paralelo por padrão). Duas mensagens do mesmo lead chegando
  segundos uma da outra podem desambiguar em paralelo e o lead recebe duas
  perguntas — a guarda de saída não pega isso porque as duas passagens têm
  `message_id` diferentes. Serializar por conversa antes da segunda chamada ao
  modelo é a [TEC-128](https://eduardodurieuxlopes.atlassian.net/browse/TEC-128).
- O limiar de 0,6 continua não calibrado. Ele saiu de um comentário e virou
  constante nomeada — que é o pré-requisito para a TEC-210 mexer nele.

## TEC-227 — Cancelamento do worker não perde a mensagem

`asyncio.CancelledError` é `BaseException`, não `Exception`. Quando o
`job_timeout` do arq estoura — ou o worker desliga — nenhum `except Exception`
pega o cancelamento, e até aqui isso custava caro de dois jeitos.

A linha ficava em `PROCESSING` com `attempts` congelado. E `PROCESSING` é
reivindicável: o sweeper reenfileirava a mesma mensagem a cada varredura,
**para sempre**, pagando o turno inteiro — chamadas ao modelo inclusas — a cada
volta, porque o teto de `sweep_max_attempts` nunca era alcançado. Não era uma
parada silenciosa; era um laço de retentativa paga sem limite.

E se o cancelamento caísse depois da reserva de envio commitada, a reserva
sobrevivia: o sweeper reenfileirava, a guarda suprimia a reentrega e a mensagem
fechava em `PROCESSED` — terminal — com o lead sem ter recebido nada.

### Garantias

- Um turno cancelado deixa a mensagem em `FAILED`, com `attempts` incrementado
  e `last_error` preenchido, nunca em `PROCESSING` silencioso. Cada
  cancelamento passa a consumir uma das `sweep_max_attempts`, então o laço fica
  limitado pela primeira vez.
- O `CancelledError` **continua propagando** depois do registro. Engoli-lo
  quebraria o desligamento limpo do worker. Se a própria escrita do `FAILED`
  falhar ou estourar seu teto de tempo, ela vira o evento
  `message.cancelled_nao_registrado` e o cancelamento segue mesmo assim — a
  garantia de propagação não depende de o banco responder.
- A escrita que registra o cancelamento tem teto de tempo próprio. Quando ela
  roda, todo prazo já se foi (o timeout do arq dispara uma vez e não volta), e
  um banco pendurado — justamente uma das razões de o turno ter estourado o
  orçamento — prenderia o slot do worker para sempre.
- Cancelamento durante a entrega libera a reserva em `outbound_dispatches`,
  como já acontecia com `EnvioRetentavel`. É a mesma troca que a TEC-134 fez, e
  pelo mesmo motivo: entre o lead receber duas vezes e nunca receber, a
  duplicata ganha — ela é visível e recuperável, o silêncio não.
- Cancelamento tem evento próprio no log (`message.cancelled`), separado de
  `message.failed`.
- Todos os testes forçam cancelamento **real** (`task.cancel()` numa task em
  voo). A diferença entre `Exception` e `BaseException` é o defeito inteiro —
  um teste com exceção comum passaria com o bug intacto.

### Lacunas conhecidas

- **A duplicata deixou de ser hipotética.** Se o cancelamento cair depois de o
  POST ter chegado à Meta, liberar a reserva faz a retentativa entregar de
  novo. Foi a escolha consciente; o caso oposto era perder a resposta para
  sempre. A janela é o tempo do POST, limitado a 10s pelo timeout do cliente
  do WhatsApp.
- ~~**`message.cancelled` não distingue timeout de deploy.**~~ Fechada pela
  TEC-232, abaixo. O `handle_sig` do arq cancelava todo job em voo a cada
  SIGTERM: um deploy emitia uma rajada do mesmo evento, com o mesmo
  `last_error`, e cada restart **consumia uma das cinco tentativas** — enquanto
  a docstring do `sweep_stalled` diz que esse orçamento é de "5 falhas de
  verdade", e um restart não é falha de processamento nenhuma. O
  `job_completion_wait` drena os jobs em voo antes de cancelar. O evento
  continua sendo um só, mas agora ele só dispara quando o turno de fato esgotou
  o próprio orçamento.
- **A janela do commit da reserva continua aberta.** A guarda cobre o
  `_deliver`, não o `commit()` que cria a reserva. Um cancelamento exatamente
  ali deixa indeterminado se a linha foi gravada, e se foi, ninguém a libera —
  mesma perda silenciosa, numa janela muito mais estreita (um round-trip local
  contra um POST de até 10s). É anterior a este card e continua aberta.
- **Um segundo sinal aborta o registro.** Um SIGTERM que chegue enquanto a
  escrita do `FAILED` está em voo cancela a task de novo e a linha fica em
  `PROCESSING`. O sweeper ainda a recupera, só que sem contar a tentativa.
- **Isto não cria folga no `job_timeout`.** Continua em 240s, e `resumir` +
  `classificar` sozinhos já somam o pior caso do cliente. O cancelamento apenas
  deixou de ser invisível — ele continua custando a passada inteira do turno,
  com as chamadas pagas ao modelo. Reduzir a chance de ele acontecer é a
  [TEC-228](https://eduardodurieuxlopes.atlassian.net/browse/TEC-228).


## TEC-232 — Deploy não cancela mais turno em voo

O `handle_sig` do arq cancela **todo** job em voo a cada SIGTERM. Desde a
TEC-227 esse cancelamento deixou de ser invisível — vira `FAILED` com
`attempts` incrementado — e aí o preço ficou explícito: cada restart queimava
uma das cinco `sweep_max_attempts` de uma mensagem que não tinha falhado em
nada. Cinco deploys num dia ruim, e o lead é abandonado por um orçamento que a
docstring do `sweep_stalled` reserva para "5 falhas de verdade".

`job_completion_wait = 250` troca o handler pelo
`handle_sig_wait_for_completion`: o worker para de pegar job novo, espera os
que estão em voo e **só então** cancela o que sobrou.

### Garantias

- `job_completion_wait` (250s) é **estritamente maior** que o `job_timeout`
  (240s), e é dessa relação que sai a garantia inteira: a drenagem cabe o
  orçamento completo do turno, então nenhum deploy cancela um job por conta
  própria. Ou ele termina, ou estoura os 240s dele — que é falha de verdade e
  conta certo. Um teste trava o par, porque subir o `job_timeout` sem subir a
  drenagem é o jeito provável de isto quebrar em silêncio.
- O turno drenado fecha normalmente: `PROCESSED`, sem gastar tentativa, sem
  emitir `message.cancelled`.
- A cláusula de `CancelledError` da TEC-227 continua sendo a rede embaixo. O
  cancelamento pós-janela ainda acontece — e ali ele é legítimo, porque o turno
  realmente esgotou o orçamento.
- O teste que importa não verifica a constante: ele verifica **qual handler o
  arq registra no SIGTERM**. O `get_kwargs` do arq filtra
  `WorkerSettings.__dict__` pela assinatura do `Worker` e descarta em silêncio o
  que não casa — renomear o atributo, ou torná-lo uma `property`, faria a
  configuração virar no-op sem erro nenhum. Um teste na constante passaria
  intacto nesse caso.

### Pré-requisito de deploy

**A carência SIGTERM→SIGKILL da plataforma tem de passar de ~265s.** Não é
recomendação, e o número tem conta: 250s de drenagem, mais os 10s de
`SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO` que o job não-drenado usa para escrever
seu `FAILED`, mais os hooks de shutdown (`dispose_engine` e o fechamento do
pool do Redis). Se o SIGKILL chegar antes de tudo isso, o processo morre sem
`CancelledError`: a cláusula de `process_message` não roda, nada escreve
`FAILED`, e a linha fica em `PROCESSING` com `attempts` congelado. O sweeper
ainda a recupera, mas sem contar a tentativa — o que é **pior** que cancelar na
hora, que ao menos registrava. Todo default de plataforma fica muito abaixo
disso: `docker stop` são 10s, `terminationGracePeriodSeconds` do Kubernetes são
30s.

Nenhum teste cobre esta exigência, e não é descuido: não existe configuração de
deploy neste repositório para um teste ler. O `docker-compose.yml` sobe
Postgres, Redis e Mailpit para desenvolvimento local, e o worker roda por
`python -m arq`. Quando o deploy existir, este é o número que tem de subir
junto.

### Lacunas conhecidas

- **Deploy passa a demorar até 250s.** É o preço direto da troca: drenar é
  esperar. Um turno lento no ar segura o desligamento até terminar.
- **Ctrl+C duas vezes não acelera o desligamento.** O segundo sinal cria outra
  espera em vez de cancelar na hora, e o worker continua saindo no prazo da
  primeira janela. Atrito de desenvolvimento, não de produção.
- **`message.cancelled` continua sendo um evento só.** A distinção
  timeout-versus-deploy não foi resolvida, foi tornada quase irrelevante: com a
  drenagem, o deploy praticamente não gera mais o evento. Praticamente — um
  turno que atravesse a janela inteira ainda é cancelado, e nesse caso o evento
  está certo.
- **A drenagem não cobre o SIGKILL.** Ver o pré-requisito acima. É a única
  forma de esta mudança piorar o estado anterior, e ela depende inteiramente de
  configuração que não está aqui.
- **Nada disto cria folga no `job_timeout`.** Segue em 240s, e `resumir` +
  `classificar` sozinhos já somam o pior caso do cliente. Reduzir a chance de
  estourar é a
  [TEC-228](https://eduardodurieuxlopes.atlassian.net/browse/TEC-228).

## TEC-210 — Gate de avaliação da classificação de intenção

Até aqui a qualidade do agente era impressão subjetiva. A TEC-134 já dizia:
o classificador é sempre um dublê nos testes, porque nenhum teste da suíte
normal toca a rede — a intenção entra por argumento, e os limiares de 0,8 e
0,6 da TEC-135 são autoavaliação do modelo, sem régua nenhuma para medi-los.
Um ajuste de prompt que piora a classificação passava por toda a suíte sem
barrar nada.

O gate mora fora de `tests/` — em `evals/`, com conftest próprio — porque as
fixtures `autouse` do conftest raiz exigem Postgres, e um marker `eval` não
escaparia disso. `testpaths = ["tests"]` no `pyproject.toml` já garante que
`pytest` sozinho nunca coleta o eval; rodá-lo é `pytest evals`, à parte.

**A chamada ao modelo é real, nunca gravada.** Rodar contra resposta em cache
seria determinístico e barato, e mediria nada: o que o gate existe para pegar
é uma mudança de prompt alterando o que o modelo devolve, e um replay
passaria verde com o prompt destruído. Pela mesma razão o eval não fixa
`temperature=0` — o código não passa `temperature` para a API, então produção
roda no default dela, e medir com `temperature=0` daria um número estável
sobre uma configuração que a produção não usa.

O corpus é `evals/corpus/*.yaml`, um arquivo por categoria (`compra`,
`aluguel`, `investimento`, `follow_up`, `borda`), 53 conversas e **146
turnos** anotados à mão — o texto é escrito primeiro, o rótulo depois, e por
um humano, não pelo modelo medido: gerar o corpus com o mesmo modelo que ele
avalia embutiria as pistas que aquele modelo lê bem e infla a acurácia por
construção. A distribuição por intenção sai desigual porque a conversa real é
desigual: COMPRA 57, ALUGUEL 32, INVESTIMENTO 26, FORA_DE_ESCOPO 9, INDEFINIDA
9, SUPORTE_CONTRATO 7, VENDER_IMOVEL 6. Onze conversas mudam de intenção no
meio, e duas são tentativa de injeção — uma delas com dois turnos, o hijack
frontal e, depois dele, a injeção embutida num pedido real de compra.

A medida é **por turno, não por conversa** — é o que "acurácia de intenção"
significa, e uma conversa que muda de intenção no meio só faz sentido medida
assim. Cada turno vê o histórico dos turnos anteriores já montado, como em
produção, via `mobia.evals.contexto`: `Message` transientes, cifradas com o
mesmo `encrypt`/AAD do banco real mas nunca inseridas, então o job de CI não
sobe Postgres nem Redis — só Python e a chave da API.

### Duas acurácias, e por que a crua não bastava

O gate mede **duas** acurácias sobre a mesma execução, e a segunda foi a
correção mais importante desta rodada.

A crua compara o palpite do classificador (`obtida`) com o rótulo do corpus.
Ela mede o classificador, e é cega para uma coisa: **produção não roteia pelo
palpite cru.** `conversation_intent.intencao` guarda o palpite sem edição, mas
quem consome lê `IntencaoDaConversa.efetiva`, que delega a `intencao_efetiva`
em `src/mobia/domain/agente/desambiguacao.py` e rebaixa para `INDEFINIDA`
qualquer classificação com confiança abaixo de `LIMIAR_DE_DESAMBIGUACAO`
(0,6). No turno ambíguo `executar_turno` vai além: descarta a resposta escrita
sobre o palpite e entrega a pergunta do desambiguador. Um ajuste de prompt que
preservasse a acurácia crua e destruísse a calibração da confiança deixaria o
gate verde enquanto produção desambigua em todo turno — pagando duas chamadas
por turno e não respondendo nada. O gate era cego exatamente para isso, porque
`Classificacao` não carregava `confianca`.

A **acurácia efetiva** fecha esse buraco: é a mesma comparação, feita sobre
`Classificacao.efetiva` — o que produção rotearia. Ela **bloqueia**, pelas
mesmas faixas de 90/84 da crua.

**Ela nasceu com piso próprio de 50%, e ele era andaime.** Enquanto a baseline
não existia, ninguém sabia qual acurácia efetiva era saudável, e herdar 90/84
seria repetir o erro que o próprio `LIMIAR_DE_DESAMBIGUACAO` documenta: número
do SRS, não calibrado. Um piso não medido pode abrir vermelho na primeira
execução sem regressão nenhuma. O que dava para afirmar sem medir era só a
catástrofe: se a calibração morre e a confiança de **todo** turno cai abaixo do
limiar, tudo vira `INDEFINIDA` e sobram como acerto apenas os turnos cujo
rótulo já era `INDEFINIDA` — 9 de 136, ou 6,6%. Os 50% pegavam isso, e nada
mais fino que isso.

**A primeira execução paga rodou em 27/08/2026 e mediu 126/136, ou 92,6%.** O
andaime saiu, por um motivo que a medição tornou óbvio: os 90% do critério de
aceite são sobre o que o lead experimenta, e o lead experimenta a intenção
**efetiva**, não o palpite cru. O alvo pertence a esta métrica ao menos tanto
quanto à outra.

> **Nota da TEC-145 (28/08/2026):** o corpus mudou depois desta medição, e o
> "50 conversas / 136 turnos" abaixo continua batendo, o que esconde a
> mudança em vez de denunciá-la. O terceiro turno de `aluguel-02` foi
> **reescrito** nesta card para conter uma correção de região (ver seção
> TEC-145), então a fala enviada ao modelo hoje não é mais a mesma que gerou
> os 126/136 acima — o rótulo (`ALUGUEL`) não mudou, mas o texto exato, sim.
> Os outros 31 turnos que ganharam a chave `campos` não alteram texto
> nenhum, só acrescentam anotação que o classificador nunca lê. Uma reexecução
> paga contra o corpus atual pode divergir desse número por este motivo, além
> do ruído normal entre execuções (±1,5%, citado abaixo).
>
> **Atualização (29/08/2026):** esta nota ficou desatualizada, e é exatamente
> o risco que ela existe para avisar — o corpus mudou de novo por baixo dela
> sem que ninguém voltasse para corrigi-la. A TEC-239 deu um quarto turno a
> `compra-02` e a `compra-08`; o corpus tinha então **138 turnos**, não 136, e o
> texto logo abaixo já reflete o número atual. A comparação com os 126/136
> acima segue valendo pelo motivo original — o turno de `aluguel-02` mudou de
> texto —, mas agora soma-se um segundo motivo, maior, para uma reexecução
> divergir: dois turnos inteiros que não existiam quando esta medição rodou.
>
> **Segunda atualização (29/08/2026, TEC-246):** e mudou uma terceira vez, no
> mesmo dia. A TEC-246 acrescentou três conversas inteiras (`compra-13`,
> `compra-14`, `compra-15`) para fechar a cobertura por valor de vocabulário
> da extração — oito turnos novos, todos COMPRA. O corpus está em **53
> conversas e 146 turnos**, e a distribuição por intenção logo abaixo já
> reflete isso: COMPRA passou de 49 para 57, e as outras seis intenções não
> mudaram. Os turnos novos são de extração, não de intenção, mas entram na
> acurácia de intenção do mesmo jeito, porque a medida é por turno — então a
> distância entre os 126/136 acima e uma reexecução cresceu de novo: são hoje
> dez turnos que não existiam quando aquela medição rodou.

Isso trouxe um ganho e um custo. O ganho: **degradação parcial de calibração
passou a barrar.** Com o piso de 50%, meio corpus rebaixado dava exatamente 50%
e passava, e essa limitação estava declarada aqui; agora meia calibração
perdida é vermelho, porque é metade dos leads recebendo pergunta em vez de
atendimento. O custo: 92,6% deixa 2,6 pontos até o alvo, e o ruído entre
execuções é da ordem de ±1,5% — a efetiva vai oscilar entre VERDE e AMARELO
perto da borda. AMARELO não bloqueia, e são 8,6 pontos até o piso de 84%.

Separadas, as duas também diferenciam o diagnóstico: as duas vermelhas é o
classificador degradando; a crua verde e a efetiva vermelha é a calibração da
confiança desabando com o palpite intacto. E a efetiva pode ficar **acima** da
crua sem que seja bug — num turno cujo rótulo é `INDEFINIDA`, rebaixar um
palpite mal-confiante acerta o rótulo. A seção "Confiança" do relatório conta
esses dois casos separados (`acertos_rebaixados`, `acertos_recuperados`).

### Garantias

- **Verde em 90%, amarelo até 84%, vermelho abaixo.** Os 84% não são um
  número escolhido para este README: é o exemplo de regressão que o próprio
  Gherkin do card usa para dizer "isto tem de barrar o merge".
- **A comparação é aritmética inteira, nunca float.** `faixa_de` em
  `src/mobia/evals/metricas.py` compara `acertos * 100` contra
  `total * ALVO_PCT`: dois lados inteiros, nenhuma divisão no caminho, exato por
  construção. O motivo **não** é que float erraria a borda — não erraria.
  `126/150` e o literal `0.84` são o mesmo `double`, e
  `print(126/150 >= 0.84, 126/150 == 0.84, 135/150 >= 0.9)` imprime
  `True True True`. O motivo é que, com inteiros, ninguém precisa verificar
  isso: não existe representação decimal no caminho sobre a qual raciocinar,
  então a borda exata deixa de ser um caso a analisar a cada mexida em limiar
  ou em tamanho de corpus. Uma versão anterior desta seção afirmava que a borda
  caía para o lado errado em float; era falso, e a escolha continua certa por
  outro motivo.
- **A acurácia efetiva bloqueia, e é a única que pega regressão de
  calibração.** Ela mede `Classificacao.efetiva` — o que produção rotearia —
  contra o rótulo, pelas mesmas faixas de 90/84 da crua. Ver "Duas acurácias"
  acima: um prompt com palpite intacto e confiança destruída reprova aqui, e só
  aqui.
- **`Classificacao` carrega `confianca`, e o campo não é opcional.** Sem ele
  não existe a tripla (esperada, obtida, confiança) que recalibrar
  `LIMIAR_DE_DESAMBIGUACAO` exige, e nenhuma outra execução do sistema produz
  essas triplas — o gate seria a única chance de coletá-las e a jogaria fora.
- **`SEM_MECANISMO` nunca é verde, e nunca bloqueia.** As três métricas que o
  card pede e não têm sujeito — precisão de extração (TEC-145), taxa de
  alucinação (TEC-161) e aderência ao tom (TEC-140) — aparecem declaradas em
  todo relatório nesse estado. Nunca verde, porque um slot que reporta verde
  sem medir nada some do radar e finge cobertura que não existe. Nunca
  bloqueia, porque um estado sem mecanismo que barrasse merge deixaria o gate
  permanentemente vermelho — e um gate sempre vermelho é desligado em uma
  semana.
- **O relatório nomeia os turnos errados, um por linha**, com
  `conversa_id[índice]: esperada -> obtida (confiança)`. A matriz de confusão
  diz que `INVESTIMENTO` virou `COMPRA` sete vezes; ela não diz quais sete, e
  descobrir isso pela matriz custaria outra execução paga. Sem teto de linhas
  de propósito: uma lista truncada devolve o leitor ao problema que ela
  resolve. Entram na lista também os turnos cujo palpite estava **certo** e foi
  rebaixado pela confiança — eles não aparecem na acurácia crua nem na matriz,
  e são os únicos que só a calibração explica, então cada linha vem marcada com
  qual dos quatro casos é — exceto o errado e confiante, o único que não leva
  marca, porque é o caso simples e não precisa de explicação extra.
- **Falha de infraestrutura abandona a conversa e a execução segue.** Um 429,
  um timeout ou um `RespostaInvalida` não são o modelo errando a intenção:
  contá-los como turno errado faria rede instável ler como regressão de prompt.
  Antes, uma falha no turno 90 subia e levava o dinheiro já gasto e os 89
  resultados sem imprimir nada; agora cada conversa é um envelope, a que falha
  é registrada em `FalhaDeInfraestrutura` e a próxima começa. O relatório sai
  sempre — inclusive numa execução que perdeu tudo —, porque ele é o único
  artefato que sobra de dinheiro já gasto, e ele mostra as falhas de rede em
  seção própria, logo depois das métricas, dizendo explicitamente que nenhum
  turno delas entrou em métrica nenhuma. Vermelho por 429 pede re-rodar;
  vermelho por regressão pede investigar.
- **A conversa vale inteira ou não vale.** Uma conversa interrompida no meio é
  descartada por completo, sem aproveitar os turnos que já tinham dado certo:
  o histórico é sequencial, então o que sobra é sempre o prefixo dela — e o
  corpus põe a mudança de intenção no meio ou no fim justamente porque é ali
  que mora o turno difícil. Aproveitar prefixos enviesaria a acurácia para
  cima em toda execução com rede instável.
- **Duas asserções guardam a validade da execução, antes da que julga o
  prompt**, e nessa ordem porque a primeira que estourar é a mensagem que o CI
  mostra: `TETO_DE_CONVERSAS_ABANDONADAS` (5) diz "a rede caiu, re-rode",
  `PISO_DE_TURNOS` (120) diz "sobrou amostra de menos", e só então `bloqueia`
  diz "o prompt regrediu". O teto de 5 não é gosto: é a folga do piso —
  146 − 120 = 26 turnos — dividida pelo pior caso de abandono. Essa conta não
  é mais 5 × 3: a TEC-239 deu um quarto turno a `compra-02` e a `compra-08`,
  então as cinco conversas mais longas do corpus hoje somam 4 + 4 + 3 + 3 + 3
  = 17 turnos, contra 26 de folga — o teto de 5 continua de pé, e a margem
  **alargou**: era 1 quando o corpus tinha 138 turnos (17 contra 18 de folga),
  e é 9 hoje, porque a TEC-246 cresceu o corpus em conversas curtas e as cinco
  mais longas continuam as mesmas. Com seis abandonos o pior caso seria
  146 − 20 = 126 turnos, ainda **acima** do piso — antes desta card seriam
  138 − 20 = 118, e seis já furava. A fronteira mudou de seis para **nove**
  abandonos (146 − 29 = 117), e é exatamente ela que
  `tests/unit/test_evals_metricas.py::test_o_teto_de_abandono_nunca_consegue_furar_o_piso_de_turnos`
  falha de graça se o corpus mudar de forma e as duas asserções passarem a
  poder reprovar a mesma execução por motivos diferentes.
- O gate compara **percentual**, não contagem absoluta — o corpus tem hoje
  146 turnos, e uma conversa a mais ou a menos muda esse total, então cravar
  contagem faria o limiar mudar de significado a cada conversa acrescentada.
  O piso de 120 turnos (`PISO_DE_TURNOS`) é o que garante que um único turno
  não valha mais de 0,8% e a faixa amarela continue absorvendo o ruído entre
  execuções — os 146 turnos reais folgam esse piso em 26.
- **`evals.yml` é um workflow só, sem `paths` nem `paths-ignore`, e roda em
  todo `pull_request`** — sempre exatamente um check run, com nome estável
  (`Avaliacoes de IA`). Um passo inicial decide sozinho se o PR mexeu em
  prompt de agente, comparando `git diff --name-only
  "origin/${{ github.base_ref }}...HEAD"` contra o regex
  `^(src/mobia/domain/agente/|src/mobia/evals/|evals/)`; só quando bate é que
  os passos caros (instalar dependências, chamar o modelo) rodam — a maioria
  dos PRs não paga nada, mas o check aparece do mesmo jeito, com um log
  dizendo qual caminho foi tomado, para não virar um "passou sem fazer nada"
  silencioso demais para investigar.
- **Esse desenho de workflow único substitui um par que existiu antes**
  (`evals.yml` com `paths` de inclusão, `evals-skip.yml` com o
  `paths-ignore` complementar) e que tinha uma corrida real. A semântica do
  GitHub Actions é assimétrica: `paths` roda se *algum* arquivo casa,
  `paths-ignore` roda se *qualquer* arquivo *não* casa. Um PR que mudasse
  `classificador.py` (casa) e também `README.md` (não casa) disparava os
  **dois** workflows no mesmo commit, com o mesmo nome de check — e o check
  trivial (`evals-skip.yml`) podia terminar primeiro e mascarar a falha real
  do outro. O motivo de existir um par continua válido e é o motivo de o
  workflow único sempre rodar: um check obrigatório com filtro de `paths`
  nunca roda em PR que não toca aqueles caminhos, e a proteção de branch fica
  esperando para sempre, travando o merge — só que agora a resposta é um
  único workflow sem filtro de gatilho, não dois workflows espelhados. Este
  raciocínio é hipotético hoje, porque o repositório não pode ter check
  obrigatório (ver lacunas), mas é o que impede alguém de "otimizar" o gatilho
  de volta para um filtro de `paths` e criar o problema no dia em que puder.
- **`fetch-depth: 0` no checkout não é detalhe.** Sem histórico completo,
  `origin/${{ github.base_ref }}` não existe no clone raso e o `git diff` do
  passo de decisão falha — um erro que só apareceria no primeiro PR real, não
  em desenvolvimento local.
- **Pré-requisito:** o segredo `ANTHROPIC_API_KEY` no repositório. Foi criado em
  27/08/2026; sem ele o job não falha no primeiro turno — ele abandona cada
  conversa com `ConfiguracaoInsegura`, sem gastar chamada nenhuma, e reprova
  pelo teto de conversas abandonadas. O relatório sai dizendo o que houve.

### Lacunas conhecidas

- **Não há como tornar `Avaliacoes de IA` um check obrigatório.** Proteção de
  branch e rulesets exigem GitHub Team em organização, ou repositório público, e
  o `durexex-Inc` está em plano gratuito com repositório privado: os endpoints
  respondem `403 — Upgrade to GitHub Pro or make this repository public`. O gate
  roda em todo PR que toque os caminhos, e o vermelho aparece na lista de
  checks — mas **nada impede o merge por cima dele**. Hoje o que separa uma
  regressão de prompt da `main` é disciplina de quem mergeia, não trava. Se o
  time crescer, ou o merge passar a ser feito por quem não acompanhou o PR, a
  trava deixa de ser opcional.
- **Duas medições, ainda não uma distribuição.** A baseline de 27/08/2026
  (95,6% na crua, 92,6% na efetiva) ganhou uma segunda em 30/08/2026 pela
  TEC-247 (97,3% e 96,6%), contra um corpus diferente. Os pisos foram
  escolhidos em torno da primeira, e o ruído real entre execuções continua
  estimado (±1,5%), não medido: dois pontos contra corpus distintos não são
  dispersão. Um gate relativo a histórico — bloquear por queda maior que a
  dispersão observada — já tem **onde** guardar as execuções desde a TEC-247
  (`evals/relatorios/`, commitado), mas ainda não tem execuções suficientes
  para calcular a dispersão, e o relatório de uma execução **em CI** continua
  efêmero: não há `upload-artifact` em `evals.yml`. Enquanto isso, um vermelho
  perto da borda pode ser variância.
- ~~**Degradação parcial de calibração não barra.**~~ Fechada quando a baseline
  medida substituiu o piso de 50% pelas faixas de 90/84. Meio corpus rebaixado
  dava exatamente 50% e passava; hoje é vermelho.
- **A contagem de "turnos abaixo do limiar" do relatório não é a contagem de
  perguntas que produção faria.** Ela vem de `deve_desambiguar(confianca,
  None)` — marcador vazio, porque o eval não tem banco nem episódio em aberto —
  e responde "a confiança sozinha bastaria para perguntar?". Produção tem a
  segunda condição, uma pergunta por episódio, então numa conversa com
  ambiguidade persistente ela pergunta menos vezes que essa contagem sugere. O
  rebaixamento em si não depende do marcador, então a acurácia efetiva
  continua sendo exatamente o que produção rotearia.
- **O filtro interno de `evals.yml` tinha um buraco, fechado na TEC-204.**
  `montagem.py` mora em `src/mobia/domain/context/`, que não casava com o regex
  `^(src/mobia/domain/agente/|src/mobia/evals/|evals/)` do passo "Decidir se
  o prompt mudou": uma mudança ali alterava o que o modelo vê sem rodar o
  eval. Desde a TEC-204 o filtro casa também `src/mobia/domain/context/` e
  `src/mobia/infra/moderacao.py`, porque é ali que mora a delimitação do texto
  do lead que a suíte de injeção (`evals/test_injecao.py`) mede.
- **`src/mobia/app/config.py` também está fora do filtro, e esse buraco é
  maior.** É lá que mora `modelo_agente` (`"claude-opus-5"`), e trocar o modelo
  muda mais do que um ajuste de prompt muda: um PR de uma linha pode substituir
  o modelo medido e ser mergeado sem o gate rodar uma vez. **Não** foi incluído
  no filtro de propósito, e o motivo está comentado no próprio `evals.yml`:
  `config.py` é o arquivo de configuração inteiro e muda por muitos motivos
  alheios ao agente, então incluí-lo faria o gate pago rodar à toa em PRs que
  não têm nada a ver com o modelo. A cobertura de verdade seria mover
  `modelo_agente` para um arquivo que só o agente use — não existe ainda. Se um
  dia o gate não rodar quando deveria, este é o lugar a olhar primeiro.
- **Corpus sintético não é tráfego real.** Cento e quarenta e seis turnos
  escritos por quem conhece o sistema carregam o viés de quem os escreveu, e
  nenhuma anotação cuidadosa remove isso. O número que sair daqui é um piso
  de confiança, não uma medida de campo. Oito desses turnos — as três
  conversas que a TEC-246 escreveu — são sintéticos num sentido ainda mais
  forte: existem para cobrir valores do vocabulário de extração, e não porque
  alguém observou o arquétipo. Ver a garantia da cobertura por valor na seção
  TEC-145.
- **9 das 10 conversas de `investimento.yaml` abrem com pista lexical
  explícita** — "airbnb", "revender", "renda" — então o lado INVESTIMENTO do
  par difícil (compra sem finalidade declarada é COMPRA; INVESTIMENTO exige
  evidência positiva de renda ou revenda) é majoritariamente detecção de
  palavra-chave, não desambiguação de verdade. A exceção é `investimento-04`:
  o primeiro turno abre neutro ("quero comprar um apartamento de 2 quartos na
  zona oeste", rotulado COMPRA) e só o segundo revela a finalidade, o único
  caso no corpus em que a pista chega depois da abertura.
  **Mas essa exceção salva menos do que parece**, e as duas coisas são
  verdade ao mesmo tempo: o segundo turno dela recita a definição do próprio
  system prompt quase palavra por palavra — o corpus diz `"nao pra morar"`
  contra o `"nao para morar"` de `SISTEMA_DO_AGENTE` em
  `src/mobia/domain/agente/classificador.py`. Acertar esse turno é, no limite,
  casar com o texto do prompt, não desambiguar finalidade. Ou seja: o único
  caso em que a pista chega depois da abertura é também o caso em que a pista
  está mais fácil, e a cobertura real desse lado do par difícil segue sem
  exemplo forte.
- **Das 3 falas de injeção do corpus — em 2 conversas —, 2 são hijack
  frontal** e são as mais fáceis de recusar ("ignore as instruções
  anteriores…", "esquece que você é da imobiliária…"). A terceira, o segundo turno de `borda-injecao-01`, é a
  injeção embutida num pedido legítimo, rotulada COMPRA porque é isso que o
  lead quer; ela mede a metade legítima do turno, e ignorar a instrução colada
  é trabalho do system prompt, que este gate não mede. Um exemplo só é pouco
  para essa forma, que é a que quebra prompt na prática.
- **COMPRA é 39% dos turnos** (57 de 146): um classificador que responda
  sempre COMPRA já tira 39% de acurácia de graça. Isso não invalida o alvo —
  90% continua exigindo acerto real nas outras classes —, mas a matriz de
  confusão vai ser dominada por COMPRA e ALUGUEL, e VENDER_IMOVEL (6 turnos)
  e SUPORTE_CONTRATO (7) têm massa tão pequena que um único erro move a
  classe inteira em 14–17 pontos percentuais. **O desequilíbrio piorou nesta
  árvore, e por um motivo alheio à intenção:** era 35% (49 de 138) até a
  TEC-246, que acrescentou oito turnos COMPRA para fechar cobertura de
  vocabulário da **extração**. As três conversas novas cabiam em qualquer
  categoria; foram para `compra.yaml` porque o arquétipo do lead que procura
  chácara, usa consórcio ou ainda não decidiu a forma de pagamento é o de
  quem compra. O piso de graça de um classificador degenerado subiu 3,5 pontos
  por isso (35,5% para 39,0%), e a próxima card que acrescentar conversa deve olhar esta linha
  antes de escolher o arquivo.
- **O eval mede `classificar` isolado**, não o turno inteiro com worker e
  banco — a integração já tem cobertura própria na suíte normal, mas uma
  regressão que só apareça ali não é pega aqui.
- **O histórico realimentado diverge de produção depois de um turno
  ambíguo.** O runner alimenta o turno seguinte com a resposta da chamada de
  `classificar`. Produção, no turno ambíguo com o episódio ainda limpo, faz
  outra coisa: `executar_turno` (`src/mobia/domain/agente/turno.py`)
  **descarta** essa resposta, paga uma segunda chamada a
  `classificador.desambiguar` e é a pergunta de desambiguação — não esta
  resposta — que entra no histórico e é gravada. O contexto medido a partir do
  turno seguinte, portanto, não é o que produção teria. Isso não afeta a
  classificação de cada turno, que é sempre a da primeira chamada, a mesma que
  produção grava em `conversation_intent`; afeta o contexto dos turnos que vêm
  **depois** de uma abertura provavelmente ambígua — `borda-evasivo-01`,
  `borda-evasivo-02`, `borda-mista-01`, `borda-longa-01` e `follow-up-07` —,
  que são justamente os turnos mais difíceis do corpus. Replicar o desvio
  dobraria as chamadas pagas nesses turnos, e é decisão de escopo, fora da
  TEC-210.
- **Zero acentos nos dados do corpus.** Não há **um único** caractere
  acentuado nos 146 turnos:
  `LC_ALL=C grep -n '[^ -~\t]' evals/corpus/*.yaml` não casa nada. Isso é
  vazamento da convenção de código (comentários e docstrings em ASCII puro)
  para dentro dos dados, onde ela não vale: `carregar` em
  `src/mobia/evals/corpus.py` lê o YAML com `encoding="utf-8"` e acento é
  seguro em todo o caminho. Lead real digita "não", "orçamento", "três", e o
  corpus não exercita nenhum. As próximas adições de turno **podem** usar
  acentuação normal — só os comentários de cabeçalho dos `.yaml` seguem a regra
  de código, porque ali ela é a convenção do repositório.
- **Este card não recalibra os limiares de 0,8 e 0,6.** Ele cria a régua;
  medir e mexer nos números é trabalho seguinte.
- **Moderação (TEC-233) e política de não-treinamento com o provedor
  (TEC-234) continuam abertas.** Foram desmembradas da TEC-210 porque uma é
  feature de produção e a outra é tarefa contratual — nenhuma das duas é
  avaliação, e este gate não entrega nenhuma das duas.

## TEC-233 — Moderação de entrada e saída

A TEC-210 registrou a lacuna nestes termos: "não há moderação de entrada nem
de saída", enquanto o critério de aceite do produto exige as duas em 100% dos
turnos. Esta card fecha a lacuna — só ela, não a medição: as taxas continuam
desconhecidas, ver "Lacunas conhecidas" abaixo.

`ModeradorPort` (`src/mobia/domain/moderacao/port.py`) é um protocolo de um
método, `moderar(texto, *, direcao: Direcao) -> Veredito`. `Direcao` tem dois
valores, `ENTRADA` e `SAIDA`, porque o critério não é o mesmo dos dois lados:
na entrada julga-se a fala de um estranho; na saída, o que a imobiliária diz
em nome próprio, com critério mais estrito — o mesmo texto pode ser tolerável
vindo do lead e inaceitável vindo da empresa. `Veredito` é `frozen`: atravessa
o turno sem ser reescrito no caminho. `ModeracaoIndisponivel` é a exceção de
"não deu para moderar", que **não** é o mesmo que "moderou e liberou" — quem
trata essa exceção decide de forma assimétrica entre as duas pontas (ver
Garantias). O port também define os dois textos fixos que substituem a fala
do modelo quando ela é barrada: `TEXTO_DA_RECUSA_DE_ENTRADA` e
`TEXTO_NEUTRO_DE_SAIDA` — nenhum dos dois explica o critério (explicar ensina
a contornar) nem acusa o lead (falso positivo é comum, e quem caiu nele não é
infrator).

`ModeradorAnthropic` (`src/mobia/infra/moderacao.py`) é o único adaptador. Ele
manda uma mensagem para o modelo com um dos dois system prompts fixos
(`SISTEMA_DA_ENTRADA`, `SISTEMA_DA_SAIDA`) e exige de volta `LIBERAR` sozinho,
ou `BLOQUEAR` seguido de uma ou duas categorias — sem pontuação nem
explicação —, com `MAX_TOKENS_DO_VEREDITO = 24`: curto o bastante para que um
truncamento vire um erro tipado em vez de um veredito pela metade — "BLOQ"
não é resposta. Qualquer coisa fora do protocolo (resposta truncada, palavra
diferente, exceção do SDK, `stop_reason` que não é `end_turn`) vira
`ModeracaoIndisponivel`; o adaptador nunca interpreta o desconhecido como
liberado, porque isso transformaria um moderador confuso em um moderador
desligado, e desligado em silêncio.

A **TEC-204** acrescentou `INJECAO` ao vocabulário da entrada — tentativa de
mudar as instruções do agente, de fazer revelar as regras dele, ou de se
passar pelo sistema. Ela é a exceção do protocolo: não está em
`CATEGORIAS_QUE_BLOQUEIAM`, e por isso sozinha não bloqueia nada — o turno
segue normal e só o achado vira evento de auditoria (`INJECAO_DETECTADA`,
ver TEC-206). É a terceira palavra do protocolo que existe: junto de uma
categoria que bloqueia, o veredito escreve as duas (`BLOQUEAR ASSEDIO
INJECAO`). A defesa contra a injeção em si — delimitar o texto do lead e
declará-lo dado, nunca instrução — não é deste sistema; é
`domain/agente/delimitacao.py`.

`executar_turno` (`src/mobia/domain/agente/turno.py`) chama esse protocolo
duas vezes: uma vez para a fala do lead, antes de montar o contexto; uma vez
para o texto que o agente está prestes a entregar, depois de decidido qual
texto é esse.

### Garantias

- **A moderação vive no turno, não num decorador do outbound, e há um teste
  que fixa exatamente esse motivo.**
  `tests/integration/test_moderacao_de_saida.py::test_o_recorder_grava_o_texto_entregue_e_nao_o_barrado`
  existe porque `record_agent_message` grava o texto **entregue**. Um
  decorador que interceptasse e substituísse a saída por dentro faria o
  recorder gravar o texto **barrado**: o histórico do lead passaria a conter
  uma fala que ele nunca viu, que entra no contexto do turno seguinte e é
  dobrada permanentemente no resumo da TEC-127. Morar no turno é o que
  garante que o recorder só veja o texto que de fato saiu.
- **Cliente próprio, com teto de 5s e `modelo_moderacao`, e não o cliente do
  turno.** `get_moderation_client()` usa
  `TIMEOUT_DA_MODERACAO_SEGUNDOS = 5.0` e `MAX_TENTATIVAS_DA_MODERACAO = 0`
  (`src/mobia/infra/moderacao.py`). O cliente do turno
  (`infra/anthropic.py`) não tem retentativa (`MAX_TENTATIVAS = 0`, desde a
  TEC-228) e cada chamada manda o próprio teto — de `TETO_DO_COUNT_TOKENS`
  (5s) a `TETO_DO_INVESTIDOR` (35s) — contra um `job_timeout` de 240s que o
  turno **já** estoura sozinho: `resumir` + `classificar` + `desambiguar`
  somam 360s no pior caso (comentário de `job_timeout` em `workers/main.py`, e a seção
  TEC-135 acima). Moderar as duas pontas com aquele cliente somaria mais 240s
  a um orçamento já estourado; com o teto de 5s e sem retentativa, as duas
  chamadas de moderação somam 10s — ruído contra uma folga que já não existe,
  não um agravante novo. `modelo_moderacao` (`claude-haiku-4-5-20251001` em
  `app/config.py`) é uma configuração própria, independente de
  `modelo_agente`, porque classificar uma palavra e escrever uma resposta não
  precisam do mesmo modelo.
- **A falha é assimétrica, e as duas metades importam.** Na entrada ela falha
  **aberta**:
  `tests/integration/test_moderacao_de_entrada.py::test_moderador_indisponivel_na_entrada_deixa_o_turno_seguir`
  prova que o turno segue quando o moderador não responde, porque a fala do
  lead já está cifrada no banco — a ingestão gravou antes de o worker
  existir — e negar atendimento a um lead legítimo por um serviço fora do ar
  pune o inocente. Na saída ela falha **fechada**:
  `tests/integration/test_moderacao_de_saida.py::test_moderador_indisponivel_na_saida_nao_entrega`
  prova que a exceção propaga e nada é entregue, porque entregar texto não
  moderado é exatamente o risco que este subsistema existe para fechar, e o
  custo de errar aqui é público — a reputação da imobiliária, não só o
  atendimento de um lead.
- **Bloqueio nunca produz silêncio**, nas duas pontas — o mesmo critério que
  a TEC-134 e a TEC-227 já tinham escolhido ao preferir a duplicata visível à
  perda silenciosa. Entrada bloqueada entrega `TEXTO_DA_RECUSA_DE_ENTRADA`;
  saída bloqueada entrega `TEXTO_NEUTRO_DE_SAIDA` no lugar do texto barrado.
  As duas passam por `record_agent_message`, então o histórico registra o
  que o lead efetivamente recebeu.
- **A moderação de entrada roda antes de `montar_contexto`, e isso economiza
  o turno inteiro quando ela bloqueia** — inclusive as chamadas pagas que a
  montagem pode disparar (`resumidor`, a cada ~40 mensagens; `contador`,
  perto do teto de tokens).
  `tests/integration/test_moderacao_de_entrada.py::test_entrada_bloqueada_entrega_recusa_e_nao_chama_o_modelo`
  usa um espião sobre `montar_contexto` para provar que ele **não** é
  chamado no caminho bloqueado — sem o espião, uma mensagem semeada não
  torna `montar_contexto` observável, e o teste passaria com o bloco movido
  para depois dele. O contraponto,
  `test_entrada_liberada_segue_o_turno`, usa o mesmo espião para garantir que
  o caminho liberado continua montando contexto de verdade.
- **A saída é moderada uma vez por turno, porque só um texto sai.**
  `tests/integration/test_moderacao_de_saida.py::test_a_saida_e_moderada_uma_vez_por_turno`
  conta exatamente uma chamada com `Direcao.SAIDA`. No caminho ambíguo a
  resposta da primeira chamada ao classificador já é descartada antes de
  chegar à moderação — só a pergunta do desambiguador é julgada.
- **Saída bloqueada não gasta a pergunta de desambiguação.**
  `marcar_desambiguacao` afirma "eu já perguntei", e é por isso que a
  gravação espera a entrega confirmada: escrita antes, um 5xx da Meta
  queimaria a única chance do episódio e o lead ficaria em `INDEFINIDA` sem
  ninguém ter perguntado nada. Um bloqueio de saída é indistinguível de um
  5xx no único aspecto que o marcador afirma — a pergunta não chegou; o que
  chegou foi `TEXTO_NEUTRO_DE_SAIDA`, que não pergunta nada. A condição em
  `executar_turno` exige as duas coisas, e o `turno.desambiguou` vai junto,
  porque fora dela ele afirmava algo que não aconteceu.
  `tests/integration/test_moderacao_de_saida.py::test_saida_bloqueada_no_caminho_ambiguo_nao_marca_a_desambiguacao`
  é também o único teste que exercita moderação no caminho ambíguo — todos os
  outros usam a confiança padrão do dublê (0,91), e era esse ponto cego que
  mantinha o defeito vivo por seis revisões.
- **O veredito é lido tolerante na forma e rígido no conteúdo.** O protocolo
  pede palavras sem pontuação, mas `BLOQUEAR.` ou `**LIBERAR**` não podem
  custar um turno: comparados por igualdade eles virariam
  `ModeracaoIndisponivel`, e na saída isso propaga até a linha ficar em
  `FAILED` para sempre, sem o lead receber nada. `_ATE_TRES_PALAVRAS`
  (`infra/moderacao.py`) exige até três corridas de letras cercadas só de
  não-letras — a terceira existe só para `INJECAO` acompanhar outra
  categoria (TEC-204) —; ela não procura a palavra dentro de uma frase,
  então `BLOQUEAR LIBERAR`, `não vou BLOQUEAR` e `talvez` continuam sendo
  indisponibilidade, e duas categorias que bloqueiam juntas (`BLOQUEAR
  ASSEDIO AMEACA`) também, porque no máximo uma categoria que bloqueia pode
  sobrar depois de separar `INJECAO`. A garantia que sustenta o subsistema —
  o desconhecido nunca vira liberado — fica intacta, e há teste para cada
  metade.
- **A entrega de texto fixo não mente na telemetria nem no desfecho.**
  `_entregar_texto_fixo` não chama modelo nenhum, e grava
  `MODELO_SEM_CHAMADA` (`app/config.py`, custo zero na tabela de preços) em
  vez de `model=""` — que caía fora da tabela, fazia `custo_em_dolar`
  devolver `None` e emitia `telemetry.unknown_model` a cada entrada
  bloqueada, abrindo chamado para uma lacuna que não existe. E
  `EnvioForaDaJanela` ali é `warning` e `"expirado"`, como no caminho
  principal, e não `error` e `"sem_resposta"`: janela de 24h fechada não é
  recusa permanente, e o `Literal` de `ResultadoDoTurno` existe para essa
  distinção não se perder.
- **O texto julgado nunca entra em log, nas duas direções.** Os eventos
  `moderacao.entrada_bloqueada` e `moderacao.saida_bloqueada`
  (`domain/agente/turno.py`) logam `message_id` e `motivo` (a palavra
  `ENTRADA:BLOQUEAR` ou `SAIDA:BLOQUEAR`), nunca o texto. O adaptador segue a
  mesma regra do lado do erro: a exceção carrega `type(exc).__name__`, nunca
  `str(exc)` nem o texto enviado, porque a mensagem de erro do SDK pode
  ecoar o corpo da requisição.
- **O corpus tem os dois lados, e os de controle valem mais que os
  positivos.** São 41 casos em 4 arquivos — 11 em `entrada_libera.yaml`, 10
  em cada um dos outros três
  (`evals/moderacao/entrada_bloqueia.yaml`, `entrada_libera.yaml`,
  `saida_bloqueia.yaml`, `saida_libera.yaml`) — um moderador que bloqueia
  tudo passa de cara no corpus só-positivo e parece seguro; só o corpus de
  controle (`*_libera`, o que **não** deveria bloquear) separa moderação de
  censura.
  `tests/unit/test_corpus_de_moderacao.py::test_o_controle_de_entrada_cobre_o_falso_positivo_caro`
  exige que o corpus de controle contenha, nomeadamente, lead irritado e
  palavrão usado como ênfase — o falso positivo mais caro deste sistema,
  porque bloquear reclamação legítima perde o cliente que estava
  reclamando. Esse arquivo de teste parametriza dois testes sobre os 7
  arquivos do corpus (os 4 de sempre mais os três da TEC-204 —
  `entrada_injecao`, `entrada_injecao_benigna`, `entrada_injecao_bloqueia`) e
  soma cinco testes únicos: os dois lados existem nas duas direções, o
  controle de entrada cobre o falso positivo caro, os ids são únicos entre
  todos os arquivos, a injeção tem o gêmeo benigno, e o ataque que dita o
  rótulo `BLOQUEAR INJECAO` por extenso está coberto.
- **Nenhum piso foi cravado** para as taxas de acerto do moderador.
  `evals/test_moderacao.py` mede e imprime as quatro taxas por categoria mas
  faz uma única asserção — que o moderador respondeu em todos os casos
  (`indisponiveis == 0`) — de propósito: a TEC-210 já provou que um piso
  cravado sem medição prévia abre vermelho na primeira execução sem
  regressão nenhuma. O piso entra depois, com o número na mão.

### Lacunas conhecidas

- **A moderação de entrada não impede que a fala exista.** Ela roda no
  worker, depois de a ingestão já ter gravado a mensagem cifrada no banco.
  Apagar o que entrou é a TEC-234 e a política de retenção, não esta card.
- **Falha aberta na entrada é buraco declarado, não fechado.** Enquanto o
  moderador estiver fora do ar, falas impróprias entram no contexto do
  agente sem barreira nenhuma. O evento `moderacao.indisponivel` dá
  visibilidade a isso, e visibilidade não é barreira.
- **O turno passa a ter até cinco chamadas que geram texto, contra um
  `job_timeout` que três delas já estouravam sozinhas.** As cinco são
  `resumir`, `classificar`, `desambiguar` e as duas moderações — entrada e
  saída, uma vez cada por turno. O número **exclui** `count_tokens`
  (`contador.contar`), de propósito: ela é um round trip a mais que não gera
  token nenhum, e pode acontecer mais de uma vez no mesmo turno — o laço de
  truncamento de `montar_contexto` reconta a cada corte. Isto era verdade até
  a TEC-229, que fez `_pior_turno()` (`src/mobia/infra/anthropic.py`) derivar
  um número fechado de contagens a partir de `contexto_max_iteracoes` e
  `contexto_gatilho_de_regeneracao` — e voltou a valer com a TEC-290, que
  desfez essa derivação: a fase de montagem ganhou um relógio agregado
  próprio (`Settings.contexto_deadline_de_montagem_segundos`) em vez de um
  número de chamadas, e hoje `_pior_turno()` é constante de novo e lista só
  as fatias limitadas por requisição — sem `resumir` nem `count_tokens`, que
  saem pelo relógio da fase, não por contagem. `resumir` + `classificar` +
  `desambiguar` já somavam 360s de pior caso antes desta card (TEC-135,
  cliente de 120s por chamada); a moderação soma 10s, num cliente com teto de
  5s por chamada: marginal contra um orçamento que já estava estourado, não a
  causa dele. Reduzir a chance de o turno estourar o `job_timeout` é a
  TEC-228, não esta card.
- **Falso positivo custa atendimento, e nada no código limita a taxa.** O
  corpus de controle (`*_libera`) mede quantas vezes o moderador bloqueia o
  que deveria liberar; medir não é impedir, e não há piso nem teto de código
  agindo sobre esse número.
- **Não há revisão humana de bloqueios.** Um lead barrado pela moderação de
  entrada, ou uma resposta barrada na saída, não chega a nenhum humano para
  reavaliação. Handoff é a TEC-174.
- **A moderação julga texto isolado, não a conversa.** Cada chamada recebe
  só o texto do turno atual, sem o histórico. Falas individualmente
  inofensivas podem compor assédio ao longo de vários turnos sem que nada
  aqui veja isso.
- **O eval de moderação nunca foi executado.** `evals/test_moderacao.py`
  existe e mede quatro taxas reais contra o corpus de 41 casos, mas até este
  README ser escrito ninguém rodou `pytest evals` com ele — as duas taxas
  (falso positivo e falso negativo, nas duas direções) são desconhecidas.
- **A fala bloqueada na entrada volta ao contexto no turno seguinte.** É a
  lacuna mais séria desta card, e o spec afirma o contrário — *"o que ela
  impede é que a fala vire contexto, resposta e resumo"*. Isso vale para o
  turno em que a fala chega, e só para ele. O bloqueio retorna cedo e
  economiza aquele turno, mas a linha da mensagem continua em `messages`,
  vira `PROCESSED` como qualquer outra (`workers/jobs/process_message.py`
  grava o status pelo desfecho, e o bloqueio devolve `"respondido"`) e **não
  recebe marca nenhuma de bloqueio**. `literais_apos`
  (`src/mobia/domain/context/janela.py`) seleciona por conversa e marca-d'água
  do resumo; não filtra moderação. Então o lead manda M1 (bloqueada), recebe
  a recusa, manda M2 — e o turno de M2 monta contexto decifrando M1 inteira
  para dentro do prompt. Na dobra dos ~40, M1 entra no resumo e fica lá
  permanentemente. O que resolveria é uma marca de bloqueio na própria linha
  da mensagem mais um filtro por ela na janela; é card próprio, e não está
  feito. Até lá, o que a moderação de entrada impede é que a fala vire
  **resposta naquele turno** — não que ela vire contexto ou resumo depois.
- **A indisponibilidade prolongada do moderador custa cinco turnos pagos por
  mensagem e termina em silêncio.** Com o provedor fora do ar nas duas
  pontas, a entrada falha aberta (o turno segue e paga `classificar`, e a
  montagem pode pagar `resumir`) e a saída falha fechada (a exceção propaga,
  nada é entregue). A linha vira `FAILED`, o sweeper reenfileira, e cada
  tentativa paga tudo de novo até `sweep_max_attempts` (5); depois disso ela
  fica em `FAILED` para sempre e o lead não recebe nada. É consequência
  defensável de "a saída fecha" — entregar texto não moderado é o risco que
  esta card existe para fechar —, mas o preço é este, e não estava escrito em
  lugar nenhum.
  `tests/integration/test_moderacao_de_saida.py::test_moderador_fora_do_ar_nas_duas_pontas_paga_o_turno_e_nao_entrega`
  fixa o comportamento composto.
- **Mensagem sem texto não passa pela moderação de entrada.** O `if corpo:`
  de `executar_turno` pula o bloco inteiro quando `text_body` é nulo — áudio,
  imagem, documento, e o tipo desconhecido. Hoje é inofensivo, porque não há
  texto a julgar: `montagem.py` põe um marcador (`(audio, sem transcricao)`)
  no lugar. Mas "moderação em 100% dos turnos" não é literalmente verdade, e
  deixa de ser inofensivo no dia em que a transcrição existir — o texto
  transcrito chegaria ao contexto sem ter passado por lugar nenhum. Quem
  implementar transcrição tem de mover a moderação para depois dela.

## TEC-145 — Extração de qualificação do lead

Até aqui o agente classificava intenção e respondia, e parava aí: o que o
lead dizia sobre o que procura — região, orçamento, quartos, forma de
pagamento — se perdia depois do turno, e cada pergunta seguinte partia do
zero. Esta card faz essa fala virar estado estruturado, persistido, e
consultável por SQL — pré-requisito declarado da TEC-147, TEC-150 e TEC-158.

`Extracao` (`src/mobia/domain/agente/schemas.py`) é o contrato: nove campos,
todos anuláveis, sem `intencao` — quem classifica intenção é o classificador,
e duas fontes para o mesmo fato divergiriam (a divergência apareceria como bug
de score na TEC-150). Todo campo anulável tem um significado exato: `None` é
"o lead não falou disso **neste turno**", nunca "esqueça o que sabia" — quem
apaga com esse sentido é `preenchidos()`, que descarta só os `None` e
preserva `False` (`tem_imovel_para_vender`) e `0` (`vagas`) como informação
válida. `FormaPagamento.INDEFINIDA` **não** é sinônimo de `None`, e a TEC-246
escreveu a diferença no docstring de `Extracao` antes de escrever fala que a
usasse: `None` é "o lead não falou de pagamento neste turno", `INDEFINIDA` é
"o lead afirmou que ainda não decidiu". O valor existia no enum sem
significado escrito em lugar nenhum — fora a própria linha que o declara em
`FormaPagamento`, nenhum **uso** de `INDEFINIDA` em `src/` era deste enum;
todos os outros são de `Intencao` —, e anotar uma fala para ele antes disso seria
inventar o significado de passagem.

A extração viaja **na mesma chamada** que já classifica e responde — sem
`tool` separada, sem chamada extra. `SCHEMA_DA_EXTRACAO`
(`classificador.py`) entra como mais uma propriedade de
`SCHEMA_DA_RESPOSTA`, e a nulidade de cada campo é `anyOf: [tipo, null]`, não
`type: [tipo, "null"]` — `transform_schema` do SDK despacha por um `Literal`
de tipos únicos e estoura em `assert_never` no segundo formato, e a falha
seria no import do módulo, não numa chamada. `extrair()` **nunca levanta**:
preço fora de `numeric(12,2)`, `quartos`/`vagas` fora de 0–20, `regiao` acima
de 120 caracteres ou um booleano lido como `1 quarto` (`isinstance(True,
int)` é verdadeiro em Python) são descartados campo a campo — um valor
malformado não pode derrubar a resposta entregável, porque a extração é
enriquecimento e a resposta é o produto.

`gravar_estado` (`src/mobia/domain/context/repositorio.py`) grava só o que
veio: o `UPSERT` monta `SET` a partir de `extracao.preenchidos()`, então um
campo que o lead não mencionou neste turno nunca aparece no `SET` e não pode
sobrescrever com `NULL` o que já estava lá. `FORA_DE_ESCOPO` não grava nada —
a guarda mora aqui, não em quem chama, para que não haja como esquecê-la — e
"não grava" também não é "apaga": o lead que qualificou e depois mandou uma
piada continua com o que disse. A função não commita; `executar_turno` grava
intenção e estado no mesmo commit, porque os dois fatos vêm da mesma chamada.

### A medição: corpus anotado, estado acumulado no runner, precisão no gate

O eval da TEC-210 media só intenção; esta card estende o mesmo corpus e o
mesmo runner para medir extração, sem pagar chamada nova.

`TurnoAnotado.campos` (`src/mobia/evals/corpus.py`) é a chave nova do YAML,
com três estados que significam três coisas diferentes:

| estado | valor no YAML | significado |
|---|---|---|
| ausente | chave não escrita | o turno fica fora da medição de extração — "não sei enumerar com confiança tudo o que esta fala afirma" |
| vazio | `campos: {}` | o turno está anotado por completo, e o completo é nada — "o lead não afirmou nada neste turno", tudo que o modelo devolver aqui é invenção |
| preenchido | `campos: {...}` | o turno afirma alguma coisa, e a anotação diz exatamente o quê |

`campos:` **sem valor** — o typo de escrever a chave e esquecer o `{}`, que o
YAML lê como `None` — é **recusado** com `CorpusInvalido` em vez de cair num
dos dois estados acima: são dois significados opostos ("fora da medição" e
"nada foi afirmado, tudo é invenção") a dois caracteres de distância, e
herdar um deles por acidente de digitação seria pior que estourar. A
mensagem manda escolher — omitir a chave, ou escrever `campos: {}`.
`campos` presente (vazio ou preenchido) é contrato de anotação **completa**:
`precisao_da_extracao` conta campo extraído que não está na anotação como
erro, então uma anotação parcial não vira nota mais baixa do modelo — vira
medição errada. `carregar` valida cada valor contra o vocabulário fechado
(`TipoImovel`, `Urgencia`, `FormaPagamento`) e recusa campo desconhecido ou
fora do vocabulário no carregamento, antes de qualquer chamada paga.

`TurnoAnotado` ganhou três propriedades para ler esses estados —
`anotado` (`campos is not None`), `positivo` (`campos is not None and
campos != {}`) e `negativo` (`campos == {}`). Elas existem porque, antes
desta onda, quatro lugares testavam `campos` por veracidade (`if
turno.campos`) e um por `is not None`, e as duas formas coincidiam
perfeitamente enquanto `{}` era impossível de anotar — um dicionário vazio e
`None` são igualmente falsy, então `if turno.campos` não distinguia "fora da
medição" de "anotado como vazio": leria um turno negativo como se não
estivesse anotado. Os três pontos que vigiam o piso de anotação — o pré-voo
(`evals/conftest.py`), o corpus commitado no CI
(`tests/unit/test_evals_corpus_real.py`) e a amostra sobrevivente depois do
abandono (`evals/test_acuracia_de_intencao.py`) — passaram a usar as
propriedades novas em vez da veracidade do campo.

`_rodar_conversa` (`evals/test_acuracia_de_intencao.py`) acumula um
`estado_acumulado: dict[str, Any]` turno a turno e passa
`contexto_do_historico(..., estado=LeadQualification(**estado_acumulado))`
a cada chamada — `LeadQualification` aqui é o mesmo padrão transiente que
`mensagem_transiente` já usa, nunca vai a sessão nenhuma. Sem isso a medição
de "não repergunta campo preenchido" mediria estado sempre vazio: o modelo
nunca teria visto o campo. A acumulação chama `campos_a_gravar(intencao,
extracao)` (`src/mobia/domain/context/repositorio.py`) e faz
`estado_acumulado.update(...)` com o retorno — a mesma função que
`gravar_estado` usa em produção, extraída nesta onda porque o runner tinha
uma cópia da regra que divergia dela em duas frentes: acumulava por cima da
guarda de `FORA_DE_ESCOPO` (produção não grava nada nesse turno; o runner
acumulava o que o modelo extraiu de qualquer forma) e nunca guardava
`intencao` (produção sempre grava; o `LeadQualification` sintético do eval
nunca carregava a linha `intencao: X` que `montagem._texto_do_estado` põe no
prompt real a partir do segundo turno — diferença de prompt em praticamente
todo turno de uma conversa com troca de intenção, que é exatamente o que o
corpus de borda existe para exercitar). Com a função compartilhada as duas
pontas não podem mais divergir sem que o teste da outra ponta quebre junto.

`precisao_da_extracao` (`src/mobia/evals/metricas.py`) compara pelo
denominador da **união** entre esperado e obtido, por turno: só o esperado no
denominador daria 100% a um modelo que acerta o anotado e inventa mais
quatro campos; só o obtido daria 100% a um modelo que nunca extrai nada — o
mesmo furo que a TEC-233 fechou no corpus de moderação, na direção oposta.
Ela **entra em `_metricas_de` e em `bloqueia`**: ao contrário das três
métricas `SEM_MECANISMO` que a TEC-210 deixou declaradas, a extração agora
tem sujeito, e uma precisão abaixo do piso de 85% (`PISO_DE_PRECISAO_DA_EXTRACAO_PCT`)
reprova a execução — a mesma faixa vermelha/amarela/verde de `faixa_de`, com
piso próprio em vez de herdar 90/84 da intenção.

`PISO_DE_TURNOS_ANOTADOS = 45` (`src/mobia/evals/metricas.py`) é o piso
irmão de `PISO_DE_TURNOS`, na outra direção: sem ele, anotar três turnos
fáceis daria 100% de precisão num corpus que não mede nada — o nome é
histórico, e o piso confere `turno.positivo`. Hoje **62 turnos estão
anotados como positivos**, distribuídos em `evals/corpus/compra.yaml` (29),
`evals/corpus/aluguel.yaml` (14), `evals/corpus/follow_up.yaml` (8),
`evals/corpus/investimento.yaml` (6) e `evals/corpus/borda.yaml` (5).
`compra`, `aluguel` e `investimento` ganharam a chave `campos` na TEC-145;
`borda` e `follow_up`, na TEC-239, que precisou dos turnos de injeção e de
venda para tirar quatro campos do zero. A TEC-242 acrescentou sete a esse
total: turnos que citavam sinônimo de tipologia (*kitnet*, *studio*,
*flat*, *cobertura*, *sobrado*) e ficavam fora da medição só por não haver
regra que traduzisse a palavra do lead para o vocabulário de `TipoImovel`.
A TEC-245 acrescentou dez, ao ler uma por uma as falas que
estavam fora da medição sem decisão escrita — a maioria em `follow_up` e
`borda`, que são os arquivos onde o lead se refere a um imóvel já visto e a
anotação exige decidir se a fala o **nomeia** ou só aponta para ele (ver
"Lacunas conhecidas"). A TEC-246 acrescentou os sete últimos, todos em
`compra`: seis vêm das três conversas novas que ela escreveu para fechar a
cobertura por valor, e o sétimo é `compra-10` índice 0 (*"nosso primeiro
imovel"*), que era negativo e passou a `{tem_imovel_para_vender: false}` —
como negativo a régua cobrava invenção de um modelo que lesse a fala com
razão.
`aluguel-02` carrega o caso de correção que a D4 do spec pediu com risco
declarado: o lead troca de região no meio da conversa (`brooklin` →
`itaim bibi`), e é o turno que prova que a sobrescrita pelo mais novo tem
cobertura de medição.

`PISO_DE_TURNOS_NEGATIVOS = 53` (`src/mobia/evals/metricas.py`) é o piso
irmão de `PISO_DE_TURNOS_ANOTADOS` numa terceira direção: aquele responde
"sobrou amostra para medir acerto?"; este responde "sobrou amostra para
pegar invenção?" — e os dois são separados de propósito, porque um piso
único sobre "todo turno anotado" se auto-satisfaria (30 turnos negativos sem
invenção nenhuma dariam denominador zero, e `faixa_de` levantaria
`ValueError` em vez de reportar — o mesmo furo entrando por outra porta). A
TEC-238 anotou 39 turnos negativos, e esta revisão tirou dois que eram
pergunta de processo pressupondo campo, não ausência de afirmação
(`follow-up-03` índice 1 e `aluguel-09` índice 2), restando 37 — os dois
voltaram a ser negativos na TEC-246, que tirou a pressuposição do critério
de exclusão (ver "Lacunas conhecidas"). A TEC-245 acrescentou 29 ao passar o
corpus inteiro sob o mesmo critério, chegando a 66, e a TEC-246 fechou em
**70 turnos negativos**: os dois de volta acima, mais `borda-mista-01`
índice 2 pelo mesmo motivo, mais dois das conversas novas, menos
`compra-10` índice 0, que virou positivo. Estão distribuídos em
`evals/corpus/investimento.yaml` (21),
`evals/corpus/borda.yaml` (17), `evals/corpus/aluguel.yaml` (12),
`evals/corpus/follow_up.yaml` (12) e `evals/corpus/compra.yaml` (8). A
TEC-238 tinha concentrado os negativos em `borda` e `follow_up`, os
arquivos com mais turno de saudação, despedida e assunto fora de escopo,
onde "o lead não afirmou nada" é a leitura mais direta; a TEC-245 desfez
essa concentração ao mostrar que o resto do corpus é dominado por outra
forma de fala igualmente clara — pergunta de processo dirigida ao corretor.
`investimento` passou de 6 para 21 negativos, quinze dos vinte e nove que a
triagem acrescentou, porque é o arquivo em que o lead mais pergunta sobre
serviço e custo em vez de dizer o que procura. O piso vem do pior caso de
abandono, no mesmo molde de `TETO_DE_CONVERSAS_ABANDONADAS`: as cinco
conversas com mais negativos somam 15, então a execução mais azarada ainda
deixa 70 − 15 = 55 negativos de pé, e o piso fica em 53, com folga de dois.

`discrepancias_da_extracao` (`src/mobia/evals/metricas.py`) decompõe, campo a
campo, o que `precisao_da_extracao` conta como erro. É **diagnóstico, nunca
gate**: não devolve faixa e não entra em `bloqueia`. Existe porque o número da
métrica sozinho não diz se o corpus mede errado ou se o modelo extrai mal, e
essas duas causas pedem cards diferentes. Cada `Discrepancia` carrega
`conversa_id` e `indice` justamente para que quem for anotar não precise de
outra execução paga só para descobrir **onde** faltava anotação.

Os três tipos não são simétricos, e ler isso errado custa a card errada:

| tipo | o que aconteceu | de quem é o problema |
|---|---|---|
| `extra` | o modelo extraiu, o corpus não anotou | acusa a **medição** antes do modelo |
| `faltou` | o corpus anotou, o modelo não devolveu | acusa o **modelo** ou o prompt |
| `divergiu` | veio nos dois, com valores diferentes | acusa o modelo, ou a anotação |

`extra` é o que mais engana. Com o denominador de união, um campo que o modelo
extraiu **certo** e que ninguém anotou desconta exatamente como uma invenção —
campo com muitos `extra` e pouca anotação no corpus é candidato a lacuna de
anotação, não a defeito do modelo. Era a leitura que a TEC-238 precisaria para
separar invenção de anotação faltante nos 56 turnos sem `campos` de então; a
TEC-245 fez essa separação por leitura das falas, sem execução paga, e sobraram
17 turnos sem `campos`; a TEC-246 tirou mais três ao dar eixo único ao
critério, e são hoje **14** — todos com motivo escrito. A execução
de 28/08 já exerceu essa leitura contra dados reais uma vez, e foi assim que
`regiao` apareceu como o maior balde de discrepâncias — mas contra o corpus
de antes da TEC-239 e da TEC-238, e sem turno negativo nenhum. A execução de
30/08 (TEC-247) a exerceu com 70 turnos negativos, e a leitura se pagou: dos 5
`extra` da execução, **1 caiu em turno negativo** — invenção sem discussão
possível — e os outros 4 em turnos positivos, onde continuam ambíguos entre
invenção e anotação faltante. Sem a separação, os cinco pareceriam a mesma
coisa.

Uma invariante amarra as duas funções contra a mesma sequência de observadas:
`acertos + len(discrepancias) == total`. Há teste guardando
(`test_acertos_mais_discrepancias_fecham_o_total_da_metrica`), porque as duas
derivam do mesmo conjunto — a união do esperado com o obtido — e mudar a fórmula
de uma sem mudar a outra faria o relatório mentir em silêncio em vez de quebrar.
A ordem da lista acompanha os turnos observados, e dentro do turno é alfabética
por campo: quem lê, lê de cima para baixo seguindo a conversa, e a ordem não pode
depender da iteração de um `set`.

No relatório, `_secao_de_extracao` (`src/mobia/evals/relatorio.py`) imprime o
agregado por campo antes da lista por turno — o agregado diz onde está o
problema, e o endereço é o que evita pagar outra execução para achar onde anotar.

O proxy de repergunta (`MARCADORES_DE_REPERGUNTA`,
`evals/test_acuracia_de_intencao.py`) conta, por palavra-chave, quantas
vezes a resposta do agente parece reperguntar um campo que o estado
**já tinha** antes daquele turno (`conhecidos_antes`, capturado antes da
chamada). Ele é **diagnóstico, nunca gate**, pelo mesmo motivo que
`ResumoDeConfianca` já é diagnóstico no relatório da TEC-210: aparece numa
seção própria do relatório (`render(..., reperguntas=...)`,
`src/mobia/evals/relatorio.py`), mas não entra em `_metricas_de` nem em
`bloqueia`.

### Garantias

- **A extração não paga chamada extra.** Ela viaja no mesmo schema
  estruturado que já classifica intenção e escreve a resposta — o eval não
  precisou de nenhuma chamada nova para medi-la, só estender o corpus e o
  runner que a TEC-210 já pagava.
- **`CONTEXTO_HEADROOM_DE_TOKENS` subiu de 400 para 800 nesta card**
  (`src/mobia/app/config.py`, commit `68eddb6`). O schema de saída ganhou o
  objeto `extracao`, e ele sozinho custa ~263 tokens enviados em toda chamada
  e nunca contados por `montar_contexto` — a mesma ordem de grandeza do
  déficit que a TEC-134 já tinha medido para o resto da requisição. **Os
  números a seguir são os medidos nesta card e não valem hoje** (a reserva
  subiu de novo na TEC-250, e o prompt cresceu duas vezes; os de hoje saem de
  `python -m pytest -q -k margem_do_orcamento -s`): a subcontagem subiu para
  526; com a reserva em 400 ela nem passava mais na primeira asserção de
  `test_diferenca_entre_o_contado_e_o_enviado` (`subcontagem < headroom`, e
  526 não é menor que 400). Com a reserva em 800 ela passava nas duas, com 74
  tokens de folga antes da segunda (headroom × 0,75 = 600) voltar a disparar.
  Preço: 400 tokens a menos de literais e resumo por turno, de um teto de
  12000 — 3,3% do contexto, em troca de extração estruturada. Ver o item "O
  teto comparado é o nominal menos `CONTEXTO_HEADROOM_DE_TOKENS`" na seção
  TEC-127 acima.
- **`intencao` está fora de `Extracao` de propósito**, e fica assim mesmo
  tendo aparecido nos dois lugares onde seria conveniente incluí-la — o
  schema da chamada e `campos` do corpus. Duas fontes de intenção divergiriam
  em silêncio; só o classificador decide.
- **Nenhuma guarda de `extrair()` derruba o turno.** Preço, quartos/vagas,
  região e o booleano de "tem imóvel para vender" são validados um a um, e um
  campo malformado é descartado sozinho — os outros campos e a resposta ao
  lead seguem intactos.
- **`None` nunca apaga, `FORA_DE_ESCOPO` não grava nada, e `intencao` sempre
  entra quando há gravação — em produção e na medição, pela mesma função.**
  `campos_a_gravar(intencao, extracao)` (`src/mobia/domain/context/repositorio.py`)
  é a regra única: `gravar_estado` usa o retorno para montar o `SET` do
  upsert, e o runner do eval usa o mesmo retorno para o `estado_acumulado.update(...)`
  turno a turno. Antes desta onda cada lado tinha sua própria cópia da regra,
  e divergiam em duas frentes — ver "A medição" acima.
- **`FORA_DE_ESCOPO` não grava nada, e a guarda mora em `campos_a_gravar`**, o
  único lugar que os dois chamadores passam — não há como esquecê-la em um
  novo caminho de chamada futuro.
- **O corpus valida o vocabulário no carregamento, antes de qualquer chamada
  paga.** `carregar` recusa campo desconhecido ou valor fora de `TipoImovel`,
  `Urgencia` ou `FormaPagamento` com o arquivo e a conversa no erro — o mesmo
  padrão de validação adiantada que o piso de turnos da TEC-210 já usava.
- **A precisão de extração pune os dois lados da conta nos 132 turnos
  medidos — 62 positivos e 70 negativos.** Pela união entre campos esperados
  e obtidos, nem um modelo que inventa campos, nem um que nunca extrai nada,
  tira 100% de graça **nesse subconjunto**, e desde a TEC-238 os negativos
  (`campos: {}`, "o lead não afirmou nada neste turno") fecham a metade que
  faltava: sem eles um modelo podia inventar à vontade em todo turno sem
  anotação positiva e não pagar por isso em lugar nenhum. Os outros 14 turnos
  do corpus continuam fora da medição — chave `campos` ausente é o único
  jeito de anotar "não sei enumerar com confiança tudo o que esta fala
  afirma" —, e invenção neles não é medida por ninguém. A diferença desde a
  TEC-245 é que esses 14 são **o conjunto inteiro dos que ficam de fora**, e
  cada um é decisão com motivo escrito: `_FORA_DA_MEDICAO`
  (`tests/unit/test_evals_corpus_real.py`) declara os 14, e um turno novo sem
  `campos` quebra o CI até alguém decidir para onde ele vai. Ver "Lacunas
  conhecidas".
- **A regra "o imóvel que o lead TEM não é o que ele procura" ganhou teste.**
  Ela é da TEC-239, mora no docstring de `TurnoAnotado` e até a TEC-245 valia
  só por disciplina de quem anotava. O guarda de sinônimos da TEC-242 varre
  *kitnet*, *studio*, *flat*, *cobertura*, *sobrado* e *república* — mais
  *chácara* e *sítio*, que a TEC-246 acrescentou —, e não as
  palavras **literais** do vocabulário: um turno que dissesse "apartamento"
  com todas as letras e não anotasse `tipo_imovel` entrava em silêncio, que é
  exatamente a falha que a TEC-242 nomeou e fechou pela metade.
  `test_todo_turno_com_palavra_do_vocabulario_tem_tipo_imovel_anotado`
  (`tests/unit/test_evals_corpus_real.py`) varre `apartamento`, `apto`,
  `casa`, `terreno` e `sala comercial` com fronteira de palavra, e tem duas
  exceções nomeadas — `follow-up-03` índice 0 ("comprei um apartamento com
  vocês faz 3 anos") e `follow-up-06` índice 0 ("quero colocar meu apartamento
  à venda") —, que são o caso literal da regra: os dois anotam
  `tem_imovel_para_vender: true` e nenhum anota `tipo_imovel`, e os dois estão
  certos. As exceções não são válvula de escape: turno novo tem de escolher
  entre anotar o tipo e entrar na lista com motivo escrito.
- **A cobertura passou a ser por valor de vocabulário, e não só por campo.**
  Até a TEC-246 o teste exigia uma anotação por **campo**, e seis valores
  ficavam em zero — `RURAL`, `CONSORCIO`, `FormaPagamento.INDEFINIDA`,
  `SEM_PRESSA`, `ATE_6_MESES` e `tem_imovel_para_vender: false`, este último o
  caso que `preenchidos()` existe para preservar. Uma regressão restrita a um
  deles passava o gate. Hoje `test_todo_valor_do_vocabulario_tem_anotacao`
  (`tests/unit/test_evals_corpus_real.py`) exige **todo membro** de
  `TipoImovel`, `Urgencia` e `FormaPagamento`, mais os dois booleanos de
  `tem_imovel_para_vender`, e o conjunto esperado sai de `_VOCABULARIO` — o
  mesmo mapa que `carregar` usa para validar o YAML — iterando os membros de
  cada enum, e não de uma lista escrita à mão. **Valor novo no
  vocabulário nasce quebrando o CI**, em vez de nascer descoberto em silêncio:
  é a mesma classe de furo que `test_toda_intencao_do_enum_aparece` já fechava
  para `Intencao`.

  **O preço, declarado:** cinco dos seis valores foram fechados por **fala
  nova**, em três conversas escritas para o vocabulário — `compra-13`
  (chácara, `RURAL` + `SEM_PRESSA`), `compra-14` (`CONSORCIO` +
  `ATE_6_MESES`) e `compra-15` (`INDEFINIDA`). Elas não vêm de tráfego nem de
  arquétipo observado: existem porque o enum tem esses membros. O corpus
  inteiro já é sintético (ver a lacuna correspondente na seção TEC-210), mas
  estas três o são num sentido mais forte, e quem for ler um número baixo
  nesses turnos precisa saber que a fala foi escrita para o valor, e não o
  valor colhido da fala. O sexto — `tem_imovel_para_vender: false` — foi o
  único fechado sem fala nova: `compra-10` índice 0 (*"nosso primeiro
  imovel"*) já existia e estava anotado `{}`, o que cobrava invenção de um
  modelo que lesse a fala com razão. Escrever fala nova para os outros cinco
  foi **escolha declarada**, e a alternativa era deixar a lacuna aberta.
- **Há teste de correção de região no corpus**
  (`tests/unit/test_evals_corpus_real.py::test_ha_turno_de_correcao_anotado`),
  porque a sobrescrita "mais novo vence, sem histórico" é a decisão do spec
  com risco mais declarado (D4), e sem um caso anotado ela não tinha cobertura
  de medição nenhuma.
- **TEC-241 dá forma canônica a `regiao`, e é decisão registrada, não só
  código** (`docs/superpowers/specs/2026-08-29-tec-241-contrato-de-forma-da-regiao-design.md`,
  emenda ao spec desta card). `normalizar_regiao`
  (`src/mobia/domain/agente/schemas.py`) é a única regra de forma, com dois
  consumidores: `extrair` grava canônico em `lead_qualification.regiao`, e
  `_comparavel` (`src/mobia/evals/metricas.py`) compara canônico contra
  canônico na medição. Uma função só, e não duas — o mesmo motivo que já
  matou `faixa_de_catastrofe` duplicada e levou `campos_a_gravar` a ser
  compartilhada entre produção e eval (ver acima): duas cópias da mesma regra
  divergem, mais cedo ou mais tarde. Ela colapsa espaço, aplica `casefold` e
  tira prefixos de referência (`perto da`, `perto de`, `regiao do`,
  `estacao`, …) do início da string, **repetidamente** até não sobrar
  nenhum — mas **nunca tira `zona`**: `zona leste`, `zona sul` e `zona oeste`
  são o nome da região, não ruído de referência.
- **A TEC-246 emparelhou as três assimetrias da lista de prefixos.** A lista
  tratava as famílias de forma desigual sem que nada explicasse por quê: `na
  regiao` tinha `da` e `do` e ignorava `de`, `das` e `dos`; `proximo` e `perto`
  tinham o singular e não o plural; e `perto` tinha `de` e `proximo` não.
  Entraram oito prefixos — a lista vai de 15 para 23 —, e
  `test_normalizar_regiao_trata_as_familias_de_prefixo_simetricamente`
  (`tests/unit/test_extracao.py`) trava as oito formas novas. A terceira
  fechou só na revisão final da card, e vale registrar por quê: ela era
  falsificável em uma chamada — `normalizar_regiao("perto de metro")` devolvia
  `"metro"` e `normalizar_regiao("proximo de metro")` devolvia a string
  inteira — e mesmo assim **não foi decisão escrita nenhuma:** a tabela da D9
  do spec desta card lista `proximo …` como tendo `da`, `do`, `ao`, `a` e
  faltando só `das`/`dos` — `de` não aparece na coluna do que falta, então
  nunca entrou em escopo para ser recusado, foi esquecido. A própria decisão
  que existe para fechar assimetria reproduziu uma, o que é a evidência mais
  forte que este bullet tem a favor da sua própria tese. O furo
  era **latente**, e é por isso que ele merece registro em vez de passar como
  conserto de rotina: o corpus só exercitava `na regiao da/do`, então a régua
  nunca tocaria nas oito formas novas, e nada quebraria até um lead real
  escrever uma delas — *"na regiao de"* é português corrente. O que dá peso à
  hipótese é a única execução paga que este projeto tem: forma não-canônica de
  `regiao` respondeu por **10 das 29 discrepâncias** de 28/08, o maior balde
  da execução, todas `divergiu` por desacordo de forma. Foi o que originou a
  TEC-241, e é exatamente a discrepância que um prefixo desconhecido produz —
  a fala do lead não é limitada às formas que o corpus escreveu.
  `test_normalizar_regiao_nao_come_o_de_de_um_toponimo` guarda o outro lado:
  `das` só sai depois de `regiao`, `proximo` ou `perto`, senão a anotação
  `regiao: jardim das flores` de `compra-04` deixaria de casar consigo mesma.
- **Normalizar perde informação, e a perda é aceita por escrito.** `"perto da
  usp"` e `"usp"` viram a mesma string depois de normalizadas; o lead que
  disse a primeira queria proximidade, não necessariamente o campus, e essa
  distinção some do valor gravado. A troca é a favor do filtro SQL por
  igualdade que a TEC-158 precisa — o texto original da fala continua
  intacto no histórico de mensagens, cifrado, que é onde ele sempre esteve.
- **Esse consolo tem prazo de validade.** `_texto_do_estado`
  (`src/mobia/domain/context/montagem.py`) entra no prompt de verdade que o
  modelo lê a cada turno, não só na estimativa de tokens — então a partir
  desta card a memória que o modelo enxerga passa a mostrar `regiao: vila
  madalena` em vez da fala original do lead. Enquanto as mensagens literais
  que carregam "perto da" ainda estiverem na janela de contexto, a intenção
  de proximidade continua visível ao modelo por elas; quando saem da janela
  (dobradas em resumo, ou truncadas), essa intenção some da visão do modelo
  também, não só do banco — o histórico cifrado continua existindo, mas deixa
  de ser lido a cada turno.
- **É mudança de comportamento de produção, sem migração retroativa.** Os
  registros já gravados em `lead_qualification.regiao` ficam na forma velha;
  não há migração dos dados existentes, e por um tempo a coluna terá as duas
  formas — velha e canônica — convivendo. A próxima fala do lead sobre a
  mesma região sobrescreve pelo mais novo (D4 acima), então o convívio se
  resolve sozinho por reincidência, não por migração.
- **O número foi medido pela TEC-247, e o critério de aceite não se
  sustentou.** O critério da TEC-241 — "as divergências de `regiao` caem para
  perto de zero numa execução do gate" — exigia execução paga, que esta card
  não fez; ela rodou em 30/08/2026 e **`regiao` continua sendo o maior balde
  de discrepâncias: 7 `divergiu`**, todas de forma, sem nenhum `extra` nem
  `faltou`. Sete não é perto de zero. Os endereços estão em
  `evals/relatorios/2026-08-30-corpus-6d74cff.md`. **Isso não é uma medida de
  efeito da normalização:** os 29 de 28/08 (10 deles de `regiao`) não servem
  de "antes" — o corpus mudou desde então em seis cards, não duas — TEC-238,
  TEC-239, TEC-241, TEC-242, TEC-245 e TEC-246 —, e as anotações de campo foram
  de 47 para 96, não para 59. "10 caiu para 7" não quer dizer nada. O que a
  execução afirma é só o estado de hoje: normalizado dos dois lados, `regiao`
  ainda diverge mais que qualquer outro campo.
- **Os sinônimos de `tipo_imovel` têm dono: a TEC-242.** Eram 8 das 29
  discrepâncias na execução de 28/08 — a TEC-241 tinha mandado esse problema
  para a TEC-239, mas a TEC-239 é sobre cobertura de campo sem anotação, não
  sobre sinônimo de vocabulário, e a referência estava errada. A regra que
  faltava é um mapa de sete entradas — cinco escritas pela TEC-242, duas
  acrescentadas pela TEC-246 —, registrado como regra de **anotação**
  no docstring de `TurnoAnotado` (`src/mobia/evals/corpus.py`), não em
  código de produção: `kitnet`, `studio`, `flat` e `cobertura` se anotam
  `APARTAMENTO`; `sobrado` se anota `CASA`; e `chacara` e `sitio` se anotam
  `RURAL`, pelo mesmo raciocínio das cinco primeiras —
  ninguém diz "quero comprar um rural", e sem a tradução no corpus a
  extração certa contaria `extra`. **Não é código de propósito:** o
  schema da chamada ao modelo é estrito — `tipo_imovel` só aceita valor de
  `TipoImovel` —, então o modelo nunca devolve "kitnet"; ele já traduz
  sozinho e devolve `APARTAMENTO`. Um mapa de tradução em código de produção
  nunca teria entrada para percorrer — seria código morto. O que faltava era
  o corpus decidir a mesma tradução: sem ela, o modelo acertando a tradução
  contava como `extra` — erro cheio, por acertar. A exceção:
  `república` fica **fora** do mapa porque é uso, não tipologia —
  pode ser casa ou apartamento —, e o único turno que a usa (`aluguel-07`
  índice 0, "república ou kitnet") oferece duas tipologias sem escolher
  nenhuma, então fica sem `tipo_imovel`, de propósito.

  **O que fica perdido:** *kitnet*, *studio*, *flat* e *cobertura* deixam de
  se distinguir de *apartamento* no estado de qualificação, e isso muda
  faixa de preço e metragem esperadas para o lead — um kitnet e uma
  cobertura duplex não pedem o mesmo orçamento, e o estado agora lê os dois
  como o mesmo valor. Preservar a distinção exigiria alargar `TipoImovel`, o
  que mexe na coluna `lead_qualification.tipo_imovel`, no filtro SQL que a
  TEC-158 faz sobre ela e no orçamento de contexto do prompt, cuja folga
  sempre coube em dezenas de caracteres, nunca em centenas — `python -m pytest
  -q -k margem_do_orcamento -s` diz quantos são hoje. **É escolha, registrada
  aqui, não esquecimento.**

  E o agravante que a TEC-240 registrou vale igual aqui: `_texto_do_estado`
  entra no prompt de verdade que o modelo lê a cada turno, não só na
  estimativa de tokens — então a memória que o próprio modelo enxerga também
  passa a mostrar `APARTAMENTO` em vez de "kitnet". Enquanto a mensagem
  literal do lead ainda estiver na janela de contexto, a palavra original
  continua visível por ela; quando sai da janela (dobrada em resumo, ou
  truncada), a palavra do lead some da visão do modelo também, não só do
  estado gravado.

  **O efeito desta card continua sem baseline comparável, e sempre vai
  continuar.** As 8 discrepâncias de sinônimo são da execução de 28/08 —
  anterior à TEC-238, à TEC-239, à TEC-240, à TEC-241, a esta card, à
  TEC-245 e à TEC-246. Sete mudanças de corpus e de prompt depois, um "antes"
  daquele tamanho não serve de baseline, e a execução da TEC-247 (30/08/2026)
  não conserta isso retroativamente: ela mede o efeito desta regra **e** o de
  outras seis cards ao mesmo tempo, sem jeito de separar as causas — a mesma
  ressalva que o bullet de `regiao`, logo acima, já faz para a própria lacuna.
  O que ela dá é o **estado de hoje**, e só ele: `tipo_imovel` respondeu por 6
  das 21 discrepâncias, metade `faltou` e metade `extra` — empatado com
  `urgencia` e atrás de `regiao`.
- **O proxy de repergunta nunca bloqueia**, e há comentário no próprio
  `MARCADORES_DE_REPERGUNTA` dizendo por quê: é heurística de palavra-chave,
  com erro nas duas direções. Ver "Lacunas conhecidas".

> **Nota da TEC-240 (29/08/2026).** Os números de orçamento deste bloco são
> os medidos naquela data e **não valem hoje** — a TEC-250 gastou a margem
> descrita abaixo e subiu a reserva. Os de hoje saem de `python -m pytest -q
> -k margem_do_orcamento -s`. Até aqui o prompt classificava intenção e
> extraía campos, mas nunca nomeava a extração como tarefa nem explicava o
> que `null` significa — a semântica em que o desenho inteiro se apoia
> (`None` nunca apaga, "não falou disso neste turno" e não "esqueça o que
> sabia"; ver "Garantias" acima) chegava ao modelo só como nomes de campo
> crus, sem contrato nenhum em texto. Esta card faz `SISTEMA_DO_AGENTE`
> nomear a terceira tarefa e dizer explicitamente que `null` é "não falou
> disso agora" — nunca "não sei" — e que inferir o não-dito conta erro igual
> a não extrair o dito. Três coisas que o escopo original também pedia **não**
> foram feitas, e ficam registradas em vez de escondidas:
>
> - **A reserva não subiu nesta card.** `CONTEXTO_HEADROOM_DE_TOKENS` ficou
>   em 800 (a TEC-250 depois o levou a 850).
>   Entre a subcontagem de 526 que a TEC-145 deixou e o teto de 600 da segunda
>   asserção de `test_diferenca_entre_o_contado_e_o_enviado` havia 296
>   caracteres de folga (74 tokens de proxy); o texto novo do prompt coube
>   nela, deixando a subcontagem em 587 — 13 tokens de margem, travados por
>   `test_a_margem_do_orcamento_do_prompt_e_deliberada` para a próxima card não
>   gastá-los sem saber. Subir a reserva era saída permitida pelo card e foi
>   recusada de propósito: cada 100 tokens de reserva são 100 tokens a menos
>   de literais e resumo por turno.
> - **Nenhum campo do schema ganhou `description`, e o item 3 do escopo do
>   card não foi entregue.** Descrever só os três enums de vocabulário
>   arbitrário (`TipoImovel`, `Urgencia`, `FormaPagamento`) custa da ordem de
>   300 caracteres — estoura sozinho os 296 de folga, antes de qualquer outro
>   campo do schema ou qualquer palavra a mais no prompt.
> - **O efeito não foi medido, e o critério 4 do card não se sustenta como
>   escrito.** A única execução paga de extração é a de 28/08 (seção acima),
>   contra um corpus que já mudou uma vez nesta árvore desde então — a
>   TEC-239 levou as anotações de 47 para 59 — e vai mudar de novo quando a
>   TEC-238 entrar (37 turnos negativos, ainda só no PR #14, não nesta
>   branch). Um "depois" medido hoje contra aquele "antes" já divergiria por
>   mudança de prompt **e** de régua ao mesmo tempo, e a diferença não seria
>   atribuível a uma causa só — e a TEC-238 só vai aumentar essa distância.
>   Medir efeito de prompt exigiria uma execução paga nova **antes** desta
>   card entrar — duas execuções pagas, não uma —, e essa execução não
>   rodou.
>
>   *Posterior (TEC-247, 30/08/2026):* a segunda execução paga rodou, e a frase
>   acima continua de pé — ela mede esta card junto com outras seis, e o efeito
>   **isolado** da TEC-240 segue sem baseline e sempre vai seguir. O que deixou
>   de ser desconhecido é o estado absoluto do que esta card queria: 70 turnos
>   negativos, 1 com invenção. A instrução por-turno bastou. Ver a seção
>   TEC-247.

### Lacunas conhecidas

- **A medição de "não repergunta" é um proxy ininterpretável como cota — nem
  piso, nem teto —, só indicador aproximado.** Detectar em texto livre que o
  agente perguntou a região exigiria um juiz-modelo pago.
  `MARCADORES_DE_REPERGUNTA` em `evals/test_acuracia_de_intencao.py` é lista de
  palavra-chave casada com fronteira de palavra, e só conta se a resposta tiver
  `?`. Isso elimina os falsos positivos mais óbvios (`"onde"` dentro de
  "responder", "casa" dentro de "casamento", o agente descrevendo um imóvel
  sem perguntar nada), mas não os dois tipos de erro: falso negativo por
  construção (uma repergunta com outras palavras não é contada) e falso
  positivo residual (o agente pode citar "apartamento" ou "vaga" ao descrever
  um imóvel numa frase que, por outro motivo, termina com `?`). Os seis casos
  que motivaram o aperto — quatro negativos, dois positivos — estão travados em
  `tests/unit/test_evals_reperguntas.py`.
- **Nada impede o agente de reperguntar.** A escolha da próxima pergunta é do
  modelo, guiada pelo prompt; não há seletor em código. O spec (D5) explica por
  quê — TEC-148 e TEC-149 mexem no mesmo seletor e o reescreveriam.
- **Uma extração ruim apaga dado bom em definitivo.** A sobrescrita é pelo mais
  novo e a tabela guarda só o valor atual, sem histórico: não há como saber que
  houve troca nem voltar atrás. Aceito conscientemente no spec (D4); a
  alternativa sobrepunha desenho com a TEC-152.
- **O corpus anota um subconjunto dos turnos.** A precisão de extração é medida
  sobre os turnos com `campos` anotado, não sobre os 146. `PISO_DE_TURNOS_ANOTADOS`
  guarda o tamanho mínimo desse subconjunto, e é vigiado nos três pontos em
  que `PISO_DE_TURNOS` já era: pré-voo (`evals/conftest.py`), corpus commitado
  no CI (`tests/unit/test_evals_corpus_real.py`) e amostra sobrevivente depois
  do abandono (`evals/test_acuracia_de_intencao.py`, `assert` ao lado do de
  `PISO_DE_TURNOS`, e `_metricas_de` cai em `sem_mecanismo` abaixo do piso, não
  só abaixo de zero). Antes desta onda ele só era vigiado no segundo ponto: o
  pior caso medido — abandonar as `TETO_DE_CONVERSAS_ABANDONADAS` conversas com
  mais anotação — deixava os dois asserts de `PISO_DE_TURNOS` passarem (121
  turnos) com só 20 turnos anotados / 32 anotações de campo sobrevivendo, 33%
  abaixo do piso declarado, e `precisao_da_extracao` bloqueava ou liberava um
  gate pago com essa amostra — números de antes da TEC-239 acrescentar dois
  turnos ao corpus (136, não os 146 de hoje), não do corpus atual. O pior caso
  de hoje, medido em 29/08 sobre o corpus depois da TEC-246, é **47 positivos e
  55 negativos** de pé — as cinco conversas com mais positivos somam 15, e as
  cinco com mais negativos somam outros 15 —, e é dele que saem os pisos
  atuais: `PISO_DE_TURNOS_ANOTADOS = 45` e
  `PISO_DE_TURNOS_NEGATIVOS = 53`, dois abaixo do pior caso em cada direção,
  que é a mesma folga que os pisos anteriores tinham. Os dois pisos subiram
  porque a amostra permitiu, e não porque a medição melhorou: o que aumenta o
  pior caso é ter mais turno anotado, não ter anotação melhor.
- **A precisão de extração agora mede 132 dos 146 turnos — 62 positivos e 70
  negativos —, e o exploit descrito antes não funciona mais.** `campos: {}`
  é o estado novo do contrato: "o lead não afirmou nada neste turno, tudo
  que vier é invenção". Chave ausente continua significando exatamente o
  que significava antes — "fora da medição" —; a diferença é que agora
  existe um jeito de anotar o oposto sem ambiguidade. Um modelo que
  extraísse perfeitamente nos turnos positivos e inventasse
  `regiao`/`tipo_imovel` à vontade nos 70 negativos não tira mais 100% de
  graça: cada invenção entra no denominador de união contra um `esperado`
  vazio, e há teste travando esse comportamento pelo nome
  (`test_modelo_que_inventa_em_turno_negativo_nao_tira_cem_por_cento`,
  `tests/unit/test_evals_metricas.py`). Mas **14 turnos continuam fora da
  medição**, e é esse o buraco que sobra — muito menor do que os 56 que a
  TEC-238 declarou aqui, e hoje de outra natureza. Quatro exclusões, cobrindo
  cinco turnos, já eram deliberadas antes da TEC-245, e cada uma foi escrita
  como armadilha real que valia a pena nomear em vez de anotar errado só para
  fechar o número (convenção de índice de turno, 0-based, declarada em
  `TurnoAnotado`, `src/mobia/evals/corpus.py`). **Duas delas sobreviveram e
  duas caíram na TEC-246.** As que ficaram: `follow-up-03` índice 2
  ("documentação pra baixa do financiamento") fica de fora porque o
  financiamento ali é o que o lead **já tem**, não a forma de pagamento que
  pretende usar, e a distinção é fina de mais para virar gate;
  `borda-evasivo-02` índices 1 e 2 ("depois eu vejo com calma", "ainda to
  decidindo o que quero") ficam de fora porque **omissão não é o mesmo que
  asserção de completude**: a TEC-239 omitiu `SEM_PRESSA` aqui por incerteza
  sobre o que essas falas afirmam, e um negativo é uma afirmação forte de
  que a fala não afirma nada — a mesma incerteza que justificou a omissão
  também impede essa afirmação forte. As que caíram: `follow-up-03` índice 1
  ("quanto tempo leva pra avaliar o imóvel?") e `aluguel-09` índice 2 ("e pode
  ter animal de estimação no prédio?") ficavam de fora por serem pergunta de
  processo que **pressupõe** um campo sem dar pra enumerar com confiança tudo
  o que a fala afirma. **O argumento que as sustentava, preservado porque era
  verdadeiro quando foi escrito:** é a mesma forma de fala que `aluguel-08`
  índice 2 (*"o predio ja tem alvara pra uso comercial de saude?"*) usa para
  **reafirmar** `tipo_imovel`, e um negativo aqui puniria o modelo por ler a
  fala com razão. O que a TEC-246 opôs a ele não foi um contra-exemplo, e sim
  o propósito do negativo: `aluguel-08` índice 2 é positivo porque *"uso
  comercial de saude"* **nomeia** a tipologia, e `prédio` sozinho não nomeia
  nada — as duas falas só são "a mesma forma" na superfície. A TEC-246 tirou a
  pressuposição do critério — ver o bullet do `prédio` abaixo —, e os dois são
  negativos hoje.

  Dos outros 51 turnos fora da medição este bullet dizia, até a TEC-245, que
  eram *"trabalho de anotação que ainda não foi feito, não decisão tomada"*.
  **Essa frase estava errada**, e o que a derrubou foi ler as 51 falas uma a
  uma: a maioria é pergunta de processo dirigida ao corretor — *"qual o valor
  do condomínio mais o IPTU junto?"*, *"tem faxina inclusa ou eu que
  providencio?"*, *"qual a previsão de entrega desse lançamento?"* —, e o
  corpus já sabia o que fazer com essa forma de fala: turnos irmãos nas mesmas
  conversas estavam anotados `campos: {}` havia duas cards. O que faltava não
  era o trabalho de anotação; era o **critério escrito** que dissesse quando
  uma pergunta é negativo e quando é exclusão. Ele existia implícito nas quatro
  exclusões acima, e a TEC-245 o escreveu: o que exclui não é ser pergunta, é
  a fala **pressupor** um campo sem afirmá-lo, ou sugerir um valor sem
  nomeá-lo. Passadas as 51 sob esse critério — que a TEC-246 depois encurtou,
  tirando dele a pressuposição —, 10 viraram
  positivo, 29 viraram negativo `campos: {}` e 12 se juntaram às exclusões,
  fechando em 17. Duas das doze valem nota porque quem decidiu foi a régua e
  não a intuição: *"precisa ser perto do metrô"* (`borda-mista-02` índice 2) e
  *"tem alguma coisa perto de metrô nessa faixa?"* (`compra-02` índice 2) são
  a mesma constatação de proximidade sem topônimo, e por um tempo estiveram
  em baldes diferentes. O que as igualou é um fato do código, não simetria:
  `normalizar_regiao("perto do metro")` devolve `"metro"` — a normalização
  **não** descarta a frase como ruído —, então um negativo ali contaria
  invenção contra um modelo que só repetiu o que o lead disse. `metro` não é
  topônimo; `usp` e `vila madalena` são, e é por isso que aquelas anotam
  `regiao`.

  O que mudou de estrutura, e não só de número: o conjunto fora da medição
  passou a ser **exaustivo e vigiado**. `_FORA_DA_MEDICAO`
  (`tests/unit/test_evals_corpus_real.py`) declara os 14 com o motivo de cada
  um, e um turno novo sem `campos` quebra o CI até alguém decidir para onde
  ele vai — "fora da medição" deixou de ser um estado em que um turno cai por
  omissão. Ver as emendas correspondentes nos specs da TEC-238, da TEC-245 e
  da TEC-246.
  Os 14 continuam sem
  cobertura de invenção nenhuma, e isso é o preço aceito: forçar anotação
  neles seria inventar anotação, que é o erro que a régua pune nos dois
  sentidos.

  `compra-11` índice 2 ("o sobrado tem escritura já regularizada?") estava
  nesta lista desde que a TEC-238 a escreveu — `sobrado` não estava no
  vocabulário de `TipoImovel`, e marcá-lo como negativo puniria com força de
  gate um modelo que devolvesse `CASA` com razão. A TEC-242 criou a tradução que
  faltava (ver "Garantias" acima), e o turno saiu desta lista: hoje é
  anotado `campos: {tipo_imovel: CASA}` e conta como acerto, não mais como
  exclusão. Ver a emenda correspondente no spec da TEC-238. Um ponto para
  não ler o número errado quando ele aparecer: invenção nos 9 turnos
  negativos de intenção `FORA_DE_ESCOPO` é
  medida, mas nunca chega a `lead_qualification`, porque `campos_a_gravar`
  devolve dict vazio para essa intenção (ver "Garantias") — esse número é
  sinal de quão disposto o modelo está a inventar, não risco de dado
  permanente gravado. É a
  [TEC-238](https://eduardodurieuxlopes.atlassian.net/browse/TEC-238).
- ~~**O critério de exclusão e o de anáfora colidem numa classe de
  turnos.**~~ **Fechada pela TEC-246, e a anáfora venceu.** A TEC-245
  declarou aqui uma colisão aberta por decisão: *"e pode ter animal de
  estimação no prédio?"* (`aluguel-09` índice 2) ficava **fora da medição**
  porque `prédio` é contêiner genérico, enquanto *"aquele mesmo prédio"*
  (`aluguel-01` índice 1) era **negativo** porque anáfora pura não nomeia
  nada — duas falas da mesma forma, com um modelo que devolvesse
  `tipo_imovel` levando invenção numa e nada na outra, em sete turnos com dica
  de tipologia na fala. A TEC-246 deu **eixo único** ao critério: pergunta de
  processo que não nomeia campo é negativo, **pressuponha ela o imóvel do
  turno anterior ou não**. `aluguel-09` índice 2 é negativo hoje, e com ele
  `follow-up-03` índice 1 e `borda-mista-01` índice 2, que caíam na mesma
  leitura. O que decidiu foi o propósito do negativo: ele existe para pegar o
  modelo **reemitindo estado acumulado**, que é a primeira hipótese que este
  README manda checar se a próxima execução paga vier vermelha — e o corpus já
  tinha decidido isso em outro lugar, no comentário de `borda-longa-01` índice
  2, que registra que repetir os campos do turno anterior conta `extra` de
  propósito.

  **A história não se apaga, e o argumento da TEC-238 não foi derrubado por
  estar errado.** Quando ela excluiu `aluguel-09` índice 2, a regra de anáfora
  **não existia** — só nasceu na TEC-245, junto dos primeiros negativos com
  dica de tipologia; antes disso nenhum turno negativo do corpus tinha uma, e
  não havia colisão a resolver. Excluir era a leitura conservadora certa num
  corpus sem o outro lado da comparação. O que mudou não foi o raciocínio: foi
  o corpus ganhar a regra que torna a exclusão desnecessária. Ver as emendas
  datadas nos specs da TEC-238, da TEC-242 e da TEC-245.

  **O que a exclusão continua reservando** são três famílias, e só elas,
  enumeradas no docstring de `TurnoAnotado` (`src/mobia/evals/corpus.py`),
  onde o próximo anotador as lê antes de anotar: sugerir um valor sem nomeá-lo
  (*"precisa ser terrea"* sugerindo `CASA`); nomear algo que o vocabulário não
  expressa (*"permuta com meu carro na entrada"* não é valor de
  `FormaPagamento`); e incerteza declarada sobre o que a fala afirma
  (*"depois eu vejo com calma"*). Pressuposição saiu da lista.
- **Nenhum dos nove campos fica com zero anotação, e o teste guarda isso.**
  Contagem nos 62 turnos anotados como positivos, 96 anotações de campo:

  | campo | anotações |
  |---|---|
  | `tipo_imovel` | 36 |
  | `regiao` | 23 |
  | `forma_pagamento` | 11 |
  | `quartos` | 10 |
  | `urgencia` | 7 |
  | `faixa_preco_max` | 4 |
  | `tem_imovel_para_vender` | 3 |
  | `faixa_preco_min` | 1 |
  | `vagas` | 1 |

  > **Emenda da TEC-254 (31/08/2026).** A tabela acima é de 29/08 e a régua
  > mudou desde então. Hoje são **147 turnos, 62 positivos, 71 negativos e 97
  > anotações**, com `tipo_imovel` em 37. Os totais coincidem por acaso: a
  > TEC-254 tirou a anotação por pressuposição de `compra-10[0]`, acrescentou
  > `tipo_imovel` a `aluguel-07[0]` e criou um turno em `compra-10` para
  > devolver a cobertura de `tem_imovel_para_vender: false`, que o primeiro
  > movimento tinha zerado. Ver a seção TEC-254.

  A TEC-239 fechou uma inversão de incentivo, e não só um número baixo.
  `precisao_da_extracao` soma pela união entre esperado e obtido por turno,
  então um campo que o corpus **nunca** anota só entra no denominador pelo
  lado obtido: extraí-lo corretamente jamais somava um acerto — não havia
  anotação contra a qual bater — mas sempre somava ao total. Com
  `urgencia`, `vagas`, `faixa_preco_min` e `tem_imovel_para_vender` em zero,
  o piso de 85% **premiava um modelo que se recusasse a extrair quatro dos
  nove campos que a TEC-145 existe para entregar**. Hoje não há campo nessa
  situação, e `test_todo_campo_de_extracao_tem_anotacao` deriva a lista de
  `fields(Extracao)` — a próxima card que acrescentar campo quebra o teste em
  vez de reabrir o buraco em silêncio.

  O que **não** mudou é a aritmética da união, que ainda desconta extração
  correta em turno onde aquele campo não foi anotado: um modelo perfeito com
  `N` extrações desse tipo tira `96/(96+N)` — `N=10` ainda é VERDE, `N=11` é
  o primeiro AMARELO e `N=17` o primeiro VERMELHO. As bordas subiram duas
  vezes, e a cadeia inteira importa porque é ela que mostra que a tolerância
  acompanha o denominador e nada mais. Cada tripla é
  **(último VERDE / primeiro AMARELO / primeiro VERMELHO)**, a mesma
  convenção da frase acima e em todas as três: **7/8/13** com 69 anotações,
  **9/10/15** com 83, **10/11/17** com 96. O denominador foi de 69 para 83 na
  TEC-245 e de 83 para 96 na TEC-246, e **não** foi o furo que fechou:
  a tolerância a anotação faltante é proporcional ao tamanho da amostra
  anotada, e é só isso que as duas cards compraram aqui. **A convenção precisa
  ser dita porque este parágrafo já usou outra:** versões anteriores dele
  escreviam a tripla de 69 como `7/12/13`, com o **último** AMARELO (12) no
  meio em vez do primeiro (8). As duas descrevem a mesma faixa — AMARELO vai
  de 8 a 12 com 69 anotações —, e misturar as duas numa mesma cadeia faz um
  degrau parecer maior do que é.
  As nove bordas são conferidas por execução contra `faixa_de`, em aritmética
  inteira, e não por regra de três — o arredondamento não põe a borda onde a
  intuição decimal a colocaria. O caso que prova isso está no denominador de
  hoje, e só nele: com 96 anotações, `N=17` dá `96/113`, que **exibe**
  85,0% e mesmo assim reprova, porque `96 × 100 = 9600` é menor que
  `113 × 85 = 9605`. Uma leitura decimal
  do relatório poria essa execução exatamente no piso. A diferença é que agora
  isso é ruído de anotação faltante, distribuído, e não um piso estrutural em
  quatro campos específicos. Quem for investigar um número baixo lê
  `discrepancias_da_extracao`, que separa `extra` (acusa a medição) de
  `faltou` e `divergiu` (acusam o modelo).
- **A barra de anotação de `urgencia` é marco temporal explícito.** "mes que
  vem" e "essa semana" contam; "quero fechar logo" e "bora marcar a
  assinatura" não. A barra é estreita porque a métrica pune os dois lados:
  anotar o que a fala não afirma penaliza o modelo por não inventar, e a
  fronteira entre pressa e entusiasmo não sobrevive a dois anotadores
  independentes. **A barra continua exatamente onde estava** — *"quero fechar
  logo"* (`follow-up-07` índice 2) e *"bora marcar a assinatura"*
  (`follow-up-08` índice 0) seguem sem marco temporal, e nenhum dos dois anota
  `urgencia`. O que a TEC-245 corrigiu foi a consequência que se tirava daí:
  até ela, esses dois turnos ficavam **inteiros** fora da medição, como se não
  saber o valor de um campo impedisse enumerar os outros oito. Não impede —
  `follow-up-07` índice 2 afirma tipologia e quartos (*"aquele apartamento de
  3 quartos"*), `follow-up-08` índice 0 afirma forma de pagamento
  (*"consegui aprovar o financiamento!"*) —, e hoje os dois estão dentro da
  medição, anotados pelos campos que nomeiam. A barra tira um **campo** da
  anotação, e não o turno da medição: a distinção parece pequena, e confundi-la
  manteve dois turnos fora da medição desde a TEC-239.
- ~~**A precisão de extração rodou uma vez, em 28/08/2026, e o número se
  perdeu.**~~ Fechada pela [TEC-247](https://eduardodurieuxlopes.atlassian.net/browse/TEC-247)
  em 30/08/2026: **79,2% (80/101), VERMELHO**, com o relatório commitado em
  `evals/relatorios/2026-08-30-corpus-6d74cff.md`. Ver a seção TEC-247.
  O que se perdeu da execução de 28/08 continua perdido, e fica registrado
  porque explica de onde vieram a TEC-241 e a TEC-242: ela rodou com a
  instrumentação de `discrepancias_da_extracao`, contra o corpus de então — 32
  turnos anotados, 47 anotações, `regiao` com 17 —, e produziu **29
  discrepâncias**, das quais 10 em `regiao` (todas `divergiu`, por desacordo de
  forma) e 8 em sinônimos de `tipo_imovel`. **O percentual e a faixa daquela
  execução nunca foram registrados** — o que sobrou está na descrição da
  TEC-241, e é só a decomposição por campo.
- ~~**Não há baseline comparável para a extração.**~~ Fechada pela TEC-247: a
  execução de 30/08/2026 é o "antes" real, medido contra o corpus fechado pela
  TEC-246 (`6d74cff`) e com data, commit e condições de validade registrados ao
  lado do número. Os 29 de 28/08 continuam sem servir de comparação, pelo
  motivo original: são de um corpus que mudou desde então em seis cards —
  TEC-238, TEC-239, TEC-241, TEC-242, TEC-245 e TEC-246 —, e as anotações de
  campo foram de 47 para 96. A diferença entre aquela execução e esta não é
  atribuível a uma causa só, e **não deve ser lida como efeito de nada**.
- **A convenção por-turno já está no prompt, e continua sem medição contra
  ele.** Até a TEC-240, `SISTEMA_DO_AGENTE`
  (`src/mobia/domain/agente/classificador.py`) só mandava usar o resumo e o
  estado de qualificação acumulado "como memória", e quem dizia que cada turno
  extrai só o que aquele turno afirma era o docstring de `Extracao`, que o
  modelo não lê. A régua depende dessa convenção desde a TEC-145 — toda
  anotação positiva do corpus enumera só o que aquele turno afirma —, então o
  silêncio do prompt era um risco de medição, não uma curiosidade. Hoje o
  prompt diz — *"Na extracao, preencha so o que a fala DESTE turno afirma"* —,
  e as duas instruções convivem no mesmo texto puxando para lados opostos: o
  estado acumulado é oferecido como memória a usar, e a extração é proibida de
  reemiti-lo. Nada garante que o modelo resolva essa tensão do jeito que a
  régua espera. A execução de 28/08 não podia responder isso — é anterior tanto
  aos turnos negativos da TEC-238 quanto ao texto que a TEC-240 acrescentou.
  **A TEC-247 mediu, em 30/08/2026, e a tensão se resolve do lado certo:** 70
  turnos negativos, **1 com invenção**, 1 campo. A hipótese que estava escrita
  aqui — o modelo reemitindo estado acumulado num turno que não afirmou nada de
  novo — era a primeira a checar se o vermelho viesse por invenção nos
  negativos, e **não é o que aconteceu**: a execução veio vermelha na precisão
  da extração (79,2%) por `faltou` e `divergiu` em turnos positivos, com os
  negativos praticamente limpos. A instrução da TEC-240 bastou; o que não
  bastou está em outro lugar. Ver a seção TEC-247.

## TEC-247 — A baseline paga da extração, e o relatório que sobrou dela

**A execução rodou em 30/08/2026, 12:02 UTC**, contra o corpus fechado pela
TEC-246 — commit `6d74cff`, a última mudança de régua —, com a árvore em
`b607fce` e `modelo_agente = claude-opus-5`. Foram 146 chamadas sequenciais,
uma por turno, em 19min53s.

**A precisão da extração deu VERMELHO: 80/101, ou 79,2%** — abaixo do piso de
85% e do alvo de 90%. É o número que este projeto não tinha, e ele é ruim.

As outras duas métricas passaram, e melhoraram sobre a baseline de 27/08/2026:

| métrica | 27/08/2026 | 30/08/2026 | faixa |
| --- | --- | --- | --- |
| acurácia de intenção (crua) | 130/136, 95,6% | 142/146, **97,3%** | VERDE |
| acurácia efetiva (o que produção roteia) | 126/136, 92,6% | 141/146, **96,6%** | VERDE |
| precisão da extração | não registrada | 80/101, **79,2%** | **VERMELHO** |

### O relatório está commitado, e essa é a metade do card que não era sobre o número

`evals/relatorios/2026-08-30-corpus-6d74cff.md`. O nome carrega a data e o
commit do corpus de propósito: baseline sem as duas não tem prazo de validade,
e foi exatamente assim que o resultado de 28/08/2026 se perdeu — a execução
aconteceu, custou dinheiro, e o que sobrou dela foi a decomposição por campo
que alguém copiou para a descrição da TEC-241 antes do terminal fechar.

O runner grava o artefato **antes** das asserções (`preservar`,
`src/mobia/evals/relatorio.py`), e não depois. A ordem importa e esta execução
provou por quê: ela foi vermelha, o `assert not bloqueia(metricas)` abortou o
teste, e um artefato escrito depois dele não existiria justamente na execução
que mais precisa ser lida turno a turno. Se a gravação falhar, o relatório
ainda sai no terminal e a execução segue reprovando pelo que mediu — o disco
não pode derrubar a medida.

### Condições de validade, ao lado do número

Uma execução que roçou um piso vale menos que uma folgada, e o relatório
sozinho não dizia qual das duas foi: `_secao_de_infraestrutura` só imprime
quando **houve** falha, então zero abandono não imprimia nada, e os três pisos
não apareciam em lugar nenhum quando a execução passava por eles. Agora
aparecem, em `_condicoes_da_execucao` (`evals/test_acuracia_de_intencao.py`),
no topo do próprio artefato:

- **conversas abandonadas: 0**, teto 5. Nenhuma perda de rede — a execução
  atravessou inteira, e nenhum número aqui está contaminado por 429.
- **turnos medidos: 146/120**, folga de 26.
- **turnos anotados positivos: 62/45**, folga de 17.
- **turnos anotados negativos: 70/53**, folga de 17.

Nenhum piso foi roçado. **Este resultado não tem desculpa de amostra**: as três
folgas são as maiores que este corpus já teve, e o vermelho não é ruído de
denominador pequeno.

### A decomposição, e como não ler ela errado

São **21 discrepâncias** em 101 campos no denominador de união. A separação que
importa é entre o que acusa a **medição** e o que acusa o **modelo**:

| tipo | quantas | acusa |
| --- | --- | --- |
| `extra` (modelo extraiu, corpus não anotou) | 5 | a medição, ou invenção |
| `faltou` (corpus anotou, modelo não devolveu) | 8 | o modelo |
| `divergiu` (veio nos dois, valores diferentes) | 8 | o modelo |

Por campo:

- **`regiao` — 7 `divergiu`**, o maior balde da execução, e nenhum `extra` nem
  `faltou`.
- **`urgencia` — 6** (3 `faltou`, 2 `extra`, 1 `divergiu`), o campo com o
  espalhamento mais largo entre os três tipos.
- **`tipo_imovel` — 6** (3 `faltou`, 3 `extra`).
- **`forma_pagamento` — 1 `faltou`**; **`tem_imovel_para_vender` — 1 `faltou`**.

**O vermelho não é lacuna de anotação, e a conta do card fecha isso sem
ambiguidade.** A leitura registrada em TEC-247 diz que, com 96 anotações, um
modelo perfeito com `N` extrações corretas em campo não anotado ainda tira
VERDE até `N=10`, AMARELO de 11 a 16, e VERMELHO a partir de 17. **Esta
execução teve `N=5`** — dentro da faixa verde, com folga de cinco. O
denominador confirma: 96 anotações + 5 `extra` = os 101 campos medidos. Se o
corpus estivesse perfeito e o modelo errasse só os 5 `extra`, seriam 96/101 =
95%, VERDE. **Os 16 `faltou` + `divergiu` são o vermelho inteiro**, e eles
acusam o modelo ou o prompt, não a régua.

### Invenção nos turnos negativos: a hipótese do card não se confirmou

Este é o número que a execução vê pela primeira vez com cobertura real — **70
turnos negativos, contra 37 na última vez que alguém olhou** — e ele veio
limpo: **1 turno com invenção, 1 campo**. Um em setenta.

A TEC-247 mandava, se o vermelho viesse por invenção nos negativos, checar
primeiro o modelo reemitindo estado acumulado num turno que não afirmou nada
de novo — as duas instruções de `SISTEMA_DO_AGENTE` que convivem no mesmo texto
puxando para lados opostos (o estado é oferecido como memória, e a extração é
proibida de reemiti-lo). **Não foi isso.** O modelo resolve essa tensão do jeito
que a régua espera em 69 dos 70 turnos negativos, e a convenção por-turno da
TEC-240 passa a ter medição contra o prompt real — ela funciona.

Os outros 4 `extra` estão em turnos **positivos**, onde o corpus anotou alguns
campos e não aquele. Ali `extra` continua ambíguo por construção: pode ser
invenção, pode ser extração correta de campo que ninguém anotou, e no
denominador de união as duas descontam igual.

Os **9 turnos `FORA_DE_ESCOPO`** foram classificados certo, todos os nove, e
nada deles chega a `lead_qualification` de qualquer jeito — `campos_a_gravar`
devolve dict vazio para essa intenção. É disciplina do modelo, não risco de
dado gravado.

### `regiao` continua sendo o maior balde, depois da TEC-241

Sete `divergiu`, e nenhum `extra` nem `faltou`: o modelo acha a região sempre,
e discorda da forma em sete turnos. Em 28/08 eram **10 das 29** discrepâncias,
todas `divergiu` por desacordo de forma, e foi isso que originou a TEC-241 —
que normalizou os dois lados da comparação com `normalizar_regiao` justamente
para essas sumirem.

As duas execuções não são comparáveis (corpus diferente, seis cards no meio),
então "10 caiu para 7" não é uma medida de efeito e não deve ser lida como
uma. O que se pode afirmar é mais simples e mais desconfortável: **depois da
normalização, `regiao` ainda é o campo que mais diverge**, e o critério de
aceite da TEC-241 — "as divergências de `regiao` caem para perto de zero numa
execução do gate" — **não foi atingido**. Sete não é perto de zero. Os
endereços estão no relatório: `aluguel-06[1]`, `aluguel-10[0]`,
`borda-longa-01[0]`, `compra-08[1]`, `compra-12[0]`, `compra-13[0]`,
`investimento-07[0]`.

### Confiança: o limiar continua custando mais do que devolve

5 turnos de 146 (3,4%) abaixo de `LIMIAR_DE_DESAMBIGUACAO`, **1 acerto
rebaixado** para INDEFINIDA (`compra-04[0]`, confiança 0,55) e **0 erros que o
rebaixamento acertou**. Em 27/08 a conta era 4 perdidos e zero recuperados; o
sinal é o mesmo, mais fraco, e na mesma direção: o rebaixamento não recuperou
um único acerto em nenhuma das duas execuções pagas que este projeto tem.

Os outros 4 turnos abaixo do limiar já vinham com `obtida = INDEFINIDA` —
eram erro cru, e a confiança baixa neles é coerente. A diferença entre 97,3% e
96,6% é esse único acerto rebaixado, e mais nada.

### O que esta card não fez, de propósito

**Não agiu sobre o resultado.** O número veio ruim, e consertar é card própria:
esta entrega a medição, não o conserto. Mexer em corpus, prompt, schema ou
qualquer piso durante esta card invalidaria a própria execução que ela pagou.

Consequência a aceitar por escrito: **a `main` fica com o gate vermelho** até
que a card do conserto entre. O vermelho é verdadeiro — a precisão da extração
está abaixo do piso que o SRS declara — e escondê-lo mexendo no piso seria
trocar o instrumento pelo número que se queria dele.

### O relatório dizia onde, e não o quê — e para `divergiu` isso não basta

A execução de 30/08 expôs um buraco na própria instrumentação que ela usou.
`Discrepancia` carregava `conversa_id`, `indice`, `campo` e `tipo`, e o
docstring explicava por quê: para quem for anotar não precisar de outra
execução paga só para descobrir **onde** faltava anotação.

Isso resolve `faltou` e `extra`, que são perguntas de anotação — o endereço
manda a pessoa no YAML certo e ela vê o resto. **Não resolve `divergiu`**, que
é uma pergunta de comparação: os dois lados existem, e sem os valores não há
como saber se o modelo errou o campo ou se as duas formas apenas não casaram.
São causas opostas, e pedem cards opostos.

Foi exatamente onde a baseline parou. Sete `divergiu` em `regiao`, os sete
endereços registrados, e **nenhum dos catorze valores**. A hipótese mais forte
ficou sem como ser confirmada sem pagar as 146 chamadas de novo — numa card
que existe para que resultado pago não se perca.

`Discrepancia` agora carrega `esperado` e `obtido`, e `_secao_de_extracao` os
imprime na linha do turno:

```
  - compra-13 turno 0: regiao (divergiu) -- anotado 'sao roque', obtido 'São Roque'
  - compra-02 turno 1: forma_pagamento (faltou) -- anotado 'FGTS'
  - follow-up-03 turno 0: tipo_imovel (extra) -- obtido 'APARTAMENTO'
```

Três decisões, com o motivo de cada uma:

- **Os valores são crus, não normalizados.** Quem lê a lista já sabe que
  `_comparavel` rodou e **não** reconciliou os dois — é o que estar nesta lista
  significa —, então a forma comparada não acrescentaria nada. A crua
  acrescenta: é nela que o acento, o espaço sobrando e `600000` contra
  `Decimal('600000.00')` ficam visíveis.
- **`repr`, e não `str`.** Este texto é lido por quem está caçando defeito de
  comparação, e `repr` mostra justamente o que `str` esconde.
- **`None` é "este lado não tinha valor", sem ambiguidade.** O corpus recusa
  anotação com valor nulo (`_turno_de`, `corpus.py`) e `preenchidos()` nunca
  devolve `None`, então o lado ausente nunca colide com um valor real. `faltou`
  imprime só o anotado, `extra` só o obtido.

**Isso não é mudança de régua, e o número não se mexeu.**
`precisao_da_extracao` não foi tocada: ela conta a união de esperado com obtido
exatamente como contava, e os **79,2% (80/101) da baseline continuam valendo**
como medidos. O que ganhou campos foi a decomposição de diagnóstico, que nunca
entrou em `_metricas_de` nem em `bloqueia`.

**E não diagnostica a execução de 30/08 retroativamente.** Aqueles valores
nunca foram capturados, e não existem em lugar nenhum. O que esta mudança faz é
garantir que a próxima execução paga não termine na mesma parede.

#### A hipótese que a instrumentação vai testar

`normalizar_regiao` (`src/mobia/domain/agente/schemas.py`) dobra caixa e espaço
e remove prefixo de referência. **Não dobra acento.** Todo prefixo de
`_PREFIXOS_DE_REFERENCIA` é escrito sem acento — `regiao`, `proximo`,
`estacao` — e as **23 anotações de `regiao` do corpus também**: nenhuma tem
acento, num domínio paulistano onde `Saúde`, `Aclimação`, `Tatuapé` e `Butantã`
levam. `casefold()` não reconcilia isso: `casefold("São Roque")` é
`"são roque"`, que não é `"sao roque"`.
`test_divergiu_guarda_os_dois_valores_crus`
(`tests/unit/test_evals_metricas.py`) trava o mecanismo — o par
`sao roque` / `São Roque` **produz** um `divergiu`.

**Mas o próprio corpus tem a evidência contrária, e ela é forte.** Das 23
anotações, 16 casaram e 7 divergiram, sem nenhum `faltou` nem `extra` — o
modelo devolveu `regiao` nos 23 turnos. Entre as que **casaram** estão
`butanta` (`borda-injecao-01[1]`) e `tatuape` (`compra-09[0]`), e as duas
levam acento em português corrente. Se o modelo restaurasse acento de forma
uniforme, essas duas teriam divergido também. Não divergiram. **Acento sozinho
não explica os sete.**

E dois dos sete não são acento de jeito nenhum: `sp` (`compra-12[0]` e
`investimento-07[0]`) contra qualquer expansão que o modelo tenha devolvido é
abreviação, não grafia — e `"sao paulo"` continua diferente de `"sp"` depois de
qualquer dobra de acento. Esses dois são pergunta de **anotação**, não de
normalização: se o modelo devolveu "São Paulo" para *"estou de mudança pra
sp"*, quem está errado é a anotação, não ele.

**Conclusão honesta: a causa dos sete é desconhecida.** O que está descartado é
"acento explica tudo"; o que sobra são pelo menos três mecanismos distintos
(grafia, prefixo não coberto, abreviação) e nenhum medido. Os valores daquela
execução não foram guardados, então isto não se resolve relendo nada — se
resolve chamando o modelo naqueles turnos e olhando o que ele devolve.

A conta de faixa não depende da causa: com os sete resolvidos, seja lá como, a
precisão vai a 87/101 (86,1%), AMARELO, e o gate deixa de bloquear. Se forem
defeito de régua, a leitura registrada acima — de que os 16 `faltou`+`divergiu`
acusam o modelo — vale para os `faltou` e fica em aberto para os `divergiu`.

Descobrir a causa e corrigir é **card própria**, pelo mesmo motivo que
consertar o número era: mexer em `normalizar_regiao` ou nas anotações é
mudança de régua, invalida qualquer baseline anterior a ela, e tem de entrar
antes da próxima execução paga — a mesma disciplina que a TEC-246 impôs à
TEC-247.

O diagnóstico, porém, **não** custa uma execução paga inteira. São 7 turnos
nomeados: `aluguel-06[1]`, `aluguel-10[0]`, `borda-longa-01[0]`,
`compra-08[1]`, `compra-12[0]`, `compra-13[0]`, `investimento-07[0]`. Chamar o
modelo só neles são **7 chamadas, 5% de uma execução**, e respondem
definitivamente o que 146 chamadas responderiam. É a forma barata de sair
daqui, e ela existe porque os endereços foram registrados.

### Lacunas conhecidas

- **O relatório de uma execução em CI continua efêmero.** O runner grava em
  disco sempre, mas em CI esse arquivo morre com o runner: não há
  `upload-artifact` em `.github/workflows/evals.yml`, e nada commita de volta.
  A lacuna que a TEC-247 fechou é a da execução **local**, que é a que produziu
  esta baseline. Uma execução disparada por `workflow_dispatch` ainda deixa só
  log.
- **Duas medições de intenção, ainda não uma distribuição.** 95,6%/92,6% em
  27/08 e 97,3%/96,6% em 30/08, contra corpus diferentes. Dois pontos não são
  dispersão, e o ruído entre execuções continua estimado (±1,5%), não medido.
  Um gate relativo a histórico — bloquear por queda maior que a dispersão
  observada — agora tem onde guardar as execuções (`evals/relatorios/`), mas
  ainda não tem execuções suficientes para calcular a dispersão.
- **A precisão da extração tem exatamente um ponto.** Não há com o que comparar
  os 79,2%: a execução de 28/08 não registrou percentual nenhum. Este número é
  o "antes" que a TEC-235 e a TEC-244 não tinham; ele não é um "depois" de
  coisa nenhuma.
- **`extra` em turno positivo continua ambíguo.** Os 4 fora dos negativos podem
  ser invenção ou anotação faltante, e a execução não distingue. Só o turno
  negativo dá `extra` sem ambiguidade, e lá houve 1. Os valores crus, agora
  registrados, não desfazem essa ambiguidade — ela é da anotação, não da
  comparação —, mas dizem **o que** o modelo extraiu, que é o suficiente para
  quem for decidir se aquilo merecia anotação.
- ~~**Os valores dos `divergiu` de 30/08 não existem, e não vão existir.**~~
  Verdade sobre *aquela* execução, e contornada pela TEC-248: sondar os sete
  turnos custou 9 chamadas em vez de 146, e respondeu a pergunta sem esperar
  a próxima execução paga. Ver a seção TEC-248.

## TEC-248 — Por que `regiao` divergia, medido com nove chamadas

A baseline da TEC-247 deu VERMELHO com **7 `divergiu` em `regiao`**, o maior
balde da execução, e ninguém sabia a causa: `Discrepancia` registrava o
endereço e não os valores, e a instrumentação que os registraria entrou
*depois* da execução.

Esta card sondou os sete. **Nove chamadas — não 146, e nem os sete da
estimativa**: `aluguel-06` e `compra-08` são índice 1, e o turno 0 deles tem de
rodar antes para montar o histórico e o estado acumulado. Custo medido:
**US$ 0,18**. O artefato está em `evals/relatorios/2026-08-30-sonda-regiao.md`,
commitado antes de qualquer análise.

### O que o modelo devolveu, e o que cada um era

| turno | anotado | obtido | mecanismo | de quem era |
| --- | --- | --- | --- | --- |
| `aluguel-06[1]` | `vila madalena` | `vila madalena (perto da estação), são paulo` | parentético + cidade anexada | régua |
| `aluguel-10[0]` | `saude` | `saúde` | acento | régua |
| `borda-longa-01[0]` | `aclimacao` | `aclimação` | acento | régua |
| `compra-08[1]` | `paulista` | `avenida paulista` | logradouro | régua |
| `compra-12[0]` | `sp` | `são paulo` | expansão de abreviação | **anotação** |
| `compra-13[0]` | `sao roque` | `são roque (sp)` | acento + UF parentética | régua |
| `investimento-07[0]` | `sp` | `são paulo (sp)` | expansão + acento + UF | **anotação** |

**Em nenhum dos sete o modelo errou a região.** Seis eram defeito de régua e
um era anotação errada — e "erro do modelo", que era a leitura registrada pela
TEC-247 para os `faltou` e `divergiu`, não vale para nenhum destes sete.

### O mecanismo dominante não era acento

A hipótese que a TEC-247 deixou escrita era acento, e ela estava **parcialmente
certa e mal fundamentada**. Acento aparece em quatro dos sete valores devolvidos
(`saúde`, `aclimação`, `são roque`, `são paulo`), mas dobrar acento sozinho
resolveria só **dois** deles.

O que a sonda mostrou é maior que acento: **o modelo devolve o LUGAR, e não a
string do lead.** Ele expande `sp` para `são paulo`, promove `paulista` a
`avenida paulista`, anexa a cidade depois de vírgula e acrescenta a UF entre
parênteses. É comportamento coerente e, do ponto de vista do produto, *melhor*
que a anotação — só não era o que a régua comparava.

E a inconsistência que a TEC-247 tinha observado continua verdadeira, agora com
explicação: a mesma execução devolveu `saúde` e `aclimação` **com** acento e
`butanta` e `tatuape` **sem** — e essas duas casaram justamente por isso. O
modelo não é consistente com diacrítico, então a régua não pode depender de
adivinhar qual das duas formas vem.

### O que mudou na régua

`normalizar_regiao` ganhou três passes, nesta ordem, antes da remoção de
prefixo que já existia:

1. **Dobra acento** (NFD + descarte de combinantes; pega cedilha junto).
2. **Derruba qualificador entre parênteses** — `sao roque (sp)` é `sao roque`.
   Parêntese é ruído de referência como os prefixos, só que no fim.
3. **Fica com o pedaço antes da primeira vírgula** — o contexto mais largo que
   o modelo anexa não é o que o filtro compara.

**A ordem não é detalhe.** O acento tem de cair **antes** dos prefixos: o
modelo devolveu `(perto da estação)` com acento, e `estacao ` na lista é
escrito sem — dobrar depois deixaria o prefixo dentro do valor.
`test_normalizar_regiao_fica_com_o_pedaco_antes_da_virgula` exercita os três
passes e a ordem entre eles de uma vez.

`_PREFIXOS_DE_REFERENCIA` ganhou `avenida `, e mais `av. ` e `av ` por
simetria — só `avenida ` foi observada, mas a lição que a TEC-246 tirou do
próprio caro é que lista de prefixo assimétrica é bug latente, que só aparece
quando alguém escreve a forma que faltava.

Isto é mudança na função que **produção também usa** ao gravar, e não só na
medição. A perda de informação vai na mesma direção que o README já aceita por
escrito para `perto da usp` → `usp`: a troca é a favor do filtro SQL da
TEC-158, que compara `regiao` por igualdade.

### A decisão de anotação, que não era de régua

Os dois `sp` **não** eram defeito de normalização. O modelo devolveu o lugar
(`são paulo`) e o corpus anotava a abreviação do lead (`sp`). Quem estava
errado era a anotação: ela punia o modelo por acertar.

`compra-12[0]` e `investimento-07[0]` passaram a anotar `sao paulo`, e a regra
está escrita no docstring de `TurnoAnotado` — **`regiao` se anota pelo lugar,
não pela string do lead**, irmã da regra da TEC-241 que tirou a preposição. As
duas dizem a mesma coisa: o campo guarda o topônimo que o filtro compara, não a
forma como o lead o escreveu.

Resolver isso na normalização exigiria uma tabela de apelidos, e é ali que a
função deixaria de normalizar **forma** e passaria a decidir **semântica**.
`test_normalizar_regiao_nao_inventa_expansao_de_abreviacao` trava essa fronteira:
`sp` e `sao paulo` continuam diferentes de propósito.

### O que isso deve fazer com o número, e por que não é medição

Com os sete resolvidos, a precisão da extração iria de 80/101 (79,2%,
VERMELHO) para **87/101 (86,1%), AMARELO** — acima do piso de 85%, e o gate
deixaria de bloquear.

**Isso é aritmética, não medição.** É o que os mesmos valores dariam se
recontados com a régua nova, e não uma execução nova. Uma execução paga contra
esta régua pode divergir: a normalização mudou para todos os 23 turnos com
`regiao`, não só para os sete, e o ruído normal entre execuções continua na
casa de ±1,5%. **Esta card não mede o próprio efeito** — medir é a próxima
execução paga, e é card própria pelo mesmo motivo que a TEC-247 foi.

E a baseline de 30/08 deixa de servir como "antes" comparável a partir daqui:
ela mediu a régua de `6d74cff`, e esta card mexeu na régua. O número dela
continua válido como o que foi medido; o que expira é a comparabilidade.

### Lacunas conhecidas

- **Os outros 14 de discrepância continuam sem diagnóstico.** `urgencia` (6,
  espalhado nos três tipos), `tipo_imovel` (6, metade `faltou` e metade
  `extra`), `forma_pagamento` (1) e `tem_imovel_para_vender` (1). A sonda desta
  card cobriu `regiao` e nada mais, e não há razão para supor que a causa seja a
  mesma — `regiao` era o único campo com contrato de forma próprio.
- **A sonda não é reprodutível a partir do repositório.** O script viveu fora
  da árvore e o que ficou foi o resultado. Repetir o método para `urgencia` ou
  `tipo_imovel` custa reescrevê-lo.
- **Nenhum dos sete foi re-medido depois do conserto.** Os testes travam os
  pares reais que a sonda colheu, o que garante que a régua nova reconcilia
  *aqueles* valores — não que o modelo devolva os mesmos valores na próxima
  execução.
- **`av. ` e `av ` nunca foram observados.** Entraram por simetria, e a única
  forma medida é `avenida `.

## TEC-249 — O custo da moderação nunca foi registrado

A moderação roda em **todo turno, nas duas pontas**. É o caminho mais quente do
produto, e o gasto dele nunca apareceu em lugar nenhum.

### A causa não era a que a card descrevia

A card foi escrita supondo que `custo_em_dolar` devolvia `None` para a
moderação e que `telemetry.unknown_model` vinha sendo emitido a cada chamada,
sem ninguém ler. **Estava errado, e a leitura do código desmentiu.**

`ModeradorAnthropic.moderar` (`src/mobia/infra/moderacao.py`) **nunca chamou
`custo_em_dolar`.** Ela tinha a resposta inteira em mãos — com `model` e
`usage` — e descartava as duas, devolvendo só o `Veredito(bloqueado, motivo)`.
Não havia log, não havia contagem de tokens, não havia custo. Não era uma
consulta que falhava: era instrumentação que não existia.

O buraco na tabela de preços é real, mas era **latente**: ninguém consultava o
preço da moderação, então nada acusava. Ele viraria custo nulo em produção no
instante em que alguém instrumentasse — que é o que esta card fez.

### Os dois defeitos, e por que são irmãos

**1. O ID datado não achava preço.** `custo_em_dolar` fazia busca por chave
exata:

| | valor |
| --- | --- |
| `settings.modelo_moderacao` | `claude-haiku-4-5-20251001` |
| chave em `PRECOS_POR_MODELO` | `claude-haiku-4-5` |

Um snapshot datado é o **mesmo modelo pelo mesmo preço**, então a busca passou
a reduzir um sufixo de data antes de desistir. A redução é estreita de
propósito: sai só `-` seguido de **oito dígitos**, e só no fim.
`claude-opus-9-20260101` continua devolvendo `None`, porque `claude-opus-9`
também não está na tabela — a lacuna continua aparecendo, que é o que o
docstring de `custo_em_dolar` promete. Uma linha por data seria a alternativa,
e a primeira que faltasse reabriria o buraco.

**2. A moderação não media nada.** `moderar` passou a registrar
`moderacao.avaliada` com modelo, direção, tokens, latência e custo — **antes**
de qualquer recusa, porque a chamada já foi paga e um veredito fora do
protocolo custa igual a um veredito bom. Registrar só no caminho feliz
esconderia justamente o gasto que não produziu nada.

O log usa `resposta.model`, e não `settings.modelo_moderacao`: o que interessa
é o modelo que **serviu** a requisição, que pode diferir do que foi pedido.

A regra do log do classificador — só números e id de modelo — aperta aqui, e
está travada por teste: o que a moderação vê é conteúdo do lead ou da empresa,
e a resposta carrega o veredito sobre ele. Nem o texto julgado, nem o veredito.

### A causa de fundo, que era comum aos dois

**A tabela de preços não tinha nada que a amarrasse à realidade.** Dois defeitos
distintos saíram dela em dois dias:

- `claude-sonnet-5` estava com `$3/$15`, que são os preços do
  `claude-sonnet-4-6` — corrigido na troca do `modelo_agente`.
- `modelo_moderacao` não tinha entrada nenhuma — esta card.

O teste que deveria ter pego o primeiro repetia `3.00`/`15.00` escritos à mão,
duplicando a constante: pegava erro de fórmula e nunca erro de preço. Agora há
duas guardas que fecham a classe inteira:

- `test_precos_batem_com_a_tabela_publicada` trava os preços contra a tabela
  publicada.
- `test_todo_modelo_configurado_tem_preco_cadastrado` varre toda `modelo_*` de
  `Settings` e exige preço para cada uma. **É o teste que teria pego este bug
  no dia em que ele entrou**, e é o que pega o próximo modelo configurado sem
  entrada.

### O histórico não é recuperável

O custo da moderação nunca foi gravado, e **os tokens também não** — `moderar`
descartava `usage` inteiro, então não há de onde recalcular. Não existe registro
em `message_telemetry` para as chamadas de moderação: elas nunca passaram pelo
`MessageRecorder`.

Fica como está, por escrito: **o gasto de moderação anterior a esta card é
desconhecido e permanece desconhecido.** A série começa aqui.

### Lacunas conhecidas

- **O custo da moderação vai para log, não para `message_telemetry`.** O
  classificador e o resumo fazem o mesmo, então isto é consistente — mas
  significa que o gasto de moderação não entra em nenhuma consulta SQL, só em
  agregação de log. Somar custo por conversa continua não sendo possível para
  esta ponta.
- **Quanto a moderação custou até aqui continua desconhecido**, e não há como
  recuperar.
- **A redução de snapshot é sintática, não semântica.** Ela assume que
  `-YYYYMMDD` no fim é sempre um snapshot do modelo à esquerda. É verdade para
  a convenção de nomes de hoje; um ID futuro que termine em oito dígitos por
  outro motivo passaria a ser reduzido por engano.

## TEC-251 — Prompt caching: 88% da entrada era o mesmo texto, pago toda vez

Toda chamada ao agente manda o mesmo prefixo — `SISTEMA_DO_AGENTE` mais o
schema de `output_config`. **Medido em 30/08/2026: 1.652 tokens**, idênticos
nas 146 chamadas de uma execução e em todo turno de produção. Na execução do
sonnet-5 isso foi **241.192 dos 273.401 tokens de entrada.**

### Que funciona está verificado, e a dedução dizia o contrário

O mínimo cacheável é **por modelo**, e prefixo curto demais **não cacheia e não
dá erro** — sai `cache_creation_input_tokens: 0` e ninguém percebe.

`SISTEMA_DO_AGENTE` sozinho tem **457 tokens**, abaixo dos 1.024 que o
`claude-sonnet-5` exige. A documentação descreve o prefixo como
`tools` → `system` → `messages` e não cita `output_config`, então pela leitura
dela o schema ficaria de fora e o cache seria inútil aqui.

Duas chamadas (US$ 0,01) resolveram:

```
chamada 1: input=21  cache_creation=1652  cache_read=0
chamada 2: input=21  cache_creation=0     cache_read=1652
```

**O schema entra.** Medir custou menos que continuar deduzindo.

### O ganho, e onde ele não vale

Na execução do gate: **US$ 1,15 → US$ 0,72, 37% a menos**, com a saída
intacta.

**Em produção o ganho não foi medido, e pode ser negativo.** O TTL padrão é de
5 minutos. No eval as chamadas saem a 6,1s uma da outra e o prefixo fica quente
do começo ao fim; em produção os turnos são esparsos, e um turno frio paga o
prefixo **mais** o ágio de 1,25% da escrita. Por turno, medido:

| turno | custo |
| --- | --- |
| sem cache | US$ 0,006992 |
| quente (leitura) | **US$ 0,004018** |
| frio (escrita) | **US$ 0,007818** |

Um turno frio custa **12% a mais** que não ter cache. Com tráfego baixo o saldo
pode virar. `test_turno_frio_custa_mais_que_turno_sem_cache` trava esse fato
para ele não virar surpresa.

### O custo passou a mentir para baixo, e foi consertado junto

Os tokens cacheados **saem de `input_tokens`** e vão para contadores próprios:
um turno que reportava ~1.700 de entrada passou a reportar **54**. Como
`custo_em_dolar` só olhava `tokens_in`, o custo caiu junto — sem o gasto ter
caído tanto.

É o defeito da TEC-249 entrando pela outra porta, e contra o que o próprio
docstring da função promete: *"Zero somaria silenciosamente no painel de custo
e faria o gasto parecer menor do que foi."* `custo_em_dolar` ganhou
`cache_write` e `cache_read`, com o ágio de 1,25× e o desconto de 0,1× sobre o
preço de entrada. Os dois com default zero, então moderação e resumo — que não
usam cache — não veem número nenhum mudar.

### O acoplamento que ninguém veria

O mínimo cacheável **não é monotônico entre gerações**: 512 no `claude-opus-5`,
**1.024** no `claude-sonnet-5`, **4.096** no `claude-haiku-4-5`. O prefixo de
1.652 passa nos dois primeiros e **falharia no terceiro, em silêncio**.

Trocar `modelo_agente` pode desligar o cache sem nada acusar — e `config.py`
está fora do filtro de `evals.yml`, então nem o gate pago dispararia. É a mesma
classe de armadilha da tabela de preços da TEC-249: configuração que muda
comportamento sem sinal. `test_o_prefixo_cacheavel_passa_o_minimo_do_modelo`
amarra o tamanho do prefixo ao modelo configurado, e é o sinal que faltava.

### Lacunas conhecidas

- **O ganho em produção não foi medido.** Depende da densidade de turnos, e não
  há dado de tráfego. O TTL de 1h existe e custa mais na escrita — decisão para
  quando houver dado.
- **`PREFIXO_CACHEAVEL_EM_TOKENS` é um número copiado, não calculado.** Ele foi
  medido com `count_tokens` e travado à mão; mudar o prompt ou o schema o
  invalida, e nada recalcula sozinho. O teste guarda o limiar, não a medição.
- **A desambiguação provavelmente não cacheia.** Ela não manda schema, então o
  prefixo dela é só o system prompt próprio — abaixo do mínimo. Os contadores
  são registrados no log dela de propósito: é o que transforma "não cacheia" de
  suposição em dado.

## TEC-250 — O prompt passou a dizer o que a régua sempre cobrou

A execução de 30/08 deixou 15 discrepâncias de extração, e 13 delas eram
`tipo_imovel` e `urgencia`. **O diagnóstico custou zero**: a instrumentação da
TEC-248 põe os valores crus na linha do relatório, e com eles mais as falas do
corpus as 13 se explicaram sem uma única chamada paga.

Nenhuma era o modelo errando.

### Causa A — a convenção por-turno era ambígua sobre RE-AFIRMAÇÃO

O prompt dizia *"preencha so o que a fala DESTE turno afirma"* e, no mesmo
texto, oferecia o estado acumulado como memória. Quando um turno posterior
**re-afirma** algo que já está no estado, as duas instruções apontavam para
lados opostos — e o modelo resolvia isso de forma inconsistente: 6 vezes não
reemitia onde o corpus esperava que sim, 1 vez reemitia onde esperava que não.

`follow-up-08` tinha os dois defeitos na mesma conversa: `urgencia` disparava
um turno cedo (*"bora marcar"*, sem marco temporal) e faltava no turno que tem
o marco (*"essa sexta a tarde"*).

### Causa B — regras de anotação que viviam só no corpus

O docstring de `TurnoAnotado` carrega as regras que a régua aplica, e **o
modelo nunca as via**. Ele era cobrado por um contrato que não recebeu:

- o imóvel que o lead **tem** não é o que ele procura (TEC-239);
- `urgencia` exige **marco temporal explícito**; entusiasmo não é marco.

### O que entrou, e o que custou

Três frases em `SISTEMA_DO_AGENTE`, cada uma travada por teste — `mesmo que ja
esteja no estado`, `O imovel que o lead ja tem nao e o que ele procura`,
`Urgencia so com marco temporal explicito`.

**A reserva subiu de 800 para 850**, e a alternativa foi procurada primeiro. Não
havia corte de ~92 caracteres que não tocasse algo medido: a enumeração das
tarefas (TEC-240), os parênteses que separam COMPRA de INVESTIMENTO, a guarda de
alucinação, a definição da confiança. Preço registrado: **50 tokens a menos de
literais por turno, 0,4% do contexto** — contra os 400 tokens (3,3%) que a
subida anterior custou.

830 não serviu, e o meio token importou: **na medição desta card**, 830 × 0,75
= 622,5 contra uma subcontagem de 622,8. Empatar com o teto derrotaria o fator
0,75, que existe para haver folga. (Esses são os números de 30/08/2026; a
TEC-243 tirou os valores derivados da prosa, e os de hoje saem de `python -m
pytest -q -k margem_do_orcamento -s`.)

### O resultado

| execução | precisão da extração | faixa |
| --- | --- | --- |
| 30/08, sonnet-5 | 88/103, 85,4% | AMARELO |
| 30/08, mesma régua (CI) | 87/104, 83,7% | **VERMELHO** |
| 30/08, com a TEC-250 | **89/97, 91,8%** | **VERDE** |

**Acima do alvo de 90%, não só do piso.** Primeira vez. A folga sobre o piso
passou de 0,4 para **6,8 pontos**.

**Desta vez a atribuição é segura**, e das anteriores não era: o efeito é de
**8,1 pontos** contra um ruído observado de **1,7** entre duas execuções do
mesmo sistema. Efeito cinco vezes maior que a dispersão medida não se explica
por sorte.

> **Emenda da TEC-244 (30/08/2026, 22:20 UTC).** O parágrafo acima ficou de pé
> sobre uma estimativa de ruído que a TEC-244 depois mediu de novo e achou
> **três vezes maior: 5,7 pontos**, entre duas execuções deste mesmo código.
> Com essa dispersão, o efeito de 8,1 pontos continua provavelmente real — é
> maior que ela —, mas **"cinco vezes maior que o ruído" está errado: é menos
> de uma vez e meia**. E os 91,8% desta execução são o topo de uma faixa, não
> um patamar: uma execução do código idêntico, duas horas depois, deu 86,1% —
> abaixo do alvo. Ver a seção TEC-244.
>
> **Emenda da TEC-253.** Duas correções à emenda acima. Primeira: 1,7 e 5,7
> são duas observações da mesma grandeza, não uma estimativa errada e uma
> certa — e o par que deu 1,7 **não pode ser reexaminado**, porque a execução
> de 83,7% não teve artefato preservado. Segunda, e é a que importa:
> decompondo a métrica, **o efeito de 8,1 pontos era quase todo redução de
> invenção**. Sobre a base fixa — acertos nos 96 campos anotados, que é
> constante — o antes deu 91,7% e as três execuções seguintes deram 92,7%,
> 90,6% e 91,7%. O `faltou` ficou em **8 antes e 8 depois**: a regra de
> re-afirmação, creditada acima com "Causa A: 3 de 7", não moveu o agregado.
> O efeito existe e é sobre inventar menos — que é a parcela volátil. Ver a
> seção TEC-253.

As discrepâncias caíram de 17 para **8**, e `urgencia` foi a **zero**.

### O que se resolveu, e o que não

**Causa B: 5 de 6.** As regras que faltavam no prompt funcionaram quase por
completo. Sobrou `aluguel-07[0]` — *"procuro republica ou kitnet"* —, onde o
corpus omite de propósito porque o lead oferece duas opções e não escolhe, e o
modelo continua escolhendo `APARTAMENTO` a partir de `kitnet`.

**Causa A: 3 de 7.** A regra de re-afirmação funcionou **parcialmente**, e o
padrão do que sobrou é nítido: os quatro casos restantes são todos de lead
**repetindo o MESMO termo** — `cobertura` duas vezes em `compra-06`, `sobrado`
de novo em `compra-11`, `comercial` de novo em `aluguel-08`. O caso que se
resolveu (`aluguel-05[1]`, *"pode ser flat tambem"*) é o único em que o lead
introduz um **sinônimo novo**.

A hipótese para a próxima card: o modelo trata repetir a mesma palavra como
"já disse isso" e trata um sinônimo novo como afirmação nova. A regra escrita
não distingue os dois casos. **Não está medido** — é leitura de quatro turnos,
não experimento.

### Lacunas conhecidas

- **Quatro discrepâncias de `tipo_imovel` continuam**, todas de repetição do
  mesmo termo. A hipótese acima não foi testada.
- **`aluguel-07[0]` é decisão de anotação em aberto.** O corpus omite porque o
  lead oferece duas tipologias; o modelo escolhe uma. Qual dos dois está certo
  é questão de régua, não de prompt.
- **`compra-09[1]` (`forma_pagamento: A_VISTA`) é discrepância nova**, que não
  aparecia nas execuções anteriores. Não foi diagnosticada aqui; **a TEC-244
  diagnosticou depois: era ruído** — o turno sumiu da lista numa das três
  execuções seguintes.
- **Duas execuções não são distribuição.** O ruído de 1,7 ponto vem de dois
  pontos sobre o mesmo sistema, e era a única dispersão medida que este projeto
  tinha. **A TEC-244 mediu um terceiro par e achou 5,7 pontos** — ver a seção
  dela, e a emenda acima.

## TEC-244 — A ordem do schema não era onde o problema estava

`SISTEMA_DO_AGENTE` sempre anunciou *"a cada turno você faz três coisas:
classifica a intenção do lead, **extrai o que ele procura**, e responde a
ele"*. O schema entregava `intencao → confianca → resposta → extracao`:
`extracao` era anexada depois da definição de `SCHEMA_DA_RESPOSTA`, porque
`SCHEMA_DA_EXTRACAO` só existe mais adiante no módulo, e a ordem saiu como
efeito colateral disso.

O modelo preenche o objeto na ordem declarada, então ele formulava a resposta
ao lead **antes** de ter isolado o que a fala afirma. A TEC-240 usou exatamente
esse argumento para escolher a ordem da frase — escolheu certo e descreveu o
schema errado, e a incoerência continuou entregue a cada turno de produção.

### A mudança, e o custo zero verificado

`extracao` passou para antes de `resposta` em `properties` e em `required`, via
`_ORDEM_DOS_CAMPOS` com guarda de import — `RuntimeError` e não `assert`,
porque `python -O` removeria o assert e a reordenação descartaria em silêncio
um campo novo.

`json.dumps(_SCHEMA_COMPILADO)` continua com **1424 caracteres, 356,0 tokens**
no proxy: mesmas chaves, mesmo conteúdo, só a ordem muda. O orçamento de
contexto não se mexe, e isso foi medido, não herdado da alegação da TEC-240.

### Três execuções, e o que elas dizem

O PR da TEC-243 disparou o gate pago sem que ninguém pedisse — o filtro de
`evals.yml` é por caminho e não distingue mudança de comentário. Isso saiu
caro e saiu **útil**: virou uma segunda medição da ordem antiga, com prompt e
schemas byte-a-byte idênticos aos da execução da TEC-250, corpus e régua
intocados e o mesmo `claude-sonnet-5`.

| execução | ordem | extração | discrep. | campos `extra` | intenção |
| --- | --- | --- | --- | --- | --- |
| 30/08 17:08 | antiga | 89/97 — **91,8%** VERDE | 8 | 1 | 143/146 |
| 30/08 19:51 | antiga | 87/101 — **86,1%** AMARELO | 14 | 5 | 143/146 |
| 30/08 22:20 | **nova** | 88/99 — **88,9%** AMARELO | 11 | 3 | 142/146 |

**Toda métrica da ordem nova cai entre as duas execuções da ordem antiga.**
Extração, contagem de discrepâncias, campos inventados: nenhuma delas sai da
faixa que o mesmo código produziu sozinho. A intenção ficou um turno abaixo,
que é menos que a variação de tudo o mais.

**O efeito da reordenação é indistinguível de ruído**, e isso é o resultado —
não um resultado que faltou.

### O que a comparação turno a turno mostra

As oito discrepâncias da primeira execução reaparecem **todas** na segunda: há
um núcleo determinístico de erro e uma cauda espúria que varia. Na ordem nova,
**sete das oito sobrevivem**. A que sumiu — `compra-09[1]`, `forma_pagamento:
A_VISTA` — é a mesma que a seção TEC-250 registrou como *"discrepância nova,
não diagnosticada"*: ela apareceu numa execução, sumiu na outra, e o diagnóstico
correto era ruído.

O núcleo que sobrevive é quase todo de repetição do mesmo termo — o padrão que
a TEC-250 já tinha isolado como hipótese. A ordem do schema não toca nele.

**Isso virou a TEC-252**, e não é da TEC-242: aquela decidiu o vocabulário
fechado (o que `kitnet`, `sobrado` e `studio` viram) e está Feita. Falhar em
reemitir um termo que o lead repete é outro defeito, e dois dos seis casos nem
são `tipo_imovel` — são `forma_pagamento` e `tem_imovel_para_vender`. Se a
hipótese estiver certa, o defeito é da regra de `null`, não da tipologia.

A hipótese do card era que extrair antes de responder reduziria campo
inventado. Os campos `extra` foram 1, 5 e 3: a ordem nova ficou no meio. **A
hipótese não se sustenta nem se refuta com esta amostra.**

### A decisão: a ordem nova fica

Fica, e não por ter ganhado a medição — ela empatou. Fica por três razões que
não dependem do número:

1. **Custa zero.** Nenhum token, nenhuma latência, nenhuma chamada a mais.
2. **Resolve a contradição** entre o que o prompt anuncia e o que o schema
   pede, que era o critério 2 do card. A alternativa seria editar o texto do
   prompt para anunciar `classifica, responde, extrai` — mais invasivo, e
   contra o argumento que a própria TEC-240 considerou correto.
3. **A medição não mostrou dano.** "Sem efeito detectável" é razão para manter
   a versão coerente, não para preferir a incoerente.

### O achado que vale mais que o card

**O ruído entre execuções da precisão de extração é de 5,7 pontos.** A seção
TEC-250 registra, como lacuna, que *"o ruído de 1,7 ponto vem de dois pontos
sobre o mesmo sistema, e é a única dispersão medida que este projeto tem"*.
Agora há um terceiro par, e a dispersão é **três vezes maior** do que aquela
estimativa.

Isso tem consequência para tudo que este gate mede:

- **Uma execução não distingue efeitos menores que ~6 pontos de extração.**
  Qualquer card que atribuir a uma mudança um ganho dessa ordem está lendo
  ruído, a menos que rode várias vezes por braço.
- **A acurácia de intenção não tem esse problema**: 143, 143, 142 em três
  execuções. O ruído é específico da extração, e a mecânica é visível — o
  núcleo de erro é estável e a cauda de campo inventado é que oscila. O
  denominador oscila junto, porque campo `extra` entra na conta.
- **A conclusão da TEC-250 fica enfraquecida**, e está anotada lá.

### Lacunas conhecidas

- **Três execuções ainda não são distribuição.** 5,7 pontos é a maior
  dispersão observada, não a dispersão real. O limite superior continua
  desconhecido.
- **A hipótese do card não foi respondida, só arquivada.** Responder se a
  ordem reduz invenção exigiria várias execuções por braço — dinheiro que a
  pergunta, medida esta, não justifica.
- **O núcleo estável de sete discrepâncias continua**, e é a **TEC-252**.
- **O ruído medido aqui não foi tratado, só registrado.** Decidir o protocolo
  de medição — quantas execuções por braço, ou atacar a variância na fonte —
  é a **TEC-253**, e a TEC-252 depende dela para ser medida sem repetir o
  erro de atribuição da TEC-250.

## TEC-253 — O que o gate resolve, e duas atribuições que não sobrevivem

A precisão da extração é a métrica que este projeto mais usou para decidir, e
até aqui ninguém sabia quanto dela é sinal. Duas execuções do **mesmo código**
— prompt, schema, corpus, régua e modelo idênticos — deram **91,8% (VERDE)** e
**86,1% (AMARELO)**. A mesma árvore atravessa o alvo dependendo da hora.

### A causa: a métrica soma duas coisas que se movem diferente

`precisao_da_extracao` usa denominador de **união** (`esperado | obtido`), e
isso está certo: sem contar o inventado, um modelo que acerta o anotado e
inventa mais quatro tiraria 100%. O preço é que ela junta numa razão só o
defeito e o ruído.

Os campos **anotados** são 96 em toda execução — é o corpus, constante por
construção. Decompondo as cinco execuções preservadas de 30/08/2026:

| execução | modelo | união (trava) | base fixa (`acertos/96`) | `faltou` | `divergiu` | `extra` |
| --- | --- | --- | --- | --- | --- | --- |
| 12:02 | opus-5 | 79,2% VERMELHO | 83,3% | 8 | 8 | 5 |
| 14:44 | sonnet-5 | 85,4% AMARELO | 91,7% | 8 | 0 | 7 |
| 17:08 | sonnet-5 | **91,8% VERDE** | 92,7% | 7 | 0 | 1 |
| 19:51 | sonnet-5 | **86,1% AMARELO** | 90,6% | 8 | 1 | 5 |
| 22:20 | sonnet-5 | 88,9% AMARELO | 91,7% | 8 | 0 | 3 |

As duas linhas em negrito são o **mesmo código**. Leia as colunas:

- **`faltou` é praticamente constante** — 8, 8, 7, 8, 8 — em cinco execuções,
  dois modelos e três versões de prompt. É o defeito, e ele é determinístico.
- **`extra` é que oscila** — 1 a 7 —, e cada campo inventado desconta **duas
  vezes**: deixa de ser acerto e infla o denominador.
- **A base fixa dispersa menos que a união**: 2,1 pontos contra 5,7 no par do
  mesmo código.

> **Emenda da execução de 31/08.** A palavra **determinístico** acima é forte
> demais, e a sexta execução mostrou por quê. O `faltou` manteve a contagem
> (7) e **trocou de membros**: `aluguel-05` e `follow-up-01` saíram,
> `compra-13[1]` e `follow-up-08[1]` entraram. Cinco dos oito permanecem.
>
> O que é estável é a **contagem**, não a lista de turnos. A distinção entre
> núcleo e cauda continua valendo — `faltou` oscila muito menos que `extra` —,
> mas ela é estatística, e tratá-la como um conjunto fixo de turnos foi ler
> dois pontos como se fossem uma distribuição. É o erro que esta própria seção
> documenta, cometido por ela. Ver a seção da execução de 31/08.

### O poder de resolução

**Uma execução não sustenta atribuir um efeito de menos de ~6 pontos na
métrica de união, nem de ~2 pontos na base fixa.** Esses são os maiores
desvios observados entre execuções do mesmo código, não a dispersão real —
duas execuções não são distribuição, e o limite superior continua desconhecido.

O número mora em `DISPERSAO_MEDIDA` (`src/mobia/evals/metricas.py`), datado, e
**o relatório de toda execução agora o imprime**, numa seção que vem antes da
lista de discrepâncias. Quem abre o artefato para comparar com a execução
anterior esbarra no aviso antes de formar opinião — que é exatamente o que não
aconteceu nas duas atribuições abaixo.

### O protocolo, e ele é mais barato do que parecia

A saída óbvia era rodar N execuções por braço e multiplicar a conta por N. A
decomposição dá uma mais barata, porque as parcelas não precisam do mesmo
tratamento:

- **Para efeito sobre o defeito** (`faltou`, `divergiu`): compare as contagens
  diretamente. São estáveis o bastante para uma execução por braço dizer
  alguma coisa — 8, 8, 7, 8, 8 é um sinal limpo.
- **Para efeito sobre invenção** (`extra`): precisa de várias execuções por
  braço. É a parcela volátil, e nenhuma execução isolada decide.
- **Nunca compare o percentual de união entre execuções** para atribuir causa.
  Ele é a métrica certa para *travar* — pune os dois lados — e a errada para
  *comparar*.

### Duas atribuições que não sobrevivem

**A TEC-250 não melhorou a extração do que estava anotado.** Ela reivindicou
8,1 pontos (85,4% → 91,8%). Na base fixa: 91,7% → 92,7%, e as três execuções
pós-TEC-250 dão 92,7%, 90,6% e 91,7% — média igual à de antes. O `faltou`
ficou em 8 antes e 8 depois. **O que a TEC-250 mexeu foi a invenção**, de 7
para 1/5/3 campos — efeito real, e as regras dela eram mesmo em parte sobre
isso, mas é outro efeito, e é o volátil. A regra de re-afirmação, que ela
creditou com "Causa A: 3 de 7", não moveu o `faltou` agregado.

**A troca de `modelo_agente` para sonnet-5 não tem medição de extração que a
sustente.** A comparação opus-5 (12:02) contra sonnet-5 (14:44) atravessa a
TEC-248, que mudou a régua: `normalizar_regiao` entrou em `schemas.py` e
`metricas.py` mudou 83 linhas entre os dois commits. E os números batem exato
com essa explicação — os 8 `divergiu` do opus eram **7 de `regiao`** e um de
`urgencia`, e viraram acerto; `acertos` foi de 80 para 88, `faltou` ficou em 8
nos dois lados. **O ganho inteiro é da régua, não do modelo.** A troca pode ter
sido boa; a extração não a mediu.

A acurácia de intenção não sofre disso — 142, 143, 143, 143, 142 nas cinco
execuções — e é a única das duas em que "sonnet-5 aguentou" se sustenta.

### O que mudou no código

`decomposicao_da_extracao` refaz a mesma varredura de `precisao_da_extracao`,
aberta por tipo, e o relatório ganhou a seção. **Nada do que trava mudou**: a
métrica de união e o piso de 85% continuam idênticos — esta card mediu o
instrumento, não mexeu no que ele cobra. Um teste amarra as duas contas
(`anotados + extra == total` da métrica de união), para as fórmulas não
divergirem em silêncio.

### Lacunas conhecidas

- **Dois pares não são distribuição.** 5,7 e 2,1 são os maiores desvios
  observados. Caracterizar a dispersão de verdade custaria execuções pagas que
  esta card não gastou.
- **O par que sustentava os "1,7 pontos" não pode ser reexaminado.** A
  execução de 83,7% que a TEC-250 citou não teve o artefato preservado — é
  anterior ao commit que fez o relatório de CI parar de ser efêmero —, então a
  decomposição dela não existe e não dá para saber se aqueles 1,7 eram do
  mesmo código.
- **A variância não foi reduzida, só isolada.** Atacar a cauda de invenção é
  mudança de comportamento, e é a TEC-252.
- **A base fixa não é métrica de gate, e não virou uma.** Ela ignora invenção
  de propósito; usá-la para travar reabriria o furo que o denominador de união
  fecha.

## TEC-252 — A métrica de extração cobrava reemissão; produção nunca viu

A hipótese da card era que o modelo deixa de reemitir um campo quando o lead
repete o mesmo termo. **Ela se confirmou com nitidez rara** — e a conclusão que
ela previa se inverteu.

### A hipótese, medida no corpus

O corpus tem exatamente **sete turnos de reafirmação**: mesmo campo, mesmo
valor já anotado antes na conversa. O modelo falha em **seis deles**. O único
que passou, `compra-09[1]`, é justamente o que apareceu e sumiu entre as
execuções — ruído.

Fora das reafirmações, sobram duas faltas. A concentração é quase perfeita.

### Por que o modelo falha, e por que ele está certo

As falas dizem tudo:

> `compra-06[2]`: *"qual o valor do condominio **dessa cobertura**?"*
> `compra-11[2]`: *"**o sobrado** tem escritura ja regularizada?"*
> `aluguel-08[2]`: *"o predio ja tem alvara pra uso **comercial** de saude?"*

Em todos, o termo aparece como **referência ao imóvel em discussão**, não como
afirmação de um critério de busca. *"Qual o valor do condomínio dessa
cobertura?"* pressupõe que é uma cobertura; não afirma. E a regra do prompt
manda extrair *"só o que a fala DESTE turno afirma"*. **O modelo está
obedecendo à regra.**

### A consequência: seis dos oito erros não existem em produção

`campos_a_gravar` — a função que `gravar_estado` e o runner do eval
compartilham — documenta que **`None` no campo não apaga**. Nos seis casos, um
turno anterior extraiu o valor certo, e o estado o carrega. O modelo devolver
`null` depois não muda nada.

Mas `precisao_da_extracao` compara **turno a turno**: `obtido` é o
`preenchidos()` daquele turno. Ela conta seis erros que o lead nunca vive.

E a punição é simétrica, o que fecha o diagnóstico:

- **`follow-up-06`**: o corpus anota `tem_imovel_para_vender` no turno 0; o
  modelo o reemitiu no turno 2, onde não há anotação. Turno a turno isso é
  `extra` — invenção. Punido por reafirmar **demais**.
- **`follow-up-08`**: o corpus anota `urgencia` no turno 1; o modelo a extraiu
  no turno 0. Também `extra`. Punido por acertar **cedo**.

**A métrica por turno é uma métrica de *timing* disfarçada de métrica de
*conteúdo*.** Ela cobra que o modelo emita cada campo exatamente nos turnos em
que o corpus o anotou — e produção só enxerga o estado acumulado.

### A extração efetiva

`precisao_efetiva_da_extracao` compara o **estado final de cada conversa**
contra a anotação acumulada. É o espelho do que `acuracia_efetiva` já faz para
a intenção: medir o que produção entrega, não o palpite cru.

Reconstruindo a execução de 30/08 22:20 a partir do relatório preservado, sem
execução nova:

| | turno a turno | **efetiva** |
| --- | --- | --- |
| precisão | 88,9% | **96,6%** (85/88) |
| divergências | 11 | **3** |

E as três que sobram têm donos diferentes:

- **`aluguel-07`, `tipo_imovel` (`extra`)** — o lead diz *"republica ou
  kitnet"*, oferece duas tipologias e o corpus omite de propósito. É a disputa
  de anotação já registrada na seção TEC-250. **Questão de régua.**
- **`compra-10`, `tem_imovel_para_vender` (`faltou`)** — *"queremos comprar
  nosso primeiro imovel"*. O corpus pede **inferir** `False` de "primeiro
  imóvel"; a guarda de alucinação do prompt proíbe inferir o não-dito.
  **Corpus e prompt se contradizem**, e não dá para atender aos dois.
- **`follow-up-01`, `tipo_imovel` (`faltou`)** — *"ainda ta de pe aquele
  apartamento que vc me mostrou?"*. **Esta é falha limpa do modelo**, e é a
  única.

**O defeito real de extração é um turno em 146.**

### Por que a regra no prompt não foi escrita

A card previa ajustar a regra de `null` para o modelo reafirmar pressuposição.
Não foi feito, e a razão é dupla:

1. **Não melhoraria o produto.** O estado já está certo nos seis casos. A
   mudança melhoraria só o número.
2. **Custaria orçamento que não existe.** A margem sobre o teto de 627 é de
   **4,2 tokens** (`pytest -q -k margem_do_orcamento -s`). Gastar isso para
   mover uma métrica que não mede o produto, num caminho pago e em todo turno
   de produção, é o oposto do que a TEC-253 acabou de estabelecer.

E há o risco de fazer mal: ensinar o modelo a reafirmar o pressuposto empurra
na direção contrária à guarda de alucinação, que é a única que existe.

### O que isso diz sobre as cards anteriores

A TEC-240 e a TEC-250 gastaram orçamento de prompt para mover a precisão da
extração. A TEC-253 já tinha mostrado que a TEC-250 não melhorou o que estava
anotado — só reduziu invenção. Esta card mostra por que a régua parecia pior do
que o produto: **boa parte do que ela cobrava era reemissão, não extração.**

### Lacunas conhecidas

- **A efetiva é diagnóstico, não trava.** Promovê-la exigiria piso próprio e
  medido; o de `precisao_da_extracao` foi calibrado contra outra conta, e
  mexer no que o gate cobra estava fora de escopo aqui e na TEC-253.
- **Ela compara só o estado final.** Um campo gravado certo e depois
  sobrescrito errado aparece pelo valor final. Comparar a cada turno daria
  peso maior a conversa longa, e o valor final é o que o handoff e o lead
  scoring vão ler.
- **Os 96,6% são reconstrução**, não execução nova — derivados do relatório de
  22:20 e do corpus. ~~A próxima execução paga imprime o número medido.~~
  **Ela imprimiu 94,4%, e os dois não são comparáveis:** a TEC-254 mudou a
  régua entre a reconstrução e a medição, então ela ficou sem conferência
  possível. Ver a seção da execução de 31/08.
- **`follow-up-01[0]` não era defeito estável.** A execução de 31/08 não o
  encontrou — o modelo extraiu o campo. A conclusão de que ele era "a única
  falha limpa do modelo" saiu de uma execução só, que é exatamente o que a
  TEC-253 manda não fazer.
- ~~**`compra-10` continua em aberto**, e é decisão de régua.~~ **Fechada
  pela TEC-254, e o corpus cedeu:** a anotação por pressuposição saiu, o turno
  virou negativo, e a execução de 31/08 confirmou que ele deixou de divergir.

## TEC-235 — O limiar fica em 0,6, e o custo que motivou a card desapareceu sozinho

A card foi escrita em 27/08/2026 com a primeira medição do gate, e o argumento
dela era forte: o rebaixamento por confiança convertia **4 acertos em erros e
corrigia zero**, e os 3 pontos entre a acurácia crua e a efetiva eram
inteiramente acertos jogados fora. Uma segunda execução no mesmo dia confirmou:
6 acertos rebaixados, zero erros recuperados.

**Em 30/08 esse custo é zero, e ninguém tocou no limiar.**

| data | modelo | turnos sub-limiar | acertos rebaixados (custo) | erros recuperados (benefício) | crua × efetiva |
| --- | --- | --- | --- | --- | --- |
| 27/08 | opus-5 | 13/136 | **4** | 0 | 95,6% × 92,6% |
| 27/08 | opus-5 | 12/136 | **6** | 0 | 96,3% × 91,9% |
| 30/08 12:02 | opus-5 | 5/146 | 1 | 0 | 97,3% × 96,6% |
| 30/08 14:44 | sonnet-5 | 4/146 | **0** | 0 | 97,9% × **97,9%** |
| 30/08 17:08 | sonnet-5 | 4/146 | **0** | 0 | 97,9% × **97,9%** |
| 30/08 19:51 | sonnet-5 | 4/146 | **0** | 0 | 97,9% × **97,9%** |
| 30/08 22:20 | sonnet-5 | 3/146 | **0** | 0 | 97,3% × **97,3%** |

Nas quatro execuções com `sonnet-5`, **a acurácia efetiva é igual à crua**. Não
há mais lacuna para fechar.

### O que mudou, e o que não

Entre as duas datas trocou o modelo (`opus-5` → `sonnet-5`) e o prompt cresceu
duas vezes (TEC-240, TEC-250). A distribuição de confiança subiu junto: os
turnos de compra com transação implícita — *"quanto ta pedindo?"*, *"da pra
negociar o valor?"* — que voltavam entre 0,50 e 0,58 pararam de voltar.

**O benefício nunca existiu.** `erros que o rebaixamento acertou` deu **zero em
todas as sete execuções**, de duas datas, dois modelos e três versões de
prompt. O limiar nunca salvou nada.

Com custo zero e benefício zero, **o limiar está inerte** neste corpus.

### A decisão: fica em 0,6

Baixá-lo compraria um benefício medido de **zero** e assumiria risco não
medido — que é o oposto do que a card pedia. Os critérios de aceite dela, em
Gherkin, pedem que "a quantidade de acertos rebaixados diminua" e que "a
acurácia efetiva suba": as duas já estão no melhor valor possível, e não há
como satisfazê-los mexendo no número.

O terceiro critério — *"quem consulta o porquê daquele valor encontra a medição
que o sustenta, e não um palpite"* — **é o que esta card entrega**. O
comentário de `LIMIAR_DE_DESAMBIGUACAO` deixou de dizer "provisório até a
TEC-210 medir" e passou a carregar os números, e um teste trava o valor para
que quem o baixar leia o porquê antes.

### O que faria falta para calibrar de verdade

O benefício ser zero é **fato sobre o corpus**, não licença para eliminar o
limiar. O corpus não tem turnos de ambiguidade genuína — aqueles em que
perguntar é a resposta certa —, então ele mede só um lado da conta. Quem quiser
mexer no limiar precisa primeiro anotar turnos que exercitem o outro lado.

A card já dizia isso nas regras de negócio. A medição confirmou.

### O `0,8` não existia

Dois comentários citavam "os limiares de 0,8 e 0,6" como se houvesse dois.
**Não há.** A única comparação de confiança em `src/` é contra
`LIMIAR_DE_DESAMBIGUACAO`; o `0,8` nunca governou decisão nenhuma. As menções
saíram, e um teste varre `src/mobia/domain/agente/` para que um segundo limiar
só entre nomeado — um número solto num `if` é exatamente como o `0,6` começou,
e foram três cards até ele virar medição.

### Lacunas conhecidas

- **A calibragem continua impossível com este corpus**, e agora está escrito
  por quê.
- **O custo pode voltar.** Ele sumiu por efeito colateral de mudanças de
  modelo e prompt, não por decisão. Se a distribuição de confiança descer de
  novo, o custo volta — e o gate mostra, porque mede as duas colunas em toda
  execução.
- **Nenhuma execução paga foi gasta nesta card.** Os sete pontos saíram dos
  relatórios preservados e da própria descrição da card.

## TEC-237 — O porquê do erro do provedor, sem afrouxar a regra que o escondia

Em 28/08/2026 o gate pago falhou em **100% das chamadas** — 50 de 50 conversas
de intenção e 41 de 41 casos de moderação — com `BadRequestError`, em 13
segundos. Nenhuma linha do caminho de chamada tinha mudado. **O diagnóstico
levou um dia e passou por três hipóteses erradas.**

A causa estava na primeira linha do corpo de erro:

```
400 invalid_request_error
"Your credit balance is too low to access the Anthropic API."
```

Saldo esgotado volta como **400**, o mesmo código de um erro de contrato entre
cliente e servidor. Por isso pareceu problema de schema ou de versão de SDK.

### A regra que escondeu a resposta estava certa

O código nunca interpola `str(exc)`, e não por descuido: `KeyError` e
`TypeError` de um schema inesperado **ecoam o valor recebido** na mensagem da
exceção, e esse valor pode ser a fala do lead. A garantia é da TEC-134 e está
escrita em cada um dos pontos que a aplicam.

Aplicada sem exceção, ela apagou a única informação que resolvia o caso.

### A distinção que abre a exceção

**Corpo de erro de `APIStatusError` é gerado pelo servidor**; mensagem de
exceção arbitrária é montada pelo Python interpolando o que estourou. São
coisas diferentes, e só a primeira passa.

`motivo_do_provedor` (`src/mobia/infra/anthropic.py`) devolve `None` para
qualquer exceção que não seja `APIStatusError` — **não há ramo de melhor
esforço**, que seria exatamente o buraco que a função existe para não abrir.
Um `APIConnectionError` também não passa: é do SDK, mas não houve resposta
HTTP, então não há corpo do servidor para citar.

Para os que passam, sai status, tipo, mensagem e `request_id` — este último não
estava no escopo da card e entra porque é handle de correlação com o suporte do
provedor, sem conteúdo nenhum.

### Onde aparece

- **Relatório do eval**: `FalhaDeInfraestrutura` ganhou `motivo`, indentado sob
  a falha. As 91 linhas cegas de 28/08 diriam que foi crédito.
- **`montagem.py`**: o log de `contexto.degradado` ganhou `motivo`.
- **`moderacao.py`**: `ModeracaoIndisponivel` passa a carregar o motivo quando
  ele existe, e o nome da classe quando não. Foi este caminho que somou 41 das
  91 falhas.

### O risco que sobra, e ele não é zero

A garantia depende de o provedor não ecoar o payload no corpo de erro. Isso
vale para erros de conta, permissão e limite — os que motivaram a card —, mas
um erro de validação de schema poderia, em tese, citar o valor recusado.

Três coisas limitam o estrago: o teto de 300 caracteres, o mascaramento de
corrida de dígitos que `app/logging.py` aplica a todo valor logado, e o fato de
a fala do lead ir em `messages`, que a API valida por forma e não por conteúdo.

**Não é prova.** É o balanço entre um dia de diagnóstico e um risco estreito,
tomado com os olhos abertos e escrito aqui para quem vier depois poder
discordar.

### Lacunas conhecidas

- **O teto de versão do SDK continua sem existir.** A primeira versão da card
  culpava a atualização de `anthropic` 1.1.0 → 1.2.0; a comparação arquivo a
  arquivo mostrou que os quatro do caminho de chamada são idênticos. É boa
  prática e pede card própria — não sob a justificativa deste incidente.
- **Não há alerta de saldo.** Esta card faz o diagnóstico custar cinco minutos
  em vez de um dia; não impede a próxima parada.

## TEC-236 — A fala bloqueada saía do turno, mas continuava entrando no contexto

A moderação de entrada da TEC-233 impede que a fala bloqueada vire **resposta
naquele turno** — não que ela vire contexto ou resumo depois. O spec daquela
card afirmava o contrário, e a divergência já estava registrada.

O caminho que expunha o defeito: o lead manda M1 (bloqueada), recebe a recusa,
manda M2 — e o turno de M2 monta contexto **decifrando M1 inteira** para dentro
do prompt. Na dobra dos ~40 turnos, M1 entra no resumo permanente e fica lá.

### Marca em paralelo ao `status`, e não um `MessageStatus` novo

A card deixou a escolha ao implementador e pediu que ficasse registrada. É esta,
e as três razões:

- **`status` responde outra pergunta.** Ele diz se o pipeline de ingestão
  terminou com a linha. Um turno bloqueado **entregou** a recusa ao lead: ele
  terminou, e `PROCESSED` é a resposta certa. Um `BLOCKED` terminal contaria a
  mesma história com outra palavra.
- **`CLAIMABLE_STATUSES` governa o que o sweeper reivindica.** Um valor novo no
  enum obriga a revisar essa tupla e todo `status ==` do projeto por uma
  pergunta que não é sobre retentativa.
- **As duas coisas coexistem.** Uma fala bloqueada cuja recusa não foi entregue
  é `FAILED` **e** bloqueada. Um campo só não representa isso.

E há a prova estrutural: `status` é escrito por `process_message`, pelo desfecho
do turno; `executar_turno` nunca toca nele. As duas colunas são escritas por
camadas diferentes. Um teste afirma exatamente isso.

`bloqueada_em` é timestamp e não booleano pelo mesmo motivo de
`desambiguado_em`: ocupa o mesmo espaço e responde "quando" numa investigação.

### O filtro mora na janela, e o resumo herda de graça

`literais_apos` ganhou `Message.bloqueada_em.is_(None)`. É o ponto por onde tudo
que monta contexto ou resumo passa, então o que não sai dali não chega a lugar
nenhum — `dividir` recebe o que `literais_apos` devolve, e a dobra nunca vê a
fala bloqueada.

**Consequência aceita:** a mensagem bloqueada deixa de contar para o gatilho de
regeneração. É correto — o gatilho conta o que vai virar prompt —, e está
anotado no teste que precisou semear 41 em vez de 40 por causa disso.

### Marcar vem antes de entregar, e a ordem é o ponto

`_entregar_texto_fixo` tem três saídas que não entregam nada: janela de 24h
fechada, recusa permanente da Meta, reentrega suprimida. **Duas delas fecham a
linha em `PROCESSED`, que é terminal** — ninguém volta nela.

Marcar depois da entrega deixaria a fala bloqueada sem marca exatamente nos
casos em que ninguém mais passa por ali, e ela entraria no contexto do turno
seguinte. Um teste cobre isso com a janela fechada.

### A marca propaga a falha, ao contrário da telemetria

`marcar_bloqueada` mora fora de `MessageRecorder` de propósito. O contrato
daquele é explícito — *"nenhum método propaga exceção"* — e está certo para
telemetria: perder uma linha de custo não pode derrubar a resposta.

Aqui a escolha é a oposta. Se a marca falhar em silêncio, a fala bloqueada
continua elegível para o contexto e para o resumo permanente. O desfecho seguro
é falhar o turno, deixar a linha em `FAILED` e o sweeper retentar — pagando de
novo a moderação, que é barata perto de vazar a fala para dentro do prompt.

### Lacunas conhecidas

- **As falas bloqueadas antes desta migration não têm marca**, e não há como
  distingui-las: o bloqueio não deixava rastro na linha, e esse era o defeito.
  Elas continuam elegíveis para contexto e resumo. Backfill exigiria re-moderar
  histórico (pago) ou cruzar com o log de `moderacao.entrada_bloqueada`, que
  retém por tempo limitado. Está escrito na própria migration.
- **Bloqueio de saída não grava marca**, e não precisa: `_entregar_texto_fixo`
  registra o texto neutro entregue, e a fala recusada do modelo nunca existiu
  como linha.
- **Moderação com histórico da conversa** — falas individualmente inofensivas
  que compõem assédio ao longo de vários turnos — continua fora, é outra lacuna
  declarada e outra card.

## TEC-254 — As duas disputas de régua, decididas em direções opostas

A TEC-252 mediu a extração como produção a experimenta e sobraram três
divergências em 146 turnos. Uma era falha do modelo; **as outras duas eram
disputas de régua**, e nenhuma tinha dono. Esta card as decide — e cada uma
caiu para um lado diferente.

### `compra-10[0]` — o prompt vence a pressuposição

> *"minha esposa e eu queremos comprar nosso primeiro imovel, pode me ajudar a
> entender o processo?"* → o corpus anotava `tem_imovel_para_vender: false`.

Ninguém disse isso; deduz-se de "primeiro imóvel". E `SISTEMA_DO_AGENTE` diz
*"**Nao infira**: extrair o que a fala nao afirma conta erro igual a nao
extrair o que ela afirma"*.

**A colisão era deliberada dos dois lados, e ninguém tinha visto.** As duas
regras são de 29/08/2026: o prompt às 11:20 (TEC-240), a anotação às 22:25
(TEC-246, commit *"anafora vence a pressuposicao, e primeiro imovel volta pra
medicao"*). A anotação veio **onze horas depois** da regra que ela contradiz.

**Decisão: o corpus cede.** O prompt é o contrato a que o modelo responde;
cobrar dele o oposto do que se pede é medir errado, não medir alto. E o corpus
já era inconsistente consigo: dos três turnos que anotam esse campo, os outros
dois — *"preciso vender"*, *"quero colocar meu apartamento a venda"* — são
afirmação direta.

Vira **negativo** e não exclusão, e isso não é escolha: pressuposição não está
entre as três famílias que a exclusão reserva, e foi a própria TEC-246 que a
tirou daquela lista.

### `aluguel-07[0]` — o modelo vence a omissão

> *"sou estudante, procuro republica ou kitnet pra alugar perto da unicamp"* →
> o corpus omitia `tipo_imovel`; o modelo devolvia `APARTAMENTO` e levava
> `extra` em toda execução.

`kitnet` **está** no vocabulário, e a TEC-242 decidiu que ela vira
`APARTAMENTO`. `república` não está, porque é uso e não tipologia. O lead
nomeou uma coisa que a régua reconhece e uma que ela não reconhece.

**Decisão: o modelo acertou.** Oferecer uma segunda opção não desfaz o que foi
nomeado. O turno passa a anotar `tipo_imovel: APARTAMENTO`, e o falso positivo
permanente da régua desaparece.

**A linha entre as duas decisões é a mesma**, e agora está escrita no docstring
de `TurnoAnotado`, onde o próximo anotador a lê antes de anotar: vale o que a
fala **diz**, não o que ela deixa concluir.

### O terceiro passo, que a card não previa

Tirar a pressuposição de `compra-10[0]` deixou o corpus **sem nenhuma anotação
de `tem_imovel_para_vender: false`** — era o único turno que a tinha, e
`test_todo_valor_do_vocabulario_tem_anotacao` reprovou. Com razão: `False` é
justamente o valor que `preenchidos()` existe para preservar (`is not None`, e
não a veracidade do valor), e um corpus que nunca o mede não guarda esse
contrato.

Nenhuma fala do corpus afirmava isso explicitamente. **Foi preciso escrever
uma** — *"a gente nao tem nenhum imovel pra vender, vai ser so a compra
mesmo"* —, acrescentada a `compra-10`. Ela afirma do mesmo jeito que os outros
dois turnos do campo, que era o que faltava.

### A régua mudou, e a comparação fica cortada aqui

O corpus foi de 146 para **147 turnos**, e três anotações se mexeram. **Execuções
anteriores a 31/08/2026 não são comparáveis com as posteriores** na precisão de
extração.

Isto está escrito porque foi assim que a TEC-248 confundiu a leitura da troca de
modelo — a régua mudou no meio e ninguém marcou o corte, e a TEC-253 gastou
metade de uma varredura para descobrir. Os totais coincidirem (96 → 97
anotações, 62 positivos nos dois) é coincidência dos três movimentos, não
estabilidade.

**Efeito esperado na próxima execução paga:** duas das três divergências da
extração efetiva somem, e sobra `follow-up-01[0]` — a única falha limpa do
modelo, que é da TEC-252.

### Lacunas conhecidas

- **O sinal de "primeira compra" continua sem ser capturado**, e agora por
  decisão. Se ele tiver valor comercial, sai da extração e vira derivação em
  outro lugar, fora do caminho pago — card própria, e não bloqueia nada hoje.
- **O turno novo nunca foi medido.** Ele entra na próxima execução paga como
  qualquer outro; se o modelo falhar nele, é falha de verdade e não artefato.

## A execução de 31/08 — o que ela verificou, e a previsão minha que ela derrubou

Primeira execução paga depois de sete cards, e a primeira com o corpus de 147
turnos. Relatório em `evals/relatorios/2026-08-31-verificacao-das-decisoes.md`.

| métrica | resultado |
| --- | --- |
| acurácia de intenção | 143/147 — **97,3% VERDE** (crua = efetiva) |
| precisão da extração (união, é a que trava) | 89/98 — **90,8% VERDE** |
| precisão da extração (base fixa) | 89/97 — 91,8% |
| **extração efetiva** (estado final) | **85/90 — 94,4%** |
| decomposição | `faltou` 7 · `divergiu` 1 · `extra` 1 |

### O que ela verificou

**As duas decisões de régua da TEC-254 funcionaram.** `compra-10` e
`aluguel-07` sumiram das duas listas de divergência. São verificações
**categóricas** — o turno aparece ou não —, então uma execução basta, ao
contrário de qualquer leitura de percentual.

**A extração efetiva saiu medida pela primeira vez**, e as seções que a TEC-252
e a TEC-253 acrescentaram ao relatório foram impressas numa execução real. Até
aqui existiam só em teste unitário.

### A previsão que ela derrubou, e ela era minha

A TEC-252 concluiu que `follow-up-01[0]` era **"a única falha limpa do
modelo"** — o defeito de verdade, depois de descontar artefato de medição e
disputa de régua.

**Ele não aparece nesta execução.** O modelo extraiu o campo. Não era defeito
estável: era cauda de ruído, e foi chamado de determinístico com base numa
execução só.

O `faltou` conta a mesma história de outro jeito. Ele manteve a **contagem**
— 7, contra 8, 8, 7, 8, 8 nas cinco anteriores — e **trocou de membros**:
`aluguel-05` e `follow-up-01` saíram; `compra-13[1]` e `follow-up-08[1]`
entraram, os dois em `urgencia`. Cinco dos antigos permanecem.

**A conclusão da TEC-253 precisa de emenda.** Ela afirmou que "as oito
discrepâncias da primeira execução reaparecem todas na segunda" e concluiu que
o núcleo era determinístico. Isso era verdade para o par que ela comparou. Com
mais pontos, o que é estável é a **contagem**; a identidade dos turnos varia
mais do que dois pontos deixavam ver. A distinção entre núcleo e cauda continua
útil — `faltou` oscila muito menos que `extra` —, mas ela é estatística e não
uma lista fixa de turnos.

É o erro que a própria TEC-253 documentou, cometido por quem o documentou.

### Uma validação que ficou impossível, e é erro de sequenciamento

Os **96,6% (85/88)** que a seção TEC-252 registra são reconstrução, derivada do
relatório de 30/08 22:20 e do corpus daquela data. A medição de hoje dá
**94,4% (85/90)** — mesmo numerador, denominador diferente.

**Os dois números não são comparáveis**, porque a TEC-254 mudou a régua entre
um e outro. Rodar o gate **antes** da TEC-254 teria validado a reconstrução;
rodar depois não valida nem refuta. A reconstrução cumpriu o papel dela, que
era informar a decisão, mas ficou sem conferência — e isso foi escolha de ordem,
não acaso.

### O que apareceu de novo

- **`compra-13[0]`: `regiao` divergiu** — anotado `sao roque`, obtido `sao
  roque e arredores`. Mesma classe que a TEC-248 tratou: o modelo devolve o
  lugar com uma qualificação a mais. Não tem card.
- **`urgencia` voltou a falhar em dois turnos** (`compra-13[1]` SEM_PRESSA,
  `follow-up-08[1]` IMEDIATA), depois de a TEC-250 tê-la levado a zero. Dentro
  da faixa de ruído que a TEC-253 mediu, mas é o campo a observar na próxima.
- **`extra` caiu para 1**, o menor desde 30/08 17:08.

### O que continua sem resposta

**Esta é uma execução.** Com 5,7 pontos de ruído medido na métrica de união,
ela não distingue efeito de ruído — serve como baseline nova, que a mudança de
régua tornou obrigatória, e como verificação das decisões categóricas.

**A baseline válida para comparação passa a ser esta**, e não nenhuma das seis
de 30/08.

### A segunda execução de 31/08 — o primeiro número de tom, e o primeiro par válido

Disparada às 13:19 UTC, **mesmo código e mesma régua** da de 11:46: os dois PRs
entre elas foram documentação e medição, nada que o modelo veja. Relatório em
`evals/relatorios/2026-08-31-aderencia-ao-tom-medida.md`.

| | 11:46 | 13:19 |
| --- | --- | --- |
| acurácia de intenção | 143/147 | 144/147 |
| acurácia efetiva | 143/147 | 143/147 |
| **extração (união)** | **89/98 — 90,8%** | **89/98 — 90,8%** |
| base fixa | 89/97 — 91,8% | 89/97 — 91,8% |
| `faltou` / `divergiu` / `extra` | 7 / 1 / 1 | 8 / 0 / 1 |
| extração efetiva | 85/90 — 94,4% | 86/92 — 93,5% |
| **aderência ao tom** | — | **121/147 — 82,3% AMARELO** |

#### A dispersão deu 0,0, e o número conservador não baixou

As duas execuções deram **exatamente** 89/98. A composição mudou — um
`divergiu` virou `faltou` — mas o total não.

`DISPERSAO_MEDIDA` **continua em 5,7**. Baixar para 0,0 diria que o gate
resolve efeitos arbitrariamente pequenos, e isso é falso: duas execuções
concordarem uma vez não é ausência de dispersão.

**A leitura que os três pares agora sustentam:** a dispersão não é propriedade
fixa da métrica, é função de **quanto o modelo inventa naquela execução**. O
par que deu 5,7 teve `extra` indo de 1 para 5; o que deu 0,0 teve `extra` em 1
nas duas. Quando a invenção é baixa e estável as execuções concordam; quando
ela oscila, a métrica oscila junto, e o denominador de união amplifica.

Isso refina o modelo da TEC-253 sem contradizê-lo: `extra` continua sendo a
parcela volátil, e agora sabemos que ela é a **causa** da dispersão, não só um
sintoma correlacionado.

#### As duas observações sem dono eram ruído

`compra-13[0]` (`sao roque` × `sao roque e arredores`) não voltou. `urgencia`
não aparece em discrepância nenhuma desta execução. Era exatamente para isso
que o segundo ponto servia, e nenhuma das duas vira card.

#### Uma ressalva à TEC-254 que só o segundo ponto revelou

`aluguel-07: tipo_imovel (faltou)` aparece no estado final desta execução. É o
turno que a TEC-254 anotou como `APARTAMENTO` decidindo que "o modelo acertou"
— e **desta vez ele não extraiu**.

A decisão continua defensável: a régua diz o que é **correto**, não o que o
modelo faz de forma confiável, e "kitnet está no vocabulário" não deixa de ser
verdade porque o modelo às vezes não o usa. Mas a frase *"o modelo acertou"*
descrevia execuções em que ele acertou, e ele o faz de forma variável. Fica
registrado.

#### O primeiro número de aderência ao tom, e o que ele ainda não diz

**121/147 — 82,3%**, AMARELO contra o piso-andaime de 50%. Decomposto:

- **2 violações de comprimento** — 602 e 625 caracteres. Estouram por pouco.
- **26 violações de "uma pergunta"** — e **24 delas com exatamente duas**.

**Não dá para interpretar os 26 ainda**, e a culpa é do que a TEC-140 entregou:
`ViolacaoDeFormato` carregava o endereço e a contagem, e **não o texto**. Sem
ele não se separa duas perguntas de verdade de erro do proxy de `?` — e
descobrir exigiria outra execução paga.

É a mesma lição que `Discrepancia` já encodava ao guardar `esperado` e `obtido`
crus: *"endereço sozinho não diagnostica"*. O texto agora viaja junto, e a
próxima execução responde sem custo novo. Não há dado de lead real nisso: o
corpus é fictício e o texto é a fala do **agente**.

**A decisão de como aplicar continua esperando**, e agora por um motivo mais
específico: se os 26 forem majoritariamente proxy, a aderência real está perto
de 98% e não há o que aplicar.

### A terceira execução de 31/08 — o texto responde, e a resposta não era a esperada

Primeira execução com o texto da resposta no relatório. Preservada em
`evals/relatorios/2026-08-31-tom-com-o-texto.md`.

| | 11:46 | 13:19 | 15:0x |
| --- | --- | --- | --- |
| acurácia de intenção | 143/147 | 144/147 | 145/147 |
| **extração (união)** | 89/98 — 90,8% | 89/98 — 90,8% | 90/99 — **90,9%** |
| `extra` | 1 | 1 | 2 |
| **aderência ao tom** | — | 121/147 — 82,3% | 118/147 — **80,3%** |
| violações de comprimento | — | 2 | 1 |
| violações de perguntas | — | 26 | **28** |

#### A hipótese estava errada, e o texto provou

A suposição era que boa parte das violações de "uma pergunta" fosse erro do
proxy de `?`. **Não é.** Lendo os textos, a maioria é de duas perguntas de
qualificação genuínas, quase sempre no mesmo formato:

> `compra-14[0]`: *"Você tem alguma região ou bairro de preferência? **E**
> precisa de vaga de garagem?"*
>
> `aluguel-08[0]`: *"em qual região ou bairro você gostaria de alugar? **E**
> você tem uma ideia de faixa de valor de aluguel...?"*

Umas três são artefato — abertura fática (*"Como posso te ajudar hoje?"*) ou
uma pergunta só partida em duas frases — mas não explicam as 28.

#### O achado real: o bloco de perguntas não existe

**Todas as 28 violações são exatamente 2 perguntas. Zero turnos com 3 ou
mais**, em 147 turnos.

Isso vale para esta execução, e **não** para as duas. A das 13:19 tem um turno
com três perguntas — `follow-up-07[0]`. Um em 294 turnos medidos, o que
continua muito longe do bloco de cinco, mas a diferença importa: a régua não
fica cega ao subir o limiar, porque esse turno segue sendo pego.

A regra vem de RN-04.2 e a justificativa escrita na card é *"nunca um bloco com
cinco perguntas"* e *"não responder a um questionário"*. **O cenário que a
regra teme não está acontecendo.** O que acontece é um padrão estável de duas
perguntas em ~19% dos turnos.

Isto tem a mesma forma das disputas da TEC-254: a régua literal sinaliza um
comportamento que o propósito dela talvez não condene. **A decisão é de
produto** — subir o limiar para 2 contraria RN-04.2 como escrito, e mantê-lo em
1 exige atacar um comportamento que pode ser aceitável.

#### A decisão (TEC-255): o limiar sobe para 2

O motivo, e ele não é "o agente está passando na prova": uma régua que marca
19% dos turnos como violação de um comportamento que ninguém pretende
consertar vira régua ignorada, e régua ignorada é pior que régua nenhuma. As
outras duas saídas foram recusadas com o custo na mão — corrigir o agente por
prompt não cabe (a margem sobre o teto é de 13,0 tokens depois da TEC-257), por
regeneração custa chamada paga por violação em produção, e por truncagem corta
frase no meio; conviver deixaria a métrica reportando ~80% para sempre sem
ninguém saber se é bom.

**Isto contraria RN-04.2 como está escrito.** A emenda foi feita: o SRS v1.0
está versionado em [`docs/srs/`](docs/srs/srs-agente-sdr-imobiliario-v1.0.md) e a
emenda E-01 altera RN-04.2 e RN-05.4.

Até 01/09/2026 este documento e o `metricas.py` citavam **RN-04.7** para a regra
de uma pergunta por turno. Estava errado, e o erro só apareceu quando o SRS
entrou no repositório: RN-04.7 é o indicador de digitação acima de 4 s. A regra
das perguntas é a RN-04.2 — a mesma sentença do teto de 600 caracteres, que o
código já citava certo — e reaparece em RN-05.4.

Recalculadas sob o limiar 2, as duas execuções de 31/08 dão:

|  | 13:19 | 15:0x |
| --- | --- | --- |
| sob MAX=1 (como reportado) | 121/147 — 82,3% | 118/147 — 80,3% |
| sob MAX=2 (recalculado) | **144/147 — 98,0%** | **146/147 — 99,3%** |
| quem continua violando | `compra-10[1]`, `compra-10[2]`, `follow-up-07[0]` | `aluguel-07[2]` |

Não é estimativa: o limiar só muda a classificação, os textos são os mesmos, e
os relatórios trazem cada violação com o valor medido.

**O piso deixa de ser andaime.** O andaime de 50% existia porque o texto do
agente nunca tinha sido medido, e o próprio comentário dizia que trocá-lo era
trabalho da próxima card, com o número na mão. O piso passa a ser **90%**, oito
pontos abaixo do pior ponto observado — a escolha conservadora, porque dois
pontos de medição são pouco para um piso apertado. Como `aderencia_ao_tom`
usava o `ALVO_PCT` global de 90, alvo e piso ficariam iguais e a faixa AMARELA
sumiria: a métrica ganha **alvo próprio de 98%**. VERDE ≥98, AMARELO 90–98 (não
bloqueia), VERMELHO <90.

**O corte de comparação.** Execuções anteriores a esta card reportam sob MAX=1
e não são comparáveis linha a linha com as posteriores. Qualquer execução
antiga cujo relatório liste as violações com o valor medido pode ser convertida
por recálculo, como as duas acima.

#### Um achado lateral que é dano mais claro

**O agente repete as mesmas duas perguntas em turnos consecutivos.**
`compra-14` pergunta *"região? E vaga?"* nos turnos 0, 1 **e** 2 — o lead não
respondeu e o agente reinsiste, com a mesma formulação.

Isso é pior que perguntar duas de uma vez, e é outro problema. O relatório já
tem um proxy de reperguntas para o caso vizinho (perguntar o que o estado já
sabe); este é perguntar de novo o que ainda não foi respondido.

#### A hipótese da dispersão se sustenta no terceiro ponto

Extração deu **90,8 / 90,8 / 90,9** nas três execuções, com `extra` em
**1 / 1 / 2**. Invenção baixa e estável, métrica parada — como a leitura de que
a dispersão segue a invenção previa. `DISPERSAO_MEDIDA` continua em 5,7 pelo
mesmo motivo de antes: ele diz o que o gate não resolve no pior caso observado.

#### Lacunas conhecidas

- **A decisão do limiar de perguntas está aberta**, e é de produto.
- **A repetição de perguntas não tem card nem medição.** O proxy atual mede
  outra coisa.
- **Três pontos ainda não são distribuição**, mesmo os três concordando.

### A quarta execução de 31/08 — a insistência é sistemática, e a amostra menor enganava

Primeira medição de insistência sobre os 147 turnos. Preservada em
`evals/relatorios/2026-08-31-insistencia-medida.md`.

**18 conversas de 42 — 43% — têm ao menos um campo perguntado mais de uma vez
sem o lead ter respondido.** Em **14 delas** o campo foi perguntado em **três
turnos**.

A contagem manual sobre a execução anterior tinha achado **cinco**. A diferença
não é ruído: aquela contagem só via os 28 turnos que violaram formato, porque
eram os únicos cujo texto o relatório carregava. Um turno com **uma** pergunta
só não viola formato, e repete igual. **A amostra disponível subestimava o
fenômeno em 3,6 vezes** — e isso é um aviso sobre medir pelo que está à mão.

#### O pior caso é um vendedor

`follow-up-06` é `VENDER_IMOVEL` nos três turnos: o lead quer anunciar o
apartamento dele e pergunta sobre comissão e preço. O agente pergunta
**quartos, região, tipo de imóvel e vagas — três vezes cada**.

Isso não é insistência, é o roteiro de qualificação de comprador rodando em
quem quer vender — território da TEC-137, que encaminha venda direto ao
handoff. **É um caso só entre os 16**, então não é padrão; é o pior exemplo, e
aponta para outro problema.

Os outros quinze são compradores, locatários e investidores legítimos sendo
perguntados de novo.

#### O instrumento, conferido contra a contagem manual

Três das cinco conversas contadas à mão aparecem: `compra-14`, `compra-02` e
`compra-13`. **`investimento-01` e `investimento-03` não aparecem**, e há duas
explicações possíveis que os artefatos não separam: o filtro `- conhecidos_antes`
pode estar corretamente jogando aqueles casos para o proxy de reperguntas (campo
que o lead **já** respondeu), ou o modelo simplesmente não repetiu a pergunta
nesta execução. Fica registrado sem escolher.

#### A quarta medição de extração, e a hipótese continua de pé

| | 11:46 | 13:19 | 15:0x | 16:xx |
| --- | --- | --- | --- | --- |
| extração (união) | 90,8% | 90,8% | 90,9% | **91,8%** |
| `extra` | 1 | 1 | 2 | 1 |
| `faltou` | 7 | 8 | 7 | 7 |
| aderência ao tom | — | 82,3% | 80,3% | **83,7%** |

Quatro execuções na mesma régua dispersam **1,0 ponto** na união, com a invenção
entre 1 e 2. `DISPERSAO_MEDIDA` continua em 5,7 pelo mesmo motivo: ele diz o que
o gate não resolve no **pior** caso observado, e o par que o produziu teve
invenção indo de 1 a 5.

#### O que isso decide

A TEC-256 dizia: *"se for raro, é registro e não conserto; se for sistemático,
as saídas são regra no prompt (não cabe) ou marcar no estado o que já foi
perguntado e não respondido"*.

**43% é sistemático.** A decisão de tratar deixou de depender de medição e passa
a depender de escolha — e a única saída que cabe no orçamento é a segunda, que é
mudança de produção.

## TEC-256 — Reinsistir na pergunta que o lead ignorou

A execução de 31/08 que trouxe o texto das respostas mostrou um padrão que
ninguém tinha visto: `compra-14` pergunta *"região ou bairro? E vaga de
garagem?"* nos turnos **0, 1 e 2**, com a mesma formulação. O lead responde
outra coisa a cada turno e recebe a mesma pergunta três vezes.

### A lacuna era precisa

`SISTEMA_DO_AGENTE` já diz *"não repergunte o que já está preenchido"*, e o
relatório já tinha um proxy que mede isso. **Os dois cobrem "não pergunte o que
você já sabe".** Nenhum cobria *"não repita o que o lead ignorou"* — e é aí que
`compra-14` cai: `regiao` e `vagas` **não** estão no estado, porque o lead nunca
respondeu. Pela regra anterior o agente estava correto.

### O critério é por campo, e os dados escolheram

Comparar o texto das perguntas pegaria só repetição literal. Em `compra-14` o
turno 0 pergunta *"Você tem alguma região ou bairro de preferência?"* e o turno
1 pergunta *"para eu montar boas opções [...] você tem alguma região ou bairro
de preferência?"*: **mesma pergunta, textos diferentes**.

Por isso a detecção é por marcador de campo, reusando a tabela do proxy antigo.
O preço está escrito: dois campos numa frase contam como duas perguntas, e uma
reformulação que troque a palavra-chave escapa.

### Uma tabela, dois proxies opostos

`MARCADORES_DE_REPERGUNTA` saiu do runner e foi para `metricas.py`, com
`campos_perguntados` como detecção única. `_reperguntou` passou a delegar.

Os dois agora fazem **perguntas opostas sobre a mesma detecção**: um mede
perguntar o que o estado **já sabe**, o outro perguntar de novo o que o lead
**não respondeu**. Duas cópias da tabela divergiriam, e a divergência só
apareceria na borda — o defeito que `campos_a_gravar` e `_subcontagem` já
custaram a este projeto. Um teste amarra os dois.

### Entra como diagnóstico, sem faixa

**Reinsistir não é errado em si.** Se o lead ignorou, perguntar de novo é
razoável. O que incomoda é a cadência e a formulação idêntica — e ninguém
decidiu ainda se isso é defeito. Medir primeiro, como na TEC-140 (parte 1) e
pelo mesmo motivo.

### Lacunas conhecidas

- **Nada foi medido ainda em execução real.** Os cinco casos conhecidos vêm de
  contar sobre os 28 turnos que violaram formato, que são os únicos cujo texto
  o relatório carregava. O número sobre os 147 sai na próxima execução paga.
- **A decisão de tratar ou conviver depende desse número**, e as saídas
  conhecidas são regra no prompt (não cabe) ou marcar no estado o que já foi
  perguntado sem resposta, que é mudança de produção.
- **Testes puros pagam banco.** Os dez testes acrescentados aqui não precisam
  de Postgres e mesmo assim herdam as fixtures autouse de `tests/conftest.py`.
  É desenho pré-existente e declarado, mas cada teste puro novo o torna um
  pouco mais caro.

## TEC-140 (parte 1) — A aderência ao tom deixou de ser um slot vazio

O relatório do gate declarava, em toda execução paga:

```
- aderencia ao tom: SEM_MECANISMO -- sem mecanismo: TEC-140 nao existe
```

Agora ela mede. **Sem nenhuma chamada paga adicional**: o texto que o agente
devolve já era gerado em toda execução e **descartado** — `resposta.resposta`
alimentava o proxy de reperguntas e o histórico, e mais nada.

### A card foi decomposta, e esta é a primeira parte

A TEC-140 tem quatro peças em subsistemas diferentes:

| peça | onde vive | estado |
| --- | --- | --- |
| formato do texto (600 caracteres, uma pergunta, emoji) | resposta do modelo | **esta parte** |
| a métrica que o mede no gate | `metricas.py`, `relatorio.py` | **esta parte** |
| teto de 2 mensagens consecutivas | estado de conversa + guarda do outbound | card própria |
| indicador de digitação acima de 4s | `OutboundPort` + API da Meta | card própria |

As duas últimas mudam comportamento de produção, e a do indicador muda a
interface que três implementações de `OutboundPort` seguem.

### Medir antes de aplicar, e a razão é a sessão inteira

A card diz "**aplicar**" o formato. Esta parte **não aplica nada** — nem no
prompt, nem em produção.

O motivo: **não existia um único dado sobre conformidade**. Pode ser que o
modelo já cumpra as três regras quase sempre, e aí "aplicar" é um problema
muito menor do que a card supõe. As três formas de aplicar têm custos muito
diferentes — regra no prompt não cabe (a margem é de 4,2 tokens), validação com
regeneração custa uma chamada paga por violação em produção, e truncar corta
frase no meio — e escolher entre elas sem número é o erro que a TEC-240 e a
TEC-250 cometeram gastando orçamento de prompt.

### Duas regras são decidíveis, a terceira não é

- **600 caracteres** — `len(resposta) <= 600`. Exato, sem proxy.
- **Uma pergunta por turno** — contagem de `?`. **É proxy**, da mesma classe
  que `_reperguntou`: *"cabe em R$ 500?"* conta pergunta que não pergunta nada
  ao lead, e *"me diz qual região você prefere"* escapa por não ter `?`.
- **Emoji** — *"a informação essencial nunca depende de emoji"* exige entender
  o que a frase afirma: se a figurinha substitui uma palavra ou só decora.
  **Nenhuma contagem responde isso**, então ela não vira critério. O relatório
  conta emoji como diagnóstico, com a limitação escrita ao lado do número.

Reportar um número que não mede a regra seria pior que não reportar — é o
mesmo raciocínio de `sem_mecanismo`.

**A métrica é por resposta, não por violação.** O lead vive o turno: um turno
que estoura o tamanho **e** faz três perguntas é um turno ruim, não dois.

### O piso nasceu andaime, e a TEC-255 o trocou pelo medido

Ele nasceu como `PISO_ANDAIME_DE_ADERENCIA_AO_TOM_PCT = 50`, porque ninguém
sabia qual aderência era saudável: o texto nunca tinha sido medido. Cravar 84
ali seria piso não medido, e um piso não medido **abre VERMELHO na primeira
execução sem regressão nenhuma** — o que a docstring de `sem_mecanismo` avisa, e
o que a `acuracia_efetiva` viveu até a TEC-210 medir (ela teve andaime de 50%
pelo mesmo motivo). Um teste travava o valor para que a troca fosse deliberada.

A troca aconteceu na TEC-255, com o número na mão: `PISO_DE_ADERENCIA_AO_TOM_PCT
= 90` e `ALVO_DE_ADERENCIA_AO_TOM_PCT = 98`. O raciocínio e os números estão na
decisão do limiar, acima. O teste que travava o andaime continua existindo, e
agora trava o piso medido e o alvo próprio.

### Lacunas conhecidas

- **A regra do emoji continua sem mecanismo**, e isso é limite do problema e
  não da implementação.
- ~~A emenda ao SRS está pendente.~~ Feita na emenda E-01 de
  [`docs/srs/`](docs/srs/srs-agente-sdr-imobiliario-v1.0.md), sobre RN-04.2 e
  RN-05.4.
- **O piso de 90% se apoia em dois pontos de medição**, os dois recalculados
  sobre execuções feitas sob o limiar antigo. A primeira execução paga sob o
  limiar novo é que confirma a faixa.

## Escolher o modelo no disparo manual do gate

`workflow_dispatch` passou a aceitar um input `modelo`. Vazio — que é o caso de
todo `pull_request` — usa o default de `config.py`; preenchido, exporta
`MODELO_AGENTE` só para aquela execução.

Isso fecha **metade** da lacuna registrada acima: dá para comparar modelos pela
UI do Actions, sem commit e sem tocar em `config.py`, e o
`_condicoes_da_execucao` já grava o modelo no topo do artefato — cada execução
fica auto-identificada.

**A outra metade continua aberta.** Um PR que troque o *default* em
`config.py` continua passando sem medir, porque o arquivo está fora do filtro
de propósito: ele carrega config alheia ao agente, e incluí-lo faria o gate
pago rodar por motivos que não têm nada a ver com o prompt. Hoje o que segura
essa ponta é `test_defaults_do_agente`.

### O nome intermediário não é estilo

`inputs.modelo` é string vazia tanto no `pull_request` quanto no dispatch sem
escolha. Exportar `MODELO_AGENTE=""` faria o pydantic aceitar vazio e a
primeira chamada falhar com modelo inválido — o passo lê `MODELO_ESCOLHIDO` e
só promove a `MODELO_AGENTE` quando tem conteúdo.

### A guarda que roda antes de gastar

Um modelo com typo falharia sozinho na primeira chamada, e isso seria barato.
**O caso caro é o modelo válido sem preço cadastrado**: ele roda as 146
chamadas e produz um relatório com `custo_usd=None` — exatamente o buraco que
a TEC-249 fechou na moderação, entrando de novo pela porta do disparo manual.

O passo `Conferir o modelo escolhido` reusa `PRECOS_POR_MODELO` e
`MINIMO_CACHEAVEL_POR_MODELO` em vez de repetir valores, e distingue os dois
casos:

- **sem preço → falha**, antes de qualquer chamada paga;
- **prefixo abaixo do mínimo de cache → avisa e segue.** Prefixo curto demais
  não cacheia e não dá erro; a execução fica mais cara, mas continua válida, e
  reprovar por isso seria confundir custo com medição. Com `claude-haiku-4-5`
  (mínimo 4.096 contra prefixo de 2.351) é exatamente esse o caso.

### O relatório de uma execução em CI deixou de ser efêmero

A lacuna que o próprio README registrava — *"o relatório de uma execução em CI
continua efêmero: não há `upload-artifact` em `evals.yml`"* — mordeu em 30/08.
A execução que abriu **VERMELHO** no CI perdeu o relatório, e o diagnóstico só
saiu porque o log tinha cabido ali. Foi sorte, não desenho.

O `evals.yml` passou a subir o relatório como artefato de workflow, e duas
decisões carregam o peso disso:

**`always()` é o ponto inteiro do passo, não robustez de rotina.** A execução
vermelha é a que mais precisa ser lida turno a turno, e é exatamente a que faz
o passo anterior falhar. Sem `always()`, o artefato só existiria nas execuções
que passaram — ou seja, só quando ninguém precisa dele. O runner já gravava
antes das asserções (`preservar`) justamente por isso; faltava o CI subir.

**`RELATORIO_DE_EVAL` aponta para fora da árvore.** O default é
`evals/relatorios/<data>.md`, e ali moram os relatórios **commitados** — um
glob subiria os quatro históricos junto com o novo. Em `runner.temp` só existe
o desta execução.

A condição repete `mexeu` porque `always()` sozinho roda até quando o eval foi
pulado, e aí não há arquivo nenhum. `if-no-files-found: warn` fecha o resto:
não ter relatório é anormal e merece aviso, mas não é motivo para reprovar um
job que já falhou por outro motivo — ou que passou.

`Log do resultado` também ganhou `always()`: sem isso ele era pulado justamente
nas execuções que falharam, e é ele que aponta onde o artefato está.

#### O que isto não resolve

O artefato vive **90 dias** e some. Ele serve para investigar uma execução
recente, não como série histórica — para isso continua valendo o relatório
commitado, que é o que a TEC-247 estabeleceu e o que sustenta a comparação
entre execuções neste README.

### O resumo também trocou para sonnet-5, e essa troca não foi medida

`modelo_resumo` passou de `claude-opus-5` para `claude-sonnet-5` junto com o
agente.

**Foi mudança manual, feita direto na `main`, sem card e sem PR** — commit
`3a711a5`, cuja mensagem diz `readME.md` mas cujo diff é só `config.py`. Fica
registrado aqui porque o histórico do git não conta essa história: quem
procurar depois por que o resumo trocou de modelo não acha nada no `git log`,
e esta é justamente a troca de modelo que **não tem gate** para explicá-la
retroativamente.

A mudança em si é decisão legítima de quem toca o projeto. O que não sobrevive
sozinho é o *registro* dela.

**A diferença entre as duas trocas é o instrumento, e ela importa.**

| | `modelo_agente` | `modelo_resumo` |
| --- | --- | --- |
| tem gate | sim | **não** |
| medido depois da troca | ver a ressalva abaixo | **não é mensurável hoje** |

Nada em `evals/` toca `modelo_resumo`. A única guarda que ele tem é
`test_todo_modelo_configurado_tem_preco_cadastrado`, que confere **preço**, não
qualidade — foi ela que a TEC-249 criou, e ela pega custo nulo, não regressão.

O argumento *"sonnet-5 aguentou"* vale para a **acurácia de intenção**, medida
antes e depois. **Ele não transfere para a qualidade do resumo** — se ela
regrediu, nada neste projeto acusaria.

> **Ressalva da TEC-253.** Ele também **não se sustenta para a extração**, e a
> linha da tabela acima foi esvaziada por isso. A comparação opus-5 (12:02)
> contra sonnet-5 (14:44) atravessa a TEC-248, que mudou a régua: os 8
> `divergiu` do opus eram 7 de `regiao` e um de `urgencia`, e viraram acerto
> quando `normalizar_regiao` entrou. `acertos` foi de 80 para 88 e `faltou`
> ficou em 8 nos dois lados — **o ganho inteiro é da régua, não do modelo**. A
> troca pode ter sido boa; a extração não a mediu. Ver a seção TEC-253.

Medir exigiria corpus e critério próprios, que não existem — e a TEC-140, que
seria o lugar disso, também não. É a mesma lacuna que `aderencia ao tom` já
declara como `SEM_MECANISMO` no relatório do gate, agora com um segundo dono.

Os dois campos continuam separados de propósito, e rodarem no mesmo modelo hoje
não muda isso: **é a possibilidade de divergir que a separação guarda, não o
fato de divergirem agora.**

### As colunas de cache do banco, que ficaram NULL desde a TEC-126

A TEC-251 ligou o prompt caching e pôs os contadores no **log**. Isso não
alcança consulta nenhuma: `message_telemetry.cache_read_tokens` e
`cache_write_tokens` existem desde a TEC-126, `record_agent_message` sempre as
aceitou como parâmetro, e **nenhum chamador passava valor**. Continuavam
sempre `NULL`.

Era critério de aceite da [TEC-231](https://eduardodurieuxlopes.atlassian.net/browse/TEC-231),
que já existia aberta quando a TEC-251 foi escrita — e a TEC-251 é, em boa
parte, duplicata dela e da
[TEC-220](https://eduardodurieuxlopes.atlassian.net/browse/TEC-220). O backlog
não foi consultado antes de criar a card nova; fica registrado porque o erro é
de processo e se repete sozinho.

**A consequência era concreta:** o painel de custo da TEC-191 somaria custo sem
a parte de cache — o mesmo padrão da TEC-249, gasto que existe e não chega a
lugar consultável.

`RespostaDoAgente` e `PerguntaDeDesambiguacao` passaram a carregar
`cache_write`/`cache_read`, o turno os repassa, e o recorder os grava.

#### O custo gravado também subestimava

`record_agent_message` calculava `cost_usd` com `tokens_in` e `tokens_out` só.
Como os tokens cacheados **saem** de `input_tokens`, o custo no banco cairia
sem o gasto ter caído — o mesmo defeito que a TEC-251 consertou no log,
sobrevivendo no caminho que o painel de fato lê.

Havia um teste travando exatamente esse comportamento,
`test_custo_ignora_tokens_de_cache_por_ora`, com justificativa honesta enquanto
valeu: *"sem agente não há forma de uso real para tarifar, e inventar taxa
agora seria chute materializado no histórico de custo"*. O agente existe, o
cache está ligado, e a taxa deixou de ser chute — 1,25× na escrita e 0,1× na
leitura. O teste foi substituído por dois: um que cobra a conta com cache, e um
que garante que `None` nas colunas continua gravando o custo de antes.

#### Zero e `None` significam coisas diferentes nessas colunas

`cache_write=0` é *"o modelo respondeu, o prefixo foi enviado, e o cache poupou
nada"* — uma quantidade. `NULL` é *"esta linha é anterior à TEC-231 e ninguém
media"* — uma ausência. As duas leituras não podem colidir na mesma coluna, e
por isso os campos de telemetria usam `0` e as colunas continuam aceitando
`None` para o histórico.
## TEC-182 — Opt-out: o lead pede para sair, e o silêncio é imediato

Antes desta card, procurar por `opt.out` ou `descadastr` no código inteiro
devolvia zero. Um lead que escrevia *"não quero mais receber mensagens"*
recebia uma resposta de qualificação. Era evidência de LGPD inexistente
(RNF-19), era a defesa contra denúncia na Meta que o Anexo B do SRS manda nunca
cortar, e bloqueava a
[TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) — ligar
cadência automática sem chave de desligamento é o caminho mais curto para o
bloqueio do número.

O desenho inteiro está em
`docs/superpowers/specs/2026-09-01-tec-182-opt-out-design.md`, com as decisões
e os erros que a revisão da branch encontrou marcados no próprio documento.

### Duas faixas de detecção, e o que fecha a colisão

A detecção é determinística e sem chamada paga: uma decisão de LGPD não pode
depender de um provedor estar de pé. São duas faixas em
`src/mobia/domain/optout/deteccao.py`.

**Termos inequívocos** casam em qualquer posição da mensagem, e o que os torna
seguros **não** é a raridade da frase — é o **objeto de mensageria** que cada
um carrega. `pare de me mandar mensagens` não colide com *"pare de mandar
apartamento sem vaga"*; `nao quero mais receber mensagens` não colide com *"nao
quero mais receber apartamento sem vaga"*. A primeira versão da lista tinha os
termos **truncados** (`pare de mandar`, `nao quero mais receber`) e silenciava
lead comprador para sempre, em silêncio, com o lead vendo só a ausência de
resposta.

**Termos ambíguos** (`sair`, `parar`, `stop`, `cancelar`, `me tire da lista`,
`nao quero mais`) só disparam quando são a **mensagem inteira** normalizada —
minúsculas, sem acento, sem pontuação, espaços colapsados. É o padrão real de
quem quer sair, e a estreiteza é o que protege *"podemos parar por aqui hoje?"*
e *"quero sair do aluguel e comprar"*.

A assimetria é o **inverso** da TEC-257: lá marcar de mais era o erro
perigoso; aqui deixar de detectar é violação de LGPD e detectar demais é
prejuízo comercial. Por isso a faixa inequívoca é generosa e só a ambígua é
estrita.

### A guarda mora na porta de saída, e a checagem do turno é só economia

A checagem de opt-out roda em `GuardedOutbound.send`, **antes** da reserva em
`outbound_dispatches` — barrar depois deixaria linha órfã e o sweeper leria
isso como tentativa feita. É lá, e não em `executar_turno`, porque o turno
protege o caminho de hoje e nada mais.

A checagem no topo do turno continua existindo, e é **economia**, não correção:
sem ela, um lead silenciado pagaria a classificação inteira para o envio ser
barrado no fim. A duplicação é deliberada e assimétrica — esquecer a do turno
custa dinheiro, esquecer a da porta manda mensagem para quem pediu para parar.

O único envio que atravessa a guarda é a confirmação do próprio pedido, por um
`kind` dedicado (`optout_confirmacao`). A exceção é nomeada, não um furo.

### Registro append-only, porque reativação não apaga evidência

`optout_events` tem uma linha por evento, e o estado atual de um lead é o
**último** evento por `(channel, conversation_key)`. Com coluna booleana, a
reativação **apagaria** a prova do opt-out — exatamente o que a RN-14.2 exige
que não aconteça.

`created_at` é carimbado pelo Postgres (`server_default=func.now()`), como nas
demais tabelas do repositório que já usam o mesmo padrão. Aqui isso pesa mais do que nelas: a
consulta de estado é `ORDER BY created_at DESC LIMIT 1` **sem desempate**, então
a ordem *é* o estado — com o relógio do cliente escrevendo a coluna, um skew
entre o worker que grava o opt-out e a máquina que roda o script de reativação
inverteria os dois eventos e devolveria "não está em opt-out" para quem pediu
para sair.

O evento referencia `message_id` e **não copia** o texto: o corpo já está
cifrado em `messages`, e copiá-lo criaria uma segunda cópia em claro da fala do
lead.

### Reativação por script, com autor e motivo obrigatórios

```
python -m mobia.admin.reativar --channel wa --key <conversation_key> \
    --autor "Paulo M." --motivo "lead pediu por telefone"
```

Script e não endpoint: o projeto não tem camada de autenticação (JWT, OIDC e
papéis são a TEC-201, com zero linhas), e um endpoint sem autenticação que
reverte proteção de LGPD é pior que não ter reativação nenhuma. Quem consegue
rodar isto já tem acesso ao servidor e ao banco, e isso **é** a autenticação.
Quando o dashboard existir (TEC-189), ele chama a mesma função de domínio.

### Garantias

- Opt-out detectado é gravado **antes** de a confirmação sair. Se a entrega
  falhar de forma terminal, o lead fica em silêncio sem confirmação — ruim e
  conforme. Na ordem inversa teríamos opt-out não registrado e continuaríamos
  mandando mensagem, que é a violação.
- O registro acontece **antes** da moderação de entrada. Uma mensagem que é ao
  mesmo tempo pedido de opt-out e algo que a moderação reprova ainda é
  registrada — senão a recusa de entrada seria mandada para quem pediu para
  sair.
- Falha **retentável** na confirmação (5xx da Meta) não perde a confirmação: o
  short-circuit de silêncio no topo do turno não dispara quando a mensagem em
  mãos é ela própria um pedido de opt-out, então a retentativa reentrega. A
  idempotência vem da reserva em `outbound_dispatches`.
- O silêncio é sobre o **lead**, não sobre a mensagem ter texto: imagem e áudio
  de quem pediu opt-out também não recebem resposta.
- Um `kind` que ninguém previu (`follow_up`, o da TEC-183) é barrado por
  default. A guarda é lista negra de um `kind` só, não lista branca.

### Lacunas conhecidas

- **Um lead que já optou e digita "parar" de novo recebe a confirmação de
  novo.** É o resíduo aceito do conserto da falha retentável: o short-circuit
  de silêncio não pode barrar um pedido de opt-out em mãos, e distinguir
  "retentativa da mesma mensagem" de "mensagem nova" no topo do turno exigiria
  estado que não existe. É defensável porque a confirmação do próprio pedido já
  é a exceção nomeada, e porque o gatilho é sempre uma fala do lead pedindo
  exatamente isso. O segundo turno também grava um segundo evento `OPT_OUT` —
  inofensivo, porque a tabela é append-only e o estado é o último evento.
- **O mesmo conserto troca um `silenciado`/`info` por um `reentrega_suprimida`/
  `error` num caminho benigno.** Se o worker morrer depois de a confirmação
  ter sido entregue com sucesso e antes de marcar a linha como processada, o
  turno seguinte agora encontra a reserva viva em `outbound_dispatches` e
  devolve `reentrega_suprimida`, com log em nível `error` — antes deste
  conserto, o mesmo cenário devolvia `silenciado`, em `info`. É alarme falso,
  recém-alcançável por causa desta correção: vale a linha para quem for
  investigar o alerta não procurar defeito onde não há.
- **A guarda é fail-open para `message_id` inexistente.** Sem linha em
  `messages` atrás do id, não há `(channel, conversation_key)` a consultar, e
  recusar o envio esconderia o defeito real, que é o chamador. A consequência
  é direta: **um envio disparado com uuid sintético passa sem checagem
  nenhuma**.
- **Nada amarra `payload["para"]` ao `conversation_key` da mensagem.** A guarda
  decide pelo lead do `message_id`; o adaptador do WhatsApp entrega para
  `payload["para"]`. Um chamador que misture os dois é aprovado pela guarda e
  entrega ao endereço errado.
- **O que a TEC-183 precisa respeitar**, e nada disso é garantido pelo
  compilador: herdar `GuardedOutbound` e **nunca** implementar `OutboundPort`
  direto (é `Protocol` estrutural — uma classe com `async def send` tipa igual
  e não tem guarda); passar um `message_id` que exista em `messages` e
  pertença ao lead alvo; nunca reusar `optout_confirmacao`, que é bypass
  incondicional; manter `payload["para"]` coerente com o `conversation_key` da
  mensagem.
- **A moldura de cortesia não é detectada.** *"por favor pare"* e *"obrigado,
  pode parar"* não disparam nada: a faixa estrita compara a mensagem inteira.
  Relaxá-la é redesenho da regra e reabre o falso positivo que ela fecha.
- **`nao quero mais receber nada` deixou de disparar.** O termo estava na faixa
  inequívoca e silenciava *"nao quero mais receber nada sem vaga"*, *"...nada
  acima de 500 mil"* e *"...nada nessa regiao"* — `nada` é quantificador
  universal e aceita complemento partitivo, então não é objeto de mensageria.
  Saiu da lista; as três frases viraram teste negativo permanente.
- **A detecção é lista fixa e vai errar por falta.** *"chega"*, *"me deixa em
  paz"* não são detectados. A lista não é estendida por antecipação: cada termo
  novo é risco de falso positivo, e não há conversa real deste produto para
  dizer quais faltam.
- **A evidência se autodestrói no relógio de retenção de `messages`.** O evento
  referencia `message_id`, e a D4 do desenho afirma que *"a referência **é** o
  conteúdo original"*. Quando a RNF-22 (retenção de 12 meses de `messages`)
  existir, esse id vira ponteiro solto e a afirmação deixa de valer. A migração
  `0010` já não tem FK para `messages` para a limpeza não apagar evidência por
  cascata — mas não ter FK preserva a **linha**, não o **conteúdo**.
- **Não há métrica de opt-out.** Quantos acontecem, e se algum foi falso
  positivo, ninguém sabe. Cabe no epic de observabilidade.
- **O cenário de opt-out durante rajada é vacuamente verdadeiro.** A RN-01.6
  (debounce) não existe. Quem a implementar tem que furar a janela para o
  opt-out, e o teste nasce com ela.
