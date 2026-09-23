# TEC-130 — O encerramento por inatividade, e a fronteira de histórico que a reabertura precisava ter

**Status:** desenhado
**Card:** [TEC-130](https://eduardodurieuxlopes.atlassian.net/browse/TEC-130)
**Branch:** `feat/tec-130-encerrar-por-inatividade`
**Origem:** RF-02, RN-02.3 (SRS v1.0). Card escrita em 22/08/2026, antes das emendas que a contradizem — ver D1.
**Linhas citadas:** os números de linha deste documento valem para `843481f`. `turno.py` tem 4380 linhas e muda em quase toda card; confie no nome da função, não no número.

## Objetivo

A RN-02.3 diz que a conversa é encerrada após 30 dias sem interação, e que a mensagem seguinte abre uma conversa nova, vinculada ao mesmo lead, **com acesso ao histórico anterior via resumo**. Hoje nada encerra por inatividade, e a reabertura que existe entrega ao agente a transcrição literal da conversa anterior — o oposto do que a regra pede.

Esta card acrescenta o encerramento por inatividade e por opt-out, e desenha a fronteira de histórico que faltava.

## O estado antes desta card, conferido no código durante o desenho

- **A entidade já existe, e foi escrita para esta card estendê-la.** `Conversa` (`conversa/models.py`) tem `status`, `motivo_do_encerramento` e `encerrada_em`, com PK `(channel, conversation_key)`. A docstring do módulo nomeia a TEC-130 e diz por extenso que ela **estende, não cria** — a Emenda E-02 da RN-02.3 registra o mesmo.
- **Há um único motivo e um único escritor.** `MotivoDoEncerramento` tem só `FORA_DE_ESCOPO`, e o único chamador de `encerrar_conversa` em produção é `turno.py:3745`, no fecho da RN-03.5.
- **A reabertura já existe**, em `turno.py:1269-1323`, e roda **antes** de `montar_contexto` (`turno.py:1690`). Ela não olha o motivo, de propósito — o comentário de lá diz que quem acrescentar um motivo e quiser outro tratamento muda aquela linha deliberadamente.
- **O portão de opt-out roda antes dos dois** (`turno.py:1117`). Um lead em opt-out retorna cedo e nunca chega ao bloco da reabertura: reabrir não ressuscita quem pediu para sair.
- **`silencia_o_agente` exige `FORA_DE_ESCOPO`** (`conversa/repositorio.py`). A propriedade foi escrita assim por causa desta card: uma versão que olhasse só o `status` transformaria todo encerramento por inatividade em 30 dias de silêncio, destruindo o reengajamento que a RN-02.3 existe para ter.
- **"Conversa nova" é derivada, não perguntada.** `e_conversa_nova` (`agente/identificacao.py:35`) mede silêncio direto em `messages`, e a constante `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30` mora lá — importada por `conversa/repositorio.py` para medir a janela do próprio encerramento.
- **A única fronteira de histórico que existe é a marca do resumo.** `literais_apos` (`context/janela.py:41`) filtra por `(channel, conversation_key)`, por `bloqueada_em` e pela marca. Não há nenhuma noção de encerramento. `ler_resumo` é uma linha por `(channel, conversation_key)`, rolante.
- **A dobra já roda dentro do turno**, em `montar_contexto` (`montagem.py:528`), quando os literais passam do gatilho de regeneração.
- **A cadência de follow-up esgota em no máximo 14 dias** (`followup/cadencia.py:27`, FRIO: 3 + 14). Ela sempre termina dentro da janela de 30.

## O defeito que a card nomeia, e o que ela não nomeia

O que a card pede está escrito: nada encerra por inatividade. Encerrar é acrescentar um motivo e um escritor, e a Emenda E-02 já disse isso.

**O que a card não nomeia é o mais caro.** O critério *"a conversa nova tem acesso ao histórico anterior por meio do resumo, não pela transcrição inteira"* não é satisfeito hoje nem seria pelo encerramento sozinho. A marca do resumo é a única coisa que separa o que o agente vê do que ele não vê, e ela não sabe o que é encerramento. Uma conversa reaberta entrega ao prompt a cauda literal da anterior — até o piso de mensagens que `dividir` preserva — como se fosse a mesma conversa. Encerrar sem mexer nisso escreve a data e o motivo no banco e não muda uma linha do que o modelo lê.

## Decisões

### D1 — Concluir o handoff não encerra a conversa, e o Gherkin da card é descartado

A card lista três situações de encerramento, e uma delas é *"handoff concluído"*. A **Emenda E-01 da RN-02.3 (TEC-278, 13/09/2026)** diz o contrário, por extenso: concluir o handoff significa **retomar** o atendimento automático, e *"a TEC-130 tem de respeitar essa separação quando chegar"*. A card é de 22/08 e a emenda é posterior.

A emenda vence. O cenário *"Encerrar por handoff concluído"* não é implementado, e nada é acrescentado a `devolver` (`api/routes/conversas.py`).

A razão da emenda continua valendo e é o argumento: se concluir encerrasse, o encerramento dobraria o histórico no resumo (D4), e o lead que o corretor acabou de atender voltaria a falar com um agente que só tem o resumo daquele atendimento, não a transcrição. É exatamente o esquecimento que a E-01 quis impedir — e sob esta card ele seria pior que em 13/09, porque agora o encerramento tem consequência sobre o contexto, e não só sobre o `status`.

Fica emenda nova, registrando que o Gherkin foi descartado e por quê.

### D2 — Dois motivos novos, `INATIVIDADE` e `OPTOUT`, e nenhum dos dois cala o agente

`MotivoDoEncerramento` ganha os dois membros. Nenhum entra em `silencia_o_agente`, que continua exigindo `FORA_DE_ESCOPO`.

Para `INATIVIDADE` é o ponto inteiro da regra: a conversa fechada por silêncio tem de ser respondida na mensagem seguinte, senão o reengajamento morre. Para `OPTOUT` o silêncio já existe e vem de outro lugar — `esta_em_optout`, no portão de `turno.py:1117` —, e duplicá-lo aqui criaria duas fontes para o mesmo fato.

Sem tabela nova e sem segunda noção de encerrada, como a Emenda E-02 mandou.

### D3 — Dois mecanismos, um relógio: o sweep escreve o registro, o turno decide o contexto

É a decisão central, e é a que diverge do que o repo previa.

- O **sweep** `sweep_conversas_inativas` fecha a conversa e grava data e motivo. É a escrituração que a card pede e o que alimenta quem lê o estado do funil. **Uma vez por dia**, e não de 30 em 30 segundos como `sweep_stalled`: a janela é de 30 dias, então a diferença entre fechar às 3h e fechar às 3h30 não existe para ninguém, e a consulta varre `messages` inteira em vez de uma fila curta.
- A **fronteira do contexto não depende dele**. O gatilho da dobra (D4) é o relógio — a janela de silêncio caindo no meio do que ainda não foi resumido —, não o `status` da linha. Ver a Emenda D4-a para a forma exata, que mudou na revisão final.

O comentário de `identificacao.py:30` promete o contrário: *"Quando aquela card chegar, este modulo passa a perguntar a entidade em vez de derivar, e esta constante sai."* **Declinado de propósito, e o comentário muda junto.**

Perguntar a entidade põe um cron no caminho crítico de uma correção de contexto. Com o sweep parado — ou apenas ainda não executado, porque ele roda uma vez por dia e o lead voltou antes —, a conversa continuaria `ATIVA`, a leitura do `status` diria "mesma conversa", e o turno montaria o prompt com a transcrição velha **e** sem apresentação. Silenciosamente, e num caminho que nenhum teste de integração pegaria, porque nos testes o sweep sempre acabou de rodar. O argumento vale para os dois leitores do relógio, e continua valendo depois da Emenda D4-a: um deles trocou de forma, nenhum passou a perguntar a entidade.

Derivar é o que torna a correção verdadeira independentemente da varredura. O preço é que a definição de silêncio continua em dois lugares — a constante e a linha do banco —, e ele se paga com a mesma constante servindo aos dois: ela sai de `agente/identificacao.py` e passa a morar em `conversa/regras.py`, ao lado de `TETO_DE_FORA_DE_ESCOPO`, que é o módulo puro do ciclo de vida da conversa. `identificacao.py` e o sweep passam a importá-la de lá.

**Consequência declarada:** o sweep pode ficar para trás do que o turno já considera conversa nova. Uma conversa com 45 dias de silêncio cuja varredura ainda não passou é, para o turno, uma reabertura — dobra o histórico e se apresenta — e, para o banco, uma conversa `ATIVA`. Os dois convergem na varredura seguinte. É o mesmo desencontro que `situacao_da_conversa` já documenta para a janela vencida: *"a linha fica como estava, e esta função já conta a verdade"*.

### D4 — A dobra forçada, e a marca como fronteira

`montar_contexto` dobra **tudo** o que ficou para trás, ignorando o piso de mensagens literais que `dividir` preserva, quando o relógio diz que esta conversa reabriu.

> **Emenda D4-a (revisão final, 23/09/2026) — o gatilho mudou de lugar.** A primeira versão desta decisão dava a `montar_contexto` um parâmetro `forcar_dobra` que o turno ligava com `e_conversa_nova(message)`. **Isso nunca disparava numa rajada de volta**, que é o caso comum: o lead que sumiu manda "oi" e a pergunta no mesmo envelope, a ingestão commita as duas linhas antes de qualquer turno rodar, a primeira fecha como `agrupado` sem rodar turno e quem carrega o turno é a **mais nova** — que encontra a irmã de segundos atrás e devolve `False`. Nenhuma dobra, a transcrição velha inteira no prompt, e sem conserto nos turnos seguintes, porque o predicado continua `False` até o gatilho de acúmulo dos 40 literais.
>
> O parâmetro saiu da assinatura. `montar_contexto` decide sozinha, pelos **próprios literais**: dobra à força quando existe literal mais velho que `agora - DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` **e** existe literal a partir desse corte (`_reabriu_depois_do_silencio`). Continua sendo o relógio e não o `status`, então a D3 fica de pé. Três consequências novas: o lead novo fica coberto por construção (sem literal velho não há dobra, e o "oi" já não depende do piso de 1 para não virar resumo); a conversa cuja transcrição anterior já foi inteiramente dobrada também não dobra, e está certo, porque não há transcrição velha a tirar; e a consulta extra por turno que a versão anterior declarava desapareceu junto com a chamada. `e_conversa_nova` continua decidindo identificação e apresentação, e a cegueira dela à rajada — lacuna pré-existente da TEC-139 — permanece lá.

> **Emenda D4-b (revisão final, 23/09/2026) — o gatilho virou um INTERVALO, e o corte passou a cair dentro dele.** A forma da Emenda D4-a — *existe literal mais velho que o corte **e** existe literal a partir dele* — não é o mesmo que *"a conversa ficou 30 dias parada"*, e a diferença produziu duas regressões.
>
> 1. **Falso positivo na conversa esparsa.** Um lead que falou nos dias −45, −20, −5 e hoje satisfaz as duas pontas sem nunca ter ficado um mês calado: o maior silêncio dele é de 25 dias. Ele levava dobra forçada — a conversa inteira virando resumo menos uma mensagem, e uma chamada paga ao resumidor — e sem se apresentar, porque `e_conversa_nova`, que decide a apresentação, responde `False` para ele. Era regressão em quem não é desta card.
> 2. **Falso negativo no ramo da moderação.** Quando a fala do turno é carimbada `bloqueada_em`, `literais_apos` a filtra. Não restando literal a partir do corte, nada disparava e a transcrição anterior **inteira** ia ao prompt.
>
> A regra passa a ser: existe `i` tal que `literais[i+1].created_at - literais[i].created_at` passa de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` (`_fronteira_do_silencio`). Vale o **último** `i`, que é a reabertura mais recente. A rajada de volta continua coberta, porque o intervalo entre a cauda velha e o primeiro "oi" é exatamente o que dispara; a conversa esparsa deixa de disparar; e o ramo da moderação volta a disparar, porque a recusa de entrada que ele entrega é gravada como fala OUTBOUND do agente (`record_agent_message`, dentro de `_entregar_texto_fixo`) antes de `montar_contexto` rodar — ela é o literal recente que marca o lado novo do intervalo.
>
> **Sabendo ONDE o intervalo está, o corte deixa de ser "tudo menos a mais recente".** `_dobrar` passou a receber `manter_literais = len(literais) - (i + 1)` e a repassá-lo a `dividir` como `minimas`: dobra-se exatamente o lado velho. Daí duas consequências — o custo da rajada que a D4 declarava deixou de existir, e a comparação é **estrita** (`>`, não `>=`) para o empate continuar caindo do mesmo lado que em `e_conversa_nova`: exatamente 30 dias ainda não abre conversa nova. O que se preserva é o lado do empate, não a igualdade das medidas: lá o silêncio é contado do relógio do turno até a fala anterior, aqui entre dois `created_at`, e os segundos que separam as duas medidas cabem entre elas.
> As três consequências que a D4-a listou continuam de pé, por outro caminho: o lead novo não tem par de literais a comparar, a conversa já inteiramente dobrada não tem mais o intervalo dentro da lista, e nenhuma consulta nova entrou.
>
> **A dobra não rearma no turno seguinte.** A marca avança até `literais[i]`, então `literais_apos` passa a devolver só o que já estava depois do intervalo — e, tendo-se escolhido o último, nessa sobra não existe intervalo a achar. O que rearma é a degradação: com o resumidor fora do ar a marca não avança, os dois literais que cercam o intervalo continuam vizinhos, e o turno seguinte tenta de novo.

A marca do resumo passa a cobrir a conversa anterior inteira, e `literais_apos` devolve só o que é novo. **A fronteira vira a marca** — que já é a fronteira que o sistema tem — em vez de um filtro por `encerrada_em` ou de uma coluna nova. O agente recebe o resumo da conversa anterior e nenhuma linha da transcrição dela, que é o critério da card ao pé da letra — **e sem exceção, desde a Emenda D4-b**: o corte cai no próprio intervalo de silêncio, então o que fica literal é exatamente o que veio depois dele.

**O piso não vai a zero, vai a um**, e a primeira versão desta decisão errava nisso. Ela dizia que a fala em processamento não entra na conta, citando um comentário de `turno.py` — mas aquele comentário fala do **ramo da mensagem bloqueada pela moderação**, onde `marcar_bloqueada` já carimbou a linha e `literais_apos` filtra `bloqueada_em IS NULL`. No caminho normal a fala do lead **está** na lista: a ingestão a commita antes de enfileirar o job, e tem de estar lá, porque o job recebe o `message_id`.

Com piso zero, a dobra engoliria a fala do próprio turno — o modelo receberia `Mensagens recentes:` vazio e responderia a uma paráfrase da própria pergunta. E não só na reabertura: `e_conversa_nova` também devolve verdadeiro quando não existe mensagem anterior nenhuma, então o primeiro turno de **todo lead novo** pagaria um resumo do "oi", gravaria esse resumo permanente e mandaria contexto literal vazio — o caminho mais comum do produto.

Com piso um, a aritmética fecha nos dois casos: na reabertura, as mensagens antigas dobram e a nova fica literal; no lead novo, o único literal cabe sob o piso e `_dobrar` retorna antes de chamar o resumidor, então nem a chamada paga acontece. É a mesma invariante que `janela.py` já afirma para o `piso_pode_ceder` — a mais recente tem de sobrar, porque é a fala a que o modelo responde. **A Emenda D4-b trocou o piso por uma fronteira**, e o que sobrevive desta subseção é a refutação da premissa do piso zero, não o número um: `minimas` é hoje `len(literais) - i - 1`, que nunca chega a zero pelo mesmo argumento e preserva mais de uma mensagem quando há mais de uma do lado novo.

**O custo da rajada existiu e saiu (Emenda D4-b).** Enquanto o gatilho só dizia *se* a conversa tinha reaberto, o único corte defensável era "tudo menos a mais recente", e as demais mensagens da rajada iam para o resumo — perda de fidelidade, não de dado, declarada aqui. Com o corte caindo no intervalo, **todas** as falas novas ficam literais e não há custo a declarar.

**O ramo da moderação, e por que ele deixou de ser exceção.** Esta decisão declarava aqui um vazamento de uma linha: com a fala do turno carimbada `bloqueada_em` e fora de `literais`, o piso de uma mensagem preservaria a **última da conversa anterior**. **A declaração era falsa nos dois sentidos.** Ela não podia acontecer: o gatilho de então exigia um literal a partir do corte para disparar, e o piso de uma mensagem preserva justamente o literal mais recente — que é esse, nunca uma linha velha. E o que de fato acontecia era pior do que o declarado: não havendo literal a partir do corte, nada disparava e a transcrição anterior **inteira** ia ao prompt. A Emenda D4-b fecha os dois casos, e a Emenda E-03 ao SRS voltou a dizer *"nenhuma linha da transcrição"* sem ressalva.


**Degradação declarada.** `montar_contexto` já degrada para o resumo anterior quando `resumir` levanta `ResumoInvalido`, sem avançar a marca. Com a dobra forçada isso significa a cauda velha vazando para o prompt — a conversa nova enxerga a transcrição da anterior, que é justamente o que esta card impede. Aceito, com log próprio (`contexto.dobra_forcada_falhou`, `warning`): a alternativa seria descartar os literais sem tê-los resumido, e aí o agente perde o resumo **e** a transcrição e responde cego a um lead que ele já atendeu. Ver demais é menos ruim que não ver nada.

### D5 — O sweep não sobrescreve motivo

Ele só fecha conversa `ATIVA` ou sem linha. Conversa já encerrada por `FORA_DE_ESCOPO` ou `OPTOUT` fica como está.

Sem isso, `encerrar_conversa` — que é upsert idempotente de propósito — apagaria o motivo real 30 dias depois de ele ter sido escrito, e toda conversa do sistema convergiria para `INATIVIDADE`. O motivo é vocabulário justamente para não perder essa distinção.

### D6 — Opt-out encerra, como escrituração

No bloco `if pedido_de_optout:` (`turno.py:1325`), depois de `registrar_optout`. Só registro: quem cala é `esta_em_optout`, e o portão dele roda antes da reabertura, então a conversa encerrada por opt-out nunca é reaberta por mensagem de um lead que continua em opt-out.

**São duas transações, não uma**, e a ordem importa. `registrar_optout` recebe a `session_factory` e commita a própria sessão (`optout/repositorio.py:32`), enquanto `encerrar_conversa` recebe uma sessão e deixa o commit para quem chama — não há como juntá-las sem mudar a assinatura de uma das duas. O opt-out é gravado primeiro, pelo mesmo argumento que o bloco já usa para gravá-lo antes da entrega: morrer entre as duas deixa o lead em opt-out com a conversa ainda `ATIVA` — registro de menos, nunca mensagem a mais. A varredura da D3 fecha essa conversa por `INATIVIDADE` 30 dias depois, com o motivo menos preciso; é o custo aceito, e é menor que o de inverter a ordem.

Um lead reativado (`reativar`, `optout/repositorio.py:45`) passa a valer pelo portão e cai na reabertura normal, com dobra — o que é o comportamento certo: ele voltou depois de ter saído, e a conversa é outra.

### D7 — O que NÃO muda

- **`silencia_o_agente`** continua exigindo `FORA_DE_ESCOPO`. Ver D2.
- **A linha da reabertura continua cega ao motivo.** Os dois motivos novos reabrem como qualquer outro, que é o que a RN-02.3 pede.
- **Nada é apagado nem anonimizado.** A card põe retenção (E9, RNF-21, RNF-22) fora de escopo, e encerrar conversa não apaga nada — as mensagens continuam em `messages`, cifradas, e o resumo continua sendo o mesmo registro rolante.
- **Não nasce identidade nova de conversa.** A card diz *"uma nova conversa é criada"* e o modelo de dados do SRS diz `Lead 1:N Conversa`, mas a Emenda E-02 já decidiu que esta card estende a entidade existente, sem tabela nova. "Conversa nova" continua sendo a mesma linha reaberta, mais a apresentação, mais a fronteira de histórico que a D4 cria. **A lacuna fica declarada:** não há como listar as conversas anteriores de um lead, nem contar quantas foram, porque não existe uma linha por conversa. Quem precisar da série acrescenta a tabela de eventos — a mesma lacuna que `conversa/models.py` já declara para o histórico de encerramentos.

## Emenda ao SRS

**Emenda E-03 à RN-02.3.** O cenário *"Encerrar por handoff concluído"* da TEC-130 é descartado, em favor da Emenda E-01 desta mesma regra: concluir o handoff continua significando retomar o atendimento automático, e não encerrar. Os motivos de encerramento passam a ser três — `FORA_DE_ESCOPO` (RN-03.5), `INATIVIDADE` e `OPTOUT`. A regra ganha também o que ela sempre disse e nunca teve: *"com acesso ao histórico anterior via resumo"* passa a ser verdade por construção, porque a primeira mensagem depois do encerramento dobra o histórico no resumo antes de montar o contexto. O encerramento por inatividade conta a partir da **última fala do lead**, não da última mensagem de qualquer direção — o follow-up automático não adia o encerramento de quem sumiu.

## Testes

- Os quatro cenários do Gherkin da card, menos o do handoff (D1).
- A fronteira nos dois lados: 29 dias não encerra, 30 encerra. O empate resolve para o lado fechado, como `situacao_da_conversa` e `e_conversa_nova` já resolvem o deles — e pela mesma razão, que é as três leituras compartilharem a constante.
- O relógio ignora OUTBOUND: conversa com uma linha OUTBOUND no dia 14 e última fala do lead no dia 0 encerra no dia 30, não no 44. **A propriedade é preventiva** — ver a Emenda T-01 abaixo: hoje nenhum mecanismo grava essa linha fora do turno, então o cenário do teste é sintético e o filtro protege contra a mudança, não contra um adiamento que exista.
- A dobra forçada deixa **zero** literal da conversa anterior no contexto, e o resumo cobre o que eles diziam.
- A conversa esparsa — falas nos dias −45, −20, −5 e hoje, somando mais de 30 dias de silêncio sem nenhum intervalo de 30 — **não** dobra. É a regressão 1 da Emenda D4-b, e o teste existe para que ela não volte.
- A rajada de volta deixa **todas** as falas novas literais, e não só a mais recente. É o ganho do corte no intervalo; uma implementação que volte a "tudo menos a mais recente" reprova.
- O sweep não sobrescreve `FORA_DE_ESCOPO` nem `OPTOUT`.
- A degradação da D4: resumo falho na dobra forçada mantém o resumo anterior, loga o warning, e o turno não morre.
- Opt-out encerra com o motivo próprio, e o lead em opt-out que volta não reabre.

> **Emenda T-01 (revisão final, 23/09/2026) — a justificativa do filtro `INBOUND` era contrafactual.** Este documento e a docstring de `encerrar_inativas` diziam que contar OUTBOUND faria o follow-up da RN-13.1 empurrar o encerramento para o dia 44. **É falso.** `sweep_followups` entrega por `outbound.send` e não grava linha em `messages` — a contabilidade dele é a tabela `followups` —, e o único criador de linha OUTBOUND ali é `MessageRecorder.record_agent_message`, chamado só de `turno.py`, sempre segundos depois da INBOUND que disparou o turno. O filtro continua certo pela razão que já estava escrita ao lado dele — *"sem interação" é o lead sem interagir; o agente falando sozinho é a evidência de que não há interação* — e o argumento do follow-up passa a ser **preventivo**: para que o dia em que a entrega do follow-up virar linha em `messages` não mude o encerramento de quem sumiu.

## Fora de escopo

- **Eliminação e anonimização por retenção** (E9, RNF-21, RNF-22) — a card declara, e encerrar não apaga.
- **Identidade por conversa** — ver D7.
- **Encerramento manual pelo dashboard** — a card o cita como o contorno que existe durante o piloto, não como entrega.
- **Histórico de encerramentos** — lacuna herdada da TEC-138, não aberta por esta card.
