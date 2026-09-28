# TEC-317 — Atualizar o funil a cada 30 segundos com a aba visível

**Card:** [TEC-317](https://eduardodurieuxlopes.atlassian.net/browse/TEC-317) — épico TEC-303
**Branch:** `feat/tec-317-atualizacao-automatica-do-funil`
**Relaciona-se a:** TEC-316 (filtros do funil na URL), TEC-190 (funil e o Data Cache de 60 s)

## O que já existe quando a card começa

- O funil (`app/(painel)/page.tsx`) é um server component puro: `filtrosDaUrl` lê os filtros da URL, `buscarFunil` (`lib/metricas.ts`) chama o FastAPI com `next: { revalidate: 60 }`, e a página renderiza o resultado. **Não há nenhum polling client-side hoje** — a única forma de ver dados novos é recarregar a página, e o teto de defasagem de 60 s (RN-17.3) é satisfeito só por isso.
- O único componente de cliente com timer no painel é `AvisoDeInatividade.tsx`: um `setInterval(verificar, 1000)` que compara horários (não conta em segundos brutos), porque uma aba que o navegador põe para dormir acorda sabendo quanto tempo passou de verdade. É o padrão a seguir aqui.
- O backend (`GET /api/v1/metricas/funil`) não tem cache nenhum — cada chamada lê o banco ao vivo (`srs-agente-sdr-imobiliario-v1.0.md` linha 1486, p95 de 0,068 s). O teto de 60 s é inteiramente uma decisão do frontend, e o polling desta card é a mesma decisão com outro número.
- O Data Cache do Next casa por URL, método, **cabeçalhos** e corpo — o `Authorization: Bearer` do usuário logado entra na chave (TEC-309, D7). Duas abas da mesma pessoa dividem a mesma entrada de cache; pessoas diferentes, não.

## D1 — Polling é `router.refresh()`, não um novo fetch client-side

Um componente de cliente não pode chamar `buscarFunil` diretamente: o módulo importa `server-only` de propósito (TEC-302), e replicar a chamada no cliente exporia o access token no navegador. A única forma de pedir dados novos ao servidor sem recarregar a página inteira é `router.refresh()` (`next/navigation`) — ele reexecuta o server component com os **mesmos** `searchParams`, e como os filtros SÃO a URL (D da TEC-190/TEC-316), eles chegam intactos: nada a fazer para "não perder o filtro por canal web" do cenário 1 do Gherkin, é consequência da arquitetura já escolhida.

## D2 — O intervalo do Data Cache desce de 60 s para 30 s, e é isso que segura a carga

A RN diz "polling a cada 30 s" e "30 usuários geram no máximo 1 req/s ao endpoint". Sem mexer no cache, cada `router.refresh()` bateria direto no FastAPI a cada 30 s por aba — e duas abas da mesma pessoa, ou um clique em "tentar de novo" em cima do intervalo, dobrariam a conta. Baixando `revalidarEmSegundos` de `buscarFunil` de 60 para 30, o Data Cache volta a fazer o que já fazia na TEC-309 (D7), só que com o número novo: a entrada por usuário dura 30 s, então `router.refresh()` chamado por qualquer aba daquela pessoa dentro da janela é um cache hit, e só uma chamada por pessoa a cada 30 s alcança o backend. Com 30 gerentes de painel aberto, são no máximo 30 requisições a cada 30 s — exatamente 1 req/s, o teto do cenário 3.

O comentário de `buscarFunil` que explica essa matemática (TEC-309, D7) muda de "uma por minuto" para "uma a cada 30 s" — ele descreve a decisão de hoje, e ficaria mentindo se só o número mudasse.

## D3 — O relógio de reagendamento é próprio, não o `atualizadoEm` do servidor

O componente de cliente (`AtualizacaoAutomatica.tsx`) recebe `atualizadoEm: string` — um `ISOString` que a `Pagina` grava no instante em que `buscarFunil` retorna com sucesso — e usa isso para exibir "Atualizado há N s". Mas o relógio que decide **quando chamar `router.refresh()` de novo** é outro: um `useRef` próprio, atualizado a cada tentativa, independente de a prop ter mudado.

A razão é falha silenciosa. Se o agendamento dependesse de `atualizadoEm` mudar para se rearmar (um `useEffect` com `[atualizadoEm]` nas deps, que dispara e espera a próxima renderização para resetar uma flag), um `router.refresh()` que falhe sem re-renderizar a página — rede instável, aba que o SO suspendeu — trava o polling para sempre: a prop nunca muda, o efeito nunca reagenda. Com o relógio próprio, a tentativa seguinte acontece 30 s depois de qualquer jeito, sucesso ou não — o pior caso é uma tentativa perdida, nunca um polling morto.

## D4 — Pausa com a aba oculta, sem zerar o relógio

`talvezAtualizar` roda a cada segundo (`setInterval`) e também em todo `visibilitychange`. Ele sai cedo, sem tocar em nada, quando `document.visibilityState !== 'visible'` — nem chama `router.refresh()`, nem atualiza o texto exibido. É o que faz o cenário 2 do Gherkin ("nenhuma nova consulta foi feita" em 2 minutos ocultos) valer: a aba oculta simplesmente não avalia a condição de refresh.

Ao voltar a ficar visível, o listener de `visibilitychange` dispara `talvezAtualizar` na hora — sem esperar o próximo segundo cheio —, e como o relógio (D3) nunca foi zerado enquanto oculta, `agora - ultimaTentativa` já passa de 30 000 ms depois de qualquer ausência de 30 s ou mais: a atualização acontece imediatamente ao reabrir a aba, uma vez só (o relógio é zerado nesse instante), não em rajada.

## D5 — Hidratação começa em "0 s", não em `Date.now() - atualizadoEm`

O servidor renderiza o texto no mesmo instante em que grava `atualizadoEm`, então a primeira renderização é sempre "Atualizado há 0 s". Se o componente calculasse `segundos` direto de `Date.now()` no corpo da função, o cliente hidrataria alguns milissegundos depois e correria o risco de arredondar para "1 s" — um `<p>` cujo texto diverge entre servidor e cliente, que o React acusa. `segundos` começa como `useState(0)` (igual nos dois lados) e só passa a refletir o tempo real dentro do `useEffect`, que roda exclusivamente no cliente.

## D6 — O componente só existe quando o funil aparece

`<AtualizacaoAutomatica>` fica dentro do mesmo bloco condicional que `<Funil>` e `<Indicadores>` (`{funil ? (...) : null}`), não fora dele. Isso significa que, se `buscarFunil` falhar, o polling **para** — não tenta se recuperar sozinho enquanto o backend estiver fora. É a mesma escolha que o resto da página já faz (TEC-313, TEC-321): um erro não vira dado, e a recuperação é o "tentar de novo" explícito do `ErroDeCarga`, não um retry invisível. Adicionar um retry automático aqui divergiria desse padrão sem que a card peça — o Gherkin não tem cenário de recuperação de erro.

## Fora do escopo desta história

Tempo real por SSE/WebSocket (Won't, já escrito na card) — o `GET /api/v1/eventos/stream` existe para o chat (TEC-350/351), não para este painel.

## Testes

- **`lib/metricas.test.ts`**: as duas asserções de `revalidate: 60` passam a `30`.
- **`components/AtualizacaoAutomatica.test.tsx`** (novo, com `vi.useFakeTimers`): não chama `refresh` antes de 30 s; chama exatamente uma vez aos 30 s, com a aba visível; nenhuma chamada em 2 minutos com `document.visibilityState = 'hidden'`; ao voltar a ficar visível depois de ficar oculta por mais de 30 s, chama `refresh` uma única vez (não em rajada); o texto exibido soma segundos corretamente entre atualizações.
- **`app/(painel)/page.test.tsx`**: o mock de `next/navigation` ganha `useRouter`; um teste novo confirma que "Atualizado há" aparece quando o funil carrega e não aparece na tela de erro.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais, sessão GERENTE sem MFA.

| passo | resultado |
| --- | --- |
| Funil aberto, aba visível, log do backend amostrado a cada 10s por ~80s | contagem sobe exatamente em `t≈30s` e `t≈61s` — o resto das amostras (10s, 20s, 40s, 50s, 71s) não muda, confirmando o intervalo de 30s e que a janela seguinte cai dentro do cache |
| `document.visibilityState` forçado para `'hidden'` por 80s (amostrado a cada 10s) | contagem não muda nenhuma vez — zero chamadas ao funil com a aba oculta |
| `visibilityState` de volta a `'visible'` | uma chamada nova ao funil imediatamente (sem esperar o próximo segundo cheio); mais 5s depois, a contagem não mudou de novo — não é rajada |
| `/?canal=web`, aguardando o ciclo de refresh seguinte | a chamada do ciclo seguinte ainda traz `canal=web` — o filtro sobrevive ao `router.refresh()` |

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Atualizar sem perder os filtros | `router.refresh()` reexecuta com os mesmos `searchParams` (D1); confirmado no navegador com filtro por canal aplicado |
| Pausar com a aba oculta | `AtualizacaoAutomatica.test.tsx` (D4) |
| Carga controlada (1 req/s para 30 usuários) | `revalidarEmSegundos: 30` dedupa por `Authorization` (D2) — não há teste automatizado de carga com 30 sessões reais; a garantia é a mesma matemática que já sustentava o teto anterior (TEC-309, D7), com o número novo |

## Lacunas declaradas

- **L1 — Sem teste de carga real com 30 sessões simultâneas.** O cenário 3 do Gherkin é satisfeito por construção (o Data Cache dedupa por usuário, e o número de usuários não muda essa propriedade), não por uma medição direta como a da TEC-190/RNF-04. Fica igual à garantia que já existia para o teto de 60 s.
- **L2 — O SRS do frontend não está no repo.** RN-FE-05.4 e RNF-FE-07 vêm do texto da card, como já registrado na L2 da TEC-316.
