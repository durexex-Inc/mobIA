# TEC-363 — O evento `consentimento` no WebSocket do chat web

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-363](https://eduardodurieuxlopes.atlassian.net/browse/TEC-363) — épico TEC-200
**Branch:** `feat/tec-363-consentimento-no-chat-web`
**Origem:** RN-FE-20.2, §6.3, RT-FE-07 (SRS mobIA Frontend v1.0); TEC-207 (base legal)

## O que existe hoje, conferido

**Não existe consentimento neste repo.** Nem tabela, nem módulo, nem migration — `grep -ri consent src/` devolve zero. Esta card cria a entidade, e não só o evento.

O protocolo do `WS /widget/chat` tem, do cliente para o servidor, **dois** frames: `ola` (handshake) e `mensagem`. E o `_ler_do_lead` é estrito por construção:

```python
if not isinstance(frame, dict) or frame.get("tipo") != TIPO_MENSAGEM:
    await websocket.close(code=CODIGO_PROTOCOLO)
    return
```

Qualquer outra coisa fecha o socket com 1002. **Hoje um cliente que mandasse `consentimento` perderia a conversa inteira** — não é que o evento seja ignorado, é que ele derruba.

**E uma premissa da card mudou desde que ela foi escrita.** Ela diz "após o vínculo por telefone (TEC-129)", tratando-o como futuro. A TEC-129 **mergeou hoje** (PR #160): `vinculos_de_sessao` e `domain/identidade/` já existem. O vínculo ao lead deixou de ser hipotético.

## D1 — Append-only, no molde do opt-out — mas por uma razão que NÃO é a dele

A tabela `consentimentos` espelha a forma de `optout_events`: uma linha por evento, `(channel, conversation_key)` identificando quem, índice `created_at DESC`. O estado atual é o último evento. Pelo mesmo motivo que aquele módulo escreve: coluna booleana mutável apagaria a evidência, e evidência é o produto aqui.

**Mas há um ponto em que a analogia se inverte, e segui-la cegamente seria o erro.** O `optout_events` deliberadamente **não copia** o texto que disparou o evento — referencia `message_id`, porque o corpo já está cifrado em `messages` e copiá-lo criaria uma segunda cópia em claro da fala do lead.

Aqui é o contrário: **`texto_exibido` é NOSSO texto, não o do lead.** É o aviso de privacidade que mostramos, e ele é precisamente a prova de a que a pessoa consentiu — sem ele o registro diz "ela aceitou" sem dizer aceitou o quê, que não vale como evidência. Copiar é obrigatório, e não há dado pessoal nisso.

Quem for estender este módulo lendo o do opt-out por analogia vai concluir o oposto. Fica escrito no módulo.

## D2 — Duas datas, e só uma é confiável

| coluna | relógio | serve para |
| --- | --- | --- |
| `exibido_em` | **do cliente**, vem no frame | diagnóstico, e só |
| `created_at` | do Postgres, `server_default` | **a evidência** |

O `exibidoEm` que a card pede no payload é escrito pelo navegador da visitante, e um navegador com o relógio errado — ou um cliente forjado — escreveria o que quisesse. Guardá-lo tem valor (mostra quanto tempo a pessoa levou entre ver e aceitar, e denuncia skew), **mas a data que responde "quando ela consentiu" é a nossa**.

Mesmo argumento que `optout_events` já faz para o `created_at` dele, e pelo qual esta coluna também é `server_default=func.now()`.

## D3 — A recusa TAMBÉM vira linha, e isso diverge da leitura literal do Gherkin

O segundo critério de aceite:

> **Cenário: Visitante que não aceitou** — Então nenhum consentimento de marketing é registrado para ela

Duas leituras. **Não gravar nada** quando `marketing: false`, ou **gravar a recusa** com `marketing=false`.

**Escolhida: gravar.** Uma linha que diz `marketing=false` não é um consentimento registrado — é uma recusa registrada, e o critério continua satisfeito no que ele afirma: a pessoa não acaba com consentimento de marketing. O que se ganha é o que a LGPD de fato pede: prova de que o aviso foi exibido e de que a resposta foi "não". Sem a linha, "não perguntamos" e "perguntamos e ela recusou" ficam indistinguíveis — e são coisas muito diferentes numa auditoria.

É a mesma razão pela qual `optout_events` grava a reativação em vez de apagar o opt-out.

**Para que ninguém precise interpretar linhas**, o repositório expõe `tem_consentimento_de_marketing(...)`, e é ela que o teste do critério de aceite exercita. Um `SELECT` ingênuo na tabela traria os dois tipos de linha, e é exatamente isso que a função existe para evitar.

**A divergência vai no comentário da card.**

## D4 — O vínculo ao lead é JOIN, e não coluna

A card pede o registro "vinculado à sessão e, após o vínculo por telefone (TEC-129), ao lead".

**A tabela guarda só `(channel, conversation_key)` = (`web`, sessão).** O consentimento chega no começo da conversa, antes de a visitante digitar telefone nenhum — então, na hora de gravar, o vínculo quase sempre **não existe ainda**. Uma coluna `telefone` aqui nasceria nula e nunca seria preenchida, porque nada volta para atualizá-la.

O vínculo é derivado quando alguém perguntar, por `vinculos_de_sessao` — que a TEC-129 acabou de trazer. Guardar o par da sessão é o que torna esse join possível; copiar o telefone seria criar um segundo lugar para ele ficar desatualizado.

## D5 — O frame recusado não derruba o socket

O `_ler_do_lead` ganha um ramo antes do `close(1002)`. Dentro dele, três recusas que **não** fecham, no molde do `texto_longo_demais` que já existe:

- `marketing` que não é booleano;
- `textoExibido` vazio (sem ele não há evidência, e gravar seria fingir que há);
- `textoExibido` acima do teto.

**O teto não é zelo:** é entrada de cliente indo para uma coluna. A mesma lição de `TAMANHO_MAXIMO_DO_ID`, três funções acima — sem teto, um texto enorme estoura `DataError`, vira 1011, e o cliente reenvia o mesmo frame para sempre.

**E a falha ao gravar também não fecha.** Fechar transformaria um problema de banco em perda da conversa. O cliente recebe `erro` e pode tentar de novo; a alternativa — derrubar — destruiria o que a rota existe para proteger.

## D6 — Há ack, e ele é adição ao que a card pede

A card manda "aceitar o evento e persistir", e não menciona resposta. **O servidor responde `{ "tipo": "consentimento_registrado" }` mesmo assim**, porque sem ele o cliente não tem como saber se o registro caiu — e o consentimento é justamente a coisa que a TEC-352 vai querer confirmar antes de seguir. Um cliente sem ack ou assume que deu certo (e perde registros em silêncio) ou reenvia sempre (e enche a tabela).

Frame novo e não reaproveitamento do `recebido`: aquele carrega `id` de mensagem, que consentimento não tem.

**Adição ao escopo literal, e vai no comentário da card.**

## Arquivos

```
alembic/versions/0042_consentimentos.py
src/mobia/domain/consentimento/__init__.py
src/mobia/domain/consentimento/models.py        # Consentimento, append-only
src/mobia/domain/consentimento/repositorio.py   # registrar / tem_consentimento_de_marketing
src/mobia/api/routes/widget.py                  # o ramo do frame
```

## Testes

- **`tests/unit/`** — nada: não há regra pura aqui que valha isolar. A decisão está na forma da tabela e no ramo do socket, e as duas precisam de banco ou de WebSocket.
- **`tests/integration/`** — os dois cenários do Gherkin pelo repositório; a recusa gravando linha **e** `tem_consentimento_de_marketing` devolvendo `False` (é a D3 virando asserção); o último evento vencendo o anterior quando a pessoa muda de ideia.
- **`tests/integration/` (socket)** — no molde de `test_widget_*`: o frame aceito grava e recebe ack; `marketing` não-booleano, texto vazio e texto longo demais são recusados **sem fechar**; e o socket **continua servindo mensagem depois** — que é a regressão que importa, porque o ramo novo fica antes do `close(1002)` que todo frame desconhecido ainda deve levar.
- **Frame desconhecido continua fechando com 1002** — sem este teste, o ramo novo poderia afrouxar a checagem sem nada reclamar.

## Emendas ao SRS

- **§6.3** — os eventos do cliente listados são `{ "tipo": "mensagem", ... }`. Ganham `{ "tipo": "consentimento", "marketing": bool, "textoExibido": "...", "exibidoEm": "<ISO-8601>" }`, e os do servidor ganham `{ "tipo": "consentimento_registrado" }`.

## Lacunas declaradas

- **L1 — nada exibe o aviso ainda.** Dito sem rodeio: **quando este PR entrar, nenhuma visitante verá pedido de consentimento nenhum** — existe onde registrar, não existe quem pergunte. É a TEC-352, que esta card destrava.
- **L2 — o consentimento não muda comportamento nenhum hoje.** Nada consulta `tem_consentimento_de_marketing` para decidir se manda oferta, porque não há disparo de marketing neste repo. A função nasce sem chamador de produção, e é o registro que a card pede.
- **L3 — o vínculo ao lead depende de a visitante digitar o telefone.** Quem consente e nunca o digita fica com o consentimento preso à sessão, sem alcançar o WhatsApp dela. É consequência da forma da TEC-129, não desta card.
- **L4 — o SRS do frontend não está no repo.** RN-FE-20.2 e RT-FE-07 foram lidos do texto da card. Mesma lacuna que a TEC-302 e a TEC-362 declararam.
