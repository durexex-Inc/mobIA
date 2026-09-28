# TEC-348 — Reconectar o chat automaticamente e reenviar as mensagens pendentes

**Status:** implementado (27/09/2026)
**Card:** [TEC-348](https://eduardodurieuxlopes.atlassian.net/browse/TEC-348) — épico TEC-307
**Branch:** `feat/tec-348-reconectar-chat`
**Depende de:** TEC-346 (a conversa), TEC-347 (o `historico` em toda reconexão), TEC-364 (`ack` reenviado para `id` repetido), TEC-124 (dedup por `id` dentro da sessão)

## O que existe quando a card começa

- **Toda queda vira falha.** O `close` do socket marca como `falhou` toda mensagem `enviando`, a conexão vai para `fechada`, e só "Reenviar" ou uma mensagem nova reabrem o socket (L5 da TEC-346).
- **O prazo do `ack` corre desde o clique.** `transmitir` agenda os 10 s antes de saber se o socket está aberto: mensagem que espera na fila vence o prazo sem ter saído.
- **Reenviar é seguro.** A reconexão manda no `ola` a sessão em memória, o servidor deduplica o `id` pela UNIQUE dentro da sessão e confirma de novo o repetido (D1 da TEC-364).
- **O servidor diz quando está fora.** Banco ou Redis indisponível fecham com `1011` (`CODIGO_INDISPONIVEL` em `src/mobia/api/routes/widget.py`), inclusive quando a gravação da mensagem falha — o `ack` não vem e o comentário de lá já diz que o `1011` é o sinal para o cliente reconectar.
- **O `historico` volta em toda conexão** e mantém as pendentes no fim (D2 da TEC-347). Uma mensagem gravada cujo `ack` se perdeu aparece duas vezes na tela (L4 da TEC-347).

As regras RN-FE-17.3, RN-FE-17.4 e RNF-FE-12b vêm do texto da card: o SRS do frontend não está no repo.

## D1 — A espera antes da tentativa n é min(2ⁿ⁻¹, 30) s

- Tentativa 1 espera 1 s, a 2 espera 2 s, depois 4, 8, 16, e da 6 em diante 30 s. É a tabela da card; função pura `esperaDaTentativa` em `frontend/src/lib/conversa.ts`.
- **Sem jitter.** A card fixa os números, e o único servidor que eles poupam é o nosso; o limite por IP (D1 da TEC-346) continua sendo a rede para quem reconecta demais.
- **A tentativa conta a partir da primeira queda.** Cada socket que fecha antes de abrir soma uma; um socket que abre zera a contagem.

## D2 — Quem reconecta sozinho, e quem não

A queda leva a conexão a um estado novo, `reconectando {tentativa, desde, instavel}`. O `close` passa a carregar o código e o instante, e o redutor decide:

| antes | código | depois |
| --- | --- | --- |
| `aguardando` (`muitas_tentativas`) | qualquer | continua `aguardando` — a espera tem timer próprio |
| `adormecida` (sono, TEC-347 D4; ou `4000` do servidor) | qualquer | continua `adormecida` |
| `offline` (desistiu, D3) | qualquer | continua `offline` |
| qualquer outro | `1002` | `fechada` — cliente quebrado; reconectar repetiria o mesmo frame recusado |
| qualquer outro | outro | `reconectando` |

- `desde` é o instante da primeira queda e não muda entre as tentativas; `instavel` fica verdadeiro a partir do primeiro `1011` da mesma queda (D4).
- **Só `fechada` marca as pendentes como `falhou`**, como antes. As outras preservam o que a tela mostrava.

## D3 — Cinco minutos sem conexão: para de tentar e oferece "Tentar de novo"

- Um timer em `desde + 5 min` troca `reconectando` por `offline {instavel}`, e o timer da próxima tentativa morre junto.
- **Parar de tentar é a leitura do "exibe Tentar de novo":** um botão que faz o que já está sendo feito sozinho não diz nada à visitante. Parar também encerra o socket que um celular esquecido abriria a cada 30 s para sempre.
- "Tentar de novo" abre um socket na hora. Se ele cair, começa uma queda nova: tentativa 1, `desde` de agora, mais cinco minutos.
- **Uma mensagem enviada em `offline` também reconecta na hora**, pelo mesmo caminho: é gesto da visitante, como o botão.
  - **Nota (27/09/2026):** mesmo que ainda haja um socket abrindo. A última tentativa pode estar pendurada no handshake quando os cinco minutos vencem, e esperar por ela seguraria a mensagem sem prazo.

## D4 — A fila local é o que está `enviando`

- **A mensagem enviada sem conexão fica `enviando`** — não `falhou` — até sair. Durante `reconectando` e `offline`, enviar ou reenviar põe a mensagem na fila e não abre socket (em `offline`, abre: D3).
- **No `open`, depois do `ola`, saem todas as mensagens `enviando` da tela**, na ordem, com o mesmo `id` — não só as que estavam na fila. As que tinham saído pelo socket que caiu e não receberam `ack` saem de novo: o servidor deduplica e confirma (D1 da TEC-364), então a mensagem é gravada uma vez só, que é o primeiro cenário da card.
- **O prazo do `ack` só corre com a mensagem no fio.** Ele é agendado quando o frame sai por um socket aberto, e todos os prazos morrem no `close`. Sem isso uma mensagem esperando a reconexão viraria "Não enviada" aos 10 s.
- **A fila vive na memória da página.** Recarregar a descarta, como já registrava a L6 da TEC-347.

## D5 — O `historico` confirma a pendente que o servidor já tem

Na reconexão, o `historico` chega antes do `ack` da mensagem reenviada — o servidor o lê no `ola`, antes de ler o reenvio. Se a mensagem tinha sido gravada antes da queda, ele a traz, e a tela a mostraria duas vezes: a do histórico e a pendente, que o `ack` depois confirma (L4 da TEC-347).

- **Uma fala da visitante que o histórico traz e a tela não tinha como confirmada casa com a primeira pendente de mesmo texto**, na ordem. A pendente vai para a posição do histórico, com o mesmo `messageId` e o estado `recebida`; o `ack` que vem depois não muda nada.
- Texto repetido ("sim", "ok") casa pela ordem: a primeira fala nova do histórico com a primeira pendente igual. O erro possível é confirmar a pendente errada entre duas de texto igual — as duas vão acabar `recebida` de qualquer jeito, porque ambas são reenviadas.

## D6 — A tela

- **`reconectando`:** uma linha `role="status"` acima do campo, "Reconectando…". O campo continua de pé: é para a visitante digitar durante a queda.
- **`instavel`:** a linha diz "Nosso atendimento está instável. Deixe sua mensagem que responderemos." — a frase da card, texto que a visitante lê, com acento.
- **`offline`:** "Sem conexão." (ou a frase de instável) e o botão "Tentar de novo".
- **O estado da conexão no cabeçalho é da TEC-351** ("Conectado", "Reconectando…", "Offline"). Esta card não mexe no cabeçalho; a linha acima do campo é o indicador que a card pede, e a TEC-351 decide se ele muda de lugar.

## Notas de implementação (27/09/2026)

- **Encerrar a conversa durante a queda abre a conversa nova na hora**, como fora dela: `encerrou` leva a conexão a `conectando`, e a tentativa marcada morre com o `reconectando`.
- **A queda não dorme** (D4 da TEC-347): com a conexão em `reconectando` ou `offline`, o prazo do sono vencendo não fecha nada — nem a tentativa ainda abrindo —, senão o fechamento de `adormecida` marcaria como `falhou` a fila que a reconexão vai mandar.
- A lista das `enviando` que o `open` manda vem do último render; a fila em memória cobre a mensagem despachada que ainda não chegou a um render, e o mapa por `messageId` impede que ela saia duas vezes.

## Verificação no navegador (27/09/2026)

Edge headless dirigido por CDP, `/embed/chat` servido pelo `next dev`, API local com as chaves externas inválidas:

| passo | resultado |
| --- | --- |
| API parada; "Tem vaga de garagem?" enviada durante a queda | "Reconectando…", mensagem "Enviando…" depois de 12 s — o prazo do `ack` não correu |
| API de volta | reconexão sozinha com `retomada: true`, mensagem "Recebida"; uma linha no banco por mensagem |
| Redis parado e a página recarregada | o handshake levou `1011` (`widget.central_indisponivel`): a frase de instável, "Reconectando…", mensagem "Enviando…" |
| Redis de volta | "Recebida"; o `historico` repôs a tela sem duplicar a pendente (D5) |
| API parada por mais de 5 min | "Sem conexão." e "Tentar de novo"; com a API de volta, nenhuma tentativa sozinha; o clique entregou a mensagem da fila |

## Testes

- `esperaDaTentativa`: 1, 2, 4, 8, 16, 30, 30 — os exemplos da card.
- Redutor: cada linha da tabela da D2; `tentativa` soma e `desde` fica; `instavel` a partir do `1011`; `abriu` zera; `desistiu` só a partir de `reconectando`; o `historico` da D5 (pendente vira `recebida` na posição, texto repetido pela ordem, sem pendente igual nada muda).
- Componente (socket falso, relógio falso): os quatro cenários do Gherkin — mensagem enviada na queda sai uma vez, depois do `ola`, e vai a "Recebida" no `ack`; as esperas 1, 8 e 30 s; "Tentar de novo" aos 5 min; `1011` mostra a frase e mantém a mensagem `enviando`. E: `1002` continua manual; o prazo do `ack` não corre durante a queda.
- Navegador: derrubar e subir o backend com uma mensagem escrita no meio.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Mensagem enviada sem conexão é entregue uma única vez | componente: um frame `mensagem` por socket, mesmo `id`, `enviando` → `recebida`; a dedup é do servidor (TEC-124, TEC-364); navegador |
| Espera crescente entre tentativas | `esperaDaTentativa` e componente com relógio falso |
| "Tentar de novo" após 5 minutos | componente com relógio falso |
| Atendimento fora do ar | componente: `close` `1011` → frase, mensagem `enviando`; navegador com o backend parado |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — Backend parado por inteiro não fecha com `1011`.** Sem processo do outro lado não há quem mande código: o navegador vê `1006`, igual a uma queda de rede, e a tela diz "Reconectando…", não a frase de instável. A frase aparece quando o servidor está de pé e o banco ou o Redis não.
- **L3 — A fila não sobrevive ao recarregar** (D4; L6 da TEC-347).
- **L4 — O evento `online` do navegador não antecipa a tentativa.** Com a rede de volta, a próxima tentativa espera o que faltar da espera corrente — até 30 s.
