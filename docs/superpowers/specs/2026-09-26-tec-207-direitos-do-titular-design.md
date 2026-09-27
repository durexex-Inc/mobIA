# TEC-207 — Direitos do titular e retenção

**Status:** implementado, PR aberto
**Card:** [TEC-207](https://eduardodurieuxlopes.atlassian.net/browse/TEC-207) — épico TEC-200
**Branch:** `feat/tec-207-direitos-do-titular`
**Origem:** RNF-19 a RNF-24, PR-09 e RN-B07 do SRS v1.0 (`docs/srs/srs-agente-sdr-imobiliario-v1.0.md`); endpoints da §6.7.

## O corte

A card junta sete frentes de natureza diferente. Esta entrega o **núcleo de direitos**:
- pedido de titular pelo WhatsApp e pelo endpoint, com prazo;
- exportação JSON;
- eliminação por anonimização, preservando as métricas;
- retenção (24 e 12 meses);
- auditoria das ações.

**Viram cards próprias, no backlog** (TEC-380 e TEC-381):
- a redação de dado sensível antes da persistência (TEC-380);
- a pseudonimização antes do LLM (TEC-381).

As duas dependem de detectar conteúdo no texto livre do lead, e isso é outro problema, com outro custo e outro teste. Há uma constatação que muda o tamanho da segunda: **o sistema não guarda o nome do lead**. Não há tabela de lead, e `messages.envelope_context` não tem escritor. O único nome que chega ao modelo é o que o lead digita.

## O que já existia

| Frente | Antes desta card |
|---|---|
| Exportação | `leads/detalhe.py::ler_detalhe` e `leads/transcricao.py::pagina_da_transcricao` (TEC-193), a reusar |
| Correção | `api/routes/intervencao.py::editar` (TEC-194) corrige a qualificação; devolve 409 com a conversa encerrada. **Não muda nesta card** |
| Consentimento com evidência | `consentimento/models.py::Consentimento` (TEC-363) grava texto exibido, data, hora e canal, **só no web**. O critério de aceite está atendido no registro; ninguém exibe nem consulta o consentimento ainda |
| Eliminação, retenção, pedido de titular | Nada. A única retenção é a da trilha (`auditoria/retencao.py::apagar_vencidos`) |

## Decisões tomadas com o Eduardo

1. **Núcleo aqui, o resto em cards filhas.**
2. **Lead convertido = lead com handoff `ACEITO` ou `CONCLUIDO`.** É onde o funil termina e onde o corretor assume a relação; esse lead sai da regra dos 24 meses. A transcrição dele ainda expira em 12.
3. **O pedido pelo WhatsApp vira uma solicitação na fila, e o ADMIN executa.** Não é automático: um terceiro com o celular emprestado não apaga tudo sem revisão, e há espaço para recusa por retenção legal (o 409 da §6.7).

## D1 — Anonimizar por troca de chave

Eliminar não é apagar linhas: apagar `messages` tira o lead da coorte do funil (`metricas/repositorio.py::_nascimento`) e apaga o custo histórico por cascata (`message_telemetry`). A anonimização:

1. **Troca o par em todas as tabelas** de `reindexacao.TABELAS_COM_CHAVE_DE_LEAD` por um **pseudônimo aleatório**: 64 hex de `secrets.token_hex(32)`, não derivado de nada. Nenhuma identidade nova é gravada. O pseudônimo não tem volta, e é isso que o separa do HMAC da TEC-203.
2. **Apaga o que identifica ou é conteúdo:**
   - a linha de `identidades_de_lead`;
   - `vinculos_de_sessao` (o telefone digitado no widget);
   - `conversation_summaries` (o resumo);
   - `text_body`, `raw_payload` e `envelope_context` de `messages`, que viram nulos;
   - os arquivos de mídia do lead (`midia/armazem.py` ganha `apagar`).
3. **Mantém o que as métricas contam:**
   - as linhas de `messages` sem conteúdo (created_at, direction, role);
   - `message_telemetry`, `lead_qualification`, handoffs, agendamentos, recomendações, trilhas de score e intenção e consentimentos, todos sob o pseudônimo.
4. **Tabelas imutáveis:** reusa o desligamento das triggers de `reindexacao.py` (`TRIGGERS_DE_IMUTABILIDADE`), na mesma transação, pela mesma razão declarada lá.
5. **A trilha de auditoria não é tocada.** O `lead_ref` antigo continua lá e deixa de bater com o par, que agora é aleatório. É o que `auditoria/referencia.py::lead_ref` já prometia: "sobrevive à eliminação do lead".
6. **O que a implementação acrescentou** (corrigido na implementação — a lista acima não bastava para "nenhuma coluna guarda o telefone"):
   - **`provider_message_id` vira `'anon:' || id`** em todas as mensagens do par, em qualquer canal. O wamid da Meta é base64 de um protobuf que carrega o telefone em claro, e o id do widget carrega a chave da sessão na frente. O preço: um status de entrega que a Meta mande depois para o wamid antigo não acha mais a linha — para um lead eliminado, o comportamento certo.
   - **`handoffs.resumo` vira nulo.** É derivado da transcrição, e o item 3 o mantinha sob o pseudônimo junto com o handoff.
   - **`referencias_de_lead` é apagada** junto com as três tabelas do item 2, e é isso que faz o `leadId` dar 404 (D4).
   - **Mídia:** toda linha de `midias_recebidas` do par sai, em qualquer status; a sem `chave_no_armazem` entra pela chave determinística de `midia/politica.py::chave_do_objeto`, porque um download em voo pode ter gravado o arquivo antes da linha. `anonimizar_lead` devolve as chaves e **quem chama apaga os arquivos depois do commit** — antes, um rollback deixaria linha apontando para arquivo apagado; depois, o pior caso é um arquivo órfão, logado. `ArmazemDeMidia.apagar` é idempotente.
   - **Toda solicitação `ABERTA` do par é fechada como `ATENDIDA`**, não só a que disparou a anonimização: `solicitacoes_de_titular` está em `TABELAS_COM_CHAVE_DE_LEAD`, e uma aberta seria arrastada para o pseudônimo e ficaria na fila sem ninguém que a pudesse atender.
   - **`eliminacao.anonimizar` só executa solicitação `ABERTA` de `ELIMINACAO`**, sob `SELECT ... FOR UPDATE`; qualquer outra é no-op com log. Um id de pedido de acesso passado por engano apagaria quem só pediu para ver os dados.
   - **O vínculo do mesmo telefone no widget também sai.** Ao eliminar um lead do WhatsApp, `anonimizar_lead` lê o `wa_id` da identidade antes de apagá-la e remove de `vinculos_de_sessao` toda linha com o mesmo `telefone_indice` (`indice_de_telefone(normalizar(wa_id))`): é a única linha fora do par que guarda o número. **Limite declarado:** as conversas web vinculadas são outros pares e ficam — sai o vínculo, não a conversa.
   - **O pulado da rotação de chave.** Sem identidade, o par anonimizado é pulado pela rotação da TEC-203 e conta no aviso de `reindexacao.par_sem_identidade`; o runbook (`docs/seguranca/segredos.md`) diz como separar esse caso do bug.

Função única, `anonimizar_lead(conn, *, channel, conversation_key)`, sync sobre `Connection` como a reindexação. Ela serve a eliminação a pedido e a retenção de 24 meses.

## D2 — Solicitação de titular

Tabela `solicitacoes_de_titular`. Como guarda `conversation_key` enquanto aberta, entra em `reindexacao.TABELAS_COM_CHAVE_DE_LEAD` — a rotação da chave de índice da TEC-203 a arrasta junto:

| coluna | |
|---|---|
| `id` | UUID |
| `lead_ref` | HMAC do par (`auditoria/referencia.py::lead_ref`) — sobrevive à anonimização |
| `channel`, `conversation_key` | o par, **enquanto aberta**; vira nulo ao ser atendida ou recusada |
| `tipo` | `ELIMINACAO` ou `ACESSO` |
| `origem` | `WHATSAPP`, `ADMIN` ou `RETENCAO` — a retenção também registra uma solicitação, já atendida, para que toda anonimização tenha registro e entidade na trilha |
| `status` | `ABERTA`, `ATENDIDA`, `RECUSADA` |
| `motivo_da_recusa` | texto, só na recusa |
| `recebida_em`, `prazo_em` | prazo = recebida + 15 dias |
| `atendida_em` | |

## D3 — O pedido pelo WhatsApp

- **Detecção determinística**, no molde de `optout/deteccao.py::pediu_optout` e `humano/deteccao.py::pediu_humano`: sem chamada paga, porque uma decisão de LGPD não pode depender de o provedor estar de pé.
  - `pedido_de_titular(texto) -> TipoDeSolicitacao | None`.
  - Pedido de eliminação: "apagar meus dados", "excluir meus dados", "deletar meus dados", "esquecer meus dados".
  - Pedido de acesso: "quero meus dados", "quais dados vocês têm".
- **Colisão com o opt-out.** "Remover meu contato" é termo de opt-out. A regra é que texto que fala de **dados** é pedido de titular, e texto que fala de **contato ou mensagens** é opt-out. A precedência fica escrita no código e testada nos dois sentidos.
- **No turno:** entra antes da moderação e sem LLM, como o opt-out.
  - Registra a solicitação (idempotente: uma aberta do mesmo tipo por lead).
  - Responde com texto fixo, **com acento**, um por tipo: "Registrei seu pedido de acesso aos seus dados. Ele será atendido em até 15 dias." e "Registrei seu pedido para apagar seus dados. Ele será atendido em até 15 dias, e até lá não vou mais te enviar mensagens."
  - **Entra antes do portão de silêncio por opt-out**: quem já pediu para sair continua podendo exercer o direito.
  - O texto sai com um kind próprio, que fura as guardas de opt-out e de atendimento humano de `GuardedOutbound.send`, exatamente como `KIND_DA_CONFIRMACAO_DE_OPTOUT` fura: é reconhecimento legal de um pedido do próprio lead, e sem isso o opt-out que o pedido de eliminação registra bloquearia a confirmação dele.
- **O pedido de eliminação também registra opt-out.** Quem pede para apagar os dados não quer receber follow-up enquanto o pedido espera.

**Corrigido na implementação:**
- **Corrigido na implementação: confirmação em dois passos, decisão do Eduardo** (revisão final). O pedido de eliminação pelo WhatsApp **não registra nada, não grava opt-out e não encerra a conversa**: responde com "Para confirmar que você quer apagar seus dados, responda APAGAR. Se não era isso, é só continuar a conversa." (`TEXTO_DA_PERGUNTA_DE_ELIMINACAO`, kind `KIND_DA_PERGUNTA_DE_ELIMINACAO`, desfecho `confirmacao_de_titular_pedida`). O que o parágrafo acima descreve — registrar, gravar opt-out, encerrar e confirmar — passa a acontecer na mensagem **seguinte**, se ela for inteira a palavra de confirmação ("apagar", "sim, apagar", "confirmo apagar") **e** a última mensagem do agente a esse lead tiver sido a pergunta, há menos de 24 horas. A razão: frases de correção de cadastro ("Apaga meus dados antigos e usa esse telefone novo", "Pode excluir meus dados do cadastro antigo e manter o novo?") são indistinguíveis de um pedido legal pelo texto, e em um passo só cada uma delas calava o lead e, sem recusa do ADMIN, o anonimizava uns 14 dias depois.
  - **"A última mensagem do agente" vem de `outbound_dispatches`**, sem tabela nova (`titular/repositorio.py::pergunta_de_eliminacao_pendente`): todo envio ao lead — resposta, texto fixo, follow-up, aviso de agendamento, fala do corretor — reserva `(message_id, kind)` ali antes de sair, e só a reserva guarda o kind. A reserva mais recente das mensagens do par, excluindo as da própria mensagem que confirma (para a retentativa do turno continuar se reconhecendo), tem de ser a da pergunta, com `created_at` a menos de 24 horas do `now()` do banco.
  - **"apagar" sem pergunta pendente segue o turno normal**, e o lead que continua a conversa em vez de confirmar é atendido pelo modelo, sem registro nenhum.
  - **A pergunta fura as guardas de opt-out e de atendimento humano**, como a confirmação (`KINDS_QUE_FURAM_AS_GUARDAS`), e o bloco inteiro continua antes do portão de silêncio: quem já optou pode pedir e confirmar. Uma mensagem que pede opt-out junto com a eliminação grava o opt-out já no primeiro passo.
  - **A palavra de confirmação fura o debounce e o fecho "agrupado"** (`e_palavra_de_confirmacao`, em `IngestionService` e `process_message`) sempre que a mensagem inteira é ela, haja ou não pergunta pendente — a ingestão não consulta o banco, e furar sem ser confirmação só faz o turno rodar sem esperar.
  - **O acesso continua em um passo**, porque não destrói nada.
- **A detecção ficou mais larga que as frases acima, e tem limite declarado.** O objeto é "dados do próprio lead" (`meus dados`, `dados pessoais`, `dados que vocês têm`, `dados … de mim`); a eliminação é um dos seis verbos (apagar, excluir, deletar, remover, esquecer, eliminar) numa forma de pedir, como palavra inteira: infinitivo, infinitivo pessoal, subjuntivo singular e plural ("apaguem", "excluam") e o imperativo singular do português falado ("apaga meus dados"). O presente do indicativo no plural ("vocês apagam meus dados?", "vocês excluem… depois de quanto tempo?") fica de fora: é pergunta, não pedido. O singular fica dentro, com uma ambiguidade aceita: "apaga" é também o indicativo de terceira pessoa, e "o sistema apaga meus dados depois?" vira eliminação — o preço de não perder a forma mais comum de pedir, com o ADMIN podendo recusar na fila. A primeira versão casava o radical solto e transformava em eliminação "uma cópia dos meus dados, exclusivamente por e-mail", "esqueci de mandar meus dados pessoais" e "o anúncio foi removido?"; o particípio ("foram apagados?") fica de fora de propósito; o acesso é o verbo **ligado ao objeto**, nunca um verbo solto: "quero/mandem/enviem" seguido de "meus dados", com no máximo um verbo de acesso ("ver", "receber") e um "uma cópia dos" no meio, ou "quais dados vocês têm **de mim**". A versão anterior aceitava `quero`, `ver` e `quais` soltos em qualquer ponto da mensagem, e a revisão final achou frases de venda viradas em acesso — "Quero agendar uma visita, meus dados: …", "Já mandei meus dados, quero ver o apartamento", "Quais dados pessoais vocês precisam pra visita?", "quero corrigir meus dados" —, cada uma calando o agente com o texto fixo. O preço aceito é o recall: frase de acesso fora dessas duas formas não é reconhecida, e o ADMIN ainda pode atender pela exportação (D4). Negação até duas palavras antes do verbo anula. Frase fora desses padrões não é reconhecida — o ADMIN ainda pode registrar pelo `DELETE` (D4).
- **Veto de imóvel colado ao "dados".** "Quais dados vocês têm do condomínio?" é pergunta sobre o imóvel: um substantivo de imóvel (imóvel, apartamento, casa, condomínio, anúncio) a até quatro palavras do fim do objeto, precedido de preposição (e no máximo um artigo), veta. Um imóvel em outra parte da mensagem ("apaguem meus dados e parem de mandar imóveis") não veta — três rodadas de revisão fixaram essa forma, registradas na docstring de `titular/deteccao.py`.
- **O pedido fura o debounce e o fecho "agrupado"**, como o opt-out e o pedido de humano (`messages/service.py::IngestionService`, `workers/jobs/process_message.py::process_message`): o prazo conta de quando o turno registra o pedido, e uma rajada que o engolisse perderia o pedido em silêncio.
- **O pedido de eliminação encerra a conversa** com motivo `OPTOUT`, pela mesma função do bloco de opt-out (`_encerrar_por_optout`), e só grava opt-out se o lead ainda não estiver nele. **Uma mensagem de acesso que também pede opt-out** ("pare de mandar mensagem e quero meus dados") grava o opt-out junto, porque o bloco do titular retorna antes do bloco de opt-out.
- **Na mesma mensagem, o pedido de titular vence o pedido de humano:** o bloco vem antes de todas as guardas e encerra o turno, então nenhum handoff nasce. Com eliminação confirmada é coerente (a conversa acaba de ser encerrada por opt-out); com acesso, e com a pergunta do primeiro passo da eliminação, o lead que também quer uma pessoa precisa pedir de novo. Registrado como Emenda E-08 à RN-16.1.
- **Antes da moderação de entrada, mas não sem ela:** desde a TEC-297 a moderação roda no fecho de `executar_turno`, depois do registro.

## D4 — Endpoints

Todos exigem a permissão nova `ATENDER_TITULAR`, só do ADMIN, fora de `_CONCEDIDAS` como `VER_AUDITORIA`.

| rota | o que faz |
|---|---|
| `GET /api/v1/titular/solicitacoes` | a fila, filtrável por status, ordenada pelo prazo |
| `GET /api/v1/leads/{leadId}/dados-pessoais` | exportação JSON: canal, telefone revelado, qualificação, transcrição inteira decifrada, agendamentos, consentimentos, datas. Registra `DADOS_EXPORTADOS`. Marca como atendida a solicitação `ACESSO` aberta, se houver |
| `DELETE /api/v1/leads/{leadId}/dados-pessoais` | 202 e job ARQ que roda `anonimizar_lead`. Marca como atendida a solicitação `ELIMINACAO` aberta, ou cria uma de origem `ADMIN` já atendida. 404 se o apelido não resolve, que é o caso do lead já anonimizado |
| `POST /api/v1/titular/solicitacoes/{id}/recusa` | recusa com motivo obrigatório (ex.: retenção legal). Registra `TITULAR_RECUSADO` |

**Corrigido na implementação:**
- **O `DELETE` deixa a solicitação `ABERTA`**, e quem a fecha como atendida é o job, via `eliminacao.anonimizar`. A tabela acima dizia que a rota a marcava atendida ou criava uma já atendida; fechar antes do job rodar mostraria atendido um pedido cujo dado ainda existe. A solicitação que a rota cria tem origem `ADMIN`; a que o lead já abrira pelo WhatsApp é reaproveitada sem trocar a origem. Sem pool do Redis, ou com o enqueue falhando, é 503 e a solicitação continua aberta; o `_job_id` é fixo por solicitação.
- **A exportação** traz também score, recomendações e follow-ups, e a transcrição com as falas retidas pela moderação (`ve_retidas=True`), que a tela do corretor esconde. **O resumo fica de fora**: é derivado da transcrição, que já sai inteira.
- **A recusa** é 404 para solicitação inexistente e 409 para a que já não está aberta; o motivo tem de 1 a 2000 caracteres, e não só espaço.

`leadId` é o apelido de `referencias_de_lead`, como no resto do dashboard. A anonimização apaga a linha de `referencias_de_lead` do par antigo: o apelido deixa de resolver, e o que `leads/detalhe.py` já prevê ("um apelido que sobreviver às mensagens dele é 404") passa a acontecer.

## D5 — Retenção

Sweep diário, `sweep_retencao_de_leads`, depois do da auditoria:

- **Transcrição com mais de 12 meses**, de qualquer lead: o conteúdo das mensagens vira nulo e a mídia correspondente é apagada. A linha fica.
- **Lead sem conversão** (nenhum handoff `ACEITO` ou `CONCLUIDO`) **com mais de 24 meses desde a última interação** (`max(messages.created_at)`, a mesma de `leads/repositorio.py::_ultima_interacao`): `anonimizar_lead`.
- **Solicitação `ELIMINACAO` aberta com o prazo de 15 dias vencido:** `anonimizar_lead`, e a solicitação passa a atendida. Antes do prazo o sweep não toca nela — o ADMIN tem os 15 dias para executar ou recusar (decisão 3); depois deles, o pedido é cumprido, e nenhum passa do prazo legal por inação.
- Em lotes, com commit por lead, para não segurar lock longo.

**Corrigido na implementação:**
- **A transcrição de 12 meses zera `text_body`, `raw_payload` e `envelope_context`, e só.** `handoffs.resumo`, `provider_message_id` e o vínculo de sessão ficam — só a anonimização os apaga, e para o lead convertido, que nunca é anonimizado, eles ficam enquanto a conversa existir. O resumo da conversa (`conversation_summaries`) cuja última mensagem passou do corte é apagado.
- **Par sem identidade não entra na regra dos 24 meses**: é o pseudônimo de um lead já anonimizado, que nunca volta a falar e seria "anonimizado" de novo a cada dia.
- **Reconferência antes de anonimizar** (`titular/retencao.py::_lead_ainda_vencido`): a seleção em lote é um retrato, e o lead pode ter voltado a falar ou ganho um handoff `ACEITO` enquanto esperava a vez.
- **Falha isolada por lead**: uma exceção num lead loga com `lead_ref` (nunca o telefone) e o sweep segue; sem isso, a ordenação faria o mesmo lead problemático travar todas as passagens futuras. Cada uma das três etapas também roda mesmo que a anterior falhe inteira.
- **A eliminação aberta é cumprida um dia ANTES do fim do prazo, e não depois** (`cumprir_eliminacoes_a_vencer`, `titular/repositorio.py::vencendo` com `ANTECEDENCIA_DO_CUMPRIMENTO` de um dia). O bullet acima dizia "com o prazo vencido" e que nenhum pedido passaria do prazo; com o sweep diário, cumprir só o vencido punha toda passagem depois do prazo. Agora o ADMIN tem cerca de 14 dias, e a passagem diária cai dentro dos 15. Ainda não é garantia: o teto de 100 por passagem e uma falha (logada, retentada no dia seguinte) podem fazer um pedido passar.
- **Teto por passagem e `timeout=900`**: até 100 eliminações a vencer, 200 leads (2 lotes de 100) e 10 mil mensagens (20 lotes de 500) por passagem; o job tem teto próprio de 900 s, maior que o `job_timeout` de 240 s do worker. Um acúmulo grande drena em vários dias. A conta está no comentário de `workers/main.py::WorkerSettings`.
- **Ordem das etapas:** eliminações a vencer, depois leads de 24 meses, depois transcrições — assim um lead que caiba em duas regras é processado por uma só.
- **Horário:** 5h, uma hora depois do `sweep_retencao_auditoria` (4h).

## D6 — Auditoria

Ações novas no vocabulário da trilha, com migration que recria o CHECK (molde das 0056/0057):
- `TITULAR_SOLICITOU`: quando o pedido chega, pelo WhatsApp ou pelo ADMIN.
- `DADOS_EXPORTADOS`.
- `LEAD_ANONIMIZADO`: registrada pelo job e pelo sweep, sobre a solicitação (a origem dela diz se foi pedido ou retenção).
- `TITULAR_RECUSADO`.

`Entidade` ganha `solicitacao_de_titular`. `tests/unit/test_auditoria_vocabulario.py` prende as cópias.

## O que a card não entrega

- **Redação de dado sensível e pseudonimização antes do LLM:** TEC-380 e TEC-381.
- **O CRM externo:** o que já foi exportado para ele (`workers/jobs/exportar_crm.py`) não é apagado por nós. A eliminação no CRM é do operador do CRM.
- **Consentimento no WhatsApp:** não existe, e a RNF-19 o exige para follow-up após o encerramento. Fica como lacuna registrada; o follow-up de hoje (`sweep_followups`) não o consulta.
- **Papel de DPO:** não existe; `ATENDER_TITULAR` fica com o ADMIN.
- **Pedido de correção pelo WhatsApp:** não é detectado. A correção continua pelo dashboard (TEC-194).
- **Entrega da exportação ao titular:** o endpoint produz o JSON para o ADMIN; como ele chega ao lead (e-mail, arquivo) é operação, não código.

## Testes

- **Unitários:** detecção (termos, precedência sobre opt-out nos dois sentidos, negação); prazo de 15 dias; vocabulário.
- **Integração:**
  - `anonimizar_lead` sobre lead semeado em todas as tabelas: nenhuma coluna guarda o telefone, a chave antiga ou o conteúdo; a identidade some; o apelido some; triggers voltam ligadas.
  - **O funil e o custo do período são os mesmos antes e depois**: o critério "os indicadores agregados continuam corretos", medido.
  - Turno com "quero apagar meus dados": registra a solicitação, o opt-out e responde o texto fixo sem chamar o modelo. **Corrigido na implementação:** desde a confirmação em dois passos (D3), esse turno só pergunta; o registro, o opt-out e a confirmação vêm no "apagar" seguinte, e há testes para a pergunta vencida (24 horas), para a última fala do agente não ser a pergunta, para o lead que continua a conversa, para quem já optou e para a rajada.
  - Endpoints: permissão, exportação completa, 202 e job, recusa, 404 após anonimizar.
  - Sweep: transcrição de 13 meses esvaziada; lead não convertido de 25 meses anonimizado; lead convertido de 25 meses mantido.

## Critérios de aceite

| Cenário | Situação |
|---|---|
| Exportar os dados em formato portável | Exercitado |
| Eliminação remove o dado pessoal e preserva a métrica | Exercitado, com o funil e o custo comparados antes e depois |
| Pedido pelo próprio WhatsApp é reconhecido | Exercitado |
| Dado sensível é redigido | **TEC-380** |
| Pseudonimização antes do envio ao modelo | **TEC-381** |
| Consentimento de marketing com evidência | Já atendido pela TEC-363 (web); nada muda |

## Emendas ao SRS

- **RNF-21:** o pedido pelo WhatsApp entra numa fila atendida pelo ADMIN; não há execução automática.
- **RNF-22:** "lead sem conversão" = sem handoff `ACEITO` ou `CONCLUIDO`; a anonimização troca o par por pseudônimo aleatório e mantém as linhas sem conteúdo.

Feitas (todas `TEC-207, 26/09/2026`, no SRS): E-01 à RNF-21 (fila, prazo, cumprimento pela retenção, limite da detecção, correção só pelo dashboard, eliminação confirmada em dois passos), E-01 à RNF-22 (conversão, anonimização, os 12 meses, o CRM), E-06 à RNF-18 (as quatro ações e a entidade), E-01 ao `GET` e ao `DELETE` da seção 6.7 (só `ADMIN`; 404 para lead anonimizado; recusa por `POST .../recusa` em vez do 409), E-02 à RN-01.4 (a mídia passa a ter retenção), E-02 à RN-01.6 (o pedido fura o debounce), E-01 à RN-14.4 (a eliminação confirmada também silencia) e E-08 à RN-16.1 (o pedido de titular vence o de humano na mesma mensagem).
