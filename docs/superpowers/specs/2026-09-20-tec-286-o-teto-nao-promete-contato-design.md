# TEC-286 — O teto de perguntas para de prometer contato

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-286](https://eduardodurieuxlopes.atlassian.net/browse/TEC-286) — épico TEC-144
**Branch:** `feat/tec-286-o-teto-nao-promete-contato`
**Origem:** RF-05, RN-05.5; dívida herdada da TEC-149.

## Objetivo

Tirar de `TEXTO_DO_LIMITE_DE_PERGUNTAS` a frase *"Pode deixar que ele entra em contato."*, e fazer a guarda de teste barrar a **promessa**, e não o vocabulário que as três ocorrências anteriores por acaso usaram.

## O que a exploração mudou em relação ao texto da card

**A TEC-280 está Feita, e a premissa da card envelheceu em parte.** A card afirma que "nada notifica corretor nenhum enquanto a TEC-280 e a TEC-281 estiverem abertas". Hoje o e-mail ao corretor **entrega**, por SMTP. O hedge continua certo, mas pela razão que três comentários do repo já escrevem por extenso — *aceito pelo servidor não é o mesmo que lido por um corretor* — mais o WhatsApp (TEC-281), que segue só registrando por falta de template aprovado pela Meta. A consequência prática é a nota de reversão: ela passa a depender só da TEC-281, não das duas.

**A promessa é citada em três lugares, não um.** Além do literal, dois comentários de `turno.py` a citam por extenso: o da despedida (~2527), que justifica por que a TEC-138 vence as substituições acima dela, e o da virada do investidor (~2253), que justifica registrar o handoff ali. O segundo só aparece na leitura — a citação está quebrada entre duas linhas de comentário, e nenhum grep pela frase inteira a encontra. Mudar só o literal deixaria os dois mentindo sobre o texto que citam — o defeito que a TEC-146 pagou caro.

**Três textos ao lead nunca estiveram na guarda de acento.** `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`, `TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE` e `TEXTO_DO_PEDIDO_DE_HUMANO` (o de dentro do horário) são constantes de módulo entregues ao lead e estão fora de `LITERAIS_AO_LEAD` — só a variante `_FORA_DO_HORARIO` do pedido de humano entrou. Não é lacuna desta card, mas ela é a primeira a precisar da mesma lista para outra finalidade, e é onde fechar sai de graça.

## D1 — A frase nova é a da irmã, não uma quarta redação

A última frase passa a ser **"Já coloquei sua conversa na fila deles."**, idêntica ao fecho de `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`.

Não é economia de criatividade: a regra da card é espelhar as irmãs já hedgeadas em vez de inventar uma quarta forma de dizer o mesmo fato. Duas redações para o mesmo fato são duas coisas para manter em sincronia — é o argumento que o comentário de `SUFIXO_FORA_DA_JANELA` já usa para justificar copiar a redação da TEC-143.

O texto inteiro passa a ser:

> "Já perguntei bastante e não quero virar interrogatório. Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui. Já coloquei sua conversa na fila deles."

**O que a frase nova afirma é verdade hoje:** o handoff é criado no bloco transacional, e ele fica mesmo quando a despedida da TEC-138 sobrescreve o texto. A fila existe; o que não existe é a garantia de que alguém a abriu.

**Nota de reversão no comentário do literal.** Quando a TEC-281 entregar, a promessa passa a ser verdadeira e o texto pode voltar a ser firme. Fica escrito qual é a condição — sem isso, o hedge vira folclore e a próxima pessoa não sabe se ainda vale.

## D2 — `LITERAIS_AO_LEAD` sai do arquivo do acento e vira módulo próprio

A tupla vive hoje dentro de `tests/unit/test_acento_no_texto_ao_lead.py`. Ela passa para `tests/unit/literais_ao_lead.py`, e as duas guardas — acento e promessa — leem dela.

A alternativa era parametrizar à mão, na guarda nova, os cinco textos que a card nomeia. Foi recusada porque produz **duas listas de literais ao lead** no mesmo diretório, e um texto fixo novo não entra em nenhuma das duas sozinho. Com uma lista só, entrar na lista passa a significar "coberto pelas duas guardas", que é a propriedade que faz a próxima card não repetir esta.

A lista cresce de 17 para 20 com os três achados acima. `test_a_lista_de_literais_nao_encolheu_sem_querer` acompanha o número novo, e vai para `tests/unit/test_literais_ao_lead.py` — arquivo próprio, porque o pytest só coleta `test_*.py` e um teste escrito dentro do módulo da lista nunca rodaria. Ele é a guarda da guarda: sem ele, tirar um literal da lista é mudança que nada denuncia, já que nenhuma das duas guardas reprova por ausência.

**A docstring do arquivo do acento fica onde está.** Ela explica por que a guarda cobre constantes de módulo e não os rótulos da ficha de imóvel — é raciocínio sobre o *escopo da lista*, então a parte que descreve o que a lista é acompanha a lista; a parte que descreve o que a guarda de acento faz com ela fica no arquivo do acento.

## D3 — A guarda nova barra frases, e erra de menos

Arquivo novo `tests/unit/test_promessa_ao_lead.py`, no molde do vizinho de acento.

```python
PROMESSAS_BANIDAS = (
    "avisei", "avisamos", "avisado",
    "entra em contato", "entrar em contato", "entrará em contato",
    "entram em contato",
    "vai te procurar", "vai te ligar", "vai te chamar",
)
```

**A assimetria é deliberada, e é a mesma que o arquivo de acento declara:** uma frase faltando na lista deixa de pegar um caso; nenhuma frase da lista reprova texto correto. Não há como provar por análise de texto que uma prosa não promete nada — o que dá para prender é o conjunto de formas que este repo de fato já escreveu, três vezes, e as vizinhas óbvias delas.

A busca é por substring em minúsculas, e não por fronteira de palavra como no acento: aqui as agulhas são frases de duas ou três palavras, e a fronteira não acrescenta nada que a frase inteira já não dê.

`test_nenhum_texto_promete_que_alguem_foi_avisado`, hoje em `test_textos_do_encaminhamento.py`, **sai de lá e é absorvido aqui** — senão ficam duas listas de palavras banidas, que é o mesmo defeito que a D2 evita na lista de literais. O que fica naquele arquivo é o que é específico da TEC-137: os dois textos serem distintos, não terminarem em pergunta, e o sufixo formatar as horas.

## D4 — A prosa que passa a mentir

Quatro sítios, todos dentro do diff. Eram três quando este desenho foi escrito: a citação da virada do investidor está quebrada entre duas linhas de comentário e nenhum grep pela frase inteira a encontra — ela apareceu na leitura do arquivo.

1. O comentário de `TEXTO_DO_LIMITE_DE_PERGUNTAS` — ganha a nota de reversão e para de depender da TEC-280 para justificar o hedge.
2. O comentário da despedida (~2527) — passa a citar a frase nova, e o argumento dele **continua válido**: "já coloquei sua conversa na fila deles" também promete um depois que a conversa encerrada não tem, então a despedida continua tendo de vencer. O que mudou é quem promete: antes, um corretor que ninguém avisou; agora, uma fila que o silêncio de 30 dias fecha.
3. O comentário da virada do investidor (~2253) — passa a citar a frase nova, e o caso que ele descreve fica **pior**, não melhor: a frase agora afirma uma linha em `handoffs` que, sem aquele registro, não existiria.
4. A docstring de `tests/unit/test_textos_do_encaminhamento.py` — diz que o arquivo testa "em especial que nenhum dos dois promete que alguém foi avisado", que é justamente o teste que sai dele.

Os dois planos que citam a frase antiga (`2026-09-14-tec-149-...` e `2026-09-14-tec-267-...`) **não são tocados**: plano registra o que se fez num dia, e `scripts/comentarios_tocados.py` os deixa fora por isso.

## D5 — O que não muda, e as lacunas declaradas

**`TEXTO_DA_BUSCA_INCONCLUSIVA` fica como está.** Ele diz "já te retorno com as opções", que é promessa — mas do **agente sobre si mesmo**, e na trilha dele o agente de fato volta. A guarda desta card é sobre contato futuro de **corretor**; ampliá-la para promessa em geral exigiria decidir quando o agente pode falar do próprio futuro, que é decisão de produto e não cabe aqui.

**`TEXTO_SEM_RESULTADO_APOS_AMPLIAR` fica como está.** Ele pergunta "Quer que um corretor olhe isso com você?" — é pergunta, não promessa, e já é tratado pelo comentário da despedida.

**O teto de oito perguntas e o momento do handoff não mudam** — fora do escopo pela card.

## Testes

* A guarda nova, parametrizada sobre os 20 literais: nenhum contém frase banida.
* Um teste de que a lista de frases banidas não encolheu, pela mesma razão que o vizinho de acento tem um.
* O teste de que a lista de literais não encolheu acompanha o número novo (20).
* Verificação nos dois sentidos, como a nota de método da TEC-289 pede e a TEC-138 praticou: com a frase antiga plantada de volta num literal, a guarda nova reprova; sem ela, passa. É o que separa "escrevi um teste" de "escrevi um teste que pode reprovar".
* Os testes de integração que comparam `TEXTO_DO_LIMITE_DE_PERGUNTAS` por identidade (`test_turno_teto_de_perguntas.py`, `test_turno_investidor.py`, `test_encaminhamento_por_intencao.py`) **não precisam mudar**: importam a constante em vez de repetir o literal.

## O que este desenho não entrega

Entregar a notificação por WhatsApp (TEC-281) — e, com ela, o direito de o texto voltar a ser firme. Enquanto ela não entrar, o lead que bate o teto sabe que a conversa está numa fila, e não que alguém vai procurá-lo.
