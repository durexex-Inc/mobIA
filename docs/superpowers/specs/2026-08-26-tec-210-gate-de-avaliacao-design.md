# TEC-210 — Gate de avaliação da classificação de intenção

- **Data:** 2026-08-26
- **Jira:** [TEC-210](https://eduardodurieuxlopes.atlassian.net/browse/TEC-210) · Épico [TEC-208](https://eduardodurieuxlopes.atlassian.net/browse/TEC-208)
- **Origem:** RNF-25, RNF-26, RNF-28 (SRS v1.0); seção 4.4, RT-01
- **Status:** aprovado, aguardando plano de implementação

## Problema

A qualidade do agente é hoje uma impressão subjetiva. Um ajuste de prompt que
piora a classificação de intenção não é barrado por nada: a suíte inteira passa,
porque nenhum teste toca a rede — o classificador é sempre um dublê, e a intenção
entra por argumento. Os testes provam que a classificação atravessa um turno real
e chega ao banco intacta. Não provam que ela está certa.

Os limiares de 0,8 e 0,6 que decidem desambiguação são autoavaliação do modelo,
não probabilidade calibrada, e saíram de um comentário. Não há como recalibrá-los
sem antes existir uma régua.

## Escopo: o que este card não entrega

A TEC-210 como está escrita no Jira são cinco trabalhos que não se parecem. Este
spec entrega **um** deles e declara os outros fora de escopo — não por
conveniência, mas porque três das quatro métricas do card não têm feature para
medir, e dois dos cinco itens não são avaliação.

| Item do card | Neste spec |
|---|---|
| Corpus de conversas sintéticas anotadas | ✅ entregue |
| Harness + acurácia de intenção | ✅ entregue |
| Gate no CI que bloqueia merge | ✅ entregue |
| Precisão de extração de campos (≥ 85%) | ✗ sem sujeito — TEC-145 não existe |
| Taxa de alucinação (< 2%) | ✗ sem sujeito — bloqueada por TEC-161, como o próprio card declara |
| Aderência ao tom | ✗ sem sujeito — TEC-140 não existe |
| Moderação de entrada e saída em 100% dos turnos | ✗ é feature de produção, não avaliação |
| Política de não-treinamento com o provedor | ✗ é tarefa contratual, ninguém programa |

As três métricas sem sujeito **entram declaradas no relatório**, sempre em
`SEM_MECANISMO`, nunca em verde. Ver a seção própria abaixo.

## Abordagem: pytest fora de `tests/`, chamada real ao modelo

**A chamada ao modelo é real.** Rodar o eval contra resposta gravada seria
determinístico, barato e mediria exatamente nada: o que o gate existe para pegar
é a mudança de prompt alterando o que o modelo devolve, e um replay passaria
verde com o prompt destruído. Cada execução custa dinheiro e não é
determinística — as duas consequências moldam tudo o que vem depois.

**O eval mora em `evals/`, não em `tests/`.** O conftest raiz tem três fixtures
`autouse`, e `migrar_banco` e `banco_limpo` exigem Postgres: qualquer arquivo sob
`tests/` herda isso, e um marker `eval` não escaparia. Com diretório separado e
conftest próprio, o `testpaths = ["tests"]` do pyproject já garante que `pytest`
puro nunca o colete. O isolamento vem do diretório, que é menos máquina que um
marker, não mais.

Roda com `python -m pytest evals`.

## O corpus

`evals/corpus/*.yaml`, agrupado por categoria — `compra.yaml`,
`investimento.yaml`, `follow_up.yaml`, `borda.yaml`. Um arquivo por categoria
porque o corpus é a régua: se um humano não consegue revisá-lo, ele não mede nada
confiável.

```yaml
- id: compra-07
  descricao: lead abre por preço e vira aluguel no meio
  turnos:
    - lead: "vi o apto de vocês na vila mariana, quanto tá?"
      intencao: COMPRA
    - lead: "na verdade pra comprar tá fora do meu alcance, tem pra alugar?"
      intencao: ALUGUEL
```

Cobertura exigida pelo card: compra, investimento e follow-up, mais os casos de
borda — lead evasivo, mudança de intenção no meio, tentativa de injeção e pedido
fora de escopo.

**O texto é sintético; o rótulo é anotado à mão.** Gerar o corpus com o mesmo
modelo que ele mede embute as pistas que aquele modelo lê bem, e a acurácia sai
inflada por construção. O rótulo é a verdade, e ele não pode vir de quem está
sendo medido.

## A unidade de medida

**Por turno, não por conversa.** Uma conversa com mudança de intenção no meio só
faz sentido assim, e é o que "acurácia de intenção" significa: de cada
classificação que o agente fez, quantas acertou.

Cinquenta conversas de aproximadamente três turnos dão cerca de **150 turnos
anotados**. O turno é avaliado com o contexto dos turnos anteriores da mesma
conversa já montado — a classificação do terceiro turno vê os dois primeiros,
como em produção.

## Os limiares e o não-determinismo

O código não passa `temperature`, então produção roda no default da API. O eval
roda igual: medir com `temperature=0` daria um número estável sobre uma
configuração que a produção não usa, e o gate ficaria verde para um prompt que se
comporta mal exatamente onde o cliente o encontra.

O preço dessa escolha é variação entre execuções, e a resposta a ela são duas
linhas em vez de uma:

```
>= 90%  (135/150)   verde     — o alvo do card
84-89%  (126-134)   amarelo   — avisa, não bloqueia
<  84%  (< 126)     vermelho  — bloqueia o merge
```

**O gate compara percentual, não contagem.** Os absolutos entre parênteses supõem
exatamente 150 turnos e servem para leitura; o corpus real vai fechar em algum
número próximo, e cravar contagem faria o limiar mudar de significado a cada
conversa acrescentada. O corpus tem um piso de 120 turnos: abaixo disso, um único
turno vale mais de 0,8% e a faixa amarela deixa de absorver o ruído.

Os 84% não são invenção: é o número que o próprio Gherkin do card usa como
exemplo de regressão que deve barrar. O ruído esperado entre execuções é de ±2
turnos, ou 1,3% em 150 — bem dentro da faixa amarela. Uma regressão de verdade,
como um prompt quebrado, derruba dezenas de pontos, não dois.

A alternativa rejeitada foi bloqueio duro em 90%. Ela flakearia perto da borda, e
a reação previsível a um gate que flakeia é re-rodar o job até passar — que é o
modo de falha que esvazia o gate por dentro.

## Como o contexto é montado sem banco

`ContextoMontado` recebe `literais: list[Message]`, e `_texto_da` chama
`decrypt(linha.text_body, aad_de(linha.id, "text_body"))`: o corpo é cifrado com
AAD ligado ao `id` da linha.

O eval constrói `Message` **transientes** — `id=uuid4()`,
`text_body=encrypt(texto, aad_de(id, "text_body"))` — sem sessão e sem `INSERT`.
O padrão já existe no `semear` do conftest de testes; a versão do eval é a mesma
coisa sem o `await session`.

Consequência: o job de CI não declara `services:`. Só Python e a chave da API. O
eval mede `ClassificadorAnthropic.classificar` isolado, não o turno inteiro — a
integração com worker e banco já tem cobertura própria na suíte atual.

## As três métricas sem sujeito

Extração, alucinação e tom aparecem no relatório de cada execução com estado
`SEM_MECANISMO`, e **nunca em verde**.

Um slot ausente que reporta verde é pior que slot nenhum: some do radar e cria a
impressão de que os quatro alvos do card estão cobertos quando apenas um está.
Declarado e falhando, ele é uma dívida visível em toda execução.

Quando TEC-145, TEC-161 e TEC-140 chegarem, cada uma pluga a sua métrica e o
estado muda de `SEM_MECANISMO` para número.

## O gate no CI

Workflow separado, `.github/workflows/evals.yml`. O `ci.yml` fica intocado e o
gate é independente:

```yaml
on:
  pull_request:
    paths:
      - 'src/mobia/domain/agente/**'
      - 'evals/**'
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

O path filter é o que o Gherkin do card pede — "Dada uma alteração em qualquer
prompt de agente". A maioria dos PRs não paga nada.

O relatório aponta qual métrica regrediu, com a matriz de confusão por intenção:
saber que a acurácia caiu para 81% não diz o que fazer; saber que `INVESTIMENTO`
está virando `COMPRA` em metade dos casos, sim.

**Falha de infraestrutura aborta a execução; não vira erro de classificação.** Um
`RespostaInvalida`, um 429 ou um timeout do cliente não são o modelo errando a
intenção — contá-los como turno errado faria uma rede instável ler como regressão
de prompt e barrar um merge inocente. O job termina em erro com a causa, distinto
do vermelho de acurácia, e a execução não produz número.

## Pré-requisitos fora do código

Dois itens que não dependem de implementação e sem os quais o gate não funciona:

1. **O segredo `ANTHROPIC_API_KEY` não existe no repositório.** Sem ele o job
   falha no primeiro turno.
2. **Um check com path filter não pode ser marcado como obrigatório do jeito
   ingênuo.** Nos PRs que não tocam os paths ele nunca roda, e a proteção de
   branch fica esperando para sempre, bloqueando o merge. A saída é um job
   companheiro que reporta sucesso quando o filtro não bate.

## Testes

O eval é a medição, não o teste — mas o encanamento dele tem teste próprio, e
esses rodam na suíte normal, sem rede:

- O carregador de corpus rejeita rótulo que não seja membro de `Intencao`. Um
  `COMPRA_` com typo viraria turno silenciosamente sempre-errado, derrubando a
  acurácia por um defeito do corpus e não do prompt.
- O cálculo de acurácia sobre resultados sintéticos, com as bordas exatas: 135 de
  150 é verde, 134 é amarelo, 126 é amarelo, 125 é vermelho.
- As três métricas sem mecanismo reportam `SEM_MECANISMO`, e o resultado nunca é
  verde.
- O construtor de `Message` transiente produz uma linha que `_texto_da` decifra de
  volta ao texto original.

## Garantias

- Uma mudança de prompt que derrube a acurácia de intenção abaixo de 84% barra o
  merge, com relatório apontando a métrica e a matriz de confusão.
- O eval mede a mesma configuração que a produção usa — sem `temperature` fixada
  para conveniência de medição.
- A régua existe: os limiares de 0,8 e 0,6 passam a ser mensuráveis.
- O corpus é revisável por humano, e seus rótulos não vêm do modelo medido.
- Nenhuma métrica sem mecanismo pode reportar verde.

## Lacunas conhecidas

- **O path filter tem um buraco.** Uma mudança em `montagem.py` altera o que o
  modelo vê sem tocar em nenhum prompt, e passa livre. Cobrir isso exigiria rodar
  o gate em todo PR, com o custo e o flake que a decisão do limiar rejeitou.
- **Este card não recalibra 0,8 e 0,6.** Ele cria a régua; medir e mexer nos
  números é trabalho seguinte.
- **Corpus sintético não é tráfego real.** Cento e cinquenta turnos escritos por
  quem conhece o sistema carregam o viés de quem os escreveu, e nenhuma anotação
  cuidadosa remove isso. O número que sair daqui é um piso de confiança, não uma
  medida de campo.
- **O eval não cobre o turno inteiro.** Ele chama `classificar` direto; regressão
  que só apareça na integração com contexto real do banco não é pega aqui.
- **Nada disto entrega moderação.** O primeiro turno que existe continua indo ao
  ar sem moderação de entrada ou de saída — item 4 do card, que precisa de card
  próprio por ser feature de produção.
- **A política de não-treinamento continua não configurada.** Item 5 do card,
  administrativo.
