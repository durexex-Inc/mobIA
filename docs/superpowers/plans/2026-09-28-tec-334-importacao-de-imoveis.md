# TEC-334 — Plano: importar imóveis em lote por CSV e ver as linhas rejeitadas

Desenho: `docs/superpowers/specs/2026-09-28-tec-334-importacao-de-imoveis-design.md`. Só frontend — o backend (TEC-156/TEC-157/TEC-197) já existe. Estende a tela `/admin/imoveis` da TEC-333.

## Passos

- [x] **`lib/servidor/bff.ts`**: duas entradas em `ROTAS_PERMITIDAS` — `POST api/v1/imoveis/importar`, `GET api/v1/imoveis/importacoes/*` (D6). Casos novos em `lib/servidor/bff.test.ts` (rota certa, método errado, `importacoes` sem id).
- [x] **`lib/csv.ts`** (novo): parser de prévia só do cliente — delimitador `;`/`,` pelo cabeçalho, BOM opcional, campo entre aspas numa única linha tratado, sem suporte a campo multi-linha (D1); `linhasParaCsv` para gerar o CSV de download das rejeições (D5), com escape RFC 4180 mínimo.
- [x] **`lib/importacaoDeImoveis.ts`** (novo): tipos (`Importacao`, `Erro`, `StatusDaImportacao`), `TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024` (D2, mesmo valor de `api/routes/imoveis.py`), `INTERVALO_DE_POLLING_MS = 3000` (D3).
- [x] **`lib/servidor/importacaoDeImoveis.ts`** (novo): `buscarImportacaoMaisRecente` (`GET /api/v1/imoveis/importacoes?limite=1`, D4), `ErroDeImportacao`.
- [x] **`components/ImportarImoveis.tsx`** (novo): seleção de arquivo, checagem de 10 MB na seleção (D2), prévia de 10 linhas (D1), confirmar dispara `POST /bff/api/v1/imoveis/importar` com `FormData`. Guarda tambem `importacaoAtual`, seedado por `importacaoInicial` (D4) -- nao precisou de um wrapper `'use client'` a mais.
- [x] **`components/AcompanharImportacao.tsx`** (novo): mostra o relatório atual e faz polling enquanto `PROCESSANDO` (D3), lista as linhas rejeitadas com número e motivo, botão "Baixar rejeições" que monta o Blob (D5).
- [x] **`app/(painel)/admin/imoveis/page.tsx`**: busca a importação mais recente do servidor (D4) e monta `ImportarImoveis`/`AcompanharImportacao` ao lado da lista de imóveis já existente (TEC-333) — mesma guarda `GERIR_CATALOGO`, sem uma segunda página. Falha ao buscar a importacao mais recente nao derruba a pagina (engolida, ao contrario de `buscarImoveis`).
- [x] **Testes**: `lib/csv.test.ts`, `lib/importacaoDeImoveis.test.ts`, `lib/servidor/importacaoDeImoveis.test.ts`, `components/ImportarImoveis.test.tsx`, `components/AcompanharImportacao.test.tsx` (com `vi.useFakeTimers()`), mais casos em `app/(painel)/admin/imoveis/page.test.tsx` e `lib/servidor/bff.test.ts`.
- [x] **Gates**: `npm test` -- 87 arquivos, 1178 testes, 0 falhas. `npm run lint` limpo. `npx tsc --noEmit` limpo. `npm run build` -- compilou, 18 rotas geradas. Node 24.21.0 via fnm. Sem mudança de backend nesta card.
- [x] **Navegador**: Edge headless por CDP, ADMIN (usuario ad-hoc com MFA). CSV de 5 linhas (4 validas, 1 com `tipo` invalido): previa mostrou 16 colunas x 5 linhas. Arquivo de 11 MB: recusa imediata "O arquivo passa de 10 MB; use a CLI de seed.", sem previa nem POST. Confirmar mostrou "Processando…" e, apos o worker ARQ concluir, "Concluído" com Processados 5 / Inseridos 4 / Rejeitados 1. Tabela de rejeicoes mostrou "Linha 6: tipo invalido: 'PALACIO'"; "Baixar rejeições" gerou `linha,motivo` / `6,tipo invalido: 'PALACIO'`.
- [x] **Jira**: comentar as decisões (parser de prévia sem paridade total com o backend, D1; polling de 3s sem pausa de aba, D3) e o link do PR; mover para "Em análise".
