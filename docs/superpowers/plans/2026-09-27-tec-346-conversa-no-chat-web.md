# TEC-346 — Conversa no chat web: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A visitante conversa com o assistente dentro do iframe do site: cada mensagem mostra `enviando` → `recebida` ou `falhou` com reenvio, as falas do agente aparecem uma por balão, o cabeçalho diz "Assistente virtual" junto ao nome, e a recusa por limite mostra "Muitas tentativas, aguarde N s" com o N real.

**Architecture:** O backend troca o `429` do handshake por `accept` + frame `erro` `muitas_tentativas` com `aguardeSegundos` calculado da janela deslizante + fechamento 1013. O Next passa a conhecer o endereço do WebSocket por uma variável do servidor e o autoriza no `connect-src` de `/embed/*`. No cliente, um redutor puro (`lib/conversa.ts`) guarda o estado da conversa, e um componente cliente (`Conversa.tsx`) liga o redutor ao `WebSocket` e desenha a tela.

**Tech Stack:** FastAPI + Starlette WebSocket, Redis (zset); Next.js 16 App Router + React 19; Vitest 5 + jsdom + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-27-tec-346-conversa-no-chat-web-design.md` — leia antes de qualquer task; D1–D5 e L1–L5 são citadas por número.

## Global Constraints

- Comentários e docstrings em `src/`, `tests/` e `frontend/src/`: português **sem acento**. Texto que a visitante lê: **com acento**.
- Commits: `tipo(TEC-346): o que passou a ser verdade`, assunto sem acento, terminando com exatamente `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gates Python antes de cada commit que toque `.py`: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Gates frontend antes de cada commit que toque `frontend/`: `npm run lint`, `npm test`, e `npx tsc --noEmit` sem erro novo (o `next build` checa os testes também). Todo `vi.fn` cujos `mock.calls` são indexados leva assinatura tipada.
- Frame de recusa, exato: `{"tipo": "erro", "codigo": "muitas_tentativas", "mensagem": "Muitas tentativas, aguarde {N} s.", "aguardeSegundos": N}`, fechamento **1013**. N inteiro ≥ 1; 60 quando não dá para calcular.
- Frame do cliente para mensagem: `{"tipo": "mensagem", "id": "<uuid v4>", "texto": "..."}`. `ola` sempre com `"sessao": null` nesta card (D4).
- Limite do campo: **1000** caracteres. Prazo do `ack`: **10000 ms**.
- Chave do `localStorage`: `mobia:sessao`.
- Textos da tela, exatos: cabeçalho `"{nome} · Assistente virtual"` ou `"Assistente virtual"`; estados `"Enviando…"`, `"Recebida"`, `"Não enviada"`; botão `"Reenviar"`; placeholder `"Escreva sua mensagem"`; botão `"Enviar"`.
- Cor só por classe e `var(--cor-primaria)`; nunca atributo `style` (CSP).
- Código se cita em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.

## Review Focus

1. **Duas abas ou o mesmo `messageId` reenviado recebem `ack` repetido** — o segundo `ack` de uma mensagem já `recebida` não muda nada, e o `ack` de um id desconhecido é ignorado. Teste na Task 3.
2. **`ack` que chega depois do prazo de 10 s** — a mensagem já em `falhou` passa a `recebida` (o servidor aceitou). Teste na Task 3.
3. **Frame que não é JSON, ou `tipo` desconhecido** — ignorado sem quebrar a tela. Teste na Task 3.
4. **`localStorage` que lança** (modo privado, storage bloqueado) — a conversa segue. Teste na Task 4.
5. **Enviar só espaços, ou colar mais de 1000 caracteres** — não envia vazio; o campo corta em 1000. Teste na Task 4.

---

### Task 1: A recusa por limite vira frame `muitas_tentativas` com a espera real

**Files:**
- Modify: `src/mobia/infra/rate_limit.py`, `src/mobia/api/routes/widget.py`
- Modify: `docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md` (emenda na D7)
- Test: `tests/unit/test_espera_do_limite.py` (novo), `tests/integration/test_widget_limite_por_ip.py`

**Interfaces:**
- Produces: `espera_para_caber(scores: Sequence[float], *, janela_segundos: float, agora: float) -> int` (pura) e `async def segundos_ate_caber(pool: Redis | None, *, chave: str, janela_segundos: float, agora: float | None = None) -> int` em `infra/rate_limit.py`; `ESPERA_PADRAO_EM_SEGUNDOS = 60`.

