# TEC-297 — A moderação de entrada deixa de depender de por onde o turno sai

**Status:** desenhado, não implementado.
**Card:** TEC-297 (High). **Origem:** revisão final do PR #143 (TEC-295), achado C1.
**Base do desenho:** `c8b286a`. Toda linha citada aqui foi conferida nesse commit; se você lê isto depois de a implementação mexer no arquivo, confie no nome da função e não no número.

## Objetivo

Fazer com que toda fala de entrada com corpo seja moderada exatamente uma vez, qualquer que seja a saída que o turno tome — e não apenas quando o turno chega à linha da moderação.

## O estado antes desta card, conferido no código durante o desenho

- A moderação de entrada roda em **dois** pontos de `src/`: `executar_turno` (`turno.py:1311`) e `_moderar_superada` (`workers/jobs/process_message.py:306-367`, criada pela TEC-295).
- **`executar_turno` tem cinco returns antes da moderação, não dois.** A card TEC-297 nomeia dois; os cinco são:

  | # | linha do `return` | desfecho | condição |
  | --- | --- | --- | --- |
  | 1 | 947 | `"silenciado"` | lead já em opt-out |
  | 2 | 1021 | `"atendimento_humano"` | conversa silenciada **ou** handoff já aberto |
  | 3 | 1093 | `"fora_de_escopo"` | `situacao.silencia_o_agente` (RN-03.5) |
  | 4 | 1177 | `"opt_out"` | pedido de opt-out |
  | 5 | 1307 | `"pedido_de_humano"` | pedido explícito de humano |

  O ramo #2 é provavelmente o de maior volume dos cinco, e a card não o menciona: depois que um handoff abre, **toda** mensagem que o lead escrever retorna ali. Não é uma fala, é a conversa inteira com o humano.
- `bloqueada_em` tem **quatro leitores diretos**, e o resumo permanente **não é um deles**:

  | leitor | arquivo | função |
  | --- | --- | --- |
  | 1 | `domain/context/janela.py:56` | `literais_apos` (janela de contexto) |
  | 2 | `domain/context/repositorio.py:1146` | `contar_mensagens_do_lead` (lead score) |
  | 3 | `domain/followup/repositorio.py:182` | CTE `_CTES_DA_ANCORA` |
  | 4 | `domain/messages/rajada.py:93` | `ha_fala_pendente_antes` (TEC-295) |

  O resumo permanente herda a garantia por consumir a saída de `literais_apos` — `_dobrar` opera sobre a lista em memória e nunca relê `messages`. A contagem "quatro consumidores" da TEC-295 contava o resumo como o quarto; o quarto leitor real é `ha_fala_pendente_antes`, que aquela card criou. A garantia é a mesma; a lista de onde mexer, não.

  A CTE do item 3 alimenta **duas** consultas, `candidatos_a_followup` e `listar_dormentes`.
- A moderação é **fail-open na entrada e fail-closed na saída**, assimetria declarada em `domain/moderacao/port.py` e praticada nos dois pontos de entrada. Timeout de `5.0s` e **zero retentativas**, constantes de módulo em `infra/moderacao.py:36-37` — não há campo em `Settings`.
- Custo medido de uma moderação: **US$ 0,00057** (TEC-295, 21/09/2026, `claude-haiku-4-5`).
- **A garantia da TEC-236 nunca foi escrita no SRS.** `TEC-236` e `bloqueada_em` têm zero ocorrências em `docs/srs/`. A RN-04.5 fala em recusa e auditoria; nada sobre contexto ou resumo.

## O defeito

A fala que dispara qualquer uma das cinco saídas nunca é moderada. `bloqueada_em` fica nulo, e os quatro leitores a tratam como fala legítima: ela entra na janela de contexto, é decifrada, vai para o prompt, entra no resumo permanente na dobra dos ~40 turnos, sobe a temperatura do lead e reancora a régua de reengajamento.

O cenário do ramo #5 não é exótico: `"vai se f****, quero falar com uma pessoa"`. O lead que xinga é frequentemente o mesmo que quer falar com gente.

O defeito é **anterior ao debounce**. Não foi a TEC-128 nem a TEC-295 que o criaram, e ele vale para qualquer mensagem, superada ou não.

## O que este desenho descobriu que a card supõe errado

