# TEC-368 — Ler o `X-Request-Id` na entrada

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-368](https://eduardodurieuxlopes.atlassian.net/browse/TEC-368) — épico TEC-208
**Branch:** `feat/tec-368-x-request-id-na-entrada`
**Origem:** RNF-34 (SRS v1.0); lacuna L4 declarada no desenho da TEC-302

## O problema, medido

A TEC-302 fez o proxy `/bff/*` mandar `X-Request-Id` em toda chamada ao FastAPI. **O FastAPI não lê esse header em lugar nenhum.** O `correlation_id` de `app/logging.py` é um `ContextVar` que o processador `_add_correlation_id` injeta em todo evento do structlog — mas quem o preenche são dois handlers, cada um com um UUID próprio e novo:

- `api/routes/whatsapp.py`, no webhook;
- `api/routes/widget.py`, no WebSocket.

A rota que o painel chama não preenche nada. Hoje, portanto, **um evento de log do backend gerado pelo painel não tem correlação nenhuma** — nem com o Next, nem consigo mesmo entre duas linhas da mesma requisição.

## D1 — Middleware, e não dependência

`Depends` só roda nas rotas que o declaram, e o alvo é toda rota. O argumento é o mesmo que `main.py` já escreveu sobre o `RateLimitPorIP`:

> Aplica-se por omissão e não por opt-in: uma lista de rotas incluídas erraria para o lado de esquecer uma rota nova, que é o erro caro.

Vale igual aqui, e com menos risco: correlação não recusa requisição nenhuma, então não há o caso de "quem precisa ficar de fora". **Não há rota isenta** — nem `/health`. Um id custa um `uuid4` e não toca banco.

## D2 — O middleware tem de ser o MAIS EXTERNO, e isso se consegue adicionando-o por ÚLTIMO

Contraintuitivo o bastante para ser verificado na fonte do Starlette em vez de lembrado:

```python
def add_middleware(self, middleware_class, *args, **kwargs):
    self.user_middleware.insert(0, Middleware(middleware_class, *args, **kwargs))   # applications.py:107

def build_middleware_stack(self):
    ...
    app = self.router
    for cls, args, kwargs in reversed(middleware):     # applications.py:81
        app = cls(app, *args, **kwargs)
```

`add_middleware` insere no **índice 0**, e a pilha é construída em `reversed`, então o índice 0 é envolvido por último — ou seja, fica por **fora**. **O último `add_middleware` é o mais externo e roda primeiro.**

Então, em `create_app`:

```python
app.add_middleware(RateLimitPorIP)
app.add_middleware(CorrelacaoDeRequisicao)   # depois na ordem do codigo => por FORA na pilha
```

**Por que a correlação precisa ficar por fora do limitador**, e não é detalhe: o `RateLimitPorIP` emite `log.warning("ratelimit.blocked", ...)` e devolve 429 **sem chamar `call_next`**. Se a correlação estivesse por dentro, ela nunca rodaria nesse caminho — e o evento de bloqueio, que é exatamente o que alguém vai depurar, sairia sem `correlation_id`, com a resposta 429 sem o header. A requisição que mais interessa correlacionar seria a única sem correlação.

Isto vira **teste**, não só comentário: uma inversão futura na ordem das duas linhas não reprova em gate nenhum.

## D3 — `set()` sai de `whatsapp.py` e FICA em `widget.py`

A assimetria é obrigatória, e a razão já está escrita em `main.py` sobre o outro middleware:

> `BaseHTTPMiddleware` devolve cedo para todo escopo que não seja `http`, então o handshake de `/widget/chat` nunca passa por aqui.

- **`whatsapp.py`: o `correlation_id.set(uuid4())` sai.** É HTTP, então o middleware já garantiu um id antes de o handler rodar. Mantê-lo teria um efeito real — **sobrescreveria** o id de entrada por um novo. Hoje isso é inofensivo porque a Meta não manda `X-Request-Id`; amanhã, se mandar, o handler jogaria fora justamente a alça de correlação que ela ofereceu.
- **`widget.py`: fica, e ganha comentário dizendo por quê.** É WebSocket, escopo `websocket`, e nenhum `BaseHTTPMiddleware` o vê. Sem o comentário, a próxima pessoa que ler as duas linhas lado a lado apaga a que sobrou por simetria — e a correlação do widget some sem nada reprovar.

## D4 — A forma aceita é a MESMA do BFF, e isso não é coincidência a manter à mão

O BFF aceita `^[A-Za-z0-9._:-]{1,200}$` (`idDeRequisicao`, em `frontend/src/lib/servidor/bff.ts`). O backend aceita o mesmo.

**Se o backend fosse mais estrito, ele descartaria ids que o BFF propagou** — e a correlação quebraria exatamente no caso para que ela existe, sem nada reclamar: os dois lados logariam ids diferentes para a mesma requisição, e quem depurasse concluiria que são requisições distintas.

Não há como um gate ligar as duas expressões através da fronteira de linguagem. O que dá para fazer, e é o que se faz: **testar a borda dos dois lados com os mesmos valores** — 200 caracteres aceitos, 201 substituídos —, e escrever em cada lado que o outro existe.

Id malformado é **substituído**, nunca recusado: o cliente não deve perder a requisição por causa de um header de diagnóstico. Aceitá-lo sem olhar seria deixar entrada não confiável escrever no log.

## D5 — `ContextVar` com `Token`, e `reset()` no `finally`

`correlation_id.set()` devolve um `Token`; o valor é restaurado com `reset(token)`. O `finally` garante isso mesmo quando o handler levanta.

Na prática o uvicorn roda cada requisição na sua própria task, e `contextvars` são copiadas por task — então o vazamento entre requisições provavelmente não aconteceria de qualquer jeito. **"Provavelmente" não é a garantia que se quer num id que vai para o log**, e o custo de estar certo é uma linha. O cenário de vazamento está no Gherkin da card e vira teste.

Há uma sutileza do `BaseHTTPMiddleware` que o teste precisa cobrir de verdade, e não por suposição: ele roda o app de baixo numa **task separada**, criada dentro de `call_next`. Tasks do anyio herdam uma cópia do contexto no momento da criação, e o `set()` acontece antes — então o handler enxerga o valor. Isso é afirmação sobre biblioteca de terceiro, então o teste que prova é o que vale, não este parágrafo.

## D6 — A resposta devolve o id

`X-Request-Id` na resposta, inclusive nos caminhos de erro e no 429. Quem está diagnosticando lê o header da resposta que recebeu e procura por ele no log — sem isso, é preciso já saber o id para poder achá-lo, que é circular.

## Arquivos

```
src/mobia/api/middleware.py          # CorrelacaoDeRequisicao, ao lado do RateLimitPorIP
src/mobia/app/main.py                # add_middleware, DEPOIS do RateLimitPorIP
src/mobia/api/routes/whatsapp.py     # sai o set()
src/mobia/api/routes/widget.py       # fica o set(), com o porque escrito
```

A validação de forma mora em `middleware.py` e não em `app/logging.py`: é validação de header HTTP, e `logging.py` é sobre o pipeline de log.

## Testes

- **`tests/unit/`** — a forma aceita (UUID, ULID, 200 caracteres), a substituída (espaço, quebra de linha, 201 caracteres, vazio) e a gerada na ausência. Função pura, sem app.
- **`tests/integration/`** — com `TestClient`: o id de entrada aparece no evento de log e no header da resposta; sem header, um é gerado; malformado é substituído e a requisição é atendida; o id não vaza para a requisição seguinte.
- **A ordem da pilha (D2) tem teste próprio**, e é o que mais importa aqui: com o limitador estourado, o 429 carrega `X-Request-Id` e o evento `ratelimit.blocked` carrega `correlation_id`. É o que reprova se alguém trocar as duas linhas de `create_app` de lugar.
- **A borda de 200/201 é exercitada com os mesmos valores do teste do BFF** (`bff.test.ts`), pela D4.

## Emendas ao SRS

Nenhuma. A RNF-34 pede log estruturado com id de correlação; esta card a aproxima em vez de divergir dela.

## Lacunas declaradas

- **L1 — o widget continua com id próprio, sem correlação com quem o chamou.** WebSocket não passa por `BaseHTTPMiddleware`. Correlacionar o handshake exigiria middleware ASGI puro, que é mudança de forma e não desta card.
- **L2 — o SRS chama de `trace_id` (RNF-34 e o formato de erro do §API) e o código chama `correlation_id`.** A divergência é anterior a esta card e não é resolvida aqui; fica registrada para quem for implementar o formato de erro RFC 7807 do SRS, que promete `traceId` no corpo.
- **L3 — isto não é tracing distribuído.** A RNF-35 pede OpenTelemetry cobrindo webhook → fila → agente → tool → resposta. Um id que atravessa uma fronteira HTTP não é isso, e o ARQ (que roda os jobs) continua fora: um job enfileirado não herda o `correlation_id` de quem o enfileirou.
