# TEC-362 — O evento `digitando` no WebSocket do chat web

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-362](https://eduardodurieuxlopes.atlassian.net/browse/TEC-362) — épico TEC-133
**Branch:** `feat/tec-362-digitando-no-chat-web`
**Origem:** RN-FE-19.1, RN-FE-19.2, §6.3, RT-FE-07 (SRS mobIA Frontend v1.0); RN-04.7 e Emenda E-01 (SRS v1.0)

## A lacuna que esta card fecha está escrita no código, e diz o que fazer

A D5 do desenho da TEC-124:

> **Lacuna declarada:** o web fica sem indicador de digitação. Publicá-lo exigiria pôr a sessão na assinatura do `IndicadorDePresencaPort` — mexida de contrato que esta card não faz. Vai no comentário.

E o comentário existe, em `workers/main.py`:

```python
ctx["indicadores"] = {
    CANAL_WHATSAPP: WhatsAppIndicador(),
    # Lacuna declarada da TEC-124: publicar "digitando" exigiria a sessao
    # na assinatura do `IndicadorDePresencaPort`, e esta card nao mexe
    # nesse contrato.
    CANAL_WEB: IndicadorNoop(),
}
```

**Esta é a card que mexe no contrato.** Todo o resto do caminho já existe e já roda: `process_message` escolhe o indicador por `linha.channel`, `indicador_de_digitacao` agenda a tarefa, dorme os 4 s, confere opt-out e atendimento humano, e dispara. Hoje ele dispara contra um `IndicadorNoop`, que loga `presenca.noop` e volta.

## D1 — O port ganha `para`, e a palavra não é nova

A assinatura de hoje é `indicar_digitacao(*, provider_message_id: str, de: str)`, onde `de` é `message.recipient_external_id`. **No canal web isso não serve, e é exatamente a lacuna**: numa mensagem de entrada do widget,

| campo | valor no web | valor no WhatsApp |
| --- | --- | --- |
| `sender_external_id` | **a sessão** | o telefone do lead |
| `recipient_external_id` | `"widget"`, constante | o número da imobiliária |
| `provider_message_id` | `"<sessão>:<id do frame>"` | o `wamid` |

A publicação precisa da sessão, e ela está em `sender_external_id`. O port passa o outro.

**O port ganha `para: str`, alimentado por `message.sender_external_id`.** É quem vê o indicador: o telefone do lead no WhatsApp, a sessão no web. O `WhatsAppIndicador` o ignora — o indicador da Meta é anotação sobre a mensagem recebida, e continua precisando de `provider_message_id` e `de`.

**`para` não é palavra inventada para esta card.** É como este repo já chama a mesma coisa: `WebOutbound._deliver` publica em `canal_da_sessao(str(payload["para"]))`, ou seja, `para` já é a sessão no canal web e o número no WhatsApp. Escolher outro nome criaria um segundo vocabulário para o mesmo conceito, a uma função de distância.

**Recuperar a sessão de `provider_message_id` foi recusado.** Ela está lá — `_chave_do_id(sessao, identificador)` a põe como prefixo —, e um `split(":", 1)[0]` funcionaria hoje. Mas amarraria o indicador ao formato daquela chave, que existe para outra finalidade (dedup pela UNIQUE `(channel, provider_message_id)`), e a quebra seria silenciosa: publicar num canal errado não levanta, só não chega a ninguém. A lacuna da TEC-124 diz para mexer no contrato; mexer no contrato é o conserto, e o atalho é o que ela evitou.

## D2 — O frame leva `ate`, e o valor é 25 s por paridade

```json
{ "tipo": "digitando", "ate": "2026-09-24T20:10:35.123456+00:00" }
```

`ate` é o instante em que o cliente deve parar de mostrar o indicador. **O valor é `agora + 25 s`, e o 25 vem do WhatsApp**: a Emenda E-01 da RN-04.7 registra que o indicador da Meta "desaparece após 25 s", e a L1 da TEC-274 registra que aquela card não o renova. Os dois canais passam a mentir igual — um turno de 40 s deixa o lead sem indicador nos 11 s finais nos dois lugares.

**Paridade é a razão, e ela é melhor que o número.** Um valor diferente aqui faria o mesmo turno parecer diferente em cada canal, sem nada no produto que justificasse a diferença. Quando a renovação existir (a L1 da TEC-274 prevê a card), ela muda os dois juntos.

**O 25 é constante de módulo, não configuração.** No WhatsApp ele não é nosso: é o comportamento da Meta, e não há o que configurar. Pôr só o lado web em `Settings` criaria um botão que desalinha os canais e não tem caso de uso — e a `indicador_de_digitacao_apos_segundos`, que é configuração de verdade, continua sendo a única.

**O web fica com uma vantagem sobre o WhatsApp, e é de graça:** ali o cliente sabe *quando* parar, porque o instante veio no frame. No WhatsApp quem expira é a Meta, sem nos dizer.

## D3 — O `WebIndicador` mora em `domain/outbound/web.py`

Ao lado do `WebOutbound` e do `canal_da_sessao`, porque é a mesma publicação no mesmo canal do mesmo Redis. Pôr em `presenca.py` misturaria o agendador — que é agnóstico de canal e guarda o Protocol — com um adaptador de um canal só, que é a separação que o `WhatsAppIndicador` já respeita ao morar em `outbound/whatsapp.py`.

## D4 — Não herda de `GuardedOutbound`, e a razão é a mesma do irmão

O `WhatsAppIndicador` já a escreve: não há o que reservar, o indicador não é mensagem e não tem `kind`, e herdar obrigaria a inventar um kind sintético numa tabela cuja UNIQUE existe para dedup de mensagem. As guardas de opt-out e atendimento humano moram no agendador e rodam no instante do disparo — depois do sono, que é o que pega o lead que digita "parar" durante a espera.

## D5 — Falha propaga crua, e o agendador engole

O `RedisError` não é capturado aqui, ao contrário do que `WebOutbound._deliver` faz. São contratos diferentes, e os dois estão escritos:

- `OutboundPort.send` **tem** semântica de exceção — o tipo decide o desfecho do turno —, então `WebOutbound` traduz e loga.
- `IndicadorDePresencaPort` declara o oposto: *"Quem implementar isto pode levantar o que quiser; o agendador engole tudo e loga."* E o `WhatsAppIndicador` segue isso — *"Erro de rede propaga cru e o agendador o engole"*.

Capturar aqui produziria duas linhas de log para o mesmo evento e uma divergência entre os dois indicadores sem motivo.

## D6 — Zero ouvintes é o caso normal

Mesma razão que o docstring de `web.py` já dá para a entrega: a aba fechada é o comum, não falha. O log sai em `info` com a contagem.

**E aqui é ainda menos grave que na entrega.** Lá, uma publicação sem ouvinte é uma fala que só aparecerá na reconexão; aqui é um indicador que não vale nada fora do instante — não há o que recuperar depois, e nem se quer.

## Arquivos

```
src/mobia/domain/outbound/presenca.py    # o port ganha `para`; o agendador o repassa
src/mobia/domain/outbound/web.py         # WebIndicador
src/mobia/domain/outbound/whatsapp.py    # assinatura acompanha; `para` ignorado, com o porque
src/mobia/workers/main.py                # WebIndicador no lugar do IndicadorNoop, e o comentario da lacuna sai
```

`process_message.py` **não muda**: ele já passa `ctx["indicadores"][linha.channel]`, e o agendador é quem lê a `Message`.

## Testes

- **`tests/unit/`** — o frame: `tipo`, e `ate` sendo `agora + 25 s` em ISO-8601 com fuso. O relógio é congelado, senão a asserta vira "algo perto de 25".
- **`tests/integration/`** — no molde de `test_indicador_de_digitacao.py`, que já cobre o WhatsApp: o turno web que passa de 4 s publica no canal da sessão; o que não passa, não publica; opt-out e atendimento humano barram (as guardas são as mesmas e não são reimplementadas, mas um teste por canal prova que o web passa por elas).
- **A regressão que mais importa:** o `WhatsAppIndicador` continua recebendo `provider_message_id` e `de` inalterados depois da mudança de assinatura. É o que pega um `para` trocado por engano com o `de`.
- **Zero ouvintes não levanta** — é o caso normal da aba fechada.

## Emendas ao SRS

- **§6.3** — o frame de servidor listado é `{ "tipo": "digitando" }`, sem carga. Passa a ser `{ "tipo": "digitando", "ate": "<ISO-8601>" }`. O `ate` é o que permite ao cliente parar sozinho, em vez de ter de adivinhar a duração.
- **RN-04.7, Emenda E-01** — a regra hoje descreve só o canal WhatsApp e o efeito de tique azul que a Cloud API impõe. Ela passa a valer também no web, **sem** esse efeito colateral: no chat web o indicador é evento próprio, não anotação sobre a mensagem recebida, e não marca nada como lido.

## Lacunas declaradas

- **L1 — o indicador continua sem renovação**, agora nos dois canais. Turno acima de 29 s deixa o lead sem sinal no fim. É a L1 da TEC-274, herdada de propósito: renovar exige critério de parada próprio e decisão sobre o que fazer quando a renovação falha, e a paridade da D2 seria quebrada se só o web renovasse.
- **L2 — nada no navegador consome este evento ainda.** A TEC-351 é a card do indicador no chat web, e o card desta aqui a nomeia como destravada. **Dito sem rodeio: quando este PR entrar, ninguém vê "digitando..." no site** — existe o evento, não existe quem o desenhe.
- **L3 — o SRS do frontend não está no repo.** A card cita RN-FE-19.1, RN-FE-19.2, §6.3 e RT-FE-07 de um documento que `docs/srs/` não tem. O formato `{ ate: ISO-8601 }` veio do texto da card, que é a fonte de requisitos; se aquele SRS existe noutro lugar, este desenho não foi conferido contra ele. Mesma lacuna que a TEC-302 declarou.
- **L4 — a card manda registrar o formato "na spec da TEC-124 (P-09)", e não há P-09 ali.** As seções daquele desenho são D1 a D8. O formato foi registrado como emenda à **D5**, que é a seção que declarou esta lacuna — é onde quem procurar vai olhar.
