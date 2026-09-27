# TEC-327 — Assumir e devolver a conversa pelo painel

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-327](https://eduardodurieuxlopes.atlassian.net/browse/TEC-327) — épico TEC-304
**Branch:** `feat/tec-327-assumir-e-devolver`
**Depende de:** TEC-194 (`POST /leads/{leadId}/assumir` e `/devolver`), TEC-324 (a conversa), TEC-302 (o `/bff/*`)

## O que existe quando a card começa

`POST /api/v1/leads/{leadId}/assumir` e `/devolver` existem desde a TEC-194, com `ATENDER_LEAD` e o corretor tirado da claim do JWT, nunca do corpo. Usuário sem vínculo de corretor ativo leva 409. `assumir` é idempotente para quem já é o dono e responde **409 "conversa ja assumida por outro"** quando outro corretor a tem. `devolver` aceita qualquer corretor, e não só quem assumiu (docstring de `atendimento/repositorio.py::devolver`).

A conversa (TEC-324) mostra as falas e pagina para trás. Cada leitura da transcrição grava `DADO_PESSOAL_ACESSADO` (D3 da TEC-193).

**Três coisas que a card pressupõe e que não existem:**

1. o 409 não diz quem assumiu, e a card pede o nome;
2. o detalhe não diz se a conversa está assumida, então a faixa sumiria ao recarregar;
3. o polling de 5 s gravaria 12 acessos por minuto por aba aberta.

## D1 — O polling só grava na trilha quando traz fala nova

**Decisão do Eduardo, 27/09/2026, com três alternativas na mesa.**

A rota da transcrição ganha `?depois=<cursor>`, que devolve só as falas **posteriores** à última que a tela já tem, em ordem cronológica. **Ela grava `DADO_PESSOAL_ACESSADO` só quando a resposta traz pelo menos uma fala.** Um poll vazio não entrega dado pessoal nenhum, e registrá-lo encheria a trilha de leituras que não leram nada. O registro continua comitado antes de a resposta sair, como na D3 da TEC-193.

- **Ordem das checagens:** 404, depois 403 do CORRETOR (com o `ACESSO_NEGADO` de sempre), depois a consulta, depois o registro, se houve fala. A negação continua registrada em todo poll negado. Não deveria haver nenhum: a tela só faz polling do lead que abriu.
- **O cursor é opaco, então o servidor devolve o próximo.** As duas formas da rota passam a responder `cursorPosterior`, o cursor da fala mais recente da resposta. A tela nunca monta cursor. Num poll vazio, `cursorPosterior` repete o `depois` recebido.
- **`cursor` e `depois` juntos são 422**: são direções opostas, e escolher uma em silêncio devolveria a página que não foi pedida.
- **`depois` de uma fala de outro lead é 422**, pela mesma regra do cursor para trás.

As alternativas e por que não: **registrar todo poll** deixaria a trilha dominada por leituras vazias; **não ter polling** deixaria o segundo cenário da card fora dela.

Vira a **Emenda E-02 à seção 6.2 / `GET /api/v1/conversas/{conversaId}/mensagens`**, que é a seção onde o SRS descreve a transcrição.

## D2 — O detalhe diz quem tem a conversa

`GET /api/v1/leads/{leadId}` ganha `atendimento`:

```json
"atendimento": { "assumidoPor": { "corretorId": "uuid", "nome": "Paulo" }, "assumidoEm": "ISO-8601" }
```

O campo é `null` quando ninguém assumiu, ou quando a última pessoa devolveu (`devolvido_em` preenchido). O nome vem de `corretores.nome`, que é gente da operação, e não do lead. Não é dado pessoal que a trilha precise registrar.

## D3 — O 409 diz quem tem a conversa

Quando `assumir` recusa, a rota lê quem é o dono atual e responde:

```json
{ "detail": { "motivo": "conversa_de_outro", "assumidoPor": { "corretorId": "uuid", "nome": "Ana" } } }
```

**`detail` vira objeto só neste 409.** Os outros 409 da rota (sem vínculo de corretor) continuam como texto. A tela precisa do nome para a frase, e tirá-lo de dentro de uma string seria prender a tela ao texto do backend.

Entre a recusa e a leitura, a outra pessoa pode ter devolvido a conversa. Nesse caso `assumidoPor` sai `null`, e a tela diz "A conversa mudou de mãos; recarregue a página". Não se tenta assumir de novo sozinho: a pessoa clicou numa conversa que estava com outro, e decidir de novo é dela.

## D4 — A tela

- **Os botões só aparecem para quem pode agir**: `ATENDER_LEAD` e vínculo de corretor (`corretorId` no `/auth/me`). O GERENTE sem vínculo levaria 409 "sem vínculo de corretor" em todo clique. Esse caso é declarado (L2).
- **Três estados, lidos do `atendimento` do detalhe:**

  | estado | o que aparece |
  | --- | --- |
  | ninguém assumiu | botão "Assumir conversa" |
  | quem vê é o dono | a faixa **"Você está no controle — o agente está em silêncio"** e o botão "Devolver ao agente" |
  | outro corretor tem | "A conversa está com Ana." e o botão "Devolver ao agente" |

  No terceiro estado, "Devolver" aparece porque o backend aceita a devolução de qualquer corretor, e é o conserto do caso real do corretor que assumiu e saiu de férias (docstring de `devolver`). Assumir por cima de outro não existe: o backend recusa.
- **Confirmação** com `window.confirm`, nas duas ações. O `<dialog>` nativo daria um modal com mais controle visual, e pediria foco, `Esc` e estado que o `confirm` já dá acessíveis. Trocar é card de acabamento, se alguém pedir.
- **A ação é um `POST` pelo `/bff/*`.** A allowlist ganha `POST api/v1/leads/*/assumir` e `/devolver`. O proxy já recusa mutação sem `Origin` da própria origem (CSRF), e o `fetch` do navegador manda esse cabeçalho.
- **Depois da ação, a tela recarrega os dados do servidor** (`router.refresh()`), e não muda o estado por conta própria. O servidor é quem sabe o estado; mudar a faixa sem ler de volta poderia mostrar o controle depois de uma resposta que não o deu.

## D5 — O polling

- **Só com a conversa assumida por quem vê a tela**, que é o que a card pede, e **só com a aba visível** (`document.visibilityState`). Voltando a ficar visível, faz um poll na hora.
- **A cada 5 s**, `GET /bff/api/v1/leads/{id}/mensagens?depois=<cursorPosterior>`. As falas novas entram no fim da lista.
- **Mensagem nova é anunciada** na região `aria-live="polite"` que a TEC-324 criou: "1 mensagem nova". A D5 da TEC-324 registrou que não havia o que anunciar. Agora há.
- **A rolagem acompanha só se a pessoa já estava no fim.** Se ela subiu para ler o começo da conversa, a fala nova não a arrasta para baixo.
- **Falha no poll não para o polling nem mostra erro a cada 5 s.** Um 401 para o polling e diz que a sessão terminou, porque tentar de novo não adianta. Os outros erros tentam de novo no próximo ciclo.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| assumir a conversa | teste do componente: confirmar chama o `POST` e recarrega; teste da página: com `atendimento` do próprio corretor, a faixa aparece |
| mensagem nova do lead em até 10 s | teste do componente com relógio falso: poll a cada 5 s, fala nova no fim. Integração: `depois` devolve só as posteriores |
| conversa já assumida por outro | teste do componente: o 409 com o nome vira "A conversa já está com Ana". Integração: o 409 traz o nome, e o dono não muda |
| devolver ao agente | teste do componente: confirmar chama o `POST` e recarrega; teste da página: sem `atendimento`, a faixa não aparece |

**E a D1, contra banco:** o poll vazio não grava nada, o poll com fala grava uma linha, e `cursor` com `depois` é 422.

## Lacunas declaradas

- **L1 — o polling só roda com a conversa assumida por quem vê a tela.** Quem só observa não recebe fala nova até recarregar, o mesmo estado da TEC-324.
- **L2 — o GERENTE ou ADMIN sem vínculo de corretor não vê os botões.** Assumir exige um corretor em nome de quem falar (decisão de 26/09/2026 na TEC-194).
- **L3 — `window.confirm`, e não um modal desenhado** (D4).
- **L4 — a faixa é da tela do detalhe.** A lista de leads não diz quais conversas estão assumidas.

## Emendas ao SRS

**Emenda E-02 à seção 6.2 / `GET /api/v1/leads/{leadId}/mensagens` (TEC-327, 27/09/2026)**: a rota aceita `?depois=<cursor>`, que devolve só as falas posteriores, em ordem cronológica. As duas formas passam a responder `cursorPosterior`. **Com `depois`, `DADO_PESSOAL_ACESSADO` só é gravado quando a resposta traz pelo menos uma fala**: poll vazio não entrega dado pessoal. `cursor` e `depois` juntos são 422. Decisão do Eduardo, 27/09/2026.

**Emenda E-02 à seção 6.2 / `GET /api/v1/leads/{leadId}` (TEC-327, 27/09/2026)**: a resposta ganha `atendimento`, com quem tem a conversa (`assumidoPor.corretorId`, `assumidoPor.nome`) e desde quando, ou `null`.

**Emenda E-02 à seção 6.2 / `POST /api/v1/conversas/{conversaId}/assumir` (TEC-327, 27/09/2026)**: o 409 de `POST /leads/{leadId}/assumir` passa a trazer `detail.assumidoPor`, no mesmo formato do detalhe.

Cada seção do SRS numera as próprias emendas, e as três só tinham a E-01.
