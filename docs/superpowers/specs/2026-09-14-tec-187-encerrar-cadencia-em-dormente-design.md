# TEC-187 — Encerrar a cadência e marcar o lead como DORMENTE

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187) — Should (MoSCoW), origem RF-13 / RN-13.5 (SRS v1.0)
**Branch:** `feat/tec-187-encerrar-cadencia-em-dormente`
**Destravada por:** [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) (a cadência derivada), [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) (a temperatura), [TEC-182](https://eduardodurieuxlopes.atlassian.net/browse/TEC-182) (o opt-out)
**Destrava:** [TEC-189](https://eduardodurieuxlopes.atlassian.net/browse/TEC-189) (dashboard) e a campanha manual do épico E8

## Objetivo

A RN-13.5 diz que, esgotadas as tentativas sem resposta, o lead vira `DORMENTE`, sai da cadência automática e permanece elegível a campanha manual pelo dashboard.

**Metade disso já é verdade e ninguém a nomeou.** Desde a TEC-183 o lead que esgotou a cadência sai da automação por aritmética: o corte `WHERE ja_disparada < CASE temperatura ... END` (`domain/followup/repositorio.py:209`) simplesmente para de devolvê-lo. O que falta é o rótulo — e a consulta que o torna segmentável. A própria card diz onde está o valor: *"funciona, mas ninguém consegue segmentar a base depois"*.

Esta card, portanto, **não muda comportamento de envio nenhum**. Ela dá nome, sinal e consulta a um estado que o sistema já produz.

## O estado de hoje

| Peça | Estado | Consequência |
| --- | --- | --- |
| Status do lead (`NOVO`, `EM_CONVERSA`, `QUALIFICADO`, `AGENDADO`, `HANDOFF`, `DORMENTE`, `DESCARTADO`) | **Não existe em código.** A linha 738 do SRS (dicionário de dados, entidade Lead) é o único lugar do repositório onde esses nomes aparecem, e é documento | `D1` — `DORMENTE` nasce derivado, e o enum de sete valores não é criado aqui (`L1`) |
| `Temperatura` (`context/temperatura.py:27`) | Existe, três valores, persistida em `lead_qualification.temperatura` como `String(8)` | É o único vocabulário de estado do lead que existe; não comporta `DORMENTE` nem `EM_CONVERSA` |
| Esgotamento da cadência | Invisível. O lead some da candidatura em `repositorio.py:209` e nada é gravado | `D1`, `D3` |
| Data e contagem da transição | **Já gravadas.** A linha de `followups` da última tentativa tem `created_at` e `tentativa_numero` (`followup/models.py:26-72`) | `D2` — a card não precisa de tabela nova |
| Reinício ao lead responder | Já acontece, sem código: a fala move `ancora_em`, e `MAX`/`COUNT` filtrados por âncora voltam a zero (Emenda E-01 da RN-13.4) | `D4` — a reativação sai de graça |
| Listagem de leads | **Não existe.** Nem rota `GET /leads`, nem função de repositório que liste; só leituras por par `(channel, conversation_key)` | `D2` entrega a função; `L2` declara que a rota não vem |
| Dashboard | Não existe (TEC-189) | `L2` — o cenário 3 da card fica parcialmente exercitado |

## Decisões

### D1 — `DORMENTE` é derivado, e a régua já está no SQL

Nenhuma coluna, nenhuma migration, `alembic` continua em `0033`. Uma função pura em `domain/followup/cadencia.py`, ao lado de `tentativa_devida`:

```python
def esta_dormente(*, temperatura: Temperatura, ja_disparada: int) -> bool:
    return ja_disparada >= len(CADENCIA[temperatura])
```

Três razões, nesta ordem.

**A primeira é que o estado já é derivado — persistí-lo criaria uma segunda fonte.** Esta expressão é a **negação exata** do corte de candidatura em `repositorio.py:209`. E não são duas verdades que podem divergir: o `CASE` daquele SQL é *gerado* a partir de `CADENCIA` por `_TETOS_POR_TEMPERATURA` (`:133-136`) e `_CASE_TETO_POR_TEMPERATURA` (`:147-150`), pela mesma razão que `INTERVALO_MINIMO` (`cadencia.py:52`) é derivado e não escrito à mão. A função lê o mesmo dict. Alongar `CADENCIA` move os três juntos.

**A segunda é o precedente do repositório.** O opt-out é derivado do último evento (`optout/repositorio.py:72-89`), a cadência é derivada da âncora (Emenda E-01 da RN-13.4). Uma coluna `status` carimbada afirmaria, num segundo lugar, o que `followups` já afirma — e este repositório trata afirmação desatualizada como defeito, não como sujeira.

**A terceira é que a reativação some.** Uma coluna exigiria código novo no caminho quente da ingestão para limpá-la quando o lead responde. Derivado, não há o que limpar: ver `D4`.

**Sobre a reversibilidade que a TEC-183 documentou.** A docstring de `candidatos_a_followup` registra que o corte é reavaliado contra a temperatura viva a cada varredura, e portanto um lead que esgotou `FRIO` (2) e depois esquentasse voltaria a ser candidato às tentativas 3 e 4 **sob a mesma âncora** — o que faria um `DORMENTE` derivado se desfazer sozinho, sem o lead ter falado.

Verificado em 14/09/2026: **esse caminho não é alcançável hoje.** Existe um único gravador de `lead_qualification.temperatura` em produção, o `UPDATE` de `registrar_recalculo` (`context/repositorio.py:1147-1178`), alcançável apenas por `executar_turno` → `process_message`. Todos os insumos da decisão saem de falas INBOUND não bloqueadas do próprio lead: o score não tem decaimento nem janela de recência (dito literalmente em `context/score.py:137-141`), `imoveis_compativeis` está fixado em `0` (`context/repositorio.py:1103`, até a TEC-158), `gatilhos` vem do texto do turno, e não há cron de recálculo nem comando `admin` que escreva a coluna. Quando a temperatura muda, a âncora já se moveu pela mesma fala — e o lead já deixou de ser dormente por aritmética, antes do teto mudar.

Logo, `DORMENTE` derivado é **estável hoje**, e a instabilidade é uma consequência declarada de cards futuras, não desta (`L4`).

### D2 — `listar_dormentes` inverte o corte e reusa as CTEs da âncora

As três CTEs de `_SELECIONAR_CANDIDATOS` (`falas_do_lead`, `ultima_fala`, `candidatos`, `repositorio.py:152-206`) passam a ser uma constante de módulo compartilhada. As duas consultas diferem **só no `WHERE` final e na projeção**: `ja_disparada < CASE ...` devolve quem ainda deve receber, `ja_disparada >= CASE ...` devolve quem adormeceu. Extrair é reuso real, não abstração especulativa: sem isso seriam duas cópias de cinquenta linhas de SQL que precisam concordar sobre o que é a âncora, e a segunda cópia envelheceria sozinha.

```python
@dataclass(frozen=True)
class LeadDormente:
    channel: str
    conversation_key: str
    temperatura: Temperatura
    ancora_em: datetime
    tentativas: int          # MAX(tentativa_numero) sob a ancora
    adormeceu_em: datetime   # MAX(created_at) sob a mesma ancora
```

`tentativas` e `adormeceu_em` são a *"data e a quantidade de tentativas realizadas"* que a card exige da transição. Elas não são gravadas por esta card: são lidas da linha que a TEC-183 já grava.

**`MAX(created_at)` é a linha da última tentativa, e não por acaso.** `tentativa_devida` só devolve número maior que `ja_disparada` (`cadencia.py:97-99`), então as inserções sob uma âncora são monotônicas em `tentativa_numero`, e a linha de maior `tentativa_numero` é também a de maior `created_at`. Se um dia a régua passar a devolver tentativa intermediária, esta igualdade quebra — e o lugar de consertá-la é aqui.

**O opt-out é filtrado por candidato, em Python, e não juntado no SQL.** Fonte única: `esta_em_optout` é a função que decide o que é opt-out, e o sweep já a consulta assim (`sweep_followups.py:409-414`) — é o mesmo precedente da TEC-146, que gastou uma card inteira consertando um fato afirmado em dois lugares. A razão de excluir, e não apenas marcar: a lista existe para alimentar campanha manual, e a RN-14.3 diz que lead com opt-out só volta a ser contatado por ação humana explícita **com justificativa registrada**. Entregá-lo numa lista rotulada "elegível a campanha" convida exatamente o disparo que a RN-14.3 proíbe.

**Consequência declarada:** o `LIMIT` é aplicado no SQL, antes do filtro de opt-out, então a lista pode voltar com menos que `limite` havendo mais dormentes. É o comportamento idêntico ao de `candidatos_a_followup`, que corta em `:limite` e depois descarta candidatos nas guardas.

### D3 — O evento `followup.dormente`, emitido depois do commit

Em `workers/jobs/sweep_followups.py`, junto ao `followup.antispam_atingido` (`:502`) e **depois** do `await session.commit()` de `:452` — a mesma regra que a TEC-183 impôs ao `followup.devido` (`:471`, e a docstring de `:226` a escreve): nada é logado antes de estar gravado, porque um log que afirma um fato que a transação depois desfez é pior que log nenhum.

Dispara quando `tentativa == len(CADENCIA[candidato.temperatura])`. Diferente do `followup.antispam_atingido`, que hoje só é alcançável no `QUENTE` — porque `MAXIMO_SEM_RESPOSTA = 4` coincide com o teto daquela temperatura e `MORNO` para em 3 —, este é alcançável nas três.

**Divergência declarada em relação ao Gherkin da card.** O cenário 1 diz *"Quando a última tentativa se esgota"*. No desenho derivado esse instante **não existe**: não há tentativa pendente que expire, há uma linha que é gravada. O evento dispara no momento em que a **última tentativa é enviada**, não depois de ela ficar sem resposta. Um lead que responder dez minutos depois já terá gerado a linha de log. O efeito prático é nulo — nada age sobre o evento, e a resposta move a âncora e o tira de `DORMENTE` na varredura seguinte —, mas a linha existe e alguém vai lê-la, então está escrita aqui.

### D4 — A reativação não tem código, e `EM_CONVERSA` não é entregue

O cenário 4 da card pede que a resposta do lead devolva o status a `EM_CONVERSA`. **`EM_CONVERSA` não existe em código nenhum**, e esta card não o cria (`L1`).

O que acontece quando o lead responde: `IngestionService._persist` grava a fala INBOUND (`messages/service.py:73`), a CTE `falas_do_lead` passa a escolhê-la como `posicao = 1`, `ancora_em` muda, `MAX`/`COUNT` filtrados por `f.ancora_em = u.ancora` voltam a `0`, `esta_dormente` vira `False` e a cadência recomeça da nova âncora.

Isto é, verbatim, a segunda linha do "Então" do cenário 4 — *"uma nova cadência é calculada a partir da nova última mensagem"* — e o efeito observável da primeira. **O nome não é entregue; o comportamento é.** Divergência declarada, e a mesma forma de argumento que a Emenda E-01 da RN-13.4 usou para o cancelamento da cadência.

## Lacunas declaradas

**L1 — O enum de status do lead continua não existindo.** O SRS descreve sete valores na entidade Lead (linha 738) e esta card entrega um: `DORMENTE`, derivado, sem coluna. Os outros seis (`NOVO`, `EM_CONVERSA`, `QUALIFICADO`, `AGENDADO`, `HANDOFF`, `DESCARTADO`) derivam de fatos que moram em outras tabelas e não têm dono. O desenho da TEC-147 previa que *"essa card paga a migração e reconcilia"* — ela não paga, e a razão está em `D1`: o estado que a RN-13.5 cria é justamente o que **não** precisa de coluna. Quem criar a coluna um dia herda a reconciliação inteira, não um sétimo dela.

**L2 — O cenário 3 fica parcialmente exercitado.** *"A gerente filtra a base por leads dormentes no dashboard"* não tem onde acontecer: não há dashboard (TEC-189) nem rota de listagem de leads. Entrega-se `listar_dormentes` no repositório, testada por integração, e nenhuma rota HTTP — mesmo precedente da TEC-182 (D6), em que `reativar` ficou sem rota porque o projeto não tem camada de autenticação e uma rota sem auth que reverte proteção de LGPD é pior que a ausência dela. Aqui o argumento é o mesmo com outro objeto: uma listagem sem auth expõe a base inteira de leads. A TEC-189 chama esta função quando existir.

**L3 — Lead com `temperatura` NULL não é candidato nem dormente.** Quem escreveu antes da TEC-151 e nunca mais falou tem `temperatura IS NULL`, é excluído da candidatura pelo `IN` (`repositorio.py:205`, lacuna 3 do desenho da TEC-183) e, pela mesma consulta, fica fora de `listar_dormentes`. Ele não está na automação nem na lista de segmentação — invisível às duas. `esta_dormente` tipa `Temperatura`, não `str | None`, e portanto não finge cobrir o caso.

**L4 — A estabilidade de `D1` é uma medição de hoje, não uma invariante.** `DORMENTE` derivado só é estável porque a temperatura não muda sem o lead falar. A TEC-158 (`imoveis_compativeis` deixa de ser `0`) e a TEC-192 (intervenção humana no score) são exatamente as cards que quebram isso: com qualquer uma delas, um lead pode esquentar calado, ganhar teto maior e deixar de ser dormente sem ter respondido. Não há guarda contra isso aqui, de propósito — o comportamento resultante (volta a receber follow-up porque agora é `QUENTE`) é o que a RN-13.1 pede ao dizer que a mudança de temperatura recalcula a cadência restante. O que muda é que o rótulo deixa de ser pegajoso, e quem construir o dashboard precisa saber disso.

## Emendas ao SRS

**Emenda E-01 (TEC-187, 14/09/2026) à RN-13.5.** A regra manda que o lead esgotado vire `DORMENTE`, saia da cadência automática e permaneça elegível a campanha manual. Fica fixado que `DORMENTE` é **estado derivado e não coluna**: o lead está dormente quando o número de tentativas já disparadas sob a âncora atual alcança o teto da sua temperatura viva, e a pergunta é respondida por função pura (`esta_dormente`) e pela consulta `listar_dormentes`, sem nenhuma escrita nova no banco. **Consequência declarada:** a coluna `status` da entidade Lead da seção 5 continua não existindo, e dos sete valores que ela lista apenas `DORMENTE` ganha significado operacional — os outros seis seguem sem dono. Fica declarado também que *"sai da cadência automática"* já era verdade desde a Emenda E-01 da RN-13.4: o corte por temperatura da consulta de candidatos deixa de devolver o lead esgotado, e esta card não altera envio nenhum. A *"data e a quantidade de tentativas realizadas"* que a transição registra não são gravadas por esta card: são o `created_at` e o `tentativa_numero` da linha de `followups` da última tentativa. A elegibilidade a campanha manual é entregue como função de repositório **sem rota HTTP**, pelo mesmo motivo da reativação de opt-out da TEC-182, e a lista **exclui** o lead com opt-out registrado, porque a RN-14.3 condiciona qualquer novo contato dele a ação humana com justificativa. Por fim, a reativação do cenário 4 da card acontece **sem código**: a resposta do lead move a âncora e a contagem sob a âncora nova começa em zero — o estado `EM_CONVERSA` que o critério nomeia não é entregue, e o efeito observável que ele descreve é.

A linha correspondente entra também na tabela-índice de emendas do topo do SRS (`| E-01 | RN-13.5 | TEC-187 | 14/09/2026 |`).

## Testes

**Unitários, sem Docker** (`tests/unit/test_cadencia.py`):

- `esta_dormente` é `False` em `teto - 1` e `True` em `teto` e `teto + 1`, para as três temperaturas — com o teto lido de `CADENCIA`, nunca escrito à mão no teste.
- `esta_dormente` é `False` com `ja_disparada = 0` nas três temperaturas (o lead que nunca recebeu nada não é dormente).
- A negação é exata: para toda temperatura e todo `ja_disparada` de 0 a 5, `esta_dormente(...)` é verdadeiro exatamente quando o corte SQL excluiria o lead. Guarda contra o corte e a função divergirem.

**Integração** (arquivo novo `tests/integration/test_listar_dormentes.py`):

- Um lead `MORNO` com 3 linhas de `followups` sob a âncora atual aparece na lista; com 2, não aparece.
- `tentativas` e `adormeceu_em` batem com a linha de maior `tentativa_numero`.
- Um lead que esgotou e **depois falou** não aparece: a âncora nova não tem linha nenhuma. É o cenário 4 da card.
- Um lead que esgotou e depois registrou opt-out não aparece.
- Um lead com `temperatura IS NULL` não aparece, mesmo tendo linhas de `followups` (é `L3`, testada para que a lacuna seja verificável e não só afirmada).
- O `followup.dormente` é emitido uma vez quando a varredura grava a tentativa que fecha o teto, e não é emitido nas anteriores (`tests/integration/test_sweep_followups.py`).

**Não coberto, e por quê:** o cenário 3 (filtrar no dashboard) não tem ponta a exercitar — ver `L2`. Nenhum teste inventa endpoint para se auto-satisfazer.

## Fora de escopo

- A ferramenta de campanha manual (épico E8) e o dashboard que a hospeda (TEC-189). Esta card entrega o rótulo e a consulta que a tornam possível, como a própria card delimita.
- A coluna `status` da entidade Lead e os outros seis valores do enum — `L1`.
- Qualquer mudança no que é enviado ou em quando é enviado. Esta card não toca `tentativa_devida`, `CADENCIA`, as guardas de horário, opt-out, silenciamento ou anti-spam.