**O prazo de 5 segundos não é obstáculo para moderar nestes ramos.** A card afirma que moderar ali "custa uma chamada paga no caminho de um handoff que promete 5 segundos". O que o SRS promete é a CA-04.3 (linha 203): *"um handoff **é criado** em até 5 s"* — mede até a linha existir no banco. A Emenda E-04 da RN-16.1 (linha 446) diz apenas *"o handoff precisa nascer em até 5 segundos"*, sem ancorar início nem fim; a CA-04.3 é a única definição operacional que existe.

No ramo #5, `registrar_handoff` + `commit` é a primeira coisa que acontece (`turno.py:1207-1219`); log, `_agendar_resumo` e a entrega do aviso vêm todos depois. No ramo #4, `registrar_optout` vem antes da entrega. **Moderar depois da ação e depois da entrega não encosta em nenhum relógio prometido** — nem na CA-04.3, nem na RN-14.1 ("para todo envio automático imediatamente"), nem na Emenda E-01 da RN-04.7, que mede 4 s do início do processamento até a primeira entrega.

A objeção da card só valeria para mover a moderação para **antes** do registro, que este desenho não propõe.

## Decisões

### D1 — Moderação por último em cada saída, não antes

A chamada acontece depois da ação do ramo e depois da entrega do texto do ramo. É isso que mantém os três relógios acima fora do caminho da chamada paga, e é o que dispensa qualquer concorrência: não há nada a paralelizar se nada está esperando.

Consequência aceita: se o processo morrer entre a entrega e a marca, a fala fica sem marca. O sweeper retenta a mensagem inteira e a marca sai na retentativa; `_entregar_texto_fixo` é idempotente pela UNIQUE `(message_id, kind)`, então o texto do ramo não duplica. Janela menor que a da D5 da TEC-295, já aceita por aquele desenho.

### D2 — Marca e auditoria, sem recusa

A fala reprovada nestes cinco ramos recebe `bloqueada_em` e `ModerationEvent`, e **nenhuma recusa é entregue**. O lead recebe só o texto do próprio ramo — a confirmação de opt-out, o aviso de handoff — ou nada, nos três ramos silenciosos.

Duas razões, e as duas são da regra e não da conveniência. Nos ramos #1, #2 e #3 o turno hoje não entrega nada: uma recusa ali quebraria exatamente o silêncio que a guarda existe para manter. No ramo #4 seria mandar uma segunda mensagem a quem acabou de pedir para sair, que é a violação que a RN-14.1 existe para impedir — e é o mesmo argumento que o comentário de `turno.py:1133-1149` já usa para pôr o opt-out acima da moderação.

Precedente: a D3 da TEC-295 decidiu o mesmo para a superada bloqueada — marca sem recusa própria.

Reforço no ramo #2: mesmo que quiséssemos entregar a recusa ali, a Emenda E-03 da RN-16.4 (linha 458) manda `GuardedOutbound.send` barrar tudo durante atendimento humano exceto `KIND_DA_CONFIRMACAO_DE_OPTOUT`. A recusa seria barrada na saída. Entregá-la exigiria abrir uma segunda escotilha naquela guarda, e a própria E-03 registra que a primeira só existe porque a decisão "barra tudo" estava errada num caso previsto pela LGPD — não é precedente para abrir a segunda.

**A marca não destrói a evidência de opt-out.** A RN-14.2 (linha 409) exige que o opt-out seja registrado *"com timestamp, canal e conteúdo original — é evidência de LGPD"*. `marcar_bloqueada` só preenche uma coluna e insere uma linha de auditoria: o `OptoutEvent` continua referenciando `message_id` e o corpo continua cifrado em `messages`. Nada é apagado, e a evidência sobrevive inteira. Vale dizer porque a interação é o tipo de coisa que alguém "conserta" depois sem perceber que há uma regra de conformidade do outro lado.

### D3 — A operação vira uma função de domínio, usada pelos três chamadores

"Moderar entrada e marcar" está escrito duas vezes hoje, com a mesma sequência de fail-open, log e `marcar_bloqueada`. Uma terceira cópia para os cinco ramos é o erro óbvio.

Nasce em `domain/messages/bloqueio.py`, ao lado de `marcar_bloqueada`:

