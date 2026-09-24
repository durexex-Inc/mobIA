# TEC-129 — Unificar histórico do lead entre WhatsApp e web

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-129](https://eduardodurieuxlopes.atlassian.net/browse/TEC-129) — épico TEC-123
**Branch:** `feat/tec-129-historico-unificado`
**Origem:** RF-01, RN-01.1 (SRS v1.0), e a RN-01.1 E-01 da TEC-124.

## Objetivo

Quem começou a conversa no chat do site e depois escreveu pelo WhatsApp não recomeça do zero: o agente, no WhatsApp, já sabe o que a pessoa disse no site.

## O que o repo tem, e por que isso decide o desenho

Quatro fatos, medidos sobre `b71e588`:

1. **Não existe entidade lead.** Não há tabela `leads`, nem `lead_id`, nem `tenant_id`. O lead é o par `(channel, conversation_key)`, repetido em cerca de 15 tabelas — `messages`, `lead_qualification`, `conversation_summaries`, `conversation_intent`, `recomendacoes`, `handoffs`, `followups`, `optout_events`, `atendimento_humano`, entre outras —, várias com UNIQUE sobre ele e nenhuma com FK a repontar. O resumo da conversa é cifrado com AAD derivado do par (`aad_do_resumo`, `domain/context/models.py`).
2. **A resposta é roteada por `messages.channel`** (`RoteadorPorCanal`, TEC-124). Regravar as falas web como `whatsapp` tira a resposta da aba aberta.
3. **Turnos da mesma conversa não são serializados.** O `claim_message` trava por mensagem, a deduplicação do ARQ é por mensagem, e o comentário em `domain/context/repositorio.py` diz isso com todas as letras. A única serialização é o `FOR UPDATE` na linha de `lead_qualification`.
4. **Nada captura telefone.** O classificador não tem campo de telefone, e não há normalização E.164 em lugar nenhum de `src/`. O `conversation_key` do WhatsApp é o `from` cru da Meta, sem `+`.

## D1 — A unificação é assimétrica: só o lado WhatsApp herda

A sessão web é um portador anônimo (RN-01.1 E-01): o visitante digita um telefone e nada verifica que o número é dele. O WhatsApp é o lado autenticado — a Meta garante que quem escreve de um número é o dono dele.

Por isso:

- **O turno WhatsApp enxerga as sessões web vinculadas ao seu número** — critérios (a intenção entre eles), recusas e as falas literais. Ver a D4 para o que fica de fora.
- **O turno web continua enxergando só a própria sessão.** E a aba continua mostrando só as falas da própria sessão (`historico_da_sessao`, inalterado).

A alternativa simétrica — o turno web também lendo o estado do WhatsApp — **vaza pela boca do agente**: quem digita o telefone de outra pessoa passa a conversar com um agente que conhece a qualificação dela, e ele diz "você procurava 3 quartos no Campeche, até 900 mil". Esconder o histórico da tela não adianta se o agente o recita.

A unificação total, com a tela web mostrando o WhatsApp, exigiria verificar o telefone — um código por WhatsApp, por exemplo. É escopo novo, e não é esta card.

**Consequência declarada:** quem fala pelo WhatsApp e depois volta ao site encontra um agente que não sabe o que foi dito no WhatsApp.

A assimetria também elimina a corrida do fato 3: cada turno grava só no próprio par, e o único ponto de encontro — o upsert da qualificação do WhatsApp — já é serializado.

## D2 — O telefone vem de uma regex determinística sobre a fala da visitante

Nem campo novo no classificador, nem frame novo do widget:

- **Campo no classificador** custaria prompt e schema, que o teste da margem do orçamento vigia, e tornaria a extração não determinística.
- **Frame `{"tipo": "telefone"}`** dependeria de um formulário que não existe — o widget não existe (TEC-124, "o que não entrega"). Ninguém o exercitaria.

**O agente não passa a pedir telefone.** A card não pede isso, e mudar o comportamento da conversa é outra decisão.

Módulo puro novo, `domain/identidade/telefone.py`:

- `extrair_telefone(texto) -> str | None` reconhece telefone brasileiro, celular e fixo: `+55` opcional, DDD com ou sem parênteses, 8 ou 9 dígitos, separados por espaço, hífen, ponto ou nada.
  - **Emenda (revisão final, 24/09/2026):** duas formas comuns passam a casar. O **9 separado** do resto do celular — `(48) 9 9999-0000`, `+55 48 9 9999-0000` —, com o separador admitido só depois de um 9 inicial. E o **zero de tronco** antes do DDD — `(048) 99999-0000`, `048 99999-0000` —, que `normalizar` descarta. O zero só é tronco quando a máscara o põe junto do DDD (entre parênteses, ou seguido de separador): onze dígitos crus começando por zero continuam não casando, porque são CPF cru tanto quanto telefone e descartar o zero ali abriria um falso positivo novo.
- **Dois telefones diferentes na mesma mensagem devolvem `None`.** Não há como saber qual é o da pessoa.
- Número estrangeiro não é reconhecido. Limite declarado.
- A sequência precisa ser um telefone plausível — DDD válido, e, com 9 dígitos, começar por 9. Isso afasta CEP (8 dígitos sem DDD), preço e CPF pontuado (`000.000.000-00`, que a máscara não aceita).
- **CPF sem pontuação cujo terceiro dígito é 9 casa, e isso é um falso positivo aceito.** Onze dígitos soltos com DDD válido e 9 na terceira posição são indistinguíveis de um celular. O custo é um vínculo errado: o que a sessão disse vai para o contexto do WhatsApp de um número que talvez nem exista. Não vaza nada do WhatsApp para o web (D1).

`normalizar(digitos) -> str` leva qualquer forma à canônica: só dígitos, com o `55`. **Celular de 8 dígitos ganha o 9** — é a mesma regra que resolve o `wa_id` que a Meta entrega sem o 9 para parte dos celulares brasileiros. A forma canônica do celular tem 13 dígitos, a do fixo, 12.

## D3 — O vínculo nasce na ingestão do canal web

Depois de a mensagem web ser persistida pelo `IngestionService`, no caminho do `WS /widget/chat`, e **não dentro do turno**. É determinístico, não depende de o turno rodar nem falhar, e fica fora de `executar_turno`.

Tabela nova, `vinculos_de_sessao`:

| coluna | tipo | |
| --- | --- | --- |
| `channel` | `String(32)` | PK, junto com `conversation_key` — a sessão web |
| `conversation_key` | `String(64)` | PK |
| `telefone` | `String(16)` | forma canônica da D2, indexada |
| `message_id` | FK para `messages.id` | a mensagem que trouxe o telefone — evidência |
| `criado_em` | `timestamptz` | |

Regras:

- **Uma sessão se vincula uma vez.** O primeiro telefone vale. Um telefone diferente depois é ignorado, com log — `INSERT … ON CONFLICT DO NOTHING`.
- **Várias sessões podem apontar para o mesmo telefone** — a mesma pessoa em dois navegadores.
- O vínculo não se desfaz nesta card.
- Os dígitos ficam em claro, como já ficam no `conversation_key` do WhatsApp. Não é dado novo exposto.

A tabela entra em `TABELAS` de `tests/conftest.py`.

## D4 — O turno WhatsApp absorve as sessões vinculadas

**Quando:** no começo de todo turno cujo `message.channel` é `whatsapp`, antes de `montar_contexto`. O `conversation_key` é normalizado pela D2, e a busca em `vinculos_de_sessao` devolve as sessões web. Sem vínculo, o turno fica exatamente como hoje.

A absorção é **idempotente** e roda em todo turno: isso cobre a sessão web que continua viva depois de o WhatsApp começar.

**Só grava no par do WhatsApp** — o próprio par do turno. Nada escreve no par web.

| estado | regra |
| --- | --- |
| `lead_qualification`, critérios (intenção, faixa de preço, região, tipo, quartos, vagas, urgência, forma de pagamento, imóvel para vender, campos de investidor) | preenche **só o campo vazio** no WhatsApp; o que o WhatsApp já sabe prevalece. Com várias sessões, vale a de `updated_at` mais recente |
| `campos_recusados` | união, menos o que o WhatsApp já tem preenchido: o que a pessoa se recusou a dizer no site não é perguntado de novo |
| falas literais | a janela lê os pares `[whatsapp, web…]` num `tuple_(...).in_(...)`, que usa o mesmo `ix_messages_timeline`; o corte que já existe para caber no orçamento se aplica ao conjunto |

A intenção entra pela coluna `lead_qualification.intencao`, que é um dos critérios da primeira linha.

- **Emenda (revisão final, 24/09/2026) — o orçamento e o investidor não atravessam banda de intenção.** A faixa de preço, a recusa do orçamento em `campos_recusados` e os campos de investidor só são absorvidos de uma sessão cuja intenção está na mesma banda que a do WhatsApp, pelo mesmo predicado que a TEC-136 usa para descartar a faixa na troca de intenção (`mudou_de_banda`). Sem isso, o turno seguinte a uma troca de compra para aluguel achava a faixa vazia e a repreenchia com o orçamento de compra do site, para sempre. Sessão sem intenção, com o WhatsApp numa banda, não passa; WhatsApp sem intenção herda primeiro a intenção e é ela que define a banda. Os campos de investidor vêm em bloco, de uma sessão só, e só quando o WhatsApp ainda não tem nenhum — `perfil_investidor` é derivado dos outros, e misturá-los campo a campo produzia um perfil que nenhum estado sustenta.

**Dois limites** (emenda da revisão final, 24/09/2026):

- **Só o que foi dito até a fala do turno.** Das sessões vinculadas, a janela só lê as falas com `created_at` estritamente anterior ao da mensagem que o turno responde. O instante vem da própria mensagem, passado por `executar_turno` a `montar_contexto` (`ate_das_vinculadas`), e não do relógio do turno — que pode rodar bem depois dela, por debounce, fila ou retentativa. As falas do próprio par do WhatsApp não têm esse limite. Estrito, e não `<=`, porque no empate a ordem sai do `id` e uma fala web no mesmo instante poderia ficar depois da do turno. Com isso a fala do turno volta a ser, por construção, a mais recente da lista, que é o que o piso da janela pressupõe quando cede.
- **No máximo três sessões por turno** — as vinculadas por último, por `criado_em` do vínculo —, na absorção e na janela (`MAXIMO_DE_SESSOES_VINCULADAS`, `domain/identidade/repositorio.py`). A qualificação, que não é texto e não tem instante, continua absorvida sem o limite temporal.

**Consequência declarada: qualquer pessoa que saiba o número de outra planta critérios e texto no contexto do WhatsApp dela.** O vínculo não é verificado (D1), então quem digita o telefone de outra pessoa no site faz o que disse ali entrar na qualificação e na janela do WhatsApp daquele número — limitado ao que foi dito antes de cada fala do WhatsApp e a três sessões. Nada vaza na direção contrária. Aceitar isso é decisão de produto; fechar exigiria verificar o telefone, que é o escopo que esta card não entrega.

**Consequência declarada: a dobra por silêncio também enxerga o web.** As falas web entram na mesma janela de literais que alimenta `_fronteira_do_silencio` (TEC-130, D4) — se o último literal web for mais de 30 dias anterior ao primeiro literal do WhatsApp, a dobra forçada dispara já no primeiro turno do WhatsApp, e o resumidor paga uma chamada para dobrar a sessão web inteira junto com o que veio antes dela no par do WhatsApp. A dobra escreve só no resumo do par do WhatsApp — nunca no par web (D1), consistente com o resto desta seção.

**O que não é absorvido, e por quê:**

- **`recomendacoes`** — *retirado depois da aprovação das seções, ao ler o código para o plano.* A linha sem reação (`reacao_lead IS NULL`) é o gatilho da chamada de reação, e a ordem das linhas é o ordinal de "o segundo" (`ler_pendentes`, `domain/agente/repositorio.py`). Copiada para o par do WhatsApp, uma apresentação feita no site dispararia no WhatsApp a pergunta sobre um imóvel que a conversa dali nunca mostrou, e deslocaria o ordinal das apresentações do próprio WhatsApp. **Consequência:** o agente pode reapresentar no WhatsApp um imóvel que a pessoa já viu no site.
- **`conversation_intent`** — *retirado pelo mesmo motivo.* A linha carrega a confiança, o marcador de desambiguação e o contador de fora de escopo seguidos (RN-03.5), que são do episódio de conversa, não da pessoa. Herdar o contador do site aproximaria o WhatsApp do silêncio por fora de escopo sem que ele tivesse feito nada.

- **O resumo web.** Seria um bloco novo no prompt a cada turno, contra um orçamento apertado — e o que o cenário 1 exige, os critérios, já chega pela qualificação.
- **Score e temperatura.** São recalculados no próprio turno.
- **Opt-out, handoff e atendimento humano do web.** Não propagam para o WhatsApp: uma sessão não verificada não pode silenciar nem escalar o número de outra pessoa. O inverso também não, porque o turno web não enxerga o WhatsApp (D1).

## D5 — Fora do turno, nada muda

- **Reengajamento:** igual. Continua exigindo fala recebida pelo WhatsApp (`CANAIS_COM_REENGAJAMENTO`), e o web continua fora (TEC-124, D8).
- **Handoff e dossiê do corretor:** o dossiê de um lead WhatsApp já sai com os critérios absorvidos, porque estão na qualificação. **A transcrição do dossiê mostra só as falas do WhatsApp.**
- **Métricas e funil:** **um lead vinculado conta como dois**, porque o nascimento é contado por par (`domain/metricas/repositorio.py`). O painel da TEC-190 superestima leads na proporção dos vínculos.

As duas últimas são lacunas declaradas — decisão de produto, que vai no comentário da card. Consertar o funil toca todas as consultas de `metricas/repositorio.py`, e é outra card.

## Emenda ao SRS

**RN-01.1 E-02**, aninhada abaixo da E-01, sem reescrever nenhuma das duas:

- a unificação é assimétrica — só o lado WhatsApp herda o que foi dito no web;
- o telefone vem de regex sobre a fala da visitante, e só número brasileiro;
- o motivo é que a sessão web é anônima e não verifica o telefone.

## Testes

- **Unitários da D2:** as máscaras comuns; com e sem `+55`; com e sem o 9; fixo; CEP, preço e CPF pontuado não casam; CPF cru com 9 na terceira posição casa, e o teste fixa isso como falso positivo conhecido; dois telefones na mesma mensagem devolvem `None`; o `wa_id` de 12 dígitos normaliza igual ao celular de 13.
- **Integração do vínculo (D3):** cria; o primeiro telefone vence; duas sessões para um telefone; mensagem com dois números não vincula.
- **Integração da absorção (D4):** preenche só o campo vazio; `campos_recusados` faz união; não grava no par web; é idempotente; opt-out web não silencia o WhatsApp.
- **Features — os três cenários da card:**
  - *Mesma pessoa migra do site para o WhatsApp:* turno WhatsApp com o modelo falso; os critérios web estão no estado e o agente não os pergunta.
  - *Sessão anônima é vinculada ao informar o telefone:* 6 mensagens web, o telefone aparece, as 6 pertencem ao lead pelo vínculo.
  - *Telefones diferentes não são unificados:* dois telefones, nada cruza.
- **O teste do vazamento:** a sessão web vinculada ao telefone de outra pessoa não recebe no contexto nenhum dado que veio do WhatsApp. É ele que guarda a D1.

## O que esta card não entrega

- Unificação na direção WhatsApp → web, e a tela web mostrando o WhatsApp — exigiriam verificar o telefone.
- Telefone estrangeiro.
- Desfazer ou corrigir um vínculo.
- O agente pedir o telefone.
- A transcrição do dossiê com as falas web, e o funil contando o lead vinculado uma vez só.
- Imóveis apresentados no site contando como já vistos no WhatsApp (ver D4).
- Uma entidade `leads` com `lead_id` — o modelo do SRS, que custaria migrar as ~15 tabelas. Se um dia for necessária, é card própria.
- `e_conversa_nova` (`domain/agente/identificacao.py`) só consulta o par do próprio turno — o lado WhatsApp. O agente se apresenta de novo no WhatsApp mesmo quando o contexto já carrega a conversa herdada do web; a absorção da D4 não alimenta esse predicado.
