# TEC-353 — Informar o telefone com máscara e pedir um corretor pelo chat

**Status:** implementado (28/09/2026)
**Card:** [TEC-353](https://eduardodurieuxlopes.atlassian.net/browse/TEC-353) — épico TEC-307
**Branch:** `feat/tec-353-telefone-e-corretor`
**Depende de:** TEC-346 (a conversa), TEC-129 (o vínculo por telefone), TEC-143 (o pedido de humano), TEC-182 (o opt-out)

## O que existe quando a card começa

- **O agente nunca pede o telefone.** A TEC-129 deixou isso fora do escopo ("O agente pedir o telefone"), e nenhum prompt do agente fala de telefone, contato ou WhatsApp. Nenhum frame do servidor diz que o telefone foi pedido.
- **O vínculo sai de uma regex sobre a fala.** `domain/identidade/telefone.py::extrair_telefone` reconhece telefone brasileiro em qualquer mensagem da visitante, com ou sem `+55`, e a D2 da TEC-129 recusou um frame `telefone` próprio.
- **O pedido de humano é uma guarda determinística sobre o texto.** `domain/humano/deteccao.py::pediu_humano` casa uma lista de termos. **"Quero falar com um corretor" não casa**: a lista só tem "falar com um corretor de verdade", e "falar com um corretor" solto é conversa normal de quem quer visitar um imóvel.
- **O opt-out também é guarda sobre o texto** (`domain/optout/deteccao.py::pediu_optout`). A confirmação sai pelo mesmo `WebOutbound` de toda fala, e o chat já a desenha como balão do agente.

As regras RN-FE-20.3 a 20.5 vêm do texto da card: o SRS do frontend não está no repo.

## D1 — O campo de telefone abre pelo menu, porque o agente não pede

A regra da card é "quando o agente pede o telefone, o widget oferece campo com máscara". Esse momento não existe:

- o agente não pede;
- se passasse a pedir, seria uma mudança no comportamento da conversa, que a TEC-129 recusou decidir;
- adivinhar o pedido pelo texto do agente ("telefone" numa fala) acenderia o campo em "o telefone da imobiliária é…".

**Por isso o campo abre por "Informar meu telefone", no menu "Opções da conversa"**, ao lado de "Falar com um corretor". A visitante escolhe quando dar o número, e o contorno da card continua valendo: quem digita o telefone no campo de texto é vinculado do mesmo jeito.

Os dois cenários de telefone ("Dado que o assistente pediu o telefone") são exercitados a partir do menu. A premissa deles não acontece hoje.

## D2 — A máscara e a validação

- **O campo aceita só dígitos, até 11, sem o `+55`**, e mostra `(48) 99999-0021` enquanto a visitante digita. `type="tel"`, `inputMode="numeric"`, `autoComplete="tel-national"`.
- **Válido:**
  - 11 dígitos com DDD em uso e o assinante começando por 9 (celular);
  - 10 dígitos com DDD em uso e o assinante começando de 2 a 5 (fixo).

  É a regra de `normalizar` no servidor, sem o que ele aceita e o campo não precisa: o `+55`, o zero de tronco, o celular antigo de 8 dígitos.
- **A lista de DDDs é cópia de `_DDDS`** (`src/mobia/domain/identidade/telefone.py`). Mudar uma sem a outra deixa o cliente recusar o que o servidor vincularia, ou o contrário.
- **Inválido, o envio é bloqueado** e o campo diz o formato esperado: "Informe DDD e número: (48) 99999-0021 para celular ou (48) 3333-0021 para fixo." Com `aria-invalid` e a mensagem ligada por `aria-describedby`.
- **O que sai é uma mensagem comum** com o número em `+55 48 99999-0021` (celular) ou `+55 48 3333-0021` (fixo) — o formato do primeiro cenário. Ela vira balão, passa pela fila da reconexão e pela ciência da TEC-352, e o servidor a vincula pela regex, sem frame novo.

## D3 — "Falar com um corretor" manda uma frase que a guarda reconhece

- O item do menu envia **"Quero falar com uma pessoa da equipe de corretores."** como mensagem da visitante. Ela contém "falar com uma pessoa", que é termo da guarda, e diz o que o botão diz.
- **A lista de termos não muda.** Pôr "falar com um corretor" nela mudaria o WhatsApp também, e ali a frase é o começo normal de quem quer visitar.
- **O contrato é um teste do backend** (`tests/unit/test_contrato_do_chat_web.py`): `pediu_humano` da frase é verdadeiro, e `extrair_telefone` das duas formas da D2 dá o número canônico. As frases são cópias das constantes do frontend, e o teste as nomeia. Assim, quem mexer na lista de termos, ou na regex, vê o chat quebrar.

## D4 — Opt-out sem lógica no cliente

"parar" e "sair" saem como qualquer mensagem. A confirmação do servidor chega como `mensagem` e vira balão do agente. Não há código novo: o cenário é exercitado para provar que ele continua sem código.

## D5 — O menu

- **Três itens, nesta ordem:** "Falar com um corretor", "Informar meu telefone", "Encerrar conversa". Abrir o menu foca o primeiro.
- **Setas para cima e para baixo** movem o foco entre os itens, e as pontas dão a volta (padrão de `role="menu"`). Escape fecha, como já fazia.
- **Com o campo de telefone aberto**, "Cancelar" volta ao campo de texto sem enviar nada.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, API, worker ARQ e `next dev` locais, chaves externas inválidas. As duas guardas não chamam o modelo, e por isso respondem de verdade mesmo sem chave.

| passo | resultado |
| --- | --- |
| menu → "Informar meu telefone", "9999-002", enviar | nada saiu; o campo mostrou "Informe DDD e número: …" |
| "48999990021", enviar | o campo mostrou `(48) 99999-0021`; o balão `+55 48 99999-0021` foi a "Recebida"; linha nova em `vinculos_de_sessao`, canal `web` |
| menu → "Falar com um corretor" | o balão com a frase; o servidor respondeu "Claro! Já estou passando esta conversa para um corretor da nossa equipe. …" |
| "parar" | o servidor respondeu "Pronto, não vou mais te enviar mensagens. …"; linha em `optout_events`, canal `web` |

O turno da mensagem do telefone falhou no classificador, porque a chave era inválida, e o vínculo saiu assim mesmo: ele é gravado na ingestão, antes do turno (TEC-129).

## Testes

- `lib/telefone`:
  - a máscara parcial;
  - os válidos (celular e fixo);
  - os inválidos: incompleto, DDD fora de uso, celular sem o 9, fixo começando por 6;
  - o formato de envio.
- Backend: o teste de contrato da D3.
- Componente (socket falso):
  - "Falar com um corretor" manda a frase;
  - o campo de telefone abre pelo menu, mascara, bloqueia "9999-002" com o formato esperado e manda "+55 48 99999-0021";
  - "Cancelar" volta;
  - "parar" sai como mensagem, e a confirmação do servidor aparece;
  - setas no menu.
- Navegador, com o worker de pé e chaves inválidas (as duas guardas não chamam o modelo):
  - "Falar com um corretor" leva à resposta de encaminhamento;
  - "parar" leva à confirmação do opt-out;
  - o telefone vincula a sessão (`vinculos_de_sessao`).

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Informar telefone válido | componente e `lib`: "(48) 99999-0021" sai como "+55 48 99999-0021"; navegador: o vínculo |
| Recusar telefone incompleto | componente: "9999-002" não sai, e o campo mostra o formato |
| Pedir um corretor | componente: a frase; contrato no backend; navegador: a resposta do servidor |
| Opt-out é tratado pelo servidor | componente: "parar" como mensagem comum e a confirmação como balão; navegador |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — O campo não abre sozinho quando o agente pede o telefone**, porque o agente não pede (D1). Se uma card futura fizer o agente pedir, ela precisa emitir um sinal (um `kind` na mensagem, por exemplo), e o campo passa a abrir por ele.
- **L3 — Só número brasileiro**, como no servidor.
- **L4 — O vínculo não é verificado** (D1 da TEC-129): quem digita o número de outra pessoa é vinculado a ela.
