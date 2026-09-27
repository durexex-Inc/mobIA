# TEC-381 — Pseudonimizar dado de identificação antes do envio ao provedor de LLM

**Status:** desenho aprovado (as duas decisões de produto foram tomadas pelo Eduardo em 27/09/2026), implementado nesta branch
**Card:** [TEC-381](https://eduardodurieuxlopes.atlassian.net/browse/TEC-381) — épico TEC-200
**Branch:** `feat/tec-381-pseudonimizar-antes-do-llm`
**Origem:** RNF-23 (SRS v1.0): "dados de identificação direta (nome completo, telefone) são substituídos por pseudônimos antes do envio ao modelo sempre que não forem necessários à resposta".

## O que o repo tem, medido sobre `5151500`

1. **Nenhum campo nosso põe nome ou telefone no prompt.** O `conversation_key` do dossiê é HMAC (TEC-203), e o dossiê do handoff (`handoff/dossie.py::renderizar`) é estruturado, sem texto livre do lead.
2. **Três caminhos levam o texto livre do lead a um provedor:**
   - **o contexto do turno e a dobra do resumo**, os dois por `context/montagem.py::_texto_da`, que é também quem mede os tokens. Por ali passam o classificador, o investidor, a desambiguação e o resumidor;
   - **a moderação de entrada**, que manda o `corpo` cru (`messages/bloqueio.py::moderar_entrada_e_marcar`), inclusive a da mensagem superada (`process_message.py::_moderar_superada`);
   - **a Whisper** (TEC-131), que ouve o áudio. Não há como pseudonimizar uma voz.
3. **O telefone tem regra determinística** (`identidade/telefone.py`); o nome não tem.

## D1 — Escopo: o texto que o lead escreve, em trânsito

"O que nós pomos no prompt" é vazio, e atender a card por construção não protegeria nada: o único canal real é o lead escrevendo o próprio nome e o próprio número. Então a pseudonimização age sobre o texto do lead **nos dois pontos em que ele sai para um provedor de texto**: `_texto_da` e a moderação de entrada.

**Só em trânsito, e nunca no banco.** O vínculo de telefone da TEC-129 lê o número da fala gravada, e o corretor precisa do contato real. O que muda é o que sai do processo.

**Só a fala do LEAD.** O agente nunca viu o nome, então não o repete. A fala do corretor pode ter o nome dele próprio ("aqui é o João"), e esse não é dado do lead.

**Em `_texto_da`, e por isso também na contagem.** Os tokens medidos e os enviados continuam sendo o mesmo texto, que é o invariante de `test_diferenca_entre_o_contado_e_o_enviado`. O prompt de sistema não muda, então `test_a_margem_do_orcamento_do_prompt_e_deliberada` não se mexe. Os marcadores entram nas literais, que são variáveis.

## D2 — Irreversível, com marcador (decisão do Eduardo)

O modelo recebe `[nome do lead]` ou `[telefone do lead]` e nunca o original. O agente deixa de chamar o lead pelo nome. A RNF-23 fala em "pseudônimo"; o marcador é um pseudônimo fixo, e **não há tabela de reversão**, o que é mais forte que o requisito.

**A guarda de saída.** Se o modelo copiar um marcador para a resposta, o lead receberia "Oi, [nome do lead]!". `sem_marcadores` limpa a fala do modelo nos três pontos em que o classificador a constrói: a resposta do agente, a do investidor e a pergunta de desambiguação. Limpa na fonte, e não no `send`, porque a fala também é gravada pelo `recorder` e moderada na saída. Uma limpeza só no envio deixaria o marcador no histórico.
- `[nome do lead]` some, com a vírgula e o espaço que o acompanham: "Oi, [nome do lead]! Tudo bem?" vira "Oi! Tudo bem?".
- `[telefone do lead]` vira "seu telefone".

**O resumo guarda os marcadores.** Ele é gerado a partir das literais já pseudonimizadas e volta ao prompt nos turnos seguintes. É o comportamento certo: nome não reentra pelo resumo.

## D3 — Detecção

- **Telefone:** a regex de `identidade/telefone.py`, validada por `normalizar`, a mesma que decide o vínculo. O que não normaliza para um telefone brasileiro (protocolo, CPF cru) não é trocado.
- **Nome (decisão do Eduardo):** só frases explícitas.
  - Depois de "me chamo" e "meu nome é", o nome casa até com minúscula, porque a frase já diz o que vem.
  - Depois de "sou o/a", "aqui é o/a" e "quem fala é o/a", só casa com maiúscula. Sem isso, "sou o dono do apartamento" viraria nome.
  - O nome é de uma a quatro palavras, aceitando "de", "da", "dos" no meio.

**Perde, e é declarado:** o nome solto ("Marina aqui"), a assinatura, o nome de terceiro, e o nome dito sem essas frases.

## Emenda ao SRS

**RNF-23 E-01 (TEC-381, 27/09/2026):**
- o pseudônimo é um marcador fixo e irreversível;
- vale para o texto que o lead escreve, no contexto, no resumo e na moderação de entrada;
- o banco guarda o original;
- nome só é detectado em frase explícita;
- o áudio vai à transcrição sem pseudonimização.

## Testes

- **Unitários:**
  - `pseudonimizar`: formatos de telefone; falsos positivos (protocolo, preço, CPF); as frases de nome, com minúscula e com maiúscula; "sou o dono" não casa; idempotência;
  - `sem_marcadores`;
  - `_texto_da` com a fala do lead e com a do corretor.
- **Integração:**
  - o classificador recebe o contexto pseudonimizado e devolve a resposta limpa;
  - a moderação de entrada recebe o texto pseudonimizado.
- **Features, os dois cenários da card:** um turno de ponta a ponta cujo contexto enviado ao classificador não tem o nome nem o telefone, com o banco guardando os dois.

## O que esta card não entrega

- **A Whisper recebe a voz do lead**, com nome e telefone falados. A transcrição que volta é pseudonimizada daí em diante como qualquer texto.
- **Nome fora das frases explícitas** (D3).
- **O agente não chama o lead pelo nome**, e isso é consequência da D2, não defeito.
- **E-mail, CPF e endereço não entram.** A RNF-23 fala em "nome completo, telefone". Um CPF digitado, por exemplo, ainda vai ao modelo.
