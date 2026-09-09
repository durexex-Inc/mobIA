# TEC-162 — Apresentar até 3 imóveis com ficha estruturada por canal

**Status:** desenhado em 2026-09-09 na branch `feat/tec-162-ficha-por-canal`.

**Card:** [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162) — Must (MoSCoW), prioridade Highest. Origem: RF-10, RN-10.1 e RN-10.2 (SRS v1.0). Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**Destravada em 2026-09-08 pela [TEC-265](https://eduardodurieuxlopes.atlassian.net/browse/TEC-265)**, junto com a TEC-161. As duas estavam bloqueadas pela TEC-158 *e* pela 265, e os dois bloqueios caíram no mesmo merge (PR #70).

**Escolhida antes da TEC-161, que é a outra Highest da épica**, e a ordem é deliberada. A RN-09.4 manda a TEC-161 comparar *"identificador e preço"* do que a resposta cita. Sobre prosa livre isso é extração de entidade; sobre a ficha estruturada desta card é comparação de campo. Fazer a 161 primeiro obrigaria a escrever um parser que esta card joga fora. O preço da inversão é uma janela em que o agente já recebe candidatos no contexto (desde a 265) e nada valida o que ele cita.

## Objetivo

A busca da épica passa a ser visível ao lead. Até esta card, `executar_turno` obtém candidatos, o modelo os enxerga, e o que sai é uma mensagem de texto só — a recomendação existe no contexto do modelo e não na tela de quem decide visitar.

**O que esta card entrega:** a ficha dos oito campos da RN-10.1, montada por código a partir do catálogo, entregue como até três imagens com legenda no WhatsApp.

**O que ela não entrega:** o card clicável do widget web (D1), o registro da recomendação (RN-10.3/RN-10.4, TEC-163) e a validação da resposta contra os candidatos (TEC-161).

## O estado de hoje, medido

- **`executar_turno` manda exatamente uma mensagem de texto por turno.** [`turno.py:508`](../../../src/mobia/domain/agente/turno.py#L508) — *"Uma vez por turno: so um texto sai"* — com payload `{para, de, texto}`.
- **O adaptador da Meta fixa `"type": "text"`** no corpo ([`whatsapp.py:52-57`](../../../src/mobia/domain/outbound/whatsapp.py#L52)). Imagem com legenda é `type: "image"` com `image.link` e `caption`; não há caminho para ela.
- **A idempotência é `UNIQUE (message_id, kind)`** ([`outbound/models.py:29`](../../../src/mobia/domain/outbound/models.py#L29)), com um único `kind = "reply"` hoje. Três imóveis são três efeitos externos.
- **`Candidato` não carrega condomínio nem foto** ([`catalogo/schemas.py:208-217`](../../../src/mobia/domain/catalogo/schemas.py#L208)). Os dois existem em `Imovel`; a busca não os seleciona.
- **`RespostaDoAgente.candidatos` guarda os dicts que o modelo viu, não os `Candidato`** ([`agente/schemas.py:305`](../../../src/mobia/domain/agente/schemas.py#L305)). Os objetos do catálogo morrem dentro do closure de `porta_de_busca`.
- **`preco_centavos` já foi deixado inteiro para esta card** — [`ferramenta_de_busca.py:78`](../../../src/mobia/domain/agente/ferramenta_de_busca.py#L78): *"formatar e apresentacao (TEC-162)"*.
- **A margem do orçamento do prompt é de 6,0 tokens** (líquido 780,0 contra teto fixo de 786), medida em 2026-09-08 pela TEC-265. Campos novos no schema custaram ~18,5 (`perguntou`) e ~17,6 (`recusou`) nas cards anteriores.
- **Não existe formatador de reais no repositório.** `domain/agente/dinheiro.py` é o parser da fala do lead para centavos, só a direção contrária.
- **O canal web não existe.** `channel` conhece `wa` e `eval`; `api/routes/` tem `whatsapp.py` e `imoveis.py`. O widget é a [TEC-124](https://eduardodurieuxlopes.atlassian.net/browse/TEC-124), *A fazer*.
- **O seed (`data/seed/imoveis.csv`, 520 linhas):** `caracteristicas` vazio em 117; `fotos` presente em todas as 520; `descricao` é boilerplate gerado (média de 88 caracteres, do tipo *"Terreno de 666 m2 em Coqueiros, 0 quarto(s) e 0 vaga(s). Sem diferenciais listados."*); preços com centavos de verdade (`516464.30`).
- **A suíte na `main` (`04b1c6a`) não está verde:** 1336 passed, 2 failed, 3 errors em 31min01. As cinco falhas são `ConnectionResetError`, `OSError` e `redis.exceptions.ConnectionError`, nenhuma asserção — a família WinError 64 que o `CLAUDE.md` documenta.

## Decisões

### D1 — Ficha agnóstica de canal, um renderizador só

A RN-10.2 pede dois canais e o terceiro cenário do Gherkin da card pede o card clicável do widget web. **O widget não existe**, e a TEC-124 é uma épica de canal inteira (WebSocket, sessão, histórico unificado entre WhatsApp e web).

A ficha nasce como objeto de valor sem canal — os oito campos da RN-10.1 já resolvidos, incluindo preço formatado e diferencial. Só um renderizador é escrito: o da legenda do WhatsApp. A TEC-124 escreve o dela contra a ficha que já existirá.

A alternativa era escrever também o renderizador de card web, função pura testável em unidade, cumprindo os quatro cenários. Foi recusada por YAGNI com agravante: um formato de card desenhado sem widget contra o qual validar é palpite, ficaria sem consumidor até a TEC-124 e provavelmente mudaria quando ela chegasse.

**Consequência declarada:** a card fecha com um dos quatro cenários do Gherkin não entregue, por emenda registrada e não por omissão.

### D2 — Mídia fica fora do teto de mensagens consecutivas

A RN-04.2 limita a **2 mensagens consecutivas**. A RN-10.2 pede **3 imóveis, uma imagem cada**. As duas regras do mesmo SRS se contradizem, e a CA-10.1 desempata: ela pressupõe três apresentados (*"Dados 3 imóveis apresentados, quando o lead responde 'gostei do segundo'"*), então baixar o teto de imóveis para 2 invalidaria um critério de aceite.

A emenda vai na RN-04.2: o teto de 2 vale para mensagens de **texto**; a apresentação pode emitir até 3 mensagens de **apresentação** por turno — mídia, ou texto quando o imóvel não tem foto (D13). O teto existe contra parede de texto, e três fichas de apresentação — com ou sem foto — não são isso: cada uma carrega um imóvel diferente, e a D13 já garante que a ausência de foto nunca esconde o imóvel por trás de silêncio. Uma redação presa a "mídia" deixaria de fora justamente o turno que a Task 6 semeou (dois imóveis sem foto no seed) e cujas três legendas, todas em texto, ficariam sem teto declarado — a falha que este mesmo desenho existe para fechar.

**Sem mensagem de abertura.** As três legendas se bastam, e uma quarta mensagem seria justamente a parede que a regra teme.

### D3 — O código escolhe os três e deriva o diferencial; o prompt não muda

Os oito campos da RN-10.1 são colunas de `Imovel`, com uma exceção: *"um diferencial em uma frase"* não é coluna de nada.

O código pega os três primeiros de `gerada.candidatos` — a busca já ordena por score — e deriva o diferencial de `caracteristicas`. **Custo no orçamento do prompt: zero.**

As duas alternativas foram recusadas por preço, contra uma margem de 6,0 tokens:

- **Campo novo no schema de saída** com até três `{imovel_id, diferencial}`: ~20-40 tokens. Estoura o teto, exige subir teto *e* reserva, e a última subida custou 180 tokens de contexto por turno.
- **Segunda ferramenta `apresentar_imoveis`** no laço de tool use da TEC-265: a definição da ferramenta de busca sozinha custou 131,2 tokens, mais um round-trip por turno de apresentação.

O ritual do `CLAUDE.md` manda perguntar *"o que sai do prompt para o novo texto entrar?"* antes de subir o número. Nesta card nada precisa entrar.

**Benefício que a decisão traz de graça:** nenhum campo da ficha passa pelo modelo, então nenhum pode ser inventado. A TEC-161 fica trivialmente satisfeita na parte da ficha e sobra para ela só a prosa — que existiria de qualquer forma.

**Consequência declarada:** o diferencial é genérico. Ele não responde ao que o lead pediu — um lead que falou de metrô não vê "perto do metrô" em destaque, vê as duas primeiras características do cadastro. Se as evals mostrarem que isso custa conversão, o campo no schema é a card seguinte, com o preço já levantado aqui.

### D4 — O gatilho reusa `perguntou`, que já existe

Candidatos não-vazios **não** significam que o agente quis apresentar. Ele pode ter buscado e então perguntado *"achei opções — você prefere zona sul ou norte?"*. Disparar fichas sempre que a busca voltou apresenta em cima de uma pergunta.

A apresentação acontece quando `gerada.candidatos` é não-vazio **e** `gerada.perguntou` é vazio. O campo `perguntou` existe desde a TEC-257 ([`agente/schemas.py:277-283`](../../../src/mobia/domain/agente/schemas.py#L277)), é declarado pelo próprio modelo e já é pago. Custo desta decisão: zero.

Se o modelo perguntou, a prosa sai como texto e as fichas esperam o próximo turno. Isso respeita a RN-04.2 (*"uma pergunta por vez"*) em vez de brigar com ela.

A alternativa de decidir por "o filtro tinha dimensões suficientes" foi recusada: inventaria aqui uma regra de negócio que regra nenhuma do SRS pede, decidindo por conta própria o que é uma recomendação crível.

**Consequência declarada:** um turno em que o modelo pergunta *e* queria mostrar opções adia a apresentação por um turno.

### D5 — A prosa do modelo vira prefixo da legenda do primeiro imóvel

Num turno de apresentação sobra o texto que o modelo escreveu em `gerada.resposta`, e a D2 recusou a mensagem de abertura. A legenda 1 fica `"<prosa>\n\n<ficha>"`; as legendas 2 e 3 são ficha pura.

Descartar a prosa tem precedente no repo — o caminho ambíguo já descarta a resposta da primeira chamada ([`turno.py:504-506`](../../../src/mobia/domain/agente/turno.py#L504)) — e foi recusado: o lead receberia três fotos sem uma palavra de contexto, no turno mais importante da conversa, e pagaríamos tokens de saída por um texto jogado fora.

**Consequência declarada:** a legenda 1 é estruturalmente diferente das outras duas, e é a única que pode encostar no teto de 600 caracteres (ver D14).

### D6 — O turno rebusca os três imóveis por id, em vez de alargar o `Candidato`

A ficha precisa de condomínio, foto e características, e nenhum dos três chega ao turno: `RespostaDoAgente.candidatos` guarda os dicts que o modelo viu, e a TEC-265 os manteve estreitos de propósito.

Alargar o `Candidato` e o SELECT da busca resolveria o acesso, mas exigiria decidir se os campos novos entram em `_candidato_serializavel` — e entrar custa orçamento de prompt por um dado que o modelo não usa.

O turno pega os três primeiros `imovel_id` e pede as fichas a `ferramenta_de_busca.fichas_do_catalogo`, que chama `imoveis_por_ids(session, ids)`, novo em [`catalogo/repositorio.py`](../../../src/mobia/domain/catalogo/repositorio.py) — o arquivo hoje só tem `sincronizar`, e leitura por id não existe em lugar nenhum. A função devolve na ordem dos ids pedidos, que é a ordem de score. A camada intermediária existe pela invariante de import descrita em Fronteiras, não por gosto.

O contrato de `porta_de_busca` fica intocado, e a busca e o `Candidato` não mudam.

**Consequência declarada:** uma query a mais por turno de apresentação. E imóvel inativado entre a busca e a rebusca volta a menos — o turno apresenta o que voltou, sem erro. Menos de três fichas é resultado válido.

### D7 — O preço vem do dict do candidato, não da linha rebuscada

A linha rebuscada tem `preco_venda` e `preco_aluguel` e **não diz qual usar**: a operação buscada existe só dentro do closure de `porta_de_busca`. O dict do candidato já traz `preco_centavos`, que pelo contrato do `Candidato` é *"o preco da OPERACAO buscada — a mesma coluna que o filtro comparou"* ([`catalogo/schemas.py:197-201`](../../../src/mobia/domain/catalogo/schemas.py#L197)).

Então: preço do dict; condomínio, fotos e características da linha rebuscada.

**Benefício:** a ficha e a referência da TEC-161 passam a ser o mesmo número, e não existe divergência possível entre o que mostramos ao lead e o que ela valida.

### D8 — Payload polimórfico por `tipo`, com texto como default

`WhatsAppOutbound._deliver` passa a ler `payload["tipo"]`. Ausente significa `"texto"`, e é isso que mantém intactos os três chamadores de hoje — [`turno.py:543`](../../../src/mobia/domain/agente/turno.py#L543), `_entregar_texto_fixo` e os caminhos de follow-up. `"imagem"` traz `{link, legenda}` e o corpo sai como `type: "image"` com `image.link` e `caption`.

A alternativa de um `OutboundPort` novo para mídia foi recusada por motivo estrutural: quem implementa o Protocol sem herdar de `GuardedOutbound` **perde a guarda de opt-out**, e o docstring do port ([`outbound/port.py:42-53`](../../../src/mobia/domain/outbound/port.py#L42)) avisa exatamente disso. Falaríamos com quem pediu silêncio.

A alternativa de explodir a lista de fichas dentro do adaptador, com o turno mandando um payload só, foi recusada porque uma reserva para três efeitos externos destrói a garantia do `UNIQUE (message_id, kind)`: falha na segunda imagem deixaria a reserva gravada e nada retentável.

### D9 — Três kinds fixos por posição

`ficha_1`, `ficha_2`, `ficha_3`. `kind` é `String(32)`, cabe com folga.

Posição e não id do imóvel porque o `UNIQUE (message_id, kind)` precisa de um valor que a retentativa reproduza. Um kind derivado do id deixaria de colidir assim que a retentativa escolhesse outro imóvel, e a idempotência sumiria justamente no caso em que ela importa.

### D10 — Recusa permanente numa ficha não cala as outras

Hoje `EnvioRecusado` retorna na hora ([`turno.py:558-566`](../../../src/mobia/domain/agente/turno.py#L558)). Na apresentação, o turno loga `error` por ficha e **segue para a próxima**; o resultado é `processed` se ao menos uma entrou.

A divergência é deliberada e o motivo é qual recusa é provável aqui: a Meta rejeitando a URL da mídia. As URLs do catálogo são o campo mais frágil que temos — no seed são `https://exemplo.com/te-1001-1.jpg`, que não resolvem. Uma foto ruim não pode apagar dois imóveis bons.

`EnvioForaDaJanela` mantém o tratamento de hoje: a apresentação inteira é impossível e o turno retorna `expirado`.

### D11 — Centavos truncados para baixo, nunca arredondados

`51646430` centavos → `R$ 516.464`. O seed tem preço com centavos de verdade (`516464.30`), então não é hipótese.

Truncar para baixo e não arredondar porque **a direção do erro importa**: arredondar para cima cota ao lead um preço acima do real, e é essa a que vira reclamação na visita. A TEC-146 é o precedente de dinheiro errado em silêncio sobrevivendo a duas revisões.

### D12 — Sem acento na fala do agente

`"Condominio R$ 550"`, não `"Condomínio"`. O `CLAUDE.md` documenta a regra para comentários e docstrings, mas a prática do repo já a estende ao texto que o lead recebe: `TEXTO_DA_BUSCA_INCONCLUSIVA` diz *"para nao te passar informacao errada. Ja te retorno com as opcoes"* ([`turno.py:50-53`](../../../src/mobia/domain/agente/turno.py#L50)).

A ficha é o texto mais visível que o lead recebe de nós, então a convenção fica cara aqui. Ficha acentuada convivendo com fallback não-acentuado na mesma conversa é pior que uniformemente feio, então esta card segue a convenção. **Trocar a política é card própria** (ver L4).

### D13 — Vazio omite a linha, nunca esconde o imóvel

Condomínio nulo omite a linha do condomínio. `caracteristicas` vazio — 117 dos 520 do seed — omite a linha do destaque. Imóvel sem foto vira mensagem de **texto** com a ficha no corpo, caindo no caminho que já existe em vez de ganhar um ramo próprio.

O princípio é da própria RN-10.2: *"Imóvel sem foto é apresentado mesmo assim, com os dados textuais — a ausência de imagem não o esconde."*

### D14 — O teto de 600 corta a prosa, nunca a ficha

Se `"<prosa>\n\n<ficha>"` passar de 600 caracteres, a prosa é truncada na última fronteira de palavra que couber. A ficha é o conteúdo que a RN-10.1 exige; a prosa é ornamento.

O limite de legenda da Meta é 1024, então o que aperta é o 600 da RN-04.2 — hoje medido nas evals ([`evals/metricas.py:375`](../../../src/mobia/evals/metricas.py#L375)) e não imposto em `src/`. Esta card é o primeiro lugar de `src/` que o respeita por construção.

### D15 — Dois imóveis sem foto no seed

Os 520 imóveis do seed têm foto, então o caminho de texto da D13 seria invisível fora do teste. A TEC-262 é o precedente literal: ela semeou imóveis rurais para que a correção fosse observável.

`test_tem_pelo_menos_500_imoveis` usa `>= 500`, então acrescentar linhas é seguro, e `test_base_simulada.py` ganha a asserção de que existe pelo menos um imóvel sem foto — no molde de `test_os_seis_tipos_aparecem_na_base`, que a 262 escreveu.

### D16 — A linha do tempo grava as três legendas concatenadas

`executar_turno` termina em `recorder.record_agent_message(text=texto, ...)` ([`turno.py:688-708`](../../../src/mobia/domain/agente/turno.py#L688)), e esse texto volta no contexto do turno seguinte. Num turno de três fichas, o que se grava são **as três legendas concatenadas** — o que o lead de fato recebeu, sem formato inventado.

Gravar só a prosa foi recusado: a linha do tempo omitiria o que o lead viu, e o turno seguinte poderia reapresentar os mesmos três imóveis por não saber que já os mostrou. O docstring de `executar_turno` é enfático sobre memória inventada contaminar tudo o que vem depois; memória que omite é o espelho disso. Gravar prosa mais uma linha compacta com os códigos (`"[apresentados: AP-1004, ...]"`) foi recusado por inventar um formato que entra no contexto como se o agente o tivesse dito ao lead.

**Custo medido:** três legendas dão ~450 caracteres, ~112 tokens pela estimativa `len//4` de [`context/montagem.py:227`](../../../src/mobia/domain/context/montagem.py#L227), contra ~50 de um turno de texto. Não estoura nada — `contexto_teto_de_tokens` é 12000 com `contexto_headroom_de_tokens` de 1060, e `_truncar_ate_caber` derruba literais pela metade até caber, com piso de 20 (`contexto_literais_minimas`). O preço se paga em janela de memória mais curta, não em estouro.

## O fluxo do turno de apresentação

1. `gerada.candidatos` não-vazio **e** `gerada.perguntou` vazio **e** não estamos desambiguando (D4). A terceira condição é a mesma regra da segunda: no caminho de desambiguação o texto entregue é a pergunta do desambiguador, e D4 diz que pergunta adia as fichas. `gerada.perguntou` não a cobre porque fala da chamada 1, que foi descartada.
2. Os três primeiros `imovel_id`, na ordem de score → `imoveis_por_ids` (D6).
3. Menos de três voltarem: apresenta o que voltou.
4. A moderação de saída roda sobre a prosa, e **só** sobre ela — a ficha é dado do banco montado por código, e não tem texto de modelo dentro.
5. `legenda_de(ficha_1, prefixo=prosa_moderada)`, `legenda_de(ficha_2)`, `legenda_de(ficha_3)`.
6. Até três `outbound.send`, cada um com seu kind (D9), tipo `imagem` ou `texto` conforme a foto (D13).

**Se a prosa for bloqueada pela moderação, o prefixo vira `TEXTO_NEUTRO_DE_SAIDA` e as três fichas vão de todo jeito.** Suprimi-las puniria o lead por uma frase do modelo, e elas não podem ser a causa do bloqueio.

## O formato da ficha

Com `AP-1004` do seed (`preco_venda` 516464.30, condomínio 550, `churrasqueira|mobiliado|piscina|sacada`):

```
Apartamento em Lagoa da Conceicao
Lagoa da Conceicao - R$ 516.464
4 quartos - 2 vagas - 54 m2
Condominio R$ 550
Destaque: churrasqueira e mobiliado
```

Cerca de 140 caracteres, folga confortável dentro dos 600.

**Separador ASCII, e `m2` e não `m²`, pelo mesmo motivo da D12.** A disciplina do repo na fala do agente é ASCII puro, e a `descricao` gerada do seed já escreve *"Terreno de 666 m2"*. Um `·` bonito no meio de uma ficha sem acento seria inconsistência escolhida.

**Destaque são as duas primeiras características, na ordem do catálogo** — ordem armazenada e não ranking; quem quiser priorizar muda o CSV. Duas e não quatro porque cinco linhas já é o limite do que se lê numa legenda.

A redundância título/bairro é do título gerado do seed, não do formato, e não se conserta dropando o bairro — que a RN-10.1 exige.

## Fronteiras

**A invariante que decide o desenho dos módulos.** [`ferramenta_de_busca.py:3`](../../../src/mobia/domain/agente/ferramenta_de_busca.py#L3) declara: *"Este e o unico arquivo em que `domain/agente` toca `domain/catalogo`, e o acoplamento fica aqui de proposito: o agente consome o catalogo, o catalogo nao sabe que existe agente."* Um `apresentacao.py` que importasse `Imovel` a quebraria, e `turno.py` chamando `imoveis_por_ids` direto também. A rebusca da D6 fica, então, atrás do arquivo que já é a fronteira.

**`domain/agente/apresentacao.py`** (novo, puro, sem I/O e **sem nenhum import de `domain/catalogo`**): `Ficha` frozen, `legenda_de(ficha, prefixo=None)` e o formatador de reais (D11). Testável sem banco, sem chave e sem canal. Não vai para `turno.py`, que já tem 42,5K.

**`domain/agente/ferramenta_de_busca.py`**: ganha `fichas_do_catalogo(session_factory, *, ids, precos)`, que chama o repositório e monta as `Ficha`. É a única peça que vê `Imovel` e `Ficha` ao mesmo tempo, e é o arquivo cujo docstring já assume esse papel.

**`domain/catalogo/repositorio.py`**: ganha `imoveis_por_ids` (D6). O catálogo continua sem saber que existe agente.

**`domain/outbound/whatsapp.py`**: ganha o ramo de `tipo` (D8).

**`domain/agente/turno.py`**: ganha a orquestração, no molde de `_entregar_texto_fixo`.

## Emendas ao SRS

Entram como item aninhado abaixo da regra que alteram, sem reescrever o texto de 22/08/2026:

- **RN-04.2 — Emenda E-02 (TEC-162, 09/09/2026):** o teto de 2 mensagens consecutivas vale para mensagens de texto. A apresentação de imóveis da RN-10.2 pode emitir até 3 mensagens de **apresentação** por turno — mídia, ou texto quando o imóvel não tem foto. Justificativa em D2. É **E-02** porque a RN-04.2 já tem a E-01 (TEC-255), e vale notar que aquela emenda declarou a cláusula das 2 mensagens *"inalterada"* — esta é a que a altera, oito dias depois.
- **RN-10.2 — Emenda E-01 (TEC-162, 09/09/2026):** o card clicável do widget web fica com a TEC-124. Justificativa em D1. É a primeira emenda desta regra.

## Testes

**Basenames distintos entre `unit/` e `integration/`, e isto não é detalhe:** colisão aborta a coleta da suíte inteira e não aparece em execução isolada. `tests/unit/test_apresentacao.py` e `tests/integration/test_apresentacao_no_turno.py` — o segundo rima com `test_busca_no_turno.py`, que já existe.

Unitários, sem banco:
- os oito campos da RN-10.1 na legenda;
- condomínio nulo omite a linha;
- `caracteristicas` vazio omite o destaque;
- centavos truncados para baixo (D11);
- prosa longa truncada com a ficha intacta (D14);
- imóvel sem foto produz payload de texto (D13);
- adaptador: `tipo` ausente produz `type: text` — a prova da retrocompatibilidade dos três chamadores de hoje;
- adaptador: `tipo: imagem` produz `type: image` com `link` e `caption`.

Integração:
- 10 candidatos produzem exatamente 3 dispatches, com kinds `ficha_1..3`;
- `perguntou` não-vazio produz 1 texto e zero fichas (D4);
- `ficha_1` já em `outbound_dispatches` vira no-op e as outras duas entram (D9);
- `EnvioRecusado` na `ficha_2` não impede a `ficha_3` (D10);
- imóvel inativado entre a busca e a rebusca apresenta 2 (D6).

**`OutboundFake` em `tests/conftest.py` tem de aceitar payload de imagem.** Hoje `_deliver` faz `self.entregues.append(payload["texto"])` ([`conftest.py:260-263`](../../../tests/conftest.py#L260)), e o primeiro payload de imagem levanta `KeyError` — dentro do duble, num traceback que aponta para o conftest e não para a card. É a primeira coisa a consertar, antes de qualquer teste de integração da apresentação.

**Nenhuma tabela nova**, então `TABELAS` em `tests/conftest.py` não cresce e não há `TRUNCATE ... CASCADE` adicional por teste.

**`pytest -k margem_do_orcamento -s` é tarefa explícita do plano**, provando que a margem continua em 6,0. O desenho inteiro se apoia em não tocar o prompt (D3), e isso precisa de evidência.

**O aceite compara contra o baseline, não contra verde:** 1336 passed / 2 failed / 3 errors em `04b1c6a`, com as falhas na família WinError 64.

## Lacunas conhecidas

### L1 — A retentativa pode misturar o conjunto

`EnvioRetentavel` propaga, a linha vira `FAILED` e o sweeper roda o turno **inteiro** de novo — nova chamada paga, nova busca. O classificador não fixa `temperature` ([`classificador.py:432-434`](../../../src/mobia/domain/agente/classificador.py#L432) monta `kwargs` sem ela, valendo o default da API), então o filtro da segunda vez pode diferir. A `ficha_1` já entregue colide na reserva e vira no-op; as outras duas podem vir de um top-3 diferente.

**Nunca duplica, pode misturar.** A correção limpa é persistir o conjunto escolhido, que é a `Recomendacao` da RN-10.3 — a TEC-163. Fica declarada, não consertada.

**Custo achado na execução, e não coberto pelo parágrafo acima: a entrega parcial some da linha do tempo.** Se a `ficha_1` já entregou e a `ficha_2` toma o mesmo `EnvioRetentavel`, a reserva da `ficha_2` é liberada e a linha vira `FAILED` antes de `_apresentar` devolver — o que significa que `record_agent_message` nunca roda para esta tentativa, e a legenda que o lead JÁ RECEBEU (a `ficha_1`) não fica gravada em lugar nenhum. O sweeper roda o turno de novo: a reserva da `ficha_1` sobrevive e a suprime (não duplica, ver acima), mas nada no histórico registra que ela foi mostrada — o turno seguinte pode reapresentar exatamente aquele imóvel, porque a única fonte que saberia disso é a linha do tempo, e ela ficou muda para essa tentativa. `EnvioForaDaJanela` depois de uma ficha ter entrado abre o mesmo buraco, pelo mesmo motivo. Fica só no docstring de `_apresentar` (`turno.py`) desde a implementação; entra aqui porque a TEC-163 será planejada a partir deste documento, e o custo que ela precisa fechar não pode existir só em comentário de código. A `Recomendacao` da RN-10.3 é a correção de verdade: persistir o conjunto escolhido ANTES da entrega tornaria a gravação da linha do tempo independente do sucesso do envio, e o buraco fecharia junto com o de cima.

### L2 — O card web fica sem renderizador

Consequência aceita da D1. A TEC-124 herda a tarefa e a ficha agnóstica contra a qual escrevê-la.

### L3 — As URLs de foto do seed não resolvem

`https://exemplo.com/...` em todas as 520 linhas. Numa entrega real a Meta recusa a mídia, e o caminho exercitado seria o da D10 — não o da apresentação bem-sucedida. Testes usam adaptador de mentira e não sofrem disso; **uma demonstração manual contra a Cloud API sofreria**, e o sintoma pareceria bug da card. Popular fotos reais é problema do catálogo, não desta card.

### L4 — A política de acento na fala do agente

A D12 segue a convenção existente e a torna visível: três fichas por turno é muito mais texto não-acentuado chegando ao lead do que um fallback ocasional. Candidata a card própria, com o `CLAUDE.md` a atualizar junto — hoje ele documenta a regra só para comentários e docstrings.

### L5 — `test_dedup_por_message_id.py` reprova isolado

O `CLAUDE.md` afirma que os arquivos dessa família *"passam 100% em isolamento"*. Em 2026-09-09 o arquivo reprovou **3 de 5 sozinho**, com `redis.exceptions.ConnectionError ... (22, 'O nome da rede especificado nao esta mais disponivel', None, 64, None)` — o WinError 64 no Redis, não no Postgres. E os testes que reprovaram isolados **não são os mesmos** que reprovaram na suíte completa. Sem relação com esta card, mas é o que impede usar "suíte verde" como critério de aceite. Candidata a card própria.

## Fora de escopo

- RN-10.3 e RN-10.4 — registro da recomendação e realimentação pela reação do lead ([TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163)).
- Validação da resposta contra os candidatos ([TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161)).
- Indicadores de rentabilidade para investidor ([TEC-154](https://eduardodurieuxlopes.atlassian.net/browse/TEC-154)).
- O card clicável do widget web ([TEC-124](https://eduardodurieuxlopes.atlassian.net/browse/TEC-124), ver D1 e L2).
- O conjunto misturado na retentativa (L1).
