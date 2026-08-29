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
  schema de saída (`SCHEMA_DA_RESPOSTA`) soma um segundo ~263 à subcontagem,
  que sobe para **526**. Com a reserva ainda em 400 essa subcontagem já
  excederia a própria reserva; com 800 ela cabe com **74 tokens** de folga
  antes de a segunda asserção de `test_diferenca_entre_o_contado_e_o_enviado`
  (headroom × 0,75, ou seja 600) voltar a disparar — não os ~137 que a
  reserva de 400 deixava contra os ~263 de antes da TEC-145. A conta usa o
  mesmo proxy `len/4` do módulo, não uma chamada paga de `count_tokens`, e
  vive em `test_diferenca_entre_o_contado_e_o_enviado`, que quebra se alguma
  das parcelas crescer. Ver a seção TEC-145 abaixo e o comentário de
  `contexto_headroom_de_tokens` em `src/mobia/app/config.py`, que já tinha a
  conta certa.
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
  acurácia é a TEC-210, com as 50 conversas anotadas.

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
`aluguel`, `investimento`, `follow_up`, `borda`), 50 conversas e **136
turnos** anotados à mão — o texto é escrito primeiro, o rótulo depois, e por
um humano, não pelo modelo medido: gerar o corpus com o mesmo modelo que ele
avalia embutiria as pistas que aquele modelo lê bem e infla a acurácia por
construção. A distribuição por intenção sai desigual porque a conversa real é
desigual: COMPRA 47, ALUGUEL 32, INVESTIMENTO 26, FORA_DE_ESCOPO 9, INDEFINIDA
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
  diz "o prompt regrediu". O teto de 5 não é gosto: é a folga do piso dividida
  pela conversa mais longa do corpus (5 × 3 = 15 turnos, contra 16 de folga),
  e `tests/unit/test_evals_metricas.py::test_o_teto_de_abandono_nunca_consegue_furar_o_piso_de_turnos`
  falha de graça se o corpus mudar de forma e as duas asserções passarem a
  poder reprovar a mesma execução por motivos diferentes.
- O gate compara **percentual**, não contagem absoluta — o corpus tem hoje
  136 turnos, e uma conversa a mais ou a menos muda esse total, então cravar
  contagem faria o limiar mudar de significado a cada conversa acrescentada.
  O piso de 120 turnos (`PISO_DE_TURNOS`) é o que garante que um único turno
  não valha mais de 0,8% e a faixa amarela continue absorvendo o ruído entre
  execuções — os 136 turnos reais folgam esse piso em 16.
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
- **Uma medição, não uma distribuição.** A baseline de 27/08/2026 é uma amostra
  única: 95,6% na crua, 92,6% na efetiva. Os pisos foram escolhidos em torno
  dela, e o ruído real entre execuções é estimado (±1,5%), não medido. Um gate
  relativo a histórico — bloquear por queda maior que a dispersão observada —
  exigiria guardar as execuções, e o relatório hoje vive só no log efêmero do
  CI. Enquanto isso, um vermelho perto da borda pode ser variância.
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
- **Corpus sintético não é tráfego real.** Cento e trinta e seis turnos
  escritos por quem conhece o sistema carregam o viés de quem os escreveu, e
  nenhuma anotação cuidadosa remove isso. O número que sair daqui é um piso
  de confiança, não uma medida de campo.
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
- **COMPRA é 35% dos turnos** (47 de 136): um classificador que responda
  sempre COMPRA já tira 35% de acurácia de graça. Isso não invalida o alvo —
  90% continua exigindo acerto real nas outras classes —, mas a matriz de
  confusão vai ser dominada por COMPRA e ALUGUEL, e VENDER_IMOVEL (6 turnos)
  e SUPORTE_CONTRATO (7) têm massa tão pequena que um único erro move a
  classe inteira em 14–17 pontos percentuais.
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
  acentuado nos 136 turnos:
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
válida.

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

`PISO_DE_TURNOS_ANOTADOS = 30` (`src/mobia/evals/metricas.py`) é o piso
irmão de `PISO_DE_TURNOS`, na outra direção: sem ele, anotar três turnos
fáceis daria 100% de precisão num corpus que não mede nada — o nome é
histórico, e o piso confere `turno.positivo`. Hoje **38 turnos estão
anotados como positivos**, distribuídos em `evals/corpus/compra.yaml` (17),
`evals/corpus/aluguel.yaml` (12), `evals/corpus/investimento.yaml` (5),
`evals/corpus/borda.yaml` (2) e `evals/corpus/follow_up.yaml` (2). Os três
primeiros ganharam a chave `campos` na TEC-145; os dois últimos, na TEC-239,
que precisou dos turnos de injeção e de venda para tirar quatro campos do
zero.
`aluguel-02` carrega o caso de correção que a D4 do spec pediu com risco
declarado: o lead troca de região no meio da conversa (`brooklin` →
`itaim bibi`), e é o turno que prova que a sobrescrita pelo mais novo tem
cobertura de medição.

