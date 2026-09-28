# TEC-334 — Plano: importar imóveis em lote por CSV e ver as linhas rejeitadas

Desenho: `docs/superpowers/specs/2026-09-28-tec-334-importacao-de-imoveis-design.md`. Só frontend — o backend (TEC-156/TEC-157/TEC-197) já existe. Estende a tela `/admin/imoveis` da TEC-333.

## Passos

- [ ] **`lib/servidor/bff.ts`**: duas entradas em `ROTAS_PERMITIDAS` — `POST api/v1/imoveis/importar`, `GET api/v1/imoveis/importacoes/*` (D6).
- [ ] **`lib/csv.ts`** (novo): parser de prévia só do cliente — delimitador `;`/`,` pelo cabeçalho, BOM opcional, sem suporte a campo multi-linha (D1); `linhasParaCsv` para gerar o CSV de download das rejeições (D5), com escape RFC 4180 mínimo.
- [ ] **`lib/importacaoDeImoveis.ts`** (novo): tipos (`Importacao`, `Erro`), `TETO_DE_UPLOAD_EM_BYTES = 10 * 1024 * 1024` (D2, mesmo valor de `api/routes/imoveis.py`), `INTERVALO_DE_POLLING_MS = 3000` (D3).
- [ ] **`lib/servidor/importacaoDeImoveis.ts`** (novo): `buscarImportacaoMaisRecente` (`GET /api/v1/imoveis/importacoes?limite=1`, D4), `ErroDeImportacao`.
- [ ] **`components/ImportarImoveis.tsx`** (novo): seleção de arquivo, checagem de 10 MB na seleção (D2), prévia de 10 linhas (D1), confirmar dispara `POST /bff/api/v1/imoveis/importar` com `FormData`.
- [ ] **`components/AcompanharImportacao.tsx`** (novo): mostra o relatório atual e faz polling enquanto `PROCESSANDO` (D3), lista as linhas rejeitadas com número e motivo, botão "Baixar rejeições" que monta o Blob (D5).
- [ ] **`app/(painel)/admin/imoveis/page.tsx`**: busca a importação mais recente do servidor (D4) e monta `ImportarImoveis`/`AcompanharImportacao` ao lado da lista de imóveis já existente (TEC-333) — mesma guarda `GERIR_CATALOGO`, sem uma segunda página.
- [ ] **Testes**: `lib/csv.test.ts`, `lib/importacaoDeImoveis.test.ts`, `lib/servidor/importacaoDeImoveis.test.ts`, `components/ImportarImoveis.test.tsx`, `components/AcompanharImportacao.test.tsx`, mais casos em `app/(painel)/admin/imoveis/page.test.tsx` e `lib/servidor/bff.test.ts`.
- [ ] **Gates**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`. Sem mudança de backend nesta card.
- [ ] **Navegador**: Edge headless por CDP, ADMIN — selecionar um CSV pequeno e ver a prévia de 10 linhas; selecionar um arquivo > 10 MB e ver a recusa; confirmar o envio e ver "Processando" até concluir; conferir as linhas rejeitadas (se o CSV de teste tiver alguma) e baixar o CSV delas.
- [ ] **Jira**: comentar as decisões (parser de prévia sem paridade total com o backend, D1; polling de 3s sem pausa de aba, D3) e o link do PR; mover para "Em análise".