- [ ] **Step 1: Testes da função pura**

`tests/unit/test_espera_do_limite.py`:

```python
"""A espera ate caber de novo um pedido na janela deslizante. TEC-346, D1.

O zset guarda os `limite + 1` pedidos mais recentes (o barrado incluso). Um
pedido novo cabe quando sobram no maximo `limite - 1` antigos na janela, ou
seja, quando os DOIS mais velhos saem dela: a espera e `score[1] + janela -
agora`.
"""

import pytest

from mobia.infra.rate_limit import ESPERA_PADRAO_EM_SEGUNDOS, espera_para_caber


def test_espera_ate_o_segundo_mais_velho_sair_da_janela() -> None:
    # limite 2: zset com 3 pedidos, em 0, 40 e 50. O de 40 sai em 100.
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=80.0) == 20


def test_arredonda_para_cima() -> None:
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=80.5) == 20
    assert espera_para_caber([0.0, 40.2, 50.0], janela_segundos=60, agora=80.0) == 21


def test_nunca_menos_de_um_segundo() -> None:
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=100.0) == 1
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=500.0) == 1


def test_limite_um_espera_a_janela_desde_o_ultimo() -> None:
    # limite 1: zset com 2 pedidos; o segundo e o proprio barrado.
    assert espera_para_caber([10.0, 30.0], janela_segundos=60, agora=30.0) == 60


@pytest.mark.parametrize("scores", [[], [10.0]])
def test_sem_dados_suficientes_vale_o_padrao(scores: list[float]) -> None:
    assert espera_para_caber(scores, janela_segundos=60, agora=30.0) == ESPERA_PADRAO_EM_SEGUNDOS
```

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_espera_do_limite.py -q --tb=short` → ImportError.

- [ ] **Step 3: Implementar em `infra/rate_limit.py`**

Acrescente `from collections.abc import Sequence` aos imports e, depois de `consumir`:

```python
# TEC-346, D1. O que a visitante le quando nao da para calcular: a janela
# inteira, que e o teto do que ela pode ter de esperar.
ESPERA_PADRAO_EM_SEGUNDOS = math.ceil(JANELA_DE_UM_MINUTO)


def espera_para_caber(scores: Sequence[float], *, janela_segundos: float, agora: float) -> int:
    """Segundos ate um pedido novo caber, dados os scores do zset em ordem crescente.

    O zset guarda os `limite + 1` mais recentes -- o pedido barrado incluso,
    porque `consumir` adiciona antes de contar. O proximo cabe quando, somado a
    ele mesmo, o volume nao passa de `limite`: sobram no maximo `limite - 1`
    antigos, e para isso os dois mais velhos precisam ter saido da janela.

    Pura, para ser testada sem Redis. Nunca menos de 1: "aguarde 0 s" seria
    convite a tentar ja, e a contagem pode estar no limite exato.
    """
    if len(scores) < 2:
        return ESPERA_PADRAO_EM_SEGUNDOS
    return max(1, math.ceil(scores[1] + janela_segundos - agora))


async def segundos_ate_caber(
    pool: Redis | None,
    *,
    chave: str,
    janela_segundos: float,
    agora: float | None = None,
) -> int:
    """Le os dois scores mais velhos e devolve a espera. Redis fora: o padrao."""
    if pool is None:
        return ESPERA_PADRAO_EM_SEGUNDOS
    instante = time() if agora is None else agora
    try:
        pares = await pool.zrange(chave, 0, 1, withscores=True)
    except RedisError as exc:
        log.warning("ratelimit.indisponivel", erro=type(exc).__name__)
        return ESPERA_PADRAO_EM_SEGUNDOS
    return espera_para_caber(
        [float(score) for _, score in pares], janela_segundos=janela_segundos, agora=instante
    )
