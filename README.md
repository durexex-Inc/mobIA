# mobIA

Agente de IA para qualificação de leads imobiliários.

## Ambiente local

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env
docker compose up -d
```

## Comandos

| O quê | Comando |
|---|---|
| Testes | `python -m pytest` |
| Teste de latência | `python -m pytest -m perf` |
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
- O teto comparado é o nominal **menos** `CONTEXTO_HEADROOM_DE_TOKENS`. A
  contagem mede uma mensagem plana, sem `system` e sem os rótulos e o schema que
  a requisição real carrega; a reserva cobre essa diferença. A TEC-134 mediu:
  a contagem fica ~263 tokens abaixo do que se envia (`SISTEMA` contado e não
  enviado, `SISTEMA_DO_AGENTE`, o schema de saída e os rótulos enviados e não
  contados), contra uma reserva que era 400 na época. **A partir da TEC-145 a
  reserva é 800, não 400**: o objeto `extracao` que a TEC-145 acrescentou ao
  schema de saída (`SCHEMA_DA_RESPOSTA`) soma um segundo ~263 à subcontagem.
  Na TEC-145 isso a levava a **526**; com a reserva ainda em 400 ela já
  excederia a própria reserva, e com 800 ela cabia com **74 tokens** de folga
  antes de a segunda asserção de `test_diferenca_entre_o_contado_e_o_enviado`
  (headroom × 0,75, ou seja 600) voltar a disparar — não os ~137 que a
  reserva de 400 deixava contra os ~263 de antes da TEC-145. **A TEC-240
  alongou `SISTEMA_DO_AGENTE` e a subcontagem subiu para 587**, com 13
  tokens de folga (ver a nota da TEC-240 na seção TEC-145 abaixo e
  `test_a_margem_do_orcamento_do_prompt_e_deliberada`); 526/74 ficam como o
  número da época, não o de hoje. A conta usa o mesmo proxy `len/4` do
  módulo, não uma chamada paga de `count_tokens`, e vive em
  `test_diferenca_entre_o_contado_e_o_enviado`, que quebra se alguma das
  parcelas crescer — o único dos lugares onde ela está escrita que não pode
  mentir, porque roda. Ver a seção TEC-145 abaixo e o comentário de
  `contexto_headroom_de_tokens` em `src/mobia/app/config.py`.
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
deploy neste repositório para um teste ler. O `docker-compose.yml` sobe apenas
Postgres e Redis para desenvolvimento local, e o worker roda por `python -m
arq`. Quando o deploy existir, este é o número que tem de subir junto.

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
- **O filtro interno de `evals.yml` tem um buraco.** `montagem.py` mora em
  `src/mobia/domain/context/`, que não casa com o regex
  `^(src/mobia/domain/agente/|src/mobia/evals/|evals/)` do passo "Decidir se
  o prompt mudou". Uma mudança ali altera o que o modelo vê — o contexto que
  ele recebe — sem tocar em nenhum prompt de agente, e passa livre sem rodar
  o eval. Cobrir isso exigiria rodar o gate em todo PR, com o custo e o
  flake que a decisão do limiar amarelo rejeitou.
- **`src/mobia/app/config.py` também está fora do filtro, e esse buraco é
  maior.** É lá que mora `modelo_agente` (`"claude-opus-5"`), e trocar o modelo
  muda mais do que um ajuste de prompt muda: um PR de uma linha pode substituir
  o modelo medido e ser mergeado sem o gate rodar uma vez. **Não** foi incluído
  no filtro de propósito, e o motivo está comentado no próprio `evals.yml`:
  `config.py` é o arquivo de configuração inteiro e muda por muitos motivos
  alheios ao agente, então incluí-lo faria o gate pago rodar à toa em PRs que
  não têm nada a ver com o modelo. A cobertura de verdade seria mover
  `modelo_agente` para um arquivo que só o agente use — não existe ainda. Se um
  dia o gate não rodar quando deveria, este e o `montagem.py` são os dois
  lugares a olhar primeiro.
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
(`SISTEMA_DA_ENTRADA`, `SISTEMA_DA_SAIDA`) e exige de volta exatamente uma
palavra — `BLOQUEAR` ou `LIBERAR` — sem pontuação nem explicação, com
`MAX_TOKENS_DO_VEREDITO = 8`: curto o bastante para que um truncamento vire
um erro tipado em vez de um veredito pela metade — "BLOQ" não é resposta.
Qualquer coisa fora do protocolo (resposta truncada, palavra diferente,
exceção do SDK, `stop_reason` que não é `end_turn`) vira
`ModeracaoIndisponivel`; o adaptador nunca interpreta o desconhecido como
liberado, porque isso transformaria um moderador confuso em um moderador
desligado, e desligado em silêncio.

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
  (`infra/anthropic.py`) tem 60s por tentativa com uma retentativa — 120s de
  pior caso por chamada — contra um `job_timeout` de 240s que o turno **já**
  estoura sozinho: `resumir` + `classificar` + `desambiguar` somam 360s no
  pior caso (comentário de `job_timeout` em `workers/main.py`, e a seção
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
  pede uma palavra sem pontuação, mas `BLOQUEAR.` ou `**LIBERAR**` não podem
  custar um turno: comparados por igualdade eles virariam
  `ModeracaoIndisponivel`, e na saída isso propaga até a linha ficar em
  `FAILED` para sempre, sem o lead receber nada. `_UMA_PALAVRA`
  (`infra/moderacao.py`) exige que a resposta inteira seja **uma** corrida de
  letras cercada só de não-letras; ela não procura a palavra dentro de uma
  frase, então `BLOQUEAR LIBERAR`, `não vou BLOQUEAR` e `talvez` continuam
  sendo indisponibilidade. A garantia que sustenta o subsistema — o
  desconhecido nunca vira liberado — fica intacta, e há teste para cada
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
  reclamando. Esse arquivo de teste tem 11 testes ao todo (dois
  parametrizados sobre os 4 arquivos do corpus, mais três testes únicos:
  os dois lados existem nas duas direções, o controle de entrada cobre o
  falso positivo caro, e os ids são únicos entre todos os arquivos).
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
  truncamento de `montar_contexto` reconta a cada corte, então não há um
  "número de chamadas" fechado que a inclua. `resumir` + `classificar` +
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
  déficit que a TEC-134 já tinha medido para o resto da requisição. A
  subcontagem total sobe para 526; com a reserva em 400 ela nem passaria mais
  na primeira asserção de `test_diferenca_entre_o_contado_e_o_enviado`
  (`subcontagem < headroom`, e 526 não é menor que 400). Com a reserva em 800
  ela passa nas duas, com 74 tokens de folga antes da segunda (headroom ×
  0,75 = 600) voltar a disparar. Preço: 400 tokens a
  menos de literais e resumo por turno, de um teto de 12000 — 3,3% do
  contexto, em troca de extração estruturada. Ver o item "O teto comparado é
  o nominal menos `CONTEXTO_HEADROOM_DE_TOKENS`" na seção TEC-127 acima, que
  tinha ficado com os números de antes desta mudança.
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
  TEC-158 faz sobre ela e no orçamento de contexto do prompt — hoje em 587
  de um teto de 600 (ver nota da TEC-240 acima). **É escolha, registrada
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

> **Nota da TEC-240 (29/08/2026):** até aqui o prompt classificava intenção e
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
> - **A reserva não subiu.** `CONTEXTO_HEADROOM_DE_TOKENS` continua em 800.
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

830 não serviu, e o meio token importou: 830 × 0,75 = 622,5 contra subcontagem
de 622,8. Empatar com o teto derrotaria o fator 0,75, que existe para haver
folga.

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
  aparecia nas execuções anteriores. Não foi diagnosticada.
- **Duas execuções não são distribuição.** O ruído de 1,7 ponto vem de dois
  pontos sobre o mesmo sistema, e é a única dispersão medida que este projeto
  tem.

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
  (mínimo 4.096 contra prefixo de 1.716) é exatamente esse o caso.

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
