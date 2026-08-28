# TEC-233 — Moderação de entrada e saída em 100% dos turnos

- **Data:** 2026-08-27
- **Jira:** [TEC-233](https://eduardodurieuxlopes.atlassian.net/browse/TEC-233) · Épico [TEC-200](https://eduardodurieuxlopes.atlassian.net/browse/TEC-200)
- **Origem:** desmembrada da [TEC-210](https://eduardodurieuxlopes.atlassian.net/browse/TEC-210); RNF-26 (SRS v1.0), seção 4.4, RT-01
- **Status:** aprovado, aguardando plano de implementação
- **Descrição viva:** a seção **TEC-233** do `README.md`. Este spec está
  congelado no que foi aprovado e **não** é reescrito; onde ele e o código
  discordarem, o código ganha. A implementação divergiu nos pontos abaixo, e
  quem for ler o corpo do spec precisa deles antes:
  - **A moderação de entrada não impede que a fala vire contexto e resumo —
    só que ela vire resposta naquele turno.** A lacuna abaixo diz o contrário,
    literalmente: *"o que ela impede é que a fala vire contexto, resposta e
    resumo"*. É falso para todo turno posterior. O bloqueio retorna cedo, mas
    a linha da mensagem fica em `messages` com `status=PROCESSED` e **sem
    nenhuma marca de bloqueio**, e `literais_apos`
    (`src/mobia/domain/context/janela.py`) seleciona por conversa e
    marca-d'água do resumo, sem filtrar moderação. O turno seguinte decifra a
    fala bloqueada inteira para dentro do prompt, e na dobra dos ~40 ela entra
    no resumo permanentemente. Fechar isso exige marca na linha da mensagem
    mais filtro na janela; é card próprio, e o README declara a lacuna.
  - **São até cinco chamadas que geram texto, não quatro.** `resumir` +
    `classificar` + `desambiguar` + moderação de entrada + moderação de saída.
    O número exclui `count_tokens` (`contador.contar`), que é round trip sem
    geração e pode acontecer mais de uma vez no mesmo turno — o laço de
    truncamento de `montar_contexto` reconta a cada corte.
  - **`_entregar_texto_fixo` não garante "PROCESSED com algo entregue".** O
    spec afirma que os dois casos de bloqueio fecham o turno em `PROCESSED`
    porque algo foi entregue. Dois ramos contradizem isso: `EnvioForaDaJanela`
    devolve `"expirado"` e `reentrega_suprimida` devolve
    `"reentrega_suprimida"`, e em nenhum dos dois há garantia de que o lead
    recebeu alguma coisa. A linha fica em `PROCESSED` nos dois — o desfecho é
    terminal —, mas "PROCESSED" aqui significa "não vale retentar", não
    "entregue".
  - **O texto fixo de recusa não passa pela moderação de saída.** A garantia
    "nenhum texto é entregue ao lead sem ter passado por moderação de saída"
    tem essa exceção: `_entregar_texto_fixo` vai direto ao `outbound.send`.
    É deliberado — o texto é constante, escrito à mão neste repositório, e
    moderá-lo pagaria uma chamada para julgar algo que não veio do modelo —,
    mas a garantia, como escrita, é mais ampla que o código.
  - **O corpus tem 41 casos, não um múltiplo redondo.** `entrada_libera.yaml`
    tem 11; os outros três têm 10 cada.

## Problema

O primeiro turno que existe está no ar sem nenhuma moderação, nem de entrada nem
de saída. A única barreira é uma linha no `SISTEMA_DO_AGENTE` mandando o modelo
não inventar informação — e isso é prompt, não controle: quem depende de o
modelo obedecer não tem garantia nenhuma quando ele não obedece.

A lacuna está declarada na seção TEC-134 do README desde que o primeiro turno
foi ao ar. A TEC-210 exigia moderação em 100% dos turnos como um dos seus cinco
itens; ela foi desmembrada para cá porque **moderação é feature de produção, não
avaliação** — roda em todo turno servindo lead real, e tem latência, custo e modo
de falha próprios que nada têm a ver com medir acurácia.

## Escopo

Duas superfícies, e só elas:

| | |
|---|---|
| Fala do lead, antes de virar contexto | ✅ |
| Texto do agente, antes de ser entregue | ✅ |
| Corpus de verificação, com casos que bloqueiam e casos que não | ✅ |
| Blindagem contra prompt injection | ✗ é a [TEC-204](https://eduardodurieuxlopes.atlassian.net/browse/TEC-204) |
| Handoff humano no bloqueio | ✗ depende da [TEC-174](https://eduardodurieuxlopes.atlassian.net/browse/TEC-174), que não existe |
| Política de retenção e não-treinamento | ✗ é a [TEC-234](https://eduardodurieuxlopes.atlassian.net/browse/TEC-234) |

A distinção com a TEC-204 é a que mais confunde: lá é o lead tentando sequestrar
a instrução do agente; aqui é conteúdo impróprio em qualquer direção. Uma fala
pode ser as duas coisas, e cada card cobre a sua metade.

## Abordagem: uma porta, chamada pelo turno

`ModeradorPort` ao lado de `ClassificadorPort` e `OutboundPort`, com
`ModeradorAnthropic` em `infra/`. O turno chama nas duas pontas.

**Por que no turno, e não num decorador do outbound.** O repositório já tem o
padrão de decorar a saída — `GuardedOutbound` faz isso para a reserva de envio —
e a primeira ideia foi repetí-lo. Não funciona: `record_agent_message(text=...)`
grava **o texto entregue**, e um decorador que substituísse o texto por dentro
faria o recorder gravar o texto barrado. O histórico do lead passaria a conter
uma fala que ele nunca viu, que entra no contexto do turno seguinte e depois é
dobrada permanentemente no resumo. É exatamente o defeito que a docstring de
`executar_turno` já descreve como o pior desfecho possível. A substituição tem
de acontecer onde o turno decide o que enviar **e** o que gravar.

**Por que não na ingestão.** Barrar a fala imprópria antes de enfileirar é mais
barato e impediria que ela virasse contexto. Mas a resposta ao lead teria de
sair da API, que hoje não entrega nada — a entrega inteira vive no worker.
Inventar um segundo caminho de saída para economizar um job é caro pelo lado
errado. Fica registrado como a forma melhor caso a API ganhe entrega própria.

## A porta

```python
class Direcao(StrEnum):
    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"


@dataclass(frozen=True)
class Veredito:
    bloqueado: bool
    motivo: str


class ModeradorPort(Protocol):
    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito: ...
```

A direção não é decoração: o prompt difere. Na entrada julga-se a fala de um
estranho, e o critério é o que não pode entrar no contexto do agente. Na saída
julga-se o que a imobiliária vai dizer em nome próprio, e o critério é mais
estrito — o mesmo texto pode ser tolerável vindo do lead e inaceitável vindo da
empresa.

`motivo` existe para o log e para o corpus de verificação; ele **nunca** carrega
o texto julgado.

## Cliente próprio, com teto curto

`ModeradorAnthropic` **não** reusa `get_client()`. Cliente separado,
`timeout=5s`, `max_retries=0`, e modelo próprio em `Settings`:
`modelo_moderacao`, ao lado de `modelo_agente` e `modelo_resumo` que já existem.

O campo é separado de propósito. Moderar é classificação binária sobre texto
curto, e não precisa do modelo que escreve a resposta — amarrar os dois faria
uma troca de `modelo_agente` mudar em silêncio o custo e a latência da
moderação de todo turno. É também o buraco que a TEC-210 declara no filtro do
gate: `config.py` muda por muitos motivos, e trocar modelo passa sem re-medir.

O cliente atual tem `TIMEOUT_SEGUNDOS = 60` e `MAX_TENTATIVAS = 1`, ou seja 120s
de pior caso por chamada, contra um `job_timeout` de 240s. O turno já estoura o
orçamento no pior caso — `resumir` + `classificar` + `desambiguar` dão 360s, e
isso está documentado no comentário de `job_timeout` e na TEC-135. Moderar com o
mesmo cliente somaria 240s a um orçamento já estourado; com teto de 5s e sem
retentativa, soma 10s, que é ruído contra os 120s de folga que já não existem.

Reduzir a chance de estourar é a
[TEC-228](https://eduardodurieuxlopes.atlassian.net/browse/TEC-228), não este
card. O que este card não pode fazer é piorar materialmente o problema, e 10s
não pioram.

## O fluxo

**Entrada.** Primeira coisa do `executar_turno`, antes de `montar_contexto`. O
turno passa a decifrar `message.text_body` — mesma chamada que `_texto_da` já faz
em `montagem.py`. Bloqueado: entrega o texto fixo de recusa, grava, e retorna
sem **nenhuma** chamada ao modelo. O turno inteiro é economizado, que é o efeito
colateral bom de moderar antes.

**Saída.** Depois de escolhido o texto que vai ser entregue — a resposta da
chamada 1, ou a pergunta de desambiguação, o que for — e antes do
`outbound.send`. Bloqueado: substitui pelo texto fixo neutro, e é o texto fixo
que vai para o `send` e para o `record_agent_message`.

A saída é moderada **uma vez por turno**, não duas. No caminho ambíguo a resposta
da chamada 1 é descartada e só a pergunta é entregue; só um texto sai, então só
um texto é julgado.

## Falha do moderador: assimétrica, e de propósito

Quando o moderador **falha** — timeout, indisponibilidade, resposta inutilizável
— é diferente de quando ele funciona e diz não.

**Entrada falha aberta.** O turno segue sem moderação de entrada, com evento
próprio no log. A fala do lead já está cifrada no banco de qualquer jeito: a
ingestão a gravou antes de o worker existir. Negar atendimento a um lead legítimo
porque um serviço caiu pune o inocente por um problema alheio à conversa dele.

**Saída falha fechada.** Não entrega. A exceção propaga, a linha vira `FAILED`
com `attempts` incrementado, e o sweeper retenta — o mesmo caminho de qualquer
falha recuperável do turno. Entregar texto não moderado é precisamente o risco
que este card existe para fechar, e a assimetria é essa: na entrada o custo de
falhar aberto recai sobre o contexto do agente; na saída, sobre a reputação da
imobiliária, em público.

## O que o lead recebe quando é bloqueado

Texto fixo nas duas pontas, e **nunca silêncio**.

O silêncio é o pior desfecho, e este repositório já decidiu isso duas vezes: a
TEC-134 escolheu a duplicata sobre a perda porque *"ela é visível e recuperável,
o silêncio não"*, e a TEC-227 repetiu o critério. Um lead bloqueado por falso
positivo — e falso positivo em moderação é comum — que não recebe nada não tem
como saber que precisa reformular.

- **Entrada bloqueada:** recusa curta e neutra, que não acusa nem explica o
  critério. Explicar o critério ensina a contorná-lo.
- **Saída bloqueada:** texto neutro que não finge ser resposta. O lead percebe
  que algo não saiu como devia, e o evento no log leva um humano até ali.

Os dois casos fecham o turno em `PROCESSED`: algo foi entregue.

## Telemetria

`moderacao.entrada_bloqueada` e `moderacao.saida_bloqueada`, ambos em `error` —
é o nível que o alerta observa, pelo mesmo critério que `outbound.recusado` e
`turno.reentrega_suprimida` já usam.

`moderacao.indisponivel` para a falha do moderador, com a direção, para que o
bypass da entrada seja visível. Moderação que se desliga em silêncio quando o
serviço cai é moderação que não existe justamente quando ninguém está olhando.

**O texto julgado nunca entra no log**, nas duas direções. Na entrada é fala do
lead, coberta pela mesma regra de PII que o resto do sistema segue. Na saída é o
conteúdo impróprio em si — registrá-lo criaria, no log, exatamente aquilo que a
moderação impediu de sair.

## O corpus de verificação

`evals/moderacao/*.yaml`, ao lado do corpus de intenção da TEC-210, com a mesma
disciplina: rótulo anotado à mão, texto escrito antes do rótulo.

**Casos que devem bloquear e casos que não devem, nos dois.** Um moderador que
bloqueia tudo passa em corpus só-positivo, e é o modo de falha mais fácil de
enviar sem perceber — ele parece seguro. O corpus de controle é o que separa
moderação de censura.

Cobertura mínima: conteúdo discriminatório explícito e velado; ameaça direta e
educada; assédio; e o lado negativo — lead irritado, gíria, palavrão comum
brasileiro em contexto inofensivo, e reclamação legítima. Um lead que escreve
"que porcaria de atendimento" não pode ser bloqueado.

## Testes

- Dublê de moderador, como os outros ports, para os caminhos do turno: entrada
  bloqueada não chama o modelo; saída bloqueada substitui o texto **e** grava o
  texto substituído; falha na entrada segue; falha na saída não entrega.
- O teste que prova que o recorder grava o texto **entregue** e não o barrado é
  o que fixa a razão de a moderação viver no turno. Sem ele, alguém move para um
  decorador e reintroduz a fala fantasma.
- O corpus roda contra o modelo real em `evals/test_moderacao.py`, **arquivo
  próprio**, e não como métrica nova dentro do gate de intenção.

  A separação importa. O gate de intenção tem três slots em `SEM_MECANISMO`
  esperando features que não existem — extração, alucinação, tom —, e moderação
  não é nenhum deles: encaixá-la ali confundiria "a métrica ganhou mecanismo"
  com "chegou uma métrica nova". Como arquivo próprio, ela é coletada pelo mesmo
  `pytest evals` e roda no mesmo workflow, sem tocar no runner de intenção nem
  nos pisos dele.

  Duas medidas, com pisos próprios: **taxa de bloqueio** no corpus positivo, e
  **taxa de falso positivo** no corpus de controle. Nenhum dos dois pisos é
  cravado neste spec — a TEC-210 provou que piso não medido abre vermelho na
  primeira execução sem regressão nenhuma. Medir primeiro, cravar depois.

## Garantias

- Nenhum texto é entregue ao lead sem ter passado por moderação de saída, ou sem
  que a falha em moderá-lo tenha impedido a entrega.
- Nenhuma fala do lead vira contexto para o modelo sem ter passado por moderação
  de entrada, ou sem que a falha em moderá-la esteja registrada.
- Bloqueio nunca produz silêncio.
- O conteúdo julgado não aparece em log nenhum.
- Moderar acrescenta no máximo 10s ao pior caso do turno.

## Lacunas conhecidas

- **A moderação de entrada não impede que a fala exista.** Ela roda no worker,
  depois de a ingestão ter gravado a mensagem cifrada. O que ela impede é que a
  fala vire contexto, resposta e resumo. Apagar o que já entrou é assunto da
  TEC-234 e da política de retenção.
- **Falha aberta na entrada é um buraco declarado.** Enquanto o moderador estiver
  fora, falas impróprias entram no contexto normalmente. O evento
  `moderacao.indisponivel` existe para que isso seja visível, mas visibilidade
  não é barreira.
- **O turno passa a ter até quatro chamadas ao modelo** contra um `job_timeout`
  que já estoura em 360s no pior caso. Os ~10s da moderação são marginais, mas
  somam a um problema que já existe e pertence à TEC-228.
- **Falso positivo custa atendimento.** Um lead legítimo bloqueado recebe recusa
  e não é atendido naquele turno. O corpus de controle mede a taxa; nada no
  código a limita.
- **Não há revisão humana.** Bloqueio vira log, e log vira alerta se alguém
  configurar o alerta. Ninguém revisa fila de bloqueios, e o handoff humano é a
  TEC-174.
- **A moderação julga texto isolado, não conversa.** Uma sequência de falas
  individualmente inofensivas pode compor assédio, e nada aqui vê isso.
