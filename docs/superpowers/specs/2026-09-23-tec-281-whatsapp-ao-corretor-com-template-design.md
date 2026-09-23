# TEC-281 — Entregar a notificação ao corretor por WhatsApp com template aprovado

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-281](https://eduardodurieuxlopes.atlassian.net/browse/TEC-281) — épico TEC-173
**Branch:** `feat/tec-281-whatsapp-ao-corretor-com-template`
**Origem:** Emenda E-02 da RN-16.2 (TEC-177, 12/09/2026).

## Objetivo

Fazer o aviso de lead chegar ao corretor pelo WhatsApp, e não só ficar registrado num log dizendo que não foi entregue.

## O que a card diz que falta, e que já não falta

A card foi escrita em 13/09 e descreve o estado daquela data. **A TEC-186, mergeada em 23/09, tornou falsas duas das três afirmações da seção "Metade interna":**

| a card diz | hoje |
| --- | --- |
| "`WhatsAppOutbound._deliver` hoje monta exclusivamente `corpo["type"] = "text"` — nunca `template`" | **falso**: `whatsapp.py` monta `type: "template"` com `name`, `language` e `components`, e o comentário credita a TEC-186 |
| "o nome do template aprovado vira configuração" | **já existe**: `whatsapp_templates_aprovados` em `config.py`, com `Settings.templates_aprovados` derivado |
| "um adaptador novo substitui `WhatsAppRegistrado`" | continua verdadeiro — é o que sobra |

É a mesma classe de defeito que a TEC-296 corrigiu em duas specs: prosa escrita antes da implementação, em tempo presente, que o merge de outra card tornou falsa. **Vira emenda na card.**

Sobra, portanto, menos do que a card descreve: o adaptador, o nome do template dele, e o comportamento sem aprovação.

## D1 — O canal do corretor NÃO passa por `GuardedOutbound`

É a decisão mais importante do desenho, e a leitura ingênua — *"já existe `WhatsAppOutbound`, use-o"* — está errada.

`GuardedOutbound.send(message_id, kind, payload)` aplica três coisas, e **as três são sobre o lead**:

- **opt-out** — `esta_em_optout_por_mensagem(session, message_id)`, que exige uma linha em `messages`;
- **atendimento humano** — barra envio por cima de quem assumiu a conversa;
- **reserva** em `outbound_dispatches`, para não duplicar resposta.

O corretor **não é lead**: não tem linha em `messages`, não tem opt-out, não está em conversa nenhuma. Passar a notificação por ali exigiria inventar um `message_id` — uma linha falsa em `messages`, que é a tabela de onde saem as métricas de origem e o histórico da conversa. O remédio seria pior que a doença.

O canal novo fala com a Cloud API direto. **O que ele não herda, ele também não precisa:** não há opt-out de corretor a respeitar (se houver algum dia, é card própria, e o lugar dela é `destinatario.py`, não aqui), e não há risco de duplicar resposta ao lead porque não é ao lead que se fala.

**O que ele precisa e não pode perder** é a única guarda que se aplica: nunca cair na mensagem livre. Ver a D3.

## D2 — A porta passa um `Aviso`, não `(assunto, corpo)`

`montar()` devolve hoje `(assunto, corpo)`, com o `corpo` concatenando resumo e link. O e-mail manda isso inteiro e está certo. **O template não pode.**

Um template da Meta recebe **parâmetros posicionais**, e o resumo não cabe em nenhum: é prosa de até 1.500 caracteres, destilada do que o lead escreveu, e a Meta revisa template humano por humano. O que o WhatsApp entrega é o aviso — etiqueta, prioridade, link.

Esses três valores **existem estruturados** no sítio de chamada (`handoff.etiqueta`, `handoff.prioridade`, `link_da_transcricao(...)`), e são jogados fora na hora em que `montar` os concatena em prosa. A alternativa seria o canal extrair o link de volta do `corpo` por regex — **recusada**: parsear prosa que nós mesmos acabamos de montar é criar um acoplamento textual que nenhum teste de `montar` protegeria.

Então `montar` passa a devolver um `Aviso` — dataclass congelada com `assunto`, `corpo`, `etiqueta`, `prioridade` e `link` — e a porta vira `enviar(*, destino: str, aviso: Aviso)`. O e-mail usa `assunto` e `corpo` e ignora o resto; o WhatsApp usa os estruturados e **nunca toca em `corpo`**.

Isso mantém o que `canais.py` declara como valor — *"uma forma só para os dois: a porta ainda é uma só"* — e de quebra resolve um risco que o próprio `montar` documenta: o docstring avisa que `etiqueta` e `prioridade` são dois `str` adjacentes e trocá-los não levanta nem o mypy vê. Num campo nomeado de dataclass, trocar passa a ser visível.

## D3 — Sem template aprovado: barulhento no canal, nunca silencioso

O nome do template do aviso ao corretor entra como configuração própria (`whatsapp_template_notificacao_corretor`), e **só é usado se também estiver em `templates_aprovados`** — o mesmo par que a TEC-186 estabeleceu, em que o catálogo é código e a aprovação é fato externo injetado.

Sem nome configurado, ou com nome fora do conjunto aprovado, o canal **levanta `FalhaDeCanal`**. Nunca tenta texto livre: o corretor está sempre fora da janela de 24h, então a mensagem livre é recusa garantida com o código 131047 — não é degradação, é desperdício de chamada.

**Mas levantar sozinho perde o sinal, e isso foi medido no código.** `notificar` só loga `motivos` quando **nenhum** canal aceitou; com o e-mail entregando, a falha do WhatsApp não apareceria em lugar nenhum — pior que o `WhatsAppRegistrado` de hoje, que ao menos loga `notificacao.nao_entregue`. Por isso o canal **loga antes de levantar**, com o mesmo cuidado dos outros: `destino` e `assunto` sim, `corpo` nunca.

## D4 — O que o template carrega, e a divergência que isso cria com a RN-16.2

Três parâmetros: etiqueta, prioridade e link. **Sem resumo**, pela razão da D2.

A RN-16.2 diz *"notificação por e-mail e WhatsApp ao corretor designado em até 60 s, **com resumo** e link direto"* — tratando os dois canais como equivalentes. Eles não podem ser. **Entra como emenda ao SRS**, nomeada no comentário da card, como a própria TEC-281 antecipou.

O e-mail continua levando o resumo. Quem quiser o conteúdo tem o e-mail ou o painel; o WhatsApp é o toque no ombro.

## O que este desenho não entrega

**A aprovação do template pela Meta.** É submissão externa, com prazo de terceiro, e nenhum PR a fecha. O código entra configurável e inerte até o nome aprovado ser injetado — exatamente o padrão que a TEC-186 adotou e que o RT-03 prevê.

**Consequência prática, dita sem rodeio:** enquanto não houver template aprovado e configurado, **o corretor continua sem receber WhatsApp**. Esta card troca "um log dizendo que não foi entregue" por "um canal pronto que entrega no dia em que a Meta aprovar". Não troca por "corretor avisado".

**O link continua quebrado.** `link_da_transcricao` aponta para a E8, que não existe — `mensagem.py` já registra isso em negrito desde a TEC-280. Esta card não conserta, e agora o link quebrado passa a viajar por dois canais em vez de um.

**Opt-out de corretor.** Não existe e não é criado aqui.
