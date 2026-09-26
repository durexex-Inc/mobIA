# TEC-207 — Direitos do titular e retenção

**Status:** desenho aprovado, implementação pendente
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

**Viram cards próprias, no backlog:**
- a redação de dado sensível antes da persistência;
- a pseudonimização antes do LLM.

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

Função única, `anonimizar_lead(conn, *, channel, conversation_key)`, sync sobre `Connection` como a reindexação. Ela serve a eliminação a pedido e a retenção de 24 meses.

## D2 — Solicitação de titular

Tabela `solicitacoes_de_titular`:

| coluna | |
|---|---|
| `id` | UUID |
| `lead_ref` | HMAC do par (`auditoria/referencia.py::lead_ref`) — sobrevive à anonimização |
| `channel`, `conversation_key` | o par, **enquanto aberta**; vira nulo ao ser atendida ou recusada |
| `tipo` | `ELIMINACAO` ou `ACESSO` |
| `origem` | `WHATSAPP` ou `ADMIN` |
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
  - Responde com texto fixo, **com acento**: "Registrei seu pedido. Ele será atendido em até 15 dias."
- **O pedido de eliminação também registra opt-out.** Quem pede para apagar os dados não quer receber follow-up enquanto o pedido espera.

## D4 — Endpoints

Todos exigem a permissão nova `ATENDER_TITULAR`, só do ADMIN, fora de `_CONCEDIDAS` como `VER_AUDITORIA`.

| rota | o que faz |
|---|---|
| `GET /api/v1/titular/solicitacoes` | a fila, filtrável por status, ordenada pelo prazo |
| `GET /api/v1/leads/{leadId}/dados-pessoais` | exportação JSON: canal, telefone revelado, qualificação, transcrição inteira decifrada, agendamentos, consentimentos, datas. Registra `DADOS_EXPORTADOS`. Marca como atendida a solicitação `ACESSO` aberta, se houver |
| `DELETE /api/v1/leads/{leadId}/dados-pessoais` | 202 e job ARQ que roda `anonimizar_lead`. Marca como atendida a solicitação `ELIMINACAO` aberta, ou cria uma de origem `ADMIN` já atendida. 404 se o apelido não resolve, que é o caso do lead já anonimizado |
| `POST /api/v1/titular/solicitacoes/{id}/recusa` | recusa com motivo obrigatório (ex.: retenção legal). Registra `TITULAR_RECUSADO` |

`leadId` é o apelido de `referencias_de_lead`, como no resto do dashboard. A anonimização apaga a linha de `referencias_de_lead` do par antigo: o apelido deixa de resolver, e o que `leads/detalhe.py` já prevê ("um apelido que sobreviver às mensagens dele é 404") passa a acontecer.

## D5 — Retenção

Sweep diário, `sweep_retencao_de_leads`, depois do da auditoria:

- **Transcrição com mais de 12 meses**, de qualquer lead: o conteúdo das mensagens vira nulo e a mídia correspondente é apagada. A linha fica.
- **Lead sem conversão** (nenhum handoff `ACEITO` ou `CONCLUIDO`) **com mais de 24 meses desde a última interação** (`max(messages.created_at)`, a mesma de `leads/repositorio.py::_ultima_interacao`): `anonimizar_lead`. Lead com solicitação `ELIMINACAO` aberta também é anonimizado por aqui, e a solicitação passa a atendida.
- Em lotes, com commit por lead, para não segurar lock longo.

## D6 — Auditoria

Ações novas no vocabulário da trilha, com migration que recria o CHECK (molde das 0056/0057):
- `TITULAR_SOLICITOU`: quando o pedido chega, pelo WhatsApp ou pelo ADMIN.
- `DADOS_EXPORTADOS`.
- `LEAD_ANONIMIZADO`: registrada pelo job e pelo sweep, com `detalhes.motivo` igual a `solicitacao` ou `retencao`.
- `TITULAR_RECUSADO`.

`Entidade` ganha `solicitacao_de_titular`. `tests/unit/test_auditoria_vocabulario.py` prende as cópias.

## O que a card não entrega

- **Redação de dado sensível e pseudonimização antes do LLM:** cards filhas.
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
  - Turno com "quero apagar meus dados": registra a solicitação, o opt-out e responde o texto fixo sem chamar o modelo.
  - Endpoints: permissão, exportação completa, 202 e job, recusa, 404 após anonimizar.
  - Sweep: transcrição de 13 meses esvaziada; lead não convertido de 25 meses anonimizado; lead convertido de 25 meses mantido.

## Critérios de aceite

| Cenário | Situação |
|---|---|
| Exportar os dados em formato portável | Exercitado |
| Eliminação remove o dado pessoal e preserva a métrica | Exercitado, com o funil e o custo comparados antes e depois |
| Pedido pelo próprio WhatsApp é reconhecido | Exercitado |
| Dado sensível é redigido | **Card filha** |
| Pseudonimização antes do envio ao modelo | **Card filha** |
| Consentimento de marketing com evidência | Já atendido pela TEC-363 (web); nada muda |

## Emendas ao SRS

- **RNF-21:** o pedido pelo WhatsApp entra numa fila atendida pelo ADMIN; não há execução automática.
- **RNF-22:** "lead sem conversão" = sem handoff `ACEITO` ou `CONCLUIDO`; a anonimização troca o par por pseudônimo aleatório e mantém as linhas sem conteúdo.
