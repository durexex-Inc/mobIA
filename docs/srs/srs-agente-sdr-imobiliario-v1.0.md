# Especificação de Requisitos de Software — Agente SDR Imobiliário com IA Generativa

**Versão:** 1.0 | **Data:** 22/08/2026 | **Status:** Rascunho para validação
**Contexto:** Tech Challenge — Fase 5 (Hackathon FIAP / POS TECH). Prova de Conceito.

> **Este arquivo é o SRS v1.0 versionado no repositório, com emendas em linha.**
> O corpo é o original de 22/08/2026, byte a byte. Toda mudança posterior aparece
> como um item aninhado **Emenda E-nn (TEC-nnn, data)** logo abaixo da regra que
> altera, nunca reescrevendo o texto original — quem lê vê o que a v1.0 dizia e o
> que mudou depois.
>
> | Emenda | Regras | Card | Data |
> | --- | --- | --- | --- |
> | E-01 | RN-04.2, RN-05.4 | [TEC-255](https://eduardodurieuxlopes.atlassian.net/browse/TEC-255) | 01/09/2026 |
> | E-01 | RN-06.4 | [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152) | 02/09/2026 |
> | E-01 | RN-05.7 | [TEC-148](https://eduardodurieuxlopes.atlassian.net/browse/TEC-148) | 03/09/2026 |
> | E-01 | RN-06.2 | [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) | 03/09/2026 |
> | E-01 | RN-13.4 | [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) | 03/09/2026 |
> | E-01 | RN-13.3 | [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) | 04/09/2026 |
> | E-01 | RN-13.7 | [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188) | 04/09/2026 |
> | E-01 | RN-08.5, RN-08.1, Seção 6.3 (`POST /api/v1/imoveis/importar`) | [TEC-156](https://eduardodurieuxlopes.atlassian.net/browse/TEC-156) | 06/09/2026 |
> | E-01 | RN-08.2 | [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157) | 07/09/2026 |
> | E-01 | RN-09.1, RN-09.6 | [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) | 07/09/2026 |
> | E-02 | RN-08.2 | [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) | 07/09/2026 |
> | E-02 | RN-08.1, RN-09.1 | [TEC-262](https://eduardodurieuxlopes.atlassian.net/browse/TEC-262) | 08/09/2026 |
> | E-01 | RN-09.3 | [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) | 11/09/2026 |
> | E-01 | CA-09.1 | [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) | 11/09/2026 |
> | E-01 | RN-10.3 | [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163) | 12/09/2026 |
> | E-01 | RN-10.4 | [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163) | 12/09/2026 |
> | E-03 | RN-04.2 | [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163) | 12/09/2026 |
> | E-02 | RN-10.3 | [TEC-275](https://eduardodurieuxlopes.atlassian.net/browse/TEC-275) | 13/09/2026 |
> | E-01 | RN-05.5 | [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149) | 14/09/2026 |
> | E-01 | RN-07.2 | [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153) | 14/09/2026 |
> | E-01 | RN-05.2 | [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153) | 14/09/2026 |
> | E-01 | RN-07.3, RN-07.5, RN-10.1 | [TEC-154](https://eduardodurieuxlopes.atlassian.net/browse/TEC-154) | 14/09/2026 |
> | E-01 | RN-13.2 | [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184) | 14/09/2026 |
> | E-01 | RN-13.5 | [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187) | 14/09/2026 |
> | E-01 | RN-03.3 | [TEC-136](https://eduardodurieuxlopes.atlassian.net/browse/TEC-136) | 15/09/2026 |
> | E-02 | RN-06.4 | [TEC-136](https://eduardodurieuxlopes.atlassian.net/browse/TEC-136) | 15/09/2026 |
> | E-02 | RN-02.3 | [TEC-138](https://eduardodurieuxlopes.atlassian.net/browse/TEC-138) | 16/09/2026 |
> | E-01 | RN-03.5 | [TEC-138](https://eduardodurieuxlopes.atlassian.net/browse/TEC-138) | 16/09/2026 |
> | E-01 | RN-13.6 | [TEC-186](https://eduardodurieuxlopes.atlassian.net/browse/TEC-186) | 22/09/2026 |
>
> **Este índice está incompleto e a linha acima não o conserta.** Emendas do corpo de várias cards (TEC-139, TEC-142, TEC-161, TEC-162, TEC-174 a TEC-179, TEC-196, TEC-278) nunca foram indexadas — a TEC-275 acrescentou só a sua. Quem procura a lista completa lê o corpo do documento, não esta tabela.

---

## 1. Visão Geral do Sistema

### 1.1 Objetivo e proposta de valor

O sistema é um **SDR (Sales Development Representative) digital** para o mercado imobiliário: um agente conversacional que atende leads 24 horas por dia no WhatsApp e no site da imobiliária, conduz uma conversa natural para descobrir o que a pessoa procura, consulta a base de imóveis para mostrar opções aderentes, classifica o lead por temperatura, agenda a visita ou reunião com o corretor certo e, quando o lead some, retoma o contato sozinho.

O ganho comercial vem de três frentes mensuráveis: **tempo de primeira resposta** cai de horas para segundos, **nenhum lead fica sem follow-up** porque a cadência é automática, e o corretor só recebe o lead depois de qualificado, com um resumo pronto — em vez de gastar as primeiras trinta perguntas descobrindo se a pessoa tem orçamento. O agente não vende: ele filtra, aquece e entrega. A negociação continua sendo humana.

Como POC de hackathon, o sistema é uma aplicação completa e funcional ponta a ponta, com base de imóveis simulada, mas construída com decisões de arquitetura que sobrevivem à produção — sem atalhos que exijam reescrita para virar produto.

### 1.2 Público-alvo e personas

**Marina, 34 anos — lead compradora.** Está no WhatsApp às 22h30 depois de ver um anúncio no Instagram. Escreve "oi, esse apartamento da zona sul ainda tá disponível?" e, se ninguém responder em dez minutos, já mandou mensagem para outras três imobiliárias. Ela não quer preencher formulário nem falar com robô que responde por menu numerado. Ganha: resposta imediata, três opções que realmente cabem no bolso dela e uma visita marcada sem trocar quinze mensagens.

**Ricardo, 48 anos — lead investidor.** Tem R$ 800 mil para alocar e quer saber rentabilidade de aluguel, não metragem de varanda. Detesta ser tratado como quem compra para morar. Ganha: um atendimento que reconhece o perfil dele na segunda mensagem e o direciona para o especialista em investimentos, com o ticket e a expectativa de retorno já registrados.

**Paulo, 41 anos — corretor.** Recebe 60 leads por semana no celular pessoal, misturados com mensagens de família. Perde tempo com curioso e esquece de retomar quem estava quente. Ganha: uma fila priorizada por score, resumo de uma tela por lead, e a agenda preenchida com visitas confirmadas em vez de "depois eu vejo".

**Anelise, 37 anos — gerente comercial.** Hoje não sabe quantos leads entraram, quantos foram atendidos e onde o funil vaza; monta relatório no Excel toda segunda. Ganha: dashboard com funil em tempo real, taxa de qualificação, tempo médio de resposta e volume por origem.

### 1.3 Escopo

**Dentro do MVP (POC entregável):**

| # | Item |
|---|---|
| 1 | Atendimento conversacional em WhatsApp (Meta Cloud API) e widget web de chat |
| 2 | Orquestração multiagente com roteamento por intenção (compra, aluguel, investimento) |
| 3 | Memória conversacional persistente entre sessões e canais |
| 4 | Qualificação progressiva com lead scoring automático |
| 5 | RAG sobre base simulada de imóveis (busca híbrida: vetorial + filtros estruturados) |
| 6 | Agendamento de visitas e reuniões com verificação de disponibilidade do corretor |
| 7 | Follow-up automático em cadência configurável |
| 8 | Resumo inteligente e handoff para o corretor |
| 9 | Dashboard web de acompanhamento (funil, leads, conversas, agendamentos) |
| 10 | Observabilidade de LLM (tracing, custo por conversa, latência) e guardrails |
| 11 | Deploy em cloud com CI/CD |

**Fora do MVP:**

- Fechamento de contrato, geração de proposta, assinatura digital, análise de crédito.
- Integração com portais externos (VivaReal, ZAP, OLX) — a base é simulada e carregada por seed/CSV.
- Voice AI (atendimento por áudio em tempo real). O sistema aceita **áudio recebido** no WhatsApp com transcrição (RF-01.3), mas não faz chamadas de voz. Fica como evolução declarada, com o ponto de extensão previsto na arquitetura.
- Integração bidirecional com CRM de mercado. O MVP entrega um **adaptador CRM com implementação de webhook genérico**; conectores para Pipedrive/HubSpot ficam como plug-in.
- App mobile nativo. O dashboard é web responsivo.
- Multi-tenant real (várias imobiliárias isoladas na mesma instância). A modelagem já prevê a coluna `tenant_id`, mas o MVP roda com um único tenant.
- Pagamentos, assinatura de plano, faturamento.

### 1.4 Premissas

Nenhuma destas informações estava no briefing; foram arbitradas com base em prática de mercado e precisam de validação antes de virarem backlog.

| ID | Premissa | Impacto se for diferente |
|---|---|---|
| PR-01 | Volume da POC: até 200 leads simultâneos e 5.000 mensagens/dia. | Acima de ~50 mensagens/s a fila de processamento precisa de partição por tenant e o rate limit da Meta vira gargalo. |
| PR-02 | A base simulada tem entre 500 e 2.000 imóveis, carregada por seed em JSON/CSV com fotos por URL. | Acima de 100 mil imóveis, `pgvector` com IVFFlat deixa de bastar e exige HNSW ou banco vetorial dedicado. |
| PR-03 | Um único tenant (uma imobiliária) na POC, com `tenant_id` já modelado. | Multi-tenant real exige RLS no Postgres e isolamento de índice vetorial — 2 a 3 dias de trabalho adicional. |
| PR-04 | Idioma único: português do Brasil. | Multi-idioma exige detecção de idioma no ingress e prompts versionados por locale. |
| PR-05 | Conta WhatsApp Business API em modo de teste (até 5 números verificados) durante a POC. | Produção exige verificação de negócio na Meta e aprovação de templates de mensagem — prazo de 3 a 15 dias úteis, fora do controle do time. |
| PR-06 | Janela de atendimento: agente responde 24/7; corretor humano atende de segunda a sábado, 9h–19h. | Handoff fora do horário cai em fila com aviso ao lead, não em espera silenciosa. |
| PR-07 | Provedor de LLM principal: Anthropic Claude via API, com OpenAI como fallback. | Restrição de fornecedor único elimina a estratégia de fallback do RT-02 e aumenta o risco de indisponibilidade. |
| PR-08 | Orçamento de POC de até US$ 150 em créditos de LLM para desenvolvimento, demo e testes. | Abaixo disso, é preciso trocar o modelo de qualificação por um modelo menor e cachear respostas de demo. |
| PR-09 | Os dados dos leads são dados pessoais reais desde a POC (nome, telefone, preferências). | Se a demo usar apenas dados sintéticos, o rigor de LGPD pode ser demonstrado sem tratar titulares reais — mas o código deve permanecer o mesmo. |
| PR-10 | Prazo de execução do hackathon: 4 a 6 semanas com equipe de 3 a 5 pessoas. | Prazo menor exige cortar o Anexo B (roadmap) na coluna "P2". |

---

## 2. Requisitos Funcionais

Cada requisito tem identificador rastreável. `RF-` = requisito funcional, `RN-` = regra de negócio, `CA-` = critério de aceite.

### 2.1 Módulo A — Atendimento Conversacional

#### RF-01 — Recepção multicanal de mensagens

**História:** Como lead, quero mandar mensagem pelo WhatsApp ou pelo chat do site e ser atendido imediatamente, para não precisar esperar horário comercial nem preencher formulário.

**Regras de negócio:**
- RN-01.1: O sistema aceita mensagens de dois canais: WhatsApp (webhook da Meta Cloud API) e widget web (WebSocket). Um mesmo lead identificado pelo telefone tem histórico unificado entre canais.
  - **Emenda E-01 (TEC-124, 24/09/2026):** a identidade do canal web é o **UUID de sessão emitido pelo servidor**, não o telefone. A segunda frase desta regra — "um mesmo lead identificado pelo telefone tem histórico unificado entre canais" — descreve a TEC-129 e não esta card: aqui, duas sessões da mesma pessoa, em dois navegadores, são duas conversas sem relação entre si, e o widget não pede telefone em momento algum. O id é emitido no primeiro frame e reapresentado pela página na reconexão; ele nunca viaja em URL, porque em query string entraria em log de acesso, `Referer` e histórico do navegador. O canal é gravado como `web`, minúsculo, e não `WEB` como a card escrevia: a coluna `messages.channel` já estava povoada com `whatsapp` em minúsculas. **Consequência declarada:** quem tiver o id lê aquela conversa — é a mesma exposição de um link mágico, mitigada por ser UUIDv4 e por não haver autenticação de visitante nesta fase.
- RN-01.2: O webhook responde `200 OK` em até 500 ms e processa a mensagem de forma assíncrona via fila. Nunca processa LLM dentro do ciclo de requisição do webhook.
- RN-01.3: Mensagens de áudio recebidas são transcritas (Whisper ou equivalente) e tratadas como texto. Áudios acima de 120 segundos são recusados com resposta cordial pedindo texto.
- RN-01.4: Imagens e documentos recebidos são armazenados e o agente responde reconhecendo o envio, sem tentar interpretá-los no MVP.
- RN-01.5: Mensagens duplicadas (mesmo `message_id` da Meta) são descartadas por idempotência — a Meta reenvia em caso de timeout.
- RN-01.6: Se o lead enviar 3 mensagens em menos de 8 segundos, o sistema aguarda o fim da rajada (debounce de 6 s) e responde uma única vez considerando todas — comportamento humano, não uma resposta por linha.
  - **Emenda E-01 (TEC-128, 21/09/2026):** o debounce é **incondicional** — toda mensagem recebida aguarda a janela antes de virar turno, e não apenas a que integra uma rajada de três em oito segundos. A condição original não é implementável: a rajada só é reconhecível depois de terminada, e a essa altura a resposta à primeira mensagem já teria sido entregue e a reserva dela em `outbound_dispatches` já estaria commitada. A janela é configurável (`debounce_de_rajada_segundos`, default 6 s) e mensagem de opt-out não a aguarda.

**Critérios de aceite:**
- CA-01.1: Dado um webhook da Meta com mensagem de texto, quando recebido, então o `200 OK` retorna em menos de 500 ms e a mensagem aparece na fila.
- CA-01.2: Dado o mesmo `message_id` entregue duas vezes, quando processado, então apenas uma resposta é enviada ao lead.
- CA-01.3: Dadas 3 mensagens em 5 segundos, quando processadas, então o lead recebe uma única resposta que contempla o conteúdo das três.

#### RF-02 — Memória conversacional e continuidade

**História:** Como lead que voltou dois dias depois, quero continuar de onde parei, para não repetir tudo que já falei.

**Regras de negócio:**
- RN-02.1: Toda mensagem (entrada e saída) é persistida com timestamp, canal, papel (`lead`/`agente`/`corretor`) e metadados de custo/tokens.
- RN-02.2: O contexto enviado ao LLM é composto por: (a) as últimas 20 mensagens na íntegra, (b) um resumo comprimido das mensagens anteriores, (c) o estado estruturado de qualificação do lead. O resumo é regerado a cada 20 mensagens novas.
  - **Emenda E-01 (TEC-297, 21/09/2026):** a composição descrita acima exclui a fala que a moderação de entrada bloqueou, e essa exclusão nunca foi escrita nesta especificação — existia só no código desde a TEC-236 (agosto de 2026). O item (a) lê `messages` filtrando a marca de bloqueio, e o item (b) **herda a exclusão por construção**: a dobra que forma o resumo opera sobre a lista que a leitura do item (a) devolve e nunca relê a tabela, então o que não sai de lá nunca chega ao resumo permanente. A mesma definição de fala do lead governa a contagem do lead score (RF-06) desde a TEC-152 e a âncora da cadência de reengajamento (RF-13) desde a TEC-183 — ver a Emenda E-01 da RN-13.4 —, e a TEC-295 acrescentou um quarto leitor sob a mesma definição, o do agrupamento de rajada, prendendo os quatro com teste. A TEC-297 estendeu a marca aos cinco caminhos que retornavam antes da moderação — ver a Emenda E-03 da RN-04.5. **Consequência aceita:** a fala bloqueada também deixa de contar para o gatilho de regeneração do resumo descrito na segunda frase desta regra.
- RN-02.3: A conversa é considerada **encerrada** após 30 dias sem interação, ou por handoff concluído, ou por opt-out. Nova mensagem após encerramento abre nova conversa vinculada ao mesmo lead, com acesso ao histórico anterior via resumo.
  - **Emenda E-01 (TEC-278, 13/09/2026):** concluir o handoff **não** encerra a conversa. A regra acima junta *"handoff concluído"* e *"conversa encerrada"* como se fossem o mesmo fato, e este sistema precisa separá-los: o handoff acaba quando o humano termina o atendimento, e `POST /api/v1/conversas/devolver` — a rota que o conclui, ver a Emenda E-04 da RN-16.4 — significa **retomar** o atendimento automático, não encerrá-lo. Se concluir encerrasse, o lead que o corretor acabou de atender voltaria a falar com um agente sem memória do que aconteceu. O encerramento de conversa segue sendo só por inatividade (TEC-130, ainda a fazer) ou por opt-out. **A TEC-130 tem de respeitar essa separação quando chegar.** Ver a D3 do desenho da TEC-278.
  - **Emenda E-02 (TEC-138, 16/09/2026):** a Emenda E-01 acima afirmava que *"o encerramento de conversa segue sendo só por inatividade (TEC-130, ainda a fazer) ou por opt-out"* e advertia que *"a TEC-130 tem de respeitar essa separação quando chegar"*. As duas frases datam de antes desta card e não valem mais: existe hoje um **terceiro** motivo de encerramento, `FORA_DE_ESCOPO` (RN-03.5) — e a entidade de conversa que a regra pressupõe, e que a Emenda E-01 da RN-05.7 registrava como deferida, **passou a existir nesta card**: a tabela `conversas`, com colunas `status` (`ATIVA`/`ENCERRADA`) e `motivo_do_encerramento`, este último um vocabulário aberto a outros motivos. **A TEC-130, quando chegar, estende essa entidade em vez de criá-la**: acrescenta `INATIVIDADE` ao vocabulário de motivos e o escritor que fecha a conversa por inatividade, sem tabela nova nem uma segunda noção de "encerrada". **E ganha com isso a escrituração do encerramento, não a janela de silêncio**: os 30 dias em que o agente não responde são política do `FORA_DE_ESCOPO` (RN-03.5), não propriedade do `status` — a guarda do turno exige o motivo, e um motivo novo só entra no silêncio se quem o acrescentar decidir isso explicitamente. A distinção não é acadêmica: silêncio por omissão calaria o agente por 30 dias em toda conversa fechada por inatividade, destruindo exatamente o reengajamento que esta regra existe para ter — *"nova mensagem após encerramento abre nova conversa vinculada ao mesmo lead"*. A advertência da Emenda E-01 continua valendo como registro histórico — de uma separação que, na época, ainda dependia de a TEC-130 chegar primeiro, o que não aconteceu.
  - **Emenda E-03 (TEC-130, 22/09/2026):** esta regra ganhou implementação, e em três pontos ela diverge do que a card pedia. **(1) Concluir o handoff não encerra a conversa**, e o cenário Gherkin da TEC-130 que pedia isso foi descartado — a Emenda E-01 acima já havia decidido a separação, e sob esta card ela passou a ter uma consequência que não tinha em 13/09: o encerramento agora dobra o histórico no resumo, então encerrar ao concluir faria o lead que o corretor acabou de atender voltar a um agente sem a transcrição daquele atendimento. **(2) Os motivos de encerramento passam a ser três:** `FORA_DE_ESCOPO` (RN-03.5), `INATIVIDADE` e `OPTOUT` — nenhum dos dois novos herda a janela de 30 dias de silêncio, que continua sendo política do primeiro. **(3) O encerramento por inatividade conta a partir da última fala do lead** (`INBOUND`), não da última mensagem de qualquer direção: *"sem interação"* é o lead sem interagir, e o agente falando sozinho é a evidência de que não há interação, não o contrário. **O filtro é preventivo**, e não o conserto de um adiamento que exista: `sweep_followups` entrega o follow-up da RN-13.1 por `outbound.send` e não grava linha em `messages` — a contabilidade dele é a tabela `followups` —, e o único criador de linha OUTBOUND ali é `MessageRecorder.record_agent_message`, chamado só de dentro do turno. Contar OUTBOUND, hoje, não adiaria encerramento nenhum; o filtro existe para que o dia em que a entrega do follow-up virar linha em `messages` não mude o encerramento de quem sumiu. A promessa *"com acesso ao histórico anterior via resumo"* passou a ser verdade por construção — a primeira mensagem depois do encerramento dobra o histórico no resumo antes de montar o contexto, então a conversa nova recebe o resumo da anterior e **nenhuma linha da transcrição dela**. Sem exceção: o gatilho é um intervalo de 30 dias entre duas mensagens consecutivas do que ainda não foi resumido, e o corte cai exatamente nesse intervalo, de modo que fica literal só o que veio depois dele. Nem a fala bloqueada pela moderação de entrada (Emenda E-01 da RN-02.2) abre exceção: a recusa que aquele ramo entrega é gravada como fala do agente antes da montagem, e é ela que marca o lado novo do intervalo. **A única forma de a transcrição anterior chegar ao prompt é a degradação declarada:** o resumidor fora do ar na hora da dobra mantém o resumo anterior e não avança a marca, com alarme próprio (`contexto.dobra_forcada_falhou`) e nova tentativa no turno seguinte. **Lacuna declarada:** não nasceu identidade por conversa; `Lead 1:N Conversa`, no modelo de dados da seção 5, continua sendo o diagrama e não o esquema — não há como listar nem contar as conversas anteriores de um lead. Ver `docs/superpowers/specs/2026-09-22-tec-130-encerrar-por-inatividade-design.md`.
- RN-02.4: O estado estruturado (intenção, orçamento, região, quartos, urgência) nunca é reconstruído pelo LLM a cada turno — é lido do banco e injetado no prompt. O LLM apenas propõe atualizações via tool call.
- RN-02.5: Contexto máximo enviado ao modelo: 12.000 tokens. Excedido, o resumo é comprimido antes da chamada.

**Critérios de aceite:**
- CA-02.1: Dado um lead que informou orçamento na conversa e retorna após 48 horas, quando escreve novamente, então o agente não repergunta o orçamento e faz referência explícita ao que já sabia.
- CA-02.2: Dada uma conversa com 60 mensagens, quando o agente responde, então o prompt enviado contém resumo + 20 mensagens e não estoura 12.000 tokens.

#### RF-03 — Identificação de intenção e roteamento

**História:** Como lead investidor, quero que o atendimento entenda logo que não estou comprando para morar, para não responder perguntas irrelevantes.

**Regras de negócio:**
- RN-03.1: Intenções suportadas: `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `VENDER_IMOVEL`, `SUPORTE_CONTRATO`, `INDEFINIDA`, `FORA_DE_ESCOPO`.
- RN-03.2: A intenção é classificada a cada turno com confiança de 0 a 1. Abaixo de 0,6, o agente faz **uma** pergunta aberta de desambiguação em vez de assumir.
- RN-03.3: A intenção pode mudar durante a conversa (lead começa em aluguel e migra para compra). A mudança é registrada com histórico e dispara reavaliação da qualificação, preservando os campos ainda válidos (região, quartos).
  - **Emenda E-01 (TEC-136, 15/09/2026):** O descarte vale para qualquer troca de **banda de valor**, não só para o par ALUGUEL↔COMPRA que o Gherkin da card nomeia: `COMPRA`, `INVESTIMENTO` e `VENDER_IMOVEL` compartilham a mesma banda, então migrar entre elas não descarta nada, e migrar de qualquer uma delas para `ALUGUEL` (ou vice-versa) descarta. Uma conversa sem intenção acumulada ainda conta como troca: o número foi admitido sob a banda frouxa (a união das duas, sem validar nenhuma), e por isso não sobrevive à primeira classificação que o lead recebe. **Só o orçamento é descartado** — `faixa_preco_min_centavos`, `faixa_preco_max_centavos` e a marca de pergunta nas duas colunas que a guardam (`perguntados_sem_resposta`, `campos_recusados`); `forma_pagamento`, `tem_imovel_para_vender` e o bloco inteiro de investidor sobrevivem à troca e continuam contando para a completude. O teto de perguntas da RN-05.5 não devolve nada — a pergunta que descobriu o orçamento descartado continua contada. A troca fica registrada em `conversation_intent_audit` (append-only, uma linha por troca), e o recálculo de score que ela dispara nomeia a causa na trilha da RN-06.4, mesmo quando nenhum dos cinco fatores se move.
- RN-03.4: `VENDER_IMOVEL` e `SUPORTE_CONTRATO` não são qualificados pelo SDR — vão direto para a fila de handoff com a etiqueta correspondente.
  - **Emenda E-01 (TEC-137, 15/09/2026):** para estas duas intenções, o lead deixa de receber a prosa do modelo — recebe um texto fixo de encaminhamento, um por intenção (`venda-imovel` e `suporte-contrato` são filas diferentes, e quem tem dúvida de contrato já é cliente, não um lead comum). A substituição vale em **todo turno** com aquela intenção, não só no primeiro: o lead que insiste recebe a mesma frase de novo. Fora da janela de atendimento da imobiliária (TEC-143), o texto ganha um aviso de horário formatado a partir da configuração, nunca de um literal. **Divergência declarada:** o Gherkin da card fala em *"de segunda a sábado, das 9h às 19h"*; a janela real, configurada pela TEC-143, é 9h–18h, sem componente de dia da semana. O texto formata a partir da configuração — diz o que o sistema de fato faz —, e alinhar os dois números é decisão de produto, não de código.
  - **Emenda E-02 (TEC-285, 19/09/2026):** a divergência que a Emenda E-01 declarou está **fechada**, e no sentido do Gherkin: a janela de atendimento da imobiliária passa a ser **de segunda a sábado, das 9h às 19h**, alinhando-se ao PR-06. O que muda no sistema são duas coisas, e só a primeira estava na E-01: `atendimento_horario_fim` vai de 18 para 19, e **domingo deixa de ser dia de atendimento** — um eixo que a configuração não tinha. Os dias são **regra em código** e não configuração (`_DOMINGO`, em `domain/humano/deteccao.py`), enquanto as horas continuam vindo de `Settings` e sendo formatadas no texto, que era o argumento da E-01 e não cai. **Consequências declaradas:** sábado às 18h30 passava a fora da janela e passa a dentro, porque a mudança de horas alcança os seis dias; e o aviso de janela humana da TEC-177 continua prometendo "de segunda a sábado" com as horas do **corretor**, cuja jornada ainda não tem dia da semana — a divergência encolhe pela metade e só fecha com a agenda real (TEC-170). Ver `docs/superpowers/specs/2026-09-19-tec-285-janela-de-atendimento-com-dia-da-semana-design.md`.
- RN-03.5: `FORA_DE_ESCOPO` (assunto sem relação com imóveis) recebe resposta cordial que redireciona ao tema; após 3 tentativas seguidas fora de escopo, a conversa é encerrada educadamente.
  - **Emenda E-01 (TEC-138, 16/09/2026):** o encerramento desta regra é uma **janela de silêncio de 30 dias, e não um estado terminal**: passados os 30 dias, a próxima mensagem do lead reabre a conversa (`status` volta a `ATIVA`) e o turno segue normalmente. A contagem de *"3 tentativas seguidas"* é de mensagens cuja intenção **efetiva** é `FORA_DE_ESCOPO`, **consecutivas** — qualquer outra intenção zera o contador, inclusive dentro da mesma conversa. "Efetiva" é a intenção depois do limiar de desambiguação: um palpite `FORA_DE_ESCOPO` com confiança abaixo do limiar vale `INDEFINIDA` e **zera** o contador, pela mesma convenção que as outras regras deste sistema já seguem — uma classificação que não sustenta roteamento não pode sustentar 30 dias de silêncio. A *"resposta cordial que redireciona ao tema"* das duas primeiras mensagens continua sendo prosa do modelo, sem literal nem instrução de prompt que garanta o redirecionamento; só a terceira mensagem recebe texto fixo do repositório, que substitui a resposta do modelo — **exceto quando a moderação de saída bloqueia aquele turno**, caso em que o lead recebe o texto neutro da moderação e a conversa é encerrada mesmo assim, sem ouvir a despedida. O encerramento não espera um turno desbloqueado: esperar deixaria a conversa aberta indefinidamente diante de um interlocutor cujo texto a moderação sempre barra, que é justamente o perfil de abuso que esta regra limita. A partir da **quarta** mensagem dentro da janela, o turno não chama mais o modelo: uma guarda no topo de `executar_turno` devolve antes da moderação de entrada, da montagem de contexto e da classificação. **A guarda é cega ao conteúdo** — a partir desse ponto ela não classifica mais nada, só olha o relógio e o contador que a terceira mensagem já fechou; uma mensagem dentro do assunto que chegue nessa janela é silenciada exatamente do mesmo jeito, e o turno é só *rotulado* `"fora_de_escopo"`, não verificado como tal. Um falso positivo do classificador nas três primeiras mensagens produz esse mesmo silêncio — é a lacuna que o próprio desenho da TEC-138 declara. Essa guarda abre duas exceções, e as duas são decisão de pessoa vencendo política automática: o pedido de opt-out (LGPD) e o pedido explícito de atendimento humano — este último também **reabre** a conversa, ainda dentro da janela, porque o lead voltou com um pedido que não é fora de escopo. Ver a D5 do desenho da TEC-138.

**Critérios de aceite:**
- CA-03.1: Dada a mensagem "quero investir em imóveis para renda", quando classificada, então a intenção é `INVESTIMENTO` com confiança ≥ 0,8 e o agente pergunta sobre ticket ou expectativa de retorno — não sobre número de quartos.
- CA-03.2: Dada a mensagem "queria ver umas casas aí", quando classificada com confiança < 0,6, então o agente faz uma pergunta de desambiguação entre comprar e alugar.

#### RF-04 — Humanização e guardrails

**História:** Como lead, quero conversar com algo que soe humano e nunca me prometa o que não pode cumprir, para confiar na imobiliária.

**Regras de negócio:**
- RN-04.1: O agente se identifica como assistente virtual da imobiliária na primeira mensagem de cada conversa. Não finge ser pessoa física se perguntado diretamente.
  - **Emenda E-01 (TEC-139, 11/09/2026):** "conversa", na expressão *"primeira mensagem de cada conversa"*, passa a ter definição operacional: **não há mensagem desta conversa, em qualquer direção, nos últimos 30 dias**, derivada do timeline de `messages`. A definição é **provisória** e existe porque a entidade de conversa não existe — a emenda E-01 da TEC-148 sob a RN-05.7 registra que ela foi deferida, e a TEC-130 é quem a cria. O limiar de 30 dias é o mesmo que a TEC-130 nomeia, e não um segundo número: quando aquela card chegar, esta definição é substituída pela entidade, não reconciliada com ela. A identificação vale para a **primeira mensagem de saída** da conversa em qualquer trilha — resposta do agente, recusa da moderação (RN-04.5), texto neutro de saída ou confirmação de opt-out (RN-14.2) —, porque a regra protege o lead de receber texto nosso sem saber de quem é, e a trilha que produziu o texto não muda isso. Ver as D1 e D2 do desenho.
- RN-04.2: Respostas limitadas a 600 caracteres por mensagem, com no máximo 2 mensagens consecutivas. Uma pergunta por vez — nunca um questionário de cinco itens.
  - **Emenda E-01 (TEC-255, 01/09/2026):** a cláusula *"uma pergunta por vez"* passa a admitir **até duas perguntas por turno**. As outras duas cláusulas desta regra — 600 caracteres e no máximo 2 mensagens consecutivas — ficam inalteradas.

    **Motivo, medido.** Duas execuções pagas de 31/08/2026, sobre 294 turnos, mostraram que o cenário que a regra teme não acontece: as violações são quase todas de duas perguntas de qualificação genuínas (*"Você tem alguma região de preferência? E precisa de vaga?"*), e o maior turno observado tem **três** perguntas, uma única vez. O teto de uma pergunta marcava ~19% dos turnos como violação de um comportamento que ninguém pretendia corrigir, e régua que ninguém pretende obedecer vira régua ignorada. Sob o teto de duas, as mesmas execuções dão 98,0% e 99,3% de aderência, e a régua continua pegando o turno de três perguntas.

    O "questionário de cinco itens" que esta regra existe para impedir continua proibido — é justamente o que o teto de duas passa a vigiar.
  - **Emenda E-02 (TEC-162, 09/09/2026):** o teto de *"no máximo 2 mensagens consecutivas"* passa a valer para mensagens de **texto**. A apresentação de imóveis da RN-10.2 pode emitir até 3 mensagens de **apresentação** por turno — mídia, ou texto quando o imóvel não tem foto (RN-10.2, D13 do desenho da TEC-162): a ficha sem foto cai no caminho de texto que já existe, e não deixa de contar como apresentação por isso. A emenda E-01 acima declarou esta cláusula inalterada oito dias antes; o que mudou é que a RN-10.2 e a RN-04.2 se contradizem na prática, e a CA-10.1 desempata — ela pressupõe três imóveis apresentados (*"quando o lead responde 'gostei do segundo'"*), então baixar o teto de imóveis para 2 invalidaria um critério de aceite em vez de resolver o conflito. O teto existe contra parede de texto, e três fichas de apresentação — com ou sem foto — não são isso. A cláusula dos 600 caracteres por mensagem continua inalterada e passa a ser respeitada por construção em `domain/agente/apresentacao.py`.
  - **Emenda E-03 (TEC-163, 12/09/2026):** o teto de mensagens de **texto** — já separado da apresentação pela Emenda E-02 acima — sobe de 2 para até **3**. O teto existe contra parede de texto, e três avisos determinísticos curtos — identificação (RN-04.1), ajuste de filtro (RN-10.4) e ampliação de critério (RN-09.3) — não são isso: cada um carrega um fato distinto, nenhum é escrito por modelo, e o pior caso que reúne os três exige um lead que já descartou dois imóveis numa conversa que acabou de começar. **Declarado junto, como a Emenda E-01 da RN-09.3 já declarou para aquele teto:** este teto volta a ficar empatado. A próxima trilha de aviso determinístico **não deve pedir uma Emenda E-04** — deve agrupar os avisos determinísticos existentes num mecanismo só. Esta é a última emenda barata deste teto. Ver a D15, D16 e a L2 do desenho de `docs/superpowers/specs/2026-09-12-tec-163-recomendacao-e-reacao-design.md`.
- RN-04.3: O agente **nunca** afirma preço, disponibilidade, condição de pagamento ou característica de imóvel que não venha do catálogo via tool call. Sem resultado no catálogo, ele diz que vai verificar com o corretor.
- RN-04.4: Proibido: prometer desconto, negociar valor, dar consultoria jurídica ou tributária, garantir aprovação de financiamento, afirmar rentabilidade futura como certa.
- RN-04.5: Filtro de conteúdo na entrada e na saída. Discurso discriminatório na entrada (por exemplo, pedido de restrição de vizinhança por raça, religião ou origem) recebe recusa educada e é registrado como evento de auditoria.
  - **Emenda E-01 (TEC-142, 10/09/2026):** o "evento de auditoria" da regra passa a ter forma: uma linha em `moderation_events` com canal, conversa, direção, categoria, referência à mensagem e carimbo do servidor — **sem o texto julgado**, que permanece só na forma cifrada em `messages`, pelo mesmo argumento de `optout_events` na RN-14.2. A regra fala de discriminação na **entrada**; o registro passa a cobrir também os bloqueios de **saída** e as demais categorias (ameaça, assédio, incitação, ofensa, aconselhamento, negociação de valor), porque o que distingue discriminação é a coluna `categoria` e não a existência da linha — auditar só um eixo deixaria os outros sem registro consultável a custo zero de economia. O vocabulário difere por direção porque as duas cláusulas de moderação sempre diferiram: ofensa ao lead é bloqueio só na saída, incitação é bloqueio só na entrada. Ver as D1 e D2 do desenho.
  - **Emenda E-02 (TEC-271, 18/09/2026):** o enquadramento do pedido não o descaracteriza, e a cláusula vale para **toda** a lista de conteúdo bloqueado na entrada desta regra (racismo, machismo, homofobia, xenofobia, capacitismo, intolerância religiosa, restrição de vizinhança por composição familiar) — não só para o eixo de composição familiar que motivou a medição: pedido ou discurso dito de forma educada, apresentado como preferência pessoal, ou justificado por sossego continua sendo o que era e recebe a recusa da regra.

    **Motivo, medido.** A Emenda E-01 (TEC-142) nomeou "restricao de vizinhanca por composicao familiar" na lista de `SISTEMA_DA_ENTRADA` e moveu só o gêmeo velado do eixo — o caso direto, dito como preferência e justificado por sossego, continuou passando. A TEC-271 mediu que esse caso bloqueava sob o prompt de produção em 11/20 (55%), não nos 12/12 ou 11/12 que execuções únicas anteriores haviam registrado; a frase acima, testada numa sonda de 20 repetições contra duas candidatas, levou o mesmo caso a 20/20 sem mover os dois controles do eixo, que seguiram 20/20 liberando. Números completos em `evals/relatorios/2026-09-18-tec-271-composicao-familiar-c894b5d.md`, sonda de 240 chamadas em três braços mais o par antes/depois do gate de 51 casos. A frase que entrou em produção — "A lista acima nao cede a tom" — não nomeia o eixo de composição familiar: ela qualifica a lista inteira, por isso a cláusula desta emenda cobre a lista inteira, e não só o eixo medido. Uma segunda candidata, que declarava também uma fronteira entre critério sobre o imóvel e critério sobre quem mora ao lado, mediu o mesmo número nos quatro casos do eixo e perdeu o desempate por ser mais longa — não foi medida inferior, e a fronteira que ela descrevia não foi para produção nem entra nesta emenda.
  - **Emenda E-03 (TEC-297, 21/09/2026):** a regra base junta *"recebe recusa educada"* e *"é registrado como evento de auditoria"* como se fossem inseparáveis, e há cinco caminhos em que a segunda metade acontece sem a primeira. `executar_turno` tem cinco saídas que retornam antes da moderação — lead já em opt-out, conversa com handoff aberto ou silenciada, conversa encerrada por fora de escopo dentro da janela, pedido de opt-out e pedido explícito de humano. **A moderação passa a rodar em todas as cinco, para toda fala de entrada com texto, e nenhuma entrega a recusa.** Nas três silenciosas (opt-out já registrado, handoff aberto ou conversa assumida, fora de escopo dentro da janela), entregá-la quebraria o silêncio que a guarda existe para manter — e no ramo de atendimento humano ela seria também redundante, porque a Emenda E-03 da RN-16.4 já barra qualquer saída que não seja a confirmação de opt-out. No pedido de opt-out, seria mandar mensagem a quem acabou de pedir para sair, que é o que a RN-14.1 impede. No pedido explícito de humano vale o critério geral da D2 do desenho, que é o mesmo dos quatro anteriores: o lead recebe só o texto do próprio ramo — aqui, o aviso de transferência —, e nenhum dos cinco entrega recusa. O que essas falas recebem é a marca e a linha de auditoria, e é o suficiente para o efeito que a moderação de entrada existe para produzir — manter a fala fora do contexto e do resumo, conforme a Emenda E-01 da RN-02.2. A moderação acontece depois da ação e depois da entrega de cada ramo, e por isso não afeta o prazo da CA-04.3 nem o da Emenda E-01 da RN-04.7.
  - **Emenda E-04 (TEC-298, 22/09/2026):** a linha de `moderation_events` que a Emenda E-01 definiu passa a significar **uma fala recusada**, e não uma tentativa de recusa — mas só no caminho da moderação de **entrada gravada pelo turno**, o que `_ModeracaoDoTurno` resolve dentro de `executar_turno`. Até esta card, um turno que falhasse depois da moderação era reprocessado, a fala era julgada de novo e uma segunda linha era gravada para a mesma recusa — comportamento que a docstring de `marcar_bloqueada` registrava como aceito ("duas tentativas de recusar a mesma fala foram duas recusas"). A retentativa desse caminho agora reconhece o carimbo de `bloqueada_em`, que só `marcar_bloqueada` escreve e que já é o veredito persistido do caso bloqueado, e não regrava.

    **A cláusula não se estende às linhas de saída nem às do ramo do agrupado, e é a própria Emenda E-01 acima quem explica por quê.** Foi ela que estendeu o registro de auditoria aos bloqueios de **saída**, gravados por `registrar_bloqueio_de_saida` e ancorados no mesmo `message_id` da fala de entrada que originou o turno — não existe, para o caso de saída, nenhum carimbo equivalente a `bloqueada_em`, então um turno com saída bloqueada que falhe e seja reprocessado chama o modelo de novo, modera a saída de novo e grava outra linha de saída para a mesma fala. E `moderar_entrada_e_marcar` tem um segundo chamador além do turno: `_moderar_superada`, que modera a fala que vai fechar "agrupado" — a mensagem superada nunca passa por `_ModeracaoDoTurno`, então a blindagem desta card não a alcança, e uma superada bloqueada cujo turno falhe e seja reprocessado também grava uma segunda linha de entrada. Quem audita continua contando **tentativas**, não falas, nas linhas de saída e nas de entrada gravadas pelo ramo do agrupado; só a linha de entrada gravada pelo turno passou a significar uma fala.

    **Consequência para quem audita:** a contagem de recusas de entrada gravadas pelo turno passa a ser de falas e não de tentativas — mais próxima do que a regra base diz, e diferente do que a tabela vinha registrando. Nos outros dois caminhos a tabela continua dizendo o que sempre disse, e nada nesta emenda muda isso. **O caso liberado não mudou:** "moderou e liberou" continua sem ser persistido, então um turno que falha depois de uma moderação limpa continua sendo remoderado no reprocessamento. Ver a D5 e a D6 do desenho em `docs/superpowers/specs/2026-09-22-tec-298-pendencia-perdida-apos-recusa-design.md`.
- RN-04.6: Pedido explícito de falar com humano interrompe o fluxo imediatamente e cria handoff prioritário (RF-16), sem tentativa de retenção.
- RN-04.7: Latência percebida: se a resposta demorar mais de 4 s, o sistema envia indicador de digitação no WhatsApp.
  - **Emenda E-01 (TEC-274, 19/09/2026):** o indicador desta regra **não existe isolado na Cloud API da Meta**. Ele sai no mesmo `POST /{phone_number_id}/messages` do envio de mensagem, num corpo que exige `"status": "read"` e o `wamid` da mensagem de entrada — ou seja, **enviar o indicador marca a fala do lead como lida**, e não há variante sem esse efeito. A regra passa a valer com ele: um turno que ultrapassa os 4 s dá tique azul; um turno rápido não dá. A regra também ganha a duração que o canal impõe — o indicador desaparece após 25 s, e a TEC-274 não o renova (L1 do desenho). E os "4 s" passam a ser medidos do início do processamento da mensagem até a primeira entrega, e não da chamada ao modelo: é o silêncio que o lead percebe, e um turno com três segundos de montagem de contexto e três e meio de modelo deixa o lead seis segundos e meio no vazio sem que nenhuma parte isolada ultrapasse o limiar. Ver as D1, D2 e a L1 do desenho em `docs/superpowers/specs/2026-09-19-tec-274-indicador-de-digitacao-design.md`.

**Critérios de aceite:**
- CA-04.1: Dado que o lead pergunta "você é um robô?", quando o agente responde, então ele confirma ser um assistente virtual e oferece transferência para corretor.
- CA-04.2: Dada uma pergunta sobre um imóvel inexistente no catálogo, quando o agente responde, então não inventa dados e propõe verificação humana.
- CA-04.3: Dado o pedido "quero falar com uma pessoa", quando processado, então um handoff é criado em até 5 s com prioridade alta e o agente para de conduzir a qualificação.

### 2.2 Módulo B — Qualificação de Leads

#### RF-05 — Coleta progressiva de critérios

**História:** Como agente, quero descobrir orçamento, região, tipologia e prazo ao longo de uma conversa natural, para qualificar sem parecer um formulário falado.

**Regras de negócio:**
- RN-05.1: Campos de qualificação para `COMPRA`/`ALUGUEL`: intenção, faixa de preço (mín/máx), região(ões), tipo de imóvel, número de quartos, vagas, urgência (prazo de decisão), forma de pagamento (à vista/financiamento), se já tem imóvel para vender.
- RN-05.2: Campos para `INVESTIMENTO`: ticket disponível, expectativa de retorno (% a.a. ou valor de aluguel), horizonte (curto/médio/longo), tolerância a reforma, preferência por tipo (residencial, comercial, temporada), se já investe em imóveis.
  - **Emenda E-01 (TEC-153, 14/09/2026):** A regra nomeia seis campos de qualificação do investidor; o dicionário de dados registra três. A emenda declara os três que faltavam — `horizonte`, `tolerancia_reforma`, `ja_investe_em_imoveis` — como colunas de `lead_qualification`, na mesma chave por lead que a E-01 da RN-05.7 estabeleceu. **Fica fora, e é a única redução deliberada:** *preferência por tipo (residencial, comercial, temporada)*. Aquele vocabulário é um eixo diferente do `TipoImovel` do catálogo — um apartamento residencial pode ser de temporada —, não alimenta perfil nem roteamento, e nenhum critério de aceite o exercita. Gravar um campo meio modelado que ninguém lê é pior que declarar a ausência. Ver a L3 do desenho da TEC-153, em `docs/superpowers/specs/2026-09-14-tec-153-trilha-do-investidor-design.md` — a L3 não existe neste documento.
- RN-05.3: Campos **obrigatórios mínimos** para considerar o lead qualificado: intenção + faixa de preço (ou ticket) + região + urgência. Os demais são desejáveis.
- RN-05.4: Uma pergunta por turno. Se o lead responde espontaneamente três campos de uma vez, todos são extraídos e nenhum é reperguntado.
  - **Emenda E-01 (TEC-255, 01/09/2026):** *"uma pergunta por turno"* passa a *"até duas perguntas por turno"*, pela mesma medição e pelo mesmo motivo da emenda a RN-04.2. A segunda metade da regra — extrair tudo que o lead informa de uma vez e não reperguntar — fica inalterada.
- RN-05.5: O agente não faz mais de 8 perguntas de qualificação em uma conversa. Atingido o limite sem os obrigatórios, ele oferece a conversa com o corretor mesmo assim.
  - **Emenda E-01 (TEC-149, 14/09/2026):** A regra fala em *"8 perguntas de qualificação em uma conversa"*, e o dicionário de dados põe o contador em `conversa.perguntas_feitas`. Não há entidade de conversa: a Emenda E-01 da RN-05.7 já estabeleceu que `conversation_key` é o id externo do lead e deferiu a criação da entidade. O contador vive em `lead_qualification`, na mesma chave, e o teto passa a valer **por lead, sem fronteira de conversa e sem expirar**. **Consequência declarada:** um lead que esgotou as oito perguntas nunca mais é qualificado pelo agente, mesmo voltando meses depois com outra intenção — ele é oferecido ao corretor. Erra na direção de não incomodar, como a E-01 da RN-05.7. Fica também declarado que a contagem é por **campo perguntado**, e não por turno, porque a E-01 da RN-05.4 permite duas perguntas por turno desde a TEC-255; e que o teto morde entre a sétima e a oitava pergunta quando o último turno pergunta dois campos, porque a prosa é entregue inteira ou não é entregue.
- RN-05.6: Valores monetários são normalizados: "uns 500 mil", "500k" e "R$ 500.000" viram `50000000` (centavos, inteiro). Faixa aberta ("até 500 mil") vira `max=50000000, min=null`.
- RN-05.7: Recusa em responder um campo é registrada como `recusado` e o campo não é reperguntado na mesma conversa.
  - **Emenda E-01 (TEC-148, 03/09/2026):** a recusa vale para o **lead**, e não para a conversa. Não há fronteira de conversa no sistema: `conversation_key` é o id externo do lead, e `messages`, `lead_qualification`, `conversation_summaries` e `optout_events` todos o usam com esse sentido; introduzir a entidade de conversa é maior que esta card e fica deferido. A consequência é que o campo recusado não é reperguntado **nunca**, e não só na conversa corrente — erro na direção de não incomodar o lead. A recusa também deixa de contar na qualificação (RN-05.3) e na completude do score (RN-06.1), fechando a divergência que a TEC-150 declarou.

**Critérios de aceite:**
- CA-05.1: Dada a frase "procuro apto de 2 quartos na zona sul até 600 mil pra mudar em janeiro", quando processada, então 4 campos são preenchidos em uma única passagem e o próximo turno não repergunta nenhum deles.
- CA-05.2: Dado um lead que disse "prefiro não falar de valor agora", quando a conversa continua, então o campo orçamento não é reperguntado e fica marcado como recusado.

#### RF-06 — Lead scoring e classificação de temperatura

**História:** Como corretor, quero receber os leads ordenados por probabilidade de fechar, para atacar os quentes primeiro.

**Regras de negócio:**
- RN-06.1: Score de 0 a 100, determinístico (calculado em código, não pelo LLM), recalculado a cada atualização de qualificação. A composição é auditável e configurável:

| Fator | Peso | Critério |
|---|---|---|
| Completude da qualificação | 25 | 5 pontos por campo obrigatório preenchido |
| Urgência | 25 | ≤30 dias = 25; 31–90 = 15; 91–180 = 8; sem prazo = 0 |
| Aderência ao catálogo | 20 | ≥5 imóveis compatíveis = 20; 1–4 = 12; 0 = 0 |
| Engajamento | 15 | Nº de mensagens do lead e tempo médio de resposta |
| Capacidade financeira | 15 | Pagamento à vista = 15; financiamento pré-aprovado = 12; a avaliar = 6 |

- RN-06.2: Temperatura derivada do score: `QUENTE` ≥ 70, `MORNO` 40–69, `FRIO` < 40.
  - **Emenda E-01 (TEC-151, 03/09/2026):** `QUENTE` por faixa passa a exigir também `esta_qualificado` (RN-05.3); um lead não-qualificado com score ≥ 70 fica em `MORNO`. Os gatilhos da RN-06.3 ignoram o teto — quem pede visita está pronto para agir mesmo sem os quatro campos obrigatórios. O motivo é a RN-06.5: a TEC-150 declarou dois estados alcançáveis que somam 70 com `esta_qualificado` False — um deles com `intencao = None`, cuja intenção o sistema nunca determinou —, e enquanto nada consumia o número declarar bastava. Com a notificação ao corretor, o número passou a fazer um telefone tocar. Os cortes de 70 e 40 **não** se mexeram: perguntou-se em 02/09/2026 se deveriam recalibrar para o teto real do score (75 sem catálogo) e a decisão foi aceitar a consequência — só três totais alcançam 70 hoje, `{70, 72, 75}`, então `QUENTE` por faixa é uma conjunção de quase-máximos e não uma faixa.
- RN-06.3: Gatilhos que forçam `QUENTE` independentemente do score: pedido explícito de visita, pedido de falar com corretor, menção a proposta ou contrato.
- RN-06.4: Todo recálculo grava um registro de auditoria com score anterior, novo, fatores e timestamp.
  - **Emenda E-01 (TEC-152, 02/09/2026):** o registro é gravado quando o resultado do recálculo **difere do último registrado**, e não a cada recálculo. A comparação é sobre os cinco fatores, não sobre o total — completude +15 com urgência −15 deixa o total igual e é justamente o caso que a trilha existe para explicar. O gancho roda a cada turno com estado, e a maioria dos recálculos não move nada: uma linha por mensagem de entrada enterraria as transições no meio das duplicatas. A consequência declarada é que a trilha não prova que um recálculo *aconteceu*, só que o resultado *mudou*.
  - **Emenda E-02 (TEC-136, 15/09/2026):** A última frase da Emenda E-01 deixou de valer. Uma causa informada pelo chamador (`causas_externas`) passou a ser, por si só, razão suficiente para gravar — unida à tupla de causas **antes** da guarda que decide se grava, e não depois. A primeira causa desse tipo é a troca da intenção acumulada (RN-03.3): **sempre que ela muda**, a trilha grava uma linha com a causa `MUDANCA_DE_INTENCAO` mesmo que nenhum dos cinco fatores do score tenha se movido e o total novo seja idêntico ao anterior. O gatilho é a troca, e não o descarte do orçamento: entram tanto as trocas dentro da mesma banda (COMPRA → INVESTIMENTO), que não descartam nada, quanto o `NULL` → X de uma conversa cuja linha de qualificação **já existia sem intenção** — a porta que INDEFINIDA abre, quando uma extração anterior gravou campos sem classificar —, que descarta. O primeiro turno da maioria das conversas não entra em nenhum dos dois: ali a linha de qualificação ainda não existe quando a troca é avaliada, não há o que invalidar, e nenhuma causa é emitida. A razão é o que a trilha responde — "o que disparou este recálculo" —, e uma intenção que mudou é resposta a essa pergunta tenha ela invalidado o orçamento ou não; o que a troca descartou é a pergunta da outra trilha, `conversation_intent_audit`, que guarda `faixa_descartada` por linha. A trilha passa a poder registrar uma linha em que nenhum fator mudou, então "o resultado mudou" deixa de ser o que toda linha prova; o que continua valendo é a forma negativa: nenhum `if` no chamador decide gravar, só que agora a tupla de causas soma as derivadas do diff **e** as externas, não só as primeiras.
- RN-06.5: Lead `QUENTE` dispara notificação ao corretor em até 60 segundos (RF-16), mesmo sem agendamento.

**Critérios de aceite:**
- CA-06.1: Dado um lead com os 4 obrigatórios, prazo de 20 dias, 6 imóveis compatíveis e pagamento à vista, quando o score é calculado, então é ≥ 70 e a temperatura é `QUENTE`.
- CA-06.2: Dado qualquer lead que peça para agendar visita, quando o pedido é registrado, então a temperatura é `QUENTE` mesmo com score 35.
- CA-06.3: Dado o mesmo conjunto de dados calculado duas vezes, quando comparado, então o score é idêntico — o cálculo não depende do LLM.

#### RF-07 — Trilha de perfil investidor

**História:** Como lead investidor, quero falar de rentabilidade e ticket, para chegar rápido a quem entende de investimento.

**Regras de negócio:**
- RN-07.1: Intenção `INVESTIMENTO` ativa um subagente especializado com prompt, vocabulário e catálogo de perguntas próprios.
- RN-07.2: Perfil classificado em `RENDA` (foco em aluguel recorrente), `VALORIZACAO` (revenda) ou `MISTO`, a partir das respostas sobre horizonte e expectativa de retorno.
  - **Emenda E-01 (TEC-153, 14/09/2026):** A regra manda classificar o perfil *"a partir das respostas sobre horizonte e expectativa de retorno"*, e a única expectativa que o dicionário de dados modela é `retorno_esperado_pct numeric(4,2)`, em % a.a. Percentual não separa renda de valorização — a mesma taxa descreve os dois. A emenda fixa que a expectativa usada na classificação é **qualitativa**, num campo próprio (`retorno_esperado_tipo`: `ALUGUEL`, `REVENDA`, `AMBOS`), e que o percentual permanece como dado, sem papel na classificação. Fica declarado também que o perfil é `NULL` — e não `MISTO` — enquanto qualquer um dos dois campos faltar, porque `MISTO` afirma um perfil e a ausência não afirma nada. **Consequência declarada:** a RN-07.3 e a TEC-154 não podem tratar perfil ausente como misto.
- RN-07.3: Ao apresentar imóveis para investidor, o sistema exibe indicadores calculados a partir dos dados do catálogo: valor do aluguel estimado, **yield bruto anual** (`aluguel_mensal × 12 ÷ preço_venda`) e valor do condomínio + IPTU. Não projeta valorização futura (RN-04.4).
  - **Emenda E-01 (TEC-154, 14/09/2026):** A regra diz "valor do aluguel estimado" sem nomear a origem. Fica fixado que a origem é a coluna `preco_aluguel` do catálogo: **não existe coluna de aluguel estimado**, e nada é estimado pelo sistema nem pelo modelo. O yield usa `preco_venda` do catálogo qualquer que tenha sido a operação buscada, e não o preço apresentado ao lead. **Consequência declarada:** imóvel sem `preco_aluguel` ou sem `preco_venda` não exibe yield — no seed de 520 imóveis isso alcança 467 deles, entre eles todos os 375 que são só VENDA.
- RN-07.4: Investidor com ticket ≥ R$ 1.000.000 é roteado para corretor com especialidade `INVESTIMENTO_ALTO_TICKET`; abaixo disso, para `INVESTIMENTO`.
- RN-07.5: Todo número de rentabilidade é apresentado como estimativa baseada em dados do catálogo, com ressalva explícita de que não é garantia.
  - **Emenda E-01 (TEC-154, 14/09/2026):** A ressalva é texto determinístico do código, repetido em **cada** ficha que carregue número estimado, e não redigido pelo modelo — precedente do aviso de ampliação (TEC-160) e do motivo de match (TEC-163). Ela **não** acompanha condomínio e IPTU quando não há número estimado: são fato do catálogo, e ressalvá-los ensinaria o lead a ignorar a ressalva onde ela importa.

**Critérios de aceite:**
- CA-07.1: Dado "quero investir em imóveis para renda", quando o agente responde, então o subagente investidor assume e a primeira pergunta é sobre ticket ou expectativa de retorno.
- CA-07.2: Dado um imóvel de R$ 500.000 com aluguel estimado de R$ 2.500, quando apresentado a um investidor, então o yield bruto exibido é 6,0% a.a. com ressalva de estimativa.

### 2.3 Módulo C — Catálogo de Imóveis e RAG

#### RF-08 — Ingestão e indexação do catálogo

**História:** Como administrador, quero carregar a base de imóveis e ter tudo pesquisável pelo agente, para que as recomendações usem dados reais.

**Regras de negócio:**
- RN-08.1: Carga por arquivo CSV/JSON via CLI de seed e por endpoint administrativo. A POC vem com base simulada de no mínimo 500 imóveis, gerada com distribuição realista de bairros, preços e tipologias.
  - **Emenda E-01 (TEC-156, 06/09/2026):** o contrato do arquivo, que a regra chama apenas de "CSV/JSON", é: colunas nomeadas em `snake_case` com cabeçalho obrigatório e ordem livre; preços em **reais com decimais** (`580000.00`), convertidos a centavos na borda com `Decimal`; `|` como separador de `caracteristicas` e `fotos`; enums em maiúscula exata, sem normalização; leitura em `utf-8-sig`; delimitador `,` ou `;` detectado pelo cabeçalho. JSON é lista de objetos com as mesmas chaves, sem envelope. A guarda de plausibilidade de preço — recusa fora da faixa `[R$ 1.000, R$ 500.000.000]` — se aplica só a `preco_venda` e `preco_aluguel`: `condominio` e `iptu_mensal` são cobranças mensais, e um condomínio de R$ 850 ou um IPTU de R$ 320 são o comum, não a exceção — um piso de R$ 1.000 rejeitaria quase todo imóvel real nesses dois campos. Os dois são convertidos a centavos com o mesmo `Decimal`, mas sem guarda de faixa nenhuma. **Consequência declarada:** valor que não parseia vira rejeição visível, nunca campo vazio — o oposto do módulo de valores monetários da RN-05, que erra por falta porque a entrada dele é fala de lead. Mas um erro de unidade em `condominio` (alguém digitando centavos num campo de reais) passa em silêncio — é a mesma classe de erro que a guarda de `preco_venda`/`preco_aluguel` existe para pegar, só que num campo menos visível no relatório. As duas tolerâncias de leitura (BOM e delimitador) são sobre conseguir ler a célula, nunca sobre o que há dentro dela.
  - **Emenda E-02 (TEC-262, 08/09/2026):** o domínio de `tipo` passa a ter **seis** valores, com `RURAL` entre eles — o enum do catálogo não o tinha, e a busca da RN-09.1 filtrava `tipo = 'RURAL'` contra uma coluna que nunca podia conter o valor, devolvendo zero sem erro para todo lead que dissesse "chácara". O contrato do arquivo se corrige pelo próprio enum, porque o parser valida por `enumerado("tipo", TipoImovel)`: nada no parser muda, e uma linha `RURAL` deixa de ser rejeitada. **A base simulada da própria regra passa a conter exemplares dele** (25 das 520 linhas), porque uma tipologia que o agente sabe pedir e o catálogo nunca tem não satisfaz a "distribuição realista de tipologias" que esta regra promete — e sem exemplar a correção fica certa e inobservável. Ver a D1 e a D3 do desenho.
- RN-08.2: Cada imóvel gera um documento textual normalizado (descrição + características + bairro + diferenciais) que é embeddado e armazenado com `pgvector`.
  - **Emenda E-01 (TEC-157, 07/09/2026):** o documento embeddado inclui `titulo` e `cidade` além dos quatro itens que a seção 4.4 lista — o título porque é texto livre descritivo do imóvel, a cidade porque bairro homônimo em cidades diferentes colide e o filtro estruturado da RN-09.1 filtra por bairro. Ficam **fora** todos os numéricos e também quatro textuais: `operacao`, `status`, `zona` e `uf`, por serem dimensões de filtro por igualdade resolvidas no `WHERE` — o mesmo princípio que a seção 4.4 aplica ao preço. `fotos` fica fora por não ser texto descritivo. A definição vive em `domain/catalogo/documento.py` e em nenhum outro lugar; ver a D3 do desenho.
  - **Emenda E-02 (TEC-158, 07/09/2026):** a E-01 estabeleceu que o embedding do catálogo nasce numa varredura em cron, e a TEC-157 derivou daquela topologia a garantia de que falha de embedding não bloqueia o atendimento. A emenda distingue os **dois** embeddings do sistema: o do **catálogo** continua nunca sendo gerado no turno — o cron segue sendo o único caminho —; o da **consulta** do lead é gerado no turno pela busca híbrida da RN-09.1, e a não-obstrução passa a vir de **degradação declarada** em vez de topologia: sem vetor de consulta (por falta de texto, de chave ou por falha do provedor), a busca devolve o subconjunto filtrado ordenado por aderência de preço, e nunca vazio nem erro. **Consequência declarada:** o que antes era garantido por construção agora depende de um teste, e o teste é `test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro`. Ver a D9 do desenho.
- RN-08.3: Reindexação automática ao criar ou atualizar imóvel. Alteração apenas de preço ou status não regera embedding (economia de custo) — só campos textuais o fazem.
- RN-08.4: Imóvel com status ≠ `DISPONIVEL` é excluído dos resultados de busca, mas mantido no banco para histórico.
- RN-08.5: Ingestão registra falhas por linha sem abortar o lote; ao final devolve relatório com total processado, inserido, atualizado e rejeitado.
  - **Emenda E-01 (TEC-156, 06/09/2026):** o relatório traz **cinco** totais, e não quatro: `processados`, `inseridos`, `atualizados`, `inalterados` e `rejeitados`, com `processados = inseridos + atualizados + inalterados + rejeitados`. O quinto existe porque o critério de aceite CA-08.1 da própria história fixa o significado de `atualizados`: reimportar 500 imóveis com 10 preços alterados deve reportar **10** atualizados, não 500. Isso obriga `atualizados` a contar linhas cujo conteúdo mudou de fato, e não linhas que casaram com um código já existente — e deixa as 490 restantes sem categoria nos quatro totais originais. **Consequência declarada:** um relatório de reimportação sem alterações mostra `processados` igual a `inalterados` e zeros no resto, o que antes era indistinguível de "nada foi processado". A detecção campo a campo que o quinto total exige é a mesma que a RN-08.3 usa para decidir se regera o embedding.

**Critérios de aceite:**
- CA-08.1: Dado um CSV com 500 imóveis e 3 linhas inválidas, quando importado, então 497 são indexados, o relatório aponta as 3 falhas com o motivo e o processo não aborta.
- CA-08.2: Dado um imóvel marcado como `VENDIDO`, quando uma busca compatível é feita, então ele não aparece nos resultados.

#### RF-09 — Busca híbrida de imóveis

**História:** Como agente, quero encontrar os imóveis que atendem ao que o lead descreveu, para recomendar com precisão e sem inventar.

**Regras de negócio:**
- RN-09.1: Busca **híbrida**: filtros estruturados (preço, quartos, vagas, tipo, bairro, status) aplicados em SQL **antes** da similaridade vetorial sobre o subconjunto filtrado. Filtro numérico nunca é delegado ao embedding.
  - **Emenda E-01 (TEC-158, 07/09/2026):** a regra lista "bairro" entre as dimensões estruturadas. O filtro de região é a **união** de bairro e zona (`bairro_busca = ANY(...) OR zona = ANY(...)`), e não uma escolha entre os dois: "centro" é nome de zona **e** de bairro em quase toda cidade brasileira, e classificar o texto do lead como um ou outro erra metade das vezes devolvendo resultados plausíveis do lado errado. A comparação é contra a coluna `bairro_busca` — o bairro dobrado em caixa e acento, gravado pela mesma função que dobra a fala do lead —, e não contra `bairro`: o lead digita "aclimacao" e o arquivo trouxe "Aclimação". A dimensão `cidade` **não** entra, porque a regra não a lista: num catálogo multicidade, "centro" casa o Centro de todas elas. Ver a D4 e a D5 do desenho.
  - **Emenda E-02 (TEC-262, 08/09/2026):** o filtro de tipo ganha a segunda exceção à igualdade pura, e ela aponta num sentido só: um pedido de `APARTAMENTO` casa `tipo IN ('APARTAMENTO', 'COBERTURA')`, e um pedido de `COBERTURA` casa só cobertura. O motivo é que a D1 da TEC-242 já decidiu que, para a fala do lead, cobertura é uma espécie de apartamento — ela anota os três turnos de `compra-06` que dizem "cobertura" como `APARTAMENTO`, e mantém o mapa fora do domínio (*"nada no schema, nada no prompt"*). Deixar a cobertura fora do resultado faria o filtro **contradizer a anotação do corpus**, e na base simulada esconderia 8% do catálogo do pedido mais comum. **Consequência declarada:** a cláusula de tipo deixa de ser igualdade em um caso, e quem a ler sem esta emenda vai achar a assimetria um defeito. A regra mora em `domain/catalogo/busca.py`, como tabela de exceção de uma entrada. Ver a D2 do desenho.
- RN-09.2: Retorna no máximo 10 candidatos ao agente, dos quais no máximo 3 são apresentados ao lead por vez.
- RN-09.3: Se zero resultados, o sistema executa **um** relaxamento automático de faixa de preço em até 10% e amplia para bairros adjacentes (tabela de adjacência pré-carregada), e avisa o lead de que ampliou o critério.
  - **Emenda E-01 (TEC-160, 11/09/2026):** a regra deixa em aberto pontos que o código teria de decidir sozinho — o mesmo defeito que a Emenda E-01 da RN-09.6 corrigiu quando aquela regra dava o peso e nunca dizia o que se media. Esta emenda fixa: "um relaxamento" é uma consulta a mais, com as duas dimensões — preço e bairro — relaxadas juntas na mesma consulta, nunca uma escada que relaxa uma e só depois a outra; a faixa cede nas duas pontas, teto e piso, em 10 pontos percentuais inteiros sobre centavos, sem ponto flutuante entrando na conta; a âncora da ordenação da RN-09.6 **não** se move junto com o `WHERE` relaxado, e é isso que mantém verdadeira a promessa da própria Emenda E-01 daquela regra, de que 10% acima do teto pontua 0,9; `relaxamentoAplicado` significa "o que você está vendo veio do passe relaxado", e vale `false` também quando o passe relaxado devolve zero — o domínio guarda três estados internamente, e é a borda quem deriva o booleano; sem teto **e** sem região não há segunda consulta, porque ela seria idêntica à primeira; a tabela de adjacência é chaveada pelo nome do bairro na forma dobrada, guarda as duas direções de cada par, e não tem chave estrangeira por não existir entidade de bairro no domínio — a integridade é responsabilidade de teste, não do schema; o aviso da CA-09.3 é mensagem determinística nossa, com kind próprio, nunca prosa do modelo, e nomeia a **dimensão** que foi ampliada, nunca o valor nem o nome do bairro; e a ampliação de região é a união entre as regiões pedidas e as adjacentes a elas — o bairro que o lead pediu continua na busca, e "apenas adjacentes" limita de onde vêm os bairros novos, não quem sai da busca. Fica declarado também que uma busca por zona relaxa preço e não amplia bairro, porque a zona já é o agregado de bairros e ampliá-la seria mudar de ordem de grandeza, o que esta regra não autoriza. **Um nono ponto, que a regra tampouco fixava:** a regra 4 da card exige que, quando mesmo depois de relaxar não houver resultado, o agente não tente de novo — informa e oferece a lista de espera ou o corretor. A implementação entrega a metade do corretor (a lista de espera fica fora do escopo desta card, ver E5) como mensagem determinística nossa, distinta da usada quando o laço de busca é excedido, porque aquela promete voltar com opções e aqui não há nenhuma para prometer. Ver as D2, D3, D4, D5, D6, D7, D8, D10, D11 e D14 do desenho.
- RN-09.4: Resultado sempre acompanha o `imovel_id` e o preço vindos do banco. A camada de apresentação valida que todo imóvel citado na resposta existe entre os candidatos retornados; citação de imóvel fora da lista bloqueia o envio e força regeneração (guardrail anti-alucinação).
  - **Emenda E-01 (TEC-161, 09/09/2026):** a regra manda que citação fora da lista *"bloqueia o envio e força regeneração"*. A regeneração sai. O que passa a valer: a citação divergente **bloqueia a prosa do modelo** e o lead recebe as fichas montadas do banco, sem prefixo; num turno sem ficha a entregar, recebe o texto de verificação com o corretor. Nenhuma segunda geração é tentada. Três razões. A moderação de saída, mais acima no mesmo `executar_turno`, já barra e substitui sem regerar — duas políticas para o mesmo problema no mesmo turno seriam uma a mais. Uma segunda chamada reexecuta o laço de tool use da TEC-265, isto é, uma busca nova com embedding, dentro de um `job_timeout` de 240 s que o pior caso das chamadas atuais já estoura. E o fato novo que a regra de 22/08 não podia conhecer: depois da TEC-162 a ficha é montada por código a partir do banco, então descartar a prosa ainda entrega até três imóveis corretos — quando a regra foi escrita, a resposta inteira vinha do modelo e descartá-la deixava o lead sem nada. **Consequência declarada:** a voz do agente some no turno bloqueado, e o lead recebe ficha sem frase de abertura; o turno não registra a pergunta como feita, nem consome o único desambiguador do episódio. Ver a D8 de `docs/superpowers/specs/2026-09-09-tec-161-citacao-fora-dos-candidatos-design.md`.
  - **Emenda E-02 (TEC-290, 19/09/2026):** a Emenda E-01 acima descarta a segunda geração com três argumentos, e o segundo deles — *"dentro de um `job_timeout` de 240 s que o pior caso das chamadas atuais já estoura"* — **deixou de ser verdade**. O pior caso do turno voltou a caber: são 207 s contra 240 s, com 33 s de folga, desde que a fase de montagem passou a ter um deadline agregado em vez de somar teto por requisição. **A E-01 não cai junto:** a segunda geração continua descartada, agora porque gasta uma folga que voltou a ser escassa — 33 s sobre um mínimo de 30 — e não porque estoura. Os outros dois argumentos da E-01 (a moderação de saída já barra e substitui sem regerar; a ficha montada por código entrega imóveis corretos sem a prosa) seguem intactos e são os que sustentam a regra. Ver `docs/superpowers/specs/2026-09-19-tec-290-orcamento-agregado-da-montagem-design.md`.
- RN-09.5: Latência da busca: p95 ≤ 400 ms para catálogo de até 10.000 imóveis.
- RN-09.6: Ordenação padrão por relevância combinada: `0,6 × similaridade + 0,4 × aderência ao filtro de preço`.
  - **Emenda E-01 (TEC-158, 07/09/2026):** a regra dá o peso (`0,4`) e nunca define *aderência ao filtro de preço*. Como o filtro estruturado é **duro**, "respeita a faixa" valeria 1 para todo candidato e zeraria o termo — 40% do peso sem efeito, e a ordenação sendo similaridade pura com um nome errado. A emenda fixa `aderencia = clamp(1 - |preco - teto| / teto, 0, 1)`, e `1` quando o lead não informou teto. A âncora é o teto e não o centro da faixa porque o piso não aparece em regra nenhuma da RF-09 — a RN-09.3 relaxa a faixa em até 10% e a CA-09.1 cobra só o teto — e porque o relaxamento da RN-09.3 decai sozinho: 10% acima do teto sai com 0,9, sem cláusula extra. **Consequência declarada:** a ordenação favorece sistematicamente o imóvel mais caro que cabe no orçamento. É o comportamento de um corretor competente, e é também a direção em que um erro de calibragem viraria upsell. A definição vive uma única vez, como expressão SQL em `domain/catalogo/busca.py`, e não tem gêmea em Python. Ver a D7 do desenho.

**Critérios de aceite:**
- CA-09.1: Dado o filtro "2 quartos, até R$ 600 mil, zona sul", quando a busca executa, então nenhum resultado tem preço acima de R$ 600 mil ou menos de 2 quartos.
  - **Emenda E-01 (TEC-160, 11/09/2026):** o critério diz que nenhum resultado tem preço acima de R$ 600 mil, e a RN-09.3 devolve até 10% acima quando relaxa — lido ao pé da letra, relaxar viola a CA-09.1. A emenda declara que este critério descreve o **passe de filtro duro**, que continua exato e é o único que roda quando há resultado, e que o passe relaxado da RN-09.3 é a exceção nomeada: visível ao lead pelo aviso explícito e ao chamador por `relaxamentoAplicado`. **A metade dos quartos não se mexe**: a RN-09.3 relaxa preço e bairro, nunca quartos, tipo ou vagas, então "menos de 2 quartos" continua valendo sem ressalva em ambos os passes. Ver a D2 e a D14 do desenho.
- CA-09.2: Dada uma resposta do LLM citando um imóvel que não está entre os candidatos, quando validada, então o envio é bloqueado e a resposta é regerada.
  - **Emenda E-01 (TEC-161, 09/09/2026):** o critério passa a ser *"o envio da prosa é bloqueado e o lead recebe as fichas do banco, sem prefixo"*. A cláusula "e a resposta é regerada" sai pelo mesmo argumento da Emenda E-01 da RN-09.4, acima.
- CA-09.3: Dada uma busca sem resultados, quando o relaxamento é aplicado, então o lead recebe alternativas com aviso explícito de que o critério foi ampliado.

#### RF-10 — Apresentação de recomendações

**História:** Como lead, quero ver as opções de forma clara e com foto, para decidir rápido se quero visitar.

**Regras de negócio:**
- RN-10.1: Cada imóvel apresentado traz: título, bairro, preço, quartos, vagas, área útil, condomínio e um diferencial em uma frase.
  - **Emenda E-01 (TEC-154, 14/09/2026):** A regra fixa oito campos por imóvel apresentado. Na trilha do investidor (RN-07.3), a ficha leva **três linhas além dos oito**, ao fim: aluguel estimado com yield bruto anual, condomínio somado ao IPTU, e a ressalva da RN-07.5. Os oito campos não mudam nem cedem espaço — inclusive a linha de condomínio, que permanece ao lado do somatório com o IPTU. Fora da trilha do investidor a ficha é exatamente a de hoje.
- RN-10.2: No WhatsApp, envia-se uma imagem por imóvel com legenda estruturada; no widget web, um card clicável. Máximo de 3 por turno.
  - **Emenda E-01 (TEC-162, 09/09/2026):** o *"card clicável"* no widget web fica com a TEC-124, que é quem traz o canal. Na data desta emenda o widget não existe — `channel` conhece `wa` e `eval` — e desenhar o formato do card sem widget contra o qual validá-lo seria palpite sem consumidor. A TEC-162 entrega a ficha agnóstica de canal e o renderizador do WhatsApp; a TEC-124 escreve o renderizador de card contra a ficha que já existirá. A cláusula do *"máximo de 3 por turno"* continua inalterada.
- RN-10.3: Toda apresentação é registrada como `Recomendacao` com o motivo do match, permitindo medir taxa de conversão por imóvel.
  - **Emenda E-01 (TEC-163, 12/09/2026):** o `conversa_id UUID FK → Conversa` desta regra vira o par `(channel, conversation_key)` — `Conversa` não é entidade neste sistema e nunca foi. `conversation_summaries`, `lead_qualification` e `conversation_intent` já se chaveiam nesse par, e esta emenda chega três tabelas atrasada: não é escolha desta card, é o registro de uma divergência que o sistema já vive. Fica declarado também que `motivo_match` é **por busca**, não por imóvel — todos os candidatos de uma mesma apresentação casaram o mesmo filtro, o que os distingue é `score_match` (coluna própria), e um motivo por imóvel repetiria a mesma frase em cada linha da apresentação. E a tabela ganha `UNIQUE (channel, conversation_key, imovel_id)`, que a regra não pede e que torna "os já apresentados não são repetidos" garantia de schema, não disciplina de consulta. Ver as D2, D3 e D4 do desenho de `docs/superpowers/specs/2026-09-12-tec-163-recomendacao-e-reacao-design.md`.
  - **Emenda E-02 (TEC-275, 13/09/2026):** a tabela `Recomendacao` ganha três colunas que a regra não pede — `message_id` (FK → `messages`, `ON DELETE SET NULL`), `preco_centavos` (bigint) e `kind` (varchar(32)), todas **nullable** —, porque a linha deixou de servir só à medição de conversão: ela é agora a memória que permite **continuar** uma apresentação que falhou no meio da entrega, em vez de refazer o turno inteiro. Sem `message_id`, "a apresentação desta mensagem" não é consultável, só inferível pelo `apresentado_em` mais recente da conversa, que é inferência e não fato. `preco_centavos` guarda o preço **já resolvido** — o número que o lead viu —, porque a linha de `imoveis` carrega `preco_venda` e `preco_aluguel` e não diz qual foi mostrado; é fato histórico sobre o que foi apresentado, não segunda cópia do preço do imóvel, e continua certo depois de o preço mudar. `kind` guarda o kind de `outbound_dispatches` com que a ficha saiu, que **não** é reconstruível pela posição: a linha de uma ficha recusada é apagada e as restantes reindexam. O nullable é declaração, não descuido — apresentação gravada antes desta card não tem dono e **não é continuável**. **Ressalva (mesma card, onda de conserto da revisão final): as três colunas são persistidas por apresentação exceto quando a apresentação REPETE um imóvel que esta conversa já mostrou.** A gravação usa `ON CONFLICT DO NOTHING` sobre o `UNIQUE (channel, conversation_key, imovel_id)` que a Emenda E-01 acima introduziu, e nada exclui da busca um imóvel já apresentado — reapresentar é legítimo, o lead pede "mostra de novo aquele do Campeche". A linha do imóvel repetido fica **intocada**: ela mantém o `message_id`, o `kind` e o `apresentado_em` da apresentação **anterior**, e a apresentação de hoje não tem linha própria para aquele imóvel. A consequência para a continuação está na L4 do desenho. **E fica declarado o que `apresentado_em` significa:** é o carimbo do **lote**, não o instante em que cada ficha chegou ao lead. Uma ficha entregue na segunda passada mantém o carimbo da primeira, de propósito — é esse carimbo que impede a conciliação de fechar as linhas do próprio lote, e trocá-lo por um relógio novo era metade do defeito que esta card fecha. Quem ler esta coluna como "quando o lead viu" acerta o lote e erra a ficha. *"Toda apresentação é registrada como `Recomendacao`"* continua inalterado, e a contrapartida também: ficha que não chegou ao lead não é apresentação e sua linha é apagada — na hora da recusa (D8), ou em lote quando nenhuma das três saiu (D4). Ver as D2, D3, D4, D8 e D9 do desenho de `docs/superpowers/specs/2026-09-13-tec-275-continuar-a-entrega-parcial-design.md`.
- RN-10.4: Reação do lead (interesse, descarte, pedido de mais opções) é registrada e realimenta os próximos filtros na mesma conversa — descartar dois imóveis por "longe demais" restringe a busca de bairro.
  - **Emenda E-01 (TEC-163, 12/09/2026):** a regra dá um exemplo e nunca define a operação; esta emenda fixa o que faltava. O limiar é **dois** descartes por distância na mesma conversa. "Restringir a busca de bairro" significa excluir das buscas seguintes os bairros dos imóveis descartados por essa razão. `motivo_descarte` guarda a **categoria** do descarte — `DISTANCIA`, `PRECO`, `TAMANHO` ou `OUTRO` — e não a frase do lead: "realimenta o filtro" exige um valor comparável, e a frase continua disponível na linha do tempo de `messages`, sem precisar de segunda cópia aqui. Um descarte sem categoria legível **não conta** para o limiar. Um pedido explícito do lead por um bairro excluído **levanta a exclusão** para aquela busca — a exclusão é inferência nossa a partir de dois descartes, e nomear o bairro é declaração dele, que prevalece sobre a inferência. *"Realimenta"*, lido como "sempre informado", significa **quando o ajuste nasce ou muda**, não a cada busca subsequente. E a exclusão **sobrevive ao relaxamento da RN-09.3**: a ampliação para bairros adjacentes não devolve um bairro que o lead acabou de pedir para excluir. Ver as D10 a D14 do desenho de `docs/superpowers/specs/2026-09-12-tec-163-recomendacao-e-reacao-design.md`.

**Critérios de aceite:**
- CA-10.1: Dados 3 imóveis apresentados, quando o lead responde "gostei do segundo", então o sistema identifica corretamente o imóvel referido e o marca com interesse.

### 2.4 Módulo D — Agendamento

#### RF-11 — Consulta de disponibilidade e proposta de horários

**História:** Como lead, quero escolher um horário de visita dentro da conversa, para não precisar ligar nem esperar retorno.

**Regras de negócio:**
- RN-11.1: O sistema propõe até 3 janelas disponíveis, considerando: agenda do corretor, horário comercial (PR-06), antecedência mínima de 3 horas e duração padrão de 60 minutos (visita) ou 30 minutos (reunião remota).
- RN-11.2: A alocação do corretor considera especialidade (compra, aluguel, investimento, alto ticket) e região de atuação. Sem corretor com match exato, cai no corretor generalista de plantão.
- RN-11.3: Interpretação de linguagem natural de data: "amanhã de tarde", "quinta às 15h", "no fim de semana" são resolvidas para timestamp em `America/Sao_Paulo`, sempre com confirmação explícita da data e hora absolutas antes de gravar.
- RN-11.4: Slot é reservado com lock otimista por 5 minutos durante a confirmação; expirado sem confirmação, volta a ficar disponível.
- RN-11.5: Sem disponibilidade nas próximas 72 horas, o sistema oferece lista de espera e cria handoff para o corretor propor horário.

**Critérios de aceite:**
- CA-11.1: Dado "pode ser quinta de manhã", quando processado, então o agente propõe horários concretos daquela quinta e pede confirmação com data e hora explícitas antes de gravar.
- CA-11.2: Dados dois leads confirmando o mesmo slot simultaneamente, quando processados, então apenas um agendamento é criado e o outro recebe alternativas.

#### RF-12 — Confirmação, lembrete e cancelamento

**História:** Como corretor, quero que as visitas sejam confirmadas e lembradas, para reduzir o não comparecimento.

**Regras de negócio:**
- RN-12.1: Confirmado o agendamento, lead e corretor recebem mensagem com data, hora, endereço e nome do corretor; evento é criado no Google Calendar do corretor com convite (integração opcional, desligável por flag).
- RN-12.2: Lembretes automáticos: 24 horas antes e 2 horas antes. O de 24 h pede confirmação de presença ("sim/remarcar/cancelar").
- RN-12.3: Cancelamento pelo lead libera o slot, notifica o corretor e agenda tentativa de remarcação em 24 horas.
- RN-12.4: Não comparecimento (marcado pelo corretor) reduz o score do lead em 15 pontos e entra na cadência de reengajamento.
- RN-12.5: Status possíveis: `PROPOSTO`, `CONFIRMADO`, `REAGENDADO`, `CANCELADO`, `REALIZADO`, `NO_SHOW`.

**Critérios de aceite:**
- CA-12.1: Dado um agendamento confirmado para daqui a 26 horas, quando o relógio chega a 24 h antes, então o lembrete é enviado uma única vez.
- CA-12.2: Dado um cancelamento, quando processado, então o slot volta ao pool em menos de 10 s e o corretor é notificado.

### 2.5 Módulo E — Follow-up Automático

#### RF-13 — Cadência de reengajamento

**História:** Como gerente, quero que nenhum lead morra por falta de retorno, para não perder venda por esquecimento.

**Regras de negócio:**
- RN-13.1: Cadência padrão por temperatura, contada a partir da última mensagem do lead:

| Temperatura | Tentativas | Intervalos |
|---|---|---|
| QUENTE | 4 | 2 h, 24 h, 3 dias, 7 dias |
| MORNO | 3 | 24 h, 4 dias, 10 dias |
| FRIO | 2 | 3 dias, 14 dias |

  - **Emenda E-01 (TEC-124, 24/09/2026):** a cadência — e, com ela, a transição para `DORMENTE` da RN-13.5 — vale apenas para canal com push. O canal web fica de fora por construção: a seleção de candidatos e a de dormentes filtram por `CANAIS_COM_REENGAJAMENTO` (`domain/messages/canais.py`), hoje só o WhatsApp, na expressão que as duas consultas compartilham. A razão é que um follow-up de 24 h numa sessão de navegador não chega a ninguém: viraria linha em `followups` marcada como enviada e texto que a visitante só veria se voltasse por conta própria — caso em que ela não precisava do follow-up. **É allowlist e não exclusão do web**: canal novo nasce de fora e entra quando alguém decidir que ele tem para onde empurrar mensagem. Reengajar visitante de site é decisão de produto, e não existe card para ela. O aviso ao lead de que o corretor só responde na próxima janela (RN-16) **não** é reengajamento e continua alcançando o web, pela sessão aberta.

- RN-13.2: Cada follow-up é gerado com o contexto da conversa e **traz informação nova** (novo imóvel compatível, mudança de preço, convite para agendar). Proibido "oi, tudo bem?" solto.
  - **Emenda E-01 (TEC-184, 14/09/2026):** a regra manda que o follow-up traga informação nova e proíba mensagem vazia. Fica fixado que: a informação nova é escolhida **por código**, numa ordem fixa (queda de preço, depois imóvel novo compatível, depois convite para agendar), e que **só queda** de preço qualifica — a regra de negócio da card diz "mudança" e o critério de aceite diz "redução", e aumento de preço não reengaja. Fica declarado também que a mensagem vazia é **irrepresentável** e não bloqueada: como o convite é sempre uma alternativa, a geração nunca produz mensagem sem conteúdo; o que a validação descarta é a prosa do modelo, não o envio.
- RN-13.3: Envio apenas entre 9h e 20h no fuso do lead. Disparo agendado fora da janela é adiado para a próxima abertura.
  - **Emenda E-01 (TEC-185, 04/09/2026):** a janela é **guarda de disparo, e não ajuste de agendamento**. `devido_em` continua sendo a hora da aritmética da RN-13.1 — `ancora_em` mais o intervalo da tentativa — e pode cair fora da janela, inclusive de madrugada; o que a janela impede é o disparo naquele instante. O efeito observável da regra é o descrito: nenhum envio automático fora de 9h–20h, e o disparo recusado é adiado para a próxima abertura sem consumir a tentativa, porque na cadência derivada nada é gravado quando a janela recusa e `ja_disparada` não se move. **Consequência declarada:** a afirmação do modelo de dados da seção 5 de que `agendado_para` está *"já ajustado à janela da RN-13.3"* não vale para `devido_em` — a Emenda E-01 da RN-13.4 já havia renomeado a coluna e apontado para esta card, e esta fecha o ponto escolhendo **não** ajustar, porque `created_at` já registra a hora do disparo real e ajustar `devido_em` gravaria a mesma informação duas vezes, apagando o atraso. A janela vale para todo envio automático, mas hoje só existe um sítio de automação (a varredura da cadência); lembrete de visita e reengajamento a herdarão quando existirem (TEC-171, TEC-172).
- RN-13.4: Resposta do lead cancela a cadência pendente e reinicia o ciclo a partir do novo estado.
  - **Emenda E-01 (TEC-183, 03/09/2026):** não há cadência pendente a cancelar, porque não há agendamento persistido. A cadência é derivada da **âncora** — a última fala não bloqueada do lead — a cada varredura, e a resposta do lead move essa âncora, o que faz a régua recomeçar por aritmética. O efeito observável da regra é idêntico ao descrito: as tentativas restantes não acontecem, e o ciclo recomeça a partir do novo estado. O motivo da mudança de forma são as outras duas regras da mesma card, que um horário gravado no banco tornaria mentirosas: *"mudança de temperatura recalcula a cadência restante"* e *"os intervalos vêm de configuração e podem ser ajustados sem deploy"* — um `agendado_para` persistido congela o intervalo no instante do agendamento e fica imune às duas. **Consequência declarada:** a entidade `FollowUp` da seção 5 perde a coluna `status` e o enum inteiro — não só `PENDENTE` e `CANCELADO` das cinco opções, mas `ENVIADO`, `FALHOU` e `RESPONDIDO` também —, porque uma linha só é gravada para uma tentativa que de fato disparou, e não sobra estado nenhum para uma linha guardar; e `agendado_para` passa a ser `devido_em`, calculado no momento do disparo e **não** ajustado à janela da RN-13.3 (isso é a TEC-185).
- RN-13.5: Esgotadas as tentativas sem resposta, o lead vira `DORMENTE` e sai da cadência automática, permanecendo elegível a campanha manual pelo dashboard.
  - **Emenda E-01 (TEC-187, 14/09/2026):** a regra manda que o lead esgotado vire `DORMENTE`, saia da cadência automática e permaneça elegível a campanha manual. Fica fixado que `DORMENTE` é **estado derivado e não coluna**: o lead está dormente quando a MAIOR tentativa já disparada sob a âncora atual — a posição na régua, não a contagem de mensagens — alcança o teto da sua temperatura viva, e a pergunta é respondida por função pura (`esta_dormente`) e pela consulta `listar_dormentes`, sem nenhuma escrita nova no banco. **Consequência declarada:** a coluna `status` da entidade Lead da seção 5 continua não existindo, e dos sete valores que ela lista apenas `DORMENTE` ganha significado operacional — os outros seis seguem sem dono. Fica declarado também que *"sai da cadência automática"* já era verdade desde a Emenda E-01 da RN-13.4: o corte por temperatura da consulta de candidatos deixa de devolver o lead esgotado, e esta card não altera envio nenhum. A *"data e a quantidade de tentativas realizadas"* que a transição registra não são gravadas por esta card, e são duas contas diferentes sobre a mesma âncora: a data é o `created_at` da linha de `followups` de maior `tentativa_numero`, e a quantidade é a CONTAGEM de linhas sob essa âncora — não a posição da última tentativa, que a régua pula para tentativas intermediárias e por isso pode ser maior que o número de mensagens que de fato saíram. A elegibilidade a campanha manual é entregue como função de repositório **sem rota HTTP**, pelo mesmo motivo da reativação de opt-out da TEC-182, e a lista **exclui** o lead com opt-out registrado, porque a RN-14.3 condiciona qualquer novo contato dele a ação humana com justificativa. Por fim, a reativação do cenário 4 da card acontece **sem código**: a resposta do lead move a âncora e a contagem sob a âncora nova começa em zero — o estado `EM_CONVERSA` que o critério nomeia não é entregue, e o efeito observável que ele descreve é.
- RN-13.6: Fora da janela de 24 horas do WhatsApp, o envio só pode usar **template aprovado** pela Meta. O sistema mantém no mínimo 3 templates aprovados e escolhe conforme o contexto; sem template aplicável, o follow-up é convertido em tarefa para o corretor.
  - **Emenda E-01 (TEC-186, 22/09/2026):** a verificação da janela é feita **a partir da âncora** — a última fala não bloqueada do lead, a mesma da Emenda E-01 da RN-13.4 —, e não do relógio no adaptador do WhatsApp; a decisão é tomada **antes** do envio, de modo que fora da janela nenhuma mensagem livre é tentada (CA-13.3). O catálogo mantém no mínimo 3 templates **em código**, um por contexto (queda de preço, imóvel novo, convite), e a **aprovação pela Meta é configuração externa** (`whatsapp_templates_aprovados`), porque a submissão dos templates é atividade fora do código e o RT-03 avisa que ela pode não chegar no prazo — com o default vazio, todo follow-up fora da janela vira tarefa para o corretor, que é a mitigação do RT-03 em vigor. Sem template aprovado aplicável ao contexto, o follow-up é gravado como uma linha append-only em `tarefas_de_corretor` (sem rota HTTP nem painel — a E8 a consome quando existir). **Consequência declarada:** as colunas `usou_template` e `template_nome` que a seção 5 lista na entidade de follow-up **não** existem em `followups` — a decisão de canal acontece pós-commit (TEC-184) e uma coluna de desfecho quebraria o append-only que a Emenda E-01 da RN-13.4 fixou ou reintroduziria o reprocessamento que a estrutura pós-commit da TEC-184 evita; o uso de template é observável por `followup.entregue` (com `canal` e `template`) e a tarefa pela tabela própria, na mesma forma derivada que as Emendas E-01 da RN-13.4 e da RN-13.5 já adotaram para o status e o `DORMENTE`. O `EnvioForaDaJanela` residual (a posição de +2h do QUENTE, dentro da janela, que a Meta recuse por desacordo de relógio na borda) continua sendo consumido com log `info`, sem virar template nem tarefa.
- RN-13.7: Máximo absoluto de 4 mensagens não respondidas consecutivas por lead. Atingido, nenhuma automação envia mais nada — proteção anti-spam e contra bloqueio do número.
  - **Emenda E-01 (TEC-188, 04/09/2026):** o contador é o **número de linhas de `followups` sob a âncora atual** — a última fala não bloqueada do lead —, e não a posição da última tentativa. A régua da cadência devolve a maior tentativa vencida e pula as intermediárias, então um lead calado há dez dias tem uma única linha com `tentativa_numero = 4`: contar pela posição cortaria da automação um lead que recebeu **uma** mensagem. Duas regras da card caem dessa forma sem código próprio: *"qualquer resposta do lead zera o contador"*, porque a resposta move a âncora e a contagem sob a âncora nova começa em zero; e *"tentativas de ciclos diferentes somam"*, porque o que separa dois ciclos sem o lead falar é a mudança de temperatura, que **não** move a âncora — as tentativas dos dois ciclos ficam sob a mesma âncora e a contagem já as soma. **Consequência declarada:** enquanto o follow-up for a única automação, o máximo de 4 coincide com o teto de tentativas do `QUENTE`, porque a restrição `UNIQUE` admite no máximo quatro linhas por âncora; a guarda não altera envio nenhum hoje e existe para ser herdada pela TEC-184 e pela TEC-171. O efeito observável desta card é o evento `followup.antispam_atingido`, emitido uma vez, no instante em que a contagem fecha. Uma resposta do lead **bloqueada pela moderação** não zera o contador, pela mesma razão que não move a âncora (ver a lacuna 8 do desenho da TEC-183).

**Critérios de aceite:**
- CA-13.1: Dado um lead `QUENTE` que parou de responder às 18h, quando passam 2 horas, então o follow-up é enviado às 20h; se fosse às 19h30, seria adiado para as 9h do dia seguinte.
- CA-13.2: Dado um lead que responde após o segundo follow-up, quando a resposta chega, então as tentativas restantes são canceladas.
- CA-13.3: Dado um lead a 30 horas da última interação, quando o follow-up dispara, então usa template aprovado e não mensagem livre.

#### RF-14 — Opt-out e preferências de contato

**História:** Como lead, quero poder pedir para não receber mais mensagens e que isso seja respeitado na hora.

**Regras de negócio:**
- RN-14.1: Palavras-chave de opt-out (`sair`, `parar`, `não quero mais`, `descadastrar`) são detectadas em qualquer turno e param todo envio automático imediatamente.
- RN-14.2: Opt-out é confirmado em uma mensagem e registrado com timestamp, canal e conteúdo original — é evidência de LGPD.
- RN-14.3: Lead com opt-out só volta a ser contatado por ação humana explícita registrada no dashboard, com justificativa.
- RN-14.4: O opt-out não apaga o histórico automaticamente; a eliminação de dados é pedido separado (RNF-09).

**Critérios de aceite:**
- CA-14.1: Dado "não quero mais receber mensagens", quando processado, então nenhuma automação envia mensagem a esse lead e o registro de opt-out existe com timestamp.

### 2.6 Módulo F — Handoff e Resumo Inteligente

#### RF-15 — Resumo inteligente para o corretor

**História:** Como corretor, quero um resumo de meia página do lead, para entrar na conversa sabendo tudo sem ler 40 mensagens.

**Regras de negócio:**
- RN-15.1: O resumo contém, em blocos fixos: (a) quem é o lead e como chegou, (b) o que procura — critérios estruturados, (c) score, temperatura e justificativa dos fatores, (d) imóveis apresentados e reações, (e) objeções e pontos de atenção levantados, (f) próxima ação recomendada com prazo.
  - **Emenda E-01 (TEC-175, 12/09/2026):** o bloco **(e)** é montado a partir de `lead_qualification.campos_recusados`, `lead_qualification.perguntados_sem_resposta` e dos `recomendacoes.motivo_descarte` — e **não** a partir das objeções que o lead argumentou, que nenhuma tabela deste sistema guarda. Não existe entidade Objeção, e nenhuma card do épico E7 a cria. As três fontes acima são pontos de atenção verdadeiros, mas de outra natureza: dizem que o lead recusou informar renda, não o que ele respondeu quando o preço subiu. Dar ao modelo o `conversation_summaries.resumo` (cuja instrução já manda preservar objeções) foi descartado porque a origem seria prosa escrita por outro modelo, o que daria ao bloco (e) fidelidade diferente dos outros cinco — contra a RN-15.3, que é a regra fundadora deste resumo. Consequência declarada: o bloco (e) é mais magro do que a regra original promete. Ver a D4 do desenho.
  - **Emenda E-02 (TEC-175, 12/09/2026):** o bloco **(a)** identifica o lead por canal, chave da conversa e data da primeira mensagem. **Não há nome de lead neste sistema** — nem `lead_qualification` nem `messages` têm a coluna, e nenhuma card a cria. O corretor sabe por onde responder, não com quem fala. Criar o campo é decisão de produto (quem pergunta o nome, em que ponto do roteiro, o que fazer se o lead não disser) e não cabe numa card de resumo. Ver a L1 do desenho.
- RN-15.2: Gerado automaticamente no handoff e regenerado sob demanda no dashboard. Limite de 1.500 caracteres.
- RN-15.3: Todo dado factual do resumo vem do estado estruturado, não da interpretação livre do modelo. O LLM redige a narrativa; os números vêm do banco.
- RN-15.4: Geração em até 8 segundos (p95). Em falha do provedor, o sistema entrega um resumo determinístico em template a partir dos campos estruturados — o corretor nunca fica sem resumo.
  - **Emenda E-01 (TEC-176, 13/09/2026):** o resumo de contingência cobre **toda** falha que deixaria `handoffs.resumo` nulo, e não apenas a indisponibilidade do provedor. Em particular, cobre a **resposta malformada do modelo** — bloco ausente, blocos fora de ordem, ou texto acima dos 1.500 caracteres mesmo depois da compressão —, que a D7 da TEC-175 decidiu, com razão, não truncar. A promessa desta regra é sobre o que o **corretor** recebe, não sobre a causa da falha: do lado dele, resposta malformada e provedor fora do ar são a mesma coisa, um lead sem contexto. Seguir a letra "falha do provedor" deixaria a regra violada pela metade depois de uma card feita para fechá-la. **Exceção declarada:** dossiê ausente (o handoff sumiu entre a criação e o job) continua sem resumo — sem fatos não há template, e montar um seria produzir um resumo que não descreve lead nenhum. Ver a D1 do desenho.
  - **Emenda E-02 (TEC-176, 13/09/2026):** a falha do provedor **não é retentada** — o template é gravado na primeira falha. O argumento é da própria card, que exige que o corretor seja notificado *"sem atraso — a degradação é do conteúdo, não do fluxo"*; retentar é, por definição, atrasar, e o que se ganharia esperando é um resumo melhor para um corretor que, enquanto isso, não recebeu nada. A RNF-27 fala em dois retries com backoff antes de desistir, mas essa estratégia é a E9 e **não existe hoje**: o que havia era a retentativa genérica do ARQ, sem limite configurado para este job. **Consequência declarada:** uma falha transitória de rede produz um resumo simplificado que uma retentativa teria evitado; o caminho de volta é a regeneração sob demanda da RN-15.2. Ver a D2 do desenho.
- RN-15.5: O resumo é sempre acompanhado do link para a transcrição completa.

**Critérios de aceite:**
- CA-15.1: Dado um handoff, quando o resumo é gerado, então contém os 6 blocos, cabe em 1.500 caracteres e todo número citado bate com o banco.
- CA-15.2: Dada indisponibilidade do provedor de LLM, quando o handoff ocorre, então o resumo em template é entregue e o corretor é notificado normalmente.

#### RF-16 — Handoff e integração com CRM

**História:** Como corretor, quero ser avisado no canal que uso quando um lead está pronto, para não perder o timing.

**Regras de negócio:**
- RN-16.1: Gatilhos de handoff: lead atinge `QUENTE`; agendamento confirmado; pedido explícito de humano; intenção `VENDER_IMOVEL` ou `SUPORTE_CONTRATO`; limite de 8 perguntas atingido; erro irrecuperável do agente.
  - **Emenda E-01 (TEC-174, 12/09/2026):** a prioridade de um handoff **aberto** escala para `ALTA` e **nunca desce**. A regra original fixa a prioridade pelo gatilho (`ALTA` para pedido explícito de humano, `NORMAL` para os demais) mas é silenciosa sobre o gatilho que chega depois, sobre um handoff que já existe — e a regra de deduplicação manda o gatilho novo atualizar o existente em vez de criar outro. Sem esta emenda, a leitura literal rebaixaria um pedido explícito a `NORMAL` sempre que houvesse handoff anterior, violando a RN-04.6, que manda o pedido explícito *"interromper o fluxo imediatamente e criar handoff prioritário"*. A **etiqueta**, ao contrário da prioridade, permanece a do gatilho que criou o handoff: é por ela que a fila do dashboard (RF-18) é filtrada, e etiqueta que muda sozinha embaralha filtro salvo. Ver a D6 e a D7 do desenho.
  - **Emenda E-02 (TEC-174, 12/09/2026):** `corretor_id` é **opcional** enquanto não existirem corretores. O modelo de dados da seção 5 o declara obrigatório e como FK, mas a entidade Corretor só nasce na TEC-196 — FK exige tabela alvo. A coluna nasce nulável e sem restrição de chave estrangeira; a TEC-196 acrescenta a restrição quando criar a tabela. **Provisória por construção**, ao contrário da ausência de FK em `moderation_events` e `lead_score_audit`, que é permanente e tem outra causa (descompasso de retenção). Consequência declarada: o critério de aceite *"Handoff aponta o corretor já alocado"* não é exercitável até a TEC-196. Ver a D3 e a L1 do desenho.
  - **Emenda E-03 (TEC-196, 12/09/2026):** a restrição que a E-02 prometeu **existe**. A TEC-196 criou a tabela `corretores` e acrescentou a chave estrangeira de `handoffs.corretor_id`, com `ON DELETE RESTRICT` — corretor se desativa por `ativo = false`, nunca se apaga, então a cascata não tem caso de uso e apagar por engano deve doer. **A coluna continua nulável**, e por outra razão que não a original: não há mais ausência de tabela alvo, há ausência de quem aloque. Escrever o `corretor_id` de um handoff é a TEC-166. Consequência: o critério de aceite *"Handoff aponta o corretor já alocado"*, declarado inexercitável na L1 do desenho da TEC-174, segue inexercitável — agora por falta de alocação, não por falta de entidade. Ver a D5 do desenho da TEC-196.
  - **Emenda E-04 (TEC-143, 15/09/2026):** o gatilho "pedido explícito de humano" passa a ser acionado de verdade, e de forma **determinística, não semântica** — sem chamar o modelo. Não foi acrescentada intenção nova ao enum `Intencao`: medido, `FALAR_COM_HUMANO` custaria 5 tokens no schema compilado e levaria a margem do orçamento de prompt de 6,2 para 1,2, mas o que decidiu não foi o custo — foi a dependência. O handoff precisa nascer em até 5 segundos, e uma chamada paga ao classificador falha pior justamente quando o lead já está irritado o bastante para pedir uma pessoa; a guarda determinística torna o prazo consequência da arquitetura, não aposta na latência do provedor. A regra original é silenciosa sobre horário: **fora da janela de atendimento o handoff é criado do mesmo jeito** — o que muda é só o texto que o lead recebe —, porque a card é explícita em que ele nunca fica em espera silenciosa. Essa janela (`Settings.atendimento_horario_inicio`/`atendimento_horario_fim`) é fixa e da **imobiliária**, não a jornada do corretor designado: no instante do pedido ninguém foi designado ainda, e a alocação por especialidade e região é outra card (TEC-166). Por fim, enquanto esse handoff seguir aberto o agente cala — mas não pela consulta que a TEC-179 construiu (`AtendimentoHumano`, cujo `assumir` exige um `corretor_id` que não existe no instante do pedido): a pergunta é nova, `tem_handoff_de_humano_aberto`, sobre a fila de handoff em si, não sobre quem assumiu. **A esteira da RN-16.2 e da RN-16.3 vale para este gatilho como para os demais**, e isso precisa ser dito porque "o handoff nasce do mesmo jeito" foi entendido como bastando: o handoff criado pelo pedido explícito agenda o resumo no mesmo ponto em que os outros cinco sítios o agendam, e é por esse resumo que a notificação é enfileirada e o `sla_limite_em` é gravado. A primeira implementação desta card não fazia essa chamada, e o efeito não era "nasce igual": o handoff ficava fora da notificação e sem prazo, invisível para a escalada da RN-16.3, e só era recuperado pela rede da TEC-279 de 10 a 15 minutos depois, com alarme — a rede de segurança como caminho normal do único gatilho `ALTA` desta regra. **Fora da janela de atendimento nada disso muda**: a janela decide só o texto que o lead recebe; o prazo continua contando dentro da jornada do corretor destinatário (Emenda E-01 da RN-16.3) e o handoff sem destinatário continua escalando na hora e sem prazo (Emenda E-02 da RN-16.3). **Percorrer a esteira não é o mesmo que avisar alguém:** a Emenda E-02 da RN-16.2 segue em vigor — os dois canais registram e não entregam —, e por isso o texto que o lead recebe fala do encaminhamento e do horário e **não afirma que alguém foi avisado**. **Consequência declarada:** a detecção tem lacuna de recall — um pedido escrito de um jeito que a lista de termos não prevê continua no loop de qualificação —, e não há medição de cobertura possível hoje, porque o corpus de evals não contém nenhum pedido de humano; e tem lacuna simétrica de precisão, porque a lista não fixa de quem é a pessoa do outro lado — "falar com uma pessoa do banco" transfere, e qualificar a frase mataria o critério de aceite da card. Ver a D1, a D3 e a D5 do desenho e as lacunas declaradas lá.
- RN-16.2: Notificação por e-mail e WhatsApp ao corretor designado em até 60 s, com resumo e link direto para o lead no dashboard.
  - **Emenda E-01 (TEC-177, 12/09/2026):** o destinatário é o corretor **alocado** quando houver, e o **generalista de plantão** quando não houver. "Designado" pressupõe alocação, que é a TEC-166 — `handoffs.corretor_id` tem chave estrangeira desde a TEC-196 e nunca é escrito. Com mais de um plantão ativo, escolhe-se o **mais antigo** por `criado_em`: a D7 da TEC-196 deixou a multiplicidade aberta de propósito, porque a card de lá não escreveu a regra, e esta card precisa de uma resposta determinística para poder enviar. Sem plantão ativo e sem corretor alocado, o handoff nasce marcado como pendente de aviso manual — não há para quem mandar, e registrar sucesso seria mentir. **Qual plantão deve receber é decisão da TEC-166**, e quando ela chegar esta escolha sai daqui. Ver a D3 do desenho.
  - **Emenda E-02 (TEC-177, 12/09/2026):** os dois canais nascem como **porta com adaptador que registra e não entrega**, e por isso **nada chega a corretor nenhum** enquanto duas coisas não existirem, nenhuma delas produzível por um PR deste repositório. **E-mail:** não há infraestrutura nenhuma no projeto — sem dependência no `pyproject.toml`, sem SMTP, sem provedor —, e a escolha foi deliberadamente adiada em 12/09/2026. **WhatsApp:** a Cloud API da Meta recusa mensagem livre passadas 24 h da última fala do destinatário (código `131047`, que `outbound/whatsapp.py` já trata), e o corretor está **sempre** fora dessa janela porque não conversa com o número da empresa — entregar exige um **template aprovado pela Meta**, que é cadastro externo com prazo próprio. Consequência declarada: os três primeiros critérios de aceite da card são exercitados com dublês, e a mitigação do risco RN-B03 que esta regra representa **não está em vigor**. Ver a D4 e a L1 do desenho.
  - **Emenda E-03 (TEC-280, 20/09/2026):** o e-mail passa a **entregar de verdade**, por SMTP direto — a metade da Emenda E-02 acima que falava de e-mail deixou de valer. A escolha de provedor (Mailpit em desenvolvimento; SES, Postmark ou Resend em produção) ficou sendo configuração, não código: o worker recusa subir sem `SMTP_HOST` e `SMTP_REMETENTE`. O canal de WhatsApp ao corretor **continua** só registrando e não entregando — a outra metade da Emenda E-02 segue em vigor —, e a TEC-281 é quem fecha essa lacuna. A mitigação do risco RN-B03 que esta regra representa passa a valer **pela metade**: um canal entrega, o outro não.
  - **Emenda E-04 (TEC-281, 23/09/2026):** os dois canais **não são equivalentes**, e a regra os trata como se fossem. O e-mail leva o resumo; o **WhatsApp leva um aviso sem resumo** — etiqueta, prioridade e link. A razão é da Meta e não nossa: fora da janela de 24 h a Cloud API só aceita **template aprovado**, e o corretor está *sempre* fora dessa janela porque não conversa com o número da empresa. Template recebe parâmetros posicionais revisados humano por humano, e o resumo é prosa de até 1.500 caracteres destilada do que o lead escreveu — não cabe num parâmetro nem passaria na revisão. **Quem quiser o conteúdo tem o e-mail ou o painel;** o WhatsApp é o toque no ombro. A metade da Emenda E-02 que falava de WhatsApp deixa de valer no que diz respeito à porta — o adaptador agora entrega —, mas **a entrega continua condicionada a um fato externo**: sem template aprovado pela Meta e configurado (`whatsapp_template_notificacao_corretor`, que só vale se também estiver em `whatsapp_templates_aprovados`), o canal falha alto e registra o motivo, e o corretor continua recebendo só o e-mail. Nunca há tentativa de texto livre: seria recusa garantida com o código 131047. **Consequência declarada:** a escalada ao gerente da RN-16.3 usa o mesmo vetor de canais e **não tem template próprio**, então o WhatsApp falha lá por desenho — o gerente continua avisado só por e-mail, agora dito em voz alta em vez de registrado como se fosse entrega. Ver a D1 e a D4 do desenho.
- RN-16.3: Handoff cria uma tarefa com SLA de aceite: 15 min para `QUENTE`, 4 h para os demais. Estourado o SLA, escala para o gerente comercial.
  - **Emenda E-01 (TEC-178, 13/09/2026):** o relógio do SLA conta dentro da **jornada do corretor destinatário** — `corretores.horario_inicio`/`horario_fim`, que a TEC-196 criou —, e não dentro de uma janela geral da imobiliária. A consequência é que `sla_limite_em` **não pode ser gravado na criação do handoff**: a jornada só é conhecida depois que o destinatário é resolvido, o que acontece no job de notificação. O prazo é gravado lá, alguns segundos depois, o que é inofensivo diante de um SLA mínimo de quinze minutos. A temperatura que define o prazo vem de `lead_qualification.temperatura` e não do gatilho do handoff: `LEAD_QUENTE` significa "acabou de atravessar a borda", e um handoff criado por pedido explícito de humano sobre um lead **já** quente merece os mesmos quinze minutos. Temperatura nula conta como não-quente — dar quinze minutos a um lead cuja temperatura ninguém calculou seria inventar urgência. Ver a D2 e a D3 do desenho.
  - **Emenda E-02 (TEC-178, 13/09/2026):** handoff **sem destinatário** — nenhum corretor alocado e nenhum plantão ativo — **escala imediatamente** e fica sem prazo. Sem corretor não há jornada, e atribuir um prazo genérico inventaria um dono que não existe. "Ninguém sequer foi avisado" é a versão mais forte do que esta regra leva ao gerente, então o handoff nasce `ESCALADO`, ao lado do `aviso_manual_pendente` que a Emenda E-01 da RN-16.2 já marca. Ver a D4 do desenho.
  - **Emenda E-03 (TEC-178, 13/09/2026):** o **gerente comercial** é uma flag `gerente` em `corretores`, espelhando o `plantao` da TEC-196 — mesma tabela, mesmo padrão, e a mesma cascata determinística (com mais de um gerente ativo, o mais antigo por `criado_em`, porque é o que não muda quando alguém cadastra outro). Não existe entidade Gerente neste sistema, e inventá-la agora seria inventá-la duas vezes: a TEC-201 e a TEC-202 trazem `usuarios` e papéis de verdade. **Custo declarado:** "papel" passa a morar numa tabela que aquelas cards vão querer governar depois. Dívida consciente. Ver a D7 do desenho.
- RN-16.4: Ao assumir, o corretor coloca o agente em modo silencioso naquela conversa. O agente não envia mais nada até ser reativado, mas continua registrando as mensagens.
  - **Emenda E-01 (TEC-179, 13/09/2026):** o autor de assumir e devolver é um `corretor_id` **informado no corpo** e guardado pelo `X-Admin-Token`, e não a identidade autenticada que este SRS pressupõe (`Bearer JWT`, papel `CORRETOR`) — que ainda não existe. É **afirmação de quem chama, não identidade provada**: quem tem o token pode assumir em nome de qualquer corretor, e devolver a conversa que outro assumiu. Fechar é a TEC-201.
  - **Emenda E-02 (TEC-179, 13/09/2026):** assumir a conversa **aceita junto** o handoff `PENDENTE` ou `ESCALADO` da mesma conversa, carimbando `aceito_em`. Sem isso o corretor atende e a gerente comercial é cobrada pelo mesmo lead quinze minutos depois, porque a fila de escalada da RN-16.3 não sabe que alguém já pegou o caso. `ESCALADO` entra pelo mesmo argumento da Emenda E-01 da seção 6.5: aceitar depois da escalada é o caso real, não uma falha a recusar.
  - **Emenda E-03 (TEC-179, 13/09/2026):** a guarda de atendimento humano em `GuardedOutbound.send` não barra `KIND_DA_CONFIRMACAO_DE_OPTOUT` — ela barra todo o resto. A D5 do desenho desta card decidiu "barra tudo, sem escotilha", e essa decisão estava errada num caso que ela não previu: sem a exceção, um lead que digita "PARE" numa conversa já assumida tem o opt-out registrado mas **não recebe a confirmação**, porque o repositório trata a confirmação do próprio pedido como o único envio permitido depois do registro (ver `domain/optout/`). O argumento original da D5 era sobre o caminho **humano** de envio — que ainda não existe —, e a confirmação de opt-out é reconhecimento legal de um pedido do próprio lead, não mensagem de conversa; nunca devia ter caído na mesma guarda. Pela mesma razão, a saída barata do turno (`executar_turno`) passou a ser condicionada a `not pedido_de_optout`: sem essa condição, o próprio pedido de opt-out era descartado sem ser gravado, porque a checagem de silêncio corria antes do registro dele.
  - **Emenda E-04 (TEC-278, 13/09/2026):** `POST /api/v1/conversas/devolver` passa a **concluir** o handoff aberto da conversa, espelhando a Emenda E-02 acima, que fez `assumir` aceitá-lo. É o primeiro escritor que `CONCLUIDO` tem desde a TEC-174: sem ele, o índice de `handoffs` — que desde esta card cobre todo status menos `CONCLUIDO` — prenderia a conversa ao primeiro handoff dela para sempre. Ver a D1 e a D2 do desenho da TEC-278.
- RN-16.5: Exportação para CRM via adaptador com interface única (`CrmPort`), implementada no MVP como webhook HTTP configurável com payload JSON versionado e retry exponencial (3 tentativas). Falha permanente vira alerta, não perda silenciosa.

**Critérios de aceite:**
- CA-16.1: Dado um lead que vira `QUENTE`, quando o handoff é criado, então o corretor recebe notificação em até 60 s com resumo e link.
- CA-16.2: Dado que o corretor assume a conversa, quando o lead envia nova mensagem, então o agente não responde automaticamente e a mensagem aparece no dashboard.
- CA-16.3: Dado um webhook de CRM indisponível, quando o envio falha 3 vezes, então um alerta é registrado e o payload fica em fila de reprocessamento.

### 2.7 Módulo G — Dashboard e Administração

#### RF-17 — Painel de funil e métricas

**História:** Como gerente comercial, quero ver o funil em tempo real, para saber onde estamos perdendo lead.

**Regras de negócio:**
- RN-17.1: Indicadores do período selecionado: leads novos, conversas ativas, taxa de qualificação, distribuição por temperatura, agendamentos criados/confirmados/realizados, taxa de no-show, tempo médio de primeira resposta, tempo médio de qualificação, taxa de handoff aceito no SLA.
- RN-17.2: Funil visual em 6 etapas: Novo → Em conversa → Qualificado → Recomendado → Agendado → Handoff aceito, com valor absoluto e taxa de conversão entre etapas.
- RN-17.3: Filtros por período, canal, intenção, temperatura e corretor. Dados atualizados com atraso máximo de 60 s.
- RN-17.4: Painel de custo de IA: custo total do período, custo médio por conversa e por lead qualificado, tokens consumidos por modelo.

**Critérios de aceite:**
- CA-17.1: Dado um agendamento criado, quando o dashboard é recarregado após 60 s, então o contador de agendamentos reflete a mudança.

#### RF-18 — Lista de leads e visão de conversa

**História:** Como corretor, quero abrir um lead e ver tudo — resumo, critérios e a conversa inteira.

**Regras de negócio:**
- RN-18.1: Lista paginada com ordenação padrão por score decrescente e busca por nome, telefone ou bairro de interesse.
- RN-18.2: Detalhe do lead: dados de contato, qualificação estruturada, histórico de score, imóveis recomendados, agendamentos, follow-ups enviados e transcrição completa com timestamps.
- RN-18.3: O corretor pode intervir na conversa pelo dashboard (RN-16.4), editar campos de qualificação e forçar recálculo do score.
- RN-18.4: Toda edição manual é registrada com autor e timestamp.
- RN-18.5: Telefone e e-mail exibidos mascarados por padrão para papéis sem permissão `VER_DADOS_COMPLETOS`; revelar registra evento de auditoria.

**Critérios de aceite:**
- CA-18.1: Dado um corretor sem a permissão, quando abre um lead, então o telefone aparece parcialmente mascarado.
- CA-18.2: Dada uma edição de orçamento pelo corretor, quando salva, então o score é recalculado e a alteração fica registrada com autor.

#### RF-19 — Gestão de catálogo, corretores e configuração do agente

**História:** Como administrador, quero ajustar imóveis, corretores e o comportamento do agente sem depender de deploy.

**Regras de negócio:**
- RN-19.1: CRUD de imóveis com upload em lote e alteração de status.
- RN-19.2: CRUD de corretores com especialidade, regiões, horário de trabalho e capacidade diária de visitas.
- RN-19.3: Configuração do agente sem deploy: tom de voz, nome do assistente, limite de perguntas, pesos do lead scoring, intervalos de cadência de follow-up.
- RN-19.4: Prompts versionados. Toda alteração cria nova versão com autor e diff, e permite rollback para versão anterior.
- RN-19.5: Acesso a este módulo restrito ao papel `ADMIN`.
  - **Emenda E-01 (TEC-196, 12/09/2026):** enquanto a TEC-201 não existir, o papel `ADMIN` é o header `X-Admin-Token` comparado em tempo constante com `CATALOGO_ADMIN_TOKEN`, o mesmo do catálogo (Emenda E-01 da TEC-156), e **com a variável vazia o router não é registrado** — a rota devolve `404`, porque rota que não existe não pode ser exposta por engano de configuração. **A diferença em relação ao catálogo é material e por isso está escrita aqui:** aquela emenda aceitou o segredo compartilhado com a justificativa de que *"o objeto é o catálogo de imóveis e não dado pessoal, ao contrário da reativação de opt-out da TEC-182, que por isso ficou sem rota HTTP"*. O cadastro de corretores **é** dado pessoal — nome, e-mail e telefone de pessoas reais —, então esta emenda estende a um dado pessoal uma guarda que foi aceita justamente por não haver dado pessoal em jogo. **Consequência declarada: quem tem o token passa a poder ler o contato de todos os corretores, e o segredo não tem expiração, rotação nem papel.** Decisão consciente de 12/09/2026, e o argumento escrito para a TEC-201 ser antecipada. Ver a D8 do desenho.

**Critérios de aceite:**
- CA-19.1: Dada uma alteração no peso de urgência do score, quando salva, então os próximos recálculos usam o novo peso sem reiniciar a aplicação.
- CA-19.2: Dada uma nova versão de prompt que piora as respostas, quando o rollback é acionado, então a versão anterior volta a valer em menos de 30 s.

---

## 3. Requisitos Não Funcionais

Todo RNF traz métrica e forma de verificação. Os alvos consideram o volume da PR-01.

### 3.1 Desempenho

| ID | Requisito | Métrica | Verificação |
|---|---|---|---|
| RNF-01 | Ack do webhook de mensagem | p95 ≤ 300 ms, p99 ≤ 500 ms | Teste de carga k6 com 50 req/s |
| RNF-02 | Primeira resposta ao lead (ponta a ponta, incluindo LLM) | p95 ≤ 6 s, p99 ≤ 10 s | Tracing Langfuse/OTel em ambiente de homologação |
| RNF-03 | Busca no catálogo (RAG híbrido) | p95 ≤ 400 ms com 10.000 imóveis | Benchmark com base sintética |
| RNF-04 | Carregamento do dashboard | p95 ≤ 2 s (LCP) com 1.000 leads | Lighthouse CI no pipeline |
| RNF-05 | Geração do resumo de handoff | p95 ≤ 8 s | Métrica por operação no tracing |
| RNF-06 | Custo de IA | ≤ US$ 0,12 por conversa qualificada | Painel de custo (RN-17.4); alerta em 80% do orçamento |

### 3.2 Escalabilidade

| ID | Requisito | Métrica | Verificação |
|---|---|---|---|
| RNF-07 | Concorrência suportada na POC | 200 conversas simultâneas, 5.000 mensagens/dia sem degradar RNF-02 | Teste de carga antes da demo |
| RNF-08 | Escala horizontal | API e workers sem estado, escaláveis por réplica; alvo de 2.000 conversas simultâneas com 6 réplicas | Teste com 3× a carga da POC |
| RNF-09 | Desacoplamento por fila | Nenhum processamento de LLM no ciclo HTTP; profundidade de fila monitorada com alerta acima de 500 itens | Inspeção de arquitetura + alerta configurado |
| RNF-10 | Gargalos declarados | Rate limit da Meta (80 msg/s por número) e TPM do provedor de LLM são os tetos reais; mitigação por fila com backpressure e rate limiter por canal | Documentado e testado com rajada sintética |

### 3.3 Segurança e privacidade

| ID | Requisito | Métrica / regra | Verificação |
|---|---|---|---|
| RNF-11 | Autenticação do dashboard | OAuth2/OIDC com JWT de 60 min e refresh de 7 dias; MFA obrigatório para `ADMIN` | Teste de autenticação no CI |
| RNF-12 | Autorização por papel | Papéis `ADMIN`, `GERENTE`, `CORRETOR`, `LEITURA`; corretor só vê os próprios leads salvo permissão explícita | Suíte de testes de autorização por rota |
| RNF-13 | Criptografia | TLS 1.3 em trânsito; AES-256 em repouso no banco e nos backups | Scan de configuração + verificação do provedor |
| RNF-14 | Segredos | Nenhum segredo em repositório; uso de secret manager do provedor; rotação a cada 90 dias | `gitleaks` no pipeline, bloqueante |
| RNF-15 | Validação de webhook | Assinatura `X-Hub-Signature-256` da Meta verificada em toda requisição; payload não assinado é descartado com log | Teste automatizado com payload forjado |
| RNF-16 | Rate limiting e abuso | 20 mensagens/min por número; 100 req/min por IP no widget; excedente entra em backoff — ver Emenda E-01 | Teste de carga com rajada |
| RNF-17 | Prompt injection | Conteúdo do lead sempre delimitado e tratado como dado, nunca como instrução; instruções do sistema não são sobrescrevíveis; suíte de 20 ataques conhecidos no CI | Teste de regressão de segurança |
| RNF-18 | Auditoria | Log imutável de acesso a dado pessoal, alteração de qualificação, handoff, opt-out e mudança de prompt; retenção de 12 meses | Revisão da tabela de auditoria |

- **Emenda E-01 (TEC-205, 21/09/2026)** — o backoff é do excedente **por número**, que é adiado por `atraso_de_backoff_segundos` e processado depois. O excedente **por IP** recebe `429` com `Retry-After`, não backoff: ali a requisição é síncrona e não há o que adiar sem deixar o cliente pendurado. O webhook do WhatsApp fica **isento** do limite por IP — o IP da Meta é compartilhado por todo o tráfego de entrada, e limitá-lo não distingue abuso de operação; o `/health` fica isento pela mesma classe de razão, já que um 429 num probe de liveness derrubaria o processo. O limite por IP se aplica a toda rota HTTP restante, inclusive antes de o widget do TEC-124 existir.
- **Emenda E-02 (TEC-124, 24/09/2026)** — o limite por IP passa a ser aplicado também no **handshake do WebSocket do widget**, por dentro do próprio endpoint. A Emenda E-01 escreve que o limite "se aplica a toda rota HTTP restante", e isso está correto: `RateLimitPorIP` é um `BaseHTTPMiddleware`, e essa classe devolve cedo para todo escopo que não seja `http` — o handshake de `ws://` nunca passava por ela, o que foi medido com um teste antes da correção (com limite 2, a terceira conexão era aceita). O comentário de `create_app` afirmava o contrário desde a TEC-205, citando o widget desta card pelo nome, e foi corrigido junto. Mesmo limite e mesma janela do middleware, de propósito; o excedente recebe o código de fechamento 1013, análogo ao 429 da rota HTTP, e grava a mesma linha em `rate_limit_events`.

**LGPD** (Lei 13.709/2018) — tratado explicitamente por haver dado pessoal desde a POC (PR-09):

| ID | Requisito |
|---|---|
| RNF-19 | **Base legal:** execução de procedimentos preliminares a contrato a pedido do titular (art. 7º, V) para o atendimento; **consentimento** (art. 7º, I) para comunicações de marketing e follow-up após encerramento. O consentimento é registrado com texto exibido, data, hora e canal. |
| RNF-20 | **Dados tratados:** nome, telefone, e-mail, preferências de imóvel, faixa de renda inferida, transcrição de conversa. **Não são coletados dados sensíveis** (art. 5º, II); se o lead os informar espontaneamente, o campo é redigido antes da persistência. |
| RNF-21 | **Direitos do titular:** acesso, correção, portabilidade (export JSON) e eliminação atendidos em até 15 dias, por endpoint administrativo e por comando no próprio WhatsApp. |
| RNF-22 | **Retenção:** lead sem conversão é eliminado ou anonimizado em 24 meses após a última interação; transcrições, em 12 meses. Anonimização preserva métricas agregadas. |
| RNF-23 | **Transferência internacional:** o provedor de LLM processa dados fora do Brasil. Isso é informado no aviso de privacidade, contrato com cláusula de não-treinamento e retenção zero, e dados de identificação direta (nome completo, telefone) são substituídos por pseudônimos antes do envio ao modelo sempre que não forem necessários à resposta. |
| RNF-24 | **Encarregado (DPO):** indicado no aviso de privacidade com canal de contato; a POC define o papel e o e-mail, mesmo que a pessoa seja fictícia no exercício. |

**Específicos de IA generativa:**

| ID | Requisito | Verificação |
|---|---|---|
| RNF-25 | Política de não-treinamento com o provedor; opt-out de retenção configurado na conta | Print da configuração + cláusula contratual |
| RNF-26 | Mitigação de alucinação: dado factual só sai de tool call validada (RN-09.4); taxa de alucinação medida em suíte de 50 conversas sintéticas, alvo < 2% | Eval automatizada no CI |
| RNF-27 | Indisponibilidade do modelo: timeout de 15 s, 2 retries com backoff, fallback para provedor secundário e, esgotado, mensagem de espera ao lead + handoff automático | Teste de caos com provedor simulado offline |
| RNF-28 | Moderação de entrada e saída ativa em 100% dos turnos | Teste com corpus de conteúdo impróprio |

### 3.4 Disponibilidade e continuidade

| ID | Requisito | Métrica | Verificação |
|---|---|---|---|
| RNF-29 | Disponibilidade do canal de atendimento | 99,5% mensal (≈3,6 h de indisponibilidade) | Monitor sintético a cada 60 s |
| RNF-30 | RTO / RPO | RTO 4 h, RPO 15 min | Ensaio de restauração documentado |
| RNF-31 | Backup | Snapshot diário do Postgres com retenção de 7 dias + WAL contínuo; restauração testada ao menos uma vez antes da entrega | Registro do teste de restore |
| RNF-32 | Degradação graciosa | Sem LLM: mensagem honesta + handoff. Sem busca vetorial: fallback para busca SQL por filtros. Sem WhatsApp: widget web segue operando | Teste de caos por componente |
| RNF-33 | Entrega de mensagem | Nenhuma mensagem recebida é perdida: fila persistente, dead-letter queue e reprocessamento manual | Teste de kill do worker durante processamento |

### 3.5 Observabilidade

| ID | Requisito | Verificação |
|---|---|---|
| RNF-34 | Logs estruturados em JSON com `trace_id`, `lead_id`, `conversa_id`; dado pessoal mascarado no log | Inspeção de amostra de logs |
| RNF-35 | Tracing distribuído com OpenTelemetry cobrindo webhook → fila → agente → tool → resposta | Trace completo visível para uma conversa de ponta a ponta |
| RNF-36 | Observabilidade de LLM: prompt, resposta, modelo, tokens, custo, latência e resultado de eval por chamada (Langfuse) | Painel com últimas 100 chamadas |
| RNF-37 | Métricas RED (Rate, Errors, Duration) por endpoint e por agente, expostas em Prometheus | Dashboard Grafana ativo |
| RNF-38 | Alertas mínimos: erro > 2% em 5 min; p95 de resposta > 10 s; fila > 500; custo diário > 120% da média de 7 dias; falha de webhook da Meta | Alertas configurados e testados com disparo real |

### 3.6 Acessibilidade e compatibilidade

| ID | Requisito | Verificação |
|---|---|---|
| RNF-39 | Dashboard em conformidade WCAG 2.1 nível AA: contraste, navegação por teclado, rótulos ARIA em elementos interativos | `axe-core` no CI, zero violações críticas |
| RNF-40 | Compatibilidade: duas últimas versões de Chrome, Firefox, Safari e Edge | Matriz de teste no pipeline |
| RNF-41 | Responsividade de 360 px a 1920 px — o corretor usa celular | Teste visual em 3 breakpoints |
| RNF-42 | Mensagens do agente compatíveis com leitores de tela e sem depender de emoji para transmitir informação essencial | Revisão de conteúdo das mensagens |

---

## 4. Arquitetura de Software e Tecnologias

### 4.1 Estilo arquitetural

**Monólito modular com processamento assíncrono**, organizado em arquitetura hexagonal (ports & adapters).

A escolha é deliberada e contrária ao reflexo de propor microsserviços. Para uma POC de hackathon com equipe pequena, microsserviços custariam mais em orquestração, observabilidade distribuída e tempo de setup do que devolveriam em escala — e escala não é o problema deste sistema hoje. O monólito modular entrega o mesmo isolamento lógico com um décimo do custo operacional.

O que torna a escolha defensável em avaliação de arquitetura é o desenho interno:

- **Módulos com fronteira explícita** (`conversacao`, `qualificacao`, `catalogo`, `agendamento`, `followup`, `handoff`, `dashboard`), comunicando-se por interfaces, não por import direto de implementação.
- **Ports & adapters** em toda integração externa: `MessagingPort` (WhatsApp/Web), `LlmPort` (Anthropic/OpenAI), `CrmPort`, `CalendarPort`, `VectorStorePort`. Trocar de provedor é trocar adaptador — e é isso que permite o fallback de LLM do RNF-27.
- **Fila entre ingestão e processamento**: o webhook só valida e enfileira. Todo trabalho pesado roda em worker, o que atende RNF-01 e RNF-09 e permite escalar o processamento independentemente da recepção.
- **Extração de serviço prevista**: se o volume crescer, o `worker-agente` sai como serviço próprio sem tocar no restante, porque já se comunica só por fila e interface.

**Orquestração multiagente por grafo de estados (LangGraph).** Um agente monolítico com um prompt gigante degrada conforme as regras crescem. O desenho usa um supervisor e agentes especializados:

| Agente | Responsabilidade |
|---|---|
| **Supervisor** | Classifica intenção, decide o próximo agente, controla o fluxo e o limite de perguntas |
| **Qualificador** | Conduz a coleta progressiva de critérios (compra/aluguel) |
| **Investidor** | Trilha especializada de perfil investidor e indicadores de rentabilidade |
| **Consultor de Imóveis** | Executa a busca RAG e monta as recomendações |
| **Agendador** | Resolve datas, consulta disponibilidade e confirma o agendamento |
| **Redator de Resumo** | Gera o resumo de handoff a partir do estado estruturado |

O **estado** do grafo é persistido no Postgres a cada transição (checkpointing), o que dá continuidade entre sessões (RF-02) e permite retomar de onde parou após falha de worker.

### 4.2 Stack recomendada

| Camada | Recomendado | Justificativa (requisito atendido) | Alternativa | Trade-off |
|---|---|---|---|---|
| Backend / API | **Python 3.12 + FastAPI** | Ecossistema de IA maduro; async nativo atende RNF-01; Pydantic dá validação de tool call de graça | NestJS (Node 22) | Ganha se o time é TS puro; perde bibliotecas de IA e obriga integração via HTTP com serviço Python |
| Orquestração de agentes | **LangGraph** | Grafo explícito com checkpointing atende RF-02 e o desenho multiagente; estado inspecionável facilita debug | CrewAI / agente único | CrewAI é mais rápido de escrever e menos controlável; agente único degrada com o número de regras |
| LLM principal | **Claude Sonnet** (Anthropic) | Boa aderência a instrução longa e tool use confiável — crítico para RN-04.3 e RN-09.4 | GPT-4.1 / Gemini 2.5 | Fica como fallback via `LlmPort`; troca sem mexer no domínio |
| LLM auxiliar | **Modelo pequeno** (Haiku ou equivalente) | Classificação de intenção e extração de campos não precisam do modelo grande — corta ~60% do custo (RNF-06) | Modelo único para tudo | Simplifica o código, triplica a conta |
| Embeddings | **`text-embedding-3-small`** (1536d) | Custo baixo e qualidade suficiente para 500–2.000 imóveis (PR-02) | BGE-M3 self-hosted | Elimina custo por chamada; adiciona GPU/CPU e tempo de setup |
| Banco relacional + vetorial | **PostgreSQL 16 + pgvector** | Um banco só para dados e vetores; a busca híbrida da RN-09.1 fica um `JOIN`, não uma orquestração entre dois sistemas | Pinecone / Qdrant | Melhor em escala >1M vetores; na POC adiciona custo, latência de rede e consistência eventual |
| Cache e fila | **Redis 7** | Cache de sessão, debounce da RN-01.6, rate limit da RNF-16 e broker da fila em um componente | RabbitMQ / SQS | Mais garantias de entrega; mais um componente para operar |
| Workers | **Celery** (ou Dramatiq) com beat | Processamento assíncrono e agendamento da cadência de follow-up (RF-13) no mesmo runtime | Cron externo + Lambda | Escala melhor e custa menos parado; perde a coesão de deploy |
| Frontend | **Next.js 15 + React 19 + TypeScript** | SSR ajuda o LCP da RNF-04; um só projeto para dashboard e widget | Vite SPA | Build mais simples; perde SSR e roteamento pronto |
| UI | **Tailwind + shadcn/ui** | Componentes acessíveis por padrão, ajuda a RNF-39 | Material UI | Mais completo; mais pesado e com cara genérica |
| Tempo real | **WebSocket** (FastAPI) + SSE no dashboard | Chat web e atualização do painel (RN-17.3) | Polling a cada 30 s | Trivial de implementar; pior experiência e mais carga |
| WhatsApp | **Meta WhatsApp Cloud API** | Oficial, sem risco de bloqueio; templates para a RN-13.6 | Evolution API (não oficial) | Sobe em minutos e sem aprovação; risco real de banimento do número — inaceitável em algo que "poderia existir no mercado" |
| Transcrição de áudio | **Whisper API** | Atende RN-01.3 com esforço mínimo | `faster-whisper` local | Sem custo por minuto; exige infra e aumenta latência |
| Observabilidade de LLM | **Langfuse** (self-hosted ou cloud) | Traces, custo e evals de prompt em um lugar (RNF-36) | LangSmith | Integração mais fluida com LangChain; menos flexível para self-host |
| Observabilidade de infra | **OpenTelemetry + Prometheus + Grafana** | RNF-35, RNF-37, RNF-38 com padrão aberto | Datadog | Muito melhor pronto-para-uso; custo alto para POC |
| Testes | **pytest + pytest-asyncio + Playwright** | Unidade, integração e E2E; evals de IA como testes (RNF-26) | Jest + Cypress | Só faz sentido se o backend for Node |
| CI/CD | **GitHub Actions** | Lint, testes, `gitleaks` (RNF-14), build e deploy automático | GitLab CI | Equivalente; escolha segue onde o repositório vive |
| Infra / deploy | **Docker + AWS ECS Fargate** (RDS Postgres, ElastiCache, S3) | Escala horizontal da RNF-08 sem gerir servidor | Railway / Render | Sobem em uma tarde e custam quase nada — melhor escolha se o tempo de hackathon apertar; menos controle de rede e escala |
| IaC | **Terraform** | Ambiente reproduzível e revisável em PR | Console da AWS | Rápido agora, impossível de reproduzir depois |

### 4.3 Diagrama conceitual

```mermaid
flowchart TB
    subgraph Canais
        WA[WhatsApp Cloud API]
        WEB[Widget Web - Next.js]
        DASH[Dashboard - Next.js]
    end

    subgraph Aplicacao
        API[API FastAPI - Ingress e REST]
        FILA[Redis - Fila e Cache]
        WORKER[Worker Celery - Orquestrador]
        BEAT[Scheduler - Cadencia de Follow-up]
    end

    subgraph Agentes
        SUP[Supervisor - Roteador de Intencao]
        QUAL[Agente Qualificador]
        INV[Agente Investidor]
        CONS[Agente Consultor de Imoveis]
        AGD[Agente Agendador]
        RES[Agente Redator de Resumo]
    end

    subgraph Dados
        PG[(PostgreSQL + pgvector)]
        S3[(S3 - Midias)]
    end

    subgraph Externos
        LLM[Provedor LLM - Primario e Fallback]
        EMB[API de Embeddings]
        CAL[Google Calendar]
        CRM[CRM via Webhook]
        OBS[Langfuse e OpenTelemetry]
    end

    WA -->|webhook assinado| API
    WEB -->|websocket| API
    DASH -->|REST + SSE| API
    API --> FILA
    FILA --> WORKER
    BEAT --> FILA
    WORKER --> SUP
    SUP --> QUAL
    SUP --> INV
    SUP --> CONS
    SUP --> AGD
    SUP --> RES
    QUAL --> PG
    CONS --> PG
    AGD --> PG
    AGD --> CAL
    RES --> CRM
    WORKER --> PG
    WORKER --> S3
    SUP --> LLM
    CONS --> EMB
    WORKER --> OBS
    WORKER -->|resposta| API
    API -->|envio| WA
```

Fluxo de uma mensagem, em uma linha: o webhook valida a assinatura, grava a mensagem e enfileira em menos de 300 ms; o worker carrega o estado do grafo, o supervisor roteia para o agente certo, o agente usa tool calls contra o Postgres, a resposta passa pelo guardrail de validação e volta ao canal de origem.

### 4.4 Integrações e serviços de IA

| Integração | Protocolo | Direção | Tratamento de falha |
|---|---|---|---|
| WhatsApp Cloud API | REST + webhook assinado (HMAC SHA-256) | Bidirecional | Retry com backoff (3×); falha permanente vira alerta e tarefa manual |
| Provedor de LLM | HTTPS / SDK | Saída | Timeout 15 s, 2 retries, fallback de provedor, depois handoff (RNF-27) |
| API de Embeddings | HTTPS | Saída | Reindexação em fila; falha não bloqueia o atendimento, apenas atrasa a indexação |
| Google Calendar | OAuth2 + REST | Saída | Opcional por feature flag; falha não impede o agendamento no banco |
| CRM | Webhook HTTP com payload versionado | Saída | 3 retries exponenciais + dead-letter queue |
| Langfuse / OTel | SDK assíncrono | Saída | Best-effort: falha de telemetria nunca derruba requisição |

**Estratégia de RAG.** Indexação por imóvel (não por chunk arbitrário): cada imóvel vira um documento único, porque o registro já é curto e coeso — fragmentar destruiria a associação entre característica e preço. O texto embeddado combina descrição, bairro, tipologia e diferenciais; os campos numéricos ficam **fora** do embedding e são resolvidos por filtro SQL, evitando o erro clássico de pedir ao vetor que entenda "até 600 mil". Recuperação em duas fases: filtro estruturado primeiro, similaridade por cosseno depois, sobre o subconjunto. Toda resposta que cita imóvel passa pela validação da RN-09.4.

**Engenharia de prompt.** Prompts versionados em arquivo, carregados por configuração (RN-19.4), com system prompt separado por agente. Conteúdo do lead sempre delimitado por marcador e declarado como dado não confiável (RNF-17). Few-shot de 3 a 5 exemplos por agente, extraídos de conversas reais anotadas. Saídas estruturadas por schema Pydantic em toda extração de campo — nada de parsear texto livre.

**Avaliação de qualidade.** Conjunto de 50 conversas sintéticas cobrindo os três cenários do briefing (compra, investimento, follow-up) mais casos de borda: lead evasivo, mudança de intenção no meio, tentativa de prompt injection, pedido fora de escopo. Métricas por execução: acurácia de intenção (alvo ≥ 90%), precisão de extração de campos (≥ 85%), taxa de alucinação (< 2%), aderência ao tom. Roda no CI a cada alteração de prompt e bloqueia merge em regressão.

---

## 5. Modelo de Dados (Conceitual)

Campos marcados com **DP** são dados pessoais sob LGPD e estão sujeitos aos RNF-19 a RNF-24: criptografia em repouso, mascaramento em log e no dashboard, e eliminação conforme política de retenção.

### 5.1 Entidades principais

**Lead** — pessoa que entrou em contato.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| tenant_id | UUID | Sim | Multi-tenant futuro (PR-03) |
| nome | varchar(120) | Não | **DP** — informado na conversa |
| telefone | varchar(20) | Sim | **DP** — E.164, único por tenant |
| email | varchar(160) | Não | **DP** |
| canal_origem | enum | Sim | `WHATSAPP`, `WEB` |
| utm_origem | varchar(80) | Não | Campanha de aquisição |
| status | enum | Sim | `NOVO`, `EM_CONVERSA`, `QUALIFICADO`, `AGENDADO`, `HANDOFF`, `DORMENTE`, `DESCARTADO` |
| score | smallint | Sim | 0–100, default 0 |
| temperatura | enum | Sim | `FRIO`, `MORNO`, `QUENTE` |
| corretor_id | UUID | Não | FK → Corretor, após roteamento |
| opt_out | boolean | Sim | Default false (RF-14) |
| opt_out_em | timestamptz | Não | Evidência de LGPD |
| consentimento_marketing | boolean | Sim | Default false (RNF-19) |
| criado_em / atualizado_em | timestamptz | Sim | |

**Conversa** — sessão de atendimento de um lead.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| lead_id | UUID | Sim | FK → Lead |
| canal | enum | Sim | `WHATSAPP`, `WEB` |
| status | enum | Sim | `ATIVA`, `AGUARDANDO_LEAD`, `SILENCIADA`, `ENCERRADA` |
| intencao_atual | enum | Sim | Ver RN-03.1 |
| intencao_confianca | numeric(3,2) | Sim | 0–1 |
| resumo_contexto | text | Não | Resumo comprimido (RN-02.2) |
| estado_grafo | jsonb | Sim | Checkpoint do LangGraph |
| perguntas_feitas | smallint | Sim | Limite da RN-05.5 |
| ultima_msg_lead_em | timestamptz | Não | Base da cadência e da janela de 24 h |
| encerrada_em | timestamptz | Não | |

**Mensagem** — cada turno registrado.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| conversa_id | UUID | Sim | FK → Conversa |
| papel | enum | Sim | `LEAD`, `AGENTE`, `CORRETOR`, `SISTEMA` |
| conteudo | text | Sim | **DP** — pode conter dado pessoal |
| tipo | enum | Sim | `TEXTO`, `AUDIO`, `IMAGEM`, `DOCUMENTO`, `TEMPLATE` |
| midia_url | text | Não | Ponteiro para S3 |
| provider_message_id | varchar(80) | Não | Único — idempotência da RN-01.5 |
| agente_origem | varchar(40) | Não | Qual subagente respondeu |
| tokens_entrada / tokens_saida | integer | Não | Base do custo (RN-17.4) |
| custo_usd | numeric(10,6) | Não | |
| latencia_ms | integer | Não | |
| criado_em | timestamptz | Sim | |

**Qualificacao** — estado estruturado do que o lead procura (1:1 com Conversa).

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| conversa_id | UUID | Sim | FK, único |
| tipo_operacao | enum | Não | `COMPRA`, `ALUGUEL`, `INVESTIMENTO` |
| preco_min / preco_max | bigint | Não | Centavos (RN-05.6) |
| regioes | text[] | Não | Bairros/zonas de interesse |
| tipo_imovel | enum | Não | `APARTAMENTO`, `CASA`, `COBERTURA`, `TERRENO`, `COMERCIAL` |
| quartos_min / vagas_min | smallint | Não | |
| urgencia_dias | smallint | Não | Prazo de decisão |
| forma_pagamento | enum | Não | `A_VISTA`, `FINANCIAMENTO`, `A_AVALIAR` |
| tem_imovel_para_vender | boolean | Não | |
| perfil_investidor | enum | Não | `RENDA`, `VALORIZACAO`, `MISTO` (RN-07.2) |
| ticket_investimento | bigint | Não | Centavos |
| retorno_esperado_pct | numeric(4,2) | Não | % a.a. |
| campos_recusados | text[] | Não | RN-05.7 |
| completude_pct | smallint | Sim | Derivado, 0–100 |

**Imovel** — item do catálogo simulado.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| codigo | varchar(20) | Sim | Único, legível pelo corretor |
| titulo | varchar(160) | Sim | |
| descricao | text | Sim | Fonte do embedding |
| tipo | enum | Sim | Mesmo domínio de `tipo_imovel` |
| operacao | enum | Sim | `VENDA`, `ALUGUEL`, `AMBOS` |
| preco_venda / preco_aluguel | bigint | Não | Centavos; ao menos um obrigatório |
| condominio / iptu_mensal | bigint | Não | Centavos |
| bairro / cidade / uf | varchar | Sim | Indexados |
| zona | enum | Não | `NORTE`, `SUL`, `LESTE`, `OESTE`, `CENTRO` |
| latitude / longitude | numeric(9,6) | Não | Distância e mapa |
| area_util_m2 | integer | Sim | |
| quartos / suites / banheiros / vagas | smallint | Sim | |
| caracteristicas | text[] | Não | Ex.: varanda gourmet, pet friendly |
| fotos | text[] | Não | URLs |
| status | enum | Sim | `DISPONIVEL`, `RESERVADO`, `VENDIDO`, `ALUGADO`, `INATIVO` |
| embedding | vector(1536) | Não | pgvector, índice IVFFlat |
| embedding_atualizado_em | timestamptz | Não | Controle da RN-08.3 |

**Corretor**

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| nome | varchar(120) | Sim | **DP** — ver a Emenda E-01 abaixo: **em claro**, contra a regra de criptografia em repouso |
| email / telefone | varchar | Sim | **DP** — canais de notificação. Ver a Emenda E-01 abaixo: **em claro** |
| creci | varchar(20) | Não | |
| especialidades | text[] | Sim | `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `INVESTIMENTO_ALTO_TICKET` |
| regioes_atuacao | text[] | Sim | Normalizadas com `dobrar()` na escrita, como `bairro_busca` — ver a D4 do desenho da TEC-196 |
| horario_trabalho | jsonb | Sim | Ver a Emenda E-02 abaixo: vira `horario_inicio` + `horario_fim`, inteiros de hora |
| capacidade_diaria | smallint | Sim | Máximo de visitas/dia |
| ativo | boolean | Sim | |

- **Emenda E-01 (TEC-196, 12/09/2026):** `nome`, `email` e `telefone` ficam **em claro**, e não cifrados em repouso como a regra dos campos **DP** (seção 5, parágrafo de abertura) determina. Duas razões. **O repo não cifra isto nem para o lead:** `messages.sender_external_id` e `messages.conversation_key` guardam o telefone do titular e são `varchar`; o que este sistema cifra é *conteúdo* (`text_body`, `raw_payload`, os resumos), nunca *identificador* — cifrar o contato do corretor instituiria uma política mais estrita para o funcionário do que para o titular que a LGPD protege. **E cifrar destruiria a única defesa contra corretor duplicado:** o nonce aleatório do AES-GCM faz, por desenho, a busca por igualdade deixar de existir, então `UNIQUE(email)` não funcionaria sobre coluna cifrada, e duas linhas do mesmo corretor passariam — fazendo a notificação da RN-16.2 sair em duplicata. A alternativa de cifrar com um HMAC determinístico à parte foi descartada: acrescenta um segredo ao ciclo de vida e produz um identificável estável, que é o que a cifra existia para evitar. Ver a D1 do desenho.
- **Emenda E-02 (TEC-196, 12/09/2026):** `horario_trabalho jsonb` com "janelas por dia da semana" vira **`horario_inicio` e `horario_fim`, inteiros de hora**. É a forma que o repo já usa para janela de atendimento (`followup_horario_inicio`/`followup_horario_fim` em `app/config.py`, consumidos por `outbound/horario.py`), e é o que o critério de aceite da TEC-196 exercita — *"um corretor com jornada de 9h às 18h"*, uma janela, sem dia. **Consequência declarada: sábado meio período não cabe**, embora o PR-06 já diga que o corretor atende "de segunda a sábado, 9h–19h"; quando a agenda real da TEC-170 chegar, isto é migration. Ver a D2 do desenho.

**Recomendacao** — imóvel apresentado a um lead.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| conversa_id / imovel_id | UUID | Sim | FKs |
| score_match | numeric(4,3) | Sim | Relevância da RN-09.6 |
| motivo_match | text | Sim | Explicabilidade |
| reacao_lead | enum | Não | `INTERESSE`, `DESCARTE`, `NEUTRO`, `SEM_RESPOSTA` |
| motivo_descarte | varchar(80) | Não | Realimenta o filtro (RN-10.4) |
| apresentado_em | timestamptz | Sim | |

**Agendamento**

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| lead_id / corretor_id | UUID | Sim | FKs |
| imovel_id | UUID | Não | Nulo em reunião de consultoria |
| tipo | enum | Sim | `VISITA_PRESENCIAL`, `REUNIAO_REMOTA` |
| inicio_em / fim_em | timestamptz | Sim | Índice de unicidade por corretor + intervalo |
| status | enum | Sim | Ver RN-12.5 |
| origem | enum | Sim | `AGENTE`, `CORRETOR` |
| calendar_event_id | varchar(120) | Não | Referência externa |
| lembrete_24h_em / lembrete_2h_em | timestamptz | Não | Idempotência do envio |

**FollowUp** — tentativa programada de reengajamento.

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| conversa_id | UUID | Sim | FK |
| tentativa_numero | smallint | Sim | Posição na cadência (RN-13.1) |
| agendado_para | timestamptz | Sim | Já ajustado à janela da RN-13.3 |
| status | enum | Sim | `PENDENTE`, `ENVIADO`, `CANCELADO`, `FALHOU`, `RESPONDIDO` |
| usou_template | boolean | Sim | RN-13.6 |
| template_nome | varchar(80) | Não | |
| enviado_em | timestamptz | Não | |

**Handoff**

| Campo | Tipo | Obrig. | Observação |
|---|---|---|---|
| id | UUID | Sim | PK |
| channel + conversation_key | varchar | Sim | **Emenda E-03 (TEC-174, 12/09/2026):** a identidade do lead é este par, e não `conversa_id`. Não existe tabela `conversas` — a entidade foi deferida para a TEC-130 — e o par já é a identidade em `lead_qualification`, `followups`, `optout_events` e `moderation_events`. Criar `conversa_id` agora instituiria uma segunda identidade concorrente com a que quatro tabelas usam. Ver a D2 do desenho. |
| corretor_id | UUID | Não | Nulável, **e com FK desde a TEC-196** (12/09/2026), que criou a tabela alvo. A ausência de FK que a Emenda E-02 da RN-16.1 declarou "provisória por construção" terminou; a nulabilidade permanece, porque alocar é a TEC-166 |
| gatilho | enum | Sim | Ver RN-16.1 |
| prioridade | enum | Sim | `ALTA`, `NORMAL` |
| resumo | text | Sim | Gerado no RF-15 |
| resumo_fallback | boolean | Sim | Indica geração determinística (RN-15.4) |
| sla_limite_em | timestamptz | Não | RN-16.3. **Nulável desde a TEC-178** (13/09/2026), contra o "Sim" original: o prazo usa a jornada do corretor destinatário (Emenda E-01 da RN-16.3), então é gravado no job de notificação e não na criação — a coluna fica nula por alguns segundos. E fica nula **para sempre** no handoff sem destinatário, que escala na hora e não tem prazo porque não há a quem cobrar (Emenda E-02). Nulo aqui significa "ainda não notificado" ou "não havia a quem cobrar", nunca "prazo zero" |
| aceito_em | timestamptz | Não | |
| status | enum | Sim | `PENDENTE`, `ACEITO`, `ESCALADO`, `CONCLUIDO` |
| crm_sincronizado_em | timestamptz | Não | RN-16.5 |

**Usuario** (acesso ao dashboard) — `id`, `nome` **DP**, `email` **DP**, `papel` (`ADMIN`, `GERENTE`, `CORRETOR`, `LEITURA`), `corretor_id` opcional, `mfa_habilitado`, `ativo`.

**EventoAuditoria** — `id`, `ator_tipo` (`USUARIO`, `AGENTE`, `SISTEMA`), `ator_id`, `acao`, `entidade`, `entidade_id`, `dados_antes` jsonb, `dados_depois` jsonb, `ip`, `criado_em`. Append-only, sem update nem delete (RNF-18).

**ConfiguracaoAgente** — `id`, `chave`, `valor` jsonb, `versao`, `autor_id`, `ativo`, `criado_em`. Guarda prompts, pesos de score e cadências (RN-19.3, RN-19.4).

### 5.2 Relacionamentos

- `Lead 1:N Conversa` — o lead volta em momentos diferentes; cada retorno após 30 dias abre nova conversa (RN-02.3).
- `Conversa 1:N Mensagem` — ordenadas por `criado_em`.
- `Conversa 1:1 Qualificacao` — o estado estruturado acompanha a sessão, não o lead, porque critérios mudam entre uma busca e outra.
- `Conversa 1:N Recomendacao N:1 Imovel` — tabela associativa com atributos próprios (score, reação).
- `Conversa 1:N FollowUp` e `Conversa 1:N Handoff`.
- `Lead 1:N Agendamento N:1 Corretor`; `Agendamento N:1 Imovel` (opcional).
- `Corretor 1:1 Usuario` (opcional — nem todo usuário é corretor).
- `Lead N:1 Corretor` — corretor responsável atual.

### 5.3 Diagrama ER

```mermaid
erDiagram
    LEAD ||--o{ CONVERSA : inicia
    LEAD ||--o{ AGENDAMENTO : possui
    LEAD }o--|| CORRETOR : atribuido_a
    CONVERSA ||--o{ MENSAGEM : contem
    CONVERSA ||--|| QUALIFICACAO : descreve
    CONVERSA ||--o{ RECOMENDACAO : gera
    CONVERSA ||--o{ FOLLOWUP : agenda
    CONVERSA ||--o{ HANDOFF : produz
    IMOVEL ||--o{ RECOMENDACAO : aparece_em
    IMOVEL ||--o{ AGENDAMENTO : visitado_em
    CORRETOR ||--o{ AGENDAMENTO : conduz
    CORRETOR ||--o{ HANDOFF : recebe
    CORRETOR ||--o| USUARIO : acessa
    USUARIO ||--o{ EVENTOAUDITORIA : registra
    USUARIO ||--o{ CONFIGURACAOAGENTE : versiona

    LEAD {
        uuid id PK
        varchar telefone
        varchar nome
        smallint score
        enum temperatura
        boolean opt_out
    }
    CONVERSA {
        uuid id PK
        uuid lead_id FK
        enum intencao_atual
        jsonb estado_grafo
        enum status
    }
    MENSAGEM {
        uuid id PK
        uuid conversa_id FK
        enum papel
        text conteudo
        numeric custo_usd
    }
    QUALIFICACAO {
        uuid id PK
        uuid conversa_id FK
        bigint preco_max
        smallint quartos_min
        smallint urgencia_dias
    }
    IMOVEL {
        uuid id PK
        varchar codigo
        bigint preco_venda
        varchar bairro
        vector embedding
    }
    RECOMENDACAO {
        uuid id PK
        uuid conversa_id FK
        uuid imovel_id FK
        enum reacao_lead
    }
    AGENDAMENTO {
        uuid id PK
        uuid lead_id FK
        uuid corretor_id FK
        timestamptz inicio_em
        enum status
    }
    FOLLOWUP {
        uuid id PK
        uuid conversa_id FK
        smallint tentativa_numero
        timestamptz agendado_para
    }
    HANDOFF {
        uuid id PK
        uuid conversa_id FK
        uuid corretor_id FK
        text resumo
        enum status
    }
    CORRETOR {
        uuid id PK
        varchar nome
        text especialidades
        jsonb horario_trabalho
    }
    USUARIO {
        uuid id PK
        varchar email
        enum papel
    }
    EVENTOAUDITORIA {
        uuid id PK
        varchar acao
        jsonb dados_depois
    }
    CONFIGURACAOAGENTE {
        uuid id PK
        varchar chave
        smallint versao
    }
```

**Índices críticos:** `lead(telefone, tenant_id)` único; `mensagem(conversa_id, criado_em)`; `mensagem(provider_message_id)` único parcial; `imovel(status, tipo, preco_venda, quartos)` composto para o filtro da RN-09.1; `imovel USING ivfflat (embedding vector_cosine_ops)`; `agendamento(corretor_id, inicio_em)` com constraint de exclusão por intervalo (`EXCLUDE USING gist`) para garantir a CA-11.2; `followup(status, agendado_para)` para o scheduler.

---

## 6. Endpoints de API Principais

REST sobre HTTPS, versionado em `/api/v1`, respostas em JSON. Autenticação por Bearer JWT no dashboard; webhooks autenticam por assinatura HMAC. Erros seguem formato único (RFC 7807 simplificado): `{ "erro": "codigo_legivel", "mensagem": "descrição", "detalhes": {}, "traceId": "uuid" }`. Listagens paginam por cursor: `?cursor=<opaco>&limite=25` (máx. 100).

### 6.1 Ingestão de mensagens

#### GET /api/v1/webhooks/whatsapp
Autenticação: `hub.verify_token` da Meta | Handshake de verificação do webhook.
Resposta `200 OK`: echo de `hub.challenge` em texto puro.

#### POST /api/v1/webhooks/whatsapp
Autenticação: assinatura `X-Hub-Signature-256` (RNF-15) | Público (validado por HMAC)

Entrada (resumo do payload da Meta):
```json
{ "entry": [{ "changes": [{ "value": { "messages": [{ "from": "5548999998888", "id": "wamid.xxx", "type": "text", "text": { "body": "Estou procurando apartamento na zona sul" } }] } }] }] }
```
`200 OK`: `{ "recebido": true }` — sempre em ≤ 300 ms, processamento assíncrono (RN-01.2).
Erros: 401 (assinatura inválida), 422 (payload malformado). Nunca 5xx para a Meta em erro de negócio — isso causaria reenvio em massa.

#### WS /api/v1/chat/ws?sessao={uuid}
Autenticação: token de sessão anônima emitido pelo widget | Canal web.
Eventos do cliente: `{ "tipo": "mensagem", "conteudo": "string" }`.
Eventos do servidor: `{ "tipo": "digitando" }`, `{ "tipo": "mensagem", "conteudo": "string", "imoveis": [] }`, `{ "tipo": "erro", "codigo": "string" }`.

### 6.2 Leads e conversas

#### GET /api/v1/leads
Autenticação: Bearer JWT | Papéis: `CORRETOR` (só os próprios), `GERENTE`, `ADMIN`
Query: `?temperatura=QUENTE&status=QUALIFICADO&intencao=COMPRA&corretorId=&busca=&ordenar=score_desc&cursor=&limite=25`

`200 OK`:
```json
{ "itens": [{ "id": "uuid", "nome": "Marina S.", "telefone": "+5548*****8888", "score": 82, "temperatura": "QUENTE", "status": "QUALIFICADO", "intencao": "COMPRA", "ultimaInteracaoEm": "ISO-8601" }], "proximoCursor": "opaco", "total": 143 }
```
Telefone mascarado conforme RN-18.5. Erros: 401, 403.

#### GET /api/v1/leads/{leadId}
Autenticação: Bearer JWT | Papéis: `CORRETOR` (próprio), `GERENTE`, `ADMIN`
`200 OK`: lead, qualificação consolidada, histórico de score, conversas, recomendações, agendamentos e follow-ups.
Erros: 403 (lead de outro corretor), 404.

#### GET /api/v1/conversas/{conversaId}/mensagens
Autenticação: Bearer JWT | Paginação por cursor, ordem cronológica.
`200 OK`: `{ "itens": [{ "id": "uuid", "papel": "LEAD", "conteudo": "string", "tipo": "TEXTO", "criadoEm": "ISO-8601" }], "proximoCursor": null }`

#### PATCH /api/v1/leads/{leadId}/qualificacao
Autenticação: Bearer JWT | Papéis: `CORRETOR`, `GERENTE`, `ADMIN`
Entrada: `{ "precoMax": 65000000, "quartosMin": 3, "urgenciaDias": 30 }`
`200 OK`: `{ "qualificacao": {}, "scoreAnterior": 61, "scoreAtual": 74, "temperatura": "QUENTE" }` — recálculo síncrono (RN-18.3) e evento de auditoria.
Erros: 400 (valor fora de domínio), 403, 409 (conversa encerrada).

#### POST /api/v1/conversas/{conversaId}/assumir
Autenticação: Bearer JWT | Papel: `CORRETOR`
`200 OK`: `{ "status": "SILENCIADA", "assumidoPor": "uuid", "assumidoEm": "ISO-8601" }` (RN-16.4)
Erros: 409 (já assumida por outro).
  - **Emenda E-01 (TEC-179, 13/09/2026):** passa a existir `POST /api/v1/conversas/devolver`, que o texto original desta seção não previa e que a RN-16.4 exige ("até ser reativado"). E **as duas rotas — assumir e devolver — endereçam a conversa pelo par `(channel, conversation_key)` no corpo**, não por um `{conversaId}`: não existe entidade conversa neste sistema, e inventá-la numa card de silenciamento seria desenhar o modelo de dados de meio sistema. Autenticação: `X-Admin-Token`, ver a Emenda E-01 da RN-16.4.

#### POST /api/v1/conversas/{conversaId}/mensagens
Autenticação: Bearer JWT | Papel: `CORRETOR` — envio manual pelo dashboard.
Entrada: `{ "conteudo": "string" }` → `201 Created`. Erros: 409 (fora da janela de 24 h sem template), 422 (lead com opt-out).

### 6.3 Catálogo de imóveis

#### GET /api/v1/imoveis
Autenticação: Bearer JWT | Query: `?tipo=APARTAMENTO&precoMax=60000000&quartosMin=2&bairro=Centro&status=DISPONIVEL&cursor=`
`200 OK`: lista paginada com os campos de vitrine.

#### POST /api/v1/imoveis/busca
Autenticação: Bearer JWT ou token interno do agente | Busca híbrida (RF-09).
Entrada:
```json
{ "consultaTexto": "apartamento com varanda perto da praia", "filtros": { "precoMax": 60000000, "quartosMin": 2, "regioes": ["Zona Sul"], "operacao": "VENDA" }, "limite": 10 }
```
`200 OK`:
```json
{ "itens": [{ "id": "uuid", "codigo": "AP-1042", "titulo": "string", "bairro": "string", "precoVenda": 58000000, "quartos": 2, "vagas": 1, "areaUtilM2": 74, "scoreMatch": 0.87, "motivoMatch": "string", "yieldBrutoAnual": 0.061 }], "relaxamentoAplicado": false, "totalCandidatos": 7 }
```
`yieldBrutoAnual` só é retornado quando o contexto é de investimento (RN-07.3). Erros: 400 (filtro inconsistente, ex.: `precoMin > precoMax`), 422.

#### POST /api/v1/imoveis/importar
Autenticação: Bearer JWT | Papel: `ADMIN` | `multipart/form-data` com CSV ou JSON.
`202 Accepted`: `{ "importacaoId": "uuid", "status": "PROCESSANDO" }`
  - **Emenda E-01 (TEC-156, 06/09/2026):** enquanto a TEC-201 não existir, a autenticação deste endpoint é o header `X-Admin-Token`, comparado em tempo constante com `CATALOGO_ADMIN_TOKEN`; token ausente ou errado devolve `403`. **Com a variável vazia o router não é registrado**, e a rota devolve `404` — rota que não existe não pode ser exposta por engano de configuração, o que uma rota respondendo `401` não garante. `Bearer JWT | Papel: ADMIN` continua sendo o alvo: a TEC-201 troca o corpo da dependência `exigir_admin` e nenhum handler muda. **Consequência declarada:** um segredo compartilhado não tem expiração, rotação nem papel — quem o tem pode reimportar o catálogo inteiro. Aceito porque o objeto é o catálogo de imóveis e não dado pessoal, ao contrário da reativação de opt-out da TEC-182, que por isso ficou sem rota HTTP.
#### GET /api/v1/imoveis/importacoes/{id} → `{ "status": "CONCLUIDO", "processados": 500, "inseridos": 497, "rejeitados": 3, "erros": [{ "linha": 12, "motivo": "preco_venda ausente" }] }` (RN-08.5)

#### POST /api/v1/imoveis · PATCH /api/v1/imoveis/{id} · DELETE /api/v1/imoveis/{id}
Autenticação: Bearer JWT | Papel: `ADMIN`. DELETE é lógico (`status=INATIVO`), nunca físico. Erros: 400, 403, 404, 409 (código duplicado).

### 6.4 Agendamentos

#### GET /api/v1/agendamentos/disponibilidade
Autenticação: Bearer JWT ou token interno do agente
Query: `?corretorId=&especialidade=COMPRA&regiao=Zona Sul&de=2026-08-25&ate=2026-08-28&duracaoMin=60`
`200 OK`: `{ "janelas": [{ "corretorId": "uuid", "corretorNome": "Paulo M.", "inicioEm": "2026-08-25T14:00:00-03:00", "fimEm": "2026-08-25T15:00:00-03:00" }] }` — no máximo 3 sugestões (RN-11.1).

#### POST /api/v1/agendamentos
Autenticação: Bearer JWT ou token interno do agente
Entrada: `{ "leadId": "uuid", "corretorId": "uuid", "imovelId": "uuid", "tipo": "VISITA_PRESENCIAL", "inicioEm": "2026-08-25T14:00:00-03:00" }`
`201 Created`: `{ "id": "uuid", "status": "CONFIRMADO", "calendarEventId": "string" }`
Erros: 409 (slot já ocupado — CA-11.2), 422 (fora do horário de trabalho ou antecedência < 3 h), 404.

#### PATCH /api/v1/agendamentos/{id} — remarcação e mudança de status
Entrada: `{ "status": "CANCELADO", "motivo": "string" }` ou `{ "inicioEm": "ISO-8601" }`
`200 OK`. Erros: 409 (conflito no novo horário), 422 (transição de status inválida — ex.: `REALIZADO` → `PROPOSTO`).

### 6.5 Handoff e follow-up

#### GET /api/v1/handoffs
Autenticação: Bearer JWT | Query: `?status=PENDENTE&prioridade=ALTA` — fila de trabalho do corretor.

#### POST /api/v1/handoffs/{id}/aceitar
`200 OK`: `{ "status": "ACEITO", "aceitoEm": "ISO-8601", "dentroDoSla": true }`. Erros: 409 (já aceito), 410 (escalado por SLA).
- **Emenda E-01 (TEC-178, 13/09/2026):** o 410 acima **nunca é levantado**. Aceitar um handoff `ESCALADO` passa a ser **permitido** — o mesmo 200 desta seção, gravando `aceito_em` e movendo o status para `ACEITO` — e não recusado. Aceitar depois da escalada é o caso real: o gerente cobrou e alguém pegou o lead; recusar puniria justamente o comportamento que a RN-16.3 quer produzir. O 409 continua reservado a handoff que já está `ACEITO` (ou `CONCLUIDO`, fora do escopo desta card) — a idempotência é até o primeiro aceite, não depois dele. `dentroDoSla` reflete o carimbo real: para um handoff aceito depois de escalado, `aceitoEm` vem depois de `sla_limite_em` e o campo sai `false`, sem que isso bloqueie o aceite — **exceto no handoff escalado sem destinatário** (Emenda E-02 da RN-16.3), cujo `sla_limite_em` é nulo para sempre: aí o campo sai `true` por vacuidade, nunca por pontualidade, e quem calcular a taxa de aceite no prazo da RN-17.1 precisa excluir `sla_limite_em IS NULL` do denominador. Autenticação: `X-Admin-Token` via `exigir_admin`, não Bearer JWT — mesma exposição que a Emenda E-01 da RN-19.5 já declarou para o módulo administrativo, aqui estendida a esta rota por não existir ainda a infraestrutura de papéis da TEC-201. Ver `src/mobia/api/routes/handoffs.py` e o relatório da Task 6.

#### POST /api/v1/leads/{leadId}/resumo
Autenticação: Bearer JWT | Regeneração sob demanda (RN-15.2).
`200 OK`: `{ "resumo": "string", "geradoEm": "ISO-8601", "fallback": false }`. Erros: 503 com resumo determinístico no corpo (RN-15.4).

#### POST /api/v1/conversas/{conversaId}/followups/cancelar
`200 OK`: `{ "cancelados": 2 }` — usado quando o corretor assume manualmente.

### 6.6 Dashboard e administração

#### GET /api/v1/metricas/funil
Query: `?de=2026-08-01&ate=2026-08-22&canal=&intencao=&corretorId=`
`200 OK`:
```json
{ "etapas": [{ "nome": "Novo", "quantidade": 320 }, { "nome": "Em conversa", "quantidade": 268 }, { "nome": "Qualificado", "quantidade": 141 }, { "nome": "Recomendado", "quantidade": 118 }, { "nome": "Agendado", "quantidade": 47 }, { "nome": "Handoff aceito", "quantidade": 39 }],
  "tempoMedioPrimeiraRespostaSeg": 4.2, "taxaQualificacao": 0.44, "taxaNoShow": 0.11, "slaHandoffCumpridoPct": 0.87 }
```

#### GET /api/v1/metricas/custo-ia
`200 OK`: `{ "custoTotalUsd": 38.42, "custoPorConversaUsd": 0.09, "custoPorLeadQualificadoUsd": 0.27, "tokensPorModelo": { "claude-sonnet": 4820000, "claude-haiku": 9310000 } }` (RN-17.4, RNF-06)

#### GET /api/v1/eventos/stream
SSE com atualizações em tempo real do dashboard: `lead.criado`, `lead.score_alterado`, `handoff.criado`, `agendamento.confirmado`.

#### GET · PUT /api/v1/configuracoes/{chave}
Autenticação: Bearer JWT | Papel: `ADMIN`
PUT entrada: `{ "valor": { "pesoUrgencia": 30 }, "comentario": "ajuste pós-teste" }`
`200 OK`: `{ "chave": "lead_scoring", "versao": 4, "ativoEm": "ISO-8601" }` (RN-19.3)

#### POST /api/v1/configuracoes/{chave}/rollback
Entrada: `{ "versao": 3 }` → `200 OK` em menos de 30 s (CA-19.2).

#### CRUD /api/v1/corretores
Papel: `ADMIN` (RN-19.2). Erros: 409 ao inativar corretor com agendamento futuro — exige reatribuição antes.

### 6.7 Conformidade LGPD

#### GET /api/v1/leads/{leadId}/dados-pessoais
Papel: `ADMIN` ou requisição autenticada do próprio titular | Exportação em JSON (portabilidade, RNF-21).

#### DELETE /api/v1/leads/{leadId}/dados-pessoais
Papel: `ADMIN` | `202 Accepted` — anonimização assíncrona preservando métricas agregadas; conclusão em até 15 dias, normalmente em minutos. Erros: 409 (retenção legal obrigatória em curso).

---

## 7. Critérios de Aceite e Riscos

### 7.1 Definition of Done

Um item só é considerado pronto quando todos estes pontos são verdadeiros:

- [ ] Todos os critérios de aceite (`CA-`) do requisito passam em teste automatizado.
- [ ] Cobertura de testes ≥ 75% no domínio (regras de negócio e scoring em 100%).
- [ ] Testes de integração cobrindo os adaptadores externos com mock e contrato.
- [ ] Eval de IA executada sem regressão nas métricas da seção 4.4, quando o item toca prompt ou agente.
- [ ] Nenhum `TODO`, credencial ou log de dado pessoal em claro no código.
- [ ] Migração de banco versionada (Alembic) e reversível.
- [ ] Endpoint documentado no OpenAPI, gerado automaticamente e revisado.
- [ ] Logs, métricas e traces emitidos para o novo caminho de código.
- [ ] Revisão por par aprovada e pipeline verde.

### 7.2 Critérios de release para produção

- [ ] Os 19 requisitos funcionais implementados e aceitos.
- [ ] RNFs medidos em homologação com evidência registrada — não estimados.
- [ ] Teste de carga executado no volume da PR-01 sem violar RNF-02.
- [ ] Teste de caos por componente: LLM fora, Redis fora, WhatsApp fora (RNF-32).
- [ ] Restauração de backup ensaiada e cronometrada dentro do RTO (RNF-30/31).
- [ ] Suíte de prompt injection sem falhas (RNF-17).
- [ ] Itens de LGPD atendidos: base legal documentada, aviso de privacidade publicado, endpoints de direito do titular funcionando, retenção configurada (RNF-19 a RNF-24).
- [ ] Templates de WhatsApp aprovados pela Meta (mínimo 3) — dependência externa, iniciar cedo.
- [ ] Plano de rollback testado: rollback de deploy em < 10 min e rollback de prompt em < 30 s.
- [ ] Alertas configurados e disparados ao menos uma vez em teste (RNF-38).
- [ ] Entregáveis do desafio prontos: repositório, README, documento de arquitetura, demo funcional, pitch técnico e explicação da IA utilizada.

### 7.3 Riscos técnicos

| ID | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| RT-01 | Alucinação: o agente inventa imóvel, preço ou condição, gerando promessa falsa ao cliente | Alta | Crítico | Dado factual só via tool call; validação pós-geração que bloqueia citação de imóvel fora dos candidatos (RN-09.4); eval de alucinação bloqueante no CI (RNF-26) |
| RT-02 | Indisponibilidade ou throttling do provedor de LLM durante a demo | Média | Alto | `LlmPort` com fallback de provedor; timeout de 15 s; cache das respostas do roteiro de demo; modo de degradação com handoff (RNF-27) |
| RT-03 | Aprovação da conta WhatsApp Business e dos templates atrasa além do hackathon | Alta | Alto | Iniciar verificação na semana 1; manter o widget web como canal principal da demo e o WhatsApp como diferencial; jamais depender de API não oficial |
| RT-04 | Custo de LLM estoura o orçamento da PR-08 durante os testes | Média | Médio | Modelo pequeno para classificação e extração; cache de embeddings; limite diário por ambiente com corte automático; painel de custo (RNF-06) |
| RT-05 | Prompt injection via mensagem do lead expõe prompt de sistema ou muda o comportamento | Média | Alto | Delimitação de conteúdo não confiável, instruções não sobrescrevíveis, suíte de 20 ataques no CI (RNF-17) |
| RT-06 | Qualidade da busca RAG baixa: recomendações fora do que o lead pediu | Média | Alto | Busca híbrida com filtro SQL antes do vetor (RN-09.1); conjunto de 30 consultas com gabarito e medição de precisão@3 |
| RT-07 | Conflito de agendamento por concorrência (dois leads no mesmo slot) | Média | Médio | Constraint de exclusão por intervalo no Postgres + lock otimista de 5 min (RN-11.4) |
| RT-08 | Vazamento de dado pessoal em log, trace ou prompt enviado ao provedor | Baixa | Crítico | Mascaramento no logger, pseudonimização antes do envio ao modelo (RNF-23), `gitleaks` e revisão de amostra de logs no DoD |
| RT-09 | Fila cresce sem controle em pico e a latência percebida explode | Baixa | Médio | Autoscaling de worker por profundidade de fila, backpressure, alerta acima de 500 itens (RNF-09) |
| RT-10 | Interpretação errada de data em linguagem natural gera visita no dia errado | Média | Médio | Confirmação obrigatória com data e hora absolutas antes de gravar (RN-11.3); testes com 20 expressões de data |
| RT-11 | Equipe sem experiência prévia em LangGraph consome o prazo em curva de aprendizado | Média | Médio | Spike de 1 dia na semana 1 com protótipo descartável; fallback para orquestração manual por máquina de estados se o spike falhar |

### 7.4 Riscos de negócio

| ID | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| RN-B01 | Rejeição do lead a atendimento automatizado — abandono na primeira mensagem | Média | Alto | Transparência desde o início (RN-04.1), saída para humano sempre disponível (RN-04.6), medição de taxa de abandono no primeiro turno |
| RN-B02 | Follow-up percebido como spam, gerando denúncia e bloqueio do número na Meta | Média | Crítico | Teto de 4 mensagens não respondidas (RN-13.7), janela de horário (RN-13.3), opt-out imediato (RF-14), monitoramento do indicador de qualidade do número |
| RN-B03 | Corretor não adota a ferramenta e continua atendendo pelo celular pessoal | Alta | Alto | Notificação no canal que ele já usa (WhatsApp/e-mail), resumo que economiza tempo real, SLA visível e ranking por aceite no dashboard |
| RN-B04 | Viés discriminatório no atendimento ou na recomendação, gerando risco reputacional e legal | Baixa | Crítico | Guardrail de conteúdo (RN-04.5), auditoria de recusas, revisão humana de amostra semanal de conversas |
| RN-B05 | Dependência de fornecedor único de LLM com mudança de preço ou de termos | Média | Médio | `LlmPort` com dois provedores homologados; custo por conversa monitorado; contrato revisado antes de produção |
| RN-B06 | Escopo do hackathon cresce (Voice AI, CRM, multi-tenant) e nada fica pronto | Alta | Alto | Escopo negativo explícito na seção 1.3; roadmap priorizado do Anexo B; corte por prioridade, não por qualidade |
| RN-B07 | Mudança regulatória ou fiscalização de LGPD sobre uso de IA em atendimento | Baixa | Alto | Base legal documentada, aviso de privacidade, registro de consentimento e trilha de auditoria desde o MVP |
| RN-B08 | Base simulada não convence na avaliação por parecer irreal | Média | Médio | Gerar catálogo com distribuição realista de bairros, preços e fotos; validar com um corretor real antes da demo |

---

## Anexo A — Rastreabilidade com os critérios de avaliação do desafio

| Critério do desafio | Onde é atendido |
|---|---|
| Arquitetura — organização | Monólito modular hexagonal com 7 módulos de fronteira explícita (4.1) |
| Arquitetura — escalabilidade | RNF-07 a RNF-10; fila, workers sem estado, extração de serviço prevista |
| Arquitetura — componentização | Ports & adapters: `MessagingPort`, `LlmPort`, `CrmPort`, `CalendarPort`, `VectorStorePort` (4.1) |
| IA — qualidade das respostas | Multiagente especializado (4.1), evals com métricas e gate no CI (4.4, RNF-26) |
| IA — humanização | RF-04 completo: tom, tamanho, uma pergunta por vez, indicador de digitação |
| IA — contexto conversacional | RF-02: persistência, resumo comprimido, checkpointing do grafo |
| UX — interface, clareza, usabilidade | RF-17 a RF-19, RNF-04, RNF-39 a RNF-42 |
| Inovação — diferenciais técnicos | RAG híbrido (RF-09), WhatsApp oficial, memória (RF-02), multiagentes (4.1), CRM via porta (RN-16.5), observabilidade de LLM (RNF-36), segurança (3.3), deploy em cloud (4.2) |
| Entregável — repositório e README | DoD e critérios de release (7.1, 7.2) |
| Entregável — arquitetura da solução | Seção 4 com diagrama Mermaid |
| Entregável — explicação da IA utilizada | Seção 4.4: RAG, prompts, avaliação, escolha de modelos |

**Diferenciais do briefing não incluídos no MVP:** Voice AI (chamada de voz) e conector nativo de CRM ficam fora por escopo (1.3), com ponto de extensão já previsto — respectivamente na `MessagingPort` e na `CrmPort`.

## Anexo B — Roadmap sugerido de execução

Prioridades: **P0** = sem isso não há demo; **P1** = diferencial competitivo; **P2** = se sobrar tempo.

| Semana | Entrega | Prioridade |
|---|---|---|
| 1 | Setup do repositório, CI, Docker, modelo de dados, migrações, seed de 500 imóveis; spike de LangGraph; início da verificação da conta Meta (RT-03) | P0 |
| 2 | Ingestão web + WhatsApp, memória conversacional, supervisor e agente qualificador; RF-01, RF-02, RF-03, RF-05 | P0 |
| 3 | RAG híbrido e agente consultor; lead scoring; RF-06, RF-08, RF-09, RF-10 | P0 |
| 4 | Agendamento, follow-up, handoff e resumo; RF-11 a RF-16 | P0/P1 |
| 5 | Dashboard, observabilidade, evals, hardening de segurança; RF-17 a RF-19, seção 3 | P1 |
| 6 | Deploy em cloud, teste de carga e caos, roteiro e ensaio do pitch, trilha de investidor refinada (RF-07) | P1/P2 |

Corte sob pressão de prazo, nesta ordem: Google Calendar → transcrição de áudio → SSE (vira polling) → trilha de investidor com indicadores → painel de custo. Nunca cortar: guardrail anti-alucinação (RT-01), opt-out (RF-14) e validação de assinatura do webhook (RNF-15).
