# TEC-326 — Regenerar o resumo inteligente com trava de 60 segundos

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-326](https://eduardodurieuxlopes.atlassian.net/browse/TEC-326) — épico TEC-304
**Branch:** `feat/tec-326-regenerar-resumo`
**Depende de:** TEC-175 e TEC-193 (a rota e a trava), TEC-323 (a seção Resumo), TEC-302 (o `/bff/*`)

## O que existe quando a card começa

`POST /api/v1/handoffs/{handoffId}/resumo` existe desde a TEC-175, com a trava de 60 s desde a TEC-193 (D6, escrita para esta card). Funciona assim:

- exige `ATENDER_LEAD`, e o CORRETOR só alcança o próprio handoff;
- **é síncrono**: chama o modelo e responde com o resumo novo `{resumo, geradoEm, modelo, resumoFallback, link}`, ou com o de contingência da TEC-176 se o modelo falhar;
- grava `DADO_PESSOAL_ACESSADO` com `campo=resumo`;
- menos de 60 s desde `resumo_gerado_em` é **429 com `Retry-After`**, antes de chamar o modelo. A geração automática do handoff também conta.

O detalhe devolve `resumo.handoffId` "pelo qual a tela regenera". **A card é só de frontend.**

## D1 — O botão fica na seção Resumo, para quem tem `ATENDER_LEAD`

Ele aparece só quando há resumo, ou seja, quando há handoff para regenerar. Lead sem resumo continua com o estado vazio da TEC-323. O CORRETOR só abre o detalhe do próprio lead, e é o dono do handoff dele.

## D2 — O novo resumo substitui o anterior pela resposta, sem reler o detalhe

`components/ResumoRegeneravel.tsx`, de cliente, desenha o resumo e guarda-o em estado. Com o 200, **o texto novo entra no lugar do antigo a partir da resposta**, com o mesmo corte em seis blocos (`dividirResumo`) e o mesmo rótulo de contingência. Reler o detalhe com `router.refresh()` gravaria mais um `DADO_PESSOAL_ACESSADO` (`campo=detalhe`) para mostrar um texto que já veio na resposta.

**Durante a geração** o resumo anterior continua visível, com `aria-busy`, e a seção diz "Gerando novo resumo…" (`role="status"`). É o "a tela mostra que o resumo está sendo gerado" do primeiro cenário. O botão fica desabilitado.

## D3 — A trava de 60 s conta de `geradoEm`, como a do backend

O botão fica desabilitado até `geradoEm + 60 s`, com a contagem "Disponível em N s", atualizada a cada segundo. A conta é a mesma do backend (`resumo_gerado_em`), então:

- depois de regenerar, o `geradoEm` novo reinicia a trava;
- abrir o detalhe logo depois da geração automática do handoff já mostra a trava;
- o segundo cenário da card, "pediu há 20 s, fica indisponível pelos próximos 40", é a conta.

**O 429 não vira erro genérico.** A tela lê o `Retry-After` e diz "O resumo foi gerado há menos de um minuto. Disponível em N s.". Isso acontece quando o relógio do navegador está adiantado em relação ao servidor, ou quando outra aba regenerou.

## D4 — Recusas

| resposta | a tela diz |
| --- | --- |
| 429 | a trava, com o `Retry-After` (D3) |
| 401 | Sua sessão terminou. Recarregue a página para entrar de novo. |
| 403 / 404 | Não foi possível regenerar este resumo. |
| rede / 5xx | Não foi possível gerar o novo resumo. Tente de novo. |

Em todas, o resumo anterior fica.

## D5 — O proxy libera a rota

`ROTAS_PERMITIDAS` ganha `POST api/v1/handoffs/*/resumo`. A regra de `Origin` recusa mutação de outra origem, e o dono é conferido pelo FastAPI.

**E o proxy passa a repassar `Retry-After`.** Até aqui ele repassava só o `Content-Type`, por lista, para não vazar `Set-Cookie` ou o que o FastAPI mandasse um dia. A verificação ponta a ponta mostrou o 429 chegando sem o cabeçalho, e a tela teria de supor os 60 s cheios. `Retry-After` entra na lista; o resto continua de fora.

## Fora do escopo

- **Geração assíncrona com aviso quando pronto.** A rota é síncrona. A espera é a do modelo, e o botão fica desabilitado nela.
