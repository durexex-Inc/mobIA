# TEC-313 — Estados padrão de tela — plano

Desenho: `docs/superpowers/specs/2026-09-24-tec-313-estados-padrao-de-tela-design.md`
Branch: `feat/tec-313-estados-padrao-de-tela`

## Task 1 — O vocabulário (`lib/estados.ts`)

- `EstadoDeDado`: `carregando | vazio | erro | sem_fonte | com_dados`.
- A função que decide, pura: `disponivel: false` → `sem_fonte`; nulo → `vazio`; **zero → `com_dados`**.
- Testes primeiro, porque é aqui que mora a regra que a card existe para proteger.

## Task 2 — As peças (`components/estado/`)

- `AindaNaoMedido` — texto + motivo por `title` e `aria-describedby` (D4).
- `ErroDeCarga` — mensagem genérica, `request_id` copiável quando houver, link "tentar de novo" (D3, D6).
- `Vazio` e `Skeleton`.

## Task 3 — O skeleton atrasado (D2)

- `app/loading.tsx` com o skeleton do painel.
- A animação de 300 ms e o `.visually-hidden` em `globals.css`.

## Task 4 — O erro carrega o que a tela precisa (`lib/metricas.ts`)

- `ErroDeMetricas` ganha `requestId: string | null` (do header da resposta) e `campos: string[]`.
- `detalheDe` passa a devolver campos estruturados além da prosa.

## Task 5 — Adoção

- `formato.ts` e `Indicadores.tsx`: "Ainda não medido" (D1).
- `Filtros.tsx`: 422 ao lado do campo, com fallback acima do formulário (D5).
- `page.tsx`: `ErroDeCarga` no lugar do aviso atual.

## Task 6 — Gates

```bash
cd frontend
npm run lint && npm test && npm run build && npm run verificar:bundle
```

Sob **Node 24** (`.nvmrc`) — com Node 20 nenhum teste roda. Mais `tsc --noEmit`, os gates da raiz (a branch toca `docs/`) e `scripts/comentarios_tocados.py --checar`.

Verificar no app de pé que o skeleton não pisca em carga rápida — é o que teste de unidade não pega (D2).
