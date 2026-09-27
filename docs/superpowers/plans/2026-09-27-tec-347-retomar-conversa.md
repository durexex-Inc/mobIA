# TEC-347 — Retomar a conversa: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recarregar a página retoma a conversa com o histórico; "Encerrar conversa" começa outra; a sessão guardada vale 30 dias desde a criação; minimizado 30 minutos sem atividade, o socket dorme e reabrir retoma.

**Architecture:** Um módulo puro guarda e valida a sessão no `localStorage`. O redutor da TEC-346 passa a tratar `historico` como verdade do servidor e ganha os eventos `encerrou` e `adormeceu`. O componente `Conversa.tsx` lê a sessão guardada na primeira conexão, grava só sessão nova, tem o menu de encerrar e o prazo de 30 minutos quando minimizado. O `widget.js` avisa o iframe ao abrir e fechar o painel.

**Tech Stack:** Next.js 16 + React 19, Vitest 5 + jsdom + Testing Library; `frontend/public/widget.js` em JavaScript puro.

**Spec:** `docs/superpowers/specs/2026-09-27-tec-347-retomar-conversa-design.md` — D1–D4, L1–L5.

## Global Constraints

- Comentários em `frontend/src/` e `frontend/public/widget.js`: português **sem acento**. Texto que a visitante lê: **com acento**.
- Commits: `tipo(TEC-347): o que passou a ser verdade`, assunto sem acento, terminando com exatamente `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gates (em `frontend/`): `npm run lint`, `npm test`, `npx tsc --noEmit` sem erro novo (todo `vi.fn` com `mock.calls` indexado leva assinatura tipada), e na última task `npm run build` e `npm run verificar:widget`.
- Chave do storage: `mobia:sessao`. Formato: `{"sessao": "<uuid>", "criadaEm": <epoch ms>}`. Validade: `30 * 24 * 60 * 60 * 1000` ms desde `criadaEm`.
- Prazo de sono minimizado: `30 * 60 * 1000` ms.
- Aviso do loader: `{ tipo: 'mobia:visibilidade', aberto: boolean }`, enviado com `targetOrigin` = origem do chat.
- Textos da tela, exatos: botão `"Opções da conversa"` (aria-label; o rótulo visível pode ser `⋯`), item `"Encerrar conversa"`, pergunta `"Encerrar esta conversa? O histórico some desta tela."`, botões `"Encerrar"` e `"Cancelar"`.
- Cor só por classe e `var(--cor-primaria)`; nunca atributo `style` no iframe (CSP). No `widget.js` o estilo segue por CSSOM, como já está.
- `.md` cita código por âncora (`arquivo.ts::Nome`), nunca por número de linha.

## Review Focus

1. **Duas abas da mesma sessão** — ambas retomam; nenhuma regrava o storage (a sessão é a mesma), então o prazo não anda.
2. **`historico` chegando com mensagem local ainda `enviando`** — a local fica no fim, uma vez só; se o `ack` dela chegar depois, vira `recebida` sem duplicar.
3. **Frame `historico` malformado** (`mensagens` não é lista, item sem `texto`, `papel` desconhecido) — itens inválidos são pulados; frame inteiro inválido não muda nada.
4. **Aviso de visibilidade vindo de outra janela ou com `aberto` não booleano** — ignorado.
5. **Encerrar durante a espera de `muitas_tentativas`** — a tela zera e a nova conexão respeita a espera? Regra: encerrar durante `aguardando` apaga a sessão e a tela, mas **não** abre conexão antes de a espera acabar.

---

### Task 1: A sessão guardada, com validade de 30 dias

**Files:** Create `frontend/src/lib/sessaoGuardada.ts`, `frontend/src/lib/sessaoGuardada.test.ts`.

**Interfaces:**

```ts
export const CHAVE_DA_SESSAO = 'mobia:sessao'
export const VALIDADE_DA_SESSAO_MS = 30 * 24 * 60 * 60 * 1000
export type Armazem = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
/** A sessao valida guardada, ou null. Apaga o que estiver invalido ou vencido. Nunca lanca. */
export function lerSessao(armazem: Armazem | null, agora: number): string | null
/** Grava `sessao` com `criadaEm = agora`, a menos que ja seja a guardada. Nunca lanca. */
export function gravarSessao(armazem: Armazem | null, sessao: string, agora: number): void
/** Apaga a sessao guardada. Nunca lanca. */
export function apagarSessao(armazem: Armazem | null): void
/** `window.localStorage`, ou null se acessar lancar. */
export function armazemDoNavegador(): Armazem | null
```

- [ ] **Step 1: Testes.** Um armazém em memória (`Map`) que implementa `Armazem`, e um que lança em toda operação. Casos:
  - grava e lê de volta dentro do prazo (29 dias e 23 h depois);
  - 31 dias depois → `null` **e** a chave foi removida;
  - exatamente 30 dias → `null` (a validade é `< 30 dias`);
  - `criadaEm` no futuro → `null` e removida;
  - JSON torto, texto puro `"415b23dc-823d-4926-9442-964169fdb758"` (o formato da TEC-346), objeto sem `sessao`, `sessao` que não é UUID, `criadaEm` não numérico → `null` e removida;
  - `gravarSessao` com a mesma sessão já guardada **não** muda `criadaEm` (prazo desde a criação — D1);
  - `gravarSessao` com sessão diferente substitui, com `criadaEm = agora`;
  - armazém que lança: `lerSessao` → `null`, `gravarSessao`/`apagarSessao` não lançam;
  - `armazem = null`: as três funções funcionam sem lançar.
- [ ] **Step 2:** Rodar e ver falhar.
- [ ] **Step 3:** Implementar. UUID pelo padrão `/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i`. Docstring sem acento citando a D1 e dizendo por que o prazo não renova.
- [ ] **Step 4:** Rodar e ver passar; lint; tsc.
- [ ] **Step 5:** Commit — `feat(TEC-347): a sessao do chat fica guardada por no maximo 30 dias desde a criacao`.

---

### Task 2: O redutor trata `historico`, `encerrou` e `adormeceu`

**Files:** Modify `frontend/src/lib/conversa.ts`, `frontend/src/lib/conversa.test.ts`.

**Interfaces (acréscimos):**
- `Conexao` ganha `| { tipo: 'adormecida' }`.
- `Evento` ganha `| { tipo: 'encerrou' } | { tipo: 'adormeceu' }`.

Regras novas (cada uma com teste):
- **`historico`** com `mensagens` lista: monta uma mensagem por item válido — `papel: 'lead'` com `texto` string não vazia → visitante `recebida`, `messageId` sintético `historico-${i}`; `papel: 'agente'` com `texto` string não vazia → agente com `chave` única; item inválido é pulado. A nova lista é **essas mensagens seguidas das mensagens locais da visitante em `enviando` ou `falhou`, na ordem em que estavam**. As `recebida` locais e as do agente em memória saem (o histórico as contém). `mensagens` que não é lista → mesma referência.
- As chaves do agente precisam continuar únicas depois de um `historico` seguido de novas falas (hoje a chave deriva do comprimento da lista — confira que continua sem colisão ou troque por um contador guardado no estado; se trocar, o estado ganha o campo e `INICIAL` também).
- **`ack`** de um id `historico-*` não existe na prática; nada muda.
- **`encerrou`** → `{ ...INICIAL, conexao }` onde `conexao` é a atual se for `aguardando` (a espera continua valendo — Review Focus 5), senão `{ tipo: 'conectando' }`. `sessao` volta a `null`.
- **`adormeceu`** → `conexao: adormecida`. Nada muda nas mensagens.
- **`fechou` com `conexao: adormecida`** → continua `adormecida`, e as `enviando` **ainda** viram `falhou` (elas não foram confirmadas; a regra da TEC-346 vale). Mesma referência se nada mudar.
- **`abriu`** a partir de `adormecida` → `aberta` (regra atual).

- [ ] **Step 1:** Testes, incluindo Review Focus 2 e 3.
- [ ] **Step 2:** Ver falhar. **Step 3:** Implementar; atualize a docstring de módulo (ela diz que `historico` é ignorado e é da TEC-347). **Step 4:** Ver passar; lint; tsc.
- [ ] **Step 5:** Commit — `feat(TEC-347): o historico do servidor volta para a tela do chat`.

---

### Task 3: O componente retoma, encerra e dorme

**Files:** Modify `frontend/src/components/Conversa.tsx`, `frontend/src/components/Conversa.test.tsx`, `frontend/src/app/globals.css`, e o cabeçalho se o menu morar nele (`frontend/src/components/CabecalhoDoChat.tsx`). README do frontend: a seção do chat.

Comportamento:
- **Primeira conexão:** `sessaoRef` começa com `lerSessao(armazemDoNavegador(), Date.now())`. O `ola` da primeira conexão leva esse valor (ou `null`).
- **Gravação:** quando `conversa.sessao` muda para um valor não nulo, `gravarSessao(armazem, sessao, Date.now())` (a função já não regrava a mesma sessão). Remova a gravação direta que existe hoje.
- **Menu:** botão com `aria-label="Opções da conversa"`, `aria-haspopup="menu"` e `aria-expanded`; o menu tem o item "Encerrar conversa". Escolher mostra a confirmação (texto exato das Global Constraints) com "Encerrar" e "Cancelar". "Cancelar" fecha sem efeito. "Encerrar": `apagarSessao`, `sessaoRef.current = null`, despacha `encerrou`, fecha o socket atual (sem que o `close` dele marque nada — ele já é o socket antigo), limpa os prazos de `ack`, e — se não estiver `aguardando` — abre uma conexão nova (que manda `ola` com `null`). Escape fecha o menu.
- **Visibilidade:** um listener de `message` na janela aceita só `event.source === window.parent`, `data.tipo === 'mobia:visibilidade'` e `typeof data.aberto === 'boolean'`. Estado inicial: aberto.
  - Ao ficar minimizado: agenda o sono em `30 * 60 * 1000` ms. Qualquer frame enviado ou recebido enquanto minimizado reagenda. Ao vencer: despacha `adormeceu` e fecha o socket.
  - Ao abrir: cancela o sono; se a conexão estiver `adormecida`, abre uma conexão nova com a sessão (`sessaoRef.current`).
  - Desmontar limpa o timer e o listener.
- **CSS:** o menu e a confirmação por classe; nada de atributo `style`.

Testes (WebSocket falso da TEC-346, `vi.useFakeTimers`, um `localStorage` controlado):
1. **Cenário 1:** storage com sessão válida → o primeiro `ola` leva a sessão; `receber(historico com 12 falas)` → 12 balões na ordem, as da visitante com "Recebida" e sem "Reenviar".
2. Storage vazio → `ola` com `null`; `receber(sessao)` grava `{sessao, criadaEm}`; `receber(sessao)` igual de novo não regrava (`criadaEm` inalterado).
3. **Cenário 3:** storage com sessão de 31 dias → `ola` com `null` e a chave foi apagada.
4. **Cenário 2:** menu → "Encerrar conversa" → confirmação → "Encerrar": storage apagado, tela sem balões, novo socket com `ola` `null`. "Cancelar" não muda nada.
5. **Cenário 4:** aviso `aberto:false` do pai → 30 min depois o socket fecha e a tela não mostra falha; aviso `aberto:true` → novo socket com `ola` levando a sessão; `historico` repõe as falas.
6. Frame recebido enquanto minimizado reinicia o prazo (29 min + frame + 29 min → ainda aberto).
7. Aviso de outra janela (`source` ≠ `window.parent`) ou com `aberto: 'false'` é ignorado (Review Focus 4). No jsdom `window.parent === window`: simule outra janela com `source: {}` ou um objeto qualquer.
8. Encerrar durante `muitas_tentativas` não abre conexão antes do fim da espera (Review Focus 5).
9. `localStorage` que lança: o chat abre com `null` e conversa normalmente.

- [ ] Steps: testes → ver falhar → implementar → ver passar → lint, tsc, `npm test` → commit `feat(TEC-347): a visitante retoma a conversa ao recarregar e pode encerra-la`.
- Atualize a docstring de `Conversa.tsx` (ela diz que a retomada é da TEC-347 e que a primeira conexão sempre vai com `null`) e a do módulo `conversa.ts` se ainda disser algo sobre isso. README: a frase sobre cada carregamento ser uma conversa nova.

---

### Task 4: O loader avisa o iframe ao abrir e fechar

**Files:** Modify `frontend/public/widget.js`, `frontend/src/widget/widget.test.ts`.

- No clique que alterna o painel já criado, depois de trocar o `display`: `quadro.contentWindow.postMessage({ tipo: 'mobia:visibilidade', aberto: <novo estado> }, origem)` dentro de try/catch (D7 da TEC-344: nada escapa para o site). O painel recém-criado não manda aviso: o iframe começa assumindo aberto.
- `abrirPainel` precisa devolver (ou expor) o `quadro` para o clique alcançar a janela dele; mantenha a função legível.
- Testes: fechar → `postMessage` na `contentWindow` do iframe com `{tipo, aberto:false}` e a origem do script; abrir de novo → `aberto:true`; `postMessage` que lança não gera erro no site. Espie `quadro.contentWindow.postMessage` com `vi.spyOn`.
- `npm run verificar:widget` continua abaixo de 5120 bytes; anote o tamanho no relatório.
- Commit — `feat(TEC-347): o loader avisa o chat quando o painel abre e fecha`.

---

### Task 5: Verificação e entrega (controlador)

- `scripts/comentarios_tocados.py` e `--checar`; status da spec para `implementado` com notas datadas das divergências; suíte Python inteira (nada de Python muda, mas o merge com a `main` pode trazer algo); `npm run build`.
- Navegador (Edge): conversar, recarregar e ver as falas voltarem; encerrar e ver a conversa nova; minimizar e reabrir (o prazo de 30 min só pode ser verificado por teste — no navegador, confirmar ao menos que o aviso de visibilidade chega ao iframe e que reabrir depois de um sono forçado retoma).
- Push, PR, comentário na card, "Em análise".