`PISO_DE_TURNOS_NEGATIVOS = 25` (`src/mobia/evals/metricas.py`) é o piso
irmão de `PISO_DE_TURNOS_ANOTADOS` numa terceira direção: aquele responde
"sobrou amostra para medir acerto?"; este responde "sobrou amostra para
pegar invenção?" — e os dois são separados de propósito, porque um piso
único sobre "todo turno anotado" se auto-satisfaria (30 turnos negativos sem
invenção nenhuma dariam denominador zero, e `faixa_de` levantaria
`ValueError` em vez de reportar — o mesmo furo entrando por outra porta). A
TEC-238 anotou **39 turnos negativos**, distribuídos em
`evals/corpus/borda.yaml` (14), `evals/corpus/aluguel.yaml` (7),
`evals/corpus/follow_up.yaml` (7), `evals/corpus/investimento.yaml` (6) e
`evals/corpus/compra.yaml` (5) — concentrados em `borda` e `follow_up`
porque são os arquivos com mais turno de saudação, despedida e assunto fora
de escopo, onde "o lead não afirmou nada" é a leitura mais direta. O piso
vem do pior caso de abandono, no mesmo molde de
`TETO_DE_CONVERSAS_ABANDONADAS`: as cinco conversas com mais negativos somam
12, então a execução mais azarada ainda deixa 39 − 12 = 27 negativos de pé, e
o piso fica em 25, com folga de dois.

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
anotação, não a defeito do modelo. É a leitura que a TEC-238 vai precisar para
separar invenção de anotação faltante nos 100 turnos sem `campos` — e a que,
até a primeira execução paga acontecer, ninguém ainda exerceu contra dados
reais.

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
- **A precisão de extração pune os dois lados da conta nos 32 turnos
  anotados** — pela união entre campos esperados e obtidos, nem um modelo que
  inventa campos, nem um que nunca extrai nada, tira 100% de graça **nesse
  subconjunto**. Nos outros 104 turnos do corpus, `campos` ausente tira o
  turno da medição de extração por completo (é o único jeito de anotar "esta
  fala não afirma nada extraível" — `carregar` recusa `campos: {}` com
  `CorpusInvalido` e manda omitir a chave em vez de deixá-la vazia), então uma
  invenção nesses 104 turnos não é medida por ninguém. Ver "Lacunas
  conhecidas".
- **Há teste de correção de região no corpus**
  (`tests/unit/test_evals_corpus_real.py::test_ha_turno_de_correcao_anotado`),
  porque a sobrescrita "mais novo vence, sem histórico" é a decisão do spec
  com risco mais declarado (D4), e sem um caso anotado ela não tinha cobertura
  de medição nenhuma.
- **O proxy de repergunta nunca bloqueia**, e há comentário no próprio
  `MARCADORES_DE_REPERGUNTA` dizendo por quê: é heurística de palavra-chave,
  com erro nas duas direções. Ver "Lacunas conhecidas".

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
  sobre os turnos com `campos` anotado, não sobre os 138. `PISO_DE_TURNOS_ANOTADOS`
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
  gate pago com essa amostra.