```

- [ ] **Step 4: Rodar e ver passar** — o mesmo comando → PASS.

- [ ] **Step 5: Trocar o teste de integração**

Em `tests/integration/test_widget_limite_por_ip.py`, substitua `test_handshake_acima_do_limite_recebe_429_com_retry_after` por:

```python
async def test_handshake_acima_do_limite_recebe_muitas_tentativas_e_1013(
    ws_cliente, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    """TEC-346, D1: o navegador nao le status de handshake recusado.

    A TEC-124 respondia HTTP 429 com `Retry-After` antes do `accept`. Para um
    navegador isso e so `onclose` 1006, igual a qualquer queda de rede. Agora o
    servidor aceita, diz quanto esperar num frame e fecha com 1013 ("Try
    Again Later"), que a pagina consegue ler.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(2):
        async with ws_cliente(ip="198.51.100.9") as ws:
            await ws.aceitar()

    async with ws_cliente(ip="198.51.100.9") as ws:
        await ws.aceitar()
        frame = await ws.receber()
        fechamento = await ws.evento()

    assert frame["tipo"] == "erro"
    assert frame["codigo"] == "muitas_tentativas"
    assert 1 <= frame["aguardeSegundos"] <= 60
    assert frame["mensagem"] == f"Muitas tentativas, aguarde {frame['aguardeSegundos']} s."
    assert fechamento["type"] == "websocket.close"
    assert fechamento["code"] == 1013

    evento = (
        await session.execute(select(RateLimitEvent).where(RateLimitEvent.chave == "198.51.100.9"))
    ).scalar_one()
    assert evento.escopo == ESCOPO_IP
    assert evento.limite == 2
    assert evento.volume == 3
```

Leia `ClienteWebSocket` em `tests/conftest.py` antes: se `receber()` não devolver o frame já decodificado, ou `evento()` não trouxer `code`, ajuste o teste ao helper sem mudar o que ele afirma. Atualize a docstring de módulo do arquivo se ela mencionar o 429.

- [ ] **Step 6: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_limite_por_ip.py -q --tb=short` → o novo falha (recebe a recusa HTTP).

- [ ] **Step 7: Implementar a recusa**

Em `widget.py`: `_cabe_no_limite_por_ip` passa a devolver também a chave e o pool necessários, ou a própria rota chama `segundos_ate_caber` com `chave_de_ip(ip)`. Escolha a forma que mantém a função legível; o que importa é que a espera seja lida da mesma chave que acabou de barrar. Substitua `_recusar_por_excesso` por:

```python
CODIGO_TENTE_MAIS_TARDE = 1013


async def _recusar_por_excesso(websocket: WebSocket, *, aguarde_segundos: int) -> None:
    """Aceita, diz quanto esperar e fecha com 1013. TEC-346, D1.

    **Nao e mais o 429 da TEC-124.** Aquela recusa era a certa para um cliente
    HTTP, e o cliente desta rota e um navegador: a API `WebSocket` nao expoe o
    status nem os cabecalhos de um handshake recusado, e a pagina via so
    `onclose` 1006, como numa queda de rede. Aceitar custa um `accept` a mais
    por conexao barrada, e e o que deixa a visitante ler "espere".

    Nada alem disso acontece: nenhum `ola` e lido e nenhuma sessao e criada.
    """
    await websocket.accept()
    await websocket.send_json(
        {
            "tipo": "erro",
            "codigo": "muitas_tentativas",
            "mensagem": f"Muitas tentativas, aguarde {aguarde_segundos} s.",
            "aguardeSegundos": aguarde_segundos,
        }
    )
    await websocket.close(code=CODIGO_TENTE_MAIS_TARDE)
```

Remova o import de `Response` se ficar sem uso. Atualize o comentário do bloco de fechamentos (1002, 1011) para listar o 1013, e a docstring de `_cabe_no_limite_por_ip` se ela descrever a recusa.

- [ ] **Step 8: Rodar e ver passar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_limite_por_ip.py tests/unit/test_espera_do_limite.py tests/features/test_atendimento_pelo_widget_web.py -q --tb=short` → PASS.

- [ ] **Step 9: Emenda na spec da TEC-124**

Abaixo da D7 de `docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md`, sem reescrever o texto dela, um item aninhado:

```markdown
- **Emenda (TEC-346, 27/09/2026):** o `429` com `Retry-After` saiu. A API `WebSocket` do navegador não expõe status nem cabeçalhos de um handshake recusado — a página via só `onclose` 1006. O handshake excedente agora é aceito, recebe `{"tipo": "erro", "codigo": "muitas_tentativas", "mensagem", "aguardeSegundos"}` e é fechado com 1013; a espera é o que falta da janela deslizante (`infra/rate_limit.py::espera_para_caber`). Ver a D1 do desenho da TEC-346.
```

- [ ] **Step 10: Gates, `tests/unit` inteiro, commit**

```bash
git add src/mobia/infra/rate_limit.py src/mobia/api/routes/widget.py tests/unit/test_espera_do_limite.py tests/integration/test_widget_limite_por_ip.py docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md
git commit -m "feat(TEC-346): o handshake barrado pelo limite diz quanto esperar num frame que o navegador le"
```

---

### Task 2: O Next conhece o endereço do WebSocket e o autoriza em `/embed/*`

**Files:**
- Create: `frontend/src/lib/servidor/enderecoDoChat.ts`
- Modify: `frontend/src/proxy.ts`, `frontend/README.md` (tabela de variáveis)
- Test: `frontend/src/lib/servidor/enderecoDoChat.test.ts`, `frontend/src/proxy.test.ts`

**Interfaces:**
- Produces: `enderecoDoChat(): string` (ex.: `ws://localhost:8000/widget/chat`) e `origemDoChat(): string` (ex.: `ws://localhost:8000`), sem `server-only` (o proxy importa); `politicaDeSeguranca(nonce, isDev, { embutivel, conectarA })` — com `embutivel: true` acrescenta `connect-src 'self' <conectarA>`.

- [ ] **Step 1: Testes do endereço**

```ts
import { afterEach, describe, expect, it } from 'vitest'

import { enderecoDoChat, origemDoChat } from './enderecoDoChat'

describe('enderecoDoChat', () => {
  afterEach(() => {
    delete process.env.MOBIA_WIDGET_WS_URL
    delete process.env.MOBIA_API_BASE
  })

  it('usa MOBIA_WIDGET_WS_URL quando existe', () => {
    process.env.MOBIA_WIDGET_WS_URL = 'wss://api.exemplo.com/widget/chat'
    expect(enderecoDoChat()).toBe('wss://api.exemplo.com/widget/chat')
    expect(origemDoChat()).toBe('wss://api.exemplo.com')
  })

  it('sem ela, deriva de MOBIA_API_BASE trocando http por ws', () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    expect(enderecoDoChat()).toBe('ws://backend:8000/widget/chat')
  })

  it('https vira wss', () => {
    process.env.MOBIA_API_BASE = 'https://api.exemplo.com'
    expect(enderecoDoChat()).toBe('wss://api.exemplo.com/widget/chat')
  })

  it('sem nenhuma, o padrao local', () => {
    expect(enderecoDoChat()).toBe('ws://localhost:8000/widget/chat')
  })
})
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar `enderecoDoChat.ts`**

```ts
/**
 * Onde o iframe do chat abre o WebSocket (TEC-346, D2).
 *
 * Lido no servidor -- pela pagina `/embed/chat`, que o passa por prop, e pelo
 * proxy, que monta o `connect-src` -- e nunca por `NEXT_PUBLIC_`: a regra do
 * README e de nenhuma variavel publica, e aqui nao ha necessidade de uma.
 *
 * Sem `server-only` porque o proxy importa este modulo, e ele nao tem segredo.
 */
export function enderecoDoChat(): string {
  const explicito = process.env.MOBIA_WIDGET_WS_URL
  if (explicito) {
    return explicito
  }
  const api = new URL(process.env.MOBIA_API_BASE ?? 'http://localhost:8000')
  api.protocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
  api.pathname = '/widget/chat'
  return api.toString()
}

/** A origem de `enderecoDoChat`, para o `connect-src`. A mesma fonte, para nao divergir. */
export function origemDoChat(): string {
  const url = new URL(enderecoDoChat())
  return `${url.protocol}//${url.host}`
}
```

(`new URL('ws://...').origin` é `"null"` para esquemas não especiais em alguns ambientes; por isso a montagem por `protocol` + `host`.)

- [ ] **Step 4: Rodar e ver passar.**

- [ ] **Step 5: CSP — testes**

Em `proxy.test.ts`:

```ts
  it('o embed pode abrir o WebSocket do chat, e so ele (TEC-346, D2)', () => {
    const politica = politicaDeSeguranca('abc', false, {
      embutivel: true,
      conectarA: 'wss://api.exemplo.com',
    })
    expect(politica).toContain("connect-src 'self' wss://api.exemplo.com")
  })

  it('o painel continua sem connect-src', () => {
    expect(politicaDeSeguranca('abc', false)).not.toContain('connect-src')
  })

  it('a resposta de /embed/chat autoriza a origem do WebSocket', () => {
    process.env.MOBIA_WIDGET_WS_URL = 'wss://api.exemplo.com/widget/chat'
    try {
      expect(cspDe('/embed/chat')).toContain("connect-src 'self' wss://api.exemplo.com")
      expect(cspDe('/leads')).not.toContain('connect-src')
    } finally {
      delete process.env.MOBIA_WIDGET_WS_URL
    }
  })
```

- [ ] **Step 6: CSP — implementar.** Em `politicaDeSeguranca`, aceite `conectarA?: string` nas opções e, quando `embutivel && conectarA`, acrescente `connect-src 'self' ${conectarA}` logo depois de `default-src`, com um comentário sem acento citando a D2. Em `proxy()`, passe `conectarA: origemDoChat()` só quando a rota é do embed. Rode `npx vitest run src/proxy.test.ts src/cabecalhos.test.ts src/lib/servidor/enderecoDoChat.test.ts` → PASS.

- [ ] **Step 7: README.** Na tabela "As variáveis, e por que nenhuma delas é `NEXT_PUBLIC_`" de `frontend/README.md`, uma linha para `MOBIA_WIDGET_WS_URL`: quem lê (a página `/embed/chat` e o proxy, no servidor), obrigatória não (derivada de `MOBIA_API_BASE`).

- [ ] **Step 8: Gates e commit** — `git commit -m "feat(TEC-346): o chat embutido sabe onde fica o WebSocket e a CSP o deixa conectar"`.

---

### Task 3: O redutor da conversa

**Files:**
- Create: `frontend/src/lib/conversa.ts`
- Test: `frontend/src/lib/conversa.test.ts`

**Interfaces:**
- Produces:

```ts
export type EstadoDaMensagem = 'enviando' | 'recebida' | 'falhou'
export type Mensagem =
  | { autor: 'visitante'; messageId: string; texto: string; estado: EstadoDaMensagem }
  | { autor: 'agente'; chave: string; texto: string }
export type Conexao =
  | { tipo: 'conectando' }
  | { tipo: 'aberta' }
  | { tipo: 'fechada' }
  | { tipo: 'aguardando'; mensagem: string; segundos: number }
export type Conversa = { mensagens: Mensagem[]; conexao: Conexao; sessao: string | null }
export type Evento =
  | { tipo: 'abriu' }
  | { tipo: 'enviou'; messageId: string; texto: string }
  | { tipo: 'frame'; bruto: string }
  | { tipo: 'fechou' }
  | { tipo: 'prazoDoAck'; messageId: string }
  | { tipo: 'reenviou'; messageId: string }
export const LIMITE_DE_CARACTERES = 1000
export const PRAZO_DO_ACK_MS = 10_000
export const INICIAL: Conversa
export function reduzir(estado: Conversa, evento: Evento): Conversa
export function novoMessageId(): string
```

Regras de `reduzir` (cada uma com teste):
- `abriu` → `conexao: aberta`.
- `enviou` → acrescenta mensagem da visitante em `enviando`.
- `frame` com JSON inválido ou `tipo` desconhecido → estado igual (mesma referência).
- `sessao` → `sessao` = o UUID do frame.
- `mensagem` (do servidor) → acrescenta mensagem do agente; `chave` única e estável (ex.: contador `agente-${n}` derivado do total de mensagens).
- `imovel` com `texto` string não vazia → mensagem do agente com esse texto; sem texto → estado igual.
- `ack` de id `enviando` ou `falhou` → `recebida`; de id `recebida` ou desconhecido → estado igual.
- `erro` com `messageId` de mensagem `enviando` → `falhou`.
- `erro` com `codigo: 'muitas_tentativas'` → `conexao: { tipo: 'aguardando', mensagem, segundos: aguardeSegundos }` (segundos inválido → 60).
- `digitando`, `imagem`, `historico`, `consentimento_registrado` → estado igual.
- `fechou` → toda `enviando` vira `falhou`; `conexao: fechada`, exceto se já `aguardando` (continua `aguardando`).
- `prazoDoAck` de id em `enviando` → `falhou`; qualquer outro → estado igual.
- `reenviou` de id em `falhou` → `enviando`, sem mudar a posição da mensagem.

`novoMessageId`: `crypto.randomUUID()` se existir; senão v4 por `crypto.getRandomValues` (16 bytes, byte 6 `& 0x0f | 0x40`, byte 8 `& 0x3f | 0x80`, formatado 8-4-4-4-12). Teste: formato v4 por regex nos dois caminhos (o de reserva com `randomUUID` removido por stub).

- [ ] **Step 1:** Escreva `conversa.test.ts` com um teste por regra acima (incluindo os três balões em ordem: três frames `mensagem` → três mensagens do agente na ordem, com chaves distintas) e os itens 1–3 do Review Focus.
- [ ] **Step 2:** Rode e veja falhar.
- [ ] **Step 3:** Implemente `conversa.ts` (docstring de módulo sem acento citando a D3 e dizendo o que esta card ignora e qual card trata cada frame ignorado). O redutor não faz I/O, não lê relógio e não toca `localStorage`.
- [ ] **Step 4:** Rode e veja passar; `npx tsc --noEmit` sem erro novo.
- [ ] **Step 5:** Lint e commit — `feat(TEC-346): o estado da conversa do chat web e um redutor puro`.

---

### Task 4: O componente da conversa, o cabeçalho e a página

**Files:**
- Create: `frontend/src/components/Conversa.tsx`
- Modify: `frontend/src/components/CabecalhoDoChat.tsx`, `frontend/src/app/embed/chat/page.tsx`, `frontend/src/lib/aparencia.ts` (se `nomeExibido` mudar de papel), `frontend/src/app/globals.css`
- Test: `frontend/src/components/Conversa.test.tsx`, `frontend/src/components/CabecalhoDoChat.test.tsx`

**Interfaces:**
- Consumes: `reduzir`, `INICIAL`, `novoMessageId`, `LIMITE_DE_CARACTERES`, `PRAZO_DO_ACK_MS` (Task 3); `enderecoDoChat()` (Task 2).
- Produces: `<Conversa endereco={string} />` (client component); `<CabecalhoDoChat nome={string | null} />`.

**Comportamento de `Conversa`:**
- Monta: `new WebSocket(endereco)`; no `open`, despacha `abriu` e manda `{"tipo":"ola","sessao":null}`.
- `message` → despacha `frame` com `event.data` (string). Quando o estado ganha uma `sessao` nova, grava em `localStorage['mobia:sessao']` dentro de try/catch.
- `close` → despacha `fechou`.
- Enviar: texto sem espaços nas pontas vazio → nada; senão `novoMessageId()`, despacha `enviou`, manda `{"tipo":"mensagem","id","texto"}` e agenda `prazoDoAck` em `PRAZO_DO_ACK_MS`. Limpa o campo.
- Reenviar: despacha `reenviou`; se o socket estiver aberto, manda o mesmo frame; se fechado, abre um socket novo (mesmo fluxo de montagem) e manda as mensagens `enviando` depois do `ola`. Agenda de novo o prazo.
- `aguardando`: o formulário é trocado pela `mensagem` do servidor; depois de `segundos` o componente abre um socket novo.
- Desmonta: fecha o socket e limpa timers.
- Marcação: `<ol aria-live="polite">` com um `<li>` por mensagem (classe por autor); o da visitante tem o texto do estado (`"Enviando…"`, `"Recebida"`, `"Não enviada"`) e, em `falhou`, `<button type="button">Reenviar</button>`. Formulário com `<textarea maxLength={1000} placeholder="Escreva sua mensagem" aria-label="Mensagem">`, contador `"{n}/1000"` e `<button type="submit">Enviar</button>`.

- [ ] **Step 1: Testes com um WebSocket falso**

Em `Conversa.test.tsx`, uma classe `SocketFalso` (instâncias guardadas numa lista; `enviados: string[]`; métodos de teste `abrir()`, `receber(frame: object)`, `fechar(code = 1006)`; `readyState`; `send`, `close`, `addEventListener` ou `onopen/onmessage/onclose` — use a mesma API que o componente usar) instalada com `vi.stubGlobal('WebSocket', SocketFalso)`. Testes:
  1. **Cenário 1:** envia "Vocês têm apartamento no Campeche?" → aparece com "Enviando…" e o frame enviado tem `tipo`, `id` v4 e `texto`; `receber({tipo:'ack', messageId})` → "Recebida".
  2. **Cenário 2:** três `receber({tipo:'mensagem', texto, kind})` → três `<li>` do agente na ordem.
  3. **Cenário 3:** `receber({tipo:'erro', codigo:'muitas_tentativas', mensagem:'Muitas tentativas, aguarde 20 s.', aguardeSegundos:20})` + `fechar(1013)` → o texto "Muitas tentativas, aguarde 20 s." está na tela; com timers falsos, depois de 20 s existe um segundo `SocketFalso`.
  4. Sem `ack` em 10 s → "Não enviada" e "Reenviar"; clicar reenvia com o **mesmo** `id`.
  5. Socket fecha com mensagem pendente → "Não enviada"; "Reenviar" abre socket novo, manda `ola` e depois a mensagem com o mesmo id.
  6. `ola` enviado no `open` com `sessao: null`; `receber({tipo:'sessao', sessao})` grava em `localStorage['mobia:sessao']`; com `localStorage.setItem` lançando, a conversa segue (Review Focus 4).
  7. Enviar só espaços não manda nada; o `textarea` tem `maxLength` 1000 e o contador mostra `n/1000` (Review Focus 5).
  8. A lista tem `aria-live="polite"`.

`CabecalhoDoChat.test.tsx`: com `nome="Lia"` o `h1` é "Lia · Assistente virtual"; com `nome={null}`, "Assistente virtual" (cenário 4).

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar.**
  - `CabecalhoDoChat` recebe `nome: string | null` e monta o texto; se `nomeExibido` deixar de ter uso, remova-o de `lib/aparencia.ts` e dos testes dele (ou mantenha-o se a página ainda usar), sem deixar código morto.
  - `Conversa.tsx` com `'use client'`, `useReducer(reduzir, INICIAL)`, o socket num `useRef`, timers num `useRef<Map>`. Docstring sem acento citando D3–D5 e dizendo que reconexão automática é da TEC-348 e retomada é da TEC-347.
  - `page.tsx`: passa `aparencia.nomeDoAssistente` ao cabeçalho e `enderecoDoChat()` à `Conversa`; `AvisoDePronto` continua. Atualize a docstring da página (ela diz que a conversa é da TEC-346).
  - `globals.css`: classes da lista, dos balões (visitante à direita com `var(--cor-primaria)` e texto branco; agente à esquerda, cinza claro), do estado, do formulário. Nada de atributo `style`.

- [ ] **Step 4: Rodar e ver passar** — `npx vitest run src/components src/lib`; `npx tsc --noEmit` sem erro novo; `npm run build` lista `/embed/chat`.

- [ ] **Step 5: Lint, `npm test`, commit** — `feat(TEC-346): a visitante conversa pelo chat do site e ve se a mensagem chegou`.

---

### Task 5: Verificação e entrega

- [ ] **Step 1: Comentários tocados.** `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` e `--checar`; releia cada `ALTERADO`/`VIZINHO`/`PROSA`/`NOMEIA`. Atenção a textos que ainda digam que a recusa é `429` (spec da TEC-124 fora da emenda não se reescreve; README, docstrings e comentários sim) e ao que diz que "nenhum cliente consome o WebSocket".
- [ ] **Step 2: Status da spec** para `implementado`, com nota datada em cada decisão que divergiu.
- [ ] **Step 3: Suíte inteira** (`-n 8 --dist loadfile --tb=short`), hash anotado; falha repetida → comparar com a `main` antes de concluir.
- [ ] **Step 4: Navegador** (controlador): API com `TENANT_SLUG`, Next dev, site hospedeiro; conversar de verdade (a resposta do agente depende do worker ARQ e do modelo — se não houver worker/chave, verificar ao menos `ack` e o estado "Recebida"); forçar o limite com `RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO=2` e confirmar "Muitas tentativas, aguarde N s"; decidir a L2 (`upgrade-insecure-requests` com `ws://` em dev).
- [ ] **Step 5: Push, PR, comentário na card e "Em análise"** (controlador).
