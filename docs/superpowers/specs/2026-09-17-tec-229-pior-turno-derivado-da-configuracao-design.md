# TEC-229 — O pior turno é derivado da configuração, e não cabe

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-229](https://eduardodurieuxlopes.atlassian.net/browse/TEC-229) — épico TEC-133
**Branch:** `feat/tec-229-pior-turno-derivado-da-configuracao`
**Card gerada:** [TEC-290](https://eduardodurieuxlopes.atlassian.net/browse/TEC-290) — fechar o orçamento que este desenho abre
**Origem:** re-review da branch `feat/tec-134-classificacao-intencao`; parte do trabalho foi absorvida pela TEC-228.

## Objetivo

Fazer o orçamento de tempo do turno dizer a verdade sobre quantas chamadas um turno pode fazer. Hoje duas afirmações convivem, as duas erradas na mesma direção: uma asserção em `tests/integration/test_worker_startup.py` que supõe duas chamadas por turno, e um `_PIOR_TURNO` em `infra/anthropic.py` que conta `resumir` e `count_tokens` uma vez cada quando o laço de montagem pode rodar ambos várias vezes.

Corrigir as duas deixa o orçamento estourado. **Isso é o entregável, não um efeito colateral** — a card diz, com todas as letras, que ficar vermelho é o sinal que o teste existe para dar.

## O que a TEC-228 já resolveu, e por que a card ainda tem conteúdo

A card é de 26/08/2026. A TEC-228 mergeou em 16/09 e entregou boa parte do que ela pedia: `tests/unit/test_orcamento_do_turno.py` soma os quatro clientes externos importando cada teto de quem o define, compara com o `job_timeout` real do `WorkerSettings`, e não escreve nenhum dos números à mão. O critério *"o pior caso é derivado da configuração"* está atendido para tudo que a TEC-228 enxergou.

Sobraram duas coisas, e a segunda é a que importa.

### A asserção que a card descreve continua lá, e piorou

`test_job_timeout_cabe_dentro_da_janela_do_sweeper` ainda tem:

```python
pior_caso_por_chamada = TIMEOUT_SEGUNDOS * (1 + MAX_TENTATIVAS)
assert pior_caso_por_chamada * 2 <= WorkerSettings.job_timeout
```

A card a descreve passando por empate exato: `120 × 2 = 240`. **Não é mais o caso.** A TEC-228 zerou `MAX_TENTATIVAS`, então a conta virou `60 × 1 × 2 = 120 ≤ 240`. O empate virou folga de 2x — e a folga é ilusória, porque o número que ela mede não governa chamada nenhuma do turno.

`TIMEOUT_SEGUNDOS` hoje é, pelo próprio comentário dele, **o piso de quem não pede teto**: `followup/prosa.py` e `handoff/resumo.py`, as duas chamadas de **fora** do turno. Quem faz uma fatia do turno manda o seu próprio teto. A asserção, portanto, afirma algo sobre o turno usando a constante que explicitamente não é a do turno, e o comentário acima dela — *"as duas chamadas pesadas do turno com dobra (resumir + classificar)"* — descreve um modelo que o código abandonou.

### O critério de pronto nº 1 não é cumprido nem pela TEC-228

A card pede: *"o teste falha se `contexto_max_iteracoes` subir"*. Hoje não falha em lugar nenhum. `_PIOR_TURNO` é uma tupla de constantes de módulo:

```python
_PIOR_TURNO = (
    (TETO_DO_COUNT_TOKENS, 1),
    (TETO_DO_RESUMO, 1),
    ...
)
```

Nenhuma das duas primeiras linhas olha para configuração. Mas `montar_contexto` (`domain/context/montagem.py`) faz:

- **uma** dobra pelo gatilho de acumulação (`deve_regenerar`), com um `resumir`;
- **uma** contagem antes do laço (`_contar_se_valer`);
- o laço `while tokens > teto`, que roda até `contexto_max_iteracoes` voltas, **cada uma com um `resumir` e uma contagem**;
- `_truncar_ate_caber`, que corta a janela pela metade a cada passo e conta a cada corte, mais uma contagem final se descartar o resumo.

É a mesma classe de erro que a TEC-228 encontrou e consertou uma camada acima: contar uma requisição onde o código faz várias. A TEC-228 pegou as duas fatias que fazem duas requisições por causa da ferramenta de busca; não pegou as duas que fazem N por causa do laço de montagem.

## A conta, com os valores de 17/09/2026

Medido rodando o código, não estimado:

| | `_PIOR_TURNO` afirma | pior caso real |
| --- | --- | --- |
| `resumir` | 1× | **4×** |
| `count_tokens` | 1× | **11×** |
| `reagir` | 1× | 1× |
| `classificar` | 2× | 2× |
| `investidor` | 2× | 2× |
| **Anthropic** | 162s | **287s** |
| embed + moderação + Meta | 40s | 40s |
| **soma** | 202s | **327s** |

Contra `job_timeout = 240`. A folga de 38s que o comentário de `workers/main.py` anuncia é, na verdade, um déficit de 87s — e a reserva de 30s para o banco que `test_a_folga_paga_o_banco` exige some junto.

## Decisões

### D1 — `_PIOR_TURNO` vira função e lê a configuração

`resumir` e `count_tokens` deixam de ser `1`:

```
resumir      = 1 + contexto_max_iteracoes
count_tokens = 1 + contexto_max_iteracoes + ceil(log2(contexto_gatilho_de_regeneracao)) + 1
```

O primeiro termo de cada linha é a chamada de fora do laço (a dobra do gatilho; a contagem pré-laço). O termo do meio é o laço. O último termo de `count_tokens` é `_truncar_ate_caber`: ele corta pela metade a cada volta, então chega a uma literal em `log2(N)` passos, mais uma contagem se ainda precisar descartar o resumo.

`_PIOR_TURNO` precisa de `get_settings()` e por isso deixa de ser tupla de módulo. Vira uma função privada que `segundos_do_modelo_no_pior_turno()` chama — a assinatura pública não muda, então `test_orcamento_do_turno.py` e o comentário de `job_timeout` continuam válidos como referências.

**`N` vem de `contexto_gatilho_de_regeneracao` e isso é uma suposição, não um teorema.** O gatilho dobra em 40 literais, então em regime normal a janela que chega ao truncamento tem essa ordem de grandeza. Se a dobra falhar, `literais` pode passar disso. O comentário vai dizer isso em vez de fingir que o teto é exato: a alternativa seria não ter teto nenhum, que é o estado de hoje.

**O termo do truncamento é pessimista de propósito.** `_contar_se_valer` só paga o round-trip acima do limiar (6564 tokens hoje), e cortar a janela pela metade derruba a contagem rápido — na prática, o truncamento não paga sete contagens. Mas um teto não pode depender de quão rápido o texto encolhe, e subcontar aqui é exatamente o defeito que esta card existe para matar.

### D2 — `test_job_timeout_cabe_dentro_da_janela_do_sweeper` fica só com a invariante do nome dele

Sai a asserção do `pior_caso_por_chamada`, saem os imports de `TIMEOUT_SEGUNDOS` e `MAX_TENTATIVAS`, sai o parágrafo do docstring que descreve o turno.

**Sai também `assert WorkerSettings.job_timeout >= 180`.** É um número escrito à mão sem justificativa em lugar nenhum, e hoje é dominado por `test_a_folga_paga_o_banco`, que exige `job_timeout ≥ soma + 30` — um piso derivado, muito mais forte. Manter os dois seria guardar a versão fraca do mesmo invariante, e é o tipo de número que a card condena por nome.

Fica `job_timeout < sweep_inflight_after_seconds`, que é o que o nome do teste promete e o que nenhum outro teste cobre. O docstring passa a apontar para `tests/unit/test_orcamento_do_turno.py` como o lugar onde a conta do turno mora, para que a próxima pessoa não reconstrua o grafo aqui de novo.

### D3 — O vermelho é `xfail(strict=True)`, e não uma `main` quebrada

`test_o_pior_turno_cabe_no_job_timeout` e `test_a_folga_paga_o_banco` recebem `@pytest.mark.xfail(strict=True, reason=...)` citando a TEC-290.

**Estrito é a parte que importa.** Com `strict=True`, o dia em que alguém fechar o orçamento os testes viram `XPASS` e **reprovam**, obrigando a remoção da marca. Um `xfail` não-estrito ficaria verde para sempre, nas duas direções, e seria a mesma falsa segurança de outro formato.

A alternativa — deixar reprovando de verdade — foi descartada: bloqueia todo merge até a TEC-290 e treina quem lê a ignorar o CI, que é o mecanismo que esta card documenta em outro lugar. `xfail` estrito registra a dívida sem cobrar pedágio de quem não a criou.

`test_o_investidor_e_o_teto_mais_alto_do_turno` continua verde — ele não depende da soma.

### D4 — A prosa que afirma que a conta fecha é corrigida junto

Não é higiene, é o defeito principal. O comentário de `job_timeout` em `workers/main.py` diz hoje **"Hoje a conta fecha, com os quatro clientes externos contados"** e exibe a tabela `162 / 20 / 10 / 10 = 202s contra estes 240 — 38s de folga para o banco`.

Isso passa a ser falso. E é o mesmo defeito, no mesmo comentário, uma versão atrás: a TEC-228 encontrou lá um `360s` onde o real era `840s`. Um comentário que já mentiu uma vez e volta a mentir com número novo é pior que nenhum.

Recebem correção:

- o comentário de `job_timeout` (`workers/main.py`) — a tabela vira 287/327 e a frase inverte, citando a TEC-290;
- o docstring de `segundos_do_modelo_no_pior_turno` (`infra/anthropic.py`), que afirma ser *"a única coisa que torna vermelha a mudança de um teto que não cabe"* — com o `xfail` isso deixa de ser verdade e precisa dizer o que é;
- o cabeçalho de `tests/unit/test_orcamento_do_turno.py`;
- o bloco de comentário de `_PIOR_TURNO`, que afirma "São cinco fatias" com as multiplicidades antigas.

`scripts/comentarios_tocados.py` roda antes do PR para pegar o que esta lista não previu — em particular os `VIZINHO` de `anthropic.py` e os `PROSA` que citem esses arquivos.

## Testes

| teste | o que fixa |
| --- | --- |
| `test_o_pior_turno_cabe_no_job_timeout` | `xfail(strict=True)` — a conta não fecha, e fechar remove a marca |
| `test_a_folga_paga_o_banco` | `xfail(strict=True)` — mesma razão |
| `test_o_investidor_e_o_teto_mais_alto_do_turno` | intacto, continua verde |
| `test_job_timeout_cabe_dentro_da_janela_do_sweeper` | reduzido à invariante do sweeper |
| **novo:** `test_o_pior_turno_segue_contexto_max_iteracoes` | critério de pronto nº 1 — subir a configuração move `segundos_do_modelo_no_pior_turno()`; hoje não move |

O teste novo é o que impede a regressão de verdade. Sem ele, alguém pode voltar `_PIOR_TURNO` para constantes e os `xfail` continuariam `xfail` — verdes, pelo motivo errado.

## O que esta card não entrega

**O orçamento continua estourado quando ela mergear.** Nada em produção fica mais rápido ou mais lento: o `job_timeout` segue 240s, os tetos seguem os mesmos, e um turno patológico continua podendo ser cancelado pelo ARQ exatamente como hoje. O que muda é que a suíte para de afirmar o contrário.

Fechar a conta é a [TEC-290](https://eduardodurieuxlopes.atlassian.net/browse/TEC-290), e não cabia aqui porque não é decisão de código: `job_timeout` é limitado por `sweep_inflight_after_seconds = 300`, então fechar 327s mais a reserva de banco exige mexer na janela do sweeper — quanto tempo uma conversa pode ficar presa antes de ser reenfileirada é decisão de produto.

## Emendas ao SRS

Nenhuma. O orçamento de tempo do turno não é requisito do SRS v1.0; ele vive nos comentários de `workers/main.py` e `infra/anthropic.py`, que esta card corrige diretamente.
