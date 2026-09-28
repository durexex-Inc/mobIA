# TEC-316 — Plano: filtros do funil na URL, corretor desabilitado

Desenho: `docs/superpowers/specs/2026-09-28-tec-316-filtros-do-funil-na-url-design.md`. A maior parte já existia (TEC-190); esta card fecha três lacunas.

## Passos

- [x] **`lib/periodo.ts`**: `periodoPadrao` de `-29` para `-30` dias, batendo com o exemplo do Gherkin desta card; atualizado `periodo.test.ts`.
- [x] **`domain/metricas/filtros.py`**: `_mais_um_ano` e a checagem de 12 meses em `montar_recorte`, recusando com `FiltroInvalido("ate", ...)`.
- [x] **`components/Filtros.tsx`**: campo Corretor vira `<select disabled>` com "Disponível após a alocação de corretor.", no molde de `FiltrosDeLeads` (TEC-322, D5).
- [x] **`app/(painel)/page.tsx`**: `filtrosDaUrl` parou de ler `corretorId` da URL.
- [x] **Testes**: `test_filtros_do_funil.py` (12 meses, unitário) e `test_rota_de_metricas.py` (12 meses, integração); `periodo.test.ts` (datas corrigidas); `Filtros.test.tsx` (campo desabilitado; ajuste dos testes de 422 — `corretorId` saiu, `ate` entrou como exemplo isolado, com o comentário corrigido sobre onde o erro real aparece); `page.test.tsx` confirmando que `corretorId` na URL não é enviado ao backend.
- [x] **Gates**: os três do Python (+ suíte completa do backend, 6162 passed, 9 falhas pré-existentes não relacionadas — `[WinError 64]` sob carga), `npm test` (963 verdes), `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: funil real com o período padrão novo (`2026-08-29` a `2026-09-28`); campo Corretor desabilitado; o exemplo exato do Gherkin (13+ meses) recusado com o limite citado; link com quatro filtros reproduzindo a visão; `?corretorId=` na URL ignorado sem erro.
- [x] **Prosa**: comentário na Jira sobre a correção do período padrão (muda comportamento já em produção) e sobre a TEC-166 não desbloquear nada; correção do próprio desenho sobre onde a mensagem de 12 meses aparece (achado durante a verificação no navegador).
