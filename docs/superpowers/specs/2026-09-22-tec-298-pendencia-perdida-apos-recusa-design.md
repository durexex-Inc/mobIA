# TEC-298 — A rota de recuperação que a TEC-295 abriu deixa de morrer na retentativa

**Status:** implementado
**Card:** [TEC-298](https://eduardodurieuxlopes.atlassian.net/browse/TEC-298)
**Branch:** `feat/tec-298-pendencia-perdida-apos-recusa`
**Origem:** revisão final da TEC-295 (PR #143), achado I1.
**Linhas citadas:** os números de linha deste documento valem para `8c4fd85`. `turno.py` tem 4302 linhas e muda em quase toda card; confie no nome da função, não no número.

## Objetivo

A TEC-295 (D4) fez o turno bloqueado pela moderação de entrada entregar a recusa **e** continuar, para responder a pergunta legítima que veio antes dela na rajada. A rota existe e funciona na primeira passada. **Ela morre em qualquer retentativa** — e a retentativa é o caso comum, porque entre a recusa e a resposta o turno executa mais de mil linhas, chama o modelo e faz duas entregas.

Esta card faz a rota sobreviver ao reprocessamento, para de pagar moderação por uma fala já julgada, e conserta um alarme que hoje dispara sobre algo que chegou.

## O estado antes desta card, conferido no código durante o desenho

- **`ha_fala_pendente_antes` (`messages/rajada.py:55`) tem UM chamador em produção**, `turno.py:1524`. Os outros leitores são testes (`tests/integration/test_rajada.py`). A card supôs que mexer na semântica dela exigiria pensar "contra os outros usos"; não há outros usos.
- **A fronteira que ela usa é `MAX(created_at)` das falas OUTBOUND** do par `(channel, conversation_key)`. Não há filtro por tipo de fala: qualquer coisa que o agente diga fecha a pendência.
- **`GuardedOutbound.send` reserva e COMMITA antes de entregar** (`outbound/port.py:288`). A linha OUTBOUND da recusa só é gravada depois, pelo `MessageRecorder` no fim de `_entregar_texto_fixo`. Logo `outbound_dispatches.created_at` da reserva é **estritamente anterior** ao `created_at` da fala que envenena a fronteira.
- **Numa falha retentável, a reserva da recusa NÃO é liberada.** `KIND_DA_RECUSA_DE_ENTRADA` não está em `_GRUPOS` (`outbound/kinds.py`), então `grupo_de` devolve `(kind,)` e `_liberar` apaga só a dela — mas `_liberar` só roda no `except (EnvioRetentavel, CancelledError)` do próprio `send` da recusa. A falha desta card acontece **depois**, na resposta, e a reserva da recusa fica.
- **`messages.bloqueada_em` já é o veredito persistido do caso bloqueado.** `marcar_bloqueada` (`messages/bloqueio.py:53`) carimba a coluna e grava o `ModerationEvent` no mesmo commit. Na retentativa a linha já está carimbada antes de o moderador ser chamado de novo.
- **`PROCESSED` é terminal.** Não está em `CLAIMABLE_STATUSES` e `sweep_stalled` não o seleciona. A pergunta agrupada não tem rota de recuperação própria — a única que existe é a continuação do turno da carregadora.

## O defeito, em três metades independentes

**(1) A própria recusa apaga a pendência.** Na retentativa, `ha_fala_pendente_antes` devolve `False`: a recusa da passada anterior foi gravada como OUTBOUND e virou a última fala do agente. `tem_pendencia` sai falso, e a continuação não roda.

O comentário da TEC-295 marcado `D4, ruling R5`, logo acima do cálculo, já previu exatamente este mecanismo — e por isso mandou calcular `tem_pendencia` ANTES de `_entregar_texto_fixo`. **A ordem está certa e não é o defeito.** O que ela não cobre é a passada SEGUINTE, em que a recusa já está no banco antes de o turno começar.

**(2) O guard fecha o turno mesmo quando a recusa já chegou.** `turno.py:1562` retorna para todo desfecho que não seja `"respondido"`. Isso está certo para os outros três (janela fechada, opt-out concorrente, atendimento humano concorrente) e **errado para `"reentrega_suprimida"`**, que significa o contrário de "não chegou". O comentário logo acima dele já declara a consequência por escrito — a card corrigiu o comentário, não o comportamento.

**(3) O alarme mente, e a moderação é repaga.** `_entregar_texto_fixo` loga `turno.reentrega_suprimida` em `error` — o alarme de dado sumido — sobre uma recusa que chegou. E `_ModeracaoDoTurno.resolver` (`turno.py:857`) chama o moderador de novo, pagando outra vez e gravando outra linha em `moderation_events` para a mesma fala.

## Decisões

### D1 — A fronteira do agente ganha um teto opcional, e o teto vem da reserva

`ha_fala_pendente_antes` passa a aceitar `teto_do_agente: datetime | None = None`. Quando dado, o `MAX(created_at)` das falas OUTBOUND ignora as falas a partir dele — reconstruindo a fronteira que existia antes da recusa.

O chamador obtém o teto consultando `outbound_dispatches` por `(message.id, KIND_DA_RECUSA_DE_ENTRADA)`: se a reserva existe, esta é uma retentativa e o `created_at` dela é o teto; se não existe, é a primeira passada e o teto é `None`.

**Por que funciona:** a reserva é commitada antes do `_deliver`, e a fala OUTBOUND é gravada depois dele. A desigualdade é estrita e não depende de relógio de cliente — os dois carimbos são `func.now()` do Postgres.

**Por que não a coluna nova** (opção 2 da card): custaria migration, uma coluna na tabela mais quente do sistema e uma escrita a mais no caminho crítico, para guardar um fato que já é derivável. A docstring de `rajada.py` promete que nenhuma das duas funções guarda estado — "são recomputadas de `messages`, que é onde já está". Uma coluna quebraria essa promessa; o teto a preserva.

**Por que não "a recusa nunca é fronteira"** (opção 1 da card): é a leitura mais bonita — uma recusa não responde nada, então nunca deveria fechar uma pendência —, e **foi descartada por falta de discriminador**, não por discordância. `messages` não guarda `kind`; `text_body` está cifrado; e `message_telemetry.subagent = "moderacao"` é o default de `_entregar_texto_fixo`, compartilhado com o texto do laço de busca excedido, que é resposta de verdade. Registrado aqui para não ser tentada de novo sem um sinal novo.

### D2 — O risco do parâmetro opcional fica declarado, não resolvido

Um chamador futuro de `ha_fala_pendente_antes` que esqueça de passar o teto cai no defeito de hoje, em silêncio. A alternativa seria a função descobrir o teto sozinha — mas aí `domain/messages/rajada.py` passaria a conhecer `outbound_dispatches` e o kind da recusa, acoplamento que ela hoje não tem e que inverteria a direção da dependência.

Fica o parâmetro, e a razão fica presa na docstring dela. **Hoje o chamador é um só**, o que torna o risco pequeno e o custo do acoplamento desproporcional.

### D3 — O guard deixa `"reentrega_suprimida"` seguir, e só ele

`turno.py:1562` passa a separar os quatro desfechos: `"respondido"` e `"reentrega_suprimida"` seguem para a continuação (ainda sujeitos ao `if not tem_pendencia` logo abaixo); `"expirado"`, `"bloqueado_por_optout"` e `"bloqueado_por_atendimento_humano"` continuam retornando.

O critério não muda: **a continuação acontece quando o lead já tem a recusa em mãos.** Nos três que saem, ou o lead não pode receber nada agora, ou a entrega falhou de verdade.

### D4 — O alarme da recusa vira `warning` com nome próprio, e não `info`

Em `_entregar_texto_fixo`, quando `kind == KIND_DA_RECUSA_DE_ENTRADA`, o `log.error("turno.reentrega_suprimida")` vira `log.warning("turno.recusa_ja_reservada")`. O desfecho devolvido continua `"reentrega_suprimida"` — nenhum valor novo no `Literal` de `ResultadoDoTurno`, nenhum chamador a atualizar.

**`info` foi recusado de propósito.** A reserva sobrevivente é evidência forte de entrega, **não é prova**: ela também sobrevive se o worker morreu entre o commit da reserva e o `_deliver`, ou se o próprio `_liberar` falhou. Nessas duas rotas a recusa de fato não chegou. `warning` diz o que se sabe — a reserva existe, então quase certamente chegou — sem fingir certeza e sem acordar ninguém à toa. A rota do `_liberar` já tem alarme próprio (`outbound.liberacao_falhou`).

O critério de pronto da card pede que "o alarme não dispare em falso quando a recusa já havia chegado". **Ele é cumprido no que é verificável e não no que é indecidível** — daqui não há como saber que chegou, só que foi reservada.

### D5 — A moderação não é repaga quando a fala já está carimbada

`_ModeracaoDoTurno.resolver` passa a consultar `messages.bloqueada_em` antes de chamar o moderador. Não-nulo significa que uma passada anterior já julgou e bloqueou esta fala: o `Veredito` é remontado do banco — `bloqueado=True`, `categoria` da última linha de `moderation_events` daquele `message_id` com `direcao = 'entrada'`.

Sem migration, sem tabela nova. Economiza a chamada paga e a linha duplicada de auditoria.

**O caso LIBERADO continua repagando, e isso é declarado.** "Moderou e liberou" não é persistido em lugar nenhum — `bloqueada_em` nulo não distingue "julgado e liberado" de "nunca julgado", e a assimetria é do desenho da TEC-236, não desta card. Persistir o veredito liberado exigiria coluna ou tabela nova e decidir invalidação; fica fora. Um turno que morre depois de uma moderação limpa segue pagando duas vezes.

**O `motivo` do `Veredito` remontado fica vazio.** Ele não é persistido e só alimenta o log `moderacao.entrada_bloqueada`, que a passada anterior já emitiu. Remontar um `motivo` inventado seria pior que a lacuna.

### D6 — O comentário de `marcar_bloqueada` deixa de valer, e muda junto

A docstring de `marcar_bloqueada` (`messages/bloqueio.py`) afirma hoje: *"O evento da segunda passada do sweeper é uma linha a mais numa tabela append-only, e não é um problema: `moderation_events` registra recusas, e duas tentativas de recusar a mesma fala foram duas recusas."*

Com a D5, a segunda passada deixa de gravar. O comentário passa a descrever um comportamento que não existe — o defeito que o CLAUDE.md trata como defeito, não como sujeira. Ele é reescrito para registrar a decisão nova e por que ela mudou.

### D7 — O que NÃO muda

- **A regra da TEC-233 continua valendo.** Fala reprovada isolada, sem pendência antes dela, continua fechando o turno logo depois da recusa. O `if not tem_pendencia` de `turno.py:1564` fica onde está.
- **Uma resposta por rajada.** A continuação entrega uma resposta só, pelo mesmo caminho de hoje.
- **A recusa não é reentregue.** A reserva sobrevivente é justamente o que garante isso, e a D3 não a toca.
- **A ordem de cálculo da TEC-295 (D4, ruling R5).** `tem_pendencia` continua sendo calculado antes de `_entregar_texto_fixo`. O teto da D1 cobre a passada seguinte, não substitui a ordem.

## Emenda ao SRS

**Emenda E-04 à RN-04.5.** A E-01 (TEC-142) deu forma ao evento de auditoria: uma linha em `moderation_events` por bloqueio. A prática até aqui gravava **uma linha por tentativa de recusa** — um turno que falhava depois da moderação e era reprocessado deixava duas linhas para a mesma fala, e o comentário de `marcar_bloqueada` registrava isso como aceito. Com esta card a linha passa a significar **uma fala recusada**: a retentativa reconhece o carimbo de `bloqueada_em` e não regrava. Quem audita lê contagem de recusas, e a contagem passa a ser de falas e não de tentativas — mais próxima do que a regra base diz, e diferente do que a tabela vinha registrando.

## Testes

O critério da card pede o que hoje não existe: forçar a falha **entre as duas entregas**. O molde está em `tests/features/test_reprocessamento_apos_falha.py`, que já faz isso para a resposta.

1. **A pergunta pendente é respondida na retentativa.** Rajada com pergunta legítima agrupada + carregadora bloqueada; a recusa sai, a resposta falha com `EnvioRetentavel`, o sweeper reprocessa — e o lead recebe a resposta à pergunta.
2. **A recusa não sai de novo** nessa mesma retentativa.
3. **A retentativa não chama o moderador** e não grava segunda linha em `moderation_events`.
4. **Fala reprovada isolada continua não engajando** — a garantia da TEC-233, na retentativa e não só na primeira passada.
5. **O teto em `ha_fala_pendente_antes`**, direto, em `test_rajada.py`: com teto anterior à fala do agente, a pendência reaparece; sem teto, o comportamento de hoje é idêntico ao de antes (nenhum dos testes existentes muda).

**Doze asserções existentes citam `turno.reentrega_suprimida`** — em `test_formato_no_turno.py`, `test_turno.py`, `test_turno_atendimento_humano.py` e `test_turno_optout.py`. A D4 muda o nome do evento **só** quando `kind == KIND_DA_RECUSA_DE_ENTRADA`, e essas quatro exercitam a resposta, a confirmação de opt-out e a janela humana. A implementação confirma uma a uma que nenhuma passa pelo kind da recusa antes de declarar que continuam valendo — se alguma passar, ela é atualizada e a razão entra no comentário do PR.

## Fora de escopo

- **Persistir o veredito LIBERADO** para evitar remoderação de turnos que falham depois de uma moderação limpa (ver D5).
- **Dar rota de recuperação própria à mensagem `PROCESSED`/`"agrupado"`.** A continuação do turno da carregadora continua sendo a única rota; esta card a faz sobreviver, não cria uma segunda.
- **Partir `executar_turno`.** As 2706 linhas que o CLAUDE.md nomeia continuam lá.
