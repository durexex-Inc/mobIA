# TEC-318 — Plano: abrir a lista de leads a partir de uma etapa do funil

Desenho: `docs/superpowers/specs/2026-09-28-tec-318-abrir-leads-da-etapa-design.md`.

## Passos

- [x] **`domain/metricas/repositorio.py`**: extrair `_condicoes_das_etapas(coorte)`; `contar_etapas` passa a usá-la; novas `selecionar_coorte(recorte)` e `selecionar_etapa(recorte, etapa)` (D1).
- [x] **`domain/leads/repositorio.py`**: `_consulta`/`listar_leads` ganham `coorte_do_funil: Any` (`Select` resolvido), com `.exists()` quando presente.
- [x] **`api/routes/leads.py`**: novos query params `de`, `ate`, `intencao`, `etapa`; validação via `montar_recorte` (D2); 422 se `etapa`/`intencao` vierem sem `de`+`ate`, ou `etapa` fora do vocabulário.
- [x] **`components/Funil.tsx`**: prop `filtros: Filtros`; `urlDaEtapa`; etapa disponível vira `<a className="funil-etapa-link">` com `display: contents` (D4); etapa indisponível continua sem link.
- [x] **`app/globals.css`**: `.funil-etapa-link`, `.leads-origem-do-funil`.
- [x] **`app/(painel)/page.tsx`**: passa `filtros` para `<Funil>`.
- [x] **`lib/leads.ts`**: `OrigemDoFunil`, `origemDoFunilDaUrl`; `urlDaLista` inclui os quatro campos quando presentes (D6).
- [x] **`lib/servidor/leads.ts`**: `buscarLeads`/`buscarPaginas` mandam `de`/`ate`/`intencao`/`etapa` ao FastAPI quando houver `origemDoFunil`.
- [x] **`components/TabelaDeLeads.tsx`**: `CabecalhoOrdenavel` ganha `origemDoFunil` e repassa a `urlDaLista`.
- [x] **`app/(painel)/leads/page.tsx`**: lê `origemDoFunil` da URL; thread até `buscarPaginas`, `PaginacaoDeLeads`, `TabelaDeLeads`; aviso "Etapa: X — período" com link para `/leads` limpo.
- [x] **Testes**: integração de `selecionar_etapa`/`selecionar_coorte`/`contar_etapas` (regressão, `test_repositorio_de_metricas.py`); integração de `test_lista_de_leads.py` (etapa filtra, 422 sem período, 422 etapa desconhecida, canal dentro da etapa); `Funil.test.tsx`; `lib/leads.test.ts`; `leads/page.test.tsx`.
- [x] **Gates**: os três do Python (ruff check, ruff format, mypy) + suíte completa (`-n 8 --dist loadfile`, 6181 passed, 2 failed + 1 error pré-existentes e não relacionados — confirmados flaky isolados); `npm test` (980 verdes), `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: Edge headless por CDP, GERENTE, dados semeados em Novo/Em conversa/Qualificado. Confirmado: cada etapa disponível (inclusive com quantidade zero) tem `href` para `/leads?de=...&ate=...&etapa=...`; abrir o link mostra só os leads daquela etapa (3 de 3, batendo com a contagem do funil) e o aviso "Etapa do funil: Qualificado — período de 2026-09-01 a 2026-09-30 · Ver todos os leads"; os cabeçalhos de ordenação preservam `de`/`ate`/`etapa`.
- [x] **Jira**: comentário na card com o achado sobre `[CONFIRMAR]`, o que foi implementado e a lacuna L1; mover para "Em análise".