```python
async def moderar_entrada_e_marcar(
    session_factory, moderador, *, message_id, channel, conversation_key, corpo
) -> Veredito | None:
    """Modera a fala de entrada e, se reprovada, marca + audita no mesmo commit.

    Devolve None quando o provedor esta indisponivel -- fail-open, a
    assimetria que `domain/moderacao/port.py` documenta. Nao entrega
    recusa nenhuma: quem chama decide se ha texto a mandar.
    """
```

Passam a chamá-la: o caminho normal do turno (que segue decidindo a recusa com o `Veredito` devolvido), o `_moderar_superada` do worker (que vira uma linha), e o `finally` da D4.

Isto refatora código que a TEC-295 entregou em `c8b286a`. É deliberado: sem a extração, a lógica de fail-open e de log fica em três lugares, e a próxima correção acerta dois.

### D4 — Uma resolução, não cinco chamadas

```python
moderacao = _ModeracaoDoTurno(session_factory, moderador, message, corpo)
try:
    ...                                      # os cinco returns ficam intactos
    veredito = await moderacao.resolver()    # na 1311, decide a recusa como hoje
    ...
finally:
    await moderacao.resolver_no_fim()        # no-op se alguem ja resolveu
```

`_ModeracaoDoTurno` é privada de `turno.py`, e não vai para `domain/messages/`: ela carrega estado de um turno — o veredito memorizado e o `_resolvida` — e não tem sentido fora dele. O que é compartilhado é a função da D3, que ela chama. A divisão é essa: a operação no domínio, a memória no turno.

`resolver()` memoriza o veredito e a segunda chamada em diante é no-op. Os cinco returns antecipados não são tocados: o `finally` os cobre. Os returns **depois** da 1311 — `_continuar_entrega` (1468), `"sem_resposta"` (1498) — caem no no-op, que é o mecanismo funcionando.

**Por que `finally` e não uma chamada antes de cada `return`:** cinco sítios que precisam ser lembrados é a forma que já apodreceu duas vezes neste arquivo. A TEC-128 enumerou três exceções e a quarta ficou de fora; a TEC-295 enumerou dois ramos e havia cinco. Um sexto ramo futuro nasce coberto pelo `finally` e nasceria furado por uma lista.

### D5 — O `finally` roda mesmo com o turno falhando, e não mascara a exceção

`marcar_bloqueada` propaga exceção de propósito — a docstring de `bloqueio.py` explica por quê. Mas propagar de dentro de um `finally` substituiria a exceção real do turno, e `last_error` guardaria a classe errada.

- **Sem exceção em voo:** deixa propagar. Preserva o contrato de `bloqueio.py`; o turno vira `FAILED`, o sweeper retenta, a marca sai depois.
- **Com exceção em voo** (`sys.exc_info()[0] is not None`): engole e loga `moderacao.marca_falhou`. A exceção original chega inteira ao `last_error`.

O `finally` roda no caminho de erro **de propósito**: uma mensagem que esgota as cinco tentativas nunca mais é visitada, e sem isso a fala ficaria sem marca para sempre. O preço é US$ 0,00057 num caminho que já falhou.

### D6 — O custo, dito inteiro

Três caminhos que hoje custam zero passam a custar uma moderação cada: os ramos #1, #2 e #3. O de maior volume é o #2 — toda mensagem escrita enquanto um handoff está aberto. A US$ 0,57 por mil, é o mesmo preço que a TEC-295 aceitou pagar na rajada, e não houve alternativa mais barata que preservasse a garantia.

### D7 — O que NÃO muda

- Os quatro leitores de `bloqueada_em` não mudam: já filtram `bloqueada_em IS NULL` e passam a receber a marca que faltava.
- A ordem das cinco guardas não muda. Nenhuma delas desce nem sobe.
- A assimetria fail-open na entrada / fail-closed na saída não muda.
- O timeout de `5.0s` e as zero retentativas não mudam, e continuam constantes de módulo.
- O texto fixo de recusa continua sem passar pela moderação de saída — lacuna da TEC-233, não desta card.

## Emendas ao SRS

A numeração é por regra, não global.

**RN-04.5 → Emenda E-03.** Obrigatória: esta card muda o que a regra promete. A base diz que o discurso discriminatório na entrada *"recebe recusa educada **e** é registrado como evento de auditoria"* — uma conjunção. A D2 desacopla as duas metades: nos cinco ramos sai a auditoria sem a recusa. A emenda registra isso, a razão (a recusa quebraria o silêncio das guardas ou mandaria mensagem a quem pediu para sair), e que a moderação passa a rodar independentemente da saída que o turno tome.

