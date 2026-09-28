# TEC-349 — plano de implementação

Desenho: `docs/superpowers/specs/2026-09-27-tec-349-cards-de-imovel-no-chat-design.md`.

1. `frontend/src/lib/imovel.ts`, com o parser, os formatadores e os testes.
2. `frontend/src/lib/conversa.ts`: o caso `imoveis` de `Mensagem`, o agrupamento em `aplicarImovel` e o `historico`, com os testes.
3. `frontend/src/components/CardDeImovel.tsx` e o CSS em `globals.css`, com os testes dos quatro cenários.
4. `Conversa.tsx` desenhando a fileira, com o teste de ponta a ponta pelo socket.
5. O README do frontend, e os gates do CI do frontend: lint, testes, loader, build e varredura do bundle.
