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
  contados), contra uma reserva de 400 — que por isso continua em 400. A conta
  usa o mesmo proxy `len/4` do módulo, não uma chamada paga de `count_tokens`, e
  vive em `test_diferenca_entre_o_contado_e_o_enviado`, que quebra se alguma das
  parcelas crescer.
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
pega o cancelamento, e até aqui isso significava perder a mensagem em silêncio:
a linha ficava em `PROCESSING` para sempre, `attempts` não subia, e um
cancelamento depois da reserva de envio commitada fazia o sweeper reenfileirar,
a guarda suprimir a reentrega e a mensagem fechar em `PROCESSED` — terminal —
com o lead sem ter recebido nada.

### Garantias

- Um turno cancelado deixa a mensagem em `FAILED`, com `attempts` incrementado
  e `last_error` preenchido, nunca em `PROCESSING` silencioso. `FAILED` é
  reivindicável, então o sweeper a recupera pelo caminho normal e o teto de
  `sweep_max_attempts` limita o laço.
- O `CancelledError` **continua propagando** depois do registro. Engoli-lo
  quebraria o desligamento limpo do worker.
- Cancelamento durante a entrega libera a reserva em `outbound_dispatches`,
  como já acontecia com `EnvioRetentavel`. É a mesma troca que a TEC-134 fez, e
  pelo mesmo motivo: entre o lead receber duas vezes e nunca receber, a
  duplicata ganha — ela é visível e recuperável, o silêncio não.
- Cancelamento tem evento próprio no log (`message.cancelled`), separado de
  `message.failed`: estourar o orçamento de tempo do worker é problema
  operacional diferente de o turno falhar.
- Todos os testes forçam cancelamento **real** (`task.cancel()` numa task em
  voo). A diferença entre `Exception` e `BaseException` é o defeito inteiro —
  um teste com exceção comum passaria com o bug intacto.

### Lacunas conhecidas

- **A duplicata deixou de ser hipotética.** Se o cancelamento cair depois de o
  POST ter chegado à Meta, liberar a reserva faz a retentativa entregar de
  novo. Foi a escolha consciente; o caso oposto era perder a resposta para
  sempre.
- **Isto não cria folga no `job_timeout`.** Continua em 240s, e `resumir` +
  `classificar` sozinhos já somam o pior caso do cliente. O cancelamento
  apenas deixou de ser invisível — ele continua custando a passada inteira do
  turno, com as chamadas pagas ao modelo. Reduzir a chance de ele acontecer é
  a [TEC-228](https://eduardodurieuxlopes.atlassian.net/browse/TEC-228).
