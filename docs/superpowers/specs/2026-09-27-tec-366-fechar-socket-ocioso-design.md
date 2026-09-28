# TEC-366 — O servidor encerra as conexões ociosas do WebSocket do chat web

**Status:** implementado
**Card:** [TEC-366](https://eduardodurieuxlopes.atlassian.net/browse/TEC-366) — épico TEC-123
**Branch:** `feat/tec-366-fechar-socket-ocioso`
**Depende de:** TEC-124 (`WS /widget/chat`), TEC-347 (o sono do cliente, D4)

## O que existe quando a card começa

- **`chat` (`api/routes/widget.py`) roda duas tarefas** até a primeira terminar: `_ler_do_lead` e `_escrever_do_agente`. Nenhuma tem prazo, então um socket sem tráfego fica aberto até o cliente ir embora.
- **O cliente só dorme com o painel minimizado** (TEC-347, D4): 30 minutos sem nenhum frame, em nenhum sentido, e ele fecha o socket como `adormecida`. Reabrir o painel reconecta com a sessão, e o `historico` repõe o que faltou. Com o painel aberto, e para clientes antigos ou conexões órfãs, nada fecha.
- **Qualquer fechamento que não seja o sono vira `fechada`** no cliente, e reabrir o painel não reconecta a partir dela (a reconexão automática é da TEC-348). Enviar uma mensagem reconecta de qualquer estado (`transmitir`).
  - **Nota (TEC-348, 27/09/2026):** desde a TEC-348 só o `1002` vira `fechada`; os outros fechamentos que não são o sono vão a `reconectando`, e quem reabre o socket é o timer da reconexão, não o painel. Enviar durante a reconexão põe a mensagem na fila em vez de abrir socket.

## D1 — Uma terceira tarefa vigia a ociosidade

- **`_vigiar_ociosidade`** entra no mesmo `asyncio.wait` das outras duas. Ela dorme exatamente o que falta para o prazo, contado do último frame, e fecha com `CODIGO_OCIOSA` quando ele vence. Terminar a tarefa tira `chat` da espera pelo mesmo caminho da visitante fechando a aba, e o `finally` solta a fila da central.
- **Tráfego é qualquer frame, nos dois sentidos**, como no cliente: o frame que chega (inclusive um que será recusado) e a fala do agente que sai. `ack` e `erro` respondem a um frame que já contou.
- **O relógio é monotônico:** um ajuste do relógio do host não fecha nem eterniza uma conexão.
- **O prazo é `widget_ociosidade_segundos`**, com padrão de 1800 s, os mesmos 30 minutos do cliente.

## D2 — `CODIGO_OCIOSA = 4000`, e o cliente o trata como sono

- **O código vem da faixa privada do RFC 6455.** Nenhum código padrão diz "ocioso": 1000 é fechamento sem motivo, e 1001 é o servidor indo embora.
- **O cliente trata 4000 como `adormeceu`**, antes do `fechou` (`frontend/src/components/Conversa.tsx`). A retomada que a card pede depende disso:
  - com o painel minimizado, reabri-lo reconecta com a sessão e o histórico, exatamente como no sono do próprio cliente;
  - com o painel aberto, a próxima mensagem reconecta, pelo caminho que já existia.

  Sem essa mudança, o fechamento do servidor viraria `fechada`, e reabrir o painel não reconectaria.
- **O cliente e o servidor usam os mesmos 30 minutos**, e quem chegar primeiro dá o mesmo resultado: `adormecida`.

## Testes

- **Backend** (`test_widget_ociosidade.py`, com o prazo encurtado pelo ambiente):
  - o socket ocioso fecha com 4000 e deixa `widget.ociosa` no log;
  - três mensagens espaçadas atravessam mais que o prazo sem derrubar a conexão;
  - a sessão fechada por ociosidade se retoma com o histórico;
  - o padrão é de 30 minutos.
- **Frontend** (`Conversa.test.tsx`):
  - 4000 com o painel minimizado vira sono, e reabrir reconecta com a sessão;
  - 1006 não vira sono, e reabrir não reconecta, o que prova que é o código que decide;
  - 4000 com o painel aberto, e a próxima mensagem reconecta.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Fechar conexão ociosa | `test_conexao_ociosa_e_fechada_pelo_servidor`, com o prazo encurtado. Os 31 minutos reais não são esperados |
| Retomar depois do fechamento | `test_retomar_depois_do_fechamento_por_ociosidade` e os dois testes de 4000 do cliente |

## Lacunas declaradas

- **L1 — A tela não diferencia `adormecida` de `fechada`.** O estado da conexão na tela é da TEC-351. Até lá, a visitante não vê aviso nenhum.
- **L2 — Um cliente antigo, sem o tratamento de 4000, vê o fechamento como queda.** Ele ainda reconecta na próxima mensagem, mas reabrir o painel não o reconecta sozinho.
