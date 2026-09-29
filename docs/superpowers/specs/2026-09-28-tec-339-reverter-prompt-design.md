# TEC-339 — Reverter um agente para uma versão anterior do prompt

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-339](https://eduardodurieuxlopes.atlassian.net/browse/TEC-339) — História, Should (MoSCoW), prioridade High. Origem: RN-FE-14.3, RN-FE-14.4 (SRS mobIA Frontend v1.0) · TEC-199.

**A história:** *"Como Rafael, administrador da imobiliária, quero voltar um agente para o prompt anterior em segundos, para desfazer uma publicação que piorou o atendimento."*

**Full-stack, como a TEC-337.** `POST /api/v1/prompts/{agente}/rollback` (TEC-199) já faz a reversão em si — mas a card pede uma coisa que a resposta de hoje não tem: *"mostra o tempo até ativação retornado pelo backend."*

## Investigado antes de desenhar: o que é o "tempo até ativação"

A TEC-199 é deliberadamente **sem cache** (`domain/prompts/repositorio.py`, mesmo D1 da `configuracao/repositorio.py`): todo turno lê a vigente na hora, e o rollback grava só uma linha em `ativacoes_de_prompt` — sem fila, sem worker, sem propagação. O alvo "< 30 s" é a **CA-19.2 do SRS** (`docs/srs/srs-agente-sdr-imobiliario-v1.0.md:740`), uma meta de aceite para "o turno seguinte usar o texto revertido" — não um valor que o backend algum dia calculou. Não existe hoje nenhum campo de duração na resposta do `rollback`, em lugar nenhum do sistema (nem em `configuracao/`, que tem a mesma arquitetura sem cache).

**Decisão:** o backend passa a medir e devolver quanto tempo a própria chamada levou — a escrita síncrona no banco, do jeito que ela é. Isso é a única coisa que existe para reportar; fabricar uma "espera de propagação" que não existe seria mentir sobre uma arquitetura que é correta por ser instantânea. O número que a tela mostra vai ficar quase sempre abaixo de 100 ms — o que **cumpre** a meta de 30 s por uma folga enorme, e é honesto sobre o motivo: não há nada para esperar.

## D1 — `POST /rollback` ganha `tempoDeAtivacaoMs`, medido no próprio handler

Em `api/routes/prompts.py::reverter`, um `time.perf_counter()` antes de `repositorio.reverter` e outro depois do `session.commit()` — o mesmo recorte que já é a operação inteira, sem incluir a auditoria (`registrar_evento`) that já acontece antes do commit atual, então a medida cobre exatamente "quanto custou reverter". Campo novo na resposta: `"tempoDeAtivacaoMs": int` (arredondado, nunca negativo). Nenhuma mudança de comportamento nos outros campos nem nos códigos de erro (404/409 continuam iguais, sem o campo, porque nada foi revertido).

## D2 — Confirmar digitando o número, com o mesmo molde de `EliminarDadosDoTitular`

A card pede: *""Reverter para esta versão" exige confirmação digitando o número da versão."* Mesmo padrão de `components/EliminarDadosDoTitular.tsx` (TEC-342): um `<dialog>` com um campo de texto, e o botão "Confirmar reversão" **desabilitado até o texto digitado bater com o número da versão** (comparação de string, não de int — `"06"` não é `"6"`). O número nunca viaja na requisição: só o `versao` do botão que abriu o diálogo, como o `leadId` do path em vez do texto digitado.

**O segundo cenário do Gherkin ("confirmação com número errado") não precisa de nenhum tratamento de erro do servidor** — o botão desabilitado já impede a chamada de sair. Não existe caminho de UI para mandar a reversão com o número errado, então o teste é sobre o DOM (botão desabilitado), não sobre uma resposta HTTP.

## D3 — Onde o botão mora: a lista de versões, uma linha por versão

A TEC-338 já lista as versões (`buscarVersoes`, sem texto) no seletor de comparação. Este card acrescenta, ao lado de cada versão QUE NÃO é a ativa, um botão "Reverter para esta versão" — abre o diálogo do D2, e ao confirmar chama `POST /rollback` com aquele número. A versão ativa não ganha o botão (reverter para ela mesma é sempre `409`, e a TEC-199 já recusa).

## D4 — Sucesso mostra o tempo e atualiza a página; erro mostra a mensagem do backend

Depois do `200`, o diálogo mostra "Revertido para a versão N em X ms" (D1) em vez de fechar direto, com um botão "Fechar" que aciona `router.refresh()` — mesmo padrão de sucesso-antes-de-fechar de `EliminarDadosDoTitular`. `404` (versão nunca existiu) e `409` (já é a ativa — corrida com outra aba) mostram a mensagem do backend como veio, sem inventar texto novo.

## D5 — Outros agentes não mudam: já é verdade por construção

O terceiro cenário ("reverter o qualificador não muda o consultor") não pede código novo: `POST /api/v1/prompts/{agente}/rollback` já tem o agente no path, e cada `AgenteDoPrompt` tem sua própria tabela de ativações (`domain/prompts/repositorio.py`). A página de detalhe de um agente (`/admin/prompts/[agente]`) nunca busca dado do outro. O teste deste cenário é so a garantia de que reverter não navega nem re-busca o outro agente.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Reverter com confirmação | exercitado — diálogo D2, `POST /rollback`, tempo mostrado (D1/D4) |
| Confirmação com número errado | exercitado — botão desabilitado até o texto bater (D2), sem chamada de rede |
| Outros agentes não mudam | exercitado por construção (D5) — teste confirma que nada do outro agente é buscado |

## Fora de escopo

- **Desfazer o rollback** ("re-reverter"): a própria TEC-199 já permite reverter para qualquer versão, inclusive a que valia antes — não é uma ação nova, é o mesmo botão usado de novo.
- **Barra de progresso ou polling do "tempo até ativação"**: o valor é devolvido de uma vez, na mesma resposta do `POST` — não há nada assíncrono para acompanhar (D1).
