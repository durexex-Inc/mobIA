# TEC-330 — Mascarar e revelar telefone e e-mail do lead no painel

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-330](https://eduardodurieuxlopes.atlassian.net/browse/TEC-330) — épico TEC-304
**Branch:** `feat/tec-330-revelar-dado-pessoal`
**Depende de:** TEC-195 (`POST /leads/{leadId}/revelar` e a máscara), TEC-323 (o detalhe), TEC-321 (a lista), TEC-312 (permissões no servidor), TEC-302 (o `/bff/*`)

## O que existe quando a card começa

Desde a TEC-195 **todo chamador recebe o telefone mascarado**, com ou sem `VER_DADOS_COMPLETOS` (D4 de lá): a lista e o detalhe nunca carregam o número cheio para papel nenhum. O primeiro cenário da card — o navegador do CORRETOR só recebe a máscara — já é verdade no backend, e é verdade também para a GERENTE.

`POST /api/v1/leads/{leadId}/revelar` com `{"campo": "telefone" | "email"}` exige `VER_DADOS_COMPLETOS` (GERENTE e ADMIN), grava e **comita** `DADO_PESSOAL_ACESSADO` com o campo antes de ler o valor, e responde `{"campo", "valor"}`. O telefone sai na forma canônica com `+` (`+5548999990021`); o e-mail sai **sempre `null`**, porque nenhuma tabela guarda e-mail de lead (D7 da TEC-195).

**Três coisas que a card pressupõe e que não existem:**

1. a revelação não chega ao navegador: a allowlist do `/bff/*` a deixou de fora de propósito, com teste que prende isso;
2. o e-mail não tem valor a revelar;
3. na lista, o telefone é o texto do link que abre o detalhe, e um botão não pode morar dentro de `<a>`.

## D1 — Um componente de cliente guarda o valor, e só ele

`components/DadoRevelavel.tsx`, `'use client'`. Recebe o lead, o campo e o texto mascarado, mostra a máscara e um botão **Revelar**. O clique faz o `POST` pelo proxy; **o valor só aparece quando a resposta chega com 200**, e o 200 só sai depois do commit da trilha. É isso que atende ao "só então o número completo é exibido": a tela não tem um estado intermediário em que mostre o número antes da resposta.

O valor vive num `useState` e em nenhum outro lugar:

- **5 minutos** depois da resposta, um `setTimeout` o apaga e a máscara volta;
- **sair da tela** desmonta o componente, e o estado morre com ele; voltar começa mascarado;
- **Ocultar** apaga antes do prazo. A card não pede, mas custa um botão, e quem revelou para ditar um número não tem por que deixá-lo na tela por cinco minutos.

Nada vai para URL, `localStorage`, `sessionStorage` ou `console`. Não há cache de requisição do lado do cliente para evitar: o painel não usa react-query nem SWR, e o `fetch` vai com `cache: 'no-store'` mesmo assim, para que ninguém dependa de o `POST` não ser cacheável.

Revelar de novo depois do prazo grava outra linha na trilha. É o comportamento certo: são duas leituras.

## D2 — O botão só aparece para quem pode, e só quando há o que revelar

A página decide no servidor, como toda permissão do painel (D2 da TEC-312): `quem.permissoes.has('VER_DADOS_COMPLETOS')` vira a prop `podeRevelar`. Para CORRETOR e LEITURA o componente nem monta o botão.

**Sem máscara não há botão.** Telefone `null` (lead do site sem vínculo) continua "Não informado", e revelar gravaria na trilha a leitura de um campo vazio.

**Por isso o e-mail não ganha botão nesta card.** O detalhe recebe `contato.email: null` sempre, e oferecer "Revelar" para devolver `null` seria um clique que grava auditoria para dizer que não há nada. A seção passa a ler `contato.email` em vez de escrever "Não informado" fixo: no dia em que a coluna nascer e o backend mandar a máscara, o botão aparece sem mudar a tela. O `campo` do componente já aceita `'email'`.

Se a resposta vier com `valor: null` mesmo havendo máscara (o número sumiu entre o carregamento e o clique), a tela diz "Não informado" até o prazo, e não volta a mostrar a máscara como se houvesse número.

## D3 — O número aparece como o backend o manda

`+5548999990021`, sem espaços nem hífen. A docstring de `repositorio.py::valor_revelado` explica por que o backend já manda a forma canônica: é a que se disca e se copia, e uma segunda regra de formatação na tela seria livre para divergir da máscara. A tela não formata.

## D4 — Lista e detalhe

- **Detalhe:** o telefone da seção Contato vira `DadoRevelavel`. O título (`h1`) continua mascarado: ele identifica o lead, e revelar ali duplicaria o número na tela sem ninguém ter pedido duas vezes.
- **Lista:** a primeira coluna mostra o link para o detalhe, como hoje, e o botão fica **ao lado do link, fora dele**. Revelado, o número passa a ser o texto do link. `TabelaDeLeads` ganha `podeRevelar`.

## D5 — O proxy libera a revelação e manda `no-store` em tudo

`ROTAS_PERMITIDAS` ganha `POST api/v1/leads/*/revelar`. A regra de `Origin` já recusa mutação de outra origem, e quem decide o papel é o FastAPI, pelo JWT da sessão.

**Toda resposta do `/bff/*` passa a levar `Cache-Control: no-store`.** O proxy só serve dado pessoal (transcrição, revelação) e mutação; nada ali deveria ficar em cache de navegador nem de intermediário. É uma linha, e troca "o `POST` não costuma ser cacheado" por "não é cacheado".

## Erros

| status | a tela diz |
| --- | --- |
| 401 | Sua sessão terminou. Recarregue a página para entrar de novo. |
| 403 | Você não tem permissão para ver este dado. |
| 404 | Este lead não existe mais. |
| rede ou outro | Não foi possível revelar. Tente de novo. |

Em todos, a máscara fica.

## Fora do escopo

- **Exportação:** nenhuma exportação de lead existe (RN-FE-10.4).
- **E-mail revelado de fato:** falta a fonte, que é de outra card (D2).
- **Logs do servidor:** o proxy não registra corpo de resposta, e o FastAPI também não. Esta card não muda nenhum dos dois.
