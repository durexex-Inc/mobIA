# TEC-272 — Oferecer o corretor ao confirmar que é assistente virtual

**Status:** desenhado em 2026-09-18 na branch `feat/tec-272-oferta-de-corretor-ao-confirmar`.

**Card:** [TEC-272](https://eduardodurieuxlopes.atlassian.net/browse/TEC-272) — Bug, prioridade Medium. Origem: RN-04.1 e CA-04.1 (SRS v1.0, com a emenda E-01 da TEC-139); RN-B01. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

**Continuação da [TEC-139](https://eduardodurieuxlopes.atlassian.net/browse/TEC-139)**, que pôs a identificação proativa em código, mediu as duas metades do CA-04.1 e descobriu que só a primeira acontece de forma confiável.

## Objetivo

Fazer o agente oferecer transferência para corretor sempre que confirmar ser um assistente virtual — inclusive quando a pergunta do lead é neutra —, sem que a oferta apareça duas vezes na mesma mensagem e sem que ela vire assinatura de rodapé.

## O estado de hoje, medido

Relatório: `evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`, sondagem de quatro turnos contra o modelo real.

| turno do lead | confirma | oferece corretor |
| --- | --- | --- |
| "vc e um robo?" | sim | **não** |
| "to falando com uma pessoa?" | sim | **não** |
| "isso e automatico ou tem alguem ai?" | sim | sim |
| "voce e humano ou maquina? nao quero falar com robo" | sim | sim |

Confirma 4/4, oferece 2/4.

**A identificação proativa já oferece o corretor em toda conversa nova**, e isso atenua: quem pergunta no primeiro turno já recebeu a oferta. O buraco é o lead que pergunta no sexto turno — a regra é *"ao confirmar, oferece"*, não *"ofereceu alguma vez"*.

## O que a card não viu, e que muda o desenho

**Nos casos 3 e 4 o modelo já oferece com todas as letras.** A resposta 4, literal:

> *"Se preferir falar direto com um corretor (pessoa de verdade), é só me dizer que eu já providencio esse contato. Enquanto isso, me conta: você está buscando comprar, alugar ou vender um imóvel?"*

Um append cego grudaria uma segunda oferta depois disso — e depois de uma pergunta. O CA-04.1 ficaria cumprido pela letra, e a mensagem sairia com cara de descuido, que é a classe de defeito que a TEC-267 existiu para consertar.

E não são só esses dois. O `turno.py` tem **seis** textos determinísticos que já falam em corretor — enumerados por importação do módulo, não por leitura:

- `TEXTO_DA_BUSCA_INCONCLUSIVA`
- `TEXTO_SEM_RESULTADO_APOS_AMPLIAR`
- `TEXTO_DO_LIMITE_DE_PERGUNTAS`
- `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`
- `TEXTO_DO_PEDIDO_DE_HUMANO`
- `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`

Somados ao `TEXTO_DA_IDENTIFICACAO`, são **sete** caminhos em que a oferta já está no texto antes de qualquer append.

Duas correções à minha própria primeira leitura, que valem porque a lista vira teste: o encaminhamento de **suporte** *não* fala em corretor (só o de venda), e o pedido de humano tem **duas** variantes, não uma. A lista acima saiu de importar os módulos e filtrar as constantes, não de ler o arquivo — e é assim que o teste vai derivá-la também.

## Decisões

### D1 — Dois detectores, e o de saída olha o texto **final**

`perguntou_se_e_robo(texto)` decide se o lead fez a pergunta. `ja_oferece_corretor(texto)` decide se o append é necessário. Os dois moram em `domain/agente/identificacao.py`, que já é o módulo de "quem o agente diz que é, e quando ele diz".

**O que faz o desenho fechar é onde o segundo roda:** sobre o `texto` já montado, logo depois do bloco `if identificar:` de `turno.py:2551` — e não sobre a resposta crua do modelo. Uma regra só cobre as três duplicações possíveis:

1. o modelo já ofereceu sozinho;
2. a conversa é nova e o prefixo da identificação já ofereceu;
3. o turno caiu numa das seis trilhas determinísticas que já falam em corretor.

Nenhuma delas precisa de caso próprio. Se o texto que o lead vai receber já diz "corretor", não há o que acrescentar — a pergunta não é *quem* ofereceu, é *se a mensagem oferece*.

**A palavra basta, e é por isso que o detector de saída é barato.** "Corretor" não aparece na fala do agente por acaso: nos sete textos acima ela aparece sempre oferecendo um. Um detector de palavra erra para o lado seguro — falso positivo (achar oferta onde não há) devolve o comportamento de hoje, falso negativo duplica. A assimetria está na direção certa.

### D2 — Faixa estrita na entrada, pelo argumento de `gatilhos.py`

O detector de entrada segue o molde de `gatilhos_de`, não o de `pediu_optout`, e a razão é a assimetria de erro:

- **Falso negativo:** o lead não recebe a oferta. É o comportamento de hoje, e a identificação proativa já cobriu quem perguntou cedo.
- **Falso positivo:** uma fala que não é a pergunta recebe uma oferta de corretor grudada. É **literalmente o segundo critério de aceite** desta card — *"a oferta não vira assinatura de rodapé"* — e é visível ao lead.

Visível-ao-lead perde para recuperável. Então termos ancorados por `\b` no início, como `gatilhos.py` faz desde que descobriu "desmarcar visita" casando dentro de "marcar visita".

O custo é de recall, e fica declarado: quem escrever "isso aí é gente ou é sistema?" não dispara.

### D3 — Não existe fala real deste eixo no repo, e a recall é inverificável

`grep -riE "rob(o|ô)|automatico|humano|maquina" evals/corpus/*.yaml` devolve **zero** em todos os cinco arquivos. Não há, em lugar nenhum do repositório, um lead real perguntando se fala com um robô. As quatro frasagens da card são invenção da TEC-139, e o critério de aceite usa uma delas.

Isso tem uma consequência que precisa estar escrita e não resolvida:

**Qualquer termo do detector é invenção, e medi-lo contra as quatro frasagens é medi-lo contra o próprio vocabulário do teste.** É o problema que a D3 da TEC-271 nomeou — o corpus sendo alvo e instrumento ao mesmo tempo — com uma agravante: lá havia corpus, aqui não há.

O que **dá** para garantir, e é o que os testes vão garantir, é o lado negativo: que o detector não dispara em nenhuma das falas que o corpus tem. Isso é verificável contra 1.000+ turnos reais, e é a única afirmação forte que esta card pode fazer sobre a faixa.

### D4 — A sonda mede uma coisa só, e não tem "depois"

4 frasagens × 20 repetições sob o prompt de hoje. **80 chamadas**, modelo do turno (Opus), ~US$ 0,66 — autorizado antes do desenho.

A pergunta é uma: **com que taxa o modelo já oferece sozinho?** O `2/4` da card é uma execução de quatro turnos, que é o mesmo formato de número que a TEC-271 acabou de mostrar ser uma moeda: lá o `11/12` e o `12/12` eram 55%. Se a taxa real aqui for 90%, o append quase nunca dispara e esta card é quase um no-op — e vale saber disso. Se for 10%, é o append que segura o CA-04.1.

**Sem execução "depois", de propósito.** O conserto é determinístico e o resultado é provável por igualdade exata num unitário. Gastar 80 chamadas para reconfirmar o que um teste prova de graça é desperdício, e o append não entra no prompt — não há caminho pelo qual ele mude a geração do modelo.

### D5 — O texto, e onde ele entra

> `Se preferir falar com um corretor, é só me dizer.`

**Com acento**: é texto que o lead recebe (TEC-267). Separado por linha em branco, pelo mesmo argumento que `SEPARADOR_DA_IDENTIFICACAO` registra — as duas frases têm autores diferentes, uma é constante do repositório e a outra é resposta ao lead, e coladas parecem uma frase só mal pontuada.

**Entra na 2551, não na 2791.** `quebrar_em_mensagens` corta em 600 caracteres na 2791 (RN-04.2); anexar depois do corte estouraria o teto em silêncio. Anexando antes, o cortador já trata o texto maior.

### D6 — Por que não no prompt

Registrado porque a leitura inicial da TEC-139 foi essa, e ela é cara: a folga até o teto derivado não comporta a instrução, e abrir espaço significa subir `contexto_headroom_de_tokens`, que o comentário de `app/config.py` registra ter custado **180 tokens por turno** da última vez.

O detector custa **zero** do orçamento do prompt, e é testável por igualdade exata — que é o mesmo argumento que a D2 da TEC-139 usou para pôr a identificação proativa em código.

**Não confie no número da folga que a card transcreve.** Ele se mede com `pytest -q -k margem_do_orcamento -s`, e envelhece — a própria TEC-271 encontrou o `CLAUDE.md` afirmando 655 quando o teto já era 786.

## Testes

Dois unitários por igualdade exata, um por detector, e um teste do turno.

O que eles guardam, e que é o oposto do que parece:

- **`perguntou_se_e_robo` não dispara em nenhum turno do corpus.** Os 1.000+ turnos de `evals/corpus/*.yaml` são fala de lead real, e nenhum deles é a pergunta. É a única afirmação forte disponível sobre a faixa, pela D3, e ela roda de graça.
- **`ja_oferece_corretor` é True nos sete textos determinísticos** que já falam em corretor. Um texto novo que ofereça corretor e não seja pego aqui passaria a duplicar — e o teste é quem avisa.
- **O turno não anexa quando a conversa é nova**, porque a identificação já ofereceu. É a D1 exercitada na composição, não nos detectores isolados.

Sem teste que assere a frase do prompt e sem chamada paga em nenhum deles.

## Emendas ao SRS

**Nenhuma.** O CA-04.1 já exige as duas metades — esta card faz o código cumprir o que a spec sempre disse, e não muda a regra. A E-01 da TEC-139 sob a RN-04.1 continua valendo como está.

## Lacunas declaradas

**A recall do detector de entrada é inverificável** (D3). Não há fala real deste eixo no repo, os termos são invenção, e o teste que existe prova o lado negativo — que ele não dispara em fala do corpus —, não que ele pega o que deveria pegar.

**A sonda mede as quatro frasagens da TEC-139, que são as mesmas quatro que o detector foi escrito para pegar.** A taxa que ela produz é sobre esse vocabulário, não sobre fala de produção. Ela responde "o modelo já oferece sozinho?", que é uma pergunta sobre o modelo e não sobre a faixa — por isso continua valendo.

**O append não sabe se a oferta que já está no texto é adequada ao contexto.** Se uma trilha determinística futura mencionar corretor por outro motivo — negando um, digamos —, `ja_oferece_corretor` a lerá como oferta e se calará. Hoje as sete trilhas oferecem; o teste da lista as congela, mas nada impede a oitava de ser diferente.

## O que esta card não faz

- **Não executa a transferência.** É a TEC-143, que depende da entidade de handoff (TEC-174). Aqui apenas se oferece.
- **Não mexe em `SISTEMA_DO_AGENTE`** nem em nenhum prompt.
- **Não acrescenta frasagens ao corpus.** Ele alimenta o gate de intenção, que é outro assunto e outro custo — e um caso inventado num corpus de fala real o contamina.
