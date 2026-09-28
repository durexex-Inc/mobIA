# TEC-315 — Plano: coorte incompleta e "Ainda não medido" no funil

Desenho: `docs/superpowers/specs/2026-09-28-tec-315-coorte-incompleta-design.md`. Descoberta importante: os dois cenários centrais do Gherkin não são mais reproduzíveis com dado real (TEC-367 + TEC-376 já resolveram os defeitos na raiz) — a implementação é defensiva, na fronteira da API.

## Passos

- [x] **`lib/formato.ts`**: `coorteIncompleta(valor)`; atualizado o comentário de `quantidadeLegivel` (não mais "continua sendo da TEC-315" — passou a ser aqui).
- [x] **`components/Funil.tsx`**: `conversaoConfiavel(etapa, anterior)` — suprime a conversão se a etapa atual ou a anterior estiver `disponivel: false`, independente do que o backend mandou; o aviso "Coorte incompleta" (ícone decorativo + texto visível + explicação por `title`/`aria-describedby`/`visually-hidden`, molde de `AindaNaoMedido`).
- [x] **Testes**: `formato.test.ts` (`coorteIncompleta`); `Funil.test.tsx` (conversão > 100% com aviso; conversão normal sem aviso; etapa sem fonte não propaga conversão mesmo que o backend mande um número ali).
- [x] **Gates**: os três do Python, `npm test` (961 verdes), `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: confirmado que a tela real do funil continua idêntica — `Agendado` disponível, nenhum "Coorte incompleta".
- [x] **Prosa**: comentário na Jira explicando a descoberta (TEC-367/TEC-376 resolveram a raiz).
- [x] **Correção incidental**: âncora quebrada em `docs/superpowers/specs/2026-09-28-tec-343-trilha-de-auditoria-design.md` (`autorizacao.py::como_ator` → `autorizacao.py::IdentidadeDaRequisicao.como_ator`), achada pelo gate de prosa ao rodar `comentarios_tocados.py --checar`.
