# Arquitetura da Solução — mobIA

> Agente SDR Imobiliário com IA Generativa — Hackathon FIAP (Tech Challenge, Fase 5).
> Documento de arquitetura para entrega junto ao repositório, README e pitch técnico.

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Estilo arquitetural](#2-estilo-arquitetural)
3. [Diagrama de contexto (C4 — Nível 1)](#3-diagrama-de-contexto-c4--nível-1)
4. [Containers (C4 — Nível 2)](#4-containers-c4--nível-2)
5. [Componentes do backend (C4 — Nível 3)](#5-componentes-do-backend-c4--nível-3)
6. [Fluxos principais (sequência)](#6-fluxos-principais-sequência)
7. [RAG do catálogo de imóveis](#7-rag-do-catálogo-de-imóveis)
8. [Modelo de dados](#8-modelo-de-dados)
9. [Jobs e agendamentos (worker)](#9-jobs-e-agendamentos-worker)
10. [Segurança, privacidade e LGPD](#10-segurança-privacidade-e-lgpd)
11. [Inteligência Artificial](#11-inteligência-artificial)
12. [Deploy e infraestrutura](#12-deploy-e-infraestrutura)
13. [Observabilidade e escalabilidade](#13-observabilidade-e-escalabilidade)
14. [Decisões arquiteturais (ADRs)](#14-decisões-arquiteturais-adrs)
15. [Estrutura de diretórios](#15-estrutura-de-diretórios)
16. [Integrações externas](#16-integrações-externas)

---

## 1. Visão geral

O **mobIA** é um agente de pré-venda (SDR) para o mercado imobiliário. Ele atende
leads automaticamente por WhatsApp e por um widget web, conduz uma conversa
humanizada, **qualifica** o lead, identifica a **intenção** (compra, aluguel ou
investimento), consulta uma **base de imóveis** com busca semântica (RAG),
**agenda** reuniões/visitas, faz **follow-up automático** quando o lead esfria e
gera **resumos inteligentes** para os corretores, com um **painel** de
acompanhamento.

O sistema foi desenhado para o modo de falha real do negócio — lead perdido por
demora, falta de acompanhamento e sobrecarga do corretor — e por isso trata com
rigor três propriedades: **não perder mensagem** (durabilidade), **não responder
duas vezes** (idempotência) e **não vazar dado pessoal** (cifra + LGPD).

| Dimensão | Escolha |
|---|---|
| Linguagem/stack | Python 3.13, FastAPI (API), arq (worker assíncrono), Next.js (painel/widget) |
| Dados | PostgreSQL 16 + `pgvector` (busca vetorial), Redis (fila + rate limit + sessão do painel) |
| IA | Anthropic Claude (agente/resumo/moderação), OpenAI (embeddings e transcrição) |
| Canais | WhatsApp Cloud API (Meta), widget web (WebSocket) |
| Integrações | SMTP, Google Calendar, Webhook de CRM |
| Deploy | Contêineres Docker atrás de Traefik em VPS (ou Heroku, como alternativa) |

---

## 2. Estilo arquitetural

**Monólito modular, publicado como três tipos de processo.** Todo o backend vive
num único pacote Python (`mobia`) com fronteiras de módulo bem definidas por
domínio; o mesmo artefato roda em dois papéis — **API** (HTTP, síncrono ao lead)
e **worker** (arq, assíncrono) — e o **frontend** Next.js é o terceiro processo.
Essa separação dá o isolamento de "micro-serviço" (web e worker escalam
independentemente) sem o custo operacional de múltiplos repositórios e contratos
de rede.

```mermaid
flowchart LR
  subgraph proc["Três processos, um código"]
    API["API — FastAPI<br/>(HTTP, caminho do lead)"]
    WRK["Worker — arq<br/>(assíncrono, jobs e cron)"]
    FE["Frontend — Next.js<br/>(painel + widget)"]
  end
  API -->|enfileira| REDIS[("Redis")]
  REDIS -->|consome| WRK
  API --> PG[("PostgreSQL<br/>+ pgvector")]
  WRK --> PG
  FE -->|BFF/REST| API
  FE --> REDIS
```

Princípios que atravessam o código:

- **Domínio no centro, adaptadores na borda.** `domain/` não conhece HTTP nem
  rede; `infra/` isola Postgres, Redis, Anthropic, OpenAI, S3, SMTP, TLS.
- **Durabilidade antes de efeito.** A mensagem é gravada no Postgres **antes** de
  ir para o Redis; se o processo morrer no meio, um cron (`sweep_stalled`)
  reenfileira.
- **Idempotência no efeito externo.** Todo envio passa por `outbound_dispatches`
  com `UNIQUE (message_id, kind)` — reprocessar não duplica mensagem ao lead.
- **Configuração que recusa subir insegura.** Chaves de desenvolvimento, segredo
  de JWT curto ou TLS ausente em produção **abortam o boot** em vez de degradar
  em silêncio.

---

## 3. Diagrama de contexto (C4 — Nível 1)

```mermaid
flowchart TB
  leadWa(["Lead<br/>(WhatsApp)"])
  leadWeb(["Lead<br/>(site / widget)"])
  corretor(["Corretor / Admin<br/>(painel)"])

  subgraph sis["mobIA — Agente SDR Imobiliário"]
    core["Atendimento, qualificação,<br/>RAG, agendamento, follow-up"]
  end

  anthropic["Anthropic Claude<br/>(LLM do agente)"]
  openai["OpenAI<br/>(embeddings + Whisper)"]
  meta["Meta WhatsApp<br/>Cloud API"]
  gcal["Google Calendar"]
  smtp["Servidor SMTP"]
  crm["CRM externo<br/>(webhook)"]

  leadWa <-->|mensagens| meta
  meta <-->|webhook / envio| core
  leadWeb <-->|WebSocket| core
  corretor <-->|HTTPS| core

  core -->|prompts / respostas| anthropic
  core -->|vetores / transcrição| openai
  core -->|agenda visita| gcal
  core -->|notifica corretor| smtp
  core -->|exporta lead| crm
```

---

## 4. Containers (C4 — Nível 2)

```mermaid
flowchart TB
  subgraph edge["Borda"]
    traefik["Traefik<br/>(TLS, roteamento)"]
  end

  subgraph apps["Aplicação (contêineres)"]
    fe["Frontend<br/>Next.js (SSR)"]
    api["API<br/>FastAPI / Uvicorn"]
    wrk["Worker<br/>arq"]
  end

  subgraph data["Dados (rede interna)"]
    pg[("PostgreSQL 16<br/>+ pgvector")]
    redis[("Redis 7")]
  end

  ext["Integrações externas<br/>(Anthropic, OpenAI, Meta,<br/>SMTP, Google, CRM)"]

  traefik -->|"painel.&lt;dominio&gt;"| fe
  traefik -->|"api.&lt;dominio&gt;"| api
  fe -->|"REST / BFF (interno)"| api
  fe -->|sessão do painel| redis
  api -->|"enfileira jobs"| redis
  wrk -->|"consome jobs"| redis
  api --> pg
  wrk --> pg
  api --> ext
  wrk --> ext
```

Responsabilidades por container:

| Container | Responsabilidade | Observações |
|---|---|---|
| **Frontend (Next.js)** | Painel do corretor/admin e página do widget; BFF que fala com a API | Sessão do painel no Redis; sem segredo exposto ao browser |
| **API (FastAPI)** | Webhook do WhatsApp, WebSocket do widget, REST do painel, autenticação | Caminho rápido: persiste e enfileira, não bloqueia o lead |
| **Worker (arq)** | Turno do agente, RAG, resumo, notificação, follow-up, sweeps (cron) | Onde mora o custo (LLM, embeddings) e a recuperação |
| **PostgreSQL + pgvector** | Verdade do sistema: mensagens, leads, catálogo, vetores, auditoria | Só na rede interna, sem porta pública |
| **Redis** | Fila do arq, rate limiting, sessão do painel | Só na rede interna |

---

## 5. Componentes do backend (C4 — Nível 3)

```mermaid
flowchart TB
  subgraph apilayer["Camada API (src/mobia/api)"]
    rotas["routes/<br/>whatsapp · widget · auth · leads ·<br/>conversas · imoveis · corretores ·<br/>agendamentos · handoffs · metricas ·<br/>prompts · configuracao · titular"]
    mw["middleware<br/>(rate limit, correlação)"]
    authz["autorizacao / deps"]
  end

  subgraph dominio["Domínio (src/mobia/domain)"]
    ag["agente<br/>(classificador, turno, busca,<br/>recomendação, investidor)"]
    ctx["context<br/>(montagem, resumo, qualificação,<br/>score, temperatura, janela)"]
    msg["messages / conversa / identidade"]
    cat["catalogo<br/>(importação, parser, busca, fotos)"]
    pessoas["usuarios · corretores"]
    fluxo["followup · handoff · agendamento ·<br/>atendimento · humano · limites"]
    gov["moderacao · consentimento · optout ·<br/>privacidade · titular · auditoria"]
    out["outbound · notificacao · crm · midia · metricas · prompts"]
  end

  subgraph infra["Infra / adaptadores (src/mobia/infra)"]
    db["db (SQLAlchemy async)"]
    queue["queue (arq)"]
    crypto["crypto (cifra + blind index)"]
    emb["embeddings (OpenAI)"]
    llm["anthropic"]
    mod["moderacao"]
    tls["tls · signature · rate_limit · transcricao"]
  end

  subgraph jobs["Worker (src/mobia/workers/jobs)"]
    pm["process_message"]
    outros["gerar_resumo · notificar · exportar_crm ·<br/>baixar_midia · transcrever_audio ·<br/>indexar_catalogo · 12 sweeps"]
  end

  rotas --> dominio
  mw --> authz
  dominio --> infra
  jobs --> dominio
  jobs --> infra
```

O domínio é dividido em **29 módulos** por responsabilidade de negócio; a API
expõe **16 grupos de rotas**; o worker tem **23 jobs** (um de processamento de
turno e o resto de efeitos e varreduras agendadas). Cada módulo de domínio
publica funções puras de regra e um `repositorio.py` que fala com o banco — o
teste exercita a regra sem subir rede.

---

## 6. Fluxos principais (sequência)

### 6.1 Ingestão do WhatsApp e resposta do agente

O cerne do sistema. A API faz o mínimo no caminho síncrono (validar, persistir,
confirmar) e devolve `200` rápido; o trabalho caro acontece no worker.

```mermaid
sequenceDiagram
  autonumber
  participant Meta as Meta WhatsApp
  participant API as API (webhook)
  participant PG as PostgreSQL
  participant R as Redis (arq)
  participant W as Worker (process_message)
  participant Ctx as Contexto + RAG
  participant LLM as Claude
  participant Mod as Moderação

  Meta->>API: POST /webhooks/whatsapp (assinatura HMAC)
  API->>API: valida assinatura (descarta se inválida)
  API->>PG: grava mensagem (COMMIT antes do Redis)
  API->>R: enfileira process_message (debounce de rajada)
  API-->>Meta: 200 OK rápido (p95 ~300ms)
  R->>W: entrega job (job_id estável = sem duplicar)
  W->>Ctx: monta contexto (histórico + resumo + RAG do catálogo)
  Ctx->>PG: lê conversa, qualificação, imóveis (pgvector)
  W->>Mod: modera entrada
  W->>LLM: prompt do turno (orçamento de tokens)
  LLM-->>W: resposta + eventual chamada de ferramenta
  W->>Mod: modera saída
  W->>PG: registra turno em outbound_dispatches (UNIQUE)
  W->>Meta: envia resposta ao lead
  Note over W,PG: Se o worker morrer no meio,<br/>sweep_stalled (a cada 30s) reenfileira.
```

Garantias de robustez:

- **Durabilidade:** a mensagem é commitada no Postgres antes de ir ao Redis.
- **Idempotência:** `_job_id` estável no arq (recusa re-enqueue do mesmo turno) +
  `outbound_dispatches UNIQUE (message_id, kind)` no efeito externo.
- **Rajada:** `debounce` agrupa mensagens picotadas do lead em um só turno.
- **Recuperação:** `sweep_stalled` reenfileira mensagens recebidas e não
  processadas; `sweep_midias_pendentes`, `sweep_importacoes_travadas` cobrem os
  demais caminhos parados.

### 6.2 Qualificação e intenção

```mermaid
sequenceDiagram
  autonumber
  participant W as Worker (turno)
  participant Cls as Classificador de intenção
  participant Q as Qualificação / Score / Temperatura
  participant PG as PostgreSQL
  participant H as Handoff / Agendamento

  W->>Cls: classifica intenção da conversa
  Note right of Cls: COMPRA · ALUGUEL · INVESTIMENTO
  Cls->>PG: grava conversation_intent (+ audit)
  W->>Q: extrai critérios (faixa de preço, quartos, região, urgência, perfil investidor, ticket)
  Q->>PG: atualiza lead_qualification + score + temperatura
  alt lead quente / pronto
    W->>H: encaminha para reunião ou especialista
    H->>PG: cria agendamento / handoff
  else segue qualificando
    W->>W: próxima pergunta (teto de perguntas por turno)
  end
```

A intenção dirige a trilha: **compra** pergunta faixa de preço, quartos, região e
urgência; **investimento** levanta perfil investidor, ticket e expectativa de
retorno (módulo `agente/investidor.py`) e direciona ao especialista. O **score** e
a **temperatura** priorizam o lead quente.

### 6.3 Follow-up automático (reengajamento)

```mermaid
sequenceDiagram
  autonumber
  participant Cron as arq cron (sweep_followups)
  participant F as Domínio followup
  participant PG as PostgreSQL
  participant Meta as WhatsApp

  Cron->>F: a cada ciclo, procura leads dormentes
  F->>PG: lê cadência e última interação
  alt dentro da janela de 24h
    F->>Meta: mensagem livre de reengajamento
  else fora da janela de 24h
    F->>Meta: template aprovado pela Meta (ou vira tarefa do corretor)
  end
  F->>PG: registra envio, encerra cadência se o lead some
```

A cadência respeita a **janela de 24h** da Meta (fora dela só template aprovado) e
o **horário de atendimento** configurável; quando o lead responde, a cadência é
retomada com contexto; quando some, é encerrada (`sweep_followups`,
`sweep_sla`, `sweep_lembretes`).

### 6.4 Autenticação do painel (corretor/admin)

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser (painel)
  participant FE as Frontend (Next BFF)
  participant R as Redis (sessão)
  participant API as API (auth)
  participant PG as PostgreSQL

  B->>FE: e-mail + senha
  FE->>API: POST /api/v1/auth/login
  API->>PG: valida senha (Argon2id)
  alt usuário com MFA (ADMIN sempre)
    API-->>FE: exige TOTP
    B->>FE: código do autenticador
    FE->>API: POST /api/v1/auth/mfa (TOTP)
  end
  API-->>FE: access (JWT curto) + refresh
  FE->>R: grava sessão do painel (cookie httpOnly)
  Note over API,PG: refresh rotacionado, reuso de refresh<br/>tratado como roubo (sessoes_de_refresh)
```

Senhas com **Argon2id**, segundo fator **TOTP** (obrigatório para ADMIN), **JWT**
curto com **refresh rotacionado** e detecção de reuso de refresh. A sessão do
painel vive no Redis; o segredo do Redis nunca chega ao browser.

---

## 7. RAG do catálogo de imóveis

O agente responde sobre imóveis reais por **busca híbrida** (vetorial + filtros
estruturados) sobre o catálogo, com embeddings gerados na ingestão.

```mermaid
flowchart LR
  csv["Base simulada<br/>data/seed/imoveis.csv"] -->|seed / importação| imp["Importação<br/>(parser + validação)"]
  imp --> pg[("imoveis<br/>(Postgres)")]
  cron["arq cron:<br/>indexar_catalogo"] --> emb["Embeddings<br/>(OpenAI text-embedding-3-small, 1536d)"]
  pg --> emb
  emb -->|coluna vector| pg
  lead(["Pergunta do lead"]) --> turno["Turno do agente"]
  turno --> busca["Ferramenta de busca<br/>(agente/ferramenta_de_busca)"]
  busca -->|"vetor + filtros<br/>preço, quartos, região"| pg
  pg -->|imóveis relevantes| busca
  busca --> turno
  turno -->|recomendação citável| lead
```

Pontos de desenho:

- **Indexação incremental** por cron (`indexar_catalogo`): só vetoriza o que mudou,
  em lotes, com teto por passagem.
- **Busca híbrida:** o vetor do `pgvector` dá a semântica ("apartamento perto da
  praia"), e os filtros estruturados aplicam preço, quartos e região; há
  **relaxamento** controlado quando a busca estrita volta vazia.
- **Resposta citável:** a recomendação referencia imóveis existentes, evitando o
  agente "inventar" imóvel (combate a alucinação).
- **Extensões Postgres** criadas por migration: `vector` (pgvector) e `btree_gist`.

---

## 8. Modelo de dados

O esquema tem ~35 tabelas sob migrations Alembic. O diagrama abaixo mostra o
núcleo e as relações principais (atributos resumidos).

```mermaid
erDiagram
  CONVERSAS ||--o{ MESSAGES : contém
  CONVERSAS ||--o| CONVERSATION_INTENT : tem
  CONVERSAS ||--o| LEAD_QUALIFICATION : tem
  CONVERSAS ||--o{ CONVERSATION_SUMMARIES : resume
  CONVERSAS ||--o| IDENTIDADES_DE_LEAD : identifica
  CONVERSAS ||--o{ FOLLOWUPS : agenda
  CONVERSAS ||--o{ HANDOFFS : escala
  CONVERSAS ||--o{ AGENDAMENTOS : marca
  MESSAGES ||--o{ OUTBOUND_DISPATCHES : "efeito idempotente"
  MESSAGES ||--o{ MIDIAS_RECEBIDAS : anexa
  MESSAGES ||--o| MESSAGE_TELEMETRY : mede
  CORRETORES ||--o{ HANDOFFS : recebe
  CORRETORES ||--o{ TAREFAS_DE_CORRETOR : executa
  CORRETORES ||--o{ AGENDAMENTOS : conduz
  USUARIOS ||--o{ SESSOES_DE_REFRESH : autentica
  USUARIOS }o--o| CORRETORES : "vincula (papel CORRETOR)"
  IMOVEIS ||--o{ RECOMENDACOES : citado_em
  IMOVEIS }o--o{ BAIRROS_ADJACENTES : vizinho
  IMPORTACOES ||--o{ IMOVEIS : carrega
  CONVERSAS ||--o{ OPTOUT_EVENTS : "LGPD opt-out"
  CONVERSAS ||--o{ EVENTOS_AUDITORIA : audita
  CONVERSAS ||--o{ MODERATION_EVENTS : modera

  CONVERSAS {
    uuid id PK
    string canal "whatsapp | web"
    string conversation_key "HMAC (não é o telefone)"
    enum estado
    timestamp criado_em
  }
  MESSAGES {
    uuid id PK
    uuid conversa_id FK
    enum direcao "INBOUND | OUTBOUND"
    enum content_type
    bytea conteudo_cifrado "AES-GCM"
    string provider_message_id "idempotência de ingestão"
    enum status
  }
  IDENTIDADES_DE_LEAD {
    uuid id PK
    string lead_ref "blind index (HMAC)"
    string canal
  }
  IMOVEIS {
    uuid id PK
    string referencia
    enum operacao "COMPRA | ALUGUEL"
    numeric preco
    int quartos
    string bairro
    vector embedding "1536d (pgvector)"
  }
  LEAD_QUALIFICATION {
    uuid conversa_id FK
    enum intencao "COMPRA | ALUGUEL | INVESTIMENTO"
    numeric faixa_preco
    int quartos
    string regiao
    enum urgencia
    enum perfil_investidor
  }
  OUTBOUND_DISPATCHES {
    uuid id PK
    uuid message_id FK
    string kind
    string status "UNIQUE(message_id, kind)"
  }
  USUARIOS {
    uuid id PK
    string email UK
    enum papel "ADMIN | GERENTE | CORRETOR | LEITURA"
    string senha_hash "Argon2id"
    bool mfa_habilitado
  }
```

Notas de modelagem relevantes para a avaliação:

- **PII cifrada em repouso.** O conteúdo das mensagens é cifrado (AES-GCM) com
  keyring versionado; o telefone do lead nunca é chave — a conversa é referenciada
  por um `conversation_key` (HMAC) e a auditoria por um `lead_ref` (blind index),
  o que permite buscar sem armazenar o identificador em claro.
- **Idempotência no banco.** `provider_message_id` barra ingestão duplicada;
  `outbound_dispatches (message_id, kind)` barra efeito duplicado.
- **Trilha e retenção.** `eventos_auditoria`, `moderation_events`,
  `conversation_intent_audit`, `lead_score_audit` registram o porquê das decisões;
  sweeps diários aplicam retenção (LGPD).

---

## 9. Jobs e agendamentos (worker)

O worker arq roda **jobs sob demanda** (enfileirados pela API) e **cron** (varreduras
periódicas de recuperação e manutenção).

| Job | Tipo | Papel |
|---|---|---|
| `process_message` | sob demanda | Turno do agente (o fluxo da seção 6.1) |
| `gerar_resumo` | sob demanda | Resumo inteligente da conversa para o corretor |
| `notificar` | sob demanda | Notifica o corretor (SMTP / template WhatsApp) |
| `baixar_midia` / `transcrever_audio` | sob demanda | Mídia recebida (imagem/doc) e áudio → texto (Whisper) |
| `exportar_crm` | sob demanda | Exporta lead qualificado via webhook de CRM |
| `importar_catalogo` / `indexar_catalogo` | demanda / cron 30s | Importa catálogo e gera embeddings incrementais |
| `sweep_stalled` | cron 30s | Reenfileira mensagens recebidas e não processadas |
| `sweep_midias_pendentes` | cron | Recupera download/transcrição parados |
| `sweep_followups` / `sweep_sla` / `sweep_lembretes` | cron | Cadência de follow-up, SLA de aceite, lembretes |
| `sweep_remarcacoes` / `sweep_lista_de_espera` | cron | Remarcação e fila de espera de agendamento |
| `sweep_conversas_inativas` | cron diário | Encerra conversas inativas |
| `sweep_crm_pendentes` | cron 15min | Reenvio de exportações de CRM pendentes |
| `sweep_importacoes_travadas` | cron | Destrava importações de catálogo paradas |
| `sweep_retencao_auditoria` / `sweep_retencao_de_leads` / `eliminar_lead` | cron diário | Retenção e eliminação (LGPD) |

O `keep_result = 0` e o `_job_id` estável garantem que uma varredura que
reenfileira **não multiplique** trabalho nem chamadas pagas de LLM/embedding.

---

## 10. Segurança, privacidade e LGPD

```mermaid
flowchart TB
  subgraph borda["Na borda"]
    hmac["Validação HMAC do webhook (Meta)"]
    rl["Rate limit por número e por IP (Redis)"]
    tls_edge["TLS (Let's Encrypt via Traefik) + HSTS"]
  end
  subgraph app["Na aplicação"]
    jwt["JWT curto + refresh rotacionado"]
    mfa["MFA TOTP (ADMIN obrigatório)"]
    argon["Senhas Argon2id"]
    papeis["Papéis: ADMIN / GERENTE / CORRETOR / LEITURA"]
    mod["Moderação de entrada e saída do LLM"]
  end
  subgraph dados["Nos dados"]
    aes["Conteúdo cifrado AES-GCM (keyring versionado)"]
    blind["Blind index / conversation_key (sem telefone em claro)"]
    optout["Opt-out + retenção + eliminação (LGPD)"]
    tls_infra["TLS para infra gerenciada (configurável)"]
  end
  borda --> app --> dados
```

- **Guardas de boot:** em produção, chave de cifra de desenvolvimento, segredo de
  JWT fraco/padrão, chaves HMAC padrão ou Redis sem TLS (em rede não confiável)
  **abortam a subida** — o sistema recusa rodar inseguro em vez de degradar calado.
- **LGPD:** opt-out reversível só por operação administrativa auditada; retenção e
  eliminação de leads por cron; o titular tem rota de solicitação
  (`solicitacoes_de_titular`).
- **Moderação:** entrada e saída do agente passam por um modelo de moderação; os
  eventos ficam em `moderation_events`.

---

## 11. Inteligência Artificial

```mermaid
flowchart LR
  subgraph multi["Multiagentes (Claude)"]
    agente["Agente principal<br/>(claude-sonnet)"]
    sec["Agente secundário<br/>(claude-haiku)"]
    moder["Moderação<br/>(claude-haiku)"]
    resumo["Resumo<br/>(claude-sonnet)"]
  end
  subgraph openai["OpenAI"]
    embed["Embeddings<br/>text-embedding-3-small"]
    whisper["Transcrição<br/>whisper-1"]
  end
  ctx["Montagem de contexto<br/>(orçamento de tokens, janela,<br/>resumo progressivo, histórico)"]
  rag["RAG do catálogo (pgvector)"]
  ctx --> agente
  rag --> ctx
  embed --> rag
  whisper -->|áudio do lead vira texto| ctx
```

- **Multiagentes por papel:** agente de conversa, agente secundário, moderação e
  resumo — modelos e prompts configuráveis por agente, com **versionamento de
  prompt** (`versoes_de_prompt`, `ativacoes_de_prompt`) e comparação/rollback de
  versão pelo painel.
- **Memória conversacional:** histórico + **resumo progressivo** da conversa,
  montados dentro de um **orçamento de tokens** (regeneração do resumo quando
  estoura), de modo que conversas longas cabem no contexto sem perder o fio.
- **Humanização:** indicador de digitação, debounce de rajada, acentuação e tom na
  fala ao lead, teto de perguntas por turno.
- **Observabilidade de IA:** telemetria por mensagem (`message_telemetry`) com
  custo por modelo materializado no registro; suíte de **evals** versionada
  (`evals/`) como gate de regressão de prompt no CI.

---

## 12. Deploy e infraestrutura

Duas topologias suportadas; a **VPS com Docker + Traefik** é a escolhida para a
entrega. A alternativa **Heroku** está preservada em outra branch.

### 12.1 VPS (Docker Compose + Traefik) — escolhida

```mermaid
flowchart TB
  user(["Internet"]) -->|443| traefik["Traefik<br/>(Let's Encrypt, HTTP→HTTPS)"]
  subgraph vps["VPS única (Hostinger)"]
    traefik -->|painel.dominio| fe["frontend (Next)"]
    traefik -->|api.dominio| api["api (FastAPI)"]
    wrk["worker (arq)"]
    subgraph interna["rede interna (sem porta pública)"]
      pg[("postgres + pgvector")]
      redis[("redis")]
    end
    migrate["migrate (one-shot:<br/>alembic upgrade head)"]
    fe --- interna
    api --- interna
    wrk --- interna
    migrate --- pg
    api -.->|egress| ext["APIs externas"]
    wrk -.->|egress| ext
  end
```

- **Traefik** termina TLS (Let's Encrypt) e roteia por subdomínio; só 80/443
  expostos. Postgres e Redis ficam na **rede interna** (`internal: true`), sem
  porta pública nem saída para a internet.
- **Migração antes do app:** o serviço `migrate` roda `alembic upgrade head` e sai;
  `api`/`worker` só sobem depois dele (`service_completed_successfully`).
- **CI/CD:** GitHub Actions builda imagens (tag = SHA) no GHCR, faz deploy por SSH,
  migra e sobe; **rollback automático** por healthcheck (tag anterior em
  `.last-good`).
- **Operação:** imagens não-root com healthcheck no `/health`; backup diário do
  Postgres (`pg_dump | gzip`, retenção 14 dias); `ufw` + `fail2ban`. Detalhes em
  `docs/deploy-vps.md`.

### 12.2 Heroku (alternativa)

Mesmo código, dois apps: um Python com `web` (uvicorn) + `worker` (arq) via
Procfile e add-ons gerenciados de Postgres/Redis; outro para o frontend.
Documentado em `docs/deploy-heroku.md` (branch `feature/deploy-heroku`).

### 12.3 Pipeline de deploy (VPS)

```mermaid
flowchart LR
  push["push / dispatch"] --> build["GitHub Actions:<br/>build + push GHCR (tag=SHA)"]
  build --> ssh["SSH na VPS"]
  ssh --> pull["docker compose pull"]
  pull --> mig["migrate (alembic)"]
  mig --> up["compose up -d"]
  up --> health{"healthcheck<br/>verde?"}
  health -->|sim| ok["deploy ok"]
  health -->|não| rb["rollback (.last-good)"]
```

---

## 13. Observabilidade e escalabilidade

**Observabilidade.** Logs estruturados (`structlog`) com correlação de requisição
(middleware), máscara de PII nos campos estruturados, e o cuidado de **não vazar a
linha do banco** por dentro de mensagens de exceção (parâmetros ocultados, erro do
driver reduzido a `sqlstate`/constraint). Telemetria por mensagem
(`message_telemetry`) com custo por modelo. A suíte de evals mede qualidade e
regressão de prompt no CI.

**Escalabilidade.** Os três processos escalam de forma independente:

```mermaid
flowchart LR
  subgraph escala["Pontos de escala"]
    api["API: stateless →<br/>escala horizontal atrás do Traefik"]
    wrk["Worker: mais réplicas arq →<br/>mais turnos em paralelo"]
    pg["Postgres: vertical + réplica de leitura,<br/>pgvector indexado"]
    redis["Redis: fila + rate limit compartilhados"]
  end
```

- **API** é stateless (sessão no Redis/JWT): replica horizontalmente sem afinidade.
- **Worker** é a vazão do agente: adicionar réplicas aumenta turnos simultâneos; o
  `_job_id` estável mantém a idempotência mesmo com concorrência.
- **Caminho do lead desacoplado do caminho caro:** a API responde em milissegundos
  e o LLM roda no worker — picos de mensagens viram fila, não timeout.
- **Rate limiting** por número e por IP protege contra abuso e surto.

---

## 14. Decisões arquiteturais (ADRs)

| # | Decisão | Motivo | Trade-off aceito |
|---|---|---|---|
| 1 | Monólito modular com 3 processos (não microsserviços) | Isolamento de escala sem custo de rede/repos; prioridade é velocidade e simplicidade | Um deploy acopla os três artefatos de código |
| 2 | Persistir antes de enfileirar + `sweep_stalled` | Nunca perder mensagem do lead | Latência extra de um COMMIT antes do enqueue |
| 3 | Idempotência via `outbound_dispatches` + `_job_id` | Nunca responder o lead duas vezes | Tabela e chave únicas a manter |
| 4 | PII cifrada + blind index (sem telefone em claro) | LGPD e vazamento por log/erro | Busca por identidade exige HMAC, não `LIKE` |
| 5 | RAG com `pgvector` no mesmo Postgres | Uma base só; busca híbrida simples | Indexação incremental a orquestrar (cron) |
| 6 | Multiagentes com prompt versionado | Qualidade/humanização e rollback de prompt | Mais modelos e configuração a gerir |
| 7 | Config que recusa subir insegura | Falha de segurança é barulhenta, não silenciosa | Boot aborta se o ambiente estiver incompleto |
| 8 | VPS + Docker + Traefik (vs. PaaS) | Controle, custo e demonstração de arquitetura/cloud | Operação (backup, patch, firewall) é responsabilidade nossa |

---

## 15. Estrutura de diretórios

```text
mobIA/
├── src/mobia/
│   ├── app/            # FastAPI: main, config (guardas de produção), logging
│   ├── api/            # routes/, middleware, autorizacao, deps, saida
│   ├── domain/         # 29 módulos de negócio (agente, context, catalogo, ...)
│   ├── infra/          # db, queue, crypto, embeddings, anthropic, tls, ...
│   ├── workers/        # main (WorkerSettings) + jobs/ (process_message + sweeps)
│   ├── admin/          # criar_usuario, seed_catalogo, seed_producao, ...
│   └── evals/          # corpus/runner de avaliação de IA
├── alembic/            # migrations (cria extensões vector e btree_gist)
├── data/seed/          # base simulada de imóveis (imoveis.csv)
├── frontend/           # Next.js (painel + widget)
├── docs/               # arquitetura.md (este doc), deploy-vps.md, deploy-heroku.md
├── Dockerfile · frontend/Dockerfile · docker-compose.prod.yml
├── .github/workflows/  # ci.yml, evals.yml, deploy-vps.yml
└── pyproject.toml · uv.lock
```

---

## 16. Integrações externas

| Integração | Uso | Direção | Observação |
|---|---|---|---|
| **Anthropic Claude** | Agente, moderação, resumo | saída | Modelos configuráveis por agente |
| **OpenAI** | Embeddings do catálogo + transcrição de áudio | saída | `text-embedding-3-small` (1536d), `whisper-1` |
| **Meta WhatsApp Cloud API** | Recebe (webhook HMAC) e envia mensagens | entrada/saída | Janela de 24h; templates aprovados |
| **Widget web** | Canal alternativo ao WhatsApp | entrada/saída | WebSocket (`/widget/chat`) |
| **SMTP** | Notificação ao corretor | saída | Obrigatório para o worker subir |
| **Google Calendar** | Agendamento de visitas/reuniões | saída | Opcional (desliga se sem credencial) |
| **CRM (webhook)** | Exporta lead qualificado | saída | Opcional; assinado; com reenvio |

---

*Documento gerado para a entrega do Tech Challenge (Fase 5). Diagramas em Mermaid,
renderizados nativamente pelo GitHub. Para o passo a passo de publicação, ver
`docs/deploy-vps.md`.*
