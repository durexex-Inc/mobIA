# TEC-194 — Intervir na conversa e editar a qualificação

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-194](https://eduardodurieuxlopes.atlassian.net/browse/TEC-194) — épico TEC-189
**Branch:** `feat/tec-194-intervir-e-editar-qualificacao`
**Origem:** RF-18, RN-18.3, RN-18.4, RN-16.4 (SRS v1.0) · TEC-179, TEC-193, TEC-195, TEC-206 · telas TEC-327, TEC-328, TEC-329

## O problema

A card pede quatro coisas ao corretor: falar com o lead pelo dashboard (e com isso calar o agente), corrigir a qualificação, forçar o recálculo do score e devolver a conversa ao agente. O levantamento achou metade pronta e metade inalcançável:

| pedido | o que existe | o que falta |
|---|---|---|
| silenciar e devolver | `POST /conversas/assumir` e `/devolver` (TEC-179, TEC-278), com o par no **corpo** | desde a TEC-195 o dashboard só conhece o `leadId` — o par é o telefone, e a tela não o tem |
| falar com o lead | **nada**: nenhum escritor de `messages` com `role=CORRETOR`; a guarda de silêncio de `GuardedOutbound` barra todo envio de conversa assumida, e o comentário dela já previa: *"quando a rota de envio manual do corretor chegar, ela ainda encontra o proprio envio barrado aqui"* | a rota, um `kind` que atravesse a guarda de silêncio, e uma porta de saída na API — hoje só o worker monta o `RoteadorPorCanal` |
| editar a qualificação | `lead_qualification`, `registrar_recalculo`, `CAUSA_EDICAO_MANUAL` (sem produtor), `lead_score_audit.autor` (sempre nulo), `Acao.QUALIFICACAO_ALTERADA` (sem chamador) | a rota, e o autor chegar à trilha de score |
| forçar recálculo | `registrar_recalculo(causas_externas=...)` | a rota e uma causa `RECALCULO_MANUAL` |

## D1 — Tudo pelo `leadId`

```
POST  /api/v1/leads/{leadId}/assumir
POST  /api/v1/leads/{leadId}/devolver
POST  /api/v1/leads/{leadId}/mensagens        { "texto": "…" }
PATCH /api/v1/leads/{leadId}/qualificacao     { "faixaPrecoMaxCentavos": 80000000, … }
POST  /api/v1/leads/{leadId}/score/recalcular
```

Todas com `ATENDER_LEAD`, com o mesmo recorte do CORRETOR que o detalhe usa (TEC-193, D2): 404 para apelido inexistente, 403 com `ACESSO_NEGADO` para lead de outro corretor.

**`/conversas/assumir` e `/devolver` ficam**, sem mudança. Removê-las não é desta card, e elas são o que o `X-Admin-Token` usa hoje. As novas chamam a mesma lógica, que sai das rotas para uma função de domínio (`atendimento/tomada.py`) — duas cópias do "aceita junto o handoff" (D6 da TEC-179) e do "conclui junto" (D2 da TEC-278) divergiriam.

## D2 — Quem fala é um corretor cadastrado

**Decisão do Eduardo, 26/09/2026.** `atendimento_humano.assumido_por` tem FK para `corretores.id`, e é o `corretor_id` que a guarda, a devolução e a lista usam. **As rotas novas tiram o corretor da claim do JWT, e não do corpo.** Usuário sem vínculo de corretor — um GERENTE sem cadastro de corretor, ou o `X-Admin-Token` — recebe **409** com a razão escrita: não há em nome de quem gravar o atendimento. Continuar aceitando `corretor_id` no corpo reabriria, para ADMIN e GERENTE, o "falar em nome de terceiro" que a Emenda E-05 da RN-16.4 tolerou por falta de identidade — e aqui a identidade existe.

## D3 — Enviar mensagem assume a conversa, e o envio é síncrono

Primeiro cenário: *"a mensagem chega ao lead no canal de origem, e o agente entra em modo silencioso"*. Então `POST /mensagens`:

1. **assume a conversa** para o corretor que envia (idempotente se já é dele); se outro corretor a tem, **409** — não se fala por cima de um colega;
2. **envia pela porta de saída**, ancorado na última fala do lead (`messages/ancora.py`), com `kind = "corretor:<id-da-fala>"`;
3. **só depois de aceito, grava a fala** em `messages` com `role=CORRETOR`, `direction=OUTBOUND`, texto cifrado — o mesmo "envia, depois grava" que o turno usa para a fala do agente. Gravar antes deixaria na transcrição uma fala que o lead nunca recebeu.

**Síncrono, e não por fila.** A tela precisa saber, na resposta, se a mensagem saiu: a TEC-328 pede que o corretor seja avisado quando a janela de 24 h do WhatsApp fechou, e uma fila responderia "aceito" antes de saber. O custo é a requisição esperar a Meta; o corretor clicou "enviar" e está esperando isso mesmo. Por isso **a API passa a montar um `RoteadorPorCanal`**, igual ao do worker, com os mesmos adaptadores e as mesmas guardas — por uma dependência preguiçosa (`api/saida.py`) e não no `lifespan`, que o `ASGITransport` dos testes não roda.

**Desfechos:**

| o que aconteceu | resposta |
|---|---|
| aceito pelo canal | **201** `{ "id", "em" }` |
| `EnvioForaDaJanela` (Meta 131047) | **409** `janela_fechada` — a tela oferece template, que é outra card |
| guarda de opt-out barrou | **409** `lead_em_optout` |
| `EnvioRetentavel` / `EnvioRecusado` | **502** — nada gravado, o corretor tenta de novo |

**O `kind` do corretor atravessa a guarda de silêncio e não a de opt-out** — decisão do Eduardo, 26/09/2026. Silêncio é "o agente não fala por cima do corretor" — o corretor é justamente quem pode. Opt-out é o lead pedindo para não receber mensagem, e isso vale para gente também: uma pessoa ligada à imobiliária insistindo depois do "pare" é o caso que a LGPD mais pune. **O kind é único por fala** (o id novo), então a reserva de `outbound_dispatches` nunca suprime um segundo envio legítimo, e o `False` da guarda só pode significar opt-out.

**Não passa por moderação nem por limite de tamanho do agente**: é texto de uma pessoa da operação, que responde por ele. O teto é o do canal — 4096 caracteres, o da Meta para texto — validado na borda.

## D4 — Editar a qualificação

`PATCH` parcial: só os campos presentes mudam; `null` explícito limpa. Editáveis: `faixaPrecoMinCentavos`, `faixaPrecoMaxCentavos`, `regiao`, `tipoImovel`, `quartos`, `vagas`, `urgencia`, `formaPagamento`, `temImovelParaVender`. Os enumerados são conferidos contra o vocabulário de `agente/schemas.py`; mínimo acima do máximo é 422.

**`intencao` não é editável.** Trocar a intenção dispara `aplicar_mudanca_de_intencao`, que descarta orçamento dito sob outra banda e grava trilha própria (TEC-136) — é uma operação com regra, e não um campo. Fica para quando alguém pedir.

**Na mesma transação:** o upsert dos campos, `registrar_recalculo(causas_externas=(EDICAO_MANUAL,), autor=…)` e um `QUALIFICACAO_ALTERADA` **por campo alterado** na trilha, com `campo=<nome>`. Campo enviado com o valor que já tinha não conta como alterado. O valor não vai para a trilha, pela regra da TEC-206: *"o registro diz qual campo mudou, não para quê"*. A resposta traz `scoreAnterior`, `scoreAtual` e `temperatura`, como a seção 6.2 escreve.

**Quando a edição faz o lead cruzar a borda da RN-05.3, `qualificado_em` é carimbado** pela mesma função que o turno usa (`carimbar_qualificacao`). O carimbo é o da primeira travessia, e ela aconteceu; quem a causou fica na trilha de score, com `EDICAO_MANUAL` e o autor. Consequência: o funil passa a contar como qualificado o lead que o corretor completou.

**A linha de qualificação é criada se não existir** — ao contrário de `carimbar_qualificacao`, que recusa isso para não inventar estado. Aqui o estado não é inventado: uma pessoa o informou.

**Conversa encerrada é 409**, como a seção 6.2 escreve. Corrigir a ficha de um lead que acabou não reabre nada e mexeria no score que o funil já contou.

## D5 — Forçar o recálculo

`POST /score/recalcular` chama `registrar_recalculo(causas_externas=(RECALCULO_MANUAL,), autor=…)`. **Causa nova, e não `EDICAO_MANUAL`**: o terceiro cenário diz *"motivo de recálculo manual"*, e quem lê a trilha precisa distinguir "alguém mudou um campo" de "alguém pediu para recontar". A linha é gravada mesmo com o total igual — é para isso que `causas_externas` existe.

Lead sem linha de qualificação é **409**: não há o que pontuar, e gravar um zero seria afirmar algo sobre o lead.

## D6 — O autor chega à trilha de score

`registrar_recalculo` ganha `autor: str | None = None`, gravado em `lead_score_audit.autor`. O valor é o de `IdentidadeDaRequisicao.para_log()` — o `usuario_id`, o mesmo identificador que a trilha de auditoria grava em `ator_id`. Os dois chamadores de hoje (turno e não-comparecimento) não passam nada, e a coluna continua nula para eles, o que é verdade: o ato não é de uma pessoa.

## D7 — A devolução já é registrada

Quarto cenário: *"a devolução fica registrada com autor e momento"*. `atendimento_humano.devolvido_por` e `devolvido_em` fazem isso desde a TEC-179. **Não entra na trilha de auditoria**: a RNF-18 lista acesso a dado pessoal, qualificação, handoff, opt-out e prompt, e devolver não é nenhum deles.

## Arquivos

```
src/mobia/domain/atendimento/tomada.py        # assumir/devolver com o handoff junto (D1)
src/mobia/domain/atendimento/fala.py          # enviar e gravar a fala do corretor (D3)
src/mobia/domain/leads/edicao.py              # o PATCH e o recalculo manual (D4, D5)
src/mobia/domain/context/repositorio.py       # `autor` em registrar_recalculo (D6)
src/mobia/domain/context/auditoria.py         # CAUSA_RECALCULO_MANUAL
src/mobia/domain/outbound/kinds.py            # o kind da fala do corretor
src/mobia/domain/outbound/port.py             # a excecao na guarda de silencio
src/mobia/api/routes/intervencao.py           # as cinco rotas (mesmo prefixo de leads.py)
src/mobia/api/routes/conversas.py             # passa a chamar `tomada.py`
src/mobia/api/saida.py                        # o RoteadorPorCanal da API (D3)
src/mobia/domain/handoff/vocabulario.py       # ACEITAVEIS sai da rota de handoff
```

Sem migration.

## Testes

- **Os quatro cenários do Gherkin, contra banco**, com porta de saída falsa: a mensagem chega e o agente cala; orçamento de 500 mil para 800 mil recalcula e registra autor; recálculo forçado grava `RECALCULO_MANUAL`; devolver reativa e grava `devolvido_por`/`devolvido_em`.
- **Os desfechos do envio** — janela fechada é 409 e não grava fala; opt-out é 409; falha do canal é 502 e não grava; outro corretor com a conversa é 409.
- **A guarda** — o `kind` do corretor passa pela guarda de silêncio e é barrado pela de opt-out; qualquer outro kind continua barrado pela de silêncio.
- **A fala entra na transcrição** com `autor: CORRETOR`.
- **A edição** — só o campo que mudou gera `QUALIFICACAO_ALTERADA`; valor igual não gera; enumerado fora do vocabulário é 422; mínimo acima do máximo é 422; conversa encerrada é 409; o valor não aparece na trilha.
- **O recorte e o vínculo** — CORRETOR de outro lead é 403; LEITURA é 403; usuário sem vínculo de corretor é 409.
- **As rotas antigas** continuam passando nos testes que já existem.

## Emendas ao SRS

- **RN-18.3, Emenda E-01** — as rotas por `leadId`, o envio síncrono que assume a conversa, os quatro desfechos, `intencao` fora da edição, e a causa `RECALCULO_MANUAL`.
- **RN-18.4, Emenda E-01** — o autor em `lead_score_audit.autor` e um `QUALIFICACAO_ALTERADA` por campo; a devolução registrada em `atendimento_humano` e não na trilha.
- **RN-16.4, Emenda E-06** — o envio manual do corretor existe e atravessa a guarda de silêncio; a de opt-out continua valendo para ele; quem envia é o corretor da claim, nunca o do corpo.
- **Seção 6.2, `PATCH /leads/{leadId}/qualificacao`, Emenda E-01** — os campos editáveis e a resposta.

## Lacunas declaradas

- **L1 — fora da janela de 24 h não há como falar.** O 409 diz por quê; oferecer template é outra card (e a TEC-373, de submeter templates à Meta, ainda não andou).
- **L2 — o fator de catálogo é sempre zero** (`imoveis_compativeis=0` em `registrar_recalculo`). O terceiro cenário fala de *"um lead cujo catálogo mudou"*: o recálculo forçado grava a linha com o motivo, mas a mudança de catálogo **não move o score**, porque nada a mede. O teste afirma o que a rota faz — a linha nova com `RECALCULO_MANUAL` —, e não um score que mudaria.
- **L3 — `intencao` não se edita** (D4).
- **L4 — ADMIN e GERENTE sem cadastro de corretor não falam com o lead nem assumem pela rota nova** (D2). Pela antiga, com o par no corpo, continuam podendo.
- **L5 — mídia não se envia**, só texto.
- **L7 — o campo que o lead recusou continua recusado** (`campos_recusados`) mesmo depois de o corretor preenchê-lo, e continua sem contar para a qualificação (D4 da TEC-148). Tirá-lo da lista pediria decidir entre os cinco nomes que o orçamento tem neste repo, e não é desta card.
- **L8 — o kind da fala no web vai no frame do widget** (`corretor:…`), e a tela do chat web (TEC-346) é quem decide se a mostra diferente da do assistente.
- **L6 — o envio síncrono prende a requisição até a Meta responder.** O timeout do adaptador é o que limita; não foi medido sob carga.