- **A precisão de extração agora mede 77 dos 138 turnos — 38 positivos e 39
  negativos —, e o exploit descrito antes não funciona mais.** `campos: {}`
  é o estado novo do contrato: "o lead não afirmou nada neste turno, tudo
  que vier é invenção". Chave ausente continua significando exatamente o
  que significava antes — "fora da medição" —; a diferença é que agora
  existe um jeito de anotar o oposto sem ambiguidade. Um modelo que
  extraísse perfeitamente nos turnos positivos e inventasse
  `regiao`/`tipo_imovel` à vontade nos 39 negativos não tira mais 100% de
  graça: cada invenção entra no denominador de união contra um `esperado`
  vazio, e há teste travando esse comportamento pelo nome
  (`test_modelo_que_inventa_em_turno_negativo_nao_tira_cem_por_cento`,
  `tests/unit/test_evals_metricas.py`). Mas **61 turnos continuam fora da
  medição**, e é esse o buraco que sobra desta card, não o que ela fecha.
  Três exclusões entre esses 61 foram deliberadas, e cada uma é uma
  armadilha real que valeu a pena nomear em vez de anotar errado só para
  fechar o número: `compra-11` t2 ("o sobrado tem escritura já
  regularizada?") fica de fora porque `sobrado` não está no vocabulário de
  `TipoImovel`, e um modelo que devolve `CASA` está lendo a fala com razão —
  marcar como negativo puniria o acerto com força de gate; `follow-up-03` t2
  ("documentação pra baixa do financiamento") fica de fora porque o
  financiamento ali é o que o lead **já tem**, não a forma de pagamento que
  pretende usar, e a distinção é fina de mais para virar gate; e
  `borda-evasivo-02` t1/t2 ("depois eu vejo com calma") fica de fora porque
  a TEC-239 já decidiu que essa fala não afirma `SEM_PRESSA` — anotá-la como
  negativo afirmaria o contrário, com a mesma força de gate que a omissão
  existe para evitar. As três exclusões cobrem quatro turnos (o par
  `borda-evasivo-02` conta dois); os outros 57 turnos fora da medição não têm
  exclusão documentada: são trabalho de anotação que ainda não foi feito, não
  decisão tomada, e continuam sem cobertura de invenção nenhuma. Um ponto para não
  ler o número errado quando ele aparecer: invenção nos 9 turnos negativos
  de intenção `FORA_DE_ESCOPO` é medida, mas nunca chega a
  `lead_qualification`, porque `campos_a_gravar` devolve dict vazio para
  essa intenção (ver "Garantias") — esse número é sinal de quão disposto o
  modelo está a inventar, não risco de dado permanente gravado. É a
  [TEC-238](https://eduardodurieuxlopes.atlassian.net/browse/TEC-238).
- **Nenhum dos nove campos fica com zero anotação, e o teste guarda isso.**
  Contagem nos 38 turnos anotados, 59 anotações de campo:

  | campo | anotações |
  |---|---|
  | `regiao` | 18 |
  | `tipo_imovel` | 18 |
  | `quartos` | 8 |
  | `forma_pagamento` | 6 |
  | `faixa_preco_max` | 3 |
  | `tem_imovel_para_vender` | 2 |
  | `urgencia` | 2 |
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
  `N` extrações desse tipo tira `59/(59+N)` — `N=6` ainda é VERDE, `N=10` dá
  85,5% (AMARELO) e `N=11` dá 84,3% (VERMELHO). A diferença é que agora isso
  é ruído de anotação faltante, distribuído, e não um piso estrutural em
  quatro campos específicos. Quem for investigar um número baixo lê
  `discrepancias_da_extracao`, que separa `extra` (acusa a medição) de
  `faltou` e `divergiu` (acusam o modelo).
- **A cobertura é por campo, não por valor de vocabulário.** O teste exige uma
  anotação por campo; ele não exige que todo membro de `TipoImovel`,
  `Urgencia` e `FormaPagamento` apareça, e vários não aparecem — `RURAL`,
  `CONSORCIO`, `FormaPagamento.INDEFINIDA`, `SEM_PRESSA` e `ATE_6_MESES` não
  têm nenhuma anotação, nem `tem_imovel_para_vender: false`, que é o caso que
  `preenchidos()` existe para preservar. É a mesma classe de furo que
  `test_toda_intencao_do_enum_aparece` fecha para `Intencao`, e aqui está
  aberta: uma regressão restrita a um desses valores passa o gate. Fechá-la
  exige fala nova para cada valor, algumas bem artificiais, e ficou fora do
  escopo da TEC-239 de propósito.
- **A barra de anotação de `urgencia` é marco temporal explícito.** "mes que
  vem" e "essa semana" contam; "quero fechar logo" e "bora marcar a
  assinatura" não. A barra é estreita porque a métrica pune os dois lados:
  anotar o que a fala não afirma penaliza o modelo por não inventar, e a
  fronteira entre pressa e entusiasmo não sobrevive a dois anotadores
  independentes. Consequência aceita: `follow-up-07` t3 e `follow-up-08` t1
  ficam fora da medição de extração, e um modelo que lê `IMEDIATA` ali não
  ganha nem perde ponto.
- **A precisão de extração nunca foi executada.** O eval é pago e roda sob demanda
  ou em PR que toque `src/mobia/domain/agente/`.
