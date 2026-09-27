# TEC-322 — Filtrar e paginar a lista de leads, com cartões no celular

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-322](https://eduardodurieuxlopes.atlassian.net/browse/TEC-322) — épico TEC-304
**Branch:** `feat/tec-322-filtrar-e-paginar`
**Depende de:** TEC-321 (a lista base), TEC-192 (`GET /api/v1/leads`)

## O que existe quando a card começa

`GET /api/v1/leads` aceita `status`, `temperatura`, `canal`, `corretorId`, `busca`, `ordenar`, `limite` (padrão 25) e `cursor`, e devolve `{itens, proximoCursor}`, **sem `total`** (Emenda E-01 da TEC-192). O recorte do CORRETOR é do backend, pela claim do JWT. A tela (TEC-321) mostra só a primeira página, com a busca e as duas ordens na URL, e diz "Ver os demais ainda não está disponível".

**Duas coisas que a card pressupõe e que não existem:**

1. **páginas numeradas sem total.** O cursor só sabe dar a próxima página, não a página 7;
2. **nomes para o filtro por corretor.** `GET /api/v1/corretores` exige `GERIR_CORRETORES`, que só o ADMIN tem. A GERENTE, para quem o filtro mais serve, não tem de onde tirar a lista. É a mesma lacuna que levou a TEC-316 a manter desabilitado o filtro por corretor do funil.

**A card é só de frontend.** O único Python é o teste de vocabulário.

## D1 — Tudo na URL, e mudar filtro volta à primeira página

A URL carrega `busca`, `ordenar`, `status`, `temperatura`, `canal`, `corretorId`, e a posição: `cursor`, `anterior` (repetido) e `acumular`. `lib/leads.ts::urlDaLista` passa a receber o estado inteiro. Os links de ordem, a busca e os filtros o preservam.

**Mudar busca, ordem ou filtro descarta a posição.** Um cursor é de uma consulta, e continuá-lo noutra devolveria uma página plausível e errada. O backend já recusa cursor de outra ordem com 422.

Valor desconhecido na URL cai em "todos", como a ordem cai na padrão. O backend recusaria `status` desconhecido com 422, e a tela não repassa o que não está no vocabulário.

## D2 — Páginas numeradas sem total: os cursores já vistos ficam na URL

**A partir de 1024 px** a navegação é `1 2 3 … N  Próxima`:
- as páginas de 1 a N−1 são as já visitadas;
- N é a atual, marcada com `aria-current`;
- "Próxima" aparece quando há `proximoCursor`.

A URL da página N leva o `cursor` dela e, em `anterior`, os cursores das páginas 2 a N−1, na ordem. A página 1 não tem cursor. Voltar para a página k é remontar a URL com os k−2 primeiros cursores de `anterior` e o seguinte como `cursor`. **Cada página é uma chamada só ao FastAPI.**

**O que não existe, e por quê:** pular para uma página ainda não visitada e dizer "de 7". As duas coisas exigem o total, que a TEC-192 recusou a calcular. "Próxima" é a pergunta que o cursor responde.

O primeiro cenário da card ("da 26ª à 50ª na mesma ordem") é o cursor fazendo o que já faz.

## D3 — "Carregar mais" no celular: o mesmo link, com `acumular`

**Abaixo de 1024 px** a navegação é um botão "Carregar mais": um link para a próxima página com `acumular=1`. Com `acumular`, o servidor busca, em paralelo, a página 1, as de `anterior` e a atual, e desenha todas em sequência. Sem JS, o link funciona. Ele usa `scroll={false}`, então quem rola não volta ao topo, e a URL continua compartilhável.

**As duas navegações vão no HTML, e o CSS escolhe qual aparece.** O servidor não sabe a largura da tela. Com `acumular`, as linhas das páginas anteriores levam a classe `leads-pagina-anterior`, escondida a partir de 1024 px. Um link acumulado aberto no desktop mostra só a página atual, com a numeração.

**O custo de `acumular`:** N chamadas ao FastAPI para a página N, em paralelo. Só o "carregar mais" o pede; a numeração nunca acumula.

## D4 — Cartões abaixo de 768 px, na mesma marcação

Abaixo de 768 px, **a mesma tabela vira cartões pelo CSS**: `display: block` nas linhas, o cabeçalho escondido, e cada célula com o rótulo da coluna vindo de `data-rotulo`. Não há uma segunda marcação. Duplicá-la duplicaria o botão "Revelar" da TEC-330 e o estado dele. A primeira célula (telefone mascarado e link para o detalhe), a temperatura e o score ficam em destaque. **Não há nome**, porque nenhuma tabela o guarda (L3 da TEC-321).

O formato por largura é CSS. **O jsdom não avalia media query**, então os testes afirmam a estrutura: as duas navegações presentes, com as classes certas, e as classes das linhas acumuladas. **A largura real não foi conferida num navegador**: a verificação ponta a ponta leu o HTML servido, e não renderiza CSS. Quem revisar precisa abrir `/leads` em 360, 768 e 1280 px.

## D5 — Os filtros

Um `<form method="get">` com quatro listas: status, temperatura, canal e corretor. Cada uma tem a opção "Todos". Mudar uma lista submete o formulário, e sem JS o botão "Filtrar" faz o mesmo. A busca e a ordem vão em campos ocultos.

- **Status, temperatura e canal** saem dos mapas de rótulo de `lib/leads.ts`, exportados e presos aos vocabulários do backend pelo teste de vocabulário: `conversa/vocabulario.py::Status`, `context/temperatura.py::Temperatura` e os canais de `messages/canais.py`.
- **Corretor**, por papel:
  - **ADMIN** (`GERIR_CORRETORES`): a lista com os corretores ativos, buscada no servidor.
  - **GERENTE e LEITURA**: a lista aparece desabilitada, com "Filtro por corretor indisponível para o seu papel". É o mesmo desfecho da TEC-316.
  - **CORRETOR**: não aparece. O backend já recorta pela carteira dele.
  - **`corretorId` na URL vale para todos.** Um link filtrado pela ADMIN abre filtrado para a GERENTE, e a tela diz "Filtrada por um corretor", com "Remover filtro".

## Fora do escopo

- **Total de leads e salto para página não visitada** (D2).
- **Liberar a lista de corretores para a GERENTE.** É decisão de permissão, não de tela, e a TEC-316 já a deixou em aberto.
