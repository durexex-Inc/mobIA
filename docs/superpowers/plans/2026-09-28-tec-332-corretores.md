# TEC-332 — Plano: cadastrar, editar e desativar corretores

Desenho: `docs/superpowers/specs/2026-09-28-tec-332-corretores-design.md`. Só frontend — o backend (TEC-196) já existe.

## Passos

- [ ] **`lib/servidor/bff.ts`**: quatro entradas em `ROTAS_PERMITIDAS` — `GET`/`POST api/v1/corretores`, `GET`/`PATCH api/v1/corretores/*` (D8).
- [ ] **`lib/corretores.ts`** (novo): tipos (`Corretor`, `CorretorNovo`/pedido de criação, `CorretorEditado`/pedido de edição parcial), constantes de especialidade (`COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `INVESTIMENTO_ALTO_TICKET` — mesma grafia do backend), `CAPACIDADE_MAXIMA = 20` (D3), validação de formulário e montagem do corpo do `POST`/`PATCH`.
- [ ] **`lib/servidor/corretores.ts`** (novo): `buscarCorretores` (`GET /api/v1/corretores`, sem `?ativos=` — D6), `ErroDeCorretores`, no molde de `lib/servidor/titular.ts`.
- [ ] **`components/FormularioDeCorretor.tsx`** (novo): criar/editar no molde de `EdicaoDaQualificacao.tsx` — estado local, `sujo`/`registrarAlteracaoNaoSalva`, especialidades (checkbox múltiplo), regiões (uma por linha, adicionar/remover), horário início/fim, capacidade (1–20, client-side), plantão, `POST` na criação e `PATCH` parcial na edição via `/bff/api/v1/corretores[/*]`, 409 de e-mail duplicado como erro do campo.
- [ ] **`components/DesativarCorretor.tsx`** (novo): confirmação citando "o histórico e os leads atribuídos são mantidos", `PATCH { ativo: false }` via `/bff/*`.
- [ ] **`components/ListaDeCorretores.tsx`** (novo): a lista com rótulo de texto para inativo e para plantonista (D6), botão editar (abre `FormularioDeCorretor`) e desativar por linha só quando ativo.
- [ ] **`app/(painel)/admin/corretores/page.tsx`** (novo): mesmo molde de `app/(painel)/admin/titular/page.tsx` — guarda `GERIR_CORRETORES`, `buscarCorretores` do servidor, 401 redireciona ao login, 403 vence a permissão lida (`SemPermissao`), vazio com `Vazio`, erro com `ErroDeCarga`.
- [ ] **`app/(painel)/admin/page.tsx`**: `href: '/admin/corretores'` na seção "Corretores".
- [ ] **Testes**: `lib/corretores.test.ts`, `lib/servidor/corretores.test.ts`, `components/FormularioDeCorretor.test.tsx`, `components/DesativarCorretor.test.tsx`, `components/ListaDeCorretores.test.tsx`, `app/(painel)/admin/corretores/page.test.tsx`, mais casos em `lib/servidor/bff.test.ts` e `app/(painel)/admin/page.test.tsx`.
- [ ] **Gates**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`. Sem mudança de backend nesta card — gates do Python não re-executados.
- [ ] **Navegador**: Edge headless por CDP, ADMIN — cadastrar corretor válido, capacidade 21 recusada na tela, desativar com confirmação, lista mostrando inativo e plantonista com texto.
- [ ] **Jira**: comentar as três divergências (D1, D2, D3) e a lacuna do teto de 20 só no cliente; mover para "Em análise".