**RN-02.2 → Emenda E-01.** A regra que descreve a composição do contexto do LLM, hoje sem nenhuma emenda. Registra a garantia da TEC-236, que nunca chegou ao SRS: o contexto exclui a fala que a moderação de entrada bloqueou, o resumo permanente herda por construção porque `dividir` recebe o que `literais_apos` devolve, e desde a TEC-295 o score e a âncora de follow-up usam a mesma definição de fala do lead. Sem ela, esta card se justifica por uma garantia que nenhuma regra enuncia.

## As garantias a não reabrir

Além das quatro que a TEC-295 listou, esta card acrescenta uma:

1. **(TEC-233)** A fala reprovada na entrada nunca vira a resposta daquele turno.
2. **(TEC-236)** A fala reprovada nunca entra em contexto de turno nenhum nem no resumo permanente.
3. **(TEC-236/TEC-142)** Marca e auditoria saem no mesmo commit.
4. **(TEC-150/cadência)** Score, follow-up e `ha_fala_pendente_antes` usam a mesma definição de fala do lead — `direction=INBOUND AND bloqueada_em IS NULL` — e continuam concordando com a janela quanto a `bloqueada_em`.
5. **(TEC-143/CA-04.3)** O handoff do pedido explícito continua nascendo sem esperar chamada paga.

Sobre a garantia 4, uma precisão que a prosa existente induz ao erro: `literais_apos` **não** filtra `direction`, e não deve — ela devolve as duas direções porque é a janela de contexto. A concordância entre os quatro leitores é sobre `bloqueada_em IS NULL`; o `direction = INBOUND` vale para os três de "fala do lead". Os comentários em `followup/repositorio.py:60-63`, `messages/rajada.py:73-76` e `context/score.py:102-114` dizem "as leituras têm de concordar" sem essa ressalva, e alguém pode ler isso como convite a pôr um filtro de `direction` em `literais_apos`, o que quebraria o contexto.

## Testes

| teste | o que prova |
| --- | --- |
| parametrizado nos cinco desfechos: fala reprovável recebe `bloqueada_em` + `ModerationEvent` | o objetivo da card, sem enumerar ramo em prosa de teste |
| parametrizado nos cinco: a fala não aparece em `literais_apos` | a garantia 2 pela janela real, não pelo desfecho |
| nenhum OUTBOUND com `KIND_DA_RECUSA_DE_ENTRADA` nos cinco | a D2 |
| o handoff já existe quando o moderador é chamado | a garantia 5 e a D1 — moderador falso consulta o banco ao ser chamado |
| ação do ramo acontece com moderação indisponível | fail-open; handoff e opt-out não dependem do provedor |
| moderador chamado exatamente uma vez por turno | a D4, no caminho normal e nos cinco |
| fala liberada continua entrando no contexto nos cinco ramos | que a D1 não fecha o caminho comum |
| turno que levanta exceção: `last_error` guarda a classe original | a D5 |
| mensagem sem corpo: zero chamadas ao moderador | que o `if corpo` continua valendo |

`test_pedido_de_humano_passa_antes_da_moderacao_de_entrada` continua passando: a ordem que ele trava é preservada e reforçada.

## Fora de escopo

- **A entrega parcial da TEC-275** não precisa de nada: ela não retorna cedo e já cai na moderação normal do turno.
- **Nenhuma mudança na janela do debounce**, no `superada_por_mais_nova` ou nas exceções da TEC-128.
- **Ancorar os 5 segundos da Emenda E-04 da RN-16.1.** A emenda não diz de onde até onde, e a CA-04.3 é a única definição operacional. Emendar isso é card própria; este desenho apenas usa a CA-04.3 como a leitura defensável.
- **O `bloqueada_em` sem índice.** Os quatro leitores filtram pelo par `(channel, conversation_key)` e resolvem a coluna como filtro residual. Nada nesta card muda o volume dessas consultas.
- **Os itens 3, 4 e 6 do comentário de fechamento da TEC-295** (limite de recência de `ha_fala_pendente_antes`, instrução ao modelo sobre a pergunta pendente, a lista de trilhas de `_entregar_texto_fixo`). Continuam sem card.
