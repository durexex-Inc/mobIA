# TEC-279 — Levantar o handoff que ficou sem prazo porque a fila engoliu o enfileiramento

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-279](https://eduardodurieuxlopes.atlassian.net/browse/TEC-279) — História, Should (MoSCoW), prioridade High. Origem: lacuna **L6** do desenho da TEC-178, aberta pela revisão final daquela branch. Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Anelise, gerente comercial, quero que um lead esquecido apareça mesmo quando a falha foi da infraestrutura, para que a rede de segurança não dependa justamente da peça que falhou."*

## Objetivo

A varredura da TEC-178 é a rede de segurança do épico, e ela exige `sla_limite_em IS NOT NULL`. O prazo é gravado no job de notificação. **Se o enfileiramento falha, o prazo nunca existe, e a rede não enxerga o handoff.** A rede depende da peça que falhou.

O resultado é o *"um handoff que ninguém viu fica parado, e nada o levanta"* que abre o Objetivo da TEC-178 — chegando por uma porta que aquele desenho não cobria.

## O que a exploração descobriu

**São dois pontos de engolimento, e a card só nomeia um.** E há um terceiro modo que ela não prevê.

| Onde | O que se perde | A card nomeia? |
|---|---|---|
| `turno.py:350`, `_agendar_resumo` | resumo, notificação e prazo — o handoff nasce e nada mais acontece | de passagem |
| `gerar_resumo.py:46` | notificação e prazo; o resumo existe | sim |
| o job é enfileirado e o worker nunca o roda (worker caído, `max_tries` esgotado) | notificação e prazo | **não** |

Os três terminam no **mesmo estado**. Isso decide a D1: o critério não pode ser sobre qual falha aconteceu.

## Decisões

### D1 — O critério é o estado, e ele já existe em colunas que ninguém lê

```
status = 'PENDENTE'
AND sla_limite_em IS NULL
AND notificado_em IS NULL
AND aviso_manual_pendente = false
AND criado_em < agora - INTERVALO_DE_RECUPERACAO
```

As três condições do meio dizem, juntas, uma coisa só: **`notificar` nunca chegou a decidir nada sobre este handoff.** Ele grava `sla_limite_em` cedo e `notificado_em`/`aviso_manual_pendente` no fim; nenhum dos três preenchido significa que a função não rodou. Um handoff em que `notificar` rodou e falhou a entrega tem `aviso_manual_pendente = true` e **não** é recuperado — aquilo não é um handoff perdido, é um handoff que o sistema já viu.

**Isto dá a `notificado_em` e `aviso_manual_pendente` o primeiro leitor da vida delas.** O Objetivo do desenho da TEC-178 prometeu exatamente isso — *"dar leitor às duas colunas que a TEC-177 criou e a ninguém entregou"* — e não entregou: a revisão final da TEC-179 verificou por busca que nada em `src/` as lê. Esta card fecha aquela ponta, um épico depois.

### D2 — Três dos quatro cenários do Gherkin passam por construção

- **Handoff sem destinatário não é recuperado:** `notificar` marca `ESCALADO` naquele caminho (emenda E-02 da RN-16.3), e `status = 'PENDENTE'` já o filtra.
- **Handoff recém-criado não é recuperado cedo demais:** é o `criado_em < agora - INTERVALO`.
- **A recuperação não duplica notificação:** é o `notificado_em IS NULL`.

Nenhum dos três precisa de código próprio. Os testes existem para provar que continuam assim, não para construir nada.

### D3 — Reenfileira, e escolhe o job pelo resumo

- `resumo IS NULL` → reenfileira **`gerar_resumo`**. Ele gera o resumo e, ao terminar, enfileira `notificar` — é o caminho inteiro.
- `resumo` preenchido → reenfileira **`notificar`** direto.

A ramificação não é zelo: **`gerar_resumo` não checa se o resumo já existe** — ele carrega o dossiê e chama o redator incondicionalmente. Reenfileirá-lo sobre um handoff que já tem resumo pagaria uma segunda chamada ao provedor por nada.

E o contrário — reenfileirar sempre `notificar` — perderia o resumo para sempre no primeiro caso. O corretor receberia o `TEXTO_SEM_RESUMO`, que é o caminho degradado da D2 da TEC-177: legítimo quando o resumo falhou de verdade, indevido quando ele nem foi tentado.

### D4 — Nunca desiste, e não guarda contador

A varredura reenfileira em toda passagem enquanto o estado persistir. Sem coluna de tentativas, sem desistência, sem escalada por esgotamento.

Se o Redis está fora, o sistema inteiro parou — o webhook grava mas não enfileira, os workers não consomem. Uma tentativa a cada cinco minutos por handoff preso é barata diante disso, e some sozinha quando o Redis voltar.

A alternativa (desistir e escalar ao gerente) pagaria estado novo por um aviso que **ninguém receberia**: os canais não entregam. E depois da TEC-278 um `ESCALADO` prende a conversa até alguém assumir e devolver — transformar uma falha transitória de Redis nisso seria pior que o problema.

Decisão do Eduardo em 13/09/2026.

### D5 — O intervalo é de 10 minutos

Folgado o bastante para o caminho normal concluir mesmo com o provedor lento e uma retentativa do ARQ — reenfileirar um job que ainda ia rodar é o risco de um limiar curto, e o `_job_id` fixo só protege enquanto o job original está vivo.

Decisão do Eduardo em 13/09/2026.

### D6 — Mora no domínio com uma porta, e entra no `sweep_sla`

`src/mobia/domain/handoff/recuperacao.py`, no molde de `escalar_vencidos`: recebe o `session_factory` e uma porta, devolve quantos recuperou.

`ReenfileiradorPort` tem dois métodos — `agendar_resumo` e `agendar_notificacao` — porque a D3 precisa escolher entre dois jobs. Poderia usar `ctx["redis"]` direto no arquivo do job, que é o que `gerar_resumo` faz; a porta existe porque é ela que permite ao teste assertar **qual job foi enfileirado para qual handoff** sem um dublê de Redis, e essa asserção é a única prova da D3.

Entra no `sweep_sla`, que já roda de cinco em cinco minutos e já é a rede de segurança do épico. Não é cron nova.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Handoff sem prazo e sem notificação é recuperado | exercitado, nos dois ramos da D3 |
| Handoff recém-criado não é recuperado cedo demais | **por construção** (D2) |
| Handoff sem destinatário não é recuperado | **por construção** (D2) |
| A recuperação não duplica notificação | **por construção** (D2) |

## Lacunas declaradas

### L1 — A recuperação notifica; para o corretor e a gerente isso é invisível, para o lead não é

O primeiro cenário diz *"então o handoff é notificado ou levado ao gerente, e deixa de estar invisível"*. Ele deixa de estar invisível **no banco**: ganha prazo, entra na varredura de SLA, pode ser escalado.

Para o **corretor** e para a **gerente**, continua invisível: a emenda E-02 da RN-16.2 declara que os dois canais de `canais.py` (`EmailRegistrado`/`WhatsAppRegistrado`) só registram, não entregam, e não há painel.

Para o **lead**, não. `notificar` termina chamando `_avisar_lead_da_janela_humana` (`domain/notificacao/envio.py:274`), que roda independente de qualquer canal ter aceitado e envia pelo `ctx["outbound"]` — em produção o `WhatsAppOutbound` real (`domain/outbound/whatsapp.py`, `workers/main.py:79`), que entrega de verdade pela Cloud API da Meta. Um handoff preso seis horas (Redis fora durante a noite, por exemplo) faz o lead receber o texto da janela humana seis horas depois de ter pedido um atendimento humano — sem nada antes disso. Combinado com a **L4** (sem teto de idade), a primeira passagem depois de um deploy sobre um banco com handoffs presos dispara essa mensagem para todos eles de uma vez.

Atenuante: a janela de 24h da Meta (`CODIGO_FORA_DA_JANELA = 131047`) recusa a mensagem livre quando o lead não fala há mais de um dia, o que limita o efeito prático a essa faixa (10 minutos a 24 horas) em vez de qualquer atraso. Isso não anula o ponto — só o limita.

**É a quarta card seguida do épico a entregar estado sem leitor humano para o corretor e a gerente** — e aqui a ironia é própria: a card existe para que um handoff perdido volte a ser visto, e o que ele volta a ser, para essas duas pessoas, é visto pelo Postgres. Para o lead, a recuperação tem um efeito real e pode chegar tarde demais para ser útil. Se isso não for desejado (por exemplo, gatear `_avisar_lead_da_janela_humana` por idade do handoff), a decisão é de produto, e é outra card.

### L2 — Nada recupera o handoff cujo `notificar` rodou e falhou no meio

`notificar` grava `sla_limite_em` cedo e `notificado_em` no fim. Se ele morrer entre os dois, o handoff fica com prazo e sem notificação — e a D1 **não** o recupera, porque `sla_limite_em IS NULL` é falso.

Isso é deliberado e não é buraco: com prazo gravado, ele é visível para a varredura de SLA da TEC-178, que o escalará quando vencer. O lead não some. O que se perde é a notificação ao corretor destinatário — ele nunca saberá; só o gerente, na escalada.

### L3 — O resumo perdido no primeiro ramo custa uma chamada ao provedor

Quando `_agendar_resumo` falha, a D3 reenfileira `gerar_resumo`, que paga a chamada que a falha impediu. É o preço certo — o alternativo é o corretor receber `TEXTO_SEM_RESUMO` sobre um lead cujo resumo nunca foi tentado —, mas é custo que a card introduz e que não existia antes.

### L4 — Não há limite superior de idade

A varredura pega qualquer handoff no estado, por mais velho que seja. Num banco com handoffs perdidos de meses atrás, a primeira passagem depois do deploy os recupera todos de uma vez — cada um pagando uma chamada ao provedor se estiver sem resumo.

O teto de `limite=100` por passagem contém o pico, mas não o total. O desenho aceita isso porque o épico nunca rodou em produção e o estado não existe.

## Fora de escopo

Tornar o enfileiramento transacional com a gravação do handoff — é o que eliminaria a classe inteira, e é outra card. A estratégia de retentativa entre provedores (E9). A entrega pelos canais. O painel (E8).
