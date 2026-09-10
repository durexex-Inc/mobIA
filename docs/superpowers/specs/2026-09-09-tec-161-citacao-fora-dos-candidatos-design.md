# TEC-161 — Bloquear resposta que cite imóvel fora dos candidatos

**Status:** desenhado em 2026-09-09 na branch `feat/tec-161-citacao-fora-dos-candidatos`.

**Card:** [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161) — Must (MoSCoW), prioridade Highest. Origem: RF-09 (RN-09.4), RT-01, RNF-26. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155). Consta no Anexo B como item que nunca deve ser cortado.

**Destravada pelas duas bloqueadoras:** [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) (a busca híbrida) e [TEC-265](https://eduardodurieuxlopes.atlassian.net/browse/TEC-265) (a ligação ao turno, que criou `RespostaDoAgente.candidatos`), ambas em **Feito**.

**Encolhida pela [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162)**, já mergeada — o comentário de 09/09 na card registra o achado e este desenho o executa.

## Objetivo

Nenhuma cifra e nenhum código de imóvel chegam ao lead sem corresponder ao que o banco devolveu naquele turno. A validação é determinística, roda sobre a prosa do modelo antes de qualquer reserva em `outbound_dispatches`, e não gasta uma segunda chamada paga.

## O estado de hoje, medido

- **A ficha não passa pelo modelo.** `_apresentar` (`domain/agente/turno.py`) monta os oito campos da RN-10.1 a partir de `fichas_do_catalogo`, que lê do banco. A D3 da TEC-162 é explícita: nenhum campo da ficha pode ser inventado porque nenhum campo da ficha vem do modelo.
- **A prosa do modelo é o prefixo da legenda da ficha 1**, e só dela (D5 da TEC-162). Nos turnos que não apresentam, ela é a mensagem inteira.
- **`RespostaDoAgente.candidatos`** existe desde a TEC-265, com o comentário que antecipa esta card: lista vazia significa "não houve busca neste turno", e o campo não é opcional exatamente para que "não buscou" e "buscou e não achou" levem à **mesma** decisão aqui.
- **O modelo vê** `imovel_id`, `codigo`, `titulo`, `bairro`, `preco_centavos`, `quartos`, `vagas`, `area_util_m2` (`_candidato_serializavel`, `domain/agente/ferramenta_de_busca.py`). O preço vai como inteiro em centavos, e o comentário de lá diz que é assim porque é o que esta card vai comparar.
- **A instrução já existe e não é guarda.** A `description` de `FERRAMENTA_DE_BUSCA` diz *"Busca no catalogo. Nunca cite imovel que nao veio dela."* — o que falta é a verificação, não o pedido.
- **A moderação de saída não regenera.** Bloqueou, ela troca `texto` por `TEXTO_NEUTRO_DE_SAIDA` e o turno segue. É o precedente mais próximo desta card e está no mesmo arquivo, antes do ponto de enxerto.
- **A margem do orçamento do prompt é de 6,0 tokens** (líquido 780,0 contra teto fixo de 786), medida em 2026-09-09 por `pytest -k margem_do_orcamento -s`. Esta card não gasta nada dela.
- **Códigos do catálogo** têm a forma `AP-1004`, `CA-1005`, `TE-1001` no seed (`data/seed/imoveis.csv`); a coluna é `String(20)` e não tem constraint de formato.

## Decisões

### D1 — Um módulo puro, e não mais lógica dentro do `turno.py`

`domain/agente/citacao.py`, sem I/O, sem banco e sem chamada ao modelo, no molde de `apresentacao.py` e `dinheiro.py`. `turno.py` já tem 53 KB e `executar_turno` sozinha ocupa 647 linhas; o validador entra lá como uma chamada e um `if`.

```python
@dataclass(frozen=True, slots=True)
class Divergencia:
    tipo: Literal["preco", "codigo"]
    citado: str

def divergencias_de(
    prosa: str,
    *,
    candidatos: Sequence[Mapping[str, Any]],
    faixa: tuple[int | None, int | None],
) -> tuple[Divergencia, ...]: ...
```

Tupla vazia significa que a prosa passa. `Divergencia.citado` já vem formatado para o log (ver D10) e **nunca** carrega a prosa inteira.

### D2 — Número só é dinheiro se tiver marcador

Marcador é `R$`, a palavra `reais`, ou sufixo de grandeza (`mil`, `milhao`, `milhoes`). Sem essa exigência, `2 quartos`, `80 m2`, `3 opções` e `andar 12` viram preço, e a guarda passa a bloquear turno correto — que é o único jeito de uma guarda anti-alucinação perder a confiança de quem opera.

**Consequência declarada:** *"esse aí sai por 750"* não é detectado. A guarda **erra por falta**, e essa é a política que o `dinheiro.py` já declara no próprio docstring: *"A gramatica e lista fixa e erra por falta; estende-la e decisao de card"*. Esta card não a estende para além do marcador.

### D3 — A gramática monetária é a do `dinheiro.py`, estendida — não uma gêmea

Entra em `domain/agente/dinheiro.py` uma função pública:

```python
def valores_em(texto: str) -> tuple[int, ...]:
    """Todos os valores monetarios do texto, em centavos, na ordem em que aparecem."""
```

Ela reusa `_RUIDO`, `_BEM_FORMADO` e `_resolver`, que já resolvem "quinhentos mil", "1,2 milhão" e "R$ 516.464,30". Um segundo parser de expressão monetária em português neste repo seria duas gramáticas divergindo em silêncio — o mesmo defeito que o `CLAUDE.md` descreve para comentário desatualizado, na forma de código.

`valores_em` herda a garantia que o módulo inteiro tem: **não levanta**. Qualquer sequência de caracteres é entrada válida, porque a prosa vem do modelo repetindo a fala do lead.

### D4 — Tolerância de 10% contra o preço do candidato

O modelo lê `preco_centavos: 51646430` e escreve *"R$ 516 mil"*, *"cerca de 500 mil"* ou *"R$ 516.464"*. Igualdade exata reprovaria prosa correta em quase todo turno.

Um valor da prosa passa se, para **algum** candidato, `abs(citado - preco) / preco <= 0,10`. Assim `500 mil` contra `516.464` passa (3,2%) e `700 mil` bloqueia (35%).

**O número não é derivado — é emprestado da RN-09.3**, que relaxa a faixa de preço em até 10%. As duas coisas são semanticamente diferentes (relaxar busca não é tolerar citação), e a escolha é deliberada: inventar uma segunda constante de tolerância obrigaria a defender um número novo sem dado para calibrá-lo. Quando houver medição de campo, o lugar de mexer é uma constante só.

**A janela é real e é o custo aceito:** num imóvel de R$ 500 mil, 50 mil reais de erro na prosa passam. O que a torna tolerável é que a ficha logo abaixo, na mesma mensagem, mostra o preço do banco — a prosa erra, o dado corrige, e o lead não descobre na visita.

### D5 — A faixa declarada pelo lead é valor legítimo

`depois_do_estado` (`LeadQualification`, gravado no mesmo turno) carrega `faixa_preco_min_centavos` e `faixa_preco_max_centavos` acumulados, e está em escopo no ponto de enxerto. Um valor da prosa dentro dessa faixa passa mesmo sem casar com candidato nenhum.

Sem isso, *"entendi, até R$ 600 mil"* — o modelo ecoando o que o lead acabou de dizer — viraria bloqueio, e num turno de qualificação pura (sem busca, sem candidato) todo eco de orçamento bloquearia. `depois_do_estado` é `None` no turno mais comum de todos — aquele em que o lead não disse nada novo sobre orçamento e `gravar_estado` por isso não grava linha —, e é exatamente nesse turno que o eco acontece com mais frequência. Por isso o ponto de enxerto usa `depois_do_estado or contexto.estado`: quando o turno atual não gravou nada, cai no estado de antes dele, que já carrega a faixa de um turno anterior. A válvula só fica ausente quando não há nenhuma linha `lead_qualification` para o lead — nem a de antes, nem a de depois —, e só nesse caso todo valor tem de casar com candidato.

### D6 — Código pelo formato do catálogo

`\b[A-Z]{2,3}-\d{3,6}\b`. Cada achado tem de ser o `codigo` de algum candidato do turno, comparado por igualdade exata — código não tem tolerância.

**Consequência declarada:** a coluna é `String(20)` sem constraint de formato, então um catálogo com código de outra forma não é detectado. Erra por falta, como a D2.

### D7 — Valida sempre, contra o que o banco devolveu neste turno

A validação roda sobre **todo** texto que o modelo escreveu e que vai sair, inclusive com `candidatos == []`. Esse é o caso RT-01 mais puro — o modelo não chamou a ferramenta e mesmo assim citou preço — e é a lacuna 3 que a TEC-265 deixou aberta de propósito. Com lista vazia nenhum valor casa, então só a faixa da D5 passa.

No caminho de desambiguação, o texto entregue é a pergunta da chamada 2, e ela é validada contra `gerada.candidatos` da chamada 1. A chamada 1 foi descartada como **texto**, mas seus candidatos são linhas do banco: aceitá-los não abre buraco nenhum, e recusá-los bloquearia pergunta legítima.

A validação roda **depois** da moderação de saída, sobre o texto que de fato vai sair. Se a moderação já substituiu por `TEXTO_NEUTRO_DE_SAIDA`, esta guarda passa trivialmente — texto fixo nosso não tem cifra. Não há interação entre as duas.

### D8 — Não regenera: descarta a prosa

O enxerto fica em `executar_turno` depois do bloco da moderação de saída **e** depois do cálculo de `apresentando` — a guarda usa esse valor para decidir o desfecho do bloqueio — mas **antes** de `_apresentar`, que é quem grava reserva em `outbound_dispatches` e entrega. Bloquear depois de `_apresentar` deixaria reserva gravada e mensagem entregue.

- **Turno de apresentação:** a prosa vira `""` e `legenda_de` omite o prefixo. O lead recebe as fichas puras, montadas do banco. Nenhum conteúdo da RN-10.1 se perde — o docstring de `legenda_de` já diz que, sob pressão de espaço, *"o que se corta e o PREFIXO -- nunca a ficha. A ficha e o conteudo que a RN-10.1 exige e a prosa e ornamento"*. Esta card aplica a mesma ordem de prioridade sob pressão de confiança.
- **Turno que não apresenta:** `texto = TEXTO_DA_BUSCA_INCONCLUSIVA`.

**Por que não regenerar**, contra a letra da RN-09.4 (ver Emendas):

1. **O precedente do próprio arquivo.** A moderação de saída barra e substitui; não paga uma segunda geração. Duas guardas de saída no mesmo turno com desfechos opostos seriam duas políticas para o mesmo problema.
2. **A segunda chamada custa mais do que uma chamada.** Ela reexecuta o laço de tool use da TEC-265 — uma busca nova, com embedding — dentro de um `job_timeout` de 240s que o comentário de `infra/anthropic.py` já descreve como estourado no pior caso das chamadas existentes.
3. **Ela compra pouco.** Mesmo contexto, mesmos candidatos, outra amostra: nada garante que a segunda prosa não invente também. O quarto cenário da card existe justamente porque quem escreveu a regra já previa a segunda falha.
4. **O que a regeneração tentava salvar já está salvo.** Quando a card foi escrita, a resposta era texto livre e descartá-la deixava o lead sem nada. Depois da TEC-162, descartar a prosa ainda entrega até três fichas corretas do banco.

### D9 — Um texto conservador, não dois

O comentário da card deixa em aberto se a resposta conservadora do quarto cenário é a mesma `TEXTO_DA_BUSCA_INCONCLUSIVA` que já existe. **É a mesma.** Ela diz *"Deixa eu confirmar algumas coisas com um corretor para nao te passar informacao errada. Ja te retorno com as opcoes."* — literalmente a proposta de verificação humana que o cenário pede.

`TEXTO_NEUTRO_DE_SAIDA` foi considerado e recusado: ele pede que o lead repita a última mensagem, o que convida exatamente o mesmo turno a acontecer de novo.

**Custo herdado, declarado:** a promessa *"já te retorno com as opções"* não se cumpre sozinha — nada no sistema reagenda o turno. Esse custo **já existe** hoje no caminho do `LacoDeBuscaExcedido`, que entrega esse mesmo texto. Esta card o herda; não o introduz e não o resolve.

### D10 — O evento é log estruturado, e o denominador já existe

```python
log.error(
    "citacao.bloqueada",
    channel=message.channel,
    message_id=str(message.id),
    tipos=[d.tipo for d in divergencias],
    citados=[d.citado for d in divergencias],
    candidatos=len(gerada.candidatos),
    apresentando=apresentando,
)
```

**A prosa não entra no log**, pela mesma razão que o texto barrado pela moderação não entra: registrá-la criaria no log exatamente aquilo que a guarda impediu de sair. Os valores divergentes entram porque são o que o modelo inventou, e são o único dado que torna a linha investigável.

`Divergencia.citado` sai **formatado por `reais_de`** (`R$ 749.000`), e não em centavos. Não é cosmético: `_mascarar_digitos` (`app/logging.py`) come corridas de 10 a 15 dígitos, e um imóvel de R$ 10 milhões em centavos são exatamente 10 dígitos — o valor sairia mascarado do log justamente no caso caro. Com pontos de milhar não há corrida.

**A taxa não precisa de tabela nova.** Numerador: os eventos `citacao.bloqueada`. Denominador: as linhas de `message_telemetry`, uma por turno, que já existem.

### D11 — Orçamento do prompt: zero

Nenhum campo novo no schema compilado, nenhuma frase nova em `SISTEMA_DO_AGENTE`, nenhuma propriedade nova em `FERRAMENTA_DE_BUSCA`. A margem de 6,0 tokens fica intacta.

A alternativa recusada era pedir ao modelo que declarasse quais imóveis citou, num campo novo do schema. Ela tornaria a detecção trivial e é **exatamente a errada**: a guarda anti-alucinação passaria a depender da honestidade do mesmo modelo que ela existe para checar, e ainda gastaria mais do que a margem inteira tem.

## Fluxo

```
executar_turno
  ...
  moderacao de saida  ──bloqueou──> texto = TEXTO_NEUTRO_DE_SAIDA
  │
  ├─ apresentando = bool(candidatos) and not perguntou and not desambiguando
  │
  ├─ divergencias_de(texto, candidatos=gerada.candidatos, faixa=...)
  │     vazio ──────────> segue com a prosa do modelo
  │     nao vazio ──────> log.error("citacao.bloqueada")
  │                       apresentando?  sim → prosa = ""
  │                                      nao → texto = TEXTO_DA_BUSCA_INCONCLUSIVA
  │
  └─ _apresentar(...) ──> outbound.send  (primeira reserva em outbound_dispatches)
```

O bloqueio acontece à esquerda da primeira reserva. É a invariante que a card cobra e a única ordem que o comentário do Eduardo aceita.

## Testes

**Unitários, `tests/unit/test_citacao.py`** — sem banco, sem rede:

- Tabela da D2: texto com marcador vira valor; `2 quartos`, `80 m2`, `andar 12` não viram.
- Tabela da D4: `500 mil` contra `516.464` passa; `700 mil` bloqueia; limite exato de 10% dos dois lados.
- D5: valor dentro da faixa do lead passa sem candidato; com `faixa=(None, None)` bloqueia.
- D6: `AP-1004` de candidato passa; `AP-9999` bloqueia; código de outra forma não é detectado (a lacuna, travada como teste).
- D7: `candidatos=[]` com cifra na prosa bloqueia.
- Os quatro cenários Gherkin da card, na redação nova (ver abaixo).

**Unitários, `tests/unit/test_dinheiro.py`** — a tabela de `valores_em`, incluindo o texto que não contém valor nenhum e o que contém três.

**Integração, sobre `executar_turno`:**

- Turno de apresentação com prosa divergente: o lead recebe as fichas, `outbound.send` é chamado com legenda **sem** prefixo, e o evento sai.
- Turno que não apresenta com prosa divergente: o texto entregue é `TEXTO_DA_BUSCA_INCONCLUSIVA`.
- Prosa consistente: nada muda em relação ao comportamento de hoje.
- **Nenhuma reserva é gravada antes da validação** — o teste que trava a ordem da D8.

Todos com dublê do cliente do modelo, no molde de `_ClienteFalso` (`tests/unit/test_classificador.py`). **Nenhum teste desta card gasta crédito.**

## Emendas ao SRS

**Duas**, e são a contrapartida honesta da D8.

- Sob a **RN-09.4**, `Emenda E-01 (TEC-161, 09/09/2026)`: onde a regra diz que citação fora da lista *"bloqueia o envio e força regeneração"*, passa a valer que ela **bloqueia a prosa e entrega a ficha montada do banco**, sem segunda geração. O argumento é o da D8, e o fato novo que o justifica é a TEC-162: quando a regra foi escrita, a resposta inteira vinha do modelo e descartá-la deixava o lead sem nada.
- Sob a **CA-09.2**, `Emenda E-01 (TEC-161, 09/09/2026)`: o critério passa a ser *"o envio da prosa é bloqueado e o lead recebe a ficha do banco"*, remetendo à emenda da RN-09.4.

Nenhuma das duas reescreve o texto de 22/08/2026, conforme a regra de emendas do `CLAUDE.md`.

## A card precisa ser reescrita antes do plano

Os cenários 1 e 4 da TEC-161 falam em regerar, e a D8 não regera. **Cards são a fonte de requisitos e quem as escreve é o dono do projeto** — este desenho propõe a redação, não a aplica:

```gherkin
  Cenário: Resposta que cita imóvel fora da lista tem a prosa descartada
    Dada uma resposta gerada citando preço ou código fora dos candidatos
    Quando ela é validada antes do envio
    Então a prosa não é enviada
    E o lead recebe as fichas montadas do banco, sem prefixo

  Cenário: Sem ficha para entregar, o lead recebe verificação humana
    Dada uma prosa bloqueada num turno que não apresenta imóvel
    Quando ela é validada
    Então o lead recebe o texto de verificação com o corretor
    E nenhuma segunda geração é tentada
```

Os cenários 2 (preço divergente bloqueia) e 3 (resposta consistente passa) seguem válidos como estão.

## Lacunas declaradas

1. **Paráfrase sem número passa.** *"Tenho um bem espaçoso na praia"*, sobre imóvel que não existe, não é detectável sem um juiz LLM. A guarda cobre cifra e código, que é onde a promessa falsa vira reclamação na visita. Um juiz LLM foi recusado por custo e por fazer a guarda depender de um modelo.
2. **A tolerância de 10% é uma janela real** (D4), e o número é emprestado, não medido.
3. **O formato de código é o do seed** (D6).
4. **Bairro e título não são validados.** O modelo os ecoa legitimamente — o lead pediu Trindade, a prosa diz Trindade — e checá-los produziria bloqueio em turno correto. Consequência: *"tenho ótimas opções no Itaim"* sem candidato no Itaim passa, desde que sem cifra.
5. **A ausência de busca continua sem guarda.** Esta card valida o que a prosa afirma; ela não obriga o modelo a chamar a ferramenta. É a mesma lacuna 3 da TEC-265, e o lugar de olhar continua sendo a taxa de `tool_use` por turno, que a TEC-211 vai instrumentar.
6. **A guarda valida contra todos os candidatos, não só os entregues.** `gerada.candidatos` carrega até dez, por RN-09.2, e `_apresentar` só entrega os três primeiros. Prosa que cita o preço exato do candidato #7 passa a guarda — o valor é real, veio do banco — e o lead recebe as fichas 1 a 3, sem nenhuma delas para conferir o número. Estreitar a base da guarda para os três entregues é o remédio errado: trocaria um falso negativo com lastro no banco (o preço citado existe, só não foi mostrado) por falsos positivos sem lastro nenhum, bloqueando prosa correta toda vez que ela mencionar a #4 em diante.
7. **Valores secundários não são preço de candidato.** Condomínio, IPTU, entrada e ITBI não entram em `_candidato_serializavel` — o modelo não vê `condominio` — e por isso só passam pela válvula da D5, se o valor citado couber na faixa que o lead já declarou. *"o condomínio fica em torno de R$ 500"* bloqueia para um lead que declarou "de 300 a 450 mil": nem candidato nem faixa sustentam os R$ 500. Frequência baixa, porque o modelo tem pouco motivo para se voluntariar a citar condomínio sem o dado à vista, mas é a classe de entrada mais provável de queimar um turno correto, já que o valor é verdadeiro e ainda assim bloqueia.
8. **Um turno com duas buscas valida contra a última, não contra as duas.** `classificador.py:519` atribui `candidatos = _candidatos_de(...)` a cada chamada de ferramenta, sem acumular as anteriores — comportamento pré-existente da TEC-265, e consistente com o que `_apresentar` mostra, que também só conhece a busca final. Esta card é a primeira consumidora que transforma essa atribuição numa decisão de bloqueio: prosa que cita um candidato só visto na primeira busca do turno bloqueia, mesmo que o valor tenha vindo do banco.

## Fora de escopo

- **A suíte de avaliação de alucinação no CI (E9 / RNF-26)** — aqui se entrega o mecanismo, lá a medição contínua. É a TEC-210, que declara esta card como bloqueadora da métrica "taxa de alucinação".
- **A regra de conduta do agente** (TEC-141), que esta card torna verificável mas não implementa.
- **Persistir o conjunto recomendado** (`Recomendacao`, TEC-163), que resolveria a L1 da TEC-162 e não é condição para nada aqui.
