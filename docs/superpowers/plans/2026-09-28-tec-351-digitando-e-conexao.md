# TEC-351 — Plano: indicador de digitação e estado da conexão

Desenho: `docs/superpowers/specs/2026-09-28-tec-351-digitando-e-conexao-design.md`. Só frontend: o frame `digitando` já existe (TEC-362).

## Passos

- [x] **Redutor** (`frontend/src/lib/conversa.ts`): `digitando` na `Conversa`; o frame liga, com o `ate` lido ou nulo; `mensagem`, `imovel`, `imagem`, `fechou` e `encerrou` apagam; `digitacaoVenceu` apaga só o indicador daquele frame. Os testes antigos que afirmavam o frame ignorado e o `INICIAL` sem o campo mudam.
- [x] **Cabeçalho** (`CabecalhoDoChat`): `conexao` opcional, texto e ponto `aria-hidden`, `role="status"`. Testes dos quatro textos.
- [x] **Componente** (`Conversa`): a tabela da D3; o prazo do indicador (o `ate` dentro de 30 s, senão 30 s); a linha do indicador fora do `log`; a linha da TEC-348 só com a frase de instável e o "Tentar de novo". Testes com relógio falso, e o teste da TEC-348 que procurava "Sem conexão." passa a olhar o cabeçalho.
- [x] **CSS** do estado e do indicador.
- [x] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: Edge headless por CDP, `digitando` publicado no Redis, API parada.
- [x] **Prosa**: nota na D6 da TEC-348; os parágrafos do README do frontend.
