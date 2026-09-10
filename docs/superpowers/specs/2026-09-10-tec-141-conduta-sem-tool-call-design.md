# TEC-141 — Bloquear dado factual sem origem em tool call

**Status:** desenhado em 2026-09-10 na branch `feat/tec-141-conduta-sem-tool-call`.

**Card:** [TEC-141](https://eduardodurieuxlopes.atlassian.net/browse/TEC-141) — Must (MoSCoW), prioridade Highest. Origem: RF-04, RN-04.3, RN-04.4 (SRS v1.0); RT-01, RNF-26. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

**Desbloqueada pela [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161)**, mergeada em `main` como `fcafa95` — a validação técnica que torna a regra de conduta verificável. O quarto critério de aceite desta card foi parcialmente entregue pela [TEC-269](https://eduardodurieuxlopes.atlassian.net/browse/TEC-269); ver "O que esta card não faz".

## Objetivo

O agente para de negociar valor e de prometer desconto, e passa a encaminhar isso ao corretor — com a regra escrita onde ela previne e checada onde ela é medível.

## O estado de hoje, medido

Boa parte da RN-04.3 e da RN-04.4 **já está implementada**, em três lugares diferentes. O que falta é menor do que a card sugere:

| Regra | Onde já está | Falta |
|---|---|---|
| Nunca afirmar preço/característica fora de tool call (RN-04.3) | `SISTEMA_DO_AGENTE`: *"Nao invente informacao sobre imoveis que nao esteja no contexto"*; `FERRAMENTA_DE_BUSCA.description`: *"Nunca cite imovel que nao veio dela"*; e a guarda determinística da TEC-161 | — |
| Sem resultado, dizer que verifica com o corretor (RN-04.3) | `TEXTO_DA_BUSCA_INCONCLUSIVA` (`turno.py`), nos caminhos do laço excedido e da citação bloqueada | o caminho "busca devolveu zero" |
| Consultoria jurídica ou tributária (RN-04.4) | `SISTEMA_DA_SAIDA`: *"conselho juridico ou financeiro apresentado como certeza"* | — |
| Garantir aprovação de financiamento (RN-04.4) | idem, pela cláusula financeira | — |
| Afirmar rentabilidade futura como certa (RN-04.4) | idem; e a RN-07.5 exige a ressalva na trilha de investidor | — |
| **Prometer desconto, negociar valor (RN-04.4)** | **nada** | **tudo** |

- **A margem do orçamento do prompt é de 6,0 tokens** (líquido 780,0 contra teto fixo de 786), medida em 2026-09-10 por `pytest -k margem_do_orcamento -s`.
- O corpus de avaliação tem turnos de negociação e de financiamento, mas **nenhuma métrica mede se a resposta recusou** — as quatro atuais medem intenção, extração, alucinação e formato.
- `evals/moderacao/` já tem corpus anotado em quatro arquivos (`entrada_bloqueia`, `entrada_libera`, `saida_bloqueia`, `saida_libera`), com o formato `id` / `texto` / `porque`.

## Decisões

### D1 — A regra vive em dois lugares, com papéis distintos

O **prompt previne**: o modelo escreve a recusa certa e o lead recebe uma resposta útil. O **moderador é a rede**: pega o turno em que o prompt falhou.

Nenhum dos dois sozinho serve. Só prompt não verifica nada — é exatamente a situação em que a TEC-161 encontrou o RT-01, com uma instrução na `description` da ferramenta e nada checando. Só moderador entrega ao lead o `TEXTO_NEUTRO_DE_SAIDA` (*"Tive um problema para montar a resposta agora"*) diante de *"consegue baixar para 550 mil?"*, que é uma pergunta legítima e comum.

### D2 — O teto do orçamento sobe para 793, e são dois tetos, não um

A cláusula precisa recusar **e** encaminhar, e a margem é **6,0**. Nenhuma redação cabe nela: mesmo `Nao negocie valor nem prometa desconto.` sem destino custa 10,00.

O ritual do `CLAUDE.md` foi cumprido na ordem certa — a pergunta "o que sai para o novo texto entrar?" veio antes de "quanto subo o número?". A busca achou **um** corte legítimo:

- **Sai `, de 0 a 1`** da frase da confiança (**-2,50**). `SCHEMA_DA_RESPOSTA` declara `"confianca": {"type": "number", "minimum": 0, "maximum": 1}`, mas o compilador de schema do lado do servidor não aceita essas duas chaves para `number` — `transform_schema` (biblioteca `anthropic`) as dobra para dentro de `description`, e o campo compilado vira `{"type": "number", "description": "{minimum: 0, maximum: 1}"}`. A faixa chega ao modelo mesmo assim, só que como texto em `description`, então dizê-la também em prosa repete o que o schema compilado já carrega. O que **não** sai é o resto da frase: `minimum`/`maximum` declaram a faixa, não o significado.

**Há dois tetos, e eles são acoplados.** O 786 não é o limite real: `test_diferenca_entre_o_contado_e_o_enviado` afirma `subcontagem < contexto_headroom_de_tokens * 0,75`, o que hoje dá **795,0** (1060 × 0,75). O 786 é o teto **deliberadamente mais apertado** dos dois, e a própria docstring diz isso. Passar o teto fixo de 795 o tornaria mais frouxo que o derivado, invertendo a relação — e o número que de fato prenderia seria 795, com margem de 1,75.

Isso elimina a redação longa. Medindo as três candidatas contra os dois tetos:

| Cláusula | Líquido | Teto fixo | Cabe? |
|---|---|---|---|
| `Nao negocie valor: e com o corretor.` | 786,75 | 793 | **sim** |
| `Nao negocie valor nem desconto: e com o corretor.` | 790,00 | 797 | exige subir `headroom` |
| `Nao negocie valor nem prometa desconto: isso e com o corretor.` | 793,25 | 800 | exige subir `headroom` |

Subir `contexto_headroom_de_tokens` não é gratuito: o comentário dele em `config.py` registra que a última subida (880 → 1060, na TEC-265) custou **180 tokens a menos de literais e resumo por turno**. A reserva sai do mesmo contexto que guarda a conversa do lead.

**Escolha: a primeira.** Teto **786 → 793**, líquido 786,75, margem **6,25**, `headroom` intocado, zero custo em histórico de conversa. `desconto` sai da prosa do prompt e fica com o moderador, onde não custa nada — e pedir desconto é negociar valor, então a cláusula curta cobre o cenário do Gherkin.

> **Duas correções registradas.** A primeira versão deste desenho dizia teto 796; 796 sobre 793,25 são 2,75 de margem, não os ~6 prometidos — erro de aritmética que eu levei à decisão de produto antes de conferir. A segunda dizia 800, e estava errada por outro motivo: eu tratava o orçamento como um número quando são dois, e 800 é maior que o teto derivado de 795. A decisão de produto (só a negociação entra no prompt, com destino) sobreviveu às duas; o que mudou foi o preço, para menos.

Não há corte maior disponível sem apagar regra que outra card pagou para pôr ali — a docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada` registra cada uma, e desfazer trabalho alheio para financiar o meu seria a leitura errada do ritual.

### D3 — Só a negociação entra no prompt

Entra, ao fim do parágrafo de resposta:

```
Nao negocie valor: e com o corretor.
```

**O destino não é ornamento.** O segundo cenário Gherkin da card exige `E encaminha a negociação ao corretor` — recusar sem encaminhar não passa no critério de aceite.

**Não entram** jurídico, financiamento e rentabilidade futura. A `SISTEMA_DA_SAIDA` já os barra, e pagar ~25 tokens em **toda** chamada para prevenir o que a rede já pega, em casos raros no corpus, é o oposto de YAGNI. **Consequência declarada:** nesses três, o lead que esbarrar na regra recebe o texto neutro em vez de uma resposta boa. É a troca aceita: prevenção custa por turno, rede custa só quando falha.

### D4 — O moderador ganha a negociação, fora do teto

`SISTEMA_DA_SAIDA` passa a barrar promessa de desconto e negociação de valor. O prompt do moderador tem orçamento próprio: os dois tetos da D2 medem o bloco `system` do **agente**, e a moderação é outra chamada, com outro `system`. Esta metade é gratuita no contexto pago do turno.

**O risco está no outro lado, e é o que a card pode quebrar.** O moderador hoje libera explicitamente *"dizer que nao ha imovel no perfil, que o valor esta fora da faixa, ou pedir mais informacao"*. Essa liberação tem de sobreviver: `"Esse está acima da sua faixa"` é atendimento correto, `"consigo baixar para 550"` é a violação, e a fronteira entre as duas é estreita. Um moderador que confunde as duas bloqueia conversa comercial normal — o erro que o próprio `SISTEMA_DA_ENTRADA` chama de *"erro, nao cautela"*.

### D5 — A medição vai para o eval de moderação

O veredito do moderador é `BLOQUEAR`/`LIBERAR`: binário, anotável, medível sem juiz. Julgar se uma prosa "negociou" não é nenhuma dessas coisas.

Entram casos em `evals/moderacao/saida_bloqueia.yaml` e **igual número de contraexemplos** em `saida_libera.yaml`. A segunda metade não é simetria estética: é o que impede a card de entregar um moderador que bloqueia tudo que menciona preço e ainda assim mede 100% de acerto no arquivo de bloqueio.

**Consequência declarada:** a prevenção — o prompt — **não ganha número próprio**. Mede-se a rede, não a rede mais a prevenção. Medir o prompt exigiria julgar prosa livre, que é o juiz LLM que a TEC-269 recusou por custo e por fazer a guarda depender de um modelo. Fica como lacuna.

## Fluxo

```
turno do agente
  |
  +- SISTEMA_DO_AGENTE ganha a clausula (D3)  -> o modelo recusa e encaminha
  |
  v
moderacao de saida (ja existe, roda em todo turno)
  |
  +- SISTEMA_DA_SAIDA ganha a proibicao (D4) -> BLOQUEAR se o modelo negociou
  |
  v
bloqueou? -> texto = TEXTO_NEUTRO_DE_SAIDA (comportamento atual, nao muda)
```

## Testes

**Unitários** (`tests/unit/`, sem rede):

- A cláusula está em `SISTEMA_DO_AGENTE` e o `, de 0 a 1` saiu.
- `pytest -k margem_do_orcamento -s` passa com teto 793 e margem 6,25. O histórico do teto ganha a linha desta card, com o custo e o corte.
- O corpus de moderação continua satisfazendo os invariantes que `tests/unit/` já guarda (contagem por arquivo, ids únicos).

**Eval de moderação** (`pytest evals` — pago, roda só quando autorizado):

- Os casos novos de `saida_bloqueia` são bloqueados.
- Os contraexemplos de `saida_libera` continuam liberados — inclusive os que já existiam sobre valor fora da faixa.

## Emendas ao SRS

**Nenhuma.** A RN-04.3 e a RN-04.4 são implementadas, não contrariadas. A regra diz que as condutas são proibidas; não diz por qual mecanismo, e distribuir entre prompt e moderador é decisão de implementação.

O teto do orçamento não é regra de SRS: vive no corpo de `test_a_margem_do_orcamento_do_prompt_e_deliberada`, e o histórico dele fica na docstring daquele teste.

## Lacunas declaradas

1. **A prevenção não tem número.** Mede-se o moderador; o prompt fica sem métrica própria (D5).
2. **Jurídico, financiamento e rentabilidade não têm prevenção**, só rede — o lead que esbarrar recebe o texto neutro (D3).
3. **A UX do bloqueio não muda.** Todo bloqueio do moderador entrega `TEXTO_NEUTRO_DE_SAIDA`, que não explica nada ao lead. É o comportamento atual para toda a moderação, herdado e não introduzido aqui.
4. **O caminho "a busca devolveu zero"** continua sem tratamento próprio: `TEXTO_DA_BUSCA_INCONCLUSIVA` cobre o laço excedido e a citação bloqueada, não o resultado vazio.

## O que esta card não faz

- **O quarto critério de aceite, na íntegra.** Ele exige que a taxa de alucinação fique abaixo de 2% **e que regressão bloqueie o merge**. A TEC-269 entregou a medição (0,0–0,7% em duas execuções) e deliberadamente deixou o piso como andaime em 50%, porque uma execução não é distribuição. **O gate bloqueante é card própria**, quando houver histórico. Esta card não o fecha e não deve fingir que fecha.
- **O caminho sem resultado no catálogo** (lacuna 4): os outros dois caminhos (laço excedido, citação bloqueada) já são resolvidos em código, a custo zero de prompt, por `TEXTO_DA_BUSCA_INCONCLUSIVA` (`turno.py`) — pôr o terceiro caminho no prompt pagaria por turno por algo que também dá para resolver em código, pelo mesmo mecanismo.
- **Filtro de conteúdo discriminatório** — é a TEC-142, e a própria card já o declara fora de escopo.
