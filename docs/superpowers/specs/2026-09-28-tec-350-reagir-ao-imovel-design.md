# TEC-350 — Reagir a um imóvel com "Gostei" ou "Não é pra mim"

**Status:** implementado (28/09/2026)
**Card:** [TEC-350](https://eduardodurieuxlopes.atlassian.net/browse/TEC-350) — épico TEC-307
**Branch:** `feat/tec-350-reagir-ao-imovel`
**Depende de:** TEC-349 (os cards), TEC-163 (a reação registrada), TEC-348 (a fila local)

## O que existe quando a card começa

- **O card não tem botão de reação.** `CardDeImovel` só recebe o imóvel, de propósito: a pré-visualização da administração (TEC-336) desenha o mesmo componente.
- **A reação já é registrada pelo servidor a partir do texto.** No turno seguinte a uma apresentação, `classificador.reagir` recebe os imóveis pendentes numerados como `N. {titulo} -- {bairro}` e a fala do lead, e devolve por ordinal `INTERESSE` ou `DESCARTE` (D6 e D7 da TEC-163). Não existe outro canal: o protocolo do WebSocket não tem frame de reação.
- **A captura acontece uma vez por apresentação** (D8 da TEC-163). O primeiro turno depois das fichas resolve todas as pendentes. Os imóveis que o lead não mencionou fecham como `NEUTRO`, e dali em diante não há o que capturar até a próxima apresentação.

A regra RN-FE-18.5 vem do texto da card: o SRS do frontend não está no repo.

## D1 — O toque manda uma mensagem comum, com título e bairro

- "Gostei" envia `Gostei do imóvel "Casa 3 quartos" (Campeche).`
- "Não é pra mim" envia `O imóvel "Casa 3 quartos" (Campeche) não é pra mim.`
- **Título e bairro são o que o `reagir` lê de cada imóvel.** Com os dois no texto, o modelo casa o toque com o ordinal certo mesmo quando dois cards têm o mesmo título. O `id` não vai no texto: é UUID, o modelo nunca o vê, e a D7 da TEC-163 existe para que ele não produza identificador.
- **É o mesmo caminho do campo de texto.** O toque passa por `enviar` e `transmitir`: vira balão da visitante, ganha `messageId`, estado "Enviando…" → "Recebida", e entra na fila local da TEC-348 se a conexão estiver caída. O cenário "a conversa mostra a mensagem de Marina" sai daí de graça.
- É texto que a visitante lê: com acento.

## D2 — Um toque por card, e o card mostra qual foi

- Depois do toque, os dois botões daquele card ficam desabilitados, e o escolhido fica marcado (`aria-pressed`).
- **Trocar de ideia é pelo campo de texto.** Um segundo toque mandaria uma segunda mensagem contradizendo a primeira, e o servidor não a registraria (D3).
- O que foi tocado vive no estado do componente `Conversa`, por `id` do imóvel, e some com "Encerrar conversa". Na reconexão, o `historico` troca a fileira de cards pelos balões com a legenda (L2 da TEC-364), e os botões somem com ela.
- Durante a espera de `muitas_tentativas` os botões ficam desabilitados, como o campo, que nem aparece.

## D3 — O card só ganha os botões quando quem o desenha pede

`CardDeImovel` recebe `aoReagir` opcional e a reação já escolhida. Sem `aoReagir`, o card é o de hoje, e a pré-visualização da administração continua sem botão nenhum.

Os botões ficam num rodapé do card, acima da área de clique esticada do título (`.card-imovel__acao::after`). Sem isso, o toque em "Gostei" expandiria a ficha.

## Verificação no navegador (28/09/2026)

Edge headless dirigido por CDP, `/embed/chat` servido pelo `next dev`, API local com as chaves externas inválidas. Os cards foram publicados direto no canal Redis da sessão, sem o modelo. Os cliques são eventos de mouse por coordenada, que passam pelo hit-testing — `element.click()` não pegaria a área esticada do título por cima dos botões.

| passo | resultado |
| --- | --- |
| clique em "Gostei" no primeiro card | a ficha não expandiu; "Gostei" marcado, os dois desabilitados, o segundo card livre; o balão `Gostei do imóvel "Casa 3 quartos" (Campeche).` chegou a "Recebida" |
| clique em "Não é pra mim" no segundo card | o balão `O imóvel "Apartamento 2 quartos" (Trindade) não é pra mim.`, "Recebida" |
| clique no preço do primeiro card | a ficha expandiu: a área de clique do card continua valendo fora do rodapé |

**Não exercitado: a linha em `recomendacoes`.** Registrar a reação exige a chamada `reagir` ao modelo, que é paga, e a verificação roda com a chave inválida. O caminho do servidor é o da TEC-163, sem mudança; o que esta card garante é o texto que chega a ele.

## Testes

- `CardDeImovel`: sem `aoReagir` não há botão; com ele, os dois botões, e o clique chama `aoReagir` com a reação; a reação escolhida desabilita os dois e marca a escolhida; clicar num botão não expande a ficha.
- `Conversa` (socket falso): "Gostei" num card manda o frame `mensagem` com o texto do D1 e mostra o balão da visitante; "Não é pra mim" idem; os botões daquele card ficam desabilitados e os dos outros não; com a conexão caída, o toque fica "Enviando…" e sai na reconexão; "Encerrar conversa" limpa.
- Navegador: toque num card de uma apresentação real e conferência da linha em `recomendacoes`, se houver chave do modelo; sem ela, o balão e o frame.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Gostar de um imóvel — a conversa mostra a mensagem | componente: o balão com "Gostei do imóvel "Casa 3 quartos" (…)" |
| Gostar de um imóvel — a reação fica registrada no lead | a gravação é do servidor (TEC-163), a partir do texto; ver L2 |
| Descartar um imóvel | componente: o balão com "… não é pra mim." |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — Só o primeiro toque depois de uma apresentação é registrado** (D8 da TEC-163). Se Marina toca "Gostei" no primeiro card e depois "Não é pra mim" no segundo, o primeiro toque grava `INTERESSE` no primeiro e `NEUTRO` nos outros dois; o segundo toque chega ao agente como texto, mas não muda nenhuma linha de `recomendacoes`. O mesmo vale para um toque depois de ela já ter escrito qualquer coisa. Registrar reações posteriores exige mudar a D8 da TEC-163 no servidor.
- **L3 — O registro depende do modelo.** A reação sai de uma chamada ao LLM que lê o texto, e não de um frame estruturado: um toque é tão confiável quanto uma frase digitada, não mais. Um frame de reação no protocolo tornaria o registro determinístico, e é trabalho de servidor.
- **L4 — "Não é pra mim" não diz o porquê.** Sem motivo no texto, o `reagir` não tem de onde tirar `DISTANCIA`, e só `DISTANCIA` conta para a realimentação do filtro de bairro (RN-10.4). Só a visitante que escreve "é longe demais" alimenta o filtro.
