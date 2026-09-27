# TEC-311 — Avisar e encerrar a sessão ociosa

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-311](https://eduardodurieuxlopes.atlassian.net/browse/TEC-311) — épico TEC-301
**Branch:** `feat/tec-311-sessao-ociosa`
**Depende de:** TEC-310 (renovação e `/sair`)

## D1 — O aviso é o primeiro componente de cliente do painel

"30 minutos sem interação" só se observa no navegador: o servidor não vê o mouse. Então nasce `AvisoDeInatividade`, com `'use client'`, desenhado pelo layout do painel quando há alguém logado.

- **Interação** é `pointerdown`, `keydown`, `wheel`, `touchstart` e `mousemove` — este limitado a um registro por segundo, para não custar nada.
- **O relógio é o horário, e não o timer.** Uma checagem por segundo compara `Date.now()` com a última interação. Navegador que põe a aba em segundo plano atrasa timers para uma vez por minuto ou mais; comparando horários, a aba que acorda depois de 40 minutos sabe na hora que já passou do limite.
- **Aos 30 minutos**, abre um `role="alertdialog"` com a contagem de 60 segundos e o botão "Continuar conectado". Responder — pelo botão ou por qualquer interação — fecha o aviso e zera a contagem (cenário 1).
- **Aos 60 segundos sem resposta**, chama `POST /sair`, que revoga o refresh e apaga a sessão (TEC-310), e leva ao login com `erro=inatividade` e o `returnTo` da tela atual (cenário 2).

O componente importa só `lib/destino` e `lib/inatividade` (funções puras). Nada de `lib/servidor/` chega ao bundle de cliente, e o `server-only` reprovaria o build se chegasse.

## D2 — Várias abas: a última interação é de todas

Uma aba esquecida em segundo plano não pode derrubar a sessão de quem está trabalhando em outra: a sessão é uma só, e o `/sair` de uma aba encerra todas.

A última interação vai para o `localStorage` (`mobia:ultima-interacao`), e cada aba usa a mais recente entre a sua e a gravada — ouvindo o evento `storage`, que o navegador dispara nas outras abas. **Guarda um horário e nada mais**: nenhum token, nenhum id de sessão. Se o `localStorage` não estiver disponível (modo privado, bloqueio), cada aba conta sozinha, que é o comportamento sem esta decisão.

## D3 — O servidor também encerra, porque um celular esquecido não roda JavaScript

A história é explícita: "para que um celular esquecido não fique com a base aberta". O timer de cliente não cobre a aba fechada, o navegador que matou a aba em segundo plano nem o telefone que dormiu. Então o servidor também encerra — apagando — a sessão ociosa há mais de **32 minutos**.

- **A atividade é uma chave própria no Redis, com validade de 32 minutos** (`mobia:painel:atividade:<digest>`). Cada leitura de sessão pelo servidor a regrava, o que empurra a validade para a frente; a chave ter sumido quer dizer "32 minutos sem nada". `obterSessaoValida` então apaga a sessão e devolve `null`.
- **Chave própria, e não um campo no registro da sessão**, por causa da renovação da TEC-310. Regravar o registro para marcar atividade seria ler, mudar e gravar — e uma renovação concorrente, gravando o par novo no meio, seria sobrescrita pelo par antigo. O refresh antigo já foi consumido; a próxima renovação o apresentaria de novo, e a detecção de reuso derrubaria a sessão. Com chave própria, o registro dos tokens só é escrito pela renovação.
- **Toda leitura de sessão pelo servidor conta como atividade** (navegar, o menu, o `/bff/*`): é um `SET` com validade, sem leitura antes.
- **Sessões criadas antes desta card não têm a chave**, e no primeiro acesso depois do deploy contam como ociosas: quem estiver logado entra de novo uma vez.
- **Interação sem navegação também precisa chegar ao servidor.** Quem lê o funil por 35 minutos mexendo o mouse está ativo, e o servidor não vê isso. O cliente manda `POST /sessao/atividade` quando há interação, **no máximo uma vez por minuto**. A rota confere o `Origin` e lê a sessão, o que já grava a atividade.
- **Por que 32, e não 31.** O cliente encerra aos 30 minutos mais 60 segundos. O batimento tem até um minuto de atraso em relação à interação real. 32 minutos é o menor limite em que o servidor nunca encerra antes de o cliente ter tido a chance de avisar.

## D4 — Alteração não salva

O painel ainda não tem formulário de edição — o da qualificação do lead é a TEC-329. Entra o mecanismo:

- `registrarAlteracaoNaoSalva(chave, sim)`, em `lib/inatividade.ts`: um formulário avisa que tem, ou deixou de ter, alteração pendente.
- Com alguma registrada, o aviso de inatividade diz "Você tem alterações que não foram salvas e serão perdidas" — antes de a sessão cair, que é o que o cenário 3 pede.

A TEC-329 só precisa chamar a função quando o formulário ficar sujo e quando salvar.

## D5 — A mensagem no login

`erro=inatividade` vira "Sua sessão foi encerrada depois de 30 minutos sem uso. Entre de novo para continuar." Distinguir isso de `sessao_expirada` não é detalhe: quem estava lendo e foi derrubado precisa saber que foi o tempo, e não um erro.

## Lacunas declaradas

- **L1 — o cenário 3 não é exercitado de ponta a ponta**, porque não há formulário de edição (D4). O teste do componente registra uma alteração à mão e afirma o aviso.
- **L2 — o comportamento em navegador real não foi verificado.** Os testes usam jsdom com relógio falso. Timers em segundo plano, o evento `storage` entre abas reais e o foco do diálogo dependem do navegador; a verificação é manual, e fica no PR.
- **L3 — o `localStorage` guarda o horário da última interação** (D2). Não é dado pessoal nem credencial, mas é um rastro de uso no aparelho.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| continuar a sessão a partir do aviso | `AvisoDeInatividade` (D1); teste com relógio falso: aviso aos 30 min, "Continuar" o fecha e manda o batimento |
| encerrar a sessão após a contagem | D1 (cliente) e D3 (servidor); teste do `POST /sair` e do destino; teste da sessão ociosa no servidor |
| avisar sobre alteração não salva | D4; teste do componente com alteração registrada (L1) |

**Sem emenda ao SRS do agente.**
