# TEC-332 — Plano: cadastrar, editar e desativar corretores

Desenho: `docs/superpowers/specs/2026-09-28-tec-332-corretores-design.md`. Só frontend — o backend (TEC-196) já existe.

## Passos

- [x] **`lib/servidor/bff.ts`**: quatro entradas em `ROTAS_PERMITIDAS` — `GET`/`POST api/v1/corretores`, `GET`/`PATCH api/v1/corretores/*` (D8). Os dois testes pré-existentes que usavam `corretores` como exemplo de rota fora da allowlist (`bff.test.ts`, `route.test.ts`) foram trocados para `imoveis`, que continua fora.
- [x] **`lib/corretores.ts`** (novo): `Corretor`, `Formulario`, constantes de especialidade (`COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `INVESTIMENTO_ALTO_TICKET`), `CAPACIDADE_MAXIMA = 20` (D3), `validarFormulario`/`formularioValido`, `pedidoDeCadastro` (POST completo, sem `gerente` — D4), `pedidoDeEdicao`/`estaSujo` (PATCH parcial), `recusaDe` (409 de e-mail → campo `email`, D9).
- [x] **`lib/servidor/corretores.ts`** (novo): `buscarCorretores` (`GET /api/v1/corretores`, sem `?ativos=` — D6), `ErroDeCorretores`, no molde de `lib/servidor/titular.ts`.
- [x] **`components/FormularioDeCorretor.tsx`** (novo): criar/editar no molde de `EdicaoDaQualificacao.tsx` — estado local, `sujo`/`registrarAlteracaoNaoSalva`, especialidades (checkbox múltiplo), regiões (uma por linha, adicionar/remover), horário início/fim, capacidade (1–20, client-side), plantão, `POST` na criação e `PATCH` parcial na edição via `/bff/api/v1/corretores[/*]`, 409 de e-mail duplicado como erro do campo.
- [x] **`components/DesativarCorretor.tsx`** (novo): confirmação citando "o histórico e os leads atribuídos são mantidos", `PATCH { ativo: false }` via `/bff/*`.
- [x] **`components/ListaDeCorretores.tsx`** (novo): a lista com rótulo de texto para inativo e para plantonista (D6), botão editar (abre `FormularioDeCorretor`) e desativar por linha só quando ativo.
- [x] **`app/(painel)/admin/corretores/page.tsx`** (novo): mesmo molde de `app/(painel)/admin/titular/page.tsx` — guarda `GERIR_CORRETORES`, `buscarCorretores` do servidor, 401 redireciona ao login, 403 vence a permissão lida (`SemPermissao`), vazio com `Vazio`, erro com `ErroDeCarga`.
- [x] **`app/(painel)/admin/page.tsx`**: `href: '/admin/corretores'` na seção "Corretores" (o teste de contagem de "ainda não disponível" caiu de 4 para 3).
- [x] **Testes**: `lib/corretores.test.ts` (29), `lib/servidor/corretores.test.ts` (4), `components/FormularioDeCorretor.test.tsx` (8), `components/DesativarCorretor.test.tsx` (5), `components/ListaDeCorretores.test.tsx` (5), `app/(painel)/admin/corretores/page.test.tsx` (8), mais casos em `lib/servidor/bff.test.ts` e `app/(painel)/admin/page.test.tsx`.
- [x] **Gates**: `npm test` (1073 verdes), `npm run lint` limpo, `tsc --noEmit` limpo, `npm run build` ok (rota `/admin/corretores` gerada). Rodados com o Node 24 do fnm -- o Node 20 do PATH quebra o jsdom (`webidl.util.markAsUncloneable is not a function`). Sem mudança de backend nesta card — gates do Python não re-executados.
- [x] **Navegador**: Edge headless por CDP, ADMIN (usuário criado ad-hoc na base de dev). Confirmado: cadastro válido aparece na lista; capacidade 21 não dispara `fetch` nenhum e mostra "Informe um número entre 1 e 20." com o formulário aberto; desativar mostra o texto exigido literal ("O histórico e os leads atribuídos são mantidos; o corretor deixa de receber novas alocações.") e a linha passa a "Inativo"; corretor de plantão aparece como "Generalista de plantão".
- [x] **Jira**: comentário com as divergências (D1–D5) e o link do PR; card movida para "Em análise".
