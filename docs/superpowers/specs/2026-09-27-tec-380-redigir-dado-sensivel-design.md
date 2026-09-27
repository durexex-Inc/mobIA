# TEC-380 — Redigir dado sensível informado espontaneamente antes de gravar a mensagem

**Status:** desenho aprovado (as três decisões de produto foram tomadas pelo Eduardo em 27/09/2026), implementado nesta branch
**Card:** [TEC-380](https://eduardodurieuxlopes.atlassian.net/browse/TEC-380) — épico TEC-200
**Branch:** `feat/tec-380-redigir-dado-sensivel`
**Origem:** RNF-20 (SRS v1.0): "se o lead os informar espontaneamente, o campo é redigido antes da persistência".

## O que o repo tem, medido sobre `e81b881`

1. **Dois pontos gravam texto do lead.** O primeiro é `IngestionService._persist` (`domain/messages/service.py`), por onde passam o WhatsApp e o widget web. O segundo, desde a TEC-131, é `gravar_transcricao` (`domain/midia/repositorio.py`), que grava a transcrição do áudio. A fala do corretor (`atendimento/fala.py`) e a do agente (`recorder.py`) não são do lead.
2. **O texto é gravado duas vezes.** Uma em `text_body` e outra dentro de `raw_payload`, cifrado: `text.body` e as legendas no envelope da Meta, e `texto` no frame do widget. Redigir só `text_body` deixaria o dado no envelope.
3. **A moderação não guarda texto.** `bloqueios_de_moderacao` guarda só a categoria.
4. **Nada detecta dado sensível.** Existe o molde determinístico de `pediu_optout` (`optout/deteccao.py`).

## D1 — Detecção por regra, antes de gravar

**Decisão do Eduardo, sobre a recomendação.** O modelo não é opção antes da persistência: a RN-01.2 proíbe LLM no ciclo do webhook, e é ali que a mensagem é gravada. Detectar por modelo depois de gravar contrariaria o "antes da persistência" da RNF-20, e faria uma regra de LGPD depender de o provedor estar de pé.

A regra fica em `domain/privacidade/redacao.py`, que expõe `redigir(texto) -> Redacao(texto, trechos)`. É pura, determinística e sem chamada.

**A comparação é insensível a caixa e a acento, mas preserva o texto original.** O texto passa por um dobramento caractere a caractere, em que cada caractere vira exatamente um: minúsculo e sem diacrítico. O dobramento tem o mesmo comprimento do original, então um trecho achado nele recorta o mesmo trecho do original. O resto da mensagem sai intacto, com acento e caixa. A normalização de `pediu_optout` não serve aqui: ela apaga pontuação e colapsa espaços, e os índices deixariam de bater.

**Duas faixas, pela mesma lógica de precisão da TEC-257:**
- **Termo inequívoco, em qualquer posição.** Nomes de condição de saúde que não aparecem em conversa de imóvel com outro sentido: "diabetes", "HIV", "câncer", "autismo", "Alzheimer", "quimioterapia", "hemodiálise"…
- **Termo identitário, só na primeira pessoa.** Religião, opinião política, origem racial e orientação sexual só casam depois de "sou", "somos", "eu sou" e variações. "Perto da Católica" é um bairro, "perto da igreja" é localização, e "sou católica" é convicção religiosa. Sem a primeira pessoa, a redação apagaria o pedido de imóvel.

**O que a regra perde, e isso é declarado.** Termo fora da lista, paráfrase ("tenho açúcar alto"), erro de digitação e dado de terceiro na forma identitária ("meu marido é evangélico") passam. Dado genético ou biométrico não entra na lista: "biometria" é a portaria do prédio. O teste de aceite fixa o que a regra pega, não uma promessa de recall.

## D2 — O que redigir: só o trecho

**Decisão do Eduardo.** O termo casado é trocado por um marcador, e o resto da mensagem fica. "Tenho diabetes e quero térreo" vira "Tenho [dado sensível removido] e quero térreo": a necessidade de imóvel sobrevive.

**O marcador é genérico, sem categoria** (decisão deste desenho). "[dado sensível: saúde]" diria, por si, que a pessoa tem uma condição de saúde. O marcador vai com acento porque aparece no painel para o corretor.

**Exceção, também decisão do Eduardo:** deficiência e mobilidade reduzida ("cadeirante", "cadeira de rodas", "mobilidade reduzida", "deficiente visual"…) viram `[necessidade de acessibilidade]`. A condição não é gravada, e o requisito de imóvel continua visível para o agente e para o corretor.

**O marcador não casa com a própria regra**, então redigir um texto já redigido não muda nada. Isso tem teste.

## D3 — Onde a redação roda, e o que o agente vê

- **Em `_persist`, sobre o `ParsedMessage`:** em `text_body` e em toda string de `raw_payload`, percorrido recursivamente. É isso que cobre `text.body`, as legendas, o `texto` do widget e o nome de arquivo do documento.
- **Em `transcrever_audio`, antes de `gravar_transcricao`.**
- **A detecção de opt-out, de pedido de humano e de pedido de titular da ingestão continua sobre o texto original.** Ele ainda está na memória e nunca é gravado. Nenhum marcador colide com esses termos.
- **O agente vê o texto redigido.** Não é escolha: o turno roda em outro processo e lê do banco. O modelo nunca recebe o dado. A pseudonimização antes do LLM, fora do escopo da card, continua sendo outra card.
- **Log:** `privacidade.dado_sensivel_redigido`, com `message_id` e a quantidade de trechos. Sem categoria, porque a categoria ligada a um id seria o próprio dado.

## Emenda ao SRS

**RNF-20 E-01 (TEC-380, 27/09/2026)**, aninhada na linha da tabela:
- a redação é determinística, sobre uma lista de termos;
- troca o trecho por um marcador genérico;
- a acessibilidade vira `[necessidade de acessibilidade]`;
- vale para texto, legenda, envelope e transcrição de áudio;
- o recall é limitado, e isso é declarado.

## Testes

- **Unitários (`test_redacao.py`):**
  - cada categoria casa;
  - caixa e acento;
  - a primeira pessoa exigida nos identitários;
  - os falsos positivos de imóvel que não podem casar ("perto da Católica", "perto da igreja", "portaria com biometria", "rua Evangelista");
  - idempotência;
  - o texto em volta preservado.
- **Integração:**
  - a ingestão grava o texto redigido em `text_body` e em `raw_payload`, pelo WhatsApp e pelo widget;
  - a transcrição é redigida.
- **Features, os dois cenários da card**, pelo webhook.

## O que esta card não entrega

- **Mensagens gravadas antes desta card não são redigidas.** Não há migração de histórico: ela exigiria decifrar e reescrever toda a base, e a retenção da TEC-207 as esvazia em 12 meses.
- **Recall limitado** (D1). A lista é o que um lead de imóvel plausivelmente escreve, e não um classificador.
- **Imagem e documento não são lidos.** O conteúdo de um laudo em PDF fica guardado, cifrado, como a TEC-132 já declarava. Só o nome do arquivo passa pela redação.
- **O dado sensível ainda passa pelo provedor da transcrição**: a Whisper ouve o áudio antes da redação. Resolver isso é da card de pseudonimização.
