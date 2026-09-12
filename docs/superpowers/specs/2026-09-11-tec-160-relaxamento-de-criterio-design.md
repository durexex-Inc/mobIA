# TEC-160 — Relaxar o critério quando a busca não devolve nada

**Status:** desenhado em 2026-09-11.

**Card:** [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) — História, Should (MoSCoW), prioridade High. Origem: RF-09, RN-09.3 e CA-09.3 (SRS v1.0). Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**A história:** *"Como Marina, cujo critério não achou nada, quero receber opções próximas em vez de um 'não encontrei', para não sair da conversa de mãos vazias."* O contorno que a card registra, e que esta implementação substitui, é o agente admitir que não achou e encaminhar ao corretor — *"funciona, mas perde a conversa"*.

**Desbloqueada pela [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158)** (a busca híbrida, que é o passe que esta card aprende a repetir) **e pela [TEC-262](https://eduardodurieuxlopes.atlassian.net/browse/TEC-262)**, mergeada como `6c74206`. A segunda não é dependência de código: o desenho dela registra que *"a TEC-160 existe para relaxar zero-resultados e o relaxamento que a RN-09.3 descreve é de faixa de preço e bairros adjacentes. Um zero causado por tipo sem par no catálogo é invisível para ela: relaxaria preço e bairro de uma busca que nunca teve chance."* Com `RURAL` no catálogo, esse zero deixou de existir.

**Esta card foi encomendada por escrito pela TEC-158.** O plano dela deixou um teste órfão: *"o clamp em 0 da aderência é inalcançável enquanto o filtro é duro (...) o teste dele pertence à card que abre o caminho. Escrever agora um teste que exercita um estado inalcançável seria testar a implementação em vez do comportamento."* Esta é a card que abre o caminho, e a D2 abaixo é o motivo de o teste ser não-trivial.

## Objetivo

Fazer valer a RN-09.3: busca sem resultado executa **um** relaxamento automático — faixa de preço em até 10% e bairros adjacentes — e o lead é avisado de que o critério foi ampliado.

**O que a card entrega:** a política de relaxamento em módulo próprio, a tabela de adjacência com carga, o estado do relaxamento nos dois contratos de saída (o `tool_result` do agente e o `POST` da seção 6.3), o aviso ao lead como mensagem própria dizendo em que dimensão ampliou, o desfecho quando nem ampliando aparece algo, e as duas emendas ao SRS que a regra exige para deixar de se contradizer.

**O que ela não entrega:** relaxamento de tipo, quartos ou vagas (a RN-09.3 não os menciona — ver a L3); adjacência de outras cidades (L1); e a medição do SLA do caminho relaxado, que é da TEC-159 (L4).

## O estado de hoje

`buscar()`, em [`domain/catalogo/busca.py`](../../../src/mobia/domain/catalogo/busca.py), é uma passagem única de SQL: filtro duro no `WHERE`, score no `ORDER BY`, `count() over()` para o total antes do `LIMIT`. Zero resultado devolve `ResultadoDaBusca` com tupla vazia e `total_candidatos = 0` — e isso não é erro, é o que a TEC-158 deliberadamente deixou como porta para esta card.

Dois chamadores: `porta_de_busca` em [`domain/agente/ferramenta_de_busca.py`](../../../src/mobia/domain/agente/ferramenta_de_busca.py), que é o tool call do agente, e o `POST /api/v1/imoveis/busca` em [`api/routes/imoveis.py`](../../../src/mobia/api/routes/imoveis.py). Os dois precisam do campo novo: a seção 6.3 do SRS já escreve `"relaxamentoAplicado": false` no exemplo de resposta, na linha 1048.

Não existe tabela de adjacência, nem módulo, nem seed. O catálogo simulado tem **12 bairros numa cidade só** (Florianópolis), cada um com `zona` preenchida, e `Imovel.bairro_busca` guarda a forma dobrada contra a qual o filtro compara.

## Decisões

### D1 — A política mora em módulo próprio, e `buscar()` continua sendo um passe

Módulo novo `domain/catalogo/relaxamento.py`, com `buscar_com_relaxamento()`, `alargar()` e o lookup de adjacência. Importa `busca.py` numa direção só.

A alternativa era `buscar()` relaxar por dentro — uma função, dois passes, os dois chamadores ganhando sem mudar. Recusada por duas razões. A primeira é que a docstring de `busca.py` afirma que *"não precisa de CTE nem de duas viagens ao banco"* e deriva dali a garantia de latência; uma função que faz duas viagens sob esse texto o torna falso, e este repo trata comentário desatualizado como defeito. A segunda é que montar a consulta e decidir a política de zero-resultado são responsabilidades diferentes, e separá-las dá à RN-09.3 um nome próprio nos testes.

A terceira alternativa — a política duplicada nos dois chamadores — foi descartada sem discussão: é exatamente o que os comentários de `COLUNA_DE_PRECO` e `_INCLUSOES` recusam em voz alta.

### D2 — A divergência entre o `WHERE` e a âncora mora num campo de `FiltroDeBusca`

`FiltroDeBusca` ganha `relaxado: bool = False`.

**Este é o coração da card, e a implementação óbvia erra aqui.** A emenda E-01 da RN-09.6 promete que *"o relaxamento da TEC-160 decai sozinho, porque 10% acima do teto sai com 0,9 sem cláusula extra"*. Mas `_aderencia` ancora em `filtro.preco_max_centavos` — **o mesmo campo que o `WHERE` compara**. Um segundo passe construído como "um `FiltroDeBusca` novo com teto × 1,10" leva a âncora junto: o imóvel de R$ 660 mil passa a valer **1,0** em vez de 0,9, a promessa da E-01 vira falsa em silêncio, e a ordenação passa a favorecer sistematicamente o imóvel mais caro do conjunto ampliado — que é a direção do upsell que a própria E-01 nomeia como o risco a vigiar.

Um parâmetro `ancora_de_preco: int | None = None` em `buscar()` não resolve: `None` já é valor legítimo do domínio ("o lead não deu teto", aderência constante 1), então o default seria indistinguível do caso real e exigiria sentinela. Com o campo no filtro, `buscar()` lê `relaxado` em **um** lugar — o `WHERE` de preço ganha a folga, `_aderencia` continua recebendo `filtro.preco_max_centavos` cru — e os dois fatos ficam visíveis na mesma função. A promessa da E-01 passa a ser consequência do código, e não coincidência entre dois campos que por acaso eram iguais.

### D3 — A folga é inteira, em pontos percentuais, e cede nas duas pontas

```python
MARGEM_DO_RELAXAMENTO_PCT = 10   # RN-09.3
teto = filtro.preco_max_centavos * (100 + MARGEM_DO_RELAXAMENTO_PCT) // 100
piso = filtro.preco_min_centavos * (100 - MARGEM_DO_RELAXAMENTO_PCT) // 100
```

Aritmética inteira sobre centavos, sem ponto flutuante entrando no SQL. Um `× 1.10` em `float` produz tetos que variam no último centavo, e num catálogo com preços densos isso vira desempate invisível numa suíte que já flakeia sob carga.

**Cada ponta só cede se o lead a informou.** As duas são `int | None` e o `WHERE` só as inclui quando presentes — a folga se aplica ao que existe, e `None` continua significando "sem essa ponta", nunca "zero".

As **duas** pontas cedem porque "faixa de preço em até 10%" é sobre o intervalo, e um piso que continua duro enquanto o teto cede é uma assimetria que ninguém consegue justificar seis meses depois. O impacto prático é quase nulo — a própria E-01 da RN-09.6 registra que *"o piso não aparece em regra nenhuma da RF-09"* e `preco_min_centavos` raramente vem preenchido —, e o ganho é a regra ter um número só.

### D4 — Um passe só, com as duas dimensões juntas

A RN-09.3 põe **um** em negrito. O relaxamento é uma segunda consulta, no máximo, com teto × 1,10 e regiões ∪ adjacentes ao mesmo tempo.

A alternativa da escada — relaxa preço, se ainda zero amplia bairro — devolveria um resultado mais próximo do pedido original, porque não ampliaria geografia sem necessidade. Recusada por dois motivos: contradiz o negrito da regra, e custa até três consultas no pior caso contra o p95 de 400 ms que a TEC-159 mede.

Quando só uma dimensão é relaxável — lead sem teto, ou sem região —, o passe degrada para ela sozinha sem virar caso especial.

### D5 — "Nada relaxável" é caminho de saída, não uma segunda consulta idêntica

Sem teto **e** sem região, o zero veio de tipo, quartos ou vagas, e a RN-09.3 não relaxa nenhum dos três. A segunda consulta seria byte a byte igual à primeira: paga-se latência contra o p95 da TEC-159 para receber o mesmo zero.

É também a lacuna que o desenho da TEC-262 nomeou — *"relaxaria preço e bairro de uma busca que nunca teve chance"* — e que ele fechou para o caso do tipo. Para quartos e vagas ela continua aberta, e a L3 a registra.

### D6 — O estado do relaxamento é tri-estado no domínio, e booleano só nas bordas

```python
class EstadoDoRelaxamento(StrEnum):
    NAO_HOUVE = "NAO_HOUVE"        # achou no passe 1, ou nada era relaxavel
    APLICADO = "APLICADO"          # relaxou e achou
    SEM_RESULTADO = "SEM_RESULTADO"  # relaxou e continuou zero
```

`ResultadoDaBusca.relaxamento` guarda o enum; `buscar()` devolve **sempre** `NAO_HOUVE`, porque ela é um passe e não sabe se é o primeiro ou o segundo. Quem afirma é `buscar_com_relaxamento`, por `dataclasses.replace`.

**Um booleano não serve, e a regra 4 da card é quem prova.** A card manda que, *"se mesmo com o relaxamento não houver resultado, o agente não tenta de novo: informa e oferece a lista de espera ou o corretor"*. O turno precisa então distinguir três situações, e `relaxamentoAplicado: false` colapsa duas delas: "não relaxei" e "relaxei e não achei" pedem mensagens diferentes ao lead — a primeira não menciona ampliação nenhuma, a segunda tem de dizer que nem ampliando apareceu algo. Com o enum, o estado impossível ("não tentei, mas apliquei") deixa de ser representável.

**Nas bordas continua booleano, como os contratos escrevem.** `relaxamentoAplicado` do `POST` da seção 6.3 e `relaxamento_aplicado` do `tool_result` são `estado is APLICADO`, derivados num lugar só. O `tool_result` leva também `relaxamento_sem_resultado` — ele é consumido pelo **nosso** código no turno, não pelo modelo, e por isso não ganha frase no prompt (ver a D12): no caminho em que ele é verdadeiro a prosa do modelo é substituída de qualquer jeito (D14).

Com isso o aviso e o campo continuam sendo o mesmo fato: o aviso da D10 sai se e somente se o estado é `APLICADO`, e não existe estado em que um contradiga o outro.

### D7 — A adjacência é tabela no banco, semeada pela própria migration

A migration `0021_bairros_adjacentes.py` cria a tabela **e** insere os pares na mesma revisão.

O SRS diz "tabela de adjacência pré-carregada", e a carga junto do schema tem uma consequência boa nos testes: a tabela fica **fora** de `TABELAS` no `tests/conftest.py`, sobrevive ao `TRUNCATE ... CASCADE` que a fixture autouse `banco_limpo` dá a cada teste, e todo teste de integração a tem sem semear. Numa suíte de mais de 1.200 testes, incluí-la em `TABELAS` custaria mais de mil `TRUNCATE` a mais — e o `CLAUDE.md` registra que essa contenção de lock é o que produz os flakes de `ConnectionResetError`.

A alternativa do CSV em `data/seed/` (o molde do catálogo) foi recusada por isso: ou todo teste de integração semeia, ou a tabela entra em `TABELAS` e paga o custo acima. A alternativa de migrar o schema vazio e semear à parte foi recusada porque um ambiente recém-migrado teria a tabela vazia, e a RN-09.3 silenciosamente não ampliaria bairro nenhum — falha que não levanta erro e se parece com "nada é adjacente".

**Contrapartida declarada:** mudar a adjacência passa a exigir migration nova, e "pré-carregada" passa a significar "pelo schema".

### D8 — Chaveada pelo bairro dobrado, as duas direções, sem FK

```sql
CREATE TABLE bairros_adjacentes (
    bairro_busca     TEXT NOT NULL,
    adjacente_busca  TEXT NOT NULL,
    PRIMARY KEY (bairro_busca, adjacente_busca)
)
```

**Dobrado, nunca o nome bonito.** `FiltroDeBusca.regioes` chega dobrada (`busca.py` aplica `dobrar` na entrada) e `Imovel.bairro_busca` é a coluna que o `WHERE` compara. Guardar `"Lagoa da Conceição"` obrigaria a dobrar em tempo de consulta e faria um acento divergente no seed nunca casar, calado. Os valores gravados são `agronomica`, `lagoa da conceicao`, `santo antonio de lisboa`.

**As duas direções, não uma.** Adjacência é simétrica no mundo, mas guardar um lado só obrigaria a consulta a ser um `OR` sobre duas colunas com união. O caminho é quente — a TEC-159 mede p95 ≤ 400 ms —, e com as duas direções a consulta é um `IN` simples que a PK serve direto. A simetria vira teste, não convenção.

**Sem FK, porque não há entidade de bairro.** `bairro_busca` é coluna desnormalizada de `imoveis`. Consequência: uma linha que nomeie bairro inexistente é inerte, e um erro de digitação do lado esquerdo faz aquele bairro nunca ampliar — as duas falham em silêncio. **A integridade que o schema não dá vira teste**: todo nome da tabela existe entre os `bairro_busca` do catálogo seed.

**Os 15 pares (30 linhas), critério "contíguos ou ligados por via direta":**

| Bairro | Amplia para |
|---|---|
| Centro | Agronomica, Trindade, Estreito |
| Agronomica | Centro, Trindade, Itacorubi |
| Trindade | Centro, Agronomica, Itacorubi |
| Itacorubi | Trindade, Agronomica, Lagoa da Conceicao, Santo Antonio de Lisboa |
| Lagoa da Conceicao | Itacorubi, Campeche |
| Campeche | Lagoa da Conceicao |
| Estreito | Centro, Balneario, Coqueiros |
| Balneario | Estreito, Coqueiros |
| Coqueiros | Estreito, Balneario |
| Canasvieiras | Jurere, Santo Antonio de Lisboa |
| Jurere | Canasvieiras, Santo Antonio de Lisboa |
| Santo Antonio de Lisboa | Jurere, Canasvieiras, Itacorubi |

Duas escolhas que registro porque alguém vai perguntar: **Campeche tem um vizinho só**, então filtrar Campeche amplia para exatamente um bairro a mais; e **Centro↔Estreito atravessa a baía**, incluído por serem ligados pela ponte e por um lead de Florianópolis tratá-los como vizinhos.

### D9 — O vetor da consulta é calculado uma vez para os dois passes

`buscar()` ganha `vetor: list[float] | None = None`. Presente, manda; ausente, deriva de `consulta_texto` e `embedador` como hoje.

Sem isso, o passe 2 recebe `consulta_texto` de novo e chama o embedador uma **segunda** vez: segunda chamada paga ao provedor e segunda latência, para o mesmo texto, em todo turno relaxado. `buscar_com_relaxamento` vetoriza uma vez e entrega o mesmo vetor aos dois.

Não precisa de sentinela: "passei `None`" e "não passei" querem a mesma coisa — derive se puder. O `except Exception` de `_vetor_da_consulta` continua sendo o único lugar que trata falha de provedor.

### D10 — O aviso é mensagem própria com kind próprio, não prefixo de legenda

As três variantes da D11 e `KIND_DO_CRITERIO_AMPLIADO = "criterio_ampliado"`, em `turno.py`, ao lado de `TEXTO_DA_BUSCA_INCONCLUSIVA`.

**Prefixo não serve, e a TEC-139 já pagou para descobrir.** No caminho de apresentação a prosa vira prefixo da legenda da primeira ficha, e `legenda_de` corta o **prefixo** antes da ficha — `_prosa_que_cabe` devolve string vazia quando não sobra espaço. O comentário da TEC-139 diz por que a identificação saiu dali: *"ela sairia truncada ou não sairia nenhuma, em silêncio"*. Um aviso que some em silêncio quebra a CA-09.3 exatamente no turno em que ela existe para valer.

**Kind próprio é obrigatório, não preferência.** No caminho de apresentação a identificação já envia com `KIND_DA_RESPOSTA`, e a reserva em `outbound_dispatches` tem `UNIQUE (message_id, kind)` — a constraint `uq_outbound_message_kind`, criada na `0002` e que a `port.py` nomeia em `UNIQUE_DA_RESERVA`. Duas mensagens com o mesmo kind no mesmo `message_id` colidiriam na reserva, e a segunda seria descartada como se fosse reprocessamento. A coluna é `String(32)`, e `"criterio_ampliado"` tem 17. É o mesmo motivo que deu `reply_2` à segunda mensagem de texto da TEC-140. String fixa, sem id dentro, pelo argumento de idempotência que o comentário de `KINDS_DAS_FICHAS` registra — kind que muda entre retentativas perde a dedup justamente quando ela importa.

**Ordem:** identificação (se conversa nova) → aviso → até 3 fichas. A identificação diz quem fala; o aviso enquadra o que vem.

**O aviso sai só no caminho `apresentando`.** Se o relaxamento produziu candidatos mas o modelo perguntou algo, ou o desambiguador assumiu, as fichas ficam para o próximo turno — e avisar "ampliei o critério" sem mostrar alternativa é aviso sobre nada. A CA-09.3 diz *"o lead recebe alternativas **com** aviso explícito"*: os dois andam juntos ou nenhum anda.

**A RN-04.2 fecha sem emenda, e fica empatada.** A E-02 da TEC-162 separou os tetos em até 2 mensagens de texto e até 3 de apresentação; conversa nova com relaxamento gasta os dois textos mais até 3 fichas. Ver a L5.

### D11 — O aviso diz **em quê** ampliou, no nível da dimensão, e nunca em número

A card exige que *"o lead é sempre avisado, de forma explícita, de que o critério foi ampliado **e em quê**"*. São três variantes, e sai a que corresponde ao que de fato foi relaxado:

| Relaxou | Texto |
|---|---|
| preço e bairro | `"...ampliei um pouco: valor um pouco acima e bairros vizinhos."` |
| só preço | `"...ampliei um pouco o valor."` |
| só bairro | `"...incluí bairros vizinhos."` |

**Uma constante fixa que dissesse sempre as duas coisas seria o aviso mentindo.** O lead que não deu região nenhuma teve só o preço relaxado, e ouvir "incluí bairros vizinhos" é informação falsa sobre o que o sistema fez — num aviso cujo propósito inteiro é ser explícito. A variante é escolhida pelo que `alargar` mudou, e não por heurística no turno.

**"Em quê" para aqui: dimensão, nunca valor.** O texto não diz 10%, nem o teto ampliado. O número ampliado é conta nossa, não fato do banco, e dizê-lo ao lead é afirmar precisão sobre política interna. É também o que mantém o aviso fora da discussão da TEC-161 — texto nosso não passa por `divergencias_de`, mas um texto nosso que cita valor convida o próximo leitor a achar que passa.

Os nomes dos bairros também ficam de fora, e essa é a escolha mais discutível das três: nome de bairro é fato do catálogo e não reabriria o problema da TEC-161. Ficam fora porque a lista é variável — a Trindade do Gherkin amplia para três, o Itacorubi para quatro — e uma mensagem que cresce com o grau do nó é mensagem cujo pior caso ninguém mediu. O lead vê o bairro de cada imóvel na ficha, que é onde ele importa.

### D12 — O modelo sabe que relaxou, e a instrução viaja no `tool_result`, não no prompt

**Emenda de implementação (11/09/2026).** O desenho original mandava `SISTEMA_DO_AGENTE` ganhar uma frase curta explicando o campo, e registrava que o plano mediria antes de gastar. A medição foi feita e **reprovou a frase**:

| | tokens |
|---|---|
| teto fixo de `test_a_margem_do_orcamento_do_prompt_e_deliberada` | 793 |
| subcontagem atual | 786,8 |
| **margem** | **6,2** |
| teto derivado (`contexto_headroom_de_tokens` 1060 × 0,75) | 795 |
| frase candidata (~77 caracteres pelo proxy `len/4`) | ~19,25 |

A frase não cabe, e as três saídas do manual estavam fechadas. Subir o teto fixo acima de 795 o tornaria **decorativo** — quem passaria a prender seria o derivado, e a folga que o teste imprime deixaria de ser a folga real. Subir `contexto_headroom_de_tokens` custa 180 tokens por turno da conversa do lead, pelo registro do comentário daquele campo. E a pergunta que o `CLAUDE.md` manda fazer — *o que sai do prompt para o novo texto entrar?* — não tem resposta barata aqui: a definição de confiança alimenta a desambiguação da TEC-135; *"nao negocie valor"*, *"orcamento vago"*, *"o imovel que o lead ja tem"* e *"urgencia so com marco temporal"* vieram cada uma de uma card. Cortar qualquer uma paga a TEC-160 com uma regressão em outra.

**A saída foi não pôr a instrução no prompt.** Ela viaja dentro do próprio `tool_result`, como uma chave `aviso` presente **somente quando houve relaxamento**:

```python
"aviso": "criterio ampliado: estes imoveis passam do que o lead pediu; nao afirme que atendem"
```

O `tool_result` é conteúdo de turno, contado por `montar_contexto` como o resto da conversa, e **não passa pelo teto fixo** — que mede `SISTEMA_DO_AGENTE`, o schema compilado e a definição em `tools=`. A instrução chega ao modelo exatamente quando é relevante, adjacente aos candidatos que ela descreve, e custa **zero** nos ~99% dos turnos em que nada relaxa — enquanto uma frase no `system` custaria em toda chamada, inclusive nas que nem buscam.

**O que continua verdadeiro da versão original:** sem alguma forma de instrução o campo é decorativo e o defeito chega ao lead — o modelo escreveria prosa afirmando que achou o que ele pediu, sobre um imóvel 10% acima do orçamento em bairro vizinho, e o aviso determinístico sairia logo em seguida, fazendo o lead ler uma contradição dentro da mesma entrega.

**Custo declarado da troca.** Instrução entregue como dado tem menos peso que instrução de sistema, e o modelo pode ignorá-la com mais facilidade. O que limita o estrago é que o aviso ao lead (D10 e D11) é mensagem determinística nossa e não depende do modelo: o pior caso é prosa destoando do aviso, não lead desinformado. Se a eval da TEC-210 mostrar o modelo afirmando que os imóveis atendem ao pedido, o caminho é reabrir o orçamento com card própria — não remendar aqui.

**Este desenho não transcreve o teto de hoje**, pela mesma razão que o comentário de `classificador.py` não transcreve: é derivado, muda a cada mudança de prompt ou schema, e transcrito à mão envelhece sem ninguém notar. A tabela acima é a medição de 11/09/2026, datada de propósito. Rode `pytest -q -k margem_do_orcamento -s` para saber a de hoje.

**Uma consequência que declaro para ninguém se assustar com o log.** Se o modelo inventar o teto ampliado em prosa — "achei até R$ 660 mil" — e nenhum candidato custar isso, a TEC-161 bloqueia e um `citacao.bloqueada` aparece em turno relaxado. É correto: `_cabe_em_algum` aceita preço que bata com algum candidato, e o teto ampliado não é candidato nenhum. Preço **de** candidato relaxado passa normalmente, porque é candidato.

### D13 — Falha na adjacência degrada para relaxamento só de preço

Log e segue com a dimensão que sobrou, no molde de `_vetor_da_consulta` e da D6 da TEC-265: *"derrubar a dimensão e não a busca"*. Bairro sem linha na tabela não é erro — é lista vazia, e o passe relaxa só o preço.

### D14 — Relaxou e continuou zero tem desfecho nosso, não prosa do modelo

`TEXTO_SEM_RESULTADO_APOS_AMPLIAR`: informa que nem ampliando apareceu algo e oferece o corretor. Substitui `texto` no caminho de não-apresentação, exatamente como o caminho de citação bloqueada da TEC-161 já faz.

É a regra 4 da card, e o segundo cenário do Gherkin a cobra: *"nenhuma segunda ampliação é tentada, e o lead recebe a oferta de lista de espera ou conversa com o corretor"*. **A lista de espera está fora de escopo** — a própria card a exclui, junto do handoff por indisponibilidade (E5 e E7) —, então o desfecho oferece o corretor, que é a metade que esta card pode entregar.

**Constante nova, e não reúso de `TEXTO_DA_BUSCA_INCONCLUSIVA`.** Aquele texto promete *"já te retorno com as opções"*, e aqui não há opção nenhuma para retornar — seria o sistema prometendo o que sabe que não tem. O laço excedido e a citação bloqueada podem prometer porque nos dois casos os imóveis existem e o problema é nosso.

**Só no zero pós-relaxamento**, que é o único que a card legisla. O zero de "nada relaxável" (D5) segue com a prosa do modelo: ali ele ainda pode fazer algo útil que nós não sabemos fazer — perguntar se o lead aceita dois quartos, por exemplo — e calá-lo custaria mais do que padroniza. É o `estado is SEM_RESULTADO` da D6 que separa os dois, e é por isso que o booleano não bastava.

## Os quatro cenários do Gherkin

| Cenário da card | Onde é verificado |
|---|---|
| 1 — Ampliar faixa e bairro quando não há resultado (3 quartos, R$ 400.000, Trindade → R$ 440.000 + adjacentes) | Integração, com os números da card |
| 2 — Relaxamento acontece uma única vez, e o lead recebe a oferta do corretor | Integração (nenhuma terceira consulta) + turno (D14) |
| 3 — Busca com resultado não é relaxada, e nenhum aviso é enviado | Integração + turno |
| 4 — Bairros adjacentes vêm da tabela pré-carregada | Integração |

**Uma ambiguidade do cenário 4, resolvida aqui.** Ele diz *"**apenas** bairros marcados como adjacentes à Trindade entram na busca"*. Ao pé da letra isso excluiria a própria Trindade — o que estaria errado: o passe 1 não achou nada na Trindade **sob o filtro original**, mas com o preço relaxado pode haver ali um imóvel a R$ 420.000, e descartá-lo seria devolver o vizinho e esconder o bairro que o lead pediu. A leitura que vale é *"a ampliação se limita à tabela; nenhum bairro não-marcado entra"*, e a busca é regiões ∪ adjacentes. O cenário 1 confirma essa leitura ao dizer "preço até R$ 440.000 **e** bairros adjacentes", e não "em vez de".

## O que a card entrega

1. `domain/catalogo/relaxamento.py`: `buscar_com_relaxamento()`, `alargar()` e o lookup de adjacência.
2. `FiltroDeBusca.relaxado`, `EstadoDoRelaxamento` e `ResultadoDaBusca.relaxamento`.
3. `buscar()` com o parâmetro `vetor` e a leitura de `relaxado` no `WHERE` de preço.
4. Migration `0021_bairros_adjacentes.py`, com schema e os 30 pares.
5. `relaxamento_aplicado` e `relaxamento_sem_resultado` no `tool_result`; `relaxamentoAplicado` no `POST` da seção 6.3; os dois chamadores migrados para `buscar_com_relaxamento`.
6. A chave `aviso` no `tool_result`, presente so quando houve relaxamento (ver a D12 — a frase no prompt foi medida e nao coube).
7. As três variantes do aviso, `KIND_DO_CRITERIO_AMPLIADO` e o envio no caminho de apresentação.
8. `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` e a substituição no caminho de não-apresentação (D14).
9. As duas emendas ao SRS, e as duas linhas no índice do topo.

## Testes

| Onde | O quê |
|---|---|
| Unit | `alargar`: regiões ∪ adjacentes, `relaxado=True`, teto original **preservado** |
| Unit | "nada relaxável" não dispara segunda consulta |
| Unit | os dois booleanos derivados do `tool_result`, com `buscar` injetado |
| Unit | o vetor é calculado uma vez e reusado pelos dois passes |
| Unit | a variante do aviso corresponde ao que foi relaxado — as três (D11) |
| Integração | **cenário 1 da card**: 3 quartos, R$ 400.000, Trindade → R$ 440.000 e adjacentes |
| Integração | **cenário 3 da card**: busca com resultado não relaxa e não avisa |
| Integração | **cenário 4 da card**: só bairro marcado adjacente entra, e a Trindade continua dentro |
| Integração | **10% acima do teto pontua 0,9** — a dívida que a TEC-158 deixou nomeada |
| Integração | **cenário 2 da card**: relaxou e continuou zero → `SEM_RESULTADO`, e nenhuma terceira consulta |
| Integração | a tabela é simétrica, e todo nome dela existe no catálogo seed |
| Integração | busca por zona relaxa preço e não amplia bairro |
| Turno | o aviso sai como mensagem própria, com kind próprio, depois da identificação |
| Turno | o aviso **não** sai quando o modelo perguntou |
| Turno | `SEM_RESULTADO` substitui a prosa pelo desfecho com o corretor (D14) |
| Turno | zero de "nada relaxável" **não** substitui a prosa do modelo |
| Orçamento | `margem_do_orcamento` continua passando com a frase nova |

**Basenames únicos entre `tests/unit/` e `tests/integration/`**: `test_relaxamento_alargar.py` e `test_relaxamento_busca.py`. Colisão de basename aborta a coleta da suíte inteira e não aparece em execução isolada — já custou duas cards neste repo.

**`bairros_adjacentes` NÃO entra em `TABELAS`** no `tests/conftest.py`. Ver a D7.

## As emendas ao SRS

**`CA-09.1` — Emenda E-01 (TEC-160, 11/09/2026).** O critério diz *"nenhum resultado tem preço acima de R$ 600 mil"* e a RN-09.3 devolve até 10% acima: literalmente, relaxar viola a CA-09.1. A emenda declara que ela descreve o **passe de filtro duro** — que continua exato e é o único que roda quando há resultado — e que o passe relaxado é a exceção nomeada, visível ao lead pelo aviso e ao chamador por `relaxamentoAplicado`. **A metade dos quartos não se mexe**: a RN-09.3 relaxa preço e bairro, nunca quartos, tipo ou vagas.

**`RN-09.3` — Emenda E-01 (TEC-160, 11/09/2026).** A regra deixa oito pontos em aberto que o código decidiria sozinho — o mesmo defeito que a E-01 da RN-09.6 corrigiu quando a regra dava o peso e nunca dizia o que se media. A emenda fixa: (1) *"um relaxamento"* é uma consulta a mais, com as duas dimensões juntas; (2) a faixa cede nas duas pontas, 10 pontos percentuais, em aritmética inteira sobre centavos; (3) a âncora da ordenação da RN-09.6 **não** se move com o `WHERE`; (4) `relaxamentoAplicado` significa "o que você está vendo veio do passe relaxado", e é `false` quando o passe relaxado também dá zero — o domínio guarda os três estados e a borda deriva o booleano; (5) sem teto e sem região não há segunda consulta; (6) a tabela de adjacência é chaveada pelo bairro dobrado, guarda as duas direções e não tem FK, e a integridade é teste, não schema; (7) o aviso da CA-09.3 é mensagem determinística nossa, com kind próprio, nunca prosa do modelo, e **nomeia a dimensão que foi ampliada** — nunca o valor; (8) a ampliação de região é regiões ∪ adjacentes: o bairro pedido continua na busca, e "apenas adjacentes" limita de onde vêm os novos, não quem sai. Declara junto que **busca por zona relaxa preço e não amplia bairro**.

**O que não se emenda.** A RN-04.2 continua valendo sem mudança (ver a D10 e a L5). A RN-09.6 não precisa de emenda nova: a E-01 dela já previu este caso — o que muda é que a previsão passa a ter teste.

## Lacunas conhecidas

### L1 — A adjacência é de uma cidade só, e não tem FK

Os 30 pares cobrem os 12 bairros de Florianópolis do catálogo simulado. Um catálogo com segunda cidade precisa ou de coluna de cidade na tabela, ou da constatação de que bairros homônimos em cidades diferentes vão ampliar errado — que é a mesma lacuna 8 do desenho da TEC-158, sobre não haver filtro de cidade. Sem FK, nome errado na tabela falha em silêncio; o teste de que todo nome existe no catálogo é o que substitui a constraint.

### L2 — Busca por zona não amplia geograficamente

Se o lead disse "zona sul", `regioes` é `("zona sul",)`, que não casa nome de bairro nenhum: o passe relaxa só o preço. É a decisão correta — a zona já é o agregado de bairros, e ampliar "zona sul" para "zona leste" é ampliação de outra ordem de grandeza, que a RN-09.3 não autoriza —, mas é comportamento que alguém vai encontrar e achar que é bug.

### L3 — O relaxamento não toca tipo, quartos nem vagas

A RN-09.3 nomeia preço e bairro, e a card entrega isso. Zero causado por "4 quartos" num catálogo cujo máximo é 3 continua sendo zero depois do relaxamento, com `relaxamentoAplicado: false`. A TEC-262 fechou a metade do tipo; quartos e vagas seguem abertos e precisam de card e de emenda, não de código esperto aqui.

### L4 — A TEC-159 mede só o caminho feliz

O p95 ≤ 400 ms passa a cobrir, no caminho de zero resultado, duas consultas mais o lookup de adjacência. O atenuante é que o passe 1 desse caminho é o mais barato que existe, porque não devolve linha. O desenho da TEC-159 foi escrito antes desta card e não exercita o caminho relaxado: é pendência nomeada para lá, não escopo daqui.

### L5 — A folga de texto da RN-04.2 acabou

Depois desta card, conversa nova com relaxamento gasta as duas mensagens de texto que a E-02 da TEC-162 permite. **Não sobra folga.** A próxima trilha que quiser mensagem própria vai precisar de emenda à RN-04.2 — e não vai descobrir isso sozinha se ninguém registrar agora.

### L7 — O aviso pode ser entregue sem ficha nenhuma atrás dele

Achado na revisão final da branch, e **deliberadamente não corrigido nesta card**.

O aviso é enviado antes de `_apresentar`, e `_apresentar` pode entregar zero fichas: `fichas_do_catalogo` descarta os `id` sem linha, e quando descarta todos o laço não roda — o repo loga `apresentacao.fichas_sumiram_do_catalogo` em nível `error` justamente porque "o lead nao recebe nada". Nesse turno o lead lê exatamente uma mensagem: *"Nao achei nada exatamente no que voce pediu, entao ampliei um pouco a busca... **Veja se algum destes serve.**"* — seguida de nada.

É a mesma falha que a D6 usa para justificar o tri-estado (*"o aviso ao lead anunciaria 'ampliei o critério' seguido de nada"*), entrando por outra porta.

**Por que fica.** O conserto exige reordenar o caminho de apresentação — resolver as fichas antes dos dois envios de texto —, e isso o desenho não previu. O gatilho é um estado que o próprio repo já trata como anomalia e registra em `error`. E a mensagem de identificação carrega a **mesma** forma desde a TEC-139 sem nunca ter sido tratada como defeito: o aviso não introduz o problema, herda-o.

**O que esta card muda, e por isso a lacuna existe:** o texto do aviso torna o órfão **autocontraditório** em vez de apenas solitário. A identificação sozinha é estranha; *"Veja se algum destes serve"* sobre coisa nenhuma é uma promessa quebrada. Quem for consertar a forma herdada tem aqui o motivo para tratar as duas de uma vez.

### L6 — O desfecho oferece o corretor, e não a lista de espera

A regra 4 da card diz *"informa e oferece a lista de espera **ou** o corretor"*, e a mesma card põe a lista de espera fora de escopo (E5). A D14 entrega a metade disponível. Quando o E5 existir, o texto de `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` é o lugar a revisitar — e esta lacuna é o bilhete para quem chegar lá.

## Fora de escopo

- A lista de espera e o handoff por indisponibilidade — a própria card os exclui (E5 e E7). Ver a L6.
- Relaxamento de tipo, quartos ou vagas (L3).
- Adjacência multi-cidade e filtro de cidade (L1, e a lacuna 8 da TEC-158).
- A medição do SLA no caminho relaxado (L4, TEC-159).
- Um segundo nível de relaxamento, ou relaxamento configurável: a RN-09.3 diz **um**, e pesos configuráveis são RF-19.
