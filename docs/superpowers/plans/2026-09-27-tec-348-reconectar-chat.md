# TEC-348 — Plano: reconectar o chat e reenviar as pendentes

Desenho: `docs/superpowers/specs/2026-09-27-tec-348-reconectar-chat-design.md`. Só frontend: o servidor já deduplica por `id` e fecha com `1011` quando está indisponível.

## Passos

- [x] **Redutor** (`frontend/src/lib/conversa.ts`): `esperaDaTentativa`; estados `reconectando` e `offline`; `fechou` com `codigo` e `agora`, e a tabela da D2; evento `desistiu`; o `historico` confirma a pendente que já traz (D5).
- [x] **Testes do redutor**: a tabela da card para a espera; cada linha da D2; `tentativa` e `desde`; `instavel`; `desistiu`; os casos da D5. Os testes antigos de `fechou` passam a dizer o código.
- [x] **Componente** (`frontend/src/components/Conversa.tsx`): o `open` manda toda `enviando`; o prazo do `ack` só com a mensagem no fio e todo `close` o cancela; timer da tentativa e timer dos 5 min; `transmitir` não fura a reconexão; "Tentar de novo"; a linha de estado acima do campo; a queda não dorme.
- [x] **Testes do componente**: os quatro cenários do Gherkin com relógio falso; o `1002` manual; o prazo do `ack` parado na queda; a pendente confirmada pelo `historico`; encerrar durante a queda. Os testes do caminho manual passam a fechar com `1002`.
- [x] **CSS** da linha de estado (`frontend/src/app/globals.css`).
- [x] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: Edge headless por CDP — API parada, Redis parado (`1011`), 5 min sem API.
- [x] **Prosa**: notas nos desenhos da TEC-346, TEC-347 e TEC-366; o parágrafo do README do frontend.
