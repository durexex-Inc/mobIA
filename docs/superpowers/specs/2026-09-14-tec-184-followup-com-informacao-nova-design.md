# TEC-184 — O follow-up traz informação nova

**Status:** desenhado em 2026-09-14.

**Card:** [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184) — História, Should (MoSCoW), prioridade High. Origem: RF-13, RN-13.2 (SRS v1.0); RN-B02. Épico [TEC-181](https://eduardodurieuxlopes.atlassian.net/browse/TEC-181). Bloqueada pela [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) (Feito).

**A história:** *"Como Marina, quero que a mensagem de retorno me traga algo útil, para não sentir que estou sendo perseguida por um robô carente."*

## Objetivo

A TEC-183 entregou a régua da cadência: `sweep_followups` descobre quem está devido, grava a tentativa em `followups` e emite `followup.devido`. **Nada é enviado ao lead** — o docstring daquele job diz isso por extenso e explica por quê: a RN-13.2 proíbe follow-up sem informação nova, e um texto provisório violaria a regra de frente.

Esta card fecha isso: escolhe a informação nova, monta a mensagem e a entrega.

## O que a exploração descobriu, e que muda o desenho

**O preço histórico já está gravado, e com a razão certa.** `Recomendacao.preco_centavos` guarda o número que o lead viu, e o comentário da coluna (TEC-275, D3) já declara: *"Isto NÃO é uma segunda cópia do preço do imóvel: é um fato histórico sobre o que foi apresentado, e continua certo depois de o preço do imóvel mudar."* Comparar essa coluna contra `imoveis.preco_venda` de hoje detecta queda de preço **sem tabela de histórico nenhuma**. Ver a D2.

**Só 1 das 9 posições da cadência cabe na janela de 24 horas do WhatsApp.**

| temperatura | tentativas (RN-13.1) | dentro da janela |
|---|---|---|
| QUENTE | 2h, 24h, 3d, 7d | **1** (a de 2h) |
| MORNO | 24h, 4d, 10d | 0 |
| FRIO | 3d, 14d | 0 |

Fora da janela a Meta recusa texto livre, e `outbound/whatsapp.py` já converte o código de erro dela em `EnvioForaDaJanela`. Texto por template aprovado é a TEC-186, que a própria card põe fora de escopo. Ver a L1 — é a maior consequência desta card.

**A porta de saída reserva por `message_id`, e o follow-up não responde a mensagem nenhuma.** `outbound_dispatches` tem `UNIQUE (message_id, kind)` com FK para `messages`, e as guardas de opt-out e de conversa silenciada resolvem o lead **pela mensagem**. Um follow-up não é resposta — mas a âncora da cadência *é* o `created_at` de uma mensagem real do lead. Ver a D1.

**O lead já tem critérios gravados.** `lead_qualification` carrega `regiao`, `tipo_imovel`, `faixa_preco_min/max_centavos`, `quartos` e `vagas` — o suficiente para remontar um `FiltroDeBusca` sem inventar nada.

**A guarda de citação já existe.** `domain/agente/citacao.py` (TEC-161) valida que a prosa do modelo só cite imóvel que veio da busca. Ver a D5.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `sweep_followups` | grava a tentativa e emite evento; **não envia** | objetivo |
| `Recomendacao.preco_centavos` | preço histórico do que foi apresentado | D2 |
| `lead_qualification` | critérios do lead, nuláveis | D2 |
| `outbound_dispatches` | `UNIQUE (message_id, kind)`, FK para `messages` | D1 |
| `Candidato` (followup) | tem `ancora_em`, **não** tem o id da mensagem-âncora | D1 |
| `legenda_de` / `reais_de` | ficha pronta, teto de 600 respeitado por construção | D3 |
| `citacao.py` | guarda de citação da TEC-161 | D5 |
| `EnvioForaDaJanela` | levantada pelo adaptador quando a Meta recusa | L1 |
| `job_timeout` do ARQ | 240 s, já apertado (Emenda E-01 da RN-09.4) | D7 |

## Decisões

### D1 — A mensagem se ancora na última fala do lead

`kind = followup_<n>`, e `message_id` = o id da mensagem que é a âncora da cadência.

Três coisas saem de graça, e é por isso que esta é a escolha e não uma tabela nova:

- **Idempotência por tentativa.** A `UNIQUE (message_id, kind)` de `outbound_dispatches` espelha exatamente a `UNIQUE (channel, conversation_key, ancora_em, tentativa_numero)` de `followups`. Duas varreduras concorrentes não conseguem mandar a mesma tentativa duas vezes.
- **As guardas de opt-out e silêncio funcionam sem uma linha de mudança.** Elas resolvem o lead pela mensagem (`esta_em_optout_por_mensagem`, `esta_silenciada_por_mensagem`), e a mensagem-âncora é do lead certo.
- **A reserva sobrevive a crash no meio do envio**, com a mesma semântica de liberação que a resposta normal já tem.

`Candidato` ganha `ancora_message_id`. A agregação que o produz já agrupa sobre `messages` — o id sai da mesma consulta, não de uma segunda.

### D2 — A informação nova é escolhida por código, em ordem fixa

Três fontes; a primeira que existir ganha, e só uma entra na mensagem.

**1. Queda de preço em imóvel já apresentado.** `recomendacoes.preco_centavos` contra `imoveis.preco_venda` de hoje, para os imóveis desta conversa. **Só queda.**

A regra de negócio da card diz *"mudança de preço"* e o Gherkin diz *"uma redução de preço"*. A card se contradiz, e a decisão é seguir o Gherkin: aumento não reengaja — é um motivo a mais para o lead sumir, e a história pede que a mensagem *"traga algo útil"*. Se o preço subiu e não há outra novidade, cai no convite. Divergência declarada.

**2. Imóvel novo compatível.** `FiltroDeBusca` remontado a partir de `lead_qualification`, com dois filtros a mais: `imoveis.created_at > ancora_em` e exclusão do que já foi apresentado a esta conversa (a `UNIQUE (channel, conversation_key, imovel_id)` de `recomendacoes` torna isso uma consulta, não uma inferência).

**3. Convite para agendar.** O fallback que a card exige, e o único vivo — ver a L2.

**Queda vence imóvel novo** porque é sobre algo em que o lead **já** demonstrou interesse; um anúncio que ele nunca viu é aposta mais fraca. **Uma fonte por mensagem**, e não as duas: duas fichas num follow-up é a parede de texto que a RN-04.2 existe para evitar, e a card pede *"informação nova"*, no singular.

### D3 — A ficha é reusada, não reescrita

`legenda_de` e `reais_de` (`domain/agente/apresentacao.py`) já montam a ficha e já respeitam os 600 caracteres por construção. O follow-up de imóvel novo usa a ficha inteira; o de queda de preço acrescenta uma linha:

```
De R$ 620.000 por R$ 590.000
```

Reescrever o formato aqui criaria uma segunda fonte para "como um imóvel é mostrado ao lead", que é o defeito que a TEC-146 gastou uma card inteira consertando.

### D4 — O modelo escreve só a abertura

Híbrido, exatamente como a apresentação: o código escolhe e renderiza o fato, e o modelo escreve uma linha de contexto que entra como **prefixo**, cortada primeiro quando o teto aperta. O contexto da conversa que a card pede (*"gerado com o contexto da conversa"*) é o resumo já gravado em `conversation_summaries`.

Número de preço nunca passa pelo modelo. É a mesma postura da D7 da TEC-265 e da D8 da TEC-154, pela terceira vez: número no prompt convida o modelo a repeti-lo errado, arredondado, ou como promessa.

### D5 — A guarda de citação da TEC-161 passa a valer aqui

O imóvel citado existe no catálogo **por construção** — quem o escolheu foi o código, a partir de uma linha do banco. A guarda de `citacao.py` cobre o caso restante: o modelo inventar um segundo imóvel na abertura. É o *"cita apenas imóveis validados pelo catálogo"* da card, sem escrever validação nova.

### D6 — A mensagem vazia deixa de ser bloqueada e passa a ser impossível

Sempre há um fato: no pior caso, o convite para agendar. Então a mensagem nunca sai vazia, e não há envio a bloquear.

O que a guarda faz de verdade é **descartar a prosa** quando o modelo devolve só saudação — o bloco de fato sai sozinho. Isso atende o espírito do cenário 4 (*"não é uma saudação sem conteúdo"*) e **não** a letra dele (*"Então o envio é bloqueado"*). Divergência declarada.

Tornar o estado ruim irrepresentável, em vez de detectá-lo, é a mesma escolha que a D4 da TEC-153 fez com o perfil e a D1 da TEC-154 com `Rentabilidade`.

### D7 — O sweep ganha um teto de envios por execução

Hoje o laço é barato: quatro guardas puras e duas consultas por candidato. Passando a fazer uma chamada de modelo e uma de API por candidato, com `limite=500`, um acúmulo — primeiro deploy, ou volta de indisponibilidade — estoura o `job_timeout` de 240 s, que a Emenda E-01 da RN-09.4 já registra como apertado.

O teto corta em **25 envios por execução**. Quem sobra **continua devido** e entra na próxima varredura, cinco minutos depois: a cadência é ancorada e não encadeada (docstring de `cadencia.py`), então nada se desloca por causa do atraso. O teto vive uma vez, como constante do módulo do job.

**De onde vem o 25, e o que ele não é.** Não é medição — a chamada que ele limita ainda não existe. É um limite derivado do `job_timeout = 240 s`: supondo ~4 s de pior caso por follow-up (uma chamada de prosa com `max_tokens` pequeno, mais o POST para a Meta), 25 envios são ~100 s, menos da metade do orçamento, deixando o resto para a agregação que produz os candidatos e para a variância da rede. **Quem medir o custo real deve corrigir este número** — e a direção certa é medir, não subir por intuição quando a varredura parecer lenta. Com 25 por execução e uma varredura a cada 5 minutos, a vazão é de 300 follow-ups por hora, muito acima de qualquer acúmulo plausível deste sistema.

**Correção posterior à implementação.** A estimativa de ~4 s por follow-up acima está errada, e a implementação a falsificou: o cliente do provedor de modelo (`infra/anthropic.py`) tem `TIMEOUT_SEGUNDOS = 60.0` e `MAX_TENTATIVAS = 1`, ou seja, até **120 s** por chamada de `redigir_abertura` (primeira tentativa mais uma retentativa), e não os poucos segundos que a conta original supunha para "uma chamada de prosa com `max_tokens` pequeno". Com isso, o pior caso de 25 envios não é ~100 s — é **~3250 s** contra um `job_timeout` de 240 s, e um teto de contagem sozinho não protege o orçamento de tempo que ele foi desenhado para proteger. O código ganhou um segundo teto, `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS` (`workers/jobs/sweep_followups.py`), checado no topo do laço de envio: como mais um candidato inteiro pode começar logo depois da checagem passar, o tempo total no pior caso é o teto mais um candidato. `MAXIMO_DE_ENVIOS_POR_EXECUCAO = 25` continua valendo, mas só como limite de **volume** por passagem — quem corrigir esta conta com uma medição real deve revisar `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS`, não o 25, porque é aquela constante que hoje garante o corte dentro do `job_timeout`.

**Segunda correção (revisão final).** A conta `110 + 130 = 240` que esta decisão registrava era falsa, e o próprio código a desmentia: os ~130 s somam **apenas os dois clientes externos**. Depois da checagem no topo do laço, o candidato ainda paga `esta_em_optout`, `esta_silenciada`, `registrar_followup` mais o commit, as três consultas de `_novidade_do_followup`, a sessão de `fichas_do_catalogo`, o `ler_resumo`, o `scalar` do `de` e as três sessões próprias que `GuardedOutbound.send` abre — nada disso entrava na soma. Um teto que fecha em **igualdade exata** sobre uma soma incompleta não fica sem margem: fica com margem negativa.

O teto passou de 110 para **90 s**, pela conta honesta 240 (`job_timeout`) − 130 (os dois clientes externos) − 20 = 90, em que os 20 s são uma **reserva declarada** para o custo de banco do candidato — e não uma medição, porque ninguém mediu, e é por isso que ela é generosa em vez de justa. A conta viva mora no comentário da constante, em uma cópia só; este parágrafo registra por que ela mudou. Continua valendo que quem medir o custo real deve corrigir `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS`, e não o 25.

## Lacunas declaradas

**L1 — Hoje só a tentativa de 2h do QUENTE chega ao lead.** As outras oito posições da cadência estão fora da janela de 24 horas e a Meta as recusa. **A tentativa fica registrada e consumida** — `followups` é append-only e a linha é gravada antes do envio, então ela não é reentregue quando a TEC-186 entrar. Consequência prática: **MORNO e FRIO não recebem follow-up nenhum até a TEC-186**, e os leads que passarem pela cadência nesse intervalo perdem aquelas tentativas para sempre.

Decorre disto um custo recorrente aceito de propósito: como a recusa só aparece quando a Meta responde, essas oito posições **pagam uma chamada de modelo e uma de API** para produzir uma mensagem rejeitada. Mantém todo o caminho exercitado e vira valor no dia em que a TEC-186 entrar; até lá, é desperdício medido e conhecido.

**L2 — "Tarefa para o corretor" não é entregável.** A regra de negócio oferece isso como alternativa ao convite quando não há novidade. Quem notifica corretor é a TEC-280/TEC-281, ambas abertas — então o convite é o único caminho vivo, e a alternativa da card fica sem implementação.

**L3 — A queda de preço só enxerga imóvel que já foi apresentado.** Sem linha em `recomendacoes` não há preço de referência, e o `updated_at` de `imoveis` diz que algo mudou, não o que era antes. Um lead que nunca recebeu ficha não tem essa fonte — para ele, sobram imóvel novo e convite.

## Emendas ao SRS

**RN-13.2 — Emenda E-01 (TEC-184, 14/09/2026).** (A regra não tinha emenda até esta card.) A regra manda que o follow-up traga informação nova e proíbe mensagem vazia. Fica fixado que: a informação nova é escolhida **por código**, numa ordem fixa (queda de preço, depois imóvel novo compatível, depois convite para agendar), e que **só queda** de preço qualifica — a regra de negócio da card diz "mudança" e o critério de aceite diz "redução", e aumento de preço não reengaja. Fica declarado também que a mensagem vazia é **irrepresentável** e não bloqueada: como o convite é sempre uma alternativa, a geração nunca produz mensagem sem conteúdo; o que a validação descarta é a prosa do modelo, não o envio.

## Testes

Unitários, sem Docker:

- A escolha do fato: queda vence imóvel novo vence convite.
- Aumento de preço **não** produz follow-up de preço — cai para a próxima fonte.
- A linha `De R$ 620.000 por R$ 590.000`, com `reais_de` truncando para baixo dos dois lados.
- Prosa que é só saudação é descartada, e o fato sai sozinho.
- O teto de 600 com o bloco dentro: a prosa cede, o fato não.

Integração:

- Queda detectada contra `recomendacoes.preco_centavos`, e não contra o `preco_venda` de hoje dos dois lados.
- Imóvel novo filtrado por `created_at > ancora_em` e excluindo o já apresentado.
- O sweep enviando pela porta com `kind=followup_<n>`, e a segunda varredura não reenviando (a `UNIQUE` absorve).
- `EnvioForaDaJanela` vira log e não derruba o lote; a linha de `followups` permanece.
- O teto de envios por execução: o excedente continua devido na varredura seguinte.
